"""Drill-through: every dashboard number opens the list behind it (product review 3.2, F-15).

No database: the shared predicates (``services.drill_through``) are compiled to
PostgreSQL and read; the list endpoints are driven with a fake session that records the
statement they count with; the dashboard's links are checked against the parameters
each list endpoint actually declares.

Pinned here:

1. **One predicate, two users.** The dashboard counts and the list filters with the same
   function — never tested, tests overdue / due / failed (latest reviewed or pre-review
   test), open incidents, issues past due, policy and third-party reviews overdue.
2. **The lists accept what the dashboard links to.** Every queue link and tile link names
   a parameter its list endpoint declares, with a value that endpoint accepts.
3. **Fixes found on the way.** "Remediated" issues are no longer counted as open on the
   dashboard (the register's overdue filter never did); open incidents include triage,
   investigating and contained (``?open=true``; ``?status=open`` is the literal status).
"""
from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.api.v1 import controls as controls_api
from app.api.v1 import dashboard
from app.api.v1 import incidents as incidents_api
from app.api.v1 import issues as issues_api
from app.api.v1 import policies as policies_api
from app.api.v1 import vendors as vendors_api
from app.models.control import Control
from app.models.enums import Criticality
from app.models.incident import Incident
from app.models.issue import Issue
from app.models.policy import Policy
from app.models.risk import Risk
from app.models.vendor import Vendor
from app.services import drill_through as dt

TODAY = date(2026, 9, 12)


def sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def where(model, clause) -> str:
    """The WHERE clause of ``SELECT id FROM <model> WHERE <clause>``, compiled."""
    return sql(select(model.id).where(clause)).split("WHERE", 1)[1]


# ===================================================================== controls ===
def test_rating_filters_count_operating_controls_only():
    for value in ("assured", "effective", "partially_effective", "failing", "not_assessed"):
        text = where(Control, dt.control_assurance_clause(value))
        assert "controls.status NOT IN ('planned', 'retired')" in text, value
    assert "controls.effectiveness = 'not_assessed'" in where(Control, dt.control_assurance_clause("not_assessed"))
    assert "controls.effectiveness = 'ineffective'" in where(Control, dt.control_assurance_clause("failing"))
    assured = where(Control, dt.control_assurance_clause("assured"))
    assert "'effective'" in assured and "'partially_effective'" in assured and "'ineffective'" not in assured


def test_not_operating_is_planned_or_retired():
    text = where(Control, dt.control_assurance_clause("not_operating"))
    assert "controls.status IN ('planned', 'retired')" in text and "effectiveness" not in text


def test_unmapped_means_no_live_clause_of_a_live_framework():
    text = where(Control, dt.control_assurance_clause("unmapped"))
    assert text.strip().startswith("NOT (EXISTS")
    assert "requirement_controls.control_id = controls.id" in text
    assert "requirements.deleted IS false" in text and "frameworks.deleted IS false" in text


def test_test_filters():
    overdue = where(Control, dt.control_test_clause("overdue", TODAY))
    assert "controls.next_audit_date < '2026-09-12'" in overdue
    assert "controls.status NOT IN ('planned', 'retired')" in overdue
    due = where(Control, dt.control_test_clause("due_30d", TODAY))
    assert "controls.next_audit_date >= '2026-09-12'" in due
    assert f"controls.next_audit_date <= '{TODAY + timedelta(days=30)}'" in due


def test_failed_is_the_latest_test_that_counts():
    text = where(Control, dt.control_test_clause("failed", TODAY))
    assert "DISTINCT ON (control_audits.control_id)" in text
    assert "control_audits.review_status IN ('reviewed', 'legacy')" in text
    assert "control_audits.conducted_date DESC NULLS LAST" in text
    assert "result = 'failed'" in text
    assert "controls.status NOT IN ('planned', 'retired')" in text


def test_unknown_values_are_refused():
    with pytest.raises(ValueError):
        dt.control_assurance_clause("covered")
    with pytest.raises(ValueError):
        dt.control_test_clause("late", TODAY)


# ============================================================== other registers ===
def test_open_issue_excludes_every_closed_state():
    # The dashboard used to treat "remediated" as open; the register never did.
    text = where(Issue, dt.issue_open())
    for state in ("closed", "remediated", "risk_accepted"):
        assert f"'{state}'" in text
    overdue = where(Issue, dt.issue_overdue(TODAY))
    assert "issues.due_date IS NOT NULL" in overdue and "issues.due_date < '2026-09-12'" in overdue


