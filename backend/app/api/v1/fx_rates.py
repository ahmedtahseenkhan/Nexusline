"""Exchange rates API — ``/settings/exchange-rates`` (plan §11 decision 4).

The bank maintains its own rates into the reporting currency: on-premises installations
have no internet feed, and a bank reports at its own treasury or SBP rates anyway.

* ``GET    /settings/exchange-rates`` — any signed-in user. Every rate into the current
  reporting currency (newest first), a per-currency summary with the latest rate and its
  age, and ``missing``: currencies used on records that have no rate yet.
* ``GET    /settings/exchange-rates/convert`` — any signed-in user. Preview one
  conversion (``amount``, ``currency``, ``on_date``) with the rate used.
* ``POST   /settings/exchange-rates`` — ``settings:manage``. Add a rate; a second rate for
  the same currency and date is a 409 (edit the existing one). The reporting currency
  itself needs no rate and is refused.
* ``PATCH  /settings/exchange-rates/{id}`` — ``settings:manage``. Correct a rate, its date
  or its source.
* ``DELETE /settings/exchange-rates/{id}`` — ``settings:manage``.

Every write is audited. CSV import goes through the generic import engine (resource
``fx-rates``), which calls :func:`upsert_rate` so re-importing a file updates rates in
place rather than failing on duplicates.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require
from app.models.fx import FxRate
from app.models.identity import User
from app.schemas.fx import (
    ConversionPreview,
    FxCurrencySummary,
    FxRateCreate,
    FxRateList,
    FxRateRead,
    FxRateUpdate,
)
from app.schemas.tenant_settings import CURRENCIES
from app.services import audit
from app.services import fx

router = APIRouter(prefix="/settings/exchange-rates", tags=["settings"])
_MANAGE = Depends(require("settings:manage"))

REPORTING_CURRENCY_REFUSAL = (
    "{code} is the reporting currency; amounts in it are never converted, so it needs no rate."
)
DUPLICATE_REFUSAL = (
    "There is already a {code} rate effective {day}. Edit that rate instead of adding a second one."
)


def _currency_columns():
    """Every column holding the currency of an amount (blank = reporting currency)."""
    from app.models import (
        aml, asset, authority, bia, declaration, fraud, operational_risk, outsourcing,
        risk_quant, scenario, shariah, vendor,
    )

    return [
        operational_risk.LossEvent.currency,
        asset.Asset.currency,
        bia.BiaAssessment.currency,
        fraud.FraudCase.currency,
        risk_quant.RiskQuantification.currency,
        scenario.ScenarioAnalysis.currency,
        scenario.CapitalCalculation.currency,
        aml.SuspiciousActivityReport.currency,
        authority.AuthorityMatrix.currency,
        authority.DualControlRule.currency,
        declaration.Declaration.currency,
        shariah.CharityDisbursement.currency,
        vendor.Vendor.spend_currency,
        vendor.ServiceContract.currency,
        outsourcing.OutsourcingArrangement.contract_currency,
    ]


async def currencies_in_use(db) -> set[str]:
    """Distinct currency codes recorded on money fields, in one UNION query.

    Each branch is distinct in itself, so the union merges a handful of rows per register
    rather than one per record. Read once when the settings page opens.
    """
    from sqlalchemy import union

    stmt = union(*(select(col.label("code")).where(col != "").distinct() for col in _currency_columns()))
    rows = (await db.execute(stmt)).all()
    return {str(r[0]).strip().upper() for r in rows if r[0] and str(r[0]).strip()}


def _read(row: FxRate, names: dict) -> FxRateRead:
    item = FxRateRead.model_validate(row)
    item.created_by_name = names.get(row.created_by_id, "")
    return item


async def _names(db, rows) -> dict:
    ids = {r.created_by_id for r in rows if r.created_by_id}
    if not ids:
        return {}
    users = (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    return {u.id: (u.full_name or u.email) for u in users}


def summarise(rows, today: date | None = None) -> list[FxCurrencySummary]:
    """Latest rate per currency. Pure."""
    today = today or date.today()
    latest: dict[str, FxRate] = {}
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.currency] = counts.get(r.currency, 0) + 1
        if r.currency not in latest or r.effective_date > latest[r.currency].effective_date:
            latest[r.currency] = r
    return [
        FxCurrencySummary(
            currency=code, name=CURRENCIES.get(code, ""), latest_rate=r.rate_to_reporting,
            latest_date=r.effective_date, rate_count=counts[code],
            age_days=max((today - r.effective_date).days, 0),
        )
        for code, r in sorted(latest.items())
    ]


@router.get("", response_model=FxRateList)
async def list_rates(
    db: DbSession, user: CurrentUser, currency: str | None = Query(default=None, max_length=3)
) -> FxRateList:
    """Every rate into the reporting currency. Any signed-in user."""
    reporting = await fx.reporting_currency(db, user.tenant_id)
    stmt = select(FxRate).where(FxRate.reporting_currency == reporting)
    all_rows = list((await db.scalars(stmt)).all())
    rows = [r for r in all_rows if not currency or r.currency == currency.strip().upper()]
    rows.sort(key=lambda r: (r.effective_date, r.currency), reverse=True)
    names = await _names(db, rows)
    in_use = await currencies_in_use(db)
    have = {r.currency for r in all_rows}
    return FxRateList(
        reporting_currency=reporting,
        currencies=summarise(all_rows),
        items=[_read(r, names) for r in rows],
        missing=sorted(c for c in in_use if c != reporting and c not in have),
    )


@router.get("/convert", response_model=ConversionPreview)
async def preview_conversion(
    db: DbSession, user: CurrentUser,
    amount: float = Query(...), currency: str = Query(default=""), on_date: date | None = None,
) -> ConversionPreview:
    """What ``amount`` in ``currency`` on ``on_date`` is in the reporting currency."""
    conv = await fx.convert(db, amount, currency, on_date, tenant_id=user.tenant_id)
    return ConversionPreview(
        amount=amount, currency=conv.currency, reporting_currency=conv.reporting_currency,
        converted=fx.money(conv.amount) if conv.amount is not None else None,
        rate=conv.rate, rate_date=conv.rate_date, note=conv.note,
    )


async def _existing(db, currency: str, reporting: str, effective: date, exclude: uuid.UUID | None = None):
    stmt = select(FxRate).where(
        FxRate.currency == currency, FxRate.reporting_currency == reporting,
        FxRate.effective_date == effective,
    )
    row = await db.scalar(stmt)
    return None if row is None or row.id == exclude else row


def _describe(row: FxRate) -> str:
    return (f"1 {row.currency} = {Decimal(row.rate_to_reporting).normalize():f} "
            f"{row.reporting_currency} from {row.effective_date.isoformat()}")


async def upsert_rate(body: FxRateCreate, db, user) -> FxRate:
    """Add a rate, or update the rate already on file for that currency and date.

    Used by the CSV import (``fx-rates``); the create endpoint refuses duplicates instead.
    """
    reporting = await fx.reporting_currency(db, user.tenant_id)
    if body.currency == reporting:
        raise ValueError(REPORTING_CURRENCY_REFUSAL.format(code=reporting))
    row = await _existing(db, body.currency, reporting, body.effective_date)
    if row is None:
        row = FxRate(
            tenant_id=user.tenant_id, currency=body.currency, reporting_currency=reporting,
            rate_to_reporting=body.rate_to_reporting, effective_date=body.effective_date,
            source=body.source, created_by_id=user.id,
        )
        db.add(row)
    else:
        row.rate_to_reporting = body.rate_to_reporting
        if body.source:
            row.source = body.source
    await db.flush()
    return row


@router.post("", response_model=FxRateRead, status_code=201, dependencies=[_MANAGE])
async def create_rate(body: FxRateCreate, db: DbSession, user: CurrentUser) -> FxRateRead:
    reporting = await fx.reporting_currency(db, user.tenant_id)
    if body.currency == reporting:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, REPORTING_CURRENCY_REFUSAL.format(code=reporting))
    if await _existing(db, body.currency, reporting, body.effective_date) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            DUPLICATE_REFUSAL.format(code=body.currency, day=body.effective_date.isoformat()),
        )
    row = FxRate(
        tenant_id=user.tenant_id, currency=body.currency, reporting_currency=reporting,
        rate_to_reporting=body.rate_to_reporting, effective_date=body.effective_date,
        source=body.source.strip(), created_by_id=user.id,
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db, actor=user, action="create", entity_type="fx_rate", entity_id=row.id,
        summary=f"Added exchange rate {_describe(row)}",
        changes={"currency": row.currency, "rate": str(row.rate_to_reporting),
                 "effective_date": row.effective_date.isoformat(), "source": row.source},
    )
    return _read(row, {user.id: getattr(user, "full_name", "") or getattr(user, "email", "")})


async def _get(db, rate_id: uuid.UUID) -> FxRate:
    row = await db.get(FxRate, rate_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exchange rate not found")
    return row


@router.patch("/{rate_id}", response_model=FxRateRead, dependencies=[_MANAGE])
async def update_rate(rate_id: uuid.UUID, body: FxRateUpdate, db: DbSession, user: CurrentUser) -> FxRateRead:
    row = await _get(db, rate_id)
    patch = body.model_dump(exclude_unset=True, exclude_none=True)
    if "effective_date" in patch and patch["effective_date"] != row.effective_date:
        if await _existing(db, row.currency, row.reporting_currency, patch["effective_date"], exclude=row.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                DUPLICATE_REFUSAL.format(code=row.currency, day=patch["effective_date"].isoformat()),
            )
    changes = {}
    for name, value in patch.items():
        if name == "source":
            value = value.strip()
        old = getattr(row, name)
        if old != value:
            changes[name] = {"from": str(old), "to": str(value)}
            setattr(row, name, value)
    if changes:
        await db.flush()
        await audit.record(
            db, actor=user, action="update", entity_type="fx_rate", entity_id=row.id,
            summary=f"Changed exchange rate: now {_describe(row)}", changes=changes,
        )
    return _read(row, await _names(db, [row]))


@router.delete("/{rate_id}", status_code=204, dependencies=[_MANAGE])
async def delete_rate(rate_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    row = await _get(db, rate_id)
    summary = f"Deleted exchange rate {_describe(row)}"
    await db.delete(row)
    await db.flush()
    await audit.record(db, actor=user, action="delete", entity_type="fx_rate", entity_id=rate_id, summary=summary)
