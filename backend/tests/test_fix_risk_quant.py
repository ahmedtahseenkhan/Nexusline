"""Risk quantification: impossible ranges are refused and results never go stale.

Client report: a quantification with TEF min 5 / most likely 1 / max 0.5 was saved and
simulated, and after an input edit the list, the summary total and the top five kept
the old run's mean ALE and P90.

Pinned here:

* min <= most likely <= max (and nothing negative) for TEF and loss magnitude, on
  create (schema), on a partial edit (the resulting state) and before a simulation;
* an edit that changes an input clears the cached run and moves the record back to
  draft; approving needs a run of the current inputs; the summary counts current runs only.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import risk_quant as api
from app.models.risk_quant import QuantStatus
from app.schemas.risk_quant import RiskQuantCreate, RiskQuantUpdate, range_problem

GOOD = dict(tef_min=0.1, tef_likely=0.5, tef_max=2.0, lm_min=1e5, lm_likely=1e6, lm_max=2e7)


# ------------------------------------------------------------------ range rules
@pytest.mark.parametrize("bad", [
    dict(tef_min=5, tef_likely=1, tef_max=0.5),
    dict(tef_min=1, tef_likely=3, tef_max=2),
    dict(lm_min=10, lm_likely=5, lm_max=20),
    dict(lm_min=-1, lm_likely=5, lm_max=20),
])
def test_impossible_ranges_are_named(bad):
    assert range_problem({**GOOD, **bad})
    with pytest.raises(ValidationError):
        RiskQuantCreate(title="x", **{**GOOD, **bad})


def test_a_sound_or_single_point_range_passes():
    assert range_problem(GOOD) is None
    assert range_problem(dict(GOOD, tef_min=1, tef_likely=1, tef_max=1)) is None
    assert range_problem({}) is None  # all zero: nothing estimated yet
    RiskQuantCreate(title="x", **GOOD)


def test_iterations_must_be_positive():
    with pytest.raises(ValidationError):
        RiskQuantCreate(title="x", iterations=0, **GOOD)
    with pytest.raises(ValidationError):
        RiskQuantUpdate(iterations=-5)


# ------------------------------------------------------------------ edits and status
def _record(**kw):
    base = dict(
        id=uuid.uuid4(), reference="FAIR-001", title="Ransomware", currency="PKR", iterations=5000,
        tef_min=Decimal("0.1"), tef_likely=Decimal("0.5"), tef_max=Decimal("2.0"),
        lm_min=Decimal("100000.00"), lm_likely=Decimal("1000000.00"), lm_max=Decimal("20000000.00"),
        last_mean_ale=Decimal("1982949.16"), last_p90=Decimal("4100000.00"),
        last_simulated=date(2026, 9, 20), status=QuantStatus.simulated, risk_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _DB:
    async def flush(self):
        return None


@pytest.fixture
def record(monkeypatch):
    state = {"obj": _record()}

    async def load(db, qid):
        return state["obj"]

    monkeypatch.setattr(api, "_load", load)
    monkeypatch.setattr(api.RiskQuantRead, "model_validate", classmethod(lambda cls, o: o))
    return state


async def test_an_input_edit_clears_the_cached_run(record):
    out = await api.update_quantification(uuid.uuid4(), RiskQuantUpdate(tef_likely=1.0), _DB())
    assert (out.last_mean_ale, out.last_p90, out.last_simulated) == (0, 0, None)
    assert out.status == QuantStatus.draft


async def test_a_resent_unchanged_input_keeps_the_run(record):
    # The edit form sends every field; Decimal 0.5 and float 0.5 are the same input.
    out = await api.update_quantification(
        uuid.uuid4(), RiskQuantUpdate(title="Renamed", tef_likely=0.5, currency="PKR", status="simulated"), _DB(),
    )
    assert out.last_simulated == date(2026, 9, 20) and out.status == QuantStatus.simulated


async def test_approving_is_not_an_edit(record):
    # Approved is the sign-off the approval lifecycle gives (lifecycle_gates.QUANT_STATUS):
    # an edit can't write it, with or without a current run.
    for body in (RiskQuantUpdate(lm_max=3e7, status="approved"), RiskQuantUpdate(status="approved")):
        with pytest.raises(HTTPException) as exc:
            await api.update_quantification(uuid.uuid4(), body, _DB())
        assert exc.value.status_code == 422 and "not by editing its status" in exc.value.detail
    assert record["obj"].status != QuantStatus.approved


async def test_a_partial_edit_is_checked_on_the_resulting_range(record):
    with pytest.raises(HTTPException) as exc:
        await api.update_quantification(uuid.uuid4(), RiskQuantUpdate(lm_max=1000), _DB())
    assert exc.value.status_code == 422 and "Loss magnitude" in exc.value.detail
    assert record["obj"].last_simulated is not None  # nothing was written


async def test_simulate_refuses_a_stored_impossible_range(record):
    record["obj"] = _record(tef_min=Decimal(5), tef_likely=Decimal(1), tef_max=Decimal("0.5"))
    with pytest.raises(HTTPException) as exc:
        await api.simulate(uuid.uuid4(), _DB(), SimpleNamespace(id=uuid.uuid4()))
    assert exc.value.status_code == 422


def test_status_rules():
    assert api._status_for(QuantStatus.simulated, has_result=False) == QuantStatus.draft
    assert api._status_for(QuantStatus.simulated, has_result=True) == QuantStatus.simulated
    with pytest.raises(HTTPException):
        api._status_for(QuantStatus.approved, has_result=False)


# ------------------------------------------------------------------ summary
class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


async def test_summary_counts_current_runs_only(monkeypatch):
    fresh = _record(title="Fresh", last_mean_ale=Decimal(500))
    stale = _record(title="Edited", last_mean_ale=Decimal(0), last_p90=Decimal(0), last_simulated=None)

    class DB:
        async def scalars(self, stmt):
            return _Scalars([fresh, stale])

    async def book(db):
        return api.fx.RateBook("PKR")

    monkeypatch.setattr(api.fx, "load_rate_book", book)
    out = await api.quant_summary(DB())
    assert out.total_mean_ale == 500 and out.count_simulated == 1 and out.count_quantified == 2
    assert [t.title for t in out.top] == ["Fresh"]
