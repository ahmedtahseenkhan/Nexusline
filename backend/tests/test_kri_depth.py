"""Key Risk Indicator depth (product review F-14, plan §2.6).

No database: the pure rules are tested directly and the endpoints are driven with a fake
session, stubbed loaders and a captured audit trail.

Pinned here:

1. **Status** — higher/lower-is-worse unchanged; ``within_range`` is green inside the
   band (bounds inclusive), amber outside it, red at or beyond ``bound ± tolerance``
   (``limit_threshold``), red at once when no tolerance is set.
2. **Threshold rules** — warning strictly before limit in the direction of travel;
   within-range needs both bounds with lower < upper, no warning, a non-negative
   tolerance; empty thresholds only while the KRI has no value. Enforced on create,
   on update (the merged state) and before a reading is recorded.
3. **Readings** — never dated in the future; a back-filled reading doesn't move the
   current value; a reading that moves a KRI *up* into amber/red raises an ``event:``
   notification naming the escalation target and action, and is audited.
4. **Escalations** — one per level, a person or a role, an action; audited.
5. **Feed** — the token is shown once, only its SHA-256 is stored, it is checked in
   constant time, a missing/malformed/wrong/revoked token is a 401 before anything is
   read, and a good one records the reading as the ``KRI feed`` actor.
"""
from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError

from app.api.v1 import operational_risk as api
from app.models.enums import KriDirection, KriStatus, ReviewFrequency
from app.models.notification import EVENT_PREFIX, Notification
from app.models.audit import AuditLog
from app.models.operational_risk import KeyRiskIndicator, KriEscalation, KriMeasurement, band_distance, kri_status
from app.schemas import operational_risk as s
from app.services import audit as audit_service
from app.services import master_data
from app.services import notifications as ns
from app.services import webhooks
from app.services.import_registry import REGISTRY

TODAY = date(2026, 9, 12)
HI, LO, RANGE = KriDirection.higher_is_worse, KriDirection.lower_is_worse, KriDirection.within_range


# ================================================================== fakes ===
class FakeDB:
    def __init__(self, scalar=None, get=None):
        self._scalar = scalar  # a value, or a callable(stmt) -> value
        self.tables = get or {}
        self.added: list = []
        self.deleted: list = []
        self.flushed = 0

    async def scalar(self, stmt, *_a, **_k):
        return self._scalar(stmt) if callable(self._scalar) else self._scalar

    async def scalars(self, *_a, **_k):
        return SimpleNamespace(all=lambda: [])

    async def get(self, model, key):
        return self.tables.get(key)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flushed += 1
        for obj in self.added:  # what the database fills in at INSERT
            if getattr(obj, "id", "x") is None:
                obj.id = uuid.uuid4()
            if getattr(obj, "created_at", "x") is None:
                obj.created_at = datetime(2026, 9, 12, tzinfo=timezone.utc)

    def of(self, kind):
        return [o for o in self.added if isinstance(o, kind)]


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit_service, "record", record)
    return calls


@pytest.fixture
def today(monkeypatch):
    async def fake_today(db, tenant_id):
        return TODAY

    monkeypatch.setattr(api, "_today", fake_today)
    return TODAY


@pytest.fixture
def people(monkeypatch):
    jane = SimpleNamespace(id=uuid.uuid4(), full_name="Jane Doe", email="jane@bank.pk")
    omar = SimpleNamespace(id=uuid.uuid4(), full_name="Omar Khan", email="omar@bank.pk")
    table = {jane.id: jane, omar.id: omar}

    async def users_by_id(db, ids):
        return {i: table[i] for i in ids if i in table}

    async def check_user(db, user_id, field="owner_id"):
        if user_id is not None and user_id not in table:
            raise HTTPException(status_code=422, detail=f"{field}: that person is not a user in this organisation.")

    monkeypatch.setattr(master_data, "users_by_id", users_by_id)
    monkeypatch.setattr(master_data, "check_user", check_user)
    return SimpleNamespace(jane=jane, omar=omar)


