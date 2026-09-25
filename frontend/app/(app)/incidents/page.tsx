"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { timezoneOffset, useFormat } from "@/lib/format";
import { fromZonedInput, toZonedInput } from "@/lib/zonedInput";
import { confirmDeleteWithImpact } from "@/lib/records";
import type { LookupRef, UserRef } from "@/lib/masterData";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFilterParams, type FilterSpec } from "@/lib/useFilterParams";
import DataTable, { type Column } from "@/components/DataTable";
import BulkEditBar from "@/components/BulkEditBar";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText, { RichTextView } from "@/components/RichText";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import ArchivedRecords from "@/components/ArchivedRecords";
import { useCustomFieldFacts } from "@/components/CustomFieldsPanel";
import { useCustomFieldForm } from "@/components/useCustomFieldForm";
import {
  Fact, FactGrid, FactList, LabelledSearch, OpenPoints, PrimaryAction, RecordSection, RelatedGroups, SectionNav, SummaryBand,
  approvalHintFor, approvalMetaItem, relatedCount, rowAction, rowLabel, useRecordCtx, useRecordGovernanceData, useRecordSections,
  withBaseMoreItems, type MetaItem, type RelatedGroup,
} from "@/components/record";
import { useHasPermission } from "@/lib/tenantSettings";
import { Field, TextInput, TextArea, Select, NumberInput, Toggle, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";
import { titleCase } from "@/lib/text";
import { sentenceCase, textOnlyPerson } from "@/lib/record/text";
import { htmlToText } from "@/lib/sanitize";
import {
  INCIDENT_CLEAR_TEXT, incidentDurationNote, incidentGenerateHint, incidentHeadline, incidentOpenPoints, incidentRegulatorName,
  incidentTiles, type IncidentInput,
} from "@/lib/record/incident";
import type { PointAction } from "@/lib/record/types";

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
  regulator_id?: string | null;
  regulator_ref?: LookupRef | null;
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
  /** Timestamps (ISO 8601 with offset) since phase 2 — shown with formatDateTime. */
  detected_at: string | null;
  occurred_at: string | null;
  contained_at: string | null;
  resolved_at: string | null;
  customers_affected: number | null;
  records_affected: number | null;
  /** Nothing was lost: no cost, left out of loss totals, no loss event. */
  near_miss: boolean;
  /** Flagging it opens (once) a linked data-breach record and notifies the DPO role. */
  personal_data_breach: boolean;
  /** Regulator-notification clock, read off the initial report. */
  notification_deadline: string | null;
  notified_at: string | null;
  regulator_reference: string | null;
  /** Hours to the deadline (to the submission once made); negative when late. */
  hours_to_deadline: number | null;
  notified_on_time: boolean | null;
  mttd_hours: number | null;
  mttc_hours: number | null;
  mttr_hours: number | null;
  loss_events: LossRef[];
  data_breaches: Ref[];
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

type LossRef = {
  id: string;
  reference: string;
  title: string;
  status: string;
  gross_loss: number;
  recovery: number;
  net_loss: number;
  currency: string;
  occurrence_date: string | null;
};

type IncidentSummary = {
  total: number;
  open: number;
  reportable: number;
  notifications_pending: number;
  notifications_overdue: number;
  notified_on_time: number;
  notified_late: number;
  near_misses: number;
  personal_data_breaches: number;
  total_cost: number;
  response_times: {
    mttd_hours: number | null; mttd_count: number;
    mttc_hours: number | null; mttc_count: number;
    mttr_hours: number | null; mttr_count: number;
  };
};

// ----------------------------------------------------------------- option helpers
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const SEVERITY = opts(["low", "medium", "high", "critical"]);
const STATUS = opts(["open", "triage", "investigating", "contained", "resolved", "closed"]);
/** Register filters, kept in the URL so a link can open the list already filtered.
 *  `open=true` is every incident not resolved or closed — the dashboard's "open
 *  incidents"; `status=open` is the literal Open status. */
const INCIDENT_FILTERS = {
  status: ["open", "triage", "investigating", "contained", "resolved", "closed"],
  open: "boolean",
  severity: ["low", "medium", "high", "critical"],
  is_reportable: "boolean",
} as const satisfies FilterSpec;
const ALL_OPEN = "__open";
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
const SEV_TONE: Record<string, "low" | "medium" | "high" | "critical"> = { low: "low", medium: "medium", high: "high", critical: "critical" };
const STAGE_TONE: Record<string, "low" | "medium" | "neutral"> = {
  done: "low",
  in_progress: "medium",
  pending: "neutral",
};

const refToOpt = (x: Ref): AsyncOption => ({ value: x.id, label: x.title || x.name || x.reference || x.id });
const personName = (u: UserRef | null, legacy: string) => u?.full_name || u?.email || legacy || "";
const regulatorName = (i: IncidentFull) => incidentRegulatorName(i);

/** "45 m", "5 h 12 m", "2 d 4 h" — a duration given in hours (sign ignored). */
function duration(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || !Number.isFinite(hours)) return "—";
  const mins = Math.round(Math.abs(hours) * 60);
  if (mins < 60) return `${mins} m`;
  const h = Math.floor(mins / 60);
  if (h < 48) return `${h} h${mins % 60 ? ` ${mins % 60} m` : ""}`;
  return `${Math.floor(h / 24)} d${h % 24 ? ` ${h % 24} h` : ""}`;
}

/** Hours between two ISO timestamps (null when either is blank or the order is wrong). */
function hoursBetween(a: string | null, b: string | null): number | null {
  if (!a || !b) return null;
  const d = (new Date(b).getTime() - new Date(a).getTime()) / 3_600_000;
  return Number.isFinite(d) && d >= 0 ? d : null;
}

