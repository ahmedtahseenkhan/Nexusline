"""Validate and normalise a custom-field value — one rule set for every way a value
arrives (the record form's PUT, and spreadsheet import).

A value is stored as text, so the checks here are what keep it meaningful: a number
field holds a number, a date an ISO date, a checkbox ``true``/``false``, and a select
one of its options in the option's own spelling. A blank value clears the field, which
a required field refuses.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any

from app.models.enums import CustomFieldType
from app.services import csv_io

#: Custom-field type -> the ``csv_io.coerce`` kind that parses it.
KIND: dict[CustomFieldType, str] = {
    CustomFieldType.text: "text",
    CustomFieldType.textarea: "text",
    CustomFieldType.number: "float",
    CustomFieldType.date: "date",
    CustomFieldType.checkbox: "bool",
    CustomFieldType.select: "enum",
}


def options_of(field: Any) -> list[str]:
    """A select field's options (one per line), blanks dropped."""
    return [o.strip() for o in (getattr(field, "options", "") or "").splitlines() if o.strip()]


def normalise(kind: str, raw: str | None, options: list[str] | None = None) -> str:
    """The value to store for ``raw`` under a field of this kind, or ``""`` for a blank.

    Checkbox values normalise to ``true``/``false``, dates to ISO, select values to the
    option's own spelling (case-insensitive). Raises ``ValueError`` with a message that
    names the bad value. Pure.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    if kind == "enum":
        match = next((o for o in options or [] if o.casefold() == text.casefold()), None)
        if match is None:
            raise ValueError(f"'{text}' is not a valid option (allowed: {', '.join(options or [])})")
        return match
    value = csv_io.coerce(text, kind)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"'{text}' is not a valid number")
    return text


def clean(field: Any, raw: str | None) -> str:
    """The value to store for one field (a ``CustomField`` row), or ``ValueError`` naming
    the field: a malformed value, or a required (enabled) field left blank. A checkbox
    always has an answer — unticked reads "no" — so "required" never refuses one. Pure."""
    kind = KIND.get(getattr(field, "field_type", None), "text")
    try:
        value = normalise(kind, raw, options_of(field) if kind == "enum" else None)
    except ValueError as exc:
        raise ValueError(f"{field.label}: {exc}") from exc
    if not value and kind != "bool" and getattr(field, "required", False) and getattr(field, "enabled", True):
        raise ValueError(f"{field.label}: this field is required")
    return value
