"""Continuous-control-monitoring evidence feed (phase 3, plan §3.4).

A monitoring tool posts results for a connector with a token instead of a login. These
pin the token (shape, SHA-256 only, constant-time check, one 401 for every failure),
what a result becomes (evidence on the control, a run of the connector's test when
there is exactly one, an alert when it failed — at most one a day), what it must never
do (move the control's effectiveness), and the refusals (a time in the future, an
unknown control, a test of another control). Pure — the ingest runs against a fake
tenant session.
"""
import hashlib
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import integrations as ccm
from app.models.enums import ControlEffectiveness, EvidenceStatus, EvidenceType
from app.models.integrations import CcmResult, CcmStatus, ConnectorStatus
from app.schemas.integrations import IngestBody

TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
CONNECTOR = uuid.UUID("22222222-2222-2222-2222-222222222222")
KHI = ZoneInfo("Asia/Karachi")


# ------------------------------------------------------------------------- token ---
def test_a_token_names_its_organisation_and_connector():
    token = ccm.new_ingest_token(TENANT, CONNECTOR)
    assert token.startswith(f"{TENANT.hex}.{CONNECTOR.hex}.")
    assert ccm.parse_ingest_token(token) == (TENANT, CONNECTOR)
    assert ccm.new_ingest_token(TENANT, CONNECTOR) != token


@pytest.mark.parametrize("bad", [
    None, "", "abc", f"{TENANT.hex}.secretsecretsecretsecret",            # a KRI-style token
    f"{TENANT.hex}.{CONNECTOR.hex}.short",                                  # secret too short
    f"nothex.{CONNECTOR.hex}.{'x' * 40}", f"{TENANT.hex}.{CONNECTOR.hex}.{'x' * 40}.extra",
])
def test_malformed_tokens_are_rejected(bad):
    assert ccm.parse_ingest_token(bad) is None


def test_only_the_hash_is_compared_in_constant_time(monkeypatch):
    token = ccm.new_ingest_token(TENANT, CONNECTOR)
    stored = hashlib.sha256(token.encode()).hexdigest()
    assert ccm.ingest_token_hash(token) == stored
    calls = []
    real = ccm.hmac.compare_digest
    monkeypatch.setattr(ccm.hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real(a, b))
    assert ccm.ingest_token_matches(token, stored)
    assert not ccm.ingest_token_matches(token + "x", stored)
    assert len(calls) == 2
    assert not ccm.ingest_token_matches(token, "")  # revoked
    assert not ccm.ingest_token_matches("", stored)


def test_the_token_never_reaches_read_models_or_history():
    from app.schemas.integrations import ConnectorRead
    from app.services import versioning

    assert "ingest_token_hash" not in ConnectorRead.model_fields
    assert "has_ingest_token" in ConnectorRead.model_fields
    # Connectors are not versioned; if they ever are, the hash must be skipped.
    assert "connector" not in versioning.MODEL_MAP or "ingest_token_hash" in versioning._SKIP


# ---------------------------------------------------------------------- rules ---
def test_a_result_from_the_future_is_refused_beyond_clock_skew():
    now = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    assert ccm.observed_refusal(now - timedelta(days=3), now) is None
    assert ccm.observed_refusal(now + timedelta(minutes=1), now) is None   # a slightly fast clock
    assert "future" in ccm.observed_refusal(now + timedelta(minutes=10), now)


def test_run_result_and_pass_rate():
    assert ccm.RUN_RESULT["passed_with_exceptions"] == CcmResult.passed
    assert ccm.RUN_RESULT["failed"] == CcmResult.failed
    assert ccm.run_pass_rate("passed", None) == 100.0
    assert ccm.run_pass_rate("failed", None) == 0.0
    assert ccm.run_pass_rate("passed_with_exceptions", 97.5) == 97.5


