"""Typed crosswalks: materialising shipped content, rejections, coverage via crosswalk
and common-control reuse on pack install (phase 4, workstream 4C).

A crosswalk row reads **requirement → related requirement** with a relationship from
``crosswalk_content.RELATIONSHIPS``. Three things are built on it here:

1. **Materialisation.** Shipped rows (``services.crosswalk_content``) between the
   frameworks an organisation has installed become ``requirement_crosswalks`` rows with
   origin ``shipped`` — on install and on every boot (``data_repairs``), idempotently. A
   rejected shipped row (``CrosswalkRejection``) is never added back. A shipped row the
   content later retypes is updated; one the content drops is removed unless someone in
   the organisation approved it. A legacy row (written before typing: manual, related,
   no source, never approved) takes the shipped typing for its pair.
2. **Coverage via crosswalk.** A clause whose own controls are not assured (none mapped,
   or mapped but untested) is *covered via crosswalk* when an ``equivalent`` clause, or
   one that wholly contains it (read from the clause: ``subset``), has an assured
   control. It is never counted as a direct mapping; the posture and the Statement of
   Applicability show it separately, and "adopt mapping" turns it into a direct link.
   A failing direct control is never masked by a crosswalk.
3. **Common controls.** When a controls pack is installed, a clause with a shipped
   crosswalk to a clause of an installed framework that already has a control is offered
   that control (``framework_library.plan_pack``).

The rules are pure and unit-tested; the async functions load and write for a tenant.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from app.services import crosswalk_content as content
from app.services.crosswalk_content import (
    EQUIVALENT,
    INTERSECTS,
    INVERSE,
    RELATED,
    RELATIONSHIPS,
    SUBSET,
    SUPERSET,
)

ORIGIN_SHIPPED = "shipped"
ORIGIN_ACCEPTED = "accepted"
ORIGIN_MANUAL = "manual"
ORIGINS: tuple[str, ...] = (ORIGIN_SHIPPED, ORIGIN_ACCEPTED, ORIGIN_MANUAL)

#: Read from the clause that needs coverage: the relationships under which the other
#: clause's working control meets it.
COVERING: tuple[str, ...] = (EQUIVALENT, SUBSET)
#: Pack install: relationships that propose reusing a control. Equivalent reuses by
#: default; the others are offered for a decision. ``related`` proposes nothing.
REUSE_DEFAULT: tuple[str, ...] = (EQUIVALENT,)
REUSE_ASK: tuple[str, ...] = (SUBSET, SUPERSET, INTERSECTS)
_REL_RANK = {EQUIVALENT: 0, SUBSET: 1, SUPERSET: 2, INTERSECTS: 3, RELATED: 4}

#: Short, plain labels read from the first clause ("A.8.5 contains PCI 8.4.2").
RELATIONSHIP_PHRASES: dict[str, str] = {
    EQUIVALENT: "is equivalent to",
    SUBSET: "is contained in",
    SUPERSET: "contains",
    INTERSECTS: "overlaps",
    RELATED: "is related to",
}


def inverse(relationship: str) -> str:
    return INVERSE.get(relationship, RELATED)


def covers(relationship_from_target: str) -> bool:
    """Whether the other clause's assured control covers the target clause, given the
    relationship read from the target."""
    return relationship_from_target in COVERING


# ---------------------------------------------------------------------------
# Links (pure)
# ---------------------------------------------------------------------------
@dataclass
class Link:
    """One ``requirement_crosswalks`` row."""

    requirement_id: object
    related_requirement_id: object
    relationship: str = RELATED
    rationale: str = ""
    source: str = ""
    content_version: str = ""
    confidence: float | None = None
    origin: str = ORIGIN_MANUAL
    approved_by: str = ""
    approved_by_id: object = None
    approved_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def pair(self) -> frozenset:
        return frozenset((self.requirement_id, self.related_requirement_id))

    def other(self, rid):
        return self.related_requirement_id if rid == self.requirement_id else self.requirement_id

    def relationship_from(self, rid) -> str:
        """The relationship read from ``rid``'s side."""
        return self.relationship if rid == self.requirement_id else inverse(self.relationship)

    @property
    def is_legacy(self) -> bool:
        """Written before crosswalks were typed and never touched since."""
        return (
            self.origin == ORIGIN_MANUAL and self.relationship == RELATED and not self.source
            and not self.rationale and self.approved_at is None
        )

    @classmethod
    def from_row(cls, row) -> "Link":
        m = getattr(row, "_mapping", row)
        get = m.get if hasattr(m, "get") else (lambda k, d=None: getattr(m, k, d))
        return cls(
            requirement_id=get("requirement_id"), related_requirement_id=get("related_requirement_id"),
            relationship=get("relationship") or RELATED, rationale=get("rationale") or "",
            source=get("source") or "", content_version=get("content_version") or "",
            confidence=get("confidence"), origin=get("origin") or ORIGIN_MANUAL,
            approved_by=get("approved_by") or "", approved_by_id=get("approved_by_id"),
            approved_at=get("approved_at"), created_at=get("created_at"),
        )


