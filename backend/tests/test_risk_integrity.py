"""Risk-register integrity rules (product review, phase 0: D-01 and F-02).

No database: the pure rules in ``services.risk_integrity`` are tested directly, and the
endpoints are driven with a fake session, stubbed loaders and a captured audit trail.

Pinned here:

1. **Residual never above inherent** unless a reason is written down by someone who may
   accept risk — on create, on update (the merged state, not just the payload), on the
   assess path and on the accept-residual path.
2. **Correcting the residual clears the review flag** it raised, and only that reason.
3. **Orphaned means no live link of any kind**, the purge archives only ticked ids that
   are still orphaned, writes one audit row per risk, and respects dual control.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.v1 import risks as risks_api
from app.db.data_repairs import RESIDUAL_REVIEW_REASON
from app.models.risk import Risk
from app.schemas.risk import OrphanPurgeRequest, ResidualAcceptance, RiskAssessment, RiskCreate, RiskUpdate
from app.services import risk_integrity as ri

WRITER = ["risk:read", "risk:write"]
ACCEPTER = ["risk:read", "risk:write", "risk:accept"]


def _user(perms):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x", permission_codes=perms)


def _risk(**kw):
    base = dict(
        id=uuid.uuid4(), reference="R-117", title="Card fraud",
        inherent_likelihood=3, inherent_impact=5,
        residual_likelihood=None, residual_impact=None,
        residual_override_reason="", needs_review=False, review_reason="",
        review_frequency=None, last_review_date=None, annual_loss_expectancy=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ================================================================ residual rule ===
@pytest.mark.parametrize(
    "inh,res,expected",
    [
        ((3, 5), (4, 5), True),    # 20 > 15: the reviewed R-117
        ((3, 5), (5, 3), False),   # equal products are fine
        ((3, 5), (2, 5), False),
        ((3, 5), (None, 5), False),  # residual not assessed yet
        ((3, 5), (None, None), False),
    ],
)
def test_residual_exceeds_inherent(inh, res, expected):
    assert ri.residual_exceeds_inherent(*inh, *res) is expected


def _violation(reason="", can_accept=False, changes=True, res=(4, 5)):
    return ri.residual_rule_violation(
        inherent_likelihood=3, inherent_impact=5,
        residual_likelihood=res[0], residual_impact=res[1],
        override_reason=reason, can_accept=can_accept, changes_scoring=changes,
    )


def test_residual_within_inherent_needs_nothing():
    assert _violation(res=(2, 5)) is None


def test_residual_above_inherent_without_reason_is_422():
    assert _violation() == (422, ri.RESIDUAL_ABOVE_INHERENT_DETAIL)
    assert _violation(reason="   ") == (422, ri.RESIDUAL_ABOVE_INHERENT_DETAIL)
    # Even a risk acceptor must write the reason down.
    assert _violation(can_accept=True)[0] == 422


def test_residual_above_inherent_with_reason_needs_risk_accept():
    assert _violation(reason="Control failed in prod") == (403, ri.RESIDUAL_OVERRIDE_NEEDS_ACCEPT_DETAIL)
    assert _violation(reason="Control failed in prod", can_accept=True) is None


def test_a_standing_override_does_not_block_unrelated_edits():
    # A colleague without risk:accept can still edit the title of a risk whose override
    # an acceptor recorded earlier — but not if no reason stands.
    assert _violation(reason="Recorded by CRO", changes=False) is None
    assert _violation(reason="", changes=False)[0] == 422


def test_enforce_raises_http_exception():
    with pytest.raises(HTTPException) as exc:
        ri.enforce_residual_rule(
            inherent_likelihood=3, inherent_impact=5, residual_likelihood=4,
            residual_impact=5, override_reason="", can_accept=True,
        )
    assert exc.value.status_code == 422
    assert exc.value.detail == (
        "Residual risk cannot be higher than inherent risk. "
        "Lower the residual, or record an override reason."
    )


def test_can_accept_risk_reads_permission_codes():
    assert ri.can_accept_risk(_user(ACCEPTER))
    assert not ri.can_accept_risk(_user(WRITER))
    assert not ri.can_accept_risk(SimpleNamespace())


def test_scoring_fields_match_the_models_and_schemas():
    for name in ri.SCORING_FIELDS:
        assert hasattr(Risk, name)
        assert name in RiskUpdate.model_fields
        assert name in RiskCreate.model_fields
    assert "residual_override_reason" in RiskAssessment.model_fields


# ================================================================ review reasons ===
def test_review_reasons_append_once_and_remove_individually():
    text = ri.add_review_reason("", "Asset removed – review: SWIFT gateway")
    text = ri.add_review_reason(text, RESIDUAL_REVIEW_REASON)
    text = ri.add_review_reason(text, RESIDUAL_REVIEW_REASON)  # no duplicate
    assert ri.review_reasons(text) == ["Asset removed – review: SWIFT gateway", RESIDUAL_REVIEW_REASON]
    assert ri.remove_review_reason(text, RESIDUAL_REVIEW_REASON) == "Asset removed – review: SWIFT gateway"


def test_clear_residual_flag_only_once_corrected():
    risk = _risk(residual_likelihood=4, residual_impact=5, needs_review=True,
                 review_reason=RESIDUAL_REVIEW_REASON)
    assert ri.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON) is False
    assert risk.needs_review is True

    risk.residual_likelihood = 2  # lowered: 10 <= 15
    assert ri.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON) is True
    assert (risk.needs_review, risk.review_reason) == (False, "")


def test_clear_residual_flag_by_override_keeps_other_reasons():
    other = "Asset removed – review: Core DB"
    risk = _risk(residual_likelihood=4, residual_impact=5, needs_review=True,
                 review_reason=f"{other}\n{RESIDUAL_REVIEW_REASON}",
                 residual_override_reason="Compensating control withdrawn")
    assert ri.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON) is True
    assert risk.needs_review is True
    assert risk.review_reason == other


def test_clear_residual_flag_ignores_risks_flagged_for_something_else():
    risk = _risk(needs_review=True, review_reason="Asset removed – review: X")
    assert ri.clear_residual_flag(risk, RESIDUAL_REVIEW_REASON) is False
    assert risk.needs_review is True


def test_asset_removal_flags_without_clobbering():
    a = _risk(review_reason="Earlier reason", needs_review=True)
    b = _risk()
    assert ri.flag_for_asset_removal([a, b], "SWIFT gateway") == 2
    assert a.review_reason == "Earlier reason\nAsset removed – review: SWIFT gateway"
    assert (b.needs_review, b.review_reason) == (True, "Asset removed – review: SWIFT gateway")


# ============================================================== orphan predicate ===
def test_a_risk_that_never_had_an_asset_is_never_orphaned():
    assert ri.is_orphaned(deleted_asset_links=0, live_links=ri.empty_link_counts()) is False


def test_only_a_risk_with_no_live_link_of_any_kind_is_orphaned():
    assert ri.is_orphaned(deleted_asset_links=2, live_links=ri.empty_link_counts()) is True
    for key in ri.LINK_KEYS:
        counts = ri.empty_link_counts()
        counts[key] = 1
        assert ri.is_orphaned(deleted_asset_links=2, live_links=counts) is False, key


def test_every_risk_relationship_is_counted_as_a_link():
    """A new relationship on Risk must be added to LINK_KINDS, or the cleanup could
    archive a risk that is still in use."""
    from sqlalchemy import inspect

    rels = {r.key for r in inspect(Risk).relationships} - {"acceptances"}
    missing = rels - set(ri.LINK_KEYS)
    assert not missing, f"Add these to risk_integrity.LINK_KINDS: {sorted(missing)}"


def test_link_count_query_covers_every_kind_and_compiles_for_postgres():
    sql = str(ri.link_count_query([uuid.uuid4()]).compile(dialect=postgresql.dialect()))
    assert sql.count("UNION ALL") == len(ri.LINK_KEYS) - 1
    for key in ri.LINK_KEYS:
        assert f"'{key}' AS kind" in sql, key
    # Soft-deleted targets never count as live.
    for table in ("controls", "business_units", "requirements", "issues", "rcsa_assessments"):
        assert f"{table}.deleted IS false" in sql, table


# ================================================================ purge request ===
def test_purge_request_requires_ids_and_a_reason():
    rid = uuid.uuid4()
    with pytest.raises(ValidationError):
        OrphanPurgeRequest(risk_ids=[], reason="duplicates")
    with pytest.raises(ValidationError):
        OrphanPurgeRequest(reason="duplicates")
    with pytest.raises(ValidationError):
        OrphanPurgeRequest(risk_ids=[rid], reason="   ")
    with pytest.raises(ValidationError):
        OrphanPurgeRequest(risk_ids=[rid])
    assert OrphanPurgeRequest(risk_ids=[rid], reason="  generated in error ").reason == "generated in error"


# ======================================================================= fakes ===
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.flushed = 0

    async def scalars(self, *_a, **_k):
        return _Rows(self.rows)

    async def flush(self):
        self.flushed += 1


@pytest.fixture
def audit_log(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(risks_api.audit, "record", record)
    return calls


@pytest.fixture
def stub_io(monkeypatch):
    """Stub the loaders so endpoints run without a database."""
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
    return state


# ============================================================ endpoints: update ===
async def test_update_rejects_lowering_inherent_below_a_stored_residual(stub_io, audit_log):
    stub_io["risk"] = _risk(inherent_likelihood=4, inherent_impact=5, residual_likelihood=4, residual_impact=4)
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(
            stub_io["risk"].id, RiskUpdate(inherent_likelihood=3), FakeDB(), _user(ACCEPTER)
        )
    assert exc.value.status_code == 422
    assert stub_io["risk"].inherent_likelihood == 4  # nothing written
    assert audit_log == []


async def test_update_override_needs_risk_accept(stub_io, audit_log):
    stub_io["risk"] = _risk()
    # Phase 2: a score change also carries its assessment rationale.
    body = RiskUpdate(residual_likelihood=4, residual_impact=5, residual_override_reason="Control withdrawn",
                      assessment_rationale="Control withdrawn")
    with pytest.raises(HTTPException) as exc:
        await risks_api.update_risk(stub_io["risk"].id, body, FakeDB(), _user(WRITER))
    assert exc.value.status_code == 403
    assert exc.value.detail == ri.RESIDUAL_OVERRIDE_NEEDS_ACCEPT_DETAIL

    await risks_api.update_risk(stub_io["risk"].id, body, FakeDB(), _user(ACCEPTER))
    assert (stub_io["risk"].residual_likelihood, stub_io["risk"].residual_override_reason) == (4, "Control withdrawn")
    assert len(audit_log) == 1


async def test_update_that_resends_unchanged_scores_passes_for_a_writer(stub_io, audit_log):
    # The form sends every field; an acceptor's standing override must not lock the
    # record against a writer editing its title.
    stub_io["risk"] = _risk(residual_likelihood=4, residual_impact=5, residual_override_reason="CRO decision")
    body = RiskUpdate(title="Card-not-present fraud", inherent_likelihood=3, inherent_impact=5,
                      residual_likelihood=4, residual_impact=5, residual_override_reason="CRO decision")
    await risks_api.update_risk(stub_io["risk"].id, body, FakeDB(), _user(WRITER))
    assert stub_io["risk"].title == "Card-not-present fraud"


async def test_update_that_corrects_the_residual_clears_the_flag(stub_io, audit_log):
    stub_io["risk"] = _risk(residual_likelihood=4, residual_impact=5, needs_review=True,
                            review_reason=RESIDUAL_REVIEW_REASON)
    await risks_api.update_risk(
        stub_io["risk"].id, RiskUpdate(residual_likelihood=2, assessment_rationale="Lowered after review"),
        FakeDB(), _user(WRITER),
    )
    assert (stub_io["risk"].needs_review, stub_io["risk"].review_reason) == (False, "")
    assert "review flag cleared" in audit_log[0]["changes"]["review_reason"]


async def test_create_rejects_residual_above_inherent(stub_io, audit_log):
    body = RiskCreate(title="x", inherent_likelihood=3, inherent_impact=5, residual_likelihood=4, residual_impact=5)
    with pytest.raises(HTTPException) as exc:
        await risks_api.create_risk(body, FakeDB(), _user(ACCEPTER))
    assert exc.value.status_code == 422


# ============================================================ endpoints: assess ===
async def test_assess_path_enforces_the_rule(stub_io, audit_log):
    stub_io["risk"] = _risk(status=risks_api.RiskStatus.assessed)
    with pytest.raises(HTTPException) as exc:
        await risks_api.assess_risk(
            stub_io["risk"].id, RiskAssessment(residual_likelihood=4, residual_impact=5), FakeDB(), _user(ACCEPTER)
        )
    assert exc.value.status_code == 422
    await risks_api.assess_risk(
        stub_io["risk"].id,
        RiskAssessment(residual_likelihood=4, residual_impact=5, residual_override_reason="Control withdrawn",
                       assessment_rationale="Control withdrawn"),
        FakeDB(), _user(ACCEPTER),
    )
    assert stub_io["risk"].residual_override_reason == "Control withdrawn"


async def test_accept_residual_override_above_inherent_needs_risk_accept(stub_io, audit_log, monkeypatch):
    stub_io["risk"] = _risk(controls=[], status=risks_api.RiskStatus.assessed)

    async def policy(db, tenant_id):
        return None

    monkeypatch.setattr(risks_api, "get_or_create_residual_policy", policy)
    monkeypatch.setattr(risks_api, "policy_spec", lambda p: None)
    monkeypatch.setattr(
        risks_api, "suggest_residual",
        lambda *a, **k: SimpleNamespace(likelihood=2, impact=5, rationale=["x"]),
    )
    body = ResidualAcceptance(likelihood=4, impact=5, override_reason="Control withdrawn")
    with pytest.raises(HTTPException) as exc:
        await risks_api.accept_residual(stub_io["risk"].id, body, FakeDB(), _user(WRITER))
    assert exc.value.status_code == 403
    await risks_api.accept_residual(stub_io["risk"].id, body, FakeDB(), _user(ACCEPTER))
    assert stub_io["risk"].residual_likelihood == 4


# ====================================================== endpoints: mark reviewed ===
async def test_mark_reviewed_refused_while_residual_still_above_inherent(stub_io, audit_log):
    stub_io["risk"] = _risk(residual_likelihood=4, residual_impact=5, needs_review=True,
                            review_reason=RESIDUAL_REVIEW_REASON)
    with pytest.raises(HTTPException) as exc:
        await risks_api.mark_risk_reviewed(stub_io["risk"].id, FakeDB(), _user(WRITER))
    assert exc.value.status_code == 409
    assert stub_io["risk"].needs_review is True


async def test_mark_reviewed_clears_and_audits(stub_io, audit_log):
    stub_io["risk"] = _risk(needs_review=True, review_reason="Asset removed – review: Core DB")
    await risks_api.mark_risk_reviewed(stub_io["risk"].id, FakeDB(), _user(WRITER))
    assert (stub_io["risk"].needs_review, stub_io["risk"].review_reason) == (False, "")
    assert audit_log[0]["action"] == "mark_reviewed"
    assert audit_log[0]["entity_id"] == stub_io["risk"].id


# ============================================================= endpoints: purge ===
def _purge_setup(monkeypatch, orphaned, *, dual_control_required=False):
    async def scan(db):
        return ri.OrphanScan(orphaned=[r.id for r in orphaned])

    async def required(db, module, action, amount=None):
        assert (module, action) == ("risk", "bulk_archive")
        return dual_control_required, None

    monkeypatch.setattr(risks_api.risk_integrity, "scan_orphans", scan)
    monkeypatch.setattr(risks_api.dual_control, "dual_control_required", required)


async def test_purge_archives_only_ticked_ids_that_are_still_orphaned(monkeypatch, audit_log):
    a, b = _risk(reference="R-001", deleted=False), _risk(reference="R-002", deleted=False)
    _purge_setup(monkeypatch, [a])
    stale = uuid.uuid4()  # gained a live link since the preview
    res = await risks_api.purge_orphaned_risks(
        OrphanPurgeRequest(risk_ids=[a.id, stale], reason="Generated against retired assets"),
        FakeDB([a]), _user(WRITER),
    )
    assert (res.archived, res.references, res.skipped) == (1, ["R-001"], 1)
    assert a.deleted is True and b.deleted is False
    # One row per archived risk, plus one summary row.
    per_risk = [c for c in audit_log if c["entity_id"] is not None]
    assert [c["entity_id"] for c in per_risk] == [a.id]
    assert "Generated against retired assets" in per_risk[0]["summary"]
    summary = [c for c in audit_log if c["entity_id"] is None]
    assert len(summary) == 1 and summary[0]["changes"]["reason"] == "Generated against retired assets"


async def test_purge_is_refused_under_dual_control(monkeypatch, audit_log):
    a = _risk(deleted=False)
    _purge_setup(monkeypatch, [a], dual_control_required=True)
    with pytest.raises(HTTPException) as exc:
        await risks_api.purge_orphaned_risks(
            OrphanPurgeRequest(risk_ids=[a.id], reason="cleanup"), FakeDB([a]), _user(WRITER)
        )
    assert exc.value.status_code == 403
    assert a.deleted is False
    assert audit_log == []


async def test_purge_with_nothing_orphaned_archives_nothing(monkeypatch, audit_log):
    _purge_setup(monkeypatch, [])
    res = await risks_api.purge_orphaned_risks(
        OrphanPurgeRequest(risk_ids=[uuid.uuid4()], reason="cleanup"), FakeDB([]), _user(WRITER)
    )
    assert (res.archived, res.skipped) == (0, 1)
    assert audit_log == []


def test_a_risk_in_the_hierarchy_is_never_an_orphan():
    # Phase 3: a risk with live children, or under a live parent, is in use.
    import uuid as _uuid

    from sqlalchemy.dialects import postgresql

    from app.services import risk_integrity as ri

    assert {"child_risks", "parent_risk"} <= set(ri.LINK_KEYS)
    sql = str(ri.link_count_query([_uuid.uuid4()]).compile(dialect=postgresql.dialect()))
    assert "'child_risks'" in sql and "'parent_risk'" in sql
    counts = ri.empty_link_counts()
    counts["child_risks"] = 2
    assert not ri.is_orphaned(deleted_asset_links=1, live_links=counts)
