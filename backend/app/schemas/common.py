"""Shared schema building blocks."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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


class ExceptionRef(GraphRef):
    """A linked exception, with what a record page needs to describe it: its decision
    state and when it lapses (spec B3).

    A subclass rather than two more fields on ``GraphRef``: ``GraphRef`` is read with
    ``from_attributes`` from dozens of models, many of which have a ``status`` of their
    own, so widening it would change every other payload that uses it.

    ``status`` is the exception's state as the exceptions register shows it: an approved
    exception past its expiry reads ``expired`` (a derived state, never stored — see
    ``api.v1.exceptions``), so a page never calls a lapsed exception approved.
    """

    status: str | None = None
    expires_at: date | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _enum_value(cls, v):
        return getattr(v, "value", v)

    @model_validator(mode="after")
    def _approved_past_expiry_is_expired(self) -> "ExceptionRef":
        self.status = exception_status(self.status, self.expires_at)
        return self


def exception_status(status, expires_at: date | None, today: date | None = None) -> str | None:
    """An exception's state as the register shows it: ``expired`` for an approved
    exception past its expiry, else its stored status (enum or text). Pure."""
    value = getattr(status, "value", status)
    if value == "approved" and expires_at is not None and expires_at < (today or date.today()):
        return "expired"
    return value


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

