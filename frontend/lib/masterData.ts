/* Client for the phase-1 master data: governed lookup lists, the people / unit /
   process pickers and the organisation settings.

   The picker components (LookupSelect, UserPicker, BusinessUnitSelect, ProcessSelect)
   use these; a page only needs them directly for admin screens or to label ids in a
   list. Small lists are cached for the page's lifetime (one request per list per page
   load) and the cache is dropped whenever this client writes to them. */

import { apiCall, queryString } from "@/lib/api";
import type { TenantSettings } from "@/lib/format";

/* ---------------------------------------------------------------------- types -- */

/** A person as records reference them (`owner`, `assignee` … on read schemas). */
export type UserRef = { id: string; full_name: string; email: string };
/** A lookup value as records reference them (`category`, `regulator` …). */
export type LookupRef = { id: string; key: string; value: string; label: string };
/** A business unit or process as records reference them. */
export type UnitRef = { id: string; name: string };

/** One governed list (`GET /lookups`). */
export type LookupList = {
  key: string;
  name: string;
  /** Text already typed into the fields this list backs became values on upgrade. */
  seeded_from_text: boolean;
  total: number;
  active: number;
};

/** One value of a list (`GET /lookups/{key}`). */
export type LookupValue = LookupRef & {
  description: string;
  sort_order: number;
  active: boolean;
  parent_id: string | null;
  parent_label: string;
  /** "Parent › Child" for a child value, else the label. */
  path: string;
  depth: number;
  /** A shipped default: deleting it brings it back on restart — deactivate instead. */
  builtin: boolean;
  /** Records pointing at the value (only when asked for with `usage: true`). */
  usage: number | null;
};

export type LookupCreate = {
  label: string;
  value?: string;
  description?: string;
  sort_order?: number;
  active?: boolean;
  parent_id?: string | null;
};
export type LookupPatch = Partial<Pick<LookupValue, "label" | "description" | "sort_order" | "active" | "parent_id">>;

/** A pickable person (`GET /pickers/users`). */
export type UserPick = UserRef & { roles: string[]; is_active: boolean };
/** A business unit in the flattened tree (`GET /pickers/business-units`). */
export type UnitPick = UnitRef & { parent_id: string | null; depth: number; path: string };
/** A process (`GET /pickers/processes`). */
export type ProcessPick = UnitRef & { business_unit_id: string | null; business_unit_name: string };

export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

export type TenantSettingsOptions = {
  currencies: { code: string; name: string }[];
  date_formats: string[];
  timezones: string[];
  retention_min_days: number;
  retention_max_days: number;
};

/** Permission that manages lookup values (add / rename / deactivate / delete). */
export const LOOKUP_MANAGE_PERMISSION = "org:write";
/** Permission that changes the organisation settings. */
export const SETTINGS_MANAGE_PERMISSION = "settings:manage";

/* -------------------------------------------------------------------- lookups -- */

export function listLookupLists(): Promise<LookupList[]> {
  return apiCall<LookupList[]>("GET", "/lookups");
}

/** Values of a list. `active` defaults to "true" (what pickers want). */
export function lookupValues(
  key: string,
  opts: { active?: "true" | "false" | "all"; search?: string; usage?: boolean } = {},
): Promise<LookupValue[]> {
  return apiCall<LookupValue[]>(
    "GET",
    `/lookups/${encodeURIComponent(key)}${queryString({
      active: opts.active,
      search: opts.search?.trim() || undefined,
      usage: opts.usage ? "true" : undefined,
    })}`,
  );
}

export function lookupValue(key: string, id: string): Promise<LookupValue> {
  return apiCall<LookupValue>("GET", `/lookups/${encodeURIComponent(key)}/${id}`);
}

const lookupCache = new Map<string, Promise<LookupValue[]>>();

/** Every value of a list, active or not, cached for the page's lifetime — for labelling
 *  ids a record already holds. */
export function cachedLookupList(key: string): Promise<LookupValue[]> {
  let p = lookupCache.get(key);
  if (!p) {
    p = lookupValues(key, { active: "all" }).catch((e) => {
      lookupCache.delete(key);
      throw e;
    });
    lookupCache.set(key, p);
  }
  return p;
}

/** Drop the cached copy of one list (or all of them). */
export function invalidateLookupCache(key?: string): void {
  if (key) lookupCache.delete(key);
  else lookupCache.clear();
}

