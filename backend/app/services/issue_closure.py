"""Issues that can be traced and whose closure is proven (product review 2.3, F-12).

Four rules, kept here so the API, the start-up repair and the tests read one answer:

* **Typed links.** An issue names the risks, controls, requirements, assets and third
  parties it concerns through link tables (``issue_risks`` …), not through the bare
  ``source_id`` it used to carry. ``source_type`` / ``source_reference`` / ``source_id``
  stay as provenance — *where the issue came from* — and when ``source_id`` names one
  of those five kinds of record the matching link row is written too, so an issue
  raised from a risk is listed on that risk by the link, not by a guess.
  :func:`backfill_source_links` does the same for issues raised before the links
  existed (called from ``db.data_repairs.repair_tenant``; idempotent).
* **Closure is two people's work.** The generic edit may no longer move an issue into a
  closed state. An independent validator records whether the fix works
  (``POST /issues/{id}/validate``) — not the owner, not whoever raised it, and with
  closure evidence attached — and only then may it be closed
  (``POST /issues/{id}/close``), with no action still open. Closing as *risk accepted*
  needs no validation; it needs an approved acceptance on a linked risk, or a note from
  someone who may approve issues.
* **The closed date is the day it closed.** Set by the server on the transition into a
  closed state and cleared on reopen; no request may write it.
* **Deadline slippage is on the record.** Every move of a due date is logged with who
  asked and why. Pushing the date *later* on a regulator-related, high or critical
  issue waits for someone else's approval; until then the date does not move.

The pure rules come first (no database); the database helpers after them.
"""
from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

from sqlalchemy import Table, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import Severity
from app.models.issue import (
    ActionStatus,
    IssueStatus2,
    issue_assets,
    issue_controls,
    issue_requirements,
    issue_risks,
    issue_vendors,
)

# =================================================================== pure rules ===
#: Statuses meaning "done" — the issue no longer needs remediation.
CLOSED_STATES: frozenset[IssueStatus2] = frozenset(
    {IssueStatus2.closed, IssueStatus2.remediated, IssueStatus2.risk_accepted}
)
#: Statuses an issue may be moved to (or raised in) through the ordinary edit.
OPEN_STATES: frozenset[IssueStatus2] = frozenset(set(IssueStatus2) - CLOSED_STATES)

EFFECTIVE = "effective"
NOT_EFFECTIVE = "not_effective"
VALIDATION_RESULTS = (EFFECTIVE, NOT_EFFECTIVE)

#: Severities whose deadline cannot be pushed out without a second person.
EXTENSION_APPROVAL_SEVERITIES: frozenset[Severity] = frozenset({Severity.high, Severity.critical})

PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"

CLOSE_WITH_ACTIONS = (
    "Status '{status}' closes the issue, and an issue is closed with Validate and Close — "
    "not by editing it. Record an independent validation first (Validate), then Close."
)


def _status(value: Any) -> IssueStatus2 | None:
    if value is None or isinstance(value, IssueStatus2):
        return value
    return IssueStatus2(value)


def is_closed(status: Any) -> bool:
    return _status(status) in CLOSED_STATES


def edit_status_refusal(current: Any, requested: Any) -> str | None:
    """Why the generic edit may not set ``requested``, or None.

    Resending the stored status is fine (a form saves every field); moving between open
    states is fine; reopening a closed issue is fine. Moving *into* a closed state is
    what Validate and Close are for."""
    cur, new = _status(current), _status(requested)
    if new is None or new == cur or new not in CLOSED_STATES:
        return None
    return CLOSE_WITH_ACTIONS.format(status=new.value.replace("_", " "))


def create_status_refusal(requested: Any) -> str | None:
    """A new issue is raised open; there is nothing yet to validate or close."""
    new = _status(requested)
    if new in CLOSED_STATES:
        return (
            f"An issue cannot be raised as '{new.value.replace('_', ' ')}'. Raise it open, "
            "then close it with Validate and Close once the fix is evidenced."
        )
    return None


def is_reopen(current: Any, requested: Any) -> bool:
    cur, new = _status(current), _status(requested)
    return new is not None and cur in CLOSED_STATES and new not in CLOSED_STATES


def closed_date_after(current: Any, new: Any, closed_on: date | None, today: date) -> date | None:
    """The closed date after a status move: today on the way in, cleared on the way out,
    unchanged otherwise."""
    was, now = is_closed(current), is_closed(new)
    if now and not was:
        return today
    if was and not now:
        return None
    return closed_on


