"use client";

import { useEffect, useState } from "react";
import { api, type Control, type Evidence } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconEvidence, IconPlus } from "@/components/icons";

const TYPES = ["document", "screenshot", "log", "link", "configuration", "other"];
const STATUS_TONE: Record<string, "low" | "medium" | "critical" | "neutral"> = {
  valid: "low",
  pending: "medium",
  expired: "critical",
};

export default function EvidencePage() {
  const [items, setItems] = useState<Evidence[]>([]);
  const [controls, setControls] = useState<Control[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [controlId, setControlId] = useState("");
  const [title, setTitle] = useState("");
  const [evidenceType, setEvidenceType] = useState("document");
  const [reference, setReference] = useState("");

  async function load() {
    try {
      const [ev, ctrls] = await Promise.all([api.evidence(), api.controls()]);
      setItems(ev.items);
      setControls(ctrls.items);
      if (!controlId && ctrls.items.length) setControlId(ctrls.items[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createEvidence({
        control_id: controlId,
        title,
        evidence_type: evidenceType,
        reference,
      });
      setShowForm(false);
      setTitle("");
      setReference("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add evidence");
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.deleteEvidence(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Evidence</h1>
          <p>Audit-ready artifacts attached to controls — collect once, satisfy many.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)} disabled={!controls.length}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "Add evidence"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 240px" }}>
              <label className="label">Control</label>
              <select className="select" value={controlId} onChange={(e) => setControlId(e.target.value)}>
                {controls.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.reference ? `${c.reference} — ` : ""}{c.name}
                  </option>
                ))}
              </select>
            </div>
            <div style={{ width: 170 }}>
              <label className="label">Type</label>
              <select className="select" value={evidenceType} onChange={(e) => setEvidenceType(e.target.value)}>
                {TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          </div>
          <label className="label">Title</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Q2 access review export" />
          <label className="label">Reference (URL or location)</label>
          <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="https://…" />
          <button className="btn" style={{ marginTop: 16 }}>Add evidence</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Collected evidence</h3>
          <span className="sub">{items.length} items</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Control</th>
                <th>Type</th>
                <th>Status</th>
                <th>Reference</th>
                <th>Collected</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((ev) => (
                <tr key={ev.id}>
                  <td className="cell-title">{ev.title}</td>
                  <td className="muted">
                    {ev.control ? (ev.control.reference || ev.control.name) : "—"}
                  </td>
                  <td><Badge tone="info" plain>{ev.evidence_type}</Badge></td>
                  <td><Badge tone={STATUS_TONE[ev.status] || "neutral"}>{ev.status}</Badge></td>
                  <td className="muted" style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {ev.reference ? <a href={ev.reference} target="_blank" rel="noreferrer">{ev.reference}</a> : "—"}
                  </td>
                  <td className="muted">{ev.collected_at || "—"}</td>
                  <td>
                    <button className="btn secondary sm" onClick={() => remove(ev.id)}>Delete</button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconEvidence width={24} height={24} /></span>
                      <h3>No evidence yet</h3>
                      <p>Attach evidence to a control to demonstrate compliance.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
