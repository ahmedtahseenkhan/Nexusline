"""Bulk edit: set one value on many records of a register at once (product review 3.2).

``PATCH /records/{entity_type}/bulk`` with ``{ids, patch}``, ``patch`` holding any of
``owner_id``, ``next_review_date``, ``review_frequency``, ``category_id`` and ``status``.

* **An explicit allow-list per register** (:data:`REGISTERS`). Each generic key maps to
  the register's own column — a control's "next review" is its next *test* date, an
  incident's owner is its *assignee*, an asset's owner is its owning *business unit* —
  and a register lists only what a person may set on the record's own form.
  ``workflow_status`` is never listed: approval state moves only through the lifecycle
  (``services.record_workflow``). Policies have no bulk status for the same reason.
* **Values are checked once** for the whole batch, the way the record's own edit checks
  them (``services.master_data``): an active user, a live business unit, an active value
  from the register's own governed list, a status or frequency the form offers.
* **Each record then goes through its register's rules** (:func:`plan`, pure):

  - control — planned and retired controls have no test clock, so a next test date is
    skipped for them; a new test frequency re-derives the next test from the last test;
    a status change starts or stops the test and maintenance clocks
    (``control_assurance.next_cycle_date``, exactly as ``PATCH /controls/{id}``);
  - issue — the status can move between *open* and *in progress* only; closing takes
    Validate and Close, and a closed issue is reopened from the issue itself;
  - incident — a status move stamps containment / resolution where blank, and an
    incident whose timeline would then be out of order is skipped
    (``incident_clock``, as ``PATCH /incidents/{id}``);
  - policy — a new review frequency re-derives the next review from today; risk — from
    the last review (as their edits do), on the *effective* cycle: a risk's rating may
    require a shorter one than the frequency set (``RiskSetting.review_cadence``), so a
    new frequency that does not change the effective cycle leaves the date alone, and a
    next review date later than the rating allows is skipped (F-22). Risks carry no bulk
    status, so nothing here can move a risk out of Draft past its owner-and-unit rule.

  Setting a review frequency and a next review date in the same request is refused:
  the new frequency would re-derive the date the same request sets.
* **Live records of this organisation only.** An id that is archived, not found (or in
  another organisation) or would not change is skipped with that reason, and a skipped
  record is never partly written.
* **One audit entry per record changed**, each carrying the run's ``batch_id`` in its
  ``changes``, so the trail answers "what else changed in that bulk edit?".
"""
from __future__ import annotations

import enum
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import select

from app.core.database import shallow_loads
from app.db.fk_backfill import FK_LOOKUP_KEYS
from app.models.enums import ControlStatus, IncidentStatus, ReviewFrequency, VendorStatus
from app.models.issue import IssueStatus2
from app.services import audit, control_assurance, entity_types, master_data, record_registry
from app.services import incident_clock as clock
from app.services.issue_closure import CLOSED_STATES as ISSUE_CLOSED_STATES
from app.services.ref_fields import fit
from app.services import risk_scoring
from app.services.risk_scoring import next_review_date

#: Every key a bulk patch may carry (each register accepts a subset).
KEYS: tuple[str, ...] = ("owner_id", "next_review_date", "review_frequency", "category_id", "status")

NOT_FOUND = "not found"
ARCHIVED = "archived"
NO_CHANGE = "no change"


class Skip(Exception):
    """This record is left exactly as it is, for the reason given."""


@dataclass(frozen=True)
class Field:
    """One value a register can set in bulk."""

    key: str  # the generic key in the patch
    column: str  # the model column it writes
    kind: str  # user | unit | lookup | date | frequency | status
    label: str  # the register's own name for it
    text_column: str | None = None  # legacy text twin kept in step (ref_fields rule)
    lookup_key: str | None = None
    choices: tuple[enum.Enum, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Register:
    entity_type: str
    noun: str  # plural, for messages
    fields: tuple[Field, ...]

    def field(self, key: str) -> Field | None:
        return next((f for f in self.fields if f.key == key), None)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields)