def shipped_values(row: content.ShippedRow, requirement_id, related_requirement_id, from_id) -> dict:
    """Column values for a shipped row stored as (requirement_id → related), where
    ``from_id`` is the id of the content row's *from* clause."""
    rel = row.relationship if requirement_id == from_id else inverse(row.relationship)
    return {
        "requirement_id": requirement_id,
        "related_requirement_id": related_requirement_id,
        "relationship": rel,
        "rationale": row.rationale,
        "source": row.source,
        "content_version": row.version,
        "confidence": row.confidence,
        "origin": ORIGIN_SHIPPED,
    }


_TYPED_FIELDS = ("relationship", "rationale", "source", "content_version", "confidence", "origin")


@dataclass
class SyncPlan:
    inserts: list[dict] = field(default_factory=list)
    #: (requirement_id, related_requirement_id, values to set)
    updates: list[tuple[object, object, dict]] = field(default_factory=list)
    #: (requirement_id, related_requirement_id) of shipped rows the content no longer has
    deletes: list[tuple[object, object]] = field(default_factory=list)
    skipped_rejected: int = 0


def plan_sync(
    installed: dict[tuple[str, str], object],
    existing: Iterable[Link],
    rejected: set[tuple[str, str, str, str]],
    rows: Iterable[content.ShippedRow] | None = None,
    clause_of: dict[object, tuple[str, str]] | None = None,
) -> SyncPlan:
    """What materialising the shipped content needs to write. Pure.

    ``installed`` maps (template key, reference) to a live requirement id; ``existing``
    are the crosswalk rows among those requirements; ``rejected`` the content keys
    (from template, from ref, to template, to ref) this organisation rejected;
    ``clause_of`` maps requirement id back to (template key, reference) so shipped rows
    the content no longer has can be found."""
    rows = list(content.all_rows() if rows is None else rows)
    by_pair = {link.pair: link for link in existing}
    plan = SyncPlan()
    shipped_pairs: set[frozenset] = set()
    for row in rows:
        a = installed.get((row.from_template, row.from_ref))
        b = installed.get((row.to_template, row.to_ref))
        if a is None or b is None or a == b:
            continue
        pair = frozenset((a, b))
        if row.key in rejected:
            plan.skipped_rejected += 1
            continue
        shipped_pairs.add(pair)
        link = by_pair.get(pair)
        if link is None:
            plan.inserts.append(shipped_values(row, a, b, a))
            by_pair[pair] = Link(a, b, row.relationship, origin=ORIGIN_SHIPPED)
            continue
        if link.origin != ORIGIN_SHIPPED and not link.is_legacy:
            continue  # somebody in the organisation typed this pair: theirs wins
        want = shipped_values(row, link.requirement_id, link.related_requirement_id, a)
        changes = {k: want[k] for k in _TYPED_FIELDS if getattr(link, k) != want[k]}
        if changes:
            if "relationship" in changes and link.approved_at is not None:
                # A reviewed row whose type changed needs reviewing again.
                changes.update(approved_by="", approved_by_id=None, approved_at=None)
            plan.updates.append((link.requirement_id, link.related_requirement_id, changes))
    if clause_of is not None:
        live_keys = {content.pair_key(*r.key) for r in rows}
        for link in by_pair.values():
            if link.origin != ORIGIN_SHIPPED or link.pair in shipped_pairs or link.approved_at is not None:
                continue
            ca, cb = clause_of.get(link.requirement_id), clause_of.get(link.related_requirement_id)
            if ca is None or cb is None:
                continue
            if content.pair_key(*ca, *cb) not in live_keys:
                plan.deletes.append((link.requirement_id, link.related_requirement_id))
    return plan


