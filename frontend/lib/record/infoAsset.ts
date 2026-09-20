/* Record wording for the information asset (record-page-spec §4.3), plus the asset
   pieces the IT asset shares (lib/record/itAsset.ts imports them from here).

   Every judgement sentence on the information asset page lives here: the six tiles, the
   headline, the open points, the Classification table's Agreement column, the fact texts
   and the page's fixed copy (hints, empty states, clear text). The page renders what these
   functions return and adds no wording of its own. Wording changes update the fixtures in
   lib/record/__fixtures__/ (`npm run check:record-copy`) and need a Compliance reviewer.

   Pure: imports only ./text and ./types, so the fixture runner executes it under Node.
   It explains the server's judgements (effective_criticality = business value, the
   server's review_status, the B8 bands and appetite status) and never recomputes them;
   the one client projection is the documented CIA scheme rank (`schemeRank`).

   Degrade paths (fields added in round 2 that an older API does not send):
   - B8 `risks[]` scores / bands / appetite: absent, or null for a viewer without
     risk:read → the Risk exposure tile lists labels only, the headline has no breach
     count and the Risks group shows no meta.
   - B3 `exceptions[]` status / expiry: absent → no meta on the Exceptions group.
   - B1 `can_attest` / B4 `native_review`: read through `ctx.gov.attestation`; unknown
     `canAttest` (null) keeps the attest fix, false drops it; without native review the
     overdue-review fix edits the review cycle instead of attesting. */

import { approvalWithoutStepText, attestFix, attestationNotePoint, critRank, exceptionStateText, joinList, missedReviewsText, plural, rowLabel, schemeRank, sentenceCase, truncate } from "./text";
import type { Basis, Ctx, Fmt, GovModel, OpenPoint, PointAction, Seg, TileModel, TileValue } from "./types";

/* ------------------------------------------------------------------ input types */

/** `LinkRef {id, label}` as GET /assets/{id} returns most relations. */
export type AssetLinkRef = { id: string; label: string };

/** `GraphRef` (reverse links: controls, threats, vulnerabilities, third parties…). */
export type AssetGraphRef = { id: string; reference?: string; title?: string; name?: string };

/** A risk on the asset. B8 adds everything after `label`; each may be absent (older API)
 *  or null (the viewer may not read risks, or the tenant scale was not loaded). */
export type AssetRiskRef = AssetLinkRef & {
  reference?: string;
  inherent_score?: number | null;
  inherent_severity?: string | null;
  residual_score?: number | null;
  residual_severity?: string | null;
  /** "within_appetite" | "elevated" | "breach" | null */
  appetite_status?: string | null;
};

/** A linked exception. B3 adds `status` (an approved exception past expiry reads "expired") and `expires_at`. */
export type AssetExceptionRef = AssetLinkRef & { status?: string | null; expires_at?: string | null };

/** The information asset in a dependency; B8 adds the business value an IT asset inherits. */
export type HostedInfoRef = AssetLinkRef & { business_value?: string | null };

export type AssetDependency = {
  id: string;
  relationship_type: string;
  notes: string;
  information_asset: HostedInfoRef | null;
  it_asset: AssetLinkRef | null;
};

/** The distinct assets on one side of `deps`, by id in first-seen order: one pair can be
 *  linked under several relationship types ("hosts" and "backs_up"), and counting rows
 *  would name the same asset twice. A link whose asset is archived (no ref) counts once
 *  each, as "an archived asset". */
export function distinctLinked(deps: readonly AssetDependency[], side: "it_asset" | "information_asset"): string[] {
  const seen = new Map<string, string>();
  let archived = 0;
  for (const d of deps) {
    const ref = d[side];
    if (!ref) archived++;
    else if (!seen.has(ref.id)) seen.set(ref.id, ref.label);
  }
  return [...seen.values(), ...Array.from({ length: archived }, () => "an archived asset")];
}

export type AssetClassificationRef = { id: string; name: string; value: number; type_name: string };

export type ClassificationTypeRow = {
  id: string;
  name: string;
  description?: string;
  classifications: { id: string; name: string; value: number; criteria: string }[];
};

