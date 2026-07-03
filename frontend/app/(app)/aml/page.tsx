"use client";

import { useEffect, useState } from "react";
import {
  api,
  type ScreeningCase,
  type ScreeningSummary,
  type Sar,
  type AmlRisk,
} from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

// ------------------------------------------------------------------ enum lists
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const SUBJECT_TYPE = opts(["customer", "counterparty", "employee", "vendor"]);
const SCREENING_TYPE = opts(["sanctions", "pep", "adverse_media", "comprehensive"]);
const MATCH_STATUS = opts(["no_match", "potential_match", "confirmed_match", "false_positive"]);
const RATING = opts(["low", "medium", "high", "critical"]);
const SCREENING_STATUS = opts(["open", "under_review", "cleared", "escalated"]);
const SAR_PRIORITY = opts(["low", "medium", "high", "critical"]);
const SAR_STATUS = opts(["draft", "under_review", "filed", "closed"]);
const AML_SCOPE = opts(["customer", "product", "geography", "channel", "enterprise"]);
const REVIEW_FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);

// ------------------------------------------------------------------ tones
const SEVERITY_TONE: Record<string, Tone> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};
const MATCH_STATUS_TONE: Record<string, Tone> = {
  no_match: "low",
  potential_match: "high",
  confirmed_match: "critical",
  false_positive: "neutral",
};
const SCREENING_STATUS_TONE: Record<string, Tone> = {
  open: "medium",
  under_review: "info",
  cleared: "low",
  escalated: "critical",
};
const SAR_STATUS_TONE: Record<string, Tone> = {
  draft: "medium",
  under_review: "info",
  filed: "low",
  closed: "neutral",
};

function SeverityBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={SEVERITY_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

// ------------------------------------------------------------------ screening form state
type ScreeningForm = {
  subject_name: string;
  subject_type: string;
  screening_type: string;
  lists_checked: string;
  match_status: string;
  risk_rating: string;
  status: string;
  screened_date: string;
  reviewer: string;
  disposition: string;
  workflow_status: string;
};
const BLANK_SCREENING: ScreeningForm = {
  subject_name: "",
  subject_type: "customer",
  screening_type: "sanctions",
  lists_checked: "",
  match_status: "no_match",
  risk_rating: "low",
  status: "open",
  screened_date: "",
  reviewer: "",
  disposition: "",
  workflow_status: "draft",
};
function fromScreening(s: ScreeningCase): ScreeningForm {
  return {
    subject_name: s.subject_name,
    subject_type: s.subject_type || "customer",
    screening_type: s.screening_type || "sanctions",
    lists_checked: s.lists_checked || "",
    match_status: s.match_status || "no_match",
    risk_rating: s.risk_rating || "low",
    status: s.status || "open",
    screened_date: s.screened_date || "",
    reviewer: s.reviewer || "",
    disposition: s.disposition || "",
    workflow_status: s.workflow_status || "draft",
  };
}
function screeningPayload(f: ScreeningForm): Record<string, unknown> {
  return {
    subject_name: f.subject_name,
    subject_type: f.subject_type,
    screening_type: f.screening_type,
    lists_checked: f.lists_checked,
    match_status: f.match_status,
    risk_rating: f.risk_rating,
    status: f.status,
    screened_date: f.screened_date || null,
    reviewer: f.reviewer,
    disposition: f.disposition,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ SAR form state
type SarForm = {
  subject: string;
  analyst: string;
  priority: string;
  amount: string;
  currency: string;
  detected_date: string;
  deadline: string;
  status: string;
  activity_description: string;
  suspicion_reason: string;
  filed_date: string;
  fmu_reference: string;
  workflow_status: string;
};
const BLANK_SAR: SarForm = {
  subject: "",
  analyst: "",
  priority: "medium",
  amount: "",
  currency: "PKR",
  detected_date: "",
  deadline: "",
  status: "draft",
  activity_description: "",
  suspicion_reason: "",
  filed_date: "",
  fmu_reference: "",
  workflow_status: "draft",
};
function fromSar(s: Sar): SarForm {
  return {
    subject: s.subject,
    analyst: s.analyst || "",
    priority: s.priority || "medium",
    amount: s.amount != null ? String(s.amount) : "",
    currency: s.currency || "PKR",
    detected_date: s.detected_date || "",
    deadline: s.deadline || "",
    status: s.status || "draft",
    activity_description: s.activity_description || "",
    suspicion_reason: s.suspicion_reason || "",
    filed_date: s.filed_date || "",
    fmu_reference: s.fmu_reference || "",
    workflow_status: s.workflow_status || "draft",
  };
}
function sarPayload(f: SarForm): Record<string, unknown> {
  return {
    subject: f.subject,
    analyst: f.analyst,
    priority: f.priority,
    amount: f.amount === "" ? null : Number(f.amount),
    currency: f.currency,
    detected_date: f.detected_date || null,
    deadline: f.deadline || null,
    status: f.status,
    activity_description: f.activity_description,
    suspicion_reason: f.suspicion_reason,
    filed_date: f.filed_date || null,
    fmu_reference: f.fmu_reference,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ AML risk form state
type RiskForm = {
  title: string;
  scope: string;
  subject: string;
  inherent_risk: string;
  mitigating_controls: string;
  residual_risk: string;
  assessor: string;
  assessment_date: string;
  review_frequency: string;
  next_review_date: string;
  workflow_status: string;
};
const BLANK_RISK: RiskForm = {
  title: "",
  scope: "customer",
  subject: "",
  inherent_risk: "medium",
  mitigating_controls: "",
  residual_risk: "low",
  assessor: "",
  assessment_date: "",
  review_frequency: "annual",
  next_review_date: "",
  workflow_status: "draft",
};
function fromRisk(r: AmlRisk): RiskForm {
  return {
    title: r.title,
    scope: r.scope || "customer",
    subject: r.subject || "",
    inherent_risk: r.inherent_risk || "medium",
    mitigating_controls: r.mitigating_controls || "",
    residual_risk: r.residual_risk || "low",
    assessor: r.assessor || "",
    assessment_date: r.assessment_date || "",
    review_frequency: r.review_frequency || "annual",
    next_review_date: r.next_review_date || "",
    workflow_status: r.workflow_status || "draft",
  };
}
function riskPayload(f: RiskForm): Record<string, unknown> {
  return {
    title: f.title,
    scope: f.scope,
    subject: f.subject,
    inherent_risk: f.inherent_risk,
    mitigating_controls: f.mitigating_controls,
    residual_risk: f.residual_risk,
    assessor: f.assessor,
    assessment_date: f.assessment_date || null,
    review_frequency: f.review_frequency,
    next_review_date: f.next_review_date || null,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ sections
type SectionId = "screening" | "sars" | "risks";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "screening", label: "Screening" },
  { id: "sars", label: "STR / SAR Filings" },
  { id: "risks", label: "AML Risk Assessments" },
];

export default function AmlPage() {
  const [section, setSection] = useState<SectionId>("screening");
  const [error, setError] = useState<string | null>(null);

  const [cases, setCases] = useState<ScreeningCase[]>([]);
  const [summary, setSummary] = useState<ScreeningSummary | null>(null);
  const [sars, setSars] = useState<Sar[]>([]);
  const [risks, setRisks] = useState<AmlRisk[]>([]);

  // ---- screening dialog ----
  const [editingCase, setEditingCase] = useState<ScreeningCase | null>(null);
  const [showCaseForm, setShowCaseForm] = useState(false);
  const [savingCase, setSavingCase] = useState(false);
  const [sf, setSf] = useState<ScreeningForm>(BLANK_SCREENING);
  const setS = <K extends keyof ScreeningForm>(k: K, v: ScreeningForm[K]) => setSf((p) => ({ ...p, [k]: v }));

  // ---- SAR dialog ----
  const [editingSar, setEditingSar] = useState<Sar | null>(null);
  const [showSarForm, setShowSarForm] = useState(false);
  const [savingSar, setSavingSar] = useState(false);
  const [af, setAf] = useState<SarForm>(BLANK_SAR);
  const setA = <K extends keyof SarForm>(k: K, v: SarForm[K]) => setAf((p) => ({ ...p, [k]: v }));

  // ---- risk dialog ----
  const [editingRisk, setEditingRisk] = useState<AmlRisk | null>(null);
  const [showRiskForm, setShowRiskForm] = useState(false);
  const [savingRisk, setSavingRisk] = useState(false);
  const [rf, setRf] = useState<RiskForm>(BLANK_RISK);
  const setR = <K extends keyof RiskForm>(k: K, v: RiskForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadCases() {
    try {
      const res = await api.amlScreening();
      setCases(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load screening cases");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await api.screeningSummary());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load screening summary");
    }
  }
  async function loadSars() {
    try {
      const res = await api.amlSars();
      setSars(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load STR/SAR filings");
    }
  }
  async function loadRisks() {
    try {
      const res = await api.amlRisks();
      setRisks(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load risk assessments");
    }
  }

  useEffect(() => {
    loadCases();
    loadSummary();
    loadSars();
    loadRisks();
  }, []);

  // ------------------------------------------------------------- screening CRUD
  function openNewCase() {
    setEditingCase(null);
    setSf(BLANK_SCREENING);
    setShowCaseForm(true);
  }
  function openEditCase(c: ScreeningCase) {
    setEditingCase(c);
    setSf(fromScreening(c));
    setShowCaseForm(true);
  }
  async function saveCase() {
    setError(null);
    setSavingCase(true);
    try {
      const payload = screeningPayload(sf);
      if (editingCase) await api.updateScreening(editingCase.id, payload);
      else await api.createScreening(payload);
      setShowCaseForm(false);
      await loadCases();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save screening case");
    } finally {
      setSavingCase(false);
    }
  }
  async function removeCase(c: ScreeningCase) {
    if (!window.confirm(`Delete screening case ${c.reference || c.subject_name}?`)) return;
    setError(null);
    try {
      await api.deleteScreening(c.id);
      setShowCaseForm(false);
      await loadCases();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- SAR CRUD
  function openNewSar() {
    setEditingSar(null);
    setAf(BLANK_SAR);
    setShowSarForm(true);
  }
  function openEditSar(s: Sar) {
    setEditingSar(s);
    setAf(fromSar(s));
    setShowSarForm(true);
  }
  async function saveSar() {
    setError(null);
    setSavingSar(true);
    try {
      const payload = sarPayload(af);
      if (editingSar) await api.updateSar(editingSar.id, payload);
      else await api.createSar(payload);
      setShowSarForm(false);
      await loadSars();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save STR/SAR");
    } finally {
      setSavingSar(false);
    }
  }
  async function removeSar(s: Sar) {
    if (!window.confirm(`Delete STR/SAR ${s.reference || s.subject}?`)) return;
    setError(null);
    try {
      await api.deleteSar(s.id);
      setShowSarForm(false);
      await loadSars();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- risk CRUD
  function openNewRisk() {
    setEditingRisk(null);
    setRf(BLANK_RISK);
    setShowRiskForm(true);
  }
  function openEditRisk(r: AmlRisk) {
    setEditingRisk(r);
    setRf(fromRisk(r));
    setShowRiskForm(true);
  }
  async function saveRisk() {
    setError(null);
    setSavingRisk(true);
    try {
      const payload = riskPayload(rf);
      if (editingRisk) await api.updateAmlRisk(editingRisk.id, payload);
      else await api.createAmlRisk(payload);
      setShowRiskForm(false);
      await loadRisks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save assessment");
    } finally {
      setSavingRisk(false);
    }
  }
  async function removeRisk(r: AmlRisk) {
    if (!window.confirm(`Delete assessment ${r.reference || r.title}?`)) return;
    setError(null);
    try {
      await api.deleteAmlRisk(r.id);
      setShowRiskForm(false);
      await loadRisks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const matchCount = summary
    ? (summary.by_match_status["potential_match"] || 0) + (summary.by_match_status["confirmed_match"] || 0)
    : 0;

  // ------------------------------------------------------------- screening form
  const screeningGeneral = (
    <>
      <Field label="Subject name" required help="Name of the party being screened.">
        <TextInput value={sf.subject_name} onChange={(v) => setS("subject_name", v)} placeholder="Party name" required />
      </Field>
      <div className="field-row">
        <Field label="Subject type" help="What kind of party this is.">
          <Select value={sf.subject_type} onChange={(v) => setS("subject_type", v)} options={SUBJECT_TYPE} />
        </Field>
        <Field label="Screening type" help="Which check was run.">
          <Select value={sf.screening_type} onChange={(v) => setS("screening_type", v)} options={SCREENING_TYPE} />
        </Field>
      </div>
      <Field label="Lists checked" help='Watchlists screened, e.g. "UN, OFAC, EU".'>
        <TextInput value={sf.lists_checked} onChange={(v) => setS("lists_checked", v)} placeholder="UN, OFAC, EU" />
      </Field>
      <div className="field-row">
        <Field label="Match status" help="Outcome of the screening.">
          <Select value={sf.match_status} onChange={(v) => setS("match_status", v)} options={MATCH_STATUS} />
        </Field>
        <Field label="Risk rating">
          <Select value={sf.risk_rating} onChange={(v) => setS("risk_rating", v)} options={RATING} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status" help="Case handling status.">
          <Select value={sf.status} onChange={(v) => setS("status", v)} options={SCREENING_STATUS} />
        </Field>
        <Field label="Screened date">
          <TextInput type="date" value={sf.screened_date} onChange={(v) => setS("screened_date", v)} />
        </Field>
      </div>
      <Field label="Reviewer" help="Analyst who reviewed the hit.">
        <TextInput value={sf.reviewer} onChange={(v) => setS("reviewer", v)} placeholder="Name" />
      </Field>
      <Field label="Disposition" help="How the potential match was resolved.">
        <TextArea value={sf.disposition} onChange={(v) => setS("disposition", v)} rows={3} placeholder="Resolution and rationale." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this screening record.">
        <Select value={sf.workflow_status} onChange={(v) => setS("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- SAR form tabs
  const sarGeneral = (
    <>
      <Field label="Subject" required help="Party the suspicious activity relates to.">
        <TextInput value={af.subject} onChange={(v) => setA("subject", v)} placeholder="Subject name" required />
      </Field>
      <div className="field-row">
        <Field label="Analyst">
          <TextInput value={af.analyst} onChange={(v) => setA("analyst", v)} placeholder="Name" />
        </Field>
        <Field label="Priority">
          <Select value={af.priority} onChange={(v) => setA("priority", v)} options={SAR_PRIORITY} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Amount" help="Value of the suspicious activity.">
          <TextInput type="number" value={af.amount} onChange={(v) => setA("amount", v)} placeholder="0" />
        </Field>
        <Field label="Currency">
          <TextInput value={af.currency} onChange={(v) => setA("currency", v)} placeholder="PKR" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Detected date" help="When the activity was detected.">
          <TextInput type="date" value={af.detected_date} onChange={(v) => setA("detected_date", v)} />
        </Field>
        <Field label="Deadline" help="FMU filing deadline — auto-computed as 7 days after the detection date when left blank.">
          <TextInput type="date" value={af.deadline} onChange={(v) => setA("deadline", v)} />
        </Field>
      </div>
      <Field label="Status">
        <Select value={af.status} onChange={(v) => setA("status", v)} options={SAR_STATUS} />
      </Field>
    </>
  );
  const sarDetails = (
    <>
      <Field label="Activity description" help="What the suspicious activity involved.">
        <TextArea value={af.activity_description} onChange={(v) => setA("activity_description", v)} rows={3} placeholder="Describe the transactions or behaviour." />
      </Field>
      <Field label="Suspicion reason" help="Grounds for suspicion.">
        <TextArea value={af.suspicion_reason} onChange={(v) => setA("suspicion_reason", v)} rows={3} placeholder="Why this is being reported." />
      </Field>
      <div className="field-row">
        <Field label="Filed date" help="Date the report was filed with the FMU.">
          <TextInput type="date" value={af.filed_date} onChange={(v) => setA("filed_date", v)} />
        </Field>
        <Field label="FMU reference" help="Reference issued by the FMU on filing.">
          <TextInput value={af.fmu_reference} onChange={(v) => setA("fmu_reference", v)} placeholder="FMU-…" />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this filing record.">
        <Select value={af.workflow_status} onChange={(v) => setA("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- risk form
  const riskGeneral = (
    <>
      <Field label="Title" required help="For example: FY26 enterprise ML/TF risk assessment.">
        <TextInput value={rf.title} onChange={(v) => setR("title", v)} placeholder="Assessment title" required />
      </Field>
      <div className="field-row">
        <Field label="Scope" help="What the assessment covers.">
          <Select value={rf.scope} onChange={(v) => setR("scope", v)} options={AML_SCOPE} />
        </Field>
        <Field label="Subject" help="The specific customer, product, geography or channel assessed.">
          <TextInput value={rf.subject} onChange={(v) => setR("subject", v)} placeholder="Subject" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Inherent risk" help="Risk before mitigating controls.">
          <Select value={rf.inherent_risk} onChange={(v) => setR("inherent_risk", v)} options={RATING} />
        </Field>
        <Field label="Residual risk" help="Risk after mitigating controls.">
          <Select value={rf.residual_risk} onChange={(v) => setR("residual_risk", v)} options={RATING} />
        </Field>
      </div>
      <Field label="Mitigating controls" help="Controls that reduce the inherent risk.">
        <TextArea value={rf.mitigating_controls} onChange={(v) => setR("mitigating_controls", v)} rows={3} placeholder="Applied AML controls." />
      </Field>
      <div className="field-row">
        <Field label="Assessor">
          <TextInput value={rf.assessor} onChange={(v) => setR("assessor", v)} placeholder="Name" />
        </Field>
        <Field label="Assessment date">
          <TextInput type="date" value={rf.assessment_date} onChange={(v) => setR("assessment_date", v)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Review frequency" help="How often the assessment is refreshed.">
          <Select value={rf.review_frequency} onChange={(v) => setR("review_frequency", v)} options={REVIEW_FREQ} />
        </Field>
        <Field label="Next review date" help="Drives the overdue flag.">
          <TextInput type="date" value={rf.next_review_date} onChange={(v) => setR("next_review_date", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this assessment record.">
        <Select value={rf.workflow_status} onChange={(v) => setR("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>AML / CFT</h1>
          <p>Sanctions &amp; PEP screening, suspicious transaction / activity reporting to the FMU, and money-laundering risk assessments.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "screening" && (
            <button className="btn" onClick={openNewCase}>
              <IconPlus width={16} height={16} /> New screening case
            </button>
          )}
          {section === "sars" && (
            <button className="btn" onClick={openNewSar}>
              <IconPlus width={16} height={16} /> New STR/SAR
            </button>
          )}
          {section === "risks" && (
            <button className="btn" onClick={openNewRisk}>
              <IconPlus width={16} height={16} /> New assessment
            </button>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
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

      {/* ============================================= SCREENING */}
      {section === "screening" && (
        <>
          <div className="grid stat-grid">
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{summary ? summary.total.toLocaleString() : "—"}</span>
              </div>
              <span className="l">Screening cases</span>
            </div>
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{summary ? summary.open_cases.toLocaleString() : "—"}</span>
              </div>
              <span className="l">Open cases</span>
            </div>
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{summary ? summary.escalated.toLocaleString() : "—"}</span>
              </div>
              <span className="l">Escalated</span>
            </div>
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{summary ? matchCount.toLocaleString() : "—"}</span>
              </div>
              <span className="l">Potential / confirmed matches</span>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Sanctions &amp; PEP Screening</h3>
              <span className="sub">{cases.length} total · click a row to edit</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Subject</th>
                    <th>Type</th>
                    <th>Screening</th>
                    <th>Match</th>
                    <th>Risk</th>
                    <th>Status</th>
                    <th>Screened</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((c) => (
                    <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => openEditCase(c)}>
                      <td className="ref">{c.reference || "—"}</td>
                      <td className="cell-title">{c.subject_name}</td>
                      <td className="muted">{cap(c.subject_type)}</td>
                      <td><Badge tone="info">{cap(c.screening_type)}</Badge></td>
                      <td><Badge tone={MATCH_STATUS_TONE[c.match_status] || "neutral"}>{cap(c.match_status)}</Badge></td>
                      <td><SeverityBadge value={c.risk_rating} /></td>
                      <td><Badge tone={SCREENING_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge></td>
                      <td className="muted">{c.screened_date || "—"}</td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => removeCase(c)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {cases.length === 0 && (
                    <tr>
                      <td colSpan={9}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No screening cases</h3>
                          <p>Record sanctions and PEP screening results against watchlists.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ============================================= STR / SAR FILINGS */}
      {section === "sars" && (
        <div className="card">
          <div className="card-head">
            <h3>STR / SAR Filings</h3>
            <span className="sub">{sars.length} total · click a row to edit</span>
          </div>
          <p className="muted" style={{ padding: "0 16px 12px", fontSize: 13 }}>
            The FMU filing deadline is auto-computed as 7 days after the detection date when left blank.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Subject</th>
                  <th>Priority</th>
                  <th>Amount</th>
                  <th>Detected</th>
                  <th>Deadline</th>
                  <th>Status</th>
                  <th>FMU ref</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {sars.map((s) => (
                  <tr key={s.id} style={{ cursor: "pointer" }} onClick={() => openEditSar(s)}>
                    <td className="ref">{s.reference || "—"}</td>
                    <td className="cell-title">{s.subject}</td>
                    <td><SeverityBadge value={s.priority} /></td>
                    <td className="muted">{num(s.amount)} {s.currency}</td>
                    <td className="muted">{s.detected_date || "—"}</td>
                    <td>
                      {s.is_overdue ? (
                        <Badge tone="critical">Overdue</Badge>
                      ) : (
                        <span className="muted">{s.deadline || "—"}</span>
                      )}
                    </td>
                    <td><Badge tone={SAR_STATUS_TONE[s.status] || "neutral"}>{cap(s.status)}</Badge></td>
                    <td className="muted">{s.fmu_reference || "—"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeSar(s)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {sars.length === 0 && (
                  <tr>
                    <td colSpan={9}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No STR/SAR filings</h3>
                        <p>Draft suspicious transaction / activity reports and track their FMU filing deadlines.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= AML RISK ASSESSMENTS */}
      {section === "risks" && (
        <div className="card">
          <div className="card-head">
            <h3>AML Risk Assessments</h3>
            <span className="sub">{risks.length} total · click a row to edit</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Title</th>
                  <th>Scope</th>
                  <th>Subject</th>
                  <th>Inherent</th>
                  <th>Residual</th>
                  <th>Next review</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {risks.map((r) => (
                  <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openEditRisk(r)}>
                    <td className="ref">{r.reference || "—"}</td>
                    <td className="cell-title">{r.title}</td>
                    <td><Badge tone="info">{cap(r.scope)}</Badge></td>
                    <td className="muted">{r.subject || "—"}</td>
                    <td><SeverityBadge value={r.inherent_risk} /></td>
                    <td><SeverityBadge value={r.residual_risk} /></td>
                    <td>
                      {r.is_review_overdue ? (
                        <Badge tone="high">Overdue</Badge>
                      ) : (
                        <span className="muted">{r.next_review_date || "—"}</span>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeRisk(r)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {risks.length === 0 && (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No risk assessments</h3>
                        <p>Assess money-laundering risk across customers, products, geographies and channels.</p>
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
      {showCaseForm && (
        <FormModal
          title={editingCase ? `Edit screening case — ${editingCase.reference || editingCase.subject_name}` : "New screening case"}
          wide
          tabs={[{ id: "general", label: "General", content: screeningGeneral, required: true }]}
          onClose={() => setShowCaseForm(false)}
          onSave={saveCase}
          saving={savingCase}
          error={error}
          saveLabel={editingCase ? "Save changes" : "Create case"}
          footerLeft={
            editingCase ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeCase(editingCase)}
                disabled={savingCase}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showSarForm && (
        <FormModal
          title={editingSar ? `Edit STR/SAR — ${editingSar.reference || editingSar.subject}` : "New STR/SAR"}
          wide
          tabs={[
            { id: "general", label: "General", content: sarGeneral, required: true },
            { id: "details", label: "Details", content: sarDetails },
          ]}
          onClose={() => setShowSarForm(false)}
          onSave={saveSar}
          saving={savingSar}
          error={error}
          saveLabel={editingSar ? "Save changes" : "Create STR/SAR"}
          footerLeft={
            editingSar ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeSar(editingSar)}
                disabled={savingSar}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showRiskForm && (
        <FormModal
          title={editingRisk ? `Edit assessment — ${editingRisk.reference || editingRisk.title}` : "New assessment"}
          wide
          tabs={[{ id: "general", label: "General", content: riskGeneral, required: true }]}
          onClose={() => setShowRiskForm(false)}
          onSave={saveRisk}
          saving={savingRisk}
          error={error}
          saveLabel={editingRisk ? "Save changes" : "Create assessment"}
          footerLeft={
            editingRisk ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeRisk(editingRisk)}
                disabled={savingRisk}
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
