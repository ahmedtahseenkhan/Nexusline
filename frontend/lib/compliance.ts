/** Compliance-content client: Statement of Applicability, suggested clauses for
 *  controls (D-03) and the controls-pack install preview. Kept out of lib/api.ts so the
 *  shared client stays small; everything goes through apiCall / downloadBlob, which
 *  surface the server's own error message. */
import { apiCall, downloadBlob, slugForFile } from "@/lib/api";

/* ------------------------------------------------------ Statement of Applicability */
export type SoaView = "all" | "applicable" | "excluded" | "no_control";

export interface SoaControl {
  id: string;
  reference: string;
  name: string;
  effectiveness: string;
  status: string;
  /** The last reviewed test (decision 7). */
  last_test_date: string | null;
  last_test_result: string | null;
  /** Tests awaiting a reviewer (optional: older API). */
  pending_review_count?: number;
}

export interface SoaRow {
  requirement_id: string;
  reference: string;
  title: string;
  domain: string;
  /** False when the clause's treatment or status is "not applicable". */
  applicable: boolean;
  justification: string;
  /** The clause's compliance status (not_assessed … compliant). */
  implementation_status: string;
  treatment: string | null;
  coverage: string;
  controls: SoaControl[];
  /** The newest reviewed test across the implementing controls (decision 7). */
  last_test_date: string | null;
  last_test_result: string | null;
  /** Tests awaiting a reviewer across the implementing controls — not in the result. */
  pending_review_count?: number;
  /** Covered via crosswalk: not tested directly, but an equivalent or containing clause of
   *  another framework has a tested control. Never a direct mapping. */
  via_crosswalk?: ViaCrosswalk | null;
}

export interface SoaSummary {
  total: number;
  applicable: number;
  excluded: number;
  no_control: number;
  missing_justification: number;
  /** Applicable clauses with a control, and with a tested, working control. */
  mapped?: number;
  assured?: number;
  /** Applicable clauses covered via crosswalk only. */
  via_crosswalk?: number;
}

export interface StatementOfApplicability {
  framework_id: string;
  framework_name: string;
  version: string;
  organisation: string;
  generated_at: string;
  summary: SoaSummary;
  rows: SoaRow[];
}

export const getSoa = (frameworkId: string) =>
  apiCall<StatementOfApplicability>("GET", `/compliance/frameworks/${frameworkId}/soa`);

/** Exclusion needs a justification (the server returns 422 without one). */
export const setApplicability = (requirementId: string, applicable: boolean, justification?: string) =>
  apiCall<SoaRow>("PATCH", `/requirements/${requirementId}/applicability`, {
    applicable,
    ...(justification !== undefined ? { justification } : {}),
  });

export function downloadSoa(frameworkId: string, frameworkName: string, format: "xlsx" | "pdf", view: SoaView = "all") {
  const q = view === "all" ? "" : `?view=${view}`;
  return downloadBlob(`/compliance/frameworks/${frameworkId}/soa.${format}${q}`, `soa-${slugForFile(frameworkName)}.${format}`);
}

/* --------------------------------------------------- suggested clauses for controls */
export interface RequirementSuggestion {
  requirement_id: string;
  framework_id: string | null;
  framework: string;
  reference: string;
  title: string;
  /** 0–1, deterministic for the same data. */
  score: number;
  reasons: string[];
}

export interface ControlSuggestions {
  control_id: string;
  reference: string;
  name: string;
  suggestions: RequirementSuggestion[];
}

export const getSuggestedRequirements = (controlId: string, limit = 15) =>
  apiCall<RequirementSuggestion[]>("GET", `/controls/${controlId}/suggested-requirements?limit=${limit}`);

export const acceptSuggestedRequirements = (controlId: string, requirementIds: string[]) =>
  apiCall<{ linked: number; requirement_ids: string[] }>(
    "POST", `/controls/${controlId}/suggested-requirements/accept`, { requirement_ids: requirementIds },
  );

