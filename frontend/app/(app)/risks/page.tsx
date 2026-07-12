"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { api, apiCall, type CustomField, type RiskSetting } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import CustomFieldsEditor from "@/components/CustomFieldsEditor";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import RecordIssues from "@/components/RecordIssues";
import RelatedChips from "@/components/RelatedChips";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconGauge, IconPlus } from "@/components/icons";

// --------------------------------------------------------------- inline types
type Ref = { id: string; reference?: string; title?: string; name?: string };

type RiskRow = {
  id: string;
  reference: string;
  title: string;
  description: string;
  category: string;
  status: string;
  owner_id: string | null;

  inherent_likelihood: number;
  inherent_impact: number;
  inherent_score: number | null;
  residual_likelihood: number | null;
  residual_impact: number | null;
  residual_score: number | null;
  inherent_severity: string | null;
  residual_severity: string | null;

  annual_loss_frequency: number | null;
  single_loss_expectancy: number | null;
  annual_loss_expectancy: number | null;

  treatment_strategy: string | null;
  treatment_description: string;
  treatment_owner: string;
  treatment_deadline: string | null;
  treatment_cost: number | null;

  review_frequency: string;
  last_review_date: string | null;
  next_review_date: string | null;
  expired_reviews: number;
  workflow_status: string;
  workflow_owner: string;

  assets: Ref[];
  controls: Ref[];
  threats: Ref[];
  vulnerabilities: Ref[];
  policies: Ref[];
  incidents: Ref[];

  // reverse graph links (read-only, from GET /risks/{id})
  requirements?: Ref[];
  exceptions?: Ref[];
  vendors?: Ref[];
  projects?: Ref[];
  goals?: Ref[];
  processing_activities?: Ref[];
  audit_findings?: Ref[];
};

type Page<T> = { items: T[] };
type Named = { id: string; name?: string; reference?: string; title?: string };
type UserRow = { id: string; email: string; full_name: string };

// --------------------------------------------------------------- option helpers
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "assessed", "treatment_planned", "treatment_in_progress", "accepted", "closed"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const STRATEGY = opts(["mitigate", "accept", "transfer", "avoid"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const SCALE: Option[] = [1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }));

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  closed: "low",
  accepted: "info",
  treatment_in_progress: "medium",
  treatment_planned: "medium",
  assessed: "info",
  draft: "neutral",
};

