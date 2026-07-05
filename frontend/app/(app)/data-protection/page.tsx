"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconShield } from "@/components/icons";

// ------------------------------------------------------------------ types
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type Dpia = {
  id: string;
  reference: string;
  title: string;
  processing_activity: string;
  description: string;
  necessity_justification: string;
  risks_identified: string;
  mitigations: string;
  residual_risk: string;
  status: string;
  owner: string;
  dpo_reviewer: string;
  review_date: string | null;
  workflow_status: string;
  created_at: string;
};

type Dsar = {
  id: string;
  reference: string;
  subject_name: string;
  subject_contact: string;
  request_type: string;
  received_date: string | null;
  due_date: string | null;
  response_date: string | null;
  handler: string;
  notes: string;
  status: string;
  workflow_status: string;
  sla_days: number;
  is_overdue: boolean;
  created_at: string;
};

type DataBreach = {
  id: string;
  reference: string;
  title: string;
  description: string;
  breach_type: string;
  discovered_date: string | null;
  occurred_date: string | null;
  records_affected: number;
  data_categories: string;
  severity: string;
  reported_to_regulator: boolean;
  regulator_report_date: string | null;
  notification_required: boolean;
  subjects_notified: boolean;
  status: string;
  owner: string;
  root_cause: string;
  remediation: string;
  workflow_status: string;
  notification_overdue: boolean;
  created_at: string;
};

type ConsentRecord = {
  id: string;
  reference: string;
  subject_name: string;
  purpose: string;
  consent_given: boolean;
  consent_date: string | null;
  withdrawal_date: string | null;
  channel: string;
  lawful_basis: string;
  status: string;
  created_at: string;
};

type DpSummary = {
  dpias_by_status: Record<string, number>;
  dpias_total: number;
  dsars_open: number;
  dsars_overdue: number;
  breaches_open: number;
  breaches_notification_overdue: number;
  consents_active: number;
  consents_withdrawn: number;
};

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

// ------------------------------------------------------------------ enum lists
const DPIA_STATUS = opts(["not_required", "required", "in_progress", "completed", "approved"]);
const DSAR_TYPE = opts(["access", "rectification", "erasure", "portability", "objection", "restriction"]);
const DSAR_STATUS = opts(["received", "verifying", "in_progress", "fulfilled", "rejected"]);
const BREACH_TYPE = opts(["confidentiality", "integrity", "availability"]);
const BREACH_STATUS = opts(["open", "investigating", "contained", "notified", "closed"]);
const CONSENT_STATUS = opts(["active", "withdrawn", "expired"]);
const CRITICALITY = opts(["low", "medium", "high", "critical"]);
const SEVERITY = opts(["low", "medium", "high", "critical"]);
const LAWFUL_BASIS = opts([
  "consent",
  "contract",
  "legal_obligation",
  "vital_interests",
  "public_task",
  "legitimate_interests",
]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

// ------------------------------------------------------------------ tones
const CRIT_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "high", critical: "critical" };
const DPIA_STATUS_TONE: Record<string, Tone> = {
  not_required: "neutral",
  required: "high",
  in_progress: "info",
  completed: "low",
  approved: "low",
};
const DSAR_STATUS_TONE: Record<string, Tone> = {
  received: "info",
  verifying: "info",
  in_progress: "medium",
  fulfilled: "low",
  rejected: "neutral",
};
const BREACH_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  investigating: "medium",
  contained: "info",
  notified: "info",
  closed: "neutral",
};
const CONSENT_STATUS_TONE: Record<string, Tone> = {
  active: "low",
  withdrawn: "high",
  expired: "neutral",
};

function CritBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={CRIT_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

// ------------------------------------------------------------------ form state
type DpiaForm = {
  title: string;
  processing_activity: string;
  description: string;
  necessity_justification: string;
  risks_identified: string;
  mitigations: string;
  residual_risk: string;
  status: string;
  owner: string;
  dpo_reviewer: string;
  review_date: string;
  workflow_status: string;
};
const BLANK_DPIA: DpiaForm = {
  title: "",
  processing_activity: "",
  description: "",
  necessity_justification: "",
  risks_identified: "",
  mitigations: "",
  residual_risk: "low",
  status: "required",
  owner: "",
  dpo_reviewer: "",
  review_date: "",
  workflow_status: "draft",
};
function fromDpia(d: Dpia): DpiaForm {
  return {
    title: d.title,
    processing_activity: d.processing_activity || "",
    description: d.description || "",
    necessity_justification: d.necessity_justification || "",
    risks_identified: d.risks_identified || "",
    mitigations: d.mitigations || "",
    residual_risk: d.residual_risk || "low",
    status: d.status || "required",
    owner: d.owner || "",
    dpo_reviewer: d.dpo_reviewer || "",
    review_date: d.review_date || "",
    workflow_status: d.workflow_status || "draft",
  };
}
function dpiaPayload(f: DpiaForm): Record<string, unknown> {
  return {
    title: f.title,
    processing_activity: f.processing_activity,
    description: f.description,
    necessity_justification: f.necessity_justification,
    risks_identified: f.risks_identified,
    mitigations: f.mitigations,
    residual_risk: f.residual_risk,
    status: f.status,
    owner: f.owner,
    dpo_reviewer: f.dpo_reviewer,
    review_date: f.review_date || null,
    workflow_status: f.workflow_status,
  };
}

type DsarForm = {
  subject_name: string;
  subject_contact: string;
  request_type: string;
  received_date: string;
  due_date: string;
  response_date: string;
  handler: string;
  notes: string;
  status: string;
  workflow_status: string;
};
const BLANK_DSAR: DsarForm = {
  subject_name: "",
  subject_contact: "",
  request_type: "access",
  received_date: "",
  due_date: "",
  response_date: "",
  handler: "",
  notes: "",
  status: "received",
  workflow_status: "draft",
};
function fromDsar(d: Dsar): DsarForm {
  return {
    subject_name: d.subject_name || "",
    subject_contact: d.subject_contact || "",
    request_type: d.request_type || "access",
    received_date: d.received_date || "",
    due_date: d.due_date || "",
    response_date: d.response_date || "",
    handler: d.handler || "",
    notes: d.notes || "",
    status: d.status || "received",
    workflow_status: d.workflow_status || "draft",
  };
}
function dsarPayload(f: DsarForm): Record<string, unknown> {
  return {
    subject_name: f.subject_name,
    subject_contact: f.subject_contact,
    request_type: f.request_type,
    received_date: f.received_date || null,
    due_date: f.due_date || null,
    response_date: f.response_date || null,
    handler: f.handler,
    notes: f.notes,
    status: f.status,
    workflow_status: f.workflow_status,
  };
}

type BreachForm = {
  title: string;
  description: string;
  breach_type: string;
  discovered_date: string;
  occurred_date: string;
  records_affected: string;
  data_categories: string;
  severity: string;
  reported_to_regulator: boolean;
  regulator_report_date: string;
  notification_required: boolean;
  subjects_notified: boolean;
  status: string;
  owner: string;
  root_cause: string;
  remediation: string;
  workflow_status: string;
};
const BLANK_BREACH: BreachForm = {
  title: "",
  description: "",
  breach_type: "confidentiality",
  discovered_date: "",
  occurred_date: "",
  records_affected: "",
  data_categories: "",
  severity: "low",
  reported_to_regulator: false,
  regulator_report_date: "",
  notification_required: false,
  subjects_notified: false,
  status: "open",
  owner: "",
  root_cause: "",
  remediation: "",
  workflow_status: "draft",
};
function fromBreach(b: DataBreach): BreachForm {
  return {
    title: b.title,
    description: b.description || "",
    breach_type: b.breach_type || "confidentiality",
    discovered_date: b.discovered_date || "",
    occurred_date: b.occurred_date || "",
    records_affected: b.records_affected != null ? String(b.records_affected) : "",
    data_categories: b.data_categories || "",
    severity: b.severity || "low",
    reported_to_regulator: !!b.reported_to_regulator,
    regulator_report_date: b.regulator_report_date || "",
    notification_required: !!b.notification_required,
    subjects_notified: !!b.subjects_notified,
    status: b.status || "open",
    owner: b.owner || "",
    root_cause: b.root_cause || "",
    remediation: b.remediation || "",
    workflow_status: b.workflow_status || "draft",
  };
}
function breachPayload(f: BreachForm): Record<string, unknown> {
  return {
    title: f.title,
    description: f.description,
    breach_type: f.breach_type,
    discovered_date: f.discovered_date || null,
    occurred_date: f.occurred_date || null,
    records_affected: f.records_affected === "" ? 0 : Number(f.records_affected),
    data_categories: f.data_categories,
    severity: f.severity,
    reported_to_regulator: f.reported_to_regulator,
    regulator_report_date: f.regulator_report_date || null,
    notification_required: f.notification_required,
    subjects_notified: f.subjects_notified,
    status: f.status,
    owner: f.owner,
    root_cause: f.root_cause,
    remediation: f.remediation,
    workflow_status: f.workflow_status,
  };
}

type ConsentForm = {
  subject_name: string;
  purpose: string;
  consent_given: boolean;
  consent_date: string;
  withdrawal_date: string;
  channel: string;
  lawful_basis: string;
  status: string;
};
const BLANK_CONSENT: ConsentForm = {
  subject_name: "",
  purpose: "",
  consent_given: true,
  consent_date: "",
  withdrawal_date: "",
  channel: "",
  lawful_basis: "consent",
  status: "active",
};
function fromConsent(c: ConsentRecord): ConsentForm {
  return {
    subject_name: c.subject_name || "",
    purpose: c.purpose || "",
    consent_given: !!c.consent_given,
    consent_date: c.consent_date || "",
    withdrawal_date: c.withdrawal_date || "",
    channel: c.channel || "",
    lawful_basis: c.lawful_basis || "consent",
    status: c.status || "active",
  };
}
function consentPayload(f: ConsentForm): Record<string, unknown> {
  return {
    subject_name: f.subject_name,
    purpose: f.purpose,
    consent_given: f.consent_given,
    consent_date: f.consent_date || null,
    withdrawal_date: f.withdrawal_date || null,
    channel: f.channel,
    lawful_basis: f.lawful_basis,
    status: f.status,
  };
}

// ------------------------------------------------------------------ sections
type SectionId = "dpia" | "dsar" | "breach" | "consent";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "dpia", label: "DPIA" },
  { id: "dsar", label: "DSAR" },
  { id: "breach", label: "Breach Register" },
  { id: "consent", label: "Consent" },
];

