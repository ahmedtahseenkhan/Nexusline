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
  IconPolicy,
  IconRisk,
  IconSettings,
  IconShield,
  IconUsers,
  IconVendor,
} from "@/components/icons";

export type NavItem = { href: string; label: string; icon: ReactNode; tag?: string };
export type NavSection = { title: string; items: NavItem[] };

/** Flat href→item lookup, and the nav item that owns a given pathname (longest
 *  matching href wins), so favorites/recents can resolve a route to its label + icon. */
export function navItemFor(pathname: string): NavItem | null {
  let best: NavItem | null = null;
  for (const section of NAV) {
    for (const it of section.items) {
      if (pathname === it.href || pathname.startsWith(it.href + "/")) {
        if (!best || it.href.length > best.href.length) best = it;
      }
    }
  }
  return best;
}

export function navItemByHref(href: string): NavItem | null {
  for (const section of NAV) {
    for (const it of section.items) if (it.href === href) return it;
  }
  return null;
}

/** Canonical module registry — the single source of truth for the sidebar and the
 *  command palette. Entries are filtered per installation by module licensing
 *  (see `routeDisabled` / `useModules`). */
export const NAV: NavSection[] = [
  {
    title: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: <IconDashboard /> },
      { href: "/reports", label: "Reports & KPIs", icon: <IconActivity /> },
      { href: "/goals", label: "Strategy & Goals", icon: <IconGauge /> },
      { href: "/ai-assist", label: "AI Assist", icon: <IconActivity />, tag: "AI" },
    ],
  },
  {
    title: "Risk",
    items: [
      { href: "/risks", label: "Risk Register", icon: <IconRisk /> },
      { href: "/operational-risk", label: "Operational Risk", icon: <IconGauge /> },
      { href: "/scenario-analysis", label: "Scenario & Capital", icon: <IconGauge /> },
      { href: "/model-risk", label: "Model Risk", icon: <IconGauge /> },
      { href: "/threat-library", label: "Threat Library", icon: <IconAlert /> },
      { href: "/risk-quantification", label: "Risk Quantification", icon: <IconGauge /> },
      { href: "/it-assets", label: "IT Asset Management", icon: <IconAsset /> },
      { href: "/information-assets", label: "Information Assets", icon: <IconLayers /> },
      { href: "/vendors", label: "Third Parties", icon: <IconVendor /> },
      { href: "/outsourcing", label: "Outsourcing & Cloud", icon: <IconVendor /> },
      { href: "/assessments", label: "Vendor Assessments", icon: <IconCompliance /> },
      { href: "/questionnaires", label: "Questionnaires", icon: <IconPolicy /> },
    ],
  },
  {
    title: "Compliance",
    items: [
      { href: "/compliance", label: "Compliance", icon: <IconCompliance /> },
      { href: "/content-library", label: "Framework Library", icon: <IconCompliance /> },
      { href: "/regulatory-change", label: "Regulatory Change", icon: <IconCompliance /> },
      { href: "/icfr", label: "ICFR", icon: <IconCheck /> },
      { href: "/aml", label: "AML / CFT", icon: <IconShield /> },
      { href: "/fraud", label: "Fraud Risk", icon: <IconAlert /> },
      { href: "/controls", label: "Control Catalog", icon: <IconControl /> },
      { href: "/vulnerabilities", label: "Vulnerabilities", icon: <IconAlert /> },
      { href: "/evidence", label: "Evidence", icon: <IconEvidence /> },
      { href: "/internal-audit", label: "Internal Audit", icon: <IconCheck /> },
      { href: "/declarations", label: "Declarations", icon: <IconPolicy /> },
      { href: "/shariah", label: "Shariah Governance", icon: <IconShield /> },
    ],
  },
  {
    title: "Governance",
    items: [
      { href: "/policies", label: "Policy Management", icon: <IconPolicy /> },
      { href: "/privacy", label: "Data Privacy (RoPA)", icon: <IconCompliance /> },
      { href: "/data-protection", label: "Data Protection", icon: <IconShield /> },
      { href: "/awareness", label: "Awareness Training", icon: <IconUsers /> },
      { href: "/delegation-of-authority", label: "Delegation of Authority", icon: <IconUsers /> },
      { href: "/governance", label: "Board & Committees", icon: <IconUsers /> },
      { href: "/esg", label: "ESG / Green Banking", icon: <IconGauge /> },
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
      { href: "/bia", label: "Business Impact Analysis", icon: <IconShield /> },
      { href: "/issues", label: "Issues & Actions", icon: <IconAlert /> },
      { href: "/whistleblowing", label: "Whistleblowing", icon: <IconAlert /> },
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
      { href: "/integrations", label: "Integrations & CCM", icon: <IconActivity /> },
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
