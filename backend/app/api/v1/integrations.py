"""Integrations & Continuous Controls Monitoring (CCM) API.

A connector registry plus automated control tests that record pass/fail over time.
Recording a run updates the parent test's last_run / last_result / pass_rate so the UI
can trend control health.

**Monitoring feed (phase 3).** ``POST /connectors/{id}/ingest-token`` issues a token for
one connector, shown once (only its SHA-256 is kept); ``DELETE`` revokes it. The
monitoring tool then posts each result to ``POST /connectors/ingest`` with
``Authorization: Bearer <token>`` and no user session. The token is
``<organisation hex>.<connector hex>.<secret>``, so the endpoint can open that
organisation's row-level-security scope and find the connector before checking the
secret in constant time; every authentication failure is the same 401. Each result:

* is recorded as **evidence** on the control (collected when observed, valid), which is
  how it shows on the control;
* is recorded as a **run** of the connector's monitoring test for that control, when the
  connector has exactly one active test for it (or the one ``test_reference`` names);
* raises a **"Continuous monitoring failed"** alert when it failed — at most one per
  control and connector per day;
* never changes the control's **effectiveness**: that moves only on a test a person
  records and another person reviews (phase 2). The evidence is there to attach to it.

Every write is in the activity trail with the actor ``Connector <name>``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status as http_status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.database import tenant_session
from app.core.deps import CurrentUser, DbSession, require
from app.core.listing import ListParams, apply_sort
from app.models.integrations import (
    AutomatedControlTest,
    CcmResult,
    CcmStatus,
    Connector,
    ConnectorStatus,
    ConnectorType,
    ControlTestRun,
)
from app.schemas.common import Page
from app.schemas.integrations import (
    CheckTypeRead,
    ConnectionTestResult,
    ConnectorKindRead,
    ControlMonitoringRead,
    MonitoringTestRead,
    ParamSpecRead,
    RunDetail,
    RunNowResult,
    RunRead,
    SecretsWrite,
    CctCreate,
    CctRead,
    CctUpdate,
    ConnectorCreate,
    ConnectorFeedRead,
    ConnectorRead,
    ConnectorUpdate,
    IngestBody,
    IngestLogItem,
    IngestResult,
    IngestTokenIssued,
    RunCreate,
)
from app.services.refs import next_reference
from app.services import ccm_checks, ccm_rate_limit, ccm_runner
from app.services.rate_limit import too_many_requests
from app.services.ccm_checks import secrets as ccm_secrets
from app.services import audit as audit_log

router = APIRouter(tags=["integrations"])

_READ = Depends(require("ccm:read"))
_WRITE = Depends(require("ccm:write"))

_CONNECTOR_SORTABLE = {
    "name": Connector.name,
    "reference": Connector.reference,
    "status": Connector.status,
    "connector_type": Connector.connector_type,
    "last_sync": Connector.last_sync,
    "created_at": Connector.created_at,
}
_CCT_SORTABLE = {
    "name": AutomatedControlTest.name,
    "reference": AutomatedControlTest.reference,
    "control_ref": AutomatedControlTest.control_ref,
    "status": AutomatedControlTest.status,
    "last_result": AutomatedControlTest.last_result,
    "pass_rate": AutomatedControlTest.pass_rate,
    "last_run": AutomatedControlTest.last_run,
    "created_at": AutomatedControlTest.created_at,
}


async def _next_ref(db, model, prefix: str) -> str:
    return await next_reference(db, model, prefix)


async def _get(db, model, obj_id, name):
    obj = await db.scalar(select(model).where(model.id == obj_id))
    if obj is None or getattr(obj, "deleted", False):
        raise HTTPException(status_code=404, detail=f"{name} not found")
    return obj


# ================================================================ connectors ===
async def _load_connector(db, cid) -> Connector:
    obj = await db.scalar(
        select(Connector)
        .where(Connector.id == cid, Connector.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return obj


@router.get("/connectors", response_model=Page[ConnectorRead], dependencies=[_READ])
async def list_connectors(
    db: DbSession,
    status: ConnectorStatus | None = None,
    connector_type: ConnectorType | None = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ConnectorRead]:
    stmt = select(Connector).where(Connector.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(Connector.status == status)
    if connector_type is not None:
        stmt = stmt.where(Connector.connector_type == connector_type)
    if search:
        stmt = stmt.where(Connector.name.ilike(f"%{search}%") | Connector.reference.ilike(f"%{search}%"))
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CONNECTOR_SORTABLE, default=Connector.name)
    else:
        stmt = stmt.order_by(Connector.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[ConnectorRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/connectors", response_model=ConnectorRead, status_code=201, dependencies=[_WRITE])
async def create_connector(body: ConnectorCreate, db: DbSession, user: CurrentUser) -> ConnectorRead:
    data = body.model_dump(exclude={"secrets", "clear_secrets"})
    _check_connector_settings(data["connector_type"], data.get("config") or {}, body.secrets)
    obj = Connector(tenant_id=user.tenant_id, **data)
    changed = ccm_secrets.apply(obj, body.secrets, None)
    obj.reference = await _next_ref(db, Connector, "CON")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="connector",
                           entity_id=obj.id, summary=f"Registered connector {obj.reference}: {obj.name}"
                           + (f"; secrets set: {', '.join(changed)}" if changed else ""))
    return ConnectorRead.model_validate(await _load_connector(db, obj.id))


@router.get("/connectors/{cid}", response_model=ConnectorRead, dependencies=[_READ])
async def get_connector(cid: uuid.UUID, db: DbSession) -> ConnectorRead:
    return ConnectorRead.model_validate(await _load_connector(db, cid))


def _check_connector_settings(connector_type, config: dict, secrets: dict | None, clear: list | None = None) -> None:
    errors = ccm_checks.config_errors(connector_type, config) + ccm_checks.secret_errors(
        connector_type, list((secrets or {}).keys()) + list(clear or []))
    if errors:
        raise HTTPException(status_code=422, detail=" ".join(errors))


def _changes(obj, data: dict) -> dict:
    out = {}
    for k, v in data.items():
        before = getattr(obj, k)
        if before != v:
            out[k] = {"from": str(getattr(before, "value", before)), "to": str(getattr(v, "value", v))}
    return out


@router.patch("/connectors/{cid}", response_model=ConnectorRead, dependencies=[_WRITE])
async def update_connector(cid: uuid.UUID, body: ConnectorUpdate, db: DbSession, user: CurrentUser) -> ConnectorRead:
    obj = await _load_connector(db, cid)
    data = body.model_dump(exclude_unset=True, exclude={"secrets", "clear_secrets"})
    ctype = data.get("connector_type") or obj.connector_type
    _check_connector_settings(getattr(ctype, "value", ctype), data.get("config", obj.config) or {},
                              body.secrets, body.clear_secrets)
    changes = _changes(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    secret_changes = ccm_secrets.apply(obj, body.secrets, body.clear_secrets)
    if secret_changes:
        # Names only: a secret's value never reaches the activity trail.
        changes["secrets"] = {"from": "", "to": "changed: " + ", ".join(secret_changes)}
    await db.flush()
    if changes:
        await audit_log.record(db, actor=user, action="update", entity_type="connector", entity_id=obj.id,
                               summary=f"Updated connector {obj.reference}: {', '.join(changes)}"[:500],
                               changes=changes)
    return ConnectorRead.model_validate(await _load_connector(db, cid))


@router.delete("/connectors/{cid}", status_code=204, dependencies=[_WRITE])
async def delete_connector(cid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_connector(db, cid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    # An archived connector's feed stops for good: restoring it needs a new token.
    had_token = bool(obj.ingest_token_hash)
    obj.ingest_token_hash = ""
    await db.flush()
    await audit_log.record(db, actor=user, action="delete", entity_type="connector", entity_id=obj.id,
                           summary=f"Archived connector {obj.reference}: {obj.name}"
                                   + ("; its monitoring-feed token was revoked" if had_token else ""))


# ================================================= automated control tests (CCM) ===
DEFINITION_FIELDS = frozenset({"check_type", "parameters", "connector_id", "control_id", "kri_id", "control_ref"})


async def _check_definition(db, data: dict) -> None:
    """Refuse a definition that cannot run, in words; fill ``control_ref`` from the picked
    control. Only reads the database for the links actually set."""
    from app.models.control import Control
    from app.models.operational_risk import KeyRiskIndicator

    connector_type = None
    if data.get("connector_id"):
        connector = await db.scalar(select(Connector).where(Connector.id == data["connector_id"],
                                                            Connector.deleted.is_(False)))
        if connector is None:
            raise HTTPException(status_code=422, detail="connector_id: no such connector.")
        connector_type = connector.connector_type.value
    errors = ccm_checks.definition_errors(data.get("check_type") or "manual", data.get("parameters") or {}, connector_type)
    if errors:
        raise HTTPException(status_code=422, detail=" ".join(errors))
    if data.get("control_id"):
        control = await db.scalar(select(Control).where(Control.id == data["control_id"], Control.deleted.is_(False)))
        if control is None:
            raise HTTPException(status_code=422, detail="control_id: no such control.")
        data["control_ref"] = control.reference or data.get("control_ref") or ""
    if data.get("kri_id"):
        kri = await db.scalar(select(KeyRiskIndicator.id).where(KeyRiskIndicator.id == data["kri_id"],
                                                                KeyRiskIndicator.deleted.is_(False)))
        if kri is None:
            raise HTTPException(status_code=422, detail="kri_id: no such KRI.")


async def _load_test(db, tid) -> AutomatedControlTest:
    obj = await db.scalar(
        select(AutomatedControlTest)
        .where(AutomatedControlTest.id == tid, AutomatedControlTest.deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    if obj is None:
        raise HTTPException(status_code=404, detail="Automated control test not found")
    return obj


@router.get("/automated-control-tests", response_model=Page[CctRead], dependencies=[_READ])
async def list_tests(
    db: DbSession,
    status: CcmStatus | None = None,
    last_result: CcmResult | None = None,
    search: str | None = None,
    sort_by: Annotated[str | None, Query()] = None,
    sort_dir: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CctRead]:
    stmt = select(AutomatedControlTest).where(AutomatedControlTest.deleted.is_(False))
    if status is not None:
        stmt = stmt.where(AutomatedControlTest.status == status)
    if last_result is not None:
        stmt = stmt.where(AutomatedControlTest.last_result == last_result)
    if search:
        stmt = stmt.where(
            AutomatedControlTest.name.ilike(f"%{search}%")
            | AutomatedControlTest.reference.ilike(f"%{search}%")
            | AutomatedControlTest.control_ref.ilike(f"%{search}%")
        )
    if sort_by:
        params = ListParams(limit=limit, offset=offset, sort_by=sort_by, sort_dir=sort_dir, q=search)
        stmt = apply_sort(stmt, params, _CCT_SORTABLE, default=AutomatedControlTest.name)
    else:
        stmt = stmt.order_by(AutomatedControlTest.name)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.limit(limit).offset(offset))).all()
    return Page(items=[CctRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/automated-control-tests", response_model=CctRead, status_code=201, dependencies=[_WRITE])
async def create_test(body: CctCreate, db: DbSession, user: CurrentUser) -> CctRead:
    data = body.model_dump()
    await _check_definition(db, data)
    obj = AutomatedControlTest(tenant_id=user.tenant_id, **data)
    obj.reference = await _next_ref(db, AutomatedControlTest, "CCM")
    db.add(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="create", entity_type="automated_control_test",
                           entity_id=obj.id, summary=f"Created continuous control test {obj.reference}: {obj.name}")
    return CctRead.model_validate(await _load_test(db, obj.id))


@router.get("/automated-control-tests/{tid}", response_model=CctRead, dependencies=[_READ])
async def get_test(tid: uuid.UUID, db: DbSession) -> CctRead:
    return CctRead.model_validate(await _load_test(db, tid))


@router.patch("/automated-control-tests/{tid}", response_model=CctRead, dependencies=[_WRITE])
async def update_test(tid: uuid.UUID, body: CctUpdate, db: DbSession, user: CurrentUser) -> CctRead:
    obj = await _load_test(db, tid)
    data = body.model_dump(exclude_unset=True)
    if data.keys() & DEFINITION_FIELDS:
        merged = {f: getattr(obj, f) for f in DEFINITION_FIELDS} | data
        await _check_definition(db, merged)
        data.update({k: merged[k] for k in ("control_ref",) if k in merged and merged[k] != obj.control_ref})
    changes = _changes(obj, data)
    for k, v in data.items():
        setattr(obj, k, v)
    await db.flush()
    if changes:
        await audit_log.record(db, actor=user, action="update", entity_type="automated_control_test",
                               entity_id=obj.id, summary=f"Updated continuous control test {obj.reference}: "
                                                         f"{', '.join(changes)}"[:500], changes=changes)
    return CctRead.model_validate(await _load_test(db, tid))


@router.delete("/automated-control-tests/{tid}", status_code=204, dependencies=[_WRITE])
async def delete_test(tid: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await _load_test(db, tid)
    obj.deleted = True
    obj.deleted_date = datetime.now(timezone.utc)
    await db.flush()
    await audit_log.record(db, actor=user, action="delete", entity_type="automated_control_test",
                           entity_id=obj.id, summary=f"Archived continuous control test {obj.reference}: {obj.name}")


@router.post("/automated-control-tests/{tid}/runs", response_model=CctRead, status_code=201, dependencies=[_WRITE])
async def add_run(tid: uuid.UUID, body: RunCreate, db: DbSession, user: CurrentUser) -> CctRead:
    test = await _load_test(db, tid)
    run = ControlTestRun(tenant_id=user.tenant_id, test_id=tid, **body.model_dump())
    db.add(run)
    # Roll the outcome up onto the test only when this run is the latest — back-filling an
    # older run must not overwrite the current last_run / last_result / pass_rate.
    run_date = body.run_date or date.today()
    if test.last_run is None or run_date >= test.last_run:
        test.last_run = run_date
        test.last_result = body.result
        test.pass_rate = body.pass_rate
    await db.flush()
    await audit_log.record(db, actor=user, action="record_run", entity_type="automated_control_test",
                           entity_id=tid, summary=f"Recorded a {body.result.value.replace('_', ' ')} run of "
                                                  f"{test.reference} dated {run_date}",
                           changes={"run_id": str(run.id), "result": body.result.value,
                                    "pass_rate": body.pass_rate, "run_date": run_date.isoformat()})
    return CctRead.model_validate(await _load_test(db, tid))


@router.delete("/control-test-runs/{run_id}", status_code=204, dependencies=[_WRITE])
async def delete_run(run_id: uuid.UUID, db: DbSession, user: CurrentUser) -> None:
    obj = await db.scalar(select(ControlTestRun).where(ControlTestRun.id == run_id))
    if obj is None:
        raise HTTPException(status_code=404, detail="Record not found")
    test_id, facts = obj.test_id, {"run_id": str(obj.id), "result": obj.result.value,
                                   "run_date": obj.run_date.isoformat() if obj.run_date else None}
    await db.delete(obj)
    await db.flush()
    await audit_log.record(db, actor=user, action="delete_run", entity_type="automated_control_test",
                           entity_id=test_id, summary=f"Removed a {facts['result'].replace('_', ' ')} run dated "
                                                      f"{facts['run_date'] or 'undated'}", changes=facts)


# ================================================================== summary ===
class IntegrationsSummary(BaseModel):
    total_connectors: int
    active_connectors: int
    error_connectors: int
    stale_connectors: int
    total_tests: int
    tests_by_result: dict[str, int]
    avg_pass_rate: float
    failing_tests: int
    # Phase 4
    executable_tests: int = 0
    overdue_tests: int = 0
    error_tests: int = 0
    controls_failing_monitoring: int = 0


@router.get("/integrations-summary", response_model=IntegrationsSummary, dependencies=[_READ],
            summary="CCM dashboard roll-up: connector health and automated-control-test results")
async def integrations_summary(db: DbSession) -> IntegrationsSummary:
    connectors = (await db.scalars(select(Connector).where(Connector.deleted.is_(False)))).all()
    active = sum(1 for c in connectors if c.status == ConnectorStatus.active)
    errored = sum(1 for c in connectors if c.status == ConnectorStatus.error)
    stale = sum(1 for c in connectors if c.is_stale)

    tests = (await db.scalars(select(AutomatedControlTest).where(AutomatedControlTest.deleted.is_(False)))).all()
    by_result: dict[str, int] = defaultdict(int)
    for t in tests:
        by_result[t.last_result.value] += 1
    failing = by_result.get(CcmResult.failed.value, 0)
    rated = [float(t.pass_rate or 0) for t in tests]
    avg_pass = round(sum(rated) / len(rated), 2) if rated else 0.0

    return IntegrationsSummary(
        total_connectors=len(connectors),
        active_connectors=active,
        error_connectors=errored,
        stale_connectors=stale,
        total_tests=len(tests),
        tests_by_result=dict(by_result),
        avg_pass_rate=avg_pass,
        failing_tests=failing,
        executable_tests=sum(1 for t in tests if ccm_runner.is_executable(t)),
        overdue_tests=sum(1 for t in tests if ccm_runner.is_overdue(t, datetime.now(timezone.utc))),
        error_tests=by_result.get(CcmResult.error.value, 0),
        controls_failing_monitoring=len({t.control_id for t in tests
                                         if t.control_id and t.failing_since and t.status == CcmStatus.active}),
    )



# ============================================================ monitoring feed ===
INGEST_ENDPOINT = "/api/v1/connectors/ingest"
INGEST_TOKEN_BYTES = 32
#: How far a result's timestamp may run ahead of this server's clock (the monitoring
#: tool's clock may be a little fast) before it is refused as being in the future.
CLOCK_SKEW = timedelta(minutes=2)
# The result mapping, the failure alert and the connector actor live with the runner,
# which records pushed and pulled results through one path.
from app.services.ccm_runner import FAILED_FAMILY, RUN_RESULT, connector_actor, failed_alert  # noqa: E402,F401


def new_ingest_token(tenant_id: uuid.UUID, connector_id: uuid.UUID) -> str:
    """``<org hex>.<connector hex>.<secret>`` — the prefixes scope the lookup, the whole
    token (hashed) proves it."""
    return f"{tenant_id.hex}.{connector_id.hex}.{secrets.token_urlsafe(INGEST_TOKEN_BYTES)}"


def ingest_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def parse_ingest_token(token: str | None) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(organisation id, connector id) of a feed token, or None when it isn't shaped like
    one. Pure."""
    parts = (token or "").split(".")
    if len(parts) != 3 or len(parts[2]) < 20:
        return None
    try:
        return uuid.UUID(hex=parts[0]), uuid.UUID(hex=parts[1])
    except ValueError:
        return None


