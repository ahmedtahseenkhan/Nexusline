"""Product review phase 4A — loose ends from the 17 September re-check.

No database: pure rules are tested directly, queries are compiled for PostgreSQL, and
endpoints run against small fakes.

Pinned here:

1. **Hierarchy figures** — roll-ups and the board tree band, rank and count breaches
   over the board register only; drafts, never-scored and settled risks stay listed,
   marked ``in_figures=False`` and counted in ``not_in_figures``; a never-scored draft
   has no score. The heat map aggregates to one level at each branch's worst risk.
2. **Register PDF** — takes the list endpoint's own filter dependency, so every list
   filter (``pending_validation``, ``needs_review``, ``risk_type``, ``source``…) narrows
   it, and prints each active filter on the cover.
3. **Restoring a migrated risk** — withdraws its pending candidate when every source is
   back and the migration made it; otherwise removes only the restored risk's assets.
4. **Pending suggestions** — served from the organisation's cache while the fingerprint
   matches, recounted when it moves or the row is a day old.
5. **One eligibility rule** — route-stage roles (holders need ``workflow:approve``)
   apply to the Approvals list, the decide endpoint, My Work, recipients and e-mail links.
6. **KRI feed rate limit** — token bucket; the feed answers 429 with ``Retry-After``.
"""
from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - registers every mapper
from app.api.v1 import approvals as approvals_api
from app.api.v1 import operational_risk as kri_api
from app.api.v1 import pdf as pdf_api
from app.api.v1 import risks as risks_api
from app.core.config import settings
from app.models.approval import ApprovalAction, ApprovalRequest
from app.models.enums import ApprovalStatus
from app.schemas import operational_risk as kri_schemas
from app.schemas.risk import RiskHierarchyNode, RiskRollup
from app.services import action_tokens as at
from app.services import clause_suggestions as cs
from app.services import legacy_risk_migration as lrm
from app.services import my_work as mw
from app.services import notifications as ns
from app.services import rate_limit
from app.services import risk_hierarchy as rh
from app.services.notifications import Directory, DirectoryUser
from app.services.risk_hierarchy import RiskFacts
from app.services.risk_scoring import AppetiteBook, SeverityScale

NOW = datetime.now(timezone.utc)
FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ============================================================ 1. hierarchy figures ===
def _risk(ref, parent=None, level=None, inh=(1, 1), res=(None, None), status="assessed", assessed=NOW):
    return RiskFacts(
        id=uuid.uuid4(), parent_id=parent.id if parent else None, level=level, reference=ref, title=ref,
        status=status, inherent_likelihood=inh[0], inherent_impact=inh[1],
        residual_likelihood=res[0], residual_impact=res[1], last_assessed_at=assessed,
    )


@pytest.fixture
def mixed():
    e1 = _risk("E1", level=1)
    c1 = _risk("C1", e1, 2)
    live = _risk("S1", c1, 3, inh=(3, 3))  # 9, medium — the only one counted
    draft_unscored = _risk("S2", c1, 3, status="draft", assessed=None)  # stored 1x1 placeholder
    draft_scored = _risk("S3", c1, 3, inh=(5, 5), status="draft")  # scored but still a draft
    closed = _risk("S4", c1, 3, inh=(5, 5), status="closed")  # settled
    accepted = _risk("S5", c1, 3, inh=(4, 5), status="accepted")
    all_ = [e1, c1, live, draft_unscored, draft_scored, closed, accepted]
    return SimpleNamespace(e1=e1, c1=c1, live=live, draft_unscored=draft_unscored, draft_scored=draft_scored,
                           closed=closed, all=all_)


