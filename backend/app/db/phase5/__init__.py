"""Phase 5 schema patches, one module per workstream.

Each module exposes ``TABLES`` (new tables created from metadata) and ``ddl_statements()``
(idempotent ALTERs on existing tables). ``all_ddl_statements`` / ``all_tables`` collect them
for boot (``init_db``) and migration ``0035``.
"""
from __future__ import annotations

import importlib

STREAMS = ("licence_retention", "money_taxonomy", "record_rules")


def _modules():
    for name in STREAMS:
        try:
            yield importlib.import_module(f"app.db.phase5.{name}")
        except ModuleNotFoundError as exc:  # a stream with no schema changes has no module
            if exc.name != f"app.db.phase5.{name}":
                raise


def all_ddl_statements() -> list[str]:
    return [s for m in _modules() for s in getattr(m, "ddl_statements", lambda: [])()]


def all_tables() -> list[str]:
    return [t for m in _modules() for t in getattr(m, "TABLES", ())]
