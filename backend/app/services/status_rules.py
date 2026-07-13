"""Dynamic status rule engine — introspect evaluable fields per model and evaluate
admin-defined rules against records to produce colored labels."""
from __future__ import annotations

import enum as _enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum

from app.models.asset import Asset
from app.models.compliance import Requirement
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.incident import Incident
from app.models.operational_risk import KeyRiskIndicator, RcsaAssessment
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.risk import Risk
from app.models.vendor import Vendor

# Models that support dynamic status rules.
MODEL_MAP: dict[str, type] = {
    "risk": Risk,
    "control": Control,
    "incident": Incident,
    "vendor": Vendor,
    "project": Project,
    "policy": Policy,
    "asset": Asset,
    "goal": Goal,
    "exception": ExceptionRecord,
    "requirement": Requirement,
    "continuity_plan": ContinuityPlan,
    "processing_activity": ProcessingActivity,
    "key_risk_indicator": KeyRiskIndicator,
    "rcsa_assessment": RcsaAssessment,
}

OPERATORS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "overdue", "is_true", "is_false", "not_empty"]

_SKIP = {"id", "tenant_id", "created_at", "updated_at"}


def _field_type(col) -> str | None:
    t = col.type
    if isinstance(t, SAEnum):
        return "enum"
    if isinstance(t, Boolean):
        return "bool"
    if isinstance(t, (Integer, Numeric)):
        return "number"
    if isinstance(t, (Date, DateTime)):
        return "date"
    if isinstance(t, (String, Text)):
        return "text"
    return None


def evaluable_fields(model: str) -> list[dict]:
    cls = MODEL_MAP[model]
    out: list[dict] = []
    for col in cls.__table__.columns:
        if col.name in _SKIP or col.name.endswith("_id"):
            continue
        ftype = _field_type(col)
        if ftype is None:
            continue
        info = {"key": col.name, "type": ftype, "label": col.name.replace("_", " ").title()}
        if ftype == "enum" and isinstance(col.type, SAEnum):
            info["options"] = list(col.type.enums)
        out.append(info)
    return out


def _coerce(val):
    if isinstance(val, _enum.Enum):
        return val.value
    if isinstance(val, datetime):
        return val.date()
    return val


def _as_date(s: str):
    try:
        return date.fromisoformat(s.strip()[:10])
    except (ValueError, AttributeError):
        return None


def matches(rule, record) -> bool:
    return match_values(record, rule.field, rule.operator, rule.value)


def match_values(record, field: str, op: str, rv: str) -> bool:
    raw = getattr(record, field, None)

    if op == "overdue":
        v = _coerce(raw)
        return isinstance(v, date) and v < date.today()
    if op == "is_true":
        return bool(raw) is True
    if op == "is_false":
        return bool(raw) is False
    if op == "not_empty":
        return raw not in (None, "", 0)

    val = _coerce(raw)
    if val is None:
        return False

    if op in ("gt", "gte", "lt", "lte"):
        a, b = None, None
        try:
            a, b = float(val), float(rv)
        except (ValueError, TypeError):
            da, db = (val if isinstance(val, date) else _as_date(str(val))), _as_date(rv)
            if da is None or db is None:
                return False
            a, b = da, db
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        if op == "lt":
            return a < b
        return a <= b

    sval = str(val)
    if op == "eq":
        return sval == rv
    if op == "ne":
        return sval != rv
    if op == "contains":
        return rv.lower() in sval.lower()
    return False


def evaluate(record, rules) -> list[dict]:
    """Return [{label, color}] for the rules that match this record, by priority."""
    hits = [r for r in sorted(rules, key=lambda r: r.priority) if r.enabled and matches(r, record)]
    return [{"label": r.label, "color": r.color} for r in hits]
