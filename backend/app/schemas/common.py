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


class UserRef(BaseModel):
    """A person picked from the user list, as forms and lists show them."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    full_name: str = ""
    email: str = ""


class LookupRef(BaseModel):
    """A value from a governed lookup list."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    key: str = ""
    value: str = ""
    label: str = ""


class UnitRef(BaseModel):
    """A business unit or process, by name."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str = ""