def test_a_rollup_counts_the_board_register_only(mixed):
    book = AppetiteBook(appetite=4, tolerance=6)
    result = rh.rollup(mixed.e1, rh.children_index(mixed.all), SeverityScale(), book)
    assert result.total == 6 and result.not_in_figures == 4
    # C1 (assessed, 1x1) and S1 are counted; the 25s belong to a draft and a closed risk.
    assert result.by_severity == {"low": 1, "medium": 1, "high": 0, "critical": 0}
    assert result.worst_exposure.reference == "S1"  # not the 25s: a draft and a closed risk
    assert result.breaches == 1  # S1 at 9 > 6; the closed and accepted 25/20 are not breaches
    by_ref = {s.reference: s for s in result.descendants}
    assert by_ref["S2"].scored is False and by_ref["S2"].severity is None and by_ref["S2"].exposure is None
    assert by_ref["S3"].in_figures is False and by_ref["S3"].severity == "critical"
    assert by_ref["S4"].appetite_status is None and by_ref["S1"].in_figures is True
    read = RiskRollup.model_validate(result, from_attributes=True)
    assert read.not_in_figures == 4 and read.descendants[0].in_figures is True


def test_the_board_tree_marks_what_is_not_in_its_figures(mixed):
    roots = rh.build_tree(mixed.all, max_level=3, scale=SeverityScale())
    c1 = roots[0].children[0]
    assert c1.descendants_count == 5 and c1.not_in_figures == 4 and c1.worst.reference == "S1"
    assert c1.by_severity["critical"] == 0
    shown = {n.reference: n for n in c1.children}
    assert shown["S2"].in_figures is False and shown["S2"].scored is False
    read = RiskHierarchyNode.model_validate(roots[0], from_attributes=True)
    assert read.children[0].not_in_figures == 4


def test_the_heat_map_aggregates_to_a_level_at_the_worst_branch_risk(mixed):
    other = _risk("E2", level=1, status="draft", assessed=None)
    only_draft = _risk("C2", other, 2, inh=(5, 5), status="draft")
    risks = [*mixed.all, other, only_draft]
    cells = rh.level_cells(risks, 1)
    assert [(c.risk.reference, c.inherent, c.residual) for c in cells] == [("E1", (3, 3), (3, 3))]
    # E1 itself is 1x1 but scored and live, and its branch's worst is S1; E2 holds only a draft.
    register = rh.level_cells(risks, 1, counted=lambda r: r.scored)
    assert [(c.risk.reference, c.inherent) for c in register] == [("E1", (5, 5)), ("E2", (5, 5))]
    assert [c.risk.reference for c in rh.level_cells(risks, 3)] == ["S1"]


def test_the_risk_matrix_takes_a_level():
    from app.api.v1 import risk_program

    params = inspect.signature(risk_program.risk_matrix).parameters
    assert "level" in params and "level_cells" in inspect.getsource(risk_program.risk_matrix)


# ================================================================ 2. register PDF ===
def _query_params(path, method="get"):
    from app.main import app

    return {p["name"] for p in app.openapi()["paths"][path][method]["parameters"]}


def test_the_pdf_takes_every_list_filter():
    listing = _query_params("/api/v1/risks") - {"sort_by", "sort_dir", "limit", "offset"}
    report = _query_params("/api/v1/reports/pdf/risk-register") - {"details"}
    assert listing == report
    assert {"pending_validation", "needs_review", "risk_type", "source", "appetite"} <= report


def test_one_filter_builder_narrows_both():
    f = risks_api.RiskListFilters(
        pending_validation=True, needs_review=True, risk_type="operational", source="audit", level="none",
    )
    text = _sql(f.statement(AppetiteBook(appetite=6, tolerance=12)))
    assert "risks.status = 'draft'" in text and "risks.needs_review IS true" in text
    assert "risks.risk_type = 'operational'" in text and "risks.source = 'audit'" in text
    assert "risks.level IS NULL" in text
    assert "filters.statement" in inspect.getsource(pdf_api.risk_register_report)
    assert "filters.statement" in inspect.getsource(risks_api.list_risks)


