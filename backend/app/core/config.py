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
