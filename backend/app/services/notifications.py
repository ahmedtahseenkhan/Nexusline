"""Cross-module alert scanner — computes due/overdue/gap alerts across every module
and reconciles them into the ``notifications`` table (dedup + auto-resolve).

Three rules keep the feed readable once real data is in it:

* **An alert goes to the person who has to act.** Every alert names its recipients:
  the record's accountable person where a user is on file (a risk's owner, a control's
  owner and — for tests — its operator, an issue action's owner, an incident's assignee,
  a KRI's owner and escalation target, a third party's relationship owner, an approval's
  named approver …), or a role (a KRI escalation to "CRO", the approvers of an approval
  addressed to nobody in particular, the SLA escalation role of a missed turnaround
  time). One notification row is stored per recipient, and the recipient is part of the
  row's ``dedup_key`` (``risk-review:<id>@u:<user>``, ``kri-breach:<id>@r:CRO``). An alert
  whose record names nobody we can resolve stays addressed to everyone (no user, no
  role), exactly as before, so nothing is silently lost.
* **Housekeeping is grouped, decisions never are.** When one low-urgency family (tests,
  maintenance, scheduled reviews, training) raises more than :data:`GROUP_THRESHOLD`
  alerts *for one recipient*, they collapse into one row for that recipient ("36
  controls have tests overdue") with a handful of examples and a link to the list. The
  families in :data:`NEVER_GROUPED` (tolerance breaches, turnaround-time breaches,
  approvals, attestations, regulator and incident deadlines, and the like) always stay
  one row per record, so they can't be buried.
* **An alert says what is true now, and opens the record.** ``refresh`` rewrites the
  text of an alert that already exists when the condition behind it has changed ("R-117
  scores 20", not the 15 it scored when first raised). Every individual alert links to
  the record itself (``/risks?id=<id>``), so the bell and the email digest open the
  record's drawer rather than the whole register.

Who sees a row (:func:`visible_clause`): the user it names, the members of the role it
names, or — when it names neither — everyone in the organisation. A row may name both a
person and a role (a KRI escalation to "Jane Doe and the CRO role" is one event).
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.control import UNTESTABLE_CONTROL_STATUSES
from app.models.access_review import AccessReview
from app.models.approval import ApprovalRequest
from app.models.attestation import Attestation
from app.models.awareness import AwarenessProgram
from app.models.continuity import ContinuityPlan
from app.models.control import Control
from app.models.enums import (
    AcceptanceStatus,
    AccessReviewStatus,
    ApprovalStatus,
    DpiaStatus,
    ExceptionStatus,
    KriDirection,
    KriStatus,
    NotificationCategory,
    ProjectStatus,
    RcsaStatus,
    SarStatus,
    VendorStatus,
)
from app.models.exception import ExceptionRecord
from app.models.goal import Goal
from app.models.internal_audit import AuditEngagement, AuditFinding
from app.models.issue import ActionStatus, Issue, IssueAction, IssueDueDateChange, IssueStatus2
from app.models.shariah import ShariahFinding, ShariahReview
from app.models.operational_risk import KeyRiskIndicator, RcsaAssessment
from app.models.incident import Incident, RegulatoryReport
from app.models.aml import ScreeningCase, SuspiciousActivityReport
from app.models.enums import RegulatoryReportStatus, ScreeningCaseStatus
from app.models.enums import AuditEngagementStatus, AuditFindingStatus, ShariahFindingStatus
from app.models.notification import EVENT_PREFIX, Notification
from app.models.policy import Policy
from app.models.privacy import ProcessingActivity
from app.models.project import Project
from app.models.risk import Risk, RiskAcceptance, RiskTreatmentAction
from app.models.vendor import CERT_EXPIRY_WARNING_DAYS, Vendor, VendorCertification, certification_expiry_state
from app.services.risk_acceptance import EXPIRY_WARNING_DAYS
from app.services.risk_scoring import effective_score
from app.services.risk_settings import get_or_create_settings, load_appetite_book

_W = NotificationCategory.warning
_C = NotificationCategory.critical
_I = NotificationCategory.info

# EVENT_PREFIX is defined on the model and imported above; callers that already reach
# for it through this module keep working.


#: Entity types whose own record carries the review schedule (``review_frequency`` /
#: ``next_review_date``). Attesting one of these moves that schedule (see
#: ``api.v1.attestations``), and the native review sweep below raises the overdue alert,
#: so the attestation sweep must not raise a second one for the same date.
NATIVE_REVIEW_ENTITY_TYPES: frozenset[str] = frozenset({"risk", "policy", "vendor"})

#: More than this many alerts in one groupable family (for one recipient) collapse into
#: a single row.
GROUP_THRESHOLD = 5
#: Examples named in a grouped alert's body.
GROUP_EXAMPLES = 5

#: Low-urgency families that may be grouped: dedup-key prefix -> (noun singular,
#: noun plural, predicate, link). Everything here is scheduled housekeeping whose
#: individual rows add nothing a filtered list doesn't show better.
GROUPABLE_FAMILIES: dict[str, tuple[str, str, str, str]] = {
    "control-audit": ("control", "controls", "tests overdue", "/controls"),
    "control-maint": ("control", "controls", "maintenance overdue", "/controls"),
    "risk-review": ("risk", "risks", "reviews overdue", "/risks"),
    # One per overdue open treatment action (phase 2), not one per risk deadline.
    "risk-treatment": ("risk treatment action", "risk treatment actions", "past due", "/risks"),
    # Phase 3: one per overdue open issue (CAPA) action, to its owner.
    "issue-action": ("issue action", "issue actions", "past due", "/issues"),
    "policy-review": ("policy", "policies", "reviews overdue", "/policies"),
    "vendor-review": ("third party", "third parties", "reviews overdue", "/vendors"),
    # Third-party certifications (phase 2), one alert per certificate: warned
    # CERT_EXPIRY_WARNING_DAYS out, then flagged once lapsed.
    "vendor-cert-expiring": ("third-party certification", "third-party certifications", "less than 60 days left", "/vendors"),
    "vendor-cert-expired": ("third-party certification", "third-party certifications", "expired", "/vendors"),
    "goal-audit": ("goal", "goals", "audits overdue", "/goals"),
    "bcp-test": ("continuity plan", "continuity plans", "tests overdue", "/continuity"),
    "ar-overdue": ("access review", "access reviews", "past due", "/access-reviews"),
    "aw-due": ("awareness programme", "awareness programmes", "training due", "/awareness"),
    "proj-overdue": ("project", "projects", "deadlines passed", "/projects"),
    "rcsa-overdue": ("RCSA", "RCSAs", "past due", "/operational-risk"),
    "iaeng-overdue": ("audit engagement", "audit engagements", "planned completion passed", "/internal-audit"),
}

#: Families that always render one row per record, however many there are. Each one is
#: either a breach, a decision somebody must take, or a clock set by a regulator:
#:
#: * ``risk-breach`` — a risk above tolerance; the board-level question.
#: * ``risk-acceptance-expiring`` — each lapse needs a named renew/let-lapse decision.
#: * ``tat-breach`` / ``tat-at-risk`` — turnaround-time (SLA) clocks, escalated by email.
#: * ``approval-pending`` — a named person's decision is waiting.
#: * ``issue-extension`` — a later due date on a serious issue awaits someone's approval.
#: * ``attest-overdue`` — a sign-off owed by a named person.
#: * ``regreport-overdue`` / ``sar-overdue`` — regulator (SBP / FMU) filing deadlines.
#: * ``screening-escalated`` — a sanctions match awaiting a decision.
#: * ``exc-expired`` — an approved deviation has lapsed and is now unapproved.
#: * ``kri-breach`` — an indicator past its limit (or outside its within-range band).
#: * ``iafinding-overdue`` / ``snc-overdue`` — audit and Shariah findings past remediation date.
#: * ``ropa-transfer`` / ``ropa-dpia`` — data-protection obligations under the law.
#:
#: Anything not in :data:`GROUPABLE_FAMILIES` is never grouped, so a new family is
#: individual until someone decides otherwise; this list documents the deliberate choices.
NEVER_GROUPED: frozenset[str] = frozenset({
    "risk-breach", "risk-acceptance-expiring", "tat-breach", "tat-at-risk",
    "approval-pending", "issue-extension", "attest-overdue", "regreport-overdue", "sar-overdue",
    "screening-escalated", "exc-expired", "kri-breach", "iafinding-overdue",
    "snc-overdue", "ropa-transfer", "ropa-dpia",
})

GROUP_PREFIX = "group:"

_CATEGORY_RANK = {NotificationCategory.critical: 0, NotificationCategory.warning: 1, NotificationCategory.info: 2}


def family_of(dedup_key: str) -> str:
    """The alert family a dedup key belongs to: everything before the first ``:``."""
    return dedup_key.split(":", 1)[0]


# ================================================================ recipients ===
#: A recipient is ``("u", <user id>)`` — one person — or ``("r", <role name>)`` — the
#: members of a role. An alert with no recipients is for everyone.
USER, ROLE = "u", "r"
Recipient = tuple[str, Any]

#: Separates an alert's condition key from its recipient in ``dedup_key``.
RECIPIENT_SEPARATOR = "@"


def to_users(*user_ids: Any) -> list[Recipient]:
    return [(USER, uid) for uid in user_ids if uid is not None]


def to_roles(*names: str | None) -> list[Recipient]:
    return [(ROLE, n) for n in names if n]


def recipient_suffix(user_id: Any = None, role_name: str | None = None) -> str:
    """``@u:<id>`` / ``@r:<role>`` / ``""`` (everyone). A row naming both a person and a
    role (an event) is keyed by the person."""
    if user_id is not None:
        return f"{RECIPIENT_SEPARATOR}{USER}:{user_id}"
    if role_name:
        return f"{RECIPIENT_SEPARATOR}{ROLE}:{role_name}"
    return ""


def base_key(dedup_key: str) -> str:
    """The condition an alert key describes, without its recipient."""
    return (dedup_key or "").split(RECIPIENT_SEPARATOR, 1)[0]


@dataclass
class DirectoryUser:
    id: uuid.UUID
    email: str = ""
    full_name: str = ""
    is_active: bool = True
    roles: tuple[str, ...] = ()


@dataclass
class Directory:
    """The organisation's people and roles, as the scanner needs them: who is active,
    who a free-text owner names, which roles exist and what they grant. Built once per
    scan (:func:`load_directory`); pure once built, so the routing rules are testable."""

    users: dict[uuid.UUID, DirectoryUser] = field(default_factory=dict)
    #: role name -> permission codes it grants (every role, even one granting nothing).
    role_permissions: dict[str, frozenset[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._by_email: dict[str, uuid.UUID] = {}
        self._by_name: dict[str, list[uuid.UUID]] = {}
        for u in self.users.values():
            if not u.is_active:
                continue
            if u.email:
                self._by_email[u.email.strip().lower()] = u.id
            name = " ".join((u.full_name or "").split()).lower()
            if name:
                self._by_name.setdefault(name, []).append(u.id)
        self._roles = {name.lower(): name for name in self.role_permissions}

    # -- people
    def active(self, user_id: Any) -> bool:
        u = self.users.get(user_id) if user_id is not None else None
        return bool(u and u.is_active)

    def first_active(self, *user_ids: Any) -> list[Recipient]:
        """The first of ``user_ids`` who is an active user, as a recipient list."""
        for uid in user_ids:
            if self.active(uid):
                return [(USER, uid)]
        return []

    def active_users(self, *user_ids: Any) -> list[Recipient]:
        return [(USER, uid) for uid in dict.fromkeys(user_ids) if self.active(uid)]

    def person(self, text: str | None) -> uuid.UUID | None:
        """The active user a free-text name or address means: an exact e-mail match, or
        the one active user with exactly that full name. None when it names nobody, or
        more than one person."""
        t = " ".join((text or "").split()).lower()
        if not t:
            return None
        if t in self._by_email:
            return self._by_email[t]
        ids = self._by_name.get(t, [])
        return ids[0] if len(ids) == 1 else None

    def label(self, user_id: Any) -> str:
        u = self.users.get(user_id)
        return (u.full_name or u.email) if u else ""

    # -- roles
    def role(self, name: str | None) -> str | None:
        """The role's canonical name (case-insensitive match), or None."""
        return self._roles.get(" ".join((name or "").split()).lower()) if name else None

    def roles_of(self, user_id: Any) -> tuple[str, ...]:
        u = self.users.get(user_id)
        return u.roles if u else ()

    def members(self, role_name: str) -> list[uuid.UUID]:
        return [u.id for u in self.users.values() if u.is_active and role_name in u.roles]

    def roles_granting(self, *permissions: str) -> list[str]:
        """Roles granting every one of ``permissions``, sorted by name."""
        wanted = set(permissions)
        return sorted(name for name, perms in self.role_permissions.items() if wanted <= perms)

    def permissions_of(self, user_id: Any) -> set[str]:
        codes: set[str] = set()
        for r in self.roles_of(user_id):
            codes |= self.role_permissions.get(r, frozenset())
        return codes

    def dpo_roles(self) -> list[str]:
        from app.services.incident_clock import is_dpo_role

        return sorted(name for name in self.role_permissions if is_dpo_role(name))


