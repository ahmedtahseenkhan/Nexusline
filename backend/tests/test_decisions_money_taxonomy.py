"""Decisions 4 and 5 (plan §11): reporting currency with exchange rates, Basel level 2.

No database: the conversion service and every roll-up that uses it are pure, and the
endpoints are driven with a fake session.

Pinned here:

1. **Rate selection** — the latest rate on or before the amount's date; a later rate is
   never used; a date before the first rate has none; the reporting currency converts
   1:1; a blank currency is the reporting currency.
2. **Nothing is mixed** — an amount with no rate is never added into a total; it is
   reported as ``unconverted`` with its currency, count and original sum.
3. **Loss roll-up** — by Basel level 1 and level 2, converted at each event's accounting
   date (else discovery, else occurrence), counts intact even when amounts are excluded.
4. **Basel taxonomy** — exactly 20 level-2 categories under the 7 level-1 types, with the
   Accord's names, and a level-2 category that belongs to another level-1 type is refused.
5. **Rates API** — a rate for the reporting currency itself is refused, a duplicate
   currency/date is a 409, and rates are audited.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import assets as assets_api
from app.api.v1 import fx_rates as fx_api
from app.api.v1 import operational_risk as oprisk_api
from app.api.v1 import outsourcing as outsourcing_api
from app.api.v1 import vendors as vendors_api
from app.models.enums import BaselEventType
from app.models.operational_risk import (
    BASEL_EVENT_TYPES_L2,
    BASEL_L1_LABELS,
    BASEL_L2_PARENT,
    basel_l2_error,
)
from app.schemas.fx import FxRateCreate
from app.schemas.operational_risk import LossEventCreate, LossEventUpdate
from app.services import audit as audit_service
from app.services import fx

pytestmark = pytest.mark.asyncio

USD_RATES = [
    ("USD", date(2026, 1, 1), Decimal("270.00")),
    ("USD", date(2026, 6, 30), Decimal("280.00")),
    ("AED", date(2026, 6, 30), Decimal("76.00")),
]


def book(rates=USD_RATES, reporting="PKR") -> fx.RateBook:
    return fx.RateBook(reporting, rates)


# ======================================================== 1. rate selection ===
def test_the_rate_in_force_on_the_amounts_date_is_used():
    b = book()
    assert b.rate_for("USD", date(2026, 3, 1)) == (Decimal("270.00"), date(2026, 1, 1))
    assert b.rate_for("USD", date(2026, 6, 30)) == (Decimal("280.00"), date(2026, 6, 30))
    assert b.rate_for("USD", date(2026, 9, 1)) == (Decimal("280.00"), date(2026, 6, 30))


def test_a_rate_dated_after_the_amount_is_never_used():
    assert book().rate_for("USD", date(2025, 12, 31)) is None
    assert book().convert(100, "USD", date(2025, 12, 31)).amount is None


def test_the_reporting_currency_converts_one_to_one_and_blank_means_it():
    b = book()
    assert b.convert(1000, "PKR", date(2020, 1, 1)).amount == Decimal(1000)
    blank = b.convert(1000, "", date(2020, 1, 1))
    assert blank.currency == "PKR" and blank.amount == Decimal(1000) and blank.rate == Decimal(1)
    assert b.convert(1000, None).amount == Decimal(1000)
    # A different reporting currency moves the 1:1 case with it.
    assert fx.RateBook("USD", []).convert(50, "usd").amount == Decimal(50)


def test_an_unknown_currency_has_no_rate():
    conv = book().convert(100, "GBP", date(2026, 7, 1))
    assert conv.amount is None and conv.converted is False
    assert "No GBP → PKR rate" in conv.note


def test_the_note_names_the_rate_that_was_used():
    conv = book().convert(100, "USD", date(2026, 7, 1))
    assert conv.amount == Decimal("28000.00")
    assert conv.note == "1 USD = 280 PKR (rate of 2026-06-30)"


# ================================================== 2. nothing gets mixed in ===
def test_amounts_without_a_rate_are_listed_not_added():
    total = fx.MoneyTotal(book())
    total.add(1_000_000, "PKR", date(2026, 7, 1))
    total.add(10_000, "USD", date(2026, 7, 1))       # 2,800,000
    total.add(5_000, "GBP", date(2026, 7, 1))        # no rate
    total.add(2_000, "GBP", date(2026, 7, 2))        # no rate
    out = total.as_dict()
    assert out["total"] == 3_800_000.00 and out["count"] == 4
    assert out["reporting_currency"] == "PKR"
    assert out["unconverted"] == [{"currency": "GBP", "count": 2, "amount": 7000.0}]
    by = {row["currency"]: row for row in out["by_currency"]}
    assert by["USD"]["amount"] == 10_000 and by["USD"]["converted"] == 2_800_000
    assert by["USD"]["latest_rate_date"] == date(2026, 6, 30)
    assert by["GBP"]["converted"] == 0


def test_a_grouped_sum_keeps_its_row_count():
    total = fx.MoneyTotal(book())
    total.add(300_000, "PKR", count=3)
    total.add(1_000, "GBP", count=2)
    out = total.as_dict()
    assert out["count"] == 5 and out["total"] == 300_000
    assert out["unconverted"] == [{"currency": "GBP", "count": 2, "amount": 1000.0}]


# ========================================================= 3. loss roll-up ====
def _loss(gross, recovery=0, currency="PKR", l1=BaselEventType.internal_fraud, l2="",
          accounting=None, discovery=None, occurrence=None):
    return SimpleNamespace(
        gross_loss=gross, recovery=recovery, currency=currency, basel_event_type=l1,
        basel_event_type_l2=l2, accounting_date=accounting, discovery_date=discovery,
        occurrence_date=occurrence,
    )


def test_a_loss_converts_at_its_accounting_date_then_discovery_then_occurrence():
    booked = _loss(100, accounting=date(2026, 2, 1), discovery=date(2026, 7, 1))
    assert fx.loss_conversion_date(booked) == date(2026, 2, 1)
    assert fx.loss_conversion_date(_loss(100, discovery=date(2026, 7, 1), occurrence=date(2026, 1, 5))) == date(2026, 7, 1)
    assert fx.loss_conversion_date(_loss(100, occurrence=date(2026, 1, 5))) == date(2026, 1, 5)
    assert fx.loss_conversion_date(_loss(100)) is None


def test_the_loss_summary_never_mixes_currencies():
    events = [
        _loss(1_000_000, 200_000, "PKR", accounting=date(2026, 7, 1)),
        _loss(10_000, 0, "USD", l2="unauthorised_activity", accounting=date(2026, 2, 1)),   # 270
        _loss(500, 0, "GBP", accounting=date(2026, 7, 1)),                                   # no rate
    ]
    out = oprisk_api.summarise_losses(events, book())
    assert out.reporting_currency == "PKR"
    assert out.total_count == 3                      # every event is counted
    assert out.total_gross == 1_000_000 + 2_700_000  # the GBP loss is not added
    assert out.total_net == 800_000 + 2_700_000
    assert [u.model_dump() for u in out.unconverted] == [{"currency": "GBP", "count": 1, "amount": 500.0}]
    (row,) = out.rows
    assert row.basel_event_type == "internal_fraud" and row.label == "Internal fraud"
    assert row.count == 3 and row.unconverted_count == 1
    by_l2 = {r.basel_event_type_l2: r for r in row.level2}
    assert by_l2["unauthorised_activity"].gross_loss == 2_700_000
    assert by_l2[""].count == 2 and by_l2[""].label == "Not categorised at level 2"


def test_the_summary_orders_the_event_types_as_the_accord_does():
    events = [
        _loss(1, l1=BaselEventType.execution_delivery_process_management),
        _loss(1, l1=BaselEventType.internal_fraud),
        _loss(1, l1=BaselEventType.damage_to_physical_assets),
    ]
    out = oprisk_api.summarise_losses(events, book())
    assert [r.basel_event_type for r in out.rows] == [
        "internal_fraud", "damage_to_physical_assets", "execution_delivery_process_management",
    ]


# ==================================================== 4. the Basel taxonomy ===
def test_basel_level_two_has_the_twenty_annex_nine_categories():
    assert len(BASEL_EVENT_TYPES_L2) == 20
    assert len({k for k, *_ in BASEL_EVENT_TYPES_L2}) == 20
    counts: dict[str, int] = {}
    for _key, parent, _name, _examples in BASEL_EVENT_TYPES_L2:
        counts[parent] = counts.get(parent, 0) + 1
    assert counts == {
        "internal_fraud": 2,
        "external_fraud": 2,
        "employment_practices": 3,
        "clients_products_business_practices": 5,
        "damage_to_physical_assets": 1,
        "business_disruption_system_failure": 1,
        "execution_delivery_process_management": 6,
    }
    assert set(counts) == {e.value for e in BaselEventType} == set(BASEL_L1_LABELS)
    names = {name for _k, _p, name, _e in BASEL_EVENT_TYPES_L2}
    assert {"Unauthorised activity", "Theft and fraud", "Systems security", "Employee relations",
            "Safe environment", "Diversity & discrimination", "Product flaws", "Advisory activities",
            "Disasters and other events", "Systems", "Monitoring and reporting",
            "Vendors & suppliers"} <= names
    # "Theft and fraud" is both an internal and an external category, under its own key.
    assert BASEL_L2_PARENT["internal_theft_and_fraud"] == "internal_fraud"
    assert BASEL_L2_PARENT["external_theft_and_fraud"] == "external_fraud"


def test_the_taxonomy_endpoint_hands_the_ui_seven_types_and_twenty_categories():
    nodes = oprisk_api.basel_taxonomy()
    assert len(nodes) == 7
    assert sum(len(n.level2) for n in nodes) == 20
    internal = next(n for n in nodes if n.value == "internal_fraud")
    assert [c.label for c in internal.level2] == ["Unauthorised activity", "Theft and fraud"]
    assert "mismarking of position" in internal.level2[0].examples


def test_a_level_two_category_must_belong_to_the_level_one_type():
    assert basel_l2_error(BaselEventType.internal_fraud, "unauthorised_activity") is None
    assert basel_l2_error(BaselEventType.internal_fraud, "") is None   # blank is allowed
    assert basel_l2_error(BaselEventType.internal_fraud, None) is None
    wrong = basel_l2_error(BaselEventType.external_fraud, "unauthorised_activity")
    assert wrong and "belongs under Internal fraud" in wrong
    assert "not a Basel II level-2 event category" in basel_l2_error(BaselEventType.internal_fraud, "made_up")


def test_the_loss_form_refuses_a_level_two_from_another_event_type():
    ok = LossEventCreate(title="Card skimming", basel_event_type=BaselEventType.external_fraud,
                         basel_event_type_l2="external_theft_and_fraud")
    assert ok.basel_event_type_l2 == "external_theft_and_fraud"
    with pytest.raises(ValidationError) as exc:
        LossEventCreate(title="Wrong", basel_event_type=BaselEventType.external_fraud,
                        basel_event_type_l2="unauthorised_activity")
    assert "belongs under Internal fraud" in str(exc.value)


def test_an_update_checks_the_level_two_against_the_type_the_record_ends_up_with():
    record = SimpleNamespace(basel_event_type=BaselEventType.internal_fraud,
                             basel_event_type_l2="unauthorised_activity")
    patch = LossEventUpdate(basel_event_type=BaselEventType.external_fraud).model_dump(exclude_unset=True)
    with pytest.raises(HTTPException) as exc:
        oprisk_api.check_loss_taxonomy(record, patch)
    assert exc.value.status_code == 422 and "belongs under Internal fraud" in exc.value.detail
    # Sending both together is fine, and the level-2 category can always be cleared.
    both = LossEventUpdate(basel_event_type=BaselEventType.external_fraud,
                           basel_event_type_l2="systems_security").model_dump(exclude_unset=True)
    oprisk_api.check_loss_taxonomy(record, both)
    cleared = LossEventUpdate(basel_event_type_l2="").model_dump(exclude_unset=True)
    oprisk_api.check_loss_taxonomy(record, cleared)
    assert cleared["basel_event_type_l2"] == ""


def test_an_existing_loss_event_keeps_an_empty_level_two():
    # Nothing is guessed for events recorded before level 2 existed.
    assert LossEventCreate(title="Old event").basel_event_type_l2 == ""


# ============================================ 5. totals elsewhere in the app ===
def _contract(value, currency="", expired=False):
    return SimpleNamespace(value=value, currency=currency, is_expired=expired)


def test_vendor_contract_totals_convert_and_keep_the_breakdown():
    out = vendors_api.contract_total(
        [_contract(1_000_000, "PKR"), _contract(250_000, ""), _contract(10_000, "USD"),
         _contract(99, "USD", expired=True), _contract(400, "GBP")],
        book(),
    )
    assert out["total"] == 1_250_000 + 2_800_000
    assert out["unconverted"] == [{"currency": "GBP", "count": 1, "amount": 400.0}]
    # The per-currency view the page already shows is unchanged.
    assert vendors_api.contract_totals(
        [_contract(1_000_000, "PKR"), _contract(10_000, "USD")], "PKR"
    ) == {"PKR": 1_000_000, "USD": 10_000}


def test_vendor_spend_summary_converts_spend_and_live_contracts():
    vendors = [
        SimpleNamespace(annual_spend=12_000_000, spend_currency="PKR", status="active",
                        contracts=[_contract(1_000_000, "PKR")]),
        SimpleNamespace(annual_spend=10_000, spend_currency="USD", status="active",
                        contracts=[_contract(5_000, "USD")]),
        SimpleNamespace(annual_spend=None, spend_currency="", status="active",
                        contracts=[_contract(100, "GBP")]),
        # Offboarded: no longer a cost, though its contract still has to run out.
        SimpleNamespace(annual_spend=9_000_000, spend_currency="PKR", status="offboarded", contracts=[]),
    ]
    out = vendors_api.spend_summary(vendors, book())
    assert out.vendors == 4
    assert out.annual_spend.total == 12_000_000 + 2_800_000
    assert out.active_contracts.total == 1_000_000 + 1_400_000
    assert [u.currency for u in out.active_contracts.unconverted] == ["GBP"]


async def test_the_asset_replacement_total_is_converted_per_currency():
    class GroupedDB:
        async def execute(self, *_a, **_k):
            return SimpleNamespace(all=lambda: [("PKR", 5_000_000, 4), ("USD", 10_000, 2), ("GBP", 700, 1)])

        async def scalar(self, *_a, **_k):
            return "PKR"

    async def rate_book(db, tenant_id=None, reporting=None):
        return book()

    original = fx.load_rate_book
    fx.load_rate_book = rate_book
    try:
        out = await assets_api.replacement_value(GroupedDB(), [])
    finally:
        fx.load_rate_book = original
    assert out["total"] == 5_000_000 + 2_800_000
    assert out["count"] == 7
    assert out["unconverted"] == [{"currency": "GBP", "count": 1, "amount": 700.0}]


async def test_the_outsourcing_summary_totals_contract_value(monkeypatch):
    async def rate_book(db, tenant_id=None, reporting=None):
        return book()

    monkeypatch.setattr(outsourcing_api.fx, "load_rate_book", rate_book)
    rows = [
        _arrangement(contract_value=Decimal("4000000"), contract_currency=""),
        _arrangement(contract_value=Decimal("10000"), contract_currency="USD"),
        _arrangement(contract_value=Decimal("500"), contract_currency="GBP"),
        _arrangement(contract_value=Decimal("999"), contract_currency="PKR",
                     status=outsourcing_api.OutsourcingStatus.terminated),
    ]
    out = await outsourcing_api.outsourcing_summary(_RowsDB(rows))
    assert out.contract_value.total == 4_000_000 + 2_800_000  # the terminated one is left out
    assert out.contract_value.reporting_currency == "PKR"
    assert [u.currency for u in out.contract_value.unconverted] == ["GBP"]


class _RowsDB:
    def __init__(self, rows):
        self.rows = rows

    async def scalars(self, *_a, **_k):
        return SimpleNamespace(all=lambda: self.rows)


def _arrangement(**kw):
    base = dict(
        materiality=outsourcing_api.OutsourcingMateriality.non_material,
        status=outsourcing_api.OutsourcingStatus.active, is_cloud=False,
        sbp_approval_status=outsourcing_api.SbpApprovalStatus.not_required,
        is_contract_expiring=False, exit_plan_tested=True, exit_plan="Plan",
        substitutability="easy", concentration_level="low", missing_for_activation=[],
        contract_value=None, contract_currency="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ================================================================ 6. the API ===
class _FakeDB:
    def __init__(self, scalar=None, rows=None):
        self.scalar_result = scalar
        self.rows = rows or []
        self.added: list = []
        self.flushed = 0

    async def scalar(self, *_a, **_k):
        result = self.scalar_result
        return result(*_a) if callable(result) else result

    async def scalars(self, *_a, **_k):
        rows = self.rows
        return SimpleNamespace(all=lambda: rows)

    async def execute(self, *_a, **_k):
        return SimpleNamespace(all=lambda: [])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        # A real flush fills the column defaults (id, timestamps) before the row is read back.
        self.flushed += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


def _user():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="risk@bank.pk",
                           full_name="Risk Officer", permission_codes=["settings:manage"])


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit_service, "record", record)
    return calls


async def test_a_rate_for_the_reporting_currency_is_refused(audit_calls):
    db = _FakeDB(scalar="PKR")
    body = FxRateCreate(currency="PKR", rate_to_reporting=Decimal("1"), effective_date=date(2026, 7, 1))
    with pytest.raises(HTTPException) as exc:
        await fx_api.create_rate(body, db, _user())
    assert exc.value.status_code == 422 and "reporting currency" in exc.value.detail
    assert db.added == [] and audit_calls == []


async def test_a_second_rate_for_the_same_currency_and_day_is_a_conflict(audit_calls):
    existing = SimpleNamespace(id=uuid.uuid4())
    db = _FakeDB(scalar=lambda *_: existing)
    # The first scalar call returns the reporting currency, the second the clashing rate.
    calls = iter(["PKR", existing])
    db.scalar_result = lambda *_: next(calls)
    body = FxRateCreate(currency="USD", rate_to_reporting=Decimal("280"), effective_date=date(2026, 7, 1))
    with pytest.raises(HTTPException) as exc:
        await fx_api.create_rate(body, db, _user())
    assert exc.value.status_code == 409 and "2026-07-01" in exc.value.detail


async def test_adding_a_rate_records_it_in_the_activity_log(audit_calls):
    calls = iter(["PKR", None])
    db = _FakeDB()
    db.scalar_result = lambda *_: next(calls)
    user = _user()
    body = FxRateCreate(currency="usd", rate_to_reporting=Decimal("278.45"),
                        effective_date=date(2026, 7, 1), source="SBP weighted average")
    out = await fx_api.create_rate(body, db, user)
    assert out.currency == "USD" and out.reporting_currency == "PKR"
    assert out.rate_to_reporting == Decimal("278.45") and out.created_by_id == user.id
    (entry,) = audit_calls
    assert entry["action"] == "create" and entry["entity_type"] == "fx_rate"
    assert "1 USD = 278.45 PKR from 2026-07-01" in entry["summary"]


def test_an_unsupported_currency_code_is_refused():
    with pytest.raises(ValidationError):
        FxRateCreate(currency="XYZ", rate_to_reporting=Decimal("1"), effective_date=date(2026, 7, 1))
    with pytest.raises(ValidationError):  # a rate must be positive
        FxRateCreate(currency="USD", rate_to_reporting=Decimal("0"), effective_date=date(2026, 7, 1))


def test_the_rate_list_summarises_the_latest_rate_per_currency():
    rows = [
        SimpleNamespace(currency="USD", rate_to_reporting=Decimal("270"), effective_date=date(2026, 1, 1)),
        SimpleNamespace(currency="USD", rate_to_reporting=Decimal("280"), effective_date=date(2026, 6, 30)),
        SimpleNamespace(currency="AED", rate_to_reporting=Decimal("76"), effective_date=date(2026, 6, 30)),
    ]
    usd, aed = sorted(fx_api.summarise(rows, today=date(2026, 7, 30)), key=lambda s: s.currency == "USD")
    assert (usd.currency, usd.rate_count) == ("AED", 1)
    assert aed.currency == "USD" and aed.latest_rate == Decimal("280") and aed.rate_count == 2
    assert aed.age_days == 30 and aed.name == "US Dollar"
