"use client";

import { useEffect, useState } from "react";
import { api, type AttestationStatus } from "@/lib/api";
import { Badge } from "@/components/badges";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";

const TONE: Record<string, "low" | "high" | "neutral"> = {
  current: "low",
  overdue: "high",
  never: "neutral",
};
const FREQS = ["fortnightly", "monthly", "quarterly", "semiannual", "annual", "none"];

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

/** Periodic review sign-off for any record.
 *
 *  An attestation certifies a stated sentence, signed by someone independent of the
 *  record (not its owner, not the person who entered it) once it is out of draft; a
 *  second person may confirm it. Records that carry their own review cycle (risk,
 *  policy, third party) take the cadence from that cycle, so there is one review date. */
export default function AttestationPanel({ entityType, entityId }: { entityType: string; entityId: string }) {
  const { formatDate, formatDateTime } = useFormat();
  const [data, setData] = useState<AttestationStatus | null>(null);
  const [meId, setMeId] = useState<string | null>(null);
  const [frequency, setFrequency] = useState("annual");
  const [statement, setStatement] = useState("");
  const [scope, setScope] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);

  async function load() {
    const d = await api.attestation(entityType, entityId).catch(() => null);
    setData(d);
    if (d?.frequency) setFrequency(d.frequency);
    if (d) setStatement((s) => s || d.default_statement);
  }
  useEffect(() => {
    setStatement("");
    setScope("");
    setComment("");
    load();
  }, [entityType, entityId]);
  useEffect(() => {
    api.me().then((m) => setMeId(m.id)).catch(() => setMeId(null));
  }, []);

  if (!data) return null;

  async function attest() {
    if (!data) return;
    setBusy(true);
    try {
      const payload: Record<string, unknown> = { comment, statement: statement.trim(), scope: scope.trim() };
      if (!data.native_review) payload.frequency = frequency;
      const d = await api.attest(entityType, entityId, payload);
      setData(d);
      setComment("");
      setScope("");
      toast("Attestation recorded");
    } catch (e) {
      toast(errMsg(e, "Could not record the attestation"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function confirm(id: string) {
    setConfirming(id);
    try {
      const d = await api.confirmAttestation(id);
      setData(d);
      toast("Attestation confirmed");
    } catch (e) {
      toast(errMsg(e, "Could not confirm the attestation"), "error");
    } finally {
      setConfirming(null);
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
          <div><span className="muted">Last attested</span><br /><b>{data.last_attested_at ? formatDateTime(data.last_attested_at) : "Never"}</b></div>
          <div><span className="muted">By</span><br /><b>{data.last_by || "—"}</b></div>
          <div><span className="muted">Next due</span><br /><b>{formatDate(data.next_due)}</b></div>
        </div>

        <div style={{ display: "grid", gap: 10 }}>
          <div>
            <label className="label" htmlFor={`att-statement-${entityId}`}>Statement you are signing</label>
            <textarea
              id={`att-statement-${entityId}`}
              className="input"
              rows={2}
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              placeholder={data.default_statement}
            />
          </div>
          <div>
            <label className="label" htmlFor={`att-scope-${entityId}`}>Scope (optional)</label>
            <input
              id={`att-scope-${entityId}`}
              className="input"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
              placeholder="What you looked at, e.g. Q3 loss data, latest control tests"
            />
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
            {data.native_review ? (
              <div style={{ flex: "1 1 100%", fontSize: 12.5 }} className="muted">
                Next review: <b>{data.next_due ? formatDate(data.next_due) : "not scheduled"}</b>, from this record&apos;s review cycle
                {data.frequency ? ` (${data.frequency})` : ""}. Attesting records the review and moves that date.
              </div>
            ) : (
              <div style={{ flex: "0 0 140px" }}>
                <label className="label" htmlFor={`att-freq-${entityId}`}>Frequency</label>
                <select id={`att-freq-${entityId}`} className="input" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
                  {FREQS.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
              </div>
            )}
            <div style={{ flex: "1 1 200px" }}>
              <label className="label" htmlFor={`att-comment-${entityId}`}>Comment</label>
              <input id={`att-comment-${entityId}`} className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Reviewed — no changes" />
            </div>
            <button className="btn" onClick={attest} disabled={busy || !statement.trim()}>{busy ? "Saving…" : "Attest now"}</button>
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            The record&apos;s owner and the person who entered it can&apos;t attest it, and a draft must be submitted for review first.
          </div>
        </div>

        {data.history.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <label className="label">History</label>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {data.history.map((h) => {
                const canConfirm = !h.confirmed_by_id && meId !== null && h.attested_by_id !== meId;
                return (
                  <div key={h.id} style={{ fontSize: 12.5, borderTop: "1px solid var(--border, #eef1f5)", paddingTop: 8 }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                      <span className="muted" style={{ minWidth: 90 }}>{formatDateTime(h.attested_at)}</span>
                      <span>Signed by <b>{h.attested_by_email || "—"}</b></span>
                      <span className="muted">({h.frequency} · next {formatDate(h.next_due)})</span>
                      <span style={{ marginLeft: "auto" }}>
                        {h.confirmed_by_id ? (
                          <span className="muted">Confirmed by <b>{h.confirmed_by_email || "another user"}</b>{h.confirmed_at ? ` on ${formatDateTime(h.confirmed_at)}` : ""}</span>
                        ) : canConfirm ? (
                          <button className="btn secondary sm" onClick={() => confirm(h.id)} disabled={confirming === h.id}>
                            {confirming === h.id ? "Confirming…" : "Confirm"}
                          </button>
                        ) : (
                          <span className="muted">Not yet confirmed</span>
                        )}
                      </span>
                    </div>
                    {h.statement && <div style={{ marginTop: 4 }}>&ldquo;{h.statement}&rdquo;</div>}
                    {h.scope && <div className="muted" style={{ marginTop: 2 }}>Scope: {h.scope}</div>}
                    {h.comment && <div className="muted" style={{ marginTop: 2 }}>{h.comment}</div>}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
