"""Startup repairs for data written before the product-review phase-0 rules existed.

Every step is idempotent and safe to run on every boot: each one only touches rows that
still break a rule, so a clean database costs a handful of cheap queries.

Tenant-scoped work runs inside a tenant session (row-level security is forced even for
the table owner, so a bare ``UPDATE`` from a migration would silently match nothing).
The two unique indexes are created afterwards on the admin connection, once the
duplicates they forbid have been merged away; if a duplicate survives, the index is
skipped and logged rather than failing the start-up.

The record-page repairs (spec §3.6 B10) change regulated records, so each one writes an
audit row per record it touches, attributed to the platform (``system``), never to a
person (:func:`system_audit`). They run in a savepoint each: one that fails is logged and
retried on the next start instead of stopping the start-up.

* **B10a** A controls-pack install wrote the framework's name as each control's
  classification. A control's classification that names an installed framework is
  cleared; one that is really a nature (Preventive, Detective, Corrective, Directive) is
  copied into an empty ``nature``; and those values are deactivated in the
  ``control_classification`` list — once each, so an administrator who brings one back
  is not overruled on the next start.
* **Decision 8 (2026-09-17)** A control with no classification at all is classified by
  its ISO/IEC 27002:2022 theme (Organizational / People / Physical / Technological) when
  the control itself says which one: its ISO 27002 attributes, its own Annex A reference,
  or the single theme of the clauses it implements. Once per control — clearing it again
  is a decision the next start respects.
* **B10b** A record that is approved or retired with no approval step on file (seeded,
  imported, or set before approvals were tracked) gets one ``workflow_import`` row:
  "Imported as approved: no approver recorded". It never names a person.
* **B10c (decision 6)** A record written before the approval lifecycle existed sits at
  ``workflow_status = draft`` however live it is, and decision 6 would leave it
  permanently un-attestable. Where its own business status says it is in force (a
  published policy, an operational control, an assessed risk, an active third party, a
  closed incident or issue — :data:`LIVE_BUSINESS_STATUSES`) and it has no approval
  history at all, the approval is recorded as ``approved`` with one ``system`` row
  saying it was recorded on upgrade. Never a record in review, one a reviewer sent back,
  or one at a draft-equivalent status.
* **Maker roles (2026-09-25)** Organisations seeded before maker roles were enforced
  have ``Risk Manager`` as the maker role of the risk-acceptance, risk-approval and
  exception-approval rules. Where such a rule is still exactly as seeded and nobody has
  created or edited it by hand, the maker role is cleared with one ``system`` row per
  organisation ("maker role cleared — was never enforced; set it again to enforce")
  (``services.default_governance.clear_legacy_maker_roles``).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import func, or_, select, text, update

from app.core.database import set_session_tenant, tenant_session
from app.models.control import UNTESTABLE_CONTROL_STATUSES, Control
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.models.widget import DashboardWidget

logger = logging.getLogger(__name__)

RESIDUAL_REVIEW_REASON = (
    "Residual score is higher than inherent with no reason recorded. Controls can only "
    "reduce a risk: correct the residual, or record why it is higher."
)

#: The ``control_classification`` list mixed a control's *nature* (COSO / ISO 27002:
#: what it does about an event) into its classification. Normalised label → the
#: ``controls.nature`` value (``schemas.control.Nature``).
NATURE_CLASSIFICATIONS: dict[str, str] = {
    "preventive": "preventive",
    "detective": "detective",
    "corrective": "corrective",
    "directive": "directive",
}
CLASSIFICATION_LIST = "control_classification"
#: ``changes.via`` on every audit row a data repair writes.
REPAIR_VIA = "data_repair"
#: Why a ``control_classification`` value is not a classification (:func:`misfiled_as`).
MISFILED_FRAMEWORK = "framework"
MISFILED_NATURE = "nature"
#: ``entity_type`` of a lookup value's audit rows (as the lookup admin writes them).
LOOKUP_ENTITY = "lookup"
#: B10b: the one approval row a record approved (or retired) with no step on file gets.
IMPORT_ACTION = "workflow_import"
IMPORTED_STATES: tuple[str, ...] = ("approved", "retired")


@dataclass
class RepairReport:
    widgets_removed: int = 0
    frameworks_merged: int = 0
    framework_kinds_set: int = 0
    control_test_dates_cleared: int = 0
    risks_flagged: int = 0
    classification_values_regraded: int = 0
    foreign_keys_matched: int = 0
    lookups_created: int = 0
    operating_effectiveness_carried: int = 0
    control_classifications_cleared: int = 0
    control_natures_set: int = 0
    classification_values_retired: int = 0
    approvals_backfilled: int = 0
    scenario_kinds_set: int = 0
    title_asset_flags_set: int = 0
    title_asset_flags_cleared: int = 0
    governance_defaults_added: int = 0
    requirement_sort_keys_filled: int = 0
    #: Phase 4C: shipped crosswalks materialised / retyped / withdrawn between installed frameworks.
    crosswalks_synced: int = 0
    #: Phase 5 decision 2: organisations moved from the old 90-day retention default to 10 years.
    retention_defaults_upgraded: int = 0
    #: Phase 5 decision 8: controls classified by their ISO/IEC 27002:2022 theme.
    control_themes_classified: int = 0
    #: B10c (decision 6): records already in force before the approval lifecycle existed,
    #: whose approval was recorded on upgrade so they can be attested again.
    predated_approvals_recorded: int = 0
    #: Maker roles on untouched legacy default rules, cleared before they became enforced.
    legacy_maker_roles_cleared: int = 0
    indexes_skipped: list[str] = field(default_factory=list)
    repairs_failed: list[str] = field(default_factory=list)

    def any(self) -> bool:
        return bool(
            self.widgets_removed or self.frameworks_merged or self.framework_kinds_set
            or self.control_test_dates_cleared or self.risks_flagged
            or self.classification_values_regraded or self.foreign_keys_matched
            or self.lookups_created or self.operating_effectiveness_carried
            or self.control_classifications_cleared or self.control_natures_set
            or self.classification_values_retired or self.approvals_backfilled
            or self.scenario_kinds_set or self.title_asset_flags_set or self.title_asset_flags_cleared
            or self.governance_defaults_added or self.control_themes_classified
            or self.requirement_sort_keys_filled or self.crosswalks_synced
            or self.retention_defaults_upgraded or self.predated_approvals_recorded
            or self.legacy_maker_roles_cleared
            or self.indexes_skipped or self.repairs_failed
        )


async def dedupe_widgets(db) -> int:
    """Keep the oldest tile per (metric, form); delete the rest."""
    rows = (
        await db.scalars(
            select(DashboardWidget).order_by(DashboardWidget.created_at, DashboardWidget.id)
        )
    ).all()
    seen: set[tuple[str, str]] = set()
    removed = 0
    for w in rows:
        key = (w.metric_key, w.viz or "number")
        if key in seen:
            await db.delete(w)
            removed += 1
        else:
            seen.add(key)
    return removed


async def clear_untestable_control_dates(db) -> int:
    """A planned or retired control carries no test or maintenance clock; drop dates
    set before that rule. Returns controls changed."""
    rows = (
        await db.scalars(
            select(Control).where(
                Control.deleted.is_(False),
                Control.status.in_(UNTESTABLE_CONTROL_STATUSES),
                or_(Control.next_audit_date.is_not(None), Control.next_maintenance_date.is_not(None)),
            )
        )
    ).all()
    for c in rows:
        c.next_audit_date = None
        c.next_maintenance_date = None
    return len(rows)


async def flag_residual_above_inherent(db) -> int:
    """Flag risks whose residual exceeds inherent with no recorded reason."""
    rows = (
        await db.scalars(
            select(Risk).where(
                Risk.deleted.is_(False),
                Risk.needs_review.is_(False),
                Risk.residual_likelihood.is_not(None),
                Risk.residual_impact.is_not(None),
                Risk.residual_likelihood * Risk.residual_impact
                > Risk.inherent_likelihood * Risk.inherent_impact,
                or_(Risk.residual_override_reason.is_(None), Risk.residual_override_reason == ""),
            )
        )
    ).all()
    for r in rows:
        r.needs_review = True
        r.review_reason = RESIDUAL_REVIEW_REASON
    return len(rows)


def regrade_plan(
    axis: str, current: list[tuple[str, float, str]]
) -> list[tuple[str, str, str]] | None:
    """How to re-grade one classification axis, or None to leave it alone.

    Only an axis that still holds *exactly* the confidentiality defaults (same names,
    values and criteria, in any order) is re-graded; anything a tenant touched is theirs.
    Returns (old name, new name, new criteria) per value, matched on the numeric grade so
    every asset keeps the grade it had.
    """
    from app.db.reference_data import CLASSIFICATION_VALUES_BY_AXIS, CONFIDENTIALITY_VALUES

    target = CLASSIFICATION_VALUES_BY_AXIS.get(axis)
    if target is None or target == CONFIDENTIALITY_VALUES:
        return None
    if sorted(current) != sorted(CONFIDENTIALITY_VALUES):
        return None
    by_value = {value: (name, criteria) for name, value, criteria in target}
    return [(name, *by_value[value]) for name, value, _criteria in current]


async def regrade_default_cia_axes(db) -> int:
    """Give untouched Integrity / Availability axes their own grade names (see
    ``reference_data.CLASSIFICATION_VALUES_BY_AXIS``). Returns values renamed."""
    from app.models.asset import AssetClassification, AssetClassificationType

    renamed = 0
    for axis in (await db.scalars(select(AssetClassificationType))).all():
        values = (
            await db.scalars(select(AssetClassification).where(AssetClassification.type_id == axis.id))
        ).all()
        plan = regrade_plan(axis.name, [(v.name, float(v.value), v.criteria or "") for v in values])
        if plan is None:
            continue
        by_name = {v.name: v for v in values}
        for old, new, criteria in plan:
            by_name[old].name = new
            by_name[old].criteria = criteria
            renamed += 1
    return renamed


async def carry_effectiveness_to_operating(db) -> int:
    """Phase 2 splits design and operating effectiveness. A control's existing rating came
    from its tests of operation, so it becomes the operating rating where that is unset."""
    from app.models.enums import ControlEffectiveness

    rows = (
        await db.scalars(
            select(Control).where(
                Control.deleted.is_(False),
                Control.operating_effectiveness == ControlEffectiveness.not_assessed,
                Control.effectiveness != ControlEffectiveness.not_assessed,
            )
        )
    ).all()
    for c in rows:
        c.operating_effectiveness = c.effectiveness
    return len(rows)


# ------------------------------------------------------------ B10: the audit row ---
def system_audit(
    db, tenant_id, *, action: str, entity_type: str, entity_id, summary: str, changes: dict,
) -> None:
    """Append one audit row attributed to the platform (``system``), never to a person.

    The row :func:`app.services.audit.record_system` writes, without its webhook fan-out:
    that delivers in-request over HTTP (up to a 5-second timeout per hook), and a start-up
    repair touching every imported record must not wait on an integration once per row.
    No version snapshot either, exactly as ``record_system``: the platform is not an
    author of the record.
    """
    from app.models.audit import AuditLog
    from app.services.audit import SYSTEM_ACTOR_EMAIL

    db.add(
        AuditLog(
            tenant_id=tenant_id, actor_id=None, actor_email=SYSTEM_ACTOR_EMAIL, action=action,
            entity_type=entity_type, entity_id=entity_id, summary=summary[:500],
            changes=changes,
        )
    )


# ------------------------------------------------ B10a: control classification ---
def _norm(text_: str | None) -> str:
    """Trimmed, case-folded, inner whitespace collapsed — ``fk_backfill.norm``."""
    from app.db.fk_backfill import norm

    return norm(text_)


def nature_of(*names: str | None) -> str | None:
    """The ``controls.nature`` value one of these classification names spells, or None."""
    for name in names:
        found = NATURE_CLASSIFICATIONS.get(_norm(name))
        if found:
            return found
    return None


def misfiled_as(label: str | None, value: str | None, framework_names: set[str]) -> str | None:
    """Why a ``control_classification`` value is not a kind of control, or None. Pure.

    ``"framework"`` when its label is an installed framework's name (``framework_names``
    are normalised): a controls-pack install wrote it, and the start-up backfill minted a
    value from the text. ``"nature"`` when it spells a control's nature (Preventive,
    Detective, Corrective, Directive), which has its own field. Anything else ("Technical",
    a bank's own values) is a genuine classification.
    """
    if _norm(label) and _norm(label) in framework_names:
        return MISFILED_FRAMEWORK
    if nature_of(label, value):
        return MISFILED_NATURE
    return None


def plan_value_retirement(
    rows, framework_names: set[str], retired_before: set
) -> tuple[list[tuple[object, str]], set]:
    """``(values to deactivate now with why, values to leave alone)``. Pure.

    ``rows`` are the list's values (``id``, ``label``, ``value``, ``active``);
    ``retired_before`` holds the ids this repair has already deactivated once (it wrote
    an audit row for each). A misfiled value is deactivated once. One an administrator
    has since re-activated is theirs: it is not deactivated again, and the controls
    classified under it are left alone (``respected``) — a start-up repair never fights
    a deliberate choice, and every boot after the first is a no-op.
    """
    retire: list[tuple[object, str]] = []
    respected: set = set()
    for row in rows:
        kind = misfiled_as(row.label, row.value, framework_names)
        if kind is None:
            continue
        if row.id in retired_before:
            if row.active:
                respected.add(row.id)
            continue
        if row.active:
            retire.append((row, kind))
    return retire, respected


@dataclass(frozen=True)
class ClassificationFix:
    """What B10a does to one control. ``framework`` is the framework name its
    classification carried; ``nature`` the value copied into an empty ``nature``."""

    clear_id: bool = False
    clear_text: bool = False
    framework: str | None = None
    nature: str | None = None
    nature_source: str | None = None

    def __bool__(self) -> bool:
        return self.clear_id or self.clear_text or self.nature is not None


def plan_classification_fix(
    *,
    text_value: str | None,
    lookup_label: str | None,
    lookup_value: str | None = None,
    has_lookup: bool,
    nature: str | None,
    framework_names: set[str],
    nature_copied_before: bool = False,
) -> ClassificationFix:
    """B10a for one control. Pure.

    ``framework_names`` are normalised (:func:`_norm`). A pack install wrote the
    framework's name as the control's classification, and the start-up backfill turned
    that text into a ``control_classification`` value; neither says what kind of control
    it is. So:

    * the link is cleared when the linked value's label is an installed framework's
      name, and the free text when *it* is one — both, because the backfill would
      otherwise re-link the text to the same value on the next start;
    * a classification that is really a nature (Preventive, Detective, Corrective,
      Directive) is copied into ``nature`` when that is empty — from the linked value,
      or from the text when nothing is linked. The classification itself is kept (its
      value is deactivated, so it can't be picked again; existing records still show it).
      It is copied once per control (``nature_copied_before``: this repair already wrote
      a nature row for it): an owner who later clears the nature has decided, and the
      next start must not put it back.
    """
    label_is_framework = has_lookup and bool(_norm(lookup_label)) and _norm(lookup_label) in framework_names
    text_is_framework = bool(_norm(text_value)) and _norm(text_value) in framework_names
    framework = None
    if label_is_framework:
        framework = (lookup_label or "").strip()
    elif text_is_framework:
        framework = (text_value or "").strip()

    copied = source = None
    if not (nature or "").strip() and not nature_copied_before:
        if has_lookup:
            copied = nature_of(lookup_label, lookup_value)
            source = (lookup_label or lookup_value or "").strip()
        elif not text_is_framework:
            copied = nature_of(text_value)
            source = (text_value or "").strip()
    return ClassificationFix(
        clear_id=label_is_framework,
        clear_text=text_is_framework,
        framework=framework,
        nature=copied,
        nature_source=source if copied else None,
    )


def classification_fix_summary(fix: ClassificationFix) -> str:
    """The audit summary for one control's B10a repair."""
    parts = []
    if fix.clear_id or fix.clear_text:
        parts.append(
            f"Cleared the classification '{fix.framework}': it names a framework, "
            "not a kind of control"
        )
    if fix.nature is not None:
        parts.append(
            f"Nature set to {fix.nature.capitalize()} from the classification "
            f"'{fix.nature_source}'"
        )
    return ("; ".join(parts) + " (data repair)")[:500]


def classification_fix_changes(
    fix: ClassificationFix, *, classification_id, text_value: str | None
) -> dict:
    """``changes`` for the audit row: each field as ``{from, to}``, plus ``via``."""
    out: dict = {}
    if fix.clear_id:
        out["classification_id"] = {"from": str(classification_id), "to": None}
    if fix.clear_text:
        out["classification"] = {"from": text_value or "", "to": ""}
    if fix.nature is not None:
        out["nature"] = {"from": None, "to": fix.nature}
    out["via"] = REPAIR_VIA
    return out


def value_retirement_audit(row, kind: str, list_name: str) -> dict:
    """The audit row (action, summary, changes) for deactivating one misfiled value —
    the shape the lookup admin writes when a person deactivates a value, plus ``via``."""
    why = (
        "it names a framework, not a kind of control"
        if kind == MISFILED_FRAMEWORK
        else "it is a control's nature, recorded in the Nature field"
    )
    return {
        "action": "update",
        "summary": f"Deactivated '{row.label}' in {list_name}: {why} (data repair)",
        "changes": {
            "key": row.key, "value": row.value,
            "active": {"from": True, "to": False}, "via": REPAIR_VIA,
        },
    }


async def repair_control_classifications(db, tenant_id) -> tuple[int, int, int]:
    """B10a. Returns (controls whose framework classification was cleared, controls given
    a nature, classification values deactivated). Each change is audited per record as
    ``system``. Idempotent: after the first start it costs three small reads."""
    from app.models.audit import AuditLog
    from app.models.compliance import Framework
    from app.models.lookup import LOOKUP_LISTS, Lookup

    framework_names = {
        _norm(n) for n in (await db.scalars(select(Framework.name))).all() if _norm(n)
    }
    lookups = list(
        (await db.scalars(select(Lookup).where(Lookup.key == CLASSIFICATION_LIST))).all()
    )
    by_id = {row.id: row for row in lookups}
    misfiled = [
        row.id for row in lookups if misfiled_as(row.label, row.value, framework_names)
    ]
    retired_before: set = set()
    if misfiled:
        retired_before = set(
            (
                await db.scalars(
                    select(AuditLog.entity_id).where(
                        AuditLog.entity_type == LOOKUP_ENTITY,
                        AuditLog.entity_id.in_(misfiled),
                        AuditLog.actor_id.is_(None),
                        AuditLog.changes["via"].astext == REPAIR_VIA,
                    )
                )
            ).all()
        )
    retire, respected = plan_value_retirement(lookups, framework_names, retired_before)
    # Text the backfill would link to a respected value is that value's too.
    respected_texts = {
        _norm(t) for row in lookups if row.id in respected for t in (row.label, row.value) if _norm(t)
    }

    suspect_ids = [i for i in misfiled if i not in respected]
    suspect_texts = sorted((framework_names | set(NATURE_CLASSIFICATIONS)) - respected_texts)
    conditions = []
    if suspect_texts:
        conditions.append(func.lower(func.trim(Control.classification)).in_(suspect_texts))
    if suspect_ids:
        conditions.append(Control.classification_id.in_(suspect_ids))
    rows = []
    if conditions:
        rows = (
            await db.execute(
                select(
                    Control.id, Control.classification, Control.classification_id, Control.nature,
                ).where(Control.deleted.is_(False), or_(*conditions))
            )
        ).all()

    # Controls this repair already gave a nature: an owner may have cleared it since,
    # and that is their call (the nature is copied once per control).
    natured_before: set = set()
    if any(not (r[3] or "").strip() for r in rows):
        natured_before = set(
            (
                await db.scalars(
                    select(AuditLog.entity_id).where(
                        AuditLog.entity_type == "control",
                        AuditLog.entity_id.in_([r[0] for r in rows if not (r[3] or "").strip()]),
                        AuditLog.actor_id.is_(None),
                        AuditLog.changes["via"].astext == REPAIR_VIA,
                        AuditLog.changes.has_key("nature"),
                    )
                )
            ).all()
        )

    cleared = natured = 0
    for cid, text_value, classification_id, nature in rows:
        if classification_id is not None and classification_id in respected:
            continue
        row = by_id.get(classification_id) if classification_id is not None else None
        if row is None and _norm(text_value) in respected_texts:
            continue
        fix = plan_classification_fix(
            text_value=text_value,
            lookup_label=row.label if row is not None else None,
            lookup_value=row.value if row is not None else None,
            has_lookup=row is not None,
            nature=nature,
            framework_names=framework_names,
            nature_copied_before=cid in natured_before,
        )
        if not fix:
            continue
        values: dict = {}
        if fix.clear_id:
            values["classification_id"] = None
        if fix.clear_text:
            values["classification"] = ""
        if fix.nature is not None:
            values["nature"] = fix.nature
        await db.execute(
            update(Control).where(Control.id == cid).values(**values)
            .execution_options(synchronize_session=False)
        )
        system_audit(
            db, tenant_id, action="update", entity_type="control", entity_id=cid,
            summary=classification_fix_summary(fix),
            changes=classification_fix_changes(
                fix, classification_id=classification_id, text_value=text_value,
            ),
        )
        cleared += int(fix.clear_id or fix.clear_text)
        natured += int(fix.nature is not None)

    list_name = LOOKUP_LISTS.get(CLASSIFICATION_LIST, ("Control classification", True))[0]
    for row, kind in retire:
        row.active = False  # a loaded row: the session writes it, and stays in step
        system_audit(
            db, tenant_id, entity_type=LOOKUP_ENTITY, entity_id=row.id,
            **value_retirement_audit(row, kind, list_name),
        )
    return cleared, natured, len(retire)


# ------------------------------------------- B10b: approvals with no step on file ---
def imported_approval_audit(state: str) -> dict:
    """The one audit row (action, summary, changes) B10b writes for a record in
    ``state`` with no approval step on file. It names no person: nobody is on record as
    having approved it, and the trail must not imply otherwise."""
    return {
        "action": IMPORT_ACTION,
        "summary": f"Imported as {state}: no approver recorded",
        "changes": {"from": None, "to": state, "via": "import"},
    }


def workflow_step_actions():
    """Audit actions that are an approval *step*: every ``workflow_*`` row except an
    approval-owner change (``workflow_owner``), which approves nothing — the record page
    counts steps the same way, so a record whose only row is an owner change still
    reads "No approval step on file" and is still a candidate."""
    from app.models.audit import AuditLog
    from app.services.record_workflow import AUDIT_PREFIX

    return (
        AuditLog.action.like(f"{AUDIT_PREFIX}%"),
        AuditLog.action != f"{AUDIT_PREFIX}owner",
    )


def imported_approvals_query(model, entity_type: str):
    """Live records of ``model`` that are approved or retired and have no approval step
    in the trail under ``entity_type`` — the B10b candidates. ``None`` when the model
    has no lifecycle column."""
    from app.models.audit import AuditLog
    from app.services import record_registry

    if not record_registry.has_workflow(model):
        return None
    column = model.__table__.c.workflow_status
    enum_class = getattr(column.type, "enum_class", None)
    states = (
        [enum_class(s) for s in IMPORTED_STATES if s in enum_class._value2member_map_]
        if enum_class is not None else list(IMPORTED_STATES)
    )
    if not states:
        return None
    step = (
        select(AuditLog.id)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == model.id, *workflow_step_actions())
        .exists()
    )
    stmt = select(model.id, model.workflow_status).where(model.workflow_status.in_(states), ~step)
    if "deleted" in model.__table__.c:
        stmt = stmt.where(model.deleted.is_(False))
    return stmt


async def backfill_imported_approvals(db, tenant_id) -> int:
    """B10b. Every registered record type with a lifecycle: a record that is approved or
    retired with no approval step on file gets one ``workflow_import`` row, attributed
    to ``system``. Idempotent: the row it writes is itself an approval step, so the
    record is not a candidate on the next start. Returns rows written."""
    from app.services import record_registry
    from app.services.entity_types import ENTITY_TYPES

    written = 0
    seen: set = set()
    for entity_type in ENTITY_TYPES:
        model = record_registry.model_for(entity_type)
        if model is None or model in seen:
            continue
        seen.add(model)
        stmt = imported_approvals_query(model, entity_type)
        if stmt is None:
            continue
        for rid, state in (await db.execute(stmt)).all():
            system_audit(
                db, tenant_id, entity_type=entity_type, entity_id=rid,
                **imported_approval_audit(str(getattr(state, "value", state))),
            )
            written += 1
    return written


# ------------------- B10c: records that predate the approval lifecycle (decision 6) ---
#: ``changes.via`` on a B10c row, telling it apart from B10b's plain ``import``.
PREDATES_VIA = "predates_workflow"
#: The *business* statuses that mean "this record is in force", per record type. Only
#: these grandfather a record whose approval was never recorded: a draft-equivalent
#: (planned, prospective, open, in progress, under review, proposed) never does, and
#: neither does a terminal state that was never live (a retired policy or control).
#: Decision 6 refuses to attest anything that is not approved, so without this a bank's
#: whole pre-upgrade register — every live policy, operating control and assessed risk —
#: could never be certified again.
LIVE_BUSINESS_STATUSES: dict[str, tuple[str, ...]] = {
    # PolicyStatus: draft, under_review, approved, published, retired
    "policy": ("approved", "published"),
    # ControlStatus: planned, implemented, operational, retired
    "control": ("implemented", "operational"),
    # RiskStatus: draft, assessed, treatment_planned, treatment_in_progress, accepted, closed
    "risk": ("assessed", "treatment_planned", "treatment_in_progress", "accepted", "closed"),
    # VendorStatus: prospective, active, suspended, offboarded — a suspended or offboarded
    # third party was live, but only an active one is in force today.
    "vendor": ("active",),
    # IncidentStatus: open, triage, investigating, contained, resolved, closed
    "incident": ("closed",),
    # IssueStatus2: open, in_progress, remediated, closed, risk_accepted
    "issue": ("closed", "risk_accepted"),
}


def predated_approval_audit(label: str, business_state: str) -> dict:
    """The one audit row B10c writes. It names no person — nobody approved the record —
    and says plainly why the platform recorded the approval."""
    return {
        "action": IMPORT_ACTION,
        "summary": (
            f"Approval recorded on upgrade: this {label} was already {business_state.replace('_', ' ')} "
            "before the approval workflow existed, so it had no approval to complete"
        ),
        "changes": {"from": "draft", "to": "approved", "via": PREDATES_VIA,
                    "business_status": business_state},
    }


def _enum_values(column, wanted: Iterable[str]) -> list:
    """``wanted`` as the column's own enum members, dropping any the enum doesn't have."""
    enum_class = getattr(column.type, "enum_class", None)
    if enum_class is None:
        return list(wanted)
    return [enum_class(v) for v in wanted if v in enum_class._value2member_map_]


def predated_approvals_query(model, entity_type: str):
    """Live records of ``model`` whose *business* status says they are in force, whose
    approval is still ``draft``, and which have no approval history at all — the B10c
    candidates. ``None`` when the type has no such status or no lifecycle.

    A record in review, or one a reviewer rejected back to draft, is excluded: the
    rejection is itself an approval step, so the "no history" test leaves it out.
    """
    from app.models.audit import AuditLog
    from app.services import record_registry

    wanted = LIVE_BUSINESS_STATUSES.get(entity_type)
    if not wanted or not record_registry.has_workflow(model):
        return None
    columns = model.__table__.c
    business = columns.get("status")
    if business is None:
        return None
    states = _enum_values(business, wanted)
    draft = _enum_values(columns.workflow_status, ("draft",))
    if not states or not draft:
        return None
    step = (
        select(AuditLog.id)
        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == model.id, *workflow_step_actions())
        .exists()
    )
    stmt = select(model.id, business).where(
        columns.workflow_status == draft[0], business.in_(states), ~step
    )
    if "deleted" in columns:
        stmt = stmt.where(model.deleted.is_(False))
    return stmt