export const bulkSuggestRequirements = (controlIds: string[], minScore = 0.5, limit = 5) =>
  apiCall<ControlSuggestions[]>("POST", "/controls/suggest-requirements/bulk", {
    control_ids: controlIds, min_score: minScore, limit,
  });

export const bulkAcceptSuggestions = (pairs: { control_id: string; requirement_id: string }[]) =>
  apiCall<{ linked: number; controls: number }>("POST", "/controls/suggest-requirements/bulk/accept", { pairs });

/** A suggestion this strong is pre-ticked ("Strong"); the server's STRONG. */
export const STRONG_SUGGESTION = 0.75;

/** Register-wide review scope: controls with no clause mapped (of the framework, when one
 *  is given), or every control. */
export type SuggestionScope = "unmapped" | "all";

export interface SuggestionReviewPage {
  scope: SuggestionScope;
  framework_id: string | null;
  total_controls: number;
  offset: number;
  page_size: number;
  scanned: number;
  next_offset: number | null;
  groups: ControlSuggestions[];
  suggestion_count: number;
  strong_count: number;
  frameworks: { framework_id: string | null; framework: string; suggestions: number; strong: number }[];
}

export const reviewSuggestionsPage = (opts: {
  scope: SuggestionScope; frameworkId?: string | null; offset: number; pageSize?: number; minScore?: number; limit?: number;
}) => {
  const q = new URLSearchParams({
    scope: opts.scope,
    offset: String(opts.offset),
    page_size: String(opts.pageSize ?? 100),
    min_score: String(opts.minScore ?? 0.5),
    limit: String(opts.limit ?? 5),
  });
  if (opts.frameworkId) q.set("framework_id", opts.frameworkId);
  return apiCall<SuggestionReviewPage>("GET", `/controls/suggest-requirements/review?${q}`);
};

export interface PendingSuggestions {
  framework_id: string | null;
  unmapped_controls: number;
  scanned: number;
  capped: boolean;
  controls_with_strong: number;
  strong_suggestions: number;
  /** When the count was taken; the server keeps it until controls, clauses or mappings change. */
  computed_at?: string | null;
  cached?: boolean;
}

export const getPendingSuggestions = (frameworkId?: string | null) =>
  apiCall<PendingSuggestions>(
    "GET", `/controls/suggest-requirements/pending${frameworkId ? `?framework_id=${encodeURIComponent(frameworkId)}` : ""}`,
  );

/* ------------------------------------------------------------ framework posture */
/** Assessed compliant / mapped / tested, of the applicable clauses (F-19). Mapping never
 *  makes a clause compliant; this shows what it did achieve. */
export interface FrameworkPosture {
  total: number;
  applicable: number;
  compliant: number;
  mapped: number;
  assured: number;
  unassessed: number;
  failing: number;
  compliant_pct: number;
  mapped_pct: number;
  assured_pct: number;
  /** Not tested directly, covered by a tested control through an equivalent or containing
   *  crosswalk. Never part of mapped or tested. */
  via_crosswalk?: number;
  via_crosswalk_pct?: number;
  /** "0% assessed compliant · 62% mapped · 8% tested" */
  line: string;
}

/* ------------------------------------------------------------ typed crosswalks */
/** Read from the first clause: equivalent; subset = contained in the other; superset =
 *  contains the other; intersects = overlaps; related = same subject only. */
export type CrosswalkRelationship = "equivalent" | "subset" | "superset" | "intersects" | "related";
export type CrosswalkOrigin = "shipped" | "accepted" | "manual";

export const RELATIONSHIPS: CrosswalkRelationship[] = ["equivalent", "subset", "superset", "intersects", "related"];

/** Plain labels, read from the first clause to the second. */
export const RELATIONSHIP_LABEL: Record<CrosswalkRelationship, string> = {
  equivalent: "Equivalent",
  subset: "Contained in",
  superset: "Contains",
  intersects: "Overlaps",
  related: "Related",
};

