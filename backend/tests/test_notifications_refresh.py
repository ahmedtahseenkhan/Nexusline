"""The alert feed once real data is in it: grouping housekeeping, keeping text current.

Pure functions only — no database. ``group_alerts`` decides what collapses into one row;
``alert_changes`` decides what an existing row must be rewritten to; ``keys_to_delete``
is the reconcile rule that makes a group disappear once it shrinks back under the
threshold.
"""
import uuid
from types import SimpleNamespace

from app.models.enums import NotificationCategory
from app.services import notifications as ns

W = NotificationCategory.warning
C = NotificationCategory.critical
I = NotificationCategory.info  # noqa: E741


def _alert(family: str, ref: str, *, category=W, etype="control", link="/controls", body="", eid=None):
    return {
        "dedup_key": f"{family}:{eid or uuid.uuid4()}",
        "title": f"Something overdue: {ref}",
        "body": body or f"{ref} was due",
        "category": category,
        "entity_type": etype,
        "entity_id": eid or uuid.uuid4(),
        "link": link,
    }


def _many(family, n, **kw):
    return [_alert(family, f"C-{i:03d}", **kw) for i in range(1, n + 1)]


# ------------------------------------------------------------------- grouping ---
def test_up_to_the_threshold_alerts_stay_individual():
    alerts = _many("control-audit", ns.GROUP_THRESHOLD)
    assert ns.group_alerts(alerts) == alerts


def test_above_the_threshold_a_housekeeping_family_becomes_one_row():
    alerts = _many("control-audit", 36)
    out = ns.group_alerts(alerts)
    assert len(out) == 1
    g = out[0]
    assert g["dedup_key"] == "group:control-audit"
    assert g["title"] == "36 controls have tests overdue"
    assert g["link"] == "/controls"
    assert g["entity_id"] is None
    # Up to five examples, then how many more.
    assert g["body"] == "Including C-001, C-002, C-003, C-004, C-005 and 31 more."


def test_the_group_key_is_stable_across_scans():
    """Same family, different members and count: same key, so refresh updates in place."""
    a = ns.group_alerts(_many("control-audit", 12))[0]
    b = ns.group_alerts(_many("control-audit", 20))[0]
    assert a["dedup_key"] == b["dedup_key"]


def test_families_group_independently_and_order_is_kept():
    breach = _alert("risk-breach", "R-117", category=C, etype="risk", link="/risks")
    alerts = [breach] + _many("control-audit", 7) + [_alert("policy-review", "POL-1", etype="policy")]
    out = ns.group_alerts(alerts)
    assert [a["dedup_key"].split(":")[0] for a in out] == ["risk-breach", "group", "policy-review"]


def test_alerts_that_matter_are_never_grouped():
    """Breaches, TAT, approvals and attestations always render one row per record."""
    for fam in ("risk-breach", "tat-breach", "tat-at-risk", "approval-pending", "attest-overdue",
                "regreport-overdue", "sar-overdue", "kri-breach", "exc-expired"):
        alerts = _many(fam, 40, category=C)
        assert ns.group_alerts(alerts) == alerts, fam
        assert fam in ns.NEVER_GROUPED
        assert fam not in ns.GROUPABLE_FAMILIES


def test_an_unknown_family_is_never_grouped():
    alerts = _many("brand-new-family", 50)
    assert ns.group_alerts(alerts) == alerts


def test_the_grouped_row_takes_its_most_urgent_member_category():
    alerts = _many("aw-due", 6, category=I, etype="awareness_program", link="/awareness")
    assert ns.group_alerts(alerts)[0]["category"] == I
    alerts[3]["category"] = W
    assert ns.group_alerts(alerts)[0]["category"] == W


def test_singular_wording():
    out = ns.group_alerts(_many("policy-review", 6, etype="policy"), threshold=0)
    assert out[0]["title"] == "6 policies have reviews overdue"
    one = ns.group_alerts(_many("policy-review", 1, etype="policy"), threshold=0)
    assert one[0]["title"] == "1 policy has reviews overdue"