# ---------------------------------------------------------------------------
# Coverage via crosswalk (pure)
# ---------------------------------------------------------------------------
@dataclass
class ViaControl:
    id: object
    reference: str
    name: str
    effectiveness: str

    def label(self) -> str:
        ref = f"{self.reference} " if self.reference else ""
        return f"{ref}{self.name}".strip()


@dataclass
class ViaCrosswalk:
    """Why a clause counts as covered via crosswalk."""

    requirement_id: object
    #: The clause whose control covers it.
    via_requirement_id: object
    via_reference: str
    via_title: str
    via_framework: str
    #: Read from the covered clause: equivalent | subset.
    relationship: str
    source: str = ""
    controls: list[ViaControl] = field(default_factory=list)

    @property
    def label(self) -> str:
        """"mapped via ISO/IEC 27001:2022 A.8.5"."""
        where = f"{self.via_framework} " if self.via_framework else ""
        return f"mapped via {where}{self.via_reference or self.via_title}".strip()

    def as_dict(self) -> dict:
        return {
            "via_requirement_id": self.via_requirement_id,
            "via_reference": self.via_reference,
            "via_title": self.via_title,
            "via_framework": self.via_framework,
            "relationship": self.relationship,
            "source": self.source,
            "label": self.label,
            "controls": [vars(c) for c in self.controls],
        }


#: Own coverage states a crosswalk may add to. ``failing`` is excluded on purpose.
VIA_ELIGIBLE = ("unmapped", "unassessed")


def resolve_via(
    targets: dict[object, tuple[object, str]],
    links: Iterable[Link],
    assured: dict[object, list[ViaControl]],
    clauses: dict[object, tuple[object, str, str, str]],
) -> dict[object, ViaCrosswalk]:
    """Coverage via crosswalk for each target. Pure.

    ``targets``: requirement id → (framework id, own coverage state).
    ``assured``: requirement id → its assured controls.
    ``clauses``: requirement id → (framework id, reference, title, framework name) for the
    live clauses on the other side."""
    best: dict[object, tuple[tuple, ViaCrosswalk]] = {}
    for link in links:
        for rid in (link.requirement_id, link.related_requirement_id):
            target = targets.get(rid)
            if target is None or target[1] not in VIA_ELIGIBLE:
                continue
            rel = link.relationship_from(rid)
            if not covers(rel):
                continue
            other = link.other(rid)
            info = clauses.get(other)
            controls = assured.get(other) or []
            if info is None or not controls or info[0] == target[0]:
                continue
            fw_id, ref, title, fw_name = info
            via = ViaCrosswalk(rid, other, ref, title, fw_name, rel, link.source,
                               sorted(controls, key=lambda c: (c.reference, c.name)))
            rank = (_REL_RANK[rel], -(link.confidence or 0.0), fw_name.lower(), ref)
            if rid not in best or rank < best[rid][0]:
                best[rid] = (rank, via)
    return {rid: via for rid, (_, via) in best.items()}