def _user(perms=("oprisk:read", "oprisk:write")):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="analyst@bank.pk",
                           permission_codes=list(perms))


def _kri(**kw) -> KeyRiskIndicator:
    base = dict(
        id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="KRI-007", name="Failed wire transfers",
        unit="%", direction=HI, warning_threshold=2, limit_threshold=5, lower_bound=None,
        upper_bound=None, current_value=None, last_measured_date=None, owner="", owner_id=None,
        feed_token_hash="", deleted=False,
    )
    base.update(kw)
    return KeyRiskIndicator(**base)


# ================================================================= status ===
@pytest.mark.parametrize(
    "direction,value,warn,limit,expected",
    [
        (HI, None, 2, 5, KriStatus.no_data),
        (HI, 1, 2, 5, KriStatus.green),
        (HI, 2, 2, 5, KriStatus.amber),   # at the warning is amber
        (HI, 5, 2, 5, KriStatus.red),     # at the limit is red
        (HI, 9, None, 5, KriStatus.red),
        (HI, 4, None, 5, KriStatus.green),  # no warning: no amber zone
        (LO, 120, 110, 100, KriStatus.green),
        (LO, 110, 110, 100, KriStatus.amber),
        (LO, 100, 110, 100, KriStatus.red),
    ],
)
def test_one_sided_status_is_unchanged(direction, value, warn, limit, expected):
    assert kri_status(direction, value, warn, limit) == expected


@pytest.mark.parametrize(
    "value,tolerance,expected",
    [
        (130, 10, KriStatus.green),
        (110, 10, KriStatus.green),   # the bounds count as inside
        (150, 10, KriStatus.green),
        (105, 10, KriStatus.amber),   # 5 below the band, within tolerance
        (158, 10, KriStatus.amber),
        (100, 10, KriStatus.red),     # exactly lower − tolerance: red, like reaching a limit
        (160, 10, KriStatus.red),
        (95, 10, KriStatus.red),
        (109, None, KriStatus.red),   # no tolerance: leaving the band is a breach
        (151, 0, KriStatus.red),
        (None, 10, KriStatus.no_data),
    ],
)
def test_within_range_status(value, tolerance, expected):
    assert kri_status(RANGE, value, None, tolerance, 110, 150) == expected


def test_band_distance_and_open_sides():
    assert band_distance(105, 110, 150) == 5
    assert band_distance(155, 110, 150) == 5
    assert band_distance(130, 110, 150) == 0
    assert band_distance(1_000, 110, None) == 0  # a missing bound leaves that side open


def test_the_model_property_uses_the_band():
    kri = _kri(direction=RANGE, warning_threshold=None, limit_threshold=10, lower_bound=110,
               upper_bound=150, current_value=104)
    assert kri.status == KriStatus.amber and not kri.is_breached
    kri.current_value = 99
    assert kri.status == KriStatus.red and kri.is_breached


# ======================================================= threshold rules ===
def _refuse(direction, warn=None, limit=None, lower=None, upper=None, has_value=False):
    return api.threshold_refusal(direction, warn, limit, lower, upper, has_value=has_value)


def test_warning_must_come_before_the_limit_in_the_direction_of_travel():
    assert _refuse(HI, 2, 5) is None
    assert "below the limit" in _refuse(HI, 5, 2)
    assert "below the limit" in _refuse(HI, 5, 5)  # strictly before
    assert _refuse(LO, 110, 100) is None
    assert "above the limit" in _refuse(LO, 100, 110)
    assert "above the limit" in _refuse(LO, 100, 100)


def test_empty_thresholds_only_while_there_is_no_value():
    assert _refuse(HI) is None
    assert "needs a warning or a limit" in _refuse(HI, has_value=True)
    assert _refuse(HI, None, 5, has_value=True) is None  # one threshold is usable
    assert _refuse(LO, 110, None, has_value=True) is None


