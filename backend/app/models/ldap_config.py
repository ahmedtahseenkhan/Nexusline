"""Per-tenant LDAP / Active Directory connection settings.

Drives directory authentication and just-in-time user provisioning. Stored per
tenant so each on-prem org binds to its own AD. The bind password is stored as
given (deploy behind the app's own access controls); rotate via the admin UI.
"""
from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class LdapConfig(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "ldap_configs"

    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=389)
    use_ssl: Mapped[bool] = mapped_column(Boolean, default=False)   # LDAPS (636)
    start_tls: Mapped[bool] = mapped_column(Boolean, default=True)  # StartTLS on 389

    bind_dn: Mapped[str] = mapped_column(String(512), default="")       # service account
    bind_password: Mapped[str] = mapped_column(String(512), default="")
    base_dn: Mapped[str] = mapped_column(String(512), default="")       # user search base

    # {username} is substituted with the login value. AD email login example:
    #   (userPrincipalName={username})  or  (mail={username})  or  (sAMAccountName={username})
    user_filter: Mapped[str] = mapped_column(String(512), default="(userPrincipalName={username})")
    email_attribute: Mapped[str] = mapped_column(String(64), default="mail")
    name_attribute: Mapped[str] = mapped_column(String(64), default="displayName")

    # Role name granted to JIT-provisioned directory users on first login.
    default_role: Mapped[str] = mapped_column(String(64), default="Viewer")
