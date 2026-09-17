"""The respondent portal: token links, rate limits, access logging and upload limits
(product review phase 4E).

* **Token.** ``<tenant hex>.<link id hex>.<secret>`` (the shape of ``action_tokens``): the
  tenant prefix lets the public endpoint open that organisation's row-level-security scope,
  the id finds the link, the 32-byte secret proves possession. Only the SHA-256 of the
  whole token is stored (``assessment_links.token_hash``) and compared in constant time.
  The token exists only in the response that created it and in the e-mail.
* **Life.** A link expires (1–90 days, default 30), can be revoked, and "resend" revokes the
  old link and issues a new one. Reminders issue a fresh link and leave earlier ones valid
  until they expire. Unlike an approval link, a portal link is reusable — the respondent
  saves drafts over days — so it is not single-use.
* **What a link can do.** Read the questionnaire (no scores, no risk flags), save answers
  and upload evidence while the assessment is sent / in progress, and submit. After the
  reviewer returns answers, only those answers can change. Nothing else.
* **Rate limit.** Shared token buckets (:mod:`app.services.rate_limit`): :data:`IP_LIMIT` requests per
  :data:`WINDOW_SECONDS` per client address and :data:`LINK_LIMIT` per link; a refused
  request is a 429. (One process per deployment; a multi-process deployment should also
  rate-limit ``/api/v1/respond`` at the reverse proxy.)
* **Audit.** Every request through a link that names this organisation writes an
  ``assessment_access_logs`` row with the address and user agent, including refusals
  (expired, revoked, wrong secret). Saves, uploads and submission are also in the audit
  trail, attributed to the contact ("name <email> via respondent link").
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Any

from app.models.assessment import AssessmentAccessLog, AssessmentLink
from app.services.rate_limit import RateLimiter

SECRET_BYTES = 32
DEFAULT_EXPIRY_DAYS = 30
MAX_EXPIRY_DAYS = 90
WINDOW_SECONDS = 300
IP_LIMIT = 300
LINK_LIMIT = 200

#: Evidence uploads: size cap (MB) and accepted file types.
MAX_UPLOAD_MB = 10
ALLOWED_EXTENSIONS: dict[str, tuple[str, ...]] = {
    ".pdf": ("application/pdf",),
    ".png": ("image/png",),
    ".jpg": ("image/jpeg",),
    ".jpeg": ("image/jpeg",),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
    ".csv": ("text/csv", "application/vnd.ms-excel", "text/plain"),
    ".txt": ("text/plain",),
    ".zip": ("application/zip", "application/x-zip-compressed"),
}
MAX_FILES_PER_ANSWER = 10

ACTIVE, EXPIRED, REVOKED = "active", "expired", "revoked"
EDITABLE_STATUSES = frozenset({"sent", "in_progress"})


# ================================================================== tokens ===
def new_token(tenant_id: uuid.UUID, link_id: uuid.UUID) -> str:
    return f"{tenant_id.hex}.{link_id.hex}.{secrets.token_urlsafe(SECRET_BYTES)}"


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def parse_token(token: str | None) -> tuple[uuid.UUID, uuid.UUID] | None:
    """``(tenant id, link id)`` of a well-formed token, else None. Pure."""
    parts = (token or "").split(".")
    if len(parts) != 3 or len(parts[2]) < 40:
        return None
    try:
        return uuid.UUID(hex=parts[0]), uuid.UUID(hex=parts[1])
    except ValueError:
        return None


def token_matches(token: str, stored_hash: str) -> bool:
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(token_hash(token), stored_hash)


def link_state(link: Any, now: datetime) -> str:
    """active | expired | revoked. Pure."""
    if getattr(link, "revoked_at", None) is not None:
        return REVOKED
    expires = link.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return EXPIRED if expires <= now else ACTIVE


def respond_url(token: str) -> str:
    from app.services.email import base_url

    return f"{base_url()}/respond/{token}"


def issue_link(
    *, tenant_id: uuid.UUID, assessment_id: uuid.UUID, contact_name: str, contact_email: str,
    expires_in_days: int = DEFAULT_EXPIRY_DAYS, reason: str = "manual", created_by_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> tuple[AssessmentLink, str]:
    """A new link row (not yet added to the session) and its token — the only time the
    token exists outside the e-mail."""
    days = max(1, min(int(expires_in_days or DEFAULT_EXPIRY_DAYS), MAX_EXPIRY_DAYS))
    link_id = uuid.uuid4()
    token = new_token(tenant_id, link_id)
    link = AssessmentLink(
        id=link_id, tenant_id=tenant_id, assessment_id=assessment_id, token_hash=token_hash(token),
        contact_name=(contact_name or "").strip()[:200], contact_email=(contact_email or "").strip()[:255],
        reason=reason, expires_at=(now or datetime.now(timezone.utc)) + timedelta(days=days),
        created_by_id=created_by_id, use_count=0,
    )
    return link, token


# ============================================================== rate limit ===
# Shared token buckets (Redis when it answers, else per worker): IP_LIMIT calls per
# WINDOW_SECONDS per client address, LINK_LIMIT per link.
ip_limiter = RateLimiter("respond-ip", capacity=IP_LIMIT, per_second=IP_LIMIT / WINDOW_SECONDS)
link_limiter = RateLimiter("respond-link", capacity=LINK_LIMIT, per_second=LINK_LIMIT / WINDOW_SECONDS)


def client_address(request: Any) -> str:
    """The caller's address: the first ``X-Forwarded-For`` hop when a proxy set one."""
    headers = getattr(request, "headers", {}) or {}
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    client = getattr(request, "client", None)
    return (getattr(client, "host", "") or "")[:64]


def user_agent(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    return (headers.get("user-agent") or "")[:400]


def access_log(
    *, tenant_id: uuid.UUID, assessment_id: uuid.UUID | None, link_id: uuid.UUID | None, action: str,
    request: Any, outcome: str = "ok", detail: str = "",
) -> AssessmentAccessLog:
    return AssessmentAccessLog(
        tenant_id=tenant_id, assessment_id=assessment_id, link_id=link_id, action=action[:24],
        outcome=outcome[:16], detail=(detail or "")[:255], ip_address=client_address(request),
        user_agent=user_agent(request),
    )


# ================================================================= uploads ===
def upload_refusal(filename: str | None, content_type: str | None) -> str | None:
    """Why this file type is refused, or None. Pure."""
    ext = PurePath(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return (
            f"Files of type '{ext or 'unknown'}' can't be uploaded. Accepted: "
            + ", ".join(sorted(e.lstrip(".").upper() for e in ALLOWED_EXTENSIONS)) + "."
        )
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype and ctype != "application/octet-stream" and ctype not in ALLOWED_EXTENSIONS[ext]:
        return f"The file's content type ({ctype}) does not match its {ext} extension."
    return None


@dataclass(frozen=True)
class PortalActor:
    """Who the audit trail names for a respondent-link action."""

    tenant_id: uuid.UUID
    email: str
    id: uuid.UUID | None = None
    permission_codes: tuple[str, ...] = ()


def portal_actor(tenant_id: uuid.UUID, link: Any) -> PortalActor:
    name = (getattr(link, "contact_name", "") or "").strip()
    email = (getattr(link, "contact_email", "") or "").strip()
    who = f"{name} <{email}>" if name and email else (email or name or "respondent")
    return PortalActor(tenant_id=tenant_id, email=f"{who} via respondent link"[:255])
