from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CustomFieldType


class CustomFieldCreate(BaseModel):
    model: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    field_type: CustomFieldType = CustomFieldType.text
    options: str = ""  # one option per line (select)
    required: bool = False
    help_text: str = ""
    order_index: int = 0
    enabled: bool = True


class CustomFieldUpdate(BaseModel):
    label: str | None = None
    field_type: CustomFieldType | None = None
    options: str | None = None
    required: bool | None = None
    help_text: str | None = None
    order_index: int | None = None
    enabled: bool | None = None


class CustomFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    model: str
    label: str
    field_type: CustomFieldType
    options: str
    required: bool
    help_text: str
    order_index: int
    enabled: bool
    created_at: datetime


class CustomFieldValueItem(BaseModel):
    """A field definition paired with the current value for a record."""

    field: CustomFieldRead
    value: str


class CustomFieldValuesUpdate(BaseModel):
    # field_id -> value
    values: dict[uuid.UUID, str]