def _test(ref, control_ref, status=CcmStatus.active, connector=CONNECTOR, deleted=False):
    return SimpleNamespace(id=uuid.uuid4(), reference=ref, control_ref=control_ref, status=status,
                           connector_id=connector, deleted=deleted, last_run=None, last_result=CcmResult.not_run,
                           pass_rate=0)


def test_the_one_active_test_for_the_control_records_the_run():
    t = _test("CCM-1", " a.8.5 ")
    m = ccm.match_test([t, _test("CCM-2", "A.8.2"), _test("CCM-3", "A.8.5", connector=uuid.uuid4())],
                       connector_id=CONNECTOR, control_reference="A.8.5", test_reference=None)
    assert m.test is t and m.note == ""


def test_no_ambiguous_or_paused_test_records_no_run_and_says_why():
    none = ccm.match_test([], connector_id=CONNECTOR, control_reference="A.8.5", test_reference=None)
    assert none.test is None and "No monitoring test" in none.note
    two = ccm.match_test([_test("CCM-1", "A.8.5"), _test("CCM-2", "A.8.5")],
                         connector_id=CONNECTOR, control_reference="A.8.5", test_reference=None)
    assert two.test is None and "test_reference" in two.note and "CCM-1, CCM-2" in two.note
    paused = ccm.match_test([_test("CCM-1", "A.8.5", CcmStatus.paused)],
                            connector_id=CONNECTOR, control_reference="A.8.5", test_reference=None)
    assert paused.test is None and "paused" in paused.note
    archived = ccm.match_test([_test("CCM-1", "A.8.5", deleted=True)],
                              connector_id=CONNECTOR, control_reference="A.8.5", test_reference=None)
    assert archived.test is None


def test_a_named_test_must_be_this_connectors_and_this_controls():
    mine = _test("CCM-1", "A.8.5")
    other_control = _test("CCM-2", "A.8.2")
    blank = _test("CCM-3", "")
    kw = dict(connector_id=CONNECTOR, control_reference="A.8.5")
    assert ccm.match_test([mine, other_control], test_reference="ccm-1", **kw).test is mine
    assert ccm.match_test([blank], test_reference="CCM-3", **kw).test is blank
    with pytest.raises(ValueError, match="monitors control A.8.2"):
        ccm.match_test([other_control], test_reference="CCM-2", **kw)
    with pytest.raises(ValueError, match="no monitoring test"):
        ccm.match_test([_test("CCM-9", "A.8.5", connector=uuid.uuid4())], test_reference="CCM-9", **kw)


def test_a_failed_result_alert_is_one_per_control_per_day():
    connector = SimpleNamespace(id=CONNECTOR, name="Azure AD")
    control = SimpleNamespace(id=uuid.uuid4(), reference="A.8.5", name="Secure authentication", is_key=True)
    a = ccm.failed_alert(connector=connector, control=control, observed_local="2026-09-12 10:00",
                         summary="3 admins without MFA", owner="Sara", day=date(2026, 9, 12))
    b = ccm.failed_alert(connector=connector, control=control, observed_local="2026-09-12 18:00",
                         summary="2 admins without MFA", owner="Sara", day=date(2026, 9, 12))
    c = ccm.failed_alert(connector=connector, control=control, observed_local="2026-09-13 10:00",
                         summary="x", owner="", day=date(2026, 9, 13))
    assert a["dedup_key"] == b["dedup_key"] != c["dedup_key"]
    assert a["dedup_key"].startswith("event:ccm-failed:")
    assert a["category"].value == "critical" and a["entity_type"] == "control"
    assert a["link"] == f"/controls?id={control.id}"
    assert "effectiveness is unchanged" in a["body"] and "Control owner: Sara" in a["body"]
    control.is_key = False
    assert ccm.failed_alert(connector=connector, control=control, observed_local="", summary="x", owner="",
                            day=date(2026, 9, 12))["category"].value == "warning"


