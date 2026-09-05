"""Link risks to business units and processes — segment-scoped risk assessment.

A bank does not convene a risk workshop around an asset; it convenes one around a
segment — "Digital Banking", "Trade Finance", "Branch Operations" — and the assets are
what that segment happens to run on. Until now the register could be filtered by
category and by asset but never by segment, so the one cut the business actually asks
for was the one cut the tool could not produce.

Two join tables, both many-to-many. A single owning unit would be simpler, but a control
failure like "MFA not enforced" genuinely belongs to Retail and Corporate at once, and
forcing a choice would either duplicate the risk or hide it from one of them.

Neither table carries a ``tenant_id`` and neither takes an RLS policy, which is how
every other link table in the schema works: both endpoints are tenant-scoped, so a row
joining them is unreachable across tenants regardless.

Revision ID: 0025_risk_segment_scoping
Revises: 0024_risk_scale_to_ten
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. the new join tables)
from app.core.database import Base

revision = "0025_risk_segment_scoping"
down_revision = "0024_risk_scale_to_ten"
branch_labels = None
depends_on = None

_TABLES = ("risk_business_units", "risk_processes")


def upgrade() -> None:
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables[name] for name in _TABLES],
        checkfirst=True,
    )
    # Their segment-side indexes are declared on the Table objects, so create_all
    # builds them here and on the boot path alike.


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
