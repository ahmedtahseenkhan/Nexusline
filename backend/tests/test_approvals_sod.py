"""Segregation of duties on approval requests, and the demo data that shows it.

No DB: the SoD rules are pure functions in ``api/v1/approvals.py``; the demo-tenant
guards are pure helpers in ``db/seed.py``, ``api/v1/platform.py`` and ``api/v1/system.py``.
"""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import approvals
from app.core.config import settings

MAKER = uuid.uuid4()
CHECKER = uuid.uuid4()


# ------------------------------------------------------------------ is_maker ---
def test_maker_matched_by_id():
    assert approvals.is_maker(MAKER, "maker@bank.pk", MAKER, "someone-else@bank.pk")


def test_maker_matched_by_email_when_request_has_no_id():
    # Imported / older seeded requests carry only the maker's address.
    assert approvals.is_maker(None, "Maker@Bank.pk", CHECKER, "maker@bank.pk")


def test_maker_email_match_is_case_and_space_insensitive():
    assert approvals.is_maker(None, "  MAKER@bank.PK ", CHECKER, "maker@bank.pk")


def test_email_match_blocks_even_when_ids_differ():
    # Same person under two ids (re-provisioned account) is still the maker.
    assert approvals.is_maker(MAKER, "maker@bank.pk", CHECKER, "maker@bank.pk")


def test_independent_checker_is_not_maker():
    assert not approvals.is_maker(MAKER, "maker@bank.pk", CHECKER, "checker@bank.pk")


def test_blank_emails_never_match():
    assert not approvals.is_maker(None, "", CHECKER, "")


# ------------------------------------------------------------ enforce_sod ---
def _request(requested_by=None, email=""):
    return SimpleNamespace(requested_by=requested_by, requested_by_email=email)


def test_enforce_sod_blocks_self_approval_by_email(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    with pytest.raises(HTTPException) as exc:
        approvals.enforce_sod(_request(None, "admin@acme.com"), CHECKER, "ADMIN@acme.com")
    assert exc.value.status_code == 403
    assert "Segregation of duties" in exc.value.detail


def test_enforce_sod_blocks_self_approval_by_id(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    with pytest.raises(HTTPException):
        approvals.enforce_sod(_request(MAKER, "maker@bank.pk"), MAKER, "maker@bank.pk")


def test_enforce_sod_allows_independent_checker(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    approvals.enforce_sod(_request(MAKER, "maker@bank.pk"), CHECKER, "checker@bank.pk")


def test_enforce_sod_off_allows_self(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", False)
    approvals.enforce_sod(_request(MAKER, "maker@bank.pk"), MAKER, "maker@bank.pk")


# ------------------------------------------------- require_maker_identity ---
def test_request_with_neither_id_nor_email_is_refused():
    with pytest.raises(HTTPException) as exc:
        approvals.require_maker_identity(None, "  ")
    assert exc.value.status_code == 422


@pytest.mark.parametrize("maker_id,email", [(MAKER, ""), (None, "maker@bank.pk"), (MAKER, "maker@bank.pk")])
def test_request_with_either_identity_is_accepted(maker_id, email):
    approvals.require_maker_identity(maker_id, email)


def test_approval_read_exposes_maker_id():
    from app.schemas.approval import ApprovalRead

    assert "requested_by" in ApprovalRead.model_fields


# ------------------------------------------ demo data that makes SoD visible ---
def test_demo_maker_email_uses_admin_domain():
    from app.db.seed import demo_maker_email

    assert demo_maker_email("admin@acme.com") == "ayesha.siddiqui@acme.com"
    assert demo_maker_email("root@bank.example.pk") == "ayesha.siddiqui@bank.example.pk"


def test_demo_maker_role_exists_and_cannot_approve():
    # The maker must be a real seeded role, and not a checker — otherwise the demo shows
    # two people who can both approve and SoD proves nothing.
    from app.core.permissions import DEFAULT_ROLES
    from app.db.seed import DEMO_MAKER_ROLE

    _, codes = DEFAULT_ROLES[DEMO_MAKER_ROLE]
    assert "workflow:approve" not in codes


def test_default_workflows_cover_policy_and_risk_with_three_stages():
    from app.db.seed import DEFAULT_WORKFLOWS
    from app.models.workflow import ApproverMode

    by_type = {entity_type: stages for entity_type, _, _, stages in DEFAULT_WORKFLOWS}
    assert set(by_type) == {"policy", "risk"}
    for stages in by_type.values():
        assert len(stages) == 3
        for _, mode, _ in stages:
            ApproverMode(mode)  # every mode is a real enum value


def test_default_widgets_titles_come_from_metric_catalogue():
    from app.db.seed import DEFAULT_WIDGETS
    from app.services.metrics import CATALOG

    keys = [key for key, _ in DEFAULT_WIDGETS]
    assert len(keys) == len(set(keys))  # one tile per metric: the unique index holds
    assert all(key in CATALOG for key in keys)
    assert CATALOG["risks_total"][0] == "Total risks"


def test_demo_reset_refused_outside_demo_org():
    from app.api.v1.platform import demo_reset_refusal

    assert demo_reset_refusal("acme", "acme", "acme", ["NL-E2E-TEST"]) is None
    assert demo_reset_refusal("hbl", "hbl", "acme", ["NL-E2E-TEST"])[0] == 403
    assert demo_reset_refusal("acme", "wrong", "acme", ["NL-E2E-TEST"])[0] == 422
    assert demo_reset_refusal("acme", "acme", "", ["NL-E2E-TEST"])[0] == 403
    assert demo_reset_refusal("acme", "acme", "acme", [])[0] == 409


def test_client_install_has_no_demo_org(monkeypatch):
    monkeypatch.setattr(settings, "demo_org_slug", "")
    monkeypatch.setattr(settings, "seed_data", False)
    assert settings.demo_org == ""
    monkeypatch.setattr(settings, "seed_data", True)
    assert settings.demo_org == settings.seed_org_slug


def test_license_banner_only_for_unenforced_unlicensed_builds():
    from app.api.v1.system import license_banner_state

    assert license_banner_state("unlicensed", enforcing=False)["evaluation_build"] is True
    assert license_banner_state("unconfigured", enforcing=False)["evaluation_build"] is True
    assert license_banner_state("valid", enforcing=False)["evaluation_build"] is False
    assert license_banner_state("unlicensed", enforcing=True)["evaluation_build"] is False
