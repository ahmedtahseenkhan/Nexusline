"""Resolve a polymorphic ``entity_type`` string to its ORM class, and describe a record.

The shared panels (attestations, archive/restore, impact, the record lifecycle) all
address a record by ``(entity_type, entity_id)``. This module answers the two questions
they share:

* **Which mapped class is behind this type?** — :func:`model_for`, by table name, since
  the table is almost always the plural of the type (``risk`` → ``risks``,
  ``policy`` → ``policies``). The few that aren't are listed in ``_TABLE_OVERRIDES``.
* **How do I name this record to a person?** — :func:`reference_of`, :func:`title_of`
  and :func:`label_of` ("R-012 Ransomware on core banking").

The reverse direction — which entity type a class is — is :func:`entity_type_for_model`,
used to name the linked record types in an impact report.
"""
from __future__ import annotations

import re
from typing import Any

__all__ = [
    "entity_type_for_model",
    "has_soft_delete",
    "has_workflow",
    "humanize",
    "label_of",
    "link_for",
    "model_for",
    "reference_of",
    "title_of",
    "type_label",
]

#: Entity types whose table name isn't the plain plural of the type.
_TABLE_OVERRIDES: dict[str, str] = {
    "evidence": "evidence",
    "authority_matrix": "authority_matrix",
    "model_inventory": "model_inventory",
    "committee_meeting": "committee_meetings",
}

#: Attributes that name a record, in the order tried.
TITLE_ATTRIBUTES: tuple[str, ...] = (
    "title",
    "name",
    "subject",
    "activity",
    "process_name",
    "subject_name",
    "entity_name",
    "declarant_name",
    "full_name",
    "summary",
    "validation_type",
)


def _candidate_tables(entity_type: str) -> list[str]:
    if entity_type in _TABLE_OVERRIDES:
        return [_TABLE_OVERRIDES[entity_type]]
    out = [f"{entity_type}s", f"{entity_type}es"]
    if entity_type.endswith("y"):
        out.insert(0, f"{entity_type[:-1]}ies")
    if entity_type.endswith("is"):
        out.insert(0, f"{entity_type[:-2]}es")
    out.append(entity_type)
    return out


_MODELS_BY_TABLE: dict[str, type] | None = None
_TYPES_BY_MODEL: dict[type, str] | None = None


def _models_by_table() -> dict[str, type]:
    global _MODELS_BY_TABLE
    if _MODELS_BY_TABLE is None:
        import app.models  # noqa: F401 - populate the registry
        from app.models.base import Base

        _MODELS_BY_TABLE = {
            m.class_.__tablename__: m.class_
            for m in Base.registry.mappers
            if getattr(m.class_, "__tablename__", None)
        }
    return _MODELS_BY_TABLE


def model_for(entity_type: str) -> type | None:
    """The mapped class behind a registered entity type, or None if it has no table."""
    tables = _models_by_table()
    for table in _candidate_tables(entity_type):
        found = tables.get(table)
        if found is not None:
            return found
    return None


def entity_type_for_model(model: type | None) -> str | None:
    """The registered entity type whose table is this class's, or None."""
    global _TYPES_BY_MODEL
    if model is None:
        return None
    if _TYPES_BY_MODEL is None:
        from app.services.entity_types import ENTITY_TYPES

        out: dict[type, str] = {}
        for key in ENTITY_TYPES:
            cls = model_for(key)
            if cls is not None:
                out.setdefault(cls, key)
        _TYPES_BY_MODEL = out
    return _TYPES_BY_MODEL.get(model)


def _columns(model: type) -> Any:
    table = getattr(model, "__table__", None)
    return getattr(table, "c", None)


def has_soft_delete(model: type | None) -> bool:
    """True when the table carries the ``deleted`` / ``deleted_date`` envelope."""
    cols = _columns(model) if model is not None else None
    return cols is not None and "deleted" in cols and "deleted_date" in cols


def has_workflow(model: type | None) -> bool:
    """True when the table carries the approval lifecycle column ``workflow_status``."""
    cols = _columns(model) if model is not None else None
    return cols is not None and "workflow_status" in cols


#: Words shown in capitals when a class or table name is turned into a label.
_ACRONYMS: frozenset[str] = frozenset(
    {"aml", "bcp", "bia", "ccm", "dpia", "dsar", "esg", "icfr", "it", "kri", "rcsa", "ropa", "sar"}
)


def humanize(name: str) -> str:
    """``RiskAcceptance`` / ``risk_acceptances`` → ``Risk acceptance``; ``RcsaRisk`` → ``RCSA risk``."""
    if not name:
        return ""
    if "_" in name or name.islower():
        words = name.replace("_", " ").strip()
        if words.endswith("ies"):
            words = words[:-3] + "y"
        elif words.endswith("ses"):
            words = words[:-2]
        elif words.endswith("s") and not words.endswith("ss"):
            words = words[:-1]
    else:
        words = re.sub(r"(?<!^)(?=[A-Z])", " ", name)
    tokens = [t.upper() if t in _ACRONYMS else t for t in words.strip().lower().split()]
    text = " ".join(tokens)
    return text[:1].upper() + text[1:]


def type_label(entity_type: str, model: type | None = None) -> str:
    """A person's name for a record type: the registry label, else the class name."""
    from app.services.entity_types import ENTITY_TYPES

    spec = ENTITY_TYPES.get(entity_type)
    if spec is not None:
        return spec.label
    if model is not None:
        return humanize(model.__name__)
    return humanize(entity_type)


def reference_of(record: Any) -> str:
    return str(getattr(record, "reference", "") or "")


def title_of(record: Any) -> str:
    for attr in TITLE_ATTRIBUTES:
        value = getattr(record, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def label_of(record: Any) -> str:
    """"R-012 Ransomware on core banking" — reference and title, whichever exist."""
    parts = [p for p in (reference_of(record), title_of(record)) if p]
    if parts:
        return " ".join(parts)
    rid = getattr(record, "id", None)
    return str(rid)[:8] if rid else ""


def link_for(record: Any) -> str:
    """The frontend deep link that opens this record in its register, or ``""``.

    Borrowed from global search's target list so there is one map of register paths;
    assets split into the IT and information registers by class, as search does.
    """
    from app.api.v1.search import _TARGETS
    from app.models.asset import Asset

    rid = getattr(record, "id", None)
    for target in _TARGETS:
        if isinstance(record, target.model):
            base = target.link
            if target.model is Asset:
                kind = getattr(getattr(record, "asset_class", None), "value", None)
                base = "/it-assets" if kind == "it_asset" else "/information-assets"
            return f"{base}?id={rid}" if rid else base
    return ""
