/* The incident record's judgement wording (record-page-spec §4.7): the summary tiles, the
   open points, the headline and the regulator-clock phrase. The only place this wording
   lives — `app/(app)/incidents/page.tsx` renders what these functions return, and
   `lib/record/__fixtures__/incident.json` pins them (`npm run check:record-copy`). A
   wording change updates the fixture and needs a Compliance reviewer on the PR.

   `ctx.now` is the page's ticking clock (it re-renders every 30 s), so the notification
   countdown in the band and the open points stays live.

   Pure (record-page-spec §3.2): no React, no DOM; imports `./text`, `./types` and the
   DOM-free `htmlToText` from `@/lib/sanitize` (root cause and lessons are rich text). */

import { htmlToText } from "@/lib/sanitize";
import { approvalWithoutStepText, durationHours, joinList, plural, sentenceCase, textOnlyPerson, truncate } from "./text";
import type { Ctx, Fmt, OpenPoint, Seg, TileModel, TileValue } from "./types";

/* ------------------------------------------------------------------ input ----- */

/** The fields of `GET /incidents/{id}` (IncidentFull) the rules read. */
export type IncidentFacts = {
  severity: string | null;
  status: string;
  assignee?: string | null;
  assignee_id?: string | null;
  category?: string | null;
  category_ref?: { label: string } | null;
  classification?: string | null;
  classification_ref?: { label: string } | null;
  impact: string;
  root_cause: string;
  lessons_learned: string;
  cost: number | null;
  /** When it happened; absent on an older API. */
  occurred_at?: string | null;
  detected_at: string | null;
  contained_at: string | null;
  /** When it was resolved; absent on an older API. */
  resolved_at?: string | null;
  customers_affected: number | null;
  records_affected: number | null;
  near_miss: boolean;
  personal_data_breach: boolean;
  notification_deadline: string | null;
  notified_at: string | null;
  notified_on_time: boolean | null;
  regulator_reference: string | null;
  mttd_hours: number | null;
  mttc_hours: number | null;
  mttr_hours: number | null;
  loss_events: { net_loss: number; currency: string }[];
  data_breaches: unknown[];
  stage_count: number;
  completed_stages: number;
  lifecycle_complete: boolean;
  current_stage: string | null;
  is_reportable: boolean;
  regulator?: string | null;
  regulator_ref?: { label: string } | null;
  regulatory_reports: unknown[];
};

export type IncidentInput = { incident: IncidentFacts };

/* -------------------------------------------------------------- helpers ----- */

const TILE_TONES = new Set(["critical", "high", "medium", "low"]);
const sevValue = (v: string | null | undefined): TileValue =>
  v ? { text: sentenceCase(v), tone: (TILE_TONES.has(v) ? v : "neutral") as TileValue["tone"], badge: true } : { text: "Not rated", tone: "hollow" };
/** "Approved" / "In review" / "Retired" — the Record approval state as the header shows it. */
const WORKFLOW_LABEL: Record<string, string> = { in_review: "In review", approved: "Approved", retired: "Retired" };
const PAST_CONTAINMENT = new Set(["contained", "resolved", "closed"]);
const RESOLVED = new Set(["resolved", "closed"]);
const count = (n: number) => n.toLocaleString("en-US");

/** A timestamp entered as a date only: the tenant's clock reads 00:00 (the form's date
 *  inputs store midnight). Uses the page's formatter, so it follows the tenant timezone. */
export function incidentDateOnly(v: string | null | undefined, fmt: Fmt): boolean {
  return !!v && / 00:00$/.test(fmt.dateTime(v));
}

/** A response duration between two recorded times: "4 h", or, when both ends were
 *  entered as dates only, the calendar gap ("the same day", "2 days") since the hours
 *  between two midnights say nothing about how fast anyone was. */
export function incidentSpan(
  hours: number | null | undefined, from: string | null | undefined, to: string | null | undefined, fmt: Fmt,
): { text: string; dateOnly: boolean } | null {
  if (hours === null || hours === undefined) return null;
  if (incidentDateOnly(from, fmt) && incidentDateOnly(to, fmt)) {
    const days = Math.round(Math.abs(hours) / 24);
    return { text: days === 0 ? "the same day" : plural(days, "day"), dateOnly: true };
  }
  return { text: durationHours(hours), dateOnly: false };
}

/** What the Timeline shows for a calculated duration (MTTD, MTTC, MTTR) when it can't be
 *  shown as a plain figure: "Needs Occurred" while a time it is calculated from is not
 *  recorded (nobody types a duration, so it never joins the "not set · Fill in" list),
 *  "Same day (dates only)" when both times were entered as dates only. null = show the
 *  figure. */
