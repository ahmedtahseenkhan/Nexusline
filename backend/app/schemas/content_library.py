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
    #: The tenant's Framework this pack was installed as — lets the library link straight
    #: to it in Compliance. None until installed.
    framework_id: uuid.UUID | None = None
    #: A catalogue of controls (ISO 27001 Annex A, CIS, ...) rather than management
    #: clauses — installing it also populates the Control Catalogue.
    is_control_framework: bool = False
    control_count: int = 0
    #: For an installed control framework: how many of *its own* control-type clauses
    #: have a control behind them, out of how many it has. Present below total means
    #: the controls pack has not been created for it.
    controls_present: int = 0
    controls_total: int = 0


class InstallResult(BaseModel):
    """Returned after a pack is installed into the tenant."""

    framework_id: uuid.UUID
    name: str
    requirement_count: int
    controls_created: int = 0
    controls_linked: int = 0


class InstalledPack(BaseModel):
    """A pack that already exists as a Framework for this tenant."""

    id: str
    name: str
