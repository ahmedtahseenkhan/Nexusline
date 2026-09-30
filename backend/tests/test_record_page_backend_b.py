"""Record-page backend, part B (spec §3.6: B2, B3, B6, B7, B8, B10a, B12).

No database: the pure builders are tested directly, the loaders with a fake session that
counts its queries, and the accept-residual endpoint with stubbed loaders and a captured
audit trail (the pattern of ``test_risk_integrity``).

Pinned here:

* **B2** A risk's controls carry their rating, its basis and their test record — counted
  from reviewed (or pre-review) conclusive tests only, two queries for any number of
  controls — and the list, which does not compute them, never passes off the row's
  unreviewed counts as assurance.
* **B3** Exception refs on risk, control, asset and policy carry status and expiry; an
  approved exception past its expiry reads ``expired``. ``GraphRef`` itself is unchanged.
* **B6** Accepting a suggestion that takes credit from an untested rating needs a note,
  which lands in the stored rationale and the audit trail.
* **B7** A control's clauses name their framework without lazy-loading it.
* **B8** An asset's risks carry scores, bands and appetite status (the dashboard's rules),
  only for a viewer who may read risks; dependencies carry the business value.
* **B10a** Installing a controls pack no longer writes the framework name as the
  control's classification.
* **B12** The suggested residual says which appetite band it would fall in — and which
  controls it credits and whether accepting it needs a note (B6), from the same rule the
  accept call enforces.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.v1 import assets as assets_api
from app.api.v1 import controls as controls_api
from app.api.v1 import risks as risks_api
from app.models.compliance import Requirement
from app.models.control import Control
from app.models.enums import (
    AssetClass,
    ControlEffectiveness as E,
    ControlStatus,
    Criticality,
    ExceptionStatus,
    RiskStatus,
    Severity,
    TestResult as R,
)
from app.models.exception import ExceptionRecord
from app.schemas.asset import AssetRead, ExceptionLinkRef, RiskExposureRef
from app.schemas.common import ExceptionRef, GraphRef, exception_status
from app.schemas.control import ControlAssuranceRef, ControlRead, RequirementLinkRef
from app.schemas.policy import PolicyRead
from app.schemas.risk import (
    UNTESTED_CREDIT_NOTE_NEEDED,
    ResidualAcceptance,
    RiskRead,
    SuggestedResidual,
)
from app.services import framework_library as fl
from app.services.residual_engine import ControlInput, ResidualPolicySpec, suggest_residual
from app.services.risk_scoring import AppetiteBook, SeverityScale

async def _no_review_policy(db, user):
    from app.services.risk_scoring import SeverityScale

    return SeverityScale(), {}


async def _no_alert_refresh(db, user, risk):
    return None


TODAY = date.today()
AGO = lambda days: TODAY - timedelta(days=days)  # noqa: E731


def _user(perms=("risk:read", "risk:write")):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x", permission_codes=list(perms))


def _test(result=R.passed, review="reviewed", days_ago=10, test_type="operating", control_id=None):
    when = AGO(days_ago)
    return SimpleNamespace(
        control_id=control_id, result=result, review_status=review, test_type=test_type,
        conducted_date=when, created_at=datetime(when.year, when.month, when.day, 9, tzinfo=timezone.utc),
    )


def _control(**kw):
    base = dict(
        id=uuid.uuid4(), name="Backup & Recovery", reference="A.8.13",
        effectiveness=E.effective, effectiveness_override_reason="",
        status=ControlStatus.operational, next_audit_date=AGO(-90),
        # What the residual engine reads (the row's own, unreviewed view).
        last_audit_result=None, is_audit_overdue=False, audit_findings=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    """Answers ``execute`` from a queue of row lists and keeps the statements."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.statements = []
        self.flushed = 0

    async def execute(self, stmt, *_a, **_k):
        self.statements.append(stmt)
        return _Result(self.answers.pop(0) if self.answers else [])

    async def flush(self):
        self.flushed += 1


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


