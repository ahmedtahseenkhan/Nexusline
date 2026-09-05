"""Lapsing risk acceptances whose approval has run out.

The defect this covers is a silent one: ``RiskAcceptance.expires_at`` was stored from
the day the feature shipped and nothing ever read it, so a risk accepted "until 31 Dec
2024" was still reported as accepted years later. The rules pinned here are the ones a
bank examiner would ask about.

No DB required — a fake async session returns canned rows, exactly like
``test_dual_control``.
"""
import uuid
from datetime import date, timedelta

import pytest

from app.models.enums import AcceptanceStatus, RiskStatus, TreatmentStrategy
from app.models.risk import Risk, RiskAcceptance
from app.services import risk_acceptance

TODAY = date(2026, 9, 4)
TENANT = uuid.uuid4()


def make_acceptance(*, status=AcceptanceStatus.approved, expires_at=None, risk_id=None):
    a = RiskAcceptance()
    a.id = uuid.uuid4()
    a.risk_id = risk_id or uuid.uuid4()
    a.status = status
    a.expires_at = expires_at
    return a


def make_risk(*, status=RiskStatus.accepted, strategy=TreatmentStrategy.accept, deleted=False):
    r = Risk()
    r.id = uuid.uuid4()
    r.reference = "R-001"
    r.title = "Credentials compromised on internet banking"
    r.status = status
    r.treatment_strategy = strategy
    r.deleted = deleted
    return r


class FakeDB:
    """Stands in for AsyncSession: canned acceptance list, risks by id, records adds."""

    def __init__(self, acceptances, risks=None):
        self._acceptances = acceptances
        self._risks = {r.id: r for r in (risks or [])}
        self.added = []
        self.flushed = 0

    async def scalars(self, *_args, **_kwargs):
        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        return _Result(self._acceptances)

    async def get(self, _model, ident):
        return self._risks.get(ident)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