export function incidentDurationNote(
  i: Pick<IncidentFacts, "status" | "occurred_at" | "detected_at" | "contained_at" | "resolved_at" | "mttd_hours" | "mttc_hours" | "mttr_hours">,
  key: "mttd" | "mttc" | "mttr",
  fmt: Fmt,
): string | null {
  const [fromKey, toKey, hours] =
    key === "mttd" ? (["occurred_at", "detected_at", i.mttd_hours] as const)
    : key === "mttc" ? (["detected_at", "contained_at", i.mttc_hours] as const)
    : (["detected_at", "resolved_at", i.mttr_hours] as const);
  const LABEL: Record<string, string> = { occurred_at: "Occurred", detected_at: "Detected", contained_at: "Contained", resolved_at: "Resolved" };
  if (hours === null || hours === undefined) {
    // An incident that hasn't reached the end point has nothing to measure yet: that is
    // a fact ("Not resolved yet"), not a time someone forgot to enter.
    if (!i[toKey] && toKey === "resolved_at" && !RESOLVED.has(i.status)) return "Not resolved yet";
    if (!i[toKey] && toKey === "contained_at" && !PAST_CONTAINMENT.has(i.status)) return "Not contained yet";
    const need = [fromKey, toKey].filter((k) => !i[k]).map((k) => LABEL[k]);
    return need.length ? `Needs ${joinList(need)}` : "Not calculated";
  }
  const span = incidentSpan(hours, i[fromKey], i[toKey], fmt);
  if (span?.dateOnly) return span.text === "the same day" ? "Same day (dates only, no times)" : `${sentenceCase(span.text)} (dates only)`;
  return null;
}

/** The timeline times not recorded, in the order they happen: "occurrence", "detection",
 *  "containment", "resolution". Containment and resolution only count once the incident is
 *  past them (an open incident that isn't contained yet is a fact, not a gap). */
export function incidentMissingTimes(i: Pick<IncidentFacts, "status" | "occurred_at" | "detected_at" | "contained_at" | "resolved_at">): string[] {
  const out: string[] = [];
  // occurred_at undefined = an older API that doesn't send it: don't claim it's missing.
  if (i.occurred_at === null) out.push("occurrence");
  if (!i.detected_at) out.push("detection");
  if (!i.contained_at && PAST_CONTAINMENT.has(i.status)) out.push("containment");
  if (i.resolved_at === null && RESOLVED.has(i.status)) out.push("resolution");
  return out;
}

/** "Occurrence and containment times not recorded" / "Detection time not recorded". */
export function incidentMissingTimesText(missing: readonly string[]): string {
  if (!missing.length) return "";
  return `${sentenceCase(joinList([...missing]))} ${missing.length === 1 ? "time" : "times"} not recorded`;
}

/** The hint on "Generate <regulator> reports", worded for the state: generating also marks
 *  a non-reportable incident reportable (POST …/regulatory-reports/generate sets it). */
export function incidentGenerateHint(i: Pick<IncidentFacts, "is_reportable" | "regulatory_reports" | "regulator" | "regulator_ref">): string {
  const reg = incidentRegulatorName(i) || "SBP";
  if (!i.is_reportable) return `Marks the incident reportable to ${reg} and creates its initial and final reports`;
  if (i.regulatory_reports.length === 0) return `Creates the initial and final ${reg} reports`;
  return "Recreates any initial or final report that was removed";
}

/** The regulator the incident is reported to: the picked value, else the legacy text. */
export function incidentRegulatorName(i: Pick<IncidentFacts, "regulator" | "regulator_ref">): string {
  return i.regulator_ref?.label || i.regulator || "";
}

/** The regulator-notification clock as a tile value and a lower-case phrase for the headline. */
export function incidentRegClock(
  i: Pick<IncidentFacts, "is_reportable" | "notification_deadline" | "notified_at" | "notified_on_time">,
  now: Date,
): { value: TileValue; phrase: string; hoursLeft: number | null } {
  if (!i.is_reportable) return { value: { text: "Not reportable", tone: "neutral", badge: true }, phrase: "not reportable", hoursLeft: null };
  if (!i.notification_deadline) return { value: { text: "No report generated", tone: "medium", badge: true }, phrase: "no report generated", hoursLeft: null };
  if (i.notified_at) {
    return i.notified_on_time === false
      ? { value: { text: "Notified late", tone: "critical", badge: true }, phrase: "notified late", hoursLeft: null }
      : { value: { text: "Notified on time", tone: "low", badge: true }, phrase: "notified on time", hoursLeft: null };
  }
  const left = (new Date(i.notification_deadline).getTime() - now.getTime()) / 3.6e6;
  if (left < 0) return { value: { text: `Overdue ${durationHours(-left)}`, tone: "critical", badge: true }, phrase: `report overdue by ${durationHours(-left)}`, hoursLeft: left };
  return {
    value: { text: `Due in ${durationHours(left)}`, tone: left < 6 ? "high" : "medium", badge: true },
    phrase: `report due in ${durationHours(left)}`,
    hoursLeft: left,
  };
}

