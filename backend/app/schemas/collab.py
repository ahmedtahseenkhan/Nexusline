from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    author_email: str
    body: str
    created_at: datetime
    can_delete: bool = False


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    color: str


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = "#2563eb"


class TagAssign(BaseModel):
    tag_id: uuid.UUID | None = None
    name: str | None = None  # create-and-assign if no id
    color: str = "#2563eb"


class AttachmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    url: str = ""
    kind: str = "link"


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    url: str
    kind: str
    added_by_email: str
    created_at: datetime


class CollabBundle(BaseModel):
    comments: list[CommentRead]
    tags: list[TagRead]
    attachments: list[AttachmentRead]
    available_tags: list[TagRead]