@pytest.fixture(autouse=True)
def _no_audit_io(monkeypatch):
    """The audit helper fans out to webhooks, which a fake session cannot serve."""
    calls = []

    async def _record(_db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(risk_acceptance.audit, "record_system", _record)
    return calls


# ------------------------------------------------------------- the predicates ---
def test_an_acceptance_is_still_in_force_on_its_expiry_date():
    """"Valid until 31 December" means the 31st is covered. Off-by-one here would
    un-accept a risk a day early and put a false alarm in front of the board."""
    a = make_acceptance(expires_at=TODAY)
    assert risk_acceptance.is_lapsed(a, TODAY) is False
    assert risk_acceptance.is_lapsed(a, TODAY + timedelta(days=1)) is True


def test_an_open_ended_acceptance_never_lapses():
    assert risk_acceptance.is_lapsed(make_acceptance(expires_at=None), TODAY) is False


@pytest.mark.parametrize(
    "status", [AcceptanceStatus.pending, AcceptanceStatus.rejected, AcceptanceStatus.expired]
)
def test_only_an_approved_acceptance_can_lapse(status):
    """A pending request that sailed past its proposed expiry is a stale request, not a
    lapsed approval — nothing was ever accepted, so nothing is un-accepted."""
    a = make_acceptance(status=status, expires_at=TODAY - timedelta(days=10))
    assert risk_acceptance.is_lapsed(a, TODAY) is False


def test_the_warning_window_covers_today_up_to_the_expiry():
    inside = make_acceptance(expires_at=TODAY + timedelta(days=risk_acceptance.EXPIRY_WARNING_DAYS))
    outside = make_acceptance(
        expires_at=TODAY + timedelta(days=risk_acceptance.EXPIRY_WARNING_DAYS + 1)
    )
    already_lapsed = make_acceptance(expires_at=TODAY - timedelta(days=1))
    window = risk_acceptance.EXPIRY_WARNING_DAYS
    assert risk_acceptance.expires_within(inside, TODAY, window) is True
    assert risk_acceptance.expires_within(outside, TODAY, window) is False
    # Already gone: the lapse event covers it, so it must not also chase.
    assert risk_acceptance.expires_within(already_lapsed, TODAY, window) is False


# ------------------------------------------------------------------ the sweep ---
@pytest.mark.asyncio
async def test_nothing_lapsed_changes_nothing():
    db = FakeDB([])
    result = await risk_acceptance.expire_lapsed(db, TENANT, TODAY)
    assert (result.expired, result.reopened) == (0, 0)
    assert db.added == []


@pytest.mark.asyncio
async def test_a_lapsed_acceptance_returns_its_risk_to_the_register():
    risk = make_risk()
    acceptance = make_acceptance(expires_at=TODAY - timedelta(days=1), risk_id=risk.id)
    db = FakeDB([acceptance], [risk])

    result = await risk_acceptance.expire_lapsed(db, TENANT, TODAY)

    assert acceptance.status is AcceptanceStatus.expired
    assert risk.status is RiskStatus.assessed
    # Leaving "accept" would report a strategy the bank no longer has approval for.
    assert risk.treatment_strategy is None
    assert (result.expired, result.reopened) == (1, 1)
    assert result.references == ["R-001"]


@pytest.mark.asyncio
async def test_the_lapse_is_recorded_as_an_event_not_a_resolvable_alert(_no_audit_io):
    """The alert reconciler deletes conditions it can no longer re-derive. A lapse
    happened on a date and can never become false, so it has to carry EVENT_PREFIX or
    nobody would ever see it."""
    from app.models.notification import EVENT_PREFIX

    risk = make_risk()
    acceptance = make_acceptance(expires_at=TODAY - timedelta(days=1), risk_id=risk.id)
    db = FakeDB([acceptance], [risk])

    await risk_acceptance.expire_lapsed(db, TENANT, TODAY)

    notifications = [n for n in db.added if getattr(n, "dedup_key", "")]
    assert len(notifications) == 1
    assert notifications[0].dedup_key.startswith(EVENT_PREFIX)
    assert notifications[0].entity_id == risk.id
    assert _no_audit_io and _no_audit_io[0]["action"] == "expire_acceptance"


@pytest.mark.asyncio
async def test_a_risk_already_moved_on_is_left_alone():
    """Someone re-opened this risk and started treating it before the acceptance ran
    out. The lapse must not drag it back to 'assessed' and wipe their strategy."""
    risk = make_risk(status=RiskStatus.treatment_in_progress, strategy=TreatmentStrategy.mitigate)
    acceptance = make_acceptance(expires_at=TODAY - timedelta(days=1), risk_id=risk.id)
    db = FakeDB([acceptance], [risk])

    result = await risk_acceptance.expire_lapsed(db, TENANT, TODAY)

    assert acceptance.status is AcceptanceStatus.expired  # the record still lapses
    assert risk.status is RiskStatus.treatment_in_progress
    assert risk.treatment_strategy is TreatmentStrategy.mitigate
    assert (result.expired, result.reopened) == (1, 0)


@pytest.mark.asyncio
async def test_a_closed_risk_is_not_reopened():
    risk = make_risk(status=RiskStatus.closed, strategy=None)
    acceptance = make_acceptance(expires_at=TODAY - timedelta(days=1), risk_id=risk.id)
    db = FakeDB([acceptance], [risk])

    result = await risk_acceptance.expire_lapsed(db, TENANT, TODAY)

    assert risk.status is RiskStatus.closed
    assert (result.expired, result.reopened) == (1, 0)


@pytest.mark.asyncio
async def test_a_soft_deleted_risk_lapses_quietly():
    """The acceptance record still has to stop claiming to be in force, but there is no
    live risk to re-open and nothing to tell anyone about."""
    risk = make_risk(deleted=True)
    acceptance = make_acceptance(expires_at=TODAY - timedelta(days=1), risk_id=risk.id)
    db = FakeDB([acceptance], [risk])

    result = await risk_acceptance.expire_lapsed(db, TENANT, TODAY)

    assert acceptance.status is AcceptanceStatus.expired
    assert (result.expired, result.reopened) == (1, 0)
    assert db.added == []


@pytest.mark.asyncio
async def test_several_lapses_are_all_processed():
    risks = [make_risk() for _ in range(3)]
    acceptances = [
        make_acceptance(expires_at=TODAY - timedelta(days=n + 1), risk_id=r.id)
        for n, r in enumerate(risks)
    ]
    db = FakeDB(acceptances, risks)

    result = await risk_acceptance.expire_lapsed(db, TENANT, TODAY)

    assert (result.expired, result.reopened) == (3, 3)
    assert all(r.status is RiskStatus.assessed for r in risks)