/** Re-render every `ms` so a countdown stays live. */
function useNow(ms = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** The regulator-notification position as a badge: live countdown while pending,
 *  on time / late once notified. */
function NotificationBadge({ i }: { i: IncidentFull }) {
  const now = useNow();
  if (!i.notification_deadline) return <span className="muted">—</span>;
  if (i.notified_at) {
    return i.notified_on_time
      ? <Badge tone="low" asIs>Notified on time</Badge>
      : <Badge tone="critical" asIs>Notified late{i.hours_to_deadline != null ? ` · ${duration(i.hours_to_deadline)}` : ""}</Badge>;
  }
  const left = (new Date(i.notification_deadline).getTime() - now) / 3_600_000;
  if (left < 0) return <Badge tone="critical" asIs>Overdue by {duration(left)}</Badge>;
  return <Badge tone={left < 6 ? "high" : "medium"} asIs>Due in {duration(left)}</Badge>;
}

// ----------------------------------------------------------------- record copy
/* The incident's judgement wording (tiles, open points, headline, the regulator clock)
   lives in lib/record/incident.ts, pinned by lib/record/__fixtures__/incident-*.json. Stored
   rich text (root cause, lessons learned) renders through RichTextView (lib/sanitize). */

/** Labels of the built-in fields a custom field could duplicate (admins get a note). */
const INCIDENT_BUILT_IN_LABELS = ["Handler", "Owner", "Severity", "Status", "Type", "Category", "Classification", "Impact", "Root cause"];

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
  /** datetime-local values ("YYYY-MM-DDTHH:mm") in the organisation's timezone. */
  detected_at: string;
  occurred_at: string;
  contained_at: string;
  resolved_at: string;
  notified_at: string;
  regulator_reference: string;
  impact: string;
  root_cause: string;
  lessons_learned: string;
  cost: number | "";
  customers_affected: number | "";
  records_affected: number | "";
  near_miss: boolean;
  personal_data_breach: boolean;
  control_ids: AsyncOption[];
  vendor_ids: AsyncOption[];
  asset_ids: AsyncOption[];
  risk_ids: AsyncOption[];
};

const BLANK: FormState = {
  title: "", description: "", category_id: null, classification_id: null,
  severity: "medium", status: "open",
  assignee_id: null, reported_by_id: null, is_reportable: false, regulator_id: null,
  detected_at: "", occurred_at: "", contained_at: "", resolved_at: "",
  notified_at: "", regulator_reference: "",
  impact: "", root_cause: "", lessons_learned: "", cost: "",
  customers_affected: "", records_affected: "", near_miss: false, personal_data_breach: false,
  control_ids: [], vendor_ids: [], asset_ids: [], risk_ids: [],
};

function fromIncident(i: IncidentFull, tz: string): FormState {
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
    detected_at: toZonedInput(i.detected_at, tz),
    occurred_at: toZonedInput(i.occurred_at, tz),
    contained_at: toZonedInput(i.contained_at, tz),
    resolved_at: toZonedInput(i.resolved_at, tz),
    notified_at: toZonedInput(i.notified_at, tz),
    regulator_reference: i.regulator_reference || "",
    impact: i.impact || "",
    root_cause: i.root_cause || "",
    lessons_learned: i.lessons_learned || "",
    cost: i.cost ?? "",
    customers_affected: i.customers_affected ?? "",
    records_affected: i.records_affected ?? "",
    near_miss: !!i.near_miss,
    personal_data_breach: !!i.personal_data_breach,
    control_ids: i.controls.map(refToOpt),
    vendor_ids: i.vendors.map(refToOpt),
    asset_ids: i.assets.map(refToOpt),
    risk_ids: i.risks.map(refToOpt),
  };
}

/** Strip empty strings to null so the backend's optional fields stay null; timestamps
 *  go with the organisation's UTC offset. The notification lives on the initial report,
 *  so it is only sent for a reportable incident. */
function toPayload(f: FormState, tz: string) {
  const notification = f.is_reportable
    ? { notified_at: fromZonedInput(f.notified_at, tz), regulator_reference: f.regulator_reference.trim() }
    : {};
  return {
    ...notification,
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
    detected_at: fromZonedInput(f.detected_at, tz),
    occurred_at: fromZonedInput(f.occurred_at, tz),
    contained_at: fromZonedInput(f.contained_at, tz),
    resolved_at: fromZonedInput(f.resolved_at, tz),
    impact: f.impact,
    root_cause: f.root_cause,
    lessons_learned: f.lessons_learned,
    cost: f.near_miss || f.cost === "" ? null : f.cost,
    customers_affected: f.customers_affected === "" ? null : f.customers_affected,
    records_affected: f.records_affected === "" ? null : f.records_affected,
    near_miss: f.near_miss,
    personal_data_breach: f.personal_data_breach,
    control_ids: f.control_ids.map((o) => o.value),
    vendor_ids: f.vendor_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
    risk_ids: f.risk_ids.map((o) => o.value),
  };
}

