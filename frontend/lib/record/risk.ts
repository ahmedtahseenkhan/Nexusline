/* The risk record page's judgement wording (record-page-spec §4.1): the six summary
   tiles, the open points, the headline, and every explanatory line the sections carry
   (basis cells, the controls note, the suggested-residual basis, the rollup line).

   Pure: plain record data plus `Ctx`, no React, no DOM, no `@/components`, so
   `npm run check:record-copy` runs it under Node against lib/record/__fixtures__/risk-*.json.
   This file is the only place risk wording lives; the page renders what it returns.
   A wording change updates the fixtures and needs a Compliance reviewer (§3.8).

   It explains the server's judgements (appetite_status, control assurance, the severity
   bands) and never recomputes them, with two client projections kept for an older API:
   the appetite band a *suggested* score would fall in (B12 sends it), and which linked
   controls a suggestion takes credit from (B6 sends `credited_control_ids`).

   Backend fields read, each optional so an older API degrades as §3.6 says:
     B2  controls[].effectiveness, effectiveness_basis, audit_count, last_audit_result,
         last_audit_date, next_audit_date, is_audit_overdue, pending_review_count,
         open_finding_count, open_issue_count — the counted (reviewed) test view, the
         same one the residual engine judges reliance by (control_assurance.reliance_note)
         — absent (older API, or a viewer without control:read): reliance tile "Basis not
           shown", no untested-credit point, the Controls table shows Ref and Name only.
           open_issue_count alone is absent without issue:read: nothing is said about issues.
     B3  exceptions[].status, expires_at — absent: "EXC-001 is linked; an exception is
         not a risk acceptance."
     B6  suggestion.credited_control_ids, note_required — absent: credit is projected
         from the ratings, and the page learns a note is needed from the refusal.
     B12 suggestion.appetite_status — absent: the register's own rule (≤ appetite
         within, ≤ tolerance elevated, else breach). */

import type { Basis, Ctx, Fmt, OpenPoint, ScaleModel, Seg, TileModel, TileValue, Tone } from "./types";
import { approvalWithoutStepText, exceptionStateText, joinList, missedReviewsText, plural, quote, segsText, sentenceCase, truncate } from "./text";

// ------------------------------------------------------------------ input types

export type RiskUserRef = { full_name?: string | null; email?: string | null } | null;

/** A linked control as `GET /risks/{id}` returns it: identity, plus the assurance
 *  fields of B2 (`ControlAssuranceRef`) on the new API. */
export type RiskControlRef = {
  id: string;
  reference?: string;
  name?: string;
  title?: string;
  effectiveness?: string | null;
  /** tests | override | manual | none (B2). */
  effectiveness_basis?: string | null;
  audit_count?: number | null;
  last_audit_result?: string | null;
  last_audit_date?: string | null;
  next_audit_date?: string | null;
  is_audit_overdue?: boolean | null;
  /** Tests awaiting a reviewer: not counted above, and they withhold no credit yet. */
  pending_review_count?: number | null;
  /** Open audit findings: the residual engine withholds credit while any is open. */
  open_finding_count?: number | null;
  /** null / absent when the viewer lacks issue:read (the server leaves it out). */
  open_issue_count?: number | null;
};

/** A linked exception to policy (B3 adds `status` and `expires_at`). */
export type RiskExceptionRef = {
  id: string;
  reference?: string;
  title?: string;
  name?: string;
  status?: string | null;
  expires_at?: string | null;
};

export type RiskAcceptanceRef = {
  id: string;
  status: string;
  rationale?: string | null;
  created_at: string;
  decided_at?: string | null;
  expires_at?: string | null;
};

/** `GET /risks/{id}/suggested-residual` (+ B6, B12 on the new API). */
export type RiskSuggestion = {
  likelihood: number;
  impact: number;
  score: number;
  reduction: number;
  rationale: string[];
  matches_current: boolean;
  /** B12: the appetite band the suggested score would fall in. */
  appetite_status?: string | null;
  /** B6: the controls whose credit the suggestion takes; empty when it equals inherent. */
  credited_control_ids?: string[] | null;
  /** B6: accepting the suggestion as it stands needs the owner's note. */
  note_required?: boolean | null;
};

/** The payload fields of `GET /risks/{id}` the rules read. */
export type RiskRecord = {
  title: string;
  description?: string | null;
  cause?: string | null;
  event?: string | null;
  consequence?: string | null;
  status: string;
  owner_id: string | null;
  /** Business units the risk sits in; absent on an older API (nothing is said then). */
  business_units?: { id: string; name?: string }[] | null;
  category?: string | null;
  category_id?: string | null;
  category_ref?: { label: string; path?: string | null } | null;

  inherent_likelihood: number | null;
  inherent_impact: number | null;
  inherent_score: number | null;
  inherent_severity: string | null;
  /** The server's is_scored (F-23): false for a draft nobody has scored. Absent on an
   *  older API, where the page applies the same rule itself. */
  inherent_scored?: boolean | null;
  residual_likelihood: number | null;
  residual_impact: number | null;
  residual_score: number | null;
  residual_severity: string | null;
  residual_override_reason?: string | null;
  suggested_residual_likelihood?: number | null;
  suggested_residual_impact?: number | null;
  residual_accepted_at?: string | null;
  target_score?: number | null;

  assessment_rationale?: string | null;
  last_assessed_at?: string | null;
  last_assessed_by_ref?: RiskUserRef;
  impact_dimensions?: { basis: string }[] | null;

  treatment_strategy: string | null;
  treatment_progress?: { done: number; total: number; open: number; overdue?: number } | null;

  appetite_score?: number | null;
  tolerance_score?: number | null;
  appetite_status?: string | null;
  appetite_category_id?: string | null;

  annual_loss_frequency: number | null;
  single_loss_expectancy: number | null;
  annual_loss_expectancy: number | null;

  review_frequency?: string | null;
  /** The cycle the review clock runs on: the stricter of review_frequency and the longest
   *  the rating allows (F-22), and why when the rating decides it. */
  effective_review_frequency?: string | null;
  review_frequency_reason?: string | null;
  last_review_date?: string | null;
  next_review_date: string | null;
  expired_reviews?: number | null;

  /** The server's rollup of the linked controls' health: "ok" | "untested" | "issues" | "none". */
  control_health?: string | null;
  controls: RiskControlRef[];
  exceptions?: RiskExceptionRef[] | null;
  acceptances?: RiskAcceptanceRef[] | null;
};

