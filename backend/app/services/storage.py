"""Local binary object storage for uploaded files (attachments & evidence).

Files are written under ``settings.file_storage_dir`` partitioned by tenant, so a
tenant's blobs never share a directory with another's. Each stored object is keyed
by a random UUID plus a sanitized original filename, giving a stable, collision-free
relative key that is recorded on the :class:`~app.models.collab.StoredFile` row.

This is a filesystem backend by design (no external dependency). The public
surface — :func:`save_upload`, :func:`resolve_path`, :func:`delete_object` — is the
seam to swap in S3/GCS later without touching callers.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

_CHUNK = 1024 * 1024  # 1 MiB streaming chunks
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class StoredBlob:
    storage_key: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


def _root() -> Path:
    root = Path(settings.file_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(name: str) -> str:
    """Reduce an arbitrary client filename to a safe basename (no path parts)."""
    base = Path(name or "file").name
    cleaned = _SAFE.sub("_", base).strip("._") or "file"
    return cleaned[:120]


async def save_upload(tenant_id: uuid.UUID | str, upload: UploadFile) -> StoredBlob:
    """Persist an ``UploadFile`` to disk, enforcing the configured size cap.

    Streams in chunks so a large upload never fully materializes in memory, hashing
    as it goes. Raises 413 if the file exceeds ``max_upload_mb`` and cleans up the
    partial write.
    """
    limit = settings.max_upload_mb * 1024 * 1024
    safe = _safe_name(upload.filename or "file")
    key = f"{tenant_id}/{uuid.uuid4().hex}__{safe}"
    dest = _root() / key
    dest.parent.mkdir(parents=True, exist_ok=True)

    hasher = hashlib.sha256()
    size = 0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk = await upload.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds the {settings.max_upload_mb} MB limit",
                    )
                hasher.update(chunk)
                fh.write(chunk)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:  # noqa: BLE001 - never leave a partial file behind
        dest.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    return StoredBlob(
        storage_key=key,
        filename=safe,
        content_type=upload.content_type or "application/octet-stream",
        size_bytes=size,
        sha256=hasher.hexdigest(),
    )


def resolve_path(tenant_id: uuid.UUID | str, storage_key: str) -> Path:
    """Return the on-disk path for a stored key, guarding against traversal.

    The key must live under this tenant's partition and inside the storage root;
    anything else raises 404 rather than reading an unexpected file.
    """
    root = _root()
    path = (root / storage_key).resolve()
    tenant_root = (root / str(tenant_id)).resolve()
    if not str(path).startswith(str(tenant_root) + "/") or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return path


def delete_object(storage_key: str) -> None:
    """Best-effort removal of the on-disk blob (row deletion is the source of truth)."""
    try:
        (_root() / storage_key).unlink(missing_ok=True)
    except OSError:
        pass
