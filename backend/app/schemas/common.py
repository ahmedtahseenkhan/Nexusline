"""Shared schema building blocks."""
from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class GraphRef(BaseModel):
    """A lightweight, universal reference to any linked record for cross-module
    "Related records" display. Populates whichever of reference/title/name the source
    record has; the UI shows `reference || title || name`."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str = ""
    title: str = ""
    name: str = ""


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int
