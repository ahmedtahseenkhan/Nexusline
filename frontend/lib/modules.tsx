"use client";

/**
 * Per-installation module entitlements, mirrored from GET /system/modules.
 * The sidebar hides nav entries and the app layout blocks direct URLs for
 * modules the installation hasn't licensed/enabled; the API enforces the same
 * server-side, so this is presentation, not security. Fails open (everything
 * visible) if the endpoint is unreachable — the backend still rejects calls.
 */
import { createContext, useContext } from "react";
import type { ModuleState } from "@/lib/api";

type ModulesContextValue = {
  modules: ModuleState[];
  /** Frontend route prefixes belonging to disabled modules. */
  disabledRoutes: string[];
};

const ModulesContext = createContext<ModulesContextValue>({ modules: [], disabledRoutes: [] });

export function buildModulesContext(modules: ModuleState[]): ModulesContextValue {
  return {
    modules,
    disabledRoutes: modules.filter((m) => !m.enabled).flatMap((m) => m.routes),
  };
}

export const ModulesProvider = ModulesContext.Provider;

export function useModules(): ModulesContextValue {
  return useContext(ModulesContext);
}

export function routeDisabled(pathname: string, disabledRoutes: string[]): boolean {
  return disabledRoutes.some((r) => pathname === r || pathname.startsWith(r + "/"));
}

/** The disabled module owning a pathname, for the lock screen. */
export function moduleForRoute(pathname: string, modules: ModuleState[]): ModuleState | undefined {
  return modules.find((m) => m.routes.some((r) => pathname === r || pathname.startsWith(r + "/")));
}
