"""A stored address is shown as it is: one unusual row must not fail the Users page."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate, UserRead


def _user(email: str):
    return SimpleNamespace(
        id=uuid.uuid4(), email=email, full_name="", is_active=True,
        created_at=datetime.now(timezone.utc), mfa_enabled=False, auth_source="ldap",
        is_platform_admin=False, permission_codes=[], role_names=[],
    )


@pytest.mark.parametrize("email", ["loadtest@local", "ahmed@MBL", "svc-grc@corp"])
def test_a_directory_address_on_a_single_label_domain_still_reads(email):
    assert UserRead.model_validate(_user(email)).email == email


def test_a_new_account_still_needs_a_valid_address():
    with pytest.raises(ValidationError):
        UserCreate(email="loadtest@local", password="Password123!")
