"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconAlert } from "@/components/icons";

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

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
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
const ACTION_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  in_progress: "info",
  done: "low",
  cancelled: "neutral",
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

export default function IssuesPage() {
  const [error, setError] = useState<string | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [summary, setSummary] = useState<IssuesSummary | null>(null);

  // ---- filters ----
  const [fSearch, setFSearch] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [fSource, setFSource] = useState("");
  const [fOverdue, setFOverdue] = useState(false);
  const [fRegulator, setFRegulator] = useState(false);

  // ---- issue dialog + expanded detail ----
  const [editing, setEditing] = useState<Issue | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<IssueForm>(BLANK_ISSUE);
  const setFF = <K extends keyof IssueForm>(k: K, v: IssueForm[K]) => setF((p) => ({ ...p, [k]: v }));

  const [open, setOpen] = useState<Issue | null>(null);
  const [ad, setAd] = useState<ActionDraft>(BLANK_ACTION);
  const setAD = <K extends keyof ActionDraft>(k: K, v: ActionDraft[K]) => setAd((p) => ({ ...p, [k]: v }));
  const [ud, setUd] = useState<UpdateDraft>(BLANK_UPDATE);
  const setUD = <K extends keyof UpdateDraft>(k: K, v: UpdateDraft[K]) => setUd((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadIssues(keepOpen?: string) {
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (fSearch.trim()) params.set("search", fSearch.trim());
      if (fStatus) params.set("status", fStatus);
      if (fSource) params.set("source_type", fSource);
      if (fOverdue) params.set("overdue", "true");
      if (fRegulator) params.set("regulator_related", "true");
      const res = await apiCall<Page<Issue>>("GET", `/issues?${params.toString()}`);
      setIssues(res.items);
      if (keepOpen) setOpen(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load issues");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<IssuesSummary>("GET", "/issues-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }
  async function refreshIssue(id: string) {
    const i = await apiCall<Issue>("GET", `/issues/${id}`);
    setOpen(i);
    setIssues((prev) => prev.map((x) => (x.id === id ? i : x)));
  }

  useEffect(() => {
    loadIssues();
    loadSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------------- issue CRUD
  function openNew() {
    setEditing(null);
    setF(BLANK_ISSUE);
    setShowForm(true);
  }
  function openEdit(i: Issue) {
    setEditing(i);
    setF(fromIssue(i));
    setShowForm(true);
  }
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = issuePayload(f);
      if (editing) await apiCall<Issue>("PATCH", `/issues/${editing.id}`, payload);
      else await apiCall<Issue>("POST", "/issues", payload);
      setShowForm(false);
      await loadIssues(open?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save issue");
    } finally {
      setSaving(false);
    }
  }
  async function remove(i: Issue) {
    if (!window.confirm(`Delete issue ${i.reference || i.title}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/issues/${i.id}`);
      setShowForm(false);
      if (open?.id === i.id) setOpen(null);
      await loadIssues();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggle(i: Issue) {
    setAd(BLANK_ACTION);
    setUd(BLANK_UPDATE);
    setOpen(open?.id === i.id ? null : i);
  }

  // ------------------------------------------------------------- CAPA actions (inline)
  async function addAction() {
    if (!open) return;
    setError(null);
    try {
      await apiCall<Issue>("POST", `/issues/${open.id}/actions`, {
        title: ad.title,
        action_type: ad.action_type,
        owner: ad.owner,
        due_date: ad.due_date || null,
        status: ad.status,
      });
      setAd(BLANK_ACTION);
      await refreshIssue(open.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add action");
    }
  }
  async function setActionStatus(lineId: string, status: string) {
    if (!open) return;
    setError(null);
    try {
      await apiCall<IssueAction>("PATCH", `/issue-actions/${lineId}`, { status });
      await refreshIssue(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update action");
    }
  }
  async function removeAction(lineId: string) {
    if (!open) return;
    if (!window.confirm("Remove this action?")) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/issue-actions/${lineId}`);
      await refreshIssue(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove action");
    }
  }

  // ------------------------------------------------------------- updates (inline)
  async function addUpdate() {
    if (!open) return;
    setError(null);
    try {
      await apiCall<Issue>("POST", `/issues/${open.id}/updates`, {
        note: ud.note,
        author: ud.author,
        update_date: ud.update_date || null,
        status_change: ud.status_change,
      });
      setUd(BLANK_UPDATE);
      await refreshIssue(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add update");
    }
  }

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
      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.total_open.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Open issues</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.overdue_count.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Overdue</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.repeat_finding_count.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Repeat findings</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.regulator_related_open.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Regulator-related open</span>
        </div>
      </div>

      {/* ============================================= filters + register */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Issues</h3>
          <span className="sub">{issues.length} shown · click a row to manage actions &amp; progress</span>
        </div>

        <form
          className="card-pad"
          style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", paddingBottom: 4 }}
          onSubmit={(ev) => { ev.preventDefault(); loadIssues(open?.id); }}
        >
          <div style={{ flex: "1 1 220px" }}>
            <label className="label">Search</label>
            <input className="input" value={fSearch} onChange={(ev) => setFSearch(ev.target.value)} placeholder="Title, reference, owner…" />
          </div>
          <div style={{ width: 170 }}>
            <label className="label">Status</label>
            <select className="select" value={fStatus} onChange={(ev) => setFStatus(ev.target.value)}>
              <option value="">All statuses</option>
              {ISSUE_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
          </div>
          <div style={{ width: 190 }}>
            <label className="label">Source</label>
            <select className="select" value={fSource} onChange={(ev) => setFSource(ev.target.value)}>
              <option value="">All sources</option>
              {SOURCE_TYPES.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
          </div>
          <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={fOverdue} onChange={(ev) => setFOverdue(ev.target.checked)} /> Overdue only
          </label>
          <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
            <input type="checkbox" checked={fRegulator} onChange={(ev) => setFRegulator(ev.target.checked)} /> Regulator-related
          </label>
          <button className="btn secondary sm" type="submit">Apply</button>
        </form>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Source</th>
                <th>Severity</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Actions</th>
                <th>Due</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {issues.map((i) => (
                <tr key={i.id} style={{ cursor: "pointer" }} onClick={() => toggle(i)}>
                  <td className="ref">{i.reference || "—"}</td>
                  <td className="cell-title">
                    {i.title}
                    {i.repeat_finding && <> <Badge tone="medium">Repeat</Badge></>}
                    {i.regulator_related && <> <Badge tone="info">Regulator</Badge></>}
                  </td>
                  <td><Badge tone="info">{cap(i.source_type)}</Badge></td>
                  <td><SevBadge value={i.severity} /></td>
                  <td className="muted">{i.owner || "—"}</td>
                  <td><StatusBadge value={i.status} /></td>
                  <td className="muted">{i.open_action_count}/{i.action_count}</td>
                  <td>
                    {i.is_overdue ? (
                      <Badge tone="high">Overdue</Badge>
                    ) : (
                      <span className="muted">{i.due_date || "—"}</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => toggle(i)}>
                        {open?.id === i.id ? "Hide" : "Manage"}
                      </button>
                      <button className="btn secondary sm" onClick={() => openEdit(i)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => remove(i)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {issues.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconAlert width={24} height={24} /></span>
                      <h3>No issues</h3>
                      <p>Raise an issue, or feed findings from audit, compliance, RCSA, Shariah, incidents and inspections into one register.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ============================================= detail */}
      {open && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head row-between">
              <div>
                <h3>{open.reference} — {open.title}</h3>
                <span className="sub">
                  {cap(open.status)} · {cap(open.source_type)}
                  {open.source_reference ? " · " + open.source_reference : ""}
                  {open.owner ? " · owner " + open.owner : ""} · {open.age_days}d old
                </span>
              </div>
              <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                <div style={{ display: "flex", gap: 6 }}>
                  <SevBadge value={open.severity} />
                  <StatusBadge value={open.status} />
                  {open.is_overdue && <Badge tone="high">Overdue</Badge>}
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn secondary sm" onClick={() => openEdit(open)}>Edit</button>
                  <button className="btn secondary sm" onClick={() => remove(open)}>Delete</button>
                </div>
              </div>
            </div>

            <div className="card-pad">
              {(open.description || open.root_cause || open.management_response) && (
                <div style={{ marginBottom: 16, display: "grid", gap: 8 }}>
                  {open.description && (
                    <div><span className="muted" style={{ fontSize: 12 }}>Description</span><div>{open.description}</div></div>
                  )}
                  {open.root_cause && (
                    <div><span className="muted" style={{ fontSize: 12 }}>Root cause</span><div>{open.root_cause}</div></div>
                  )}
                  {open.management_response && (
                    <div><span className="muted" style={{ fontSize: 12 }}>Management response</span><div>{open.management_response}</div></div>
                  )}
                </div>
              )}

              {/* -------- CAPA actions -------- */}
              <strong>Corrective &amp; preventive actions (CAPA)</strong>
              <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                The remediation plan for this issue. Marking an action done stamps its completion date.
              </p>
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(ev) => { ev.preventDefault(); addAction(); }}
              >
                <div style={{ flex: "1 1 220px" }}>
                  <label className="label">Action title</label>
                  <input className="input" value={ad.title} onChange={(ev) => setAD("title", ev.target.value)} placeholder="Corrective action" required />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Type</label>
                  <select className="select" value={ad.action_type} onChange={(ev) => setAD("action_type", ev.target.value)}>
                    {CAPA_TYPE.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                  </select>
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Owner</label>
                  <input className="input" value={ad.owner} onChange={(ev) => setAD("owner", ev.target.value)} placeholder="Owner" />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Due date</label>
                  <input className="input" type="date" value={ad.due_date} onChange={(ev) => setAD("due_date", ev.target.value)} />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Status</label>
                  <select className="select" value={ad.status} onChange={(ev) => setAD("status", ev.target.value)}>
                    {ACTION_STATUS.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                  </select>
                </div>
                <button className="btn">Add</button>
              </form>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Type</th>
                      <th>Owner</th>
                      <th>Due</th>
                      <th>Completed</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {open.actions.map((a) => (
                      <tr key={a.id}>
                        <td className="cell-title">{a.title}</td>
                        <td><Badge tone={a.action_type === "preventive" ? "info" : "neutral"}>{cap(a.action_type)}</Badge></td>
                        <td className="muted">{a.owner || "—"}</td>
                        <td>
                          {a.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{a.due_date || "—"}</span>}
                        </td>
                        <td className="muted">{a.completed_date || "—"}</td>
                        <td>
                          <select
                            className="select"
                            value={a.status}
                            onChange={(ev) => setActionStatus(a.id, ev.target.value)}
                            style={{ padding: "2px 6px", height: "auto" }}
                          >
                            {ACTION_STATUS.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                          </select>
                        </td>
                        <td>
                          <button className="btn secondary sm" onClick={() => removeAction(a.id)}>Remove</button>
                        </td>
                      </tr>
                    ))}
                    {open.actions.length === 0 && (
                      <tr><td colSpan={7}><span className="muted">No actions recorded yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* -------- progress log -------- */}
              <strong style={{ display: "block", marginTop: 20 }}>Progress log</strong>
              <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                Chronological remediation updates and status changes.
              </p>
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(ev) => { ev.preventDefault(); addUpdate(); }}
              >
                <div style={{ flex: "1 1 260px" }}>
                  <label className="label">Update note</label>
                  <input className="input" value={ud.note} onChange={(ev) => setUD("note", ev.target.value)} placeholder="Progress note" required />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Author</label>
                  <input className="input" value={ud.author} onChange={(ev) => setUD("author", ev.target.value)} placeholder="Author" />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Date</label>
                  <input className="input" type="date" value={ud.update_date} onChange={(ev) => setUD("update_date", ev.target.value)} />
                </div>
                <div style={{ width: 170 }}>
                  <label className="label">Status change</label>
                  <input className="input" value={ud.status_change} onChange={(ev) => setUD("status_change", ev.target.value)} placeholder="e.g. open → in_progress" />
                </div>
                <button className="btn">Log</button>
              </form>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Author</th>
                      <th>Note</th>
                      <th>Status change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...open.updates]
                      .sort((a, b) => (b.update_date || "").localeCompare(a.update_date || ""))
                      .map((u) => (
                        <tr key={u.id}>
                          <td className="muted">{u.update_date || "—"}</td>
                          <td className="muted">{u.author || "—"}</td>
                          <td className="cell-title">{u.note || "—"}</td>
                          <td className="muted">{u.status_change || "—"}</td>
                        </tr>
                      ))}
                    {open.updates.length === 0 && (
                      <tr><td colSpan={4}><span className="muted">No progress logged yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <RecordPanels model="issue" entityId={open.id} />
        </>
      )}

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
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => remove(editing)}
                disabled={saving}
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
