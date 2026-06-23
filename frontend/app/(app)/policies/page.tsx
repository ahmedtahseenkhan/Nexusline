"use client";

import { useEffect, useState } from "react";
import { api, type Policy } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconPolicy } from "@/components/icons";

const POLICY_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  published: "low",
  approved: "info",
  under_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

export default function PoliciesPage() {
  const [items, setItems] = useState<Policy[]>([]);
  const [open, setOpen] = useState<Policy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("");
  const [owner, setOwner] = useState("");

  async function load() {
    try {
      setItems((await api.policies()).items);
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
      await api.createPolicy({ title, category, owner });
      setShowForm(false);
      setTitle("");
      setCategory("");
      setOwner("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create policy");
    }
  }

  async function acknowledge(id: string, ref: string) {
    setError(null);
    try {
      await api.acknowledgePolicy(id);
      setNote(`You acknowledged ${ref}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to acknowledge");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Policy Management</h1>
          <p>Repository for policies with versioning, review cycles and acknowledgments.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New policy"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
      {note && (
        <div className="card card-pad" style={{ marginBottom: 16, borderColor: "var(--primary)" }}>
          {note}
        </div>
      )}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Title</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Data Retention Policy" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Category</label>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Security" />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Owner</label>
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="CISO" />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create policy</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Policies</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Version</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Acks</th>
                <th>Next review</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === p.id ? null : p)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">{p.title}</td>
                  <td className="muted">v{p.version}</td>
                  <td><Badge tone={POLICY_TONE[p.status] || "neutral"}>{p.status.replace(/_/g, " ")}</Badge></td>
                  <td className="muted">{p.owner || "—"}</td>
                  <td><Badge tone="info" plain>{p.acknowledgment_count}</Badge></td>
                  <td className="muted">{p.next_review_date || "—"}</td>
                  <td>
                    <button className="btn secondary sm" onClick={(e) => { e.stopPropagation(); acknowledge(p.id, p.reference); }}>
                      <IconCheck width={14} height={14} /> Acknowledge
                    </button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="empty">
                      <span className="ico"><IconPolicy width={24} height={24} /></span>
                      <h3>No policies</h3>
                      <p>Create your first policy to build the repository.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {open && <RecordPanels model="policy" entityId={open.id} />}
    </>
  );
}
