"""Default approval routes and dual-control rules every organisation starts with.

A bank that signs up used to get segregation of duties only as a global switch: no
approval routes (the seeded ones were disabled and only existed in the demo) and no
dual-control rules, so an examiner asking "where is your maker-checker configured?"
was shown an empty register. This module is the one place that says what a new
organisation gets, and it is used by:

* ``db.provisioning.create_organization`` — every new organisation (sign-up, platform
  console, first-run bootstrap and the demo);
* ``POST /settings/organisation/onboarding/complete`` — so an organisation that deleted
  everything during set-up still leaves onboarding with a baseline;
* ``db.data_repairs.repair_tenant`` — once per existing organisation (marked in the
  activity log with :data:`SEEDED_ACTION`), so organisations created before this
  existed receive the same baseline on the next start.

**Never overwrites.** A route is added only for a record type that has no route at all
(enabled or not) — except the two untouched, never-enabled routes the old demo seed
created, which named roles no organisation has (``CISO``, ``CRO``) and are upgraded in
place. A rule is added only for a (module, action) that has no rule, deleted ones
included, so a rule an administrator removed does not come back.

**Routes** (:data:`DEFAULT_ROUTES`) govern the record lifecycle's *submit for review*
(``services/record_workflow.py``): the maker submits, and the named role decides in the
Approvals inbox. Only record types with that lifecycle can be routed; issue closure and
control-test review are dedicated two-person steps and are governed by rules instead.

========== ===================== =================================================
record     route                 who decides
========== ===================== =================================================
risk       Risk approval         Risk Approver (the CRO function) — the risk owner
                                 submits the assessment
policy     Policy approval       Compliance Manager (compliance head) — the policy
                                 owner submits
exception  Exception approval    Risk Approver
========== ===================== =================================================

**Rules** (:data:`DEFAULT_RULES`) cover every (module, action) key the code enforces
(see ``services/dual_control.py``). They are created *enabled* when the installation
enforces segregation of duties, which changes nothing about what is refused — with no
rule the global switch already refused the same things — but makes the configuration
visible and adjustable per action (a threshold, or an explicit exemption). On an
installation with ``ENFORCE_SEGREGATION_OF_DUTIES=false`` they are created disabled, so
seeding them does not switch four-eyes on behind the operator's back.

**Roles nobody holds.** A route stage names a role. When no active user other than the
maker holds it, the stage cannot be decided by a holder; rather than dead-ending, anyone
with ``workflow:approve`` may decide it and the Approvals page and Settings say
"No one holds the … role — assign it in Users" (:func:`stage_decision_refusal`,
:func:`role_gap_message`).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

#: Activity-log action marking that an organisation received the defaults (the boot
#: repair runs once per organisation because of it).
SEEDED_ACTION = "default_governance_seeded"
SEEDED_ENTITY = "tenant_settings"


@dataclass(frozen=True)
class StageSpec:
    name: str
    approver_mode: str  # ApproverMode value
    approver_ref: str = ""
    sla_days: int = 0


@dataclass(frozen=True)
class RouteSpec:
    entity_type: str
    name: str
    description: str
    stages: tuple[StageSpec, ...]


@dataclass(frozen=True)
class RuleSpec:
    module: str
    action: str
    maker_role: str
    checker_role: str
    description: str


#: Role names seeded by ``core.permissions.DEFAULT_ROLES`` that routes rely on.
RISK_APPROVER = "Risk Approver"
COMPLIANCE_MANAGER = "Compliance Manager"
RISK_MANAGER = "Risk Manager"

DEFAULT_ROUTES: tuple[RouteSpec, ...] = (
    RouteSpec(
        "risk",
        "Risk approval",
        "The risk owner submits the assessment; the Risk Approver (the CRO function) "
        "approves it or sends it back. Accepting a risk is decided separately, under the "
        "risk's Acceptances, by someone other than whoever asked for it.",
        (StageSpec("CRO approval", "role", RISK_APPROVER, 10),),
    ),
    RouteSpec(
        "policy",
        "Policy approval",
        "The policy owner submits the policy; the Compliance Manager (compliance head) "
        "approves it before it can be published.",
        (StageSpec("Compliance head approval", "role", COMPLIANCE_MANAGER, 10),),
    ),
    RouteSpec(
        "exception",
        "Exception approval",
        "Whoever raises the exception submits it; the Risk Approver approves it or sends "
        "it back.",
        (StageSpec("Risk approval", "role", RISK_APPROVER, 5),),
    ),
)

#: The disabled routes the demo seed created before this module existed, as
#: (entity_type, name, ((stage name, mode, ref), ...)). An organisation that still has
#: one exactly like this, never enabled, gets it upgraded to the matching default.
LEGACY_DEFAULT_ROUTES: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "policy",
        "Policy approval",
        (
            ("Policy owner review", "record_owner", ""),
            ("Compliance review", "role", "Compliance Manager"),
            ("CISO sign-off", "role", "CISO"),
        ),
    ),
    (
        "risk",
        "Risk acceptance",
        (
            ("Risk owner confirmation", "record_owner", ""),
            ("Department head approval", "line_manager", ""),
            ("CRO approval", "role", "CRO"),
        ),
    ),
)


def _delete_rule(entity: str, label: str) -> RuleSpec:
    return RuleSpec(
        entity, "delete", "", "",
        f"Archiving a {label}: the person who entered it cannot also delete it.",
    )


#: Decision 9 (2026-09-20): **no default attest rule.** An attestation is the record
#: owner's own certification (ServiceNow IRM campaigns, Archer, SOX 302/404, ISO 27001
#: A.5.36), and in a bank the first-line owner usually entered the record too — a
#: maker-checker rule on ``(<type>, attest)`` would therefore leave nobody able to
#: certify it now that decision 6 requires a complete approval first. Independence comes
#: from that approval and from the required second signature
#: (``api/v1/attestations.confirm``). Organisations seeded with the old
#: ``(risk|control|policy|vendor, attest)`` rules keep them — they are in the
#: administrator's register and are theirs to disable — and attesting honours a rule that
#: is there; nothing re-creates one.
DEFAULT_RULES: tuple[RuleSpec, ...] = (
    RuleSpec("risk", "accept", RISK_MANAGER, RISK_APPROVER,
             "Accepting a risk: whoever asked for the acceptance cannot approve it."),
    RuleSpec("risk", "approve", RISK_MANAGER, RISK_APPROVER,
             "Approving a risk submitted for review: not whoever entered or submitted it."),
    RuleSpec("risk", "bulk_archive", RISK_MANAGER, "",
             "Archiving risks with no live links in bulk. One person does it in one step, so "
             "while this rule requires dual control the bulk archive is refused; archive "
             "risks one at a time, or exempt this action to allow it."),
    _delete_rule("risk", "risk"),
    RuleSpec("exception", "approve", RISK_MANAGER, RISK_APPROVER,
             "Approving an exception: whoever requested it cannot approve it."),
    RuleSpec("control", "audit", "", COMPLIANCE_MANAGER,
             "Recording a control test: not whoever entered the control."),
    RuleSpec("control", "review_test", "", COMPLIANCE_MANAGER,
             "Reviewing a control test: not the tester, nor whoever recorded or edited the test."),
    _delete_rule("control", "control"),
    RuleSpec("policy", "publish", "", COMPLIANCE_MANAGER,
             "Publishing a policy: not whoever entered it."),
    RuleSpec("policy", "approve", "", COMPLIANCE_MANAGER,
             "Approving a policy submitted for review: not whoever entered or submitted it."),
    _delete_rule("policy", "policy"),
    RuleSpec("issue", "validate", "", "",
             "Validating an issue's remediation: not its owner, nor whoever raised it."),
    RuleSpec("issue", "close", "", "",
             "Closing an issue: not whoever raised it."),
    RuleSpec("issue", "extend_due_date", "", "",
             "Approving a later due date on a regulator-related, high or critical issue: "
             "not whoever asked for it."),
    _delete_rule("issue", "issue"),
    RuleSpec("authority", "update", "", "",
             "Amending a delegation-of-authority line: not whoever entered it."),
    _delete_rule("business_unit", "business unit"),
    _delete_rule("process", "process"),
    _delete_rule("legal", "legal register entry"),
    _delete_rule("incident", "incident"),
    _delete_rule("vendor", "third party"),
    RuleSpec("assessment", "review", "", "",
             "Completing the review of a questionnaire assessment: not whoever sent it."),
    RuleSpec("aml", "file_sar", "", "",
             "Marking an STR / SAR as filed with the FMU: not whoever prepared it."),
    RuleSpec("shariah", "charity_approved", "", "",
             "Approving a purification disbursement: not whoever entered it."),
    RuleSpec("shariah", "charity_disbursed", "", "",
             "Releasing a purification disbursement: not whoever entered it."),
)


# ----------------------------------------------------------------------- pure rules ---
def _key(name: str | None) -> str:
    return (name or "").strip().lower()


def routes_to_add(existing_entity_types: Iterable[str]) -> list[RouteSpec]:
    """Default routes for record types that have no route at all."""
    have = set(existing_entity_types)
    return [r for r in DEFAULT_ROUTES if r.entity_type not in have]


def rules_to_add(existing_keys: Iterable[tuple[str, str]]) -> list[RuleSpec]:
    """Default rules for (module, action) keys that have no rule, deleted ones included."""
    have = {(m, a) for m, a in existing_keys}
    return [r for r in DEFAULT_RULES if (r.module, r.action) not in have]


def legacy_upgrade_for(
    entity_type: str, name: str, enabled: bool, stages: Iterable[tuple[str, str, str]]
) -> RouteSpec | None:
    """The default that replaces an untouched legacy demo route, or None.

    Only a route that was never enabled and still has exactly the legacy stages matches;
    anything an administrator edited is theirs and is left alone.
    """
    if enabled:
        return None
    signature = tuple((s, m, r) for s, m, r in stages)
    for legacy_type, legacy_name, legacy_stages in LEGACY_DEFAULT_ROUTES:
        if (entity_type, name, signature) == (legacy_type, legacy_name, legacy_stages):
            return next(r for r in DEFAULT_ROUTES if r.entity_type == entity_type)
    return None


def needs_second_user(active_users: int, sod_enforced: bool) -> bool:
    """One active user and segregation of duties on: nothing that needs a checker can be
    decided, because the only person is always the maker."""
    return sod_enforced and active_users < 2


SECOND_USER_MESSAGE = (
    "Segregation of duties needs at least two users. You are the only active user, so "
    "nothing you submit can be approved — invite a colleague and give them an approver role."
)


def role_gap_message(role: str, *, only_maker: bool = False, lacks_permission: bool = False) -> str:
    """What the Approvals page and Settings say about a stage role nobody can decide."""
    if lacks_permission:
        return (
            f"No one other than the submitter who holds the {role} role can approve requests "
            "(the role lacks the workflow:approve permission) — grant it in Roles. Until then "
            "anyone who can approve may decide it."
        )
    if only_maker:
        return (
            f"Only the person who submitted this holds the {role} role — assign it to "
            "someone else in Users. Until then anyone who can approve may decide it."
        )
    return (
        f"No one holds the {role} role — assign it in Users. Until then anyone who can "
        "approve may decide it."
    )


def stage_decision_refusal(
    stage_role: str | None, decider_role_names: Iterable[str], eligible_holders: int
) -> str | None:
    """Why this user may not decide a route stage assigned to ``stage_role``, or None.

    ``eligible_holders`` counts active users holding the role other than the request's
    maker who can approve (``workflow:approve``) — ``notifications.stage_gate`` counts
    them for every caller. With none, the stage falls back to anyone who can approve
    (the page warns); otherwise only a holder decides it.
    """
    if not (stage_role or "").strip() or eligible_holders <= 0:
        return None
    if _key(stage_role) in {_key(n) for n in decider_role_names}:
        return None
    return (
        f"This approval stage is decided by the {stage_role.strip()} role. Ask someone who "
        "holds it to decide."
    )


@dataclass
class SeedResult:
    routes_added: list[str] = field(default_factory=list)
    routes_upgraded: list[str] = field(default_factory=list)
    rules_added: int = 0

    def __bool__(self) -> bool:
        return bool(self.routes_added or self.routes_upgraded or self.rules_added)

    def summary(self) -> str:
        parts = []
        if self.routes_added:
            parts.append(f"added approval routes: {', '.join(self.routes_added)}")
        if self.routes_upgraded:
            parts.append(f"upgraded approval routes: {', '.join(self.routes_upgraded)}")
        if self.rules_added:
            parts.append(f"added {self.rules_added} dual-control rule(s)")
        return "Default segregation-of-duties set-up: " + ("; ".join(parts) or "nothing to add")


# ------------------------------------------------------------------ database helpers ---
def _stages(tenant_id, spec: RouteSpec):
    from app.models.workflow import ApproverMode, WorkflowStage

    return [
        WorkflowStage(
            tenant_id=tenant_id,
            order_index=i,
            name=stage.name,
            approver_mode=ApproverMode(stage.approver_mode),
            approver_ref=stage.approver_ref,
            required_approvals=1,
            sla_days=stage.sla_days,
        )
        for i, stage in enumerate(spec.stages, start=1)
    ]


async def ensure_default_routes(db: AsyncSession, tenant_id) -> tuple[list[str], list[str]]:
    """Add missing default routes (enabled) and upgrade untouched legacy ones."""
    from app.models.workflow import WorkflowDefinition

    definitions = (await db.scalars(select(WorkflowDefinition))).all()
    enabled_types = {d.entity_type for d in definitions if d.enabled}
    upgraded: list[str] = []
    for d in definitions:
        spec = legacy_upgrade_for(
            d.entity_type, d.name, d.enabled,
            [(s.name, getattr(s.approver_mode, "value", s.approver_mode), s.approver_ref or "")
             for s in d.stages],
        )
        if spec is None or d.entity_type in enabled_types:
            continue
        d.name = spec.name
        d.description = spec.description
        d.stages.clear()
        await db.flush()
        d.stages.extend(_stages(tenant_id, spec))
        d.enabled = True
        enabled_types.add(d.entity_type)
        upgraded.append(spec.name)
    added: list[str] = []
    for spec in routes_to_add(d.entity_type for d in definitions):
        definition = WorkflowDefinition(
            tenant_id=tenant_id, entity_type=spec.entity_type, name=spec.name,
            description=spec.description, enabled=True,
        )
        definition.stages = _stages(tenant_id, spec)
        db.add(definition)
        added.append(spec.name)
    await db.flush()
    return added, upgraded


async def ensure_default_rules(db: AsyncSession, tenant_id, *, enabled: bool | None = None) -> int:
    """Add a rule for every default (module, action) the organisation has none for."""
    from app.core.config import settings
    from app.models.authority import DualControlRule, DualControlStatus
    from app.services.refs import next_reference

    on = settings.enforce_segregation_of_duties if enabled is None else enabled
    existing = (await db.execute(select(DualControlRule.module, DualControlRule.action))).all()
    added = 0
    for spec in rules_to_add((m, a) for m, a in existing):
        rule = DualControlRule(
            tenant_id=tenant_id, module=spec.module, action=spec.action,
            requires_dual_control=True, maker_role=spec.maker_role,
            checker_role=spec.checker_role, description=spec.description, enabled=on,
            status=DualControlStatus.active if on else DualControlStatus.disabled,
        )
        rule.reference = await next_reference(db, DualControlRule, "MC")
        db.add(rule)
        await db.flush()
        added += 1
    return added


async def already_seeded(db: AsyncSession) -> bool:
    from app.models.audit import AuditLog

    return bool(await db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == SEEDED_ACTION, AuditLog.entity_type == SEEDED_ENTITY
        )
    ))


async def ensure_default_governance(db: AsyncSession, tenant_id, *, actor=None) -> SeedResult:
    """Give the organisation its default routes and rules (never overwriting), and mark
    it in the activity log. The session must be scoped to ``tenant_id``."""
    from app.models.audit import AuditLog
    from app.services.audit import SYSTEM_ACTOR_EMAIL

    result = SeedResult()
    result.routes_added, result.routes_upgraded = await ensure_default_routes(db, tenant_id)
    result.rules_added = await ensure_default_rules(db, tenant_id)
    if result or not await already_seeded(db):
        db.add(AuditLog(
            tenant_id=tenant_id,
            actor_id=getattr(actor, "id", None),
            actor_email=getattr(actor, "email", None) or SYSTEM_ACTOR_EMAIL,
            action=SEEDED_ACTION, entity_type=SEEDED_ENTITY, entity_id=None,
            summary=result.summary()[:500],
            changes={"routes_added": result.routes_added,
                     "routes_upgraded": result.routes_upgraded,
                     "rules_added": result.rules_added},
        ))
    await db.flush()
    return result


async def role_holders(db: AsyncSession) -> dict[str, set[uuid.UUID]]:
    """Active users per role, keyed by lower-cased role name."""
    from app.models.identity import Role, User, user_roles

    rows = (await db.execute(
        select(Role.name, User.id)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .join(User, User.id == user_roles.c.user_id)
        .where(User.is_active.is_(True))
    )).all()
    out: dict[str, set[uuid.UUID]] = {}
    for name, user_id in rows:
        out.setdefault(_key(name), set()).add(user_id)
    return out


def eligible_holder_count(
    holders: Mapping[str, set[uuid.UUID]], role: str | None, maker_id: uuid.UUID | None
) -> int:
    """Active holders of ``role`` other than the maker. Pure. Ignores permissions: the
    decision rule counts with ``notifications.stage_gate``, which also requires
    ``workflow:approve``; this stays for Settings' plain head count."""
    ids = holders.get(_key(role), set())
    return len(ids - ({maker_id} if maker_id is not None else set()))


