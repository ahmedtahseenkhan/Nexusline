"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

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
interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
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
const PILLAR_TONE: Record<string, Tone> = {
  environmental: "low",
  social: "info",
  governance: "medium",
};
const ESG_STATUS_TONE: Record<string, Tone> = {
  not_started: "neutral",
  in_progress: "info",
  achieved: "low",
  off_track: "critical",
};
const ENV_RISK_TONE: Record<string, Tone> = {
  high: "critical",
  medium: "medium",
  low: "low",
};

// ------------------------------------------------------------------ form state
type EsgForm = {
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
};
const BLANK_ESG: EsgForm = {
  title: "",
  description: "",
  pillar: "environmental",
  category: "",
  metric: "",
  target_value: "",
  current_value: "",
  unit: "",
  status: "not_started",
  owner: "",
  period: "",
  sbp_green_banking_ref: "",
  workflow_status: "draft",
};
function fromEsg(a: EsgAssessment): EsgForm {
  return {
    title: a.title,
    description: a.description || "",
    pillar: a.pillar || "environmental",
    category: a.category || "",
    metric: a.metric || "",
    target_value: a.target_value || "",
    current_value: a.current_value || "",
    unit: a.unit || "",
    status: a.status || "not_started",
    owner: a.owner || "",
    period: a.period || "",
    sbp_green_banking_ref: a.sbp_green_banking_ref || "",
    workflow_status: a.workflow_status || "draft",
  };
}

type EnvForm = {
  entity_name: string;
  sector: string;
  risk_category: string;
  assessment: string;
  mitigation: string;
  rating_date: string;
  assessor: string;
};
const BLANK_ENV: EnvForm = {
  entity_name: "",
  sector: "",
  risk_category: "low",
  assessment: "",
  mitigation: "",
  rating_date: "",
  assessor: "",
};
function fromEnv(r: EnvRating): EnvForm {
  return {
    entity_name: r.entity_name,
    sector: r.sector || "",
    risk_category: r.risk_category || "low",
    assessment: r.assessment || "",
    mitigation: r.mitigation || "",
    rating_date: r.rating_date || "",
    assessor: r.assessor || "",
  };
}

type SectionId = "assessments" | "ratings";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "assessments", label: "ESG Assessments" },
  { id: "ratings", label: "Environmental Risk Ratings" },
];