# ======================================================================== B2 ===
def test_only_reviewed_or_legacy_conclusive_tests_count():
    c = _control()
    ref = risks_api.control_assurance_ref(c, [
        _test(R.passed, "legacy", days_ago=200),
        _test(R.passed, "reviewed", days_ago=40),
        _test(R.failed, "pending", days_ago=5),      # the tester's claim, not assurance
        _test(R.failed, "returned", days_ago=3),     # sent back: not assurance either
        _test(R.not_assessed, "legacy", days_ago=1),  # a placeholder, not a test
    ], open_issue_count=2, today=TODAY)
    assert ref.audit_count == 2
    assert (ref.last_audit_result, ref.last_audit_date) == (R.passed, AGO(40))
    assert ref.effectiveness_basis == "tests"
    assert ref.effectiveness == E.effective
    assert ref.open_issue_count == 2
    assert (ref.next_audit_date, ref.is_audit_overdue) == (AGO(-90), False)


def test_the_latest_counting_test_of_either_kind_is_the_last_result():
    ref = risks_api.control_assurance_ref(_control(), [
        _test(R.passed, days_ago=30, test_type="operating"),
        _test(R.failed, days_ago=8, test_type="design"),
    ])
    assert (ref.last_audit_result, ref.last_audit_date, ref.audit_count) == (R.failed, AGO(8), 2)


@pytest.mark.parametrize(
    "kw,tests,basis",
    [
        (dict(effectiveness=E.effective), [], "manual"),            # rated by hand, never tested
        (dict(effectiveness=E.not_assessed), [], "none"),
        (dict(effectiveness_override_reason="CRO call"), [_test()], "override"),
        (dict(), [_test(R.passed, "pending")], "manual"),            # only an unreviewed test
    ],
)
def test_the_basis_follows_the_phase_2_derivation(kw, tests, basis):
    assert risks_api.control_assurance_ref(_control(**kw), tests).effectiveness_basis == basis


def test_the_test_clock_is_the_controls_own_and_planned_controls_have_none():
    overdue = risks_api.control_assurance_ref(_control(next_audit_date=AGO(3)), [], today=TODAY)
    assert (overdue.is_audit_overdue, overdue.next_audit_date) == (True, AGO(3))
    planned = risks_api.control_assurance_ref(
        _control(status=ControlStatus.planned, next_audit_date=AGO(3)), [], today=TODAY
    )
    assert (planned.is_audit_overdue, planned.next_audit_date) == (False, None)


@pytest.mark.parametrize(
    "basis,count,untested",
    [("tests", 2, False), ("manual", 0, True), ("override", 3, True), ("none", 0, True), ("tests", 0, True)],
)
def test_what_counts_as_an_untested_rating(basis, count, untested):
    ref = ControlAssuranceRef(id=uuid.uuid4(), name="x", reference="C-1", effectiveness_basis=basis, audit_count=count)
    assert risks_api.rests_on_untested_rating(ref) is untested


async def test_assurance_takes_two_queries_whatever_the_number_of_controls():
    a, b, c = _control(reference="A.8.13"), _control(reference="A.5.15"), _control(reference="A.8.2")
    db = FakeDB(
        [_test(R.passed, control_id=a.id), _test(R.failed, "pending", control_id=a.id), _test(R.passed, control_id=b.id)],
        [(a.id, 1)],
    )
    refs = await risks_api._assured_controls(db, [a, b, c])
    assert len(db.statements) == 2
    assert [(r.reference, r.audit_count, r.open_issue_count) for r in refs] == [
        ("A.8.13", 1, 1), ("A.5.15", 1, 0), ("A.8.2", 0, 0),
    ]
    tests_sql, issues_sql = map(_sql, db.statements)
    assert "control_audits.control_id IN" in tests_sql
    # Open issues only: live, not closed, remediated or accepted.
    assert "issues.deleted IS false" in issues_sql
    assert "NOT IN" in issues_sql and "GROUP BY issue_controls.control_id" in issues_sql


async def test_no_controls_no_queries():
    db = FakeDB()
    assert await risks_api._assured_controls(db, []) == []
    assert db.statements == []


def test_the_list_never_reads_assurance_off_the_row():
    """``Control.audit_count`` counts unreviewed tests; the ref must not borrow it."""
    control = Control(id=uuid.uuid4(), name="Backup", reference="A.8.13", effectiveness=E.effective)
    ref = ControlAssuranceRef.model_validate(control)
    assert (ref.reference, ref.effectiveness, ref.audit_count, ref.effectiveness_basis) == ("A.8.13", None, None, None)
    assert RiskRead.model_fields["controls"].annotation == list[ControlAssuranceRef]


