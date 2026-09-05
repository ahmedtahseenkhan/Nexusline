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

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException, status

#: Usable width between the page margins (A4 less 2 x 18mm), in points. Column widths
#: are budgeted against this: overshoot it and ReportLab silently squeezes columns until
#: words like "CRITICAL" break mid-syllable.
CONTENT_WIDTH = 493

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


def _render(story, org_name: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
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


def _severity_of(score, max_score: int) -> str:
    from app.services.risk_scoring import severity_for_score

    band = severity_for_score(score, max_score)
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


def _heat_map(ss, risks, matrix_size: int, max_score: int):
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


def _band_legend(ss, max_score: int) -> str:
    from app.services.risk_scoring import band_ranges

    return " · ".join(
        f"{severity.value.title()} {low}–{high}" for low, high, severity in band_ranges(max_score)
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

    breaches = [r for r in ordered if (_effective(r) or 0) > context.tolerance]
    elevated = [r for r in ordered
                if context.appetite < (_effective(r) or 0) <= context.tolerance]

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
        ("Severity bands", _band_legend(ss, max_score)),
        ("Risk appetite", f"score ≤ {context.appetite}"),
        ("Risk tolerance", f"score ≤ {context.tolerance} (above this is a breach)"),
        ("Exposure shown", "Residual where assessed, otherwise inherent"),
    ])]

    story += [_h2(ss, "Heat map"), _heat_map(ss, ordered, context.matrix_size, max_score)]

    # ------------------------------------------------------------- register
    story += [_h2(ss, "Risk register")]
    rows = []
    for risk in ordered:
        label, colour = _appetite_label(_effective(risk), context.appetite, context.tolerance)
        rows.append([
            risk.reference,
            risk.title,
            _names(risk.business_units) if risk.business_units else "—",
            _sev_chip(ss, _severity_of(risk.inherent_score, max_score)),
            _sev_chip(ss, _severity_of(risk.residual_score, max_score)),
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
    label, colour = _appetite_label(_effective(risk), context.appetite, context.tolerance)

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
             f"({_severity_of(risk.inherent_score, max_score).title()})"),
            ("Residual",
             f"L{risk.residual_likelihood} x I{risk.residual_impact} = {risk.residual_score} "
             f"({_severity_of(risk.residual_score, max_score).title()})"
             if risk.residual_score is not None else "Not yet assessed"),
            ("Against appetite", label),
            ("Annual loss exposure",
             f"{risk.annual_loss_expectancy:,.2f}" if risk.annual_loss_expectancy else "—"),
            ("Next review", _d(risk.next_review_date)),
        ]),
    ]
    if risk.description:
        flow += [_h2(ss, "Description"), _body(ss, risk.description)]

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
        ("Cost", f"{risk.treatment_cost:,.2f}" if risk.treatment_cost else "—"),
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
        ("Total annual loss exposure", f"{stats.get('total_exposure', 0):,.2f}"),
        ("Pending risk acceptances", stats.get("pending_acceptances")),
    ])]
    by_status = stats.get("risks_by_status") or {}
    if by_status:
        story += [_h2(ss, "Risks by status"),
                  _table(ss, ["Status", "Count"], [[k.title(), str(v)] for k, v in by_status.items()],
                         col_widths=[200, 80])]
    return _render(story, org_name)
