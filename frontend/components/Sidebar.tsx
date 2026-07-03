"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import {
  IconActivity,
  IconAlert,
  IconAsset,
  IconCheck,
  IconCompliance,
  IconControl,
  IconDashboard,
  IconEvidence,
  IconGauge,
  IconLayers,
  IconNexus,
  IconPolicy,
  IconRisk,
  IconSettings,
  IconShield,
  IconUsers,
  IconVendor,
} from "./icons";

type Item = { href: string; label: string; icon: ReactNode; tag?: string };
type Section = { title: string; items: Item[] };

const NAV: Section[] = [
  {
    title: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: <IconDashboard /> },
      { href: "/reports", label: "Reports & KPIs", icon: <IconActivity /> },
      { href: "/goals", label: "Strategy & Goals", icon: <IconGauge /> },
    ],
  },
  {
    title: "Risk",
    items: [
      { href: "/risks", label: "Risk Register", icon: <IconRisk /> },
      { href: "/operational-risk", label: "Operational Risk", icon: <IconGauge /> },
      { href: "/threat-library", label: "Threat Library", icon: <IconAlert /> },
      { href: "/assets", label: "Asset Management", icon: <IconAsset /> },
      { href: "/vendors", label: "Third Parties", icon: <IconVendor /> },
      { href: "/assessments", label: "Vendor Assessments", icon: <IconCompliance /> },
      { href: "/questionnaires", label: "Questionnaires", icon: <IconPolicy /> },
    ],
  },
  {
    title: "Compliance",
    items: [
      { href: "/compliance", label: "Compliance", icon: <IconCompliance /> },
      { href: "/aml", label: "AML / CFT", icon: <IconShield /> },
      { href: "/controls", label: "Control Catalog", icon: <IconControl /> },
      { href: "/evidence", label: "Evidence", icon: <IconEvidence /> },
      { href: "/internal-audit", label: "Internal Audit", icon: <IconCheck /> },
      { href: "/shariah", label: "Shariah Governance", icon: <IconShield /> },
    ],
  },
  {
    title: "Governance",
    items: [
      { href: "/policies", label: "Policy Management", icon: <IconPolicy /> },
      { href: "/privacy", label: "Data Privacy (RoPA)", icon: <IconCompliance /> },
      { href: "/awareness", label: "Awareness Training", icon: <IconUsers /> },
    ],
  },
  {
    title: "Organization",
    items: [
      { href: "/business-units", label: "Business Units", icon: <IconLayers /> },
      { href: "/processes", label: "Processes", icon: <IconActivity /> },
      { href: "/legal", label: "Legal Register", icon: <IconPolicy /> },
      { href: "/organization", label: "Users & Roles", icon: <IconUsers /> },
    ],
  },
  {
    title: "Operations",
    items: [
      { href: "/incidents", label: "Security Operations", icon: <IconShield /> },
      { href: "/continuity", label: "Business Continuity", icon: <IconShield /> },
      { href: "/access-reviews", label: "Access Reviews", icon: <IconUsers /> },
      { href: "/approvals", label: "Approvals", icon: <IconCheck /> },
      { href: "/exceptions", label: "Exceptions", icon: <IconAlert /> },
      { href: "/projects", label: "Projects", icon: <IconLayers /> },
      { href: "/audit", label: "Activity Log", icon: <IconActivity /> },
    ],
  },
  {
    title: "System",
    items: [
      { href: "/custom-fields", label: "Custom Fields", icon: <IconLayers /> },
      { href: "/status-rules", label: "Status Rules", icon: <IconGauge /> },
      { href: "/filters", label: "Saved Filters", icon: <IconCompliance /> },
      { href: "/data-io", label: "Import / Export", icon: <IconActivity /> },
      { href: "/webhooks", label: "Webhooks", icon: <IconActivity /> },
      { href: "/sso-settings", label: "SSO", icon: <IconShield /> },
      { href: "/settings", label: "Settings", icon: <IconSettings /> },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <span className="logo">
          <IconNexus width={19} height={19} />
        </span>
        <span className="wordmark">Nexus<b>Line</b></span>
      </div>
      <nav className="nav">
        {NAV.map((section) => (
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