# ======================================================================== B3 ===
def test_exception_status_reads_expired_once_an_approval_lapses():
    assert exception_status(ExceptionStatus.approved, AGO(1), TODAY) == "expired"
    assert exception_status(ExceptionStatus.approved, TODAY, TODAY) == "approved"
    assert exception_status(ExceptionStatus.approved, None, TODAY) == "approved"
    assert exception_status(ExceptionStatus.pending, AGO(30), TODAY) == "pending"
    assert exception_status(None, None) is None


def test_exception_refs_carry_status_and_expiry_from_the_row():
    lapsed = ExceptionRecord(id=uuid.uuid4(), reference="EXC-001", title="Legacy TLS",
                             status=ExceptionStatus.approved, expires_at=AGO(2))
    current = ExceptionRecord(id=uuid.uuid4(), reference="EXC-002", title="Vendor SSO",
                              status=ExceptionStatus.approved, expires_at=AGO(-30))
    assert ExceptionRef.model_validate(lapsed).model_dump(include={"reference", "status", "expires_at"}) == {
        "reference": "EXC-001", "status": "expired", "expires_at": AGO(2),
    }
    assert ExceptionRef.model_validate(current).status == "approved"
    # Every record read that lists exceptions uses the richer ref …
    for model in (RiskRead, ControlRead, PolicyRead):
        assert model.model_fields["exceptions"].annotation == list[ExceptionRef], model.__name__
    assert AssetRead.model_fields["exceptions"].annotation == list[ExceptionLinkRef]
    # … and GraphRef, read from dozens of models with a status of their own, is untouched.
    assert set(GraphRef.model_fields) == {"id", "reference", "title", "name"}


def test_asset_exception_refs_carry_status_and_expiry():
    x = SimpleNamespace(id=uuid.uuid4(), reference="EXC-003", title="t", status=ExceptionStatus.approved, expires_at=AGO(5))
    ref = assets_api._exception_ref(x)
    assert (ref.label, ref.status, ref.expires_at) == ("EXC-003", "expired", AGO(5))


# ======================================================================== B6 ===
@pytest.fixture
def audit_log(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(risks_api.audit, "record", record)
    return calls


def _risk(controls, **kw):
    base = dict(
        id=uuid.uuid4(), reference="R-002", title="Data loss", category_id=None,
        inherent_likelihood=4, inherent_impact=5, inherent_score=20,
        residual_likelihood=None, residual_impact=None, residual_score=None,
        target_likelihood=None, target_impact=None,
        status=RiskStatus.assessed, assessment_rationale="Scored at the RCSA",
        last_assessed_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        residual_override_reason="", needs_review=False, review_reason="", controls=controls,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def stub(monkeypatch):
    """Loaders stubbed; the real residual engine runs with the default policy."""
    state = {}

    async def load(db, risk_id):
        return state["risk"]

    async def read(db, risk_id, user):
        return state["risk"]

    async def size(db, tenant_id):
        return 5

    async def policy(db, tenant_id):
        return None

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api, "_read", read)
    monkeypatch.setattr(risks_api, "get_matrix_size", size)
    # F-22: the review clock and the alert refresh need the tenant's settings and the
    # notifications table; neither is under test here.
    monkeypatch.setattr(risks_api, "_review_policy", _no_review_policy)
    monkeypatch.setattr(risks_api, "_refresh_alerts", _no_alert_refresh)
    monkeypatch.setattr(risks_api, "_reconcile_title_flag", _no_alert_refresh)
    monkeypatch.setattr(risks_api, "get_or_create_residual_policy", policy)
    monkeypatch.setattr(risks_api, "policy_spec", lambda p: ResidualPolicySpec())

    async def no_dimensions(db, risk_id):
        return []

    # The residual is not scored by dimension here (see test_fix_risk_residual_dimensions).
    monkeypatch.setattr(risks_api, "_stored_dimensions", no_dimensions)
    return state


async def test_accepting_credit_from_a_hand_rating_needs_a_note(stub, audit_log):
    hand = _control()  # effective, no test on file
    stub["risk"] = _risk([hand])
    with pytest.raises(HTTPException) as exc:
        await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(), FakeDB([]), _user())
    assert (exc.value.status_code, exc.value.detail) == (422, UNTESTED_CREDIT_NOTE_NEEDED)
    assert UNTESTED_CREDIT_NOTE_NEEDED == "Accepting credit from an untested control rating needs a note"
    assert stub["risk"].residual_likelihood is None and audit_log == []

    with pytest.raises(HTTPException):  # blank is no note
        await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(note="   "), FakeDB([]), _user())

    await risks_api.accept_residual(
        stub["risk"].id, ResidualAcceptance(note=" Tested by internal audit in May; report pending "),
        FakeDB([]), _user(),
    )
    risk = stub["risk"]
    assert (risk.residual_likelihood, risk.residual_impact) == (2, 5)
    assert risk.assessment_rationale.startswith("Accepted the suggested residual 2x5: ")
    assert risk.assessment_rationale.endswith("; owner's note: Tested by internal audit in May; report pending")
    changes = audit_log[0]["changes"]
    assert changes["note"] == "Tested by internal audit in May; report pending"
    assert changes["untested_credit"] == ["A.8.13"]


