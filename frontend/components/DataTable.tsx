"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { apiCall } from "@/lib/api";
import { type ListQuery, type Page, toQueryString, useDebounced, useLatest } from "@/lib/list";

/* The list workbench every register page shares.

   A register is where GRC work actually happens — a risk manager lives in the risk
   list, not in individual records — so the list has to carry the same information a
   record does and let each person arrange it their way. Four things make it that
   rather than a table:

   · A **column catalogue** wider than the default view. Pages declare every column
     they can show; the user adds, removes and reorders them, and the layout is
     remembered per table.
   · **Saved views** — a named arrangement of columns, sort, search and filters, shown
     as tabs. "Top risks", "Review deadline this month", "Mine". The question is saved,
     the rows are always live.
   · **Bulk selection** with a per-page actions slot, plus export of the selection.
   · **Dynamic status** chips from the status-rules engine ("Control audit failed",
     "High score"), evaluated in one call for the page of rows.

   Layout, views and density persist in localStorage under the table's key. They are
   per person and per browser on purpose: how I arrange my register is not a decision
   the organisation needs to record. */

export type Column<T> = {
  key: string;
  header: string;
  /** cell renderer; defaults to String(row[key]) */
  render?: (row: T) => ReactNode;
  /** allow server sort on this column (key must be in the endpoint's sort allow-list) */
  sortable?: boolean;
  align?: "left" | "right" | "center";
  width?: string | number;
  /** Not shown until the user adds it from the column chooser. */
  hidden?: boolean;
  /** Cannot be hidden. The key "actions" is treated as locked and kept last. */
  locked?: boolean;
  /** Plain-text value for the CSV of a selection; defaults to String(row[key]). */
  text?: (row: T) => string;
};

export type SavedView = {
  id: string;
  name: string;
  columns: string[];
  sort: { by: string; dir: "asc" | "desc" } | null;
  search: string;
  filters?: Record<string, string | number | boolean | undefined>;
};

type Density = "comfortable" | "compact";

type Prefs = {
  columns?: string[];
  density?: Density;
  views?: SavedView[];
  activeView?: string | null;
};

type StatusLabel = { label: string; color: string };

type Props<T> = {
  columns: Column<T>[];
  /** fetch one page from the server for the given query */
  fetcher: (qs: string) => Promise<Page<T>>;
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  /** id of the currently open record, to highlight its row */
  activeKey?: string | null;
  searchPlaceholder?: string;
  /** page-specific filters (status dropdowns etc.); changing this refetches from page 0 */
  filters?: Record<string, string | number | boolean | undefined>;
  /** toolbar content on the right (Add button, export, …) */
  toolbarRight?: ReactNode;
  pageSize?: number;
  defaultSort?: { by: string; dir: "asc" | "desc" };
  emptyMessage?: string;
  /** bump this number to force a refetch (e.g. after a create/delete elsewhere) */
  refreshKey?: number;
  /** Stable key for remembering layout, views and density. Defaults to the URL path. */
  tableKey?: string;
  /** Status-rules model name ("risk", "control", "asset", …) — adds the Dynamic status column. */
  statusModel?: string;
  /** Enable bulk selection. Receives the selected rows and a function to clear them. */
  bulkActions?: (selected: T[], clear: () => void) => ReactNode;
  /** Lets a saved view restore the page's own filters. Without it, views keep columns, sort and search only. */
  onApplyFilters?: (filters: Record<string, string | number | boolean | undefined>) => void;
};

const STATUS_KEY = "__dynamic_status";
const SELECT_KEY = "__select";

const TONE_COLORS: Record<string, string> = {
  red: "var(--red)", danger: "var(--red)", critical: "var(--red)",
  orange: "var(--orange)", high: "var(--orange)", warning: "var(--amber)",
  amber: "var(--amber)", yellow: "var(--amber)", medium: "var(--amber)",
  green: "var(--green)", success: "var(--green)", low: "var(--green)", ok: "var(--green)",
  blue: "var(--primary-text)", info: "var(--primary-text)", primary: "var(--primary-text)",
  grey: "var(--muted)", gray: "var(--muted)", neutral: "var(--muted)",
};

