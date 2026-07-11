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
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";

// ------------------------------------------------------------------ types
interface EsgAssessment {
  id: string;
  reference: string;
  title: string;
  description: string;
  pillar: string;
  category: string;
  metric: string;
  target_value: string;
  current_value: string;
  unit: string;
  status: string;
  owner: string;
  period: string;
  sbp_green_banking_ref: string;
  workflow_status: string;
  progress_note: string;
  created_at: string;
}
interface EnvRating {
  id: string;
  reference: string;
  entity_name: string;
  sector: string;
  risk_category: string;
  assessment: string;
  mitigation: string;
  rating_date: string | null;
  assessor: string;
  created_at: string;
}
interface EsgSummary {
  total_assessments: number;
  by_pillar: Record<string, number>;
  by_status: Record<string, number>;
  achieved: number;
  achieved_pct: number;
  env_ratings_total: number;
  env_by_category: Record<string, number>;
  high_env_risk: number;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ enum lists
const PILLARS = opts(["environmental", "social", "governance"]);
const ESG_STATUS = opts(["not_started", "in_progress", "achieved", "off_track"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const ENV_RISK = opts(["high", "medium", "low"]);

// ------------------------------------------------------------------ tones
const PILLAR_TONE: Record<string, Tone> = { environmental: "low", social: "info", governance: "medium" };
const ESG_STATUS_TONE: Record<string, Tone> = { not_started: "neutral", in_progress: "info", achieved: "low", off_track: "critical" };
const ENV_RISK_TONE: Record<string, Tone> = { high: "critical", medium: "medium", low: "low" };

// ------------------------------------------------------------------ form state
type EsgForm = {
  title: string; description: string; pillar: string; category: string; metric: string;
  target_value: string; current_value: string; unit: string; status: string; owner: string;
  period: string; sbp_green_banking_ref: string; workflow_status: string;
};
const BLANK_ESG: EsgForm = {
  title: "", description: "", pillar: "environmental", category: "", metric: "",
  target_value: "", current_value: "", unit: "", status: "not_started", owner: "",
  period: "", sbp_green_banking_ref: "", workflow_status: "draft",
};
function fromEsg(a: EsgAssessment): EsgForm {
  return {
    title: a.title, description: a.description || "", pillar: a.pillar || "environmental",
    category: a.category || "", metric: a.metric || "", target_value: a.target_value || "",
    current_value: a.current_value || "", unit: a.unit || "", status: a.status || "not_started",
    owner: a.owner || "", period: a.period || "", sbp_green_banking_ref: a.sbp_green_banking_ref || "",
    workflow_status: a.workflow_status || "draft",
  };
}

type EnvForm = {
  entity_name: string; sector: string; risk_category: string; assessment: string;
  mitigation: string; rating_date: string; assessor: string;
};
const BLANK_ENV: EnvForm = {
  entity_name: "", sector: "", risk_category: "low", assessment: "", mitigation: "", rating_date: "", assessor: "",
};
function fromEnv(r: EnvRating): EnvForm {
  return {
    entity_name: r.entity_name, sector: r.sector || "", risk_category: r.risk_category || "low",
    assessment: r.assessment || "", mitigation: r.mitigation || "", rating_date: r.rating_date || "",
    assessor: r.assessor || "",
  };
}

type SectionId = "assessments" | "ratings";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "assessments", label: "ESG Assessments" },
  { id: "ratings", label: "Environmental Risk Ratings" },
];

/* ================================================================ page ===== */
function EsgInner() {
  const [section, setSection] = useState<SectionId>("assessments");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<EsgSummary | null>(null);

  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<EsgAssessment | null>(null);

  // ---- ESG dialog ----
  const [editingEsg, setEditingEsg] = useState<EsgAssessment | null>(null);
  const [showEsgForm, setShowEsgForm] = useState(false);
  const [savingEsg, setSavingEsg] = useState(false);
  const [ef, setEf] = useState<EsgForm>(BLANK_ESG);
  const setE = <K extends keyof EsgForm>(k: K, v: EsgForm[K]) => setEf((p) => ({ ...p, [k]: v }));

  // ---- Env rating dialog ----
  const [editingEnv, setEditingEnv] = useState<EnvRating | null>(null);
  const [showEnvForm, setShowEnvForm] = useState(false);
  const [savingEnv, setSavingEnv] = useState(false);
  const [rf, setRf] = useState<EnvForm>(BLANK_ENV);
  const setR = <K extends keyof EnvForm>(k: K, v: EnvForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchAssessments = useCallback((qs: string) => apiCall<PagedList<EsgAssessment>>("GET", `/esg-assessments?${qs}`), []);
  const fetchRatings = useCallback((qs: string) => apiCall<PagedList<EnvRating>>("GET", `/environmental-risk-ratings?${qs}`), []);

  const loadSummary = useCallback(() => { apiCall<EsgSummary>("GET", "/esg-summary").then(setSummary).catch(() => {}); }, []);
  const loadDetail = useCallback((id: string) => { apiCall<EsgAssessment>("GET", `/esg-assessments/${id}`).then(setDetail).catch(() => setDetail(null)); }, []);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // ------------------------------------------------------------- ESG CRUD
  function openNewEsg() { setEditingEsg(null); setEf(BLANK_ESG); setError(null); setShowEsgForm(true); }
  function openEditEsg(a: EsgAssessment) { setEditingEsg(a); setEf(fromEsg(a)); setError(null); setShowEsgForm(true); }
  async function saveEsg() {
    setError(null); setSavingEsg(true);
    try {
      if (editingEsg) await apiCall("PATCH", `/esg-assessments/${editingEsg.id}`, ef);
      else await apiCall("POST", "/esg-assessments", ef);
      setShowEsgForm(false); reload(); loadSummary(); if (openId) loadDetail(openId);
      toast(editingEsg ? "Changes saved" : "ESG assessment created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save ESG assessment"); }
    finally { setSavingEsg(false); }
  }
  async function removeEsg(a: EsgAssessment) {
    if (!(await confirmDialog({ title: `Delete ESG assessment ${a.reference || a.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/esg-assessments/${a.id}`);
      setShowEsgForm(false); if (openId === a.id) setOpenId(null); reload(); loadSummary(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }

  // ------------------------------------------------------------- Env rating CRUD
  function openNewEnv() { setEditingEnv(null); setRf(BLANK_ENV); setError(null); setShowEnvForm(true); }
  function openEditEnv(r: EnvRating) { setEditingEnv(r); setRf(fromEnv(r)); setError(null); setShowEnvForm(true); }
  async function saveEnv() {
    setError(null); setSavingEnv(true);
    try {
      const payload = { ...rf, rating_date: rf.rating_date || null };
      if (editingEnv) await apiCall("PATCH", `/environmental-risk-ratings/${editingEnv.id}`, payload);
      else await apiCall("POST", "/environmental-risk-ratings", payload);
      setShowEnvForm(false); reload(); loadSummary();
      toast(editingEnv ? "Changes saved" : "Rating created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save environmental risk rating"); }
    finally { setSavingEnv(false); }
  }
  async function removeEnv(r: EnvRating) {
    if (!(await confirmDialog({ title: `Delete environmental risk rating ${r.reference || r.entity_name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/environmental-risk-ratings/${r.id}`);
      setShowEnvForm(false); reload(); loadSummary(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }

  // ------------------------------------------------------------- columns
  const esgColumns: Column<EsgAssessment>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (a) => <span className="ref">{a.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (a) => <span className="cell-title">{a.title}</span> },
    { key: "pillar", header: "Pillar", sortable: true, render: (a) => <Badge tone={PILLAR_TONE[a.pillar] || "neutral"}>{cap(a.pillar)}</Badge> },
    { key: "category", header: "Category", sortable: true, render: (a) => <span className="muted">{a.category || "—"}</span> },
    { key: "target", header: "Target", render: (a) => <span className="muted">{a.target_value ? `${a.target_value}${a.unit ? " " + a.unit : ""}` : "—"}</span> },
    { key: "current", header: "Current", render: (a) => <span className="muted">{a.current_value ? `${a.current_value}${a.unit ? " " + a.unit : ""}` : "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (a) => <Badge tone={ESG_STATUS_TONE[a.status] || "neutral"}>{cap(a.status)}</Badge> },
    { key: "actions", header: "", render: (a) => <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditEsg(a)}>Edit</button><button className="btn secondary sm" onClick={() => removeEsg(a)}>Delete</button></div> },
  ];

  const envColumns: Column<EnvRating>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference || "—"}</span> },
    { key: "entity_name", header: "Entity", sortable: true, render: (r) => <span className="cell-title">{r.entity_name}</span> },
    { key: "sector", header: "Sector", sortable: true, render: (r) => <span className="muted">{r.sector || "—"}</span> },
    { key: "risk_category", header: "Risk category", sortable: true, render: (r) => <Badge tone={ENV_RISK_TONE[r.risk_category] || "neutral"}>{cap(r.risk_category)}</Badge> },
    { key: "assessor", header: "Assessor", sortable: true, render: (r) => <span className="muted">{r.assessor || "—"}</span> },
    { key: "rating_date", header: "Rating date", sortable: true, render: (r) => <span className="muted">{r.rating_date || "—"}</span> },
    { key: "actions", header: "", render: (r) => <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditEnv(r)}>Edit</button><button className="btn secondary sm" onClick={() => removeEnv(r)}>Delete</button></div> },
  ];

  // ------------------------------------------------------------- ESG form tabs
  const esgGeneral = (
    <>
      <Field label="Title" required help="For example: Green financing portfolio share.">
        <TextInput value={ef.title} onChange={(v) => setE("title", v)} placeholder="ESG metric / target title" required />
      </Field>
      <div className="field-row">
        <Field label="Pillar" help="Environmental, social, or governance.">
          <Select value={ef.pillar} onChange={(v) => setE("pillar", v)} options={PILLARS} />
        </Field>
        <Field label="Category" help='e.g. "climate risk", "green financing", "financial inclusion".'>
          <TextInput value={ef.category} onChange={(v) => setE("category", v)} placeholder="green financing" />
        </Field>
      </div>
      <Field label="Metric" help="What is being measured.">
        <TextInput value={ef.metric} onChange={(v) => setE("metric", v)} placeholder="Green financing as % of advances" />
      </Field>
      <div className="field-row">
        <Field label="Target value">
          <TextInput value={ef.target_value} onChange={(v) => setE("target_value", v)} placeholder="10" />
        </Field>
        <Field label="Current value">
          <TextInput value={ef.current_value} onChange={(v) => setE("current_value", v)} placeholder="6.4" />
        </Field>
        <Field label="Unit" help='e.g. "%", "PKR mn", "count".'>
          <TextInput value={ef.unit} onChange={(v) => setE("unit", v)} placeholder="%" />
        </Field>
      </div>
      <Field label="Status" help="Progress against target.">
        <Select value={ef.status} onChange={(v) => setE("status", v)} options={ESG_STATUS} />
      </Field>
      <Field label="Description">
        <TextArea value={ef.description} onChange={(v) => setE("description", v)} rows={3} placeholder="Context for this ESG metric." />
      </Field>
    </>
  );
  const esgGovernance = (
    <>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={ef.owner} onChange={(v) => setE("owner", v)} placeholder="Sustainability lead" />
        </Field>
        <Field label="Period" help="Reporting period, e.g. FY26 or Q1 2026.">
          <TextInput value={ef.period} onChange={(v) => setE("period", v)} placeholder="FY26" />
        </Field>
      </div>
      <Field label="SBP Green Banking reference" help="Clause / requirement in the SBP Green Banking Guidelines.">
        <TextInput value={ef.sbp_green_banking_ref} onChange={(v) => setE("sbp_green_banking_ref", v)} placeholder="GBG 2017 §4.2" />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this record.">
        <Select value={ef.workflow_status} onChange={(v) => setE("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  const envGeneral = (
    <>
      <Field label="Entity name" required help="Borrower, client, or vendor being rated.">
        <TextInput value={rf.entity_name} onChange={(v) => setR("entity_name", v)} placeholder="ACME Cement Ltd" required />
      </Field>
      <div className="field-row">
        <Field label="Sector">
          <TextInput value={rf.sector} onChange={(v) => setR("sector", v)} placeholder="Cement / manufacturing" />
        </Field>
        <Field label="Risk category" help="Environmental risk level of this exposure.">
          <Select value={rf.risk_category} onChange={(v) => setR("risk_category", v)} options={ENV_RISK} />
        </Field>
      </div>
      <Field label="Assessment" help="Environmental due-diligence findings.">
        <TextArea value={rf.assessment} onChange={(v) => setR("assessment", v)} rows={3} placeholder="Environmental exposure assessment." />
      </Field>
      <Field label="Mitigation" help="Mitigating measures / covenants.">
        <TextArea value={rf.mitigation} onChange={(v) => setR("mitigation", v)} rows={3} placeholder="Mitigation measures." />
      </Field>
      <div className="field-row">
        <Field label="Rating date">
          <TextInput type="date" value={rf.rating_date} onChange={(v) => setR("rating_date", v)} />
        </Field>
        <Field label="Assessor">
          <TextInput value={rf.assessor} onChange={(v) => setR("assessor", v)} placeholder="Credit risk officer" />
        </Field>
      </div>
    </>
  );

  const offTrack = summary ? summary.by_status["off_track"] || 0 : null;

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>ESG / Green Banking</h1>
          <p>SBP Green Banking Guidelines alignment, ESG metrics across the environmental, social and governance pillars, and environmental risk ratings for credit &amp; vendor exposures.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "assessments" && (
            <button className="btn" onClick={openNewEsg}>
              New ESG assessment
            </button>
          )}
          {section === "ratings" && (
            <button className="btn" onClick={openNewEnv}>
              New environmental rating
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.total_assessments.toLocaleString() : "—"}</span></div>
          <span className="l">ESG assessments</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.achieved.toLocaleString() : "—"}</span></div>
          <span className="l">Targets achieved{summary ? ` (${summary.achieved_pct}%)` : ""}</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{offTrack != null ? offTrack.toLocaleString() : "—"}</span></div>
          <span className="l">Off track</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.high_env_risk.toLocaleString() : "—"}</span></div>
          <span className="l">High env-risk entities</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, margin: "16px 0", flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button key={s.id} className={`btn${section === s.id ? "" : " secondary"}`} onClick={() => setSection(s.id)} type="button">
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {section === "assessments" && (
        <DataTable<EsgAssessment>
          columns={esgColumns}
          fetcher={fetchAssessments}
          rowKey={(a) => a.id}
          onRowClick={(a) => setOpenId(a.id)}
          activeKey={openId}
          searchPlaceholder="Search assessments by title, category, metric or owner…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No ESG assessments. Track ESG metrics and targets aligned to the SBP Green Banking Guidelines."
          refreshKey={refreshKey}
        />
      )}

      {section === "ratings" && (
        <DataTable<EnvRating>
          columns={envColumns}
          fetcher={fetchRatings}
          rowKey={(r) => r.id}
          onRowClick={(r) => openEditEnv(r)}
          searchPlaceholder="Search ratings by entity or sector…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No environmental risk ratings. Rate the environmental risk of credit and vendor exposures."
          refreshKey={refreshKey}
        />
      )}

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference || ""} ${detail.title}`.trim() : "…"}
        subtitle={detail ? `${cap(detail.pillar)}${detail.owner ? " · owner " + detail.owner : ""}${detail.period ? " · " + detail.period : ""}` : ""}
        width={720}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditEsg(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeEsg(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Metric</div><div style={{ marginTop: 4 }}><strong>{detail.metric || "—"}</strong></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Target</div><div style={{ marginTop: 4 }}><strong>{detail.target_value ? `${detail.target_value}${detail.unit ? " " + detail.unit : ""}` : "—"}</strong></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Current</div><div style={{ marginTop: 4 }}><strong>{detail.current_value ? `${detail.current_value}${detail.unit ? " " + detail.unit : ""}` : "—"}</strong></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Status</div><div style={{ marginTop: 4 }}><Badge tone={ESG_STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge></div></div>
            </div>
            {detail.sbp_green_banking_ref && (
              <p className="muted" style={{ fontSize: 13, margin: "0 0 8px" }}>SBP Green Banking ref: <strong>{detail.sbp_green_banking_ref}</strong></p>
            )}
            {detail.description && <p style={{ fontSize: 13, margin: "0 0 14px" }}>{detail.description}</p>}
            <RecordPanels model="esg_assessment" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {showEsgForm && (
        <FormModal
          title={editingEsg ? `Edit ESG assessment — ${editingEsg.reference || editingEsg.title}` : "New ESG assessment"}
          wide
          tabs={[
            { id: "general", label: "General", content: esgGeneral, required: true },
            { id: "governance", label: "Ownership & SBP", content: esgGovernance },
          ]}
          onClose={() => setShowEsgForm(false)}
          onSave={saveEsg}
          saving={savingEsg}
          error={error}
          saveLabel={editingEsg ? "Save changes" : "Create ESG assessment"}
          footerLeft={editingEsg ? (
            <button className="btn secondary sm" type="button" onClick={() => removeEsg(editingEsg)} disabled={savingEsg} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
          ) : undefined}
        />
      )}

      {showEnvForm && (
        <FormModal
          title={editingEnv ? `Edit environmental rating — ${editingEnv.reference || editingEnv.entity_name}` : "New environmental rating"}
          wide
          tabs={[{ id: "general", label: "General", content: envGeneral, required: true }]}
          onClose={() => setShowEnvForm(false)}
          onSave={saveEnv}
          saving={savingEnv}
          error={error}
          saveLabel={editingEnv ? "Save changes" : "Create rating"}
          footerLeft={editingEnv ? (
            <button className="btn secondary sm" type="button" onClick={() => removeEnv(editingEnv)} disabled={savingEnv} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
          ) : undefined}
        />
      )}
    </>
  );
}

export default function EsgPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <EsgInner />
    </Suspense>
  );
}