def test_within_range_rules():
    assert "both a lower and an upper bound" in _refuse(RANGE, lower=110)
    assert "both a lower and an upper bound" in _refuse(RANGE, upper=150)
    assert "must be below the upper bound" in _refuse(RANGE, lower=150, upper=110)
    assert "must be below the upper bound" in _refuse(RANGE, lower=150, upper=150)
    assert "no warning threshold" in _refuse(RANGE, warn=5, lower=110, upper=150)
    assert "can't be negative" in _refuse(RANGE, limit=-1, lower=110, upper=150)
    assert _refuse(RANGE, limit=10, lower=110, upper=150, has_value=True) is None
    assert _refuse(RANGE, lower=110, upper=150, has_value=True) is None  # tolerance optional


def test_bounds_are_cleared_when_the_direction_leaves_within_range():
    kri = _kri(direction=RANGE, lower_bound=110, upper_bound=150, warning_threshold=None)
    data = {"direction": HI}
    api.clear_bounds_off_range(kri, data)
    assert data == {"direction": HI, "lower_bound": None, "upper_bound": None}
    keep = {"direction": RANGE, "lower_bound": 1, "upper_bound": 2}
    api.clear_bounds_off_range(None, keep)
    assert keep["lower_bound"] == 1 and keep["upper_bound"] == 2


async def test_create_refuses_bad_thresholds_before_touching_the_database(audit_calls):
    body = s.KriCreate(name="Wires", warning_threshold=10, limit_threshold=5)
    db = FakeDB()
    with pytest.raises(HTTPException) as exc:
        await api.create_kri(body, db, _user())
    assert exc.value.status_code == 422 and "below the limit" in exc.value.detail
    assert not db.added and not audit_calls

    with pytest.raises(HTTPException) as exc:
        await api.create_kri(s.KriCreate(name="LCR", direction=RANGE, lower_bound=110), db, _user())
    assert "both a lower and an upper bound" in exc.value.detail

    with pytest.raises(HTTPException) as exc:  # a legacy value with no thresholds
        await api.create_kri(s.KriCreate(name="Old", current_value=3), db, _user())
    assert "needs a warning or a limit" in exc.value.detail


async def test_create_writes_the_new_fields_and_audits(monkeypatch, audit_calls, people):
    async def next_ref(db, model, prefix):
        return "KRI-008"

    async def read(db, kid):
        return kid

    monkeypatch.setattr(api, "_next_ref", next_ref)
    monkeypatch.setattr(api, "_kri_read", read)
    db = FakeDB(get={people.jane.id: people.jane})  # apply_refs labels the picked provider
    body = s.KriCreate(
        name="LCR", direction=RANGE, lower_bound=110, upper_bound=150, limit_threshold=10,
        definition="Liquidity coverage ratio", numerator="HQLA", denominator="30-day net outflows",
        data_source="Treasury ALM", data_provider_id=people.jane.id, indicator_type="leading",
        frequency=ReviewFrequency.daily,
    )
    await api.create_kri(body, db, _user())
    (kri,) = db.of(KeyRiskIndicator)
    assert (kri.lower_bound, kri.upper_bound, kri.limit_threshold) == (110, 150, 10)
    assert kri.data_provider_id == people.jane.id and kri.indicator_type == "leading"
    assert kri.frequency == ReviewFrequency.daily and kri.numerator == "HQLA"
    assert audit_calls[-1]["action"] == "create" and "KRI-008" in audit_calls[-1]["summary"]


async def test_create_refuses_an_unknown_appetite():
    with pytest.raises(HTTPException) as exc:
        await api._check_appetite(FakeDB(get={}), uuid.uuid4())
    assert exc.value.status_code == 422 and exc.value.detail.startswith("appetite_id:")


