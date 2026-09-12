"""Risk hierarchy (product review, phase 3 — F-04): enterprise → category → scenario.

No database: the pure rules in ``services.risk_hierarchy`` are tested directly, the new
register filters are compiled for PostgreSQL and read back, and the risk endpoints'
hierarchy helpers are driven with stubbed loaders.

Pinned here:

1. **Placement** — a parent is live, not the risk itself and not below it; it sits
   above its child (1 above 2 above 3); the child's level defaults to the parent's + 1;
   level 1 has no parent; a level change may not leave a child at or above the risk.
2. **Roll-ups** — every descendant with its depth, the worst residual (assessed only)
   and the worst exposure (residual, else inherent), counts by severity band, breaches.
3. **Board tree** — levels 1..max_level as a forest; counts and the worst exposure cover
   every level below a node, including levels the view does not show.
4. **Filters** — level / max_level / parent / roots, review, appetite per category,
   has-controls and treatment-overdue, as SQL.
"""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - registers every mapper before the services import them
from app.api.v1 import risks as risks_api
from app.schemas.risk import RiskCreate, RiskHierarchyNode, RiskRead, RiskRollup, RiskUpdate
from app.services import risk_hierarchy as rh
from app.services.risk_hierarchy import HierarchyError, Node, RiskFacts, place
from app.services.risk_query import UNPLACED, build_risk_query
from app.services.risk_scoring import AppetiteBook, SeverityScale

TODAY = date(2026, 9, 12)


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ================================================================ placement rules ===
def test_a_risk_with_no_parent_keeps_the_level_it_was_given():
    assert place(risk_id=None, parent_id=None, parent=None, level=None, level_given=False) is None
    assert place(risk_id=None, parent_id=None, parent=None, level=1, level_given=True) == 1
    assert place(risk_id=None, parent_id=None, parent=None, level=3, level_given=True) == 3


@pytest.mark.parametrize("parent_level,expected", [(1, 2), (2, 3)])
def test_the_level_defaults_to_one_below_the_parent(parent_level, expected):
    parent = Node(_id(), "R-0001", parent_level)
    assert place(risk_id=None, parent_id=parent.id, parent=parent, level=None, level_given=False) == expected


def test_a_parent_two_levels_up_is_allowed():
    parent = Node(_id(), "R-0001", 1)
    assert place(risk_id=None, parent_id=parent.id, parent=parent, level=3, level_given=True) == 3


def test_a_scenario_risk_has_nothing_below_it():
    parent = Node(_id(), "R-0009", 3)
    with pytest.raises(HierarchyError, match="scenario .level 3. risk"):
        place(risk_id=None, parent_id=parent.id, parent=parent, level=None, level_given=False)
    with pytest.raises(HierarchyError, match="bottom of the hierarchy"):
        place(risk_id=None, parent_id=parent.id, parent=parent, level=3, level_given=True)


def test_a_parent_must_sit_above_its_child():
    parent = Node(_id(), "R-0002", 2)
    with pytest.raises(HierarchyError, match="A parent must sit above its child: R-0002 is level 2"):
        place(risk_id=None, parent_id=parent.id, parent=parent, level=2, level_given=True)


def test_an_enterprise_risk_has_no_parent():
    parent = Node(_id(), "R-0001", 1)
    with pytest.raises(HierarchyError, match="enterprise .level 1. risk sits at the top"):
        place(risk_id=None, parent_id=parent.id, parent=parent, level=1, level_given=True)


def test_the_parent_must_exist_and_be_live():
    pid = _id()
    with pytest.raises(HierarchyError, match="not found"):
        place(risk_id=None, parent_id=pid, parent=None, level=None, level_given=False)
    with pytest.raises(HierarchyError, match="archived"):
        place(risk_id=None, parent_id=pid, parent=Node(pid, "R-1", 1, deleted=True), level=None, level_given=False)


def test_a_risk_cannot_be_its_own_parent():
    rid = _id()
    with pytest.raises(HierarchyError, match="its own parent"):
        place(risk_id=rid, parent_id=rid, parent=Node(rid, "R-1", 1), level=2, level_given=True)


def test_a_parent_below_the_risk_would_make_a_loop():
    me, child = _id(), _id()
    with pytest.raises(HierarchyError, match="loop"):
        place(
            risk_id=me, parent_id=child, parent=Node(child, "R-0007", 1),
            level=2, level_given=True, ancestors_of_parent=[child, me],
        )


