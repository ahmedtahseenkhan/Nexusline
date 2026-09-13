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

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, DbSession, require
from app.schemas.content_library import (
    ContentPackSummary,
    InstallResult,
    InstalledPack,
    PackControlRef,
    PackInstallBody,
    PackPreview,
    PackPreviewRow,
)
from app.services import control_mapping
from app.services.framework_library import (
    CREATE,
    MATCH_NAME,
    MATCH_REFERENCE,
    TEMPLATES,
    PackDecisionError,
    TemplateInstall,
    controls_present,
    install_controls_pack,
    install_template,
    installed_framework_for,
    installed_template_keys,
    preview_controls_pack,
    template_installs,
    template_kind,
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


def _summary(
    key: str,
    installed: dict[str, TemplateInstall],
    present: dict[str, tuple[int, int]] | None = None,
) -> ContentPackSummary:
    tpl = TEMPLATES[key]
    inst = installed.get(key)
    return ContentPackSummary(
        id=key,
        name=tpl["name"],
        standard=tpl["name"],
        description=tpl.get("description", ""),
        domain=_DOMAINS.get(key, "Compliance"),
        requirement_count=len(tpl["requirements"]),
        installed=inst is not None,
        framework_id=inst.framework_id if inst else None,
        is_control_framework=control_mapping.is_control_framework(key),
        control_count=len(control_mapping.control_requirements(tpl, key)),
        controls_present=(present or {}).get(key, (0, 0))[0],
        controls_total=(present or {}).get(key, (0, 0))[1],
        installed_as=inst.name if inst else None,
        upgrade_available=bool(inst and inst.upgrade_available),
        requirements_missing=inst.missing if inst else 0,
        kind=template_kind(key),
    )


@router.get(
    "/content-library",
    response_model=list[ContentPackSummary],
    dependencies=[Depends(require("compliance:read"))],
)
async def list_packs(db: DbSession) -> list[ContentPackSummary]:
    """List every installable framework, flagging which are already installed — and
    which installed copies are a legacy pack or shallow, so can be upgraded."""
    installed = await template_installs(db)
    # For installed control frameworks, whether the controls pack is there yet — an
    # install that predates the pack shows "Create controls" instead of "done".
    present: dict[str, tuple[int, int]] = {}
    for key in TEMPLATES:
        if key in installed and control_mapping.is_control_framework(key):
            fw = await installed_framework_for(db, key)
            if fw is not None:
                present[key] = await controls_present(db, fw, key)
    return [_summary(key, installed, present) for key in TEMPLATES]


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
async def install_pack(
    pack_id: str, db: DbSession, user: CurrentUser,
    create_controls: bool | None = None,
    body: PackInstallBody | None = None,
) -> InstallResult:
    """Create a Framework and all of its Requirements for this tenant — and, for a
    control framework, its Control Catalogue entries (``create_controls=false`` to skip).

    When the standard is already installed under a legacy pack name, or with clauses
    missing, it is upgraded in place (``upgraded: true``, ``requirements_added``);
    existing requirements, statuses and links are kept. 409 only when it is complete.

    Existing controls are reused by reference, then by normalised name; the optional
    body's ``decisions`` override the name matches per clause (see the preview).
    """
    outcome = await install_template(
        db, user, pack_id, create_controls=create_controls,
        decisions=body.decisions if body else None,
    )
    fw = outcome.framework
    return InstallResult(
        framework_id=fw.id,
        name=fw.name,
        requirement_count=outcome.requirements,
        requirements_added=outcome.requirements_added,
        controls_created=outcome.controls_created,
        controls_linked=outcome.controls_linked,
        requirements_linked=outcome.requirements_linked,
        upgraded=outcome.upgraded,
        previous_name=outcome.previous_name,
    )


@router.post(
    "/content-library/{pack_id}/install-controls",
    response_model=InstallResult,
    dependencies=[Depends(require("compliance:write"))],
)
async def install_controls(
    pack_id: str, db: DbSession, user: CurrentUser, body: PackInstallBody | None = None,
) -> InstallResult:
    """Create the Control Catalogue entries for a framework that is *already* installed.

    The upgrade path: a framework installed before the controls pack existed (or before
    it became a control framework, as the SBP ETGRM, Outsourcing and BCP frameworks did)
    has its clauses but nothing behind them. Idempotent — controls that already exist by
    reference or by normalised name are linked, not recreated, so it is safe to run
    twice. ``decisions`` overrides the name matches per clause.
    """
    _check_control_pack(pack_id)
    fw = await installed_framework_for(db, pack_id)
    if fw is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Install the framework first")
    pack = await install_controls_pack(
        db, user, fw, pack_id, decisions=body.decisions if body else None,
    )
    from app.services import audit
    await audit.record(
        db, actor=user, action="update", entity_type="framework", entity_id=fw.id,
        summary=(
            f"Created controls pack for {fw.name}: {pack.created} controls created, "
            f"{pack.linked} matched to existing controls, {pack.requirements_linked} requirement links"
        ),
    )
    return InstallResult(
        framework_id=fw.id, name=fw.name, requirement_count=len(TEMPLATES[pack_id]["requirements"]),
        controls_created=pack.created, controls_linked=pack.linked,
        requirements_linked=pack.requirements_linked,
    )


def _check_control_pack(pack_id: str) -> None:
    if pack_id not in TEMPLATES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown framework template")
    if not control_mapping.is_control_framework(pack_id):
        raise HTTPException(status_code=422, detail="This framework has management clauses, not controls")


def _ref(c) -> PackControlRef | None:
    return PackControlRef(id=c.id, reference=c.reference, name=c.name) if c is not None else None


@router.post(
    "/content-library/{pack_id}/install-controls/preview",
    response_model=PackPreview,
    dependencies=[Depends(require("compliance:read"))],
)
async def preview_install_controls(
    pack_id: str, db: DbSession, body: PackInstallBody | None = None,
) -> PackPreview:
    """What installing this framework's controls would do to the Control Catalogue,
    clause by clause, without writing anything: **create** a control, reuse the one
    with the same reference (**match-by-reference**), or reuse one with the same
    normalised name (**match-by-name**). Send ``decisions`` to see the plan with
    overrides applied; send the same ``decisions`` to ``install`` /
    ``install-controls`` and that is exactly what is written.
    """
    _check_control_pack(pack_id)
    try:
        steps = await preview_controls_pack(db, pack_id, body.decisions if body else None)
    except PackDecisionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    installed = await installed_framework_for(db, pack_id)
    rows = [
        PackPreviewRow(
            requirement_ref=s.requirement_ref,
            catalogue_reference=s.catalogue_reference,
            title=s.title,
            action=s.action,
            control=_ref(s.control),
            name_match=_ref(s.name_match),
        )
        for s in steps
    ]
    created = sum(1 for r in rows if r.action == CREATE)
    return PackPreview(
        pack_id=pack_id,
        name=TEMPLATES[pack_id]["name"],
        installed=installed is not None,
        framework_id=installed.id if installed is not None else None,
        create=created,
        reuse=len(rows) - created,
        match_reference=sum(1 for r in rows if r.action == MATCH_REFERENCE),
        match_name=sum(1 for r in rows if r.action == MATCH_NAME),
        rows=rows,
    )
