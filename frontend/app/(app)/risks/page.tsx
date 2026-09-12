"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, apiCall, type CustomField, type MatrixLevel, type RiskAcceptance, type RiskMatrixConfig, type RiskSetting, type TreatmentAction } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { confirmDeleteWithImpact, WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";
import { deleteEach, deleteErrorText, toastDeleteSummary } from "@/lib/bulkDelete";
import { cachedBusinessUnits, lookupValues, pickProcesses, type LookupRef, type LookupValue, type UserRef } from "@/lib/masterData";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import BusinessUnitSelect from "@/components/BusinessUnitSelect";
import ProcessSelect from "@/components/ProcessSelect";
import WorkflowFields from "@/components/WorkflowFields";
import ArchivedRecords from "@/components/ArchivedRecords";
import CustomFieldsEditor from "@/components/CustomFieldsEditor";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import RecordIssues from "@/components/RecordIssues";
import RelatedChips from "@/components/RelatedChips";
import RiskAcceptancePanel from "@/components/RiskAcceptancePanel";
import RiskTreatmentActions from "@/components/RiskTreatmentActions";
import ResidualSuggestion from "@/components/ResidualSuggestion";
import WorkflowStrip from "@/components/WorkflowStrip";
import RiskMethodology from "@/components/RiskMethodology";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import AsyncSelect from "@/components/AsyncSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import GenerateRisks, { type GenerateRisksHandle } from "@/components/GenerateRisks";
import Menu from "@/components/Menu";
import ImportExport, { type ImportExportHandle } from "@/components/ImportExport";
import OrphanCleanup, { type OrphanCleanupHandle } from "@/components/OrphanCleanup";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import { titleCase } from "@/lib/text";
import { useFilterParams, type FilterSpec, type FilterValues } from "@/lib/useFilterParams";
import { useRouter } from "next/navigation";
import RiskHierarchyTree, { LevelBadge, LEVEL_LABEL } from "@/components/RiskHierarchyTree";
import BulkEditBar from "@/components/BulkEditBar";

// --------------------------------------------------------------- inline types
type Ref = { id: string; reference?: string; title?: string; name?: string };

type RiskRow = {
  id: string;
  reference: string;
  title: string;
  description: string;
  /** Legacy free text, kept in step with the picked category. */
  category: string;
  category_id: string | null;
  category_ref: (LookupRef & { path?: string }) | null;
  status: string;
  owner_id: string | null;
  owner_ref: UserRef | null;

  inherent_likelihood: number;
  inherent_impact: number;
  inherent_score: number | null;
  residual_likelihood: number | null;
  residual_impact: number | null;
  residual_score: number | null;
  inherent_severity: string | null;
  residual_severity: string | null;
  residual_override_reason?: string;

  // Phase 2: the risk statement, classification, target and assessment trail.
  cause?: string;
  event?: string;
  consequence?: string;
  risk_type?: string | null;
  velocity?: string | null;
  source?: string | null;
  identified_date?: string | null;
  identified_by_id?: string | null;
  identified_by_ref?: UserRef | null;
  target_likelihood?: number | null;
  target_impact?: number | null;
  target_score?: number | null;
  target_severity?: string | null;
  assessment_rationale?: string;
  last_assessed_at?: string | null;
  last_assessed_by_ref?: UserRef | null;
  impact_dimensions?: { id: string; dimension_id: string; dimension_ref: LookupRef | null; basis: string; score: number; rationale: string }[];
  treatment_actions?: TreatmentAction[];
  treatment_progress?: { done: number; total: number; open: number; overdue: number; percent: number } | null;
  /** The appetite that applies: the risk's top-level category's, else the organisation's. */
  appetite_score?: number | null;
  tolerance_score?: number | null;
  appetite_status?: string | null;
  appetite_category_id?: string | null;

  // Raised when something the risk depended on changed underneath it; one reason per line.
  needs_review?: boolean;
  review_reason?: string;

  // Phase 3 hierarchy: 1 enterprise, 2 category, 3 scenario (null = not placed).
  level?: number | null;
  parent_id?: string | null;
  /** The live parent; null when there is none or it was archived. */
  parent?: Ref | null;
  /** Live risks directly below. */
  children_count?: number;

  annual_loss_frequency: number | null;
  single_loss_expectancy: number | null;
  annual_loss_expectancy: number | null;

  treatment_strategy: string | null;
  treatment_description: string;
  /** Legacy free text; shown only while no user is picked. */
  treatment_owner: string;
  treatment_owner_id: string | null;
  treatment_owner_ref: UserRef | null;
  treatment_deadline: string | null;
  treatment_cost: number | null;

  review_frequency: string;
  last_review_date: string | null;
  next_review_date: string | null;
  expired_reviews: number;
  /** Read-only: moved only through WorkflowFields. */
  workflow_status: string;

  control_health?: string;

  business_units: Ref[];
  processes: Ref[];
  assets: Ref[];
  controls: Ref[];
  threats: Ref[];
  vulnerabilities: Ref[];
  policies: Ref[];
  incidents: Ref[];

  acceptances?: RiskAcceptance[];
  created_at?: string;
  updated_at?: string;

  // reverse graph links (read-only, from GET /risks/{id})
  requirements?: Ref[];
  exceptions?: Ref[];
  vendors?: Ref[];
  projects?: Ref[];
  goals?: Ref[];
  processing_activities?: Ref[];
  audit_findings?: Ref[];
  issues?: Ref[];
};

type Named = { id: string; name?: string; reference?: string; title?: string };

/** GET /risks/{id}/rollup — everything below a risk in the hierarchy. */
type RollupNode = {
  id: string; reference: string; title: string; level: number | null; depth: number;
  exposure: number | null; residual_score: number | null; severity: string | null; appetite_status: string | null;
};
type RiskRollupView = {
  children: RollupNode[]; descendants: RollupNode[]; worst_residual: RollupNode | null;
  worst_exposure: RollupNode | null; by_severity: Record<string, number>; breaches: number; total: number;
};

// --------------------------------------------------------------- option helpers
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "assessed", "treatment_planned", "treatment_in_progress", "accepted", "closed"]);
const STRATEGY = opts(["mitigate", "accept", "transfer", "avoid"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
/* Phase 2 fixed vocabularies — they mirror RISK_TYPES / RISK_VELOCITIES / RISK_SOURCES
   on the server, which refuses anything else. */
const RISK_TYPE = opts(["strategic", "operational", "financial", "compliance", "technology", "emerging"]);
const VELOCITY: Option[] = [
  { value: "immediate", label: "Immediate — within days" },
  { value: "weeks", label: "Weeks" },
  { value: "months", label: "Months" },
  { value: "years", label: "Years" },
];
const SOURCE: Option[] = [
  { value: "rcsa", label: "RCSA" },
  { value: "audit", label: "Audit" },
  { value: "incident", label: "Incident" },
  { value: "regulatory", label: "Regulatory" },
  { value: "self_identified", label: "Self-identified" },
  { value: "generated", label: "Generated (scenario library)" },
  { value: "other", label: "Other" },
];
const sourceLabel = (v: string | null | undefined) => SOURCE.find((o) => o.value === v)?.label ?? (v ? cap(v) : "");
const velocityLabel = (v: string | null | undefined) => VELOCITY.find((o) => o.value === v)?.label ?? (v ? cap(v) : "");
/** Mirrors risk_integrity.compose_title: "<Event>, caused by <cause>, resulting in <consequence>". */
function composeTitle(cause: string, event: string, consequence: string): string {
  const clean = (t: string) => t.split(/\s+/).filter(Boolean).join(" ").replace(/[ .;,]+$/, "");
  const lower = (t: string) => (/^[A-Z]{2}/.test(t) ? t : t.charAt(0).toLowerCase() + t.slice(1));
  const ev = clean(event);
  if (!ev) return "";
  const parts = [ev.charAt(0).toUpperCase() + ev.slice(1)];
  if (clean(cause)) parts.push(`caused by ${lower(clean(cause))}`);
  if (clean(consequence)) parts.push(`resulting in ${lower(clean(consequence))}`);
  const title = parts.join(", ");
  return title.length > 255 ? title.slice(0, 254) + "…" : title;
}
/** How impact-dimension scores combine (RiskSetting.impact_mode). */
function combineImpact(scores: number[], mode: string | undefined): number | null {
  if (!scores.length) return null;
  if (mode === "average") return Math.ceil(scores.reduce((a, b) => a + b, 0) / scores.length);
  return Math.max(...scores);
}
const DIM_BASES = ["inherent", "residual"] as const;
/** Score options for the tenant's matrix — a 4x4 register must not offer a 5. */
const scaleOptions = (size: number): Option[] =>
  Array.from({ length: size }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }));

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  closed: "low",
  accepted: "info",
  treatment_in_progress: "medium",
  treatment_planned: "medium",
  assessed: "info",
  draft: "neutral",
};

/** The picked category as the list shows it: "Parent › Child", else the legacy text. */
const categoryText = (r: Pick<RiskRow, "category" | "category_ref">) =>
  r.category_ref ? r.category_ref.path || r.category_ref.label : r.category || "";

const workflowLabel = (s: string) => WORKFLOW_STATE_LABEL[s as WorkflowStateKey] ?? cap(s);

function isOverdue(d: string | null): boolean {
  if (!d) return false;
  return new Date(d) < new Date(new Date().toDateString());
}

/** Where the risk stands against the appetite that applies to it — its top-level
 *  category's where one is set (the server says which), else the organisation's. */
function appetite(r: RiskRow, s: RiskSetting | null) {
  const label = { within_appetite: "within appetite", elevated: "elevated", breach: "breach" } as const;
  const tone = { within_appetite: "low", elevated: "medium", breach: "critical" } as const;
  let status = r.appetite_status as keyof typeof label | null | undefined;
  if (status === undefined) {
    if (!s) return null;
    const score = r.residual_score ?? r.inherent_score;
    if (score == null) return null;
    status = score <= s.appetite_score ? "within_appetite" : score <= s.tolerance_score ? "elevated" : "breach";
  }
  if (!status || !(status in label)) return null;
  const thresholds = r.tolerance_score != null ? ` (appetite ${r.appetite_score}, tolerance ${r.tolerance_score}${r.appetite_category_id ? ", category's" : ""})` : "";
  return { label: label[status], tone: tone[status], title: `${cap(label[status])}${thresholds}` };
}

// live rollup of the health of a record's mitigating controls
function controlHealth(v: string | null | undefined): React.ReactNode {
  if (v === "issues") return <Badge tone="high">Control issues</Badge>;
  if (v === "ok") return <Badge tone="low">Controls OK</Badge>;
  return <span className="muted">—</span>;
}

/** One reason per line on the risk; shown as the badge's tooltip and in the drawer. */
const reviewReasons = (r: { review_reason?: string }) =>
  (r.review_reason || "").split("\n").filter((x) => x.trim());

const REVIEW_FILTER: Option[] = [
  { value: "true", label: "Needs review" },
  { value: "false", label: "No review needed" },
];

/* Phase 3: filters that live in the URL, so the dashboard's numbers open the risks behind
   them (/risks?review=overdue, ?appetite=breach, ?treatment_overdue=true …) and one branch
   of the hierarchy is a link (?parent_id=…). The server defines each exactly as the
   dashboard counts it (services/risk_query.py). Booleans are declared as values because
   the table leaves `false` out of its query. `view=tree` shows the hierarchy. */
