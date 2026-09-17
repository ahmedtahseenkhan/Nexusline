"""Every risk number agrees with the record (re-check of 17 September, F-21/F-22/F-23).

No database: the rules are pure and tested directly; endpoints run with their loaders
stubbed, as in tests/test_risk_integrity.py.

Pinned here:

1. **One "is it scored?" rule** (F-23). A draft no score change has stamped carries a
   stored 1x1 placeholder: the read model says ``inherent_scored`` false and leaves its
   severities and appetite status null, the heat map never plots it.
2. **Control health has three states** (F-23): ``issues`` (reliance withheld, or an open
   issue) > ``untested`` (a rating no reviewed test stands behind) > ``ok``.
3. **Board figures are taken over the board register** (F-21): scored, out of Draft,
   not accepted or closed — the dashboard, ``?appetite=`` and the breach alert alike;
   drafts are ``?pending_validation=true``. Leaving Draft needs an owner and a business
   unit, by an edit, an assessment or a lifecycle submit.
4. **The rating drives the review cycle** (F-22): the effective cycle is the stricter of
   the one set and the longest the rating allows; re-saving never moves the date, a
   re-score that tightens the cycle brings it in; bulk edit and attestation follow it.
5. **Alerts follow a score save** (F-22): one risk's alerts reconcile on their own; a
   review alert already folded into a group is not duplicated.
"""
from __future__ import annotations

import datetime as dt_
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1 import dashboard
from app.api.v1 import risks as risks_api
from app.models.enums import ControlEffectiveness as E
from app.models.enums import ControlStatus, ReviewFrequency as F, RiskStatus, Severity, TestResult as R
from app.models.risk import Risk
from app.schemas.risk import RiskRead, RiskSettingRead, RiskUpdate
from app.services import bulk_edit as be
from app.services import control_assurance as ca
from app.services import drill_through as dt
from app.services import notifications as nt
from app.services import record_workflow as rw
from app.services import risk_integrity as ri
from app.services import risk_query as rq
from app.services import risk_scoring as rs
from app.services.risk_scoring import AppetiteBook, SeverityScale

TODAY = date(2026, 9, 17)
STAMPED = datetime(2026, 9, 1, tzinfo=timezone.utc)


def sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def where(clause) -> str:
    return sql(select(Risk.id).where(clause)).split("WHERE", 1)[1]


def _payload(**kw) -> dict:
    base = dict(
        id=uuid.uuid4(), reference="R-116", title="Card fraud", description="", category="",
        status="draft", owner_id=None, inherent_likelihood=1, inherent_impact=1,
        inherent_score=1, residual_likelihood=None, residual_impact=None,
        residual_score=None, annual_loss_frequency=None, single_loss_expectancy=None,
        annual_loss_expectancy=None, treatment_strategy=None, treatment_description="",
        treatment_owner="", treatment_deadline=None, treatment_cost=None,
        review_frequency="annual", last_review_date=None, next_review_date=None,
        expired_reviews=0, workflow_status="draft", workflow_owner="", last_assessed_at=None,
        created_at=dt_.datetime.now(), updated_at=dt_.datetime.now(),
    )
    base.update(kw)
    return base


# ============================================================ 1. is it scored? ===
@pytest.mark.parametrize(
    "status,stamped,scored",
    [("draft", None, False), ("draft", STAMPED, True), ("assessed", None, True),
     (RiskStatus.draft, None, False), (RiskStatus.closed, None, True)],
)
def test_one_rule_says_whether_a_risk_is_scored(status, stamped, scored):
    assert rs.is_scored(status, stamped) is scored


def test_an_unscored_draft_reads_as_not_scored_not_as_low_and_within_appetite():
    book = AppetiteBook(appetite=6, tolerance=12)
    read = RiskRead.model_validate(_payload(), context={"appetite": book})
    assert read.inherent_scored is False
    assert (read.inherent_severity, read.residual_severity, read.appetite_status) == (None, None, None)
    # The thresholds that would apply are still shown; only the verdict is withheld.
    assert (read.appetite_score, read.tolerance_score) == (6, 12)
    # The response pass (no context) does not band it either.
    assert RiskRead.model_validate(read).inherent_severity is None