def ingest_token_matches(token: str, stored_hash: str) -> bool:
    """Constant-time check of a presented token against the stored hash. Pure."""
    if not token or not stored_hash:
        return False
    return hmac.compare_digest(ingest_token_hash(token), stored_hash)


def observed_refusal(observed: datetime, now: datetime) -> str | None:
    """A result can't come from the future (beyond :data:`CLOCK_SKEW`). Pure."""
    if observed > now + CLOCK_SKEW:
        return f"observed_at: {observed.isoformat()} is in the future; send the time the check ran."
    return None


def run_pass_rate(result: str, pass_rate: float | None) -> float:
    """The run's pass rate: as sent, else 100 for a pass and 0 for a failure. Pure."""
    if pass_rate is not None:
        return float(pass_rate)
    return 0.0 if result == "failed" else 100.0


def _norm(ref: str | None) -> str:
    return (ref or "").strip().lower()


@dataclass
class TestMatch:
    test: object | None
    note: str = ""


def match_test(tests, *, connector_id, control_reference: str, test_reference: str | None) -> TestMatch:
    """The monitoring test a result is recorded on. Pure.

    With ``test_reference``: that test, which must belong to this connector and (when it
    names a control) monitor this control — otherwise ``ValueError``. Without: the one
    active test of this connector for this control; none, several or a paused one mean
    no run is recorded, and the note says why."""
    live = [t for t in tests if not getattr(t, "deleted", False) and t.connector_id == connector_id]
    if test_reference:
        named = [t for t in live if _norm(t.reference) == _norm(test_reference)]
        if not named:
            raise ValueError(f"test_reference: this connector has no monitoring test {test_reference}.")
        test = named[0]
        if (test.control_ref or "").strip() and _norm(test.control_ref) != _norm(control_reference):
            raise ValueError(
                f"test_reference: {test.reference} monitors control {test.control_ref}, not {control_reference}."
            )
        if test.status == CcmStatus.paused:
            return TestMatch(None, f"{test.reference} is paused, so no run was recorded.")
        return TestMatch(test)
    mine = [t for t in live if _norm(t.control_ref) == _norm(control_reference) and _norm(control_reference)]
    active = [t for t in mine if t.status == CcmStatus.active]
    if len(active) == 1:
        return TestMatch(active[0])
    if len(active) > 1:
        refs = ", ".join(sorted(t.reference for t in active))
        return TestMatch(None, f"{len(active)} monitoring tests on this connector cover {control_reference} "
                               f"({refs}); send test_reference to record the run on one.")
    if mine:
        return TestMatch(None, f"The monitoring test for {control_reference} on this connector is paused, so no run was recorded.")
    return TestMatch(None, f"No monitoring test on this connector covers {control_reference}, so no run was recorded; "
                           "the result is kept as evidence.")


