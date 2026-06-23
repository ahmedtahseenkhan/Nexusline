from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Condition(BaseModel):
    field: str
    operator: str
    value: str = ""


class SavedFilterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=64)
    description: str = ""
    match_mode: str = "all"
    conditions: list[Condition] = []
    shared: bool = True

    @field_validator("match_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in ("all", "any"):
            raise ValueError("match_mode must be 'all' or 'any'")
        return v


class SavedFilterUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    match_mode: str | None = None
    conditions: list[Condition] | None = None
    shared: bool | None = None


class SavedFilterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    model: str
    description: str
    match_mode: str
    conditions: list[Condition]
    shared: bool
    owner_email: str
    created_at: datetime


class FilterMatch(BaseModel):
    id: uuid.UUID
    label: str


class FilterResults(BaseModel):
    count: int
    total: int
    matches: list[FilterMatch]
