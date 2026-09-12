"""Platform-operator endpoints: provisioning and running the organisations themselves.

Everything else in the API answers "what is true inside my organisation?". This router
answers "which organisations exist on this deployment?", which is a different question
with a different audience: whoever runs the install, not whoever uses it. That is why
access is the ``is_platform_admin`` column rather than a permission code — permissions
live in tenant-scoped ``roles`` rows, so an org admin could otherwise mint themselves
one.

One consequence worth stating, because it bites: a tenant-less session cannot write to
a tenant-scoped table either. Where these endpoints record something in an organisation's
own audit trail they must first point the session at that organisation, and the operator
identity travels in the entry rather than in the connection.

**These endpoints deliberately cannot read tenant data.** The listing joins nothing;
per-organisation counts are gathered by opening a session scoped to each tenant in turn
and counting inside it. That is more round trips than one grouped query, and it is the
point: row-level security means a grouped query across tenants is not expressible, and
an endpoint that could express one would be the hole this console exists to avoid.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, or_, select, update

from app.core.config import settings
from app.core.database import set_session_tenant, system_session, tenant_session
from app.core.deps import CurrentUser, require_platform_admin
from app.db.provisioning import create_organization
from app.models.control import Control
from app.models.identity import User
from app.models.risk import Risk
from app.models.tenant import Tenant
from app.services import audit, license, password_policy

router = APIRouter(
    prefix="/platform",
    tags=["platform"],
    dependencies=[Depends(require_platform_admin)],
)


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    #: Counted inside the organisation's own RLS scope, never across it.
    users: int = 0
    active_users: int = 0
    risks: int = 0
    controls: int = 0


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    #: The organisation identifier its people type at the login screen.
    slug: str = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=128)
    admin_full_name: str = ""


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    #: Suspending blocks every login for the organisation. Its data is untouched.
    is_active: bool | None = None


class DemoResetRequest(BaseModel):
    #: Must equal the organisation's identifier (slug) — typed, not clicked.
    confirm: str


class DemoResetResult(BaseModel):
    organization: str
    prefixes: list[str]
    #: Records archived, per table. Tables with nothing to archive are omitted.
    archived: dict[str, int]
    total: int


class PlatformSummary(BaseModel):
    organizations: int
    active_organizations: int
    users: int
    deployment: str
    license: dict


async def _counts(tenant_id: uuid.UUID) -> dict[str, int]:
    """Row counts for one organisation, read inside that organisation's own scope."""
    async with tenant_session(tenant_id) as db:
        users = (await db.scalars(select(User))).all()
        return {
            "users": len(users),
            "active_users": sum(1 for u in users if u.is_active),
            "risks": await db.scalar(
                select(func.count()).select_from(Risk).where(Risk.deleted.is_(False))
            ) or 0,
            "controls": await db.scalar(
                select(func.count()).select_from(Control).where(Control.deleted.is_(False))
            ) or 0,
        }


@router.get("/organizations", response_model=list[OrganizationRead])
async def list_organizations(with_counts: bool = True) -> list[OrganizationRead]:
    """Every organisation on this deployment, newest first.

    ``with_counts=false`` skips the per-organisation round trips, which is what a
    deployment with a long list of orgs should use for a quick check.
    """
    async with system_session() as db:
        tenants = (await db.scalars(select(Tenant).order_by(Tenant.created_at.desc()))).all()
        rows = [OrganizationRead.model_validate(t) for t in tenants]

    if with_counts:
        for row in rows:
            for key, value in (await _counts(row.id)).items():
                setattr(row, key, value)
    return rows


