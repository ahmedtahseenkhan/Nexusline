"use client";

/* Where a signed-in user lands, and getting them back to a deep link after sign-in.

   After sign-in, a user lands on their workspace (GET /my/workspace): first line on My
   Work, second line on the dashboard, internal audit on Assurance, board members on the
   board home, administrators on the dashboard — or on the start page they chose in
   Settings. An administrator who may change organisation settings goes to first-run
   setup (/onboarding) while the organisation hasn't finished it.

   A link opened while signed out (an e-mailed alert's "/risks?id=…") is remembered and
   opened after sign-in instead — through the password, two-factor and SSO flows alike.

   The login page decides the landing itself; the app layout applies it once per new
   session for the flows that come back through /dashboard (SSO, two-factor enrolment).
   A marker of the session (a hash of the token, never the token) records that the
   landing has happened, so opening the dashboard later — in this tab or another — is
   never redirected. */

import { apiCall, getToken, type Me } from "@/lib/api";

/** Holding any of these makes a user an administrator for landing purposes. */
export const ADMIN_PERMISSIONS = ["settings:manage", "user:write"] as const;

const LANDED_KEY = "nexusline_landed";
const NEXT_KEY = "nexusline_next";
/** A remembered deep link is dropped if sign-in doesn't follow within this time. */
const NEXT_TTL_MS = 30 * 60 * 1000;

export function isAdmin(me: Pick<Me, "permission_codes"> | null | undefined): boolean {
  const held = new Set(me?.permission_codes || []);
  return ADMIN_PERMISSIONS.some((p) => held.has(p));
}

/** A workspace the user may start on (GET /my/workspace). */
export type WorkspaceOption = { key: string; label: string; href: string; description: string };

/** Where a user starts, by line of defence (services/workspaces.py):
 *  first line → My Work, second line → dashboard, internal audit → Assurance,
 *  board → Board home, administrators → dashboard. Their own choice wins while they can
 *  still open it. */
export type Workspace = {
  line: "first_line" | "second_line" | "audit" | "board";
  is_admin: boolean;
  default: string;
  preference: string | null;
  landing: string;
  landing_href: string;
  available: WorkspaceOption[];
};

export function getWorkspace(): Promise<Workspace> {
  return apiCall<Workspace>("GET", "/my/workspace");
}

/** Choose a start page; null goes back to the default for the user's line of defence. */
export function setWorkspacePreference(workspace: string | null): Promise<Workspace> {
  return apiCall<Workspace>("PUT", "/my/workspace", { workspace });
}

/** The page a user should land on after signing in. */
export async function landingPath(me: Me): Promise<string> {
  if ((me.permission_codes || []).includes("settings:manage")) {
    try {
      const org = await apiCall<{ onboarding_completed_at?: string | null }>("GET", "/settings/organisation");
      // Only an explicit "not yet" sends someone to setup (an older server omits the field).
      if (org && "onboarding_completed_at" in org && !org.onboarding_completed_at) return "/onboarding";
    } catch {
      /* settings unreadable: fall through to the workspace */
    }
  }
  try {
    return (await getWorkspace()).landing_href || "/my-work";
  } catch {
    // An older server without workspaces: administrators to the dashboard, others to My Work.
    return isAdmin(me) ? "/dashboard" : "/my-work";
  }
}

/** A same-site path to go to after sign-in, or null (never an absolute or protocol-
 *  relative URL, and never the login page itself). */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw) return null;
  if (!raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return null;
  if (raw === "/" || raw.startsWith("/?") || raw.startsWith("/act")) return null;
  return raw;
}

function fingerprint(token: string | null): string {
  if (!token) return "";
  let h = 5381;
  for (let i = 0; i < token.length; i += 1) h = ((h << 5) + h + token.charCodeAt(i)) | 0;
  return `${token.length}.${(h >>> 0).toString(36)}`;
}

/** Record that this session has landed (so the layout doesn't redirect again). */
export function markLanded(): void {
  try {
    window.localStorage.setItem(LANDED_KEY, fingerprint(getToken()));
  } catch {
    /* storage unavailable: at worst the layout redirects the first /dashboard once */
  }
}

/** Whether this session hasn't been through its landing yet. */
export function needsLanding(): boolean {
  try {
    return window.localStorage.getItem(LANDED_KEY) !== fingerprint(getToken());
  } catch {
    return false;
  }
}

/** Remember a deep link to open after the next sign-in. */
export function rememberNext(path: string): void {
  const safe = safeNext(path);
  if (!safe) return;
  try {
    window.localStorage.setItem(NEXT_KEY, JSON.stringify({ path: safe, at: Date.now() }));
  } catch {
    /* storage unavailable: the ?next= parameter still carries it for password sign-in */
  }
}

/** The remembered deep link (once), if it is recent. */
export function takeNext(): string | null {
  try {
    const raw = window.localStorage.getItem(NEXT_KEY);
    window.localStorage.removeItem(NEXT_KEY);
    if (!raw) return null;
    const { path, at } = JSON.parse(raw) as { path?: string; at?: number };
    if (!at || Date.now() - at > NEXT_TTL_MS) return null;
    return safeNext(path);
  } catch {
    return null;
  }
}
