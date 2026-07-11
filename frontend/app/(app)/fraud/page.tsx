"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ local types
interface FraudRisk {
  id: string;
  reference: string;
  title: string;
  description: string;
  scheme: string;
  channel: string;
  business_line: string;
  inherent_likelihood: number;
  inherent_impact: number;
  control_description: string;
  control_effectiveness: string;
  residual_likelihood: number;
  residual_impact: number;
  red_flags: string;
  owner: string;
  status: string;
  workflow_status: string;
  inherent_score: number;
  residual_score: number;
  created_at: string;
}
interface FraudCase {
  id: string;
  reference: string;
  title: string;
  description: string;
  scheme: string;
  channel: string;
  status: string;
  reported_date: string | null;
  discovery_date: string | null;
  incident_date: string | null;
  amount_involved: number;
  amount_recovered: number;
  currency: string;
  perpetrator_type: string;
  customer_impacted: boolean;
  customers_affected: number;
  reported_to_regulator: boolean;
  regulator_ref: string;
  investigator: string;
  root_cause: string;
  resolution: string;
  workflow_status: string;
  net_loss: number;
  created_at: string;
}
interface FraudControlCheck {
  id: string;
  reference: string;
  requirement: string;
  sbp_reference: string;
  category: string;
  implemented: boolean;
  status: string;
  owner: string;
  evidence_note: string;
  target_date: string | null;
  created_at: string;
}
interface FraudSummary {
  cases_by_status: Record<string, number>;
  open_cases: number;
  loss_by_scheme: { scheme: string; count: number; gross_loss: number; net_loss: number }[];
  total_gross_loss: number;
  total_net_loss: number;
  checklist_total: number;
  checklist_implemented: number;
  checklist_pct: number;
  risks_by_band: Record<string, number>;
  high_residual_risks: number;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());
const pkr = (n: number | null | undefined) => (n == null ? "—" : "PKR " + Number(n).toLocaleString());
const band = (score: number) => (score >= 15 ? "high" : score >= 8 ? "medium" : "low");

// ------------------------------------------------------------------ enum lists
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const SCORES = opts(["1", "2", "3", "4", "5"]);
const CONTROL_EFF = opts(["not_assessed", "ineffective", "partially_effective", "effective"]);
const FRAUD_SCHEME = opts([
  "asset_misappropriation",
  "corruption",
  "financial_statement_fraud",
  "cyber_enabled",
  "identity_theft",
  "card_fraud",
  "digital_channel_fraud",
  "insider_fraud",
  "external_fraud",
  "cheque_fraud",
  "other",
]);
const FRAUD_CHANNEL = opts([
  "branch",
  "atm",
  "internet_banking",
  "mobile_app",
  "cards",
  "wire_swift",
  "call_center",
  "agent_network",
  "other",
]);
const RISK_STATUS = opts(["open", "mitigating", "monitored", "closed"]);
const CASE_STATUS = opts(["reported", "investigating", "confirmed", "recovered", "closed", "referred_to_authorities"]);
const PERPETRATOR = opts(["internal", "external", "collusion", "unknown"]);
const CONTROL_CATEGORY = opts([
  "behavioral_monitoring",
  "transaction_limits",
  "customer_authentication",
  "real_time_alerting",
  "complaint_handling",
  "fraud_detection_system",
  "staff_training",
]);
const CONTROL_STATUS = opts(["not_implemented", "in_progress", "implemented"]);

// ------------------------------------------------------------------ tones
const RISK_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  mitigating: "info",
  monitored: "medium",
  closed: "neutral",
};
const CASE_STATUS_TONE: Record<string, Tone> = {
  reported: "high",
  investigating: "info",
  confirmed: "critical",
  recovered: "low",
  closed: "neutral",
  referred_to_authorities: "medium",
};
const CONTROL_STATUS_TONE: Record<string, Tone> = {
  not_implemented: "critical",
  in_progress: "medium",
  implemented: "low",
};
const BAND_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "critical" };
const EFF_TONE: Record<string, Tone> = {
  effective: "low",
  partially_effective: "medium",
  ineffective: "critical",
  not_assessed: "neutral",
};

function EffBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={EFF_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}
function BandBadge({ score }: { score: number }) {
  const b = band(score);
  return <Badge tone={BAND_TONE[b]}>{cap(b)} ({score})</Badge>;
}

