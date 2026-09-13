/* The issue record's judgement wording (record-page-spec §4.6): the summary tiles, the
   open points, the headline and the few sentences the header derives from them. The only
   place this wording lives — `app/(app)/issues/page.tsx` renders what these functions
   return, and `lib/record/__fixtures__/issue.json` pins them (`npm run
   check:record-copy`). A wording change updates the fixture and needs a Compliance
   reviewer on the PR.

   Pure (record-page-spec §3.2): no React, no DOM, imports only `./text` and `./types`. */

import { approvalWithoutStepText, plural, quote, sentenceCase, sentenceLabel, textOnlyPerson, truncate } from "./text";
import type { Ctx, OpenPoint, Seg, TileModel, TileValue } from "./types";

/* ------------------------------------------------------------------ input ----- */

type Person = { full_name?: string | null; email?: string | null } | null | undefined;

/** A CAPA line, the parts the rules read. */
export type IssueActionFacts = { status: string; due_date: string | null; is_overdue: boolean };

/** A due-date change request, the parts the rules read. */
export type IssueDueChangeFacts = { status: string; reason: string; requested_by_id: string | null; created_at: string };

/** The fields of `GET /issues/{id}` the rules read. */
export type IssueFacts = {
  severity: string | null;
  status: string;
  owner?: string | null;
  owner_id?: string | null;
  source_type: string;
  source_reference: string;
  source_id: string | null;
  identified_date: string | null;
  due_date: string | null;
  closed_date: string | null;
  created_at?: string;
  root_cause: string;
  root_cause_category_ref?: { label: string } | null;
  validation_result: string | null;
  validation_note: string;
  validated_by_ref?: Person;
  validated_at: string | null;
  risks: unknown[];
  controls: unknown[];
  due_date_changes: IssueDueChangeFacts[];
  due_date_moves: number;
  action_count: number;
  open_action_count: number;
  is_overdue: boolean;
  age_days: number;
  actions: IssueActionFacts[];
};

/** Where the issue was raised from, once the page has placed `source_id`: the register
 *  it sits in ("risk", "control", …, or "other" for a record in another module) and its
 *  label. null while it is being placed. */
export type IssueSource = { kind: string; label: string };

export type IssueInput = {
  issue: IssueFacts;
  source: IssueSource | null;
  meId: string | null;
  /** May decide due-date changes (workflow:approve). */
  canApprove: boolean;
  /** The header primary's label: notes that point at it offer the jump only when it matches. */
  primaryLabel: string | null;
};

/* -------------------------------------------------------------- helpers ----- */

const CLOSED_STATES = new Set(["closed", "remediated", "risk_accepted"]);
/** Closed, remediated and risk-accepted issues are closed. */
export const isIssueClosed = (status: string) => CLOSED_STATES.has(status);

const TILE_TONES = new Set(["critical", "high", "medium", "low"]);
const sevValue = (v: string | null | undefined): TileValue =>
  v ? { text: sentenceCase(v), tone: (TILE_TONES.has(v) ? v : "neutral") as TileValue["tone"], badge: true } : { text: "Not rated", tone: "hollow" };

/** Whole days from the ISO date `iso` to `now` in the viewer's calendar (negative when it
 *  is still ahead). */
function daysFrom(iso: string, now: Date): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const then = new Date(y, (m || 1) - 1, d || 1).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return Math.round((today - then) / 86_400_000);
}

/** Days past the due date (at least 1 once the server calls it overdue). */
export function issueDaysOverdue(i: Pick<IssueFacts, "due_date">, now: Date): number {
  return i.due_date ? Math.max(daysFrom(i.due_date, now), 1) : 1;
}

/** The header's Due badge: "Overdue · 12 days". */
export function issueOverdueText(i: Pick<IssueFacts, "due_date">, now: Date): string {
  return `Overdue · ${plural(issueDaysOverdue(i, now), "day")}`;
}

/** What the "Raised against" link says: null when nothing is linked. */
export function issueSourceLabel(i: Pick<IssueFacts, "source_id">, source: IssueSource | null): string | null {
  if (!i.source_id) return null;
  if (!source) return "Loading…";
  if (source.kind === "other") return "A record in another module";
  return source.label;
}

const personName = (u: Person, legacy = "") => u?.full_name || u?.email || legacy;
const inText = (key: string) => sentenceLabel(sentenceCase(key));
/** "Approved" / "In review" / "Retired" — the Record approval state as the header shows it. */
const WORKFLOW_LABEL: Record<string, string> = { in_review: "In review", approved: "Approved", retired: "Retired" };

/* ---------------------------------------------------------------- tiles ----- */

