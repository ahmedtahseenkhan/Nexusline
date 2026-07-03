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


class LoginResult(BaseModel):
    """Either a full token (no MFA) or an MFA challenge to complete the second factor."""

    mfa_required: bool = False
    challenge_token: str | None = None
    # Present only when mfa_required is False:
    access_token: str | None = None
    token_type: str = "bearer"
    expires_in: int | None = None
    user: UserRead | None = None


class MfaVerifyRequest(BaseModel):
    challenge_token: str
    code: str


class MfaSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MfaActivateRequest(BaseModel):
    code: str


class MfaDisableRequest(BaseModel):
    code: str = ""  # a user disabling their own MFA must supply a valid code


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=128)


class LdapConfigRead(BaseModel):
    model_config = {"from_attributes": True}
    enabled: bool
    host: str
    port: int
    use_ssl: bool
    start_tls: bool
    bind_dn: str
    base_dn: str
    user_filter: str
    email_attribute: str
    name_attribute: str
    default_role: str
    bind_password_set: bool = False


class LdapConfigUpdate(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 389
    use_ssl: bool = False
    start_tls: bool = True
    bind_dn: str = ""
    bind_password: str | None = None  # only updates when provided
    base_dn: str = ""
    user_filter: str = "(userPrincipalName={username})"
    email_attribute: str = "mail"
    name_attribute: str = "displayName"
    default_role: str = "Viewer"