def test_open_incidents_include_every_unresolved_status():
    text = where(Incident, dt.incident_open())
    assert "incidents.status NOT IN ('resolved', 'closed')" in text and "triage" not in text


def test_policy_review_overdue_is_for_policies_in_force():
    text = where(Policy, dt.policy_review_overdue(TODAY))
    assert "policies.status IN ('approved', 'published')" in text
    assert "policies.next_review_date < '2026-09-12'" in text


def test_vendor_review_overdue():
    assert "vendors.next_review_date < '2026-09-12'" in where(Vendor, dt.vendor_review_overdue(TODAY))


def test_risk_predicates_are_the_registers():
    # The dashboard counts risk treatment with the risk register's own predicate.
    from app.services import risk_query

    assert sql(dt.risk_treatment_overdue(TODAY)) == sql(risk_query.treatment_overdue_clause(TODAY))
    assert "risks.next_review_date < '2026-09-12'" in where(Risk, dt.risk_review_overdue(TODAY))
    text = where(Risk, dt.risk_treatment_overdue(TODAY))
    assert "risks.status NOT IN ('accepted', 'closed')" in text
    assert "risk_treatment_actions.status IN ('open', 'in_progress')" in text
    assert "risk_treatment_actions.due_date < '2026-09-12'" in text
    assert "risks.treatment_deadline < '2026-09-12'" in text


# ======================================================================= links ===
def test_href():
    assert dt.href("/controls", test="overdue") == "/controls?test=overdue"
    assert dt.href("/issues", overdue=True) == "/issues?overdue=true"
    assert dt.href("/vendors", review=None) == "/vendors"


def test_queue_lines_link_to_their_filtered_lists():
    items = dashboard.action_items({"not_assessed": 98, "breach": 1, "tests_overdue": 0, "issues_overdue": 4})
    assert [i.key for i in items] == ["breach", "issues_overdue", "not_assessed"]  # priority order, zeros left out
    by_key = {i.key: i for i in items}
    assert by_key["not_assessed"].label == "98 controls never tested"
    assert by_key["not_assessed"].href == "/controls?assurance=not_assessed"
    assert by_key["breach"].label == "1 risk above tolerance"
    assert by_key["breach"].href == "/risks?appetite=breach"
    assert by_key["issues_overdue"].href == "/issues?overdue=true"
    assert set(dt.ACTION_LINKS) == {k for k, *_ in dashboard.QUEUE}


def test_treatment_line_counts_risks_because_it_opens_the_risk_list():
    (item,) = dashboard.action_items({"treatments_overdue": 3})
    assert item.label == "3 risks with treatment past due"
    assert item.href == "/risks?treatment_overdue=true"


# ------------------------------------------- the lists accept what is linked to ---
def _declared(path: str) -> dict[str, dict]:
    from app.main import app

    op = app.openapi()["paths"][f"/api/v1{path}"]["get"]
    return {p["name"]: p.get("schema", {}) for p in op.get("parameters", [])}


def _values(schema: dict) -> set:
    """The fixed values a query parameter accepts (``enum`` or a single ``const``)."""
    out: set = set()
    for s in schema.get("anyOf", [schema]):
        out |= set(s.get("enum", []))
        if "const" in s:
            out.add(s["const"])
    return out


def _accepts(schema: dict, value: str) -> bool:
    options = schema.get("anyOf", [schema])
    for s in options:
        if value in _values(s):
            return True
        if "enum" in s or "const" in s:
            continue
        if s.get("type") == "boolean" and value in ("true", "false"):
            return True
        if s.get("type") == "string" and "pattern" in s:
            if re.fullmatch(s["pattern"].strip("^$"), value):
                return True
            continue
        if s.get("type") == "string":
            return True
        if "$ref" in s:  # an enum schema by reference (e.g. Criticality)
            return True
    return False


_PAGES = Path(__file__).resolve().parents[2] / "frontend" / "app" / "(app)"


def _frontend_links() -> set[str]:
    page = _PAGES / "dashboard" / "page.tsx"
    if not page.exists():
        return set()
    return set(re.findall(r'"(/[a-z-]+\?[^"$`{}]+)"', page.read_text(encoding="utf-8")))


