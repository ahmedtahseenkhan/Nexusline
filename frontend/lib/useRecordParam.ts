"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

/**
 * Read/write a record id in the URL query (`?<key>=<id>`), so an open record is
 * deep-linkable, shareable, and works with the browser Back button. Replaces the
 * app's old pattern of holding the selected record in `useState` (which died on
 * refresh and made Back exit the whole module).
 */
export function useRecordParam(key = "id"): [string | null, (id: string | null) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const current = params.get(key);

  const setId = useCallback(
    (id: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (id) next.set(key, id);
      else next.delete(key);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, params, key],
  );

  return [current, setId];
}
