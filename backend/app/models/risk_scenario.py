"""Risk-scenario templates — the bridge from an asset register to a risk register.

Each row is a reusable "threat exploits vulnerability against this kind of asset"
statement, plus how to derive an opening score from the asset's own rating. The
generation endpoint pairs selected assets with the applicable templates and *proposes*
risks; a risk owner edits and commits them.

The built-in catalogue in :mod:`app.services.risk_scenarios` is installed into this
table rather than read from directly, so a bank can retune the library — add its own
scenarios, silence the ones that do not apply, change a base likelihood — without a
release.
"""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.services.risk_scenarios import IMPACT_RULES

_RULES = ", ".join(f"'{r}'" for r in IMPACT_RULES)


class RiskScenarioTemplate(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "risk_scenario_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_risk_scenario_reference"),
        CheckConstraint(f"impact_rule IN ({_RULES})", name="ck_risk_scenario_impact_rule"),
        CheckConstraint("likelihood BETWEEN 1 AND 5", name="ck_risk_scenario_likelihood"),
    )

    reference: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="", index=True)

    #: Comma-separated ``AssetClass`` values this scenario applies to. Empty = every asset.
    asset_classes: Mapped[str] = mapped_column(String(120), default="")

    #: Threat and vulnerability by name. Resolved to (or created in) the Threat Library
    #: at commit time, so a generated risk carries the same graph links a hand-made one does.
    threat: Mapped[str] = mapped_column(String(200), default="")
    vulnerability: Mapped[str] = mapped_column(String(200), default="")

    #: Base likelihood on a 1-5 scale, rescaled to whatever matrix the tenant uses.
    likelihood: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    impact_rule: Mapped[str] = mapped_column(String(32), default="from_criticality", nullable=False)
    impact_property: Mapped[str] = mapped_column(String(20), default="")
    fixed_impact: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    treatment_hint: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