async def approve_predated_records(db, tenant_id) -> int:
    """B10c. A record written before the approval lifecycle existed sits at
    ``workflow_status = draft`` however live it is, and decision 6 would leave it
    permanently un-attestable. Where its own business status says it is in force
    (:data:`LIVE_BUSINESS_STATUSES`) and nobody has ever taken an approval step on it,
    the approval is recorded as ``approved`` with one ``system`` audit row saying why.

    Once per record: that row is itself an approval step, so the record stops being a
    candidate. It never touches a record with any approval history (a rejection
    included), one in review, or one whose business status is a draft equivalent.
    Returns the number of records approved.
    """
    from app.services import record_registry
    from app.services.entity_types import ENTITY_TYPES

    approved = 0
    for entity_type in LIVE_BUSINESS_STATUSES:
        if entity_type not in ENTITY_TYPES:
            continue
        model = record_registry.model_for(entity_type)
        stmt = predated_approvals_query(model, entity_type) if model is not None else None
        if stmt is None:
            continue
        label = record_registry.type_label(entity_type, model).lower()
        live = _enum_values(model.__table__.c.workflow_status, ("approved",))
        if not live:
            continue
        for rid, business in (await db.execute(stmt)).all():
            await db.execute(
                update(model).where(model.id == rid)
                # Recording history is not an edit: keep the record's last-updated time.
                .values(workflow_status=live[0], updated_at=model.updated_at)
                .execution_options(synchronize_session=False)
            )
            system_audit(
                db, tenant_id, entity_type=entity_type, entity_id=rid,
                **predated_approval_audit(label, str(getattr(business, "value", business))),
            )
            approved += 1
    return approved


