"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { confirmDeleteWithImpact } from "@/lib/records";
import type { LookupRef, UserRef } from "@/lib/masterData";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import WorkflowFields from "@/components/WorkflowFields";
import ArchivedRecords from "@/components/ArchivedRecords";
import { Field, TextInput, TextArea, Select, NumberInput, Toggle, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";
import { titleCase } from "@/lib/text";

// ----------------------------------------------------------------- types (inline)
type Ref = { id: string; reference?: string; title?: string; name?: string };

type IncidentStageFull = {
  id: string;
  incident_id: string;
  name: string;
  order_index: number;
  status: string;
  notes: string;
  completed_at: string | null;
};

type RegReport = {
  id: string;
  incident_id: string;
  regulator: string;
  report_type: string;
  deadline: string | null;
  status: string;
  submitted_at: string | null;
  reference: string;
  summary: string;
  /** Legacy text (the picked user's name once a submitter is picked). */
  submitted_by: string;
  submitted_by_id: string | null;
  submitted_by_ref: UserRef | null;
  is_overdue: boolean;
  created_at: string;
};

type IncidentFull = {
  id: string;
  reference: string;
  title: string;
  description: string;
  /** Legacy text columns — hold the picked value's name once an id is set. */
  category: string;
  category_id: string | null;
  category_ref: LookupRef | null;
  classification: string;
  classification_id: string | null;
  classification_ref: LookupRef | null;
  severity: string;
  status: string;
  /** Read-only: moved by the approval lifecycle (WorkflowFields). */
  workflow_status: string;
  assignee: string;
  assignee_id: string | null;
  assignee_ref: UserRef | null;
  reported_by: string;
  reported_by_id: string | null;
  reported_by_ref: UserRef | null;
  impact: string;
  root_cause: string;
  lessons_learned: string;
  cost: number | null;
  detected_at: string | null;
  occurred_at: string | null;
  resolved_at: string | null;
  stage_count: number;
  completed_stages: number;
  lifecycle_complete: boolean;
  current_stage: string | null;
  stages: IncidentStageFull[];
  is_reportable: boolean;
  regulator: string;
  regulator_id: string | null;
  regulator_ref: LookupRef | null;
  regulatory_reports: RegReport[];
  controls: Ref[];
  vendors: Ref[];
  assets: Ref[];
  risks: Ref[];
  created_at: string;
};

// ----------------------------------------------------------------- option helpers
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const SEVERITY = opts(["low", "medium", "high", "critical"]);
const STATUS = opts(["open", "triage", "investigating", "contained", "resolved", "closed"]);
const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
/** The server's four-eyes refusal of a delete ("Segregation of duties: you entered …"). */
const isSodRefusal = (e: unknown) => e instanceof Error && /^segregation of duties/i.test(e.message);

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  open: "high",
  triage: "medium",
  investigating: "medium",
  contained: "info",
  resolved: "low",
  closed: "neutral",
};
const STAGE_TONE: Record<string, "low" | "medium" | "neutral"> = {
  done: "low",
  in_progress: "medium",
  pending: "neutral",
};

const refToOpt = (x: Ref): AsyncOption => ({ value: x.id, label: x.title || x.name || x.reference || x.id });
const personName = (u: UserRef | null, legacy: string) => u?.full_name || u?.email || legacy || "";
const regulatorName = (i: IncidentFull) => i.regulator_ref?.label || i.regulator || "";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <div style={{ marginTop: 2, fontSize: 13 }}>{children}</div>
    </div>
  );
}

// ----------------------------------------------------------------- form state
type FormState = {
  title: string;
  description: string;
  category_id: string | null;
  classification_id: string | null;
  severity: string;
  status: string;
  assignee_id: string | null;
  reported_by_id: string | null;
  is_reportable: boolean;
  regulator_id: string | null;
  detected_at: string;
  occurred_at: string;
  resolved_at: string;
  impact: string;
  root_cause: string;
  lessons_learned: string;
  cost: number | "";
  control_ids: AsyncOption[];
  vendor_ids: AsyncOption[];
  asset_ids: AsyncOption[];
  risk_ids: AsyncOption[];
};

