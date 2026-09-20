"""Currency conversion to the reporting currency (plan §11 decision 4).

Rules, in one place, so every total in the product follows them:

* The **reporting currency** is ``TenantSettings.currency`` (PKR unless changed).
* An amount in the reporting currency converts 1:1. A **blank** currency means the
  reporting currency (vendor spend and contracts recorded before they carried one).
* Any other currency converts at the **latest rate whose effective date is on or before
  the amount's date** (``fx_rates``, entered by the bank). A rate dated after the amount
  is never used — a loss discovered in March is not revalued at a September rate.
* An amount with **no usable rate is never added in**. It is reported separately as
  ``unconverted`` (currency, count, original sum) so the screen can say "Excludes 3 USD
  amounts with no exchange rate".

Which date each module converts at is decided by its caller and documented there:
loss events at the accounting date (Basel II / ORX: the date the loss hit the P&L),
falling back to discovery, then occurrence, then today; stock figures (asset replacement cost,
annual vendor spend, live contract value) at today's rate.

:class:`RateBook` is pure and holds every rate for the reporting currency, so an
aggregation loads rates once (:func:`load_rate_book`) and converts in memory.
"""
from __future__ import annotations

import bisect
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

DEFAULT_REPORTING_CURRENCY = "PKR"
_CENT = Decimal("0.01")


def normalise(code: Any, reporting_currency: str) -> str:
    """An upper-case currency code; blank/None means the reporting currency."""
    text = str(code or "").strip().upper()
    return text or reporting_currency


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def money(value: Decimal) -> float:
    """A Decimal amount rounded to cents, as a float for JSON responses."""
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Conversion:
    """The result of converting one amount.

    ``amount`` is the converted value in the reporting currency, or ``None`` when no rate
    applies ("no rate"). ``rate`` and ``rate_date`` are the rate used (1 and ``None`` for
    the reporting currency itself).
    """

    original: Decimal
    currency: str
    reporting_currency: str
    amount: Decimal | None
    rate: Decimal | None
    rate_date: date | None

    @property
    def converted(self) -> bool:
        return self.amount is not None

    @property
    def note(self) -> str:
        if self.amount is None:
            return f"No {self.currency} → {self.reporting_currency} rate on or before the amount's date"
        if self.rate_date is None:
            return ""
        return f"1 {self.currency} = {self.rate.normalize():f} {self.reporting_currency} (rate of {self.rate_date.isoformat()})"


class RateBook:
    """Every rate into one reporting currency, indexed per currency by effective date. Pure."""

    def __init__(self, reporting_currency: str | None, rates: Iterable[tuple[str, date, Any]] = ()):
        self.reporting_currency = normalise(reporting_currency, DEFAULT_REPORTING_CURRENCY)
        series: dict[str, list[tuple[date, Decimal]]] = {}
        for code, effective, rate in rates:
            value = _decimal(rate)
            if effective is None or value is None or value <= 0:
                continue
            series.setdefault(normalise(code, self.reporting_currency), []).append((effective, value))
        self._dates: dict[str, list[date]] = {}
        self._rates: dict[str, list[Decimal]] = {}
        for code, points in series.items():
            points.sort(key=lambda p: p[0])
            self._dates[code] = [d for d, _ in points]
            self._rates[code] = [r for _, r in points]

    def currencies(self) -> list[str]:
        return sorted(self._dates)

    def rate_for(self, currency: Any, on_date: date | None = None) -> tuple[Decimal, date | None] | None:
        """``(rate, rate_date)`` for ``currency`` on ``on_date`` (today when None), or None."""
        code = normalise(currency, self.reporting_currency)
        if code == self.reporting_currency:
            return Decimal(1), None
        dates = self._dates.get(code)
        if not dates:
            return None
        idx = bisect.bisect_right(dates, on_date or date.today()) - 1
        if idx < 0:
            return None
        return self._rates[code][idx], dates[idx]

    def convert(self, amount: Any, currency: Any, on_date: date | None = None) -> Conversion:
        original = _decimal(amount) or Decimal(0)
        code = normalise(currency, self.reporting_currency)
        found = self.rate_for(code, on_date)
        if found is None:
            return Conversion(original, code, self.reporting_currency, None, None, None)
        rate, rate_date = found
        return Conversion(original, code, self.reporting_currency, original * rate, rate, rate_date)


@dataclass
class _Bucket:
    count: int = 0
    original: Decimal = field(default_factory=lambda: Decimal(0))
    converted: Decimal = field(default_factory=lambda: Decimal(0))


