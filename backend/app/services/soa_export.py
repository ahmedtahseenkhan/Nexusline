"""Statement of Applicability — the ISO/IEC 27001 6.1.3 d) document, for any
compliance framework.

One row per clause: whether it applies, why (a justification is mandatory for an
exclusion and recommended for an inclusion), the controls that implement it with their
effectiveness and last test, and the clause's implementation status. The auditor reads
it; the certification body asks for it first.

Applicability is not a new field. A clause is **excluded** when its treatment is
``not_applicable`` or its status is ``not_applicable`` — the two places the product
already recorded "does not apply", and the ones the gap analysis and compliance
percentage already honour — so the SoA can never disagree with the gap count. Excluding
through the SoA sets both; including clears both back to their untouched defaults.

The rules and the row building are pure (unit-tested); the renderers take loaded rows
and return bytes, as ``pdf_report`` and ``report_export`` do.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from xml.sax.saxutils import escape

from fastapi import HTTPException, status

NOT_APPLICABLE = "not_applicable"
NOT_ASSESSED = "not_assessed"

#: SoA filters: every clause, the applicable ones, the exclusions, and applicable
#: clauses with nothing implementing them (the auditor's first question).
VIEWS = ("all", "applicable", "excluded", "no_control")


def _plain(value):
    return getattr(value, "value", value)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def is_applicable(treatment, status_) -> bool:
    """A clause applies unless its treatment or its status says it does not."""
    return _plain(treatment) != NOT_APPLICABLE and _plain(status_) != NOT_APPLICABLE


def applicability_error(applicable: bool, justification: str | None) -> str | None:
    """Why this applicability decision cannot be recorded, or None.

    ISO/IEC 27001 6.1.3 d) requires the SoA to justify every exclusion; an inclusion's
    justification is recommended but optional."""
    if not applicable and not (justification or "").strip():
        return (
            "A justification is required to exclude a clause from the Statement of "
            "Applicability (ISO/IEC 27001 6.1.3 d): say why it does not apply."
        )
    return None


def applicability_changes(applicable: bool, treatment, status_) -> dict:
    """The treatment/status values an applicability decision writes.

    Excluding sets both to ``not_applicable``. Including resets only the ones that said
    ``not_applicable`` — treatment to none, status to not assessed — so a clause's real
    assessment is never touched by toggling it in and out."""
    if not applicable:
        return {"treatment": NOT_APPLICABLE, "status": NOT_APPLICABLE}
    out: dict = {}
    if _plain(treatment) == NOT_APPLICABLE:
        out["treatment"] = None
    if _plain(status_) == NOT_APPLICABLE:
        out["status"] = NOT_ASSESSED
    return out


def justification_after(applicable: bool, was_applicable: bool, current: str, given: str | None) -> str:
    """The justification to store. Given text always wins (trimmed). Re-including a
    clause without new text clears the old exclusion reason — "no card data in scope"
    must not sit against a clause that now applies."""
    if given is not None:
        return given.strip()
    if applicable and not was_applicable:
        return ""
    return current or ""


# The shared natural order (F-16), re-exported for existing callers.
from app.services.reference_sort import natural_key  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------
@dataclass
class SoaControl:
    id: object
    reference: str
    name: str
    effectiveness: str
    status: str
    #: Decision 7 (2026-09-17): the last *reviewed* test (``Control.last_reviewed_*``) —
    #: tests awaiting a reviewer are ``pending_review_count``, never the result shown.
    last_test_date: date | None = None
    last_test_result: str | None = None
    pending_review_count: int = 0

    def label(self) -> str:
        ref = f"{self.reference} " if self.reference else ""
        test = (
            f", last reviewed test {self.last_test_date.isoformat()} ({_words(self.last_test_result)})"
            if self.last_test_date else ", never tested"
        )
        if self.pending_review_count:
            test += f", {_awaiting(self.pending_review_count)}"
        return f"{ref}{self.name} — {_words(self.effectiveness)}{test}"


@dataclass
class SoaRow:
    requirement_id: object
    reference: str
    title: str
    domain: str
    applicable: bool
    justification: str
    implementation_status: str
    treatment: str | None
    coverage: str
    controls: list[SoaControl] = field(default_factory=list)
    #: The newest reviewed test across the implementing controls (decision 7).
    last_test_date: date | None = None
    last_test_result: str | None = None
    #: Tests awaiting review across the implementing controls — shown, never counted.
    pending_review_count: int = 0
    #: Phase 4C: not tested directly but covered by a tested control of an equivalent or
    #: containing clause (``crosswalks.ViaCrosswalk``). Never a direct mapping.
    via_crosswalk: object = None

    @property
    def via_text(self) -> str:
        """"Covered via crosswalk, not a direct mapping: mapped via ISO/IEC 27001:2022
        A.8.5 (equivalent) — A.8.5 Secure authentication (effective)"."""
        v = self.via_crosswalk
        if v is None:
            return ""
        controls = "; ".join(f"{c.label()} ({_words(c.effectiveness)})" for c in v.controls)
        return (
            f"Covered via crosswalk, not a direct mapping: {v.label} ({v.relationship})"
            + (f" — {controls}" if controls else "")
        )


