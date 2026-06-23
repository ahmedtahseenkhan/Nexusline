from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserRead


class RegisterOrgRequest(BaseModel):
    org_name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    admin_email: EmailStr
    admin_password: str = Field(min_length=8, max_length=128)
    admin_full_name: str = ""


class LoginRequest(BaseModel):
    tenant_slug: str
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
