/* The control record's wording (record-page-spec §4.2, §5 rows 2, 5, 9, 17–19).

   Every judgement the control record states in words lives here and nowhere else: the
   headline, the six summary tiles, the open points, and the copy the page prints around
   them (the header's Source / Next-test items, the section sub-lines and empty lines,
   the effectiveness notes, how a linked exception and a test are named). Wording changes
   update the fixtures in lib/record/__fixtures__/control-*.json and need a Compliance
   reviewer (§3.8).

   Pure functions of plain record data — the payload of GET /controls/{id}, its tests
   (GET /controls/{id}/audits), its maintenance log (GET /controls/{id}/maintenances), the
   suggested-clause count, and the governance slice `ctx.gov` — so `npm run
   check:record-copy` runs them under Node. No React, no DOM, no fetching. Server
   judgements (effectiveness, its basis, the overdue flags, can_attest) are explained
   here, never recomputed.

   Backend fields read defensively (an older API omits them, and the copy degrades):
   - B7 `requirements[].framework`: the header's "Source" item and the reliance tile name
     the framework. Absent → the stored classification keeps its own label, and the tile
     names the clause alone. Never a guess from the reference.
   - B3 `exceptions[].status` / `expires_at`: the exception's state and expiry. Absent →
     the chip alone.
   - B1 `can_attest` / `blocked_reason` (via `ctx.gov.attestation`): the "Never attested"
     note offers Attest only when the server allows it and says why not otherwise.
     Absent → the action stays and the attest call's refusal shows inline.
   - B10b import backfill (`ctx.gov.lastStep.action === "import"`): the approval gap says
     "Imported as approved, no approver recorded" — nobody is named.
   - Decision 7 (2026-09-17) `tested_count` / `reviewed_audit_count` / `last_reviewed_*`:
     "tested" means signed off by a reviewer. The headline, the Testing tile and the
     untested gap read reviewed tests only and show tests awaiting review beside them
     ("1 test awaiting review"). Absent (older API) → the test log's count and result,
     worded "on file", never "reviewed".
   - Decision 6 (2026-09-17): attesting needs a complete approval. While the approval is
     draft or in review the note asks for the approval instead of offering Attest. */

import { htmlToText } from "@/lib/sanitize";
import { attestationNotePoint, cadenceNoun, exceptionStateText, importedApprovalText, joinList, plural, quote, segsText, sentenceCase, textOnlyPerson, truncate } from "./text";
import type { Basis, Ctx, Fmt, OpenPoint, Seg, TileModel, TileValue } from "./types";

/* ------------------------------------------------------------------ input types */

export type ControlPerson = { full_name?: string | null; email?: string | null };
export type ControlLink = { id: string; reference?: string | null; title?: string | null; name?: string | null };
/** A linked clause. `framework` / `framework_id` arrive with B7. */
export type ControlRequirementRef = ControlLink & { framework?: string | null; framework_id?: string | null };
/** A linked exception. `status` (approved past expiry reads "expired") and `expires_at` arrive with B3. */
export type ControlExceptionRef = ControlLink & { status?: string | null; expires_at?: string | null };

/** The fields of GET /controls/{id} the rules read. */
export type ControlRecord = {
  reference: string;
  name: string;
  objective: string;
  description: string;
  /** Legacy free-text owner ("CISO"), shown only while no owner is picked. */
  owner: string;
  owner_id: string | null;
  owner_ref?: ControlPerson | null;
  operator_id: string | null;
  operator_ref?: ControlPerson | null;
  classification: string;
  classification_ref?: { label: string; path?: string } | null;
  /** planned | implemented | operational | retired */
  status: string;
  is_key: boolean;
  effectiveness: string;
  design_effectiveness: string;
  operating_effectiveness: string;
  /** tests | override | manual | none */
  effectiveness_basis: string;
  effectiveness_override_reason: string;
  open_issues: ControlLink[];
  /** True when an open issue lowered the operating rating (server; optional on an older
   *  API, which then gets the "at best" wording). */
  operating_capped?: boolean;
  pending_review_count: number;
  test_procedure: string;
  evidence_expected: string;
  audit_frequency: string;
  maintenance_frequency: string;
  next_audit_date: string | null;
  last_audit_date: string | null;
  next_maintenance_date: string | null;
  last_maintenance_date: string | null;
  /** The test log: every test on file ("tests recorded"), and the newest one's result
   *  (reviewed or not). The Tests tab only — never read as assurance. */
  audit_count: number;
  /** Decision 7: reviewed tests (= `reviewed_audit_count`). Optional: older API. */
  tested_count?: number;
  last_audit_result: string | null;
  /** What ratings and risk credit read: tests that count (reviewed, or recorded before
   *  reviews existed). The same view a risk sees on this control (B2). Optional: older API. */
  reviewed_audit_count?: number;
  last_reviewed_result?: string | null;
  last_reviewed_date?: string | null;
  is_audit_overdue: boolean;
  maintenance_count: number;
  last_maintenance_result: string | null;
  is_maintenance_overdue: boolean;
  requirements: ControlRequirementRef[];
  risks: ControlLink[];
  exceptions?: ControlExceptionRef[];
};

/** The fields of one GET /controls/{id}/audits row the rules read. */
export type ControlTestRecord = {
  result: string;
  test_type: string | null;
  conducted_date: string | null;
  created_at: string;
  /** pending | reviewed | returned | legacy (recorded before reviews existed) */
  review_status: string;
  reviewed_by_ref?: ControlPerson | null;
  reviewed_at: string | null;
  evidence: ControlLink[];
};

export type ControlMaintenanceRecord = { id: string; result: string; task: string; conducted_date: string | null };

