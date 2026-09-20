"""Shipped crosswalk content: which clauses of two library frameworks relate, and how.

"Map once, comply many" needs content, not only tooling: a bank that installs ISO/IEC
27001:2022, PCI DSS v4.0.1 and the SBP Cyber Security framework should find the
relationships between their clauses already recorded, reviewable and rejectable, rather
than build them one pair at a time.

One module per framework pair (``iso_csf``, ``csf_800_53`` ...). Each declares the two
library template keys, where the mapping comes from, and its rows in a compact text
table, one row per line::

    <from ref>  <to ref>  <relationship>  <confidence>  [short rationale]

References are the template's own spelling (``A.8.5``, ``PR.AA-03``, ``8.4.2``) and every
one must exist in ``framework_library.TEMPLATES`` — pinned by
``tests/test_phase4_crosswalks.py``. Rationale is a short note in our own words; no
standard's text is copied.

Relationships (set-theoretic, as NIST OLIR defines them), always read **from → to**:

* ``equivalent`` — the two ask for the same outcome; meeting either meets the other.
* ``subset`` — the *from* clause is wholly contained in the *to* clause: meeting *to*
  meets *from*, not the reverse.
* ``superset`` — the *from* clause wholly contains the *to* clause: meeting *from* meets
  *to*, not the reverse.
* ``intersects`` — they overlap, and each asks for something the other does not.
* ``related`` — same subject, no claim that either satisfies any part of the other.

Only ``equivalent`` and a direction-correct containment let an assured control on one
clause show the other as "covered via crosswalk" (``services.crosswalks``). When a
mapping is uncertain it is ``intersects`` or ``related``, never ``equivalent``.

``CONTENT_VERSION`` moves whenever any row changes; a tenant's materialised rows record
the version they came from, and a boot sync brings them up to date.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache

#: Bump when any row is added, removed or retyped.
CONTENT_VERSION = "2026.09.1"

EQUIVALENT = "equivalent"
SUBSET = "subset"
SUPERSET = "superset"
INTERSECTS = "intersects"
RELATED = "related"
RELATIONSHIPS: tuple[str, ...] = (EQUIVALENT, SUBSET, SUPERSET, INTERSECTS, RELATED)

#: The relationship read the other way round.
INVERSE: dict[str, str] = {
    EQUIVALENT: EQUIVALENT,
    SUBSET: SUPERSET,
    SUPERSET: SUBSET,
    INTERSECTS: INTERSECTS,
    RELATED: RELATED,
}

RELATIONSHIP_LABELS: dict[str, str] = {
    EQUIVALENT: "Equivalent",
    SUBSET: "Contained in",
    SUPERSET: "Contains",
    INTERSECTS: "Overlaps",
    RELATED: "Related",
}

#: Modules, one per framework pair, in presentation order.
PAIR_MODULES: tuple[str, ...] = (
    "iso_csf",
    "iso_800_53",
    "csf_800_53",
    "iso_cis",
    "iso_pci",
    "iso_soc2",
    "iso_etgrm",
    "iso_sbp_cyber",
    "etgrm_sbp_cyber",
    "pci_cis",
)


@dataclass(frozen=True)
class ShippedRow:
    """One shipped crosswalk, read from → to."""

    from_template: str
    from_ref: str
    to_template: str
    to_ref: str
    relationship: str
    confidence: float
    rationale: str
    source: str
    version: str = CONTENT_VERSION

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.from_template, self.from_ref, self.to_template, self.to_ref)

    def oriented(self, from_template: str, from_ref: str) -> "ShippedRow":
        """This row read from ``(from_template, from_ref)``; the row itself when it
        already is, the inverse (subset ↔ superset) when it is the *to* side."""
        if (self.from_template, self.from_ref) == (from_template, from_ref):
            return self
        return ShippedRow(
            self.to_template, self.to_ref, self.from_template, self.from_ref,
            INVERSE[self.relationship], self.confidence, self.rationale, self.source, self.version,
        )


@dataclass(frozen=True)
class PairContent:
    module: str
    from_template: str
    to_template: str
    source: str
    rows: tuple[ShippedRow, ...]


class ContentError(ValueError):
    """A malformed row in a content module."""


def parse_rows(text: str, *, from_template: str, to_template: str, source: str, module: str = "") -> tuple[ShippedRow, ...]:
    """Parse a module's text table. Blank lines and ``#`` comments are skipped."""
    out: list[ShippedRow] = []
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 4)
        if len(parts) < 4:
            raise ContentError(f"{module}:{n}: expected '<from> <to> <relationship> <confidence> [rationale]': {line!r}")
        a, b, rel, conf = parts[:4]
        if rel not in RELATIONSHIPS:
            raise ContentError(f"{module}:{n}: unknown relationship {rel!r}")
        try:
            confidence = float(conf)
        except ValueError as exc:
            raise ContentError(f"{module}:{n}: confidence {conf!r} is not a number") from exc
        if not 0 < confidence <= 1:
            raise ContentError(f"{module}:{n}: confidence {confidence} is outside (0, 1]")
        rationale = parts[4].strip() if len(parts) > 4 else ""
        out.append(ShippedRow(from_template, a, to_template, b, rel, confidence, rationale, source))
    return tuple(out)


