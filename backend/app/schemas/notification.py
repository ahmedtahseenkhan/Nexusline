from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import NotificationCategory


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    body: str
    category: NotificationCategory
    entity_type: str
    entity_id: uuid.UUID | None
    link: str
    created_at: datetime
    seen: bool = False


class NotificationList(BaseModel):
    items: list[NotificationRead]
    unseen_count: int
