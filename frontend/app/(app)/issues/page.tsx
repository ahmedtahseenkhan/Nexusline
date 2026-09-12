"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { apiCall } from "@/lib/api";
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
  closed_date: string | null;
  root_cause: string;
  management_response: string;
  repeat_finding: boolean;
  regulator_related: boolean;
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
  closed_date: string;
  root_cause: string;
  management_response: string;
  repeat_finding: boolean;
  regulator_related: boolean;
};
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
  closed_date: "",
  root_cause: "",
  management_response: "",
  repeat_finding: false,
  regulator_related: false,
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
    closed_date: i.closed_date || "",
    root_cause: i.root_cause || "",
    management_response: i.management_response || "",
    repeat_finding: !!i.repeat_finding,
    regulator_related: !!i.regulator_related,
  };
}
function issuePayload(f: IssueForm): Record<string, unknown> {
  return {
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
    closed_date: f.closed_date || null,
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

/* ================================================================ page ===== */
function IssuesInner() {
  const { formatDate } = useFormat();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Issue | null>(null);
  const [detailSource, setDetailSource] = useState<ResolvedSource | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<IssuesSummary | null>(null);

  // ---- filters ----
  const [fStatus, setFStatus] = useState("");
  const [fSource, setFSource] = useState("");
  const [fOverdue, setFOverdue] = useState(false);
  const [fRegulator, setFRegulator] = useState(false);

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
      const payload = issuePayload(f);
      if (editing) await apiCall<Issue>("PATCH", `/issues/${editing.id}`, payload);
      else await apiCall<Issue>("POST", "/issues", payload);
      setShowForm(false); reload(); loadSummary(); if (openId) loadDetail(openId);
      toast(editing ? "Changes saved" : "Issue raised");
    } catch (e) { setError(errMsg(e, "Failed to save issue")); }
    finally { setSaving(false); }
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
    { key: "actions", header: "", render: (i) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(i)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(i)}>Delete</button></div> },
  ];

  const filters = {
    status: fStatus || undefined,
    source_type: fSource || undefined,
    overdue: fOverdue || undefined,
    regulator_related: fRegulator || undefined,
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
      return {
        ...p,
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
        <Field label="Status">
          <Select value={f.status} onChange={(v) => setFF("status", v)} options={ISSUE_STATUS} />
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
  const remediationTab = (
    <>
      <div className="field-row">
        <Field label="Identified date">
          <TextInput type="date" value={f.identified_date} onChange={(v) => setFF("identified_date", v)} />
        </Field>
        <Field label="Due date" help="Target remediation date — drives the overdue flag.">
          <TextInput type="date" value={f.due_date} onChange={(v) => setFF("due_date", v)} />
        </Field>
      </div>
      <Field label="Closed date" help="Set automatically when the issue is closed / remediated / risk-accepted.">
        <TextInput type="date" value={f.closed_date} onChange={(v) => setFF("closed_date", v)} />
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
              <Fact label="Due">{formatDate(detail.due_date)}</Fact>
              <Fact label="Closed">{formatDate(detail.closed_date)}</Fact>
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
    </>
  );
}

export default function IssuesPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <IssuesInner />
    </Suspense>
  );
}
