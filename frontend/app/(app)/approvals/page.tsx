"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type ApprovalRequest } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

const TONE: Record<string, "low" | "medium" | "critical" | "neutral"> = {
  approved: "low",
  pending: "medium",
  rejected: "critical",
  cancelled: "neutral",
};

export default function ApprovalsPage() {
  const [items, setItems] = useState<ApprovalRequest[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [approver, setApprover] = useState("");
  const [description, setDescription] = useState("");
  const [required, setRequired] = useState(1);

  async function load() {
    try {
      setItems((await api.approvals()).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function act(fn: Promise<unknown>) {
    setError(null);
    try {
      await fn;
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await act(api.submitApproval({ title, approver, description, required_approvals: required }));
    setShowForm(false);
    setTitle("");
    setApprover("");
    setDescription("");
    setRequired(1);
  }

  function reject(id: string) {
    const reason = window.prompt("Reason for rejection (required):");
    if (reason && reason.trim()) act(api.decideApproval(id, false, reason.trim()));
  }

  const pending = items.filter((i) => i.status === "pending");

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Approvals</h1>
          <p>Submit records for approval and track decisions across the org.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New request"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={submit}>
          <label className="label">What needs approval?</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Publish Data Retention Policy" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Approver</label>
              <input className="input" value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="e.g. CISO" />
            </div>
            <div style={{ flex: "1 1 280px" }}>
              <label className="label">Notes</label>
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div style={{ flex: "0 0 180px" }}>
              <label className="label">Approvals required</label>
              <select className="input" value={required} onChange={(e) => setRequired(Number(e.target.value))}>
                <option value={1}>1 — four-eyes</option>
                <option value={2}>2 — six-eyes</option>
                <option value={3}>3 checkers</option>
              </select>
            </div>
          </div>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
            Maker-checker: the submitter cannot approve their own request; {required} independent
            checker{required !== 1 ? "s" : ""} must approve before it is granted.
          </p>
          <button className="btn" style={{ marginTop: 12 }}>Submit for approval</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Awaiting decision</h3>
          <span className="sub">{pending.length} pending</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Ref</th><th>Title</th><th>Maker</th><th>Approvals</th><th>Due</th><th></th></tr></thead>
            <tbody>
              {pending.map((a) => (
                <tr key={a.id}>
                  <td className="ref">{a.reference}</td>
                  <td className="cell-title">
                    {a.title}
                    {a.link && a.entity_label && <Link href={a.link} style={{ marginLeft: 8, fontSize: 12 }}>{a.entity_label}</Link>}
                  </td>
                  <td className="muted">{a.requested_by_email}</td>
                  <td>
                    <Badge tone={a.approvals_received >= a.required_approvals ? "low" : "medium"}>
                      {a.approvals_received}/{a.required_approvals}
                    </Badge>
                  </td>
                  <td className="muted">{a.due_date || "—"}{a.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn sm" onClick={() => act(api.decideApproval(a.id, true))} title="An independent checker approves"><IconCheck width={13} height={13} /> Approve</button>
                      <button className="btn secondary sm" onClick={() => reject(a.id)}>Reject</button>
                      <button className="btn secondary sm" onClick={() => act(api.cancelApproval(a.id))}>Cancel</button>
                    </div>
                  </td>
                </tr>
              ))}
              {pending.length === 0 && (<tr><td colSpan={6}><div className="empty"><span className="ico"><IconCheck width={24} height={24} /></span><h3>Nothing awaiting approval</h3></div></td></tr>)}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>All requests</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Ref</th><th>Title</th><th>Status</th><th>Decided by</th><th>Comment</th></tr></thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="ref">{a.reference}</td>
                  <td className="cell-title">{a.title}</td>
                  <td><Badge tone={TONE[a.status] || "neutral"}>{a.status}</Badge></td>
                  <td className="muted">{a.decided_by_email || "—"}</td>
                  <td className="muted">{a.decision_comment || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
