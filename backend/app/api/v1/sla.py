"""Turnaround-time (TAT) policy and breach reporting.

``GET /sla-policies`` always returns a complete grid — every record type crossed with
every severity — filling unconfigured scopes with the shipped default and flagging them
``is_default``. A settings screen that shows blanks for anything nobody has touched
teaches the user that the clock is off, when in fact it is running.

``GET /sla-breaches`` reconciles before it reports, so a policy edited a minute ago is
reflected immediately rather than at the next background sweep.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.enums import Severity
from app.models.sla import SlaPolicy
from app.schemas.sla import (
    SlaPolicyRead,
    SlaPolicyUpdate,
    TatSummary,
)
from app.services import audit as audit_log
from app.services import sla

router = APIRouter(tags=["sla"])

_READ = Depends(require("risk:read"))
_WRITE = Depends(require("sla:manage"))

_SEVERITY_ORDER = (Severity.critical, Severity.high, Severity.medium, Severity.low)


@router.get(
    "/sla-policies",
    response_model=list[SlaPolicyRead],
    dependencies=[_READ],
    summary="The full TAT grid — configured scopes plus the defaults in force elsewhere",
)
async def list_policies(db: DbSession) -> list[SlaPolicyRead]:
    configured = {(p.entity_type, p.severity): p for p in (await db.scalars(select(SlaPolicy))).all()}
    out: list[SlaPolicyRead] = []
    for key, spec in sla.ENTITIES.items():
        for severity in _SEVERITY_ORDER:
            row = configured.get((key, severity))
            if row is not None:
                out.append(
                    SlaPolicyRead(
                        id=row.id, entity_type=key, entity_label=spec.label, severity=severity,
                        target_days=row.target_days, warn_at_percent=row.warn_at_percent,
                        escalate_to_role=row.escalate_to_role, enabled=row.enabled,
                        is_default=False,
                    )
                )
                continue
            default = sla.DEFAULT_TARGETS.get(key, {}).get(severity)
            out.append(
                SlaPolicyRead(
                    id=None, entity_type=key, entity_label=spec.label, severity=severity,
                    target_days=default or 0, warn_at_percent=sla.DEFAULT_WARN_PERCENT,
                    escalate_to_role="", enabled=default is not None, is_default=True,
                )
            )
    return out


@router.put(
    "/sla-policies",
    response_model=list[SlaPolicyRead],
    dependencies=[_WRITE],
    summary="Upsert one or more scopes of the TAT grid",
)
async def update_policies(
    body: SlaPolicyUpdate, db: DbSession, user: CurrentUser
) -> list[SlaPolicyRead]:
    existing = {(p.entity_type, p.severity): p for p in (await db.scalars(select(SlaPolicy))).all()}
    for item in body.policies:
        row = existing.get((item.entity_type, item.severity))
        if row is None:
            row = SlaPolicy(
                tenant_id=user.tenant_id, entity_type=item.entity_type, severity=item.severity
            )
            db.add(row)
        row.target_days = item.target_days
        row.warn_at_percent = item.warn_at_percent
        row.escalate_to_role = item.escalate_to_role
        row.enabled = item.enabled
    await db.flush()
    # Due dates are derived, so a policy change has to propagate to the records now —
    # otherwise the register keeps reporting yesterday's windows until the next sweep.
    await sla.reconcile(db, user.tenant_id)
    await audit_log.record(
        db, actor=user, action="update", entity_type="sla_policy", entity_id=None,
        summary=f"Updated {len(body.policies)} turnaround-time target(s)",
        changes={
            f"{i.entity_type}/{i.severity.value}": f"{i.target_days}d" for i in body.policies
        },
    )
    return await list_policies(db)


@router.get(
    "/sla-breaches",
    response_model=TatSummary,
    dependencies=[_READ],
    summary="Records at risk of, or past, their turnaround time",
)
async def breaches(db: DbSession, user: CurrentUser) -> TatSummary:
    return TatSummary.model_validate(await sla.summary(db, user.tenant_id))
