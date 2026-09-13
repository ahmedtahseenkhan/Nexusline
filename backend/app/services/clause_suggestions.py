"""Suggest framework clauses for an existing control (D-03).

A bank's catalogue is full of controls named "MFA for internet banking" or "Privileged
access management" that were never linked to a clause, because mapping is one record at
a time and ``SCENARIO_CONTROLS`` only resolves exact catalogue references. This module
proposes the links; a person accepts them. It never writes anything itself.

Candidates are the requirements of the organisation's *installed* compliance frameworks
(live, ``kind == "compliance"``, not excluded from the Statement of Applicability). Each
is scored for a control from four signals, all deterministic and offline:

1. **The control's own reference.** A control keyed ``A.8.5`` or ``CIS 6.3`` is that
   clause's control; it just was not linked.
2. **A curated synonym table** (:data:`TOPICS`): "MFA", "2FA", "multi-factor" → ISO
   A.8.5, PCI 8.4/8.5, NIST CSF PR.AA-03, SBP CS-3.3, ETGRM-3.5 … Every reference in it
   exists in a library template (pinned by ``tests/test_clause_suggestions.py``). A
   topic found in the control's *name* counts more than one found only in its
   description, and the first topic in the name — the thing the control *is*, as in
   "MFA for privileged access" — counts most.
3. **Keyword overlap** between the control's name, description and objective and the
   clause's title and description: TF-IDF cosine over a light-stemmed, stop-worded
   vocabulary, weighted towards titles and names.
4. **Propagation.** A clause suggested on its own merits pulls in, at a lower score,
   the clauses crosswalked to it (``requirement_crosswalks``) and the clauses that the
   scenario library lists alongside it for the same risk scenarios
   (``control_mapping.SCENARIO_CONTROLS``, read in reverse).

The pure core (:func:`score_candidates`) takes plain data so the rules are unit-tested;
the async functions at the bottom load that data for a tenant.
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Iterable

from app.services import control_mapping
from app.services.framework_library import TEMPLATES, template_key_for_name


# ---------------------------------------------------------------------------
# Synonym table
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Topic:
    key: str
    label: str
    #: Phrases that name the topic, matched as whole words on stemmed text.
    patterns: tuple[str, ...]
    #: Template key -> template-native references, strongest first.
    refs: dict[str, tuple[str, ...]]


ISO = "iso-27001-2022"
PCI = "pci-dss-4.0"
CSF = "nist-csf-2.0"
CIS = "cis-controls-v8"
N53 = "nist-800-53-r5"
SOC = "soc-2-2017"
GDPR = "gdpr"
CS = "sbp-cybersecurity"
ETGRM = "sbp-etgrm"
OS = "sbp-outsourcing"
BCP = "sbp-bcp"

TOPICS: tuple[Topic, ...] = (
    Topic("mfa", "Multi-factor authentication",
          ("mfa", "multi factor", "multifactor", "2fa", "two factor", "two step verification",
           "strong authentication", "one time password", "otp"),
          {ISO: ("A.8.5",), PCI: ("8.4", "8.5", "8.4.2"), CSF: ("PR.AA-03",),
           CIS: ("6.3", "6.4", "6.5"), N53: ("IA-2",), SOC: ("CC6.1",),
           CS: ("CS-3.3",), ETGRM: ("ETGRM-3.5",)}),
    Topic("pam", "Privileged access",
          ("pam", "privileged access", "privileged account", "privileged user", "privileged identity",
           "privileged", "admin account", "administrator account", "administrative access",
           "admin access", "superuser", "root access"),
          {ISO: ("A.8.2", "A.8.18"), PCI: ("7.2", "7.2.1"), CSF: ("PR.AA-05",),
           CIS: ("5.4", "6.5", "12.8"), N53: ("AC-6",), SOC: ("CC6.3",),
           CS: ("CS-3.4",), ETGRM: ("ETGRM-3.5",)}),
    Topic("access_control", "Access control and identity management",
          ("access control", "access management", "identity management", "identity and access",
           "iam", "user provisioning", "provisioning", "deprovisioning", "de provisioning",
           "joiner mover leaver", "leaver", "least privilege", "role based access", "rbac",
           "need to know"),
          {ISO: ("A.5.15", "A.5.16", "A.5.18", "A.8.3"), PCI: ("7.1", "7.2", "8.2"),
           CSF: ("PR.AA-01", "PR.AA-05"), CIS: ("6.1", "6.2", "6.7", "6.8", "5.1"),
           N53: ("AC-2", "AC-3", "AC-6"), SOC: ("CC6.1", "CC6.2", "CC6.3"),
           CS: ("CS-3.1", "CS-3.2"), ETGRM: ("ETGRM-3.4",)}),
    Topic("access_review", "Access review",
          ("access review", "user access review", "access recertification", "recertification",
           "entitlement review", "review of access", "access right review", "access certification",
           "periodic access review"),
          {ISO: ("A.5.18",), PCI: ("7.2", "7.3"), CSF: ("PR.AA-05",), CIS: ("6.1", "6.2", "5.3"),
           N53: ("AC-2",), SOC: ("CC6.2", "CC6.3"), CS: ("CS-3.2",), ETGRM: ("ETGRM-3.4",)}),
    Topic("password", "Passwords and credentials",
          ("password", "passphrase", "credential", "authentication information", "password policy"),
          {ISO: ("A.5.17",), PCI: ("8.3", "8.3.1"), CSF: ("PR.AA-01",), CIS: ("5.2",),
           N53: ("IA-5",), ETGRM: ("ETGRM-3.5",)}),
    Topic("encryption", "Encryption and cryptography",
          ("encryption", "encrypt", "cryptography", "cryptographic", "crypto", "key management",
           "tls", "ssl", "hsm", "hardware security module", "pki", "certificate management"),
          {ISO: ("A.8.24",), PCI: ("3.5", "4.2", "3.5.1", "4.2.1", "3.6", "3.7"),
           CSF: ("PR.DS-01", "PR.DS-02"), CIS: ("3.11", "3.10", "3.6", "3.9"),
           N53: ("SC-13", "SC-28", "SC-8", "SC-12"), SOC: ("CC6.7",), GDPR: ("Art. 32",),
           CS: ("CS-3.10",), ETGRM: ("ETGRM-3.8",)}),
    Topic("logging", "Logging",
          ("logging", "log management", "audit log", "audit trail", "event log", "log retention",
           "log collection", "syslog", "siem"),
          {ISO: ("A.8.15",), PCI: ("10.2", "10.2.1", "10.3", "10.5"), CSF: ("PR.PS-04",),
           CIS: ("8.2", "8.9", "8.10"), N53: ("AU-2", "AU-12"), CS: ("CS-4.2", "CS-4.5"),
           ETGRM: ("ETGRM-3.10",)}),
    Topic("monitoring", "Security monitoring",
          ("security monitoring", "siem", "log review", "log monitoring", "continuous monitoring",
           "monitoring activity", "anomaly detection", "threat detection", "security operation",
           "security event", "use case monitoring", "alerting"),
          {ISO: ("A.8.16",), PCI: ("10.4", "10.4.1", "10.7", "11.5"),
           CSF: ("DE.CM-01", "DE.CM-09", "DE.AE-02", "DE.AE-03"), CIS: ("8.11", "13.1"),
           N53: ("SI-4", "AU-6"), SOC: ("CC7.2",), CS: ("CS-4.1", "CS-4.3", "CS-4.6"),
           ETGRM: ("ETGRM-3.10",)}),
    Topic("backup", "Backup and restore",
          ("backup", "back up", "restore", "restoration", "data recovery", "recovery point",
           "restore test", "offsite storage", "off site storage"),
          {ISO: ("A.8.13",), CSF: ("PR.DS-11", "RC.RP-03"), CIS: ("11.2", "11.5", "11.3", "11.1", "11.4"),
           N53: ("CP-9", "CP-10"), SOC: ("A1.2",), CS: ("CS-6.3",), ETGRM: ("ETGRM-4.6",),
           BCP: ("BCP-9.3", "BCP-9.4")}),
    Topic("vulnerability", "Vulnerability and patch management",
          ("vulnerability", "patch", "patching", "patch management", "vulnerability scan",
           "vulnerability assessment", "security update", "remediation of vulnerability"),
          {ISO: ("A.8.8",), PCI: ("6.3", "11.3", "6.3.1", "6.3.3", "11.3.1"),
           CSF: ("ID.RA-01", "PR.PS-02"), CIS: ("7.1", "7.3", "7.4", "7.5", "7.2", "7.7"),
           N53: ("RA-5", "SI-2"), SOC: ("CC7.1",), CS: ("CS-3.8", "CS-2.5"),
           ETGRM: ("ETGRM-3.9", "ETGRM-4.9")}),
    Topic("pentest", "Penetration testing",
          ("penetration test", "pen test", "pentest", "red team", "ethical hacking"),
          {ISO: ("A.8.8",), PCI: ("11.4", "11.4.1"), CIS: ("18.1", "18.2", "18.5", "16.13"),
           N53: ("CA-8",), CS: ("CS-4.9",)}),
    Topic("incident", "Incident response",
          ("incident response", "incident management", "incident handling", "security incident",
           "incident", "csirt", "breach response", "breach notification", "incident reporting"),
          {ISO: ("A.5.24", "A.5.25", "A.5.26", "A.5.27", "A.6.8"), PCI: ("12.10", "12.10.1"),
           CSF: ("RS.MA-01", "RS.MA-02", "RS.MI-01"), CIS: ("17.4", "17.1", "17.3", "17.8"),
           N53: ("IR-4", "IR-8"), SOC: ("CC7.3", "CC7.4"), GDPR: ("Art. 33", "Art. 34"),
           CS: ("CS-5.1", "CS-5.4", "CS-5.8"), ETGRM: ("ETGRM-4.5",)}),
    Topic("awareness", "Security awareness and training",
          ("awareness", "security training", "awareness training", "phishing simulation",
           "phishing exercise", "security education", "training"),
          {ISO: ("A.6.3",), PCI: ("12.6",), CSF: ("PR.AT-01", "PR.AT-02"),
           CIS: ("14.1", "14.2", "14.9"), N53: ("AT-2", "AT-3"),
           CS: ("CS-8.1", "CS-8.2", "CS-8.4")}),
    Topic("change", "Change management",
          ("change management", "change control", "change request", "change advisory",
           "release management", "change approval", "emergency change"),
          {ISO: ("A.8.32",), PCI: ("6.5",), CSF: ("ID.RA-07", "PR.PS-01"), N53: ("CM-3",),
           SOC: ("CC8.1",), CS: ("CS-3.9",), ETGRM: ("ETGRM-4.2", "ETGRM-4.9")}),
    Topic("network", "Network security",
          ("firewall", "network security", "network segmentation", "segmentation",
           "segregation of network", "intrusion detection", "intrusion prevention", "perimeter",
           "dmz", "vpn", "remote access", "network access control", "waf",
           "web application firewall", "ddos"),
          {ISO: ("A.8.20", "A.8.21", "A.8.22"), PCI: ("1.2", "1.3", "1.4", "1.2.1"),
           CSF: ("PR.IR-01", "DE.CM-01"), CIS: ("4.4", "4.5", "12.2", "13.4", "13.3", "12.7"),
           N53: ("SC-7", "AC-17"), SOC: ("CC6.6",), CS: ("CS-3.5", "CS-3.6", "CS-4.4"),
           ETGRM: ("ETGRM-3.6",)}),
    Topic("asset_inventory", "Asset inventory",
          ("asset inventory", "asset register", "inventory of asset", "cmdb",
           "configuration management database", "asset management", "hardware inventory",
           "software inventory", "information asset register"),
          {ISO: ("A.5.9",), CSF: ("ID.AM-01", "ID.AM-02", "ID.AM-07"), CIS: ("1.1", "2.1", "3.2"),
           N53: ("CM-8",), CS: ("CS-2.1",), ETGRM: ("ETGRM-4.3",)}),
    Topic("supplier", "Supplier and third-party risk",
          ("supplier", "vendor", "third party", "service provider", "outsourcing", "outsourced",
           "tpsp", "subcontractor", "sub contractor"),
          {ISO: ("A.5.19", "A.5.20", "A.5.21", "A.5.22"), PCI: ("12.8", "12.8.1", "12.9"),
           CSF: ("GV.SC-01", "GV.SC-05", "GV.SC-06", "GV.SC-07"),
           CIS: ("15.1", "15.2", "15.4", "15.5", "15.6"), N53: ("SA-9", "SR-6"),
           SOC: ("CC9.2",), GDPR: ("Art. 28",), CS: ("CS-7.1", "CS-7.2", "CS-7.3", "CS-7.4"),
           ETGRM: ("ETGRM-7.3", "ETGRM-7.4", "ETGRM-7.5"),
           OS: ("OS-3.1", "OS-4.1", "OS-5.1", "OS-5.2")}),
    Topic("cloud", "Cloud services",
          ("cloud", "saas", "iaas", "paas"),
          {ISO: ("A.5.23",), ETGRM: ("ETGRM-7.7",), OS: ("OS-8.1", "OS-8.5")}),
    Topic("continuity", "Business continuity and disaster recovery",
          ("business continuity", "continuity plan", "bcp", "bcm", "disaster recovery", "dr",
           "drp", "dr test", "dr drill", "failover", "resilience", "crisis management",
           "recovery time objective", "rto", "rpo"),
          {ISO: ("A.5.29", "A.5.30", "A.8.14"), CSF: ("PR.IR-03", "RC.RP-01", "ID.IM-04"),
           CIS: ("11.1",), N53: ("CP-2", "CP-4", "CP-7"), SOC: ("CC9.1", "A1.3"),
           CS: ("CS-6.1", "CS-6.2", "CS-6.4", "CS-6.5"),
           ETGRM: ("ETGRM-6.1", "ETGRM-6.4", "ETGRM-6.5", "ETGRM-6.6"),
           BCP: ("BCP-5.1", "BCP-7.1", "BCP-9.1", "BCP-9.2"), OS: ("OS-7.1",)}),
    Topic("classification", "Information classification",
          ("data classification", "information classification", "classification", "labelling",
           "labeling", "information handling", "handling of information"),
          {ISO: ("A.5.12", "A.5.13"), CSF: ("ID.AM-05",), CIS: ("3.7",), N53: ("RA-2",),
           SOC: ("C1.1",), CS: ("CS-2.2",), ETGRM: ("ETGRM-3.3",)}),
    Topic("malware", "Malware protection",
          ("malware", "anti malware", "antimalware", "antivirus", "anti virus", "endpoint protection",
           "edr", "endpoint detection", "ransomware"),
          {ISO: ("A.8.7",), PCI: ("5.2", "5.3", "5.2.1"), CSF: ("DE.CM-09",),
           CIS: ("10.1", "10.2", "10.6", "10.7"), N53: ("SI-3",), SOC: ("CC6.8",),
           CS: ("CS-3.7",), ETGRM: ("ETGRM-3.7",)}),
    Topic("dlp", "Data leakage prevention",
          ("dlp", "data loss prevention", "data leakage", "data leak", "exfiltration"),
          {ISO: ("A.8.12",), CIS: ("3.13",), CS: ("CS-3.12",), ETGRM: ("ETGRM-3.11",)}),
    Topic("hardening", "Secure configuration",
          ("hardening", "secure configuration", "baseline configuration", "configuration baseline",
           "configuration management", "cis benchmark", "default password", "default account"),
          {ISO: ("A.8.9",), PCI: ("2.2", "2.2.1", "2.2.2"), CSF: ("PR.PS-01",),
           CIS: ("4.1", "4.2", "4.7"), N53: ("CM-6",), CS: ("CS-3.9",), ETGRM: ("ETGRM-4.3",)}),
    Topic("sod", "Segregation of duties",
          ("segregation of duty", "separation of duty", "maker checker", "four eye", "dual control",
           "sod"),
          {ISO: ("A.5.3",), N53: ("AC-5",), ETGRM: ("ETGRM-1.6",)}),
    Topic("physical", "Physical security",
          ("physical security", "physical access", "cctv", "access card", "data centre",
           "data center", "server room", "visitor", "physical entry"),
          {ISO: ("A.7.1", "A.7.2", "A.7.4"), PCI: ("9.2", "9.3"), CSF: ("PR.AA-06", "DE.CM-02"),
           N53: ("PE-3",), SOC: ("CC6.4",), CS: ("CS-3.15",), ETGRM: ("ETGRM-4.7",)}),
    Topic("secure_development", "Secure development",
          ("secure development", "sdlc", "secure coding", "code review", "application security",
           "sast", "dast", "devsecops", "secure software"),
          {ISO: ("A.8.25", "A.8.26", "A.8.28", "A.8.29"), PCI: ("6.2", "6.1", "6.2.1"),
           CSF: ("PR.PS-06",), CIS: ("16.1", "16.12"), CS: ("CS-3.14",),
           ETGRM: ("ETGRM-5.4", "ETGRM-5.5")}),
    Topic("capacity", "Capacity management",
          ("capacity management", "capacity planning", "capacity"),
          {ISO: ("A.8.6",), CSF: ("PR.IR-04",), SOC: ("A1.1",), ETGRM: ("ETGRM-4.4",)}),
    Topic("retention", "Records and retention",
          ("retention", "record management", "records management", "record keeping", "archiving"),
          {ISO: ("A.5.33",), PCI: ("3.2.1",), CIS: ("3.4",)}),
    Topic("disposal", "Secure disposal",
          ("disposal", "secure deletion", "data destruction", "media sanitisation",
           "media sanitization", "secure erase", "wiping"),
          {ISO: ("A.7.14", "A.8.10"), CIS: ("3.5",), N53: ("MP-6",), SOC: ("C1.2",), OS: ("OS-6.5",)}),
    Topic("privacy", "Privacy and personal data",
          ("privacy", "personal data", "pii", "personally identifiable", "data protection"),
          {ISO: ("A.5.34",), GDPR: ("Art. 5", "Art. 32")}),
    Topic("time_sync", "Clock synchronisation",
          ("time synchronization", "time synchronisation", "ntp", "clock synchronization",
           "clock synchronisation"),
          {ISO: ("A.8.17",), PCI: ("10.6",), CIS: ("8.4",)}),
)


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+")

#: English function words plus the words every GRC clause uses ("ensure", "maintain",
#: "information security"): they match everything, so they mean nothing.
STOPWORDS = frozenset(
    """a about above after all also an and any are as at be been being both but by can
    could do does each either for from had has have having how if in into is it its may
    more most must no nor not of on once only or other our out over own per same shall
    should so such than that the their them then there these they this those through to
    under until up upon was we were what when where which while who whom why will with
    within without would you your
    appropriate based defined define documented ensure established establish including
    information implement implemented maintain maintained organization organisation
    organizational relevant required requirement requirements security system systems
    use used using control controls process processes procedure procedures policy policies
    measure measures manage managed management level levels""".split()
)


def stem(word: str) -> str:
    """A deliberately small suffix stripper: enough that "backups", "logging" and
    "encrypted" meet "backup", "log" and "encrypt", and deterministic by construction."""
    w = word
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and w.endswith("sses"):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        w = w[:-3]
    elif len(w) > 4 and w.endswith("ed"):
        w = w[:-2]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiouls":
        w = w[:-1]
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    return w


def words(text: str | None) -> list[str]:
    """Lower-cased, punctuation-split, stemmed words (stop-words kept, for phrases)."""
    return [stem(w) for w in _WORD.findall((text or "").lower())]


def tokens(text: str | None) -> list[str]:
    """Keyword tokens: stemmed words without stop-words or single characters."""
    return [
        stem(w) for w in _WORD.findall((text or "").lower())
        if w not in STOPWORDS and len(w) > 1
    ]


def _phrase(pattern: str) -> tuple[str, ...]:
    return tuple(words(pattern))


_TOPIC_PHRASES: tuple[tuple[Topic, tuple[tuple[str, ...], ...]], ...] = tuple(
    (t, tuple(_phrase(p) for p in t.patterns)) for t in TOPICS
)


def _find(phrase: tuple[str, ...], seq: list[str]) -> int:
    """Index of the first occurrence of ``phrase`` in ``seq`` (whole words), or -1."""
    n = len(phrase)
    if not n:
        return -1
    for i in range(len(seq) - n + 1):
        if tuple(seq[i:i + n]) == phrase:
            return i
    return -1


def topics_in(text: str | None) -> list[tuple[Topic, int]]:
    """(topic, position of its first mention) for every topic named in ``text``,
    ordered by where it first appears — so the first is what the text is about."""
    seq = words(text)
    found: list[tuple[Topic, int]] = []
    for topic, phrases in _TOPIC_PHRASES:
        positions = [p for p in (_find(ph, seq) for ph in phrases) if p >= 0]
        if positions:
            found.append((topic, min(positions)))
    found.sort(key=lambda tp: (tp[1], tp[0].key))
    return found


def natural_key(reference: str) -> tuple:
    """"A.5.9" before "A.5.10"; letters compare case-insensitively."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.findall(r"\d+|[A-Za-z]+", reference or "")
    )


