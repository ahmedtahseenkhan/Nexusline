"""Phase 1 free text -> key sweep for the operational registers (product review §1.3, §1.4).

Issues (with CAPA actions and the progress log), incidents (with regulatory reports),
KRIs, loss events, RCSA campaigns (with their risk lines) and third parties. No database:
the write rule in ``services.ref_fields`` is pure and tested directly; the endpoints run
against a fake session with stubbed loaders, as in ``test_risk_integrity``.

Pinned here:

1. Create/Update accept the new keys and no longer accept ``workflow_status`` (the record
   lifecycle owns it); Read still shows it, plus a resolved ref beside each key.
2. The id wins over text; text alone is matched (email / full name / unit or process
   name / lookup value or label); unmatched, ambiguous or deactivated text is kept with
   a warning; resending a record's own id or text changes nothing.
3. A bad id is a 422 naming the field; a good one writes its label into the legacy text.
4. A page of records (and their child lines) resolves its refs in one query per kind.
5. Deleting an issue, incident or third party is audited and refused (403) to the person
   who entered it while segregation of duties applies; removing a CAPA action is audited.
6. The CSV registry for these registers carries no ``workflow_status`` column, and an
   import reports every value it had to keep as text as a row warning.
"""
from __future__ import annotations

import dataclasses
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import dataio
from app.api.v1 import incidents as incidents_api
from app.api.v1 import issues as issues_api
from app.api.v1 import operational_risk as oprisk_api
from app.api.v1 import regulatory as regulatory_api
from app.api.v1 import vendors as vendors_api
from app.db.fk_backfill import FK_LOOKUP_KEYS
from app.models.identity import User
from app.models.incident import Incident, RegulatoryReport
from app.models.issue import Issue, IssueAction, IssueUpdate
from app.models.lookup import Lookup
from app.models.operational_risk import KeyRiskIndicator, LossEvent, RcsaAssessment, RcsaRisk
from app.models.organization import BusinessUnit, Process
from app.models.vendor import Vendor
from app.schemas import incident as incident_s
from app.schemas import issue as issue_s
from app.schemas import operational_risk as oprisk_s
from app.schemas import vendor as vendor_s
from app.schemas.dataio import ImportRequest
from app.services import audit as audit_service
from app.services import delete_guard, dual_control
from app.services import ref_fields as rf
from app.services.import_registry import REGISTRY
from app.services.ref_fields import Candidate

# ================================================================ schemas ===
WRITE_SCHEMAS = {
    "issue": (issue_s.IssueCreate, issue_s.IssueUpdatePatch,
              {"owner_id", "business_unit_id", "category_id", "workflow_owner_id"}),
    "incident": (incident_s.IncidentCreate, incident_s.IncidentUpdate,
                 {"assignee_id", "reported_by_id", "category_id", "classification_id",
                  "regulator_id", "workflow_owner_id"}),
    "kri": (oprisk_s.KriCreate, oprisk_s.KriUpdate,
            {"owner_id", "business_unit_id", "category_id", "workflow_owner_id"}),
    "loss_event": (oprisk_s.LossEventCreate, oprisk_s.LossEventUpdate,
                   {"action_owner_id", "business_unit_id", "workflow_owner_id"}),
    "rcsa": (oprisk_s.RcsaCreate, oprisk_s.RcsaUpdate,
             {"assessor_id", "business_unit_id", "process_id", "workflow_owner_id"}),
    "vendor": (vendor_s.VendorCreate, vendor_s.VendorUpdate,
               {"category_id", "country_id", "workflow_owner_id"}),
}
READ_SCHEMAS = {
    "issue": (issue_s.IssueRead, {"owner_ref", "business_unit_ref", "category_ref", "workflow_owner_ref"}),
    "incident": (incident_s.IncidentRead, {"assignee_ref", "reported_by_ref", "category_ref",
                                           "classification_ref", "regulator_ref", "workflow_owner_ref"}),
    "kri": (oprisk_s.KriRead, {"owner_ref", "business_unit_ref", "category_ref", "workflow_owner_ref"}),
    "loss_event": (oprisk_s.LossEventRead, {"action_owner_ref", "business_unit_ref", "workflow_owner_ref"}),
    "rcsa": (oprisk_s.RcsaRead, {"assessor_ref", "business_unit_ref", "process_ref", "workflow_owner_ref"}),
    "vendor": (vendor_s.VendorRead, {"category_ref", "country_ref", "workflow_owner_ref"}),
}