async def test_update_validates_the_merged_state_only_when_thresholds_change(monkeypatch, audit_calls):
    kri = _kri(direction=RANGE, warning_threshold=None, limit_threshold=10, lower_bound=110, upper_bound=150)

    async def load(db, kid):
        return kri

    async def read(db, kid):
        return kri

    monkeypatch.setattr(api, "_load_kri", load)
    monkeypatch.setattr(api, "_kri_read", read)
    with pytest.raises(HTTPException) as exc:
        await api.update_kri(kri.id, s.KriUpdate(warning_threshold=5), FakeDB(), _user())
    assert "no warning threshold" in exc.value.detail
    with pytest.raises(HTTPException) as exc:
        await api.update_kri(kri.id, s.KriUpdate(upper_bound=100), FakeDB(), _user())
    assert "must be below the upper bound" in exc.value.detail

    # A legacy KRI that breaks today's rule can still have its name edited.
    legacy = _kri(warning_threshold=9, limit_threshold=5, current_value=3)
    monkeypatch.setattr(api, "_load_kri", lambda db, kid: _async(legacy))
    await api.update_kri(legacy.id, s.KriUpdate(name="Renamed"), FakeDB(), _user())
    assert legacy.name == "Renamed" and audit_calls[-1]["action"] == "update"

    # Switching a range KRI to higher-is-worse clears its bounds.
    monkeypatch.setattr(api, "_load_kri", lambda db, kid: _async(kri))
    await api.update_kri(kri.id, s.KriUpdate(direction=HI, warning_threshold=2, limit_threshold=10),
                         FakeDB(), _user())
    assert kri.lower_bound is None and kri.upper_bound is None and kri.direction == HI


async def _async(value):
    return value


def test_schemas_carry_the_new_fields_and_never_the_token_hash():
    create = set(s.KriCreate.model_fields)
    assert {"definition", "numerator", "denominator", "data_source", "data_provider_id", "indicator_type",
            "lower_bound", "upper_bound", "appetite_id"} <= create
    assert {"lower_bound", "upper_bound", "appetite_id", "data_provider_id"} <= set(s.KriUpdate.model_fields)
    read = set(s.KriRead.model_fields)
    assert {"data_provider_ref", "appetite_ref", "escalations", "has_feed_token"} <= read
    assert "feed_token_hash" not in read and "feed_token_hash" not in create
    with pytest.raises(ValidationError):
        s.KriCreate(name="x", indicator_type="sideways")
    assert s.KriCreate(name="x", frequency="weekly").frequency == ReviewFrequency.weekly


def test_the_import_registry_carries_the_new_columns():
    cols = {c.field: c for c in REGISTRY["kris"].columns}
    for name in ("definition", "numerator", "denominator", "data_source", "lower_bound", "upper_bound",
                 "indicator_type", "data_provider_id"):
        assert name in cols, name
    assert cols["indicator_type"].enum_values == ["leading", "lagging"]
    assert cols["data_provider_id"].link.match_field == "email" and not cols["data_provider_id"].link.multi


# ========================================================== escalation rule ===
@pytest.mark.parametrize(
    "before,after,expected",
    [
        (KriStatus.green, KriStatus.amber, "amber"),
        (KriStatus.no_data, KriStatus.amber, "amber"),
        (KriStatus.green, KriStatus.red, "red"),
        (KriStatus.amber, KriStatus.red, "red"),
        (KriStatus.red, KriStatus.amber, None),  # improving is not an escalation
        (KriStatus.amber, KriStatus.amber, None),
        (KriStatus.red, KriStatus.red, None),
        (KriStatus.amber, KriStatus.green, None),
    ],
)
def test_escalation_level(before, after, expected):
    assert api.escalation_level(before, after) == expected


# ================================================================ readings ===
async def test_a_reading_needs_thresholds(today):
    kri = _kri(warning_threshold=None, limit_threshold=None)
    with pytest.raises(HTTPException) as exc:
        await api.record_reading(FakeDB(), kri, value=3, as_of=None, notes="", tenant_id=kri.tenant_id)
    assert exc.value.status_code == 422 and "Set this KRI's thresholds" in exc.value.detail


async def test_a_reading_is_never_dated_in_the_future(today):
    kri = _kri()
    db = FakeDB()
    with pytest.raises(HTTPException) as exc:
        await api.record_reading(db, kri, value=1, as_of=TODAY + timedelta(days=1), notes="",
                                 tenant_id=kri.tenant_id)
    assert exc.value.status_code == 422 and "in the future" in exc.value.detail
    assert not db.added and kri.current_value is None