# ---------------------------------------------------------------------------
# Common controls on pack install (pure)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReuseCandidate:
    """An existing control a new clause could reuse through a shipped crosswalk."""

    requirement_ref: str
    control_id: object
    control_reference: str
    control_name: str
    via_template: str
    via_reference: str
    via_framework: str
    #: Read from the new clause.
    relationship: str
    confidence: float
    rationale: str = ""
    source: str = ""

    @property
    def default_reuse(self) -> bool:
        return self.relationship in REUSE_DEFAULT

    def sort_key(self):
        return (_REL_RANK[self.relationship], -self.confidence, self.via_framework.lower(),
                self.via_reference, (self.control_reference or "").lower(), str(self.control_id))


def reuse_candidates(
    key: str,
    mapped: Iterable[tuple[str, str, object, str, str, str]],
    rejected: set[tuple[str, str, str, str]] = frozenset(),
    rows: Iterable[content.ShippedRow] | None = None,
) -> dict[str, list[ReuseCandidate]]:
    """New clause reference → candidates, best first. Pure.

    ``mapped`` holds (template key, clause reference, control id, control reference,
    control name, framework name) for every live control mapped to a clause of an
    installed framework other than ``key``."""
    by_clause: dict[tuple[str, str], list[tuple[object, str, str, str]]] = {}
    for tkey, ref, cid, cref, cname, fw_name in mapped:
        if tkey == key:
            continue
        by_clause.setdefault((tkey, ref), []).append((cid, cref, cname, fw_name))
    source_rows = content.rows_from(key) if rows is None else [
        r if r.from_template == key else r.oriented(r.to_template, r.to_ref)
        for r in rows if key in (r.from_template, r.to_template)
    ]
    out: dict[str, list[ReuseCandidate]] = {}
    for r in source_rows:
        if r.relationship not in REUSE_DEFAULT + REUSE_ASK:
            continue
        stored = r.key if r.key in rejected else (r.to_template, r.to_ref, r.from_template, r.from_ref)
        if stored in rejected:
            continue
        for cid, cref, cname, fw_name in by_clause.get((r.to_template, r.to_ref), []):
            out.setdefault(r.from_ref, []).append(ReuseCandidate(
                r.from_ref, cid, cref, cname, r.to_template, r.to_ref, fw_name,
                r.relationship, r.confidence, r.rationale, r.source,
            ))
    for ref in out:
        seen: set = set()
        uniq = []
        for c in sorted(out[ref], key=ReuseCandidate.sort_key):
            if c.control_id not in seen:
                seen.add(c.control_id)
                uniq.append(c)
        out[ref] = uniq
    return out


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
async def installed_clauses(db) -> tuple[dict[tuple[str, str], object], dict[object, tuple[str, str]], dict[str, object]]:
    """(template key, reference) → requirement id for every live clause of an installed
    library framework that has shipped content, the reverse map, and key → framework id."""
    from sqlalchemy import select

    from app.models.compliance import Requirement
    from app.services.framework_library import template_installs

    wanted = {p.from_template for p in content.pairs()} | {p.to_template for p in content.pairs()}
    installs = {k: v.framework_id for k, v in (await template_installs(db)).items() if k in wanted}
    if len(installs) < 2:
        return {}, {}, installs
    key_of = {fid: k for k, fid in installs.items()}
    fwd: dict[tuple[str, str], object] = {}
    back: dict[object, tuple[str, str]] = {}
    for rid, fid, ref in (await db.execute(
        select(Requirement.id, Requirement.framework_id, Requirement.reference)
        .where(Requirement.framework_id.in_(list(key_of)), Requirement.deleted.is_(False))
    )).all():
        k = (key_of[fid], (ref or "").strip())
        fwd.setdefault(k, rid)
        back[rid] = k
    return fwd, back, installs


async def load_links(db, requirement_ids: Iterable, *, both: bool = True) -> list[Link]:
    """Crosswalk rows touching ``requirement_ids`` (``both``: both ends inside)."""
    from sqlalchemy import select

    from app.models.compliance import requirement_crosswalks as rc

    ids = list(requirement_ids)
    if not ids:
        return []
    stmt = select(rc)
    if both:
        stmt = stmt.where(rc.c.requirement_id.in_(ids), rc.c.related_requirement_id.in_(ids))
    else:
        stmt = stmt.where(rc.c.requirement_id.in_(ids) | rc.c.related_requirement_id.in_(ids))
    return [Link.from_row(r) for r in (await db.execute(stmt)).all()]


