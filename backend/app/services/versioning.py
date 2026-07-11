"""Versioning service — snapshot a record's columns into ``record_versions`` on each
change, and restore a record to a prior version. Wired into the audit pipeline so every
mutation that calls ``audit.record`` is versioned automatically (for mapped models)."""
from __future__ import annotations

import decimal
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.compliance import Framework, Requirement
from app.models.control import Control
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.incident import Incident
from app.models.organization import BusinessUnit, Legal, Process
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.risk import Risk
from app.models.vendor import Vendor
from app.models.version import RecordVersion

# entity_type (as used in audit.record) -> model
MODEL_MAP: dict[str, type] = {
    "risk": Risk,
    "control": Control,
    "asset": Asset,
    "policy": Policy,
    "incident": Incident,
    "project": Project,
    "goal": Goal,
    "exception": ExceptionRecord,
    "vendor": Vendor,
    "requirement": Requirement,
    "framework": Framework,
    "processing_activity": ProcessingActivity,
    "business_unit": BusinessUnit,
    "process": Process,
    "legal": Legal,
}

_SKIP = {"tenant_id"}


def _json(value):
    # Must be TOTAL: the result is written to a JSONB column at commit time, which
    # happens after the HTTP response is sent — a non-serialisable value here (e.g. a
    # Decimal from a Numeric column) would fail the flush and silently roll back the
    # whole request. Anything unrecognised degrades to str rather than corrupting it.
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def snapshot_columns(entity) -> dict:
    return {c.name: _json(getattr(entity, c.name)) for c in entity.__table__.columns if c.name not in _SKIP}


async def capture(db: AsyncSession, entity_type: str, entity_id, actor_email: str, action: str, summary: str) -> None:
    """Record a new version of an entity (best-effort; never raises to the caller)."""
    cls = MODEL_MAP.get(entity_type)
    if cls is None or entity_id is None:
        return
    try:
        entity = await db.scalar(select(cls).where(cls.id == entity_id))
        if entity is None:
            return
        last = await db.scalar(
            select(func.max(RecordVersion.version_no)).where(
                RecordVersion.entity_type == entity_type, RecordVersion.entity_id == entity_id
            )
        )
        db.add(
            RecordVersion(
                tenant_id=entity.tenant_id,
                entity_type=entity_type,
                entity_id=entity_id,
                version_no=(last or 0) + 1,
                action=action,
                actor_email=actor_email,
                summary=summary,
                snapshot=snapshot_columns(entity),
            )
        )
    except Exception:  # noqa: BLE001 - versioning must never break a GRC operation
        return


def _coerce(col, value):
    """Convert a JSON-serialised snapshot value back to the column's Python type."""
    if value is None:
        return None
    try:
        pytype = col.type.python_type
    except (NotImplementedError, AttributeError):
        return value
    if isinstance(pytype, type) and issubclass(pytype, enum.Enum):
        return pytype(value)
    if pytype is uuid.UUID and isinstance(value, str):
        return uuid.UUID(value)
    if pytype is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    if pytype is date and isinstance(value, str):
        return date.fromisoformat(value[:10])
    return value


async def restore(db: AsyncSession, version: RecordVersion) -> object | None:
    """Restore the entity to this version's snapshot (column values only)."""
    cls = MODEL_MAP.get(version.entity_type)
    if cls is None:
        return None
    entity = await db.scalar(select(cls).where(cls.id == version.entity_id))
    if entity is None:
        return None
    protected = {"id", "tenant_id", "created_at", "deleted", "deleted_date"}
    by_name = {c.name: c for c in entity.__table__.columns}
    for key, value in version.snapshot.items():
        col = by_name.get(key)
        if col is None or key in protected or col.computed is not None:
            continue  # skip generated columns (e.g. inherent_score)
        setattr(entity, key, _coerce(col, value))
    await db.flush()
    return entity