/** Net loss per currency: "PKR 1,200,000 + USD 5,000". */
function netLoss(i: Pick<IncidentFacts, "loss_events">, fmt: Fmt): string {
  const sums: Record<string, number> = {};
  for (const l of i.loss_events) sums[l.currency || ""] = (sums[l.currency || ""] ?? 0) + (Number(l.net_loss) || 0);
  return Object.entries(sums).map(([c, n]) => fmt.money(n, c || null)).join(" + ");
}

/** No root cause or no lessons learned on file (both are rich text). */
const unanalysed = (i: Pick<IncidentFacts, "root_cause" | "lessons_learned">) => !htmlToText(i.root_cause) || !htmlToText(i.lessons_learned);

function stagePhrase(i: IncidentFacts): string {
  if (i.lifecycle_complete) return unanalysed(i) ? "all stages marked done, analysis not recorded" : "response complete";
  if (!i.stage_count) return "no response stages";
  const at = Math.min(i.completed_stages + 1, i.stage_count);
  return `stage ${at} of ${i.stage_count}${i.current_stage ? `: ${i.current_stage}` : ""}`;
}

/** "12 customers, 480 records" — the affected counts that were recorded. */
function affectedCounts(i: IncidentFacts): string[] {
  return [
    i.customers_affected != null ? `${count(i.customers_affected)} ${i.customers_affected === 1 ? "customer" : "customers"}` : "",
    i.records_affected != null ? `${count(i.records_affected)} ${i.records_affected === 1 ? "record" : "records"}` : "",
  ].filter(Boolean);
}

/* ---------------------------------------------------------------- tiles ----- */

