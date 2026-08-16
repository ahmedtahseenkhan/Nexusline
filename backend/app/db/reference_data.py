"""Baseline lookup data every tenant needs from day one.

Dropdowns like *Media type* and *Vendor type* read tenant-scoped lookup tables. Those
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

#: The default classification scheme: three CIA axes, each with the same graded values.
#: A tenant with its own methodology edits or replaces the axes under Settings → Lookups.
DEFAULT_CLASSIFICATION_VALUES: tuple[tuple[str, float, str], ...] = (
    ("Public", 1.0, "Publicly shareable, no harm if disclosed"),
    ("Internal", 2.0, "Internal use only"),
    ("Confidential", 3.0, "Limited distribution, business impact if disclosed"),
    ("Restricted", 4.0, "Strictly need-to-know, severe impact if disclosed"),
)
DEFAULT_CLASSIFICATION_AXES: tuple[str, ...] = ("Confidentiality", "Integrity", "Availability")


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
        for vname, value, criteria in DEFAULT_CLASSIFICATION_VALUES:
            db.add(
                AssetClassification(
                    tenant_id=tenant_id, type_id=ct.id, name=vname, value=value, criteria=criteria
                )
            )
            added += 1
        added += 1

    if added:
        await db.flush()
    return added


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