@pytest.mark.parametrize("module", sorted(WRITE_SCHEMAS))
def test_create_and_update_take_the_new_keys_and_not_workflow_status(module):
    create, update, keys = WRITE_SCHEMAS[module]
    for schema in (create, update):
        assert keys <= set(schema.model_fields), (schema.__name__, keys - set(schema.model_fields))
        assert "workflow_status" not in schema.model_fields, schema.__name__
        assert "workflow_owner" not in schema.model_fields, schema.__name__


@pytest.mark.parametrize("module", sorted(WRITE_SCHEMAS))
def test_a_sent_workflow_status_is_dropped_not_stored(module):
    _, update, _ = WRITE_SCHEMAS[module]
    body = update(workflow_status="approved", workflow_owner="Someone")
    assert body.model_dump(exclude_unset=True) == {}


@pytest.mark.parametrize("module", sorted(READ_SCHEMAS))
def test_reads_keep_workflow_status_and_show_every_key_with_its_ref(module):
    read, refs = READ_SCHEMAS[module]
    _, _, keys = WRITE_SCHEMAS[module]
    fields = set(read.model_fields)
    assert {"workflow_status", "workflow_owner"} <= fields
    assert keys <= fields and refs <= fields


def test_child_lines_take_and_show_their_person_or_category():
    assert "owner_id" in issue_s.IssueActionCreate.model_fields
    assert "owner_id" in issue_s.IssueActionUpdate.model_fields
    assert {"owner", "owner_id", "owner_ref"} <= set(issue_s.IssueActionRead.model_fields)
    assert "author_id" in issue_s.IssueUpdateCreate.model_fields
    assert {"author", "author_id", "author_ref"} <= set(issue_s.IssueUpdateRead.model_fields)
    for schema in (incident_s.RegReportCreate, incident_s.RegReportUpdate):
        assert "submitted_by_id" in schema.model_fields
    assert {"submitted_by", "submitted_by_id", "submitted_by_ref"} <= set(incident_s.RegReportRead.model_fields)
    for schema in (oprisk_s.RcsaRiskCreate, oprisk_s.RcsaRiskUpdate):
        assert {"category_id", "action_owner_id"} <= set(schema.model_fields)
    assert {"category_ref", "action_owner_ref"} <= set(oprisk_s.RcsaRiskRead.model_fields)


def test_vendor_location_stays_free_text_beside_the_country_picker():
    fields = vendor_s.VendorCreate.model_fields
    assert fields["location"].annotation is str
    assert "country" in (fields["location"].description or "").lower()
    assert "location" in (fields["country_id"].description or "")


DECLARED = [
    (Issue, issues_api.ISSUE_REFS, issue_s.IssueRead),
    (IssueAction, issues_api.ACTION_REFS, issue_s.IssueActionRead),
    (IssueUpdate, issues_api.UPDATE_REFS, issue_s.IssueUpdateRead),
    (Incident, incidents_api.INCIDENT_REFS, incident_s.IncidentRead),
    (RegulatoryReport, incidents_api.REPORT_REFS, incident_s.RegReportRead),
    (KeyRiskIndicator, oprisk_api.KRI_REFS, oprisk_s.KriRead),
    (LossEvent, oprisk_api.LOSS_REFS, oprisk_s.LossEventRead),
    (RcsaAssessment, oprisk_api.RCSA_REFS, oprisk_s.RcsaRead),
    (RcsaRisk, oprisk_api.RCSA_LINE_REFS, oprisk_s.RcsaRiskRead),
    (Vendor, vendors_api.VENDOR_REFS, vendor_s.VendorRead),
]


@pytest.mark.parametrize("model,fields,read", DECLARED, ids=lambda x: getattr(x, "__name__", ""))
def test_every_declared_field_names_real_columns_and_read_fields(model, fields, read):
    columns = model.__table__.c
    for f in fields:
        assert f.id_field in columns, (model.__name__, f.id_field)
        assert f.text_field is None or f.text_field in columns, (model.__name__, f.text_field)
        assert f.ref_name in read.model_fields, (read.__name__, f.ref_name)
        assert f.id_field in read.model_fields, (read.__name__, f.id_field)
        if f.kind == "lookup":
            assert f.lookup_key == FK_LOOKUP_KEYS[(model.__tablename__, f.id_field)]


