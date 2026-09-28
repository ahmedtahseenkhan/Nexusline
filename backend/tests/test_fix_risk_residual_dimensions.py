"""Residual sign-off keeps the residual impact and its dimension scores in step.

Client report: after "Accept suggested residual" the risk recorded 4x5 while its
residual dimension scores still derived 3, so the detail showed residual 5 beside
dimensions of 3 and every later save of the edit form was refused with "Residual impact
5 disagrees with its dimension scores".

Pinned here:

* accept-residual removes the residual dimension rows when the impact it records is not
  the one they derive (the control-effectiveness sign-off is now the basis), and says so
  in the audit trail; rows that still agree, and inherent rows, stay;
* ``POST /risks/{id}/assess`` refuses a residual impact its dimension scores do not
  derive, as the edit form does.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import risks as risks_api
from app.models.enums import RiskStatus
from app.schemas.risk import ResidualAcceptance, RiskAssessment
from app.services.residual_engine import ResidualPolicySpec
from app.services.risk_scoring import SeverityScale


class _DB:
    def __init__(self):
        self.deleted: list = []

    async def delete(self, row):
        self.deleted.append(row)

    async def flush(self):
        return None


def _user():
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="cro@bank.pk",
        permission_codes=["risk:read", "risk:write"],
    )


def _dim(basis, score):
    return SimpleNamespace(id=uuid.uuid4(), dimension_id=uuid.uuid4(), basis=basis, score=score)


def _risk(**kw):
    base = dict(
        id=uuid.uuid4(), reference="R-310", title="Card fraud", category_id=None,
        inherent_likelihood=4, inherent_impact=5, inherent_score=20,
        residual_likelihood=3, residual_impact=3, residual_score=9,
        target_likelihood=None, target_impact=None,
        status=RiskStatus.assessed, assessment_rationale="Scored at the RCSA",
        last_assessed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        residual_override_reason="", needs_review=False, review_reason="", controls=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def audit_log(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(risks_api.audit, "record", record)
    return calls


@pytest.fixture
def stub(monkeypatch):
    state: dict = {"dims": []}

    async def load(db, risk_id):
        return state["risk"]

    async def read(db, risk_id, user):
        return state["risk"]

    async def size(db, tenant_id):
        return 5

    async def nothing(*_a, **_k):
        return None

    async def review_policy(db, user):
        return SeverityScale(), {}

    async def stored(db, risk_id):
        return list(state["dims"])

    async def settings(db, tenant_id):
        return SimpleNamespace(impact_mode="max")

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api, "_read", read)
    monkeypatch.setattr(risks_api, "get_matrix_size", size)
    monkeypatch.setattr(risks_api, "_review_policy", review_policy)
    monkeypatch.setattr(risks_api, "_refresh_alerts", nothing)
    monkeypatch.setattr(risks_api, "get_or_create_residual_policy", nothing)
    monkeypatch.setattr(risks_api, "policy_spec", lambda p: ResidualPolicySpec())
    monkeypatch.setattr(risks_api, "_stored_dimensions", stored)
    monkeypatch.setattr(risks_api, "get_or_create_settings", settings)
    return state


async def test_accepting_the_suggestion_clears_residual_dimensions_it_contradicts(stub, audit_log):
    inherent, residual = _dim("inherent", 5), _dim("residual", 3)
    stub["dims"] = [inherent, residual]
    stub["risk"] = _risk()  # no controls: the suggestion is the inherent 4x5
    db = _DB()
    await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(), db, _user())
    assert (stub["risk"].residual_likelihood, stub["risk"].residual_impact) == (4, 5)
    assert db.deleted == [residual]  # the inherent dimension score is untouched
    assert audit_log[0]["changes"]["residual_dimensions_cleared"] == f"{residual.dimension_id}=3"


async def test_residual_dimensions_that_still_agree_are_kept(stub, audit_log):
    stub["dims"] = [_dim("inherent", 5), _dim("residual", 5)]
    stub["risk"] = _risk()
    db = _DB()
    await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(), db, _user())
    assert db.deleted == []
    assert "residual_dimensions_cleared" not in audit_log[0]["changes"]


async def test_an_override_also_releases_the_contradicting_dimensions(stub, audit_log):
    residual = _dim("residual", 2)
    stub["dims"] = [residual]
    stub["risk"] = _risk()
    db = _DB()
    await risks_api.accept_residual(
        stub["risk"].id, ResidualAcceptance(likelihood=3, impact=4, override_reason="Dual control live"),
        db, _user(),
    )
    assert stub["risk"].residual_impact == 4
    assert db.deleted == [residual]


async def test_assess_refuses_an_impact_the_residual_dimensions_do_not_derive(stub, audit_log):
    stub["dims"] = [_dim("residual", 3)]
    stub["risk"] = _risk()
    with pytest.raises(HTTPException) as exc:
        await risks_api.assess_risk(
            stub["risk"].id,
            RiskAssessment(residual_likelihood=2, residual_impact=4, assessment_rationale="re-scored"),
            _DB(), _user(),
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == risks_api.DIMENSION_DERIVED_DETAIL.format(basis="residual")
    assert stub["risk"].residual_impact == 3 and audit_log == []


async def test_assess_accepts_the_derived_impact(stub, audit_log):
    stub["dims"] = [_dim("residual", 3)]
    stub["risk"] = _risk()
    await risks_api.assess_risk(
        stub["risk"].id,
        RiskAssessment(residual_likelihood=2, residual_impact=3, assessment_rationale="re-scored"),
        _DB(), _user(),
    )
    assert (stub["risk"].residual_likelihood, stub["risk"].residual_impact) == (2, 3)
