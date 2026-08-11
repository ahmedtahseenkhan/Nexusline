"""Global search — one endpoint that scans the primary registers by name/title.

Returns a flat, ranked list of hits across modules with a deep-link path, powering
the top-bar search box. RLS keeps every query scoped to the caller's tenant, and
each entity is guarded by its module read-permission so results never leak fields a
user could not otherwise see.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import String, cast, literal, or_, select, union_all

from app.core.deps import CurrentUser, DbSession
from app.models.aml import AmlRiskAssessment, ScreeningCase, SuspiciousActivityReport
from app.models.asset import Asset
from app.models.bia import BiaAssessment
from app.models.compliance import Requirement
from app.models.enums import AssetClass
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.data_protection import DataBreach, Dpia, Dsar
from app.models.evidence import Evidence
from app.models.exception import ExceptionRecord
from app.models.fraud import FraudCase, FraudRisk
from app.models.goal import Goal
from app.models.governance import Committee
from app.models.icfr import IcfrDeficiency, IcfrProcess
from app.models.incident import Incident
from app.models.internal_audit import AuditEngagement, AuditFinding, AuditableUnit
from app.models.issue import Issue
from app.models.model_risk import ModelInventory
from app.models.operational_risk import KeyRiskIndicator, LossEvent, RcsaAssessment
from app.models.organization import BusinessUnit, Legal, Process
from app.models.outsourcing import OutsourcingArrangement
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.regulatory_change import Obligation, RegulatoryChange
from app.models.risk import Risk
from app.models.scenario import ScenarioAnalysis
from app.models.shariah import ShariahReview, ShariahRuling
from app.models.threat import Threat, Vulnerability
from app.models.vendor import Vendor
from app.models.vulnerability import VulnFinding
from app.models.whistleblowing import WhistleblowingReport

router = APIRouter(prefix="/search", tags=["search"])


class SearchHit(BaseModel):
    type: str
    label: str
    reference: str
    title: str
    link: str


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]


@dataclass(frozen=True)
class _Target:
    model: type
    type_label: str
    title_attr: str
    link: str
    read_perm: str


# One entry per searchable register. ``title_attr`` is the human name/title column.
_TARGETS: list[_Target] = [
    _Target(Risk, "Risk", "title", "/risks", "risk:read"),
    _Target(Control, "Control", "name", "/controls", "control:read"),
    _Target(Asset, "Asset", "name", "/assets", "asset:read"),
    _Target(Vendor, "Vendor", "name", "/vendors", "vendor:read"),
    _Target(Policy, "Policy", "title", "/policies", "policy:read"),
    _Target(Requirement, "Requirement", "title", "/compliance", "compliance:read"),
    _Target(Incident, "Incident", "title", "/incidents", "incident:read"),
    _Target(ExceptionRecord, "Exception", "title", "/exceptions", "exception:read"),
    _Target(Project, "Project", "title", "/projects", "project:read"),
    _Target(Goal, "Goal", "name", "/goals", "goal:read"),
    _Target(ContinuityPlan, "Continuity Plan", "name", "/continuity", "bcp:read"),
    _Target(ProcessingActivity, "Processing Activity", "name", "/privacy", "privacy:read"),
    _Target(BusinessUnit, "Business Unit", "name", "/business-units", "org:read"),
    _Target(Process, "Process", "name", "/processes", "org:read"),
    _Target(Legal, "Legal", "name", "/legal", "org:read"),
    _Target(Evidence, "Evidence", "title", "/evidence", "control:read"),
    _Target(Threat, "Threat", "name", "/threat-library", "risk:read"),
    _Target(Vulnerability, "Vulnerability", "name", "/threat-library", "risk:read"),
    # --- connective tissue & assurance ---
    _Target(Issue, "Issue", "title", "/issues", "issue:read"),
    _Target(AuditFinding, "Audit Finding", "title", "/internal-audit", "internal_audit:read"),
    _Target(AuditEngagement, "Audit Engagement", "title", "/internal-audit", "internal_audit:read"),
    _Target(AuditableUnit, "Auditable Unit", "name", "/internal-audit", "internal_audit:read"),
    # --- operational risk ---
    _Target(RcsaAssessment, "RCSA", "title", "/operational-risk", "oprisk:read"),
    _Target(KeyRiskIndicator, "KRI", "name", "/operational-risk", "oprisk:read"),
    _Target(LossEvent, "Loss Event", "title", "/operational-risk", "oprisk:read"),
    _Target(ScenarioAnalysis, "Scenario", "title", "/scenario-analysis", "scenario:read"),
    _Target(ModelInventory, "Model", "name", "/model-risk", "modelrisk:read"),
    # --- compliance & regulatory ---
    _Target(RegulatoryChange, "Regulatory Change", "title", "/regulatory-change", "regchange:read"),
    _Target(Obligation, "Obligation", "title", "/regulatory-change", "regchange:read"),
    _Target(IcfrProcess, "ICFR Process", "name", "/icfr", "icfr:read"),
    _Target(IcfrDeficiency, "ICFR Deficiency", "title", "/icfr", "icfr:read"),
    _Target(OutsourcingArrangement, "Outsourcing", "title", "/outsourcing", "outsourcing:read"),
    _Target(Committee, "Committee", "name", "/governance", "governance:read"),
    # --- resilience ---
    _Target(BiaAssessment, "BIA", "process_name", "/bia", "bia:read"),
    _Target(VulnFinding, "Vulnerability Finding", "title", "/vulnerabilities", "vuln:read"),
    # --- privacy ---
    _Target(Dpia, "DPIA", "title", "/data-protection", "dpo:read"),
    _Target(Dsar, "Data Subject Request", "subject_name", "/data-protection", "dpo:read"),
    _Target(DataBreach, "Data Breach", "title", "/data-protection", "dpo:read"),
    # --- financial crime & Islamic banking ---
    _Target(SuspiciousActivityReport, "STR / SAR", "subject", "/aml", "aml:read"),
    _Target(ScreeningCase, "Screening Case", "subject_name", "/aml", "aml:read"),
    _Target(AmlRiskAssessment, "AML Risk Assessment", "title", "/aml", "aml:read"),
    _Target(FraudRisk, "Fraud Risk", "title", "/fraud", "fraud:read"),
    _Target(FraudCase, "Fraud Case", "title", "/fraud", "fraud:read"),
    _Target(WhistleblowingReport, "Whistleblowing Report", "title", "/whistleblowing", "whistle:read"),
    _Target(ShariahRuling, "Shariah Ruling", "title", "/shariah", "shariah:read"),
    _Target(ShariahReview, "Shariah Review", "title", "/shariah", "shariah:read"),
]


@router.get("", response_model=SearchResults)
async def global_search(q: str, db: DbSession, user: CurrentUser, limit: int = 8) -> SearchResults:
    term = q.strip()
    if len(term) < 2:
        return SearchResults(query=q, hits=[])

    perms = set(user.permission_codes)
    like = f"%{term}%"
    per_type = max(1, min(limit, 15))

    # One UNION ALL over every permitted register instead of a query per register.
    # With ~45 targets the round trips, not the scans, dominated the response time;
    # this keeps a full-catalogue search to a single statement. Each branch projects
    # the same four text columns so the union types line up across models.
    branches = []
    for idx, tgt in enumerate(_TARGETS):
        if tgt.read_perm not in perms:
            continue
        model = tgt.model
        title_col = getattr(model, tgt.title_attr)
        conditions = [title_col.ilike(like)]
        if hasattr(model, "reference"):
            conditions.append(model.reference.ilike(like))
        if hasattr(model, "description"):
            conditions.append(model.description.ilike(like))

        reference_col = (
            cast(model.reference, String) if hasattr(model, "reference") else literal("").cast(String)
        )
        # Assets carry their class so the hit can deep-link to the right register.
        extra_col = (
            cast(model.asset_class, String) if model is Asset else literal("").cast(String)
        )

        stmt = select(
            cast(model.id, String).label("id"),
            reference_col.label("reference"),
            cast(title_col, String).label("title"),
            literal(idx).label("target"),
            extra_col.label("extra"),
        ).where(or_(*conditions))
        if hasattr(model, "deleted"):
            stmt = stmt.where(model.deleted.is_(False))
        branches.append(stmt.limit(per_type))

    if not branches:
        return SearchResults(query=q, hits=[])

    rows = (await db.execute(branches[0] if len(branches) == 1 else union_all(*branches))).all()

    hits: list[SearchHit] = []
    for row in rows:
        tgt = _TARGETS[row.target]
        reference = row.reference or ""
        # Deep-link straight to the record so search/⌘K opens its drawer, not just
        # the module. Assets split by class into the IT vs Information register.
        base = tgt.link
        if tgt.model is Asset:
            base = "/it-assets" if row.extra == AssetClass.it_asset.value else "/information-assets"
        hits.append(
            SearchHit(
                type=tgt.type_label,
                label=f"{tgt.type_label} · {reference}" if reference else tgt.type_label,
                reference=reference,
                title=row.title or "",
                link=f"{base}?id={row.id}",
            )
        )

    # Prioritize exact/prefix matches on the title, then reference matches.
    lowered = term.lower()

    def rank(h: SearchHit) -> tuple[int, int]:
        t = h.title.lower()
        primary = 0 if t == lowered else 1 if t.startswith(lowered) else 2 if lowered in t else 3
        return (primary, len(h.title))

    hits.sort(key=rank)
    return SearchResults(query=q, hits=hits[: limit * 3])
