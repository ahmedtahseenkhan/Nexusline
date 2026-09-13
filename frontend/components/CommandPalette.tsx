"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type SearchHit } from "@/lib/api";
import { routeDisabled, useModules } from "@/lib/modules";
import { visibleNav, type NavAccess } from "@/lib/nav";
import { useNavUser } from "@/lib/navPrefs";
import { useTenantSettings } from "@/lib/tenantSettings";
import { trapTab, useEscapeLayer } from "@/lib/escapeLayer";

type NavRow = { kind: "nav"; href: string; label: string; section: string };
type RecordRow = { kind: "record"; hit: SearchHit };
type Row = NavRow | RecordRow;

/** ⌘K / Ctrl-K command palette: fuzzy-jump to any licensed module and search records
 *  across every register from the keyboard. Mounted once in the app shell. Offers
 *  exactly the links the sidebar shows this user (licence + permission filter). */
export default function CommandPalette() {
  const router = useRouter();
  const { disabledRoutes } = useModules();
  const { permissions: shellPermissions } = useTenantSettings();
  const me = useNavUser();
  const access: NavAccess = useMemo(
    () => ({ permissions: shellPermissions.length ? shellPermissions : me?.permissions ?? [], platformAdmin: !!me?.platformAdmin }),
    [shellPermissions, me],
  );
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  // Combobox semantics: the input keeps focus and names the highlighted row through
  // aria-activedescendant, so a screen reader hears each row as ArrowUp / ArrowDown move.
  const uid = useId();
  const listId = `cmdk-list-${uid}`;
  const rowId = (i: number) => `cmdk-row-${uid}-${i}`;
  const boxRef = useRef<HTMLDivElement>(null);

  // Flat list of navigable modules this user may open in this installation — includes
  // group-level single links (Dashboard, Shariah) and every submenu item.
  const navRows = useMemo<NavRow[]>(
    () =>
      visibleNav(access, (href) => !routeDisabled(href, disabledRoutes)).flatMap((s) => {
        const rows: NavRow[] = [];
        if (s.href) rows.push({ kind: "nav", href: s.href, label: s.title, section: s.title });
        for (const it of s.items) rows.push({ kind: "nav", href: it.href, label: it.label, section: s.title });
        return rows;
      }),
    [disabledRoutes, access]
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

  // Focus moves into the palette on open and back to where it was on close (Esc, a
  // click outside, or a choice that leaves the page as it was), when that element is
  // still in the document.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => {
      if (opener && opener !== document.body && opener.isConnected && typeof opener.focus === "function") {
        opener.focus({ preventScroll: true });
      }
    };
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
  // Esc closes the palette and nothing under it (an open record stays open), wherever
  // focus is inside it; the input's own Esc handling below consumes it first.
  useEscapeLayer(open, close);

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
      <div
        ref={boxRef}
        className="cmdk"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => trapTab(e, boxRef.current)}
      >
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
          role="combobox"
          aria-expanded={rows.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={rows[active] ? rowId(active) : undefined}
        />
        <div className="cmdk-list" ref={listRef} role="listbox" id={listId} aria-label="Results" tabIndex={-1}>
          {rows.length === 0 ? (
            <div className="cmdk-empty" role="presentation">{term.length < 2 ? "Type to search records…" : `No matches for “${q}”.`}</div>
          ) : (
            <>
              {filteredNav.length > 0 && <div className="cmdk-group" role="presentation">Navigate</div>}
              {filteredNav.map((r, i) => (
                <button
                  key={`nav-${r.href}`}
                  id={rowId(i)}
                  role="option"
                  aria-selected={active === i}
                  tabIndex={-1}
                  data-idx={i}
                  className={`cmdk-row${active === i ? " active" : ""}`}
                  onMouseMove={() => setActive(i)}
                  onClick={() => choose(r)}
                >
                  <span className="cmdk-row-title">{r.label}</span>
                  <span className="cmdk-row-sub">{r.section}</span>
                </button>
              ))}
              {hits.length > 0 && <div className="cmdk-group" role="presentation">Records</div>}
              {hits.map((hit, j) => {
                const idx = firstRecordIdx + j;
                return (
                  <button
                    key={`rec-${hit.type}-${hit.reference}-${j}`}
                    id={rowId(idx)}
                    role="option"
                    aria-selected={active === idx}
                    tabIndex={-1}
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
