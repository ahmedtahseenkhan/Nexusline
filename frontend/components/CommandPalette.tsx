"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type SearchHit } from "@/lib/api";
import { routeDisabled, useModules } from "@/lib/modules";
import { NAV } from "@/lib/nav";

type NavRow = { kind: "nav"; href: string; label: string; section: string };
type RecordRow = { kind: "record"; hit: SearchHit };
type Row = NavRow | RecordRow;

/** ⌘K / Ctrl-K command palette: fuzzy-jump to any licensed module and search records
 *  across every register from the keyboard. Mounted once in the app shell. */
export default function CommandPalette() {
  const router = useRouter();
  const { disabledRoutes } = useModules();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Flat list of navigable modules this installation has enabled — includes
  // group-level single links (Dashboard, Shariah) and every submenu item.
  const navRows = useMemo<NavRow[]>(
    () =>
      NAV.flatMap((s) => {
        const rows: NavRow[] = [];
        if (s.href && !routeDisabled(s.href, disabledRoutes))
          rows.push({ kind: "nav", href: s.href, label: s.title, section: s.title });
        for (const it of s.items)
          if (!routeDisabled(it.href, disabledRoutes))
            rows.push({ kind: "nav", href: it.href, label: it.label, section: s.title });
        return rows;
      }),
    [disabledRoutes]
  );

  const openPalette = useCallback(() => {
    setQ("");
    setHits([]);
    setActive(0);
    setOpen(true);
  }, []);

  // Global ⌘K / Ctrl-K toggle.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        setOpen((v) => !v);
        if (!open) openPalette();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, openPalette]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Debounced record search.
  useEffect(() => {
    if (!open) return;
    const term = q.trim();
    if (term.length < 2) {
      setHits([]);
      return;
    }
    const t = setTimeout(() => {
      api.search(term).then((r) => setHits(r.hits)).catch(() => setHits([]));
    }, 220);
    return () => clearTimeout(t);
  }, [q, open]);

  const term = q.trim().toLowerCase();
  const filteredNav = useMemo(() => {
    if (!term) return navRows.slice(0, 8);
    return navRows
      .filter((r) => r.label.toLowerCase().includes(term) || r.section.toLowerCase().includes(term))
      .slice(0, 8);
  }, [navRows, term]);

  const rows = useMemo<Row[]>(
    () => [...filteredNav, ...hits.map((hit) => ({ kind: "record" as const, hit }))],
    [filteredNav, hits]
  );

  // Keep the active index in range as results change.
  useEffect(() => {
    setActive((a) => (rows.length === 0 ? 0 : Math.min(a, rows.length - 1)));
  }, [rows.length]);

  const close = useCallback(() => setOpen(false), []);

  const choose = useCallback(
    (row: Row) => {
      close();
      router.push(row.kind === "nav" ? row.href : row.hit.link);
    },
    [close, router]
  );

  function onInputKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (rows[active]) choose(rows[active]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  }

  // Scroll the active row into view.
  useEffect(() => {
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${active}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [active]);

  if (!open) return null;

  const firstRecordIdx = filteredNav.length;

  return (
    <div className="cmdk-overlay" onMouseDown={close}>
      <div className="cmdk" role="dialog" aria-label="Command palette" onMouseDown={(e) => e.stopPropagation()}>
        <input
          ref={inputRef}
          className="cmdk-input"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setActive(0);
          }}
          onKeyDown={onInputKey}
          placeholder="Jump to a module or search records…"
          aria-label="Command palette search"
        />
        <div className="cmdk-list" ref={listRef}>
          {rows.length === 0 ? (
            <div className="cmdk-empty">{term.length < 2 ? "Type to search records…" : `No matches for “${q}”.`}</div>
          ) : (
            <>
              {filteredNav.length > 0 && <div className="cmdk-group">Navigate</div>}
              {filteredNav.map((r, i) => (
                <button
                  key={`nav-${r.href}`}
                  data-idx={i}
                  className={`cmdk-row${active === i ? " active" : ""}`}
                  onMouseMove={() => setActive(i)}
                  onClick={() => choose(r)}
                >
                  <span className="cmdk-row-title">{r.label}</span>
                  <span className="cmdk-row-sub">{r.section}</span>
                </button>
              ))}
              {hits.length > 0 && <div className="cmdk-group">Records</div>}
              {hits.map((hit, j) => {
                const idx = firstRecordIdx + j;
                return (
                  <button
                    key={`rec-${hit.type}-${hit.reference}-${j}`}
                    data-idx={idx}
                    className={`cmdk-row${active === idx ? " active" : ""}`}
                    onMouseMove={() => setActive(idx)}
                    onClick={() => choose({ kind: "record", hit })}
                  >
                    <span className="cmdk-row-title">{hit.title}</span>
                    <span className="cmdk-row-sub">{hit.label}</span>
                  </button>
                );
              })}
            </>
          )}
        </div>
        <div className="cmdk-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
          <span><kbd>↵</kbd> open</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </div>
  );
}
