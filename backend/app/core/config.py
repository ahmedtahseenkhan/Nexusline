"""Application configuration, loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # MFA (TOTP). When required, all local users must enrol before full access.
    mfa_issuer: str = "NexusLine GRC"
    mfa_required: bool = False
    # LDAP / Active Directory (per-tenant config in DB; this only gates the feature)
    ldap_enabled: bool = False

    # --- On-prem productionization ---
    app_version: str = "1.0.0"
    deployment_mode: str = "on-prem"  # on-prem | saas
    # Offline licensing (Ed25519, no phone-home). enforce_license fails startup on an
    # invalid/expired/absent license when true; keep false for dev/self-host.
    enforce_license: bool = False
    license_file: str = "./deploy/license.key"
    license_public_key_path: str = "./deploy/license_pubkey.pem"
    # Comma-separated module keys to hide on this installation even when
    # licensed (see app/core/modules.py), e.g. "shariah" for a conventional
    # bank or "esg,ai_assist". The license remains the entitlement ceiling.
    disabled_modules: str = ""
    # Backups (pg_dump) target directory.
    backup_dir: str = "./var/backups"

    # Regulatory incident reporting SLA windows (verify against the current SBP circular).
    default_regulator: str = "SBP"
    regulatory_initial_report_hours: int = 24   # initial breach notification
    regulatory_final_report_days: int = 30      # detailed / final report

    # AML/CFT — STR/SAR filing SLA (days from detection; verify vs FMU/SBP rules).
    aml_str_filing_days: int = 7

    # Seed
    seed_data: bool = True
    seed_org_name: str = "Acme Corp"
    seed_org_slug: str = "acme"
    seed_admin_email: str = "admin@acme.com"
    seed_admin_password: str = "ChangeMe123!"

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
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
