"""PDF report generation with ReportLab (pure-Python, air-gap friendly).

No headless browser and no external font files — uses the built-in Helvetica family
so it runs in a locked-down on-prem container. ``reportlab`` is imported lazily so
the app boots without it; PDF endpoints then return a clear 501.

Public generators take already-loaded (RLS-scoped) data from the API layer and return
PDF bytes: board packs, audit-committee reports, Shariah-board reports and the risk
report. Nothing here queries — the caller loads and scopes, this renders, which is what
keeps a filtered export and the screen it came from in agreement.
"""
from __future__ import annotations

from typing import Any

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException, status

#: Usable width between the page margins (A4 less 2 x 18mm), in points. Column widths
#: are budgeted against this: overshoot it and ReportLab silently squeezes columns until
#: words like "CRITICAL" break mid-syllable.
CONTENT_WIDTH = 493
#: The same for a landscape page — what a wide report table gets.
LANDSCAPE_CONTENT_WIDTH = 740

PRIMARY = "#1d4fd7"
INK = "#111827"
MUTED = "#6b7280"
LINE = "#d0d5dd"
ZEBRA = "#f5f7fb"
_SEV_COLOR = {"low": "#166434", "medium": "#b7791f", "high": "#c03f0c", "critical": "#ba1c1c"}


def _require_reportlab():
    try:
        import reportlab  # noqa: F401, PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="PDF export requires the 'reportlab' package to be installed on the server.",
        ) from exc


def _styles():
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("NxTitle", parent=ss["Title"], fontName="Helvetica-Bold",
                          fontSize=22, textColor=PRIMARY, spaceAfter=2, leading=26))
    ss.add(ParagraphStyle("NxSub", fontName="Helvetica", fontSize=10.5, textColor=MUTED, spaceAfter=2))
    ss.add(ParagraphStyle("NxH2", fontName="Helvetica-Bold", fontSize=13, textColor=INK,
                          spaceBefore=14, spaceAfter=6, leading=16))
    ss.add(ParagraphStyle("NxBody", fontName="Helvetica", fontSize=9.5, textColor=INK,
                          leading=13, alignment=TA_LEFT))
    ss.add(ParagraphStyle("NxCell", fontName="Helvetica", fontSize=8.5, textColor=INK, leading=11))
    ss.add(ParagraphStyle("NxCellB", parent=ss["NxCell"], fontName="Helvetica-Bold"))
    return ss


