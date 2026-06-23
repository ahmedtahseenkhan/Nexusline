"""Authentication: org registration, per-org login, and current-user."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.config import settings
from app.core.database import set_session_tenant, system_session, tenant_session
from app.core.deps import CurrentUser
from app.core.security import create_access_token, verify_password
from app.db.provisioning import create_organization
from app.models.identity import User
from app.models.tenant import Tenant
from app.schemas.auth import LoginRequest, RegisterOrgRequest, TokenResponse
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])

_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
)


def _token_response(user: User, tenant_id) -> TokenResponse:
    token = create_access_token(
        subject=str(user.id),
        tenant_id=str(tenant_id),
        roles=user.role_names,
        permissions=user.permission_codes,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserRead.model_validate(user),
    )


@router.post(
    "/register-org",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new organization and its first admin",
)
async def register_org(body: RegisterOrgRequest) -> TokenResponse:
    async with tenant_session(None) as db:
        if await db.scalar(select(Tenant).where(Tenant.slug == body.slug)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization slug already taken",
            )
        tenant, admin = await create_organization(
            db,
            name=body.org_name,
            slug=body.slug,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
            admin_full_name=body.admin_full_name,
        )
        return _token_response(admin, tenant.id)


@router.post("/login", response_model=TokenResponse, summary="Log in to an organization")
async def login(body: LoginRequest) -> TokenResponse:
    async with system_session() as db:
        tenant = await db.scalar(
            select(Tenant).where(Tenant.slug == body.tenant_slug, Tenant.is_active.is_(True))
        )
        if tenant is None:
            raise _INVALID
        # Scope subsequent queries to this tenant via RLS.
        await set_session_tenant(db, tenant.id)
        user = await db.scalar(select(User).where(User.email == body.email))
        if (
            user is None
            or not user.is_active
            or not verify_password(body.password, user.hashed_password)
        ):
            raise _INVALID
        return _token_response(user, tenant.id)


@router.get("/me", response_model=UserRead, summary="Current authenticated user")
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