async def test_the_cover_names_every_active_filter():
    unit_id = uuid.uuid4()

    class DB:
        async def get(self, model, key):
            return SimpleNamespace(name="Retail Banking") if key == unit_id else None

    f = risks_api.RiskListFilters(
        business_unit_id=unit_id, pending_validation=True, needs_review=True, risk_type="operational",
        source="internal_audit", appetite="breach", level="2",
    )
    label = await pdf_api._scope_label(DB(), f)
    for part in ("Retail Banking", "Pending validation", "Flagged for review", "Risk type: operational",
                 "Source: internal audit", "above tolerance", "category (L2)"):
        assert part in label, part
    assert await pdf_api._scope_label(DB(), risks_api.RiskListFilters()) == "Whole register"


def test_the_register_export_sends_the_table_filters():
    page = (FRONTEND / "app" / "(app)" / "risks" / "page.tsx").read_text(encoding="utf-8")
    assert "api.pdfRiskRegister(exportFilters" in page


# ==================================================== 3. restoring a migrated risk ===
A, B, C = (uuid.uuid4() for _ in range(3))
R1, R2 = uuid.uuid4(), uuid.uuid4()


def test_restoring_every_source_withdraws_the_candidate_the_migration_made():
    out = lrm.restore_outcome(
        restored_id=R1, created_by_migration=True, sources={R1, R2}, live_sources={R1, R2},
        assets_by_source={R1: {A}, R2: {B}}, candidate_assets={A, B},
    )
    assert out.action == lrm.WITHDRAW


def test_restoring_one_source_removes_only_its_assets():
    out = lrm.restore_outcome(
        restored_id=R1, created_by_migration=True, sources={R1, R2}, live_sources={R1},
        assets_by_source={R1: {A, C}, R2: {B, C}}, candidate_assets={A, B, C},
    )
    # C is still carried by the archived R2, so it stays.
    assert out.action == lrm.TRIM and out.remove_assets == {A}


def test_a_joined_candidate_is_trimmed_not_withdrawn():
    out = lrm.restore_outcome(
        restored_id=R1, created_by_migration=False, sources={R1}, live_sources={R1},
        assets_by_source={R1: {A}}, candidate_assets={A, B},
    )
    assert out.action == lrm.TRIM and out.remove_assets == {A}
    emptied = lrm.restore_outcome(
        restored_id=R1, created_by_migration=False, sources={R1}, live_sources={R1},
        assets_by_source={R1: {A}}, candidate_assets={A},
    )
    assert emptied.action == lrm.WITHDRAW
    nothing = lrm.restore_outcome(
        restored_id=R1, created_by_migration=False, sources={R1}, live_sources={R1},
        assets_by_source={R1: {C}}, candidate_assets={A},
    )
    assert nothing.action is None


def test_the_restore_endpoint_releases_candidates_for_risks():
    from app.api.v1 import records

    source = inspect.getsource(records.restore_record)
    assert "_release_migrated_candidate" in source
    assert lrm.RESTORED_NOTE == "Source risk restored"
    archive = (FRONTEND / "components" / "ArchivedRecords.tsx").read_text(encoding="utf-8")
    assert "risk candidates queue" in archive


# ======================================================= 4. pending suggestions ===
def test_a_cached_count_is_served_only_while_it_matches():
    row = SimpleNamespace(fingerprint="f1", computed_at=NOW - timedelta(minutes=5))
    assert cs.cache_fresh(row, "f1", NOW)
    assert not cs.cache_fresh(row, "f2", NOW)
    assert not cs.cache_fresh(SimpleNamespace(fingerprint="f1", computed_at=NOW - timedelta(days=2)), "f1", NOW)
    assert not cs.cache_fresh(None, "f1", NOW)
    stamp = datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc)
    assert cs.fingerprint_text((3, stamp, None, 7)) == f"3|{stamp.isoformat()}||7"