# ============================================================ pure rule ===
OWNER = rf.user("owner_id", "owner")
ME, OTHER = uuid.uuid4(), uuid.uuid4()


@pytest.mark.parametrize(
    "sent,stored,expected",
    [
        # The id wins over any text sent with it.
        ({"owner_id": OTHER, "owner": "typed"}, (None, ""), ("id", OTHER)),
        ({"owner_id": OTHER}, (ME, "Me"), ("id", OTHER)),
        # A form resending the stored id changes nothing (and its text is ignored).
        ({"owner_id": ME, "owner": "stale text"}, (ME, "Me"), ("same", None)),
        # Clearing a picked person clears the name it wrote…
        ({"owner_id": None}, (ME, "Me"), ("clear", "")),
        ({"owner_id": None, "owner": "Me"}, (ME, "Me"), ("clear", "")),
        # …but keeps different text sent with the null, as typed.
        ({"owner_id": None, "owner": "Someone else"}, (ME, "Me"), ("clear", "Someone else")),
        # A null id with nothing stored clears nothing: untouched legacy text survives,
        # and a create (which dumps owner_id=None for every row) still matches its text.
        ({"owner_id": None}, (None, "Head of Ops"), ("keep", None)),
        ({"owner_id": None, "owner": "ali@bank.pk"}, (None, ""), ("text", "ali@bank.pk")),
        # Text alone: new text is matched; the same text (case/spacing aside) is kept.
        ({"owner": "ali@bank.pk"}, (None, ""), ("text", "ali@bank.pk")),
        ({"owner": "  me "}, (ME, "Me"), ("keep", None)),
        ({"owner": ""}, (ME, "Me"), ("text", "")),
        ({}, (ME, "Me"), ("keep", None)),
    ],
)
def test_pick(sent, stored, expected):
    assert rf.pick(sent, OWNER, stored_id=stored[0], stored_text=stored[1]) == expected


def test_workflow_owner_text_is_readable_but_not_writable():
    assert rf.pick({"workflow_owner": "Typed"}, rf.WORKFLOW_OWNER) == ("keep", None)
    assert rf.pick({"workflow_owner_id": ME, "workflow_owner": "x"}, rf.WORKFLOW_OWNER) == ("id", ME)


def test_ref_names():
    assert [f.ref_name for f in incidents_api.INCIDENT_REFS] == [
        "assignee_ref", "reported_by_ref", "category_ref", "classification_ref",
        "regulator_ref", "workflow_owner_ref",
    ]


# ====================================================== import resolution ===
def _person(name, email, active=True):
    return Candidate(uuid.uuid4(), name or email, strong=(email,), weak=(name,), active=active)


def test_resolve_text_prefers_an_email_over_namesakes():
    ali1, ali2 = _person("Ali Khan", "ali@bank.pk"), _person("Ali Khan", "ali.k@bank.pk")
    hit = rf.resolve_text("ALI@bank.pk ", [ali1, ali2], field="owner", noun="user")
    assert (hit.id, hit.label, hit.warning) == (ali1.id, "Ali Khan", None)


def test_resolve_text_matches_a_full_name_ignoring_case_and_spacing():
    ali = _person("Ali Khan", "ali@bank.pk")
    assert rf.resolve_text("ali   khan", [ali]).id == ali.id


def test_resolve_text_never_guesses_between_namesakes():
    found = rf.resolve_text("Ali Khan", [_person("Ali Khan", "a@x"), _person("Ali Khan", "b@x")],
                            field="owner", noun="user")
    assert found.id is None and found.warning == "owner: 'Ali Khan' matches 2 users; kept as text — pick one."


def test_resolve_text_does_not_pick_a_deactivated_user():
    found = rf.resolve_text("Gone Person", [_person("Gone Person", "g@x", active=False)],
                            field="assessor", noun="user")
    assert found.id is None and "deactivated" in found.warning and found.warning.startswith("assessor:")


