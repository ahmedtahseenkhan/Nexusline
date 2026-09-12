"""Incidents: the regulator's clock, impact flags and loss hand-off (product review §2.5, F-10).

No database: the pure rules in ``services.incident_clock`` are tested directly and the
endpoints run against a fake session with stubbed loaders, as in ``test_risk_integrity``.

Pinned here:

1. **Timestamps, not dates.** The read schema keeps a time of day (regression: the
   columns became TIMESTAMPTZ); a bare date or offset-less value is read in the
   organisation's timezone; ``RegulatoryReport.is_overdue`` compares instants.
2. **The regulatory clock.** Initial report = detection + N hours to the minute, final =
   + M days; the reports are created once, pending deadlines move with detection,
   submitted reports are history; the incident reads back deadline, notified-at,
   reference, hours to deadline (negative when late) and on-time.
3. **Timeline and flags.** Occurred ≤ detected ≤ contained ≤ resolved; a status move
   stamps the step it implies; a near miss carries no cost and no loss; a personal data
   breach opens one linked breach and notifies a DPO role when there is one.
4. **Loss events** are pre-filled from the incident; **MTTD/MTTC/MTTR** per incident and
   averaged.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.api.v1 import incidents as incidents_api
from app.api.v1 import tenant_settings as tenant_settings_api
from app.core.config import settings
from app.models.data_protection import DataBreach
from app.models.enums import (
    IncidentStatus,
    RegulatoryReportStatus,
    RegulatoryReportType,
    Severity,
)
from app.models.incident import RegulatoryReport
from app.models.notification import EVENT_PREFIX, Notification
from app.models.operational_risk import LossEvent
from app.schemas.incident import IncidentCreate, IncidentRead, IncidentUpdate
from app.services import audit as audit_service
from app.services import incident_clock as clock
from app.services import ref_fields as rf

PKT = ZoneInfo("Asia/Karachi")
UTC = timezone.utc
INITIAL = RegulatoryReportType.initial_notification
FINAL = RegulatoryReportType.final_report


def _report(rtype=INITIAL, deadline=None, status=RegulatoryReportStatus.pending, submitted_at=None,
            reference="", regulator="SBP", regulator_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(), report_type=rtype, deadline=deadline, status=status,
        submitted_at=submitted_at, reference=reference, regulator=regulator, regulator_id=regulator_id,
    )


# ============================================================ timestamps ===
def _read_payload(**kw):
    base = dict(
        id=uuid.uuid4(), reference="INC-001", title="Card data exfiltration",
        stage_count=0, completed_stages=0, lifecycle_complete=False, current_stage=None,
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )
    base.update(kw)
    return base


def test_the_read_schema_keeps_the_time_of_day():
    """Regression: occurred/detected/resolved became TIMESTAMPTZ; a read typed ``date``
    would reject (or truncate) 14:37 on the day."""
    at = datetime(2026, 9, 1, 14, 37, 12, tzinfo=PKT)
    read = IncidentRead.model_validate(_read_payload(
        detected_at=at, occurred_at=at - timedelta(hours=2), contained_at=at + timedelta(hours=1),
        resolved_at=at + timedelta(days=1),
    ))
    assert read.detected_at == at and read.detected_at.hour == 14 and read.detected_at.minute == 37
    assert read.resolved_at == at + timedelta(days=1)
    assert '"detected_at":"2026-09-01T14:37:12+05:00"' in read.model_dump_json()


def test_regulatory_report_reads_are_timestamps_too():
    from app.schemas.incident import RegReportRead

    deadline = datetime(2026, 9, 2, 9, 15, tzinfo=PKT)
    read = RegReportRead.model_validate(dict(
        id=uuid.uuid4(), incident_id=uuid.uuid4(), regulator="SBP", report_type=INITIAL,
        deadline=deadline, status=RegulatoryReportStatus.pending, submitted_at=None, reference="",
        summary="", submitted_by="", is_overdue=False, created_at=deadline,
    ))
    assert read.deadline == deadline and read.deadline.minute == 15


@pytest.mark.parametrize("sent,expected", [
    ("2026-09-01", datetime(2026, 9, 1, 0, 0)),                       # a bare date: 00:00
    ("2026-09-01T14:30", datetime(2026, 9, 1, 14, 30)),               # datetime-local, no offset
    ("2026-09-01T14:30:00+05:00", datetime(2026, 9, 1, 14, 30, tzinfo=PKT)),
])
def test_writes_accept_a_date_or_a_date_time(sent, expected):
    body = IncidentCreate(title="x", detected_at=sent)
    assert body.detected_at.replace(tzinfo=None) == expected.replace(tzinfo=None)
    assert (body.detected_at.utcoffset() is None) == (expected.tzinfo is None)
    assert IncidentUpdate(resolved_at=sent).resolved_at is not None


def test_localize_reads_a_date_or_naive_value_in_the_organisation_zone():
    assert clock.localize(date(2026, 9, 1), PKT) == datetime(2026, 9, 1, 0, 0, tzinfo=PKT)
    assert clock.localize(datetime(2026, 9, 1, 14, 30), PKT) == datetime(2026, 9, 1, 14, 30, tzinfo=PKT)
    aware = datetime(2026, 9, 1, 9, 30, tzinfo=UTC)
    assert clock.localize(aware, PKT) is aware  # an offset is kept as sent
    assert clock.localize(None, PKT) is None
    # 00:00 in Karachi is 19:00 UTC the day before.
    assert clock.localize(date(2026, 9, 1), PKT).astimezone(UTC) == datetime(2026, 8, 31, 19, 0, tzinfo=UTC)


async def test_the_organisation_zone_is_only_read_when_a_value_needs_it(monkeypatch):
    calls = []

    async def zone_of(db, tenant_id):
        calls.append(tenant_id)
        return ZoneInfo("Asia/Dubai")

    monkeypatch.setattr(clock, "tenant_zone", zone_of)
    aware = {"detected_at": datetime(2026, 9, 1, 9, 0, tzinfo=UTC), "title": "x"}
    await clock.localize_fields(None, "t1", aware, clock.TIMELINE_FIELDS)
    assert calls == []
    mixed = {"detected_at": datetime(2026, 9, 1, 9, 0), "resolved_at": None}
    await clock.localize_fields(None, "t1", mixed, clock.TIMELINE_FIELDS)
    assert calls == ["t1"] and mixed["detected_at"].utcoffset() == timedelta(hours=4)


def test_an_unknown_zone_falls_back_to_the_default():
    assert clock.zone("Mars/Olympus") == ZoneInfo("Asia/Karachi")
    assert clock.zone(None) == ZoneInfo("Asia/Karachi")
    assert clock.zone("Asia/Dubai") == ZoneInfo("Asia/Dubai")


def test_a_timestamp_deadline_is_overdue_from_the_minute_it_passes():
    """Regression: ``is_overdue`` compared a TIMESTAMPTZ with ``date.today()`` (TypeError)."""
    now = clock.now_utc()
    late = RegulatoryReport(status=RegulatoryReportStatus.pending, deadline=now - timedelta(minutes=1))
    due = RegulatoryReport(status=RegulatoryReportStatus.pending, deadline=now + timedelta(minutes=5))
    sent = RegulatoryReport(status=RegulatoryReportStatus.submitted, deadline=now - timedelta(days=1))
    assert late.is_overdue is True and due.is_overdue is False and sent.is_overdue is False
    assert RegulatoryReport(status=RegulatoryReportStatus.pending, deadline=None).is_overdue is False


# ========================================================= regulatory clock ===
def test_deadlines_are_computed_to_the_minute():
    anchor = datetime(2026, 9, 1, 10, 37, 45, tzinfo=PKT)
    due = clock.planned_deadlines(anchor, 24, 30)
    assert due[INITIAL] == datetime(2026, 9, 2, 10, 37, tzinfo=PKT)  # not rounded to a day
    assert due[FINAL] == datetime(2026, 10, 1, 10, 37, tzinfo=PKT)
    assert clock.planned_deadlines(anchor, 6, 14)[INITIAL] == datetime(2026, 9, 1, 16, 37, tzinfo=PKT)


def test_the_clock_starts_at_detection_else_when_the_incident_was_logged():
    logged = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    detected = datetime(2026, 8, 31, 22, 0, tzinfo=UTC)
    assert clock.clock_anchor(SimpleNamespace(detected_at=detected, created_at=logged)) == detected
    assert clock.clock_anchor(SimpleNamespace(detected_at=None, created_at=logged)) == logged
    now = datetime(2026, 9, 2, tzinfo=UTC)
    assert clock.clock_anchor(SimpleNamespace(detected_at=None, created_at=None), now) == now


def test_sync_creates_the_two_reports_once():
    planned = clock.planned_deadlines(datetime(2026, 9, 1, 9, 0, tzinfo=UTC), 24, 30)
    create, changes = clock.plan_sync([], planned, recompute=True, regulator="SBP", regulator_id=None)
    assert create == [INITIAL, FINAL] and [c.action for c in changes] == ["created", "created"]
    existing = [_report(INITIAL, planned[INITIAL]), _report(FINAL, planned[FINAL])]
    create, changes = clock.plan_sync(existing, planned, recompute=True, regulator="SBP", regulator_id=None)
    assert create == [] and changes == []


def test_a_pending_deadline_moves_with_detection_but_a_submitted_one_is_history():
    old = clock.planned_deadlines(datetime(2026, 9, 1, 9, 0, tzinfo=UTC), 24, 30)
    new = clock.planned_deadlines(datetime(2026, 9, 1, 6, 0, tzinfo=UTC), 24, 30)
    initial = _report(INITIAL, old[INITIAL], status=RegulatoryReportStatus.submitted,
                      submitted_at=old[INITIAL] - timedelta(hours=3))
    final = _report(FINAL, old[FINAL])
    _, changes = clock.plan_sync([initial, final], new, recompute=True, regulator="SBP", regulator_id=None)
    assert initial.deadline == old[INITIAL]  # untouched
    assert final.deadline == new[FINAL] and [(c.report_type, c.action) for c in changes] == [(FINAL, "moved")]


def test_without_recompute_an_edited_deadline_is_kept_and_a_removed_report_not_recreated():
    planned = clock.planned_deadlines(datetime(2026, 9, 1, 9, 0, tzinfo=UTC), 24, 30)
    agreed = planned[FINAL] + timedelta(days=15)  # extension agreed with the regulator
    final = _report(FINAL, agreed)
    create, changes = clock.plan_sync([final], planned, recompute=False, regulator="SBP",
                                      regulator_id=None, create_missing=False)
    assert create == [] and changes == [] and final.deadline == agreed


def test_pending_reports_follow_the_incident_regulator():
    secp = uuid.uuid4()
    planned = clock.planned_deadlines(datetime(2026, 9, 1, 9, 0, tzinfo=UTC), 24, 30)
    pending = _report(INITIAL, planned[INITIAL])
    sent = _report(FINAL, planned[FINAL], status=RegulatoryReportStatus.submitted)
    clock.plan_sync([pending, sent], planned, recompute=False, regulator="SECP", regulator_id=secp)
    assert (pending.regulator, pending.regulator_id) == ("SECP", secp)
    assert sent.regulator == "SBP"


def test_sync_appends_report_rows_to_the_incident():
    inc = SimpleNamespace(detected_at=datetime(2026, 9, 1, 9, 15, 30, tzinfo=PKT), created_at=None,
                          regulator="", regulator_id=None, regulatory_reports=[])
    clock.sync_regulatory_reports(inc, tenant_id=uuid.uuid4(), initial_hours=24, final_days=30,
                                  default_regulator="SBP", recompute=True)
    rows = {r.report_type: r for r in inc.regulatory_reports}
    assert set(rows) == {INITIAL, FINAL}
    assert rows[INITIAL].deadline == datetime(2026, 9, 2, 9, 15, tzinfo=PKT)
    assert rows[INITIAL].regulator == "SBP" and rows[INITIAL].status == RegulatoryReportStatus.pending


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


def test_no_initial_report_means_no_clock():
    assert clock.notification_clock([], NOW) == clock.NotificationClock(None, None, None, None, None)
    assert clock.notification_clock([_report(FINAL, NOW)], NOW).notification_deadline is None


def test_a_pending_notification_counts_down_and_is_not_yet_judged():
    c = clock.notification_clock([_report(INITIAL, NOW + timedelta(hours=5, minutes=30))], NOW)
    assert c.hours_to_deadline == 5.5 and c.notified_on_time is None and c.notified_at is None


def test_a_missed_deadline_is_negative_and_late():
    c = clock.notification_clock([_report(INITIAL, NOW - timedelta(hours=2))], NOW)
    assert c.hours_to_deadline == -2.0 and c.notified_on_time is False


def test_a_notification_is_judged_against_its_deadline_and_the_margin_frozen():
    deadline = NOW - timedelta(days=3)
    on_time = _report(INITIAL, deadline, status=RegulatoryReportStatus.acknowledged,
                      submitted_at=deadline - timedelta(hours=4), reference="SBP/IR/2026/118")
    c = clock.notification_clock([on_time], NOW)
    assert c.notified_on_time is True and c.hours_to_deadline == 4.0
    assert c.notified_at == deadline - timedelta(hours=4) and c.regulator_reference == "SBP/IR/2026/118"
    late = _report(INITIAL, deadline, status=RegulatoryReportStatus.submitted,
                   submitted_at=deadline + timedelta(minutes=90))
    c = clock.notification_clock([late], NOW)
    assert c.notified_on_time is False and c.hours_to_deadline == -1.5
    assert c.regulator_reference is None


def test_the_earliest_initial_report_is_the_one_that_counts():
    first, second = NOW + timedelta(hours=1), NOW + timedelta(hours=10)
    c = clock.notification_clock([_report(INITIAL, second), _report(INITIAL, first)], NOW)
    assert c.notification_deadline == first


# ================================================================ timeline ===
def test_the_timeline_must_run_in_order():
    t0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    ok = {"occurred_at": t0, "detected_at": t0 + timedelta(hours=1),
          "contained_at": t0 + timedelta(hours=3), "resolved_at": t0 + timedelta(days=1)}
    assert clock.timeline_problems(ok) == []
    assert clock.timeline_problems({"occurred_at": t0, "detected_at": t0 - timedelta(minutes=1)}) == [
        "Detected is before occurred"
    ]
    assert "Resolved is before contained" in clock.timeline_problems(
        {"contained_at": t0, "resolved_at": t0 - timedelta(hours=1)}
    )
    assert clock.timeline_problems({"detected_at": t0}) == []  # blanks are not compared


def test_a_status_move_stamps_the_step_it_implies_only_when_blank():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    assert clock.status_stamps(IncidentStatus.contained, {"contained_at": None}, now) == {"contained_at": now}
    assert clock.status_stamps(IncidentStatus.closed, {"resolved_at": None}, now) == {"resolved_at": now}
    earlier = now - timedelta(days=1)
    assert clock.status_stamps(IncidentStatus.resolved, {"resolved_at": earlier}, now) == {}
    assert clock.status_stamps(IncidentStatus.investigating, {}, now) == {}


def test_response_times_in_hours():
    t0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
    inc = SimpleNamespace(occurred_at=t0, detected_at=t0 + timedelta(minutes=90),
                          contained_at=t0 + timedelta(hours=5, minutes=30), resolved_at=t0 + timedelta(days=2))
    t = clock.response_times(inc)
    assert (t.mttd_hours, t.mttc_hours, t.mttr_hours) == (1.5, 4.0, 46.5)
    legacy = SimpleNamespace(occurred_at=t0, detected_at=t0 - timedelta(days=1), contained_at=None, resolved_at=None)
    assert clock.response_times(legacy) == clock.ResponseTimes(None, None, None)  # impossible: not averaged
    assert clock.average([1.5, None, 4.5]) == (3.0, 2) and clock.average([]) == (None, 0)


# ================================================================== flags ===
def test_a_near_miss_has_no_cost_and_no_loss():
    assert clock.near_miss_problem(True, 5000.0) is not None
    assert clock.near_miss_problem(True, None) is None and clock.near_miss_problem(True, 0) is None
    assert clock.near_miss_problem(False, 5000.0) is None
    rows = [SimpleNamespace(cost=1000.0, near_miss=False), SimpleNamespace(cost=250.0, near_miss=True),
            SimpleNamespace(cost=None, near_miss=False)]
    assert clock.loss_total(rows) == 1000.0


@pytest.mark.parametrize("name,expected", [
    ("DPO", True), ("Data Protection Officer", True), ("data_protection", True),
    ("Head of Data Protection", True), ("Risk Manager", False), ("", False), ("Deposits", False),
])
def test_dpo_role_names(name, expected):
    assert clock.is_dpo_role(name) is expected


def test_the_business_unit_is_only_taken_when_the_links_name_exactly_one():
    retail, corp = uuid.uuid4(), uuid.uuid4()
    assert clock.single_unit([SimpleNamespace(owner_id=retail)],
                             [SimpleNamespace(business_units=[SimpleNamespace(id=retail)])]) == retail
    assert clock.single_unit([SimpleNamespace(owner_id=retail)],
                             [SimpleNamespace(business_units=[SimpleNamespace(id=corp)])]) is None
    assert clock.single_unit([], []) is None


# ============================================================== endpoints ===
class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, roles=(), scalar=None):
        self.roles = list(roles)
        self.scalar_result = scalar
        self.added: list = []
        self.flushed = 0

    async def scalar(self, *_a, **_k):
        return self.scalar_result

    async def get(self, model, key):
        return SimpleNamespace(id=key, name="Retail Banking", deleted=False)

    async def scalars(self, *_a, **_k):
        return _Rows(self.roles)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None and hasattr(obj, "id"):
            obj.id = uuid.uuid4()

    async def flush(self):
        self.flushed += 1


def _actor():
    return SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="soc@bank.pk",
                           permission_codes=["incident:read", "incident:write", "oprisk:write"])


def _incident(**kw):
    t0 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    base = dict(
        id=uuid.uuid4(), reference="INC-042", title="Customer card data exposed", description="",
        severity=Severity.high, status=IncidentStatus.investigating, occurred_at=t0 - timedelta(hours=2),
        detected_at=t0, contained_at=None, resolved_at=None, near_miss=False, cost=None,
        personal_data_breach=False, records_affected=1800, customers_affected=900, is_reportable=False,
        regulator="", regulator_id=None, regulatory_reports=[], created_at=t0, root_cause="",
        assignee="", assignee_id=None, assets=[], risks=[], controls=[], vendors=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def audit_calls(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr(audit_service, "record", record)
    return calls


@pytest.fixture
def stub_update(monkeypatch, audit_calls):
    """Stub the loaders around ``update_incident`` and return the incident it edits."""
    holder = {}

    async def load(db, _id):
        return holder["inc"]

    async def fresh(db, _id):
        return holder["inc"]

    async def read(db, obj):
        return obj

    async def flush_assoc(*_a, **_k):
        return None

    async def no_candidates(db, f, text):
        return []

    monkeypatch.setattr(incidents_api, "_load", load)
    monkeypatch.setattr(incidents_api, "_fresh", fresh)
    monkeypatch.setattr(incidents_api, "incident_read", read)
    monkeypatch.setattr(incidents_api, "_flush_assoc", flush_assoc)
    monkeypatch.setattr(rf, "_candidates", no_candidates)
    return holder


async def test_an_out_of_order_timeline_is_refused(stub_update):
    inc = stub_update["inc"] = _incident()
    body = IncidentUpdate(occurred_at=inc.detected_at + timedelta(hours=1))
    with pytest.raises(HTTPException) as exc:
        await incidents_api.update_incident(inc.id, body, FakeDB(), _actor())
    assert exc.value.status_code == 422 and "Detected is before occurred" in exc.value.detail


async def test_a_near_miss_with_a_cost_is_refused(stub_update):
    inc = stub_update["inc"] = _incident(cost=12000.0)
    with pytest.raises(HTTPException) as exc:
        await incidents_api.update_incident(inc.id, IncidentUpdate(near_miss=True), FakeDB(), _actor())
    assert exc.value.status_code == 422 and "near miss" in exc.value.detail


async def test_moving_to_contained_stamps_containment(stub_update, audit_calls):
    inc = stub_update["inc"] = _incident()
    await incidents_api.update_incident(inc.id, IncidentUpdate(status=IncidentStatus.contained), FakeDB(), _actor())
    assert inc.contained_at is not None and inc.contained_at >= inc.detected_at
    assert "contained_at" in audit_calls[-1]["changes"]["fields"]


async def test_marking_reportable_starts_the_regulator_clock(stub_update, audit_calls):
    inc = stub_update["inc"] = _incident()
    await incidents_api.update_incident(inc.id, IncidentUpdate(is_reportable=True), FakeDB(), _actor())
    rows = {r.report_type: r for r in inc.regulatory_reports}
    hours = settings.regulatory_initial_report_hours
    assert rows[INITIAL].deadline == inc.detected_at + timedelta(hours=hours)
    assert rows[FINAL].deadline == inc.detected_at + timedelta(days=settings.regulatory_final_report_days)
    assert inc.regulator == settings.default_regulator  # a reportable incident is owed to someone
    assert audit_calls[-1]["changes"]["regulatory"] == ["initial notification created", "final report created"]


async def test_correcting_detection_moves_the_pending_deadlines(stub_update):
    t0 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    old = clock.planned_deadlines(t0, settings.regulatory_initial_report_hours, settings.regulatory_final_report_days)
    initial = RegulatoryReport(report_type=INITIAL, deadline=old[INITIAL], status=RegulatoryReportStatus.pending,
                               regulator="SBP", regulator_id=None)
    inc = stub_update["inc"] = _incident(is_reportable=True, regulator="SBP", regulatory_reports=[initial])
    earlier = t0 - timedelta(hours=1)  # still after it occurred (t0 - 2h)
    await incidents_api.update_incident(inc.id, IncidentUpdate(detected_at=earlier), FakeDB(), _actor())
    assert initial.deadline == earlier + timedelta(hours=settings.regulatory_initial_report_hours)
    # The final report was removed on purpose earlier; a correction does not bring it back.
    assert [r.report_type for r in inc.regulatory_reports] == [INITIAL]


async def test_a_read_carries_the_clock_and_response_times():
    t0 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    report = SimpleNamespace(report_type=INITIAL, deadline=t0 + timedelta(hours=24),
                             status=RegulatoryReportStatus.submitted, submitted_at=t0 + timedelta(hours=20),
                             reference="SBP-ACK-9")
    inc = _incident(regulatory_reports=[report], contained_at=t0 + timedelta(hours=3))
    item = incidents_api.with_clock(IncidentRead.model_validate(_read_payload()), inc, t0 + timedelta(days=2))
    assert item.notification_deadline == t0 + timedelta(hours=24)
    assert item.notified_at == t0 + timedelta(hours=20) and item.regulator_reference == "SBP-ACK-9"
    assert item.hours_to_deadline == 4.0 and item.notified_on_time is True
    assert (item.mttd_hours, item.mttc_hours, item.mttr_hours) == (2.0, 3.0, None)


def test_the_summary_averages_response_times_and_leaves_near_misses_out_of_losses():
    t0 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    late = SimpleNamespace(report_type=INITIAL, deadline=t0, status=RegulatoryReportStatus.pending,
                           submitted_at=None, reference="")
    rows = [
        _incident(cost=5000.0, contained_at=t0 + timedelta(hours=2), resolved_at=t0 + timedelta(hours=10),
                  is_reportable=True, regulatory_reports=[late], status=IncidentStatus.resolved),
        _incident(cost=900.0, near_miss=True, occurred_at=t0 - timedelta(hours=4), personal_data_breach=True),
    ]
    s = incidents_api.summarize(rows, now=t0 + timedelta(hours=1))
    assert s.total == 2 and s.open == 1 and s.near_misses == 1 and s.personal_data_breaches == 1
    assert s.total_cost == 5000.0
    assert s.notifications_pending == 1 and s.notifications_overdue == 1
    assert s.response_times.mttd_hours == 3.0 and s.response_times.mttd_count == 2
    assert s.response_times.mttr_hours == 10.0 and s.response_times.mttr_count == 1
    assert s.customers_affected == 1800 and s.records_affected == 3600


# ------------------------------------------------------ personal data breach ---
@pytest.fixture
def breach_env(monkeypatch, audit_calls):
    async def zone_of(db, tenant_id):
        return PKT

    async def next_ref(db, model, prefix):
        return f"{prefix}-007"

    monkeypatch.setattr(clock, "tenant_zone", zone_of)
    monkeypatch.setattr(incidents_api, "next_reference", next_ref)
    monkeypatch.setattr(incidents_api, "module_enabled", lambda key: True)
    return audit_calls


async def test_a_personal_data_breach_opens_a_breach_and_tells_the_dpo(breach_env):
    inc = _incident(personal_data_breach=True, occurred_at=datetime(2026, 9, 9, 20, 0, tzinfo=UTC))
    db = FakeDB(roles=[SimpleNamespace(name="Data Protection Officer"), SimpleNamespace(name="Viewer")])
    breach, note = await incidents_api._hand_off_breach(db, inc, _actor())
    assert isinstance(breach, DataBreach) and breach.reference == "BR-007" and breach.incident is inc
    assert breach.records_affected == 1800 and breach.severity == Severity.high
    assert breach.notification_required is True
    # 20:00 UTC on 9 Sep is 01:00 on 10 Sep in Karachi: the register's date is the local one.
    assert breach.occurred_date == date(2026, 9, 10) and breach.discovered_date == date(2026, 9, 10)
    notes = [o for o in db.added if isinstance(o, Notification)]
    assert len(notes) == 1 and notes[0].dedup_key == f"{EVENT_PREFIX}personal-data-breach:{breach.id}"
    assert "Data Protection Officer" in notes[0].body and "DPO notified" in note
    assert breach_env[-1]["entity_type"] == "data_breach" and breach_env[-1]["action"] == "create"


async def test_without_a_dpo_role_the_breach_is_audited_only(breach_env):
    db = FakeDB(roles=[SimpleNamespace(name="Risk Manager")])
    breach, note = await incidents_api._hand_off_breach(db, _incident(personal_data_breach=True), _actor())
    assert breach is not None and not [o for o in db.added if isinstance(o, Notification)]
    assert "no DPO role" in note and "no DPO role" in breach_env[-1]["summary"]


async def test_the_breach_is_created_once(breach_env):
    existing = SimpleNamespace(reference="BR-003")
    db = FakeDB(scalar=existing)
    breach, note = await incidents_api._hand_off_breach(db, _incident(personal_data_breach=True), _actor())
    assert breach is existing and db.added == [] and "already linked to BR-003" in note


# --------------------------------------------------------------- loss event ---
@pytest.fixture
def loss_env(monkeypatch, audit_calls):
    holder = {}

    async def load(db, _id):
        return holder["inc"]

    async def fresh(db, _id):
        return holder["inc"]

    async def read(db, obj):
        return obj

    async def org(db, tenant_id):
        return SimpleNamespace(timezone="Asia/Karachi", currency="PKR")

    async def next_ref(db, model, prefix):
        return f"{prefix}-012"

    monkeypatch.setattr(incidents_api, "_load", load)
    monkeypatch.setattr(incidents_api, "_fresh", fresh)
    monkeypatch.setattr(incidents_api, "incident_read", read)
    monkeypatch.setattr(incidents_api, "next_reference", next_ref)
    monkeypatch.setattr(tenant_settings_api, "get_or_create_settings", org)
    return holder


async def test_a_loss_event_is_prefilled_from_the_incident(loss_env, audit_calls):
    retail = uuid.uuid4()
    risk = SimpleNamespace(id=uuid.uuid4(), business_units=[SimpleNamespace(id=retail)])
    inc = loss_env["inc"] = _incident(cost=250000.0, root_cause="Unpatched gateway",
                                      assets=[SimpleNamespace(owner_id=retail)], risks=[risk])
    db = FakeDB()
    await incidents_api.create_loss_event(inc.id, db, _actor())
    loss = next(o for o in db.added if isinstance(o, LossEvent))
    assert loss.incident_id == inc.id and loss.reference == "LOSS-012"
    assert float(loss.gross_loss) == 250000.0 and loss.currency == "PKR"
    assert loss.business_unit_id == retail and loss.risks == [risk]
    assert loss.occurrence_date == date(2026, 9, 10) and loss.discovery_date == date(2026, 9, 10)
    assert loss.root_cause == "Unpatched gateway"
    assert {(c["entity_type"], c["action"]) for c in audit_calls} == {("loss_event", "create"), ("incident", "update")}


async def test_a_near_miss_has_no_loss_event(loss_env):
    inc = loss_env["inc"] = _incident(near_miss=True)
    with pytest.raises(HTTPException) as exc:
        await incidents_api.create_loss_event(inc.id, FakeDB(), _actor())
    assert exc.value.status_code == 409


def test_the_import_takes_a_date_or_a_date_time_for_the_timeline():
    from app.services.import_registry import REGISTRY

    cols = {c.field: c for c in REGISTRY["incidents"].columns}
    for f in clock.TIMELINE_FIELDS:
        assert cols[f].kind == "text" and "00:00" in cols[f].help, f
    assert {"near_miss", "personal_data_breach", "is_reportable", "customers_affected"} <= set(cols)


# ------------------------------------------------------- notification on form ---
def test_the_form_records_the_notification_on_the_initial_report():
    t0 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    initial = _report(INITIAL, t0 + timedelta(hours=24))
    final = _report(FINAL, t0 + timedelta(days=30))
    notes = clock.apply_notification([final, initial], {"notified_at": t0 + timedelta(hours=7),
                                                        "regulator_reference": " SBP/IR/77 "})
    assert initial.submitted_at == t0 + timedelta(hours=7) and initial.status == RegulatoryReportStatus.submitted
    assert initial.reference == "SBP/IR/77" and final.submitted_at is None
    assert notes == ["initial notification recorded", "regulator reference recorded"]
    clock.apply_notification([initial], {"notified_at": None})
    assert initial.submitted_at is None and initial.status == RegulatoryReportStatus.pending


def test_a_notification_needs_a_reportable_incident():
    with pytest.raises(ValueError):
        clock.apply_notification([], {"notified_at": datetime(2026, 9, 10, tzinfo=UTC)})
    assert clock.apply_notification([], {"notified_at": None, "regulator_reference": ""}) == []


async def test_a_notification_on_a_non_reportable_incident_is_a_conflict(stub_update):
    inc = stub_update["inc"] = _incident()
    with pytest.raises(HTTPException) as exc:
        await incidents_api.update_incident(
            inc.id, IncidentUpdate(notified_at=datetime(2026, 9, 10, 12, 0, tzinfo=UTC)), FakeDB(), _actor()
        )
    assert exc.value.status_code == 409


def test_resending_the_notification_the_form_showed_changes_nothing():
    t0 = datetime(2026, 9, 10, 9, 0, 27, tzinfo=UTC)
    initial = _report(INITIAL, t0 + timedelta(hours=24), status=RegulatoryReportStatus.acknowledged,
                      submitted_at=t0, reference="SBP/IR/77")
    notes = clock.apply_notification([initial], {"notified_at": t0.replace(second=0), "regulator_reference": "SBP/IR/77"})
    assert notes == [] and initial.submitted_at == t0 and initial.status == RegulatoryReportStatus.acknowledged
