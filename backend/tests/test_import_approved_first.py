"""An import can't bring a record in live before it is approved.

Operational states that need the approval to exist first (an outsourced service
"active", a model "in production") are refused by the form while the record is a
draft; the import used to create them anyway. The gate now starts such a row at the
form's default, with a warning — unless the row is itself carried in approved."""
from app.services.import_registry import REGISTRY, ImportGate, _start_value
from app.services.lifecycle_gates import APPROVED_FIRST


def _gate(entity_type: str, resource: str) -> ImportGate:
    res = REGISTRY[resource]
    return ImportGate(approved_first=tuple(
        (rule, _start_value(res, rule.field)) for rule in APPROVED_FIRST[entity_type]
    ))


def test_live_status_on_an_unapproved_row_starts_at_the_default():
    payload = {"status": "active", "workflow_status": "draft"}
    warnings = _gate("outsourcing_arrangement", "outsourcing-arrangements").apply(payload)
    assert payload["status"] == "proposed"
    assert len(warnings) == 1 and "before its approval" in warnings[0]


def test_an_approved_row_keeps_its_live_status():
    payload = {"status": "in_production", "workflow_status": "approved"}
    assert _gate("model_inventory", "models").apply(payload) == []
    assert payload["status"] == "in_production"


def test_other_statuses_pass_untouched():
    payload = {"status": "development"}
    assert _gate("model_inventory", "models").apply(payload) == []
    assert payload["status"] == "development"