@lru_cache(maxsize=1)
def pairs() -> tuple[PairContent, ...]:
    out = []
    for name in PAIR_MODULES:
        mod = importlib.import_module(f"{__name__}.{name}")
        out.append(PairContent(
            module=name, from_template=mod.FROM, to_template=mod.TO, source=mod.SOURCE,
            rows=parse_rows(mod.ROWS, from_template=mod.FROM, to_template=mod.TO, source=mod.SOURCE, module=name),
        ))
    return tuple(out)


@lru_cache(maxsize=1)
def all_rows() -> tuple[ShippedRow, ...]:
    return tuple(r for p in pairs() for r in p.rows)


def pair_key(a_template: str, a_ref: str, b_template: str, b_ref: str) -> frozenset:
    """Order-free identity of a clause pair."""
    return frozenset(((a_template, a_ref), (b_template, b_ref)))


@lru_cache(maxsize=1)
def by_pair() -> dict[frozenset, ShippedRow]:
    """Clause pair (either order) → the shipped row. A pair is shipped at most once."""
    return {pair_key(*r.key): r for r in all_rows()}


def lookup(a_template: str, a_ref: str, b_template: str, b_ref: str) -> ShippedRow | None:
    """The shipped row for a clause pair, read from ``a``; None when not shipped."""
    row = by_pair().get(pair_key(a_template, a_ref, b_template, b_ref))
    return row.oriented(a_template, a_ref) if row is not None else None


def rows_between(templates) -> list[ShippedRow]:
    """Every shipped row whose two frameworks are both in ``templates``."""
    have = set(templates)
    return [r for r in all_rows() if r.from_template in have and r.to_template in have]


def rows_from(template: str, others=None) -> list[ShippedRow]:
    """Every shipped row touching ``template``, read from it; limited to ``others`` when
    given."""
    out = []
    for r in all_rows():
        if r.from_template == template or r.to_template == template:
            o = r if r.from_template == template else r.oriented(r.to_template, r.to_ref)
            if others is None or o.to_template in others:
                out.append(o)
    return out


def counts() -> list[dict]:
    """Rows per framework pair and per relationship — for the content note and the
    report."""
    out = []
    for p in pairs():
        by_rel = {rel: 0 for rel in RELATIONSHIPS}
        for r in p.rows:
            by_rel[r.relationship] += 1
        out.append({
            "module": p.module, "from_template": p.from_template, "to_template": p.to_template,
            "source": p.source, "rows": len(p.rows), "by_relationship": by_rel,
        })
    return out


__all__ = [
    "CONTENT_VERSION", "EQUIVALENT", "SUBSET", "SUPERSET", "INTERSECTS", "RELATED",
    "RELATIONSHIPS", "INVERSE", "RELATIONSHIP_LABELS", "ShippedRow", "PairContent",
    "ContentError", "parse_rows", "pairs", "all_rows", "pair_key", "by_pair", "lookup",
    "rows_between", "rows_from", "counts",
]