const RISK_URL_FILTERS = {
  // The dashboard's "By segment" rows open /risks?business_unit_id=…
  business_unit_id: "string",
  level: ["1", "2", "3", "none"],
  parent_id: "string",
  roots_only: ["true"],
  review: ["overdue", "due_30d"],
  appetite: ["within", "elevated", "breach"],
  has_controls: ["true", "false"],
  treatment_overdue: ["true"],
  view: ["tree"],
} as const satisfies FilterSpec;

const LEVEL_FILTER: Option[] = [
  { value: "1", label: "L1 · Enterprise" },
  { value: "2", label: "L2 · Category" },
  { value: "3", label: "L3 · Scenario" },
  { value: "none", label: "Not placed" },
];
const LEVEL_OPTIONS: Option[] = [
  { value: "1", label: "1 — Enterprise (what the board reads)" },
  { value: "2", label: "2 — Category" },
  { value: "3", label: "3 — Scenario (what practitioners assess)" },
];
const DUE_FILTER: Option[] = [
  { value: "overdue", label: "Review overdue" },
  { value: "due_30d", label: "Review due in 30 days" },
];
const APPETITE_FILTER: Option[] = [
  { value: "within", label: "Within appetite" },
  { value: "elevated", label: "Elevated" },
  { value: "breach", label: "Above tolerance" },
];
const CONTROLS_FILTER: Option[] = [
  { value: "true", label: "Has controls" },
  { value: "false", label: "No controls" },
];
const TREATMENT_FILTER: Option[] = [{ value: "true", label: "Treatment overdue" }];

// --------------------------------------------------------------- form state
type FormState = {
  title: string;
  description: string;
  cause: string;
  event: string;
  consequence: string;
  risk_type: string;
  velocity: string;
  source: string;
  identified_date: string;
  identified_by_id: string | null;
  category_id: string | null;
  status: string;
  owner_id: string | null;
  inherent_likelihood: number | "";
  inherent_impact: number | "";
  residual_likelihood: string;
  residual_impact: string;
  target_likelihood: string;
  target_impact: string;
  assessment_rationale: string;
  /** Impact scored per dimension, keyed "basis:dimension_id" -> score ("" = not scored). */
  dims: Record<string, string>;
  residual_override_reason: string;
  annual_loss_frequency: number | "";
  single_loss_expectancy: number | "";
  treatment_strategy: string;
  treatment_description: string;
  treatment_owner_id: string | null;
  treatment_deadline: string;
  treatment_cost: number | "";
  review_frequency: string;
  business_unit_ids: AsyncOption[];
  process_ids: AsyncOption[];
  asset_ids: AsyncOption[];
  control_ids: AsyncOption[];
  threat_ids: AsyncOption[];
  vulnerability_ids: AsyncOption[];
  policy_ids: AsyncOption[];
  incident_ids: AsyncOption[];
  /** Hierarchy: "" = not placed (or: follows the parent's level + 1 when a parent is set). */
  level: string;
  parent: { id: string; label: string } | null;
};

const refToOpt = (x: Ref): AsyncOption => ({
  value: x.id,
  label: x.reference || x.title || x.name || x.id,
});

/* No pre-filled scores: an assessor chooses them (the old 3x3 default made unscored risks
   look assessed). A draft may be saved unscored; it leaves draft once scored with a
   rationale. */
const BLANK: FormState = {
  title: "", description: "", cause: "", event: "", consequence: "",
  risk_type: "", velocity: "", source: "", identified_date: "", identified_by_id: null,
  category_id: null, status: "draft", owner_id: null,
  inherent_likelihood: "", inherent_impact: "",
  residual_likelihood: "", residual_impact: "", target_likelihood: "", target_impact: "",
  assessment_rationale: "", dims: {}, residual_override_reason: "",
  annual_loss_frequency: "", single_loss_expectancy: "",
  treatment_strategy: "", treatment_description: "", treatment_owner_id: null,
  treatment_deadline: "", treatment_cost: "", review_frequency: "annual",
  business_unit_ids: [], process_ids: [],
  asset_ids: [], control_ids: [], threat_ids: [], vulnerability_ids: [], policy_ids: [], incident_ids: [],
  level: "", parent: null,
};

function fromRisk(r: RiskRow): FormState {
  // A draft never scored (no assessment stamp) shows blank scores, not the stored 1x1.
  const unscored = r.status === "draft" && !r.last_assessed_at;
  return {
    title: r.title,
    description: r.description || "",
    cause: r.cause || "",
    event: r.event || "",
    consequence: r.consequence || "",
    risk_type: r.risk_type || "",
    velocity: r.velocity || "",
    source: r.source || "",
    identified_date: r.identified_date || "",
    identified_by_id: r.identified_by_id ?? null,
    category_id: r.category_id ?? null,
    status: r.status,
    owner_id: r.owner_id ?? null,
    inherent_likelihood: unscored ? "" : r.inherent_likelihood,
    inherent_impact: unscored ? "" : r.inherent_impact,
    residual_likelihood: r.residual_likelihood ? String(r.residual_likelihood) : "",
    residual_impact: r.residual_impact ? String(r.residual_impact) : "",
    target_likelihood: r.target_likelihood ? String(r.target_likelihood) : "",
    target_impact: r.target_impact ? String(r.target_impact) : "",
    assessment_rationale: r.assessment_rationale || "",
    dims: Object.fromEntries((r.impact_dimensions ?? []).map((d) => [`${d.basis}:${d.dimension_id}`, String(d.score)])),
    residual_override_reason: r.residual_override_reason || "",
    annual_loss_frequency: r.annual_loss_frequency ?? "",
    single_loss_expectancy: r.single_loss_expectancy ?? "",
    treatment_strategy: r.treatment_strategy || "",
    treatment_description: r.treatment_description || "",
    treatment_owner_id: r.treatment_owner_id ?? null,
    treatment_deadline: r.treatment_deadline || "",
    treatment_cost: r.treatment_cost ?? "",
    review_frequency: r.review_frequency,
    business_unit_ids: (r.business_units ?? []).map(refToOpt),
    process_ids: (r.processes ?? []).map(refToOpt),
    asset_ids: r.assets.map(refToOpt),
    control_ids: r.controls.map(refToOpt),
    threat_ids: r.threats.map(refToOpt),
    vulnerability_ids: r.vulnerabilities.map(refToOpt),
    policy_ids: r.policies.map(refToOpt),
    incident_ids: r.incidents.map(refToOpt),
    level: r.level ? String(r.level) : "",
    // An archived parent stays linked (unchanged, it is not re-checked on save).
    parent: r.parent
      ? { id: r.parent.id, label: `${r.parent.reference ?? ""} — ${r.parent.title ?? ""}` }
      : r.parent_id ? { id: r.parent_id, label: "Archived parent" } : null,
  };
}

function toPayload(f: FormState): Record<string, unknown> {
  const num = (v: number | "") => (v === "" ? null : Number(v));
  const scale = (v: string) => (v === "" ? null : Number(v));
  const dims = Object.entries(f.dims)
    .filter(([, v]) => v !== "")
    .map(([key, v]) => {
      const [basis, dimension_id] = key.split(":");
      return { basis, dimension_id, score: Number(v) };
    });
  return {
    title: f.title.trim(),
    description: f.description,
    cause: f.cause,
    event: f.event,
    consequence: f.consequence,
    risk_type: f.risk_type || null,
    velocity: f.velocity || null,
    source: f.source || null,
    identified_date: f.identified_date || null,
    identified_by_id: f.identified_by_id,
    category_id: f.category_id,
    status: f.status,
    owner_id: f.owner_id,
    // Blank = not chosen yet; the server keeps a draft unscored.
    inherent_likelihood: f.inherent_likelihood === "" ? null : Number(f.inherent_likelihood),
    inherent_impact: f.inherent_impact === "" ? null : Number(f.inherent_impact),
    residual_likelihood: scale(f.residual_likelihood),
    residual_impact: scale(f.residual_impact),
    target_likelihood: scale(f.target_likelihood),
    target_impact: scale(f.target_impact),
    assessment_rationale: f.assessment_rationale.trim(),
    impact_dimensions: dims,
    residual_override_reason: f.residual_override_reason.trim(),
    annual_loss_frequency: num(f.annual_loss_frequency),
    single_loss_expectancy: num(f.single_loss_expectancy),
    treatment_strategy: f.treatment_strategy || null,
    treatment_description: f.treatment_description,
    treatment_owner_id: f.treatment_owner_id,
    treatment_deadline: f.treatment_deadline || null,
    treatment_cost: num(f.treatment_cost),
    review_frequency: f.review_frequency,
    business_unit_ids: f.business_unit_ids.map((o) => o.value),
    process_ids: f.process_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
    control_ids: f.control_ids.map((o) => o.value),
    threat_ids: f.threat_ids.map((o) => o.value),
    vulnerability_ids: f.vulnerability_ids.map((o) => o.value),
    policy_ids: f.policy_ids.map((o) => o.value),
    incident_ids: f.incident_ids.map((o) => o.value),
    // With a parent and no level the server places the risk one level below it.
    level: f.level === "" ? null : Number(f.level),
    parent_id: f.level === "1" ? null : f.parent?.id ?? null,
  };
}

