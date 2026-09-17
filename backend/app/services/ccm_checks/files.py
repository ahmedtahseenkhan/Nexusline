"""File-fed checks: SIEM / log-source health and generic CSV rows, plus the import folder.

On-prem, a scanner or SIEM export job writes files into a share; the connector's
``config.import_path`` (inside ``settings.ccm_import_dir``) and ``config.file_pattern``
say where, and a scheduled run reads the newest matching file. A person can upload a file
with "Run with file" instead.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.ccm_checks import selector
from app.services.ccm_checks.base import (
    CheckContext,
    CheckError,
    CheckOutcome,
    CheckSpec,
    COMPARISON_OPS,
    Param,
    UploadedFile,
    as_int,
    as_list,
    compare,
)

MAX_FILE_BYTES = 200 * 1024 * 1024


# -------------------------------------------------------------- import folder ---
def import_root() -> Path:
    from app.core.config import settings

    return Path(settings.ccm_import_dir).resolve()


def folder_for(config: dict, root: Path | None = None) -> Path:
    """The connector's import folder, which must be inside the import root."""
    root = (root or import_root()).resolve()
    rel = str(config.get("import_path") or "").strip()
    if not rel:
        raise CheckError("The connector has no import folder.")
    folder = (root / rel).resolve()
    if folder != root and root not in folder.parents:
        raise CheckError(f"The import folder must be inside {root}.")
    return folder


def newest_file(config: dict, root: Path | None = None) -> UploadedFile:
    folder = folder_for(config, root)
    if not folder.is_dir():
        raise CheckError(f"The import folder {folder} does not exist.")
    pattern = str(config.get("file_pattern") or "*").strip() or "*"
    files = [f for f in folder.glob(pattern) if f.is_file()]
    if not files:
        raise CheckError(f"No file matching {pattern} in {folder}.")
    newest = max(files, key=lambda f: f.stat().st_mtime)
    if newest.stat().st_size > MAX_FILE_BYTES:
        raise CheckError(f"{newest.name} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    return UploadedFile(
        filename=newest.name, content=newest.read_bytes(), origin=str(newest),
        modified_at=datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc),
    )


def folder_summary(config: dict, root: Path | None = None) -> str:
    folder = folder_for(config, root)
    if not folder.is_dir():
        raise CheckError(f"The import folder {folder} does not exist.")
    pattern = str(config.get("file_pattern") or "*").strip() or "*"
    files = [f for f in folder.glob(pattern) if f.is_file()]
    if not files:
        return f"The import folder {folder} exists but has no file matching {pattern} yet."
    newest = max(files, key=lambda f: f.stat().st_mtime)
    at = datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc).strftime("%d %b %Y %H:%M UTC")
    return f"{len(files)} file(s) matching {pattern} in {folder}; newest {newest.name}, written {at}."


