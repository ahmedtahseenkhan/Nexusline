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
from sqlalchemy import or_, select

from app.core.deps import CurrentUser, DbSession
from app.models.asset import Asset
from app.models.compliance import Requirement
from app.models.enums import AssetClass
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.incident import Incident
from app.models.organization import BusinessUnit, Legal, Process
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.risk import Risk
from app.models.vendor import Vendor

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
]


@router.get("", response_model=SearchResults)
async def global_search(q: str, db: DbSession, user: CurrentUser, limit: int = 8) -> SearchResults:
    term = q.strip()
    if len(term) < 2:
        return SearchResults(query=q, hits=[])

    perms = set(user.permission_codes)
    like = f"%{term}%"
    per_type = max(1, min(limit, 15))
    hits: list[SearchHit] = []

    for tgt in _TARGETS:
        if tgt.read_perm not in perms:
            continue
        model = tgt.model
        title_col = getattr(model, tgt.title_attr)
        conditions = [title_col.ilike(like)]
        if hasattr(model, "reference"):
            conditions.append(model.reference.ilike(like))
        if hasattr(model, "description"):
            conditions.append(model.description.ilike(like))

        stmt = select(model).where(or_(*conditions))
        if hasattr(model, "deleted"):
            stmt = stmt.where(model.deleted.is_(False))
        stmt = stmt.limit(per_type)

        for obj in (await db.scalars(stmt)).all():
            reference = getattr(obj, "reference", "") or ""
            title = getattr(obj, tgt.title_attr, "") or ""
            # Deep-link straight to the record so search/⌘K opens its drawer, not just
            # the module. Assets split by class into the IT vs Information register.
            base = tgt.link
            if model is Asset:
                base = "/it-assets" if obj.asset_class == AssetClass.it_asset else "/information-assets"
            hits.append(
                SearchHit(
                    type=tgt.type_label,
                    label=f"{tgt.type_label} · {reference}" if reference else tgt.type_label,
                    reference=reference,
                    title=str(title),
                    link=f"{base}?id={obj.id}",
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
