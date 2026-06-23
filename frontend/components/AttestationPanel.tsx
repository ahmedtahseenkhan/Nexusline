"use client";

import { useEffect, useState } from "react";
import { api, type AttestationStatus } from "@/lib/api";
import { Badge } from "@/components/badges";

const TONE: Record<string, "low" | "high" | "neutral"> = {
  current: "low",
  overdue: "high",
  never: "neutral",
};
const FREQS = ["monthly", "quarterly", "semiannual", "annual", "none"];

/** Periodic review sign-off for any record. */
export default function AttestationPanel({ entityType, entityId }: { entityType: string; entityId: string }) {
  const [data, setData] = useState<AttestationStatus | null>(null);
  const [frequency, setFrequency] = useState("annual");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const d = await api.attestation(entityType, entityId).catch(() => null);
    setData(d);
    if (d?.frequency) setFrequency(d.frequency);
  }
  useEffect(() => {
    load();
  }, [entityType, entityId]);

  if (!data) return null;

  async function attest() {
    setBusy(true);
    try {
      await api.attest(entityType, entityId, { frequency, comment });
      setComment("");
      await load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3>Review &amp; Attestation</h3>
        <Badge tone={TONE[data.status] || "neutral"}>{data.status}</Badge>
      </div>
      <div className="card-pad">
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13, marginBottom: 14 }}>
          <div><span className="muted">Last reviewed</span><br /><b>{data.last_attested_at || "Never"}</b></div>
          <div><span className="muted">By</span><br /><b>{data.last_by || "—"}</b></div>
          <div><span className="muted">Next due</span><br /><b>{data.next_due || "—"}</b></div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: "0 0 140px" }}>
            <label className="label">Frequency</label>
            <select className="input" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
              {FREQS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div style={{ flex: "1 1 200px" }}>
            <label className="label">Comment</label>
            <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Reviewed — no changes" />
          </div>
          <button className="btn" onClick={attest} disabled={busy}>{busy ? "Saving…" : "Attest now"}</button>
        </div>

        {data.history.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <label className="label">History</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {data.history.map((h) => (
                <div key={h.id} style={{ display: "flex", gap: 10, fontSize: 12.5, alignItems: "center" }}>
                  <span className="muted" style={{ width: 90 }}>{h.attested_at}</span>
                  <b>{h.attested_by_email}</b>
                  <span className="muted">({h.frequency} · next {h.next_due || "—"})</span>
                  {h.comment && <span style={{ marginLeft: "auto" }} className="muted">{h.comment}</span>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
