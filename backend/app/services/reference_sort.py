"""Natural order for clause references — A.5.2 before A.5.10, 4.1 before 10.1.

References are text, so ``ORDER BY reference`` puts "A.5.10" before "A.5.2" and "10.1"
before "4.1". Two views of one rule live here so they can never disagree:

* :func:`natural_key` — a tuple for sorting in Python (the SoA export, suggestions).
* :func:`reference_sort_key` — a string stored in ``requirements.reference_sort_key``
  that sorts the same way in SQL, so a paged list can ``ORDER BY`` it.

The string is built from the reference's runs of digits and letters (punctuation is a
separator and is dropped). Each run starts with a type marker — ``0`` for a number,
``1`` for a word — so numbers sort before words, as they do in the tuple. A number is
zero-padded to a fixed width; a word is lower-cased. Nothing but ``0-9`` and ``a-z``
ends up in the key, because database collations (en_US, ICU) ignore punctuation and
spaces at the first level and would otherwise reorder it.

Why a word needs no padding: a word run is followed by the end of the key or by a
type marker (a digit), and every digit sorts before every letter — so "ab" followed by
anything sorts before "abc", exactly as the tuple compares them.
"""
from __future__ import annotations

import re

#: Width a numeric run is padded to. Ten digits covers any clause number.
NUMBER_WIDTH = 10
#: The column is VARCHAR(255).
MAX_LENGTH = 255

_RUNS = re.compile(r"\d+|[A-Za-z]+")


def natural_key(reference: str | None) -> tuple:
    """"A.5.9" before "A.5.10"; letters compare case-insensitively."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in _RUNS.findall(reference or "")
    )


def reference_sort_key(reference: str | None) -> str:
    """The stored, SQL-sortable form of :func:`natural_key`.

    ``""`` for a blank reference, which sorts first — as the empty tuple does."""
    parts: list[str] = []
    for run in _RUNS.findall(reference or ""):
        if run.isdigit():
            digits = run.lstrip("0") or "0"
            parts.append("0" + digits.rjust(NUMBER_WIDTH, "0"))
        else:
            parts.append("1" + run.lower())
    return "".join(parts)[:MAX_LENGTH]