async def stage_roles(db: AsyncSession, approval_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The role each route-stage approval is assigned to (approvals that are not a
    role-assigned stage are absent)."""
    from app.models.workflow import ApproverMode, WorkflowInstanceStage, WorkflowStage

    ids = [i for i in approval_ids if i is not None]
    if not ids:
        return {}
    rows = (await db.execute(
        select(WorkflowInstanceStage.approval_request_id, WorkflowStage.approver_ref)
        .join(WorkflowStage, WorkflowStage.id == WorkflowInstanceStage.stage_id)
        .where(
            WorkflowInstanceStage.approval_request_id.in_(ids),
            WorkflowStage.approver_mode == ApproverMode.role,
        )
    )).all()
    return {aid: (ref or "").strip() for aid, ref in rows if (ref or "").strip()}


async def governance_status(db: AsyncSession) -> dict:
    """Segregation-of-duties readiness for Settings, onboarding and the admin banner."""
    from app.core.config import settings
    from app.models.authority import DualControlRule
    from app.models.identity import User
    from app.models.workflow import ApproverMode, WorkflowDefinition

    active = await db.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    ) or 0
    holders = await role_holders(db)
    definitions = (await db.scalars(
        select(WorkflowDefinition).order_by(WorkflowDefinition.entity_type, WorkflowDefinition.name)
    )).all()
    routes = []
    gaps: dict[str, list[str]] = {}
    for d in definitions:
        stages = []
        for s in d.stages:
            role = (s.approver_ref or "").strip() if s.approver_mode == ApproverMode.role else ""
            count = len(holders.get(_key(role), set())) if role else None
            stages.append({"name": s.name, "role": role or None, "holders": count})
            if d.enabled and role and not count:
                gaps.setdefault(role, []).append(d.name)
        routes.append({
            "id": str(d.id), "entity_type": d.entity_type, "name": d.name,
            "enabled": d.enabled, "stages": stages,
        })
    rules = (await db.execute(
        select(DualControlRule.enabled).where(DualControlRule.deleted.is_(False))
    )).scalars().all()
    sod = bool(settings.enforce_segregation_of_duties)
    return {
        "sod_enforced": sod,
        "active_users": active,
        "needs_second_user": needs_second_user(active, sod),
        "second_user_message": SECOND_USER_MESSAGE if needs_second_user(active, sod) else None,
        "routes": routes,
        "rules_total": len(rules),
        "rules_enabled": sum(1 for r in rules if r),
        "role_gaps": [
            {"role": role, "routes": names, "message": role_gap_message(role)}
            for role, names in sorted(gaps.items())
        ],
    }


__all__ = [
    "DEFAULT_ROUTES",
    "DEFAULT_RULES",
    "LEGACY_DEFAULT_ROUTES",
    "SECOND_USER_MESSAGE",
    "SEEDED_ACTION",
    "SeedResult",
    "eligible_holder_count",
    "ensure_default_governance",
    "governance_status",
    "legacy_upgrade_for",
    "needs_second_user",
    "role_gap_message",
    "role_holders",
    "routes_to_add",
    "rules_to_add",
    "stage_decision_refusal",
    "stage_roles",
]