async def test_a_back_filled_reading_neither_moves_the_value_nor_escalates(today, people):
    kri = _kri(current_value=1, last_measured_date=TODAY)
    db = FakeDB()
    reading = await api.record_reading(db, kri, value=9, as_of=TODAY - timedelta(days=30), notes="",
                                       tenant_id=kri.tenant_id)
    assert not reading.advanced and reading.level is None
    assert kri.current_value == 1 and kri.last_measured_date == TODAY
    assert len(db.of(KriMeasurement)) == 1 and not db.of(Notification)


async def test_turning_red_raises_the_escalation_naming_the_target_and_action(today, people):
    kri = _kri(current_value=1, last_measured_date=TODAY - timedelta(days=1), owner_id=people.omar.id)
    kri.escalations = [
        KriEscalation(level="red", escalate_to_id=people.jane.id, escalate_to_role="CRO",
                      action="Freeze outbound wires above PKR 10m and brief the CRO"),
        KriEscalation(level="amber", escalate_to_id=people.omar.id, escalate_to_role="", action="Investigate"),
    ]
    db = FakeDB()
    reading = await api.record_reading(db, kri, value=6, as_of=None, notes="EOD", tenant_id=kri.tenant_id)
    assert reading.level == "red" and kri.current_value == 6 and kri.last_measured_date == TODAY
    (note,) = db.of(Notification)
    assert note.dedup_key == f"{EVENT_PREFIX}kri-escalation:{kri.id}:{reading.measurement.id}"
    assert note.category.value == "critical" and "KRI-007" in note.title
    assert "Jane Doe and the CRO role" in note.body and "Freeze outbound wires" in note.body
    assert "limit 5" in note.body

    entries = api.reading_audit(kri, reading, via="entered by a@b")
    assert [e["action"] for e in entries] == ["measure", "escalate"]
    assert entries[1]["changes"]["target"] == "Jane Doe and the CRO role"
    assert entries[1]["changes"]["level"] == "red"


async def test_amber_without_an_escalation_names_the_owner(today, people):
    kri = _kri(current_value=1, last_measured_date=TODAY - timedelta(days=1), owner_id=people.omar.id)
    db = FakeDB()
    reading = await api.record_reading(db, kri, value=3, as_of=None, notes="", tenant_id=kri.tenant_id)
    assert reading.level == "amber"
    (note,) = db.of(Notification)
    assert note.category.value == "warning"
    assert "No amber escalation is set" in note.body and "Omar Khan" in note.body


async def test_improving_from_red_to_amber_raises_nothing(today, people):
    kri = _kri(current_value=9, last_measured_date=TODAY - timedelta(days=1))
    db = FakeDB()
    reading = await api.record_reading(db, kri, value=3, as_of=None, notes="", tenant_id=kri.tenant_id)
    assert reading.after == KriStatus.amber and reading.level is None and not db.of(Notification)


async def test_the_manual_endpoint_audits_the_reading_and_the_escalation(monkeypatch, today, people, audit_calls):
    kri = _kri(direction=RANGE, warning_threshold=None, limit_threshold=10, lower_bound=110,
               upper_bound=150, current_value=130, last_measured_date=TODAY - timedelta(days=1))
    monkeypatch.setattr(api, "_load_kri", lambda db, kid: _async(kri))
    monkeypatch.setattr(api, "_kri_read", lambda db, kid: _async(kri))
    user = _user()
    await api.add_measurement(kri.id, s.MeasurementCreate(value=95), FakeDB(), user)
    assert [c["action"] for c in audit_calls] == ["measure", "escalate"]
    assert all(c["actor"] is user for c in audit_calls)
    assert "red" in audit_calls[1]["summary"]