export function incidentTiles({ incident: i }: IncidentInput, ctx: Ctx): TileModel[] {
  const { fmt, now } = ctx;
  const reg = incidentRegulatorName(i) || "the regulator";

  // Severity & classification
  const type = i.category_ref?.label || i.category || "";
  const cls = i.classification_ref?.label || i.classification || "";
  const affected = affectedCounts(i);
  const severity: TileModel = {
    key: "severity", label: "Severity & classification", section: "timeline",
    value: sevValue(i.severity),
    because: [`${type || "Type not set"} · ${cls || "classification not set"}${affected.length ? `; ${affected.join(", ")} affected` : ""}.`],
    // "The handler" only when a person is picked: a text label ("Network Team") is not
    // someone who set anything (the same rule as the header's "Text only" owner).
    basis: { kind: "declared", text: i.assignee_id ? "Set by the handler" : "Set by hand" },
  };

  // Regulator notification
  const clock = incidentRegClock(i, now);
  const clockBecause: Seg[] =
    !i.is_reportable ? ["Not marked reportable."]
    : !i.notification_deadline ? [`Marked reportable to ${reg}, but no regulator report exists yet.`]
    : i.notified_at ? [`Submitted ${fmt.dateTime(i.notified_at)}${i.regulator_reference ? `, ref ${truncate(i.regulator_reference, 40)}` : ""}.`]
    : [`Initial report to ${reg} due ${fmt.dateTime(i.notification_deadline)}, counted from ${i.detected_at ? `detection at ${fmt.dateTime(i.detected_at)}` : "when it was logged"}.`];
  const regclock: TileModel = {
    key: "regclock", label: "Regulator notification", section: "regulatory",
    value: clock.value,
    because: clockBecause,
    basis: !i.is_reportable ? { kind: "declared", text: "Reportability set by hand" }
      : !i.notification_deadline ? { kind: "missing", text: "No report on file" }
      : i.notified_at ? { kind: "evidenced", text: "Submission recorded" }
      : { kind: "derived", text: "Calculated from detection time" },
  };

  // Impact
  const counts = affected.join(" · ");
  const impactText = (i.impact || "").trim(); // plain text (a TextArea), not rich text
  const impact: TileModel = {
    key: "impact", label: "Impact", section: "impact",
    value: counts ? { text: counts } : { text: "Not recorded", tone: "hollow" },
    because: [impactText ? truncate(impactText, 120) : "No impact assessment written."],
    basis: impactText || counts ? { kind: "declared", text: "Recorded by hand" } : { kind: "missing", text: "Not on file" },
  };

  // Loss
  let loss: TileModel;
  if (i.near_miss) {
    loss = {
      key: "loss", label: "Loss", section: "impact",
      value: { text: "Near miss", tone: "info", badge: true },
      because: ["Nothing was lost; excluded from loss totals."],
      basis: { kind: "declared", text: "Marked as a near miss" },
    };
  } else if (i.loss_events.length) {
    const net = netLoss(i, fmt);
    loss = {
      key: "loss", label: "Loss", section: "impact",
      value: { text: net },
      because: [`${plural(i.loss_events.length, "loss event")} in the loss database, net ${net}.`],
      basis: { kind: "evidenced", text: "From the loss database" },
    };
  } else if (i.cost != null) {
    loss = {
      key: "loss", label: "Loss", section: "impact",
      value: { text: `Est. ${fmt.money(i.cost)}` },
      because: [`Estimated ${fmt.money(i.cost)}; no loss event recorded yet.`],
      basis: { kind: "declared", text: "Estimate" },
    };
  } else {
    loss = {
      key: "loss", label: "Loss", section: "impact",
      value: { text: "Not recorded", tone: "hollow" },
      because: ["No cost estimate or loss event recorded."],
      basis: { kind: "missing", text: "Not on file" },
    };
  }

  // Response times. Name exactly which times are missing, and never call a resolved or
  // closed incident "not contained": it is past containment, whether or not the time
  // was written down.
  const missing = incidentMissingTimes(i);
  const detect = incidentSpan(i.mttd_hours, i.occurred_at, i.detected_at, fmt);
  const contain = incidentSpan(i.mttc_hours, i.detected_at, i.contained_at, fmt);
  const resolve = incidentSpan(i.mttr_hours, i.detected_at, i.resolved_at, fmt);
  const resolved = RESOLVED.has(i.status);
  const facts: string[] = [];
  if (detect) facts.push(detect.dateOnly ? `detected ${detect.text === "the same day" ? "the day it occurred" : `${detect.text} after it occurred`} (dates only)` : `detected ${detect.text} after it occurred`);
  if (contain) facts.push(contain.dateOnly ? `contained ${contain.text === "the same day" ? "the day it was detected" : `${contain.text} after detection`} (dates only)` : `contained ${contain.text} after detection`);
  else if (!i.contained_at && !PAST_CONTAINMENT.has(i.status)) facts.push("not contained yet");
  if (resolve) facts.push(resolve.dateOnly ? `resolved ${resolve.text === "the same day" ? "the day it was detected" : `${resolve.text} after detection`} (dates only)` : `resolved ${resolve.text} after detection`);
  else if (!resolved) facts.push("not resolved yet");
  const parts = [...facts, incidentMissingTimesText(missing).toLowerCase()].filter(Boolean);
  const responseBecause = parts.length ? `${parts.join("; ")}.` : "Resolved.";
  const response: TileModel = {
    key: "response", label: "Response times", section: "timeline",
    value: contain ? { text: contain.dateOnly ? (contain.text === "the same day" ? "Contained same day" : `Contained in ${contain.text}`) : `Contained in ${contain.text}` }
      : i.contained_at ? { text: "Contained" }
      : resolved ? { text: sentenceCase(i.status) }
      : PAST_CONTAINMENT.has(i.status) ? { text: "Contained", unit: "time not recorded" }
      : { text: "Not contained", tone: "hollow" },
    because: [responseBecause.charAt(0).toUpperCase() + responseBecause.slice(1)],
    basis: missing.length ? { kind: "missing", text: `${plural(missing.length, "time")} not recorded` } : { kind: "derived", text: "From the timeline" },
  };

  // Response stage. Stages are ticked by hand: "all done" with no root cause or lessons
  // on file is a claim the record doesn't back, so it isn't shown as a green state.
  const unanalysed = [
    !htmlToText(i.root_cause) ? "root cause" : "",
    !htmlToText(i.lessons_learned) ? "lessons learned" : "",
  ].filter(Boolean);
  const hollowComplete = i.lifecycle_complete && unanalysed.length > 0;
  const stage: TileModel = {
    key: "stage", label: "Response stage", section: "lifecycle",
    value: i.lifecycle_complete ? { text: "Complete", tone: hollowComplete ? "medium" : "low", badge: true }
      : i.stage_count ? { text: `Stage ${Math.min(i.completed_stages + 1, i.stage_count)} of ${i.stage_count}`, unit: i.current_stage || undefined }
      : { text: "No stages", tone: "hollow" },
    because: hollowComplete
      ? [`${i.completed_stages} of ${i.stage_count} stages marked done, but ${joinList(unanalysed)} ${unanalysed.length > 1 ? "are" : "is"} not recorded.`]
      : [`${i.completed_stages} of ${i.stage_count} stages done${!i.lifecycle_complete && i.current_stage ? `; next: ${i.current_stage}` : ""}.`],
    basis: hollowComplete ? { kind: "declared", text: "Stages marked done by hand" } : { kind: "derived", text: "From the response lifecycle" },
  };

  return [severity, regclock, impact, loss, response, stage];
}

