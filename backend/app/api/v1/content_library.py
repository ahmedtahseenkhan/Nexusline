"""Framework Content Library — the browsable face of the built-in framework library.

One source of truth: :data:`app.services.framework_library.TEMPLATES`. This module used
to carry its own six shallow packs (ISO 27001 Annex A only, a 28-row NIST CSF, a 12-row
PCI DSS…), which meant the same standard was installable twice — once here, once through
``/framework-templates`` on the Compliance page — under two different names and depths.
Both endpoints now list and install the same templates through
:func:`framework_library.install_template`, so "installed" means the same thing
everywhere and a standard can exist only once per tenant.

Reuses the compliance permission keys: ``compliance:read`` (browse) and
``compliance:write`` (install). Installed frameworks then appear in the Compliance module.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status

from app.core.deps import CurrentUser, DbSession, require
from app.schemas.content_library import (
    ContentPackSummary,
    InstallResult,
    InstalledPack,
)
from app.services.framework_library import (
    TEMPLATES,
    install_template,
    installed_template_frameworks,
    installed_template_keys,
)

router = APIRouter(tags=["content-library"])

#: Library-grid grouping per template key; anything unlisted falls back to "Compliance".
_DOMAINS: dict[str, str] = {
    "iso-27001-2022": "Information Security",
    "iso-27005-2022": "Risk Management",
    "iso-31000-2018": "Risk Management",
    "iso-42001-2023": "AI Governance",
    "soc-2-2017": "Assurance",
    "nist-csf-2.0": "Cybersecurity",
    "pci-dss-4.0": "Payment Card Security",
    "gdpr": "Privacy",
    "hipaa-security-privacy": "Privacy",
    "cis-controls-v8": "Cybersecurity",
    "nist-800-53-r5": "Information Security",
    "sbp-etgrm": "Technology Governance",
    "sbp-cybersecurity": "Cybersecurity",
    "sbp-outsourcing": "Third-Party Risk",
    "sbp-bcp": "Business Continuity",
    "basel-operational-risk": "Operational Risk",
    "shariah-governance": "Shariah Governance",
}


def _summary(key: str, installed: dict[str, uuid.UUID]) -> ContentPackSummary:
    tpl = TEMPLATES[key]
    return ContentPackSummary(
        id=key,
        name=tpl["name"],
        standard=tpl["name"],
        description=tpl.get("description", ""),
        domain=_DOMAINS.get(key, "Compliance"),
        requirement_count=len(tpl["requirements"]),
        installed=key in installed,
        framework_id=installed.get(key),
    )


@router.get(
    "/content-library",
    response_model=list[ContentPackSummary],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_packs(db: DbSession) -> list[ContentPackSummary]:
    """List every installable framework, flagging which are already installed."""
    installed = await installed_template_frameworks(db)
    return [_summary(key, installed) for key in TEMPLATES]


@router.get(
    "/content-library/installed",
    response_model=list[InstalledPack],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_installed(db: DbSession) -> list[InstalledPack]:
    """List the frameworks from the library that already exist for this tenant."""
    installed = await installed_template_keys(db)
    return [InstalledPack(id=key, name=TEMPLATES[key]["name"]) for key in installed]


@router.post(
    "/content-library/{pack_id}/install",
    response_model=InstallResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require("compliance:write"))],
)
async def install_pack(pack_id: str, db: DbSession, user: CurrentUser) -> InstallResult:
    """Create a Framework and all of its Requirements for this tenant."""
    fw = await install_template(db, user, pack_id)
    return InstallResult(
        framework_id=fw.id,
        name=fw.name,
        requirement_count=len(TEMPLATES[pack_id]["requirements"]),
    )