export default function EsgPage() {
  const [section, setSection] = useState<SectionId>("assessments");
  const [error, setError] = useState<string | null>(null);

  const [assessments, setAssessments] = useState<EsgAssessment[]>([]);
  const [ratings, setRatings] = useState<EnvRating[]>([]);
  const [summary, setSummary] = useState<EsgSummary | null>(null);

  // ---- ESG dialog + expanded detail ----
  const [editingEsg, setEditingEsg] = useState<EsgAssessment | null>(null);
  const [showEsgForm, setShowEsgForm] = useState(false);
  const [savingEsg, setSavingEsg] = useState(false);
  const [ef, setEf] = useState<EsgForm>(BLANK_ESG);
  const setE = <K extends keyof EsgForm>(k: K, v: EsgForm[K]) => setEf((p) => ({ ...p, [k]: v }));
  const [openEsg, setOpenEsg] = useState<EsgAssessment | null>(null);

  // ---- Env rating dialog ----
  const [editingEnv, setEditingEnv] = useState<EnvRating | null>(null);
  const [showEnvForm, setShowEnvForm] = useState(false);
  const [savingEnv, setSavingEnv] = useState(false);
  const [rf, setRf] = useState<EnvForm>(BLANK_ENV);
  const setR = <K extends keyof EnvForm>(k: K, v: EnvForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadAssessments(keepOpen?: string) {
    try {
      const res = await apiCall<Page<EsgAssessment>>("GET", "/esg-assessments?limit=200");
      setAssessments(res.items);
      if (keepOpen) setOpenEsg(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ESG assessments");
    }
  }
  async function loadRatings() {
    try {
      const res = await apiCall<Page<EnvRating>>("GET", "/environmental-risk-ratings?limit=200");
      setRatings(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load environmental risk ratings");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<EsgSummary>("GET", "/esg-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ESG summary");
    }
  }

  useEffect(() => {
    loadAssessments();
    loadRatings();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- ESG CRUD
  function openNewEsg() {
    setEditingEsg(null);
    setEf(BLANK_ESG);
    setShowEsgForm(true);
  }
  function openEditEsg(a: EsgAssessment) {
    setEditingEsg(a);
    setEf(fromEsg(a));
    setShowEsgForm(true);
  }
  async function saveEsg() {
    setError(null);
    setSavingEsg(true);
    try {
      if (editingEsg) await apiCall("PATCH", `/esg-assessments/${editingEsg.id}`, ef);
      else await apiCall("POST", "/esg-assessments", ef);
      setShowEsgForm(false);
      await loadAssessments(openEsg?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save ESG assessment");
    } finally {
      setSavingEsg(false);
    }
  }
  async function removeEsg(a: EsgAssessment) {
    if (!window.confirm(`Delete ESG assessment ${a.reference || a.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/esg-assessments/${a.id}`);
      setShowEsgForm(false);
      if (openEsg?.id === a.id) setOpenEsg(null);
      await loadAssessments();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleEsg(a: EsgAssessment) {
    setOpenEsg(openEsg?.id === a.id ? null : a);
  }

  // ------------------------------------------------------------- Env rating CRUD
  function openNewEnv() {
    setEditingEnv(null);
    setRf(BLANK_ENV);
    setShowEnvForm(true);
  }
  function openEditEnv(r: EnvRating) {
    setEditingEnv(r);
    setRf(fromEnv(r));
    setShowEnvForm(true);
  }
  async function saveEnv() {
    setError(null);
    setSavingEnv(true);
    try {
      const payload = { ...rf, rating_date: rf.rating_date || null };
      if (editingEnv) await apiCall("PATCH", `/environmental-risk-ratings/${editingEnv.id}`, payload);
      else await apiCall("POST", "/environmental-risk-ratings", payload);
      setShowEnvForm(false);
      await loadRatings();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save environmental risk rating");
    } finally {
      setSavingEnv(false);
    }
  }
  async function removeEnv(r: EnvRating) {
    if (!window.confirm(`Delete environmental risk rating ${r.reference || r.entity_name}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/environmental-risk-ratings/${r.id}`);
      setShowEnvForm(false);
      await loadRatings();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

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

  // ------------------------------------------------------------- Env form tabs
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
              <IconPlus width={16} height={16} /> New ESG assessment
            </button>
          )}
          {section === "ratings" && (
            <button className="btn" onClick={openNewEnv}>
              <IconPlus width={16} height={16} /> New environmental rating
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.total_assessments.toLocaleString() : "—"}</span>
          </div>
          <span className="l">ESG assessments</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.achieved.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Targets achieved{summary ? ` (${summary.achieved_pct}%)` : ""}</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{offTrack != null ? offTrack.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Off track</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.high_env_risk.toLocaleString() : "—"}</span>
          </div>
          <span className="l">High env-risk entities</span>
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

      {/* ============================================= ESG ASSESSMENTS */}
      {section === "assessments" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>ESG Assessments</h3>
              <span className="sub">{assessments.length} total · click a row to expand</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Title</th>
                    <th>Pillar</th>
                    <th>Category</th>
                    <th>Target</th>
                    <th>Current</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {assessments.map((a) => (
                    <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => toggleEsg(a)}>
                      <td className="ref">{a.reference || "—"}</td>
                      <td className="cell-title">{a.title}</td>
                      <td><Badge tone={PILLAR_TONE[a.pillar] || "neutral"}>{cap(a.pillar)}</Badge></td>
                      <td className="muted">{a.category || "—"}</td>
                      <td className="muted">{a.target_value ? `${a.target_value}${a.unit ? " " + a.unit : ""}` : "—"}</td>
                      <td className="muted">{a.current_value ? `${a.current_value}${a.unit ? " " + a.unit : ""}` : "—"}</td>
                      <td><Badge tone={ESG_STATUS_TONE[a.status] || "neutral"}>{cap(a.status)}</Badge></td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleEsg(a)}>
                            {openEsg?.id === a.id ? "Hide" : "Open"}
                          </button>
                          <button className="btn secondary sm" onClick={() => openEditEsg(a)}>Edit</button>
                          <button className="btn secondary sm" onClick={() => removeEsg(a)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {assessments.length === 0 && (
                    <tr>
                      <td colSpan={8}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No ESG assessments</h3>
                          <p>Track ESG metrics and targets aligned to the SBP Green Banking Guidelines.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openEsg && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openEsg.reference} — {openEsg.title}</h3>
                    <span className="sub">
                      {cap(openEsg.pillar)} · {openEsg.progress_note}
                      {openEsg.owner ? " · owner " + openEsg.owner : ""}
                      {openEsg.period ? " · " + openEsg.period : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button className="btn secondary sm" onClick={() => openEditEsg(openEsg)}>Edit</button>
                    <button className="btn secondary sm" onClick={() => removeEsg(openEsg)}>Delete</button>
                  </div>
                </div>

                <div className="card-pad">
                  <div className="field-row" style={{ marginBottom: 12 }}>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Metric</div>
                      <strong>{openEsg.metric || "—"}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Target</div>
                      <strong>{openEsg.target_value ? `${openEsg.target_value}${openEsg.unit ? " " + openEsg.unit : ""}` : "—"}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Current</div>
                      <strong>{openEsg.current_value ? `${openEsg.current_value}${openEsg.unit ? " " + openEsg.unit : ""}` : "—"}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Status</div>
                      <Badge tone={ESG_STATUS_TONE[openEsg.status] || "neutral"}>{cap(openEsg.status)}</Badge>
                    </div>
                  </div>
                  {openEsg.sbp_green_banking_ref && (
                    <p className="muted" style={{ fontSize: 13, margin: "0 0 8px" }}>
                      SBP Green Banking ref: <strong>{openEsg.sbp_green_banking_ref}</strong>
                    </p>
                  )}
                  {openEsg.description && (
                    <p style={{ fontSize: 13, margin: 0 }}>{openEsg.description}</p>
                  )}
                </div>
              </div>

              <RecordPanels model="esg_assessment" entityId={openEsg.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= ENV RISK RATINGS */}
      {section === "ratings" && (
        <div className="card">
          <div className="card-head">
            <h3>Environmental Risk Ratings</h3>
            <span className="sub">{ratings.length} total · borrower / client / vendor E-risk register · click a row to edit</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Entity</th>
                  <th>Sector</th>
                  <th>Risk category</th>
                  <th>Assessor</th>
                  <th>Rating date</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {ratings.map((r) => (
                  <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openEditEnv(r)}>
                    <td className="ref">{r.reference || "—"}</td>
                    <td className="cell-title">{r.entity_name}</td>
                    <td className="muted">{r.sector || "—"}</td>
                    <td><Badge tone={ENV_RISK_TONE[r.risk_category] || "neutral"}>{cap(r.risk_category)}</Badge></td>
                    <td className="muted">{r.assessor || "—"}</td>
                    <td className="muted">{r.rating_date || "—"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeEnv(r)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {ratings.length === 0 && (
                  <tr>
                    <td colSpan={7}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No environmental risk ratings</h3>
                        <p>Rate the environmental risk of credit and vendor exposures for green-banking due diligence.</p>
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
          footerLeft={
            editingEsg ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeEsg(editingEsg)}
                disabled={savingEsg}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
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
          footerLeft={
            editingEnv ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeEnv(editingEnv)}
                disabled={savingEnv}
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