export function issueTiles({ issue: i, source }: IssueInput, ctx: Ctx): TileModel[] {
  const { fmt, now } = ctx;
  const closed = isIssueClosed(i.status);

  // Due date
  const moves = i.due_date_moves;
  const lastApproved = [...i.due_date_changes]
    .filter((c) => c.status === "approved")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  let due: TileModel;
  if (!i.due_date) {
    due = {
      key: "due", label: "Due date", section: "due",
      value: { text: "No due date", tone: "hollow" },
      because: ["No target remediation date, so the issue can't show as overdue."],
      basis: { kind: "missing", text: "Not on file" },
    };
  } else {
    const past = daysFrom(i.due_date, now);
    const value: TileValue = i.is_overdue
      ? { text: `Overdue ${plural(issueDaysOverdue(i, now), "day")}`, tone: "critical", badge: true }
      : closed || past > 0 ? { text: `Due ${fmt.date(i.due_date)}` }
      : past === 0 ? { text: "Due today", tone: "medium" }
      : { text: `Due in ${plural(-past, "day")}` };
    const reason = lastApproved?.reason?.trim();
    due = {
      key: "due", label: "Due date", section: "due", value,
      because: [`Due ${fmt.date(i.due_date)}${moves > 0 ? `; moved ${plural(moves, "time")}${reason ? `, last reason ${quote(reason)}` : ""}` : ""}.`],
      basis: moves > 0 ? { kind: "declared", text: `Date moved ${moves}×` } : { kind: "derived", text: "From the due date" },
    };
  }

  // Age
  const identified = i.identified_date || i.created_at || null;
  const age: TileModel = {
    key: "age", label: "Age", section: "finding",
    value: { text: plural(i.age_days, "day") },
    because: [`${identified ? `Identified ${fmt.date(identified)}` : "Identification date not recorded"}${i.closed_date ? `; closed ${fmt.date(i.closed_date)}` : ""}.`],
    basis: { kind: "derived", text: "Calculated" },
  };

  // Remediation (CAPA)
  const total = i.action_count;
  const open = i.open_action_count;
  const overdue = i.actions.filter((a) => a.is_overdue).length;
  const nextDue = i.actions
    .filter((a) => (a.status === "open" || a.status === "in_progress") && a.due_date)
    .map((a) => a.due_date as string)
    .sort()[0];
  const remediation: TileModel = total === 0
    ? {
        key: "remediation", label: "Remediation", section: "remediation",
        value: { text: "No actions", tone: "hollow" },
        because: ["No corrective or preventive action recorded."],
        basis: { kind: "missing", text: "Not on file" },
      }
    : {
        key: "remediation", label: "Remediation", section: "remediation",
        value: { text: `${total - open} of ${total}`, unit: "actions done" },
        because: [
          open === 0 ? "No action open" : `${open} open`,
          overdue ? `, ${overdue} overdue` : "",
          nextDue ? `; next due ${fmt.date(nextDue)}` : "",
          ".",
        ],
        basis: { kind: "derived", text: "From the action plan" },
      };

  // Raised against
  const sourceLabel = issueSourceLabel(i, source);
  const raised: TileModel = {
    key: "source", label: "Raised against", section: "finding",
    value: sourceLabel ? { text: sourceLabel } : { text: "Not linked", tone: "hollow" },
    because: [
      `Raised from ${inText(i.source_type || "other")}${i.source_reference ? ` (${truncate(i.source_reference, 40)})` : ""}; `,
      `linked to ${plural(i.risks.length, "risk")} and ${plural(i.controls.length, "control")}.`,
    ],
    basis: { kind: "derived", text: "From the source link" },
  };

  // Root cause
  const rc = (i.root_cause || "").trim();
  const rootCause: TileModel = {
    key: "rootcause", label: "Root cause", section: "finding",
    value: i.root_cause_category_ref
      ? { text: i.root_cause_category_ref.label }
      : { text: rc ? "Not categorised" : "Not analysed", tone: "hollow" },
    because: [rc ? truncate(rc, 120) : "No root cause recorded — needed before closure."],
    basis: rc || i.root_cause_category_ref ? { kind: "declared", text: "Recorded by hand" } : { kind: "missing", text: "Not on file" },
  };

  // Validation & closure
  const validated = i.validation_result === "effective" || i.validation_result === "not_effective";
  const closureValue: TileValue =
    i.validation_result === "effective" ? { text: "Validated effective", tone: "low", badge: true }
    : i.validation_result === "not_effective" ? { text: "Not effective", tone: "high", badge: true }
    : closed ? { text: "Closed, not validated", tone: "medium", badge: true }
    : { text: "Not validated", tone: "hollow" };
  const note = (i.validation_note || "").trim();
  const closure: TileModel = {
    key: "closure", label: "Validation & closure", section: "closure",
    value: closureValue,
    because: validated
      ? [`By ${personName(i.validated_by_ref) || "an unnamed validator"}${i.validated_at ? ` on ${fmt.date(i.validated_at)}` : ""}${note ? `: ${quote(note)}` : ""}.`]
      : closed
        ? [`${sentenceCase(i.status)}${i.closed_date ? ` on ${fmt.date(i.closed_date)}` : ""} with no validation on file.`]
        : [`To close: finish every action (${open} open), attach closure evidence, and have someone independent validate the fix.`],
    basis: validated ? { kind: "evidenced", text: "Validation on file" } : { kind: "missing", text: "Not on file" },
  };

  return [due, age, remediation, raised, rootCause, closure];
}

