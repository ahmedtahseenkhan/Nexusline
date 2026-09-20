/* Pure model types for the record page (dossier): record-page-spec §3.2.

   Pure TypeScript: no React, no DOM, no `@/components` imports, no `enum` or
   `namespace`. Imports only from other `lib/record/*` files or pure `@/lib/*` modules,
   so the fixture runner (`npm run check:record-copy`) can execute the derivations
   under Node with `--experimental-strip-types`.

   Each `lib/record/<type>.ts` exports exactly:
     <type>Tiles(input, ctx): TileModel[]        exactly 6 tiles, in the order of §4
     <type>OpenPoints(input, ctx): OpenPoint[]   gaps first, then notes, each in rule order
     <type>Headline(input, ctx): Seg[]           one sentence, ≤ 160 characters, never clamped */

/** A run of sentence text. `{ b }` renders as `<b>` (key figures); nothing else is markup. */
export type Seg = string | { b: string };

export type Tone = "critical" | "high" | "medium" | "low" | "info" | "neutral" | "hollow";

/** evidenced = backed by a record on file · declared = set by hand · derived = calculated · missing = not on file */
export type BasisKind = "evidenced" | "declared" | "derived" | "missing";

/** `text` ≤ 60 chars, sentence case, no full stop. */
export type Basis = { kind: BasisKind; text: string };

export type TileValue = {
  /** "Critical", "Not recorded", "PKR 100,000" */
  text: string;
  /** Badge tone when `badge` is true; word colour otherwise (critical | high | medium | low only). "hollow" always renders a hollow badge. */
  tone?: Tone;
  /** Render `text` as `<Badge tone asIs>`. */
  badge?: boolean;
  /** Bold figure after the badge: "20". */
  num?: string;
  /** Muted suffix: "/ year", "of 1", "in breach". */
  unit?: string;
};

export type ScaleModel = {
  max: number;
  appetite: number;
  tolerance: number;
  marks: { score: number; kind: "inherent" | "residual" | "suggested" | "target"; dim?: boolean }[];
};

export type TileModel = {
  /** Stable, e.g. "inherent"; also the React key and fixture key. */
  key: string;
  /** Sentence case: "Inherent risk". */
  label: string;
  value: TileValue;
  /** REQUIRED; ≤ 160 characters in total; quoted free text truncated at 60 chars. */
  because: Seg[];
  /** REQUIRED. */
  basis: Basis;
  /** Id of the section that backs the tile. */
  section: string;
  /** Appetite tile only. */
  scale?: ScaleModel;
};

/** "open": target is an opener key the page maps to a form it already has, e.g. "record-test" → openRecordTest(). */
export type PointAction = {
  label: string;
  kind: "section" | "edit" | "focus" | "href" | "attest" | "open";
  target: string;
};

export type OpenPoint = { id: string; level: "gap" | "note"; text: Seg[]; action?: PointAction };

export type Fmt = {
  /** "03 Jul 2027" (tenant format). */
  date(v: string | null | undefined): string;
  dateTime(v: string | null | undefined): string;
  money(n: number | null | undefined, currency?: string | null): string;
};

/** The slice of governance the rules read. Built from live data by `toGovModel()`
 *  (components/record/RecordGovernance.tsx); fixtures supply it directly. */
export type GovModel = {
  /** null = not in the lifecycle registry. */
  workflowState: "draft" | "in_review" | "approved" | "retired" | null;
  /** Approval steps on file: history minus `import` backfills (and minus owner changes, see toGovModel). */
  approvalSteps: number;
  /** Newest state-changing history item. `via` distinguishes the two platform-written
   *  backfills: "import" (B10b, already approved) and "predates_workflow" (B10c, in
   *  force before the approval lifecycle existed). */
  lastStep: { action: string; at: string; actor: string; reason: string; via?: string } | null;
  /** Newest "submit" step (for "in review since"). */
  lastSubmitAt: string | null;
  attestation: {
    /** Judged on the last COMPLETE attestation: one awaiting its second signature has
     *  certified nothing, so it leaves the status where it was. */
    status: "current" | "overdue" | "never";
    nativeReview: boolean;
    nextDue: string | null;
    canAttest: boolean | null;
    blockedReason: string | null;
    /** Decision 9: this record's attestation needs an independent second signature. */
    confirmationRequired?: boolean;
    /** Why it does ("Key control"), when it does. */
    confirmationReason?: string | null;
    /** The newest attestation is signed but still waiting for that signature. */
    awaitingConfirmation?: boolean;
    awaitingBy?: string | null;
    awaitingAt?: string | null;
  } | null;
  /** useHasPermission("<module>:write") */
  canWrite: boolean;
};

export type Ctx = { fmt: Fmt; now: Date; gov: GovModel };
