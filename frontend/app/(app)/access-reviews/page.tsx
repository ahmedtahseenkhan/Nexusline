"use client";

import { useEffect, useState } from "react";
import { api, type AccessReview } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconUsers } from "@/components/icons";

const STATUS_TONE: Record<string, "low" | "medium" | "neutral"> = {
  completed: "low",
  in_progress: "medium",
  draft: "neutral",
};
const DECISION_TONE: Record<string, "low" | "critical" | "neutral"> = {
  keep: "low",
  revoke: "critical",
  pending: "neutral",
};

export default function AccessReviewsPage() {
  const [items, setItems] = useState<AccessReview[]>([]);
  const [open, setOpen] = useState<AccessReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [system, setSystem] = useState("");
  const [reviewer, setReviewer] = useState("");

  const [user, setUser] = useState("");
  const [accessText, setAccessText] = useState("");

  async function load(keep?: string) {
    try {
      const r = await api.accessReviews();
      setItems(r.items);
      if (keep) setOpen(r.items.find((x) => x.id === keep) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function act(fn: Promise<unknown>, keep?: string) {
    setError(null);
    try {
      await fn;
      await load(keep);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    await act(api.createAccessReview({ name, system_name: system, reviewer, status: "in_progress" }));
    setShowForm(false);
    setName("");
    setSystem("");
    setReviewer("");
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Access Reviews</h1>
          <p>Periodic access certification — keep or revoke each account.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New review"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Name</label>
          <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Q4 Admin Access Review" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">System</label>
              <input className="input" value={system} onChange={(e) => setSystem(e.target.value)} placeholder="e.g. Production AWS" />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Reviewer</label>
              <input className="input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create review</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Certification campaigns</h3>
          <span className="sub">{items.length} total · click to certify</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Ref</th><th>Name</th><th>System</th><th>Status</th><th>Progress</th><th>Keep / Revoke</th><th>Due</th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === r.id ? null : r)}>
                  <td className="ref">{r.reference}</td>
                  <td className="cell-title">{r.name}</td>
                  <td className="muted">{r.system_name || (r.asset ? r.asset.name : "—")}</td>
                  <td><Badge tone={STATUS_TONE[r.status] || "neutral"}>{r.status.replace(/_/g, " ")}</Badge></td>
                  <td style={{ minWidth: 130 }}>
                    <div className="progress"><span style={{ width: `${r.completion_pct}%` }} /></div>
                    <span className="muted" style={{ fontSize: 11 }}>{r.reviewed_count}/{r.total_items}</span>
                  </td>
                  <td className="muted"><span style={{ color: "var(--green)" }}>{r.keep_count}</span> / <span style={{ color: "var(--red)" }}>{r.revoke_count}</span></td>
                  <td className="muted">{r.due_date || "—"}{r.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={7}><div className="empty"><span className="ico"><IconUsers width={24} height={24} /></span><h3>No access reviews</h3></div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>Accounts · {open.reference}</h3>
              <span className="sub">{open.reviewed_count}/{open.total_items} certified</span>
            </div>
            {open.status !== "completed" && open.total_items > 0 && (
              <button className="btn" onClick={() => act(api.completeAccessReview(open.id), open.id)}>
                <IconCheck width={14} height={14} /> Complete review
              </button>
            )}
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Account</th><th>Access</th><th>Decision</th><th></th></tr>
              </thead>
              <tbody>
                {open.items.map((it) => (
                  <tr key={it.id}>
                    <td className="cell-title">{it.username}<div className="when">{it.display_name}</div></td>
                    <td className="muted">{it.access || "—"}</td>
                    <td><Badge tone={DECISION_TONE[it.decision] || "neutral"}>{it.decision}</Badge></td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn secondary sm" onClick={() => act(api.decideReviewItem(open.id, it.id, { decision: "keep" }), open.id)}>Keep</button>
                        <button className="btn secondary sm" onClick={() => act(api.decideReviewItem(open.id, it.id, { decision: "revoke" }), open.id)}>Revoke</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {open.items.length === 0 && (<tr><td colSpan={4} className="muted" style={{ padding: 16 }}>No accounts yet.</td></tr>)}
              </tbody>
            </table>
          </div>
          <form
            className="card-pad"
            style={{ display: "flex", gap: 8, borderTop: "1px solid var(--border)" }}
            onSubmit={(e) => {
              e.preventDefault();
              if (!user) return;
              act(api.addReviewItem(open.id, { username: user, access: accessText }), open.id);
              setUser("");
              setAccessText("");
            }}
          >
            <input className="input" value={user} onChange={(e) => setUser(e.target.value)} placeholder="username" style={{ width: 180 }} />
            <input className="input" value={accessText} onChange={(e) => setAccessText(e.target.value)} placeholder="access / roles held" />
            <button className="btn sm">Add account</button>
          </form>
        </div>
      )}
    </>
  );
}
