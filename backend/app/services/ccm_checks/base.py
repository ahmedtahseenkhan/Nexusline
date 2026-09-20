"""What every continuous-monitoring check shares: its input, its outcome, the threshold
rule, value comparisons and parameter validation. Pure — no database, no network.

A check is a synchronous function ``run(ctx) -> CheckOutcome`` (the runner calls it in a
worker thread with a timeout). It reports the **population** it looked at and the
**exceptions** it found; whether that is a pass is decided here, by the test's threshold,
never by the check.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

#: Exception rows kept on a run (and so in its evidence); the count is always exact.
SAMPLE_CAP = 200
#: Exception rows written into the evidence description itself.
EVIDENCE_LINES = 25


class CheckError(Exception):
    """The check could not run (bad configuration, source unreachable, unreadable file).
    Recorded as a run with result *error* — never as a pass or a failure."""


class ConnectionFailure(CheckError):
    """The source itself could not be reached or refused the credentials."""


@dataclass
class UploadedFile:
    filename: str
    content: bytes
    #: Where it came from: "upload" (a person) or the import-folder path.
    origin: str = "upload"
    modified_at: datetime | None = None


@dataclass
class CheckContext:
    parameters: dict
    connector_type: str | None = None
    config: dict = field(default_factory=dict)
    secrets: dict = field(default_factory=dict)
    timeout: float = 30.0
    file: UploadedFile | None = None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    #: Injected for tests: ``ldap_factory(config, secrets, timeout)`` → connection;
    #: ``http_get(url, headers, params, timeout, verify)`` → (status, json body).
    ldap_factory: Callable[..., Any] | None = None
    http_get: Callable[..., tuple[int, Any]] | None = None
    #: May an HTTP check reach private addresses (``settings.ccm_allow_private_urls``).
    allow_private_urls: bool = True
    #: Vulnerability checks: first-seen dates already in the register, by finding key.
    known_first_seen: dict = field(default_factory=dict)

    @property
    def today(self) -> date:
        return self.now.date()


@dataclass
class CheckOutcome:
    population: int
    exceptions: list[dict]
    summary: str
    metric_value: float | None = None
    details: dict = field(default_factory=dict)
    #: A value comparison decides pass/fail itself (no exception count to threshold).
    passed: bool | None = None
    #: Vulnerability checks: findings to upsert into the register when asked to.
    vulnerabilities: list = field(default_factory=list)

    @property
    def exceptions_count(self) -> int:
        return len(self.exceptions)

    @property
    def sample(self) -> list[dict]:
        return [dict(e) for e in self.exceptions[:SAMPLE_CAP]]


@dataclass(frozen=True)
class Param:
    """One field of a check's parameter form (served to the test builder)."""

    name: str
    label: str
    kind: str = "text"  # text | number | list | bool | select | textarea | json
    required: bool = False
    default: Any = None
    help: str = ""
    options: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckSpec:
    key: str
    label: str
    group: str
    description: str
    #: Connector types a test of this check may use; empty = no connector needed.
    connector_types: tuple[str, ...]
    #: "connector" (pulls from the source) | "file" (an upload or the import folder) |
    #: "connector_or_file" | "none" (manual / pushed).
    input: str
    params: tuple[Param, ...]
    pass_criterion: str
    population: str
    run: Callable[[CheckContext], CheckOutcome] | None = None
    #: Extra validation beyond types: ``validate(params) -> list[str]``.
    validate: Callable[[dict], list[str]] | None = None


# ----------------------------------------------------------------- threshold ---
def exception_percent(population: int, exceptions: int) -> float:
    if population <= 0:
        return 0.0 if exceptions == 0 else 100.0
    return round(100.0 * exceptions / population, 2)


def pass_rate(population: int, exceptions: int) -> float:
    if population <= 0:
        return 100.0 if exceptions == 0 else 0.0
    return round(max(0.0, 100.0 * (population - exceptions) / population), 2)


def evaluate(outcome: CheckOutcome, max_failures: int | None, max_percent: float | None) -> bool:
    """Does this outcome pass the test's threshold? Pure.

    A value comparison (``outcome.passed`` set) decides for itself. Otherwise no threshold
    means no exception is allowed; each limit that is set must hold."""
    if outcome.passed is not None:
        return outcome.passed
    count = outcome.exceptions_count
    if max_failures is None and max_percent is None:
        return count == 0
    if max_failures is not None and count > int(max_failures):
        return False
    if max_percent is not None and exception_percent(outcome.population, count) > float(max_percent):
        return False
    return True


