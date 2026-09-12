"""Approve or reject from an e-mail (product review F-15, plan §3.2), and the per-person
digest that carries the links.

No database: pure rules directly; the public endpoints with a fake tenant session and
stubbed loaders; the digest with a fake session.

Pinned here:

1. **The token** — ``<tenant>.<id>.<secret>``, 32 random bytes, only its SHA-256 stored,
   compared in constant time, 72-hour expiry, bound to one user, action and request.
2. **A GET never decides**; the POST confirms: unused, unexpired, active user who may
   still decide (permission, not the maker, not voted), claimed atomically, then the
   in-app ``decide_approval`` runs as that user and ``decide_by_email`` is audited.
3. **Who gets links** — the people an approval waits on who may decide it.
4. **Immediate e-mail** — new pending approvals are queued by a mapper hook and sent
   after commit only when SMTP is configured; a rollback forgets them.
5. **Digests** — each person gets only their own + role + everyone's new alerts, once
   per condition, with deep links and decision links; nothing new → no e-mail; a sent
   digest is the marker for the next.
"""
from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.api.v1 import approvals as approvals_api
from app.core.config import settings
from app.models.approval import ApprovalAction, ApprovalRequest
from app.models.enums import ApprovalStatus, NotificationCategory
from app.models.notification import ActionToken
from app.schemas.approval import ApprovalDecision
from app.schemas.my_work import EmailActionConfirm
from app.services import action_tokens as at
from app.services import audit as audit_service
from app.services import email as email_service
from app.services import notifications as ns
from app.services import scheduler
from app.services.notifications import Directory, DirectoryUser

NOW = datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)
TENANT = uuid.uuid4()
ME, OTHER, MAKER, IDLE = (uuid.uuid4() for _ in range(4))


def _user(uid=ME, *, active=True, perms=("workflow:approve", "workflow:read"), email="me@bank.pk"):
    return SimpleNamespace(id=uid, tenant_id=TENANT, email=email, full_name="Me Myself", is_active=active,
                           permission_codes=list(perms))


def _approval(**kw) -> ApprovalRequest:
    base = dict(id=uuid.uuid4(), tenant_id=TENANT, reference="APR-003", title="Accept R-117 <card fraud>",
                description="Residual 12 within appetite", approver="", requested_by=MAKER,
                requested_by_email="maker@bank.pk", status=ApprovalStatus.pending, required_approvals=1,
                entity_label="R-117 Card fraud", entity_type="risk", due_date=None)
    base.update(kw)
    ap = ApprovalRequest(**base)
    ap.actions = []
    return ap


def _row(token: str, **kw) -> ActionToken:
    tenant_id, token_id = at.parse_token(token)
    base = dict(id=token_id, tenant_id=tenant_id, token_hash=at.token_hash(token), user_id=ME,
                action=at.ACTION_DECIDE, entity_type=at.ENTITY_APPROVAL, entity_id=uuid.uuid4(),
                expires_at=NOW + at.TOKEN_TTL, used_at=None)
    base.update(kw)
    return ActionToken(**base)


# ================================================================= the token ===
def test_a_token_carries_its_tenant_and_row_and_a_long_secret():
    token_id = uuid.uuid4()
    token = at.new_token(TENANT, token_id)
    tenant_hex, id_hex, secret = token.split(".")
    assert (tenant_hex, id_hex) == (TENANT.hex, token_id.hex)
    assert len(secret) >= 43  # 32 bytes, url-safe base64
    assert at.parse_token(token) == (TENANT, token_id)
    assert at.new_token(TENANT, token_id) != token  # fresh randomness every time


@pytest.mark.parametrize("bad", ["", None, "abc", "a.b", f"{TENANT.hex}.{uuid.uuid4().hex}.short",
                                 f"nothex.{uuid.uuid4().hex}.{'x' * 43}", f"{TENANT.hex}.{'z' * 32}.{'x' * 43}",
                                 f"{TENANT.hex}.{uuid.uuid4().hex}.{'x' * 43}.extra"])