def open_action_titles(actions: Iterable[Any]) -> list[str]:
    return [
        a.title for a in actions
        if a.status in (ActionStatus.open, ActionStatus.in_progress)
    ]


def validation_refusal(*, status: Any, result: str, attachments: int, note: str) -> str | None:
    """Why this validation cannot be recorded (a 409), or None.

    Evidence is required to call a fix *effective* — the validator is certifying the
    remediation, and the certificate needs something behind it. A *not effective*
    result sends the issue back and needs only the validator's note. (Closing as risk
    accepted needs no validation at all, so it needs no evidence either.)"""
    st = _status(status)
    if st in CLOSED_STATES:
        return "This issue is already closed. Reopen it (edit its status) before validating again."
    if result not in VALIDATION_RESULTS:
        return f"Result must be one of: {', '.join(VALIDATION_RESULTS)}."
    if not (note or "").strip():
        return "Write a validation note: what you checked and what you found."
    if result == EFFECTIVE and attachments < 1:
        return (
            "Attach closure evidence to the issue first (Attachments or Files on the issue), "
            "then record it as effective."
        )
    return None


def validator_conflict(
    validator_id: uuid.UUID | None, owner_id: uuid.UUID | None, raised_by_id: uuid.UUID | None
) -> str | None:
    """Segregation of duties for validation: not the owner, not whoever raised it."""
    if validator_id is None:
        return None
    if owner_id is not None and validator_id == owner_id:
        return (
            "Segregation of duties: you own this issue's remediation, so you cannot validate "
            "it — an independent validator must."
        )
    if raised_by_id is not None and validator_id == raised_by_id:
        return (
            "Segregation of duties: you raised this issue, so you cannot validate its fix — "
            "an independent validator must."
        )
    return None


def close_refusal(
    *,
    target: Any,
    current: Any,
    open_actions: Sequence[str],
    validation_result: str | None,
    has_approved_acceptance: bool,
    note: str,
    can_approve: bool,
) -> str | None:
    """Why the issue cannot be closed as ``target`` (a 409), or None. Pure."""
    tgt, cur = _status(target), _status(current)
    if tgt not in CLOSED_STATES:
        closed = ", ".join(sorted(s.value for s in CLOSED_STATES))
        return f"Close needs a closed status ({closed}); to reopen, edit the status."
    if cur in CLOSED_STATES:
        return f"This issue is already {cur.value.replace('_', ' ')}."
    if open_actions:
        shown = "; ".join(open_actions[:5]) + ("…" if len(open_actions) > 5 else "")
        return (
            f"{len(open_actions)} action(s) are still open ({shown}). Mark them done or "
            "cancelled before closing the issue."
        )
    if tgt == IssueStatus2.risk_accepted:
        if has_approved_acceptance:
            return None
        if not (note or "").strip():
            return (
                "Closing as risk accepted needs an approved risk acceptance on a linked risk, "
                "or a note explaining the acceptance from someone who may approve issues."
            )
        if not can_approve:
            return (
                "No linked risk has an approved acceptance, so closing as risk accepted needs "
                "someone who may approve issues (workflow approval permission)."
            )
        return None
    if validation_result != EFFECTIVE:
        if validation_result == NOT_EFFECTIVE:
            return "The last validation found the fix not effective. Remediate, then have it validated again."
        return (
            "No effective validation yet. An independent validator must record the fix as "
            "effective (Validate) before the issue can be closed."
        )
    return None


def is_due_date_move(old: date | None, new: date | None) -> bool:
    """A change of an existing due date. Setting the first date is planning, not a move."""
    return old is not None and old != new


def is_extension(old: date | None, new: date | None) -> bool:
    """The deadline gets later — or goes away, which is the longest extension of all."""
    if old is None:
        return False
    return new is None or new > old


def needs_extension_approval(
    old: date | None, new: date | None, *, regulator_related: bool, severity: Any
) -> bool:
    sev = severity if isinstance(severity, Severity) or severity is None else Severity(severity)
    return is_extension(old, new) and (bool(regulator_related) or sev in EXTENSION_APPROVAL_SEVERITIES)


def due_date_moves(changes: Iterable[Any]) -> int:
    """How many times the date actually moved: approved changes of an existing date."""
    return sum(1 for c in changes if c.status == APPROVED and c.old_due_date is not None)


def acceptance_in_force(acceptance: Any, today: date) -> bool:
    """An approved acceptance that has not lapsed (expiry is inclusive of the day)."""
    from app.models.enums import AcceptanceStatus

    return acceptance.status == AcceptanceStatus.approved and (
        acceptance.expires_at is None or acceptance.expires_at >= today
    )


