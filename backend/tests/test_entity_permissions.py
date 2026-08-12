"""The polymorphic-panel guard: entity-type validation and per-module permissions.

Comments, tags, file uploads, attestations and custom-field values attach to records by
an ``(entity_type, entity_id)`` pair rather than a foreign key. Before this guard existed
any authenticated user could write through those panels to records they could only read,
and an unrecognised ``entity_type`` silently created an orphan row. These tests pin both
invariants so the panels can never drift back to authentication-only.
"""
import pytest
from fastapi import HTTPException

from app.models.custom_field import CUSTOM_FIELD_MODELS
from app.core.permissions import ALL_PERMISSIONS
from app.services import entity_types


class FakeUser:
    def __init__(self, *codes: str):
        self.permission_codes = list(codes)


# ------------------------------------------------------- registry consistency ---
def test_every_permission_code_is_real():
    """A typo in the registry would fail open or lock a module out entirely."""
    known = set(ALL_PERMISSIONS)
    bad = {
        name: (spec.read_perm, spec.write_perm)
        for name, spec in entity_types.ENTITY_TYPES.items()
        if spec.read_perm not in known or spec.write_perm not in known
    }
    assert bad == {}


def test_custom_field_models_are_all_registered():
    """Any model that can carry custom fields must be resolvable to a permission,
    otherwise its custom-field panel 422s for every user."""
    missing = [m for m in CUSTOM_FIELD_MODELS if m not in entity_types.ENTITY_TYPES]
    assert missing == []


# ------------------------------------------------------------ type validation ---
@pytest.mark.parametrize("bogus", ["nonsense", "not_a_real_type", "", "Risk", "risks"])
def test_unknown_entity_type_is_rejected(bogus):
    with pytest.raises(HTTPException) as exc:
        entity_types.spec(bogus)
    assert exc.value.status_code == 422
    assert "Unknown entity type" in exc.value.detail


def test_known_entity_type_resolves():
    assert entity_types.spec("risk").write_perm == "risk:write"
    assert entity_types.spec("shariah_review").read_perm == "shariah:read"


# ------------------------------------------------------------ permission gate ---
def test_reader_may_read_but_not_write():
    reader = FakeUser("risk:read")
    assert entity_types.require_read(reader, "risk").label == "Risk"
    with pytest.raises(HTTPException) as exc:
        entity_types.require_write(reader, "risk")
    assert exc.value.status_code == 403
    assert "risk:write" in exc.value.detail


def test_writer_may_write():
    writer = FakeUser("risk:read", "risk:write")
    assert entity_types.require_write(writer, "risk").label == "Risk"


def test_permission_on_one_module_does_not_grant_another():
    """The exact escalation the guard exists to stop: write on risks must not let a
    user write to, say, a Shariah review through the same shared panel."""
    writer = FakeUser("risk:read", "risk:write")
    with pytest.raises(HTTPException) as exc:
        entity_types.require_write(writer, "shariah_review")
    assert exc.value.status_code == 403


def test_no_permissions_cannot_read():
    with pytest.raises(HTTPException) as exc:
        entity_types.require_read(FakeUser(), "control")
    assert exc.value.status_code == 403


def test_validation_precedes_permission_check():
    """An unknown type is a 422 even for a user with no rights at all — the caller
    should learn the type is wrong, not that they lack a permission that cannot exist."""
    with pytest.raises(HTTPException) as exc:
        entity_types.require_write(FakeUser(), "nonsense")
    assert exc.value.status_code == 422