# ------------------------------------ re-check F-04: scenario kinds, title vs asset ---
#: ``changes`` key on the audit row written when a template takes the library's kinds.
SCENARIO_KINDS_CHANGE = "asset_kinds"


async def backfill_scenario_kinds(db, tenant_id) -> int:
    """Installed library scenarios that predate asset kinds take the library's kinds
    (``risk_scenarios.library_kinds_for``: only rows still *being* the library scenario).
    Once per template: a row this repair already filled and a person has since cleared
    ("every kind") is theirs and stays cleared. One ``system`` audit row per template.
    Returns templates changed."""
    from app.models.audit import AuditLog
    from app.models.risk_scenario import RiskScenarioTemplate
    from app.services.risk_scenarios import CATALOGUE, library_kinds_for

    specs = {s.reference: s for s in CATALOGUE}
    rows = (
        await db.scalars(
            select(RiskScenarioTemplate).where(
                RiskScenarioTemplate.reference.in_(sorted(specs)),
                or_(RiskScenarioTemplate.asset_kinds.is_(None), RiskScenarioTemplate.asset_kinds == ""),
            )
        )
    ).all()
    todo = [(row, kinds) for row in rows if (kinds := library_kinds_for(row, specs[row.reference]))]
    if not todo:
        return 0
    filled_before = set(
        (
            await db.scalars(
                select(AuditLog.entity_id).where(
                    AuditLog.entity_type == "risk_scenario",
                    AuditLog.entity_id.in_([row.id for row, _ in todo]),
                    AuditLog.actor_id.is_(None),
                    AuditLog.changes["via"].astext == REPAIR_VIA,
                    AuditLog.changes.has_key(SCENARIO_KINDS_CHANGE),
                )
            )
        ).all()
    )
    changed = 0
    for row, kinds in todo:
        if row.id in filled_before:
            continue
        row.asset_kinds = kinds
        system_audit(
            db, tenant_id, action="update", entity_type="risk_scenario", entity_id=row.id,
            summary=f"Risk scenario {row.reference} now fits only these asset kinds: {kinds} (data repair)",
            changes={SCENARIO_KINDS_CHANGE: {"from": "", "to": kinds}, "via": REPAIR_VIA},
        )
        changed += 1
    return changed


