"""Database backup via ``pg_dump`` (custom-format archive).

Backups run as the Postgres owner role (full DDL+data) and land in
``settings.backup_dir``. Restore is intentionally *not* an API action (too
destructive to expose); the deployment runbook documents ``pg_restore``. Suitable
for the on-prem model where the bank owns the box and schedules off-host copies.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings


def _backup_root() -> Path:
    root = Path(settings.backup_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def list_backups() -> list[dict]:
    root = _backup_root()
    items = []
    for p in sorted(root.glob("*.dump"), reverse=True):
        st = p.stat()
        items.append({
            "filename": p.name,
            "size_bytes": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return items


async def create_backup() -> dict:
    """Run pg_dump into a timestamped custom-format archive. Returns its metadata."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out = _backup_root() / f"nexusline-{stamp}.dump"

    cmd = [
        "pg_dump",
        "-h", settings.postgres_host,
        "-p", str(settings.postgres_port),
        "-U", settings.postgres_user,
        "-d", settings.postgres_db,
        "-F", "c",             # custom format (compressed, restorable with pg_restore)
        "-f", str(out),
    ]
    env = {**os.environ, "PGPASSWORD": settings.postgres_password}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
    except FileNotFoundError as exc:
        raise RuntimeError("pg_dump not found on the server PATH") from exc

    if proc.returncode != 0:
        out.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed: {stderr.decode(errors='replace')[:500]}")

    st = out.stat()
    return {
        "filename": out.name,
        "size_bytes": st.st_size,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "path": str(out),
    }