/** The review-cycle fields both asset types carry. */
export type AssetReviewFields = {
  review_frequency: string;
  next_review_date: string | null;
  last_review_date: string | null;
  /** "none" | "current" | "overdue" (server-computed from next_review_date). */
  review_status: string;
  expired_reviews?: number;
};

/** What the information asset rules read from GET /assets/{id}. */
export type InfoAssetRecord = AssetReviewFields & {
  id: string;
  name: string;
  description: string;
  confidentiality: string;
  integrity: string;
  availability: string;
  business_value: string;
  effective_criticality: string;
  information_owner: string;
  data_categories: string;
  records_volume: string;
  potential_liabilities?: string;
  self_assessed: boolean;
  assessed_by: string;
  assessed_date: string | null;
  rto_hours?: number | null;
  rpo_hours?: number | null;
  classifications?: AssetClassificationRef[];
  dependencies: AssetDependency[];
  risks?: AssetRiskRef[];
  controls?: AssetGraphRef[];
};

/** `InfoAssetInput` = the asset read and GET /asset-classification-types. */
export type InfoAssetInput = { asset: InfoAssetRecord; classTypes: ClassificationTypeRow[] };

/* ------------------------------------------------------------ shared small helpers */

/** A severity tile value: the badge, or hollow "Not assessed". */
export function sevValue(v: string | null | undefined): TileValue {
  const k = (v ?? "").toLowerCase();
  if (!k) return { text: "Not assessed", tone: "hollow" };
  const tone = critRank(k) ? (k as "low" | "medium" | "high" | "critical") : "neutral";
  return { text: sentenceCase(k), tone, badge: true };
}

/** "A and B" / "A, B, +3 more": the first `k` names (each truncated), then a count. */
export function someNames(names: readonly string[], k: number, each = 36): string {
  const shown = names.slice(0, k).map((n) => truncate(n, each));
  const rest = names.length - shown.length;
  return rest > 0 ? `${shown.join(", ")}, +${rest} more` : joinList(shown);
}

/** "A.5.15 Access Control Policy" (reference and name, either alone). */
export function graphName(g: AssetGraphRef): string {
  return rowLabel(g.reference, (g.title || g.name || "").trim(), 200) || "Untitled";
}

/** The row label of a linked record for accessible names ("Unlink Customer master data"). */
export const linkRowLabel = (ref: AssetLinkRef | null | undefined): string => (ref?.label ?? "").trim() || "archived asset";

const APPROVAL_WITHOUT_STEP = new Set(["approved", "in_review", "retired"]);

/** The gap every asset shares: Record approval shows a state no approval step backs. */
export function approvedWithoutStepPoint(prefix: string, gov: GovModel): OpenPoint | null {
  const ws = gov.workflowState;
  if (!ws || !APPROVAL_WITHOUT_STEP.has(ws) || gov.approvalSteps !== 0) return null;
  return {
    id: `${prefix}.approved_without_step`,
    level: "gap",
    text: [approvalWithoutStepText(gov, sentenceCase(ws))],
    action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
  };
}

/** The attest fix, unless the server said this viewer may not attest (B1) or the
 *  approval must come first (decision 6: Submit for review / See approval). */
function attestAction(gov: GovModel): PointAction | undefined {
  return attestFix(gov);
}

/** The note every asset shares: approved and never attested ("Never attested"), or in
 *  review ("Approve before attesting…"). Draft and retired raise none. An attestation
 *  awaiting its required second signature (decision 9) speaks before either. */
export function neverAttestedPoint(prefix: string, gov: GovModel, fmt?: Pick<Fmt, "date">): OpenPoint | null {
  return attestationNotePoint(prefix, gov, { fmt });
}

/** Overdue review: attest when attesting records the review (B4, `nativeReview`),
 *  otherwise open the review-cycle tab. */
export function reviewOverduePoint(prefix: string, a: AssetReviewFields, ctx: Ctx, cycleTab: string): OpenPoint | null {
  if (a.review_status !== "overdue") return null;
  const action: PointAction | undefined = ctx.gov.attestation?.nativeReview
    ? attestAction(ctx.gov)
    : { kind: "edit", target: cycleTab, label: "Edit review cycle" };
  return {
    id: `${prefix}.review_overdue`,
    level: "gap",
    text: [`Review overdue since ${ctx.fmt.date(a.next_review_date)}.`],
    action,
  };
}

