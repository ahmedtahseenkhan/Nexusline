"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

/* List filters that live in the URL, so a number elsewhere can open the list behind it.

   The dashboard's "98 controls never tested" links to `/controls?assurance=not_assessed`;
   the controls page declares its filters once and reads them from the query string:

     const CONTROL_FILTERS = {
       assurance: ["assured", "failing", "not_assessed"] as const,  // allowed values
       test: ["overdue", "due_30d", "failed"] as const,
       key: "boolean",
       owner_id: "string",
     } as const satisfies FilterSpec;

     const filters = useFilterParams(CONTROL_FILTERS);
     filters.values.assurance        // "not_assessed" | … | undefined (typed per page)
     filters.set("test", "overdue")  // updates the list and the URL, no reload
     <DataTable filters={filters.values} onApplyFilters={filters.replace} … />

   - The initial values come from the URL; a value outside the declared list is ignored,
     so a stale or hand-typed link never sends the API something it would refuse.
   - Changing a filter rewrites the query string with `history.replaceState` (no reload,
     no new history entry; Next.js keeps `useSearchParams` in step), leaving every other
     parameter — the open record's `?id=` — as it was. The address bar is therefore always
     a shareable link to exactly what is on screen.
   - Arriving again with different parameters (a sidebar or dashboard link to the page
     you are on, Back/Forward) re-reads them.
   - Declare the spec at module level: it is read on every render.
   Pages using it sit inside a <Suspense> boundary, as `useSearchParams` requires. */

export type FilterKind = "string" | "boolean" | readonly string[];
export type FilterSpec = Record<string, FilterKind>;
export type FilterValues<S extends FilterSpec> = {
  [K in keyof S]?: S[K] extends "boolean"
    ? boolean
    : S[K] extends readonly (infer U)[]
      ? U
      : string;
};

type Readable = { get(name: string): string | null };

/** Read the declared filters from a query string. Pure. */
export function parseFilters<S extends FilterSpec>(spec: S, params: Readable): FilterValues<S> {
  const out: Record<string, string | boolean> = {};
  for (const [key, kind] of Object.entries(spec)) {
    const raw = params.get(key);
    if (raw === null || raw === "") continue;
    if (kind === "boolean") {
      if (raw === "true" || raw === "false") out[key] = raw === "true";
    } else if (typeof kind !== "string") {
      if (kind.includes(raw)) out[key] = raw;
    } else {
      out[key] = raw;
    }
  }
  return out as FilterValues<S>;
}

/** The query string with the declared filters set to `values` (others kept). Pure. */
export function withFilters<S extends FilterSpec>(spec: S, search: string, values: FilterValues<S>): string {
  const params = new URLSearchParams(search);
  for (const key of Object.keys(spec)) {
    const v = (values as Record<string, unknown>)[key];
    if (v === undefined || v === null || v === "") params.delete(key);
    else params.set(key, String(v));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

function same(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) if ((a[k] ?? undefined) !== (b[k] ?? undefined)) return false;
  return true;
}

export type FilterParams<S extends FilterSpec> = {
  /** Current values, ready to pass as DataTable `filters`. */
  values: FilterValues<S>;
  /** Set one filter (undefined / "" clears it). */
  set: <K extends keyof S & string>(key: K, value: FilterValues<S>[K] | undefined) => void;
  /** Set several at once; keys not given are kept. */
  update: (patch: FilterValues<S>) => void;
  /** Replace them all (a saved view): keys not given are cleared, unknown keys ignored. */
  replace: (next: Record<string, string | number | boolean | undefined>) => void;
  clear: () => void;
  /** How many filters hold a value. */
  active: number;
};

export function useFilterParams<S extends FilterSpec>(spec: S): FilterParams<S> {
  const searchParams = useSearchParams();
  const qs = searchParams.toString();
  const [values, setValues] = useState<FilterValues<S>>(() => parseFilters(spec, searchParams));
  // The latest values, including a change made earlier in the same event (two quick
  // `set` calls must not undo each other before React re-renders).
  const current = useRef(values);
  current.current = values;

  // Arriving with different parameters (a link to this page, Back/Forward): re-read.
  useEffect(() => {
    const fromUrl = parseFilters(spec, new URLSearchParams(qs));
    if (!same(current.current as Record<string, unknown>, fromUrl as Record<string, unknown>)) {
      current.current = fromUrl;
      setValues(fromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qs]);

  const commit = useCallback(
    (next: FilterValues<S>) => {
      current.current = next;
      setValues(next);
      if (typeof window === "undefined") return;
      const search = withFilters(spec, window.location.search, next);
      if (search !== window.location.search) {
        window.history.replaceState(null, "", `${window.location.pathname}${search}${window.location.hash}`);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const set = useCallback(
    <K extends keyof S & string>(key: K, value: FilterValues<S>[K] | undefined) =>
      commit({ ...current.current, [key]: value === "" ? undefined : value } as FilterValues<S>),
    [commit],
  );
  const update = useCallback(
    (patch: FilterValues<S>) => commit({ ...current.current, ...patch } as FilterValues<S>),
    [commit],
  );
  const replace = useCallback(
    (next: Record<string, string | number | boolean | undefined>) => {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(next ?? {})) if (v !== undefined && v !== "" && k in spec) params.set(k, String(v));
      commit(parseFilters(spec, params));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [commit],
  );
  const clear = useCallback(() => commit({} as FilterValues<S>), [commit]);
  const active = useMemo(
    () => Object.values(values as Record<string, unknown>).filter((v) => v !== undefined && v !== "").length,
    [values],
  );

  return { values, set, update, replace, clear, active };
}