def _footer(org_name: str):
    from reportlab.lib.units import mm

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 12 * mm, f"{org_name} — Confidential")
        canvas.drawCentredString(canvas._pagesize[0] / 2, 12 * mm, f"Generated {generated}")
        canvas.drawRightString(canvas._pagesize[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def content_width(landscape: bool = False) -> int:
    """Usable width between the margins for either orientation, in points."""
    return LANDSCAPE_CONTENT_WIDTH if landscape else CONTENT_WIDTH


def _render(story, org_name: str, landscape: bool = False) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.pagesizes import landscape as _landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=_landscape(A4) if landscape else A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
    )
    foot = _footer(org_name)
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()


# --------------------------------------------------------------- flowable helpers ---
def _title_block(ss, title: str, subtitle: str, org_name: str):
    from reportlab.platypus import Paragraph, Spacer

    return [
        Paragraph(org_name, ss["NxSub"]),
        Paragraph(title, ss["NxTitle"]),
        Paragraph(subtitle, ss["NxSub"]),
        Spacer(1, 10),
    ]


def _h2(ss, text: str):
    from reportlab.platypus import Paragraph
    return Paragraph(text, ss["NxH2"])


def _body(ss, text: str):
    from reportlab.platypus import Paragraph
    return Paragraph((text or "—").replace("\n", "<br/>"), ss["NxBody"])


def _kv(ss, pairs: list[tuple[str, str]]):
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Table, TableStyle

    data = [[Paragraph(k, ss["NxCellB"]), Paragraph(str(v) if v not in (None, "") else "—", ss["NxCell"])]
            for k, v in pairs]
    t = Table(data, colWidths=[45 * mm, None])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _table(ss, headers: list[str], rows: list[list], col_widths=None):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    head = [Paragraph(f"<font color='white'>{h}</font>", ss["NxCellB"]) for h in headers]
    body = [[c if hasattr(c, "wrap") else Paragraph(str(c) if c not in (None, "") else "—", ss["NxCell"]) for c in r]
            for r in rows]
    t = Table([head] + body, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(PRIMARY)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(ZEBRA)]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _sev_chip(ss, sev: str):
    from reportlab.platypus import Paragraph
    color = _SEV_COLOR.get((sev or "").lower(), MUTED)
    return Paragraph(f"<font color='{color}'><b>{(sev or '—').upper()}</b></font>", ss["NxCell"])


def _kpis(ss, items: list[tuple[str, str]]):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    cells = [[Paragraph(f"<font size=16 color='{PRIMARY}'><b>{v}</b></font><br/>"
                        f"<font size=8 color='{MUTED}'>{k}</font>", ss["NxCell"]) for k, v in items]]
    t = Table(cells, colWidths=[(180 / len(items))] + [None] * (len(items) - 1) if items else None)
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _d(value) -> str:
    return str(value) if value not in (None, "") else "—"


# ==================================================================== generators ===
def audit_engagement_pdf(eng, org_name: str) -> bytes:
    """Internal-audit engagement report (audit-committee pack)."""
    _require_reportlab()
    from reportlab.platypus import Spacer
    ss = _styles()
    story = _title_block(ss, f"Internal Audit Report — {eng.reference}",
                         eng.title, org_name)
    story += [_kpis(ss, [("Findings", str(eng.finding_count)),
                         ("Open", str(eng.open_finding_count)),
                         ("Status", eng.status.value.replace("_", " ").title())]), Spacer(1, 4)]
    story += [_h2(ss, "Engagement details"), _kv(ss, [
        ("Reference", eng.reference), ("Lead auditor", eng.lead_auditor),
        ("Audit team", eng.audit_team), ("Status", eng.status.value),
        ("Period", f"{_d(eng.period_start)} – {_d(eng.period_end)}"),
        ("Planned", f"{_d(eng.planned_start)} – {_d(eng.planned_end)}"),
        ("Overall opinion", eng.rating.value.title() if eng.rating else "—"),
    ])]
    story += [_h2(ss, "Scope"), _body(ss, eng.scope), _h2(ss, "Objectives"), _body(ss, eng.objectives)]
    if eng.procedures:
        story += [_h2(ss, "Working papers")]
        rows = [[p.title, p.result.value.replace("_", " ").title(), p.workpaper_ref or "—", p.performed_by or "—"]
                for p in eng.procedures]
        story += [_table(ss, ["Procedure", "Result", "WP ref", "By"], rows,
                         col_widths=[240, 70, 70, 90])]
    if eng.findings:
        story += [_h2(ss, "Findings")]
        rows = [[f.reference, f.title, _sev_chip(ss, f.rating.value), f.action_owner or "—",
                 _d(f.due_date), f.status.value.replace("_", " ").title()] for f in eng.findings]
        story += [_table(ss, ["Ref", "Finding", "Rating", "Owner", "Due", "Status"], rows,
                         col_widths=[52, 190, 55, 80, 60, 65])]
    if eng.conclusion:
        story += [_h2(ss, "Conclusion"), _body(ss, eng.conclusion)]
    return _render(story, org_name)


def shariah_review_pdf(rev, org_name: str) -> bytes:
    """Shariah compliance review report (Shariah-board pack)."""
    _require_reportlab()
    from reportlab.platypus import Spacer
    ss = _styles()
    story = _title_block(ss, f"Shariah Review Report — {rev.reference}", rev.title, org_name)
    story += [_kpis(ss, [("SNC findings", str(rev.finding_count)),
                         ("Open", str(rev.open_finding_count)),
                         ("Income to purify", f"{rev.snc_income_total:,.2f}")]), Spacer(1, 4)]
    story += [_h2(ss, "Review details"), _kv(ss, [
        ("Reference", rev.reference), ("Reviewer", rev.reviewer),
        ("Type", rev.review_type), ("Status", rev.status.value),
        ("Period", f"{_d(rev.period_start)} – {_d(rev.period_end)}"),
        ("Rating", rev.rating.value.title() if rev.rating else "—"),
    ])]
    story += [_h2(ss, "Scope"), _body(ss, rev.scope)]
    if rev.findings:
        story += [_h2(ss, "Shariah Non-Compliance (SNC) findings")]
        rows = [[f.reference, f.title, _sev_chip(ss, f.severity.value),
                 f"{float(f.snc_income_amount):,.2f}" if f.snc_income_amount else "—",
                 f.action_owner or "—", f.status.value.replace("_", " ").title()] for f in rev.findings]
        story += [_table(ss, ["Ref", "Finding", "Severity", "SNC income", "Owner", "Status"], rows,
                         col_widths=[52, 180, 60, 70, 75, 65])]
    if rev.conclusion:
        story += [_h2(ss, "Conclusion"), _body(ss, rev.conclusion)]
    return _render(story, org_name)


@dataclass
class RiskReportContext:
    """Everything the register report needs that is not on a ``Risk`` row.

    Gathered by the API layer (which alone knows the tenant's matrix and can resolve
    owner names) and passed in, so this module stays a pure renderer over loaded data.
    """

    org_name: str
    appetite: int
    tolerance: int
    max_score: int
    matrix_size: int
    #: Human description of the filter the register was exporting under, e.g.
    #: "Digital Banking · Assessed". Printed on the cover so a PDF circulating on its
    #: own can never be mistaken for the whole register.
    scope: str = "Whole register"
    #: Risk owner id -> display name. Absent ids render as "Unassigned".
    owner_names: dict = field(default_factory=dict)
    #: Per-risk detail pages. Off for a quick table-only export.
    include_details: bool = True
    #: Phase 2: per-category appetite (``risk_scoring.AppetiteBook``) and the tenant's
    #: banding (``risk_scoring.SeverityScale``). None falls back to the single values above.
    book: Any = None
    scale: Any = None
    #: Decision 4: the reporting currency the money lines are written in (risk ALE and
    #: treatment cost carry no currency of their own).
    currency: str = "PKR"

    def thresholds(self, risk) -> tuple[int, int]:
        """(appetite, tolerance) for this risk: its category's, else the default."""
        if self.book is not None:
            return self.book.thresholds(getattr(risk, "category_id", None))
        return self.appetite, self.tolerance

    @property
    def bands(self):
        return self.scale.bands if self.scale is not None else None


def _severity_of(score, max_score: int, bands=None) -> str:
    from app.services.risk_scoring import severity_for_score

    band = severity_for_score(score, max_score, bands)
    return band.value if band is not None else ""


def _appetite_label(score, appetite: int, tolerance: int) -> tuple[str, str]:
    """(label, colour) for a score against the org's thresholds."""
    from app.services.risk_scoring import appetite_status

    status = appetite_status(score, appetite, tolerance)
    return {
        "within_appetite": ("Within appetite", _SEV_COLOR["low"]),
        "elevated": ("Elevated", _SEV_COLOR["medium"]),
        "breach": ("BREACH", _SEV_COLOR["critical"]),
    }.get(status or "", ("—", MUTED))


def _effective(risk):
    """Current exposure: the residual once assessed, otherwise the inherent score."""
    return risk.residual_score if risk.residual_score is not None else risk.inherent_score


def _names(items, attr: str = "name") -> str:
    return ", ".join(getattr(i, attr, "") or "" for i in items) or "—"


def _asset_line(asset) -> str:
    """Asset name followed by the classification a reader needs to judge the rating.

    A bare asset name tells a board nothing; "Core Banking — Information asset,
    Confidential, criticality Critical" is what makes the score defensible.
    """
    bits = []
    asset_class = getattr(asset, "asset_class", None)
    if asset_class is not None:
        # .title() would render "it_asset" as "It Asset", which reads as a typo in a
        # board pack. The two values are known, so spell them.
        bits.append({"it_asset": "IT asset", "information_asset": "Information asset"}
                    .get(asset_class.value, asset_class.value.replace("_", " ").title()))
    label = getattr(asset, "label", None)
    if label is not None and getattr(label, "name", ""):
        bits.append(label.name)
    for classification in getattr(asset, "classifications", None) or []:
        axis = getattr(classification, "type", None)
        axis_name = getattr(axis, "name", "") if axis is not None else ""
        bits.append(f"{axis_name}: {classification.name}" if axis_name else classification.name)
    criticality = getattr(asset, "criticality", None)
    if criticality is not None:
        bits.append(f"criticality {criticality.value.title()}")
    return f"{asset.name} — {', '.join(bits)}" if bits else asset.name


def _heat_map(ss, risks, matrix_size: int, max_score: int, scale=None):
    """Likelihood x impact grid with a count per cell, coloured by severity band.

    Impact ascends up the page and likelihood across it, which is the orientation every
    bank's methodology document draws, so the picture in the pack matches the picture in
    the policy. Counts use each risk's *effective* score position — residual where it has
    been assessed, inherent where it has not — because that is the exposure the board is
    being asked about.
    """
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    counts: dict[tuple[int, int], int] = {}
    for risk in risks:
        likelihood = risk.residual_likelihood if risk.residual_score is not None else risk.inherent_likelihood
        impact = risk.residual_impact if risk.residual_score is not None else risk.inherent_impact
        if likelihood and impact:
            counts[(likelihood, impact)] = counts.get((likelihood, impact), 0) + 1

    header = [Paragraph("<font size=7 color='%s'><b>I \\ L</b></font>" % MUTED, ss["NxCell"])]
    header += [Paragraph(f"<font size=7 color='{MUTED}'>{n}</font>", ss["NxCell"])
               for n in range(1, matrix_size + 1)]
    data = [header]
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.white),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_index, impact in enumerate(range(matrix_size, 0, -1), start=1):
        row = [Paragraph(f"<font size=7 color='{MUTED}'>{impact}</font>", ss["NxCell"])]
        for col_index, likelihood in enumerate(range(1, matrix_size + 1), start=1):
            count = counts.get((likelihood, impact), 0)
            if scale is not None:  # the tenant's bands and any per-cell override
                band = scale.for_cell(likelihood, impact)
                colour = _SEV_COLOR.get(band.value if band else "", MUTED)
            else:
                colour = _SEV_COLOR.get(_severity_of(likelihood * impact, max_score), MUTED)
            style.append(("BACKGROUND", (col_index, row_index), (col_index, row_index),
                          colors.HexColor(colour)))
            row.append(Paragraph(
                f"<font color='white' size=9><b>{count or ''}</b></font>", ss["NxCell"]
            ))
        data.append(row)

    # The row-label column only ever holds one or two digits; everything else goes to
    # the grid, which is the part being read.
    label_width = 26
    cell = (CONTENT_WIDTH - label_width) / matrix_size
    table = Table(
        data,
        colWidths=[label_width] + [cell] * matrix_size,
        rowHeights=[14] + [18] * matrix_size,
    )
    table.setStyle(TableStyle(style))
    return table