export type RiskInput = {
  risk: RiskRecord;
  /** The suggestion for this risk; null while loading or when it failed. */
  suggestion: RiskSuggestion | null;
  matrixSize: number;
  impactMode: "max" | "average";
};

// ------------------------------------------------------------------ small helpers

export type AppetiteKey = "within_appetite" | "elevated" | "breach";
export const APPETITE_WORD: Record<AppetiteKey, string> = { within_appetite: "Within appetite", elevated: "Elevated", breach: "Breach" };
export const APPETITE_TONE: Record<AppetiteKey, Tone> = { within_appetite: "low", elevated: "medium", breach: "critical" };

const SEVERITIES = new Set(["critical", "high", "medium", "low"]);
/** A severity band's badge tone; anything unknown is neutral. */
export const sevTone = (s: string | null | undefined): "critical" | "high" | "medium" | "low" | "neutral" =>
  s && SEVERITIES.has(s) ? (s as "critical" | "high" | "medium" | "low") : "neutral";

/** `name(u)` of the spec: full name, else e-mail. */
export const personName = (u: RiskUserRef | undefined) => (u ? u.full_name || u.email || "" : "");
/** 0.2 → "0.2", 1234.5 → "1,234.5". */
export const figure = (n: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n);
const noStop = (s: string) => s.trim().replace(/[.\s]+$/, "");
const trimmed = (s: string | null | undefined) => (s ?? "").trim();
/** At most 160 characters of because-text: the first candidate that fits. */
const MAX_BECAUSE = 160;
function firstFit(...candidates: Seg[][]): Seg[] {
  for (const c of candidates) if (segsText(c).length <= MAX_BECAUSE) return c;
  const last = candidates[candidates.length - 1];
  return [truncate(segsText(last), MAX_BECAUSE)];
}

/** Statuses that claim an assessment has happened. */
const ASSESSED_STATUSES = new Set(["assessed", "treatment_planned", "treatment_in_progress", "accepted"]);
const APPROVAL_STATE_WORD: Record<string, string> = { in_review: "In review", approved: "Approved", retired: "Retired" };

/** Whole days from `now` to a calendar date; negative once it has passed. */
export function daysFrom(d: string, now: Date): number {
  const [y, m, day] = d.slice(0, 10).split("-").map(Number);
  const target = new Date(y, (m || 1) - 1, day || 1).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  return Math.round((target - today) / 86_400_000);
}

/** A calendar date that has passed. */
export const isPast = (d: string | null | undefined, now: Date) => !!d && daysFrom(d, now) < 0;

// ------------------------------------------------------------------ identity

/** Mirrors risk_integrity.compose_title: "<Event>, caused by <cause>, resulting in <consequence>". */
export function composeRiskTitle(cause: string, event: string, consequence: string): string {
  const clean = (t: string) => t.split(/\s+/).filter(Boolean).join(" ").replace(/[ .;,]+$/, "");
  const lower = (t: string) => (/^[A-Z]{2}/.test(t) ? t : t.charAt(0).toLowerCase() + t.slice(1));
  const ev = clean(event);
  if (!ev) return "";
  const parts = [ev.charAt(0).toUpperCase() + ev.slice(1)];
  if (clean(cause)) parts.push(`caused by ${lower(clean(cause))}`);
  if (clean(consequence)) parts.push(`resulting in ${lower(clean(consequence))}`);
  const title = parts.join(", ");
  return title.length > 255 ? title.slice(0, 254) + "…" : title;
}

/** The lead under the H1: the description when it says more than the title, else the
 *  composed risk statement when that differs from the title, else nothing (§4.1). */
export function riskLead(r: Pick<RiskRecord, "title" | "description" | "cause" | "event" | "consequence">): string | null {
  const d = trimmed(r.description);
  if (d && d !== r.title.trim()) return d;
  const composed = composeRiskTitle(r.cause || "", r.event || "", r.consequence || "");
  return composed && composed !== r.title ? composed : null;
}

/** The picked category as the list shows it: "Parent › Child", else the legacy text. */
export const categoryText = (r: Pick<RiskRecord, "category" | "category_ref">) =>
  r.category_ref ? r.category_ref.path || r.category_ref.label : r.category || "";

/** One reason per line on a risk flagged for review. */
export const reviewReasons = (r: { review_reason?: string | null }) =>
  (r.review_reason || "").split("\n").filter((x) => x.trim());

/** A draft never scored: its stored 1×1 is a placeholder, not an assessment. The server
 *  says so (`inherent_scored`, risk_scoring.is_scored); an older API gets the same rule here. */
export const isUnscored = (r: Pick<RiskRecord, "inherent_score" | "status" | "last_assessed_at" | "inherent_scored">) =>
  r.inherent_score == null
  || (typeof r.inherent_scored === "boolean" ? !r.inherent_scored : r.status === "draft" && !r.last_assessed_at);

/** "Monthly", "Twice a year" — the risk form's words for a review cycle. */
export function frequencyWord(v: string): string {
  if (v === "semiannual") return "Twice a year";
  if (v === "none") return "No cycle";
  return sentenceCase(v);
}

/** "Monthly — required for Critical risks" when the rating decides the cycle, else null. */
export const cadenceNote = (r: Pick<RiskRecord, "review_frequency_reason">) => trimmed(r.review_frequency_reason) || null;

// ------------------------------------------------------------------ appetite

const asAppetite = (s: string | null | undefined): AppetiteKey | null =>
  s === "within_appetite" || s === "elevated" || s === "breach" ? s : null;

/** The server's appetite verdict — only when there is a real score to measure. */
export function appetiteVerdict(r: RiskRecord): AppetiteKey | null {
  if (isUnscored(r)) return null;
  return asAppetite(r.appetite_status);
}

/** The band a suggested score falls in: the server's (B12), else the register's rule
 *  (≤ appetite within, ≤ tolerance elevated, else breach). */