# ========================================================== notification text ===
def test_breach_alert_text_covers_the_band_and_the_red_escalation(people):
    kri = _kri(direction=RANGE, warning_threshold=None, limit_threshold=10, lower_bound=110,
               upper_bound=150, current_value=95)
    kri.escalations = [KriEscalation(level="red", escalate_to_id=None, escalate_to_role="ALCO",
                                     action="Convene ALCO within 24 hours")]
    body = ns.kri_breach_body(kri, {})
    assert "is outside its range 110–150 %, tolerance 10" in body
    assert "Escalate to the ALCO role: Convene ALCO within 24 hours" in body
    one_sided = _kri(current_value=7)
    assert ns.kri_breach_body(one_sided, {}) == "Failed wire transfers — current 7 % breached its warning 2, limit 5 %"


# ============================================================ escalations CRUD ===
def test_an_escalation_names_someone_and_an_action():
    with pytest.raises(ValidationError):
        s.KriEscalationCreate(level="red", action="Call the CRO")
    with pytest.raises(ValidationError):
        s.KriEscalationCreate(level="purple", escalate_to_role="CRO", action="x")
    with pytest.raises(ValidationError):
        s.KriEscalationCreate(level="red", escalate_to_role="CRO", action="   ")
    assert s.KriEscalationCreate(level="amber", escalate_to_role="CRO", action="Review").level == "amber"


async def test_create_escalation_is_one_per_level_validated_and_audited(monkeypatch, people, audit_calls):
    kri = _kri()
    kri.escalations = [KriEscalation(id=uuid.uuid4(), level="red", escalate_to_role="CRO", action="x")]
    monkeypatch.setattr(api, "_load_kri", lambda db, kid: _async(kri))
    user = _user()
    with pytest.raises(HTTPException) as exc:
        await api.create_escalation(kri.id, s.KriEscalationCreate(level="red", escalate_to_role="CRO", action="y"),
                                    FakeDB(), user)
    assert exc.value.status_code == 409

    # Unknown role → 422 naming the field.
    with pytest.raises(HTTPException) as exc:
        await api.create_escalation(kri.id, s.KriEscalationCreate(level="amber", escalate_to_role="Nobody", action="y"),
                                    FakeDB(scalar=None), user)
    assert exc.value.status_code == 422 and exc.value.detail.startswith("escalate_to_role:")

    role = SimpleNamespace(name="CRO")
    db = FakeDB(scalar=role)
    read = await api.create_escalation(
        kri.id, s.KriEscalationCreate(level="amber", escalate_to_id=people.jane.id, escalate_to_role="cro",
                                      action=" Review within 2 days "), db, user)
    (row,) = db.of(KriEscalation)
    assert row.escalate_to_role == "CRO" and row.action == "Review within 2 days"
    assert read.escalate_to_ref.full_name == "Jane Doe"
    assert audit_calls[-1]["action"] == "add_escalation" and audit_calls[-1]["entity_id"] == kri.id


async def test_update_and_delete_escalation(monkeypatch, people, audit_calls):
    kri = _kri()
    amber = KriEscalation(id=uuid.uuid4(), kri_id=kri.id, level="amber", escalate_to_id=people.jane.id,
                          escalate_to_role="", action="Review", created_at=datetime.now(timezone.utc))
    red = KriEscalation(id=uuid.uuid4(), kri_id=kri.id, level="red", escalate_to_id=None,
                        escalate_to_role="CRO", action="Freeze", created_at=datetime.now(timezone.utc))
    kri.escalations = [amber, red]
    monkeypatch.setattr(api, "_load_kri", lambda db, kid: _async(kri))
    monkeypatch.setattr(api, "_load_escalation", lambda db, kid, eid: _async(amber))
    user = _user()
    with pytest.raises(HTTPException) as exc:  # red is taken
        await api.update_escalation(kri.id, amber.id, s.KriEscalationUpdate(level="red"), FakeDB(), user)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:  # nobody left to tell
        await api.update_escalation(kri.id, amber.id, s.KriEscalationUpdate(escalate_to_id=None), FakeDB(), user)
    assert exc.value.status_code == 422
    await api.update_escalation(kri.id, amber.id, s.KriEscalationUpdate(action="Call Omar"), FakeDB(), user)
    assert amber.action == "Call Omar" and audit_calls[-1]["action"] == "update_escalation"
    db = FakeDB()
    await api.delete_escalation(kri.id, amber.id, db, user)
    assert db.deleted == [amber] and audit_calls[-1]["action"] == "remove_escalation"