def test_a_scored_draft_is_banded_and_judged():
    book = AppetiteBook(appetite=6, tolerance=12)
    read = RiskRead.model_validate(
        _payload(inherent_likelihood=4, inherent_impact=5, inherent_score=20, last_assessed_at=STAMPED),
        context={"appetite": book},
    )
    assert read.inherent_scored is True
    assert (read.inherent_severity, read.appetite_status) == (Severity.critical, "breach")


# ============================================================= 2. control health ===
def _test(result=R.passed, review="reviewed", when=TODAY - timedelta(days=20)):
    return SimpleNamespace(result=result, review_status=review, test_type="operating",
                           conducted_date=when, created_at=datetime(2026, 9, 1))


def _control(tests=(), **kw):
    base = dict(id=uuid.uuid4(), reference="A.8.13", name="Backup", status=ControlStatus.operational,
                next_audit_date=TODAY + timedelta(days=90), effectiveness=E.effective,
                effectiveness_override_reason="", audit_findings=[], audits=list(tests))
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "reliance,basis,tests,issues,state",
    [
        ("", "tests", 2, 0, "ok"),
        ("", "manual", 0, 0, "untested"),
        ("", "override", 3, 0, "untested"),
        ("", "none", 0, 0, "untested"),
        ("", "tests", 0, 0, "untested"),
        ("", "tests", 2, 1, "issues"),          # an open issue against the control
        ("its test is overdue", "manual", 0, 0, "issues"),  # issues outrank untested
    ],
)
def test_a_controls_health_state(reliance, basis, tests, issues, state):
    assert ca.control_health_state(reliance=reliance, basis=basis, reviewed_tests=tests, open_issues=issues) == state


def test_the_rollup_takes_the_worst_state():
    assert ca.rollup_health([]) == "none"
    assert ca.rollup_health(["ok", "ok"]) == "ok"
    assert ca.rollup_health(["ok", "untested"]) == "untested"
    assert ca.rollup_health(["untested", "issues", "ok"]) == "issues"


def test_a_hand_rated_control_is_never_controls_ok_on_the_register():
    hand_rated = _control()  # effective, no tests on file
    assert Risk.control_health.fget(SimpleNamespace(controls=[hand_rated])) == "untested"
    tested = _control([_test()])
    assert Risk.control_health.fget(SimpleNamespace(controls=[tested])) == "ok"
    failed = _control([_test(R.failed)])
    assert Risk.control_health.fget(SimpleNamespace(controls=[tested, hand_rated, failed])) == "issues"


def test_open_issues_make_a_tested_control_issues():
    tested = _control([_test()])
    assert ca.health_of_control(tested, open_issues=0, today=TODAY) == "ok"
    assert ca.health_of_control(tested, open_issues=2, today=TODAY) == "issues"


def test_the_record_pages_untested_rule_is_the_services():
    from app.schemas.control import ControlAssuranceRef

    for basis, count in (("tests", 2), ("manual", 0), ("override", 3), ("none", 0), ("tests", 0)):
        ref = ControlAssuranceRef(id=uuid.uuid4(), name="x", reference="C-1", effectiveness_basis=basis, audit_count=count)
        assert risks_api.rests_on_untested_rating(ref) is ca.rests_on_untested_rating(basis, count)


class _HealthDB:
    """Answers ``_assurance_inputs``: the test rows, then the open issue counts."""

    def __init__(self, tests, issues):
        self.results = [tests, issues]

    async def execute(self, stmt, *a, **k):
        rows = self.results.pop(0)
        return SimpleNamespace(all=lambda: rows)


