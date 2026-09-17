/* Cross-register record operations — archive/restore, delete impact and the record
   lifecycle — against the generic `/records/{entityType}/…` endpoints.

   `entityType` is the shared entity registry key ("risk", "control", "business_unit"…);
   every call inherits the owning module's permissions on the server. */

import { createElement, type ReactNode } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog } from "@/lib/feedback";
import type { UserRef } from "@/lib/masterData";

/* ------------------------------------------------------------------ types --- */
export type ArchivedRow = { id: string; reference: string; title: string; deleted_date: string | null };
export type ArchivedPage = { items: ArchivedRow[]; total: number; limit: number; offset: number };
export type RestoreResult = {
  entity_type: string; id: string; reference: string; title: string; label: string;
  /** What else the restore changed, in a sentence (e.g. a risk candidate withdrawn). */
  note?: string;
};

export type ImpactLink = { type: string; label: string; count: number };
export type ImpactReport = { entity_type: string; id: string; label: string; links: ImpactLink[]; total: number };

export type WorkflowStateKey = "draft" | "in_review" | "approved" | "retired";
export type WorkflowActionKey = "submit" | "approve" | "reject" | "revise" | "retire";

export type WorkflowHistoryItem = {
  action: string;
  actor_id: string | null;
  actor_email: string;
  at: string;
  from_state: string | null;
  to_state: string | null;
  reason: string;
  via: string;
  summary: string;
};

export type RecordWorkflow = {
  entity_type: string;
  id: string;
  label: string;
  state: WorkflowStateKey;
  owner: UserRef | null;
  owner_text: string;
  can_set_owner: boolean;
  allowed_actions: WorkflowActionKey[];
  blocked_reason: string | null;
  routing: boolean;
  route_instance_id: string | null;
  history: WorkflowHistoryItem[];
};

export type TransitionResult = {
  entity_type: string;
  id: string;
  action: WorkflowActionKey;
  previous: WorkflowStateKey;
  state: WorkflowStateKey;
  routed: boolean;
  route_instance_id: string | null;
  allowed_actions: WorkflowActionKey[];
};

/* -------------------------------------------------------------------- API --- */
const seg = (s: string) => encodeURIComponent(s);

export const records = {
  /** Archived (soft-deleted) records of one type, newest first. */
  archived(entityType: string, opts: { search?: string; limit?: number; offset?: number } = {}) {
    const qs = new URLSearchParams();
    if (opts.search) qs.set("search", opts.search);
    qs.set("limit", String(opts.limit ?? 50));
    qs.set("offset", String(opts.offset ?? 0));
    return apiCall<ArchivedPage>("GET", `/records/${seg(entityType)}/archived?${qs}`);
  },
  /** Bring an archived record back (409 if a live record now holds its name). */
  restore(entityType: string, id: string) {
    return apiCall<RestoreResult>("POST", `/records/${seg(entityType)}/${seg(id)}/restore`);
  },
  /** Live linked records by type — what a delete would touch. */
  impact(entityType: string, id: string) {
    return apiCall<ImpactReport>("GET", `/records/${seg(entityType)}/${seg(id)}/impact`);
  },
  /** Lifecycle state, approval owner, this user's allowed actions and the history. */
  workflow(entityType: string, id: string) {
    return apiCall<RecordWorkflow>("GET", `/records/${seg(entityType)}/${seg(id)}/workflow`);
  },
  /** Submit / approve / reject (reason required) / revise / retire. */
  transition(entityType: string, id: string, action: WorkflowActionKey, reason?: string) {
    return apiCall<TransitionResult>(
      "POST",
      `/records/${seg(entityType)}/${seg(id)}/workflow/${action}`,
      { reason: reason?.trim() || null },
    );
  },
  /** Name (or clear, with null) the approval owner. */
  setOwner(entityType: string, id: string, ownerId: string | null) {
    return apiCall<RecordWorkflow>("PUT", `/records/${seg(entityType)}/${seg(id)}/workflow/owner`, {
      workflow_owner_id: ownerId,
    });
  },
};

/* ------------------------------------------------------------------ words --- */
export const WORKFLOW_STATE_LABEL: Record<WorkflowStateKey, string> = {
  draft: "Draft",
  in_review: "In review",
  approved: "Approved",
  retired: "Retired",
};