def test_resolve_text_keeps_unmatched_text_with_a_warning():
    found = rf.resolve_text("Head of Ops (vacant)", [], field="owner", noun="user")
    assert found == rf.Resolution(None, None, "owner: no user matches 'Head of Ops (vacant)'; kept as text.")
    assert rf.resolve_text("   ", []) == rf.Resolution(None)


def test_resolve_text_matches_a_lookup_by_value_slug_or_label():
    fraud = Candidate(uuid.uuid4(), "Card fraud", strong=("card_fraud",), weak=("Card fraud",))
    assert rf.resolve_text("card_fraud", [fraud]).id == fraud.id
    assert rf.resolve_text("Card Fraud", [fraud]).label == "Card fraud"
    assert rf.resolve_text("card-fraud", [fraud]).id == fraud.id  # slug form of the value


def test_fit_trims_a_label_to_the_legacy_column():
    assert rf.fit(Incident, "regulator", "x" * 300) == "x" * 64
    assert rf.fit(Issue, "owner", "Ali") == "Ali"


# ===================================================== write path, fake db ===
def _user_row(name="Jane Doe", email="jane@bank.pk", active=True):
    return SimpleNamespace(id=uuid.uuid4(), full_name=name, email=email, is_active=active)


def _lookup_row(key="issue_category", label="Process failure", value="process_failure", active=True):
    return SimpleNamespace(id=uuid.uuid4(), key=key, value=value, label=label, active=active)


def _named_row(name="Retail Banking"):
    return SimpleNamespace(id=uuid.uuid4(), name=name, deleted=False)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    """``get`` from dicts; ``scalars`` answers by the selected entity and counts calls."""

    def __init__(self, users=(), lookups=(), units=(), processes=()):
        self.tables = {
            User: {u.id: u for u in users},
            Lookup: {r.id: r for r in lookups},
            BusinessUnit: {r.id: r for r in units},
            Process: {r.id: r for r in processes},
        }
        self.scalar_calls: list[str] = []
        self.flushed = 0
        self.added: list = []
        self.deleted: list = []
        self.scalar_result = None

    async def get(self, model, key):
        return self.tables.get(model, {}).get(key)

    async def scalars(self, stmt, *_a, **_k):
        entity = stmt.column_descriptions[0]["entity"]
        self.scalar_calls.append(entity.__name__)
        return _Rows(list(self.tables.get(entity, {}).values()))

    async def execute(self, stmt, *_a, **_k):
        """A column select (the import's link index): the selected columns of each row."""
        columns = stmt.column_descriptions
        rows = self.tables.get(columns[0]["entity"], {}).values()
        return _Rows([tuple(getattr(r, c["name"], None) for c in columns) for r in rows])

    async def scalar(self, *_a, **_k):
        return self.scalar_result

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flushed += 1

    @asynccontextmanager
    async def begin_nested(self):
        yield


async def test_a_picked_id_writes_its_label_into_the_legacy_text():
    jane, cat, unit = _user_row(), _lookup_row(), _named_row()
    data = {"owner_id": jane.id, "owner": "typed by an old client",
            "category_id": cat.id, "business_unit_id": unit.id}
    await rf.apply_refs(FakeDB(users=[jane], lookups=[cat], units=[unit]), Issue, data, issues_api.ISSUE_REFS)
    assert data == {"owner_id": jane.id, "owner": "Jane Doe", "category_id": cat.id,
                    "category": "Process failure", "business_unit_id": unit.id,
                    "business_unit": "Retail Banking"}


async def test_a_user_without_a_name_is_shown_by_email_and_a_process_by_name():
    anon, proc = _user_row(name=""), _named_row("Loan origination")
    data = {"assessor_id": anon.id, "process_id": proc.id}
    await rf.apply_refs(FakeDB(users=[anon], processes=[proc]), RcsaAssessment, data, oprisk_api.RCSA_REFS)
    assert data["assessor"] == "jane@bank.pk" and data["process"] == "Loan origination"


