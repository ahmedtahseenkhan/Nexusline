"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";

/* Everything the assurance function has to turn up for, in one window. It reads dates
   that already exist — planned fieldwork, finding due dates, when each auditable unit
   falls due, unstarted plan lines — so nothing here is a second copy of a date recorded
   somewhere else. */

type Event = {
  kind: string;
  date: string;
  end_date: string | null;
  title: string;
  reference: string;
  severity: string;
  link: string;
  overdue: boolean;
};

const KIND_LABEL: Record<string, string> = {
  fieldwork: "Fieldwork",
  finding_due: "Finding due",
  unit_due: "Unit falls due",
  planned_audit: "Planned (not started)",
};

const KIND_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  fieldwork: "info",
  finding_due: "medium",
  unit_due: "neutral",
  planned_audit: "low",
};

function monthKey(iso: string): string {
  return iso.slice(0, 7);
}

function monthLabel(key: string): string {
  const [year, month] = key.split("-").map(Number);
  return new Date(year, month - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function dayLabel(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}

/** Default window: a month and a half back, four and a half months forward. */
function defaultRange(): { from: string; to: string } {
  const now = new Date();
  const from = new Date(now.getTime() - 45 * 864e5);
  const to = new Date(now.getTime() + 135 * 864e5);
  return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

export default function AuditCalendarTab() {
  const [range, setRange] = useState(defaultRange);
  const [events, setEvents] = useState<Event[]>([]);
  const [kinds, setKinds] = useState<Set<string>>(new Set(Object.keys(KIND_LABEL)));
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiCall<{ events: Event[] }>(
      "GET",
      `/audit-calendar?from=${range.from}&to=${range.to}`,
    )
      .then((data) => setEvents(data.events))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the calendar"));
  }, [range]);

  useEffect(load, [load]);

  const shown = useMemo(() => events.filter((e) => kinds.has(e.kind)), [events, kinds]);

  const months = useMemo(() => {
    const out = new Map<string, Event[]>();
    for (const event of shown) {
      const key = monthKey(event.date);
      if (!out.has(key)) out.set(key, []);
      out.get(key)!.push(event);
    }
    return [...out.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [shown]);

  function toggleKind(kind: string) {
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }

  const overdue = shown.filter((e) => e.overdue).length;

  return (
    <>
      <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ width: 170 }}>
          <label className="label">From</label>
          <input className="input" type="date" value={range.from} onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))} />
        </div>
        <div style={{ width: 170 }}>
          <label className="label">To</label>
          <input className="input" type="date" value={range.to} onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))} />
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", paddingBottom: 6 }}>
          {Object.entries(KIND_LABEL).map(([kind, label]) => (
            <button
              key={kind}
              type="button"
              className={`btn sm${kinds.has(kind) ? "" : " secondary"}`}
              onClick={() => toggleKind(kind)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <Badge tone="info">{shown.length} event(s)</Badge>
        {overdue > 0 && <Badge tone="critical">{overdue} already past</Badge>}
      </div>

      {months.length === 0 && (
        <div className="card card-pad muted" style={{ fontSize: 13 }}>
          Nothing scheduled in this window. Plan lines, engagement dates, finding due dates and
          audit-universe due dates all appear here as soon as they exist.
        </div>
      )}

      {months.map(([key, monthEvents]) => (
        <div className="card" key={key} style={{ marginBottom: 16 }}>
          <div className="card-head">
            <h3>{monthLabel(key)}</h3>
            <span className="sub">{monthEvents.length} event(s)</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 90 }}>Date</th>
                  <th style={{ width: 170 }}>Kind</th>
                  <th>What</th>
                  <th style={{ width: 100 }}>Ref</th>
                  <th style={{ width: 100 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {monthEvents.map((event, index) => (
                  <tr key={`${event.kind}-${event.reference}-${event.date}-${index}`}>
                    <td className="ref">{dayLabel(event.date)}</td>
                    <td>
                      <Badge tone={KIND_TONE[event.kind] ?? "neutral"}>
                        {KIND_LABEL[event.kind] ?? event.kind}
                      </Badge>
                    </td>
                    <td className="cell-title">
                      {event.title}
                      {event.end_date && event.end_date !== event.date && (
                        <span className="muted" style={{ fontSize: 11.5 }}> → {dayLabel(event.end_date)}</span>
                      )}
                    </td>
                    <td className="muted">{event.reference || "—"}</td>
                    <td>
                      {event.overdue ? (
                        <Badge tone="critical">Past</Badge>
                      ) : (
                        <span className="muted" style={{ fontSize: 12 }}>Upcoming</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}
