"""The risk candidate queue (product review, phase 3 — F-04).

Generation used to write one register risk per asset × scenario pair; the reviewed
register held 1,700 near-duplicates. Pairs now queue as candidates, grouped by a
de-duplication key, and only an accepted candidate becomes a risk.

No database: the pure rules in ``services.risk_scenarios`` are tested directly and the
queue endpoints are driven with a scripted session (every statement is compiled for
PostgreSQL, so a malformed query fails here) and stubbed loaders.

Pinned here:

1. **The key** — scenario + process + business unit; asset class only when an asset has
   neither. The asset's process is its first live process by name; its unit is its
   owning unit, else the process's.
2. **The plan** — pairs already in the register are skipped (accepted candidate with a
   live risk, a pre-queue generated risk, or a matching title); pairs join a pending
   candidate; duplicates within a run fold into one candidate;
   ``created + merged + skipped == pairs``.
3. **Titles and scores** — one asset keeps its (possibly edited) title; several assets
   never keep a title that names only one of them; a candidate is scored at its worst.
4. **Decisions** — accept promotes through ``create_risk`` (draft, generated, level 3),
   reject needs a reason, merge folds assets and references into the survivor; one
   audit row per candidate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - registers every mapper before the services import them
from app.api.v1 import risk_scenarios as api
from app.api.v1 import risks as risks_api
from app.models.risk_scenario import RiskProposal as ProposalRow
from app.schemas.risk_scenario import (
    AcceptRequest,
    CommitItem,
    CommitRequest,
    MergeRequest,
    ProposalRead,
    RejectRequest,
)
from app.services import risk_scenarios as rs
from app.services.risk_scenarios import (
    CATALOGUE,
    AssetFacts,
    KeyOwner,
    PairIn,
    Placement,
    ProposalFacts,
    applies_to_asset,
    candidate_title,
    dedupe_key,
    group_subject,
    group_title,
    key_owners,
    match_generated_title,
    merge_candidates,
    merge_refs,
    place_asset,
    plan_commit,
    scope_label,
    split_refs,
    title_for,
    title_patterns,
    worst_scores,
)
from app.models.enums import AssetClass, Criticality

PAY, RETAIL, OPS = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _id() -> uuid.UUID:
    return uuid.uuid4()


# ======================================================================== the key ===
def test_the_key_is_scenario_process_and_unit():
    assert dedupe_key("RS-011", PAY, RETAIL, "it_asset") == f"RS-011|{PAY}|{RETAIL}"
    assert dedupe_key("RS-011", None, RETAIL, "it_asset") == f"RS-011|-|{RETAIL}"
    assert dedupe_key("RS-011", PAY, None, "it_asset") == f"RS-011|{PAY}|-"


def test_an_asset_with_neither_process_nor_unit_is_keyed_by_its_class():
    assert dedupe_key("RS-011", None, None, "it_asset") == "RS-011|-|-|it_asset"
    assert dedupe_key("RS-011", None, None, "information_asset") != dedupe_key("RS-011", None, None, "it_asset")


def test_the_scenario_reference_is_normalised():
    assert dedupe_key(" rs-011 ", PAY, RETAIL) == dedupe_key("RS-011", PAY, RETAIL)


def test_the_owning_unit_wins_over_the_process_unit():
    where = place_asset(
        asset_class="it_asset", owner_unit=(RETAIL, "Retail Banking"),
        processes=[(PAY, "Payments", OPS)], unit_names={RETAIL: "Retail Banking", OPS: "Operations"},
    )
    assert (where.process_id, where.business_unit_id, where.business_unit_name) == (PAY, RETAIL, "Retail Banking")


def test_without_an_owning_unit_the_process_unit_is_used():
    where = place_asset(
        asset_class="it_asset", owner_unit=None, processes=[(PAY, "Payments", OPS)],
        unit_names={OPS: "Operations"},
    )
    assert (where.business_unit_id, where.business_unit_name) == (OPS, "Operations")


def test_with_several_processes_the_first_by_name_is_used():
    a, b = _id(), _id()
    where = place_asset(
        asset_class="it_asset", owner_unit=None,
        processes=[(a, "trade finance", None), (b, "Payments", None)], unit_names={},
    )
    assert (where.process_id, where.process_name) == (b, "Payments")
    again = place_asset(
        asset_class="it_asset", owner_unit=None,
        processes=[(b, "Payments", None), (a, "trade finance", None)], unit_names={},
    )
    assert again == where  # stable whatever order the database returns


def test_an_unplaced_asset_keeps_only_its_class():
    where = place_asset(asset_class="information_asset", owner_unit=None, processes=[], unit_names={})
    assert where == Placement(asset_class="information_asset")
    assert scope_label(where) == "Information assets"


# ================================================================ titles & scores ===
def test_scope_and_group_titles_read_naturally():
    both = Placement("it_asset", PAY, "Payments", RETAIL, "Retail Banking")
    assert scope_label(both) == "Payments · Retail Banking"
    assert group_subject(both) == "Payments assets in Retail Banking"
    assert group_title("Ransomware encrypts {asset}", group_subject(both)) == (
        "Ransomware encrypts Payments assets in Retail Banking"
    )
    unit_only = Placement("it_asset", None, "", RETAIL, "Retail Banking")
    assert group_title("{asset} runs on unsupported technology", group_subject(unit_only)) == (
        "Retail Banking assets runs on unsupported technology"
    )
    assert group_title("Ransomware", "IT assets") == "Ransomware — IT assets"
    assert len(group_title("Ransomware encrypts {asset}", "x" * 400)) == 255


def test_one_asset_keeps_the_title_offered():
    assert candidate_title(["My edited title"], group="G", asset_count=1, single_asset_titles={"auto"}) == "My edited title"


def test_several_assets_keep_a_shared_title_unless_it_names_one_asset():
    single = {"ransomware encrypts server-1", "ransomware encrypts server-2"}
    shared = ["Ransomware across Payments", "Ransomware across Payments"]
    assert candidate_title(shared, group="G", asset_count=2, single_asset_titles=single) == "Ransomware across Payments"
    per_asset = ["Ransomware encrypts Server-1", "Ransomware encrypts Server-2"]
    assert candidate_title(per_asset, group="G", asset_count=2, single_asset_titles=single) == "G"
    one_named = ["Ransomware encrypts Server-1"]
    assert candidate_title(one_named, group="G", asset_count=2, single_asset_titles=single) == "G"
    # The preview's "(hostname)" suffix still names one asset.
    assert candidate_title(["Ransomware encrypts Server-1 (host-01)"], group="G", asset_count=2,
                           single_asset_titles=single) == "G"


def test_a_candidate_is_scored_at_its_worst_asset():
    assert worst_scores([(3, 4), (5, 2), (2, 5)]) == (3, 4)  # 12 beats 10 and 10
    assert worst_scores([(2, 5), (5, 2)]) == (2, 5)  # tie on score: the higher impact
    assert worst_scores([(None, 3), (0, 0)]) == (None, None)


def test_control_references_merge_without_repeats():
    assert split_refs(" A.8.5, ,CIS 6.3 ") == ["A.8.5", "CIS 6.3"]
    assert merge_refs(["A.8.5", "CIS 6.3"], ["a.8.5", "PCI 8.4"], []) == ["A.8.5", "CIS 6.3", "PCI 8.4"]


# ======================================================== pre-queue generated risks ===
def _facts(name="Core Banking") -> AssetFacts:
    m = Criticality.medium
    return AssetFacts(name, AssetClass.it_asset.value, m, m, m, m, m)


def test_titles_from_the_old_generator_are_recognised():
    patterns = title_patterns([("RS-001", "Unauthorised access to {asset}"), ("RS-099", "Ransomware")])
    assert match_generated_title("Unauthorised access to Core Banking", patterns) == [("RS-001", ["Core Banking"])]
    assert match_generated_title("unauthorised ACCESS to core banking", patterns) == [("RS-001", ["core banking"])]
    assert match_generated_title("Ransomware — ATM Switch", patterns) == [("RS-099", ["ATM Switch"])]
    assert match_generated_title("Unauthorised physical access to X", patterns) == []


def test_a_disambiguated_title_offers_both_readings():
    patterns = title_patterns([("RS-011", "Ransomware encrypts {asset}")])
    assert match_generated_title("Ransomware encrypts Payments DB (pay-db-01)", patterns) == [
        ("RS-011", ["Payments DB (pay-db-01)", "Payments DB"])
    ]


def test_every_catalogue_title_round_trips():
    patterns = title_patterns([(s.reference, s.title) for s in CATALOGUE])
    asset = _facts("Card Management System")
    for spec in CATALOGUE:
        if not applies_to_asset(spec, asset):
            continue
        hits = dict(match_generated_title(title_for(spec, asset), patterns))
        assert "Card Management System" in hits.get(spec.reference, []), spec.reference


# ================================================================== key ownership ===
def _facts_row(key, status, **kw) -> ProposalFacts:
    return ProposalFacts(id=kw.pop("id", _id()), dedupe_key=key, status=status, title=kw.pop("title", key), **kw)


def test_an_accepted_candidate_with_a_live_risk_owns_its_key():
    risk = _id()
    accepted = _facts_row("K", "accepted", promoted_risk_id=risk)
    pending = _facts_row("K", "pending")
    owners = key_owners([pending, accepted], {p.id: p for p in (pending, accepted)}, {risk: "R-0042"})
    assert (owners["K"].status, owners["K"].risk_reference) == ("accepted", "R-0042")


def test_an_accepted_candidate_whose_risk_was_archived_owns_nothing():
    accepted = _facts_row("K", "accepted", promoted_risk_id=_id())
    assert key_owners([accepted], {accepted.id: accepted}, {}) == {}


def test_the_oldest_pending_candidate_owns_its_key():
    first, second = _facts_row("K", "pending"), _facts_row("K", "pending")
    owners = key_owners([first, second], {first.id: first, second.id: second}, {})
    assert owners["K"].proposal_id == first.id


def test_a_merged_candidates_key_follows_its_survivor():
    survivor = _facts_row("KA", "pending", title="Ransomware across Payments")
    folded = _facts_row("KB", "merged", merged_into_id=survivor.id)
    owners = key_owners([folded], {survivor.id: survivor, folded.id: folded}, {})
    assert (owners["KB"].status, owners["KB"].proposal_id) == ("pending", survivor.id)


def test_a_merge_loop_in_old_data_stops():
    a_id, b_id = _id(), _id()
    a = _facts_row("KA", "merged", id=a_id, merged_into_id=b_id)
    b = _facts_row("KB", "merged", id=b_id, merged_into_id=a_id)
    assert rs.survivor_of(a, {a_id: a, b_id: b}).id == b_id
    assert key_owners([a, b], {a_id: a, b_id: b}, {}) == {}


def test_the_latest_rejection_is_reported():
    now = datetime.now(timezone.utc)
    old = _facts_row("K", "rejected", decision_note="old", decided_at=now - timedelta(days=9))
    new = _facts_row("K", "rejected", decision_note="Covered by R-0012", decided_at=now)
    owners = key_owners([new, old], {old.id: old, new.id: new}, {})
    assert (owners["K"].status, owners["K"].note) == ("rejected", "Covered by R-0012")


# ======================================================================== the plan ===
def _pair(i, key, *, asset=None, title=None, score=(3, 3), auto=None, refs=()):
    return PairIn(
        index=i, asset_id=asset or _id(), key=key, title=title or f"Pair {i}", likelihood=score[0],
        impact=score[1], scenario_reference=key.split("|")[0], asset_name=f"Asset {i}",
        auto_title=auto or f"Pair {i}", group_title=f"Group {key.split('|')[0]}", refs=tuple(refs),
    )


def test_duplicates_within_a_run_fold_into_one_candidate():
    pairs = [
        _pair(0, "RS-011|p|u", score=(2, 3), refs=["A.8.13"]),
        _pair(1, "RS-011|p|u", score=(4, 4), refs=["a.8.13", "CIS 11.2"]),
        _pair(2, "RS-001|p|u"),
    ]
    plan = plan_commit(pairs, owners={})
    assert (plan.created, plan.merged, plan.merged_into_existing, len(plan.skipped)) == (2, 1, 0, 0)
    ransomware = plan.new[0]
    assert ransomware.scores == (4, 4)
    assert ransomware.refs == ["A.8.13", "CIS 11.2"]
    assert ransomware.asset_ids == [pairs[0].asset_id, pairs[1].asset_id]
    assert ransomware.title == "Group RS-011"  # two per-asset titles -> the group title


def test_the_previews_group_title_is_kept():
    pairs = [_pair(0, "K|p|u", title="Ransomware across Payments"), _pair(1, "K|p|u", title="Ransomware across Payments")]
    assert plan_commit(pairs, owners={}).new[0].title == "Ransomware across Payments"


def test_a_pair_joins_a_pending_candidate():
    pid = _id()
    pairs = [_pair(0, "K|p|u"), _pair(1, "K|p|u")]
    plan = plan_commit(pairs, owners={"K|p|u": KeyOwner("pending", pid, "Queued")})
    assert plan.created == 0 and plan.merges == {pid: pairs}
    assert (plan.merged, plan.merged_into_existing) == (2, 2)


def test_pairs_already_in_the_register_are_skipped():
    accepted = KeyOwner("accepted", _id(), "x", _id(), "R-0042")
    pairs = [
        _pair(0, "A|p|u"),  # accepted candidate with a live risk
        _pair(1, "B|p|u"),  # covered by a pre-queue generated risk
        _pair(2, "C|p|u", title="Unauthorised access to Core Banking"),  # a live risk has the title
        _pair(3, "D|p|u", auto="Ransomware encrypts ATM"),  # ... or the auto title
        _pair(4, "E|p|u"),
    ]
    plan = plan_commit(
        pairs,
        owners={"A|p|u": accepted},
        legacy_keys={"B|p|u": "R-0007"},
        register_titles={"unauthorised access to core banking": "R-0001", "ransomware encrypts atm": "R-0002"},
    )
    assert [(p.index, ref) for p, ref in plan.skipped] == [(0, "R-0042"), (1, "R-0007"), (2, "R-0001"), (3, "R-0002")]
    assert [c.key for c in plan.new] == ["E|p|u"]


def test_a_rejected_key_can_still_be_sent():
    plan = plan_commit([_pair(0, "K|p|u")], owners={"K|p|u": KeyOwner("rejected", _id(), note="n/a")})
    assert plan.created == 1


def test_every_pair_is_accounted_for():
    pid = _id()
    owners = {"Q|p|u": KeyOwner("pending", pid), "S|p|u": KeyOwner("accepted", _id(), risk_id=_id(), risk_reference="R-1")}
    keys = ["N|p|u", "N|p|u", "Q|p|u", "S|p|u", "M|p|u", "N|p|u"]
    plan = plan_commit([_pair(i, k) for i, k in enumerate(keys)], owners=owners)
    assert plan.created + plan.merged + len(plan.skipped) == len(keys)
    assert (plan.created, plan.merged, len(plan.skipped)) == (2, 3, 1)


def test_merging_candidates_unions_assets_and_references():
    a, b, c = _id(), _id(), _id()
    outcome = merge_candidates((2, 3), "A.8.5", [a], [((4, 4), "a.8.5, CIS 6.3", [b, a]), ((1, 5), "", [c])])
    assert outcome.asset_ids == [a, b, c]
    assert outcome.control_references == "A.8.5, CIS 6.3"
    assert (outcome.likelihood, outcome.impact) == (4, 4)


# ======================================================================== schemas ===
def test_a_commit_item_must_name_its_scenario():
    base = dict(asset_id=_id(), title="x", inherent_likelihood=3, inherent_impact=3)
    with pytest.raises(ValidationError):
        CommitItem(**base)
    assert CommitItem(**base, scenario_reference=" RS-001 ").scenario_reference == "RS-001"
    assert CommitItem(**base, scenario_id=_id()).scenario_id is not None


def test_rejecting_needs_a_reason():
    with pytest.raises(ValidationError):
        RejectRequest(ids=[_id()], note="   ")
    with pytest.raises(ValidationError):
        RejectRequest(ids=[_id()])
    with pytest.raises(ValidationError):
        RejectRequest(ids=[], note="duplicate")
    assert RejectRequest(ids=[_id()], note=" Covered by R-0012 ").note == "Covered by R-0012"


def test_accepting_needs_at_least_one_candidate():
    with pytest.raises(ValidationError):
        AcceptRequest(ids=[])


def test_the_read_model_splits_stored_references():
    now = datetime.now(timezone.utc)
    read = ProposalRead.model_validate(SimpleNamespace(
        id=_id(), title="t", status="pending", control_references="A.8.5, CIS 6.3", created_at=now, updated_at=now,
    ))
    assert read.control_references == ["A.8.5", "CIS 6.3"]


# ============================================================ scripted session ===
class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _Nested:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        self.db.savepoints += 1
        return self

    async def __aexit__(self, *exc):
        return False


class ScriptedDB:
    """Compiles each statement for PostgreSQL and answers it from ``answer(sql)``."""

    def __init__(self, answer=None):
        self.answer = answer or (lambda sql: [])
        self.sql: list[str] = []
        self.added: list = []
        self.flushes = 0
        self.savepoints = 0

    def _run(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        self.sql.append(sql)
        return self.answer(sql)

    async def execute(self, stmt):
        return _Rows(self._run(stmt))

    async def scalars(self, stmt):
        return _Rows(self._run(stmt))

    async def scalar(self, stmt):
        rows = self._run(stmt)
        return rows[0] if rows else None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def begin_nested(self):
        return _Nested(self)


def _user():
    return SimpleNamespace(id=_id(), tenant_id=_id(), email="cro@bank.pk", permission_codes=["risk:read", "risk:write"])


def _row(status="pending", **kw):
    base = dict(
        id=_id(), title="Ransomware encrypts Payments assets", status=status, scenario_reference="RS-011",
        description="d", business_unit_id=RETAIL, process_id=PAY, category_id=None, inherent_likelihood=3,
        inherent_impact=4, control_references="A.8.13", dedupe_key=f"RS-011|{PAY}|{RETAIL}",
        merged_into_id=None, promoted_risk_id=None, decided_by_id=None, decided_at=None, decision_note="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def audit(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(api.audit_log, "record", record)
    return calls


def _lock(monkeypatch, rows):
    async def lock(db, ids):
        return {r.id: r for r in rows if r.id in set(ids)}

    monkeypatch.setattr(api, "_lock_proposals", lock)


# ========================================================================= reject ===
async def test_reject_decides_pending_candidates_and_audits_each(monkeypatch, audit):
    pending, other, done = _row(), _row(title="Data leakage"), _row(status="accepted")
    missing = _id()
    _lock(monkeypatch, [pending, other, done])
    user = _user()
    result = await api.reject_proposals(
        RejectRequest(ids=[pending.id, done.id, other.id, missing, pending.id], note="Covered by R-0012"),
        ScriptedDB(), user,
    )
    assert result.rejected == 2
    assert {(s.id, s.message) for s in result.skipped} == {(done.id, "Already accepted"), (missing, "Candidate not found")}
    for row in (pending, other):
        assert (row.status, row.decision_note, row.decided_by_id) == ("rejected", "Covered by R-0012", user.id)
        assert row.decided_at is not None
    assert done.status == "accepted"
    assert [(a["action"], a["entity_id"]) for a in audit] == [("reject", pending.id), ("reject", other.id)]
    assert all(a["entity_type"] == "risk_proposal" for a in audit)


# ========================================================================== merge ===
async def test_merge_needs_another_candidate(monkeypatch, audit):
    keep = _row()
    _lock(monkeypatch, [keep])
    with pytest.raises(HTTPException) as exc:
        await api.merge_proposals(MergeRequest(ids=[keep.id], into_id=keep.id), ScriptedDB(), _user())
    assert exc.value.status_code == 422


async def test_merge_refuses_decided_candidates(monkeypatch, audit):
    keep, gone = _row(), _row(status="rejected", title="Old")
    _lock(monkeypatch, [keep, gone])
    with pytest.raises(HTTPException) as exc:
        await api.merge_proposals(MergeRequest(ids=[gone.id], into_id=keep.id), ScriptedDB(), _user())
    assert exc.value.status_code == 409 and "“Old” is rejected" in exc.value.detail
    decided_keep = _row(status="accepted")
    _lock(monkeypatch, [decided_keep, _row()])
    with pytest.raises(HTTPException) as exc:
        await api.merge_proposals(MergeRequest(ids=[_id()], into_id=decided_keep.id), ScriptedDB(), _user())
    assert exc.value.status_code == 409


async def test_merge_folds_assets_and_references_into_the_survivor(monkeypatch, audit):
    a, b, c = _id(), _id(), _id()
    keep = _row(inherent_likelihood=2, inherent_impact=3, control_references="A.8.13")
    one = _row(title="Ransomware encrypts Server-9", inherent_likelihood=4, inherent_impact=4,
               control_references="CIS 11.2")
    two = _row(title="Backups fail", inherent_likelihood=1, inherent_impact=2, control_references="a.8.13")
    _lock(monkeypatch, [keep, one, two])
    held = {keep.id: [a], one.id: [b], two.id: [a, c]}
    linked: list = []

    async def assets(db, ids, *, live_only):
        return {pid: held[pid] for pid in ids}

    async def link(db, links):
        linked.extend(links)

    async def title(db, row, asset_ids):
        return "Ransomware encrypts Payments assets in Retail Banking"

    async def reads(db, user, rows):
        return [SimpleNamespace(id=r.id) for r in rows]

    monkeypatch.setattr(api, "_asset_ids_by_proposal", assets)
    monkeypatch.setattr(api, "_link_assets", link)
    monkeypatch.setattr(api, "_survivor_title", title)
    monkeypatch.setattr(api, "_proposal_reads", reads)
    monkeypatch.setattr(api, "MergeResult", lambda **kw: SimpleNamespace(**kw))
    user = _user()

    result = await api.merge_proposals(MergeRequest(ids=[one.id, two.id, keep.id], into_id=keep.id), ScriptedDB(), user)

    assert result.merged == 2 and result.survivor.id == keep.id
    assert (keep.inherent_likelihood, keep.inherent_impact) == (4, 4)
    assert keep.control_references == "A.8.13, CIS 11.2"
    assert [(link["proposal_id"], link["asset_id"]) for link in linked] == [(keep.id, b), (keep.id, c)]
    for other in (one, two):
        assert (other.status, other.merged_into_id, other.decided_by_id) == ("merged", keep.id, user.id)
    assert [(x["action"], x["entity_id"]) for x in audit] == [
        ("merge", one.id), ("merge", two.id), ("update", keep.id),
    ]


# ========================================================================= accept ===
def test_the_promoted_risk_is_a_generated_scenario_draft():
    row = _row(category_id=None)
    template = SimpleNamespace(category="Cyber Security", treatment_hint="Immutable backups", description="tpl")
    owner, parent, assets = _id(), _id(), [_id(), _id()]
    payload = api._promotion_payload(
        row, template, asset_ids=assets, control_ids=[_id()], threat_ids=[_id()], vulnerability_ids=[],
        category_id=None, owner_id=owner, parent_id=parent,
    )
    assert payload.status.value == "draft" and payload.source == "generated" and payload.level == 3
    assert (payload.owner_id, payload.parent_id) == (owner, parent)
    assert payload.asset_ids == assets
    assert payload.business_unit_ids == [RETAIL] and payload.process_ids == [PAY]
    assert (payload.inherent_likelihood, payload.inherent_impact) == (3, 4)
    # No picked category: the scenario's category text is matched onto the list later.
    assert (payload.category_id, payload.category) == (None, "Cyber Security")
    assert payload.treatment_description == "Immutable backups"
    picked = _id()
    chosen = api._promotion_payload(
        _row(category_id=_id()), template, asset_ids=assets, control_ids=[], threat_ids=[],
        vulnerability_ids=[], category_id=picked, owner_id=None, parent_id=None,
    )
    assert (chosen.category_id, chosen.category) == (picked, "")


@pytest.fixture
def accept_env(monkeypatch, audit):
    """Stub every loader around ``accept_proposals``; record what ``create_risk`` got."""
    state = SimpleNamespace(created=[], rows=[], assets={}, audit=audit, linked=[])
    template = SimpleNamespace(
        reference="RS-011", title="Ransomware encrypts {asset}", category="Cyber Security",
        threat="Ransomware", vulnerability="No immutable backup", treatment_hint="Backups", description="",
    )

    async def check(db, body):
        return None

    async def lock(db, ids):
        return {r.id: r for r in state.rows if r.id in set(ids)}

    async def templates(db):
        return {}, {"RS-011": template}

    async def assets(db, ids, *, live_only):
        assert live_only
        return {pid: state.assets.get(pid, []) for pid in ids}

    async def names(db, model):
        return {}

    async def ensure(db, user, model, index, name, category):
        return [uuid.uuid5(uuid.NAMESPACE_DNS, name)] if name else []

    async def create(*, body, db, user):
        if body.title == "boom":
            raise HTTPException(status_code=422, detail="inherent likelihood 6 is outside this organisation's 5x5 risk matrix")
        state.created.append(body)
        return SimpleNamespace(id=_id(), reference=f"R-{len(state.created):04d}", title=body.title)

    async def clauses(db, risk_id, control_ids):
        state.linked.append((risk_id, list(control_ids)))
        return 0

    monkeypatch.setattr(api, "_check_accept_choices", check)
    monkeypatch.setattr(api, "_lock_proposals", lock)
    monkeypatch.setattr(api, "_templates", templates)
    monkeypatch.setattr(api, "_asset_ids_by_proposal", assets)
    monkeypatch.setattr(api, "_name_index", names)
    monkeypatch.setattr(api, "_ensure_catalog", ensure)
    monkeypatch.setattr(api, "_link_clauses", clauses)
    monkeypatch.setattr(risks_api, "create_risk", create)
    return state


async def test_accept_promotes_through_create_risk(accept_env):
    control_a, control_b = _id(), _id()
    asset = _id()
    good = _row(control_references="A.8.13, NOT-IN-CATALOGUE")
    accept_env.rows = [good]
    accept_env.assets = {good.id: [asset]}

    def answer(sql):
        if "FROM controls" in sql and "control_assets" not in sql:
            return [(control_a, "A.8.13")]
        if "control_assets" in sql:
            return [(asset, control_b)]
        return []

    db = ScriptedDB(answer)
    user = _user()
    owner = _id()
    result = await api.accept_proposals(AcceptRequest(ids=[good.id], owner_id=owner, note="Agreed in RCSA"), db, user)

    assert result.accepted == 1 and result.errors == [] and result.risks[0].reference == "R-0001"
    body = accept_env.created[0]
    assert body.source == "generated" and body.level == 3 and body.status.value == "draft"
    assert body.owner_id == owner and body.asset_ids == [asset]
    # The asset's own control first, then the scenario's references resolved by catalogue.
    assert body.control_ids == [control_b, control_a]
    assert body.threat_ids and body.vulnerability_ids
    assert (good.status, good.promoted_risk_id, good.decided_by_id, good.decision_note) == (
        "accepted", result.risks[0].id, user.id, "Agreed in RCSA",
    )
    assert accept_env.linked == [(result.risks[0].id, [control_b, control_a])]
    assert db.savepoints == 1
    assert [(a["action"], a["entity_id"]) for a in accept_env.audit] == [("accept", good.id)]


async def test_accept_reports_each_failure_and_goes_on(accept_env):
    good, boom, decided, orphan = _row(), _row(title="boom"), _row(status="merged"), _row(title="No assets left")
    accept_env.rows = [good, boom, decided, orphan]
    accept_env.assets = {good.id: [_id()], boom.id: [_id()]}
    result = await api.accept_proposals(
        AcceptRequest(ids=[boom.id, decided.id, orphan.id, good.id]), ScriptedDB(), _user(),
    )
    assert result.accepted == 1
    messages = {e.id: e.message for e in result.errors}
    assert "outside this organisation's 5x5" in messages[boom.id]
    assert messages[decided.id] == "Already merged"
    assert "deleted since" in messages[orphan.id]
    assert (boom.status, orphan.status, good.status) == ("pending", "pending", "accepted")


async def test_accept_checks_the_picked_parent_once(monkeypatch):
    async def node(db, rid):
        return risks_api.risk_hierarchy.Node(rid, "R-0300", 3)

    async def check_lookup(*a, **k):
        return None

    monkeypatch.setattr(risks_api, "_hierarchy_node", node)
    monkeypatch.setattr(api.master_data, "check_lookup", check_lookup)
    monkeypatch.setattr(api.master_data, "check_user", check_lookup)
    with pytest.raises(HTTPException) as exc:
        await api._check_accept_choices(ScriptedDB(), AcceptRequest(ids=[_id()], parent_id=_id()))
    assert exc.value.status_code == 422 and "bottom of the hierarchy" in exc.value.detail


# ========================================================================= commit ===
@pytest.fixture
def commit_env(monkeypatch, audit):
    """Stub the loaders around ``commit``; the assets and scenarios are scripted."""
    template = SimpleNamespace(
        id=_id(), reference="RS-011", title="Ransomware encrypts {asset}", description="Malware encrypts it",
        category="Cyber Security", asset_classes="", threat="Ransomware", vulnerability="No backup",
        likelihood=3, impact_rule="fixed", impact_property="", fixed_impact=3, treatment_hint="",
        control_references="A.8.13, CIS 11.2",
    )
    m = Criticality.medium
    state = SimpleNamespace(
        template=template, audit=audit, owners={}, legacy={}, register=[], links=[],
        assets={}, placements={}, existing={},
    )

    def asset(name, where):
        aid = _id()
        state.assets[aid] = SimpleNamespace(
            id=aid, name=name, asset_class=AssetClass.it_asset, criticality=m, business_value=m,
            confidentiality=m, integrity=m, availability=m,
        )
        state.placements[aid] = where
        return aid

    state.asset = asset

    async def noop(*a, **k):
        return None

    async def templates(db):
        return {template.id: template}, {"RS-011": template}

    async def size(db, tenant_id):
        return 5

    async def placements(db, ids):
        return {i: state.placements[i] for i in ids if i in state.placements}

    async def owners(db, keys):
        return {k: v for k, v in state.owners.items() if k in keys}

    async def register(db):
        return state.register

    async def legacy(db, register, templates, keys):
        return state.legacy

    async def categories(db, texts):
        return {"cyber security": state.category}

    async def link(db, links):
        state.links.extend(links)

    async def current(db, ids, *, live_only):
        return {pid: state.existing.get(pid, {}).get("assets", []) for pid in ids}

    async def names(db, ids):
        return {aid: state.assets[aid].name for aid in ids if aid in state.assets}

    state.category = _id()
    monkeypatch.setattr(api, "_lock_queue", noop)
    monkeypatch.setattr(api, "_templates", templates)
    monkeypatch.setattr(api, "get_matrix_size", size)
    monkeypatch.setattr(api, "_placements", placements)
    monkeypatch.setattr(api, "_key_owners", owners)
    monkeypatch.setattr(api, "_register_rows", register)
    monkeypatch.setattr(api, "_legacy_keys", legacy)
    monkeypatch.setattr(api, "_category_ids", categories)
    monkeypatch.setattr(api, "_link_assets", link)
    monkeypatch.setattr(api, "_asset_ids_by_proposal", current)
    monkeypatch.setattr(api, "_asset_names", names)
    return state


def _commit_db(state):
    def answer(sql):
        if "FROM assets" in sql:
            return list(state.assets.values())
        if "FROM risk_proposals" in sql:
            return [e["row"] for e in state.existing.values()]
        return []

    return ScriptedDB(answer)


def _item(state, asset_id, title, score=(3, 3), **kw):
    return CommitItem(
        asset_id=asset_id, scenario_reference=state.template.reference, title=title,
        inherent_likelihood=score[0], inherent_impact=score[1], **kw,
    )


async def test_commit_queues_one_candidate_per_key(commit_env):
    where = Placement("it_asset", PAY, "Payments", RETAIL, "Retail Banking")
    s1, s2 = commit_env.asset("Server-1", where), commit_env.asset("Server-2", where)
    lone = commit_env.asset("Laptop-7", Placement("it_asset"))
    db = _commit_db(commit_env)
    user = _user()
    result = await api.commit(CommitRequest(items=[
        _item(commit_env, s1, "Ransomware encrypts Server-1", (3, 3)),
        _item(commit_env, s2, "Ransomware encrypts Server-2", (4, 5)),
        _item(commit_env, lone, "Ransomware encrypts Laptop-7"),
    ]), db, user)

    assert (result.created, result.merged, result.merged_into_existing, result.skipped) == (2, 1, 0, 0)
    rows = [o for o in db.added if isinstance(o, ProposalRow)]
    payments = next(r for r in rows if r.process_id == PAY)
    assert payments.title == "Ransomware encrypts Payments assets in Retail Banking"
    assert (payments.inherent_likelihood, payments.inherent_impact) == (4, 5)
    assert payments.dedupe_key == f"RS-011|{PAY}|{RETAIL}"
    assert (payments.status, payments.run_id, payments.created_by_id) == ("pending", result.run_id, user.id)
    assert payments.category_id == commit_env.category
    assert payments.control_references == "A.8.13, CIS 11.2"
    laptop = next(r for r in rows if r.process_id is None)
    assert laptop.dedupe_key == "RS-011|-|-|it_asset" and laptop.title == "Ransomware encrypts Laptop-7"
    assert {(link["proposal_id"], link["asset_id"]) for link in commit_env.links} == {
        (payments.id, s1), (payments.id, s2), (laptop.id, lone),
    }
    assert set(result.proposals) == {payments.id, laptop.id}
    summary = commit_env.audit[-1]
    assert summary["entity_type"] == "risk_proposal" and summary["changes"]["created"] == 2


async def test_commit_merges_into_the_queue_and_skips_the_register(commit_env):
    where = Placement("it_asset", PAY, "Payments", RETAIL, "Retail Banking")
    s1, s2, s3 = (commit_env.asset(n, where) for n in ("Server-1", "Server-2", "Server-3"))
    elsewhere = commit_env.asset("ATM-1", Placement("it_asset", None, "", OPS, "Operations"))
    key = f"RS-011|{PAY}|{RETAIL}"
    existing = _row(title="Ransomware encrypts Server-1", inherent_likelihood=2, inherent_impact=2,
                    control_references="A.8.13", dedupe_key=key)
    commit_env.existing = {existing.id: {"row": existing, "assets": [s1]}}
    commit_env.owners = {key: KeyOwner("pending", existing.id, existing.title)}
    commit_env.legacy = {f"RS-011|-|{OPS}": "R-0099"}
    db = _commit_db(commit_env)

    result = await api.commit(CommitRequest(items=[
        _item(commit_env, s2, existing.title, (3, 4)),
        _item(commit_env, s3, existing.title, (2, 2)),
        _item(commit_env, elsewhere, "Ransomware encrypts ATM-1"),
    ]), db, _user())

    assert (result.created, result.merged, result.merged_into_existing, result.skipped) == (0, 2, 2, 1)
    assert result.skipped_items[0].risk_reference == "R-0099"
    # Three assets now: the single-asset title gives way to the group's.
    assert existing.title == "Ransomware encrypts Payments assets in Retail Banking"
    assert (existing.inherent_likelihood, existing.inherent_impact) == (3, 4)
    assert {link["asset_id"] for link in commit_env.links} == {s2, s3}
    update = [a for a in commit_env.audit if a["action"] == "update"]
    assert update and update[0]["entity_id"] == existing.id and update[0]["changes"]["assets_added"] == 2


async def test_commit_reports_pairs_it_cannot_queue(commit_env):
    where = Placement("it_asset", PAY, "Payments", RETAIL, "Retail Banking")
    ok = commit_env.asset("Server-1", where)
    db = _commit_db(commit_env)
    result = await api.commit(CommitRequest(items=[
        _item(commit_env, _id(), "Deleted asset"),
        CommitItem(asset_id=ok, scenario_reference="RS-404", title="Gone scenario", inherent_likelihood=1, inherent_impact=1),
        _item(commit_env, ok, "Too big", (6, 6)),
        _item(commit_env, ok, "Ransomware encrypts Server-1"),
    ]), db, _user())
    assert result.created == 1
    assert [e.title for e in result.errors] == ["Deleted asset", "Gone scenario", "Too big"]
    assert "5x5" in result.errors[2].message


# ================================================================ SQL construction ===
def test_the_queue_filters_compile():
    stmt = api._proposal_filters(
        select(ProposalRow), search="ransom", scenario="rs-011", business_unit_id=RETAIL, process_id=PAY,
        run_id=_id(), asset_id=_id(),
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    for fragment in ("risk_proposals.title ILIKE", "upper(risk_proposals.scenario_reference)",
                     "risk_proposals.business_unit_id", "risk_proposals.run_id", "EXISTS (SELECT risk_proposal_assets.proposal_id"):
        assert fragment in sql, fragment


async def test_key_owner_lookup_follows_merge_chains():
    survivor = SimpleNamespace(
        id=_id(), dedupe_key="KA", status="pending", title="Survivor", merged_into_id=None,
        promoted_risk_id=None, decision_note="", decided_at=None,
    )
    folded = SimpleNamespace(
        id=_id(), dedupe_key="KB", status="merged", title="Folded", merged_into_id=survivor.id,
        promoted_risk_id=None, decision_note="", decided_at=None,
    )
    calls = []

    def answer(sql):
        calls.append(sql)
        return [folded] if len(calls) == 1 else [survivor]

    owners = await api._key_owners(ScriptedDB(answer), {"KB"})
    assert owners["KB"].proposal_id == survivor.id and len(calls) == 2


async def test_legacy_register_keys_come_from_titles_and_linked_assets(monkeypatch):
    asset_id, risk_id = _id(), _id()
    template = SimpleNamespace(reference="RS-011", title="Ransomware encrypts {asset}")
    where = Placement("it_asset", PAY, "Payments", RETAIL, "Retail Banking")

    async def placements(db, ids):
        return {asset_id: where} if asset_id in set(ids) else {}

    monkeypatch.setattr(api, "_placements", placements)
    db = ScriptedDB(lambda sql: [(risk_id, asset_id, "Server-1")] if "risk_assets" in sql else [])
    key = dedupe_key("RS-011", PAY, RETAIL)
    out = await api._legacy_keys(
        db, [(risk_id, "R-0005", "Ransomware encrypts Server-1"), (_id(), "R-0006", "Something else")],
        [template], {key},
    )
    assert out == {key: "R-0005"}
