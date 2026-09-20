"""Phase 4D: continuous control monitoring that runs.

Parsers (Nessus, Qualys, OpenVAS) on small inline files, Active Directory checks on a
fake LDAP connection, the JSON selector, thresholds and comparisons, the SSRF guard, the
runner's due and overdue rules, issue dedupe per test, the reliance signal, connector
secrets (encrypted, write-only) and the feed rate limiter. Pure or on fake sessions.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.integrations import CcmResult, CcmStatus
from app.services import ccm_checks, ccm_runner, control_assurance
from app.services.ccm_checks import CheckContext, CheckError, CheckOutcome, UploadedFile, files, http_json, ldap_checks, selector, vuln_import
from app.services.ccm_checks import secrets as box
from app.services.rate_limit import RateLimiter

NOW = datetime(2026, 9, 17, 6, 0, tzinfo=timezone.utc)


# ================================================================== parsers ===
NESSUS = b"""<?xml version="1.0" ?>
<NessusClientData_v2><Report name="Weekly">
 <ReportHost name="10.1.1.5"><HostProperties>
   <tag name="host-ip">10.1.1.5</tag><tag name="host-fqdn">cbs-app01.bank.local</tag>
   <tag name="HOST_END">Tue Sep 15 02:10:00 2026</tag></HostProperties>
  <ReportItem port="443" protocol="tcp" severity="4" pluginID="1001" pluginName="OpenSSL RCE">
   <cve>CVE-2026-1111</cve><cvss3_base_score>9.8</cvss3_base_score>
   <patch_publication_date>2026/07/01</patch_publication_date><solution>Upgrade</solution></ReportItem>
  <ReportItem port="8443" protocol="tcp" severity="4" pluginID="1001" pluginName="OpenSSL RCE">
   <cve>CVE-2026-1111</cve></ReportItem>
  <ReportItem port="22" protocol="tcp" severity="3" pluginID="1002" pluginName="SSH weak MAC"/>
  <ReportItem port="0" protocol="tcp" severity="0" pluginID="19506" pluginName="Scan info"/>
 </ReportHost></Report></NessusClientData_v2>"""

QUALYS = b"""Scan Results,,,
Generated,09/16/2026,,
"IP","DNS","NetBIOS","QID","Title","Type","Severity","CVE ID","First Detected","Last Detected","Vuln Status"
"10.1.1.7","atm-sw01.bank.local","ATMSW01","38170","SSL Certificate Expired","Vuln","5","CVE-2026-2222","07/01/2026 10:00:00","09/16/2026 10:00:00","Active"
"10.1.1.7","atm-sw01.bank.local","ATMSW01","11827","HTTP TRACE enabled","Vuln","4","","09/10/2026 10:00:00","09/16/2026 10:00:00","New"
"10.1.1.8","","","45038","Host scan time","Ig","1","","09/16/2026","09/16/2026","Active"
"10.1.1.9","","","38171","Old fixed thing","Vuln","5","","01/01/2026","02/01/2026","Fixed"
"""

OPENVAS = b"""<report id="r1"><report><scan_start>2026-09-14T01:00:00Z</scan_start><results>
 <result id="a"><name>Apache Struts RCE</name><host>10.2.0.4<hostname>web01</hostname></host><port>8080/tcp</port>
  <nvt oid="1.3.6.1.4.1.25623.1.0.1"><refs><ref type="cve" id="CVE-2026-3333"/><ref type="url" id="x"/></refs></nvt>
  <threat>High</threat><severity>10.0</severity><creation_time>2026-08-01T00:00:00Z</creation_time></result>
 <result id="b"><name>TCP timestamps</name><host>10.2.0.4</host><threat>Log</threat><severity>0.0</severity></result>
 <result id="c"><name>Weak cipher</name><host>10.2.0.5</host><threat>Medium</threat><severity>5.0</severity></result>
