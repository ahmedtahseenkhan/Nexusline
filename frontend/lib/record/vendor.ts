/* The third-party record's judgement wording (record-page-spec §4.8): the summary tiles,
   the open points, the headline and the review-overdue rule the header shares with them.
   The only place this wording lives — `app/(app)/vendors/page.tsx` renders what these
   functions return, and `lib/record/__fixtures__/vendor.json` pins them (`npm run
   check:record-copy`). A wording change updates the fixture and needs a Compliance
   reviewer on the PR.

   Pure (record-page-spec §3.2): no React, no DOM, imports only `./text` and `./types`. */

import { approvalWithoutStepText, joinList, plural, quote, sentenceCase, truncate } from "./text";
import type { Ctx, OpenPoint, Seg, TileModel, TileValue } from "./types";

/* ------------------------------------------------------------------ input ----- */

export type VendorContractFacts = { end_date: string | null; is_expired: boolean };
export type VendorCertificationFacts = {
  cert_type_label: string;
  expires_on: string | null;
  /** valid | expiring (within 60 days) | expired | no_expiry */
  expiry_state: string;
  days_to_expiry: number | null;
};
export type VendorTieringFacts = {
  proposed_criticality: string | null;
  overridden: boolean;
  assessment: { id: string } | null;
  submitted_at: string | null;
  score_pct: number | null;
  band_tier: string | null;
  worst_case_answers: number | null;
  floor_applied: boolean;
  stale: boolean;
  problem: string;
};
export type VendorOutsourcingFacts = {
  reference: string;
  title: string;
  materiality: string;
  exit_plan: string;
  exit_plan_tested: boolean;
  /** Why it is (or is not) material. Absent from an older API. */
  materiality_assessment?: string;
  /** easy | moderate | difficult | none | "" (not assessed). */
  substitutability?: string;
  /** low | medium | high | "" (not assessed). */
  concentration_level?: string;
  concentration_note?: string;
  status?: string;
};
/** Derived on the server (api/v1/vendors.concentration_view). */
export type VendorConcentrationFacts = {
  material_arrangements: number;
  arrangements: number;
  critical_processes: number;
  processes: number;
  recorded_level: string;
  /** low | medium | high */
  level: string;
  flagged: boolean;
  reasons: string[];
  /** Critical third party (or one supporting a critical process) with no arrangement on file. */
  arrangement_expected: boolean;
};

/** The fields of `GET /vendors/{id}` the rules read. */
export type VendorFacts = {
  /** The vendor id, for links out (e.g. recording an outsourcing arrangement). */
  id?: string;
  criticality: string;
  status: string;
  risk_rating: string | null;
  shares_data: boolean;
  assessment_status: string;
  last_assessed_at: string | null;
  next_review_date: string | null;
  contracts: VendorContractFacts[];
  contract_count: number;
  active_contract_totals?: Record<string, number>;
  relationship_owner_ref?: { full_name?: string | null; email?: string | null } | null;
  data_classification_ref?: { label: string } | null;
  data_residency_countries?: { label: string }[];
  certifications?: VendorCertificationFacts[];
  /** Linked security assessments (graph refs). */
  assessments?: { id: string; reference?: string; title?: string; name?: string }[];
  inherent_tier?: string | null;
  tier_override_reason?: string;
  tiering?: VendorTieringFacts | null;
  outsourcing?: VendorOutsourcingFacts[];
  concentration?: VendorConcentrationFacts | null;
};

export type VendorInput = { vendor: VendorFacts };

/* -------------------------------------------------------------- helpers ----- */

const TILE_TONES = new Set(["critical", "high", "medium", "low"]);
/** A criticality / tier / rating word as a badge tone. */
export const vendorSevTone = (v: string | null | undefined) =>
  (v && TILE_TONES.has(v) ? v : "neutral") as "low" | "medium" | "high" | "critical" | "neutral";
const sevValue = (v: string | null | undefined, unset: string): TileValue =>
  v ? { text: sentenceCase(v), tone: vendorSevTone(v), badge: true } : { text: unset, tone: "hollow" };
const lower = (v: string | null | undefined) => sentenceCase(v).toLowerCase();
/** "Approved" / "In review" / "Retired" — the Record approval state as the header shows it. */
const WORKFLOW_LABEL: Record<string, string> = { in_review: "In review", approved: "Approved", retired: "Retired" };