export function suggestedAppetite(s: RiskSuggestion, r: RiskRecord): AppetiteKey | null {
  const server = asAppetite(s.appetite_status);
  if (server) return server;
  if (r.appetite_score == null || r.tolerance_score == null) return null;
  return s.score <= r.appetite_score ? "within_appetite" : s.score <= r.tolerance_score ? "elevated" : "breach";
}

/** Whose thresholds apply: the organisation's, or the top-level category's own. */
export function appetiteScope(r: RiskRecord, short = false): string {
  if (!r.appetite_category_id) return "organisation";
  if (short) return "its category's";
  const cat = categoryText(r);
  if (cat.includes(" › ")) return `category ${truncate(cat.split(" › ")[0], 28)}`;
  if (cat && r.appetite_category_id === r.category_id) return `category ${truncate(cat, 28)}`;
  return "its parent category";
}

/** "6 · 12 (organisation; Business Continuity has none of its own)". */
export function appetiteFact(r: RiskRecord): string | null {
  if (r.appetite_score == null || r.tolerance_score == null) return null;
  const top = categoryText(r).split(" › ")[0];
  const scope = r.appetite_category_id ? appetiteScope(r) : top ? `organisation; ${top} has none of its own` : "organisation";
  return `${r.appetite_score} · ${r.tolerance_score} (${scope})`;
}

// ------------------------------------------------------------------ acceptance and exceptions

export type AcceptanceView<A extends RiskAcceptanceRef = RiskAcceptanceRef> = {
  inForce: A | null;
  pending: A | null;
  lapsed: A | null;
};

/** The acceptance in force (approved, not past its expiry), a request awaiting a
 *  decision, and — when nothing is in force — the latest decision if it has lapsed. */
