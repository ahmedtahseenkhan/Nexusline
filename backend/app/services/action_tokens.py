"""Single-use links that let a named person approve or reject from an e-mail.

* **Shape.** A token is ``<tenant hex>.<token id hex>.<secret>``. The tenant prefix lets
  the unauthenticated endpoint open that organisation's row-level-security scope before
  it can see anything (as the KRI feed does); the id finds the row; the 32-byte secret
  is what proves possession. Only the SHA-256 of the whole token is stored
  (``action_tokens.token_hash``) and the presented token is compared with it in
  constant time. Tokens never enter version history or the audit trail.
* **Bound and short-lived.** Each token names one user, one action
  (:data:`ACTION_DECIDE`) and one record (an approval request); it expires after
  :data:`TOKEN_TTL` (72 hours) and works once — it is claimed with an atomic
  ``UPDATE … WHERE used_at IS NULL`` in the same transaction as the decision, so a
  decision that fails (a rejection without a reason, say) leaves it usable.
* **A GET never decides.** Mail scanners and link previewers follow links, so the
  e-mail's Approve / Reject buttons open a page (``/act?token=…``) that shows what is
  being decided; the person confirms with a POST.
* **The same decision path.** Confirming runs ``approvals.decide_approval`` as the
  token's user — who must still be active and still able to decide the request — so
  segregation of duties, one vote per checker, the reason a rejection needs, approval
  routes and the record's lifecycle apply exactly as in the app. It is audited twice:
  the decision itself, and ``decide_by_email``.
* **Immediate e-mail.** When an approval request is created — from the inbox, a route
  stage or the audit plan — a mapper hook queues it; once the transaction commits, and
  only when SMTP is configured, each person it waits on who may decide it gets a
  "decision needed" e-mail with their own links (:func:`send_decision_requests`). The
  scheduler's digest carries fresh links too.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, object_session, selectinload

from app.models.approval import ApprovalRequest
from app.models.enums import ApprovalStatus
from app.models.notification import ActionToken

logger = logging.getLogger("nexusline.action_tokens")

#: The one action tokens authorise today: deciding an approval request.
ACTION_DECIDE = "approval.decide"
ENTITY_APPROVAL = "approval"
TOKEN_TTL = timedelta(hours=72)
SECRET_BYTES = 32
#: Used and expired tokens are deleted this long after they expire.
TOKEN_RETENTION = timedelta(days=30)

DECISIONS = ("approve", "reject")


# ================================================================ the token ===
def new_token(tenant_id: uuid.UUID, token_id: uuid.UUID) -> str:
    """``<tenant hex>.<token id hex>.<random secret>``. Pure apart from the randomness."""
    return f"{tenant_id.hex}.{token_id.hex}.{secrets.token_urlsafe(SECRET_BYTES)}"


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def parse_token(token: str | None) -> tuple[uuid.UUID, uuid.UUID] | None:
    """``(tenant id, token id)`` of a well-formed token, else None. Pure."""
    parts = (token or "").split(".")
    if len(parts) != 3 or len(parts[2]) < 40:
        return None
    try:
        return uuid.UUID(hex=parts[0]), uuid.UUID(hex=parts[1])
    except ValueError:
        return None


def token_matches(token: str, stored_hash: str) -> bool:
    """Constant-time check of a presented token against the stored hash. Pure."""
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(token_hash(token), stored_hash)


def action_url(token: str, decision: str | None = None) -> str:
    """The confirmation page for a token (``<app>/act?token=…&decision=approve``)."""
    from app.services.email import base_url

    url = f"{base_url()}/act?token={token}"
    return f"{url}&decision={decision}" if decision in DECISIONS else url


def enabled() -> bool:
    """Whether Approve / Reject links may be issued and redeemed (``EMAIL_ACTIONS_ENABLED``)."""
    from app.core.config import settings

    return bool(getattr(settings, "email_actions_enabled", True))


async def issue_token(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, approval_id: uuid.UUID,
    now: datetime | None = None,
) -> str:
    """Store a new token for ``user_id`` to decide ``approval_id`` and return it — the
    only time the token itself exists outside the e-mail."""
    token_id = uuid.uuid4()
    token = new_token(tenant_id, token_id)
    db.add(ActionToken(
        id=token_id, tenant_id=tenant_id, token_hash=token_hash(token), user_id=user_id,
        action=ACTION_DECIDE, entity_type=ENTITY_APPROVAL, entity_id=approval_id,
        expires_at=(now or datetime.now(timezone.utc)) + TOKEN_TTL,
    ))
    return token


# ============================================================ opening a token ===
@dataclass
class TokenContext:
    row: ActionToken
    user: Any
    approval: ApprovalRequest | None
    organisation: str = ""


#: Token states the confirmation page distinguishes.
READY, USED, EXPIRED, NOT_ELIGIBLE, DECIDED = "ready", "used", "expired", "not_eligible", "decided"


def token_state(
    row: Any, user: Any, approval: Any, now: datetime, *, sod: bool | None = None
) -> tuple[str, str]:
    """``(state, message)`` for an opened token. Pure.

    ``ready`` only when the token is unused and unexpired, its user is active, and that
    user may decide the request right now (see ``notifications.approval_refusal``)."""
    from app.services.notifications import approval_refusal

    if getattr(row, "used_at", None) is not None:
        return USED, "This link has already been used."
    if row.expires_at <= now:
        return EXPIRED, "This link has expired. Open the request in NexusLine to decide it."
    if user is None or not getattr(user, "is_active", False):
        return NOT_ELIGIBLE, "This link is no longer valid."
    if approval is None:
        return NOT_ELIGIBLE, "The request this link was for no longer exists."
    status = getattr(approval.status, "value", approval.status)
    if status != ApprovalStatus.pending.value:
        return DECIDED, f"This request is already {status}."
    refusal = approval_refusal(
        approval, user_id=user.id, email=user.email, permissions=user.permission_codes,
        voted_ids=[a.actor_id for a in (approval.actions or [])], sod=sod,
    )
    if refusal:
        return NOT_ELIGIBLE, refusal
    return READY, ""


async def open_token(db: AsyncSession, token: str) -> TokenContext | None:
    """The token's row, user and approval — or None when the token is malformed, for
    another organisation, unknown, or doesn't match (callers answer all of these the
    same way). ``db`` must already be scoped to the token's tenant."""
    from app.models.identity import User
    from app.models.tenant import Tenant

    if not enabled():  # switched off: every link, old or new, is dead
        return None
    parsed = parse_token(token)
    if parsed is None:
        return None
    tenant_id, token_id = parsed
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None or not tenant.is_active:
        return None
    row = await db.get(ActionToken, token_id)
    if row is None or row.tenant_id != tenant_id or not token_matches(token, row.token_hash):
        return None
    if row.action != ACTION_DECIDE or row.entity_type != ENTITY_APPROVAL:
        return None
    user = await db.get(User, row.user_id)
    approval = await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == row.entity_id)
        .options(selectinload(ApprovalRequest.actions))
    )
    return TokenContext(row=row, user=user, approval=approval, organisation=tenant.name)