const BLANK: FormState = {
  title: "", description: "", category_id: null, classification_id: null,
  severity: "medium", status: "open",
  assignee_id: null, reported_by_id: null, is_reportable: false, regulator_id: null,
  detected_at: "", occurred_at: "", resolved_at: "",
  impact: "", root_cause: "", lessons_learned: "", cost: "",
  control_ids: [], vendor_ids: [], asset_ids: [], risk_ids: [],
};

function fromIncident(i: IncidentFull): FormState {
  return {
    title: i.title,
    description: i.description || "",
    category_id: i.category_id,
    classification_id: i.classification_id,
    severity: i.severity,
    status: i.status,
    assignee_id: i.assignee_id,
    reported_by_id: i.reported_by_id,
    is_reportable: !!i.is_reportable,
    regulator_id: i.regulator_id,
    detected_at: i.detected_at || "",
    occurred_at: i.occurred_at || "",
    resolved_at: i.resolved_at || "",
    impact: i.impact || "",
    root_cause: i.root_cause || "",
    lessons_learned: i.lessons_learned || "",
    cost: i.cost ?? "",
    control_ids: i.controls.map(refToOpt),
    vendor_ids: i.vendors.map(refToOpt),
    asset_ids: i.assets.map(refToOpt),
    risk_ids: i.risks.map(refToOpt),
  };
}

/** Strip empty-string dates/cost to null so the backend's optional fields stay null. */
function toPayload(f: FormState) {
  return {
    title: f.title,
    description: f.description,
    category_id: f.category_id,
    classification_id: f.classification_id,
    severity: f.severity,
    status: f.status,
    assignee_id: f.assignee_id,
    reported_by_id: f.reported_by_id,
    is_reportable: f.is_reportable,
    regulator_id: f.regulator_id,
    detected_at: f.detected_at || null,
    occurred_at: f.occurred_at || null,
    resolved_at: f.resolved_at || null,
    impact: f.impact,
    root_cause: f.root_cause,
    lessons_learned: f.lessons_learned,
    cost: f.cost === "" ? null : f.cost,
    control_ids: f.control_ids.map((o) => o.value),
    vendor_ids: f.vendor_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
    risk_ids: f.risk_ids.map((o) => o.value),
  };
}