// --------------------------------------------------------------- page
function RisksPage() {
  const [settings, setSettings] = useState<RiskSetting | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [recordId, setRecordId] = useRecordParam("id");
  // Hierarchy and drill-through filters, read from and written to the URL.
  const urlFilters = useFilterParams(RISK_URL_FILTERS);
  const treeView = urlFilters.values.view === "tree";
  const [rollup, setRollup] = useState<RiskRollupView | null>(null);
  const [parentFilterLabel, setParentFilterLabel] = useState("");
  const { currency, formatDate, formatDateTime, formatMoney } = useFormat();
  /** Money in the organisation's currency, compact from a million up ("PKR 1.2M"). */
  const money = (n: number | null | undefined) => formatMoney(n, null, { compact: "auto" });
  // Read-only detail loaded for the view drawer (?id=). Edit is a separate action.
  const [detail, setDetail] = useState<RiskRow | null>(null);

  // appetite editor
  const [showSettings, setShowSettings] = useState(false);
  // The import/export, generator and orphan dialogs are driven from the More menu, so
  // the page head holds three controls instead of eight.
  const io = useRef<ImportExportHandle>(null);
  const gen = useRef<GenerateRisksHandle>(null);
  const orphans = useRef<OrphanCleanupHandle>(null);
  const [appetiteScore, setAppetiteScore] = useState(6);
  const [toleranceScore, setToleranceScore] = useState(12);

  // form modal
  const [editing, setEditing] = useState<RiskRow | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  // Impact dimensions (Settings → Lookups → Impact dimension), the grid's rows.
  const [dimensions, setDimensions] = useState<LookupValue[]>([]);

  // Segment scope. A risk workshop convenes around one business unit or process, so the
  // register needs to narrow to that cut — and whatever is narrowed to here is what the
  // register PDF exports, so the download always matches the screen it was launched from.
  // The organisation's own wording for each rung of the two axes. An assessor picking
  // "4" needs to know what the bank decided 4 means, or the number is just a number and
  // two people scoring the same risk will disagree.
  const [matrix, setMatrix] = useState<RiskMatrixConfig | null>(null);
  const [showScale, setShowScale] = useState(false);

  // The business-unit scope lives in the URL (see RISK_URL_FILTERS); its name is looked
  // up for the scope label and the PDF cover.
  const [scopeUnitName, setScopeUnitName] = useState("");
  const scopeUnitId = urlFilters.values.business_unit_id ?? null;
  const scopeUnit = useMemo(
    () => (scopeUnitId ? { id: scopeUnitId, name: scopeUnitName } : null),
    [scopeUnitId, scopeUnitName],
  );
  const updateUrlFilters = urlFilters.update;
  const setScopeUnit = useCallback(
    (next: { id: string; name: string } | null) => {
      setScopeUnitName(next?.name ?? "");
      updateUrlFilters({ business_unit_id: next?.id || undefined });
    },
    [updateUrlFilters],
  );
  useEffect(() => {
    if (!scopeUnitId) return;
    cachedBusinessUnits()
      .then((all) => { const unit = all.find((x) => x.id === scopeUnitId); if (unit) setScopeUnitName(unit.name); })
      .catch(() => {});
  }, [scopeUnitId]);
  const [scopeProcess, setScopeProcess] = useState<{ id: string; name: string } | null>(null);
  const [scopeStatus, setScopeStatus] = useState("");
  const [scopeReview, setScopeReview] = useState("");
  const [scopeAsset, setScopeAsset] = useState<{ id: string; name: string } | null>(null);

  // org-defined custom fields, edited inside the form and saved with the record
  const [cfDefs, setCfDefs] = useState<CustomField[]>([]);
  const [cfValues, setCfValues] = useState<Record<string, string>>({});

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  // The matrix is per-organisation configurable, so every score input and threshold
  // bound is derived from it rather than assuming 5x5.
  const matrixSize = settings?.matrix_size ?? 5;
  const maxScore = matrixSize * matrixSize;
  const SCALE = scaleOptions(matrixSize);

  /* Each axis gets its own options, labelled in the organisation's words — "3 — Possible"
     rather than a bare "3". The dropdown is a native <select>, so the option text is the
     only thing that can carry meaning inside it; the full definition goes underneath the
     field and in the reference table, where it has room to be a sentence. */
  const axisOptions = (levels: MatrixLevel[] | undefined): Option[] =>
    levels?.length
      ? levels.map((l) => ({ value: String(l.level), label: l.label ? `${l.level} — ${l.label}` : String(l.level) }))
      : SCALE;
  const LIKELIHOOD = axisOptions(matrix?.likelihood_levels);
  const IMPACT = axisOptions(matrix?.impact_levels);

  /** The chosen rung's definition, for the line under the field. */
  const rung = (levels: MatrixLevel[] | undefined, value: number | string) => {
    const n = Number(value);
    if (!n || !levels) return null;
    const hit = levels.find((l) => l.level === n);
    if (!hit || (!hit.label && !hit.definition)) return null;
    return (
      <span>
        <b>{hit.level} — {hit.label}</b>
        {hit.definition ? `: ${hit.definition}` : ""}
      </span>
    );
  };

  /** Both axes' chosen wording on one line, or nothing when neither is set. */
  const chosen = (likelihood: number | string, impact: number | string) => {
    const l = rung(matrix?.likelihood_levels, likelihood);
    const i = rung(matrix?.impact_levels, impact);
    if (!l && !i) return null;
    return (
      <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, marginTop: 6 }}>
        {l && <div>Likelihood {l}</div>}
        {i && <div>Impact {i}</div>}
      </div>
    );
  };

  /** True once somebody has actually written the criteria down. */
  const scaleIsDefined = Boolean(
    matrix?.likelihood_levels?.some((l) => l.definition) || matrix?.impact_levels?.some((l) => l.definition),
  );
  const fetchRisks = useCallback((qs: string) => apiCall<PagedList<RiskRow>>("GET", `/risks?${qs}`), []);

  // One scope object, read by the table and by the export. Undefined entries are
  // dropped from the query string, so "no scope" is the plain register. The review
  // filter narrows the table only: the register PDF has no such filter yet.
  const scopeFilters = useMemo(
    () => ({
      business_unit_id: scopeUnit?.id || undefined,
      process_id: scopeProcess?.id || undefined,
      asset_id: scopeAsset?.id || undefined,
      status: scopeStatus || undefined,
    }),
    [scopeUnit, scopeProcess, scopeAsset, scopeStatus],
  );
  // The phase-3 URL filters narrow the table only, like the review flag: the register
  // PDF endpoint does not forward them yet (services/risk_query.py already supports them).
  const u = urlFilters.values;
  const tableFilters = useMemo(
    () => ({
      ...scopeFilters,
      needs_review: scopeReview || undefined,
      level: u.level, parent_id: u.parent_id, roots_only: u.roots_only, review: u.review,
      appetite: u.appetite, has_controls: u.has_controls, treatment_overdue: u.treatment_overdue,
    }),
    [scopeFilters, scopeReview, u.level, u.parent_id, u.roots_only, u.review, u.appetite, u.has_controls, u.treatment_overdue],
  );
  // The parent a "risks below" link narrowed to, by reference.
  useEffect(() => {
    if (!u.parent_id) { setParentFilterLabel(""); return; }
    apiCall<RiskRow>("GET", `/risks/${u.parent_id}`)
      .then((r) => setParentFilterLabel(`${r.reference} — ${r.title}`))
      .catch(() => setParentFilterLabel("an archived risk"));
  }, [u.parent_id]);
  const router = useRouter();
  const setUrlFilter = (key: keyof typeof RISK_URL_FILTERS & string, value: string) =>
    urlFilters.update({ [key]: value || undefined } as FilterValues<typeof RISK_URL_FILTERS>);
  const urlFiltered = Boolean(u.level || u.parent_id || u.roots_only || u.review || u.appetite || u.has_controls || u.treatment_overdue);
  const clearUrlFilters = () =>
    urlFilters.update({
      level: undefined, parent_id: undefined, roots_only: undefined, review: undefined,
      appetite: undefined, has_controls: undefined, treatment_overdue: undefined,
    });
  /** Close the open record and list the risks directly below it — one URL change, so
   *  the record param and the filter cannot overwrite each other. */
  const showBelow = (id: string) => {
    const next = new URLSearchParams(window.location.search);
    next.delete("id");
    next.delete("view");
    next.set("parent_id", id);
    router.replace(`/risks?${next.toString()}`, { scroll: false });
  };
  /** Parents a risk can sit under: live risks at a higher level (a lower number). */
  const parentSearch = (q: string) => {
    const max = f.level ? Math.max(Number(f.level) - 1, 1) : 2;
    return apiCall<PagedList<RiskRow>>("GET", `/risks?max_level=${max}&limit=20&search=${encodeURIComponent(q)}`).then((r) =>
      r.items
        .filter((x) => x.id !== editing?.id)
        .map((x) => ({ value: x.id, label: `${x.reference} — ${x.title}`, sub: x.level ? `L${x.level} · ${LEVEL_LABEL[x.level]}` : undefined })),
    );
  };
  const scopeLabel = useMemo(() => {
    const parts = [
      scopeUnit?.name,
      scopeProcess?.name,
      scopeAsset?.name,
      scopeStatus ? cap(scopeStatus) : undefined,
    ].filter(Boolean);
    return parts.length ? `Scoped to ${parts.join(" · ")}` : "Whole register";
  }, [scopeUnit, scopeProcess, scopeAsset, scopeStatus]);

  // Server typeahead sources for the form's link pickers (replaces 6 capped preloads).
  const linkSearch = (path: string) => (q: string) =>
    apiCall<PagedList<Named>>("GET", `/${path}?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((x) => ({ value: x.id, label: x.name || x.title || x.reference || x.id, sub: x.reference })),
    );

  useEffect(() => {
    api.riskSettings().then((s) => {
      setSettings(s);
      setAppetiteScore(s.appetite_score);
      setToleranceScore(s.tolerance_score);
    }).catch(() => {});
    api.customFields("risk").then((d) => setCfDefs(d.filter((x) => x.enabled))).catch(() => {});
    api.riskMatrixConfig().then(setMatrix).catch(() => {});
    lookupValues("impact_dimension").then(setDimensions).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setCfValues({});
    setError(null);
    setShowForm(true);
  }
  function openEdit(r: RiskRow) {
    setEditing(r);
    setF(fromRisk(r));
    setCfValues({});
    if (cfDefs.length) {
      api
        .customFieldValues("risk", r.id)
        .then((rows) => setCfValues(Object.fromEntries(rows.map((x) => [x.field.id, x.value]))))
        .catch(() => {});
    }
    setError(null);
    setShowForm(true);
  }

  // Deep-link view: ?id= (row click, global search, ⌘K) loads the record's full detail
  // into the read-only drawer. Editing is a separate action from there.
  const loadDetail = useCallback((id: string) => {
    apiCall<RiskRow>("GET", `/risks/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (recordId) loadDetail(recordId);
    else setDetail(null);
  }, [recordId, loadDetail]);
  // What sits below the open risk in the hierarchy.
  useEffect(() => {
    if (!detail?.children_count) { setRollup(null); return; }
    apiCall<RiskRollupView>("GET", `/risks/${detail.id}/rollup`).then(setRollup).catch(() => setRollup(null));
  }, [detail?.id, detail?.children_count]);

  async function save() {
    setError(null);
    if (!f.title.trim() && !f.event.trim()) {
      setError("Give the risk a title, or describe the event — the title is then composed from the statement.");
      return;
    }
    if (residualAbove && !f.residual_override_reason.trim()) {
      setError("Residual cannot exceed inherent without an override reason. Lower the residual, or write down why it is higher.");
      return;
    }
    if (targetAbove) {
      setError("The target cannot be higher than the residual (or inherent) risk — treatment only lowers a risk.");
      return;
    }
    if (rationaleNeeded && !rationaleFresh) {
      setError(leavingDraft
        ? "Before this risk leaves draft, choose its inherent likelihood and impact and write the assessment rationale."
        : "The scores changed: write down why in the assessment rationale.");
      return;
    }
    if (leavingDraft && (f.inherent_likelihood === "" || f.inherent_impact === "")) {
      setError("Choose the inherent likelihood and impact before moving the risk out of draft.");
      return;
    }
    setSaving(true);
    try {
      const payload = toPayload(f);
      let riskId = editing?.id;
      if (editing) await apiCall("PATCH", `/risks/${editing.id}`, payload);
      else riskId = (await apiCall<RiskRow>("POST", "/risks", payload)).id;
      if (cfDefs.length && riskId) {
        await api.setCustomFieldValues("risk", riskId, cfValues);
      }
      setShowForm(false);
      reload();
      if (recordId) loadDetail(recordId);  // refresh the open view drawer
      toast(editing ? "Changes saved" : "Risk created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save risk");
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: RiskRow) {
    if (!(await confirmDeleteWithImpact("risk", r.id, `${r.reference} — ${r.title}`))) return;
    try {
      await apiCall("DELETE", `/risks/${r.id}`);
      if (recordId === r.id) setRecordId(null);
      reload();
      toast(`Archived ${r.reference}`);
    } catch (e) {
      // A segregation-of-duties refusal (you entered it) says who must delete it.
      toast(deleteErrorText(e, "Failed to delete risk"), "error");
    }
  }

  async function markReviewed(r: RiskRow) {
    try {
      await apiCall("POST", `/risks/${r.id}/mark-reviewed`);
      reload();
      loadDetail(r.id);
      toast("Marked reviewed");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not mark the risk reviewed", "error");
    }
  }

  async function saveSettings(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const s = await api.updateRiskSettings({ appetite_score: appetiteScore, tolerance_score: toleranceScore });
      setSettings(s);
      setShowSettings(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    }
  }

  const personText = (u: UserRef | null | undefined, fallback?: string) => (u ? u.full_name || u.email : fallback || "");
  const linkCount = (r: RiskRow) =>
    r.assets.length + r.controls.length + r.threats.length + r.vulnerabilities.length + r.policies.length + r.incidents.length;

  // read-only helpers for the view drawer
  const chips = (items: Ref[]) =>
    items.length ? (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((x) => (
          <span key={x.id} className="chip">{x.reference || x.title || x.name || x.id}</span>
        ))}
      </div>
    ) : (
      <span className="muted">—</span>
    );
  const field = (label: string, value: React.ReactNode) => (
    <div style={{ minWidth: 140 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
      <div style={{ marginTop: 3 }}>{value ?? <span className="muted">—</span>}</div>
    </div>
  );

  // computed previews
  const inhScore = f.inherent_likelihood === "" || f.inherent_impact === "" ? null : Number(f.inherent_likelihood) * Number(f.inherent_impact);
  const resScore = f.residual_likelihood === "" || f.residual_impact === "" ? null : Number(f.residual_likelihood) * Number(f.residual_impact);
  const tgtScore = f.target_likelihood === "" || f.target_impact === "" ? null : Number(f.target_likelihood) * Number(f.target_impact);
  // Treatment only lowers a risk: target <= residual <= inherent.
  const targetAbove = tgtScore != null && ((resScore != null && tgtScore > resScore) || (inhScore != null && tgtScore > inhScore));

  /* The assessment trail. A score change needs a new rationale (a draft may keep
     provisional scores without one); leaving draft needs chosen scores and a rationale.
     The server enforces both — this only says so before the round trip. */
  const storedScores = editing && !(editing.status === "draft" && !editing.last_assessed_at)
    ? [editing.inherent_likelihood, editing.inherent_impact, editing.residual_likelihood ?? "", editing.residual_impact ?? ""].map(String)
    : ["", "", "", ""];
  const formScores = [f.inherent_likelihood, f.inherent_impact, f.residual_likelihood, f.residual_impact].map(String);
  const scoresChanged = formScores.some((v, i) => v !== storedScores[i]);
  const leavingDraft = f.status !== "draft" && (!editing || editing.status === "draft");
  const rationaleNeeded = (scoresChanged && f.status !== "draft") || leavingDraft;
  const rationaleFresh = Boolean(f.assessment_rationale.trim()) &&
    (!scoresChanged || f.assessment_rationale.trim() !== (editing?.assessment_rationale ?? "").trim() || !editing);

  /** Set a score; the first change clears a rationale that described the old scores. */
  const setScore = (k: "inherent_likelihood" | "inherent_impact" | "residual_likelihood" | "residual_impact", v: string) =>
    setF((p) => {
      const next = { ...p, [k]: k.startsWith("inherent") ? (v === "" ? "" : Number(v)) : v } as FormState;
      if (editing && p.assessment_rationale === (editing.assessment_rationale ?? "") && p.assessment_rationale) {
        next.assessment_rationale = "";
      }
      return next;
    });

  /** Dimension rows: the active list, plus any dimension the risk is already scored on. */
  const dimensionRows = useMemo(() => {
    const rows = dimensions.map((d) => ({ id: d.id, label: d.label }));
    for (const d of editing?.impact_dimensions ?? []) {
      if (!rows.some((r) => r.id === d.dimension_id)) rows.push({ id: d.dimension_id, label: d.dimension_ref?.label ?? "Dimension" });
    }
    return rows;
  }, [dimensions, editing]);
  /** The overall impact a basis' dimension scores decide, or null when none is scored. */
  const dimImpact = (dims: Record<string, string>, basis: string) =>
    combineImpact(
      Object.entries(dims).filter(([k, v]) => k.startsWith(`${basis}:`) && v !== "").map(([, v]) => Number(v)),
      settings?.impact_mode,
    );
  const setDim = (basis: string, dimensionId: string, v: string) =>
    setF((p) => {
      const dims = { ...p.dims, [`${basis}:${dimensionId}`]: v };
      const derived = dimImpact(dims, basis);
      const next = { ...p, dims } as FormState;
      if (derived != null) {
        if (basis === "inherent") next.inherent_impact = derived;
        else next.residual_impact = String(derived);
      }
      if (editing && p.assessment_rationale === (editing.assessment_rationale ?? "") && p.assessment_rationale) {
        next.assessment_rationale = "";
      }
      return next;
    });
  const inherentByDims = dimImpact(f.dims, "inherent") != null;
  const residualByDims = dimImpact(f.dims, "residual") != null;
  const hasActions = (editing?.treatment_actions?.length ?? 0) > 0;
  const composedTitle = composeTitle(f.cause, f.event, f.consequence);
  // Controls can only reduce a risk. A residual above inherent is refused by the server
  // unless an override reason is recorded by someone who can accept risk.
  const residualAbove = inhScore != null && resScore != null && resScore > inhScore;
  /** Label the options that, with the other residual axis as chosen, would exceed inherent. */
  const markAbove = (options: Option[], other: string): Option[] =>
    inhScore == null || other === ""
      ? options
      : options.map((o) =>
          Number(o.value) * Number(other) > inhScore ? { ...o, label: `${o.label} (above inherent)` } : o,
        );
  const alePreview =
    f.annual_loss_frequency === "" || f.single_loss_expectancy === ""
      ? null
      : Number(f.annual_loss_frequency) * Number(f.single_loss_expectancy);

  // --------------------------------------------------------------- tabs
  const generalTab = (
    <>
      {/* The risk statement first: cause → event → consequence is what makes two people
          describe the same risk the same way. The title is composed from it when blank. */}
      <div className="field-row">
        <Field label="Cause" help="What could make it happen.">
          <TextArea value={f.cause} onChange={(v) => set("cause", v)} rows={2} placeholder="Phishing emails harvest staff credentials" />
        </Field>
        <Field label="Event" help="What could happen — the risk itself.">
          <TextArea value={f.event} onChange={(v) => set("event", v)} rows={2} placeholder="Unauthorised access to customer accounts" />
        </Field>
        <Field label="Consequence" help="What it would lead to.">
          <TextArea value={f.consequence} onChange={(v) => set("consequence", v)} rows={2} placeholder="Customer losses and an SBP enforcement action" />
        </Field>
      </div>
      <Field
        label="Title"
        required={!f.event.trim()}
        help={f.title.trim() || !composedTitle ? "A short name for the risk." : `Leave blank to use: “${composedTitle}”`}
      >
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder={composedTitle || "Phishing leads to credential theft"} />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="Threat / vulnerability context and what could go wrong." />
      </Field>
      <div className="field-row">
        <Field label="Category" help="From the organisation's risk category list (Settings → Lookups).">
          <LookupSelect
            lookupKey="risk_category"
            value={f.category_id}
            onChange={(id) => set("category_id", id)}
            legacyText={editing?.category_id ? null : editing?.category}
            placeholder="Choose a category…"
            allowCreate
          />
        </Field>
        <Field label="Risk Owner" help="The person accountable for this risk.">
          <UserPicker
            value={f.owner_id}
            onChange={(id) => set("owner_id", id)}
            selected={editing?.owner_ref}
            placeholder="Unassigned — search people…"
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Risk type" help="The top cut of the taxonomy; the category above is the finer one.">
          <Select value={f.risk_type} onChange={(v) => set("risk_type", v)} options={RISK_TYPE} placeholder="Not classified" />
        </Field>
        <Field label="Velocity" help="How fast the impact is felt once the event happens.">
          <Select value={f.velocity} onChange={(v) => set("velocity", v)} options={VELOCITY} placeholder="Not assessed" />
        </Field>
        <Field label="Source" help="Where the risk was identified.">
          <Select value={f.source} onChange={(v) => set("source", v)} options={SOURCE} placeholder="Not recorded" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Identified on">
          <TextInput value={f.identified_date} onChange={(v) => set("identified_date", v)} type="date" />
        </Field>
        <Field label="Identified by" help="Defaults to you when left blank on a new risk.">
          <UserPicker
            value={f.identified_by_id}
            onChange={(id) => set("identified_by_id", id)}
            selected={editing?.identified_by_ref}
            placeholder="Search people…"
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status" help="Where the risk is in assessment and treatment. A draft may be saved unscored; any other status needs the inherent scores and an assessment rationale. Approval is separate: submit it for review from the risk's detail view.">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
      </div>
      {/* Phase 3 hierarchy: enterprise → category → scenario. The server checks the parent
          is live, above this risk and not below it. */}
      <div className="field-row">
        <Field
          label="Hierarchy level"
          help={f.level === "" && f.parent ? "Left blank, the risk sits one level below its parent." : "Level 1 risks are what the board reads; level 3 scenarios are what practitioners assess."}
        >
          <Select
            value={f.level}
            onChange={(v) => setF((p) => ({ ...p, level: v, parent: v === "1" ? null : p.parent }))}
            options={LEVEL_OPTIONS}
            placeholder="Not placed"
          />
        </Field>
        <Field
          label="Parent risk"
          help={f.level === "1" ? "An enterprise (level 1) risk sits at the top: it has no parent." : "A live risk at a higher level (a lower number)."}
        >
          <AsyncSelect
            search={parentSearch}
            value={f.parent?.id ?? null}
            selectedLabel={f.parent?.label}
            onChange={(id, opt) => set("parent", id ? { id, label: opt?.label ?? "" } : null)}
            placeholder={f.level === "1" ? "No parent at level 1" : "No parent — search risks…"}
            disabled={f.level === "1"}
          />
        </Field>
      </div>
    </>
  );

  const assessmentTab = (
    <>
      {/* The criteria the two numbers below are supposed to mean, on the same screen as
          the numbers. Collapsed by default so it does not push the form down, but one
          click away — an assessor comparing rung 3 against rung 4 should not have to
          leave the record to do it. */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
        <span className="muted" style={{ fontSize: 12.5 }}>
          Scoring on your {matrixSize}×{matrixSize} matrix — scores run 1 to {maxScore}.
        </span>
        <button type="button" className="btn secondary sm" onClick={() => setShowScale((v) => !v)}>
          {showScale ? "Hide scale" : "What do 1–" + matrixSize + " mean?"}
        </button>
      </div>

      {showScale && (
        <div className="card card-pad" style={{ marginBottom: 14 }}>
          {!scaleIsDefined && (
            <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
              Your organisation has not written its criteria yet, so these are generic
              placeholders. An administrator sets the real wording under{" "}
              <b>Risk Register → Appetite → Risk methodology</b>; that is what makes two
              assessors score the same risk the same way.
            </div>
          )}
          {/* auto-fit rather than 1fr 1fr: the criteria column holds a sentence, and at
              10 rungs in a modal two fixed columns squeeze it into a ribbon. */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
            {([["Likelihood", matrix?.likelihood_levels], ["Impact", matrix?.impact_levels]] as const).map(
              ([axis, levels]) => (
                <div key={axis}>
                  <div className="bt" style={{ marginBottom: 6 }}>{axis}</div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr><th style={{ width: 34 }}>#</th><th style={{ width: "34%" }}>Means</th><th>Criteria</th></tr>
                      </thead>
                      <tbody>
                        {(levels ?? []).map((l) => (
                          <tr key={`${axis}-${l.level}`}>
                            <td className="ref">{l.level}</td>
                            <td>{l.label || "—"}</td>
                            <td className="muted" style={{ fontSize: 12.5 }}>{l.definition || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ),
            )}
          </div>
        </div>
      )}

      <Field label="Inherent Risk" help={`Likelihood × Impact before any controls are considered (1–${matrixSize} scale).`}>
        <div className="field-row">
          <Select value={String(f.inherent_likelihood)} onChange={(v) => setScore("inherent_likelihood", v)} options={LIKELIHOOD} placeholder="Likelihood" />
          {inherentByDims ? (
            <div className="field" style={{ margin: 0 }}>
              <label>Impact</label>
              <div style={{ paddingTop: 4 }} title="Set by the dimension scores below">
                <Badge tone="neutral" plain>{f.inherent_impact}</Badge> <span className="muted" style={{ fontSize: 12 }}>from dimensions</span>
              </div>
            </div>
          ) : (
            <Select value={String(f.inherent_impact)} onChange={(v) => setScore("inherent_impact", v)} options={IMPACT} placeholder="Impact" />
          )}
          <div className="field" style={{ margin: 0 }}>
            <label>Score</label>
            <div style={{ paddingTop: 4 }}>
              {inhScore != null ? <Badge tone="neutral" plain>{inhScore}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
        {chosen(f.inherent_likelihood, f.inherent_impact)}
      </Field>
      <Field label="Residual Risk" help="Likelihood × Impact after controls. Leave blank until assessed. Controls can only reduce a risk, so residual should not exceed inherent.">
        <div className="field-row">
          <Select value={f.residual_likelihood} onChange={(v) => setScore("residual_likelihood", v)} options={markAbove(LIKELIHOOD, f.residual_impact)} placeholder="Likelihood" />
          {residualByDims ? (
            <div className="field" style={{ margin: 0 }}>
              <label>Impact</label>
              <div style={{ paddingTop: 4 }} title="Set by the dimension scores below">
                <Badge tone="neutral" plain>{f.residual_impact}</Badge> <span className="muted" style={{ fontSize: 12 }}>from dimensions</span>
              </div>
            </div>
          ) : (
            <Select value={f.residual_impact} onChange={(v) => setScore("residual_impact", v)} options={markAbove(IMPACT, f.residual_likelihood)} placeholder="Impact" />
          )}
          <div className="field" style={{ margin: 0 }}>
            <label>Score</label>
            <div style={{ paddingTop: 4 }}>
              {resScore != null ? <Badge tone={residualAbove ? "critical" : "neutral"} plain>{resScore}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
        {chosen(f.residual_likelihood, f.residual_impact)}
        {residualAbove && (
          <div role="alert" style={{ marginTop: 8, padding: "8px 10px", borderRadius: 6, background: "var(--red-bg)", color: "var(--red)", fontSize: 12.5, lineHeight: 1.5 }}>
            Residual {resScore} is higher than inherent {inhScore}. Residual cannot exceed inherent
            without an override reason. Lower the residual, or record why it is higher below.
          </div>
        )}
      </Field>
      {/* Impact by dimension: rows are the organisation's impact dimensions, columns the
          two assessments. Scoring any dimension sets that column's overall impact
          (the highest, or the average rounded up — Risk methodology). */}
      {dimensionRows.length > 0 && (
        <Field
          label="Impact by dimension"
          help={`Optional. Score the dimensions that apply; the overall impact is the ${settings?.impact_mode === "average" ? "average (rounded up)" : "highest"} of them. Leave a column blank to set its impact directly.`}
        >
          <div className="table-wrap">
            <table style={{ fontSize: 13 }}>
              <thead>
                <tr>
                  <th>Dimension</th>
                  {DIM_BASES.map((b) => <th key={b} style={{ width: 150, textTransform: "capitalize" }}>{b}</th>)}
                </tr>
              </thead>
              <tbody>
                {dimensionRows.map((d) => (
                  <tr key={d.id}>
                    <td>{d.label}</td>
                    {DIM_BASES.map((b) => (
                      <td key={b}>
                        <select
                          className="select" aria-label={`${d.label} ${b} impact`}
                          value={f.dims[`${b}:${d.id}`] ?? ""}
                          onChange={(e) => setDim(b, d.id, e.target.value)}
                        >
                          <option value="">—</option>
                          {IMPACT.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                      </td>
                    ))}
                  </tr>
                ))}
                <tr>
                  <td className="muted" style={{ fontWeight: 600 }}>Overall impact</td>
                  {DIM_BASES.map((b) => {
                    const v = dimImpact(f.dims, b);
                    return <td key={b}>{v != null ? <Badge tone="neutral" plain>{v}</Badge> : <span className="muted">set above</span>}</td>;
                  })}
                </tr>
              </tbody>
            </table>
          </div>
        </Field>
      )}

      <Field label="Target Risk" help="Where treatment should take the risk. Optional; it cannot be higher than the residual (or inherent) risk.">
        <div className="field-row">
          <Select value={f.target_likelihood} onChange={(v) => set("target_likelihood", v)} options={LIKELIHOOD} placeholder="Likelihood" />
          <Select value={f.target_impact} onChange={(v) => set("target_impact", v)} options={IMPACT} placeholder="Impact" />
          <div className="field" style={{ margin: 0 }}>
            <label>Score</label>
            <div style={{ paddingTop: 4 }}>
              {tgtScore != null ? <Badge tone={targetAbove ? "critical" : "neutral"} plain>{tgtScore}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
        {targetAbove && (
          <div role="alert" style={{ marginTop: 8, fontSize: 12.5, color: "var(--red)" }}>
            Target {tgtScore} is higher than the {resScore != null && tgtScore! > resScore ? `residual ${resScore}` : `inherent ${inhScore}`} — lower it.
          </div>
        )}
      </Field>

      <Field
        label="Assessment rationale"
        required={rationaleNeeded}
        help={
          editing?.last_assessed_at
            ? `Why the scores are what they are. Last assessed ${formatDateTime(editing.last_assessed_at)}${editing.last_assessed_by_ref ? ` by ${editing.last_assessed_by_ref.full_name || editing.last_assessed_by_ref.email}` : ""}.`
            : "Why the scores are what they are. Required whenever a score changes (a draft may keep provisional scores) and before the risk leaves draft."
        }
      >
        {rationaleNeeded && !rationaleFresh && (
          <div role="status" style={{ marginBottom: 6, padding: "6px 10px", borderRadius: 6, background: "var(--amber-bg)", fontSize: 12.5 }}>
            {scoresChanged && editing ? "The scores changed — say why they moved." : "Say why the risk scores this way."}
          </div>
        )}
        <TextArea
          value={f.assessment_rationale}
          onChange={(v) => set("assessment_rationale", v)}
          rows={3}
          placeholder="For example: two card-fraud losses this quarter and the 3-D Secure rollout slipped to Q1"
        />
      </Field>

      {residualAbove && (
        <Field
          label="Override reason"
          required
          help="Why the residual is higher than inherent. Only a user who can accept risk may record this; it is kept on the risk and in the audit trail."
        >
          <TextArea
            value={f.residual_override_reason}
            onChange={(v) => set("residual_override_reason", v)}
            rows={2}
            placeholder="For example: the compensating control was withdrawn on 1 Sep; exposure now exceeds the original assessment"
          />
        </Field>
      )}

      <Field label="Quantitative (FAIR)" help={`Annual Loss Expectancy = loss events / year × ${currency} per event. Optional.`}>
        <div className="field-row">
          <div className="field" style={{ margin: 0 }}>
            <label>Loss events / year (ALF)</label>
            <NumberInput value={f.annual_loss_frequency} onChange={(v) => set("annual_loss_frequency", v)} min={0} step={0.1} placeholder="0.5" />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>{currency} per event (SLE)</label>
            <NumberInput value={f.single_loss_expectancy} onChange={(v) => set("single_loss_expectancy", v)} min={0} step={1000} placeholder="200000" />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Exposure (ALE)</label>
            <div style={{ paddingTop: 4 }}>
              {alePreview != null ? <Badge tone="info" plain>{money(alePreview)}</Badge> : <span className="muted">—</span>}
            </div>
          </div>
        </div>
      </Field>

      <div className="field-row">
        <Field label="Treatment Strategy">
          <Select value={f.treatment_strategy} onChange={(v) => set("treatment_strategy", v)} options={STRATEGY} placeholder="Not decided" />
        </Field>
        <Field label="Treatment Owner" help="The person responsible for carrying out the treatment plan.">
          <UserPicker
            value={f.treatment_owner_id}
            onChange={(id) => set("treatment_owner_id", id)}
            selected={editing?.treatment_owner_ref}
            legacyText={editing?.treatment_owner_id ? null : editing?.treatment_owner}
            placeholder="Search people…"
          />
        </Field>
      </div>
      <div className="field-row">
        <Field
          label="Treatment Deadline"
          help={hasActions ? "Follows the treatment actions (the latest open action's due date) — change an action's due date in the risk's detail view." : "Once the plan has actions, this follows them."}
        >
          {hasActions ? (
            <div style={{ paddingTop: 4 }}>{formatDate(editing?.treatment_deadline ?? null)}</div>
          ) : (
            <TextInput value={f.treatment_deadline} onChange={(v) => set("treatment_deadline", v)} type="date" />
          )}
        </Field>
        <Field label={`Treatment Cost (${currency})`}>
          <NumberInput value={f.treatment_cost} onChange={(v) => set("treatment_cost", v)} min={0} step={1000} placeholder="50000" />
        </Field>
      </div>
      <Field label="Treatment Plan" help="The plan's summary. Owned, dated actions are added from the risk's detail view.">
        <RichText value={f.treatment_description} onChange={(v) => set("treatment_description", v)} placeholder="Summarise the treatment plan…" />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field
        label="Business units"
        help="The segments this risk sits in — a workshop scopes to one of these, and the register can be filtered by it."
      >
        <AsyncMultiSelect search={linkSearch("business-units")} value={f.business_unit_ids} onChange={(v) => set("business_unit_ids", v)} />
      </Field>
      <Field label="Processes" help="Business processes this risk affects, where the exposure is narrower than a whole unit.">
        <AsyncMultiSelect search={linkSearch("processes")} value={f.process_ids} onChange={(v) => set("process_ids", v)} />
      </Field>
      <Field label="Assets" help="Assets exposed to or affected by this risk.">
        <AsyncMultiSelect search={linkSearch("assets")} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
      </Field>
      <Field label="Controls" help="Controls that mitigate this risk (reduce residual likelihood/impact).">
        <AsyncMultiSelect search={linkSearch("controls")} value={f.control_ids} onChange={(v) => set("control_ids", v)} />
      </Field>
      <Field label="Threats" help="Threats from the catalog that could trigger this risk.">
        <AsyncMultiSelect search={linkSearch("threats")} value={f.threat_ids} onChange={(v) => set("threat_ids", v)} />
      </Field>
      <Field label="Vulnerabilities" help="Weaknesses a threat could exploit.">
        <AsyncMultiSelect search={linkSearch("vulnerabilities")} value={f.vulnerability_ids} onChange={(v) => set("vulnerability_ids", v)} />
      </Field>
      <Field label="Policies" help="Policies that govern or address this risk.">
        <AsyncMultiSelect search={linkSearch("policies")} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} />
      </Field>
      <Field label="Incidents" help="Incidents that materialised from this risk.">
        <AsyncMultiSelect search={linkSearch("incidents")} value={f.incident_ids} onChange={(v) => set("incident_ids", v)} />
      </Field>
    </>
  );

  const reviewTab = (
    <>
      <Field label="Review Frequency" help="How often this risk should be re-assessed. The next review date is scheduled automatically.">
        <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
      </Field>
      {editing && (
        <div className="field-row">
          <Field label="Last Review">
            <TextInput value={formatDate(editing.last_review_date)} onChange={() => {}} />
          </Field>
          <Field label="Next Review">
            <TextInput value={formatDate(editing.next_review_date)} onChange={() => {}} />
          </Field>
          <Field label="Expired Reviews">
            <TextInput value={String(editing.expired_reviews)} onChange={() => {}} />
          </Field>
        </div>
      )}
      {editing && (
        <p className="muted" style={{ fontSize: 13 }}>
          Review dates are managed by the register. Use the dedicated review action to mark this risk reviewed and reschedule.
        </p>
      )}
    </>
  );

  /* Inline relation chips. Each links to the record's own page, the same way the
     drawer's related-record chips do — the list is the workbench, so the graph has to
     be walkable from it. */
  const linkChips = (items: Ref[] | undefined, href: string) =>
    items && items.length ? (
      <div className="chips" onClick={(e) => e.stopPropagation()}>
        {items.map((x) => (
          <Link key={x.id} className="chip" href={`${href}?id=${x.id}`}>{x.name || x.title || x.reference || x.id}</Link>
        ))}
      </div>
    ) : <span className="muted">—</span>;
  const names = (items: Ref[] | undefined) => (items ?? []).map((x) => x.name || x.title || x.reference || "").join(", ");
  const rungLabel = (axis: "likelihood" | "impact", n: number | null) => {
    if (!n) return "—";
    const lvl = (axis === "likelihood" ? matrix?.likelihood_levels : matrix?.impact_levels)?.find((l) => l.level === n);
    return lvl?.label ? `${n} — ${lvl.label}` : String(n);
  };
  const classification = (l: number | null, i: number | null) =>
    l && i ? (
      <div className="chips">
        <span className="chip" title="Likelihood">L {rungLabel("likelihood", l)}</span>
        <span className="chip" title="Impact">I {rungLabel("impact", i)}</span>
      </div>
    ) : <span className="muted">—</span>;
  const scoreCell = (sev: string | null, score: number | null) => (
    <><Severity value={sev} /> <span className="muted">({score ?? "—"})</span></>
  );

  /* The full catalogue. What is shown by default is the working set a risk manager
     scans; everything else is one click away in the column chooser, and the layout
     is remembered per person. */
  const riskColumns: Column<RiskRow>[] = [
    { key: "reference", header: "Ref", sortable: true, locked: true, render: (r) => <span className="ref">{r.reference}</span> },
    { key: "title", header: "Title", sortable: true, locked: true, render: (r) => <span className="cell-title">{r.title}</span> },
    { key: "category", header: "Category", sortable: true, render: (r) => <span className="muted">{categoryText(r) || "—"}</span>, text: (r) => categoryText(r) },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge>, text: (r) => cap(r.status) },
    { key: "level", header: "Level", sortable: true, render: (r) => <LevelBadge level={r.level} />, text: (r) => (r.level ? `L${r.level} ${LEVEL_LABEL[r.level]}` : "") },
    { key: "parent", header: "Parent", hidden: true, render: (r) => (r.parent ? <button type="button" className="chip" title={r.parent.title} onClick={(e) => { e.stopPropagation(); setRecordId(r.parent!.id); }}>{r.parent.reference}</button> : <span className="muted">—</span>), text: (r) => r.parent?.reference ?? "" },
    { key: "children_count", header: "Below", hidden: true, render: (r) => (r.children_count ? <button type="button" className="linklike" title="List the risks directly below" onClick={(e) => { e.stopPropagation(); setUrlFilter("parent_id", r.id); }}>{r.children_count}</button> : <span className="muted">—</span>), text: (r) => (r.children_count ? String(r.children_count) : "") },
    { key: "owner", header: "Owner", render: (r) => <span className="muted"><UserName user={r.owner_ref} /></span>, text: (r) => personText(r.owner_ref) },
    { key: "business_units", header: "Business units", render: (r) => linkChips(r.business_units, "/business-units"), text: (r) => names(r.business_units) },
    { key: "processes", header: "Processes", hidden: true, render: (r) => linkChips(r.processes, "/processes"), text: (r) => names(r.processes) },
    { key: "assets", header: "Assets", render: (r) => linkChips(r.assets, "/information-assets"), text: (r) => names(r.assets) },
    { key: "controls", header: "Controls", render: (r) => linkChips(r.controls, "/controls"), text: (r) => names(r.controls) },
    { key: "policies", header: "Policies", hidden: true, render: (r) => linkChips(r.policies, "/policies"), text: (r) => names(r.policies) },
    { key: "threats", header: "Threats", hidden: true, render: (r) => linkChips(r.threats, "/threat-library"), text: (r) => names(r.threats) },
    { key: "vulnerabilities", header: "Vulnerabilities", hidden: true, render: (r) => linkChips(r.vulnerabilities, "/threat-library"), text: (r) => names(r.vulnerabilities) },
    { key: "incidents", header: "Incidents", hidden: true, render: (r) => linkChips(r.incidents, "/incidents"), text: (r) => names(r.incidents) },
    { key: "inherent_classification", header: "Inherent classification", hidden: true, render: (r) => classification(r.inherent_likelihood, r.inherent_impact), text: (r) => `L${r.inherent_likelihood} I${r.inherent_impact}` },
    { key: "inherent_score", header: "Inherent", sortable: true, render: (r) => scoreCell(r.inherent_severity, r.inherent_score), text: (r) => `${r.inherent_score ?? ""} ${r.inherent_severity ?? ""}`.trim() },
    { key: "residual_classification", header: "Residual classification", hidden: true, render: (r) => classification(r.residual_likelihood, r.residual_impact), text: (r) => r.residual_likelihood ? `L${r.residual_likelihood} I${r.residual_impact}` : "" },
    { key: "residual_score", header: "Residual", sortable: true, render: (r) => scoreCell(r.residual_severity, r.residual_score), text: (r) => `${r.residual_score ?? ""} ${r.residual_severity ?? ""}`.trim() },
    { key: "target_score", header: "Target", hidden: true, sortable: true, render: (r) => (r.target_score ? scoreCell(r.target_severity ?? null, r.target_score) : <span className="muted">—</span>), text: (r) => (r.target_score ? `${r.target_score} ${r.target_severity ?? ""}`.trim() : "") },
    { key: "appetite", header: "Appetite", render: (r) => { const a = appetite(r, settings); return a ? <span title={a.title}><Badge tone={a.tone}>{a.label}</Badge></span> : <span className="muted">—</span>; }, text: (r) => appetite(r, settings)?.label ?? "" },
    { key: "risk_type", header: "Type", hidden: true, sortable: true, render: (r) => <span className="muted">{r.risk_type ? cap(r.risk_type) : "—"}</span>, text: (r) => (r.risk_type ? cap(r.risk_type) : "") },
    { key: "velocity", header: "Velocity", hidden: true, render: (r) => <span className="muted">{velocityLabel(r.velocity) || "—"}</span>, text: (r) => velocityLabel(r.velocity) },
    { key: "source", header: "Source", hidden: true, sortable: true, render: (r) => <span className="muted">{sourceLabel(r.source) || "—"}</span>, text: (r) => sourceLabel(r.source) },
    { key: "treatment_progress", header: "Treatment actions", hidden: true, render: (r) => (r.treatment_progress?.total ? <span className="muted">{r.treatment_progress.done}/{r.treatment_progress.total}{r.treatment_progress.overdue ? <span style={{ color: "var(--red)" }}> · {r.treatment_progress.overdue} overdue</span> : null}</span> : <span className="muted">—</span>), text: (r) => (r.treatment_progress?.total ? `${r.treatment_progress.done}/${r.treatment_progress.total}` : "") },
    { key: "control_health", header: "Control health", render: (r) => controlHealth(r.control_health), text: (r) => r.control_health ?? "" },
    { key: "needs_review", header: "Review flag", render: (r) => (r.needs_review ? <span title={reviewReasons(r).join("\n")}><Badge tone="high">Needs review</Badge></span> : <span className="muted">—</span>), text: (r) => (r.needs_review ? `Needs review: ${reviewReasons(r).join("; ")}` : "") },
    { key: "treatment_strategy", header: "Treatment", hidden: true, render: (r) => <span className="muted">{r.treatment_strategy ? cap(r.treatment_strategy) : "—"}</span>, text: (r) => r.treatment_strategy ? cap(r.treatment_strategy) : "" },
    { key: "treatment_owner", header: "Treatment owner", hidden: true, render: (r) => <span className="muted"><UserName user={r.treatment_owner_ref} fallback={r.treatment_owner} /></span>, text: (r) => personText(r.treatment_owner_ref, r.treatment_owner) },
    { key: "treatment_deadline", header: "Treatment deadline", hidden: true, sortable: true, render: (r) => <span className="muted">{formatDate(r.treatment_deadline)}</span>, text: (r) => (r.treatment_deadline ? formatDate(r.treatment_deadline) : "") },
    { key: "exposure", header: "Exposure", render: (r) => <span className="muted">{money(r.annual_loss_expectancy)}</span>, text: (r) => money(r.annual_loss_expectancy) },
    { key: "workflow_status", header: "Approval", hidden: true, render: (r) => <span className="muted">{workflowLabel(r.workflow_status)}</span>, text: (r) => workflowLabel(r.workflow_status) },
    { key: "review_frequency", header: "Review cycle", hidden: true, render: (r) => <span className="muted">{cap(r.review_frequency)}</span>, text: (r) => cap(r.review_frequency) },
    { key: "last_review_date", header: "Last review", hidden: true, render: (r) => <span className="muted">{formatDate(r.last_review_date)}</span>, text: (r) => (r.last_review_date ? formatDate(r.last_review_date) : "") },
    { key: "next_review_date", header: "Review", sortable: true, render: (r) => (isOverdue(r.next_review_date) ? <Badge tone="high">Overdue</Badge> : <span className="muted">{formatDate(r.next_review_date)}</span>), text: (r) => (r.next_review_date ? formatDate(r.next_review_date) : "") },
    { key: "created_at", header: "Created", hidden: true, render: (r) => <span className="muted">{formatDate(r.created_at)}</span>, text: (r) => (r.created_at ? formatDate(r.created_at) : "") },
    { key: "updated_at", header: "Updated", hidden: true, render: (r) => <span className="muted">{formatDate(r.updated_at)}</span>, text: (r) => (r.updated_at ? formatDate(r.updated_at) : "") },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(r)}>Delete</button></div> },
  ];

  /** Delete every selected risk after one confirmation, then drop the selection. */
  async function removeMany(rowsToDelete: RiskRow[], clear: () => void) {
    const ok = await confirmDialog({
      title: `Delete ${rowsToDelete.length} risk${rowsToDelete.length === 1 ? "" : "s"}?`,
      message: "They are archived, not destroyed: links from other records are kept, they can be restored from Archived, and the activity trail records who removed them.",
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    const res = await deleteEach(rowsToDelete, (r) => apiCall("DELETE", `/risks/${r.id}`));
    clear();
    reload();
    toastDeleteSummary(res, "risk");
  }

  /** A saved view restoring its filters into the page's own scope state. */
  const applyScope = (f: Record<string, string | number | boolean | undefined>) => {
    urlFilters.replace(f);
    const unitId = typeof f.business_unit_id === "string" ? f.business_unit_id : "";
    setScopeUnit(unitId ? { id: unitId, name: "" } : null);
    if (unitId) {
      cachedBusinessUnits()
        .then((all) => { const u = all.find((x) => x.id === unitId); if (u) setScopeUnit({ id: u.id, name: u.name }); })
        .catch(() => {});
    }
    const processId = typeof f.process_id === "string" ? f.process_id : "";
    setScopeProcess(processId ? { id: processId, name: "" } : null);
    if (processId) {
      pickProcesses({ ids: [processId] })
        .then((rows) => { if (rows[0]) setScopeProcess({ id: rows[0].id, name: rows[0].name }); })
        .catch(() => {});
    }
    setScopeStatus(typeof f.status === "string" ? f.status : "");
    setScopeReview(typeof f.needs_review === "string" ? f.needs_review : typeof f.needs_review === "boolean" ? String(f.needs_review) : "");
    const assetId = typeof f.asset_id === "string" ? f.asset_id : "";
    if (!assetId) { setScopeAsset(null); return; }
    setScopeAsset({ id: assetId, name: "" });
    apiCall<{ id: string; name: string }>("GET", `/assets/${assetId}`)
      .then((a) => setScopeAsset({ id: a.id, name: a.name })).catch(() => {});
  };

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Risk Register</h1>
          <p>Qualitative ({matrixSize}×{matrixSize}) and quantitative (FAIR) risks, with controls, threats and review cycles.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div className="seg" role="tablist" aria-label="Register view">
            <button className={!treeView ? "on" : ""} onClick={() => setUrlFilter("view", "")} role="tab" aria-selected={!treeView}>List</button>
            <button className={treeView ? "on" : ""} onClick={() => setUrlFilter("view", "tree")} role="tab" aria-selected={treeView}>Hierarchy</button>
          </div>
          <Menu
            label="Export"
            items={[
              {
                label: "Register PDF",
                hint: scopeLabel === "Whole register" ? "Every risk, with detail pages" : scopeLabel,
                onClick: () =>
                  api.pdfRiskRegister(scopeFilters, scopeLabel === "Whole register" ? undefined : scopeLabel).catch(() => {}),
              },
              { label: "Export CSV", hint: "All risks, every column", onClick: () => io.current?.exportCsv() },
            ]}
          />
          <Menu
            label="More"
            items={[
              { label: "Import risks…", hint: "From your existing register — CSV or Excel", onClick: () => io.current?.openImport() },
              { label: "Download import template", onClick: () => io.current?.template() },
              "divider",
              /* The answer to "one control applies to four assets — shouldn't each get its
                 own rating?": one proposed risk per asset, impact from that asset's own
                 criticality, rather than one rating stretched across four assets. */
              { label: "Generate risks from assets…", hint: "Proposals go to the risk candidates queue, not the register", onClick: () => gen.current?.open() },
              { label: "Risk candidates…", hint: "Accept, merge or reject generated risks", onClick: () => router.push("/risk-proposals") },
              { label: "Review risks with no live links…", hint: "Risks whose assets were deleted and that link to nothing else", onClick: () => orphans.current?.open() },
              "divider",
              {
                label: "Risk methodology…",
                hint: settings ? `Appetite ≤ ${settings.appetite_score} · tolerance ≤ ${settings.tolerance_score} · ${matrixSize}×${matrixSize} matrix` : undefined,
                onClick: () => setShowSettings(true),
              },
            ]}
          />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} />
            Add risk
          </button>
        </div>
      </div>

      {/* Dialogs driven from the menus above; they render nothing until opened. */}
      <ImportExport ref={io} resource="risks" label="Risks" onDone={reload} hideButtons />
      <GenerateRisks ref={gen} label="the asset inventory" onDone={reload} hideButton />
      <OrphanCleanup ref={orphans} onDone={reload} hideButton />

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {treeView ? (
        <RiskHierarchyTree
          onOpen={(id) => setRecordId(id)}
          onShowUnplaced={() => urlFilters.update({ view: undefined, level: "none" })}
          refreshKey={refreshKey}
        />
      ) : (
      <DataTable<RiskRow>
        toolbarLeft={
          /* The segment scope. Sits beside the search box rather than in a card of its
             own: it narrows the whole page — counts and the export included — but it
             does not need its own hundred and fifty pixels to say so. */
          <div className="toolbar-filters">
            <div style={{ width: 200 }}>
              <BusinessUnitSelect
                value={scopeUnit?.id ?? null}
                onChange={(id, u) => setScopeUnit(id ? { id, name: u?.name ?? "" } : null)}
                placeholder="All business units"
              />
            </div>
            <div style={{ width: 180 }}>
              <ProcessSelect
                value={scopeProcess?.id ?? null}
                businessUnitId={scopeUnit?.id}
                onChange={(id, p) => setScopeProcess(id ? { id, name: p?.name ?? "" } : null)}
                placeholder="All processes"
              />
            </div>
            <div style={{ width: 180 }}>
              <AsyncSelect
                search={linkSearch("assets")}
                value={scopeAsset?.id ?? null}
                selectedLabel={scopeAsset?.name}
                onChange={(id, opt) => setScopeAsset(id ? { id, name: opt?.label ?? "" } : null)}
                placeholder="All assets"
              />
            </div>
            <div style={{ width: 150 }}>
              <Select value={scopeStatus} onChange={setScopeStatus} options={STATUS} placeholder="Any status" />
            </div>
            <div style={{ width: 160 }}>
              <Select value={scopeReview} onChange={setScopeReview} options={REVIEW_FILTER} placeholder="Any review flag" />
            </div>
            <div style={{ width: 140 }}>
              <Select value={u.level ?? ""} onChange={(v) => setUrlFilter("level", v)} options={LEVEL_FILTER} placeholder="Any level" />
            </div>
            <div style={{ width: 175 }}>
              <Select value={u.review ?? ""} onChange={(v) => setUrlFilter("review", v)} options={DUE_FILTER} placeholder="Any review date" />
            </div>
            <div style={{ width: 160 }}>
              <Select value={u.appetite ?? ""} onChange={(v) => setUrlFilter("appetite", v)} options={APPETITE_FILTER} placeholder="Any appetite" />
            </div>
            <div style={{ width: 145 }}>
              <Select value={u.has_controls ?? ""} onChange={(v) => setUrlFilter("has_controls", v)} options={CONTROLS_FILTER} placeholder="Any controls" />
            </div>
            <div style={{ width: 165 }}>
              <Select value={u.treatment_overdue ?? ""} onChange={(v) => setUrlFilter("treatment_overdue", v)} options={TREATMENT_FILTER} placeholder="Any treatment" />
            </div>
            {u.parent_id && (
              <span className="chip">
                Directly below {parentFilterLabel || "…"}
                <button className="chip-x" onClick={() => setUrlFilter("parent_id", "")} aria-label="Show risks at every place in the hierarchy">✕</button>
              </span>
            )}
            {u.roots_only && (
              <span className="chip">
                Top of the hierarchy only
                <button className="chip-x" onClick={() => setUrlFilter("roots_only", "")} aria-label="Show every risk">✕</button>
              </span>
            )}
            {(scopeUnit || scopeProcess || scopeAsset || scopeStatus || scopeReview || urlFiltered) && (
              <button className="btn secondary sm" onClick={() => { setScopeUnit(null); setScopeProcess(null); setScopeAsset(null); setScopeStatus(""); setScopeReview(""); clearUrlFilters(); }}>
                Clear
              </button>
            )}
          </div>
        }
        tabsRight={
          settings && (
            <span className="appetite-chip">
              <span>{scopeLabel}</span>
              <span>·</span>
              <span>
                Appetite ≤ <b style={{ color: "var(--green)" }}>{settings.appetite_score}</b>
                {" "}· Tolerance ≤ <b style={{ color: "var(--amber)" }}>{settings.tolerance_score}</b>
              </span>
              <button className="linklike" onClick={() => setShowSettings(true)}>Methodology</button>
            </span>
          )
        }
        toolbarRight={<ArchivedRecords entityType="risk" noun="risks" onRestored={reload} refreshKey={refreshKey} />}
        tableKey="risks"
        statusModel="risk"
        columns={riskColumns}
        fetcher={fetchRisks}
        filters={tableFilters}
        onApplyFilters={applyScope}
        bulkActions={(rows, clear) => (
          <>
            <BulkEditBar entityType="risk" rows={rows} onDone={() => { clear(); reload(); }} />
            <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
          </>
        )}
        rowKey={(r) => r.id}
        onRowClick={(r) => setRecordId(r.id)}
        activeKey={recordId ?? undefined}
        searchPlaceholder="Search risks by title or reference…"
        defaultSort={{ by: "inherent_score", dir: "desc" }}
        emptyMessage="No risks yet. Create your first risk to start building the register."
        refreshKey={refreshKey}
      />
      )}

      {/* Appetite, tolerance and the matrix — the organisation's methodology. A side
          panel rather than a card above the register: it is edited once a year and
          read every day, and reading it should cost one line, not a hundred pixels. */}
      <RecordDrawer
        open={showSettings}
        onClose={() => setShowSettings(false)}
        layout="panel"
        width={780}
        title="Risk methodology"
        subtitle={`${matrixSize}×${matrixSize} matrix · scores 1–${maxScore} · score above tolerance is a breach`}
      >
        <form onSubmit={saveSettings} style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ width: 190 }}>
            <label className="label">Appetite (1–{maxScore})</label>
            <input className="input" type="number" min={1} max={maxScore} value={appetiteScore} onChange={(e) => setAppetiteScore(Number(e.target.value))} />
          </div>
          <div style={{ width: 190 }}>
            <label className="label">Tolerance (1–{maxScore})</label>
            <input className="input" type="number" min={1} max={maxScore} value={toleranceScore} onChange={(e) => setToleranceScore(Number(e.target.value))} />
          </div>
          <button className="btn">Save thresholds</button>
        </form>
        <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 16 }}>
          <RiskMethodology
            onSaved={() => {
              reload();
              api.riskSettings().then(setSettings).catch(() => {});
              api.riskMatrixConfig().then(setMatrix).catch(() => {});
            }}
          />
        </div>
      </RecordDrawer>

      {/* Read-only detail view (?id=) — click a row to see everything; Edit is separate. */}
      <RecordDrawer
        aside={detail ? <RecordPanels model="risk" entityId={detail.id} /> : null}
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? cap(detail.status) + (categoryText(detail) ? ` · ${categoryText(detail)}` : "") : ""}
        width={680}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            {detail.needs_review && (
              <div role="status" style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: "10px 14px", borderRadius: 8, marginBottom: 16, background: "var(--amber-bg)", border: "1px solid var(--border)" }}>
                <Badge tone="high">Needs review</Badge>
                <div style={{ flex: 1, fontSize: 13, lineHeight: 1.5 }}>
                  {reviewReasons(detail).length
                    ? reviewReasons(detail).map((line, i) => <div key={i}>{line}</div>)
                    : <span className="muted">Something this risk depended on changed.</span>}
                </div>
                <button className="btn secondary sm" onClick={() => markReviewed(detail)}>Mark reviewed</button>
              </div>
            )}
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "flex-end", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Inherent</div><div style={{ marginTop: 4 }}><Severity value={detail.inherent_severity} /> <span className="muted">({detail.inherent_score ?? "—"})</span></div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Residual</div><div style={{ marginTop: 4 }}><Severity value={detail.residual_severity} /> <span className="muted">({detail.residual_score ?? "—"})</span></div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Target</div><div style={{ marginTop: 4 }}>{detail.target_score ? <><Severity value={detail.target_severity ?? null} /> <span className="muted">({detail.target_score})</span></> : <span className="muted">Not set</span>}</div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Appetite</div><div style={{ marginTop: 4 }}>{(() => { const a = appetite(detail, settings); return a ? <span title={a.title}><Badge tone={a.tone}>{a.label}</Badge></span> : <span className="muted">—</span>; })()}</div>{detail.tolerance_score != null && <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{detail.appetite_category_id ? "Category" : "Organisation"}: {detail.appetite_score} · {detail.tolerance_score}</div>}</div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Control health</div><div style={{ marginTop: 4 }}>{controlHealth(detail.control_health)}</div></div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}><div className="muted" style={{ fontSize: 12 }}>Exposure (ALE)</div><div style={{ marginTop: 4 }}>{money(detail.annual_loss_expectancy)}</div></div>
            </div>

            {/* Phase 3: where the risk sits — its parent, and everything below it. */}
            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <strong style={{ fontSize: 13 }}>Hierarchy</strong>
                <LevelBadge level={detail.level} />
                {detail.parent ? (
                  <span style={{ fontSize: 13 }}>
                    under{" "}
                    <button type="button" className="chip" title={detail.parent.title} onClick={() => setRecordId(detail.parent!.id)}>
                      {detail.parent.reference}
                    </button>{" "}
                    <span className="muted">{detail.parent.title}</span>
                  </span>
                ) : (
                  <span className="muted" style={{ fontSize: 13 }}>{detail.parent_id ? "Its parent was archived" : "No parent"}</span>
                )}
              </div>
              {rollup && rollup.total > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                    Directly below ({rollup.children.length})
                  </div>
                  <div className="chips">
                    {rollup.children.map((c) => (
                      <button key={c.id} type="button" className="chip" title={c.title} onClick={() => setRecordId(c.id)}>
                        {c.reference} <Severity value={c.severity} />
                      </button>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center", marginTop: 10, fontSize: 12.5 }}>
                    <span>{rollup.total} below in all</span>
                    {rollup.worst_exposure && (
                      <span>
                        worst exposure{" "}
                        <button type="button" className="linklike" onClick={() => setRecordId(rollup.worst_exposure!.id)}>{rollup.worst_exposure.reference}</button>{" "}
                        <Severity value={rollup.worst_exposure.severity} /> <span className="muted">({rollup.worst_exposure.exposure ?? "—"})</span>
                      </span>
                    )}
                    {rollup.worst_residual && (
                      <span>
                        worst residual{" "}
                        <button type="button" className="linklike" onClick={() => setRecordId(rollup.worst_residual!.id)}>{rollup.worst_residual.reference}</button>{" "}
                        <span className="muted">({rollup.worst_residual.residual_score})</span>
                      </span>
                    )}
                    <span className="muted">
                      {(["critical", "high", "medium", "low"] as const).map((b) => `${rollup.by_severity[b] ?? 0} ${b}`).join(" · ")}
                    </span>
                    {rollup.breaches > 0 && <Badge tone="critical">{rollup.breaches} above tolerance</Badge>}
                    <button type="button" className="linklike" onClick={() => showBelow(detail.id)}>List the risks directly below</button>
                  </div>
                </div>
              )}
            </div>

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <strong style={{ fontSize: 13, display: "block", marginBottom: 10 }}>Approval</strong>
              <WorkflowFields entityType="risk" entityId={detail.id} onChanged={() => { reload(); loadDetail(detail.id); }} />
            </div>

            <WorkflowStrip
              entityType="risk"
              entityId={detail.id}
              entityLabel={`${detail.reference} — ${detail.title}`}
              link="/risks"
              ownerEmail={detail.owner_ref?.email ?? ""}
              hideStart
              onChange={() => { reload(); loadDetail(detail.id); }}
            />

            <ResidualSuggestion
              riskId={detail.id}
              onAccepted={() => { reload(); loadDetail(detail.id); }}
            />

            <RiskAcceptancePanel
              riskId={detail.id}
              riskReference={detail.reference}
              acceptances={detail.acceptances ?? []}
              onChange={() => { reload(); loadDetail(detail.id); }}
            />

            {(detail.cause || detail.event || detail.consequence) && (
              <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16, display: "grid", gap: 8 }}>
                <strong style={{ fontSize: 13 }}>Risk statement</strong>
                {([["Cause", detail.cause], ["Event", detail.event], ["Consequence", detail.consequence]] as const).map(([label, text]) =>
                  text ? (
                    <div key={label} style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 8, fontSize: 13.5, lineHeight: 1.5 }}>
                      <span className="muted" style={{ fontWeight: 600, fontSize: 12 }}>{label}</span>
                      <span>{text}</span>
                    </div>
                  ) : null,
                )}
              </div>
            )}

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              {field("Owner", <UserName user={detail.owner_ref} />)}
              {field("Category", categoryText(detail) || "—")}
              {field("Status", <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>)}
              {field("Type", detail.risk_type ? cap(detail.risk_type) : "—")}
              {field("Velocity", velocityLabel(detail.velocity) || "—")}
              {field("Source", sourceLabel(detail.source) || "—")}
              {field("Identified", detail.identified_date || detail.identified_by_ref
                ? <>{detail.identified_date ? formatDate(detail.identified_date) : ""}{detail.identified_by_ref ? <> {detail.identified_date ? "· " : ""}<UserName user={detail.identified_by_ref} /></> : null}</>
                : "—")}
            </div>

            {(detail.assessment_rationale || detail.last_assessed_at) && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
                  Assessment rationale
                  {detail.last_assessed_at && <> · assessed {formatDateTime(detail.last_assessed_at)}{detail.last_assessed_by_ref ? <> by <UserName user={detail.last_assessed_by_ref} /></> : null}</>}
                </div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }}>{detail.assessment_rationale || <span className="muted">No rationale recorded (provisional draft scores).</span>}</div>
              </div>
            )}

            {(detail.impact_dimensions?.length ?? 0) > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Impact by dimension</div>
                <div className="table-wrap">
                  <table style={{ fontSize: 13 }}>
                    <thead><tr><th>Dimension</th>{DIM_BASES.map((b) => <th key={b} style={{ width: 110, textTransform: "capitalize" }}>{b}</th>)}</tr></thead>
                    <tbody>
                      {Array.from(new Map((detail.impact_dimensions ?? []).map((d) => [d.dimension_id, d.dimension_ref?.label ?? "Dimension"])).entries()).map(([id, label]) => (
                        <tr key={id}>
                          <td>{label}</td>
                          {DIM_BASES.map((b) => {
                            const hit = detail.impact_dimensions?.find((d) => d.dimension_id === id && d.basis === b);
                            return <td key={b}>{hit ? rungLabel("impact", hit.score) : <span className="muted">—</span>}</td>;
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {detail.description && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description</div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }}>{detail.description}</div>
              </div>
            )}

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <strong style={{ fontSize: 13 }}>Treatment</strong>
              <div style={{ display: "flex", gap: 22, flexWrap: "wrap", margin: "10px 0" }}>
                {field("Strategy", detail.treatment_strategy ? cap(detail.treatment_strategy) : "—")}
                {field("Owner", <UserName user={detail.treatment_owner_ref} fallback={detail.treatment_owner} />)}
                {field(detail.treatment_actions?.length ? "Deadline (from actions)" : "Deadline", formatDate(detail.treatment_deadline))}
                {field("Cost", money(detail.treatment_cost))}
              </div>
              {detail.treatment_description && (
                <div style={{ fontSize: 13.5, lineHeight: 1.5 }} dangerouslySetInnerHTML={{ __html: detail.treatment_description }} />
              )}
              <RiskTreatmentActions
                riskId={detail.id}
                actions={detail.treatment_actions ?? []}
                progress={detail.treatment_progress}
                onChange={() => { reload(); loadDetail(detail.id); }}
              />
            </div>

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 18 }}>
              {field("Review frequency", cap(detail.review_frequency))}
              {field("Last review", formatDate(detail.last_review_date))}
              {field("Next review", isOverdue(detail.next_review_date) ? <Badge tone="high">Overdue · {formatDate(detail.next_review_date)}</Badge> : formatDate(detail.next_review_date))}
              {field("Expired reviews", String(detail.expired_reviews))}
            </div>

            <strong style={{ fontSize: 13 }}>Related records</strong>
            <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 8 }}>
              <RelatedChips label="Business units" items={detail.business_units} href="/business-units" />
              <RelatedChips label="Processes" items={detail.processes} href="/processes" />
              <RelatedChips label="Assets" items={detail.assets} href="/information-assets" />
              <RelatedChips label="Controls" items={detail.controls} href="/controls" />
              <RelatedChips label="Threats" items={detail.threats} href="/threat-library" />
              <RelatedChips label="Vulnerabilities" items={detail.vulnerabilities} href="/threat-library" />
              <RelatedChips label="Policies" items={detail.policies} href="/policies" />
              <RelatedChips label="Incidents" items={detail.incidents} href="/incidents" />
              <RelatedChips label="Compliance requirements" items={detail.requirements} href="/compliance" />
              <RelatedChips label="Exceptions" items={detail.exceptions} href="/exceptions" />
              <RelatedChips label="Third parties" items={detail.vendors} href="/vendors" />
              <RelatedChips label="Projects" items={detail.projects} href="/projects" />
              <RelatedChips label="Goals" items={detail.goals} href="/goals" />
              <RelatedChips label="Processing activities" items={detail.processing_activities} href="/privacy" />
              <RelatedChips label="Audit findings" items={detail.audit_findings} href="/internal-audit" />
              <RelatedChips label="Issues" items={detail.issues} href="/issues" />
            </div>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              <RecordIssues entityId={detail.id} entityRef={detail.reference} sourceType="risk_assessment" />
            </div>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            </div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit risk — ${editing.reference}` : "Add item (Risk Register)"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "assessment", label: "Assessment", content: assessmentTab },
            { id: "links", label: "Links & Relations", content: linksTab },
            { id: "review", label: "Review", content: reviewTab },
            ...(cfDefs.length
              ? [{
                  id: "custom",
                  label: "Custom fields",
                  required: cfDefs.some((d) => d.required),
                  content: (
                    <CustomFieldsEditor
                      fields={cfDefs}
                      values={cfValues}
                      onChange={(id, v) => setCfValues((p) => ({ ...p, [id]: v }))}
                    />
                  ),
                }]
              : []),
          ]}
          onClose={() => { setShowForm(false); setRecordId(null); }}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create risk"}
        />
      )}
    </>
  );
}

export default function RisksPageWrapper() {
  return (
    <Suspense fallback={null}>
      <RisksPage />
    </Suspense>
  );
}
