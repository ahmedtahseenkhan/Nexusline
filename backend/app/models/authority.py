"""Delegation of Authority (DoA) + Maker-Checker configuration registries.

Banking table stakes: two governance registers a bank's board and management
sign off on.

* **AuthorityMatrix** — the Delegation-of-Authority matrix: who (which role /
  approval level) may approve what activity, up to which monetary limit, in which
  currency, under which conditions.
* **DualControlRule** — the maker-checker (four-eyes / dual-control) registry: for a
  given module + action, whether dual control is required, who makes and who checks,
  and above which amount threshold the control kicks in.

This module delivers the *configuration / registry* + UI. Runtime enforcement of the
matrix and the four-eyes rules is a later cross-cutting task.
"""
from __future__ import annotations

import enum
from datetime import date

from sqlalchemy import Boolean, Date, Integer, Numeric, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    WorkflowMixin,
)


# ===================================================== module-local enums ===
class AuthorityCategory(str, enum.Enum):
    """The kind of activity a delegation-of-authority line governs."""

    credit = "credit"
    expenditure = "expenditure"
    procurement = "procurement"
    hr = "hr"
    it_change = "it_change"
    risk_acceptance = "risk_acceptance"
    treasury = "treasury"
    general = "general"


class AuthorityStatus(str, enum.Enum):
    active = "active"
    retired = "retired"


class DualControlStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"


# ============================================ delegation-of-authority matrix ===
class AuthorityMatrix(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A single delegation-of-authority line: a role's approval mandate for an
    activity, bounded by an amount band."""

    __tablename__ = "authority_matrix"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    activity: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[AuthorityCategory] = mapped_column(
        SAEnum(AuthorityCategory, name="authority_category"),
        default=AuthorityCategory.general, nullable=False,
    )
    role_title: Mapped[str] = mapped_column(String(200), default="")
    approval_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    amount_from: Mapped[float] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    amount_to: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    conditions: Mapped[str] = mapped_column(Text, default="")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[AuthorityStatus] = mapped_column(
        SAEnum(AuthorityStatus, name="authority_status"),
        default=AuthorityStatus.active, nullable=False,
    )

    @property
    def amount_range_label(self) -> str:
        cur = self.currency or "PKR"
        lo = float(self.amount_from or 0)
        if self.amount_to is None:
            return f"{cur} {lo:,.0f}+ (unlimited)"
        return f"{cur} {lo:,.0f} – {float(self.amount_to):,.0f}"


# ================================================= maker-checker (dual-control) ===
class DualControlRule(UUIDPrimaryKeyMixin, TimestampMixin, TenantMixin, WorkflowMixin, SoftDeleteMixin, Base):
    """A four-eyes / dual-control configuration for one module action."""

    __tablename__ = "dual_control_rules"

    reference: Mapped[str] = mapped_column(String(32), default="", index=True)
    module: Mapped[str] = mapped_column(String(120), default="", index=True)
    action: Mapped[str] = mapped_column(String(120), default="")
    requires_dual_control: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    maker_role: Mapped[str] = mapped_column(String(200), default="")
    checker_role: Mapped[str] = mapped_column(String(200), default="")
    threshold_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    status: Mapped[DualControlStatus] = mapped_column(
        SAEnum(DualControlStatus, name="dual_control_status"),
        default=DualControlStatus.active, nullable=False,
    )