def _page_filters(path: str) -> set[str] | None:
    """The URL filters a register page reads: the keys of its ``*_FILTERS = {…} as const
    satisfies FilterSpec`` declaration (lib/useFilterParams.ts). None without the frontend."""
    page = _PAGES / path.strip("/") / "page.tsx"
    if not page.exists():
        return None
    out: set[str] = set()
    for block in re.findall(r"_FILTERS = \{(.*?)\} as const satisfies FilterSpec", page.read_text(encoding="utf-8"), re.S):
        out |= set(re.findall(r"^\s*([a-z_]+):", block, re.M))
    return out


#: Owned by the risk register, which lands its own filters; checked once it declares them.
_RISK_REGISTER = {"/risks"}


@pytest.mark.parametrize("link", sorted(set(dt.ACTION_LINKS.values()) | _frontend_links()))
def test_every_dashboard_link_is_a_filter_its_list_accepts(link):
    parts = urlsplit(link)
    params = dict(parse_qsl(parts.query))
    if not params:
        return
    declared = _declared(parts.path)
    for name, value in params.items():
        if name not in declared and parts.path in _RISK_REGISTER:
            pytest.skip(f"GET {parts.path} does not declare '{name}' yet (risk register filter)")
        assert name in declared, f"{link}: GET {parts.path} has no '{name}' filter"
        if name == "id" or name.endswith("_id"):
            continue
        assert _accepts(declared[name], value), f"{link}: '{value}' is not a value '{name}' accepts"


@pytest.mark.parametrize("link", sorted(set(dt.ACTION_LINKS.values()) | _frontend_links()))
def test_every_dashboard_link_is_read_by_its_page(link):
    """The page behind a link reads the filter from the URL, so it opens filtered."""
    parts = urlsplit(link)
    params = dict(parse_qsl(parts.query))
    if not params:
        return
    read = _page_filters(parts.path)
    if read is None:
        pytest.skip("frontend sources not present")
    for name in params:
        if name not in read and parts.path in _RISK_REGISTER:
            pytest.skip(f"the risk register page does not read '{name}' from the URL yet")
        assert name in read, f"{link}: the {parts.path} page does not read '{name}' from the URL"


# ==================================================== the endpoints filter with it ===
class RecordingDB:
    """Records every statement; returns nothing. Enough for a list endpoint's count."""

    def __init__(self):
        self.statements = []

    async def scalar(self, stmt, *a, **k):
        self.statements.append(stmt)
        return 0

    async def scalars(self, stmt, *a, **k):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [])

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        return SimpleNamespace(all=lambda: [], scalars=lambda: SimpleNamespace(all=lambda: []))

    async def get(self, *a, **k):
        return None

    def counted(self) -> str:
        """The WHERE clause of the statement the endpoint counted its total with."""
        return sql(self.statements[0]).split("WHERE", 1)[-1]


def _defaults(fn, **given):
    """Call a FastAPI endpoint function directly: resolve its Query() defaults."""
    import inspect

    from fastapi.params import Param

    out = {}
    for name, p in inspect.signature(fn).parameters.items():
        if name in given or name == "db":
            continue
        default = p.default
        if isinstance(default, Param):
            default = default.default
        out[name] = default
    out.update(given)
    return out


async def _list(fn, **given) -> str:
    db = RecordingDB()
    await fn(db=db, **_defaults(fn, **given))
    return db.counted()


async def test_controls_list_filters_with_the_shared_predicates():
    text = await _list(controls_api.list_controls, assurance="not_assessed")
    assert "controls.effectiveness = 'not_assessed'" in text
    assert "controls.status NOT IN ('planned', 'retired')" in text
    text = await _list(controls_api.list_controls, test="failed")
    assert "DISTINCT ON (control_audits.control_id)" in text
    text = await _list(controls_api.list_controls, key=True)
    assert "controls.is_key IS true" in text
    # is_key wins over the key alias when both are sent.
    assert "controls.is_key IS false" in await _list(controls_api.list_controls, key=True, is_key=False)


async def test_issues_overdue_filter_is_the_dashboard_predicate():
    text = await _list(issues_api.list_issues, overdue=True)
    assert "'remediated'" in text and "issues.due_date <" in text


async def test_incidents_open_filter():
    assert "incidents.status NOT IN ('resolved', 'closed')" in await _list(incidents_api.list_incidents, open_only=True)
    text = await _list(incidents_api.list_incidents, open_only=False)
    assert "NOT (incidents.status NOT IN ('resolved', 'closed'))" in text or "incidents.status IN ('resolved', 'closed')" in text
    assert "resolved" not in await _list(incidents_api.list_incidents)