async def load_directory(db: AsyncSession) -> Directory:
    """This organisation's users, role memberships and role permissions (four queries;
    row-level security scopes users and roles, and the association tables are only
    reached through them)."""
    from app.models.identity import Permission, Role, User, role_permissions, user_roles

    users = {
        uid: DirectoryUser(id=uid, email=email or "", full_name=name or "", is_active=bool(active))
        for uid, email, name, active in (
            await db.execute(select(User.id, User.email, User.full_name, User.is_active))
        ).all()
    }
    memberships: dict[uuid.UUID, list[str]] = {}
    for uid, role_name in (
        await db.execute(select(user_roles.c.user_id, Role.name).join(Role, Role.id == user_roles.c.role_id))
    ).all():
        memberships.setdefault(uid, []).append(role_name)
    for uid, names in memberships.items():
        if uid in users:
            users[uid].roles = tuple(sorted(names))
    grants: dict[str, set[str]] = {name: set() for (name,) in (await db.execute(select(Role.name))).all()}
    for role_name, code in (
        await db.execute(
            select(Role.name, Permission.code)
            .join(role_permissions, role_permissions.c.role_id == Role.id)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
        )
    ).all():
        grants.setdefault(role_name, set()).add(code)
    return Directory(users=users, role_permissions={k: frozenset(v) for k, v in grants.items()})


def normalise_recipients(recipients: Iterable[Recipient] | None, directory: Directory | None) -> list[Recipient]:
    """Drop recipients who can't receive anything (unknown or inactive users, roles that
    don't exist), canonicalise role names and remove duplicates, keeping order. Pure.
    Without a directory every recipient is taken at its word."""
    out: list[Recipient] = []
    seen: set[Recipient] = set()
    for kind, value in recipients or ():
        if kind == USER:
            if value is None or (directory is not None and not directory.active(value)):
                continue
            item: Recipient = (USER, value)
        elif kind == ROLE:
            name = directory.role(value) if directory is not None else (value or None)
            if not name:
                continue
            item = (ROLE, name)
        else:
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def address_alerts(alerts: Iterable[Mapping[str, Any]], directory: Directory | None = None) -> list[dict]:
    """One alert per recipient. Pure.

    Each scanned alert carries ``to`` (its recipients). An alert with recipients becomes
    one copy per recipient, with the recipient appended to its ``dedup_key`` and set in
    ``user_id`` / ``role_name``; an alert with none (or none who can receive it) stays
    one copy for everyone, under its plain key.
    """
    out: list[dict] = []
    for a in alerts:
        base = {k: v for k, v in a.items() if k != "to"}
        recipients = normalise_recipients(a.get("to"), directory)
        if not recipients:
            out.append({**base, "user_id": None, "role_name": ""})
            continue
        for kind, value in recipients:
            user_id, role_name = (value, "") if kind == USER else (None, value)
            out.append({
                **base,
                "dedup_key": f"{a['dedup_key']}{recipient_suffix(user_id, role_name)}",
                "user_id": user_id,
                "role_name": role_name,
            })
    return out


# ================================================================ grouping ===
def _example_label(alert: Mapping[str, Any]) -> str:
    title = str(alert.get("title", ""))
    return title.split(": ", 1)[1] if ": " in title else title


def _recipient_of(alert: Mapping[str, Any]) -> str:
    return recipient_suffix(alert.get("user_id"), alert.get("role_name") or "")


