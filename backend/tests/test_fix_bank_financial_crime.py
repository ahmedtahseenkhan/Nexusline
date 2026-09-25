"""Bank-module fixes of 25 Sep 2026 — financial crime and Shariah four-eyes.

* STR/SAR filing is four-eyes on *every* path to ``filed``: create, update with or
  without a ``filed_date`` key, and whatever the edit form sends; the filing date is
  stamped by the transition and never typed onto an unfiled report or wiped.
* A purification (charity) entry cannot be created already approved or disbursed.
* STR/SAR history is written under the record type ``suspicious_activity_report``; the
  maker lookup still reads entries written under the legacy ``sar``.

No DB: the dual-control rule lookup and the maker lookup are replaced with fakes.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import aml, shariah
from app.core.config import settings
from app.models.enums import CharityStatus, SarStatus
from app.schemas.shariah import CharityCreate
from app.services import dual_control

MAKER = uuid.uuid4()
CHECKER = uuid.uuid4()
BACKEND = Path(__file__).resolve().parents[1]


def _user(uid):
    return SimpleNamespace(id=uid, tenant_id=uuid.uuid4(), email="u@bank.pk")


def _sar(status=SarStatus.draft, filed_date=None):
    return SimpleNamespace(id=uuid.uuid4(), status=status, filed_date=filed_date)


@pytest.fixture
def four_eyes(monkeypatch):
    """SoD on, no explicit rule; the SAR's preparer is MAKER (under ``by_type``)."""
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)

    async def no_rule(db, module, action):
        return None

    by_type = {aml.SAR_ENTITY: MAKER}

    async def maker_of(db, entity_type, entity_id, record=None):
        return by_type.get(entity_type)

    monkeypatch.setattr(dual_control, "find_rule", no_rule)
    monkeypatch.setattr(dual_control, "maker_of", maker_of)
    return by_type


# ================================================================== STR / SAR ===
@pytest.mark.asyncio
async def test_a_sar_cannot_be_created_as_filed(four_eyes):
    data = {"status": SarStatus.filed, "filed_date": None}
    with pytest.raises(HTTPException) as exc:
        await aml._apply_sar_filing(None, data, _user(MAKER))
    assert exc.value.status_code == 403
    assert "cannot be filed by the person who prepared it" in exc.value.detail


@pytest.mark.asyncio
async def test_with_dual_control_off_a_created_filed_sar_is_stamped(four_eyes, monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", False)
    data = {"status": SarStatus.filed, "filed_date": None}
    await aml._apply_sar_filing(None, data, _user(MAKER))
    assert data["filed_date"] == date.today()


@pytest.mark.asyncio
async def test_the_edit_form_sending_filed_date_null_does_not_bypass_four_eyes(four_eyes):
    # The bug: the form always sends filed_date: null, and the check only ran when the
    # key was absent — the maker filed their own report.
    data = {"status": SarStatus.filed, "filed_date": None, "subject": "X"}
    with pytest.raises(HTTPException) as exc:
        await aml._apply_sar_filing(None, data, _user(MAKER), _sar())
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_a_typed_filing_date_does_not_bypass_four_eyes(four_eyes):
    data = {"status": SarStatus.filed, "filed_date": date.today() - timedelta(days=1)}
    with pytest.raises(HTTPException):
        await aml._apply_sar_filing(None, data, _user(MAKER), _sar())


@pytest.mark.asyncio
async def test_an_independent_checker_files_and_the_date_is_stamped(four_eyes):
    data = {"status": SarStatus.filed, "filed_date": None}
    await aml._apply_sar_filing(None, data, _user(CHECKER), _sar(SarStatus.under_review))
    assert data["filed_date"] == date.today()


@pytest.mark.asyncio
async def test_the_checker_may_record_an_earlier_submission_date(four_eyes):
    earlier = date.today() - timedelta(days=2)
    data = {"status": SarStatus.filed, "filed_date": earlier}
    await aml._apply_sar_filing(None, data, _user(CHECKER), _sar())
    assert data["filed_date"] == earlier


@pytest.mark.asyncio
async def test_a_future_filing_date_is_refused(four_eyes):
    data = {"status": SarStatus.filed, "filed_date": date.today() + timedelta(days=1)}
    with pytest.raises(HTTPException) as exc:
        await aml._apply_sar_filing(None, data, _user(CHECKER), _sar())
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_filing_date_on_an_unfiled_report_is_refused(four_eyes):
    # Otherwise a maker could make a draft *look* filed without the checker.
    data = {"status": SarStatus.draft, "filed_date": date.today()}
    with pytest.raises(HTTPException) as exc:
        await aml._apply_sar_filing(None, data, _user(MAKER), _sar())
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException):
        await aml._apply_sar_filing(None, {"filed_date": date.today()}, _user(MAKER))


