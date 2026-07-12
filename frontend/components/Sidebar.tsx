"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { routeDisabled, useModules } from "@/lib/modules";
import { NAV } from "@/lib/nav";
import { IconNexus } from "./icons";

export default function Sidebar() {
  const pathname = usePathname();
  const { disabledRoutes } = useModules();
  // Hide nav entries for modules this installation hasn't licensed/enabled;
  // sections that empty out disappear entirely.
  const nav = NAV.map((section) => ({
    ...section,
    items: section.items.filter((it) => !routeDisabled(it.href, disabledRoutes)),
  })).filter((section) => section.items.length > 0);
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="logo">
          <IconNexus width={19} height={19} />
        </span>
        <span className="wordmark">Nexus<b>Line</b></span>
      </div>
      <nav className="nav">
        {nav.map((section) => (
          <div key={section.title}>
            <div className="nav-section">{section.title}</div>
            {section.items.map((it) => {
              const active = pathname === it.href || pathname.startsWith(it.href + "/");
              return (
                <Link
                  key={it.href}
                  href={it.href}
                  className={`nav-item${active ? " active" : ""}`}
                  aria-current={active ? "page" : undefined}
                >
                  {it.icon}
                  {it.label}
                  {it.tag && <span className="nav-tag">{it.tag}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="sidebar-foot">NexusLine · Governance Intelligence · v1.0</div>
    </aside>
  );
}