async def _guarded(db, report: RepairReport, name: str, step):
    """Run one repair in a savepoint; on failure roll it back, log it and carry on, so
    one bad row never stops the start-up (the repair retries on the next start)."""
    try:
        async with db.begin_nested():
            return await step()
    except Exception:  # noqa: BLE001 - a repair must not stop the start-up
        logger.exception("Data repair %s failed; it will retry on the next start", name)
        report.repairs_failed.append(name)
        return None


async def fill_requirement_sort_keys(db) -> int:
    """F-16: every requirement carries the natural-order key of its reference
    (``services.reference_sort``). Rows written before the column existed, or by a
    path that bypassed the model, are filled; a correct key is left alone."""
    from app.models.compliance import Requirement
    from app.services.reference_sort import reference_sort_key

    rows = (await db.execute(
        select(Requirement.id, Requirement.reference, Requirement.reference_sort_key)
    )).all()
    fixed = 0
    for rid, reference, stored in rows:
        key = reference_sort_key(reference)
        if key != (stored or ""):
            await db.execute(
                update(Requirement).where(Requirement.id == rid)
                # A derived key is not an edit: keep the clause's last-updated time.
                .values(reference_sort_key=key, updated_at=Requirement.updated_at)
                .execution_options(synchronize_session=False)
            )
            fixed += 1
    return fixed