export async function createLookupValue(key: string, body: LookupCreate): Promise<LookupValue> {
  const row = await apiCall<LookupValue>("POST", `/lookups/${encodeURIComponent(key)}`, body);
  invalidateLookupCache(key);
  return row;
}

export async function updateLookupValue(key: string, id: string, patch: LookupPatch): Promise<LookupValue> {
  const row = await apiCall<LookupValue>("PATCH", `/lookups/${encodeURIComponent(key)}/${id}`, patch);
  invalidateLookupCache(key);
  return row;
}

/** Hard delete; the API answers 409 "In use by N records; deactivate it instead." */
export async function deleteLookupValue(key: string, id: string): Promise<void> {
  await apiCall<void>("DELETE", `/lookups/${encodeURIComponent(key)}/${id}`);
  invalidateLookupCache(key);
}

/** Set the display order from an ordered list of ids. */
export async function reorderLookupValues(key: string, ids: string[]): Promise<LookupValue[]> {
  const rows = await apiCall<LookupValue[]>("PUT", `/lookups/${encodeURIComponent(key)}/order`, { ids });
  invalidateLookupCache(key);
  return rows;
}

/* -------------------------------------------------------------------- pickers -- */

/** Active users matching `search` (name or email). Any signed-in user may call this. */
export function pickUsers(
  opts: { search?: string; role?: string; limit?: number; offset?: number } = {},
): Promise<Page<UserPick>> {
  return apiCall<Page<UserPick>>(
    "GET",
    `/pickers/users${queryString({
      search: opts.search?.trim() || undefined,
      role: opts.role || undefined,
      limit: opts.limit ? String(opts.limit) : undefined,
      offset: opts.offset ? String(opts.offset) : undefined,
    })}`,
  );
}

const userCache = new Map<string, Promise<UserPick | null>>();

/** Users by id, deactivated ones included (for labelling saved owners). Cached. */
export async function usersById(ids: string[]): Promise<Record<string, UserPick>> {
  const wanted = Array.from(new Set(ids.filter(Boolean)));
  const missing = wanted.filter((id) => !userCache.has(id));
  if (missing.length) {
    const batch = apiCall<Page<UserPick>>("GET", `/pickers/users?limit=50&ids=${missing.slice(0, 50).join(",")}`)
      .then((p) => p.items)
      .catch(() => [] as UserPick[]);
    for (const id of missing.slice(0, 50)) {
      userCache.set(id, batch.then((items) => items.find((u) => u.id === id) ?? null));
    }
  }
  const out: Record<string, UserPick> = {};
  await Promise.all(
    wanted.map(async (id) => {
      const u = await userCache.get(id);
      if (u) out[id] = u;
    }),
  );
  return out;
}

let unitCache: Promise<UnitPick[]> | null = null;

/** The whole business-unit tree, flattened depth-first. Cached. */
export function cachedBusinessUnits(): Promise<UnitPick[]> {
  if (!unitCache) {
    unitCache = apiCall<UnitPick[]>("GET", "/pickers/business-units").catch((e) => {
      unitCache = null;
      throw e;
    });
  }
  return unitCache;
}

/** Call after creating, renaming, moving or archiving a business unit. */
export function invalidateBusinessUnits(): void {
  unitCache = null;
}

/** Processes, optionally within one business unit. */
export function pickProcesses(
  opts: { businessUnitId?: string | null; search?: string; ids?: string[] } = {},
): Promise<ProcessPick[]> {
  return apiCall<ProcessPick[]>(
    "GET",
    `/pickers/processes${queryString({
      business_unit_id: opts.businessUnitId || undefined,
      search: opts.search?.trim() || undefined,
      ids: opts.ids?.length ? opts.ids.join(",") : undefined,
    })}`,
  );
}

/* ------------------------------------------------------------------- settings -- */

export function getOrganisationSettings(): Promise<TenantSettings> {
  return apiCall<TenantSettings>("GET", "/settings/organisation");
}

/** Partial update; requires `settings:manage`. */
export function updateOrganisationSettings(patch: Partial<TenantSettings>): Promise<TenantSettings> {
  return apiCall<TenantSettings>("PATCH", "/settings/organisation", patch);
}

export function organisationSettingsOptions(): Promise<TenantSettingsOptions> {
  return apiCall<TenantSettingsOptions>("GET", "/settings/organisation/options");
}