def test_the_parent_must_be_placed_first():
    parent = Node(_id(), "R-0004", None)
    with pytest.raises(HierarchyError, match="isn't placed"):
        place(risk_id=None, parent_id=parent.id, parent=parent, level=None, level_given=False)


def test_moving_under_a_new_parent_keeps_the_current_level():
    parent = Node(_id(), "R-0001", 1)
    assert place(
        risk_id=_id(), parent_id=parent.id, parent=parent, level=None, level_given=False, current_level=3,
    ) == 3


def test_moving_under_a_parent_at_the_same_level_is_refused():
    parent = Node(_id(), "R-0002", 2)
    with pytest.raises(HierarchyError, match="must sit above"):
        place(risk_id=_id(), parent_id=parent.id, parent=parent, level=None, level_given=False, current_level=2)


def test_an_explicit_null_level_under_a_parent_takes_the_default():
    parent = Node(_id(), "R-0001", 1)
    assert place(risk_id=_id(), parent_id=parent.id, parent=parent, level=None, level_given=True, current_level=3) == 2


def test_children_must_stay_below_the_risk():
    kids = [Node(_id(), "R-0100", 3), Node(_id(), "R-0101", 3)]
    assert place(risk_id=_id(), parent_id=None, parent=None, level=2, level_given=True, current_level=2, children=kids) == 2
    with pytest.raises(HierarchyError, match="R-0100, R-0101 sit below this risk at level 3"):
        place(risk_id=_id(), parent_id=None, parent=None, level=3, level_given=True, current_level=2, children=kids)
    with pytest.raises(HierarchyError, match="needs a level"):
        place(risk_id=_id(), parent_id=None, parent=None, level=None, level_given=True, current_level=2, children=kids)


def test_archived_or_unplaced_children_do_not_block():
    kids = [Node(_id(), "R-0100", 2, deleted=True), Node(_id(), "R-0101", None)]
    assert place(risk_id=_id(), parent_id=None, parent=None, level=3, level_given=True, current_level=1, children=kids) == 3


def test_a_level_outside_the_three_is_refused():
    with pytest.raises(HierarchyError, match="Level must be"):
        place(risk_id=None, parent_id=None, parent=None, level=4, level_given=True)


def test_the_schemas_bound_the_level():
    assert RiskCreate(title="x", level=3).level == 3
    with pytest.raises(ValidationError):
        RiskCreate(title="x", level=4)
    with pytest.raises(ValidationError):
        RiskUpdate(level=0)
    assert RiskUpdate(parent_id=None).model_fields_set == {"parent_id"}


# ====================================================================== roll-ups ===
def _risk(ref, parent=None, level=None, inh=(1, 1), res=(None, None), category=None, status="draft"):
    return RiskFacts(
        id=_id(), parent_id=parent.id if parent else None, level=level, reference=ref, title=ref,
        status=status, category_id=category, inherent_likelihood=inh[0], inherent_impact=inh[1],
        residual_likelihood=res[0], residual_impact=res[1],
    )


@pytest.fixture
def tree():
    e1 = _risk("E1", level=1)
    c1 = _risk("C1", e1, 2)
    c2 = _risk("C2", e1, 2)
    s1 = _risk("S1", c1, 3, inh=(4, 5), res=(3, 4))  # residual 12
    s2 = _risk("S2", c1, 3, inh=(5, 5))  # no residual: exposure 25
    s3 = _risk("S3", c2, 3, inh=(3, 3), res=(2, 2))  # residual 4
    return SimpleNamespace(e1=e1, c1=c1, c2=c2, s1=s1, s2=s2, s3=s3, all=[e1, c1, c2, s1, s2, s3])


def test_rollup_lists_children_and_every_descendant(tree):
    result = rh.rollup(tree.e1, rh.children_index(tree.all), SeverityScale())
    assert [s.reference for s in result.children] == ["C1", "C2"]
    assert [(s.reference, s.depth) for s in result.descendants] == [
        ("C1", 1), ("C2", 1), ("S1", 2), ("S2", 2), ("S3", 2),
    ]
    assert result.total == 5
    assert result.risk.reference == "E1" and result.risk.depth == 0


def test_rollup_finds_the_worst_residual_and_the_worst_exposure(tree):
    result = rh.rollup(tree.e1, rh.children_index(tree.all), SeverityScale())
    # Worst residual reads assessed risks only; worst exposure falls back to inherent.
    assert (result.worst_residual.reference, result.worst_residual.residual_score) == ("S1", 12)
    assert (result.worst_exposure.reference, result.worst_exposure.exposure) == ("S2", 25)


