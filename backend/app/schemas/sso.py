from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SsoConfigUpdate(BaseModel):
    provider: str = "oidc"
    enabled: bool = False
    client_id: str = ""
    client_secret: str | None = None  # None = leave unchanged
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    scopes: str = "openid email profile"
    email_claim: str = "email"
    name_claim: str = "name"
    jit_provisioning: bool = True
    default_role: str = "Viewer"
    allowed_domains: str = ""


class SsoConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    provider: str
    enabled: bool
    client_id: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scopes: str
    email_claim: str
    name_claim: str
    jit_provisioning: bool
    default_role: str
    allowed_domains: str
    client_secret_set: bool = False


class SsoStatus(BaseModel):
    enabled: bool
    provider: str


class SsoLoginResponse(BaseModel):
    redirect_url: str


class SsoCallbackRequest(BaseModel):
    code: str
    state: str
    redirect_uri: str