async def test_the_register_column_counts_open_issues_the_row_cannot_see():
    control = _control()
    risk = SimpleNamespace(id=uuid.uuid4(), controls=[control])
    row = SimpleNamespace(control_id=control.id, **vars(_test()))
    health = await risks_api._control_health(_HealthDB([row], [(control.id, 1)]), [risk])
    assert health[risk.id] == "issues"
    bare = SimpleNamespace(id=uuid.uuid4(), controls=[])
    assert await risks_api._control_health(_HealthDB([], []), [bare]) == {bare.id: "none"}


# ============================================================ 3. board register ===
@pytest.mark.parametrize(
    "status,stamped,deleted,on_board",
    [
        (RiskStatus.assessed, STAMPED, False, True),
        (RiskStatus.treatment_in_progress, None, False, True),
        (RiskStatus.draft, None, False, False),     # unscored draft
        (RiskStatus.draft, STAMPED, False, False),  # scored, but not validated
        (RiskStatus.accepted, STAMPED, False, False),
        (RiskStatus.closed, STAMPED, False, False),
        (RiskStatus.assessed, STAMPED, True, False),
    ],
)
def test_the_board_register(status, stamped, deleted, on_board):
    assert rq.on_board_register(status, stamped, deleted) is on_board


def test_the_board_register_in_sql():
    text = where(rq.board_register_clause())
    assert "risks.deleted IS false" in text
    assert "risks.last_assessed_at IS NOT NULL" in text
    assert "risks.status != 'draft'" in text
    assert "risks.status NOT IN ('accepted', 'closed')" in text
    assert dt.risk_board_register is not None and where(dt.risk_board_register()) == text


def test_the_appetite_filter_counts_only_the_board_register():
    book = AppetiteBook(appetite=6, tolerance=12)
    text = sql(rq.build_risk_query(appetite="breach", appetite_book=book))
    assert "risks.status NOT IN ('accepted', 'closed')" in text and "risks.status != 'draft'" in text
    pending = sql(rq.build_risk_query(pending_validation=True))
    assert "risks.status = 'draft'" in pending
    assert "draft" not in sql(rq.build_risk_query())


def test_the_pending_validation_link_is_a_register_filter():
    assert dt.PENDING_VALIDATION_LINK == "/risks?pending_validation=true"
    from app.main import app

    params = {p["name"] for p in app.openapi()["paths"]["/api/v1/risks"]["get"]["parameters"]}
    assert "pending_validation" in params


def test_completeness_is_part_of_the_overview():
    from app.schemas.dashboard import DashboardOverview, DataCompleteness

    assert "completeness" in DashboardOverview.model_fields
    block = DataCompleteness(live_risks=74, board_risks=20, pending_validation=50, owned=30, owned_pct=40.5)
    assert block.approved_pct is None


class _RecordingDB:
    def __init__(self):
        self.statements = []

    async def scalar(self, stmt, *a, **k):
        self.statements.append(stmt)
        return 0

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [])


async def test_the_severity_and_appetite_tallies_read_the_board_register(monkeypatch):
    async def settings(db, tenant_id):
        return SimpleNamespace(appetite_score=6, tolerance_score=12, matrix_size=5, severity_bands={}, matrix_cells={})

    async def book(db, tenant_id, settings=None):
        return AppetiteBook()

    monkeypatch.setattr(dashboard, "get_or_create_settings", settings)
    monkeypatch.setattr(dashboard, "load_appetite_book", book)
    db = _RecordingDB()
    await dashboard.get_dashboard(db, _user())
    banded = [sql(s) for s in db.statements if "risks.inherent_likelihood" in sql(s)]
    assert banded and all("risks.status NOT IN ('accepted', 'closed')" in text for text in banded)


# ------------------------------------------------------------- leaving Draft ---
def test_leaving_draft_names_what_is_missing():
    assert ri.draft_exit_refusal(has_owner=False, has_business_unit=False) == ri.LEAVE_DRAFT_NEEDS_OWNER_AND_UNIT
    assert ri.draft_exit_refusal(has_owner=False, has_business_unit=True) == ri.LEAVE_DRAFT_NEEDS_OWNER
    assert ri.draft_exit_refusal(has_owner=True, has_business_unit=False) == ri.LEAVE_DRAFT_NEEDS_UNIT
    assert ri.draft_exit_refusal(has_owner=True, has_business_unit=True) is None