def _band_legend(ss, max_score: int, bands=None) -> str:
    from app.services.risk_scoring import band_ranges

    return " · ".join(
        f"{severity.value.title()} {low}–{high}"
        for low, high, severity in band_ranges(max_score, bands)
    )


def risk_register_pdf(risks, context: RiskReportContext) -> bytes:
    """The risk report a board or a regulator actually asks for.

    Three parts, in the order they get read: a cover that says what this is and what it
    covers, a one-line-per-risk register, and — for anything above appetite — a detail
    page carrying the controls, the assets with their classification, both ratings and
    the treatment plan. The scope line is printed on the cover because a filtered export
    circulating without it is indistinguishable from the whole register.
    """
    _require_reportlab()
    from reportlab.platypus import PageBreak, Spacer

    ss = _styles()
    max_score = context.max_score
    ordered = sorted(risks, key=lambda r: (_effective(r) or 0), reverse=True)

    # Each risk against its own category's appetite and tolerance (Phase 2).
    breaches = [r for r in ordered if (_effective(r) or 0) > context.thresholds(r)[1]]
    elevated = [r for r in ordered
                if context.thresholds(r)[0] < (_effective(r) or 0) <= context.thresholds(r)[1]]

    # ---------------------------------------------------------------- cover
    story = _title_block(
        ss, "Risk Report",
        f"{context.scope} · {len(ordered)} risk(s) · "
        f"{context.matrix_size}x{context.matrix_size} matrix, scores 1–{max_score}",
        context.org_name,
    )
    story += [_kpis(ss, [
        ("Risks in report", str(len(ordered))),
        ("Above tolerance", str(len(breaches))),
        ("Elevated", str(len(elevated))),
        ("Within appetite", str(len(ordered) - len(breaches) - len(elevated))),
    ]), Spacer(1, 6)]

    story += [_h2(ss, "Methodology"), _kv(ss, [
        ("Scale", f"Likelihood 1–{context.matrix_size} x impact 1–{context.matrix_size}, "
                  f"score 1–{max_score}"),
        ("Severity bands", _band_legend(ss, max_score, context.bands)),
        ("Risk appetite", f"score ≤ {context.appetite}"
                          + (" (organisation default; set per category for "
                             f"{len(context.book.by_category)} categories)"
                             if context.book is not None and context.book.by_category else "")),
        ("Risk tolerance", f"score ≤ {context.tolerance} (above this is a breach)"),
        ("Exposure shown", "Residual where assessed, otherwise inherent"),
    ])]

    story += [_h2(ss, "Heat map"), _heat_map(ss, ordered, context.matrix_size, max_score, context.scale)]

    # ------------------------------------------------------------- register
    story += [_h2(ss, "Risk register")]
    rows = []
    for risk in ordered:
        label, colour = _appetite_label(_effective(risk), *context.thresholds(risk))
        rows.append([
            risk.reference,
            risk.title,
            _names(risk.business_units) if risk.business_units else "—",
            _sev_chip(ss, _severity_of(risk.inherent_score, max_score, context.bands)),
            _sev_chip(ss, _severity_of(risk.residual_score, max_score, context.bands)),
            _chip(ss, label, colour),
            context.owner_names.get(risk.owner_id) or "Unassigned",
            str(len(risk.controls)),
        ])
    story += [_table(
        ss,
        ["Ref", "Risk", "Segment", "Inherent", "Residual", "Appetite", "Owner", "Ctrls"],
        rows,
        # Sums to 488 of the 493 available. Sized so the two things a reader scans for
        # never wrap: the severity words ("CRITICAL") and the column headings.
        col_widths=[40, 104, 66, 56, 56, 62, 64, 40],
    )]

    # -------------------------------------------------------- detail pages
    if context.include_details and ordered:
        story += [PageBreak(), _h2(ss, "Risk detail")]
        for index, risk in enumerate(ordered):
            if index:
                story += [PageBreak()]
            story += _risk_detail(ss, risk, context)

    return _render(story, context.org_name)