async def test_an_override_basis_needs_a_note_even_with_tests_on_file(stub, audit_log):
    overridden = _control(effectiveness_override_reason="Set by the CISO")
    stub["risk"] = _risk([overridden])
    db = FakeDB([_test(R.passed, control_id=overridden.id)])
    with pytest.raises(HTTPException) as exc:
        await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(), db, _user())
    assert exc.value.detail == UNTESTED_CREDIT_NOTE_NEEDED


async def test_credit_from_reviewed_tests_needs_no_note(stub, audit_log):
    tested = _control()
    stub["risk"] = _risk([tested])
    db = FakeDB([_test(R.passed, "reviewed", control_id=tested.id)])
    await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(), db, _user())
    assert stub["risk"].residual_likelihood == 2
    assert "owner's note" not in stub["risk"].assessment_rationale
    assert "note" not in audit_log[0]["changes"] and "untested_credit" not in audit_log[0]["changes"]
    # Only the credited controls were looked up: the tests, not the issues.
    assert len(db.statements) == 1


async def test_an_untested_control_that_earns_no_credit_needs_no_note(stub, audit_log):
    tested = _control(reference="A.5.15")
    idle = _control(reference="A.8.2", effectiveness=E.not_assessed)  # weight 0: no credit
    stub["risk"] = _risk([tested, idle])
    db = FakeDB([_test(R.passed, control_id=tested.id)])
    await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(), db, _user())
    assert "control_audits.control_id IN" in _sql(db.statements[0])
    assert stub["risk"].residual_likelihood == 2


async def test_no_credit_taken_no_note_and_no_query(stub, audit_log):
    stub["risk"] = _risk([])
    db = FakeDB()
    await risks_api.accept_residual(stub["risk"].id, ResidualAcceptance(), db, _user())
    assert db.statements == []
    assert (stub["risk"].residual_likelihood, stub["risk"].residual_impact) == (4, 5)


async def test_an_override_carries_its_own_reason_not_a_note(stub, audit_log):
    stub["risk"] = _risk([_control()])
    body = ResidualAcceptance(likelihood=3, impact=5, override_reason="Backups untested; one step of credit only")
    await risks_api.accept_residual(stub["risk"].id, body, FakeDB(), _user())
    assert stub["risk"].residual_likelihood == 3
    assert stub["risk"].assessment_rationale.endswith("Backups untested; one step of credit only")


def test_the_note_is_optional_in_the_schema():
    assert ResidualAcceptance().note == ""
    assert ResidualAcceptance(note="x").note == "x"


def test_the_engine_names_the_controls_it_credits():
    keys = [uuid.uuid4() for _ in range(3)]
    s = suggest_residual(4, 5, [
        ControlInput("A", E.effective, key=keys[0]),
        ControlInput("B", E.not_assessed, key=keys[1]),           # weight 0
        ControlInput("C", E.effective, healthy=False, key=keys[2]),  # not reliable today
    ])
    assert s.credited == (keys[0],)
    assert suggest_residual(4, 5, [ControlInput("A", E.effective)]).credited == ("A",)
    # A reduction that moves nothing (likelihood already 1) credits nothing.
    assert suggest_residual(1, 5, [ControlInput("A", E.effective)]).credited == ()
    assert suggest_residual(4, 5, [ControlInput("A", E.effective)], ResidualPolicySpec(enabled=False)).credited == ()