/* ------------------------------------------------------------- headline ----- */

export function issueHeadline({ issue: i }: IssueInput, ctx: Ctx): Seg[] {
  const late = i.is_overdue ? `, ${plural(issueDaysOverdue(i, ctx.now), "day")} overdue` : "";
  const actions: Seg[] = i.action_count === 0
    ? ["no actions recorded"]
    : [{ b: `${i.action_count - i.open_action_count} of ${i.action_count}` }, " actions done"];
  const validation =
    i.validation_result === "effective" ? "validated effective"
    : i.validation_result === "not_effective" ? "validated not effective"
    : "not validated";
  return [`${i.severity ? sentenceCase(i.severity) : "Unrated"} issue${late}; `, ...actions, `; ${validation}.`];
}

/* ---------------------------------------------------------- open points ----- */

export function issueOpenPoints({ issue: i, meId, canApprove, primaryLabel }: IssueInput, ctx: Ctx): OpenPoint[] {
  const { gov, now } = ctx;
  const closed = isIssueClosed(i.status);
  const gaps: OpenPoint[] = [];
  const notes: OpenPoint[] = [];

  if (!i.owner_id && !(i.owner || "").trim()) {
    gaps.push({ id: "issue.owner", level: "gap", text: ["No issue owner."], action: { kind: "edit", target: "general", label: "Assign owner" } });
  }
  if (!closed && !i.due_date) {
    // A finding with no target date never shows as overdue; for a bank that is a finding
    // in itself. The date is edited on the form's Remediation tab.
    gaps.push({
      id: "issue.no_due_date", level: "gap", text: ["No target remediation date: it can't go overdue."],
      action: { kind: "edit", target: "remediation", label: "Set due date" },
    });
  }
  if (i.is_overdue) {
    gaps.push({ id: "issue.overdue", level: "gap", text: [`Overdue by ${plural(issueDaysOverdue(i, now), "day")}.`], action: { kind: "section", target: "remediation", label: "Open plan" } });
  }
  if (i.status !== "open" && !(i.root_cause || "").trim()) {
    // The root cause is edited on the form's Remediation tab.
    gaps.push({ id: "issue.no_root_cause", level: "gap", text: ["No root cause recorded."], action: { kind: "edit", target: "remediation", label: "Record root cause" } });
  }
  if (i.validation_result === "not_effective" && !closed) {
    gaps.push({ id: "issue.not_effective", level: "gap", text: ["Validated as not effective: the fix did not work."], action: { kind: "section", target: "closure", label: "See validation" } });
  }
  if (canApprove && meId && i.due_date_changes.some((c) => c.status === "pending" && c.requested_by_id !== meId)) {
    gaps.push({ id: "issue.due_change_to_decide", level: "gap", text: ["A due-date change is waiting for your decision."], action: { kind: "section", target: "due", label: "Decide" } });
  }
  const ws = gov.workflowState;
  if ((ws === "approved" || ws === "in_review" || ws === "retired") && gov.approvalSteps === 0) {
    gaps.push({
      id: "issue.approved_without_step", level: "gap",
      text: [approvalWithoutStepText(gov, WORKFLOW_LABEL[ws])],
      action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
    });
  }

  if (textOnlyPerson(i.owner_id, i.owner)) {
    notes.push({
      id: "issue.owner_text", level: "note", text: [`Owner is a text label (“${truncate(i.owner, 40)}”), not a person`],
      action: { kind: "edit", target: "general", label: "Pick a person" },
    });
  }
  if (i.due_date_moves >= 2) {
    notes.push({ id: "issue.moved_twice", level: "note", text: [`Due date moved ${i.due_date_moves} times`], action: { kind: "section", target: "due", label: "See history" } });
  }
  if (!closed && i.action_count > 0 && i.open_action_count === 0 && !i.validation_result) {
    notes.push({
      id: "issue.ready_to_validate", level: "note", text: ["All actions done; not yet validated"],
      action: primaryLabel === "Validate…" ? { kind: "focus", target: "rec-primary", label: "Validate…" } : undefined,
    });
  }
  if (i.action_count === 0) {
    notes.push({ id: "issue.no_actions", level: "note", text: ["No corrective action recorded"], action: { kind: "open", target: "add-action", label: "Add action" } });
  }
  return [...gaps, ...notes];
}

/** The line OpenPoints shows when nothing is open. */
export const ISSUE_CLEAR_TEXT = "No open points: owner, root cause, actions and validation are on file.";

/** The Validation & closure section's guidance while the issue is open. */
export function issueClosureGuidance(openActions: number): string {
  return `To close: finish or cancel every action (${openActions} open), attach closure evidence (Discussion & files), and have someone other than the owner and the person who raised it record the fix as effective. Closing as risk accepted needs an approved acceptance on a linked risk instead, or an approver's note.`;
}
