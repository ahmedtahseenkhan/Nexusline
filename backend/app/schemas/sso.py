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
    """The tenant's SSO config as the admin screen sees it.

    Every field carries the same default as its ``SsoConfig`` column. Column defaults
    are applied by SQLAlchemy at INSERT, so an *unsaved* ``SsoConfig()`` — what the GET
    returns before SSO has ever been configured — has ``None`` in every attribute.
    Without these defaults that first page load fails validation and 500s.
    """

    model_config = ConfigDict(from_attributes=True)
    provider: str = "oidc"
    enabled: bool = False
    client_id: str = ""
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    scopes: str = "openid email profile"
    email_claim: str = "email"
    name_claim: str = "name"
    jit_provisioning: bool = True
    default_role: str = "Viewer"
    allowed_domains: str = ""
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
