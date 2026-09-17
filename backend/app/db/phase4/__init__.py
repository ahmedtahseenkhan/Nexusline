"""Phase 4 schema patches, one module per workstream.

Each module exposes ``TABLES`` (new tables created from metadata) and ``ddl_statements()``
(idempotent ALTERs on existing tables). ``all_ddl_statements`` / ``all_tables`` collect them
for boot (``init_db``) and migration ``0034``.
"""
from __future__ import annotations

import importlib

STREAMS = ("loose_ends", "workspaces", "crosswalks", "ccm", "questionnaires")


def _modules():
    for name in STREAMS:
        try:
            yield importlib.import_module(f"app.db.phase4.{name}")
        except ModuleNotFoundError as exc:  # a stream with no schema changes has no module
            if exc.name != f"app.db.phase4.{name}":
                raise


def all_ddl_statements() -> list[str]:
    return [s for m in _modules() for s in getattr(m, "ddl_statements", lambda: [])()]


def all_tables() -> list[str]:
    return [t for m in _modules() for t in getattr(m, "TABLES", ())]
