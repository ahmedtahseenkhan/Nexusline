"""My Work — everything waiting for one person, from every register, in one answer.

``GET /my/work`` (``api/v1/my_work.py``) returns sections, one per kind of work, each
with its count, its items overdue first, and a deep link per item. The kinds:

* **Decisions waiting for you** — approval requests you may decide (you hold
  ``workflow:approve``, didn't raise the request, haven't voted, and it is addressed to
  you, a role you hold, or to no one in particular: the same routing the notification
  feed uses); records submitted for review in the lifecycle that you may approve (the
  module's approve permission; not the maker or the submitter while four-eyes applies;
  not while an approval route owns the decision); control tests pending an independent
  review you may give (``control:test``; you didn't perform, record or edit the test);
  issue fixes ready for validation (every action done; not the owner or whoever raised
  it); issue due-date extensions awaiting approval (not the person who asked).
* **Things you own that are due** — within :data:`HORIZON_DAYS` or overdue: risk
  treatment actions, issue actions and issues you own; incidents assigned to you;
  control tests on controls you own or operate; tests a reviewer returned to you; risk
  reviews; periodic reviews and attestations of records you own (policies, third
  parties, and every record type the attestation panel covers); KRI readings you supply
  (the next reading is due one ``frequency`` after the last one, within
  :data:`KRI_HORIZON_DAYS`); actions on open RCSAs you own.
* **Policies to acknowledge** — published policies whose roles include one of yours (or
  that name no role), that you haven't acknowledged.

Every kind is one query on indexed columns (owner / assignee / status / date), selecting
columns rather than whole records so no record's eager relationships load; the four-eyes
filters add one query on the audit trail each. A section shows at most
:data:`MAX_ITEMS` items; ``count`` is the full number (up to :data:`ROW_CAP`).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import String, Uuid, and_, cast, exists, false, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.my_work import MyWorkItem, MyWorkRead, MyWorkSection, TreatmentActionDone

#: "Due soon" looks this many days ahead.
HORIZON_DAYS = 14
#: KRI readings fall due every cycle; only the next few days are "due".
KRI_HORIZON_DAYS = 3
#: Items shown per section.
MAX_ITEMS = 50
#: Rows read per kind (a section's count stops here).
ROW_CAP = 500

ACK = "acknowledge"
MARK_DONE = "mark_done"

#: (kind, label, hint), in the order the page shows them: decisions first.
KINDS: tuple[tuple[str, str, str], ...] = (
    ("approval", "Approvals waiting for you",
     "Requests you can approve or reject — never ones you raised."),
    ("record_review", "Records submitted for your review",
     "Records sent for review in their approval lifecycle that you may approve or return."),
    ("test_review", "Control tests to review",
     "Tests pending an independent review; you didn't perform, record or edit them."),
    ("issue_validation", "Issue fixes to validate",
     "Every action is done; an independent validator must confirm the fix works."),
    ("due_date_change", "Due-date extensions to approve",
     "Later due dates on serious issues, asked for by someone else."),
    ("treatment_action", "Your risk treatment actions",
     "Open actions you own, overdue or due in the next two weeks."),
    ("issue_action", "Your issue actions",
     "Open corrective and preventive actions you own, overdue or due soon."),
    ("issue", "Issues you own", "Open issues past or near their agreed due date."),
    ("incident", "Incidents assigned to you", "Open incidents; the date is the turnaround-time deadline."),
    ("control_test", "Control tests due", "Controls you own or operate whose next test is due."),
    ("test_returned", "Tests returned to you", "A reviewer sent your test back — fix it and resubmit."),
    ("risk_review", "Risk reviews due", "Risks you own whose review date is near or past."),
    ("attestation", "Reviews and attestations due",
     "Records you own whose periodic review or attestation is due."),
    ("kri_measurement", "KRI readings due", "KRIs you supply data for whose next reading is due."),
    ("rcsa_action", "RCSA actions assigned to you", "Actions on open RCSAs where you are the action owner."),
    ("policy_ack", "Policies to acknowledge",
     "Published policies that apply to your roles and that you haven't acknowledged."),
)
KIND_LABELS: dict[str, str] = {k: label for k, label, _hint in KINDS}


# ================================================================= pure rules ===
def due_flags(due: date | None, today: date, horizon: date) -> tuple[bool, bool]:
    """``(overdue, due_soon)`` for a due date. Pure."""
    if due is None:
        return False, False
    if due < today:
        return True, False
    return False, due <= horizon


def item(kind: str, today: date, horizon: date, *, due: date | None = None, **fields: Any) -> MyWorkItem:
    overdue, soon = due_flags(due, today, horizon)
    return MyWorkItem(kind=kind, due_date=due, overdue=overdue, due_soon=soon, **fields)


def sort_items(items: Iterable[MyWorkItem]) -> list[MyWorkItem]:
    """Overdue first, then by due date (undated last), then by title. Pure."""
    return sorted(
        items,
        key=lambda i: (not i.overdue, i.due_date is None, i.due_date or date.max, (i.title or "").lower()),
    )


def build_section(kind: str, items: Sequence[MyWorkItem], *, max_items: int = MAX_ITEMS) -> MyWorkSection:
    ordered = sort_items(items)
    label, hint = next(((label, hint) for k, label, hint in KINDS if k == kind), (kind, ""))
    return MyWorkSection(
        kind=kind, label=label, hint=hint, count=len(ordered),
        overdue=sum(1 for i in ordered if i.overdue),
        items=ordered[:max_items], truncated=len(ordered) > max_items,
    )


def assemble(user_id: uuid.UUID, today: date, found: dict[str, list[MyWorkItem]]) -> MyWorkRead:
    """The response from each kind's items, in :data:`KINDS` order. Pure."""
    sections = [build_section(kind, found.get(kind, [])) for kind, _l, _h in KINDS]
    return MyWorkRead(
        user_id=user_id, as_of=today, horizon_days=HORIZON_DAYS,
        total=sum(s.count for s in sections), overdue=sum(s.overdue for s in sections),
        counts={s.kind: s.count for s in sections}, sections=sections,
    )


