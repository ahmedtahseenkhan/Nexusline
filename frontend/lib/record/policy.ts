/* The policy record's judgement wording (record-page-spec §4.5): the summary tiles, the
   open points, the headline and the sentences the page shows about publication and the
   review cycle. The only place this wording lives — `app/(app)/policies/page.tsx`
   renders what these functions return, and `lib/record/__fixtures__/policy.json` pins
   them (`npm run check:record-copy`). A wording change updates the fixture and needs a
   Compliance reviewer on the PR.

   Pure (record-page-spec §3.2): no React, no DOM, imports only `./text` and `./types`,
   so the fixture runner executes it under Node. */

import { approvalBlocksAttest, approvalWithoutStepText, attestFix, awaitingConfirmationPoint, exceptionStateText, joinList, missedReviewsText, plural, progressTone, sentenceCase, textOnlyPerson, truncate } from "./text";
import type { Basis, Ctx, Fmt, OpenPoint, Seg, TileModel, TileValue } from "./types";

/* ------------------------------------------------------------------ input ----- */

/** A linked record as `GET /policies/{id}` returns it. */
export type PolicyRef = { id: string; reference?: string; title?: string; name?: string };

/** A linked exception. `status` (pending | approved | rejected | expired | closed; an
 *  approved one past its expiry reads expired) and `expires_at` arrive with B3; an older
 *  API sends neither, and the Exceptions tile then names the exceptions only. */
export type PolicyExceptionRef = PolicyRef & { status?: string | null; expires_at?: string | null };

/** The fields of `GET /policies/{id}` (PolicyRead) the rules read. */
export type PolicyFacts = {
  version: string;
  status: string;
  workflow_status: string;
  owner?: string | null;
  owner_id?: string | null;
  review_frequency: string;
  next_review_date: string | null;
  last_review_date: string | null;
  published_at: string | null;
  is_review_overdue: boolean;
  effective_date?: string | null;
  /** The policy text (rich text) and the document link; with `use_attachments` the
   *  document lives in the attachments, which the record read doesn't list. */
  body?: string | null;
  url?: string | null;
  use_attachments?: boolean;
  controls: PolicyRef[];
  requirements: PolicyRef[];
  approving_authority_ref?: PolicyRef | null;
  supersedes_ref?: PolicyRef | null;
  superseded_by?: PolicyRef[];
  exceptions?: PolicyExceptionRef[];
};

/** `GET /policies/{id}/acknowledgement-status`, the parts the rules read. */
export type PolicyAckFacts = {
  scope: "roles" | "everyone" | string;
  roles: string[];
  total: number;
  acknowledged: number;
  pending: number;
  outside_scope: number;
};

export type PolicyInput = {
  policy: PolicyFacts;
  /** null while loading or when the status could not be read. */
  ack: PolicyAckFacts | null;
  /** `GET /policies/{id}/reviews`: an open review has no `actual_review_date`. */
  reviews: { actual_review_date: string | null }[];
  /** The header primary's label ("Publish", "Submit for review", …): notes that point at
   *  it offer the jump only when it is that action. */
  primaryLabel: string | null;
};

/* -------------------------------------------------------------- helpers ----- */

export type PolicyPubState = "published" | "approved" | "under_review" | "draft" | "retired";

/** Where the document stands. Approval can arrive through the lifecycle before the
 *  status is written back, so an approved workflow counts as approved (as Publish does). */
export function policyPubState(p: Pick<PolicyFacts, "status" | "workflow_status">): PolicyPubState {
  if (p.status === "published") return "published";
  if (p.status === "retired") return "retired";
  if (p.status === "approved" || p.workflow_status === "approved") return "approved";
  if (p.status === "under_review" || p.workflow_status === "in_review") return "under_review";
  return "draft";
}

/** Published (or approved) as a document while Record approval is still Draft or In
 *  review: nobody approved the content staff are asked to acknowledge. Reads the page's
 *  governance state, else the record's own `workflow_status`. */
export function policyPublishedUnapproved(p: Pick<PolicyFacts, "status" | "workflow_status">, workflowState: string | null): boolean {
  const ws = workflowState ?? p.workflow_status;
  return p.status === "published" && (ws === "draft" || ws === "in_review");
}

