"""Vulnerability scanner exports: Nessus (``.nessus`` v2 XML), Qualys (CSV) and OpenVAS /
Greenbone (report XML).

Each parser turns a file into :class:`Finding` rows; the check counts the findings at the
chosen severities and flags those open longer than the remediation SLA. Pure — the
register upsert (``VulnFinding``, linked to assets by hostname or IP) is done by the
runner with the findings this returns.

**Age.** A scan says what is open now, not since when. ``age_from``:

* ``first_detected`` (default) — the first time the finding was seen: the register's
  discovered date when it is already there, else the scanner's own first-detected date
  (Qualys), else the scan date (so a finding new to the register starts at 0 days);
* ``patch_published`` — how long a fix has been available (Nessus
  ``patch_publication_date``, else its ``vuln_publication_date``), else as above.

XML is parsed with the standard library; a document declaring a DTD or entities is
refused (no scanner export needs one), which closes entity-expansion attacks without
``defusedxml``.
"""
from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime

from app.services.ccm_checks.base import CheckContext, CheckError, CheckOutcome, CheckSpec, Param, as_list

SEVERITIES = ("critical", "high", "medium", "low", "informational")
#: The register's SLA (``models.vulnerability._SLA_BY_SEVERITY``), days.
DEFAULT_SLA_DAYS = {"critical": 7, "high": 30, "medium": 90, "low": 180, "informational": 365}
MAX_FINDINGS = 200_000


@dataclass
class Finding:
    host: str
    ip: str
    title: str
    severity: str
    plugin_id: str = ""
    cves: list[str] = field(default_factory=list)
    cvss: float | None = None
    port: str = ""
    first_seen: date | None = None
    patch_published: date | None = None
    solution: str = ""
    description: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return finding_key(self.cves[0] if self.cves else "", self.plugin_id or self.title, self.ip or self.host)


def finding_key(cve: str, plugin_or_title: str, where: str) -> tuple[str, str]:
    """How one finding on one host is recognised across scans and in the register."""
    what = (cve or plugin_or_title or "").strip().lower()
    return what, (where or "").strip().lower()


# ------------------------------------------------------------------- helpers ---
def _safe_xml(content: bytes) -> ET.Element:
    head = content[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in content.lower():
        raise CheckError("The file declares a DTD or entities, which scanner exports never need; it was not read.")
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise CheckError(f"The file is not well-formed XML: {exc}.") from exc


def _date(text: str | None) -> date | None:
    value = (text or "").strip()
    if not value:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
                "%d/%m/%Y", "%a %b %d %H:%M:%S %Y", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _float(text) -> float | None:
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def severity_from_cvss(score: float | None) -> str:
    if score is None:
        return "informational"
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score > 0:
        return "low"
    return "informational"


_CVE = re.compile(r"CVE-\d{4}-\d{4,}", re.I)


# -------------------------------------------------------------------- Nessus ---
_NESSUS_SEVERITY = {"4": "critical", "3": "high", "2": "medium", "1": "low", "0": "informational"}


def parse_nessus(content: bytes) -> list[Finding]:
    root = _safe_xml(content)
    if root.tag != "NessusClientData_v2":
        raise CheckError("Not a Nessus v2 export (.nessus): the root element is not NessusClientData_v2.")
    out: list[Finding] = []
    for host in root.iter("ReportHost"):
        tags = {t.get("name", ""): (t.text or "").strip() for t in host.iter("tag")}
        ip = tags.get("host-ip", "")
        name = tags.get("host-fqdn") or tags.get("netbios-name") or host.get("name", "") or ip
        scanned = _date(tags.get("HOST_END") or tags.get("HOST_START"))
        for item in host.findall("ReportItem"):
            sev = _NESSUS_SEVERITY.get(item.get("severity", "0"), "informational")
            cvss = _float(item.findtext("cvss3_base_score")) or _float(item.findtext("cvss_base_score"))
            out.append(Finding(
                host=name, ip=ip, title=(item.get("pluginName") or item.findtext("plugin_name") or "").strip(),
                severity=sev, plugin_id=f"nessus:{item.get('pluginID', '')}",
                cves=[(c.text or "").strip().upper() for c in item.findall("cve") if (c.text or "").strip()],
                cvss=cvss, port=f"{item.get('port', '')}/{item.get('protocol', '')}".strip("/"),
                first_seen=scanned,
                patch_published=_date(item.findtext("patch_publication_date")) or _date(item.findtext("vuln_publication_date")),
                solution=(item.findtext("solution") or "").strip(), description=(item.findtext("synopsis") or "").strip(),
            ))
            if len(out) > MAX_FINDINGS:
                raise CheckError(f"More than {MAX_FINDINGS} findings in one file; split the export.")
    return out


# -------------------------------------------------------------------- Qualys ---
_QUALYS_SEVERITY = {"5": "critical", "4": "high", "3": "medium", "2": "low", "1": "informational"}


def _col(row: dict, *names: str) -> str:
    lowered = {str(k or "").strip().lower(): v for k, v in row.items()}
    for n in names:
        v = lowered.get(n.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def parse_qualys_csv(content: bytes) -> list[Finding]:
    text = content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    header_at = next((i for i, line in enumerate(lines[:200])
                      if "qid" in line.lower() and ("ip" in line.lower() or "dns" in line.lower())), None)
    if header_at is None:
        raise CheckError("Not a Qualys CSV export: no header row with QID and IP columns in the first 200 lines.")
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_at:])))
    out: list[Finding] = []
    for row in reader:
        qid = _col(row, "QID")
        if not qid or not qid.strip().isdigit():
            continue  # a footer or a blank line
        vtype = _col(row, "Type", "Vuln Type").lower()
        if vtype.startswith("ig") or vtype in ("info", "information gathered"):
            continue
        status = _col(row, "Vuln Status", "Status").lower()
        if status == "fixed":
            continue
        ip = _col(row, "IP", "IP Address")
        cves = [c.upper() for c in _CVE.findall(_col(row, "CVE ID", "CVE"))]
        out.append(Finding(
            host=_col(row, "DNS", "DNS Name", "FQDN", "NetBIOS") or ip, ip=ip, title=_col(row, "Title"),
            severity=_QUALYS_SEVERITY.get(_col(row, "Severity"), "medium"), plugin_id=f"qualys:{qid}", cves=cves,
            cvss=_float(_col(row, "CVSS3.1 Base", "CVSS3 Base", "CVSS Base")),
            port=_col(row, "Port"), first_seen=_date(_col(row, "First Detected")),
            solution=_col(row, "Solution"), description=_col(row, "Threat"),
        ))
        if len(out) > MAX_FINDINGS:
            raise CheckError(f"More than {MAX_FINDINGS} findings in one file; split the export.")
    return out


