"""Bank-module fixes of 25 Sep 2026 — links and lifecycles.

* "Add obligation" under a regulatory change resolves its requirement / policy /
  control ids onto the graph edges instead of passing them to the model (a 500).
* Reverse links: a Shariah ruling lists the products it approves, a product its
  reviews; policies and controls list the obligations they satisfy.
* An incident's asset link carries the asset's class, so the UI opens the right register.
* One loss event per incident: a second "Create loss event" is a 409, not a double count.
* A whistleblowing case-log status change moves the case, along its lifecycle.
* A completed, passing model validation moves the next validation date on by tier.

No DB: the endpoints run against small fakes.
"""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import incidents, model_risk, regulatory_change, shariah
from app.api.v1 import whistleblowing as wb
from app.models.control import Control
from app.models.enums import AssetClass, Criticality
from app.models.model_risk import ModelValidationStatus, ValidationOutcome
from app.models.policy import Policy
from app.models.regulatory_change import Obligation
from app.models.whistleblowing import WhistleStatus
from app.schemas.control import ControlRead
from app.schemas.incident import IncAssetRef, IncidentRead
from app.schemas.policy import PolicyRead
from app.schemas.regulatory_change import ObligationCreate
from app.schemas.shariah import ProductRead, ReviewRead, RulingRead
from app.schemas.whistleblowing import WhistleUpdateCreate

USER = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@bank.pk")


# ======================================================== nested obligation add ===
class _CaptureDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_adding_an_obligation_to_a_change_links_its_policies_and_controls(monkeypatch):
    change_id = uuid.uuid4()
    pol, ctl = Policy(id=uuid.uuid4(), title="AML policy"), Control(id=uuid.uuid4(), name="CDD")

    async def load_change(db, cid):
        return SimpleNamespace(id=cid, reference="RC-001")

    async def resolve(db, model, ids):
        return {Policy: [pol], Control: [ctl]}.get(model, []) if ids else []

    async def next_ref(db, model, prefix):
        return "OBL-009"

    async def no_audit(*a, **k):
        return None

    monkeypatch.setattr(regulatory_change, "_load_change", load_change)
    monkeypatch.setattr(regulatory_change, "_resolve", resolve)
    monkeypatch.setattr(regulatory_change, "_next_ref", next_ref)
    monkeypatch.setattr(regulatory_change.audit_log, "record", no_audit)
    monkeypatch.setattr(regulatory_change.RegulatoryChangeRead, "model_validate", classmethod(lambda cls, o: o))

    db = _CaptureDB()
    body = ObligationCreate(title="Report CTRs within 7 days", policy_ids=[pol.id], control_ids=[ctl.id])
    await regulatory_change.add_obligation(change_id, body, db, USER)
    (obl,) = [o for o in db.added if isinstance(o, Obligation)]
    assert obl.regulatory_change_id == change_id
    assert obl.policies == [pol] and obl.controls == [ctl] and obl.requirements == []
    assert obl.reference == "OBL-009"


# ================================================================ reverse links ===
def test_policies_and_controls_show_the_obligations_they_satisfy():
    assert "obligations" in PolicyRead.model_fields
    assert "obligations" in ControlRead.model_fields
    assert Policy.obligations.property.viewonly and Control.obligations.property.viewonly


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ScalarsDB:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, stmt):
        return _Rows(self.rows)

    async def refresh(self, obj, attribute_names=None):
        return None


def _ruling():
    return SimpleNamespace(
        id=uuid.uuid4(), reference="SR-001", title="Commodity murabaha", subject="", ruling_text="",
        basis="", status="approved", approved_by="Board", issued_date=None, review_frequency="annual",
        next_review_date=None, workflow_status="draft", is_review_overdue=False, created_at="2026-09-01T00:00:00Z",
        deleted=False,
    )


@pytest.mark.asyncio
async def test_a_ruling_lists_the_products_it_approves():
    product = SimpleNamespace(id=uuid.uuid4(), reference="IP-001", name="Home Musharakah", title="")
    out = await shariah._ruling_read(_ScalarsDB([product]), _ruling())
    assert isinstance(out, RulingRead)
    assert [(p.reference, p.name) for p in out.products] == [("IP-001", "Home Musharakah")]


@pytest.mark.asyncio
async def test_a_product_lists_its_reviews_and_names_its_approving_ruling():
    ruling = _ruling()
    product = SimpleNamespace(
        id=uuid.uuid4(), reference="IP-001", name="Home Musharakah", description="", shariah_mode="musharakah",
        structure="", status="in_development", owner="", launch_date=None, approving_ruling_id=ruling.id,
        approving_ruling=ruling, workflow_status="draft", created_at="2026-09-01T00:00:00Z",
    )
    review = SimpleNamespace(id=uuid.uuid4(), reference="SHR-001", title="Q3 product review", name="")
    out = await shariah._product_read(_ScalarsDB([review]), product)
    assert isinstance(out, ProductRead)
    assert out.approving_ruling.reference == "SR-001"
    assert [r.reference for r in out.reviews] == ["SHR-001"]
    assert "product" in ReviewRead.model_fields


# ================================================================ incident links ===
def test_an_incident_asset_link_carries_its_class():
    ref = IncAssetRef.model_validate(SimpleNamespace(id=uuid.uuid4(), name="Core banking DB",
                                                     asset_class=AssetClass.it_asset))
    assert ref.asset_class == AssetClass.it_asset
    assert IncidentRead.model_fields["assets"].annotation == list[IncAssetRef]


