"""Remaining verified gaps, 2026-09-25. No database.

Pinned here:

1. **Currency** — every money currency a schema accepts is a three-letter ISO 4217 code,
   upper-cased; blank falls back to PKR; reads never re-validate a legacy row.
2. **Data protection** — archiving a DPIA, DSAR, consent record or breach is audited.
3. **BIA** — a dependency's asset carries its class, so the chip opens the right register.
4. **TAT clock** — an audit finding is clocked from its engagement's report date, else
   the end of fieldwork, else creation (IIA 2440 / 2500).
5. **SMA capital** — marking a calculation final freezes the rate, edges and figures;
   later rates don't restate it; inputs are locked; reopening needs a reason and is
   audited with the frozen basis; a final calculation can't be archived.
6. **Module gating** — global search and My Work leave out switched-off modules.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.v1 import data_protection as dp
from app.api.v1 import scenario as api
from app.api.v1 import search
from app.models.enums import AssetClass
from app.models.scenario import CapitalStatus
from app.schemas.aml import SarCreate, SarUpdate
from app.schemas.asset import AssetCreate, AssetUpdate
from app.schemas.bia import BiaCreate, BiaDependencyRead, BiaUpdate
from app.schemas.declaration import DeclarationCreate
from app.schemas.fraud import FraudCaseUpdate
from app.schemas.risk_quant import RiskQuantUpdate
from app.schemas.scenario import CapitalCreate, CapitalReopen, ScenarioUpdate
from app.schemas.shariah import CharityUpdate
from app.services import my_work as mw
from app.services import sla
from app.services.fx import RateBook


# ================================================================ 1. currency ===
@pytest.mark.parametrize("schema, extra", [
    (AssetCreate, {"name": "x"}), (AssetUpdate, {}), (BiaCreate, {"process_name": "x"}), (BiaUpdate, {}),
    (SarCreate, {"subject": "x"}), (SarUpdate, {}), (DeclarationCreate, {}), (FraudCaseUpdate, {}),
    (RiskQuantUpdate, {}), (CharityUpdate, {}), (ScenarioUpdate, {}), (CapitalCreate, {}),
])
def test_money_currency_is_an_iso_code(schema, extra):
    assert schema(currency=" usd ", **extra).currency == "USD"
    with pytest.raises(ValidationError):
        schema(currency="PKRRRRRRRRRRR", **extra)  # used to reach a String(8) column
    with pytest.raises(ValidationError):
        schema(currency="ZZZ", **extra)


def test_blank_currency_is_the_default_and_none_is_untouched():
    assert AssetCreate(name="x", currency="").currency == "PKR"
    assert AssetUpdate().currency is None
    assert BiaUpdate(currency="  ").currency == "PKR"


# ======================================================== 2. data protection ===
class _Db:
    def __init__(self, obj=None):
        self.obj = obj

    async def scalar(self, _stmt):
        return self.obj

    async def flush(self):
        pass


@pytest.fixture
def trail(monkeypatch):
    written: list[dict] = []

    async def record(db, **kw):
        written.append(kw)

    monkeypatch.setattr(dp.audit_log, "record", record)
    monkeypatch.setattr(api.audit_log, "record", record)
    return written


@pytest.mark.parametrize("fn, entity_type", [
    (dp.delete_dpia, "dpia"), (dp.delete_dsar, "dsar"),
    (dp.delete_consent_record, "consent_record"), (dp.delete_data_breach, "data_breach"),
])
async def test_archiving_a_data_protection_record_is_audited(fn, entity_type, trail):
    obj = SimpleNamespace(id=uuid.uuid4(), reference="REF-1", deleted=False, deleted_date=None)
    user = SimpleNamespace(email="dpo@bank.pk", tenant_id=uuid.uuid4())
    await fn(obj.id, _Db(obj), user)
    assert obj.deleted is True and obj.deleted_date is not None
    assert [(t["action"], t["entity_type"], t["entity_id"]) for t in trail] == [("delete", entity_type, obj.id)]
    assert "Archived" in trail[0]["summary"] and "REF-1" in trail[0]["summary"]


# ===================================================================== 3. BIA ===
def test_a_bia_dependency_says_which_register_its_asset_is_in():
    asset = SimpleNamespace(id=uuid.uuid4(), reference="", title="", name="Core banking DB",
                            asset_class=AssetClass.it_asset)
    dep = SimpleNamespace(
        id=uuid.uuid4(), bia_id=uuid.uuid4(), dependency_type="it_asset", name="db", asset_id=asset.id,
        vendor_id=None, description="", criticality="medium", rto_hours=None,
        single_point_of_failure=False, asset=asset, vendor=None, created_at=datetime.now(timezone.utc),
    )
    read = BiaDependencyRead.model_validate(dep)
    assert read.model_dump(mode="json")["asset"]["asset_class"] == "it_asset"


# =============================================================== 4. TAT clock ===
def test_an_audit_finding_is_clocked_from_the_report_then_fieldwork_then_creation():
    fields = sla.ENTITIES["audit_finding"].started_fields
    created = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)

    def finding(report, end):
        return SimpleNamespace(created_at=created, engagement=SimpleNamespace(report_date=report, actual_end=end))

    assert sla._started_on(finding(date(2026, 3, 31), date(2026, 3, 10)), fields) == date(2026, 3, 31)
    assert sla._started_on(finding(None, date(2026, 3, 10)), fields) == date(2026, 3, 10)
    assert sla._started_on(finding(None, None), fields) == date(2026, 9, 1)
    assert sla._started_on(SimpleNamespace(created_at=created, engagement=None), fields) == date(2026, 9, 1)
    # The sweep loads the engagement with the finding (no lazy load in async).
    assert sla.ENTITIES["audit_finding"].load_options


# ============================================================= 5. SMA capital ===
def _book(eur_pkr):
    return RateBook("PKR", [("EUR", date(2026, 1, 1), eur_pkr)])


def _capital(status=CapitalStatus.draft, **kw):
    base = dict(
        id=uuid.uuid4(), reference="CAP-001", period="FY2026", business_indicator=500e9,
        avg_annual_loss=2e9, currency="PKR", notes="", status=status, workflow_status="draft",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc), deleted=False, deleted_date=None,
    )
    obj = SimpleNamespace(**{**base, **kw})
    api._unfreeze(obj)
    return obj


USER = SimpleNamespace(email="cro@bank.pk", tenant_id=uuid.uuid4())


def test_a_final_calculation_keeps_its_figures_when_rates_move():
    obj = _capital()
    api._freeze(obj, _book(300), USER)
    obj.status = CapitalStatus.final
    filed = api._capital_read(obj, _book(300))
    later = api._capital_read(obj, _book(900))
    assert filed.basis_frozen and later.basis_frozen
    assert (later.orc, later.bucket, later.bucket_1_threshold) == (filed.orc, filed.bucket, filed.bucket_1_threshold)
    assert later.fx_factor == 300 and "300.0000 PKR" in later.threshold_basis
    assert later.final_by == "cro@bank.pk" and later.final_at is not None
    # A draft follows today's rate.
    obj.status = CapitalStatus.draft
    assert api._capital_read(obj, _book(900)).orc != filed.orc


def test_a_calculation_cannot_be_final_without_a_rate():
    with pytest.raises(HTTPException) as exc:
        api._freeze(_capital(), RateBook("PKR"), USER)
    assert exc.value.status_code == 409 and "EUR" in exc.value.detail


def test_a_legacy_final_is_flagged_as_live():
    read = api._capital_read(_capital(CapitalStatus.final), _book(300))
    assert not read.basis_frozen and "today's exchange rate" in read.frozen_note


@pytest.fixture
def rates(monkeypatch):
    book = {"now": _book(300)}

    async def load(_db):
        return book["now"]

    monkeypatch.setattr(api.fx, "load_rate_book", load)
    return book


async def test_marking_final_freezes_and_audits(rates, trail):
    obj = _capital()
    read = await api.update_capital(obj.id, api.CapitalUpdate(status="final"), _Db(obj), USER)
    assert read.basis_frozen and obj.final_orc is not None
    assert trail[-1]["action"] == "finalise" and trail[-1]["changes"]["basis"]["fx_factor"] == 300


async def test_a_final_calculations_inputs_are_locked_but_notes_are_not(rates, trail):
    obj = _capital()
    api._freeze(obj, rates["now"], USER)
    obj.status = CapitalStatus.final
    for change in ({"business_indicator": 1.0}, {"currency": "USD"}, {"status": "draft"}):
        with pytest.raises(HTTPException) as exc:
            await api.update_capital(obj.id, api.CapitalUpdate(**change), _Db(obj), USER)
        assert exc.value.status_code == 409 and "Reopen" in exc.value.detail
    # Saving the form unchanged (same figures, as floats) plus a note is fine.
    await api.update_capital(obj.id, api.CapitalUpdate(business_indicator=500e9, status="final",
                                                       notes="Filed with the ICAAP"), _Db(obj), USER)
    assert obj.notes == "Filed with the ICAAP" and obj.final_at is not None
    with pytest.raises(HTTPException) as exc:
        await api.delete_capital(obj.id, _Db(obj), USER)
    assert exc.value.status_code == 409 and not obj.deleted


async def test_reopening_needs_a_reason_and_keeps_the_frozen_basis_in_the_trail(rates, trail, monkeypatch):
    from app.services import dual_control

    async def _no_four_eyes(db, module, action, amount=None):
        return False, None  # the second-person rule is pinned in test_fix_maker_checker_gaps

    monkeypatch.setattr(dual_control, "dual_control_required", _no_four_eyes)
    with pytest.raises(ValidationError):
        CapitalReopen(reason="fix")
    obj = _capital()
    api._freeze(obj, rates["now"], USER)
    obj.status = CapitalStatus.final
    frozen_orc = float(obj.final_orc)
    read = await api.reopen_capital(obj.id, CapitalReopen(reason="Restating BI after SBP inspection"), _Db(obj), USER)
    assert read.status == CapitalStatus.draft and not read.basis_frozen and obj.final_at is None
    entry = trail[-1]
    assert entry["action"] == "reopen" and "SBP inspection" in entry["summary"]
    assert entry["changes"]["frozen_basis"]["orc"] == frozen_orc
    with pytest.raises(HTTPException) as exc:  # nothing left to reopen
        await api.reopen_capital(obj.id, CapitalReopen(reason="Restating BI again, twice"), _Db(obj), USER)
    assert exc.value.status_code == 409


# ========================================================== 6. module gating ===
class _SearchDb:
    def __init__(self):
        self.sql = ""

    async def execute(self, stmt):
        self.sql = str(stmt.compile(dialect=postgresql.dialect()))
        return SimpleNamespace(all=lambda: [])


async def test_search_leaves_out_a_switched_off_module(monkeypatch):
    user = SimpleNamespace(tenant_id=uuid.uuid4(), permission_codes=["risk:read", "scenario:read", "dpo:read"])

    async def usable(_tid):
        return {"data_protection"}

    monkeypatch.setattr(search.modules, "usable_modules", usable)
    db = _SearchDb()
    await search.global_search("probe", db, user)
    assert "scenario_analyses" not in db.sql  # module off
    assert "dpias" in db.sql and "risks" in db.sql  # module on / core


def _ctx(off):
    return mw.Ctx(user_id=uuid.uuid4(), email="", permissions=set(), role_names=set(), role_ids=set(),
                  today=date(2026, 9, 25), horizon=date(2026, 10, 9), modules_off=set(off))


def test_my_work_knows_which_record_types_are_off():
    ctx = _ctx({"scenario_analysis", "data_protection"})
    assert mw._entity_off(ctx, "scenario_analysis") and mw._entity_off(ctx, "dpia")
    assert not mw._entity_off(ctx, "risk") and not mw._entity_off(ctx, "") and not mw._entity_off(ctx, None)


async def test_my_work_counts_every_licensable_module_the_organisation_turned_off(monkeypatch):
    from app.services import modules

    monkeypatch.setattr(modules, "enabled_modules", lambda: {"scenario_analysis", "bia", "aml"})

    class Db:
        async def scalar(self, _stmt):
            return ["bia"]

    off = await mw._module_off(Db())
    assert {"scenario_analysis", "aml"} <= off and "bia" not in off


async def test_my_work_drops_items_about_switched_off_modules(monkeypatch):
    async def builder_on(db, ctx):
        return [ctx.mk("record_review", id=uuid.uuid4(), title="t", reference="", subtitle="", link="/x",
                       entity_type="risk", entity_id=uuid.uuid4())]

    async def builder_off(db, ctx):
        return [ctx.mk("record_review", id=uuid.uuid4(), title="t", reference="", subtitle="", link="/x",
                       entity_type="scenario_analysis", entity_id=uuid.uuid4())]

    async def off(_db):
        return {"scenario_analysis"}

    async def directory(_db):
        return None

    import app.services.notifications as ns

    monkeypatch.setattr(mw, "BUILDERS", {"record_review": builder_on, "approval": builder_off})
    monkeypatch.setattr(mw, "_module_off", off)
    monkeypatch.setattr(ns, "load_directory", directory)
    user = SimpleNamespace(id=uuid.uuid4(), email="a@b.pk", permission_codes=[], roles=[])
    result = await mw.my_work(None, user, today=date(2026, 9, 25))
    types = [i.entity_type for s in result.sections for i in s.items]
    assert types == ["risk"]
