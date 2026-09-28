"""File STR/SAR history under the record type everything else uses.

The AML API wrote an STR/SAR's audit entries as ``sar`` while approvals, comments,
custom fields, the record view's trail and the Activity Log filter all know the record
as ``suspicious_activity_report`` — so a SAR's own history never showed up against it.
The API now writes the full type; this moves the entries written before. Idempotent:
a second run finds nothing left to rename.

Revision ID: 0038_sar_audit_entity_type
Revises: 0037_split_asset_custom_fields
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

revision = "0038_sar_audit_entity_type"
down_revision = "0037_split_asset_custom_fields"
branch_labels = None
depends_on = None


def _rls(force: bool) -> None:
    # Row-level security is FORCEd on audit_logs and a migration has no tenant set;
    # lift it for the table owner while every tenant's rows are renamed.
    op.execute(f"ALTER TABLE audit_logs {'' if force else 'NO '}FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rls(False)
    op.execute(
        "UPDATE audit_logs SET entity_type = 'suspicious_activity_report' WHERE entity_type = 'sar'"
    )
    _rls(True)


def downgrade() -> None:
    # Not reversed: "sar" was never a record type anything else could look up, and the
    # renamed rows cannot be told apart from entries other services wrote under the full
    # type.
    pass