async def seed_default_governance(db, tenant_id) -> int:
    """Default approval routes and dual-control rules for an organisation that predates
    them (``services/default_governance.py``). Runs once per organisation; returns the
    number of routes and rules added or upgraded."""
    from app.services import default_governance

    if await default_governance.already_seeded(db):
        return 0
    result = await default_governance.ensure_default_governance(db, tenant_id)
    return len(result.routes_added) + len(result.routes_upgraded) + result.rules_added


async def _clear_legacy_maker_roles(db, tenant_id) -> int:
    from app.services import default_governance

    return await default_governance.clear_legacy_maker_roles(db, tenant_id)


async def _reconcile_title_flags(db) -> tuple[int, int]:
    from app.services.risk_integrity import reconcile_generated_title_flags

    return await reconcile_generated_title_flags(db)


async def repair_tenant(db, report: RepairReport, tenant_id=None) -> None:
    from app.db.fk_backfill import backfill_foreign_keys
    from app.services import framework_library
    from app.services.issue_closure import backfill_source_links

    report.widgets_removed += await dedupe_widgets(db)
    report.frameworks_merged += await framework_library.merge_duplicate_frameworks(db)
    report.framework_kinds_set += await framework_library.backfill_framework_kinds(db)
    report.control_test_dates_cleared += await clear_untestable_control_dates(db)
    report.risks_flagged += await flag_residual_above_inherent(db)
    report.classification_values_regraded += await regrade_default_cia_axes(db)
    report.operating_effectiveness_carried += await carry_effectiveness_to_operating(db)
    await backfill_source_links(db)  # issues raised from a record get the typed link (2.3)
    report.requirement_sort_keys_filled += await fill_requirement_sort_keys(db)  # F-16
    if tenant_id is not None:
        # B10: before the foreign-key backfill, which would otherwise re-link a
        # framework name typed into a control's classification on this very start.
        await db.flush()
        fixed = await _guarded(
            db, report, "control_classifications",
            lambda: repair_control_classifications(db, tenant_id),
        )
        if fixed:
            report.control_classifications_cleared += fixed[0]
            report.control_natures_set += fixed[1]
            report.classification_values_retired += fixed[2]
        report.approvals_backfilled += await _guarded(
            db, report, "imported_approvals", lambda: backfill_imported_approvals(db, tenant_id),
        ) or 0
        # B10c: a record already in force before the approval lifecycle existed is
        # approved, so decision 6 does not leave it permanently un-attestable. After
        # B10b, which is about records already approved.
        report.predated_approvals_recorded += await _guarded(
            db, report, "predated_approvals", lambda: approve_predated_records(db, tenant_id),
        ) or 0
        # Re-check F-04: scenarios fit asset kinds; a generated title naming an asset
        # the risk does not link is flagged for review (and the flag cleared once fixed).
        report.scenario_kinds_set += await _guarded(
            db, report, "scenario_kinds", lambda: backfill_scenario_kinds(db, tenant_id),
        ) or 0
        title_flags = await _guarded(
            db, report, "generated_title_asset", lambda: _reconcile_title_flags(db),
        )
        if title_flags:
            report.title_asset_flags_set += title_flags[0]
            report.title_asset_flags_cleared += title_flags[1]
        # Lookup seeding (reference data) runs before this, so defined values match first.
        fk = await backfill_foreign_keys(db, tenant_id)
        report.foreign_keys_matched += fk.matched
        report.lookups_created += fk.lookups_created
        # F-06 re-check: default approval routes and dual-control rules, once per
        # organisation (marked in the activity log). Never overwrites.
        report.governance_defaults_added += await _guarded(
            db, report, "default_governance", lambda: seed_default_governance(db, tenant_id),
        ) or 0
        # Maker roles became enforced (dual_control.enforce_maker_role). The old defaults
        # named "Risk Manager" as the maker of risk acceptance, risk approval and exception
        # approval, never enforced; on rules still exactly as seeded it is cleared (one
        # audit row per organisation), so the upgrade blocks nobody. Rules an
        # administrator created or edited keep what they say.
        report.legacy_maker_roles_cleared += await _guarded(
            db, report, "legacy_maker_roles", lambda: _clear_legacy_maker_roles(db, tenant_id),
        ) or 0
        # --- phase4c: shipped crosswalk content (idempotent; rejected rows stay out) ---
        report.crosswalks_synced += await _guarded(
            db, report, "phase4c_crosswalk_content", lambda: _sync_crosswalk_content(db),
        ) or 0
        # --- phase5 decision 8: ISO 27002 theme as the control's classification ---
        # After B10a (which clears framework names) and after the lookup seed, so the four
        # themes exist and a cleared classification can take one.
        report.control_themes_classified += await _guarded(
            db, report, "phase5_control_themes",
            lambda: backfill_control_classification_themes(db, tenant_id),
        ) or 0
        # --- phase5 decision 2: retention default 90 days -> 10 years, once, audited ---
        report.retention_defaults_upgraded += int(bool(await _guarded(
            db, report, "phase5_retention_default", lambda: upgrade_retention_default(db, tenant_id),
        )))
    await db.flush()