/** Details › Review cycle: "Annual · last 03 Jul 2026" or "Annual · never reviewed", with
 *  " · 2 reviews missed" only when some were. */
export function reviewCycleText(a: AssetReviewFields, fmt: Fmt): string {
  const last = a.last_review_date ? `last ${fmt.date(a.last_review_date)}` : "never reviewed";
  if (!a.review_frequency || a.review_frequency === "none") return `No review cycle · ${last}`;
  return `${sentenceCase(a.review_frequency)} · ${last}${missedReviewsText(a.expired_reviews)}`;
}

/** The header's "Review status" for both asset types. A never-reviewed asset with a date
 *  ahead reads "Not yet reviewed", first due …, not a green "Current" (which implies a
 *  review took place). Sub-lines use one format: "next 03 Jul 2027 · Annual · last …". */
export function assetReviewStatusView(a: AssetReviewFields, fmt: Fmt): { text: string; tone: "high" | "low" | "hollow"; sub: string } {
  const st = (a.review_status ?? "").toLowerCase();
  const next = a.next_review_date ? fmt.date(a.next_review_date) : null;
  const cadence = a.review_frequency && a.review_frequency !== "none" ? sentenceCase(a.review_frequency) : null;
  const last = a.last_review_date ? fmt.date(a.last_review_date) : null;
  const join = (xs: (string | null)[]) => xs.filter(Boolean).join(" · ");
  if (st === "overdue" && next) return { text: `Overdue since ${next}`, tone: "high", sub: join([cadence, (last ? `last ${last}` : "never reviewed")]) };
  if (next && !last) return { text: "Not yet reviewed", tone: "hollow", sub: join([`first due ${next}`, cadence]) };
  if (st === "current" || next) return { text: "Current", tone: "low", sub: join([next ? `next ${next}` : null, cadence, (last ? `last ${last}` : "never reviewed")]) };
  return { text: "Not scheduled", tone: "hollow", sub: join([cadence, (last ? `last ${last}` : "never reviewed")]) };
}

/** The "Review status" header hint: honest about whether attesting moves the date (B4). */
export function reviewStatusHint(nativeReview: boolean): string {
  return nativeReview
    ? "The asset's review cycle. Attesting the asset records its review and moves the next date."
    : "The asset's own review cycle, tracked apart from its attestation.";
}

/** The "Record approval" hint for both asset types (slot 2, after Review status). */
export const ASSET_APPROVAL_HINT = "Whether this record's content has been signed off. Separate from its review cycle.";

/* --------------------------------------------------------- risk exposure (B8) */

const APPETITE_RANK: Record<string, number> = { within_appetite: 1, elevated: 2, breach: 3 };

/** "in breach" / "elevated" / "within appetite" / "not measured against appetite". */
export function appetiteWord(status: string | null | undefined): string {
  const k = (status ?? "").toLowerCase();
  if (k === "breach") return "in breach";
  if (k === "elevated") return "elevated";
  if (k === "within_appetite") return "within appetite";
  return "not measured against appetite";
}

const scored = (r: AssetRiskRef) =>
  (r.inherent_score !== null && r.inherent_score !== undefined) || (r.residual_score !== null && r.residual_score !== undefined);

/** True when the risk refs carry B8 scores the viewer may see. */
export function hasRiskExposure(risks: readonly AssetRiskRef[] | undefined): boolean {
  return (risks ?? []).some(scored);
}

/** The score and band that represent current exposure: residual when assessed, else inherent. */
export function effectiveExposure(r: AssetRiskRef): { score: number | null; severity: string | null } {
  if (r.residual_score !== null && r.residual_score !== undefined) {
    return { score: r.residual_score, severity: r.residual_severity ?? null };
  }
  return { score: r.inherent_score ?? null, severity: r.inherent_severity ?? null };
}

