"""Attestation is a four-eyes act on a live, non-draft record (D-06), with one review
clock per record (D-05b).

No database: the independence/state rule is a pure function, the record lookup is a
table-name resolution over the model registry, and the maker-checker leg reuses the
fake-session pattern from ``test_dual_control``.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import attestations as att
from app.core.config import settings
from app.models.base import WorkflowState
from app.services import dual_control, entity_types
from app.services.notifications import NATIVE_REVIEW_ENTITY_TYPES

ME = uuid.uuid4()
OTHER = uuid.uuid4()


# -------------------------------------------------------- independence ---
def test_the_owner_attests_their_own_record():
    """Decision 9: the owner is the expected signer — independence comes from the
    approval (decision 6) and the second signature, not from barring the owner."""
    assert att.attest_refusal(attester_id=ME, owner_id=ME, workflow_status=WorkflowState.approved) is None


def test_someone_else_can_attest_an_approved_record():
    assert att.attest_refusal(attester_id=ME, owner_id=OTHER, workflow_status=WorkflowState.approved) is None


def test_an_attestation_by_anyone_but_the_owner_stands_in_for_the_owner():
    assert att.on_behalf_of(ME, OTHER) == OTHER
    assert att.on_behalf_of(ME, ME) is None
    assert att.on_behalf_of(ME, None) is None


def test_a_record_with_no_owner_fk_is_judged_on_state_alone():
    assert att.attest_refusal(attester_id=ME, owner_id=None, workflow_status=WorkflowState.in_review) is None


# ----------------------------------------------------------------- state ---
def test_a_draft_cannot_be_attested():
    """The D-06 case: a draft risk certified by its creator minutes after writing it."""
    assert att.attest_refusal(attester_id=ME, owner_id=OTHER, workflow_status=WorkflowState.draft) == (
        409, att.DRAFT_REFUSAL,
    )


def test_draft_is_recognised_as_a_plain_string_and_other_enums():
    """Asset uses its own WorkflowStatus enum; both spell the value "draft"."""
    assert att.attest_refusal(attester_id=ME, owner_id=None, workflow_status="draft")[0] == 409
    assert att.attest_refusal(attester_id=ME, owner_id=None, workflow_status=None) is None


def test_a_draft_is_refused_to_the_owner_too():
    """Decision 9 removed the owner refusal, not the draft one: a record still being
    written certifies nothing, whoever signs it."""
    assert att.attest_refusal(attester_id=ME, owner_id=ME, workflow_status=WorkflowState.draft) == (
        409, att.DRAFT_REFUSAL,
    )


# ---------------------------------------------------------- second signature ---
def test_the_attester_cannot_confirm_their_own_attestation():
    assert att.confirm_refusal(confirmer_id=ME, attester_id=ME, already_confirmed=False)[0] == 403


def test_a_second_person_can_confirm_once():
    assert att.confirm_refusal(confirmer_id=OTHER, attester_id=ME, already_confirmed=False) is None
    assert att.confirm_refusal(confirmer_id=OTHER, attester_id=ME, already_confirmed=True)[0] == 409


# ------------------------------------------------------------- maker-checker ---
class FakeDB:
    """Answers dual_control's two lookups: the maker from the audit trail, and the
    (absent) dual-control rule, so the global switch decides."""

    def __init__(self, maker):
        self.maker = maker

    async def scalar(self, stmt, *args, **kwargs):
        return self.maker if "audit_log" in str(stmt) else None

    async def get(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_the_maker_of_a_record_cannot_attest_it(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    with pytest.raises(HTTPException) as exc:
        await dual_control.enforce_record_maker_checker(
            FakeDB(maker=ME), module="risk", action="attest", entity_type="risk",
            entity_id=uuid.uuid4(), checker_id=ME, subject="risk",
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_an_independent_checker_may_attest(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    await dual_control.enforce_record_maker_checker(
        FakeDB(maker=OTHER), module="risk", action="attest", entity_type="risk",
        entity_id=uuid.uuid4(), checker_id=ME, subject="risk",
    )


# ----------------------------------------------------------- record lookup ---
def test_every_registered_entity_type_resolves_to_a_model():
    """attest() must be able to load any record the panel can be mounted on."""
    missing = [et for et in entity_types.ENTITY_TYPES if att.model_for(et) is None]
    assert missing == []


@pytest.mark.parametrize("et,table", [
    ("risk", "risks"), ("policy", "policies"), ("vendor", "vendors"), ("process", "processes"),
    ("evidence", "evidence"), ("scenario_analysis", "scenario_analyses"),
    ("processing_activity", "processing_activities"), ("authority_matrix", "authority_matrix"),
    ("data_breach", "data_breaches"), ("committee_meeting", "committee_meetings"),
])
def test_entity_types_resolve_to_the_right_table(et, table):
    assert att.model_for(et).__tablename__ == table


def test_owner_is_only_a_user_foreign_key():
    """Risk.owner_id is a user; Asset.owner_id is a business unit and must not count."""
    from app.models.asset import Asset
    from app.models.risk import Risk

    risk = Risk()
    risk.owner_id = ME
    assert att.owner_user_id(risk) == ME
    asset = Asset()
    asset.owner_id = ME
    assert att.owner_user_id(asset) is None
    assert att.owner_user_id(SimpleNamespace(owner_id=ME)) is None


# --------------------------------------------------------- statements & clock ---
def test_default_statements():
    assert att.default_statement("risk") == "I confirm this risk assessment is current and complete."
    assert att.default_statement("control") == "I confirm this control is designed and operating as described."
    assert att.default_statement("policy") == "I confirm this policy is current and has been reviewed."
    assert att.default_statement("loss_event") == "I confirm this loss event is current and complete."


def test_native_review_types_carry_their_own_schedule():
    from app.models.asset import Asset
    from app.models.policy import Policy
    from app.models.risk import Risk
    from app.models.vendor import Vendor

    by_type = {"risk": Risk, "policy": Policy, "vendor": Vendor, "asset": Asset}
    # One review clock per record: the attestation is the record's review for these
    # (spec B4 added the asset), and each has its own overdue sweep on that date.
    assert set(by_type) == att.REVIEW_CLOCK_ENTITY_TYPES
    assert att.REVIEW_CLOCK_ENTITY_TYPES == NATIVE_REVIEW_ENTITY_TYPES
    for et, model in by_type.items():
        record = model()
        assert att._native(et, record), et
        assert hasattr(record, "review_frequency") and hasattr(record, "next_review_date")
    assert not att._native("control", SimpleNamespace(review_frequency=None, next_review_date=None))
    assert not att._native("risk", None)


class _Rec:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_a_record_s_own_status_decides_whether_it_is_a_draft():
    from app.models.enums import RiskStatus

    # The reviewer's case: a risk still in Draft can't be attested...
    assert att.lifecycle_state(_Rec(status=RiskStatus.draft, workflow_status=WorkflowState.approved)) == RiskStatus.draft
    # ...an assessed risk passes the draft rule; its approval is judged separately
    # (decision 6, ``approval_state``), which an unmapped stand-in doesn't have.
    rec = _Rec(status=RiskStatus.assessed, workflow_status=WorkflowState.draft)
    state = att.lifecycle_state(rec)
    assert att.attest_refusal(attester_id=ME, owner_id=OTHER, workflow_status=state) is None
    assert att.approval_state(rec) is None


def test_records_without_a_business_status_fall_back_to_the_workflow_field():
    assert att.lifecycle_state(_Rec(workflow_status=WorkflowState.draft)) == WorkflowState.draft
