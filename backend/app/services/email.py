"""Outbound email via SMTP, with a dev-safe fallback.

When ``settings.smtp_host`` is empty (the default) nothing is sent — the message is
logged instead, so local/dev runs never fail for lack of a mail server. Configure
SMTP_* env vars to enable real delivery. Sending uses the stdlib ``smtplib`` on a
worker thread (``asyncio.to_thread``) so the event loop is never blocked, avoiding a
hard third-party dependency.
"""
from __future__ import annotations

import asyncio
import logging
import re
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("nexusline.email")

_TAGS = re.compile(r"<[^>]+>")


def is_configured() -> bool:
    return bool(settings.smtp_host)


def _html_to_text(html: str) -> str:
    text = re.sub(r"<(br|/p|/div|/li|/tr)[^>]*>", "\n", html, flags=re.I)
    return _TAGS.sub("", text).strip()


def _send_sync(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def send_email(
    to: list[str] | str, subject: str, html: str, text: str | None = None
) -> bool:
    """Send one email. Returns True if actually dispatched, False in dev fallback."""
    recipients = [to] if isinstance(to, str) else list(to)
    recipients = [r for r in recipients if r]
    if not recipients:
        return False

    if not is_configured():
        logger.info(
            "[email:dev] SMTP not configured — would send to=%s subject=%r",
            recipients, subject,
        )
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(text or _html_to_text(html))
    msg.add_alternative(html, subtype="html")

    try:
        await asyncio.to_thread(_send_sync, msg)
        return True
    except Exception:  # noqa: BLE001 - never let mail failure break a request/job
        logger.exception("Failed to send email to %s", recipients)
        return False


# --------------------------------------------------------------------- digests ---
_CAT_COLOR = {"critical": "#ba1c1c", "warning": "#c03f0c", "info": "#1d4fd7"}


def render_digest(org_name: str, alerts: list) -> tuple[str, str]:
    """Build (subject, html) for a batch of new notification-like objects.

    Each alert exposes ``.title``, ``.body``, ``.category`` (enum or str) and
    optionally ``.link``.
    """
    n = len(alerts)
    subject = f"[{org_name}] {n} new GRC alert{'s' if n != 1 else ''}"
    base = settings.app_base_url.rstrip("/")
    rows = []
    for a in alerts:
        cat = getattr(a, "category", "info")
        cat = getattr(cat, "value", cat)
        color = _CAT_COLOR.get(str(cat), "#1d4fd7")
        link = getattr(a, "link", "") or ""
        href = f"{base}{link}" if link.startswith("/") else link
        title = getattr(a, "title", "")
        title_html = f'<a href="{href}" style="color:#1d4fd7;text-decoration:none">{title}</a>' if href else title
        rows.append(
            f'<tr>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #eee;vertical-align:top">'
            f'<span style="display:inline-block;padding:1px 8px;border-radius:10px;'
            f'background:{color};color:#fff;font-size:11px;text-transform:uppercase">{cat}</span></td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #eee">'
            f'<div style="font-weight:600;font-size:14px">{title_html}</div>'
            f'<div style="color:#555;font-size:13px">{getattr(a, "body", "")}</div></td>'
            f'</tr>'
        )
    html = (
        f'<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;margin:0 auto">'
        f'<h2 style="font-size:18px">GRC alerts for {org_name}</h2>'
        f'<p style="color:#555;font-size:14px">{n} item{"s" if n != 1 else ""} need attention.</p>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px">{"".join(rows)}</table>'
        f'<p style="margin-top:18px"><a href="{base}/notifications" '
        f'style="background:#1d4fd7;color:#fff;padding:8px 14px;border-radius:6px;'
        f'text-decoration:none;font-size:14px">Open NexusLine</a></p>'
        f'</div>'
    )
    return subject, html
