/* Words for audit-log rows, shared by ActivityPanel (classic rail) and RecordTrail (dossier). */

import { WORKFLOW_ACTION_DONE, workflowStepWords } from "@/lib/workflowActions";
import type { TrailFilter } from "@/components/record/types";

export const ACTION_WORDS: Record<string, string> = {
  create: "created", update: "updated", delete: "deleted", review: "reviewed",
  attest: "attested", attest_confirm: "confirmed an attestation", decide: "decided", publish: "published",
  export: "exported", submit: "submitted", withdraw: "withdrew",
  request_acceptance: "requested acceptance", approve_acceptance: "approved acceptance",
  reject_acceptance: "rejected acceptance", expire_acceptance: "acceptance lapsed",
  accept_residual: "accepted residual", accept: "accepted", assess: "assessed", mark_reviewed: "marked reviewed",
  import_state: "imported the record with its approval state",
};

/** The verb for an audit action: ACTION_WORDS, `workflow_*` via WORKFLOW_ACTION_DONE, else the action in words. */
export function actionWord(action: string): string {
  if (action.startsWith("workflow_")) {
    const k = action.slice("workflow_".length);
    const done = WORKFLOW_ACTION_DONE[k];
    if (done) return done.charAt(0).toLowerCase() + done.slice(1);
  }
  return ACTION_WORDS[action] ?? action.replace(/_/g, " ");
}

const DECISIONS = new Set([
  "request_acceptance", "approve_acceptance", "reject_acceptance", "expire_acceptance",
  "accept", "accept_residual", "assess", "review", "mark_reviewed",
]);

/** Trail category from the audit action (record-page-spec §3.3.11). */
export function trailCategory(action: string): Exclude<TrailFilter, "all"> {
  if (action.startsWith("workflow_") || action === "submit" || action === "withdraw") return "approval";
  if (action === "attest" || action === "attest_confirm") return "attestation";
  if (DECISIONS.has(action)) return "decision";
  return "change";
}

export const TRAIL_LABEL: Record<TrailFilter, string> = {
  all: "All",
  approval: "Approval",
  attestation: "Attestation",
  decision: "Decisions",
  change: "Changes",
};

/** A 403 from the API (the viewer lacks the permission), as `request()` reports it. */
export function isForbidden(e: unknown): boolean {
  if (!e || typeof e !== "object") return false;
  const status = (e as { status?: unknown }).status;
  if (status === 403) return true;
  const msg = e instanceof Error ? e.message : "";
  return /requires permission|forbidden|not permitted|permission denied/i.test(msg);
}

export const TRAIL_FORBIDDEN = "You need the Activity log permission to see this record's trail.";

/** How an audit row names who did it: the actor's e-mail, "System" for platform rows,
 *  and null for an import backfill (`workflow_import`), which is shown as one sentence —
 *  "Imported as approved, no approver recorded" — and never names anyone. */
export function trailRowWords(row: {
  action: string;
  actor_email?: string | null;
  summary?: string | null;
  changes?: Record<string, unknown> | null;
}): { actor: string | null; verb: string; sentence: string | null } {
  // Only the audit action `workflow_import` is the backfill; a bare "import" row (a bulk
  // import of the register) is an ordinary change by the person who ran it.
  const to = row.changes && typeof row.changes.to === "string" ? row.changes.to : null;
  const step = row.action.startsWith("workflow_") ? row.action : "workflow_change";
  const w = workflowStepWords({ action: step, actor_email: row.actor_email, to_state: to, summary: row.summary });
  if (row.action === "workflow_import" && w.sentence) return { actor: null, verb: actionWord(row.action), sentence: w.sentence };
  return { actor: w.actor, verb: actionWord(row.action), sentence: null };
}