async def _token_admin(user: CurrentUser):
    """Issuing or revoking a feed token: whoever manages connectors (``ccm:write``) or
    integrations (``integration:manage``)."""
    if not ({"ccm:write", "integration:manage"} & set(user.permission_codes)):
        raise HTTPException(status_code=403, detail="Requires permission(s): ccm:write or integration:manage")
    return user


@router.post("/connectors/{cid}/ingest-token", response_model=IngestTokenIssued, status_code=201,
             summary="Issue (or replace) the connector's monitoring-feed token — shown once")
async def issue_ingest_token(cid: uuid.UUID, db: DbSession, user=Depends(_token_admin)) -> IngestTokenIssued:
    connector = await _load_connector(db, cid)
    rotated = bool(connector.ingest_token_hash)
    token = new_ingest_token(user.tenant_id, connector.id)
    connector.ingest_token_hash = ingest_token_hash(token)
    await db.flush()
    await audit_log.record(db, actor=user, action="ingest_token_issue", entity_type="connector", entity_id=cid,
                           summary=f"{'Replaced' if rotated else 'Issued'} the monitoring-feed token of connector "
                                   f"{connector.reference}", changes={"rotated": rotated})
    return IngestTokenIssued(
        connector_id=cid, token=token, endpoint=INGEST_ENDPOINT, header=f"Authorization: Bearer {token}",
        note=("Copy it now: only a fingerprint is kept, so it can't be shown again. "
              + ("The previous token stopped working. " if rotated else "")
              + 'POST {"control_reference": "A.8.5", "result": "passed", "observed_at": "2026-09-12T10:00:00+05:00", '
                '"summary": "…"} to the endpoint with this header.'),
    )