# ---------------------------------------------------------------- request body ---
def _body(**kw):
    base = {"control_reference": "A.8.5", "result": "passed", "observed_at": "2026-09-12T10:00:00+05:00",
            "summary": "All privileged accounts have MFA"}
    return IngestBody(**{**base, **kw})


def test_the_body_needs_a_control():
    with pytest.raises(ValidationError, match="control_reference or control_id"):
        _body(control_reference=None)
    assert _body(control_reference=None, control_id=str(uuid.uuid4())).control_id


def test_exceptions_need_a_pass_rate_and_results_are_closed():
    with pytest.raises(ValidationError, match="pass_rate"):
        _body(result="passed_with_exceptions")
    assert _body(result="passed_with_exceptions", pass_rate=98).pass_rate == 98
    with pytest.raises(ValidationError):
        _body(result="error")
    with pytest.raises(ValidationError):
        _body(pass_rate=101)


def test_oversized_details_are_refused():
    with pytest.raises(ValidationError, match="details"):
        _body(details={"rows": ["x" * 1000] * 60})


def test_token_admin_needs_ccm_write_or_integration_manage():
    import asyncio

    ok = SimpleNamespace(permission_codes=["ccm:read", "integration:manage"])
    assert asyncio.run(ccm._token_admin(ok)) is ok
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ccm._token_admin(SimpleNamespace(permission_codes=["ccm:read"])))
    assert exc.value.status_code == 403


# ------------------------------------------------------------ authentication ---
async def test_a_missing_or_malformed_token_is_401_before_any_database():
    for creds in (None, SimpleNamespace(scheme="Bearer", credentials="nope"),
                  SimpleNamespace(scheme="Basic", credentials=ccm.new_ingest_token(TENANT, CONNECTOR))):
        with pytest.raises(HTTPException) as exc:
            await ccm._verified_ingest(creds)
        assert exc.value.status_code == 401 and exc.value.detail == "Invalid or revoked connector feed token."