# ======================================================================= B12 ===
async def test_the_suggestion_says_which_appetite_band_it_would_fall_in(monkeypatch):
    cat = uuid.uuid4()
    risk = _risk([_control()], category_id=cat)

    async def load(db, risk_id):
        return risk

    async def policy(db, tenant_id):
        return None

    books = {"book": AppetiteBook(appetite=6, tolerance=12)}

    async def book(db, tenant_id, settings=None):
        return books["book"]

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api, "get_or_create_residual_policy", policy)
    monkeypatch.setattr(risks_api, "policy_spec", lambda p: ResidualPolicySpec())
    monkeypatch.setattr(risks_api, "load_appetite_book", book)

    s = await risks_api.get_suggested_residual(risk.id, FakeDB(), _user())
    assert (s.score, s.appetite_status) == (10, "elevated")  # 4x5 → 2x5, appetite 6, tolerance 12
    # The control it credits is rated by hand with no test on file: accepting needs a note.
    assert (s.credited_control_ids, s.note_required) == ([risk.controls[0].id], True)
    # The risk's category thresholds apply, as they do to the recorded score.
    books["book"] = AppetiteBook(appetite=6, tolerance=12, by_category={cat: (4, 8)}, parents={cat: None})
    assert (await risks_api.get_suggested_residual(risk.id, FakeDB(), _user())).appetite_status == "breach"
    books["book"] = AppetiteBook(appetite=10, tolerance=15)
    assert (await risks_api.get_suggested_residual(risk.id, FakeDB(), _user())).appetite_status == "within_appetite"


async def test_the_suggestion_names_what_accepting_it_relies_on(monkeypatch):
    """The page lists the credited controls and asks for the note from the server's own
    answer (B6), never by re-deriving the residual policy's weights."""
    tested, idle = _control(reference="A.5.15"), _control(reference="A.8.2", effectiveness=E.not_assessed)
    state = {"risk": _risk([tested, idle])}

    async def load(db, risk_id):
        return state["risk"]

    async def policy(db, tenant_id):
        return None

    async def book(db, tenant_id, settings=None):
        return AppetiteBook(appetite=6, tolerance=12)

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api, "get_or_create_residual_policy", policy)
    monkeypatch.setattr(risks_api, "policy_spec", lambda p: ResidualPolicySpec())
    monkeypatch.setattr(risks_api, "load_appetite_book", book)

    db = FakeDB([_test(R.passed, "reviewed", control_id=tested.id)])
    s = await risks_api.get_suggested_residual(state["risk"].id, db, _user())
    assert (s.credited_control_ids, s.note_required) == ([tested.id], False)  # idle earns nothing
    assert len(db.statements) == 1 and "control_audits.control_id IN" in _sql(db.statements[0])

    # Only a pending test behind the credited rating: the tester's claim, so a note is needed.
    db = FakeDB([_test(R.passed, "pending", control_id=tested.id)])
    assert (await risks_api.get_suggested_residual(state["risk"].id, db, _user())).note_required is True

    # Nothing credited: nothing to rely on, nothing looked up.
    state["risk"] = _risk([idle])
    db = FakeDB()
    s = await risks_api.get_suggested_residual(state["risk"].id, db, _user())
    assert (s.credited_control_ids, s.note_required, db.statements) == ([], False, [])


def test_suggested_residual_stays_backward_compatible():
    s = SuggestedResidual(likelihood=2, impact=5, score=10, reduction=2, rationale=[], inherent_score=20,
                          current_residual_score=None, matches_current=False)
    assert (s.appetite_status, s.credited_control_ids, s.note_required) == (None, [], False)


# ======================================================================== B7 ===
class _LazyRequirement:
    """A requirement row whose framework is not loaded: touching it is a lazy load."""

    def __init__(self, framework_id):
        self.id = uuid.uuid4()
        self.reference = "A.5.1"
        self.title = "Policies for information security"
        self.framework_id = framework_id

    @property
    def framework(self):
        raise AssertionError("lazy-loaded Requirement.framework")