@router.delete("/connectors/{cid}/ingest-token", status_code=204, summary="Revoke the connector's feed token")
async def revoke_ingest_token(cid: uuid.UUID, db: DbSession, user=Depends(_token_admin)) -> None:
    connector = await _load_connector(db, cid)
    if not connector.ingest_token_hash:
        return
    connector.ingest_token_hash = ""
    await db.flush()
    await audit_log.record(db, actor=user, action="ingest_token_revoke", entity_type="connector", entity_id=cid,
                           summary=f"Revoked the monitoring-feed token of connector {connector.reference}")


@router.get("/connectors/{cid}/feed", response_model=ConnectorFeedRead, dependencies=[_READ],
            summary="The connector's feed: token state, last result received, recent results")
async def connector_feed(cid: uuid.UUID, db: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> ConnectorFeedRead:
    from app.models.audit import AuditLog

    connector = await _load_connector(db, cid)
    base = select(AuditLog).where(AuditLog.entity_type == "connector", AuditLog.entity_id == cid,
                                  AuditLog.action == "ingest")
    rows = (await db.scalars(base.order_by(AuditLog.created_at.desc()).limit(limit))).all()
    since = datetime.now(timezone.utc) - timedelta(days=30)
    recent_count = await db.scalar(select(func.count()).select_from(base.where(AuditLog.created_at >= since).subquery())) or 0

    def uid(value):
        try:
            return uuid.UUID(str(value)) if value else None
        except ValueError:
            return None

    return ConnectorFeedRead(
        connector_id=cid, has_token=connector.has_ingest_token, endpoint=INGEST_ENDPOINT,
        last_ingest_at=rows[0].created_at if rows else None, ingests_last_30_days=recent_count,
        recent=[
            IngestLogItem(
                at=r.created_at, result=str((r.changes or {}).get("result", "")),
                control_id=uid((r.changes or {}).get("control_id")),
                control_reference=str((r.changes or {}).get("control_reference", "")),
                summary=str((r.changes or {}).get("summary", "")),
                observed_at=str((r.changes or {}).get("observed_at", "")),
                evidence_id=uid((r.changes or {}).get("evidence_id")), run_id=uid((r.changes or {}).get("run_id")),
                test_reference=(r.changes or {}).get("test_reference") or None,
                alert_raised=bool((r.changes or {}).get("alert")),
            )
            for r in rows
        ],
    )


_INGEST_AUTH = HTTPBearer(
    auto_error=False, scheme_name="ConnectorFeedToken",
    description="The connector's feed token from POST /connectors/{id}/ingest-token (not a user session).",
)


def _ingest_denied() -> HTTPException:
    """One answer for every failure (no token, malformed, unknown organisation or
    connector, wrong or revoked token, disabled or archived connector, module off), so a
    caller learns nothing about which part was wrong."""
    return HTTPException(
        status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked connector feed token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def _ccm_enabled(db) -> bool:
    """Licensed on the installation and switched on for the organisation."""
    from app.models.settings import TenantSettings
    from app.services import modules

    if not modules.is_enabled("integrations_ccm"):
        return False
    chosen = await db.scalar(select(TenantSettings.enabled_modules))
    return not isinstance(chosen, list) or "integrations_ccm" in chosen


async def _feed_connector(db, token: str, tenant_id: uuid.UUID, connector_id: uuid.UUID) -> Connector:
    from app.models.tenant import Tenant

    tenant = await db.get(Tenant, tenant_id)
    connector = None
    if tenant is not None and tenant.is_active and await _ccm_enabled(db):
        connector = await db.scalar(
            select(Connector).where(Connector.id == connector_id, Connector.deleted.is_(False))
        )
    if (connector is None or connector.status == ConnectorStatus.disabled
            or not ingest_token_matches(token, connector.ingest_token_hash)):
        raise _ingest_denied()
    return connector


@dataclass(frozen=True)
class _IngestAuth:
    token: str
    tenant_id: uuid.UUID
    connector_id: uuid.UUID


async def _verified_ingest(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_INGEST_AUTH)] = None,
) -> _IngestAuth:
    """Authenticate the feed before the body is even read, so every failure is a 401."""
    token = creds.credentials if creds is not None and (creds.scheme or "").lower() == "bearer" else ""
    parsed = parse_ingest_token(token)
    if parsed is None:
        raise _ingest_denied()
    async with tenant_session(parsed[0]) as db:
        await _feed_connector(db, token, *parsed)
    # Phase 4: per-token rate limit (after authentication, so a stranger cannot spend a
    # real connector's allowance).
    decision = await ccm_rate_limit.feed_limiter().hit(parsed[1].hex)
    if not decision.allowed:
        raise too_many_requests(decision, "results from this connector")
    return _IngestAuth(token, *parsed)


