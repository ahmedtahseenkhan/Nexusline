"""Give IT assets and information assets their own custom fields.

Both registers are rows of ``assets`` and used to share one custom-field key,
``asset`` — a field added for IT assets showed up on every information asset too.
Each ``asset`` field is copied to ``it_asset`` and ``information_asset``; every saved
value moves to the copy matching its asset's class; the shared field is then removed
(its values cascade). An organisation can delete whichever copy it does not need.

Revision ID: 0037_split_asset_custom_fields
Revises: 0036_mfa_enforcement_level
Create Date: 2026-09-24
"""
from __future__ import annotations

from alembic import op

revision = "0037_split_asset_custom_fields"
down_revision = "0036_mfa_enforcement_level"
branch_labels = None
depends_on = None

_TABLES = ("custom_fields", "custom_field_values")


def _rls(force: bool) -> None:
    # Row-level security is FORCEd on these tables and a migration has no tenant set;
    # lift it for the table owner while the rows move across every tenant.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} {'' if force else 'NO '}FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rls(False)
    op.execute(
        """
        CREATE TEMP TABLE cf_asset_split ON COMMIT DROP AS
        SELECT f.id AS old_id, k.model, gen_random_uuid() AS new_id
        FROM custom_fields f
        CROSS JOIN (VALUES ('it_asset'), ('information_asset')) AS k(model)
        WHERE f.model = 'asset'
        """
    )
    op.execute(
        """
        INSERT INTO custom_fields
            (id, tenant_id, model, label, field_type, options, required, help_text,
             order_index, enabled, created_at, updated_at)
        SELECT s.new_id, f.tenant_id, s.model, f.label, f.field_type, f.options,
               f.required, f.help_text, f.order_index, f.enabled, f.created_at, now()
        FROM cf_asset_split s JOIN custom_fields f ON f.id = s.old_id
        """
    )
    op.execute(
        """
        INSERT INTO custom_field_values
            (id, tenant_id, custom_field_id, entity_id, value, created_at, updated_at)
        SELECT gen_random_uuid(), v.tenant_id, s.new_id, v.entity_id, v.value,
               v.created_at, v.updated_at
        FROM custom_field_values v
        JOIN assets a ON a.id = v.entity_id
        JOIN cf_asset_split s ON s.old_id = v.custom_field_id AND s.model = a.asset_class::text
        """
    )
    op.execute("DELETE FROM custom_fields WHERE model = 'asset'")
    _rls(True)


def downgrade() -> None:
    # Merge back onto the IT-asset copy; information-asset copies with the same label
    # hand their values to it and are dropped.
    _rls(False)
    op.execute(
        """
        UPDATE custom_field_values v SET custom_field_id = it.id
        FROM custom_fields info
        JOIN custom_fields it
          ON it.tenant_id = info.tenant_id AND it.model = 'it_asset' AND it.label = info.label
        WHERE info.model = 'information_asset' AND v.custom_field_id = info.id
        """
    )
    op.execute(
        """
        DELETE FROM custom_fields info USING custom_fields it
        WHERE info.model = 'information_asset' AND it.model = 'it_asset'
          AND it.tenant_id = info.tenant_id AND it.label = info.label
        """
    )
    op.execute("UPDATE custom_fields SET model = 'asset' WHERE model IN ('it_asset', 'information_asset')")
    _rls(True)
