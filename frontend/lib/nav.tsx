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

/** Who may see a link. A user without the permission never sees it — in the sidebar,
 *  favourites, recents or the command palette. This is presentation, not security: the
 *  API behind each page refuses the call regardless. Each code is the permission the
 *  page's main API requires (its list endpoint's `require(...)` on the server). */
export type NavGate = {
  /** The one permission the page needs, e.g. "risk:read". */
  permission?: string;
  /** Any one of these is enough (a page serving several kinds of editor). */
  anyPermission?: string[];
  /** Shown only to deployment operators (`is_platform_admin`). Module licensing gates
   *  what an installation *bought*; this gates what an installation's *operator* runs,
   *  which is a different axis and cannot be expressed as a permission code — those are
   *  tenant-scoped rows an org admin can grant themselves. */
  platformAdminOnly?: boolean;
};

export type NavItem = NavGate & {
  href: string;
  label: string;
  icon: ReactNode;
  tag?: string;
};
/** A top-level nav group (eramba-style): either a single link (`href` set, no items)
 *  or a collapsible group whose `items` expand on click. A group none of whose items
 *  the user may open disappears. */
export type NavSection = NavGate & { title: string; icon: ReactNode; href?: string; items: NavItem[] };

/** Canonical module registry — single source of truth for the sidebar and the command
 *  palette. Modeled on eramba's nav: ~a dozen top-level groups, modules as submenus,
 *  instead of 57 always-visible links. Entries are filtered per installation by module
 *  licensing (see `routeDisabled` / `useModules`) and per user by `permission`.
 *  A new page adds one line here, with the permission its main API requires. */
