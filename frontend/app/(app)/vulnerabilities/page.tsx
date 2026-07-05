"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ types
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type VulnFinding = {
  id: string;
  reference: string;
  title: string;
  cve_id: string;
  cvss_score: number;
  severity: string;
  asset_name: string;
  asset_ip: string;
  source: string;
  description: string;
  remediation: string;
  owner: string;
  status: string;
  discovered_date: string | null;
  due_date: string | null;
  remediated_date: string | null;
  sla_days: number;
  is_overdue: boolean;
  workflow_status: string;
  created_at: string;
};

type PatchRecord = {
  id: string;
  reference: string;
  title: string;
  vendor: string;
  patch_ref: string;
  category: string;
  released_date: string | null;
  deployed_date: string | null;
  status: string;
  affected_assets: string;
  owner: string;
  notes: string;
  workflow_status: string;
  created_at: string;
};

type Summary = {
  findings_by_severity: { severity: string; count: number }[];
  open_critical_high: number;
  overdue_findings: number;
  total_findings: number;
  open_findings: number;
  patch_compliance_pct: number;
  patches_by_status: { status: string; count: number }[];
  total_patches: number;
};

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

// ------------------------------------------------------------------ enum lists
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const VULN_SEVERITY = ["critical", "high", "medium", "low", "informational"];
const VULN_SOURCE = ["nessus", "qualys", "openvas", "defender", "manual", "pentest", "bug_bounty"];
const VULN_STATUS = ["open", "in_progress", "remediated", "risk_accepted", "false_positive"];
const PATCH_CATEGORY = ["os", "application", "firmware", "database", "network", "security_tool"];
const PATCH_STATUS = ["pending", "testing", "deploying", "deployed", "failed", "rolled_back"];

// ------------------------------------------------------------------ tones
const SEVERITY_TONE: Record<string, Tone> = {
  critical: "critical",
  high: "high",
  medium: "medium",
  low: "low",
  informational: "neutral",
};
const VULN_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  in_progress: "info",
  remediated: "low",
  risk_accepted: "medium",
  false_positive: "neutral",
};
const PATCH_STATUS_TONE: Record<string, Tone> = {
  pending: "neutral",
  testing: "info",
  deploying: "info",
  deployed: "low",
  failed: "critical",
  rolled_back: "high",
};