def _decide(**kw):
    base = dict(creating=False, changed=False, sends_inherent=True, rationale="RCSA",
                stored_rationale="", status_before="draft", status_after="assessed",
                previously_assessed=True)
    base.update(kw)
    return ri.assessment_decision(**base)


def test_the_assessment_rule_refuses_an_unowned_risk_leaving_draft():
    with pytest.raises(HTTPException) as exc:
        _decide(has_owner=False, has_business_unit=True)
    assert (exc.value.status_code, exc.value.detail) == (422, ri.LEAVE_DRAFT_NEEDS_OWNER)
    # Scores and rationale are still asked for first.
    with pytest.raises(HTTPException) as exc:
        _decide(sends_inherent=False, previously_assessed=False, has_owner=False, has_business_unit=False)
    assert exc.value.detail == ri.LEAVE_DRAFT_DETAIL
    # Staying in draft needs neither; an unknown owner (None) is not checked.
    assert _decide(status_after="draft", has_owner=False, has_business_unit=False)
    assert _decide()
    # A risk already out of draft is not re-gated.
    assert _decide(status_before="assessed", has_owner=False, has_business_unit=False)


async def test_submitting_an_unowned_risk_for_approval_is_422():
    from app.models.base import WorkflowState

    risk = Risk(id=uuid.uuid4(), title="R", reference="R-1", workflow_status=WorkflowState.draft)
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@bank.pk",
                           permission_codes=["risk:read", "risk:write"])
    with pytest.raises(HTTPException) as exc:
        await rw.apply(SimpleNamespace(), user, risk, "risk", "submit")
    assert (exc.value.status_code, exc.value.detail) == (422, ri.LEAVE_DRAFT_NEEDS_OWNER_AND_UNIT)
    assert risk.workflow_status == WorkflowState.draft


# ============================================================== 4. review cadence ===
def test_the_stricter_cycle_wins():
    assert rs.stricter_frequency(F.annual, F.monthly) == F.monthly
    assert rs.stricter_frequency(F.quarterly, F.semiannual) == F.quarterly
    assert rs.stricter_frequency(F.none, F.annual) == F.annual
    assert rs.stricter_frequency("weekly", "monthly") == F.weekly


def test_the_cadence_falls_back_to_the_product_default():
    assert rs.review_cadence({}) == {"critical": F.monthly, "high": F.quarterly, "medium": F.semiannual, "low": F.annual}
    merged = rs.review_cadence({"high": "monthly", "low": "daily", "extreme": "monthly"})
    assert merged["high"] == F.monthly and merged["low"] == F.annual  # a bad value is ignored


def test_a_cadence_is_checked_before_it_is_stored():
    assert rs.validate_review_cadence({"critical": "monthly", "high": "monthly"}) == {"critical": "monthly", "high": "monthly"}
    for bad in ({"urgent": "monthly"}, {"critical": "weekly"}, {"critical": "annual"}):
        with pytest.raises(ValueError):
            rs.validate_review_cadence(bad)


@pytest.mark.parametrize(
    "chosen,severity,cadence,expected,reason",
    [
        (F.annual, Severity.critical, {}, F.monthly, "Monthly — required for Critical risks"),
        (F.monthly, Severity.critical, {}, F.monthly, ""),
        (F.annual, Severity.high, {"high": "semiannual"}, F.semiannual, "Twice a year — required for High risks"),
        (F.annual, Severity.low, {}, F.annual, ""),
        (F.none, Severity.medium, {}, F.semiannual, "Twice a year — required for Medium risks"),
        (F.annual, None, {}, F.annual, ""),  # unscored: the chosen cycle stands
    ],
)
def test_the_effective_cycle(chosen, severity, cadence, expected, reason):
    assert rs.effective_review_frequency(chosen, severity, cadence) == (expected, reason)


