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
  last_test_date: string | null;
  last_test_result: string | null;
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
  last_test_date: string | null;
  last_test_result: string | null;
}

export interface SoaSummary {
  total: number;
  applicable: number;
  excluded: number;
  no_control: number;
  missing_justification: number;
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

/* ------------------------------------------------------- controls-pack preview */
export type PackAction = "create" | "match-by-reference" | "match-by-name" | "map-to-existing";

export interface PackControlRef { id: string; reference: string; name: string }

export interface PackPreviewRow {
  requirement_ref: string;
  catalogue_reference: string;
  title: string;
  action: PackAction;
  control: PackControlRef | null;
  name_match: PackControlRef | null;
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
  rows: PackPreviewRow[];
}

/** requirement_ref -> "create" | control id */
export type PackDecisions = Record<string, string>;

export const previewControlsPack = (packId: string, decisions: PackDecisions = {}) =>
  apiCall<PackPreview>("POST", `/content-library/${packId}/install-controls/preview`, { decisions });
