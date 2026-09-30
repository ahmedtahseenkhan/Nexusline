"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import CommandPalette from "@/components/CommandPalette";
import TatReminder from "@/components/TatReminder";
import { api, getToken, type LicenceBanner, type Me, type ModuleState, type SystemStatus } from "@/lib/api";
import { ModulesProvider, buildModulesContext, moduleForRoute, routeDisabled } from "@/lib/modules";
import { FeedbackHost } from "@/lib/feedback";
import { TenantSettingsProvider } from "@/lib/tenantSettings";
import { useFormat } from "@/lib/format";
import { landingPath, markLanded, needsLanding, rememberNext, safeNext, takeNext } from "@/lib/landing";
import { useSessionKeepAlive } from "@/lib/sessionKeepAlive";
import { loadGovernanceStatus, type GovernanceStatus } from "@/components/SegregationOfDutiesSettings";

function ModuleLocked({ module: mod }: { module?: ModuleState }) {
  return (
    <div className="card" style={{ maxWidth: 560, margin: "48px auto", textAlign: "center" }}>
      <div className="card-pad" style={{ padding: "40px 32px" }}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>🔒</div>
        <h2 style={{ marginBottom: 8 }}>{mod ? mod.title : "Module"} is not enabled</h2>
        <p className="muted" style={{ fontSize: 14, lineHeight: 1.6 }}>
          This module is not included in your installation&apos;s license
          {mod?.licensed && mod.disabled_by_config ? " configuration" : ""}. Contact your
          administrator or vendor to enable it.
        </p>
      </div>
    </div>
  );
}

const MFA_BANNER_KEY = "nexusline_mfa_banner_dismissed";

/** Persistent, slim: an evaluation build must never be mistaken for a production one. */
function EvaluationBanner() {
  return (
    <div
      role="status"
      style={{ background: "var(--amber-bg)", color: "var(--amber)", borderBottom: "1px solid #f0d9ae", padding: "5px 16px", fontSize: 12.5, fontWeight: 600, textAlign: "center" }}
    >
      Unlicensed evaluation build — not for production use
    </div>
  );
}

/** Licence lifecycle (decision 1). Administrators see the expiry countdown from 60 days
 *  before, the grace period and the seat warning; everyone sees read-only mode. Not
 *  dismissible: each is something to act on. */
function LicenceBannerBar({ banner, isAdmin }: { banner: LicenceBanner; isAdmin: boolean }) {
  const critical = banner.tone === "critical";
  return (
    <div
      role={critical ? "alert" : "status"}
      style={{
        background: critical ? "var(--red-bg, #fdecec)" : "var(--amber-bg)",
        color: critical ? "var(--red, #b42318)" : "var(--amber)",
        borderBottom: "1px solid var(--border)",
        padding: "6px 16px",
        fontSize: 13,
        fontWeight: 600,
        textAlign: "center",
      }}
    >
      {banner.message}{" "}
      {isAdmin && (
        <Link href="/settings#system" style={{ fontWeight: 700, color: "inherit", textDecoration: "underline" }}>
          {banner.state === "seats" ? "Licence details" : "Install a renewed licence"}
        </Link>
      )}
      {!isAdmin && banner.state === "read_only" && " Contact your administrator."}
    </div>
  );
}

/** Dismissible reminder while the MFA grace period runs. Dismissal is remembered per
 *  deadline in this browser only; the policy itself is enforced by the server. */
function MfaDueBanner({ due }: { due: string }) {
  const { formatDate } = useFormat();
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem(MFA_BANNER_KEY) === due;
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  function dismiss() {
    try {
      window.localStorage.setItem(MFA_BANNER_KEY, due);
    } catch {
      /* storage unavailable: dismiss for this page view only */
    }
    setHidden(true);
  }
  return (
    <div
      role="status"
      style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "center", flexWrap: "wrap", background: "var(--primary-weak)", color: "var(--primary-text)", borderBottom: "1px solid var(--border)", padding: "6px 16px", fontSize: 13 }}
    >
      <span>
        Two-factor authentication is required for your account from {formatDate(due)}.{" "}
        <Link href="/settings" style={{ fontWeight: 600 }}>Set it up now</Link>
      </span>
      <button type="button" className="btn secondary sm" onClick={dismiss} aria-label="Dismiss two-factor reminder">
        Dismiss
      </button>
    </div>
  );
}

/** Administrators only, persistent: maker-checker cannot work with one active user, and a
 *  route stage whose role nobody holds falls back to any approver. Both are open points
 *  until fixed, so they are not dismissible. */