def test_a_clause_ref_never_lazy_loads_its_framework():
    fid = uuid.uuid4()
    ref = RequirementLinkRef.model_validate(_LazyRequirement(fid))
    assert (ref.reference, ref.framework_id, ref.framework) == ("A.5.1", fid, None)
    # A framework already loaded is used as is.
    loaded = Requirement(id=uuid.uuid4(), reference="A.8.13", title="Backup", framework_id=fid)
    loaded.__dict__["framework"] = SimpleNamespace(name="ISO/IEC 27001:2022")
    assert RequirementLinkRef.model_validate(loaded).framework == "ISO/IEC 27001:2022"
    assert ControlRead.model_fields["requirements"].annotation == list[RequirementLinkRef]


async def test_frameworks_are_named_with_one_query_per_page():
    iso, pci = uuid.uuid4(), uuid.uuid4()
    r1, r2, r3 = (RequirementLinkRef(id=uuid.uuid4(), reference=x) for x in ("A.5.1", "12.3", "A.9.9"))
    items = [SimpleNamespace(requirements=[r1, r2]), SimpleNamespace(requirements=[r2, r3])]
    db = FakeDB([(r1.id, iso, "ISO/IEC 27001:2022"), (r2.id, pci, "PCI DSS 4.0")])
    found = await controls_api._frameworks_by_requirement(db, [r.id for i in items for r in i.requirements])
    controls_api.fill_frameworks(items, found)
    assert len(db.statements) == 1
    assert "JOIN frameworks ON frameworks.id = requirements.framework_id" in _sql(db.statements[0])
    assert (r1.framework, r1.framework_id) == ("ISO/IEC 27001:2022", iso)
    assert (r2.framework, r2.framework_id) == ("PCI DSS 4.0", pci)
    assert (r3.framework, r3.framework_id) == (None, None)  # not found: left unset, never guessed
    assert await controls_api._frameworks_by_requirement(FakeDB(), []) == {}


# ======================================================================== B8 ===
def _asset_risk(**kw):
    base = dict(id=uuid.uuid4(), reference="R-007", title="Ransomware", category_id=None,
                inherent_likelihood=4, inherent_impact=5, inherent_score=20,
                residual_likelihood=2, residual_impact=4, residual_score=8)
    base.update(kw)
    return SimpleNamespace(**base)


def test_an_assets_risk_carries_the_dashboards_bands_and_appetite():
    scale = SeverityScale(max_score=25)
    ref = assets_api.risk_exposure_ref(_asset_risk(), (scale, AppetiteBook(appetite=6, tolerance=12)))
    assert (ref.label, ref.reference, ref.inherent_score, ref.residual_score) == ("Ransomware", "R-007", 20, 8)
    assert (ref.inherent_severity, ref.residual_severity) == (scale.for_cell(4, 5), scale.for_cell(2, 4))
    assert ref.appetite_status == "elevated"  # judged on the residual, 8
    # Cell overrides and the category's own appetite apply, as on the register.
    cat = uuid.uuid4()
    overridden = SeverityScale(max_score=25, cells={"2,4": "high"})
    ref = assets_api.risk_exposure_ref(
        _asset_risk(category_id=cat),
        (overridden, AppetiteBook(appetite=6, tolerance=12, by_category={cat: (4, 6)}, parents={cat: None})),
    )
    assert (ref.residual_severity, ref.appetite_status) == (Severity.high, "breach")
    # Unassessed: judged on the inherent score, no residual band.
    ref = assets_api.risk_exposure_ref(
        _asset_risk(residual_likelihood=None, residual_impact=None, residual_score=None),
        (scale, AppetiteBook(appetite=6, tolerance=12)),
    )
    assert (ref.residual_severity, ref.appetite_status) == (None, "breach")


