"""First-run seeding: bootstrap org/admin plus a few sample GRC records.

The demo org gets two people so segregation of duties is visible rather than switched
off: the seeded admin (checker, who also holds the Risk Approver and Compliance Manager
roles the default approval routes are assigned to) and a risk manager, Ayesha Siddiqui
(maker). Ayesha
entered the sample controls and policies, owns the sample risks and raised APR-002, so
the admin can legitimately test, publish and approve them; APR-001 was raised by the
admin, who therefore sees it as their own and cannot decide it.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import tenant_session
from app.db.provisioning import create_organization
from app.models.assessment import (
    Assessment,
    AssessmentAnswer,
    AssessmentFinding,
    Question,
    QuestionOption,
    Questionnaire,
)
from app.models.access_review import AccessReview, AccessReviewItem
from app.models.approval import ApprovalRequest
from app.models.asset import (
    Asset,
    AssetClassification,
    AssetClassificationType,
    AssetLabel,
    AssetMediaType,
    AssetReview,
)
from app.models.awareness import (
    AwarenessOption,
    AwarenessProgram,
    AwarenessQuestion,
    TrainingRecord,
)
from app.models.compliance import Requirement, requirement_crosswalks
from app.models.continuity import ContinuityPlan, ContinuityTask, ContinuityTest
from app.models.control import Control, ControlAudit, ControlMaintenance
from app.models.enums import (
    AssessmentStatus,
    AssetReviewStatus,
    WorkflowStatus,
    ComplianceStatus,
    ControlEffectiveness,
    ControlStatus,
    Criticality,
    EvidenceStatus,
    EvidenceType,
    IncidentStatus,
    PolicyStatus,
    ReviewFrequency,
    RiskStatus,
    Severity,
    TestResult,
    TreatmentStrategy,
    VendorAssessmentStatus,
    VendorStatus,
)
from app.models.enums import ExceptionStatus, ExceptionType
from app.models.evidence import Evidence
from app.models.exception import ExceptionRecord
from app.models.incident import Incident
from app.models.goal import Goal, GoalAudit
from app.models.organization import BusinessUnit, Legal, Process
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project, ProjectExpense, ProjectTask
from app.models.risk import Risk
from app.models.threat import Threat, Vulnerability
from app.models.vendor import Vendor
from app.models.audit import AuditLog
from app.models.base import WorkflowState
from app.models.identity import Role, User
from app.models.tenant import Tenant
from app.services.risk_scoring import next_review_date

#: The demo maker. Email is built on the seed admin's domain; password is the seed
#: admin's (a dev default — the demo seed must never run for a client, SEED_DATA=false).
DEMO_MAKER_NAME = "Ayesha Siddiqui"
DEMO_MAKER_ROLE = "Risk Manager"


def demo_maker_email(admin_email: str) -> str:
    domain = admin_email.rsplit("@", 1)[-1] if "@" in admin_email else "example.com"
    return f"ayesha.siddiqui@{domain}"


async def _seed_demo_maker(db: AsyncSession, tenant_id) -> User:
    """The second demo user (risk manager, the maker). Idempotent by e-mail."""
    from app.core.security import hash_password

    email = demo_maker_email(settings.seed_admin_email)
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        return existing
    role = await db.scalar(select(Role).where(Role.name == DEMO_MAKER_ROLE))
    user = User(
        tenant_id=tenant_id,
        email=email,
        full_name=DEMO_MAKER_NAME,
        hashed_password=hash_password(settings.seed_admin_password),
        roles=[role] if role is not None else [],
    )
    db.add(user)
    await db.flush()
    return user


def _created_by(tenant_id, maker: User, entity_type: str, entity_id, label: str) -> AuditLog:
    """The ``create`` trail entry a record would have had if the maker had typed it in.

    Four-eyes resolves the maker of a record from this entry (``dual_control.maker_of``);
    without it every seeded record has no maker and the check silently never fires."""
    return AuditLog(
        tenant_id=tenant_id,
        actor_id=maker.id,
        actor_email=maker.email,
        action="create",
        entity_type=entity_type,
        entity_id=entity_id,
        summary=f"Created {entity_type} {label} (demo data)",
        changes={"source": "demo_seed"},
    )


#: Default approval routes now live in ``services/default_governance.py`` and are created
#: — enabled — for every organisation by ``create_organization``. Kept here as
#: (entity_type, name, description, stages) for callers that read the old shape; each
#: stage is (name, approver_mode, approver_ref).
from app.services.default_governance import DEFAULT_ROUTES as _DEFAULT_ROUTES  # noqa: E402

DEFAULT_WORKFLOWS: tuple[tuple[str, str, str, tuple[tuple[str, str, str], ...]], ...] = tuple(
    (r.entity_type, r.name, r.description, tuple((s.name, s.approver_mode, s.approver_ref) for s in r.stages))
    for r in _DEFAULT_ROUTES
)


async def seed_default_workflows(db: AsyncSession, tenant_id) -> int:
    """Add the default routes (enabled) a tenant has none for, and upgrade the untouched
    disabled routes older demo seeds created. Idempotent; never overwrites."""
    from app.services.default_governance import ensure_default_routes

    added, upgraded = await ensure_default_routes(db, tenant_id)
    return len(added) + len(upgraded)


#: Default KPI tiles, (metric_key, viz). Titles come from the metric catalogue.
DEFAULT_WIDGETS: tuple[tuple[str, str], ...] = (
    ("risks_total", "number"),
    ("risks_above_tolerance", "number"),
    ("incidents_open", "number"),
    ("approvals_pending", "number"),
    ("risks_by_severity", "bar"),
    ("compliance_by_status", "donut"),
    ("controls_by_status", "bar"),
)


async def seed_default_widgets(db: AsyncSession, tenant_id) -> int:
    """Add the default dashboard tiles whose metric the tenant has no tile for yet.
    Idempotent, and never collides with the (tenant, metric_key, viz) unique index."""
    from app.models.widget import DashboardWidget
    from app.services.metrics import CATALOG

    have = set((await db.scalars(select(DashboardWidget.metric_key))).all())
    order = (await db.scalar(select(func.max(DashboardWidget.order_index)))) or 0
    added = 0
    for key, viz in DEFAULT_WIDGETS:
        if key in have:
            continue
        order += 1
        title = CATALOG[key][0] if key in CATALOG else key.replace("_", " ").capitalize()
        db.add(DashboardWidget(tenant_id=tenant_id, title=title, metric_key=key, viz=viz, order_index=order))
        have.add(key)
        added += 1
    await db.flush()
    return added


#: Roles the demo admin also holds, so the one login a demo uses can decide every stage of
#: the default approval routes (services/default_governance.py) that Ayesha submits.
DEMO_CHECKER_ROLES: tuple[str, ...] = ("Risk Approver", "Compliance Manager")


async def _grant_demo_checker_roles(db: AsyncSession, admin: User) -> None:
    """Give the demo admin the route approver roles. Idempotent."""
    have = {r.name for r in admin.roles}
    wanted = [n for n in DEMO_CHECKER_ROLES if n not in have]
    if not wanted:
        return
    roles = (await db.scalars(select(Role).where(Role.name.in_(wanted)))).all()
    admin.roles = [*admin.roles, *roles]
    await db.flush()


async def _seed_sample_data(db: AsyncSession, tenant_id, admin: User) -> None:
    today = date.today()
    maker = await _seed_demo_maker(db, tenant_id)
    await _grant_demo_checker_roles(db, admin)

    # Baseline lookups (media types, vendor types, labels) were already inserted by
    # create_organization -> ensure_reference_data; index them by name for the sample
    # records below.
    media_types: dict[str, AssetMediaType] = {
        m.name: m for m in (await db.scalars(select(AssetMediaType))).all()
    }

    # CIA classification scheme — seeded by ensure_reference_data; index "Axis:Value".
    classif: dict[str, AssetClassification] = {}
    for ct in (await db.scalars(select(AssetClassificationType))).all():
        for c in ct.classifications:
            classif[f"{ct.name}:{c.name}"] = c

    # Handling / data-classification labels — seeded by ensure_reference_data.
    labels: dict[str, AssetLabel] = {
        l.name: l for l in (await db.scalars(select(AssetLabel))).all()
    }

    C = Criticality
    db_objs: dict[str, Asset] = {}
    # Each CIA axis grades on its own scale (reference_data.py). A key that does not
    # resolve — a tenant that renamed a value, or a scheme mid-migration — is skipped
    # rather than crashing the seed.
    for name, mtype, crit, conf, integ, avail, lbl, cls_keys in [
        ("Customer Database", "Data Asset", C.critical, C.critical, C.high, C.high, "Restricted",
         ["Confidentiality:Restricted", "Integrity:High", "Availability:Business-critical"]),
        ("Payroll System", "Software", C.high, C.high, C.high, C.medium, "Confidential",
         ["Confidentiality:Confidential", "Integrity:High"]),
        ("Corporate Network", "Network", C.medium, C.medium, C.medium, C.high, "Internal",
         ["Availability:Business-critical"]),
    ]:
        a = Asset(
            tenant_id=tenant_id,
            name=name,
            description=f"{name} — core asset in the security program.",
            media_type_id=media_types[mtype].id,
            criticality=crit,
            confidentiality=conf,
            integrity=integ,
            availability=avail,
            label_id=labels[lbl].id if lbl in labels else None,
            review_frequency=ReviewFrequency.annual,
            next_review_date=next_review_date(ReviewFrequency.annual, today),
            workflow_status=WorkflowStatus.approved,
        )
        # assign the M2M while the object is still pending (no IO) to avoid lazy-load
        a.classifications = [classif[k] for k in cls_keys if k in classif]
        db.add(a)
        db_objs[name] = a
    await db.flush()

    from app.models.enums import ControlType

    ctrls: dict[str, Control] = {}
    for name, ref, status, eff, objective, owner, opex, capex, util in [
        ("Access Control Policy", "A.5.15", ControlStatus.operational, ControlEffectiveness.effective,
         "Ensure least-privilege access to systems and data.", "IT Security", 12000, 0, 15),
        ("Encryption at Rest", "A.8.24", ControlStatus.operational, ControlEffectiveness.partially_effective,
         "Protect stored data confidentiality via encryption.", "Infrastructure", 8000, 20000, 10),
        ("Backup & Recovery", "A.8.13", ControlStatus.implemented, ControlEffectiveness.effective,
         "Ensure data can be restored after a disruptive event.", "Infrastructure", 15000, 30000, 20),
    ]:
        c = Control(
            tenant_id=tenant_id,
            name=name,
            reference=ref,
            objective=objective,
            owner=owner,
            control_type=ControlType.production,
            classification="Technical",
            status=status,
            effectiveness=eff,
            workflow_status=WorkflowState.approved,
            opex=opex, capex=capex, resource_utilization=util,
            audit_frequency=ReviewFrequency.annual,
            audit_metric="Sample of access grants reviewed against policy.",
            audit_success_criteria="100% of sampled grants comply with least-privilege.",
            maintenance_frequency=ReviewFrequency.quarterly,
            next_audit_date=next_review_date(ReviewFrequency.annual, today),
            next_maintenance_date=next_review_date(ReviewFrequency.quarterly, today),
        )
        db.add(c)
        ctrls[name] = c
    await db.flush()
    # Ayesha entered the controls, so the admin may test them and she may not.
    db.add_all(
        [_created_by(tenant_id, maker, "control", c.id, f"{c.reference} {c.name}") for c in ctrls.values()]
    )

    # A completed audit + maintenance on the access-control policy
    acp = ctrls["Access Control Policy"]
    acp.last_audit_date = today
    db.add_all(
        [
            ControlAudit(
                tenant_id=tenant_id,
                control_id=acp.id,
                result=TestResult.passed,
                conducted_date=today,
                result_description="Annual access review passed with no findings.",
                auditor="Internal Audit",
            ),
            ControlMaintenance(
                tenant_id=tenant_id,
                control_id=ctrls["Encryption at Rest"].id,
                task="Rotate KMS keys",
                result=TestResult.passed,
                conducted_date=today,
                conclusion="Keys rotated successfully.",
            ),
        ]
    )
    await db.flush()

    # --- Threat & Vulnerability catalogs ---
    threats: dict[str, Threat] = {}
    for tname, tcat in [
        ("Phishing", "Social Engineering"),
        ("Ransomware", "Malware"),
        ("Malware", "Malware"),
        ("Insider threat", "People"),
        ("Denial of service", "Availability"),
        ("Unauthorized access", "Access"),
        ("Data leakage", "Data"),
        ("Supply chain compromise", "Third Party"),
        ("Physical theft", "Physical"),
        ("Credential stuffing", "Access"),
        ("SQL injection", "Application"),
        ("Cross-site scripting", "Application"),
        ("Man-in-the-middle", "Network"),
        ("Privilege escalation", "Access"),
        ("Zero-day exploit", "Technical"),
        ("Social engineering", "Social Engineering"),
        ("Data destruction", "Data"),
        ("Natural disaster", "Environmental"),
        ("Power failure", "Environmental"),
        ("Hardware failure", "Technical"),
        ("Eavesdropping", "Network"),
        ("Session hijacking", "Access"),
        ("API abuse", "Application"),
        ("Cloud misconfiguration", "Third Party"),
        ("Espionage", "People"),
    ]:
        t = Threat(tenant_id=tenant_id, name=tname, category=tcat)
        db.add(t)
        threats[tname] = t

    vulns: dict[str, Vulnerability] = {}
    for vname, vcat in [
        ("Unpatched software", "Technical"),
        ("Weak passwords", "Access"),
        ("Misconfiguration", "Technical"),
        ("Missing MFA", "Access"),
        ("Lack of encryption", "Data"),
        ("Excessive privileges", "Access"),
        ("No offline backups", "Resilience"),
        ("Untrained staff", "People"),
        ("Legacy systems", "Technical"),
        ("Exposed network ports", "Network"),
        ("No input validation", "Application"),
        ("Default credentials", "Access"),
        ("Unencrypted backups", "Data"),
        ("No network segmentation", "Network"),
        ("Missing security patches", "Technical"),
        ("Weak access reviews", "Access"),
        ("No DLP controls", "Data"),
        ("Single points of failure", "Resilience"),
        ("Shadow IT", "Governance"),
        ("Unrestricted outbound traffic", "Network"),
        ("No logging/monitoring", "Detection"),
        ("Hard-coded secrets", "Application"),
    ]:
        v = Vulnerability(tenant_id=tenant_id, name=vname, category=vcat)
        db.add(v)
        vulns[vname] = v
    await db.flush()

    risks = [
        Risk(
            tenant_id=tenant_id,
            reference="R-001",
            title="Unauthorized access to customer data",
            description="Threat actor gains access to the customer database.",
            category="Information Security",
            status=RiskStatus.treatment_in_progress,
            inherent_likelihood=4,
            inherent_impact=5,
            residual_likelihood=2,
            residual_impact=3,
            annual_loss_frequency=0.5,
            single_loss_expectancy=200000,
            treatment_strategy=TreatmentStrategy.mitigate,
            treatment_description="Enforce least-privilege access and encrypt data at rest.",
            treatment_owner="CISO",
            treatment_deadline=next_review_date(ReviewFrequency.quarterly, today),
            treatment_cost=45000,
            workflow_status=WorkflowState.approved,
            review_frequency=ReviewFrequency.quarterly,
            last_review_date=today,
            next_review_date=next_review_date(ReviewFrequency.quarterly, today),
            assets=[db_objs["Customer Database"]],
            controls=[ctrls["Access Control Policy"], ctrls["Encryption at Rest"]],
            threats=[threats["Unauthorized access"], threats["Phishing"]],
            vulnerabilities=[vulns["Weak passwords"], vulns["Missing MFA"]],
        ),
        Risk(
            tenant_id=tenant_id,
            reference="R-002",
            title="Ransomware encrypts production systems",
            description="Malware encrypts critical systems, disrupting operations.",
            category="Business Continuity",
            status=RiskStatus.assessed,
            inherent_likelihood=4,
            inherent_impact=5,
            annual_loss_frequency=0.2,
            single_loss_expectancy=500000,
            treatment_strategy=TreatmentStrategy.mitigate,
            review_frequency=ReviewFrequency.annual,
            next_review_date=next_review_date(ReviewFrequency.annual, today),
            assets=[db_objs["Corporate Network"]],
            controls=[ctrls["Backup & Recovery"]],
            threats=[threats["Ransomware"], threats["Phishing"]],
            vulnerabilities=[vulns["No offline backups"], vulns["Unpatched software"]],
        ),
        Risk(
            tenant_id=tenant_id,
            reference="R-003",
            title="Payroll data exposed by insider",
            description="Privileged insider exfiltrates payroll records.",
            category="Information Security",
            status=RiskStatus.treatment_planned,
            inherent_likelihood=3,
            inherent_impact=4,
            residual_likelihood=2,
            residual_impact=2,
            treatment_strategy=TreatmentStrategy.mitigate,
            review_frequency=ReviewFrequency.semiannual,
            next_review_date=next_review_date(ReviewFrequency.semiannual, today),
            assets=[db_objs["Payroll System"]],
            controls=[ctrls["Access Control Policy"]],
            threats=[threats["Insider threat"]],
            vulnerabilities=[vulns["Excessive privileges"]],
        ),
    ]
    # Ayesha, the risk manager, owns the register's sample risks.
    for r in risks:
        r.owner_id = maker.id
    db.add_all(risks)
    await db.flush()

    # --- Compliance: the full library ISO 27001:2022 (clauses + 93 Annex A controls) ---
    # Installed through the same path as the Content Library, so the demo never carries
    # a shallow copy whose name blocks the real one. The controls pack links the three
    # sample controls above by reference (A.5.15, A.8.24, A.8.13) instead of duplicating
    # them; the remaining Annex A controls arrive as planned / not assessed.
    from app.services import framework_library

    iso = (await framework_library.install_template(db, admin, "iso-27001-2022")).framework
    iso_reqs = await _requirements_by_ref(db, iso.id)

    C = ComplianceStatus
    for ref, st, mapped in [
        ("A.5.15", C.compliant, [ctrls["Access Control Policy"]]),
        ("A.8.24", C.partially_compliant, [ctrls["Encryption at Rest"]]),
        ("A.8.13", C.compliant, [ctrls["Backup & Recovery"]]),
        ("A.5.7", C.not_assessed, []),
        ("A.8.16", C.non_compliant, []),
    ]:
        req = iso_reqs.get(ref)
        if req is None:
            continue
        req.status = st
        for ctrl in mapped:
            if ctrl not in req.controls:
                req.controls.append(ctrl)
    await db.flush()

    # Second framework (SOC 2, also from the library) reusing the same control, then
    # crosswalk the equivalents: ISO A.5.15 ≡ SOC 2 CC6.1.
    soc2 = (await framework_library.install_template(db, admin, "soc-2-2017")).framework
    cc61 = (await _requirements_by_ref(db, soc2.id)).get("CC6.1")
    if cc61 is not None:
        cc61.status = C.compliant
        if ctrls["Access Control Policy"] not in cc61.controls:
            cc61.controls.append(ctrls["Access Control Policy"])
        await db.flush()
        if "A.5.15" in iso_reqs:
            await db.execute(
                requirement_crosswalks.insert().values(
                    requirement_id=iso_reqs["A.5.15"].id, related_requirement_id=cc61.id
                )
            )

    # Evidence attached to controls (demonstrates every requirement those controls map to).
    db.add_all(
        [
            Evidence(
                tenant_id=tenant_id,
                control_id=ctrls["Access Control Policy"].id,
                title="Quarterly IAM access review",
                evidence_type=EvidenceType.document,
                status=EvidenceStatus.valid,
                reference="https://drive.example/iam-review-q2",
                collected_at=today,
            ),
            Evidence(
                tenant_id=tenant_id,
                control_id=ctrls["Encryption at Rest"].id,
                title="KMS encryption configuration",
                evidence_type=EvidenceType.screenshot,
                status=EvidenceStatus.valid,
                reference="https://drive.example/kms.png",
                collected_at=today,
            ),
        ]
    )
    await db.flush()

    # --- Incidents (with response-stage lifecycle) ---
    from app.models.enums import StageStatus
    from app.models.incident import DEFAULT_STAGES, IncidentStage

    def _stages(done_through: int):
        return [
            IncidentStage(
                tenant_id=tenant_id,
                name=name,
                order_index=i,
                status=StageStatus.done if i < done_through else StageStatus.pending,
                completed_at=today if i < done_through else None,
            )
            for i, name in enumerate(DEFAULT_STAGES)
        ]

    # Incident timelines are timestamps (phase 2); demo times are Asia/Karachi wall clock,
    # the default organisation timezone. INC-001 is owed to SBP, so it carries the
    # regulator's clock (initial report due 24h after detection, final in 30 days).
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from app.core.config import settings as app_settings
    from app.models.enums import RegulatoryReportStatus, RegulatoryReportType
    from app.models.incident import RegulatoryReport
    from app.services.incident_clock import planned_deadlines

    pkt = ZoneInfo("Asia/Karachi")

    def _at(days_ago: int, hh: int, mm: int = 0) -> datetime:
        return datetime.combine(today - timedelta(days=days_ago), time(hh, mm), tzinfo=pkt)

    inc1 = Incident(
        tenant_id=tenant_id,
        reference="INC-001",
        title="Phishing campaign targeting finance team",
        category="Phishing",
        severity=Severity.high,
        status=IncidentStatus.contained,
        assignee="SOC Team",
        occurred_at=_at(1, 8, 40),
        detected_at=_at(1, 9, 15),
        contained_at=_at(1, 13, 30),
        customers_affected=0,
        records_affected=0,
        is_reportable=True,
        regulator=app_settings.default_regulator,
    )
    inc1.stages = _stages(2)  # Identification + Containment done; on Eradication
    due = planned_deadlines(
        inc1.detected_at, app_settings.regulatory_initial_report_hours,
        app_settings.regulatory_final_report_days,
    )
    inc1.regulatory_reports = [
        RegulatoryReport(
            tenant_id=tenant_id, regulator=app_settings.default_regulator,
            report_type=RegulatoryReportType.initial_notification,
            deadline=due[RegulatoryReportType.initial_notification],
            status=RegulatoryReportStatus.submitted, submitted_at=_at(1, 18, 5),
            reference="SBP-ACK-0001", submitted_by="CISO",
        ),
        RegulatoryReport(
            tenant_id=tenant_id, regulator=app_settings.default_regulator,
            report_type=RegulatoryReportType.final_report,
            deadline=due[RegulatoryReportType.final_report],
            status=RegulatoryReportStatus.pending,
        ),
    ]
    inc2 = Incident(
        tenant_id=tenant_id,
        reference="INC-002",
        title="Brief DDoS against public website",
        category="Availability",
        severity=Severity.medium,
        status=IncidentStatus.resolved,
        assignee="Network Team",
        occurred_at=_at(3, 22, 10),
        detected_at=_at(3, 22, 25),
        contained_at=_at(3, 23, 5),
        resolved_at=_at(2, 2, 0),
        customers_affected=1200,
    )
    inc2.stages = _stages(5)  # all done -> lifecycle complete
    inc3 = Incident(
        tenant_id=tenant_id,
        reference="INC-003",
        title="Wire transfer to a spoofed vendor account stopped at call-back",
        category="Fraud",
        severity=Severity.low,
        status=IncidentStatus.closed,
        assignee="Operations",
        near_miss=True,
        occurred_at=_at(6, 11, 0),
        detected_at=_at(6, 11, 20),
        contained_at=_at(6, 11, 20),
        resolved_at=_at(5, 16, 0),
    )
    inc3.stages = _stages(5)
    db.add_all([inc1, inc2, inc3])

    # --- Policies ---
    db.add_all(
        [
            Policy(
                tenant_id=tenant_id,
                reference="POL-001",
                title="Information Security Policy",
                category="Security",
                version="2.1",
                status=PolicyStatus.published,
                owner="CISO",
                review_frequency=ReviewFrequency.annual,
                next_review_date=next_review_date(ReviewFrequency.annual, today),
                published_at=today,
            ),
            Policy(
                tenant_id=tenant_id,
                reference="POL-002",
                title="Acceptable Use Policy",
                category="HR",
                version="1.0",
                status=PolicyStatus.under_review,
                owner="IT",
                review_frequency=ReviewFrequency.annual,
                next_review_date=next_review_date(ReviewFrequency.annual, today),
            ),
        ]
    )

    await db.flush()
    # Ayesha drafted the policies, so the admin may publish them and she may not.
    db.add_all(
        [
            _created_by(tenant_id, maker, "policy", p.id, f"{p.reference} {p.title}")
            for p in (await db.scalars(select(Policy))).all()
        ]
    )

    # --- Vendors / third parties (types come from ensure_reference_data) ---
    from app.models.vendor import ServiceContract, VendorType

    vendor_types = {v.name: v for v in (await db.scalars(select(VendorType))).all()}
    vt_cloud = vendor_types["Cloud Provider"]
    vt_proc = vendor_types["Data Processor"]

    aws = Vendor(
        tenant_id=tenant_id,
        name="Amazon Web Services",
        category="Cloud Infrastructure",
        type_id=vt_cloud.id,
        contact_name="AWS Security Team",
        contact_email="security@aws.example",
        contact_phone="+1-206-555-0100",
        website="https://aws.amazon.com",
        location="Seattle, US",
        criticality=Criticality.critical,
        status=VendorStatus.active,
        workflow_status=WorkflowState.approved,
        risk_rating=Severity.medium,
        shares_data=True,
        assessment_status=AssessmentStatus.completed,
        last_assessed_at=today,
        onboarded_at=date(2023, 1, 10),
        review_frequency=ReviewFrequency.annual,
        next_review_date=next_review_date(ReviewFrequency.annual, today),
    )
    # link AWS to the risk + assets it touches, and a contract (assign while pending)
    aws.risks = [risks[1]]
    aws.assets = [db_objs["Customer Database"], db_objs["Corporate Network"]]
    aws.contracts = [
        ServiceContract(tenant_id=tenant_id, name="AWS Enterprise Agreement", value=240000,
                        start_date=date(2023, 1, 10), end_date=date(2026, 1, 9),
                        description="Cloud infrastructure + enterprise support."),
    ]
    db.add_all(
        [
            aws,
            Vendor(
                tenant_id=tenant_id,
                name="Mailchimp",
                category="Email Marketing",
                type_id=vt_proc.id,
                contact_email="privacy@mailchimp.example",
                contact_name="Mailchimp DPO",
                criticality=Criticality.medium,
                status=VendorStatus.active,
                workflow_status=WorkflowState.approved,
                risk_rating=Severity.low,
                shares_data=True,
                assessment_status=AssessmentStatus.in_progress,
                onboarded_at=date(2024, 6, 1),
                review_frequency=ReviewFrequency.annual,
                next_review_date=next_review_date(ReviewFrequency.annual, today),
            ),
        ]
    )
    await db.flush()

    # --- Vendor assessment questionnaire + an assessment for AWS ---
    import secrets as _secrets

    qn = Questionnaire(
        tenant_id=tenant_id,
        name="Security Baseline Assessment",
        description="Baseline third-party security questionnaire.",
    )

    def _q(text, order):
        q = Question(tenant_id=tenant_id, text=text, order_index=order)
        q.options = [
            QuestionOption(tenant_id=tenant_id, label="Yes", score=10, order_index=0),
            QuestionOption(tenant_id=tenant_id, label="Partial", score=5, order_index=1),
            QuestionOption(tenant_id=tenant_id, label="No", score=0, order_index=2),
        ]
        return q

    qn.questions = [
        _q("Do you hold a current ISO 27001 or SOC 2 certification?", 0),
        _q("Is data encrypted in transit and at rest?", 1),
        _q("Do you enforce multi-factor authentication for all staff?", 2),
        _q("Do you run regular penetration tests?", 3),
    ]
    db.add(qn)
    await db.flush()

    assessment = Assessment(
        tenant_id=tenant_id,
        title="AWS annual security review",
        vendor_id=aws.id,
        questionnaire_id=qn.id,
        status=VendorAssessmentStatus.submitted,
        access_hash=_secrets.token_urlsafe(24),
        submitted_at=today,
        due_date=next_review_date(ReviewFrequency.annual, today),
    )
    db.add(assessment)
    await db.flush()
    # Answer: Yes, Yes, Yes, Partial  -> 35/40 = 87.5%
    chosen = [0, 0, 0, 1]  # option index per question
    for q, idx in zip(qn.questions, chosen):
        db.add(
            AssessmentAnswer(
                tenant_id=tenant_id,
                assessment_id=assessment.id,
                question_id=q.id,
                option_id=q.options[idx].id,
            )
        )
    db.add(
        AssessmentFinding(
            tenant_id=tenant_id,
            assessment_id=assessment.id,
            title="No regular penetration testing",
            description="Vendor only performs annual pen tests; quarterly recommended.",
            severity=Severity.medium,
        )
    )
    await db.flush()

    # --- Business Organization ---
    it = BusinessUnit(tenant_id=tenant_id, name="IT", description="Information Technology", manager="CIO",
                      email="it@acme.com", location="HQ — Floor 3", workflow_status=WorkflowState.approved)
    hr = BusinessUnit(tenant_id=tenant_id, name="Human Resources", manager="CHRO",
                      email="hr@acme.com", location="HQ — Floor 2", workflow_status=WorkflowState.approved)
    fin = BusinessUnit(tenant_id=tenant_id, name="Finance", manager="CFO",
                       email="finance@acme.com", location="HQ — Floor 4", workflow_status=WorkflowState.approved)
    db.add_all([it, hr, fin])
    await db.flush()
    # RACI ownership (scalar FKs — safe to set post-flush) + review history
    cdb = db_objs["Customer Database"]
    cdb.owner_id, cdb.guardian_id, cdb.user_id = it.id, it.id, fin.id
    cdb.last_review_date = date(2025, 12, 1)
    pay = db_objs["Payroll System"]
    pay.owner_id, pay.guardian_id = hr.id, it.id
    net = db_objs["Corporate Network"]
    net.owner_id, net.guardian_id = it.id, it.id
    db.add_all(
        [
            AssetReview(tenant_id=tenant_id, asset_id=cdb.id, reviewer="Data Protection Officer",
                        scheduled_date=date(2025, 12, 1), actual_date=date(2025, 12, 1),
                        status=AssetReviewStatus.completed, outcome="passed",
                        comments="Annual CIA review — no change to classification."),
            AssetReview(tenant_id=tenant_id, asset_id=cdb.id, reviewer="Data Protection Officer",
                        scheduled_date=next_review_date(ReviewFrequency.annual, today),
                        status=AssetReviewStatus.scheduled),
            AssetReview(tenant_id=tenant_id, asset_id=pay.id, reviewer="HR Manager",
                        scheduled_date=next_review_date(ReviewFrequency.annual, today),
                        status=AssetReviewStatus.scheduled),
        ]
    )
    db.add_all(
        [
            Process(
                tenant_id=tenant_id,
                name="Payroll",
                business_unit_id=hr.id,
                owner="Payroll Manager",
                criticality=Criticality.high,
                rto_hours=24, rpo_hours=4, rpd_hours=48,
                workflow_status=WorkflowState.approved,
            ),
            Process(
                tenant_id=tenant_id,
                name="Customer Billing",
                business_unit_id=fin.id,
                owner="Billing Lead",
                criticality=Criticality.critical,
                rto_hours=4, rpo_hours=1, rpd_hours=8,
                workflow_status=WorkflowState.approved,
            ),
            Process(
                tenant_id=tenant_id,
                name="IT Service Desk",
                business_unit_id=it.id,
                owner="Service Desk Manager",
                criticality=Criticality.medium,
                rto_hours=8, rpo_hours=8, rpd_hours=24,
                workflow_status=WorkflowState.approved,
            ),
        ]
    )
    gdpr = Legal(
        tenant_id=tenant_id, name="GDPR", category="Privacy", jurisdiction="EU",
        reference="Regulation (EU) 2016/679", countries="DE,FR,IE,NL",
        risk_magnifier=1.5, workflow_status=WorkflowState.approved,
        description="EU General Data Protection Regulation.",
    )
    pci = Legal(
        tenant_id=tenant_id, name="PCI-DSS", category="Payments", jurisdiction="Global",
        reference="PCI-DSS v4.0", countries="US,GB,DE",
        risk_magnifier=1.2, workflow_status=WorkflowState.approved,
        description="Payment Card Industry Data Security Standard.",
    )
    # Which units are subject to which obligations (assign while pending — no lazy load)
    gdpr.business_units = [it, hr, fin]
    pci.business_units = [fin]
    db.add_all([gdpr, pci])
    await db.flush()

    # --- Exception (time-boxed acceptance of a risk) ---
    exc = ExceptionRecord(
        tenant_id=tenant_id,
        reference="EXC-001",
        title="Accept ransomware risk pending backup overhaul",
        description="Residual exposure accepted while the immutable-backup project completes.",
        exception_type=ExceptionType.risk,
        rationale="Mitigation project R-002 underway; interim acceptance approved by CISO.",
        status=ExceptionStatus.approved,
        start_date=today,
        expires_at=next_review_date(ReviewFrequency.semiannual, today),
        decided_at=today,
        risks=[risks[1]],
    )
    db.add(exc)
    await db.flush()

    # --- Project (remediation) with tasks, expenses and links ---
    from app.models.enums import ProjectStatus

    proj = Project(
        tenant_id=tenant_id,
        reference="PRJ-001",
        title="Immutable backup rollout",
        description="Deploy immutable, offsite backups to mitigate ransomware risk R-002.",
        status=ProjectStatus.ongoing,
        owner="Infrastructure Team",
        start_date=today,
        deadline=next_review_date(ReviewFrequency.quarterly, today),
        budget=120000,
        risks=[risks[1]],
        controls=[ctrls["Backup & Recovery"]],
    )
    proj.tasks = [
        ProjectTask(tenant_id=tenant_id, title="Select backup vendor", completion=100, order_index=1),
        ProjectTask(tenant_id=tenant_id, title="Pilot in staging", completion=60, order_index=2, due_date=today),
        ProjectTask(tenant_id=tenant_id, title="Production rollout", completion=0, order_index=3),
    ]
    proj.expenses = [
        ProjectExpense(tenant_id=tenant_id, amount=45000, description="Vendor licensing", expense_date=today),
        ProjectExpense(tenant_id=tenant_id, amount=12000, description="Implementation services", expense_date=today),
    ]
    db.add(proj)
    await db.flush()

    # --- Strategy & Goals ---
    from app.models.enums import GoalAuditResult, GoalStatus

    g1 = Goal(
        tenant_id=tenant_id,
        reference="GOAL-001",
        name="Achieve ISO 27001 certification",
        description="Reach certified status against ISO/IEC 27001:2022.",
        owner="CISO",
        status=GoalStatus.on_track,
        audit_metric="External audit certificate issued",
        success_criteria="Stage 2 audit passed with no major nonconformities",
        audit_frequency=ReviewFrequency.annual,
        last_audit_date=today,
        next_audit_date=next_review_date(ReviewFrequency.annual, today),
        risks=[risks[0]],
        projects=[proj],
    )
    g1.audits = [
        GoalAudit(
            tenant_id=tenant_id,
            result=GoalAuditResult.passed,
            planned_date=today,
            conducted_date=today,
            result_description="Stage 1 readiness review passed.",
            auditor="Internal Audit",
        )
    ]
    g2 = Goal(
        tenant_id=tenant_id,
        reference="GOAL-002",
        name="Reduce critical risks by 50%",
        description="Halve the number of critical-severity risks within the year.",
        owner="Head of Risk",
        status=GoalStatus.at_risk,
        audit_metric="Count of critical inherent risks",
        success_criteria="Critical risk count reduced by 50% vs baseline",
        audit_frequency=ReviewFrequency.quarterly,
        next_audit_date=next_review_date(ReviewFrequency.quarterly, today),
    )
    db.add_all([g1, g2])
    await db.flush()

    # --- Business Continuity plan ---
    from app.models.enums import ContinuityStatus

    billing = await db.scalar(select(Process).where(Process.name == "Customer Billing"))
    bcp = ContinuityPlan(
        tenant_id=tenant_id,
        reference="BCP-001",
        name="Ransomware recovery plan",
        description="Restore critical billing systems after a ransomware event.",
        status=ContinuityStatus.active,
        owner="Business Continuity Manager",
        business_unit_id=it.id,
        process_id=billing.id if billing else None,
        max_tolerable_downtime_hours=4,
        criticality=Criticality.critical,
        test_frequency=ReviewFrequency.semiannual,
        last_test_date=today,
        next_test_date=next_review_date(ReviewFrequency.semiannual, today),
    )
    bcp.tasks = [
        ContinuityTask(tenant_id=tenant_id, step=1, action="Isolate affected systems", actor="SOC", timing="Within 1 hour", location="Data center", method="Disconnect from network"),
        ContinuityTask(tenant_id=tenant_id, step=2, action="Restore from immutable backups", actor="Infrastructure", timing="Within 4 hours", location="DR site", method="Rebuild from offline backups"),
        ContinuityTask(tenant_id=tenant_id, step=3, action="Validate and resume billing", actor="Finance", timing="Within 8 hours", location="HQ", method="Reconcile and re-enable transactions"),
    ]
    bcp.tests = [
        ContinuityTest(tenant_id=tenant_id, result=TestResult.passed, conducted_date=today, result_description="Tabletop exercise completed; RTO met.", tester="BC Team"),
    ]
    db.add(bcp)
    await db.flush()

    # --- Data Privacy / RoPA (GDPR Article 30) ---
    from app.models.enums import DpiaStatus, LawfulBasis, RopaStatus

    db.add_all(
        [
            ProcessingActivity(
                tenant_id=tenant_id,
                reference="ROPA-001",
                name="Customer CRM processing",
                purpose="Manage customer relationships, orders and support.",
                status=RopaStatus.active,
                lawful_basis=LawfulBasis.contract,
                data_subjects="Customers, prospects",
                data_categories="Contact details, purchase history",
                retention_period="6 years after last transaction",
                controller="Acme Corp",
                dpo="Data Protection Officer",
                business_unit_id=it.id,
                cross_border_transfer=True,
                transfer_destinations="United States",
                transfer_safeguard="",  # gap: transfer without a safeguard
                dpia_required=True,
                dpia_status=DpiaStatus.in_progress,  # outstanding
                assets=[db_objs["Customer Database"]],
                risks=[risks[0]],
            ),
            ProcessingActivity(
                tenant_id=tenant_id,
                reference="ROPA-002",
                name="Employee HR records",
                purpose="Payroll, benefits and HR administration.",
                status=RopaStatus.active,
                lawful_basis=LawfulBasis.legal_obligation,
                data_subjects="Employees",
                data_categories="Identity, salary, banking; health (special category)",
                special_category=True,
                retention_period="7 years after termination",
                controller="Acme Corp",
                dpo="Data Protection Officer",
                business_unit_id=hr.id,
                cross_border_transfer=False,
                transfer_safeguard="N/A",
                dpia_required=False,
                dpia_status=DpiaStatus.not_required,
                assets=[db_objs["Payroll System"]],
            ),
        ]
    )
    await db.flush()

    # --- Access Review / certification ---
    from app.models.enums import AccessDecision, AccessReviewStatus

    ar = AccessReview(
        tenant_id=tenant_id,
        reference="AR-001",
        name="Q3 Production Access Review",
        description="Quarterly certification of access to the customer database.",
        status=AccessReviewStatus.in_progress,
        reviewer="IT Security",
        system_name="Customer Database",
        asset_id=db_objs["Customer Database"].id,
        due_date=next_review_date(ReviewFrequency.quarterly, today),
        frequency=ReviewFrequency.quarterly,
        next_review_date=next_review_date(ReviewFrequency.quarterly, today),
    )
    ar.items = [
        AccessReviewItem(tenant_id=tenant_id, username="jdoe", display_name="Jane Doe", access="db_reader", decision=AccessDecision.keep, decided_by="IT Security", decided_at=today),
        AccessReviewItem(tenant_id=tenant_id, username="bsmith", display_name="Bob Smith", access="db_admin", decision=AccessDecision.revoke, comment="Left the data team", decided_by="IT Security", decided_at=today),
        AccessReviewItem(tenant_id=tenant_id, username="svc_backup", display_name="Backup service account", access="db_reader", decision=AccessDecision.keep, decided_by="IT Security", decided_at=today),
        AccessReviewItem(tenant_id=tenant_id, username="contractor1", display_name="External contractor", access="db_admin"),
    ]
    db.add(ar)
    await db.flush()

    # --- Awareness training program ---
    from app.models.enums import AwarenessStatus, TrainingStatus

    prog = AwarenessProgram(
        tenant_id=tenant_id,
        reference="AW-001",
        name="Annual Security Awareness",
        description="Phishing, passwords and data handling refresher.",
        content="Complete the short course then take the quiz.",
        status=AwarenessStatus.active,
        passing_score=70,
        frequency=ReviewFrequency.annual,
        due_date=next_review_date(ReviewFrequency.annual, today),
        next_due_date=next_review_date(ReviewFrequency.annual, today),
    )

    def _q(text, order, correct_idx, labels):
        q = AwarenessQuestion(tenant_id=tenant_id, text=text, order_index=order)
        q.options = [
            AwarenessOption(tenant_id=tenant_id, label=lbl, is_correct=(i == correct_idx), order_index=i)
            for i, lbl in enumerate(labels)
        ]
        return q

    prog.questions = [
        _q("What should you do with a suspicious email?", 0, 1, ["Open the attachment", "Report it to security", "Forward to colleagues"]),
        _q("How often should passwords be unique per service?", 1, 0, ["Always", "Sometimes", "Never"]),
        _q("Where may you store confidential customer data?", 2, 2, ["Personal laptop", "Public cloud drive", "Approved encrypted systems"]),
    ]
    prog.participants = [
        TrainingRecord(tenant_id=tenant_id, participant_name="Jane Doe", participant_email="jane@acme.com", status=TrainingStatus.completed, score=100, completed_at=today),
        TrainingRecord(tenant_id=tenant_id, participant_name="Bob Smith", participant_email="bob@acme.com", status=TrainingStatus.completed, score=66, completed_at=today),
        TrainingRecord(tenant_id=tenant_id, participant_name="Carol King", participant_email="carol@acme.com", status=TrainingStatus.assigned),
    ]
    db.add(prog)
    await db.flush()

    # --- Approval workflow requests ---
    from datetime import date as _date

    from app.models.enums import ApprovalStatus

    pol2 = await db.scalar(select(Policy).where(Policy.reference == "POL-002"))
    db.add_all(
        [
            ApprovalRequest(
                tenant_id=tenant_id,
                reference="APR-001",
                title="Publish Acceptable Use Policy v1.0",
                description="Approve POL-002 for publication after review.",
                status=ApprovalStatus.pending,
                entity_type="policy",
                entity_id=pol2.id if pol2 else None,
                entity_label="POL-002 Acceptable Use Policy",
                link="/policies",
                approver="CISO",
                # Raised by the admin: they see it as their own and cannot decide it.
                requested_by=admin.id,
                requested_by_email=admin.email,
                due_date=_date(2025, 12, 1),  # past -> overdue
            ),
            ApprovalRequest(
                tenant_id=tenant_id,
                reference="APR-002",
                title="Approve risk treatment for ransomware (R-002)",
                description="Sign off on the mitigation plan for R-002.",
                status=ApprovalStatus.pending,
                entity_type="risk",
                entity_id=risks[1].id,
                entity_label="R-002 Ransomware",
                link="/risks",
                approver="Head of Risk",
                # Raised by Ayesha (the maker): the admin is an independent checker.
                requested_by=maker.id,
                requested_by_email=maker.email,
                due_date=next_review_date(ReviewFrequency.monthly, today),
            ),
        ]
    )
    await db.flush()

    # --- Custom fields (extend the Project model) ---
    from app.models.custom_field import CustomField, CustomFieldValue
    from app.models.enums import CustomFieldType

    cf_dept = CustomField(
        tenant_id=tenant_id, model="project", label="Department",
        field_type=CustomFieldType.select,
        options="Engineering\nSecurity\nOperations\nFinance",
        required=True, order_index=1, help_text="Owning department for this project.",
    )
    cf_owner = CustomField(
        tenant_id=tenant_id, model="project", label="Budget Owner",
        field_type=CustomFieldType.text, order_index=2,
    )
    cf_board = CustomField(
        tenant_id=tenant_id, model="project", label="Board Approved",
        field_type=CustomFieldType.checkbox, order_index=3,
    )
    cf_ctrl_owner = CustomField(
        tenant_id=tenant_id, model="control", label="Control Owner",
        field_type=CustomFieldType.text, order_index=1,
    )
    cf_inc_sev = CustomField(
        tenant_id=tenant_id, model="incident", label="Customer Impact",
        field_type=CustomFieldType.select, options="None\nLow\nModerate\nSevere",
        order_index=1, help_text="Estimated impact on customers.",
    )
    cf_vendor_tier = CustomField(
        tenant_id=tenant_id, model="vendor", label="Contract Tier",
        field_type=CustomFieldType.select, options="Tier 1\nTier 2\nTier 3", order_index=1,
    )
    db.add_all([cf_dept, cf_owner, cf_board, cf_ctrl_owner, cf_inc_sev, cf_vendor_tier])
    await db.flush()
    db.add_all(
        [
            CustomFieldValue(tenant_id=tenant_id, custom_field_id=cf_dept.id, entity_id=proj.id, value="Security"),
            CustomFieldValue(tenant_id=tenant_id, custom_field_id=cf_owner.id, entity_id=proj.id, value="Jane Doe (CISO)"),
            CustomFieldValue(tenant_id=tenant_id, custom_field_id=cf_board.id, entity_id=proj.id, value="true"),
        ]
    )
    await db.flush()

    # --- Default KPI dashboard widgets (idempotent; catalogue titles) ---
    await seed_default_widgets(db, tenant_id)

    # --- Default approval routes and dual-control rules (enabled). create_organization
    # already added them; this keeps a re-seeded demo tenant complete. ---
    from app.services.default_governance import ensure_default_governance

    await ensure_default_governance(db, tenant_id)

    # --- Collaboration (comments / tags / attachments on the seeded project) ---
    from app.models.collab import Attachment, Comment, EntityTag, Tag

    t_priority = Tag(tenant_id=tenant_id, name="High Priority", color="#dc2626")
    t_security = Tag(tenant_id=tenant_id, name="Security", color="#2563eb")
    t_q3 = Tag(tenant_id=tenant_id, name="Q3", color="#16a34a")
    db.add_all([t_priority, t_security, t_q3])
    await db.flush()
    db.add_all(
        [
            EntityTag(tenant_id=tenant_id, tag_id=t_priority.id, entity_type="project", entity_id=proj.id),
            EntityTag(tenant_id=tenant_id, tag_id=t_security.id, entity_type="project", entity_id=proj.id),
            Comment(tenant_id=tenant_id, entity_type="project", entity_id=proj.id,
                    author_email=settings.seed_admin_email, body="Kickoff complete — immutable backup vendor shortlisted."),
            Comment(tenant_id=tenant_id, entity_type="project", entity_id=proj.id,
                    author_email=settings.seed_admin_email, body="Budget approved by the board; procurement in progress."),
            Attachment(tenant_id=tenant_id, entity_type="project", entity_id=proj.id,
                       title="Project charter.pdf", url="https://example.com/charter.pdf", kind="document",
                       added_by_email=settings.seed_admin_email),
        ]
    )
    await db.flush()

    # --- Example webhook (disabled by default) ---
    from app.models.webhook import Webhook

    db.add(
        Webhook(
            tenant_id=tenant_id,
            name="Security SIEM",
            url="https://example.com/nexusline/webhook",
            secret="change-me",
            events="risk,incident,approval",
            enabled=False,
        )
    )
    await db.flush()

    # --- Dynamic status rules ---
    from app.models.status_rule import StatusRule

    db.add_all(
        [
            StatusRule(tenant_id=tenant_id, model="risk", field="inherent_score", operator="gte",
                       value="15", label="High Exposure", color="#dc2626", priority=1),
            StatusRule(tenant_id=tenant_id, model="risk", field="next_review_date", operator="overdue",
                       value="", label="Review Overdue", color="#d97706", priority=2),
            StatusRule(tenant_id=tenant_id, model="risk", field="status", operator="eq",
                       value="accepted", label="Accepted", color="#2563eb", priority=3),
            StatusRule(tenant_id=tenant_id, model="control", field="next_audit_date", operator="overdue",
                       value="", label="Audit Overdue", color="#d97706", priority=1),
            StatusRule(tenant_id=tenant_id, model="asset", field="criticality", operator="eq",
                       value="critical", label="Critical Asset", color="#dc2626", priority=1),
            StatusRule(tenant_id=tenant_id, model="asset", field="next_review_date", operator="overdue",
                       value="", label="Review Overdue", color="#d97706", priority=2),
        ]
    )
    await db.flush()

    # --- Attestations (one current on project, one overdue on a risk) ---
    from datetime import date as _d

    from app.models.attestation import Attestation

    db.add_all(
        [
            Attestation(
                tenant_id=tenant_id, entity_type="project", entity_id=proj.id,
                attested_by_email=settings.seed_admin_email, attested_at=today,
                comment="Initial project review completed.", frequency=ReviewFrequency.quarterly,
                next_due=next_review_date(ReviewFrequency.quarterly, today),
            ),
            Attestation(
                tenant_id=tenant_id, entity_type="risk", entity_id=risks[0].id,
                attested_by_email=settings.seed_admin_email, attested_at=_d(2025, 1, 15),
                comment="Annual risk review.", frequency=ReviewFrequency.annual,
                next_due=_d(2026, 1, 15),  # past -> overdue
            ),
        ]
    )
    await db.flush()

    # --- Saved filters ---
    from app.models.saved_filter import SavedFilter

    db.add_all(
        [
            SavedFilter(
                tenant_id=tenant_id, name="High inherent risks", model="risk", shared=True,
                owner_email=settings.seed_admin_email, match_mode="all",
                description="Risks with an inherent score of 15 or more.",
                conditions=[{"field": "inherent_score", "operator": "gte", "value": "15"}],
            ),
            SavedFilter(
                tenant_id=tenant_id, name="Open & high incidents", model="incident", shared=True,
                owner_email=settings.seed_admin_email, match_mode="any",
                description="Incidents that are open or under investigation.",
                conditions=[
                    {"field": "status", "operator": "eq", "value": "open"},
                    {"field": "status", "operator": "eq", "value": "investigating"},
                ],
            ),
            SavedFilter(
                tenant_id=tenant_id, name="Critical assets", model="asset", shared=True,
                owner_email=settings.seed_admin_email, match_mode="all",
                conditions=[{"field": "criticality", "operator": "eq", "value": "critical"}],
            ),
            SavedFilter(
                tenant_id=tenant_id, name="Review overdue", model="asset", shared=True,
                owner_email=settings.seed_admin_email, match_mode="all",
                conditions=[{"field": "next_review_date", "operator": "overdue", "value": ""}],
            ),
        ]
    )
    await db.flush()


async def _requirements_by_ref(db: AsyncSession, framework_id) -> dict[str, Requirement]:
    rows = (await db.scalars(select(Requirement).where(Requirement.framework_id == framework_id))).all()
    return {r.reference: r for r in rows}


async def seed_if_empty() -> None:
    """Create the bootstrap org (+ demo data when ``seed_data``) if no tenants exist yet.

    ``seed_data`` → the demo: bootstrap org, admin, sample records, the second maker
    user, default tiles, plus the empty isolation-demo org. Every organisation — demo or
    not — gets the enabled default approval routes and dual-control rules from
    ``create_organization``.
    ``seed_bootstrap`` alone → a clean first organisation and its admin, nothing else —
    what a client installation gets.
    """
    if not (settings.seed_data or settings.seed_bootstrap):
        return

    async with tenant_session(None) as db:
        count = await db.scalar(select(func.count()).select_from(Tenant))
        if count and count > 0:
            return

        tenant, _admin = await create_organization(
            db,
            name=settings.seed_org_name,
            slug=settings.seed_org_slug,
            admin_email=settings.seed_admin_email,
            admin_password=settings.seed_admin_password,
            admin_full_name="Platform Admin",
        )
        # The bootstrap admin operates the deployment as well as this org — somebody has
        # to be able to create the second one, and on a fresh install there is nobody else.
        _admin.is_platform_admin = True
        if not settings.seed_data:
            print(
                f"Bootstrapped org '{tenant.name}' (slug={tenant.slug}) with admin "
                f"{settings.seed_admin_email} (platform administrator); no demo data. "
                "Change the admin password on first login."
            )
            return

        await _seed_sample_data(db, tenant.id, _admin)
        print(
            f"Seeded org '{tenant.name}' (slug={tenant.slug}) "
            f"with admin {settings.seed_admin_email} (platform administrator) "
            f"and maker {demo_maker_email(settings.seed_admin_email)} ({DEMO_MAKER_ROLE})."
        )

        if settings.seed_second_org:
            # Deliberately left empty. Signing into it and finding an empty register is
            # the demonstration: same URL, same build, none of the first org's data.
            second, _ = await create_organization(
                db,
                name=settings.seed_second_org_name,
                slug=settings.seed_second_org_slug,
                admin_email=settings.seed_second_admin_email,
                admin_password=settings.seed_admin_password,
                admin_full_name="Organisation Admin",
            )
            print(
                f"Seeded second org '{second.name}' (slug={second.slug}) "
                f"with admin {settings.seed_second_admin_email} — empty, to show isolation."
            )