def threshold_text(max_failures: int | None, max_percent: float | None) -> str:
    """The threshold in words: "no exceptions", "at most 3 exceptions and 1%"."""
    parts = []
    if max_failures is not None:
        parts.append("no exceptions" if int(max_failures) == 0 else f"at most {int(max_failures)} exception"
                     + ("" if int(max_failures) == 1 else "s"))
    if max_percent is not None:
        parts.append(f"at most {float(max_percent):g}% of the population")
    return " and ".join(parts) if parts else "no exceptions"


# ---------------------------------------------------------------- comparisons ---
COMPARISON_OPS = ("==", "!=", "<", "<=", ">", ">=", "contains", "not_contains", "in", "not_in",
                  "is_true", "is_false", "is_empty", "not_empty")


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not (isinstance(value, float) and math.isnan(value)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1", "enabled", "on"}
    return bool(value)


def _items(expected: Any) -> list[str]:
    if isinstance(expected, (list, tuple, set)):
        return [str(x).strip().lower() for x in expected]
    return [p.strip().lower() for p in str(expected or "").split(",") if p.strip()]


def compare(actual: Any, op: str, expected: Any = None) -> bool:
    """``actual <op> expected``, numbers compared as numbers when both sides are. Pure."""
    if op not in COMPARISON_OPS:
        raise CheckError(f"Unknown comparison '{op}'.")
    if op == "is_true":
        return _truthy(actual)
    if op == "is_false":
        return not _truthy(actual)
    if op == "is_empty":
        return actual is None or actual == "" or actual == [] or actual == {}
    if op == "not_empty":
        return not compare(actual, "is_empty")
    if op in ("in", "not_in"):
        hit = str(actual if actual is not None else "").strip().lower() in _items(expected)
        return hit if op == "in" else not hit
    if op in ("contains", "not_contains"):
        if isinstance(actual, (list, tuple)):
            hit = str(expected).lower() in [str(x).lower() for x in actual]
        else:
            hit = str(expected).lower() in str(actual if actual is not None else "").lower()
        return hit if op == "contains" else not hit
    a, e = _num(actual), _num(expected)
    if a is not None and e is not None:
        return {"==": a == e, "!=": a != e, "<": a < e, "<=": a <= e, ">": a > e, ">=": a >= e}[op]
    if op in ("==", "!="):
        same = str(actual if actual is not None else "").strip().lower() == str(expected if expected is not None else "").strip().lower()
        return same if op == "==" else not same
    raise CheckError(f"Cannot compare {actual!r} {op} {expected!r}: both sides must be numbers.")


# ------------------------------------------------------------------ parameters ---
def as_list(value: Any) -> list[str]:
    """A list parameter from a list or from text (one per line or comma-separated)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value)
    parts = text.splitlines() if "\n" in text else text.split(",")
    return [p.strip() for p in parts if p.strip()]


def as_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def validate_params(spec: CheckSpec, params: dict) -> list[str]:
    """Type and required-field errors for a test's parameters, plus the check's own."""
    errors: list[str] = []
    for p in spec.params:
        value = params.get(p.name)
        empty = value is None or value == "" or value == []
        if p.required and empty:
            errors.append(f"{p.label}: required.")
            continue
        if empty:
            continue
        if p.kind == "number" and _num(value) is None:
            errors.append(f"{p.label}: must be a number.")
        elif p.kind == "select" and p.options and str(value) not in p.options:
            errors.append(f"{p.label}: must be one of {', '.join(p.options)}.")
        elif p.kind == "json" and not isinstance(value, (dict, list)):
            errors.append(f"{p.label}: must be a JSON object.")
    if spec.validate is not None:
        errors.extend(spec.validate(params))
    return errors


def with_defaults(spec: CheckSpec, params: dict | None) -> dict:
    out = {p.name: p.default for p in spec.params if p.default is not None}
    out.update({k: v for k, v in (params or {}).items() if v is not None and v != ""})
    return out


def label_of(row: dict, *fields: str) -> str:
    for f in fields:
        v = row.get(f)
        if v not in (None, ""):
            return str(v)
    return ""