class _CacheDB:
    def __init__(self, row, fingerprint="3|x"):
        self.row, self.fingerprint, self.statements = row, fingerprint, []

    async def scalar(self, stmt):
        return self.row

    async def execute(self, stmt):
        self.statements.append(str(stmt.compile(dialect=postgresql.dialect())))
        return SimpleNamespace(one=lambda: (3, "x"))


async def test_the_pending_count_is_served_from_the_cache_or_recounted(monkeypatch):
    calls = []

    async def count(db, *, framework_id=None, cap=1000):
        calls.append(framework_id)
        return {"framework_id": framework_id, "unmapped_controls": 40, "scanned": 40, "capped": False,
                "controls_with_strong": 12, "strong_suggestions": 30}

    monkeypatch.setattr(cs, "pending_strong", count)
    fresh = SimpleNamespace(fingerprint="3|x", computed_at=NOW - timedelta(minutes=1),
                            value={"controls_with_strong": 5, "strong_suggestions": 9})
    served = await cs.pending_strong_cached(_CacheDB(fresh), uuid.uuid4(), now=NOW)
    assert served["cached"] and served["controls_with_strong"] == 5 and calls == []

    stale = SimpleNamespace(fingerprint="2|x", computed_at=NOW, value={})
    db = _CacheDB(stale)
    counted = await cs.pending_strong_cached(db, uuid.uuid4(), now=NOW)
    assert not counted["cached"] and counted["controls_with_strong"] == 12 and calls == [None]
    upsert = db.statements[-1]
    assert "INSERT INTO tenant_computed_cache" in upsert and "ON CONFLICT ON CONSTRAINT uq_tenant_computed_cache_key" in upsert


def test_the_fingerprint_reads_every_input_in_one_statement():
    captured = []

    class DB:
        async def execute(self, stmt):
            captured.append(_sql(stmt))
            return SimpleNamespace(one=lambda: (1,))

    import asyncio

    asyncio.run(cs.suggestion_fingerprint(DB()))
    (text,) = captured
    for table in ("controls", "requirements", "frameworks", "requirement_controls", "requirement_crosswalks"):
        assert f"FROM {table}" in text, table
    assert "hashtext" in text


def test_the_dashboard_hints_at_waiting_suggestions():
    page = (FRONTEND / "app" / "(app)" / "dashboard" / "page.tsx").read_text(encoding="utf-8")
    assert "getPendingSuggestions" in page and "/controls#review-suggestions" in page
    controls = (FRONTEND / "app" / "(app)" / "controls" / "page.tsx").read_text(encoding="utf-8")
    assert '"#review-suggestions"' in controls


# ===================================================== 5. one eligibility rule ===
ME, HOLDER, MAKER, ADMIN = (uuid.uuid4() for _ in range(4))


def _directory(holder_perms=frozenset({"workflow:approve"})):
    return Directory(
        users={
            ME: DirectoryUser(ME, "me@bank.pk", "Me", True, ("Admin",)),
            HOLDER: DirectoryUser(HOLDER, "holder@bank.pk", "Holder", True, ("Risk Approver",)),
            MAKER: DirectoryUser(MAKER, "maker@bank.pk", "Maker", True, ("Risk Approver",)),
        },
        role_permissions={"Admin": frozenset({"workflow:approve"}), "Risk Approver": holder_perms},
    )


def _approval(**kw):
    base = dict(id=uuid.uuid4(), reference="APR-1", title="Approve policy", approver="Risk Approver",
                requested_by=MAKER, requested_by_email="maker@bank.pk", status=ApprovalStatus.pending,
                required_approvals=1, entity_label="", entity_type="policy", due_date=None, description="",
                link="", decided_by_email="", decision_comment="", created_at=NOW)
    base.update(kw)
    ap = ApprovalRequest(**base)
    ap.actions = []
    return ap