// ------------------------------------------------------------------ fraud-risk form state
type RiskForm = {
  title: string;
  scheme: string;
  channel: string;
  business_line: string;
  description: string;
  inherent_likelihood: string;
  inherent_impact: string;
  control_description: string;
  control_effectiveness: string;
  residual_likelihood: string;
  residual_impact: string;
  red_flags: string;
  owner: string;
  status: string;
  workflow_status: string;
};
const BLANK_RISK: RiskForm = {
  title: "",
  scheme: "asset_misappropriation",
  channel: "branch",
  business_line: "",
  description: "",
  inherent_likelihood: "3",
  inherent_impact: "3",
  control_description: "",
  control_effectiveness: "not_assessed",
  residual_likelihood: "2",
  residual_impact: "2",
  red_flags: "",
  owner: "",
  status: "open",
  workflow_status: "draft",
};
function fromRisk(r: FraudRisk): RiskForm {
  return {
    title: r.title,
    scheme: r.scheme || "asset_misappropriation",
    channel: r.channel || "branch",
    business_line: r.business_line || "",
    description: r.description || "",
    inherent_likelihood: String(r.inherent_likelihood ?? 1),
    inherent_impact: String(r.inherent_impact ?? 1),
    control_description: r.control_description || "",
    control_effectiveness: r.control_effectiveness || "not_assessed",
    residual_likelihood: String(r.residual_likelihood ?? 1),
    residual_impact: String(r.residual_impact ?? 1),
    red_flags: r.red_flags || "",
    owner: r.owner || "",
    status: r.status || "open",
    workflow_status: r.workflow_status || "draft",
  };
}
function riskPayload(f: RiskForm): Record<string, unknown> {
  return {
    title: f.title,
    scheme: f.scheme,
    channel: f.channel,
    business_line: f.business_line,
    description: f.description,
    inherent_likelihood: Number(f.inherent_likelihood) || 1,
    inherent_impact: Number(f.inherent_impact) || 1,
    control_description: f.control_description,
    control_effectiveness: f.control_effectiveness,
    residual_likelihood: Number(f.residual_likelihood) || 1,
    residual_impact: Number(f.residual_impact) || 1,
    red_flags: f.red_flags,
    owner: f.owner,
    status: f.status,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ fraud-case form state
type CaseForm = {
  title: string;
  scheme: string;
  channel: string;
  status: string;
  description: string;
  incident_date: string;
  discovery_date: string;
  reported_date: string;
  amount_involved: string;
  amount_recovered: string;
  currency: string;
  perpetrator_type: string;
  customer_impacted: boolean;
  customers_affected: string;
  reported_to_regulator: boolean;
  regulator_ref: string;
  investigator: string;
  root_cause: string;
  resolution: string;
  workflow_status: string;
};
const BLANK_CASE: CaseForm = {
  title: "",
  scheme: "digital_channel_fraud",
  channel: "internet_banking",
  status: "reported",
  description: "",
  incident_date: "",
  discovery_date: "",
  reported_date: "",
  amount_involved: "",
  amount_recovered: "",
  currency: "PKR",
  perpetrator_type: "unknown",
  customer_impacted: false,
  customers_affected: "",
  reported_to_regulator: false,
  regulator_ref: "",
  investigator: "",
  root_cause: "",
  resolution: "",
  workflow_status: "draft",
};
function fromCase(c: FraudCase): CaseForm {
  return {
    title: c.title,
    scheme: c.scheme || "digital_channel_fraud",
    channel: c.channel || "internet_banking",
    status: c.status || "reported",
    description: c.description || "",
    incident_date: c.incident_date || "",
    discovery_date: c.discovery_date || "",
    reported_date: c.reported_date || "",
    amount_involved: c.amount_involved != null ? String(c.amount_involved) : "",
    amount_recovered: c.amount_recovered != null ? String(c.amount_recovered) : "",
    currency: c.currency || "PKR",
    perpetrator_type: c.perpetrator_type || "unknown",
    customer_impacted: !!c.customer_impacted,
    customers_affected: c.customers_affected != null ? String(c.customers_affected) : "",
    reported_to_regulator: !!c.reported_to_regulator,
    regulator_ref: c.regulator_ref || "",
    investigator: c.investigator || "",
    root_cause: c.root_cause || "",
    resolution: c.resolution || "",
    workflow_status: c.workflow_status || "draft",
  };
}
function casePayload(f: CaseForm): Record<string, unknown> {
  return {
    title: f.title,
    scheme: f.scheme,
    channel: f.channel,
    status: f.status,
    description: f.description,
    incident_date: f.incident_date || null,
    discovery_date: f.discovery_date || null,
    reported_date: f.reported_date || null,
    amount_involved: f.amount_involved === "" ? 0 : Number(f.amount_involved),
    amount_recovered: f.amount_recovered === "" ? 0 : Number(f.amount_recovered),
    currency: f.currency,
    perpetrator_type: f.perpetrator_type,
    customer_impacted: f.customer_impacted,
    customers_affected: f.customers_affected === "" ? 0 : Number(f.customers_affected),
    reported_to_regulator: f.reported_to_regulator,
    regulator_ref: f.regulator_ref,
    investigator: f.investigator,
    root_cause: f.root_cause,
    resolution: f.resolution,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ checklist form state
type CheckForm = {
  requirement: string;
  sbp_reference: string;
  category: string;
  status: string;
  implemented: boolean;
  owner: string;
  evidence_note: string;
  target_date: string;
};
const BLANK_CHECK: CheckForm = {
  requirement: "",
  sbp_reference: "",
  category: "behavioral_monitoring",
  status: "not_implemented",
  implemented: false,
  owner: "",
  evidence_note: "",
  target_date: "",
};
function fromCheck(k: FraudControlCheck): CheckForm {
  return {
    requirement: k.requirement,
    sbp_reference: k.sbp_reference || "",
    category: k.category || "behavioral_monitoring",
    status: k.status || "not_implemented",
    implemented: !!k.implemented,
    owner: k.owner || "",
    evidence_note: k.evidence_note || "",
    target_date: k.target_date || "",
  };
}
function checkPayload(f: CheckForm): Record<string, unknown> {
  return {
    requirement: f.requirement,
    sbp_reference: f.sbp_reference,
    category: f.category,
    status: f.status,
    implemented: f.implemented,
    owner: f.owner,
    evidence_note: f.evidence_note,
    target_date: f.target_date || null,
  };
}

// ------------------------------------------------------------------ sections
type SectionId = "risks" | "cases" | "checklist";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "risks", label: "Fraud Risk Register" },
  { id: "cases", label: "Fraud Cases" },
  { id: "checklist", label: "SBP Control Checklist" },
];

function FraudInner() {
  const [section, setSection] = useState<SectionId>("risks");
  const [error, setError] = useState<string | null>(null);

  const [summary, setSummary] = useState<FraudSummary | null>(null);

  const [riskKey, setRiskKey] = useState(0);
  const [caseKey, setCaseKey] = useState(0);
  const [checkKey, setCheckKey] = useState(0);
  const reloadRisks = useCallback(() => setRiskKey((k) => k + 1), []);
  const reloadCases = useCallback(() => setCaseKey((k) => k + 1), []);
  const reloadChecks = useCallback(() => setCheckKey((k) => k + 1), []);

  const fetchRisks = useCallback((qs: string) => apiCall<PagedList<FraudRisk>>("GET", `/fraud-risks?${qs}`), []);
  const fetchCases = useCallback((qs: string) => apiCall<PagedList<FraudCase>>("GET", `/fraud-cases?${qs}`), []);
  const fetchChecks = useCallback((qs: string) => apiCall<PagedList<FraudControlCheck>>("GET", `/fraud-control-checks?${qs}`), []);

  const loadSummary = useCallback(() => {
    apiCall<FraudSummary>("GET", "/fraud-summary").then(setSummary).catch((e) => setError(e instanceof Error ? e.message : "Failed to load fraud summary"));
  }, []);
  useEffect(() => { loadSummary(); }, [loadSummary]);

  // ---- risk dialog ----
  const [editingRisk, setEditingRisk] = useState<FraudRisk | null>(null);
  const [showRiskForm, setShowRiskForm] = useState(false);
  const [savingRisk, setSavingRisk] = useState(false);
  const [rf, setRf] = useState<RiskForm>(BLANK_RISK);
  const setR = <K extends keyof RiskForm>(k: K, v: RiskForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  // ---- case dialog ----
  const [editingCase, setEditingCase] = useState<FraudCase | null>(null);
  const [showCaseForm, setShowCaseForm] = useState(false);
  const [savingCase, setSavingCase] = useState(false);
  const [cf, setCf] = useState<CaseForm>(BLANK_CASE);
  const setC = <K extends keyof CaseForm>(k: K, v: CaseForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ---- checklist dialog ----
  const [editingCheck, setEditingCheck] = useState<FraudControlCheck | null>(null);
  const [showCheckForm, setShowCheckForm] = useState(false);
  const [savingCheck, setSavingCheck] = useState(false);
  const [kf, setKf] = useState<CheckForm>(BLANK_CHECK);
  const setK = <K extends keyof CheckForm>(k: K, v: CheckForm[K]) => setKf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- risk CRUD
  function openNewRisk() {
    setEditingRisk(null);
    setRf(BLANK_RISK);
    setShowRiskForm(true);
  }
  function openEditRisk(r: FraudRisk) {
    setEditingRisk(r);
    setRf(fromRisk(r));
    setShowRiskForm(true);
  }
  async function saveRisk() {
    setError(null);
    setSavingRisk(true);
    try {
      const payload = riskPayload(rf);
      if (editingRisk) await apiCall<FraudRisk>("PATCH", `/fraud-risks/${editingRisk.id}`, payload);
      else await apiCall<FraudRisk>("POST", "/fraud-risks", payload);
      setShowRiskForm(false);
      reloadRisks();
      loadSummary();
      toast(editingRisk ? "Changes saved" : "Fraud risk created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save fraud risk");
    } finally {
      setSavingRisk(false);
    }
  }
  async function removeRisk(r: FraudRisk) {
    if (!(await confirmDialog({ title: `Delete fraud risk ${r.reference || r.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/fraud-risks/${r.id}`);
      setShowRiskForm(false);
      reloadRisks();
      loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- case CRUD
  function openNewCase() {
    setEditingCase(null);
    setCf(BLANK_CASE);
    setShowCaseForm(true);
  }
  function openEditCase(c: FraudCase) {
    setEditingCase(c);
    setCf(fromCase(c));
    setShowCaseForm(true);
  }
  async function saveCase() {
    setError(null);
    setSavingCase(true);
    try {
      const payload = casePayload(cf);
      if (editingCase) await apiCall<FraudCase>("PATCH", `/fraud-cases/${editingCase.id}`, payload);
      else await apiCall<FraudCase>("POST", "/fraud-cases", payload);
      setShowCaseForm(false);
      reloadCases();
      loadSummary();
      toast(editingCase ? "Changes saved" : "Fraud case created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save fraud case");
    } finally {
      setSavingCase(false);
    }
  }
  async function removeCase(c: FraudCase) {
    if (!(await confirmDialog({ title: `Delete fraud case ${c.reference || c.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/fraud-cases/${c.id}`);
      setShowCaseForm(false);
      reloadCases();
      loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- checklist CRUD
  function openNewCheck() {
    setEditingCheck(null);
    setKf(BLANK_CHECK);
    setShowCheckForm(true);
  }
  function openEditCheck(k: FraudControlCheck) {
    setEditingCheck(k);
    setKf(fromCheck(k));
    setShowCheckForm(true);
  }
  async function saveCheck() {
    setError(null);
    setSavingCheck(true);
    try {
      const payload = checkPayload(kf);
      if (editingCheck) await apiCall<FraudControlCheck>("PATCH", `/fraud-control-checks/${editingCheck.id}`, payload);
      else await apiCall<FraudControlCheck>("POST", "/fraud-control-checks", payload);
      setShowCheckForm(false);
      reloadChecks();
      loadSummary();
      toast(editingCheck ? "Changes saved" : "Control check created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save control check");
    } finally {
      setSavingCheck(false);
    }
  }
  async function removeCheck(k: FraudControlCheck) {
    if (!(await confirmDialog({ title: `Delete control check ${k.reference}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/fraud-control-checks/${k.id}`);
      setShowCheckForm(false);
      reloadChecks();
      loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  async function toggleImplemented(k: FraudControlCheck) {
    const on = !k.implemented;
    setError(null);
    try {
      await apiCall<FraudControlCheck>("PATCH", `/fraud-control-checks/${k.id}`, {
        implemented: on,
        status: on ? "implemented" : "not_implemented",
      });
      reloadChecks();
      loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update control check");
    }
  }

  // ------------------------------------------------------------- columns
  const riskColumns: Column<FraudRisk>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (r) => <span className="cell-title">{r.title}</span> },
    { key: "scheme", header: "Scheme", sortable: true, render: (r) => <Badge tone="info">{cap(r.scheme)}</Badge> },
    { key: "channel", header: "Channel", sortable: true, render: (r) => <span className="muted">{cap(r.channel)}</span> },
    { key: "inherent", header: "Inherent LxI", render: (r) => <span className="muted">{r.inherent_likelihood}×{r.inherent_impact} ({r.inherent_score})</span> },
    { key: "control_effectiveness", header: "Control", sortable: true, render: (r) => <EffBadge value={r.control_effectiveness} /> },
    { key: "residual", header: "Residual", render: (r) => <BandBadge score={r.residual_score} /> },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={RISK_STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge> },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => removeRisk(r)}>Delete</button></div> },
  ];

  const caseColumns: Column<FraudCase>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (c) => <span className="cell-title">{c.title}</span> },
    { key: "scheme", header: "Scheme", sortable: true, render: (c) => <Badge tone="info">{cap(c.scheme)}</Badge> },
    { key: "amount_involved", header: "Involved", sortable: true, render: (c) => <span className="muted">{num(c.amount_involved)} {c.currency}</span> },
    { key: "amount_recovered", header: "Recovered", sortable: true, render: (c) => <span className="muted">{num(c.amount_recovered)}</span> },
    { key: "net_loss", header: "Net loss", render: (c) => <span className="muted">{num(c.net_loss)}</span> },
    { key: "perpetrator_type", header: "Perpetrator", sortable: true, render: (c) => <span className="muted">{cap(c.perpetrator_type)}</span> },
    { key: "regulator", header: "Regulator", render: (c) => (c.reported_to_regulator ? <Badge tone="high">Reported{c.regulator_ref ? ` · ${c.regulator_ref}` : ""}</Badge> : <span className="muted">Not reported</span>) },
    { key: "status", header: "Status", sortable: true, render: (c) => <Badge tone={CASE_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge> },
    { key: "actions", header: "", render: (c) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => removeCase(c)}>Delete</button></div> },
  ];

  const checkColumns: Column<FraudControlCheck>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (k) => <span className="ref">{k.reference || "—"}</span> },
    { key: "requirement", header: "Requirement", render: (k) => <span className="cell-title">{k.requirement}</span> },
    { key: "category", header: "Category", sortable: true, render: (k) => <Badge tone="info">{cap(k.category)}</Badge> },
    { key: "sbp_reference", header: "SBP ref", sortable: true, render: (k) => <span className="muted">{k.sbp_reference || "—"}</span> },
    { key: "owner", header: "Owner", sortable: true, render: (k) => <span className="muted">{k.owner || "—"}</span> },
    { key: "target_date", header: "Target", sortable: true, render: (k) => <span className="muted">{k.target_date || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (k) => <Badge tone={CONTROL_STATUS_TONE[k.status] || "neutral"}>{cap(k.status)}</Badge> },
    { key: "implemented", header: "Implemented", render: (k) => <span onClick={(e) => e.stopPropagation()}><Toggle checked={k.implemented} onChange={() => toggleImplemented(k)} /></span> },
    { key: "actions", header: "", render: (k) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => removeCheck(k)}>Delete</button></div> },
  ];

  // ------------------------------------------------------------- risk form tabs
  const riskGeneral = (
    <>
      <Field label="Title" required help="For example: Account-takeover via mobile-app credential theft.">
        <TextInput value={rf.title} onChange={(v) => setR("title", v)} placeholder="Fraud risk title" required />
      </Field>
      <div className="field-row">
        <Field label="Fraud scheme" help="The fraud typology this risk represents.">
          <Select value={rf.scheme} onChange={(v) => setR("scheme", v)} options={FRAUD_SCHEME} />
        </Field>
        <Field label="Channel" help="Banking channel exposed to this risk.">
          <Select value={rf.channel} onChange={(v) => setR("channel", v)} options={FRAUD_CHANNEL} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Business line">
          <TextInput value={rf.business_line} onChange={(v) => setR("business_line", v)} placeholder="Retail banking" />
        </Field>
        <Field label="Status">
          <Select value={rf.status} onChange={(v) => setR("status", v)} options={RISK_STATUS} />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={rf.description} onChange={(v) => setR("description", v)} rows={3} placeholder="How the fraud could occur." />
      </Field>
    </>
  );
  const riskAssessment = (
    <>
      <div className="field-row">
        <Field label="Inherent likelihood" help="1 (rare) to 5 (almost certain).">
          <Select value={rf.inherent_likelihood} onChange={(v) => setR("inherent_likelihood", v)} options={SCORES} />
        </Field>
        <Field label="Inherent impact" help="1 (minor) to 5 (severe).">
          <Select value={rf.inherent_impact} onChange={(v) => setR("inherent_impact", v)} options={SCORES} />
        </Field>
      </div>
      <Field label="Control description" help="Anti-fraud controls that mitigate this risk.">
        <TextArea value={rf.control_description} onChange={(v) => setR("control_description", v)} rows={3} placeholder="Mitigating controls." />
      </Field>
      <Field label="Control effectiveness">
        <Select value={rf.control_effectiveness} onChange={(v) => setR("control_effectiveness", v)} options={CONTROL_EFF} />
      </Field>
      <div className="field-row">
        <Field label="Residual likelihood" help="After controls, 1 to 5.">
          <Select value={rf.residual_likelihood} onChange={(v) => setR("residual_likelihood", v)} options={SCORES} />
        </Field>
        <Field label="Residual impact" help="After controls, 1 to 5.">
          <Select value={rf.residual_impact} onChange={(v) => setR("residual_impact", v)} options={SCORES} />
        </Field>
      </div>
      <Field label="Red flags" help="Warning indicators that this fraud may be occurring.">
        <TextArea value={rf.red_flags} onChange={(v) => setR("red_flags", v)} rows={3} placeholder="Out-of-pattern cash-outs, dormant-account reactivation…" />
      </Field>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={rf.owner} onChange={(v) => setR("owner", v)} placeholder="Risk owner" />
        </Field>
        <Field label="Workflow" help="Approval lifecycle for this record.">
          <Select value={rf.workflow_status} onChange={(v) => setR("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );

  // ------------------------------------------------------------- case form tabs
  const caseGeneral = (
    <>
      <Field label="Title" required help="For example: Unauthorized wire transfer from corporate account.">
        <TextInput value={cf.title} onChange={(v) => setC("title", v)} placeholder="Fraud case title" required />
      </Field>
      <div className="field-row">
        <Field label="Fraud scheme">
          <Select value={cf.scheme} onChange={(v) => setC("scheme", v)} options={FRAUD_SCHEME} />
        </Field>
        <Field label="Channel">
          <Select value={cf.channel} onChange={(v) => setC("channel", v)} options={FRAUD_CHANNEL} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status" help="Case handling lifecycle.">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={CASE_STATUS} />
        </Field>
        <Field label="Perpetrator type">
          <Select value={cf.perpetrator_type} onChange={(v) => setC("perpetrator_type", v)} options={PERPETRATOR} />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={cf.description} onChange={(v) => setC("description", v)} rows={3} placeholder="What happened." />
      </Field>
    </>
  );
  const caseLoss = (
    <>
      <div className="field-row">
        <Field label="Amount involved" help="Gross fraud amount (PKR).">
          <TextInput type="number" value={cf.amount_involved} onChange={(v) => setC("amount_involved", v)} placeholder="0" />
        </Field>
        <Field label="Amount recovered" help="Recovered so far (PKR). Net loss = involved − recovered.">
          <TextInput type="number" value={cf.amount_recovered} onChange={(v) => setC("amount_recovered", v)} placeholder="0" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Currency">
          <TextInput value={cf.currency} onChange={(v) => setC("currency", v)} placeholder="PKR" />
        </Field>
        <Field label="Customers affected">
          <TextInput type="number" value={cf.customers_affected} onChange={(v) => setC("customers_affected", v)} placeholder="0" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Incident date" help="When the fraud occurred.">
          <TextInput type="date" value={cf.incident_date} onChange={(v) => setC("incident_date", v)} />
        </Field>
        <Field label="Discovery date">
          <TextInput type="date" value={cf.discovery_date} onChange={(v) => setC("discovery_date", v)} />
        </Field>
      </div>
      <Field label="Reported date" help="When the case was formally reported internally.">
        <TextInput type="date" value={cf.reported_date} onChange={(v) => setC("reported_date", v)} />
      </Field>
      <Field label="Customer impacted">
        <Toggle checked={cf.customer_impacted} onChange={(v) => setC("customer_impacted", v)} label="One or more customers were impacted" />
      </Field>
    </>
  );
  const caseInvestigation = (
    <>
      <Field label="Reported to regulator (SBP)">
        <Toggle checked={cf.reported_to_regulator} onChange={(v) => setC("reported_to_regulator", v)} label="Case reported to SBP" />
      </Field>
      <Field label="Regulator reference" help="SBP acknowledgement / reference number, if reported.">
        <TextInput value={cf.regulator_ref} onChange={(v) => setC("regulator_ref", v)} placeholder="SBP-…" />
      </Field>
      <Field label="Investigator">
        <TextInput value={cf.investigator} onChange={(v) => setC("investigator", v)} placeholder="Name" />
      </Field>
      <Field label="Root cause">
        <TextArea value={cf.root_cause} onChange={(v) => setC("root_cause", v)} rows={3} placeholder="Underlying cause of the fraud." />
      </Field>
      <Field label="Resolution">
        <TextArea value={cf.resolution} onChange={(v) => setC("resolution", v)} rows={3} placeholder="Outcome, recovery and remediation." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this record.">
        <Select value={cf.workflow_status} onChange={(v) => setC("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- checklist form
  const checkGeneral = (
    <>
      <Field label="Requirement" required help='SBP digital-fraud control, e.g. "Impose 2-hour restriction on out-of-pattern incoming-fund cash-outs / transfers."'>
        <TextArea value={kf.requirement} onChange={(v) => setK("requirement", v)} rows={3} placeholder="Control requirement" />
      </Field>
      <div className="field-row">
        <Field label="Category">
          <Select value={kf.category} onChange={(v) => setK("category", v)} options={CONTROL_CATEGORY} />
        </Field>
        <Field label="SBP reference" help="Circular / clause reference.">
          <TextInput value={kf.sbp_reference} onChange={(v) => setK("sbp_reference", v)} placeholder="PSD Circular …" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status">
          <Select value={kf.status} onChange={(v) => setK("status", v)} options={CONTROL_STATUS} />
        </Field>
        <Field label="Target date" help="Planned implementation date.">
          <TextInput type="date" value={kf.target_date} onChange={(v) => setK("target_date", v)} />
        </Field>
      </div>
      <Field label="Implemented">
        <Toggle checked={kf.implemented} onChange={(v) => setK("implemented", v)} label="Control is implemented" />
      </Field>
      <Field label="Owner">
        <TextInput value={kf.owner} onChange={(v) => setK("owner", v)} placeholder="Accountable owner" />
      </Field>
      <Field label="Evidence note" help="Evidence of implementation.">
        <TextArea value={kf.evidence_note} onChange={(v) => setK("evidence_note", v)} rows={3} placeholder="How compliance is evidenced." />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Fraud Risk Management</h1>
          <p>Fraud risk register, fraud case management with recovery tracking, and the SBP digital-fraud control checklist. Distinct from AML/CFT.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "risks" && (
            <button className="btn" onClick={openNewRisk}>
              <IconPlus width={16} height={16} /> New fraud risk
            </button>
          )}
          {section === "cases" && (
            <button className="btn" onClick={openNewCase}>
              <IconPlus width={16} height={16} /> New fraud case
            </button>
          )}
          {section === "checklist" && (
            <button className="btn" onClick={openNewCheck}>
              <IconPlus width={16} height={16} /> New control check
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.open_cases.toLocaleString() : "—"}</span></div>
          <span className="l">Open fraud cases</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? pkr(summary.total_net_loss) : "—"}</span></div>
          <span className="l">Total net fraud loss</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? `${summary.checklist_pct}%` : "—"}</span></div>
          <span className="l">SBP checklist implemented</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.high_residual_risks.toLocaleString() : "—"}</span></div>
          <span className="l">High residual risks</span>
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

      {/* ============================================= FRAUD RISK REGISTER */}
      {section === "risks" && (
        <DataTable<FraudRisk>
          columns={riskColumns}
          fetcher={fetchRisks}
          rowKey={(r) => r.id}
          onRowClick={(r) => openEditRisk(r)}
          searchPlaceholder="Search fraud risks by title or reference…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No fraud risks. Build the register — score inherent and residual fraud exposure by scheme and channel."
          refreshKey={riskKey}
        />
      )}

      {/* ============================================= FRAUD CASES */}
      {section === "cases" && (
        <DataTable<FraudCase>
          columns={caseColumns}
          fetcher={fetchCases}
          rowKey={(c) => c.id}
          onRowClick={(c) => openEditCase(c)}
          searchPlaceholder="Search fraud cases by title or reference…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No fraud cases. Log incidents with gross / net loss, recovery, perpetrator type and SBP reporting."
          refreshKey={caseKey}
        />
      )}

      {/* ============================================= SBP CONTROL CHECKLIST */}
      {section === "checklist" && (
        <DataTable<FraudControlCheck>
          columns={checkColumns}
          fetcher={fetchChecks}
          rowKey={(k) => k.id}
          onRowClick={(k) => openEditCheck(k)}
          searchPlaceholder="Search checklist by requirement, reference or SBP ref…"
          defaultSort={{ by: "created_at", dir: "asc" }}
          emptyMessage="No control checks. Track SBP digital-fraud control requirements and mark them implemented as evidence is collected."
          refreshKey={checkKey}
          toolbarRight={
            summary ? (
              <div style={{ minWidth: 220 }}>
                <div className="muted" style={{ fontSize: 12, marginBottom: 4, textAlign: "right" }}>
                  {summary.checklist_implemented} / {summary.checklist_total} implemented · {summary.checklist_pct}%
                </div>
                <div className="progress"><span style={{ width: `${summary.checklist_pct}%` }} /></div>
              </div>
            ) : undefined
          }
        />
      )}

      {/* ============================================= MODALS */}
      {showRiskForm && (
        <FormModal
          title={editingRisk ? `Edit fraud risk — ${editingRisk.reference || editingRisk.title}` : "New fraud risk"}
          wide
          tabs={[
            { id: "general", label: "General", content: riskGeneral, required: true },
            { id: "assessment", label: "Assessment", content: riskAssessment },
          ]}
          onClose={() => setShowRiskForm(false)}
          onSave={saveRisk}
          saving={savingRisk}
          error={error}
          saveLabel={editingRisk ? "Save changes" : "Create fraud risk"}
          footerLeft={
            editingRisk ? (
              <button className="btn secondary sm" type="button" onClick={() => removeRisk(editingRisk)} disabled={savingRisk} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showCaseForm && (
        <FormModal
          title={editingCase ? `Edit fraud case — ${editingCase.reference || editingCase.title}` : "New fraud case"}
          wide
          tabs={[
            { id: "general", label: "General", content: caseGeneral, required: true },
            { id: "loss", label: "Loss & Dates", content: caseLoss },
            { id: "investigation", label: "Investigation", content: caseInvestigation },
          ]}
          onClose={() => setShowCaseForm(false)}
          onSave={saveCase}
          saving={savingCase}
          error={error}
          saveLabel={editingCase ? "Save changes" : "Create fraud case"}
          footerLeft={
            editingCase ? (
              <button className="btn secondary sm" type="button" onClick={() => removeCase(editingCase)} disabled={savingCase} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showCheckForm && (
        <FormModal
          title={editingCheck ? `Edit control check — ${editingCheck.reference}` : "New control check"}
          wide
          tabs={[{ id: "general", label: "General", content: checkGeneral, required: true }]}
          onClose={() => setShowCheckForm(false)}
          onSave={saveCheck}
          saving={savingCheck}
          error={error}
          saveLabel={editingCheck ? "Save changes" : "Create control check"}
          footerLeft={
            editingCheck ? (
              <button className="btn secondary sm" type="button" onClick={() => removeCheck(editingCheck)} disabled={savingCheck} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

export default function FraudPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <FraudInner />
    </Suspense>
  );
}