/** One continuous-monitoring test of the control (GET /ccm/controls/{id}/monitoring). */
export type ControlMonitoringTest = {
  id: string;
  reference: string;
  name: string;
  check_label: string;
  status: string;
  last_result: string;
  last_run: string | null;
  failing_since: string | null;
  last_error: string;
  recent_runs: number;
  recent_pass_rate: number | null;
  overdue: boolean;
  issue_reference?: string | null;
};
/** Phase 4D: the control's continuous monitoring. `state` is not_monitored | paused |
 *  not_run | passing | failing | error | overdue (server). */
export type ControlMonitoring = {
  state: string;
  failing_since: string | null;
  recent_runs: number;
  recent_pass_rate: number | null;
  tests: ControlMonitoringTest[];
};

export type ControlInput = {
  control: ControlRecord;
  tests: ControlTestRecord[];
  maints: ControlMaintenanceRecord[];
  /** Suggested clauses from the installed frameworks; null until known. */
  suggestionCount: number | null;
  /** Continuous monitoring; absent or null until loaded (and on an older API). */
  monitoring?: ControlMonitoring | null;
};

/* ------------------------------------------------------------------ vocabulary */

/** Implemented or operational: the control runs, so it has test and maintenance clocks. */
export const LIVE_STATUSES: ReadonlySet<string> = new Set(["implemented", "operational"]);
/** Planned and retired controls carry no test clock (the server never schedules one). */
export const UNTESTABLE_STATUSES: ReadonlySet<string> = new Set(["planned", "retired"]);

export const CONTROL_STATUS_TONE: Readonly<Record<string, "low" | "info" | "neutral">> = {
  operational: "low",
  implemented: "info",
  planned: "neutral",
  retired: "neutral",
};
export const EFFECTIVENESS_TONE: Readonly<Record<string, "low" | "medium" | "critical">> = {
  effective: "low",
  partially_effective: "medium",
  ineffective: "critical",
};
/** Conclusive results only; "not_assessed" has no tone. */
export const RESULT_TONE: Readonly<Record<string, "low" | "medium" | "critical">> = {
  passed: "low",
  passed_with_exceptions: "medium",
  failed: "critical",
};
export const TEST_RESULT_LABEL: Readonly<Record<string, string>> = {
  passed: "Passed",
  passed_with_exceptions: "Passed with exceptions",
  failed: "Failed",
  not_assessed: "Not assessed",
};
export const TEST_REVIEW_LABEL: Readonly<Record<string, string>> = {
  pending: "Pending review",
  reviewed: "Reviewed",
  returned: "Returned",
  legacy: "Before reviews",
};

export const CONTROL_LIFECYCLE_HINT = "Planned, Implemented, Operational or Retired. Tests are scheduled only once implemented.";
export const CONTROL_OWNER_HINT = "Tests, issues and attestation requests route here.";
export const CONTROL_OPERATOR_HINT = "Runs the control day to day.";
export const CONTROL_SOURCE_HINT = "Where this control comes from. Its classification is not recorded.";
/** OpenPoints `clearText`. */
export const CONTROL_CLEAR_TEXT = "No open points: owner, operator, procedure, tests and approval are on file.";
export const TESTS_REVIEW_NOTE = "A test counts as a test — and changes the rating — only once someone other than its tester approves it. Tests awaiting review are listed here and counted apart.";

/** How the combined rating came about, in one sentence (the effectiveness line and the register tooltip). */
export const EFFECTIVENESS_BASIS_NOTE: Readonly<Record<string, string>> = {
  tests: "Derived from the latest reviewed design and operating tests (the worse of the two).",
  override: "Set by hand — see the reason below. The next approved test replaces it.",
  manual: "Rated by hand before ratings were derived from tests; kept until the first reviewed test.",
  none: "Not assessed: no reviewed test yet.",
};

/** The Combined row's "From" cell in the effectiveness breakdown. */
export function combinedFromText(basis: string | null | undefined): string {
  if (basis === "override") return "Override, set by hand";
  if (basis === "manual") return "Set by hand before ratings came from tests";
  if (basis === "tests") return "The worse of design and operating";
  return "No reviewed test";
}

/** The one-line effectiveness note when design, operating and combined agree. */
export function effectivenessNote(basis: string | null | undefined): string {
  return basis === "none" || !basis ? "No reviewed test yet." : EFFECTIVENESS_BASIS_NOTE[basis] ?? "";
}

/** The open-issue cap, before the issue chips. */
export function issueCapText(n: number): string {
  return `${n === 1 ? "An open issue holds" : "Open issues hold"} the operating rating at partially effective at best until closed:`;
}

const FREQ_ADVERB: Record<string, string> = {
  fortnightly: "Every two weeks",
  monthly: "Monthly",
  quarterly: "Quarterly",
  semiannual: "Twice a year",
  annual: "Annually",
};
/** How often a cycle runs, as a label: "Annually", "Quarterly"; "" for none / unset. */
export function cadence(freq: string | null | undefined): string {
  return FREQ_ADVERB[freq ?? ""] ?? "";
}
/** A cycle as a fact value: "Annually", "No cycle", or null when unset. */
export function cycleFact(freq: string | null | undefined): string | null {
  if (freq === "none") return "No cycle";
  return cadence(freq) || null;
}

export const NO_TEST_CLOCK: Readonly<Record<string, string>> = {
  planned: "No test scheduled until the control is implemented",
  retired: "Retired — no further tests scheduled",
};
export const NO_MAINTENANCE_CLOCK: Readonly<Record<string, string>> = {
  planned: "No maintenance scheduled until the control is implemented",
  retired: "Retired — no further maintenance scheduled",
};

/* ------------------------------------------------------------------ small helpers */

