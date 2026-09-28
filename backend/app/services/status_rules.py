"""Dynamic status rule engine — introspect evaluable fields per model and evaluate
admin-defined rules against records to produce colored labels."""
from __future__ import annotations

import enum as _enum
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum

from app.models.aml import AmlRiskAssessment, ScreeningCase, SuspiciousActivityReport
from app.models.asset import Asset
from app.models.compliance import Requirement
from app.models.enums import Criticality
from app.models.continuity import ContinuityPlan
from app.models.evidence import Evidence
from app.models.control import Control
from app.models.exception import ExceptionRecord
from app.models.fraud import FraudCase, FraudRisk
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
    "evidence": Evidence,
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
    # Financial crime: valid entity types and custom-field models, so their registers can
    # carry status labels too.
    "aml_risk_assessment": AmlRiskAssessment,
    "suspicious_activity_report": SuspiciousActivityReport,
    "screening_case": ScreeningCase,
    "fraud_risk": FraudRisk,
    "fraud_case": FraudCase,
}

OPERATORS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "overdue", "is_true", "is_false", "not_empty"]

#: Operators that ignore the rule's ``value``: a verdict reports an empty value for them,
#: so a stale value left on the rule never shows up in the condition it explains.
VALUELESS_OPERATORS: frozenset[str] = frozenset({"overdue", "is_true", "is_false", "not_empty"})

_SKIP = {"id", "tenant_id", "created_at", "updated_at"}

#: Computed values a rule may test beside the table's own columns — the figure the
#: register shows rather than a stored input. An asset's stored ``criticality`` is set by
#: no form, so a rule on it never agreed with the "Effective criticality" column; the
#: shipped "Critical Asset" label tests this instead. Same shape as a column entry.
EXTRA_FIELDS: dict[str, list[dict]] = {
    "asset": [
        {
            "key": "effective_criticality", "type": "enum", "label": "Effective Criticality",
            "options": [c.value for c in Criticality],
        },
    ],
}


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
    out.extend(dict(f) for f in EXTRA_FIELDS.get(model, []))
    return out


def load_options(cls: type, rules) -> tuple:
    """Loader options for reading ``cls`` rows only to evaluate ``rules``: every eagerly
    mapped relationship left unloaded except what a computed field a rule tests reads
    (``schema_loading.PROPERTY_READS``). Evaluating a page of assets otherwise loaded all
    twenty-eight of each asset's relationships — seconds per list page at bank scale."""
    from app.core.schema_loading import PROPERTY_READS, options_for

    reads: set[str] = set()
    for klass in cls.__mro__:
        table = PROPERTY_READS.get(klass.__name__, {})
        for rule in rules:
            reads.update(table.get(rule.field, ()))
    return options_for(cls, None, tuple(sorted(reads)))


def field_keys(model: str) -> set[str]:
    """The field names a rule or saved filter on ``model`` may test."""
    return {f["key"] for f in evaluable_fields(model)}


def condition_problem(model: str, field: str | None, operator: str | None) -> str | None:
    """Why a condition can't be evaluated on ``model``, or None. Pure apart from the
    model's columns. A condition on a field the model doesn't have never matches, so
    accepting it would save a rule or filter that silently does nothing."""
    if model not in MODEL_MAP:
        return f"Unsupported model '{model}'"
    if operator not in OPERATORS:
        return f"Unsupported operator '{operator}'"
    if field not in field_keys(model):
        return f"'{field}' is not a field of {model}. Choose one of GET /status-rules/fields/{model}."
    return None


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


def verdict(rule) -> dict:
    """What a matching rule tells the reader: its label and colour, plus the condition
    that fired it — ``field``, ``operator`` and ``value`` exactly as the rule stores them
    ("inherent_score", "gte", "15"), so the page can say "inherent score ≥ 15"."""
    return {
        "label": rule.label,
        "color": rule.color,
        "field": rule.field,
        "operator": rule.operator,
        "value": "" if rule.operator in VALUELESS_OPERATORS else (rule.value or ""),
    }


def evaluate(record, rules) -> list[dict]:
    """Return [{label, color, field, operator, value}] for the rules that match this
    record, by priority."""
    hits = [r for r in sorted(rules, key=lambda r: r.priority) if r.enabled and matches(r, record)]
    return [verdict(r) for r in hits]
