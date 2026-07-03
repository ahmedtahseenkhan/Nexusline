"""PDF report generation with ReportLab (pure-Python, air-gap friendly).

No headless browser and no external font files — uses the built-in Helvetica family
so it runs in a locked-down on-prem container. ``reportlab`` is imported lazily so
the app boots without it; PDF endpoints then return a clear 501.

Public generators take already-loaded (RLS-scoped) data from the API layer and return
PDF bytes: board packs, audit-committee reports, Shariah-board reports and the risk
register.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from fastapi import HTTPException, status

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


def risk_register_pdf(risks, appetite: int, tolerance: int, org_name: str) -> bytes:
    """Full risk register report (board risk pack)."""
    _require_reportlab()
    from app.services.risk_scoring import severity_for_score

    def sev(score):
        s = severity_for_score(score)
        return s.value if s is not None else ""

    ss = _styles()
    story = _title_block(ss, "Risk Register", f"{len(risks)} risks · appetite ≤ {appetite} · tolerance ≤ {tolerance}", org_name)
    rows = []
    for r in risks:
        rows.append([
            r.reference, r.title, r.category or "—",
            _sev_chip(ss, sev(r.inherent_score)),
            _sev_chip(ss, sev(r.residual_score)),
            r.status.value.replace("_", " ").title(), _d(r.next_review_date),
        ])
    story += [_table(ss, ["Ref", "Risk", "Category", "Inherent", "Residual", "Status", "Review"], rows,
                     col_widths=[48, 150, 70, 55, 55, 62, 62])]
    return _render(story, org_name)


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