# ---------------------------------------------------------------------------
# Scoring (pure)
# ---------------------------------------------------------------------------
#: A topic in the control's name; the first such topic; a topic only in its text.
SYN_NAME = 0.6
SYN_HEAD_BONUS = 0.2
SYN_TEXT = 0.4
#: Each further topic that also lists the clause.
SYN_EXTRA_TOPIC = 0.05
#: Second and later references a topic lists for the same framework are weaker.
SYN_SECONDARY = 0.9
#: Keyword overlap adds this much of the cosine to a synonym hit...
KW_WITH_SYNONYM = 0.25
#: ...and on its own is worth this much of it, when the overlap is real.
KW_ALONE = 0.5
KW_ALONE_MIN_COSINE = 0.25
KW_ALONE_MIN_SHARED = 2
#: The control already carries this clause's catalogue reference.
OWN_REFERENCE = 0.95
#: Propagation from a clause suggested on its own merits.
CROSSWALK_FACTOR = 0.6
SCENARIO_FACTOR = 0.5
SCENARIO_MIN_SHARE = 0.5
SCENARIO_MIN_SOURCE = 0.4


@dataclass(frozen=True)
class Candidate:
    """One requirement of an installed framework, as scoring sees it."""

    requirement_id: object
    framework: str
    reference: str
    title: str
    description: str = ""
    framework_id: object = None
    #: The library template the framework was installed from (None for a framework the
    #: organisation built itself — scored on keywords only).
    template_key: str | None = None