def _chip(ss, text: str, colour: str):
    from reportlab.platypus import Paragraph
    return Paragraph(f"<font color='{colour}'><b>{text}</b></font>", ss["NxCell"])


def _risk_detail(ss, risk, context: RiskReportContext) -> list:
    """One risk, in the detail a reviewer needs to challenge the rating."""
    from reportlab.platypus import Paragraph

    max_score = context.max_score
    label, colour = _appetite_label(_effective(risk), *context.thresholds(risk))

    flow = [
        Paragraph(f"{risk.reference} — {risk.title}", ss["NxH2"]),
        _kv(ss, [
            ("Category", risk.category),
            ("Status", risk.status.value.replace("_", " ").title()),
            ("Owner", context.owner_names.get(risk.owner_id) or "Unassigned"),
            ("Business units", _names(risk.business_units)),
            ("Processes", _names(risk.processes)),
            ("Inherent",
             f"L{risk.inherent_likelihood} x I{risk.inherent_impact} = {risk.inherent_score} "
             f"({_severity_of(risk.inherent_score, max_score, context.bands).title()})"),
            ("Residual",
             f"L{risk.residual_likelihood} x I{risk.residual_impact} = {risk.residual_score} "
             f"({_severity_of(risk.residual_score, max_score, context.bands).title()})"
             if risk.residual_score is not None else "Not yet assessed"),
            ("Target",
             f"L{risk.target_likelihood} x I{risk.target_impact} = "
             f"{risk.target_likelihood * risk.target_impact}"
             if getattr(risk, "target_likelihood", None) and getattr(risk, "target_impact", None)
             else "Not set"),
            ("Against appetite", label),
            ("Type · velocity · source", " · ".join(
                (getattr(risk, name, None) or "—").replace("_", " ").title()
                for name in ("risk_type", "velocity", "source")
            )),
            ("Annual loss exposure",
             f"{context.currency} {risk.annual_loss_expectancy:,.2f}" if risk.annual_loss_expectancy else "—"),
            ("Next review", _d(risk.next_review_date)),
        ]),
    ]
    statement = [
        (label_, text_) for label_, text_ in (
            ("Cause", getattr(risk, "cause", "")), ("Event", getattr(risk, "event", "")),
            ("Consequence", getattr(risk, "consequence", "")),
        ) if text_
    ]
    if statement:
        flow += [_h2(ss, "Risk statement"), _kv(ss, statement)]
    if risk.description:
        flow += [_h2(ss, "Description"), _body(ss, risk.description)]
    if getattr(risk, "assessment_rationale", ""):
        assessed = getattr(risk, "last_assessed_at", None)
        flow += [_h2(ss, "Assessment rationale" + (f" (assessed {_d(assessed.date())})" if assessed else "")),
                 _body(ss, risk.assessment_rationale)]

    if risk.assets:
        flow += [_h2(ss, "Assets at risk")]
        flow += [_table(ss, ["Asset and classification"],
                        [[_asset_line(a)] for a in risk.assets], col_widths=[None])]

    if risk.controls:
        flow += [_h2(ss, "Mitigating controls")]
        rows = [[
            control.reference or "—",
            control.name,
            control.effectiveness.value.replace("_", " ").title() if control.effectiveness else "—",
            control.status.value.replace("_", " ").title() if control.status else "—",
            control.owner or "—",
            _d(control.next_audit_date),
        ] for control in risk.controls]
        flow += [_table(ss, ["Ref", "Control", "Effectiveness", "Status", "Owner", "Next test"],
                        rows, col_widths=[52, 150, 72, 62, 78, 58])]
    else:
        flow += [_h2(ss, "Mitigating controls"),
                 _body(ss, "None linked — the residual rating rests on nothing recorded here.")]

    treatment = risk.treatment_strategy.value.title() if risk.treatment_strategy else "Not decided"
    flow += [_h2(ss, "Treatment"), _kv(ss, [
        ("Strategy", treatment),
        ("Owner", risk.treatment_owner),
        ("Deadline", _d(risk.treatment_deadline)),
        ("Cost", f"{context.currency} {risk.treatment_cost:,.2f}" if risk.treatment_cost else "—"),
    ])]
    if risk.treatment_description:
        flow += [_body(ss, risk.treatment_description)]

    accepted = [a for a in (risk.acceptances or [])]
    if accepted:
        flow += [_h2(ss, "Acceptance history")]
        rows = [[a.status.value.title(), _d(a.expires_at), _d(a.decided_at),
                 (a.rationale or "—")[:300]] for a in accepted]
        flow += [_table(ss, ["Decision", "Expires", "Decided", "Rationale"], rows,
                        col_widths=[62, 62, 62, None])]
    return flow


