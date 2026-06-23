from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WebhookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=1024)
    secret: str = ""
    events: str = "*"
    enabled: bool = True


class WebhookUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    secret: str | None = None
    events: str | None = None
    enabled: bool | None = None


class WebhookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    url: str
    events: str
    enabled: bool
    last_status: int | None
    last_delivered_at: datetime | None
    created_at: datetime


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event: str
    status_code: int | None
    success: bool
    error: str
    created_at: datetime