export default function DataProtectionPage() {
  const [section, setSection] = useState<SectionId>("dpia");
  const [error, setError] = useState<string | null>(null);

  const [dpias, setDpias] = useState<Dpia[]>([]);
  const [dsars, setDsars] = useState<Dsar[]>([]);
  const [breaches, setBreaches] = useState<DataBreach[]>([]);
  const [consents, setConsents] = useState<ConsentRecord[]>([]);
  const [summary, setSummary] = useState<DpSummary | null>(null);

  // ---- DPIA dialog ----
  const [editingDpia, setEditingDpia] = useState<Dpia | null>(null);
  const [showDpiaForm, setShowDpiaForm] = useState(false);
  const [savingDpia, setSavingDpia] = useState(false);
  const [df, setDf] = useState<DpiaForm>(BLANK_DPIA);
  const setD = <K extends keyof DpiaForm>(k: K, v: DpiaForm[K]) => setDf((p) => ({ ...p, [k]: v }));

  // ---- DSAR dialog ----
  const [editingDsar, setEditingDsar] = useState<Dsar | null>(null);
  const [showDsarForm, setShowDsarForm] = useState(false);
  const [savingDsar, setSavingDsar] = useState(false);
  const [sf, setSf] = useState<DsarForm>(BLANK_DSAR);
  const setS = <K extends keyof DsarForm>(k: K, v: DsarForm[K]) => setSf((p) => ({ ...p, [k]: v }));

  // ---- Breach dialog + expanded detail ----
  const [editingBreach, setEditingBreach] = useState<DataBreach | null>(null);
  const [showBreachForm, setShowBreachForm] = useState(false);
  const [savingBreach, setSavingBreach] = useState(false);
  const [bf, setBf] = useState<BreachForm>(BLANK_BREACH);
  const setB = <K extends keyof BreachForm>(k: K, v: BreachForm[K]) => setBf((p) => ({ ...p, [k]: v }));
  const [openBreach, setOpenBreach] = useState<DataBreach | null>(null);

  // ---- Consent dialog ----
  const [editingConsent, setEditingConsent] = useState<ConsentRecord | null>(null);
  const [showConsentForm, setShowConsentForm] = useState(false);
  const [savingConsent, setSavingConsent] = useState(false);
  const [cf, setCf] = useState<ConsentForm>(BLANK_CONSENT);
  const setC = <K extends keyof ConsentForm>(k: K, v: ConsentForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadDpias() {
    try {
      const res = await apiCall<Page<Dpia>>("GET", "/dpias?limit=200");
      setDpias(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load DPIAs");
    }
  }
  async function loadDsars() {
    try {
      const res = await apiCall<Page<Dsar>>("GET", "/dsars?limit=200");
      setDsars(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load DSARs");
    }
  }
  async function loadBreaches(keepOpen?: string) {
    try {
      const res = await apiCall<Page<DataBreach>>("GET", "/data-breaches?limit=200");
      setBreaches(res.items);
      if (keepOpen) setOpenBreach(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load breach register");
    }
  }
  async function loadConsents() {
    try {
      const res = await apiCall<Page<ConsentRecord>>("GET", "/consent-records?limit=200");
      setConsents(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load consent ledger");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<DpSummary>("GET", "/data-protection-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }

  useEffect(() => {
    loadDpias();
    loadDsars();
    loadBreaches();
    loadConsents();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- DPIA CRUD
  function openNewDpia() {
    setEditingDpia(null);
    setDf(BLANK_DPIA);
    setShowDpiaForm(true);
  }
  function openEditDpia(d: Dpia) {
    setEditingDpia(d);
    setDf(fromDpia(d));
    setShowDpiaForm(true);
  }
  async function saveDpia() {
    setError(null);
    setSavingDpia(true);
    try {
      const payload = dpiaPayload(df);
      if (editingDpia) await apiCall("PATCH", `/dpias/${editingDpia.id}`, payload);
      else await apiCall("POST", "/dpias", payload);
      setShowDpiaForm(false);
      await loadDpias();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save DPIA");
    } finally {
      setSavingDpia(false);
    }
  }
  async function removeDpia(d: Dpia) {
    if (!window.confirm(`Delete DPIA ${d.reference || d.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/dpias/${d.id}`);
      setShowDpiaForm(false);
      await loadDpias();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- DSAR CRUD
  function openNewDsar() {
    setEditingDsar(null);
    setSf(BLANK_DSAR);
    setShowDsarForm(true);
  }
  function openEditDsar(d: Dsar) {
    setEditingDsar(d);
    setSf(fromDsar(d));
    setShowDsarForm(true);
  }
  async function saveDsar() {
    setError(null);
    setSavingDsar(true);
    try {
      const payload = dsarPayload(sf);
      if (editingDsar) await apiCall("PATCH", `/dsars/${editingDsar.id}`, payload);
      else await apiCall("POST", "/dsars", payload);
      setShowDsarForm(false);
      await loadDsars();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save DSAR");
    } finally {
      setSavingDsar(false);
    }
  }
  async function removeDsar(d: Dsar) {
    if (!window.confirm(`Delete DSAR ${d.reference || d.subject_name}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/dsars/${d.id}`);
      setShowDsarForm(false);
      await loadDsars();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- Breach CRUD
  function openNewBreach() {
    setEditingBreach(null);
    setBf(BLANK_BREACH);
    setShowBreachForm(true);
  }
  function openEditBreach(b: DataBreach) {
    setEditingBreach(b);
    setBf(fromBreach(b));
    setShowBreachForm(true);
  }
  function toggleBreach(b: DataBreach) {
    setOpenBreach(openBreach?.id === b.id ? null : b);
  }
  async function saveBreach() {
    setError(null);
    setSavingBreach(true);
    try {
      const payload = breachPayload(bf);
      if (editingBreach) await apiCall("PATCH", `/data-breaches/${editingBreach.id}`, payload);
      else await apiCall("POST", "/data-breaches", payload);
      setShowBreachForm(false);
      await loadBreaches(openBreach?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save breach");
    } finally {
      setSavingBreach(false);
    }
  }
  async function removeBreach(b: DataBreach) {
    if (!window.confirm(`Delete breach ${b.reference || b.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/data-breaches/${b.id}`);
      setShowBreachForm(false);
      if (openBreach?.id === b.id) setOpenBreach(null);
      await loadBreaches();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- Consent CRUD
  function openNewConsent() {
    setEditingConsent(null);
    setCf(BLANK_CONSENT);
    setShowConsentForm(true);
  }
  function openEditConsent(c: ConsentRecord) {
    setEditingConsent(c);
    setCf(fromConsent(c));
    setShowConsentForm(true);
  }
  async function saveConsent() {
    setError(null);
    setSavingConsent(true);
    try {
      const payload = consentPayload(cf);
      if (editingConsent) await apiCall("PATCH", `/consent-records/${editingConsent.id}`, payload);
      else await apiCall("POST", "/consent-records", payload);
      setShowConsentForm(false);
      await loadConsents();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save consent record");
    } finally {
      setSavingConsent(false);
    }
  }
  async function removeConsent(c: ConsentRecord) {
    if (!window.confirm(`Delete consent record ${c.reference || c.subject_name}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/consent-records/${c.id}`);
      setShowConsentForm(false);
      await loadConsents();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- DPIA form tabs
  const dpiaGeneral = (
    <>
      <Field label="Title" required help="For example: Retail onboarding biometric KYC processing.">
        <TextInput value={df.title} onChange={(v) => setD("title", v)} placeholder="DPIA title" required />
      </Field>
      <div className="field-row">
        <Field label="Processing activity" help="The RoPA activity this assessment covers.">
          <TextInput value={df.processing_activity} onChange={(v) => setD("processing_activity", v)} placeholder="Customer onboarding" />
        </Field>
        <Field label="Status">
          <Select value={df.status} onChange={(v) => setD("status", v)} options={DPIA_STATUS} />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={df.description} onChange={(v) => setD("description", v)} rows={3} placeholder="Scope and nature of the processing." />
      </Field>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={df.owner} onChange={(v) => setD("owner", v)} placeholder="Business owner" />
        </Field>
        <Field label="Residual risk" help="Residual risk after mitigations.">
          <Select value={df.residual_risk} onChange={(v) => setD("residual_risk", v)} options={CRITICALITY} />
        </Field>
      </div>
    </>
  );
  const dpiaAssessment = (
    <>
      <Field label="Necessity & proportionality" help="Why the processing is necessary and proportionate.">
        <TextArea value={df.necessity_justification} onChange={(v) => setD("necessity_justification", v)} rows={3} placeholder="Necessity justification" />
      </Field>
      <Field label="Risks identified" help="Risks to data subjects.">
        <TextArea value={df.risks_identified} onChange={(v) => setD("risks_identified", v)} rows={3} placeholder="Identified risks to rights and freedoms" />
      </Field>
      <Field label="Mitigations" help="Measures to reduce the risks.">
        <TextArea value={df.mitigations} onChange={(v) => setD("mitigations", v)} rows={3} placeholder="Mitigating measures" />
      </Field>
    </>
  );
  const dpiaReview = (
    <>
      <div className="field-row">
        <Field label="DPO reviewer" help="Data Protection Officer who reviewed this DPIA.">
          <TextInput value={df.dpo_reviewer} onChange={(v) => setD("dpo_reviewer", v)} placeholder="DPO name" />
        </Field>
        <Field label="Review date">
          <TextInput type="date" value={df.review_date} onChange={(v) => setD("review_date", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this DPIA record.">
        <Select value={df.workflow_status} onChange={(v) => setD("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- DSAR form tabs
  const dsarGeneral = (
    <>
      <div className="field-row">
        <Field label="Subject name" help="The data subject making the request.">
          <TextInput value={sf.subject_name} onChange={(v) => setS("subject_name", v)} placeholder="Full name" />
        </Field>
        <Field label="Subject contact" help="Email / phone / CNIC for verification.">
          <TextInput value={sf.subject_contact} onChange={(v) => setS("subject_contact", v)} placeholder="Contact detail" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Request type" help="The data-subject right being exercised.">
          <Select value={sf.request_type} onChange={(v) => setS("request_type", v)} options={DSAR_TYPE} />
        </Field>
        <Field label="Status">
          <Select value={sf.status} onChange={(v) => setS("status", v)} options={DSAR_STATUS} />
        </Field>
      </div>
      <Field label="Handler" help="Officer handling the request.">
        <TextInput value={sf.handler} onChange={(v) => setS("handler", v)} placeholder="Assigned handler" />
      </Field>
    </>
  );
  const dsarTiming = (
    <>
      <div className="field-row">
        <Field label="Received date" help="When the request was received — starts the 30-day SLA clock.">
          <TextInput type="date" value={sf.received_date} onChange={(v) => setS("received_date", v)} />
        </Field>
        <Field label="Due date" help="Statutory response deadline (30 days).">
          <TextInput type="date" value={sf.due_date} onChange={(v) => setS("due_date", v)} />
        </Field>
      </div>
      <Field label="Response date" help="When the request was fulfilled / responded to.">
        <TextInput type="date" value={sf.response_date} onChange={(v) => setS("response_date", v)} />
      </Field>
      <Field label="Notes">
        <TextArea value={sf.notes} onChange={(v) => setS("notes", v)} rows={3} placeholder="Handling notes, verification steps, outcome." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this request record.">
        <Select value={sf.workflow_status} onChange={(v) => setS("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- Breach form tabs
  const breachGeneral = (
    <>
      <Field label="Title" required help="For example: Misdirected statements exposed to wrong customers.">
        <TextInput value={bf.title} onChange={(v) => setB("title", v)} placeholder="Breach title" required />
      </Field>
      <div className="field-row">
        <Field label="Breach type" help="Confidentiality, integrity or availability breach.">
          <Select value={bf.breach_type} onChange={(v) => setB("breach_type", v)} options={BREACH_TYPE} />
        </Field>
        <Field label="Severity">
          <Select value={bf.severity} onChange={(v) => setB("severity", v)} options={SEVERITY} />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={bf.description} onChange={(v) => setB("description", v)} rows={3} placeholder="What happened." />
      </Field>
      <div className="field-row">
        <Field label="Records affected" help="Number of personal-data records impacted.">
          <TextInput type="number" value={bf.records_affected} onChange={(v) => setB("records_affected", v)} placeholder="0" />
        </Field>
        <Field label="Status">
          <Select value={bf.status} onChange={(v) => setB("status", v)} options={BREACH_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Data categories" help="Categories of personal data involved.">
          <TextInput value={bf.data_categories} onChange={(v) => setB("data_categories", v)} placeholder="Name, CNIC, account balance" />
        </Field>
        <Field label="Owner">
          <TextInput value={bf.owner} onChange={(v) => setB("owner", v)} placeholder="Response owner" />
        </Field>
      </div>
    </>
  );
  const breachTiming = (
    <>
      <div className="field-row">
        <Field label="Discovered date" help="When the breach was discovered — starts the 72-hour clock.">
          <TextInput type="date" value={bf.discovered_date} onChange={(v) => setB("discovered_date", v)} />
        </Field>
        <Field label="Occurred date">
          <TextInput type="date" value={bf.occurred_date} onChange={(v) => setB("occurred_date", v)} />
        </Field>
      </div>
      <Field label="Regulator notification required" help="Does this breach require notifying the regulator?">
        <Toggle checked={bf.notification_required} onChange={(v) => setB("notification_required", v)} label="Notification required" />
      </Field>
      <div className="field-row">
        <Field label="Reported to regulator">
          <Toggle checked={bf.reported_to_regulator} onChange={(v) => setB("reported_to_regulator", v)} label="Reported" />
        </Field>
        <Field label="Regulator report date">
          <TextInput type="date" value={bf.regulator_report_date} onChange={(v) => setB("regulator_report_date", v)} />
        </Field>
      </div>
      <Field label="Subjects notified" help="Have affected data subjects been notified?">
        <Toggle checked={bf.subjects_notified} onChange={(v) => setB("subjects_notified", v)} label="Subjects notified" />
      </Field>
    </>
  );
  const breachResponse = (
    <>
      <Field label="Root cause">
        <TextArea value={bf.root_cause} onChange={(v) => setB("root_cause", v)} rows={3} placeholder="Underlying cause of the breach." />
      </Field>
      <Field label="Remediation">
        <TextArea value={bf.remediation} onChange={(v) => setB("remediation", v)} rows={3} placeholder="Containment and corrective actions." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this breach record.">
        <Select value={bf.workflow_status} onChange={(v) => setB("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- Consent form tabs
  const consentGeneral = (
    <>
      <div className="field-row">
        <Field label="Subject name" help="The data subject giving consent.">
          <TextInput value={cf.subject_name} onChange={(v) => setC("subject_name", v)} placeholder="Full name" />
        </Field>
        <Field label="Status">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={CONSENT_STATUS} />
        </Field>
      </div>
      <Field label="Purpose" help="What the consent is for.">
        <TextInput value={cf.purpose} onChange={(v) => setC("purpose", v)} placeholder="Marketing communications" />
      </Field>
      <div className="field-row">
        <Field label="Lawful basis" help="Lawful basis relied upon for the processing.">
          <Select value={cf.lawful_basis} onChange={(v) => setC("lawful_basis", v)} options={LAWFUL_BASIS} />
        </Field>
        <Field label="Channel" help="How the consent was collected.">
          <TextInput value={cf.channel} onChange={(v) => setC("channel", v)} placeholder="Mobile app / branch form" />
        </Field>
      </div>
      <Field label="Consent given">
        <Toggle checked={cf.consent_given} onChange={(v) => setC("consent_given", v)} label="Consent granted" />
      </Field>
      <div className="field-row">
        <Field label="Consent date">
          <TextInput type="date" value={cf.consent_date} onChange={(v) => setC("consent_date", v)} />
        </Field>
        <Field label="Withdrawal date">
          <TextInput type="date" value={cf.withdrawal_date} onChange={(v) => setC("withdrawal_date", v)} />
        </Field>
      </div>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Data Protection</h1>
          <p>Pakistan PDPA readiness — impact assessments, subject access requests on a 30-day SLA, the breach register with the 72-hour notification rule, and a consent ledger.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "dpia" && (
            <button className="btn" onClick={openNewDpia}><IconPlus width={16} height={16} /> New DPIA</button>
          )}
          {section === "dsar" && (
            <button className="btn" onClick={openNewDsar}><IconPlus width={16} height={16} /> New DSAR</button>
          )}
          {section === "breach" && (
            <button className="btn" onClick={openNewBreach}><IconPlus width={16} height={16} /> New breach</button>
          )}
          {section === "consent" && (
            <button className="btn" onClick={openNewConsent}><IconPlus width={16} height={16} /> New consent</button>
          )}
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.dsars_open.toLocaleString() : "—"}</span></div>
          <span className="l">Open DSARs</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.dsars_overdue.toLocaleString() : "—"}</span></div>
          <span className="l">DSARs overdue</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.breaches_open.toLocaleString() : "—"}</span></div>
          <span className="l">Breaches open</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.breaches_notification_overdue.toLocaleString() : "—"}</span></div>
          <span className="l">72h notify overdue</span>
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

      {/* ============================================= DPIA */}
      {section === "dpia" && (
        <div className="card">
          <div className="card-head">
            <h3>Data Protection Impact Assessments</h3>
            <span className="sub">{dpias.length} total · click a row to edit</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Title</th>
                  <th>Processing activity</th>
                  <th>Residual risk</th>
                  <th>Status</th>
                  <th>DPO reviewer</th>
                  <th>Review date</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {dpias.map((d) => (
                  <tr key={d.id} style={{ cursor: "pointer" }} onClick={() => openEditDpia(d)}>
                    <td className="ref">{d.reference || "—"}</td>
                    <td className="cell-title">{d.title}</td>
                    <td className="muted">{d.processing_activity || "—"}</td>
                    <td><CritBadge value={d.residual_risk} /></td>
                    <td><Badge tone={DPIA_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge></td>
                    <td className="muted">{d.dpo_reviewer || "—"}</td>
                    <td className="muted">{d.review_date || "—"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeDpia(d)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {dpias.length === 0 && (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty">
                        <span className="ico"><IconShield width={24} height={24} /></span>
                        <h3>No DPIAs</h3>
                        <p>Assess the data-protection impact of high-risk processing activities.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= DSAR */}
      {section === "dsar" && (
        <div className="card">
          <div className="card-head">
            <h3>Data Subject Access Requests</h3>
            <span className="sub">{dsars.length} total · 30-day statutory SLA · click a row to edit</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Subject</th>
                  <th>Type</th>
                  <th>Received</th>
                  <th>Due / SLA</th>
                  <th>Handler</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {dsars.map((d) => (
                  <tr key={d.id} style={{ cursor: "pointer" }} onClick={() => openEditDsar(d)}>
                    <td className="ref">{d.reference || "—"}</td>
                    <td className="cell-title">{d.subject_name || "—"}</td>
                    <td><Badge tone="info">{cap(d.request_type)}</Badge></td>
                    <td className="muted">{d.received_date || "—"}</td>
                    <td>
                      {d.is_overdue ? (
                        <Badge tone="critical">Overdue</Badge>
                      ) : (
                        <span className="muted">{d.due_date || "—"} · {d.sla_days}d SLA</span>
                      )}
                    </td>
                    <td className="muted">{d.handler || "—"}</td>
                    <td><Badge tone={DSAR_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge></td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeDsar(d)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {dsars.length === 0 && (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty">
                        <span className="ico"><IconShield width={24} height={24} /></span>
                        <h3>No subject requests</h3>
                        <p>Log data-subject access, erasure and portability requests to track the SLA.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= BREACH REGISTER */}
      {section === "breach" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>Personal-Data Breach Register</h3>
              <span className="sub">{breaches.length} total · 72-hour regulator notification rule · click a row to expand</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Title</th>
                    <th>Type</th>
                    <th>Severity</th>
                    <th>Records</th>
                    <th>Status</th>
                    <th>Notification</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {breaches.map((b) => (
                    <tr key={b.id} style={{ cursor: "pointer" }} onClick={() => toggleBreach(b)}>
                      <td className="ref">{b.reference || "—"}</td>
                      <td className="cell-title">{b.title}</td>
                      <td><Badge tone="info">{cap(b.breach_type)}</Badge></td>
                      <td><CritBadge value={b.severity} /></td>
                      <td className="muted">{num(b.records_affected)}</td>
                      <td><Badge tone={BREACH_STATUS_TONE[b.status] || "neutral"}>{cap(b.status)}</Badge></td>
                      <td>
                        {b.notification_overdue ? (
                          <Badge tone="critical">72h overdue</Badge>
                        ) : b.reported_to_regulator ? (
                          <Badge tone="low">Reported</Badge>
                        ) : b.notification_required ? (
                          <Badge tone="medium">Required</Badge>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleBreach(b)}>
                            {openBreach?.id === b.id ? "Hide" : "Open"}
                          </button>
                          <button className="btn secondary sm" onClick={() => removeBreach(b)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {breaches.length === 0 && (
                    <tr>
                      <td colSpan={8}>
                        <div className="empty">
                          <span className="ico"><IconShield width={24} height={24} /></span>
                          <h3>No breaches recorded</h3>
                          <p>Register personal-data breaches to track containment and regulator notification.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openBreach && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openBreach.reference} — {openBreach.title}</h3>
                    <span className="sub">
                      {cap(openBreach.status)} · {cap(openBreach.breach_type)} · {num(openBreach.records_affected)} records
                      {openBreach.discovered_date ? " · discovered " + openBreach.discovered_date : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    {openBreach.notification_overdue && <Badge tone="critical">72h notification overdue</Badge>}
                    <button className="btn secondary sm" onClick={() => openEditBreach(openBreach)}>Edit</button>
                    <button className="btn secondary sm" onClick={() => removeBreach(openBreach)}>Delete</button>
                  </div>
                </div>
                <div className="card-pad">
                  <div className="field-row" style={{ marginBottom: 12 }}>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Data categories</div>
                      <strong>{openBreach.data_categories || "—"}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Owner</div>
                      <strong>{openBreach.owner || "—"}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Regulator reported</div>
                      <strong>{openBreach.reported_to_regulator ? (openBreach.regulator_report_date || "Yes") : "No"}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Subjects notified</div>
                      <strong>{openBreach.subjects_notified ? "Yes" : "No"}</strong>
                    </div>
                  </div>
                  <div style={{ marginBottom: 10 }}>
                    <div className="muted" style={{ fontSize: 12 }}>Root cause</div>
                    <p style={{ margin: "2px 0 0" }}>{openBreach.root_cause || "—"}</p>
                  </div>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Remediation</div>
                    <p style={{ margin: "2px 0 0" }}>{openBreach.remediation || "—"}</p>
                  </div>
                </div>
              </div>

              <RecordPanels model="data_breach" entityId={openBreach.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= CONSENT */}
      {section === "consent" && (
        <>
          <div className="grid stat-grid" style={{ marginBottom: 16 }}>
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.consents_active.toLocaleString() : "—"}</span></div>
              <span className="l">Active consents</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.consents_withdrawn.toLocaleString() : "—"}</span></div>
              <span className="l">Withdrawn</span>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Consent Ledger</h3>
              <span className="sub">{consents.length} total · click a row to edit</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Subject</th>
                    <th>Purpose</th>
                    <th>Lawful basis</th>
                    <th>Channel</th>
                    <th>Given</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {consents.map((c) => (
                    <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => openEditConsent(c)}>
                      <td className="ref">{c.reference || "—"}</td>
                      <td className="cell-title">{c.subject_name || "—"}</td>
                      <td className="muted">{c.purpose || "—"}</td>
                      <td className="muted">{cap(c.lawful_basis)}</td>
                      <td className="muted">{c.channel || "—"}</td>
                      <td className="muted">{c.consent_given ? (c.consent_date || "Yes") : "No"}</td>
                      <td><Badge tone={CONSENT_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge></td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => removeConsent(c)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {consents.length === 0 && (
                    <tr>
                      <td colSpan={8}>
                        <div className="empty">
                          <span className="ico"><IconShield width={24} height={24} /></span>
                          <h3>No consent records</h3>
                          <p>Record subject consents, their lawful basis, and withdrawals.</p>
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

      {/* ============================================= MODALS */}
      {showDpiaForm && (
        <FormModal
          title={editingDpia ? `Edit DPIA — ${editingDpia.reference || editingDpia.title}` : "New DPIA"}
          wide
          tabs={[
            { id: "general", label: "General", content: dpiaGeneral, required: true },
            { id: "assessment", label: "Assessment", content: dpiaAssessment },
            { id: "review", label: "Review", content: dpiaReview },
          ]}
          onClose={() => setShowDpiaForm(false)}
          onSave={saveDpia}
          saving={savingDpia}
          error={error}
          saveLabel={editingDpia ? "Save changes" : "Create DPIA"}
          footerLeft={
            editingDpia ? (
              <button className="btn secondary sm" type="button" onClick={() => removeDpia(editingDpia)} disabled={savingDpia} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}

      {showDsarForm && (
        <FormModal
          title={editingDsar ? `Edit DSAR — ${editingDsar.reference || editingDsar.subject_name}` : "New DSAR"}
          wide
          tabs={[
            { id: "general", label: "General", content: dsarGeneral },
            { id: "timing", label: "Timing & notes", content: dsarTiming },
          ]}
          onClose={() => setShowDsarForm(false)}
          onSave={saveDsar}
          saving={savingDsar}
          error={error}
          saveLabel={editingDsar ? "Save changes" : "Create DSAR"}
          footerLeft={
            editingDsar ? (
              <button className="btn secondary sm" type="button" onClick={() => removeDsar(editingDsar)} disabled={savingDsar} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}

      {showBreachForm && (
        <FormModal
          title={editingBreach ? `Edit breach — ${editingBreach.reference || editingBreach.title}` : "New breach"}
          wide
          tabs={[
            { id: "general", label: "General", content: breachGeneral, required: true },
            { id: "timing", label: "Timing & notification", content: breachTiming },
            { id: "response", label: "Response", content: breachResponse },
          ]}
          onClose={() => setShowBreachForm(false)}
          onSave={saveBreach}
          saving={savingBreach}
          error={error}
          saveLabel={editingBreach ? "Save changes" : "Create breach"}
          footerLeft={
            editingBreach ? (
              <button className="btn secondary sm" type="button" onClick={() => removeBreach(editingBreach)} disabled={savingBreach} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}

      {showConsentForm && (
        <FormModal
          title={editingConsent ? `Edit consent — ${editingConsent.reference || editingConsent.subject_name}` : "New consent"}
          wide
          tabs={[{ id: "general", label: "General", content: consentGeneral }]}
          onClose={() => setShowConsentForm(false)}
          onSave={saveConsent}
          saving={savingConsent}
          error={error}
          saveLabel={editingConsent ? "Save changes" : "Create consent"}
          footerLeft={
            editingConsent ? (
              <button className="btn secondary sm" type="button" onClick={() => removeConsent(editingConsent)} disabled={savingConsent} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}
    </>
  );
}
