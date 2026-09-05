"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { api, apiCall, type CustomField, type MatrixLevel, type RiskAcceptance, type RiskMatrixConfig, type RiskSetting } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import CustomFieldsEditor from "@/components/CustomFieldsEditor";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import RecordIssues from "@/components/RecordIssues";
import RelatedChips from "@/components/RelatedChips";
import RiskAcceptancePanel from "@/components/RiskAcceptancePanel";
import ResidualSuggestion from "@/components/ResidualSuggestion";
import WorkflowStrip from "@/components/WorkflowStrip";
import RiskMethodology from "@/components/RiskMethodology";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import AsyncSelect from "@/components/AsyncSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import GenerateRisks from "@/components/GenerateRisks";
import ImportExport from "@/components/ImportExport";
import OrphanCleanup from "@/components/OrphanCleanup";
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

  control_health?: string;

  business_units: Ref[];
  processes: Ref[];
  assets: Ref[];
  controls: Ref[];
  threats: Ref[];
  vulnerabilities: Ref[];
  policies: Ref[];
  incidents: Ref[];

  acceptances?: RiskAcceptance[];
  created_at?: string;
  updated_at?: string;

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
/** Score options for the tenant's matrix — a 4x4 register must not offer a 5. */
const scaleOptions = (size: number): Option[] =>
  Array.from({ length: size }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }));

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

