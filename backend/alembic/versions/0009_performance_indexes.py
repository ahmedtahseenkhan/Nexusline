"""Performance indexes: notification-scan date columns + register created_at sort.

At bank-scale data volumes two access patterns dominate and were unindexed:

  1. The notification scanner (``services/notifications.py``) runs on every
     ``GET /notifications`` poll and now filters each module to only its
     alert-worthy rows in SQL — ``WHERE deleted = false AND <date> < today``.
     Those date columns (review/audit/test/due/deadline dates) get a btree so
     the poll is an index range-scan instead of a sequential scan per table.

  2. Every register list page sorts by ``created_at`` by default and paginates.
     The high-traffic register tables get a ``created_at`` index.

Index names match SQLAlchemy's ``index=True`` default (``ix_<table>_<column>``),
so this migration and the ``create_all`` boot path converge on one schema — the
same source-of-truth pattern used by the asset-split DDL in 0008. Every statement
is ``CREATE INDEX IF NOT EXISTS`` / ``DROP INDEX IF EXISTS``, so it is safe on
fresh or existing databases and can be re-run.

Revision ID: 0009_performance_indexes
Revises: 0008_banking_productionization
Create Date: 2026-07-12
"""
from __future__ import annotations

from alembic import op

revision = "0009_performance_indexes"
down_revision = "0008_banking_productionization"
branch_labels = None
depends_on = None

# (table, column) — date columns filtered by the polled notification scan.
_DATE_INDEXES = [
    ("risks", "next_review_date"),
    ("controls", "next_audit_date"),
    ("controls", "next_maintenance_date"),
    ("exceptions", "expires_at"),
    ("goals", "next_audit_date"),
    ("continuity_plans", "next_test_date"),
    ("access_reviews", "due_date"),
    ("policies", "next_review_date"),
    ("awareness_programs", "next_due_date"),
    ("projects", "deadline"),
    ("audit_findings", "due_date"),
    ("audit_engagements", "planned_end"),
    ("shariah_findings", "due_date"),
    ("rcsa_assessments", "due_date"),
    ("suspicious_activity_reports", "deadline"),
    ("regulatory_reports", "deadline"),
]

# High-traffic register tables sorted by created_at on their list pages.
_CREATED_AT_TABLES = [
    "risks", "controls", "assets", "incidents", "vendors", "issues",
    "policies", "projects", "exceptions", "processing_activities",
    "screening_cases", "suspicious_activity_reports", "fraud_cases",
    "model_inventory", "audit_findings",
]


def upgrade() -> None:
    for table, column in _DATE_INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column} ON {table} ({column})")
    for table in _CREATED_AT_TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_created_at ON {table} (created_at)")


def downgrade() -> None:
    for table, column in _DATE_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_{column}")
    for table in _CREATED_AT_TABLES:
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_created_at")