/** Today as YYYY-MM-DD in the viewer's clock (review dates are date-only). */
function isoDay(now: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${p(now.getMonth() + 1)}-${p(now.getDate())}`;
}

/** The next review date has passed. */
export function vendorReviewOverdue(v: Pick<VendorFacts, "next_review_date" | "status">, now: Date): boolean {
  // The server's rule (drill_through.vendor_review_overdue, the alerts, My Work): an
  // offboarded third party has nothing left to review.
  if (v.status === "offboarded") return false;
  return !!v.next_review_date && v.next_review_date.slice(0, 10) < isoDay(now);
}

/** Certificates still worth chasing: none once the third party is offboarded (the
 *  server's certificate alerts skip offboarded third parties too). */
function liveCerts<T>(v: Pick<VendorFacts, "status">, certs: readonly T[]): readonly T[] {
  return v.status === "offboarded" ? [] : certs;
}

/** A certificate in force: valid, or expiring within 60 days. */
export const vendorCertIsValid = (c: Pick<VendorCertificationFacts, "expiry_state">) => c.expiry_state === "valid" || c.expiry_state === "expiring";

/** "Handles our data" as a badge tone: amber while the data classification or residency is
 *  missing (a risk-bearing fact with nothing recorded about it), neutral once both are on
 *  file. Never the success green. */
export function vendorDataTone(v: Pick<VendorFacts, "shares_data" | "data_classification_ref" | "data_residency_countries">): "medium" | "neutral" {
  return v.shares_data && (!v.data_classification_ref || !(v.data_residency_countries ?? []).length) ? "medium" : "neutral";
}

/** Contracts in force vs on file, for the tile, the section head and the headline. */
export function vendorContractState(v: Pick<VendorFacts, "contracts" | "contract_count">): {
  inForce: number;
  expired: number;
  onFile: number;
  /** The latest end date among the expired contracts. */
  latestExpiry: string | null;
} {
  const inForce = v.contracts.filter((c) => !c.is_expired).length;
  const expiredList = v.contracts.filter((c) => c.is_expired);
  const latestExpiry = expiredList.map((c) => c.end_date).filter((d): d is string => !!d).sort().pop() ?? null;
  return { inForce, expired: expiredList.length, onFile: Math.max(v.contract_count, v.contracts.length), latestExpiry };
}

/** The Contracts section head's sub: "Active value USD 260,000" while a contract is in
 *  force, else "None in force · 1 expired" (never "Active value PKR 0"). */
export function vendorContractsSub(v: Pick<VendorFacts, "contracts" | "contract_count" | "active_contract_totals">, fmt: Ctx["fmt"]): string | null {
  const st = vendorContractState(v);
  if (st.onFile === 0) return null;
  if (st.inForce === 0) return `None in force${st.expired ? ` · ${st.expired} expired` : ""}`;
  const totals = Object.entries(v.active_contract_totals ?? {})
    .filter(([, n]) => n > 0)
    .map(([c, n]) => fmt.money(n, c || null))
    .join(" + ");
  return totals ? `Active value ${totals}` : `${st.inForce} in force`;
}

/** Substitutability as the record says it. */
export const VENDOR_SUBSTITUTABILITY: Record<string, string> = {
  easy: "Easy to substitute",
  moderate: "Moderately hard to substitute",
  difficult: "Difficult to substitute",
  none: "No realistic alternative",
};
const HARD_TO_SUBSTITUTE = new Set(["difficult", "none"]);
const exitPlanTested = (o: VendorOutsourcingFacts) => !!o.exit_plan?.trim() && o.exit_plan_tested;

/** The Due diligence section's outsourcing lines: materiality with its rationale,
 *  substitutability, and what the concentration level rests on (the level itself is
 *  `concentration.level`, shown as a badge). Pure. */
export function vendorOutsourcingDiligence(v: Pick<VendorFacts, "outsourcing" | "concentration">): {
  materiality: string | null;
  rationale: string | null;
  substitutability: string | null;
  concentration: string | null;
} {
  const live = (v.outsourcing ?? []).filter((o) => o.status !== "terminated");
  const c = v.concentration ?? null;
  if (!live.length) {
    return {
      materiality: null, rationale: null, substitutability: null,
      concentration: c && c.critical_processes ? `${plural(c.critical_processes, "high or critical process", "high or critical processes")} depend on this provider` : null,
    };
  }
  const material = live.filter((o) => o.materiality === "material");
  const materiality = material.length
    ? `Material outsourcing (${joinList(material.map((o) => o.reference || o.title))})`
    : `Non-material outsourcing (${joinList(live.map((o) => o.reference || o.title))})`;
  const rationales = live.filter((o) => o.materiality_assessment?.trim());
  const rationale = rationales.length
    ? rationales.map((o) => `${live.length > 1 ? `${o.reference || o.title}: ` : ""}${o.materiality_assessment!.trim()}`).join(" · ")
    : null;
  const subs = live.filter((o) => o.substitutability);
  const substitutability = subs.length
    ? subs.map((o) => `${live.length > 1 ? `${o.reference || o.title}: ` : ""}${VENDOR_SUBSTITUTABILITY[o.substitutability!] ?? o.substitutability}`).join(" · ")
    : null;
  let concentration: string | null = null;
  if (c) {
    const parts = [
      plural(c.material_arrangements, "material arrangement"),
      plural(c.critical_processes, "high or critical process", "high or critical processes"),
    ];
    const recorded = c.recorded_level ? `; recorded ${c.recorded_level}` : "";
    const notes = live.map((o) => o.concentration_note?.trim()).filter(Boolean);
    concentration = `${parts.join(", ")}${recorded}${notes.length ? `. ${notes.join(" · ")}` : ""}`;
  }
  return { materiality, rationale, substitutability, concentration };
}

/** "tiering proposes high": the header's amber note when the criticality was overridden. */
export function vendorOverrideNote(v: VendorFacts): string | null {
  const t = v.tiering;
  return t?.overridden && t.proposed_criticality ? `tiering proposes ${lower(t.proposed_criticality)}` : null;
}

/** The Tiering section's override line. */
export function vendorOverrideText(v: VendorFacts): string {
  return `Set to ${lower(v.criticality)} instead of the proposed ${lower(v.tiering?.proposed_criticality)}: ${v.tier_override_reason || "no reason recorded"}`;
}

/* ---------------------------------------------------------------- tiles ----- */

export function vendorTiles({ vendor: v }: VendorInput, ctx: Ctx): TileModel[] {
  const { fmt } = ctx;
  const t = v.tiering ?? null;

  // Inherent tier
  const stale = t?.stale ? " The latest questionnaire gives a different tier — recompute." : "";
  const tierBecause: Seg[] =
    t && t.score_pct != null && t.band_tier
      ? [`Tiering score ${Math.round(t.score_pct)}% → ${lower(t.band_tier)} (bands 70 / 45 / 20%)${t.floor_applied ? `; raised by ${plural(t.worst_case_answers ?? 0, "worst-case answer")}` : ""}.${stale}`]
      : v.inherent_tier
        ? [`${sentenceCase(v.inherent_tier)} tier on file; no questionnaire score is shown.${stale}`]
        : ["Answer the 8-question tiering questionnaire to set it."];
  const tier: TileModel = {
    key: "tier", label: "Inherent tier", section: "tiering",
    value: sevValue(v.inherent_tier, "Not tiered"),
    because: tierBecause,
    basis: t?.submitted_at ? { kind: "evidenced", text: `From questionnaire submitted ${fmt.date(t.submitted_at)}` } : { kind: "missing", text: "Not on file" },
  };

  // Criticality
  const reason = (v.tier_override_reason || "").trim();
  const criticality: TileModel = t?.overridden
    ? {
        key: "criticality", label: "Criticality", section: "tiering",
        value: sevValue(v.criticality, "Not set"),
        because: [`Set to ${lower(v.criticality)} instead of the proposed ${lower(t.proposed_criticality)}${reason ? `: ${quote(reason)}` : "; no reason recorded"}.`],
        basis: { kind: "declared", text: "Overridden by hand" },
      }
    : t?.proposed_criticality
      ? {
          key: "criticality", label: "Criticality", section: "tiering",
          value: sevValue(v.criticality, "Not set"),
          because: ["Follows the tiering proposal."],
          basis: { kind: "derived", text: "From the tiering proposal" },
        }
      : {
          key: "criticality", label: "Criticality", section: "tiering",
          value: sevValue(v.criticality, "Not set"),
          because: ["Set by hand; no tiering on file."],
          basis: { kind: "declared", text: "Set by hand" },
        };

  // Risk rating
  const last = v.last_assessed_at ? `, last ${fmt.date(v.last_assessed_at)}` : "";
  const assessment =
    v.assessment_status === "completed" ? `From the completed assessment${last}.`
    : v.assessment_status === "in_progress" ? `From the assessment in progress${last}.`
    : `Assessment not started${last}.`;
  // A rating from a completed assessment that is linked here is backed by a record; with
  // no assessment on file it is a hand-set value.
  // The tiering questionnaire is linked as an assessment too, but it sets the tier, not
  // this rating: leave it out. The links carry no order or state, so a single remaining
  // assessment is named and several are counted, rather than naming an arbitrary one.
  const tieringId = v.tiering?.assessment?.id;
  const linked = (v.assessments ?? []).filter((x) => x.id !== tieringId);
  const onFile = linked.length > 0;
  const onFileName = linked.length === 1 ? (linked[0].reference || linked[0].title || linked[0].name || "").trim() : "";
  const onFileText = linked.length > 1 ? `From ${linked.length} linked assessments` : `From assessment ${onFileName || "on file"}`;
  const rating: TileModel = {
    key: "rating", label: "Risk rating", section: "diligence",
    value: sevValue(v.risk_rating, "Not rated"),
    because: [v.risk_rating ? assessment : `No risk rating recorded; the assessment is ${lower(v.assessment_status)}.`],
    basis: !v.risk_rating ? { kind: "missing", text: "Not on file" }
      : v.assessment_status === "completed" && onFile ? { kind: "evidenced", text: truncate(onFileText, 60) }
      : { kind: "declared", text: "Set by the assessor" },
  };

  // Data handling
  const cls = v.data_classification_ref?.label || "";
  const residency = truncate(joinList((v.data_residency_countries ?? []).map((c) => c.label)), 60);
  const data: TileModel = !v.shares_data
    ? {
        key: "data", label: "Data handling", section: "diligence",
        value: { text: "No data shared" },
        because: ["Recorded as not storing, processing or accessing our data."],
        basis: { kind: "declared", text: "Recorded by hand" },
      }
    : {
        key: "data", label: "Data handling", section: "diligence",
        value: { text: "Handles our data", tone: vendorDataTone(v), badge: true },
        because: [
          cls && residency ? `${cls} data; resident in ${residency}.`
          : cls ? `${cls} data; residency not recorded.`
          : residency ? `Classification not recorded; resident in ${residency}.`
          : "Handles our data, but no data classification or residency is recorded.",
        ],
        basis: cls && residency ? { kind: "declared", text: "Recorded by hand" } : { kind: "missing", text: "Not on file" },
      };

  // Contracts: say whether any is in force; a contract on file that has ended is not
  // cover ("None" + "1 contract." read as if the one on file were live).
  const cst = vendorContractState(v);
  const active = v.contracts.filter((c) => !c.is_expired);
  const totals = Object.entries(v.active_contract_totals ?? {})
    .filter(([, n]) => n > 0)
    .map(([c, n]) => fmt.money(n, c || null))
    .join(" + ");
  const nextExpiry = active.map((c) => c.end_date).filter((d): d is string => !!d).sort()[0];
  const expiredOn = cst.latestExpiry ? ` on ${fmt.date(cst.latestExpiry)}` : "";
  const contracts: TileModel = {
    key: "contracts", label: "Contracts", section: "contracts",
    value: active.length ? { text: `${active.length} active` }
      : cst.onFile ? { text: "None in force", tone: v.status === "active" ? "high" : "hollow", badge: v.status === "active" }
      : { text: "None", tone: "hollow" },
    because: cst.onFile === 0
      ? ["No service contract on file."]
      : active.length
        ? [`${plural(v.contract_count, "contract")}${totals ? `; active value ${totals}` : ""}${nextExpiry ? `; next expiry ${fmt.date(nextExpiry)}` : ""}.`]
        : cst.onFile === 1
          ? [`No contract in force: the one on file expired${expiredOn}.`]
          : [`No contract in force: ${cst.onFile} on file, latest expired${expiredOn}.`],
    basis: cst.onFile ? { kind: "derived", text: "From contract records" } : { kind: "missing", text: "Not on file" },
  };

  // Certifications
  const certs = v.certifications ?? [];
  const valid = certs.filter(vendorCertIsValid);
  const expiring = certs.filter((c) => c.expiry_state === "expiring").length;
  const expired = certs.filter((c) => c.expiry_state === "expired").length;
  const firsts = valid.slice(0, 2).map((c) => (c.expires_on ? `${c.cert_type_label} to ${fmt.date(c.expires_on)}` : c.cert_type_label));
  const tail = `${expiring} expiring within 60 days, ${expired} expired`;
  const certTile: TileModel = {
    key: "certs", label: "Certifications", section: "certifications",
    value: valid.length ? { text: `${valid.length} valid` } : { text: "None", tone: "hollow" },
    because: certs.length === 0 ? ["No certification on file."] : [firsts.length ? `${firsts.join(", ")}; ${tail}.` : `${tail.charAt(0).toUpperCase()}${tail.slice(1)}.`],
    basis: valid.length ? { kind: "evidenced", text: "Certificates on file" } : { kind: "missing", text: "Not on file" },
  };

  return [tier, criticality, rating, data, contracts, certTile];
}

/* ------------------------------------------------------------- headline ----- */

export function vendorHeadline({ vendor: v }: VendorInput, _ctx: Ctx): Seg[] {
  const over = vendorOverrideNote(v);
  const tier = v.inherent_tier ? `inherent tier ${lower(v.inherent_tier)}` : "not tiered";
  const active = v.contracts.filter((c) => !c.is_expired).length;
  const valid = (v.certifications ?? []).filter(vendorCertIsValid).length;
  return [
    `${v.criticality ? `${sentenceCase(v.criticality)} third party` : "Third party, criticality not set"}${over ? ` (${over})` : ""}; ${tier}; `,
    active ? { b: plural(active, "active contract") } : "no contract in force",
    "; ",
    valid ? { b: plural(valid, "valid certification") } : "no valid certification",
    ".",
  ];
}

/* ---------------------------------------------------------- open points ----- */

export function vendorOpenPoints({ vendor: v }: VendorInput, ctx: Ctx): OpenPoint[] {
  const { fmt, gov, now } = ctx;
  const t = v.tiering ?? null;
  const certs = v.certifications ?? [];
  const gaps: OpenPoint[] = [];
  const notes: OpenPoint[] = [];

  if (!v.relationship_owner_ref) {
    gaps.push({ id: "vendor.owner", level: "gap", text: ["No relationship owner."], action: { kind: "edit", target: "diligence", label: "Assign owner" } });
  }
  if (t?.stale) {
    gaps.push({
      id: "vendor.tier_stale", level: "gap", text: [t.problem || "The latest tiering questionnaire gives a different tier."],
      action: { kind: "section", target: "tiering", label: "Recompute" },
    });
  }
  if (t?.overridden && !(v.tier_override_reason || "").trim()) {
    // The override reason sits under Criticality on the form's General tab.
    gaps.push({ id: "vendor.override_no_reason", level: "gap", text: ["Criticality overridden without a reason."], action: { kind: "edit", target: "general", label: "Give a reason" } });
  }
  if (v.shares_data && !v.data_classification_ref) {
    gaps.push({
      id: "vendor.data_unclassified", level: "gap", text: ["Handles our data but the data classification is not recorded."],
      action: { kind: "edit", target: "diligence", label: "Classify" },
    });
  }
  const expiredCerts = liveCerts(v, certs).filter((c) => c.expiry_state === "expired");
  if (expiredCerts.length) {
    const c = expiredCerts[0];
    gaps.push({
      id: "vendor.cert_expired", level: "gap",
      text: [`${c.cert_type_label} certificate expired${c.expires_on ? ` on ${fmt.date(c.expires_on)}` : ""}${expiredCerts.length > 1 ? ` (+${expiredCerts.length - 1} more)` : ""}.`],
      action: { kind: "section", target: "certifications", label: "See certificates" },
    });
  }
  if (v.status === "active" && v.contracts.length > 0 && v.contracts.every((c) => c.is_expired)) {
    gaps.push({ id: "vendor.contract_expired_active", level: "gap", text: ["Active third party with no contract in force."], action: { kind: "section", target: "contracts", label: "See contracts" } });
  }
  if (vendorReviewOverdue(v, now)) {
    // B1: the server says whether this viewer may attest (the review is native to the
    // attestation). Refused → point at the Sign-off card, which prints the reason; an
    // older API sends no verdict and the Attest… jump stays (the refusal shows inline).
    gaps.push({
      id: "vendor.review_overdue", level: "gap", text: [`Review overdue since ${fmt.date(v.next_review_date)}.`],
      action: gov.attestation?.canAttest === false
        ? { kind: "focus", target: "rec-signoff", label: "See sign-off" }
        : { kind: "attest", target: "attest", label: "Attest…" },
    });
  }
  const liveOutsourcing = (v.outsourcing ?? []).filter((o) => o.status !== "terminated");
  // Most urgent first: a material service the bank cannot easily replace, with no tested
  // way out.
  const cornered = liveOutsourcing.filter((o) => o.materiality === "material" && HARD_TO_SUBSTITUTE.has(o.substitutability ?? "") && !exitPlanTested(o));
  if (cornered.length) {
    const o = cornered[0];
    gaps.unshift({
      id: "vendor.hard_to_substitute_untested", level: "gap",
      text: [
        `Material outsourcing ${o.reference || o.title} ${o.substitutability === "none" ? "has no realistic alternative" : "is difficult to substitute"} and ${o.exit_plan?.trim() ? "its exit plan is untested" : "has no exit plan"}${cornered.length > 1 ? ` (+${cornered.length - 1} more)` : ""}.`,
      ],
      action: { kind: "section", target: "outsourcing", label: "See outsourcing" },
    });
  }
  const untested = liveOutsourcing.filter((o) => o.materiality === "material" && !exitPlanTested(o) && !cornered.includes(o));
  if (untested.length) {
    gaps.push({
      id: "vendor.exit_plan_untested", level: "gap",
      text: [`Material outsourcing ${untested[0].reference || untested[0].title} has no tested exit plan${untested.length > 1 ? ` (+${untested.length - 1} more)` : ""}.`],
      action: { kind: "section", target: "outsourcing", label: "See outsourcing" },
    });
  }
  const conc = v.concentration ?? null;
  if (conc?.flagged && v.status !== "offboarded") {
    gaps.push({
      id: "vendor.high_concentration", level: "gap",
      text: [`High concentration: ${conc.reasons[0] ? conc.reasons[0].replace(/\.$/, "").replace(/^./, (ch) => ch.toLowerCase()) : "much of the bank relies on this provider"}${conc.reasons.length > 1 ? ` (+${conc.reasons.length - 1} more)` : ""}.`],
      action: { kind: "section", target: "diligence", label: "See due diligence" },
    });
  }
  if (conc?.arrangement_expected && v.status !== "offboarded" && v.id) {
    gaps.push({
      id: "vendor.outsourcing_undecided", level: "gap",
      text: ["No outsourcing arrangement recorded — decide whether this is material outsourcing."],
      action: { kind: "href", target: `/outsourcing?new=1&vendor_id=${encodeURIComponent(v.id)}`, label: "Record arrangement" },
    });
  }
  const ws = gov.workflowState;
  if ((ws === "approved" || ws === "in_review" || ws === "retired") && gov.approvalSteps === 0) {
    gaps.push({
      id: "vendor.approved_without_step", level: "gap",
      text: [approvalWithoutStepText(gov, WORKFLOW_LABEL[ws])],
      action: { kind: "focus", target: "rec-signoff", label: "See sign-off" },
    });
  }

  if (!v.inherent_tier && !t?.assessment) {
    notes.push({ id: "vendor.not_tiered", level: "note", text: ["Not tiered"], action: { kind: "section", target: "tiering", label: "Start tiering" } });
  }
  if (v.contract_count === 0) {
    notes.push({ id: "vendor.no_contract", level: "note", text: ["No service contract on file"], action: { kind: "edit", target: "contracts", label: "Add contract" } });
  }
  const expiringCert = liveCerts(v, certs).find((c) => c.expiry_state === "expiring");
  if (expiringCert) {
    notes.push({
      id: "vendor.cert_expiring", level: "note",
      text: [`${expiringCert.cert_type_label} certificate expires in ${plural(expiringCert.days_to_expiry ?? 0, "day")}`],
      action: { kind: "section", target: "certifications", label: "See certificates" },
    });
  }
  return [...gaps, ...notes];
}

/** The line OpenPoints shows when nothing is open. */
export const VENDOR_CLEAR_TEXT = "No open points: owner, tiering, contracts, certificates and review are on file.";