class _LossDB:
    def __init__(self, existing):
        self.existing = existing
        self.locked = False

    async def scalar(self, stmt):
        if "FOR UPDATE" in str(stmt.compile()):
            self.locked = True
            return None
        return self.existing


@pytest.mark.asyncio
async def test_a_second_loss_event_for_the_same_incident_is_refused(monkeypatch):
    inc = SimpleNamespace(id=uuid.uuid4(), near_miss=False, reference="INC-001")

    async def load(db, incident_id):
        return inc

    monkeypatch.setattr(incidents, "_load", load)
    db = _LossDB("LOSS-004")
    with pytest.raises(HTTPException) as exc:
        await incidents.create_loss_event(inc.id, db, USER)
    assert exc.value.status_code == 409 and "LOSS-004" in exc.value.detail
    assert db.locked  # two simultaneous clicks queue on the incident row


# ============================================================ whistleblowing log ===
def test_a_blank_status_change_is_a_plain_note():
    assert WhistleUpdateCreate(note="called reporter", status_change="").status_change is None
    assert WhistleUpdateCreate(status_change="triage").status_change == WhistleStatus.triage
    with pytest.raises(ValueError):
        WhistleUpdateCreate(status_change="whatever")


@pytest.mark.parametrize("current, new", [
    (WhistleStatus.received, WhistleStatus.triage),
    (WhistleStatus.triage, WhistleStatus.investigating),
    (WhistleStatus.investigating, WhistleStatus.substantiated),
    (WhistleStatus.investigating, WhistleStatus.unsubstantiated),
    (WhistleStatus.substantiated, WhistleStatus.closed),
    (WhistleStatus.received, WhistleStatus.closed),
    (WhistleStatus.closed, WhistleStatus.investigating),
])
def test_lifecycle_steps_are_allowed(current, new):
    wb.check_transition(current, new)


@pytest.mark.parametrize("current, new", [
    (WhistleStatus.received, WhistleStatus.substantiated),
    (WhistleStatus.triage, WhistleStatus.unsubstantiated),
    (WhistleStatus.closed, WhistleStatus.received),
    (WhistleStatus.substantiated, WhistleStatus.unsubstantiated),
])
def test_skipping_the_investigation_is_refused(current, new):
    with pytest.raises(HTTPException) as exc:
        wb.check_transition(current, new)
    assert exc.value.status_code == 422


def test_every_status_has_a_way_forward():
    assert set(wb.WHISTLE_TRANSITIONS) == set(WhistleStatus)


class _LogDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_a_case_log_status_change_moves_the_report_and_is_audited(monkeypatch):
    report = SimpleNamespace(id=uuid.uuid4(), reference="WB-001", status=WhistleStatus.received)
    audited = []

    async def load(db, rid):
        return report

    async def record(db, **kw):
        audited.append(kw)

    monkeypatch.setattr(wb, "_load_report", load)
    monkeypatch.setattr(wb.audit_log, "record", record)
    monkeypatch.setattr(wb.WhistleReportRead, "model_validate", classmethod(lambda cls, o: o))
    db = _LogDB()
    await wb.add_update(report.id, WhistleUpdateCreate(note="Assigned to IA", status_change="triage"), db, USER)
    assert report.status == WhistleStatus.triage
    (entry,) = db.added
    assert entry.status_change == "triage" and entry.update_date == date.today()
    assert audited and audited[0]["changes"] == {"status": {"from": "received", "to": "triage"}}

    with pytest.raises(HTTPException):  # already triage
        await wb.add_update(report.id, WhistleUpdateCreate(note="x", status_change="triage"), db, USER)


# ============================================================ model validation ===
def _model(tier, last=None, nxt=None):
    return SimpleNamespace(materiality=tier, last_validation_date=last, next_validation_date=nxt)


def _validation(d, status=ModelValidationStatus.completed, outcome=ValidationOutcome.pass_):
    return SimpleNamespace(validation_date=d, status=status, outcome=outcome)


@pytest.mark.parametrize("tier, expected", [
    (Criticality.critical, date(2027, 9, 1)),
    (Criticality.high, date(2027, 9, 1)),
    (Criticality.medium, date(2028, 9, 1)),
    (Criticality.low, date(2029, 9, 1)),
])
def test_a_passed_validation_sets_the_next_date_by_tier(tier, expected):
    m = _model(tier)
    model_risk.advance_validation_schedule(m, _validation(date(2026, 9, 1)))
    assert m.last_validation_date == date(2026, 9, 1) and m.next_validation_date == expected


def test_a_failed_validation_does_not_push_the_due_date_out():
    m = _model(Criticality.high, nxt=date(2026, 10, 1))
    model_risk.advance_validation_schedule(m, _validation(date(2026, 9, 1), outcome=ValidationOutcome.fail))
    assert m.last_validation_date == date(2026, 9, 1) and m.next_validation_date == date(2026, 10, 1)


def test_planned_and_backdated_validations_do_not_move_the_schedule():
    m = _model(Criticality.medium, last=date(2026, 6, 1), nxt=date(2028, 6, 1))
    model_risk.advance_validation_schedule(m, _validation(date(2026, 12, 1), status=ModelValidationStatus.planned))
    model_risk.advance_validation_schedule(m, _validation(date(2025, 1, 1)))
    assert m.last_validation_date == date(2026, 6, 1) and m.next_validation_date == date(2028, 6, 1)