F = ReviewFrequency
#: What the review-cycle dropdown offers on the policy, third-party, asset and risk forms.
REVIEW_CYCLES: tuple[ReviewFrequency, ...] = (F.none, F.monthly, F.quarterly, F.semiannual, F.annual)
#: What the control form offers for its test frequency.
TEST_CYCLES: tuple[ReviewFrequency, ...] = (F.none, F.fortnightly, F.monthly, F.quarterly, F.semiannual, F.annual)
#: The statuses the ordinary issue edit may set (closing is Validate and Close).
ISSUE_EDIT_STATES: tuple[IssueStatus2, ...] = (IssueStatus2.open, IssueStatus2.in_progress)


def _user(column: str = "owner_id", text: str | None = "owner", label: str = "Owner") -> Field:
    return Field("owner_id", column, "user", label, text)


def _category(table: str, column: str = "category_id", text: str | None = "category",
              label: str = "Category") -> Field:
    # The list comes from fk_backfill.FK_LOOKUP_KEYS, like ref_fields.lookup, so the bulk
    # path, the record's edit and the boot backfill can never disagree about it.
    return Field("category_id", column, "lookup", label, text, FK_LOOKUP_KEYS[(table, column)])


def _next_review(note: str = "") -> Field:
    return Field("next_review_date", "next_review_date", "date", "Next review date", note=note)


def _frequency(note: str = "") -> Field:
    return Field("review_frequency", "review_frequency", "frequency", "Review frequency",
                 choices=REVIEW_CYCLES, note=note)


REGISTERS: dict[str, Register] = {
    "control": Register("control", "controls", (
        _user(),
        _category("controls", "classification_id", "classification", "Classification"),
        Field("next_review_date", "next_audit_date", "date", "Next test date",
              note="Planned and retired controls are skipped: they have no test clock until they are implemented."),
        Field("review_frequency", "audit_frequency", "frequency", "Test frequency", choices=TEST_CYCLES,
              note="The next test date is re-derived from each control's last test (or today)."),
        Field("status", "status", "status", "Status", choices=tuple(ControlStatus),
              note="Going live starts the test clock; planned or retired stops it."),
    )),
    "issue": Register("issue", "issues", (
        _user(),
        _category("issues"),
        Field("status", "status", "status", "Status", choices=ISSUE_EDIT_STATES,
              note="Closing takes Validate and Close on each issue; closed issues are skipped."),
    )),
    "incident": Register("incident", "incidents", (
        _user("assignee_id", "assignee", "Assignee"),
        _category("incidents", label="Incident type"),
        Field("status", "status", "status", "Status", choices=tuple(IncidentStatus),
              note="Moving to contained or resolved records the time now where it is blank."),
    )),
    "policy": Register("policy", "policies", (
        _user(),
        _category("policies"),
        _next_review(),
        _frequency("The next review date is re-derived from today."),
    )),
    "vendor": Register("vendor", "third parties", (
        _user("relationship_owner_id", None, "Relationship owner"),
        _category("vendors"),
        _next_review(),
        _frequency(),
        Field("status", "status", "status", "Status", choices=tuple(VendorStatus)),
    )),
    "asset": Register("asset", "assets", (
        Field("owner_id", "owner_id", "unit", "Owning unit"),
        _next_review(),
        _frequency(),
    )),
    "risk": Register("risk", "risks", (
        _user(text=None),  # a risk's owner never had a text column (risks.RISK_REFS)
        _category("risks"),
        _next_review(),
        _frequency(
            "The next review date is re-derived from each risk's last review (or today) when the "
            "cycle changes; a risk's rating can require a shorter cycle than the one set."
        ),
    )),
}

#: Columns a register rule moves beside the ones asked for, in words for the trail.
_DERIVED_WORDS = {
    "next_audit_date": "next test date",
    "next_maintenance_date": "next maintenance date",
    "next_review_date": "next review date",
    "contained_at": "contained at",
    "resolved_at": "resolved at",
}


