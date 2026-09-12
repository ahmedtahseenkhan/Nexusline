"""Risk v2 — record depth for the risk register (product review, phase 2, F-09).

No database: the pure rules are tested directly and the endpoints are driven with fakes
(the same pattern as ``test_risk_integrity``).

Pinned here:

1. **Risk statement.** A blank title is composed from event, cause and consequence.
2. **Assessment trail.** A score change needs a new rationale (except on a draft), is
   stamped, and a risk leaves draft only with chosen inherent scores and a rationale.
3. **Target <= residual <= inherent.**
4. **Impact by dimension** decides the overall impact ("max" or "average" rounded up)
   and an explicit impact that disagrees is refused.
5. **Configured bands and cells** replace the derived bands only when set; the default
   5x5 is unchanged.
6. **Appetite per top-level category** with the organisation's as the fallback.
7. **Treatment actions** drive the deadline, the progress and the overdue alert.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1 import risk_program
from app.api.v1 import risks as risks_api
from app.models.enums import RiskStatus, Severity
from app.schemas.risk import (
    RISK_SOURCES,
    RISK_TYPES,
    RISK_VELOCITIES,
    ImpactDimensionIn,
    RiskAssessment,
    RiskCreate,
    RiskMatrixConfigUpdate,
    RiskRead,
    RiskUpdate,
)
from app.services import notifications
from app.services import risk_integrity as ri
from app.services.risk_scoring import (
    AppetiteBook,
    SeverityScale,
    band_ranges,
    cell_key,
    impact_from_dimensions,
    severity_for_score,
    validate_bands,
    validate_cells,
)

WRITER = ["risk:read", "risk:write"]
ACCEPTER = ["risk:read", "risk:write", "risk:accept"]


def _user(perms=WRITER):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x", permission_codes=perms)


# =============================================================== risk statement ===
def test_title_composes_event_cause_and_consequence():
    assert ri.compose_title("Phishing emails", "Customer data exfiltrated.", "Regulatory fine") == (
        "Customer data exfiltrated, caused by phishing emails, resulting in regulatory fine"
    )


def test_title_needs_an_event_and_keeps_acronyms():
    assert ri.compose_title("Phishing", "", "Fine") == ""
    assert ri.compose_title("SWIFT outage", "payments   delayed", None) == (
        "Payments delayed, caused by SWIFT outage"
    )
    assert ri.compose_title(None, "Fraud", None) == "Fraud"


def test_title_is_trimmed_to_the_column():
    title = ri.compose_title("c" * 200, "e" * 100, "q" * 200)
    assert len(title) == 255 and title.endswith("…")


def test_vocabularies_are_fixed_lists():
    assert "emerging" in RISK_TYPES and "generated" in RISK_SOURCES
    assert RISK_VELOCITIES == ("immediate", "weeks", "months", "years")
    with pytest.raises(Exception):
        RiskCreate(title="x", risk_type="made-up")


# ============================================================ assessment trail ===
def _decide(**kw):
    base = dict(
        creating=False, changed=False, sends_inherent=False, rationale=None,
        stored_rationale="", status_before="assessed", status_after="assessed",
        previously_assessed=True,
    )
    base.update(kw)
    return ri.assessment_decision(**base)


def test_changed_scores_are_values_not_presence():
    stored = {"inherent_likelihood": 3, "inherent_impact": 4, "residual_likelihood": None, "residual_impact": None}
    assert ri.changed_scores(stored, {"inherent_likelihood": 3, "inherent_impact": 4}) == []
    assert ri.changed_scores(stored, {"inherent_impact": 5}) == ["inherent_impact"]
    assert ri.changed_scores(None, {"inherent_likelihood": None, "residual_impact": 2}) == ["residual_impact"]


def test_score_change_on_an_assessed_risk_needs_a_new_rationale():
    with pytest.raises(HTTPException) as exc:
        _decide(changed=True)
    assert exc.value.status_code == 422 and exc.value.detail == ri.RATIONALE_REQUIRED_DETAIL
    # Resending the old rationale is not a reason for the new scores.
    with pytest.raises(HTTPException):
        _decide(changed=True, rationale="Old words", stored_rationale="Old words")
    d = _decide(changed=True, rationale="  Control failed in Q3  ", stored_rationale="Old words")
    assert d == ri.Assessment(stamp=True, rationale="Control failed in Q3")


def test_a_draft_may_carry_provisional_scores_and_loses_the_stale_rationale():
    d = _decide(changed=True, status_before="draft", status_after="draft", stored_rationale="Old words")
    assert d == ri.Assessment(stamp=True, rationale="")


def test_unrelated_edits_do_not_stamp():
    assert _decide(sends_inherent=True, rationale="Same", stored_rationale="Same") == ri.Assessment(False, None)


def test_a_new_rationale_with_the_scores_reaffirms_the_assessment():
    assert _decide(sends_inherent=True, rationale="Reviewed at RC", stored_rationale="Old") == (
        ri.Assessment(stamp=True, rationale="Reviewed at RC")
    )


def test_leaving_draft_needs_chosen_scores_and_a_rationale():
    leave = dict(status_before="draft", status_after="assessed", previously_assessed=False)
    with pytest.raises(HTTPException) as exc:
        _decide(rationale="Why", **leave)  # scores never chosen
    assert exc.value.detail == ri.LEAVE_DRAFT_DETAIL
    with pytest.raises(HTTPException):
        _decide(sends_inherent=True, **leave)  # no rationale
    # Confirming the scores as they stand, with a reason, is an assessment.
    assert _decide(sends_inherent=True, rationale="Why", **leave).stamp is True
    # Scores recorded earlier plus a stored rationale also let it go.
    assert _decide(status_before="draft", status_after="assessed", stored_rationale="Why").stamp is False


def test_creating_beyond_draft_is_an_assessment():
    with pytest.raises(HTTPException):
        _decide(creating=True, status_before=None, previously_assessed=False, changed=True, sends_inherent=True)
    d = _decide(creating=True, status_before=None, previously_assessed=False, changed=True,
                sends_inherent=True, rationale="Workshop 12 Sep")
    assert d == ri.Assessment(stamp=True, rationale="Workshop 12 Sep")


# ================================================================== target rule ===
def test_target_never_above_residual_or_inherent():
    rule = ri.target_rule_violation
    assert rule(inherent=(4, 5), residual=(3, 4), target=(None, None)) is None
    assert rule(inherent=(4, 5), residual=(3, 4), target=(2, None)) == ri.TARGET_INCOMPLETE_DETAIL
    assert rule(inherent=(4, 5), residual=(3, 4), target=(2, 3)) is None
    assert "residual risk 12" in rule(inherent=(4, 5), residual=(3, 4), target=(4, 4))
    assert "inherent risk 6" in rule(inherent=(2, 3), residual=(None, None), target=(3, 3))


# ============================================================ impact dimensions ===
def test_impact_combines_by_max_or_rounded_up_average():
    assert impact_from_dimensions([2, 5, 3]) == 5
    assert impact_from_dimensions([3, 4], "average") == 4
    assert impact_from_dimensions([2, 2, 3], "average") == 3
    assert impact_from_dimensions([], "max") is None


def test_dimensions_decide_the_impact_of_their_basis():
    fin, reg = uuid.uuid4(), uuid.uuid4()
    rows = [
        {"dimension_id": fin, "basis": "inherent", "score": 2},
        {"dimension_id": reg, "basis": "inherent", "score": 5},
        {"dimension_id": fin, "basis": "residual", "score": 3},
    ]
    assert ri.derive_dimension_impacts(rows, {}, "max") == {"inherent_impact": 5, "residual_impact": 3}
    assert ri.derive_dimension_impacts(rows, {"inherent_impact": 5}, "max")["inherent_impact"] == 5
    with pytest.raises(HTTPException) as exc:
        ri.derive_dimension_impacts(rows, {"inherent_impact": 3}, "max")
    assert exc.value.status_code == 422 and "highest of 5, 2 is 5" in exc.value.detail
    with pytest.raises(HTTPException):
        ri.derive_dimension_impacts(rows + [{"dimension_id": fin, "basis": "inherent", "score": 1}], {}, "max")


# =========================================================== bands and cells ===
def test_default_bands_are_unchanged_and_configured_ones_replace_them():
    assert band_ranges() == [
        (1, 4, Severity.low), (5, 9, Severity.medium), (10, 14, Severity.high), (15, 25, Severity.critical),
    ]
    bands = {"low_max": 3, "medium_max": 7, "high_max": 12}
    assert band_ranges(25, bands)[3] == (13, 25, Severity.critical)
    assert severity_for_score(13, 25, bands) is Severity.critical
    assert severity_for_score(13) is Severity.high


def test_band_thresholds_are_validated():
    assert validate_bands(None, 25) is None
    assert validate_bands({"low_max": 4, "medium_max": 9, "high_max": 14}, 25) == (4, 9, 14)
    for bad in ({"low_max": 5, "medium_max": 5, "high_max": 14}, {"low_max": 4, "medium_max": 9, "high_max": 25},
                {"low_max": 0, "medium_max": 9, "high_max": 14}, {"low_max": 4}):
        with pytest.raises(ValueError):
            validate_bands(bad, 25)
    # Thresholds that no longer fit a shrunk matrix are ignored, not trusted.
    assert band_ranges(9, (4, 9, 14)) == band_ranges(9)


def test_cells_are_validated_and_override_their_score_band():
    assert validate_cells({"2, 5": "high"}, 5) == {"2,5": "high"}
    for bad in ({"6,1": "low"}, {"x": "low"}, {"1,1": "severe"}):
        with pytest.raises(ValueError):
            validate_cells(bad, 5)
    scale = SeverityScale(max_score=25, cells={cell_key(2, 5): "high"})
    assert scale.for_cell(2, 5) is Severity.high      # 10 would be high anyway …
    scale = SeverityScale(max_score=25, cells={cell_key(1, 5): "critical"})
    assert scale.for_cell(1, 5) is Severity.critical  # … 5 would be medium
    assert scale.for_cell(5, 1) is Severity.medium    # the mirror cell is untouched
    assert scale.for_risk(1, 5, None, None) is Severity.critical
    assert scale.for_risk(1, 5, 1, 1) is Severity.low  # residual decides once assessed
    assert scale.for_cell(None, 3) is None


def test_matrix_config_update_distinguishes_unset_from_cleared_bands():
    assert "severity_bands" not in RiskMatrixConfigUpdate(size=5).model_fields_set
    assert "severity_bands" in RiskMatrixConfigUpdate(size=5, severity_bands=None).model_fields_set


# ======================================================= appetite per category ===
def _book():
    ops, fraud, it = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return ops, fraud, it, AppetiteBook(
        appetite=6, tolerance=12,
        by_category={ops: (4, 8)},
        parents={ops: None, fraud: ops, it: None},
    )


def test_a_risk_takes_its_top_level_categorys_appetite_else_the_default():
    ops, fraud, it, book = _book()
    assert book.top_of(fraud) == ops
    assert book.thresholds(fraud) == (4, 8)       # sub-category inherits its L1's
    assert book.thresholds(it) == (6, 12)         # L1 with no appetite -> default
    assert book.thresholds(None) == (6, 12)
    assert book.source_of(fraud) == ops and book.source_of(it) is None
    assert book.status(9, fraud) == "breach" and book.status(9, it) == "elevated"
    assert book.min_tolerance == 8


def test_a_cycle_in_the_category_tree_cannot_hang_the_walk():
    a, b = uuid.uuid4(), uuid.uuid4()
    book = AppetiteBook(parents={a: b, b: a})
    assert book.thresholds(a) == (6, 12)


def test_risk_read_carries_banding_and_appetite_from_context():
    ops, fraud, _it, book = _book()
    now = datetime.now(timezone.utc)
    risk = SimpleNamespace(
        id=uuid.uuid4(), reference="R-1", title="t", description="", category="", category_id=fraud,
        status=RiskStatus.assessed, owner_id=None, inherent_likelihood=1, inherent_impact=5,
        inherent_score=5, residual_likelihood=None, residual_impact=None, residual_score=None,
        annual_loss_frequency=None, single_loss_expectancy=None, annual_loss_expectancy=None,
        treatment_strategy=None, treatment_description="", treatment_owner="", treatment_deadline=None,
        treatment_cost=None, review_frequency="annual", last_review_date=None, next_review_date=None,
        expired_reviews=0, workflow_status="draft", workflow_owner="", created_at=now, updated_at=now,
        target_likelihood=1, target_impact=2,
    )
    scale = SeverityScale(max_score=25, cells={"1,5": "critical"})
    read = RiskRead.model_validate(risk, context={"scale": scale, "appetite": book})
    assert read.inherent_severity is Severity.critical
    assert (read.target_score, read.target_severity) == (2, Severity.low)
    assert (read.appetite_score, read.tolerance_score, read.appetite_category_id) == (4, 8, ops)
    assert read.appetite_status == "elevated"
    # The older context still works and leaves the appetite fields alone.
    plain = RiskRead.model_validate(risk, context={"max_score": 25})
    assert plain.inherent_severity is Severity.medium and plain.appetite_status is None


def test_threshold_pair_is_checked_against_the_matrix():
    risk_program._check_threshold_pair(4, 8, 25, 5)
    with pytest.raises(HTTPException):
        risk_program._check_threshold_pair(9, 8, 25, 5)
    with pytest.raises(HTTPException):
        risk_program._check_threshold_pair(4, 30, 25, 5)


# ============================================================= treatment actions ===
def _action(status="open", due=None, completed_at=None, percent=0):
    return SimpleNamespace(status=status, due_date=due, completed_at=completed_at, percent_complete=percent)


def test_deadline_follows_the_latest_open_action():
    d = date(2026, 9, 1)
    actions = [_action(due=d), _action(due=d + timedelta(days=30)), _action("done", d + timedelta(days=90))]
    assert ri.derive_treatment_deadline(actions) == d + timedelta(days=30)
    closed = [_action("done", d), _action("cancelled", d + timedelta(days=99)), _action("done", d + timedelta(days=5))]
    assert ri.derive_treatment_deadline(closed) == d + timedelta(days=5)
    assert ri.derive_treatment_deadline([_action()]) is None


def test_progress_is_done_over_the_plan_without_cancelled_actions():
    today = date(2026, 9, 12)
    actions = [_action("done"), _action("open", today - timedelta(days=1)), _action("in_progress", today),
               _action("cancelled")]
    assert ri.treatment_progress(actions, today) == {"done": 1, "total": 3, "open": 2, "overdue": 1, "percent": 33}
    assert ri.treatment_progress([], today)["percent"] == 0


def test_done_stamps_completion_once_and_leaving_done_clears_it():
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    a = _action(percent=40)
    ri.apply_action_status(a, status="done", percent=None, now=now)
    assert (a.status, a.percent_complete, a.completed_at) == ("done", 100, now)
    ri.apply_action_status(a, status="done", percent=None, now=now + timedelta(days=1))
    assert a.completed_at == now
    ri.apply_action_status(a, status="in_progress", percent=60, now=now)
    assert (a.percent_complete, a.completed_at) == (60, None)


def test_overdue_treatment_actions_are_a_groupable_family():
    assert "risk-treatment" in notifications.GROUPABLE_FAMILIES
    assert "risk-treatment" not in notifications.NEVER_GROUPED


# ======================================================================= fakes ===
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    """``scalars`` answers the stored impact-dimension query with ``dims``."""

    def __init__(self, dims=()):
        self.added = []
        self.flushed = 0
        self.dims = list(dims)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1

    async def scalars(self, *_a, **_k):
        return _Rows(self.dims)


@pytest.fixture
def audit_log(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(risks_api.audit, "record", record)
    return calls


@pytest.fixture
def io(monkeypatch):
    state = {"actions": 0}

    async def load(db, risk_id):
        return state["risk"]

    async def read(db, risk_id, user):
        return state.get("risk")

    async def size(db, tenant_id):
        return 5

    async def ref(db):
        return "R-900"

    async def action_count(db, risk_id):
        return state["actions"]

    async def settings(db, tenant_id):
        return SimpleNamespace(impact_mode=state.get("impact_mode", "max"))

    async def check_lookup(db, lookup_id, key, field):
        assert key == "impact_dimension"

    monkeypatch.setattr(risks_api, "_load_risk", load)
    monkeypatch.setattr(risks_api, "_read", read)
    monkeypatch.setattr(risks_api, "get_matrix_size", size)
    monkeypatch.setattr(risks_api, "_next_reference", ref)
    monkeypatch.setattr(risks_api, "_action_count", action_count)
    monkeypatch.setattr(risks_api, "get_or_create_settings", settings)
    monkeypatch.setattr(risks_api.master_data, "check_lookup", check_lookup)
    return state


def _stored(**kw):
    base = dict(
        id=uuid.uuid4(), reference="R-117", title="Card fraud", status=RiskStatus.assessed,
        inherent_likelihood=3, inherent_impact=4, residual_likelihood=None, residual_impact=None,
        residual_override_reason="", needs_review=False, review_reason="", review_frequency=None,
        last_review_date=None, annual_loss_expectancy=None, target_likelihood=None, target_impact=None,
        assessment_rationale="Workshop", last_assessed_at=None, last_assessed_by_id=None,
        treatment_deadline=None, owner_id=None, treatment_owner="", treatment_owner_id=None,
        category="", category_id=None, workflow_owner="", workflow_owner_id=None,
        identified_by_id=None, cause="", event="", consequence="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _created(db) -> "risks_api.Risk":
    return next(o for o in db.added if isinstance(o, risks_api.Risk))


# ============================================================ endpoints: create ===
async def test_create_composes_the_title_and_defaults_the_identifier(io, audit_log):
    db, me = FakeDB(), _user()
    await risks_api.create_risk(
        RiskCreate(event="Core banking outage", cause="failed patch", consequence="branches offline"), db, me
    )
    risk = _created(db)
    assert risk.title == "Core banking outage, caused by failed patch, resulting in branches offline"
    assert risk.identified_by_id == me.id
    # Unscored draft: stored 1x1, not stamped.
    assert (risk.inherent_likelihood, risk.inherent_impact, risk.last_assessed_at) == (1, 1, None)


async def test_create_without_title_or_event_is_422(io, audit_log):
    with pytest.raises(HTTPException) as exc:
        await risks_api.create_risk(RiskCreate(cause="phishing"), FakeDB(), _user())
    assert exc.value.detail == ri.TITLE_NEEDS_STATEMENT_DETAIL


async def test_a_scored_draft_is_stamped_but_needs_no_rationale(io, audit_log):
    db, me = FakeDB(), _user()
    await risks_api.create_risk(RiskCreate(title="x", inherent_likelihood=3, inherent_impact=4), db, me)
    risk = _created(db)
    assert risk.last_assessed_by_id == me.id and risk.last_assessed_at is not None
    assert risk.status == RiskStatus.draft


async def test_creating_an_assessed_risk_needs_scores_and_rationale(io, audit_log):
    with pytest.raises(HTTPException) as exc:
        await risks_api.create_risk(
            RiskCreate(title="x", status=RiskStatus.assessed, assessment_rationale="why"), FakeDB(), _user()
        )
    assert exc.value.detail == ri.LEAVE_DRAFT_DETAIL
    db = FakeDB()
    await risks_api.create_risk(
        RiskCreate(title="x", status=RiskStatus.assessed, inherent_likelihood=2, inherent_impact=3,
                   assessment_rationale="RCSA workshop"), db, _user(),
    )
    assert _created(db).assessment_rationale == "RCSA workshop"


async def test_create_derives_impact_from_dimensions(io, audit_log):
    fin, reg = uuid.uuid4(), uuid.uuid4()
    db = FakeDB()
    await risks_api.create_risk(
        RiskCreate(
            title="x", inherent_likelihood=3,
            impact_dimensions=[ImpactDimensionIn(dimension_id=fin, score=2),
                               ImpactDimensionIn(dimension_id=reg, score=4)],
        ),
        db, _user(),
    )
    risk = _created(db)
    assert risk.inherent_impact == 4
    dims = [o for o in db.added if isinstance(o, risks_api.RiskImpactDimension)]
    assert sorted(d.score for d in dims) == [2, 4] and all(d.risk_id == risk.id for d in dims)


async def test_create_refuses_an_impact_that_disagrees_with_its_dimensions(io, audit_log):
    io["impact_mode"] = "average"
    with pytest.raises(HTTPException) as exc:
        await risks_api.create_risk(
            RiskCreate(title="x", inherent_likelihood=3, inherent_impact=5,
                       impact_dimensions=[ImpactDimensionIn(dimension_id=uuid.uuid4(), score=2),
                                          ImpactDimensionIn(dimension_id=uuid.uuid4(), score=3)]),
            FakeDB(), _user(),
        )
    assert exc.value.status_code == 422 and "average" in exc.value.detail


async def test_create_refuses_a_target_above_inherent(io, audit_log):
    with pytest.raises(HTTPException) as exc:
        await risks_api.create_risk(
            RiskCreate(title="x", inherent_likelihood=2, inherent_impact=2, target_likelihood=3, target_impact=2),
            FakeDB(), _user(),
        )
    assert "Target risk 6" in exc.value.detail


# ============================================================ endpoints: update ===
async def test_update_refuses_a_score_change_without_a_rationale(io, audit_log):
    io["risk"] = _stored()
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(io["risk"].id, RiskUpdate(inherent_impact=5), FakeDB(), _user())
    assert exc.value.detail == ri.RATIONALE_REQUIRED_DETAIL
    assert io["risk"].inherent_impact == 4 and audit_log == []


async def test_update_with_a_rationale_stamps_the_assessment(io, audit_log):
    me = _user()
    io["risk"] = _stored()
    await risks_api.update_risk(
        io["risk"].id, RiskUpdate(inherent_impact=5, assessment_rationale="New fraud typology"), FakeDB(), me
    )
    risk = io["risk"]
    assert (risk.inherent_impact, risk.assessment_rationale, risk.last_assessed_by_id) == (5, "New fraud typology", me.id)
    assert audit_log[0]["changes"]["assessed"] == "inherent_impact"


async def test_resaving_the_form_unchanged_does_not_stamp(io, audit_log):
    io["risk"] = _stored()
    await risks_api.update_risk(
        io["risk"].id,
        RiskUpdate(title="Card fraud v2", inherent_likelihood=3, inherent_impact=4, assessment_rationale="Workshop"),
        FakeDB(), _user(),
    )
    assert io["risk"].title == "Card fraud v2" and io["risk"].last_assessed_at is None


async def test_a_null_inherent_score_means_not_chosen(io, audit_log):
    io["risk"] = _stored(status=RiskStatus.draft)
    await risks_api.update_risk(
        io["risk"].id, RiskUpdate(inherent_likelihood=None, inherent_impact=None, title="t"), FakeDB(), _user()
    )
    assert io["risk"].inherent_likelihood == 3


async def test_moving_a_never_scored_draft_on_is_422(io, audit_log):
    io["risk"] = _stored(status=RiskStatus.draft, assessment_rationale="")
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(io["risk"].id, RiskUpdate(status=RiskStatus.assessed), FakeDB(), _user())
    assert exc.value.detail == ri.LEAVE_DRAFT_DETAIL


async def test_the_deadline_follows_the_actions_once_there_are_any(io, audit_log):
    io["risk"], io["actions"] = _stored(), 2
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(io["risk"].id, RiskUpdate(treatment_deadline=date(2027, 1, 1)), FakeDB(), _user())
    assert "follows the treatment actions" in exc.value.detail
    io["actions"] = 0
    await risks_api.update_risk(io["risk"].id, RiskUpdate(treatment_deadline=date(2027, 1, 1)), FakeDB(), _user())
    assert io["risk"].treatment_deadline == date(2027, 1, 1)


async def test_an_impact_scored_by_dimension_moves_only_with_its_dimensions(io, audit_log):
    io["risk"] = _stored()
    db = FakeDB(dims=[SimpleNamespace(basis="inherent", dimension_id=uuid.uuid4(), score=4)])
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(
            io["risk"].id, RiskUpdate(inherent_impact=5, assessment_rationale="why"), db, _user()
        )
    assert "derived from its dimension scores" in exc.value.detail


async def test_update_refuses_a_target_above_the_residual(io, audit_log):
    io["risk"] = _stored(residual_likelihood=2, residual_impact=2)
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(io["risk"].id, RiskUpdate(target_likelihood=3, target_impact=2), FakeDB(), _user())
    assert "residual risk 4" in exc.value.detail


# ============================================================ endpoints: assess ===
async def test_assess_keeps_an_incomplete_draft_as_draft(io, audit_log):
    io["risk"] = _stored(status=RiskStatus.draft, assessment_rationale="")
    await risks_api.assess_risk(io["risk"].id, RiskAssessment(residual_likelihood=2, residual_impact=2), FakeDB(), _user())
    assert io["risk"].status == RiskStatus.draft and io["risk"].residual_likelihood == 2


async def test_assess_moves_an_assessed_draft_on_with_a_rationale(io, audit_log):
    io["risk"] = _stored(status=RiskStatus.draft, last_assessed_at=datetime.now(timezone.utc))
    await risks_api.assess_risk(
        io["risk"].id,
        RiskAssessment(residual_likelihood=2, residual_impact=2, assessment_rationale="Two controls tested"),
        FakeDB(), _user(),
    )
    assert io["risk"].status == RiskStatus.assessed
    assert io["risk"].assessment_rationale == "Two controls tested"