# ------------------------------------------------------------------- OpenVAS ---
def parse_openvas_xml(content: bytes) -> list[Finding]:
    root = _safe_xml(content)
    results = list(root.iter("result"))
    if root.tag not in ("report", "get_reports_response") and not results:
        raise CheckError("Not an OpenVAS / Greenbone report: no <report> with <result> elements.")
    scan_start = _date(root.findtext(".//scan_start") or root.findtext(".//creation_time"))
    out: list[Finding] = []
    for r in results:
        host_el = r.find("host")
        if host_el is None:
            continue  # a result summary, not a finding
        ip = (host_el.text or "").strip()
        hostname = (host_el.findtext("hostname") or "").strip()
        nvt = r.find("nvt")
        score = _float(r.findtext("severity"))
        threat = (r.findtext("threat") or "").strip().lower()
        if threat in ("log", "debug", "false positive") or (score is not None and score <= 0):
            continue
        cves: list[str] = []
        if nvt is not None:
            cves = [ref.get("id", "").upper() for ref in nvt.iter("ref") if ref.get("type", "").lower() == "cve"]
            cves += [c.upper() for c in _CVE.findall(nvt.findtext("cve") or "")]
        out.append(Finding(
            host=hostname or ip, ip=ip, title=(r.findtext("name") or (nvt.findtext("name") if nvt is not None else "") or "").strip(),
            severity=severity_from_cvss(score), plugin_id=f"openvas:{nvt.get('oid', '') if nvt is not None else ''}",
            cves=sorted(set(c for c in cves if c)), cvss=score, port=(r.findtext("port") or "").strip(),
            first_seen=_date(r.findtext("creation_time")) or scan_start,
            solution=((nvt.findtext("solution") if nvt is not None else "") or "").strip(),
            description=(r.findtext("description") or "").strip()[:2000],
        ))
        if len(out) > MAX_FINDINGS:
            raise CheckError(f"More than {MAX_FINDINGS} findings in one file; split the export.")
    return out


PARSERS = {"nessus": parse_nessus, "qualys": parse_qualys_csv, "openvas": parse_openvas_xml}


def detect_format(filename: str, content: bytes) -> str:
    name = (filename or "").lower()
    head = content[:2048].lstrip().lower()
    if name.endswith(".nessus") or b"<nessusclientdata" in head:
        return "nessus"
    if head.startswith(b"<") or name.endswith(".xml"):
        return "openvas"
    return "qualys"


def dedupe(findings: list[Finding]) -> list[Finding]:
    """One row per finding per host (a plugin firing on several ports counts once)."""
    seen: dict[tuple[str, str], Finding] = {}
    for f in findings:
        current = seen.get(f.key)
        if current is None or SEVERITIES.index(f.severity) < SEVERITIES.index(current.severity):
            seen[f.key] = f
    return list(seen.values())


