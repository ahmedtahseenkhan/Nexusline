"""Phase 1 free text -> key sweep for the core registers (product review §1.3, §1.4).

Risks, controls (and control tests), policies (and policy reviews), business units,
processes, the legal register and goals. No database: the endpoints run against a fake
session with stubbed loaders, as in ``test_risk_integrity``. The shared write/read rule
(``services.ref_fields``) has its own pure tests in ``test_fk_sweep_ops``; here it is
driven through these modules' declarations.

Pinned here:

1. Create/Update accept the new keys and no longer accept ``workflow_status`` (the record
   lifecycle owns it); Read still shows it, plus a resolved ref beside each key.
2. The id wins over text; text alone is matched (email / full name / lookup value or
   label); unmatched text is kept; resending a record's own text keeps its key.
3. A bad id is a 422 naming the field; a good one writes its label into the legacy text.
4. A page of records resolves its refs in one query per kind.
5. Deleting a risk, control, policy, business unit or process is audited and refused
   (403) to the person who entered it while segregation of duties applies.
6. The CSV registry for these registers carries no ``workflow_status`` column and its
   owner/category columns flow into the Create schema as matchable text.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import controls as controls_api
from app.api.v1 import organization as org_api
from app.api.v1 import policies as policies_api
from app.api.v1 import risks as risks_api
from app.models.identity import User
from app.models.lookup import Lookup
from app.models.risk import Risk
from app.schemas import control as control_s
from app.schemas import goal as goal_s
from app.schemas import organization as org_s
from app.schemas import policy as policy_s
from app.schemas import risk as risk_s
from app.services import delete_guard, dual_control
from app.services import ref_fields as rf
from app.services.import_registry import REGISTRY

# ============================================================== schemas ===
WRITE_SCHEMAS = {
    "risk": (risk_s.RiskCreate, risk_s.RiskUpdate,
             {"owner_id", "treatment_owner_id", "category_id", "workflow_owner_id"}),
    "control": (control_s.ControlCreate, control_s.ControlUpdate,
                {"owner_id", "operator_id", "classification_id", "workflow_owner_id"}),
    "policy": (policy_s.PolicyCreate, policy_s.PolicyUpdate,
               {"owner_id", "category_id", "workflow_owner_id"}),
    "business_unit": (org_s.BusinessUnitCreate, org_s.BusinessUnitUpdate,
                      {"manager_id", "workflow_owner_id"}),
    "process": (org_s.ProcessCreate, org_s.ProcessUpdate, {"owner_id", "workflow_owner_id"}),
    "legal": (org_s.LegalCreate, org_s.LegalUpdate, {"category_id", "workflow_owner_id"}),
    "goal": (goal_s.GoalCreate, goal_s.GoalUpdate, {"owner_id", "workflow_owner_id"}),
}

async def _no_review_policy(db, user):
    from app.services.risk_scoring import SeverityScale

    return SeverityScale(), {}


async def _no_alert_refresh(db, user, risk):
    return None


READ_SCHEMAS = {
    "risk": (risk_s.RiskRead, {"owner_ref", "treatment_owner_ref", "category_ref", "workflow_owner_ref"}),
    "control": (control_s.ControlRead,
                {"owner_ref", "operator_ref", "classification_ref", "workflow_owner_ref"}),
    "policy": (policy_s.PolicyRead, {"owner_ref", "category_ref", "workflow_owner_ref"}),
    "business_unit": (org_s.BusinessUnitRead, {"manager_ref", "workflow_owner_ref"}),
    "process": (org_s.ProcessRead, {"owner_ref", "workflow_owner_ref"}),
    "legal": (org_s.LegalRead, {"category_ref", "workflow_owner_ref"}),
    "goal": (goal_s.GoalRead, {"owner_ref", "workflow_owner_ref"}),
}


@pytest.mark.parametrize("module", sorted(WRITE_SCHEMAS))
def test_create_and_update_take_the_new_keys_and_not_workflow_status(module):
    create, update, keys = WRITE_SCHEMAS[module]
    for schema in (create, update):
        assert keys <= set(schema.model_fields), (schema.__name__, keys - set(schema.model_fields))
        assert "workflow_status" not in schema.model_fields, schema.__name__
        # The approval owner is picked, never typed: its text is read-only.
        assert "workflow_owner" not in schema.model_fields, schema.__name__


@pytest.mark.parametrize("module", sorted(WRITE_SCHEMAS))
def test_a_sent_workflow_status_is_dropped_not_stored(module):
    create, update, _ = WRITE_SCHEMAS[module]
    body = update(workflow_status="approved")
    assert "workflow_status" not in body.model_dump(exclude_unset=True)


@pytest.mark.parametrize("module", sorted(READ_SCHEMAS))
def test_reads_keep_workflow_status_and_show_every_key_with_its_ref(module):
    read, refs = READ_SCHEMAS[module]
    _, _, keys = WRITE_SCHEMAS[module]
    fields = set(read.model_fields)
    assert "workflow_status" in fields and "workflow_owner" in fields
    assert keys <= fields
    assert refs <= fields


def test_child_records_take_and_show_their_person():
    assert "tested_by_id" in control_s.ControlAuditCreate.model_fields
    assert {"tested_by_id", "tested_by_ref", "auditor"} <= set(control_s.ControlAuditRead.model_fields)
    assert "reviewer_id" in policy_s.PolicyReviewCreate.model_fields
    assert {"reviewer_id", "reviewer_ref", "reviewer"} <= set(policy_s.PolicyReviewRead.model_fields)


DECLARED = {
    Risk: (risks_api.RISK_REFS, risk_s.RiskRead),
    controls_api.Control: (controls_api.CONTROL_REFS, control_s.ControlRead),
    controls_api.ControlAudit: (controls_api.AUDIT_REFS, control_s.ControlAuditRead),
    policies_api.Policy: (policies_api.POLICY_REFS, policy_s.PolicyRead),
    policies_api.PolicyReview: (policies_api.REVIEW_REFS, policy_s.PolicyReviewRead),
    org_api.BusinessUnit: (org_api.BU_REFS, org_s.BusinessUnitRead),
    org_api.Process: (org_api.PROCESS_REFS, org_s.ProcessRead),
    org_api.Legal: (org_api.LEGAL_REFS, org_s.LegalRead),
}


def test_every_declared_field_names_real_columns_and_read_fields():
    from app.api.v1 import goals as goals_api
    from app.db.fk_backfill import FK_LOOKUP_KEYS

    declared = {**DECLARED, goals_api.Goal: (goals_api.GOAL_REFS, goal_s.GoalRead)}
    for model, (fields, read) in declared.items():
        cols = model.__table__.c
        for f in fields:
            assert f.id_field in cols, (model.__name__, f.id_field)
            assert f.text_field is None or f.text_field in cols, (model.__name__, f.text_field)
            assert f.ref_name in read.model_fields, (read.__name__, f.ref_name)
            if f.kind == "lookup":
                assert FK_LOOKUP_KEYS[(model.__tablename__, f.id_field)] == f.lookup_key


def test_every_routed_record_declares_its_approval_owner():
    children = (controls_api.ControlAudit, policies_api.PolicyReview)  # not routed on their own
    for model, (fields, _read) in DECLARED.items():
        if model not in children:
            assert rf.WORKFLOW_OWNER in fields, model.__name__


# ============================================================ fake session ===
def _user_row(uid=None, name="Jane Doe", email="jane@bank.pk", active=True):
    return SimpleNamespace(id=uid or uuid.uuid4(), full_name=name, email=email, is_active=active)


def _lookup_row(key="risk_category", label="Operational risk", value="operational", active=True):
    return SimpleNamespace(id=uuid.uuid4(), key=key, value=value, label=label, active=active)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    """``get`` from a dict; ``scalars`` answers by the selected entity and counts calls."""

    def __init__(self, users=(), lookups=()):
        self.users = {u.id: u for u in users}
        self.lookups = {r.id: r for r in lookups}
        self.scalar_calls: list[str] = []
        self.flushed = 0

    async def get(self, model, key):
        if model is User:
            return self.users.get(key)
        if model is Lookup:
            return self.lookups.get(key)
        return None

    async def scalars(self, stmt, *_a, **_k):
        entity = stmt.column_descriptions[0]["entity"]
        self.scalar_calls.append(entity.__name__)
        source = self.users if entity is User else self.lookups if entity is Lookup else {}
        return _Rows(list(source.values()))

    async def flush(self):
        self.flushed += 1


OWNER = rf.user("owner_id", "owner")


async def test_a_picked_user_writes_their_name_into_the_text():
    jane = _user_row()
    data = {"owner_id": jane.id, "owner": "typed by an old client"}
    await rf.apply_refs(FakeDB(users=[jane]), controls_api.Control, data, [OWNER])
    assert data == {"owner_id": jane.id, "owner": "Jane Doe"}


async def test_bad_ids_are_422_naming_the_field():
    gone = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        await rf.apply_refs(FakeDB(), controls_api.Control, {"owner_id": gone}, [OWNER])
    assert exc.value.status_code == 422 and exc.value.detail.startswith("owner_id:")

    wrong_list = _lookup_row(key="policy_category")
    with pytest.raises(HTTPException) as exc:
        await rf.apply_refs(
            FakeDB(lookups=[wrong_list]), Risk, {"category_id": wrong_list.id}, risks_api.RISK_REFS
        )
    assert exc.value.status_code == 422 and exc.value.detail.startswith("category_id:")


async def test_a_category_label_longer_than_the_legacy_column_is_trimmed():
    long = _lookup_row(label="L" * 180)  # risks.category is String(100)
    data = {"category_id": long.id}
    await rf.apply_refs(FakeDB(lookups=[long]), Risk, data, risks_api.RISK_REFS)
    assert len(data["category"]) == Risk.__table__.c.category.type.length


async def test_resending_a_deactivated_owner_the_record_already_has_is_not_refused():
    left = _user_row(name="Left The Bank", active=False)
    record = SimpleNamespace(owner_id=left.id, owner="Left The Bank")
    data = {"owner_id": left.id, "owner": "Left The Bank", "name": "Access review"}
    await rf.apply_refs(FakeDB(users=[left]), controls_api.Control, data, [OWNER], record=record)
    assert "owner_id" not in data  # unchanged: nothing written, nothing re-checked
    with pytest.raises(HTTPException):  # but a new pick of that person is refused
        await rf.apply_refs(FakeDB(users=[left]), controls_api.Control, {"owner_id": left.id}, [OWNER])


async def test_text_alone_is_matched_and_unmatched_text_is_kept_with_a_warning():
    """What a CSV import (or an older API client) sends: text only."""
    jane = _user_row()
    tech = _lookup_row(key="control_classification", value="technical", label="Technical")
    hit = {"owner": "JANE@bank.pk", "classification": "technical"}
    warned = await rf.apply_refs(
        FakeDB(users=[jane], lookups=[tech]), controls_api.Control, hit, controls_api.CONTROL_REFS
    )
    assert (hit["owner_id"], hit["owner"]) == (jane.id, "Jane Doe")
    assert (hit["classification_id"], hit["classification"]) == (tech.id, "Technical")
    assert warned == []

    miss = {"owner": "Head of Ops (vacant)"}
    with rf.collect_warnings() as row_warnings:
        await rf.apply_refs(FakeDB(users=[jane]), controls_api.Control, miss, controls_api.CONTROL_REFS)
    assert miss == {"owner": "Head of Ops (vacant)", "owner_id": None}
    assert len(row_warnings) == 1 and "Head of Ops (vacant)" in row_warnings[0]


async def test_workflow_owner_text_is_not_an_input():
    data = {"workflow_owner": "typed approver"}
    await rf.apply_refs(FakeDB(), org_api.BusinessUnit, data, org_api.BU_REFS)
    assert "workflow_owner" not in data


async def test_a_page_resolves_refs_in_one_query_per_kind():
    jane, ali = _user_row(), _user_row(name="Ali Khan", email="ali@bank.pk")
    cat = _lookup_row()
    risks = [
        SimpleNamespace(owner_id=jane.id, treatment_owner_id=ali.id, category_id=cat.id,
                        workflow_owner_id=None),
        SimpleNamespace(owner_id=ali.id, treatment_owner_id=None, category_id=None,
                        workflow_owner_id=jane.id),
        SimpleNamespace(owner_id=None, treatment_owner_id=None, category_id=cat.id,
                        workflow_owner_id=None),
    ]
    reads = [risk_s.RiskRead.model_construct() for _ in risks]
    db = FakeDB(users=[jane, ali], lookups=[cat])
    await rf.fill_refs(db, list(zip(risks, reads)), risks_api.RISK_REFS)
    assert sorted(db.scalar_calls) == ["Lookup", "User"]
    assert reads[0].owner_ref.full_name == "Jane Doe"
    assert reads[0].treatment_owner_ref.full_name == "Ali Khan"
    assert reads[0].category_ref.label == "Operational risk"
    assert reads[1].workflow_owner_ref.id == jane.id
    assert reads[2].owner_ref is None and reads[2].category_ref.id == cat.id


# ================================================================ endpoints ===
def _actor():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x",
                           permission_codes=["risk:read", "risk:write", "risk:delete"])


def _risk(**kw):
    base = dict(
        id=uuid.uuid4(), reference="R-001", title="Card fraud",
        inherent_likelihood=3, inherent_impact=4, residual_likelihood=None, residual_impact=None,
        residual_override_reason="", needs_review=False, review_reason="",
        review_frequency=None, last_review_date=None, annual_loss_expectancy=None,
        treatment_owner="", treatment_owner_id=None, category="", category_id=None,
        owner_id=None, workflow_owner="", workflow_owner_id=None, deleted=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    for module in (risks_api.audit, controls_api.audit_log, policies_api.audit, org_api.audit_log):
        monkeypatch.setattr(module, "record", record)
    return calls


@pytest.fixture
def risk_io(monkeypatch):
    state = {}

    async def load(db, risk_id):
        return state["risk"]

    async def read(db, risk_id, user):
        return state["risk"]

    async def size(db, tenant_id):
        return 5

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api, "_read", read)
    monkeypatch.setattr(risks_api, "get_matrix_size", size)
    # F-22: the review clock and the alert refresh need the tenant's settings and the
    # notifications table; neither is under test here.
    monkeypatch.setattr(risks_api, "_review_policy", _no_review_policy)
    monkeypatch.setattr(risks_api, "_refresh_alerts", _no_alert_refresh)
    monkeypatch.setattr(risks_api, "_reconcile_title_flag", _no_alert_refresh)
    return state


async def test_update_risk_picks_a_treatment_owner_and_mirrors_the_name(risk_io, audit_calls):
    jane = _user_row()
    risk_io["risk"] = _risk(treatment_owner="someone typed this")
    await risks_api.update_risk(
        risk_io["risk"].id, risk_s.RiskUpdate(treatment_owner_id=jane.id), FakeDB(users=[jane]), _actor()
    )
    assert (risk_io["risk"].treatment_owner_id, risk_io["risk"].treatment_owner) == (jane.id, "Jane Doe")


async def test_update_risk_rejects_a_category_from_another_list(risk_io, audit_calls):
    wrong = _lookup_row(key="incident_type")
    risk_io["risk"] = _risk()
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(
            risk_io["risk"].id, risk_s.RiskUpdate(category_id=wrong.id), FakeDB(lookups=[wrong]), _actor()
        )
    assert exc.value.status_code == 422 and exc.value.detail.startswith("category_id:")
    assert risk_io["risk"].category_id is None and audit_calls == []


async def test_an_old_form_echoing_the_text_keeps_the_key(risk_io, audit_calls):
    jane = _user_row(name="Jane Doe-Khan")  # renamed since the text was written
    risk_io["risk"] = _risk(treatment_owner="Jane Doe", treatment_owner_id=jane.id)
    await risks_api.update_risk(
        risk_io["risk"].id, risk_s.RiskUpdate(title="Card fraud", treatment_owner="Jane Doe"),
        FakeDB(users=[jane]), _actor(),
    )
    assert risk_io["risk"].treatment_owner_id == jane.id


def _sod(monkeypatch, *, maker, required=True):
    async def maker_of(db, entity_type, entity_id, record=None):
        return maker

    async def dual_control_required(db, module, action, amount=None):
        return required, None

    monkeypatch.setattr(dual_control, "maker_of", maker_of)
    monkeypatch.setattr(dual_control, "dual_control_required", dual_control_required)


async def test_the_maker_cannot_delete_their_own_risk(risk_io, audit_calls, monkeypatch):
    me = _actor()
    risk_io["risk"] = _risk()
    _sod(monkeypatch, maker=me.id)
    with pytest.raises(HTTPException) as exc:
        await risks_api.delete_risk(risk_io["risk"].id, FakeDB(), me)
    assert exc.value.status_code == 403
    assert exc.value.detail == delete_guard.refusal("risk", "risk")
    assert risk_io["risk"].deleted is False and audit_calls == []


async def test_an_independent_user_deletes_the_risk_and_it_is_audited(risk_io, audit_calls, monkeypatch):
    risk_io["risk"] = _risk()
    _sod(monkeypatch, maker=uuid.uuid4())
    await risks_api.delete_risk(risk_io["risk"].id, FakeDB(), _actor())
    assert risk_io["risk"].deleted is True
    assert [c["action"] for c in audit_calls] == ["delete"]


async def test_a_rule_switching_dual_control_off_lets_a_single_user_delete(risk_io, audit_calls, monkeypatch):
    me = _actor()
    risk_io["risk"] = _risk()
    _sod(monkeypatch, maker=me.id, required=False)
    await risks_api.delete_risk(risk_io["risk"].id, FakeDB(), me)
    assert risk_io["risk"].deleted is True


def _control(**kw):
    base = dict(id=uuid.uuid4(), reference="AC-2", name="Access review", deleted=False,
                deleted_date=None, owner_id=None, status=None, audit_frequency=None)
    base.update(kw)
    return SimpleNamespace(**base)


async def test_deleting_a_control_is_audited_and_under_dual_control(audit_calls, monkeypatch):
    control = _control()

    async def get(db, control_id):
        return control

    monkeypatch.setattr(controls_api, "_get_or_404", get)
    me = _actor()
    _sod(monkeypatch, maker=me.id)
    with pytest.raises(HTTPException) as exc:
        await controls_api.delete_control(control.id, FakeDB(), me)
    assert exc.value.status_code == 403 and control.deleted is False

    _sod(monkeypatch, maker=uuid.uuid4())
    await controls_api.delete_control(control.id, FakeDB(), me)
    assert control.deleted is True
    assert audit_calls[-1]["action"] == "delete" and audit_calls[-1]["entity_type"] == "control"


async def test_deleting_a_policy_is_audited_and_under_dual_control(audit_calls, monkeypatch):
    policy = SimpleNamespace(id=uuid.uuid4(), reference="POL-001", title="Access", deleted=False,
                             deleted_date=None, owner_id=None)

    async def load(db, policy_id):
        return policy

    monkeypatch.setattr(policies_api, "_load", load)
    me = _actor()
    _sod(monkeypatch, maker=me.id)
    with pytest.raises(HTTPException):
        await policies_api.delete_policy(policy.id, FakeDB(), me)
    assert policy.deleted is False
    _sod(monkeypatch, maker=uuid.uuid4())
    await policies_api.delete_policy(policy.id, FakeDB(), me)
    assert policy.deleted is True and audit_calls[-1]["entity_type"] == "policy"


@pytest.mark.parametrize("endpoint, label", [
    (org_api.delete_business_unit, "business unit"), (org_api.delete_process, "process"),
])
async def test_org_register_deletes_are_under_dual_control(endpoint, label, audit_calls, monkeypatch):
    unit = SimpleNamespace(id=uuid.uuid4(), name="Retail", deleted=False, deleted_date=None)

    async def get(db, model, obj_id, name):
        return unit

    monkeypatch.setattr(org_api, "_get", get)
    me = _actor()
    _sod(monkeypatch, maker=me.id)
    with pytest.raises(HTTPException) as exc:
        await endpoint(unit.id, FakeDB(), me)
    assert label in exc.value.detail and unit.deleted is False and audit_calls == []


async def test_the_named_tester_may_not_be_the_controls_maker(monkeypatch):
    maker = _user_row(name="Maker")
    control = _control()

    async def get(db, control_id):
        return control

    monkeypatch.setattr(controls_api, "_get_or_404", get)
    _sod(monkeypatch, maker=maker.id)
    body = control_s.ControlAuditCreate(tested_by_id=maker.id)
    with pytest.raises(HTTPException) as exc:
        await controls_api.record_control_audit(control.id, body, FakeDB(users=[maker]), _actor())
    assert exc.value.status_code == 403


# ============================================================ CSV registry ===
MY_RESOURCES = ("risks", "controls", "policies", "legal", "business-units", "processes", "goals")


@pytest.mark.parametrize("resource", MY_RESOURCES)
def test_registry_imports_the_legacy_workflow_state(resource):
    # Reversed after the sweep: a bank migrating from a legacy tool keeps approved
    # states, gated on approval rights (import_registry.import_state_refusal).
    assert "workflow_status" in {c.field for c in REGISTRY[resource].columns}


def test_registry_owner_and_category_text_reaches_the_create_schema_for_matching():
    """Import builds the Create schema from the CSV row and calls the module's create
    function, which matches the text (ref_fields). So the text must survive the schema."""
    from app.api.v1.dataio import _row_to_payload

    res = REGISTRY["risks"]
    headers = {c.header: c for c in res.columns}
    payload = _row_to_payload(
        {"title": "Fraud", "inherent_likelihood": "2", "inherent_impact": "3",
         "category": "Operational", "treatment_owner": "jane@bank.pk",
         "workflow_status": "approved"},
        headers, {},
    )
    body = res.create_schema(**payload)
    assert (body.category, body.treatment_owner) == ("Operational", "jane@bank.pk")
    # The legacy state is carried by the import wrapper and written only after the
    # gate; the module's own create function never sees it.
    assert "workflow_status" in body.model_dump()
    person_help = {c.help for c in res.columns if c.field == "treatment_owner"}
    assert all("email or full name" in h.lower() for h in person_help)