/* ------------------------------------------------------------- headline ----- */

export function incidentHeadline({ incident: i }: IncidentInput, ctx: Ctx): Seg[] {
  const reg = incidentRegulatorName(i) || "the regulator";
  const sev = i.severity ? sentenceCase(i.severity) : "Unrated";
  return [`${sev} incident${i.is_reportable ? `, reportable to ${reg}` : ""}; `, { b: incidentRegClock(i, ctx.now).phrase }, `; ${stagePhrase(i)}.`];
}

/* ---------------------------------------------------------- open points ----- */

export function incidentOpenPoints({ incident: i }: IncidentInput, ctx: Ctx): OpenPoint[] {
  const { gov, now } = ctx;
  const gaps: OpenPoint[] = [];
  const notes: OpenPoint[] = [];

  if (!i.assignee_id && !(i.assignee || "").trim()) {
    gaps.push({ id: "incident.handler", level: "gap", text: ["No handler assigned."], action: { kind: "edit", target: "general", label: "Assign handler" } });
  }
  if (i.notification_deadline && !i.notified_at) {
    const late = (now.getTime() - new Date(i.notification_deadline).getTime()) / 3.6e6;
    if (late > 0) {
      gaps.push({
        id: "incident.notification_overdue", level: "gap",
        text: [`Regulator notification overdue by ${durationHours(late)}.`],
        action: { kind: "section", target: "regulatory", label: "Open reporting" },
      });
    }
  }
  if (i.is_reportable && i.regulatory_reports.length === 0) {
    gaps.push({
      id: "incident.reportable_no_reports", level: "gap", text: ["Marked reportable but no regulator report exists."],
      action: { kind: "section", target: "regulatory", label: "Generate reports" },
    });
  }
  if (i.personal_data_breach && i.data_breaches.length === 0) {
    gaps.push({
      id: "incident.breach_record_missing", level: "gap", text: ["Personal data breach with no data-breach record."],
      action: { kind: "section", target: "details", label: "See details" },
    });
  }
  if (RESOLVED.has(i.status) && (!htmlToText(i.root_cause) || !htmlToText(i.lessons_learned))) {
    gaps.push({
      id: "incident.resolved_without_analysis", level: "gap", text: ["Resolved without a root cause or lessons learned."],
      action: { kind: "edit", target: "analysis", label: "Record analysis" },
    });
  }
  const ws = gov.workflowState;
  if ((ws === "approved" || ws === "in_review" || ws === "retired") && gov.approvalSteps === 0) {
    gaps.push({
      id: "incident.approved_without_step", level: "gap",
      text: [approvalWithoutStepText(gov, WORKFLOW_LABEL[ws])],
      action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
    });
  }

  if (textOnlyPerson(i.assignee_id, i.assignee)) {
    notes.push({
      id: "incident.handler_text", level: "note", text: [`Handler is a text label (“${truncate(i.assignee, 40)}”), not a person`],
      action: { kind: "edit", target: "general", label: "Pick a person" },
    });
  }
  const missingTimes = incidentMissingTimes(i);
  if (missingTimes.length) {
    notes.push({
      id: "incident.times_not_recorded", level: "note", text: [incidentMissingTimesText(missingTimes)],
      action: { kind: "edit", target: "timeline", label: missingTimes.length > 1 ? "Add times" : "Add time" },
    });
  }
  if (!i.near_miss && i.cost == null && i.loss_events.length === 0) {
    notes.push({ id: "incident.no_loss_recorded", level: "note", text: ["No loss recorded"], action: { kind: "section", target: "impact", label: "See impact" } });
  }
  return [...gaps, ...notes];
}

/** The line OpenPoints shows when nothing is open. */
export const INCIDENT_CLEAR_TEXT = "No open points: handler, regulator reporting and analysis are on file.";
