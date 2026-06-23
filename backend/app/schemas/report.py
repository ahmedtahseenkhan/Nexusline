from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

VIZ = {"number", "bar", "donut"}


class MetricInfo(BaseModel):
    key: str
    label: str
    description: str
    kind: str  # scalar | breakdown
    category: str


class WidgetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    metric_key: str = Field(min_length=1, max_length=64)
    viz: str = "number"
    order_index: int = 0

    @field_validator("viz")
    @classmethod
    def _viz(cls, v: str) -> str:
        if v not in VIZ:
            raise ValueError(f"viz must be one of {sorted(VIZ)}")
        return v


class WidgetUpdate(BaseModel):
    title: str | None = None
    viz: str | None = None
    order_index: int | None = None


class WidgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    metric_key: str
    viz: str
    order_index: int


class SeriesPoint(BaseModel):
    label: str
    value: float


class WidgetData(BaseModel):
    widget: WidgetRead
    kind: str
    value: float | None = None
    series: list[SeriesPoint] | None = None
    error: str | None = None