/** The worst linked risk: appetite band, then the effective band, then the effective score. */
export function worstRisk(risks: readonly AssetRiskRef[]): AssetRiskRef | null {
  let best: AssetRiskRef | null = null;
  let key: [number, number, number] = [-1, -1, -1];
  for (const r of risks) {
    if (!scored(r)) continue;
    const e = effectiveExposure(r);
    const k: [number, number, number] = [APPETITE_RANK[(r.appetite_status ?? "").toLowerCase()] ?? 0, critRank(e.severity), e.score ?? 0];
    if (k[0] > key[0] || (k[0] === key[0] && (k[1] > key[1] || (k[1] === key[1] && k[2] > key[2])))) {
      best = r;
      key = k;
    }
  }
  return best;
}

export const breachCount = (risks: readonly AssetRiskRef[] | undefined): number =>
  (risks ?? []).filter((r) => (r.appetite_status ?? "").toLowerCase() === "breach").length;

/** A risk's row label, "R-002 Ransomware encrypts production systems": the API sends `reference`
 *  and the risk's name as `label` (an older API sent the reference as the label, so the name is dropped then). */
export function riskRowLabel(r: AssetRiskRef): string {
  const ref = (r.reference ?? "").trim();
  const label = (r.label ?? "").trim();
  return rowLabel(ref || label, ref && label !== ref ? label : "", 80);
}

/** Linked records › Risks meta with B8: "Critical 20 · in breach"; null without scores. */
export function riskGroupMeta(r: AssetRiskRef): string | null {
  if (!scored(r)) return null;
  const e = effectiveExposure(r);
  const band = [e.severity ? sentenceCase(e.severity) : "", e.score !== null ? String(e.score) : ""].filter(Boolean).join(" ");
  const appetite = r.appetite_status ? appetiteWord(r.appetite_status) : "";
  return [band, appetite].filter(Boolean).join(" · ") || null;
}

/** Linked records › Exceptions meta with B3: "Approved · expires 03 Jan 2027", "Expired 03 Jan 2026". */
export function exceptionGroupMeta(x: AssetExceptionRef, fmt: Fmt): string | null {
  return exceptionStateText(x.status, x.expires_at, fmt);
}

/** The Risk exposure tile, shared by both asset types (§4.3, §4.4). */
export function riskExposureTile(risks: readonly AssetRiskRef[] | undefined): TileModel {
  const rs = risks ?? [];
  const n = rs.length;
  const base = { key: "risk", label: "Risk exposure", section: "linked", basis: { kind: "derived", text: "From risk links" } as Basis };
  if (n === 0) {
    return {
      ...base,
      value: { text: "No risks", tone: "hollow" },
      because: ["No risk linked — Generate risks proposes them from the scenario library."],
    };
  }
  const worst = hasRiskExposure(rs) ? worstRisk(rs) : null;
  if (!worst) {
    // Degrade (no B8, or the viewer may not read risks): the labels only.
    return {
      ...base,
      value: { text: plural(n, "risk") },
      because: [`${someNames(rs.map(riskRowLabel), 3, 30)} linked; ratings are in the risk report.`],
    };
  }
  const k = breachCount(rs);
  const e = effectiveExposure(worst);
  const inhSev = worst.inherent_severity ? ` (${sentenceCase(worst.inherent_severity)})` : "";
  const inh = worst.inherent_score !== null && worst.inherent_score !== undefined ? String(worst.inherent_score) : null;
  const res = worst.residual_score !== null && worst.residual_score !== undefined ? String(worst.residual_score) : null;
  const because: Seg[] = [`${truncate(riskRowLabel(worst), 48)}: inherent `];
  because.push(inh ? { b: inh } : "not scored", inh ? inhSev : "", ", residual ");
  because.push(res ? { b: res } : "not recorded", `, ${appetiteWord(worst.appetite_status)}.`);
  const value: TileValue = k
    ? { text: plural(n, "risk"), tone: "critical", unit: `${k} in breach` }
    : { text: plural(n, "risk"), unit: e.severity ? `worst ${e.severity.toLowerCase()}` : undefined };
  return { ...base, value, because: because.filter((s) => s !== "") };
}

/** The headline's risk clause: "1 linked risk, 1 in breach" / "2 linked risks" / "no linked risk". */
export function riskClause(risks: readonly AssetRiskRef[] | undefined): string {
  const n = (risks ?? []).length;
  if (!n) return "no linked risk";
  const k = hasRiskExposure(risks) ? breachCount(risks) : 0;
  return k ? `${plural(n, "linked risk")}, ${k} in breach` : plural(n, "linked risk");
}

