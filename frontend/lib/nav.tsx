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
/** A top-level nav group (eramba-style): either a single link (`href` set, no items)
 *  or a collapsible group whose `items` expand on click. */
export type NavSection = { title: string; icon: ReactNode; href?: string; items: NavItem[] };

/** Canonical module registry — single source of truth for the sidebar and the command
 *  palette. Modeled on eramba's nav: ~a dozen top-level groups, modules as submenus,
 *  instead of 57 always-visible links. Entries are filtered per installation by module
 *  licensing (see `routeDisabled` / `useModules`). */
export const NAV: NavSection[] = [
  { title: "Dashboard", icon: <IconDashboard />, href: "/dashboard", items: [] },
  {
    title: "Program",
    icon: <IconGauge />,
    items: [
      { href: "/reports", label: "Reports & KPIs", icon: <IconActivity /> },
      { href: "/goals", label: "Strategy & Goals", icon: <IconGauge /> },
      { href: "/projects", label: "Projects", icon: <IconLayers /> },
      { href: "/approvals", label: "Approvals", icon: <IconCheck /> },
      { href: "/ai-assist", label: "AI Assist", icon: <IconActivity />, tag: "AI" },
    ],
  },
  {
    title: "Organization",
    icon: <IconUsers />,
    items: [
      { href: "/business-units", label: "Business Units", icon: <IconLayers /> },
      { href: "/processes", label: "Processes", icon: <IconActivity /> },
      { href: "/legal", label: "Legal Register", icon: <IconPolicy /> },
      { href: "/governance", label: "Board & Committees", icon: <IconUsers /> },
      { href: "/delegation-of-authority", label: "Delegation of Authority", icon: <IconUsers /> },
      { href: "/organization", label: "Users & Roles", icon: <IconUsers /> },
    ],
  },
  {
    title: "Asset Management",
    icon: <IconAsset />,
    items: [
      { href: "/information-assets", label: "Information Assets", icon: <IconLayers /> },
      { href: "/it-assets", label: "IT Assets", icon: <IconAsset /> },
      { href: "/privacy", label: "Data Privacy (RoPA)", icon: <IconCompliance /> },
      { href: "/data-protection", label: "Data Protection", icon: <IconShield /> },
    ],
  },
  {
    title: "Risk Management",
    icon: <IconRisk />,
    items: [
      { href: "/risks", label: "Risk Register", icon: <IconRisk /> },
      { href: "/operational-risk", label: "Operational Risk", icon: <IconGauge /> },
      { href: "/scenario-analysis", label: "Scenario & Capital", icon: <IconGauge /> },
      { href: "/model-risk", label: "Model Risk", icon: <IconGauge /> },
      { href: "/risk-quantification", label: "Risk Quantification", icon: <IconGauge /> },
      { href: "/threat-library", label: "Threat Library", icon: <IconAlert /> },
      { href: "/exceptions", label: "Risk Exceptions", icon: <IconAlert /> },
    ],
  },
  {
    title: "Third-Party Risk",
    icon: <IconVendor />,
    items: [
      { href: "/vendors", label: "Third Parties", icon: <IconVendor /> },
      { href: "/outsourcing", label: "Outsourcing & Cloud", icon: <IconVendor /> },
      { href: "/assessments", label: "Vendor Assessments", icon: <IconCompliance /> },
      { href: "/questionnaires", label: "Questionnaires", icon: <IconPolicy /> },
    ],
  },
  {
    title: "Controls & Assurance",
    icon: <IconControl />,
    items: [
      { href: "/controls", label: "Control Catalog", icon: <IconControl /> },
      { href: "/evidence", label: "Evidence", icon: <IconEvidence /> },
      { href: "/policies", label: "Policy Management", icon: <IconPolicy /> },
      { href: "/awareness", label: "Awareness Training", icon: <IconUsers /> },
      { href: "/internal-audit", label: "Internal Audit", icon: <IconCheck /> },
    ],
  },
  {
    title: "Compliance",
    icon: <IconCompliance />,
    items: [
      { href: "/compliance", label: "Compliance Management", icon: <IconCompliance /> },
      { href: "/content-library", label: "Framework Library", icon: <IconCompliance /> },
      { href: "/regulatory-change", label: "Regulatory Change", icon: <IconCompliance /> },
      { href: "/icfr", label: "ICFR", icon: <IconCheck /> },
      { href: "/declarations", label: "Declarations", icon: <IconPolicy /> },
      { href: "/esg", label: "ESG / Green Banking", icon: <IconGauge /> },
    ],
  },
  {
    title: "Financial Crime",
    icon: <IconShield />,
    items: [
      { href: "/aml", label: "AML / CFT", icon: <IconShield /> },
      { href: "/fraud", label: "Fraud Risk", icon: <IconAlert /> },
      { href: "/whistleblowing", label: "Whistleblowing", icon: <IconAlert /> },
    ],
  },
  { title: "Shariah Governance", icon: <IconShield />, href: "/shariah", items: [] },
  {
    title: "Security Operations",
    icon: <IconShield />,
    items: [
      { href: "/incidents", label: "Incidents", icon: <IconShield /> },
      { href: "/vulnerabilities", label: "Vulnerabilities", icon: <IconAlert /> },
      { href: "/continuity", label: "Business Continuity", icon: <IconShield /> },
      { href: "/bia", label: "Business Impact Analysis", icon: <IconShield /> },
      { href: "/access-reviews", label: "Access Reviews", icon: <IconUsers /> },
      { href: "/issues", label: "Issues & Actions", icon: <IconAlert /> },
    ],
  },
  {
    title: "Settings",
    icon: <IconSettings />,
    items: [
      { href: "/settings", label: "General Settings", icon: <IconSettings /> },
      { href: "/integrations", label: "Integrations & CCM", icon: <IconActivity /> },
      { href: "/custom-fields", label: "Custom Fields", icon: <IconLayers /> },
      { href: "/status-rules", label: "Status Rules", icon: <IconGauge /> },
      { href: "/filters", label: "Saved Filters", icon: <IconCompliance /> },
      { href: "/data-io", label: "Import / Export", icon: <IconActivity /> },
      { href: "/webhooks", label: "Webhooks", icon: <IconActivity /> },
      { href: "/sso-settings", label: "Single Sign-On", icon: <IconShield /> },
      { href: "/audit", label: "Activity Log", icon: <IconActivity /> },
    ],
  },
];

/** Every navigable link: group-level single links + all submenu items. */
export function allNavItems(): NavItem[] {
  const out: NavItem[] = [];
  for (const s of NAV) {
    if (s.href) out.push({ href: s.href, label: s.title, icon: s.icon });
    out.push(...s.items);
  }
  return out;
}

/** The nav item that owns a given pathname (longest matching href wins), so
 *  favorites/recents can resolve a route to its label + icon. */
export function navItemFor(pathname: string): NavItem | null {
  let best: NavItem | null = null;
  for (const it of allNavItems()) {
    if (pathname === it.href || pathname.startsWith(it.href + "/")) {
      if (!best || it.href.length > best.href.length) best = it;
    }
  }
  return best;
}

export function navItemByHref(href: string): NavItem | null {
  for (const it of allNavItems()) if (it.href === href) return it;
  return null;
}