async def rejected_keys(db) -> set[tuple[str, str, str, str]]:
    from sqlalchemy import select

    from app.models.compliance import CrosswalkRejection

    return {
        (r.from_template, r.from_reference, r.to_template, r.to_reference)
        for r in (await db.scalars(select(CrosswalkRejection))).all()
    }


@dataclass
class SyncResult:
    inserted: int = 0
    updated: int = 0
    removed: int = 0
    skipped_rejected: int = 0

    @property
    def changed(self) -> int:
        return self.inserted + self.updated + self.removed


async def sync_shipped(db) -> SyncResult:
    """Materialise the shipped crosswalks between this organisation's installed library
    frameworks. Idempotent; flushes, never commits."""
    from sqlalchemy import and_, delete, insert, update

    from app.models.compliance import requirement_crosswalks as rc

    fwd, back, _ = await installed_clauses(db)
    if not fwd:
        return SyncResult()
    existing = await load_links(db, list(back))
    plan = plan_sync(fwd, existing, await rejected_keys(db), clause_of=back)
    for values in plan.inserts:
        await db.execute(insert(rc).values(**values))
    for a, b, values in plan.updates:
        await db.execute(update(rc).where(and_(rc.c.requirement_id == a, rc.c.related_requirement_id == b)).values(**values))
    for a, b in plan.deletes:
        await db.execute(delete(rc).where(and_(rc.c.requirement_id == a, rc.c.related_requirement_id == b)))
    if plan.inserts or plan.updates or plan.deletes:
        await db.flush()
    return SyncResult(len(plan.inserts), len(plan.updates), len(plan.deletes), plan.skipped_rejected)


def clause_key(requirement) -> tuple[str, str] | None:
    """(template key, reference) of a loaded requirement whose framework is a library
    template, else None."""
    from app.services.framework_library import template_key_for_name

    fw = getattr(requirement, "framework", None)
    key = template_key_for_name(getattr(fw, "name", None)) if fw is not None else None
    return (key, (requirement.reference or "").strip()) if key else None


def shipped_row_for(a, b) -> content.ShippedRow | None:
    """The shipped row for two loaded requirements (as content orients it)."""
    ka, kb = clause_key(a), clause_key(b)
    if ka is None or kb is None:
        return None
    return content.by_pair().get(content.pair_key(*ka, *kb))


async def record_rejection(db, user, row: content.ShippedRow, reason: str = "") -> bool:
    """Store a rejection for a shipped row; False when it was already rejected."""
    from sqlalchemy import select

    from app.models.compliance import CrosswalkRejection

    found = await db.scalar(select(CrosswalkRejection).where(
        CrosswalkRejection.from_template == row.from_template,
        CrosswalkRejection.from_reference == row.from_ref,
        CrosswalkRejection.to_template == row.to_template,
        CrosswalkRejection.to_reference == row.to_ref,
    ))
    if found is not None:
        return False
    db.add(CrosswalkRejection(
        tenant_id=user.tenant_id, from_template=row.from_template, from_reference=row.from_ref,
        to_template=row.to_template, to_reference=row.to_ref, relationship=row.relationship,
        content_version=row.version, reason=(reason or "").strip(),
        rejected_by=getattr(user, "full_name", "") or getattr(user, "email", "") or "",
        rejected_by_id=getattr(user, "id", None),
    ))
    return True


def approver_values(user) -> dict:
    return {
        "approved_by": (getattr(user, "full_name", "") or getattr(user, "email", "") or "")[:200],
        "approved_by_id": getattr(user, "id", None),
        "approved_at": datetime.now(timezone.utc),
    }