</results></report></report>"""


def test_nessus_parses_hosts_findings_and_dedupes_ports():
    rows = vuln_import.parse_nessus(NESSUS)
    assert len(rows) == 4
    crit = rows[0]
    assert (crit.host, crit.ip, crit.severity, crit.cves, crit.cvss) == (
        "cbs-app01.bank.local", "10.1.1.5", "critical", ["CVE-2026-1111"], 9.8)
    assert crit.patch_published == date(2026, 7, 1) and crit.first_seen == date(2026, 9, 15)
    assert len(vuln_import.dedupe(rows)) == 3  # the same plugin on two ports is one finding


def test_qualys_csv_skips_preamble_information_and_fixed():
    rows = vuln_import.parse_qualys_csv(QUALYS)
    assert [(r.plugin_id, r.severity) for r in rows] == [("qualys:38170", "critical"), ("qualys:11827", "high")]
    assert rows[0].first_seen == date(2026, 7, 1) and rows[0].cves == ["CVE-2026-2222"]


def test_openvas_maps_cvss_to_severity_and_skips_logs():
    rows = vuln_import.parse_openvas_xml(OPENVAS)
    assert [(r.host, r.severity) for r in rows] == [("web01", "critical"), ("10.2.0.5", "medium")]
    assert rows[0].cves == ["CVE-2026-3333"] and rows[0].first_seen == date(2026, 8, 1)


def test_format_detection_and_entity_refusal():
    assert vuln_import.detect_format("scan.nessus", NESSUS) == "nessus"
    assert vuln_import.detect_format("r.xml", OPENVAS) == "openvas"
    assert vuln_import.detect_format("q.csv", QUALYS) == "qualys"
    with pytest.raises(CheckError, match="DTD"):
        vuln_import.parse_nessus(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><NessusClientData_v2/>')
    with pytest.raises(CheckError, match="Qualys"):
        vuln_import.parse_qualys_csv(b"a,b\n1,2\n")


def test_vulnerability_check_counts_past_sla_and_prefers_register_dates():
    ctx = CheckContext(parameters={"severities": ["critical", "high"]}, file=UploadedFile("q.csv", QUALYS), now=NOW)
    out = vuln_import.vulnerability_scan(ctx)
    # critical first detected 1 Jul (78 days > 7); high first detected 10 Sep (7 days < 30)
    assert (out.population, out.exceptions_count) == (2, 1)
    assert out.exceptions[0]["age_days"] == 78 and out.details["by_severity"] == {"critical": 1, "high": 1}
    # The register first saw the high finding in June: now it is past its 30 days too.
    key = vuln_import.finding_key("", "qualys:11827", "10.1.1.7")
    ctx.known_first_seen = {key: date(2026, 6, 1)}
    assert vuln_import.vulnerability_scan(ctx).exceptions_count == 2


def test_nessus_patch_published_age():
    base = {"severities": ["critical"], "sla_days": {"critical": 30}}
    fresh = CheckContext(parameters=base, file=UploadedFile("s.nessus", NESSUS), now=NOW)
    assert vuln_import.vulnerability_scan(fresh).exceptions_count == 0  # scanned 15 Sep
    aged = CheckContext(parameters={**base, "age_from": "patch_published"}, file=UploadedFile("s.nessus", NESSUS), now=NOW)
    assert vuln_import.vulnerability_scan(aged).exceptions_count == 1  # patch out since 1 Jul


# ===================================================================== LDAP ===
FILETIME = lambda dt: str(int((dt - datetime(1601, 1, 1, tzinfo=timezone.utc)).total_seconds() * 10**7))  # noqa: E731


class FakeLdap:
    """Answers a search from a function of (base, filter); records searches; pages once."""

    def __init__(self, answer):
        self.answer = answer
        self.searches = []
        self.response = []
        self.result = {}
        self.unbound = False

    def search(self, search_base, search_filter, search_scope="SUBTREE", attributes=None, paged_size=None, paged_cookie=None):
        self.searches.append((search_base, search_filter))
        self.response = [{"type": "searchResEntry", "dn": e.get("dn", ""), "attributes": {k: v for k, v in e.items() if k != "dn"}}
                         for e in self.answer(search_base, search_filter)]
        self.result = {"result": 0}
        return True

    def unbind(self):
        self.unbound = True


def _user(sam, uac=512, **attrs):
    return {"dn": f"CN={sam},OU=Users,DC=bank,DC=local", "sAMAccountName": [sam], "userAccountControl": [str(uac)], **attrs}


def _ctx(conn, **params):
    return CheckContext(parameters=params, connector_type="active_directory", config={"base_dn": "DC=bank,DC=local"},
                        now=NOW, ldap_factory=lambda c, s, t: conn)


def test_privileged_group_members_flags_unapproved_enabled_members():
    def answer(base, flt):
        if "objectClass=group" in flt:
            return [{"dn": "CN=Domain Admins,CN=Users,DC=bank,DC=local", "cn": ["Domain Admins"]}]
        assert "1.2.840.113556.1.4.1941" in flt  # nested membership
        return [_user("adm.ali"), _user("adm.sara"), _user("old.admin", uac=514)]

    conn = FakeLdap(answer)
    out = ldap_checks.privileged_group_members(_ctx(conn, groups=["Domain Admins"], approved_accounts="ADM.ALI"))
    assert (out.population, [e["account"] for e in out.exceptions]) == (2, ["adm.sara"])
    assert conn.unbound


def test_privileged_group_that_does_not_exist_is_an_error():
    with pytest.raises(CheckError, match="not found"):
        ldap_checks.privileged_group_members(_ctx(FakeLdap(lambda b, f: []), groups=["Nope"]))


def test_inactive_accounts_uses_last_logon_and_creation():
    entries = [
        _user("active", lastLogonTimestamp=[FILETIME(NOW - timedelta(days=5))]),
        _user("stale", lastLogonTimestamp=[FILETIME(NOW - timedelta(days=200))]),
        _user("never.old", whenCreated=["20250101000000.0Z"]),
        _user("never.new", whenCreated=[(NOW - timedelta(days=3)).strftime("%Y%m%d%H%M%S.0Z")]),
        _user("disabled", uac=514, lastLogonTimestamp=[FILETIME(NOW - timedelta(days=400))]),
        _user("breakglass", lastLogonTimestamp=["0"]),
    ]
    out = ldap_checks.inactive_accounts(_ctx(FakeLdap(lambda b, f: entries), days=90, excluded_accounts=["breakglass"]))
    assert out.population == 4  # disabled and excluded are out
    assert sorted(e["account"] for e in out.exceptions) == ["never.old", "stale"]


def test_password_never_expires_and_approved_exceptions():
    entries = [_user("svc_backup", uac=512 | 0x10000), _user("jdoe", uac=512 | 0x10000), _user("ok")]
    out = ldap_checks.password_never_expires(_ctx(FakeLdap(lambda b, f: entries), approved_accounts=["svc_backup"]))
    assert (out.population, [e["account"] for e in out.exceptions]) == (3, ["jdoe"])


def test_leavers_from_an_hr_file_and_from_an_ou():
    entries = [_user("a.khan", mail=["a.khan@bank.pk"]), _user("b.shah", uac=514, mail=["b.shah@bank.pk"])]
    ctx = _ctx(FakeLdap(lambda b, f: entries), match_attribute="mail")
    ctx.file = UploadedFile("leavers.csv", b"Employee,Email\n1,A.Khan@bank.pk\n2,b.shah@bank.pk\n3,c@bank.pk\n")
    out = ldap_checks.leavers_still_enabled(ctx)
    assert (out.population, [e["leaver"] for e in out.exceptions]) == (3, ["A.Khan@bank.pk"])

    ou = ldap_checks.leavers_still_enabled(_ctx(FakeLdap(lambda b, f: entries), mode="leavers_ou", leavers_ou="OU=Leavers,DC=bank,DC=local"))
    assert (ou.population, ou.exceptions_count) == (2, 1)
    with pytest.raises(CheckError, match="No leavers"):
        ldap_checks.leavers_still_enabled(_ctx(FakeLdap(lambda b, f: entries)))


def test_service_accounts_with_interactive_logon():
    entries = [
        _user("svc_ok", userWorkstations=["APP01,APP02"]),
        _user("svc_any"),
        _user("svc_rdp", userWorkstations=["APP03"], memberOf=["CN=Remote Desktop Users,CN=Builtin,DC=bank,DC=local"]),
        _user("human"),
    ]
    out = ldap_checks.service_accounts_interactive(_ctx(FakeLdap(lambda b, f: entries), name_prefixes=["svc_"],
                                                        interactive_groups=["Remote Desktop Users"]))
    assert out.population == 3
    assert {e["account"]: e["issue"] for e in out.exceptions} == {
        "svc_any": "not restricted to named hosts", "svc_rdp": "member of Remote Desktop Users"}


def test_ad_time_and_filter_escaping():
    assert ldap_checks.ad_time(["9223372036854775807"]) is None
    assert ldap_checks.ad_time("20260101120000.0Z") == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    assert ldap_checks.ad_time(FILETIME(NOW)).date() == NOW.date()
    assert ldap_checks.escape("a*(b)\\") == "a\\2a\\28b\\29\\5c"


# ================================================================= selector ===
def test_dotted_selector():
    doc = {"data": {"items": [{"name": "a", "mfa": False}, {"name": "b", "mfa": True}], "count": 2}}
    assert selector.select(doc, "data.count") == 2
    assert selector.select(doc, "data.items[1].name") == "b"
    assert selector.select(doc, "data.items.0.name") == "a"
    assert selector.select(doc, "data.items[*].mfa") == [False, True]
    assert selector.select(doc, "$.data.items[-1].name") == "b"
    assert selector.resolve(doc, "data.missing") is selector.MISSING
    assert selector.select(doc, "") is doc


# ============================================================ threshold/compare ===
def _outcome(pop, exc, passed=None):
    return CheckOutcome(population=pop, exceptions=[{"i": i} for i in range(exc)], summary="", passed=passed)


def test_threshold_rules():
    assert ccm_checks.evaluate(_outcome(100, 0), None, None)
    assert not ccm_checks.evaluate(_outcome(100, 1), None, None)  # no threshold: none allowed
    assert ccm_checks.evaluate(_outcome(100, 3), 3, None) and not ccm_checks.evaluate(_outcome(100, 4), 3, None)
    assert ccm_checks.evaluate(_outcome(200, 2), None, 1.0) and not ccm_checks.evaluate(_outcome(200, 3), None, 1.0)
    assert not ccm_checks.evaluate(_outcome(1000, 5), 3, 1.0)  # both limits must hold
    assert ccm_checks.evaluate(_outcome(1, 1, passed=True), 0, None)  # a value check decides itself
    assert ccm_checks.pass_rate(40, 1) == 97.5 and ccm_checks.pass_rate(0, 0) == 100.0
    assert ccm_checks.threshold_text(0, None) == "no exceptions"
    assert ccm_checks.threshold_text(3, 1.5) == "at most 3 exceptions and at most 1.5% of the population"


def test_comparisons():
    c = ccm_checks.base.compare
    assert c("5", "<=", 5) and c(10, ">", "9.5") and c("PASS", "==", "pass")
    assert c("fail", "in", "fail, failed") and c("ok", "not_in", ["fail"])
    assert c(["a", "B"], "contains", "b") and c("false", "is_false") and c("", "is_empty")
    with pytest.raises(CheckError):
        c("abc", "<", 3)
    with pytest.raises(CheckError):
        c(1, "~=", 1)


def test_http_json_value_and_list_modes():
    body = {"summary": {"admins_without_mfa": 2}, "users": [{"upn": "a", "mfa": False}, {"upn": "b", "mfa": True}]}
    calls = []

    def getter(url, headers, params, timeout, verify):
        calls.append((url, headers))
        return 200, body

    cfg = {"base_url": "https://idp.bank.local/api", "auth": "bearer"}
    ctx = CheckContext(parameters={"path": "/report", "selector": "summary.admins_without_mfa", "op": "==", "expected": 0},
                       config=cfg, secrets={"token": "t0k"}, http_get=getter)
    out = http_json.http_json_check(ctx)
    assert out.passed is False and out.metric_value == 2
    assert calls[0] == ("https://idp.bank.local/api/report", {"Authorization": "Bearer t0k"})
    ctx.parameters = {"path": "report", "selector": "users", "mode": "list", "label_field": "upn",
                      "exception_when": {"field": "mfa", "op": "is_false"}}
    out = http_json.http_json_check(ctx)
    assert (out.population, out.exceptions) == (2, [{"item": "a", "mfa": False}])


def test_ssrf_guard_depends_on_deployment(monkeypatch):
    private = lambda host: ["10.0.0.5"]  # noqa: E731
    public = lambda host: ["8.8.8.8"]  # noqa: E731
    assert http_json.url_refusal("https://cbs.bank.local/x", allow_private=True, resolve=private) is None
    assert "private" in http_json.url_refusal("https://cbs.bank.local/x", allow_private=False, resolve=private)
    assert http_json.url_refusal("https://api.vendor.com/x", allow_private=False, resolve=public) is None
    assert "HTTPS" in http_json.url_refusal("http://api.vendor.com/x", allow_private=False, resolve=public)
    assert "169.254" in http_json.url_refusal("https://meta/x", allow_private=False, resolve=lambda h: ["169.254.169.254"])
    assert "secrets" in http_json.url_refusal("https://u:p@h/x", allow_private=True)
    from app.core.config import settings

    monkeypatch.setattr(settings, "ccm_allow_private_urls", None)
    monkeypatch.setattr(settings, "deployment_mode", "saas")
    assert http_json.private_urls_allowed() is False
    monkeypatch.setattr(settings, "deployment_mode", "on-prem")
    assert http_json.private_urls_allowed() is True
    monkeypatch.setattr(settings, "ccm_allow_private_urls", False)
    assert http_json.private_urls_allowed() is False


def test_siem_source_health_from_a_json_export():
    doc = b'{"sources": [{"name": "DC01", "last_event": "2026-09-17T05:00:00Z"}, {"name": "FW-EDGE", "last_event": 1757900000}]}'
    ctx = CheckContext(parameters={"max_silence_hours": 24, "list_selector": "sources", "expected_sources": ["DC01", "CBS-DB"]},
                       file=UploadedFile("siem.json", doc), now=NOW)
    out = files.siem_source_health(ctx)
    assert out.population == 3
    assert [e["source"] for e in out.exceptions] == ["FW-EDGE", "CBS-DB"]


def test_csv_rows_check():
    ctx = CheckContext(parameters={"column": "status", "op": "in", "value": "fail", "label_column": "branch"},
                       file=UploadedFile("b.csv", b"branch,status\nKHI,pass\nLHE,FAIL\n"), now=NOW)
    out = files.csv_rows_check(ctx)
    assert (out.population, out.exceptions) == (2, [{"row": 2, "item": "LHE", "status": "FAIL"}])


def test_import_folder_must_stay_inside_the_root(tmp_path):
    (tmp_path / "nessus").mkdir()
    (tmp_path / "nessus" / "old.nessus").write_bytes(b"old")
    newest = tmp_path / "nessus" / "new.nessus"
    newest.write_bytes(NESSUS)
    import os

    os.utime(tmp_path / "nessus" / "old.nessus", (1, 1))
    assert files.newest_file({"import_path": "nessus", "file_pattern": "*.nessus"}, tmp_path).filename == "new.nessus"
    with pytest.raises(CheckError, match="inside"):
        files.folder_for({"import_path": "../../etc"}, tmp_path)


def test_definition_errors():
    assert ccm_checks.definition_errors("manual", {}, None) == []
    assert "unknown" in ccm_checks.definition_errors("nope", {}, None)[0]
    errs = ccm_checks.definition_errors("ad_inactive_accounts", {"days": "x"}, "siem")
    assert any("number" in e for e in errs) and any("cannot run on a siem" in e for e in errs)
    assert any("pick one" in e for e in ccm_checks.definition_errors("ad_password_never_expires", {}, None))
    assert ccm_checks.definition_errors("vuln_scan_sla", {"severities": ["urgent"]}, "vuln_scanner")
    assert ccm_checks.config_errors("active_directory", {"host": "dc", "base_url": "x"}) == [
        "Setting 'base_url' does not apply to this connector type."]
    assert ccm_checks.secret_errors("active_directory", ["token"])


# ================================================================== secrets ===
def test_secrets_are_encrypted_write_only_and_never_read(monkeypatch):
    from app.core.config import settings
    from app.schemas.integrations import ConnectorRead

    monkeypatch.setattr(settings, "connector_secret_key", "")
    box._fernet_for.cache_clear()
    c = SimpleNamespace(secrets_encrypted="", secret_keys=[])
    assert box.apply(c, {"bind_password": "S3cret!"}, None) == ["bind_password"]
    assert "S3cret" not in c.secrets_encrypted and c.secret_keys == ["bind_password"]
    assert box.decrypt(c.secrets_encrypted) == {"bind_password": "S3cret!"}
    assert box.apply(c, {"bind_password": ""}, None) == []  # blank keeps
    assert box.apply(c, None, ["bind_password"]) == ["bind_password"] and c.secrets_encrypted == ""
    # a different key cannot read them
    box.apply(c, {"token": "abc"}, None)
    monkeypatch.setattr(settings, "connector_secret_key", "another key entirely")
    with pytest.raises(box.SecretsUnreadable):
        box.decrypt(c.secrets_encrypted)
    assert box.apply(c, {"token": "new"}, None) == ["token"]  # re-entering replaces
    assert box.masked(["token"]) == {"token": "set"}
    fields = set(ConnectorRead.model_fields)
    assert "secrets_encrypted" not in fields and "secrets" not in fields and "secrets_set" in fields


# ================================================================== runner ===
def _test(**kw):
    base = dict(id=uuid.uuid4(), reference="CCM-001", name="Inactive accounts", check_type="ad_inactive_accounts",
                status=CcmStatus.active, frequency=SimpleNamespace(value="daily"), last_run_at=None, last_run=None,
                created_at=NOW - timedelta(days=10), deleted=False, parameters={}, control_id=None, failing_since=None,
                issue_id=None, kri_id=None, kri_metric="exceptions", pass_criterion="", test_logic="",
                last_result=CcmResult.not_run)
    return SimpleNamespace(**{**base, **kw})


def test_due_logic():
    assert ccm_runner.is_due(_test(), NOW)
    assert not ccm_runner.is_due(_test(last_run_at=NOW - timedelta(hours=5)), NOW)
    assert ccm_runner.is_due(_test(last_run_at=NOW - timedelta(hours=23, minutes=55)), NOW)  # same sweep daily
    assert not ccm_runner.is_due(_test(check_type="manual"), NOW)
    assert not ccm_runner.is_due(_test(status=CcmStatus.paused), NOW)
    assert not ccm_runner.is_due(_test(frequency=SimpleNamespace(value="none")), NOW)
    monthly = _test(frequency=SimpleNamespace(value="monthly"), last_run_at=NOW - timedelta(days=29))
    assert not ccm_runner.is_due(monthly, NOW)


def test_auto_runnable_needs_a_connector_and_a_folder_for_files():
    ad = SimpleNamespace(status=SimpleNamespace(value="active"), config={}, deleted=False)
    assert ccm_runner.auto_runnable(_test(), ad)
    assert not ccm_runner.auto_runnable(_test(), None)
    assert not ccm_runner.auto_runnable(_test(), SimpleNamespace(status=SimpleNamespace(value="disabled"), config={}, deleted=False))
    vuln = _test(check_type="vuln_scan_sla")
    assert not ccm_runner.auto_runnable(vuln, ad)
    assert ccm_runner.auto_runnable(vuln, SimpleNamespace(status=SimpleNamespace(value="active"), config={"import_path": "n"}, deleted=False))


def test_overdue_after_twice_the_frequency():
    weekly = SimpleNamespace(value="weekly")
    assert ccm_runner.is_overdue(_test(frequency=weekly, last_run_at=NOW - timedelta(days=15)), NOW)
    assert not ccm_runner.is_overdue(_test(frequency=weekly, last_run_at=NOW - timedelta(days=13)), NOW)
    assert ccm_runner.is_overdue(_test(frequency=weekly, created_at=NOW - timedelta(days=20)), NOW)  # never ran
    manual = _test(check_type="manual", frequency=weekly, last_run=date(2026, 9, 1))
    assert ccm_runner.is_overdue(manual, NOW)
    alert = ccm_runner.overdue_alert(test=manual, now=NOW)
    assert alert["dedup_key"].endswith(":2026-09-01") and "last ran on 2026-09-01" in alert["body"]


def test_recent_pass_rate_and_lock_key():
    runs = [SimpleNamespace(result=CcmResult.passed if i % 10 else CcmResult.failed, run_date=date(2026, 1, 1) + timedelta(days=i),
                            created_at=NOW) for i in range(40)] + [SimpleNamespace(result=CcmResult.error, run_date=date(2027, 1, 1), created_at=NOW)]
    n, rate = ccm_runner.recent_pass_rate(runs)
    assert n == 30 and rate == 90.0
    assert ccm_runner.recent_pass_rate([]) == (0, None)
    k = ccm_runner.lock_key(uuid.UUID("ffffffff-ffff-ffff-0000-000000000000"))
    assert -(2**63) <= k < 2**63


def test_kri_value_by_metric():
    kw = dict(exceptions=3, population=200, pass_rate=98.5, value=7.0)
    assert ccm_runner.kri_value("exceptions", **kw) == 3.0
    assert ccm_runner.kri_value("exception_percent", **kw) == 1.5
    assert ccm_runner.kri_value("population", **kw) == 200.0
    assert ccm_runner.kri_value("pass_rate", **kw) == 98.5
    assert ccm_runner.kri_value("value", **kw) == 7.0
    assert ccm_runner.kri_value("exceptions", exceptions=None, population=None, pass_rate=100.0, value=None) is None


class FakeDB:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.added = []

    @staticmethod
    def _entity(stmt):
        desc = stmt.column_descriptions[0]
        return desc.get("entity") or desc.get("type")

    async def scalar(self, stmt, *a):
        value = self.answers.get(getattr(self._entity(stmt), "__name__", ""))
        return value[0] if isinstance(value, list) else value

    async def scalars(self, stmt):
        value = self.answers.get(self._entity(stmt).__name__, [])
        return SimpleNamespace(all=lambda: value if isinstance(value, list) else [value])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


@pytest.fixture
def issue_env(monkeypatch):
    calls = SimpleNamespace(refs=0, links=[], recomputed=[], audits=[])

    async def ref(db):
        calls.refs += 1
        return f"ISS-{100 + calls.refs}"

    async def link(db, issue_id, control_id):
        calls.links.append((issue_id, control_id))

    async def recompute(db, control_id, reason):
        calls.recomputed.append((control_id, reason))

    async def audit(db, tenant_id, actor, **entry):
        calls.audits.append(entry)

    monkeypatch.setattr(ccm_runner, "next_issue_reference", ref)
    monkeypatch.setattr(ccm_runner, "link_issue_to_control", link)
    monkeypatch.setattr(ccm_runner, "recompute_control", recompute)
    monkeypatch.setattr(ccm_runner, "connector_audit", audit)
    return calls


def _control(**kw):
    return SimpleNamespace(**{**dict(id=uuid.uuid4(), reference="A.5.18", name="Access rights", is_key=True, owner="",
                                     owner_id=None, monitoring_failing_since=None), **kw})


async def test_a_failing_test_opens_one_issue_then_updates_it(issue_env):
    from app.models.issue import IssueSource, IssueStatus2

    tenant, control, test = uuid.uuid4(), _control(), _test(control_id=None)
    test.control_id = control.id
    db = FakeDB()
    issue, opened = await ccm_runner.open_or_update_issue(db, tenant_id=tenant, test=test, control=control, day=date(2026, 9, 17),
                                                          summary="4 stale accounts", actor="Connector AD", exceptions=4, population=900)
    assert opened and issue.reference == "ISS-101" and issue.source_type == IssueSource.ccm
    assert issue.severity.value == "high" and test.issue_id == issue.id
    assert issue_env.links == [(issue.id, control.id)] and issue_env.recomputed[0][0] == control.id

    # Still open: the next failure adds an update instead of a second issue.
    db = FakeDB({"Issue": issue})
    again, opened = await ccm_runner.open_or_update_issue(db, tenant_id=tenant, test=test, control=control, day=date(2026, 9, 18),
                                                          summary="3 stale accounts", actor="Connector AD", exceptions=3, population=900)
    assert again is issue and not opened and issue_env.refs == 1
    assert [type(o).__name__ for o in db.added] == ["IssueUpdate"] and "failed again" in db.added[0].note

    # Closed: the next failure opens a new one.
    issue.status = IssueStatus2.closed
    third, opened = await ccm_runner.open_or_update_issue(FakeDB({"Issue": issue}), tenant_id=tenant, test=test, control=control,
                                                          day=date(2026, 10, 1), summary="1 stale", actor="Connector AD",
                                                          exceptions=1, population=900)
    assert opened and third is not issue and issue_env.refs == 2


async def test_control_signal_follows_the_failing_tests(issue_env):
    control = _control()
    failing = _test(control_id=control.id, last_result=CcmResult.failed, failing_since=date(2026, 9, 10))
    passing = _test(control_id=control.id, last_result=CcmResult.passed)
    db = FakeDB({"AutomatedControlTest": [failing, passing]})
    assert await ccm_runner.refresh_control_signal(db, tenant_id=uuid.uuid4(), control=control, actor="x") == "failing"
    assert control.monitoring_failing_since == date(2026, 9, 10)
    assert "failing since 2026-09-10" in issue_env.audits[-1]["summary"]
    assert await ccm_runner.refresh_control_signal(db, tenant_id=uuid.uuid4(), control=control, actor="x") == ""
    failing.last_result, failing.failing_since = CcmResult.passed, None
    assert await ccm_runner.refresh_control_signal(db, tenant_id=uuid.uuid4(), control=control, actor="x") == "cleared"
    assert control.monitoring_failing_since is None


async def test_record_result_rolls_up_failing_since_and_a_pass_never_touches_effectiveness(monkeypatch):
    from app.models.enums import ControlEffectiveness

    async def owners(db, ids):
        return {}

    from app.services import master_data

    monkeypatch.setattr(master_data, "users_by_id", owners)
    control = _control(effectiveness=ControlEffectiveness.partially_effective)
    connector = SimpleNamespace(id=uuid.uuid4(), name="AD", reference="CON-001", last_sync=None)
    test = _test(control_id=control.id, pass_rate=0)
    kw = dict(tenant_id=uuid.uuid4(), connector=connector, control=control, test=test, today=date(2026, 9, 17),
              observed_text="", summary="s", evidence=None)
    r1 = await ccm_runner.record_result(FakeDB(), result="failed", observed_day=date(2026, 9, 16), pass_rate=90.0, **kw)
    assert test.failing_since == date(2026, 9, 16) and r1.alert_key and not r1.was_failing
    r2 = await ccm_runner.record_result(FakeDB(), result="failed", observed_day=date(2026, 9, 17), pass_rate=91.0, **kw)
    assert test.failing_since == date(2026, 9, 16) and r2.was_failing
    await ccm_runner.record_result(FakeDB(), result="error", observed_day=date(2026, 9, 17), pass_rate=0, **kw)
    assert test.failing_since == date(2026, 9, 16) and test.pass_rate == 91.0 and test.last_result == CcmResult.error
    await ccm_runner.record_result(FakeDB(), result="passed", observed_day=date(2026, 9, 17), pass_rate=100.0, **kw)
    assert test.failing_since is None and connector.last_sync == date(2026, 9, 17)
    assert control.effectiveness == ControlEffectiveness.partially_effective


async def test_follow_up_passes_do_not_close_and_metric_only_opens_nothing(issue_env):
    control = _control()
    test = _test(control_id=control.id, issue_id=uuid.uuid4())
    db = FakeDB({"AutomatedControlTest": [test]})
    out = await ccm_runner.follow_up(db, tenant_id=uuid.uuid4(), test=test, control=control, run=None, result="passed",
                                     day=date(2026, 9, 17), actor="A", summary="0 of 10", exceptions=0, population=10,
                                     pass_rate=100.0, metric_value=None, was_failing=True)
    assert out.issue_reference == "" and [type(o).__name__ for o in db.added] == ["IssueUpdate"]
    assert "close the issue" in db.added[0].note
    metric = _test(control_id=control.id, parameters={"metric_only": True})
    out = await ccm_runner.follow_up(FakeDB({"AutomatedControlTest": []}), tenant_id=uuid.uuid4(), test=metric, control=control,
                                     run=None, result="failed", day=date(2026, 9, 17), actor="A", summary="x", exceptions=5,
                                     population=10, pass_rate=50.0, metric_value=None, was_failing=False)
    assert out.issue_reference == "" and issue_env.refs == 0


# ============================================================ reliance signal ===
def test_reliance_note_reads_the_monitoring_signal():
    control = SimpleNamespace(status=None, next_audit_date=None, audit_findings=[], monitoring_failing_since=date(2026, 9, 12))
    note = control_assurance.reliance_note(control, [])
    assert note == "its continuous monitoring has been failing since 12 Sep 2026"
    assert control_assurance.control_health_state(reliance=note, basis="tests", reviewed_tests=1) == control_assurance.HEALTH_ISSUES
    control.monitoring_failing_since = None
    assert control_assurance.reliance_note(control, []) == ""


def test_monitoring_state_words():
    from app.api.v1 import integrations as api

    t = lambda **kw: _test(**{"last_run_at": NOW, **kw})  # noqa: E731
    assert api.monitoring_state([], NOW) == "not_monitored"
    assert api.monitoring_state([t(status=CcmStatus.paused)], NOW) == "paused"
    assert api.monitoring_state([t(last_result=CcmResult.passed), t(last_result=CcmResult.failed)], NOW) == "failing"
    assert api.monitoring_state([t(last_result=CcmResult.passed), t(last_result=CcmResult.error)], NOW) == "error"
    assert api.monitoring_state([t(last_result=CcmResult.not_run)], NOW) == "not_run"
    assert api.monitoring_state([t(last_result=CcmResult.passed)], NOW) == "passing"


def test_exception_csv_quotes_formulas():
    from app.api.v1 import integrations as api

    text = api.exceptions_csv([{"account": "=cmd", "days": 3}, {"account": "b", "note": "x"}])
    assert text.splitlines() == ["account,days,note", "'=cmd,3,", "b,,x"]


# =============================================================== rate limit ===
def test_the_feed_limiter_uses_the_shared_bucket(monkeypatch):
    from app.core.config import settings
    from app.services import ccm_rate_limit

    monkeypatch.setattr(settings, "ccm_ingest_rate_per_minute", 3)
    limiter = ccm_rate_limit.feed_limiter()
    assert (limiter.name, limiter.capacity, limiter.per_second) == ("connector-ingest", 3, 3 / 60)
    assert [limiter.hit_memory("c", now=0).allowed for _ in range(4)] == [True, True, True, False]
    assert limiter.hit_memory("other", now=0).allowed  # per key
    denied = limiter.hit_memory("c", now=0)
    assert not denied.allowed and 0 < denied.retry_after <= 20
    assert limiter.hit_memory("c", now=20.5).allowed


async def test_the_feed_answers_429_when_a_token_floods(monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi import HTTPException

    from app.api.v1 import integrations as api
    from app.services import ccm_rate_limit

    tenant, connector = uuid.uuid4(), uuid.uuid4()
    token = api.new_ingest_token(tenant, connector)

    @asynccontextmanager
    async def session(tid):
        yield None

    async def ok(db, tok, tid, cid):
        return None

    monkeypatch.setattr(api, "tenant_session", session)
    monkeypatch.setattr(api, "_feed_connector", ok)
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    limiter = RateLimiter("test-ingest", capacity=2, per_second=1e-6)
    monkeypatch.setattr(ccm_rate_limit, "feed_limiter", lambda: limiter)
    creds = SimpleNamespace(scheme="Bearer", credentials=token)
    await api._verified_ingest(creds)
    await api._verified_ingest(creds)
    with pytest.raises(HTTPException) as exc:
        await api._verified_ingest(creds)
    assert exc.value.status_code == 429 and "Retry-After" in exc.value.headers


# ============================================================ end to end (fake) ===
async def test_run_now_records_evidence_run_issue_and_signal(issue_env, monkeypatch):
    from zoneinfo import ZoneInfo

    from app.models.enums import ControlEffectiveness
    from app.models.integrations import ConnectorStatus
    from app.services import incident_clock, master_data

    async def zone(db, tid):
        return ZoneInfo("Asia/Karachi")

    async def owners(db, ids):
        return {}

    monkeypatch.setattr(incident_clock, "tenant_zone", zone)
    monkeypatch.setattr(master_data, "users_by_id", owners)
    tenant = uuid.uuid4()
    control = _control(effectiveness=ControlEffectiveness.effective)
    connector = SimpleNamespace(id=uuid.uuid4(), name="Corporate AD", reference="CON-001", status=ConnectorStatus.configured,
                                connector_type=SimpleNamespace(value="active_directory"), config={"base_dn": "DC=bank,DC=local"},
                                secrets_encrypted="", timeout_seconds=10, last_sync=None, deleted=False)
    test = _test(control_id=control.id, connector_id=connector.id, parameters={"approved_accounts": []},
                 check_type="ad_password_never_expires", threshold_max_failures=None, threshold_max_percent=None,
                 population_description="", pass_rate=0, last_error="")
    db = FakeDB({"Connector": connector, "Control": control, "Notification": None, "AutomatedControlTest": [test]})
    entries = [_user("jdoe", uac=512 | 0x10000), _user("ok")]
    report = await ccm_runner.execute_test(db, test, tenant_id=tenant, now=NOW,
                                           ldap_factory=lambda c, s, t: FakeLdap(lambda b, f: entries))
    assert report.result == "failed" and report.issue_reference == "ISS-101"
    run = report.run
    assert (run.population_size, run.exceptions_count, run.pass_rate, run.source) == (2, 1, 50.0, "run_now")
    assert run.exceptions_sample == [{"account": "jdoe", "dn": "CN=jdoe,OU=Users,DC=bank,DC=local", "password_last_set": ""}]
    evidence = [o for o in db.added if type(o).__name__ == "Evidence"][0]
    assert evidence.control_id == control.id and run.evidence_id == evidence.id and "jdoe" in evidence.description
    assert control.monitoring_failing_since == date(2026, 9, 17) and test.failing_since == date(2026, 9, 17)
    assert connector.status == ConnectorStatus.active and control.effectiveness == ControlEffectiveness.effective
    assert "not relied on" not in control_assurance.reliance_note(control, []) and control_assurance.reliance_note(control, [])


async def test_an_unreachable_directory_is_an_error_run_without_evidence(issue_env, monkeypatch):
    from zoneinfo import ZoneInfo

    from app.models.integrations import ConnectorStatus
    from app.services import incident_clock

    async def zone(db, tid):
        return ZoneInfo("Asia/Karachi")

    monkeypatch.setattr(incident_clock, "tenant_zone", zone)
    control = _control()
    connector = SimpleNamespace(id=uuid.uuid4(), name="AD", reference="CON-001", status=ConnectorStatus.active,
                                connector_type=SimpleNamespace(value="active_directory"), config={"base_dn": "DC=x"},
                                secrets_encrypted="", timeout_seconds=5, last_sync=None, deleted=False)
    test = _test(control_id=control.id, connector_id=connector.id, check_type="ad_password_never_expires",
                 threshold_max_failures=None, threshold_max_percent=None, population_description="", pass_rate=80, last_error="")
    db = FakeDB({"Connector": connector, "Control": control, "Notification": None, "AutomatedControlTest": [test]})

    def refuse(c, s, t):
        raise ccm_checks.ConnectionFailure("Could not reach dc01:636: timed out.")

    report = await ccm_runner.execute_test(db, test, tenant_id=uuid.uuid4(), now=NOW, ldap_factory=refuse)
    assert report.result == "error" and report.evidence_id is None and issue_env.refs == 0
    assert test.last_result == CcmResult.error and "timed out" in test.last_error and connector.status == ConnectorStatus.error
    assert [n.dedup_key.split(":")[1] for n in db.added if type(n).__name__ == "Notification"] == ["ccm-error"]


async def test_scan_findings_upsert_into_the_register_linked_by_host(issue_env, monkeypatch):
    from app.models.vulnerability import VulnSeverity, VulnSource
    from app.services import refs

    async def ref(db, model, prefix):
        return f"{prefix}-900"

    monkeypatch.setattr(refs, "next_reference", ref)
    asset = SimpleNamespace(id=uuid.uuid4(), hostname="atm-sw01.bank.local", ip_address="")
    known = SimpleNamespace(cve_id="CVE-2026-2222", title="SSL Certificate Expired", asset_ip="10.1.1.7", asset_name="atm-sw01",
                            severity=VulnSeverity.high, asset_id=None, discovered_date=date(2026, 6, 1))
    db = FakeDB({"VulnFinding": [known], "Asset": [asset]})
    findings = vuln_import.parse_qualys_csv(QUALYS)
    out = await ccm_runner.upsert_vulnerabilities(db, tenant_id=uuid.uuid4(), findings=findings, source="qualys",
                                                  today=date(2026, 9, 17), actor="Connector Qualys")
    assert out == {"created": 1, "updated": 1, "linked_to_assets": 2, "capped": False}
    assert known.severity == VulnSeverity.critical and known.asset_id == asset.id
    new = [o for o in db.added if type(o).__name__ == "VulnFinding"][0]
    assert (new.source, new.asset_id, new.reference, new.discovered_date) == (VulnSource.qualys, asset.id, "VLN-900", date(2026, 9, 10))
    assert new.due_date == date(2026, 10, 10)  # high: 30 days