/* ================================================================ page ===== */
function IncidentsInner() {
  const { formatDate, formatMoney, currency } = useFormat();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<IncidentFull | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // filters
  const [fStatus, setFStatus] = useState("");
  const [fSeverity, setFSeverity] = useState("");

  const [editing, setEditing] = useState<IncidentFull | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  /** Regulatory report being marked submitted (inline form under its row). */
  const [submitting, setSubmitting] = useState<{ id: string; reference: string; submitted_by_id: string | null } | null>(null);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchIncidents = useCallback((qs: string) => apiCall<PagedList<IncidentFull>>("GET", `/incidents?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<IncidentFull>("GET", `/incidents/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // server typeahead sources for the form link pickers
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.reference })));
  const searchVendors = (q: string) => apiCall<PagedList<{ id: string; name: string; category: string }>>("GET", `/vendors?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.category })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string; classification: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.classification })));

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(i: IncidentFull) { setEditing(i); setF(fromIncident(i)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<IncidentFull>("PATCH", `/incidents/${editing.id}`, payload);
      else await apiCall<IncidentFull>("POST", "/incidents", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Incident logged");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save incident"); }
    finally { setSaving(false); }
  }

  async function remove(i: IncidentFull) {
    if (!(await confirmDeleteWithImpact("incident", i.id, `${i.reference} ${i.title}`.trim()))) return;
    try {
      await apiCall<void>("DELETE", `/incidents/${i.id}`);
      setShowForm(false);
      if (openId === i.id) setOpenId(null);
      reload(); toast(`Deleted ${i.reference || "incident"}`);
    } catch (e) {
      // A 403 is segregation of duties: the server's message says who may delete it.
      toast(errMsg(e, "Failed to delete incident"), "error");
    }
  }

  async function advance(stageId: string, status: string) {
    if (!detail) return;
    setError(null);
    try {
      await apiCall<IncidentFull>("PATCH", `/incidents/${detail.id}/stages/${stageId}`, { status });
      loadDetail(detail.id); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to update stage"); }
  }

  async function regAction(fn: Promise<unknown>) {
    if (!detail) return;
    setError(null);
    try {
      await fn;
      loadDetail(detail.id); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); }
  }
  function generateRegReports() {
    if (!detail) return;
    regAction(apiCall("POST", `/incidents/${detail.id}/regulatory-reports/generate`));
  }
  function markReportSubmitted() {
    if (!submitting) return;
    const { id, reference, submitted_by_id } = submitting;
    setSubmitting(null);
    regAction(apiCall("PATCH", `/regulatory-reports/${id}`, { status: "submitted", reference: reference.trim(), submitted_by_id }));
  }
  async function deleteRegReport(r: RegReport) {
    const ok = await confirmDialog({
      title: `Remove the ${cap(r.report_type).toLowerCase()} for ${r.regulator || "the regulator"}?`,
      message: "The report and its deadline are deleted. Generate the reports again to recreate it.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    regAction(apiCall("DELETE", `/regulatory-reports/${r.id}`));
  }

  const linkCount = (i: IncidentFull) =>
    i.controls.length + i.vendors.length + i.assets.length + i.risks.length;


  /* Inline relation chips linking to each record's own page. */
  const labelOf = (x: { id: string; label?: string; name?: string; title?: string; reference?: string }) =>
    x.label || x.name || x.title || x.reference || x.id;
  const linkChips = (items: { id: string; label?: string; name?: string; title?: string; reference?: string }[] | undefined, href: string) =>
    items && items.length ? (
      <div className="chips" onClick={(e) => e.stopPropagation()}>
        {items.map((x) => <Link key={x.id} className="chip" href={`${href}?id=${x.id}`}>{labelOf(x)}</Link>)}
      </div>
    ) : <span className="muted">—</span>;
  const names = (items: { id: string; label?: string; name?: string; title?: string; reference?: string }[] | undefined) =>
    (items ?? []).map(labelOf).join(", ");

  const columns: Column<IncidentFull>[] = [
    { key: "reference", header: "Ref", sortable: true, locked: true, render: (i) => <span className="ref">{i.reference}</span> },
    { key: "title", header: "Title", sortable: true, locked: true, render: (i) => <span className="cell-title">{i.title}</span> },
    { key: "category", header: "Type", sortable: true, render: (i) => <span className="muted">{i.category_ref?.label || i.category || "—"}</span>, text: (i) => i.category_ref?.label || i.category || "" },
    { key: "classification", header: "Classification", hidden: true, render: (i) => <span className="muted">{i.classification_ref?.label || i.classification || "—"}</span>, text: (i) => i.classification_ref?.label || i.classification || "" },
    { key: "severity", header: "Severity", sortable: true, render: (i) => <Severity value={i.severity} />, text: (i) => cap(i.severity) },
    { key: "status", header: "Status", sortable: true, render: (i) => <Badge tone={STATUS_TONE[i.status] || "neutral"}>{cap(i.status)}</Badge>, text: (i) => cap(i.status) },
    { key: "assignee", header: "Owner", render: (i) => <span className="muted"><UserName user={i.assignee_ref} fallback={i.assignee} /></span>, text: (i) => personName(i.assignee_ref, i.assignee) },
    { key: "reported_by", header: "Reported by", hidden: true, render: (i) => <span className="muted"><UserName user={i.reported_by_ref} fallback={i.reported_by} /></span>, text: (i) => personName(i.reported_by_ref, i.reported_by) },
    { key: "detected_at", header: "Detected", sortable: true, render: (i) => <span className="muted">{formatDate(i.detected_at)}</span>, text: (i) => (i.detected_at ? formatDate(i.detected_at) : "") },
    { key: "occurred_at", header: "Occurred", hidden: true, render: (i) => <span className="muted">{formatDate(i.occurred_at)}</span>, text: (i) => (i.occurred_at ? formatDate(i.occurred_at) : "") },
    { key: "resolved_at", header: "Resolved", hidden: true, render: (i) => <span className="muted">{formatDate(i.resolved_at)}</span>, text: (i) => (i.resolved_at ? formatDate(i.resolved_at) : "") },
    { key: "is_reportable", header: "Reportable", hidden: true, render: (i) => (i.is_reportable ? <Badge tone="high">Reportable{regulatorName(i) ? ` · ${regulatorName(i)}` : ""}</Badge> : <span className="muted">—</span>), text: (i) => i.is_reportable ? `Yes${regulatorName(i) ? ` (${regulatorName(i)})` : ""}` : "No" },
    { key: "cost", header: "Cost", hidden: true, align: "right", render: (i) => <span className="muted">{i.cost != null ? formatMoney(i.cost) : "—"}</span>, text: (i) => i.cost != null ? formatMoney(i.cost) : "" },
    { key: "assets", header: "Assets", render: (i) => linkChips(i.assets, "/information-assets"), text: (i) => names(i.assets) },
    { key: "controls", header: "Controls", hidden: true, render: (i) => linkChips(i.controls, "/controls"), text: (i) => names(i.controls) },
    { key: "risks", header: "Risks", hidden: true, render: (i) => linkChips(i.risks, "/risks"), text: (i) => names(i.risks) },
    { key: "vendors", header: "Third parties", hidden: true, render: (i) => linkChips(i.vendors, "/vendors"), text: (i) => names(i.vendors) },
    {
      key: "lifecycle", header: "Lifecycle", width: 150, render: (i) => (
        i.lifecycle_complete ? (
          <Badge tone="low"><IconCheck width={11} height={11} /> complete</Badge>
        ) : (
          <>
            <div className="progress"><span style={{ width: `${(i.completed_stages / (i.stage_count || 1)) * 100}%` }} /></div>
            <span className="muted" style={{ fontSize: 11 }}>{i.current_stage || "—"} ({i.completed_stages}/{i.stage_count})</span>
          </>
        )
      ),
      text: (i) => i.lifecycle_complete ? "complete" : `${i.completed_stages}/${i.stage_count}`,
    },
    { key: "workflow_status", header: "Workflow", hidden: true, render: (i) => <span className="muted">{cap(i.workflow_status)}</span>, text: (i) => cap(i.workflow_status) },
    { key: "created_at", header: "Logged", hidden: true, render: (i) => <span className="muted">{formatDate(i.created_at)}</span>, text: (i) => (i.created_at ? formatDate(i.created_at) : "") },
    { key: "actions", header: "", render: (i) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(i)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(i)}>Delete</button></div> },
  ];

  /** Delete every selected incident after one confirmation, then drop the selection. */
  async function removeMany(rowsToDelete: { id: string }[], clear: () => void) {
    const ok = await confirmDialog({
      title: `Delete ${rowsToDelete.length} incident${rowsToDelete.length === 1 ? "" : "s"}?`,
      message: "They are archived, not erased: restore them from Archived until the retention period ends. Links from other records are kept and the activity trail records who removed them.",
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    let deleted = 0;
    let refused = 0;
    const failures: string[] = [];
    for (const r of rowsToDelete) {
      try {
        await apiCall("DELETE", `/incidents/${r.id}`);
        deleted += 1;
      } catch (e) {
        if (isSodRefusal(e)) refused += 1;
        else failures.push(errMsg(e, "failed"));
      }
    }
    clear();
    reload();
    const parts = [`Deleted ${deleted}`];
    if (refused) parts.push(`${refused} need${refused === 1 ? "s" : ""} another user to delete ${refused === 1 ? "it" : "them"}`);
    if (failures.length) parts.push(`${failures.length} failed (${failures[0]})`);
    toast(parts.join("; "), refused || failures.length ? "error" : "success");
  }

  const filters = { status: fStatus || undefined, severity: fSeverity || undefined };

  // ------------------------------------------------------------- tabs
  const generalTab = (
    <>
      <Field label="Title" required help="A short, descriptive name for the incident.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Suspicious login from unknown IP" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What happened, who detected it, and the initial scope." />
      </Field>
      <div className="field-row">
        <Field label="Type / Category">
          <LookupSelect
            lookupKey="incident_type"
            value={f.category_id}
            onChange={(id) => set("category_id", id)}
            legacyText={editing && !editing.category_id ? editing.category : null}
            allowCreate
          />
        </Field>
        <Field label="Classification" help="Sensitivity of the affected information (e.g. Confidential).">
          <LookupSelect
            lookupKey="incident_classification"
            value={f.classification_id}
            onChange={(id) => set("classification_id", id)}
            legacyText={editing && !editing.classification_id ? editing.classification : null}
            allowCreate
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Severity">
          <Select value={f.severity} onChange={(v) => set("severity", v)} options={SEVERITY} />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Owner / Handler" help="Person responsible for the response.">
          <UserPicker
            value={f.assignee_id}
            onChange={(id) => set("assignee_id", id)}
            selected={editing?.assignee_ref ?? null}
            legacyText={editing && !editing.assignee_id ? editing.assignee : null}
            placeholder="Incident handler…"
          />
        </Field>
        <Field label="Reported By">
          <UserPicker
            value={f.reported_by_id}
            onChange={(id) => set("reported_by_id", id)}
            selected={editing?.reported_by_ref ?? null}
            legacyText={editing && !editing.reported_by_id ? editing.reported_by : null}
            placeholder="Who reported it…"
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Reportable" help="Must be notified to a regulator (e.g. SBP) within its reporting deadlines.">
          <Toggle checked={f.is_reportable} onChange={(v) => set("is_reportable", v)} label="Reportable to a regulator" />
        </Field>
        <Field label="Regulator" help="Who the incident is reported to; the reporting panel generates their submissions.">
          <LookupSelect
            lookupKey="regulator"
            value={f.regulator_id}
            onChange={(id) => set("regulator_id", id)}
            legacyText={editing && !editing.regulator_id ? editing.regulator : null}
            placeholder="Choose a regulator…"
          />
        </Field>
      </div>
    </>
  );

  const timelineTab = (
    <>
      <div className="field-row">
        <Field label="Occurred At" help="When the incident actually took place.">
          <TextInput type="date" value={f.occurred_at} onChange={(v) => set("occurred_at", v)} />
        </Field>
        <Field label="Detected At" help="When the incident was first discovered.">
          <TextInput type="date" value={f.detected_at} onChange={(v) => set("detected_at", v)} />
        </Field>
        <Field label="Resolved At" help="When response work was completed.">
          <TextInput type="date" value={f.resolved_at} onChange={(v) => set("resolved_at", v)} />
        </Field>
      </div>
    </>
  );

  const analysisTab = (
    <>
      <Field label="Impact" help="Business / operational impact of the incident.">
        <TextArea value={f.impact} onChange={(v) => set("impact", v)} rows={3} placeholder="Systems affected, data exposed, downtime, etc." />
      </Field>
      <Field label={`Estimated Cost (${currency})`} help="Financial impact in the organisation's reporting currency.">
        <NumberInput value={f.cost} onChange={(v) => set("cost", v)} min={0} step={100} placeholder="0" />
      </Field>
      <Field label="Root Cause">
        <RichText value={f.root_cause} onChange={(v) => set("root_cause", v)} placeholder="Describe the underlying cause…" />
      </Field>
      <Field label="Lessons Learned">
        <RichText value={f.lessons_learned} onChange={(v) => set("lessons_learned", v)} placeholder="What will change to prevent recurrence…" />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Related Controls" help="Controls that failed, were tested, or mitigate this incident.">
        <AsyncMultiSelect search={searchControls} value={f.control_ids} onChange={(v) => set("control_ids", v)} />
      </Field>
      <Field label="Related Vendors" help="Third parties involved in or affected by the incident.">
        <AsyncMultiSelect search={searchVendors} value={f.vendor_ids} onChange={(v) => set("vendor_ids", v)} />
      </Field>
      <Field label="Related Risks" help="Risks this incident realised or relates to.">
        <AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} />
      </Field>
      <Field label="Affected Assets" help="Assets impacted by the incident.">
        <AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Security Operations</h1>
          <p>Log, triage and resolve security incidents through their response lifecycle.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="incidents" label="Incidents" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add incident
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<IncidentFull>
        tableKey="incidents"
        statusModel="incident"
        bulkActions={(rows, clear) => (
          <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
        )}
        columns={columns}
        fetcher={fetchIncidents}
        rowKey={(i) => i.id}
        onRowClick={(i) => setOpenId(i.id)}
        activeKey={openId}
        searchPlaceholder="Search incidents by title or reference…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        filters={filters}
        toolbarRight={
          <>
            <select className="select" style={{ maxWidth: 170 }} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
              <option value="">All statuses</option>
              {STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <select className="select" style={{ maxWidth: 150 }} value={fSeverity} onChange={(e) => setFSeverity(e.target.value)}>
              <option value="">All severities</option>
              {SEVERITY.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <ArchivedRecords entityType="incident" noun="incidents" refreshKey={refreshKey} onRestored={reload} />
          </>
        }
        emptyMessage="No incidents yet. Log your first security incident to begin tracking."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        aside={detail ? <RecordPanels model="incident" entityId={detail.id} /> : null}
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? `${cap(detail.status)} · ${personName(detail.assignee_ref, detail.assignee) || "no owner"}` : ""}
        width={760}
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
              <Severity value={detail.severity} />
              <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {linkCount(detail) > 0 && <Badge tone="neutral" plain>{linkCount(detail)} links</Badge>}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12, padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <Fact label="Type">{detail.category_ref?.label || detail.category || <span className="muted">—</span>}</Fact>
              <Fact label="Classification">{detail.classification_ref?.label || detail.classification || <span className="muted">—</span>}</Fact>
              <Fact label="Owner / handler"><UserName user={detail.assignee_ref} fallback={detail.assignee} /></Fact>
              <Fact label="Reported by"><UserName user={detail.reported_by_ref} fallback={detail.reported_by} /></Fact>
              <Fact label="Occurred">{formatDate(detail.occurred_at)}</Fact>
              <Fact label="Detected">{formatDate(detail.detected_at)}</Fact>
              <Fact label="Resolved">{formatDate(detail.resolved_at)}</Fact>
              <Fact label="Estimated cost">{detail.cost != null ? formatMoney(detail.cost) : <span className="muted">—</span>}</Fact>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Approval</h3></div>
              <div className="card-pad">
                <WorkflowFields entityType="incident" entityId={detail.id} onChanged={() => { loadDetail(detail.id); reload(); }} />
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head">
                <h3>Response lifecycle</h3>
                <span className="sub">{detail.completed_stages}/{detail.stage_count} stages done</span>
              </div>
              <div className="card-pad">
                {detail.stages.map((s) => (
                  <div key={s.id} className="activity-item" style={{ alignItems: "center" }}>
                    <span style={{ width: 24, textAlign: "center", color: "var(--faint)" }}>{s.order_index + 1}</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{s.name}</div>
                      {s.completed_at && <div className="when">completed {formatDate(s.completed_at)}</div>}
                    </div>
                    <Badge tone={STAGE_TONE[s.status] || "neutral"}>{s.status.replace(/_/g, " ")}</Badge>
                    <div style={{ display: "flex", gap: 6 }}>
                      {s.status === "pending" && <button className="btn secondary sm" onClick={() => advance(s.id, "in_progress")}>Start</button>}
                      {s.status !== "done" && <button className="btn sm" onClick={() => advance(s.id, "done")}>Done</button>}
                      {s.status === "done" && <button className="btn secondary sm" onClick={() => advance(s.id, "in_progress")}>Reopen</button>}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head">
                <h3>Regulatory reporting</h3>
                <span className="sub">
                  {detail.is_reportable ? `Reportable to ${regulatorName(detail) || "regulator"}` : "Not flagged reportable"}
                </span>
              </div>
              <div className="card-pad">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, gap: 10 }}>
                  <p className="muted" style={{ fontSize: 12.5, margin: 0, maxWidth: 460 }}>
                    Generate the standard {regulatorName(detail) || "SBP"} submissions (initial notification + final report)
                    with SLA deadlines computed from the detection date.
                  </p>
                  <button className="btn secondary sm" onClick={generateRegReports}>Generate {regulatorName(detail) || "SBP"} reports</button>
                </div>
                {detail.regulatory_reports.length > 0 ? (
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Regulator</th><th>Report</th><th>Deadline</th><th>Status</th><th>Submitted</th><th>Reference</th><th></th></tr></thead>
                      <tbody>
                        {detail.regulatory_reports.map((r) => (
                          <RegReportRow
                            key={r.id}
                            r={r}
                            formatDate={formatDate}
                            submitting={submitting?.id === r.id ? submitting : null}
                            onStartSubmit={() => setSubmitting({ id: r.id, reference: r.reference || "", submitted_by_id: r.submitted_by_id })}
                            onChangeSubmit={(patch) => setSubmitting((p) => (p ? { ...p, ...patch } : p))}
                            onCancelSubmit={() => setSubmitting(null)}
                            onConfirmSubmit={markReportSubmitted}
                            onRemove={() => deleteRegReport(r)}
                          />
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <span className="muted" style={{ fontSize: 12.5 }}>No regulatory reports yet.</span>
                )}
              </div>
            </div>

          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit incident — ${editing.reference}` : "Add item (Incidents)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "timeline", label: "Timeline", content: timelineTab },
            { id: "analysis", label: "Analysis", content: analysisTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create incident"}
          footerLeft={
            editing ? (
              <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

/* One regulatory report row, plus the inline "mark submitted" form under it. */
function RegReportRow({
  r,
  formatDate,
  submitting,
  onStartSubmit,
  onChangeSubmit,
  onCancelSubmit,
  onConfirmSubmit,
  onRemove,
}: {
  r: RegReport;
  formatDate: (v: string | null) => string;
  submitting: { reference: string; submitted_by_id: string | null } | null;
  onStartSubmit: () => void;
  onChangeSubmit: (patch: { reference?: string; submitted_by_id?: string | null }) => void;
  onCancelSubmit: () => void;
  onConfirmSubmit: () => void;
  onRemove: () => void;
}) {
  return (
    <>
      <tr>
        <td className="muted">{r.regulator}</td>
        <td className="cell-title">{cap(r.report_type)}</td>
        <td className="muted">
          {formatDate(r.deadline)}
          {r.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="critical">overdue</Badge></span>}
        </td>
        <td><Badge tone={r.status === "pending" ? "medium" : "low"}>{cap(r.status)}</Badge></td>
        <td className="muted">
          {r.submitted_at ? (
            <>
              {formatDate(r.submitted_at)}
              {(r.submitted_by_ref || r.submitted_by) && (
                <div style={{ fontSize: 12 }}>by <UserName user={r.submitted_by_ref} fallback={r.submitted_by} /></div>
              )}
            </>
          ) : "—"}
        </td>
        <td className="muted">{r.reference || "—"}</td>
        <td>
          <div style={{ display: "flex", gap: 6 }}>
            {r.status === "pending" && !submitting && <button className="btn sm" onClick={onStartSubmit}>Mark submitted</button>}
            <button className="btn secondary sm" onClick={onRemove}>Remove</button>
          </div>
        </td>
      </tr>
      {submitting && (
        <tr>
          <td colSpan={7}>
            <form
              style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}
              onSubmit={(ev) => { ev.preventDefault(); onConfirmSubmit(); }}
            >
              <div style={{ flex: "1 1 180px" }}>
                <label className="label" htmlFor={`rr-ref-${r.id}`}>Regulator acknowledgement reference</label>
                <input
                  id={`rr-ref-${r.id}`}
                  className="input"
                  value={submitting.reference}
                  onChange={(ev) => onChangeSubmit({ reference: ev.target.value })}
                  placeholder="Optional"
                />
              </div>
              <div style={{ flex: "1 1 200px" }}>
                <label className="label">Submitted by</label>
                <UserPicker
                  value={submitting.submitted_by_id}
                  selected={r.submitted_by_ref}
                  onChange={(id) => onChangeSubmit({ submitted_by_id: id })}
                  placeholder="Who submitted it…"
                />
              </div>
              <button className="btn sm" type="submit">Mark submitted</button>
              <button className="btn secondary sm" type="button" onClick={onCancelSubmit}>Cancel</button>
            </form>
          </td>
        </tr>
      )}
    </>
  );
}

export default function IncidentsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <IncidentsInner />
    </Suspense>
  );
}
