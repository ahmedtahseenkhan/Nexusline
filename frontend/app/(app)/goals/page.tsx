"use client";

import { useEffect, useState } from "react";
import { api, type Goal, type Risk } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconGauge, IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  achieved: "low",
  on_track: "info",
  at_risk: "medium",
  off_track: "critical",
  not_started: "neutral",
};
const RESULT_TONE: Record<string, "low" | "critical" | "neutral"> = {
  passed: "low",
  failed: "critical",
  not_assessed: "neutral",
};
const FREQ = ["annual", "semiannual", "quarterly", "monthly", "none"];
const STATUSES = ["not_started", "on_track", "at_risk", "off_track", "achieved"];

export default function GoalsPage() {
  const [items, setItems] = useState<Goal[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [open, setOpen] = useState<Goal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [name, setName] = useState("");
  const [owner, setOwner] = useState("");
  const [statusVal, setStatusVal] = useState("on_track");
  const [frequency, setFrequency] = useState("annual");
  const [riskId, setRiskId] = useState("");

  const [auditResult, setAuditResult] = useState("passed");
  const [auditNote, setAuditNote] = useState("");

  async function load(keepOpen?: string) {
    try {
      const [g, rk] = await Promise.all([api.goals(), api.risks()]);
      setItems(g.items);
      setRisks(rk.items);
      if (keepOpen) setOpen(g.items.find((x) => x.id === keepOpen) || null);
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

  async function createGoal(e: React.FormEvent) {
    e.preventDefault();
    await act(
      api.createGoal({
        name,
        owner,
        status: statusVal,
        audit_frequency: frequency,
        risk_ids: riskId ? [riskId] : [],
      })
    );
    setShowForm(false);
    setName("");
    setOwner("");
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Strategy &amp; Goals</h1>
          <p>Strategic goals with a recurring pass/fail audit cycle.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New goal"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={createGoal}>
          <label className="label">Goal</label>
          <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Achieve SOC 2 Type II" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Owner</label>
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} />
            </div>
            <div style={{ width: 160 }}>
              <label className="label">Status</label>
              <select className="select" value={statusVal} onChange={(e) => setStatusVal(e.target.value)}>
                {STATUSES.map((s) => (<option key={s} value={s}>{s.replace(/_/g, " ")}</option>))}
              </select>
            </div>
            <div style={{ width: 160 }}>
              <label className="label">Audit every</label>
              <select className="select" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
                {FREQ.map((f) => (<option key={f} value={f}>{f}</option>))}
              </select>
            </div>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Linked risk</label>
              <select className="select" value={riskId} onChange={(e) => setRiskId(e.target.value)}>
                <option value="">— none —</option>
                {risks.map((r) => (<option key={r.id} value={r.id}>{r.reference} — {r.title}</option>))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create goal</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Goals</h3>
          <span className="sub">{items.length} total · click a row to audit</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Goal</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Last result</th>
                <th>Audits</th>
                <th>Next audit</th>
              </tr>
            </thead>
            <tbody>
              {items.map((g) => (
                <tr key={g.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === g.id ? null : g)}>
                  <td className="ref">{g.reference}</td>
                  <td className="cell-title">{g.name}</td>
                  <td className="muted">{g.owner || "—"}</td>
                  <td><Badge tone={STATUS_TONE[g.status] || "neutral"}>{g.status.replace(/_/g, " ")}</Badge></td>
                  <td>{g.last_result ? <Badge tone={RESULT_TONE[g.last_result] || "neutral"}>{g.last_result.replace(/_/g, " ")}</Badge> : <span className="muted">—</span>}</td>
                  <td className="muted">{g.audit_count}</td>
                  <td className="muted">
                    {g.next_audit_date || "—"}{g.is_audit_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconGauge width={24} height={24} /></span>
                      <h3>No goals</h3>
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
            <h3>Audit history · {open.reference}</h3>
            <span className="sub">{open.audit_metric || "no metric defined"}</span>
          </div>
          <div className="card-pad">
            <form
              style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end" }}
              onSubmit={(e) => {
                e.preventDefault();
                act(api.recordGoalAudit(open.id, { result: auditResult, result_description: auditNote }), open.id);
                setAuditNote("");
              }}
            >
              <div style={{ width: 150 }}>
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
              <button className="btn">Record audit</button>
            </form>

            {open.audits.length ? (
              open.audits.map((a) => (
                <div key={a.id} className="activity-item">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{a.result_description || "Audit"}</div>
                    <div className="when">
                      {a.conducted_date || a.planned_date || "—"} · {a.auditor || "—"}
                    </div>
                  </div>
                  <Badge tone={RESULT_TONE[a.result] || "neutral"}>{a.result.replace(/_/g, " ")}</Badge>
                </div>
              ))
            ) : (
              <span className="muted">No audits recorded yet.</span>
            )}
          </div>
        </div>
        <RecordPanels model="goal" entityId={open.id} />
        </>
      )}
    </>
  );
}