# ------------------------------- phase5 decision 2: retention default upgrade ---
#: The window organisations had by default before decision 2, and the new one.
OLD_RETENTION_DEFAULT_DAYS = 90
NEW_RETENTION_DEFAULT_DAYS = 3650
#: Audit marker: the upgrade runs once per organisation, even if an admin later sets 90
#: again deliberately (below the new minimum, so only through the database).
RETENTION_UPGRADE_ENTITY = "tenant_settings"
RETENTION_UPGRADE_ACTION = "retention_default_upgrade"


async def upgrade_retention_default(db, tenant_id) -> bool:
    """Move an organisation still on exactly the old 90-day default to ten years.

    Decision 2 (2026-09-17): archived records stay restorable for ten years by default. An
    organisation that chose any other window keeps it. Runs once per organisation (the
    audit row is the marker) and returns whether it changed anything.
    """
    from app.models.audit import AuditLog
    from app.models.settings import TenantSettings

    done = await db.scalar(
        select(AuditLog.id).where(
            AuditLog.entity_type == RETENTION_UPGRADE_ENTITY,
            AuditLog.action == RETENTION_UPGRADE_ACTION,
        ).limit(1)
    )
    if done is not None:
        return False
    row = await db.scalar(select(TenantSettings).where(TenantSettings.tenant_id == tenant_id))
    changed = row is not None and row.retention_days == OLD_RETENTION_DEFAULT_DAYS
    if changed:
        row.retention_days = NEW_RETENTION_DEFAULT_DAYS
    system_audit(
        db, tenant_id, action=RETENTION_UPGRADE_ACTION, entity_type=RETENTION_UPGRADE_ENTITY,
        entity_id=row.id if row is not None else None,
        summary=(
            f"Retention for archived records moved from {OLD_RETENTION_DEFAULT_DAYS} days to "
            f"{NEW_RETENTION_DEFAULT_DAYS} days (10 years), the new default. The audit trail is never deleted."
            if changed else "Retention default check: organisation's own retention window kept"
        ),
        changes={
            "retention_days": [OLD_RETENTION_DEFAULT_DAYS, NEW_RETENTION_DEFAULT_DAYS] if changed else None,
            "kept": None if changed or row is None else row.retention_days,
        },
    )
    return changed


