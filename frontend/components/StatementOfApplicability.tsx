"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/feedback";
import {
  downloadSoa,
  getSoa,
  setApplicability,
  type SoaRow,
  type SoaView,
  type StatementOfApplicability as Soa,
} from "@/lib/compliance";
import { Badge, ComplianceBadge, EffectivenessBadge } from "@/components/badges";

type Props = {
  frameworkId: string;
  frameworkName: string;
  /** Called after an applicability change, so the page can refresh its gap counts. */
  onChanged?: () => void;
};

/** What is being edited: a clause's justification, and whether it is being included or
 *  excluded. Excluding always goes through here — a clause cannot leave the SoA
 *  without a reason (ISO/IEC 27001 6.1.3 d). */
type Editing = { id: string; applicable: boolean; text: string };

const VIEWS: [SoaView, string][] = [
  ["all", "All"],
  ["applicable", "Applicable"],
  ["excluded", "Excluded"],
  ["no_control", "No control"],
];

const words = (v: string | null | undefined) => (v ? v.replace(/_/g, " ") : "—");

export default function StatementOfApplicability({ frameworkId, frameworkName, onChanged }: Props) {
  const [soa, setSoa] = useState<Soa | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<SoaView>("all");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Editing | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"xlsx" | "pdf" | null>(null);

  const load = useCallback(() => {
    setError(null);
    getSoa(frameworkId)
      .then(setSoa)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load the Statement of Applicability"));
  }, [frameworkId]);

  useEffect(() => {
    setSoa(null);
    setEditing(null);
    load();
  }, [load]);

  const rows = useMemo(() => {
    if (!soa) return [];
    const q = query.trim().toLowerCase();
    return soa.rows.filter((r) => {
      if (view === "applicable" && !r.applicable) return false;
      if (view === "excluded" && r.applicable) return false;
      if (view === "no_control" && (!r.applicable || r.controls.length > 0)) return false;
      if (!q) return true;
      return [r.reference, r.title, r.domain, r.justification].some((v) => (v || "").toLowerCase().includes(q));
    });
  }, [soa, view, query]);

  function replaceRow(row: SoaRow) {
    setSoa((cur) => {
      if (!cur) return cur;
      const nextRows = cur.rows.map((r) => (r.requirement_id === row.requirement_id ? row : r));
      const summary = {
        total: nextRows.length,
        applicable: nextRows.filter((r) => r.applicable).length,
        excluded: nextRows.filter((r) => !r.applicable).length,
        no_control: nextRows.filter((r) => r.applicable && r.controls.length === 0).length,
        missing_justification: nextRows.filter((r) => !r.applicable && !r.justification.trim()).length,
      };
      return { ...cur, rows: nextRows, summary };
    });
  }

  async function save(id: string, applicable: boolean, justification?: string) {
    setBusyId(id);
    try {
      const row = await setApplicability(id, applicable, justification);
      replaceRow(row);
      setEditing(null);
      onChanged?.();
      return true;
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "error");
      return false;
    } finally {
      setBusyId(null);
    }
  }

  /** Including is immediate; excluding opens the justification editor first. */
  function toggle(row: SoaRow) {
    if (row.applicable) {
      setEditing({ id: row.requirement_id, applicable: false, text: "" });
    } else {
      save(row.requirement_id, true).then((ok) => ok && toast(`${row.reference || row.title} is applicable again.`));
    }
  }

  async function exportAs(format: "xlsx" | "pdf") {
    setExporting(format);
    try {
      await downloadSoa(frameworkId, frameworkName, format, view);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Export failed", "error");
    } finally {
      setExporting(null);
    }
  }

  if (error) return <div className="error">{error}</div>;
  if (!soa) return <div className="card"><div className="empty" style={{ padding: 28 }}><p>Loading…</p></div></div>;

  const s = soa.summary;
  const editingValid = !!editing && (editing.applicable || editing.text.trim().length > 0);

  return (
    <div className="card">
      <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
        <div>
          <h3>Statement of Applicability</h3>
          <span className="sub">
            {s.total} clauses · {s.applicable} applicable · {s.excluded} excluded ·{" "}
            <span style={{ color: s.no_control ? "var(--orange)" : undefined }}>{s.no_control} applicable without a control</span>
            {s.missing_justification > 0 && (
              <> · <span style={{ color: "var(--amber)" }}>{s.missing_justification} excluded without a justification</span></>
            )}
          </span>
        </div>
        <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
          <button className="btn secondary sm" type="button" onClick={() => exportAs("xlsx")} disabled={!!exporting}>
            {exporting === "xlsx" ? "Exporting…" : "Export XLSX"}
          </button>
          <button className="btn secondary sm" type="button" onClick={() => exportAs("pdf")} disabled={!!exporting}>
            {exporting === "pdf" ? "Exporting…" : "Export PDF"}
          </button>
        </div>
      </div>

      <div className="card-pad" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", paddingBottom: 8 }}>
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder="Search clauses or justifications…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search the Statement of Applicability"
        />
        <div className="seg">
          {VIEWS.map(([key, label]) => (
            <button key={key} type="button" className={view === key ? "on" : ""} onClick={() => setView(key)}>
              {label}
              {key === "excluded" ? ` (${s.excluded})` : key === "no_control" ? ` (${s.no_control})` : ""}
            </button>
          ))}
        </div>
        <span className="muted" style={{ fontSize: 12 }}>
          Excluding a clause needs a justification. Exports follow the filter.
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 80 }}>Ref</th>
              <th>Clause</th>
              <th style={{ width: 96 }}>Applicable</th>
              <th style={{ width: "26%" }}>Justification</th>
              <th style={{ width: "24%" }}>Implementing controls</th>
              <th style={{ width: 120 }}>Status</th>
              <th style={{ width: 110 }}>Last test</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={7} className="muted" style={{ padding: 20, textAlign: "center" }}>No clauses match this view.</td></tr>
            )}
            {rows.map((r) => {
              const isEditing = editing?.id === r.requirement_id;
              const busy = busyId === r.requirement_id;
              return (
                <tr key={r.requirement_id} style={r.applicable ? undefined : { opacity: 0.85 }}>
                  <td><span className="ref">{r.reference || "—"}</span></td>
                  <td>
                    <div className="cell-title">{r.title}</div>
                    {r.domain && <div className="muted" style={{ fontSize: 11.5 }}>{r.domain}</div>}
                  </td>
                  <td>
                    <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: busy ? "wait" : "pointer", fontSize: 12.5 }}>
                      <input
                        type="checkbox"
                        checked={isEditing ? editing.applicable : r.applicable}
                        disabled={busy}
                        onChange={() => toggle(r)}
                        aria-label={`${r.reference || r.title} applicable`}
                      />
                      {r.applicable ? "Yes" : <b>No</b>}
                    </label>
                  </td>
                  <td>
                    {isEditing ? (
                      <div style={{ display: "grid", gap: 6 }}>
                        <textarea
                          className="input"
                          rows={3}
                          autoFocus
                          value={editing.text}
                          onChange={(e) => setEditing({ ...editing, text: e.target.value })}
                          placeholder={editing.applicable ? "Why this clause applies (recommended)" : "Why this clause does not apply (required)"}
                          aria-label="Justification"
                        />
                        <div style={{ display: "flex", gap: 6 }}>
                          <button
                            className="btn sm"
                            type="button"
                            disabled={!editingValid || busy}
                            title={editingValid ? undefined : "Say why the clause does not apply"}
                            onClick={() => save(r.requirement_id, editing.applicable, editing.text)}
                          >
                            {busy ? "Saving…" : editing.applicable ? "Save" : "Exclude"}
                          </button>
                          <button className="btn secondary sm" type="button" onClick={() => setEditing(null)} disabled={busy}>
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                        <span style={{ flex: 1, fontSize: 12.5, whiteSpace: "pre-wrap" }}>
                          {r.justification || (
                            r.applicable
                              ? <span className="muted">—</span>
                              : <span style={{ color: "var(--amber)" }}>Missing — required for an exclusion</span>
                          )}
                        </span>
                        <button
                          className="btn secondary sm"
                          type="button"
                          onClick={() => setEditing({ id: r.requirement_id, applicable: r.applicable, text: r.justification })}
                          aria-label={`Edit justification for ${r.reference || r.title}`}
                        >
                          Edit
                        </button>
                      </div>
                    )}
                  </td>
                  <td>
                    {r.controls.length === 0 ? (
                      r.applicable ? <Badge tone="medium" plain>None</Badge> : <span className="muted">—</span>
                    ) : (
                      <div style={{ display: "grid", gap: 4 }}>
                        {r.controls.map((c) => (
                          <div key={c.id} style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: 12.5 }}>
                            <Link href={`/controls?id=${c.id}`} className="ref">{c.reference || c.name}</Link>
                            {c.reference && <span className="muted">{c.name}</span>}
                            <EffectivenessBadge value={c.effectiveness} />
                          </div>
                        ))}
                      </div>
                    )}
                  </td>
                  <td><ComplianceBadge value={r.implementation_status} /></td>
                  <td style={{ fontSize: 12.5 }}>
                    {r.last_test_date ? (
                      <>
                        <div>{r.last_test_date}</div>
                        <div className="muted" style={{ fontSize: 11.5 }}>{words(r.last_test_result)}</div>
                      </>
                    ) : <span className="muted">Never</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
