"""Who completed an asset review.

``asset_reviews.reviewer`` is the name planned when the review was scheduled. The person
who actually completed it was recorded only in the activity trail, so the review record —
the evidence an auditor samples — did not say who did the work. ``completed_by`` keeps
their name as it was at the time; ``completed_by_id`` links the account. The DDL is shared
with the create_all boot path (``schema_patches.asset_review_completion_ddl_statements``)
and is idempotent.

Revision ID: 0043_asset_review_completed_by
Revises: 0042_vuln_risk_acceptance
Create Date: 2026-09-27
"""
from __future__ import annotations

from alembic import op

from app.db.schema_patches import asset_review_completion_ddl_statements

revision = "0043_asset_review_completed_by"
down_revision = "0042_vuln_risk_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in asset_review_completion_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE asset_reviews DROP CONSTRAINT IF EXISTS fk_asset_reviews_completed_by_id")
    op.execute("ALTER TABLE asset_reviews DROP COLUMN IF EXISTS completed_by_id")
    op.execute("ALTER TABLE asset_reviews DROP COLUMN IF EXISTS completed_by")
