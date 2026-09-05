"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { api, type OrphanedRisk } from "@/lib/api";
import { Badge } from "@/components/badges";

/* Housekeeping for the register: risks whose every linked asset has since been
   deleted. They usually come from a bulk generation run against assets that were
   later removed — still scored, still open, but pointing at nothing.

   Same contract as the generator, in reverse: nothing is archived until the
   user has seen the list and pressed the button. Archiving is the ordinary
   soft delete, so anything removed here can be recovered from the database. */

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
        title="Find risks whose linked assets were all deleted"
      >
        Clean up orphans
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
  const [result, setResult] = useState<{ archived: number; refs: string[] } | null>(null);

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
      setRows(res.items.map((r) => ({ ...r, include: true })));
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

  async function purge() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.purgeOrphanedRisks(selected.map((r) => r.id));
      setResult({ archived: res.archived, refs: res.references });
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
      <div className="modal wide" role="dialog" aria-modal="true" aria-label="Clean up orphaned risks">
        <div className="modal-head">
          <h2>Clean up orphaned risks</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          {result ? (
            <div className="card card-pad">
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <Badge tone="low">Archived {result.archived}</Badge>
                <span className="muted" style={{ fontSize: 13 }}>
                  {result.refs.slice(0, 12).join(", ")}
                  {result.refs.length > 12 ? ` … +${result.refs.length - 12} more` : ""}
                </span>
              </div>
              <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, marginBottom: 0 }}>
                Archived, not destroyed — this is the same soft delete as the register&apos;s own
                Delete button, and each removal is in the audit log.
              </p>
            </div>
          ) : (
            <>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, marginTop: 0 }}>
                These risks were linked to assets that have since been deleted, and to nothing
                else that is still live — typically leftovers from a generation run against
                assets that were later removed. <b>Nothing is archived until you press the
                button</b> — untick anything you want to keep. Risks with no asset links at all
                are never on this list.
              </p>

              {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

              {loaded && (
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
                  <Badge tone={rows.length ? "medium" : "low"}>
                    {rows.length} orphaned risk{rows.length !== 1 ? "s" : ""}
                  </Badge>
                  <Badge tone={selected.length ? "info" : "neutral"}>{selected.length} selected</Badge>
                </div>
              )}

              {loaded && rows.length === 0 && !error && (
                <div className="muted" style={{ fontSize: 13 }}>
                  Nothing to clean — every risk with asset links still points at a live asset.
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
                          <td className="ref">{row.inherent_score ?? "—"}</td>
                          <td className="muted" style={{ fontSize: 12.5 }}>{row.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
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
              disabled={busy || selected.length === 0}
              title={selected.length === 0 ? "Select at least one risk" : undefined}
            >
              {busy ? "Working…" : `Archive ${selected.length} risk${selected.length !== 1 ? "s" : ""}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