# ================================================================= typed links ===
@dataclass(frozen=True)
class LinkKind:
    """One link table: request field, read field, join table and target model."""

    kind: str  # risk | control | requirement | asset | vendor
    ids_field: str  # risk_ids …
    read_field: str  # risks …
    table: Table
    column: str  # risk_id …
    model_path: str  # "app.models.risk:Risk"
    noun: str

    @property
    def model(self):
        import importlib

        module, name = self.model_path.split(":")
        return getattr(importlib.import_module(module), name)


LINK_KINDS: tuple[LinkKind, ...] = (
    LinkKind("risk", "risk_ids", "risks", issue_risks, "risk_id", "app.models.risk:Risk", "risk"),
    LinkKind("control", "control_ids", "controls", issue_controls, "control_id", "app.models.control:Control", "control"),
    LinkKind(
        "requirement", "requirement_ids", "requirements", issue_requirements, "requirement_id",
        "app.models.compliance:Requirement", "requirement",
    ),
    LinkKind("asset", "asset_ids", "assets", issue_assets, "asset_id", "app.models.asset:Asset", "asset"),
    LinkKind("vendor", "vendor_ids", "vendors", issue_vendors, "vendor_id", "app.models.vendor:Vendor", "third party"),
)
LINK_BY_KIND: dict[str, LinkKind] = {k.kind: k for k in LINK_KINDS}
LINK_ID_FIELDS: tuple[str, ...] = tuple(k.ids_field for k in LINK_KINDS)


def with_source_link(links: dict[str, list[uuid.UUID] | None], kind: str | None, source_id: uuid.UUID | None):
    """``links`` with the source record added to its kind's list. Pure.

    A kind the request did not send (None — "leave as is") becomes a one-item addition,
    signalled by the second return value, so an update never wipes existing links just
    because the source moved."""
    if kind is None or source_id is None:
        return links, {}
    field = LINK_BY_KIND[kind].ids_field
    current = links.get(field)
    if current is None:
        return links, {field: [source_id]}
    if source_id in current:
        return links, {}
    return {**links, field: [*current, source_id]}, {}


def _live(model, stmt):
    return stmt.where(model.deleted.is_(False)) if hasattr(model, "deleted") else stmt


async def check_link_ids(db: AsyncSession, link: LinkKind, ids: Sequence[uuid.UUID]) -> list[uuid.UUID]:
    """The ids, de-duplicated in order, each a live record of this organisation (RLS
    scopes the query) — else a 422 naming the field."""
    from fastapi import HTTPException

    wanted = list(dict.fromkeys(ids))
    if not wanted:
        return []
    model = link.model
    found = set((await db.scalars(_live(model, select(model.id).where(model.id.in_(wanted))))).all())
    missing = [str(i) for i in wanted if i not in found]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"{link.ids_field}: no live {link.noun} with id {', '.join(missing)} in this organisation.",
        )
    return wanted