# ==================================================================== feed ===
def test_feed_token_shape_hash_and_constant_time_check():
    tenant = uuid.uuid4()
    token = api.new_feed_token(tenant)
    assert api.feed_token_tenant(token) == tenant
    stored = api.feed_token_hash(token)
    assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in stored
    assert api.feed_token_matches(token, stored)
    assert not api.feed_token_matches(token + "x", stored)
    assert not api.feed_token_matches(token, "")  # revoked
    assert not api.feed_token_matches("", stored)
    for bad in ("", "nonsense", "not-a-uuid.abcdefghijklmnopqrstuvwxyz", f"{tenant.hex}.short"):
        assert api.feed_token_tenant(bad) is None
    assert api.new_feed_token(tenant) != token  # random


async def test_issuing_a_token_stores_only_its_hash_and_audits_without_it(monkeypatch, audit_calls):
    kri = _kri()
    monkeypatch.setattr(api, "_load_kri", lambda db, kid: _async(kri))
    user = _user()
    issued = await api.issue_feed_token(kri.id, FakeDB(), user)
    assert kri.feed_token_hash == api.feed_token_hash(issued.token)
    assert api.feed_token_tenant(issued.token) == user.tenant_id
    assert issued.endpoint == f"/api/v1/kris/{kri.id}/measurements/feed"
    assert issued.header == f"Authorization: Bearer {issued.token}"
    assert audit_calls[-1]["action"] == "feed_token_issue" and audit_calls[-1]["changes"] == {"rotated": False}
    assert issued.token not in repr(audit_calls)

    first = kri.feed_token_hash
    again = await api.issue_feed_token(kri.id, FakeDB(), user)
    assert kri.feed_token_hash != first and audit_calls[-1]["changes"] == {"rotated": True}
    assert "previous token stopped working" in again.note

    await api.revoke_feed_token(kri.id, FakeDB(), user)
    assert kri.feed_token_hash == "" and audit_calls[-1]["action"] == "feed_token_revoke"
    n = len(audit_calls)
    await api.revoke_feed_token(kri.id, FakeDB(), user)  # nothing to revoke: no entry
    assert len(audit_calls) == n


def _feed_session(monkeypatch, db):
    opened: list = []

    @asynccontextmanager
    async def session(tenant_id):
        opened.append(tenant_id)
        yield db

    monkeypatch.setattr(api, "tenant_session", session)
    return opened