/* ------------------------------------------------------ CIA against the scheme */

export const AXES = [
  { key: "confidentiality", label: "Confidentiality" },
  { key: "integrity", label: "Integrity" },
  { key: "availability", label: "Availability" },
] as const;
export type AxisKey = (typeof AXES)[number]["key"];
const AXIS_KEYS = new Set<string>(AXES.map((x) => x.key));

export type SchemeValue = { name: string; value: number; max: number | null; criteria: string };
export type AxisCheck = {
  key: AxisKey;
  label: string;
  /** The quick rating (used in risk scoring). */
  rating: string;
  /** The tenant scheme's value for this axis, when one is classified. */
  scheme: SchemeValue | null;
  /** schemeRank − ratingRank; null when there is no scheme value or its scale is unknown. */
  diff: number | null;
};

const fmtNum = (v: number) => String(Number(v.toFixed(2)));

/** "level 4 of 4" (or "level 4" when the scale is unknown). */
export const levelText = (s: SchemeValue): string =>
  s.max ? `level ${fmtNum(s.value)} of ${fmtNum(s.max)}` : `level ${fmtNum(s.value)}`;

/** Each C / I / A quick rating reconciled with the tenant's classification scheme. */
export function ciaChecks({ asset, classTypes }: InfoAssetInput): AxisCheck[] {
  return AXES.map(({ key, label }) => {
    const rating = asset[key];
    const mine = (asset.classifications ?? []).filter((c) => (c.type_name || "").trim().toLowerCase() === key);
    const c = mine.reduce<AssetClassificationRef | null>((hi, x) => (!hi || x.value > hi.value ? x : hi), null);
    if (!c) return { key, label, rating, scheme: null, diff: null };
    const type = classTypes.find((t) => t.name.trim().toLowerCase() === key);
    const values = (type?.classifications ?? []).map((x) => x.value);
    const top = values.length ? Math.max(...values) : 0;
    const max = top > 0 ? top : null;
    const criteria = (type?.classifications.find((x) => x.id === c.id)?.criteria ?? "").trim();
    const diff = max !== null ? schemeRank(c.value, max) - critRank(rating) : null;
    return { key, label, rating, scheme: { name: c.name, value: c.value, max, criteria }, diff };
  });
}

export const conflictsOf = (checks: readonly AxisCheck[]): AxisCheck[] => checks.filter((c) => c.diff !== null && c.diff !== 0);

/** The scheme cell: "Mission-critical · level 4 of 4", or null when no scheme value. */
export const schemeCellText = (c: AxisCheck): string | null => (c.scheme ? `${c.scheme.name} · ${levelText(c.scheme)}` : null);

/** The Agreement cell of the Classification table. */
export function agreementText(c: AxisCheck): { text: string; tone: "ok" | "differs" | "none" } {
  if (!c.scheme) return { text: "—", tone: "none" };
  if (c.diff === null) return { text: "Scheme levels not available", tone: "none" };
  if (c.diff === 0) return { text: "Agrees", tone: "ok" };
  const n = Math.abs(c.diff);
  return { text: `Scheme is ${n} level${n === 1 ? "" : "s"} ${c.diff > 0 ? "higher" : "lower"}`, tone: "differs" };
}

/** The C / I / A scheme values the Classification table does not show: the table reads
 *  the highest value per axis, so a second value on the same axis ("Confidentiality:
 *  Internal" beside "Secret") is listed under it as a fact instead of disappearing:
 *  label "Confidentiality (also classified)", value "Internal · level 2 of 4". */
export function alsoClassified({ asset, classTypes }: InfoAssetInput): { key: string; label: string; value: string }[] {
  const out: { key: string; label: string; value: string }[] = [];
  for (const { key, label } of AXES) {
    const mine = (asset.classifications ?? []).filter((c) => (c.type_name || "").trim().toLowerCase() === key);
    if (mine.length < 2) continue;
    const top = mine.reduce((hi, x) => (x.value > hi.value ? x : hi));
    const type = classTypes.find((t) => t.name.trim().toLowerCase() === key);
    const values = (type?.classifications ?? []).map((x) => x.value);
    const max = values.length && Math.max(...values) > 0 ? Math.max(...values) : null;
    for (const c of mine) {
      if (c.id === top.id) continue;
      out.push({ key: `also-${c.id}`, label: `${label} (also classified)`, value: `${c.name} · ${levelText({ name: c.name, value: c.value, max, criteria: "" })}` });
    }
  }
  return out;
}