async def write_links(
    db: AsyncSession, issue_id: uuid.UUID, link: LinkKind, ids: Sequence[uuid.UUID], *, replace: bool = True
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Make the issue's live links of this kind exactly ``ids`` (or add them, with
    ``replace=False``). Links to archived records are left alone — invisible now, back
    if the record is restored. Returns ``(added, removed)``."""
    table, col = link.table, link.table.c[link.column]
    model = link.model
    current = set((await db.scalars(select(col).where(table.c.issue_id == issue_id))).all())
    live_current = set(
        (await db.scalars(_live(model, select(model.id).where(model.id.in_(current))))).all()
    ) if current else set()
    desired = set(ids)
    removed = (live_current - desired) if replace else set()
    added = desired - current
    if removed:
        await db.execute(delete(table).where(table.c.issue_id == issue_id, col.in_(removed)))
    if added:
        await db.execute(insert(table), [{"issue_id": issue_id, link.column: t} for t in added])
    return added, removed


async def source_kind(db: AsyncSession, source_id: uuid.UUID | None) -> str | None:
    """Which of the five linkable registers holds ``source_id`` (live), if any."""
    if source_id is None:
        return None
    for link in LINK_KINDS:
        model = link.model
        if await db.scalar(_live(model, select(model.id).where(model.id == source_id))) is not None:
            return link.kind
    return None


async def link_refs(db: AsyncSession, issue_ids: Sequence[uuid.UUID]) -> dict[str, dict[uuid.UUID, list[dict]]]:
    """``{read_field: {issue_id: [ref dict]}}`` for a page of issues — one lean query per
    kind, reading only id / reference / title / name (never the target's own graph)."""
    out: dict[str, dict[uuid.UUID, list[dict]]] = {k.read_field: {} for k in LINK_KINDS}
    ids = list(issue_ids)
    if not ids:
        return out
    for link in LINK_KINDS:
        model = link.model
        table = link.table
        cols = [c for c in ("reference", "title", "name", "asset_class") if hasattr(model, c)]
        stmt = (
            select(table.c.issue_id, model.id, *[getattr(model, c) for c in cols])
            .join(model, model.id == table.c[link.column])
            .where(table.c.issue_id.in_(ids))
        )
        stmt = _live(model, stmt)
        for row in (await db.execute(stmt)).all():
            issue_id, target_id, *values = row
            ref: dict[str, Any] = {"id": target_id}
            for name, value in zip(cols, values):
                ref[name] = getattr(value, "value", value) or ""
            out[link.read_field].setdefault(issue_id, []).append(ref)
    for per_issue in out.values():
        for refs in per_issue.values():
            refs.sort(key=lambda r: (r.get("reference") or r.get("title") or r.get("name") or "").lower())
    return out


async def linked_ids(db: AsyncSession, issue_id: uuid.UUID, kind: str) -> list[uuid.UUID]:
    """Ids of the live records of this kind linked to the issue."""
    link = LINK_BY_KIND[kind]
    model = link.model
    stmt = (
        select(model.id)
        .join(link.table, link.table.c[link.column] == model.id)
        .where(link.table.c.issue_id == issue_id)
    )
    return list((await db.scalars(_live(model, stmt))).all())


async def attachment_count(db: AsyncSession, issue_id: uuid.UUID) -> int:
    """Closure evidence on the issue: link attachments plus uploaded files (collab)."""
    from app.models.collab import Attachment, StoredFile

    total = 0
    for model in (Attachment, StoredFile):
        total += await db.scalar(
            select(func.count()).select_from(model).where(
                model.entity_type == "issue", model.entity_id == issue_id
            )
        ) or 0
    return total


async def has_approved_acceptance(db: AsyncSession, risk_ids: Sequence[uuid.UUID], today: date | None = None) -> bool:
    """Whether any of these risks carries an approved, unlapsed risk acceptance."""
    from app.models.risk import RiskAcceptance

    if not risk_ids:
        return False
    today = today or date.today()
    rows = (await db.scalars(select(RiskAcceptance).where(RiskAcceptance.risk_id.in_(list(risk_ids))))).all()
    return any(acceptance_in_force(a, today) for a in rows)


async def recompute_controls(db: AsyncSession, control_ids: Iterable[uuid.UUID], *, reason: str = "") -> int:
    """Let each control re-derive its effectiveness now that an issue on it opened,
    closed or moved (an open issue holds a control at partially effective).

    ``control_assurance.recompute_effectiveness(db, control)`` is imported lazily and
    skipped silently when this build does not have it yet."""
    ids = list(dict.fromkeys(i for i in control_ids if i is not None))
    if not ids:
        return 0
    try:
        from app.services import control_assurance
    except Exception:  # noqa: BLE001 - optional dependency
        return 0
    recompute = getattr(control_assurance, "recompute_effectiveness", None)
    if recompute is None:
        return 0
    from app.models.control import Control

    try:
        takes_reason = "reason" in inspect.signature(recompute).parameters
    except (TypeError, ValueError):
        takes_reason = False
    done = 0
    for control in (await db.scalars(select(Control).where(Control.id.in_(ids), Control.deleted.is_(False)))).all():
        result = recompute(db, control, reason=reason) if takes_reason and reason else recompute(db, control)
        if inspect.isawaitable(result):
            await result
        done += 1
    return done


async def backfill_source_links(db: AsyncSession) -> int:
    """Write the typed link for every live issue whose ``source_id`` names a live risk,
    control, requirement, asset or third party. Idempotent (``ON CONFLICT DO NOTHING``);
    returns how many link rows were added. Runs inside the caller's tenant-scoped
    session, so each tenant's issues only meet that tenant's records."""
    from app.models.issue import Issue

    added = 0
    for link in LINK_KINDS:
        model = link.model
        source = _live(
            model,
            select(Issue.id, model.id)
            .join(model, model.id == Issue.source_id)
            .where(Issue.deleted.is_(False), Issue.source_id.is_not(None)),
        )
        stmt = (
            pg_insert(link.table)
            .from_select(["issue_id", link.column], source)
            .on_conflict_do_nothing()
        )
        result = await db.execute(stmt)
        added += max(result.rowcount or 0, 0)
    return added