def test_without_the_tenant_scale_or_the_permission_an_assets_risk_is_named_only():
    bare = assets_api.risk_exposure_ref(_asset_risk())
    assert (bare.inherent_score, bare.inherent_severity, bare.appetite_status) == (20, None, None)
    hidden = assets_api.risk_exposure_ref(_asset_risk(), None, scores=False)
    assert hidden.model_dump(exclude_none=True) == {"id": hidden.id, "label": "Ransomware", "reference": "R-007"}
    # A risk with no title falls back to its reference, never an empty chip.
    assert assets_api.risk_exposure_ref(_asset_risk(title="")).label == "R-007"


def test_an_information_asset_dependency_carries_its_business_value():
    info = SimpleNamespace(id=uuid.uuid4(), name="Customer master", business_value=Criticality.high)
    it = SimpleNamespace(id=uuid.uuid4(), name="DB-01")
    dep = SimpleNamespace(id=uuid.uuid4(), relationship_type="hosts", notes="", information_asset=info, it_asset=it)
    read = assets_api._dep_ref(dep)
    assert (read.information_asset.label, read.information_asset.business_value) == ("Customer master", Criticality.high)
    assert "business_value" not in read.it_asset.model_dump()


def _asset(risks):
    """Enough of an Asset row for ``_serialize``."""
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), name="Core banking DB", description="",
        asset_class=AssetClass.information_asset, media_type=None, label=None, owner=None, guardian=None,
        user=None, confidentiality=Criticality.high, integrity=Criticality.high, availability=Criticality.high,
        criticality=Criticality.high, classification=Criticality.high, potential_liabilities="",
        business_value=Criticality.high, information_owner="", data_categories="", records_volume="",
        self_assessed=False, assessed_by="", assessed_date=None, replacement_cost=0, currency="PKR",
        rto_hours=None, rpo_hours=None, environment="production", tier=None, pci_scope=None,
        location="", hostname="", ip_address="",
        serial_number="", manufacturer="", model_number="", os_version="", discovery_source="manual",
        external_id="", auto_discovered=False, last_seen=None, cost_band=Criticality.low,
        intrinsic_criticality=Criticality.low, derived_criticality=Criticality.low,
        effective_criticality=Criticality.high, review_frequency="annual", next_review_date=None,
        last_review_date=None, expired_reviews=0, review_status="none", workflow_status="draft",
        classifications=[], tags=[], hosted_dependencies=[], hosting_dependencies=[], processes=[], legals=[],
        requirements=[], incidents=[], exceptions=[], related_assets=[], risks=risks, vendors=[],
        access_reviews=[], controls=[], threats=[], vulnerabilities=[], reviews=[],
        continuity_plans=[], processing_activities=[], bia_assessments=[], vuln_findings=[],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


async def test_the_asset_read_bands_its_risks_for_a_risk_reader(monkeypatch):
    loaded = []

    async def settings(db, tenant_id):
        loaded.append(tenant_id)
        return SimpleNamespace(matrix_size=5, severity_bands=None, matrix_cells={})

    async def book(db, tenant_id, settings=None):
        return AppetiteBook(appetite=6, tolerance=12)

    monkeypatch.setattr(assets_api, "get_or_create_settings", settings)
    monkeypatch.setattr(assets_api, "load_appetite_book", book)
    asset = _asset([_asset_risk()])

    read = await assets_api._read(FakeDB(), asset, _user(("asset:read", "risk:read")))
    assert isinstance(read.risks[0], RiskExposureRef)
    # Residual 2x4 = 8: medium on the default 5x5 bands, above appetite 6 and within tolerance 12.
    assert (read.risks[0].inherent_severity, read.risks[0].residual_severity) == (Severity.critical, Severity.medium)
    assert (read.risks[0].inherent_score, read.risks[0].residual_score, read.risks[0].appetite_status) == (20, 8, "elevated")
    assert loaded == [asset.tenant_id]

    # An asset reader who may not read risks sees which risks sit on the asset, no more.
    read = await assets_api._read(FakeDB(), asset, _user(("asset:read",)))
    assert (read.risks[0].reference, read.risks[0].inherent_score, read.risks[0].appetite_status) == ("R-007", None, None)
    assert loaded == [asset.tenant_id]  # nothing loaded for them

    # No risks: nothing to band, nothing loaded.
    await assets_api._read(FakeDB(), _asset([]), _user(("asset:read", "risk:read")))
    assert len(loaded) == 1