async def via_crosswalk_for(db, requirements) -> dict[object, ViaCrosswalk]:
    """Coverage via crosswalk for loaded requirements (ORM rows with ``coverage``)."""
    from sqlalchemy import select

    from app.models.compliance import Framework, Requirement, requirement_controls
    from app.models.control import Control
    from app.services import control_assurance

    targets = {
        r.id: (r.framework_id, getattr(r, "coverage", "unmapped"))
        for r in requirements
        if not getattr(r, "deleted", False)
        and str(getattr(r.status, "value", r.status)) != "not_applicable"
        and getattr(r, "coverage", "unmapped") in VIA_ELIGIBLE
    }
    if not targets:
        return {}
    links = [
        link for link in await load_links(db, list(targets), both=False)
        if any(rid in targets and covers(link.relationship_from(rid))
               for rid in (link.requirement_id, link.related_requirement_id))
    ]
    others = {link.other(rid) for link in links for rid in (link.requirement_id, link.related_requirement_id) if rid in targets}
    if not others:
        return {}
    assured: dict[object, list[ViaControl]] = {}
    for rid, cid, ref, name, eff in (await db.execute(
        select(requirement_controls.c.requirement_id, Control.id, Control.reference, Control.name, Control.effectiveness)
        .join(Control, Control.id == requirement_controls.c.control_id)
        .where(requirement_controls.c.requirement_id.in_(list(others)), Control.deleted.is_(False),
               Control.effectiveness.in_(control_assurance.ASSURED_EFFECTIVENESS))
    )).all():
        assured.setdefault(rid, []).append(ViaControl(cid, ref or "", name or "", str(getattr(eff, "value", eff))))
    if not assured:
        return {}
    clauses = {
        rid: (fid, ref or "", title or "", fw_name or "")
        for rid, fid, ref, title, fw_name in (await db.execute(
            select(Requirement.id, Requirement.framework_id, Requirement.reference, Requirement.title, Framework.name)
            .join(Framework, Framework.id == Requirement.framework_id)
            .where(Requirement.id.in_(list(assured)), Requirement.deleted.is_(False), Framework.deleted.is_(False))
        )).all()
    }
    return resolve_via(targets, links, assured, clauses)


async def reuse_candidates_for(db, key: str) -> dict[str, list[ReuseCandidate]]:
    """Common-control candidates for installing ``key``'s controls pack in this tenant."""
    from sqlalchemy import select

    from app.models.compliance import Framework, Requirement, requirement_controls
    from app.models.control import Control
    from app.services.framework_library import template_key_for_name

    others = {p.to_template for p in content.pairs() if p.from_template == key} | {
        p.from_template for p in content.pairs() if p.to_template == key}
    if not others:
        return {}
    mapped = []
    for cid, cref, cname, fw_name, ref in (await db.execute(
        select(Control.id, Control.reference, Control.name, Framework.name, Requirement.reference)
        .select_from(requirement_controls)
        .join(Control, Control.id == requirement_controls.c.control_id)
        .join(Requirement, Requirement.id == requirement_controls.c.requirement_id)
        .join(Framework, Framework.id == Requirement.framework_id)
        .where(Control.deleted.is_(False), Requirement.deleted.is_(False), Framework.deleted.is_(False))
    )).all():
        tkey = template_key_for_name(fw_name)
        if tkey in others:
            mapped.append((tkey, (ref or "").strip(), cid, cref or "", cname or "", fw_name))
    if not mapped:
        return {}
    return reuse_candidates(key, mapped, await rejected_keys(db))


def content_note() -> dict:
    """The version and per-pair counts shown beside the crosswalk review."""
    return {"version": content.CONTENT_VERSION, "pairs": content.counts(), "relationships": list(RELATIONSHIPS)}


__all__ = [
    "ORIGINS", "ORIGIN_SHIPPED", "ORIGIN_ACCEPTED", "ORIGIN_MANUAL", "COVERING", "Link", "SyncPlan",
    "plan_sync", "ViaControl", "ViaCrosswalk", "resolve_via", "ReuseCandidate", "reuse_candidates",
    "sync_shipped", "via_crosswalk_for", "reuse_candidates_for"
]