export const RELATIONSHIP_HELP: Record<CrosswalkRelationship, string> = {
  equivalent: "Both ask for the same outcome; meeting either meets the other.",
  subset: "The first clause is wholly contained in the second: meeting the second meets the first.",
  superset: "The first clause wholly contains the second: meeting the first meets the second.",
  intersects: "They overlap; each asks for something the other does not.",
  related: "Same subject; neither is claimed to meet any part of the other.",
};

export const ORIGIN_LABEL: Record<CrosswalkOrigin, string> = {
  shipped: "Library content",
  accepted: "Accepted suggestion",
  manual: "Added by hand",
};

export interface ViaCrosswalkControl { id: string; reference: string; name: string; effectiveness: string }

export interface ViaCrosswalk {
  via_requirement_id: string;
  via_reference: string;
  via_title: string;
  via_framework: string;
  relationship: CrosswalkRelationship;
  source: string;
  /** "mapped via ISO/IEC 27001:2022 A.8.5" */
  label: string;
  controls: ViaCrosswalkControl[];
}

export const getViaCrosswalk = (requirementId: string) =>
  apiCall<ViaCrosswalk | null>("GET", `/requirements/${requirementId}/coverage-via-crosswalk`);

export const adoptCrosswalkMapping = (requirementId: string, viaRequirementId: string, controlIds?: string[]) =>
  apiCall<unknown>("POST", `/requirements/${requirementId}/adopt-crosswalk-mapping`, {
    via_requirement_id: viaRequirementId,
    ...(controlIds ? { control_ids: controlIds } : {}),
  });

export interface CrosswalkContentPair {
  module: string;
  from_template: string;
  to_template: string;
  from_name: string;
  to_name: string;
  source: string;
  rows: number;
  by_relationship: Record<string, number>;
  installed: boolean;
}

export interface CrosswalkContent { version: string; relationships: string[]; pairs: CrosswalkContentPair[] }

export const getCrosswalkContent = () => apiCall<CrosswalkContent>("GET", "/compliance/crosswalks/content");

export interface CrosswalkRejection {
  id: string;
  from_template: string;
  from_reference: string;
  to_template: string;
  to_reference: string;
  relationship: CrosswalkRelationship;
  content_version: string;
  reason: string;
  rejected_by: string;
  rejected_at: string | null;
  from_title: string;
  to_title: string;
}

/* ------------------------------------------------------- controls-pack preview */
export type PackAction = "create" | "match-by-reference" | "match-by-name" | "reuse-via-crosswalk" | "map-to-existing";

export interface PackControlRef { id: string; reference: string; name: string }

/** An existing control a clause could reuse because the library's crosswalk content relates
 *  the clause to one that control already implements (common control set). */
export interface PackCrosswalkMatch {
  control: PackControlRef;
  via_reference: string;
  via_framework: string;
  via_template: string;
  relationship: CrosswalkRelationship;
  confidence: number;
  rationale: string;
  source: string;
  /** Equivalent: reused unless you choose to create. */
  default_reuse: boolean;
}

export interface PackPreviewRow {
  requirement_ref: string;
  catalogue_reference: string;
  title: string;
  action: PackAction;
  control: PackControlRef | null;
  name_match: PackControlRef | null;
  crosswalk_match?: PackCrosswalkMatch | null;
}

export interface PackPreview {
  pack_id: string;
  name: string;
  installed: boolean;
  framework_id: string | null;
  create: number;
  reuse: number;
  match_reference: number;
  match_name: number;
  match_crosswalk?: number;
  crosswalk_to_decide?: number;
  rows: PackPreviewRow[];
}

/** requirement_ref -> "create" | control id */
export type PackDecisions = Record<string, string>;

export const previewControlsPack = (packId: string, decisions: PackDecisions = {}) =>
  apiCall<PackPreview>("POST", `/content-library/${packId}/install-controls/preview`, { decisions });