class _ListDB:
    """``list_assets``: one count, one page of rows."""

    def __init__(self, rows):
        self.rows = rows

    async def scalar(self, stmt):
        return len(self.rows)

    async def scalars(self, stmt):
        return SimpleNamespace(all=lambda: list(self.rows))

    async def run_sync(self, fn):
        return fn(None)


async def test_the_asset_list_shows_risk_scores_only_to_a_risk_reader(monkeypatch):
    async def must_not_load(*a, **k):
        raise AssertionError("the list loads no risk settings")

    monkeypatch.setattr(assets_api, "get_or_create_settings", must_not_load)
    monkeypatch.setattr(assets_api, "load_appetite_book", must_not_load)
    rows = [_asset([_asset_risk()])]

    page = await assets_api.list_assets(_ListDB(rows), _user(("asset:read", "risk:read")), limit=50, offset=0)
    risk = page.items[0].risks[0]
    assert (risk.label, risk.reference, risk.inherent_score, risk.residual_score) == ("Ransomware", "R-007", 20, 8)
    assert (risk.inherent_severity, risk.appetite_status) == (None, None)  # bands are the record read's

    page = await assets_api.list_assets(_ListDB(rows), _user(("asset:read",)), limit=50, offset=0)
    risk = page.items[0].risks[0]
    assert risk.model_dump(exclude_none=True) == {"id": risk.id, "label": "Ransomware", "reference": "R-007"}


def test_the_serializer_shows_no_risk_score_unless_told_the_viewer_may_read_risks():
    read = assets_api._serialize(_asset([_asset_risk()]))
    assert (read.risks[0].label, read.risks[0].inherent_score, read.risks[0].residual_score) == ("Ransomware", None, None)


async def test_scheduling_an_asset_review_is_audited(monkeypatch):
    asset = _asset([])
    asset.next_review_date = AGO(-10)
    calls, added = [], []

    async def record(db, **kw):
        calls.append(kw)

    async def get(db, asset_id):
        return asset

    async def read(db, a, user):
        return "read"

    async def fresh(db, asset_id):
        return asset

    monkeypatch.setattr(assets_api.audit, "record", record)
    monkeypatch.setattr(assets_api, "_get_or_404", get)
    monkeypatch.setattr(assets_api, "_fresh", fresh)
    monkeypatch.setattr(assets_api, "_read", read)
    db = SimpleNamespace(add=added.append, flush=FakeDB().flush)
    body = assets_api.AssetReviewCreate(reviewer="Internal audit", scheduled_date=AGO(-40))

    assert await assets_api.schedule_review(asset.id, body, db, _user(("asset:write",))) == "read"
    assert asset.next_review_date == AGO(-40) and len(added) == 1
    assert len(calls) == 1 and (calls[0]["action"], calls[0]["entity_type"], calls[0]["entity_id"]) == (
        "update", "asset", asset.id,
    )
    assert calls[0]["changes"] == {
        "next_review_date": {"from": AGO(-10).isoformat(), "to": AGO(-40).isoformat()},
        "reviewer": "Internal audit",
    }


# ====================================================================== B10a ===
class _PackDB:
    def __init__(self, requirements):
        self.requirements = requirements
        self.added = []

    async def execute(self, stmt):
        return SimpleNamespace(all=lambda: [])  # an empty catalogue: every control is new

    async def scalars(self, stmt):
        entity = stmt.column_descriptions[0]["entity"].__name__
        return SimpleNamespace(all=lambda: [] if entity == "Control" else list(self.requirements))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


async def test_a_pack_install_leaves_the_classification_blank():
    key = "iso-27001-2022"
    reqs = [SimpleNamespace(reference=r["reference"], controls=[])
            for r in fl.TEMPLATES[key]["requirements"] if r["reference"].startswith("A.")]
    db = _PackDB(reqs)
    created, _linked, _ = await fl.install_controls_pack(
        db, SimpleNamespace(tenant_id=uuid.uuid4()), SimpleNamespace(id=uuid.uuid4()), key
    )
    assert created > 0 and len(db.added) == created
    name = fl.TEMPLATES[key]["name"]
    assert all(not c.classification and c.classification_id is None for c in db.added), name
    # Where a control came from is its clause link, which names the framework (B7).
    assert all(r.controls for r in reqs)