export const NAV: NavSection[] = [
  { title: "My work", icon: <IconCheck />, href: "/my-work", items: [] },
  { title: "Dashboard", icon: <IconDashboard />, href: "/dashboard", items: [], permission: "risk:read" },
  {
    title: "Program",
    icon: <IconGauge />,
    items: [
      { href: "/reports", label: "Reports & KPIs", icon: <IconActivity />, permission: "report:read" },
      { href: "/report-builder", label: "Report Builder", icon: <IconCompliance />, permission: "report:read" },
      { href: "/goals", label: "Strategy & Goals", icon: <IconGauge />, permission: "goal:read" },
      { href: "/projects", label: "Projects", icon: <IconLayers />, permission: "project:read" },
      { href: "/approvals", label: "Approvals", icon: <IconCheck />, permission: "workflow:read" },
      { href: "/ai-assist", label: "AI Assist", icon: <IconActivity />, tag: "AI", permission: "ai:read" },
    ],
  },
  {
    // Renamed from "Organization" so Policy Management sits visibly under governance,
    // as the client asked. The group already held Board & Committees, Delegation of
    // Authority and the Legal Register — the governance structures that decide who owns
    // what and who may approve what — so the label now matches the contents.
    title: "Governance",
    icon: <IconUsers />,
    items: [
      { href: "/business-units", label: "Business Units", icon: <IconLayers />, permission: "org:read" },
      { href: "/processes", label: "Processes", icon: <IconActivity />, permission: "org:read" },
      { href: "/legal", label: "Legal Register", icon: <IconPolicy />, permission: "org:read" },
      { href: "/governance", label: "Board & Committees", icon: <IconUsers />, permission: "governance:read" },
      { href: "/policies", label: "Policy Management", icon: <IconPolicy />, permission: "policy:read" },
      { href: "/delegation-of-authority", label: "Delegation of Authority", icon: <IconUsers />, permission: "authority:read" },
      { href: "/organization", label: "Users & Roles", icon: <IconUsers />, anyPermission: ["user:read", "role:read"] },
    ],
  },
  {
    title: "Asset Management",
    icon: <IconAsset />,
    items: [
      { href: "/information-assets", label: "Information Assets", icon: <IconLayers />, permission: "asset:read" },
      { href: "/it-assets", label: "IT Assets", icon: <IconAsset />, permission: "asset:read" },
      { href: "/privacy", label: "Data Privacy (RoPA)", icon: <IconCompliance />, permission: "privacy:read" },
      { href: "/data-protection", label: "Data Protection", icon: <IconShield />, permission: "dpo:read" },
    ],
  },
  {
    title: "Risk Management",
    icon: <IconRisk />,
    items: [
      { href: "/risks", label: "Risk Register", icon: <IconRisk />, permission: "risk:read" },
      { href: "/risk-proposals", label: "Risk candidates", icon: <IconRisk />, permission: "risk:read" },
      { href: "/operational-risk", label: "Operational Risk", icon: <IconGauge />, permission: "oprisk:read" },
      { href: "/scenario-analysis", label: "Scenario & Capital", icon: <IconGauge />, permission: "scenario:read" },
      { href: "/model-risk", label: "Model Risk", icon: <IconGauge />, permission: "modelrisk:read" },
      { href: "/risk-quantification", label: "Risk Quantification", icon: <IconGauge />, permission: "riskquant:read" },
      { href: "/threat-library", label: "Threat Library", icon: <IconAlert />, permission: "risk:read" },
      { href: "/exceptions", label: "Risk Exceptions", icon: <IconAlert />, permission: "exception:read" },
    ],
  },
  {
    title: "Third-Party Risk",
    icon: <IconVendor />,
    items: [
      { href: "/vendors", label: "Third Parties", icon: <IconVendor />, permission: "vendor:read" },
      { href: "/outsourcing", label: "Outsourcing & Cloud", icon: <IconVendor />, permission: "outsourcing:read" },
      { href: "/assessments", label: "Vendor Assessments", icon: <IconCompliance />, permission: "assessment:read" },
      { href: "/questionnaires", label: "Questionnaires", icon: <IconPolicy />, permission: "assessment:read" },
    ],
  },
  {
    title: "Controls & Assurance",
    icon: <IconControl />,
    items: [
      { href: "/controls", label: "Control Catalog", icon: <IconControl />, permission: "control:read" },
      { href: "/evidence", label: "Evidence", icon: <IconEvidence />, permission: "control:read" },
      { href: "/awareness", label: "Awareness Training", icon: <IconUsers />, permission: "awareness:read" },
      { href: "/internal-audit", label: "Internal Audit", icon: <IconCheck />, permission: "internal_audit:read" },
    ],
  },
  {
    title: "Compliance",
    icon: <IconCompliance />,
    items: [
      { href: "/compliance", label: "Compliance Management", icon: <IconCompliance />, permission: "compliance:read" },
      { href: "/content-library", label: "Framework Library", icon: <IconCompliance />, permission: "compliance:read" },
      { href: "/regulatory-change", label: "Regulatory Change", icon: <IconCompliance />, permission: "regchange:read" },
      { href: "/icfr", label: "ICFR", icon: <IconCheck />, permission: "icfr:read" },
      { href: "/declarations", label: "Declarations", icon: <IconPolicy />, permission: "declaration:read" },
      { href: "/esg", label: "ESG / Green Banking", icon: <IconGauge />, permission: "esg:read" },
    ],
  },
  {
    title: "Financial Crime",
    icon: <IconShield />,
    items: [
      { href: "/aml", label: "AML / CFT", icon: <IconShield />, permission: "aml:read" },
      { href: "/fraud", label: "Fraud Risk", icon: <IconAlert />, permission: "fraud:read" },
      { href: "/whistleblowing", label: "Whistleblowing", icon: <IconAlert />, permission: "whistle:read" },
    ],
  },
  { title: "Shariah Governance", icon: <IconShield />, href: "/shariah", items: [], permission: "shariah:read" },
  {
    title: "Security Operations",
    icon: <IconShield />,
    items: [
      { href: "/incidents", label: "Incidents", icon: <IconShield />, permission: "incident:read" },
      { href: "/vulnerabilities", label: "Vulnerabilities", icon: <IconAlert />, permission: "vuln:read" },
      { href: "/continuity", label: "Business Continuity", icon: <IconShield />, permission: "bcp:read" },
      { href: "/bia", label: "Business Impact Analysis", icon: <IconShield />, permission: "bia:read" },
      { href: "/access-reviews", label: "Access Reviews", icon: <IconUsers />, permission: "review:read" },
      { href: "/issues", label: "Issues & Actions", icon: <IconAlert />, permission: "issue:read" },
    ],
  },
  {
    title: "Settings",
    icon: <IconSettings />,
    items: [
      // Everyone: the page carries each person's own sign-in security (two-factor set-up).
      { href: "/settings", label: "General Settings", icon: <IconSettings /> },
      { href: "/organisation-settings", label: "Organisation Settings", icon: <IconGauge />, permission: "settings:manage" },
      { href: "/integrations", label: "Integrations & CCM", icon: <IconActivity />, permission: "ccm:read" },
      { href: "/custom-fields", label: "Custom Fields", icon: <IconLayers />, permission: "customfield:manage" },
      // Governed lists are org:write; asset and third-party lists their own module's write.
      { href: "/lookups", label: "Lookups & Dropdowns", icon: <IconLayers />, anyPermission: ["org:write", "asset:write", "vendor:write"] },
      { href: "/status-rules", label: "Status Rules", icon: <IconGauge />, permission: "automation:manage" },
      { href: "/sla-policies", label: "Turnaround Time (TAT)", icon: <IconAlert />, permission: "risk:read" },
      { href: "/workflows", label: "Approval Workflows", icon: <IconCheck />, permission: "workflow:read" },
      // Everyone: saved filters are personal, and import/export checks each register's
      // own permission per resource.
      { href: "/filters", label: "Saved Filters", icon: <IconCompliance /> },
      { href: "/data-io", label: "Import / Export", icon: <IconActivity /> },
      { href: "/webhooks", label: "Webhooks", icon: <IconActivity />, permission: "integration:manage" },
      { href: "/sso-settings", label: "Single Sign-On", icon: <IconShield />, permission: "sso:manage" },
      { href: "/audit", label: "Activity Log", icon: <IconActivity />, permission: "audit:read" },
      {
        href: "/organizations",
        label: "Organisations",
        icon: <IconShield />,
        platformAdminOnly: true,
      },
    ],
  },
];

