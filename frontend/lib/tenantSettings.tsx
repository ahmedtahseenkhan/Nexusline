"use client";

/* The organisation's settings (currency, timezone, date format …) for every page.

   `TenantSettingsProvider` is mounted once in the signed-in app layout. It loads
   `GET /settings/organisation` once after login and hands the result to:
     - `useTenantSettings()` — settings + loading/error + reload + the user's permissions;
     - `useFormat()` (lib/format.ts) — date/money formatters bound to the settings;
     - the plain `formatDate` / `formatDateTime` / `formatMoney`, via `setFormatSettings`.
   Until the load finishes, and if it fails, everything uses DEFAULT_TENANT_SETTINGS
   (PKR, Asia/Karachi, DD/MM/YYYY), so nothing on screen waits for it. */

import { useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  DEFAULT_TENANT_SETTINGS,
  TenantSettingsContext,
  setFormatSettings,
  type TenantSettings,
  type TenantSettingsState,
} from "@/lib/format";
import { getOrganisationSettings } from "@/lib/masterData";

/**
 * Loads the organisation settings and provides them to the tree.
 *
 * @param permissions the signed-in user's permission codes (`Me.permission_codes`), so
 *   components can ask `useHasPermission("org:write")` without another `/auth/me` call.
 */
export function TenantSettingsProvider({
  children,
  permissions,
}: {
  children: ReactNode;
  permissions?: string[];
}) {
  const [settings, setSettings] = useState<TenantSettings>(DEFAULT_TENANT_SETTINGS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const s = { ...DEFAULT_TENANT_SETTINGS, ...(await getOrganisationSettings()) };
      setFormatSettings(s);
      setSettings(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load organisation settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const value = useMemo<TenantSettingsState>(
    () => ({ settings, loading, error, reload, permissions: permissions ?? [] }),
    [settings, loading, error, reload, permissions],
  );
  return <TenantSettingsContext.Provider value={value}>{children}</TenantSettingsContext.Provider>;
}

/** `{settings, loading, error, reload, permissions}` — see `TenantSettingsState`. */
export function useTenantSettings(): TenantSettingsState {
  return useContext(TenantSettingsContext);
}

/** Whether the signed-in user holds a permission code (UI hint only; the API enforces). */
export function useHasPermission(code: string): boolean {
  return useContext(TenantSettingsContext).permissions.includes(code);
}
