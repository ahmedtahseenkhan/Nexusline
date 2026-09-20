"""Phase 5 schema for the record rules (decisions 6 and 9).

Decision 6 (approval before attestation) reads ``workflow_status``, which every record
type already carries, so it needs no column. Decision 9 — the attestation is the record
owner's own certification — adds three to ``attestations``:

* ``confirmation_required`` — this attestation only counts once a second person confirms
  it (key controls, critical / high residual risks, material outsourcing, policies).
  Rows written before the decision default to false, so nothing becomes retrospectively
  incomplete.
* ``on_behalf_of_id`` / ``on_behalf_of_name`` — when someone other than the owner signs,
  whose certification it stands in for.
"""
from __future__ import annotations

TABLES: tuple[str, ...] = ()


def ddl_statements() -> list[str]:
    return [
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS confirmation_required "
        "BOOLEAN DEFAULT FALSE NOT NULL",
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS on_behalf_of_id UUID",
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS on_behalf_of_name "
        "VARCHAR(255) DEFAULT '' NOT NULL",
        # The second-signature queues (My Work, the record page) read exactly this slice.
        "CREATE INDEX IF NOT EXISTS ix_attestations_awaiting_confirmation "
        "ON attestations (tenant_id, attested_at) "
        "WHERE confirmation_required AND confirmed_by_id IS NULL",
    ]