def kri_next_due(frequency: Any, last_measured: date | None, today: date) -> date | None:
    """When a KRI's next reading is due: one cycle after the last reading; today when
    it has never been measured; never for frequency ``none``. Pure."""
    from app.models.enums import ReviewFrequency
    from app.services.risk_scoring import next_review_date

    freq = frequency if isinstance(frequency, ReviewFrequency) else ReviewFrequency(getattr(frequency, "value", frequency))
    if freq == ReviewFrequency.none:
        return None
    if last_measured is None:
        return today
    return next_review_date(freq, last_measured)


def decided_by_others_only(user_id: Any, makers: Iterable[Any], *, required: bool) -> bool:
    """Whether four-eyes lets this user take the decision: always when dual control
    doesn't apply, otherwise only when they are none of the makers. Pure."""
    return not required or user_id not in set(m for m in makers if m is not None)


def makers_from_trail(rows: Iterable[tuple[Any, Any, str, Any, Any]]) -> tuple[dict, dict]:
    """From ``(entity_type, entity_id, action, actor_id, created_at)`` audit rows:
    ``({(type, id): earliest creator}, {(type, id): latest submitter})``. Pure."""
    created: dict = {}
    submitted: dict = {}
    for etype, eid, action, actor, at in sorted(rows, key=lambda r: (r[4] is None, r[4] or datetime.min.replace(tzinfo=timezone.utc))):
        if actor is None:
            continue
        key = (etype, eid)
        if action == "create":
            created.setdefault(key, actor)
        elif action == "workflow_submit":
            submitted[key] = actor
    return created, submitted


def policy_ack_applies(policy_role_ids: Iterable[Any], my_role_ids: Iterable[Any]) -> bool:
    """A policy asks the user to acknowledge it when it names one of their roles, or
    names no role at all (every active user). Pure — the rule the SQL applies."""
    policy_roles = set(policy_role_ids)
    return not policy_roles or bool(policy_roles & set(my_role_ids))


def can_mark_done(action: Any, user_id: Any, permissions: Iterable[str]) -> str | None:
    """Why this user can't mark this treatment action done, or None. Pure. The action's
    owner may (it is their own report of their own work); so may anyone who can edit
    risks."""
    if getattr(action, "owner_id", None) != user_id and "risk:write" not in set(permissions):
        return "Only the action's owner, or someone who can edit risks, can mark it done."
    if action.status == "cancelled":
        return "This action was cancelled; reopen it on the risk if it is needed again."
    return None


# ================================================================ the context ===
@dataclass
class Ctx:
    user_id: uuid.UUID
    email: str
    permissions: set[str]
    role_names: set[str]
    role_ids: set[uuid.UUID]
    today: date
    horizon: date
    directory: Any = None
    modules_off: set[str] = field(default_factory=set)

    def holds(self, *codes: str) -> bool:
        return set(codes) <= self.permissions

    def mk(self, kind: str, *, due: date | None = None, **fields: Any) -> MyWorkItem:
        return item(kind, self.today, self.horizon, due=due, **fields)


