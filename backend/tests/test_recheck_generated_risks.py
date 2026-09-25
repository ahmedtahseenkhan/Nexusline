"""Generated risks after the re-check of 17 September 2026 (F-04, F-24).

No database: the pure rules are tested directly and the endpoints and loaders are driven
with a scripted session (every statement is compiled for PostgreSQL, so a malformed
query fails here).

Pinned here:

1. **Asset kinds** — every asset gets a kind from its media type, tags, name and
   technical identifiers; business functions (core banking, payments, channels) come
   from the name, tags and media type only, and never attach to network devices.
2. **The filter** — a scenario names the kinds it fits: fraud, AML and ransomware are
   never proposed for a firewall; an unclassified asset is filtered by class alone; the
   preview counts what it left out. Installed templates take the library's kinds only
   while they are still the library scenario.
3. **Title vs asset** — a generated-style title naming an asset the risk does not link
   (R-116 "Ransomware encrypts Firewall" on Core Banking Server) is flagged for review,
   and the flag clears once fixed.
4. **Legacy migration** — pre-queue generated risks are recognised, kept when a person
   has worked on them (with the reason), dropped when they do not fit, and otherwise
   grouped by the queue's key into new or waiting candidates; moved and dropped risks
   are archived with an activity entry. Each risk gives ``_legacy_keys`` one key.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401 - registers every mapper before the services import them
from app.api.v1 import risk_scenarios as api
from app.models.enums import AssetClass, Criticality
from app.models.risk_scenario import RiskProposal as ProposalRow
from app.schemas.risk_scenario import ScenarioCreate, ScenarioRead, ScenarioUpdate
from app.services import legacy_risk_migration as lm
from app.services import risk_integrity
from app.services.risk_scenarios import (
    ASSET_KIND_VALUES,
    CATALOGUE,
    FITS,
    WRONG_CLASS,
    WRONG_KIND,
    AssetFacts,
    KeyOwner,
    Placement,
    applies_to_asset,
    classify_asset,
    dedupe_key,
    library_kinds_for,
    parse_kinds,
    scenario_fit,
    title_patterns,
)

IT, INFO = AssetClass.it_asset.value, AssetClass.information_asset.value
M = Criticality.medium
PAY, RETAIL = uuid.uuid4(), uuid.uuid4()
BY_REF = {s.reference: s for s in CATALOGUE}


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _facts(name: str, asset_class: str = IT, **kw) -> AssetFacts:
    return AssetFacts(name, asset_class, M, M, M, M, M, classify_asset(asset_class=asset_class, name=name, **kw))


def _refs(facts: AssetFacts) -> set[str]:
    return {s.reference for s in CATALOGUE if applies_to_asset(s, facts)}


# ================================================================== asset kinds ===
@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        (dict(asset_class=IT, name="Firewall"), {"network_device"}),
        (dict(asset_class=IT, name="Perimeter FW", manufacturer="Fortinet"), {"network_device"}),
        (dict(asset_class=IT, name="Payments Firewall", media_type="Network"), {"network_device"}),
        (dict(asset_class=IT, name="Core Banking Server"), {"server", "core_banking"}),
        (dict(asset_class=IT, name="T24 Primary", media_type="Hardware"), {"server", "core_banking"}),
        (dict(asset_class=IT, name="HR laptop 23", media_type="Hardware"), {"end_user_device"}),
        (dict(asset_class=IT, name="ATM Fleet", media_type="Hardware"), {"end_user_device", "customer_channel"}),
        (dict(asset_class=IT, name="Mobile Banking App", media_type="Software"), {"application", "customer_channel"}),
        (dict(asset_class=IT, name="Oracle Database", media_type="Software"), {"database"}),
        (dict(asset_class=IT, name="Card Switch"), {"it_other", "payment_system"}),
        (dict(asset_class=IT, name="Office 365", media_type="IT Service"), {"cloud_service"}),
        (dict(asset_class=IT, name="Karachi Data Centre", media_type="Facilities"), {"facility"}),
        (dict(asset_class=IT, name="Asset 42"), {"it_other"}),
        (dict(asset_class=INFO, name="Board minutes", media_type="Data Asset"), {"information"}),
        (dict(asset_class=INFO, name="Customer master file"), {"information", "customer_data"}),
        (dict(asset_class=INFO, name="Loan book", data_categories="PII, financial"), {"information", "customer_data"}),
        (dict(asset_class=INFO, name="Treasury deals", media_type="Financial"), {"information", "customer_data"}),
    ],
)
def test_every_asset_gets_its_kinds(kw, expected):
    assert classify_asset(**kw) == frozenset(expected)


def test_description_hostname_and_location_tags_never_add_a_business_function():
    # A firewall "protecting core banking", named cbs-fw-01, is still only a firewall;
    # a server tagged DC-Karachi is not a building.
    assert classify_asset(asset_class=IT, name="Edge firewall", hostname="cbs-fw-01") == {"network_device"}
    assert classify_asset(asset_class=IT, name="app-01", media_type="Hardware", tags=["DC-Karachi", "prod"]) == {"server"}
    assert classify_asset(asset_class=IT, name="Switch 7", media_type="Hardware") == {"network_device"}
    # "Payment switch" and "card switch" are payment systems, not network switches.
    assert "network_device" not in classify_asset(asset_class=IT, name="Payment switch")


def test_every_kind_the_catalogue_uses_is_in_the_vocabulary_and_every_kind_is_used():
    used = {k for s in CATALOGUE for k in s.asset_kinds}
    assert used <= ASSET_KIND_VALUES
    assert used == ASSET_KIND_VALUES
    assert all(s.asset_kinds for s in CATALOGUE), "every library scenario names its kinds"


def test_parse_kinds_normalises_and_reports_unknown_spellings():
    assert parse_kinds(" Payment_System, core_banking,payment_system,, ") == (("core_banking", "payment_system"), [])
    assert parse_kinds("server, toaster") == (("server",), ["toaster"])


# =================================================================== the filter ===
def test_fraud_aml_and_ransomware_are_not_proposed_for_a_firewall():
    firewall = _facts("Firewall")
    for ref in ("RS-011", "RS-040", "RS-041", "RS-042", "RS-005", "RS-038"):
        assert not applies_to_asset(BY_REF[ref], firewall), ref
    # It gets availability, configuration and intrusion scenarios.
    assert {"RS-013", "RS-014", "RS-016", "RS-018", "RS-023", "RS-027"} <= _refs(firewall)
    assert scenario_fit(BY_REF["RS-040"], firewall) == WRONG_KIND


def test_financial_crime_only_where_money_moves_or_customer_data_lives():
    for kinds in (s.asset_kinds for s in CATALOGUE if s.category == "Financial Crime"):
        assert set(kinds) <= {"core_banking", "payment_system", "customer_channel", "customer_data"}
    assert {"RS-040", "RS-041", "RS-042"} <= _refs(_facts("Core Banking Server"))
    assert {"RS-040", "RS-041", "RS-042"} <= _refs(_facts("RAAST gateway", media_type="Software"))
    assert "RS-040" in _refs(_facts("Customer master file", INFO))
    assert not {"RS-040", "RS-041", "RS-042"} & _refs(_facts("HR laptop", media_type="Hardware"))
    assert not {"RS-040", "RS-041", "RS-042"} & _refs(_facts("Asset 42"))


def test_class_is_still_checked_first_and_an_unclassified_asset_uses_class_alone():
    spec = BY_REF["RS-012"]  # IT only
    assert scenario_fit(spec, _facts("Customer master file", INFO)) == WRONG_CLASS
    bare = AssetFacts("Firewall", IT, M, M, M, M, M)  # no kinds: generation before kinds
    assert scenario_fit(BY_REF["RS-040"], bare) == FITS


def test_every_kind_of_asset_still_gets_a_useful_register():
    for facts in (_facts("Firewall"), _facts("Core Banking Server"), _facts("Asset 42"),
                  _facts("Board minutes", INFO), _facts("Mobile Banking App", media_type="Software")):
        assert len(_refs(facts)) >= 15, facts.name
    assert {"RS-022", "RS-034", "RS-035"} == _refs(_facts("Head office", media_type="Facilities"))


def test_library_kinds_fill_only_rows_that_are_still_the_library_scenario():
    spec = BY_REF["RS-040"]
    row = SimpleNamespace(
        title=spec.title, category=spec.category, asset_classes="", threat=spec.threat,
        vulnerability=spec.vulnerability, asset_kinds="", likelihood=5, description="retuned",
    )
    assert library_kinds_for(row, spec) == "core_banking,customer_channel,customer_data,payment_system"
    assert library_kinds_for(SimpleNamespace(**{**vars(row), "asset_kinds": "server"}), spec) is None
    assert library_kinds_for(SimpleNamespace(**{**vars(row), "title": "Staff fraud via {asset}"}), spec) is None
    assert library_kinds_for(SimpleNamespace(**{**vars(row), "asset_classes": "it_asset"}), spec) is None


def test_scenario_payloads_validate_and_normalise_kinds():
    body = ScenarioCreate(title="X {asset}", asset_kinds="Server, network_device,server")
    assert body.asset_kinds == "network_device,server"
    with pytest.raises(ValidationError) as exc:
        ScenarioUpdate(asset_kinds="server, toaster")
    assert "toaster" in str(exc.value)
    assert ScenarioUpdate(asset_kinds="").asset_kinds == ""
    assert ScenarioUpdate().asset_kinds is None
    read = ScenarioRead.model_validate(SimpleNamespace(
        id=_id(), reference="RS-1", created_at=datetime.now(timezone.utc), title="t", description="",
        category="", asset_classes="", asset_kinds="retired_kind", threat="", vulnerability="", likelihood=3,
        impact_rule="fixed", impact_property="", fixed_impact=3, treatment_hint="", control_references="",
        enabled=True,
    ))
    assert read.asset_kinds == "retired_kind"  # a stored row is read as it is


def test_a_template_row_carries_its_kinds_into_the_engine():
    row = SimpleNamespace(
        reference="RS-040", title="Internal fraud committed through {asset}", description="", category="Financial Crime",
        asset_classes="", asset_kinds="payment_system, core_banking", threat="t", vulnerability="v", likelihood=2,
        impact_rule="from_criticality", impact_property="", fixed_impact=0, treatment_hint="", control_references="",
    )
    assert api._spec(row).asset_kinds == ("core_banking", "payment_system")
    assert api._spec(SimpleNamespace(**{k: v for k, v in vars(row).items() if k != "asset_kinds"})).asset_kinds == ()


# ------------------------------------------------------------- scripted session ---
class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _Nested:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class ScriptedDB:
    """Compiles each statement for PostgreSQL and answers it from ``answer(sql)``."""

    def __init__(self, answer=None):
        self.answer = answer or (lambda sql: [])
        self.sql: list[str] = []
        self.added: list = []

    def _run(self, stmt):
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        self.sql.append(sql)
        return self.answer(sql)

    async def execute(self, stmt):
        return _Rows(self._run(stmt))

    async def scalars(self, stmt):
        return _Rows(self._run(stmt))

    async def scalar(self, stmt):
        rows = self._run(stmt)
        return rows[0] if rows else None

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    def begin_nested(self):
        return _Nested(self)


def _template(ref: str, **kw):
    spec = BY_REF[ref]
    base = dict(
        id=_id(), reference=spec.reference, title=spec.title, description=spec.description, category=spec.category,
        asset_classes=",".join(spec.asset_classes), asset_kinds=",".join(spec.asset_kinds), threat=spec.threat,
        vulnerability=spec.vulnerability, likelihood=spec.likelihood, impact_rule=spec.impact_rule,
        impact_property=spec.impact_property, fixed_impact=spec.fixed_impact, treatment_hint=spec.treatment_hint,
        control_references="", enabled=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _asset_row(name, *, media="", asset_class=AssetClass.it_asset, deleted=False):
    return SimpleNamespace(
        id=_id(), name=name, asset_class=asset_class, criticality=M, effective_criticality=M, business_value=M, confidentiality=M,
        integrity=M, availability=M, media_type=SimpleNamespace(name=media) if media else None, tags=[],
        hostname="", os_version="", manufacturer="", model_number="", data_categories="", controls=[],
        deleted=deleted,
    )


async def test_generation_preview_counts_scenarios_left_out_for_the_asset_kind(monkeypatch):
    firewall, core = _asset_row("Firewall", media="Network"), _asset_row("Core Banking Server", media="Hardware")
    templates = [_template("RS-013"), _template("RS-040"), _template("RS-011")]

    async def select_assets(db, body):
        return [firewall, core]

    async def size(db, tenant_id):
        return 5

    async def empty(*a, **k):
        return {}

    async def register(db):
        return []

    monkeypatch.setattr(api, "_select_assets", select_assets)
    monkeypatch.setattr(api, "get_matrix_size", size)
    monkeypatch.setattr(api, "_placements", empty)
    monkeypatch.setattr(api, "_key_owners", empty)
    monkeypatch.setattr(api, "_register_rows", register)
    monkeypatch.setattr(api, "_legacy_keys", empty)
    db = ScriptedDB(lambda sql: templates if "FROM risk_scenario_templates" in sql else [])

    result = await api.generate(api.GenerateRequest(), db, SimpleNamespace(id=_id(), tenant_id=_id()))

    pairs = {(p.asset_name, p.scenario_reference) for p in result.proposals}
    assert pairs == {("Firewall", "RS-013"), ("Core Banking Server", "RS-013"),
                     ("Core Banking Server", "RS-040"), ("Core Banking Server", "RS-011")}
    assert result.not_fitting == 2
    assert {s.reference: s.pairs for s in result.not_fitting_scenarios} == {"RS-040": 1, "RS-011": 1}
    fraud = next(s for s in result.not_fitting_scenarios if s.reference == "RS-040")
    assert "Core banking" in fraud.fits and "Network device" not in fraud.fits
    assert next(p for p in result.proposals if p.asset_name == "Firewall").asset_kinds == ["Network device"]


# ============================================================= title vs asset ===
PATTERNS = title_patterns([("RS-011", "Ransomware encrypts {asset}"), ("RS-001", "Unauthorised access to {asset}")])


def test_a_generated_title_naming_an_unlinked_asset_is_a_mismatch():
    register = {"firewall": "Firewall", "core banking server": "Core Banking Server"}
    assert risk_integrity.generated_title_mismatch(
        "Ransomware encrypts Firewall", PATTERNS, ["Core Banking Server"], register,
    ) == "Firewall"
    assert risk_integrity.generated_title_mismatch(
        "Ransomware encrypts firewall", PATTERNS, ["FIREWALL"], register,
    ) is None
    # No asset linked: a hand-made risk that names an asset is not an error.
    assert risk_integrity.generated_title_mismatch("Ransomware encrypts Firewall", PATTERNS, [], register) is None
    # The named "asset" does not exist: a hand-written title that merely reads like one.
    assert risk_integrity.generated_title_mismatch(
        "Unauthorised access to SWIFT", PATTERNS, ["Core Banking Server"], register,
    ) is None


def test_the_title_asset_reason_is_set_replaced_and_cleared_on_its_own():
    other = "Asset removed – review: Old DB"
    risk = SimpleNamespace(needs_review=True, review_reason=other)
    assert risk_integrity.apply_title_asset_reason(risk, "Firewall") == (True, False)
    assert risk.needs_review and risk.review_reason.splitlines() == [
        other, risk_integrity.TITLE_ASSET_REASON.format(name="Firewall"),
    ]
    assert risk_integrity.apply_title_asset_reason(risk, "Firewall") == (False, False)  # idempotent
    assert risk_integrity.apply_title_asset_reason(risk, None) == (False, True)
    assert (risk.needs_review, risk.review_reason) == (True, other)  # the other reason stands

    alone = SimpleNamespace(needs_review=False, review_reason="")
    risk_integrity.apply_title_asset_reason(alone, "Firewall")
    risk_integrity.apply_title_asset_reason(alone, None)
    assert (alone.needs_review, alone.review_reason) == (False, "")


async def test_reconcile_flags_r116_and_clears_a_fixed_risk():
    r116 = SimpleNamespace(id=_id(), title="Ransomware encrypts Firewall", needs_review=False, review_reason="")
    fixed = SimpleNamespace(
        id=_id(), title="Quarterly access review gaps", needs_review=True,
        review_reason=risk_integrity.TITLE_ASSET_REASON.format(name="Firewall"),
    )

    def answer(sql):
        if "FROM risk_scenario_templates" in sql:
            return [("RS-011", "Ransomware encrypts {asset}")]
        if "risks.review_reason" in sql and "risks.needs_review" not in sql:
            return [(r.id, r.title, r.review_reason) for r in (r116, fixed)]
        if "FROM risk_assets JOIN assets" in sql:
            return [(r116.id, "Core Banking Server")]
        if "lower(trim(assets.name))" in sql:
            return [("Firewall",)]
        if "FROM risks" in sql:
            return [r116, fixed]
        return []

    assert await risk_integrity.reconcile_generated_title_flags(ScriptedDB(answer)) == (1, 1)
    assert r116.needs_review and "“Firewall”" in r116.review_reason
    assert (fixed.needs_review, fixed.review_reason) == (False, "")


# ============================================================ legacy migration ===
SPECS = {ref: BY_REF[ref] for ref in ("RS-011", "RS-013", "RS-040")}
LEGACY_PATTERNS = title_patterns((s.reference, s.title) for s in SPECS.values())


def _risk(title, *assets, reference="R-0100", **kw) -> lm.LegacyRisk:
    return lm.LegacyRisk(
        id=kw.pop("id", _id()), reference=reference, title=title, assets=tuple(assets),
        inherent_likelihood=kw.pop("likelihood", 3), inherent_impact=kw.pop("impact", 3), **kw,
    )


def _linked(name, deleted=False) -> lm.LinkedAsset:
    return lm.LinkedAsset(_id(), name, deleted)


def _plan(risks, *, facts=None, placements=None, owners=None, names=None, allowed=None):
    assets = {a.id: a for r in risks for a in r.assets}
    return lm.plan_migration(
        risks, patterns=LEGACY_PATTERNS, specs=SPECS,
        assets_by_name=names or {a.name.lower(): a for a in assets.values()},
        facts=facts if facts is not None else {aid: _facts(a.name) for aid, a in assets.items()},
        placements=placements or {}, allowed_controls=allowed or {}, owners=owners or {},
    )


def test_a_legacy_risk_is_recognised_by_its_title_and_its_one_asset():
    server = _linked("Core Banking Server")
    found = lm.recognise(_risk("Ransomware encrypts Core Banking Server", server), LEGACY_PATTERNS, {})
    assert (found.scenario_reference, found.asset) == ("RS-011", server)
    # With its link gone, an archived asset of that name still identifies it.
    gone = _linked("Old Server", deleted=True)
    found = lm.recognise(_risk("Ransomware encrypts Old Server"), LEGACY_PATTERNS, {"old server": gone})
    assert found.asset == gone
    # R-116: names an asset that exists but is not linked.
    firewall = _linked("Firewall")
    found = lm.recognise(_risk("Ransomware encrypts Firewall", server), LEGACY_PATTERNS, {"firewall": firewall})
    assert (found.asset, found.named) == (None, "Firewall")
    # A hand-written title naming nothing in the register is not the generator's.
    assert lm.recognise(_risk("Ransomware encrypts the bank", server), LEGACY_PATTERNS, {}) is None


def test_edit_reasons_list_everything_a_person_did():
    server = _linked("Core Banking Server")
    untouched = _risk("Ransomware encrypts Core Banking Server", server, control_ids=frozenset({PAY}))
    assert lm.edit_reasons(untouched, allowed_controls={PAY}) == []
    worked = _risk(
        "Ransomware encrypts Core Banking Server", server, _linked("DR Server"), status="assessed",
        owner_id=_id(), assessment_rationale="Reviewed", residual_likelihood=2, control_ids=frozenset({PAY, RETAIL}),
        other_links={"issues": 1}, activity={"edits": 3, "restored": 1, "treatment_actions": 1},
    )
    reasons = lm.edit_reasons(worked, allowed_controls={PAY})
    for expected in ("linked to 2 assets", "status is Assessed", "has an owner", "assessment rationale",
                     "residual scores", "1 control was linked by hand", "issues (1)", "3 changes by people",
                     "restored from the archive", "1 treatment action"):
        assert any(expected in r for r in reasons), expected


def test_the_plan_groups_moves_by_key_and_explains_the_rest():
    s1, s2 = _linked("Core Banking Server"), _linked("Core Banking DR Server")
    fw, gone, edited = _linked("Firewall"), _linked("Retired Server", deleted=True), _linked("Payroll Server")
    where = Placement(IT, PAY, "Payments", RETAIL, "Retail Banking")
    risks = [
        _risk("Ransomware encrypts Core Banking DR Server", s2, reference="R-0102", likelihood=4, impact=5),
        _risk("Ransomware encrypts Core Banking Server", s1, reference="R-0101", likelihood=3, impact=3),
        _risk("Internal fraud committed through Firewall", fw, reference="R-0103"),
        _risk("Ransomware encrypts Retired Server", gone, reference="R-0104"),
        _risk("Ransomware encrypts Payroll Server", edited, reference="R-0105", owner_id=_id()),
        _risk("Ransomware encrypts Core Banking Server", s1, reference="R-0106", level=3),  # from the queue
        _risk("Exploitation of an unpatched vulnerability in Core Banking Server", s1, reference="R-0107",
              from_queue=True),
    ]
    plan = _plan(risks, placements={s1.id: where, s2.id: where, fw.id: where, edited.id: where})

    assert (plan.moving, len(plan.dropped), len(plan.kept), plan.recognised) == (2, 2, 1, 5)
    (group,) = plan.groups
    assert group.key == dedupe_key("RS-011", PAY, RETAIL)
    assert [m.risk.reference for m in group.moves] == ["R-0101", "R-0102"]  # reference order
    assert group.scores == (4, 5)
    assert group.title == "Ransomware encrypts Payments assets in Retail Banking"
    assert group.joins is None and plan.new_candidates == 1
    dropped = {o.risk.reference: o.reason for o in plan.dropped}
    assert "RS-040 does not fit “Firewall” (Network device)" in dropped["R-0103"]
    assert "Core banking" in dropped["R-0103"]
    assert dropped["R-0104"] == "its asset “Retired Server” was deleted"
    assert plan.kept[0].risk.reference == "R-0105" and plan.kept[0].reason == "it has an owner"
    assert {r.reference for r in plan.to_archive} == {"R-0101", "R-0102", "R-0103", "R-0104"}


def test_the_plan_respects_what_the_queue_already_holds():
    a, b, c = _linked("Server A"), _linked("Server B"), _linked("Server C")
    placements = {
        a.id: Placement(IT, PAY, "Payments", None, ""),
        b.id: Placement(IT, RETAIL, "Cards", None, ""),
        c.id: Placement(IT, None, "", None, ""),
    }
    waiting = _id()
    owners = {
        dedupe_key("RS-011", PAY, None): KeyOwner("pending", waiting, "Ransomware encrypts Payments assets"),
        dedupe_key("RS-011", RETAIL, None): KeyOwner("accepted", _id(), "t", _id(), "R-0200"),
        dedupe_key("RS-011", None, None, IT): KeyOwner("rejected", _id(), "t", note="Covered at enterprise level"),
    }
    plan = _plan([
        _risk("Ransomware encrypts Server A", a, reference="R-1"),
        _risk("Ransomware encrypts Server B", b, reference="R-2"),
        _risk("Ransomware encrypts Server C", c, reference="R-3"),
    ], placements=placements, owners=owners)

    (group,) = plan.groups
    assert group.joins.proposal_id == waiting and plan.joined_candidates == 1 and plan.new_candidates == 0
    assert "R-0200 already covers RS-011 for Cards" in plan.kept[0].reason
    assert plan.dropped[0].reason.endswith("was rejected: Covered at enterprise level")


def test_a_title_naming_an_unlinked_asset_is_kept_for_a_person():
    core, fw = _linked("Core Banking Server"), _linked("Firewall")
    plan = _plan([_risk("Ransomware encrypts Firewall", core, reference="R-0116")],
                 names={"firewall": fw, "core banking server": core})
    assert plan.kept[0].reason.startswith("its title names “Firewall” but it is linked to “Core Banking Server”")
    assert not plan


def test_the_plan_reads_as_the_api_returns_it():
    s1 = _linked("Core Banking Server")
    plan = _plan([_risk("Ransomware encrypts Core Banking Server", s1, reference="R-0101")],
                 placements={s1.id: Placement(IT, PAY, "Payments", RETAIL, "Retail Banking")})
    read = lm.plan_read(plan)
    assert (read.recognised, read.moving, read.new_candidates) == (1, 1, 1)
    group = read.groups[0]
    assert group.title == "Ransomware encrypts Core Banking Server"  # one asset keeps its title
    assert group.scope_label == "Payments · Retail Banking" and group.risks[0].reference == "R-0101"


@pytest.fixture
def audit(monkeypatch):
    calls: list[dict] = []

    async def record(db, **kw):
        calls.append(kw)

    monkeypatch.setattr("app.services.audit.record", record)
    return calls


async def test_apply_creates_candidates_archives_risks_and_audits(monkeypatch, audit):
    s1, s2, fw = _linked("Core Banking Server"), _linked("Core Banking DR Server"), _linked("Firewall")
    where = Placement(IT, PAY, "Payments", RETAIL, "Retail Banking")
    moving = [
        _risk("Ransomware encrypts Core Banking Server", s1, reference="R-0101"),
        _risk("Ransomware encrypts Core Banking DR Server", s2, reference="R-0102", likelihood=4, impact=4),
    ]
    dropped = _risk("Internal fraud committed through Firewall", fw, reference="R-0103")
    plan = _plan([*moving, dropped], placements={s1.id: where, s2.id: where, fw.id: where})
    rows = {r.id: SimpleNamespace(id=r.id, reference=r.reference, deleted=False, deleted_date=None)
            for r in [*moving, dropped]}
    links: list[dict] = []

    async def load(db):
        return plan, lm.Context()

    async def noop(*a, **k):
        return None

    async def categories(db, texts):
        return {}

    async def link(db, new):
        links.extend(new)

    monkeypatch.setattr(lm, "load_plan", load)
    monkeypatch.setattr(api, "_lock_queue", noop)
    monkeypatch.setattr(api, "_category_ids", categories)
    monkeypatch.setattr(api, "_link_assets", link)
    db = ScriptedDB(lambda sql: list(rows.values()) if "FROM risks" in sql else [])
    user = SimpleNamespace(id=_id(), tenant_id=_id(), email="cro@bank.pk")

    result = await lm.apply(db, user)

    assert (result.archived, result.moved, result.dropped, result.created, result.joined) == (3, 2, 1, 1, 0)
    (candidate,) = [o for o in db.added if isinstance(o, ProposalRow)]
    assert candidate.status == "pending" and candidate.source_risk_id == moving[0].id
    assert (candidate.inherent_likelihood, candidate.inherent_impact) == (4, 4)
    assert candidate.title == "Ransomware encrypts Payments assets in Retail Banking"
    assert {link["asset_id"] for link in links} == {s1.id, s2.id}
    assert all(r.deleted and r.deleted_date for r in rows.values())
    archived = {a["entity_id"]: a for a in audit if a["entity_type"] == "risk"}
    assert "moved to risk candidates" in archived[moving[0].id]["summary"]
    assert archived[moving[1].id]["changes"]["proposal_id"] == str(candidate.id)
    assert archived[dropped.id]["changes"]["via"] == lm.MIGRATION_VIA and "does not fit" in archived[dropped.id]["summary"]
    assert audit[-1]["action"] == lm.MIGRATION_VIA and audit[-1]["changes"]["moved"] == 2


async def test_load_plan_reads_the_register_with_compiling_queries(monkeypatch):
    template = _template("RS-011")
    server = _asset_row("Core Banking Server", media="Hardware")
    risk = SimpleNamespace(
        id=_id(), reference="R-0101", title="Ransomware encrypts Core Banking Server", status="draft",
        workflow_status="draft", level=None, parent_id=None, owner_id=None, treatment_owner_id=None,
        treatment_strategy=None, assessment_rationale="", residual_likelihood=None, residual_impact=None,
        target_likelihood=None, target_impact=None, inherent_likelihood=3, inherent_impact=4,
    )
    where = Placement(IT, PAY, "Payments", RETAIL, "Retail Banking")

    async def placements(db, ids):
        return {server.id: where}

    async def owners(db, keys):
        assert keys == {dedupe_key("RS-011", PAY, RETAIL)}
        return {}

    async def links(db, ids):
        return {i: {} for i in ids}

    monkeypatch.setattr(api, "_placements", placements)
    monkeypatch.setattr(api, "_key_owners", owners)
    monkeypatch.setattr(risk_integrity, "live_link_counts", links)

    def answer(sql):
        if "FROM risk_scenario_templates" in sql:
            return [template]
        if "risks.level IS NULL" in sql:
            return [risk]
        if "FROM risk_assets JOIN assets" in sql:
            return [(risk.id, server.id, server.name, False)]
        if "lower(trim(assets.name))" in sql:
            return [(server.id, server.name, False)]
        if "UNION ALL" in sql or "risk_proposals" in sql or "risk_controls" in sql or "control_assets" in sql:
            return []
        if "FROM assets" in sql:
            return [server]
        return []

    db = ScriptedDB(answer)
    plan, _ctx = await lm.load_plan(db)
    assert plan.moving == 1 and plan.groups[0].scores == (3, 4)
    assert any("audit_logs.actor_id IS NOT NULL" in sql for sql in db.sql)


# ================================================== _legacy_keys: counted once ===
async def test_legacy_keys_skip_queue_risks_and_give_one_key_per_risk(monkeypatch):
    a1 = _id()
    promoted_risk, legacy_risk = _id(), _id()
    where = Placement(IT, PAY, "Payments", RETAIL, "Retail Banking")
    templates = [SimpleNamespace(reference="RS-011", title="Ransomware encrypts {asset}"),
                 SimpleNamespace(reference="RS-099", title="Ransomware encrypts {asset}")]

    async def placements(db, ids):
        return {a1: where}

    monkeypatch.setattr(api, "_placements", placements)

    def answer(sql):
        if "risk_proposals.promoted_risk_id" in sql:
            return [promoted_risk]
        if "risk_assets" in sql:
            return [(legacy_risk, a1, "Server-1")]
        return []

    k11, k99 = dedupe_key("RS-011", PAY, RETAIL), dedupe_key("RS-099", PAY, RETAIL)
    out = await api._legacy_keys(
        ScriptedDB(answer),
        [(promoted_risk, "R-0300", "Ransomware encrypts Server-1"), (legacy_risk, "R-0005", "Ransomware encrypts Server-1")],
        templates, {k11, k99},
    )
    assert out == {k11: "R-0005"}


async def test_boot_repair_fills_library_kinds_once_and_audits_each_template():
    from app.db import data_repairs
    from app.models.audit import AuditLog

    untouched, retitled, cleared_before = _template("RS-040", asset_kinds=""), _template(
        "RS-011", asset_kinds="", title="Crypto-locker on {asset}"), _template("RS-013", asset_kinds="")

    def answer(sql):
        if "FROM risk_scenario_templates" in sql:
            return [untouched, retitled, cleared_before]
        if "FROM audit_logs" in sql:
            return [cleared_before.id]  # filled once already; a person has since cleared it
        return []

    db = ScriptedDB(answer)
    tenant = _id()
    assert await data_repairs.backfill_scenario_kinds(db, tenant) == 1
    assert untouched.asset_kinds == "core_banking,customer_channel,customer_data,payment_system"
    assert (retitled.asset_kinds, cleared_before.asset_kinds) == ("", "")
    (row,) = [o for o in db.added if isinstance(o, AuditLog)]
    assert (row.entity_id, row.actor_id, row.tenant_id) == (untouched.id, None, tenant)
    assert row.changes["via"] == data_repairs.REPAIR_VIA and row.changes["asset_kinds"]["to"] == untouched.asset_kinds
