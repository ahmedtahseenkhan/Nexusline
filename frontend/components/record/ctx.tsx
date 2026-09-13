"use client";

/* Page helpers for the dossier wiring (record-page-spec §4.0).

     const gov = useRecordGovernanceData("risk", detail?.id ?? null, { statusRulesModel: "risk" });
     const canWrite = useHasPermission("risk:write");
     const ctx = useRecordCtx(gov, canWrite);            // { fmt, now, gov: toGovModel(gov, canWrite) }
     const tiles = detail ? riskTiles(input, ctx) : [];

     identity.meta = [
       …,
       approvalMetaItem(gov, ctx.fmt, "Whether this record's content has been signed off. Separate from the risk status."),
       …,
     ];

   `approvalMetaItem` is the shared "Record approval" meta item: the WorkflowBadge (hollow
   for Draft), the short approval line as `sub` ("not submitted", "in review since …",
   "approved …"), and an amber gap when an approved / in review / retired record has no
   approval step: "Imported, no approver recorded" when its only step is an import
   backfill, otherwise "No approval step on file".

   v1.1: RecordHeader always renders this item SECOND, right after the type's status —
   pass it as `identity.approval` (or anywhere in `meta`; it is moved), or omit it and
   the header builds it from the drawer's governance with `approvalHintFor(status)`. */

import { useMemo } from "react";
import { Badge } from "@/components/badges";
import { WorkflowBadge } from "@/components/record/WorkflowBadge";
import { toGovModel, type RecordGovernance } from "@/components/record/RecordGovernance";
import type { MetaItem } from "@/components/record/types";
import { useFormat } from "@/lib/format";
import { approvalLine, sentenceCase } from "@/lib/record/text";
import type { Ctx, Fmt } from "@/lib/record/types";

/** The tenant formatters as a lib/record `Fmt`. */
export function useRecordFmt(): Fmt {
  const { formatDate, formatDateTime, formatMoney } = useFormat();
  return useMemo<Fmt>(
    () => ({
      date: (v) => formatDate(v),
      dateTime: (v) => formatDateTime(v),
      money: (n, currency) => formatMoney(n, currency),
    }),
    [formatDate, formatDateTime, formatMoney],
  );
}

/** `Ctx` for lib/record/<type>.ts. Pass `now` to drive a ticking clock (incidents). */
export function useRecordCtx(gov: RecordGovernance | null, canWrite: boolean, now?: Date): Ctx {
  const fmt = useRecordFmt();
  return { fmt, now: now ?? new Date(), gov: toGovModel(gov, canWrite) };
}

const DEFAULT_HINT = "Whether this record's content has been signed off. Separate from its business status.";

/** The "Record approval" hint that names the type's status item: "Risk status" →
 *  "Whether this record's content has been signed off. Separate from the risk status." */
export function approvalHintFor(statusLabel: string | null | undefined): string {
  const l = (statusLabel ?? "").trim();
  if (!l) return DEFAULT_HINT;
  return `Whether this record's content has been signed off. Separate from the ${l.charAt(0).toLowerCase()}${l.slice(1)}.`;
}

/** The "Record approval" header meta item, built from the governance. */
export function approvalMetaItem(gov: RecordGovernance | null, fmt: Fmt, hint: string = DEFAULT_HINT): MetaItem {
  const wf = gov?.workflow ?? null;
  if (!wf) {
    return {
      key: "approval",
      label: "Record approval",
      value: <span className="muted">{gov?.errors.workflow ? "Not available" : "Loading…"}</span>,
      hint,
    };
  }
  const model = toGovModel(gov, false);
  const line = approvalLine(model, fmt, { routing: wf.routing });
  const imported = model.approvalSteps === 0 && model.lastStep?.action === "import";
  const noStep = wf.state !== "draft" && model.approvalSteps === 0;
  return {
    key: "approval",
    label: "Record approval",
    value: <WorkflowBadge state={wf.state} asIs hollowDraft />,
    sub: line.short || undefined,
    hint,
    // An import backfill names nobody: the badge says the state, the gap says no one approved it.
    gap: imported ? { text: "Imported, no approver recorded" } : noStep ? { text: "No approval step on file" } : undefined,
  };
}

/** v1.1 slot 1 for the types with no business status (information asset, IT asset): the
 *  review state the server reports (`review_status`: current | overdue | none), with the
 *  cycle and the last review as `sub`. It replaces those pages' "Next review" item, so
 *  "Record approval" can sit second on every type.
 *
 *    status: reviewStatusMetaItem(a, ctx.fmt)
 *    → Review status  [Current] next 03 Jul 2027 · Annual · last 03 Jul 2026
 *    → Review status  (Not yet reviewed) first due 03 Jul 2027 · Annual   (a date ahead, never reviewed)
 *    → Review status  [Overdue since 03 Jul 2026] Annual · never reviewed
 *    → Review status  (Not scheduled) never reviewed */
export function reviewStatusMetaItem(
  r: { review_status?: string | null; next_review_date?: string | null; last_review_date?: string | null; review_frequency?: string | null },
  fmt: Fmt,
  hint = "The asset's review cycle. Attesting the asset records its review and moves the next date.",
): MetaItem {
  const st = (r.review_status ?? "").toLowerCase();
  const next = r.next_review_date ? fmt.date(r.next_review_date) : null;
  const cadence = r.review_frequency && r.review_frequency !== "none" ? sentenceCase(r.review_frequency) : null;
  // A green "Current" says a review took place: a never-reviewed record with a date ahead
  // reads "Not yet reviewed" instead (the same rule as assetReviewStatusView).
  const firstDue = st !== "overdue" && !!next && !r.last_review_date;
  const value =
    st === "overdue" && next ? (
      <Badge tone="high" asIs>Overdue since {next}</Badge>
    ) : firstDue ? (
      <Badge hollow asIs>Not yet reviewed</Badge>
    ) : st === "current" || (st !== "overdue" && next) ? (
      <Badge tone="low" asIs>Current</Badge>
    ) : (
      <Badge hollow asIs>Not scheduled</Badge>
    );
  const sub = (firstDue
    ? [`first due ${next}`, cadence]
    : [
        st !== "overdue" && next ? `next ${next}` : null,
        cadence,
        r.last_review_date ? `last ${fmt.date(r.last_review_date)}` : "never reviewed",
      ])
    .filter(Boolean)
    .join(" · ");
  return { key: "status", label: "Review status", value, sub, hint };
}