async def test_bad_ids_are_422_naming_the_field():
    with pytest.raises(HTTPException) as exc:
        await rf.apply_refs(FakeDB(), Incident, {"assignee_id": uuid.uuid4()}, incidents_api.INCIDENT_REFS)
    assert exc.value.status_code == 422 and exc.value.detail.startswith("assignee_id:")

    retired = _user_row(active=False)
    with pytest.raises(HTTPException) as exc:
        await rf.apply_refs(FakeDB(users=[retired]), KeyRiskIndicator, {"owner_id": retired.id},
                            oprisk_api.KRI_REFS)
    assert "deactivated" in exc.value.detail

    # An incident type is not a valid incident classification.
    incident_type = _lookup_row(key="incident_type")
    with pytest.raises(HTTPException) as exc:
        await rf.apply_refs(FakeDB(lookups=[incident_type]), Incident,
                            {"classification_id": incident_type.id}, incidents_api.INCIDENT_REFS)
    assert exc.value.status_code == 422 and exc.value.detail.startswith("classification_id:")

    with pytest.raises(HTTPException) as exc:
        await rf.apply_refs(FakeDB(), Vendor, {"country_id": uuid.uuid4()}, vendors_api.VENDOR_REFS)
    assert exc.value.detail.startswith("country_id:")


async def test_a_vendor_country_leaves_the_location_alone():
    pk = _lookup_row(key="country", label="Pakistan", value="PK")
    data = {"country_id": pk.id, "location": "I.I. Chundrigar Road, Karachi"}
    await rf.apply_refs(FakeDB(lookups=[pk]), Vendor, data, vendors_api.VENDOR_REFS)
    assert data == {"country_id": pk.id, "location": "I.I. Chundrigar Road, Karachi"}


async def test_a_long_regulator_label_is_trimmed_to_the_old_column():
    reg = _lookup_row(key="regulator", label="State Bank of Pakistan " * 5, value="sbp")
    data = {"regulator_id": reg.id}
    await rf.apply_refs(FakeDB(lookups=[reg]), Incident, data, incidents_api.INCIDENT_REFS)
    assert len(data["regulator"]) == 64


async def test_text_alone_is_matched_and_unmatched_text_is_kept_with_a_warning(monkeypatch):
    jane = _user_row()

    async def candidates(db, f, text):
        return [Candidate(jane.id, "Jane Doe", strong=(jane.email,), weak=(jane.full_name,))] \
            if text.strip().lower() == "jane@bank.pk" else []

    monkeypatch.setattr(rf, "_candidates", candidates)
    hit = {"action_owner": "JANE@bank.pk"}
    assert await rf.apply_refs(FakeDB(), LossEvent, hit, oprisk_api.LOSS_REFS) == []
    assert hit == {"action_owner": "Jane Doe", "action_owner_id": jane.id}

    miss = {"action_owner": "Head of Ops (vacant)"}
    with rf.collect_warnings() as bucket:
        warned = await rf.apply_refs(FakeDB(), LossEvent, miss, oprisk_api.LOSS_REFS)
    assert miss == {"action_owner": "Head of Ops (vacant)", "action_owner_id": None}
    assert warned == bucket == ["action_owner: no user matches 'Head of Ops (vacant)'; kept as text."]


async def test_resending_the_stored_id_does_not_recheck_a_departed_owner():
    gone = _user_row(active=False)
    record = SimpleNamespace(owner_id=gone.id, owner="Jane Doe")
    data = {"owner_id": gone.id, "owner": "Jane Doe", "title": "x"}
    await rf.apply_refs(FakeDB(users=[gone]), Issue, data, [OWNER], record=record)
    assert data == {"title": "x"}  # the other edit goes through; the owner stays as stored


async def test_create_with_schema_defaults_does_not_look_anything_up(monkeypatch):
    async def boom(*_a, **_k):
        raise AssertionError("no lookup for fields nobody sent")

    monkeypatch.setattr(rf, "_candidates", boom)
    data = issue_s.IssueCreate(title="x").model_dump()
    await rf.apply_refs(FakeDB(), Issue, data, issues_api.ISSUE_REFS)
    assert data["owner_id"] is None and data["owner"] == "" and data["category_id"] is None