def test_the_read_model_says_which_cycle_runs_and_why():
    read = RiskRead.model_validate(
        _payload(status="assessed", inherent_likelihood=5, inherent_impact=5, inherent_score=25),
        context={"cadence": {}},
    )
    assert (read.effective_review_frequency, read.review_frequency_reason) == (
        F.monthly, "Monthly — required for Critical risks")
    draft = RiskRead.model_validate(_payload(inherent_likelihood=5, inherent_impact=5, inherent_score=25))
    assert (draft.effective_review_frequency, draft.review_frequency_reason) == (F.annual, "")


def test_settings_carry_the_cadence_with_its_defaults():
    read = RiskSettingRead.model_validate(SimpleNamespace(
        appetite_score=6, tolerance_score=12, matrix_size=5, impact_mode="max", review_cadence={"high": "monthly"},
    ))
    assert read.review_cadence == {"critical": "monthly", "high": "monthly", "medium": "semiannual", "low": "annual"}
    assert read.review_cadence_defaults["high"] == "quarterly"


NEXT = TODAY + timedelta(days=200)


@pytest.mark.parametrize(
    "before,after,changed,last,expected",
    [
        (F.annual, F.annual, False, None, NEXT),                        # re-save: never moves
        (F.annual, F.annual, True, None, NEXT),                         # chosen moved, effective did not
        (F.annual, F.monthly, False, None, date(2026, 10, 17)),         # re-scored critical: brought in
        (F.annual, F.monthly, False, date(2026, 9, 10), date(2026, 10, 10)),
        (F.monthly, F.annual, False, None, NEXT),                       # loosened by the rating: stands
        (F.annual, F.quarterly, True, None, date(2026, 12, 17)),        # owner's change: re-derived
        (F.annual, F.none, True, None, None),
    ],
)
def test_when_the_review_date_moves(before, after, changed, last, expected):
    assert rs.rescheduled_review(
        current=NEXT, last_review=last, effective_before=before, effective_after=after,
        frequency_changed=changed, today=TODAY,
    ) == expected


def test_tightening_never_pushes_a_nearer_date_out():
    soon = TODAY + timedelta(days=5)
    assert rs.rescheduled_review(current=soon, last_review=None, effective_before=F.annual,
                                 effective_after=F.monthly, frequency_changed=False, today=TODAY) == soon


def test_the_cadence_follows_the_current_rating():
    scale = SeverityScale()
    draft = SimpleNamespace(status=RiskStatus.draft, last_assessed_at=None, inherent_likelihood=5,
                            inherent_impact=5, residual_likelihood=None, residual_impact=None)
    assert rs.current_severity(draft, scale) is None
    assessed = SimpleNamespace(**{**vars(draft), "status": RiskStatus.assessed, "residual_likelihood": 1,
                                  "residual_impact": 2})
    assert rs.current_severity(assessed, scale) == Severity.low  # residual decides