def group_alerts(
    alerts: list[dict], *, threshold: int = GROUP_THRESHOLD, examples: int = GROUP_EXAMPLES
) -> list[dict]:
    """Collapse any groupable family with more than ``threshold`` alerts *for one
    recipient* into one alert for that recipient.

    Pure: takes and returns the scanner's alert dicts. Order is preserved; the grouped
    alert takes the position of its bucket's first member. Families in
    :data:`NEVER_GROUPED` (or not in :data:`GROUPABLE_FAMILIES`) pass through untouched.
    Alerts without a recipient form their own bucket, keyed ``group:<family>`` as before.
    """
    buckets: dict[tuple[str, str], list[dict]] = {}
    for a in alerts:
        fam = family_of(a["dedup_key"])
        if fam in GROUPABLE_FAMILIES and fam not in NEVER_GROUPED:
            buckets.setdefault((fam, _recipient_of(a)), []).append(a)
    to_group = {key for key, members in buckets.items() if len(members) > threshold}
    if not to_group:
        return list(alerts)

    out: list[dict] = []
    emitted: set[tuple[str, str]] = set()
    for a in alerts:
        key = (family_of(a["dedup_key"]), _recipient_of(a))
        if key not in to_group:
            out.append(a)
            continue
        if key in emitted:
            continue
        emitted.add(key)
        fam, suffix = key
        members = buckets[key]
        singular, plural, predicate, link = GROUPABLE_FAMILIES[fam]
        n = len(members)
        names = [_example_label(m) for m in members[:examples]]
        more = n - len(names)
        body = "Including " + ", ".join(names) + (f" and {more} more" if more > 0 else "") + "."
        category = min((m["category"] for m in members), key=lambda c: _CATEGORY_RANK.get(c, 3))
        grouped = {
            "dedup_key": f"{GROUP_PREFIX}{fam}{suffix}",
            "title": f"{n} {plural if n != 1 else singular} {'have' if n != 1 else 'has'} {predicate}",
            "body": body,
            "category": category,
            "entity_type": members[0]["entity_type"],
            "entity_id": None,
            "link": link,
        }
        if "user_id" in members[0] or "role_name" in members[0]:
            grouped["user_id"] = members[0].get("user_id")
            grouped["role_name"] = members[0].get("role_name") or ""
        out.append(grouped)
    return out


# =============================================================== reconcile ===
#: Notification columns an alert re-derives on every scan and ``refresh`` keeps current.
REFRESHED_FIELDS: tuple[str, ...] = ("title", "body", "category", "link", "entity_type", "entity_id")


def alert_changes(existing: Any, alert: Mapping[str, Any]) -> dict[str, Any]:
    """Fields of an existing notification that differ from the freshly computed alert.

    Pure: ``existing`` is anything with the notification attributes (the ORM row, or a
    stand-in in tests). An empty dict means the stored alert is still accurate.
    """
    changes: dict[str, Any] = {}
    for field_name in REFRESHED_FIELDS:
        if field_name not in alert:
            continue
        new = alert[field_name]
        old = getattr(existing, field_name, None)
        if field_name == "category":
            old_v = getattr(old, "value", old)
            new_v = getattr(new, "value", new)
            if old_v != new_v:
                changes[field_name] = new
        elif (old or None) != (new or None):
            changes[field_name] = new
    return changes


def keys_to_delete(
    existing_keys: Iterable[str], current_keys: set[str], *, keep_prefix: str = EVENT_PREFIX
) -> list[str]:
    """Stored alert keys whose condition no longer holds. Keys starting with
    ``keep_prefix`` (recorded events) are never swept."""
    return [k for k in existing_keys if not k.startswith(keep_prefix) and k not in current_keys]


def _for_everyone(row: Any) -> bool:
    return getattr(row, "user_id", None) is None and not (getattr(row, "role_name", "") or "")


@dataclass
class ReconcilePlan:
    #: (stored row, {field: new value}) for alerts whose text changed.
    updates: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    #: (alert, created_at to keep or None). A kept date means the row is not news.
    creates: list[tuple[dict, datetime | None]] = field(default_factory=list)
    #: Stored keys whose condition no longer holds.
    deletes: list[str] = field(default_factory=list)


def reconcile_plan(
    existing: Mapping[str, Any], alerts: Sequence[Mapping[str, Any]], *, keep_prefix: str = EVENT_PREFIX
) -> ReconcilePlan:
    """What ``refresh`` must add, rewrite and delete. Pure.

    One rule beyond add/update/delete: an alert that was addressed to everyone (a row
    under its plain key — every row before per-person alerts existed, or a record that
    named no owner until now) and is now addressed to a person or a role is *not news*.
    Everyone was already shown it, and told by e-mail when it first appeared, so its
    new rows keep the old row's date: the recipient's unread count and digest don't
    treat it as new. An alert moving from one owner to another *is* news to the new owner.
    """
    plan = ReconcilePlan()
    shown_to_everyone = {
        k: row for k, row in existing.items() if not k.startswith(keep_prefix) and _for_everyone(row)
    }
    for a in alerts:
        key = a["dedup_key"]
        stored = existing.get(key)
        if stored is not None:
            changes = alert_changes(stored, a)
            if changes:
                plan.updates.append((stored, changes))
            continue
        carried = None
        base = base_key(key)
        if base != key and base in shown_to_everyone:
            carried = getattr(shown_to_everyone[base], "created_at", None)
        plan.creates.append((dict(a), carried))
    plan.deletes = keys_to_delete(existing.keys(), {a["dedup_key"] for a in alerts}, keep_prefix=keep_prefix)
    return plan


# ============================================================== visibility ===
AUDIENCE_ME, AUDIENCE_ROLE, AUDIENCE_EVERYONE = "me", "role", "everyone"


def is_visible(row: Any, user_id: Any, role_names: Iterable[str], *, mine: bool = False) -> bool:
    """Whether a notification is for this user. Pure — the rule :func:`visible_clause`
    puts in SQL. ``mine`` narrows it to rows addressed to the user or one of their roles
    (leaving out what is addressed to everyone)."""
    row_user = getattr(row, "user_id", None)
    row_role = getattr(row, "role_name", "") or ""
    if row_user is not None and row_user == user_id:
        return True
    if row_role and row_role in set(role_names):
        return True
    if mine:
        return False
    return row_user is None and not row_role


def visible_clause(user_id: Any, role_names: Iterable[str], *, mine: bool = False):
    """SQL filter for the notifications a user sees (see :func:`is_visible`)."""
    roles = sorted(set(role_names))
    addressed = [Notification.user_id == user_id]
    if roles:
        addressed.append(Notification.role_name.in_(roles))
    if mine:
        return or_(*addressed)
    return or_(*addressed, and_(Notification.user_id.is_(None), Notification.role_name == ""))


def audience_of(row: Any, user_id: Any) -> str:
    """How a visible row reached this user: ``me``, ``role`` or ``everyone``. Pure."""
    if getattr(row, "user_id", None) is not None and row.user_id == user_id:
        return AUDIENCE_ME
    if getattr(row, "role_name", ""):
        return AUDIENCE_ROLE
    return AUDIENCE_EVERYONE


# =================================================================== links ===
#: Registers whose page opens a record from ``?id=`` but that global search doesn't
#: index (so :func:`record_registry.link_for` doesn't know them).
EXTRA_LINKS: dict[str, str] = {
    "access_review": "/access-reviews",
    "awareness_program": "/awareness",
    "approval": "/approvals",
    "data_breach": "/data-protection",
    "dpia": "/data-protection",
    "dsar": "/data-protection",
}


def with_id(base: str, entity_id: Any, param: str = "id") -> str:
    """``/risks`` + id -> ``/risks?id=<id>``. Pure."""
    if not base or entity_id is None:
        return base or ""
    return f"{base}{'&' if '?' in base else '?'}{param}={entity_id}"


def record_link(record: Any, fallback: str = "") -> str:
    """The deep link that opens ``record`` in its register (``/risks?id=…``)."""
    from app.services import record_registry

    link = record_registry.link_for(record)
    if link:
        return link
    return with_id(fallback, getattr(record, "id", None)) if fallback else ""


def link_to(entity_type: str, entity_id: Any, *, asset_class: Any = None) -> str:
    """The deep link for a record known only by type and id. Pure apart from the model
    registry; ``asset_class`` picks the IT or information asset register."""
    from app.api.v1.search import _TARGETS
    from app.models.asset import Asset
    from app.services import record_registry

    model = record_registry.model_for(entity_type)
    if model is Asset:
        kind = getattr(asset_class, "value", asset_class)
        return with_id("/it-assets" if kind == "it_asset" else "/information-assets", entity_id)
    for target in _TARGETS:
        if model is not None and target.model is model:
            return with_id(target.link, entity_id)
    return with_id(EXTRA_LINKS.get(entity_type, ""), entity_id)


