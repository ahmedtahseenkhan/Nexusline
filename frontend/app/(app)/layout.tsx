"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import CommandPalette from "@/components/CommandPalette";
import TatReminder from "@/components/TatReminder";
import { api, getToken, type Me, type ModuleState, type SystemStatus } from "@/lib/api";
import { ModulesProvider, buildModulesContext, moduleForRoute, routeDisabled } from "@/lib/modules";
import { FeedbackHost } from "@/lib/feedback";
import { TenantSettingsProvider } from "@/lib/tenantSettings";
import { useFormat } from "@/lib/format";

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
        Two-factor authentication is required for your role from {formatDate(due)}.{" "}
        <Link href="/settings" style={{ fontWeight: 600 }}>Set it up now</Link>
      </span>
      <button type="button" className="btn secondary sm" onClick={dismiss} aria-label="Dismiss two-factor reminder">
        Dismiss
      </button>
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

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    Promise.all([
      api.me(),
      // Fail open: on error the sidebar shows everything and the API still enforces.
      api.systemModules().catch(() => [] as ModuleState[]),
    ])
      .then(([u, mods]) => {
        if (u.mfa_enrolment_required) {
          // Grace period over: this session can only enrol in MFA.
          router.replace("/mfa-setup");
          return;
        }
        setUser(u);
        setModules(mods);
        setReady(true);
        api.systemStatus().then(setStatus).catch(() => setStatus(null));
      })
      .catch(() => {
        router.replace("/");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const ctx = useMemo(() => buildModulesContext(modules), [modules]);

  if (!ready) {
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
          {user?.mfa_enrolment_due && !user.mfa_enabled && <MfaDueBanner due={user.mfa_enrolment_due} />}
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