const ISO_THEME: Record<string, string> = { "5": "Organisational", "6": "People", "7": "Physical", "8": "Technological" };
const HEADLINE_BASIS: Record<string, string> = {
  tests: " from reviewed tests",
  override: " by override",
  manual: ", set by hand",
  none: " — no reviewed test",
};
const APPROVAL_STATE_WORD: Record<string, string> = { in_review: "in review", approved: "approved", retired: "retired" };
const BECAUSE_MAX = 160;

/** "partially_effective" → "partially effective" (a rating inside a sentence). */
export function ratingWord(v: string | null | undefined): string {
  return sentenceCase(v || "not_assessed").toLowerCase();
}
export function isRated(v: string | null | undefined): boolean {
  return !!v && v !== "not_assessed";
}
const refText = (x: ControlLink) => (x.reference || x.title || x.name || "").trim();
/** `name(u)`: full name, else e-mail. */
export function personName(u: ControlPerson | null | undefined, fallback?: string | null): string {
  return ((u ? u.full_name || u.email : "") || fallback || "").trim();
}
const hasCycle = (freq: string | null | undefined) => !!freq && freq !== "none";
const trimmed = (s: string | null | undefined) => (s ?? "").trim();

/** Up to `n` references: "a, b and c", or "a, b, c and 2 more". */
function refList(items: ControlLink[], n = 3): string {
  const refs = items.map(refText).filter(Boolean);
  const shown = refs.slice(0, n);
  const more = refs.length - shown.length;
  return more > 0 ? `${shown.join(", ")} and ${more} more` : joinList(shown);
}

/** The first variant that fits a because-line (≤ 160 characters); the last one otherwise. */
function fit(variants: Seg[][]): Seg[] {
  return variants.find((v) => segsText(v).length <= BECAUSE_MAX) ?? variants[variants.length - 1];
}

/** When a test happened: the date performed, then when it was recorded. */
const whenOf = (t: ControlTestRecord) => `${t.conducted_date ?? (t.created_at ?? "").slice(0, 10)}|${t.created_at ?? ""}`;

/** The newest test by date performed (then recorded). */
export function newestTest<T extends ControlTestRecord>(tests: readonly T[]): T | null {
  return tests.reduce<T | null>((best, t) => (!best || whenOf(t) > whenOf(best) ? t : best), null);
}

/** The newest test of one kind that decides a rating (reviewed or legacy, conclusive):
 *  the test the server's design / operating rating comes from (services/control_assurance). */
export function latestCounting<T extends ControlTestRecord>(tests: readonly T[], kind: "design" | "operating"): T | null {
  return newestTest(
    tests.filter(
      (t) =>
        (t.review_status === "reviewed" || t.review_status === "legacy") &&
        RESULT_TONE[t.result] !== undefined &&
        (t.test_type === "design" ? "design" : "operating") === kind,
    ),
  );
}

/** A test as the record and the evidence register name it: "Operating test of 03 Jul 2026". */
export function controlTestTitle(t: { test_type?: string | null; conducted_date?: string | null }, fmt: Pick<Fmt, "date">): string {
  const kind = t.test_type ? `${sentenceCase(t.test_type)} test` : "Test";
  return t.conducted_date ? `${kind} of ${fmt.date(t.conducted_date)}` : kind;
}

/** Where a design or operating rating comes from (the breakdown's "From" cell); null when no test decides it. */
export function testFromText(t: ControlTestRecord | null, fmt: Fmt): string | null {
  if (!t) return null;
  const when = fmt.date(t.conducted_date || t.created_at);
  return t.review_status === "legacy"
    ? `${when} test · recorded before reviews`
    : `${when} test · reviewed by ${personName(t.reviewed_by_ref) || "an independent reviewer"}`;
}

/* ------------------------------------------------------------------ header copy */

/** The picked classification ("Parent › Child"), else the legacy text. */
export function classificationText(c: Pick<ControlRecord, "classification" | "classification_ref">): string {
  return c.classification_ref ? c.classification_ref.path || c.classification_ref.label : c.classification || "";
}

/** Header meta #5 (spec §4.2, §5 row 2): the control's source when the stored
 *  classification is the framework it was installed from, or there is none and a linked
 *  clause names its framework (B7). Null without B7 — never a guess from the reference. */
export function controlSource(
  c: Pick<ControlRecord, "classification" | "classification_ref" | "requirements" | "reference">,
): { framework: string; theme: string } | null {
  const cls = classificationText(c).trim().toLowerCase();
  const named = (c.requirements ?? []).filter((r) => trimmed(r.framework));
  const hit = cls ? named.find((r) => trimmed(r.framework).toLowerCase() === cls) : named[0];
  if (!hit) return null;
  const framework = trimmed(hit.framework);
  const m = /27001/.test(framework) ? /^A\.([5-8])\./.exec(c.reference || "") : null;
  return { framework, theme: m ? ISO_THEME[m[1]] : "" };
}

/** Header meta #5 as label, value and hint: "Source · ISO/IEC 27001:2022 · Organisational",
 *  or "Classification · Technical" (null value = "Not set"). */
export function controlSourceMeta(
  c: Pick<ControlRecord, "classification" | "classification_ref" | "requirements" | "reference">,
): { label: "Source" | "Classification"; value: string | null; hint?: string } {
  const src = controlSource(c);
  if (src) return { label: "Source", value: src.theme ? `${src.framework} · ${src.theme}` : src.framework, hint: CONTROL_SOURCE_HINT };
  return { label: "Classification", value: classificationText(c) || null };
}

/** A genuine classification to show in Design when the header shows the source instead; null otherwise. */
export function designClassification(
  c: Pick<ControlRecord, "classification" | "classification_ref" | "requirements" | "reference">,
): string | null {
  const src = controlSource(c);
  const cls = classificationText(c).trim();
  return src && cls && cls.toLowerCase() !== src.framework.toLowerCase() ? cls : null;
}

