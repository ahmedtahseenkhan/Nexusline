"""A framework's posture in three honest numbers (F-19).

Mapping controls to clauses never makes a clause *compliant* — only an assessment does
(``Requirement.status``). So a framework whose 93 clauses were just mapped still reads
"0% compliant", and it looked as if the mapping had done nothing. Rather than fake
compliance, the posture shows what the mapping did achieve beside what it did not:

* **assessed compliant** — applicable clauses somebody assessed as compliant;
* **mapped** — applicable clauses with at least one control mapped;
* **tested** — applicable clauses backed by a control whose test says it works
  (effective or partially effective: ``control_assurance`` "assured" coverage, the
  same rule the gap analysis and the dashboard use).
* **via crosswalk** (phase 4C) — applicable clauses not tested directly (no control, or
  an untested one) that an equivalent or containing clause of another framework covers
  with a tested control (``services.crosswalks``). Shown beside the others, never added
  to mapped or tested: it is a reason to adopt the mapping, not a mapping.

"Applicable" is the gap analysis's and the dashboard's rule: every live clause whose
status is not *not applicable*. Pure and duck-typed, so it is unit-tested without a
database.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from app.services import control_assurance

NOT_APPLICABLE = "not_applicable"
COMPLIANT = "compliant"


def _plain(value) -> str:
    return str(getattr(value, "value", value) or "")


def pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


@dataclass
class Posture:
    total: int = 0
    applicable: int = 0
    compliant: int = 0
    #: Applicable clauses with at least one live control mapped.
    mapped: int = 0
    #: Applicable clauses a working (tested) control backs.
    assured: int = 0
    #: Mapped, but no mapped control tested yet / every tested control failing.
    unassessed: int = 0
    failing: int = 0
    #: Not tested directly, but covered by a tested control through a crosswalk.
    via_crosswalk: int = 0
    compliant_pct: float = 0.0
    mapped_pct: float = 0.0
    assured_pct: float = 0.0
    via_crosswalk_pct: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def line(self) -> str:
        return posture_line(self)


def _coverage(requirement) -> str:
    cov = getattr(requirement, "coverage", None)
    if isinstance(cov, str):
        return cov
    controls = [c for c in (getattr(requirement, "controls", None) or []) if not getattr(c, "deleted", False)]
    return control_assurance.coverage_state(getattr(c, "effectiveness", None) for c in controls)


def posture(requirements: Iterable, via_crosswalk=None) -> Posture:
    """The posture of a set of clauses (archived ones are left out). ``via_crosswalk``
    holds the ids of clauses covered via crosswalk (``crosswalks.via_crosswalk_for``);
    a clause assured or failing on its own controls never counts there."""
    via = via_crosswalk or ()
    out = Posture()
    for r in requirements:
        if getattr(r, "deleted", False):
            continue
        out.total += 1
        if _plain(getattr(r, "status", None)) == NOT_APPLICABLE:
            continue
        out.applicable += 1
        if _plain(r.status) == COMPLIANT:
            out.compliant += 1
        cov = _coverage(r)
        if cov != control_assurance.UNMAPPED:
            out.mapped += 1
        if cov == control_assurance.ASSURED:
            out.assured += 1
        elif cov == control_assurance.UNASSESSED:
            out.unassessed += 1
        elif cov == control_assurance.FAILING:
            out.failing += 1
        if cov in (control_assurance.UNMAPPED, control_assurance.UNASSESSED) and getattr(r, "id", None) in via:
            out.via_crosswalk += 1
    out.compliant_pct = pct(out.compliant, out.applicable)
    out.mapped_pct = pct(out.mapped, out.applicable)
    out.assured_pct = pct(out.assured, out.applicable)
    out.via_crosswalk_pct = pct(out.via_crosswalk, out.applicable)
    return out


def combine(postures: Iterable[Posture]) -> Posture:
    """Several frameworks as one (the organisation-wide figure)."""
    out = Posture()
    for p in postures:
        for name in ("total", "applicable", "compliant", "mapped", "assured", "unassessed", "failing", "via_crosswalk"):
            setattr(out, name, getattr(out, name) + getattr(p, name))
    out.compliant_pct = pct(out.compliant, out.applicable)
    out.mapped_pct = pct(out.mapped, out.applicable)
    out.assured_pct = pct(out.assured, out.applicable)
    out.via_crosswalk_pct = pct(out.via_crosswalk, out.applicable)
    return out


def _fmt(value: float) -> str:
    return f"{value:g}%"


def posture_line(p: Posture) -> str:
    """"0% assessed compliant · 62% mapped · 8% tested" — the three numbers in the order
    a reader should weigh them. A framework with nothing applicable says so."""
    if not p.applicable:
        return "No applicable clauses"
    line = f"{_fmt(p.compliant_pct)} assessed compliant · {_fmt(p.mapped_pct)} mapped · {_fmt(p.assured_pct)} tested"
    if p.via_crosswalk:
        line += f" · {_fmt(p.via_crosswalk_pct)} covered via crosswalk"
    return line
