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


# ------------------------------------------------- maker of an existing record ---
class FakeRecordDB:
    """AsyncSession stand-in for maker_of: .scalar() answers the audit-trail lookup (and
    find_rule), .get() loads the record."""

    def __init__(self, audit_maker=None, record=None):
        self.audit_maker = audit_maker
        self.record = record
        self.got = []

    async def scalar(self, *args, **kwargs):
        return self.audit_maker

    async def get(self, model, entity_id):
        self.got.append((model, entity_id))
        return self.record


def _risk(owner_id):
    from app.models.risk import Risk

    r = Risk()
    r.id = uuid.uuid4()
    r.owner_id = owner_id
    return r


def test_maker_from_record_uses_user_owner():
    # Risk.owner_id is a foreign key to users: the owner is the maker.
    assert dual_control.maker_from_record(_risk(MAKER)) == MAKER


def test_maker_from_record_ignores_non_user_owner():
    # Asset.owner_id names a business unit, not a person.
    from app.models.asset import Asset

    a = Asset()
    a.owner_id = uuid.uuid4()
    assert dual_control.maker_from_record(a) is None


def test_maker_from_record_prefers_created_by_over_owner():
    class Plain:
        created_by = MAKER
        owner_id = OTHER

    assert dual_control.maker_from_record(Plain()) == MAKER


def test_maker_from_record_ignores_non_uuid_values():
    class Plain:
        created_by = "Jane Doe"  # a name, not a user
        owner_id = None

    assert dual_control.maker_from_record(Plain()) is None
    assert dual_control.maker_from_record(None) is None


@pytest.mark.asyncio
async def test_maker_of_prefers_audit_trail():
    record = _risk(OTHER)
    db = FakeRecordDB(audit_maker=MAKER, record=record)
    assert await dual_control.maker_of(db, "risk", record.id) == MAKER
    assert db.got == []  # never needed the record


@pytest.mark.asyncio
async def test_maker_of_falls_back_to_record_owner_when_no_trail():
    # Seeded / imported records have no create audit entry.
    record = _risk(MAKER)
    db = FakeRecordDB(audit_maker=None, record=record)
    assert await dual_control.maker_of(db, "risk", record.id) == MAKER
    assert db.got and db.got[0][1] == record.id


@pytest.mark.asyncio
async def test_maker_of_uses_record_passed_in():
    record = _risk(MAKER)
    db = FakeRecordDB(audit_maker=None, record=None)
    assert await dual_control.maker_of(db, "risk", record.id, record=record) == MAKER
    assert db.got == []


@pytest.mark.asyncio
async def test_maker_of_none_for_models_without_a_user_reference():
    # Vendors carry no user reference at all: nothing to fall back to, and no query made.
    # (Controls used to be the example; since phase 1 they carry owner_id, so the control
    # owner is now the maker of last resort.)
    db = FakeRecordDB(audit_maker=None, record=None)
    assert await dual_control.maker_of(db, "vendor", uuid.uuid4()) is None
    assert db.got == []


@pytest.mark.asyncio
async def test_record_owner_cannot_be_own_checker_without_audit_trail(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    record = _risk(MAKER)
    db = FakeRecordDB(audit_maker=None, record=record)
    with pytest.raises(HTTPException) as exc:
        await dual_control.enforce_record_maker_checker(
            db, module="risk", action="attest", entity_type="risk", entity_id=record.id,
            checker_id=MAKER, subject="risk attestation",
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_independent_checker_passes_on_seeded_record(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    record = _risk(MAKER)
    db = FakeRecordDB(audit_maker=None, record=record)
    assert await dual_control.enforce_record_maker_checker(
        db, module="risk", action="attest", entity_type="risk", entity_id=record.id,
        checker_id=OTHER,
    ) is None


def test_entity_types_resolve_to_models():
    from app.models.aml import SuspiciousActivityReport
    from app.models.authority import AuthorityMatrix
    from app.models.policy import Policy
    from app.models.risk import Risk

    assert dual_control.model_for_entity_type("risk") is Risk
    assert dual_control.model_for_entity_type("policy") is Policy
    assert dual_control.model_for_entity_type("sar") is SuspiciousActivityReport
    assert dual_control.model_for_entity_type("authority_matrix") is AuthorityMatrix
    assert dual_control.model_for_entity_type("no_such_thing") is None