def tabular_report_pdf(
    *,
    title: str,
    org_name: str,
    subject_label: str,
    run_by: str,
    params: list[tuple[str, str]],
    summary: dict[str, dict[str, int]],
    headers: list[str],
    rows: list[list],
    widths: list[int],
    landscape: bool = False,
    detail: list | None = None,
) -> bytes:
    """A report-builder run as a pack: cover, breakdowns, the table, optional detail.

    The cover states every filter that was applied. A filtered report circulating
    without that is indistinguishable from the whole register, which is how one
    segment's exposure gets read as the bank's. ``widths`` are relative hints from the
    subject registry, scaled to whatever the page orientation allows; the caller picks
    landscape once the chosen columns would not fit upright.
    """
    _require_reportlab()
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    ss = _styles()
    story = _title_block(
        ss, title, f"{subject_label} · {len(rows)} row(s) · run by {run_by}", org_name
    )

    story += [_h2(ss, "Parameters")]
    story += [_kv(ss, params or [("Filters", "None — whole register")])]

    if summary:
        story += [_h2(ss, "Summary")]
        blocks = []
        for section, counts in summary.items():
            body = "<br/>".join(
                f"{k}: <b>{n}</b>" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])
            ) or "—"
            blocks.append(Paragraph(f"<b>{section}</b><br/>{body}", ss["NxCell"]))
        story += [_side_by_side(blocks, content_width(landscape)), Spacer(1, 4)]

    story += [_h2(ss, "Results")]
    if rows:
        total = float(sum(widths) or 1)
        available = content_width(landscape) - 4
        col_widths = [max(28, available * w / total) for w in widths]
        story += [_table(ss, headers, rows, col_widths=col_widths)]
    else:
        story += [_body(ss, "No records match these parameters.")]

    if detail:
        story += [PageBreak()] + detail

    return _render(story, org_name, landscape=landscape)


