"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearToken, type Me, type SearchHit } from "@/lib/api";
import { useMobileNav } from "@/lib/mobileNav";
import { IconBell, IconLogout } from "./icons";

const TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/goals": "Strategy & Goals",
  "/risks": "Risk Register",
  "/operational-risk": "Operational Risk",
  "/threat-library": "Threat & Vulnerability Library",
  "/assets": "Asset Management",
  "/vendors": "Third-Party Risk",
  "/assessments": "Vendor Assessments",
  "/questionnaires": "Questionnaires",
  "/compliance": "Compliance Management",
  "/aml": "AML / CFT",
  "/controls": "Control Catalog",
  "/evidence": "Evidence",
  "/internal-audit": "Internal Audit",
  "/shariah": "Shariah Governance",
  "/policies": "Policy Management",
  "/privacy": "Data Privacy (RoPA)",
  "/awareness": "Awareness Training",
  "/business-units": "Business Units",
  "/processes": "Business Processes",
  "/legal": "Legal Register",
  "/organization": "Organization",
  "/incidents": "Security Operations",
  "/continuity": "Business Continuity",
  "/access-reviews": "Access Reviews",
  "/approvals": "Approvals",
  "/exceptions": "Exceptions",
  "/projects": "Projects",
  "/audit": "Activity Log",
  "/notifications": "Notifications",
  "/custom-fields": "Custom Fields",
  "/reports": "Reports & KPIs",
  "/webhooks": "Webhooks",
  "/status-rules": "Dynamic Status Rules",
  "/filters": "Saved Filters",
  "/data-io": "Import & Export",
  "/sso-settings": "Single Sign-On",
  "/settings": "Settings",
};

function initials(name: string, email: string) {
  const src = (name || email || "?").trim();
  const parts = src.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return src.slice(0, 2).toUpperCase();
}

export default function Topbar({ user }: { user: Me | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const key = Object.keys(TITLES).find((k) => pathname.startsWith(k));
  const title = key ? TITLES[key] : "NexusLine";
  const [unseen, setUnseen] = useState(0);
  const { toggle: toggleMobileNav } = useMobileNav();

  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [open, setOpen] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.notifications().then((r) => setUnseen(r.unseen_count)).catch(() => {});
  }, [pathname]);

  // Debounced global search.
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setHits([]);
      return;
    }
    const t = setTimeout(() => {
      api.search(term).then((r) => { setHits(r.hits); setOpen(true); }).catch(() => setHits([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  // Close the dropdown on outside click.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (searchRef.current && !searchRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function go(hit: SearchHit) {
    setOpen(false);
    setQ("");
    router.push(hit.link);
  }

  function logout() {
    clearToken();
    router.push("/");
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <button
          type="button"
          className="mobile-menu-btn"
          onClick={toggleMobileNav}
          aria-label="Open navigation menu"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
        <div className="topbar-title">{title}</div>
      </div>
      <div className="topbar-right">
        <div ref={searchRef} style={{ position: "relative" }}>
          <input
            className="input sm"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onFocus={() => hits.length && setOpen(true)}
            placeholder="Search…"
            aria-label="Global search"
            style={{ width: 220, height: 32, paddingRight: 34 }}
          />
          <kbd className="topbar-kbd" title="Press ⌘K / Ctrl-K for the command palette">⌘K</kbd>
          {open && (
            <div
              className="card"
              style={{ position: "absolute", top: 38, right: 0, width: 340, maxHeight: 380, overflowY: "auto", zIndex: 50, boxShadow: "0 8px 28px rgba(0,0,0,0.14)" }}
            >
              {hits.length === 0 ? (
                <div className="card-pad muted" style={{ fontSize: 13 }}>No matches for “{q}”.</div>
              ) : (
                <div style={{ padding: 4 }}>
                  {hits.map((h, i) => (
                    <button
                      key={`${h.type}-${h.reference}-${i}`}
                      onClick={() => go(h)}
                      style={{ display: "block", width: "100%", textAlign: "left", border: "none", background: "none", cursor: "pointer", padding: "8px 10px", borderRadius: 6 }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--surface-2, #f3f4f6)")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
                    >
                      <div style={{ fontSize: 13.5, fontWeight: 600 }}>{h.title}</div>
                      <div className="muted" style={{ fontSize: 11.5 }}>{h.label}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
        <Link href="/notifications" className="btn secondary sm" aria-label="Notifications" title="Notifications" style={{ position: "relative" }}>
          <IconBell width={16} height={16} />
          {unseen > 0 && (
            <span style={{ position: "absolute", top: -6, right: -6, minWidth: 16, height: 16, padding: "0 4px", borderRadius: 999, background: "var(--red)", color: "#fff", fontSize: 10, fontWeight: 700, display: "grid", placeItems: "center" }}>
              {unseen}
            </span>
          )}
        </Link>
        {user && (
          <div className="userchip">
            <span className="avatar">{initials(user.full_name, user.email)}</span>
            <span className="meta">
              <b>{user.full_name || user.email.split("@")[0]}</b>
              <span>{user.roles.map((r) => r.name).join(", ") || "Member"}</span>
            </span>
          </div>
        )}
        <button className="btn secondary sm" onClick={logout} title="Sign out">
          <IconLogout width={16} height={16} />
          Sign out
        </button>
      </div>
    </header>
  );
}
