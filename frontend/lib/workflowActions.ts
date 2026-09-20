/* One implementation of "move this record through its approval lifecycle"
   (record-page-spec §3.4), shared by WorkflowFields, PrimaryAction and SignOffCard so
   the confirms, toasts and errors are identical wherever the button sits.

     const res = await runWorkflowAction("risk", id, "submit");
     if (res === null) return;            // the user cancelled a confirm
     await gov.reload();                  // throws on error with the server message

   Revise and Retire ask for confirmation first; Reject needs `reason`. On success it
   toasts "Submitted — the approval route's first stage is in the Approvals inbox" when
   the submit started a route, otherwise the past-tense action ("Approved").

   Also here: `WORKFLOW_ACTION_DONE` (the past-tense word for every approval step,
   including `import` — the backfill row a record imported as approved carries) and
   `workflowStepWords(step)`, which says how a history item or `workflow_*` audit row
   reads. An import backfill names no actor: nobody is on record as its approver. */

import { confirmDialog, toast } from "@/lib/feedback";
import {
  records,
  WORKFLOW_ACTION_DONE as RECORDS_ACTION_DONE,
  type TransitionResult,
  type WorkflowActionKey,
} from "@/lib/records";
import { PREDATES_WORKFLOW, importedApprovalText } from "@/lib/record/text";

/** Past-tense word per approval step, keyed by the history action (`workflow_` prefix
 *  removed): lib/records' map plus `import: "Imported"` — the backfill row the server
 *  writes (`workflow_import`, actor `system`) for a record imported as approved or
 *  retired with no approval step on file. */
export const WORKFLOW_ACTION_DONE: Readonly<Record<string, string>> = { ...RECORDS_ACTION_DONE, import: "Imported" };

/** The audit actor the server uses for platform-made rows (data repairs, sweeps). */
export const SYSTEM_ACTOR_EMAIL = "system@nexusline";

/** How one approval step reads, from a `records.workflow().history` item or a
 *  `workflow_*` audit row. `actor` is null for a platform backfill (it never names a
 *  person) and "System" for other platform rows; `sentence` replaces verb + actor for
 *  the backfill: "Imported as approved, no approver recorded", or — where the record was
 *  already in force before the approval lifecycle existed (`via` `predates_workflow`,
 *  B10c) — "Approved on upgrade, no approver recorded — it predates the approval workflow".
 *
 *    workflowStepWords({ action: "approve", actor_email: "a@b.com" })   → { verb: "Approved", actor: "a@b.com", sentence: null }
 *    workflowStepWords({ action: "workflow_import", to_state: "approved" }) → { verb: "Imported", actor: null, sentence: "Imported as approved, no approver recorded" } */
export function workflowStepWords(step: {
  action: string;
  actor_email?: string | null;
  to_state?: string | null;
  summary?: string | null;
  via?: string | null;
}): { verb: string; actor: string | null; sentence: string | null } {
  const key = step.action.startsWith("workflow_") ? step.action.slice("workflow_".length) : step.action;
  const predates = (step.via ?? "") === PREDATES_WORKFLOW;
  const verb = predates ? "Approved on upgrade" : WORKFLOW_ACTION_DONE[key] ?? key.replace(/_/g, " ");
  if (key === "import") {
    const fromSummary = /^Imported as ([a-z_ ]+?)(?::|,|\s*\(|$)/i.exec((step.summary ?? "").trim())?.[1];
    return {
      verb,
      actor: null,
      sentence: importedApprovalText(step.to_state || fromSummary || "approved", step.via),
    };
  }
  const email = (step.actor_email ?? "").trim();
  const actor = !email || email === SYSTEM_ACTOR_EMAIL || email === "system" ? "System" : email;
  return { verb, actor, sentence: null };
}

export async function runWorkflowAction(
  entityType: string,
  id: string,
  action: WorkflowActionKey,
  reason?: string,
): Promise<TransitionResult | null> {
  if (action === "retire") {
    const ok = await confirmDialog({
      title: "Retire this record?",
      message: "A retired record stays on file but is no longer in force. Retiring is final — a replacement is a new record.",
      confirmLabel: "Retire",
      danger: true,
    });
    if (!ok) return null;
  }
  if (action === "revise") {
    const ok = await confirmDialog({
      title: "Reopen for revision?",
      message: "The record returns to draft. Once edited it must be submitted and approved again.",
      confirmLabel: "Revise",
    });
    if (!ok) return null;
  }
  const res = await records.transition(entityType, id, action, reason);
  toast(
    res.routed
      ? "Submitted — the approval route's first stage is in the Approvals inbox"
      : WORKFLOW_ACTION_DONE[action] || "Done",
  );
  return res;
}

/** The server's message from a failed call, or `fallback`. */
export function workflowErrorMessage(e: unknown, fallback = "Could not change the approval status"): string {
  return e instanceof Error && e.message ? e.message : fallback;
}
