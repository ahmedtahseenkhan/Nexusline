"""User, role and permission administration within an org.

This module owns three route groups, all mounted under the ``/users`` router that
``api/v1/router.py`` already registers:

* ``/users``                – user CRUD, activate/deactivate, password reset
* ``/users/roles``          – role CRUD with permission sets
* ``/users/permissions``    – the global permission catalog (read-only)

The ``/users/roles`` and ``/users/permissions`` sub-routers are mounted **before**
the dynamic ``/users/{user_id}`` routes are declared, so the literal paths win the
match instead of being swallowed by the ``{user_id}`` UUID path parameter.

Security notes:
* Password hashing stays in ``app.core.security`` (bcrypt); we never accept or
  return ``hashed_password``.
* Every endpoint keeps the existing RBAC gates (``user:*`` / ``role:*``).
* System roles (``is_system``) can have their permission set edited but cannot be
  renamed or deleted.
* Admins cannot deactivate their own account (lock-out guard).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, require
from app.core.permissions import PERMISSION_CATALOG
from app.core.security import hash_password
from app.models.identity import Permission, Role, User
from app.schemas.common import Page
from app.schemas.user import (
    PermissionRead,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    UserCreate,
    UserPasswordSet,
    UserRead,
    UserUpdate,
)
from app.services import audit, password_policy

router = APIRouter(prefix="/users", tags=["users"])


# --------------------------------------------------------------------------- helpers
async def _load_user(db: DbSession, user_id: uuid.UUID) -> User:
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _roles_by_names(db: DbSession, names: list[str]) -> list[Role]:
    if not names:
        return []
    return list((await db.scalars(select(Role).where(Role.name.in_(names)))).all())


async def _load_role(db: DbSession, role_id: uuid.UUID) -> Role:
    role = await db.scalar(
        select(Role)
        .where(Role.id == role_id)
        .options(selectinload(Role.permissions))
        .execution_options(populate_existing=True)
    )
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


async def _permissions_by_codes(db: DbSession, codes: list[str]) -> list[Permission]:
    """Resolve permission codes against the global catalog.

    Unknown codes are rejected so a typo can't silently strip access.
    """
    wanted = list(dict.fromkeys(codes))  # de-dupe, keep order
    unknown = [c for c in wanted if c not in PERMISSION_CATALOG]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown permission code(s): {', '.join(unknown)}",
        )
    if not wanted:
        return []
    return list((await db.scalars(select(Permission).where(Permission.code.in_(wanted)))).all())


def _role_read(role: Role) -> RoleRead:
    return RoleRead(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permission_codes=sorted(p.code for p in role.permissions),
    )


# ----------------------------------------------------------------------- permissions
permissions_router = APIRouter(prefix="/permissions", tags=["permissions"])


@permissions_router.get(
    "", response_model=list[PermissionRead], dependencies=[Depends(require("role:read"))]
)
async def list_permissions(db: DbSession) -> list[PermissionRead]:
    """The global permission catalog, ordered by code.

    Falls back to the static catalog so the picker works even before the DB
    catalog has been reconciled.
    """
    rows = (await db.scalars(select(Permission).order_by(Permission.code))).all()
    if rows:
        return [PermissionRead.model_validate(p) for p in rows]
    return [
        PermissionRead(code=code, description=desc)
        for code, desc in sorted(PERMISSION_CATALOG.items())
    ]


# ----------------------------------------------------------------------------- roles
roles_router = APIRouter(prefix="/roles", tags=["roles"])


@roles_router.get("", response_model=list[RoleRead], dependencies=[Depends(require("role:read"))])
async def list_roles(db: DbSession) -> list[RoleRead]:
    rows = (
        await db.scalars(
            select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
        )
    ).all()
    return [_role_read(r) for r in rows]


@roles_router.post(
    "",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("role:write"))],
)
async def create_role(body: RoleCreate, db: DbSession, actor: CurrentUser) -> RoleRead:
    name = body.name.strip()
    if await db.scalar(select(Role).where(Role.name == name)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A role with that name already exists"
        )
    perms = await _permissions_by_codes(db, body.permission_codes)
    role = Role(
        tenant_id=actor.tenant_id,
        name=name,
        description=body.description,
        is_system=False,
        permissions=perms,
    )
    db.add(role)
    await db.flush()
    await audit.record(
        db, actor=actor, action="create", entity_type="role", entity_id=role.id,
        summary=f"Created role {role.name}",
    )
    return _role_read(await _load_role(db, role.id))


@roles_router.get(
    "/{role_id}", response_model=RoleRead, dependencies=[Depends(require("role:read"))]
)
async def get_role(role_id: uuid.UUID, db: DbSession) -> RoleRead:
    return _role_read(await _load_role(db, role_id))


@roles_router.patch(
    "/{role_id}", response_model=RoleRead, dependencies=[Depends(require("role:write"))]
)
async def update_role(
    role_id: uuid.UUID, body: RoleUpdate, db: DbSession, actor: CurrentUser
) -> RoleRead:
    role = await _load_role(db, role_id)
    data = body.model_dump(exclude_unset=True)

    if data.get("name") is not None:
        new_name = data["name"].strip()
        if new_name != role.name:
            if role.is_system:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="System roles cannot be renamed",
                )
            if await db.scalar(select(Role).where(Role.name == new_name, Role.id != role.id)):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A role with that name already exists",
                )
            role.name = new_name

    if data.get("permission_codes") is not None:
        role.permissions = await _permissions_by_codes(db, data["permission_codes"])

    if data.get("description") is not None:
        role.description = data["description"]

    await db.flush()
    await audit.record(
        db, actor=actor, action="update", entity_type="role", entity_id=role.id,
        summary=f"Updated role {role.name}",
    )
    return _role_read(await _load_role(db, role.id))


@roles_router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require("role:write"))],
)
async def delete_role(role_id: uuid.UUID, db: DbSession, actor: CurrentUser) -> None:
    role = await _load_role(db, role_id)
    if role.is_system:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="System roles cannot be deleted",
        )
    assigned = await db.scalar(
        select(func.count()).select_from(User).where(User.roles.any(Role.id == role.id))
    )
    if assigned:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Role is assigned to {assigned} user(s); reassign them first",
        )
    summary = f"Deleted role {role.name}"
    await db.delete(role)
    await db.flush()
    await audit.record(
        db, actor=actor, action="delete", entity_type="role", entity_id=role_id, summary=summary
    )


# Mount the literal-path sub-routers BEFORE the dynamic /{user_id} routes below.
router.include_router(permissions_router)
router.include_router(roles_router)


# ----------------------------------------------------------------------------- users
@router.get("", response_model=Page[UserRead], dependencies=[Depends(require("user:read"))])
async def list_users(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UserRead]:
    total = await db.scalar(select(func.count()).select_from(User)) or 0
    rows = (
        await db.scalars(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .order_by(User.email)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return Page(
        items=[UserRead.model_validate(u) for u in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("user:write"))],
)
async def create_user(body: UserCreate, db: DbSession, actor: CurrentUser) -> UserRead:
    if await db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already in use"
        )
    password_policy.validate_password(body.password)
    roles = await _roles_by_names(db, body.role_names)
    user = User(
        tenant_id=actor.tenant_id,
        email=body.email,
        full_name=body.full_name,
        is_active=body.is_active,
        hashed_password=hash_password(body.password),
        password_changed_at=datetime.now(timezone.utc),
        roles=roles,
    )
    db.add(user)
    await db.flush()
    await audit.record(
        db, actor=actor, action="create", entity_type="user", entity_id=user.id,
        summary=f"Created user {user.email}",
    )
    return UserRead.model_validate(await _load_user(db, user.id))


@router.get(
    "/{user_id}", response_model=UserRead, dependencies=[Depends(require("user:read"))]
)
async def get_user(user_id: uuid.UUID, db: DbSession) -> UserRead:
    return UserRead.model_validate(await _load_user(db, user_id))


@router.patch(
    "/{user_id}", response_model=UserRead, dependencies=[Depends(require("user:write"))]
)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, db: DbSession, actor: CurrentUser
) -> UserRead:
    user = await _load_user(db, user_id)
    data = body.model_dump(exclude_unset=True)

    if "role_names" in data:
        user.roles = await _roles_by_names(db, data.pop("role_names") or [])

    # Guard: don't let an admin lock themselves out by deactivating their own account.
    if data.get("is_active") is False and user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    for field, value in data.items():
        setattr(user, field, value)

    await db.flush()
    await audit.record(
        db, actor=actor, action="update", entity_type="user", entity_id=user.id,
        summary=f"Updated user {user.email}",
    )
    return UserRead.model_validate(await _load_user(db, user.id))


async def _set_active(
    user_id: uuid.UUID, db: DbSession, actor: User, active: bool
) -> UserRead:
    user = await _load_user(db, user_id)
    if not active and user.id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )
    user.is_active = active
    await db.flush()
    await audit.record(
        db, actor=actor, action="update", entity_type="user", entity_id=user.id,
        summary=f"{'Activated' if active else 'Deactivated'} user {user.email}",
    )
    return UserRead.model_validate(await _load_user(db, user.id))


@router.post(
    "/{user_id}/activate", response_model=UserRead, dependencies=[Depends(require("user:write"))]
)
async def activate_user(user_id: uuid.UUID, db: DbSession, actor: CurrentUser) -> UserRead:
    return await _set_active(user_id, db, actor, True)


@router.post(
    "/{user_id}/deactivate", response_model=UserRead, dependencies=[Depends(require("user:write"))]
)
async def deactivate_user(user_id: uuid.UUID, db: DbSession, actor: CurrentUser) -> UserRead:
    return await _set_active(user_id, db, actor, False)


@router.post(
    "/{user_id}/password",
    response_model=UserRead,
    dependencies=[Depends(require("user:write"))],
    summary="Set a user's password (admin reset)",
)
async def set_user_password(
    user_id: uuid.UUID, body: UserPasswordSet, db: DbSession, actor: CurrentUser
) -> UserRead:
    password_policy.validate_password(body.password)
    user = await _load_user(db, user_id)
    user.hashed_password = hash_password(body.password)
    user.password_changed_at = datetime.now(timezone.utc)
    # An admin reset clears any lockout so the user can sign in again.
    user.failed_login_attempts = 0
    user.locked_until = None
    await db.flush()
    await audit.record(
        db, actor=actor, action="update", entity_type="user", entity_id=user.id,
        summary=f"Reset password for user {user.email}",
    )
    return UserRead.model_validate(await _load_user(db, user.id))
