"use client";

import { useEffect, useState } from "react";
import {
  api,
  type Control,
  type ControlAudit,
  type ControlMaintenance,
} from "@/lib/api";
import { Badge, EffectivenessBadge, StatusBadge } from "@/components/badges";
import { IconControl, IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

const RESULT_TONE: Record<string, "low" | "critical" | "neutral"> = {
  passed: "low",
  failed: "critical",
  not_assessed: "neutral",
};

function ResultBadge({ value }: { value: string | null }) {
  if (!value || value === "not_assessed") return <span className="muted">—</span>;
  return <Badge tone={RESULT_TONE[value] || "neutral"}>{value}</Badge>;
}

export default function ControlsPage() {
  const [controls, setControls] = useState<Control[]>([]);
  const [open, setOpen] = useState<Control | null>(null);
  const [audits, setAudits] = useState<ControlAudit[]>([]);
  const [maints, setMaints] = useState<ControlMaintenance[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [reference, setReference] = useState("");
  const [owner, setOwner] = useState("");

  const [auditResult, setAuditResult] = useState("passed");
  const [auditNote, setAuditNote] = useState("");
  const [maintResult, setMaintResult] = useState("passed");
  const [maintTask, setMaintTask] = useState("");

  async function load(keepOpen?: string) {
    try {
      const c = await api.controls();
      setControls(c.items);
      if (keepOpen) {
        const k = c.items.find((x) => x.id === keepOpen) || null;
        setOpen(k);
        if (k) {
          const [a, m] = await Promise.all([api.controlAudits(k.id), api.controlMaintenances(k.id)]);
          setAudits(a);
          setMaints(m);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function openControl(c: Control) {
    if (open?.id === c.id) {
      setOpen(null);
      return;
    }
    setOpen(c);
    setError(null);
    try {
      const [a, m] = await Promise.all([api.controlAudits(c.id), api.controlMaintenances(c.id)]);
      setAudits(a);
      setMaints(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load detail");
    }
  }

  async function act(fn: Promise<unknown>, keepOpen?: string) {
    setError(null);
    try {
      await fn;
      await load(keepOpen);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    await act(api.createControl({ name, reference, owner }));
    setShowForm(false);
    setName("");
    setReference("");
    setOwner("");
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Control Catalog</h1>
          <p>Reusable controls with recurring audit &amp; maintenance test cycles.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New control"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 280px" }}>
              <label className="label">Name</label>
              <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Multi-factor authentication" />
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Reference</label>
              <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="A.8.5" />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Owner</label>
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create control</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>All controls</h3>
          <span className="sub">{controls.length} total · click a row to test</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Reference</th>
                <th>Name</th>
                <th>Status</th>
                <th>Effectiveness</th>
                <th>Last audit</th>
                <th>Next audit</th>
                <th>Next maint.</th>
              </tr>
            </thead>
            <tbody>
              {controls.map((c) => (
                <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => openControl(c)}>
                  <td className="ref">{c.reference || "—"}</td>
                  <td className="cell-title">{c.name}</td>
                  <td><StatusBadge value={c.status} tone="neutral" /></td>
                  <td><EffectivenessBadge value={c.effectiveness} /></td>
                  <td><ResultBadge value={c.last_audit_result} /></td>
                  <td className="muted">
                    {c.next_audit_date || "—"}{c.is_audit_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">due</Badge></span>}
                  </td>
                  <td className="muted">
                    {c.next_maintenance_date || "—"}{c.is_maintenance_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">due</Badge></span>}
                  </td>
                </tr>
              ))}
              {controls.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconControl width={24} height={24} /></span>
                      <h3>No controls yet</h3>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (<>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="card">
            <div className="card-head">
              <h3>Audits · {open.reference || open.name}</h3>
              <span className="sub">every {open.audit_frequency}</span>
            </div>
            <div className="card-pad">
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end" }}
                onSubmit={(e) => {
                  e.preventDefault();
                  act(api.recordControlAudit(open.id, { result: auditResult, result_description: auditNote }), open.id);
                  setAuditNote("");
                }}
              >
                <div style={{ width: 130 }}>
                  <label className="label">Result</label>
                  <select className="select" value={auditResult} onChange={(e) => setAuditResult(e.target.value)}>
                    <option value="passed">passed</option>
                    <option value="failed">failed</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label className="label">Notes</label>
                  <input className="input" value={auditNote} onChange={(e) => setAuditNote(e.target.value)} placeholder="Audit conclusion" />
                </div>
                <button className="btn">Record</button>
              </form>
              {audits.length ? audits.map((a) => (
                <div key={a.id} className="activity-item">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{a.result_description || "Audit"}</div>
                    <div className="when">{a.conducted_date || "—"} · {a.auditor || "—"}</div>
                  </div>
                  <ResultBadge value={a.result} />
                </div>
              )) : <span className="muted">No audits recorded yet.</span>}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Maintenances · {open.reference || open.name}</h3>
              <span className="sub">every {open.maintenance_frequency}</span>
            </div>
            <div className="card-pad">
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end" }}
                onSubmit={(e) => {
                  e.preventDefault();
                  act(api.recordControlMaintenance(open.id, { result: maintResult, task: maintTask }), open.id);
                  setMaintTask("");
                }}
              >
                <div style={{ width: 130 }}>
                  <label className="label">Result</label>
                  <select className="select" value={maintResult} onChange={(e) => setMaintResult(e.target.value)}>
                    <option value="passed">passed</option>
                    <option value="failed">failed</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label className="label">Task</label>
                  <input className="input" value={maintTask} onChange={(e) => setMaintTask(e.target.value)} placeholder="e.g. Rotate keys" />
                </div>
                <button className="btn">Record</button>
              </form>
              {maints.length ? maints.map((m) => (
                <div key={m.id} className="activity-item">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{m.task || "Maintenance"}</div>
                    <div className="when">{m.conducted_date || "—"}</div>
                  </div>
                  <ResultBadge value={m.result} />
                </div>
              )) : <span className="muted">No maintenances recorded yet.</span>}
            </div>
          </div>
        </div>
        <RecordPanels model="control" entityId={open.id} />
        </>
      )}
    </>
  );
}