async def _sync_crosswalk_content(db) -> int:
    """Phase 4C: materialise the shipped crosswalks between this tenant's installed library
    frameworks (``services.crosswalks.sync_shipped``). A content upgrade lands here on the
    next start; a tenant's rejections and its own typed rows are never overwritten."""
    from app.services.crosswalks import sync_shipped

    return (await sync_shipped(db)).changed


UNIQUE_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "uq_frameworks_tenant_name",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_frameworks_tenant_name "
        "ON frameworks (tenant_id, lower(name)) WHERE deleted = false",
    ),
    (
        "uq_dashboard_widgets_metric",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_dashboard_widgets_metric "
        "ON dashboard_widgets (tenant_id, metric_key, viz)",
    ),
)


async def create_unique_indexes(report: RepairReport) -> None:
    from app.db.init_db import admin_engine

    for name, ddl in UNIQUE_INDEXES:
        try:
            async with admin_engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception:  # noqa: BLE001 - a surviving duplicate must not stop the start
            logger.exception("Could not create unique index %s; duplicates remain", name)
            report.indexes_skipped.append(name)


async def repair_data() -> RepairReport:
    """Run every repair for every tenant, then add the unique indexes."""
    report = RepairReport()
    async with tenant_session(None) as db:
        tenants = (await db.scalars(select(Tenant))).all()
        for tenant in tenants:
            await set_session_tenant(db, tenant.id)
            await repair_tenant(db, report, tenant.id)
    await create_unique_indexes(report)
    return report