class FakeDB:
    """Answers each query by the entity it selects; records what is added."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.added = []

    @staticmethod
    def _entity(stmt):
        desc = stmt.column_descriptions[0]
        return desc.get("entity") or desc.get("type")

    async def get(self, model, key):
        return self.answers.get(model.__name__)

    async def scalar(self, stmt):
        value = self.answers.get(self._entity(stmt).__name__)
        return value[0] if isinstance(value, list) else value

    async def scalars(self, stmt):
        value = self.answers.get(self._entity(stmt).__name__, [])
        return SimpleNamespace(all=lambda: value if isinstance(value, list) else [value])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


def _connector(token, status=ConnectorStatus.active):
    return SimpleNamespace(id=CONNECTOR, reference="CON-004", name="Azure AD", status=status,
                           ingest_token_hash=ccm.ingest_token_hash(token), last_sync=None)


def _answers(token, **kw):
    return {"Tenant": SimpleNamespace(is_active=True), "TenantSettings": None, "Connector": _connector(token), **kw}


@pytest.mark.parametrize("case", ["wrong", "revoked", "disabled", "inactive", "module_off", "archived"])
async def test_every_authentication_failure_is_the_same_401(case, monkeypatch):
    from app.services import modules

    token = ccm.new_ingest_token(TENANT, CONNECTOR)
    answers = _answers(token)
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    presented = token
    if case == "wrong":
        presented = ccm.new_ingest_token(TENANT, CONNECTOR)
    elif case == "revoked":
        answers["Connector"].ingest_token_hash = ""
    elif case == "disabled":
        answers["Connector"].status = ConnectorStatus.disabled
    elif case == "inactive":
        answers["Tenant"] = SimpleNamespace(is_active=False)
    elif case == "module_off":
        answers["TenantSettings"] = [["risk"]]  # enabled_modules without CCM: switched off
    elif case == "archived":
        answers["Connector"] = None
    with pytest.raises(HTTPException) as exc:
        await ccm._feed_connector(FakeDB(answers), presented, TENANT, CONNECTOR)
    assert exc.value.status_code == 401 and exc.value.detail == "Invalid or revoked connector feed token."


async def test_the_right_token_opens_the_connector(monkeypatch):
    from app.services import modules

    token = ccm.new_ingest_token(TENANT, CONNECTOR)
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    answers = _answers(token)
    assert await ccm._feed_connector(FakeDB(answers), token, TENANT, CONNECTOR) is answers["Connector"]


# ------------------------------------------------------------------- ingest ---
def _control(**kw):
    base = dict(id=uuid.uuid4(), reference="A.8.5", name="Secure authentication", is_key=True, owner="",
                owner_id=None, effectiveness=ControlEffectiveness.effective,
                operating_effectiveness=ControlEffectiveness.effective)
    return SimpleNamespace(**{**base, **kw})


@pytest.fixture
def ingest_env(monkeypatch):
    """A fake tenant session for ``POST /connectors/ingest``; returns (db, token, audits)."""
    from contextlib import asynccontextmanager

    from app.services import incident_clock, modules, webhooks

    token = ccm.new_ingest_token(TENANT, CONNECTOR)
    control = _control()
    test = _test("CCM-001", "A.8.5")
    db = FakeDB(_answers(token, Control=[control], AutomatedControlTest=[test], Notification=None, User=[]))

    @asynccontextmanager
    async def fake_session(tenant_id):
        assert tenant_id == TENANT
        yield db

    async def zone(db_, tid):
        return KHI

    async def no_hooks(*a, **kw):
        return 0

    monkeypatch.setattr(ccm, "tenant_session", fake_session)
    monkeypatch.setattr(incident_clock, "tenant_zone", zone)
    monkeypatch.setattr(incident_clock, "now_utc", lambda: datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc))
    monkeypatch.setattr(modules, "is_enabled", lambda key: True)
    monkeypatch.setattr(webhooks, "dispatch", no_hooks)
    # Phase 4 follow-up (issue, reliance signal, KRI) is pinned in test_phase4_ccm.py.
    from app.services import ccm_runner

    async def no_follow_up(*a, **kw):
        return ccm_runner.FollowUp()

    monkeypatch.setattr(ccm_runner, "follow_up", no_follow_up)
    return SimpleNamespace(db=db, token=token, control=control, test=test)


def _auth(env):
    return ccm._IngestAuth(env.token, TENANT, CONNECTOR)


def _added(env, name):
    return [o for o in env.db.added if type(o).__name__ == name]


async def test_a_failed_result_becomes_evidence_a_run_and_an_alert_but_not_a_rating(ingest_env):
    env = ingest_env
    body = _body(result="failed", summary="3 admin accounts without MFA", details={"accounts": ["a", "b", "c"]},
                 evidence={"title": "MFA report 12 Sep", "url": "https://siem.bank.pk/r/42", "valid_until": "2026-12-31"})
    out = await ccm.ingest_result(body, _auth(env))

    evidence = _added(env, "Evidence")[0]
    assert (evidence.control_id, evidence.status, evidence.evidence_type) == (env.control.id, EvidenceStatus.valid, EvidenceType.link)
    assert evidence.collected_at == date(2026, 9, 12) and evidence.valid_until == date(2026, 12, 31)
    assert evidence.reference == "https://siem.bank.pk/r/42" and '"accounts"' in evidence.description

    run = _added(env, "ControlTestRun")[0]
    assert (run.test_id, run.result, run.pass_rate, run.run_date) == (env.test.id, CcmResult.failed, 0.0, date(2026, 9, 12))
    assert (env.test.last_result, env.test.last_run) == (CcmResult.failed, date(2026, 9, 12))

    alert = _added(env, "Notification")[0]
    assert alert.dedup_key.startswith("event:ccm-failed:") and alert.entity_id == env.control.id

    # The rating is untouched: effectiveness moves only on a reviewed test.
    assert env.control.effectiveness == ControlEffectiveness.effective
    assert env.control.operating_effectiveness == ControlEffectiveness.effective

    audits = _added(env, "AuditLog")
    assert {a.actor_email for a in audits} == {"Connector Azure AD"}
    assert {(a.entity_type, a.action) for a in audits} == {
        ("connector", "ingest"), ("evidence", "create"), ("control", "monitoring"), ("automated_control_test", "record_run"),
    }
    assert all(a.actor_id is None for a in audits)
    assert (out.run_id, out.test_reference, out.alert_raised) == (run.id, "CCM-001", True)
    assert _added(env, "Connector") == [] and env.db.answers["Connector"].last_sync == date(2026, 9, 12)


async def test_a_pass_raises_no_alert_and_evidence_defaults_are_sensible(ingest_env):
    env = ingest_env
    out = await ccm.ingest_result(_body(), _auth(env))
    evidence = _added(env, "Evidence")[0]
    assert evidence.title == "Azure AD: passed — All privileged accounts have MFA"
    assert evidence.evidence_type == EvidenceType.log and evidence.valid_until is None
    assert _added(env, "Notification") == [] and out.alert_raised is False
    assert _added(env, "ControlTestRun")[0].pass_rate == 100.0


async def test_the_same_failure_twice_in_a_day_alerts_once(ingest_env):
    env = ingest_env
    env.db.answers["Notification"] = uuid.uuid4()  # today's alert already exists
    out = await ccm.ingest_result(_body(result="failed"), _auth(env))
    assert _added(env, "Notification") == [] and out.alert_raised is False


async def test_no_matching_test_still_keeps_the_evidence(ingest_env):
    env = ingest_env
    env.db.answers["AutomatedControlTest"] = []
    out = await ccm.ingest_result(_body(), _auth(env))
    assert _added(env, "ControlTestRun") == [] and len(_added(env, "Evidence")) == 1
    assert out.run_id is None and "No monitoring test" in out.note


async def test_a_naive_time_is_the_organisations_and_the_future_is_refused(ingest_env):
    env = ingest_env
    await ccm.ingest_result(_body(observed_at="2026-09-12T16:59:00"), _auth(env))  # 11:59 UTC
    assert _added(env, "Evidence")[0].collected_at == date(2026, 9, 12)
    with pytest.raises(HTTPException) as exc:
        await ccm.ingest_result(_body(observed_at="2026-09-12T17:30:00"), _auth(env))  # 12:30 UTC, 30 min ahead
    assert exc.value.status_code == 422 and "future" in exc.value.detail


async def test_an_unknown_or_ambiguous_control_is_refused(ingest_env):
    env = ingest_env
    env.db.answers["Control"] = []
    with pytest.raises(HTTPException) as exc:
        await ccm.ingest_result(_body(), _auth(env))
    assert exc.value.status_code == 422 and "no control has the reference" in exc.value.detail
    env.db.answers["Control"] = [_control(), _control()]
    with pytest.raises(HTTPException) as exc:
        await ccm.ingest_result(_body(), _auth(env))
    assert "send control_id" in exc.value.detail


async def test_evidence_cannot_expire_before_it_was_observed(ingest_env):
    env = ingest_env
    with pytest.raises(HTTPException) as exc:
        await ccm.ingest_result(_body(evidence={"title": "t", "valid_until": "2026-09-01"}), _auth(env))
    assert exc.value.status_code == 422


async def test_a_run_back_filled_before_the_latest_does_not_roll_up(ingest_env):
    env = ingest_env
    env.test.last_run, env.test.last_result = date(2026, 9, 12), CcmResult.passed
    await ccm.ingest_result(_body(result="failed", observed_at="2026-09-10T10:00:00+05:00"), _auth(env))
    assert _added(env, "ControlTestRun")[0].run_date == date(2026, 9, 10)
    assert env.test.last_result == CcmResult.passed and env.test.last_run == date(2026, 9, 12)
