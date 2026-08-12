"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type TatSummary } from "@/lib/api";
import { Badge } from "@/components/badges";

/* The sign-in reminder for breached turnaround times.

   A breach that only appears in a list somebody has to open is a breach nobody sees.
   This puts it in front of the user once per day — and only for genuine breaches, never
   for records merely approaching their window, because a dialog that appears every day
   for things that are still on time is one people learn to dismiss without reading.

   Dismissal is remembered for the rest of the day in localStorage, keyed by the set of
   breached records: if something *new* breaches later, the reminder returns rather than
   staying silent because it was dismissed this morning. */

const KEY = "tat-reminder-dismissed";

function signature(summary: TatSummary): string {
  return summary.records
    .filter((r) => r.days_overdue > 0)
    .map((r) => `${r.entity_type}:${r.entity_id}`)
    .sort()
    .join("|");
}

function todayStamp(): string {
  return new Date().toISOString().slice(0, 10);
}

export default function TatReminder() {
  const [summary, setSummary] = useState<TatSummary | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .slaBreaches()
      .then((data) => {
        if (!alive || data.breached === 0) return;
        setSummary(data);
        try {
          const raw = localStorage.getItem(KEY);
          const seen = raw ? (JSON.parse(raw) as { day: string; sig: string }) : null;
          if (seen && seen.day === todayStamp() && seen.sig === signature(data)) return;
        } catch {
          /* a corrupt entry just means we show the reminder */
        }
        setOpen(true);
      })
      .catch(() => {/* never block the app on this */});
    return () => {
      alive = false;
    };
  }, []);

  function dismiss() {
    if (summary) {
      try {
        localStorage.setItem(KEY, JSON.stringify({ day: todayStamp(), sig: signature(summary) }));
      } catch {
        /* private mode — the reminder simply returns on the next load */
      }
    }
    setOpen(false);
  }

  if (!open || !summary) return null;

  const breached = summary.records.filter((r) => r.days_overdue > 0);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && dismiss()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Turnaround time breached">
        <div className="modal-head">
          <h2>Turnaround time breached</h2>
          <button className="x" onClick={dismiss} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: 13.5, lineHeight: 1.6, marginTop: 0 }}>
            <b>{summary.breached}</b> record{summary.breached !== 1 ? "s have" : " has"} passed the
            turnaround time your policy allows
            {summary.at_risk > 0 && `, and ${summary.at_risk} more ${summary.at_risk !== 1 ? "are" : "is"} approaching`}.
          </p>

          <div className="table-wrap" style={{ maxHeight: 300, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 110 }}>Type</th>
                  <th>Record</th>
                  <th style={{ width: 100 }}>Overdue</th>
                </tr>
              </thead>
              <tbody>
                {breached.slice(0, 25).map((r) => (
                  <tr key={`${r.entity_type}-${r.entity_id}`}>
                    <td className="muted">{r.entity_label}</td>
                    <td className="cell-title">
                      <Link href={r.link} onClick={dismiss}>{r.label}</Link>
                    </td>
                    <td><Badge tone="critical">{r.days_overdue}d</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {breached.length > 25 && (
            <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
              …and {breached.length - 25} more.
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn secondary" type="button" onClick={dismiss}>
            Dismiss for today
          </button>
          <Link className="btn" href="/sla-policies" onClick={dismiss}>
            Review all
          </Link>
        </div>
      </div>
    </div>
  );
}