/** Header meta #6 "Next test". `badge` renders the text as a high badge; `muted` as muted text. */
export function controlNextTest(
  c: Pick<ControlRecord, "status" | "is_audit_overdue" | "next_audit_date" | "audit_frequency">,
  fmt: Fmt,
): { text: string; sub?: string; badge?: boolean; muted?: boolean } {
  if (c.status === "planned") return { text: "Not scheduled", sub: "until implemented" };
  if (c.status === "retired") return { text: "Retired" };
  if (c.is_audit_overdue) return { text: `Overdue since ${fmt.date(c.next_audit_date)}`, badge: true };
  if (c.next_audit_date) return { text: fmt.date(c.next_audit_date), sub: cadence(c.audit_frequency).toLowerCase() || undefined };
  return { text: "Not scheduled", muted: true };
}

/** The lead under the H1 (decision D2): the objective; the description's text when there is none. */
export function controlLead(c: Pick<ControlRecord, "objective" | "description">): string | null {
  return trimmed(c.objective) || htmlToText(c.description) || null;
}

/** The description goes to Design only when an objective leads and the description says something else. */
export function descriptionDiffers(c: Pick<ControlRecord, "objective" | "description">): boolean {
  const objective = trimmed(c.objective).replace(/\s+/g, " ").toLowerCase();
  const description = htmlToText(c.description).toLowerCase();
  return !!objective && !!description && objective !== description;
}

/* ------------------------------------------------------------------ section copy */

