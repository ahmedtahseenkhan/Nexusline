"""A worker started to replace one that died does not re-run the start-up DDL.

On a small server the kernel killed an API worker; uvicorn replaced it, the new worker
found the start-up lock free, re-ran the schema DDL against live traffic, deadlocked,
and uvicorn stopped the whole API (every page a 502).
"""
import asyncio

from app.db import init_db


def test_a_server_that_has_initialised_is_not_initialised_again(tmp_path, monkeypatch):
    monkeypatch.setattr(init_db, "_MARKER_DIR", tmp_path)
    monkeypatch.setattr(init_db, "_parent_identity", lambda: "4242-1000")
    assert not init_db.already_initialised()
    init_db.mark_initialised()
    assert init_db.already_initialised()

    async def enter():
        async with init_db.startup_lock() as initialise:
            return initialise

    # No database is touched: the marker answers before the advisory lock is taken.
    monkeypatch.setattr(init_db, "wait_for_db", None)
    assert asyncio.run(enter()) is False


def test_the_marker_belongs_to_this_server_process(tmp_path, monkeypatch):
    """A restarted container may reuse the pid; its start time differs."""
    monkeypatch.setattr(init_db, "_MARKER_DIR", tmp_path)
    monkeypatch.setattr(init_db, "_parent_identity", lambda: "17-1000")
    init_db.mark_initialised()
    monkeypatch.setattr(init_db, "_parent_identity", lambda: "17-2000")
    assert not init_db.already_initialised()


def test_a_single_process_server_keeps_no_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(init_db, "_MARKER_DIR", tmp_path)
    monkeypatch.setattr(init_db, "_parent_identity", lambda: None)
    init_db.mark_initialised()
    assert not init_db.already_initialised() and not list(tmp_path.iterdir())
