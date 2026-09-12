"use client";

/* "Archived (N)" for a register: a button that opens the archive of soft-deleted records
   of one type, with search and a Restore button per row.

     <ArchivedRecords entityType="risk" onRestored={() => reload()} refreshKey={deletes} />

   Uses GET /records/{entityType}/archived and POST /records/{entityType}/{id}/restore,
   so it needs the module's read permission to show and its write permission to restore
   (the server enforces both). Renders nothing when the archive can't be read — no
   permission, or a record type that isn't archived — so it is safe on any register.
   Restoring can be refused (409) when a live record now holds the same name; the
   server's message is shown as is. */

import { useCallback, useEffect, useRef, useState } from "react";
import { confirmDialog, toast } from "@/lib/feedback";
import { formatDateTime } from "@/lib/format";
import { records, type ArchivedRow } from "@/lib/records";

type Props = {
  /** Entity registry key: "risk", "control", "asset", "issue", "policy", "incident", "vendor"… */
  entityType: string;
  /** Called after a record is restored, so the register can reload. */
  onRestored?: (row: ArchivedRow) => void;
  /** Change this (e.g. a counter bumped after each delete) to refresh the count. */
  refreshKey?: string | number;
  /** Plural noun for the dialog title, e.g. "risks". Defaults to "records". */
  noun?: string;
};

const PAGE = 50;

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

export default function ArchivedRecords({ entityType, onRestored, refreshKey, noun = "records" }: Props) {
  const [count, setCount] = useState<number | null>(null);
  const [available, setAvailable] = useState(true);
  const [open, setOpen] = useState(false);

  const recount = useCallback(() => {
    records
      .archived(entityType, { limit: 1 })
      .then((page) => {
        setCount(page.total);
        setAvailable(true);
      })
      .catch(() => setAvailable(false));
  }, [entityType]);

  useEffect(recount, [recount, refreshKey]);

  if (!available) return null;

  return (
    <>
      <button
        type="button"
        className="btn secondary sm"
        onClick={() => setOpen(true)}
        title={`Deleted ${noun} are archived here and can be restored`}
      >
        Archived{count !== null ? ` (${count})` : ""}
      </button>
      {open && (
        <ArchiveDialog
          entityType={entityType}
          noun={noun}
          onClose={() => setOpen(false)}
          onRestored={(row) => {
            recount();
            onRestored?.(row);
          }}
        />
      )}
    </>
  );
}

function ArchiveDialog({
  entityType,
  noun,
  onClose,
  onRestored,
}: {
  entityType: string;
  noun: string;
  onClose: () => void;
  onRestored: (row: ArchivedRow) => void;
}) {
  const [rows, setRows] = useState<ArchivedRow[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [restoring, setRestoring] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    searchRef.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const load = useCallback(
    async (offset: number, term: string) => {
      setLoading(true);
      setError(null);
      try {
        const page = await records.archived(entityType, { search: term.trim() || undefined, limit: PAGE, offset });
        setRows((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
        setTotal(page.total);
      } catch (e) {
        setError(errMsg(e, "Could not load the archive"));
      } finally {
        setLoading(false);
      }
    },
    [entityType],
  );

  // Debounced search; the first load runs immediately.
  useEffect(() => {
    const t = setTimeout(() => load(0, search), search ? 250 : 0);
    return () => clearTimeout(t);
  }, [search, load]);

  async function restore(row: ArchivedRow) {
    const name = row.reference || row.title || "this record";
    const ok = await confirmDialog({
      title: `Restore ${name}?`,
      message:
        "It goes back into the register exactly as it was archived, with its links. The activity log records who restored it.",
      confirmLabel: "Restore",
    });
    if (!ok) return;
    setRestoring(row.id);
    try {
      const res = await records.restore(entityType, row.id);
      toast(`Restored ${res.reference || res.title || name}`);
      setRows((prev) => prev.filter((r) => r.id !== row.id));
      setTotal((n) => Math.max(0, n - 1));
      onRestored(row);
    } catch (e) {
      toast(errMsg(e, `Could not restore ${name}`), "error");
    } finally {
      setRestoring(null);
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-label={`Archived ${noun}`}>
        <div className="modal-head">
          <h2>Archived {noun}</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
            Deleted {noun} are kept here, hidden from the register, until the organisation&apos;s
            retention period ends; then they are purged for good. Restoring puts a record back
            exactly as it was.
          </p>

          <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
            <input
              ref={searchRef}
              className="input"
              style={{ maxWidth: 320 }}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search reference or title…"
              aria-label="Search the archive"
            />
            <span className="muted" style={{ fontSize: 12.5 }}>
              {loading && rows.length === 0 ? "Loading…" : `${total} archived`}
            </span>
          </div>

          {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}

          {!loading && !error && rows.length === 0 && (
            <div className="muted" style={{ fontSize: 13 }}>
              {search.trim() ? "Nothing in the archive matches that search." : `No archived ${noun}.`}
            </div>
          )}

          {rows.length > 0 && (
            <div className="table-wrap" style={{ maxHeight: 430, overflowY: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 100 }}>Ref</th>
                    <th>Title</th>
                    <th style={{ width: 170 }}>Archived</th>
                    <th style={{ width: 100 }} aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td className="ref">{row.reference || "—"}</td>
                      <td style={{ fontSize: 13 }}>{row.title || <span className="muted">Untitled</span>}</td>
                      <td className="muted" style={{ fontSize: 12.5 }}>
                        {row.deleted_date ? formatDateTime(row.deleted_date) : "—"}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        <button
                          type="button"
                          className="btn secondary sm"
                          onClick={() => restore(row)}
                          disabled={restoring !== null}
                        >
                          {restoring === row.id ? "Restoring…" : "Restore"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {rows.length < total && !error && (
            <div style={{ marginTop: 10 }}>
              <button type="button" className="btn secondary sm" onClick={() => load(rows.length, search)} disabled={loading}>
                {loading ? "Loading…" : `Show more (${total - rows.length} left)`}
              </button>
            </div>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