def _awaiting(n: int) -> str:
    return f"{n} test{'s' if n != 1 else ''} awaiting review"


def _words(value) -> str:
    v = _plain(value)
    return str(v).replace("_", " ") if v not in (None, "") else "—"


def control_row(c) -> SoaControl:
    return SoaControl(
        id=c.id,
        reference=c.reference or "",
        name=c.name or "",
        effectiveness=_plain(c.effectiveness) or "not_assessed",
        status=_plain(c.status) or "",
        # Decision 7: an examiner's SoA shows tests a reviewer signed off, not the log.
        last_test_date=getattr(c, "last_reviewed_date", None),
        last_test_result=_plain(getattr(c, "last_reviewed_result", None)),
        pending_review_count=int(getattr(c, "pending_review_count", 0) or 0),
    )


def build_row(r, via=None) -> SoaRow:
    """One SoA row from a loaded requirement (duck-typed: ORM row or test double)."""
    controls = sorted(
        (control_row(c) for c in (r.controls or []) if not getattr(c, "deleted", False)),
        key=lambda c: (natural_key(c.reference), c.name.lower()),
    )
    tested = [c for c in controls if c.last_test_date is not None]
    latest = max(tested, key=lambda c: c.last_test_date) if tested else None
    return SoaRow(
        requirement_id=r.id,
        reference=r.reference or "",
        title=r.title or "",
        domain=r.domain or "",
        applicable=is_applicable(r.treatment, r.status),
        justification=getattr(r, "applicability_justification", "") or "",
        implementation_status=_plain(r.status) or NOT_ASSESSED,
        treatment=_plain(r.treatment),
        coverage=getattr(r, "coverage", "unmapped"),
        controls=controls,
        last_test_date=latest.last_test_date if latest else None,
        last_test_result=latest.last_test_result if latest else None,
        pending_review_count=sum(c.pending_review_count for c in controls),
        via_crosswalk=via if getattr(r, "coverage", "unmapped") in ("unmapped", "unassessed") else None,
    )


def build_rows(requirements, via_crosswalk: dict | None = None) -> list[SoaRow]:
    """``via_crosswalk``: requirement id → ``crosswalks.ViaCrosswalk``."""
    via = via_crosswalk or {}
    live = [r for r in requirements if not getattr(r, "deleted", False)]
    return [build_row(r, via.get(r.id)) for r in sorted(live, key=lambda r: (natural_key(r.reference), r.title or ""))]


def summarize(rows: list[SoaRow]) -> dict[str, int]:
    return {
        "total": len(rows),
        "applicable": sum(1 for r in rows if r.applicable),
        "excluded": sum(1 for r in rows if not r.applicable),
        "no_control": sum(1 for r in rows if r.applicable and not r.controls),
        "missing_justification": sum(1 for r in rows if not r.applicable and not r.justification.strip()),
        "mapped": sum(1 for r in rows if r.applicable and r.controls),
        "assured": sum(1 for r in rows if r.applicable and r.coverage == "assured"),
        "via_crosswalk": sum(1 for r in rows if r.applicable and r.via_crosswalk is not None),
    }


def coverage_text(counts: dict) -> str:
    """"40 of 93 applicable clauses mapped to a control; 6 backed by a tested control" —
    mapped is not tested, and the export says both (F-19)."""
    applicable = counts.get("applicable", 0)
    if not applicable:
        return "No applicable clauses"
    mapped = counts.get("mapped", applicable - counts.get("no_control", 0))
    text = (
        f"{mapped} of {applicable} applicable clauses mapped to a control; "
        f"{counts.get('assured', 0)} backed by a tested control"
    )
    if counts.get("via_crosswalk"):
        text += f"; {counts['via_crosswalk']} covered via crosswalk (not direct mappings)"
    return text


def filter_rows(rows: list[SoaRow], view: str | None) -> list[SoaRow]:
    if view == "applicable":
        return [r for r in rows if r.applicable]
    if view == "excluded":
        return [r for r in rows if not r.applicable]
    if view == "no_control":
        return [r for r in rows if r.applicable and not r.controls]
    return list(rows)


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------
@dataclass
class SoaDocument:
    org_name: str
    framework_name: str
    version: str
    rows: list[SoaRow]
    #: Counts over the whole framework, even when ``rows`` is a filtered view.
    summary: dict | None = None
    #: all | applicable | excluded | no_control — printed on a filtered export.
    view: str = "all"
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.summary is None:
            self.summary = summarize(self.rows)

    @property
    def generated(self) -> str:
        return self.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    @property
    def view_label(self) -> str:
        return {
            "applicable": "Applicable clauses only",
            "excluded": "Excluded clauses only",
            "no_control": "Applicable clauses without an implementing control",
        }.get(self.view, "")