def _side_by_side(flowables: list, width: float):
    """Lay small blocks out in one row, equal widths, no borders."""
    from reportlab.lib import colors
    from reportlab.platypus import Spacer, Table, TableStyle

    if not flowables:
        return Spacer(1, 0)  # pragma: no cover
    t = Table([flowables], colWidths=[width / len(flowables)] * len(flowables))
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def risk_detail_pages(risks, context: RiskReportContext) -> list:
    """The per-risk detail flowables, for a report builder run over risks."""
    from reportlab.platypus import PageBreak

    ss = _styles()
    flow: list = [_h2(ss, "Risk detail")]
    for index, risk in enumerate(risks):
        if index:
            flow.append(PageBreak())
        flow += _risk_detail(ss, risk, context)
    return flow


def executive_summary_pdf(stats: dict, org_name: str) -> bytes:
    """One-page executive/board GRC posture summary."""
    _require_reportlab()
    from reportlab.platypus import Spacer
    ss = _styles()
    story = _title_block(ss, "Executive GRC Summary", "Governance, risk & compliance posture", org_name)
    story += [_kpis(ss, [
        ("Total risks", str(stats.get("total_risks", 0))),
        ("In breach", str(stats.get("risks_in_breach", 0))),
        ("Controls", str(stats.get("total_controls", 0))),
        ("Overdue reviews", str(stats.get("overdue_reviews", 0))),
    ]), Spacer(1, 6)]
    story += [_h2(ss, "Risk posture"), _kv(ss, [
        ("Risk appetite", stats.get("appetite_score")),
        ("Risk tolerance", stats.get("tolerance_score")),
        ("Within appetite", stats.get("risks_within_appetite")),
        ("Elevated", stats.get("risks_elevated")),
        ("In breach", stats.get("risks_in_breach")),
        ("Total annual loss exposure",
         f"{stats.get('exposure_currency') or 'PKR'} {stats.get('total_exposure', 0):,.2f}"),
        ("Pending risk acceptances", stats.get("pending_acceptances")),
    ])]
    by_status = stats.get("risks_by_status") or {}
    if by_status:
        story += [_h2(ss, "Risks by status"),
                  _table(ss, ["Status", "Count"], [[k.title(), str(v)] for k, v in by_status.items()],
                         col_widths=[200, 80])]
    return _render(story, org_name)


# ================================================================ board packs ===
# Phase 3: the committee's board pack. ``board_pack.section_views`` words every section;
# these functions only lay the words out, in the house style above, so the PDF and the
# spreadsheet built from the same views say the same thing.
def _pack_text(value) -> str:
    from xml.sax.saxutils import escape

    return escape(str(value)) if value not in (None, "") else "—"


def _pack_kpis(ss, items: list[tuple[str, str]], width: float = CONTENT_WIDTH):
    """A row of headline figures, equal widths (values are short phrases, not numbers
    alone, so the large single-number style of :func:`_kpis` would wrap)."""
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    cells = [[Paragraph(f"<font size=12.5 color='{PRIMARY}'><b>{_pack_text(v)}</b></font><br/>"
                        f"<font size=7.5 color='{MUTED}'>{_pack_text(k)}</font>", ss["NxCell"]) for k, v in items]]
    t = Table(cells, colWidths=[width / len(items)] * len(items))
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _pack_table(ss, headers: list[str], rows: list[list], col_widths, colour: str):
    """A board-pack table in the organisation's colour."""
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    head = [Paragraph(f"<font color='white'>{h}</font>", ss["NxCellB"]) for h in headers]
    body = [[Paragraph(str(c) if c not in (None, "") else "—", ss["NxCell"]) for c in r] for r in rows]
    t = Table([head] + body, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(colour)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(ZEBRA)]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor(LINE)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _commentary_box(ss, text: str, colour: str):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    body = _pack_text(text).replace("\n", "<br/>")
    t = Table([[Paragraph(f"<font color='{colour}'><b>Commentary</b></font><br/>{body}", ss["NxBody"])]],
              colWidths=[CONTENT_WIDTH])
    t.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor(colour)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(ZEBRA)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _heatmap_drawing(data: dict):
    """Likelihood (rows, high at the top) x impact (columns); each cell coloured by its
    band with the number of risks in it."""
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.lib import colors

    size = max(1, min(10, int(data.get("size") or 5)))
    cells = data.get("cells") or {}
    bands = data.get("bands") or {}
    cell, left, bottom = 34, 34, 22
    fill = {"low": "#dcfce7", "medium": "#fef3c7", "high": "#ffedd5", "critical": "#fee2e2"}
    d = Drawing(left + size * cell + 10, bottom + size * cell + 16)
    for like in range(1, size + 1):
        for imp in range(1, size + 1):
            key = f"{like},{imp}"
            x, y = left + (imp - 1) * cell, bottom + (like - 1) * cell
            d.add(Rect(x, y, cell, cell, fillColor=colors.HexColor(fill.get(str(bands.get(key) or ""), "#f3f4f6")),
                       strokeColor=colors.HexColor(LINE), strokeWidth=0.5))
            n = int(cells.get(key, 0) or 0)
            if n:
                d.add(String(x + cell / 2, y + cell / 2 - 4, str(n), fontName="Helvetica-Bold", fontSize=10,
                             fillColor=colors.HexColor(_SEV_COLOR.get(str(bands.get(key) or ""), INK)),
                             textAnchor="middle"))
    for i in range(1, size + 1):
        d.add(String(left + (i - 1) * cell + cell / 2, bottom - 12, str(i), fontSize=7.5,
                     fillColor=colors.HexColor(MUTED), textAnchor="middle"))
        d.add(String(left - 8, bottom + (i - 1) * cell + cell / 2 - 3, str(i), fontSize=7.5,
                     fillColor=colors.HexColor(MUTED), textAnchor="middle"))
    d.add(String(left + size * cell / 2, 0, "Impact", fontSize=8, fillColor=colors.HexColor(MUTED), textAnchor="middle"))
    d.add(String(2, bottom + size * cell + 4, "Likelihood", fontSize=8, fillColor=colors.HexColor(MUTED)))
    return d


