"""Load what a response schema serialises, and nothing more.

Relationships are mapped ``lazy="selectin"`` so a record arrives ready to serialise, and
``database._cap_eager_depth`` stops that three links out. Within those three links a
list still loaded every link of every linked record: listing risks read each linked
control's tests, assets, vendors and findings, and each of *their* links — two to four
hundred queries for pages that show a linked control's name and reference. Under load
that held a pooled connection per request long enough to exhaust the pool.

``options_for(Risk, RiskRead)`` walks the schema instead. A relationship the schema
reaches (directly, through a nested schema, or through a model property it reads — see
``PROPERTY_READS``) is loaded; every other eagerly mapped relationship on the way is made
lazy. The response is unchanged: the same rows are loaded for everything it shows.

``serialize_all`` serialises inside the session's greenlet, so anything the walk cannot
see — a validator that reads past its own fields, a property missing from
``PROPERTY_READS`` — is lazy-loaded (slower, never wrong) instead of raising
``MissingGreenlet``. Code that reads a row's links *after* validation, outside it, must
name them in ``also``.
"""
from __future__ import annotations

import typing
from collections.abc import Callable, Sequence
from functools import cache
from typing import Any

from pydantic import AliasChoices, BaseModel
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defaultload, joinedload, lazyload, selectinload

# Strategies that load a relationship with its parent: the ones made lazy when nothing
# reads them.
_EAGER = frozenset({"selectin", "joined", "subquery", "immediate"})
# Strategies that mean "never load this" (the endpoint assigns it, or it is a query
# attribute): kept as mapped even when a schema names the relationship.
_NEVER_LOADED = frozenset({"noload", "raise", "raise_on_sql", "dynamic", "write_only"})

#: Relationships a model property reads, by model and property name, as dotted paths
#: from the model. A property a schema serialises is otherwise opaque to the walk; one
#: missing here still works through ``serialize_all``, one lazy load per row.
PROPERTY_READS: dict[str, dict[str, tuple[str, ...]]] = {
    "Risk": {
        # control_assurance.health_of_control: the tests and the open findings.
        "control_health": ("controls.audits", "controls.audit_findings"),
    },
    "Control": {
        "audit_count": ("audits",),
        "last_audit_result": ("audits",),
        "reviewed_audit_count": ("audits",),
        "tested_count": ("audits",),
        "pending_review_count": ("audits",),
        "last_reviewed_result": ("audits",),
        "last_reviewed_date": ("audits",),
        "reliance_note": ("audits", "audit_findings"),
        "maintenance_count": ("maintenances",),
        "last_maintenance_result": ("maintenances",),
    },
    "Asset": {
        "derived_criticality": ("hosted_dependencies.information_asset",),
        "effective_criticality": ("hosted_dependencies.information_asset",),
        "risk_count": ("risks",),
    },
    "Policy": {"acknowledgment_count": ("acknowledgments",)},
    "Vendor": {
        "contract_count": ("contracts",),
        "active_contract_value": ("contracts",),
    },
    "Issue": {
        "due_date_moves": ("due_date_changes",),
        "action_count": ("actions",),
        "open_action_count": ("actions",),
    },
    "Incident": {
        "stage_count": ("stages",),
        "completed_stages": ("stages",),
        "lifecycle_complete": ("stages",),
        "current_stage": ("stages",),
    },
}

# relationship key -> what to load below it
_Tree = dict[str, "_Tree"]


def _schema_in(annotation: Any) -> type[BaseModel] | None:
    """The schema a field validates into: ``X``, ``list[X]``, ``X | None`` ..."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in typing.get_args(annotation):
        found = _schema_in(arg)
        if found is not None:
            return found
    return None


def _attribute_names(name: str, field: Any) -> set[str]:
    """Attributes ``from_attributes`` may read a field from: its name and its aliases."""
    names = {name}
    for alias in (field.alias, field.validation_alias):
        if isinstance(alias, str):
            names.add(alias)
        elif isinstance(alias, AliasChoices):
            names.update(c for c in alias.choices if isinstance(c, str))
    return names


def _merge(into: _Tree, tree: _Tree) -> None:
    for key, sub in tree.items():
        _merge(into.setdefault(key, {}), sub)


def _path(dotted: str) -> _Tree:
    tree: _Tree = {}
    for key in reversed(dotted.split(".")):
        tree = {key: tree}
    return tree


def _property_reads(model: type, name: str) -> tuple[str, ...]:
    for klass in model.__mro__:
        reads = PROPERTY_READS.get(klass.__name__, {}).get(name)
        if reads is not None:
            return reads
    return ()


def _needs(model: type, schema: type[BaseModel], trail: frozenset) -> _Tree:
    """The relationships of ``model`` that serialising it as ``schema`` reads."""
    relationships = inspect(model).relationships
    trail = trail | {(model, schema)}
    tree: _Tree = {}
    for name, field in schema.model_fields.items():
        for attr in _attribute_names(name, field):
            if attr in relationships:
                target = relationships[attr].mapper.class_
                nested = _schema_in(field.annotation)
                below = (
                    _needs(target, nested, trail)
                    if nested is not None and (target, nested) not in trail else {}
                )
                _merge(tree.setdefault(attr, {}), below)
            else:
                for dotted in _property_reads(model, attr):
                    _merge(tree, _path(dotted))
    return tree


def _options(model: type, tree: _Tree) -> list:
    """Load the relationships in ``tree`` (and what they need), lazy-load the others."""
    options = []
    for rel in inspect(model).relationships:
        attr = getattr(model, rel.key)
        if rel.key in tree:
            below = _options(rel.mapper.class_, tree[rel.key])
            if rel.lazy == "joined":
                loader = joinedload(attr)
            elif rel.lazy in _NEVER_LOADED:
                loader = defaultload(attr)
            else:
                loader = selectinload(attr)
            options.append(loader.options(*below) if below else loader)
        elif rel.lazy in _EAGER:
            options.append(lazyload(attr))
    return options


@cache
def options_for(model: type, schema: type[BaseModel] | None, also: tuple[str, ...] = ()) -> tuple:
    """Loader options for a query of ``model`` rows that will be serialised as ``schema``.

    ``also`` names further relationships, as dotted paths from ``model``, that the
    endpoint reads itself (outside ``serialize_all``), e.g. ``("controls.audit_findings",)``.
    With no ``schema`` only those are loaded — for code that reads rows by hand.
    """
    tree = _needs(model, schema, frozenset()) if schema is not None else {}
    for dotted in also:
        _merge(tree, _path(dotted))
    return tuple(_options(model, tree))


async def serialize_all(
    db: AsyncSession, rows: Sequence[Any], serialize: Callable[[Any], Any]
) -> list:
    """``[serialize(row) for row in rows]``, run where a relationship the loader options
    left unloaded can still be lazy-loaded (``AsyncSession.run_sync``)."""
    if not rows:
        return []
    return await db.run_sync(lambda _session: [serialize(row) for row in rows])