async def claim(db: AsyncSession, row: ActionToken, now: datetime) -> bool:
    """Mark the token used, atomically: False when another request got there first."""
    claimed = await db.scalar(
        update(ActionToken)
        .where(ActionToken.id == row.id, ActionToken.used_at.is_(None))
        .values(used_at=now)
        .returning(ActionToken.id)
    )
    return claimed is not None


# ========================================================== decision e-mails ===
def decision_makers(approval: Any, directory: Any, *, sod: bool | None = None) -> list[uuid.UUID]:
    """The active users a pending request is waiting on who may decide it now: the named
    person, or the members of the named (or approving) roles — minus the maker and
    anyone who has already voted. Pure."""
    from app.services.notifications import USER, approval_recipients, approval_refusal

    candidates: list[uuid.UUID] = []
    for kind, value in approval_recipients(approval, directory):
        candidates.extend([value] if kind == USER else directory.members(value))
    voted = {a.actor_id for a in (getattr(approval, "actions", None) or [])}
    out: list[uuid.UUID] = []
    for uid in dict.fromkeys(candidates):
        person = directory.users.get(uid)
        if person is None or not person.is_active or not person.email:
            continue
        if approval_refusal(
            approval, user_id=uid, email=person.email, permissions=directory.permissions_of(uid),
            voted_ids=voted, sod=sod,
        ) is None:
            out.append(uid)
    return out


