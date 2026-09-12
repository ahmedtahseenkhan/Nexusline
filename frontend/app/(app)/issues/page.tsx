"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { api, apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { confirmDeleteWithImpact, records } from "@/lib/records";
import type { LookupRef, UnitRef, UserRef } from "@/lib/masterData";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import AsyncSelect, { type Option as AsyncOption } from "@/components/AsyncSelect";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import RelatedChips, { type GraphRef } from "@/components/RelatedChips";
import { useHasPermission } from "@/lib/tenantSettings";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import BusinessUnitSelect, { UnitName } from "@/components/BusinessUnitSelect";
import WorkflowFields from "@/components/WorkflowFields";
import ArchivedRecords from "@/components/ArchivedRecords";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import ImportExport from "@/components/ImportExport";
import { titleCase } from "@/lib/text";

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

// ------------------------------------------------------------------ local types
type IssueAction = {
  id: string;
  issue_id: string;
  title: string;
  description: string;
  action_type: string;
  owner: string;
  owner_id: string | null;
  owner_ref: UserRef | null;
  due_date: string | null;
  status: string;
  completed_date: string | null;
  evidence_note: string;
  is_overdue: boolean;
  created_at?: string;
};

type IssueUpdate = {
  id: string;
  issue_id: string;
  note: string;
  author: string;
  author_id: string | null;
  author_ref: UserRef | null;
  update_date: string | null;
  status_change: string;
  created_at?: string;
};

type DueDateChange = {
  id: string;
  issue_id: string;
  old_due_date: string | null;
  new_due_date: string | null;
  reason: string;
  /** pending | approved | rejected */
  status: string;
  requested_by_id: string | null;
  requested_by_ref: UserRef | null;
  /** Who decided it; empty when no approval was needed. */
  approved_by_id: string | null;
  approved_by_ref: UserRef | null;
  approved_at: string | null;
  created_at: string;
};

type AssetRef = GraphRef & { asset_class?: string };

type Issue = {
  id: string;
  reference: string;
  title: string;
  description: string;
  source_type: string;
  source_reference: string;
  source_id: string | null;
  /** Legacy text (the picked value's label once a category is picked). */
  category: string;
  category_id: string | null;
  category_ref: LookupRef | null;
  severity: string;
  status: string;
  /** Legacy text (the picked user's name once an owner is picked). */
  owner: string;
  owner_id: string | null;
  owner_ref: UserRef | null;
  business_unit: string;
  business_unit_id: string | null;
  business_unit_ref: UnitRef | null;
  identified_date: string | null;
  due_date: string | null;
  /** Set by the server when the issue closes; cleared on reopen. Read-only. */
  closed_date: string | null;
  root_cause: string;
  root_cause_category_id: string | null;
  root_cause_category_ref: LookupRef | null;
  management_response: string;
  repeat_finding: boolean;
  regulator_related: boolean;
  validated_by_id: string | null;
  validated_by_ref: UserRef | null;
  validated_at: string | null;
  /** effective | not_effective */
  validation_result: string | null;
  validation_note: string;
  risks: GraphRef[];
  controls: GraphRef[];
  requirements: GraphRef[];
  assets: AssetRef[];
  vendors: GraphRef[];
  due_date_changes: DueDateChange[];
  due_date_moves: number;
  workflow_status: string;
  action_count: number;
  open_action_count: number;
  is_overdue: boolean;
  age_days: number;
  actions: IssueAction[];
  updates: IssueUpdate[];
  created_at?: string;
};

type IssuesSummary = {
  by_status: Record<string, number>;
  by_source_type: Record<string, number>;
  total: number;
  total_open: number;
  overdue_count: number;
  repeat_finding_count: number;
  regulator_related_open: number;
  due_date_changes_pending?: number;
};

// ------------------------------------------------------------------ enum lists
const SOURCE_TYPES = opts([
  "internal_audit",
  "compliance",
  "rcsa",
  "shariah",
  "assessment",
  "incident",
  "external_inspection",
  "risk_assessment",
  "self_identified",
  "other",
]);
const ISSUE_STATUS = opts(["open", "in_progress", "remediated", "closed", "risk_accepted"]);
/** What the edit form may set; closing goes through Validate and Close. */
const OPEN_STATUS = opts(["open", "in_progress"]);
const CLOSE_STATUS = opts(["closed", "remediated", "risk_accepted"]);
const CLOSED_STATES = new Set(["closed", "remediated", "risk_accepted"]);
const isClosed = (status: string) => CLOSED_STATES.has(status);
const SEVERITY = opts(["low", "medium", "high", "critical"]);
const CAPA_TYPE = ["corrective", "preventive"];
const ACTION_STATUS = ["open", "in_progress", "done", "cancelled"];

// ------------------------------------------------------------------ source record link
/* `source_id` is a bare id with no type column: the kind of record it points at is picked
   here, and an existing link is recognised by asking the generic records API which
   register holds it (the guess from `source_type` first). */
type SourceKind = "risk" | "control" | "requirement" | "incident";
const SOURCE_KINDS: { value: SourceKind; label: string }[] = [
  { value: "risk", label: "Risk" },
  { value: "control", label: "Control" },
  { value: "requirement", label: "Compliance requirement" },
  { value: "incident", label: "Incident" },
];
/** Unknown kind: an id we could not place in any of the registers above (kept as is). */
const OTHER_KIND = "other";
const SOURCE_TYPE_FOR_KIND: Partial<Record<SourceKind, string>> = {
  risk: "risk_assessment",
  requirement: "compliance",
  incident: "incident",
};
const SOURCE_HREF: Record<SourceKind, string> = {
  risk: "/risks",
  control: "/controls",
  requirement: "/compliance",
  incident: "/incidents",
};
const KIND_FOR_SOURCE_TYPE: Record<string, SourceKind> = {
  risk_assessment: "risk",
  compliance: "requirement",
  incident: "incident",
};

type Referenced = { id: string; reference?: string; title?: string; name?: string };
const refLabel = (x: Referenced) =>
  [x.reference, x.title || x.name].filter(Boolean).join(" · ") || x.id;
