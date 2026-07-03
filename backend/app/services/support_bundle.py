"""Redacted support-bundle generator.

Produces a single zip a customer can send to support **without granting remote
access** — the key enabler for restricted/air-gapped bank environments. All secrets
are masked; the bundle carries version, deployment/feature state, health, license
status, sanitized config, migration list and (optionally) table row counts.
"""
from __future__ import annotations

import io
import json
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.services import license as lic

_SECRET_HINTS = ("password", "secret", "key", "token", "bind_password")


def _redact_config() -> dict:
    data = settings.model_dump()
    out: dict = {}
    for k, v in data.items():
        if any(h in k.lower() for h in _SECRET_HINTS) and v:
            out[k] = "***REDACTED***"
        else:
            out[k] = v
    return out


def _migrations() -> list[str]:
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    if not versions.is_dir():
        return []
    return sorted(p.stem for p in versions.glob("*.py"))


def build_bundle(extra: dict | None = None) -> tuple[str, bytes]:
    """Return (filename, zip_bytes). ``extra`` may include db-derived context
    (e.g. table counts, requesting user) gathered by the caller."""
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")

    info = {
        "generated_at": now.isoformat(),
        "app_version": settings.app_version,
        "deployment_mode": settings.deployment_mode,
        "environment": settings.environment,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "license": lic.load_current().to_public(),
        "feature_flags": {
            "scheduler_enabled": settings.scheduler_enabled,
            "ldap_enabled": settings.ldap_enabled,
            "mfa_required": settings.mfa_required,
            "enforce_segregation_of_duties": settings.enforce_segregation_of_duties,
            "enforce_license": settings.enforce_license,
            "smtp_configured": bool(settings.smtp_host),
        },
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.json", json.dumps(info, indent=2, default=str))
        z.writestr("config.redacted.json", json.dumps(_redact_config(), indent=2, default=str))
        z.writestr("migrations.txt", "\n".join(_migrations()))
        if extra:
            z.writestr("context.json", json.dumps(extra, indent=2, default=str))
        z.writestr(
            "README.txt",
            "NexusLine support bundle\n"
            "All secrets are redacted. Send this file to support; no remote access is required.\n",
        )

    return f"nexusline-support-{stamp}.zip", buf.getvalue()