/* ------------------------------------------------------------------ access --- */
/** What the signed-in user may see: their permission codes and the operator flag. */
export type NavAccess = { permissions: readonly string[]; platformAdmin: boolean };

/** May this user open the link? (Presentation only — the API enforces.) */
export function canOpen(gate: NavGate, access: NavAccess): boolean {
  if (gate.platformAdminOnly && !access.platformAdmin) return false;
  if (gate.permission && !access.permissions.includes(gate.permission)) return false;
  if (gate.anyPermission?.length && !gate.anyPermission.some((p) => access.permissions.includes(p))) return false;
  return true;
}

/** The nav this user sees: links they may open (and, via `enabled`, that the
 *  installation licenses); a group left with nothing to open disappears. */
export function visibleNav(access: NavAccess, enabled: (href: string) => boolean = () => true): NavSection[] {
  return NAV.map((s) => ({ ...s, items: s.items.filter((it) => enabled(it.href) && canOpen(it, access)) })).filter((s) =>
    s.href ? enabled(s.href) && canOpen(s, access) : s.items.length > 0,
  );
}

/** Every navigable link: group-level single links + all submenu items. */
export function allNavItems(): NavItem[] {
  const out: NavItem[] = [];
  for (const s of NAV) {
    if (s.href)
      out.push({ href: s.href, label: s.title, icon: s.icon, permission: s.permission, anyPermission: s.anyPermission, platformAdminOnly: s.platformAdminOnly });
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

/* ------------------------------------------------------------- role presets --- */
/** Which groups open by default depends on the kind of work the user does — the three
 *  lines of defence, plus the board. The user's own open/close choices (remembered per
 *  user in navPrefs) win over the preset, and favourites and recents stay on top. */
export type NavPreset = "first_line" | "second_line" | "audit" | "board";

export const PRESET_LABEL: Record<NavPreset, string> = {
  first_line: "First line — my work and my registers",
  second_line: "Second line — risk, controls and compliance",
  audit: "Internal audit",
  board: "Board and viewers — dashboard and reports",
};

/* The mapping, in order (first match wins):
     1. Role names. "audit" → audit. "first line", "1st line", "champion", "owner",
        "business", "branch" or "operations" → first line (a *risk champion* in a branch
        is first line, whatever else the name says). "admin", "risk", "compliance",
        "grc", "second line", "2nd line", "ciso", "cro" or "cco" → second line.
        "board", "viewer", "director", "executive", "read only" → board.
     2. Otherwise permissions. No write permission at all → board. Internal-audit write
        without any second-line permission → audit. Any of risk:write, risk:accept,
        compliance:write, control:write → second line. Anything else → first line. */
const ROLE_RULES: [RegExp, NavPreset][] = [
  [/audit/i, "audit"],
  [/first[\s-]?line|1st[\s-]?line|champion|\bowner\b|business|branch|operations/i, "first_line"],
  [/admin|\brisk\b|compliance|\bgrc\b|second[\s-]?line|2nd[\s-]?line|\bciso\b|\bcro\b|\bcco\b/i, "second_line"],
  [/board|viewer|director|executive|read[\s-]?only/i, "board"],
];
const SECOND_LINE_PERMISSIONS = ["risk:write", "risk:accept", "compliance:write", "control:write"];

export function navPreset(roles: readonly string[], permissions: readonly string[]): NavPreset {
  for (const [pattern, preset] of ROLE_RULES) if (roles.some((r) => pattern.test(r))) return preset;
  const writes = permissions.filter((p) => !p.endsWith(":read"));
  if (writes.length === 0) return "board";
  const secondLine = SECOND_LINE_PERMISSIONS.some((p) => permissions.includes(p));
  if (permissions.includes("internal_audit:write") && !secondLine) return "audit";
  return secondLine ? "second_line" : "first_line";
}

const PRESET_GROUPS: Record<Exclude<NavPreset, "first_line">, string[]> = {
  second_line: ["Risk Management", "Controls & Assurance", "Compliance"],
  audit: ["Controls & Assurance"],
  board: ["Program"],
};

/** Group titles the preset opens. First line opens the groups holding a register the
 *  user can edit (a link whose `x:read` they hold alongside `x:write`) and any group
 *  holding My Work; the others are fixed. Only groups in `nav` (what the user sees). */
export function presetGroups(preset: NavPreset, nav: NavSection[], permissions: readonly string[]): Set<string> {
  const titles = new Set(nav.filter((s) => !s.href).map((s) => s.title));
  if (preset !== "first_line") return new Set(PRESET_GROUPS[preset].filter((t) => titles.has(t)));
  const out = new Set<string>();
  for (const s of nav) {
    if (s.href) continue;
    const editable = s.items.some((it) => {
      if (it.href === "/my-work") return true;
      const read = it.permission;
      return !!read && read.endsWith(":read") && permissions.includes(read.replace(/:read$/, ":write"));
    });
    if (editable) out.add(s.title);
  }
  return out;
}
