"""Schemas for the Framework Content Library — preloaded, installable framework packs.

A "pack" is a curated standard from ``app.services.framework_library.TEMPLATES`` — the
same registry behind ``/framework-templates``. Installing one materialises a real
``Framework`` + ``Requirement`` rows for the tenant via the existing compliance models.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel


class ContentPackSummary(BaseModel):
    """One installable pack, as shown in the library grid."""

    id: str
    name: str
    standard: str
    description: str
    domain: str
    requirement_count: int
    installed: bool = False


class InstallResult(BaseModel):
    """Returned after a pack is installed into the tenant."""

    framework_id: uuid.UUID
    name: str
    requirement_count: int


class InstalledPack(BaseModel):
    """A pack that already exists as a Framework for this tenant."""

    id: str
    name: str