async def test_policies_review_overdue_filter():
    text = await _list(policies_api.list_policies, review="overdue")
    assert "policies.status IN ('approved', 'published')" in text and "policies.next_review_date <" in text
    assert "next_review_date" not in await _list(policies_api.list_policies)


async def test_vendors_review_and_criticality_filters():
    assert "vendors.next_review_date <" in await _list(vendors_api.list_vendors, review="overdue")
    assert "vendors.criticality = 'critical'" in await _list(vendors_api.list_vendors, criticality=Criticality.critical)
    plain = await _list(vendors_api.list_vendors)
    assert "criticality" not in plain and "next_review_date" not in plain


def test_filter_vocabularies_are_validated_by_the_endpoints():
    declared = _declared("/controls")
    assert _values(declared["assurance"]) == set(dt.CONTROL_ASSURANCE)
    assert _values(declared["test"]) == set(dt.CONTROL_TEST)
    assert _values(_declared("/policies")["review"]) == {"overdue"}
    assert _values(_declared("/vendors")["review"]) == {"overdue"}
    assert "open" in _declared("/incidents")


# ========================================================== bulk map (controls) ===
class MapDB:
    """Serves requirements and controls to the bulk-map endpoint; records nothing else."""

    def __init__(self, requirements, controls):
        self.requirements, self.controls = requirements, controls
        self.calls = 0

    async def scalars(self, stmt, *a, **k):
        self.calls += 1
        rows = self.requirements if self.calls == 1 else self.controls
        return SimpleNamespace(all=lambda: rows)


async def test_bulk_map_refuses_unknown_requirements():
    from app.schemas.bulk import BulkMapRequirementsBody

    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), email="u@x", permission_codes=["control:write"])
    body = BulkMapRequirementsBody(control_ids=[uuid.uuid4()], requirement_ids=[uuid.uuid4()])
    with pytest.raises(HTTPException) as exc:
        await controls_api.bulk_map_requirements(body, MapDB([], []), user)
    assert exc.value.status_code == 422 and "requirement_ids" in exc.value.detail


async def test_bulk_map_links_live_controls_and_skips_the_rest(monkeypatch):
    from app.schemas.bulk import BulkMapRequirementsBody

    tenant = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, email="u@x", permission_codes=["control:write"])
    req = SimpleNamespace(id=uuid.uuid4(), reference="A.8.5", title="Secure authentication",
                          framework=SimpleNamespace(name="ISO 27001"))
    live = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, reference="C-1", name="MFA", deleted=False)
    mapped = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, reference="C-2", name="SSO", deleted=False)
    archived = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant, reference="C-3", name="Old", deleted=True)
    elsewhere = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), reference="X", name="X", deleted=False)
    missing = uuid.uuid4()

    async def fake_link(db, pairs):
        pairs = list(pairs)
        assert {c for c, _ in pairs} == {live.id, mapped.id}  # archived / other tenant never linked
        return [(live, req)]  # C-2 already carried the link

    audited = []

    async def fake_record(db, **kw):
        audited.append(kw)

    monkeypatch.setattr(controls_api.clause_suggestions, "link", fake_link)
    monkeypatch.setattr(controls_api.audit_log, "record", fake_record)
    body = BulkMapRequirementsBody(
        control_ids=[live.id, mapped.id, archived.id, elsewhere.id, missing], requirement_ids=[req.id],
    )
    result = await controls_api.bulk_map_requirements(body, MapDB([req], [live, mapped, archived, elsewhere]), user)
    outcome = {r.id: (r.outcome, r.reason) for r in result.results}
    assert outcome[live.id] == ("updated", "")
    assert outcome[mapped.id] == ("skipped", "already mapped")
    assert outcome[archived.id] == ("skipped", "archived")
    assert outcome[elsewhere.id] == ("skipped", "not found")
    assert outcome[missing] == ("skipped", "not found")
    assert result.updated == 1 and result.skipped == 4
    assert result.summary == "Updated 1; 4 skipped: 2 not found, 1 already mapped, 1 archived"
    (entry,) = audited
    assert entry["entity_id"] == live.id and entry["action"] == "map_requirements"
    assert entry["changes"]["batch_id"] == result.batch_id
    assert "A.8.5 (ISO 27001)" in entry["summary"]
