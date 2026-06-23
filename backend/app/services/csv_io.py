"""CSV serialization helpers for the generic data import/export engine.

Pure functions with no DB or FastAPI coupling: render rows to CSV text, build a
template (header + one example row) from a column spec, and coerce a raw string
cell into a typed Python value by the declared column ``kind``. Coercion raises
``ValueError`` with a human-readable message that the import endpoint surfaces
per-row.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from app.services.import_registry import Column

_TRUE = {"true", "yes", "y", "1", "t"}
_FALSE = {"false", "no", "n", "0", "f"}


def export_csv(rows: list[dict], headers: list[str]) -> str:
    """Render ``rows`` (header->value dicts) to CSV text.

    Uses ``\\n`` line endings (CRLF disabled), quotes only where needed, and
    coerces ``None`` to an empty cell. Only the supplied ``headers`` are emitted,
    in order.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=headers, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({h: _cell(row.get(h)) for h in headers})
    return buf.getvalue()


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def make_template(columns: list["Column"]) -> str:
    """Build a CSV template: a header row of importable columns plus one example row."""
    headers = [c.header for c in columns]
    example = {c.header: _example_value(c) for c in columns}
    return export_csv([example], headers)


def _example_value(column: "Column") -> str:
    """A realistic placeholder cell for the template's single example row."""
    if column.kind == "enum" and column.enum_values:
        return column.enum_values[0]
    if column.kind == "bool":
        return "false"
    if column.kind == "int":
        return "1"
    if column.kind == "float":
        return "0.0"
    if column.kind == "date":
        return date.today().isoformat()
    if column.kind == "link":
        return ""  # leave blank; references must point at existing records
    # text
    if column.field in {"title", "name"}:
        return "Example " + column.field
    return ""


def coerce(value: str, kind: str, enum_values: list[str] | None = None):
    """Coerce a raw CSV string into a typed value for the given ``kind``.

    A blank/whitespace-only cell returns ``None`` (the caller omits it so the
    Pydantic default applies). Raises ``ValueError`` with a clean message on a
    malformed int/float/date or an enum value outside ``enum_values``.
    ``link`` values are returned raw (stripped) for the caller to resolve to ids.
    """
    if value is None:
        return None
    text = value.strip()
    if text == "":
        return None

    if kind in ("text", "link"):
        return text

    if kind == "int":
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(f"'{text}' is not a valid integer") from exc

    if kind == "float":
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"'{text}' is not a valid number") from exc

    if kind == "bool":
        low = text.lower()
        if low in _TRUE:
            return True
        if low in _FALSE:
            return False
        raise ValueError(f"'{text}' is not a valid boolean (use true/false/yes/no/1/0)")

    if kind == "date":
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"'{text}' is not a valid date (expected YYYY-MM-DD)") from exc

    if kind == "enum":
        allowed = enum_values or []
        if text in allowed:
            return text
        raise ValueError(
            f"'{text}' is not a valid option (allowed: {', '.join(allowed)})"
        )

    # Unknown kind: fall back to the raw string rather than dropping the value.
    return text