def test_malformed_tokens_parse_to_nothing(bad):
    assert at.parse_token(bad) is None


def test_only_the_hash_is_kept_and_it_is_compared_in_constant_time(monkeypatch):
    token = at.new_token(TENANT, uuid.uuid4())
    assert at.token_hash(token) == hashlib.sha256(token.encode()).hexdigest()
    calls = []
    real = at.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(at.hmac, "compare_digest", spy)
    assert at.token_matches(token, at.token_hash(token))
    assert not at.token_matches(token + "x", at.token_hash(token))
    assert not at.token_matches("", at.token_hash(token)) and not at.token_matches(token, "")
    assert len(calls) == 2


async def test_issuing_stores_a_bound_expiring_row_never_the_token():
    added = []
    db = SimpleNamespace(add=added.append)
    approval_id = uuid.uuid4()
    token = await at.issue_token(db, tenant_id=TENANT, user_id=ME, approval_id=approval_id, now=NOW)
    (row,) = added
    assert row.token_hash == at.token_hash(token) and token not in row.token_hash
    assert (row.user_id, row.action, row.entity_type, row.entity_id) == (ME, "approval.decide", "approval", approval_id)
    assert row.expires_at == NOW + timedelta(hours=72) and row.used_at is None
    assert at.parse_token(token) == (TENANT, row.id)