async def _connector_audit(db, tenant_id, actor: str, **entry) -> None:
    """Audit a connector's write under its own name (no user is signed in)."""
    from app.models.audit import AuditLog
    from app.services import webhooks

    db.add(AuditLog(tenant_id=tenant_id, actor_id=None, actor_email=actor, **entry))
    await webhooks.dispatch(
        db, entity_type=entry["entity_type"], action=entry["action"],
        payload={"event": f"{entry['entity_type']}.{entry['action']}", "entity_type": entry["entity_type"],
                 "entity_id": str(entry["entity_id"]), "summary": entry["summary"], "actor": actor,
                 "changes": entry.get("changes", {})},
    )


async def _resolve_control(db, body: IngestBody):
    from app.models.control import Control

    if body.control_id is not None:
        control = await db.scalar(select(Control).where(Control.id == body.control_id, Control.deleted.is_(False)))
        if control is None:
            raise HTTPException(status_code=422, detail="control_id: no such control.")
        if body.control_reference and _norm(body.control_reference) != _norm(control.reference):
            raise HTTPException(status_code=422, detail=(
                f"control_reference {body.control_reference} is not the reference of control_id "
                f"({control.reference or 'no reference'}); send one of them."))
        return control
    ref = _norm(body.control_reference)
    found = (await db.scalars(
        select(Control).where(func.lower(func.trim(Control.reference)) == ref, Control.deleted.is_(False))
    )).all()
    if not found:
        raise HTTPException(status_code=422, detail=f"control_reference: no control has the reference {body.control_reference}.")
    if len(found) > 1:
        raise HTTPException(status_code=422, detail=(
            f"control_reference: {len(found)} controls share the reference {body.control_reference}; send control_id."))
    return found[0]


@router.post("/connectors/ingest", response_model=IngestResult, status_code=201,
             summary="Post a control-monitoring result from a connector (feed token, no user session)")
