"use client";

/* A section of the dossier main column (record-page-spec §3.3.5): a hairline rule, an
   h2 head with an optional count, context and 0–2 secondary actions, then the content.

     <RecordSection id="controls" title="Controls" count={controls.length}
       actions={<button className="btn secondary sm" onClick={() => openEdit(r, "links")}>Link controls</button>}
       empty={controls.length ? undefined : "No controls linked — nothing can reduce the residual."}>
       …table…
     </RecordSection>

   Sections register themselves (in document order) with the RecordSectionsProvider that
   RecordDrawer mounts in dossier, which feeds SectionNav and deep links
   (`?id=<uuid>#controls`). `useRecordSections().scrollTo(id)` scrolls to a section
   (no smooth scrolling), focuses its h2 and writes `#id` into the URL. Outside a
   provider `useRecordSections()` still works: `scrollTo` finds the section by id.

   `empty` (when set) renders the one-line empty state "Title · empty · actions" and
   ignores children; the h2 is kept so heading navigation lists every section. */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useIsoLayoutEffect } from "@/components/record/useIsoLayoutEffect";

export type RecordSectionItem = { id: string; title: string; count?: number | null };

export type RecordSectionsApi = {
  items: RecordSectionItem[];
  scrollTo(id: string): void;
  activeId: string | null;
  /** Set by SectionNav's scroll-spy. */
  setActiveId(id: string | null): void;
  /** The drawer has a rail (#rec-rail) the nav can link to when stacked. */
  hasRail: boolean;
  /** True for a moment after scrollTo / a deep link (the spy leaves the choice alone). */
  spyLocked(): boolean;
};

type Entry = RecordSectionItem & { el: HTMLElement | null };

type Registry = RecordSectionsApi & {
  register(e: Entry): void;
  unregister(id: string): void;
  /** True for a moment after scrollTo, so the scroll-spy does not override the click. */
  spyLocked(): boolean;
};

const SectionsContext = createContext<Registry | null>(null);

/** Scroll a record section (or `rec-rail`) into view, focus its heading and write `#id`. */
export function scrollToSection(id: string): void {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ block: "start" });
  const head = document.getElementById(`${id}-h`) as HTMLElement | null;
  const target = head ?? (el.hasAttribute("tabindex") ? el : null);
  target?.focus({ preventScroll: true });
  try {
    window.history.replaceState(null, "", `#${id}`);
  } catch {
    /* sandboxed or unsupported: the scroll already happened */
  }
}

function byDocumentOrder(a: Entry, b: Entry): number {
  if (!a.el || !b.el || a.el === b.el) return 0;
  return a.el.compareDocumentPosition(b.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

function sameItems(a: Entry[], b: Entry[]): boolean {
  return (
    a.length === b.length &&
    a.every((x, i) => x.id === b[i].id && x.title === b[i].title && x.count === b[i].count && x.el === b[i].el)
  );
}

/** Mounted by RecordDrawer in dossier. Holds the registered sections, the active one
 *  and performs the initial deep-link scroll (`location.hash`). */
export function RecordSectionsProvider({ children, hasRail = false }: { children: ReactNode; hasRail?: boolean }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const deepLinked = useRef(false);
  const lockUntil = useRef(0);
  const spyLocked = useCallback(() => Date.now() < lockUntil.current, []);

  const register = useCallback((e: Entry) => {
    setEntries((prev) => {
      const next = [...prev.filter((x) => x.id !== e.id), e].sort(byDocumentOrder);
      return sameItems(prev, next) ? prev : next;
    });
  }, []);
  const unregister = useCallback((id: string) => {
    setEntries((prev) => (prev.some((x) => x.id === id) ? prev.filter((x) => x.id !== id) : prev));
  }, []);

  const scrollTo = useCallback((id: string) => {
    lockUntil.current = Date.now() + 400;
    scrollToSection(id);
    setActiveId(id);
  }, []);

  // Deep link: scroll to `#section` once, as soon as that section has registered.
  useEffect(() => {
    if (deepLinked.current || typeof window === "undefined") return;
    const hash = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (!hash) {
      deepLinked.current = true;
      return;
    }
    const hit = entries.find((x) => x.id === hash);
    if (!hit && hash !== "rec-rail") return;
    deepLinked.current = true;
    requestAnimationFrame(() => {
      lockUntil.current = Date.now() + 400;
      document.getElementById(hash)?.scrollIntoView({ block: "start" });
      setActiveId(hash);
    });
  }, [entries]);

  const value = useMemo<Registry>(
    () => ({
      items: entries.map(({ id, title, count }) => ({ id, title, count })),
      scrollTo,
      activeId,
      setActiveId,
      hasRail,
      register,
      unregister,
      spyLocked,
    }),
    [entries, scrollTo, activeId, hasRail, register, unregister, spyLocked],
  );
  return <SectionsContext.Provider value={value}>{children}</SectionsContext.Provider>;
}

const NOOP = () => {};

/** The registered sections, the active one and `scrollTo`. Works outside a provider
 *  too (items empty; scrollTo still scrolls by id), so a page can call it at top level. */
export function useRecordSections(): RecordSectionsApi {
  const ctx = useContext(SectionsContext);
  return useMemo<RecordSectionsApi>(
    () =>
      ctx ?? { items: [], scrollTo: scrollToSection, activeId: null, setActiveId: NOOP, hasRail: false, spyLocked: () => false },
    [ctx],
  );
}

type RecordSectionProps = {
  /** Anchor, nav key and deep-link hash. */
  id: string;
  /** "Assessment" */
  title: string;
  /** Shown after the title and in the nav; null / undefined hides it. */
  count?: number | null;
  /** Muted context after the title: "Annually · next due 12 Oct 2026". */
  sub?: ReactNode;
  /** 0–2 secondary controls, right-aligned (never a filled .btn). */
  actions?: ReactNode;
  /** When set, renders the one-line empty state and ignores children. */
  empty?: ReactNode;
  children?: ReactNode;
};

export default function RecordSection({ id, title, count, sub, actions, empty, children }: RecordSectionProps) {
  const ctx = useContext(SectionsContext);
  const ref = useRef<HTMLElement>(null);
  const register = ctx?.register;
  const unregister = ctx?.unregister;

  useIsoLayoutEffect(() => {
    register?.({ id, title, count: count ?? null, el: ref.current });
  }, [register, id, title, count]);
  useIsoLayoutEffect(() => {
    if (!unregister) return;
    return () => unregister(id);
  }, [unregister, id]);

  const isEmpty = empty !== undefined && empty !== null && empty !== false;
  const headId = `${id}-h`;
  return (
    <section id={id} ref={ref} className={`rec-sec${isEmpty ? " is-empty" : ""}`} aria-labelledby={headId}>
      <div className="rec-sec-head">
        <h2 id={headId} tabIndex={-1}>
          {title}
          {count !== null && count !== undefined && <span className="n">{count}</span>}
        </h2>
        {sub && <span className="sub">{sub}</span>}
        {isEmpty && <span className="rec-empty">{empty}</span>}
        {actions && <div className="acts">{actions}</div>}
      </div>
      {!isEmpty && children}
    </section>
  );
}

export { RecordSection };