function statusColor(color: string): string {
  if (!color) return "var(--muted)";
  if (color.startsWith("#") || color.startsWith("rgb") || color.startsWith("var(")) return color;
  return TONE_COLORS[color.toLowerCase()] ?? "var(--muted)";
}

function readPrefs(key: string): Prefs {
  try {
    return JSON.parse(localStorage.getItem(key) || "{}") as Prefs;
  } catch {
    return {};
  }
}

function writePrefs(key: string, prefs: Prefs) {
  try {
    localStorage.setItem(key, JSON.stringify(prefs));
  } catch {
    /* private mode, quota — layout simply is not remembered */
  }
}

function csvCell(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}

export default function DataTable<T>({
  columns,
  fetcher,
  rowKey,
  onRowClick,
  activeKey,
  searchPlaceholder = "Search…",
  filters,
  toolbarRight,
  pageSize = 25,
  defaultSort,
  emptyMessage = "No records yet.",
  refreshKey = 0,
  tableKey,
  statusModel,
  bulkActions,
  onApplyFilters,
}: Props<T>) {
  const prefsKey = `nx.table.${tableKey ?? (typeof window !== "undefined" ? window.location.pathname : "table")}`;

  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ by: string; dir: "asc" | "desc" } | null>(defaultSort ?? null);
  const [rawSearch, setRawSearch] = useState("");
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [err, setErr] = useState("");
  const search = useDebounced(rawSearch, 300);
  const latest = useLatest();

  // ------------------------------------------------------------ layout prefs
  const [prefs, setPrefs] = useState<Prefs>({});
  const [prefsLoaded, setPrefsLoaded] = useState(false);
  useEffect(() => {
    setPrefs(readPrefs(prefsKey));
    setPrefsLoaded(true);
  }, [prefsKey]);
  const savePrefs = useCallback(
    (patch: Partial<Prefs>) =>
      setPrefs((p) => {
        const next = { ...p, ...patch };
        writePrefs(prefsKey, next);
        return next;
      }),
    [prefsKey],
  );

  const density: Density = prefs.density ?? "comfortable";
  const [showColumns, setShowColumns] = useState(false);
  const [savingView, setSavingView] = useState(false);
  const [viewName, setViewName] = useState("");

  // ----------------------------------------------------------- column model
  const catalogue = useMemo(() => {
    const cols = [...columns];
    if (statusModel) {
      cols.unshift({ key: STATUS_KEY, header: "Dynamic status", hidden: false } as Column<T>);
    }
    return cols;
  }, [columns, statusModel]);
  const byKey = useMemo(() => new Map(catalogue.map((c) => [c.key, c])), [catalogue]);
  const isLocked = (c: Column<T>) => c.locked || c.key === "actions";
  const defaultKeys = useMemo(
    () => catalogue.filter((c) => !c.hidden || isLocked(c)).map((c) => c.key),
    [catalogue], // eslint-disable-line react-hooks/exhaustive-deps
  );

  /** Visible columns in order: the remembered layout, with locked columns guaranteed
   *  and anything the page no longer declares dropped. "actions" stays last. */
  const visible = useMemo(() => {
    const chosen = (prefs.columns ?? defaultKeys).filter((k) => byKey.has(k));
    const ensured = [...chosen];
    for (const c of catalogue) if (isLocked(c) && !ensured.includes(c.key)) ensured.push(c.key);
    const ordered = ensured.filter((k) => k !== "actions");
    if (ensured.includes("actions")) ordered.push("actions");
    return ordered.map((k) => byKey.get(k)!);
  }, [prefs.columns, defaultKeys, byKey, catalogue]); // eslint-disable-line react-hooks/exhaustive-deps

  const setVisibleKeys = (keys: string[]) => savePrefs({ columns: keys, activeView: null });

  // ------------------------------------------------------------------ query
  const filtersKey = JSON.stringify(filters ?? {});
  useEffect(() => setPage(0), [filtersKey, search, sort?.by, sort?.dir]);

  const query = useMemo<ListQuery>(
    () => ({
      limit: pageSize,
      offset: page * pageSize,
      q: search || undefined,
      sort_by: sort?.by ?? null,
      sort_dir: sort?.dir,
      extra: filters,
    }),
    [pageSize, page, search, sort, filtersKey], // eslint-disable-line react-hooks/exhaustive-deps
  );

  // ---------------------------------------------------------- dynamic status
  const [statuses, setStatuses] = useState<Record<string, StatusLabel[]>>({});
  const loadStatuses = useCallback(
    async (items: T[]) => {
      if (!statusModel || items.length === 0) return;
      try {
        const res = await apiCall<Record<string, StatusLabel[]>>(
          "POST", `/status-rules/evaluate/${statusModel}`, { ids: items.map(rowKey) },
        );
        setStatuses(res || {});
      } catch {
        setStatuses({});
      }
    },
    [statusModel, rowKey],
  );

  const load = useCallback(async () => {
    const n = latest.next();
    setStatus("loading");
    try {
      const res = await fetcher(toQueryString(query));
      if (!latest.isCurrent(n)) return;
      setRows(res.items);
      setTotal(res.total);
      setStatus("ok");
      loadStatuses(res.items);
    } catch (e) {
      if (!latest.isCurrent(n)) return;
      setErr(e instanceof Error ? e.message : "Failed to load");
      setStatus("error");
    }
  }, [fetcher, query, loadStatuses]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  function toggleSort(key: string) {
    setSort((s) =>
      s?.by === key ? { by: key, dir: s.dir === "asc" ? "desc" : "asc" } : { by: key, dir: "asc" },
    );
  }

  // -------------------------------------------------------------- selection
  const [selected, setSelected] = useState<Map<string, T>>(new Map());
  const clearSelection = useCallback(() => setSelected(new Map()), []);
  useEffect(() => { clearSelection(); }, [filtersKey, search, clearSelection]);
  const pageKeys = rows.map(rowKey);
  const allOnPage = pageKeys.length > 0 && pageKeys.every((k) => selected.has(k));
  const toggleRow = (row: T) =>
    setSelected((m) => {
      const next = new Map(m);
      const k = rowKey(row);
      if (next.has(k)) next.delete(k); else next.set(k, row);
      return next;
    });
  const togglePage = () =>
    setSelected((m) => {
      const next = new Map(m);
      if (allOnPage) pageKeys.forEach((k) => next.delete(k));
      else rows.forEach((r) => next.set(rowKey(r), r));
      return next;
    });

  function exportSelection() {
    const cols = visible.filter((c) => c.key !== "actions" && c.key !== STATUS_KEY);
    const lines = [cols.map((c) => csvCell(c.header)).join(",")];
    for (const row of selected.values()) {
      lines.push(cols.map((c) => csvCell(
        c.text ? c.text(row) : String((row as Record<string, unknown>)[c.key] ?? ""),
      )).join(","));
    }
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(tableKey ?? "selection").replace(/[^a-z0-9]+/gi, "-")}-selection.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ------------------------------------------------------------------ views
  const views = prefs.views ?? [];
  const activeView = prefs.activeView ?? null;

  function applyView(v: SavedView | null) {
    if (!v) {
      savePrefs({ columns: undefined, activeView: null });
      setSort(defaultSort ?? null);
      setRawSearch("");
      onApplyFilters?.({});
      return;
    }
    savePrefs({ columns: v.columns, activeView: v.id });
    setSort(v.sort);
    setRawSearch(v.search);
    if (v.filters !== undefined) onApplyFilters?.(v.filters);
  }

  function saveView() {
    const name = viewName.trim();
    if (!name) return;
    const v: SavedView = {
      id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`,
      name,
      columns: visible.map((c) => c.key),
      sort,
      search: rawSearch,
      filters: onApplyFilters ? filters : undefined,
    };
    savePrefs({ views: [...views, v], activeView: v.id });
    setViewName("");
    setSavingView(false);
  }

  function deleteView(id: string) {
    savePrefs({ views: views.filter((v) => v.id !== id), activeView: activeView === id ? null : activeView });
  }

  // ------------------------------------------------------------------ render
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
  const colSpan = visible.length + (bulkActions ? 1 : 0);

  const cell = (c: Column<T>, row: T) => {
    if (c.key === STATUS_KEY) {
      const labels = statuses[rowKey(row)] ?? [];
      return labels.length ? (
        <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
          {labels.map((l) => (
            <span key={l.label} className="dyn-status" style={{ color: statusColor(l.color), borderColor: "currentColor" }}>
              {l.label}
            </span>
          ))}
        </span>
      ) : <span className="muted">—</span>;
    }
    return c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—");
  };

  return (
    <div className="card">
      {/* ------------------------------------------------------------ views */}
      <div className="view-tabs">
        <button className={`view-tab${activeView === null ? " active" : ""}`} onClick={() => applyView(null)}>
          All items <span className="view-count">{status === "ok" ? total.toLocaleString() : "…"}</span>
        </button>
        {views.map((v) => (
          <span key={v.id} className={`view-tab${activeView === v.id ? " active" : ""}`} onClick={() => applyView(v)}>
            {v.name}
            <button className="view-x" title="Delete view" onClick={(e) => { e.stopPropagation(); deleteView(v.id); }}>×</button>
          </span>
        ))}
        {savingView ? (
          <form className="view-save" onSubmit={(e) => { e.preventDefault(); saveView(); }}>
            <input className="input" autoFocus placeholder="View name" value={viewName} onChange={(e) => setViewName(e.target.value)} />
            <button className="btn sm" type="submit">Save</button>
            <button className="btn secondary sm" type="button" onClick={() => setSavingView(false)}>Cancel</button>
          </form>
        ) : (
          <button className="view-tab add" title="Save the current columns, sort, search and filters as a view" onClick={() => setSavingView(true)}>
            + Save view
          </button>
        )}
      </div>

      {/* --------------------------------------------------------- toolbar */}
      <div className="card-head" style={{ gap: 12, flexWrap: "wrap" }}>
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder={searchPlaceholder}
          value={rawSearch}
          onChange={(e) => setRawSearch(e.target.value)}
        />
        {selected.size > 0 && bulkActions && (
          <div className="bulk-bar">
            <b>{selected.size} selected</b>
            {bulkActions([...selected.values()], clearSelection)}
            <button className="btn secondary sm" onClick={exportSelection}>Export CSV</button>
            <button className="btn secondary sm" onClick={clearSelection}>Clear</button>
          </div>
        )}
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {toolbarRight}
          <button
            className="btn secondary sm"
            title={density === "compact" ? "Comfortable rows" : "Compact rows"}
            onClick={() => savePrefs({ density: density === "compact" ? "comfortable" : "compact" })}
          >
            {density === "compact" ? "☰" : "≡"}
          </button>
          <button className="btn secondary sm" onClick={() => setShowColumns(true)} title="Choose and order columns">
            Columns · {visible.filter((c) => c.key !== "actions").length}
          </button>
        </div>
      </div>

      {/* ----------------------------------------------------------- table */}
      <div className="table-wrap">
        <table className={density === "compact" ? "compact" : undefined}>
          <thead>
            <tr>
              {bulkActions && (
                <th style={{ width: 36 }}>
                  <input type="checkbox" checked={allOnPage} onChange={togglePage} aria-label="Select page" />
                </th>
              )}
              {visible.map((c) => {
                const active = sort?.by === c.key;
                return (
                  <th
                    key={c.key}
                    style={{
                      width: c.width,
                      textAlign: c.align,
                      cursor: c.sortable ? "pointer" : undefined,
                      userSelect: "none",
                      whiteSpace: "nowrap",
                    }}
                    onClick={c.sortable ? () => toggleSort(c.key) : undefined}
                    aria-sort={active ? (sort!.dir === "asc" ? "ascending" : "descending") : undefined}
                  >
                    {c.header}
                    {c.sortable && (
                      <span className="muted" style={{ marginLeft: 4, opacity: active ? 1 : 0.35 }}>
                        {active ? (sort!.dir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {(status === "loading" || !prefsLoaded) &&
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={`sk-${i}`}>
                  {bulkActions && <td />}
                  {visible.map((c) => (
                    <td key={c.key}><span className="skeleton" /></td>
                  ))}
                </tr>
              ))}

            {status === "error" && (
              <tr>
                <td colSpan={colSpan}>
                  <div className="error" style={{ margin: 8 }}>
                    {err} · <button className="linklike" onClick={load}>retry</button>
                  </div>
                </td>
              </tr>
            )}

            {status === "ok" && prefsLoaded && rows.length === 0 && (
              <tr>
                <td colSpan={colSpan}>
                  <div className="empty" style={{ padding: 28 }}>
                    <p>{search || filters ? "No records match your filters." : emptyMessage}</p>
                  </div>
                </td>
              </tr>
            )}

            {status === "ok" && prefsLoaded &&
              rows.map((row) => {
                const k = rowKey(row);
                return (
                  <tr
                    key={k}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={[activeKey === k ? "active-row" : "", selected.has(k) ? "selected-row" : ""].join(" ").trim() || undefined}
                    style={{ cursor: onRowClick ? "pointer" : undefined }}
                  >
                    {bulkActions && (
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selected.has(k)} onChange={() => toggleRow(row)} aria-label="Select row" />
                      </td>
                    )}
                    {visible.map((c) => (
                      <td key={c.key} style={{ textAlign: c.align }}>{cell(c, row)}</td>
                    ))}
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>

      <div
        className="table-foot"
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, padding: "10px 14px" }}
      >
        <span className="muted" style={{ fontSize: 13 }}>
          {status === "ok" ? (total === 0 ? "0 records" : `${from}–${to} of ${total.toLocaleString()}`) : "…"}
        </span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn secondary sm" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
            ‹ Prev
          </button>
          <span className="muted" style={{ fontSize: 13 }}>
            Page {lastPage === 0 ? 1 : page + 1} / {lastPage + 1}
          </span>
          <button className="btn secondary sm" disabled={page >= lastPage} onClick={() => setPage((p) => p + 1)}>
            Next ›
          </button>
        </div>
      </div>

      {showColumns && (
        <ColumnsPanel
          catalogue={catalogue}
          visible={visible.map((c) => c.key)}
          isLocked={isLocked}
          onChange={setVisibleKeys}
          onReset={() => savePrefs({ columns: undefined, activeView: null })}
          onClose={() => setShowColumns(false)}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------ column chooser */
function ColumnsPanel<T>({
  catalogue, visible, isLocked, onChange, onReset, onClose,
}: {
  catalogue: Column<T>[];
  visible: string[];
  isLocked: (c: Column<T>) => boolean;
  onChange: (keys: string[]) => void;
  onReset: () => void;
  onClose: () => void;
}) {
  const dragKey = useRef<string | null>(null);
  const shown = visible.filter((k) => k !== "actions");
  const hiddenCols = catalogue.filter((c) => !visible.includes(c.key) && c.key !== "actions");
  const label = (k: string) => catalogue.find((c) => c.key === k)?.header ?? k;

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const commit = (keys: string[]) => onChange(visible.includes("actions") ? [...keys, "actions"] : keys);

  function move(from: string, to: string) {
    if (from === to) return;
    const next = shown.filter((k) => k !== from);
    next.splice(next.indexOf(to), 0, from);
    commit(next);
  }

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" style={{ width: 380 }} onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2 style={{ margin: 0 }}>Columns</h2>
            <div className="muted" style={{ fontSize: 12.5 }}>
              {shown.length} of {catalogue.filter((c) => c.key !== "actions").length} shown · drag to reorder
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn secondary sm" onClick={onReset}>Reset</button>
            <button className="btn secondary sm" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </div>
        <div className="drawer-body" style={{ padding: "8px 12px" }}>
          {shown.map((k) => {
            const c = catalogue.find((x) => x.key === k)!;
            const locked = isLocked(c);
            return (
              <div
                key={k}
                className="col-row"
                draggable
                onDragStart={() => { dragKey.current = k; }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => { if (dragKey.current) move(dragKey.current, k); dragKey.current = null; }}
              >
                <span className="col-grip" aria-hidden>⠿</span>
                <span style={{ flex: 1, fontSize: 13.5 }}>{label(k)}</span>
                {locked ? (
                  <span className="muted" title="Always shown" style={{ fontSize: 12 }}>🔒</span>
                ) : (
                  <button className="linklike" title="Hide column" onClick={() => commit(shown.filter((x) => x !== k))}>Hide</button>
                )}
              </div>
            );
          })}
          {hiddenCols.length > 0 && (
            <>
              <div className="bt" style={{ margin: "14px 4px 6px" }}>Add column</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: "0 4px" }}>
                {hiddenCols.map((c) => (
                  <button key={c.key} className="chip" style={{ cursor: "pointer" }} onClick={() => commit([...shown, c.key])}>
                    + {c.header}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