def _appetite_trend_drawing(data: dict):
    """Stacked bars per point: within appetite, elevated, above tolerance. A point with
    no snapshot is drawn empty and labelled."""
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    points = data.get("points") or []
    d = Drawing(CONTENT_WIDTH, 170)
    chart = VerticalBarChart()
    chart.x, chart.y, chart.width, chart.height = 40, 30, CONTENT_WIDTH - 170, 120
    series = [[int(p.get(k) or 0) for p in points] for k in ("within", "elevated", "breach")]
    chart.data = series
    chart.categoryAxis.style = "stacked"
    chart.categoryAxis.categoryNames = [
        str(p.get("label")) + ("" if any(p.get(k) is not None for k in ("within", "elevated", "breach")) else "*")
        for p in points
    ]
    chart.categoryAxis.labels.fontSize = 7
    chart.valueAxis.labels.fontSize = 7
    chart.valueAxis.valueMin = 0
    for i, colour in enumerate(("#16a34a", "#d97706", "#dc2626")):
        chart.bars[i].fillColor = colors.HexColor(colour)
        chart.bars[i].strokeColor = None
    d.add(chart)
    lx = chart.x + chart.width + 16
    for i, (label, colour) in enumerate((("Within appetite", "#16a34a"), ("Elevated", "#d97706"),
                                         ("Above tolerance", "#dc2626"))):
        y = 130 - i * 16
        from reportlab.graphics.shapes import Rect

        d.add(Rect(lx, y, 9, 9, fillColor=colors.HexColor(colour), strokeColor=None))
        d.add(String(lx + 14, y + 1, label, fontSize=8, fillColor=colors.HexColor(INK)))
    if any(not any(p.get(k) is not None for k in ("within", "elevated", "breach")) for p in points):
        d.add(String(lx, 70, "* no snapshot", fontSize=7.5, fillColor=colors.HexColor(MUTED)))
    return d


def _kri_trend_drawing(series: dict, colour: str):
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.lib import colors

    readings = [r for r in series.get("readings", []) if r.get("value") is not None]
    width = (CONTENT_WIDTH - 12) / 2
    d = Drawing(width, 110)
    d.add(String(4, 98, str(series.get("name") or "")[:48], fontName="Helvetica-Bold", fontSize=8,
                 fillColor=colors.HexColor(INK)))
    if len(readings) < 2:
        return d
    plot = LinePlot()
    plot.x, plot.y, plot.width, plot.height = 34, 22, width - 46, 66
    plot.data = [[(i, float(r["value"])) for i, r in enumerate(readings)]]
    plot.lines[0].strokeColor = colors.HexColor(colour)
    plot.lines[0].strokeWidth = 1.5
    plot.xValueAxis.valueMin, plot.xValueAxis.valueMax = 0, len(readings) - 1
    plot.xValueAxis.valueSteps = list(range(len(readings)))
    plot.xValueAxis.labelTextFormat = lambda v: str(readings[int(v)].get("label") or "")[:5] if 0 <= int(v) < len(readings) else ""
    plot.xValueAxis.labels.fontSize = 6
    plot.yValueAxis.labels.fontSize = 6.5
    d.add(plot)
    return d