@pytest.mark.asyncio
async def test_editing_a_filed_report_keeps_its_filing_date_and_skips_the_check(four_eyes):
    sar = _sar(SarStatus.filed, date(2026, 9, 1))
    data = {"status": SarStatus.filed, "filed_date": None, "fmu_reference": "FMU-1"}
    await aml._apply_sar_filing(None, data, _user(MAKER), sar)  # the maker may fix the FMU ref
    assert "filed_date" not in data  # a blank never wipes the recorded filing


@pytest.mark.asyncio
async def test_a_filed_report_can_be_closed_but_not_reopened(four_eyes):
    sar = _sar(SarStatus.filed, date(2026, 9, 1))
    await aml._apply_sar_filing(None, {"status": SarStatus.closed}, _user(MAKER), sar)
    for back in (SarStatus.draft, SarStatus.under_review):
        with pytest.raises(HTTPException) as exc:
            await aml._apply_sar_filing(None, {"status": back}, _user(MAKER), sar)
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_blank_status_means_no_change(four_eyes):
    data = {"status": None, "subject": "Y"}
    await aml._apply_sar_filing(None, data, _user(MAKER), _sar())
    assert "status" not in data


@pytest.mark.asyncio
async def test_a_sar_whose_create_entry_is_under_the_legacy_key_is_still_guarded(four_eyes):
    four_eyes.clear()
    four_eyes["sar"] = MAKER  # written before the entity type was aligned
    with pytest.raises(HTTPException):
        await aml._apply_sar_filing(None, {"status": SarStatus.filed}, _user(MAKER), _sar())


def test_sar_history_is_written_under_the_record_type():
    assert aml.SAR_ENTITY == "suspicious_activity_report"
    src = (BACKEND / "app/api/v1/aml.py").read_text()
    assert 'entity_type="sar"' not in src


def test_the_repair_migration_renames_legacy_entries_idempotently():
    src = (BACKEND / "alembic/versions/0038_sar_audit_entity_type.py").read_text()
    assert "SET entity_type = 'suspicious_activity_report' WHERE entity_type = 'sar'" in src


# ============================================================ purification ledger ===
class _NoWrites:
    """The gate must refuse before anything is written."""

    def add(self, *_a, **_k):
        raise AssertionError("wrote a refused entry")

    async def flush(self):
        raise AssertionError("wrote a refused entry")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [CharityStatus.approved, CharityStatus.disbursed])
async def test_a_charity_entry_cannot_be_created_approved_or_disbursed(four_eyes, state):
    body = CharityCreate(description="SNC income Q3", amount=250_000, status=state)
    with pytest.raises(HTTPException) as exc:
        await shariah.create_charity(body, _NoWrites(), _user(MAKER))
    assert exc.value.status_code == 403
    assert "Record it as pending" in exc.value.detail


@pytest.mark.asyncio
async def test_approving_with_a_raised_amount_is_checked_against_the_larger_sum(monkeypatch):
    # An edit in the same request cannot slip a large sum under a threshold rule.
    entry = SimpleNamespace(id=uuid.uuid4(), status=CharityStatus.pending, amount=5_000)
    seen = {}

    async def get(db, model, obj_id, name):
        return entry

    async def gate(db, **kw):
        seen.update(kw)
        raise HTTPException(status_code=403, detail="stop")

    monkeypatch.setattr(shariah, "_get", get)
    monkeypatch.setattr(dual_control, "enforce_record_maker_checker", gate)
    body = shariah.CharityUpdate(status=CharityStatus.approved, amount=900_000)
    with pytest.raises(HTTPException):
        await shariah.update_charity(entry.id, body, _NoWrites(), _user(MAKER))
    assert seen["amount"] == 900_000 and seen["action"] == "charity_approved"
