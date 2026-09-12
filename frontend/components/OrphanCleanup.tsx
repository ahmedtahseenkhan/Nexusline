"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { api, type OrphanedRisk } from "@/lib/api";
import { Badge } from "@/components/badges";
import { Field, TextArea } from "@/components/fields";

/* Housekeeping for the register: risks whose linked assets were all deleted and
   that link to nothing else live — no control, business unit, process, policy,
   incident, requirement, KRI, issue or any other record. They usually come from a
   bulk generation run against assets that were later removed.

   Nothing is ticked and nothing is archived until the reviewer ticks rows, writes a
   reason and presses the button. The server checks each risk again at that moment
   and skips any that gained a link. Archiving is the ordinary soft delete: the risk
   leaves the register but stays in the database, and each one gets its own entry in
   the audit trail with the reason. */

type Props = { onDone?: () => void };

export type OrphanCleanupHandle = { open: () => void };

const OrphanCleanup = forwardRef<OrphanCleanupHandle, Props & { hideButton?: boolean }>(function OrphanCleanup(
  { onDone, hideButton }, ref,
) {
  const [open, setOpen] = useState(false);
  useImperativeHandle(ref, () => ({ open: () => setOpen(true) }));

  return (
    <>
      {!hideButton && (
      <button
        className="btn secondary"
        onClick={() => setOpen(true)}
        title="Find risks whose assets were deleted and that link to nothing else"
      >
        Review risks with no live links
      </button>
      )}
      {open && <CleanupModal onClose={() => setOpen(false)} onDone={onDone} />}
    </>
  );
});

export default OrphanCleanup;

