"""Retention purge (§1.4): only records archived longer than the tenant's window are
hard-deleted, never a live row and never a row with no archive date."""
from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - populate mappers
from app.models.risk import Risk
from app.services import record_registry, scheduler

NOW = datetime(2026, 9, 12, 2, 0, tzinfo=timezone.utc)


def test_the_cutoff_is_the_window_before_now():
    assert scheduler.retention_cutoff(NOW, 90) == NOW - timedelta(days=90)
    assert scheduler.retention_cutoff(NOW, 30) == NOW - timedelta(days=30)


def test_no_setting_means_the_default_window():
    assert scheduler.DEFAULT_RETENTION_DAYS == 90
    assert scheduler.retention_cutoff(NOW, None) == NOW - timedelta(days=90)


def test_a_zero_or_negative_window_never_purges_on_archive():
    assert scheduler.retention_cutoff(NOW, 0) == NOW - timedelta(days=1)
    assert scheduler.retention_cutoff(NOW, -5) == NOW - timedelta(days=1)


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}))


def test_candidates_are_archived_dated_and_older_than_the_cutoff():
    sql = _sql(scheduler.purge_candidates(Risk, NOW, uuid.uuid4()))
    assert "risks.deleted IS true" in sql
    assert "risks.deleted_date IS NOT NULL" in sql
    assert "risks.deleted_date <" in sql
    assert "risks.tenant_id =" in sql
    assert "LIMIT" in sql


def test_candidate_selection_on_sample_rows():
    """The same rule as the statement, applied to rows: live rows, undated archives and
    recent archives all stay."""
    cutoff = scheduler.retention_cutoff(NOW, 90)

    def due(deleted, deleted_date):
        return deleted and deleted_date is not None and deleted_date < cutoff

    assert due(True, NOW - timedelta(days=91))
    assert not due(True, NOW - timedelta(days=89))
    assert not due(True, None)
    assert not due(False, NOW - timedelta(days=400))


def test_the_core_registers_are_covered_and_soft_deletable():
    assert set(scheduler.RETENTION_ENTITY_TYPES) == {
        "risk", "control", "asset", "issue", "policy", "incident", "vendor",
    }
    for entity_type in scheduler.RETENTION_ENTITY_TYPES:
        model = record_registry.model_for(entity_type)
        assert model is not None and record_registry.has_soft_delete(model), entity_type


def test_each_row_is_deleted_in_its_own_savepoint_and_fk_failures_are_skipped():
    source = inspect.getsource(scheduler.purge_archived)
    assert "begin_nested()" in source
    assert "except IntegrityError" in source
    assert "record_system(" in source  # one summary per register, attributed to the platform


def test_the_sweep_runs_the_purge_in_its_own_transaction():
    source = inspect.getsource(scheduler.run_sweep)
    assert "purge_archived(" in source
    assert source.index("purge_archived(") < source.index("risk_acceptance.expire_lapsed(")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False  # let the error reach the caller, as a real SAVEPOINT rollback does


class _FakeDb:
    """Serves one register's due rows; deleting ``blocked`` ids fails on a foreign key."""

    def __init__(self, days, rows, blocked=()):
        self.days, self.rows, self.blocked = days, rows, set(blocked)
        self.deleted: list = []

    async def scalar(self, stmt):
        return self.days

    async def scalars(self, stmt):
        entity = stmt.column_descriptions[0]["entity"]
        return _Rows(self.rows if entity is Risk else [])

    def expunge(self, obj):
        pass

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt):
        from sqlalchemy.exc import IntegrityError

        row_id = stmt.whereclause.right.value
        if row_id in self.blocked:
            raise IntegrityError("DELETE", {}, Exception("still referenced"))
        self.deleted.append(row_id)


async def test_purge_deletes_due_rows_skips_referenced_ones_and_audits_once(monkeypatch):
    from app.services import audit

    entries = []

    async def _record_system(db, **kw):
        entries.append(kw)

    monkeypatch.setattr(audit, "record_system", _record_system)
    ok = Risk(id=uuid.uuid4(), reference="R-001", title="Old", deleted=True)
    stuck = Risk(id=uuid.uuid4(), reference="R-002", title="Referenced", deleted=True)
    db = _FakeDb(30, [ok, stuck], blocked=[stuck.id])

    tenant = uuid.uuid4()
    result = await scheduler.purge_archived(db, tenant, now=NOW)

    assert result == {"risk": 1}
    assert db.deleted == [ok.id]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["entity_type"] == "risk" and entry["action"] == "purge"
    assert entry["tenant_id"] == tenant
    assert entry["changes"]["retention_days"] == 30
    assert entry["changes"]["purged_records"] == ["R-001 Old"]
    assert entry["changes"]["kept_records"] == ["R-002 Referenced"]


async def test_purge_with_no_settings_row_uses_the_default_window(monkeypatch):
    from app.services import audit

    entries = []

    async def _record_system(db, **kw):
        entries.append(kw)

    monkeypatch.setattr(audit, "record_system", _record_system)
    db = _FakeDb(None, [Risk(id=uuid.uuid4(), title="Old", deleted=True)])
    await scheduler.purge_archived(db, uuid.uuid4(), now=NOW)
    assert entries[0]["changes"]["retention_days"] == 90
    assert entries[0]["changes"]["cutoff"] == (NOW - timedelta(days=90)).isoformat()


async def test_nothing_due_writes_no_audit(monkeypatch):
    from app.services import audit

    entries = []

    async def _record_system(db, **kw):
        entries.append(kw)

    monkeypatch.setattr(audit, "record_system", _record_system)
    assert await scheduler.purge_archived(_FakeDb(90, []), uuid.uuid4(), now=NOW) == {}
    assert entries == []
