"use client";

import { useMemo, useState } from "react";
import { api, type RiskAcceptance } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { Badge } from "@/components/badges";
import { Field, TextInput, TextArea } from "@/components/fields";

/* Accepting a risk is the one place in the register where doing nothing is a *decision*.
   Three things make it that rather than an omission, and all three are visible here:

   1. **A written rationale.** The sentence an auditor reads when they ask why this
      exposure was tolerated.
   2. **Four eyes.** Whoever requested the acceptance can never approve it; the server
      refuses, and says so. The panel does not try to guess who is allowed — it offers
      the buttons and lets the refusal be the answer, because the rule depends on
      dual-control thresholds the client cannot see.
   3. **An expiry.** An open-ended acceptance is how a risk disappears for three years.
      Once the date passes, the scheduled sweep marks the acceptance expired and puts the
      risk back in the register awaiting a fresh decision — which is why the expiry field
      warns rather than being quietly optional. */

const TONE: Record<RiskAcceptance["status"], "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  pending: "medium",
  rejected: "neutral",
  expired: "high",
};

const WORDS: Record<RiskAcceptance["status"], string> = {
  approved: "In force",
  pending: "Awaiting approval",
  rejected: "Rejected",
  expired: "Lapsed",
};

function daysUntil(date: string): number {
  const ms = new Date(date + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime();
  return Math.round(ms / 86_400_000);
}

type Props = {
  riskId: string;
  riskReference: string;
  acceptances: RiskAcceptance[];
  /** Reload the record after anything is recorded. */
  onChange: () => void;
};

export default function RiskAcceptancePanel({ riskId, riskReference, acceptances, onChange }: Props) {
  const [requesting, setRequesting] = useState(false);
  const [rationale, setRationale] = useState("");
  const [expires, setExpires] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const history = useMemo(
    () => [...acceptances].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [acceptances],
  );
  const pending = history.find((a) => a.status === "pending");
  const inForce = history.find((a) => a.status === "approved");

  async function submitRequest() {
    if (!rationale.trim()) {
      setError("Write down why this risk is being accepted — that sentence is the record.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.requestAcceptance(riskId, { rationale: rationale.trim(), expires_at: expires || null });
      setRequesting(false);
      setRationale("");
      setExpires("");
      toast(`Acceptance requested for ${riskReference}. A second person has to approve it.`);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not request acceptance");
    } finally {
      setBusy(false);
    }
  }

  async function decide(acceptance: RiskAcceptance, approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.decideAcceptance(riskId, acceptance.id, { approve, note: note.trim() });
      setNote("");
      toast(approve ? `${riskReference} accepted.` : `Acceptance rejected for ${riskReference}.`);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the decision");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>Risk acceptance</strong>
        {inForce && <Badge tone="low">In force</Badge>}
        {pending && <Badge tone="medium">Awaiting a second approver</Badge>}
        {!inForce && !pending && !history.length && (
          <span className="muted" style={{ fontSize: 12.5 }}>Never formally accepted.</span>
        )}
        {!requesting && !pending && (
          <button
            className="btn secondary sm"
            style={{ marginLeft: "auto" }}
            onClick={() => { setRequesting(true); setError(null); }}
          >
            {inForce ? "Request renewal" : "Request acceptance"}
          </button>
        )}
      </div>

      {error && <div className="error" style={{ fontSize: 12.5, marginTop: 10 }}>{error}</div>}

      {inForce?.expires_at && (() => {
        const left = daysUntil(inForce.expires_at);
        if (left < 0) return null;
        return (
          <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
            {left <= 30 ? (
              <b>
                Expires in {left} day{left === 1 ? "" : "s"} ({inForce.expires_at}) — renew it, or the risk
                returns to the register on its own.
              </b>
            ) : (
              <>In force until {inForce.expires_at}.</>
            )}
          </div>
        );
      })()}

      {/* ------------------------------------------------------- request form */}
      {requesting && (
        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          <Field
            label="Why is this risk being accepted?"
            required
            help="Stated in full: the compensating measures, who agreed, and what would change the decision. This is what an auditor reads."
          >
            <TextArea
              value={rationale}
              onChange={setRationale}
              placeholder="Exposure is tolerated until the MFA rollout completes; privileged sessions are monitored daily in the interim and reviewed by the CISO monthly."
            />
          </Field>
          <Field
            label="Acceptance expires on"
            help="Leave blank only for a deliberately open-ended acceptance. With a date, the platform lapses the acceptance itself once it passes and puts the risk back in the register — nobody has to remember."
          >
            <TextInput value={expires} onChange={setExpires} type="date" />
          </Field>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn" disabled={busy} onClick={submitRequest}>
              {busy ? "Submitting…" : "Submit for approval"}
            </button>
            <button className="btn secondary" disabled={busy} onClick={() => { setRequesting(false); setError(null); }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* -------------------------------------------------- pending decision */}
      {pending && !requesting && (
        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          <div style={{ fontSize: 13.5, lineHeight: 1.5 }}>{pending.rationale}</div>
          <Field label="Decision note" help="Optional, and recorded on the trail either way.">
            <TextInput value={note} onChange={setNote} placeholder="Approved at the September risk committee." />
          </Field>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button className="btn" disabled={busy} onClick={() => decide(pending, true)}>
              {busy ? "Recording…" : "Approve acceptance"}
            </button>
            <button className="btn secondary" disabled={busy} onClick={() => decide(pending, false)}>
              Reject
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              Whoever requested this cannot approve it.
            </span>
          </div>
        </div>
      )}

      {/* -------------------------------------------------------- the history */}
      {history.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table>
            <thead>
              <tr>
                <th style={{ width: 130 }}>Decision</th>
                <th style={{ width: 100 }}>Expires</th>
                <th style={{ width: 100 }}>Decided</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {history.map((a) => (
                <tr key={a.id}>
                  <td><Badge tone={TONE[a.status]}>{WORDS[a.status]}</Badge></td>
                  <td className="muted">{a.expires_at || "Open-ended"}</td>
                  <td className="muted">{a.decided_at || "—"}</td>
                  <td style={{ fontSize: 13 }}>{a.rationale || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