HEADERS = [
    "Reference", "Clause", "Domain", "Applicable", "Justification",
    "Implementing controls", "Implementation status", "Last reviewed test date",
    "Last reviewed test result", "Tests awaiting review",
]


def table_rows(rows: list[SoaRow]) -> list[list]:
    return [
        [
            r.reference, r.title, r.domain, "Yes" if r.applicable else "No", r.justification,
            "\n".join([c.label() for c in r.controls] + ([r.via_text] if r.via_text else [])),
            _words(r.implementation_status),
            r.last_test_date.isoformat() if r.last_test_date else "",
            _words(r.last_test_result) if r.last_test_result else "",
            r.pending_review_count or "",
        ]
        for r in rows
    ]


def to_xlsx(doc: SoaDocument) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Excel export requires the 'openpyxl' package on the server.",
        ) from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Statement of Applicability"
    bold = Font(bold=True)
    counts = doc.summary
    header = [
        ("Statement of Applicability", ""),
        ("Organisation", doc.org_name),
        ("Framework", doc.framework_name),
        ("Version", doc.version or "—"),
        ("Generated", doc.generated),
        ("Clauses", f"{counts['total']} — {counts['applicable']} applicable, "
                    f"{counts['excluded']} excluded, {counts['no_control']} applicable without a control"),
        ("Coverage", coverage_text(counts)),
    ]
    if doc.view_label:
        header.append(("Showing", doc.view_label))
    for label, value in header:
        ws.append([label, value])
        ws.cell(row=ws.max_row, column=1).font = bold
    ws.cell(row=1, column=1).font = Font(bold=True, size=14)
    ws.append([])
    first = ws.max_row + 1
    ws.append(HEADERS)
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="1D4FD7")
    for cell in ws[first]:
        cell.font = head_font
        cell.fill = head_fill
    body = table_rows(doc.rows)
    wrap = Alignment(wrap_text=True, vertical="top")
    for row in body:
        ws.append(row)
        for cell in ws[ws.max_row]:
            cell.alignment = wrap
    ws.freeze_panes = ws.cell(row=first + 1, column=1)
    if body:
        ws.auto_filter.ref = f"A{first}:{get_column_letter(len(HEADERS))}{first + len(body)}"
    for index, width in enumerate((12, 40, 24, 11, 45, 55, 20, 14, 14, 12), start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(doc: SoaDocument) -> bytes:
    from app.services import pdf_report as pr

    pr._require_reportlab()
    from reportlab.platypus import Paragraph, Spacer

    ss = pr._styles()
    counts = doc.summary
    version = f" · version {doc.version}" if doc.version else ""
    showing = f" · {doc.view_label}" if doc.view_label else ""
    story = pr._title_block(
        ss, "Statement of Applicability",
        escape(f"{doc.framework_name}{version} · generated {doc.generated}{showing}"),
        escape(doc.org_name),
    )
    story += [
        pr._kpis(ss, [
            ("Clauses", str(counts["total"])),
            ("Applicable", str(counts["applicable"])),
            ("Excluded", str(counts["excluded"])),
            ("Applicable, no control", str(counts["no_control"])),
            ("Applicable, tested control", str(counts.get("assured", 0))),
            *([("Covered via crosswalk", str(counts["via_crosswalk"]))] if counts.get("via_crosswalk") else []),
        ]),
        Spacer(1, 10),
    ]

    def cell(text: str, bold: bool = False):
        return Paragraph(escape(text or "—").replace("\n", "<br/>"), ss["NxCellB" if bold else "NxCell"])

    rows = [
        [
            cell(r.reference, bold=True),
            cell(r.title),
            cell("Yes" if r.applicable else "No", bold=not r.applicable),
            cell(r.justification),
            cell("\n".join([c.label() for c in r.controls] + ([r.via_text] if r.via_text else []))
                 or ("None" if r.applicable else "—")),
            cell(_words(r.implementation_status).capitalize()),
            cell(
                (f"{r.last_test_date.isoformat()} ({_words(r.last_test_result)})" if r.last_test_date else "Never")
                + (f"\n{_awaiting(r.pending_review_count)}" if r.pending_review_count else "")
            ),
        ]
        for r in doc.rows
    ]
    story.append(pr._table(
        ss, ["Ref", "Clause", "Applicable", "Justification", "Implementing controls", "Status", "Last reviewed test"],
        rows, col_widths=[50, 140, 55, 170, 180, 70, 75],
    ))
    return pr._render(story, doc.org_name, landscape=True)
