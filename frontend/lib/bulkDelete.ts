/* Delete several selected records one at a time and say how it went in one toast.

     const res = await deleteEach(rows, (r) => apiCall("DELETE", `/risks/${r.id}`));
     toastDeleteSummary(res, "risk");

   Under segregation of duties the server refuses (403) to let whoever entered a record
   also delete it. That is expected in a bulk delete, not an error to hide, so refusals
   are counted apart: "Deleted 3; 2 need another user to delete them". Any other failure
   is reported with the first server message. */

import { toast } from "@/lib/feedback";

export type DeleteSummary<T> = {
  deleted: T[];
  /** Refused under segregation of duties: another user has to delete these. */
  needOtherUser: T[];
  /** Failed for any other reason, with the server's message. */
  failed: { row: T; message: string }[];
};

const SOD = /segregation of duties/i;

const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** Run `del` for each row in turn (not in parallel: the server audits each delete). */
export async function deleteEach<T>(rows: T[], del: (row: T) => Promise<unknown>): Promise<DeleteSummary<T>> {
  const out: DeleteSummary<T> = { deleted: [], needOtherUser: [], failed: [] };
  for (const row of rows) {
    try {
      await del(row);
      out.deleted.push(row);
    } catch (e) {
      const message = e instanceof Error && e.message ? e.message : "Could not delete";
      if (SOD.test(message)) out.needOtherUser.push(row);
      else out.failed.push({ row, message });
    }
  }
  return out;
}

/** "Deleted 3; 2 need another user to delete them; 1 could not be deleted: <reason>". */
export function deleteSummaryText<T>(res: DeleteSummary<T>, noun = "record"): string {
  const parts: string[] = [];
  if (res.deleted.length || (!res.needOtherUser.length && !res.failed.length)) {
    parts.push(`Deleted ${plural(res.deleted.length, noun)}`);
  }
  if (res.needOtherUser.length) {
    const n = res.needOtherUser.length;
    parts.push(
      `${parts.length ? n : plural(n, noun)} ${n === 1 ? "needs" : "need"} another user to delete ${n === 1 ? "it" : "them"} (you entered ${n === 1 ? "it" : "them"})`,
    );
  }
  if (res.failed.length) {
    const n = res.failed.length;
    parts.push(`${parts.length ? n : plural(n, noun)} could not be deleted: ${res.failed[0].message}`);
  }
  return parts.join("; ");
}

/** Toast the summary: success when everything went, error when nothing did, info otherwise. */
export function toastDeleteSummary<T>(res: DeleteSummary<T>, noun = "record"): void {
  const blocked = res.needOtherUser.length + res.failed.length;
  toast(deleteSummaryText(res, noun), !blocked ? "success" : res.deleted.length ? "info" : "error");
}

/** A single delete's error for a toast — the server's own words (a segregation-of-duties
 *  refusal already says who must delete it). */
export function deleteErrorText(e: unknown, fallback = "Could not delete"): string {
  return e instanceof Error && e.message ? e.message : fallback;
}
