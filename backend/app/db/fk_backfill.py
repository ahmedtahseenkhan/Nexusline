"""Match free-text owners, units and categories onto the phase-1 foreign keys.

Runs on every start inside each tenant's session (from ``app.db.data_repairs``) and only
looks at rows whose new key is still empty and whose old text is not, so after the first
run it costs one cheap query per column.

Matching is exact after trimming and ignoring case:

* people: the user's email or full name;
* business units and processes: the name;
* lookups: the value or label within the column's list — and for a list that may be
  seeded from text (``LOOKUP_LISTS``), a value nobody has defined yet becomes a new
  lookup row, so an organisation's own categories carry over as its governed list.

Text that matches nothing is left where it is; the forms show it as "was: …" beside the
picker until someone picks a real value. Nothing is ever overwritten.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select, update

from app.core.database import Base
from app.db.schema_patches import PHASE1_FK_COLUMNS, workflow_tables
from app.models.identity import User
from app.models.lookup import LOOKUP_LISTS, Lookup
from app.models.organization import BusinessUnit, Process

#: Which governed list each lookup-backed column draws from.
FK_LOOKUP_KEYS: dict[tuple[str, str], str] = {
    ("risks", "category_id"): "risk_category",
    ("rcsa_risks", "category_id"): "risk_category",
    ("controls", "classification_id"): "control_classification",
    ("issues", "category_id"): "issue_category",
    ("incidents", "category_id"): "incident_type",
    ("incidents", "classification_id"): "incident_classification",
    ("incidents", "regulator_id"): "regulator",
    ("key_risk_indicators", "category_id"): "kri_category",
    ("policies", "category_id"): "policy_category",
    ("legals", "category_id"): "legal_category",
    ("vendors", "category_id"): "vendor_category",
    ("vendors", "country_id"): "country",
}


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm(text)).strip("_")[:120] or "value"


@dataclass
class BackfillReport:
    matched: int = 0
    lookups_created: int = 0
    unmatched: dict[str, int] = field(default_factory=dict)


async def _people(db) -> dict[str, object]:
    out: dict[str, object] = {}
    for uid, email, name in (await db.execute(select(User.id, User.email, User.full_name))).all():
        if name:
            out.setdefault(norm(name), uid)
        if email:
            out[norm(email)] = uid
    return out


async def _named(db, model) -> dict[str, object]:
    rows = (await db.execute(select(model.id, model.name).where(model.deleted.is_(False)))).all()
    return {norm(name): rid for rid, name in rows if name}


async def _lookup_index(db, key: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for lid, value, label in (
        await db.execute(select(Lookup.id, Lookup.value, Lookup.label).where(Lookup.key == key))
    ).all():
        out.setdefault(norm(value), lid)
        out[norm(label)] = lid
    return out


async def backfill_foreign_keys(db, tenant_id) -> BackfillReport:
    report = BackfillReport()
    people: dict[str, object] | None = None
    targets: dict[str, dict[str, object]] = {}

    columns = [(t, c, tgt, anchor) for t, c, tgt, anchor in PHASE1_FK_COLUMNS]
    columns += [(t, "workflow_owner_id", "users", "workflow_owner") for t in workflow_tables()]

    for table_name, col, target, anchor in columns:
        table = Base.metadata.tables.get(table_name)
        if table is None or col not in table.c or anchor not in table.c:
            continue
        pending = (
            await db.execute(
                select(table.c.id, table.c[anchor]).where(
                    table.c[col].is_(None), table.c[anchor].is_not(None), table.c[anchor] != ""
                )
            )
        ).all()
        if not pending:
            continue

        lookup_key = FK_LOOKUP_KEYS.get((table_name, col)) if target == "lookups" else None
        if target == "users":
            people = people if people is not None else await _people(db)
            index = people
        elif target == "business_units":
            index = targets.setdefault("business_units", await _named(db, BusinessUnit))
        elif target == "processes":
            index = targets.setdefault("processes", await _named(db, Process))
        elif lookup_key:
            index = targets.setdefault(f"lookup:{lookup_key}", await _lookup_index(db, lookup_key))
        else:
            continue

        by_target: dict[object, list] = {}
        for row_id, text in pending:
            key = norm(text)
            target_id = index.get(key)
            if target_id is None and lookup_key and LOOKUP_LISTS.get(lookup_key, ("", False))[1]:
                row = Lookup(
                    tenant_id=tenant_id, key=lookup_key, value=slug(text), label=text.strip()
                )
                db.add(row)
                await db.flush()
                index[key] = index[norm(row.value)] = target_id = row.id
                report.lookups_created += 1
            if target_id is None:
                report.unmatched[f"{table_name}.{anchor}"] = (
                    report.unmatched.get(f"{table_name}.{anchor}", 0) + 1
                )
                continue
            by_target.setdefault(target_id, []).append(row_id)

        for target_id, ids in by_target.items():
            await db.execute(update(table).where(table.c.id.in_(ids)).values({col: target_id}))
            report.matched += len(ids)
    return report