async def email_decision_request(db: AsyncSession, tenant_id: uuid.UUID, approval_id: uuid.UUID) -> int:
    """E-mail everyone a pending request waits on (and may decide) their own Approve /
    Reject links. Returns how many messages were dispatched. No-op without SMTP, so no
    token is minted for a message nobody will receive."""
    from app.models.tenant import Tenant
    from app.services import email as email_service
    from app.services import notifications

    if not email_service.is_configured() or not enabled():
        return 0
    approval = await db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .options(selectinload(ApprovalRequest.actions))
    )
    if approval is None or approval.status != ApprovalStatus.pending:
        return 0
    directory = await notifications.load_directory(db)
    tenant = await db.get(Tenant, tenant_id)
    org = tenant.name if tenant is not None else "NexusLine"
    now = datetime.now(timezone.utc)
    sent = 0
    for uid in decision_makers(approval, directory):
        person = directory.users[uid]
        token = await issue_token(db, tenant_id=tenant_id, user_id=uid, approval_id=approval.id, now=now)
        subject, html, text = email_service.render_decision_request(
            org, approval, recipient_name=person.full_name or person.email,
            approve_url=action_url(token, "approve"), reject_url=action_url(token, "reject"),
            open_url=email_service.absolute_url(notifications.with_id("/approvals", approval.id)),
        )
        if await email_service.send_email([person.email], subject, html, text):
            sent += 1
    await db.flush()
    return sent


async def send_decision_requests(items: Sequence[tuple[uuid.UUID, uuid.UUID]]) -> int:
    """Background job: one decision-request e-mail round per ``(tenant, approval)``,
    each in its own tenant-scoped transaction; one failure never stops the rest."""
    from app.core.database import tenant_session

    sent = 0
    for tenant_id, approval_id in items:
        try:
            async with tenant_session(tenant_id) as db:
                sent += await email_decision_request(db, tenant_id, approval_id)
        except Exception:  # noqa: BLE001 - a background mail job must not crash the loop
            logger.exception("Decision-request e-mail failed for approval %s", approval_id)
    return sent


# -------------------------------------------------------------- the hook ---
_QUEUE_KEY = "nexusline.decision_requests"
_TASKS: set[asyncio.Task] = set()


def queued_items(info: dict) -> list[tuple[uuid.UUID, uuid.UUID]]:
    return sorted(info.get(_QUEUE_KEY) or (), key=lambda item: (str(item[0]), str(item[1])))


def _queue_new_approval(mapper, connection, target) -> None:  # noqa: ARG001 - SQLAlchemy signature
    session = object_session(target)
    status = getattr(getattr(target, "status", None), "value", getattr(target, "status", None))
    if session is not None and status == ApprovalStatus.pending.value and target.tenant_id and target.id:
        session.info.setdefault(_QUEUE_KEY, set()).add((target.tenant_id, target.id))


def _send_after_commit(session: Session) -> None:
    items = queued_items(session.info)
    session.info.pop(_QUEUE_KEY, None)
    if not items:
        return
    from app.services import email as email_service

    if not email_service.is_configured():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # committed outside an event loop (a script): nothing to schedule on
        return
    task = loop.create_task(send_decision_requests(items))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _forget_after_rollback(session: Session) -> None:
    session.info.pop(_QUEUE_KEY, None)


def install_hooks() -> None:
    """Register the approval-created hooks once (idempotent — safe on re-import)."""
    if not event.contains(ApprovalRequest, "after_insert", _queue_new_approval):
        event.listen(ApprovalRequest, "after_insert", _queue_new_approval)
    if not event.contains(Session, "after_commit", _send_after_commit):
        event.listen(Session, "after_commit", _send_after_commit)
    if not event.contains(Session, "after_rollback", _forget_after_rollback):
        event.listen(Session, "after_rollback", _forget_after_rollback)


install_hooks()


# ------------------------------------------------------------- housekeeping ---
async def purge_stale(db: AsyncSession, now: datetime | None = None) -> int:
    """Delete tokens that expired more than :data:`TOKEN_RETENTION` ago."""
    from sqlalchemy import delete

    cutoff = (now or datetime.now(timezone.utc)) - TOKEN_RETENTION
    result = await db.execute(delete(ActionToken).where(ActionToken.expires_at < cutoff))
    return int(getattr(result, "rowcount", 0) or 0)


def links_for(tokens: Iterable[tuple[Any, str]]) -> dict:
    """``{approval id: DecisionLinks}`` from ``(approval id, token)`` pairs."""
    from app.services.email import DecisionLinks

    return {aid: DecisionLinks(approve=action_url(t, "approve"), reject=action_url(t, "reject")) for aid, t in tokens}