def test_action_urls_open_the_confirmation_page(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://grc.bank.pk/")
    assert at.action_url("T", "approve") == "https://grc.bank.pk/act?token=T&decision=approve"
    assert at.action_url("T", "delete") == "https://grc.bank.pk/act?token=T"


def test_claiming_is_one_atomic_update():
    stmt_holder = {}

    class DB:
        async def scalar(self, stmt):
            stmt_holder["sql"] = str(stmt.compile(dialect=postgresql.dialect()))
            return None

    import asyncio

    assert asyncio.run(at.claim(DB(), SimpleNamespace(id=uuid.uuid4()), NOW)) is False
    sql = stmt_holder["sql"]
    assert sql.startswith("UPDATE action_tokens SET used_at=") and "used_at IS NULL" in sql and "RETURNING" in sql


# ============================================================ token state ===
def test_token_states(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    token = at.new_token(TENANT, uuid.uuid4())
    ap = _approval()
    ready = _row(token, entity_id=ap.id)
    assert at.token_state(ready, _user(), ap, NOW) == (at.READY, "")
    assert at.token_state(_row(token, used_at=NOW), _user(), ap, NOW)[0] == at.USED
    assert at.token_state(_row(token, expires_at=NOW), _user(), ap, NOW)[0] == at.EXPIRED
    assert at.token_state(ready, _user(active=False), ap, NOW)[0] == at.NOT_ELIGIBLE
    assert at.token_state(ready, None, ap, NOW)[0] == at.NOT_ELIGIBLE
    assert at.token_state(ready, _user(), None, NOW)[0] == at.NOT_ELIGIBLE
    assert at.token_state(ready, _user(perms=()), ap, NOW) == (
        at.NOT_ELIGIBLE, "Deciding approval requests needs the workflow:approve permission.")
    assert at.token_state(ready, _user(MAKER, email="maker@bank.pk"), ap, NOW)[0] == at.NOT_ELIGIBLE
    voted = _approval()
    voted.actions = [ApprovalAction(actor_id=ME, action="approve")]
    assert "already recorded" in at.token_state(ready, _user(), voted, NOW)[1]
    decided = _approval(status=ApprovalStatus.rejected)
    assert at.token_state(ready, _user(), decided, NOW) == (at.DECIDED, "This request is already rejected.")


# =========================================================== who gets links ===
def _directory():
    return Directory(
        users={
            ME: DirectoryUser(ME, "me@bank.pk", "Me Myself", True, ("Risk Approver",)),
            OTHER: DirectoryUser(OTHER, "other@bank.pk", "Omar Other", True, ("Risk Approver",)),
            MAKER: DirectoryUser(MAKER, "maker@bank.pk", "Mona Maker", True, ("Risk Approver", "Risk Manager")),
            IDLE: DirectoryUser(IDLE, "idle@bank.pk", "Idle", False, ("Risk Approver",)),
        },
        role_permissions={"Risk Approver": frozenset({"workflow:approve"}), "Risk Manager": frozenset()},
    )


def test_links_go_to_those_who_may_decide(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval()
    assert at.decision_makers(ap, _directory()) == [ME, OTHER]  # not the maker, not inactive
    ap.actions = [ApprovalAction(actor_id=OTHER, action="approve")]
    assert at.decision_makers(ap, _directory()) == [ME]
    assert at.decision_makers(_approval(approver="me@bank.pk"), _directory()) == [ME]


# ================================================================ endpoints ===
@pytest.fixture
def endpoint_env(monkeypatch):
    opened = []
    db = SimpleNamespace(
        execute=None,
    )

    class _Locale:
        def first(self):
            return ("YYYY-MM-DD", "Asia/Karachi")

    async def execute(stmt, *a, **k):
        return _Locale()

    db.execute = execute

    @asynccontextmanager
    async def session(tenant_id):
        opened.append(tenant_id)
        yield db

    calls = SimpleNamespace(decide=[], claim=[], audit=[], opened=opened, db=db, claim_result=True)

    async def decide(approval_id, body, db_, user):
        calls.decide.append((approval_id, body, user))
        return SimpleNamespace(reference="APR-003", status=ApprovalStatus.approved if body.approve else ApprovalStatus.rejected,
                               approvals_received=1, required_approvals=1)

    async def claim(db_, row, now):
        calls.claim.append(row.id)
        return calls.claim_result

    async def record(db_, **kw):
        calls.audit.append(kw)

    async def load(db_, approval_id):
        return calls.approval

    monkeypatch.setattr(approvals_api, "tenant_session", session)
    monkeypatch.setattr(approvals_api, "decide_approval", decide)
    monkeypatch.setattr(approvals_api, "_load", load)
    monkeypatch.setattr(at, "claim", claim)
    monkeypatch.setattr(audit_service, "record", record)
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    return calls


def _open_with(monkeypatch, calls, token, row=None, user=None, approval=None):
    calls.approval = approval or _approval()
    row = row or _row(token, entity_id=calls.approval.id)
    ctx = at.TokenContext(row=row, user=user or _user(), approval=calls.approval, organisation="Acme Bank")

    async def open_token(db, t):
        return ctx if t == token else None

    monkeypatch.setattr(at, "open_token", open_token)
    return ctx


async def test_a_malformed_link_is_refused_before_any_session_opens(endpoint_env):
    for call in (approvals_api.preview_email_action("nonsense"),
                 approvals_api.confirm_email_action("nonsense", EmailActionConfirm(decision="approve"))):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 404
    assert endpoint_env.opened == []


async def test_the_preview_says_what_would_be_decided_and_decides_nothing(monkeypatch, endpoint_env):
    token = at.new_token(TENANT, uuid.uuid4())
    _open_with(monkeypatch, endpoint_env, token)
    out = await approvals_api.preview_email_action(token)
    assert endpoint_env.opened == [TENANT]  # the tenant comes from the token
    assert out.state == "ready" and out.organisation == "Acme Bank" and out.user_name == "Me Myself"
    assert out.approval.reference == "APR-003" and out.approval.title == "Accept R-117 <card fraud>"
    assert out.date_format == "YYYY-MM-DD"
    assert endpoint_env.decide == [] and endpoint_env.claim == [] and endpoint_env.audit == []


async def test_an_unknown_token_is_one_answer(monkeypatch, endpoint_env):
    token = at.new_token(TENANT, uuid.uuid4())
    other = at.new_token(TENANT, uuid.uuid4())
    _open_with(monkeypatch, endpoint_env, other)
    with pytest.raises(HTTPException) as exc:
        await approvals_api.preview_email_action(token)
    assert exc.value.status_code == 404


async def test_confirming_runs_the_in_app_decision_as_the_tokens_user(monkeypatch, endpoint_env):
    token = at.new_token(TENANT, uuid.uuid4())
    ctx = _open_with(monkeypatch, endpoint_env, token)
    out = await approvals_api.confirm_email_action(token, EmailActionConfirm(decision="approve"))
    assert endpoint_env.claim == [ctx.row.id]
    ((approval_id, body, user),) = endpoint_env.decide
    assert approval_id == ctx.approval.id and user is ctx.user
    assert body == ApprovalDecision(approve=True, comment="")
    (entry,) = endpoint_env.audit
    assert entry["action"] == "decide_by_email" and entry["actor"] is ctx.user
    assert entry["summary"] == "Decided by email: approved approval APR-003"
    assert entry["changes"]["token_id"] == str(ctx.row.id) and token not in str(entry)
    assert out.decision == "approve" and "You approved APR-003" in out.message


@pytest.mark.parametrize("case,status", [("used", 410), ("expired", 410), ("maker", 403), ("decided", 409)])
async def test_a_link_that_cant_be_used_is_refused_without_deciding(monkeypatch, endpoint_env, case, status):
    token = at.new_token(TENANT, uuid.uuid4())
    kwargs = {}
    if case == "used":
        kwargs["row"] = _row(token, used_at=NOW - timedelta(hours=1))
    elif case == "expired":
        kwargs["row"] = _row(token, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    elif case == "maker":
        kwargs["user"] = _user(MAKER, email="maker@bank.pk")
    elif case == "decided":
        kwargs["approval"] = _approval(status=ApprovalStatus.approved)
    _open_with(monkeypatch, endpoint_env, token, **kwargs)
    with pytest.raises(HTTPException) as exc:
        await approvals_api.confirm_email_action(token, EmailActionConfirm(decision="reject", comment="No"))
    assert exc.value.status_code == status
    assert endpoint_env.decide == [] and endpoint_env.claim == []


async def test_losing_the_claim_race_is_refused(monkeypatch, endpoint_env):
    token = at.new_token(TENANT, uuid.uuid4())
    _open_with(monkeypatch, endpoint_env, token)
    endpoint_env.claim_result = False
    with pytest.raises(HTTPException) as exc:
        await approvals_api.confirm_email_action(token, EmailActionConfirm(decision="approve"))
    assert exc.value.status_code == 410 and endpoint_env.decide == []


async def test_a_refused_decision_propagates_so_the_claim_rolls_back(monkeypatch, endpoint_env):
    token = at.new_token(TENANT, uuid.uuid4())
    _open_with(monkeypatch, endpoint_env, token)

    async def refuse(*a, **k):
        raise HTTPException(status_code=422, detail="A reason is required to reject an approval request.")

    monkeypatch.setattr(approvals_api, "decide_approval", refuse)
    with pytest.raises(HTTPException) as exc:
        await approvals_api.confirm_email_action(token, EmailActionConfirm(decision="reject"))
    assert exc.value.status_code == 422 and endpoint_env.audit == []


async def test_open_token_checks_tenant_hash_and_binding():
    from app.models.tenant import Tenant

    token = at.new_token(TENANT, uuid.uuid4())
    good = _row(token)

    def make_db(row, tenant_active=True):
        tenant = Tenant(id=TENANT, name="Acme Bank", slug="acme", is_active=tenant_active)
        user = _user()

        class DB:
            async def get(self, model, key):
                return {TENANT: tenant, good.id: row, ME: user}.get(key)

            async def scalar(self, stmt):
                return _approval(id=row.entity_id) if row is not None else None

        return DB()

    ctx = await at.open_token(make_db(good), token)
    assert ctx is not None and ctx.organisation == "Acme Bank" and ctx.approval.id == good.entity_id
    assert await at.open_token(make_db(good, tenant_active=False), token) is None
    assert await at.open_token(make_db(_row(token, token_hash=at.token_hash("other"))), token) is None
    assert await at.open_token(make_db(_row(token, action="policy.acknowledge")), token) is None
    assert await at.open_token(make_db(None), token) is None
    assert await at.open_token(make_db(good), "garbage") is None


# ================================================================= the hooks ===
def test_new_pending_approvals_are_queued_and_sent_after_commit_only_with_smtp(monkeypatch):
    session = SimpleNamespace(info={})
    monkeypatch.setattr(at, "object_session", lambda target: session)
    ap = _approval()
    at._queue_new_approval(None, None, ap)
    at._queue_new_approval(None, None, _approval(status=ApprovalStatus.cancelled))
    assert at.queued_items(session.info) == [(TENANT, ap.id)]

    monkeypatch.setattr(email_service, "is_configured", lambda: False)
    at._send_after_commit(session)
    assert session.info == {}  # dropped: nobody would receive it

    at._queue_new_approval(None, None, ap)
    at._forget_after_rollback(session)
    assert session.info == {}


async def test_after_commit_schedules_the_decision_emails(monkeypatch):
    import asyncio

    session = SimpleNamespace(info={})
    monkeypatch.setattr(at, "object_session", lambda target: session)
    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    sent = []

    async def send(items):
        sent.append(items)
        return len(items)

    monkeypatch.setattr(at, "send_decision_requests", send)
    ap = _approval()
    at._queue_new_approval(None, None, ap)
    at._send_after_commit(session)
    await asyncio.sleep(0)
    await asyncio.gather(*list(at._TASKS))
    assert sent == [[(TENANT, ap.id)]]


def test_hooks_are_installed_once():
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    at.install_hooks()
    at.install_hooks()
    assert event.contains(ApprovalRequest, "after_insert", at._queue_new_approval)
    assert event.contains(Session, "after_commit", at._send_after_commit)


async def test_decision_request_emails_mint_one_token_per_decider(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval()
    added, mails = [], []

    class DB:
        async def scalar(self, stmt):
            return ap

        async def get(self, model, key):
            return SimpleNamespace(name="Acme Bank")

        def add(self, obj):
            added.append(obj)

        async def flush(self):
            pass

    async def directory(db):
        return _directory()

    async def send(to, subject, html, text=None):
        mails.append((to, subject, text))
        return True

    monkeypatch.setattr(ns, "load_directory", directory)
    monkeypatch.setattr(email_service, "send_email", send)
    monkeypatch.setattr(email_service, "is_configured", lambda: False)
    assert await at.email_decision_request(DB(), TENANT, ap.id) == 0 and added == []

    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    assert await at.email_decision_request(DB(), TENANT, ap.id) == 2
    assert {r.user_id for r in added} == {ME, OTHER}
    assert [m[0] for m in mails] == [["me@bank.pk"], ["other@bank.pk"]]
    assert mails[0][1] == "[Acme Bank] Decision needed: APR-003 Accept R-117 <card fraud>"
    assert "/act?token=" in mails[0][2] and "decision=approve" in mails[0][2] and "decision=reject" in mails[0][2]


# ================================================================= rendering ===
def test_the_decision_email_escapes_and_carries_both_links(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://grc.bank.pk")
    subject, html, text = email_service.render_decision_request(
        "Acme <Bank>", _approval(), recipient_name="Me", approve_url="https://grc.bank.pk/act?token=T&decision=approve",
        reject_url="https://grc.bank.pk/act?token=T&decision=reject", open_url="https://grc.bank.pk/approvals?id=1",
    )
    assert "<card fraud>" not in html and "&lt;card fraud&gt;" in html and "Acme &lt;Bank&gt;" in html
    assert "act?token=T&amp;decision=approve" in html and "decision=reject" in html
    assert "Approve: https://grc.bank.pk/act?token=T&decision=approve" in text


def test_the_digest_links_every_alert_and_offers_decisions(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://grc.bank.pk")
    aid = uuid.uuid4()
    alerts = [
        SimpleNamespace(title="Approval pending: APR-003", body="Accept R-117", category=NotificationCategory.info,
                        link=f"/approvals?id={aid}", entity_id=aid),
        SimpleNamespace(title="Risk review overdue: R-9 <x>", body="due", category="warning",
                        link="/risks?id=9", entity_id=uuid.uuid4()),
    ]
    links = {aid: email_service.DecisionLinks(approve="https://a", reject="https://r")}
    subject, html, text = email_service.render_user_digest("Acme", alerts, recipient_name="Me", decisions=links, escalations=1)
    assert subject == "[Acme] 2 new GRC alerts, including 1 turnaround-time escalation"
    assert f'href="https://grc.bank.pk/approvals?id={aid}"' in html and 'href="https://grc.bank.pk/risks?id=9"' in html
    assert html.count("https://a") == 1 and "&lt;x&gt;" in html
    assert "Approve: https://a" in text and "Open: https://grc.bank.pk/risks?id=9" in text
    assert "/my-work" in html
    old_subject, old_html = email_service.render_digest("Acme", alerts[1:])
    assert old_subject == "[Acme] 1 new GRC alert" and "Approve" not in old_html.split("<p style=\"color:#888")[0]


# =================================================================== digests ===
def _n(key, *, user_id=None, role_name="", created=NOW, category=NotificationCategory.warning, entity_id=None,
       entity_type="risk"):
    return SimpleNamespace(id=uuid.uuid4(), dedup_key=key, user_id=user_id, role_name=role_name,
                           created_at=created, category=category, title=key, body="", link="/risks",
                           entity_id=entity_id, entity_type=entity_type)


def test_a_digest_holds_only_what_is_new_and_for_me_once_per_condition():
    since = NOW - timedelta(minutes=15)
    mine = _n(f"risk-review:1@u:{ME}")
    theirs = _n(f"risk-review:2@u:{OTHER}", user_id=OTHER)
    everyone = _n("risk-review:3", category=NotificationCategory.critical)
    role = _n("tat-breach:risk:4@r:CRO", role_name="CRO")
    same_as_role = _n(f"tat-breach:risk:4@u:{ME}", user_id=ME)
    old = _n("risk-review:5", created=since - timedelta(minutes=1))
    mine.user_id = ME
    rows = [mine, theirs, everyone, role, same_as_role, old]
    out = scheduler.digest_for(rows, user_id=ME, role_names=["CRO"], since=since)
    assert [n.dedup_key for n in out] == ["risk-review:3", f"risk-review:1@u:{ME}", f"tat-breach:risk:4@u:{ME}"]
    assert scheduler.escalations_in(out, ME) == 0  # reached as the owner, not via the role
    only_role = scheduler.digest_for([role], user_id=OTHER, role_names=["CRO"], since=since)
    assert scheduler.escalations_in(only_role, OTHER) == 1


def test_where_a_digest_starts():
    last = NOW - timedelta(hours=3)
    assert scheduler.digest_since(last, NOW, 15) == last
    assert scheduler.digest_since(None, NOW, 15) == NOW - timedelta(minutes=30)
    assert scheduler.digest_since(NOW - timedelta(days=30), NOW, 15) == NOW - scheduler.MAX_DIGEST_LOOKBACK


async def test_each_person_is_mailed_their_own_digest_with_decision_links(monkeypatch):
    monkeypatch.setattr(settings, "enforce_segregation_of_duties", True)
    ap = _approval()
    rows = [
        _n(f"approval-pending:{ap.id}@r:Risk Approver", role_name="Risk Approver", entity_id=ap.id,
           entity_type="approval"),
        _n(f"risk-review:1@u:{OTHER}", user_id=OTHER),
    ]
    results = [[(ME, NOW - timedelta(hours=1))], rows, [ap]]
    added, mails, markers = [], [], []

    class _Rows:
        def __init__(self, r):
            self.r = r

        def all(self):
            return self.r

    class DB:
        async def execute(self, stmt, *a, **k):
            return _Rows(results.pop(0))

        async def scalars(self, stmt, *a, **k):
            return _Rows(results.pop(0))

        def add(self, obj):
            added.append(obj)

        async def flush(self):
            pass

    async def directory(db):
        return _directory()

    async def send(to, subject, html, text=None):
        mails.append((to[0], subject, html))
        return True

    async def record_system(db, **kw):
        markers.append(kw)

    monkeypatch.setattr(ns, "load_directory", directory)
    monkeypatch.setattr(email_service, "send_email", send)
    monkeypatch.setattr(email_service, "is_configured", lambda: True)
    monkeypatch.setattr(audit_service, "record_system", record_system)
    sent = await scheduler.send_digests(DB(), TENANT, "Acme", now=NOW)

    by_person = {m[0]: m for m in mails}
    # Me and Other are Risk Approvers: both see the approval; only Other has the review.
    # The maker sees the approval (role member) but gets no decision link.
    assert set(by_person) == {"me@bank.pk", "other@bank.pk", "maker@bank.pk"} and sent == 3
    assert "decision=approve" in by_person["me@bank.pk"][2]
    assert "decision=approve" not in by_person["maker@bank.pk"][2]
    assert "risk-review:1" in by_person["other@bank.pk"][2] and "risk-review:1" not in by_person["me@bank.pk"][2]
    assert {t.user_id for t in added} == {ME, OTHER}
    assert {m["entity_id"] for m in markers} == {ME, OTHER, MAKER}
    assert all(m["action"] == "digest" and m["entity_type"] == "notification_digest" for m in markers)


async def test_nothing_new_means_no_email(monkeypatch):
    results = [[], []]
    mails = []

    class _Rows:
        def __init__(self, r):
            self.r = r

        def all(self):
            return self.r

    class DB:
        async def execute(self, stmt, *a, **k):
            return _Rows(results.pop(0))

        async def scalars(self, stmt, *a, **k):
            return _Rows(results.pop(0))

    async def directory(db):
        return _directory()

    async def send(*a, **k):
        mails.append(a)
        return True

    monkeypatch.setattr(ns, "load_directory", directory)
    monkeypatch.setattr(email_service, "send_email", send)
    assert await scheduler.send_digests(DB(), TENANT, "Acme", now=NOW) == 0 and mails == []


def test_stale_tokens_are_purged_a_month_after_expiry():
    captured = {}

    class DB:
        async def execute(self, stmt):
            captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))
            return SimpleNamespace(rowcount=3)

    import asyncio

    assert asyncio.run(at.purge_stale(DB(), NOW)) == 3
    assert captured["sql"].startswith("DELETE FROM action_tokens WHERE action_tokens.expires_at <")


@pytest.mark.asyncio
async def test_switching_email_actions_off_kills_every_link(monkeypatch):
    # A bank whose policy needs 2FA for every approval sets EMAIL_ACTIONS_ENABLED=false.
    from app.core.config import settings
    from app.services import action_tokens as at

    monkeypatch.setattr(settings, "email_actions_enabled", False, raising=False)
    assert at.enabled() is False
    token = at.new_token(uuid.uuid4(), uuid.uuid4())
    assert await at.open_token(object(), token) is None  # never touches the database