async def ingest_result(body: IngestBody, auth: Annotated[_IngestAuth, Depends(_verified_ingest)]) -> IngestResult:
    """Record one monitoring result as evidence on the control, as a run of the
    connector's test for it (when there is one), and — when it failed — as an alert.

    ``Authorization: Bearer <token>`` from ``POST /connectors/{id}/ingest-token``; the
    body is ``{"control_reference": "A.8.5" (or "control_id"), "result": "passed" |
    "failed" | "passed_with_exceptions", "observed_at": "2026-09-12T10:00:00+05:00",
    "summary": "…", "details": {…}, "pass_rate": 98.5, "test_reference": "CCM-003",
    "evidence": {"title": "…", "url": "…", "valid_until": "2026-12-31"}}``. A wrong or
    revoked token is a 401; an unknown control or a time in the future is a 422. The
    control's effectiveness is never changed here.
    """
    from app.models.enums import EvidenceStatus, EvidenceType
    from app.models.evidence import Evidence
    from app.services import incident_clock

    async with tenant_session(auth.tenant_id) as db:
        connector = await _feed_connector(db, auth.token, auth.tenant_id, auth.connector_id)
        actor = connector_actor(connector.name)
        tz = await incident_clock.tenant_zone(db, auth.tenant_id)
        observed = incident_clock.localize(body.observed_at, tz)
        now = incident_clock.now_utc()
        refusal = observed_refusal(observed, now)
        if refusal:
            raise HTTPException(status_code=422, detail=refusal)
        observed_day = incident_clock.local_date(observed, tz)
        observed_text = f"{incident_clock.local_text(observed, tz)} {getattr(tz, 'key', '')}".strip()
        if body.evidence and body.evidence.valid_until and body.evidence.valid_until < observed_day:
            raise HTTPException(status_code=422, detail="evidence.valid_until is before the result was observed.")
        control = await _resolve_control(db, body)
        control_ref = control.reference or ""
        tests = (await db.scalars(
            select(AutomatedControlTest).where(AutomatedControlTest.connector_id == connector.id,
                                               AutomatedControlTest.deleted.is_(False))
        )).all()
        try:
            match = match_test(tests, connector_id=connector.id, control_reference=control_ref,
                               test_reference=body.test_reference)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        result_words = body.result.replace("_", " ")
        pass_rate = run_pass_rate(body.result, body.pass_rate)
        rate_text = f", {pass_rate:g}% passed" if body.pass_rate is not None else ""
        ev = body.evidence
        link = (ev.url or ev.reference) if ev else ""
        evidence = Evidence(
            id=uuid.uuid4(), tenant_id=auth.tenant_id, control_id=control.id,
            title=(ev.title if ev else f"{connector.name}: {result_words} — {body.summary}")[:255],
            description=(
                f"Continuous monitoring result from connector {connector.reference} {connector.name}: "
                f"{result_words}{rate_text}, observed {observed_text}.\n\n{body.summary}"
                + (f"\n\nDetails:\n{json.dumps(body.details, indent=2, default=str)}" if body.details is not None else "")
            ),
            evidence_type=EvidenceType.link if link else EvidenceType.log,
            reference=(link or f"{connector.reference} monitoring feed")[:500],
            status=EvidenceStatus.valid, collected_at=observed_day,
            valid_until=ev.valid_until if ev else None,
        )
        test = match.test
        recorded = await ccm_runner.record_result(
            db, tenant_id=auth.tenant_id, connector=connector, control=control, test=test, result=body.result,
            observed_day=observed_day, today=incident_clock.local_date(now, tz), observed_text=observed_text,
            summary=body.summary, pass_rate=pass_rate, evidence=evidence,
            findings=("Passed with exceptions: " if body.result == "passed_with_exceptions" else "") + body.summary,
            evidence_ref=(link or f"Evidence: {evidence.title}"),
            run_fields={"source": "push", "started_at": observed},
        )
        run, alert_key = recorded.run, recorded.alert_key
        await db.flush()

        facts = {
            "result": body.result, "pass_rate": pass_rate, "observed_at": observed.isoformat(),
            "control_id": str(control.id), "control_reference": control_ref, "summary": body.summary[:500],
            "evidence_id": str(evidence.id), "run_id": str(run.id) if run else "",
            "test_reference": test.reference if test is not None else "", "alert": alert_key,
        }
        await _connector_audit(
            db, auth.tenant_id, actor, action="ingest", entity_type="connector", entity_id=connector.id,
            summary=f"Received a {result_words} result for control {control_ref or control.name}: {body.summary}"[:500],
            changes=facts,
        )
        await _connector_audit(
            db, auth.tenant_id, actor, action="create", entity_type="evidence", entity_id=evidence.id,
            summary=f"Collected evidence '{evidence.title}' for control {control_ref or control.name} "
                    f"from connector {connector.reference}"[:500],
            changes={"control_id": str(control.id), "collected_at": observed_day.isoformat(), "via": actor},
        )
        await _connector_audit(
            db, auth.tenant_id, actor, action="monitoring", entity_type="control", entity_id=control.id,
            summary=(f"Continuous monitoring ({connector.name}): {result_words} — {body.summary}. Evidence "
                     "recorded; effectiveness unchanged until a reviewed test")[:500],
            changes={k: facts[k] for k in ("result", "pass_rate", "observed_at", "evidence_id", "run_id", "alert")},
        )
        if run is not None:
            await _connector_audit(
                db, auth.tenant_id, actor, action="record_run", entity_type="automated_control_test",
                entity_id=test.id,
                summary=f"Recorded a {result_words} run of {test.reference} from connector {connector.reference}"[:500],
                changes={"run_id": str(run.id), "result": run.result.value, "pass_rate": pass_rate,
                         "run_date": observed_day.isoformat()},
            )
        # Phase 4: a failure opens (or updates) the test's issue and marks the control as
        # failing monitoring; a linked KRI gets the pass rate when that is its metric.
        fu = await ccm_runner.follow_up(
            db, tenant_id=auth.tenant_id, test=test, control=control, run=run, result=body.result, day=observed_day,
            actor=actor, summary=body.summary, exceptions=None, population=None, pass_rate=pass_rate,
            metric_value=None, was_failing=recorded.was_failing, advanced=recorded.advanced,
        )
        await db.flush()
        return IngestResult(
            connector_reference=connector.reference, control_id=control.id, control_reference=control_ref,
            evidence_id=evidence.id, run_id=run.id if run else None,
            test_reference=test.reference if test is not None else None,
            alert_raised=bool(alert_key), note=match.note,
            issue_reference=fu.issue_reference or None,
        )


# ======================================================= phase 4: executable CCM ===
def _param_read(p) -> dict:
    return {"name": p.name, "label": p.label, "kind": p.kind, "required": p.required, "default": p.default,
            "help": p.help, "options": list(p.options)}


@router.get("/ccm/check-types", response_model=list[CheckTypeRead], dependencies=[_READ],
            summary="The check types a monitoring test can run, with their parameter forms")
