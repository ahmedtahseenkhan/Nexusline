from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class PermissionRead(BaseModel):
    """An entry from the global permission catalog."""

    model_config = ConfigDict(from_attributes=True)
    code: str
    description: str


class RoleSummary(BaseModel):
    """Lightweight role reference embedded in a user record."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str = ""


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str
    is_system: bool = False
    permission_codes: list[str] = []


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime
    mfa_enabled: bool = False
    auth_source: str = "local"
    # ``User`` ORM exposes ``permission_codes`` and ``role_names`` as properties.
    permission_codes: list[str] = []
    roles: list[RoleSummary] = []


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str = Field(min_length=8, max_length=128)
    is_active: bool = True
    role_names: list[str] = Field(default_factory=lambda: ["Viewer"])


class UserUpdate(BaseModel):
    """Partial update of a user. Password is set via the dedicated endpoint."""

    full_name: str | None = None
    is_active: bool | None = None
    role_names: list[str] | None = None


class UserPasswordSet(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    permission_codes: list[str] | None = None
