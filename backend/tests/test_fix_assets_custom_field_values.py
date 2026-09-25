"""Custom-field values written from a record's form are checked like imported cells,
normalised to one spelling, and audited; a required field can't be cleared."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import custom_fields as api
from app.models.enums import CustomFieldType
from app.services import custom_field_values as cfv


def _field(label, field_type, *, options="", required=False, enabled=True):
    return SimpleNamespace(id=uuid.uuid4(), label=label, field_type=field_type, options=options,
                           required=required, enabled=enabled)


def test_values_normalise_like_an_imported_cell():
    tier = _field("Tier", CustomFieldType.select, options="Alpha\nBeta\n")
    assert cfv.clean(tier, " beta ") == "Beta"
    assert cfv.clean(_field("Flag", CustomFieldType.checkbox), "Yes") == "true"
    assert cfv.clean(_field("Flag", CustomFieldType.checkbox), "0") == "false"
    assert cfv.clean(_field("Due", CustomFieldType.date), "2026-09-25") == "2026-09-25"
    assert cfv.clean(_field("Headcount", CustomFieldType.number), "12.5") == "12.5"
    assert cfv.clean(_field("Notes", CustomFieldType.textarea), "  free text ") == "free text"


@pytest.mark.parametrize("field,raw", [
    (_field("Headcount", CustomFieldType.number), "twelve"),
    (_field("Headcount", CustomFieldType.number), "nan"),
    (_field("Tier", CustomFieldType.select, options="Alpha\nBeta"), "Gamma"),
    (_field("Due", CustomFieldType.date), "25/09/2026"),
    (_field("Flag", CustomFieldType.checkbox), "maybe"),
    (_field("Owner", CustomFieldType.text, required=True), "   "),
])
def test_bad_values_and_cleared_required_fields_are_refused(field, raw):
    with pytest.raises(ValueError) as exc:
        cfv.clean(field, raw)
    assert str(exc.value).startswith(f"{field.label}:")


def test_a_required_checkbox_or_a_disabled_field_may_be_blank():
    assert cfv.clean(_field("Agreed", CustomFieldType.checkbox, required=True), "") == ""
    assert cfv.clean(_field("Old", CustomFieldType.text, required=True, enabled=False), "") == ""


def test_a_save_writes_only_changes_and_names_them_for_the_audit_trail():
    tier = _field("Tier", CustomFieldType.select, options="Alpha\nBeta")
    notes = _field("Notes", CustomFieldType.text)
    fields = {tier.id: tier, notes.id: notes}
    writes, changes = api.plan_values(fields, {tier.id: "Alpha", notes.id: "same"},
                                      {tier.id: "beta", notes.id: "same", uuid.uuid4(): "other module"})
    assert writes == {tier.id: "Beta"}
    assert changes == {"Tier": {"from": "Alpha", "to": "Beta"}}


def test_one_bad_value_saves_nothing_and_lists_every_problem():
    size = _field("Size", CustomFieldType.number)
    owner = _field("Owner", CustomFieldType.text, required=True)
    with pytest.raises(HTTPException) as exc:
        api.plan_values({size.id: size, owner.id: owner}, {owner.id: "Ali"}, {size.id: "big", owner.id: ""})
    assert exc.value.status_code == 422
    assert "Size: 'big' is not a valid number" in exc.value.detail and "Owner: this field is required" in exc.value.detail
