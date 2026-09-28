"""Database constraint violations as the 4xx responses they are.

A duplicate name, a cleared required field or a link to a record that no longer exists
is the user's input being refused — not a server fault. Left unhandled, each surfaced
as "Internal Server Error" with nothing the person could act on. The database remains
the backstop; this only turns its refusal into a sentence.
"""
from __future__ import annotations

import logging
import re

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

logger = logging.getLogger("nexusline.db_errors")

_KEY = re.compile(r"Key \((?P<cols>[^)]*)\)=\((?P<vals>.*)\)")


def _human(name: str) -> str:
    name = re.sub(r"_id$", "", name.strip())
    return name.replace("_", " ")


def _key_columns(detail: str) -> list[str]:
    match = _KEY.search(detail)
    if not match:
        return []
    cols = [_human(c) for c in match.group("cols").split(",")]
    return [c for c in cols if c != "tenant"] or cols


def _unique_columns(constraint: str, table: str | None) -> list[str]:
    """Columns named in a ``uq_<table>_<col>_<col>`` constraint, or none when the name
    does not follow that shape (the caller then says so without guessing)."""
    name = re.sub(r"^(uq|ux|uniq)_", "", constraint)
    if not table or name == constraint:
        return []
    singular = re.sub(r"ies$", "y", table) if table.endswith("ies") else table.removesuffix("s")
    for prefix in (table, singular):
        if name.startswith(prefix + "_"):
            return [c for c in name[len(prefix) + 1:].split("_") if c and c != "tenant"]
    return []


def _fk_columns(constraint: str, table: str | None) -> list[str]:
    name = re.sub(r"_fkey$", "", constraint)
    if table and name.startswith(table + "_"):
        return [_human(name[len(table) + 1:])]
    return []


def _describe(exc: IntegrityError) -> tuple[int, str]:
    cause = getattr(exc.orig, "__cause__", None) or exc.orig
    kind = type(cause).__name__
    detail = getattr(cause, "detail", "") or ""
    column = getattr(cause, "column_name", None)
    table = getattr(cause, "table_name", None)

    if kind == "NotNullViolationError":
        return 422, f"'{_human(column or 'field')}' is required and cannot be empty."
    constraint = getattr(cause, "constraint_name", None) or ""
    if kind == "UniqueViolationError":
        # Under row-level security Postgres withholds the "Key (...)" detail, so fall
        # back to the constraint's name: uq_audit_plan_year_title -> "year and title".
        cols = _key_columns(detail) or _unique_columns(constraint, table)
        if cols:
            return 409, f"A record with this {' and '.join(cols)} already exists."
        return 409, "This record already exists."
    if kind == "ForeignKeyViolationError":
        if "is still referenced" in detail or "update or delete" in str(cause):
            return 409, "This record is still used by other records — remove those links first."
        cols = _key_columns(detail) or _fk_columns(constraint, table)
        field = " and ".join(cols) if cols else "linked record"
        return 422, f"The selected {field} does not exist (it may have been deleted)."
    if kind == "CheckViolationError":
        return 422, f"A value is outside the allowed range ({getattr(cause, 'constraint_name', '')})."
    return 409, "The change conflicts with existing data."


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    status, message = _describe(exc)
    logger.info("Refused %s %s: %s (%s)", request.method, request.url.path, message, exc.orig)
    return JSONResponse(status_code=status, content={"detail": message})


async def pool_timeout_handler(request: Request, exc: PoolTimeoutError) -> JSONResponse:
    """Every database connection stayed busy for the whole pool timeout: the server is
    saturated, not broken. Say so, and let the browser retry, instead of a bare 500."""
    logger.warning("Database pool exhausted on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "The server is busy right now. Please try again in a moment."},
        headers={"Retry-After": "5"},
    )
