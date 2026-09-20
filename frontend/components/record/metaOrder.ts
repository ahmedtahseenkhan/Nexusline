/* The header meta order (record-page-spec v1.1 decision 1): the type's own status first,
   "Record approval" SECOND, then the type's other items in the order the page gives.

     orderMeta({ status, approval, meta })   → MetaItem[]   (RecordHeader calls it)

   The approval item is found in this order: `identity.approval` (null = the type is
   outside the approval lifecycle, no item) → a `meta` item keyed "approval" or labelled
   "Record approval" → the item RecordHeader builds from the drawer's governance. The
   status item is `identity.status`, else the first `meta` item keyed "status" or
   "lifecycle". Wherever a page puts either item in `meta`, it renders in its slot, so
   no page can place approval anywhere else. With no status item the approval still
   renders second, after the first remaining item (and a dev warning asks for one).

   Pure: no React, so it can be unit-checked. */

import type { MetaItem, RecordIdentity } from "@/components/record/types";

/** Meta keys that mark the type's own business status ("Risk status", "Lifecycle"). */
export const STATUS_META_KEYS: readonly string[] = ["status", "lifecycle"];

/** The "Record approval" item, by key or by its fixed label. */
export function isApprovalMeta(m: MetaItem): boolean {
  return m.key === "approval" || m.label.trim().toLowerCase() === "record approval";
}

/** The type's own status item, by key. */
export function isStatusMeta(m: MetaItem): boolean {
  return STATUS_META_KEYS.includes(m.key);
}

export type OrderedMeta = {
  items: MetaItem[];
  /** False when no status item was found (the approval then follows the first item). */
  hasStatus: boolean;
};

/** Status, then approval, then the rest (first occurrence of each key wins). */
export function orderMeta(
  identity: Pick<RecordIdentity, "meta" | "status" | "approval">,
  autoApproval?: MetaItem | null,
): OrderedMeta {
  const meta = identity.meta ?? [];
  const approval =
    identity.approval !== undefined ? identity.approval : (meta.find(isApprovalMeta) ?? autoApproval ?? null);
  const status = identity.status ?? meta.find((m) => !isApprovalMeta(m) && isStatusMeta(m)) ?? null;
  const rest = meta.filter((m) => !isApprovalMeta(m) && m !== status && (!status || m.key !== status.key));
  const first = status ?? rest.shift() ?? null;
  const ordered = [first, approval, ...rest].filter((m): m is MetaItem => !!m);
  const seen = new Set<string>();
  const items = ordered.filter((m) => (seen.has(m.key) ? false : (seen.add(m.key), true)));
  return { items, hasStatus: !!status };
}