export function acceptanceView<A extends RiskAcceptanceRef>(r: { acceptances?: A[] | null }, now: Date): AcceptanceView<A> {
  const list = [...(r.acceptances ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const expired = (a: A) =>
    a.status === "expired" || (a.status === "approved" && !!a.expires_at && daysFrom(a.expires_at, now) < 0);
  const inForce = list.find((a) => a.status === "approved" && !expired(a)) ?? null;
  const pending = list.find((a) => a.status === "pending") ?? null;
  const decided = list.find((a) => a.status !== "pending") ?? null;
  return { inForce, pending, lapsed: !inForce && decided && expired(decided) ? decided : null };
}

/** Whether the linked exceptions carry their status and expiry (B3). */
export const hasExceptionDetail = (ex: RiskExceptionRef[]) =>
  ex.length > 0 && ex.every((x) => x.status !== undefined);

const exceptionName = (x: RiskExceptionRef) => trimmed(x.reference) || trimmed(x.title) || trimmed(x.name) || "An exception";

/** "EXC-001 (approved, expires 03 Jan 2027)", or "EXC-001" without B3. */
export function exceptionLabel(x: RiskExceptionRef, fmt: Fmt): string {
  const state = exceptionStateText(x.status, x.expires_at, fmt, { sep: ", ", lower: true });
  return state ? `${exceptionName(x)} (${state})` : exceptionName(x);
}

/** " EXC-001 (approved, expires 03 Jan 2027) is an exception to policy, not a risk
 *  acceptance." (+ " (+n more)"); without B3: " EXC-001 is linked; an exception is not a
 *  risk acceptance." `short` gives the compact form when the tile runs long. */
export function exceptionClause(r: Pick<RiskRecord, "exceptions">, fmt: Fmt, short = false): string {
  const ex = r.exceptions ?? [];
  if (!ex.length) return "";
  const more = ex.length > 1 ? ` (+${ex.length - 1} more)` : "";
  if (short || !hasExceptionDetail(ex)) return ` ${exceptionName(ex[0])}${more} is linked; an exception is not a risk acceptance.`;
  return ` ${exceptionLabel(ex[0], fmt)} is an exception to policy, not a risk acceptance.${more}`;
}

/** Risk acceptance subsection: "EXC-001 (approved, expires 03 Jan 2027) is an exception
 *  to policy, not a risk acceptance." — every linked exception, so none is mistaken for
 *  an acceptance (§5 row 15). Null when none is linked. */
export function exceptionsLine(ex: RiskExceptionRef[] | null | undefined, fmt: Fmt): string | null {
  const items = (ex ?? []).map((x) => exceptionLabel(x, fmt));
  if (!items.length) return null;
  return items.length === 1
    ? `${items[0]} is an exception to policy, not a risk acceptance.`
    : `${joinList(items)} are exceptions to policy, not risk acceptances.`;
}

/** The meta under an exception in Linked records: "Approved · expires 03 Jan 2027" (B3), else nothing. */
export function exceptionMeta(x: RiskExceptionRef, fmt: Fmt): string | null {
  return exceptionStateText(x.status, x.expires_at, fmt);
}

// ------------------------------------------------------------------ control assurance (B2)

/** True when every linked control carries its assurance fields (B2). */
export const hasAssurance = (controls: RiskControlRef[]) =>
  controls.length > 0 && controls.every((c) => typeof c.effectiveness_basis === "string");

/** A rating set by hand or by override, with none, or with no reviewed test on file —
 *  control_assurance.rests_on_untested_rating, which the register's "Not tested" reads. */
export const isUntested = (c: RiskControlRef) =>
  c.effectiveness_basis === "manual" || c.effectiveness_basis === "override" || c.effectiveness_basis === "none" || !(c.audit_count ?? 0);

/** A failed last (reviewed) test, a test overdue, an open audit finding or an open issue:
 *  a superset of what the residual engine withholds credit for, and exactly what the
 *  register's "Control issues" counts (control_assurance.control_health_state). */
export const isFailing = (c: RiskControlRef) =>
  c.last_audit_result === "failed" || !!c.is_audit_overdue || (c.open_finding_count ?? 0) > 0 || (c.open_issue_count ?? 0) > 0;

/** The Controls table's Basis cell. */
export function controlBasisWord(c: RiskControlRef): string {
  switch (c.effectiveness_basis) {
    case "tests": return "From tests";
    case "manual": return "Set by hand";
    case "override": return "Override";
    case "none": return "None";
    default: return "Not shown";
  }
}

/** "set by hand" / "by override" / "from tests" / "no rating", for running text. */
export function controlBasisPhrase(c: RiskControlRef): string {
  switch (c.effectiveness_basis) {
    case "tests": return "from tests";
    case "manual": return "set by hand";
    case "override": return "by override";
    default: return "no rating";
  }
}

/** "A.8.13 Backup & Recovery" (reference and name, cut at `n`). */
export function controlLabel(c: RiskControlRef, n = 60): string {
  const ref = trimmed(c.reference);
  const nm = trimmed(c.name) || trimmed(c.title);
  return truncate(ref && nm ? `${ref} ${nm}` : nm || ref || "A control", n);
}

/** What is wrong with a control, as verb phrases: "failed its last test on 03 Jul 2027". */
function controlProblems(c: RiskControlRef, fmt: Fmt): string[] {
  const out: string[] = [];
  if (c.last_audit_result === "failed") out.push(c.last_audit_date ? `failed its last reviewed test on ${fmt.date(c.last_audit_date)}` : "failed its last reviewed test");
  if (c.is_audit_overdue) out.push(c.next_audit_date ? `has a test overdue since ${fmt.date(c.next_audit_date)}` : "has a test overdue");
  if ((c.open_finding_count ?? 0) > 0) out.push(`has ${plural(c.open_finding_count ?? 0, "open audit finding")}`);
  if ((c.open_issue_count ?? 0) > 0) out.push(`has ${plural(c.open_issue_count ?? 0, "open issue")}`);
  return out;
}

/** The engine's credit lines: "A.8.13: −2 (effective)." → label and rating. */
const CREDIT_LINE = /^(.+?): −\d+ \(([^)]+)\)\.?$/;

/** The controls the suggestion takes credit from: the server's list (B6); else, on an
 *  older API, the controls the engine's own rationale credits ("A.8.13: −2 (effective).",
 *  matched by reference or name, the engine's label), carrying the rating named there
 *  when the ref has none (the older API's controls[] is identity only). */
export function creditedControls(input: RiskInput): RiskControlRef[] {
  const { risk: r, suggestion: s } = input;
  if (!s || s.reduction <= 0) return [];
  if (Array.isArray(s.credited_control_ids)) {
    const ids = new Set(s.credited_control_ids);
    return r.controls.filter((c) => ids.has(c.id));
  }
  const credited = new Map<string, string>();
  for (const line of s.rationale ?? []) {
    const m = CREDIT_LINE.exec(line.trim());
    if (m) credited.set(m[1].trim(), m[2].trim().toLowerCase().replace(/\s+/g, "_"));
  }
  const out: RiskControlRef[] = [];
  for (const c of r.controls) {
    const rating = credited.get(trimmed(c.reference)) ?? credited.get(trimmed(c.name));
    if (rating !== undefined) out.push(c.effectiveness ? c : { ...c, effectiveness: rating });
  }
  return out;
}

/** Whether accepting the suggestion needs the owner's note (B6): the server's answer,
 *  else judged from the assurance fields, else unknown (null) — the refusal then says. */
export function noteRequired(input: RiskInput): boolean | null {
  const s = input.suggestion;
  if (!s) return null;
  if (typeof s.note_required === "boolean") return s.note_required;
  if (!hasAssurance(input.risk.controls)) return null;
  return creditedControls(input).some(isUntested);
}

/** One line per credited control for the Accept form: "A.8.13 Backup & Recovery — rated
 *  effective, set by hand, 0 tests on file". Without B2 the basis is not shown. */
export function creditedControlLines(input: RiskInput): { id: string; text: string; untested: boolean | null }[] {
  const b2 = hasAssurance(input.risk.controls);
  return creditedControls(input).map((c) => {
    const rating = c.effectiveness ? `rated ${sentenceCase(c.effectiveness).toLowerCase()}` : "no rating";
    const text = b2
      ? `${controlLabel(c)}: ${rating}, ${controlBasisPhrase(c)}, ${plural(c.audit_count ?? 0, "reviewed test")} on file`
      : `${controlLabel(c)}: ${rating}`;
    return { id: c.id, text, untested: b2 ? isUntested(c) : null };
  });
}

/** The Assessment table's Suggested-row Basis cell: the engine's reasoning, and — with
 *  B2 — how each credited control's rating was set ("Credit from A.8.13, set by hand"). */
export function suggestedBasis(input: RiskInput): { reasoning: string; credit: string | null } {
  const s = input.suggestion;
  if (!s) return { reasoning: "", credit: null };
  const reasoning = s.rationale.map(noStop).filter(Boolean).join(" · ");
  if (!hasAssurance(input.risk.controls)) return { reasoning, credit: null };
  const credited = creditedControls(input);
  if (!credited.length) return { reasoning, credit: null };
  const parts = credited.map((c) => `${trimmed(c.reference) || controlLabel(c, 40)} (${controlBasisPhrase(c)}${(c.audit_count ?? 0) === 0 ? ", no reviewed test" : ""})`);
  return { reasoning, credit: `Credit from ${joinList(parts)}` };
}

/** The line under the Controls table. With B2 the table says it all, so only a legend
 *  for untested ratings; without it, the spec's note plus the server's health rollup. */
export function controlsNote(r: RiskRecord): string | null {
  if (!r.controls.length) return null;
  if (hasAssurance(r.controls)) {
    const u = r.controls.filter(isUntested).length;
    const pending = r.controls.reduce((n, c) => n + (c.pending_review_count ?? 0), 0);
    const lead = u > 0
      ? `${plural(u, "rating")} rest${u === 1 ? "s" : ""} on no reviewed test. Only tests that were reviewed count here.`
      : "Every rating rests on reviewed tests.";
    return pending > 0
      ? `${lead} ${plural(pending, "test")} awaiting review ${pending === 1 ? "counts" : "count"} once a reviewer decides ${pending === 1 ? "it" : "them"}, for the rating and for residual credit.`
      : lead;
  }
  const base = "Assurance detail isn't available for linked controls yet.";
  if (r.control_health === "issues") return `${base} At least one failed its last reviewed test, is overdue for one, or has an open audit finding or issue.`;
  if (r.control_health === "untested") return `${base} At least one is rated without a reviewed test; none has a failed or overdue test or anything open.`;
  if (r.control_health === "ok") return `${base} Every rating rests on reviewed tests; none has a failed or overdue test or anything open.`;
  return base;
}

// ------------------------------------------------------------------ basis lines

/** Who assessed the inherent scores, and whether a rationale backs them. */
export function inherentBasis(r: RiskRecord, fmt: Fmt, forTable = false): Basis {
  if (isUnscored(r)) return { kind: "missing", text: "Not on file" };
  const why = trimmed(r.assessment_rationale);
  if (r.last_assessed_at && why) {
    const date = fmt.date(r.last_assessed_at);
    const who = personName(r.last_assessed_by_ref);
    return {
      kind: "evidenced",
      text: who ? `Assessed by ${truncate(who, 44 - date.length)} on ${date}` : `Assessed on ${date}, rationale on file`,
    };
  }
  if (r.last_assessed_at) return { kind: "declared", text: `Scored ${fmt.date(r.last_assessed_at)}, no rationale on file` };
  if (why) return { kind: "declared", text: "Rationale on file; no assessor or date" };
  return { kind: "declared", text: forTable ? "No rationale, assessor or date" : "No assessor or rationale on file" };
}

/** The Assessment table's Basis cell for the residual row. */
export function residualBasisText(r: RiskRecord, fmt: Fmt): string {
  if (r.residual_score == null) return "Not recorded";
  const override = trimmed(r.residual_override_reason);
  if (override) return `Override: ${quote(override)}`;
  if (r.residual_accepted_at) return `Accepted suggestion ${fmt.date(r.residual_accepted_at)}`;
  return trimmed(r.assessment_rationale) ? "Recorded with rationale" : "Entered without a rationale";
}

/** "0.2 / yr × PKR 500,000 = PKR 100,000 / yr", or null when not quantified. */
export function quantificationText(r: RiskRecord, fmt: Fmt): string | null {
  const aro = r.annual_loss_frequency;
  const sle = r.single_loss_expectancy;
  if (aro == null || sle == null) return null;
  return `${figure(aro)} / yr × ${fmt.money(sle)}${r.annual_loss_expectancy != null ? ` = ${fmt.money(r.annual_loss_expectancy)} / yr` : ""}`;
}

/** "Annual · last 03 Jul 2026" or "Annual · never reviewed", with " · 2 reviews missed" only when some were.
 *  When the rating requires a shorter cycle than the one set: "Monthly (required for Critical risks) · …". */
export function reviewCycleText(r: RiskRecord, fmt: Fmt): string {
  const reason = trimmed(r.review_frequency_reason);
  const cycle = reason && r.effective_review_frequency ? r.effective_review_frequency : r.review_frequency;
  const word = cycle ? frequencyWord(cycle) : "No cycle";
  const freq = reason ? `${word} (${reason.split(" — ").slice(1).join(" — ") || reason})` : word;
  return `${freq} · ${r.last_review_date ? `last ${fmt.date(r.last_review_date)}` : "never reviewed"}${missedReviewsText(r.expired_reviews)}`;
}

/** The rollup under "Risks below": "3 below in all · worst residual R-014 (12) · …".
 *  A `ref` part is rendered as a link that opens that risk. */
export type RollupRef = { id: string; reference: string; title: string };
export type RollupPart = string | { pre: string; ref: RollupRef; post: string };
export function rollupParts(x: {
  total: number;
  worst_residual: (RollupRef & { residual_score: number | null }) | null;
  worst_exposure: (RollupRef & { exposure: number | null }) | null;
  by_severity: Record<string, number>;
  breaches: number;
}): RollupPart[] {
  const parts: RollupPart[] = [`${x.total} below in all`];
  if (x.worst_residual) parts.push({ pre: "worst residual ", ref: x.worst_residual, post: ` (${x.worst_residual.residual_score ?? "not recorded"})` });
  if (x.worst_exposure) parts.push({ pre: "worst exposure ", ref: x.worst_exposure, post: x.worst_exposure.exposure != null ? ` (${x.worst_exposure.exposure})` : "" });
  parts.push((["critical", "high", "medium", "low"] as const).map((b) => `${x.by_severity[b] ?? 0} ${b}`).join(", "));
  if (x.breaches > 0) parts.push(`${x.breaches} above tolerance`);
  return parts;
}

// ------------------------------------------------------------------ tiles

const sevValue = (sev: string | null, score: number | null): TileValue =>
  sev ? { text: sentenceCase(sev), tone: sevTone(sev), badge: true, num: String(score) } : { text: `Score ${score}` };

/** The six summary tiles, in the order of record-page-spec §4.1. */
export function riskTiles(input: RiskInput, ctx: Ctx): TileModel[] {
  const { risk: r, suggestion: s, matrixSize: m, impactMode } = input;
  const { fmt, now } = ctx;
  const unscored = isUnscored(r);
  const hasResidual = r.residual_score != null;
  const measured = hasResidual ? r.residual_score : r.inherent_score;
  const basisWord = hasResidual ? "residual" : "inherent";
  const target = r.target_score != null ? String(r.target_score) : "not set";
  const reduces = !!s && !unscored && r.inherent_score != null && s.score < r.inherent_score;
  const verdict = appetiteVerdict(r);

  // 1. Inherent risk
  const dims = (r.impact_dimensions ?? []).filter((d) => d.basis === "inherent").length;
  const inherent: TileModel = unscored
    ? {
        key: "inherent", label: "Inherent risk", section: "assessment",
        value: { text: "Not scored", tone: "hollow" },
        because: ["Draft saved without scores; inherent likelihood and impact are needed before it can leave Draft."],
        basis: inherentBasis(r, fmt),
      }
    : {
        key: "inherent", label: "Inherent risk", section: "assessment",
        value: sevValue(r.inherent_severity, r.inherent_score),
        because: [
          "Likelihood ", { b: String(r.inherent_likelihood) }, " × impact ", { b: String(r.inherent_impact) },
          ` on the ${m}×${m} matrix, before controls.`,
          ...(dims > 0 ? [` Impact is the ${impactMode === "average" ? "average" : "worst"} of ${plural(dims, "scored dimension")}.`] : []),
        ],
        basis: inherentBasis(r, fmt),
      };

  // 2. Residual risk
  let residual: TileModel;
  if (hasResidual) {
    const li = `L${r.residual_likelihood} × I${r.residual_impact}`;
    const nowSuggests: Seg[] = s && !s.matches_current ? [" Controls now suggest ", { b: String(s.score) }, "."] : [];
    const value = sevValue(r.residual_severity, r.residual_score);
    const override = trimmed(r.residual_override_reason);
    const sl = r.suggested_residual_likelihood;
    const si = r.suggested_residual_impact;
    residual = override
      ? {
          key: "residual", label: "Residual risk", section: "assessment", value,
          because: firstFit(
            [`${li}, ${sl && si ? `differs from the suggested ${sl}×${si}` : "recorded with an override"}: ${quote(override)}.`, ...nowSuggests],
            [`${li}, ${sl && si ? `differs from the suggested ${sl}×${si}` : "recorded with an override"}: ${quote(override, 40)}.`],
          ),
          basis: { kind: "declared", text: "Owner's judgement, reason on file" },
        }
      : {
          key: "residual", label: "Residual risk", section: "assessment", value,
          because: [
            `${li}${r.residual_accepted_at ? `, accepted from the control-based suggestion on ${fmt.date(r.residual_accepted_at)}` : ""}. Target ${target}.`,
            ...nowSuggests,
          ],
          basis: trimmed(r.assessment_rationale)
            ? { kind: "evidenced", text: "Recorded with rationale" }
            : { kind: "declared", text: "Entered without a rationale" },
        };
  } else {
    let because: Seg[];
    if (unscored) because = ["No residual yet: the inherent risk has to be scored first."];
    else if (!s) because = [`No residual recorded yet. Target ${target}.`];
    else if (reduces)
      because = [
        "Suggested ", { b: String(s.score) },
        ` (${s.likelihood}×${s.impact}) from control credit: ${truncate(noStop(s.rationale[0] ?? ""), 70)}. Target ${target}.`,
      ];
    else because = [`No linked control earns credit, so the suggestion equals inherent ${r.inherent_score}.`];
    residual = {
      key: "residual", label: "Residual risk", section: "assessment",
      value: { text: "Not recorded", tone: "hollow" },
      because,
      basis: { kind: "missing", text: "Awaiting the owner's judgement" },
    };
  }

  // 3. Against appetite
  let appetiteTile: TileModel;
  if (!verdict) {
    appetiteTile = {
      key: "appetite", label: "Against appetite", section: "assessment",
      value: { text: "Not measured", tone: "hollow" },
      because: [unscored ? "Nothing to measure yet: the inherent likelihood and impact aren't chosen." : "No appetite or tolerance applies to this risk yet."],
      basis: { kind: "missing", text: unscored ? "No scores to measure" : "No thresholds on file" },
    };
  } else {
    const head = (short: boolean): Seg[] => [
      `Measured on ${basisWord} `, { b: String(measured) },
      ...(hasResidual ? [] : [" because no residual is recorded"]),
      `; appetite ${r.appetite_score ?? "not set"}, tolerance `, { b: String(r.tolerance_score ?? "not set") },
      ` (${appetiteScope(r, short)}).`,
    ];
    const projected = !hasResidual && s && reduces ? suggestedAppetite(s, r) : null;
    const tail: Seg[] = projected && s ? [` At the suggested ${s.score} it would be ${APPETITE_WORD[projected]}.`] : [];
    const marks: ScaleModel["marks"] = [];
    if (r.inherent_score != null) marks.push({ score: r.inherent_score, kind: "inherent", dim: hasResidual });
    if (hasResidual && measured != null) marks.push({ score: measured, kind: "residual" });
    else if (s && reduces) marks.push({ score: s.score, kind: "suggested" });
    if (r.target_score != null) marks.push({ score: r.target_score, kind: "target" });
    appetiteTile = {
      key: "appetite", label: "Against appetite", section: "assessment",
      value: { text: APPETITE_WORD[verdict], tone: APPETITE_TONE[verdict], badge: true },
      because: firstFit([...head(false), ...tail], [...head(true), ...tail], head(true)),
      basis: { kind: "derived", text: "Calculated from score and thresholds" },
      scale:
        r.appetite_score != null && r.tolerance_score != null
          ? { max: m * m, appetite: r.appetite_score, tolerance: r.tolerance_score, marks }
          : undefined,
    };
  }

  // 4. Control reliance — never a green "OK".
  const reliance = relianceTile(r, fmt);

  // 5. Exposure (ALE)
  const ale = r.annual_loss_expectancy;
  const aro = r.annual_loss_frequency;
  const exposure: TileModel =
    ale != null
      ? {
          key: "exposure", label: "Exposure (ALE)", section: "assessment",
          value: { text: fmt.money(ale), unit: "/ year" },
          because: [
            aro != null && r.single_loss_expectancy != null
              ? `${figure(aro)} ${aro === 1 ? "event" : "events"} a year × ${fmt.money(r.single_loss_expectancy)} per event. A money measure, separate from the matrix score.`
              : "A money measure, separate from the matrix score.",
          ],
          basis: { kind: "derived", text: "Calculated: frequency × single loss" },
        }
      : {
          key: "exposure", label: "Exposure (ALE)", section: "assessment",
          value: { text: "Not quantified", tone: "hollow" },
          because: ["Add loss frequency and single-loss value (Edit → Assessment) to estimate it."],
          basis: { kind: "missing", text: "Not on file" },
        };

  // 6. Risk acceptance
  const acc = acceptanceView(r, now);
  const ex = exceptionClause(r, fmt);
  const exShort = exceptionClause(r, fmt, true);
  let acceptance: TileModel;
  if (acc.inForce) {
    const a = acc.inForce;
    const why = trimmed(a.rationale);
    const lead = (n: number | null) => `Approved${a.decided_at ? ` on ${fmt.date(a.decided_at)}` : ""}${why && n ? `: ${quote(why, n)}` : ""}.`;
    acceptance = {
      key: "acceptance", label: "Risk acceptance", section: "assessment",
      value: { text: "In force", tone: "low", badge: true, unit: a.expires_at ? `until ${fmt.date(a.expires_at)}` : "no expiry" },
      because: firstFit([`${lead(60)}${ex}`], [`${lead(60)}${exShort}`], [`${lead(null)}${exShort}`]),
      basis: { kind: "evidenced", text: "Decision on file" },
    };
  } else if (acc.pending) {
    const lead = `Requested ${fmt.date(acc.pending.created_at)}; needs a second approver.`;
    acceptance = {
      key: "acceptance", label: "Risk acceptance", section: "assessment",
      value: { text: "Awaiting approval", tone: "medium", badge: true },
      because: firstFit([`${lead}${ex}`], [`${lead}${exShort}`]),
      basis: { kind: "declared", text: "Requested, not decided" },
    };
  } else if (acc.lapsed) {
    const d = acc.lapsed.expires_at ? fmt.date(acc.lapsed.expires_at) : "";
    const tail =
      verdict === "breach" ? " Above tolerance, so a fresh decision is needed."
      : verdict === "elevated" ? " Above appetite; renewing is optional."
      : verdict === "within_appetite" ? " Within appetite; no renewal needed."
      : "";
    const lead = `The last acceptance lapsed${d ? ` on ${d}` : ""}.${tail}`;
    acceptance = {
      key: "acceptance", label: "Risk acceptance", section: "assessment",
      value: { text: d ? `Lapsed ${d}` : "Lapsed", tone: "high", badge: true },
      because: firstFit([`${lead}${ex}`], [`${lead}${exShort}`]),
      basis: { kind: "missing", text: "No decision on file" },
    };
  } else {
    const lead =
      verdict === "breach" ? "Above tolerance with no formal acceptance."
      : verdict === "elevated" ? "Above appetite, within tolerance; acceptance is optional."
      : verdict === "within_appetite" ? "Within appetite; no acceptance needed."
      : "No acceptance on file.";
    acceptance = {
      key: "acceptance", label: "Risk acceptance", section: "assessment",
      value: { text: "Not accepted", tone: "hollow" },
      because: firstFit([`${lead}${ex}`], [`${lead}${exShort}`]),
      basis: { kind: "missing", text: "No decision on file" },
    };
  }

  return [inherent, residual, appetiteTile, reliance, exposure, acceptance];
}

/** Tile 4: how far the linked controls' ratings can be trusted (B2), or the spec's
 *  degrade path when the API does not send the assurance fields. */
function relianceTile(r: RiskRecord, fmt: Fmt): TileModel {
  const base = { key: "reliance", label: "Control reliance", section: "controls" } as const;
  const n = r.controls.length;
  if (n === 0) {
    return {
      ...base,
      value: { text: "No controls", tone: "hollow" },
      because: ["No controls linked, so nothing can reduce the residual."],
      basis: { kind: "missing", text: "No controls linked" },
    };
  }
  if (!hasAssurance(r.controls)) {
    return {
      ...base,
      value: { text: plural(n, "control"), unit: r.control_health === "issues" ? "with issues" : r.control_health === "untested" ? "not tested" : undefined },
      because: ["Assurance detail isn't available here; open each control."],
      basis: { kind: "missing", text: "Basis not shown" },
    };
  }
  const untested = r.controls.filter(isUntested).length;
  const failing = r.controls.filter(isFailing).length;
  const basis: Basis = untested > 0
    ? { kind: "declared", text: "Untested rating relied on" }
    : { kind: "evidenced", text: "From reviewed tests" };
  const value: TileValue = { text: plural(n, "control"), unit: failing > 0 ? `${failing} with issues` : undefined };
  if (n === 1) {
    const c = r.controls[0];
    const pending = c.pending_review_count ?? 0;
    const tests = `${plural(c.audit_count ?? 0, "reviewed test")} on file${pending ? `, ${pending} more awaiting review` : ""}.`;
    const rated: Seg[] =
      c.effectiveness_basis === "none" || !c.effectiveness || c.effectiveness === "not_assessed"
        ? [" has no rating; ", tests]
        : [
            ` is rated ${sentenceCase(c.effectiveness)} `,
            c.effectiveness_basis === "manual" ? { b: "by hand" }
              : c.effectiveness_basis === "override" ? "by override"
              : "from reviewed tests",
            `; ${tests}`,
          ];
    const problems = controlProblems(c, fmt);
    const ref = trimmed(c.reference) || "It";
    const clean = c.open_issue_count == null
      ? " No failed or overdue test, no open audit finding."
      : " No failed or overdue test, no open issue or audit finding.";
    const tail = problems.length ? ` ${ref} ${joinList(problems)}.` : clean;
    return {
      ...base, value, basis,
      because: firstFit([controlLabel(c, 40), ...rated, tail], [trimmed(c.reference) || controlLabel(c, 24), ...rated, tail]),
    };
  }
  const effective = r.controls.filter((c) => c.effectiveness === "effective").length;
  return {
    ...base, value, basis,
    because: [`${effective} of ${n} effective; ${untested} rated without tests; ${failing} with issues.`],
  };
}

// ------------------------------------------------------------------ open points

/** Gaps first, then notes, each in the rule order of §4.1. Every fix only scrolls,
 *  focuses, opens Edit on a tab or opens a form — none changes state. */
export function riskOpenPoints(input: RiskInput, ctx: Ctx): OpenPoint[] {
  const { risk: r, suggestion: s } = input;
  const { fmt, now, gov } = ctx;
  const gaps: OpenPoint[] = [];
  const notes: OpenPoint[] = [];
  const verdict = appetiteVerdict(r);
  const acc = acceptanceView(r, now);
  const canAttest = gov.attestation?.canAttest !== false;
  const why = trimmed(r.assessment_rationale);

  // F-21: a risk leaves Draft only with an owner and a business unit; both points say so.
  const draft = r.status === "draft";
  if (!r.owner_id)
    gaps.push({
      id: "risk.owner", level: "gap",
      text: [draft ? "No risk owner: it can't leave Draft, and accountability can't be shown." : "No risk owner: accountability can't be shown."],
      action: { kind: "edit", target: "general", label: "Assign owner" },
    });
  if (Array.isArray(r.business_units) && r.business_units.length === 0)
    gaps.push({
      id: "risk.business_unit", level: "gap",
      text: [draft ? "No business unit: it can't leave Draft, and no segment reports it." : "No business unit: no segment reports this risk."],
      action: { kind: "edit", target: "links", label: "Add business unit" },
    });

  if (ASSESSED_STATUSES.has(r.status) && (!why || !r.last_assessed_at)) {
    const st = sentenceCase(r.status);
    const text = !why && !r.last_assessed_at
      ? `Status is ${st} but no assessment is on file (no rationale, assessor or date).`
      : !why
        ? `Status is ${st} but the assessment has no rationale on file.`
        : `Status is ${st} but no assessor or date is on file for the assessment.`;
    gaps.push({ id: "risk.assessed_without_assessment", level: "gap", text: [text], action: { kind: "section", target: "assessment", label: "Open assessment" } });
  }

  if (verdict === "breach" && !acc.inForce && (r.treatment_progress?.open ?? 0) === 0)
    gaps.push({
      id: "risk.breach_untreated", level: "gap",
      text: ["Above tolerance with no accepted risk and no open treatment action."],
      action: { kind: "open", target: "add-action", label: "Add action" },
    });

  // Needs the assurance fields on control refs (B2): not raised without them.
  if (hasAssurance(r.controls) && ((s?.reduction ?? 0) > 0 || r.residual_score != null)) {
    const credited = creditedControls(input).filter(isUntested);
    if (credited.length) {
      const first = credited[0];
      const refs = joinList(credited.map((c) => trimmed(c.reference) || controlLabel(c, 40)));
      gaps.push({
        id: "risk.untested_credit", level: "gap",
        text: [`Residual credit rests on an untested rating: ${refs}.`],
        action: { kind: "href", target: `/controls?id=${first.id}`, label: `Open ${trimmed(first.reference) || "control"}` },
      });
    }
  }

  if (r.next_review_date && daysFrom(r.next_review_date, now) < 0)
    gaps.push({
      id: "risk.review_overdue", level: "gap",
      text: [`Review overdue since ${fmt.date(r.next_review_date)}.`],
      action: canAttest ? { kind: "attest", target: "attest", label: "Attest…" } : undefined,
    });

  if (acc.inForce?.expires_at) {
    const left = daysFrom(acc.inForce.expires_at, now);
    if (left >= 0 && left <= 30)
      gaps.push({
        id: "risk.acceptance_lapsing", level: "gap",
        text: [`Acceptance lapses on ${fmt.date(acc.inForce.expires_at)}.`],
        action: acc.pending ? undefined : { kind: "open", target: "request-acceptance", label: "Request renewal" },
      });
  }

  if (acc.lapsed && verdict === "breach")
    gaps.push({
      id: "risk.acceptance_lapsed", level: "gap",
      text: [`Acceptance lapsed${acc.lapsed.expires_at ? ` on ${fmt.date(acc.lapsed.expires_at)}` : ""}; the breach is no longer accepted.`],
      action: acc.pending ? undefined : { kind: "open", target: "request-acceptance", label: "Request acceptance" },
    });

  const state = gov.workflowState;
  if ((state === "approved" || state === "in_review" || state === "retired") && gov.approvalSteps === 0)
    gaps.push({
      id: "risk.approved_without_step", level: "gap",
      text: [approvalWithoutStepText(gov, APPROVAL_STATE_WORD[state])],
      action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
    });

  if (r.status !== "draft" && state === "draft")
    notes.push({
      id: "risk.not_submitted", level: "note",
      text: [`${sentenceCase(r.status)} but not submitted for approval`],
      action: { kind: "focus", target: "rec-primary", label: "Submit for review" },
    });
  if (state !== null && state !== "draft" && gov.attestation?.status === "never")
    notes.push({ id: "risk.never_attested", level: "note", text: ["Never attested"], action: canAttest ? { kind: "attest", target: "attest", label: "Attest…" } : undefined });
  if (r.treatment_strategy === "mitigate" && (r.treatment_progress?.total ?? 0) === 0)
    notes.push({ id: "risk.mitigate_no_actions", level: "note", text: ["Mitigate with no actions"], action: { kind: "open", target: "add-action", label: "Add action" } });
  if (r.target_score == null)
    notes.push({ id: "risk.no_target", level: "note", text: ["No target set"], action: { kind: "edit", target: "assessment", label: "Set target" } });

  return [...gaps, ...notes];
}

// ------------------------------------------------------------------ headline

/** The reliance clause of the headline (§4.1). */
function relianceClause(r: RiskRecord): string {
  const n = r.controls.length;
  if (n === 0) return "no control linked";
  if (!hasAssurance(r.controls)) return plural(n, "linked control");
  const untested = r.controls.filter(isUntested);
  const failing = r.controls.filter(isFailing).length;
  if (n === 1 && untested.length) {
    return untested[0].effectiveness_basis === "override"
      ? "its only control's rating is an override"
      : "its only control is rated by hand with no tests";
  }
  if (n > 1 && untested.length) return `${untested.length} of ${n} controls are rated without tests`;
  if (failing > 0) return `${failing} of ${n} controls ${failing === 1 ? "has" : "have"} a failed or overdue test`;
  return n === 1 ? "its only control is tested" : `all ${n} controls are tested`;
}

/** One sentence: "Breach on inherent 20 — no residual recorded; its only control is rated by hand with no tests; no owner." */
export function riskHeadline(input: RiskInput, _ctx: Ctx): Seg[] {
  const { risk: r } = input;
  const verdict = appetiteVerdict(r);
  const unscored = isUnscored(r);
  const hasResidual = r.residual_score != null;
  const segs: Seg[] = [];
  if (verdict) segs.push(`${APPETITE_WORD[verdict]} on ${hasResidual ? "residual" : "inherent"} `, { b: String(hasResidual ? r.residual_score : r.inherent_score) });
  else segs.push(unscored ? "Not scored yet" : "Not measured against appetite");
  if (!hasResidual && !unscored) segs.push(" — no residual recorded");
  segs.push(`; ${relianceClause(r)}`);
  if (!r.owner_id) segs.push("; no owner");
  segs.push(".");
  return segs;
}