async def test_a_page_resolves_refs_in_one_query_per_kind_across_child_lines():
    jane, ali = _user_row(), _user_row(name="Ali Khan", email="ali@bank.pk")
    cat, unit = _lookup_row(), _named_row()
    issue = SimpleNamespace(owner_id=jane.id, business_unit_id=unit.id, category_id=cat.id,
                            workflow_owner_id=None)
    action = SimpleNamespace(owner_id=ali.id)
    update = SimpleNamespace(author_id=jane.id)
    reads = [issue_s.IssueRead.model_construct(), issue_s.IssueActionRead.model_construct(),
             issue_s.IssueUpdateRead.model_construct()]
    db = FakeDB(users=[jane, ali], lookups=[cat], units=[unit])
    await rf.fill_refs(db, list(zip([issue, action, update], reads)),
                       issues_api.ISSUE_REFS + issues_api.UPDATE_REFS)
    assert sorted(db.scalar_calls) == ["BusinessUnit", "Lookup", "User"]
    assert reads[0].owner_ref.full_name == "Jane Doe"
    assert reads[0].business_unit_ref.name == "Retail Banking"
    assert reads[0].category_ref.label == "Process failure"
    assert reads[0].workflow_owner_ref is None
    assert reads[1].owner_ref.full_name == "Ali Khan"
    assert reads[2].author_ref.email == "jane@bank.pk"


# ================================================================ endpoints ===
def _actor(*perms):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x", permission_codes=list(perms))


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit_service, "record", record)
    return calls


def _sod(monkeypatch, *, maker, required=True):
    async def maker_of(db, entity_type, entity_id, record=None):
        return maker

    async def dual_control_required(db, module, action, amount=None):
        assert action == "delete"
        return required, None

    monkeypatch.setattr(dual_control, "maker_of", maker_of)
    monkeypatch.setattr(dual_control, "dual_control_required", dual_control_required)


def _record(**kw):
    base = dict(id=uuid.uuid4(), reference="ISS-7", title="Branch cash shortfall", name="Acme Ltd",
                deleted=False, deleted_date=None)
    base.update(kw)
    return SimpleNamespace(**base)


DELETES = [
    ("issue", issues_api, "_load_issue", issues_api.delete_issue),
    ("incident", incidents_api, "_load", incidents_api.delete_incident),
    ("vendor", vendors_api, "_load", vendors_api.delete_vendor),
]


@pytest.mark.parametrize("entity,module,loader,endpoint", DELETES, ids=[d[0] for d in DELETES])
async def test_the_maker_cannot_delete_what_they_entered(entity, module, loader, endpoint,
                                                          audit_calls, monkeypatch):
    me, obj = _actor(), _record()

    async def load(db, _id):
        return obj

    monkeypatch.setattr(module, loader, load)
    _sod(monkeypatch, maker=me.id)
    with pytest.raises(HTTPException) as exc:
        await endpoint(obj.id, FakeDB(), me)
    assert exc.value.status_code == 403
    assert exc.value.detail == delete_guard.refusal(entity, entity)
    assert obj.deleted is False and audit_calls == []


@pytest.mark.parametrize("entity,module,loader,endpoint", DELETES, ids=[d[0] for d in DELETES])
async def test_an_independent_user_deletes_and_it_is_audited(entity, module, loader, endpoint,
                                                              audit_calls, monkeypatch):
    obj = _record()

    async def load(db, _id):
        return obj

    monkeypatch.setattr(module, loader, load)
    _sod(monkeypatch, maker=uuid.uuid4())
    await endpoint(obj.id, FakeDB(), _actor())
    assert obj.deleted is True and obj.deleted_date is not None
    assert [(c["action"], c["entity_type"], c["entity_id"]) for c in audit_calls] == [
        ("delete", entity, obj.id)
    ]


async def test_removing_a_capa_action_is_recorded_on_the_issue(audit_calls):
    from app.models.issue import ActionStatus

    action = SimpleNamespace(id=uuid.uuid4(), issue_id=uuid.uuid4(), title="Re-train tellers",
                             owner="Jane Doe", status=ActionStatus.open)
    db = FakeDB()
    db.scalar_result = action
    await issues_api.delete_action(action.id, db, _actor())
    assert db.deleted == [action]  # IssueAction has no soft-delete envelope yet
    assert audit_calls[0]["entity_type"] == "issue" and audit_calls[0]["entity_id"] == action.issue_id
    assert audit_calls[0]["changes"]["action_removed"]["title"] == "Re-train tellers"


