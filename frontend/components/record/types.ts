/* View types for the record page kit (record-page-spec §3.1, §3.3). React-facing
   counterparts of the pure model types in `lib/record/types.ts`. */

import type { ReactNode } from "react";
import type { GraphRef } from "@/components/RelatedChips";

/** One item of the header's `<dl class="rec-meta">`. 3–6 per record, in the fixed order of §4. */
export type MetaItem = {
  key: string;
  /** "Risk status" */
  label: string;
  /** Absent / null → renders `gap` if given, else muted "Not set". A value AND a gap renders both. */
  value?: ReactNode;
  /** Muted suffix: "annual", "not submitted". */
  sub?: ReactNode;
  /** Title tooltip saying what the field governs. */
  hint?: string;
  /** Amber "Not assigned" + an inline fix link (the fix only navigates or opens a form). */
  gap?: { text: string; fix?: { label: string; onClick: () => void } };
};

export type RecordIdentity = {
  /** "Risk" (CSS uppercases it). */
  kind: string;
  /** The register's nav label, e.g. "Risk Register"; the back link calls onClose. */
  backLabel: string;
  /** Mono chip; click copies window.location.href. */
  reference?: string | null;
  /** H1; never the reference. */
  name: string;
  /** Plain text; 2-line clamp with More / Less. */
  lead?: string | null;
  /** After the ref chip: Key control, L3 Scenario, Contains PII, Handles our data. */
  badges?: ReactNode;
  /** The type's other meta items, in the order of §4. Status and approval items found
   *  here (keys "status" / "lifecycle" and "approval") are moved to their fixed slots, so
   *  existing pages keep working. 3–6 items in total, counting both slots (a dev-only
   *  console.warn fires above 6). */
  meta: MetaItem[];
  /** v1.1 slot 1: the type's own business status — "Risk status", "Lifecycle",
   *  "Document status", "Issue status", "Incident status", "Third-party status"; the asset
   *  types use "Review status". Always rendered first. */
  status?: MetaItem;
  /** v1.1 slot 2: "Record approval", always rendered second, right after the status.
   *  Omit it and the header uses a meta item keyed "approval", else builds it from the
   *  drawer's governance (`approvalMetaItem`). null = the type is outside the approval
   *  lifecycle (no item). */
  approval?: MetaItem | null;
  /** Appends a "Status rules" meta item when any rule fires. */
  statusRules?: { model: string; entityId: string } | null;
};

/** One fact in a `FactList`. null, undefined, "" (or whitespace) and [] count as NOT SET. */
export type FactItem = {
  key?: string;
  label: string;
  value: ReactNode | null | undefined | "" | [];
  /** Spans all columns (procedures, descriptions). */
  wide?: boolean;
  /** Title on the label. */
  hint?: string;
  /** FormModal tab that edits it; "custom" = the custom-fields editor. */
  tab?: string;
  /** Adds "(custom field)" in the not-set sentence. */
  origin?: "custom";
};

/** A callback whose parameter is checked bivariantly, so `meta: (x: ExceptionRef) => …`
 *  is accepted where a `GraphRef` callback is expected (items are GraphRef subtypes). */
type Bivariant<T, R> = { bivarianceHack(x: T): R }["bivarianceHack"];

/** One row of `RelatedGroups` (a relationship type and its records). */
export type RelatedGroup<T extends GraphRef = GraphRef> = {
  key: string;
  /** "Exceptions" */
  label: string;
  items: T[] | undefined;
  /** "/exceptions" → `${href}?id=${x.id}`, or a function for anything else. */
  href: string | Bivariant<T, string>;
  /** Per-item muted note: "Approved · expires 03 Jan 2027". Type the parameter to reach extra fields. */
  meta?: Bivariant<T, ReactNode>;
  /** Group-level secondary control, e.g. <AssetRiskReport variant="button" …/>. */
  action?: ReactNode;
  /** e.g. the risk rollup line under "Risks below". */
  footer?: ReactNode;
};

export type TrailFilter = "all" | "approval" | "attestation" | "decision" | "change";

export type PrimaryCandidate =
  /** Eligible if gov.workflow.allowed_actions includes it. */
  | { kind: "workflow"; action: "approve" | "submit" }
  /** Eligible if gov.attestation.can_attest === true && status !== "current". */
  | { kind: "attest" }
  | { kind: "custom"; label: string; onClick: () => void; when: boolean };

/** A status-rule verdict for one record. `field`/`operator`/`value` arrive with B9. */
export type StatusRuleVerdict = { label: string; color: string; field?: string; operator?: string; value?: string };
