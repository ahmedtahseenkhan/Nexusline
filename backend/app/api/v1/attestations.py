"""Attestation API — periodic review sign-off on any record (polymorphic)."""
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.attestation import Attestation
from app.schemas.attestation import AttestationCreate, AttestationRead, AttestationStatus
from app.services import audit
from app.services.risk_scoring import next_review_date

router = APIRouter(prefix="/attestations", tags=["attestations"])


async def _history(db, entity_type: str, entity_id: uuid.UUID) -> list[Attestation]:
    return list(
        (
            await db.scalars(
                select(Attestation)
                .where(Attestation.entity_type == entity_type, Attestation.entity_id == entity_id)
                .order_by(Attestation.attested_at.desc(), Attestation.created_at.desc())
            )
        ).all()
    )


def _bundle(rows: list[Attestation]) -> AttestationStatus:
    if not rows:
        return AttestationStatus(status="never", history=[])
    latest = rows[0]
    if latest.next_due is not None and latest.next_due < date.today():
        status = "overdue"
    else:
        status = "current"
    return AttestationStatus(
        status=status,
        last_attested_at=latest.attested_at,
        last_by=latest.attested_by_email,
        next_due=latest.next_due,
        frequency=latest.frequency,
        history=[AttestationRead.model_validate(r) for r in rows],
    )


@router.get("/{entity_type}/{entity_id}", response_model=AttestationStatus)
async def get_status(entity_type: str, entity_id: uuid.UUID, db: DbSession, _: CurrentUser) -> AttestationStatus:
    return _bundle(await _history(db, entity_type, entity_id))


@router.post("/{entity_type}/{entity_id}", response_model=AttestationStatus, status_code=201)
async def attest(
    entity_type: str, entity_id: uuid.UUID, body: AttestationCreate, db: DbSession, user: CurrentUser
) -> AttestationStatus:
    today = date.today()
    row = Attestation(
        tenant_id=user.tenant_id,
        entity_type=entity_type,
        entity_id=entity_id,
        attested_by_id=user.id,
        attested_by_email=user.email,
        attested_at=today,
        comment=body.comment,
        frequency=body.frequency,
        next_due=next_review_date(body.frequency, today),
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db, actor=user, action="attest", entity_type=entity_type, entity_id=entity_id,
        summary=f"Attested {entity_type} (next due {row.next_due})",
    )
    return _bundle(await _history(db, entity_type, entity_id))