# ------------- phase5 decision 8: ISO 27002 theme classification backfill ---------
#: ISO 27001:2022 Annex A clause -> the ISO/IEC 27002:2022 theme it belongs to, which is
#: the ``control_classification`` value seeded by decision 8 (``db.lookup_seed``).
ANNEX_A_THEMES: dict[str, str] = {
    "5": "organizational",
    "6": "people",
    "7": "physical",
    "8": "technological",
}
#: Themes, for reading an explicit theme out of stored ISO 27002 attributes.
ISO27002_THEMES: tuple[str, ...] = ("organizational", "people", "physical", "technological")
#: Audit action for the backfill (one row per control it classifies).
THEME_BACKFILL_ACTION = "classification_backfill"


def theme_of_reference(reference: str | None) -> str | None:
    """The ISO 27002 theme an ISO 27001 Annex A clause belongs to, or None. Pure.

    ``"A.8.13"`` / ``"a 8.13"`` -> ``"technological"``. Only A.5 – A.8 of the 2022 edition
    count; a 2013-edition reference (A.9 …) or anything else answers None.
    """
    text_ = (reference or "").strip().lower()
    match = re.match(r"^a[\s._-]*([0-9]+)", text_)
    if match is None:
        return None
    return ANNEX_A_THEMES.get(match.group(1))


def theme_of_attributes(attributes: object) -> str | None:
    """The theme named in a control's stored ISO 27002 attributes, or None. Pure.

    The 2022 attribute vocabulary has no theme attribute, but imported content often
    carries one (``{"theme": ["Technological"]}`` / ``{"themes": "#Physical"}``); it is
    read when it is there and ignored otherwise. Two different themes mean nothing
    certain, so nothing is written.
    """
    if not isinstance(attributes, dict):
        return None
    found: set[str] = set()
    for key, raw in attributes.items():
        if str(key).strip().lower().lstrip("#") not in ("theme", "themes"):
            continue
        values = raw if isinstance(raw, (list, tuple, set)) else [raw]
        for value in values:
            token = str(value).strip().lstrip("#").lower().replace("-", "_").replace(" ", "_")
            if token in ISO27002_THEMES:
                found.add(token)
    return found.pop() if len(found) == 1 else None


def theme_for_control(
    *, reference: str | None, attributes: object, clause_references: Iterable[str] = ()
) -> str | None:
    """The theme a control belongs to, or None. Pure.

    In order: a theme stated in its ISO 27002 attributes; its own reference when that is
    an Annex A clause; otherwise the clauses it implements, but only when they all point
    at one theme (a control implementing A.5 and A.8 is neither).
    """
    stated = theme_of_attributes(attributes)
    if stated:
        return stated
    own = theme_of_reference(reference)
    if own:
        return own
    themes = {t for t in (theme_of_reference(r) for r in clause_references) if t}
    return themes.pop() if len(themes) == 1 else None


async def backfill_control_classification_themes(db, tenant_id) -> int:
    """Decision 8 (2026-09-17): classify by ISO/IEC 27002:2022 theme where the control
    already says which one it is, and only where nothing is classified yet.

    An empty ``classification_id`` is filled from the control's ISO 27002 attributes, its
    own Annex A reference, or the single theme of the clauses it implements — matching the
    seeded ``control_classification`` value. A control that carries any classification
    (linked or free text) is left alone, as is one this repair has already classified and
    somebody has since cleared: the audit row is the marker, so the next start does not
    undo their decision. One audit row per control, attributed to the platform.
    """
    from app.models.audit import AuditLog
    from app.models.compliance import Requirement, requirement_controls
    from app.models.lookup import Lookup

    values = {
        (value or "").strip().lower(): lid
        for lid, value in (
            await db.execute(
                select(Lookup.id, Lookup.value).where(
                    Lookup.key == CLASSIFICATION_LIST, Lookup.active.is_(True)
                )
            )
        ).all()
    }
    if not values:
        return 0
    rows = (
        await db.execute(
            select(Control.id, Control.reference, Control.iso27002_attributes).where(
                Control.classification_id.is_(None),
                or_(Control.classification.is_(None), func.trim(Control.classification) == ""),
                Control.deleted.is_(False),
            )
        )
    ).all()
    if not rows:
        return 0
    done = {
        cid
        for (cid,) in (
            await db.execute(
                select(AuditLog.entity_id).where(
                    AuditLog.entity_type == "control", AuditLog.action == THEME_BACKFILL_ACTION
                )
            )
        ).all()
    }
    clauses: dict[object, list[str]] = {}
    ids = [r[0] for r in rows if r[0] not in done]
    if not ids:
        return 0
    for cid, reference in (
        await db.execute(
            select(requirement_controls.c.control_id, Requirement.reference)
            .join(Requirement, Requirement.id == requirement_controls.c.requirement_id)
            .where(requirement_controls.c.control_id.in_(ids), Requirement.deleted.is_(False))
        )
    ).all():
        clauses.setdefault(cid, []).append(reference or "")

    filled = 0
    for cid, reference, attributes in rows:
        if cid in done:
            continue
        theme = theme_for_control(
            reference=reference, attributes=attributes, clause_references=clauses.get(cid, ())
        )
        lookup_id = values.get(theme or "")
        if lookup_id is None:
            continue
        await db.execute(
            update(Control).where(Control.id == cid)
            # A derived classification is not an edit: keep the control's last-updated time.
            .values(classification_id=lookup_id, updated_at=Control.updated_at)
            .execution_options(synchronize_session=False)
        )
        system_audit(
            db, tenant_id, action=THEME_BACKFILL_ACTION, entity_type="control", entity_id=cid,
            summary=(
                f"Classification set to {theme.capitalize()} from the control's ISO/IEC 27002 theme "
                "(data repair)"
            ),
            changes={"classification_id": {"from": None, "to": str(lookup_id)}, "via": REPAIR_VIA},
        )
        filled += 1
    return filled


__all__ = [
    "ANNEX_A_THEMES",
    "LIVE_BUSINESS_STATUSES",
    "NATURE_CLASSIFICATIONS",
    "RESIDUAL_REVIEW_REASON",
    "UNTESTABLE_CONTROL_STATUSES",
    "RepairReport",
    "approve_predated_records",
    "predated_approvals_query",
    "repair_data",
    "repair_tenant",
    "regrade_plan",
    "theme_for_control",
]