/** "Effectiveness & tests" sub-line: "Annually · next due 03 Jul 2027", or the no-clock note. */
export function testsSectionSub(
  c: Pick<ControlRecord, "status" | "audit_frequency" | "next_audit_date" | "is_audit_overdue">,
  fmt: Fmt,
): string {
  if (UNTESTABLE_STATUSES.has(c.status)) return NO_TEST_CLOCK[c.status];
  return [
    cadence(c.audit_frequency),
    c.next_audit_date ? `${c.is_audit_overdue ? "overdue since" : "next due"} ${fmt.date(c.next_audit_date)}` : "no next test scheduled",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The tests section with no test on file. For a planned control the section head
 *  already says no test is scheduled until it is implemented, so this doesn't repeat it. */
export function testsEmptyText(c: Pick<ControlRecord, "status">): string {
  return c.status === "planned" ? "No tests yet." : "No tests yet — record the first test.";
}

/** "Maintenance" sub-line. */
export function maintenanceSectionSub(
  c: Pick<ControlRecord, "status" | "maintenance_frequency" | "next_maintenance_date" | "is_maintenance_overdue">,
  fmt: Fmt,
): string {
  if (UNTESTABLE_STATUSES.has(c.status)) return NO_MAINTENANCE_CLOCK[c.status];
  return [
    cadence(c.maintenance_frequency),
    c.next_maintenance_date ? `${c.is_maintenance_overdue ? "overdue since" : "next due"} ${fmt.date(c.next_maintenance_date)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The maintenance section with nothing recorded: "Quarterly maintenance once implemented · none recorded." */
export function maintenanceEmptyText(c: Pick<ControlRecord, "status" | "maintenance_frequency">): string {
  const cad = cadence(c.maintenance_frequency);
  return `${cad ? `${cad} maintenance` : "No maintenance cycle"}${c.status === "planned" ? " once implemented" : ""} · none recorded.`;
}

/** A linked exception's muted note (B3): "Approved · expires 03 Jan 2027", "Expired 03 Jan 2026",
 *  "Pending". Null without B3 (the chip alone). */
export function exceptionMeta(x: ControlExceptionRef, fmt: Fmt): string | null {
  return exceptionStateText(x.status, x.expires_at, fmt);
}

/* ------------------------------------------------------------------ monitoring (phase 4D) */

/** Under the Monitoring section title. */
export const MONITORING_RATING_NOTE =
  "Monitoring never changes effectiveness. A failing run opens an issue and stops risks relying on the control until it passes.";
export const MONITORING_EMPTY_TEXT = "Not monitored. Add a continuous monitoring test for this control under Integrations & CCM.";

/** A share of runs as a whole or one-decimal percentage: "97%", "96.7%". */
function pct(n: number): string {
  return `${Number.isInteger(n) ? n : n.toFixed(1)}%`;
}

/** The control's monitoring in one line: "Monitored: passing (last 30 runs 97%)",
 *  "Monitoring failing since 12 Sep 2026". */
export function monitoringStatusText(m: ControlMonitoring | null | undefined, fmt: Pick<Fmt, "date">): string {
  if (!m || m.state === "not_monitored" || m.tests.length === 0) return "Not monitored";
  const streak = m.recent_runs > 0 && m.recent_pass_rate !== null ? ` (last ${plural(m.recent_runs, "run")} ${pct(m.recent_pass_rate)})` : "";
  switch (m.state) {
    case "failing":
      return m.failing_since ? `Monitoring failing since ${fmt.date(m.failing_since)}` : "Monitoring failing";
    case "error": {
      const t = m.tests.find((x) => x.last_result === "error");
      return `Monitoring could not run${t ? `: ${t.reference}` : ""}`;
    }
    case "overdue": {
      const t = m.tests.find((x) => x.overdue);
      return `Monitoring overdue${t ? `: ${t.reference} ${t.last_run ? `last ran ${fmt.date(t.last_run)}` : "has never run"}` : ""}`;
    }
    case "paused":
      return "Monitoring paused";
    case "not_run":
      return "Monitored: no run yet";
    default:
      return `Monitored: passing${streak}`;
  }
}

/** One test's line in the Monitoring section. */
export function monitoringTestLine(t: ControlMonitoringTest, fmt: Pick<Fmt, "date">): string {
  const check = t.check_label ? ` · ${t.check_label}` : "";
  if (t.status !== "active") return `Paused${check}`;
  if (t.last_result === "failed")
    return `Failing since ${fmt.date(t.failing_since ?? t.last_run)}${t.issue_reference ? ` · ${t.issue_reference} open` : ""}${check}`;
  if (t.last_result === "error") return `Could not run on ${fmt.date(t.last_run)}${t.last_error ? `: ${truncate(t.last_error, 80)}` : ""}`;
  if (t.last_result === "not_run" || !t.last_run) return `No run yet${check}`;
  const rate = t.recent_runs > 0 && t.recent_pass_rate !== null ? ` · last ${plural(t.recent_runs, "run")} ${pct(t.recent_pass_rate)}` : "";
  return `Passed ${fmt.date(t.last_run)}${rate}${t.overdue ? " · overdue" : ""}${check}`;
}

/* ------------------------------------------------------------------ tested (decision 7) */

/** Whether the API sent the reviewed-only view (decision 7); an older API sends only the log. */
function hasReviewedView(c: ControlRecord): boolean {
  return c.tested_count !== undefined || c.reviewed_audit_count !== undefined;
}

/** How many tests count as "tested": signed off by a reviewer (or recorded before reviews
 *  existed). An older API gives the log's count. */
export function testedCount(c: ControlRecord): number {
  return c.tested_count ?? c.reviewed_audit_count ?? c.audit_count ?? 0;
}

/** The last reviewed test's result and date (older API: the newest recorded). */
export function lastTested(c: ControlRecord): { result: string; date: string | null } {
  return hasReviewedView(c)
    ? { result: c.last_reviewed_result ?? "", date: c.last_reviewed_date ?? null }
    : { result: c.last_audit_result ?? "", date: c.last_audit_date ?? null };
}

/** "1 test awaiting review" / "" when none. */
export function awaitingReviewText(n: number | null | undefined): string {
  return n && n > 0 ? `${plural(n, "test")} awaiting review` : "";
}

/* ------------------------------------------------------------------ headline */

/** "{E}{basisClause}; {clock}; {reliedOn}." (spec §4.2) */
export function controlHeadline({ control: c }: ControlInput, { fmt }: Ctx): Seg[] {
  const e = sentenceCase(c.effectiveness || "not_assessed") + (HEADLINE_BASIS[c.effectiveness_basis] ?? HEADLINE_BASIS.none);
  let clock: Seg[];
  if (c.status === "planned") clock = ["planned, so no test clock yet"];
  else if (c.status === "retired") clock = ["retired"];
  else if (c.is_audit_overdue) clock = ["test overdue since ", { b: fmt.date(c.next_audit_date) }];
  else if (testedCount(c) === 0) clock = [c.pending_review_count ? `never tested (${awaitingReviewText(c.pending_review_count)})` : "never tested"];
  else if (lastTested(c).date) clock = ["last tested ", { b: fmt.date(lastTested(c).date) }];
  else clock = ["tested, with no test date on file"];
  const risks = (c.risks ?? []).length;
  const reliedOn: Seg[] = risks === 0 ? ["relied on by no risk"] : ["relied on by ", { b: plural(risks, "risk") }];
  return [`${e}; `, ...clock, "; ", ...reliedOn, "."];
}

/* ------------------------------------------------------------------ tiles */

/** Effectiveness · Testing · Maintenance · Relied on by · Open issues & exceptions · Evidence on file. */
export function controlTiles(i: ControlInput, ctx: Ctx): TileModel[] {
  return [effectivenessTile(i), testingTile(i, ctx), maintenanceTile(i, ctx), reliedOnTile(i), issuesTile(i), evidenceTile(i, ctx)];
}

function effectivenessTile({ control: c }: ControlInput): TileModel {
  const eff = c.effectiveness || "not_assessed";
  const value: TileValue = isRated(eff)
    ? { text: sentenceCase(eff), tone: EFFECTIVENESS_TONE[eff] ?? "neutral", badge: true }
    : { text: "Not assessed", tone: "hollow" };
  const d = ratingWord(c.design_effectiveness);
  const o = ratingWord(c.operating_effectiveness);
  const issues = c.open_issues ?? [];
  const { withRefs: capRefs, short: capped } = capClause(c, issues);
  let leads: string[]; // most detailed first
  switch (c.effectiveness_basis) {
    case "tests":
      leads = [
        isRated(c.design_effectiveness) && isRated(c.operating_effectiveness)
          ? `Worse of design ${d} and operating ${o}, from the latest reviewed tests.`
          : isRated(c.operating_effectiveness)
            ? `From the latest reviewed operating test (${o}); no reviewed design test yet.`
            : `From the latest reviewed design test (${d}); no reviewed operating test yet.`,
      ];
      break;
    case "override": {
      const tail = `. Tests say design ${d}, operating ${o}; the next approved test replaces it.`;
      const why = c.effectiveness_override_reason;
      leads = [
        `Set by hand: ${quote(why)}${tail}`,
        `Set by hand: ${quote(why, 32)}${tail}`,
        `Set by hand: ${quote(why, 40)}; the next approved test replaces it.`,
      ];
      break;
    }
    case "manual":
      leads = ["Rated by hand before ratings came from tests; no reviewed test on file."];
      break;
    default:
      leads = ["No reviewed test yet, so design and operating are both unrated."];
  }
  const because = fit([[leads[0] + capRefs], ...leads.map((l) => [l + capped])]);
  const basis: Basis =
    c.effectiveness_basis === "tests"
      ? { kind: "evidenced", text: "From reviewed tests" }
      : c.effectiveness_basis === "override"
        ? { kind: "declared", text: "Override, reason on file" }
        : c.effectiveness_basis === "manual"
          ? { kind: "declared", text: "Set by hand" }
          : { kind: "missing", text: "No reviewed test" };
  return { key: "effectiveness", label: "Effectiveness", value, because, basis, section: "tests" };
}

/** What open issues do to the rating, only as far as it is true (spec §5): the server
 *  caps the *operating* rating (effective → partially effective), which reaches the
 *  combined value only on a test basis; an override or a hand rating is never capped. */
function capClause(c: ControlRecord, issues: ControlLink[]): { withRefs: string; short: string } {
  const n = issues.length;
  if (!n) return { withRefs: "", short: "" };
  const count = plural(n, "open issue");
  const refs = refList(issues);
  const handSet = c.effectiveness_basis === "override" || c.effectiveness_basis === "manual";
  if (handSet) {
    const who = c.effectiveness_basis === "override" ? "the override" : "a hand rating";
    const them = n === 1 ? "it" : "them";
    return { withRefs: ` ${refs} ${n === 1 ? "is" : "are"} open; ${who} is not capped by ${them}.`, short: ` ${count}; ${who} is not capped by ${them}.` };
  }
  if (c.operating_capped === true && c.effectiveness_basis === "tests")
    return { withRefs: ` Operating capped at partially effective by ${count}: ${refs}.`, short: ` Operating capped at partially effective by ${count}.` };
  return {
    withRefs: ` ${count} (${refs}) hold${n === 1 ? "s" : ""} operating at partially effective at best.`,
    short: ` ${count} hold${n === 1 ? "s" : ""} operating at partially effective at best.`,
  };
}

function testingTile({ control: c, tests }: ControlInput, { fmt }: Ctx): TileModel {
  const k = c.pending_review_count || 0;
  const tested = testedCount(c);
  const { result, date: testedOn } = lastTested(c);
  let value: TileValue;
  if (c.is_audit_overdue) value = { text: "Overdue", tone: "high", badge: true };
  else if (c.status === "planned") value = { text: "No test clock", tone: "hollow" };
  else if (c.status === "retired") value = { text: "Retired", tone: "neutral", badge: true };
  else if (tested === 0) value = { text: "Never tested", tone: "hollow" };
  else if (RESULT_TONE[result])
    value = { text: sentenceCase(result), tone: RESULT_TONE[result], badge: true, unit: testedOn ? fmt.date(testedOn) : undefined };
  else value = { text: "Not recorded", tone: "hollow" };

  let because: Seg[];
  if (c.status === "planned") {
    because = [
      hasCycle(c.audit_frequency)
        ? `The ${cadenceNoun(c.audit_frequency)} test cycle starts when the control is implemented.`
        : "No test cycle is set; tests are scheduled only once the control is implemented.",
    ];
  } else if (c.status === "retired") {
    because = ["Retired — no further tests."];
  } else {
    const next: Seg[] = !c.next_audit_date
      ? ["no next test is scheduled"]
      : [c.is_audit_overdue ? "the next test was due " : "next due ", { b: fmt.date(c.next_audit_date) }];
    const cycle = c.next_audit_date && hasCycle(c.audit_frequency) ? ` (${cadenceNoun(c.audit_frequency)} cycle)` : "";
    // Decision 7: the value and the count are reviewed tests only; tests awaiting a
    // reviewer are named beside them, never inside (spec §5: no unreconciled pair).
    const reviewed = hasReviewedView(c);
    const count = reviewed
      ? (tested === 0 ? "No reviewed test" : plural(tested, "reviewed test"))
      : `${plural(tested, "test")} on file`;
    const waiting = k ? ` ${sentenceCase(awaitingReviewText(k))}.` : "";
    because = fit([
      [`${count}; `, ...next, `${cycle}.`, waiting],
      [`${count}; `, ...next, ".", waiting],
      [`${count}.`, waiting],
    ]);
  }

  const newest = newestTest(tests);
  const basis: Basis =
    newest?.review_status === "reviewed"
      ? { kind: "evidenced", text: "Latest test independently reviewed" }
      : k > 0
        ? { kind: "declared", text: "Awaiting review" }
        : !newest
          ? { kind: "missing", text: "No test on file" }
          : newest.review_status === "returned"
            ? { kind: "declared", text: "Latest test returned to the tester" }
            : { kind: "declared", text: "Recorded before independent review" };
  return { key: "testing", label: "Testing", value, because, basis, section: "tests" };
}

function maintenanceTile({ control: c }: ControlInput, { fmt }: Ctx): TileModel {
  const r = c.last_maintenance_result ?? "";
  let value: TileValue;
  if (c.is_maintenance_overdue) value = { text: "Overdue", tone: "high", badge: true };
  else if (c.status === "planned") value = { text: "No clock", tone: "hollow" };
  else if (c.status === "retired") value = { text: "Retired", tone: "neutral", badge: true };
  else if (c.maintenance_count === 0) value = { text: "None recorded", tone: "hollow" };
  else if (RESULT_TONE[r])
    value = { text: sentenceCase(r), tone: RESULT_TONE[r], badge: true, unit: c.last_maintenance_date ? fmt.date(c.last_maintenance_date) : undefined };
  else value = { text: "Not recorded", tone: "hollow" };

  const freq = c.maintenance_frequency;
  const records = plural(c.maintenance_count, "record");
  let because: Seg[];
  if (c.status === "planned") {
    because = [
      hasCycle(freq)
        ? `No maintenance clock until implemented (${cadenceNoun(freq)} once it is).`
        : "No maintenance clock until implemented, and no cycle is set.",
    ];
  } else if (c.status === "retired") {
    because = [`Retired — no further maintenance; ${records} on file.`];
  } else if (!c.next_maintenance_date) {
    because = [hasCycle(freq) ? "No next maintenance scheduled" : "No maintenance cycle set", `; ${records} on file.`];
  } else {
    because = [
      c.is_maintenance_overdue ? "Was due " : "Next due ",
      { b: fmt.date(c.next_maintenance_date) },
      hasCycle(freq) ? ` (${cadenceNoun(freq)} cycle)` : "",
      `; ${records} on file.`,
    ];
  }
  const basis: Basis =
    c.maintenance_count > 0 ? { kind: "derived", text: "From the maintenance log" } : { kind: "missing", text: "Not on file" };
  return { key: "maintenance", label: "Maintenance", value, because, basis, section: "maintenance" };
}

function reliedOnTile({ control: c }: ControlInput): TileModel {
  const riskRefs = c.risks ?? [];
  const reqRefs = c.requirements ?? [];
  const risks = riskRefs.length;
  const reqs = reqRefs.length;
  const value: TileValue = { text: `${plural(risks, "risk")} · ${plural(reqs, "requirement")}` };
  let because: Seg[];
  if (!risks && !reqs) {
    because = ["Not mapped to any requirement or risk."];
  } else {
    const first = reqRefs[0];
    const fw = trimmed(first?.framework); // B7; without it the clause is named alone
    const req = reqs
      ? `Implements ${fw ? `${fw} ` : ""}${refText(first)}${reqs > 1 ? `, +${reqs - 1} more` : ""}.`
      : "Not mapped to any requirement.";
    const none = " No risk links it, so it earns no residual credit anywhere.";
    because = fit([
      [req, risks ? ` Mitigates ${refList(riskRefs)}.` : none],
      [req, risks ? ` Mitigates ${plural(risks, "risk")}.` : none],
    ]);
  }
  return { key: "reliedon", label: "Relied on by", value, because, basis: { kind: "derived", text: "From links" }, section: "linked" };
}

function issuesTile({ control: c }: ControlInput): TileModel {
  const issues = c.open_issues ?? [];
  const exceptions = c.exceptions ?? [];
  const n = issues.length;
  const m = exceptions.length;
  const unit = m ? plural(m, "exception") : undefined;
  const value: TileValue = n > 0 ? { text: `${n} open`, tone: "medium", badge: true, unit } : { text: "None", unit };
  const who = n === 0 ? "" : n === 1 ? refText(issues[0]) : `${refText(issues[0])} and ${n - 1} more`;
  const handSet = c.effectiveness_basis === "override" || c.effectiveness_basis === "manual";
  const head =
    n === 0
      ? "No open issue caps its operating rating."
      : handSet
        ? `${who} ${n === 1 ? "is" : "are"} open; the ${c.effectiveness_basis === "override" ? "override" : "hand rating"} is not capped by ${n === 1 ? "it" : "them"}.`
        : c.operating_capped === true
          ? `${who} ${n === 1 ? "caps" : "cap"} operating at partially effective until closed.`
          : `${who} ${n === 1 ? "holds" : "hold"} operating at partially effective at best until closed.`;
  const because = fit([
    [head, m ? ` ${plural(m, "exception")} linked: ${refList(exceptions)}.` : ""],
    [head, m ? ` ${plural(m, "exception")} linked.` : ""],
  ]);
  return {
    key: "issues",
    label: "Open issues & exceptions",
    value,
    because,
    basis: { kind: "derived", text: "From issues and exceptions" },
    section: "issues",
  };
}

function evidenceTile({ control: c, tests }: ControlInput, { fmt }: Ctx): TileModel {
  const e = tests.reduce((n, t) => n + (t.evidence?.length ?? 0), 0);
  const newest = newestTest(tests);
  const reviewed = newest && newest.review_status === "reviewed" ? newest : null;
  const value: TileValue = e === 0 ? { text: "None", tone: "hollow" } : { text: plural(e, "item") };
  const expected = ` Evidence expected: ${trimmed(c.evidence_expected) ? "defined" : "not defined"}.`;
  const count = `${plural(e, "evidence item")} across ${plural(tests.length, "test")}`;
  const who = reviewed ? personName(reviewed.reviewed_by_ref) : "";
  const by = reviewed
    ? `; latest test reviewed${who ? ` by ${who}` : ""}${reviewed.reviewed_at ? ` on ${fmt.date(reviewed.reviewed_at)}` : ""}`
    : "";
  const because = fit([[`${count}${by}.${expected}`], [`${count}${reviewed ? "; latest test reviewed" : ""}.${expected}`]]);
  const basis: Basis =
    e > 0 && reviewed
      ? { kind: "evidenced", text: "Attached to a reviewed test" }
      : e > 0
        ? { kind: "declared", text: "Attached, not yet reviewed" }
        : { kind: "missing", text: "Nothing attached to tests" };
  return { key: "evidence", label: "Evidence on file", value, because, basis, section: "tests" };
}

/* ------------------------------------------------------------------ open points */

/** Gaps first, then notes, each in the rule order of spec §4.2. Fix actions only scroll,
 *  focus, open Edit on a tab, open a form ("record-test", "record-maintenance",
 *  "suggest-clauses") or attest — never change state. */
export function controlOpenPoints({ control: c, suggestionCount, monitoring }: ControlInput, { fmt, gov }: Ctx): OpenPoint[] {
  const out: OpenPoint[] = [];
  const live = LIVE_STATUSES.has(c.status);
  const planned = c.status === "planned";
  const risks = (c.risks ?? []).length;
  const pending = c.pending_review_count || 0;

  if (!c.owner_id && !trimmed(c.owner))
    out.push({
      id: "control.owner",
      level: "gap",
      text: ["No control owner: test results and issues have nobody to go to."],
      action: { kind: "edit", target: "general", label: "Assign owner" },
    });
  if (textOnlyPerson(c.owner_id, c.owner))
    out.push({
      id: "control.owner_text",
      level: "note",
      text: [`Owner is a text label (“${truncate(c.owner, 40)}”), not a person`],
      action: { kind: "edit", target: "general", label: "Pick a person" },
    });
  if (!c.operator_id && (live || planned))
    out.push({
      id: "control.operator",
      level: live ? "gap" : "note",
      text: ["No operator named"],
      action: { kind: "edit", target: "general", label: "Name operator" },
    });
  if (live && testedCount(c) === 0)
    out.push({
      id: "control.untested_in_operation",
      level: "gap",
      text: [pending ? `In operation but never tested: ${awaitingReviewText(pending)}.` : "In operation but never tested."],
      action: pending
        ? { kind: "section", target: "tests", label: "Open tests" }
        : { kind: "open", target: "record-test", label: "Record test" },
    });
  if ((c.effectiveness_basis === "manual" || c.effectiveness_basis === "override") && risks > 0)
    out.push({
      id: "control.hand_rating_relied_on",
      level: "gap",
      text: [`Rated by hand, yet ${risks === 1 ? "1 risk takes" : `${risks} risks take`} residual credit from it.`],
      action: { kind: "section", target: "tests", label: "Open effectiveness" },
    });
  if (c.is_audit_overdue)
    out.push({
      id: "control.test_overdue",
      level: "gap",
      text: ["Test overdue since ", { b: fmt.date(c.next_audit_date) }, "."],
      action: { kind: "open", target: "record-test", label: "Record test" },
    });
  if (c.is_maintenance_overdue)
    out.push({
      id: "control.maintenance_overdue",
      level: "gap",
      text: ["Maintenance overdue since ", { b: fmt.date(c.next_maintenance_date) }, "."],
      action: { kind: "open", target: "record-maintenance", label: "Record maintenance" },
    });
  const noProcedure = !trimmed(c.test_procedure);
  const noEvidence = !trimmed(c.evidence_expected);
  if ((noProcedure || noEvidence) && (live || planned)) {
    const what = noProcedure && noEvidence ? "No test procedure or expected evidence" : noProcedure ? "No test procedure" : "No expected evidence";
    const why = noProcedure ? "a tester has nothing to follow." : "a tester doesn't know what to keep.";
    out.push({
      id: "control.no_procedure",
      level: live ? "gap" : "note",
      text: [live ? `${what}: ${why}` : what],
      action: { kind: "edit", target: "attributes", label: "Complete design" },
    });
  }
  if (c.is_key && c.status === "operational" && c.effectiveness !== "effective")
    out.push({
      id: "control.key_not_effective",
      level: "gap",
      text: ["Key control is not rated effective."],
      action: { kind: "section", target: "tests", label: "Open effectiveness" },
    });
  const state = gov.workflowState;
  if (state && state !== "draft" && gov.approvalSteps === 0) {
    // B10b / B10c: a backfill names nobody, and says so.
    const imported = gov.lastStep?.action === "import";
    out.push({
      id: "control.approved_without_step",
      level: "gap",
      text: [
        imported
          ? `${importedApprovalText(state, gov.lastStep?.via)}.`
          : `Record approval shows ${APPROVAL_STATE_WORD[state] ?? state} but no approval step is on file.`,
      ],
      action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
    });
  }
  const mon = monitoring;
  if (mon && mon.state === "failing")
    out.push({
      id: "control.monitoring_failing",
      level: "gap",
      text: [mon.failing_since ? "Continuous monitoring failing since " : "Continuous monitoring failing", ...(mon.failing_since ? [{ b: fmt.date(mon.failing_since) }] : []), ": risks do not rely on it until it passes."],
      action: { kind: "section", target: "monitoring", label: "Open monitoring" },
    });
  if (mon && mon.state === "error")
    out.push({
      id: "control.monitoring_error",
      level: "note",
      text: [monitoringStatusText(mon, fmt)],
      action: { kind: "section", target: "monitoring", label: "Open monitoring" },
    });
  if (mon && mon.state === "overdue")
    out.push({
      id: "control.monitoring_overdue",
      level: "note",
      text: [monitoringStatusText(mon, fmt)],
      action: { kind: "section", target: "monitoring", label: "Open monitoring" },
    });
  // Named in the untested gap already when nothing reviewed is on file.
  if (pending > 0 && !(live && testedCount(c) === 0))
    out.push({
      id: "control.pending_review",
      level: "note",
      text: [`${plural(pending, "test result")} awaiting review`],
      action: { kind: "section", target: "tests", label: "Open tests" },
    });
  if (risks === 0)
    out.push({ id: "control.no_risk", level: "note", text: ["Relied on by no risk"], action: { kind: "edit", target: "links", label: "Link risks" } });
  if ((c.requirements ?? []).length === 0)
    out.push({
      id: "control.no_requirement",
      level: "note",
      text: ["Not mapped to any requirement"],
      action: { kind: "section", target: "linked", label: "Map requirements" },
    });
  if (suggestionCount && suggestionCount > 0)
    out.push({
      id: "control.suggestions",
      level: "note",
      text: [`${plural(suggestionCount, "suggested clause")} to review`],
      action: { kind: "open", target: "suggest-clauses", label: "Review" },
    });
  // B1: the server decides whether this viewer may attest; say why not instead of
  // offering it. Decision 6: in review asks for the approval; draft and retired say nothing.
  const attPoint = attestationNotePoint("control", gov, { withReason: true, fmt });
  if (attPoint) out.push(attPoint);
  return [...out.filter((p) => p.level === "gap"), ...out.filter((p) => p.level === "note")];
}
