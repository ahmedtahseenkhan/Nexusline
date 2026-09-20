"""The risk hierarchy (product review, phase 3 — F-04): enterprise → category → scenario.

A bank's board reads a handful of **enterprise** risks (level 1), grouped into **category**
risks (level 2); practitioners assess **scenario** risks (level 3) — which is also where
risks generated from the asset register land. ``Risk.parent_id`` links a risk to the one
above it and ``Risk.level`` says where it sits (NULL = not placed yet).

The rules, enforced on every create and update (``place``):

* a parent must be a live risk, not the risk itself, and not below it (no loops);
* a parent sits above its child: its level number is lower (1 above 2 above 3), so a
  level-3 risk has nothing below it and a level-1 risk has no parent;
* a child's level defaults to its parent's level + 1;
* moving a risk's level may not leave a child at or above it.

Roll-ups read the tree the other way: every risk below a node, the worst exposure among
them (residual when assessed, else inherent — the dashboards' "effective" score), and
counts by severity band. Those figures follow the **board register** rule
(``risk_query.on_board_register``, phase 4): only risks that are scored, out of Draft and
not accepted or closed are banded, ranked or counted as breaches — exactly what the
dashboard counts. Drafts, never-scored risks and settled risks still appear in the tree
and the lists, marked ``in_figures=False``, and each roll-up says how many it left out.
A never-scored draft carries no score at all: its stored 1x1 is a placeholder.

:func:`level_cells` aggregates the tree to one level for the dashboard heat map: each
risk at that level is plotted at the cell of the worst in-figure risk in its branch.
Everything here is pure; ``api/v1/risks.py`` loads the facts.
"""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.services.risk_query import on_board_register
from app.services.risk_scoring import AppetiteBook, SeverityScale, effective_score, is_scored

MIN_LEVEL, MAX_LEVEL = 1, 3
LEVEL_NAMES: dict[int, str] = {1: "enterprise", 2: "category", 3: "scenario"}
#: Hard stop for walks over data written before the rules existed.
MAX_DEPTH = 12


class HierarchyError(ValueError):
    """A placement that breaks a rule. The message is the sentence the user reads."""


def level_label(level: int | None) -> str:
    """``"level 2 (category)"``, or ``"not placed"``."""
    if level is None:
        return "not placed"
    return f"level {level} ({LEVEL_NAMES.get(level, '?')})"


@dataclass(frozen=True)
class Node:
    """A risk as the placement rules see it."""

    id: uuid.UUID
    reference: str = ""
    level: int | None = None
    deleted: bool = False


