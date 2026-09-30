"""Asset tier, PCI DSS scope and the asset-based risk rating method.

An asset carries its service tier (1 = most critical) and where it sits against the PCI
DSS scope. ``risk_settings.scoring_method`` lets an organisation rate its register the
ISO/IEC 27005 asset-based way — likelihood x impact times the value of the asset at risk —
with ``business_impact_bands`` holding the thresholds that business impact is rated on.
The DDL is shared with the create_all boot path
(``schema_patches.asset_based_risk_ddl_statements``) and is idempotent.

Revision ID: 0044_asset_based_risk
Revises: 0043_asset_review_completed_by
Create Date: 2026-09-30
"""
from __future__ import annotations

from alembic import op

from app.db.schema_patches import asset_based_risk_ddl_statements

revision = "0044_asset_based_risk"
down_revision = "0043_asset_review_completed_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in asset_based_risk_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE risk_settings DROP COLUMN IF EXISTS business_impact_bands")
    op.execute("ALTER TABLE risk_settings DROP COLUMN IF EXISTS scoring_method")
    op.execute("DROP INDEX IF EXISTS ix_assets_tier")
    op.execute("ALTER TABLE assets DROP COLUMN IF EXISTS pci_scope")
    op.execute("ALTER TABLE assets DROP COLUMN IF EXISTS tier")