# ==================================================================== pure rules ===
def register_for(entity_type: str) -> Register:
    """The register's bulk allow-list; 422 for a type with no bulk edit."""
    found = entity_types.spec(entity_type)
    register = REGISTERS.get(entity_type)
    if register is None:
        raise _unprocessable(f"{found.label} records can't be edited in bulk.")
    return register


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


def _value(x: Any) -> Any:
    return getattr(x, "value", x)


def choice_label(choice: Any) -> str:
    text = str(_value(choice)).replace("_", " ")
    return "Twice a year" if text == "semiannual" else text[:1].upper() + text[1:]


def check_keys(register: Register, patch: dict[str, Any]) -> None:
    """The shape rules, before any value is looked up. Raises 422."""
    if not patch:
        raise _unprocessable("Choose something to change.")
    extra = [k for k in patch if register.field(k) is None]
    if extra:
        raise _unprocessable(
            f"{register.noun.capitalize()} can't have {', '.join(sorted(extra))} set in bulk; "
            f"they accept {', '.join(register.keys)}."
        )
    blank = [k for k, v in patch.items() if v is None or (isinstance(v, str) and not v.strip())]
    if blank:
        raise _unprocessable(f"{blank[0]}: choose a value to set.")
    if "review_frequency" in patch and "next_review_date" in patch:
        raise _unprocessable(
            "Set the frequency or the next date, not both: a new frequency re-derives the date."
        )


def choose(f: Field, raw: Any) -> enum.Enum:
    """A status or frequency value the register offers; 422 otherwise."""
    for c in f.choices:
        if _value(c) == _value(raw):
            return c
    raise _unprocessable(
        f"{f.key}: '{raw}' is not one of {', '.join(str(_value(c)) for c in f.choices)}."
    )


@dataclass(frozen=True)
class Value:
    """A checked value: what the column gets, how it reads, and the legacy text twin."""

    value: Any
    text: str
    column_text: str | None = None