def test_a_stage_gate_counts_holders_who_can_approve_other_than_the_maker():
    ap = _approval()
    gate = ns.stage_gate(ap, "risk approver", _directory())
    assert (gate.role, gate.eligible, gate.holders, gate.maker_holds) == ("Risk Approver", 1, 2, True)
    lacking = ns.stage_gate(ap, "Risk Approver", _directory(frozenset()))
    assert lacking.eligible == 0 and lacking.holders == 2
    assert ns.stage_gate(ap, "", _directory()) is None


def test_recipients_follow_the_stage_gate():
    ap = _approval()
    gate = ns.stage_gate(ap, "Risk Approver", _directory())
    assert ns.approval_recipients(ap, _directory(), gate) == [(ns.ROLE, "Risk Approver")]
    d = _directory(frozenset())
    lacking = ns.stage_gate(ap, "Risk Approver", d)
    assert ns.approval_recipients(ap, d, lacking) == [(ns.ROLE, "Risk Approver"), (ns.ROLE, "Admin")]
    # A named role whose only approver is the maker widens to the approving roles.
    solo = Directory(
        users={MAKER: DirectoryUser(MAKER, "maker@bank.pk", "Maker", True, ("CRO",))},
        role_permissions={"CRO": frozenset({"workflow:approve"}), "Admin": frozenset({"workflow:approve"})},
    )
    assert ns.approval_recipients(_approval(approver="CRO"), solo) == [(ns.ROLE, "CRO"), (ns.ROLE, "Admin")]


