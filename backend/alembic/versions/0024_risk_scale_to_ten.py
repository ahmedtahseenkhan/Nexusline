"""Widen the configurable risk matrix ceiling from 6x6 to 10x10.

Banks arrive with a board-approved ERM matrix already in force, and a 1-10 likelihood /
impact scale is common enough in the local market that "re-score your whole register
onto our 1-5" is not an answer anyone accepts. The matrix has been per-tenant
configurable since 0017; only the ceiling moves here.

Nothing is rewritten. The severity bands are already expressed as fractions of the
maximum score, so a tenant left at 5x5 keeps byte-identical scores and bands; a tenant
that opts up to 10x10 gets 1-16 low, 17-36 medium, 37-56 high, 57-100 critical. The
check constraints are the only thing the database enforces, because a per-tenant
``matrix_size`` cannot be expressed as a check constraint under row-level security —
that stays in the API layer.

``risk_matrix_levels`` widens alongside ``risks``: a bank scoring on 1-10 that could not
write down what rungs 7-10 mean would have a scale but no methodology.

The DDL lives in ``app.db.schema_patches`` so this migration and the ``create_all`` boot
path apply exactly the same statements, and both read the ceiling from the single
``MAX_MATRIX_SIZE`` constant that the ORM and the Pydantic validators also use.

Revision ID: 0024_risk_scale_to_ten
Revises: 0023_fortnightly_and_plan_month
Create Date: 2026-09-04
"""
from __future__ import annotations

from alembic import op

import app.models  # noqa: F401 - registers all metadata
from app.db.schema_patches import risk_scale_constraint_statements

revision = "0024_risk_scale_to_ten"
down_revision = "0023_fortnightly_and_plan_month"
branch_labels = None
depends_on = None

# The ceiling this migration moved away from. Named here rather than imported so the
# downgrade keeps working after the constant moves again.
_PREVIOUS_CEILING = 6


def upgrade() -> None:
    for statement in risk_scale_constraint_statements():
        op.execute(statement)


def downgrade() -> None:
    """Return the checks to 1..6.

    Refused if any risk already scores above 6 — silently clamping would rewrite an
    assessor's judgement, and PostgreSQL will reject the constraint anyway. The error
    names the problem so an operator can re-score deliberately.
    """
    offending = op.get_bind().exec_driver_sql(
        "SELECT count(*) FROM risks WHERE inherent_likelihood > %s OR inherent_impact > %s "
        "OR residual_likelihood > %s OR residual_impact > %s"
        % ((_PREVIOUS_CEILING,) * 4)
    ).scalar()
    if offending:
        raise RuntimeError(
            f"{offending} risk(s) score above {_PREVIOUS_CEILING} and must be re-scored "
            f"before the matrix ceiling can be lowered."
        )
    op.execute(f"DELETE FROM risk_matrix_levels WHERE level > {_PREVIOUS_CEILING}")
    op.execute(
        f"UPDATE risk_settings SET matrix_size = {_PREVIOUS_CEILING} "
        f"WHERE matrix_size > {_PREVIOUS_CEILING}"
    )
    for table, name, column in (
        ("risks", "ck_risk_inh_likelihood", "inherent_likelihood"),
        ("risks", "ck_risk_inh_impact", "inherent_impact"),
        ("risks", "ck_risk_res_likelihood", "residual_likelihood"),
        ("risks", "ck_risk_res_impact", "residual_impact"),
        ("risk_matrix_levels", "ck_risk_matrix_level", "level"),
    ):
        nullable = column.startswith("residual_")
        expression = (
            f"{column} IS NULL OR {column} BETWEEN 1 AND {_PREVIOUS_CEILING}"
            if nullable
            else f"{column} BETWEEN 1 AND {_PREVIOUS_CEILING}"
        )
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression})")