def test_when_the_group_shrinks_the_individual_rows_return_and_the_group_goes():
    """Six overdue collapse into a group; one is tested and five remain. The next scan
    yields the five individual keys, so reconcile deletes the group row and inserts the
    five (none of which were stored while grouped)."""
    six = _many("control-audit", 6)
    stored = {a["dedup_key"] for a in ns.group_alerts(six)}
    assert stored == {"group:control-audit"}

    five = ns.group_alerts(six[:5])
    current = {a["dedup_key"] for a in five}
    assert "group:control-audit" not in current
    assert ns.keys_to_delete(stored, current) == ["group:control-audit"]
    assert current - stored == {a["dedup_key"] for a in six[:5]}


def test_event_notifications_are_never_swept():
    stored = ["event:workflow:1", "control-audit:abc", "group:control-audit"]
    assert ns.keys_to_delete(stored, set()) == ["control-audit:abc", "group:control-audit"]


# ------------------------------------------------------------ refresh diffs ---
def _row(**kw):
    base = dict(title="Risk above tolerance: R-117", body="Card fraud — score 15 exceeds tolerance 12",
                category=C, link="/risks", entity_type="risk", entity_id=None)
    return SimpleNamespace(**{**base, **kw})


def test_an_unchanged_alert_needs_no_update():
    eid = uuid.uuid4()
    row = _row(entity_id=eid)
    alert = {"dedup_key": f"risk-breach:{eid}", "title": row.title, "body": row.body,
             "category": C, "link": "/risks", "entity_type": "risk", "entity_id": eid}
    assert ns.alert_changes(row, alert) == {}


def test_a_rescored_risk_rewrites_the_body():
    """D-05a: the alert said R-117 scores 15 long after it had been rescored to 20."""
    eid = uuid.uuid4()
    row = _row(entity_id=eid)
    alert = {"dedup_key": f"risk-breach:{eid}", "title": row.title,
             "body": "Card fraud — score 20 exceeds tolerance 12",
             "category": C, "link": "/risks", "entity_type": "risk", "entity_id": eid}
    assert ns.alert_changes(row, alert) == {"body": "Card fraud — score 20 exceeds tolerance 12"}


def test_title_category_and_link_changes_are_picked_up():
    row = _row(title="Approval pending: APR-1", category=I, link="/approvals", entity_type="approval")
    alert = {"title": "Approval overdue: APR-1", "body": row.body, "category": W,
             "link": "/approvals", "entity_type": "approval", "entity_id": None}
    assert ns.alert_changes(row, alert) == {"title": "Approval overdue: APR-1", "category": W}


def test_category_compares_by_value_so_a_stored_string_is_not_a_change():
    row = _row(category="critical")
    alert = {"title": row.title, "body": row.body, "category": C, "link": row.link,
             "entity_type": row.entity_type, "entity_id": None}
    assert ns.alert_changes(row, alert) == {}


def test_a_grouped_alert_count_change_updates_title_and_body():
    stored = ns.group_alerts(_many("control-audit", 12))[0]
    row = SimpleNamespace(**stored)
    fresh = ns.group_alerts(_many("control-audit", 20))[0]
    changes = ns.alert_changes(row, fresh)
    assert changes["title"] == "20 controls have tests overdue"
    assert "body" in changes
    assert set(changes) <= set(ns.REFRESHED_FIELDS)


# ----------------------------------------------------- one review clock per record ---
def test_native_review_types_are_the_ones_with_their_own_sweep():
    assert ns.NATIVE_REVIEW_ENTITY_TYPES == {"risk", "policy", "vendor", "asset"}
    for fam in ("risk-review", "policy-review", "vendor-review", "asset-review", "itasset-review"):
        assert fam in ns.GROUPABLE_FAMILIES