class MoneyTotal:
    """Adds amounts in any currency into one reporting-currency total.

    Amounts without a rate go to ``unconverted`` instead of the total. ``by_currency``
    keeps the original per-currency breakdown (including unconverted amounts), so a
    screen can show both "PKR 12.4m" and "of which USD 40,000 at 278.50".
    """

    def __init__(self, book: RateBook):
        self.book = book
        self.total = Decimal(0)
        self.count = 0
        self._by: dict[str, _Bucket] = {}
        self._missing: dict[str, _Bucket] = {}
        self._rate_dates: dict[str, date] = {}

    @property
    def reporting_currency(self) -> str:
        return self.book.reporting_currency

    def add(self, amount: Any, currency: Any, on_date: date | None = None, *, count: int = 1) -> Conversion:
        """Add one amount — or, with ``count``, a pre-summed group of amounts that share a
        currency and conversion date (e.g. a SQL ``GROUP BY currency`` converted at today's rate)."""
        conv = self.book.convert(amount, currency, on_date)
        self.count += count
        bucket = self._by.setdefault(conv.currency, _Bucket())
        bucket.count += count
        bucket.original += conv.original
        if conv.amount is None:
            miss = self._missing.setdefault(conv.currency, _Bucket())
            miss.count += count
            miss.original += conv.original
        else:
            self.total += conv.amount
            bucket.converted += conv.amount
            if conv.rate_date is not None:
                prev = self._rate_dates.get(conv.currency)
                if prev is None or conv.rate_date > prev:
                    self._rate_dates[conv.currency] = conv.rate_date
        return conv

    def merge(self, other: "MoneyTotal") -> None:
        self.total += other.total
        self.count += other.count
        for src, dst in ((other._by, self._by), (other._missing, self._missing)):
            for code, b in src.items():
                t = dst.setdefault(code, _Bucket())
                t.count += b.count
                t.original += b.original
                t.converted += b.converted
        for code, d in other._rate_dates.items():
            if code not in self._rate_dates or d > self._rate_dates[code]:
                self._rate_dates[code] = d

    @property
    def unconverted_count(self) -> int:
        return sum(b.count for b in self._missing.values())

    def as_dict(self) -> dict:
        """The JSON shape of ``schemas.fx.MoneyTotalRead``."""
        return {
            "reporting_currency": self.reporting_currency,
            "total": money(self.total),
            "count": self.count,
            "by_currency": [
                {
                    "currency": code,
                    "count": b.count,
                    "amount": money(b.original),
                    "converted": money(b.converted),
                    "latest_rate_date": self._rate_dates.get(code),
                }
                for code, b in sorted(self._by.items())
            ],
            "unconverted": [
                {"currency": code, "count": b.count, "amount": money(b.original)}
                for code, b in sorted(self._missing.items())
            ],
        }


# ------------------------------------------------------------------ database helpers
async def reporting_currency(db, tenant_id: uuid.UUID | None = None) -> str:
    """The organisation's reporting currency; PKR when never set."""
    from app.models.settings import TenantSettings

    stmt = select(TenantSettings.currency)
    if tenant_id is not None:
        stmt = stmt.where(TenantSettings.tenant_id == tenant_id)
    value = await db.scalar(stmt.limit(1))
    return value.upper() if isinstance(value, str) and value.strip() else DEFAULT_REPORTING_CURRENCY


async def load_rate_book(db, tenant_id: uuid.UUID | None = None, reporting: str | None = None) -> RateBook:
    """Every rate into the reporting currency, loaded in one query."""
    from app.models.fx import FxRate

    code = reporting or await reporting_currency(db, tenant_id)
    stmt = select(FxRate.currency, FxRate.effective_date, FxRate.rate_to_reporting).where(
        FxRate.reporting_currency == code
    )
    if tenant_id is not None:
        stmt = stmt.where(FxRate.tenant_id == tenant_id)
    result = await db.execute(stmt)
    rows = result.all() if hasattr(result, "all") else []
    return RateBook(code, [tuple(r) for r in rows])


async def convert(db, amount: Any, currency: Any, on_date: date | None = None,
                  tenant_id: uuid.UUID | None = None) -> Conversion:
    """Convert one amount (loads the rates; use :func:`load_rate_book` for many)."""
    return (await load_rate_book(db, tenant_id)).convert(amount, currency, on_date)


def loss_conversion_date(event) -> date | None:
    """The date a loss event converts at: accounting date (when the loss was booked —
    Basel II / ORX report losses at the accounting date), else discovery, else occurrence,
    else today."""
    return (
        getattr(event, "accounting_date", None)
        or getattr(event, "discovery_date", None)
        or getattr(event, "occurrence_date", None)
    )
