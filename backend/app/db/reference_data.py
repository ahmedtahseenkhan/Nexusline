"""Baseline lookup data every tenant needs from day one.

Dropdowns like *Media type* and *Vendor type* read tenant-scoped lookup tables, and the
governed lists (``app.db.lookup_seed``) feed every category/regulator/country picker. Those
tables used to be filled only by the demo seeder, which runs for the very first org —
every org registered afterwards (and every install with ``SEED_DATA=false``) got empty
dropdowns with no way to fill them. This module owns the built-in vocabulary and two
entry points:

* :func:`ensure_reference_data` — idempotent per tenant; called from
  ``create_organization`` so new orgs are complete, and reused by the demo seeder.
* :func:`reconcile_reference_data` — startup sweep over all tenants, so orgs created
  before this module existed are backfilled. Matches by name and only ever inserts,
  so a tenant's renames/deletions of *editable* entries are respected — except the
  non-editable built-in media types, which are the fixed taxonomy.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_session_tenant, tenant_session
from app.models.asset import (
    AssetClassification,
    AssetClassificationType,
    AssetLabel,
    AssetMediaType,
)
from app.models.tenant import Tenant
from app.models.vendor import VendorType

#: eramba's 8 built-in asset kinds. ``editable=False`` — deleting one would strand the
#: assets referencing it, so the API refuses (409) and this list can be re-asserted.
BUILTIN_MEDIA_TYPES: tuple[tuple[str, str], ...] = (
    ("Data Asset", "Information itself — records, datasets, documents"),
    ("Facilities", "Physical sites: data centres, branches, offices"),
    ("People", "Staff, roles and teams the process depends on"),
    ("Hardware", "Servers, endpoints, appliances, HSMs"),
    ("Software", "Applications, databases, operating systems"),
    ("IT Service", "Provided services: hosting, SaaS, managed services"),
    ("Network", "Network infrastructure and connectivity"),
    ("Financial", "Financial instruments and monetary assets"),
)

#: Starter third-party taxonomy for a bank. All editable — a tenant renames or prunes
#: freely; the backfill only re-adds a name that has never existed in the tenant.
DEFAULT_VENDOR_TYPES: tuple[tuple[str, str], ...] = (
    ("Cloud Provider", "Infrastructure / SaaS provider"),
    ("Data Processor", "Processes personal data on our behalf"),
    ("Software Vendor", "Licensed or bespoke software supplier"),
    ("Hardware Supplier", "Equipment and spare-parts supplier"),
    ("Payment Service Provider", "Switching, acquiring, card scheme or PSP"),
    ("Outsourced Service Provider", "Business process performed by a third party"),
    ("Consultant / Professional Services", "Advisory, audit and implementation partners"),
    ("Utility / Facility", "Power, telecom, premises and physical services"),
)

#: Information-asset handling labels (the classic 4-tier scheme), with the same colors
#: the demo seeder used so both paths produce identical data.
DEFAULT_ASSET_LABELS: tuple[tuple[str, str], ...] = (
    ("Public", "#15803d"),
    ("Internal", "#2563eb"),
    ("Confidential", "#b45309"),
    ("Restricted", "#b91c1c"),
)

#: The default classification scheme: three CIA axes, each graded 1..4 on its own terms.
#: Confidentiality is about disclosure, integrity about unauthorised or accidental change,
#: availability about how long the business can do without it — so each axis names its
#: grades and criteria for what it measures. The numeric values line up (1 = least
#: sensitive) so an asset's overall rating can still be the highest of the three.
#: A tenant with its own methodology edits or replaces the axes under Settings → Lookups.
CONFIDENTIALITY_VALUES: tuple[tuple[str, float, str], ...] = (
    ("Public", 1.0, "Publicly shareable, no harm if disclosed"),
    ("Internal", 2.0, "Internal use only"),
    ("Confidential", 3.0, "Limited distribution, business impact if disclosed"),
    ("Restricted", 4.0, "Strictly need-to-know, severe impact if disclosed"),
)
INTEGRITY_VALUES: tuple[tuple[str, float, str], ...] = (
    ("Low", 1.0, "Errors or unauthorised changes would have little business effect"),
    ("Moderate", 2.0, "Errors would cause rework or minor customer impact"),
    ("High", 3.0, "Errors would cause financial loss, misreporting or customer harm"),
    ("Critical", 4.0, "Errors would cause material loss, regulatory breach or fraud"),
)
AVAILABILITY_VALUES: tuple[tuple[str, float, str], ...] = (
    ("Standard", 1.0, "Can be unavailable for several days (recovery time over 72 hours)"),
    ("Important", 2.0, "Needed within a working day (recovery time up to 24 hours)"),
    ("Business-critical", 3.0, "Needed within hours (recovery time up to 4 hours)"),
    ("Mission-critical", 4.0, "Must stay up; any outage is immediately material (under 1 hour)"),
)
#: Kept for callers that predate per-axis values: the confidentiality grades.
DEFAULT_CLASSIFICATION_VALUES = CONFIDENTIALITY_VALUES
CLASSIFICATION_VALUES_BY_AXIS: dict[str, tuple[tuple[str, float, str], ...]] = {
    "Confidentiality": CONFIDENTIALITY_VALUES,
    "Integrity": INTEGRITY_VALUES,
    "Availability": AVAILABILITY_VALUES,
}
DEFAULT_CLASSIFICATION_AXES: tuple[str, ...] = tuple(CLASSIFICATION_VALUES_BY_AXIS)


async def ensure_reference_data(db: AsyncSession, tenant_id: UUID) -> int:
    """Insert whichever built-in lookup rows this tenant is missing. Idempotent by name.

    The session's RLS tenant GUC must already point at ``tenant_id`` (true inside
    ``create_organization`` and the reconcile loop below).
    """
    added = 0

    have = {
        (n or "").strip().lower()
        for n in (await db.scalars(select(AssetMediaType.name))).all()
    }
    for name, description in BUILTIN_MEDIA_TYPES:
        if name.lower() not in have:
            db.add(
                AssetMediaType(
                    tenant_id=tenant_id, name=name, description=description, editable=False
                )
            )
            added += 1

    have = {
        (n or "").strip().lower()
        for n in (await db.scalars(select(VendorType.name))).all()
    }
    for name, description in DEFAULT_VENDOR_TYPES:
        if name.lower() not in have:
            db.add(VendorType(tenant_id=tenant_id, name=name, description=description))
            added += 1

    have = {
        (n or "").strip().lower()
        for n in (await db.scalars(select(AssetLabel.name))).all()
    }
    for name, color in DEFAULT_ASSET_LABELS:
        if name.lower() not in have:
            db.add(AssetLabel(tenant_id=tenant_id, name=name, color=color))
            added += 1

    # Classification axes are seeded whole: values only accompany a newly created axis,
    # so a tenant that pruned or re-graded an existing axis never sees values resurrected.
    have = {
        (n or "").strip().lower()
        for n in (await db.scalars(select(AssetClassificationType.name))).all()
    }
    for axis in DEFAULT_CLASSIFICATION_AXES:
        if axis.lower() in have:
            continue
        ct = AssetClassificationType(
            tenant_id=tenant_id, name=axis, description=f"{axis} rating scale"
        )
        db.add(ct)
        await db.flush()
        for vname, value, criteria in CLASSIFICATION_VALUES_BY_AXIS[axis]:
            db.add(
                AssetClassification(
                    tenant_id=tenant_id, type_id=ct.id, name=vname, value=value, criteria=criteria
                )
            )
            added += 1
        added += 1

    # Governed lookup lists (risk category, regulator, country …): same insert-only
    # contract, matched on value or label so text-derived rows are never duplicated.
    from app.db.lookup_seed import ensure_lookup_defaults

    added += await ensure_lookup_defaults(db, tenant_id)
    added += await ensure_tiering_questionnaire(db, tenant_id)

    if added:
        await db.flush()
    return added


async def ensure_tiering_questionnaire(db: AsyncSession, tenant_id: UUID) -> int:
    """Seed the "Inherent risk tiering" questionnaire (services/vendor_tiering.py) if the
    tenant has no tiering questionnaire (by purpose) and none by that name. Insert-only:
    a tenant's edits to its questions or scores are never overwritten. The seed is
    published version 1 with ``purpose = vendor_tiering``, the tier bands and mandatory
    questions in one section. Returns rows added (the questionnaire counts as one)."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from app.models.assessment import (
        VERSION_PUBLISHED,
        Question,
        QuestionnaireSection,
        QuestionOption,
        Questionnaire,
    )
    from app.services import questionnaire_logic as ql
    from app.services.vendor_tiering import (
        TIER_BANDS,
        TIERING_PURPOSE,
        TIERING_QUESTIONNAIRE_DESCRIPTION,
        TIERING_QUESTIONNAIRE_NAME,
        TIERING_QUESTIONS,
    )

    have = {
        " ".join((n or "").split()).lower()
        for n in (await db.scalars(select(Questionnaire.name))).all()
    }
    if TIERING_QUESTIONNAIRE_NAME.lower() in have:
        return 0
    purposes = set((await db.scalars(select(Questionnaire.purpose))).all())
    if TIERING_PURPOSE in purposes:
        return 0
    qid, sid = _uuid.uuid4(), _uuid.uuid4()
    q = Questionnaire(
        id=qid, family_id=qid, version=1, status=VERSION_PUBLISHED, purpose=TIERING_PURPOSE,
        tenant_id=tenant_id, name=TIERING_QUESTIONNAIRE_NAME, description=TIERING_QUESTIONNAIRE_DESCRIPTION,
        bands=[{"label": tier.capitalize(), "min_pct": minimum, "rating": tier} for minimum, tier in TIER_BANDS],
        published_at=datetime.now(timezone.utc),
        change_note="Seeded with the platform.",
    )
    section = QuestionnaireSection(
        id=sid, tenant_id=tenant_id, questionnaire_id=qid, key="tiering", title="Inherent risk",
        description="Answer every question for the relationship as it stands, before the provider's own controls.",
        order_index=0, conditions={},
    )
    q.sections = [section]
    q.questions = [
        Question(
            tenant_id=tenant_id, text=text, guidance=guidance, order_index=i, section_id=sid,
            key=f"tier_{i + 1}_{ql.slug(text)[:24]}", qtype="single_choice", mandatory=True, weight=1.0,
            conditions={}, config={},
            options=[
                QuestionOption(tenant_id=tenant_id, label=label, score=score, order_index=j, value=f"s{int(score)}_{j}")
                for j, (label, score) in enumerate(options)
            ],
        )
        for i, (text, guidance, options) in enumerate(TIERING_QUESTIONS)
    ]
    db.add(q)
    await db.flush()
    return 1


async def reconcile_reference_data() -> int:
    """Backfill every existing tenant on startup. Insert-only; returns rows added.

    Same additive contract as ``reconcile_permissions``: a missing name is added once,
    nothing is ever updated or removed, so tenant edits survive every later startup.
    """
    added = 0
    async with tenant_session(None) as db:
        tenants = (await db.scalars(select(Tenant))).all()
        for tenant in tenants:
            await set_session_tenant(db, tenant.id)
            added += await ensure_reference_data(db, tenant.id)
        await db.flush()
    return added
