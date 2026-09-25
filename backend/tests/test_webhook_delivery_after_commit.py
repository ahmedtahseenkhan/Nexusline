"""Webhooks fire after the request commits, and never for work that rolled back.

Delivery used to run inline, holding the request's transaction (and pooled connection)
for up to the HTTP timeout per hook. It is now queued on the session and sent after the
outermost commit — which must survive the import engine's per-row savepoints: a failed
row's events are dropped, the saved rows' events kept, and nothing leaves before commit.
"""
import asyncio
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services import webhooks as w


def _db():
    """The two things webhooks uses from an AsyncSession, over a real sync Session."""
    sync = Session(create_engine("sqlite://"))
    return types.SimpleNamespace(sync_session=sync, info=sync.info)


def _queue(db, name):
    if db.info.get(w._PENDING) is None:
        db.info[w._PENDING] = []
        w._deliver_after_commit(db)
    db.info[w._PENDING].append(w._Queued(db.sync_session.get_nested_transaction(), name))


@pytest.fixture
def delivered(monkeypatch):
    sent: list = []

    async def fake(jobs):
        sent.extend(jobs)

    monkeypatch.setattr(w, "_deliver_jobs", fake)
    return sent


async def test_savepoints_keep_saved_rows_and_drop_failed_ones(delivered):
    db = _db()
    s = db.sync_session
    s.begin()
    _queue(db, "outside")
    with s.begin_nested():
        _queue(db, "row1")
    await asyncio.sleep(0)
    assert delivered == []  # a released savepoint is not a commit
    with pytest.raises(RuntimeError), s.begin_nested():
        _queue(db, "row2")
        with s.begin_nested():
            _queue(db, "row2-inner")
        raise RuntimeError("bad row")
    with s.begin_nested():
        _queue(db, "row3")
    s.commit()
    await asyncio.sleep(0)
    assert delivered == ["outside", "row1", "row3"]


async def test_a_rolled_back_request_sends_nothing(delivered):
    db = _db()
    s = db.sync_session
    s.begin()
    _queue(db, "doomed")
    s.rollback()
    s.begin()
    s.commit()
    await asyncio.sleep(0)
    assert delivered == []