async def _module_off(db: AsyncSession) -> set[str]:
    """Licensable modules this organisation can't use (licence, deploy config or its own
    choice); their work isn't listed because their pages are locked."""
    from app.models.settings import TenantSettings
    from app.services import modules

    choice = await db.scalar(select(TenantSettings.enabled_modules))
    off = set()
    for key in ("operational_risk",):
        if not modules.is_enabled(key) or (isinstance(choice, list) and key not in choice):
            off.add(key)
    return off


def _link(base: str, entity_id: Any) -> str:
    from app.services.notifications import with_id

    return with_id(base, entity_id)


# ================================================================== decisions ===
async def approvals_waiting(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.approval import ApprovalAction, ApprovalRequest
    from app.models.enums import ApprovalStatus
    from app.services.notifications import (
        APPROVE_PERMISSION, ROLE, USER, approval_recipients, approval_refusal,
    )

    if not ctx.holds(APPROVE_PERMISSION):
        return []
    voted = exists().where(ApprovalAction.request_id == ApprovalRequest.id, ApprovalAction.actor_id == ctx.user_id)
    rows = (
        await db.scalars(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == ApprovalStatus.pending, ~voted)
            .order_by(ApprovalRequest.created_at)
            .limit(ROW_CAP)
        )
    ).all()
    out = []
    for ap in rows:
        addressed = any(
            (kind == USER and value == ctx.user_id) or (kind == ROLE and value in ctx.role_names)
            for kind, value in approval_recipients(ap, ctx.directory)
        )
        if not addressed or approval_refusal(
            ap, user_id=ctx.user_id, email=ctx.email, permissions=ctx.permissions, voted_ids=(),
        ) is not None:
            continue
        parts = []
        if ap.entity_label:
            parts.append(f"About {ap.entity_label}")
        if ap.requested_by_email:
            parts.append(f"raised by {ap.requested_by_email}")
        if (ap.required_approvals or 1) > 1:
            parts.append(f"{ap.required_approvals} approvals needed")
        out.append(ctx.mk(
            "approval", due=ap.due_date, id=ap.id, title=ap.title, reference=ap.reference or "",
            subtitle=" · ".join(parts), link=_link("/approvals", ap.id),
            entity_type="approval", entity_id=ap.id,
        ))
    return out


def review_types(permissions: Iterable[str]) -> list[tuple[str, type]]:
    """Registered record types with an approval lifecycle that this user may approve."""
    from app.services import record_registry, record_workflow
    from app.services.entity_types import ENTITY_TYPES

    held = set(permissions)
    out: list[tuple[str, type]] = []
    seen: set[type] = set()
    for etype in ENTITY_TYPES:
        model = record_registry.model_for(etype)
        if model is None or model in seen or not record_registry.has_workflow(model):
            continue
        try:
            needed = record_workflow.required_permissions(etype, "approve")
        except HTTPException:
            continue
        if set(needed) <= held:
            seen.add(model)
            out.append((etype, model))
    return out


def _uuid_column(cols, names: Sequence[str]):
    for name in names:
        col = cols.get(name)
        if col is None or not isinstance(col.type, Uuid):
            continue
        fks = col.foreign_keys
        if not fks or any(fk.column.table.name == "users" for fk in fks):
            return col
    return None


def in_review_select(etype: str, model: type):
    """One branch of the "records in review" UNION: id, reference, title, a maker hint
    (the record's own creator / owner column) and when it last changed."""
    from app.services import dual_control, record_registry

    cols = model.__table__.columns
    title = next((cols[a] for a in record_registry.TITLE_ATTRIBUTES if a in cols), None)
    ref = cols.get("reference")
    maker = _uuid_column(cols, dual_control.MAKER_ATTRIBUTES)
    stmt = select(
        literal(etype, String).label("entity_type"),
        cols["id"].label("id"),
        (cast(ref, String) if ref is not None else cast(literal(""), String)).label("reference"),
        (cast(title, String) if title is not None else cast(literal(""), String)).label("title"),
        (maker if maker is not None else cast(literal(None), Uuid)).label("maker_hint"),
        cols["updated_at"].label("since"),
    ).where(cols["workflow_status"] == "in_review")
    if "deleted" in cols:
        stmt = stmt.where(cols["deleted"].is_(False))
    return stmt