@router.post("/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_org(body: OrganizationCreate, user: CurrentUser) -> OrganizationRead:
    """Provision a new organisation with its first admin.

    The same call ``POST /auth/register-org`` makes, minus the self-service: this one is
    made by the operator, and it is the path a bank onboarding actually takes.
    """
    password_policy.validate_password(body.admin_password)
    async with system_session() as db:
        if await db.scalar(select(Tenant).where(Tenant.slug == body.slug)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"The identifier '{body.slug}' is already taken by another organisation",
            )
        tenant, admin = await create_organization(
            db,
            name=body.name,
            slug=body.slug,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
            admin_full_name=body.admin_full_name,
        )
        admin.password_changed_at = datetime.now(timezone.utc)
        # create_organization leaves the GUC pointing at the new org, so this lands in
        # the new organisation's own trail — where its auditors will look for it.
        await audit.record_system(
            db,
            tenant_id=tenant.id,
            action="create",
            entity_type="organization",
            entity_id=tenant.id,
            summary=f"Organisation '{body.name}' provisioned by {user.email}",
            changes={"slug": body.slug, "admin": body.admin_email, "by": user.email},
        )
        created = OrganizationRead.model_validate(tenant)
    for key, value in (await _counts(created.id)).items():
        setattr(created, key, value)
    return created


@router.patch("/organizations/{tenant_id}", response_model=OrganizationRead)
async def update_org(
    tenant_id: uuid.UUID, body: OrganizationUpdate, user: CurrentUser
) -> OrganizationRead:
    """Rename an organisation, or suspend/restore it.

    Suspension is reversible and destroys nothing: ``is_active`` is what the login flow
    checks, so people are locked out while every record stays exactly where it was. There
    is deliberately no delete — an organisation's data outlives its contract, and a
    button that drops a bank's register is not one worth having.
    """
    async with system_session() as db:
        tenant = await db.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found"
            )
        if tenant.id == user.tenant_id and body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You cannot suspend the organisation you are signed in to",
            )
        changes: dict[str, object] = {}
        # What actually happened, in the words an auditor reading this org's trail needs:
        # "updated" tells them nothing they can act on.
        done: list[str] = []
        if body.name is not None and body.name != tenant.name:
            changes["name"] = body.name
            done.append(f"renamed from '{tenant.name}' to '{body.name}'")
            tenant.name = body.name
        if body.is_active is not None and body.is_active != tenant.is_active:
            changes["is_active"] = body.is_active
            done.append("suspended" if body.is_active is False else "access restored")
            tenant.is_active = body.is_active
        await db.flush()
        if changes:
            # The trail entry belongs to the organisation it describes — that is where
            # its own auditors will look for "who suspended us, and when". Writing it
            # needs the tenant GUC pointed there: this session opened tenant-less (the
            # `tenants` registry carries no policy), and row-level security refuses an
            # INSERT stamped with a tenant the connection is not scoped to. That refusal
            # is the isolation guarantee doing its job, not an obstacle to route around.
            await set_session_tenant(db, tenant.id)
            await audit.record_system(
                db,
                tenant_id=tenant.id,
                action="update",
                entity_type="organization",
                entity_id=tenant.id,
                summary=f"Organisation {' and '.join(done)} by {user.email}",
                changes={**changes, "by": user.email},
            )
        result = OrganizationRead.model_validate(tenant)
    for key, value in (await _counts(result.id)).items():
        setattr(result, key, value)
    return result


@router.get("/summary", response_model=PlatformSummary)
async def summary() -> PlatformSummary:
    """Deployment-wide totals and the licence the whole install runs under.

    The licence is per *deployment*, not per organisation: one signed token covers the
    install, which is what makes the same build serve a multi-tenant cloud and a
    single-tenant bank on-premise without a second code path.
    """
    async with system_session() as db:
        tenants = (await db.scalars(select(Tenant))).all()

    users = 0
    for tenant in tenants:
        users += (await _counts(tenant.id))["users"]

    info = license.load_current()
    return PlatformSummary(
        organizations=len(tenants),
        active_organizations=sum(1 for t in tenants if t.is_active),
        users=users,
        deployment=info.deployment or "on-premise",
        license=info.to_public(),
    )


# ------------------------------------------------------------------ demo reset ---
def archivable_models() -> list[tuple[type, str]]:
    """Every tenant-scoped, soft-deletable model (``SoftDeleteMixin``, or its own
    ``deleted``/``deleted_date`` pair as ``assets`` has) with a ``title`` or ``name``
    column, paired with that column's name (``title`` preferred)."""
    from app.models.base import Base

    found: list[tuple[type, str]] = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        columns = cls.__table__.c
        if "tenant_id" not in columns or "deleted" not in columns or "deleted_date" not in columns:
            continue
        label = "title" if "title" in columns else "name" if "name" in columns else None
        if label is not None:
            found.append((cls, label))
    return sorted(found, key=lambda pair: pair[0].__tablename__)


