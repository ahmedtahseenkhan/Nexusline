"""Outbound email via SMTP, with a dev-safe fallback.

When ``settings.smtp_host`` is empty (the default) nothing is sent — the message is
logged instead, so local/dev runs never fail for lack of a mail server. Configure
SMTP_* env vars to enable real delivery. Sending uses the stdlib ``smtplib`` on a
worker thread (``asyncio.to_thread``) so the event loop is never blocked, avoiding a
hard third-party dependency.

Rendering (phase 3): every alert in a digest links to its record
(``settings.app_base_url`` + the alert's ``/risks?id=…`` link); an approval that the
reader may decide carries **Approve** / **Reject** buttons that open the confirmation
page (``/act?token=…``) — a link never decides anything by itself, because mail
scanners follow links. Everything interpolated into HTML is escaped, and each message
has a plain-text part that keeps the URLs.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import smtplib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from app.core.config import settings

logger = logging.getLogger("nexusline.email")

_TAGS = re.compile(r"<[^>]+>")


def is_configured() -> bool:
    return bool(settings.smtp_host)


def _html_to_text(html: str) -> str:
    text = re.sub(r"<(br|/p|/div|/li|/tr)[^>]*>", "\n", html, flags=re.I)
    return html_lib.unescape(_TAGS.sub("", text)).strip()


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


# --------------------------------------------------------------------- helpers ---
_CAT_COLOR = {"critical": "#ba1c1c", "warning": "#c03f0c", "info": "#1d4fd7"}


def _esc(value: Any) -> str:
    return html_lib.escape(str(value if value is not None else ""), quote=True)


def base_url() -> str:
    return settings.app_base_url.rstrip("/")


def absolute_url(link: str | None) -> str:
    """An app path (``/risks?id=…``) as a full URL; other values unchanged."""
    link = link or ""
    return f"{base_url()}{link}" if link.startswith("/") else link


def _button(href: str, label: str, color: str) -> str:
    return (
        f'<a href="{_esc(href)}" style="display:inline-block;background:{color};color:#fff;'
        f'padding:6px 12px;border-radius:6px;text-decoration:none;font-size:13px;'
        f'margin-right:6px">{_esc(label)}</a>'
    )


@dataclass(frozen=True)
class DecisionLinks:
    """The confirmation-page URLs an approver can use from the e-mail."""

    approve: str
    reject: str


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


# --------------------------------------------------------------------- digests ---
def render_user_digest(
    org_name: str,
    alerts: Sequence[Any],
    *,
    recipient_name: str = "",
    decisions: Mapping[Any, DecisionLinks] | None = None,
    escalations: int = 0,
) -> tuple[str, str, str]:
    """Build (subject, html, text) for one person's digest.

    Each alert exposes ``.title``, ``.body``, ``.category`` (enum or str), ``.link`` and
    ``.entity_id``. ``decisions`` maps an approval's id (the alert's ``entity_id``) to
    the Approve / Reject confirmation links minted for this reader. ``escalations`` is
    how many of the alerts reached the reader as a turnaround-time escalation, named in
    the subject so the line above the owner sees it for what it is.
    """
    decisions = decisions or {}
    n = len(alerts)
    subject = f"[{org_name}] {_plural(n, 'new GRC alert')}"
    if escalations:
        subject += f", including {_plural(escalations, 'turnaround-time escalation')}"
    base = base_url()
    rows: list[str] = []
    lines: list[str] = []
    for a in alerts:
        cat = getattr(a, "category", "info")
        cat = str(getattr(cat, "value", cat))
        color = _CAT_COLOR.get(cat, "#1d4fd7")
        href = absolute_url(getattr(a, "link", ""))
        title = getattr(a, "title", "")
        body = getattr(a, "body", "")
        title_html = (
            f'<a href="{_esc(href)}" style="color:#1d4fd7;text-decoration:none">{_esc(title)}</a>'
            if href else _esc(title)
        )
        links = decisions.get(getattr(a, "entity_id", None))
        buttons = ""
        if links is not None:
            buttons = (
                '<div style="margin-top:6px">'
                + _button(links.approve, "Approve", "#15803d")
                + _button(links.reject, "Reject", "#b91c1c")
                + "</div>"
            )
        rows.append(
            f'<tr>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #eee;vertical-align:top">'
            f'<span style="display:inline-block;padding:1px 8px;border-radius:10px;'
            f'background:{color};color:#fff;font-size:11px;text-transform:uppercase">{_esc(cat)}</span></td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #eee">'
            f'<div style="font-weight:600;font-size:14px">{title_html}</div>'
            f'<div style="color:#555;font-size:13px">{_esc(body)}</div>{buttons}</td>'
            f'</tr>'
        )
        lines.append(f"[{cat.upper()}] {title}\n  {body}" + (f"\n  Open: {href}" if href else ""))
        if links is not None:
            lines.append(f"  Approve: {links.approve}\n  Reject: {links.reject}")
    greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"
    intro = f"{_plural(n, 'item')} for you {'need' if n != 1 else 'needs'} attention."
    html = (
        f'<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;margin:0 auto">'
        f'<h2 style="font-size:18px">GRC alerts for {_esc(org_name)}</h2>'
        f'<p style="color:#555;font-size:14px">{_esc(greeting)} {_esc(intro)}</p>'
        f'<table style="width:100%;border-collapse:collapse;font-size:14px">{"".join(rows)}</table>'
        f'<p style="margin-top:18px">'
        + _button(f"{base}/my-work", "Open My Work", "#1d4fd7")
        + f'<a href="{_esc(base)}/notifications" style="font-size:13px;color:#1d4fd7">All alerts</a></p>'
        f'<p style="color:#888;font-size:12px">Approve and Reject open a page where you confirm the '
        f'decision; the links work once and expire after 72 hours.</p>'
        f'</div>'
    )
    text = (
        f"{greeting}\n{intro}\n\n" + "\n\n".join(lines)
        + f"\n\nMy Work: {base}/my-work\nAll alerts: {base}/notifications\n"
    )
    return subject, html, text


def render_digest(org_name: str, alerts: list) -> tuple[str, str]:
    """Build (subject, html) for a batch of notification-like objects (no reader, no
    decision links). Kept for callers that predate per-person digests."""
    subject, html, _text = render_user_digest(org_name, alerts)
    return subject, html


# ------------------------------------------------------------ decision request ---
def render_decision_request(
    org_name: str,
    approval: Any,
    *,
    recipient_name: str = "",
    approve_url: str,
    reject_url: str,
    open_url: str = "",
) -> tuple[str, str, str]:
    """Build (subject, html, text) for "a request is waiting for your decision"."""
    reference = getattr(approval, "reference", "") or ""
    title = getattr(approval, "title", "") or ""
    subject = f"[{org_name}] Decision needed: {reference} {title}".strip()
    rows = [
        ("Request", f"{reference} {title}".strip()),
        ("About", getattr(approval, "entity_label", "") or ""),
        ("Details", getattr(approval, "description", "") or ""),
        ("Raised by", getattr(approval, "requested_by_email", "") or ""),
        ("Due", str(getattr(approval, "due_date", "") or "")),
    ]
    required = getattr(approval, "required_approvals", 1) or 1
    if required > 1:
        rows.append(("Approvals needed", f"{getattr(approval, 'approvals_received', 0)} of {required} so far"))
    table = "".join(
        f'<tr><td style="padding:4px 10px 4px 0;color:#666;vertical-align:top;white-space:nowrap">{_esc(k)}</td>'
        f'<td style="padding:4px 0">{_esc(v)}</td></tr>'
        for k, v in rows if v
    )
    greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"
    html = (
        f'<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;margin:0 auto">'
        f'<h2 style="font-size:18px">A request is waiting for your decision</h2>'
        f'<p style="color:#555;font-size:14px">{_esc(greeting)} {_esc(org_name)} needs your decision on:</p>'
        f'<table style="border-collapse:collapse;font-size:14px;margin-bottom:14px">{table}</table>'
        f'<p>' + _button(approve_url, "Approve", "#15803d") + _button(reject_url, "Reject", "#b91c1c")
        + (f' <a href="{_esc(open_url)}" style="font-size:13px;color:#1d4fd7">Open in NexusLine</a>' if open_url else "")
        + '</p>'
        '<p style="color:#888;font-size:12px">Each button opens a page where you confirm the decision '
        '(a rejection needs a reason). The links are for you only, work once and expire after 72 hours.</p>'
        '</div>'
    )
    text = (
        f"{greeting}\n{org_name} needs your decision on:\n\n"
        + "\n".join(f"{k}: {v}" for k, v in rows if v)
        + f"\n\nApprove: {approve_url}\nReject: {reject_url}\n"
        + (f"Open in NexusLine: {open_url}\n" if open_url else "")
        + "\nEach link opens a page where you confirm the decision. The links work once and expire after 72 hours.\n"
    )
    return subject, html, text