/* ================================================================ page ===== */
function IncidentsInner() {
  const { formatDate, formatDateTime, formatMoney, currency, settings } = useFormat();
  const tz = settings.timezone;
  const tzLabel = `${tz.replace(/_/g, " ")}${timezoneOffset(tz) ? ` · ${timezoneOffset(tz)}` : ""}`;
  const [summary, setSummary] = useState<IncidentSummary | null>(null);
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<IncidentFull | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // filters (in the URL: see INCIDENT_FILTERS)
  const filterParams = useFilterParams(INCIDENT_FILTERS);
  const fv = filterParams.values;

  const [editing, setEditing] = useState<IncidentFull | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  /** Regulatory report being marked submitted (inline form under its row). */
  const [submitting, setSubmitting] = useState<{ id: string; reference: string; submitted_by_id: string | null } | null>(null);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  useEffect(() => {
    apiCall<IncidentSummary>("GET", "/incidents/summary").then(setSummary).catch(() => setSummary(null));
  }, [refreshKey]);
  const fetchIncidents = useCallback((qs: string) => apiCall<PagedList<IncidentFull>>("GET", `/incidents?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<IncidentFull>("GET", `/incidents/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // ---- the record page (dossier, record-page-spec §4.7) ----
  const gov = useRecordGovernanceData("incident", detail?.id ?? null, { statusRulesModel: "incident" });
  const canWrite = useHasPermission("incident:write");
  const nowMs = useNow(); // the notification countdown in the band and open points stays live
  const ctx = useRecordCtx(gov, canWrite, new Date(nowMs));
  const sections = useRecordSections();
  const cfForm = useCustomFieldForm("incident");
  const cf = useCustomFieldFacts("incident", detail?.id, { builtInLabels: INCIDENT_BUILT_IN_LABELS });
  /** FormModal tab to open on (a header gap, an open point or a "Fill in"). */
  const [editTab, setEditTab] = useState<string | undefined>(undefined);
  /** After any change: the governance (primary, sign-off, rules), the record, the list. */
  const refresh = () => {
    void gov.reload();
    if (openId) loadDetail(openId);
    reload();
  };

  // server typeahead sources for the form link pickers
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.reference })));
  const searchVendors = (q: string) => apiCall<PagedList<{ id: string; name: string; category: string }>>("GET", `/vendors?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.category })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string; classification: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.classification })));

  function openNew() { setEditing(null); setF(BLANK); cfForm.start(null); setError(null); setEditTab(undefined); setShowForm(true); }
  function openEdit(i: IncidentFull, tab?: string) { setEditing(i); setF(fromIncident(i, tz)); cfForm.start(i.id); setError(null); setEditTab(tab); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f, tz);
      const saved = editing
        ? await apiCall<IncidentFull>("PATCH", `/incidents/${editing.id}`, payload)
        : await apiCall<IncidentFull>("POST", "/incidents", payload);
      await cfForm.save(saved.id);
      setShowForm(false); refresh(); void cf.reload();
      toast(editing ? "Changes saved" : "Incident logged");
      if (f.personal_data_breach && !editing?.personal_data_breach) toast("Personal data breach: a breach record was opened in Data Protection");
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
    try {
      await apiCall<IncidentFull>("PATCH", `/incidents/${detail.id}/stages/${stageId}`, { status });
      refresh();
    } catch (e) { toast(errMsg(e, "Failed to update stage"), "error"); }
  }

  async function regAction(fn: Promise<unknown>) {
    if (!detail) return;
    try {
      await fn;
      refresh();
    } catch (e) { toast(errMsg(e, "Action failed"), "error"); }
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

  async function createLossEvent() {
    if (!detail) return;
    const ok = await confirmDialog({
      title: `Record a loss event for ${detail.reference}?`,
      message:
        `A loss event is added to the operational loss database, pre-filled from this incident: ` +
        `gross loss ${detail.cost != null ? formatMoney(detail.cost) : "0 (no cost recorded)"}, ` +
        `occurrence and discovery dates, the handler, root cause and linked risks. Edit it under Operational Risk → Loss Database.`,
      confirmLabel: "Create loss event",
    });
    if (!ok) return;
    setError(null);
    try {
      await apiCall<IncidentFull>("POST", `/incidents/${detail.id}/loss-event`, {});
      refresh(); toast("Loss event created");
    } catch (e) { toast(errMsg(e, "Failed to create the loss event"), "error"); }
  }

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
    { key: "detected_at", header: "Detected", sortable: true, render: (i) => <span className="muted">{formatDateTime(i.detected_at)}</span>, text: (i) => (i.detected_at ? formatDateTime(i.detected_at) : "") },
    { key: "occurred_at", header: "Occurred", sortable: true, hidden: true, render: (i) => <span className="muted">{formatDateTime(i.occurred_at)}</span>, text: (i) => (i.occurred_at ? formatDateTime(i.occurred_at) : "") },
    { key: "contained_at", header: "Contained", hidden: true, render: (i) => <span className="muted">{formatDateTime(i.contained_at)}</span>, text: (i) => (i.contained_at ? formatDateTime(i.contained_at) : "") },
    { key: "resolved_at", header: "Resolved", sortable: true, hidden: true, render: (i) => <span className="muted">{formatDateTime(i.resolved_at)}</span>, text: (i) => (i.resolved_at ? formatDateTime(i.resolved_at) : "") },
    { key: "is_reportable", header: "Reportable", hidden: true, render: (i) => (i.is_reportable ? <Badge tone="high">Reportable{regulatorName(i) ? ` · ${regulatorName(i)}` : ""}</Badge> : <span className="muted">—</span>), text: (i) => i.is_reportable ? `Yes${regulatorName(i) ? ` (${regulatorName(i)})` : ""}` : "No" },
    { key: "notification", header: "Regulator notification", render: (i) => <NotificationBadge i={i} />, text: (i) => i.notification_deadline ? (i.notified_at ? (i.notified_on_time ? "Notified on time" : "Notified late") : `Due ${formatDateTime(i.notification_deadline)}`) : "" },
    { key: "flags", header: "Flags", hidden: true, render: (i) => (i.near_miss || i.personal_data_breach) ? <div className="chips">{i.near_miss && <Badge tone="info">Near miss</Badge>}{i.personal_data_breach && <Badge tone="high">Personal data</Badge>}</div> : <span className="muted">—</span>, text: (i) => [i.near_miss && "Near miss", i.personal_data_breach && "Personal data breach"].filter(Boolean).join(", ") },
    { key: "customers_affected", header: "Customers affected", hidden: true, align: "right", render: (i) => <span className="muted">{i.customers_affected != null ? i.customers_affected.toLocaleString() : "—"}</span>, text: (i) => i.customers_affected != null ? String(i.customers_affected) : "" },
    { key: "cost", header: "Cost", hidden: true, align: "right", render: (i) => <span className="muted">{i.near_miss ? "Near miss" : i.cost != null ? formatMoney(i.cost) : "—"}</span>, text: (i) => i.near_miss ? "Near miss" : i.cost != null ? formatMoney(i.cost) : "" },
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
    { key: "actions", header: "", render: (i) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" {...rowAction("Edit", rowLabel(i.reference, i.title))} onClick={() => openEdit(i)}>Edit</button> <button className="btn secondary sm" {...rowAction("Delete", rowLabel(i.reference, i.title))} onClick={() => remove(i)}>Delete</button></div> },
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

  const filters = filterParams.values;

  // ------------------------------------------------------------- tabs
  const generalTab = (
    <>
      <Field label="Title" required help="A short, descriptive name for the incident.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="e.g. Suspicious login from unknown IP" required />
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
    </>
  );

  const regulatoryTab = (
    <>
      <div className="field-row">
        <Field label="Reportable" help="Owed to a regulator. Saving creates the initial and final reports, with deadlines counted from detection.">
          <Toggle checked={f.is_reportable} onChange={(v) => set("is_reportable", v)} label="Reportable to a regulator" />
        </Field>
        <Field label="Regulator" help="Who the incident is reported to. Left blank on a reportable incident, the default regulator (SBP) is used.">
          <LookupSelect
            lookupKey="regulator"
            value={f.regulator_id}
            onChange={(id) => set("regulator_id", id)}
            legacyText={editing && !editing.regulator_id ? editing.regulator : null}
            placeholder="Choose a regulator…"
          />
        </Field>
      </div>
      {f.is_reportable && (
        <>
          <div style={{ padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 12, fontSize: 13 }}>
            {editing?.notification_deadline ? (
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <span>Initial notification due <strong>{formatDateTime(editing.notification_deadline)}</strong></span>
                <NotificationBadge i={editing} />
              </div>
            ) : (
              <span className="muted">
                The initial notification deadline is set on save: the detection time (or, if blank, when the incident
                is logged) plus the regulator&apos;s reporting window. Changing the detection time moves pending deadlines.
              </span>
            )}
          </div>
          <div className="field-row">
            <Field label="Notified at" help={`When the regulator was notified (${tzLabel}). Marks the initial report submitted.`}>
              <TextInput type="datetime-local" value={f.notified_at} onChange={(v) => set("notified_at", v)} />
            </Field>
            <Field label="Regulator reference" help="The regulator's acknowledgement or case reference.">
              <TextInput value={f.regulator_reference} onChange={(v) => set("regulator_reference", v)} placeholder="e.g. SBP/IR/2026/118" />
            </Field>
          </div>
        </>
      )}
    </>
  );

  // Response times as the form stands, so the handler sees what the dates imply.
  const formTimes = (() => {
    const iso = (v: string) => fromZonedInput(v, tz);
    return {
      mttd: hoursBetween(iso(f.occurred_at), iso(f.detected_at)),
      mttc: hoursBetween(iso(f.detected_at), iso(f.contained_at)),
      mttr: hoursBetween(iso(f.detected_at), iso(f.resolved_at)),
    };
  })();

  const timelineTab = (
    <>
      <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
        Times are in the organisation&apos;s timezone ({tzLabel}). They must run in order: occurred, detected, contained, resolved.
      </p>
      <div className="field-row">
        <Field label="Occurred At" help="When the incident actually took place.">
          <TextInput type="datetime-local" value={f.occurred_at} onChange={(v) => set("occurred_at", v)} />
        </Field>
        <Field label="Detected At" help="When it was first discovered. Starts the regulator's clock.">
          <TextInput type="datetime-local" value={f.detected_at} onChange={(v) => set("detected_at", v)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Contained At" help="When the spread was stopped. Filled in automatically when the status moves to Contained.">
          <TextInput type="datetime-local" value={f.contained_at} onChange={(v) => set("contained_at", v)} />
        </Field>
        <Field label="Resolved At" help="When response work was completed. Filled in automatically when the status moves to Resolved or Closed.">
          <TextInput type="datetime-local" value={f.resolved_at} onChange={(v) => set("resolved_at", v)} />
        </Field>
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13 }}>
        <span><span className="muted">Time to detect</span> <strong>{duration(formTimes.mttd)}</strong></span>
        <span><span className="muted">Time to contain</span> <strong>{duration(formTimes.mttc)}</strong></span>
        <span><span className="muted">Time to resolve</span> <strong>{duration(formTimes.mttr)}</strong></span>
      </div>
    </>
  );

  const analysisTab = (
    <>
      <Field label="Impact" help="Business / operational impact of the incident.">
        <TextArea value={f.impact} onChange={(v) => set("impact", v)} rows={3} placeholder="Systems affected, data exposed, downtime, etc." />
      </Field>
      <div className="field-row">
        <Field label="Customers affected">
          <NumberInput value={f.customers_affected} onChange={(v) => set("customers_affected", v)} min={0} step={1} placeholder="Not recorded" />
        </Field>
        <Field label="Records affected" help="Data records exposed, altered or lost.">
          <NumberInput value={f.records_affected} onChange={(v) => set("records_affected", v)} min={0} step={1} placeholder="Not recorded" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Near miss" help="It could have caused a loss but did not: no cost, left out of loss totals, no loss event.">
          <Toggle checked={f.near_miss} onChange={(v) => { set("near_miss", v); if (v) set("cost", ""); }} label="Near miss — nothing was lost" />
        </Field>
        <Field label="Personal data breach" help="Personal data was exposed. Saving opens a linked breach record in Data Protection (once) and notifies the DPO role.">
          <Toggle checked={f.personal_data_breach} onChange={(v) => set("personal_data_breach", v)} label="Personal data was breached" />
          {editing && editing.data_breaches.length > 0 && (
            <div style={{ marginTop: 6, fontSize: 12.5 }}>
              Breach record:{" "}
              {editing.data_breaches.map((b) => (
                <Link key={b.id} className="chip" href={`/data-protection?section=breach&id=${b.id}`}>{b.reference || b.title}</Link>
              ))}
            </div>
          )}
        </Field>
      </div>
      {!f.near_miss && (
        <Field label={`Estimated Cost (${currency})`} help="Financial impact in the organisation's reporting currency. Becomes the gross loss when you create a loss event.">
          <NumberInput value={f.cost} onChange={(v) => set("cost", v)} min={0} step={100} placeholder="Not recorded" />
        </Field>
      )}
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

  // ------------------------------------------------------------- dossier
  const incidentInput: IncidentInput | null = detail ? { incident: detail } : null;
  /** Open-point fixes only move: scroll, focus or open Edit on a tab. */
  function handlePoint(a: PointAction) {
    if (!detail) return;
    if (a.kind === "section") sections.scrollTo(a.target);
    else if (a.kind === "edit") openEdit(detail, a.target);
    else if (a.kind === "focus") document.getElementById(a.target)?.focus();
    else if (a.kind === "attest") gov.openAttest();
  }
  const handler = detail ? personName(detail.assignee_ref, detail.assignee) : "";
  // Header meta (record-page-spec §4.7, v1.1 D1): Incident status, Record approval, then
  // Severity, Handler, Occurred, Detected.
  const statusMeta: MetaItem | undefined = detail ? {
    key: "status", label: "Incident status",
    value: <Badge tone={STATUS_TONE[detail.status] || "neutral"} asIs>{sentenceCase(detail.status)}</Badge>,
    hint: "Where the incident is in its response. Separate from record approval.",
  } : undefined;
  const incidentMeta: MetaItem[] = detail ? [
    {
      key: "severity", label: "Severity",
      value: detail.severity ? <Badge tone={SEV_TONE[detail.severity] ?? "neutral"} asIs>{sentenceCase(detail.severity)}</Badge> : null,
    },
    {
      key: "handler", label: "Handler", value: handler || null, hint: "Responsible for the response.",
      // Free text with no person picked ("Network Team") is a label nobody can be notified at.
      gap: !handler ? { text: "Not assigned", fix: canWrite ? { label: "Assign", onClick: () => openEdit(detail, "general") } : undefined }
        : textOnlyPerson(detail.assignee_id, detail.assignee) ? { text: "Text only", fix: canWrite ? { label: "Pick a person", onClick: () => openEdit(detail, "general") } : undefined }
        : undefined,
    },
    { key: "occurred", label: "Occurred", value: detail.occurred_at ? formatDateTime(detail.occurred_at) : null },
    { key: "detected", label: "Detected", value: detail.detected_at ? formatDateTime(detail.detected_at) : null, hint: "Starts the regulator's notification clock." },
  ] : [];
  const linkGroups: RelatedGroup[] = detail ? [
    { key: "risks", label: "Risks", items: detail.risks, href: "/risks" },
    { key: "controls", label: "Controls", items: detail.controls, href: "/controls" },
    { key: "assets", label: "Assets", items: detail.assets, href: "/information-assets" },
    { key: "vendors", label: "Third parties", items: detail.vendors, href: "/vendors" },
  ] : [];

  return (
    <>
      <div className="page-head row-between" style={{ flexWrap: "wrap" }}>
        {/* The actions wrap under the title on a phone instead of widening the page. */}
        <div style={{ flex: "1 1 260px", minWidth: 0 }}>
          <h1>Security Operations</h1>
          <p>Log, triage and resolve security incidents through their response lifecycle.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ImportExport resource="incidents" label="Incidents" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add incident
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {summary && (
        <div className="grid stat-grid" style={{ marginBottom: 16 }}>
          <div className="card stat">
            <div className="stat-top"><span className="n">{summary.open.toLocaleString()}</span></div>
            <span className="l">Open incidents</span>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{summary.notifications_overdue.toLocaleString()}</span></div>
            <span className="l">Regulator notifications overdue{summary.notifications_pending ? ` · ${summary.notifications_pending} pending` : ""}</span>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{duration(summary.response_times.mttd_hours)}</span></div>
            <span className="l">Mean time to detect ({summary.response_times.mttd_count})</span>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{duration(summary.response_times.mttc_hours)}</span></div>
            <span className="l">Mean time to contain ({summary.response_times.mttc_count})</span>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{duration(summary.response_times.mttr_hours)}</span></div>
            <span className="l">Mean time to resolve ({summary.response_times.mttr_count})</span>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{formatMoney(summary.total_cost, null, { compact: "auto" })}</span></div>
            <span className="l">Estimated cost{summary.near_misses ? ` · ${summary.near_misses} near miss${summary.near_misses === 1 ? "" : "es"} excluded` : ""}</span>
          </div>
        </div>
      )}

      <DataTable<IncidentFull>
        tableKey="incidents"
        statusModel="incident"
        bulkActions={(rows, clear) => (
          <>
            <BulkEditBar entityType="incident" rows={rows} onDone={() => { clear(); reload(); }} />
            <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
          </>
        )}
        onApplyFilters={filterParams.replace}
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
            <select
              className="select"
              style={{ maxWidth: 200 }}
              value={fv.open === true ? ALL_OPEN : fv.status ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                filterParams.update(v === ALL_OPEN
                  ? { open: true, status: undefined }
                  : { open: undefined, status: (v || undefined) as typeof fv.status });
              }}
              aria-label="Status"
            >
              <option value="">All statuses</option>
              <option value={ALL_OPEN}>Open — not resolved or closed</option>
              {STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <select className="select" style={{ maxWidth: 150 }} value={fv.severity ?? ""} onChange={(e) => filterParams.set("severity", (e.target.value || undefined) as typeof fv.severity)} aria-label="Severity">
              <option value="">All severities</option>
              {SEVERITY.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={fv.is_reportable === true} onChange={(e) => filterParams.set("is_reportable", e.target.checked || undefined)} /> Reportable
            </label>
            <ArchivedRecords entityType="incident" noun="incidents" refreshKey={refreshKey} onRestored={reload} />
          </>
        }
        emptyMessage="No incidents yet. Log your first security incident to begin tracking."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        variant="dossier"
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        governance={gov}
        identity={detail ? {
          kind: "Incident",
          backLabel: "Incidents",
          reference: detail.reference || null,
          name: detail.title,
          lead: detail.description || null,
          badges: (detail.near_miss || detail.personal_data_breach || detail.is_reportable) ? (
            <>
              {detail.near_miss && <Badge tone="info" asIs>Near miss</Badge>}
              {detail.personal_data_breach && <Badge tone="high" asIs>Personal data breach</Badge>}
              {detail.is_reportable && <Badge tone="high" asIs>Reportable{regulatorName(detail) ? ` · ${regulatorName(detail)}` : ""}</Badge>}
            </>
          ) : null,
          status: statusMeta,
          approval: approvalMetaItem(gov, ctx.fmt, approvalHintFor("Incident status")),
          meta: incidentMeta,
          statusRules: { model: "incident", entityId: detail.id },
        } : undefined}
        primaryAction={(
          <PrimaryAction
            candidates={[{ kind: "workflow", action: "approve" }, { kind: "workflow", action: "submit" }, { kind: "attest" }]}
            onChanged={refresh}
          />
        )}
        onEdit={detail && canWrite ? () => openEdit(detail) : undefined}
        moreItems={detail ? withBaseMoreItems(
          canWrite ? [
            { label: `Generate ${regulatorName(detail) || "SBP"} reports`, onClick: generateRegReports, hint: incidentGenerateHint(detail) },
            {
              label: "Create loss event", onClick: createLossEvent, disabled: detail.near_miss,
              hint: detail.near_miss ? "A near miss has no loss to record" : "Adds it to the operational loss database",
            },
          ] : [],
          { onDelete: canWrite ? () => remove(detail) : undefined },
        ) : []}
        aside={detail ? (
          <RecordPanels model="incident" entityId={detail.id} layout="dossier" signOff={{ onChanged: refresh }} trail={{ reference: detail.reference }} />
        ) : null}
      >
        {detail && incidentInput && (
          <>
            <SummaryBand tiles={incidentTiles(incidentInput, ctx)} headline={incidentHeadline(incidentInput, ctx)} />
            <OpenPoints
              points={incidentOpenPoints(incidentInput, ctx)}
              canAct={canWrite}
              onAction={handlePoint}
              clearText={INCIDENT_CLEAR_TEXT}
            />
            <SectionNav />

            <RecordSection
              id="timeline"
              title="Timeline"
              sub={`Times in ${tzLabel}`}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "timeline")}>Edit times</button> : undefined}
            >
              <FactList
                items={[
                  { key: "occurred", label: "Occurred", value: detail.occurred_at ? formatDateTime(detail.occurred_at) : null, tab: "timeline" },
                  { key: "detected", label: "Detected", value: detail.detected_at ? formatDateTime(detail.detected_at) : null, tab: "timeline" },
                  // A stage the incident hasn't reached reads as a fact, not a field to fill in.
                  {
                    key: "contained", label: "Contained", tab: "timeline",
                    value: detail.contained_at ? formatDateTime(detail.contained_at)
                      : !["contained", "resolved", "closed"].includes(detail.status) ? <span className="muted">Not contained yet</span>
                      : null,
                  },
                  {
                    key: "resolved", label: "Resolved", tab: "timeline",
                    value: detail.resolved_at ? formatDateTime(detail.resolved_at)
                      : !["resolved", "closed"].includes(detail.status) ? <span className="muted">Not resolved yet</span>
                      : null,
                  },
                  {
                    key: "reported_by", label: "Reported by", tab: "general",
                    value: detail.reported_by_ref || detail.reported_by ? <UserName user={detail.reported_by_ref} fallback={detail.reported_by} /> : null,
                  },
                  // Calculated from the times above, never typed: a missing input reads "Needs
                  // Occurred" (not a "Fill in" field), and two date-only entries read "Same day"
                  // rather than an implausible "0 m".
                  ...(["mttd", "mttc", "mttr"] as const).map((k) => {
                    const note = incidentDurationNote(detail, k, ctx.fmt);
                    const hours = k === "mttd" ? detail.mttd_hours : k === "mttc" ? detail.mttc_hours : detail.mttr_hours;
                    return {
                      key: k,
                      label: k === "mttd" ? "Time to detect (MTTD)" : k === "mttc" ? "Time to contain (MTTC)" : "Time to resolve (MTTR)",
                      value: note ? <span className="muted">{note}</span> : duration(hours),
                      hint: k === "mttd" ? "Calculated: occurred to detected" : k === "mttc" ? "Calculated: detected to contained" : "Calculated: detected to resolved",
                    };
                  }),
                ]}
                onFillIn={canWrite ? (tab) => openEdit(detail, tab) : undefined}
              />
            </RecordSection>

            <RecordSection
              id="impact"
              title="Impact & loss"
              count={detail.loss_events.length || null}
              actions={canWrite ? (
                <button
                  type="button"
                  className="btn secondary sm"
                  onClick={createLossEvent}
                  disabled={detail.near_miss}
                  title={detail.near_miss ? "A near miss has no loss to record" : undefined}
                >
                  Create loss event
                </button>
              ) : undefined}
            >
              <FactList
                items={[
                  { key: "customers", label: "Customers affected", value: detail.customers_affected != null ? detail.customers_affected.toLocaleString() : null, tab: "analysis" },
                  { key: "records", label: "Records affected", value: detail.records_affected != null ? detail.records_affected.toLocaleString() : null, tab: "analysis" },
                  {
                    key: "cost", label: "Estimated cost", tab: "analysis",
                    value: detail.near_miss ? "Near miss — no loss" : detail.cost != null ? formatMoney(detail.cost) : null,
                  },
                  { key: "impact", label: "Impact", value: detail.impact?.trim() || null, wide: true, tab: "analysis" },
                ]}
                onFillIn={canWrite ? (tab) => openEdit(detail, tab) : undefined}
              />
              <h3 style={{ margin: "18px 0 8px", fontSize: 13, fontWeight: 650 }}>Loss events</h3>
              {detail.loss_events.length > 0 ? (
                <div className="rec-table-wrap">
                  <table className="compact">
                    <thead><tr><th>Ref</th><th>Title</th><th>Occurred</th><th className="num">Gross</th><th className="num">Net</th><th>Status</th></tr></thead>
                    <tbody>
                      {detail.loss_events.map((l) => (
                        <tr key={l.id}>
                          <td><Link className="ref" href="/operational-risk">{l.reference}</Link></td>
                          <td className="cell-title">{l.title}</td>
                          <td className="muted">{l.occurrence_date ? formatDate(l.occurrence_date) : "Not set"}</td>
                          <td className="muted num">{formatMoney(l.gross_loss, l.currency)}</td>
                          <td className="muted num">{formatMoney(l.net_loss, l.currency)}</td>
                          <td><Badge tone={l.status === "closed" || l.status === "recovered" ? "low" : "medium"} asIs>{sentenceCase(l.status)}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="rec-empty" style={{ margin: 0 }}>
                  {detail.near_miss ? "A near miss has no loss to record." : "No loss events yet. Create one to record what this incident cost, pre-filled from the incident."}
                </p>
              )}
            </RecordSection>

            <RecordSection
              id="regulatory"
              title="Regulatory reporting"
              count={detail.regulatory_reports.length || null}
              sub={detail.is_reportable ? `Reportable to ${regulatorName(detail) || "the regulator"}` : "Not reportable"}
              actions={canWrite ? (
                <button type="button" className="btn secondary sm" title={incidentGenerateHint(detail)} onClick={generateRegReports}>Generate {regulatorName(detail) || "SBP"} reports</button>
              ) : undefined}
              empty={!detail.is_reportable && !detail.notification_deadline && detail.regulatory_reports.length === 0 ? "No regulator reports." : undefined}
            >
              {detail.notification_deadline && (
                <FactGrid>
                  <Fact label="Regulator">{regulatorName(detail) || <span className="muted">Not set</span>}</Fact>
                  <Fact label="Notification deadline">{formatDateTime(detail.notification_deadline)}</Fact>
                  <Fact label="Countdown"><NotificationBadge i={detail} /></Fact>
                  <Fact label="Notified at">{detail.notified_at ? formatDateTime(detail.notified_at) : <span className="muted">Not yet</span>}</Fact>
                  <Fact label="Regulator reference">{detail.regulator_reference || <span className="muted">Not recorded</span>}</Fact>
                </FactGrid>
              )}
              <p className="muted" style={{ fontSize: 12.5, margin: "12px 0", maxWidth: "86ch" }}>
                Marking the incident reportable creates the {regulatorName(detail) || "SBP"} initial notification and final report,
                with deadlines counted from the detection time. Generate recreates any that were removed.
              </p>
              {detail.regulatory_reports.length > 0 ? (
                <div className="rec-table-wrap">
                  <table className="compact">
                    <thead><tr><th>Regulator</th><th>Report</th><th>Deadline</th><th>Status</th><th>Submitted</th><th>Reference</th><th aria-label="Actions" /></tr></thead>
                    <tbody>
                      {detail.regulatory_reports.map((r) => (
                        <RegReportRow
                          key={r.id}
                          r={r}
                          formatDate={formatDateTime}
                          canWrite={canWrite}
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
                <p className="rec-empty" style={{ margin: 0 }}>No regulatory reports yet.</p>
              )}
            </RecordSection>

            <RecordSection
              id="lifecycle"
              title="Response lifecycle"
              count={detail.stage_count || null}
              sub={detail.stage_count ? `${detail.completed_stages} of ${detail.stage_count} stages done` : undefined}
              empty={detail.stages.length === 0 ? "No response stages." : undefined}
            >
              <div className="rec-table-wrap">
                <table className="compact">
                  <thead><tr><th style={{ width: 36 }} className="num">#</th><th>Stage</th><th>Status</th><th>Completed</th><th aria-label="Actions" /></tr></thead>
                  <tbody>
                    {detail.stages.map((s) => (
                      <tr key={s.id}>
                        <td className="muted num">{s.order_index + 1}</td>
                        <td className="cell-title">{s.name}</td>
                        <td><Badge tone={STAGE_TONE[s.status] || "neutral"} asIs>{sentenceCase(s.status)}</Badge></td>
                        <td className="muted" style={{ whiteSpace: "nowrap" }}>{s.completed_at ? formatDate(s.completed_at) : "Not yet"}</td>
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          {canWrite && (
                            <span style={{ display: "inline-flex", gap: 6 }}>
                              {s.status === "pending" && <button type="button" className="btn secondary sm" {...rowAction("Start", s.name)} onClick={() => advance(s.id, "in_progress")}>Start</button>}
                              {s.status !== "done" && <button type="button" className="btn secondary sm" {...rowAction("Done", s.name)} onClick={() => advance(s.id, "done")}>Done</button>}
                              {s.status === "done" && <button type="button" className="btn secondary sm" {...rowAction("Reopen", s.name)} onClick={() => advance(s.id, "in_progress")}>Reopen</button>}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </RecordSection>

            <RecordSection
              id="analysis"
              title="Root cause & lessons"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit root cause and lessons" onClick={() => openEdit(detail, "analysis")}>Edit</button> : undefined}
            >
              <FactList
                items={[
                  { key: "root_cause", label: "Root cause", value: htmlToText(detail.root_cause) ? <RichTextView html={detail.root_cause} style={{ overflowWrap: "anywhere" }} /> : null, wide: true, tab: "analysis" },
                  { key: "lessons", label: "Lessons learned", value: htmlToText(detail.lessons_learned) ? <RichTextView html={detail.lessons_learned} style={{ overflowWrap: "anywhere" }} /> : null, wide: true, tab: "analysis" },
                ]}
                onFillIn={canWrite ? (tab) => openEdit(detail, tab) : undefined}
                allUnsetText="Not recorded yet"
              />
            </RecordSection>

            <RecordSection
              id="details"
              title="Details"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit details" onClick={() => openEdit(detail)}>Edit</button> : undefined}
            >
              <FactList
                items={[
                  { key: "type", label: "Type", value: detail.category_ref?.label || detail.category || null, tab: "general" },
                  { key: "classification", label: "Classification", value: detail.classification_ref?.label || detail.classification || null, tab: "general" },
                  ...(detail.personal_data_breach ? [{
                    key: "breach", label: "Data breach record",
                    value: detail.data_breaches.length ? (
                      <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 6 }}>
                        {detail.data_breaches.map((b) => (
                          <Link key={b.id} className="chip chip-link rec-chip" href={`/data-protection?section=breach&id=${b.id}`} title={[b.reference, b.title].filter(Boolean).join(" ")}>
                            {b.reference && <span className="ref">{b.reference}</span>}{b.title || b.name || ""}
                          </Link>
                        ))}
                      </span>
                    ) : "Not created (Data Protection is not enabled)",
                  }] : []),
                  { key: "created", label: "Created", value: detail.created_at ? formatDate(detail.created_at) : null },
                  ...cf.facts,
                ]}
                onFillIn={canWrite ? (tab) => (tab === "custom" ? cf.setEditing(true) : openEdit(detail, tab)) : undefined}
              />
              {cf.editor}
              {cf.editLink(canWrite)}
            </RecordSection>

            <RecordSection
              id="linked"
              title="Linked records"
              count={relatedCount(linkGroups)}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "links")}>Link records</button> : undefined}
            >
              {/* The head holds "Link records"; the empty line needs no second one (v1.1 D3). */}
              <RelatedGroups groups={linkGroups} />
            </RecordSection>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit incident — ${editing.reference}` : "Add item (Incidents)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "timeline", label: "Timeline", content: timelineTab },
            { id: "regulatory", label: "Regulatory", content: regulatoryTab },
            { id: "analysis", label: "Impact & analysis", content: analysisTab },
            { id: "links", label: "Links & Relations", content: linksTab },
            ...cfForm.tabs,
          ]}
          initialTab={editTab}
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
  canWrite,
  submitting,
  onStartSubmit,
  onChangeSubmit,
  onCancelSubmit,
  onConfirmSubmit,
  onRemove,
}: {
  r: RegReport;
  formatDate: (v: string | null) => string; // formatDateTime: deadlines are timestamps
  canWrite: boolean;
  submitting: { reference: string; submitted_by_id: string | null } | null;
  onStartSubmit: () => void;
  onChangeSubmit: (patch: { reference?: string; submitted_by_id?: string | null }) => void;
  onCancelSubmit: () => void;
  onConfirmSubmit: () => void;
  onRemove: () => void;
}) {
  // The "mark submitted" form opens on demand: Esc (through the shared escape stack) or
  // Cancel closes it, and focus goes back to the button that opened it. Focus is only
  // put back when closing lost it (it sat in the removed form): when the form closed
  // because another row's form opened, that form's field already has it. After a
  // successful submit the start button goes away, so focus lands on the row's Remove.
  const startRef = useRef<HTMLButtonElement>(null);
  const removeRef = useRef<HTMLButtonElement>(null);
  const wasOpen = useRef(false);
  const closedBy = useRef<"cancel" | "confirm" | null>(null);
  const cancel = () => { closedBy.current = "cancel"; onCancelSubmit(); };
  const confirm = () => { closedBy.current = "confirm"; onConfirmSubmit(); };
  useEscapeLayer(!!submitting, cancel);
  const label = `${sentenceCase(r.report_type).toLowerCase()} for ${r.regulator_ref?.label || r.regulator || "the regulator"}`;
  useEffect(() => {
    if (submitting) { wasOpen.current = true; return; }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    const by = closedBy.current;
    closedBy.current = null;
    const active = document.activeElement;
    const lost = !active || active === document.body || !active.isConnected;
    if (!lost) return;
    (by === "confirm" ? removeRef.current : startRef.current ?? removeRef.current)?.focus();
  }, [submitting]);
  return (
    <>
      <tr>
        <td className="muted">{r.regulator_ref?.label || r.regulator}</td>
        <td className="cell-title">{sentenceCase(r.report_type)}</td>
        <td className="muted">
          {r.deadline ? formatDate(r.deadline) : "No deadline"}
          {r.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="critical" asIs>Overdue</Badge></span>}
        </td>
        <td><Badge tone={r.status === "pending" ? "medium" : "low"} asIs>{sentenceCase(r.status)}</Badge></td>
        <td className="muted">
          {r.submitted_at ? (
            <>
              {formatDate(r.submitted_at)}
              {(r.submitted_by_ref || r.submitted_by) && (
                <div style={{ fontSize: 12 }}>by <UserName user={r.submitted_by_ref} fallback={r.submitted_by} /></div>
              )}
            </>
          ) : "Not yet"}
        </td>
        <td className="muted">{r.reference || "Not recorded"}</td>
        <td>
          {canWrite && (
            <div style={{ display: "flex", gap: 6 }}>
              {r.status === "pending" && !submitting && <button ref={startRef} type="button" className="btn secondary sm" {...rowAction("Mark submitted", label)} onClick={onStartSubmit}>Mark submitted</button>}
              <button ref={removeRef} type="button" className="btn secondary sm" {...rowAction("Remove", label)} onClick={onRemove}>Remove</button>
            </div>
          )}
        </td>
      </tr>
      {submitting && (
        <tr>
          <td colSpan={7}>
            <form
              style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}
              onSubmit={(ev) => { ev.preventDefault(); confirm(); }}
            >
              <div style={{ flex: "1 1 180px" }}>
                <label className="label" htmlFor={`rr-ref-${r.id}`}>Regulator acknowledgement reference</label>
                <input
                  id={`rr-ref-${r.id}`}
                  autoFocus
                  className="input"
                  value={submitting.reference}
                  onChange={(ev) => onChangeSubmit({ reference: ev.target.value })}
                  placeholder="Optional"
                />
              </div>
              <div style={{ flex: "1 1 200px" }}>
                <LabelledSearch label="Submitted by">
                  <UserPicker
                    value={submitting.submitted_by_id}
                    selected={r.submitted_by_ref}
                    onChange={(id) => onChangeSubmit({ submitted_by_id: id })}
                    placeholder="Who submitted it…"
                  />
                </LabelledSearch>
              </div>
              <button className="btn secondary sm" type="submit" {...rowAction("Mark submitted", label)}>Mark submitted</button>
              <button className="btn secondary sm" type="button" {...rowAction("Cancel", label)} onClick={cancel}>Cancel</button>
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
