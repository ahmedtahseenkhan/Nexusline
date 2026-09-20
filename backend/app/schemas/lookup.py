"""Governed lookup lists (``/lookups``) — request and response shapes."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class LookupListRead(BaseModel):
    """One governed list, as the ``/lookups`` page lists them."""

    key: str
    name: str
    #: Existing free text in the fields this list backs becomes values on upgrade.
    seeded_from_text: bool
    total: int = 0
    active: int = 0


class LookupRead(BaseModel):
    """One value in a list.

    ``path`` is what a picker shows: the label, prefixed with the parent's label for a
    child value ("Operational › Fraud"). ``builtin`` marks a shipped default (deleting
    one brings it back on the next start — deactivate it instead). ``usage`` is the
    number of records pointing at the value; only filled when asked for (``?usage=true``).
    """

    id: uuid.UUID
    key: str
    value: str
    label: str
    description: str = ""
    sort_order: int = 0
    active: bool = True
    parent_id: uuid.UUID | None = None
    parent_label: str = ""
    path: str = ""
    depth: int = 0
    builtin: bool = False
    usage: int | None = None


class LookupCreate(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    #: Stable machine key; derived from the label when omitted. Unique within the list.
    value: str | None = Field(default=None, max_length=120)
    description: str = ""
    #: Defaults to after the last sibling.
    sort_order: int | None = None
    active: bool = True
    parent_id: uuid.UUID | None = None


class LookupUpdate(BaseModel):
    """Rename, re-describe, reorder, (de)activate or re-parent a value.

    ``value`` cannot change: it is the stable key imports and integrations match on.
    Send ``parent_id: null`` explicitly to move a child to the top level.
    """

    label: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    sort_order: int | None = None
    active: bool | None = None
    parent_id: uuid.UUID | None = None


class LookupOrder(BaseModel):
    """Ids of a list's values in the order people should see them."""

    ids: list[uuid.UUID] = Field(min_length=1)
