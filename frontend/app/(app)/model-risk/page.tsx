"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";

// ------------------------------------------------------------------ local types
interface ModelValidation {
  id: string;
  model_id: string;
  reference: string;
  validation_type: string;
  validator: string;
  validation_date: string | null;
  outcome: string;
  findings: string;
  performance_metrics: string;
  recommendations: string;
  status: string;
  created_at: string;
}
interface ModelInventory {
  id: string;
  reference: string;
  name: string;
  purpose: string;
  model_type: string;
  owner: string;
  developer: string;
  vendor: string;
  materiality: string;
  status: string;
  regulatory_relevant: boolean;
  ai_ml: boolean;
  methodology: string;
  last_validation_date: string | null;
  next_validation_date: string | null;
  workflow_status: string;
  validation_count: number;
  is_validation_overdue: boolean;
  created_at: string;
  validations: ModelValidation[];
}
interface ModelRiskSummary {
  total_models: number;
  models_by_status: Record<string, number>;
  models_by_type: Record<string, number>;
  validation_overdue: number;
  ai_ml_count: number;
  regulatory_relevant_count: number;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ enum lists
const MODEL_TYPE = opts([
  "credit_scoring",
  "ifrs9_ecl",
  "aml_transaction_monitoring",
  "fraud_detection",
  "capital",
  "stress_testing",
  "market_risk",
  "ai_ml",
  "other",
]);
const MODEL_STATUS = opts(["development", "validated", "in_production", "under_review", "retired"]);
const MATERIALITY = opts(["low", "medium", "high", "critical"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const VAL_TYPE = opts(["initial", "periodic", "targeted"]);
const VAL_OUTCOME = opts(["pass", "pass_with_findings", "fail", "not_completed"]);
const VAL_STATUS = opts(["planned", "in_progress", "completed"]);

// ------------------------------------------------------------------ tones
const STATUS_TONE: Record<string, Tone> = {
  development: "neutral",
  validated: "info",
  in_production: "low",
  under_review: "medium",
  retired: "neutral",
};
const MATERIALITY_TONE: Record<string, Tone> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};
const OUTCOME_TONE: Record<string, Tone> = {
  pass: "low",
  pass_with_findings: "medium",
  fail: "critical",
  not_completed: "neutral",
};
const VAL_STATUS_TONE: Record<string, Tone> = {
  planned: "neutral",
  in_progress: "info",
  completed: "low",
};

function OutcomeBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={OUTCOME_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

// ------------------------------------------------------------------ model form state
type ModelForm = {
  name: string;
  purpose: string;
  model_type: string;
  materiality: string;
  status: string;
  regulatory_relevant: boolean;
  ai_ml: boolean;
  methodology: string;
  owner: string;
  developer: string;
  vendor: string;
  last_validation_date: string;
  next_validation_date: string;
  workflow_status: string;
};
const BLANK_MODEL: ModelForm = {
  name: "",
  purpose: "",
  model_type: "credit_scoring",
  materiality: "medium",
  status: "development",
  regulatory_relevant: false,
  ai_ml: false,
  methodology: "",
  owner: "",
  developer: "",
  vendor: "",
  last_validation_date: "",
  next_validation_date: "",
  workflow_status: "draft",
};
function fromModel(m: ModelInventory): ModelForm {
  return {
    name: m.name,
    purpose: m.purpose || "",
    model_type: m.model_type || "credit_scoring",
    materiality: m.materiality || "medium",
    status: m.status || "development",
    regulatory_relevant: !!m.regulatory_relevant,
    ai_ml: !!m.ai_ml,
    methodology: m.methodology || "",
    owner: m.owner || "",
    developer: m.developer || "",
    vendor: m.vendor || "",
    last_validation_date: m.last_validation_date || "",
    next_validation_date: m.next_validation_date || "",
    workflow_status: m.workflow_status || "draft",
  };
}
function modelPayload(f: ModelForm): Record<string, unknown> {
  return {
    name: f.name,
    purpose: f.purpose,
    model_type: f.model_type,
    materiality: f.materiality,
    status: f.status,
    regulatory_relevant: f.regulatory_relevant,
    ai_ml: f.ai_ml,
    methodology: f.methodology,
    owner: f.owner,
    developer: f.developer,
    vendor: f.vendor,
    last_validation_date: f.last_validation_date || null,
    next_validation_date: f.next_validation_date || null,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ validation draft
type ValDraft = {
  validation_type: string;
  validator: string;
  validation_date: string;
  outcome: string;
  status: string;
  findings: string;
  performance_metrics: string;
  recommendations: string;
};
const BLANK_VAL: ValDraft = {
  validation_type: "periodic",
  validator: "",
  validation_date: "",
  outcome: "not_completed",
  status: "planned",
  findings: "",
  performance_metrics: "",
  recommendations: "",
};

function ModelRiskInner() {
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  const [summary, setSummary] = useState<ModelRiskSummary | null>(null);

  const [openId, setOpenId] = useRecordParam("id");
  const [modelDetail, setModelDetail] = useState<ModelInventory | null>(null);

  // ---- filters ----
  const [fType, setFType] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fAiMl, setFAiMl] = useState(false);
  const [fOverdue, setFOverdue] = useState(false);

  // ---- model dialog ----
  const [editingModel, setEditingModel] = useState<ModelInventory | null>(null);
  const [showModelForm, setShowModelForm] = useState(false);
  const [savingModel, setSavingModel] = useState(false);
  const [mf, setMf] = useState<ModelForm>(BLANK_MODEL);
  const setM = <K extends keyof ModelForm>(k: K, v: ModelForm[K]) => setMf((p) => ({ ...p, [k]: v }));

  // ---- inline validation add-form ----
  const [vd, setVd] = useState<ValDraft>(BLANK_VAL);
  const setV = <K extends keyof ValDraft>(k: K, v: ValDraft[K]) => setVd((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- fetcher + loaders
  const fetchModels = useCallback((qs: string) => apiCall<PagedList<ModelInventory>>("GET", `/model-risk?${qs}`), []);

  async function loadSummary() {
    try {
      setSummary(await apiCall<ModelRiskSummary>("GET", "/model-risk-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load model-risk summary");
    }
  }
  useEffect(() => {
    loadSummary();
  }, []);

  const loadModelDetail = useCallback((id: string) => {
    apiCall<ModelInventory>("GET", `/model-risk/${id}`).then(setModelDetail).catch(() => setModelDetail(null));
  }, []);
  useEffect(() => {
    if (openId) { setVd(BLANK_VAL); loadModelDetail(openId); }
    else setModelDetail(null);
  }, [openId, loadModelDetail]);

  // ------------------------------------------------------------- model CRUD
  function openNewModel() {
    setEditingModel(null);
    setMf(BLANK_MODEL);
    setError(null);
    setShowModelForm(true);
  }
  function openEditModel(m: ModelInventory) {
    setEditingModel(m);
    setMf(fromModel(m));
    setError(null);
    setShowModelForm(true);
  }
  async function saveModel() {
    setError(null);
    setSavingModel(true);
    try {
      const payload = modelPayload(mf);
      if (editingModel) await apiCall<ModelInventory>("PATCH", `/model-risk/${editingModel.id}`, payload);
      else await apiCall<ModelInventory>("POST", "/model-risk", payload);
      setShowModelForm(false);
      reload();
      if (openId) loadModelDetail(openId);
      await loadSummary();
      toast(editingModel ? "Changes saved" : "Model created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save model");
    } finally {
      setSavingModel(false);
    }
  }
  async function removeModel(m: ModelInventory) {
    if (!(await confirmDialog({ title: `Delete model ${m.reference || m.name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/model-risk/${m.id}`);
      setShowModelForm(false);
      if (openId === m.id) setOpenId(null);
      reload();
      await loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- validations (inline)
  async function addValidation() {
    if (!modelDetail) return;
    setError(null);
    try {
      const updated = await apiCall<ModelInventory>("POST", `/model-risk/${modelDetail.id}/validations`, {
        validation_type: vd.validation_type,
        validator: vd.validator,
        validation_date: vd.validation_date || null,
        outcome: vd.outcome,
        status: vd.status,
        findings: vd.findings,
        performance_metrics: vd.performance_metrics,
        recommendations: vd.recommendations,
      });
      setVd(BLANK_VAL);
      setModelDetail(updated);
      reload();
      await loadSummary();
      toast("Validation added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add validation");
    }
  }
  async function removeValidation(vid: string) {
    if (!modelDetail) return;
    if (!(await confirmDialog({ title: "Remove this validation?", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/model-validations/${vid}`);
      loadModelDetail(modelDetail.id);
      reload();
      await loadSummary();
      toast("Removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove validation");
    }
  }

  // ------------------------------------------------------------- columns
  const columns: Column<ModelInventory>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (m) => <span className="ref">{m.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, render: (m) => <span className="cell-title">{m.name}</span> },
    { key: "model_type", header: "Type", sortable: true, render: (m) => <Badge tone="info">{cap(m.model_type)}</Badge> },
    { key: "owner", header: "Owner", sortable: true, render: (m) => <span className="muted">{m.owner || "—"}</span> },
    { key: "materiality", header: "Materiality", sortable: true, render: (m) => <Badge tone={MATERIALITY_TONE[m.materiality] || "neutral"}>{cap(m.materiality)}</Badge> },
    { key: "status", header: "Status", sortable: true, render: (m) => <Badge tone={STATUS_TONE[m.status] || "neutral"}>{cap(m.status)}</Badge> },
    { key: "flags", header: "Flags", render: (m) => (
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {m.ai_ml && <Badge tone="info">AI/ML</Badge>}
        {m.regulatory_relevant && <Badge tone="medium">Regulatory</Badge>}
      </div>
    ) },
    { key: "next_validation_date", header: "Next validation", sortable: true, render: (m) => (m.is_validation_overdue ? <Badge tone="critical">Overdue</Badge> : <span className="muted">{m.next_validation_date || "—"}</span>) },
    { key: "actions", header: "", render: (m) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditModel(m)}>Edit</button> <button className="btn secondary sm" onClick={() => removeModel(m)}>Delete</button></div> },
  ];

  // ------------------------------------------------------------- model form tabs
  const modelTab = (
    <>
      <Field label="Model name" required help="For example: IFRS 9 ECL — retail portfolio.">
        <TextInput value={mf.name} onChange={(v) => setM("name", v)} placeholder="Model name" required />
      </Field>
      <Field label="Purpose" help="What the model is used for and the decisions it drives.">
        <TextArea value={mf.purpose} onChange={(v) => setM("purpose", v)} rows={3} placeholder="Purpose and business use." />
      </Field>
      <div className="field-row">
        <Field label="Model type" help="Model family / regulatory category.">
          <Select value={mf.model_type} onChange={(v) => setM("model_type", v)} options={MODEL_TYPE} />
        </Field>
        <Field label="Materiality" help="Risk-tier of the model (drives validation intensity).">
          <Select value={mf.materiality} onChange={(v) => setM("materiality", v)} options={MATERIALITY} />
        </Field>
      </div>
      <Field label="Status">
        <Select value={mf.status} onChange={(v) => setM("status", v)} options={MODEL_STATUS} />
      </Field>
      <div className="field-row">
        <Field label="Regulatory relevant" help="Used for regulatory reporting / capital (IFRS 9, Basel, SBP).">
          <Toggle checked={mf.regulatory_relevant} onChange={(v) => setM("regulatory_relevant", v)} label="Regulatory-relevant model" />
        </Field>
        <Field label="AI / ML" help="Model uses machine-learning / AI techniques (ISO 42001).">
          <Toggle checked={mf.ai_ml} onChange={(v) => setM("ai_ml", v)} label="AI / ML model" />
        </Field>
      </div>
      <Field label="Methodology" help="Modelling approach, assumptions and key parameters.">
        <TextArea value={mf.methodology} onChange={(v) => setM("methodology", v)} rows={3} placeholder="Logistic regression, gradient boosting, PD/LGD/EAD structure…" />
      </Field>
    </>
  );
  const ownershipTab = (
    <>
      <Field label="Model owner" help="Accountable business / risk owner.">
        <TextInput value={mf.owner} onChange={(v) => setM("owner", v)} placeholder="Owner" />
      </Field>
      <div className="field-row">
        <Field label="Developer" help="Internal team or individual that built the model.">
          <TextInput value={mf.developer} onChange={(v) => setM("developer", v)} placeholder="Developer" />
        </Field>
        <Field label="Vendor" help="Third-party vendor, if the model is externally sourced.">
          <TextInput value={mf.vendor} onChange={(v) => setM("vendor", v)} placeholder="Vendor" />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this inventory record.">
        <Select value={mf.workflow_status} onChange={(v) => setM("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );
  const scheduleTab = (
    <>
      <div className="field-row">
        <Field label="Last validation date" help="When the model was last independently validated.">
          <TextInput type="date" value={mf.last_validation_date} onChange={(v) => setM("last_validation_date", v)} />
        </Field>
        <Field label="Next validation date" help="Target for the next validation — drives the overdue flag.">
          <TextInput type="date" value={mf.next_validation_date} onChange={(v) => setM("next_validation_date", v)} />
        </Field>
      </div>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Model Risk &amp; AI Governance</h1>
          <p>Model inventory (IFRS 9 ECL, AML scoring, credit scoring, AI/ML) with materiality tiering and independent validation cycles (SR 11-7 / ISO 42001).</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" onClick={openNewModel}>Add model</button>
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.total_models.toLocaleString() : "—"}</span></div>
          <span className="l">Models in inventory</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.ai_ml_count.toLocaleString() : "—"}</span></div>
          <span className="l">AI / ML models</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.validation_overdue.toLocaleString() : "—"}</span></div>
          <span className="l">Validation overdue</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.regulatory_relevant_count.toLocaleString() : "—"}</span></div>
          <span className="l">Regulatory-relevant</span>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<ModelInventory>
        columns={columns}
        fetcher={fetchModels}
        rowKey={(m) => m.id}
        onRowClick={(m) => setOpenId(m.id)}
        activeKey={openId}
        searchPlaceholder="Search models by name, reference, owner or vendor…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        filters={{
          model_type: fType || undefined,
          status: fStatus || undefined,
          ai_ml: fAiMl,
          validation_overdue: fOverdue,
        }}
        toolbarRight={
          <>
            <select className="select" style={{ width: 180 }} value={fType} onChange={(e) => setFType(e.target.value)}>
              <option value="">All types</option>
              {MODEL_TYPE.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <select className="select" style={{ width: 160 }} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
              <option value="">All statuses</option>
              {MODEL_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <label className="label" style={{ display: "flex", gap: 6, alignItems: "center", margin: 0 }}>
              <input type="checkbox" checked={fAiMl} onChange={(e) => setFAiMl(e.target.checked)} /> AI / ML
            </label>
            <label className="label" style={{ display: "flex", gap: 6, alignItems: "center", margin: 0 }}>
              <input type="checkbox" checked={fOverdue} onChange={(e) => setFOverdue(e.target.checked)} /> Overdue
            </label>
          </>
        }
        emptyMessage="No models. Register the bank's quantitative and AI/ML models to build a materiality-tiered inventory with validation cycles."
        refreshKey={refreshKey}
      />

      {/* ============================================= MODEL DRAWER */}
      <RecordDrawer
        open={!!openId && !!modelDetail}
        onClose={() => setOpenId(null)}
        title={modelDetail ? `${modelDetail.reference || ""} ${modelDetail.name}`.trim() : "…"}
        subtitle={modelDetail ? `${cap(modelDetail.model_type)} · ${cap(modelDetail.status)} · ${cap(modelDetail.materiality)} materiality${modelDetail.owner ? " · owner " + modelDetail.owner : ""}` : ""}
        width={860}
        actions={modelDetail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditModel(modelDetail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeModel(modelDetail)}>Delete</button>
          </>
        )}
      >
        {modelDetail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              {modelDetail.ai_ml && <Badge tone="info">AI/ML</Badge>}
              {modelDetail.regulatory_relevant && <Badge tone="medium">Regulatory</Badge>}
              {modelDetail.is_validation_overdue && <Badge tone="critical">Validation overdue</Badge>}
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-pad">
                <strong>Validation cycles</strong>
                <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                  Independent validation exercises (initial / periodic / targeted) with outcome, findings and recommendations.
                </p>
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(ev) => { ev.preventDefault(); addValidation(); }}
                >
                  <div style={{ width: 130 }}>
                    <label className="label">Type</label>
                    <select className="select" value={vd.validation_type} onChange={(ev) => setV("validation_type", ev.target.value)}>
                      {VAL_TYPE.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label">Validator</label>
                    <input className="input" value={vd.validator} onChange={(ev) => setV("validator", ev.target.value)} placeholder="Validator" />
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label">Validation date</label>
                    <input className="input" type="date" value={vd.validation_date} onChange={(ev) => setV("validation_date", ev.target.value)} />
                  </div>
                  <div style={{ width: 160 }}>
                    <label className="label">Outcome</label>
                    <select className="select" value={vd.outcome} onChange={(ev) => setV("outcome", ev.target.value)}>
                      {VAL_OUTCOME.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Status</label>
                    <select className="select" value={vd.status} onChange={(ev) => setV("status", ev.target.value)}>
                      {VAL_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                  </div>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Findings</label>
                    <input className="input" value={vd.findings} onChange={(ev) => setV("findings", ev.target.value)} placeholder="Key findings" />
                  </div>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Performance metrics</label>
                    <input className="input" value={vd.performance_metrics} onChange={(ev) => setV("performance_metrics", ev.target.value)} placeholder="AUC, Gini, PSI…" />
                  </div>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Recommendations</label>
                    <input className="input" value={vd.recommendations} onChange={(ev) => setV("recommendations", ev.target.value)} placeholder="Remediation" />
                  </div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ref</th>
                        <th>Type</th>
                        <th>Validator</th>
                        <th>Date</th>
                        <th>Outcome</th>
                        <th>Status</th>
                        <th>Findings</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...modelDetail.validations]
                        .sort((a, b) => (b.validation_date || "").localeCompare(a.validation_date || ""))
                        .map((v) => (
                          <tr key={v.id}>
                            <td className="ref">{v.reference || "—"}</td>
                            <td className="cell-title">{cap(v.validation_type)}</td>
                            <td className="muted">{v.validator || "—"}</td>
                            <td className="muted">{v.validation_date || "—"}</td>
                            <td><OutcomeBadge value={v.outcome} /></td>
                            <td><Badge tone={VAL_STATUS_TONE[v.status] || "neutral"}>{cap(v.status)}</Badge></td>
                            <td className="muted">{v.findings || "—"}</td>
                            <td>
                              <button className="btn secondary sm" onClick={() => removeValidation(v.id)}>Remove</button>
                            </td>
                          </tr>
                        ))}
                      {modelDetail.validations.length === 0 && (
                        <tr><td colSpan={8}><span className="muted">No validations recorded yet.</span></td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <RecordPanels model="model_inventory" entityId={modelDetail.id} />
          </>
        )}
      </RecordDrawer>

      {/* ============================================= MODAL */}
      {showModelForm && (
        <FormModal
          title={editingModel ? `Edit model — ${editingModel.reference || editingModel.name}` : "New model"}
          wide
          tabs={[
            { id: "model", label: "Model", content: modelTab, required: true },
            { id: "ownership", label: "Ownership", content: ownershipTab },
            { id: "schedule", label: "Validation schedule", content: scheduleTab },
          ]}
          onClose={() => setShowModelForm(false)}
          onSave={saveModel}
          saving={savingModel}
          error={error}
          saveLabel={editingModel ? "Save changes" : "Create model"}
          footerLeft={
            editingModel ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeModel(editingModel)}
                disabled={savingModel}
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

export default function ModelRiskPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ModelRiskInner />
    </Suspense>
  );
}