def test_rollup_counts_descendants_by_band_and_breach(tree):
    book = AppetiteBook(appetite=6, tolerance=12)
    result = rh.rollup(tree.e1, rh.children_index(tree.all), SeverityScale(), book)
    # 5x5 default bands: 1-4 low, 5-9 medium, 10-14 high, 15-25 critical.
    assert result.by_severity == {"low": 3, "medium": 0, "high": 1, "critical": 1}
    assert result.breaches == 1  # S2 at 25; S1 at 12 is elevated, not a breach
    assert [s.appetite_status for s in result.descendants if s.reference == "S1"] == ["elevated"]


def test_rollup_uses_each_categorys_appetite():
    cat = _id()
    root = _risk("E1", level=1)
    child = _risk("C1", root, 2, inh=(2, 5), category=cat)  # 10
    book = AppetiteBook(appetite=6, tolerance=12, by_category={cat: (4, 8)}, parents={cat: None})
    result = rh.rollup(root, rh.children_index([root, child]), SeverityScale(), book)
    assert result.breaches == 1


def test_rollup_of_a_leaf_is_empty(tree):
    result = rh.rollup(tree.s1, rh.children_index(tree.all), SeverityScale())
    assert result.total == 0 and result.worst_exposure is None and result.worst_residual is None
    assert result.by_severity == {"low": 0, "medium": 0, "high": 0, "critical": 0}


def test_a_loop_in_old_data_cannot_hang_a_walk():
    a, b = _id(), _id()
    ra = RiskFacts(id=a, parent_id=b, level=2, reference="A")
    rb = RiskFacts(id=b, parent_id=a, level=2, reference="B")
    below = rh.descendants(a, rh.children_index([ra, rb]))
    assert [r.reference for r, _d in below] == ["B"]


def test_rollup_schema_reads_the_result(tree):
    result = rh.rollup(tree.e1, rh.children_index(tree.all), SeverityScale())
    read = RiskRollup.model_validate(result, from_attributes=True)
    assert read.worst_exposure.severity.value == "critical"
    assert len(read.descendants) == 5


# ==================================================================== board tree ===
def test_the_board_tree_stops_at_the_level_asked_for(tree):
    roots = rh.build_tree(tree.all, max_level=2, scale=SeverityScale())
    assert [r.reference for r in roots] == ["E1"]
    e1 = roots[0]
    assert [c.reference for c in e1.children] == ["C1", "C2"]
    assert e1.children_count == 2 and e1.descendants_count == 5
    c1 = e1.children[0]
    # Scenarios are not shown at max_level=2, but they are counted and ranked.
    assert c1.children == [] and c1.children_count == 2 and c1.descendants_count == 2
    assert (c1.worst.reference, c1.worst.exposure) == ("S2", 25)
    assert e1.worst.reference == "S2"
    assert c1.by_severity["critical"] == 1


def test_the_full_tree_shows_scenarios(tree):
    roots = rh.build_tree(tree.all, max_level=3, scale=SeverityScale())
    assert [s.reference for s in roots[0].children[0].children] == ["S1", "S2"]


def test_roots_include_risks_whose_parent_is_archived_or_not_shown(tree):
    archived_parent = _id()
    stray = RiskFacts(id=_id(), parent_id=archived_parent, level=2, reference="C9")
    lone = _risk("S9", level=3)
    unplaced = _risk("U1")
    roots = rh.build_tree([*tree.all, stray, lone, unplaced], max_level=2, scale=SeverityScale())
    assert [r.reference for r in roots] == ["E1", "C9"]
    roots = rh.build_tree([*tree.all, stray, lone, unplaced], max_level=3, scale=SeverityScale())
    assert [r.reference for r in roots] == ["E1", "C9", "S9"]


def test_the_tree_schema_reads_nested_nodes(tree):
    roots = rh.build_tree(tree.all, max_level=3, scale=SeverityScale())
    read = RiskHierarchyNode.model_validate(roots[0], from_attributes=True)
    assert read.children[0].children[1].reference == "S2"
    assert read.children[0].worst.reference == "S2"


# ======================================================================= filters ===
def test_level_filters():
    assert "risks.level = 2" in _sql(build_risk_query(level=2))
    assert "risks.level IS NULL" in _sql(build_risk_query(level=UNPLACED))
    text = _sql(build_risk_query(max_level=2))
    assert "risks.level IS NOT NULL" in text and "risks.level <= 2" in text


