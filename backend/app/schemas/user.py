from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RoleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    created_at: datetime
    roles: list[RoleRead] = []


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = ""
    password: str = Field(min_length=8, max_length=128)
    role_names: list[str] = Field(default_factory=lambda: ["Viewer"])
