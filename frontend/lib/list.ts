"use client";

import { useEffect, useRef, useState } from "react";

/** Standard server list envelope. */
export type Page<T> = { items: T[]; total: number; limit: number; offset: number };

/** Params a server-driven table sends. `extra` carries page-specific filters. */
export type ListQuery = {
  limit: number;
  offset: number;
  sort_by?: string | null;
  sort_dir?: "asc" | "desc";
  q?: string;
  extra?: Record<string, string | number | boolean | undefined>;
};

/** Build a `?a=b&c=d` string from a ListQuery, dropping empty values. */
export function toQueryString(qy: ListQuery): string {
  const p = new URLSearchParams();
  p.set("limit", String(qy.limit));
  p.set("offset", String(qy.offset));
  if (qy.q) p.set("search", qy.q);
  if (qy.sort_by) {
    p.set("sort_by", qy.sort_by);
    p.set("sort_dir", qy.sort_dir || "asc");
  }
  for (const [k, v] of Object.entries(qy.extra || {})) {
    if (v !== undefined && v !== "" && v !== false) p.set(k, String(v));
  }
  return p.toString();
}

/** Debounce a fast-changing value (e.g. a search box) so we don't fire a request per keystroke. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

/** Latest-only ref so an in-flight fetch that resolves after a newer one is discarded. */
export function useLatest() {
  const seq = useRef(0);
  return {
    next: () => ++seq.current,
    isCurrent: (n: number) => n === seq.current,
  };
}