def _bearer(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


@pytest.mark.parametrize("creds", [None, _bearer(""), _bearer("garbage"),
                                   HTTPAuthorizationCredentials(scheme="Basic", credentials="x.y")])
async def test_feed_without_a_token_shaped_credential_is_401_before_any_read(monkeypatch, creds):
    opened = _feed_session(monkeypatch, FakeDB())
    with pytest.raises(HTTPException) as exc:
        await api.feed_measurement(uuid.uuid4(), s.MeasurementFeed(value=1), creds)
    assert exc.value.status_code == 401 and exc.value.headers == {"WWW-Authenticate": "Bearer"}
    assert opened == []


async def test_feed_with_a_wrong_revoked_or_foreign_token_is_401(monkeypatch):
    tenant = SimpleNamespace(id=uuid.uuid4(), is_active=True)
    kri = _kri(tenant_id=tenant.id)
    good = api.new_feed_token(tenant.id)
    kri.feed_token_hash = api.feed_token_hash(good)
    db = FakeDB(scalar=kri, get={tenant.id: tenant})
    _feed_session(monkeypatch, db)
    for token in (api.new_feed_token(tenant.id),        # another token of the same org
                  api.new_feed_token(uuid.uuid4())):     # a token of another org
        with pytest.raises(HTTPException) as exc:
            await api.feed_measurement(kri.id, s.MeasurementFeed(value=1), _bearer(token))
        assert exc.value.status_code == 401
    kri.feed_token_hash = ""  # revoked
    with pytest.raises(HTTPException) as exc:
        await api.feed_measurement(kri.id, s.MeasurementFeed(value=1), _bearer(good))
    assert exc.value.status_code == 401
    kri.feed_token_hash = api.feed_token_hash(good)
    tenant.is_active = False  # a suspended organisation's feeds stop
    with pytest.raises(HTTPException) as exc:
        await api.feed_measurement(kri.id, s.MeasurementFeed(value=1), _bearer(good))
    assert exc.value.status_code == 401
    assert not db.added


async def test_feed_records_the_reading_as_the_kri_feed_and_escalates(monkeypatch, today, people):
    tenant = SimpleNamespace(id=uuid.uuid4(), is_active=True)
    kri = _kri(tenant_id=tenant.id, current_value=1, last_measured_date=TODAY - timedelta(days=1))
    kri.escalations = [KriEscalation(level="red", escalate_to_id=people.jane.id, escalate_to_role="",
                                     action="Stop the batch")]
    token = api.new_feed_token(tenant.id)
    kri.feed_token_hash = api.feed_token_hash(token)
    db = FakeDB(scalar=kri, get={tenant.id: tenant})
    opened = _feed_session(monkeypatch, db)
    hooks: list = []

    async def dispatch(db, **kw):
        hooks.append(kw)
        return 0

    monkeypatch.setattr(webhooks, "dispatch", dispatch)
    result = await api.feed_measurement(kri.id, s.MeasurementFeed(value=7.5, notes="CCM run 42"), _bearer(token))
    assert opened == [tenant.id]
    assert result.status == KriStatus.red and result.escalated == "red" and result.current_value == 7.5
    assert result.last_measured_date == TODAY and result.reference == "KRI-007"
    (m,) = db.of(KriMeasurement)
    assert m.notes == "CCM run 42" and m.as_of_date == TODAY and result.measurement_id == m.id
    logs = db.of(AuditLog)
    assert [a.action for a in logs] == ["measure", "escalate"]
    assert all(a.actor_email == api.FEED_ACTOR and a.actor_id is None and a.tenant_id == tenant.id for a in logs)
    assert "Jane Doe" in logs[1].summary
    assert [h["payload"]["actor"] for h in hooks] == [api.FEED_ACTOR, api.FEED_ACTOR]
    (note,) = db.of(Notification)
    assert "Escalate to Jane Doe: Stop the batch" in note.body
    assert set(s.FeedResult.model_fields) == {"kri_id", "reference", "measurement_id", "status", "current_value",
                                              "last_measured_date", "escalated"}  # no names, no history


async def test_feed_refuses_a_future_date_after_authenticating(monkeypatch, today):
    tenant = SimpleNamespace(id=uuid.uuid4(), is_active=True)
    kri = _kri(tenant_id=tenant.id)
    token = api.new_feed_token(tenant.id)
    kri.feed_token_hash = api.feed_token_hash(token)
    db = FakeDB(scalar=kri, get={tenant.id: tenant})
    _feed_session(monkeypatch, db)
    with pytest.raises(HTTPException) as exc:
        await api.feed_measurement(kri.id, s.MeasurementFeed(value=1, as_of_date=TODAY + timedelta(days=2)),
                                   _bearer(token))
    assert exc.value.status_code == 422 and "in the future" in exc.value.detail
    assert not db.of(KriMeasurement)


def test_the_feed_route_needs_no_user_session():
    """The feed authenticates with its own token: no JWT, session or user dependency."""
    from app.core import deps

    route = next(r for r in api.router.routes if r.path == "/kris/{kid}/measurements/feed")
    calls: set = set()

    def walk(dependant):
        for sub in dependant.dependencies:
            calls.add(sub.call)
            walk(sub)

    walk(route.dependant)
    assert not calls & {deps.get_current_user, deps.get_db, deps.get_token_payload}
    token_route = next(r for r in api.router.routes if r.path == "/kris/{kid}/feed-token" and "POST" in r.methods)
    assert any(getattr(d.dependency, "__name__", "") == "checker" for d in token_route.dependencies)  # oprisk:write
