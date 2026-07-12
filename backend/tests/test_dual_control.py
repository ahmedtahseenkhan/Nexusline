"""Unit tests for runtime maker-checker (four-eyes) enforcement.

No DB required — a fake async session returns a canned DualControlRule (or None) so we
can exercise every branch of the resolution logic and the SoD invariant."""
import uuid

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.authority import DualControlRule, DualControlStatus
from app.services import dual_control


class FakeDB:
    """Stands in for AsyncSession; find_rule only ever calls .scalar()."""

    def __init__(self, rule=None):
        self.rule = rule

    async def scalar(self, *args, **kwargs):
        return self.rule


def make_rule(**kw) -> DualControlRule:
    r = DualControlRule()
    r.enabled = kw.get("enabled", True)
    r.status = kw.get("status", DualControlStatus.active)
    r.requires_dual_control = kw.get("requires_dual_control", True)
    r.threshold_amount = kw.get("threshold_amount", None)
    return r


MAKER = uuid.uuid4()
OTHER = uuid.uuid4()


async def _enforce(db, maker, checker, **kw):
    return await dual_control.enforce_maker_checker(
        db, module="risk", action="accept", maker_id=maker, checker_id=checker, **kw
    )


# --------------------------------------------------------- no explicit rule ---
@pytest.mark.asyncio
async def test_no_rule_sod_on_blocks_self_approval(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    with pytest.raises(HTTPException) as exc:
        await _enforce(FakeDB(None), MAKER, MAKER, subject="risk acceptance")
    assert exc.value.status_code == 403
    assert "Segregation of duties" in exc.value.detail


@pytest.mark.asyncio
async def test_no_rule_sod_on_allows_independent_checker(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    # Different maker/checker → no exception.
    assert await _enforce(FakeDB(None), MAKER, OTHER) is None


@pytest.mark.asyncio
async def test_no_rule_sod_off_allows_self_approval(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", False)
    # SoD disabled globally and no rule → maker may self-approve.
    assert await _enforce(FakeDB(None), MAKER, MAKER) is None


# ------------------------------------------------------------ explicit rule ---
@pytest.mark.asyncio
async def test_rule_disabling_dual_control_allows_self(monkeypatch):
    # Explicit config wins over the global switch: rule says no dual control.
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    db = FakeDB(make_rule(requires_dual_control=False))
    assert await _enforce(db, MAKER, MAKER) is not None  # returns the rule, no raise


@pytest.mark.asyncio
async def test_rule_threshold_below_does_not_trigger(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    db = FakeDB(make_rule(threshold_amount=1_000_000))
    # Amount under the threshold → control does not kick in even for self-approval.
    assert await _enforce(db, MAKER, MAKER, amount=500_000) is not None


@pytest.mark.asyncio
async def test_rule_threshold_met_blocks_self(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    db = FakeDB(make_rule(threshold_amount=100_000))
    with pytest.raises(HTTPException) as exc:
        await _enforce(db, MAKER, MAKER, amount=500_000)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_inactive_rule_falls_back_to_global(monkeypatch):
    # A disabled rule shouldn't trigger on its own; the global switch still governs.
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    db = FakeDB(make_rule(enabled=False))
    with pytest.raises(HTTPException):
        await _enforce(db, MAKER, MAKER)


@pytest.mark.asyncio
async def test_dual_control_required_reports_rule(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    rule = make_rule(threshold_amount=100_000)
    required, got = await dual_control.dual_control_required(
        FakeDB(rule), "risk", "accept", amount=200_000
    )
    assert required is True and got is rule
