"""Approval Workflows API — submit records for approval, decide, cancel."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.approval import ApprovalAction, ApprovalRequest
from app.models.enums import ApprovalStatus, NotificationCategory
from app.schemas.approval import ApprovalCreate, ApprovalDecision, ApprovalRead
from app.schemas.common import Page
from app.services.refs import next_reference
from app.services import audit

router = APIRouter(prefix="/approvals", tags=["approvals"])

# Allow-listed sort columns for the approval queue.
_SORTABLE = {
    "created_at": ApprovalRequest.created_at,
    "status": ApprovalRequest.status,
    "due_date": ApprovalRequest.due_date,
    "reference": ApprovalRequest.reference,
}


async def _load(db, approval_id: uuid.UUID) -> ApprovalRequest:
    obj = await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .options(selectinload(ApprovalRequest.actions))
    )
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return obj


async def _next_ref(db) -> str:
    return await next_reference(db, ApprovalRequest, "APR")


# ------------------------------------------------------- segregation of duties ---
_SOD_DETAIL = (
    "Segregation of duties: the maker of a request cannot approve it — "
    "an independent checker must decide."
)


def is_maker(
    requested_by: uuid.UUID | None,
    requested_by_email: str | None,
    user_id: uuid.UUID | None,
    user_email: str | None,
) -> bool:
    """Whether this user raised the request.

    The id is authoritative when present. The e-mail is checked as well
    (case-insensitively) because requests raised by imports, integrations and older
    seed data carry only the maker's address; without it those would have no maker at
    all and anyone — including the person who raised them — could approve them.
    """
    if requested_by is not None and user_id is not None and requested_by == user_id:
        return True
    maker_email = (requested_by_email or "").strip().lower()
    return bool(maker_email) and maker_email == (user_email or "").strip().lower()


def require_maker_identity(requested_by: uuid.UUID | None, requested_by_email: str | None) -> None:
    """A request nobody can be identified as having raised cannot be checked for
    segregation of duties, so it is refused rather than stored."""
    if requested_by is None and not (requested_by_email or "").strip():
        raise HTTPException(
            status_code=422,
            detail="An approval request must record who raised it (maker id or e-mail).",
        )


#: Holders of this permission design approval routes, so they may also withdraw any
#: pending request — the administrator's escape hatch for a request raised in error.
CANCEL_ANY_PERMISSION = "automation:manage"

_CANCEL_DETAIL = (
    "Only the person who submitted this request, or an administrator who manages approval "
    "routes, can cancel it."
)


def may_cancel(
    obj: ApprovalRequest,
    user_id: uuid.UUID | None,
    user_email: str | None,
    permission_codes,
) -> bool:
    """Whether this user may cancel (or delete) the request: its maker, or an administrator.

    A checker who could cancel a request would have a quiet way to make a decision without
    recording one, so everyone else is refused.
    """
    if CANCEL_ANY_PERMISSION in set(permission_codes or ()):
        return True
    return is_maker(obj.requested_by, obj.requested_by_email, user_id, user_email)


def enforce_sod(obj: ApprovalRequest, user_id: uuid.UUID | None, user_email: str | None) -> None:
    """403 when segregation of duties is on and the would-be checker is the maker."""
    if settings.enforce_segregation_of_duties and is_maker(
        obj.requested_by, obj.requested_by_email, user_id, user_email
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_SOD_DETAIL)


async def _decision_context(db, rows) -> tuple[object, dict]:
    """The directory and the stage gates for ``rows`` — what the shared eligibility rule
    (``notifications.decision_refusal``) reads."""
    from app.services import notifications

    directory = await notifications.load_directory(db)
    return directory, await notifications.load_stage_gates(db, rows, directory)


async def finishing_approvals(db, rows) -> set[uuid.UUID]:
    """The pending requests among ``rows`` on which one more approval finishes the
    record's review — the approval ``record_workflow.write_back`` then writes onto the
    record, and the one its precondition and the delegation of authority govern: the
    last vote a request needs, on a request that is not a route stage or is its route's
    last pending stage."""
    from app.models.workflow import (
        StageStatus2,
        WorkflowInstance,
        WorkflowInstanceStage,
        WorkflowInstanceStatus,
    )

    last_vote = [
        r for r in rows
        if r.status == ApprovalStatus.pending and r.entity_id is not None
        and r.approvals_received + 1 >= (r.required_approvals or 1)
    ]
    if not last_vote:
        return set()
    stage_of = dict((await db.execute(
        select(WorkflowInstanceStage.approval_request_id, WorkflowInstanceStage.instance_id)
        .where(WorkflowInstanceStage.approval_request_id.in_([r.id for r in last_vote]))
    )).all())
    open_stages: dict = {}
    if stage_of:
        open_stages = dict((await db.execute(
            select(WorkflowInstanceStage.instance_id, func.count())
            .join(WorkflowInstance, WorkflowInstance.id == WorkflowInstanceStage.instance_id)
            .where(
                WorkflowInstanceStage.instance_id.in_(set(stage_of.values())),
                WorkflowInstanceStage.status.in_((StageStatus2.pending, StageStatus2.in_progress)),
                WorkflowInstance.status == WorkflowInstanceStatus.in_progress,
            )
            .group_by(WorkflowInstanceStage.instance_id)
        )).all())
    return {
        r.id for r in last_vote
        if r.id not in stage_of or open_stages.get(stage_of[r.id], 0) <= 1
    }


async def approve_blocks(db, rows, user) -> dict[uuid.UUID, str]:
    """``{request id: why this user's approval would be refused}`` for the requests in
    ``rows`` whose approval would finish a record that is not ready for it or whose
    amount is above the user's mandate (``lifecycle_gates.write_back_refusal`` — the
    check ``write_back`` makes). Loads only the records of checked types."""
    from app.services import lifecycle_gates

    candidates = [r for r in rows if lifecycle_gates.approval_is_checked(r.entity_type)]
    if not candidates or user is None:
        return {}
    finishing = await finishing_approvals(db, candidates)
    out: dict[uuid.UUID, str] = {}
    for r in candidates:
        if r.id not in finishing:
            continue
        refusal = await lifecycle_gates.write_back_refusal(db, r.entity_type, r.entity_id, user)
        if refusal:
            out[r.id] = refusal
    return out


async def _annotate(db, rows, user) -> list[ApprovalRead]:
    """``ApprovalRead`` for each request, with what this user may do and — for a route
    stage assigned to a role — how many people other than the maker could decide it.

    ``can_decide`` / ``decide_blocked_reason`` come from ``notifications.decision_refusal``,
    the rule the decide endpoint, My Work, the alert recipients and the e-mail links use,
    so a request offered anywhere can be decided and vice versa. ``can_approve`` /
    ``approve_blocked_reason`` add what the approval itself would be refused for
    (:func:`approve_blocks`); a user who can decide but not approve may still reject."""
    from app.services import default_governance as governance
    from app.services import notifications

    _directory, gates = await _decision_context(db, rows)
    codes = set(user.permission_codes) if user is not None else set()
    blocks = await approve_blocks(db, rows, user)
    out = []
    for r in rows:
        read = ApprovalRead.model_validate(r)
        gate = gates.get(r.id)
        extra: dict = {}
        if gate is not None:
            extra["approver_role"] = gate.role
            extra["approver_role_holders"] = gate.eligible
            if gate.eligible == 0 and r.status == ApprovalStatus.pending:
                only_maker = gate.holders > 0 and gate.maker_holds and gate.holders == 1
                lacks = gate.holders > (1 if gate.maker_holds else 0)
                extra["approver_role_gap"] = governance.role_gap_message(
                    gate.role, only_maker=only_maker and not lacks, lacks_permission=lacks,
                )
        if user is not None:
            extra["can_cancel"] = r.status == ApprovalStatus.pending and may_cancel(
                r, user.id, user.email, codes
            )
            blocked = None
            if r.status == ApprovalStatus.pending:
                blocked = notifications.approval_refusal(
                    r, user_id=user.id, email=user.email, permissions=codes,
                    role_names=user.role_names, voted_ids=[a.actor_id for a in r.actions], stage=gate,
                )
            extra["can_decide"] = r.status == ApprovalStatus.pending and blocked is None
            extra["decide_blocked_reason"] = blocked
            extra["approve_blocked_reason"] = blocks.get(r.id) if extra["can_decide"] else None
            extra["can_approve"] = extra["can_decide"] and r.id not in blocks
        out.append(read.model_copy(update=extra))
    return out


async def enforce_stage_role(db, obj: ApprovalRequest, user) -> None:
    """403 when the request is a route stage assigned to a role this user does not hold
    and someone other than the maker holds it and can approve. With no such person the
    stage falls back to anyone who can approve, and the Approvals page says so."""
    from app.services import default_governance as governance

    _directory, gates = await _decision_context(db, [obj])
    gate = gates.get(obj.id)
    if gate is None:
        return
    # The stage step of ``notifications.decision_refusal``, with the same gate.
    refusal = governance.stage_decision_refusal(gate.role, user.role_names, gate.eligible)
    if refusal:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=refusal)


@router.get("", response_model=Page[ApprovalRead], dependencies=[Depends(require("workflow:read"))])
async def list_approvals(
    db: DbSession,
    user: CurrentUser,
    search: str | None = None,
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ApprovalRead]:
    stmt: Select = select(ApprovalRequest)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(ApprovalRequest.title.ilike(like) | ApprovalRequest.reference.ilike(like))
    if status_filter is not None:
        stmt = stmt.where(ApprovalRequest.status == status_filter)
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=None)
        stmt = apply_sort(stmt, params, _SORTABLE, default=ApprovalRequest.created_at)
    else:
        stmt = stmt.order_by(ApprovalRequest.created_at.desc())
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(
            stmt.options(selectinload(ApprovalRequest.actions))
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page(items=await _annotate(db, rows, user), total=total, limit=limit, offset=offset)


@router.post("", response_model=ApprovalRead, status_code=201, dependencies=[Depends(require("workflow:write"))])
async def submit_approval(body: ApprovalCreate, db: DbSession, user: CurrentUser) -> ApprovalRead:
    obj = ApprovalRequest(
        tenant_id=user.tenant_id,
        requested_by=user.id,
        requested_by_email=user.email,
        **body.model_dump(),
    )
    require_maker_identity(obj.requested_by, obj.requested_by_email)
    obj.reference = await _next_ref(db)
    db.add(obj)
    await db.flush()
    await audit.record(
        db, actor=user, action="submit", entity_type="approval", entity_id=obj.id,
        summary=f"Submitted approval {obj.reference}: {obj.title}",
    )
    return ApprovalRead.model_validate(await _load(db, obj.id))


@router.get("/{approval_id}", response_model=ApprovalRead, dependencies=[Depends(require("workflow:read"))])
async def get_approval(approval_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ApprovalRead:
    return (await _annotate(db, [await _load(db, approval_id)], user))[0]


@router.post(
    "/{approval_id}/decision",
    response_model=ApprovalRead,
    dependencies=[Depends(require("workflow:approve"))],
    summary="Approve or reject a pending approval request (maker-checker enforced)",
)
async def decide_approval(
    approval_id: uuid.UUID, body: ApprovalDecision, db: DbSession, user: CurrentUser
) -> ApprovalRead:
    obj = await _load(db, approval_id)
    if obj.status != ApprovalStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Already {obj.status.value}"
        )

    # Segregation of Duties: the maker (submitter) can never be a checker (approver) —
    # matched on the maker's id, or on their e-mail when the request carries only that.
    enforce_sod(obj, user.id, user.email)
    # A route stage assigned to a role is decided by a holder of that role (when anyone
    # other than the maker holds it — otherwise it would dead-end).
    await enforce_stage_role(db, obj, user)
    # One decision per checker (prevents a single user counting twice toward N-eyes).
    if any(a.actor_id == user.id for a in obj.actions):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already recorded a decision on this request.",
        )
    # A rejection must carry a documented reason (audit requirement).
    if not body.approve and not (body.comment or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A reason is required to reject an approval request.",
        )

    action = ApprovalAction(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        actor_email=user.email,
        action="approve" if body.approve else "reject",
        comment=body.comment,
    )
    obj.actions.append(action)

    if not body.approve:
        obj.status = ApprovalStatus.rejected
        obj.decided_by = user.id
        obj.decided_by_email = user.email
        obj.decided_at = date.today()
        obj.decision_comment = body.comment
        summary = f"Rejected approval {obj.reference}"
    else:
        received = obj.approvals_received  # includes the vote just appended
        if received >= obj.required_approvals:
            obj.status = ApprovalStatus.approved
            obj.decided_by = user.id
            obj.decided_by_email = user.email
            obj.decided_at = date.today()
            obj.decision_comment = body.comment
            summary = f"Approved approval {obj.reference} ({received}/{obj.required_approvals})"
        else:
            summary = (
                f"Recorded approval {received}/{obj.required_approvals} for {obj.reference} "
                f"(awaiting {obj.required_approvals - received} more)"
            )

    await db.flush()

    # If this approval was one stage of a user-defined route, the decision moves the
    # record on — opening the next stage, or finishing/terminating the route. Approvals
    # that are not part of a workflow (the overwhelming majority) are untouched.
    from app.services import notifications as notifications_service
    from app.services import workflow_engine

    instance = await workflow_engine.on_approval_decided(db, obj, actor=user)
    if instance is None and obj.status in (ApprovalStatus.approved, ApprovalStatus.rejected):
        # A single-stage request raised against a record: its final decision is the
        # record's review outcome — approved, or back to draft. (A route's outcome is
        # written by the engine when the last stage lands.)
        from app.services import record_workflow

        new_state = await record_workflow.write_back(
            db,
            entity_type=obj.entity_type,
            entity_id=obj.entity_id,
            approved=obj.status == ApprovalStatus.approved,
            via=f"approval {obj.reference}",
            comment=obj.decision_comment or "",
            actor=user,
        )
        if new_state:
            summary += f" · record now {new_state.replace('_', ' ')}"
    if instance is not None:
        summary += (
            f" · workflow {instance.completed_stages}/{instance.total_stages}"
            f" ({instance.status.value})"
        )
        if instance.status.value in ("approved", "rejected"):
            # The submitter asked to be told when the whole route lands, not each stage.
            from app.models.notification import Notification

            db.add(
                Notification(
                    tenant_id=user.tenant_id,
                    title=(
                        f"Approval route {instance.status.value}: {instance.entity_label}"
                        if instance.entity_label
                        else f"Approval route {instance.status.value}"
                    ),
                    body=(
                        f"All {instance.total_stages} stage(s) decided."
                        if instance.status.value == "approved"
                        else f"Rejected at stage {obj.title}."
                    ),
                    category=(
                        NotificationCategory.info
                        if instance.status.value == "approved"
                        else NotificationCategory.warning
                    ),
                    entity_type=instance.entity_type,
                    entity_id=instance.entity_id,
                    link=obj.link,
                    # Phase 3: to the person who started the route (they asked to be told).
                    user_id=instance.started_by,
                    dedup_key=f"{notifications_service.EVENT_PREFIX}workflow-done:{instance.id}",
                )
            )
            await db.flush()

    await audit.record(
        db, actor=user, action="decide", entity_type="approval", entity_id=obj.id, summary=summary
    )
    return ApprovalRead.model_validate(await _load(db, obj.id))


@router.post(
    "/{approval_id}/cancel",
    response_model=ApprovalRead,
    dependencies=[Depends(require("workflow:write"))],
)
async def cancel_approval(approval_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ApprovalRead:
    """Withdraw a pending request. Only its maker, or an administrator who manages
    approval routes (``automation:manage``), may. A request that is a stage of an approval
    route cancels the whole route, and the record goes back to draft."""
    from app.models.workflow import WorkflowInstance, WorkflowInstanceStage, WorkflowInstanceStatus
    from app.services import record_workflow, workflow_engine

    obj = await _load(db, approval_id)
    if obj.status != ApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only pending can be cancelled")
    if not may_cancel(obj, user.id, user.email, user.permission_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_CANCEL_DETAIL)
    instance = await db.scalar(
        select(WorkflowInstance)
        .join(WorkflowInstanceStage, WorkflowInstanceStage.instance_id == WorkflowInstance.id)
        .where(
            WorkflowInstanceStage.approval_request_id == obj.id,
            WorkflowInstance.status == WorkflowInstanceStatus.in_progress,
        )
    )
    if instance is not None:
        await workflow_engine.cancel(db, instance, actor=user)
    obj.status = ApprovalStatus.cancelled
    await db.flush()
    if instance is None and obj.entity_id is not None:
        # A single request withdrawn: the record leaves review exactly as a route
        # cancellation would leave it, instead of sitting "submitted" with nothing pending.
        await record_workflow.write_back(
            db, entity_type=obj.entity_type, entity_id=obj.entity_id, approved=False,
            via="approvals", actor=user, action="withdraw",
        )
    await audit.record(
        db, actor=user, action="cancel", entity_type="approval", entity_id=obj.id,
        summary=f"Cancelled approval {obj.reference}"
        + (" and its approval route" if instance is not None else ""),
    )
    return (await _annotate(db, [await _load(db, obj.id)], user))[0]


@router.delete("/{approval_id}", status_code=204, dependencies=[Depends(require("workflow:write"))])
async def delete_approval(approval_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load(db, approval_id)
    if not may_cancel(obj, user.id, user.email, user.permission_codes):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_CANCEL_DETAIL)
    await db.delete(obj)
    await audit.record(
        db, actor=user, action="delete", entity_type="approval", entity_id=obj.id,
        summary=f"Deleted approval {obj.reference}",
    )


# ========================================================== decide from an e-mail ===
# Phase 3 (F-15). An approval request's e-mail carries Approve / Reject links with a
# single-use token (``services/action_tokens.py``: SHA-256 stored, 72-hour expiry,
# bound to one user, action and request, tenant id inside the token). Neither endpoint
# takes a session — the token is the credential:
#
# * ``GET /actions/{token}`` says what the link would decide and whether it still can.
#   It never decides: mail scanners and link previewers follow links.
# * ``POST /actions/{token}/confirm`` validates the token (constant-time hash compare,
#   unused, unexpired, its user still active and still able to decide), claims it and
#   runs ``decide_approval`` above as that user — segregation of duties, one vote per
#   checker, the reason a rejection needs, routes and the record's lifecycle all apply —
#   then audits ``decide_by_email``. A refused decision rolls the claim back.
#
# ``email_router`` is mounted by ``api/v1/my_work.py`` so the phase-3 surface registers
# with one line in ``router.py``.
from datetime import datetime, timezone  # noqa: E402

from app.core.database import tenant_session  # noqa: E402
from app.models.settings import TenantSettings  # noqa: E402
from app.schemas.my_work import (  # noqa: E402
    EmailActionApproval,
    EmailActionConfirm,
    EmailActionPreview,
    EmailActionResult,
)
from app.services import action_tokens  # noqa: E402

email_router = APIRouter(prefix="/actions", tags=["approvals"])

#: HTTP status for a token that opened but can't be used now.
_TOKEN_STATE_STATUS = {
    action_tokens.USED: status.HTTP_410_GONE,
    action_tokens.EXPIRED: status.HTTP_410_GONE,
    action_tokens.DECIDED: status.HTTP_409_CONFLICT,
    action_tokens.NOT_ELIGIBLE: status.HTTP_403_FORBIDDEN,
}


def _link_denied() -> HTTPException:
    """One answer for a malformed, unknown, other-organisation or wrong token."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="This link is not valid. Open NexusLine to find the request.",
    )