function GovernanceBanner() {
  const [status, setStatus] = useState<GovernanceStatus | null>(null);
  const [checked, setChecked] = useState(false);
  const pathname = usePathname();
  const open = !!status && (status.needs_second_user || status.role_gaps.length > 0);
  useEffect(() => {
    // Check once; while something is open, re-check on navigation so the banner clears
    // as soon as a user is invited or a role assigned.
    if (checked && !open) return;
    setChecked(true);
    loadGovernanceStatus().then(setStatus).catch(() => setStatus(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);
  if (!open || !status) return null;
  const style = { background: "var(--amber-bg)", color: "var(--amber)", borderBottom: "1px solid #f0d9ae", padding: "6px 16px", fontSize: 13, textAlign: "center" as const };
  return (
    <div role="status" style={style}>
      {status.needs_second_user ? (
        <>
          Segregation of duties needs at least two users — nothing you submit can be approved yet.{" "}
          <Link href="/organization" style={{ fontWeight: 600 }}>Invite a user</Link>
        </>
      ) : (
        <>
          {status.role_gaps.length === 1
            ? `No one holds the ${status.role_gaps[0].role} role that approval routes use — assign it in Users.`
            : `No one holds the ${status.role_gaps.map((g) => g.role).join(" or ")} roles that approval routes use — assign them in Users.`}{" "}
          <Link href="/organisation-settings#segregation-of-duties" style={{ fontWeight: 600 }}>Details</Link>
        </>
      )}
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<Me | null>(null);
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [ready, setReady] = useState(false);
  // The server could not be reached (restarting, a proxy 502, the network): not a
  // signed-out session, so the page waits and retries instead of dropping to sign-in.
  const [unreachable, setUnreachable] = useState(false);
  const [attempt, setAttempt] = useState(0);
  // Renew the session while it is in use, so nobody is signed out mid-entry.
  useSessionKeepAlive(ready);
  // The landing page this session is being sent to; the shell waits on "Loading…" until
  // it is there, so the page the user was redirected away from never flashes.
  const [landingTo, setLandingTo] = useState<string | null>(null);

  useEffect(() => {
    if (landingTo && pathname === landingTo) setLandingTo(null);
  }, [pathname, landingTo]);

  useEffect(() => {
    if (!getToken()) {
      // Signed out: keep the page asked for (an e-mailed alert's link) for after sign-in.
      const here = `${window.location.pathname}${window.location.search}`;
      const next = safeNext(here);
      if (next) rememberNext(next);
      router.replace(next ? `/?next=${encodeURIComponent(next)}` : "/");
      return;
    }
    Promise.all([
      api.me(),
      // Fail open: on error the sidebar shows everything and the API still enforces.
      api.systemModules().catch(() => [] as ModuleState[]),
    ])
      .then(async ([u, mods]) => {
        if (u.mfa_enrolment_required) {
          // Grace period over: this session can only enrol in MFA.
          router.replace("/mfa-setup");
          return;
        }
        // First page of a new session that didn't come through the login form (SSO and
        // two-factor enrolment return to /dashboard): open the remembered deep link, or
        // this user's landing page — My Work unless they administer the organisation.
        if (needsLanding()) {
          markLanded();
          const here = window.location.pathname;
          const target = takeNext() ?? (here === "/dashboard" ? await landingPath(u) : null);
          if (target && target !== `${here}${window.location.search}`) {
            setLandingTo(target.split("?")[0]);
            router.replace(target);
          }
        }
        setUser(u);
        setModules(mods);
        setReady(true);
        api.systemStatus().then(setStatus).catch(() => setStatus(null));
      })
      .catch(() => {
        // Only a lapsed session (a 401, which clears the token) is a reason to sign in
        // again. Anything else — the API restarting during a deploy, a 502 from the
        // proxy — used to sign people out mid-entry; wait and try again instead.
        if (!getToken()) {
          router.replace("/");
          return;
        }
        setUnreachable(true);
        window.setTimeout(() => setAttempt((n) => n + 1), 5000);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  const ctx = useMemo(() => buildModulesContext(modules), [modules]);

  if (!ready && unreachable) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 16 }}>
        <div style={{ textAlign: "center", maxWidth: 420 }}>
          <p style={{ fontWeight: 600, margin: "0 0 6px" }}>Can&apos;t reach the server</p>
          <p className="muted" style={{ fontSize: 13.5, margin: "0 0 14px" }}>
            You are still signed in. Trying again every few seconds — this usually clears once
            the server finishes restarting.
          </p>
          <button type="button" className="btn secondary" onClick={() => setAttempt((n) => n + 1)}>Try now</button>
        </div>
      </div>
    );
  }
  if (!ready || (landingTo && pathname !== landingTo)) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <span className="muted">Loading…</span>
      </div>
    );
  }

  const locked = routeDisabled(pathname, ctx.disabledRoutes);

  return (
    <ModulesProvider value={ctx}>
      {/* Organisation currency / timezone / date format for every page (lib/format.ts). */}
      <TenantSettingsProvider permissions={user?.permission_codes}>
      <div className="app-shell">
        <Sidebar />
        <div className="main">
          <Topbar user={user} />
          {status?.evaluation_build && <EvaluationBanner />}
          {status?.licence_banner && (
            <LicenceBannerBar
              banner={status.licence_banner}
              isAdmin={!!user?.permission_codes?.some((c) => c === "settings:manage" || c === "role:write")}
            />
          )}
          {user?.mfa_enrolment_due && !user.mfa_enabled && <MfaDueBanner due={user.mfa_enrolment_due} />}
          {user?.permission_codes?.includes("settings:manage") && <GovernanceBanner />}
          <main className="content">
            {locked ? <ModuleLocked module={moduleForRoute(pathname, modules)} /> : children}
          </main>
        </div>
      </div>
      <CommandPalette />
      {/* Surfaces breached turnaround times once per day, wherever the user lands. */}
      <TatReminder />
      <FeedbackHost />
      </TenantSettingsProvider>
    </ModulesProvider>
  );
}
