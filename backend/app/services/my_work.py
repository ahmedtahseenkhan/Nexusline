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
  parties, and every record type the attestation panel covers); attestations of
  high-stakes records awaiting your independent second signature (decision 9, which is
  what completes them); KRI readings you supply
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
from sqlalchemy import String, Uuid, and_, cast, exists, false, literal, null, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.my_work import MyWorkItem, MyWorkRead, MyWorkSection, TreatmentActionDone

#: "Due soon" looks this many days ahead.
HORIZON_DAYS = 14
#: KRI readings fall due every cycle; only the next few days are "due".
KRI_HORIZON_DAYS = 3
#: Decision 9: a required second signature is owed within a week of the certification —
#: until it is given the attestation is incomplete and the review clock has not restarted.
CONFIRM_DAYS = 7
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
    ("attestation_confirm", "Attestations to confirm",
     "High-stakes records someone has certified; your independent signature is what "
     "completes the attestation and restarts the review cycle."),
    ("kri_measurement", "KRI readings due", "KRIs you supply data for whose next reading is due."),
    ("rcsa_action", "RCSA actions assigned to you", "Actions on open RCSAs where you are the action owner."),
    ("policy_ack", "Policies to acknowledge",
     "Published policies that apply to your roles and that you haven't acknowledged."),
    # --- Phase 4B ---
    ("assessment_review", "Vendor assessments to review",
     "Third parties you manage have submitted their answers; review them."),
    ("finding_follow_up", "Audit findings to validate",
     "Findings on engagements you run whose agreed date has arrived: confirm the fix and close, or escalate."),
    ("engagement_task", "Your audit engagements",
     "Engagements you lead or work on with procedures still to perform."),
    ("audit_remediation", "Audit findings you must fix", "Open audit findings naming you as the action owner."),
    ("access_review", "Access reviews to certify", "Reviews where you are the reviewer, with accounts still to decide."),
    ("assessment_chase", "Vendor assessments awaiting answers",
     "Questionnaires sent to third parties you manage that are overdue or due soon."),
    ("regulatory_change", "Regulatory changes and obligations",
     "Circulars to assess and obligations to meet that you own."),
    ("regulatory_return", "Regulatory returns due", "Returns you file with the regulator, overdue or due soon."),
    ("incident_report", "Regulator notification deadlines",
     "Pending regulator reports on incidents assigned to you."),
    ("exception_expiry", "Exceptions expiring", "Approved exceptions you raised, approved or own that end within 30 days."),
    ("declaration", "Declarations to submit", "Open declaration campaigns waiting for your submission."),
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
    for key in ("operational_risk", "internal_audit", "regulatory_change", "declarations"):
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
        APPROVE_PERMISSION, ROLE, USER, approval_recipients, approval_refusal, load_stage_gates,
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
    # Phase 4: route stages assigned to a role go through the same eligibility rule as
    # the Approvals page and the decide endpoint, so nothing listed here is refused there.
    gates = await load_stage_gates(db, rows, ctx.directory) if rows else {}
    out = []
    for ap in rows:
        gate = gates.get(ap.id)
        addressed = any(
            (kind == USER and value == ctx.user_id) or (kind == ROLE and value in ctx.role_names)
            for kind, value in approval_recipients(ap, ctx.directory, gate)
        )
        if not addressed or approval_refusal(
            ap, user_id=ctx.user_id, email=ctx.email, permissions=ctx.permissions, voted_ids=(),
            role_names=ctx.role_names, stage=gate,
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


def complete_attestation():
    """SQL for "this attestation counts": signed, and confirmed where decision 9 requires
    a second signature. One still awaiting that signature has certified nothing, so it
    does not hold off the review it was meant to record."""
    from app.models.attestation import Attestation

    return or_(
        Attestation.confirmation_required.is_(False), Attestation.confirmed_by_id.is_not(None)
    )


async def my_attestations(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    """Periodic reviews of records I own: policies, third parties and assets by their own
    review date, every other attested record type by its latest *complete* attestation's
    next due date.

    Decision 6: only an approved record can be attested. A record whose approval is
    incomplete still appears (its review is still owed) but asks for the approval first
    (``record_workflow.attest_work_note``); a retired record owes nothing and is left out.
    """
    from app.models.asset import Asset
    from app.models.attestation import Attestation
    from app.models.enums import VendorStatus
    from app.models.policy import Policy
    from app.models.vendor import Vendor
    from app.services import record_registry
    from app.services.notifications import NATIVE_REVIEW_ENTITY_TYPES, link_to, owner_column
    from app.services.record_workflow import RETIRED, attest_work_note, state_value

    def retired(state: Any) -> bool:
        return state is not None and state_value(state) == RETIRED

    out: list[MyWorkItem] = []
    for pid, ref, title, due, wf in (
        await db.execute(
            select(Policy.id, Policy.reference, Policy.title, Policy.next_review_date, Policy.workflow_status)
            .where(Policy.owner_id == ctx.user_id, Policy.deleted.is_(False),
                   Policy.next_review_date.is_not(None), Policy.next_review_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all():
        if retired(wf):
            continue
        out.append(ctx.mk("attestation", due=due, id=pid, title=title, reference=ref or "",
                          subtitle=attest_work_note(wf) or "Policy review", link=_link("/policies", pid),
                          entity_type="policy", entity_id=pid))
    for vid, name, due, wf in (
        await db.execute(
            select(Vendor.id, Vendor.name, Vendor.next_review_date, Vendor.workflow_status)
            .where(Vendor.relationship_owner_id == ctx.user_id, Vendor.deleted.is_(False),
                   Vendor.status != VendorStatus.offboarded,  # nothing left to review
                   Vendor.next_review_date.is_not(None), Vendor.next_review_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all():
        if retired(wf):
            continue
        out.append(ctx.mk("attestation", due=due, id=vid, title=name,
                          subtitle=attest_work_note(wf) or "Third-party review",
                          link=_link("/vendors", vid), entity_type="vendor", entity_id=vid))
    # Assets by their own review date (record-page B4), for their approval owner (an
    # asset's owner is a business unit, not a person).
    # Assets carry that owner as free text, so match it like the other text owners.
    for aid, name, aclass, due, approver, wf in (
        await db.execute(
            select(Asset.id, Asset.name, Asset.asset_class, Asset.next_review_date, Asset.workflow_owner,
                   Asset.workflow_status)
            .where(Asset.workflow_owner != "", Asset.deleted.is_(False),
                   Asset.next_review_date.is_not(None), Asset.next_review_date <= ctx.horizon)
            .limit(ROW_CAP)
        )
    ).all():
        if not names_me(ctx, approver) or retired(wf):
            continue
        it = getattr(aclass, "value", aclass) == "it_asset"
        out.append(ctx.mk("attestation", due=due, id=aid, title=name,
                          subtitle=attest_work_note(wf) or ("IT asset review" if it else "Information asset review"),
                          link=link_to("asset", aid, asset_class=aclass), entity_type="asset", entity_id=aid))

    latest = (
        select(Attestation.entity_type, Attestation.entity_id, Attestation.next_due)
        .where(Attestation.entity_type.not_in(sorted(NATIVE_REVIEW_ENTITY_TYPES)), complete_attestation())
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
        wf_col = cols.get("workflow_status")
        wanted = [cols["id"], ref if ref is not None else literal(""), title if title is not None else literal(""),
                  wf_col if wf_col is not None else null()]
        if model is Asset:
            wanted.append(cols["asset_class"])
        stmt = select(*wanted).where(cols["id"].in_(list(dues)), owner == ctx.user_id)
        if "deleted" in cols:
            stmt = stmt.where(cols["deleted"].is_(False))
        label = record_registry.type_label(etype, model)
        for row in (await db.execute(stmt)).all():
            rid, wf = row[0], row[3]
            if retired(wf):
                continue
            out.append(ctx.mk(
                "attestation", due=dues[rid], id=rid, title=str(row[2] or row[1] or label),
                reference=str(row[1] or ""), subtitle=attest_work_note(wf) or f"{label} attestation",
                link=link_to(etype, rid, asset_class=row[4] if model is Asset else None),
                entity_type=etype, entity_id=rid,
            ))
    # Decision 9: a record the owner has already certified is still listed — its review is
    # not complete until someone else confirms it — but it says so instead of asking for
    # an attestation that has been made.
    waiting = await awaiting_confirmation(db, out)
    for item in out:
        if (item.entity_type, item.entity_id) in waiting:
            item.subtitle = "Attested — awaiting independent confirmation"
    return out


async def awaiting_confirmation(db: AsyncSession, items: Sequence[MyWorkItem]) -> set[tuple[str, Any]]:
    """``(entity_type, id)`` of the listed records whose newest attestation is signed but
    still owes its required second signature. One query."""
    from app.models.attestation import Attestation

    pairs = [(i.entity_type, i.entity_id) for i in items if i.entity_type and i.entity_id]
    if not pairs:
        return set()
    rows = (
        await db.execute(
            select(Attestation.entity_type, Attestation.entity_id)
            .where(
                Attestation.confirmation_required.is_(True),
                Attestation.confirmed_by_id.is_(None),
                Attestation.entity_id.in_([eid for _t, eid in pairs]),
            )
            .limit(ROW_CAP)
        )
    ).all()
    found = {(etype, eid) for etype, eid in rows}
    return {p for p in pairs if p in found}


async def attestations_to_confirm(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    """Attestations waiting for my independent second signature (decision 9).

    A high-stakes record — a key control, a critical or high residual risk, a material
    outsourcing arrangement or third party, any policy — is certified by its owner, and
    that certification only counts once somebody else confirms it: until then the review
    clock has not restarted. Nobody is named as the confirmer, so it is offered to
    everyone who may write that record and did not sign it, exactly as an approval
    addressed to no one in particular is. Owed within :data:`CONFIRM_DAYS` of signing.
    """
    from app.models.asset import Asset
    from app.models.attestation import Attestation
    from app.services import entity_types, record_registry
    from app.services.notifications import link_to
    from app.services.record_workflow import RETIRED, state_value

    rows = (
        await db.execute(
            select(Attestation.id, Attestation.entity_type, Attestation.entity_id,
                   Attestation.attested_at, Attestation.attested_by_email)
            .where(
                Attestation.confirmation_required.is_(True),
                Attestation.confirmed_by_id.is_(None),
                or_(Attestation.attested_by_id.is_(None), Attestation.attested_by_id != ctx.user_id),
            )
            .order_by(Attestation.attested_at.desc())
            .limit(ROW_CAP)
        )
    ).all()
    # Newest pending attestation per record; only types this user may write.
    pending: dict[tuple[str, Any], Any] = {}
    for row in rows:
        spec = entity_types.ENTITY_TYPES.get(row.entity_type)
        if spec is None or not ctx.holds(spec.write_perm):
            continue
        pending.setdefault((row.entity_type, row.entity_id), row)

    by_type: dict[str, dict[Any, Any]] = {}
    for (etype, eid), row in pending.items():
        by_type.setdefault(etype, {})[eid] = row
    out: list[MyWorkItem] = []
    for etype, wanted in by_type.items():
        model = record_registry.model_for(etype)
        if model is None:
            continue
        cols = model.__table__.columns
        title = next((cols[a] for a in record_registry.TITLE_ATTRIBUTES if a in cols), None)
        ref = cols.get("reference")
        wf_col = cols.get("workflow_status")
        select_cols = [cols["id"], ref if ref is not None else literal(""),
                       title if title is not None else literal(""),
                       wf_col if wf_col is not None else null()]
        if model is Asset:
            select_cols.append(cols["asset_class"])
        stmt = select(*select_cols).where(cols["id"].in_(list(wanted)))
        if "deleted" in cols:
            stmt = stmt.where(cols["deleted"].is_(False))
        label = record_registry.type_label(etype, model)
        for record in (await db.execute(stmt)).all():
            rid, wf = record[0], record[3]
            if wf is not None and state_value(wf) == RETIRED:
                continue  # a retired record owes no review, so its attestation owes none either
            row = wanted[rid]
            out.append(ctx.mk(
                "attestation_confirm", due=row.attested_at + timedelta(days=CONFIRM_DAYS),
                id=row.id, title=str(record[2] or record[1] or label), reference=str(record[1] or ""),
                subtitle=f"Certified {row.attested_at} by {row.attested_by_email or 'another user'} — "
                         "confirm it to complete the attestation",
                link=link_to(etype, rid, asset_class=record[4] if model is Asset else None),
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


# ============================================================ phase 4B kinds ===
#: Exceptions show this many days before they expire.
EXCEPTION_HORIZON_DAYS = 30
#: Access-review, assessment and return look-ahead (they need more notice than a task).
LONG_HORIZON_DAYS = 30


def names_me(ctx: Ctx, *texts: str | None) -> bool:
    """Whether any free-text person field names this user (an exact e-mail, or the one
    active user with exactly that name). Lists (audit teams) are split on , ; and new
    lines. Pure once the directory is loaded."""
    if ctx.directory is None:
        return False
    import re

    for text in texts:
        for part in re.split(r"[,;\n]", text or ""):
            if part.strip() and ctx.directory.person(part.strip()) == ctx.user_id:
                return True
    return False


def _val(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


async def assessments_for_me(db: AsyncSession, ctx: Ctx) -> tuple[list[MyWorkItem], list[MyWorkItem]]:
    """Submitted assessments to review, and sent ones still unanswered, for third parties
    whose relationship owner is this user (or, with no owner set, for anyone who runs
    assessments). Reads only ``status``, ``due_date``, ``vendor_id`` and ``title``."""
    from app.models.assessment import Assessment
    from app.models.vendor import Vendor

    if not ctx.holds("assessment:read"):
        return [], []
    rows = (await db.execute(
        select(Assessment.id, Assessment.title, Assessment.status, Assessment.due_date, Assessment.vendor_id,
               Vendor.name.label("vendor"), Vendor.relationship_owner_id)
        .outerjoin(Vendor, Vendor.id == Assessment.vendor_id)
        .where(cast(Assessment.status, String).in_(("submitted", "sent", "in_progress")))
        .limit(ROW_CAP)
    )).all()
    review, chase = [], []
    long_horizon = ctx.today + timedelta(days=LONG_HORIZON_DAYS)
    for r in rows:
        mine = r.relationship_owner_id == ctx.user_id or (r.relationship_owner_id is None and ctx.holds("assessment:write"))
        if not mine:
            continue
        status = _val(r.status)
        if status == "submitted":
            review.append(ctx.mk("assessment_review", due=r.due_date, id=r.id, title=r.title,
                                 subtitle=f"{r.vendor or 'No third party'} · answers submitted",
                                 link=_link("/assessments", r.id), entity_type="assessment", entity_id=r.id))
        elif r.due_date is not None and r.due_date <= long_horizon:
            chase.append(ctx.mk("assessment_chase", due=r.due_date, id=r.id, title=r.title,
                                subtitle=f"{r.vendor or 'No third party'} · {status.replace('_', ' ')}",
                                link=_link("/assessments", r.id), entity_type="assessment", entity_id=r.id))
    return review, chase


async def my_assessment_reviews(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    return (await assessments_for_me(db, ctx))[0]


async def my_assessment_chases(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    return (await assessments_for_me(db, ctx))[1]


async def _my_engagements(db: AsyncSession, ctx: Ctx) -> list:
    from app.models.enums import AuditEngagementStatus
    from app.models.internal_audit import AuditEngagement

    if "internal_audit" in ctx.modules_off or not ctx.holds("internal_audit:read"):
        return []
    rows = (await db.execute(
        select(AuditEngagement.id, AuditEngagement.reference, AuditEngagement.title, AuditEngagement.status,
               AuditEngagement.lead_auditor, AuditEngagement.audit_team, AuditEngagement.planned_end)
        .where(AuditEngagement.deleted.is_(False),
               AuditEngagement.status.not_in((AuditEngagementStatus.cancelled,)))
        .limit(ROW_CAP)
    )).all()
    return [r for r in rows if names_me(ctx, r.lead_auditor, r.audit_team)]


async def my_engagement_tasks(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.enums import AuditProcedureResult
    from app.models.internal_audit import AuditProcedure

    mine = [r for r in await _my_engagements(db, ctx) if _val(r.status) != "closed"]
    if not mine:
        return []
    pending = dict((await db.execute(
        select(AuditProcedure.engagement_id, func_count())
        .where(AuditProcedure.engagement_id.in_([r.id for r in mine]),
               AuditProcedure.result == AuditProcedureResult.pending)
        .group_by(AuditProcedure.engagement_id)
    )).all())
    out = []
    for r in mine:
        n = int(pending.get(r.id, 0) or 0)
        status = _val(r.status)
        if not n and status != "planned":
            continue
        out.append(ctx.mk(
            "engagement_task", due=r.planned_end, id=r.id, title=r.title, reference=r.reference or "",
            subtitle=(f"{status.capitalize()} · {n} procedure(s) still to perform" if n
                      else "Planned · no procedures yet"),
            link=_link("/internal-audit", r.id), entity_type="audit_engagement", entity_id=r.id,
        ))
    return out


async def my_findings_to_validate(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.internal_audit import AuditFinding

    mine = {r.id: r for r in await _my_engagements(db, ctx)}
    if not mine:
        return []
    rows = (await db.execute(
        select(AuditFinding.id, AuditFinding.reference, AuditFinding.title, AuditFinding.rating,
               AuditFinding.action_owner, AuditFinding.due_date, AuditFinding.engagement_id)
        .where(AuditFinding.engagement_id.in_(list(mine)), cast(AuditFinding.status, String).in_(("open", "in_progress")),
               AuditFinding.due_date.is_not(None), AuditFinding.due_date <= ctx.horizon)
        .limit(ROW_CAP)
    )).all()
    return [
        ctx.mk("finding_follow_up", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle=f"{_val(r.rating).capitalize()} · {mine[r.engagement_id].title}"
                        + (f" · owner {r.action_owner}" if r.action_owner else ""),
               link=_link("/internal-audit", r.engagement_id), entity_type="audit_engagement",
               entity_id=r.engagement_id)
        for r in rows
    ]


async def my_audit_remediation(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.internal_audit import AuditEngagement, AuditFinding

    if "internal_audit" in ctx.modules_off:
        return []
    rows = (await db.execute(
        select(AuditFinding.id, AuditFinding.reference, AuditFinding.title, AuditFinding.rating,
               AuditFinding.action_owner, AuditFinding.due_date, AuditFinding.engagement_id,
               AuditEngagement.title.label("engagement"))
        .join(AuditEngagement, AuditEngagement.id == AuditFinding.engagement_id)
        .where(AuditEngagement.deleted.is_(False), AuditFinding.action_owner != "",
               cast(AuditFinding.status, String).in_(("open", "in_progress")))
        .limit(ROW_CAP)
    )).all()
    link_ok = ctx.holds("internal_audit:read")
    return [
        ctx.mk("audit_remediation", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle=f"{_val(r.rating).capitalize()} finding · {r.engagement}",
               link=_link("/internal-audit", r.engagement_id) if link_ok else "",
               entity_type="audit_engagement", entity_id=r.engagement_id)
        for r in rows if names_me(ctx, r.action_owner)
    ]


async def my_access_reviews(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.access_review import AccessReview, AccessReviewItem
    from app.models.enums import AccessDecision, AccessReviewStatus

    if not ctx.holds("review:read"):
        return []
    rows = (await db.execute(
        select(AccessReview.id, AccessReview.reference, AccessReview.name, AccessReview.reviewer,
               AccessReview.system_name, AccessReview.due_date, AccessReview.status)
        .where(AccessReview.deleted.is_(False), AccessReview.status != AccessReviewStatus.completed,
               AccessReview.reviewer != "")
        .limit(ROW_CAP)
    )).all()
    mine = [r for r in rows if names_me(ctx, r.reviewer)]
    if not mine:
        return []
    pending = dict((await db.execute(
        select(AccessReviewItem.review_id, func_count())
        .where(AccessReviewItem.review_id.in_([r.id for r in mine]), AccessReviewItem.decision == AccessDecision.pending)
        .group_by(AccessReviewItem.review_id)
    )).all())
    return [
        ctx.mk("access_review", due=r.due_date, id=r.id, title=r.name, reference=r.reference or "",
               subtitle=" · ".join(p for p in (r.system_name, f"{int(pending.get(r.id, 0) or 0)} account(s) to decide") if p),
               link=_link("/access-reviews", r.id), entity_type="access_review", entity_id=r.id)
        for r in mine
    ]


async def my_regulatory_changes(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.regulatory_change import Obligation, ObligationStatus, RegChangeStatus, RegulatoryChange

    if "regulatory_change" in ctx.modules_off or not ctx.holds("regchange:read"):
        return []
    out = []
    for r in (await db.execute(
        select(RegulatoryChange.id, RegulatoryChange.reference, RegulatoryChange.title, RegulatoryChange.owner,
               RegulatoryChange.status, RegulatoryChange.effective_date, RegulatoryChange.regulator,
               RegulatoryChange.circular_ref)
        .where(RegulatoryChange.deleted.is_(False), RegulatoryChange.owner != "",
               RegulatoryChange.status.in_((RegChangeStatus.identified, RegChangeStatus.under_assessment,
                                            RegChangeStatus.in_implementation)))
        .limit(ROW_CAP)
    )).all():
        if not names_me(ctx, r.owner):
            continue
        status = _val(r.status)
        out.append(ctx.mk(
            "regulatory_change", due=r.effective_date, id=r.id, title=r.title, reference=r.reference or "",
            subtitle=" · ".join(p for p in (r.regulator, r.circular_ref,
                                            "assess the impact" if status != "in_implementation" else "implement it") if p),
            link=_link("/regulatory-change", r.id), entity_type="regulatory_change", entity_id=r.id,
        ))
    for r in (await db.execute(
        select(Obligation.id, Obligation.reference, Obligation.title, Obligation.owner, Obligation.due_date,
               Obligation.regulatory_change_id)
        .where(Obligation.owner != "", Obligation.status.in_((ObligationStatus.open, ObligationStatus.in_progress)),
               or_(Obligation.due_date.is_(None), Obligation.due_date <= ctx.horizon))
        .limit(ROW_CAP)
    )).all():
        if not names_me(ctx, r.owner):
            continue
        out.append(ctx.mk(
            "regulatory_change", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
            subtitle="Obligation to meet",
            link=_link("/regulatory-change", r.regulatory_change_id) if r.regulatory_change_id else "/regulatory-change",
            entity_type="obligation", entity_id=r.id,
        ))
    return out


async def my_regulatory_returns(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.regulatory_change import RegulatoryReturn

    if "regulatory_change" in ctx.modules_off or not ctx.holds("regchange:read"):
        return []
    rows = (await db.execute(
        select(RegulatoryReturn.id, RegulatoryReturn.reference, RegulatoryReturn.name, RegulatoryReturn.owner,
               RegulatoryReturn.next_due_date, RegulatoryReturn.regulator, RegulatoryReturn.submission_channel)
        .where(RegulatoryReturn.deleted.is_(False), RegulatoryReturn.owner != "",
               RegulatoryReturn.next_due_date.is_not(None),
               RegulatoryReturn.next_due_date <= ctx.today + timedelta(days=LONG_HORIZON_DAYS))
        .limit(ROW_CAP)
    )).all()
    return [
        ctx.mk("regulatory_return", due=r.next_due_date, id=r.id, title=r.name, reference=r.reference or "",
               subtitle=" · ".join(p for p in (r.regulator, r.submission_channel) if p),
               link=_link("/regulatory-change", r.id), entity_type="regulatory_return", entity_id=r.id)
        for r in rows if names_me(ctx, r.owner)
    ]


async def my_incident_reports(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.enums import IncidentStatus, RegulatoryReportStatus
    from app.models.incident import Incident, RegulatoryReport

    rows = (await db.execute(
        select(RegulatoryReport.id, RegulatoryReport.report_type, RegulatoryReport.deadline, RegulatoryReport.regulator,
               Incident.id.label("incident_id"), Incident.reference, Incident.title)
        .join(Incident, Incident.id == RegulatoryReport.incident_id)
        .where(Incident.deleted.is_(False), RegulatoryReport.status == RegulatoryReportStatus.pending,
               RegulatoryReport.deadline.is_not(None),
               or_(Incident.assignee_id == ctx.user_id, RegulatoryReport.submitted_by_id == ctx.user_id),
               Incident.status != IncidentStatus.closed)
        .limit(ROW_CAP)
    )).all()
    out = []
    for r in rows:
        deadline = r.deadline if r.deadline.tzinfo else r.deadline.replace(tzinfo=timezone.utc)
        out.append(ctx.mk(
            "incident_report", due=deadline.date(), id=r.id, title=r.title, reference=r.reference or "",
            subtitle=f"{_val(r.report_type).replace('_', ' ').capitalize()} to {r.regulator or 'the regulator'}"
                     f" · deadline {deadline.strftime('%H:%M')} UTC",
            link=_link("/incidents", r.incident_id), entity_type="incident", entity_id=r.incident_id,
        ))
    return out


async def my_expiring_exceptions(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.enums import ExceptionStatus
    from app.models.exception import ExceptionRecord

    if not ctx.holds("exception:read"):
        return []
    rows = (await db.execute(
        select(ExceptionRecord.id, ExceptionRecord.reference, ExceptionRecord.title, ExceptionRecord.expires_at,
               ExceptionRecord.requested_by, ExceptionRecord.approver_id, ExceptionRecord.business_owner)
        .where(ExceptionRecord.deleted.is_(False), ExceptionRecord.status == ExceptionStatus.approved,
               ExceptionRecord.expires_at.is_not(None),
               ExceptionRecord.expires_at <= ctx.today + timedelta(days=EXCEPTION_HORIZON_DAYS))
        .limit(ROW_CAP)
    )).all()
    out = []
    for r in rows:
        if r.requested_by == ctx.user_id:
            why = "you raised it"
        elif r.approver_id == ctx.user_id:
            why = "you approved it"
        elif names_me(ctx, r.business_owner):
            why = "you own it"
        else:
            continue
        out.append(ctx.mk(
            "exception_expiry", due=r.expires_at, id=r.id, title=r.title, reference=r.reference or "",
            subtitle=f"Renew, close or let it lapse · {why}",
            link=_link("/exceptions", r.id), entity_type="exception", entity_id=r.id,
        ))
    return out


async def my_declarations(db: AsyncSession, ctx: Ctx) -> list[MyWorkItem]:
    from app.models.declaration import CampaignStatus, Declaration, DeclarationCampaign, DeclarationStatus

    if "declarations" in ctx.modules_off:
        return []
    rows = (await db.execute(
        select(Declaration.id, Declaration.declarant_name, DeclarationCampaign.id.label("campaign_id"),
               DeclarationCampaign.reference, DeclarationCampaign.title, DeclarationCampaign.due_date,
               DeclarationCampaign.period)
        .join(DeclarationCampaign, DeclarationCampaign.id == Declaration.campaign_id)
        .where(DeclarationCampaign.deleted.is_(False), DeclarationCampaign.status == CampaignStatus.open,
               Declaration.status == DeclarationStatus.pending, Declaration.declarant_name != "")
        .limit(ROW_CAP)
    )).all()
    link_ok = ctx.holds("declaration:read")
    return [
        ctx.mk("declaration", due=r.due_date, id=r.id, title=r.title, reference=r.reference or "",
               subtitle=(f"{r.period} · " if r.period else "") + "submit your declaration",
               link=_link("/declarations", r.campaign_id) if link_ok else "",
               entity_type="declaration_campaign", entity_id=r.campaign_id)
        for r in rows if names_me(ctx, r.declarant_name)
    ]


def func_count():
    from sqlalchemy import func

    return func.count()


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
    "attestation_confirm": attestations_to_confirm,
    "kri_measurement": my_kri_readings,
    "rcsa_action": my_rcsa_actions,
    "policy_ack": policies_to_acknowledge,
    # Phase 4B
    "assessment_review": my_assessment_reviews,
    "finding_follow_up": my_findings_to_validate,
    "engagement_task": my_engagement_tasks,
    "audit_remediation": my_audit_remediation,
    "access_review": my_access_reviews,
    "assessment_chase": my_assessment_chases,
    "regulatory_change": my_regulatory_changes,
    "regulatory_return": my_regulatory_returns,
    "incident_report": my_incident_reports,
    "exception_expiry": my_expiring_exceptions,
    "declaration": my_declarations,
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