def owner_column(model: type) -> Any:
    """The column naming a record's owning *user* (the first owner-ish column that is a
    foreign key to ``users``), or None. Mirrors ``attestations.owner_user_id``:
    ``Asset.owner_id`` names a business unit and is skipped."""
    table = getattr(model, "__table__", None)
    if table is None:
        return None
    for col in table.columns:
        if "owner" not in col.key:
            continue
        if any(fk.column.table.name == "users" for fk in col.foreign_keys):
            return col
    return None


def certification_alert(cert: Any, vendor: Any, today: date) -> tuple | None:
    """The ``add(...)`` arguments for one vendor certification, or None when it is
    neither expiring nor expired. Pure (see ``models.vendor.certification_expiry_state``)."""
    from app.schemas.vendor import CERT_TYPES

    state = certification_expiry_state(cert.expires_on, today)
    label = CERT_TYPES.get(cert.cert_type, cert.cert_type)
    link = with_id("/vendors", getattr(vendor, "id", None))
    if state == "expiring":
        days = (cert.expires_on - today).days
        return (f"vendor-cert-expiring:{cert.id}", f"Certification expiring: {vendor.name} {label}",
                f"{label} expires {cert.expires_on} ({days} day(s) left) — ask for the renewed certificate",
                _W, "vendor", vendor.id, link)
    if state == "expired":
        crit = getattr(vendor.criticality, "value", vendor.criticality)
        return (f"vendor-cert-expired:{cert.id}", f"Certification expired: {vendor.name} {label}",
                f"{label} expired on {cert.expires_on} — obtain the renewal or record the gap",
                _C if crit in ("high", "critical") else _W, "vendor", vendor.id, link)
    return None


# =============================================================== approvals ===
#: Approver labels that name nobody in particular (a route's "any approver", a request
#: typed with no approver): the request goes to everyone who may decide it.
GENERIC_APPROVER_LABELS: frozenset[str] = frozenset({
    "", "any", "any approver", "approver", "approval required", "record owner", "line manager",
})
APPROVE_PERMISSION = "workflow:approve"


def resolve_approver(label: str | None, directory: Directory) -> Recipient | None:
    """Who an approval request's free-text ``approver`` names: a user (by e-mail or
    unique full name), else a role (by name), else None — nobody in particular. Pure."""
    text = " ".join((label or "").split())
    low = text.lower()
    if low in GENERIC_APPROVER_LABELS or low.startswith("line manager of"):
        return None
    uid = directory.person(text)
    if uid is not None:
        return (USER, uid)
    role = directory.role(text)
    if role:
        return (ROLE, role)
    return None


def _raised_by(approval: Any, user_id: Any, email: str | None) -> bool:
    from app.api.v1.approvals import is_maker

    return is_maker(
        getattr(approval, "requested_by", None), getattr(approval, "requested_by_email", ""), user_id, email
    )


def approval_recipients(approval: Any, directory: Directory) -> list[Recipient]:
    """Who a pending approval request is waiting on. Pure.

    The named approver when the label resolves to a person (unless that person raised
    the request — segregation of duties means they can't decide it) or a role;
    otherwise every role that grants ``workflow:approve``. When the person or role named
    can't decide it (nobody there holds ``workflow:approve``), the approving roles are
    told as well, so a request never waits unseen by everyone who could decide it. No
    approving role at all → everyone."""
    approvers = to_roles(*directory.roles_granting(APPROVE_PERMISSION))
    target = resolve_approver(getattr(approval, "approver", ""), directory)
    if target is not None and target[0] == ROLE:
        can = any(APPROVE_PERMISSION in directory.permissions_of(uid) for uid in directory.members(target[1]))
        return [target] if can else [target] + [r for r in approvers if r != target]
    if target is not None:
        person = directory.users.get(target[1])
        if not _raised_by(approval, target[1], person.email if person else None):
            if APPROVE_PERMISSION in directory.permissions_of(target[1]):
                return [target]
            return [target] + approvers
    return approvers


def approval_refusal(
    approval: Any, *, user_id: Any, email: str | None, permissions: Iterable[str],
    voted_ids: Iterable[Any] = (), sod: bool | None = None,
) -> str | None:
    """Why this user can't decide this approval request now, or None. Pure.

    The same checks, in the same order, as ``POST /approvals/{id}/decision``: the
    request is pending, the user holds ``workflow:approve``, segregation of duties (not
    the maker), one decision per checker."""
    from app.core.config import settings

    status_value = getattr(getattr(approval, "status", None), "value", getattr(approval, "status", None))
    if status_value != ApprovalStatus.pending.value:
        return f"This request is already {status_value}."
    if APPROVE_PERMISSION not in set(permissions):
        return f"Deciding approval requests needs the {APPROVE_PERMISSION} permission."
    enforce = settings.enforce_segregation_of_duties if sod is None else sod
    if enforce and _raised_by(approval, user_id, email):
        return "You raised this request, so an independent checker must decide it."
    if user_id in set(voted_ids):
        return "You have already recorded a decision on this request."
    return None


# ================================================================== KRIs ===
# Phase 2: within-range KRIs and escalation. The live ``kri-breach`` alert (scanned) says
# what is true now; the ``event:kri-escalation`` notification records the moment a
# reading moved a KRI into amber or red, naming who it goes to and what they must do.
# Phase 3: both are addressed — to the escalation's person and role (the owner when no
# escalation is set) — and the text still names them.
def _kri_num(value: Any) -> str:
    if value is None:
        return "—"
    v = float(value)
    return str(int(v)) if v.is_integer() else f"{v:.4f}".rstrip("0").rstrip(".")


def kri_threshold_text(kri: Any) -> str:
    """What a KRI's reading is judged against, in words. Pure."""
    unit = f" {kri.unit}" if getattr(kri, "unit", "") else ""
    direction = getattr(kri.direction, "value", kri.direction)
    if direction == "within_range":
        band = f"range {_kri_num(kri.lower_bound)}–{_kri_num(kri.upper_bound)}{unit}"
        if kri.limit_threshold is not None:
            return f"{band}, tolerance {_kri_num(kri.limit_threshold)}"
        return band
    parts = []
    if kri.warning_threshold is not None:
        parts.append(f"warning {_kri_num(kri.warning_threshold)}")
    if kri.limit_threshold is not None:
        parts.append(f"limit {_kri_num(kri.limit_threshold)}")
    return (", ".join(parts) + unit) if parts else "no thresholds"


def escalation_target_text(escalation: Any, people: Mapping[Any, Any]) -> str:
    """"Jane Doe and the CRO role" — who an escalation goes to. Pure."""
    if escalation is None:
        return ""
    who = []
    if escalation.escalate_to_id is not None:
        person = people.get(escalation.escalate_to_id)
        who.append((person.full_name or person.email) if person else "a user no longer on file")
    if escalation.escalate_to_role:
        who.append(f"the {escalation.escalate_to_role} role")
    return " and ".join(who)


def _escalation_for(kri: Any, level: str) -> Any:
    return next((e for e in (getattr(kri, "escalations", None) or []) if e.level == level), None)


def kri_breach_body(kri: Any, people: Mapping[Any, Any]) -> str:
    """Body of the live ``kri-breach`` alert. Pure."""
    unit = f" {kri.unit}" if getattr(kri, "unit", "") else ""
    direction = getattr(kri.direction, "value", kri.direction)
    what = "is outside its" if direction == "within_range" else "breached its"
    body = f"{kri.name} — current {_kri_num(kri.current_value)}{unit} {what} {kri_threshold_text(kri)}"
    escalation = _escalation_for(kri, "red")
    target = escalation_target_text(escalation, people)
    if target:
        body += f". Escalate to {target}" + (f": {escalation.action}" if escalation.action else "")
    return body


def kri_breach_recipients(kri: Any, directory: Directory) -> list[Recipient]:
    """A breached KRI's owner, plus its red escalation's person and role. Pure."""
    escalation = _escalation_for(kri, "red")
    people = directory.active_users(getattr(kri, "owner_id", None), getattr(escalation, "escalate_to_id", None))
    return people + to_roles(getattr(escalation, "escalate_to_role", "") or "")


def _is_active(person: Any) -> bool:
    return person is not None and bool(getattr(person, "is_active", True))


def escalation_addressee(escalation: Any, owner_id: Any, people: Mapping[Any, Any]) -> tuple[Any, str]:
    """``(user_id, role_name)`` for a KRI escalation event: the escalation's person
    and/or role, or the KRI's owner when the level has no escalation. ``(None, "")`` —
    everyone — when there is nobody to tell. Pure."""
    user_id: Any = None
    role = ""
    if escalation is not None:
        pid = getattr(escalation, "escalate_to_id", None)
        if pid is not None and _is_active(people.get(pid)):
            user_id = pid
        role = getattr(escalation, "escalate_to_role", "") or ""
    if user_id is None and not role and owner_id is not None and _is_active(people.get(owner_id)):
        user_id = owner_id
    return user_id, role


