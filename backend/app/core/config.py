"""Application configuration, loaded from environment variables."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _string_list(value: object) -> object:
    """Accept a list from the environment as JSON (``["a","b"]``) or comma-separated
    (``a,b``) — operators write the second, pydantic-settings only reads the first."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]
    return value


def _release_build() -> bool:
    """``core/build.PRODUCTION_BUILD`` — true in a release image. Read at settings load."""
    from app.core import build

    return bool(build.PRODUCTION_BUILD)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database — owner/superuser role used for DDL, migrations and bootstrap only.
    postgres_user: str = "aegis"
    postgres_password: str = "aegis_dev_password"
    postgres_db: str = "aegis"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # Least-privilege runtime role. RLS only constrains NON-superusers, so all
    # request traffic connects as this role (created/granted during init).
    app_db_user: str = "aegis_app"
    app_db_password: str = "aegis_app_password"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Application
    secret_key: str = "dev-only-insecure-secret-change-me"
    access_token_expire_minutes: int = 60
    jwt_algorithm: str = "HS256"
    environment: str = "development"
    cors_origins: str = "http://localhost:3000"

    # File storage (binary uploads for attachments & evidence)
    file_storage_dir: str = "./var/uploads"
    max_upload_mb: int = 25

    # Outbound email (SMTP). When smtp_host is empty, mail is logged, not sent.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "NexusLine GRC <no-reply@nexusline.local>"
    smtp_use_tls: bool = True
    app_base_url: str = "http://localhost:3000"

    # AI Assist ("Circular Intelligence"). Optional — when blank, the module falls back
    # to a deterministic offline heuristic so on-prem installs work with no external calls.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    # Background scheduler (periodic notification refresh, reminders, chasing)
    scheduler_enabled: bool = True
    scheduler_interval_minutes: int = 15

    # Governance controls. Maker-checker Segregation of Duties: when true, the user
    # who submits an approval request (maker) can never be the one who approves it
    # (checker). Mandated in most banking control environments; keep on for banks.
    enforce_segregation_of_duties: bool = True

    # --- Authentication hardening (banking baseline) ---
    # Password policy
    password_min_length: int = 12
    password_require_complexity: bool = True  # upper+lower+digit+symbol
    password_expiry_days: int = 0  # 0 = no expiry
    # Brute-force protection / account lockout
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    # MFA (TOTP). When ``mfa_required`` is true every user who signs in with a password
    # must enrol. Otherwise it is required for *privileged* users only: anyone holding a
    # role named in the organisation's MFA role list (Settings → Organisation → Security;
    # ``mfa_required_roles`` below is the default until an organisation sets its own, and
    # the Admin role can never be taken off) or any permission ending in
    # ":approve" (a checker). Unenrolled users get ``mfa_grace_days`` of normal sign-in
    # from their first such login; after that the session can only enrol. SSO sign-ins
    # are exempt (the identity provider owns the second factor); LDAP/AD password
    # sign-ins are not. See app/services/mfa_policy.py.
    #
    # Decision 3 (2026-09-17): a release image requires MFA for every password user unless
    # ``MFA_REQUIRED`` is set explicitly; a dev/test checkout defaults to off so local
    # sign-in and the test suite need no authenticator.
    mfa_issuer: str = "NexusLine GRC"
    mfa_required: bool = Field(default_factory=lambda: _release_build())
    # The enforcement level every organisation on this deployment starts at: ``off``
    # (nobody is made to enrol; people who enrolled keep using it), ``privileged`` (the
    # Admin role, anyone who can approve, and the listed roles) or ``everyone`` (every
    # password sign-in). Unset → ``everyone`` when ``mfa_required`` is true, else
    # ``privileged``; so ``MFA_REQUIRED`` keeps working for installs that set it. An
    # organisation may choose its own level under Settings → Organisation → Security
    # unless ``mfa_enforcement_locked`` is true — set that where the bank's IT security
    # policy, not its GRC team, decides. ``off`` is for evaluation and UAT installs.
    mfa_enforcement: str | None = None
    mfa_enforcement_locked: bool = False
    mfa_required_roles: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["admin"])
    mfa_grace_days: int = 7
    # Approve / Reject links in e-mail (phase 3). Deciding from an e-mail skips two-factor
    # authentication — the link is the credential — so they are OFF unless an installation
    # opts in: a checker must sign in (with MFA where the policy requires it) to decide.
    # While false no links are issued, digests carry no Approve / Reject buttons, and
    # links already sent stop working.
    email_actions_enabled: bool = False
    # LDAP / Active Directory (per-tenant config in DB; this only gates the feature)
    ldap_enabled: bool = False

    # Public self-service sign-up (POST /auth/register-org): anyone reaching the API can
    # create an organisation and become its administrator. A hosted-trial feature; a
    # bank's installation must not expose it. Operators create organisations from
    # Settings → Organisations, and the licence's organisation cap applies either way.
    allow_self_registration: bool = False

    # --- On-prem productionization ---
    app_version: str = "1.0.0"
    deployment_mode: str = "on-prem"  # on-prem | saas
    # Offline licensing (Ed25519, no phone-home). Only *where the license lives* is
    # configurable — whether it is enforced and which key validates it are compiled
    # into the image (see app/core/build.py), so the client cannot switch them off.
    license_file: str = "./deploy/license.key"
    # Comma-separated module keys to hide on this installation even when
    # licensed (see app/core/modules.py), e.g. "shariah" for a conventional
    # bank or "esg,ai_assist". The license remains the entitlement ceiling.
    disabled_modules: str = ""
    # Backups (pg_dump) target directory.
    backup_dir: str = "./var/backups"

    # Continuous control monitoring (phase 4D).
    # Key for connector secrets at rest (Fernet). Blank = derived from ``secret_key``, so
    # rotating ``secret_key`` then makes stored connector secrets unreadable (re-enter
    # them); set this separately to rotate one without the other.
    connector_secret_key: str = ""
    # May an HTTP connector call a private, loopback or link-local address? Blank = the
    # deployment decides: yes on-prem (core banking, SIEM and CMDB APIs are internal),
    # no on SaaS (server-side request forgery into the hosting network). "true"/"false"
    # overrides.
    ccm_allow_private_urls: bool | None = None
    # Folder scanner and log-health exports are dropped into; a connector's import path
    # must resolve inside it.
    ccm_import_dir: str = "./var/ccm-imports"
    # Monitoring-feed (POST /connectors/ingest) requests allowed per token per minute.
    ccm_ingest_rate_per_minute: int = 60

    # Regulatory incident reporting SLA windows (verify against the current SBP circular).
    default_regulator: str = "SBP"
    regulatory_initial_report_hours: int = 24   # initial breach notification
    regulatory_final_report_days: int = 30      # detailed / final report

    # AML/CFT — STR/SAR filing SLA (days from detection; verify vs FMU/SBP rules).
    aml_str_filing_days: int = 7

    # Seed. On an empty database the first org + its admin (a platform administrator)
    # are created from the seed_org_* / seed_admin_* values when either flag is on.
    # ``seed_data`` additionally loads the DEMO sample data and the isolation-demo org —
    # never for a client (docker-compose.prod.yml defaults it to false);
    # ``seed_bootstrap`` alone gives a client install a clean org and an admin to sign in
    # with, which is otherwise impossible without the public register endpoint.
    seed_data: bool = True
    seed_bootstrap: bool = True
    seed_org_name: str = "Acme Corp"
    seed_org_slug: str = "acme"
    seed_admin_email: str = "admin@acme.com"
    seed_admin_password: str = "ChangeMe123!"
    # A second, deliberately empty organisation created alongside the demo one. Its
    # entire job is to make tenant isolation visible: sign in to it and the register is
    # blank, because none of the demo org's data is reachable from here. Without it a
    # deployment only ever gets exercised on one org, which is how multi-tenancy goes
    # unvalidated right up to the day a second bank is onboarded.
    seed_second_org: bool = True
    seed_second_org_name: str = "Second Bank (isolation demo)"
    seed_second_org_slug: str = "second"
    seed_second_admin_email: str = "admin@second.com"

    # Demo-reset (POST /platform/organizations/{id}/reset-demo). Only the demo org may be
    # reset; blank means the seeded org (``seed_org_slug``) when ``seed_data`` is on, and
    # no org at all otherwise. The reset archives records whose name/title starts with one
    # of these prefixes — the markers test runs use.
    demo_org_slug: str = ""
    demo_reset_prefixes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["NL-E2E-TEST"]
    )

    @field_validator("mfa_required_roles", "demo_reset_prefixes", mode="before")
    @classmethod
    def _parse_string_list(cls, value: object) -> object:
        return _string_list(value)

    @field_validator("mfa_enforcement", mode="before")
    @classmethod
    def _parse_mfa_enforcement(cls, value: object) -> object:
        """``off`` / ``privileged`` / ``everyone`` (a few aliases accepted); empty = unset.
        A misspelling is refused at start-up rather than quietly weakening the policy."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        from app.services.mfa_policy import normalise_mode

        level = normalise_mode(value)
        if level is None:
            raise ValueError("MFA_ENFORCEMENT must be one of: off, privileged, everyone")
        return level

    def _url(self, user: str, password: str) -> str:
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url(self) -> str:
        """Owner/superuser connection — DDL, migrations, bootstrap."""
        return self._url(self.postgres_user, self.postgres_password)

    @property
    def app_database_url(self) -> str:
        """Runtime connection used by request/seed sessions (RLS-constrained)."""
        return self._url(self.app_db_user, self.app_db_password)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def demo_org(self) -> str:
        """Slug of the one organisation the demo reset may touch: ``demo_org_slug`` if
        set, else the seeded org — but only on an install that seeds demo data, so a
        client's bootstrapped org (seed_data=false) can never be "reset"."""
        if self.demo_org_slug.strip():
            return self.demo_org_slug.strip()
        return self.seed_org_slug.strip() if self.seed_data else ""

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
