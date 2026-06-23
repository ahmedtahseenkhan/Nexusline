"use client";

import { useEffect, useState } from "react";
import { api, type Project, type Risk } from "@/lib/api";
import { Badge } from "@/components/badges";
import RecordPanels from "@/components/RecordPanels";
import { IconLayers, IconPlus } from "@/components/icons";

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "neutral" | "info"> = {
  completed: "low",
  ongoing: "info",
  planned: "neutral",
  on_hold: "medium",
  cancelled: "neutral",
};

function money(n: number | null) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export default function ProjectsPage() {
  const [items, setItems] = useState<Project[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [open, setOpen] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [budget, setBudget] = useState("");
  const [deadline, setDeadline] = useState("");
  const [riskId, setRiskId] = useState("");

  const [taskTitle, setTaskTitle] = useState("");
  const [expAmount, setExpAmount] = useState("");
  const [expDesc, setExpDesc] = useState("");

  async function load(keepOpen?: string) {
    try {
      const [pj, rk] = await Promise.all([api.projects(), api.risks()]);
      setItems(pj.items);
      setRisks(rk.items);
      if (keepOpen) setOpen(pj.items.find((p) => p.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function act(fn: Promise<unknown>, keepOpen?: string) {
    setError(null);
    try {
      await fn;
      await load(keepOpen);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function createProject(e: React.FormEvent) {
    e.preventDefault();
    await act(
      api.createProject({
        title,
        owner,
        budget: budget ? Number(budget) : null,
        deadline: deadline || null,
        status: "ongoing",
        risk_ids: riskId ? [riskId] : [],
      })
    );
    setShowForm(false);
    setTitle("");
    setOwner("");
    setBudget("");
    setDeadline("");
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Projects</h1>
          <p>Remediation projects with tasks, budget and links to risks &amp; controls.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New project"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={createProject}>
          <label className="label">Title</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. MFA rollout" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Owner</label>
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} />
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Budget ($)</label>
              <input className="input" type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} />
            </div>
            <div style={{ width: 170 }}>
              <label className="label">Deadline</label>
              <input className="input" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
            </div>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Linked risk</label>
              <select className="select" value={riskId} onChange={(e) => setRiskId(e.target.value)}>
                <option value="">— none —</option>
                {risks.map((r) => (<option key={r.id} value={r.id}>{r.reference} — {r.title}</option>))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create project</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>All projects</h3>
          <span className="sub">{items.length} total · click a row for detail</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Budget / Spent</th>
                <th>Open tasks</th>
                <th>Deadline</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === p.id ? null : p)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">{p.title}</td>
                  <td><Badge tone={STATUS_TONE[p.status] || "neutral"}>{p.status.replace(/_/g, " ")}</Badge></td>
                  <td style={{ minWidth: 130 }}>
                    <div className="progress"><span style={{ width: `${p.progress}%` }} /></div>
                    <span className="muted" style={{ fontSize: 11 }}>{p.progress}%</span>
                  </td>
                  <td className="muted">
                    {money(p.budget)} / <span style={{ color: p.over_budget ? "var(--red)" : "var(--text)" }}>{money(p.spent)}</span>
                  </td>
                  <td className="muted">{p.open_tasks}</td>
                  <td className="muted">
                    {p.deadline || "—"}{p.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconLayers width={24} height={24} /></span>
                      <h3>No projects</h3>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <>
        <div className="grid" style={{ gridTemplateColumns: "1.3fr 1fr" }}>
          <div className="card">
            <div className="card-head">
              <h3>Tasks · {open.reference}</h3>
              <span className="sub">{open.progress}% complete</span>
            </div>
            <div className="card-pad">
              {open.tasks.map((t) => (
                <div key={t.id} className="activity-item" style={{ alignItems: "center" }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{t.title}</div>
                    <div className="when">
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
                      if (v !== t.completion) act(api.updateTask(open.id, t.id, { completion: v }), open.id);
                    }}
                  />
                </div>
              ))}
              <form
                style={{ display: "flex", gap: 8, marginTop: 12 }}
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!taskTitle) return;
                  act(api.addTask(open.id, { title: taskTitle, order_index: open.tasks.length + 1 }), open.id);
                  setTaskTitle("");
                }}
              >
                <input className="input" value={taskTitle} onChange={(e) => setTaskTitle(e.target.value)} placeholder="Add a task…" />
                <button className="btn sm">Add</button>
              </form>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Budget · {open.reference}</h3>
              <span className="sub" style={{ color: open.over_budget ? "var(--red)" : undefined }}>
                {money(open.spent)} / {money(open.budget)}
              </span>
            </div>
            <div className="card-pad">
              {open.expenses.map((x) => (
                <div key={x.id} className="activity-item">
                  <div style={{ flex: 1, fontSize: 13 }}>{x.description || "Expense"}</div>
                  <div className="muted">{money(x.amount)}</div>
                </div>
              ))}
              <form
                style={{ display: "flex", gap: 8, marginTop: 12 }}
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!expAmount) return;
                  act(api.addExpense(open.id, { amount: Number(expAmount), description: expDesc }), open.id);
                  setExpAmount("");
                  setExpDesc("");
                }}
              >
                <input className="input" value={expDesc} onChange={(e) => setExpDesc(e.target.value)} placeholder="Expense" />
                <input className="input" style={{ width: 110 }} type="number" min={0} value={expAmount} onChange={(e) => setExpAmount(e.target.value)} placeholder="$" />
                <button className="btn sm">Add</button>
              </form>
              {(open.risks.length > 0 || open.controls.length > 0) && (
                <div style={{ marginTop: 14, fontSize: 12 }} className="muted">
                  Addresses:{" "}
                  {[...open.risks, ...open.controls].map((l) => l.reference || l.name).join(", ")}
                </div>
              )}
            </div>
          </div>
        </div>
        <RecordPanels model="project" entityId={open.id} />
        </>
      )}
    </>
  );
}
