"""Risk register repairs: generation by real criticality, links shown on the risk, and
the acceptance request rules.

Pinned here:

* "Generate risks from assets" filters and scores on the asset's *effective*
  criticality (an information asset's business value; an IT asset's own or inherited
  rating), not the raw ``criticality`` column no form sets;
* the risk read lists RCSAs whose lines assess it (one entry per RCSA), quantifications
  and continuity plans that point at it;
* one pending acceptance request per risk, no expiry in the past, and a request that
  lapsed before its decision cannot be approved.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import risk_scenarios as gen_api
from app.api.v1 import risks as risks_api
from app.models.enums import AcceptanceStatus, AssetClass, Criticality as C, RiskStatus
from app.schemas.risk import RiskAcceptanceCreate, RiskAcceptanceDecision
from app.schemas.risk_scenario import GenerateRequest


# ------------------------------------------------------------ generation criticality
def _asset(effective, name="Asset"):
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, asset_class=AssetClass.information_asset,
        criticality=C.medium, effective_criticality=effective, business_value=effective,
        confidentiality=C.medium, integrity=C.medium, availability=C.medium,
        media_type=None, tags=[],
    )


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _AssetDB:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, stmt):
        return _Scalars(self.rows)


async def test_min_criticality_filters_on_effective_criticality():
    crit, low = _asset(C.critical, "Customer data"), _asset(C.low, "Canteen menu")
    rows = await gen_api._select_assets(_AssetDB([crit, low]), GenerateRequest(min_criticality="high"))
    assert rows == [crit]
    rows = await gen_api._select_assets(_AssetDB([crit, low]), GenerateRequest(min_criticality="medium"))
    assert rows == [crit]  # the raw column says medium for both; the effective rating decides


def test_scoring_facts_carry_the_effective_criticality():
    assert gen_api._facts(_asset(C.critical)).criticality == C.critical


# ------------------------------------------------------------------ linked records
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _LinkDB:
    def __init__(self, *answers):
        self.answers = list(answers)

    async def execute(self, stmt):
        return _Rows(self.answers.pop(0))


async def test_linked_records_group_rcsa_lines_by_assessment():
    rcsa, quant, plan = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = _LinkDB(
        [(rcsa, "RCSA-007", "Cards Q3", "Skimming"), (rcsa, "RCSA-007", "Cards Q3", "Chargebacks")],
        [(quant, "FAIR-005", "Card fraud loss")],
        [(plan, "BCP-005", "Card switch outage")],
    )
    rcsas, quants, plans = await risks_api._linked_records(db, uuid.uuid4())
    assert [(r.id, r.reference, r.title) for r in rcsas] == [(rcsa, "RCSA-007", "Cards Q3 — Skimming, Chargebacks")]
    assert [(q.reference, q.title) for q in quants] == [("FAIR-005", "Card fraud loss")]
    assert [(p.reference, p.name) for p in plans] == [("BCP-005", "Card switch outage")]


# ------------------------------------------------------------------ acceptance rules
def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="cro@bank.pk")


def _risk():
    return SimpleNamespace(
        id=uuid.uuid4(), reference="R-310", status=RiskStatus.assessed,
        last_assessed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        assessment_rationale="Scored at the RCSA", annual_loss_expectancy=None, treatment_strategy=None,
    )


class _AcceptDB:
    def __init__(self, scalar=None):
        self._scalar = scalar
        self.added: list = []

    async def scalar(self, stmt):
        return self._scalar

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.fixture
def risk(monkeypatch):
    r = _risk()

    async def load(db, risk_id):
        return r

    async def record(db, **kw):
        return None

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api.audit, "record", record)
    return r


async def test_a_second_pending_request_is_refused(risk):
    db = _AcceptDB(scalar=uuid.uuid4())  # a pending request exists
    with pytest.raises(HTTPException) as exc:
        await risks_api.request_acceptance(risk.id, RiskAcceptanceCreate(rationale="Low exposure"), db, _user())
    assert exc.value.status_code == 409 and db.added == []


async def test_an_expiry_in_the_past_is_refused(risk):
    body = RiskAcceptanceCreate(rationale="Low exposure", expires_at=date.today() - timedelta(days=1))
    with pytest.raises(HTTPException) as exc:
        await risks_api.request_acceptance(risk.id, body, _AcceptDB(), _user())
    assert exc.value.status_code == 422


async def test_a_request_that_lapsed_before_its_decision_cannot_be_approved(risk, monkeypatch):
    acceptance = SimpleNamespace(
        id=uuid.uuid4(), risk_id=risk.id, requested_by=uuid.uuid4(), status=AcceptanceStatus.pending,
        expires_at=date.today() - timedelta(days=2), approver_id=None, decided_at=None,
    )

    async def maker_checker(*_a, **_k):
        return None

    monkeypatch.setattr(risks_api.dual_control, "enforce_maker_checker", maker_checker)
    with pytest.raises(HTTPException) as exc:
        await risks_api.decide_acceptance(
            risk.id, acceptance.id, RiskAcceptanceDecision(approve=True), _AcceptDB(scalar=acceptance), _user(),
        )
    assert exc.value.status_code == 409
    assert acceptance.status == AcceptanceStatus.pending and risk.status == RiskStatus.assessed
