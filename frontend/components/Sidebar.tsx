"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { routeDisabled, useModules } from "@/lib/modules";
import { useMobileNav } from "@/lib/mobileNav";
import { NAV, navItemByHref, navItemFor, type NavItem } from "@/lib/nav";
import { useNavPrefs } from "@/lib/navPrefs";
import { IconNexus } from "./icons";

export default function Sidebar() {
  const pathname = usePathname();
  const { disabledRoutes } = useModules();
  const { favorites, recents, isFavorite, toggleFavorite, recordVisit } = useNavPrefs();
  const { open, setOpen } = useMobileNav();

  // Remember the current module as recently-visited (top-level nav item only),
  // and close the off-canvas drawer whenever navigation lands on a new route.
  useEffect(() => {
    const item = navItemFor(pathname);
    if (item) recordVisit(item.href);
    setOpen(false);
  }, [pathname, recordVisit, setOpen]);

  const enabled = (href: string) => !routeDisabled(href, disabledRoutes);

  // Hide nav entries this installation hasn't licensed; empty sections disappear.
  const nav = NAV.map((section) => ({
    ...section,
    items: section.items.filter((it) => enabled(it.href)),
  })).filter((section) => section.items.length > 0);

  const favItems = favorites.map(navItemByHref).filter((it): it is NavItem => !!it && enabled(it.href));
  const recentItems = recents
    .map(navItemByHref)
    .filter((it): it is NavItem => !!it && enabled(it.href) && !isFavorite(it.href))
    .slice(0, 5);

  function renderItem(it: NavItem) {
    const active = pathname === it.href || pathname.startsWith(it.href + "/");
    const fav = isFavorite(it.href);
    return (
      <div key={it.href} className="nav-item-wrap">
        <Link
          href={it.href}
          className={`nav-item${active ? " active" : ""}`}
          aria-current={active ? "page" : undefined}
        >
          {it.icon}
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
            {favItems.map(renderItem)}
          </div>
        )}
        {recentItems.length > 0 && (
          <div>
            <div className="nav-section">Recent</div>
            {recentItems.map(renderItem)}
          </div>
        )}
        {nav.map((section) => (
          <div key={section.title}>
            <div className="nav-section">{section.title}</div>
            {section.items.map(renderItem)}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">NexusLine · Governance Intelligence · v1.0</div>
      </aside>
    </>
  );
}
