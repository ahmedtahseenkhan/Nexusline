/* Status values a form must not offer — the client side of the server's
   `services/lifecycle_gates.allowed_values`, so a record's form never lets someone pick
   a value the save would refuse.

   Two kinds of value are withheld:

   * **Sign-offs** — reached only by the decision that records them: approving a DPIA,
     a Shariah ruling or product, a FAIR quantification, validating a model (Submit for
     review → Approve in the record's Approval panel), accepting a vulnerability's risk
     (Request risk acceptance → someone else decides).
   * **Live states that need the approval first** — an Islamic product going active, a
     model going into production, an outsourced service starting. Offered once the
     record's approval lifecycle is approved.

   The value the record already holds is always offered, so a form that saves every
   field can save it back. */

type Option = { value: string; label: string };

/** Entity type → status values only a decision reaches (server: `RULES`). */
const SIGN_OFFS: Readonly<Record<string, readonly string[]>> = {
  risk_quantification: ["approved"],
  shariah_ruling: ["under_review", "approved"],
  islamic_product: ["approved"],
  model_inventory: ["validated"],
  vuln_finding: ["risk_accepted"],
  dpia: ["approved"],
};

/** Entity type → status values that need the record approved first (server: `APPROVED_FIRST`). */
const APPROVED_FIRST: Readonly<Record<string, readonly string[]>> = {
  islamic_product: ["active"],
  model_inventory: ["in_production"],
  outsourcing_arrangement: ["active", "under_review"],
};

/** The values a save may not write, given the stored value (none on create) and the
 *  record's approval state. */
export function withheldStatuses(entityType: string, stored?: string | null, workflowState?: string | null): Set<string> {
  const out = new Set<string>(SIGN_OFFS[entityType] ?? []);
  if (workflowState !== "approved") for (const v of APPROVED_FIRST[entityType] ?? []) out.add(v);
  if (stored) out.delete(stored);
  return out;
}

/** `options` without the values a save may not write. */
export function statusOptions<T extends Option>(
  entityType: string, options: readonly T[], stored?: string | null, workflowState?: string | null,
): T[] {
  const withheld = withheldStatuses(entityType, stored, workflowState);
  return options.filter((o) => !withheld.has(o.value));
}

/** One line for under the status field: how the withheld values are reached. */
export const DECISION_HELP: Readonly<Record<string, string>> = {
  risk_quantification: "Approved is given through Submit for review → Approve, once the simulation has run.",
  shariah_ruling: "Under review and Approved record the Shariah Board's decision: use Submit for review → Approve.",
  islamic_product: "Approved is the Shariah approval (Submit for review → Approve, with an approved ruling linked); Active needs it.",
  model_inventory: "Validated is the sign-off after a passed validation (Submit for review → Approve); In production needs it.",
  vuln_finding: "Risk accepted needs a request with a reason and an end date, decided by someone else.",
  dpia: "Approved is the DPO's sign-off: complete the assessment, then Submit for review → Approve.",
  outsourcing_arrangement: "Active and Under review need the arrangement approved first (Submit for review → Approve).",
};
