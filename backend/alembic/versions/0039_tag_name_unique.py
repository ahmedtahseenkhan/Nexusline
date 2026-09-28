"""One tag per name per organisation, ignoring case and spacing.

The tag library allowed "KYC" and "kyc" side by side, so a record could carry both and
filters split between them. Duplicates are merged onto the oldest tag (assignments move
across), names are normalised, and a unique index on ``(tenant_id, lower(name))`` keeps
it that way. The statements are shared with the create_all boot path
(``schema_patches.tag_name_unique_statements``) and are idempotent.

Revision ID: 0039_tag_name_unique
Revises: 0038_sar_audit_entity_type
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

from app.db.schema_patches import tag_name_unique_statements

revision = "0039_tag_name_unique"
down_revision = "0038_sar_audit_entity_type"
branch_labels = None
depends_on = None

_TABLES = ("tags", "entity_tags")


def upgrade() -> None:
    # Row-level security is FORCEd and a migration has no tenant set; lift it for the
    # owner while duplicates merge across every tenant.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    for statement in tag_name_unique_statements():
        op.execute(statement)
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_tag_tenant_lower_name")