# ------------------------------------------------------------ the update path ---
def _stored(**kw):
    base = dict(
        id=uuid.uuid4(), reference="R-117", title="Card fraud", status=RiskStatus.assessed,
        inherent_likelihood=2, inherent_impact=3, residual_likelihood=None, residual_impact=None,
        residual_override_reason="", needs_review=False, review_reason="", review_frequency=F.annual,
        last_review_date=None, next_review_date=NEXT, annual_loss_expectancy=None,
        target_likelihood=None, target_impact=None, assessment_rationale="Workshop",
        last_assessed_at=STAMPED, last_assessed_by_id=None, treatment_deadline=None,
        owner_id=uuid.uuid4(), treatment_owner="", treatment_owner_id=None, category="",
        category_id=None, workflow_owner="", workflow_owner_id=None, identified_by_id=None,
        cause="", event="", consequence="", business_units=[SimpleNamespace(id=uuid.uuid4())],
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _DB:
    async def flush(self):
        return None

    async def scalars(self, *a, **k):
        return SimpleNamespace(all=lambda: [])


@pytest.fixture
def io(monkeypatch):
    state = {"refreshed": []}

    async def load(db, risk_id):
        return state["risk"]

    async def read(db, risk_id, user):
        return state["risk"]

    async def size(db, tenant_id):
        return 5

    async def policy(db, user):
        return SeverityScale(), {}

    async def refresh(db, user, risk):
        state["refreshed"].append(risk.id)

    async def _no_title_check(db, user, risk):
        return None

    async def record(db, **kw):
        state.setdefault("audit", []).append(kw)

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api, "_read", read)
    monkeypatch.setattr(risks_api, "get_matrix_size", size)
    monkeypatch.setattr(risks_api, "_review_policy", policy)
    monkeypatch.setattr(risks_api, "_refresh_alerts", refresh)
    monkeypatch.setattr(risks_api, "_reconcile_title_flag", _no_title_check)
    monkeypatch.setattr(risks_api.audit, "record", record)
    return state


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@bank.pk",
                           permission_codes=["risk:read", "risk:write"])


async def test_resaving_the_form_never_moves_the_review(io):
    io["risk"] = _stored()
    await risks_api.update_risk(
        io["risk"].id,
        RiskUpdate(title="Card fraud", review_frequency=F.annual, inherent_likelihood=2, inherent_impact=3),
        _DB(), _user(),
    )
    assert io["risk"].next_review_date == NEXT
    assert io["refreshed"] == []  # nothing a breach alert reads changed


async def test_a_rescore_to_critical_brings_the_review_in_and_refreshes_alerts(io):
    io["risk"] = _stored()
    await risks_api.update_risk(
        io["risk"].id,
        RiskUpdate(inherent_likelihood=5, inherent_impact=5, assessment_rationale="New typology",
                   review_frequency=F.annual),
        _DB(), _user(),
    )
    assert io["risk"].next_review_date == rs.next_review_date(F.monthly, date.today())
    assert io["refreshed"] == [io["risk"].id]
    assert "next_review_date" in io["audit"][-1]["changes"]


async def test_moving_an_unowned_draft_on_is_422(io):
    io["risk"] = _stored(status=RiskStatus.draft, owner_id=None, business_units=[])
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(io["risk"].id, RiskUpdate(status=RiskStatus.assessed), _DB(), _user())
    assert exc.value.detail == ri.LEAVE_DRAFT_NEEDS_OWNER_AND_UNIT
    assert io["risk"].status == RiskStatus.draft
    # Sending the unit with the move is enough when the owner is on file.
    io["risk"] = _stored(status=RiskStatus.draft, business_units=[])
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(io["risk"].id, RiskUpdate(status=RiskStatus.assessed), _DB(), _user())
    assert exc.value.detail == ri.LEAVE_DRAFT_NEEDS_UNIT


async def test_assessing_an_unowned_draft_keeps_it_a_draft(io):
    io["risk"] = _stored(status=RiskStatus.draft, owner_id=None)
    from app.schemas.risk import RiskAssessment

    await risks_api.assess_risk(
        io["risk"].id, RiskAssessment(residual_likelihood=1, residual_impact=2, assessment_rationale="Tested"),
        _DB(), _user(),
    )
    assert io["risk"].status == RiskStatus.draft and io["risk"].residual_likelihood == 1


