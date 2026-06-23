"use client";

import { useEffect, useState } from "react";
import { api, type ExceptionRecord, type Risk } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconAlert } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  pending: "medium",
  rejected: "critical",
  expired: "high",
  closed: "neutral",
};
const TYPES = ["risk", "policy", "compliance", "other"];

export default function ExceptionsPage() {
  const [items, setItems] = useState<ExceptionRecord[]>([]);
  const [open, setOpen] = useState<ExceptionRecord | null>(null);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [type, setType] = useState("risk");
  const [rationale, setRationale] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [riskId, setRiskId] = useState("");

  async function load() {
    try {
      const [ex, rk] = await Promise.all([api.exceptions(), api.risks()]);
      setItems(ex.items);
      setRisks(rk.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createException({
        title,
        exception_type: type,
        rationale,
        expires_at: expiresAt || null,
        risk_ids: type === "risk" && riskId ? [riskId] : [],
      });
      setShowForm(false);
      setTitle("");
      setRationale("");
      setExpiresAt("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  async function act(fn: Promise<unknown>) {
    setError(null);
    try {
      await fn;
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Exceptions</h1>
          <p>Formal, time-boxed acceptance of risk, policy or compliance gaps.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "Request exception"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Title</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Accept legacy TLS until Q4 migration" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ width: 170 }}>
              <label className="label">Type</label>
              <select className="select" value={type} onChange={(e) => setType(e.target.value)}>
                {TYPES.map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Expires</label>
              <input className="input" type="date" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
            </div>
            {type === "risk" && (
              <div style={{ flex: "1 1 240px" }}>
                <label className="label">Linked risk</label>
                <select className="select" value={riskId} onChange={(e) => setRiskId(e.target.value)}>
                  <option value="">— none —</option>
                  {risks.map((r) => (<option key={r.id} value={r.id}>{r.reference} — {r.title}</option>))}
                </select>
              </div>
            )}
          </div>
          <label className="label">Rationale</label>
          <textarea className="input" value={rationale} onChange={(e) => setRationale(e.target.value)} rows={2} placeholder="Business justification for accepting this gap" />
          <button className="btn" style={{ marginTop: 16 }}>Submit for approval</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Exception register</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Type</th>
                <th>Status</th>
                <th>Linked</th>
                <th>Expires</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((x) => (
                <tr key={x.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === x.id ? null : x)}>
                  <td className="ref">{x.reference}</td>
                  <td className="cell-title">{x.title}</td>
                  <td><Badge tone="info" plain>{x.exception_type}</Badge></td>
                  <td>
                    <Badge tone={STATUS_TONE[x.status] || "neutral"}>{x.status}</Badge>
                    {x.is_expired && <span style={{ marginLeft: 6 }}><Badge tone="high">expired</Badge></span>}
                  </td>
                  <td className="muted">
                    {[...x.risks, ...x.policies, ...x.requirements].map((l) => l.reference).join(", ") || "—"}
                  </td>
                  <td className="muted">{x.expires_at || "—"}</td>
                  <td>
                    {x.status === "pending" && (
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn sm" onClick={(e) => { e.stopPropagation(); act(api.decideException(x.id, true)); }}>
                          <IconCheck width={13} height={13} /> Approve
                        </button>
                        <button className="btn secondary sm" onClick={(e) => { e.stopPropagation(); act(api.decideException(x.id, false)); }}>Reject</button>
                      </div>
                    )}
                    {x.status === "approved" && (
                      <button className="btn secondary sm" onClick={(e) => { e.stopPropagation(); act(api.closeException(x.id)); }}>Close</button>
                    )}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconAlert width={24} height={24} /></span>
                      <h3>No exceptions</h3>
                      <p>Request an exception to formally accept a gap with an expiry date.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {open && <RecordPanels model="exception" entityId={open.id} />}
    </>
  );
}
