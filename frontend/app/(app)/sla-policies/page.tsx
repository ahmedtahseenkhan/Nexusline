"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, apiCall, type SlaPolicy, type TatSummary } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconGauge } from "@/components/icons";

/* The bank's remediation standard, expressed as something the platform can measure.
   Until this clock exists, "critical findings within 15 days" lives in a policy document
   and nobody knows it has been missed until an auditor counts.

   Every scope starts on a shipped default rather than blank, because a settings screen
   full of blanks implies the clock is off when in fact it is running. */

const SEVERITY_TONE: Record<string, "low" | "medium" | "high" | "critical"> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

type Draft = Record<string, SlaPolicy>;

const keyOf = (p: { entity_type: string; severity: string }) => `${p.entity_type}/${p.severity}`;

export default function SlaPoliciesPage() {
  const [rows, setRows] = useState<SlaPolicy[]>([]);
  const [draft, setDraft] = useState<Draft>({});
  const [summary, setSummary] = useState<TatSummary | null>(null);
  const [roles, setRoles] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .slaPolicies()
      .then((data) => {
        setRows(data);
        setDraft(Object.fromEntries(data.map((p) => [keyOf(p), p])));
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the TAT policy"));
    api.slaBreaches().then(setSummary).catch(() => {});
    // Role names power the escalation picker; a free-text fallback keeps the field
    // usable if the caller cannot read the role list.
    apiCall<{ items: { name: string }[] }>("GET", "/roles?limit=100")
      .then((r) => setRoles(r.items.map((x) => x.name)))
      .catch(() => {});
  }, []);

  useEffect(load, [load]);

  const grouped = useMemo(() => {
    const out: Record<string, SlaPolicy[]> = {};
    for (const row of rows) (out[row.entity_type] ||= []).push(row);
    return out;
  }, [rows]);

  function edit(row: SlaPolicy, patch: Partial<SlaPolicy>) {
    setDraft((prev) => ({ ...prev, [keyOf(row)]: { ...prev[keyOf(row)], ...patch } }));
  }

  const dirty = useMemo(
    () =>
      rows.filter((row) => {
        const d = draft[keyOf(row)];
        if (!d) return false;
        return (
          d.target_days !== row.target_days ||
          d.warn_at_percent !== row.warn_at_percent ||
          d.escalate_to_role !== row.escalate_to_role ||
          d.enabled !== row.enabled ||
          // A default that has been looked at and confirmed still needs writing, so the
          // grid stops reporting it as unconfigured.
          (row.is_default && d.target_days !== row.target_days)
        );
      }),
    [rows, draft],
  );

  async function save() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const payload = dirty.map((row) => {
        const d = draft[keyOf(row)];
        return {
          entity_type: d.entity_type,
          severity: d.severity,
          target_days: d.target_days,
          warn_at_percent: d.warn_at_percent,
          escalate_to_role: d.escalate_to_role,
          enabled: d.enabled,
        };
      });
      const saved = await api.updateSlaPolicies(payload);
      setRows(saved);
      setDraft(Object.fromEntries(saved.map((p) => [keyOf(p), p])));
      setNote(
        `Saved ${payload.length} target${payload.length !== 1 ? "s" : ""}. Every open record's ` +
          "window has been recalculated.",
      );
      api.slaBreaches().then(setSummary).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the TAT policy");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Turnaround Time (TAT)</h1>
          <p>
            How long a record of each severity may stay open before it is chased, and who hears
            about it when the window lapses.
          </p>
        </div>
        <button className="btn" onClick={save} disabled={busy || dirty.length === 0}>
          {busy ? "Saving…" : dirty.length ? `Save ${dirty.length} change${dirty.length !== 1 ? "s" : ""}` : "Saved"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
      {note && <div className="muted" style={{ fontSize: 12.5, marginBottom: 16 }}>{note}</div>}

      {summary && (
        <div className="grid stat-grid" style={{ marginBottom: 16 }}>
          <div className="card stat">
            <div className="stat-top"><span className="n">{summary.breached}</span></div>
            <span className="l">Past their TAT</span>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{summary.at_risk}</span></div>
            <span className="l">Approaching TAT</span>
          </div>
          {summary.by_type.slice(0, 2).map((t) => (
            <div className="card stat" key={t.entity_type}>
              <div className="stat-top"><span className="n">{t.breached}</span></div>
              <span className="l">{t.label}s breached</span>
            </div>
          ))}
        </div>
      )}

      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, margin: 0 }}>
          The clock starts when the record is raised and is measured in calendar days. This is
          separate from a record&apos;s own agreed due date: <b>TAT is what the policy allows</b>,
          the due date is what was promised to the action owner — the gap between them is worth
          seeing. An early warning is raised once the chosen percentage of the window has elapsed,
          so the owner hears about it while there is still time to act. Breaches appear in the
          notification centre, on the dashboard, and are emailed to the escalation role.
        </p>
      </div>

      {Object.entries(grouped).map(([entityType, group]) => (
        <div className="card" key={entityType} style={{ marginBottom: 16 }}>
          <div className="card-head">
            <h3>{group[0]?.entity_label ?? entityType}</h3>
            <span className="sub">
              {group.every((g) => g.is_default) ? "using shipped defaults" : "configured"}
            </span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 110 }}>Severity</th>
                  <th style={{ width: 130 }}>Target (days)</th>
                  <th style={{ width: 150 }}>Warn at</th>
                  <th>Escalate to role</th>
                  <th style={{ width: 110 }}>Clock</th>
                </tr>
              </thead>
              <tbody>
                {group.map((row) => {
                  const d = draft[keyOf(row)] ?? row;
                  return (
                    <tr key={keyOf(row)} style={{ opacity: d.enabled ? 1 : 0.55 }}>
                      <td>
                        <Badge tone={SEVERITY_TONE[row.severity] ?? "neutral"}>{row.severity}</Badge>
                        {row.is_default && (
                          <span className="muted" style={{ fontSize: 11, marginLeft: 6 }}>default</span>
                        )}
                      </td>
                      <td>
                        <input
                          className="input" type="number" min={1} max={3650}
                          style={{ width: 82, padding: "4px 8px", fontSize: 13 }}
                          value={d.target_days}
                          onChange={(e) => edit(row, { target_days: Number(e.target.value) })}
                        />
                      </td>
                      <td>
                        <input
                          className="input" type="number" min={1} max={100}
                          style={{ width: 72, padding: "4px 8px", fontSize: 13 }}
                          value={d.warn_at_percent}
                          onChange={(e) => edit(row, { warn_at_percent: Number(e.target.value) })}
                        />
                        <span className="muted" style={{ fontSize: 12, marginLeft: 6 }}>
                          % elapsed
                        </span>
                      </td>
                      <td>
                        <input
                          className="input"
                          list="sla-role-names"
                          style={{ padding: "4px 8px", fontSize: 13, maxWidth: 260 }}
                          placeholder="No escalation"
                          value={d.escalate_to_role}
                          onChange={(e) => edit(row, { escalate_to_role: e.target.value })}
                        />
                      </td>
                      <td>
                        <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12.5 }}>
                          <input
                            type="checkbox"
                            checked={d.enabled}
                            onChange={(e) => edit(row, { enabled: e.target.checked })}
                          />
                          {d.enabled ? "On" : "Off"}
                        </label>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      <datalist id="sla-role-names">
        {roles.map((r) => <option key={r} value={r} />)}
      </datalist>

      {summary && summary.records.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>Currently outside TAT</h3>
            <span className="sub">{summary.records.length} record(s)</span>
          </div>
          <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 120 }}>Type</th>
                  <th>Record</th>
                  <th style={{ width: 100 }}>Severity</th>
                  <th style={{ width: 120 }}>TAT due</th>
                  <th style={{ width: 120 }}>Status</th>
                </tr>
              </thead>
              <tbody>
                {summary.records.map((r) => (
                  <tr key={`${r.entity_type}-${r.entity_id}`}>
                    <td className="muted">{r.entity_label}</td>
                    <td className="cell-title">
                      <Link href={r.link}>{r.label}</Link>
                    </td>
                    <td><Badge tone={SEVERITY_TONE[r.severity] ?? "neutral"}>{r.severity}</Badge></td>
                    <td className="muted">{r.due ?? "—"}</td>
                    <td>
                      {r.days_overdue > 0 ? (
                        <Badge tone="critical">{r.days_overdue}d over</Badge>
                      ) : (
                        <Badge tone="medium">Approaching</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {summary && summary.records.length === 0 && (
        <div className="card card-pad muted" style={{ fontSize: 13 }}>
          <IconGauge width={16} height={16} /> Everything is inside its turnaround time.
        </div>
      )}
    </>
  );
}
