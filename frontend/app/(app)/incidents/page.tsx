"use client";

import { useEffect, useState } from "react";
import { api, type Incident } from "@/lib/api";
import { Badge, Severity, StatusBadge } from "@/components/badges";
import { IconCheck, IconPlus, IconShield } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

const SEVERITIES = ["low", "medium", "high", "critical"];
const STAGE_TONE: Record<string, "low" | "medium" | "neutral"> = {
  done: "low",
  in_progress: "medium",
  pending: "neutral",
};

export default function IncidentsPage() {
  const [items, setItems] = useState<Incident[]>([]);
  const [open, setOpen] = useState<Incident | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [severity, setSeverity] = useState("medium");
  const [assignee, setAssignee] = useState("");

  async function load(keep?: string) {
    try {
      const list = (await api.incidents()).items;
      setItems(list);
      if (keep) setOpen(list.find((x) => x.id === keep) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function advance(stageId: string, status: string) {
    if (!open) return;
    setError(null);
    try {
      await api.updateIncidentStage(open.id, stageId, { status });
      await load(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update stage");
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createIncident({ title, category, severity, assignee });
      setShowForm(false);
      setTitle("");
      setCategory("");
      setAssignee("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create incident");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Security Operations</h1>
          <p>Log, triage and resolve security incidents.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "Log incident"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Title</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Suspicious login from unknown IP" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Category</label>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Phishing" />
            </div>
            <div style={{ width: 160 }}>
              <label className="label">Severity</label>
              <select className="select" value={severity} onChange={(e) => setSeverity(e.target.value)}>
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Assignee</label>
              <input className="input" value={assignee} onChange={(e) => setAssignee(e.target.value)} placeholder="SOC Team" />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create incident</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Incidents</h3>
          <span className="sub">{items.length} total · click to manage lifecycle</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Lifecycle</th>
                <th>Assignee</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === i.id ? null : i)}>
                  <td className="ref">{i.reference}</td>
                  <td className="cell-title">{i.title}</td>
                  <td><Severity value={i.severity} /></td>
                  <td><StatusBadge value={i.status} /></td>
                  <td style={{ minWidth: 150 }}>
                    {i.lifecycle_complete ? (
                      <Badge tone="low"><IconCheck width={11} height={11} /> complete</Badge>
                    ) : (
                      <>
                        <div className="progress"><span style={{ width: `${(i.completed_stages / (i.stage_count || 1)) * 100}%` }} /></div>
                        <span className="muted" style={{ fontSize: 11 }}>{i.current_stage || "—"} ({i.completed_stages}/{i.stage_count})</span>
                      </>
                    )}
                  </td>
                  <td className="muted">{i.assignee || "—"}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <div className="empty">
                      <span className="ico"><IconShield width={24} height={24} /></span>
                      <h3>No incidents</h3>
                      <p>Log your first security incident to begin tracking.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (<>
        <div className="card">
          <div className="card-head">
            <h3>Response lifecycle · {open.reference}</h3>
            <span className="sub">{open.completed_stages}/{open.stage_count} stages done</span>
          </div>
          <div className="card-pad">
            {open.stages.map((s) => (
              <div key={s.id} className="activity-item" style={{ alignItems: "center" }}>
                <span style={{ width: 24, textAlign: "center", color: "var(--faint)" }}>{s.order_index + 1}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13 }}>{s.name}</div>
                  {s.completed_at && <div className="when">completed {s.completed_at}</div>}
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
        <RecordPanels model="incident" entityId={open.id} />
        </>
      )}
    </>
  );
}