def demo_reset_refusal(
    tenant_slug: str, confirm: str, demo_slug: str, prefixes: list[str]
) -> tuple[int, str] | None:
    """``(status code, reason)`` when a reset must be refused, or None when it may run."""
    if not demo_slug or tenant_slug != demo_slug:
        return (
            status.HTTP_403_FORBIDDEN,
            f"Only the demo organisation ('{demo_slug or 'none configured'}') can be reset; "
            f"'{tenant_slug}' is not it.",
        )
    if (confirm or "").strip() != tenant_slug:
        return (
            422,
            f"Type the organisation identifier '{tenant_slug}' in \"confirm\" to reset it.",
        )
    if not prefixes:
        return status.HTTP_409_CONFLICT, "No test-data prefixes are configured (DEMO_RESET_PREFIXES)."
    return None


@router.post("/organizations/{tenant_id}/reset-demo", response_model=DemoResetResult)
async def reset_demo(tenant_id: uuid.UUID, body: DemoResetRequest, user: CurrentUser) -> DemoResetResult:
    """Clear test debris out of the demo organisation in one call.

    **What it does:** archives (``deleted = true``, ``deleted_date = now``) every live
    record whose ``title`` — or ``name`` where the table has no title — starts with one
    of ``settings.demo_reset_prefixes`` (default ``NL-E2E-TEST``), across every
    soft-deletable table. Matching is case-sensitive and literal (``%`` and ``_`` in a
    prefix match themselves). Returns the count archived per table.

    **What it does not do:** hard-delete anything, touch records without the prefix,
    reseed, or undo edits made to seeded records. Archived rows stay in the database and
    can be restored by clearing ``deleted``.

    **Guards:** platform administrators only (router dependency); refused (403) for any
    organisation but the configured demo org (``DEMO_ORG_SLUG``, else ``SEED_ORG_SLUG`` on an
    install with ``SEED_DATA=true``; a client install has no demo org and always refuses);
    the body must be ``{"confirm": "<org slug>"}`` (422 otherwise). Every archived record
    gets its own audit entry in the organisation's trail, plus one summary entry.
    """
    async with system_session() as db:
        tenant = await db.get(Tenant, tenant_id)
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
        slug, name = tenant.slug, tenant.name

    prefixes = [p for p in settings.demo_reset_prefixes if p and p.strip()]
    refusal = demo_reset_refusal(slug, body.confirm, settings.demo_org, prefixes)
    if refusal is not None:
        raise HTTPException(status_code=refusal[0], detail=refusal[1])

    now = datetime.now(timezone.utc)
    archived: dict[str, int] = {}
    # Scoped to the demo org alone: row-level security confines every UPDATE below to it.
    async with tenant_session(tenant_id) as db:
        for model, label in archivable_models():
            column = getattr(model, label)
            rows = (
                await db.execute(
                    update(model)
                    .where(
                        model.deleted.is_(False),
                        or_(*[column.startswith(p, autoescape=True) for p in prefixes]),
                    )
                    .values(deleted=True, deleted_date=now)
                    .returning(model.id, column)
                    .execution_options(synchronize_session=False)
                )
            ).all()
            if not rows:
                continue
            archived[model.__tablename__] = len(rows)
            for row_id, row_label in rows:
                await audit.record_system(
                    db,
                    tenant_id=tenant_id,
                    action="archive",
                    entity_type=model.__tablename__,
                    entity_id=row_id,
                    summary=f"Archived test record '{str(row_label)[:200]}' (demo reset by {user.email})"[:500],
                    changes={"deleted": True, "by": user.email, "reason": "demo_reset"},
                )
        total = sum(archived.values())
        await audit.record_system(
            db,
            tenant_id=tenant_id,
            action="reset_demo",
            entity_type="organization",
            entity_id=tenant_id,
            summary=f"Demo reset by {user.email}: archived {total} test record(s)",
            changes={"prefixes": prefixes, "archived": archived, "by": user.email},
        )
    return DemoResetResult(organization=name, prefixes=prefixes, archived=archived, total=total)
