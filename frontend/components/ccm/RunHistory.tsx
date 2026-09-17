"use client";

/* Run history of one monitoring test (Integrations & CCM → a test): Run now, Run with
   file, and every run with its population, exceptions, duration, evidence and issue. A
   run's exception sample opens inline and downloads as CSV. */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { apiCall, downloadBlob, uploadMultipart } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { Badge } from "@/components/badges";
import { durationText, RUN_SOURCE_LABEL, type RunDetail, type RunNowResult, type RunRow } from "@/lib/ccm";

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

const RESULT_TONE: Record<string, "low" | "high" | "critical" | "neutral"> = { passed: "low", failed: "critical", error: "high", not_run: "neutral" };
const RESULT_LABEL: Record<string, string> = { passed: "Passed", failed: "Failed", error: "Error", not_run: "Not run" };

const errText = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

export default function RunHistory({
  testId,
  executable,
  acceptsFile,
  controlId,
  canWrite,
  onRan,
  openRunId,
}: {
  testId: string;
  /** Has a check to run (not recorded by hand / pushed). */
  executable: boolean;
  /** The check reads a file (scanner export, SIEM report, HR list, CSV). */
  acceptsFile: boolean;
  controlId: string | null;
  canWrite: boolean;
  onRan?: () => void;
  /** Open this run's exceptions on load (from an evidence link). */
  openRunId?: string | null;
}) {
  const { formatDate, formatDateTime } = useFormat();
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<RunNowResult | null>(null);
  const [open, setOpen] = useState<RunDetail | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    apiCall<Page<RunRow>>("GET", `/automated-control-tests/${testId}/runs?limit=${limit}`)
      .then((p) => { setRuns(p.items); setTotal(p.total); })
      .catch((e) => setError(errText(e, "Could not load the runs.")));
  }, [testId, limit]);
  useEffect(load, [load]);

  const showRun = useCallback((id: string) => {
    apiCall<RunDetail>("GET", `/control-test-runs/${id}`).then(setOpen).catch((e) => setError(errText(e, "Could not load the run.")));
  }, []);
  useEffect(() => { if (openRunId) showRun(openRunId); }, [openRunId, showRun]);

  async function runNow(file?: File) {
    setBusy(true);
    setError(null);
    try {
      const res = file
        ? await uploadMultipart<RunNowResult>(`/automated-control-tests/${testId}/run-upload`, file)
        : await apiCall<RunNowResult>("POST", `/automated-control-tests/${testId}/run`);
      setLast(res);
      if (res.run) setOpen(res.run);
      toast(res.result === "passed" ? "Run passed" : res.result === "failed" ? "Run failed" : "Run could not complete");
      load();
      onRan?.();
    } catch (e) {
      setError(errText(e, "The run did not start."));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div>
      {canWrite && executable && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
          <button type="button" className="btn sm" disabled={busy} onClick={() => runNow()}>{busy ? "Running…" : "Run now"}</button>
          {acceptsFile && (
            <>
              <input ref={fileRef} type="file" hidden accept=".nessus,.xml,.csv,.json,.txt"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void runNow(f); }} />
              <button type="button" className="btn secondary sm" disabled={busy} onClick={() => fileRef.current?.click()}>Run with file…</button>
            </>
          )}
          <span className="muted" style={{ fontSize: 12.5 }}>
            {acceptsFile ? "Run now uses the connector or its import folder; Run with file uses the file you choose." : "Runs against the connector with its saved settings."}
          </span>
        </div>
      )}
      {last && (
        <div className={last.result === "error" ? "error" : "card-pad"} style={{ marginBottom: 12, border: last.result === "error" ? undefined : "1px solid var(--border)", borderRadius: 8 }}>
          <strong>{RESULT_LABEL[last.result] ?? last.result}:</strong> {last.message}
          {last.issue_reference && <> · Issue {last.issue_reference} opened or updated</>}
          {last.kri_note && <> · {last.kri_note}</>}
        </div>
      )}
      {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Run</th><th>Result</th><th>Population</th><th>Exceptions</th><th>Took</th><th>Evidence / issue</th><th></th></tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>
                  {r.started_at ? formatDateTime(r.started_at) : formatDate(r.run_date)}
                  <div className="muted" style={{ fontSize: 12 }}>{RUN_SOURCE_LABEL[r.source ?? "manual"] ?? r.source}</div>
                </td>
                <td>
                  <Badge tone={RESULT_TONE[r.result] ?? "neutral"}>{RESULT_LABEL[r.result] ?? r.result}</Badge>
                  {r.error_message ? <div className="muted" style={{ fontSize: 12, maxWidth: 260 }}>{r.error_message}</div> : null}
                </td>
                <td className="muted">{r.population_size ?? "—"}</td>
                <td className="muted">{r.exceptions_count ?? "—"}</td>
                <td className="muted">{durationText(r.duration_ms) || "—"}</td>
                <td className="muted" style={{ fontSize: 12.5 }}>
                  {r.evidence_id ? <Link href={`/evidence?id=${r.evidence_id}`}>Evidence</Link> : r.evidence_ref || "—"}
                  {r.evidence_id && controlId ? <> · <Link href={`/controls?id=${controlId}#monitoring`}>Control</Link></> : null}
                  {r.issue_id ? <> · <Link href={`/issues?id=${r.issue_id}`}>Issue</Link></> : null}
                </td>
                <td>
                  {(r.exceptions_count ?? 0) > 0 || r.error_message ? (
                    <button type="button" className="btn secondary sm" onClick={() => (open?.id === r.id ? setOpen(null) : showRun(r.id))}>
                      {open?.id === r.id ? "Hide" : "Exceptions"}
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
            {runs.length === 0 && (
              <tr><td colSpan={7}><span className="muted">No runs yet.</span></td></tr>
            )}
          </tbody>
        </table>
      </div>
      {total > runs.length && (
        <button type="button" className="btn secondary sm" style={{ marginTop: 8 }} onClick={() => setLimit((n) => n + 50)}>
          Show older runs ({total - runs.length} more)
        </button>
      )}

      {open && <ExceptionSample run={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

function ExceptionSample({ run, onClose }: { run: RunDetail; onClose: () => void }) {
  const rows = run.exceptions_sample ?? [];
  const columns = Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  const count = run.exceptions_count ?? rows.length;
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="card-head row-between">
        <div>
          <h3>Exceptions {run.test_reference ? `· ${run.test_reference}` : ""}</h3>
          <span className="sub">
            {rows.length < count ? `First ${rows.length} of ${count} kept on the run.` : `${count} exception${count === 1 ? "" : "s"}.`}
            {run.issue_reference ? ` Tracked on ${run.issue_reference}.` : ""}
          </span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {rows.length > 0 && (
            <button type="button" className="btn secondary sm"
              onClick={() => void downloadBlob(`/control-test-runs/${run.id}/exceptions.csv`, `${run.test_reference || "run"}-exceptions.csv`)}>
              Download CSV
            </button>
          )}
          <button type="button" className="btn secondary sm" onClick={onClose}>Close</button>
        </div>
      </div>
      <div className="card-pad">
        {run.error_message && <div className="error" style={{ marginBottom: 10 }}>{run.error_message}</div>}
        {rows.length > 0 ? (
          <div className="table-wrap">
            <table className="compact">
              <thead><tr>{columns.map((c) => <th key={c}>{c.replace(/_/g, " ")}</th>)}</tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>{columns.map((c) => <td key={c}>{r[c] === null || r[c] === undefined ? "" : String(r[c])}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          !run.error_message && <p className="muted">No exceptions on this run.</p>
        )}
        {run.details && Object.keys(run.details).length > 0 && (
          <details style={{ marginTop: 10 }}>
            <summary className="muted">Run details</summary>
            <pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(run.details, null, 2)}</pre>
          </details>
        )}
      </div>
    </div>
  );
}