function money(n: number | null | undefined) {
  if (!n) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function isOverdue(d: string | null): boolean {
  if (!d) return false;
  return new Date(d) < new Date(new Date().toDateString());
}

function appetite(r: RiskRow, s: RiskSetting | null) {
  if (!s) return null;
  const score = r.residual_score ?? r.inherent_score;
  if (score == null) return null;
  if (score <= s.appetite_score) return { label: "within appetite", tone: "low" as const };
  if (score <= s.tolerance_score) return { label: "elevated", tone: "medium" as const };
  return { label: "breach", tone: "critical" as const };
}

// --------------------------------------------------------------- form state
type FormState = {
  title: string;
  description: string;
  category: string;
  status: string;
  workflow_status: string;
  workflow_owner: string;
  owner_id: string;
  inherent_likelihood: number | "";
  inherent_impact: number | "";
  residual_likelihood: string;
  residual_impact: string;
  annual_loss_frequency: number | "";
  single_loss_expectancy: number | "";
  treatment_strategy: string;
  treatment_description: string;
  treatment_owner: string;
  treatment_deadline: string;
  treatment_cost: number | "";
  review_frequency: string;
  asset_ids: AsyncOption[];
  control_ids: AsyncOption[];
  threat_ids: AsyncOption[];
  vulnerability_ids: AsyncOption[];
  policy_ids: AsyncOption[];
  incident_ids: AsyncOption[];
};

const refToOpt = (x: Ref): AsyncOption => ({
  value: x.id,
  label: x.reference || x.title || x.name || x.id,
});

const BLANK: FormState = {
  title: "", description: "", category: "", status: "draft",
  workflow_status: "draft", workflow_owner: "", owner_id: "",
  inherent_likelihood: 3, inherent_impact: 3,
  residual_likelihood: "", residual_impact: "",
  annual_loss_frequency: "", single_loss_expectancy: "",
  treatment_strategy: "", treatment_description: "", treatment_owner: "",
  treatment_deadline: "", treatment_cost: "", review_frequency: "annual",
  asset_ids: [], control_ids: [], threat_ids: [], vulnerability_ids: [], policy_ids: [], incident_ids: [],
};

function fromRisk(r: RiskRow): FormState {
  return {
    title: r.title,
    description: r.description || "",
    category: r.category || "",
    status: r.status,
    workflow_status: r.workflow_status,
    workflow_owner: r.workflow_owner || "",
    owner_id: r.owner_id || "",
    inherent_likelihood: r.inherent_likelihood,
    inherent_impact: r.inherent_impact,
    residual_likelihood: r.residual_likelihood ? String(r.residual_likelihood) : "",
    residual_impact: r.residual_impact ? String(r.residual_impact) : "",
    annual_loss_frequency: r.annual_loss_frequency ?? "",
    single_loss_expectancy: r.single_loss_expectancy ?? "",
    treatment_strategy: r.treatment_strategy || "",
    treatment_description: r.treatment_description || "",
    treatment_owner: r.treatment_owner || "",
    treatment_deadline: r.treatment_deadline || "",
    treatment_cost: r.treatment_cost ?? "",
    review_frequency: r.review_frequency,
    asset_ids: r.assets.map(refToOpt),
    control_ids: r.controls.map(refToOpt),
    threat_ids: r.threats.map(refToOpt),
    vulnerability_ids: r.vulnerabilities.map(refToOpt),
    policy_ids: r.policies.map(refToOpt),
    incident_ids: r.incidents.map(refToOpt),
  };
}

function toPayload(f: FormState): Record<string, unknown> {
  const num = (v: number | "") => (v === "" ? null : Number(v));
  const scale = (v: string) => (v === "" ? null : Number(v));
  return {
    title: f.title,
    description: f.description,
    category: f.category,
    status: f.status,
    workflow_status: f.workflow_status,
    workflow_owner: f.workflow_owner,
    owner_id: f.owner_id || null,
    inherent_likelihood: f.inherent_likelihood === "" ? 1 : Number(f.inherent_likelihood),
    inherent_impact: f.inherent_impact === "" ? 1 : Number(f.inherent_impact),
    residual_likelihood: scale(f.residual_likelihood),
    residual_impact: scale(f.residual_impact),
    annual_loss_frequency: num(f.annual_loss_frequency),
    single_loss_expectancy: num(f.single_loss_expectancy),
    treatment_strategy: f.treatment_strategy || null,
    treatment_description: f.treatment_description,
    treatment_owner: f.treatment_owner,
    treatment_deadline: f.treatment_deadline || null,
    treatment_cost: num(f.treatment_cost),
    review_frequency: f.review_frequency,
    asset_ids: f.asset_ids.map((o) => o.value),
    control_ids: f.control_ids.map((o) => o.value),
    threat_ids: f.threat_ids.map((o) => o.value),
    vulnerability_ids: f.vulnerability_ids.map((o) => o.value),
    policy_ids: f.policy_ids.map((o) => o.value),
    incident_ids: f.incident_ids.map((o) => o.value),
  };
}

// --------------------------------------------------------------- page
function RisksPage() {
  const [settings, setSettings] = useState<RiskSetting | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [recordId, setRecordId] = useRecordParam("id");
  // Read-only detail loaded for the view drawer (?id=). Edit is a separate action.
  const [detail, setDetail] = useState<RiskRow | null>(null);

  // appetite editor
  const [showSettings, setShowSettings] = useState(false);
  const [appetiteScore, setAppetiteScore] = useState(6);
  const [toleranceScore, setToleranceScore] = useState(12);

  // form modal
  const [editing, setEditing] = useState<RiskRow | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // org-defined custom fields, edited inside the form and saved with the record
  const [cfDefs, setCfDefs] = useState<CustomField[]>([]);
  const [cfValues, setCfValues] = useState<Record<string, string>>({});

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchRisks = useCallback((qs: string) => apiCall<PagedList<RiskRow>>("GET", `/risks?${qs}`), []);

  // Server typeahead sources for the form's link pickers (replaces 6 capped preloads).
  const linkSearch = (path: string) => (q: string) =>
    apiCall<PagedList<Named>>("GET", `/${path}?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((x) => ({ value: x.id, label: x.name || x.title || x.reference || x.id, sub: x.reference })),
    );

  useEffect(() => {
    api.riskSettings().then((s) => {
      setSettings(s);
      setAppetiteScore(s.appetite_score);
      setToleranceScore(s.tolerance_score);
    }).catch(() => {});
    apiCall<PagedList<UserRow>>("GET", "/users?limit=200").then((r) => setUsers(r.items)).catch(() => {});
    api.customFields("risk").then((d) => setCfDefs(d.filter((x) => x.enabled))).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setCfValues({});
    setError(null);
    setShowForm(true);
  }
  function openEdit(r: RiskRow) {
    setEditing(r);
    setF(fromRisk(r));
    setCfValues({});
    if (cfDefs.length) {
      api
        .customFieldValues("risk", r.id)
        .then((rows) => setCfValues(Object.fromEntries(rows.map((x) => [x.field.id, x.value]))))
        .catch(() => {});
    }
    setError(null);
    setShowForm(true);
  }

  // Deep-link view: ?id= (row click, global search, ⌘K) loads the record's full detail
  // into the read-only drawer. Editing is a separate action from there.
  const loadDetail = useCallback((id: string) => {
    apiCall<RiskRow>("GET", `/risks/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (recordId) loadDetail(recordId);
    else setDetail(null);
  }, [recordId, loadDetail]);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      let riskId = editing?.id;
      if (editing) await apiCall("PATCH", `/risks/${editing.id}`, payload);
      else riskId = (await apiCall<RiskRow>("POST", "/risks", payload)).id;
      if (cfDefs.length && riskId) {
        await api.setCustomFieldValues("risk", riskId, cfValues);
      }
      setShowForm(false);
      reload();
      if (recordId) loadDetail(recordId);  // refresh the open view drawer
      toast(editing ? "Changes saved" : "Risk created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save risk");
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: RiskRow) {
    if (!(await confirmDialog({ title: `Archive risk ${r.reference}?`, message: "It will be soft-deleted from the register.", confirmLabel: "Archive", danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/risks/${r.id}`);
      if (recordId === r.id) setRecordId(null);
      reload();
      toast("Archived");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete risk");
    }
  }

  async function saveSettings(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const s = await api.updateRiskSettings({ appetite_score: appetiteScore, tolerance_score: toleranceScore });
      setSettings(s);
      setShowSettings(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    }
  }

  const userOpts: Option[] = users.map((u) => ({ value: u.id, label: u.full_name || u.email, sub: u.email }));

  const userName = (id: string | null) => {
    if (!id) return "—";
    const u = users.find((x) => x.id === id);
    return u ? u.full_name || u.email : "—";
  };
  const linkCount = (r: RiskRow) =>
    r.assets.length + r.controls.length + r.threats.length + r.vulnerabilities.length + r.policies.length + r.incidents.length;

  // read-only helpers for the view drawer
  const chips = (items: Ref[]) =>
    items.length ? (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((x) => (
          <span key={x.id} className="chip">{x.reference || x.title || x.name || x.id}</span>
        ))}
      </div>
    ) : (
      <span className="muted">—</span>
    );
  const field = (label: string, value: React.ReactNode) => (
    <div style={{ minWidth: 140 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
      <div style={{ marginTop: 3 }}>{value ?? <span className="muted">—</span>}</div>
    </div>
  );

  // computed previews
  const inhScore = f.inherent_likelihood === "" || f.inherent_impact === "" ? null : Number(f.inherent_likelihood) * Number(f.inherent_impact);
  const resScore = f.residual_likelihood === "" || f.residual_impact === "" ? null : Number(f.residual_likelihood) * Number(f.residual_impact);
  const alePreview =
    f.annual_loss_frequency === "" || f.single_loss_expectancy === ""
      ? null
      : Number(f.annual_loss_frequency) * Number(f.single_loss_expectancy);

  // --------------------------------------------------------------- tabs
  const generalTab = (
    <>
      <Field label="Title" required help="A short statement of the risk, e.g. 'Phishing leads to credential theft'.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Phishing leads to credential theft" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="Threat / vulnerability context and what could go wrong." />
      </Field>
      <div className="field-row">
        <Field label="Category">
          <TextInput value={f.category} onChange={(v) => set("category", v)} placeholder="Information Security" />
        </Field>
        <Field label="Risk Owner" help="The user accountable for this risk.">
          <Select value={f.owner_id} onChange={(v) => set("owner_id", v)} options={userOpts} placeholder="Unassigned" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Workflow Owner">
          <TextInput value={f.workflow_owner} onChange={(v) => set("workflow_owner", v)} placeholder="Approver" />
        </Field>
      </div>
    </>
  );

  const assessmentTab = (
    <>
      <Field label="Inherent Risk" help="Likelihood × Impact before any controls are considered (1–5 scale).">
        <div className="field-row">
          <Select value={String(f.inherent_likelihood)} onChange={(v) => set("inherent_likelihood", v === "" ? "" : Number(v))} options={SCALE} placeholder="Likelihood" />
          <Select value={String(f.inherent_impact)} onChange={(v) => set("inherent_impact", v === "" ? "" : Number(v))} options={SCALE} placeholder="Impact" />
          <div className="field" style={{ margin: 0 }}>
            <label>Score</label>
            <div style={{ paddingTop: 4 }}>
              {inhScore != null ? <Badge tone="neutral" plain>{inhScore}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
      </Field>
      <Field label="Residual Risk" help="Likelihood × Impact after controls. Leave blank until assessed.">
        <div className="field-row">
          <Select value={f.residual_likelihood} onChange={(v) => set("residual_likelihood", v)} options={SCALE} placeholder="Likelihood" />
          <Select value={f.residual_impact} onChange={(v) => set("residual_impact", v)} options={SCALE} placeholder="Impact" />
          <div className="field" style={{ margin: 0 }}>
            <label>Score</label>
            <div style={{ paddingTop: 4 }}>
              {resScore != null ? <Badge tone="neutral" plain>{resScore}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
      </Field>

      <Field label="Quantitative (FAIR)" help="Annual Loss Expectancy = loss events / year × $ per event. Optional.">
        <div className="field-row">
          <div className="field" style={{ margin: 0 }}>
            <label>Loss events / year (ALF)</label>
            <NumberInput value={f.annual_loss_frequency} onChange={(v) => set("annual_loss_frequency", v)} min={0} step={0.1} placeholder="0.5" />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>$ per event (SLE)</label>
            <NumberInput value={f.single_loss_expectancy} onChange={(v) => set("single_loss_expectancy", v)} min={0} step={1000} placeholder="200000" />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Exposure (ALE)</label>
            <div style={{ paddingTop: 4 }}>
              {alePreview != null ? <Badge tone="info" plain>{money(alePreview)}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
      </Field>

      <div className="field-row">
        <Field label="Treatment Strategy">
          <Select value={f.treatment_strategy} onChange={(v) => set("treatment_strategy", v)} options={STRATEGY} placeholder="Not decided" />
        </Field>
        <Field label="Treatment Owner">
          <TextInput value={f.treatment_owner} onChange={(v) => set("treatment_owner", v)} placeholder="Responsible person" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Treatment Deadline">
          <TextInput value={f.treatment_deadline} onChange={(v) => set("treatment_deadline", v)} type="date" />
        </Field>
        <Field label="Treatment Cost ($)">
          <NumberInput value={f.treatment_cost} onChange={(v) => set("treatment_cost", v)} min={0} step={1000} placeholder="50000" />
        </Field>
      </div>
      <Field label="Treatment Plan">
        <RichText value={f.treatment_description} onChange={(v) => set("treatment_description", v)} placeholder="Describe the treatment plan, mitigating actions and milestones…" />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Assets" help="Assets exposed to or affected by this risk.">
        <AsyncMultiSelect search={linkSearch("assets")} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
      </Field>
      <Field label="Controls" help="Controls that mitigate this risk (reduce residual likelihood/impact).">
        <AsyncMultiSelect search={linkSearch("controls")} value={f.control_ids} onChange={(v) => set("control_ids", v)} />
      </Field>
      <Field label="Threats" help="Threats from the catalog that could trigger this risk.">
        <AsyncMultiSelect search={linkSearch("threats")} value={f.threat_ids} onChange={(v) => set("threat_ids", v)} />
      </Field>
      <Field label="Vulnerabilities" help="Weaknesses a threat could exploit.">
        <AsyncMultiSelect search={linkSearch("vulnerabilities")} value={f.vulnerability_ids} onChange={(v) => set("vulnerability_ids", v)} />
      </Field>
      <Field label="Policies" help="Policies that govern or address this risk.">
        <AsyncMultiSelect search={linkSearch("policies")} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} />
      </Field>
      <Field label="Incidents" help="Incidents that materialised from this risk.">
        <AsyncMultiSelect search={linkSearch("incidents")} value={f.incident_ids} onChange={(v) => set("incident_ids", v)} />
      </Field>
    </>
  );

  const reviewTab = (
    <>
      <Field label="Review Frequency" help="How often this risk should be re-assessed. The next review date is scheduled automatically.">
        <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
      </Field>
      {editing && (
        <div className="field-row">
          <Field label="Last Review">
            <TextInput value={editing.last_review_date || "—"} onChange={() => {}} />
          </Field>
          <Field label="Next Review">
            <TextInput value={editing.next_review_date || "—"} onChange={() => {}} />
          </Field>
          <Field label="Expired Reviews">
            <TextInput value={String(editing.expired_reviews)} onChange={() => {}} />
          </Field>
        </div>
      )}
      {editing && (
        <p className="muted" style={{ fontSize: 13 }}>
          Review dates are managed by the register. Use the dedicated review action to mark this risk reviewed and reschedule.
        </p>
      )}
    </>
  );

  const riskColumns: Column<RiskRow>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference}</span> },
    { key: "title", header: "Title", sortable: true, render: (r) => <span className="cell-title">{r.title}</span> },
    { key: "category", header: "Category", sortable: true, render: (r) => <span className="muted">{r.category || "—"}</span> },
    { key: "inherent_score", header: "Inherent", sortable: true, render: (r) => <><Severity value={r.inherent_severity} /> <span className="muted">({r.inherent_score ?? "—"})</span></> },
    { key: "residual_score", header: "Residual", sortable: true, render: (r) => <><Severity value={r.residual_severity} /> <span className="muted">({r.residual_score ?? "—"})</span></> },
    { key: "appetite", header: "Appetite", render: (r) => { const a = appetite(r, settings); return a ? <Badge tone={a.tone}>{a.label}</Badge> : <span className="muted">—</span>; } },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge> },
    { key: "owner", header: "Owner", render: (r) => <span className="muted">{userName(r.owner_id)}</span> },
    { key: "exposure", header: "Exposure", render: (r) => <span className="muted">{money(r.annual_loss_expectancy)}</span> },
    { key: "links", header: "Links", align: "center", render: (r) => <span className="muted">{linkCount(r) || "—"}</span> },
    { key: "next_review_date", header: "Review", sortable: true, render: (r) => (isOverdue(r.next_review_date) ? <Badge tone="high">Overdue</Badge> : <span className="muted">{r.next_review_date || "—"}</span>) },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(r)}>Delete</button></div> },
  ];

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Risk Register</h1>
          <p>Identify, score and treat risks — qualitative (5×5) and quantitative (FAIR), with controls, threats and review cycles.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={() => setShowSettings((v) => !v)}>
            <IconGauge width={16} height={16} />
            Appetite
          </button>
          <ImportExport resource="risks" label="Risks" onDone={reload} />
          <button className="btn secondary" onClick={() => api.pdfRiskRegister().catch(() => {})}>
            Register PDF
          </button>
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} />
            Add risk
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {settings && (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <div className="row-between">
            <span className="muted">
              Risk appetite ≤ <b style={{ color: "var(--green)" }}>{settings.appetite_score}</b>{" "}
              · Tolerance ≤ <b style={{ color: "var(--amber)" }}>{settings.tolerance_score}</b>{" "}
              <span style={{ color: "var(--faint)" }}>(score above tolerance = breach)</span>
            </span>
          </div>
          {showSettings && (
            <form onSubmit={saveSettings} style={{ display: "flex", gap: 14, alignItems: "flex-end", marginTop: 14 }}>
              <div style={{ width: 160 }}>
                <label className="label">Appetite (1–25)</label>
                <input className="input" type="number" min={1} max={25} value={appetiteScore} onChange={(e) => setAppetiteScore(Number(e.target.value))} />
              </div>
              <div style={{ width: 160 }}>
                <label className="label">Tolerance (1–25)</label>
                <input className="input" type="number" min={1} max={25} value={toleranceScore} onChange={(e) => setToleranceScore(Number(e.target.value))} />
              </div>
              <button className="btn">Save thresholds</button>
            </form>
          )}
        </div>
      )}

      <DataTable<RiskRow>
        columns={riskColumns}
        fetcher={fetchRisks}
        rowKey={(r) => r.id}
        onRowClick={(r) => setRecordId(r.id)}
        activeKey={recordId ?? undefined}
        searchPlaceholder="Search risks by title or reference…"
        defaultSort={{ by: "inherent_score", dir: "desc" }}
        emptyMessage="No risks yet. Create your first risk to start building the register."
        refreshKey={refreshKey}
      />

      {/* Read-only detail view (?id=) — click a row to see everything; Edit is separate. */}
      <RecordDrawer
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? cap(detail.status) + (detail.category ? ` · ${detail.category}` : "") : ""}
        width={680}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-end", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Inherent</div><div style={{ marginTop: 4 }}><Severity value={detail.inherent_severity} /> <span className="muted">({detail.inherent_score ?? "—"})</span></div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Residual</div><div style={{ marginTop: 4 }}><Severity value={detail.residual_severity} /> <span className="muted">({detail.residual_score ?? "—"})</span></div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Appetite</div><div style={{ marginTop: 4 }}>{(() => { const a = appetite(detail, settings); return a ? <Badge tone={a.tone}>{a.label}</Badge> : <span className="muted">—</span>; })()}</div></div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}><div className="muted" style={{ fontSize: 12 }}>Exposure (ALE)</div><div style={{ marginTop: 4 }}>{money(detail.annual_loss_expectancy)}</div></div>
            </div>

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              {field("Owner", userName(detail.owner_id))}
              {field("Status", <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>)}
              {field("Workflow", cap(detail.workflow_status))}
              {field("Workflow owner", detail.workflow_owner || "—")}
            </div>

            {detail.description && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description</div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }}>{detail.description}</div>
              </div>
            )}

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <strong style={{ fontSize: 13 }}>Treatment</strong>
              <div style={{ display: "flex", gap: 22, flexWrap: "wrap", margin: "10px 0" }}>
                {field("Strategy", detail.treatment_strategy ? cap(detail.treatment_strategy) : "—")}
                {field("Owner", detail.treatment_owner || "—")}
                {field("Deadline", detail.treatment_deadline || "—")}
                {field("Cost", money(detail.treatment_cost))}
              </div>
              {detail.treatment_description && (
                <div style={{ fontSize: 13.5, lineHeight: 1.5 }} dangerouslySetInnerHTML={{ __html: detail.treatment_description }} />
              )}
            </div>

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 18 }}>
              {field("Review frequency", cap(detail.review_frequency))}
              {field("Last review", detail.last_review_date || "—")}
              {field("Next review", isOverdue(detail.next_review_date) ? <Badge tone="high">Overdue · {detail.next_review_date}</Badge> : (detail.next_review_date || "—"))}
              {field("Expired reviews", String(detail.expired_reviews))}
            </div>

            <strong style={{ fontSize: 13 }}>Related records</strong>
            <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 8 }}>
              <RelatedChips label="Assets" items={detail.assets} href="/information-assets" />
              <RelatedChips label="Controls" items={detail.controls} href="/controls" />
              <RelatedChips label="Threats" items={detail.threats} href="/threat-library" />
              <RelatedChips label="Vulnerabilities" items={detail.vulnerabilities} href="/threat-library" />
              <RelatedChips label="Policies" items={detail.policies} href="/policies" />
              <RelatedChips label="Incidents" items={detail.incidents} href="/incidents" />
              <RelatedChips label="Compliance requirements" items={detail.requirements} href="/compliance" />
              <RelatedChips label="Exceptions" items={detail.exceptions} href="/exceptions" />
              <RelatedChips label="Third parties" items={detail.vendors} href="/vendors" />
              <RelatedChips label="Projects" items={detail.projects} href="/projects" />
              <RelatedChips label="Goals" items={detail.goals} href="/goals" />
              <RelatedChips label="Processing activities" items={detail.processing_activities} href="/privacy" />
              <RelatedChips label="Audit findings" items={detail.audit_findings} href="/internal-audit" />
            </div>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              <RecordIssues entityId={detail.id} entityRef={detail.reference} sourceType="risk_assessment" />
            </div>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
              <RecordPanels model="risk" entityId={detail.id} />
            </div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit risk — ${editing.reference}` : "Add item (Risk Register)"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "assessment", label: "Assessment", content: assessmentTab },
            { id: "links", label: "Links & Relations", content: linksTab },
            { id: "review", label: "Review", content: reviewTab },
            ...(cfDefs.length
              ? [{
                  id: "custom",
                  label: "Custom fields",
                  required: cfDefs.some((d) => d.required),
                  content: (
                    <CustomFieldsEditor
                      fields={cfDefs}
                      values={cfValues}
                      onChange={(id, v) => setCfValues((p) => ({ ...p, [id]: v }))}
                    />
                  ),
                }]
              : []),
          ]}
          onClose={() => { setShowForm(false); setRecordId(null); }}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create risk"}
        />
      )}
    </>
  );
}

export default function RisksPageWrapper() {
  return (
    <Suspense fallback={null}>
      <RisksPage />
    </Suspense>
  );
}