def kri_escalation_event(
    kri: Any, level: str, *, value: Any, as_of: Any, measurement_id: Any,
    escalation: Any, target: str, owner: str,
) -> dict:
    """The event notification raised when a reading moves a KRI into amber or red. Pure.

    One per reading (the dedup key carries the measurement), and an ``event:`` key so the
    reconciler never sweeps it away once the KRI recovers."""
    unit = f" {kri.unit}" if getattr(kri, "unit", "") else ""
    label = f"{kri.reference} {kri.name}".strip()
    reading = f"{_kri_num(value)}{unit}" + (f" as of {as_of}" if as_of else "")
    if escalation is not None and target:
        step = f"Escalate to {target}" + (f": {escalation.action}" if escalation.action else ".")
    elif owner:
        step = f"No {level} escalation is set for this KRI; its owner, {owner}, should act."
    else:
        step = f"No {level} escalation or owner is set for this KRI; name one on the KRI."
    state = "red (limit breached)" if level == "red" else "amber (early warning)"
    return {
        "dedup_key": f"{EVENT_PREFIX}kri-escalation:{kri.id}:{measurement_id}",
        "title": f"KRI {state}: {label}"[:255],
        "body": f"Reading {reading} against {kri_threshold_text(kri)}. {step}",
        "category": _C if level == "red" else _W,
        "entity_type": "key_risk_indicator",
        "entity_id": kri.id,
        "link": with_id("/operational-risk", kri.id),
    }


async def _escalation_people(db: AsyncSession, kris: Iterable[Any], level: str) -> dict:
    from app.services import master_data

    ids = [e.escalate_to_id for k in kris for e in (k.escalations or []) if e.level == level]
    return await master_data.users_by_id(db, ids)


async def raise_kri_escalation(
    db: AsyncSession, kri: Any, level: str, *, value: Any, as_of: Any, measurement_id: Any,
) -> dict:
    """Add the escalation event for a KRI that a reading just moved into ``level``.

    The event is addressed to the escalation's person and role (one row naming both),
    or to the KRI's owner when the level has no escalation. Returns the notification
    fields plus ``target`` and ``action`` for the caller's audit entry (the caller knows
    whether a person or the KRI feed recorded the reading)."""
    from app.services import master_data

    escalation = _escalation_for(kri, level)
    people = await master_data.users_by_id(
        db, [getattr(escalation, "escalate_to_id", None), kri.owner_id]
    )
    owner_ref = people.get(kri.owner_id) if kri.owner_id else None
    owner = (owner_ref.full_name or owner_ref.email) if owner_ref else (kri.owner or "")
    target = escalation_target_text(escalation, people)
    fields = kri_escalation_event(
        kri, level, value=value, as_of=as_of, measurement_id=measurement_id,
        escalation=escalation, target=target, owner=owner,
    )
    user_id, role_name = escalation_addressee(escalation, kri.owner_id, people)
    db.add(Notification(tenant_id=kri.tenant_id, user_id=user_id, role_name=role_name, **fields))
    return {**fields, "user_id": user_id, "role_name": role_name,
            "target": target or owner, "action": getattr(escalation, "action", "") or ""}


# ================================================================ the scan ===
async def _record_owners(
    db: AsyncSession, directory: Directory, pairs: Iterable[tuple[str, Any]]
) -> dict[tuple[str, Any], tuple[list[Recipient], str]]:
    """Recipients and deep link for records known only by ``(entity_type, id)`` — one
    query per type: the record's owning user, else its approval owner."""
    from app.models.asset import Asset
    from app.services import record_registry

    by_type: dict[str, list[Any]] = {}
    for etype, eid in pairs:
        by_type.setdefault(etype, []).append(eid)
    out: dict[tuple[str, Any], tuple[list[Recipient], str]] = {}
    for etype, ids in by_type.items():
        model = record_registry.model_for(etype)
        if model is None:
            continue
        cols = model.__table__.columns
        owner = owner_column(model)
        wf = cols.get("workflow_owner_id")
        wanted = [model.id, owner if owner is not None else None, wf if wf is not None and wf is not owner else None]
        select_cols = [c for c in wanted if c is not None]
        if model is Asset:
            select_cols.append(Asset.asset_class)
        for row in (await db.execute(select(*select_cols).where(model.id.in_(ids)))).all():
            values = dict(zip([c.key for c in select_cols], row))
            rid = values["id"]
            recipients = directory.first_active(
                values.get(owner.key) if owner is not None else None,
                values.get("workflow_owner_id"),
            )
            out[(etype, rid)] = (recipients, link_to(etype, rid, asset_class=values.get("asset_class")))
    return out


async def _tat_context(db: AsyncSession, directory: Directory, records: Sequence[Any]) -> dict:
    """For each turnaround-time record: its owner (as recipients), deep link and the
    SLA policy's escalation role. One query per record type."""
    from app.models.enums import Severity
    from app.services import sla as sla_service

    by_type: dict[str, list[Any]] = {}
    for r in records:
        by_type.setdefault(r.entity_type, []).append(r.entity_id)
    owners: dict[tuple[str, Any], tuple[list[Recipient], str]] = {}
    if "risk" in by_type:
        for rid, owner_id in (await db.execute(
            select(Risk.id, Risk.owner_id).where(Risk.id.in_(by_type["risk"]))
        )).all():
            owners[("risk", rid)] = (directory.first_active(owner_id), with_id("/risks", rid))
    if "issue" in by_type:
        for iid, owner_id in (await db.execute(
            select(Issue.id, Issue.owner_id).where(Issue.id.in_(by_type["issue"]))
        )).all():
            owners[("issue", iid)] = (directory.first_active(owner_id), with_id("/issues", iid))
    if "incident" in by_type:
        for iid, assignee_id in (await db.execute(
            select(Incident.id, Incident.assignee_id).where(Incident.id.in_(by_type["incident"]))
        )).all():
            owners[("incident", iid)] = (directory.first_active(assignee_id), with_id("/incidents", iid))
    if "audit_finding" in by_type:
        for fid, action_owner, engagement_id in (await db.execute(
            select(AuditFinding.id, AuditFinding.action_owner, AuditFinding.engagement_id)
            .where(AuditFinding.id.in_(by_type["audit_finding"]))
        )).all():
            owners[("audit_finding", fid)] = (
                to_users(directory.person(action_owner)), with_id("/internal-audit", engagement_id),
            )
    policies = await sla_service.policy_map(db)
    out = {}
    for r in records:
        recipients, link = owners.get((r.entity_type, r.entity_id), ([], with_id(r.link, r.entity_id)))
        try:
            severity = Severity(r.severity)
        except ValueError:
            severity = Severity.medium
        _t, _w, role = sla_service.target_for(policies, r.entity_type, severity)
        out[(r.entity_type, r.entity_id)] = (recipients, link, directory.role(role) or "")
    return out


