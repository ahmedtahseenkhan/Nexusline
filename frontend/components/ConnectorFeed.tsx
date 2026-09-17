"use client";

/* Monitoring feed for one connector (Integrations → connector drawer).

   A monitoring tool posts control results with a token instead of a login. Each result
   becomes evidence on the control, a run of the connector's test for that control when
   there is one, and an alert, an issue and a reliance hold when it failed (phase 4D). It
   never changes the control's effectiveness: a person records a test and another person
   reviews it. The token is
   shown once; only a fingerprint of it is kept. */

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { Badge } from "@/components/badges";

const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type IngestItem = {
  at: string;
  result: string;
  control_id: string | null;
  control_reference: string;
  summary: string;
  observed_at: string;
  evidence_id: string | null;
  run_id: string | null;
  test_reference: string | null;
  alert_raised: boolean;
};

type Feed = {
  connector_id: string;
  has_token: boolean;
  endpoint: string;
  last_ingest_at: string | null;
  ingests_last_30_days: number;
  recent: IngestItem[];
};

type Issued = { connector_id: string; token: string; endpoint: string; header: string; note: string };

const RESULT: Record<string, { tone: "low" | "medium" | "critical" | "neutral"; label: string }> = {
  passed: { tone: "low", label: "Passed" },
  passed_with_exceptions: { tone: "medium", label: "Passed with exceptions" },
  failed: { tone: "critical", label: "Failed" },
};

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

export default function ConnectorFeed({ connectorId, onChanged }: { connectorId: string; onChanged?: () => void }) {
  const { formatDateTime } = useFormat();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiCall<Feed>("GET", `/connectors/${connectorId}/feed`)
      .then((f) => { setFeed(f); setError(null); })
      .catch((e) => setError(errMsg(e, "Could not load the feed")));
  }, [connectorId]);

  useEffect(() => {
    setIssued(null);
    setFeed(null);
    load();
  }, [load]);

  const live = !!feed?.has_token;

  async function generate() {
    if (live) {
      const ok = await confirmDialog({
        title: "Replace the feed token?",
        message: "The current token stops working at once; the monitoring tool must be given the new one.",
        confirmLabel: "Replace token",
        danger: true,
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      setIssued(await apiCall<Issued>("POST", `/connectors/${connectorId}/ingest-token`));
      load();
      onChanged?.();
    } catch (e) {
      toast(errMsg(e, "Could not generate a token"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    const ok = await confirmDialog({
      title: "Revoke the feed token?",
      message: "The monitoring tool's next result is refused (401).",
      confirmLabel: "Revoke",
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await apiCall<void>("DELETE", `/connectors/${connectorId}/ingest-token`);
      setIssued(null);
      load();
      onChanged?.();
      toast("Feed token revoked");
    } catch (e) {
      toast(errMsg(e, "Could not revoke the token"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} copied`);
    } catch {
      toast("Copy failed — select the text and copy it", "error");
    }
  }

  const url = `${API_ORIGIN}${issued?.endpoint || feed?.endpoint || "/api/v1/connectors/ingest"}`;
  const curl = issued
    ? `curl -X POST '${url}' \\\n  -H 'Authorization: Bearer ${issued.token}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"control_reference": "A.8.5", "result": "passed", "observed_at": "YYYY-MM-DDTHH:MM:SS+05:00", "summary": "All privileged accounts have MFA", "evidence": {"title": "MFA coverage report", "url": "https://…"}}'`
    : "";

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-pad">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong>Monitoring feed</strong>
          <span>{live ? <Badge tone="low">Token active</Badge> : <Badge tone="neutral">No token</Badge>}</span>
        </div>
        <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
          A monitoring tool can post control results with a token instead of a user login. Each result is kept as evidence on
          the control and as a run of this connector&apos;s test for that control. A failed result raises an alert, opens an
          issue on the test (or updates the open one) and stops risks relying on the control until a result passes. The
          control&apos;s effectiveness does not change until a person records a test and another person reviews it. Results beyond the rate limit (60 a minute per token by
          default) are refused. Recorded in the activity trail as “Connector {"<name>"}”.
        </p>
        {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="btn secondary sm" onClick={generate} disabled={busy || feed === null}>
            {live ? "Replace token" : "Generate token"}
          </button>
          {live && <button type="button" className="btn secondary sm" onClick={revoke} disabled={busy}>Revoke</button>}
        </div>

        {issued && (
          <div style={{ marginTop: 12, padding: 12, border: "1px solid var(--amber)", background: "var(--amber-bg)", borderRadius: 8, display: "grid", gap: 8 }}>
            <strong style={{ fontSize: 13 }}>Copy this token now — it is not shown again.</strong>
            <div style={{ display: "flex", gap: 8 }}>
              <input className="input" readOnly value={issued.token} aria-label="Feed token" style={{ fontFamily: "var(--mono)", fontSize: 12.5 }} onFocus={(e) => e.currentTarget.select()} />
              <button type="button" className="btn sm" onClick={() => copy(issued.token, "Token")}>Copy</button>
            </div>
            <div className="muted" style={{ fontSize: 12.5 }}>Only a fingerprint of it is stored. If it is lost, generate a new one.</div>
            <pre style={{ margin: 0, padding: 10, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, overflowX: "auto", whiteSpace: "pre" }}>{curl}</pre>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="btn secondary sm" onClick={() => copy(curl, "Example request")}>Copy example</button>
              <button type="button" className="btn secondary sm" onClick={() => setIssued(null)}>I have copied it</button>
            </div>
          </div>
        )}

        {feed && (
          <>
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", margin: "14px 0 10px", fontSize: 13 }}>
              <div>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Last result received</div>
                <div>{feed.last_ingest_at ? formatDateTime(feed.last_ingest_at) : "Nothing received yet"}</div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Results in the last 30 days</div>
                <div>{feed.ingests_last_30_days.toLocaleString()}</div>
              </div>
            </div>
            {feed.recent.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Received</th>
                      <th>Control</th>
                      <th>Result</th>
                      <th>Summary</th>
                      <th>Test run</th>
                    </tr>
                  </thead>
                  <tbody>
                    {feed.recent.map((r, i) => {
                      const res = RESULT[r.result] || { tone: "neutral" as const, label: r.result || "—" };
                      return (
                        <tr key={`${r.at}-${i}`}>
                          <td className="muted" style={{ whiteSpace: "nowrap" }}>{formatDateTime(r.at)}</td>
                          <td>
                            {r.control_id ? <a href={`/controls?id=${r.control_id}`} className="ref">{r.control_reference || "Control"}</a> : <span className="ref">{r.control_reference || "—"}</span>}
                          </td>
                          <td>
                            <Badge tone={res.tone}>{res.label}</Badge>
                            {r.alert_raised && <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>Alert raised</div>}
                          </td>
                          <td className="muted" style={{ fontSize: 12.5 }}>{r.summary || "—"}</td>
                          <td className="muted">{r.test_reference || "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