@dataclass(frozen=True)
class ControlText:
    name: str
    description: str = ""
    objective: str = ""
    reference: str = ""


@dataclass
class Suggestion:
    requirement_id: object
    framework_id: object
    framework: str
    reference: str
    title: str
    score: float
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "requirement_id": self.requirement_id,
            "framework_id": self.framework_id,
            "framework": self.framework,
            "reference": self.reference,
            "title": self.title,
            "score": self.score,
            "reasons": list(self.reasons),
        }


def _norm_ref(ref: str) -> str:
    return (ref or "").strip().lower()


class CandidateIndex:
    """The candidates prepared once — TF-IDF vectors, reference lookups — so a bulk run
    over hundreds of controls does not rebuild them per control."""

    def __init__(self, candidates: Iterable[Candidate], crosswalks: dict | None = None):
        self.candidates: list[Candidate] = list(candidates)
        self.crosswalks: dict = {k: set(v) for k, v in (crosswalks or {}).items()}
        self.by_id = {c.requirement_id: c for c in self.candidates}
        # (template key, native ref) -> candidates; catalogue ref -> candidates.
        self.by_template_ref: dict[tuple[str, str], list[Candidate]] = {}
        self.by_catalogue_ref: dict[str, list[Candidate]] = {}
        for c in self.candidates:
            if c.template_key:
                self.by_template_ref.setdefault((c.template_key, _norm_ref(c.reference)), []).append(c)
                cat = control_mapping.catalogue_reference(c.template_key, c.reference)
                self.by_catalogue_ref.setdefault(_norm_ref(cat), []).append(c)
        # TF-IDF: a title counts twice, the description once.
        docs = {c.requirement_id: tokens(c.title) * 2 + tokens(c.description) for c in self.candidates}
        df: Counter = Counter()
        for toks in docs.values():
            df.update(set(toks))
        n = max(1, len(docs))
        self.idf = {t: math.log((n + 1) / (d + 1)) + 1.0 for t, d in df.items()}
        self._default_idf = math.log(n + 1) + 1.0
        self.vectors = {rid: self._vector(toks) for rid, toks in docs.items()}

    def _vector(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        vec = {t: cnt * self.idf.get(t, self._default_idf) for t, cnt in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def query(self, control: ControlText) -> dict[str, float]:
        return self._vector(
            tokens(control.name) * 2 + tokens(control.description) + tokens(control.objective)
        )


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def _topic_scores(control: ControlText) -> dict[tuple[str, str], tuple[float, list[str]]]:
    """(template key, native ref) -> (synonym score, topic labels that listed it)."""
    in_name = topics_in(control.name)
    head = in_name[0][0].key if in_name else None
    name_keys = {t.key for t, _ in in_name}
    in_text = [
        (t, p) for t, p in topics_in(f"{control.description}\n{control.objective}")
        if t.key not in name_keys
    ]
    hits: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for topic, _pos in in_name + in_text:
        base = SYN_NAME if topic.key in name_keys else SYN_TEXT
        if topic.key == head:
            base += SYN_HEAD_BONUS
        for key, refs in topic.refs.items():
            for i, ref in enumerate(refs):
                weight = base if i == 0 else base * SYN_SECONDARY
                hits.setdefault((key, _norm_ref(ref)), []).append((weight, topic.label))
    out: dict[tuple[str, str], tuple[float, list[str]]] = {}
    for k, items in hits.items():
        items.sort(key=lambda x: (-x[0], x[1]))
        labels: list[str] = []
        for _, label in items:
            if label not in labels:
                labels.append(label)
        out[k] = (items[0][0] + SYN_EXTRA_TOPIC * (len(labels) - 1), labels)
    return out


@lru_cache(maxsize=1024)
def _scenario_neighbours(catalogue_ref: str) -> tuple[tuple[str, float, tuple[str, ...]], ...]:
    """Catalogue references the scenario library lists alongside ``catalogue_ref``:
    (reference, share of its scenarios they also appear in, those scenarios)."""
    mine = [s for s, refs in control_mapping.SCENARIO_CONTROLS.items()
            if any(_norm_ref(r) == _norm_ref(catalogue_ref) for r in refs)]
    if not mine:
        return ()
    together: dict[str, list[str]] = {}
    for s in mine:
        for r in control_mapping.SCENARIO_CONTROLS[s]:
            if _norm_ref(r) != _norm_ref(catalogue_ref):
                together.setdefault(r, []).append(s)
    return tuple((r, len(ss) / len(mine), tuple(ss)) for r, ss in together.items())


def score_candidates(
    control: ControlText,
    index: CandidateIndex,
    *,
    exclude: Iterable = (),
    limit: int | None = 10,
    min_score: float = 0.0,
) -> list[Suggestion]:
    """Ranked suggestions for one control. Deterministic: same inputs, same order."""
    excluded = set(exclude)
    topic_hits = _topic_scores(control)
    qvec = index.query(control)
    own_ref = _norm_ref(control.reference)

    direct: dict[object, Suggestion] = {}

    def bump(c: Candidate, score: float, reason: str, into: dict) -> None:
        s = into.get(c.requirement_id)
        if s is None:
            s = into[c.requirement_id] = Suggestion(
                c.requirement_id, c.framework_id, c.framework, c.reference, c.title, 0.0, []
            )
        s.score = max(s.score, score)
        if reason not in s.reasons:
            s.reasons.append(reason)

    for c in index.candidates:
        if c.requirement_id in excluded:
            continue
        parts: list[tuple[float, str]] = []
        if own_ref and c.template_key and own_ref == _norm_ref(
            control_mapping.catalogue_reference(c.template_key, c.reference)
        ):
            parts.append((OWN_REFERENCE, f"The control's reference {control.reference} is this clause"))
        syn = topic_hits.get((c.template_key, _norm_ref(c.reference))) if c.template_key else None
        cos = _cosine(qvec, index.vectors.get(c.requirement_id, {}))
        shared = sorted(set(qvec) & set(index.vectors.get(c.requirement_id, {})))
        if syn is not None:
            value, labels = syn
            score = value + KW_WITH_SYNONYM * cos
            parts.append((score, "Synonym match: " + ", ".join(labels)))
            if shared and cos > 0:
                parts.append((score, "Shares keywords: " + ", ".join(shared[:6])))
        elif cos >= KW_ALONE_MIN_COSINE and len(shared) >= KW_ALONE_MIN_SHARED:
            parts.append((KW_ALONE * cos, "Shares keywords: " + ", ".join(shared[:6])))
        for score, reason in parts:
            bump(c, min(1.0, score), reason, direct)

    # Propagation, one hop, from what was suggested on its own merits.
    propagated: dict[object, Suggestion] = {}
    for sug in sorted(direct.values(), key=lambda s: (-s.score, str(s.requirement_id))):
        src = index.by_id[sug.requirement_id]
        label = f"{src.reference} ({src.framework})"
        for rid in sorted(index.crosswalks.get(src.requirement_id, ()), key=str):
            c = index.by_id.get(rid)
            if c is None or rid in excluded or c.framework_id == src.framework_id:
                continue
            bump(c, sug.score * CROSSWALK_FACTOR, f"Crosswalked to {label}", propagated)
        if src.template_key and sug.score >= SCENARIO_MIN_SOURCE:
            cat = control_mapping.catalogue_reference(src.template_key, src.reference)
            for ref, share, scenarios in _scenario_neighbours(cat):
                if share < SCENARIO_MIN_SHARE:
                    continue
                for c in index.by_catalogue_ref.get(_norm_ref(ref), []):
                    if c.requirement_id in excluded or c.template_key == src.template_key:
                        continue
                    bump(
                        c, sug.score * SCENARIO_FACTOR * share,
                        f"Addresses the same risk scenarios as {label}: {', '.join(scenarios[:3])}",
                        propagated,
                    )

    merged: dict[object, Suggestion] = dict(direct)
    for rid, sug in propagated.items():
        if rid in merged:
            for reason in sug.reasons:
                if reason not in merged[rid].reasons:
                    merged[rid].reasons.append(reason)
            merged[rid].score = max(merged[rid].score, sug.score)
        else:
            merged[rid] = sug

    out = [s for s in merged.values() if s.score >= min_score and s.score > 0]
    for s in out:
        s.score = round(min(1.0, s.score), 3)
    out.sort(key=lambda s: (-s.score, s.framework.lower(), natural_key(s.reference), str(s.requirement_id)))
    return out[:limit] if limit else out


def topic_references() -> list[tuple[str, str, str]]:
    """Every (topic, template key, reference) the synonym table ships — for the test
    that pins each to a real template clause."""
    return [(t.key, key, ref) for t in TOPICS for key, refs in t.refs.items() for ref in refs]


def iso_annex_a_for_text(text: str) -> list[tuple[str, str]]:
    """ISO/IEC 27001:2022 Annex A controls the synonym table finds in free text:
    (reference, title), in order of first mention. Used by AI Assist's offline mapping."""
    titles = {r["reference"]: r["title"] for r in TEMPLATES[ISO]["requirements"]}
    out: list[tuple[str, str]] = []
    for topic, _pos in topics_in(text):
        for ref in topic.refs.get(ISO, ()):
            if ref in titles and (ref, titles[ref]) not in out:
                out.append((ref, titles[ref]))
    return out


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
async def load_index(db) -> CandidateIndex:
    """Candidates from the tenant's installed compliance frameworks, with crosswalks."""
    from sqlalchemy import or_, select

    from app.models.compliance import Framework, Requirement, requirement_crosswalks
    from app.models.enums import ComplianceStatus, ComplianceTreatment

    frameworks = {
        fid: (name, template_key_for_name(name))
        for fid, name in (
            await db.execute(
                select(Framework.id, Framework.name).where(
                    Framework.deleted.is_(False), Framework.kind == "compliance"
                )
            )
        ).all()
    }
    if not frameworks:
        return CandidateIndex([])
    rows = (
        await db.execute(
            select(
                Requirement.id, Requirement.framework_id, Requirement.reference,
                Requirement.title, Requirement.description,
            ).where(
                Requirement.framework_id.in_(list(frameworks)),
                Requirement.deleted.is_(False),
                Requirement.status != ComplianceStatus.not_applicable,
                or_(Requirement.treatment.is_(None), Requirement.treatment != ComplianceTreatment.not_applicable),
            )
        )
    ).all()
    candidates = [
        Candidate(
            requirement_id=rid, framework_id=fid, framework=frameworks[fid][0],
            template_key=frameworks[fid][1], reference=ref or "", title=title or "",
            description=desc or "",
        )
        for rid, fid, ref, title, desc in rows
    ]
    ids = {c.requirement_id for c in candidates}
    crosswalks: dict = {}
    if ids:
        pairs = (
            await db.execute(
                select(requirement_crosswalks.c.requirement_id, requirement_crosswalks.c.related_requirement_id)
                .where(
                    requirement_crosswalks.c.requirement_id.in_(ids)
                    | requirement_crosswalks.c.related_requirement_id.in_(ids)
                )
            )
        ).all()
        for a, b in pairs:
            if a in ids and b in ids and a != b:
                crosswalks.setdefault(a, set()).add(b)
                crosswalks.setdefault(b, set()).add(a)
    return CandidateIndex(candidates, crosswalks)


async def mapped_requirement_ids(db, control_ids: Iterable[uuid.UUID]) -> dict:
    """control id -> requirement ids it is already linked to."""
    from sqlalchemy import select

    from app.models.compliance import requirement_controls

    ids = list(control_ids)
    out: dict = {cid: set() for cid in ids}
    if not ids:
        return out
    for rid, cid in (
        await db.execute(
            select(requirement_controls.c.requirement_id, requirement_controls.c.control_id)
            .where(requirement_controls.c.control_id.in_(ids))
        )
    ).all():
        out.setdefault(cid, set()).add(rid)
    return out


def control_text(control) -> ControlText:
    return ControlText(
        name=control.name or "", description=control.description or "",
        objective=control.objective or "", reference=control.reference or "",
    )


async def suggest_for_controls(
    db, controls: list, *, limit: int | None = 10, min_score: float = 0.0,
    index: CandidateIndex | None = None,
) -> dict:
    """control id -> ranked suggestions, excluding what each is already linked to."""
    index = index or await load_index(db)
    mapped = await mapped_requirement_ids(db, [c.id for c in controls])
    return {
        c.id: score_candidates(
            control_text(c), index, exclude=mapped.get(c.id, set()), limit=limit, min_score=min_score,
        )
        for c in controls
    }


async def link(db, pairs: Iterable[tuple[uuid.UUID, uuid.UUID]]) -> list[tuple[object, object]]:
    """Link (control, requirement) pairs through ``Requirement.controls``; returns the
    loaded (control, requirement) rows for links actually written. Unknown or archived
    ids raise 400."""
    from fastapi import HTTPException, status
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.compliance import Requirement
    from app.models.control import Control

    pairs = list(dict.fromkeys(pairs))
    if not pairs:
        return []
    control_ids = {c for c, _ in pairs}
    requirement_ids = {r for _, r in pairs}
    controls = {
        c.id: c for c in (
            await db.scalars(select(Control).where(Control.id.in_(control_ids), Control.deleted.is_(False)))
        ).all()
    }
    requirements = {
        r.id: r for r in (
            await db.scalars(
                select(Requirement)
                .options(selectinload(Requirement.framework))
                .where(Requirement.id.in_(requirement_ids), Requirement.deleted.is_(False))
            )
        ).all()
    }
    missing = [str(i) for i in control_ids - set(controls)] + [str(i) for i in requirement_ids - set(requirements)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown or archived id(s): {', '.join(sorted(missing))}",
        )
    written: list[tuple[object, object]] = []
    for cid, rid in pairs:
        control, requirement = controls[cid], requirements[rid]
        if control not in requirement.controls:
            requirement.controls.append(control)
            written.append((control, requirement))
    await db.flush()
    return written


# ---------------------------------------------------------------------------
# Crosswalk suggestions between two installed frameworks (phase 3)
# ---------------------------------------------------------------------------
# A crosswalk says two clauses of different frameworks ask for the same thing (ISO
# A.8.5 ≡ PCI DSS 8.4), so a control that satisfies one is evidence for the other and
# the clause suggestions above can propagate across them. Two signals propose one,
# conservatively; a person accepts it (``POST /compliance/crosswalks/accept``). Nothing
# here writes a crosswalk.
#
# 1. **The synonym table.** A topic lists, per framework, the clauses that address it,
#    strongest first. Two clauses listed for the same topic in the two frameworks are a
#    candidate — but only when at least one of them is its framework's *primary*
#    (first-listed) clause for the topic: primary ≡ primary is a strong match, primary ≡
#    secondary a likely one, and secondary ≡ secondary is never proposed (two clauses
#    that each only touch a topic need not be equivalent). Every reference must resolve
#    to a live clause of the installed framework, so a tenant on an older, shallower
#    copy simply gets fewer candidates.
# 2. **A shared control.** Two clauses implemented by the same control are a candidate,
#    weighted by how specific the control is: a control linked to one clause in each
#    framework supports that pair fully; one linked to many clauses supports each pair
#    thinly, and support below :data:`CW_CONTROL_MIN_SUPPORT` is not proposed on its own.
#
# Both signals on one pair make it stronger. Pairs already crosswalked (either way) are
# never suggested again.
CW_BOTH_PRIMARY = 0.85
CW_ONE_PRIMARY = 0.6
#: Each further topic that pairs the same two clauses.
CW_EXTRA_TOPIC = 0.05
#: Shared-control confidence: base + span x support (support capped at 1).
CW_CONTROL_BASE = 0.5
CW_CONTROL_SPAN = 0.25
#: A pair needs at least this much control support to be proposed on controls alone:
#: one control linked to at most two clauses on each side (1 / (2 x 2)).
CW_CONTROL_MIN_SUPPORT = 0.25
#: A topic match that a shared control confirms.
CW_BOTH_SIGNALS_BONUS = 0.1
CW_MAX = 0.95
#: Confidence at or above which a suggestion is "high" (and pre-ticked in the UI).
CW_HIGH = 0.75


@dataclass(frozen=True)
class CrosswalkClause:
    requirement_id: object
    framework_id: object
    reference: str
    title: str


@dataclass
class CrosswalkSuggestion:
    requirement_id: object
    reference: str
    title: str
    framework_id: object
    related_requirement_id: object
    related_reference: str
    related_title: str
    related_framework_id: object
    confidence: float
    strength: str
    reasons: list[str] = field(default_factory=list)
    #: "topic" and/or "control" — which signals proposed it.
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def topic_crosswalk_pairs(from_key: str, to_key: str) -> dict[tuple[str, str], dict[str, int]]:
    """(from ref, to ref) -> {topic label: rank} from the synonym table, for two library
    templates. Rank 2 = the primary clause of the topic in both; 1 = primary in one.
    Secondary-to-secondary pairs are left out. Pure."""
    out: dict[tuple[str, str], dict[str, int]] = {}
    if not from_key or not to_key or from_key == to_key:
        return out
    for topic in TOPICS:
        a_refs, b_refs = topic.refs.get(from_key, ()), topic.refs.get(to_key, ())
        for i, a in enumerate(a_refs):
            for j, b in enumerate(b_refs):
                rank = int(i == 0) + int(j == 0)
                if rank == 0:
                    continue
                hits = out.setdefault((a, b), {})
                hits[topic.label] = max(hits.get(topic.label, 0), rank)
    return out


def _cw_strength(confidence: float) -> str:
    return "high" if confidence >= CW_HIGH else "medium"


def suggest_crosswalks(
    from_clauses: Iterable[CrosswalkClause],
    to_clauses: Iterable[CrosswalkClause],
    *,
    from_template: str | None,
    to_template: str | None,
    control_links: dict | None = None,
    existing: Iterable[frozenset] = (),
) -> list[CrosswalkSuggestion]:
    """Candidate crosswalks from one framework's clauses to another's. Pure and
    deterministic. ``control_links`` maps a control id to ``(label, requirement ids it
    implements)``; ``existing`` holds the pairs already crosswalked (as frozensets)."""
    from_clauses, to_clauses = list(from_clauses), list(to_clauses)
    by_id = {c.requirement_id: c for c in from_clauses + to_clauses}
    from_ids = {c.requirement_id for c in from_clauses}
    to_ids = {c.requirement_id for c in to_clauses}
    done = {frozenset(p) for p in existing}

    def index(clauses):
        out: dict[str, list[CrosswalkClause]] = {}
        for c in clauses:
            out.setdefault(_norm_ref(c.reference), []).append(c)
        return out

    from_by_ref, to_by_ref = index(from_clauses), index(to_clauses)
    found: dict[tuple, dict] = {}

    def entry(a, b) -> dict:
        return found.setdefault((a, b), {"topics": {}, "controls": []})

    if from_template and to_template:
        for (a_ref, b_ref), hits in topic_crosswalk_pairs(from_template, to_template).items():
            for a in from_by_ref.get(_norm_ref(a_ref), []):
                for b in to_by_ref.get(_norm_ref(b_ref), []):
                    topics = entry(a.requirement_id, b.requirement_id)["topics"]
                    for label, rank in hits.items():
                        topics[label] = max(topics.get(label, 0), rank)

    for _cid, (label, reqs) in sorted((control_links or {}).items(), key=lambda kv: str(kv[1][0]) + str(kv[0])):
        mine = [r for r in reqs if r in from_ids]
        theirs = [r for r in reqs if r in to_ids]
        if not mine or not theirs:
            continue
        weight = 1.0 / (len(mine) * len(theirs))
        for a in mine:
            for b in theirs:
                entry(a, b)["controls"].append((label, weight))

    out: list[CrosswalkSuggestion] = []
    for (a, b), e in found.items():
        if a == b or frozenset((a, b)) in done:
            continue
        topic_score = None
        if e["topics"]:
            best = max(e["topics"].values())
            topic_score = min(CW_MAX, (CW_BOTH_PRIMARY if best >= 2 else CW_ONE_PRIMARY)
                              + CW_EXTRA_TOPIC * (len(e["topics"]) - 1))
        support = sum(w for _, w in e["controls"])
        control_score = (CW_CONTROL_BASE + CW_CONTROL_SPAN * min(1.0, support)
                         if e["controls"] and support >= CW_CONTROL_MIN_SUPPORT else None)
        if topic_score is None and control_score is None:
            continue
        if topic_score is not None and e["controls"]:
            confidence = min(CW_MAX, max(topic_score, control_score or 0.0) + CW_BOTH_SIGNALS_BONUS)
        else:
            confidence = topic_score if topic_score is not None else control_score
        reasons, sources = [], []
        for label, rank in sorted(e["topics"].items(), key=lambda kv: (-kv[1], kv[0])):
            reasons.append(f"Same topic: {label}" + (" (the primary clause in both frameworks)" if rank >= 2 else ""))
        if e["topics"]:
            sources.append("topic")
        if e["controls"]:
            labels = sorted({label for label, _ in e["controls"]})
            more = f" and {len(labels) - 3} more" if len(labels) > 3 else ""
            reasons.append(f"Implemented by the same control: {', '.join(labels[:3])}{more}")
            sources.append("control")
        ca, cb = by_id[a], by_id[b]
        out.append(CrosswalkSuggestion(
            requirement_id=a, reference=ca.reference, title=ca.title, framework_id=ca.framework_id,
            related_requirement_id=b, related_reference=cb.reference, related_title=cb.title,
            related_framework_id=cb.framework_id, confidence=round(float(confidence), 3),
            strength=_cw_strength(float(confidence)), reasons=reasons, sources=sources,
        ))
    out.sort(key=lambda s: (-s.confidence, natural_key(s.reference), natural_key(s.related_reference),
                            str(s.requirement_id), str(s.related_requirement_id)))
    return out


@dataclass
class CrosswalkContext:
    """The two frameworks and what is loaded about them, for the API."""

    from_framework: object
    to_framework: object
    from_template: str | None
    to_template: str | None
    from_clauses: list[CrosswalkClause]
    to_clauses: list[CrosswalkClause]
    existing: set[frozenset]


async def load_crosswalk_context(db, from_framework_id, to_framework_id) -> CrosswalkContext:
    """Both frameworks (live), their live clauses and the crosswalks already between them.
    Raises 404 for a missing framework and 422 when the two are the same."""
    from fastapi import HTTPException, status
    from sqlalchemy import select

    from app.models.compliance import Framework, Requirement, requirement_crosswalks

    if from_framework_id == to_framework_id:
        raise HTTPException(status_code=422,
                            detail="Pick two different frameworks to crosswalk.")
    frameworks = {
        f.id: f for f in (await db.scalars(
            select(Framework).where(Framework.id.in_([from_framework_id, to_framework_id]),
                                    Framework.deleted.is_(False))
        )).all()
    }
    for fid in (from_framework_id, to_framework_id):
        if fid not in frameworks:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Framework not found")

    async def clauses(fid) -> list[CrosswalkClause]:
        rows = (await db.execute(
            select(Requirement.id, Requirement.reference, Requirement.title)
            .where(Requirement.framework_id == fid, Requirement.deleted.is_(False))
        )).all()
        return [CrosswalkClause(rid, fid, ref or "", title or "") for rid, ref, title in rows]

    a, b = await clauses(from_framework_id), await clauses(to_framework_id)
    a_ids, b_ids = {c.requirement_id for c in a}, {c.requirement_id for c in b}
    existing: set[frozenset] = set()
    if a_ids and b_ids:
        for x, y in (await db.execute(
            select(requirement_crosswalks.c.requirement_id, requirement_crosswalks.c.related_requirement_id)
            .where(requirement_crosswalks.c.requirement_id.in_(a_ids | b_ids),
                   requirement_crosswalks.c.related_requirement_id.in_(a_ids | b_ids))
        )).all():
            if (x in a_ids and y in b_ids) or (x in b_ids and y in a_ids):
                existing.add(frozenset((x, y)))
    fa, fb = frameworks[from_framework_id], frameworks[to_framework_id]
    return CrosswalkContext(fa, fb, template_key_for_name(fa.name), template_key_for_name(fb.name), a, b, existing)


async def crosswalk_control_links(db, requirement_ids: Iterable) -> dict:
    """control id -> (label, requirement ids it implements), over live controls linked
    to any of ``requirement_ids``."""
    from sqlalchemy import select

    from app.models.compliance import requirement_controls
    from app.models.control import Control

    ids = list(requirement_ids)
    out: dict = {}
    if not ids:
        return out
    for cid, rid, ref, name in (await db.execute(
        select(requirement_controls.c.control_id, requirement_controls.c.requirement_id, Control.reference, Control.name)
        .join(Control, Control.id == requirement_controls.c.control_id)
        .where(requirement_controls.c.requirement_id.in_(ids), Control.deleted.is_(False))
    )).all():
        label = " ".join(p for p in (ref or "", name or "") if p) or str(cid)
        out.setdefault(cid, (label, set()))[1].add(rid)
    return out


async def crosswalk_suggestions_for(db, from_framework_id, to_framework_id) -> tuple[CrosswalkContext, list[CrosswalkSuggestion]]:
    ctx = await load_crosswalk_context(db, from_framework_id, to_framework_id)
    links = await crosswalk_control_links(
        db, [c.requirement_id for c in ctx.from_clauses] + [c.requirement_id for c in ctx.to_clauses]
    )
    return ctx, suggest_crosswalks(
        ctx.from_clauses, ctx.to_clauses, from_template=ctx.from_template, to_template=ctx.to_template,
        control_links=links, existing=ctx.existing,
    )