def _email_summary(obj: ApprovalRequest | None) -> EmailActionApproval | None:
    if obj is None:
        return None
    return EmailActionApproval(
        id=obj.id, reference=obj.reference or "", title=obj.title or "",
        description=obj.description or "", entity_type=obj.entity_type or "",
        entity_label=obj.entity_label or "", approver=obj.approver or "",
        requested_by_email=obj.requested_by_email or "", due_date=obj.due_date,
        required_approvals=obj.required_approvals or 1,
        approvals_received=obj.approvals_received, created_at=obj.created_at,
        status=getattr(obj.status, "value", str(obj.status)),
    )


@email_router.get(
    "/{token}",
    response_model=EmailActionPreview,
    summary="What an e-mailed Approve / Reject link decides (read-only; never decides)",
)
async def preview_email_action(token: str) -> EmailActionPreview:
    parsed = action_tokens.parse_token(token)
    if parsed is None:
        raise _link_denied()
    async with tenant_session(parsed[0]) as db:
        ctx = await action_tokens.open_token(db, token)
        if ctx is None:
            raise _link_denied()
        state, message = action_tokens.token_state(
            ctx.row, ctx.user, ctx.approval, datetime.now(timezone.utc), stage=ctx.stage
        )
        locale = (await db.execute(select(TenantSettings.date_format, TenantSettings.timezone))).first()
        blocked = ""
        if state == action_tokens.READY:
            blocked = (await approve_blocks(db, [ctx.approval], ctx.user)).get(ctx.approval.id, "")
        return EmailActionPreview(
            state=state, message=message, organisation=ctx.organisation,
            approve_blocked_reason=blocked,
            user_name=(ctx.user.full_name or ctx.user.email) if ctx.user is not None else "",
            expires_at=ctx.row.expires_at, approval=_email_summary(ctx.approval),
            **({"date_format": locale[0], "timezone": locale[1]} if locale else {}),
        )