async def records_in_review(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.asset import Asset
    from app.models.audit import AuditLog
    from app.models.workflow import WorkflowInstance, WorkflowInstanceStatus
    from app.services import dual_control, record_registry
    from app.services.notifications import link_to

    types = review_types(ctx.permissions)
    if not types:
        return []
    rows = (await db.execute(union_all(*[in_review_select(t, m) for t, m in types]).limit(ROW_CAP))).all()
    if not rows:
        return []
    ids = [r.id for r in rows]
    present = sorted({r.entity_type for r in rows})
    routed = {
        (t, i) for t, i in (
            await db.execute(
                select(WorkflowInstance.entity_type, WorkflowInstance.entity_id).where(
                    WorkflowInstance.status == WorkflowInstanceStatus.in_progress,
                    WorkflowInstance.entity_id.in_(ids),
                )
            )
        ).all()
    }
    created, submitted = makers_from_trail(
        (
            await db.execute(
                select(AuditLog.entity_type, AuditLog.entity_id, AuditLog.action, AuditLog.actor_id,
                       AuditLog.created_at).where(
                    AuditLog.entity_type.in_(present), AuditLog.entity_id.in_(ids),
                    AuditLog.action.in_(("create", "workflow_submit")),
                )
            )
        ).all()
    )
    required = {t: (await dual_control.dual_control_required(db, t, "approve"))[0] for t in present}
    asset_ids = [r.id for r in rows if record_registry.model_for(r.entity_type) is Asset]
    asset_class = dict((await db.execute(select(Asset.id, Asset.asset_class).where(Asset.id.in_(asset_ids)))).all()) if asset_ids else {}
    out = []
    for r in rows:
        key = (r.entity_type, r.id)
        if key in routed:
            continue  # its route's stages are decided from the approvals inbox
        makers = (created.get(key, r.maker_hint), submitted.get(key))
        if not decided_by_others_only(ctx.user_id, makers, required=required[r.entity_type]):
            continue
        out.append(ctx.mk(
            "record_review", id=r.id, title=r.title or r.reference or "Untitled record",
            reference=r.reference or "", subtitle=record_registry.type_label(r.entity_type),
            link=link_to(r.entity_type, r.id, asset_class=asset_class.get(r.id)),
            entity_type=r.entity_type, entity_id=r.id,
        ))
    return out


async def tests_to_review(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.audit import AuditLog
    from app.models.control import Control, ControlAudit
    from app.schemas.control import CONCLUSIVE_RESULTS, REVIEW_PENDING
    from app.services import dual_control

    if not ctx.holds("control:test"):
        return []
    rows = (
        await db.execute(
            select(ControlAudit.id, ControlAudit.control_id, ControlAudit.test_type, ControlAudit.result,
                   ControlAudit.tested_by_id, Control.reference, Control.name)
            .join(Control, Control.id == ControlAudit.control_id)
            .where(ControlAudit.review_status == REVIEW_PENDING,
                   ControlAudit.result.in_(CONCLUSIVE_RESULTS), Control.deleted.is_(False))
            .order_by(ControlAudit.created_at)
            .limit(ROW_CAP)
        )
    ).all()
    if not rows:
        return []
    required, _rule = await dual_control.dual_control_required(db, "control", "review_test")
    makers: dict = {r.id: {r.tested_by_id} for r in rows}
    if required:
        for test_id, actor in (
            await db.execute(
                select(AuditLog.entity_id, AuditLog.actor_id).where(
                    AuditLog.entity_type == "control_audit", AuditLog.entity_id.in_(list(makers)),
                    AuditLog.action.in_(("create", "update")),
                )
            )
        ).all():
            makers.setdefault(test_id, set()).add(actor)
    out = []
    for r in rows:
        if not decided_by_others_only(ctx.user_id, makers.get(r.id, ()), required=required):
            continue
        result = getattr(r.result, "value", r.result).replace("_", " ")
        kind = f"{r.test_type} test" if r.test_type else "test"
        out.append(ctx.mk(
            "test_review", id=r.id, title=f"{result.capitalize()} {kind} of {r.name}",
            reference=r.reference or "", subtitle="Approve it or return it to the tester",
            link=_link("/controls", r.control_id), entity_type="control", entity_id=r.control_id,
        ))
    return out


async def issues_to_validate(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.audit import AuditLog
    from app.models.issue import ActionStatus, Issue, IssueAction, IssueStatus2
    from app.services import dual_control

    if not ctx.holds("issue:write"):
        return []
    open_action = exists().where(
        IssueAction.issue_id == Issue.id, IssueAction.status.in_((ActionStatus.open, ActionStatus.in_progress))
    )
    done_action = exists().where(IssueAction.issue_id == Issue.id, IssueAction.status == ActionStatus.done)
    rows = (
        await db.execute(
            select(Issue.id, Issue.reference, Issue.title, Issue.due_date, Issue.owner_id, Issue.validation_result)
            .where(Issue.deleted.is_(False), Issue.status.in_((IssueStatus2.open, IssueStatus2.in_progress)),
                   done_action, ~open_action,
                   or_(Issue.validation_result.is_(None), Issue.validation_result != "effective"))
            .limit(ROW_CAP)
        )
    ).all()
    if not rows:
        return []
    required, _rule = await dual_control.dual_control_required(db, "issue", "validate")
    raisers: dict = {}
    if required:
        created, _sub = makers_from_trail(
            (await db.execute(
                select(AuditLog.entity_type, AuditLog.entity_id, AuditLog.action, AuditLog.actor_id,
                       AuditLog.created_at).where(
                    AuditLog.entity_type == "issue", AuditLog.entity_id.in_([r.id for r in rows]),
                    AuditLog.action == "create",
                )
            )).all()
        )
        raisers = {eid: actor for (_t, eid), actor in created.items()}
    out = []
    for r in rows:
        # Not the owner (whose fix it is), not whoever raised it (maker_of falls back to
        # the owner for issues that arrived without a create entry).
        makers = (r.owner_id, raisers.get(r.id, r.owner_id))
        if not decided_by_others_only(ctx.user_id, makers, required=required):
            continue
        again = r.validation_result == "not_effective"
        out.append(ctx.mk(
            "issue_validation", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
            subtitle=("Reworked after a not-effective validation — validate again" if again
                      else "All actions done — validate the fix"),
            link=_link("/issues", r.id), entity_type="issue", entity_id=r.id,
        ))
    return out


async def extensions_to_approve(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.issue import Issue, IssueDueDateChange
    from app.services import dual_control, record_workflow

    if not ctx.holds(*record_workflow.required_permissions("issue", "approve")):
        return []
    rows = (
        await db.execute(
            select(IssueDueDateChange.id, IssueDueDateChange.issue_id, IssueDueDateChange.old_due_date,
                   IssueDueDateChange.new_due_date, IssueDueDateChange.reason,
                   IssueDueDateChange.requested_by_id, Issue.reference, Issue.title)
            .join(Issue, Issue.id == IssueDueDateChange.issue_id)
            .where(IssueDueDateChange.status == "pending", Issue.deleted.is_(False))
            .limit(ROW_CAP)
        )
    ).all()
    if not rows:
        return []
    required, _rule = await dual_control.dual_control_required(db, "issue", "extend_due_date")
    out = []
    for r in rows:
        if not decided_by_others_only(ctx.user_id, (r.requested_by_id,), required=required):
            continue
        who = ctx.directory.label(r.requested_by_id) if ctx.directory is not None else ""
        out.append(MyWorkItem(
            kind="due_date_change", id=r.id, title=r.title, reference=r.reference or "",
            subtitle=(f"{who}: " if who else "") + (r.reason or "No reason given"),
            due_date=r.new_due_date, previous_date=r.old_due_date,
            link=_link("/issues", r.issue_id), entity_type="issue", entity_id=r.issue_id,
        ))
    return out


# ================================================================ things I own ===
async def my_treatment_actions(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.risk import Risk, RiskTreatmentAction

    rows = (
        await db.execute(
            select(RiskTreatmentAction.id, RiskTreatmentAction.title, RiskTreatmentAction.due_date,
                   RiskTreatmentAction.status, RiskTreatmentAction.percent_complete,
                   RiskTreatmentAction.risk_id, Risk.reference, Risk.title.label("risk_title"))
            .join(Risk, Risk.id == RiskTreatmentAction.risk_id)
            .where(RiskTreatmentAction.owner_id == ctx.user_id,
                   RiskTreatmentAction.status.in_(("open", "in_progress")),
                   Risk.deleted.is_(False),
                   RiskTreatmentAction.due_date.is_not(None), RiskTreatmentAction.due_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("treatment_action", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle=f"{r.risk_title} · {r.percent_complete}% done", link=_link("/risks", r.risk_id),
               entity_type="risk", entity_id=r.risk_id, actions=[MARK_DONE])
        for r in rows
    ]


async def my_issue_actions(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.issue import ActionStatus, Issue, IssueAction, IssueStatus2

    rows = (
        await db.execute(
            select(IssueAction.id, IssueAction.title, IssueAction.due_date, IssueAction.issue_id,
                   Issue.reference, Issue.title.label("issue_title"))
            .join(Issue, Issue.id == IssueAction.issue_id)
            .where(IssueAction.owner_id == ctx.user_id,
                   IssueAction.status.in_((ActionStatus.open, ActionStatus.in_progress)),
                   Issue.deleted.is_(False), Issue.status.in_((IssueStatus2.open, IssueStatus2.in_progress)),
                   IssueAction.due_date.is_not(None), IssueAction.due_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("issue_action", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle=r.issue_title, link=_link("/issues", r.issue_id), entity_type="issue", entity_id=r.issue_id)
        for r in rows
    ]


async def my_issues(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.issue import Issue, IssueStatus2

    rows = (
        await db.execute(
            select(Issue.id, Issue.reference, Issue.title, Issue.due_date, Issue.severity)
            .where(Issue.owner_id == ctx.user_id, Issue.deleted.is_(False),
                   Issue.status.in_((IssueStatus2.open, IssueStatus2.in_progress)),
                   Issue.due_date.is_not(None), Issue.due_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("issue", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle=f"{getattr(r.severity, 'value', r.severity)} severity", link=_link("/issues", r.id),
               entity_type="issue", entity_id=r.id)
        for r in rows
    ]


async def my_incidents(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.enums import IncidentStatus
    from app.models.incident import Incident

    rows = (
        await db.execute(
            select(Incident.id, Incident.reference, Incident.title, Incident.severity, Incident.status,
                   Incident.tat_due_date)
            .where(Incident.assignee_id == ctx.user_id, Incident.deleted.is_(False),
                   Incident.status.not_in((IncidentStatus.resolved, IncidentStatus.closed)))
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("incident", due=r.tat_due_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle=f"{getattr(r.severity, 'value', r.severity)} · {getattr(r.status, 'value', r.status)}",
               link=_link("/incidents", r.id), entity_type="incident", entity_id=r.id)
        for r in rows
    ]


async def my_control_tests(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.control import UNTESTABLE_CONTROL_STATUSES, Control

    rows = (
        await db.execute(
            select(Control.id, Control.reference, Control.name, Control.next_audit_date, Control.owner_id)
            .where(or_(Control.owner_id == ctx.user_id, Control.operator_id == ctx.user_id),
                   Control.deleted.is_(False), Control.status.not_in(UNTESTABLE_CONTROL_STATUSES),
                   Control.next_audit_date.is_not(None), Control.next_audit_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("control_test", due=r.next_audit_date, id=r.id, title=r.name, reference=r.reference or "",
               subtitle="You own this control" if r.owner_id == ctx.user_id else "You operate this control",
               link=_link("/controls", r.id), entity_type="control", entity_id=r.id)
        for r in rows
    ]


async def my_returned_tests(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.control import Control, ControlAudit
    from app.schemas.control import REVIEW_RETURNED

    rows = (
        await db.execute(
            select(ControlAudit.id, ControlAudit.control_id, ControlAudit.review_note, Control.reference, Control.name)
            .join(Control, Control.id == ControlAudit.control_id)
            .where(ControlAudit.review_status == REVIEW_RETURNED, ControlAudit.tested_by_id == ctx.user_id,
                   Control.deleted.is_(False))
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("test_returned", id=r.id, title=f"Test of {r.name}", reference=r.reference or "",
               subtitle=(f"Reviewer's note: {r.review_note}" if r.review_note else "Returned by the reviewer"),
               link=_link("/controls", r.control_id), entity_type="control", entity_id=r.control_id)
        for r in rows
    ]


async def my_risk_reviews(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.risk import Risk

    rows = (
        await db.execute(
            select(Risk.id, Risk.reference, Risk.title, Risk.next_review_date)
            .where(Risk.owner_id == ctx.user_id, Risk.deleted.is_(False),
                   Risk.next_review_date.is_not(None), Risk.next_review_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("risk_review", due=r.next_review_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle="Review the assessment and attest it", link=_link("/risks", r.id),
               entity_type="risk", entity_id=r.id)
        for r in rows
    ]


async def my_attestations(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    """Periodic reviews of records I own: policies and third parties by their own review
    date, every other attested record type by its latest attestation's next due date."""
    from app.models.asset import Asset
    from app.models.attestation import Attestation
    from app.models.enums import VendorStatus
    from app.models.policy import Policy
    from app.models.vendor import Vendor
    from app.services import record_registry
    from app.services.notifications import NATIVE_REVIEW_ENTITY_TYPES, link_to, owner_column

    out: list[MyWorkItem] = []
    for pid, ref, title, due in (
        await db.execute(
            select(Policy.id, Policy.reference, Policy.title, Policy.next_review_date)
            .where(Policy.owner_id == ctx.user_id, Policy.deleted.is_(False),
                   Policy.next_review_date.is_not(None), Policy.next_review_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all():
        out.append(ctx.mk("attestation", due=due, id=pid, title=title, reference=ref or "",
                          subtitle="Policy review", link=_link("/policies", pid),
                          entity_type="policy", entity_id=pid))
    for vid, name, due in (
        await db.execute(
            select(Vendor.id, Vendor.name, Vendor.next_review_date)
            .where(Vendor.relationship_owner_id == ctx.user_id, Vendor.deleted.is_(False),
                   Vendor.status != VendorStatus.offboarded,  # nothing left to review
                   Vendor.next_review_date.is_not(None), Vendor.next_review_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all():
        out.append(ctx.mk("attestation", due=due, id=vid, title=name, subtitle="Third-party review",
                          link=_link("/vendors", vid), entity_type="vendor", entity_id=vid))

    latest = (
        select(Attestation.entity_type, Attestation.entity_id, Attestation.next_due)
        .where(Attestation.entity_type.not_in(sorted(NATIVE_REVIEW_ENTITY_TYPES)))
        .distinct(Attestation.entity_type, Attestation.entity_id)
        .order_by(Attestation.entity_type, Attestation.entity_id, Attestation.attested_at.desc())
    ).subquery()
    due_rows = (
        await db.execute(
            select(latest.c.entity_type, latest.c.entity_id, latest.c.next_due)
            .where(latest.c.next_due.is_not(None), latest.c.next_due <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all()
    by_type: dict[str, dict[Any, date]] = {}
    for etype, eid, due in due_rows:
        by_type.setdefault(etype, {})[eid] = due
    for etype, dues in by_type.items():
        model = record_registry.model_for(etype)
        owner = owner_column(model) if model is not None else None
        if owner is None:
            continue
        cols = model.__table__.columns
        title = next((cols[a] for a in record_registry.TITLE_ATTRIBUTES if a in cols), None)
        ref = cols.get("reference")
        wanted = [cols["id"], ref if ref is not None else literal(""), title if title is not None else literal("")]
        if model is Asset:
            wanted.append(cols["asset_class"])
        stmt = select(*wanted).where(cols["id"].in_(list(dues)), owner == ctx.user_id)
        if "deleted" in cols:
            stmt = stmt.where(cols["deleted"].is_(False))
        label = record_registry.type_label(etype, model)
        for row in (await db.execute(stmt)).all():
            rid = row[0]
            out.append(ctx.mk(
                "attestation", due=dues[rid], id=rid, title=str(row[2] or row[1] or label),
                reference=str(row[1] or ""), subtitle=f"{label} attestation",
                link=link_to(etype, rid, asset_class=row[3] if model is Asset else None),
                entity_type=etype, entity_id=rid,
            ))
    return out


async def my_kri_readings(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.enums import ReviewFrequency
    from app.models.operational_risk import KeyRiskIndicator as K

    if "operational_risk" in ctx.modules_off:
        return []
    rows = (
        await db.execute(
            select(K.id, K.reference, K.name, K.frequency, K.last_measured_date)
            .where(K.deleted.is_(False), K.frequency != ReviewFrequency.none,
                   or_(K.data_provider_id == ctx.user_id, and_(K.data_provider_id.is_(None), K.owner_id == ctx.user_id)))
            .limit(ROW_CAP)
        )
    ).all()
    kri_horizon = ctx.today + timedelta(days=KRI_HORIZON_DAYS)
    out = []
    for r in rows:
        due = kri_next_due(r.frequency, r.last_measured_date, ctx.today)
        if due is None or due > kri_horizon:
            continue
        freq = getattr(r.frequency, "value", r.frequency)
        out.append(ctx.mk(
            "kri_measurement", due=due, id=r.id, title=r.name, reference=r.reference or "",
            subtitle=(f"{freq.capitalize()} reading" if r.last_measured_date else f"{freq.capitalize()} · no reading yet"),
            link=_link("/operational-risk", r.id), entity_type="key_risk_indicator", entity_id=r.id,
        ))
    return out


async def my_rcsa_actions(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.enums import RcsaStatus
    from app.models.operational_risk import RcsaAssessment, RcsaRisk

    if "operational_risk" in ctx.modules_off:
        return []
    rows = (
        await db.execute(
            select(RcsaRisk.id, RcsaRisk.title, RcsaRisk.action, RcsaRisk.due_date,
                   RcsaAssessment.id.label("assessment_id"), RcsaAssessment.reference,
                   RcsaAssessment.title.label("assessment_title"))
            .join(RcsaAssessment, RcsaAssessment.id == RcsaRisk.assessment_id)
            .where(RcsaRisk.action_owner_id == ctx.user_id, RcsaAssessment.deleted.is_(False),
                   RcsaAssessment.status != RcsaStatus.completed)
            .limit(ROW_CAP)
        )
    ).all()
    return [
        ctx.mk("rcsa_action", due=r.due_date, id=r.id, title=r.action or r.title, reference=r.reference or "",
               subtitle=f"{r.assessment_title} · {r.title}", link=_link("/operational-risk", r.assessment_id),
               entity_type="rcsa_assessment", entity_id=r.assessment_id)
        for r in rows
    ]


async def policies_to_acknowledge(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.enums import PolicyStatus
    from app.models.policy import Policy, PolicyAcknowledgment, policy_roles

    names_roles = exists().where(policy_roles.c.policy_id == Policy.id)
    names_mine = (
        exists().where(policy_roles.c.policy_id == Policy.id, policy_roles.c.role_id.in_(sorted(ctx.role_ids, key=str)))
        if ctx.role_ids else false()
    )
    acknowledged = exists().where(
        PolicyAcknowledgment.policy_id == Policy.id, PolicyAcknowledgment.user_id == ctx.user_id
    )
    rows = (
        await db.execute(
            select(Policy.id, Policy.reference, Policy.title, Policy.version)
            .where(Policy.deleted.is_(False), Policy.status == PolicyStatus.published, ~acknowledged,
                   or_(~names_roles, names_mine))
            .limit(ROW_CAP)
        )
    ).all()
    quick = [ACK] if ctx.holds("policy:read") else []
    return [
        ctx.mk("policy_ack", id=r.id, title=r.title, reference=r.reference or "",
               subtitle=(f"Version {r.version} · " if r.version else "") + "read it, then acknowledge",
               link=_link("/policies", r.id), entity_type="policy", entity_id=r.id, actions=list(quick))
        for r in rows
    ]


#: kind -> builder, in :data:`KINDS` order.
BUILDERS = {
    "approval": approvals_waiting,
    "record_review": records_in_review,
    "test_review": tests_to_review,
    "issue_validation": issues_to_validate,
    "due_date_change": extensions_to_approve,
    "treatment_action": my_treatment_actions,
    "issue_action": my_issue_actions,
    "issue": my_issues,
    "incident": my_incidents,
    "control_test": my_control_tests,
    "test_returned": my_returned_tests,
    "risk_review": my_risk_reviews,
    "attestation": my_attestations,
    "kri_measurement": my_kri_readings,
    "rcsa_action": my_rcsa_actions,
    "policy_ack": policies_to_acknowledge,
}


async def my_work(db: AsyncSession, user: Any, today: date | None = None) -> MyWorkRead:
    """Everything waiting for ``user`` (see the module docstring)."""
    from app.services.notifications import load_directory

    today = today or date.today()
    ctx = Ctx(
        user_id=user.id, email=user.email or "", permissions=set(user.permission_codes or []),
        role_names={r.name for r in user.roles}, role_ids={r.id for r in user.roles},
        today=today, horizon=today + timedelta(days=HORIZON_DAYS),
        directory=await load_directory(db), modules_off=await _module_off(db),
    )
    found = {kind: await build(db, ctx) for kind, build in BUILDERS.items()}
    return assemble(user.id, today, found)


# ================================================================ quick action ===
async def mark_treatment_action_done(db: AsyncSession, user: Any, action_id: uuid.UUID) -> TreatmentActionDone:
    """Mark one of my treatment actions done (the My Work quick action). Stamps
    ``completed_at``, sets 100 %, re-derives the risk's treatment deadline and audits the
    change on the risk, exactly as editing the action on the risk does."""
    from app.models.risk import Risk, RiskTreatmentAction
    from app.services import audit, risk_integrity

    action = await db.get(RiskTreatmentAction, action_id)
    risk = await db.get(Risk, action.risk_id) if action is not None else None
    if action is None or risk is None or risk.deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Treatment action not found")
    refusal = can_mark_done(action, user.id, user.permission_codes or [])
    if refusal:
        code = status.HTTP_409_CONFLICT if action.owner_id == user.id or "risk:write" in (user.permission_codes or []) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=code, detail=refusal)
    before = action.status
    if before != "done":
        risk_integrity.apply_action_status(action, status="done", percent=None, now=datetime.now(timezone.utc))
        await db.flush()
        actions = (await db.scalars(select(RiskTreatmentAction).where(RiskTreatmentAction.risk_id == risk.id))).all()
        if actions:
            risk.treatment_deadline = risk_integrity.derive_treatment_deadline(actions)
        await db.flush()
        await audit.record(
            db, actor=user, action="update_treatment_action", entity_type="risk", entity_id=risk.id,
            summary=f"Marked treatment action done on {risk.reference}: {action.title} (My Work)"[:500],
            changes={"action_id": str(action.id), "status": f"{before} -> done", "percent_complete": "100",
                     "treatment_deadline": str(risk.treatment_deadline or ""), "via": "my_work"},
        )
    return TreatmentActionDone(
        id=action.id, risk_id=risk.id, status=action.status, percent_complete=action.percent_complete,
        completed_at=action.completed_at, treatment_deadline=risk.treatment_deadline,
    )