const pagedSearch = (path: string) => (q: string): Promise<AsyncOption[]> =>
  apiCall<PagedList<Referenced>>("GET", `/${path}?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
    r.items.map((x) => ({ value: x.id, label: refLabel(x) })),
  );
const SOURCE_SEARCH: Record<SourceKind, (q: string) => Promise<AsyncOption[]>> = {
  risk: pagedSearch("risks"),
  control: pagedSearch("controls"),
  incident: pagedSearch("incidents"),
  requirement: (q) =>
    apiCall<{ id: string; reference: string; title: string; framework: string }[]>(
      "GET",
      `/requirements?search=${encodeURIComponent(q)}&limit=20`,
    ).then((rows) => rows.map((r) => ({ value: r.id, label: refLabel(r), sub: r.framework }))),
};

/* Typed links (issue_risks, issue_controls …): what the issue concerns, beside where it
   came from (the source fields above). */
type LinkKind = "risk" | "control" | "requirement" | "asset" | "vendor";
type LinkField = "risk_ids" | "control_ids" | "requirement_ids" | "asset_ids" | "vendor_ids";
const LINKS: { kind: LinkKind; field: LinkField; label: string; help: string; search: (q: string) => Promise<AsyncOption[]> }[] = [
  { kind: "risk", field: "risk_ids", label: "Risks", help: "Risks this issue affects or evidences.", search: SOURCE_SEARCH.risk },
  { kind: "control", field: "control_ids", label: "Controls", help: "Controls found deficient. While the issue is open it holds each control at partially effective.", search: SOURCE_SEARCH.control },
  { kind: "requirement", field: "requirement_ids", label: "Compliance requirements", help: "Clauses the gap breaches.", search: SOURCE_SEARCH.requirement },
  { kind: "asset", field: "asset_ids", label: "Assets", help: "IT or information assets involved.", search: pagedSearch("assets") },
  { kind: "vendor", field: "vendor_ids", label: "Third parties", help: "Vendors or outsourcing providers involved.", search: pagedSearch("vendors") },
];
const LINK_FIELD_FOR_SOURCE: Partial<Record<SourceKind, LinkField>> = {
  risk: "risk_ids",
  control: "control_ids",
  requirement: "requirement_ids",
};
const toOptions = (items: GraphRef[] | undefined): AsyncOption[] =>
  (items ?? []).map((x) => ({ value: x.id, label: refLabel(x) }));

type ResolvedSource = { kind: SourceKind | typeof OTHER_KIND; label: string };

/** Which register holds `id`, and its label; `other` when none of them does. */
async function resolveSource(id: string, sourceType: string): Promise<ResolvedSource> {
  const guess = KIND_FOR_SOURCE_TYPE[sourceType];
  const order: SourceKind[] = guess
    ? [guess, ...SOURCE_KINDS.map((k) => k.value).filter((k) => k !== guess)]
    : SOURCE_KINDS.map((k) => k.value);
  for (const kind of order) {
    try {
      const r = await records.impact(kind, id);
      return { kind, label: r.label || id };
    } catch {
      /* not this register — try the next */
    }
  }
  return { kind: OTHER_KIND, label: "" };
}

// ------------------------------------------------------------------ tones
const STATUS_TONE: Record<string, Tone> = {
  open: "high",
  in_progress: "info",
  remediated: "low",
  closed: "neutral",
  risk_accepted: "medium",
};
const SEV_TONE: Record<string, Tone> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

function StatusBadge({ value }: { value: string }) {
  return <Badge tone={STATUS_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}
function SevBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={SEV_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <div style={{ marginTop: 2, fontSize: 13 }}>{children}</div>
    </div>
  );
}

// ------------------------------------------------------------------ form state
type IssueForm = {
  title: string;
  description: string;
  source_type: string;
  source_reference: string;
  source_id: string | null;
  /** "" = no linked record; "other" = an id outside the pickable registers. */
  source_kind: string;
  source_label: string;
  category_id: string | null;
  severity: string;
  status: string;
  owner_id: string | null;
  business_unit_id: string | null;
  identified_date: string;
  due_date: string;
  /** Required when an existing due date changes; logged with the change. */
  due_date_reason: string;
  root_cause: string;
  root_cause_category_id: string | null;
  management_response: string;
  repeat_finding: boolean;
  regulator_related: boolean;
} & Record<LinkField, AsyncOption[]>;
const BLANK_ISSUE: IssueForm = {
  title: "",
  description: "",
  source_type: "self_identified",
  source_reference: "",
  source_id: null,
  source_kind: "",
  source_label: "",
  category_id: null,
  severity: "medium",
  status: "open",
  owner_id: null,
  business_unit_id: null,
  identified_date: "",
  due_date: "",
  due_date_reason: "",
  root_cause: "",
  root_cause_category_id: null,
  management_response: "",
  repeat_finding: false,
  regulator_related: false,
  risk_ids: [],
  control_ids: [],
  requirement_ids: [],
  asset_ids: [],
  vendor_ids: [],
};
function fromIssue(i: Issue): IssueForm {
  return {
    title: i.title,
    description: i.description || "",
    source_type: i.source_type || "self_identified",
    source_reference: i.source_reference || "",
    source_id: i.source_id || null,
    // Guessed from the source type until resolveSource() places the id.
    source_kind: i.source_id ? KIND_FOR_SOURCE_TYPE[i.source_type] || "risk" : "",
    source_label: i.source_id ? "Loading…" : "",
    category_id: i.category_id,
    severity: i.severity || "medium",
    status: i.status || "open",
    owner_id: i.owner_id,
    business_unit_id: i.business_unit_id,
    identified_date: i.identified_date || "",
    due_date: i.due_date || "",
    due_date_reason: "",
    root_cause: i.root_cause || "",
    root_cause_category_id: i.root_cause_category_id ?? null,
    management_response: i.management_response || "",
    repeat_finding: !!i.repeat_finding,
    regulator_related: !!i.regulator_related,
    risk_ids: toOptions(i.risks),
    control_ids: toOptions(i.controls),
    requirement_ids: toOptions(i.requirements),
    asset_ids: toOptions(i.assets),
    vendor_ids: toOptions(i.vendors),
  };
}
/** Whether saving this form moves an agreed due date (which needs a reason). */
const movesDueDate = (f: IssueForm, original: Issue | null) =>
  !!original?.due_date && (f.due_date || "") !== original.due_date;
function issuePayload(f: IssueForm, original: Issue | null): Record<string, unknown> {
  return {
    ...(movesDueDate(f, original) ? { due_date_reason: f.due_date_reason } : {}),
    root_cause_category_id: f.root_cause_category_id,
    ...Object.fromEntries(LINKS.map((l) => [l.field, f[l.field].map((o) => o.value)])),
    title: f.title,
    description: f.description,
    source_type: f.source_type,
    source_reference: f.source_reference,
    source_id: f.source_id,
    category_id: f.category_id,
    severity: f.severity,
    status: f.status,
    owner_id: f.owner_id,
    business_unit_id: f.business_unit_id,
    identified_date: f.identified_date || null,
    due_date: f.due_date || null,
    root_cause: f.root_cause,
    management_response: f.management_response,
    repeat_finding: f.repeat_finding,
    regulator_related: f.regulator_related,
  };
}

type ActionDraft = {
  title: string;
  action_type: string;
  owner_id: string | null;
  due_date: string;
  status: string;
};
const BLANK_ACTION: ActionDraft = {
  title: "",
  action_type: "corrective",
  owner_id: null,
  due_date: "",
  status: "open",
};

type UpdateDraft = {
  note: string;
  /** null = the signed-in user (the server's default). */
  author_id: string | null;
  update_date: string;
  status_change: string;
};
const BLANK_UPDATE: UpdateDraft = { note: "", author_id: null, update_date: "", status_change: "" };

/** A lifecycle step taken from the drawer, each in its own small dialog. */
type Step =
  | { kind: "validate" }
  | { kind: "close" }
  | { kind: "decide"; change: DueDateChange; approve: boolean };

/* ================================================================ page ===== */
function IssuesInner() {
  const { formatDate, formatDateTime } = useFormat();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Issue | null>(null);
  const [detailSource, setDetailSource] = useState<ResolvedSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<IssuesSummary | null>(null);
  // Approving a later due date needs the issue approve-equivalent permission, and never
  // the person who asked for it (the server enforces both; this only hides the buttons).
  const canApprove = useHasPermission("workflow:approve");
  const [meId, setMeId] = useState<string | null>(null);
  useEffect(() => { api.me().then((m) => setMeId(m.id)).catch(() => {}); }, []);

  // ---- filters ----
  const [fStatus, setFStatus] = useState("");
  const [fSource, setFSource] = useState("");
  const [fOverdue, setFOverdue] = useState(false);
  const [fRegulator, setFRegulator] = useState(false);
  const [fPending, setFPending] = useState(false);
  const [fMoves, setFMoves] = useState("");

  // ---- lifecycle step dialog (validate / close / decide a due-date change) ----
  const [step, setStep] = useState<Step | null>(null);
  const [stepResult, setStepResult] = useState("effective");
  const [stepStatus, setStepStatus] = useState("closed");
  const [stepNote, setStepNote] = useState("");
  const [stepError, setStepError] = useState<string | null>(null);
  const [stepSaving, setStepSaving] = useState(false);

  // ---- issue dialog ----
  const [editing, setEditing] = useState<Issue | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<IssueForm>(BLANK_ISSUE);
  const setFF = <K extends keyof IssueForm>(k: K, v: IssueForm[K]) => setF((p) => ({ ...p, [k]: v }));

  // ---- inline drafts (drawer) ----
  const [ad, setAd] = useState<ActionDraft>(BLANK_ACTION);
  const setAD = <K extends keyof ActionDraft>(k: K, v: ActionDraft[K]) => setAd((p) => ({ ...p, [k]: v }));
  const [ud, setUd] = useState<UpdateDraft>(BLANK_UPDATE);
  const setUD = <K extends keyof UpdateDraft>(k: K, v: UpdateDraft[K]) => setUd((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchIssues = useCallback((qs: string) => apiCall<PagedList<Issue>>("GET", `/issues?${qs}`), []);
  const loadSummary = useCallback(() => {
    apiCall<IssuesSummary>("GET", "/issues-summary").then(setSummary).catch(() => {});
  }, []);
  const loadDetail = useCallback((id: string) => {
    setAd(BLANK_ACTION); setUd(BLANK_UPDATE);
    apiCall<Issue>("GET", `/issues/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);
  useEffect(() => { loadSummary(); }, [loadSummary]);

  // Place the open issue's source record (for the drawer link).
  const detailSourceId = detail?.source_id ?? null;
  const detailSourceType = detail?.source_type ?? "";
  useEffect(() => {
    let live = true;
    setDetailSource(null);
    if (detailSourceId) resolveSource(detailSourceId, detailSourceType).then((r) => live && setDetailSource(r));
    return () => { live = false; };
  }, [detailSourceId, detailSourceType]);

  // Place the edited issue's source record (for the form picker).
  const editingSourceId = showForm ? editing?.source_id ?? null : null;
  const editingSourceType = editing?.source_type ?? "";
  useEffect(() => {
    let live = true;
    if (!editingSourceId) return;
    resolveSource(editingSourceId, editingSourceType).then((r) => {
      if (!live) return;
      setF((p) => (p.source_id === editingSourceId ? { ...p, source_kind: r.kind, source_label: r.label } : p));
    });
    return () => { live = false; };
  }, [editingSourceId, editingSourceType]);

  // ------------------------------------------------------------- issue CRUD
  function openNew() { setEditing(null); setF(BLANK_ISSUE); setError(null); setShowForm(true); }
  function openEdit(i: Issue) { setEditing(i); setF(fromIssue(i)); setError(null); setShowForm(true); }
  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = issuePayload(f, editing);
      let message = "Issue raised";
      if (editing) {
        const saved = await apiCall<Issue>("PATCH", `/issues/${editing.id}`, payload);
        const waiting = movesDueDate(f, editing) && saved.due_date === editing.due_date
          && saved.due_date_changes.some((c) => c.status === "pending");
        message = waiting ? "Saved. The later due date is waiting for approval." : "Changes saved";
      } else {
        await apiCall<Issue>("POST", "/issues", payload);
      }
      setShowForm(false); reload(); loadSummary(); if (openId) loadDetail(openId);
      toast(message);
    } catch (e) { setError(errMsg(e, "Failed to save issue")); }
    finally { setSaving(false); }
  }

  // ------------------------------------------------------------- validate / close / decide
  function openStep(next: Step) {
    setStep(next); setStepNote(""); setStepError(null); setStepResult("effective"); setStepStatus("closed");
  }
  async function submitStep() {
    if (!detail || !step) return;
    setStepSaving(true); setStepError(null);
    try {
      if (step.kind === "validate") {
        await apiCall<Issue>("POST", `/issues/${detail.id}/validate`, { result: stepResult, note: stepNote });
        toast(stepResult === "effective" ? "Validation recorded" : "Sent back to the owner (in progress)");
      } else if (step.kind === "close") {
        await apiCall<Issue>("POST", `/issues/${detail.id}/close`, { status: stepStatus, note: stepNote });
        toast(`Closed as ${cap(stepStatus).toLowerCase()}`);
      } else {
        await apiCall<Issue>("POST", `/issues/${detail.id}/due-date-changes/${step.change.id}/decide`, {
          approve: step.approve, note: stepNote,
        });
        toast(step.approve ? "New due date approved" : "Due-date change rejected");
      }
      setStep(null); loadDetail(detail.id); reload(); loadSummary();
    } catch (e) {
      // 409/403 bodies say exactly what is missing (open actions, evidence, validation, SoD).
      setStepError(errMsg(e, "Could not complete this step"));
    } finally { setStepSaving(false); }
  }
  async function remove(i: Issue) {
    const label = i.reference ? `${i.reference} ${i.title}` : i.title;
    if (!(await confirmDeleteWithImpact("issue", i.id, label))) return;
    try {
      await apiCall<void>("DELETE", `/issues/${i.id}`);
      setShowForm(false);
      if (openId === i.id) setOpenId(null);
      reload(); loadSummary(); toast(`Deleted ${i.reference || "issue"}`);
    } catch (e) {
      // A 403 here is segregation of duties: the server's message says who may delete it.
      toast(errMsg(e, "Failed to delete"), "error");
    }
  }

  // ------------------------------------------------------------- CAPA actions (inline)
  async function addAction() {
    if (!detail) return; setError(null);
    try {
      await apiCall<Issue>("POST", `/issues/${detail.id}/actions`, {
        title: ad.title, action_type: ad.action_type, owner_id: ad.owner_id,
        due_date: ad.due_date || null, status: ad.status,
      });
      setAd(BLANK_ACTION); loadDetail(detail.id); reload(); loadSummary();
    } catch (e) { setError(errMsg(e, "Failed to add action")); }
  }
  async function setActionStatus(lineId: string, status: string) {
    if (!detail) return; setError(null);
    try {
      await apiCall<IssueAction>("PATCH", `/issue-actions/${lineId}`, { status });
      loadDetail(detail.id); reload();
    } catch (e) { setError(errMsg(e, "Failed to update action")); }
  }
  async function setActionOwner(lineId: string, ownerId: string | null) {
    if (!detail) return; setError(null);
    try {
      await apiCall<IssueAction>("PATCH", `/issue-actions/${lineId}`, { owner_id: ownerId });
      loadDetail(detail.id);
    } catch (e) { setError(errMsg(e, "Failed to change the action owner")); }
  }
  async function removeAction(lineId: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Remove this action?", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/issue-actions/${lineId}`);
      loadDetail(detail.id); reload();
    } catch (e) { setError(errMsg(e, "Failed to remove action")); }
  }

  // ------------------------------------------------------------- updates (inline)
  async function addUpdate() {
    if (!detail) return; setError(null);
    try {
      await apiCall<Issue>("POST", `/issues/${detail.id}/updates`, {
        note: ud.note,
        // Omitted when blank: the server records the signed-in user as the author.
        ...(ud.author_id ? { author_id: ud.author_id } : {}),
        update_date: ud.update_date || null,
        status_change: ud.status_change,
      });
      setUd(BLANK_UPDATE); loadDetail(detail.id); reload();
    } catch (e) { setError(errMsg(e, "Failed to add update")); }
  }

  const ownerName = (i: Issue) => i.owner_ref?.full_name || i.owner_ref?.email || i.owner || "";

  const columns: Column<Issue>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (i) => <span className="ref">{i.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (i) => <span className="cell-title">{i.title}{i.repeat_finding && <> <Badge tone="medium">Repeat</Badge></>}{i.regulator_related && <> <Badge tone="info">Regulator</Badge></>}</span> },
    { key: "source_type", header: "Source", sortable: true, render: (i) => <Badge tone="info">{cap(i.source_type)}</Badge> },
    { key: "category", header: "Category", hidden: true, render: (i) => <span className="muted">{i.category_ref?.label || i.category || "—"}</span>, text: (i) => i.category_ref?.label || i.category || "" },
    { key: "severity", header: "Severity", sortable: true, render: (i) => <SevBadge value={i.severity} /> },
    { key: "owner", header: "Owner", sortable: true, render: (i) => <span className="muted"><UserName user={i.owner_ref} fallback={i.owner} /></span>, text: ownerName },
    { key: "business_unit", header: "Business unit", hidden: true, render: (i) => <span className="muted"><UnitName unit={i.business_unit_ref} fallback={i.business_unit} /></span>, text: (i) => i.business_unit_ref?.name || i.business_unit || "" },
    { key: "status", header: "Status", sortable: true, render: (i) => <StatusBadge value={i.status} /> },
    { key: "actions_count", header: "Actions", align: "center", render: (i) => <span className="muted">{i.open_action_count}/{i.action_count}</span> },
    { key: "due_date", header: "Due", sortable: true, render: (i) => (i.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{formatDate(i.due_date)}</span>), text: (i) => (i.due_date ? formatDate(i.due_date) : "") },
    { key: "due_date_moves", header: "Date moved", sortable: true, align: "center", hidden: true, render: (i) => (i.due_date_moves ? <Badge tone={i.due_date_moves > 1 ? "high" : "medium"}>{i.due_date_moves}×</Badge> : <span className="muted">—</span>), text: (i) => String(i.due_date_moves || 0) },
    { key: "closed_date", header: "Closed", sortable: true, hidden: true, render: (i) => <span className="muted">{formatDate(i.closed_date)}</span>, text: (i) => (i.closed_date ? formatDate(i.closed_date) : "") },
    { key: "actions", header: "", render: (i) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(i)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(i)}>Delete</button></div> },
  ];

  const filters = {
    status: fStatus || undefined,
    source_type: fSource || undefined,
    overdue: fOverdue || undefined,
    regulator_related: fRegulator || undefined,
    due_date_change_pending: fPending || undefined,
    min_due_date_moves: fMoves || undefined,
  };

  // ------------------------------------------------------------- source picker
  function pickSourceKind(kind: string) {
    setF((p) => ({ ...p, source_kind: kind, source_id: null, source_label: "" }));
  }
  function pickSource(id: string | null, opt: AsyncOption | null) {
    setF((p) => {
      if (!id) return { ...p, source_id: null, source_label: "" };
      const kind = p.source_kind as SourceKind;
      const suggested = SOURCE_TYPE_FOR_KIND[kind];
      const reference = (opt?.label || "").split(" · ")[0];
      // The record it was raised against is also linked (the server does the same).
      const linkField = LINK_FIELD_FOR_SOURCE[kind];
      const linked = linkField && !p[linkField].some((o) => o.value === id)
        ? { [linkField]: [...p[linkField], { value: id, label: opt?.label || id }] }
        : {};
      return {
        ...p,
        ...linked,
        source_id: id,
        source_label: opt?.label || "",
        // A linked risk / requirement / incident says where the issue came from.
        source_type: suggested && (p.source_type === "self_identified" || p.source_type === "other") ? suggested : p.source_type,
        source_reference: p.source_reference.trim() ? p.source_reference : reference,
      };
    });
  }
  const sourceKindOptions: Option[] =
    f.source_kind === OTHER_KIND ? [...SOURCE_KINDS, { value: OTHER_KIND, label: "Other record" }] : SOURCE_KINDS;

  // ------------------------------------------------------------- form tabs
  const generalTab = (
    <>
      <Field label="Title" required help="For example: Segregation of duties gap in wire release.">
        <TextInput value={f.title} onChange={(v) => setFF("title", v)} placeholder="Issue title" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => setFF("description", v)} rows={3} placeholder="What the issue is." />
      </Field>
      <div className="field-row">
        <Field label="Owner" help="Accountable for remediation.">
          <UserPicker
            value={f.owner_id}
            onChange={(id) => setFF("owner_id", id)}
            selected={editing?.owner_ref ?? null}
            legacyText={editing && !editing.owner_id ? editing.owner : null}
            placeholder="Remediation owner…"
          />
        </Field>
        <Field label="Business unit">
          <BusinessUnitSelect
            value={f.business_unit_id}
            onChange={(id) => setFF("business_unit_id", id)}
            legacyText={editing && !editing.business_unit_id ? editing.business_unit : null}
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Severity">
          <Select value={f.severity} onChange={(v) => setFF("severity", v)} options={SEVERITY} />
        </Field>
        <Field
          label="Status"
          help={editing && isClosed(editing.status)
            ? "Choosing an open status reopens the issue and clears its validation."
            : "Close an issue from its drawer with Validate and Close."}
        >
          <Select
            value={f.status}
            onChange={(v) => setFF("status", v)}
            options={editing && isClosed(editing.status)
              ? [{ value: editing.status, label: `${cap(editing.status)} (current)` }, ...OPEN_STATUS]
              : OPEN_STATUS}
          />
        </Field>
      </div>
    </>
  );
  const classificationTab = (
    <>
      <div className="field-row">
        <Field label="Source type" help="Which module or process raised this issue.">
          <Select value={f.source_type} onChange={(v) => setFF("source_type", v)} options={SOURCE_TYPES} />
        </Field>
        <Field label="Category">
          <LookupSelect
            lookupKey="issue_category"
            value={f.category_id}
            onChange={(id) => setFF("category_id", id)}
            legacyText={editing && !editing.category_id ? editing.category : null}
            allowCreate
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Raised against" help="The record this issue concerns — it then lists the issue too.">
          <Select value={f.source_kind} onChange={pickSourceKind} options={sourceKindOptions} placeholder="No linked record" />
        </Field>
        <Field label="Source record">
          {f.source_kind === OTHER_KIND ? (
            <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
              <span className="muted">Linked to a record from another module.</span>
              <button type="button" className="btn secondary sm" onClick={() => pickSourceKind("")}>Unlink</button>
            </div>
          ) : f.source_kind ? (
            <AsyncSelect
              key={f.source_kind}
              search={SOURCE_SEARCH[f.source_kind as SourceKind]}
              value={f.source_id}
              selectedLabel={f.source_label}
              placeholder={`Search ${SOURCE_KINDS.find((k) => k.value === f.source_kind)?.label.toLowerCase() ?? "records"}…`}
              onChange={pickSource}
            />
          ) : (
            <span className="muted" style={{ fontSize: 13 }}>Choose what the issue was raised against first.</span>
          )}
        </Field>
      </div>
      <Field label="Source reference" help='Pointer to the originating record, e.g. "AUD-004 finding 3".'>
        <TextInput value={f.source_reference} onChange={(v) => setFF("source_reference", v)} placeholder="AUD-004 finding 3" />
      </Field>
      <div className="field-row">
        <Field label="Repeat finding" help="Recurrence of a previously raised issue.">
          <Toggle checked={f.repeat_finding} onChange={(v) => setFF("repeat_finding", v)} label="Repeat finding" />
        </Field>
        <Field label="Regulator related" help="Raised by or reportable to the regulator (e.g. SBP).">
          <Toggle checked={f.regulator_related} onChange={(v) => setFF("regulator_related", v)} label="Regulator related" />
        </Field>
      </div>
    </>
  );
  const linksTab = (
    <>
      <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
        What this issue concerns. Each linked record lists the issue on its own page.
      </p>
      {LINKS.map((l) => (
        <Field key={l.field} label={l.label} help={l.help}>
          <AsyncMultiSelect search={l.search} value={f[l.field]} onChange={(v) => setFF(l.field, v)} />
        </Field>
      ))}
    </>
  );
  const dueDateMoving = movesDueDate(f, editing);
  const remediationTab = (
    <>
      <div className="field-row">
        <Field label="Identified date">
          <TextInput type="date" value={f.identified_date} onChange={(v) => setFF("identified_date", v)} />
        </Field>
        <Field
          label="Due date"
          help={editing?.due_date
            ? "Moving an agreed date needs a reason and is logged. A later date on a regulator-related, high or critical issue waits for approval."
            : "Target remediation date — drives the overdue flag."}
        >
          <TextInput type="date" value={f.due_date} onChange={(v) => setFF("due_date", v)} />
        </Field>
      </div>
      {dueDateMoving && (
        <Field label="Reason for the new due date" required help={`Currently ${formatDate(editing?.due_date ?? null)}. Kept in the issue's date history.`}>
          <textarea
            className="input"
            rows={2}
            required
            value={f.due_date_reason}
            onChange={(e) => setFF("due_date_reason", e.target.value)}
            placeholder="Why the date is moving"
          />
        </Field>
      )}
      <Field label="Closed date" help="Set by the system on Close; cleared if the issue is reopened.">
        <div style={{ fontSize: 13, padding: "6px 0" }}>
          {editing?.closed_date ? formatDate(editing.closed_date) : <span className="muted">Not closed</span>}
        </div>
      </Field>
      <Field label="Root cause category" help="From the root-cause category list; describe the detail below.">
        <LookupSelect
          lookupKey="root_cause_category"
          value={f.root_cause_category_id}
          onChange={(id) => setFF("root_cause_category_id", id)}
        />
      </Field>
      <Field label="Root cause">
        <TextArea value={f.root_cause} onChange={(v) => setFF("root_cause", v)} rows={3} placeholder="Underlying cause." />
      </Field>
      <Field label="Management response">
        <TextArea value={f.management_response} onChange={(v) => setFF("management_response", v)} rows={3} placeholder="Agreed management action." />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Issues &amp; Actions</h1>
          <p>One unified register of findings and corrective/preventive actions (CAPA) aggregated from audit, compliance, RCSA, Shariah, assessments, incidents and regulatory inspections.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="issues" label="Issues" onDone={() => setRefreshKey((k) => k + 1)} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> New issue
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= stats */}
      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.total_open.toLocaleString() : "—"}</span></div>
          <span className="l">Open issues</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.overdue_count.toLocaleString() : "—"}</span></div>
          <span className="l">Overdue</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.repeat_finding_count.toLocaleString() : "—"}</span></div>
          <span className="l">Repeat findings</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.regulator_related_open.toLocaleString() : "—"}</span></div>
          <span className="l">Regulator-related open</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? (summary.due_date_changes_pending ?? 0).toLocaleString() : "—"}</span></div>
          <span className="l">Due-date extensions awaiting approval</span>
        </div>
      </div>

      <DataTable<Issue>
        columns={columns}
        fetcher={fetchIssues}
        rowKey={(i) => i.id}
        onRowClick={(i) => setOpenId(i.id)}
        activeKey={openId}
        searchPlaceholder="Search title, reference, owner…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        filters={filters}
        toolbarRight={
          <>
            <select className="select" style={{ maxWidth: 170 }} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
              <option value="">All statuses</option>
              {ISSUE_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <select className="select" style={{ maxWidth: 190 }} value={fSource} onChange={(e) => setFSource(e.target.value)}>
              <option value="">All sources</option>
              {SOURCE_TYPES.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={fOverdue} onChange={(e) => setFOverdue(e.target.checked)} /> Overdue
            </label>
            <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={fRegulator} onChange={(e) => setFRegulator(e.target.checked)} /> Regulator
            </label>
            <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={fPending} onChange={(e) => setFPending(e.target.checked)} /> Extension pending
            </label>
            <select className="select" style={{ maxWidth: 170 }} value={fMoves} onChange={(e) => setFMoves(e.target.value)} aria-label="Due date moved">
              <option value="">Any date history</option>
              <option value="1">Date moved 1+ times</option>
              <option value="2">Date moved 2+ times</option>
              <option value="3">Date moved 3+ times</option>
            </select>
            <ArchivedRecords entityType="issue" noun="issues" refreshKey={refreshKey} onRestored={() => { reload(); loadSummary(); }} />
          </>
        }
        emptyMessage="No issues. Raise an issue, or feed findings from audit, compliance, RCSA, Shariah, incidents and inspections into one register."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        aside={detail ? <RecordPanels model="issue" entityId={detail.id} /> : null}
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? `${cap(detail.status)} · ${cap(detail.source_type)}${ownerName(detail) ? " · owner " + ownerName(detail) : ""} · ${detail.age_days}d old` : ""}
        width={820}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
              <SevBadge value={detail.severity} />
              <StatusBadge value={detail.status} />
              {detail.is_overdue && <Badge tone="high">Overdue</Badge>}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 12, padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <Fact label="Owner"><UserName user={detail.owner_ref} fallback={detail.owner} /></Fact>
              <Fact label="Business unit"><UnitName unit={detail.business_unit_ref} fallback={detail.business_unit} /></Fact>
              <Fact label="Category">{detail.category_ref?.label || detail.category || <span className="muted">—</span>}</Fact>
              <Fact label="Identified">{formatDate(detail.identified_date)}</Fact>
              <Fact label="Due">
                {formatDate(detail.due_date)}
                {detail.due_date_moves > 0 && (
                  <div className="muted" style={{ fontSize: 11.5 }}>
                    Date moved {detail.due_date_moves} {detail.due_date_moves === 1 ? "time" : "times"}
                  </div>
                )}
              </Fact>
              <Fact label="Closed">{detail.closed_date ? formatDate(detail.closed_date) : <span className="muted">—</span>}</Fact>
              <Fact label="Root cause category">{detail.root_cause_category_ref?.label || <span className="muted">—</span>}</Fact>
              <Fact label="Source">
                {cap(detail.source_type)}
                {detail.source_reference ? <span className="muted"> · {detail.source_reference}</span> : null}
              </Fact>
              {detail.source_id && (
                <Fact label="Raised against">
                  {!detailSource ? (
                    <span className="muted">Loading…</span>
                  ) : detailSource.kind === OTHER_KIND ? (
                    <span className="muted">A record in another module</span>
                  ) : (
                    <Link href={`${SOURCE_HREF[detailSource.kind]}?id=${detail.source_id}`}>{detailSource.label}</Link>
                  )}
                </Fact>
              )}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12, marginBottom: 16 }}>
              <RelatedChips label="Risks" items={detail.risks} href="/risks" />
              <RelatedChips label="Controls" items={detail.controls} href="/controls" />
              <RelatedChips label="Compliance requirements" items={detail.requirements} href="/compliance" />
              {detail.assets.some((a) => a.asset_class === "it_asset") && (
                <RelatedChips label="IT assets" items={detail.assets.filter((a) => a.asset_class === "it_asset")} href="/it-assets" />
              )}
              <RelatedChips
                label={detail.assets.some((a) => a.asset_class === "it_asset") ? "Information assets" : "Assets"}
                items={detail.assets.filter((a) => a.asset_class !== "it_asset")}
                href="/information-assets"
              />
              <RelatedChips label="Third parties" items={detail.vendors} href="/vendors" />
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head row-between">
                <h3>Validation &amp; closure</h3>
                {!isClosed(detail.status) && (
                  <div style={{ display: "flex", gap: 6 }}>
                    <button className="btn secondary sm" onClick={() => openStep({ kind: "validate" })}>Validate</button>
                    <button className="btn sm" onClick={() => openStep({ kind: "close" })}>Close</button>
                  </div>
                )}
              </div>
              <div className="card-pad" style={{ fontSize: 13 }}>
                {detail.validation_result ? (
                  <div style={{ display: "grid", gap: 4 }}>
                    <div>
                      <Badge tone={detail.validation_result === "effective" ? "low" : "high"}>
                        {detail.validation_result === "effective" ? "Validated effective" : "Validated not effective"}
                      </Badge>{" "}
                      <span className="muted">
                        by <UserName user={detail.validated_by_ref} fallback="" /> · {formatDateTime(detail.validated_at)}
                      </span>
                    </div>
                    {detail.validation_note && <div>{detail.validation_note}</div>}
                  </div>
                ) : (
                  <span className="muted">Not validated yet.</span>
                )}
                {isClosed(detail.status) ? (
                  <p className="muted" style={{ margin: "10px 0 0" }}>
                    {cap(detail.status)} on {formatDate(detail.closed_date)}. To reopen, edit the issue and choose an open status — its validation is cleared.
                  </p>
                ) : (
                  <p className="muted" style={{ margin: "10px 0 0" }}>
                    To close: finish or cancel every action ({detail.open_action_count} open), attach closure evidence
                    (Attachments / Files), and have someone other than the owner and the person who raised it record the fix as effective.
                    Closing as risk accepted needs an approved acceptance on a linked risk instead, or an approver&apos;s note.
                  </p>
                )}
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head row-between">
                <h3>Due date history</h3>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {detail.due_date_moves
                    ? `Date moved ${detail.due_date_moves} ${detail.due_date_moves === 1 ? "time" : "times"}`
                    : "Date never moved"}
                </span>
              </div>
              <div className="card-pad">
                {detail.due_date_changes.length ? (
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Asked</th><th>From</th><th>To</th><th>Reason</th><th>Asked by</th><th>Status</th><th></th></tr></thead>
                      <tbody>
                        {[...detail.due_date_changes].reverse().map((c) => {
                          const canDecide = c.status === "pending" && canApprove && !!meId && c.requested_by_id !== meId;
                          return (
                            <tr key={c.id}>
                              <td className="muted">{formatDate(c.created_at)}</td>
                              <td className="muted">{formatDate(c.old_due_date)}</td>
                              <td>{c.new_due_date ? formatDate(c.new_due_date) : <span className="muted">No date</span>}</td>
                              <td className="cell-title">{c.reason || "—"}</td>
                              <td className="muted"><UserName user={c.requested_by_ref} fallback="" /></td>
                              <td>
                                <Badge tone={c.status === "approved" ? "low" : c.status === "rejected" ? "neutral" : "medium"}>
                                  {c.status === "pending" ? "Awaiting approval" : cap(c.status)}
                                </Badge>
                                {c.approved_by_ref && (
                                  <div className="muted" style={{ fontSize: 11.5 }}>
                                    <UserName user={c.approved_by_ref} fallback="" /> · {formatDateTime(c.approved_at)}
                                  </div>
                                )}
                              </td>
                              <td style={{ whiteSpace: "nowrap" }}>
                                {canDecide && (
                                  <>
                                    <button className="btn sm" onClick={() => openStep({ kind: "decide", change: c, approve: true })}>Approve</button>{" "}
                                    <button className="btn secondary sm" onClick={() => openStep({ kind: "decide", change: c, approve: false })}>Reject</button>
                                  </>
                                )}
                                {c.status === "pending" && !canDecide && (
                                  <span className="muted" style={{ fontSize: 11.5 }}>
                                    {c.requested_by_id === meId ? "Someone else must approve" : "Needs an approver"}
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <span className="muted" style={{ fontSize: 13 }}>
                    No changes. Editing the due date asks for a reason and records it here.
                  </span>
                )}
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Approval</h3></div>
              <div className="card-pad">
                <WorkflowFields
                  entityType="issue"
                  entityId={detail.id}
                  onChanged={() => { loadDetail(detail.id); reload(); }}
                />
              </div>
            </div>

            {(detail.description || detail.root_cause || detail.management_response) && (
              <div style={{ marginBottom: 16, display: "grid", gap: 8 }}>
                {detail.description && <div><span className="muted" style={{ fontSize: 12 }}>Description</span><div>{detail.description}</div></div>}
                {detail.root_cause && <div><span className="muted" style={{ fontSize: 12 }}>Root cause</span><div>{detail.root_cause}</div></div>}
                {detail.management_response && <div><span className="muted" style={{ fontSize: 12 }}>Management response</span><div>{detail.management_response}</div></div>}
              </div>
            )}

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Corrective &amp; preventive actions (CAPA)</h3></div>
              <div className="card-pad">
                <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
                  The remediation plan for this issue. Marking an action done stamps its completion date.
                </p>
                <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(ev) => { ev.preventDefault(); addAction(); }}>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Action title</label>
                    <input className="input" value={ad.title} onChange={(ev) => setAD("title", ev.target.value)} placeholder="Corrective action" required />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Type</label>
                    <select className="select" value={ad.action_type} onChange={(ev) => setAD("action_type", ev.target.value)}>
                      {CAPA_TYPE.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                    </select>
                  </div>
                  <div style={{ width: 210 }}>
                    <label className="label">Owner</label>
                    <UserPicker value={ad.owner_id} onChange={(id) => setAD("owner_id", id)} placeholder="Action owner…" />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Due date</label>
                    <input className="input" type="date" value={ad.due_date} onChange={(ev) => setAD("due_date", ev.target.value)} />
                  </div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Title</th><th>Type</th><th>Owner</th><th>Due</th><th>Completed</th><th>Status</th><th></th></tr></thead>
                    <tbody>
                      {detail.actions.map((a) => (
                        <tr key={a.id}>
                          <td className="cell-title">{a.title}</td>
                          <td><Badge tone={a.action_type === "preventive" ? "info" : "neutral"}>{cap(a.action_type)}</Badge></td>
                          <td style={{ minWidth: 180 }}>
                            <UserPicker
                              value={a.owner_id}
                              selected={a.owner_ref}
                              legacyText={a.owner_id ? null : a.owner}
                              onChange={(id) => setActionOwner(a.id, id)}
                              placeholder="No owner"
                            />
                          </td>
                          <td>{a.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{formatDate(a.due_date)}</span>}</td>
                          <td className="muted">{formatDate(a.completed_date)}</td>
                          <td>
                            <select className="select" value={a.status} onChange={(ev) => setActionStatus(a.id, ev.target.value)} style={{ padding: "2px 6px", height: "auto" }}>
                              {ACTION_STATUS.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                            </select>
                          </td>
                          <td><button className="btn secondary sm" onClick={() => removeAction(a.id)}>Remove</button></td>
                        </tr>
                      ))}
                      {detail.actions.length === 0 && (<tr><td colSpan={7}><span className="muted">No actions recorded yet.</span></td></tr>)}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Progress log</h3></div>
              <div className="card-pad">
                <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>Chronological remediation updates and status changes.</p>
                <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(ev) => { ev.preventDefault(); addUpdate(); }}>
                  <div style={{ flex: "1 1 220px" }}>
                    <label className="label">Update note</label>
                    <input className="input" value={ud.note} onChange={(ev) => setUD("note", ev.target.value)} placeholder="Progress note" required />
                  </div>
                  <div style={{ width: 200 }}>
                    <label className="label">Author</label>
                    <UserPicker value={ud.author_id} onChange={(id) => setUD("author_id", id)} placeholder="You" />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Date</label>
                    <input className="input" type="date" value={ud.update_date} onChange={(ev) => setUD("update_date", ev.target.value)} />
                  </div>
                  <div style={{ width: 160 }}>
                    <label className="label">Status change</label>
                    <input className="input" value={ud.status_change} onChange={(ev) => setUD("status_change", ev.target.value)} placeholder="open → in_progress" />
                  </div>
                  <button className="btn">Log</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Date</th><th>Author</th><th>Note</th><th>Status change</th></tr></thead>
                    <tbody>
                      {[...detail.updates]
                        .sort((a, b) => (b.update_date || "").localeCompare(a.update_date || ""))
                        .map((u) => (
                          <tr key={u.id}>
                            <td className="muted">{formatDate(u.update_date)}</td>
                            <td className="muted"><UserName user={u.author_ref} fallback={u.author} /></td>
                            <td className="cell-title">{u.note || "—"}</td>
                            <td className="muted">{u.status_change || "—"}</td>
                          </tr>
                        ))}
                      {detail.updates.length === 0 && (<tr><td colSpan={4}><span className="muted">No progress logged yet.</span></td></tr>)}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

          </>
        )}
      </RecordDrawer>

      {/* ============================================= modal */}
      {showForm && (
        <FormModal
          title={editing ? `Edit issue — ${editing.reference || editing.title}` : "New issue"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "classification", label: "Classification", content: classificationTab },
            { id: "links", label: "Links", content: linksTab },
            { id: "remediation", label: "Remediation", content: remediationTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create issue"}
          footerLeft={
            editing ? (
              <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {step && detail && (
        <FormModal
          title={
            step.kind === "validate" ? `Validate ${detail.reference}`
              : step.kind === "close" ? `Close ${detail.reference}`
              : `${step.approve ? "Approve" : "Reject"} new due date — ${detail.reference}`
          }
          tabs={[{ id: "step", label: "Step", content: stepContent(step, detail) }]}
          onClose={() => setStep(null)}
          onSave={submitStep}
          saving={stepSaving}
          error={stepError}
          saveLabel={
            step.kind === "validate" ? "Record validation"
              : step.kind === "close" ? "Close issue"
              : step.approve ? "Approve" : "Reject"
          }
        />
      )}
    </>
  );

  function stepContent(s: Step, i: Issue) {
    if (s.kind === "validate") {
      return (
        <>
          <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
            You are certifying whether the remediation works. You must not be the issue&apos;s owner or the person who raised it.
            Recording it as effective needs closure evidence attached to the issue; not effective sends it back to the owner.
          </p>
          <Field label="Result" required>
            <Select value={stepResult} onChange={setStepResult} options={[
              { value: "effective", label: "Effective — the fix works" },
              { value: "not_effective", label: "Not effective — send back" },
            ]} />
          </Field>
          <Field label="Validation note" required help="What you checked and what you found.">
            <textarea className="input" rows={3} required value={stepNote} onChange={(e) => setStepNote(e.target.value)} />
          </Field>
        </>
      );
    }
    if (s.kind === "close") {
      const ready = [
        { ok: i.open_action_count === 0, text: i.open_action_count ? `${i.open_action_count} action(s) still open` : "No open actions" },
        { ok: i.validation_result === "effective", text: i.validation_result === "effective" ? "Validated effective" : "No effective validation yet" },
      ];
      return (
        <>
          <Field label="Close as" required>
            <Select value={stepStatus} onChange={setStepStatus} options={CLOSE_STATUS} />
          </Field>
          <ul style={{ margin: "0 0 12px", paddingLeft: 18, fontSize: 13 }}>
            {stepStatus === "risk_accepted" ? (
              <>
                <li className={i.open_action_count ? "" : "muted"}>{ready[0].text}</li>
                <li className="muted">Needs an approved risk acceptance on a linked risk, or a note from someone who may approve issues.</li>
              </>
            ) : (
              ready.map((r) => <li key={r.text} style={{ color: r.ok ? undefined : "var(--danger, #c0392b)" }}>{r.ok ? "✓ " : "✗ "}{r.text}</li>)
            )}
            <li className="muted">The person who raised the issue cannot close it.</li>
          </ul>
          <Field label="Closure note" required={stepStatus === "risk_accepted"} help="Kept in the progress log and the audit trail.">
            <textarea className="input" rows={3} value={stepNote} onChange={(e) => setStepNote(e.target.value)} />
          </Field>
        </>
      );
    }
    return (
      <>
        <p style={{ margin: "0 0 12px", fontSize: 13 }}>
          Move the due date from <strong>{formatDate(s.change.old_due_date)}</strong> to{" "}
          <strong>{s.change.new_due_date ? formatDate(s.change.new_due_date) : "no date"}</strong>.
        </p>
        <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
          Reason given by <UserName user={s.change.requested_by_ref} fallback="the requester" />: {s.change.reason || "—"}
        </p>
        <Field label="Note" help="Optional; kept in the progress log.">
          <textarea className="input" rows={2} value={stepNote} onChange={(e) => setStepNote(e.target.value)} />
        </Field>
      </>
    );
  }
}

export default function IssuesPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <IssuesInner />
    </Suspense>
  );
}
