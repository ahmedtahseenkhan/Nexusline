"use client";

/* Standard header actions for dossier pages (record-page-spec §4.0 "Base More items").

     moreItems={withBaseMoreItems(
       [{ label: "Raise issue…", onClick: () => issuesRef.current?.raise() }],   // type items first
       { onDelete: () => remove(detail) },                                        // the page's own delete + confirm
     )}

   → type items, "Copy link", "Print (working copy)", a divider, "Delete" (danger).
   Revise and Retire are never here — they live in the Sign-off card. */

import type { MenuItem } from "@/components/Menu";
import { toast } from "@/lib/feedback";

/** Copy the current URL (the record's deep link) to the clipboard, with a toast. */
export async function copyRecordLink(): Promise<void> {
  try {
    await navigator.clipboard.writeText(window.location.href);
    toast("Link copied");
  } catch {
    toast("Could not copy the link — copy it from the address bar", "error");
  }
}

/** Print the open record as a working copy (RecordDrawer dossier adds the print CSS and footer). */
export function printRecord(): void {
  window.print();
}

export function withBaseMoreItems(
  typeItems: MenuItem[],
  opts: { onDelete?: () => void; deleteLabel?: string } = {},
): MenuItem[] {
  const items: MenuItem[] = [...typeItems];
  if (items.length && items[items.length - 1] !== "divider") items.push("divider");
  items.push({ label: "Copy link", onClick: () => void copyRecordLink() });
  items.push({ label: "Print (working copy)", onClick: printRecord, hint: "Not a certified export" });
  if (opts.onDelete) {
    items.push("divider");
    items.push({ label: opts.deleteLabel ?? "Delete", onClick: opts.onDelete, danger: true });
  }
  return items;
}
