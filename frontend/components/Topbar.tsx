"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api, clearToken, type Me } from "@/lib/api";
import { IconBell, IconLogout } from "./icons";

const TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/goals": "Strategy & Goals",
  "/risks": "Risk Register",
  "/threat-library": "Threat & Vulnerability Library",
  "/assets": "Asset Management",
  "/vendors": "Third-Party Risk",
  "/assessments": "Vendor Assessments",
  "/questionnaires": "Questionnaires",
  "/compliance": "Compliance Management",
  "/controls": "Control Catalog",
  "/evidence": "Evidence",
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

  useEffect(() => {
    api.notifications().then((r) => setUnseen(r.unseen_count)).catch(() => {});
  }, [pathname]);

  function logout() {
    clearToken();
    router.push("/");
  }

  return (
    <header className="topbar">
      <div className="topbar-title">{title}</div>
      <div className="topbar-right">
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