def plan(register: Register, record: Any, values: dict[str, Value], *, today: date,
         now: datetime | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """The columns this record would change, as ``{column: new value}`` — only those
    that differ. Raises :class:`Skip` when a register rule leaves the record alone, or
    when nothing would change. Pure: reads the record, never writes it. ``context``
    carries what a register rule needs beyond the record (a risk's ``scale`` and
    ``cadence``)."""
    out: dict[str, Any] = {}
    for key, v in values.items():
        f = register.field(key)
        if f is None:
            continue
        if getattr(record, f.column, None) != v.value:
            out[f.column] = v.value
            if f.text_column:
                out[f.text_column] = v.column_text or ""
    hook = _RULES.get(register.entity_type)
    if hook is not None:
        out = hook(record, values, out, today=today, now=now or datetime.now(timezone.utc), context=context or {})
    if not out:
        raise Skip(NO_CHANGE)
    return out


def _keep_changed(record: Any, out: dict[str, Any], column: str, value: Any) -> None:
    if getattr(record, column, None) != value:
        out[column] = value
    else:
        out.pop(column, None)


def _control_rules(record: Any, values: dict[str, Value], out: dict[str, Any], *, today: date,
                   now: datetime, **_: Any) -> dict[str, Any]:
    """The test clock, as ``PATCH /controls/{id}`` runs it."""
    status_after = out.get("status", record.status)
    live_after = control_assurance.carries_test_clock(status_after)
    explicit_given = "next_review_date" in values
    if explicit_given and not live_after:
        raise Skip(
            "planned — no test clock until it is implemented"
            if _value(status_after) == ControlStatus.planned.value
            else "retired — no tests are scheduled"
        )
    became = not control_assurance.carries_test_clock(record.status) and live_after
    frequency = out.get("audit_frequency", record.audit_frequency)
    next_test = control_assurance.next_cycle_date(
        status_after, frequency, current=record.next_audit_date,
        explicit=values["next_review_date"].value if explicit_given else None,
        explicit_given=explicit_given, frequency_changed="audit_frequency" in out,
        became_testable=became, last_done=getattr(record, "last_audit_date", None), today=today,
    )
    next_maintenance = control_assurance.next_cycle_date(
        status_after, record.maintenance_frequency, current=record.next_maintenance_date,
        became_testable=became, last_done=getattr(record, "last_maintenance_date", None), today=today,
    )
    _keep_changed(record, out, "next_audit_date", next_test)
    _keep_changed(record, out, "next_maintenance_date", next_maintenance)
    return out


def _issue_rules(record: Any, values: dict[str, Value], out: dict[str, Any], **_: Any) -> dict[str, Any]:
    """Closing is Validate and Close; reopening is done on the issue, where its
    validation is cleared and the reopen is logged."""
    if "status" in values and _value(record.status) in {s.value for s in ISSUE_CLOSED_STATES}:
        raise Skip(f"{choice_label(record.status).lower()} — reopen it from the issue itself")
    return out


def _incident_rules(record: Any, values: dict[str, Value], out: dict[str, Any], *, now: datetime,
                    **_: Any) -> dict[str, Any]:
    """A status move stamps the step it implies where blank, and the timeline must stay
    in order — ``PATCH /incidents/{id}``'s rule."""
    if "status" not in out:
        return out
    current = {f: getattr(record, f, None) for f in clock.TIMELINE_FIELDS}
    stamps = clock.status_stamps(out["status"], current, now)
    if stamps:
        problems = clock.timeline_problems({**current, **stamps})
        near_miss = clock.near_miss_problem(getattr(record, "near_miss", False), getattr(record, "cost", None))
        if near_miss:
            problems.append(near_miss)
        if problems:
            raise Skip("; ".join(problems).lower())
        out.update(stamps)
    return out


def _policy_rules(record: Any, values: dict[str, Value], out: dict[str, Any], *, today: date,
                  **_: Any) -> dict[str, Any]:
    if "review_frequency" in out:
        _keep_changed(record, out, "next_review_date", next_review_date(out["review_frequency"], today))
    return out


def _risk_rules(record: Any, values: dict[str, Value], out: dict[str, Any], *, today: date,
                context: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    """The review clock on the effective cycle, as ``PATCH /risks/{id}`` runs it."""
    context = context or {}
    scale = context.get("scale")
    severity = risk_scoring.current_severity(record, scale) if scale is not None else None
    cadence = context.get("cadence")
    before = risk_scoring.effective_review_frequency(getattr(record, "review_frequency", None), severity, cadence)[0]
    if "review_frequency" in out:
        after = risk_scoring.effective_review_frequency(out["review_frequency"], severity, cadence)[0]
        _keep_changed(record, out, "next_review_date", risk_scoring.rescheduled_review(
            current=getattr(record, "next_review_date", None),
            last_review=getattr(record, "last_review_date", None),
            effective_before=before, effective_after=after, frequency_changed=True, today=today,
        ))
    elif "next_review_date" in out and severity is not None:
        latest = next_review_date(before, today)
        if latest is not None and out["next_review_date"] > latest:
            raise Skip(
                f"{severity.value} — its rating needs a review by {latest.isoformat()}"
            )
    return out


def _asset_rules(record: Any, values: dict[str, Value], out: dict[str, Any], *, today: date,
                 **_: Any) -> dict[str, Any]:
    """An asset's review date moves only as ``PATCH /assets/{id}`` lets it: an overdue
    review is cleared by completing it, and never past one cycle out
    (``services.asset_review``). Setting a date across a selection turned 1,560 overdue
    reviews green in one click without a single review."""
    from app.services.asset_review import date_change_problem

    if "next_review_date" in out:
        problem = date_change_problem(
            record.next_review_date, out["next_review_date"],
            out.get("review_frequency", record.review_frequency), today,
        )
        if problem:
            raise Skip(problem)
    return out


_RULES = {
    "asset": _asset_rules,
    "control": _control_rules,
    "issue": _issue_rules,
    "incident": _incident_rules,
    "policy": _policy_rules,
    "risk": _risk_rules,
}


def words_for(register: Register, columns: Iterable[str]) -> list[str]:
    """``["owner", "next test date"]`` — what changed, as a person reads it. The legacy
    text twin of a picked field is not listed apart from its field."""
    by_column = {f.column: f.label.lower() for f in register.fields}
    twins = {f.text_column for f in register.fields if f.text_column}
    out: list[str] = []
    for c in columns:
        if c in twins:
            continue
        word = by_column.get(c) or _DERIVED_WORDS.get(c) or c.replace("_", " ")
        if word not in out:
            out.append(word)
    return out


def summarize(results: Iterable[Any]) -> str:
    """"Updated 38; 2 skipped: archived" — or, with several reasons, "Updated 3;
    3 skipped: 2 archived, 1 no change". Pure."""
    rows = list(results)
    updated = sum(1 for r in rows if r.outcome == "updated")
    skipped = [r.reason or "skipped" for r in rows if r.outcome == "skipped"]
    head = f"Updated {updated}" if updated else "Nothing updated"
    if not skipped:
        return head
    reasons = Counter(skipped)
    if len(reasons) == 1:
        return f"{head}; {len(skipped)} skipped: {skipped[0]}"
    listed = ", ".join(f"{n} {reason}" for reason, n in reasons.most_common())
    return f"{head}; {len(skipped)} skipped: {listed}"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def new_batch_id() -> str:
    return uuid.uuid4().hex


# ====================================================================== database ===
async def resolve(db, register: Register, model: type, patch: dict[str, Any]) -> dict[str, Value]:
    """Check every value once for the whole batch; 422 naming the field otherwise."""
    from app.models.identity import User
    from app.models.lookup import Lookup
    from app.models.organization import BusinessUnit

    check_keys(register, patch)
    out: dict[str, Value] = {}
    for key, raw in patch.items():
        f = register.field(key)
        assert f is not None  # check_keys refused anything else
        if f.kind == "user":
            await master_data.check_user(db, raw, key)
            person = await db.get(User, raw)
            label = person.full_name or person.email
        elif f.kind == "unit":
            await master_data.check_unit(db, raw, key)
            label = (await db.get(BusinessUnit, raw)).name
        elif f.kind == "lookup":
            await master_data.check_lookup(db, raw, f.lookup_key or "", key)
            label = (await db.get(Lookup, raw)).label
        elif f.kind in ("status", "frequency"):
            chosen = choose(f, raw)
            out[key] = Value(chosen, choice_label(chosen))
            continue
        else:  # date
            out[key] = Value(raw, raw.isoformat() if hasattr(raw, "isoformat") else str(raw))
            continue
        out[key] = Value(raw, label, fit(model, f.text_column, label) if f.text_column else None)
    return out


async def run(db, user: Any, entity_type: str, ids: list[uuid.UUID], patch: dict[str, Any]):
    """Apply ``patch`` to each id in turn; returns a ``schemas.bulk.BulkResult``."""
    from app.schemas.bulk import BulkResult, BulkResultItem

    entity_types.require_write(user, entity_type)
    register = register_for(entity_type)
    model = record_registry.model_for(entity_type)
    values = await resolve(db, register, model, patch)
    batch = new_batch_id()
    today = date.today()
    now = datetime.now(timezone.utc)
    context: dict[str, Any] = {}
    if entity_type == "risk":
        from app.services.risk_settings import get_or_create_settings, scale_for

        settings = await get_or_create_settings(db, user.tenant_id)
        context = {"scale": scale_for(settings), "cadence": dict(settings.review_cadence or {})}

    wanted = list(dict.fromkeys(ids))
    # The records' own columns and links, not their links' links (``shallow_loads``).
    with shallow_loads(1):
        rows = {r.id: r for r in (await db.scalars(select(model).where(model.id.in_(wanted)))).all()}
    # An approved asset whose owner changes goes back for review (see
    # ``api.v1.assets.MATERIAL_FIELDS``), submitted by this user — who must be allowed to
    # submit. Checked once, before anything changes.
    resubmit_refusal: str | None = None
    if entity_type == "asset":
        from app.services import dual_control

        try:
            await dual_control.enforce_maker_role(db, module="asset", action="approve", maker_id=user.id)
        except HTTPException as refused:
            resubmit_refusal = str(refused.detail)
    results: list[BulkResultItem] = []
    asked = "; ".join(f"{register.field(k).label.lower()} → {v.text}" for k, v in values.items())
    for rid in wanted:
        record = rows.get(rid)
        if record is None or getattr(record, "tenant_id", user.tenant_id) != user.tenant_id:
            results.append(BulkResultItem(id=rid, outcome="skipped", reason=NOT_FOUND))
            continue
        ref, label = record_registry.reference_of(record), record_registry.label_of(record)
        if getattr(record, "deleted", False):
            results.append(BulkResultItem(id=rid, reference=ref, label=label, outcome="skipped", reason=ARCHIVED))
            continue
        try:
            changes = plan(register, record, values, today=today, now=now, context=context)
        except Skip as why:
            results.append(BulkResultItem(id=rid, reference=ref, label=label, outcome="skipped", reason=str(why)))
            continue
        material = entity_type == "asset" and _is_approved(record) and bool(set(changes) & _asset_material())
        if material and resubmit_refusal:
            results.append(BulkResultItem(
                id=rid, reference=ref, label=label, outcome="skipped",
                reason=f"approved — the change would send it for review, and {resubmit_refusal}",
            ))
            continue
        before = {c: getattr(record, c, None) for c in changes}
        for column, value in changes.items():
            setattr(record, column, value)
        if entity_type == "asset" and "next_review_date" in changes:
            from app.services.asset_review import sync_schedule

            await sync_schedule(db, record)
        changed = words_for(register, changes)
        await audit.record(
            db, actor=user, action="update", entity_type=entity_type, entity_id=record.id,
            summary=f"Bulk edit of {label}: {asked}"[:500],
            changes={
                "batch_id": batch,
                "bulk": True,
                "fields": {c: {"from": _text(before[c]), "to": _text(v)} for c, v in changes.items()},
            },
        )
        if material:
            from app.services import record_workflow

            await db.flush()
            await record_workflow.apply(db, user, record, entity_type, "revise",
                                        "Changed owner on the approved asset (bulk edit)")
            await record_workflow.apply(db, user, record, entity_type, "submit")
        results.append(BulkResultItem(id=rid, reference=ref, label=label, outcome="updated", changed=changed))
    await db.flush()
    updated = sum(1 for r in results if r.outcome == "updated")
    return BulkResult(
        entity_type=entity_type, batch_id=batch, updated=updated, skipped=len(results) - updated,
        summary=summarize(results), results=results,
    )


def _is_approved(record: Any) -> bool:
    return str(getattr(getattr(record, "workflow_status", None), "value", getattr(record, "workflow_status", ""))) == "approved"


def _asset_material() -> frozenset[str]:
    from app.api.v1.assets import MATERIAL_FIELDS

    return MATERIAL_FIELDS


def fields_for(user: Any, entity_type: str):
    """What the register can set in bulk, for the bar's menu (``schemas.bulk.BulkFieldsRead``)."""
    from app.schemas.bulk import BulkFieldRead, BulkFieldsRead, BulkOption

    found = entity_types.require_read(user, entity_type)
    register = register_for(entity_type)
    return BulkFieldsRead(
        entity_type=entity_type,
        noun=register.noun,
        can_edit=found.write_perm in set(getattr(user, "permission_codes", []) or []),
        fields=[
            BulkFieldRead(
                key=f.key, label=f.label, kind=f.kind, lookup_key=f.lookup_key,
                options=[BulkOption(value=_value(c), label=choice_label(c)) for c in f.choices],
                note=f.note,
            )
            for f in register.fields
        ],
    )