async def list_check_types() -> list[CheckTypeRead]:
    return [
        CheckTypeRead(key=s.key, label=s.label, group=s.group, description=s.description,
                      connector_types=list(s.connector_types), input=s.input,
                      params=[ParamSpecRead(**_param_read(p)) for p in s.params],
                      pass_criterion=s.pass_criterion, population=s.population)
        for s in ccm_checks.CHECKS.values()
    ]


@router.get("/ccm/connector-types", response_model=list[ConnectorKindRead], dependencies=[_READ],
            summary="How each connector type is reached: its settings and secret fields")
async def list_connector_kinds() -> list[ConnectorKindRead]:
    return [
        ConnectorKindRead(connector_type=t.value, kind=ccm_checks.kind_of(t.value).kind,
                          config_fields=[ParamSpecRead(**_param_read(p)) for p in ccm_checks.kind_of(t.value).config_fields],
                          secret_fields=[ParamSpecRead(**_param_read(p)) for p in ccm_checks.kind_of(t.value).secret_fields],
                          note=ccm_checks.kind_of(t.value).note)
        for t in ConnectorType
    ]


@router.put("/connectors/{cid}/secrets", response_model=ConnectorRead,
            summary="Set or clear the connector's secrets (write-only; never returned)")
async def put_connector_secrets(cid: uuid.UUID, body: SecretsWrite, db: DbSession,
                                user=Depends(_token_admin)) -> ConnectorRead:
    connector = await _load_connector(db, cid)
    _check_connector_settings(connector.connector_type.value, connector.config or {}, body.secrets, body.clear_secrets)
    changed = ccm_secrets.apply(connector, body.secrets, body.clear_secrets)
    await db.flush()
    if changed:
        await audit_log.record(db, actor=user, action="secrets", entity_type="connector", entity_id=cid,
                               summary=f"Changed the secrets of connector {connector.reference}: {', '.join(changed)}",
                               changes={"secrets": changed})
    return ConnectorRead.model_validate(await _load_connector(db, cid))


def _run_connection_test(connector_type: str, config: dict, secrets: dict, timeout: float) -> str:
    """Stubbable seam: reach the source (synchronous, run in a worker thread)."""
    from app.services.ccm_checks.http_json import private_urls_allowed

    return ccm_checks.test_connection(connector_type, config, secrets, timeout, allow_private_urls=private_urls_allowed())


@router.post("/connectors/{cid}/test-connection", response_model=ConnectionTestResult,
             summary="Reach the source with the saved settings and secrets")
async def test_connector_connection(cid: uuid.UUID, db: DbSession, user=Depends(_token_admin)) -> ConnectionTestResult:
    import asyncio

    connector = await _load_connector(db, cid)
    timeout = float(connector.timeout_seconds or 30)
    try:
        secrets_now = ccm_secrets.decrypt(connector.secrets_encrypted or "")
        message = await asyncio.wait_for(
            asyncio.to_thread(_run_connection_test, connector.connector_type.value, dict(connector.config or {}),
                              secrets_now, timeout),
            timeout=timeout + ccm_runner.TIMEOUT_GRACE_SECONDS,
        )
        ok = True
    except asyncio.TimeoutError:
        ok, message = False, f"No answer within {int(timeout)} seconds."
    except (ccm_checks.CheckError, ccm_secrets.SecretsUnreadable) as exc:
        ok, message = False, str(exc)
    except Exception as exc:  # noqa: BLE001 - say what went wrong, never a 500
        ok, message = False, f"{type(exc).__name__}: {exc}"
    now = datetime.now(timezone.utc)
    connector.last_test_at, connector.last_test_ok, connector.last_test_message = now, ok, message[:2000]
    if ok and connector.status in (ConnectorStatus.configured, ConnectorStatus.error):
        connector.status = ConnectorStatus.active
    await db.flush()
    await audit_log.record(db, actor=user, action="test_connection", entity_type="connector", entity_id=cid,
                           summary=f"Tested connector {connector.reference}: {'connected' if ok else 'failed'} — {message}"[:500],
                           changes={"ok": ok})
    return ConnectionTestResult(ok=ok, message=message, tested_at=now)


async def _run_detail(db, run: ControlTestRun) -> RunDetail:
    from app.models.evidence import Evidence
    from app.models.issue import Issue

    detail = RunDetail.model_validate(run)
    test = await db.scalar(select(AutomatedControlTest.reference).where(AutomatedControlTest.id == run.test_id))
    detail.test_reference = test or ""
    if run.evidence_id:
        detail.evidence_title = await db.scalar(select(Evidence.title).where(Evidence.id == run.evidence_id))
    if run.issue_id:
        detail.issue_reference = await db.scalar(select(Issue.reference).where(Issue.id == run.issue_id))
    return detail


async def _run_now(db, user, tid: uuid.UUID, upload=None) -> RunNowResult:
    test = await _load_test(db, tid)
    if not ccm_runner.is_executable(test):
        raise HTTPException(status_code=422, detail="This test is recorded by hand or pushed; it has no check to run.")
    try:
        report = await ccm_runner.execute_test(db, test, tenant_id=user.tenant_id,
                                               source="upload" if upload is not None else "run_now", upload=upload)
    except ccm_checks.CheckError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await audit_log.record(db, actor=user, action="run_now", entity_type="automated_control_test", entity_id=tid,
                           summary=f"Ran {test.reference} now"
                                   + (f" with file {upload.filename}" if upload is not None else "")
                                   + f": {report.result}"[:400],
                           changes={"run_id": str(report.run.id) if report.run else "", "result": report.result})
    return RunNowResult(result=report.result, message=report.message,
                        run=await _run_detail(db, report.run) if report.run is not None else None,
                        issue_reference=report.issue_reference, kri_note=report.kri_note)


@router.post("/automated-control-tests/{tid}/run", response_model=RunNowResult, dependencies=[_WRITE],
             summary="Run the test now against its connector (or the connector's import folder)")
async def run_test_now(tid: uuid.UUID, db: DbSession, user: CurrentUser) -> RunNowResult:
    return await _run_now(db, user, tid)


