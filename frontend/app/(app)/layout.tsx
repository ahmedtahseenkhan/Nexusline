"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import CommandPalette from "@/components/CommandPalette";
import { api, getToken, type Me, type ModuleState } from "@/lib/api";
import { ModulesProvider, buildModulesContext, moduleForRoute, routeDisabled } from "@/lib/modules";
import { FeedbackHost } from "@/lib/feedback";

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

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<Me | null>(null);
  const [modules, setModules] = useState<ModuleState[]>([]);
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
        setUser(u);
        setModules(mods);
        setReady(true);
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
      <div className="app-shell">
        <Sidebar />
        <div className="main">
          <Topbar user={user} />
          <main className="content">
            {locked ? <ModuleLocked module={moduleForRoute(pathname, modules)} /> : children}
          </main>
        </div>
      </div>
      <CommandPalette />
      <FeedbackHost />
    </ModulesProvider>
  );
}