function CleanupModal({ onClose, onDone }: Props & { onClose: () => void }) {
  const [rows, setRows] = useState<(OrphanedRisk & { include: boolean })[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ archived: number; refs: string[]; skipped: number } | null>(null);
  const [kept, setKept] = useState(0);
  const [reason, setReason] = useState("");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.orphanedRisks();
      // Nothing is pre-ticked: every archive is a choice somebody made row by row.
      setRows(res.items.map((r) => ({ ...r, include: false })));
      setKept(res.kept_with_links ?? 0);
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not check the register");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selected = useMemo(() => rows.filter((r) => r.include), [rows]);
  const canArchive = selected.length > 0 && reason.trim().length > 0;

  async function purge() {
    if (!canArchive) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.purgeOrphanedRisks(selected.map((r) => r.id), reason.trim());
      setResult({ archived: res.archived, refs: res.references, skipped: res.skipped ?? 0 });
      if (res.archived > 0) onDone?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not archive the risks");
    } finally {
      setBusy(false);
    }
  }

  function toggle(id: string, include: boolean) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, include } : r)));
  }

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-label="Review risks with no live links">
        <div className="modal-head">
          <h2>Review risks with no live links</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          {result ? (
            <div className="card card-pad">
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <Badge tone="low">Archived {result.archived}</Badge>
                {result.skipped > 0 && <Badge tone="info">Skipped {result.skipped}</Badge>}
                <span className="muted" style={{ fontSize: 13 }}>
                  {result.refs.slice(0, 12).join(", ")}
                  {result.refs.length > 12 ? ` … +${result.refs.length - 12} more` : ""}
                </span>
              </div>
              {result.skipped > 0 && (
                <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                  {result.skipped} selected risk{result.skipped !== 1 ? "s" : ""} gained a live link
                  since this list loaded and stayed in the register.
                </p>
              )}
              <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, marginBottom: 0 }}>
                Archived risks are hidden from the register and kept in the database. Each one
                has its own audit-log entry with your reason. A screen to restore them is coming
                in a later release.
              </p>
            </div>
          ) : (
            <>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, marginTop: 0 }}>
                These risks were linked to assets that have since been deleted, and link to
                nothing else that is still live: no control, business unit, process, policy,
                incident, requirement, KRI, issue or other record. They are usually leftovers
                from a generation run against assets that were later removed. <b>Tick only the
                risks you want to archive and give a reason</b>. Risks with no asset links at all
                are never on this list.
              </p>
              <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                Archived risks are hidden from the register and kept in the database. A screen to
                restore them is coming in a later release.
              </p>

              {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

              {loaded && (
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
                  <Badge tone={rows.length ? "medium" : "low"}>
                    {rows.length} risk{rows.length !== 1 ? "s" : ""} with no live links
                  </Badge>
                  <Badge tone={selected.length ? "info" : "neutral"}>{selected.length} selected</Badge>
                  {kept > 0 && (
                    <span className="muted" style={{ fontSize: 12.5 }}>
                      {kept} other risk{kept !== 1 ? "s" : ""} lost {kept !== 1 ? "their" : "its"} assets
                      but still link to live records, so {kept !== 1 ? "they stay" : "it stays"} in the register.
                    </span>
                  )}
                </div>
              )}

              {loaded && rows.length === 0 && !error && (
                <div className="muted" style={{ fontSize: 13 }}>
                  Nothing to review. Every risk that lost its assets still links to something live.
                </div>
              )}

              {rows.length > 0 && (
                <div className="table-wrap" style={{ maxHeight: 430, overflowY: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th style={{ width: 34 }}>
                          <input
                            type="checkbox"
                            checked={rows.every((r) => r.include)}
                            onChange={(e) => setRows((prev) => prev.map((r) => ({ ...r, include: e.target.checked })))}
                            aria-label="Select all"
                          />
                        </th>
                        <th style={{ width: 90 }}>Ref</th>
                        <th>Risk</th>
                        <th>Deleted asset(s)</th>
                        <th style={{ width: 90 }}>Live links</th>
                        <th style={{ width: 70 }}>Score</th>
                        <th style={{ width: 90 }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row) => (
                        <tr key={row.id}>
                          <td>
                            <input
                              type="checkbox"
                              checked={row.include}
                              onChange={(e) => toggle(row.id, e.target.checked)}
                              aria-label={`Include ${row.reference}`}
                            />
                          </td>
                          <td className="ref">{row.reference}</td>
                          <td>
                            <span style={{ fontSize: 13 }}>{row.title}</span>
                            {row.category && (
                              <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>{row.category}</div>
                            )}
                          </td>
                          <td className="muted" style={{ fontSize: 12.5 }}>
                            {row.deleted_asset_names.slice(0, 3).join(", ") || "—"}
                            {row.deleted_asset_names.length > 3 ? ` +${row.deleted_asset_names.length - 3} more` : ""}
                          </td>
                          <td className="muted" style={{ fontSize: 12.5 }} title={linkSummary(row) || "No live links"}>
                            {row.live_link_total ? linkSummary(row) : "0"}
                          </td>
                          <td className="ref">{row.inherent_score ?? "—"}</td>
                          <td className="muted" style={{ fontSize: 12.5 }}>{row.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {rows.length > 0 && (
                <div style={{ marginTop: 14 }}>
                  <Field
                    label="Reason"
                    required
                    help="Recorded in the audit trail against every risk you archive."
                  >
                    <TextArea
                      value={reason}
                      onChange={setReason}
                      rows={2}
                      placeholder="For example: generated against servers decommissioned in the 2026 data-centre move"
                    />
                  </Field>
                </div>
              )}
            </>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn secondary" type="button" onClick={onClose} disabled={busy}>
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button
              className="btn"
              type="button"
              onClick={purge}
              disabled={busy || !canArchive}
              title={
                selected.length === 0 ? "Tick at least one risk" : !reason.trim() ? "Give a reason" : undefined
              }
            >
              {busy ? "Working…" : `Archive ${selected.length} selected`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** "2 controls, 1 KRI" — the live links a risk still has, largest first. */
function linkSummary(row: OrphanedRisk): string {
  return Object.entries(row.live_links ?? {})
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([kind, n]) => `${n} ${kind.replace(/_/g, " ")}`)
    .join(", ");
}