# --------------------------------------------------------------- file reading ---
def rows_of(file: UploadedFile, list_selector: str = "") -> list[dict]:
    """JSON (a list, or the list at ``list_selector``) or CSV rows as dicts."""
    text = file.content.decode("utf-8-sig", errors="replace").strip()
    if text.startswith(("[", "{")):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise CheckError(f"{file.filename} is not valid JSON: {exc}.") from exc
        items = selector.select(data, list_selector) if list_selector else data
        if isinstance(items, dict):
            # {"source-a": {...}, ...} → rows carrying their key as the name
            items = [{"name": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in items.items()]
        if not isinstance(items, list):
            raise CheckError(f"No list of rows in {file.filename}" + (f" at '{list_selector}'." if list_selector else "."))
        return [i if isinstance(i, dict) else {"value": i} for i in items]
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CheckError(f"{file.filename} has no header row.")
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = float(value)
        return datetime.fromtimestamp(n / 1000 if n > 10**11 else n, tz=timezone.utc)
    text = str(value).strip()
    if text.replace(".", "", 1).isdigit():
        return parse_time(float(text))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _pick(row: dict, preferred: str, candidates: tuple[str, ...]) -> Any:
    if preferred:
        return selector.select(row, preferred)
    lowered = {str(k).lower(): v for k, v in row.items()}
    for c in candidates:
        if c in lowered and lowered[c] not in (None, ""):
            return lowered[c]
    return None


_NAME_FIELDS = ("name", "source", "log_source", "logsource", "host", "hostname", "device")
_SEEN_FIELDS = ("last_seen", "last_event", "last_event_time", "lasteventtime", "last_event_at", "lastseen", "last_received")


# ---------------------------------------------------------------------- checks ---
def siem_source_health(ctx: CheckContext) -> CheckOutcome:
    """Log sources that have not reported within N hours, and expected sources missing."""
    p = ctx.parameters
    hours = as_int(p.get("max_silence_hours"), 24) or 24
    if ctx.file is not None:
        rows = rows_of(ctx.file, str(p.get("list_selector") or ""))
        origin = ctx.file.filename
    else:
        from app.services.ccm_checks.http_json import fetch_json

        body = fetch_json(ctx, p.get("path"))
        items = selector.select(body, str(p.get("list_selector") or "")) if p.get("list_selector") else body
        if not isinstance(items, list):
            raise CheckError("The SIEM response has no list of log sources at the selector.")
        rows = [i for i in items if isinstance(i, dict)]
        origin = "API"
    cutoff = ctx.now - timedelta(hours=hours)
    ignored = {x.lower() for x in as_list(p.get("ignored_sources"))}
    seen: dict[str, datetime | None] = {}
    unreadable = 0
    for row in rows:
        name = str(_pick(row, str(p.get("name_field") or ""), _NAME_FIELDS) or "").strip()
        if not name or name.lower() in ignored:
            continue
        raw = _pick(row, str(p.get("last_seen_field") or ""), _SEEN_FIELDS)
        at = parse_time(raw)
        if raw not in (None, "") and at is None:
            unreadable += 1
        previous = seen.get(name.lower())
        seen[name.lower()] = at if previous is None or (at is not None and at > previous) else previous
    display = {}
    for row in rows:
        n = str(_pick(row, str(p.get("name_field") or ""), _NAME_FIELDS) or "").strip()
        if n:
            display.setdefault(n.lower(), n)
    exceptions = []
    for key, at in sorted(seen.items()):
        if at is None or at < cutoff:
            exceptions.append({
                "source": display.get(key, key), "last_seen": at.isoformat() if at else "never",
                "silent_hours": int((ctx.now - at).total_seconds() // 3600) if at else None,
            })
    expected = as_list(p.get("expected_sources"))
    missing = [e for e in expected if e.lower() not in seen and e.lower() not in ignored]
    exceptions += [{"source": m, "last_seen": "not in the report", "silent_hours": None} for m in missing]
    population = len(seen) + len(missing)
    return CheckOutcome(
        population=population, exceptions=exceptions,
        summary=f"{len(exceptions)} of {population} log source(s) silent for more than {hours} hours or missing ({origin})",
        metric_value=float(len(exceptions)),
        details={"max_silence_hours": hours, "expected_sources": len(expected), "missing": len(missing),
                 "unreadable_times": unreadable, "origin": origin},
    )


def csv_rows_check(ctx: CheckContext) -> CheckOutcome:
    """Each row of an uploaded CSV/JSON is one item; a row is an exception when the rule holds."""
    if ctx.file is None:
        raise CheckError("No file: upload the CSV or JSON to test, or set the connector's import folder.")
    p = ctx.parameters
    rows = rows_of(ctx.file, str(p.get("list_selector") or ""))
    column = str(p.get("column") or "result")
    op = str(p.get("op") or "in")
    value = p.get("value") if p.get("value") not in (None, "") else "fail,failed,no,false,non-compliant,noncompliant"
    label = str(p.get("label_column") or "")
    if rows and column not in rows[0] and "." not in column:
        raise CheckError(f"{ctx.file.filename} has no column '{column}' (columns: {', '.join(list(rows[0])[:20])}).")
    exceptions = []
    for i, row in enumerate(rows, start=1):
        actual = selector.select(row, column)
        if compare(actual, op, value):
            exceptions.append({"row": i, "item": str(row.get(label) or "") if label else "",
                               column: actual if isinstance(actual, (str, int, float, bool)) or actual is None else str(actual)})
    return CheckOutcome(
        population=len(rows), exceptions=exceptions,
        summary=f"{len(exceptions)} of {len(rows)} row(s) in {ctx.file.filename} where {column} {op} {value}",
        metric_value=float(len(exceptions)), details={"file": ctx.file.filename, "column": column, "op": op, "value": value},
    )


def _csv_validate(params: dict) -> list[str]:
    op = params.get("op")
    return [f"Comparison: must be one of {', '.join(COMPARISON_OPS)}."] if op and op not in COMPARISON_OPS else []


SPECS = (
    CheckSpec(
        key="siem_source_health", label="Log sources not reporting", group="SIEM",
        description=("Reads a SIEM log-source export (JSON or CSV) or calls the SIEM API, and flags sources silent for "
                     "longer than the set hours, plus expected sources missing from the report."),
        connector_types=("siem", "csv_feed", "api"), input="connector_or_file",
        params=(
            Param("max_silence_hours", "Silent after (hours)", "number", required=True, default=24),
            Param("expected_sources", "Expected sources", "list", help="Sources that must appear, one per line (domain controllers, core banking, firewalls)."),
            Param("ignored_sources", "Ignored sources", "list", help="Decommissioned or test sources, one per line."),
            Param("name_field", "Source name field", help="Blank = detected (name, source, host…)."),
            Param("last_seen_field", "Last-event time field", help="Blank = detected (last_seen, last_event…)."),
            Param("list_selector", "List selector", help="Where the list of sources is in a JSON document, e.g. data.sources."),
            Param("path", "API path", help="When pulling from the SIEM API rather than a file."),
        ),
        pass_criterion="Every expected log source reported an event within the set number of hours.",
        population="Log sources in the SIEM report, plus expected sources.",
        run=siem_source_health,
    ),
    CheckSpec(
        key="csv_rows", label="Uploaded CSV / JSON rows", group="File upload",
        description="For anything else: each row of an uploaded or dropped file is an item; a row is an exception when the rule holds.",
        connector_types=("csv_feed",), input="file",
        params=(
            Param("column", "Column", required=True, default="result"),
            Param("op", "Exception when", "select", default="in", options=COMPARISON_OPS),
            Param("value", "Value", default="fail,failed,no,false,non-compliant",
                  help="For in / not_in: a comma-separated list."),
            Param("label_column", "Label column", help="Column naming the item in the exception sample."),
            Param("list_selector", "List selector (JSON)", help="Where the rows are in a JSON document."),
        ),
        pass_criterion="Rows meeting the exception rule stay within the threshold.",
        population="Rows of the file.",
        run=csv_rows_check, validate=_csv_validate,
    ),
)