/** Classifications on other axes than C, I and A, listed under the table as facts. */
export function otherClassifications(a: InfoAssetRecord): AssetClassificationRef[] {
  return (a.classifications ?? []).filter((c) => !AXIS_KEYS.has((c.type_name || "").trim().toLowerCase()));
}

/** The highest of the three quick ratings (first axis wins a tie). */
function highestCia(a: InfoAssetRecord): { label: string; value: string } {
  let best: { label: string; value: string } = { label: AXES[0].label, value: a[AXES[0].key] };
  for (const ax of AXES) if (critRank(a[ax.key]) > critRank(best.value)) best = { label: ax.label, value: a[ax.key] };
  return best;
}

/* ------------------------------------------------------------ fact texts */

export const hasPii = (a: { data_categories?: string | null }): boolean => (a.data_categories || "").toLowerCase().includes("pii");

/** Classification › Self-assessment: "Completed by Head of Retail on 03 Jul 2026" or "Pending". */
export function selfAssessmentText(a: InfoAssetRecord, fmt: Fmt): string {
  if (!a.self_assessed) return "Pending";
  const by = (a.assessed_by ?? "").trim();
  return `Completed${by ? ` by ${by}` : ""}${a.assessed_date ? ` on ${fmt.date(a.assessed_date)}` : ""}`;
}

/** "~4.2M" → "~4.2M records"; free text ("4.2M customers") is left as written. */
export function volumeText(vol: string): string {
  const v = truncate(vol, 40);
  return /^[~≈<>+]?\s*[\d.,]+\s*[kKmMbB]?\+?$/.test(v) ? `${v} records` : v;
}

/** Details › Recovery objectives: "RTO 4 h · RPO not set". */
export function recoveryText(a: { rto_hours?: number | null; rpo_hours?: number | null }): string {
  const h = (v: number | null | undefined) => (v !== null && v !== undefined ? `${v} h` : "not set");
  return `RTO ${h(a.rto_hours)} · RPO ${h(a.rpo_hours)}`;
}

/** The header's "Owning unit · custodian" sub: "user Retail Banking" when a user unit is set. */
export const userUnitSub = (user: AssetLinkRef | null | undefined): string | undefined => (user ? `user ${user.label}` : undefined);

/** The page's fixed copy (hints, empty states, the clear text). */
export const INFO_ASSET_COPY = {
  clearText: "No open points: owner, classification, self-assessment and approval are on file.",
  businessOwnerHint: "The person who sets the business value and signs off the classification.",
  businessOwnerGap: "Not named",
  unitsNotSet: "Not set",
  unitsHint: "Business units, not people.",
  noOwningUnit: "no owning unit",
  noCustodian: "no custodian",
  hostedEmpty: "No IT assets carry this data yet.",
  hostedSub: "they inherit its business value",
  noSchemeValue: "No scheme value",
  businessValueAgreement: "Sets effective criticality",
  noNotes: "No notes",
  archivedLink: "Not available",
  generateHint: "Propose risks for this asset from the scenario library",
} as const;

/* ------------------------------------------------------------------ tiles */

