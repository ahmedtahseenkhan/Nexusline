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
counts by severity band. Everything here is pure; ``api/v1/risks.py`` loads the facts.
"""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.services.risk_scoring import AppetiteBook, SeverityScale, effective_score

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

    @property
    def inherent_score(self) -> int | None:
        if self.inherent_likelihood and self.inherent_impact:
            return self.inherent_likelihood * self.inherent_impact
        return None

    @property
    def residual_score(self) -> int | None:
        if self.residual_likelihood and self.residual_impact:
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


@dataclass
class TreeNode(Summary):
    children_count: int = 0
    descendants_count: int = 0
    worst: Summary | None = None
    by_severity: dict[str, int] = field(default_factory=dict)
    breaches: int = 0
    children: list["TreeNode"] = field(default_factory=list)


def summarise(risk: RiskFacts, depth: int, scale: SeverityScale, book: AppetiteBook | None) -> Summary:
    exposure = effective_score(risk.inherent_score, risk.residual_score)
    severity = scale.for_risk(
        risk.inherent_likelihood, risk.inherent_impact, risk.residual_likelihood, risk.residual_impact
    )
    return Summary(
        id=risk.id, reference=risk.reference, title=risk.title, level=risk.level,
        parent_id=risk.parent_id, depth=depth, status=risk.status,
        inherent_score=risk.inherent_score, residual_score=risk.residual_score,
        exposure=exposure, severity=severity.value if severity else None,
        appetite_status=book.status(exposure, risk.category_id) if book is not None else None,
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
    scored = [s for s in summaries if getattr(s, score) is not None]
    if not scored:
        return None
    return sorted(scored, key=lambda s: (-getattr(s, score), s.depth, s.reference))[0]


def _severity_counts(summaries: Iterable[Summary]) -> dict[str, int]:
    counts = Counter(s.severity for s in summaries if s.severity)
    return {band: counts.get(band, 0) for band in ("low", "medium", "high", "critical")}


def rollup(
    root: RiskFacts,
    index: Mapping[uuid.UUID, list[RiskFacts]],
    scale: SeverityScale,
    book: AppetiteBook | None = None,
) -> Rollup:
    """Children and every descendant of ``root`` with their scores, the worst residual
    (assessed risks only) and the worst exposure among them, and counts by band."""
    below = [summarise(r, d, scale, book) for r, d in descendants(root.id, index)]
    return Rollup(
        risk=summarise(root, 0, scale, book),
        children=[s for s in below if s.depth == 1],
        descendants=below,
        worst_residual=_worst(below, "residual_score"),
        worst_exposure=_worst(below, "exposure"),
        by_severity=_severity_counts(below),
        breaches=sum(1 for s in below if s.appetite_status == "breach"),
        total=len(below),
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
            breaches=sum(1 for s in below if s.appetite_status == "breach"),
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
