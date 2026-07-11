"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { type ListQuery, type Page, toQueryString, useDebounced, useLatest } from "@/lib/list";

export type Column<T> = {
  key: string;
  header: string;
  /** cell renderer; defaults to String(row[key]) */
  render?: (row: T) => ReactNode;
  /** allow server sort on this column (key must be in the endpoint's sort allow-list) */
  sortable?: boolean;
  align?: "left" | "right" | "center";
  width?: string | number;
};

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
};

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
}: Props<T>) {
  const [rows, setRows] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [sort, setSort] = useState<{ by: string; dir: "asc" | "desc" } | null>(defaultSort ?? null);
  const [rawSearch, setRawSearch] = useState("");
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [err, setErr] = useState("");
  const search = useDebounced(rawSearch, 300);
  const latest = useLatest();

  const filtersKey = JSON.stringify(filters ?? {});

  // Any filter/search/sort change resets to the first page.
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

  const load = useCallback(async () => {
    const n = latest.next();
    setStatus("loading");
    try {
      const res = await fetcher(toQueryString(query));
      if (!latest.isCurrent(n)) return; // a newer request superseded this one
      setRows(res.items);
      setTotal(res.total);
      setStatus("ok");
    } catch (e) {
      if (!latest.isCurrent(n)) return;
      setErr(e instanceof Error ? e.message : "Failed to load");
      setStatus("error");
    }
  }, [fetcher, query]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  function toggleSort(key: string) {
    setSort((s) =>
      s?.by === key ? { by: key, dir: s.dir === "asc" ? "desc" : "asc" } : { by: key, dir: "asc" },
    );
  }

  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);

  return (
    <div className="card">
      <div className="card-head" style={{ gap: 12, flexWrap: "wrap" }}>
        <input
          className="input"
          style={{ maxWidth: 280 }}
          placeholder={searchPlaceholder}
          value={rawSearch}
          onChange={(e) => setRawSearch(e.target.value)}
        />
        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>{toolbarRight}</div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {columns.map((c) => {
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
            {status === "loading" &&
              Array.from({ length: 6 }).map((_, i) => (
                <tr key={`sk-${i}`}>
                  {columns.map((c) => (
                    <td key={c.key}>
                      <span className="skeleton" />
                    </td>
                  ))}
                </tr>
              ))}

            {status === "error" && (
              <tr>
                <td colSpan={columns.length}>
                  <div className="error" style={{ margin: 8 }}>
                    {err} · <button className="linklike" onClick={load}>retry</button>
                  </div>
                </td>
              </tr>
            )}

            {status === "ok" && rows.length === 0 && (
              <tr>
                <td colSpan={columns.length}>
                  <div className="empty" style={{ padding: 28 }}>
                    <p>{search || filters ? "No records match your filters." : emptyMessage}</p>
                  </div>
                </td>
              </tr>
            )}

            {status === "ok" &&
              rows.map((row) => {
                const k = rowKey(row);
                return (
                  <tr
                    key={k}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={activeKey === k ? "active-row" : undefined}
                    style={{ cursor: onRowClick ? "pointer" : undefined }}
                  >
                    {columns.map((c) => (
                      <td key={c.key} style={{ textAlign: c.align }}>
                        {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                      </td>
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
    </div>
  );
}