export function infoAssetTiles(input: InfoAssetInput, ctx: Ctx): TileModel[] {
  const a = input.asset;
  const checks = ciaChecks(input);
  const conflicts = conflictsOf(checks);
  const withScheme = checks.filter((c) => c.scheme);
  const checkable = withScheme.filter((c) => c.diff !== null);
  const bv = sentenceCase(a.business_value);

  // 1. Effective criticality — for an information asset it IS the business value.
  const top = highestCia(a);
  // Who set the value: "the business owner" only when one is named AND has confirmed it
  // (self-assessed); otherwise it was typed in and nobody accountable has signed it off.
  const ownerNamed = !!(a.information_owner ?? "").trim();
  const setBy = ownerNamed && a.self_assessed ? "set by the business owner"
    : ownerNamed ? "set by hand; the business owner hasn't confirmed it"
    : "set by hand; no business owner has confirmed it";
  const critBecause: Seg[] = ["Equals business value (", { b: bv }, `), ${setBy}; CIA ratings don't raise it.`];
  if (critRank(top.value) > critRank(a.business_value)) {
    critBecause.push(` ${top.label} is rated `, { b: sentenceCase(top.value) }, " — confirm the value.");
  }
  const by = (a.assessed_by ?? "").trim();
  const critBasis: Basis = a.self_assessed
    ? {
        kind: "evidenced",
        text: truncate(`Self-assessed${by ? ` by ${truncate(by, 24)}` : ""}${a.assessed_date ? ` on ${ctx.fmt.date(a.assessed_date)}` : ""}`, 60),
      }
    : { kind: "declared", text: "Business value not self-assessed" };

  // 2. CIA, reconciled with the classification scheme.
  let ciaBecause: Seg[];
  let ciaBasis: Basis;
  if (conflicts.length === 1) {
    const c = conflicts[0];
    const s = c.scheme as SchemeValue;
    ciaBecause = [`${c.label} is rated `, { b: sentenceCase(c.rating) }, " here but classified ", { b: truncate(s.name, 40) }, ` (${levelText(s)}).`];
    ciaBasis = { kind: "declared", text: "Two ratings disagree" };
  } else if (conflicts.length > 1) {
    ciaBecause = [`${conflicts.length} ratings disagree with the scheme: ${joinList(conflicts.map((c) => c.label.toLowerCase()))}; see the table.`];
    ciaBasis = { kind: "declared", text: "Two ratings disagree" };
  } else if (checkable.length > 0) {
    ciaBecause = ["Consistent with the classification scheme."];
    ciaBasis = { kind: "derived", text: "Checked against the scheme" };
  } else if (withScheme.length > 0) {
    ciaBecause = ["Classified against the scheme, but its levels aren't available to compare."];
    ciaBasis = { kind: "missing", text: "Scheme levels not available" };
  } else {
    ciaBecause = ["No classification-scheme values recorded."];
    ciaBasis = { kind: "declared", text: "Rated by hand only" };
  }

  // 3. Data
  const cats = (a.data_categories ?? "").trim();
  const vol = (a.records_volume ?? "").trim();
  const dataValue: TileValue = hasPii(a)
    ? { text: "Contains PII", tone: "high", badge: true }
    : cats
      ? { text: truncate(cats, 40) }
      : { text: "Not described", tone: "hollow" };
  const dataBecause: Seg[] = cats
    ? [`${truncate(cats, 60)}${vol ? `; ${volumeText(vol)}` : ""}.`]
    : vol
      ? [`No data categories recorded, so PII can't be ruled out; ${volumeText(vol)}.`]
      : ["No data categories or record volume recorded, so PII can't be ruled out."];

  // 4. Hosted on
  const deps = a.dependencies ?? [];
  const hostNames = distinctLinked(deps, "it_asset");

  // 6. Protected by
  const controls = a.controls ?? [];

  return [
    {
      key: "criticality",
      label: "Effective criticality",
      section: "classification",
      value: sevValue(a.effective_criticality),
      because: critBecause,
      basis: critBasis,
    },
    {
      key: "cia",
      label: "Confidentiality · integrity · availability",
      section: "classification",
      value: { text: checks.map((c) => sentenceCase(c.rating) || "Not rated").join(" · ") },
      because: ciaBecause,
      basis: ciaBasis,
    },
    {
      key: "data",
      label: "Data",
      section: "classification",
      value: dataValue,
      because: dataBecause,
      basis: cats ? { kind: "declared", text: "Recorded by hand" } : { kind: "missing", text: "Not on file" },
    },
    {
      key: "hosted",
      label: "Hosted on",
      section: "hosted",
      value: hostNames.length ? { text: plural(hostNames.length, "IT asset") } : { text: "No IT assets", tone: "hollow" },
      because: hostNames.length
        ? [`Carried by ${someNames(hostNames, 2)}; ${hostNames.length === 1 ? "it inherits" : "they inherit"} its `, { b: bv }, " business value."]
        : ["No server or service is linked, so nothing inherits its value."],
      basis: { kind: "derived", text: "From dependency links" },
    },
    riskExposureTile(a.risks),
    {
      key: "protected",
      label: "Protected by",
      section: "linked",
      value: controls.length ? { text: plural(controls.length, "control") } : { text: "No controls", tone: "hollow" },
      because: controls.length
        ? [`${truncate(graphName(controls[0]), 80)}${controls.length > 1 ? `, +${controls.length - 1} more` : ""}.`]
        : ["No control is linked to this asset."],
      basis: { kind: "derived", text: "From control links" },
    },
  ];
}

