"""Payloads for the generic import/export engine and the smart import wizard.

The wizard is four steps and each has one endpoint: **inspect** (what is in your file?),
**preview** (what would this mapping produce?), **import** (do it), and profile
save/reuse so the next upload skips straight to step 3.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------- import ----
class ImportError(BaseModel):
    row: int
    message: str


class ImportResult(BaseModel):
    total: int
    created: int
    skipped: int
    errors: list[ImportError]


class ImportRequest(BaseModel):
    """CSV text plus an optional mapping.

    With no ``mapping``, behaviour is identical to the original engine: the file's
    headers must already be our canonical ones. That keeps every existing template
    download → fill → upload flow working untouched.
    """

    content: str
    mapping: dict[str, str] = {}
    custom_field_mapping: dict[str, uuid.UUID] = {}


# --------------------------------------------------------------- inspect ----
class MappingSuggestionRead(BaseModel):
    source: str
    target: str
    field: str
    confidence: float
    reason: str
    band: str  # high | medium | low — drives whether the wizard flags it for review


class InspectRequest(BaseModel):
    """Either CSV text (``content``) or a base64 .xlsx workbook (``file_b64``)."""

    content: str | None = None
    file_b64: str | None = None
    filename: str = ""
    sheet: str | None = None


class InspectResponse(BaseModel):
    """What we found in the uploaded file, and how we propose to read it.

    ``csv`` is the canonicalised table — banner rows removed, sheet flattened. The
    wizard carries it into preview/import so those steps never re-parse Excel.
    """

    csv: str
    headers: list[str]
    row_count: int
    header_row_index: int
    sheet_names: list[str]
    sheet: str
    # First few data rows, so the mapping step can show a real example under each of
    # the client's columns — the fastest way for a person to spot a wrong match.
    sample_rows: list[list[str]]
    suggestions: list[MappingSuggestionRead]
    unmapped_source_headers: list[str]
    unfilled_target_headers: list[str]
    missing_required: list[str]


# --------------------------------------------------------------- preview ----
class PreviewRow(BaseModel):
    row: int  # line number in the uploaded file (header is line 1)
    values: dict[str, str]  # our canonical header -> the value we would import
    error: str = ""


class PreviewRequest(BaseModel):
    content: str
    mapping: dict[str, str] = {}
    custom_field_mapping: dict[str, uuid.UUID] = {}
    limit: int = Field(default=20, ge=1, le=100)


class PreviewResponse(BaseModel):
    total: int  # rows in the file
    previewed: int  # rows in this response
    valid: int  # of the previewed rows, how many would import cleanly
    rows: list[PreviewRow]
    columns: list[str]  # canonical headers actually populated by this mapping


# -------------------------------------------------------------- profiles ----
class ImportProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    mapping: dict[str, str] = {}
    custom_field_mapping: dict[str, uuid.UUID] = {}


class ImportProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    resource: str
    name: str
    description: str
    mapping: dict[str, str]
    custom_field_mapping: dict[str, str]
    created_by_email: str
    created_at: datetime