// ------------------------------------------------------------------ finding form
type FindingForm = {
  title: string;
  cve_id: string;
  cvss_score: string;
  severity: string;
  asset_name: string;
  asset_ip: string;
  source: string;
  status: string;
  owner: string;
  description: string;
  remediation: string;
  discovered_date: string;
  due_date: string;
  remediated_date: string;
  workflow_status: string;
};
const BLANK_FINDING: FindingForm = {
  title: "",
  cve_id: "",
  cvss_score: "",
  severity: "medium",
  asset_name: "",
  asset_ip: "",
  source: "nessus",
  status: "open",
  owner: "",
  description: "",
  remediation: "",
  discovered_date: "",
  due_date: "",
  remediated_date: "",
  workflow_status: "draft",
};
function fromFinding(v: VulnFinding): FindingForm {
  return {
    title: v.title,
    cve_id: v.cve_id || "",
    cvss_score: v.cvss_score != null ? String(v.cvss_score) : "",
    severity: v.severity || "medium",
    asset_name: v.asset_name || "",
    asset_ip: v.asset_ip || "",
    source: v.source || "nessus",
    status: v.status || "open",
    owner: v.owner || "",
    description: v.description || "",
    remediation: v.remediation || "",
    discovered_date: v.discovered_date || "",
    due_date: v.due_date || "",
    remediated_date: v.remediated_date || "",
    workflow_status: v.workflow_status || "draft",
  };
}
function findingPayload(f: FindingForm): Record<string, unknown> {
  return {
    title: f.title,
    cve_id: f.cve_id,
    cvss_score: f.cvss_score === "" ? 0 : Number(f.cvss_score),
    severity: f.severity,
    asset_name: f.asset_name,
    asset_ip: f.asset_ip,
    source: f.source,
    status: f.status,
    owner: f.owner,
    description: f.description,
    remediation: f.remediation,
    discovered_date: f.discovered_date || null,
    due_date: f.due_date || null,
    remediated_date: f.remediated_date || null,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ patch form
type PatchForm = {
  title: string;
  vendor: string;
  patch_ref: string;
  category: string;
  status: string;
  released_date: string;
  deployed_date: string;
  affected_assets: string;
  owner: string;
  notes: string;
  workflow_status: string;
};
const BLANK_PATCH: PatchForm = {
  title: "",
  vendor: "",
  patch_ref: "",
  category: "os",
  status: "pending",
  released_date: "",
  deployed_date: "",
  affected_assets: "",
  owner: "",
  notes: "",
  workflow_status: "draft",
};
function fromPatch(p: PatchRecord): PatchForm {
  return {
    title: p.title,
    vendor: p.vendor || "",
    patch_ref: p.patch_ref || "",
    category: p.category || "os",
    status: p.status || "pending",
    released_date: p.released_date || "",
    deployed_date: p.deployed_date || "",
    affected_assets: p.affected_assets || "",
    owner: p.owner || "",
    notes: p.notes || "",
    workflow_status: p.workflow_status || "draft",
  };
}
function patchPayload(f: PatchForm): Record<string, unknown> {
  return {
    title: f.title,
    vendor: f.vendor,
    patch_ref: f.patch_ref,
    category: f.category,
    status: f.status,
    released_date: f.released_date || null,
    deployed_date: f.deployed_date || null,
    affected_assets: f.affected_assets,
    owner: f.owner,
    notes: f.notes,
    workflow_status: f.workflow_status,
  };
}

type SectionId = "findings" | "patches";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "findings", label: "Vulnerabilities" },
  { id: "patches", label: "Patches" },
];

