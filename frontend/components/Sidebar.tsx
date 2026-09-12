"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { routeDisabled, useModules } from "@/lib/modules";
import { useMobileNav } from "@/lib/mobileNav";
import {
  PRESET_LABEL,
  canOpen,
  navItemByHref,
  navItemFor,
  navPreset,
  presetGroups,
  visibleNav,
  type NavAccess,
  type NavItem,
  type NavSection,
} from "@/lib/nav";
import { useNavPrefs, useNavUser } from "@/lib/navPrefs";
import { useTenantSettings } from "@/lib/tenantSettings";
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
  const { favorites, recents, groups, isFavorite, toggleFavorite, recordVisit, setGroupOpen, resetGroups } = useNavPrefs();
  const { open, setOpen } = useMobileNav();
  const me = useNavUser();

  // Links are filtered on the user's permission codes (the app shell loaded them with
  // /auth/me) and on module licensing; a group left empty disappears. Operator-only
  // links need is_platform_admin. Presentation, not security: the API refuses anyway.
  const { permissions: shellPermissions } = useTenantSettings();
  const access: NavAccess = useMemo(
    () => ({ permissions: shellPermissions.length ? shellPermissions : me?.permissions ?? [], platformAdmin: !!me?.platformAdmin }),
    [shellPermissions, me],
  );
  const enabled = (href: string) => !routeDisabled(href, disabledRoutes);
  const visible = (it: NavItem) => enabled(it.href) && canOpen(it, access);
  const isActive = (href: string) => pathname === href || pathname.startsWith(href + "/");
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const nav = useMemo(() => visibleNav(access, enabled), [access, disabledRoutes]);

  // Which groups are open: the one holding the page you are on (for this session),
  // else your own choice for that group (remembered per user), else your role preset.
  const preset = me ? navPreset(me.roles, access.permissions) : null;
  const presetOpen = useMemo(
    () => (preset ? presetGroups(preset, nav, access.permissions) : new Set<string>()),
    [preset, nav, access.permissions],
  );
  const [sessionOpen, setSessionOpen] = useState<Record<string, boolean>>({});
  useEffect(() => {
    const owner = nav.find((s) => s.items.some((it) => isActive(it.href)));
    if (owner) setSessionOpen((p) => (p[owner.title] ? p : { ...p, [owner.title]: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, nav]);
  const isOpen = (title: string) => sessionOpen[title] ?? groups[title] ?? presetOpen.has(title);
  function toggleGroup(title: string) {
    const next = !isOpen(title);
    setSessionOpen((p) => {
      const rest = { ...p };
      delete rest[title];
      return rest;
    });
    setGroupOpen(title, next);
  }
  const customised = Object.keys(groups).length > 0;

  // Remember the current module as recently-visited, close the mobile drawer on nav.
  useEffect(() => {
    const item = navItemFor(pathname);
    if (item) recordVisit(item.href);
    setOpen(false);
  }, [pathname, recordVisit, setOpen]);

  const favItems = favorites
    .map(navItemByHref)
    .filter((it): it is NavItem => !!it && visible(it));
  const recentItems = recents
    .map(navItemByHref)
    .filter((it): it is NavItem => !!it && visible(it) && !isFavorite(it.href))
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
    const expanded = isOpen(s.title);
    const holdsActive = s.items.some((it) => isActive(it.href));
    return (
      <div key={s.title}>
        <button
          type="button"
          className={`nav-item nav-group${holdsActive && !expanded ? " active" : ""}`}
          onClick={() => toggleGroup(s.title)}
          aria-expanded={expanded}
        >
          {s.icon}
          {s.title}
          <Chevron open={expanded} />
        </button>
        {expanded && <div className="nav-sub">{s.items.map((it) => leaf(it, true))}</div>}
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
          <div
            className="nav-section"
            style={{ display: "flex", alignItems: "center", gap: 6 }}
            title={preset ? `Groups open by default for your role: ${PRESET_LABEL[preset]}` : undefined}
          >
            Modules
            {customised && (
              <button
                type="button"
                className="linklike"
                style={{ marginLeft: "auto", fontSize: 10.5, textTransform: "none", letterSpacing: 0, color: "inherit", opacity: 0.75 }}
                onClick={() => { resetGroups(); setSessionOpen({}); }}
                title="Forget which groups you opened or closed; open the ones for your role"
              >
                Reset
              </button>
            )}
          </div>
          {nav.map(group)}
        </nav>
        <div className="sidebar-foot">NexusLine · Governance Intelligence · v1.0</div>
      </aside>
    </>
  );
}