async def scan_alerts(db: AsyncSession, tenant_id, directory: Directory | None = None) -> list[dict]:
    """Every alert that holds now, each with its recipients in ``to`` (see
    :func:`address_alerts`). ``directory`` is loaded when not given."""
    today = date.today()
    alerts: list[dict] = []
    if directory is None:
        directory = await load_directory(db)

    def add(key, title, body, category, etype, eid, link, to=()):
        alerts.append(
            {
                "dedup_key": key,
                "title": title,
                "body": body,
                "category": category,
                "entity_type": etype,
                "entity_id": eid,
                "link": link,
                "to": list(to),
            }
        )

    def named(*texts: str | None) -> list[Recipient]:
        """The first free-text owner that names exactly one active user."""
        for text in texts:
            uid = directory.person(text)
            if uid is not None:
                return [(USER, uid)]
        return []

    # Every scan below filters to only the rows that actually raise an alert (overdue
    # dates, breached thresholds, open-and-past-due statuses) directly in SQL, so we never
    # materialise a whole module's table into Python. Predicates mirror the model helpers
    # (`has_transfer_gap`, `is_breached`, `is_overdue`, `effective_score`) exactly.
    settings = await get_or_create_settings(db, tenant_id)
    # Tolerance is the risk's top-level category's where one is set (RiskAppetite), else
    # the organisation's; the SQL pre-filter uses the lowest tolerance anywhere.
    book = await load_appetite_book(db, tenant_id, settings)
    _eff = func.coalesce(Risk.residual_score, Risk.inherent_score)
    _risk_stmt = select(Risk).where(
        Risk.deleted.is_(False),
        or_(Risk.next_review_date < today, _eff > book.min_tolerance),
    )
    for r in (await db.scalars(_risk_stmt)).all():
        owner = directory.first_active(r.owner_id)
        link = record_link(r, "/risks")
        if r.next_review_date and r.next_review_date < today:
            add(f"risk-review:{r.id}", f"Risk review overdue: {r.reference}",
                f"{r.title} — review was due {r.next_review_date}", _W, "risk", r.id, link, owner)
        eff = effective_score(r.inherent_score, r.residual_score)
        tolerance = book.tolerance_for(r.category_id)
        if eff is not None and eff > tolerance:
            add(f"risk-breach:{r.id}", f"Risk above tolerance: {r.reference}",
                f"{r.title} — score {eff} exceeds tolerance {tolerance}", _C, "risk", r.id, link, owner)

    # Risk treatment is tracked per action: each open action past its due date raises
    # its own alert (grouped with the rest of the housekeeping when there are many), to
    # the action's owner — else the risk's treatment owner, else the risk's owner.
    _action_stmt = (
        select(RiskTreatmentAction, Risk.reference, Risk.treatment_owner_id, Risk.owner_id)
        .join(Risk, Risk.id == RiskTreatmentAction.risk_id)
        .where(
            Risk.deleted.is_(False),
            RiskTreatmentAction.status.in_(("open", "in_progress")),
            RiskTreatmentAction.due_date < today,
        )
    )
    for action, risk_ref, treatment_owner_id, risk_owner_id in (await db.execute(_action_stmt)).all():
        add(f"risk-treatment:{action.id}", f"Treatment action overdue: {risk_ref}",
            f"{action.title} — was due {action.due_date} ({action.percent_complete}% done)",
            _W, "risk", action.risk_id, with_id("/risks", action.risk_id),
            directory.first_active(action.owner_id, treatment_owner_id, risk_owner_id))

    # An acceptance that lapses unnoticed puts the risk back in the register with nobody
    # expecting it, so the chase starts a month out — the shortest notice on which an
    # owner can restate the rationale and a second person can approve it. This is a live
    # condition: renew the acceptance or let it lapse and the alert resolves itself. The
    # lapse *event* is raised separately by `services.risk_acceptance`.
    _acceptance_stmt = (
        select(RiskAcceptance, Risk.reference, Risk.title, Risk.owner_id)
        .join(Risk, Risk.id == RiskAcceptance.risk_id)
        .where(
            RiskAcceptance.status == AcceptanceStatus.approved,
            RiskAcceptance.expires_at.is_not(None),
            RiskAcceptance.expires_at >= today,
            RiskAcceptance.expires_at <= today + timedelta(days=EXPIRY_WARNING_DAYS),
            Risk.deleted.is_(False),
        )
    )
    for acceptance, risk_ref, risk_title, risk_owner_id in (await db.execute(_acceptance_stmt)).all():
        days_left = (acceptance.expires_at - today).days
        add(f"risk-acceptance-expiring:{acceptance.id}",
            f"Risk acceptance expiring: {risk_ref or risk_title}",
            f"The approved acceptance lapses on {acceptance.expires_at} "
            f"({days_left} day(s) left) — renew it or the risk returns to the register",
            _W, "risk", acceptance.risk_id, with_id("/risks", acceptance.risk_id),
            directory.first_active(risk_owner_id))

    # Planned and retired controls have no test or maintenance clock (D-02): a control
    # that is not operating yet cannot be overdue for a test of how it operates. A test
    # is due to the control's owner and its operator; maintenance to the owner.
    _control_stmt = select(Control).where(
        Control.deleted.is_(False),
        Control.status.not_in(UNTESTABLE_CONTROL_STATUSES),
        or_(Control.next_audit_date < today, Control.next_maintenance_date < today),
    )
    for c in (await db.scalars(_control_stmt)).all():
        link = record_link(c, "/controls")
        if c.next_audit_date and c.next_audit_date < today:
            add(f"control-audit:{c.id}", f"Control audit overdue: {c.reference or c.name}",
                f"Audit was due {c.next_audit_date}", _W, "control", c.id, link,
                directory.active_users(c.owner_id, c.operator_id))
        if c.next_maintenance_date and c.next_maintenance_date < today:
            add(f"control-maint:{c.id}", f"Control maintenance overdue: {c.reference or c.name}",
                f"Maintenance was due {c.next_maintenance_date}", _W, "control", c.id, link,
                directory.first_active(c.owner_id, c.operator_id))

    _exc_stmt = select(ExceptionRecord).where(
        ExceptionRecord.deleted.is_(False),
        ExceptionRecord.status == ExceptionStatus.approved,
        ExceptionRecord.expires_at < today,
    )
    for e in (await db.scalars(_exc_stmt)).all():
        add(f"exc-expired:{e.id}", f"Exception expired: {e.reference}",
            f"{e.title} expired {e.expires_at}", _C, "exception", e.id, record_link(e, "/exceptions"),
            named(e.business_owner) or directory.first_active(e.workflow_owner_id))

    _goal_stmt = select(Goal).where(Goal.deleted.is_(False), Goal.next_audit_date < today)
    for g in (await db.scalars(_goal_stmt)).all():
        add(f"goal-audit:{g.id}", f"Goal audit overdue: {g.reference}",
            f"{g.name} — audit was due {g.next_audit_date}", _W, "goal", g.id, record_link(g, "/goals"),
            directory.first_active(g.owner_id, g.workflow_owner_id))

    _bcp_stmt = select(ContinuityPlan).where(
        ContinuityPlan.deleted.is_(False), ContinuityPlan.next_test_date < today
    )
    for p in (await db.scalars(_bcp_stmt)).all():
        add(f"bcp-test:{p.id}", f"Continuity test overdue: {p.reference}",
            f"{p.name} — test was due {p.next_test_date}", _W, "continuity_plan", p.id,
            record_link(p, "/continuity"),
            named(p.owner) or directory.first_active(p.workflow_owner_id))

    _ar_stmt = select(AccessReview).where(
        AccessReview.deleted.is_(False),
        AccessReview.due_date < today,
        AccessReview.status != AccessReviewStatus.completed,
    )
    for ar in (await db.scalars(_ar_stmt)).all():
        add(f"ar-overdue:{ar.id}", f"Access review overdue: {ar.reference}",
            f"{ar.name} — due {ar.due_date}", _W, "access_review", ar.id,
            record_link(ar, "/access-reviews"),
            named(ar.reviewer) or directory.first_active(ar.workflow_owner_id))

    # Data-protection obligations go to the activity's approval owner, else the DPO.
    _ropa_stmt = select(ProcessingActivity).where(
        ProcessingActivity.deleted.is_(False),
        or_(
            and_(ProcessingActivity.cross_border_transfer.is_(True),
                 func.trim(ProcessingActivity.transfer_safeguard) == ""),
            and_(ProcessingActivity.dpia_required.is_(True),
                 ProcessingActivity.dpia_status != DpiaStatus.completed),
        ),
    )
    for ra in (await db.scalars(_ropa_stmt)).all():
        to = directory.first_active(ra.workflow_owner_id) or to_roles(*directory.dpo_roles())
        link = record_link(ra, "/privacy")
        if ra.has_transfer_gap:
            add(f"ropa-transfer:{ra.id}", f"Transfer gap: {ra.reference}",
                f"{ra.name} — cross-border transfer without a safeguard", _C, "processing_activity", ra.id,
                link, to)
        if ra.dpia_outstanding:
            add(f"ropa-dpia:{ra.id}", f"DPIA outstanding: {ra.reference}",
                f"{ra.name} — DPIA required but not completed", _W, "processing_activity", ra.id, link, to)

    _pol_stmt = select(Policy).where(Policy.deleted.is_(False), Policy.next_review_date < today)
    for pol in (await db.scalars(_pol_stmt)).all():
        add(f"policy-review:{pol.id}", f"Policy review overdue: {pol.reference}",
            f"{pol.title} — review was due {pol.next_review_date}", _W, "policy", pol.id,
            record_link(pol, "/policies"), directory.first_active(pol.owner_id, pol.workflow_owner_id))

    # Third parties carry their own review cycle on the record; attesting a vendor moves
    # it, so this is the one overdue alert for a vendor review.
    _vendor_stmt = select(Vendor).where(
        Vendor.deleted.is_(False),
        Vendor.status != VendorStatus.offboarded,  # as drill_through.vendor_review_overdue
        Vendor.next_review_date < today,
    )
    for v in (await db.scalars(_vendor_stmt)).all():
        add(f"vendor-review:{v.id}", f"Third-party review overdue: {v.name}",
            f"Review was due {v.next_review_date}", _W, "vendor", v.id, record_link(v, "/vendors"),
            directory.first_active(v.relationship_owner_id, v.workflow_owner_id))

    # Certifications of live third parties (not offboarded) expiring within the warning
    # window or already lapsed. Expired certs of high/critical vendors are critical.
    _cert_stmt = (
        select(VendorCertification, Vendor)
        .join(Vendor, Vendor.id == VendorCertification.vendor_id)
        .where(
            Vendor.deleted.is_(False),
            Vendor.status != VendorStatus.offboarded,
            VendorCertification.expires_on.is_not(None),
            VendorCertification.expires_on <= today + timedelta(days=CERT_EXPIRY_WARNING_DAYS),
        )
    )
    for cert, v in (await db.execute(_cert_stmt)).all():
        alert = certification_alert(cert, v, today)
        if alert is not None:
            add(*alert, to=directory.first_active(v.relationship_owner_id, v.workflow_owner_id))

    _aw_stmt = select(AwarenessProgram).where(
        AwarenessProgram.deleted.is_(False), AwarenessProgram.next_due_date < today
    )
    for aw in (await db.scalars(_aw_stmt)).all():
        add(f"aw-due:{aw.id}", f"Awareness training due: {aw.reference}",
            f"{aw.name} — due {aw.next_due_date}", _I, "awareness_program", aw.id,
            record_link(aw, "/awareness"),
            named(getattr(aw, "owner", "")) or directory.first_active(aw.workflow_owner_id))

    _proj_stmt = select(Project).where(
        Project.deleted.is_(False),
        Project.deadline < today,
        Project.status != ProjectStatus.completed,
    )
    for pr in (await db.scalars(_proj_stmt)).all():
        add(f"proj-overdue:{pr.id}", f"Project overdue: {pr.reference}",
            f"{pr.title} — deadline {pr.deadline}", _W, "project", pr.id, record_link(pr, "/projects"),
            named(pr.owner) or directory.first_active(pr.workflow_owner_id))

    # Overdue attestations — DISTINCT ON keeps only the latest attestation per record
    # (one row each instead of the full history), then alert if that latest is past due.
    # Records with a native review schedule (risk, policy, vendor) are skipped: their
    # attestation writes the record's own next_review_date, which the sweeps above
    # already watch. One review clock per record, one alert — to the record's owner.
    _att_stmt = (
        select(Attestation)
        .where(Attestation.entity_type.not_in(sorted(NATIVE_REVIEW_ENTITY_TYPES)))
        .distinct(Attestation.entity_type, Attestation.entity_id)
        .order_by(Attestation.entity_type, Attestation.entity_id, Attestation.attested_at.desc())
    )
    _due_att = [att for att in (await db.scalars(_att_stmt)).all() if att.next_due and att.next_due < today]
    _att_owners = await _record_owners(db, directory, [(a.entity_type, a.entity_id) for a in _due_att]) if _due_att else {}
    for att in _due_att:
        to, link = _att_owners.get((att.entity_type, att.entity_id), ([], link_to(att.entity_type, att.entity_id)))
        add(f"attest-overdue:{att.entity_type}:{att.entity_id}", f"Attestation overdue: {att.entity_type}",
            f"{att.entity_type} review was due {att.next_due} (last by {att.attested_by_email or 'n/a'})",
            _W, att.entity_type, att.entity_id, link, to)

    _closed_finding = [AuditFindingStatus.closed, AuditFindingStatus.risk_accepted]
    _fnd_stmt = (
        select(AuditFinding, AuditEngagement.lead_auditor)
        .join(AuditEngagement, AuditEngagement.id == AuditFinding.engagement_id)
        .where(
            AuditEngagement.deleted.is_(False),
            AuditFinding.status.not_in(_closed_finding),
            AuditFinding.due_date < today,
        )
    )
    for f, lead_auditor in (await db.execute(_fnd_stmt)).all():
        add(f"iafinding-overdue:{f.id}", f"Audit finding overdue: {f.reference}",
            f"{f.title} — remediation due {f.due_date} (owner {f.action_owner or 'n/a'})",
            _C if f.rating.value in ("high", "critical") else _W,
            "audit_finding", f.id, with_id("/internal-audit", f.engagement_id),
            named(f.action_owner, lead_auditor))

    _closed_eng = [AuditEngagementStatus.closed, AuditEngagementStatus.cancelled]
    _eng_stmt = select(AuditEngagement).where(
        AuditEngagement.deleted.is_(False),
        AuditEngagement.status.not_in(_closed_eng),
        AuditEngagement.planned_end < today,
    )
    for eng in (await db.scalars(_eng_stmt)).all():
        add(f"iaeng-overdue:{eng.id}", f"Audit engagement overdue: {eng.reference}",
            f"{eng.title} — planned completion {eng.planned_end}", _W,
            "audit_engagement", eng.id, record_link(eng, "/internal-audit"),
            named(eng.lead_auditor) or directory.first_active(eng.workflow_owner_id))

    _closed_snc = [ShariahFindingStatus.closed, ShariahFindingStatus.remediated]
    _snc_stmt = (
        select(ShariahFinding)
        .join(ShariahReview, ShariahReview.id == ShariahFinding.review_id)
        .where(
            ShariahReview.deleted.is_(False),
            ShariahFinding.status.not_in(_closed_snc),
            ShariahFinding.due_date < today,
        )
    )
    for sf in (await db.scalars(_snc_stmt)).all():
        add(f"snc-overdue:{sf.id}", f"Shariah non-compliance overdue: {sf.reference}",
            f"{sf.title} — remediation due {sf.due_date}"
            + (f"; SNC income {sf.snc_income_amount} to purify" if sf.snc_income_amount else ""),
            _C if sf.severity.value in ("high", "critical") else _W,
            "shariah_finding", sf.id, with_id("/shariah", sf.review_id), named(sf.action_owner))

    # ``KeyRiskIndicator.status`` is a Python property (it depends on the direction), so
    # it can't be filtered in SQL — comparing it there compiled to ``WHERE false`` and no
    # KRI breach alert ever fired. Narrow in SQL to KRIs that can breach (a limit, or a
    # within-range band, which is red outside it even without a tolerance), decide in
    # Python. The alert names who the red escalation goes to (phase 2) and is addressed
    # to the owner and that escalation's person and role (phase 3).
    _kri_stmt = select(KeyRiskIndicator).where(
        KeyRiskIndicator.deleted.is_(False),
        KeyRiskIndicator.current_value.is_not(None),
        or_(
            KeyRiskIndicator.limit_threshold.is_not(None),
            KeyRiskIndicator.direction == KriDirection.within_range,
        ),
    )
    _kris = [k for k in (await db.scalars(_kri_stmt)).all() if k.status == KriStatus.red]
    _kri_people = await _escalation_people(db, _kris, "red") if _kris else {}
    for kri in _kris:
        add(f"kri-breach:{kri.id}", f"KRI breach: {kri.reference}",
            kri_breach_body(kri, _kri_people),
            _C, "key_risk_indicator", kri.id, record_link(kri, "/operational-risk"),
            kri_breach_recipients(kri, directory))

    _rcsa_stmt = select(RcsaAssessment).where(
        RcsaAssessment.deleted.is_(False),
        RcsaAssessment.status != RcsaStatus.completed,
        RcsaAssessment.due_date < today,
    )
    for rc in (await db.scalars(_rcsa_stmt)).all():
        add(f"rcsa-overdue:{rc.id}", f"RCSA overdue: {rc.reference}",
            f"{rc.title} — due {rc.due_date} ({rc.business_unit or 'n/a'})",
            _W, "rcsa_assessment", rc.id, record_link(rc, "/operational-risk"),
            directory.first_active(rc.assessor_id, rc.workflow_owner_id))

    # Regulator deadlines are timestamps (phase 2): overdue from the minute they pass,
    # and the alert names the time in the organisation's timezone. To the incident's
    # assignee.
    from app.services import incident_clock

    _rr_stmt = (
        select(RegulatoryReport, Incident.assignee_id)
        .join(Incident, Incident.id == RegulatoryReport.incident_id)
        .where(
            Incident.deleted.is_(False),
            RegulatoryReport.status == RegulatoryReportStatus.pending,
            RegulatoryReport.deadline < incident_clock.now_utc(),
        )
    )
    _rr_rows = (await db.execute(_rr_stmt)).all()
    _rr_tz = await incident_clock.tenant_zone(db, tenant_id) if _rr_rows else None
    for rr, assignee_id in _rr_rows:
        add(f"regreport-overdue:{rr.id}",
            f"Regulatory report overdue: {rr.regulator} {rr.report_type.value.replace('_', ' ')}",
            f"Submission was due {incident_clock.local_text(rr.deadline, _rr_tz)}",
            _C, "regulatory_report", rr.id, with_id("/incidents", rr.incident_id),
            directory.first_active(assignee_id))

    _sar_stmt = select(SuspiciousActivityReport).where(
        SuspiciousActivityReport.deleted.is_(False),
        SuspiciousActivityReport.status.not_in([SarStatus.filed, SarStatus.closed]),
        SuspiciousActivityReport.deadline < today,
    )
    for sar in (await db.scalars(_sar_stmt)).all():
        add(f"sar-overdue:{sar.id}", f"STR/SAR filing overdue: {sar.reference}",
            f"{sar.subject} — filing was due {sar.deadline}", _C, "sar", sar.id,
            with_id("/aml", sar.id, param="sar"),
            named(sar.analyst) or directory.first_active(sar.workflow_owner_id))

    _sc_stmt = select(ScreeningCase).where(
        ScreeningCase.deleted.is_(False), ScreeningCase.status == ScreeningCaseStatus.escalated
    )
    for sc in (await db.scalars(_sc_stmt)).all():
        add(f"screening-escalated:{sc.id}", f"Screening case escalated: {sc.reference}",
            f"{sc.subject_name} — {sc.match_status.value.replace('_', ' ')}", _C, "screening_case", sc.id,
            with_id("/aml", sc.id, param="case"),
            named(sc.reviewer) or directory.first_active(sc.workflow_owner_id))

    # A pending approval goes to whoever it names (a person or a role), else to the
    # roles that may decide approval requests.
    _ap_stmt = select(ApprovalRequest).where(ApprovalRequest.status == ApprovalStatus.pending)
    for ap in (await db.scalars(_ap_stmt)).all():
        overdue = ap.due_date is not None and ap.due_date < today
        add(f"approval-pending:{ap.id}",
            f"Approval {'overdue' if overdue else 'pending'}: {ap.reference}",
            f"{ap.title} — awaiting {ap.approver or 'a decision'}",
            _W if overdue else _I, "approval", ap.id, with_id("/approvals", ap.id),
            approval_recipients(ap, directory))

    # Phase 3 — issue (CAPA) actions past due, to their owner (else the issue's owner),
    # and later due dates on serious issues waiting for someone to approve them, to the
    # roles that may approve issues.
    _open_issue = Issue.status.in_((IssueStatus2.open, IssueStatus2.in_progress))
    _ia_stmt = (
        select(IssueAction, Issue.reference, Issue.owner_id)
        .join(Issue, Issue.id == IssueAction.issue_id)
        .where(
            Issue.deleted.is_(False), _open_issue,
            IssueAction.status.in_((ActionStatus.open, ActionStatus.in_progress)),
            IssueAction.due_date < today,
        )
    )
    for ia, issue_ref, issue_owner_id in (await db.execute(_ia_stmt)).all():
        add(f"issue-action:{ia.id}", f"Issue action overdue: {issue_ref}",
            f"{ia.title} — was due {ia.due_date}", _W, "issue", ia.issue_id,
            with_id("/issues", ia.issue_id), directory.first_active(ia.owner_id, issue_owner_id))

    from app.services import record_workflow

    _issue_approvers = to_roles(*directory.roles_granting(*record_workflow.required_permissions("issue", "approve")))
    _ext_stmt = (
        select(IssueDueDateChange, Issue.reference, Issue.title)
        .join(Issue, Issue.id == IssueDueDateChange.issue_id)
        .where(Issue.deleted.is_(False), IssueDueDateChange.status == "pending")
    )
    for change, issue_ref, issue_title in (await db.execute(_ext_stmt)).all():
        requester = directory.label(change.requested_by_id) or "someone"
        add(f"issue-extension:{change.id}", f"Due-date extension awaiting approval: {issue_ref}",
            f"{issue_title} — {requester} asks to move the due date from {change.old_due_date} "
            f"to {change.new_due_date or 'no date'}: {change.reason}"[:1000],
            _W, "issue", change.issue_id, with_id("/issues", change.issue_id), _issue_approvers)

    # Turnaround-time clock. Reconciling here means the sweep both recomputes every open
    # record's window against the current policy and raises the resulting alerts in one
    # pass — an early warning while there is still time to act, and a critical alert once
    # the window has actually lapsed. Both go to the record's owner; a breach also goes
    # to the policy's escalation role (the line above the owner is told, in writing,
    # through that role's members' digests).
    from app.services import sla as sla_service

    _tat_records = await sla_service.reconcile(db, tenant_id)
    _tat = await _tat_context(db, directory, _tat_records) if _tat_records else {}
    for record in _tat_records:
        owner, link, escalation_role = _tat.get(
            (record.entity_type, record.entity_id), ([], with_id(record.link, record.entity_id), "")
        )
        if record.days_overdue > 0:
            add(
                f"tat-breach:{record.entity_type}:{record.entity_id}",
                f"TAT breached: {record.entity_label} {record.label}",
                f"{record.days_overdue} day(s) past the {record.severity} turnaround time "
                f"(due {record.due})",
                _C, record.entity_type, record.entity_id, link, owner + to_roles(escalation_role),
            )
        else:
            add(
                f"tat-at-risk:{record.entity_type}:{record.entity_id}",
                f"TAT approaching: {record.entity_label} {record.label}",
                f"Turnaround time expires {record.due}",
                _W, record.entity_type, record.entity_id, link, owner,
            )

    return alerts