export default function VulnerabilitiesPage() {
  const [section, setSection] = useState<SectionId>("findings");
  const [error, setError] = useState<string | null>(null);

  const [findings, setFindings] = useState<VulnFinding[]>([]);
  const [patches, setPatches] = useState<PatchRecord[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);

  // ---- finding filters ----
  const [fSearch, setFSearch] = useState("");
  const [fSeverity, setFSeverity] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fSource, setFSource] = useState("");
  const [fOverdue, setFOverdue] = useState(false);

  // ---- finding dialog + expanded detail ----
  const [editingFinding, setEditingFinding] = useState<VulnFinding | null>(null);
  const [showFindingForm, setShowFindingForm] = useState(false);
  const [savingFinding, setSavingFinding] = useState(false);
  const [ff, setFf] = useState<FindingForm>(BLANK_FINDING);
  const setF = <K extends keyof FindingForm>(k: K, v: FindingForm[K]) => setFf((p) => ({ ...p, [k]: v }));
  const [openFinding, setOpenFinding] = useState<VulnFinding | null>(null);

  // ---- patch filters ----
  const [pStatus, setPStatus] = useState("");
  const [pCategory, setPCategory] = useState("");

  // ---- patch dialog ----
  const [editingPatch, setEditingPatch] = useState<PatchRecord | null>(null);
  const [showPatchForm, setShowPatchForm] = useState(false);
  const [savingPatch, setSavingPatch] = useState(false);
  const [pf, setPf] = useState<PatchForm>(BLANK_PATCH);
  const setP = <K extends keyof PatchForm>(k: K, v: PatchForm[K]) => setPf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadFindings() {
    try {
      const qs = new URLSearchParams();
      if (fSearch) qs.set("search", fSearch);
      if (fSeverity) qs.set("severity", fSeverity);
      if (fStatus) qs.set("status", fStatus);
      if (fSource) qs.set("source", fSource);
      if (fOverdue) qs.set("overdue", "true");
      const q = qs.toString();
      const res = await apiCall<Page<VulnFinding>>("GET", `/vuln-findings${q ? `?${q}` : ""}`);
      setFindings(res.items);
      if (openFinding) setOpenFinding(res.items.find((x) => x.id === openFinding.id) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load findings");
    }
  }
  async function loadPatches() {
    try {
      const qs = new URLSearchParams();
      if (pStatus) qs.set("status", pStatus);
      if (pCategory) qs.set("category", pCategory);
      const q = qs.toString();
      const res = await apiCall<Page<PatchRecord>>("GET", `/patch-records${q ? `?${q}` : ""}`);
      setPatches(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load patches");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<Summary>("GET", "/vulnerability-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }

  useEffect(() => {
    loadSummary();
  }, []);
  useEffect(() => {
    loadFindings();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fSearch, fSeverity, fStatus, fSource, fOverdue]);
  useEffect(() => {
    loadPatches();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pStatus, pCategory]);

  // ------------------------------------------------------------- finding CRUD
  function openNewFinding() {
    setEditingFinding(null);
    setFf(BLANK_FINDING);
    setShowFindingForm(true);
  }
  function openEditFinding(v: VulnFinding) {
    setEditingFinding(v);
    setFf(fromFinding(v));
    setShowFindingForm(true);
  }
  async function saveFinding() {
    setError(null);
    setSavingFinding(true);
    try {
      const payload = findingPayload(ff);
      if (editingFinding) await apiCall("PATCH", `/vuln-findings/${editingFinding.id}`, payload);
      else await apiCall("POST", "/vuln-findings", payload);
      setShowFindingForm(false);
      await loadFindings();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save finding");
    } finally {
      setSavingFinding(false);
    }
  }
  async function removeFinding(v: VulnFinding) {
    if (!window.confirm(`Delete vulnerability ${v.reference || v.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/vuln-findings/${v.id}`);
      setShowFindingForm(false);
      if (openFinding?.id === v.id) setOpenFinding(null);
      await loadFindings();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleFinding(v: VulnFinding) {
    setOpenFinding(openFinding?.id === v.id ? null : v);
  }

  // ------------------------------------------------------------- patch CRUD
  function openNewPatch() {
    setEditingPatch(null);
    setPf(BLANK_PATCH);
    setShowPatchForm(true);
  }
  function openEditPatch(p: PatchRecord) {
    setEditingPatch(p);
    setPf(fromPatch(p));
    setShowPatchForm(true);
  }
  async function savePatch() {
    setError(null);
    setSavingPatch(true);
    try {
      const payload = patchPayload(pf);
      if (editingPatch) await apiCall("PATCH", `/patch-records/${editingPatch.id}`, payload);
      else await apiCall("POST", "/patch-records", payload);
      setShowPatchForm(false);
      await loadPatches();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save patch");
    } finally {
      setSavingPatch(false);
    }
  }
  async function removePatch(p: PatchRecord) {
    if (!window.confirm(`Delete patch ${p.reference || p.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/patch-records/${p.id}`);
      setShowPatchForm(false);
      await loadPatches();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- finding form tabs
  const findingGeneral = (
    <>
      <Field label="Title" required help="For example: Apache Log4j RCE on core-banking node.">
        <TextInput value={ff.title} onChange={(v) => setF("title", v)} placeholder="Vulnerability title" required />
      </Field>
      <div className="field-row">
        <Field label="CVE ID" help="e.g. CVE-2021-44228.">
          <TextInput value={ff.cve_id} onChange={(v) => setF("cve_id", v)} placeholder="CVE-XXXX-XXXXX" />
        </Field>
        <Field label="CVSS score" help="Base score 0.0–10.0.">
          <TextInput type="number" value={ff.cvss_score} onChange={(v) => setF("cvss_score", v)} placeholder="0.0" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Severity">
          <Select value={ff.severity} onChange={(v) => setF("severity", v)} options={opts(VULN_SEVERITY)} />
        </Field>
        <Field label="Source" help="Scanner or discovery source.">
          <Select value={ff.source} onChange={(v) => setF("source", v)} options={opts(VULN_SOURCE)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Asset name" help="Affected host / application.">
          <TextInput value={ff.asset_name} onChange={(v) => setF("asset_name", v)} placeholder="core-banking-01" />
        </Field>
        <Field label="Asset IP">
          <TextInput value={ff.asset_ip} onChange={(v) => setF("asset_ip", v)} placeholder="10.0.0.5" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status">
          <Select value={ff.status} onChange={(v) => setF("status", v)} options={opts(VULN_STATUS)} />
        </Field>
        <Field label="Owner" help="Remediation owner.">
          <TextInput value={ff.owner} onChange={(v) => setF("owner", v)} placeholder="Owner" />
        </Field>
      </div>
    </>
  );
  const findingDetails = (
    <>
      <Field label="Description">
        <TextArea value={ff.description} onChange={(v) => setF("description", v)} rows={3} placeholder="What the weakness is and its impact." />
      </Field>
      <Field label="Remediation" help="How to fix — patch, config change, compensating control.">
        <TextArea value={ff.remediation} onChange={(v) => setF("remediation", v)} rows={3} placeholder="Recommended remediation." />
      </Field>
      <div className="field-row">
        <Field label="Discovered date">
          <TextInput type="date" value={ff.discovered_date} onChange={(v) => setF("discovered_date", v)} />
        </Field>
        <Field label="Due date" help="Remediation deadline — drives the overdue flag.">
          <TextInput type="date" value={ff.due_date} onChange={(v) => setF("due_date", v)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Remediated date">
          <TextInput type="date" value={ff.remediated_date} onChange={(v) => setF("remediated_date", v)} />
        </Field>
        <Field label="Workflow" help="Approval lifecycle for this finding record.">
          <Select value={ff.workflow_status} onChange={(v) => setF("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );

  // ------------------------------------------------------------- patch form tabs
  const patchGeneral = (
    <>
      <Field label="Title" required help="For example: July 2026 Windows Server cumulative update.">
        <TextInput value={pf.title} onChange={(v) => setP("title", v)} placeholder="Patch title" required />
      </Field>
      <div className="field-row">
        <Field label="Vendor">
          <TextInput value={pf.vendor} onChange={(v) => setP("vendor", v)} placeholder="Microsoft" />
        </Field>
        <Field label="Patch reference" help='e.g. "KB5001234" or an advisory ID.'>
          <TextInput value={pf.patch_ref} onChange={(v) => setP("patch_ref", v)} placeholder="KB5001234" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Category">
          <Select value={pf.category} onChange={(v) => setP("category", v)} options={opts(PATCH_CATEGORY)} />
        </Field>
        <Field label="Status">
          <Select value={pf.status} onChange={(v) => setP("status", v)} options={opts(PATCH_STATUS)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Released date">
          <TextInput type="date" value={pf.released_date} onChange={(v) => setP("released_date", v)} />
        </Field>
        <Field label="Deployed date">
          <TextInput type="date" value={pf.deployed_date} onChange={(v) => setP("deployed_date", v)} />
        </Field>
      </div>
      <Field label="Owner">
        <TextInput value={pf.owner} onChange={(v) => setP("owner", v)} placeholder="Owner" />
      </Field>
    </>
  );
  const patchDetails = (
    <>
      <Field label="Affected assets" help="Hosts / systems this patch applies to.">
        <TextArea value={pf.affected_assets} onChange={(v) => setP("affected_assets", v)} rows={3} placeholder="List of affected assets." />
      </Field>
      <Field label="Notes">
        <TextArea value={pf.notes} onChange={(v) => setP("notes", v)} rows={3} placeholder="Test results, rollback plan, etc." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this patch record.">
        <Select value={pf.workflow_status} onChange={(v) => setP("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Vulnerability &amp; Patch Oversight</h1>
          <p>Operational vulnerability register from scanner findings, with severity-based remediation SLAs and a patch-deployment pipeline.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "findings" && (
            <button className="btn" onClick={openNewFinding}>
              <IconPlus width={16} height={16} /> New finding
            </button>
          )}
          {section === "patches" && (
            <button className="btn" onClick={openNewPatch}>
              <IconPlus width={16} height={16} /> New patch
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.open_findings.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Open findings</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.open_critical_high.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Open critical + high</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.overdue_findings.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Overdue findings</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? `${summary.patch_compliance_pct}%` : "—"}</span>
          </div>
          <span className="l">Patch compliance</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, margin: "16px 0", flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            className={`btn${section === s.id ? "" : " secondary"}`}
            onClick={() => setSection(s.id)}
            type="button"
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= FINDINGS */}
      {section === "findings" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head row-between">
              <div>
                <h3>Vulnerabilities</h3>
                <span className="sub">{findings.length} shown · click a row to expand</span>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <input
                  className="input"
                  style={{ width: 200 }}
                  value={fSearch}
                  onChange={(e) => setFSearch(e.target.value)}
                  placeholder="Search title / CVE / asset"
                />
                <select className="select" style={{ width: 150 }} value={fSeverity} onChange={(e) => setFSeverity(e.target.value)}>
                  <option value="">All severities</option>
                  {VULN_SEVERITY.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                </select>
                <select className="select" style={{ width: 150 }} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
                  <option value="">All statuses</option>
                  {VULN_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                </select>
                <select className="select" style={{ width: 140 }} value={fSource} onChange={(e) => setFSource(e.target.value)}>
                  <option value="">All sources</option>
                  {VULN_SOURCE.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                </select>
                <label className="switch">
                  <input type="checkbox" checked={fOverdue} onChange={(e) => setFOverdue(e.target.checked)} />
                  <span className="track" />
                  <span className="txt">Overdue only</span>
                </label>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Title</th>
                    <th>CVE</th>
                    <th>CVSS</th>
                    <th>Severity</th>
                    <th>Asset</th>
                    <th>Source</th>
                    <th>Status</th>
                    <th>SLA / Due</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((v) => (
                    <tr key={v.id} style={{ cursor: "pointer" }} onClick={() => toggleFinding(v)}>
                      <td className="ref">{v.reference || "—"}</td>
                      <td className="cell-title">{v.title}</td>
                      <td className="muted">{v.cve_id || "—"}</td>
                      <td className="muted">{v.cvss_score != null ? Number(v.cvss_score).toFixed(1) : "—"}</td>
                      <td><Badge tone={SEVERITY_TONE[v.severity] || "neutral"}>{cap(v.severity)}</Badge></td>
                      <td className="muted">{v.asset_name || v.asset_ip || "—"}</td>
                      <td className="muted">{cap(v.source)}</td>
                      <td><Badge tone={VULN_STATUS_TONE[v.status] || "neutral"}>{cap(v.status)}</Badge></td>
                      <td>
                        {v.is_overdue ? (
                          <Badge tone="critical">Overdue</Badge>
                        ) : (
                          <span className="muted">{v.due_date || `${v.sla_days}d SLA`}</span>
                        )}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleFinding(v)}>
                            {openFinding?.id === v.id ? "Hide" : "View"}
                          </button>
                          <button className="btn secondary sm" onClick={() => openEditFinding(v)}>Edit</button>
                          <button className="btn secondary sm" onClick={() => removeFinding(v)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {findings.length === 0 && (
                    <tr>
                      <td colSpan={10}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No vulnerabilities</h3>
                          <p>Log scanner findings against assets to track remediation against severity-based SLAs.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openFinding && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openFinding.reference} — {openFinding.title}</h3>
                    <span className="sub">
                      {cap(openFinding.severity)} · CVSS {openFinding.cvss_score != null ? Number(openFinding.cvss_score).toFixed(1) : "—"}
                      {openFinding.cve_id ? " · " + openFinding.cve_id : ""} · {cap(openFinding.status)}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                    <div style={{ textAlign: "right" }}>
                      <div className="muted" style={{ fontSize: 12 }}>Remediation SLA</div>
                      <strong style={{ fontSize: 18 }}>{openFinding.sla_days} days</strong>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn secondary sm" onClick={() => openEditFinding(openFinding)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => removeFinding(openFinding)}>Delete</button>
                    </div>
                  </div>
                </div>

                <div className="card-pad">
                  <div className="field-row">
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Affected asset</div>
                      <div>{openFinding.asset_name || "—"}{openFinding.asset_ip ? ` (${openFinding.asset_ip})` : ""}</div>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Owner</div>
                      <div>{openFinding.owner || "—"}</div>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Discovered / Due</div>
                      <div>{openFinding.discovered_date || "—"} → {openFinding.due_date || "—"}</div>
                    </div>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <strong>Description</strong>
                    <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                      {openFinding.description || "No description recorded."}
                    </p>
                  </div>
                  <div style={{ marginTop: 12 }}>
                    <strong>Remediation</strong>
                    <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                      {openFinding.remediation || "No remediation recorded."}
                    </p>
                  </div>
                </div>
              </div>

              <RecordPanels model="vuln_finding" entityId={openFinding.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= PATCHES */}
      {section === "patches" && (
        <div className="card">
          <div className="card-head row-between">
            <div>
              <h3>Patches</h3>
              <span className="sub">{patches.length} shown · click a row to edit</span>
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <select className="select" style={{ width: 160 }} value={pStatus} onChange={(e) => setPStatus(e.target.value)}>
                <option value="">All statuses</option>
                {PATCH_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
              </select>
              <select className="select" style={{ width: 160 }} value={pCategory} onChange={(e) => setPCategory(e.target.value)}>
                <option value="">All categories</option>
                {PATCH_CATEGORY.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
              </select>
            </div>
          </div>
          {summary && summary.total_patches > 0 && (
            <div className="card-pad" style={{ paddingBottom: 0 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 6 }}>
                <span className="muted">Deployed / total patches</span>
                <strong>{summary.patch_compliance_pct}%</strong>
              </div>
              <div style={{ height: 8, borderRadius: 999, background: "var(--surface-2, #eef1f4)", overflow: "hidden" }}>
                <div
                  style={{
                    width: `${Math.min(100, Math.max(0, summary.patch_compliance_pct))}%`,
                    height: "100%",
                    background: "var(--ok, #2f9e44)",
                  }}
                />
              </div>
            </div>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Title</th>
                  <th>Vendor</th>
                  <th>Patch ref</th>
                  <th>Category</th>
                  <th>Status</th>
                  <th>Released</th>
                  <th>Deployed</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {patches.map((p) => (
                  <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => openEditPatch(p)}>
                    <td className="ref">{p.reference || "—"}</td>
                    <td className="cell-title">{p.title}</td>
                    <td className="muted">{p.vendor || "—"}</td>
                    <td className="muted">{p.patch_ref || "—"}</td>
                    <td className="muted">{cap(p.category)}</td>
                    <td><Badge tone={PATCH_STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                    <td className="muted">{p.released_date || "—"}</td>
                    <td className="muted">{p.deployed_date || "—"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removePatch(p)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {patches.length === 0 && (
                  <tr>
                    <td colSpan={9}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No patches</h3>
                        <p>Track the patch-deployment pipeline from pending through testing to deployed.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= MODALS */}
      {showFindingForm && (
        <FormModal
          title={editingFinding ? `Edit finding — ${editingFinding.reference || editingFinding.title}` : "New finding"}
          wide
          tabs={[
            { id: "general", label: "General", content: findingGeneral, required: true },
            { id: "details", label: "Details", content: findingDetails },
          ]}
          onClose={() => setShowFindingForm(false)}
          onSave={saveFinding}
          saving={savingFinding}
          error={error}
          saveLabel={editingFinding ? "Save changes" : "Create finding"}
          footerLeft={
            editingFinding ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeFinding(editingFinding)}
                disabled={savingFinding}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showPatchForm && (
        <FormModal
          title={editingPatch ? `Edit patch — ${editingPatch.reference || editingPatch.title}` : "New patch"}
          wide
          tabs={[
            { id: "general", label: "General", content: patchGeneral, required: true },
            { id: "details", label: "Details", content: patchDetails },
          ]}
          onClose={() => setShowPatchForm(false)}
          onSave={savePatch}
          saving={savingPatch}
          error={error}
          saveLabel={editingPatch ? "Save changes" : "Create patch"}
          footerLeft={
            editingPatch ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removePatch(editingPatch)}
                disabled={savingPatch}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}