/** The policy has no text and no document link on the record (and does not keep its
 *  document in the attachments). Pure: strips the rich text's tags itself. */
export function policyHasNoText(p: Pick<PolicyFacts, "body" | "url" | "use_attachments">): boolean {
  if (p.use_attachments) return false;
  const text = (p.body ?? "").replace(/<[^>]*>/g, " ").replace(/&nbsp;|&#160;/g, " ").trim();
  return !text && !(p.url ?? "").trim();
}

/** The acknowledgement count's colour: green only when everyone in scope has acknowledged,
 *  amber while anyone is still to, neutral when nobody is in scope. */
export function policyAckTone(ack: Pick<PolicyAckFacts, "acknowledged" | "total">): "low" | "medium" | "neutral" {
  return progressTone(ack.acknowledged, ack.total);
}

/** Publishing needs an approved policy (the server answers 409 otherwise). */
export function policyCanPublish(p: Pick<PolicyFacts, "status" | "workflow_status">): boolean {
  return p.status !== "published" && (p.workflow_status === "approved" || p.status === "approved");
}

const refLabel = (x: PolicyRef) => x.reference || x.title || x.name || "";

/** "A, B and C" — at most `max` labels, then "and k more". */
function refsText(items: PolicyRef[] | undefined, max = 3): string {
  const labels = (items ?? []).map(refLabel).filter(Boolean);
  if (labels.length <= max) return joinList(labels);
  return `${labels.slice(0, max).join(", ")} and ${labels.length - max} more`;
}

/** "Approved" / "In review" / "Retired" — the Record approval state as the header shows it. */
const WORKFLOW_LABEL: Record<string, string> = { in_review: "In review", approved: "Approved", retired: "Retired" };

/** The review cycle in one line: "Annual · last 03 Jul 2026 · 1 review missed", "Annual · never reviewed", or "No review cycle". */
export function policyReviewCycleText(
  p: Pick<PolicyFacts, "review_frequency" | "last_review_date"> & { expired_reviews?: number | null },
  fmt: Fmt,
): string {
  if (!p.review_frequency || p.review_frequency === "none") return "No review cycle";
  return `${sentenceCase(p.review_frequency)} · ${p.last_review_date ? `last ${fmt.date(p.last_review_date)}` : "never reviewed"}${missedReviewsText(p.expired_reviews)}`;
}

/** The Sign-off card's "Publication" row: its badge word and sentence. `warn` when the
 *  published version was never approved (Record approval still Draft or In review). */
export function policyPublicationRow(
  p: Pick<PolicyFacts, "status" | "workflow_status" | "published_at">,
  fmt: Fmt,
  workflowState: string | null = null,
): {
  state: "published" | "retired" | "not_published";
  text: Seg[];
  warn?: boolean;
} {
  const st = policyPubState(p);
  if (st === "published" && policyPublishedUnapproved(p, workflowState)) {
    return {
      state: "published", warn: true,
      text: ["Published ", { b: fmt.date(p.published_at) }, " without an approval: staff are asked to acknowledge content nobody approved."],
    };
  }
  if (st === "published") return { state: "published", text: ["Published ", { b: fmt.date(p.published_at) }, " — staff can acknowledge it."] };
  if (st === "retired") return { state: "retired", text: ["Retired — no longer binding on staff."] };
  if (policyCanPublish(p)) return { state: "not_published", text: ["Approved — publishing makes it binding on staff. Its author cannot publish it."] };
  return { state: "not_published", text: ["Publish opens once the policy is approved: submit it for review, and an independent approver approves it."] };
}

/** An exception's register state (B3); an older API sends none. */
const exceptionLive = (x: PolicyExceptionRef) => x.status === "approved" || x.status === "pending";

/** The per-item note on a linked exception (B3): "Approved · expires 03 Jan 2027",
 *  "Expired 30 Jun 2026", "Rejected"; null when the API sent no status. */
export function policyExceptionNote(x: PolicyExceptionRef, fmt: Fmt): string | null {
  return exceptionStateText(x.status, x.expires_at, fmt);
}

/* ---------------------------------------------------------------- tiles ----- */

export function policyTiles({ policy: p, ack, reviews }: PolicyInput, ctx: Ctx): TileModel[] {
  const { fmt, gov } = ctx;
  const st = policyPubState(p);
  const successors = refsText(p.superseded_by);

  // Published without an approval is not the green, settled state: amber, like the
  // Sign-off card's "Published, not approved" row.
  const pubValue: Record<PolicyPubState, TileValue> = {
    published: { text: "Published", tone: policyPublishedUnapproved(p, gov.workflowState) ? "medium" : "low", badge: true },
    approved: { text: "Approved", tone: "info", badge: true },
    under_review: { text: "Under review", tone: "medium", badge: true },
    retired: { text: "Retired", tone: "neutral", badge: true },
    draft: { text: "Draft", tone: "hollow" },
  };
  const pubBecause: Record<PolicyPubState, Seg[]> = {
    published: [
      p.published_at ? `Published ${fmt.date(p.published_at)}; ` : "Published; ",
      `effective ${p.effective_date ? fmt.date(p.effective_date) : "on publication"}.`,
    ],
    approved: ["Approved, not yet published — publishing makes it binding on staff; its author can't publish it."],
    under_review: ["In review: an independent approver approves it before it can be published."],
    retired: [`Retired${successors ? ` when ${successors} was published` : ""}.`],
    draft: ["Draft: submit for review; an independent approver approves before it can be published."],
  };
  const pubBasis: Basis =
    st === "draft" || st === "under_review" || policyPublishedUnapproved(p, gov.workflowState)
      ? { kind: "missing", text: "Not approved" }
      : gov.workflowState === null
        ? { kind: "missing", text: "Approval status not shown" }
        : gov.approvalSteps > 0
          ? { kind: "evidenced", text: "Approval on file" }
          : { kind: "declared", text: gov.lastStep?.action === "import" ? "Imported, no approver recorded" : "No approval step on file" };

  const sup = p.supersedes_ref ? refLabel(p.supersedes_ref) : "";
  const versionBecause: Seg[] =
    sup && successors ? [`Supersedes ${sup}; superseded by ${successors}.`]
    : sup ? [`Supersedes ${sup}.`]
    : successors ? [`Superseded by ${successors}.`]
    : ["First version on file."];

  let ackTile: TileModel;
  if (st !== "published") {
    ackTile = {
      key: "ack", label: "Acknowledgement", section: "acknowledgement",
      value: { text: "Not open", tone: "hollow" },
      because: ["Opens once the policy is published."],
      basis: { kind: "missing", text: "Not published" },
    };
  } else if (!ack) {
    ackTile = {
      key: "ack", label: "Acknowledgement", section: "acknowledgement",
      value: { text: "Not shown", tone: "hollow" },
      because: ["The acknowledgement status could not be loaded."],
      basis: { kind: "missing", text: "Not on file" },
    };
  } else {
    const pct = ack.total > 0 ? Math.round((ack.acknowledged / ack.total) * 100) : null;
    const scope = ack.scope === "roles" ? truncate(joinList(ack.roles) || "the policy's roles", 60) : "everyone";
    // The colour follows progress (green only when everyone has acknowledged); with
    // nobody acknowledged yet there is no acknowledgement record to rest on.
    const tone = policyAckTone(ack);
    ackTile = {
      key: "ack", label: "Acknowledgement", section: "acknowledgement",
      value: { text: `${ack.acknowledged} of ${ack.total}`, unit: pct === null ? undefined : `(${pct}%)`, tone: tone === "neutral" ? undefined : tone },
      because: [
        { b: String(ack.pending) },
        ` still to acknowledge; in scope: ${scope}.`,
        ...(ack.outside_scope > 0 ? [` +${ack.outside_scope} from outside the scope.`] : []),
      ],
      basis: ack.total === 0 ? { kind: "missing", text: "Nobody in scope" }
        : ack.acknowledged === 0 ? { kind: "missing", text: "No acknowledgement yet" }
        : { kind: "evidenced", text: "From acknowledgement records" },
    };
  }

  const openReviews = reviews.filter((r) => !r.actual_review_date).length;
  const cycle = p.review_frequency && p.review_frequency !== "none" ? `${sentenceCase(p.review_frequency)} cycle` : "No review cycle";
  const reviewValue: TileValue = p.is_review_overdue
    ? { text: "Overdue", tone: "high", badge: true }
    : p.next_review_date
      ? { text: `Due ${fmt.date(p.next_review_date)}` }
      : { text: "Not scheduled", tone: "hollow" };

  // Exceptions. With B3 each carries its state and expiry: the next expiry among those in
  // force, and how many have lapsed. Without it the tile names them only.
  const exceptions = p.exceptions ?? [];
  const withState = exceptions.some((x) => typeof x.status === "string" && x.status !== "");
  const nextExpiry = exceptions
    .filter((x) => exceptionLive(x) && x.expires_at)
    .map((x) => x.expires_at as string)
    .sort()[0];
  const lapsed = exceptions.filter((x) => x.status === "expired").length;
  const excBecause: Seg[] = !exceptions.length
    ? ["No exception is granted against this policy."]
    : [
        refsText(exceptions),
        withState && nextExpiry ? `; next expiry ${fmt.date(nextExpiry)}` : "",
        withState && lapsed ? `; ${lapsed} expired` : "",
        ".",
      ];

  return [
    { key: "publication", label: "Publication", section: "document", value: pubValue[st], because: pubBecause[st], basis: pubBasis },
    {
      key: "version", label: "Version", section: "versions",
      value: { text: `v${p.version}` },
      because: versionBecause,
      basis: { kind: "derived", text: "From version links" },
    },
    ackTile,
    {
      key: "review", label: "Review", section: "reviews",
      value: reviewValue,
      because: [`${cycle}; ${p.last_review_date ? `last reviewed ${fmt.date(p.last_review_date)}` : "never reviewed"}; ${openReviews ? plural(openReviews, "scheduled review") : "no scheduled review"} open.`],
      basis: { kind: "derived", text: "From the review schedule" },
    },
    {
      key: "coverage", label: "Implemented by", section: "linked",
      value: { text: `${plural(p.controls.length, "control")} · ${plural(p.requirements.length, "requirement")}` },
      because: [p.controls.length ? `Implemented by ${refsText(p.controls)}.` : "No control implements it."],
      basis: { kind: "derived", text: "From links" },
    },
    {
      key: "exceptions", label: "Exceptions", section: "linked",
      value: exceptions.length ? { text: plural(exceptions.length, "exception") } : { text: "None" },
      because: excBecause,
      basis: { kind: "derived", text: "From links" },
    },
  ];
}

/* ------------------------------------------------------------- headline ----- */

export function policyHeadline({ policy: p, ack }: PolicyInput, ctx: Ctx): Seg[] {
  const { fmt, gov } = ctx;
  const st = policyPubState(p);
  const head =
    st === "published" ? `Published v${p.version}${p.published_at ? ` on ${fmt.date(p.published_at)}` : ""}${policyPublishedUnapproved(p, gov.workflowState) ? " without approval" : ""}`
    : st === "approved" ? "Approved, not published"
    : st === "under_review" ? `In review v${p.version}`
    : st === "retired" ? `Retired v${p.version}`
    : `Draft v${p.version}`;
  const ackPart: Seg[] =
    st !== "published" ? ["; acknowledgement not open"]
    : ack ? ["; ", { b: `${ack.acknowledged} of ${ack.total}` }, " acknowledged"]
    : [];
  const review =
    p.is_review_overdue && p.next_review_date ? `review overdue since ${fmt.date(p.next_review_date)}`
    : p.is_review_overdue ? "review overdue"
    : p.next_review_date ? `review due ${fmt.date(p.next_review_date)}`
    : "no review scheduled";
  return [head, ...ackPart, `; ${review}.`];
}

/* ---------------------------------------------------------- open points ----- */

export function policyOpenPoints({ policy: p, ack, primaryLabel }: PolicyInput, ctx: Ctx): OpenPoint[] {
  const { fmt, gov } = ctx;
  const st = policyPubState(p);
  const gaps: OpenPoint[] = [];
  const notes: OpenPoint[] = [];

  if (!p.owner_id && !(p.owner || "").trim()) {
    gaps.push({ id: "policy.owner", level: "gap", text: ["No policy owner."], action: { kind: "edit", target: "general", label: "Assign owner" } });
  }
  if (policyPublishedUnapproved(p, gov.workflowState)) {
    const ws = gov.workflowState ?? p.workflow_status;
    gaps.push({
      id: "policy.published_unapproved", level: "gap",
      text: [`Published, but its content has not been approved (record approval: ${ws === "in_review" ? "In review" : "Draft"}).`],
      action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
    });
  }
  if (st === "published" && policyHasNoText(p)) {
    gaps.push({
      id: "policy.published_no_text", level: "gap",
      text: ["Published with no policy text or document link: staff are acknowledging nothing."],
      action: { kind: "edit", target: "content", label: "Edit text" },
    });
  }
  if (!p.approving_authority_ref) {
    gaps.push({ id: "policy.authority", level: "gap", text: ["No approving authority named."], action: { kind: "edit", target: "governance", label: "Name authority" } });
  }
  if (p.status === "published" && (p.superseded_by?.length ?? 0) > 0) {
    gaps.push({
      id: "policy.superseded_but_published", level: "gap",
      text: [`Still published although ${refsText(p.superseded_by)} supersedes it.`],
      action: { kind: "section", target: "versions", label: "See versions" },
    });
  }
  if (p.is_review_overdue) {
    // B1: the server says whether this viewer may attest (the review is native to the
    // attestation). Refused → point at the Sign-off card, which prints the reason; an
    // older API sends no verdict and the Attest… jump stays (the refusal shows inline).
    // Decision 6: a policy whose approval is incomplete is approved before it is attested.
    const att = gov.attestation;
    gaps.push({
      id: "policy.review_overdue", level: "gap",
      text: [p.next_review_date ? `Review overdue since ${fmt.date(p.next_review_date)}.` : "Review overdue."],
      action: approvalBlocksAttest(gov) || att?.canAttest === false
        ? attestFix(gov) ?? { kind: "focus", target: "rec-signoff", label: "See sign-off" }
        : { kind: "attest", target: "attest", label: "Attest…" },
    });
  }
  // Decision 9: every policy attestation needs an independent second signature, so a
  // policy certified but not yet confirmed has not completed its review.
  const waiting = awaitingConfirmationPoint("policy", gov, fmt);
  if (waiting) gaps.push(waiting);
  const ws = gov.workflowState;
  if ((ws === "approved" || ws === "in_review" || ws === "retired") && gov.approvalSteps === 0) {
    gaps.push({
      id: "policy.approved_without_step", level: "gap",
      text: [approvalWithoutStepText(gov, WORKFLOW_LABEL[ws])],
      action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
    });
  }

  if (st === "approved") {
    notes.push({
      id: "policy.not_published", level: "note", text: ["Approved, not yet published"],
      action: primaryLabel === "Publish" ? { kind: "focus", target: "rec-primary", label: "Publish" } : undefined,
    });
  }
  if (st === "published" && ack && ack.pending > 0) {
    notes.push({
      id: "policy.ack_pending", level: "note", text: [`${plural(ack.pending, "person", "people")} still to acknowledge`],
      action: { kind: "section", target: "acknowledgement", label: "See who" },
    });
  }
  if (st === "published" && ack && ack.total === 0) {
    notes.push({ id: "policy.scope_empty", level: "note", text: ["Nobody is in scope to acknowledge it"], action: { kind: "edit", target: "governance", label: "Set roles" } });
  }
  if (textOnlyPerson(p.owner_id, p.owner)) {
    notes.push({
      id: "policy.owner_text", level: "note", text: [`Owner is a text label (“${truncate(p.owner, 40)}”), not a person`],
      action: { kind: "edit", target: "general", label: "Pick a person" },
    });
  }
  if (p.controls.length === 0) {
    notes.push({ id: "policy.no_controls", level: "note", text: ["No control implements it"], action: { kind: "edit", target: "links", label: "Link controls" } });
  }
  return [...gaps, ...notes];
}

/** The line OpenPoints shows when nothing is open. */
export const POLICY_CLEAR_TEXT = "No open points: owner, approving authority, publication and review are on file.";