// live rollup of the health of a record's mitigating controls
function controlHealth(v: string | null | undefined): React.ReactNode {
  if (v === "issues") return <Badge tone="high">Control issues</Badge>;
  if (v === "ok") return <Badge tone="low">Controls OK</Badge>;
  return <span className="muted">—</span>;
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
  business_unit_ids: AsyncOption[];
  process_ids: AsyncOption[];
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
  business_unit_ids: [], process_ids: [],
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
    business_unit_ids: (r.business_units ?? []).map(refToOpt),
    process_ids: (r.processes ?? []).map(refToOpt),
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
    business_unit_ids: f.business_unit_ids.map((o) => o.value),
    process_ids: f.process_ids.map((o) => o.value),
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

  // Segment scope. A risk workshop convenes around one business unit or process, so the
  // register needs to narrow to that cut — and whatever is narrowed to here is what the
  // register PDF exports, so the download always matches the screen it was launched from.
  // The organisation's own wording for each rung of the two axes. An assessor picking
  // "4" needs to know what the bank decided 4 means, or the number is just a number and
  // two people scoring the same risk will disagree.
  const [matrix, setMatrix] = useState<RiskMatrixConfig | null>(null);
  const [showScale, setShowScale] = useState(false);

  const [segments, setSegments] = useState<{ units: Named[]; processes: Named[] }>({ units: [], processes: [] });
  const [scopeUnit, setScopeUnit] = useState("");
  const [scopeProcess, setScopeProcess] = useState("");
  const [scopeStatus, setScopeStatus] = useState("");
  const [scopeAsset, setScopeAsset] = useState<{ id: string; name: string } | null>(null);

  // org-defined custom fields, edited inside the form and saved with the record
  const [cfDefs, setCfDefs] = useState<CustomField[]>([]);
  const [cfValues, setCfValues] = useState<Record<string, string>>({});

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  // The matrix is per-organisation configurable, so every score input and threshold
  // bound is derived from it rather than assuming 5x5.
  const matrixSize = settings?.matrix_size ?? 5;
  const maxScore = matrixSize * matrixSize;
  const SCALE = scaleOptions(matrixSize);

  /* Each axis gets its own options, labelled in the organisation's words — "3 — Possible"
     rather than a bare "3". The dropdown is a native <select>, so the option text is the
     only thing that can carry meaning inside it; the full definition goes underneath the
     field and in the reference table, where it has room to be a sentence. */
  const axisOptions = (levels: MatrixLevel[] | undefined): Option[] =>
    levels?.length
      ? levels.map((l) => ({ value: String(l.level), label: l.label ? `${l.level} — ${l.label}` : String(l.level) }))
      : SCALE;
  const LIKELIHOOD = axisOptions(matrix?.likelihood_levels);
  const IMPACT = axisOptions(matrix?.impact_levels);

  /** The chosen rung's definition, for the line under the field. */
  const rung = (levels: MatrixLevel[] | undefined, value: number | string) => {
    const n = Number(value);
    if (!n || !levels) return null;
    const hit = levels.find((l) => l.level === n);
    if (!hit || (!hit.label && !hit.definition)) return null;
    return (
      <span>
        <b>{hit.level} — {hit.label}</b>
        {hit.definition ? `: ${hit.definition}` : ""}
      </span>
    );
  };

  /** Both axes' chosen wording on one line, or nothing when neither is set. */
  const chosen = (likelihood: number | string, impact: number | string) => {
    const l = rung(matrix?.likelihood_levels, likelihood);
    const i = rung(matrix?.impact_levels, impact);
    if (!l && !i) return null;
    return (
      <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 6 }}>
        {l && <div>Likelihood {l}</div>}
        {i && <div>Impact {i}</div>}
      </div>
    );
  };

  /** True once somebody has actually written the criteria down. */
  const scaleIsDefined = Boolean(
    matrix?.likelihood_levels?.some((l) => l.definition) || matrix?.impact_levels?.some((l) => l.definition),
  );
  const fetchRisks = useCallback((qs: string) => apiCall<PagedList<RiskRow>>("GET", `/risks?${qs}`), []);

  // One scope object, read by the table and by the export. Undefined entries are
  // dropped from the query string, so "no scope" is the plain register.
  const scopeFilters = useMemo(
    () => ({
      business_unit_id: scopeUnit || undefined,
      process_id: scopeProcess || undefined,
      asset_id: scopeAsset?.id || undefined,
      status: scopeStatus || undefined,
    }),
    [scopeUnit, scopeProcess, scopeAsset, scopeStatus],
  );
  const scopeLabel = useMemo(() => {
    const parts = [
      segments.units.find((u) => u.id === scopeUnit)?.name,
      segments.processes.find((x) => x.id === scopeProcess)?.name,
      scopeAsset?.name,
      scopeStatus ? cap(scopeStatus) : undefined,
    ].filter(Boolean);
    return parts.length ? `Scoped to ${parts.join(" · ")}` : "Whole register";
  }, [scopeUnit, scopeProcess, scopeAsset, scopeStatus, segments]);

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
    Promise.all([
      apiCall<PagedList<Named>>("GET", "/business-units?limit=200&sort_by=name"),
      apiCall<PagedList<Named>>("GET", "/processes?limit=200&sort_by=name"),
    ])
      .then(([u, p]) => setSegments({ units: u.items, processes: p.items }))
      .catch(() => {});
    api.customFields("risk").then((d) => setCfDefs(d.filter((x) => x.enabled))).catch(() => {});
    api.riskMatrixConfig().then(setMatrix).catch(() => {});
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
      {/* The criteria the two numbers below are supposed to mean, on the same screen as
          the numbers. Collapsed by default so it does not push the form down, but one
          click away — an assessor comparing rung 3 against rung 4 should not have to
          leave the record to do it. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <span className="muted" style={{ fontSize: 12.5 }}>
          Scoring on your {matrixSize}×{matrixSize} matrix — scores run 1 to {maxScore}.
        </span>
        <button type="button" className="btn secondary sm" onClick={() => setShowScale((v) => !v)}>
          {showScale ? "Hide scale" : "What do 1–" + matrixSize + " mean?"}
        </button>
      </div>

      {showScale && (
        <div className="card card-pad" style={{ marginBottom: 14 }}>
          {!scaleIsDefined && (
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
              Your organisation has not written its criteria yet, so these are generic
              placeholders. An administrator sets the real wording under{" "}
              <b>Risk Register → Appetite → Risk methodology</b>; that is what makes two
              assessors score the same risk the same way.
            </div>
          )}
          {/* auto-fit rather than 1fr 1fr: the criteria column holds a sentence, and at
              10 rungs in a modal two fixed columns squeeze it into a ribbon. */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
            {([["Likelihood", matrix?.likelihood_levels], ["Impact", matrix?.impact_levels]] as const).map(
              ([axis, levels]) => (
                <div key={axis}>
                  <div className="bt" style={{ marginBottom: 6 }}>{axis}</div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr><th style={{ width: 34 }}>#</th><th style={{ width: "34%" }}>Means</th><th>Criteria</th></tr>
                      </thead>
                      <tbody>
                        {(levels ?? []).map((l) => (
                          <tr key={`${axis}-${l.level}`}>
                            <td className="ref">{l.level}</td>
                            <td>{l.label || "—"}</td>
                            <td className="muted" style={{ fontSize: 12.5 }}>{l.definition || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ),
            )}
          </div>
        </div>
      )}

      <Field label="Inherent Risk" help={`Likelihood × Impact before any controls are considered (1–${matrixSize} scale).`}>
        <div className="field-row">
          <Select value={String(f.inherent_likelihood)} onChange={(v) => set("inherent_likelihood", v === "" ? "" : Number(v))} options={LIKELIHOOD} placeholder="Likelihood" />
          <Select value={String(f.inherent_impact)} onChange={(v) => set("inherent_impact", v === "" ? "" : Number(v))} options={IMPACT} placeholder="Impact" />
          <div className="field" style={{ margin: 0 }}>
            <label>Score</label>
            <div style={{ paddingTop: 4 }}>
              {inhScore != null ? <Badge tone="neutral" plain>{inhScore}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
        {chosen(f.inherent_likelihood, f.inherent_impact)}
      </Field>
      <Field label="Residual Risk" help="Likelihood × Impact after controls. Leave blank until assessed.">
        <div className="field-row">
          <Select value={f.residual_likelihood} onChange={(v) => set("residual_likelihood", v)} options={LIKELIHOOD} placeholder="Likelihood" />
          <Select value={f.residual_impact} onChange={(v) => set("residual_impact", v)} options={IMPACT} placeholder="Impact" />
          <div className="field" style={{ margin: 0 }}>
            <label>Score</label>
            <div style={{ paddingTop: 4 }}>
              {resScore != null ? <Badge tone="neutral" plain>{resScore}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
        {chosen(f.residual_likelihood, f.residual_impact)}
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
      <Field
        label="Business units"
        help="The segments this risk sits in — a workshop scopes to one of these, and the register can be filtered by it."
      >
        <AsyncMultiSelect search={linkSearch("business-units")} value={f.business_unit_ids} onChange={(v) => set("business_unit_ids", v)} />
      </Field>
      <Field label="Processes" help="Business processes this risk affects, where the exposure is narrower than a whole unit.">
        <AsyncMultiSelect search={linkSearch("processes")} value={f.process_ids} onChange={(v) => set("process_ids", v)} />
      </Field>
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

  /* Inline relation chips. Each links to the record's own page, the same way the
     drawer's related-record chips do — the list is the workbench, so the graph has to
     be walkable from it. */
  const linkChips = (items: Ref[] | undefined, href: string) =>
    items && items.length ? (
      <div className="chips" onClick={(e) => e.stopPropagation()}>
        {items.map((x) => (
          <Link key={x.id} className="chip" href={`${href}?id=${x.id}`}>{x.name || x.title || x.reference || x.id}</Link>
        ))}
      </div>
    ) : <span className="muted">—</span>;
  const names = (items: Ref[] | undefined) => (items ?? []).map((x) => x.name || x.title || x.reference || "").join(", ");
  const rungLabel = (axis: "likelihood" | "impact", n: number | null) => {
    if (!n) return "—";
    const lvl = (axis === "likelihood" ? matrix?.likelihood_levels : matrix?.impact_levels)?.find((l) => l.level === n);
    return lvl?.label ? `${n} — ${lvl.label}` : String(n);
  };
  const classification = (l: number | null, i: number | null) =>
    l && i ? (
      <div className="chips">
        <span className="chip" title="Likelihood">L {rungLabel("likelihood", l)}</span>
        <span className="chip" title="Impact">I {rungLabel("impact", i)}</span>
      </div>
    ) : <span className="muted">—</span>;
  const scoreCell = (sev: string | null, score: number | null) => (
    <><Severity value={sev} /> <span className="muted">({score ?? "—"})</span></>
  );

  /* The full catalogue. What is shown by default is the working set a risk manager
     scans; everything else is one click away in the column chooser, and the layout
     is remembered per person. */
  const riskColumns: Column<RiskRow>[] = [
    { key: "reference", header: "Ref", sortable: true, locked: true, render: (r) => <span className="ref">{r.reference}</span> },
    { key: "title", header: "Title", sortable: true, locked: true, render: (r) => <span className="cell-title">{r.title}</span> },
    { key: "category", header: "Category", sortable: true, render: (r) => <span className="muted">{r.category || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge>, text: (r) => cap(r.status) },
    { key: "owner", header: "Owner", render: (r) => <span className="muted">{userName(r.owner_id)}</span>, text: (r) => userName(r.owner_id) },
    { key: "business_units", header: "Business units", render: (r) => linkChips(r.business_units, "/business-units"), text: (r) => names(r.business_units) },
    { key: "processes", header: "Processes", hidden: true, render: (r) => linkChips(r.processes, "/processes"), text: (r) => names(r.processes) },
    { key: "assets", header: "Assets", render: (r) => linkChips(r.assets, "/information-assets"), text: (r) => names(r.assets) },
    { key: "controls", header: "Controls", render: (r) => linkChips(r.controls, "/controls"), text: (r) => names(r.controls) },
    { key: "policies", header: "Policies", hidden: true, render: (r) => linkChips(r.policies, "/policies"), text: (r) => names(r.policies) },
    { key: "threats", header: "Threats", hidden: true, render: (r) => linkChips(r.threats, "/threat-library"), text: (r) => names(r.threats) },
    { key: "vulnerabilities", header: "Vulnerabilities", hidden: true, render: (r) => linkChips(r.vulnerabilities, "/threat-library"), text: (r) => names(r.vulnerabilities) },
    { key: "incidents", header: "Incidents", hidden: true, render: (r) => linkChips(r.incidents, "/incidents"), text: (r) => names(r.incidents) },
    { key: "inherent_classification", header: "Inherent classification", hidden: true, render: (r) => classification(r.inherent_likelihood, r.inherent_impact), text: (r) => `L${r.inherent_likelihood} I${r.inherent_impact}` },
    { key: "inherent_score", header: "Inherent", sortable: true, render: (r) => scoreCell(r.inherent_severity, r.inherent_score), text: (r) => `${r.inherent_score ?? ""} ${r.inherent_severity ?? ""}`.trim() },
    { key: "residual_classification", header: "Residual classification", hidden: true, render: (r) => classification(r.residual_likelihood, r.residual_impact), text: (r) => r.residual_likelihood ? `L${r.residual_likelihood} I${r.residual_impact}` : "" },
    { key: "residual_score", header: "Residual", sortable: true, render: (r) => scoreCell(r.residual_severity, r.residual_score), text: (r) => `${r.residual_score ?? ""} ${r.residual_severity ?? ""}`.trim() },
    { key: "appetite", header: "Appetite", render: (r) => { const a = appetite(r, settings); return a ? <Badge tone={a.tone}>{a.label}</Badge> : <span className="muted">—</span>; }, text: (r) => appetite(r, settings)?.label ?? "" },
    { key: "control_health", header: "Control health", render: (r) => controlHealth(r.control_health), text: (r) => r.control_health ?? "" },
    { key: "treatment_strategy", header: "Treatment", hidden: true, render: (r) => <span className="muted">{r.treatment_strategy ? cap(r.treatment_strategy) : "—"}</span>, text: (r) => r.treatment_strategy ? cap(r.treatment_strategy) : "" },
    { key: "treatment_owner", header: "Treatment owner", hidden: true, render: (r) => <span className="muted">{r.treatment_owner || "—"}</span> },
    { key: "treatment_deadline", header: "Treatment deadline", hidden: true, sortable: true, render: (r) => <span className="muted">{r.treatment_deadline || "—"}</span> },
    { key: "exposure", header: "Exposure", render: (r) => <span className="muted">{money(r.annual_loss_expectancy)}</span>, text: (r) => money(r.annual_loss_expectancy) },
    { key: "workflow_status", header: "Workflow", hidden: true, render: (r) => <span className="muted">{cap(r.workflow_status)}</span>, text: (r) => cap(r.workflow_status) },
    { key: "review_frequency", header: "Review cycle", hidden: true, render: (r) => <span className="muted">{cap(r.review_frequency)}</span>, text: (r) => cap(r.review_frequency) },
    { key: "last_review_date", header: "Last review", hidden: true, render: (r) => <span className="muted">{r.last_review_date || "—"}</span> },
    { key: "next_review_date", header: "Review", sortable: true, render: (r) => (isOverdue(r.next_review_date) ? <Badge tone="high">Overdue</Badge> : <span className="muted">{r.next_review_date || "—"}</span>), text: (r) => r.next_review_date ?? "" },
    { key: "created_at", header: "Created", hidden: true, render: (r) => <span className="muted">{r.created_at?.slice(0, 10) || "—"}</span>, text: (r) => r.created_at?.slice(0, 10) ?? "" },
    { key: "updated_at", header: "Updated", hidden: true, render: (r) => <span className="muted">{r.updated_at?.slice(0, 10) || "—"}</span>, text: (r) => r.updated_at?.slice(0, 10) ?? "" },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(r)}>Delete</button></div> },
  ];

  /** Delete every selected risk after one confirmation, then drop the selection. */
  async function removeMany(rowsToDelete: RiskRow[], clear: () => void) {
    const ok = await confirmDialog({
      title: `Delete ${rowsToDelete.length} risk${rowsToDelete.length === 1 ? "" : "s"}?`,
      message: "They are archived, not destroyed: links from other records are kept and the activity trail records who removed them.",
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    let failed = 0;
    for (const r of rowsToDelete) {
      try { await apiCall("DELETE", `/risks/${r.id}`); } catch { failed += 1; }
    }
    clear();
    reload();
    toast(failed ? `${rowsToDelete.length - failed} deleted, ${failed} failed.` : `${rowsToDelete.length} deleted.`);
  }

  /** A saved view restoring its filters into the page's own scope state. */
  const applyScope = (f: Record<string, string | number | boolean | undefined>) => {
    setScopeUnit(typeof f.business_unit_id === "string" ? f.business_unit_id : "");
    setScopeProcess(typeof f.process_id === "string" ? f.process_id : "");
    setScopeStatus(typeof f.status === "string" ? f.status : "");
    const assetId = typeof f.asset_id === "string" ? f.asset_id : "";
    if (!assetId) { setScopeAsset(null); return; }
    setScopeAsset({ id: assetId, name: "" });
    apiCall<{ id: string; name: string }>("GET", `/assets/${assetId}`)
      .then((a) => setScopeAsset({ id: a.id, name: a.name })).catch(() => {});
  };

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Risk Register</h1>
          <p>Identify, score and treat risks — qualitative ({matrixSize}×{matrixSize}) and quantitative (FAIR), with controls, threats and review cycles.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={() => setShowSettings((v) => !v)}>
            <IconGauge width={16} height={16} />
            Appetite
          </button>
          {/* The answer to "one control applies to four assets — shouldn't each get its
              own rating?". It should, and this is how: one proposed risk per asset, with
              the opening impact taken from that asset's own criticality, rather than one
              rating stretched across four assets that differ. */}
          <GenerateRisks label="the asset inventory" onDone={reload} />
          <ImportExport resource="risks" label="Risks" onDone={reload} />
          <OrphanCleanup onDone={reload} />
          <button
            className="btn secondary"
            onClick={() =>
              api
                .pdfRiskRegister(scopeFilters, scopeLabel === "Whole register" ? undefined : scopeLabel)
                .catch(() => {})
            }
          >
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
            <>
              <form onSubmit={saveSettings} style={{ display: "flex", gap: 14, alignItems: "flex-end", marginTop: 14 }}>
                <div style={{ width: 190 }}>
                  <label className="label">Appetite (1–{maxScore})</label>
                  <input className="input" type="number" min={1} max={maxScore} value={appetiteScore} onChange={(e) => setAppetiteScore(Number(e.target.value))} />
                </div>
                <div style={{ width: 190 }}>
                  <label className="label">Tolerance (1–{maxScore})</label>
                  <input className="input" type="number" min={1} max={maxScore} value={toleranceScore} onChange={(e) => setToleranceScore(Number(e.target.value))} />
                </div>
                <button className="btn">Save thresholds</button>
              </form>

              <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 16 }}>
                <RiskMethodology
                  onSaved={() => {
                    reload();
                    api.riskSettings().then(setSettings).catch(() => {});
                    // Pull the new wording straight through, so criteria written here
                    // show up on the next risk form without a page reload.
                    api.riskMatrixConfig().then(setMatrix).catch(() => {});
                  }}
                />
              </div>
            </>
          )}
        </div>
      )}

      {/* Segment scope. Kept above the table rather than inside it because it is a
          scope, not a column filter: everything on the page — counts, the export —
          means "within this segment" once one is chosen. */}
      <div className="card card-pad" style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div style={{ width: 220 }}>
          <label className="label">Business unit</label>
          <Select
            value={scopeUnit}
            onChange={setScopeUnit}
            options={segments.units.map((u) => ({ value: u.id, label: u.name || u.id }))}
            placeholder="All business units"
          />
        </div>
        <div style={{ width: 220 }}>
          <label className="label">Process</label>
          <Select
            value={scopeProcess}
            onChange={setScopeProcess}
            options={segments.processes.map((x) => ({ value: x.id, label: x.name || x.id }))}
            placeholder="All processes"
          />
        </div>
        <div style={{ width: 230 }}>
          <label className="label">Asset</label>
          {/* Typeahead rather than a dropdown: an inventory runs to thousands, and a
              preloaded list could never reach the asset somebody actually wants. */}
          <AsyncSelect
            search={linkSearch("assets")}
            value={scopeAsset?.id ?? null}
            selectedLabel={scopeAsset?.name}
            onChange={(id, opt) => setScopeAsset(id ? { id, name: opt?.label ?? "" } : null)}
            placeholder="All assets"
          />
        </div>
        <div style={{ width: 190 }}>
          <label className="label">Status</label>
          <Select value={scopeStatus} onChange={setScopeStatus} options={STATUS} placeholder="Any status" />
        </div>
        {(scopeUnit || scopeProcess || scopeAsset || scopeStatus) && (
          <button
            className="btn secondary"
            onClick={() => { setScopeUnit(""); setScopeProcess(""); setScopeAsset(null); setScopeStatus(""); }}
          >
            Clear scope
          </button>
        )}
        <div className="muted" style={{ fontSize: 12.5, marginLeft: "auto", paddingBottom: 8 }}>
          {scopeLabel}
        </div>
      </div>

      <DataTable<RiskRow>
        tableKey="risks"
        statusModel="risk"
        columns={riskColumns}
        fetcher={fetchRisks}
        filters={scopeFilters}
        onApplyFilters={applyScope}
        bulkActions={(rows, clear) => (
          <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
        )}
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
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Control health</div><div style={{ marginTop: 4 }}>{controlHealth(detail.control_health)}</div></div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}><div className="muted" style={{ fontSize: 12 }}>Exposure (ALE)</div><div style={{ marginTop: 4 }}>{money(detail.annual_loss_expectancy)}</div></div>
            </div>

            <WorkflowStrip
              entityType="risk"
              entityId={detail.id}
              entityLabel={`${detail.reference} — ${detail.title}`}
              link="/risks"
              ownerEmail={userName(detail.owner_id)}
              onChange={() => { reload(); loadDetail(detail.id); }}
            />

            <ResidualSuggestion
              riskId={detail.id}
              onAccepted={() => { reload(); loadDetail(detail.id); }}
            />

            <RiskAcceptancePanel
              riskId={detail.id}
              riskReference={detail.reference}
              acceptances={detail.acceptances ?? []}
              onChange={() => { reload(); loadDetail(detail.id); }}
            />

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
              <RelatedChips label="Business units" items={detail.business_units} href="/business-units" />
              <RelatedChips label="Processes" items={detail.processes} href="/processes" />
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
