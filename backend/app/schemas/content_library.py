"""Schemas for the Framework Content Library — preloaded, installable framework packs.

A "pack" is a curated standard from ``app.services.framework_library.TEMPLATES`` — the
same registry behind ``/framework-templates``. Installing one materialises a real
``Framework`` + ``Requirement`` rows for the tenant via the existing compliance models.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


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
    #: The name the installed copy carries — differs from ``name`` for a legacy pack.
    installed_as: str | None = None
    #: The installed copy is a legacy pack or is missing template clauses: installing
    #: again upgrades it in place (statuses and links kept) instead of refusing.
    upgrade_available: bool = False
    #: Template clauses the installed copy lacks.
    requirements_missing: int = 0
    #: compliance | maturity | guidance — maturity frameworks are self-assessed and stay
    #: out of the compliance percentage.
    kind: str = "compliance"


class InstallResult(BaseModel):
    """Returned after a pack is installed into the tenant."""

    framework_id: uuid.UUID
    name: str
    #: Requirements the framework has from the template after this call.
    requirement_count: int
    #: Requirements this call created (all on install, the missing ones on upgrade).
    requirements_added: int = 0
    controls_created: int = 0
    #: Template controls that already existed in the catalogue, matched by reference.
    controls_linked: int = 0
    #: Requirement ↔ control links written by this call.
    requirements_linked: int = 0
    #: An existing legacy or shallow copy was upgraded in place rather than a new one made.
    upgraded: bool = False
    previous_name: str | None = None


class InstalledPack(BaseModel):
    """A pack that already exists as a Framework for this tenant."""

    id: str
    name: str


# ------------------------------------------------------------ controls-pack preview
class PackControlRef(BaseModel):
    """An existing catalogue control a clause would be linked to."""

    id: uuid.UUID
    reference: str = ""
    name: str = ""


class PackPreviewRow(BaseModel):
    """One control-type clause of a pack and what installing it would do."""

    #: The clause's reference as the framework spells it (``A.8.5``; ``6.3`` for CIS).
    requirement_ref: str
    #: The reference the control carries in the Control Catalogue (``CIS 6.3``).
    catalogue_reference: str
    title: str
    #: create | match-by-reference | match-by-name | map-to-existing (a decision).
    action: str
    #: The existing control the clause lands on; None when a new one is created.
    control: PackControlRef | None = None
    #: The same-named existing control, when one exists — kept even when a decision
    #: chose "create", so the review can offer to reuse it again.
    name_match: PackControlRef | None = None


class PackPreview(BaseModel):
    pack_id: str
    name: str
    installed: bool = False
    framework_id: uuid.UUID | None = None
    #: Rows that would create a new control.
    create: int = 0
    #: Rows that would reuse an existing control (reference + name + decision matches).
    reuse: int = 0
    match_reference: int = 0
    match_name: int = 0
    rows: list[PackPreviewRow] = Field(default_factory=list)


class PackInstallBody(BaseModel):
    """Per-clause overrides for a controls-pack install, keyed by the clause's reference
    as the framework spells it: ``"create"`` makes a new control even when a same-named
    one exists; a control id links the clause to that control instead. A clause matched
    by reference always keeps its control."""

    decisions: dict[str, str] = Field(default_factory=dict)
