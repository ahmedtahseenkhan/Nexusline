/* Shared wording helpers for the record page (record-page-spec §3.2).

   Pure: imports only `@/lib/text` (pure) and `./types` (types). The fixture runner
   executes this file under Node, so keep it free of React, the DOM and `@/components`.

     joinList(["a", "b", "c"])              → "a, b and c"   (no Oxford comma)
     joinList(["a", "b"], "or")             → "a or b"
     plural(2, "control")                   → "2 controls"
     plural(1, "third party", "third parties") → "1 third party"
     sentenceLabel("Third parties")         → "third parties"  ("KRIs", "IT assets" unchanged)
     sentenceCase("not_assessed")           → "Not assessed"
     critRank("high")                       → 3
     schemeRank(4, 4)                       → 4
     durationHours(28)                      → "1 d 4 h"
     cadenceNoun("semiannual")              → "twice-yearly"
     opLabel("gte")                         → "≥"
     approvalLine(gov, fmt)                 → { text, short, warn, note? }  (header meta + Sign-off)
     importedApprovalText("approved")       → "Imported as approved, no approver recorded"
     rowLabel("SRV-01", "Core banking host") → "SRV-01 Core banking host"
     rowActionName("Unlink", "SRV-01 Core banking host") → "Unlink SRV-01 Core banking host"
     attestFix(gov)                         → Attest… / Submit for review / See approval / none (decision 6)
     awaitingConfirmationText(att, fmt)     → "Attested by a@b on 20 Sep 2026 — awaiting independent confirmation." */

import { sentenceCase } from "@/lib/text";
import type { Fmt, GovModel, OpenPoint, PointAction, Seg } from "./types";

export { sentenceCase };

/** "a, b and c" / "a, b or c" — no Oxford comma. Empty strings are dropped. */
export function joinList(xs: readonly string[], conj: "and" | "or" = "and"): string {
  const list = xs.filter((x) => x !== "");
  if (list.length <= 1) return list.join("");
  return `${list.slice(0, -1).join(", ")} ${conj} ${list[list.length - 1]}`;
}