# --------------------------------------------------------------------- check ---
def age_start(f: Finding, age_from: str, known: dict) -> date | None:
    known_first = known.get(f.key)
    detected = min(d for d in (known_first, f.first_seen) if d is not None) if (known_first or f.first_seen) else None
    if age_from == "patch_published" and f.patch_published is not None:
        return f.patch_published
    return detected


def vulnerability_scan(ctx: CheckContext) -> CheckOutcome:
    if ctx.file is None:
        raise CheckError("No scan file: upload an export or set the connector's import folder.")
    p = ctx.parameters
    fmt = str(p.get("format") or "auto")
    if fmt == "auto":
        fmt = detect_format(ctx.file.filename, ctx.file.content)
    parser = PARSERS.get(fmt)
    if parser is None:
        raise CheckError(f"Unknown scanner format '{fmt}'.")
    findings = dedupe(parser(ctx.file.content))
    wanted = [s for s in as_list(p.get("severities")) if s in SEVERITIES] or ["critical", "high"]
    sla = dict(DEFAULT_SLA_DAYS)
    for k, v in (p.get("sla_days") or {}).items() if isinstance(p.get("sla_days"), dict) else ():
        try:
            sla[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    age_from = str(p.get("age_from") or "first_detected")
    in_scope = [f for f in findings if f.severity in wanted]
    exceptions = []
    by_severity: dict[str, int] = {}
    for f in in_scope:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        start = age_start(f, age_from, ctx.known_first_seen)
        age = (ctx.today - start).days if start else 0
        if age > sla.get(f.severity, 30):
            exceptions.append({
                "host": f.host, "ip": f.ip, "severity": f.severity, "title": f.title[:200],
                "cve": ", ".join(f.cves[:5]), "age_days": age, "sla_days": sla.get(f.severity),
                "since": start.isoformat() if start else "",
            })
    exceptions.sort(key=lambda r: (SEVERITIES.index(r["severity"]), -r["age_days"]))
    hosts = len({(f.ip or f.host).lower() for f in findings})
    return CheckOutcome(
        population=len(in_scope), exceptions=exceptions,
        summary=(f"{len(exceptions)} of {len(in_scope)} {'/'.join(wanted)} finding(s) on {hosts} host(s) are "
                 f"past their remediation SLA ({fmt} export {ctx.file.filename})"),
        metric_value=float(len(exceptions)),
        details={"format": fmt, "file": ctx.file.filename, "hosts": hosts, "findings_total": len(findings),
                 "by_severity": by_severity, "sla_days": {s: sla[s] for s in wanted}, "age_from": age_from},
        vulnerabilities=in_scope,
    )


def _validate(params: dict) -> list[str]:
    errors = []
    bad = [s for s in as_list(params.get("severities")) if s not in SEVERITIES]
    if bad:
        errors.append(f"Severities: unknown {', '.join(bad)} (use {', '.join(SEVERITIES)}).")
    sla = params.get("sla_days")
    if sla not in (None, "", {}) and not isinstance(sla, dict):
        errors.append('SLA days: a JSON object such as {"critical": 7, "high": 30}.')
    return errors


SPECS = (
    CheckSpec(
        key="vuln_scan_sla", label="Scanner findings past remediation SLA", group="Vulnerability scanning",
        description=("Reads a Nessus (.nessus), Qualys (CSV) or OpenVAS (XML) export, counts findings at the chosen "
                     "severities and flags those open longer than the SLA. Can update the Vulnerability register."),
        connector_types=("vuln_scanner", "csv_feed"), input="file",
        params=(
            Param("format", "File format", "select", default="auto", options=("auto", "nessus", "qualys", "openvas")),
            Param("severities", "Severities in scope", "list", default=["critical", "high"],
                  help="critical, high, medium, low — one per line."),
            Param("sla_days", "SLA days by severity", "json", default=dict(DEFAULT_SLA_DAYS),
                  help='Days allowed to remediate, e.g. {"critical": 7, "high": 30}.'),
            Param("age_from", "Measure age from", "select", default="first_detected",
                  options=("first_detected", "patch_published"),
                  help="first_detected: first seen (register or scanner); patch_published: when a fix became available (Nessus)."),
            Param("upsert_register", "Update the Vulnerability register", "bool", default=False,
                  help="Add new findings and link them to assets by hostname or IP. Existing findings keep their status."),
        ),
        pass_criterion="No finding at the chosen severities is open longer than its remediation SLA.",
        population="Findings at the chosen severities in the latest scan export.",
        run=vulnerability_scan, validate=_validate,
    ),
)
