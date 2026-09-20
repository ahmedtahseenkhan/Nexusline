"""Bulk edit and bulk mapping on the registers (product review 3.2, F-15).

``PATCH /records/{entity_type}/bulk`` sets one or more values on many records at once;
``POST /controls/bulk/map-requirements`` links many controls to many clauses. Both answer
with a :class:`BulkResult`: a line per id saying whether it was updated or skipped and
why, the batch id every audit entry of the run carries, and a one-line summary for the
toast ("Updated 38; 2 skipped: archived").
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The most records one request may touch. A register page selects at most a few
#: hundred; anything larger is an import, not an edit.
MAX_BULK_IDS = 500


class BulkPatch(BaseModel):
    """The values to set. Only the keys sent are applied; a register accepts the subset
    its allow-list names (``GET /records/{type}/bulk-fields``). Approval state
    (``workflow_status``) is never accepted — it moves only through the lifecycle."""

    model_config = ConfigDict(extra="forbid")

    owner_id: uuid.UUID | None = None
    next_review_date: date | None = None
    review_frequency: str | None = None
    category_id: uuid.UUID | None = None
    status: str | None = None


class BulkEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_IDS)
    patch: BulkPatch


class BulkMapRequirementsBody(BaseModel):
    """Link every listed control to every listed requirement (links are only added)."""

    model_config = ConfigDict(extra="forbid")

    control_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK_IDS)
    requirement_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class BulkResultItem(BaseModel):
    id: uuid.UUID
    reference: str = ""
    label: str = ""
    outcome: Literal["updated", "skipped"]
    #: Why a record was skipped ("archived", "not found", "no change", or a rule).
    reason: str = ""
    #: What changed on an updated record, in words ("owner", "next test date").
    changed: list[str] = Field(default_factory=list)


class BulkResult(BaseModel):
    entity_type: str
    #: Carried by every audit entry this run wrote (``changes.batch_id``).
    batch_id: str
    updated: int
    skipped: int
    #: "Updated 38; 2 skipped: archived".
    summary: str
    results: list[BulkResultItem]


class BulkOption(BaseModel):
    value: str
    label: str


class BulkFieldRead(BaseModel):
    """One value the register can set in bulk, and how to pick it."""

    #: The key in ``patch``: owner_id | next_review_date | review_frequency | category_id | status.
    key: str
    #: The register's own name for it ("Owner", "Assignee", "Next test date").
    label: str
    #: user | unit | lookup | date | frequency | status — decides the picker.
    kind: str
    #: The governed list a ``lookup`` field draws from.
    lookup_key: str | None = None
    #: The values a ``status`` or ``frequency`` field may take.
    options: list[BulkOption] = Field(default_factory=list)
    #: The register rule a person should know before confirming.
    note: str = ""


class BulkFieldsRead(BaseModel):
    entity_type: str
    #: Plural noun for messages ("controls", "third parties").
    noun: str
    #: Holds the register's write permission — without it there is nothing to offer.
    can_edit: bool
    fields: list[BulkFieldRead]
