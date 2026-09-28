"""Unified Issues & Actions (CAPA) API.

One issue universe that aggregates findings/actions from every other module
(internal audit, compliance, RCSA, Shariah, assessments, incidents, external /
SBP inspections) with a full remediation lifecycle: issues, their CAPA action
lines and a chronological progress log.

Phase 2 (product review 2.3, F-12) — the rules live in ``services.issue_closure``:

* typed links to risks, controls, requirements, assets and third parties
  (``*_ids`` on write, ``GraphRef`` lists on read); raising an issue from a record also
  writes the typed link;
* ``root_cause_category_id`` beside the ``root_cause`` narrative;
* ``closed_date`` set by the server, never by a request;
* closure through ``POST /issues/{id}/validate`` (independent validator, evidence) and
  ``POST /issues/{id}/close`` (no open actions, an effective validation or an accepted
  risk; four-eyes); the edit may reopen but not close;
* every move of a due date logged, extensions of serious issues approved by a second
  person (``POST /issues/{id}/due-date-changes/{change_id}/decide``).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, or_, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.core.schema_loading import options_for, serialize_all
from app.models.enums import Severity
from app.models.issue import (
    ActionStatus,
    Issue,
    IssueAction,
    IssueDueDateChange,
    IssueSource,
    IssueStatus2,
    IssueUpdate,
)
from app.schemas.common import GraphRef, Page
from app.schemas.issue import (
    DueDateDecision,
    IssueActionCreate,
    IssueActionRead,
    IssueActionUpdate,
    IssueAssetRef,
    IssueClose,
    IssueCreate,
    IssueImport,
    IssueRead,
    IssuesSummary,
    IssueUpdateCreate,
    IssueUpdatePatch,
    IssueValidate,
)
from app.services.refs import next_reference
from app.services import audit as audit_log
from app.services import delete_guard
from app.services import drill_through
from app.services import dual_control
from app.services import issue_closure as ic
from app.services import record_workflow
from app.services import ref_fields as rf

router = APIRouter(tags=["issues"])

_READ = Depends(require("issue:read"))
_WRITE = Depends(require("issue:write"))

_CLOSED_STATES = tuple(ic.CLOSED_STATES)
_LINK_FIELDS = set(ic.LINK_ID_FIELDS)

# Phase 1 picker fields and the legacy text each one keeps in step (services/ref_fields).
ISSUE_REFS = (
    rf.user("owner_id", "owner"),
    rf.unit("business_unit_id", "business_unit"),
    rf.lookup(Issue, "category_id", "category"),
    rf.WORKFLOW_OWNER,
)
# Phase 2: picked from the root_cause_category list, no text twin (``root_cause`` stays
# the narrative) — so it is not one of the boot-backfilled free-text fields above.
ROOT_CAUSE_REFS = (rf.RefField("root_cause_category_id", None, "lookup", "root_cause_category"),)
ACTION_REFS = (rf.user("owner_id", "owner"),)
UPDATE_REFS = (rf.user("author_id", "author"),)
# Read-only people on an issue and its due-date log (set by the server, never sent).
READ_REFS = (
    rf.user("validated_by_id", None),
    rf.user("requested_by_id", None),
    rf.user("approved_by_id", None),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _approver_permissions() -> tuple[str, ...]:
    """The issue:approve-equivalent: the module's own approve permission if the catalog
    ever gains one, else ``workflow:approve`` (with ``issue:read``) — the same answer the
    record approval lifecycle uses for issues."""
    return record_workflow.required_permissions("issue", "approve")


def _can_approve(user) -> bool:
    return set(_approver_permissions()).issubset(set(getattr(user, "permission_codes", []) or []))


async def _issue_reads(db, rows) -> list[IssueRead]:
    """Read models for a page of issues, with every person/unit/lookup resolved in one
    query per kind across the issues, their actions, progress log and due-date log, and
    every linked record in one lean query per link kind."""
    items = await serialize_all(db, rows, IssueRead.model_validate)
    pairs: list = []
    for row, item in zip(rows, items):
        pairs.append((row, item))
        pairs.extend(zip(row.actions, item.actions))
        pairs.extend(zip(row.updates, item.updates))
        pairs.extend(zip(row.due_date_changes, item.due_date_changes))
    await rf.fill_refs(db, pairs, ISSUE_REFS + ROOT_CAUSE_REFS + UPDATE_REFS + READ_REFS)
    links = await ic.link_refs(db, [r.id for r in rows])
    for row, item in zip(rows, items):
        for link in ic.LINK_KINDS:
            ref_model = IssueAssetRef if link.kind == "asset" else GraphRef
            setattr(item, link.read_field, [ref_model(**x) for x in links[link.read_field].get(row.id, [])])
    return items


async def _issue_read(db, iid) -> IssueRead:
    return (await _issue_reads(db, [await _load_issue(db, iid)]))[0]


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


async def _load_issue(db, iid) -> Issue:
    obj = await db.scalar(
        select(Issue).where(Issue.id == iid, Issue.deleted.is_(False)).execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return obj


def _refuse(code: int, message: str | None) -> None:
    if message:
        raise HTTPException(status_code=code, detail=message)


def _person(user) -> str:
    return getattr(user, "full_name", "") or getattr(user, "email", "") or ""


def _log(db, obj: Issue, user, note: str, status_change: str = "") -> None:
    """A progress-log line for a lifecycle step, written as the signed-in user."""
    db.add(IssueUpdate(
        tenant_id=user.tenant_id, issue_id=obj.id, note=note, author=_person(user)[:200],
        author_id=user.id, update_date=date.today(), status_change=status_change[:64],
    ))


async def _checked_links(db, links: dict) -> dict:
    """Each sent ``*_ids`` list validated (live, this organisation); None = not sent."""
    out: dict = {}
    for link in ic.LINK_KINDS:
        ids = links.get(link.ids_field)
        out[link.ids_field] = None if ids is None else await ic.check_link_ids(db, link, ids)
    return out


async def _write_links(db, issue_id: uuid.UUID, links: dict, additions: dict) -> dict:
    """Apply sent link lists (replace) and source-link additions (add only). Returns
    ``{read_field: {"added": [...], "removed": [...]}}`` for what actually changed."""
    changes: dict = {}
    for link in ic.LINK_KINDS:
        ids = links.get(link.ids_field)
        if ids is not None:
            added, removed = await ic.write_links(db, issue_id, link, ids)
        elif link.ids_field in additions:
            added, removed = await ic.write_links(db, issue_id, link, additions[link.ids_field], replace=False)
        else:
            continue
        if added or removed:
            changes[link.read_field] = {"added": sorted(map(str, added)), "removed": sorted(map(str, removed))}
    return changes


def _controls_touched(changes: dict) -> list[uuid.UUID]:
    moved = changes.get("controls") or {}
    return [uuid.UUID(x) for x in (*moved.get("added", []), *moved.get("removed", []))]


async def _enforce_four_eyes(db, obj: Issue, user, action: str) -> None:
    """Dual control ``(issue, <action>)``: whoever raised the issue — and, for
    validation, whoever owns its remediation — cannot take the step themselves."""
    required, rule = await dual_control.dual_control_required(db, "issue", action)
    if not required:
        return
    raiser = await dual_control.maker_of(db, "issue", obj.id, record=obj)
    if action == "validate":
        _refuse(403, ic.validator_conflict(user.id, obj.owner_id, raiser))
    elif raiser is not None and raiser == user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Segregation of duties: you raised this issue, so someone else must close it.",
        )
    await dual_control.enforce_checker_role(db, rule, module="issue", action=action,
                                            checker_id=user.id, maker_id=raiser)


_DUE_DATE_MOVES = (
    select(func.count(IssueDueDateChange.id))
    .where(
        IssueDueDateChange.issue_id == Issue.id,
        IssueDueDateChange.status == ic.APPROVED,
        IssueDueDateChange.old_due_date.is_not(None),
    )
    .correlate(Issue)
    .scalar_subquery()
)

_ISSUE_SORTABLE = {
    "reference": Issue.reference,
    "title": Issue.title,
    "severity": Issue.severity,
    "status": Issue.status,
    "source_type": Issue.source_type,
    "owner": Issue.owner,
    "due_date": Issue.due_date,
    "identified_date": Issue.identified_date,
    "closed_date": Issue.closed_date,
    "due_date_moves": _DUE_DATE_MOVES,
    "created_at": Issue.created_at,
}


def _linked_to(kind: str, record_id: uuid.UUID):
    """Issues linked to this record by the typed link — or, for issues not yet
    backfilled, by their bare ``source_id``."""
    link = ic.LINK_BY_KIND[kind]
    return or_(
        Issue.id.in_(select(link.table.c.issue_id).where(link.table.c[link.column] == record_id)),
        Issue.source_id == record_id,
    )


# ================================================================== issues ===
@router.get("/issues", response_model=Page[IssueRead], dependencies=[_READ])
async def list_issues(
    db: DbSession,
    search: Annotated[str | None, Query()] = None,
    status_filter: Annotated[IssueStatus2 | None, Query(alias="status")] = None,
    source_type: Annotated[IssueSource | None, Query()] = None,
    source_id: Annotated[uuid.UUID | None, Query()] = None,
    risk_id: Annotated[uuid.UUID | None, Query(description="Issues linked to this risk")] = None,
    control_id: Annotated[uuid.UUID | None, Query(description="Issues linked to this control")] = None,
    requirement_id: Annotated[uuid.UUID | None, Query(description="Issues linked to this requirement")] = None,
    asset_id: Annotated[uuid.UUID | None, Query(description="Issues linked to this asset")] = None,
    vendor_id: Annotated[uuid.UUID | None, Query(description="Issues linked to this third party")] = None,
    linked_id: Annotated[
        uuid.UUID | None,
        Query(description="Issues linked to this record by any link kind, or raised from it (source_id)"),
    ] = None,
    severity: Annotated[Severity | None, Query()] = None,
    overdue: Annotated[bool | None, Query()] = None,
    owner_id: Annotated[uuid.UUID | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
    root_cause_category_id: Annotated[uuid.UUID | None, Query()] = None,
    business_unit_id: Annotated[uuid.UUID | None, Query()] = None,
    regulator_related: Annotated[bool | None, Query()] = None,
    repeat_finding: Annotated[bool | None, Query()] = None,
    min_due_date_moves: Annotated[
        int | None, Query(ge=0, description="Issues whose due date moved at least this many times")
    ] = None,
    due_date_change_pending: Annotated[
        bool | None, Query(description="Issues with a due-date extension awaiting approval")
    ] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[IssueRead]:
    stmt: Select = select(Issue).where(Issue.deleted.is_(False))
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Issue.title.ilike(like),
                Issue.description.ilike(like),
                Issue.reference.ilike(like),
                Issue.source_reference.ilike(like),
                Issue.owner.ilike(like),
            )
        )
    if status_filter is not None:
        stmt = stmt.where(Issue.status == status_filter)
    if source_type is not None:
        stmt = stmt.where(Issue.source_type == source_type)
    if source_id is not None:
        stmt = stmt.where(Issue.source_id == source_id)
    for kind, record_id in (
        ("risk", risk_id), ("control", control_id), ("requirement", requirement_id),
        ("asset", asset_id), ("vendor", vendor_id),
    ):
        if record_id is not None:
            stmt = stmt.where(_linked_to(kind, record_id))
    if linked_id is not None:
        stmt = stmt.where(or_(*[_linked_to(k.kind, linked_id) for k in ic.LINK_KINDS]))
    if severity is not None:
        stmt = stmt.where(Issue.severity == severity)
    if owner_id is not None:
        stmt = stmt.where(Issue.owner_id == owner_id)
    if category_id is not None:
        stmt = stmt.where(Issue.category_id == category_id)
    if root_cause_category_id is not None:
        stmt = stmt.where(Issue.root_cause_category_id == root_cause_category_id)
    if business_unit_id is not None:
        stmt = stmt.where(Issue.business_unit_id == business_unit_id)
    if regulator_related is not None:
        stmt = stmt.where(Issue.regulator_related.is_(regulator_related))
    if repeat_finding is not None:
        stmt = stmt.where(Issue.repeat_finding.is_(repeat_finding))
    if min_due_date_moves:
        stmt = stmt.where(_DUE_DATE_MOVES >= min_due_date_moves)
    if due_date_change_pending is not None:
        pending = Issue.id.in_(
            select(IssueDueDateChange.issue_id).where(IssueDueDateChange.status == ic.PENDING)
        )
        stmt = stmt.where(pending if due_date_change_pending else ~pending)
    if overdue:
        # The dashboard's "issues past due" counts with this same predicate.
        stmt = stmt.where(drill_through.issue_overdue(date.today()))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _ISSUE_SORTABLE, default=Issue.created_at)
    else:
        stmt = stmt.order_by(Issue.created_at.desc())
    # Load what the list serialises (``schema_loading``), not every link of every link.
    loads = options_for(Issue, IssueRead)
    rows = (
        await db.scalars(stmt.options(*loads).limit(limit).offset(offset))
    ).all()
    return Page(items=await _issue_reads(db, rows), total=total, limit=limit, offset=offset)


@router.post("/issues", response_model=IssueRead, status_code=201, dependencies=[_WRITE])
async def create_issue(body: IssueCreate, db: DbSession, user: CurrentUser) -> IssueRead:
    _refuse(422, ic.create_status_refusal(body.status))
    data = body.model_dump(exclude=_LINK_FIELDS | {"closed_date"})
    if data.get("identified_date") is None:
        data["identified_date"] = date.today()
    await rf.apply_refs(db, Issue, data, ISSUE_REFS + ROOT_CAUSE_REFS)
    links = await _checked_links(db, {f: getattr(body, f) for f in ic.LINK_ID_FIELDS})
    obj = Issue(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, Issue, "ISS")
    db.add(obj)
    await db.flush()
    # Raised from a record (RecordIssues sends source_id): the link is typed, not guessed.
    links, additions = ic.with_source_link(links, await ic.source_kind(db, obj.source_id), obj.source_id)
    link_changes = await _write_links(db, obj.id, links, additions)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="create", entity_type="issue", entity_id=obj.id,
        summary=f"Raised issue {obj.reference}: {obj.title}",
        changes={"links": link_changes} if link_changes else None,
    )
    # An open issue on a control holds its effectiveness down until it closes.
    await ic.recompute_controls(db, _controls_touched(link_changes), reason=f"{obj.reference} raised")
    return await _issue_read(db, obj.id)


async def import_issue(*, body: IssueImport, db, user) -> IssueRead:
    """CSV import: the register's own create, plus the closed history a bank migrating
    from another tool brings with it.

    A row may arrive closed (closed / remediated / risk accepted) with its closed date:
    the issue is created open through :func:`create_issue` — every rule applies — and
    then set to the imported state with an ``import_state`` audit entry. Bringing a
    record in closed is a claim that somebody closed it, so, as with an imported
    approval state, only a person who could approve issues may make it in bulk."""
    target = body.status
    closing = ic.is_closed(target)
    if closing and not _can_approve(user):
        raise ValueError(
            f"Importing an issue as '{target.value}' needs approval rights "
            f"({', '.join(_approver_permissions())}). Import it open, or have someone who can "
            "approve issues run the import."
        )
    fields = body.model_dump(exclude={"closed_date"})
    if closing:
        fields["status"] = IssueStatus2.open
    created = await create_issue(body=IssueCreate.model_validate(fields), db=db, user=user)
    if not closing:
        return created
    obj = await _load_issue(db, created.id)
    obj.status = target
    obj.closed_date = body.closed_date or date.today()
    await db.flush()
    await audit_log.record(
        db, actor=user, action="import_state", entity_type="issue", entity_id=obj.id,
        summary=f"Imported {obj.reference} as {target.value} (closure carried over from the source system)",
        changes={"status": target.value, "closed_date": obj.closed_date.isoformat()},
    )
    await ic.recompute_controls(db, await ic.linked_ids(db, obj.id, "control"), reason=f"{obj.reference} imported closed")
    return await _issue_read(db, obj.id)


@router.get("/issues/{iid}", response_model=IssueRead, dependencies=[_READ])
async def get_issue(iid: uuid.UUID, db: DbSession) -> IssueRead:
    return await _issue_read(db, iid)


def _due_date_change(obj: Issue, data: dict, reason: str, user) -> IssueDueDateChange | None:
    """The due-date log row this edit writes (and whether the date waits), or None.

    Pops ``due_date`` from ``data`` when the date must not move yet (pending approval)
    or did not change. Raises 422 without a reason and 409 while another extension is
    still waiting."""
    if "due_date" not in data:
        return None
    new = data["due_date"]
    old = obj.due_date
    if new == old:
        data.pop("due_date")
        return None
    if not ic.is_due_date_move(old, new):
        return None  # the first date on an issue is planning, not a move
    if not reason:
        raise HTTPException(
            status_code=422,
            detail="due_date_reason: say why the due date is moving — every change of an agreed date is logged.",
        )
    if any(c.status == ic.PENDING for c in obj.due_date_changes):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A due-date change is already awaiting approval on this issue. Have it approved or "
            "rejected before asking for another.",
        )
    regulator = bool(obj.regulator_related) or bool(data.get("regulator_related"))
    severities = {obj.severity, data.get("severity") or obj.severity}
    waits = any(
        ic.needs_extension_approval(old, new, regulator_related=regulator, severity=s) for s in severities
    )
    if waits:
        data.pop("due_date")
    return IssueDueDateChange(
        tenant_id=user.tenant_id, issue_id=obj.id, old_due_date=old, new_due_date=new,
        reason=reason, status=ic.PENDING if waits else ic.APPROVED,
        requested_by_id=user.id, approved_at=None if waits else _now(),
    )


def _clear_validation(obj: Issue) -> None:
    obj.validated_by_id = None
    obj.validated_at = None
    obj.validation_result = None
    obj.validation_note = ""


@router.patch("/issues/{iid}", response_model=IssueRead, dependencies=[_WRITE])
async def update_issue(iid: uuid.UUID, body: IssueUpdatePatch, db: DbSession, user: CurrentUser) -> IssueRead:
    obj = await _load_issue(db, iid)
    prev_status = obj.status
    data = body.model_dump(exclude_unset=True)
    sent_links = {f: data.pop(f) for f in ic.LINK_ID_FIELDS if f in data}
    reason = (data.pop("due_date_reason", None) or "").strip()
    if data.get("status") is None:
        data.pop("status", None)
    _refuse(422, ic.edit_status_refusal(prev_status, data.get("status")))
    change = _due_date_change(obj, data, reason, user)
    if change is not None and change.status == ic.PENDING:
        # Asking for the later date is the maker's step (a rule's maker role).
        await dual_control.enforce_maker_role(db, module="issue", action="extend_due_date", maker_id=user.id)
    links = await _checked_links(db, sent_links)
    await rf.apply_refs(db, Issue, data, ISSUE_REFS + ROOT_CAUSE_REFS, record=obj)
    source_moved = "source_id" in data and data["source_id"] != obj.source_id
    changed = sorted(k for k, v in data.items() if getattr(obj, k, None) != v)
    for k, v in data.items():
        setattr(obj, k, v)
    reopened = ic.is_reopen(prev_status, obj.status)
    if reopened:
        # A reopened issue must be validated afresh before it can close again.
        obj.closed_date = None
        _clear_validation(obj)
        _log(db, obj, user, "Reopened", f"{prev_status.value} → {obj.status.value}")
    if change is not None:
        db.add(change)
    await db.flush()

    additions: dict = {}
    if source_moved and obj.source_id is not None:
        links, additions = ic.with_source_link(links, await ic.source_kind(db, obj.source_id), obj.source_id)
    link_changes = await _write_links(db, obj.id, links, additions)
    await db.flush()

    audit_changes: dict = {}
    if changed:
        audit_changes["fields"] = changed
    if link_changes:
        audit_changes["links"] = link_changes
    if changed or link_changes:
        await audit_log.record(
            db, actor=user, action="update", entity_type="issue", entity_id=obj.id,
            summary=f"Updated issue {obj.reference}"
            + (f": {', '.join(changed + sorted(link_changes))}" if changed or link_changes else ""),
            changes=audit_changes,
        )
    if change is not None:
        waiting = change.status == ic.PENDING
        await audit_log.record(
            db, actor=user, action="due_date_change", entity_type="issue", entity_id=obj.id,
            summary=(
                f"Asked to move {obj.reference} due date {change.old_due_date} → {change.new_due_date or 'none'}"
                + (" (awaiting approval)" if waiting else "")
            ),
            changes={
                "old_due_date": str(change.old_due_date) if change.old_due_date else None,
                "new_due_date": str(change.new_due_date) if change.new_due_date else None,
                "reason": change.reason, "status": change.status,
            },
        )
    if reopened:
        await audit_log.record(
            db, actor=user, action="reopen", entity_type="issue", entity_id=obj.id,
            summary=f"Reopened issue {obj.reference} ({prev_status.value} → {obj.status.value}); validation cleared",
        )
    touched = _controls_touched(link_changes)
    if reopened:
        touched += await ic.linked_ids(db, obj.id, "control")
    await ic.recompute_controls(
        db, touched, reason=f"{obj.reference} reopened" if reopened else f"{obj.reference} links changed"
    )
    return await _issue_read(db, iid)


# ======================================================== validation & closure ===
@router.post(
    "/issues/{iid}/validate", response_model=IssueRead, dependencies=[_WRITE],
    summary="Record an independent validation of the remediation (effective / not effective)",
)
async def validate_issue(iid: uuid.UUID, body: IssueValidate, db: DbSession, user: CurrentUser) -> IssueRead:
    obj = await _load_issue(db, iid)
    attachments = await ic.attachment_count(db, obj.id) if body.result == ic.EFFECTIVE else 0
    _refuse(409, ic.validation_refusal(
        status=obj.status, result=body.result, attachments=attachments, note=body.note,
    ))
    # Dual control (issue, validate): not the owner, not whoever raised it.
    await _enforce_four_eyes(db, obj, user, "validate")
    prev = obj.status
    obj.validated_by_id = user.id
    obj.validated_at = _now()
    obj.validation_result = body.result
    obj.validation_note = body.note.strip()
    if body.result == ic.NOT_EFFECTIVE:
        obj.status = IssueStatus2.in_progress  # back to the owner
    moved = f"{prev.value} → {obj.status.value}" if obj.status != prev else ""
    _log(db, obj, user, f"Validation: {body.result.replace('_', ' ')} — {obj.validation_note}", moved)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="validate", entity_type="issue", entity_id=obj.id,
        summary=f"Validated issue {obj.reference} as {body.result.replace('_', ' ')}",
        changes={"result": body.result, "note": obj.validation_note, "evidence_items": attachments},
    )
    return await _issue_read(db, iid)


@router.post(
    "/issues/{iid}/close", response_model=IssueRead, dependencies=[_WRITE],
    summary="Close an issue (closed / remediated / risk accepted)",
)
async def close_issue(iid: uuid.UUID, body: IssueClose, db: DbSession, user: CurrentUser) -> IssueRead:
    obj = await _load_issue(db, iid)
    target = IssueStatus2(body.status)
    accepted = False
    if target == IssueStatus2.risk_accepted:
        accepted = await ic.has_approved_acceptance(db, await ic.linked_ids(db, obj.id, "risk"))
    _refuse(409, ic.close_refusal(
        target=target, current=obj.status, open_actions=ic.open_action_titles(obj.actions),
        validation_result=obj.validation_result, has_approved_acceptance=accepted,
        note=body.note, can_approve=_can_approve(user),
    ))
    # Dual control (issue, close): whoever raised the issue cannot also retire it.
    await _enforce_four_eyes(db, obj, user, "close")
    prev = obj.status
    obj.status = target
    obj.closed_date = ic.closed_date_after(prev, target, obj.closed_date, date.today())
    basis = (
        "validation" if target != IssueStatus2.risk_accepted
        else "risk_acceptance" if accepted else "approver_note"
    )
    note = body.note.strip()
    _log(db, obj, user, f"Closed as {target.value.replace('_', ' ')}" + (f" — {note}" if note else ""),
         f"{prev.value} → {target.value}")
    await db.flush()
    await audit_log.record(
        db, actor=user, action="close", entity_type="issue", entity_id=obj.id,
        summary=f"Closed issue {obj.reference} as {target.value}",
        changes={"status": target.value, "note": note, "basis": basis},
    )
    await ic.recompute_controls(db, await ic.linked_ids(db, obj.id, "control"), reason=f"{obj.reference} closed")
    return await _issue_read(db, iid)


@router.post(
    "/issues/{iid}/due-date-changes/{change_id}/decide", response_model=IssueRead, dependencies=[_READ],
    summary="Approve or reject a due-date extension awaiting approval",
)
async def decide_due_date_change(
    iid: uuid.UUID, change_id: uuid.UUID, body: DueDateDecision, db: DbSession, user: CurrentUser
) -> IssueRead:
    needed = _approver_permissions()
    if not _can_approve(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires permission(s): {', '.join(needed)}"
        )
    obj = await _load_issue(db, iid)
    change = next((c for c in obj.due_date_changes if c.id == change_id), None)
    if change is None:
        raise HTTPException(status_code=404, detail="Due-date change not found")
    if change.status != ic.PENDING:
        raise HTTPException(status_code=409, detail=f"This due-date change was already {change.status}.")
    # Dual control (issue, extend_due_date): the person who asked cannot approve it.
    await dual_control.enforce_maker_checker(
        db, module="issue", action="extend_due_date",
        maker_id=change.requested_by_id, checker_id=user.id, subject="due-date extension",
    )
    change.status = ic.APPROVED if body.approve else ic.REJECTED
    change.approved_by_id = user.id
    change.approved_at = _now()
    if body.approve:
        obj.due_date = change.new_due_date
    verdict = "approved" if body.approve else "rejected"
    note = body.note.strip()
    _log(db, obj, user,
         f"Due-date change {change.old_due_date} → {change.new_due_date or 'none'} {verdict}"
         + (f" — {note}" if note else ""))
    await db.flush()
    await audit_log.record(
        db, actor=user, action="decide", entity_type="issue", entity_id=obj.id,
        summary=f"{verdict.capitalize()} due-date change on {obj.reference} "
        f"({change.old_due_date} → {change.new_due_date or 'none'})",
        changes={"change_id": str(change.id), "approve": body.approve, "note": note},
    )
    return await _issue_read(db, iid)


@router.delete("/issues/{iid}", status_code=204, dependencies=[_WRITE])
async def delete_issue(iid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_issue(db, iid)
    # (issue, delete) is a dual-control action: whoever raised the issue cannot also
    # make it disappear from the register.
    await delete_guard.enforce(db, entity_type="issue", record=obj, user=user, label="issue")
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit_log.record(
        db, actor=user, action="delete", entity_type="issue", entity_id=obj.id,
        summary=f"Archived issue {obj.reference}: {obj.title}",
    )
    # An archived issue no longer holds its controls down.
    await ic.recompute_controls(db, await ic.linked_ids(db, obj.id, "control"), reason=f"{obj.reference} archived")


# ============================================================= CAPA actions ===
@router.post("/issues/{iid}/actions", response_model=IssueRead, status_code=201, dependencies=[_WRITE])
async def add_action(iid: uuid.UUID, body: IssueActionCreate, db: DbSession, user: CurrentUser) -> IssueRead:
    obj = await _load_issue(db, iid)
    data = body.model_dump()
    await rf.apply_refs(db, IssueAction, data, ACTION_REFS)
    db.add(IssueAction(tenant_id=user.tenant_id, issue_id=iid, **data))
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="issue", entity_id=iid,
        summary=f"Added action '{body.title}' to {getattr(obj, 'reference', '') or 'issue'}",
    )
    return await _issue_read(db, iid)


@router.patch("/issue-actions/{line_id}", response_model=IssueActionRead, dependencies=[_WRITE])
async def update_action(
    line_id: uuid.UUID, body: IssueActionUpdate, db: DbSession, user: CurrentUser
) -> IssueActionRead:
    obj = await _get(db, IssueAction, line_id, "Action")
    data = body.model_dump(exclude_unset=True)
    await rf.apply_refs(db, IssueAction, data, ACTION_REFS, record=obj)
    changed = sorted(k for k, v in data.items() if getattr(obj, k, None) != v)
    for k, v in data.items():
        setattr(obj, k, v)
    # Auto-stamp completion when an action is marked done.
    if obj.status == ActionStatus.done and obj.completed_date is None:
        obj.completed_date = date.today()
    await db.flush()
    if changed:
        await audit_log.record(
            db, actor=user, action="update", entity_type="issue", entity_id=obj.issue_id,
            summary=f"Updated action '{obj.title}': {', '.join(changed)}",
            changes={"action_id": str(obj.id), "fields": changed, "status": obj.status.value},
        )
    read = IssueActionRead.model_validate(obj)
    await rf.fill_refs(db, [(obj, read)], ACTION_REFS)
    return read


@router.delete("/issue-actions/{line_id}", status_code=204, dependencies=[_WRITE])
async def delete_action(line_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    # IssueAction has no soft-delete envelope (no ``deleted`` column), so this stays a
    # hard delete until the model gains one; the trail records what was removed.
    obj = await db.scalar(select(IssueAction).where(IssueAction.id == line_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    await audit_log.record(
        db, actor=user, action="update", entity_type="issue", entity_id=obj.issue_id,
        summary=f"Removed action '{obj.title}' (owner {obj.owner or 'n/a'})",
        changes={"action_removed": {"id": str(obj.id), "title": obj.title, "status": obj.status.value}},
    )
    await db.delete(obj)


# =========================================================== progress updates ===
@router.post("/issues/{iid}/updates", response_model=IssueRead, status_code=201, dependencies=[_WRITE])
async def add_update(iid: uuid.UUID, body: IssueUpdateCreate, db: DbSession, user: CurrentUser) -> IssueRead:
    obj = await _load_issue(db, iid)
    data = body.model_dump()
    if data.get("update_date") is None:
        data["update_date"] = date.today()
    if data.get("author_id") is None and not (data.get("author") or "").strip():
        data["author_id"] = user.id  # the progress log is written by whoever is signed in
    await rf.apply_refs(db, IssueUpdate, data, UPDATE_REFS)
    db.add(IssueUpdate(tenant_id=user.tenant_id, issue_id=iid, **data))
    await db.flush()
    await audit_log.record(
        db, actor=user, action="update", entity_type="issue", entity_id=iid,
        summary=f"Logged progress on {getattr(obj, 'reference', '') or 'issue'}",
    )
    return await _issue_read(db, iid)


# ================================================================== summary ===
@router.get("/issues-summary", response_model=IssuesSummary, dependencies=[_READ],
            summary="Issue register roll-up (status / source / overdue / regulator)")
async def issues_summary(db: DbSession) -> IssuesSummary:
    issues = (await db.scalars(select(Issue).where(Issue.deleted.is_(False)))).all()
    by_status: dict[str, int] = defaultdict(int)
    by_source: dict[str, int] = defaultdict(int)
    total_open = overdue_count = repeat_count = regulator_open = pending_changes = 0
    for i in issues:
        by_status[i.status.value] += 1
        by_source[i.source_type.value] += 1
        is_open = i.status not in _CLOSED_STATES
        if is_open:
            total_open += 1
        if i.is_overdue:
            overdue_count += 1
        if i.repeat_finding:
            repeat_count += 1
        if i.regulator_related and is_open:
            regulator_open += 1
        if any(c.status == ic.PENDING for c in i.due_date_changes):
            pending_changes += 1
    return IssuesSummary(
        by_status=dict(by_status),
        by_source_type=dict(by_source),
        total=len(issues),
        total_open=total_open,
        overdue_count=overdue_count,
        repeat_finding_count=repeat_count,
        regulator_related_open=regulator_open,
        due_date_changes_pending=pending_changes,
    )