def place(
    *,
    risk_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
    parent: Node | None,
    level: int | None,
    level_given: bool,
    current_level: int | None = None,
    ancestors_of_parent: Sequence[uuid.UUID] = (),
    children: Sequence[Node] = (),
) -> int | None:
    """The level the risk will have once placed; raises :class:`HierarchyError`.

    ``risk_id`` is None on create. ``parent_id`` is the requested parent (None = no
    parent) and ``parent`` what was found for it (None when missing). ``level`` is the
    requested level, ``level_given`` whether the request carried one at all (an update
    that leaves the level alone keeps ``current_level``). ``ancestors_of_parent`` are the
    ids above the requested parent; ``children`` the risk's live children (update only).
    """
    if level is not None and not MIN_LEVEL <= level <= MAX_LEVEL:
        raise HierarchyError(f"Level must be {MIN_LEVEL} (enterprise), 2 (category) or {MAX_LEVEL} (scenario).")
    if parent_id is not None:
        if risk_id is not None and parent_id == risk_id:
            raise HierarchyError("A risk can't be its own parent.")
        if parent is None or parent.deleted:
            raise HierarchyError("The parent risk was not found — it may have been archived. Pick a live risk.")
        if risk_id is not None and risk_id in set(ancestors_of_parent):
            raise HierarchyError(
                f"{parent.reference or 'That risk'} sits below this risk already; making it the parent "
                "would create a loop."
            )
        if parent.level is None:
            raise HierarchyError(
                f"{parent.reference or 'The parent'} isn't placed in the hierarchy yet. Give it a level first."
            )
        if level is not None:
            new_level = level
        elif not level_given and current_level is not None:
            new_level = current_level
        else:
            new_level = parent.level + 1
        if new_level == MIN_LEVEL:
            raise HierarchyError("An enterprise (level 1) risk sits at the top of the hierarchy: it has no parent.")
        if parent.level >= MAX_LEVEL:
            raise HierarchyError(
                f"{parent.reference or 'The parent'} is a scenario (level 3) risk — the bottom of the "
                "hierarchy — so no risk can sit below it."
            )
        if parent.level >= new_level:
            raise HierarchyError(
                f"A parent must sit above its child: {parent.reference or 'the parent'} is "
                f"{level_label(parent.level)}, so it can only hold risks at level "
                f"{parent.level + 1}{'–3' if parent.level + 1 < MAX_LEVEL else ''}."
            )
    else:
        new_level = level if level_given else current_level

    blocking = [c for c in children if not c.deleted and c.level is not None and (new_level is None or c.level <= new_level)]
    if blocking:
        names = ", ".join(c.reference or str(c.id)[:8] for c in blocking[:3])
        more = f" and {len(blocking) - 3} more" if len(blocking) > 3 else ""
        if new_level is None:
            raise HierarchyError(
                f"{names}{more} sit below this risk, so it needs a level. Move them to another parent first."
            )
        raise HierarchyError(
            f"{names}{more} sit below this risk at level {blocking[0].level}; a parent must be above its "
            f"children, so this risk can't move to {level_label(new_level)}. Move or re-level them first."
        )
    return new_level


# ------------------------------------------------------------------- roll-ups ---
@dataclass(frozen=True)
class RiskFacts:
    """The columns a roll-up reads from one live risk."""

    id: uuid.UUID
    parent_id: uuid.UUID | None = None
    level: int | None = None
    reference: str = ""
    title: str = ""
    status: str = ""
    category_id: uuid.UUID | None = None
    inherent_likelihood: int | None = None
    inherent_impact: int | None = None
    residual_likelihood: int | None = None
    residual_impact: int | None = None
    #: Stamped by every score change; with ``status`` it says whether the risk is scored.
    last_assessed_at: datetime | None = None

    @property
    def scored(self) -> bool:
        """``risk_scoring.is_scored``: not a draft nobody has scored."""
        return is_scored(self.status, self.last_assessed_at)

    @property
    def in_figures(self) -> bool:
        """On the board register: scored, out of Draft, not accepted or closed."""
        return on_board_register(self.status, self.last_assessed_at)

    @property
    def inherent_score(self) -> int | None:
        if self.scored and self.inherent_likelihood and self.inherent_impact:
            return self.inherent_likelihood * self.inherent_impact
        return None

    @property
    def residual_score(self) -> int | None:
        if self.scored and self.residual_likelihood and self.residual_impact:
            return self.residual_likelihood * self.residual_impact
        return None


@dataclass
class Summary:
    """One risk as a roll-up or the board tree lists it."""

    id: uuid.UUID
    reference: str
    title: str
    level: int | None
    parent_id: uuid.UUID | None
    depth: int
    status: str
    inherent_score: int | None
    residual_score: int | None
    #: Residual when assessed, else inherent — what the dashboards rank by.
    exposure: int | None
    severity: str | None
    appetite_status: str | None
    #: Counted in severity bands, worst exposure and breaches (the board register).
    in_figures: bool = True
    #: False for a draft nobody has scored: no score, severity or appetite position.
    scored: bool = True


@dataclass
class Rollup:
    risk: Summary
    children: list[Summary]
    descendants: list[Summary]
    worst_residual: Summary | None
    worst_exposure: Summary | None
    by_severity: dict[str, int]
    breaches: int
    total: int
    #: Descendants listed but left out of the figures (drafts, unscored, accepted, closed).
    not_in_figures: int = 0


