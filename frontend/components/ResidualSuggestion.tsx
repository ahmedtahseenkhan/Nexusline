"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type SuggestedResidual } from "@/lib/api";
import { Badge } from "@/components/badges";

/* Shows what the linked controls' effectiveness implies the residual should be, and why,
   line by line. The number is a *proposal*: ISO 27005 and ISO 31000 both treat residual
   risk as an assessed judgement, so nothing is recorded until the risk owner accepts it,
   and recording a different number requires a written reason. That reason is what an
   auditor reads when they ask why the residual is lower than the evidence supports. */

type Props = {
  riskId: string;
  /** Called after the residual is written, so the parent can reload the record. */
  onAccepted?: () => void;
};

export default function ResidualSuggestion({ riskId, onAccepted }: Props) {
  const [data, setData] = useState<SuggestedResidual | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [overriding, setOverriding] = useState(false);
  const [likelihood, setLikelihood] = useState("");
  const [impact, setImpact] = useState("");
  const [reason, setReason] = useState("");

  const load = useCallback(() => {
    api
      .suggestedResidual(riskId)
      .then((d) => {
        setData(d);
        setLikelihood(String(d.likelihood));
        setImpact(String(d.impact));
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the suggestion"));
  }, [riskId]);

  useEffect(() => {
    setData(null);
    setError(null);
    setOverriding(false);
    setReason("");
    load();
  }, [riskId, load]);

  async function accept(override: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.acceptResidual(riskId, override
        ? { likelihood: Number(likelihood), impact: Number(impact), override_reason: reason }
        : {});
      setOverriding(false);
      setReason("");
      load();
      onAccepted?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not record the residual");
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) {
    return <div className="error" style={{ fontSize: 12.5 }}>{error}</div>;
  }
  if (!data) {
    return <div className="muted" style={{ fontSize: 12.5 }}>Working out the suggested residual…</div>;
  }

  const overrideIsDifferent =
    Number(likelihood) !== data.likelihood || Number(impact) !== data.impact;

  return (
    <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>Suggested residual</strong>
        <Badge tone={data.matches_current ? "low" : "medium"}>
          {data.likelihood} × {data.impact} = {data.score}
        </Badge>
        <span className="muted" style={{ fontSize: 12.5 }}>
          from inherent {data.inherent_score}
          {data.current_residual_score !== null ? ` · recorded ${data.current_residual_score}` : " · none recorded yet"}
        </span>
        {data.matches_current && <Badge tone="neutral" plain>Matches the record</Badge>}
      </div>

      <ul style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: 12.5, lineHeight: 1.7, color: "var(--text)" }}>
        {data.rationale.map((line, i) => (
          <li key={i} className={line.includes("no credit") ? "muted" : undefined}>{line}</li>
        ))}
      </ul>

      <p className="muted" style={{ fontSize: 12, lineHeight: 1.6, margin: "10px 0 0" }}>
        This is a proposal, not an assessment. The residual on the record only changes
        when you accept it below — or record a different judgement with a reason.
      </p>

      {error && <div className="error" style={{ marginTop: 10, fontSize: 12.5 }}>{error}</div>}

      {!overriding ? (
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <button
            className="btn sm"
            type="button"
            onClick={() => accept(false)}
            disabled={busy || data.matches_current}
            title={data.matches_current ? "The recorded residual already matches" : undefined}
          >
            {busy ? "Saving…" : "Accept suggestion"}
          </button>
          <button className="btn secondary sm" type="button" onClick={() => setOverriding(true)} disabled={busy}>
            Record a different residual
          </button>
        </div>
      ) : (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <label className="muted" style={{ fontSize: 12.5 }}>Likelihood</label>
            <input
              className="input" style={{ width: 64, padding: "5px 8px", fontSize: 13 }}
              value={likelihood} onChange={(e) => setLikelihood(e.target.value)} inputMode="numeric"
            />
            <label className="muted" style={{ fontSize: 12.5 }}>Impact</label>
            <input
              className="input" style={{ width: 64, padding: "5px 8px", fontSize: 13 }}
              value={impact} onChange={(e) => setImpact(e.target.value)} inputMode="numeric"
            />
          </div>
          <textarea
            className="input"
            style={{ padding: "6px 9px", fontSize: 13, minHeight: 60 }}
            placeholder="Why does your assessment differ from the suggestion? (required)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="btn sm"
              type="button"
              onClick={() => accept(true)}
              disabled={busy || (overrideIsDifferent && !reason.trim())}
              title={overrideIsDifferent && !reason.trim() ? "A written reason is required" : undefined}
            >
              {busy ? "Saving…" : "Record residual"}
            </button>
            <button className="btn secondary sm" type="button" onClick={() => setOverriding(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