@router.post("/automated-control-tests/{tid}/run-upload", response_model=RunNowResult, dependencies=[_WRITE],
             summary="Run the test now on an uploaded file (scanner export, SIEM report, HR leavers list, CSV)")
async def run_test_with_file(tid: uuid.UUID, db: DbSession, user: CurrentUser,
                             file: UploadFile = File(...)) -> RunNowResult:
    from app.core.config import settings

    limit = settings.max_upload_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(status_code=413, detail=f"The file is larger than {settings.max_upload_mb} MB.")
    if not content:
        raise HTTPException(status_code=422, detail="The file is empty.")
    upload = ccm_checks.UploadedFile(filename=(file.filename or "upload")[:255], content=content)
    return await _run_now(db, user, tid, upload)


@router.get("/automated-control-tests/{tid}/runs", response_model=Page[RunRead], dependencies=[_READ],
            summary="The test's run history, newest first")
async def list_test_runs(tid: uuid.UUID, db: DbSession,
                         limit: Annotated[int, Query(ge=1, le=200)] = 50,
                         offset: Annotated[int, Query(ge=0)] = 0) -> Page[RunRead]:
    await _load_test(db, tid)
    stmt = select(ControlTestRun).where(ControlTestRun.test_id == tid)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await db.scalars(stmt.order_by(ControlTestRun.run_date.desc().nullslast(), ControlTestRun.created_at.desc())
                             .limit(limit).offset(offset))).all()
    return Page(items=[RunRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset)


async def _load_run(db, run_id) -> ControlTestRun:
    run = await db.scalar(select(ControlTestRun).where(ControlTestRun.id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/control-test-runs/{run_id}", response_model=RunDetail, dependencies=[_READ],
            summary="One run with its exception sample and details")
async def get_run(run_id: uuid.UUID, db: DbSession) -> RunDetail:
    return await _run_detail(db, await _load_run(db, run_id))


def exceptions_csv(rows: list[dict]) -> str:
    """The exception sample as CSV (columns in first-seen order). Pure."""
    import csv
    import io

    columns: list[str] = []
    for row in rows:
        for k in row:
            if k not in columns:
                columns.append(k)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns or ["exception"], extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # A cell starting with = + - @ would be a formula in a spreadsheet: quote it.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v)
                         for k, v in row.items()})
    return out.getvalue()


@router.get("/control-test-runs/{run_id}/exceptions.csv", dependencies=[_READ],
            summary="Download a run's exception sample as CSV")
async def download_run_exceptions(run_id: uuid.UUID, db: DbSession):
    from fastapi.responses import Response

    run = await _load_run(db, run_id)
    return Response(content=exceptions_csv(list(run.exceptions_sample or [])), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="run-{run_id}-exceptions.csv"'})


def monitoring_state(tests: list, now: datetime) -> str:
    """One word for a control's monitoring. Pure. Worst first among active tests."""
    active = [t for t in tests if t.status == CcmStatus.active]
    if not tests:
        return "not_monitored"
    if not active:
        return "paused"
    results = {getattr(t.last_result, "value", t.last_result) for t in active}
    if "failed" in results:
        return "failing"
    if "error" in results:
        return "error"
    if any(ccm_runner.is_overdue(t, now) for t in active):
        return "overdue"
    if results <= {"not_run"}:
        return "not_run"
    return "passing"


@router.get("/ccm/controls/{control_id}/monitoring", response_model=ControlMonitoringRead, dependencies=[_READ],
            summary="Continuous monitoring of one control: state, failing since, recent pass rate, tests")
async def control_monitoring(control_id: uuid.UUID, db: DbSession) -> ControlMonitoringRead:
    from app.models.control import Control
    from app.models.issue import Issue

    control = await db.scalar(select(Control).where(Control.id == control_id, Control.deleted.is_(False)))
    if control is None:
        raise HTTPException(status_code=404, detail="Control not found")
    ref = _norm(control.reference)
    cond = AutomatedControlTest.control_id == control_id
    if ref:
        cond = cond | ((AutomatedControlTest.control_id.is_(None))
                       & (func.lower(func.trim(AutomatedControlTest.control_ref)) == ref))
    tests = (await db.scalars(select(AutomatedControlTest).where(cond, AutomatedControlTest.deleted.is_(False))
                              .order_by(AutomatedControlTest.reference))).all()
    connector_ids = {t.connector_id for t in tests if t.connector_id}
    names = {}
    if connector_ids:
        names = {c.id: f"{c.reference} {c.name}".strip()
                 for c in (await db.scalars(select(Connector).where(Connector.id.in_(connector_ids)))).all()}
    issue_ids = {t.issue_id for t in tests if t.issue_id}
    issues = {}
    if issue_ids:
        issues = {i.id: i.reference for i in (await db.scalars(select(Issue).where(Issue.id.in_(issue_ids)))).all()}
    now = datetime.now(timezone.utc)
    reads = []
    all_runs = []
    for t in tests:
        n, rate = ccm_runner.recent_pass_rate(t.runs)
        if t.status == CcmStatus.active:
            all_runs.extend(t.runs)
        latest = t.recent_runs[0] if t.runs else None
        reads.append(MonitoringTestRead(
            id=t.id, reference=t.reference, name=t.name, check_type=t.check_type or "manual",
            check_label=ccm_checks.CHECKS.get(t.check_type or "manual", ccm_checks.MANUAL).label,
            status=t.status.value, frequency=t.frequency.value, connector_name=names.get(t.connector_id, ""),
            last_result=t.last_result.value, last_run=t.last_run, last_run_at=t.last_run_at,
            failing_since=t.failing_since, last_error=t.last_error or "", recent_runs=n, recent_pass_rate=rate,
            overdue=ccm_runner.is_overdue(t, now), issue_id=t.issue_id, issue_reference=issues.get(t.issue_id),
            latest_run_id=latest.id if latest else None, latest_evidence_id=latest.evidence_id if latest else None,
        ))
    n, rate = ccm_runner.recent_pass_rate(all_runs)
    return ControlMonitoringRead(
        control_id=control_id, state=monitoring_state(list(tests), now),
        failing_since=control.monitoring_failing_since, recent_runs=n, recent_pass_rate=rate, tests=reads,
    )
