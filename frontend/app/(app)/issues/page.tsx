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
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ local types
type IssueAction = {
  id: string;
  issue_id: string;
  title: string;
  description: string;
  action_type: string;
  owner: string;
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
  category: string;
  severity: string;
  status: string;
  owner: string;
  business_unit: string;
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
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

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

// ------------------------------------------------------------------ form state
type IssueForm = {
  title: string;
  description: string;
  source_type: string;
  source_reference: string;
  source_id: string;
  category: string;
  severity: string;
  status: string;
  owner: string;
  business_unit: string;
  identified_date: string;
  due_date: string;
  closed_date: string;
  root_cause: string;
  management_response: string;
  repeat_finding: boolean;
  regulator_related: boolean;
  workflow_status: string;
};
const BLANK_ISSUE: IssueForm = {
  title: "",
  description: "",
  source_type: "self_identified",
  source_reference: "",
  source_id: "",
  category: "",
  severity: "medium",
  status: "open",
  owner: "",
  business_unit: "",
  identified_date: "",
  due_date: "",
  closed_date: "",
  root_cause: "",
  management_response: "",
  repeat_finding: false,
  regulator_related: false,
  workflow_status: "draft",
};
function fromIssue(i: Issue): IssueForm {
  return {
    title: i.title,
    description: i.description || "",
    source_type: i.source_type || "self_identified",
    source_reference: i.source_reference || "",
    source_id: i.source_id || "",
    category: i.category || "",
    severity: i.severity || "medium",
    status: i.status || "open",
    owner: i.owner || "",
    business_unit: i.business_unit || "",
    identified_date: i.identified_date || "",
    due_date: i.due_date || "",
    closed_date: i.closed_date || "",
    root_cause: i.root_cause || "",
    management_response: i.management_response || "",
    repeat_finding: !!i.repeat_finding,
    regulator_related: !!i.regulator_related,
    workflow_status: i.workflow_status || "draft",
  };
}
function issuePayload(f: IssueForm): Record<string, unknown> {
  return {
    title: f.title,
    description: f.description,
    source_type: f.source_type,
    source_reference: f.source_reference,
    source_id: f.source_id.trim() === "" ? null : f.source_id.trim(),
    category: f.category,
    severity: f.severity,
    status: f.status,
    owner: f.owner,
    business_unit: f.business_unit,
    identified_date: f.identified_date || null,
    due_date: f.due_date || null,
    closed_date: f.closed_date || null,
    root_cause: f.root_cause,
    management_response: f.management_response,
    repeat_finding: f.repeat_finding,
    regulator_related: f.regulator_related,
    workflow_status: f.workflow_status,
  };
}

type ActionDraft = {
  title: string;
  action_type: string;
  owner: string;
  due_date: string;
  status: string;
};
const BLANK_ACTION: ActionDraft = {
  title: "",
  action_type: "corrective",
  owner: "",
  due_date: "",
  status: "open",
};

type UpdateDraft = {
  note: string;
  author: string;
  update_date: string;
  status_change: string;
};
const BLANK_UPDATE: UpdateDraft = { note: "", author: "", update_date: "", status_change: "" };

/* ================================================================ page ===== */
function IssuesInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Issue | null>(null);
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
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save issue"); }
    finally { setSaving(false); }
  }
  async function remove(i: Issue) {
    if (!(await confirmDialog({ title: `Delete issue ${i.reference || i.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/issues/${i.id}`);
      setShowForm(false);
      if (openId === i.id) setOpenId(null);
      reload(); loadSummary(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }

  // ------------------------------------------------------------- CAPA actions (inline)
  async function addAction() {
    if (!detail) return; setError(null);
    try {
      await apiCall<Issue>("POST", `/issues/${detail.id}/actions`, {
        title: ad.title, action_type: ad.action_type, owner: ad.owner,
        due_date: ad.due_date || null, status: ad.status,
      });
      setAd(BLANK_ACTION); loadDetail(detail.id); reload(); loadSummary();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to add action"); }
  }
  async function setActionStatus(lineId: string, status: string) {
    if (!detail) return; setError(null);
    try {
      await apiCall<IssueAction>("PATCH", `/issue-actions/${lineId}`, { status });
      loadDetail(detail.id); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to update action"); }
  }
  async function removeAction(lineId: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Remove this action?", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/issue-actions/${lineId}`);
      loadDetail(detail.id); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to remove action"); }
  }

  // ------------------------------------------------------------- updates (inline)
  async function addUpdate() {
    if (!detail) return; setError(null);
    try {
      await apiCall<Issue>("POST", `/issues/${detail.id}/updates`, {
        note: ud.note, author: ud.author, update_date: ud.update_date || null, status_change: ud.status_change,
      });
      setUd(BLANK_UPDATE); loadDetail(detail.id); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to add update"); }
  }

  const columns: Column<Issue>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (i) => <span className="ref">{i.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (i) => <span className="cell-title">{i.title}{i.repeat_finding && <> <Badge tone="medium">Repeat</Badge></>}{i.regulator_related && <> <Badge tone="info">Regulator</Badge></>}</span> },
    { key: "source_type", header: "Source", sortable: true, render: (i) => <Badge tone="info">{cap(i.source_type)}</Badge> },
    { key: "severity", header: "Severity", sortable: true, render: (i) => <SevBadge value={i.severity} /> },
    { key: "owner", header: "Owner", sortable: true, render: (i) => <span className="muted">{i.owner || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (i) => <StatusBadge value={i.status} /> },
    { key: "actions_count", header: "Actions", align: "center", render: (i) => <span className="muted">{i.open_action_count}/{i.action_count}</span> },
    { key: "due_date", header: "Due", sortable: true, render: (i) => (i.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{i.due_date || "—"}</span>) },
    { key: "actions", header: "", render: (i) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(i)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(i)}>Delete</button></div> },
  ];

  const filters = {
    status: fStatus || undefined,
    source_type: fSource || undefined,
    overdue: fOverdue || undefined,
    regulator_related: fRegulator || undefined,
  };

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
          <TextInput value={f.owner} onChange={(v) => setFF("owner", v)} placeholder="Remediation owner" />
        </Field>
        <Field label="Business unit">
          <TextInput value={f.business_unit} onChange={(v) => setFF("business_unit", v)} placeholder="Payments" />
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
          <TextInput value={f.category} onChange={(v) => setFF("category", v)} placeholder="Operational" />
        </Field>
      </div>
      <Field label="Source reference" help='Pointer to the originating record, e.g. "AUD-004 finding 3".'>
        <TextInput value={f.source_reference} onChange={(v) => setFF("source_reference", v)} placeholder="AUD-004 finding 3" />
      </Field>
      <Field label="Source record ID" help="Optional UUID of the originating record.">
        <TextInput value={f.source_id} onChange={(v) => setFF("source_id", v)} placeholder="Optional UUID" />
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
      <Field label="Workflow" help="Approval lifecycle for this issue record.">
        <Select value={f.workflow_status} onChange={(v) => setFF("workflow_status", v)} options={WORKFLOW} />
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
          </>
        }
        emptyMessage="No issues. Raise an issue, or feed findings from audit, compliance, RCSA, Shariah, incidents and inspections into one register."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? `${cap(detail.status)} · ${cap(detail.source_type)}${detail.owner ? " · owner " + detail.owner : ""} · ${detail.age_days}d old` : ""}
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
                  <div style={{ width: 130 }}>
                    <label className="label">Owner</label>
                    <input className="input" value={ad.owner} onChange={(ev) => setAD("owner", ev.target.value)} placeholder="Owner" />
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
                          <td className="muted">{a.owner || "—"}</td>
                          <td>{a.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{a.due_date || "—"}</span>}</td>
                          <td className="muted">{a.completed_date || "—"}</td>
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
                  <div style={{ width: 130 }}>
                    <label className="label">Author</label>
                    <input className="input" value={ud.author} onChange={(ev) => setUD("author", ev.target.value)} placeholder="Author" />
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
                            <td className="muted">{u.update_date || "—"}</td>
                            <td className="muted">{u.author || "—"}</td>
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

            <RecordPanels model="issue" entityId={detail.id} />
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
