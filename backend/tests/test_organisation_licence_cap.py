"""The licence caps organisations (2026-09-22): an on-premise bank is single-tenant.

The Organisations console and the self-service sign-up both create organisations; neither
may turn a one-organisation licence into a hosting platform. Self-service sign-up is off
unless the operator enables it. Pure functions plus endpoint shape; no DB.
"""
from __future__ import annotations

import inspect

from app.core.config import Settings
from app.services import licence_state as ls
from app.services import license as lic


def test_payload_without_the_field_is_single_tenant():
    assert lic.organisations_from_payload({}) == 1
    assert lic.organisations_from_payload({"organisations": None}) == 1
    assert lic.organisations_from_payload({"organisations": "abc"}) == 1
    assert lic.organisations_from_payload({"organisations": -3}) == 1


def test_zero_is_unlimited_and_counts_pass_through():
    assert lic.organisations_from_payload({"organisations": 0}) == 0
    assert lic.organisations_from_payload({"organisations": "12"}) == 12
    assert lic.LicenseInfo().organisations == 1
    assert "organisations" in lic.LicenseInfo().to_public()


def test_single_tenant_licence_refuses_a_second_organisation():
    assert ls.organisation_refusal(limit=1, used=0, enforcing=True) is None
    msg = ls.organisation_refusal(limit=1, used=1, enforcing=True)
    assert msg and "one organisation" in msg
    assert ls.organisation_refusal(limit=1, used=5, enforcing=True)


def test_multi_organisation_licence_counts_and_unlimited_never_refuses():
    assert ls.organisation_refusal(limit=3, used=2, enforcing=True) is None
    msg = ls.organisation_refusal(limit=3, used=3, enforcing=True)
    assert msg and "3 organisations" in msg
    assert ls.organisation_refusal(limit=0, used=999, enforcing=True) is None


def test_dev_builds_never_refuse():
    assert ls.organisation_refusal(limit=1, used=10, enforcing=False) is None


def test_organisations_limit_is_unlimited_in_a_dev_build(monkeypatch):
    from app.core import build

    monkeypatch.setattr(build, "PRODUCTION_BUILD", False)
    assert ls.organisations_limit() == 0


def test_console_and_self_service_both_check_the_cap():
    from app.api.v1 import auth, platform

    assert "ensure_organisation_available" in inspect.getsource(platform.create_org)
    assert "ensure_organisation_available" in inspect.getsource(auth.register_org)


def test_self_registration_is_off_by_default_and_gates_the_endpoint(monkeypatch):
    from app.api.v1 import auth

    monkeypatch.delenv("ALLOW_SELF_REGISTRATION", raising=False)
    assert Settings(_env_file=None).allow_self_registration is False
    source = inspect.getsource(auth.register_org)
    assert "allow_self_registration" in source and "HTTP_403_FORBIDDEN" in source


def test_platform_summary_reports_the_cap():
    from app.api.v1.platform import PlatformSummary

    assert "organizations_limit" in PlatformSummary.model_fields
    assert "can_add_organization" in PlatformSummary.model_fields


def test_vendor_cli_signs_the_organisation_count():
    from app.tools import license as cli

    source = inspect.getsource(cli._sign)
    assert '"organisations": args.organisations' in source
    assert "--organisations" in inspect.getsource(cli.main)
