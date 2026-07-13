"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import RelatedChips from "@/components/RelatedChips";
import AsyncSelect from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ types
type Ref = { id: string; reference?: string; title?: string; name?: string };
const refLabel = (x: Ref) => x.reference || x.title || x.name || x.id;
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
  // additive FK to the incident register (nullable)
  incident?: Ref | null;
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
  incident_id: string;
  incident_label: string;
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
  incident_id: "",
  incident_label: "",
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
    incident_id: b.incident?.id || "",
    incident_label: b.incident ? refLabel(b.incident) : "",
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
    incident_id: f.incident_id || null,
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

// ================================================================ DPIA section
function DpiaSection({ onChanged }: { onChanged: () => void }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const [editing, setEditing] = useState<Dpia | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [df, setDf] = useState<DpiaForm>(BLANK_DPIA);
  const setD = <K extends keyof DpiaForm>(k: K, v: DpiaForm[K]) => setDf((p) => ({ ...p, [k]: v }));

  const fetcher = useCallback((qs: string) => apiCall<PagedList<Dpia>>("GET", `/dpias?${qs}`), []);

  function openNew() {
    setEditing(null);
    setDf(BLANK_DPIA);
    setError(null);
    setShowForm(true);
  }
  function openEdit(d: Dpia) {
    setEditing(d);
    setDf(fromDpia(d));
    setError(null);
    setShowForm(true);
  }
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = dpiaPayload(df);
      if (editing) await apiCall("PATCH", `/dpias/${editing.id}`, payload);
      else await apiCall("POST", "/dpias", payload);
      setShowForm(false);
      reload();
      onChanged();
      toast(editing ? "Changes saved" : "DPIA created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save DPIA");
    } finally {
      setSaving(false);
    }
  }
  async function remove(d: Dpia) {
    if (!(await confirmDialog({ title: `Delete DPIA ${d.reference || d.title}?`, danger: true }))) return;
    try {
      await apiCall("DELETE", `/dpias/${d.id}`);
      setShowForm(false);
      reload();
      onChanged();
      toast("Deleted");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to delete", "error");
    }
  }

  const columns: Column<Dpia>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (d) => <span className="ref">{d.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (d) => <span className="cell-title">{d.title}</span> },
    { key: "processing_activity", header: "Processing activity", sortable: true, render: (d) => <span className="muted">{d.processing_activity || "—"}</span> },
    { key: "residual_risk", header: "Residual risk", sortable: true, render: (d) => <CritBadge value={d.residual_risk} /> },
    { key: "status", header: "Status", sortable: true, render: (d) => <Badge tone={DPIA_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge> },
    { key: "dpo_reviewer", header: "DPO reviewer", render: (d) => <span className="muted">{d.dpo_reviewer || "—"}</span> },
    { key: "review_date", header: "Review date", sortable: true, render: (d) => <span className="muted">{d.review_date || "—"}</span> },
    { key: "actions", header: "", render: (d) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(d)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(d)}>Delete</button></div> },
  ];

  const general = (
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
  const assessment = (
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
  const review = (
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

  return (
    <>
      <DataTable<Dpia>
        columns={columns}
        fetcher={fetcher}
        rowKey={(d) => d.id}
        onRowClick={openEdit}
        searchPlaceholder="Search DPIAs by title, reference, owner…"
        emptyMessage="No DPIAs yet. Assess the data-protection impact of high-risk processing activities."
        refreshKey={refreshKey}
        toolbarRight={<button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> New DPIA</button>}
      />
      {showForm && (
        <FormModal
          title={editing ? `Edit DPIA — ${editing.reference || editing.title}` : "New DPIA"}
          wide
          tabs={[
            { id: "general", label: "General", content: general, required: true },
            { id: "assessment", label: "Assessment", content: assessment },
            { id: "review", label: "Review", content: review },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create DPIA"}
          footerLeft={
            editing ? (
              <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

// ================================================================ DSAR section
function DsarSection({ onChanged }: { onChanged: () => void }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const [editing, setEditing] = useState<Dsar | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sf, setSf] = useState<DsarForm>(BLANK_DSAR);
  const setS = <K extends keyof DsarForm>(k: K, v: DsarForm[K]) => setSf((p) => ({ ...p, [k]: v }));

  const fetcher = useCallback((qs: string) => apiCall<PagedList<Dsar>>("GET", `/dsars?${qs}`), []);

  function openNew() {
    setEditing(null);
    setSf(BLANK_DSAR);
    setError(null);
    setShowForm(true);
  }
  function openEdit(d: Dsar) {
    setEditing(d);
    setSf(fromDsar(d));
    setError(null);
    setShowForm(true);
  }
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = dsarPayload(sf);
      if (editing) await apiCall("PATCH", `/dsars/${editing.id}`, payload);
      else await apiCall("POST", "/dsars", payload);
      setShowForm(false);
      reload();
      onChanged();
      toast(editing ? "Changes saved" : "DSAR created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save DSAR");
    } finally {
      setSaving(false);
    }
  }
  async function remove(d: Dsar) {
    if (!(await confirmDialog({ title: `Delete DSAR ${d.reference || d.subject_name}?`, danger: true }))) return;
    try {
      await apiCall("DELETE", `/dsars/${d.id}`);
      setShowForm(false);
      reload();
      onChanged();
      toast("Deleted");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to delete", "error");
    }
  }

  const columns: Column<Dsar>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (d) => <span className="ref">{d.reference || "—"}</span> },
    { key: "subject_name", header: "Subject", sortable: true, render: (d) => <span className="cell-title">{d.subject_name || "—"}</span> },
    { key: "request_type", header: "Type", sortable: true, render: (d) => <Badge tone="info">{cap(d.request_type)}</Badge> },
    { key: "received_date", header: "Received", sortable: true, render: (d) => <span className="muted">{d.received_date || "—"}</span> },
    { key: "due_date", header: "Due / SLA", sortable: true, render: (d) => (d.is_overdue ? <Badge tone="critical">Overdue</Badge> : <span className="muted">{d.due_date || "—"} · {d.sla_days}d SLA</span>) },
    { key: "handler", header: "Handler", sortable: true, render: (d) => <span className="muted">{d.handler || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (d) => <Badge tone={DSAR_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge> },
    { key: "actions", header: "", render: (d) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(d)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(d)}>Delete</button></div> },
  ];

  const general = (
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
  const timing = (
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

  return (
    <>
      <DataTable<Dsar>
        columns={columns}
        fetcher={fetcher}
        rowKey={(d) => d.id}
        onRowClick={openEdit}
        searchPlaceholder="Search DSARs by subject, reference, handler…"
        emptyMessage="No subject requests yet. Log access, erasure and portability requests to track the SLA."
        refreshKey={refreshKey}
        toolbarRight={<button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> New DSAR</button>}
      />
      {showForm && (
        <FormModal
          title={editing ? `Edit DSAR — ${editing.reference || editing.subject_name}` : "New DSAR"}
          wide
          tabs={[
            { id: "general", label: "General", content: general },
            { id: "timing", label: "Timing & notes", content: timing },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create DSAR"}
          footerLeft={
            editing ? (
              <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

// ============================================================== Breach section
function BreachSection({ onChanged }: { onChanged: () => void }) {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<DataBreach | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const [editing, setEditing] = useState<DataBreach | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bf, setBf] = useState<BreachForm>(BLANK_BREACH);
  const setB = <K extends keyof BreachForm>(k: K, v: BreachForm[K]) => setBf((p) => ({ ...p, [k]: v }));

  // server typeahead over the incident register for the breach's incident FK
  const searchIncidents = (q: string) =>
    apiCall<PagedList<Ref>>("GET", `/incidents?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((x) => ({ value: x.id, label: refLabel(x), sub: x.reference })),
    );

  const fetcher = useCallback((qs: string) => apiCall<PagedList<DataBreach>>("GET", `/data-breaches?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<DataBreach>("GET", `/data-breaches/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  function openNew() {
    setEditing(null);
    setBf(BLANK_BREACH);
    setError(null);
    setShowForm(true);
  }
  function openEdit(b: DataBreach) {
    setEditing(b);
    setBf(fromBreach(b));
    setError(null);
    setShowForm(true);
  }
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = breachPayload(bf);
      if (editing) await apiCall("PATCH", `/data-breaches/${editing.id}`, payload);
      else await apiCall("POST", "/data-breaches", payload);
      setShowForm(false);
      reload();
      onChanged();
      if (openId) loadDetail(openId);
      toast(editing ? "Changes saved" : "Breach created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save breach");
    } finally {
      setSaving(false);
    }
  }
  async function remove(b: DataBreach) {
    if (!(await confirmDialog({ title: `Delete breach ${b.reference || b.title}?`, danger: true }))) return;
    try {
      await apiCall("DELETE", `/data-breaches/${b.id}`);
      setShowForm(false);
      if (openId === b.id) setOpenId(null);
      reload();
      onChanged();
      toast("Deleted");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to delete", "error");
    }
  }

  const columns: Column<DataBreach>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (b) => <span className="ref">{b.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (b) => <span className="cell-title">{b.title}</span> },
    { key: "breach_type", header: "Type", sortable: true, render: (b) => <Badge tone="info">{cap(b.breach_type)}</Badge> },
    { key: "severity", header: "Severity", sortable: true, render: (b) => <CritBadge value={b.severity} /> },
    { key: "records_affected", header: "Records", sortable: true, render: (b) => <span className="muted">{num(b.records_affected)}</span> },
    { key: "status", header: "Status", sortable: true, render: (b) => <Badge tone={BREACH_STATUS_TONE[b.status] || "neutral"}>{cap(b.status)}</Badge> },
    {
      key: "notification",
      header: "Notification",
      render: (b) =>
        b.notification_overdue ? (
          <Badge tone="critical">72h overdue</Badge>
        ) : b.reported_to_regulator ? (
          <Badge tone="low">Reported</Badge>
        ) : b.notification_required ? (
          <Badge tone="medium">Required</Badge>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: "actions", header: "", render: (b) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(b)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(b)}>Delete</button></div> },
  ];

  const general = (
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
      <Field label="Related incident" help="Link this breach to a record in the incident register.">
        <AsyncSelect
          search={searchIncidents}
          value={bf.incident_id || null}
          selectedLabel={bf.incident_label || undefined}
          onChange={(v, opt) => setBf((p) => ({ ...p, incident_id: v ?? "", incident_label: opt?.label ?? "" }))}
          placeholder="Unlinked"
        />
      </Field>
    </>
  );
  const timing = (
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
  const response = (
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

  return (
    <>
      <DataTable<DataBreach>
        columns={columns}
        fetcher={fetcher}
        rowKey={(b) => b.id}
        onRowClick={(b) => setOpenId(b.id)}
        activeKey={openId}
        searchPlaceholder="Search breaches by title, reference, data categories…"
        emptyMessage="No breaches recorded. Register personal-data breaches to track containment and regulator notification."
        refreshKey={refreshKey}
        toolbarRight={<button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> New breach</button>}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference || ""} ${detail.title}`.trim() : "…"}
        subtitle={detail ? `${cap(detail.status)} · ${cap(detail.breach_type)} · ${num(detail.records_affected)} records${detail.discovered_date ? " · discovered " + detail.discovered_date : ""}` : ""}
        width={720}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              <CritBadge value={detail.severity} />
              <Badge tone={BREACH_STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {detail.notification_overdue && <Badge tone="critical">72h notification overdue</Badge>}
            </div>
            <div className="field-row" style={{ marginBottom: 12 }}>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Data categories</div>
                <strong>{detail.data_categories || "—"}</strong>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Owner</div>
                <strong>{detail.owner || "—"}</strong>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Regulator reported</div>
                <strong>{detail.reported_to_regulator ? (detail.regulator_report_date || "Yes") : "No"}</strong>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12 }}>Subjects notified</div>
                <strong>{detail.subjects_notified ? "Yes" : "No"}</strong>
              </div>
            </div>
            <div style={{ marginBottom: 10 }}>
              <div className="muted" style={{ fontSize: 12 }}>Root cause</div>
              <p style={{ margin: "2px 0 0" }}>{detail.root_cause || "—"}</p>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div className="muted" style={{ fontSize: 12 }}>Remediation</div>
              <p style={{ margin: "2px 0 0" }}>{detail.remediation || "—"}</p>
            </div>
            <div style={{ marginBottom: 16 }}>
              <RelatedChips label="Related incident" items={detail.incident ? [detail.incident] : []} href="/incidents" />
            </div>
            <RecordPanels model="data_breach" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit breach — ${editing.reference || editing.title}` : "New breach"}
          wide
          tabs={[
            { id: "general", label: "General", content: general, required: true },
            { id: "timing", label: "Timing & notification", content: timing },
            { id: "response", label: "Response", content: response },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create breach"}
          footerLeft={
            editing ? (
              <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

// ============================================================= Consent section
function ConsentSection({ onChanged, summary }: { onChanged: () => void; summary: DpSummary | null }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const [editing, setEditing] = useState<ConsentRecord | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cf, setCf] = useState<ConsentForm>(BLANK_CONSENT);
  const setC = <K extends keyof ConsentForm>(k: K, v: ConsentForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  const fetcher = useCallback((qs: string) => apiCall<PagedList<ConsentRecord>>("GET", `/consent-records?${qs}`), []);

  function openNew() {
    setEditing(null);
    setCf(BLANK_CONSENT);
    setError(null);
    setShowForm(true);
  }
  function openEdit(c: ConsentRecord) {
    setEditing(c);
    setCf(fromConsent(c));
    setError(null);
    setShowForm(true);
  }
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = consentPayload(cf);
      if (editing) await apiCall("PATCH", `/consent-records/${editing.id}`, payload);
      else await apiCall("POST", "/consent-records", payload);
      setShowForm(false);
      reload();
      onChanged();
      toast(editing ? "Changes saved" : "Consent record created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save consent record");
    } finally {
      setSaving(false);
    }
  }
  async function remove(c: ConsentRecord) {
    if (!(await confirmDialog({ title: `Delete consent record ${c.reference || c.subject_name}?`, danger: true }))) return;
    try {
      await apiCall("DELETE", `/consent-records/${c.id}`);
      setShowForm(false);
      reload();
      onChanged();
      toast("Deleted");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to delete", "error");
    }
  }

  const columns: Column<ConsentRecord>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "subject_name", header: "Subject", sortable: true, render: (c) => <span className="cell-title">{c.subject_name || "—"}</span> },
    { key: "purpose", header: "Purpose", sortable: true, render: (c) => <span className="muted">{c.purpose || "—"}</span> },
    { key: "lawful_basis", header: "Lawful basis", sortable: true, render: (c) => <span className="muted">{cap(c.lawful_basis)}</span> },
    { key: "channel", header: "Channel", sortable: true, render: (c) => <span className="muted">{c.channel || "—"}</span> },
    { key: "given", header: "Given", render: (c) => <span className="muted">{c.consent_given ? (c.consent_date || "Yes") : "No"}</span> },
    { key: "status", header: "Status", sortable: true, render: (c) => <Badge tone={CONSENT_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge> },
    { key: "actions", header: "", render: (c) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(c)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(c)}>Delete</button></div> },
  ];

  const general = (
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

  return (
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

      <DataTable<ConsentRecord>
        columns={columns}
        fetcher={fetcher}
        rowKey={(c) => c.id}
        onRowClick={openEdit}
        searchPlaceholder="Search consents by subject, purpose, reference…"
        emptyMessage="No consent records yet. Record subject consents, their lawful basis, and withdrawals."
        refreshKey={refreshKey}
        toolbarRight={<button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> New consent</button>}
      />

      {showForm && (
        <FormModal
          title={editing ? `Edit consent — ${editing.reference || editing.subject_name}` : "New consent"}
          wide
          tabs={[{ id: "general", label: "General", content: general }]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create consent"}
          footerLeft={
            editing ? (
              <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

// ================================================================ page ======
type SectionId = "dpia" | "dsar" | "breach" | "consent";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "dpia", label: "DPIA" },
  { id: "dsar", label: "DSAR" },
  { id: "breach", label: "Breach Register" },
  { id: "consent", label: "Consent" },
];

function DataProtectionInner() {
  const [section, setSection] = useState<SectionId>("dpia");
  const [summary, setSummary] = useState<DpSummary | null>(null);

  const loadSummary = useCallback(() => {
    apiCall<DpSummary>("GET", "/data-protection-summary").then(setSummary).catch(() => {});
  }, []);
  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  return (
    <>
      <div className="page-head">
        <h1>Data Protection</h1>
        <p>Pakistan PDPA readiness — impact assessments, subject access requests on a 30-day SLA, the breach register with the 72-hour notification rule, and a consent ledger.</p>
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

      {section === "dpia" && <DpiaSection onChanged={loadSummary} />}
      {section === "dsar" && <DsarSection onChanged={loadSummary} />}
      {section === "breach" && <BreachSection onChanged={loadSummary} />}
      {section === "consent" && <ConsentSection onChanged={loadSummary} summary={summary} />}
    </>
  );
}

export default function DataProtectionPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <DataProtectionInner />
    </Suspense>
  );
}
