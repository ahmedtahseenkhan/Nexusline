"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import RecordPanels from "@/components/RecordPanels";
import { Field, TextInput, Select, MultiSelect, NumberInput, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconLayers, IconPlus, IconCheck } from "@/components/icons";

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

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type RiskRow = { id: string; reference: string; title: string };
type ControlRow = { id: string; reference: string; name: string };
type PolicyRow = { id: string; reference: string; title: string };

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
  risk_ids: string[];
  control_ids: string[];
  policy_ids: string[];
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
    risk_ids: p.risks.map((r) => r.id),
    control_ids: p.controls.map((r) => r.id),
    policy_ids: p.policies.map((r) => r.id),
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
    risk_ids: f.risk_ids,
    control_ids: f.control_ids,
    policy_ids: f.policy_ids,
  };
}

export default function ProjectsPage() {
  const [items, setItems] = useState<Project[]>([]);
  const [risks, setRisks] = useState<RiskRow[]>([]);
  const [controls, setControls] = useState<ControlRow[]>([]);
  const [policies, setPolicies] = useState<PolicyRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Project | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const [detailId, setDetailId] = useState<string | null>(null);

  // child-record draft inputs (edit mode)
  const [taskTitle, setTaskTitle] = useState("");
  const [taskAssignee, setTaskAssignee] = useState("");
  const [taskDue, setTaskDue] = useState("");
  const [expAmount, setExpAmount] = useState<number | "">("");
  const [expDesc, setExpDesc] = useState("");
  const [expDate, setExpDate] = useState("");

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load(keepEditing?: string) {
    try {
      const pj = await apiCall<Page<Project>>("GET", "/projects?limit=200");
      setItems(pj.items);
      if (keepEditing) setEditing(pj.items.find((p) => p.id === keepEditing) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  useEffect(() => {
    load();
    apiCall<Page<RiskRow>>("GET", "/risks?limit=200").then((r) => setRisks(r.items)).catch(() => {});
    apiCall<Page<ControlRow>>("GET", "/controls?limit=200").then((r) => setControls(r.items)).catch(() => {});
    apiCall<Page<PolicyRow>>("GET", "/policies?limit=200").then((r) => setPolicies(r.items)).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setShowForm(true);
  }
  function openEdit(p: Project) {
    setEditing(p);
    setF(fromProject(p));
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) {
        await apiCall<Project>("PATCH", `/projects/${editing.id}`, payload);
      } else {
        const created = await apiCall<Project>("POST", "/projects", payload);
        setEditing(created); // keep dialog open so tasks/expenses can be added
        setF(fromProject(created));
      }
      await load(editing?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save project");
    } finally {
      setSaving(false);
    }
  }

  // child-record actions (refetch the project so the modal panes refresh)
  async function child(fn: Promise<unknown>) {
    if (!editing) return;
    setError(null);
    try {
      const updated = (await fn) as Project;
      if (updated && updated.id) setEditing(updated);
      await load(editing.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  function addTask() {
    if (!editing || !taskTitle) return;
    child(
      apiCall<Project>("POST", `/projects/${editing.id}/tasks`, {
        title: taskTitle,
        assignee: taskAssignee,
        due_date: taskDue || null,
        order_index: editing.tasks.length + 1,
      }),
    );
    setTaskTitle("");
    setTaskAssignee("");
    setTaskDue("");
  }

  function addExpense() {
    if (!editing || expAmount === "") return;
    child(
      apiCall<Project>("POST", `/projects/${editing.id}/expenses`, {
        amount: Number(expAmount),
        description: expDesc,
        expense_date: expDate || null,
      }),
    );
    setExpAmount("");
    setExpDesc("");
    setExpDate("");
  }

  async function deleteProject(p: Project) {
    if (!confirm(`Delete project ${p.reference}? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/projects/${p.id}`);
      if (detailId === p.id) setDetailId(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: r.title, sub: r.reference })),
    [risks],
  );
  const controlOpts: Option[] = useMemo(
    () => controls.map((c) => ({ value: c.id, label: c.name, sub: c.reference })),
    [controls],
  );
  const policyOpts: Option[] = useMemo(
    () => policies.map((p) => ({ value: p.id, label: p.title, sub: p.reference })),
    [policies],
  );

  const linkCount = (p: Project) => p.risks.length + p.controls.length + p.policies.length;

  // ------------------------------------------------------------------ tabs
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
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
      <Field label="Controls implemented" help="Controls this project deploys or strengthens.">
        <MultiSelect value={f.control_ids} onChange={(v) => set("control_ids", v)} options={controlOpts} />
      </Field>
      <Field label="Policies addressed" help="Policies this project enforces or operationalises.">
        <MultiSelect value={f.policy_ids} onChange={(v) => set("policy_ids", v)} options={policyOpts} />
      </Field>
    </>
  );

  const tasksTab = editing ? (
    <>
      <div className="row-between" style={{ marginBottom: 10 }}>
        <span className="sub">{editing.tasks.length} task(s) · {editing.progress}% complete</span>
        <span className="sub">{editing.open_tasks} open</span>
      </div>
      {editing.tasks.map((t) => (
        <div key={t.id} className="activity-item" style={{ alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13 }}>{t.title}</div>
            <div className="when">
              {t.assignee ? `${t.assignee} · ` : ""}
              {t.due_date ? `due ${t.due_date}` : "no due date"}
              {t.is_overdue && " · overdue"}
            </div>
          </div>
          <div style={{ width: 90 }}>
            <div className="progress"><span style={{ width: `${t.completion}%` }} /></div>
          </div>
          <input
            className="input"
            style={{ width: 64, padding: "4px 6px" }}
            type="number"
            min={0}
            max={100}
            defaultValue={t.completion}
            onBlur={(e) => {
              const v = Number(e.target.value);
              if (v !== t.completion)
                child(apiCall<Project>("PATCH", `/projects/${editing.id}/tasks/${t.id}`, { completion: v }));
            }}
          />
          <button
            className="btn secondary sm"
            type="button"
            onClick={() => child(apiCall<void>("DELETE", `/projects/${editing.id}/tasks/${t.id}`))}
          >
            Remove
          </button>
        </div>
      ))}
      <div className="field-row" style={{ marginTop: 14, alignItems: "flex-end" }}>
        <Field label="New task">
          <TextInput value={taskTitle} onChange={setTaskTitle} placeholder="Task / milestone title" />
        </Field>
        <Field label="Assignee">
          <TextInput value={taskAssignee} onChange={setTaskAssignee} placeholder="Owner" />
        </Field>
        <Field label="Due date">
          <TextInput type="date" value={taskDue} onChange={setTaskDue} />
        </Field>
      </div>
      <button className="btn sm" type="button" onClick={addTask} style={{ marginTop: 4 }}>
        <IconPlus width={14} height={14} /> Add task
      </button>
    </>
  ) : (
    <p className="muted">Save the project first to add tasks and milestones.</p>
  );

  const expensesTab = editing ? (
    <>
      <div className="row-between" style={{ marginBottom: 10 }}>
        <span className="sub">{editing.expenses.length} expense(s)</span>
        <span className="sub" style={{ color: editing.over_budget ? "var(--red)" : undefined }}>
          {money(editing.spent)} spent / {money(editing.budget)} budget
        </span>
      </div>
      {editing.expenses.map((x) => (
        <div key={x.id} className="activity-item" style={{ alignItems: "center", gap: 10 }}>
          <div style={{ flex: 1, fontSize: 13 }}>{x.description || "Expense"}</div>
          <div className="when">{x.expense_date || "—"}</div>
          <div className="muted" style={{ minWidth: 70, textAlign: "right" }}>{money(x.amount)}</div>
          <button
            className="btn secondary sm"
            type="button"
            onClick={() => child(apiCall<void>("DELETE", `/projects/${editing.id}/expenses/${x.id}`))}
          >
            Remove
          </button>
        </div>
      ))}
      <div className="field-row" style={{ marginTop: 14, alignItems: "flex-end" }}>
        <Field label="Description">
          <TextInput value={expDesc} onChange={setExpDesc} placeholder="What was paid for" />
        </Field>
        <Field label="Amount ($)">
          <NumberInput value={expAmount} onChange={setExpAmount} min={0} placeholder="0" />
        </Field>
        <Field label="Date">
          <TextInput type="date" value={expDate} onChange={setExpDate} />
        </Field>
      </div>
      <button className="btn sm" type="button" onClick={addExpense} style={{ marginTop: 4 }}>
        <IconPlus width={14} height={14} /> Add expense
      </button>
    </>
  ) : (
    <p className="muted">Save the project first to record expenses.</p>
  );

  const tabs = [
    { id: "general", label: "General", content: generalTab, required: true },
    { id: "links", label: "Links & Relations", content: linksTab },
    { id: "tasks", label: "Tasks", content: tasksTab },
    { id: "expenses", label: "Budget & Expenses", content: expensesTab },
  ];

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Project Management</h1>
          <p>Remediation projects with tasks &amp; milestones, budget tracking, and links to the risks, controls and policies they address.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="projects" label="Projects" onDone={() => load()} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add project
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Projects</h3>
          <span className="sub">{items.length} total · click a row to edit</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Start</th>
                <th>Deadline</th>
                <th>Progress</th>
                <th>Tasks</th>
                <th>Budget / Spent</th>
                <th>Links</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => openEdit(p)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">{p.title}</td>
                  <td><Badge tone={STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                  <td className="muted">{p.owner || "—"}</td>
                  <td className="muted">{p.start_date || "—"}</td>
                  <td className="muted">
                    {p.deadline || "—"}
                    {p.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}
                  </td>
                  <td style={{ minWidth: 120 }}>
                    <div className="progress"><span style={{ width: `${p.progress}%` }} /></div>
                    <span className="muted" style={{ fontSize: 11 }}>{p.progress}%</span>
                  </td>
                  <td className="muted">{p.open_tasks}/{p.tasks.length}</td>
                  <td className="muted">
                    {money(p.budget)} / <span style={{ color: p.over_budget ? "var(--red)" : "var(--text)" }}>{money(p.spent)}</span>
                  </td>
                  <td className="muted">{linkCount(p) || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => setDetailId(detailId === p.id ? null : p.id)}>
                        Details
                      </button>
                      <button className="btn secondary sm" onClick={() => deleteProject(p)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={11}>
                    <div className="empty">
                      <span className="ico"><IconLayers width={24} height={24} /></span>
                      <h3>No projects</h3>
                      <p>Create your first project to start tracking remediation work.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detailId && <RecordPanels model="project" entityId={detailId} />}

      {showForm && (
        <FormModal
          title={editing ? `Edit project — ${editing.reference}` : "Add item (Projects)"}
          tabs={tabs}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create project"}
          footerLeft={
            editing ? (
              <span className="muted" style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 6 }}>
                <IconCheck width={14} height={14} /> {editing.progress}% complete · {money(editing.spent)} spent
              </span>
            ) : undefined
          }
        />
      )}
    </>
  );
}
