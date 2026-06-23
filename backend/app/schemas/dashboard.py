from __future__ import annotations

from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_risks: int
    total_controls: int
    total_assets: int
    risks_by_status: dict[str, int]
    risks_by_inherent_severity: dict[str, int]
    risks_by_residual_severity: dict[str, int]
    overdue_reviews: int
    pending_acceptances: int
    # Risk appetite program
    appetite_score: int
    tolerance_score: int
    risks_within_appetite: int
    risks_elevated: int
    risks_in_breach: int
    total_exposure: float
