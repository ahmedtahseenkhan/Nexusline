"""User administration within an org."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require
from app.core.security import hash_password
from app.models.identity import Role, User
from app.schemas.common import Page
from app.schemas.user import UserCreate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserRead], dependencies=[Depends(require("user:read"))])
async def list_users(
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[UserRead]:
    total = await db.scalar(select(func.count()).select_from(User)) or 0
    rows = (
        await db.scalars(select(User).order_by(User.email).limit(limit).offset(offset))
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
    roles = (
        await db.scalars(select(Role).where(Role.name.in_(body.role_names)))
    ).all()
    user = User(
        tenant_id=actor.tenant_id,
        email=body.email,
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        roles=list(roles),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return UserRead.model_validate(user)
