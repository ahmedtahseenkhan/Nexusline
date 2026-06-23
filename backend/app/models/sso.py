"""SSO configuration — one OIDC/OAuth2 identity-provider config per tenant."""
from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SsoConfig(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "sso_configs"

    provider: Mapped[str] = mapped_column(String(16), default="oidc")  # oidc | oauth2 | saml
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    client_id: Mapped[str] = mapped_column(String(255), default="")
    client_secret: Mapped[str] = mapped_column(String(512), default="")
    authorize_url: Mapped[str] = mapped_column(String(1024), default="")
    token_url: Mapped[str] = mapped_column(String(1024), default="")
    userinfo_url: Mapped[str] = mapped_column(String(1024), default="")
    scopes: Mapped[str] = mapped_column(String(255), default="openid email profile")

    email_claim: Mapped[str] = mapped_column(String(64), default="email")
    name_claim: Mapped[str] = mapped_column(String(64), default="name")

    jit_provisioning: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    default_role: Mapped[str] = mapped_column(String(64), default="Viewer")
    allowed_domains: Mapped[str] = mapped_column(String(512), default="")  # csv; empty = any