# --------------------------------------------------------------- bulk edit ---
def _bulk_risk(**kw):
    base = dict(status=RiskStatus.assessed, last_assessed_at=STAMPED, inherent_likelihood=5, inherent_impact=5,
                residual_likelihood=None, residual_impact=None, review_frequency=F.annual,
                next_review_date=NEXT, last_review_date=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _bulk(record, **values):
    context = {"scale": SeverityScale(), "cadence": {}}
    return be.plan(be.REGISTERS["risk"], record, values, today=TODAY, context=context)


def test_bulk_frequency_on_a_critical_risk_leaves_its_monthly_clock_alone():
    changes = _bulk(_bulk_risk(), review_frequency=be.Value(F.semiannual, "Twice a year"))
    assert changes == {"review_frequency": F.semiannual}


def test_bulk_frequency_on_a_low_risk_re_derives_as_before():
    record = _bulk_risk(inherent_likelihood=1, inherent_impact=2)
    changes = _bulk(record, review_frequency=be.Value(F.quarterly, "Quarterly"))
    assert changes["next_review_date"] == rs.next_review_date(F.quarterly, TODAY)


def test_bulk_next_review_later_than_the_rating_allows_is_skipped():
    with pytest.raises(be.Skip) as why:
        _bulk(_bulk_risk(), next_review_date=be.Value(TODAY + timedelta(days=90), "later"))
    assert "critical" in str(why.value)
    ok = _bulk(_bulk_risk(), next_review_date=be.Value(TODAY + timedelta(days=20), "soon"))
    assert ok == {"next_review_date": TODAY + timedelta(days=20)}


# ================================================================= 5. alerts ===
def _alert_row(**kw):
    base = dict(id=uuid.uuid4(), reference="R-116", title="Card fraud", owner_id=None, status=RiskStatus.assessed,
                last_assessed_at=STAMPED, deleted=False, category_id=None, next_review_date=None,
                inherent_score=20, residual_score=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_a_breach_alert_needs_a_validated_risk():
    book = AppetiteBook(appetite=6, tolerance=12)
    assert [k.split(":")[0] for k, *_ in nt.risk_alert_conditions(_alert_row(), book, TODAY)] == ["risk-breach"]
    for kw in ({"status": RiskStatus.draft}, {"status": RiskStatus.draft, "last_assessed_at": None},
               {"status": RiskStatus.closed}, {"status": RiskStatus.accepted}, {"deleted": True}):
        assert nt.risk_alert_conditions(_alert_row(**kw), book, TODAY) == [], kw
    # A draft's overdue review is still chased: it is housekeeping, not a board figure.
    overdue = _alert_row(status=RiskStatus.draft, next_review_date=TODAY - timedelta(days=1))
    assert [k.split(":")[0] for k, *_ in nt.risk_alert_conditions(overdue, book, TODAY)] == ["risk-review"]
    assert nt.risk_alert_conditions(_alert_row(residual_score=9), book, TODAY) == []


def test_a_rescore_that_ends_a_breach_resolves_its_alert_on_save():
    rid, owner = uuid.uuid4(), uuid.uuid4()
    stored = SimpleNamespace(title="Risk above tolerance: R-116", body="x", category=nt._C, link="/risks",
                             entity_type="risk", entity_id=rid, user_id=owner, role_name="",
                             created_at=datetime(2026, 9, 1))
    key = f"risk-breach:{rid}@u:{owner}"
    plan = nt.risk_refresh_plan({key: stored}, [])
    assert plan.deletes == [key] and plan.creates == []


def test_a_grouped_review_alert_is_not_duplicated_by_a_single_refresh():
    owner = uuid.uuid4()
    rid = uuid.uuid4()
    review = {"dedup_key": f"risk-review:{rid}@u:{owner}", "title": "Risk review overdue: R-1", "body": "",
              "category": nt._W, "entity_type": "risk", "entity_id": rid, "link": "/risks", "user_id": owner,
              "role_name": ""}
    breach = {**review, "dedup_key": f"risk-breach:{rid}@u:{owner}", "category": nt._C}
    plan = nt.risk_refresh_plan({}, [review, breach], grouped_keys=[f"group:risk-review@u:{owner}"])
    assert [a["dedup_key"].split(":")[0] for a, _ in plan.creates] == ["risk-breach"]
    plan = nt.risk_refresh_plan({}, [review, breach])
    assert len(plan.creates) == 2
