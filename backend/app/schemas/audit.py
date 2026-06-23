from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    actor_email: str
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    summary: str
    created_at: datetime
