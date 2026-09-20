"""My Work — ``GET /my/work``: everything waiting for the signed-in user.

* ``GET  /my/work`` — sections per kind of work (approvals, records in review, tests to
  review, validations, extensions; treatment and issue actions, issues, incidents,
  control tests, returned tests, risk reviews, attestations, KRI readings, RCSA actions;
  policies to acknowledge), each with a count and items overdue first, every item a deep
  link. Any signed-in user: it lists only their own work, filtered by what they may do.
  See ``services/my_work.py``.
* ``POST /my/work/treatment-actions/{action_id}/done`` — the quick action: mark one of
  my risk treatment actions done (its owner, or anyone with ``risk:write``). Audited on
  the risk as ``update_treatment_action``. (The other quick action, acknowledging a
  policy, is ``POST /policies/{id}/acknowledge``.)

This router also mounts the public approve-from-e-mail endpoints
(``GET /actions/{token}``, ``POST /actions/{token}/confirm``, defined beside the in-app
decision in ``api/v1/approvals.py``) so the phase-3 surface registers with one line.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.v1.approvals import email_router
from app.core.deps import CurrentUser, DbSession
from app.schemas.my_work import MyWorkRead, TreatmentActionDone
from app.services import my_work as service

router = APIRouter(tags=["my work"])


@router.get("/my/work", response_model=MyWorkRead, summary="Everything waiting for me, most urgent first")
async def get_my_work(db: DbSession, user: CurrentUser) -> MyWorkRead:
    return await service.my_work(db, user)


@router.post(
    "/my/work/treatment-actions/{action_id}/done",
    response_model=TreatmentActionDone,
    summary="Mark one of my risk treatment actions done (owner, or risk:write)",
)
async def mark_treatment_action_done(action_id: uuid.UUID, db: DbSession, user: CurrentUser) -> TreatmentActionDone:
    return await service.mark_treatment_action_done(db, user, action_id)


router.include_router(email_router)
# Phase 4B: workspaces, the board home, the assurance workspace and period snapshots.
from app.api.v1.workspaces import router as workspaces_router  # noqa: E402

router.include_router(workspaces_router)