# ================================================================= refresh ===
#: Minimum seconds between two scans of one organisation triggered by page loads (the
#: bell asks on every navigation). The scheduler and an explicit refresh always scan.
REFRESH_MIN_INTERVAL_SECONDS = 60.0
_LAST_REFRESH: dict[str, float] = {}


async def refresh(db: AsyncSession, tenant_id) -> list[Notification]:
    """Reconcile current alerts into the notifications table.

    Scans, addresses each alert to its recipients (:func:`address_alerts`), groups
    low-urgency families per recipient (:func:`group_alerts`), then adds new rows,
    rewrites the text of existing ones whose condition changed, and deletes resolved
    ones (:func:`reconcile_plan`). When a group shrinks back under the threshold, the
    group key stops appearing and is deleted while the individual keys come back.

    Returns the newly created notifications that are genuinely new. An updated alert is
    not new (its ``created_at`` — and so each user's seen state — is kept), and neither
    is an alert that everyone had already been shown and that is now addressed to its
    owner. Event rows (``EVENT_PREFIX``) are written by the module that observed the
    event and are never swept: this reconciler runs whenever the feed is opened.
    """
    directory = await load_directory(db)
    alerts = group_alerts(address_alerts(await scan_alerts(db, tenant_id, directory=directory), directory))

    existing: dict[str, Notification] = {}
    for n in (await db.scalars(select(Notification).order_by(Notification.created_at))).all():
        if n.dedup_key in existing and not n.dedup_key.startswith(EVENT_PREFIX):
            await db.delete(n)  # a duplicate left by two scans racing; keep the oldest
            continue
        existing[n.dedup_key] = n

    plan = reconcile_plan(existing, alerts, keep_prefix=EVENT_PREFIX)
    for row, changes in plan.updates:
        for field_name, value in changes.items():
            setattr(row, field_name, value)
    created: list[Notification] = []
    for a, carried in plan.creates:
        n = Notification(
            tenant_id=tenant_id,
            user_id=a.get("user_id"),
            role_name=a.get("role_name") or "",
            title=a["title"][:255],
            body=a["body"],
            category=a["category"],
            entity_type=a["entity_type"],
            entity_id=a["entity_id"],
            link=(a["link"] or "")[:255],
            dedup_key=a["dedup_key"][:255],
        )
        if carried is not None:
            n.created_at = carried
        else:
            created.append(n)
        db.add(n)
    for key in plan.deletes:
        await db.delete(existing[key])
    await db.flush()
    _LAST_REFRESH[str(tenant_id)] = time.monotonic()
    return created


async def refresh_if_stale(
    db: AsyncSession, tenant_id, *, max_age: float = REFRESH_MIN_INTERVAL_SECONDS
) -> bool:
    """Refresh unless this process scanned the organisation less than ``max_age``
    seconds ago. Returns whether it scanned."""
    last = _LAST_REFRESH.get(str(tenant_id))
    if last is not None and time.monotonic() - last < max_age:
        return False
    await refresh(db, tenant_id)
    return True