export const WORKFLOW_ACTION_LABEL: Record<WorkflowActionKey, string> = {
  submit: "Submit for review",
  approve: "Approve",
  reject: "Reject",
  revise: "Revise",
  retire: "Retire",
};

/** Past tense, as the history and toasts show it (includes the system-only "withdraw"). */
export const WORKFLOW_ACTION_DONE: Record<string, string> = {
  submit: "Submitted for review",
  approve: "Approved",
  reject: "Returned to draft",
  revise: "Reopened for revision",
  retire: "Retired",
  withdraw: "Withdrawn from review",
  owner: "Approval owner changed",
};

/** "business_unit" → "business unit". */
export function entityTypeWords(entityType: string): string {
  return entityType.replace(/_/g, " ");
}

/** A type label in running text: lower-cased unless it starts with an acronym ("RCSA assessment"). */
function inText(label: string): string {
  return /^[A-Z]{2}/.test(label) ? label : label.charAt(0).toLowerCase() + label.slice(1);
}

const UNCOUNTABLE = new Set(["evidence"]);

/** "3 controls", "1 policy", "2 third parties", "4 evidence". */
export function countOf(label: string, count: number): string {
  const word = inText(label);
  if (count === 1 || UNCOUNTABLE.has(word.toLowerCase())) return `${count} ${word}`;
  let plural: string;
  if (/[^aeiou]y$/i.test(word)) plural = word.slice(0, -1) + "ies";
  else if (/(s|x|ch|sh)$/i.test(word)) plural = word + "es";
  else plural = word + "s";
  return `${count} ${plural}`;
}

/** "12 risks, 3 controls and 1 policy" — empty string when nothing links. */
export function impactSummary(links: ImpactLink[]): string {
  const parts = links.filter((l) => l.count > 0).map((l) => countOf(l.label, l.count));
  if (parts.length <= 1) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
}

/* ---------------------------------------------------- delete confirmation --- */
type ConfirmDeleteOpts = {
  /** What the record is, in words ("risk", "business unit"); defaults from entityType. */
  typeLabel?: string;
  confirmLabel?: string;
  /** Extra sentence after the impact line (e.g. what happens to linked risks). */
  note?: string;
  /** The register hard-deletes (no archive): say it can't be undone instead. */
  permanent?: boolean;
};

/**
 * Confirm a delete after showing what links to the record:
 *   if (!(await confirmDeleteWithImpact("risk", r.id, `${r.reference} ${r.title}`))) return;
 * "This risk is linked to: 12 controls, 3 policies and 1 KRI." plus a per-type list.
 * If the impact can't be read the dialog still opens, saying so.
 */
export async function confirmDeleteWithImpact(
  entityType: string,
  id: string,
  label: string,
  opts: ConfirmDeleteOpts = {},
): Promise<boolean> {
  const type = opts.typeLabel || entityTypeWords(entityType);
  // The impact check is a round trip. If the record the delete was asked from is closed
  // (or another opened) meanwhile, don't pop a delete confirm over whatever is showing now.
  const openRecord = () => (typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("id"));
  const askedFrom = openRecord();
  const report = await records.impact(entityType, id).catch(() => null);
  if (openRecord() !== askedFrom) return false;
  const archiveNote = opts.permanent
    ? "This can't be undone."
    : "It is archived, not erased: it can be restored from the register's Archived list until the retention period ends.";

  let message: string;
  let details: ReactNode = undefined;
  if (!report) {
    message = `We couldn't check what links to this ${type}. ${archiveNote}`;
  } else if (report.total === 0) {
    message = `Nothing live links to this ${type}. ${archiveNote}`;
  } else {
    message = `This ${type} is linked to: ${impactSummary(report.links)}.`;
    details = createElement(
      "div",
      null,
      createElement(
        "ul",
        { style: { margin: "0 0 10px", paddingLeft: 18 } },
        ...report.links.map((l) => createElement("li", { key: l.type }, countOf(l.label, l.count))),
      ),
      createElement("p", { className: "muted", style: { margin: 0, fontSize: 12.5 } }, archiveNote),
    );
  }
  if (opts.note) message = `${message} ${opts.note}`;

  return confirmDialog({
    title: `Delete ${label || `this ${type}`}?`,
    message,
    details,
    confirmLabel: opts.confirmLabel || "Delete",
    danger: true,
  });
}
