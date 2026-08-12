"""Configurable risk matrix and control-driven residual suggestion.

Three changes, all additive:

* ``risk_settings.matrix_size`` — the likelihood x impact scale (3..6) a bank baselines
  its register on. Severity bands are derived from it, so the 5x5 default reproduces the
  previously hard-coded bands exactly.
* ``risk_matrix_levels`` / ``residual_policies`` — new tables holding the bank's own
  wording for each rung of the scale, and how much residual credit a control earns per
  effectiveness rating.
* ``risks.suggested_residual_*`` and the residual sign-off trail — the engine's proposal
  and the owner's acceptance are stored separately, so a suggestion never masquerades as
  an assessed residual.

The 1..5 check constraints on ``risks`` are widened to 1..6, the widest scale any tenant
may configure; the tenant's own ``matrix_size`` is enforced in the API layer because a
check constraint cannot vary per RLS tenant.

Column additions and constraint changes live in ``app.db.schema_patches`` so this
migration and the ``create_all`` boot path apply exactly the same DDL.

Revision ID: 0017_risk_methodology
Revises: 0016_import_profiles
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata (incl. the new tables)
from app.core.database import Base
from app.db.rls import rls_ddl_statements
from app.db.schema_patches import risk_methodology_ddl_statements

revision = "0017_risk_methodology"
down_revision = "0016_import_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. new columns on the pre-existing risks / risk_settings tables, plus the widened
    #    scale constraints. create_all cannot ALTER, so these come first.
    for statement in risk_methodology_ddl_statements():
        op.execute(statement)

    # 2. risk_matrix_levels + residual_policies.
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)

    # 3. tenant isolation for the new tables (idempotent across all tables).
    for statement in rls_ddl_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS risk_matrix_levels")
    op.execute("DROP TABLE IF EXISTS residual_policies")
    for column in (
        "suggested_residual_likelihood",
        "suggested_residual_impact",
        "suggested_residual_rationale",
        "residual_accepted_by",
        "residual_accepted_at",
        "residual_override_reason",
    ):
        op.execute(f"ALTER TABLE risks DROP COLUMN IF EXISTS {column}")
    op.execute("ALTER TABLE risk_settings DROP COLUMN IF EXISTS matrix_size")
    # Restore the original 1..5 scale checks. Any risk already scored 6 would block this,
    # which is the correct outcome: the data no longer fits the narrower schema.
    for name, expression in (
        ("ck_risk_inh_likelihood", "inherent_likelihood BETWEEN 1 AND 5"),
        ("ck_risk_inh_impact", "inherent_impact BETWEEN 1 AND 5"),
        ("ck_risk_res_likelihood", "residual_likelihood IS NULL OR residual_likelihood BETWEEN 1 AND 5"),
        ("ck_risk_res_impact", "residual_impact IS NULL OR residual_impact BETWEEN 1 AND 5"),
    ):
        op.execute(f"ALTER TABLE risks DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE risks ADD CONSTRAINT {name} CHECK ({expression})")