def _pack_footer(org_name: str, classification: str, draft: bool):
    from reportlab.lib.units import mm

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 12 * mm, f"{org_name} — {classification}")
        canvas.drawCentredString(canvas._pagesize[0] / 2, 12 * mm, f"Generated {generated}")
        canvas.drawRightString(canvas._pagesize[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
        if draft:
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor("#b7791f")
            canvas.drawRightString(canvas._pagesize[0] - 18 * mm, canvas._pagesize[1] - 11 * mm,
                                   "DRAFT — not yet released to the committee")
        canvas.restoreState()

    return draw


def board_pack_pdf(*, title: str, subtitle: str, cover: list[tuple[str, str]], views: list, org_name: str,
                   colour: str = PRIMARY, cover_title: str = "", classification: str = "Confidential",
                   logo_path: str | None = None, draft: bool = False) -> bytes:
    """The board pack: a cover page (the organisation's logo and cover title; what, for
    whom, which period, generated when and by whom), then each section — commentary,
    headline figures, charts, facts, tables and the note on how the figures were worked
    out. ``views`` are ``board_pack.SectionView`` objects. Every page carries the
    classification; a draft or reviewed pack is marked as not yet released."""
    _require_reportlab()
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import CondPageBreak, Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

    ss = _styles()
    ss["NxTitle"].textColor = colour
    story = []
    if logo_path:
        try:
            from reportlab.lib.utils import ImageReader

            iw, ih = ImageReader(logo_path).getSize()
            height = 18 * mm
            width = min(60 * mm, iw * height / ih) if ih else 40 * mm
            story += [Image(logo_path, width=width, height=width * ih / iw if iw else height, hAlign="LEFT"),
                      Spacer(1, 6)]
        except Exception:  # noqa: BLE001 - an unreadable logo never stops the pack
            pass
    if cover_title:
        story.append(Paragraph(f"<font color='{colour}'><b>{_pack_text(cover_title)}</b></font>", ss["NxSub"]))
    story += _title_block(ss, _pack_text(title), _pack_text(subtitle), _pack_text(org_name))
    story += [_kv(ss, [(_pack_text(k), _pack_text(v)) for k, v in cover]), Spacer(1, 8)]
    story.append(_body(ss, "Position figures (health score, appetite, top risks, control assurance, compliance, "
                           "issues, KRIs and third parties) are as at the date shown. Risk movement, failed tests "
                           "and incidents cover the period."))
    available = CONTENT_WIDTH - 4
    for index, view in enumerate(views):
        story.append(PageBreak() if index == 0 else CondPageBreak(180))
        story.append(_h2(ss, _pack_text(view.title)))
        if getattr(view, "commentary", ""):
            story += [_commentary_box(ss, view.commentary, colour), Spacer(1, 6)]
        if view.kpis:
            story += [_pack_kpis(ss, list(view.kpis)[:4]), Spacer(1, 6)]
        for chart in getattr(view, "charts", []) or []:
            flow = []
            flow.append(Paragraph(f"<b>{_pack_text(chart.title)}</b>", ss["NxBody"]))
            try:
                if chart.kind == "heatmap":
                    flow.append(_heatmap_drawing(chart.data))
                elif chart.kind == "appetite_trend":
                    flow.append(_appetite_trend_drawing(chart.data))
                elif chart.kind == "kri_trend":
                    from reportlab.platypus import Table

                    drawings = [_kri_trend_drawing(sr, colour) for sr in chart.data.get("series", [])]
                    rows = [drawings[i:i + 2] + [""] * (2 - len(drawings[i:i + 2])) for i in range(0, len(drawings), 2)]
                    if rows:
                        flow.append(Table(rows, colWidths=[CONTENT_WIDTH / 2] * 2))
            except Exception:  # noqa: BLE001 - a chart that cannot be drawn is skipped, the table remains
                continue
            if chart.note:
                flow.append(Paragraph(f"<font size=8 color='{MUTED}'>{_pack_text(chart.note)}</font>", ss["NxBody"]))
            flow.append(Spacer(1, 8))
            story.append(KeepTogether(flow))
        if view.facts:
            story += [_kv(ss, [(_pack_text(k), _pack_text(v)) for k, v in view.facts]), Spacer(1, 6)]
        for table in view.tables:
            story.append(Paragraph(f"<b>{_pack_text(table.caption)}</b>", ss["NxBody"]))
            story.append(Spacer(1, 3))
            if table.rows:
                total = float(sum(table.widths) or 1)
                widths = [max(28, available * w / total) for w in table.widths]
                story.append(_pack_table(ss, [_pack_text(h) for h in table.headers],
                                         [[_pack_text(c) for c in row] for row in table.rows], widths, colour))
                if table.total is not None and table.total > len(table.rows):
                    story.append(Paragraph(
                        f"<font size=8 color='{MUTED}'>Showing {len(table.rows)} of {table.total}; "
                        "the spreadsheet version of this pack lists them all.</font>", ss["NxBody"]))
            else:
                story.append(Paragraph(f"<font color='{MUTED}'>{_pack_text(table.empty)}</font>", ss["NxBody"]))
            story.append(Spacer(1, 8))
        for note in view.notes:
            story.append(Paragraph(f"<font size=8 color='{MUTED}'>{_pack_text(note)}</font>", ss["NxBody"]))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm)
    foot = _pack_footer(org_name, classification or "Confidential", draft)
    doc.build(story, onFirstPage=foot, onLaterPages=foot)
    return buf.getvalue()
