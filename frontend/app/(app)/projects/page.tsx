"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, Select, NumberInput, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconCheck } from "@/components/icons";

// ---------------------------------------------------------------- inline types
type Ref = { id: string; reference?: string; title?: string; name?: string };

type ProjectTask = {
  id: string;
  project_id: string;
  title: string;
  description: string;
  due_date: string | null;
  completion: number;
  order_index: number;
  assignee: string;
  is_overdue: boolean;
};

type ProjectExpense = {
  id: string;
  project_id: string;
  amount: number;
  description: string;
  expense_date: string | null;
};

type Project = {
  id: string;
  reference: string;
  title: string;
  description: string;
  status: string;
  owner: string;
  start_date: string | null;
  deadline: string | null;
  budget: number | null;
  spent: number;
  over_budget: boolean;
  progress: number;
  open_tasks: number;
  is_overdue: boolean;
  tasks: ProjectTask[];
  expenses: ProjectExpense[];
  risks: Ref[];
  controls: Ref[];
  policies: Ref[];
  created_at: string;
};

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "neutral" | "info"> = {
  completed: "low",
  ongoing: "info",
  planned: "neutral",
  on_hold: "medium",
  cancelled: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const STATUS = opts(["planned", "ongoing", "on_hold", "completed", "cancelled"]);
const refToOpt = (x: Ref): AsyncOption => ({ value: x.id, label: x.reference || x.title || x.name || x.id });

function money(n: number | null) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

// --------------------------------------------------------------------- form state
type FormState = {
  title: string;
  description: string;
  status: string;
  owner: string;
  start_date: string;
  deadline: string;
  budget: number | "";
  risk_ids: AsyncOption[];
  control_ids: AsyncOption[];
  policy_ids: AsyncOption[];
};

const BLANK: FormState = {
  title: "",
  description: "",
  status: "planned",
  owner: "",
  start_date: "",
  deadline: "",
  budget: "",
  risk_ids: [],
  control_ids: [],
  policy_ids: [],
};

function fromProject(p: Project): FormState {
  return {
    title: p.title,
    description: p.description || "",
    status: p.status,
    owner: p.owner || "",
    start_date: p.start_date || "",
    deadline: p.deadline || "",
    budget: p.budget ?? "",
    risk_ids: p.risks.map(refToOpt),
    control_ids: p.controls.map(refToOpt),
    policy_ids: p.policies.map(refToOpt),
  };
}

function toPayload(f: FormState) {
  return {
    title: f.title,
    description: f.description,
    status: f.status,
    owner: f.owner,
    start_date: f.start_date || null,
    deadline: f.deadline || null,
    budget: f.budget === "" ? null : Number(f.budget),
    risk_ids: f.risk_ids.map((o) => o.value),
    control_ids: f.control_ids.map((o) => o.value),
    policy_ids: f.policy_ids.map((o) => o.value),
  };
}

const linkCount = (p: Project) => p.risks.length + p.controls.length + p.policies.length;

/* ================================================================ page ===== */
function ProjectsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [editing, setEditing] = useState<Project | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // child-record draft inputs (drawer)
  const [taskTitle, setTaskTitle] = useState("");
  const [taskAssignee, setTaskAssignee] = useState("");
  const [taskDue, setTaskDue] = useState("");
  const [expAmount, setExpAmount] = useState<number | "">("");
  const [expDesc, setExpDesc] = useState("");
  const [expDate, setExpDate] = useState("");

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchProjects = useCallback((qs: string) => apiCall<PagedList<Project>>("GET", `/projects?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<Project>("GET", `/projects/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  // server typeahead pickers
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.reference })));
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(p: Project) { setEditing(p); setF(fromProject(p)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Project>("PATCH", `/projects/${editing.id}`, payload);
      else await apiCall<Project>("POST", "/projects", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Project created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save project"); }
    finally { setSaving(false); }
  }
  async function remove(p: Project) {
    if (!(await confirmDialog({ title: `Delete project ${p.reference}?`, message: "This cannot be undone.", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/projects/${p.id}`);
      if (openId === p.id) setOpenId(null);
      reload(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }

  // child-record actions on the open (drawer) project; endpoints return the fresh Project.
  async function child(fn: Promise<unknown>) {
    if (!detail) return;
    setError(null);
    try {
      const updated = (await fn) as Project;
      if (updated && updated.id) setDetail(updated);
      else loadDetail(detail.id);
      reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); }
  }

  function addTask() {
    if (!detail || !taskTitle) return;
    child(apiCall<Project>("POST", `/projects/${detail.id}/tasks`, {
      title: taskTitle, assignee: taskAssignee, due_date: taskDue || null, order_index: detail.tasks.length + 1,
    }));
    setTaskTitle(""); setTaskAssignee(""); setTaskDue("");
  }
  function addExpense() {
    if (!detail || expAmount === "") return;
    child(apiCall<Project>("POST", `/projects/${detail.id}/expenses`, {
      amount: Number(expAmount), description: expDesc, expense_date: expDate || null,
    }));
    setExpAmount(""); setExpDesc(""); setExpDate("");
  }

  const columns: Column<Project>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (p) => <span className="ref">{p.reference}</span> },
    { key: "title", header: "Title", sortable: true, render: (p) => <span className="cell-title">{p.title}</span> },
    { key: "status", header: "Status", sortable: true, render: (p) => <Badge tone={STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge> },
    { key: "owner", header: "Owner", sortable: true, render: (p) => <span className="muted">{p.owner || "—"}</span> },
    { key: "start_date", header: "Start", sortable: true, render: (p) => <span className="muted">{p.start_date || "—"}</span> },
    { key: "deadline", header: "Deadline", sortable: true, render: (p) => <span className="muted">{p.deadline || "—"}{p.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}</span> },
    { key: "progress", header: "Progress", render: (p) => <div style={{ minWidth: 110 }}><div className="progress"><span style={{ width: `${p.progress}%` }} /></div><span className="muted" style={{ fontSize: 11 }}>{p.progress}%</span></div> },
    { key: "tasks", header: "Tasks", render: (p) => <span className="muted">{p.open_tasks}/{p.tasks.length}</span> },
    { key: "budget", header: "Budget / Spent", render: (p) => <span className="muted">{money(p.budget)} / <span style={{ color: p.over_budget ? "var(--red)" : "var(--text)" }}>{money(p.spent)}</span></span> },
    { key: "links", header: "Links", align: "center", render: (p) => <span className="muted">{linkCount(p) || "—"}</span> },
    { key: "actions", header: "", render: (p) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(p)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(p)}>Delete</button></div> },
  ];

  // ------------------------------------------------------------------ form tabs
  const generalTab = (
    <>
      <Field label="Title" required help="For example: MFA Rollout, ISO 27001 Remediation, GDPR Programme.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="MFA rollout" required />
      </Field>
      <Field label="Description">
        <RichText value={f.description} onChange={(v) => set("description", v)} />
      </Field>
      <div className="field-row">
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Owner / GRC Contact">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="CISO" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Start date">
          <TextInput type="date" value={f.start_date} onChange={(v) => set("start_date", v)} />
        </Field>
        <Field label="Deadline">
          <TextInput type="date" value={f.deadline} onChange={(v) => set("deadline", v)} />
        </Field>
        <Field label="Budget ($)" help="Total approved budget. Spend is tracked from expenses.">
          <NumberInput value={f.budget} onChange={(v) => set("budget", v)} min={0} placeholder="0" />
        </Field>
      </div>
    </>
  );

  const linksTab = (
    <>
      <Field label="Risks addressed" help="Risks this project remediates or reduces.">
        <AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} />
      </Field>
      <Field label="Controls implemented" help="Controls this project deploys or strengthens.">
        <AsyncMultiSelect search={searchControls} value={f.control_ids} onChange={(v) => set("control_ids", v)} />
      </Field>
      <Field label="Policies addressed" help="Policies this project enforces or operationalises.">
        <AsyncMultiSelect search={searchPolicies} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Project Management</h1>
          <p>Remediation projects with tasks &amp; milestones, budget tracking, and links to the risks, controls and policies they address.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="projects" label="Projects" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add project
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Project>
        columns={columns}
        fetcher={fetchProjects}
        rowKey={(p) => p.id}
        onRowClick={(p) => setOpenId(p.id)}
        activeKey={openId}
        searchPlaceholder="Search projects by title or reference…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No projects yet. Create your first project to start tracking remediation work."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? detail.reference : "…"}
        subtitle={detail ? `${detail.title}${detail.owner ? " · " + detail.owner : ""}` : ""}
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
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16, alignItems: "center" }}>
              <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {detail.is_overdue && <Badge tone="high">Overdue</Badge>}
              <span className="muted" style={{ fontSize: 13, marginLeft: "auto" }}>
                <IconCheck width={14} height={14} /> {detail.progress}% complete · {money(detail.spent)} / {money(detail.budget)}
              </span>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Tasks &amp; milestones</h3><span className="sub">{detail.open_tasks} open · {detail.progress}%</span></div>
              <div className="card-pad">
                {detail.tasks.map((t) => (
                  <div key={t.id} className="activity-item" style={{ alignItems: "center", gap: 10 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{t.title}</div>
                      <div className="when">
                        {t.assignee ? `${t.assignee} · ` : ""}
                        {t.due_date ? `due ${t.due_date}` : "no due date"}
                        {t.is_overdue && " · overdue"}
                      </div>
                    </div>
                    <div style={{ width: 90 }}><div className="progress"><span style={{ width: `${t.completion}%` }} /></div></div>
                    <input
                      className="input" style={{ width: 64, padding: "4px 6px" }} type="number" min={0} max={100} defaultValue={t.completion}
                      onBlur={(e) => { const v = Number(e.target.value); if (v !== t.completion) child(apiCall<Project>("PATCH", `/projects/${detail.id}/tasks/${t.id}`, { completion: v })); }}
                    />
                    <button className="btn secondary sm" type="button" onClick={() => child(apiCall<void>("DELETE", `/projects/${detail.id}/tasks/${t.id}`))}>Remove</button>
                  </div>
                ))}
                {detail.tasks.length === 0 && <span className="muted">No tasks yet.</span>}
                <div className="field-row" style={{ marginTop: 14, alignItems: "flex-end" }}>
                  <Field label="New task"><TextInput value={taskTitle} onChange={setTaskTitle} placeholder="Task / milestone title" /></Field>
                  <Field label="Assignee"><TextInput value={taskAssignee} onChange={setTaskAssignee} placeholder="Owner" /></Field>
                  <Field label="Due date"><TextInput type="date" value={taskDue} onChange={setTaskDue} /></Field>
                </div>
                <button className="btn sm" type="button" onClick={addTask} disabled={!taskTitle} style={{ marginTop: 4 }}><IconPlus width={14} height={14} /> Add task</button>
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Budget &amp; expenses</h3><span className="sub" style={{ color: detail.over_budget ? "var(--red)" : undefined }}>{money(detail.spent)} / {money(detail.budget)}</span></div>
              <div className="card-pad">
                {detail.expenses.map((x) => (
                  <div key={x.id} className="activity-item" style={{ alignItems: "center", gap: 10 }}>
                    <div style={{ flex: 1, fontSize: 13 }}>{x.description || "Expense"}</div>
                    <div className="when">{x.expense_date || "—"}</div>
                    <div className="muted" style={{ minWidth: 70, textAlign: "right" }}>{money(x.amount)}</div>
                    <button className="btn secondary sm" type="button" onClick={() => child(apiCall<void>("DELETE", `/projects/${detail.id}/expenses/${x.id}`))}>Remove</button>
                  </div>
                ))}
                {detail.expenses.length === 0 && <span className="muted">No expenses yet.</span>}
                <div className="field-row" style={{ marginTop: 14, alignItems: "flex-end" }}>
                  <Field label="Description"><TextInput value={expDesc} onChange={setExpDesc} placeholder="What was paid for" /></Field>
                  <Field label="Amount ($)"><NumberInput value={expAmount} onChange={setExpAmount} min={0} placeholder="0" /></Field>
                  <Field label="Date"><TextInput type="date" value={expDate} onChange={setExpDate} /></Field>
                </div>
                <button className="btn sm" type="button" onClick={addExpense} disabled={expAmount === ""} style={{ marginTop: 4 }}><IconPlus width={14} height={14} /> Add expense</button>
              </div>
            </div>

            {(detail.risks.length > 0 || detail.controls.length > 0 || detail.policies.length > 0) && (
              <div style={{ marginBottom: 16, fontSize: 13 }}>
                {detail.risks.length > 0 && <div><span className="muted">Risks: </span>{detail.risks.map((r) => r.reference || r.title || r.name).join(", ")}</div>}
                {detail.controls.length > 0 && <div><span className="muted">Controls: </span>{detail.controls.map((c) => c.reference || c.name || c.title).join(", ")}</div>}
                {detail.policies.length > 0 && <div><span className="muted">Policies: </span>{detail.policies.map((p) => p.reference || p.title || p.name).join(", ")}</div>}
              </div>
            )}

            <RecordPanels model="project" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit project — ${editing.reference}` : "Add item (Projects)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create project"}
        />
      )}
    </>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ProjectsInner />
    </Suspense>
  );
}