def test_parent_and_roots_filters():
    pid = _id()
    assert f"risks.parent_id = '{pid}'" in _sql(build_risk_query(parent_id=pid))
    text = _sql(build_risk_query(roots_only=True))
    # No live parent: at the top, or under an archived one.
    assert "risks.parent_id IS NULL OR NOT (EXISTS" in text
    assert "risks_1.id = risks.parent_id AND risks_1.deleted IS false" in text


def test_review_filters_read_the_next_review_date():
    assert "risks.next_review_date < '2026-09-12'" in _sql(build_risk_query(review="overdue", today=TODAY))
    text = _sql(build_risk_query(review="due_30d", today=TODAY))
    assert "risks.next_review_date >= '2026-09-12'" in text
    assert "risks.next_review_date <= '2026-10-12'" in text
    with pytest.raises(ValueError):
        build_risk_query(review="soon")


def test_appetite_filter_uses_the_organisations_thresholds_without_categories():
    book = AppetiteBook(appetite=6, tolerance=12)
    effective = "coalesce(risks.residual_score, risks.inherent_score)"
    assert f"{effective} <= 6" in _sql(build_risk_query(appetite="within", appetite_book=book))
    assert f"{effective} > 6 AND {effective} <= 12" in _sql(build_risk_query(appetite="elevated", appetite_book=book))
    assert f"{effective} > 12" in _sql(build_risk_query(appetite="breach", appetite_book=book))


def test_appetite_filter_follows_each_level_one_category():
    top, sub, other = _id(), _id(), _id()
    book = AppetiteBook(
        appetite=6, tolerance=12, by_category={top: (4, 9)}, parents={top: None, sub: top, other: None},
    )
    text = _sql(build_risk_query(appetite="breach", appetite_book=book))
    # The sub-category takes its level-1 category's numbers; the rest the default.
    branch = text[text.index("CASE WHEN"):text.index("END")]
    assert str(top) in branch and str(sub) in branch and str(other) not in branch
    assert "THEN 9 ELSE 12 END" in text


def test_appetite_filter_matches_the_appetite_book():
    """The SQL predicate and the dashboard's AppetiteBook.status agree for every score."""
    from app.services.risk_query import appetite_thresholds

    top, sub = _id(), _id()
    book = AppetiteBook(appetite=6, tolerance=12, by_category={top: (4, 9)}, parents={top: None, sub: top})
    appetite, tolerance = appetite_thresholds(book)
    for cid in (top, sub, None, _id()):
        a_sql, t_sql = book.thresholds(cid)
        assert book.status(a_sql, cid) == "within_appetite"
        assert book.status(t_sql, cid) == "elevated"
        assert book.status(t_sql + 1, cid) == "breach"
    assert "CASE" in str(appetite) and "CASE" in str(tolerance)


def test_appetite_filter_needs_the_book():
    with pytest.raises(ValueError, match="appetite book"):
        build_risk_query(appetite="breach")
    with pytest.raises(ValueError):
        build_risk_query(appetite="high", appetite_book=AppetiteBook())


def test_has_controls_counts_live_controls_only():
    text = _sql(build_risk_query(has_controls=True))
    assert "EXISTS (SELECT risk_controls.risk_id" in text and "controls.deleted IS false" in text
    assert "NOT (EXISTS (SELECT risk_controls.risk_id" in _sql(build_risk_query(has_controls=False))


def test_treatment_overdue_matches_the_dashboard():
    text = _sql(build_risk_query(treatment_overdue=True, today=TODAY))
    assert "risks.status NOT IN ('accepted', 'closed')" in text
    assert "risk_treatment_actions.status IN ('open', 'in_progress')" in text
    assert "risk_treatment_actions.due_date < '2026-09-12'" in text
    # A risk without actions is judged on its own deadline.
    assert "risks.treatment_deadline < '2026-09-12'" in text
    assert _sql(build_risk_query(treatment_overdue=False, today=TODAY)).count("NOT (") >= 1


def test_existing_filters_are_unchanged_by_default():
    assert _sql(build_risk_query()).endswith("WHERE risks.deleted IS false")