def test_the_decision_rule_refuses_a_stage_outsider_while_a_holder_can_decide(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval()
    gate = ns.stage_gate(ap, "Risk Approver", _directory())
    refusal = ns.decision_refusal(ap, user_id=ME, email="me@bank.pk", permissions={"workflow:approve"},
                                  role_names=["Admin"], stage=gate)
    assert refusal.code == ns.REFUSAL_STAGE and "Risk Approver" in refusal.message
    assert ns.approval_refusal(ap, user_id=HOLDER, email="holder@bank.pk", permissions={"workflow:approve"},
                               role_names=["Risk Approver"], stage=gate) is None
    fallback = ns.stage_gate(ap, "Risk Approver", _directory(frozenset()))
    assert ns.approval_refusal(ap, user_id=ME, email="me@bank.pk", permissions={"workflow:approve"},
                               role_names=["Admin"], stage=fallback) is None


def test_email_links_go_only_to_those_the_stage_allows(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval(approver="")
    d = _directory()
    assert at.decision_makers(ap, d) == [ME, HOLDER]  # no stage: every approver but the maker
    gate = ns.stage_gate(ap, "Risk Approver", d)
    assert at.decision_makers(ap, d, stage=gate) == [HOLDER]
    user = SimpleNamespace(id=ME, email="me@bank.pk", is_active=True, permission_codes=["workflow:approve"],
                           role_names=["Admin"])
    row = SimpleNamespace(used_at=None, expires_at=NOW + timedelta(hours=1))
    state, message = at.token_state(row, user, ap, NOW, stage=gate)
    assert state == at.NOT_ELIGIBLE and "Risk Approver" in message
    assert at.token_state(row, user, ap, NOW)[0] == at.READY


class _MyWorkDB:
    def __init__(self, approvals):
        self.approvals = approvals

    async def scalars(self, stmt):
        return SimpleNamespace(all=lambda: list(self.approvals))


async def test_my_work_offers_only_decisions_the_stage_allows(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval(approver="")

    async def gates(db, approvals, directory):
        return {ap.id: ns.stage_gate(ap, "Risk Approver", directory)}

    monkeypatch.setattr(ns, "load_stage_gates", gates)

    def ctx(uid, email, roles):
        return mw.Ctx(user_id=uid, email=email, permissions={"workflow:approve"}, role_names=set(roles),
                      role_ids=set(), today=NOW.date(), horizon=NOW.date(), directory=_directory())

    assert await mw.approvals_waiting(_MyWorkDB([ap]), ctx(ME, "me@bank.pk", ["Admin"])) == []
    items = await mw.approvals_waiting(_MyWorkDB([ap]), ctx(HOLDER, "holder@bank.pk", ["Risk Approver"]))
    assert [i.id for i in items] == [ap.id]


async def test_the_approvals_list_uses_the_same_rule(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval()
    ap.actions = [ApprovalAction(id=uuid.uuid4(), actor_id=HOLDER, actor_email="holder@bank.pk", action="approve",
                                 comment="", created_at=NOW)]

    async def context(db, rows):
        d = _directory(frozenset())
        return d, {ap.id: ns.stage_gate(ap, "Risk Approver", d)}

    monkeypatch.setattr(approvals_api, "_decision_context", context)
    me = SimpleNamespace(id=ME, email="me@bank.pk", permission_codes=["workflow:approve"], role_names=["Admin"])
    (read,) = await approvals_api._annotate(object(), [ap], me)
    # The holders lack workflow:approve: the stage falls back, the page says why.
    assert read.can_decide is True and read.approver_role_holders == 0
    assert "workflow:approve" in read.approver_role_gap
    holder = SimpleNamespace(id=HOLDER, email="holder@bank.pk", permission_codes=["workflow:approve"],
                             role_names=["Risk Approver"])
    (again,) = await approvals_api._annotate(object(), [ap], holder)
    assert again.can_decide is False and "already recorded" in again.decide_blocked_reason


def test_the_approvals_page_opens_the_linked_request():
    page = (FRONTEND / "app" / "(app)" / "approvals" / "page.tsx").read_text(encoding="utf-8")
    assert 'useRecordParam("id")' in page and "/approvals/${encodeURIComponent(openId)}" in page


# ======================================================== 6. KRI feed rate limit ===
def test_the_token_bucket():
    ok, tokens, wait = rate_limit.take(2.0, 0.0, 0.0, capacity=2, per_second=1.0)
    assert ok and tokens == 1.0 and wait == 0.0
    ok, tokens, wait = rate_limit.take(0.0, 0.0, 0.5, capacity=2, per_second=1.0)
    assert not ok and tokens == 0.5 and wait == pytest.approx(0.5)
    ok, tokens, _ = rate_limit.take(0.0, 0.0, 100.0, capacity=2, per_second=1.0)  # refills to capacity only
    assert ok and tokens == 1.0


def test_memory_buckets_are_per_key():
    limiter = rate_limit.RateLimiter("t", capacity=2, per_second=0.1)
    assert limiter.hit_memory("a", 0).allowed and limiter.hit_memory("a", 0).allowed
    denied = limiter.hit_memory("a", 0)
    assert not denied.allowed and denied.retry_after == pytest.approx(10.0)
    assert limiter.hit_memory("b", 0).allowed
    assert limiter.hit_memory("a", 10.5).allowed


async def test_the_kri_feed_answers_429_before_touching_the_database(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    limiter = rate_limit.RateLimiter("kri-feed-test", capacity=1, per_second=0.001)
    monkeypatch.setattr(kri_api, "KRI_FEED_LIMIT", limiter)
    opened = []

    class _Session:
        async def __aenter__(self):
            opened.append(True)
            raise HTTPException(status_code=401, detail="stop")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(kri_api, "tenant_session", lambda tenant_id: _Session())
    tenant, kid = uuid.uuid4(), uuid.uuid4()
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=kri_api.new_feed_token(tenant))
    with pytest.raises(HTTPException) as first:
        await kri_api.feed_measurement(kid, kri_schemas.MeasurementFeed(value=1), creds)
    assert first.value.status_code == 401 and opened == [True]
    with pytest.raises(HTTPException) as second:
        await kri_api.feed_measurement(kid, kri_schemas.MeasurementFeed(value=1), creds)
    assert second.value.status_code == 429 and int(second.value.headers["Retry-After"]) >= 1
    assert opened == [True]  # the limited call opened no session
