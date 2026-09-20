"""What else depends on a record — the "this risk is linked to 12 controls…" report.

Deleting (archiving) a record is only safe when the person doing it can see what hangs
off it. Rather than hand-write that list per module, it is discovered from the schema:

* **Relationships on the mapper** — many-to-many through an association table (including
  the ``viewonly`` reverse links that most registers declare) and one-to-many children.
  Many-to-one pointers are skipped: a risk pointing *at* a business unit does not make
  the unit depend on the risk.
* **Foreign keys in other tables** that point at this record's table and have no
  relationship declared on this side. A column that merely *holds* an id without a
  foreign key (``Issue.source_id``) is deliberately ignored: it cannot be followed
  reliably and the database does not guarantee it.

Each path becomes one ``COUNT`` of the *live* rows at its far end (targets with
``deleted = true`` are excluded), and all paths are sent as scalar subqueries of a
single ``SELECT``, so an impact report is one round-trip however many links a record
type has. Paths are computed once per class and cached.

Counts are summed per related type: two different association tables from a risk to
controls would count a control twice if it were linked both ways, which the schema does
not do in practice and which errs on the side of warning more.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import Table, func, inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapper
from sqlalchemy.orm.interfaces import MANYTOMANY, ONETOMANY
from sqlalchemy.sql.schema import Column

from app.services import record_registry

__all__ = [
    "ImpactPath",
    "foreign_key_paths",
    "impact",
    "impact_paths",
    "relationship_paths",
]

#: Tables that are plumbing rather than records, never reported as linked.
IGNORED_TABLES: frozenset[str] = frozenset({"tenants"})


@dataclass(frozen=True)
class ImpactPath:
    """One way a row elsewhere can depend on a record of the source table.

    ``link_table.local_column`` holds the source record's id. For a plain child table
    the rows counted are ``link_table`` itself (``remote_column`` is None); for an
    association table they are the rows of ``target_table`` reached through
    ``remote_column``.
    """

    name: str
    link_table: Table
    local_column: Column
    target_table: Table
    remote_column: Column | None = None

    @property
    def key(self) -> tuple[str, str, str | None]:
        return (
            self.link_table.name,
            self.local_column.name,
            self.remote_column.name if self.remote_column is not None else None,
        )

    @property
    def target_has_soft_delete(self) -> bool:
        return "deleted" in self.target_table.c


def _points_at(column: Column, table: Table) -> bool:
    return any(fk.column.table is table for fk in column.foreign_keys)


def _mapped_tables() -> dict[str, type]:
    from app.models.base import Base

    out: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        table = getattr(mapper, "local_table", None)
        if isinstance(table, Table):
            out.setdefault(table.name, mapper.class_)
    return out


def relationship_paths(mapper: Mapper) -> list[ImpactPath]:
    """Dependent-record paths declared as relationships on ``mapper``.

    Only links backed by a real foreign key to the source table are returned; a
    relationship joined on an un-keyed column is skipped.
    """
    source: Table = mapper.local_table
    out: list[ImpactPath] = []
    for rel in mapper.relationships:
        if rel.direction is MANYTOMANY and rel.secondary is not None:
            secondary = rel.secondary
            if not isinstance(secondary, Table) or secondary.name in IGNORED_TABLES:
                continue
            local = [c for _, c in rel.synchronize_pairs if c.table is secondary]
            remote = [c for _, c in rel.secondary_synchronize_pairs if c.table is secondary]
            if not local or not remote or not _points_at(local[0], source):
                continue
            target = rel.mapper.local_table
            if not _points_at(remote[0], target):
                continue
            out.append(
                ImpactPath(
                    name=rel.key, link_table=secondary, local_column=local[0],
                    target_table=target, remote_column=remote[0],
                )
            )
        elif rel.direction is ONETOMANY:
            target = rel.mapper.local_table
            if not isinstance(target, Table) or target.name in IGNORED_TABLES:
                continue
            local = [r for _, r in rel.local_remote_pairs if r.table is target]
            if not local or not _points_at(local[0], source):
                continue
            out.append(
                ImpactPath(
                    name=rel.key, link_table=target, local_column=local[0], target_table=target,
                )
            )
    return out


def foreign_key_paths(
    table: Table, tables: dict[str, Table] | Any, mapped: set[str] | None = None
) -> list[ImpactPath]:
    """Every foreign key elsewhere in ``tables`` that points at ``table``.

    ``mapped`` names the tables that are mapped classes (their rows are records and are
    counted directly); any other table holding the key is treated as an association
    table, and the rows counted are those at the far end of its other foreign keys.
    """
    mapped = mapped if mapped is not None else set(_mapped_tables())
    out: list[ImpactPath] = []
    for other in tables.values():
        if other.name in IGNORED_TABLES:
            continue
        for fk in other.foreign_keys:
            if fk.column.table is not table:
                continue
            local = fk.parent
            if other.name in mapped:
                out.append(
                    ImpactPath(
                        name=f"{other.name}.{local.name}", link_table=other,
                        local_column=local, target_table=other,
                    )
                )
                continue
            remotes = [
                f for f in other.foreign_keys
                if f.parent is not local and f.column.table.name not in IGNORED_TABLES
            ]
            if not remotes:
                out.append(
                    ImpactPath(
                        name=f"{other.name}.{local.name}", link_table=other,
                        local_column=local, target_table=other,
                    )
                )
                continue
            for remote in remotes:
                out.append(
                    ImpactPath(
                        name=f"{other.name}.{local.name}", link_table=other,
                        local_column=local, target_table=remote.column.table,
                        remote_column=remote.parent,
                    )
                )
    return out


@lru_cache(maxsize=None)
def impact_paths(model: type) -> tuple[ImpactPath, ...]:
    """Relationship paths first (they carry the declared names), then every foreign key
    no relationship already covers. Cached per class."""
    from app.models.base import Base

    mapper = sa_inspect(model)
    seen: set[tuple] = set()
    out: list[ImpactPath] = []
    mapped = set(_mapped_tables())
    for path in (
        *relationship_paths(mapper),
        *foreign_key_paths(mapper.local_table, Base.metadata.tables, mapped),
    ):
        if path.key in seen:
            continue
        seen.add(path.key)
        out.append(path)
    return tuple(out)


def _count(path: ImpactPath, record_id: Any):
    """``COUNT`` of live rows at the far end of one path, as a scalar subquery."""
    link = path.link_table
    stmt = select(func.count()).where(path.local_column == record_id)
    if path.remote_column is None:
        stmt = stmt.select_from(link)
        if path.target_has_soft_delete:
            stmt = stmt.where(link.c.deleted.is_(False))
        return stmt.scalar_subquery()
    if path.target_has_soft_delete:
        target = path.target_table
        target_pk = next(
            fk.column for fk in path.remote_column.foreign_keys if fk.column.table is target
        )
        stmt = stmt.select_from(link.join(target, path.remote_column == target_pk)).where(
            target.c.deleted.is_(False)
        )
    else:
        stmt = stmt.select_from(link)
    return stmt.scalar_subquery()


def path_type(path: ImpactPath) -> tuple[str, str]:
    """``(type key, human label)`` for the rows a path counts."""
    cls = _mapped_tables().get(path.target_table.name)
    entity_type = record_registry.entity_type_for_model(cls)
    if entity_type:
        return entity_type, record_registry.type_label(entity_type, cls)
    if cls is not None:
        return path.target_table.name, record_registry.humanize(cls.__name__)
    return path.target_table.name, record_registry.humanize(path.target_table.name)


def group_counts(paths: tuple[ImpactPath, ...] | list[ImpactPath], counts: list[int]) -> list[dict]:
    """Sum counts per related type, drop zeros, largest first. Pure."""
    by_type: dict[str, dict] = {}
    for path, count in zip(paths, counts):
        if not count:
            continue
        key, label = path_type(path)
        entry = by_type.setdefault(key, {"type": key, "label": label, "count": 0})
        entry["count"] += int(count)
    return sorted(by_type.values(), key=lambda e: (-e["count"], e["label"]))


async def impact(db: AsyncSession, model: type, record_id: Any) -> list[dict]:
    """Live linked rows by related type: ``[{type, label, count}]``. One query."""
    paths = impact_paths(model)
    if not paths:
        return []
    row = (
        await db.execute(select(*[_count(p, record_id).label(f"p{i}") for i, p in enumerate(paths)]))
    ).one()
    return group_counts(paths, list(row))
