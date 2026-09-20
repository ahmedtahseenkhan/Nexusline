"""A tiny dotted-path selector for JSON (no dependency).

``data.items`` · ``data.items[0].name`` · ``data.items.0.name`` · ``hosts[*].status`` (or
``hosts.*.status``) maps over a list and returns a list. A missing key returns
:data:`MISSING` (``select`` returns ``None`` for it), never an exception, so a check can
say "the selector found nothing" in words.
"""
from __future__ import annotations

import re
from typing import Any

MISSING = object()
_TOKEN = re.compile(r"[^.\[\]]+|\[(\*|-?\d+)\]")


def parse(path: str) -> list[str]:
    """``a.b[0][*].c`` → ``["a", "b", "0", "*", "c"]``. Pure."""
    text = (path or "").strip()
    if text in ("", "$", "."):
        return []
    if text.startswith("$."):
        text = text[2:]
    tokens: list[str] = []
    for m in _TOKEN.finditer(text):
        tokens.append(m.group(1) if m.group(1) is not None else m.group(0))
    return tokens


def _step(value: Any, token: str) -> Any:
    if isinstance(value, dict):
        return value.get(token, MISSING)
    if isinstance(value, list):
        try:
            index = int(token)
        except ValueError:
            return MISSING
        if -len(value) <= index < len(value):
            return value[index]
        return MISSING
    return MISSING


def resolve(data: Any, path: str) -> Any:
    """The value at ``path``, or :data:`MISSING`. Pure."""
    tokens = parse(path)
    return _walk(data, tokens)


def _walk(value: Any, tokens: list[str]) -> Any:
    for i, token in enumerate(tokens):
        if value is MISSING:
            return MISSING
        if token == "*":
            if isinstance(value, dict):
                items = list(value.values())
            elif isinstance(value, list):
                items = value
            else:
                return MISSING
            rest = tokens[i + 1:]
            out = [_walk(item, rest) for item in items]
            return [v for v in out if v is not MISSING]
        value = _step(value, token)
    return value


def select(data: Any, path: str, default: Any = None) -> Any:
    value = resolve(data, path)
    return default if value is MISSING else value