@dataclass
class TreeNode(Summary):
    children_count: int = 0
    descendants_count: int = 0
    worst: Summary | None = None
    by_severity: dict[str, int] = field(default_factory=dict)
    breaches: int = 0
    not_in_figures: int = 0
    children: list["TreeNode"] = field(default_factory=list)


def summarise(risk: RiskFacts, depth: int, scale: SeverityScale, book: AppetiteBook | None) -> Summary:
    """One risk's line. A never-scored draft has no score or band; a risk off the board
    register keeps its own band but no appetite position (no board figure judges it)."""
    scored = risk.scored
    in_figures = risk.in_figures
    exposure = effective_score(risk.inherent_score, risk.residual_score)
    severity = (
        scale.for_risk(risk.inherent_likelihood, risk.inherent_impact, risk.residual_likelihood, risk.residual_impact)
        if scored else None
    )
    return Summary(
        id=risk.id, reference=risk.reference, title=risk.title, level=risk.level,
        parent_id=risk.parent_id, depth=depth, status=risk.status,
        inherent_score=risk.inherent_score, residual_score=risk.residual_score,
        exposure=exposure, severity=severity.value if severity else None,
        appetite_status=book.status(exposure, risk.category_id) if book is not None and in_figures else None,
        in_figures=in_figures, scored=scored,
    )


def children_index(risks: Iterable[RiskFacts]) -> dict[uuid.UUID, list[RiskFacts]]:
    """Live children of every risk, by reference."""
    index: dict[uuid.UUID, list[RiskFacts]] = {}
    for risk in risks:
        if risk.parent_id is not None:
            index.setdefault(risk.parent_id, []).append(risk)
    for kids in index.values():
        kids.sort(key=lambda r: (r.reference or "", str(r.id)))
    return index


def descendants(root_id: uuid.UUID, index: Mapping[uuid.UUID, list[RiskFacts]]) -> list[tuple[RiskFacts, int]]:
    """Every live risk below ``root_id`` with its depth (children are depth 1),
    breadth-first. Visits each risk once, so a loop in old data cannot hang it."""
    out: list[tuple[RiskFacts, int]] = []
    seen = {root_id}
    frontier = [root_id]
    depth = 0
    while frontier and depth < MAX_DEPTH:
        depth += 1
        nxt: list[uuid.UUID] = []
        for parent in frontier:
            for child in index.get(parent, ()):
                if child.id in seen:
                    continue
                seen.add(child.id)
                out.append((child, depth))
                nxt.append(child.id)
        frontier = nxt
    return out


def _worst(summaries: Sequence[Summary], score: str) -> Summary | None:
    scored = [s for s in summaries if s.in_figures and getattr(s, score) is not None]
    if not scored:
        return None
    return sorted(scored, key=lambda s: (-getattr(s, score), s.depth, s.reference))[0]


def _severity_counts(summaries: Iterable[Summary]) -> dict[str, int]:
    counts = Counter(s.severity for s in summaries if s.severity and s.in_figures)
    return {band: counts.get(band, 0) for band in ("low", "medium", "high", "critical")}


def _breaches(summaries: Iterable[Summary]) -> int:
    return sum(1 for s in summaries if s.in_figures and s.appetite_status == "breach")


def _left_out(summaries: Iterable[Summary]) -> int:
    return sum(1 for s in summaries if not s.in_figures)


def rollup(
    root: RiskFacts,
    index: Mapping[uuid.UUID, list[RiskFacts]],
    scale: SeverityScale,
    book: AppetiteBook | None = None,
) -> Rollup:
    """Children and every descendant of ``root`` with their scores, the worst residual
    (assessed risks only) and the worst exposure among them, and counts by band. The
    worsts, bands and breaches read the board register only; ``not_in_figures`` counts
    the descendants listed but left out."""
    below = [summarise(r, d, scale, book) for r, d in descendants(root.id, index)]
    return Rollup(
        risk=summarise(root, 0, scale, book),
        children=[s for s in below if s.depth == 1],
        descendants=below,
        worst_residual=_worst(below, "residual_score"),
        worst_exposure=_worst(below, "exposure"),
        by_severity=_severity_counts(below),
        breaches=_breaches(below),
        total=len(below),
        not_in_figures=_left_out(below),
    )


