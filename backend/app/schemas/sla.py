"""Payloads for the turnaround-time (TAT) policy and its breach reporting."""
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import Severity


class SlaPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID | None = None
    entity_type: str
    entity_label: str = ""
    severity: Severity
    target_days: int
    warn_at_percent: int
    escalate_to_role: str
    enabled: bool
    #: True when no row exists yet and the shipped default is being reported, so the UI
    #: can show "not configured" rather than implying someone chose these numbers.
    is_default: bool = False


class SlaPolicyItem(BaseModel):
    entity_type: str = Field(pattern="^(risk|issue|audit_finding|incident)$")
    severity: Severity
    target_days: int = Field(ge=1, le=3650)
    warn_at_percent: int = Field(default=80, ge=1, le=100)
    escalate_to_role: str = Field(default="", max_length=64)
    enabled: bool = True


class SlaPolicyUpdate(BaseModel):
    """Upsert several scopes at once — the editor is a grid, not a form per row."""

    policies: list[SlaPolicyItem] = Field(min_length=1)


class TatRecordRead(BaseModel):
    # The service returns plain dataclasses (it is deliberately Pydantic-free so the
    # clock arithmetic stays testable in isolation), so read them by attribute.
    model_config = ConfigDict(from_attributes=True)
    entity_type: str
    entity_label: str
    entity_id: uuid.UUID
    label: str
    severity: str
    due: date | None
    days_overdue: int
    link: str


class TatTypeCount(BaseModel):
    entity_type: str
    label: str
    breached: int
    at_risk: int


class TatSummary(BaseModel):
    breached: int
    at_risk: int
    by_type: list[TatTypeCount]
    records: list[TatRecordRead]