@email_router.post(
    "/{token}/confirm",
    response_model=EmailActionResult,
    summary="Confirm an e-mailed approval decision (single-use token, no session)",
)
async def confirm_email_action(token: str, body: EmailActionConfirm) -> EmailActionResult:
    parsed = action_tokens.parse_token(token)
    if parsed is None:
        raise _link_denied()
    now = datetime.now(timezone.utc)
    async with tenant_session(parsed[0]) as db:
        ctx = await action_tokens.open_token(db, token)
        if ctx is None:
            raise _link_denied()
        state, message = action_tokens.token_state(ctx.row, ctx.user, ctx.approval, now, stage=ctx.stage)
        if state != action_tokens.READY:
            raise HTTPException(status_code=_TOKEN_STATE_STATUS.get(state, 403), detail=message)
        if body.decision == "approve":
            # Refuse before claiming the link, so a refused Approve leaves it usable to reject.
            blocked = (await approve_blocks(db, [ctx.approval], ctx.user)).get(ctx.approval.id)
            if blocked:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=blocked)
        if not await action_tokens.claim(db, ctx.row, now):
            raise HTTPException(status_code=status.HTTP_410_GONE, detail="This link has already been used.")
        approve = body.decision == "approve"
        read = await decide_approval(
            ctx.approval.id, ApprovalDecision(approve=approve, comment=body.comment), db, ctx.user
        )
        verb = "approved" if approve else "rejected"
        await audit.record(
            db, actor=ctx.user, action="decide_by_email", entity_type="approval",
            entity_id=ctx.approval.id,
            summary=f"Decided by email: {verb} approval {read.reference}",
            changes={"decision": body.decision, "via": "email link", "token_id": str(ctx.row.id),
                     "status": read.status.value},
        )
        refreshed = await _load(db, ctx.approval.id)
        outcome = (
            f"Recorded your approval ({read.approvals_received} of {read.required_approvals})."
            if approve and read.status == ApprovalStatus.pending
            else f"The request is {read.status.value}."
        )
        return EmailActionResult(
            decision=body.decision, message=f"You {verb} {read.reference}. {outcome}",
            approval=_email_summary(refreshed),
        )
