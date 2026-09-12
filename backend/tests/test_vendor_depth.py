"""Third-party record depth (product review F-11, plan §2.8).

No database: the pure rules are tested directly and the endpoints are driven with a
fake session, stubbed loaders and a captured audit trail.

Pinned here:

1. **Tiering** — the seeded "Inherent risk tiering" questionnaire (8 scored questions),
   score → tier bands, worst-case floors, unanswered questions refused, the latest
   completed assessment wins, and the tier proposes a criticality.
2. **Override needs a reason** — a criticality that differs from the tier's proposal
   is a 422 without ``tier_override_reason``; matching the proposal clears the reason;
   a write-back keeps a reasoned manual criticality and adopts the proposal otherwise.
3. **Due diligence** — a vendor can't be its own sub-contractor, spend and contract
   currencies default to the organisation's, contract totals are kept per currency,
   and the outsourcing facts of live arrangements surface on the vendor.
4. **Certifications** — fixed type list, expiry states, alerts 60 days out and after
   lapse, grouped as housekeeping.
5. **Outsourcing** — owner and country are pickers beside the legacy text.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import assessments as assessments_api
from app.api.v1 import outsourcing as outsourcing_api
from app.api.v1 import vendors as vendors_api
from app.db import reference_data
from app.models.enums import Criticality, NotificationCategory
from app.models.outsourcing import OutsourcingArrangement
from app.models.vendor import CERT_EXPIRY_WARNING_DAYS, certification_expiry_state
from app.schemas import outsourcing as outsourcing_s
from app.schemas import vendor as vendor_s
from app.services import audit as audit_service
from app.services import notifications as ns
from app.services import ref_fields as rf
from app.services import vendor_tiering as vt

TODAY = date(2026, 9, 12)


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit_service, "record", record)
    return calls


def _actor():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@bank.pk",
                           permission_codes=["vendor:read", "vendor:write"])


class FakeDB:
    def __init__(self, scalar=None, rows=None, get=None):
        self.scalar_result = scalar
        self.rows = rows or []
        self.tables = get or {}
        self.added: list = []
        self.deleted: list = []
        self.flushed = 0

    async def scalar(self, *_a, **_k):
        return self.scalar_result

    async def scalars(self, *_a, **_k):
        rows = self.rows
        return SimpleNamespace(all=lambda: rows)

    async def get(self, model, key):
        return self.tables.get(key)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flushed += 1


# ================================================================ fixtures ===
def _questionnaire(name=vt.TIERING_QUESTIONNAIRE_NAME, maxima=(3,) * 8):
    questions = []
    for i, m in enumerate(maxima):
        options = [SimpleNamespace(id=uuid.uuid4(), score=float(s)) for s in range(int(m) + 1)]
        questions.append(SimpleNamespace(id=uuid.uuid4(), options=options, order_index=i))
    return SimpleNamespace(id=uuid.uuid4(), name=name, questions=questions)


def _assessment(scores, *, questionnaire=None, status="submitted", submitted_at=TODAY, created_at=None):
    q = questionnaire or _questionnaire()
    answers = []
    for question, score in zip(q.questions, scores):
        option = None if score is None else next(o for o in question.options if o.score == score)
        answers.append(SimpleNamespace(question_id=question.id, option=option))
    return SimpleNamespace(
        id=uuid.uuid4(), title="Inherent risk tiering — 1LINK", questionnaire=q, answers=answers,
        status=SimpleNamespace(value=status), submitted_at=submitted_at,
        created_at=created_at or datetime(2026, 9, 1, tzinfo=timezone.utc), vendor_id=uuid.uuid4(),
    )


def _vendor(**kw):
    base = dict(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), name="1LINK (Pvt) Ltd", criticality=Criticality.medium,
        inherent_tier=None, tier_override_reason="", assessments=[], spend_currency="PKR",
        contracts=[], outsourcing_arrangements=[], data_residency_countries=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ============================================================ seeded questions ===
def test_the_seeded_tiering_questionnaire_has_eight_scored_questions():
    assert len(vt.TIERING_QUESTIONS) == 8
    texts = [t for t, _, _ in vt.TIERING_QUESTIONS]
    assert len(set(texts)) == 8
    for _, guidance, options in vt.TIERING_QUESTIONS:
        scores = [s for _, s in options]
        assert scores == sorted(scores) and scores[0] == 0 and scores[-1] == 3, scores
        assert guidance
    topics = " ".join(texts).lower()
    for word in ("data", "customers", "sbp", "provider", "concentrated", "access", "sub-contractors", "stored"):
        assert word in topics, word


async def test_the_questionnaire_is_seeded_once_per_tenant_and_never_overwritten():
    tid = uuid.uuid4()
    db = FakeDB(rows=["Vendor security questionnaire"])
    assert await reference_data.ensure_tiering_questionnaire(db, tid) == 1
    (q,) = db.added
    assert q.name == vt.TIERING_QUESTIONNAIRE_NAME and q.tenant_id == tid
    assert len(q.questions) == 8 and all(len(x.options) == 4 for x in q.questions)
    assert [x.order_index for x in q.questions] == list(range(8))
    assert max(o.score for o in q.questions[0].options) == 3

    renamed_case = FakeDB(rows=["  inherent RISK   tiering "])
    assert await reference_data.ensure_tiering_questionnaire(renamed_case, tid) == 0
    assert renamed_case.added == []


def test_the_questionnaire_is_recognised_ignoring_case_and_spacing():
    assert vt.is_tiering_questionnaire(SimpleNamespace(name="Inherent  Risk tiering "))
    assert not vt.is_tiering_questionnaire(SimpleNamespace(name="Vendor security questionnaire"))
    assert not vt.is_tiering_questionnaire(None)


# =============================================================== score → tier ===
@pytest.mark.parametrize("pct,tier", [
    (0, "low"), (19.9, "low"), (20, "medium"), (44.9, "medium"),
    (45, "high"), (69.9, "high"), (70, "critical"), (100, "critical"),
])
def test_score_bands(pct, tier):
    assert vt.band_for(pct) == tier


@pytest.mark.parametrize("scores,tier,floored", [
    ([0] * 8, "low", False),
    ([1] * 8, "medium", False),                  # 8/24 = 33.3%
    ([3] + [0] * 7, "medium", True),             # 12.5% is low; one worst case lifts it
    ([3, 3, 0, 0, 0, 0, 0, 0], "medium", False),  # 25% is medium on its own; two worst cases add nothing
    ([3, 0, 0, 0, 0, 0, 0, 1], "medium", True),   # 16.7% is low; the worst case lifts it
    ([3, 3, 3, 0, 0, 0, 0, 0], "high", True),    # 37.5% is medium; three worst cases lift it
    ([2] * 8, "high", False),                    # 16/24 = 66.7%
    ([3, 3, 3, 2, 2, 2, 2, 1], "critical", False),  # 18/24 = 75%
    ([3] * 8, "critical", False),
])
def test_derive_tier(scores, tier, floored):
    result = vt.derive_tier([(float(s), 3.0) for s in scores])
    assert result.tier == tier and result.floor_applied is floored
    assert result.max_score == 24 and result.total_score == sum(scores)
    assert result.proposed_criticality == tier


def test_the_explanation_says_how_the_tier_was_reached():
    result = vt.derive_tier([(3.0, 3.0)] * 3 + [(0.0, 3.0)] * 5)
    assert result.explanation() == "9 of 24 (37.5%) is medium; raised to high by 3 worst-case answers"
    assert vt.derive_tier([(2.0, 3.0)] * 8).explanation() == "16 of 24 (66.7%) is high"


def test_a_question_worth_nothing_is_never_a_worst_case():
    result = vt.derive_tier([(0.0, 0.0), (0.0, 3.0)])
    assert result.worst_case_answers == 0 and result.tier == "low"


def test_nothing_to_score_is_refused():
    with pytest.raises(vt.TieringError):
        vt.derive_tier([])


def test_every_question_must_be_answered():
    a = _assessment([3, 2, None, 1, None, 0, 0, 0])
    with pytest.raises(vt.TieringError) as exc:
        vt.tier_assessment(a)
    assert "2 of 8 tiering questions are unanswered" in str(exc.value)


def test_only_a_completed_tiering_assessment_yields_a_tier():
    with pytest.raises(vt.TieringError, match="not completed"):
        vt.tier_assessment(_assessment([0] * 8, status="in_progress"))
    other = _questionnaire(name="Vendor security questionnaire")
    with pytest.raises(vt.TieringError, match="does not use"):
        vt.tier_assessment(_assessment([0] * 8, questionnaire=other))
    assert vt.tier_assessment(_assessment([2] * 8, status="reviewed")).tier == "high"


def test_a_re_weighted_questionnaire_keeps_the_same_bands():
    q = _questionnaire(maxima=(6, 6, 3, 3, 3, 3, 3, 3))  # heavier data and customer questions
    result = vt.tier_assessment(_assessment([6, 6, 0, 0, 0, 0, 0, 0], questionnaire=q))
    assert (result.total_score, result.max_score, result.score_pct) == (12, 30, 40.0)
    assert result.tier == "medium" and result.worst_case_answers == 2


def test_the_latest_completed_tiering_assessment_wins():
    older = _assessment([0] * 8, submitted_at=date(2026, 1, 5))
    newer = _assessment([3] * 8, submitted_at=date(2026, 8, 1))
    draft = _assessment([1] * 8, status="draft", submitted_at=None)
    unrelated = _assessment([0] * 8, questionnaire=_questionnaire(name="SIG Lite"), submitted_at=date(2026, 9, 1))
    assert vt.latest_completed([older, draft, newer, unrelated]) is newer
    assert vt.latest_completed([draft, unrelated]) is None


# ======================================================== criticality rule ===
def test_without_a_tier_criticality_is_entirely_manual():
    assert vt.resolve_criticality(tier=None, stored_criticality="low", stored_reason="",
                                  sent={"criticality": Criticality.critical}) == ("critical", None)


def test_overriding_the_proposed_criticality_needs_a_reason():
    with pytest.raises(vt.TieringError) as exc:
        vt.resolve_criticality(tier="high", stored_criticality="high", stored_reason="",
                               sent={"criticality": Criticality.critical})
    assert str(exc.value).startswith("tier_override_reason:") and "high proposes high" in str(exc.value)
    with pytest.raises(vt.TieringError):
        vt.resolve_criticality(tier="high", stored_criticality="high", stored_reason="",
                               sent={"criticality": "low", "tier_override_reason": "   "})


def test_an_override_with_a_reason_is_accepted_and_trimmed():
    assert vt.resolve_criticality(
        tier="high", stored_criticality="high", stored_reason="",
        sent={"criticality": "critical", "tier_override_reason": " Sole RAAST switch provider "},
    ) == ("critical", "Sole RAAST switch provider")


def test_a_reason_already_on_record_covers_a_resave():
    assert vt.resolve_criticality(tier="high", stored_criticality="critical", stored_reason="Board decision",
                                  sent={"criticality": "critical"}) == ("critical", None)


def test_returning_to_the_proposal_clears_the_reason():
    assert vt.resolve_criticality(tier="high", stored_criticality="critical", stored_reason="Board decision",
                                  sent={"criticality": "high"}) == ("high", "")


def test_a_write_back_adopts_the_proposal_unless_an_override_is_reasoned():
    result = vt.derive_tier([(2.0, 3.0)] * 8)  # high
    v = _vendor(criticality=Criticality.low)
    changes = vt.apply_tier(v, result, Criticality)
    assert v.inherent_tier == "high" and v.criticality is Criticality.high
    assert changes == {"inherent_tier": {"from": None, "to": "high"}, "criticality": {"from": "low", "to": "high"}}

    kept = _vendor(criticality=Criticality.critical, tier_override_reason="Sole card switch")
    changes = vt.apply_tier(kept, result, Criticality)
    assert kept.criticality is Criticality.critical and kept.tier_override_reason == "Sole card switch"
    assert list(changes) == ["inherent_tier"]

    stale = _vendor(criticality=Criticality.high, tier_override_reason="Old reason", inherent_tier="medium")
    changes = vt.apply_tier(stale, result, Criticality)
    assert stale.tier_override_reason == "" and "tier_override_reason" in changes


async def test_write_back_is_audited(audit_calls):
    v = _vendor()
    a = _assessment([3, 3, 3, 0, 0, 0, 0, 0])
    result = await vt.write_back(FakeDB(), v, a, _actor())
    assert result.tier == "high" and v.inherent_tier == "high" and v.criticality is Criticality.high
    (call,) = audit_calls
    assert (call["action"], call["entity_type"], call["entity_id"]) == ("tier", "vendor", v.id)
    assert "Inherent risk tier of 1LINK (Pvt) Ltd: high" in call["summary"]
    assert "raised to high by 3 worst-case answers" in call["summary"]
    assert call["changes"]["assessment_id"] == str(a.id)


# ================================================== vendor update endpoint ===
@pytest.fixture
def vendor_endpoint(monkeypatch):
    v = _vendor(inherent_tier="high", criticality=Criticality.high)

    async def load(db, _id):
        return v

    async def read(db, _id):
        return v

    async def currency(db, tenant_id):
        return "PKR"

    monkeypatch.setattr(vendors_api, "_load", load)
    monkeypatch.setattr(vendors_api, "_read", read)
    monkeypatch.setattr(vendors_api, "_org_currency", currency)
    return v


async def test_update_refuses_an_unreasoned_override(vendor_endpoint, audit_calls):
    with pytest.raises(HTTPException) as exc:
        await vendors_api.update_vendor(vendor_endpoint.id, vendor_s.VendorUpdate(criticality="critical"),
                                        FakeDB(), _actor())
    assert exc.value.status_code == 422 and exc.value.detail.startswith("tier_override_reason:")
    assert vendor_endpoint.criticality is Criticality.high and audit_calls == []


async def test_update_records_a_reasoned_override(vendor_endpoint, audit_calls):
    body = vendor_s.VendorUpdate(criticality="critical", tier_override_reason="Sole provider of RAAST connectivity")
    await vendors_api.update_vendor(vendor_endpoint.id, body, FakeDB(), _actor())
    assert vendor_endpoint.criticality == Criticality.critical
    assert vendor_endpoint.tier_override_reason == "Sole provider of RAAST connectivity"
    (call,) = audit_calls
    assert call["changes"]["criticality"] == {"from": "high", "to": "critical"}
    assert "overrides the high proposed by its high inherent tier" in call["summary"]


async def test_update_blank_spend_currency_means_the_organisations(vendor_endpoint, audit_calls):
    await vendors_api.update_vendor(vendor_endpoint.id, vendor_s.VendorUpdate(spend_currency=""), FakeDB(), _actor())
    assert vendor_endpoint.spend_currency == "PKR"


async def test_a_vendor_cannot_be_its_own_subcontractor(vendor_endpoint, audit_calls):
    with pytest.raises(HTTPException) as exc:
        await vendors_api.update_vendor(
            vendor_endpoint.id, vendor_s.VendorUpdate(subcontractor_ids=[vendor_endpoint.id]), FakeDB(), _actor()
        )
    assert exc.value.status_code == 422 and "own sub-contractor" in exc.value.detail
    vendors_api.check_subcontractors(uuid.uuid4(), [uuid.uuid4()])  # someone else is fine
    vendors_api.check_subcontractors(None, [uuid.uuid4()])  # a new vendor has no id yet


async def test_recompute_without_a_completed_tiering_is_a_422(vendor_endpoint, audit_calls):
    with pytest.raises(HTTPException) as exc:
        await vendors_api.recompute_tiering(vendor_endpoint.id, FakeDB(), _actor())
    assert exc.value.status_code == 422 and "no completed 'Inherent risk tiering'" in exc.value.detail


async def test_recompute_writes_the_tier_from_the_latest_assessment(vendor_endpoint, audit_calls):
    vendor_endpoint.inherent_tier = None
    vendor_endpoint.assessments = [_assessment([0] * 8, submitted_at=date(2026, 1, 1)),
                                   _assessment([3] * 8, submitted_at=date(2026, 9, 1))]
    await vendors_api.recompute_tiering(vendor_endpoint.id, FakeDB(), _actor())
    assert vendor_endpoint.inherent_tier == "critical" and vendor_endpoint.criticality is Criticality.critical
    assert audit_calls[0]["action"] == "tier"


async def test_create_defaults_the_spend_currency(monkeypatch, audit_calls):
    created = {}

    async def read(db, _id):
        return created.setdefault("v", db.added[0])

    async def currency(db, tenant_id):
        return "PKR"

    monkeypatch.setattr(vendors_api, "_read", read)
    monkeypatch.setattr(vendors_api, "_org_currency", currency)
    db = FakeDB()
    v = await vendors_api.create_vendor(vendor_s.VendorCreate(name="Systems Ltd", annual_spend=12_500_000),
                                        db, _actor())
    assert v.spend_currency == "PKR" and float(v.annual_spend) == 12_500_000
    created.clear()
    db = FakeDB()
    v = await vendors_api.create_vendor(vendor_s.VendorCreate(name="AWS", spend_currency="usd"), db, _actor())
    assert v.spend_currency == "USD"


# ============================================================== read blocks ===
def _contract(value, currency="", expired=False):
    return SimpleNamespace(value=value, currency=currency, is_expired=expired)


def test_contract_totals_are_kept_per_currency():
    totals = vendors_api.contract_totals(
        [_contract(1_000_000, "PKR"), _contract(250_000, ""), _contract(12_000, "USD"),
         _contract(99, "USD", expired=True), _contract(None, "EUR")],
        "PKR",
    )
    assert totals == {"PKR": 1_250_000, "USD": 12_000}


def _arrangement(**kw):
    base = dict(
        id=uuid.uuid4(), reference="OUT-3", title="Core banking hosting", deleted=False,
        status=SimpleNamespace(value="active"), materiality=SimpleNamespace(value="material"),
        is_cloud=True, data_offshored=True, country_id=None, country="UAE",
        sbp_approval_status=SimpleNamespace(value="approved"), contract_end=date(2027, 6, 30),
        exit_plan="Migrate to the Karachi DR site", exit_plan_tested=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_outsourcing_facts_of_live_arrangements_surface_on_the_vendor():
    uae = uuid.uuid4()
    facts = vendors_api.outsourcing_facts(
        [_arrangement(country_id=uae), _arrangement(deleted=True), _arrangement(country_id=None, country="Singapore")],
        {uae: SimpleNamespace(label="United Arab Emirates")},
    )
    assert [f.country for f in facts] == ["United Arab Emirates", "Singapore"]
    assert facts[0].materiality == "material" and facts[0].data_offshored and not facts[0].exit_plan_tested
    assert facts[0].exit_plan == "Migrate to the Karachi DR site"


def test_the_tiering_view_explains_the_tier_and_flags_a_stale_or_unscorable_one():
    qid = uuid.uuid4()
    none = vendors_api.tiering_view(_vendor(), qid)
    assert none.tier is None and none.assessment is None and none.questionnaire_id == qid

    v = _vendor(inherent_tier="medium", criticality=Criticality.critical, tier_override_reason="Board call",
                assessments=[_assessment([2] * 8)])
    view = vendors_api.tiering_view(v)
    assert view.overridden and view.override_reason == "Board call" and view.proposed_criticality == "medium"
    assert view.score_pct == 66.7 and view.explanation == "16 of 24 (66.7%) is high"
    assert view.stale  # the latest assessment now says high, the stored tier is medium

    broken = vendors_api.tiering_view(_vendor(inherent_tier="low", assessments=[_assessment([0, None] + [0] * 6)]))
    assert broken.stale and "unanswered" in broken.problem


# =========================================================== certifications ===
@pytest.mark.parametrize("days,state", [
    (None, "no_expiry"), (61, "valid"), (CERT_EXPIRY_WARNING_DAYS, "expiring"), (0, "expiring"), (-1, "expired"),
])
def test_certification_expiry_states(days, state):
    expires = None if days is None else TODAY + timedelta(days=days)
    assert certification_expiry_state(expires, TODAY) == state


def test_certification_types_come_from_a_fixed_list():
    assert vendor_s.VendorCertificationCreate(cert_type="SOC 2 Type II").cert_type == "soc2_type2"
    assert vendor_s.VendorCertificationCreate(cert_type="iso_27001").cert_type == "iso_27001"
    assert set(vendor_s.CERT_TYPES.values()) == {
        "ISO 27001", "ISO 22301", "SOC 1", "SOC 2 Type I", "SOC 2 Type II", "PCI DSS", "CSA STAR", "Other",
    }
    with pytest.raises(ValidationError):
        vendor_s.VendorCertificationCreate(cert_type="ISO 9001")
    read = vendor_s.VendorCertificationRead(id=uuid.uuid4(), vendor_id=uuid.uuid4(), cert_type="pci_dss")
    assert read.cert_type_label == "PCI DSS"


def test_a_certificate_cannot_expire_before_it_was_issued():
    with pytest.raises(HTTPException) as exc:
        vendors_api.check_cert_dates(date(2026, 5, 1), date(2025, 5, 1))
    assert exc.value.status_code == 422
    vendors_api.check_cert_dates(date(2025, 5, 1), date(2028, 5, 1))
    vendors_api.check_cert_dates(None, date(2028, 5, 1))


async def test_certification_crud_is_audited(monkeypatch, audit_calls):
    v = _vendor(certifications=[])

    async def load(db, _id):
        return v

    monkeypatch.setattr(vendors_api, "_load", load)
    db = FakeDB()
    body = vendor_s.VendorCertificationCreate(cert_type="ISO 27001", issuer="BSI", expires_on=date(2027, 3, 31))
    read = await vendors_api.add_certification(v.id, body, db, _actor())
    cert = db.added[0]
    assert read.cert_type == "iso_27001" and cert.vendor_id == v.id and cert.tenant_id == v.tenant_id

    async def load_cert(db, vendor_id, cert_id):
        return cert

    monkeypatch.setattr(vendors_api, "_load_cert", load_cert)
    await vendors_api.update_certification(
        v.id, cert.id, vendor_s.VendorCertificationUpdate(expires_on=date(2028, 3, 31)), db, _actor()
    )
    assert cert.expires_on == date(2028, 3, 31)
    with pytest.raises(HTTPException):
        await vendors_api.update_certification(
            v.id, cert.id, vendor_s.VendorCertificationUpdate(issued_on=date(2029, 1, 1)), db, _actor()
        )
    await vendors_api.delete_certification(v.id, cert.id, db, _actor())
    assert db.deleted == [cert]
    assert [c["action"] for c in audit_calls] == ["add_certification", "update_certification", "delete_certification"]
    assert "ISO 27001 certification of 1LINK (Pvt) Ltd, expires 2027-03-31" in audit_calls[0]["summary"]
    assert audit_calls[1]["changes"]["expires_on"] == {"from": "2027-03-31", "to": "2028-03-31"}


def _cert(days, cert_type="soc2_type2"):
    return SimpleNamespace(id=uuid.uuid4(), cert_type=cert_type, expires_on=TODAY + timedelta(days=days))


def test_certification_alerts():
    v = _vendor(criticality=Criticality.low)
    key, title, body, category, etype, eid, link = ns.certification_alert(_cert(30), v, TODAY)
    assert key.startswith("vendor-cert-expiring:") and title == "Certification expiring: 1LINK (Pvt) Ltd SOC 2 Type II"
    assert "30 day(s) left" in body and category == NotificationCategory.warning and (etype, eid) == ("vendor", v.id)
    expired = ns.certification_alert(_cert(-3, "pci_dss"), v, TODAY)
    assert expired[0].startswith("vendor-cert-expired:") and expired[3] == NotificationCategory.warning
    critical = _vendor(criticality=Criticality.critical)
    assert ns.certification_alert(_cert(-3), critical, TODAY)[3] == NotificationCategory.critical
    assert ns.certification_alert(_cert(90), v, TODAY) is None


def test_certification_alerts_are_groupable_housekeeping():
    for fam in ("vendor-cert-expiring", "vendor-cert-expired"):
        assert fam in ns.GROUPABLE_FAMILIES and fam not in ns.NEVER_GROUPED
    v = _vendor()
    alerts = []
    for _ in range(6):
        key, title, body, category, etype, eid, link = ns.certification_alert(_cert(10), v, TODAY)
        alerts.append(dict(dedup_key=key, title=title, body=body, category=category,
                           entity_type=etype, entity_id=eid, link=link))
    (grouped,) = ns.group_alerts(alerts)
    assert grouped["title"] == "6 third-party certifications have less than 60 days left"
    assert grouped["link"] == "/vendors"


# ================================================================ schemas ===
def test_due_diligence_fields_are_written_by_id_and_read_with_refs():
    create, update, read = (vendor_s.VendorCreate.model_fields, vendor_s.VendorUpdate.model_fields,
                            vendor_s.VendorRead.model_fields)
    written = {"legal_name", "registration_number", "relationship_owner_id", "data_classification_id",
               "annual_spend", "spend_currency", "process_ids", "subcontractor_ids", "data_residency_country_ids"}
    assert written <= set(create) and written <= set(update)
    assert {"relationship_owner_ref", "data_classification_ref", "data_residency_countries", "processes",
            "subcontractors", "subcontractor_of", "certifications", "inherent_tier", "tiering", "outsourcing",
            "active_contract_totals"} <= set(read)
    # The tier is derived only; the override reason is an edit, never a create.
    assert "inherent_tier" not in create and "inherent_tier" not in update
    assert "tier_override_reason" in update and "tier_override_reason" not in create


def test_currencies_are_iso_codes_or_blank():
    assert vendor_s.ServiceContractCreate(name="MSA", currency="usd").currency == "USD"
    assert vendor_s.ServiceContractCreate(name="MSA").currency == ""
    with pytest.raises(ValidationError):
        vendor_s.ServiceContractCreate(name="MSA", currency="Rupees")
    with pytest.raises(ValidationError):
        vendor_s.VendorUpdate(spend_currency="XYZ")


def test_due_diligence_pickers_are_declared_with_their_lists():
    kinds = {f.id_field: (f.kind, f.lookup_key, f.text_field) for f in vendors_api.DUE_DILIGENCE_REFS}
    assert kinds == {"relationship_owner_id": ("user", None, None),
                     "data_classification_id": ("lookup", "data_classification", None)}
    assert {f.ref_name for f in vendors_api.ALL_REFS} <= set(vendor_s.VendorRead.model_fields)


# ============================================================== outsourcing ===
def test_outsourcing_owner_and_country_are_pickers_beside_the_legacy_text():
    for schema in (outsourcing_s.OutsourcingArrangementCreate, outsourcing_s.OutsourcingArrangementUpdate):
        assert {"owner_id", "country_id", "owner", "country"} <= set(schema.model_fields)
    assert {"owner_ref", "country_ref"} <= set(outsourcing_s.OutsourcingArrangementRead.model_fields)
    columns = OutsourcingArrangement.__table__.c
    for f in outsourcing_api.OUTSOURCING_REFS:
        assert f.id_field in columns and f.text_field in columns
    assert [(f.kind, f.lookup_key) for f in outsourcing_api.OUTSOURCING_REFS] == [("user", None), ("lookup", "country")]


async def test_a_picked_owner_and_country_write_their_names_into_the_legacy_text():
    ayesha = SimpleNamespace(id=uuid.uuid4(), full_name="Ayesha Siddiqui", email="ayesha@bank.pk", is_active=True)
    uae = SimpleNamespace(id=uuid.uuid4(), key="country", value="ae", label="United Arab Emirates", active=True)
    data = {"owner_id": ayesha.id, "owner": "", "country_id": uae.id, "country": "Dubai"}
    await rf.apply_refs(FakeDB(get={ayesha.id: ayesha, uae.id: uae}), OutsourcingArrangement, data,
                        outsourcing_api.OUTSOURCING_REFS)
    assert data == {"owner_id": ayesha.id, "owner": "Ayesha Siddiqui",
                    "country_id": uae.id, "country": "United Arab Emirates"}


async def test_outsourcing_update_is_audited(monkeypatch, audit_calls):
    arr = SimpleNamespace(id=uuid.uuid4(), reference="OUT-7", title="Card switch", vendor_id=None,
                          owner_id=None, owner="", country_id=None, country="", exit_plan_tested=False)

    async def load(db, _id):
        return arr

    async def read(db, _id):
        return arr

    monkeypatch.setattr(outsourcing_api, "_load_arrangement", load)
    monkeypatch.setattr(outsourcing_api, "_arr_read", read)
    await outsourcing_api.update_arrangement(
        arr.id, outsourcing_s.OutsourcingArrangementUpdate(exit_plan_tested=True, status=None), FakeDB(), _actor()
    )
    assert arr.exit_plan_tested is True and not hasattr(arr, "status")
    assert [(c["action"], c["entity_type"]) for c in audit_calls] == [("update", "outsourcing_arrangement")]


# ============================================================ assessments hook ===
async def test_completing_a_tiering_assessment_writes_the_vendor_tier(audit_calls):
    v = _vendor()
    a = _assessment([2] * 8)
    a.vendor_id = v.id
    await assessments_api._tier_vendor(FakeDB(scalar=v), a, _actor())
    assert v.inherent_tier == "high" and audit_calls[0]["action"] == "tier"


async def test_other_questionnaires_and_open_assessments_leave_the_vendor_alone(audit_calls):
    v = _vendor()
    for a in (_assessment([3] * 8, questionnaire=_questionnaire(name="SIG Lite")),
              _assessment([3] * 8, status="in_progress")):
        await assessments_api._tier_vendor(FakeDB(scalar=v), a, _actor())
    assert v.inherent_tier is None and audit_calls == []


async def test_a_tiering_assessment_with_blanks_cannot_be_completed(audit_calls):
    v = _vendor()
    a = _assessment([2, None] + [2] * 6)
    with pytest.raises(HTTPException) as exc:
        await assessments_api._tier_vendor(FakeDB(scalar=v), a, _actor())
    assert exc.value.status_code == 422 and "1 of 8 tiering question is unanswered" in exc.value.detail
    assert v.inherent_tier is None