/* ------------------------------------------------------------------ headline */

export function infoAssetHeadline(input: InfoAssetInput, _ctx?: Ctx): Seg[] {
  const a = input.asset;
  const checks = ciaChecks(input);
  const conflicts = conflictsOf(checks);
  let cia: string;
  if (conflicts.length) {
    cia = `${conflicts[0].label.toLowerCase()} rating and classification disagree${conflicts.length > 1 ? `, +${conflicts.length - 1} more` : ""}`;
  } else if (checks.some((c) => c.diff !== null)) {
    cia = "CIA consistent with the classification scheme";
  } else if (checks.some((c) => c.scheme)) {
    cia = "CIA classified against the scheme";
  } else {
    cia = "CIA rated by hand only";
  }
  const crit = a.effective_criticality ? sentenceCase(a.effective_criticality) : "Unrated";
  // "Critical information asset", never "Critical criticality".
  return [{ b: crit }, ` information asset: criticality set by business value; ${cia}; ${riskClause(a.risks)}.`];
}

/* ------------------------------------------------------------------ open points */

export function infoAssetOpenPoints(input: InfoAssetInput, ctx: Ctx): OpenPoint[] {
  const a = input.asset;
  const gov = ctx.gov;
  const gaps: OpenPoint[] = [];
  const notes: OpenPoint[] = [];
  const push = (list: OpenPoint[], p: OpenPoint | null) => {
    if (p) list.push(p);
  };

  push(gaps, approvedWithoutStepPoint("asset", gov));
  if (!(a.information_owner ?? "").trim()) {
    gaps.push({
      id: "asset.no_business_owner",
      level: "gap",
      text: ["No named business owner: nobody signs off its value and classification."],
      action: { kind: "edit", target: "identity", label: "Name owner" },
    });
  }
  for (const c of conflictsOf(ciaChecks(input))) {
    const s = c.scheme as SchemeValue;
    gaps.push({
      id: `asset.cia_conflict.${c.key}`,
      level: "gap",
      text: [`${c.label}: rated ${sentenceCase(c.rating)}, classified ${truncate(s.name, 40)} (${levelText(s)}).`],
      action: { kind: "section", target: "classification", label: "Reconcile" },
    });
  }
  if (!a.self_assessed) {
    gaps.push({
      id: "asset.self_assessment",
      level: "gap",
      text: [(a.information_owner ?? "").trim()
        ? "Self-assessment pending: the business owner hasn't confirmed value and CIA."
        : "Self-assessment pending: nobody has confirmed value and CIA."],
      action: { kind: "edit", target: "self", label: "Record self-assessment" },
    });
  }
  if (!(a.data_categories ?? "").trim()) {
    gaps.push({
      id: "asset.data_categories",
      level: "gap",
      text: ["Data categories not recorded: PII can't be ruled out."],
      action: { kind: "edit", target: "value", label: "Add categories" },
    });
  }
  push(gaps, reviewOverduePoint("asset", a, ctx, "governance"));

  if ((a.dependencies ?? []).length === 0) {
    notes.push({
      id: "asset.not_hosted",
      level: "note",
      text: ["Not hosted on any IT asset"],
      action: { kind: "open", target: "link-it-asset", label: "Link IT asset" },
    });
  }
  push(notes, neverAttestedPoint("asset", gov, ctx.fmt));
  if ((a.risks ?? []).length === 0) {
    notes.push({ id: "asset.no_risk", level: "note", text: ["No risk linked"] });
  }
  return [...gaps, ...notes];
}
