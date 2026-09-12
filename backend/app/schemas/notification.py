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
    #: Deep link that opens the record (``/risks?id=…``); a grouped alert links to the list.
    link: str
    created_at: datetime
    seen: bool = False
    #: Who the alert is addressed to: a person, a role, both, or neither (everyone).
    user_id: uuid.UUID | None = None
    role_name: str = ""
    #: How it reached the signed-in user: ``me``, ``role`` or ``everyone``.
    audience: str = "everyone"


class NotificationList(BaseModel):
    items: list[NotificationRead]
    #: Unseen across the user's whole feed, not just this page (the bell badge).
    unseen_count: int
    #: Of those, how many are addressed to the user or one of their roles.
    unseen_mine: int = 0
    #: Rows in the whole feed; ``items`` is the ``offset``/``limit`` slice of it.
    total: int = 0
    limit: int = 0
    offset: int = 0
    #: critical / warning / info tallies across the whole feed.
    counts: dict[str, int] = {}
    #: Whether the feed was narrowed to alerts addressed to the user (``?mine=true``).
    mine: bool = False