def build_tree(
    risks: Sequence[RiskFacts],
    *,
    max_level: int,
    scale: SeverityScale,
    book: AppetiteBook | None = None,
) -> list[TreeNode]:
    """The board view: risks at levels 1..``max_level`` as a forest, each node carrying
    its child count, how many risks sit anywhere below it (at any level — a scenario
    under a category counts even when the tree stops at categories), the worst exposure
    among them and their severity counts.

    A root is a shown risk with no shown parent: at the top, or under a parent that was
    archived or is not placed.
    """
    by_id = {r.id: r for r in risks}
    index = children_index(risks)

    def shown(r: RiskFacts | None) -> bool:
        return r is not None and r.level is not None and r.level <= max_level

    def make(risk: RiskFacts, depth: int, path: frozenset[uuid.UUID]) -> TreeNode:
        below = [summarise(r, d, scale, book) for r, d in descendants(risk.id, index)]
        own = summarise(risk, depth, scale, book)
        node = TreeNode(
            **own.__dict__,
            children_count=len(index.get(risk.id, ())),
            descendants_count=len(below),
            worst=_worst(below, "exposure"),
            by_severity=_severity_counts(below),
            breaches=_breaches(below),
            not_in_figures=_left_out(below),
        )
        if depth < MAX_DEPTH:
            node.children = [
                make(child, depth + 1, path | {child.id})
                for child in index.get(risk.id, ())
                if shown(child) and child.id not in path
            ]
        return node

    roots = [r for r in risks if shown(r) and not shown(by_id.get(r.parent_id) if r.parent_id else None)]
    roots.sort(key=lambda r: (r.level or 0, r.reference or "", str(r.id)))
    return [make(r, 0, frozenset({r.id})) for r in roots]


# ------------------------------------------------------------- heat map by level ---
@dataclass(frozen=True)
class LevelCell:
    """One risk at the chosen level, plotted where the worst risk in its branch sits."""

    risk: RiskFacts
    #: (likelihood, impact) of the worst inherent score in the branch, or None.
    inherent: tuple[int, int] | None
    #: The same for the effective score (residual when assessed, else inherent).
    residual: tuple[int, int] | None


def level_cells(
    risks: Sequence[RiskFacts],
    level: int,
    *,
    counted: Callable[[RiskFacts], bool] = lambda r: r.in_figures,
) -> list[LevelCell]:
    """Aggregate the tree to ``level`` for the heat map: each live risk at that level,
    with the cell of the worst ``counted`` risk among itself and everything below it
    (inherent and effective scores ranked separately). A branch with nothing counted is
    left off the map. ``counted`` defaults to the board register; the register-wide map
    passes ``lambda r: r.scored``."""
    index = children_index(risks)
    out: list[LevelCell] = []
    for node in sorted((r for r in risks if r.level == level), key=lambda r: (r.reference or "", str(r.id))):
        branch = [node, *(r for r, _d in descendants(node.id, index))]
        kept = [r for r in branch if counted(r) and r.inherent_score is not None]
        if not kept:
            continue
        worst_inh = max(kept, key=lambda r: (r.inherent_score or 0, -(r.level or 9)))
        worst_eff = max(
            kept, key=lambda r: (effective_score(r.inherent_score, r.residual_score) or 0, -(r.level or 9))
        )
        eff_cell = (
            (worst_eff.residual_likelihood, worst_eff.residual_impact)
            if worst_eff.residual_score is not None
            else (worst_eff.inherent_likelihood, worst_eff.inherent_impact)
        )
        out.append(LevelCell(
            risk=node,
            inherent=(worst_inh.inherent_likelihood, worst_inh.inherent_impact),
            residual=eff_cell,
        ))
    return out
