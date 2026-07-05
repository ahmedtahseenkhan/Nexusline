"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconShield } from "@/components/icons";

// ------------------------------------------------------------------ types
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type BiaDependency = {
  id: string;
  bia_id: string;
  dependency_type: string;
  name: string;
  description: string;
  criticality: string;
  rto_hours: number | null;
  single_point_of_failure: boolean;
  created_at: string;
};

type BiaAssessment = {
  id: string;
  reference: string;
  process_name: string;
  business_unit: string;
  owner: string;
  description: string;
  criticality: string;
  rto_hours: number | null;
  rpo_hours: number | null;
  mtpd_hours: number | null;
  peak_periods: string;
  financial_impact_24h: number;
  financial_impact_1week: number;
  currency: string;
  operational_impact: string;
  reputational_impact: string;
  regulatory_impact: string;
  legal_impact: string;
  minimum_resources: string;
  recovery_strategy: string;
  workaround: string;
  status: string;
  assessment_date: string | null;
  next_review_date: string | null;
  workflow_status: string;
  dependency_count: number;
  is_review_overdue: boolean;
  rto_band: string;
  created_at: string;
  dependencies: BiaDependency[];
};

type BiaSummary = {
  total: number;
  by_criticality: Record<string, number>;
  rto_within_24h: number;
  rto_within_4h: number;
  total_financial_exposure: number;
  spof_dependencies: number;
  review_overdue: number;
};

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());
const hrs = (n: number | null | undefined) => (n == null ? "—" : `${num(n)}h`);

// ------------------------------------------------------------------ enum lists
const BIA_STATUS = opts(["draft", "submitted", "approved", "retired"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const CRITICALITY = opts(["low", "medium", "high", "critical"]);
const DEP_TYPES = [
  "application",
  "it_asset",
  "information_asset",
  "vendor",
  "people",
  "facility",
  "upstream_process",
  "utility",
];

// ------------------------------------------------------------------ tones
const CRIT_TONE: Record<string, Tone> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};
const BIA_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  submitted: "info",
  approved: "low",
  retired: "neutral",
};

function CritBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={CRIT_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

// ------------------------------------------------------------------ form state
type BiaForm = {
  process_name: string;
  business_unit: string;
  owner: string;
  description: string;
  criticality: string;
  status: string;
  assessment_date: string;
  next_review_date: string;
  peak_periods: string;
  rto_hours: string;
  rpo_hours: string;
  mtpd_hours: string;
  financial_impact_24h: string;
  financial_impact_1week: string;
  currency: string;
  operational_impact: string;
  reputational_impact: string;
  regulatory_impact: string;
  legal_impact: string;
  minimum_resources: string;
  recovery_strategy: string;
  workaround: string;
  workflow_status: string;
};
const BLANK_BIA: BiaForm = {
  process_name: "",
  business_unit: "",
  owner: "",
  description: "",
  criticality: "medium",
  status: "draft",
  assessment_date: "",
  next_review_date: "",
  peak_periods: "",
  rto_hours: "",
  rpo_hours: "",
  mtpd_hours: "",
  financial_impact_24h: "",
  financial_impact_1week: "",
  currency: "PKR",
  operational_impact: "",
  reputational_impact: "",
  regulatory_impact: "",
  legal_impact: "",
  minimum_resources: "",
  recovery_strategy: "",
  workaround: "",
  workflow_status: "draft",
};
function fromBia(b: BiaAssessment): BiaForm {
  return {
    process_name: b.process_name,
    business_unit: b.business_unit || "",
    owner: b.owner || "",
    description: b.description || "",
    criticality: b.criticality || "medium",
    status: b.status || "draft",
    assessment_date: b.assessment_date || "",
    next_review_date: b.next_review_date || "",
    peak_periods: b.peak_periods || "",
    rto_hours: b.rto_hours != null ? String(b.rto_hours) : "",
    rpo_hours: b.rpo_hours != null ? String(b.rpo_hours) : "",
    mtpd_hours: b.mtpd_hours != null ? String(b.mtpd_hours) : "",
    financial_impact_24h: b.financial_impact_24h != null ? String(b.financial_impact_24h) : "",
    financial_impact_1week: b.financial_impact_1week != null ? String(b.financial_impact_1week) : "",
    currency: b.currency || "PKR",
    operational_impact: b.operational_impact || "",
    reputational_impact: b.reputational_impact || "",
    regulatory_impact: b.regulatory_impact || "",
    legal_impact: b.legal_impact || "",
    minimum_resources: b.minimum_resources || "",
    recovery_strategy: b.recovery_strategy || "",
    workaround: b.workaround || "",
    workflow_status: b.workflow_status || "draft",
  };
}
function biaPayload(f: BiaForm): Record<string, unknown> {
  const int = (v: string) => (v === "" ? null : Number(v));
  return {
    process_name: f.process_name,
    business_unit: f.business_unit,
    owner: f.owner,
    description: f.description,
    criticality: f.criticality,
    status: f.status,
    assessment_date: f.assessment_date || null,
    next_review_date: f.next_review_date || null,
    peak_periods: f.peak_periods,
    rto_hours: int(f.rto_hours),
    rpo_hours: int(f.rpo_hours),
    mtpd_hours: int(f.mtpd_hours),
    financial_impact_24h: f.financial_impact_24h === "" ? 0 : Number(f.financial_impact_24h),
    financial_impact_1week: f.financial_impact_1week === "" ? 0 : Number(f.financial_impact_1week),
    currency: f.currency,
    operational_impact: f.operational_impact,
    reputational_impact: f.reputational_impact,
    regulatory_impact: f.regulatory_impact,
    legal_impact: f.legal_impact,
    minimum_resources: f.minimum_resources,
    recovery_strategy: f.recovery_strategy,
    workaround: f.workaround,
    workflow_status: f.workflow_status,
  };
}

type DepDraft = {
  dependency_type: string;
  name: string;
  criticality: string;
  rto_hours: string;
  single_point_of_failure: boolean;
};
const BLANK_DEP: DepDraft = {
  dependency_type: "application",
  name: "",
  criticality: "medium",
  rto_hours: "",
  single_point_of_failure: false,
};

export default function BiaPage() {
  const [error, setError] = useState<string | null>(null);
  const [bias, setBias] = useState<BiaAssessment[]>([]);
  const [summary, setSummary] = useState<BiaSummary | null>(null);

  const [editing, setEditing] = useState<BiaAssessment | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [bf, setBf] = useState<BiaForm>(BLANK_BIA);
  const setB = <K extends keyof BiaForm>(k: K, v: BiaForm[K]) => setBf((p) => ({ ...p, [k]: v }));

  const [open, setOpen] = useState<BiaAssessment | null>(null);
  const [dd, setDd] = useState<DepDraft>(BLANK_DEP);
  const setDD = <K extends keyof DepDraft>(k: K, v: DepDraft[K]) => setDd((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadBias(keepOpen?: string) {
    try {
      const res = await apiCall<Page<BiaAssessment>>("GET", "/bia?limit=200");
      setBias(res.items);
      if (keepOpen) setOpen(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load business impact analyses");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<BiaSummary>("GET", "/bia-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load BIA summary");
    }
  }
  async function refreshBia(id: string) {
    const b = await apiCall<BiaAssessment>("GET", `/bia/${id}`);
    setOpen(b);
    setBias((prev) => prev.map((x) => (x.id === id ? b : x)));
  }

  useEffect(() => {
    loadBias();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- BIA CRUD
  function openNew() {
    setEditing(null);
    setBf(BLANK_BIA);
    setShowForm(true);
  }
  function openEdit(b: BiaAssessment) {
    setEditing(b);
    setBf(fromBia(b));
    setShowForm(true);
  }
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = biaPayload(bf);
      if (editing) await apiCall<BiaAssessment>("PATCH", `/bia/${editing.id}`, payload);
      else await apiCall<BiaAssessment>("POST", "/bia", payload);
      setShowForm(false);
      await loadBias(open?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save BIA");
    } finally {
      setSaving(false);
    }
  }
  async function remove(b: BiaAssessment) {
    if (!window.confirm(`Delete BIA ${b.reference || b.process_name}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/bia/${b.id}`);
      setShowForm(false);
      if (open?.id === b.id) setOpen(null);
      await loadBias();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggle(b: BiaAssessment) {
    setDd(BLANK_DEP);
    setOpen(open?.id === b.id ? null : b);
  }

  // ------------------------------------------------------------- dependencies (inline)
  async function addDependency() {
    if (!open) return;
    setError(null);
    try {
      await apiCall<BiaAssessment>("POST", `/bia/${open.id}/dependencies`, {
        dependency_type: dd.dependency_type,
        name: dd.name,
        criticality: dd.criticality,
        rto_hours: dd.rto_hours === "" ? null : Number(dd.rto_hours),
        single_point_of_failure: dd.single_point_of_failure,
      });
      setDd(BLANK_DEP);
      await refreshBia(open.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add dependency");
    }
  }
  async function removeDependency(lineId: string) {
    if (!open) return;
    if (!window.confirm("Remove this dependency?")) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/bia-dependencies/${lineId}`);
      await refreshBia(open.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove dependency");
    }
  }

  // ------------------------------------------------------------- form tabs
  const processTab = (
    <>
      <Field label="Process name" required help="For example: Core banking - CBS transaction processing.">
        <TextInput value={bf.process_name} onChange={(v) => setB("process_name", v)} placeholder="Core banking - CBS" required />
      </Field>
      <div className="field-row">
        <Field label="Business unit" help="The unit that owns this process.">
          <TextInput value={bf.business_unit} onChange={(v) => setB("business_unit", v)} placeholder="Payments and Settlements" />
        </Field>
        <Field label="Process owner">
          <TextInput value={bf.owner} onChange={(v) => setB("owner", v)} placeholder="Head of Operations" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Criticality" help="Business criticality of this process.">
          <Select value={bf.criticality} onChange={(v) => setB("criticality", v)} options={CRITICALITY} />
        </Field>
        <Field label="Status">
          <Select value={bf.status} onChange={(v) => setB("status", v)} options={BIA_STATUS} />
        </Field>
      </div>
      <Field label="Description" help="What the process does and why it matters.">
        <TextArea value={bf.description} onChange={(v) => setB("description", v)} rows={3} placeholder="e.g. Processes inward/outward clearing and RTGS settlement." />
      </Field>
      <Field label="Peak periods" help="When disruption hurts most.">
        <TextInput value={bf.peak_periods} onChange={(v) => setB("peak_periods", v)} placeholder="month-end, Eid, salary days" />
      </Field>
      <div className="field-row">
        <Field label="Assessment date">
          <TextInput type="date" value={bf.assessment_date} onChange={(v) => setB("assessment_date", v)} />
        </Field>
        <Field label="Next review date" help="Drives the review-overdue flag.">
          <TextInput type="date" value={bf.next_review_date} onChange={(v) => setB("next_review_date", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this BIA record.">
        <Select value={bf.workflow_status} onChange={(v) => setB("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  const impactTab = (
    <>
      <div className="field-row">
        <Field label="RTO (hours)" help="Recovery Time Objective — max acceptable downtime.">
          <TextInput type="number" value={bf.rto_hours} onChange={(v) => setB("rto_hours", v)} placeholder="4" />
        </Field>
        <Field label="RPO (hours)" help="Recovery Point Objective — max acceptable data loss window.">
          <TextInput type="number" value={bf.rpo_hours} onChange={(v) => setB("rpo_hours", v)} placeholder="1" />
        </Field>
        <Field label="MTPD (hours)" help="Maximum Tolerable Period of Disruption.">
          <TextInput type="number" value={bf.mtpd_hours} onChange={(v) => setB("mtpd_hours", v)} placeholder="24" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Financial impact @ 24h" help="Estimated loss if disrupted for 24 hours.">
          <TextInput type="number" value={bf.financial_impact_24h} onChange={(v) => setB("financial_impact_24h", v)} placeholder="0" />
        </Field>
        <Field label="Financial impact @ 1 week" help="Estimated loss if disrupted for one week.">
          <TextInput type="number" value={bf.financial_impact_1week} onChange={(v) => setB("financial_impact_1week", v)} placeholder="0" />
        </Field>
        <Field label="Currency">
          <TextInput value={bf.currency} onChange={(v) => setB("currency", v)} placeholder="PKR" />
        </Field>
      </div>
      <Field label="Operational impact">
        <TextArea value={bf.operational_impact} onChange={(v) => setB("operational_impact", v)} rows={2} placeholder="e.g. Branches unable to post transactions; SWIFT messages queue." />
      </Field>
      <Field label="Reputational impact">
        <TextArea value={bf.reputational_impact} onChange={(v) => setB("reputational_impact", v)} rows={2} placeholder="e.g. Customer trust erosion, negative media, social-media escalation." />
      </Field>
      <Field label="Regulatory impact">
        <TextArea value={bf.regulatory_impact} onChange={(v) => setB("regulatory_impact", v)} rows={2} placeholder="e.g. SBP reporting breach; RTGS settlement failure notification." />
      </Field>
      <Field label="Legal impact">
        <TextArea value={bf.legal_impact} onChange={(v) => setB("legal_impact", v)} rows={2} placeholder="e.g. Contractual SLA penalties, customer claims." />
      </Field>
    </>
  );

  const recoveryTab = (
    <>
      <Field label="Minimum resources" help="People, systems and facilities needed to run at minimum capacity.">
        <TextArea value={bf.minimum_resources} onChange={(v) => setB("minimum_resources", v)} rows={3} placeholder="e.g. 2 operators, CBS at DR site, SWIFT terminal, secure link." />
      </Field>
      <Field label="Recovery strategy" help="How the process is restored within the RTO.">
        <TextArea value={bf.recovery_strategy} onChange={(v) => setB("recovery_strategy", v)} rows={3} placeholder="e.g. Failover to DR data centre; invoke alternate branch." />
      </Field>
      <Field label="Workaround" help="Manual / interim workaround while systems are down.">
        <TextArea value={bf.workaround} onChange={(v) => setB("workaround", v)} rows={3} placeholder="e.g. Manual vouchers with end-of-day reconciliation." />
      </Field>
    </>
  );

  const criticalCount = summary ? summary.by_criticality["critical"] || 0 : null;

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Impact Analysis</h1>
          <p>Per-process criticality, recovery objectives (RTO/RPO/MTPD), disruption impacts and dependencies that drive business continuity planning.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> New BIA
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.total.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Processes analysed</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{criticalCount != null ? criticalCount.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Critical processes</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.rto_within_24h.toLocaleString() : "—"}</span>
          </div>
          <span className="l">RTO ≤ 24h</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.total_financial_exposure.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Total financial exposure (PKR)</span>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Business Impact Analyses</h3>
          <span className="sub">{bias.length} total · click a row to manage dependencies</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Process</th>
                <th>Business unit</th>
                <th>Criticality</th>
                <th>RTO</th>
                <th>RPO</th>
                <th>MTPD</th>
                <th>Status</th>
                <th>Review</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {bias.map((b) => (
                <tr key={b.id} style={{ cursor: "pointer" }} onClick={() => toggle(b)}>
                  <td className="ref">{b.reference || "—"}</td>
                  <td className="cell-title">{b.process_name}</td>
                  <td className="muted">{b.business_unit || "—"}</td>
                  <td><CritBadge value={b.criticality} /></td>
                  <td className="muted">{hrs(b.rto_hours)}</td>
                  <td className="muted">{hrs(b.rpo_hours)}</td>
                  <td className="muted">{hrs(b.mtpd_hours)}</td>
                  <td><Badge tone={BIA_STATUS_TONE[b.status] || "neutral"}>{cap(b.status)}</Badge></td>
                  <td>
                    {b.is_review_overdue ? (
                      <Badge tone="high">Overdue</Badge>
                    ) : (
                      <span className="muted">{b.next_review_date || "—"}</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => toggle(b)}>
                        {open?.id === b.id ? "Hide" : "Manage"}
                      </button>
                      <button className="btn secondary sm" onClick={() => remove(b)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {bias.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconShield width={24} height={24} /></span>
                      <h3>No business impact analyses</h3>
                      <p>Assess a critical business process to capture RTO/RPO, impacts and dependencies for BCP.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head row-between">
              <div>
                <h3>{open.reference} — {open.process_name}</h3>
                <span className="sub">
                  {cap(open.criticality)} · {open.business_unit || "no unit"}
                  {open.owner ? " · owner " + open.owner : ""}
                  {open.peak_periods ? " · peaks: " + open.peak_periods : ""}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn secondary sm" onClick={() => openEdit(open)}>Edit</button>
                <button className="btn secondary sm" onClick={() => remove(open)}>Delete</button>
              </div>
            </div>

            <div className="card-pad">
              <div className="grid stat-grid" style={{ marginBottom: 16 }}>
                <div className="card stat">
                  <div className="stat-top"><span className="n">{hrs(open.rto_hours)}</span></div>
                  <span className="l">RTO ({open.rto_band})</span>
                </div>
                <div className="card stat">
                  <div className="stat-top"><span className="n">{hrs(open.rpo_hours)}</span></div>
                  <span className="l">RPO</span>
                </div>
                <div className="card stat">
                  <div className="stat-top"><span className="n">{hrs(open.mtpd_hours)}</span></div>
                  <span className="l">MTPD</span>
                </div>
                <div className="card stat">
                  <div className="stat-top">
                    <span className="n">{num(open.financial_impact_24h)}</span>
                  </div>
                  <span className="l">Impact @ 24h ({open.currency})</span>
                </div>
                <div className="card stat">
                  <div className="stat-top">
                    <span className="n">{num(open.financial_impact_1week)}</span>
                  </div>
                  <span className="l">Impact @ 1 week ({open.currency})</span>
                </div>
              </div>

              <div className="table-wrap" style={{ marginBottom: 16 }}>
                <table>
                  <tbody>
                    <tr><td className="muted" style={{ width: 200 }}>Operational impact</td><td>{open.operational_impact || "—"}</td></tr>
                    <tr><td className="muted">Reputational impact</td><td>{open.reputational_impact || "—"}</td></tr>
                    <tr><td className="muted">Regulatory impact</td><td>{open.regulatory_impact || "—"}</td></tr>
                    <tr><td className="muted">Legal impact</td><td>{open.legal_impact || "—"}</td></tr>
                    <tr><td className="muted">Minimum resources</td><td>{open.minimum_resources || "—"}</td></tr>
                    <tr><td className="muted">Recovery strategy</td><td>{open.recovery_strategy || "—"}</td></tr>
                    <tr><td className="muted">Workaround</td><td>{open.workaround || "—"}</td></tr>
                  </tbody>
                </table>
              </div>

              <strong>Dependencies</strong>
              <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                Applications, IT &amp; information assets, vendors, people, facilities and utilities this process relies on.
              </p>
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(ev) => { ev.preventDefault(); addDependency(); }}
              >
                <div style={{ width: 180 }}>
                  <label className="label">Type</label>
                  <select className="select" value={dd.dependency_type} onChange={(ev) => setDD("dependency_type", ev.target.value)}>
                    {DEP_TYPES.map((t) => (<option key={t} value={t}>{cap(t)}</option>))}
                  </select>
                </div>
                <div style={{ flex: "1 1 220px" }}>
                  <label className="label">Name</label>
                  <input className="input" value={dd.name} onChange={(ev) => setDD("name", ev.target.value)} placeholder="Core banking - CBS / SWIFT / DR site" required />
                </div>
                <div style={{ width: 140 }}>
                  <label className="label">Criticality</label>
                  <select className="select" value={dd.criticality} onChange={(ev) => setDD("criticality", ev.target.value)}>
                    {["low", "medium", "high", "critical"].map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                  </select>
                </div>
                <div style={{ width: 110 }}>
                  <label className="label">RTO (h)</label>
                  <input className="input" type="number" value={dd.rto_hours} onChange={(ev) => setDD("rto_hours", ev.target.value)} placeholder="4" />
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6, paddingBottom: 8 }}>
                  <input id="dep-spof" type="checkbox" checked={dd.single_point_of_failure} onChange={(ev) => setDD("single_point_of_failure", ev.target.checked)} />
                  <label htmlFor="dep-spof" className="label" style={{ margin: 0 }}>SPOF</label>
                </div>
                <button className="btn">Add</button>
              </form>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Name</th>
                      <th>Criticality</th>
                      <th>RTO</th>
                      <th>SPOF</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {open.dependencies.map((d) => (
                      <tr key={d.id}>
                        <td><Badge tone="info">{cap(d.dependency_type)}</Badge></td>
                        <td className="cell-title">{d.name}</td>
                        <td><CritBadge value={d.criticality} /></td>
                        <td className="muted">{hrs(d.rto_hours)}</td>
                        <td>{d.single_point_of_failure ? <Badge tone="critical">SPOF</Badge> : <span className="muted">—</span>}</td>
                        <td>
                          <button className="btn secondary sm" onClick={() => removeDependency(d.id)}>Remove</button>
                        </td>
                      </tr>
                    ))}
                    {open.dependencies.length === 0 && (
                      <tr><td colSpan={6}><span className="muted">No dependencies recorded yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <RecordPanels model="bia_assessment" entityId={open.id} />
        </>
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit BIA — ${editing.reference || editing.process_name}` : "New BIA"}
          wide
          tabs={[
            { id: "process", label: "Process", content: processTab, required: true },
            { id: "impact", label: "Impact & Timing", content: impactTab },
            { id: "recovery", label: "Recovery", content: recoveryTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create BIA"}
          footerLeft={
            editing ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => remove(editing)}
                disabled={saving}
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
