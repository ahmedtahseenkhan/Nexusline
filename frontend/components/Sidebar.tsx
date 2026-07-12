"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { routeDisabled, useModules } from "@/lib/modules";
import { useMobileNav } from "@/lib/mobileNav";
import { NAV, navItemByHref, navItemFor, type NavItem, type NavSection } from "@/lib/nav";
import { useNavPrefs } from "@/lib/navPrefs";
import { IconNexus } from "./icons";

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"
      style={{ marginLeft: "auto", flexShrink: 0, transition: "transform 0.16s ease", transform: open ? "rotate(180deg)" : "none" }}
      aria-hidden
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  );
}

export default function Sidebar() {
  const pathname = usePathname();
  const { disabledRoutes } = useModules();
  const { favorites, recents, isFavorite, toggleFavorite, recordVisit } = useNavPrefs();
  const { open, setOpen } = useMobileNav();

  const enabled = (href: string) => !routeDisabled(href, disabledRoutes);
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");

  // eramba-style accordion: groups collapsed by default; the group holding the
  // active route opens automatically; user toggles persist for the session.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  useEffect(() => {
    const owner = NAV.find((s) => s.items.some((it) => isActive(it.href)));
    if (owner) setExpanded((p) => (p[owner.title] ? p : { ...p, [owner.title]: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Remember the current module as recently-visited, close the mobile drawer on nav.
  useEffect(() => {
    const item = navItemFor(pathname);
    if (item) recordVisit(item.href);
    setOpen(false);
  }, [pathname, recordVisit, setOpen]);

  // Licensing: drop disabled links; groups that empty out disappear entirely.
  const nav = NAV.map((s) => ({ ...s, items: s.items.filter((it) => enabled(it.href)) })).filter(
    (s) => (s.href ? enabled(s.href) : s.items.length > 0),
  );

  const favItems = favorites.map(navItemByHref).filter((it): it is NavItem => !!it && enabled(it.href));
  const recentItems = recents
    .map(navItemByHref)
    .filter((it): it is NavItem => !!it && enabled(it.href) && !isFavorite(it.href))
    .slice(0, 4);

  function leaf(it: NavItem, sub = false) {
    const active = isActive(it.href);
    const fav = isFavorite(it.href);
    return (
      <div key={it.href} className="nav-item-wrap">
        <Link
          href={it.href}
          className={`nav-item${sub ? " sub" : ""}${active ? " active" : ""}`}
          aria-current={active ? "page" : undefined}
        >
          {!sub && it.icon}
          {it.label}
          {it.tag && <span className="nav-tag">{it.tag}</span>}
        </Link>
        <button
          type="button"
          className={`nav-star${fav ? " on" : ""}`}
          onClick={() => toggleFavorite(it.href)}
          aria-label={fav ? `Unpin ${it.label}` : `Pin ${it.label}`}
          title={fav ? "Unpin from favorites" : "Pin to favorites"}
        >
          {fav ? "★" : "☆"}
        </button>
      </div>
    );
  }

  function group(s: NavSection) {
    // Single-link groups (Dashboard, Shariah) render as a plain top-level item.
    if (s.href) {
      const active = isActive(s.href);
      return (
        <Link
          key={s.title}
          href={s.href}
          className={`nav-item${active ? " active" : ""}`}
          aria-current={active ? "page" : undefined}
        >
          {s.icon}
          {s.title}
        </Link>
      );
    }
    const isOpen = !!expanded[s.title];
    const holdsActive = s.items.some((it) => isActive(it.href));
    return (
      <div key={s.title}>
        <button
          type="button"
          className={`nav-item nav-group${holdsActive && !isOpen ? " active" : ""}`}
          onClick={() => setExpanded((p) => ({ ...p, [s.title]: !isOpen }))}
          aria-expanded={isOpen}
        >
          {s.icon}
          {s.title}
          <Chevron open={isOpen} />
        </button>
        {isOpen && <div className="nav-sub">{s.items.map((it) => leaf(it, true))}</div>}
      </div>
    );
  }

  return (
    <>
      {open && <div className="sidebar-scrim" onClick={() => setOpen(false)} aria-hidden />}
      <aside className={`sidebar${open ? " open" : ""}`}>
        <div className="sidebar-brand">
          <span className="logo">
            <IconNexus width={19} height={19} />
          </span>
          <span className="wordmark">Nexus<b>Line</b></span>
        </div>
        <nav className="nav">
          {favItems.length > 0 && (
            <div>
              <div className="nav-section">Favorites</div>
              {favItems.map((it) => leaf(it))}
            </div>
          )}
          {recentItems.length > 0 && (
            <div>
              <div className="nav-section">Recent</div>
              {recentItems.map((it) => leaf(it))}
            </div>
          )}
          <div className="nav-section">Modules</div>
          {nav.map(group)}
        </nav>
        <div className="sidebar-foot">NexusLine · Governance Intelligence · v1.0</div>
      </aside>
    </>
  );
}
