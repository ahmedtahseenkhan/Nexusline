"use client";

/* The sticky section nav at the top of the dossier main scroller (record-page-spec §3.3.6).

     <SectionNav />          // after <OpenPoints>, before the first <RecordSection>

   One link per registered RecordSection, with its count. A scroll-spy (one
   IntersectionObserver plus a passive scroll listener on the nearest scrolling
   ancestor, recomputed on resize because the scroller is `.drawer-main` when wide and
   `.drawer-columns` when stacked) sets `aria-current` on the section being read — the
   last one whose top has passed the sticky nav. At ≤1100px, when the drawer
   has a rail, it appends "Sign-off & trail" (→ #rec-rail). Hidden when fewer than
   3 sections are registered. */

import { useEffect, useRef } from "react";
import { useRecordSections } from "@/components/record/RecordSection";
import { useMediaQuery } from "@/components/record/useMediaQuery";

type SectionNavProps = { extra?: { id: string; label: string }[] };

function scrollParent(el: HTMLElement | null): HTMLElement | null {
  let node = el?.parentElement ?? null;
  while (node && node !== document.body) {
    const oy = getComputedStyle(node).overflowY;
    if (oy === "auto" || oy === "scroll") return node;
    node = node.parentElement;
  }
  return null;
}

export default function SectionNav({ extra }: SectionNavProps) {
  const { items, activeId, scrollTo, setActiveId, hasRail, spyLocked } = useRecordSections();
  const stacked = useMediaQuery("(max-width: 1100px)");
  const navRef = useRef<HTMLElement>(null);

  const links: { id: string; label: string; count?: number | null }[] = [
    ...items.map((i) => ({ id: i.id, label: i.title, count: i.count })),
    ...(extra ?? []),
    ...(stacked && hasRail ? [{ id: "rec-rail", label: "Sign-off & trail" }] : []),
  ];
  const ids = links.map((l) => l.id).join("|");
  const visibleNav = items.length >= 3;

  useEffect(() => {
    if (!visibleNav || typeof window === "undefined") return;
    const order = ids.split("|");
    let root: HTMLElement | null = null;
    let observer: IntersectionObserver | null = null;
    let frame = 0;

    // The section being read is the last one whose top has passed the line 48px below
    // the scroller's top (just under the sticky nav); at the very bottom, the last one
    // that is on screen. Geometry, not intersection flags, so short sections and
    // edge-adjacent sections resolve correctly.
    function compute() {
      frame = 0;
      if (spyLocked()) return;
      const box = root ? root.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
      const line = box.top + 49;
      let active: string | null = null;
      let lastOnScreen: string | null = null;
      for (const id of order) {
        const el = document.getElementById(id);
        if (!el) continue;
        const top = el.getBoundingClientRect().top;
        if (top <= line) active = id;
        if (top < box.bottom) lastOnScreen = id;
      }
      const atBottom = root ? root.scrollTop + root.clientHeight >= root.scrollHeight - 2 : false;
      if (atBottom && lastOnScreen) active = lastOnScreen;
      setActiveId(active);
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(compute);
    };

    function setup() {
      observer?.disconnect();
      root?.removeEventListener("scroll", schedule);
      root = scrollParent(navRef.current);
      observer = new IntersectionObserver(schedule, { root, rootMargin: "-48px 0px -60% 0px", threshold: [0, 1] });
      order.forEach((id) => {
        const el = document.getElementById(id);
        if (el) observer?.observe(el);
      });
      root?.addEventListener("scroll", schedule, { passive: true });
      schedule();
    }

    setup();
    window.addEventListener("resize", setup);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      observer?.disconnect();
      root?.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", setup);
    };
  }, [ids, visibleNav, setActiveId, spyLocked]);

  if (!visibleNav) return null;

  return (
    <nav className="rec-nav" aria-label="Record sections" ref={navRef}>
      {links.map((l) => (
        <a
          key={l.id}
          href={`#${l.id}`}
          aria-current={activeId === l.id ? "true" : undefined}
          onClick={(e) => {
            e.preventDefault();
            scrollTo(l.id);
          }}
        >
          {l.label}
          {l.count !== null && l.count !== undefined && <span className="n">{l.count}</span>}
        </a>
      ))}
    </nav>
  );
}

export { SectionNav };
