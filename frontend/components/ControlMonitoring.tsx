"use client";

/* The control record's Monitoring section (phase 4D).

   Continuous-monitoring tests of this control, from GET /ccm/controls/{id}/monitoring: one
   status line ("Monitored: passing (last 30 runs 97%)", "Monitoring failing since …"), then
   one row per test linking to its run history on Integrations & CCM. Wording lives in
   lib/record/control.ts (monitoringStatusText, monitoringTestLine). Monitoring never changes
   the rating; a failing run opens an issue and withholds reliance until it passes. */

import Link from "next/link";
import { Badge } from "@/components/badges";
import { RecordSection } from "@/components/record";
import {
  MONITORING_EMPTY_TEXT,
  MONITORING_RATING_NOTE,
  monitoringStatusText,
  monitoringTestLine,
  type ControlMonitoring,
} from "@/lib/record/control";
import type { Fmt } from "@/lib/record/types";

const STATE_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral"> = {
  passing: "low",
  failing: "critical",
  error: "high",
  overdue: "medium",
  not_run: "neutral",
  paused: "neutral",
};
const RESULT_TONE: Record<string, "low" | "high" | "critical" | "neutral"> = {
  passed: "low",
  failed: "critical",
  error: "high",
  not_run: "neutral",
};
const RESULT_LABEL: Record<string, string> = { passed: "Passed", failed: "Failed", error: "Error", not_run: "Not run" };

export default function ControlMonitoringSection({
  monitoring,
  failed,
  fmt,
}: {
  monitoring: ControlMonitoring | null;
  /** The monitoring read failed (CCM module off, or no ccm:read): the section is left out
   *  rather than claiming "Not monitored". */
  failed?: boolean;
  fmt: Pick<Fmt, "date">;
}) {
  if (failed) return null;
  const tests = monitoring?.tests ?? [];
  const empty = tests.length === 0 ? MONITORING_EMPTY_TEXT : undefined;
  return (
    <RecordSection id="monitoring" title="Monitoring" count={tests.length || undefined} sub={empty ? undefined : MONITORING_RATING_NOTE} empty={empty}>
      {monitoring && tests.length > 0 && (
        <>
          <p style={{ margin: "0 0 10px", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Badge asIs tone={STATE_TONE[monitoring.state] ?? "neutral"}>{monitoringStatusText(monitoring, fmt)}</Badge>
          </p>
          <div className="rec-table-wrap">
            <table className="compact">
              <thead>
                <tr><th>Test</th><th>Last result</th><th>Status</th></tr>
              </thead>
              <tbody>
                {tests.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <Link href={`/integrations?test=${t.id}`}>{t.reference}</Link> {t.name}
                    </td>
                    <td><Badge tone={RESULT_TONE[t.last_result] ?? "neutral"}>{RESULT_LABEL[t.last_result] ?? t.last_result}</Badge></td>
                    <td className="muted">{monitoringTestLine(t, fmt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </RecordSection>
  );
}