# ============================================================ endpoints (stubbed) ===
class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class RecordingDB:
    """Compiles every statement for PostgreSQL and answers from a script."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.sql: list[str] = []

    def _next(self, stmt):
        self.sql.append(str(stmt.compile(dialect=postgresql.dialect())))
        return self.answers.pop(0) if self.answers else []

    async def execute(self, stmt):
        return _Rows(self._next(stmt))

    async def scalars(self, stmt):
        return _Rows(self._next(stmt))


async def test_ancestor_walk_is_a_recursive_union_that_stops_on_loops():
    db = RecordingDB([[uuid.uuid4()]])
    await risks_api._ancestor_ids(db, uuid.uuid4())
    sql = db.sql[0]
    assert sql.startswith("WITH RECURSIVE risk_ancestors")
    assert " UNION SELECT" in sql and "UNION ALL" not in sql


async def test_fill_hierarchy_reads_live_parents_and_child_counts():
    parent_id, risk_id = uuid.uuid4(), uuid.uuid4()
    db = RecordingDB([
        [SimpleNamespace(id=parent_id, reference="R-0001", title="Operational risk")],
        [(risk_id, 3)],
    ])
    risk = SimpleNamespace(id=risk_id, parent_id=parent_id)
    read = SimpleNamespace(parent=None, children_count=0)
    await risks_api._fill_hierarchy(db, [(risk, read)])
    assert read.parent.reference == "R-0001" and read.children_count == 3
    assert "risks.deleted IS false" in db.sql[0]


def test_the_read_model_carries_the_hierarchy():
    fields = RiskRead.model_fields
    for name in ("level", "parent_id", "parent", "children_count"):
        assert name in fields


@pytest.fixture
def stub_tree(monkeypatch):
    """Stub the hierarchy loaders; ``calls`` records which were used."""
    nodes: dict[uuid.UUID, Node] = {}
    state = {"ancestors": [], "children": [], "calls": []}

    async def node(db, rid):
        state["calls"].append("node")
        return nodes.get(rid)

    async def ancestors(db, rid):
        state["calls"].append("ancestors")
        return state["ancestors"]

    async def children(db, rid):
        state["calls"].append("children")
        return state["children"]

    monkeypatch.setattr(risks_api, "_hierarchy_node", node)
    monkeypatch.setattr(risks_api, "_ancestor_ids", ancestors)
    monkeypatch.setattr(risks_api, "_child_nodes", children)
    state["nodes"] = nodes
    return state


async def test_create_defaults_the_level_from_the_parent(stub_tree):
    parent = Node(uuid.uuid4(), "R-0001", 1)
    stub_tree["nodes"][parent.id] = parent
    level = await risks_api._place(
        None, risk_id=None, parent_id=parent.id, level=None, level_given=False, current_level=None,
    )
    assert level == 2
    assert "ancestors" not in stub_tree["calls"]  # a new risk cannot be above anything


async def test_create_with_a_bad_parent_is_422(stub_tree):
    parent = Node(uuid.uuid4(), "R-0009", 3)
    stub_tree["nodes"][parent.id] = parent
    with pytest.raises(HTTPException) as exc:
        await risks_api._place(None, risk_id=None, parent_id=parent.id, level=None, level_given=False, current_level=None)
    assert exc.value.status_code == 422
    assert "bottom of the hierarchy" in exc.value.detail


async def test_update_that_resends_the_same_parent_checks_nothing(stub_tree):
    risk = SimpleNamespace(id=uuid.uuid4(), parent_id=uuid.uuid4(), level=3)
    data = {"title": "x", "parent_id": risk.parent_id, "level": 3}
    await risks_api._place_on_update(None, risk, data)
    assert data == {"title": "x"}
    assert stub_tree["calls"] == []  # an archived parent does not lock the record


async def test_update_moving_under_a_descendant_is_refused(stub_tree):
    risk = SimpleNamespace(id=uuid.uuid4(), parent_id=None, level=1)
    below = Node(uuid.uuid4(), "R-0050", 2)
    stub_tree["nodes"][below.id] = below
    stub_tree["ancestors"] = [below.id, risk.id]
    with pytest.raises(HTTPException) as exc:
        await risks_api._place_on_update(None, risk, {"parent_id": below.id, "level": 3})
    assert "loop" in exc.value.detail


async def test_update_level_change_checks_children(stub_tree):
    risk = SimpleNamespace(id=uuid.uuid4(), parent_id=None, level=2)
    stub_tree["children"] = [Node(uuid.uuid4(), "R-0300", 3)]
    with pytest.raises(HTTPException) as exc:
        await risks_api._place_on_update(None, risk, {"level": 3})
    assert "R-0300" in exc.value.detail
    data = {"level": 1}
    await risks_api._place_on_update(None, risk, data)
    assert data == {"level": 1, "parent_id": None}


async def test_update_detaching_keeps_the_level(stub_tree):
    risk = SimpleNamespace(id=uuid.uuid4(), parent_id=uuid.uuid4(), level=3)
    data = {"parent_id": None}
    await risks_api._place_on_update(None, risk, data)
    assert data == {"parent_id": None, "level": 3}
