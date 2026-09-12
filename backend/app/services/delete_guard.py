"""Four-eyes on deleting a business record (product review §1.4).

Archiving a risk, control, policy, business unit or process removes it from every
register, report and dashboard that counted it. Under segregation of duties the person
who entered the record may not also be the one who removes it: the same maker-checker
rule as approving it (``dual_control.enforce_record_maker_checker``), keyed
``(<entity type>, delete)``.

The maker is whoever the audit trail says created the record, else the user reference
on the record itself (``dual_control.maker_of``). With the global
``enforce_segregation_of_duties`` switch on and no rule configured, a single-user
install (a demo, an evaluation) therefore cannot delete what it entered: add a second
user, or add a dual-control rule for ``<type> / delete`` with ``requires_dual_control``
off (or a threshold), or set ``ENFORCE_SEGREGATION_OF_DUTIES=false``.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import dual_control


def refusal(entity_type: str, label: str) -> str:
    return (
        f"Segregation of duties: you entered this {label}, so another user must delete it. "
        f"Ask a colleague who may delete {label}s, or ask an administrator to add a "
        f"dual-control rule for {entity_type} / delete."
    )


async def enforce(
    db: AsyncSession,
    *,
    entity_type: str,
    record: Any,
    user: Any,
    label: str,
    amount: float | None = None,
) -> None:
    """Raise 403 when dual control applies to deleting this record and ``user`` made it."""
    try:
        await dual_control.enforce_record_maker_checker(
            db,
            module=entity_type,
            action="delete",
            entity_type=entity_type,
            entity_id=record.id,
            checker_id=user.id,
            amount=amount,
            subject=f"{label} deletion",
            record=record,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_403_FORBIDDEN:
            raise
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=refusal(entity_type, label)
        ) from exc
