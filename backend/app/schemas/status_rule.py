from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class StatusRuleCreate(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    field: str = Field(min_length=1, max_length=64)
    operator: str = Field(min_length=1, max_length=16)
    value: str = ""
    label: str = Field(min_length=1, max_length=60)
    color: str = "#dc2626"
    priority: int = 0
    enabled: bool = True


class StatusRuleUpdate(BaseModel):
    field: str | None = None
    operator: str | None = None
    value: str | None = None
    label: str | None = None
    color: str | None = None
    priority: int | None = None
    enabled: bool | None = None


class StatusRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    model: str
    field: str
    operator: str
    value: str
    label: str
    color: str
    priority: int
    enabled: bool


class StatusLabel(BaseModel):
    label: str
    color: str


class BulkEvaluateRequest(BaseModel):
    ids: list[uuid.UUID]