async def test_a_progress_entry_is_written_by_the_signed_in_user(monkeypatch):
    me = _user_row(name="Signed In")
    actor = _actor()
    actor.id = me.id

    async def load(db, _id):
        return None

    async def read(db, _id):
        return "read"

    monkeypatch.setattr(issues_api, "_load_issue", load)
    monkeypatch.setattr(issues_api, "_issue_read", read)
    db = FakeDB(users=[me])
    await issues_api.add_update(uuid.uuid4(), issue_s.IssueUpdateCreate(note="Chased owner"), db, actor)
    entry = db.added[0]
    assert entry.author_id == me.id and entry.author == "Signed In"


async def test_a_regulatory_report_submitter_is_picked(monkeypatch):
    jane = _user_row()
    report = SimpleNamespace(id=uuid.uuid4(), submitted_by_id=None, submitted_by="", submitted_at=None,
                             status=None)
    db = FakeDB(users=[jane])
    db.scalar_result = report
    monkeypatch.setattr(regulatory_api.RegReportRead, "model_validate",
                        classmethod(lambda cls, obj: cls.model_construct()))
    read = await regulatory_api.update_report(
        report.id, incident_s.RegReportUpdate(submitted_by_id=jane.id), db
    )
    assert report.submitted_by_id == jane.id and report.submitted_by == "Jane Doe"
    assert read.submitted_by_ref.id == jane.id


# ================================================================== import ===
MY_RESOURCES = ["issues", "incidents", "kris", "loss-events", "rcsa-assessments", "vendors"]


@pytest.mark.parametrize("resource", MY_RESOURCES)
def test_registry_imports_the_legacy_workflow_state(resource):
    # Reversed after the sweep: a bank migrating from a legacy tool keeps approved
    # states, gated on approval rights (import_registry.import_state_refusal).
    assert "workflow_status" in {c.field for c in REGISTRY[resource].columns}


def test_registry_person_unit_and_category_text_reaches_the_create_schema_for_matching():
    expected = {
        "issues": {"owner", "business_unit", "category"},
        "incidents": {"assignee", "reported_by", "category", "classification"},
        "kris": {"owner", "business_area", "category"},
        "loss-events": {"action_owner", "business_line"},
        "rcsa-assessments": {"assessor", "business_unit", "process"},
        "vendors": {"category"},
    }
    for resource, text_columns in expected.items():
        res = REGISTRY[resource]
        cols = {c.field: c for c in res.columns}
        for name in text_columns:
            assert cols[name].kind == "text" and name in res.create_schema.model_fields, (resource, name)
            assert "unmatched text is kept" in cols[name].help, (resource, name)


async def test_an_import_reports_text_it_had_to_keep_as_a_row_warning(monkeypatch, audit_calls):
    """End to end through the engine: the module's write path matches what it can and
    the engine turns every value kept as text into a warning on that row."""
    jane = _user_row()

    async def candidates(db, f, text):
        return [Candidate(jane.id, "Jane Doe", strong=(jane.email,), weak=(jane.full_name,))] \
            if f.kind == "user" and text.strip().lower() == "jane@bank.pk" else []

    monkeypatch.setattr(rf, "_candidates", candidates)
    created: list[dict] = []

    async def create(body, db, user):
        data = body.model_dump()
        await rf.apply_refs(db, Issue, data, issues_api.ISSUE_REFS)
        created.append(data)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setitem(dataio.REGISTRY, "issues", dataclasses.replace(REGISTRY["issues"], create_func=create))
    csv_text = (
        "title,owner,business_unit,category\n"
        "Cash shortfall,jane@bank.pk,,\n"
        "KYC backlog,Head of Ops (vacant),Retail,Onboarding\n"
    )
    result = await dataio.import_resource(
        "issues", ImportRequest(content=csv_text), FakeDB(), _actor("issue:read", "issue:write")
    )
    assert (result.total, result.created, result.errors) == (2, 2, [])
    assert created[0]["owner_id"] == jane.id and created[0]["owner"] == "Jane Doe"
    assert created[1]["owner_id"] is None and created[1]["owner"] == "Head of Ops (vacant)"
    assert [(w.row, w.message.split(":")[0]) for w in result.warnings] == [
        (3, "owner"), (3, "business_unit"), (3, "category")
    ]
    assert audit_calls[-1]["changes"]["warnings"] == 3