/** plural(2, "control") → "2 controls"; pass `many` for irregular words. */
export function plural(n: number, one: string, many: string = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** A label in running text: lower-cased unless it starts with an acronym ("KRIs", "IT assets"). */
export function sentenceLabel(label: string): string {
  const t = label.trim();
  if (/^[A-Z]{2}/.test(t)) return t;
  return t.charAt(0).toLowerCase() + t.slice(1);
}

const CRIT: Record<string, number> = { low: 1, medium: 2, high: 3, critical: 4 };

/** low 1, medium 2, high 3, critical 4; anything else 0. */
export function critRank(v: string | null | undefined): number {
  return CRIT[(v ?? "").toLowerCase()] ?? 0;
}

/** Scheme value → 1..4 rank: Math.ceil(value / max × 4), clamped to 1–4. */
export function schemeRank(value: number, max: number): number {
  if (!(max > 0)) return 1;
  return Math.min(4, Math.max(1, Math.ceil((value / max) * 4)));
}

/** "2 h", "1 d 4 h", "< 1 h" or "not yet" (null). Negative values are shown as their size. */
export function durationHours(h: number | null | undefined): string {
  if (h === null || h === undefined || !Number.isFinite(h)) return "not yet";
  const abs = Math.abs(h);
  if (abs > 0 && abs < 1) return "< 1 h";
  const total = Math.round(abs);
  const d = Math.floor(total / 24);
  const r = total % 24;
  if (d === 0) return `${r} h`;
  return r === 0 ? `${d} d` : `${d} d ${r} h`;
}

const CADENCE: Record<string, string> = {
  annual: "annual",
  semiannual: "twice-yearly",
  quarterly: "quarterly",
  monthly: "monthly",
  fortnightly: "fortnightly",
  weekly: "weekly",
  daily: "daily",
  continuous: "continuous",
  none: "no",
};

/** annual → "annual", semiannual → "twice-yearly", …, none / unset → "no". */
export function cadenceNoun(freq: string | null | undefined): string {
  const k = (freq ?? "").toLowerCase();
  if (!k) return "no";
  return CADENCE[k] ?? k.replace(/_/g, " ");
}

const OPS: Record<string, string> = {
  eq: "=",
  ne: "≠",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  contains: "contains",
  overdue: "is overdue",
  is_true: "is yes",
  is_false: "is no",
  not_empty: "is set",
};

/** Status-rule operator in words: gte → "≥", overdue → "is overdue", not_empty → "is set". */
export function opLabel(operator: string | null | undefined): string {
  const k = (operator ?? "").toLowerCase();
  return OPS[k] ?? k.replace(/_/g, " ");
}

/** Truncate free text for quoting: at most `n` characters, ending in "…" when cut. */
export function truncate(s: string | null | undefined, n = 60): string {
  const t = (s ?? "").trim().replace(/\s+/g, " ");
  if (t.length <= n) return t;
  return t.slice(0, n - 1).trimEnd() + "…";
}

/** “quoted”, truncated at `n` characters. */
export function quote(s: string | null | undefined, n = 60): string {
  return `“${truncate(s, n)}”`;
}

/** Flatten segments to plain text (accessible names, fixtures, length checks). */
export function segsText(segs: readonly Seg[]): string {
  return segs.map((s) => (typeof s === "string" ? s : s.b)).join("");
}

export type ApprovalLine = {
  /** The Sign-off card status line: "Returned to draft 03 Jul 2026 by a@b.com: “…”". */
  text: string;
  /** The header meta `sub`: "not submitted", "in review since {d}", "approved {d}", "retired {d}"; "" when the meta shows a gap instead. */
  short: string;
  /** Amber: the line reports that evidence is missing (no approval step, an import backfill). */
  warn: boolean;
  /** Muted follow-on text, e.g. "(set before approvals were tracked, or imported)". */
  note?: string;
};

const STATE_WORD: Record<string, string> = {
  draft: "draft",
  in_review: "in review",
  approved: "approved",
  retired: "retired",
};

/** `changes.via` on the B10c backfill: a record that was already in force before the
 *  approval lifecycle existed, approved on upgrade so it can be attested (decision 6). */
export const PREDATES_WORKFLOW = "predates_workflow";

/** The one sentence for a record whose only approval step was written by the platform:
 *  "Imported as approved, no approver recorded" (B10b), or "Approved on upgrade, no
 *  approver recorded — it predates the approval workflow" (B10c). Neither names a person
 *  or carries a date: the row's timestamp is when the repair ran, not when anyone
 *  decided. Used by the Sign-off card, the header meta and the trail. */
export function importedApprovalText(state: string | null | undefined, via?: string | null): string {
  const k = (state ?? "").trim().toLowerCase();
  const word = STATE_WORD[k] ?? (k.replace(/_/g, " ") || "approved");
  if ((via ?? "") === PREDATES_WORKFLOW) {
    return `Approved on upgrade, no approver recorded — it predates the approval workflow`;
  }
  return `Imported as ${word}, no approver recorded`;
}

/** The one-line approval status (record-page-spec §3.3.10), shared by the header meta
 *  ("Record approval" `sub`) and the Sign-off card. `routing` adds the inbox note while
 *  an approval route is live. */
export function approvalLine(gov: GovModel, fmt: Fmt, opts: { routing?: boolean } = {}): ApprovalLine {
  const state = gov.workflowState;
  const last = gov.lastStep;
  if (state === null) return { text: "Not in the approval lifecycle", short: "", warn: false };

  if (gov.approvalSteps === 0 && last && last.action === "import") {
    // No date and no actor: the backfill row is dated when the repair ran and is
    // attributed to the platform, so neither says anything about the approval.
    return { text: importedApprovalText(state, last.via), short: "", warn: true };
  }

  if (state !== "draft" && gov.approvalSteps === 0) {
    return {
      text: "No approval step on file",
      short: "",
      warn: true,
      note: "(set before approvals were tracked, or imported)",
    };
  }

  if (state === "draft") {
    if (!last || gov.approvalSteps === 0) return { text: "Not submitted", short: "not submitted", warn: false };
    const d = fmt.date(last.at);
    if (last.action === "reject") {
      return {
        text: `Returned to draft ${d} by ${last.actor}${last.reason.trim() ? `: ${quote(last.reason)}` : ""}`,
        short: `returned to draft ${d}`,
        warn: false,
      };
    }
    if (last.action === "revise") {
      return { text: `Reopened for revision ${d} by ${last.actor}; not resubmitted`, short: `reopened ${d}`, warn: false };
    }
    if (last.action === "withdraw") {
      return { text: `Withdrawn from review ${d}; not resubmitted`, short: `withdrawn ${d}`, warn: false };
    }
    return { text: "Not submitted", short: "not submitted", warn: false };
  }

  if (state === "in_review") {
    const d = fmt.date(gov.lastSubmitAt ?? last?.at ?? null);
    return {
      text: `In review since ${d}${opts.routing ? " · each stage is decided in the Approvals inbox" : ""}`,
      short: `in review since ${d}`,
      warn: false,
    };
  }

  const d = fmt.date(last?.at ?? null);
  if (state === "approved") {
    const by = last && last.action === "approve" && last.actor ? ` by ${last.actor}` : "";
    return { text: `Approved ${d}${by}`, short: `approved ${d}`, warn: false };
  }
  return { text: `Retired ${d}`, short: `retired ${d}`, warn: false };
}

/* ------------------------------------------------ accessible names (v1.1) --------- */

/** How a row names its record in running text and accessible names: the reference and
 *  the name ("SRV-01 Core banking host"), either alone when the other is missing, cut
 *  at `n` characters. */
export function rowLabel(reference: string | null | undefined, name?: string | null, n = 80): string {
  const ref = (reference ?? "").trim();
  const nm = (name ?? "").trim().replace(/\s+/g, " ");
  const both = ref && nm && !nm.startsWith(ref) ? `${ref} ${nm}` : nm || ref;
  return truncate(both, n);
}

/** The accessible name of a per-row action (v1.1 convention): the visible verb, then the
 *  row's label — "Edit SRV-01 Core banking host", "Unlink …", "Remove …" — so a list of
 *  buttons never reads "Edit, Edit, Edit". The name starts with the visible text, as
 *  WCAG 2.5.3 (label in name) requires. With no label it is the verb alone. */
export function rowActionName(verb: string, label: string | null | undefined): string {
  const v = verb.trim();
  const l = (label ?? "").trim().replace(/\s+/g, " ");
  return l ? `${v} ${l}` : v;
}


/** Row labels made unique within one table (decision D3): a label that occurs more than
 *  once gets " (i of n)" (or " ({noun} i of n)"), in row order; unique labels are kept as
 *  they are. Use it after adding the row's own distinguishing parts (a relationship, a
 *  period, a due date), so the counter is only the last resort. */
export function uniqueLabels(labels: readonly string[], noun?: string): string[] {
  const total = new Map<string, number>();
  for (const l of labels) total.set(l, (total.get(l) ?? 0) + 1);
  const seen = new Map<string, number>();
  return labels.map((l) => {
    const n = total.get(l) ?? 1;
    if (n < 2) return l;
    const i = (seen.get(l) ?? 0) + 1;
    seen.set(l, i);
    return `${l} (${noun ? `${noun} ` : ""}${i} of ${n})`;
  });
}

/** The "approved without a step" open point's sentence (decision D5): for an import
 *  backfill "Imported as approved, no approver recorded." — the header and Sign-off
 *  wording — else "Record approval shows {state} but no approval step is on file." */
export function approvalWithoutStepText(gov: Pick<GovModel, "workflowState" | "lastStep">, stateLabel: string): string {
  if (gov.lastStep?.action === "import") return `${importedApprovalText(gov.workflowState, gov.lastStep.via)}.`;
  return `Record approval shows ${stateLabel} but no approval step is on file.`;
}

/** A linked exception's state and date in words (B3), one rule for every record type:
 *  "Approved · expires 03 Jan 2027" (or "no expiry set"), "Pending · expires …",
 *  "Expired 30 Jun 2026" (past tense for a lapsed one), and for a rejected or closed
 *  exception the state alone (its expiry no longer means anything). Null without a
 *  status (an older API). `sep` joins state and date; `lower` lower-cases the state for
 *  use inside a sentence ("EXC-001 (approved, expires …)"). */
export function exceptionStateText(
  status: string | null | undefined,
  expiresAt: string | null | undefined,
  fmt: Pick<Fmt, "date">,
  opts: { sep?: string; lower?: boolean } = {},
): string | null {
  const st = (status ?? "").trim().toLowerCase();
  if (!st) return null;
  const sep = opts.sep ?? " · ";
  const word = opts.lower ? sentenceCase(st).toLowerCase() : sentenceCase(st);
  const d = expiresAt ? fmt.date(expiresAt) : "";
  if (st === "expired") return d ? `${word} ${d}` : word;
  if (st === "approved") return `${word}${sep}${d ? `expires ${d}` : "no expiry set"}`;
  if (st === "pending") return d ? `${word}${sep}expires ${d}` : word;
  return word;
}

/** The review-cycle tail for lapsed reviews: "" for none, " · 2 reviews missed" otherwise
 *  (the count of scheduled reviews whose date passed without one), so a zero never shows
 *  as jargon ("0 expired"). */
export function missedReviewsText(n: number | null | undefined): string {
  return n && n > 0 ? ` · ${plural(n, "review")} missed` : "";
}

/** A progress count's tone, "0 of 3" / "2 of 3" / "3 of 3": green only when all are
 *  done, amber while any is outstanding, neutral when nothing is in scope. */
export function progressTone(done: number, total: number): "low" | "medium" | "neutral" {
  if (total <= 0) return "neutral";
  return done >= total ? "low" : "medium";
}

/** A person field that holds only free text ("CISO", "Network Team"): a label, not a
 *  person anyone can notify or hold to account. False when a person is picked or the
 *  field is empty. */
export function textOnlyPerson(id: string | null | undefined, text: string | null | undefined): boolean {
  return !id && !!(text ?? "").trim();
}

/* ------------------------------------------------------------ decision 6 (2026-09-17) */

/** Whether the record's approval stops an attestation: only an approved record can be
 *  attested (a retired one is final). `null` = no approval lifecycle, never blocks. The
 *  server's `can_attest` says the same; this lets the page name the approval step. */
export function approvalBlocksAttest(gov: Pick<GovModel, "workflowState">): boolean {
  const ws = gov.workflowState;
  return ws === "draft" || ws === "in_review" || ws === "retired";
}

const ATTEST: PointAction = { kind: "attest", target: "attest", label: "Attest…" };

/** The fix an attestation point offers: Attest… when allowed; the approval step first
 *  while the approval is draft or in review; none when retired or the server refuses. */
export function attestFix(gov: Pick<GovModel, "workflowState" | "attestation">): PointAction | undefined {
  const ws = gov.workflowState;
  if (ws === "draft") return { kind: "focus", target: "rec-signoff", label: "Submit for review" };
  if (ws === "in_review") return { kind: "focus", target: "rec-signoff", label: "See approval" };
  if (ws === "retired" || gov.attestation?.canAttest === false) return undefined;
  return ATTEST;
}

/** "Approve before attesting: its approval is in review." */
export function approveBeforeAttestText(ws: "draft" | "in_review"): string {
  return `Approve before attesting: its approval is ${ws === "draft" ? "draft" : "in review"}.`;
}

/** The note that replaces "Never attested" while the record is in review, or null. A
 *  draft raises no attestation note (it is still being written; its approval card says
 *  Draft), and a retired record owes none. */
export function approveBeforeAttestPoint(prefix: string, gov: Pick<GovModel, "workflowState" | "attestation">): OpenPoint | null {
  if (gov.workflowState !== "in_review" || gov.attestation?.status !== "never") return null;
  return { id: `${prefix}.approve_before_attest`, level: "note", text: [approveBeforeAttestText("in_review")], action: attestFix(gov) };
}

/** "Never attested" for an approved record, "Approve before attesting…" for one in
 *  review, nothing for draft, retired or no lifecycle. The server's `blockedReason` joins
 *  the text when it refuses.
 *
 *  An attestation still waiting for its required second signature takes precedence: the
 *  record has been certified but the certification does not count yet, which is a
 *  different thing to say (decision 9, `awaitingConfirmationPoint`). */
export function attestationNotePoint(
  prefix: string,
  gov: Pick<GovModel, "workflowState" | "attestation">,
  opts: { withReason?: boolean; fmt?: Pick<Fmt, "date"> } = {},
): OpenPoint | null {
  const waiting = awaitingConfirmationPoint(prefix, gov, opts.fmt);
  if (waiting) return waiting;
  const ws = gov.workflowState;
  const att = gov.attestation;
  if (att?.status !== "never") return null;
  if (ws === "in_review") return approveBeforeAttestPoint(prefix, gov);
  if (ws !== "approved") return null;
  const blocked = att.canAttest === false && opts.withReason === true;
  const reason = (att.blockedReason ?? "").trim();
  return {
    id: `${prefix}.never_attested`, level: "note",
    text: [blocked && reason ? `Never attested. ${reason}` : "Never attested"],
    action: attestFix(gov),
  };
}

/* ------------------------------------------------------------ decision 9 (2026-09-20) */

/** "Attested by ayesha@bank.pk on 20 Sep 2026 — awaiting independent confirmation."
 *  The signer's own words, without a date when the server did not send one. */
export function awaitingConfirmationText(
  att: NonNullable<GovModel["attestation"]>,
  fmt?: Pick<Fmt, "date">,
): string {
  const by = (att.awaitingBy ?? "").trim() || "another user";
  const on = att.awaitingAt && fmt ? ` on ${fmt.date(att.awaitingAt)}` : "";
  return `Attested by ${by}${on} — awaiting independent confirmation.`;
}

/** The open point for a high-stakes record whose attestation is signed but not yet
 *  confirmed (decision 9): until a second person signs it, the certification does not
 *  count and the review cycle has not restarted. `null` when nothing is waiting.
 *
 *  `fmt` is optional so a page that has no formatter still gets the sentence; pass one
 *  to date it in the tenant's own format. The fix points at the Sign-off card, where the
 *  Confirm button lives — whoever may confirm sees it there. */
export function awaitingConfirmationPoint(
  prefix: string,
  gov: Pick<GovModel, "attestation">,
  fmt?: Pick<Fmt, "date">,
): OpenPoint | null {
  const att = gov.attestation;
  if (!att?.awaitingConfirmation) return null;
  return {
    id: `${prefix}.awaiting_confirmation`,
    level: "gap",
    text: [
      `${awaitingConfirmationText(att, fmt)} The review cycle restarts when it is confirmed.`,
    ],
    action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
  };
}
