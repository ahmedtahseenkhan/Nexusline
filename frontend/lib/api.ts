const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const TOKEN_KEY = "nexusline_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

/** Turn a FastAPI/Pydantic error `detail` into a readable message.
 *  A 422 returns `detail` as an array of {loc, msg, type}; render it as
 *  "Title is required" / "Field: message" instead of raw JSON. */
function formatDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const cap = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
    const parts = detail
      .map((e) => {
        if (!e || typeof e !== "object") return "";
        const loc = Array.isArray((e as { loc?: unknown[] }).loc)
          ? (e as { loc: unknown[] }).loc.filter((p) => p !== "body" && p !== "query" && p !== "path")
          : [];
        const field = loc.length ? String(loc[loc.length - 1]) : "";
        const label = field ? cap(field) : "";
        const type = (e as { type?: string }).type || "";
        const msg = (e as { msg?: string }).msg || "invalid value";
        if (type === "missing" || type.startsWith("string_too_short")) return `${label || "This field"} is required`;
        return label ? `${label}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  return fallback;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = formatDetail(body.detail, res.statusText);
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Generic typed request helper for module pages that don't need bespoke client methods. */
export function apiCall<T>(
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  return request<T>(path, {
    method,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/** Upload a binary file via multipart/form-data (browser sets the boundary). */
export async function uploadMultipart<T>(path: string, file: File): Promise<T> {
  const token = getToken();
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const b = await res.json();
      message = formatDetail(b.detail, res.statusText);
    } catch {
      /* ignore */
    }
    throw new Error(message);
  }
  return res.json();
}

/** Fetch a protected file with the bearer token and trigger a browser download. */
/** Scope a risk export can be narrowed by — the register's own filter, by another name. */
export type RiskExportScope = {
  business_unit_id?: string;
  process_id?: string;
  asset_id?: string;
  status?: string;
  category?: string;
  search?: string;
  /** Any other register list filter (needs_review, level, appetite, pending_validation…):
   *  the PDF endpoint takes exactly the list's filters. */
  [filter: string]: string | undefined;
};

/** Filesystem-safe fragment of a record's name, for download filenames. */
export function slugForFile(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "export"
  );
}

/** "?a=1&b=2" from the defined entries, or "" when there are none. */
export function queryString(params?: Record<string, string | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value) search.set(key, value);
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

/** Filename the server chose (RFC 5987 `filename*=UTF-8''...`), else the fallback. */
function filenameFrom(res: Response, fallback: string): string {
  const cd = res.headers.get("content-disposition") || "";
  const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (star) {
    try { return decodeURIComponent(star[1]); } catch { /* fall through */ }
  }
  const plain = /filename="?([^";]+)"?/i.exec(cd);
  return plain ? plain[1] : fallback;
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** Like downloadBlob, for exports whose parameters travel in a POST body. */
export async function downloadBlobPost(path: string, body: unknown, fallback = "download"): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = `Export failed (${res.status})`;
    try { message = formatDetail((await res.json()).detail, message); } catch { /* ignore */ }
    throw new Error(message);
  }
  saveBlob(await res.blob(), filenameFrom(res, fallback));
}

export async function downloadBlob(path: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let message = `Download failed (${res.status})`;
    try { message = formatDetail((await res.json()).detail, message); } catch { /* ignore */ }
    throw new Error(message);
  }
  saveBlob(await res.blob(), filename);
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: { id: string; email: string; full_name: string; roles: { name: string }[] };
}
export interface LoginResult {
  mfa_required: boolean;
  challenge_token: string | null;
  access_token: string | null;
  token_type: string;
  expires_in: number | null;
  user: LoginResponse["user"] | null;
  /** MFA grace period is over: the token can only be used to enrol. */
  mfa_enrolment_required?: boolean;
  /** MFA is required and not yet set up; full access continues until this time. */
  mfa_enrolment_due?: string | null;
}
export interface MfaSetup {
  secret: string;
  otpauth_uri: string;
}
export interface LicenseInfo {
  valid: boolean;
  status: string;
  licensed_to: string;
  plan: string;
  seats: number;
  features: string[];
  modules: string[] | null;
  issued: string;
  expires: string;
  deployment: string;
  message: string;
}
export interface ModuleState {
  key: string;
  title: string;
  category: string;
  description: string;
  routes: string[];
  licensed: boolean;
  disabled_by_config: boolean;
  enabled: boolean;
}
export interface SystemInfo {
  app_version: string;
  deployment_mode: string;
  environment: string;
  feature_flags: Record<string, boolean>;
  license: LicenseInfo;
}
export interface SystemHealth {
  status: string;
  checks: Record<string, { ok: boolean } & Record<string, unknown>>;
}
export interface BackupItem {
  filename: string;
  size_bytes: number;
  created_at: string;
}
export interface LdapConfig {
  enabled: boolean;
  host: string;
  port: number;
  use_ssl: boolean;
  start_tls: boolean;
  bind_dn: string;
  base_dn: string;
  user_filter: string;
  email_attribute: string;
  name_attribute: string;
  default_role: string;
  bind_password_set: boolean;
}

export interface Risk {
  id: string;
  reference: string;
  title: string;
  category: string;
  status: string;
  inherent_score: number | null;
  residual_score: number | null;
  inherent_severity: string | null;
  residual_severity: string | null;
  annual_loss_frequency: number | null;
  single_loss_expectancy: number | null;
  annual_loss_expectancy: number | null;
  treatment_strategy: string | null;
  next_review_date: string | null;
  assets: { id: string; name: string }[];
  controls: { id: string; name: string; reference: string }[];
  threats: { id: string; name: string }[];
  vulnerabilities: { id: string; name: string }[];
}

export interface CatalogItem {
  id: string;
  name: string;
  description: string;
  category: string;
}

export interface QOption {
  id: string;
  label: string;
  score: number;
  order_index: number;
}
export interface QQuestion {
  id: string;
  text: string;
  guidance: string;
  order_index: number;
  max_score: number;
  options: QOption[];
}
export interface QuestionnaireSummary {
  id: string;
  name: string;
  description: string;
  question_count: number;
  max_score: number;
}
export interface Questionnaire extends QuestionnaireSummary {
  questions: QQuestion[];
}
export interface AssessmentAnswer {
  id: string;
  question_id: string;
  option_id: string | null;
  comment: string;
}
export interface AssessmentFinding {
  id: string;
  title: string;
  description: string;
  severity: string;
  status: string;
  deadline: string | null;
}
export interface AssessmentSummary {
  id: string;
  title: string;
  vendor: { id: string; name: string } | null;
  status: string;
  due_date: string | null;
  question_count: number;
  answered_count: number;
  score_pct: number;
  open_findings: number;
}
export interface Assessment extends AssessmentSummary {
  vendor_id: string | null;
  questionnaire_id: string;
  questionnaire: Questionnaire | null;
  submitted_at: string | null;
  review_notes: string;
  max_score: number;
  total_score: number;
  answers: AssessmentAnswer[];
  findings: AssessmentFinding[];
}

export interface RiskSetting {
  appetite_score: number;
  tolerance_score: number;
  matrix_size: number;
  /** How impact-dimension scores combine: the highest, or the average rounded up. */
  impact_mode?: "max" | "average";
  /** Severity → the longest review cycle a risk of that rating may have (organisation's
   *  value, else the product default). */
  review_cadence?: Record<"critical" | "high" | "medium" | "low", string>;
  review_cadence_defaults?: Record<"critical" | "high" | "medium" | "low", string>;
}
/** Configured band thresholds: the highest score that is low, medium and high. */
export interface SeverityBands {
  low_max: number;
  medium_max: number;
  high_max: number;
}
/** One matrix cell with its effective band (its override, or its score's band). */
export interface MatrixCellBand {
  likelihood: number;
  impact: number;
  score: number;
  band: string;
  overridden: boolean;
}
/** Appetite and tolerance for one top-level risk category. */
export interface RiskAppetite {
  id: string;
  category_id: string;
  category_ref: { id: string; key: string; value: string; label: string } | null;
  appetite_score: number;
  tolerance_score: number;
  statement: string;
  created_at: string;
  updated_at: string;
  risks: number;
  breaches: number;
}
/** One action of a risk's treatment plan. */
export interface TreatmentAction {
  id: string;
  risk_id: string;
  title: string;
  description: string;
  owner_id: string | null;
  owner_ref: { id: string; full_name: string; email: string } | null;
  due_date: string | null;
  status: "open" | "in_progress" | "done" | "cancelled";
  percent_complete: number;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  overdue: boolean;
}

/** One rung of the likelihood or impact scale, in the organisation's own words. */
export interface MatrixLevel {
  level: number;
  label: string;
  definition: string;
}
/** A severity band, derived from the matrix size rather than configured separately. */
export interface MatrixBand {
  severity: string;
  min_score: number;
  max_score: number;
}
export interface RiskMatrixConfig {
  size: number;
  max_score: number;
  appetite_score: number;
  tolerance_score: number;
  likelihood_levels: MatrixLevel[];
  impact_levels: MatrixLevel[];
  bands: MatrixBand[];
  /** Configured thresholds; null = derived from the matrix size. */
  severity_bands?: SeverityBands | null;
  /** Per-cell overrides, keyed "likelihood,impact". */
  matrix_cells?: Record<string, string>;
  /** Every cell with its effective band. */
  cells?: MatrixCellBand[];
  impact_mode?: "max" | "average";
}
export interface ResidualPolicy {
  enabled: boolean;
  weight_effective: number;
  weight_partially_effective: number;
  weight_ineffective: number;
  weight_not_assessed: number;
  applies_to: "likelihood" | "impact" | "both";
  max_reduction: number;
}
/** One scope of the turnaround-time grid: how long a record of this severity may stay open. */
export interface SlaPolicy {
  id: string | null;
  entity_type: string;
  entity_label: string;
  severity: string;
  target_days: number;
  warn_at_percent: number;
  escalate_to_role: string;
  enabled: boolean;
  /** True when nobody has configured this scope and the shipped default is in force. */
  is_default: boolean;
}
export interface TatRecord {
  entity_type: string;
  entity_label: string;
  entity_id: string;
  label: string;
  severity: string;
  due: string | null;
  days_overdue: number;
  link: string;
}
export interface TatSummary {
  breached: number;
  at_risk: number;
  by_type: { entity_type: string; label: string; breached: number; at_risk: number }[];
  records: TatRecord[];
}

/** One reusable "threat exploits vulnerability against this kind of asset" statement. */
export interface RiskScenario {
  id: string;
  reference: string;
  title: string;
  description: string;
  category: string;
  asset_classes: string;
  /** Comma-separated asset kinds the scenario fits (see AssetKind); empty = every kind. */
  asset_kinds: string;
  threat: string;
  vulnerability: string;
  likelihood: number;
  impact_rule: string;
  impact_property: string;
  fixed_impact: number;
  treatment_hint: string;
  enabled: boolean;
}
/** One entry of the fixed asset-kind vocabulary scenarios are matched on. */
export interface AssetKind {
  value: string;
  label: string;
  description: string;
  group: string;
}
export interface ScenarioInstallResult {
  installed: number;
  skipped: number;
  total: number;
}
export interface GenerateRisksRequest {
  asset_ids?: string[];
  asset_class?: string;
  min_criticality?: string;
  scenario_ids?: string[];
  category?: string;
  limit?: number;
}
/** A pre-filled risk shown for review — nothing is written until it is committed. */
export interface RiskProposal {
  scenario_id: string;
  scenario_reference: string;
  asset_id: string;
  asset_name: string;
  title: string;
  description: string;
  category: string;
  inherent_likelihood: number;
  inherent_impact: number;
  inherent_score: number;
  threat: string;
  vulnerability: string;
  treatment_description: string;
  control_ids: string[];
  control_labels: string[];
  /** Controls the scenario calls for that this catalogue does not have (by reference). */
  unmapped_references: string[];
  /** Phase 3: pairs with the same key become one candidate (scenario + process + unit). */
  dedupe_key: string;
  /** The candidate's scope, e.g. "Payments · Retail Banking". */
  scope_label: string;
  /** The candidate's title when it covers several assets. */
  group_title: string;
  /** A pending candidate with this key is already in the queue; the pair joins it. */
  queued_proposal_id: string | null;
  queued_title: string;
  /** The key's last candidate was rejected, and why. */
  rejected_note: string;
  rejected_at: string | null;
  /** The asset's kinds as people read them ("Server or host", "Core banking"). */
  asset_kinds?: string[];
}
export interface GenerateRisksResponse {
  proposals: RiskProposal[];
  assets_considered: number;
  scenarios_considered: number;
  duplicates_skipped: number;
  truncated: boolean;
  /** Distinct candidates the proposals would make. */
  candidates: number;
  /** Proposals that would join a candidate already in the queue. */
  queued: number;
  /** Pairs of the right class left out because the asset is not a kind the scenario fits. */
  not_fitting?: number;
  not_fitting_scenarios?: { reference: string; title: string; pairs: number; fits: string[] }[];
}
export interface GeneratedRiskCommitItem {
  asset_id: string;
  scenario_id?: string;
  scenario_reference?: string;
  title: string;
  description: string;
  category: string;
  inherent_likelihood: number;
  inherent_impact: number;
  threat: string;
  vulnerability: string;
  treatment_description: string;
  control_ids: string[];
}
/** Sending proposals to the risk candidate queue: every pair created a candidate, joined
 *  one (merged — some into candidates already waiting), was skipped as already in the
 *  register, or failed. */
export interface GenerateRisksCommitResult {
  run_id: string;
  created: number;
  merged: number;
  merged_into_existing: number;
  skipped: number;
  proposals: string[];
  skipped_items: { title: string; asset_name: string; risk_reference: string }[];
  errors: { title: string; message: string }[];
}
/** A risk candidate in the queue (/risk-proposals). */
export interface RiskCandidate {
  id: string;
  run_id: string | null;
  scenario_reference: string;
  scenario_title: string;
  scenario_category: string;
  title: string;
  description: string;
  dedupe_key: string;
  status: "pending" | "accepted" | "rejected" | "merged";
  business_unit_id: string | null;
  business_unit_ref: { id: string; name: string } | null;
  process_id: string | null;
  process_ref: { id: string; name: string } | null;
  category_id: string | null;
  category_ref: { id: string; key: string; value: string; label: string } | null;
  inherent_likelihood: number | null;
  inherent_impact: number | null;
  inherent_score: number | null;
  inherent_severity: string | null;
  control_references: string[];
  controls: { id: string; reference: string; name: string }[];
  unmapped_references: string[];
  assets: { id: string; name: string; asset_class: string }[];
  archived_assets: number;
  merged_into_id: string | null;
  merged_into: { id: string; reference?: string; title?: string } | null;
  promoted_risk_id: string | null;
  promoted_risk: { id: string; reference?: string; title?: string } | null;
  promoted_risk_archived: boolean;
  /** Register risks made before the queue that this candidate was rebuilt from. */
  source_risk_id?: string | null;
  source_risks?: { id: string; reference: string; title: string; archived: boolean }[];
  created_by_ref: { id: string; full_name: string; email: string } | null;
  decided_by_ref: { id: string; full_name: string; email: string } | null;
  decided_at: string | null;
  decision_note: string;
  created_at: string;
  updated_at: string;
}
/** One generated risk made before the queue, in the move-to-queue plan. */
export interface LegacyRiskRef {
  id: string;
  reference: string;
  title: string;
  scenario_reference: string;
  asset_id: string | null;
  asset_name: string;
  inherent_likelihood: number | null;
  inherent_impact: number | null;
  reason: string;
}
export interface LegacyMigrationPlan {
  recognised: number;
  moving: number;
  dropped: number;
  kept: number;
  new_candidates: number;
  joined_candidates: number;
  groups: {
    dedupe_key: string;
    scenario_reference: string;
    scenario_title: string;
    title: string;
    scope_label: string;
    inherent_likelihood: number | null;
    inherent_impact: number | null;
    control_references: string[];
    joins_proposal_id: string | null;
    joins_title: string;
    risks: LegacyRiskRef[];
  }[];
  dropped_items: LegacyRiskRef[];
  kept_items: LegacyRiskRef[];
}
export interface LegacyMigrationResult {
  archived: number;
  moved: number;
  dropped: number;
  kept: number;
  created: number;
  joined: number;
  proposals: string[];
}
export interface RiskCandidatePage {
  items: RiskCandidate[];
  total: number;
  limit: number;
  offset: number;
  /** Candidates per status under the same filters (the status filter ignored). */
  counts: Record<string, number>;
}

/** A live risk whose linked assets were all deleted and that has no other live link. */
export interface OrphanedRisk {
  id: string;
  reference: string;
  title: string;
  category: string;
  status: string;
  inherent_score: number | null;
  deleted_asset_names: string[];
  /** Live records still linked, per kind — zero for every listed risk. */
  live_links: Record<string, number>;
  live_link_total: number;
}
export interface OrphanedRiskPage {
  items: OrphanedRisk[];
  total: number;
  /** Risks that lost their assets but still link to something live, so are not listed. */
  kept_with_links: number;
}
export interface OrphanPurgeResult {
  archived: number;
  references: string[];
  skipped: number;
}

/** A proposal only — nothing is recorded until the risk owner accepts or overrides it. */
export interface SuggestedResidual {
  likelihood: number;
  impact: number;
  score: number;
  reduction: number;
  rationale: string[];
  inherent_score: number;
  current_residual_score: number | null;
  matches_current: boolean;
}

// --- report builder ---------------------------------------------------------
export interface ReportFilterSpec {
  key: string;
  label: string;
  kind: "select" | "multiselect" | "typeahead" | "date" | "bool" | "text";
  options: { value: string; label: string }[];
  source: string;
  help: string;
}
export interface ReportColumnSpec {
  key: string;
  label: string;
  default: boolean;
  sortable: boolean;
}
export interface ReportSubject {
  key: string;
  label: string;
  has_detail: boolean;
  default_sort: string;
  default_sort_dir: "asc" | "desc";
  columns: ReportColumnSpec[];
  filters: ReportFilterSpec[];
}
/** What the server needs to answer a report: the question, not the rows. */
export interface ReportDefinition {
  subject: string;
  filters: Record<string, unknown>;
  columns: string[];
  sort_by?: string | null;
  sort_dir?: "asc" | "desc" | null;
  include_details?: boolean;
  title?: string;
}
export interface ReportRun {
  columns: { key: string; label: string }[];
  items: { id: string; cells: Record<string, unknown> }[];
  total: number;
  summary: Record<string, Record<string, number>>;
  summary_over: number;
  params: [string, string][];
}
export interface SavedReport {
  id: string;
  name: string;
  description: string;
  subject: string;
  definition: Record<string, unknown>;
  shared: boolean;
  owner_id: string | null;
  owner_email: string;
  created_at: string;
  updated_at: string;
}
export type ReportFormat = "pdf" | "xlsx" | "csv";

/** A formal decision to accept a risk, with the expiry that makes it a decision rather
 *  than a permanent omission. */
export interface RiskAcceptance {
  id: string;
  risk_id: string;
  requested_by: string | null;
  approver_id: string | null;
  rationale: string;
  status: "pending" | "approved" | "rejected" | "expired";
  expires_at: string | null;
  decided_at: string | null;
  created_at: string;
}

export interface RiskAggregateRow {
  category: string;
  count: number;
  max_inherent_score: number | null;
  max_residual_score: number | null;
  breaches: number;
  exposure: number;
}

export interface RiskAggregate {
  rows: RiskAggregateRow[];
  total_exposure: number;
  appetite_score: number;
  tolerance_score: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// --- dashboard overview (the redesigned page's single payload) ---------------------
/** `value` is null and `population` 0 when a measure has no data: it is left out of the score. */
export interface HealthComponent { key: string; label: string; value: number | null; weight: number; detail: string; population: number; formula: string }
export interface HealthCoverage { scored: number; total: number; weight_pct: number }
export interface TopRisk {
  id: string; reference: string; title: string; score: number | null; severity: string | null;
  appetite_status: string | null; owner: string; business_units: string[]; status: string;
  treatment_strategy: string | null; next_review_date: string | null; review_overdue: boolean; control_count: number;
  needs_review?: boolean; review_reason?: string;
}
export interface FrameworkPosture {
  id: string; name: string; total: number; applicable: number; assured: number; unassessed: number;
  failing: number; unmapped: number; compliant_pct: number; gaps: number; kind?: string;
}
export interface ActionItem { key: string; label: string; count: number; href: string; tone: "critical" | "warning" | "info" }
export interface KriItem {
  id: string; reference: string; name: string; current_value: number | null; warning_threshold: number | null;
  limit_threshold: number | null; unit: string; owner: string; status: string;
}
export interface DashboardOverview {
  as_of: string;
  period_days: number;
  health: { score: number; band: string; components: HealthComponent[]; coverage?: HealthCoverage | null };
  posture: {
    total_risks: number; appetite_score: number; tolerance_score: number; within_appetite: number; elevated: number;
    breach: number; by_inherent_severity: Record<string, number>; by_residual_severity: Record<string, number>; top_risks: TopRisk[];
    /** Per top-level category appetite (present when any category has its own); the null row is the default. */
    by_category?: { category_id: string | null; label: string; appetite_score: number; tolerance_score: number; risks: number; within_appetite: number; elevated: number; breach: number }[];
  };
  assurance: {
    total: number; effective: number; partially_effective: number; ineffective: number; not_assessed: number;
    tests_overdue: number; tests_due_30d: number; last_test_failed: number; tests_in_period: number;
    not_operating?: number;
  };
  compliance: { frameworks: FrameworkPosture[]; overall_assured_pct: number; other_frameworks?: FrameworkPosture[] };
  actions: ActionItem[];
  incidents: { open: number; open_by_severity: Record<string, number>; reportable_open: number; opened_in_period: number; opened_prior_period: number; tat_breached: number };
  kris: { green: number; amber: number; red: number; no_data: number; red_items: KriItem[] };
  third_parties: { total: number; by_rating: Record<string, number>; assessments_overdue: number; critical: number };
  segments: { id: string; name: string; risks: number; breach: number; elevated: number; critical: number }[];
  movement: { period_days: number; risks_created: number; risks_closed: number; acceptances_lapsed: number; tests_recorded: number; incidents_opened: number; issues_closed: number };
  /** F-21: what the board figures are taken over, what they leave out, how complete the register is. */
  completeness?: DataCompleteness | null;
}

export interface DataCompleteness {
  /** Every live risk. */
  live_risks: number;
  /** Scored, out of Draft, not accepted or closed: what every risk figure counts. */
  board_risks: number;
  /** Drafts, scored or not, left out of the figures until validated. */
  pending_validation: number;
  unscored: number;
  /** Accepted or closed: settled, out of breach and top-risk figures by design. */
  settled: number;
  pending_href: string;
  owned: number; owned_pct: number | null;
  tagged: number; tagged_pct: number | null;
  approved: number; approved_pct: number | null;
}

export interface Dashboard {
  total_risks: number;
  total_controls: number;
  total_assets: number;
  risks_by_status: Record<string, number>;
  risks_by_inherent_severity: Record<string, number>;
  risks_by_residual_severity: Record<string, number>;
  overdue_reviews: number;
  pending_acceptances: number;
  appetite_score: number;
  tolerance_score: number;
  risks_within_appetite: number;
  risks_elevated: number;
  risks_in_breach: number;
  total_exposure: number;
}

export interface Framework {
  id: string;
  name: string;
  /** compliance | maturity | guidance — only compliance frameworks carry a compliance %. */
  kind?: string;
  version: string;
  authority: string;
  requirement_count: number;
}

export interface Requirement {
  id: string;
  framework_id: string;
  reference: string;
  title: string;
  domain: string;
  status: string;
  is_covered: boolean;
  evidence_count: number;
  crosswalk_count: number;
  controls: { id: string; name: string; reference: string }[];
}

export interface Evidence {
  id: string;
  control_id: string;
  title: string;
  description: string;
  evidence_type: string;
  reference: string;
  status: string;
  collected_at: string | null;
  valid_until: string | null;
  control?: { id: string; name: string; reference: string } | null;
}

export interface CrosswalkItem {
  id: string;
  reference: string;
  title: string;
  status: string;
  framework_id: string;
  framework_name: string;
}

export interface BusinessUnit {
  id: string;
  name: string;
  description: string;
  manager: string;
  parent_id: string | null;
  parent_name?: string | null;
}

export interface ProcessRow {
  id: string;
  name: string;
  description: string;
  business_unit_id: string | null;
  owner: string;
  criticality: string;
  rto_hours: number | null;
  rpo_hours: number | null;
  business_unit?: { id: string; name: string } | null;
}

export interface Legal {
  id: string;
  name: string;
  description: string;
  category: string;
  jurisdiction: string;
  reference: string;
  risk_magnifier: number;
}

export interface ExceptionRecord {
  id: string;
  reference: string;
  title: string;
  description: string;
  exception_type: string;
  rationale: string;
  status: string;
  start_date: string | null;
  expires_at: string | null;
  closure_date: string | null;
  is_expired: boolean;
  risks: { id: string; reference: string; title: string }[];
  policies: { id: string; reference: string; title: string }[];
  requirements: { id: string; reference: string; title: string }[];
}

export interface ProjectTask {
  id: string;
  project_id: string;
  title: string;
  description: string;
  due_date: string | null;
  completion: number;
  order_index: number;
  assignee: string;
  is_overdue: boolean;
}

export interface ProjectExpense {
  id: string;
  project_id: string;
  amount: number;
  description: string;
  expense_date: string | null;
}

export interface ProjectRef {
  id: string;
  reference?: string;
  title?: string;
  name?: string;
}

export interface Project {
  id: string;
  reference: string;
  title: string;
  description: string;
  status: string;
  owner: string;
  start_date: string | null;
  deadline: string | null;
  budget: number | null;
  spent: number;
  over_budget: boolean;
  progress: number;
  open_tasks: number;
  is_overdue: boolean;
  tasks: ProjectTask[];
  expenses: ProjectExpense[];
  risks: ProjectRef[];
  controls: ProjectRef[];
  policies: ProjectRef[];
}

export interface GoalAudit {
  id: string;
  goal_id: string;
  result: string;
  planned_date: string | null;
  conducted_date: string | null;
  metric_description: string;
  success_criteria: string;
  result_description: string;
  auditor: string;
}

export interface Goal {
  id: string;
  reference: string;
  name: string;
  description: string;
  owner: string;
  status: string;
  audit_metric: string;
  success_criteria: string;
  audit_frequency: string;
  next_audit_date: string | null;
  last_audit_date: string | null;
  audit_count: number;
  last_result: string | null;
  is_audit_overdue: boolean;
  audits: GoalAudit[];
  risks: ProjectRef[];
  projects: ProjectRef[];
  policies: ProjectRef[];
}

export interface GapItem {
  id: string;
  reference: string;
  title: string;
  status: string;
  is_covered: boolean;
  reason: string;
}

export interface GapAnalysis {
  framework_id: string;
  framework_name: string;
  total_requirements: number;
  by_status: Record<string, number>;
  covered: number;
  uncovered: number;
  compliant_pct: number;
  gaps: GapItem[];
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  roles: { name: string }[];
  mfa_enabled?: boolean;
  auth_source?: string;
  /** Operator of the deployment, not of this organisation — gates the Organisations console. */
  is_platform_admin?: boolean;
  /** This session may only enrol in MFA (grace period over). */
  mfa_enrolment_required?: boolean;
  /** MFA is required for this user and not yet set up; due by this time. */
  mfa_enrolment_due?: string | null;
  /** The MFA policy applies to this user (they cannot switch MFA off). */
  mfa_required_for_user?: boolean;
  /** Signs in through the organisation's SSO: the identity provider enforces MFA. */
  mfa_via_identity_provider?: boolean;
  /** Every permission code the user's roles grant (e.g. "org:write"). */
  permission_codes?: string[];
}

/** Auth-only deployment status for the app shell (licence banner). */
export interface SystemStatus {
  license_status: string;
  /** Dev/self-host build running without a licence — everything unlocked. */
  evaluation_build: boolean;
  enforce_license: boolean;
  app_version: string;
  deployment_mode: string;
}

/** One organisation on this deployment. Counts are read inside that organisation's own
 *  scope, never across it. */
export interface Organization {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
  users: number;
  active_users: number;
  risks: number;
  controls: number;
}

export interface PlatformSummary {
  organizations: number;
  active_organizations: number;
  users: number;
  deployment: string;
  license: Record<string, unknown>;
}

export interface Notification {
  id: string;
  title: string;
  body: string;
  category: string;
  entity_type: string;
  entity_id: string | null;
  link: string;
  created_at: string;
  seen: boolean;
  /** Who it is addressed to: a person, a role, both, or neither (everyone). */
  user_id?: string | null;
  role_name?: string;
  /** How it reached the signed-in user. */
  audience?: "me" | "role" | "everyone";
}
export interface NotificationList {
  items: Notification[];
  unseen_count: number;
  /** Of the unseen, how many are addressed to the user or one of their roles. */
  unseen_mine?: number;
  /** The feed was narrowed to alerts addressed to the user (`?mine=true`). */
  mine?: boolean;
  /** Rows in the whole feed; `items` is one page of it. */
  total: number;
  limit: number;
  offset: number;
  /** critical / warning / info tallies across the whole feed. */
  counts: Record<string, number>;
}

export interface ApprovalAction {
  actor_email: string;
  action: string;
  comment: string;
  created_at: string;
}
export interface ApprovalRequest {
  id: string;
  reference: string;
  title: string;
  description: string;
  status: string;
  entity_type: string;
  entity_id: string | null;
  entity_label: string;
  link: string;
  approver: string;
  /** Maker's user id (null for requests that only carry an e-mail). */
  requested_by?: string | null;
  requested_by_email: string;
  required_approvals: number;
  approvals_received: number;
  decided_by_email: string;
  decided_at: string | null;
  decision_comment: string;
  due_date: string | null;
  is_overdue: boolean;
  created_at: string;
  actions: ApprovalAction[];
  /** A route stage assigned to a role: the role, and active holders other than the maker. */
  approver_role?: string | null;
  approver_role_holders?: number | null;
  /** Set when nobody but the maker holds the stage role ("No one holds the … role — assign it in Users"). */
  approver_role_gap?: string | null;
  /** For the signed-in user: may they cancel (maker or administrator) or decide, and if not, why. */
  can_cancel?: boolean;
  can_decide?: boolean;
  decide_blocked_reason?: string | null;
}

export interface CustomField {
  id: string;
  model: string;
  label: string;
  field_type: string;
  options: string;
  required: boolean;
  help_text: string;
  order_index: number;
  enabled: boolean;
  created_at: string;
}
export interface CustomFieldValueItem {
  field: CustomField;
  value: string;
}

export interface MetricInfo {
  key: string;
  label: string;
  description: string;
  kind: string;
  category: string;
}
export interface Widget {
  id: string;
  title: string;
  metric_key: string;
  viz: string;
  order_index: number;
}
export interface WidgetData {
  widget: Widget;
  kind: string;
  value: number | null;
  series: { label: string; value: number }[] | null;
  error: string | null;
}

export interface CollabComment {
  id: string;
  author_email: string;
  body: string;
  created_at: string;
  can_delete: boolean;
}
export interface CollabTag {
  id: string;
  name: string;
  color: string;
}
export interface CollabAttachment {
  id: string;
  title: string;
  url: string;
  kind: string;
  added_by_email: string;
  created_at: string;
}
export interface AuditableUnit {
  id: string;
  reference: string;
  name: string;
  description: string;
  category: string;
  owner: string;
  inherent_risk: string;
  audit_frequency: string;
  last_audited_date: string | null;
  next_audit_due: string | null;
  workflow_status: string;
  is_overdue: boolean;
  created_at: string;
}
export interface AuditProcedure {
  id: string;
  engagement_id: string;
  title: string;
  description: string;
  result: string;
  conclusion: string;
  workpaper_ref: string;
  performed_by: string;
  performed_date: string | null;
  created_at: string;
}
export interface AuditFinding {
  id: string;
  engagement_id: string;
  reference: string;
  title: string;
  description: string;
  rating: string;
  risk_implication: string;
  recommendation: string;
  management_response: string;
  action_owner: string;
  due_date: string | null;
  status: string;
  closed_date: string | null;
  is_overdue: boolean;
  created_at: string;
}
/** Engagements and open findings split by who performed the audit. */
export interface AssuranceSummary {
  rows: {
    audit_type: string;
    label: string;
    engagements: number;
    open_engagements: number;
    findings: number;
    open_findings: number;
    overdue_findings: number;
  }[];
  total_engagements: number;
  total_open_findings: number;
}

export interface AuditEngagement {
  id: string;
  reference: string;
  title: string;
  scope: string;
  objectives: string;
  auditable_unit_id: string | null;
  lead_auditor: string;
  audit_team: string;
  /** Provenance: internal | external_statutory | regulatory | certification. */
  audit_type: string;
  auditor_firm: string;
  report_reference: string;
  report_date: string | null;
  status: string;
  period_start: string | null;
  period_end: string | null;
  planned_start: string | null;
  planned_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  conclusion: string;
  rating: string | null;
  workflow_status: string;
  finding_count: number;
  open_finding_count: number;
  is_overdue: boolean;
  created_at: string;
  procedures: AuditProcedure[];
  findings: AuditFinding[];
}
export interface ShariahRuling {
  id: string;
  reference: string;
  title: string;
  subject: string;
  ruling_text: string;
  basis: string;
  status: string;
  approved_by: string;
  issued_date: string | null;
  review_frequency: string;
  next_review_date: string | null;
  workflow_status: string;
  is_review_overdue: boolean;
  created_at: string;
}
export interface IslamicProduct {
  id: string;
  reference: string;
  name: string;
  description: string;
  shariah_mode: string;
  structure: string;
  status: string;
  owner: string;
  launch_date: string | null;
  approving_ruling_id: string | null;
  workflow_status: string;
  created_at: string;
}
export interface ShariahFinding {
  id: string;
  review_id: string;
  reference: string;
  title: string;
  description: string;
  severity: string;
  snc_income_amount: number | null;
  recommendation: string;
  management_response: string;
  action_owner: string;
  due_date: string | null;
  status: string;
  closed_date: string | null;
  is_overdue: boolean;
  created_at: string;
}
export interface ShariahReview {
  id: string;
  reference: string;
  title: string;
  scope: string;
  review_type: string;
  reviewer: string;
  status: string;
  period_start: string | null;
  period_end: string | null;
  planned_date: string | null;
  conclusion: string;
  rating: string | null;
  product_id: string | null;
  workflow_status: string;
  finding_count: number;
  open_finding_count: number;
  snc_income_total: number;
  created_at: string;
  findings: ShariahFinding[];
}
export interface CharityDisbursement {
  id: string;
  reference: string;
  description: string;
  amount: number;
  currency: string;
  source_finding_id: string | null;
  beneficiary: string;
  status: string;
  disbursement_date: string | null;
  notes: string;
  workflow_status: string;
  created_at: string;
}
export interface RcsaRisk {
  id: string;
  assessment_id: string;
  title: string;
  category: string;
  inherent_likelihood: number;
  inherent_impact: number;
  control_description: string;
  control_effectiveness: string;
  residual_likelihood: number;
  residual_impact: number;
  action: string;
  action_owner: string;
  due_date: string | null;
  inherent_score: number;
  residual_score: number;
  created_at: string;
}
export interface RcsaAssessment {
  id: string;
  reference: string;
  title: string;
  business_unit: string;
  process: string;
  assessor: string;
  status: string;
  period: string;
  due_date: string | null;
  completed_date: string | null;
  workflow_status: string;
  risk_count: number;
  is_overdue: boolean;
  created_at: string;
  risks: RcsaRisk[];
}
export interface KriMeasurement {
  id: string;
  value: number;
  as_of_date: string | null;
  notes: string;
  created_at: string;
}
export interface KeyRiskIndicator {
  id: string;
  reference: string;
  name: string;
  description: string;
  category: string;
  business_area: string;
  owner: string;
  unit: string;
  frequency: string;
  direction: string;
  warning_threshold: number | null;
  limit_threshold: number | null;
  current_value: number | null;
  last_measured_date: string | null;
  workflow_status: string;
  status: string;
  is_breached: boolean;
  created_at: string;
  measurements: KriMeasurement[];
  // Phase 2 (F-14): definition, lineage, within-range band, appetite, escalation, feed.
  definition?: string;
  numerator?: string;
  denominator?: string;
  data_source?: string;
  data_provider_id?: string | null;
  data_provider_ref?: { id: string; full_name: string; email: string } | null;
  indicator_type?: "leading" | "lagging" | null;
  lower_bound?: number | null;
  upper_bound?: number | null;
  appetite_id?: string | null;
  appetite_ref?: KriAppetiteRef | null;
  escalations?: KriEscalation[];
  has_feed_token?: boolean;
}
/** The risk appetite a KRI measures (per top-level risk category). */
export interface KriAppetiteRef {
  id: string;
  category_id: string;
  category_label: string;
  appetite_score: number;
  tolerance_score: number;
  statement: string;
}
/** Who is told, and what they do, when a KRI turns amber or red. */
export interface KriEscalation {
  id: string;
  kri_id: string;
  level: "amber" | "red";
  escalate_to_id: string | null;
  escalate_to_ref: { id: string; full_name: string; email: string } | null;
  escalate_to_role: string;
  action: string;
  created_at: string;
}
/** Returned once by POST /kris/{id}/feed-token; only a hash is kept server-side. */
export interface KriFeedToken {
  kri_id: string;
  token: string;
  endpoint: string;
  header: string;
  note: string;
}
export interface LossEvent {
  id: string;
  reference: string;
  title: string;
  description: string;
  basel_event_type: string;
  business_line: string;
  gross_loss: number;
  recovery: number;
  currency: string;
  status: string;
  occurrence_date: string | null;
  discovery_date: string | null;
  accounting_date: string | null;
  root_cause: string;
  action_owner: string;
  workflow_status: string;
  net_loss: number;
  created_at: string;
}
export interface LossSummary {
  rows: { basel_event_type: string; count: number; gross_loss: number; net_loss: number }[];
  total_gross: number;
  total_net: number;
  total_count: number;
}
export interface ScreeningCase {
  id: string;
  reference: string;
  subject_name: string;
  subject_type: string;
  screening_type: string;
  lists_checked: string;
  match_status: string;
  risk_rating: string;
  screened_date: string | null;
  disposition: string;
  reviewer: string;
  status: string;
  workflow_status: string;
  created_at: string;
}
export interface ScreeningSummary {
  total: number;
  by_match_status: Record<string, number>;
  open_cases: number;
  escalated: number;
}
export interface Sar {
  id: string;
  reference: string;
  subject: string;
  activity_description: string;
  suspicion_reason: string;
  amount: number | null;
  currency: string;
  analyst: string;
  priority: string;
  detected_date: string | null;
  deadline: string | null;
  filed_date: string | null;
  fmu_reference: string;
  status: string;
  workflow_status: string;
  is_overdue: boolean;
  created_at: string;
}
export interface AmlRisk {
  id: string;
  reference: string;
  title: string;
  scope: string;
  subject: string;
  inherent_risk: string;
  mitigating_controls: string;
  residual_risk: string;
  assessor: string;
  assessment_date: string | null;
  review_frequency: string;
  next_review_date: string | null;
  workflow_status: string;
  is_review_overdue: boolean;
  created_at: string;
}
export interface SearchHit {
  type: string;
  label: string;
  reference: string;
  title: string;
  link: string;
}
export interface SearchResults {
  query: string;
  hits: SearchHit[];
}
export interface RiskMatrixCell {
  likelihood: number;
  impact: number;
  score: number;
  /** The cell's band — its override, or its score's band. Colour from this. */
  band?: string;
  inherent_count: number;
  residual_count: number;
  inherent_refs: string[];
  residual_refs: string[];
}
export interface RiskMatrix {
  cells: RiskMatrixCell[];
  appetite_score: number;
  tolerance_score: number;
  total: number;
  /** The matrix the counts were plotted on — render this grid, not a fixed 5x5. */
  size: number;
  max_score: number;
  likelihood_levels: MatrixLevel[];
  impact_levels: MatrixLevel[];
  /** Server-derived bands; colour from these so client and server never disagree. */
  bands: MatrixBand[];
  /** The hierarchy level the map is aggregated to (null = every risk plotted). */
  level?: number | null;
}
export interface CollabFile {
  id: string;
  title: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_by_email: string;
  created_at: string;
  can_delete: boolean;
}
export interface CollabBundle {
  comments: CollabComment[];
  tags: CollabTag[];
  attachments: CollabAttachment[];
  files: CollabFile[];
  available_tags: CollabTag[];
}

export interface Webhook {
  id: string;
  name: string;
  url: string;
  events: string;
  enabled: boolean;
  last_status: number | null;
  last_delivered_at: string | null;
  created_at: string;
}
export interface WebhookDelivery {
  id: string;
  event: string;
  status_code: number | null;
  success: boolean;
  error: string;
  created_at: string;
}

export interface StatusRule {
  id: string;
  model: string;
  field: string;
  operator: string;
  value: string;
  label: string;
  color: string;
  priority: number;
  enabled: boolean;
}
export interface StatusLabel {
  label: string;
  color: string;
}
export interface FieldInfo {
  key: string;
  type: string;
  label: string;
  options?: string[];
}

export interface Attestation {
  id: string;
  attested_by_id: string | null;
  attested_by_email: string;
  attested_at: string;
  comment: string;
  frequency: string;
  next_due: string | null;
  statement: string;
  scope: string;
  confirmed_by_id: string | null;
  confirmed_by_email: string | null;
  confirmed_at: string | null;
  created_at: string;
}
export interface AttestationStatus {
  status: string;
  last_attested_at: string | null;
  last_by: string | null;
  next_due: string | null;
  frequency: string | null;
  history: Attestation[];
  /** The record carries its own review cycle (risk, policy, vendor). */
  native_review: boolean;
  default_statement: string;
}

export interface FilterCondition {
  field: string;
  operator: string;
  value: string;
}
export interface SavedFilter {
  id: string;
  name: string;
  model: string;
  description: string;
  match_mode: string;
  conditions: FilterCondition[];
  shared: boolean;
  owner_email: string;
  created_at: string;
}
export interface FilterResults {
  count: number;
  total: number;
  matches: { id: string; label: string }[];
}

export interface SsoConfig {
  provider: string;
  enabled: boolean;
  client_id: string;
  authorize_url: string;
  token_url: string;
  userinfo_url: string;
  scopes: string;
  email_claim: string;
  name_claim: string;
  jit_provisioning: boolean;
  default_role: string;
  allowed_domains: string;
  client_secret_set: boolean;
}

export interface Control {
  id: string;
  name: string;
  reference: string;
  owner: string;
  status: string;
  effectiveness: string;
  audit_frequency: string;
  maintenance_frequency: string;
  next_audit_date: string | null;
  last_audit_date: string | null;
  next_maintenance_date: string | null;
  last_maintenance_date: string | null;
  audit_count: number;
  last_audit_result: string | null;
  is_audit_overdue: boolean;
  maintenance_count: number;
  last_maintenance_result: string | null;
  is_maintenance_overdue: boolean;
}

export interface ControlAudit {
  id: string;
  control_id: string;
  result: string;
  planned_date: string | null;
  conducted_date: string | null;
  result_description: string;
  auditor: string;
}

export interface ControlMaintenance {
  id: string;
  control_id: string;
  result: string;
  task: string;
  planned_date: string | null;
  conducted_date: string | null;
  conclusion: string;
}

interface LinkRef {
  id: string;
  label: string;
}
export interface Asset {
  id: string;
  name: string;
  description: string;
  media_type: LinkRef | null;
  label: LinkRef | null;
  owner: LinkRef | null;
  guardian: LinkRef | null;
  user: LinkRef | null;
  criticality: string;
  confidentiality: string;
  integrity: string;
  availability: string;
  classification: string;
  review_status?: string;
  next_review_date?: string | null;
  workflow_status?: string;
  classifications?: { id: string; name: string; value: number; type_name: string }[];
  risks?: LinkRef[];
  reviews?: unknown[];
}

export interface AssetLabel {
  id: string;
  name: string;
  description: string;
  color: string;
}

export interface ContinuityTask {
  id: string;
  plan_id: string;
  step: number;
  action: string;
  actor: string;
  timing: string;
  location: string;
  method: string;
}
export interface ContinuityTest {
  id: string;
  plan_id: string;
  result: string;
  planned_date: string | null;
  conducted_date: string | null;
  result_description: string;
  tester: string;
}
export interface ContinuityPlan {
  id: string;
  reference: string;
  name: string;
  description: string;
  status: string;
  owner: string;
  business_unit_id: string | null;
  process_id: string | null;
  max_tolerable_downtime_hours: number | null;
  criticality: string;
  test_frequency: string;
  next_test_date: string | null;
  last_test_date: string | null;
  task_count: number;
  test_count: number;
  last_test_result: string | null;
  is_test_overdue: boolean;
  business_unit: { id: string; name: string } | null;
  process: { id: string; name: string } | null;
  tasks: ContinuityTask[];
  tests: ContinuityTest[];
}

export interface AwOption { id: string; label: string; is_correct: boolean; order_index: number }
export interface AwQuestion { id: string; text: string; order_index: number; options: AwOption[] }
export interface TrainingRecord {
  id: string;
  program_id: string;
  participant_name: string;
  participant_email: string;
  status: string;
  score: number | null;
  completed_at: string | null;
}
export interface AwarenessProgram {
  id: string;
  reference: string;
  name: string;
  description: string;
  content: string;
  status: string;
  passing_score: number;
  frequency: string;
  due_date: string | null;
  next_due_date: string | null;
  question_count: number;
  participant_count: number;
  completed_count: number;
  compliant_count: number;
  completion_pct: number;
  compliance_pct: number;
  questions: AwQuestion[];
  participants: TrainingRecord[];
}

export interface AccessReviewItem {
  id: string;
  review_id: string;
  username: string;
  display_name: string;
  access: string;
  decision: string;
  comment: string;
  decided_by: string;
  decided_at: string | null;
}
export interface AccessReview {
  id: string;
  reference: string;
  name: string;
  description: string;
  status: string;
  reviewer: string;
  system_name: string;
  asset_id: string | null;
  due_date: string | null;
  frequency: string;
  next_review_date: string | null;
  completed_at: string | null;
  total_items: number;
  reviewed_count: number;
  keep_count: number;
  revoke_count: number;
  completion_pct: number;
  is_overdue: boolean;
  asset: { id: string; name: string } | null;
  items: AccessReviewItem[];
}

export interface Ropa {
  id: string;
  reference: string;
  name: string;
  purpose: string;
  status: string;
  lawful_basis: string;
  data_subjects: string;
  data_categories: string;
  special_category: boolean;
  retention_period: string;
  controller: string;
  processor: string;
  dpo: string;
  business_unit_id: string | null;
  cross_border_transfer: boolean;
  transfer_destinations: string;
  transfer_safeguard: string;
  dpia_required: boolean;
  dpia_status: string;
  has_transfer_gap: boolean;
  dpia_outstanding: boolean;
  business_unit: { id: string; name: string } | null;
  assets: { id: string; name: string }[];
  risks: { id: string; reference: string; title: string }[];
}

export interface UserRow {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  roles: { name: string }[];
}

export interface AuditEntry {
  id: string;
  actor_email: string;
  action: string;
  entity_type: string;
  summary: string;
  created_at: string;
}

export interface FrameworkSummary {
  framework_id: string;
  name: string;
  /** compliance | maturity | guidance */
  kind?: string;
  total_requirements: number;
  compliant: number;
  compliant_pct: number;
  /** Clauses assessed (self-assessment progress for maturity frameworks). */
  assessed?: number;
}

export interface ComplianceSummary {
  total_frameworks: number;
  total_requirements: number;
  overall_compliant_pct: number;
  frameworks: FrameworkSummary[];
}

export interface IncidentStage {
  id: string;
  incident_id: string;
  name: string;
  order_index: number;
  status: string;
  notes: string;
  completed_at: string | null;
}
export interface Incident {
  id: string;
  reference: string;
  title: string;
  category: string;
  severity: string;
  status: string;
  assignee: string;
  /** ISO 8601 timestamps with offset since phase 2 (were dates): use formatDateTime. */
  detected_at: string | null;
  occurred_at?: string | null;
  contained_at?: string | null;
  resolved_at: string | null;
  near_miss?: boolean;
  personal_data_breach?: boolean;
  /** Regulator-notification clock (the initial report's deadline / submission). */
  notification_deadline?: string | null;
  notified_at?: string | null;
  hours_to_deadline?: number | null;
  notified_on_time?: boolean | null;
  mttd_hours?: number | null;
  mttc_hours?: number | null;
  mttr_hours?: number | null;
  stage_count: number;
  completed_stages: number;
  lifecycle_complete: boolean;
  current_stage: string | null;
  stages: IncidentStage[];
}

export interface PolicyLink {
  id: string;
  reference?: string;
  title?: string;
  name?: string;
}

export interface Policy {
  id: string;
  reference: string;
  title: string;
  summary: string;
  body: string;
  url: string;
  category: string;
  document_type: string;
  version: string;
  status: string;
  workflow_status: string;
  owner: string;
  label_id: string | null;
  use_attachments: boolean;
  review_frequency: string;
  next_review_date: string | null;
  last_review_date: string | null;
  published_at: string | null;
  expired_reviews: number;
  is_review_overdue: boolean;
  acknowledgment_count: number;
  related: PolicyLink[];
  controls: PolicyLink[];
  requirements: PolicyLink[];
  risks: PolicyLink[];
  // Phase 2: governance and applicability.
  approving_authority_id?: string | null;
  approving_authority_ref?: PolicyLink | null;
  effective_date?: string | null;
  supersedes_id?: string | null;
  supersedes_ref?: PolicyLink | null;
  superseded_by?: PolicyLink[];
  business_units?: PolicyLink[];
  roles?: PolicyLink[];
}
/** GET /policies/{id}/acknowledgement-status — who must acknowledge, and who has. */
export interface PolicyAckStatus {
  policy_id: string;
  scope: "roles" | "everyone";
  roles: string[];
  note: string;
  total: number;
  acknowledged: number;
  pending: number;
  outside_scope: number;
  users: { user_id: string; full_name: string; email: string; roles: string[]; acknowledged: boolean; acknowledged_at: string | null }[];
}

export interface Vendor {
  id: string;
  name: string;
  category: string;
  contact_email: string;
  criticality: string;
  status: string;
  risk_rating: string | null;
  assessment_status: string;
  last_assessed_at: string | null;
}

export const api = {
  login: (tenant_slug: string, email: string, password: string) =>
    request<LoginResult>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ tenant_slug, email, password }),
    }),
  mfaVerify: (challenge_token: string, code: string) =>
    request<LoginResponse>("/auth/mfa/verify", {
      method: "POST",
      body: JSON.stringify({ challenge_token, code }),
    }),
  mfaSetup: () => request<MfaSetup>("/auth/mfa/setup", { method: "POST" }),
  mfaActivate: (code: string) =>
    request<unknown>("/auth/mfa/activate", { method: "POST", body: JSON.stringify({ code }) }),
  mfaDisable: (code: string) =>
    request<unknown>("/auth/mfa/disable", { method: "POST", body: JSON.stringify({ code }) }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),
  ldapConfig: () => request<LdapConfig>("/auth/ldap/config"),
  saveLdapConfig: (payload: Record<string, unknown>) =>
    request<LdapConfig>("/auth/ldap/config", { method: "PUT", body: JSON.stringify(payload) }),
  systemInfo: () => request<SystemInfo>("/system/info"),
  systemModules: () => request<ModuleState[]>("/system/modules"),
  systemStatus: () => request<SystemStatus>("/system/status"),
  systemHealth: () => request<SystemHealth>("/system/health"),
  listBackups: () => request<BackupItem[]>("/system/backups"),
  createBackup: () => request<BackupItem>("/system/backups", { method: "POST" }),
  downloadSupportBundle: () => downloadBlob("/system/support-bundle", "nexusline-support-bundle.zip"),
  risks: () => request<Page<Risk>>("/risks?limit=200"),
  orphanedRisks: () => request<OrphanedRiskPage>("/risks/orphaned"),
  purgeOrphanedRisks: (riskIds: string[], reason: string) =>
    request<OrphanPurgeResult>("/risks/orphaned/purge", {
      method: "POST",
      body: JSON.stringify({ risk_ids: riskIds, reason }),
    }),
  dashboard: () => request<Dashboard>("/dashboard"),
  dashboardOverview: (days = 30) => request<DashboardOverview>(`/dashboard/overview?days=${days}`),
  createRisk: (payload: Record<string, unknown>) =>
    request<Risk>("/risks", { method: "POST", body: JSON.stringify(payload) }),
  frameworks: () => request<Page<Framework>>("/frameworks"),
  requirements: (frameworkId: string) =>
    request<Requirement[]>(`/frameworks/${frameworkId}/requirements`),
  gapAnalysis: (frameworkId: string) =>
    request<GapAnalysis>(`/frameworks/${frameworkId}/gap-analysis`),
  complianceSummary: () => request<ComplianceSummary>("/compliance/summary"),
  createFramework: (payload: Record<string, unknown>) =>
    request<Framework>("/frameworks", { method: "POST", body: JSON.stringify(payload) }),

  me: () => request<Me>("/auth/me"),

  // --- platform operations (organisation provisioning; platform admins only) ---
  organizations: (withCounts = true) =>
    request<Organization[]>(`/platform/organizations?with_counts=${withCounts}`),
  createOrganization: (body: {
    name: string;
    slug: string;
    admin_email: string;
    admin_password: string;
    admin_full_name?: string;
  }) => request<Organization>("/platform/organizations", { method: "POST", body: JSON.stringify(body) }),
  updateOrganization: (id: string, body: { name?: string; is_active?: boolean }) =>
    request<Organization>(`/platform/organizations/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  platformSummary: () => request<PlatformSummary>("/platform/summary"),
  /** `query` adds filters, e.g. "&mine=true" or "&fresh=false" (the bell). */
  notifications: (limit = 100, offset = 0, query = "") => request<NotificationList>(`/notifications?limit=${limit}&offset=${offset}${query}`),
  markNotificationsSeen: () => request<void>("/notifications/seen", { method: "POST" }),
  approvals: () => request<Page<ApprovalRequest>>("/approvals?limit=200"),
  submitApproval: (payload: Record<string, unknown>) =>
    request<ApprovalRequest>("/approvals", { method: "POST", body: JSON.stringify(payload) }),
  decideApproval: (id: string, approve: boolean, comment = "") =>
    request<ApprovalRequest>(`/approvals/${id}/decision`, { method: "POST", body: JSON.stringify({ approve, comment }) }),
  cancelApproval: (id: string) =>
    request<ApprovalRequest>(`/approvals/${id}/cancel`, { method: "POST" }),
  customFieldModels: () => request<string[]>("/custom-fields/models"),
  customFields: (model?: string) =>
    request<Page<CustomField>>(`/custom-fields?limit=200${model ? `&model=${model}` : ""}`).then((r) => r.items),
  createCustomField: (payload: Record<string, unknown>) =>
    request<CustomField>("/custom-fields", { method: "POST", body: JSON.stringify(payload) }),
  deleteCustomField: (id: string) =>
    request<void>(`/custom-fields/${id}`, { method: "DELETE" }),
  customFieldValues: (model: string, entityId: string) =>
    request<CustomFieldValueItem[]>(`/custom-fields/${model}/values/${entityId}`),
  setCustomFieldValues: (model: string, entityId: string, values: Record<string, string>) =>
    request<CustomFieldValueItem[]>(`/custom-fields/${model}/values/${entityId}`, {
      method: "PUT",
      body: JSON.stringify({ values }),
    }),
  reportMetrics: () => request<MetricInfo[]>("/reports/metrics"),
  reportDashboard: () => request<WidgetData[]>("/reports/dashboard"),
  createWidget: (payload: Record<string, unknown>) =>
    request<Widget>("/reports/widgets", { method: "POST", body: JSON.stringify(payload) }),
  deleteWidget: (id: string) =>
    request<void>(`/reports/widgets/${id}`, { method: "DELETE" }),
  collab: (entityType: string, entityId: string) =>
    request<CollabBundle>(`/collab/${entityType}/${entityId}`),
  addComment: (entityType: string, entityId: string, body: string) =>
    request<CollabComment>(`/collab/${entityType}/${entityId}/comments`, { method: "POST", body: JSON.stringify({ body }) }),
  deleteComment: (id: string) =>
    request<void>(`/collab/comments/${id}`, { method: "DELETE" }),
  addAttachment: (entityType: string, entityId: string, payload: Record<string, unknown>) =>
    request<CollabAttachment>(`/collab/${entityType}/${entityId}/attachments`, { method: "POST", body: JSON.stringify(payload) }),
  deleteAttachment: (id: string) =>
    request<void>(`/collab/attachments/${id}`, { method: "DELETE" }),
  uploadFile: (entityType: string, entityId: string, file: File) =>
    uploadMultipart<CollabFile>(`/collab/${entityType}/${entityId}/files`, file),
  downloadFile: (id: string, filename: string) =>
    downloadBlob(`/collab/files/${id}/download`, filename),
  deleteFile: (id: string) =>
    request<void>(`/collab/files/${id}`, { method: "DELETE" }),
  sendTestEmail: () =>
    request<{ smtp_configured: boolean; sent: boolean; recipient: string }>(
      "/notifications/test-email",
      { method: "POST" },
    ),
  assignTag: (entityType: string, entityId: string, payload: Record<string, unknown>) =>
    request<CollabTag[]>(`/collab/${entityType}/${entityId}/tags`, { method: "POST", body: JSON.stringify(payload) }),
  unassignTag: (entityType: string, entityId: string, tagId: string) =>
    request<void>(`/collab/${entityType}/${entityId}/tags/${tagId}`, { method: "DELETE" }),
  webhooks: () => request<Page<Webhook>>("/webhooks?limit=200").then((r) => r.items),
  createWebhook: (payload: Record<string, unknown>) =>
    request<Webhook>("/webhooks", { method: "POST", body: JSON.stringify(payload) }),
  updateWebhook: (id: string, payload: Record<string, unknown>) =>
    request<Webhook>(`/webhooks/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteWebhook: (id: string) => request<void>(`/webhooks/${id}`, { method: "DELETE" }),
  webhookDeliveries: (id: string) => request<WebhookDelivery[]>(`/webhooks/${id}/deliveries`),
  testWebhook: (id: string) => request<WebhookDelivery>(`/webhooks/${id}/test`, { method: "POST" }),
  statusRuleModels: () => request<string[]>("/status-rules/models"),
  statusRuleOperators: () => request<string[]>("/status-rules/operators"),
  statusRuleFields: (model: string) => request<FieldInfo[]>(`/status-rules/fields/${model}`),
  statusRules: (model?: string) =>
    request<Page<StatusRule>>(`/status-rules?limit=200${model ? `&model=${model}` : ""}`).then((r) => r.items),
  createStatusRule: (payload: Record<string, unknown>) =>
    request<StatusRule>("/status-rules", { method: "POST", body: JSON.stringify(payload) }),
  deleteStatusRule: (id: string) => request<void>(`/status-rules/${id}`, { method: "DELETE" }),
  evaluateStatus: (model: string, ids: string[]) =>
    request<Record<string, StatusLabel[]>>(`/status-rules/evaluate/${model}`, { method: "POST", body: JSON.stringify({ ids }) }),
  attestation: (entityType: string, entityId: string) =>
    request<AttestationStatus>(`/attestations/${entityType}/${entityId}`),
  attest: (entityType: string, entityId: string, payload: Record<string, unknown>) =>
    request<AttestationStatus>(`/attestations/${entityType}/${entityId}`, { method: "POST", body: JSON.stringify(payload) }),
  confirmAttestation: (attestationId: string) =>
    request<AttestationStatus>(`/attestations/${attestationId}/confirm`, { method: "POST" }),
  filterFields: (model: string) => request<FieldInfo[]>(`/filters/fields/${model}`),
  filters: (model?: string) =>
    request<Page<SavedFilter>>(`/filters?limit=200${model ? `&model=${model}` : ""}`).then((r) => r.items),
  createFilter: (payload: Record<string, unknown>) =>
    request<SavedFilter>("/filters", { method: "POST", body: JSON.stringify(payload) }),
  deleteFilter: (id: string) => request<void>(`/filters/${id}`, { method: "DELETE" }),
  runFilter: (id: string) => request<FilterResults>(`/filters/${id}/results`),
  ssoConfig: () => request<SsoConfig>("/auth/sso/config"),
  updateSsoConfig: (payload: Record<string, unknown>) =>
    request<SsoConfig>("/auth/sso/config", { method: "PUT", body: JSON.stringify(payload) }),
  ssoStatus: (slug: string) => request<{ enabled: boolean; provider: string }>(`/auth/sso/${slug}/status`),
  ssoLogin: (slug: string, redirectUri: string) =>
    request<{ redirect_url: string }>(`/auth/sso/${slug}/login?redirect_uri=${encodeURIComponent(redirectUri)}`),
  ssoCallback: (slug: string, payload: { code: string; state: string; redirect_uri: string }) =>
    request<LoginResponse>(`/auth/sso/${slug}/callback`, { method: "POST", body: JSON.stringify(payload) }),
  controls: () => request<Page<Control>>("/controls?limit=200"),
  createControl: (payload: Record<string, unknown>) =>
    request<Control>("/controls", { method: "POST", body: JSON.stringify(payload) }),
  controlAudits: (id: string) => request<ControlAudit[]>(`/controls/${id}/audits`),
  recordControlAudit: (id: string, payload: Record<string, unknown>) =>
    request<Control>(`/controls/${id}/audits`, { method: "POST", body: JSON.stringify(payload) }),
  controlMaintenances: (id: string) => request<ControlMaintenance[]>(`/controls/${id}/maintenances`),
  recordControlMaintenance: (id: string, payload: Record<string, unknown>) =>
    request<Control>(`/controls/${id}/maintenances`, { method: "POST", body: JSON.stringify(payload) }),
  assets: () => request<Page<Asset>>("/assets?limit=200"),
  createAsset: (payload: Record<string, unknown>) =>
    request<Asset>("/assets", { method: "POST", body: JSON.stringify(payload) }),
  assetLabels: () => request<AssetLabel[]>("/asset-labels"),
  createAssetLabel: (payload: Record<string, unknown>) =>
    request<AssetLabel>("/asset-labels", { method: "POST", body: JSON.stringify(payload) }),
  users: () => request<Page<UserRow>>("/users?limit=200"),
  createUser: (payload: Record<string, unknown>) =>
    request<UserRow>("/users", { method: "POST", body: JSON.stringify(payload) }),
  audit: (limit = 50) => request<Page<AuditEntry>>(`/audit?limit=${limit}`),

  incidents: () => request<Page<Incident>>("/incidents?limit=200"),
  createIncident: (payload: Record<string, unknown>) =>
    request<Incident>("/incidents", { method: "POST", body: JSON.stringify(payload) }),
  updateIncidentStage: (id: string, stageId: string, payload: Record<string, unknown>) =>
    request<Incident>(`/incidents/${id}/stages/${stageId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  policies: () => request<Page<Policy>>("/policies?limit=200"),
  policy: (id: string) => request<Policy>(`/policies/${id}`),
  policyOptions: () => request<{ committees: PolicyLink[]; roles: PolicyLink[] }>("/policies/options"),
  policyAckStatus: (id: string) => request<PolicyAckStatus>(`/policies/${id}/acknowledgement-status`),
  createPolicy: (payload: Record<string, unknown>) =>
    request<Policy>("/policies", { method: "POST", body: JSON.stringify(payload) }),
  updatePolicy: (id: string, payload: Record<string, unknown>) =>
    request<Policy>(`/policies/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deletePolicy: (id: string) =>
    request<unknown>(`/policies/${id}`, { method: "DELETE" }),
  acknowledgePolicy: (id: string) =>
    request<unknown>(`/policies/${id}/acknowledge`, { method: "POST" }),
  vendors: () => request<Page<Vendor>>("/vendors?limit=200"),
  createVendor: (payload: Record<string, unknown>) =>
    request<Vendor>("/vendors", { method: "POST", body: JSON.stringify(payload) }),

  riskSettings: () => request<RiskSetting>("/risk-settings"),
  updateRiskSettings: (payload: { appetite_score: number; tolerance_score: number }) =>
    request<RiskSetting>("/risk-settings", { method: "PUT", body: JSON.stringify(payload) }),
  /** Change only what is sent: appetite, tolerance or the rating-driven review cadence. */
  patchRiskSettings: (payload: { appetite_score?: number; tolerance_score?: number; review_cadence?: Record<string, string> }) =>
    request<RiskSetting>("/risk-settings", { method: "PATCH", body: JSON.stringify(payload) }),
  riskAlerts: () => request<Risk[]>("/risk-alerts"),
  riskAggregate: () => request<RiskAggregate>("/risk-aggregate"),
  /** `board` plots only validated risks (out of Draft, not accepted or closed) — the dashboard's view. */
  /** `level` aggregates the map to one hierarchy level: each risk at that level is plotted
   *  where the worst risk in its branch sits. */
  riskMatrix: (scope: "register" | "board" = "register", level?: 1 | 2 | 3) =>
    request<RiskMatrix>(`/risk-matrix?scope=${scope}${level ? `&level=${level}` : ""}`),

  // Risk methodology: matrix scale, scale wording and the residual-suggestion policy.
  riskMatrixConfig: () => request<RiskMatrixConfig>("/risk-matrix-config"),
  updateRiskMatrixConfig: (payload: {
    size: number;
    likelihood_levels: MatrixLevel[];
    impact_levels: MatrixLevel[];
    /** Omit to keep; null returns to the derived bands. */
    severity_bands?: SeverityBands | null;
    /** Omit to keep; {} removes every override. */
    matrix_cells?: Record<string, string>;
    impact_mode?: "max" | "average";
  }) => request<RiskMatrixConfig>("/risk-matrix-config", { method: "PUT", body: JSON.stringify(payload) }),
  // Appetite per top-level risk category (the organisation's is the fallback).
  riskAppetites: () => request<RiskAppetite[]>("/risk-appetites"),
  createRiskAppetite: (payload: { category_id: string; appetite_score: number; tolerance_score: number; statement?: string }) =>
    request<RiskAppetite>("/risk-appetites", { method: "POST", body: JSON.stringify(payload) }),
  updateRiskAppetite: (id: string, payload: { appetite_score?: number; tolerance_score?: number; statement?: string }) =>
    request<RiskAppetite>(`/risk-appetites/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteRiskAppetite: (id: string) => request<unknown>(`/risk-appetites/${id}`, { method: "DELETE" }),
  // A risk's treatment actions.
  treatmentActions: (riskId: string) => request<TreatmentAction[]>(`/risks/${riskId}/treatment-actions`),
  createTreatmentAction: (riskId: string, payload: Partial<Pick<TreatmentAction, "title" | "description" | "owner_id" | "due_date" | "status" | "percent_complete">>) =>
    request<TreatmentAction>(`/risks/${riskId}/treatment-actions`, { method: "POST", body: JSON.stringify(payload) }),
  updateTreatmentAction: (riskId: string, actionId: string, payload: Partial<Pick<TreatmentAction, "title" | "description" | "owner_id" | "due_date" | "status" | "percent_complete">>) =>
    request<TreatmentAction>(`/risks/${riskId}/treatment-actions/${actionId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteTreatmentAction: (riskId: string, actionId: string) =>
    request<unknown>(`/risks/${riskId}/treatment-actions/${actionId}`, { method: "DELETE" }),
  residualPolicy: () => request<ResidualPolicy>("/residual-policy"),
  updateResidualPolicy: (payload: ResidualPolicy) =>
    request<ResidualPolicy>("/residual-policy", { method: "PUT", body: JSON.stringify(payload) }),
  // Turnaround-time (TAT) policy and breach reporting.
  slaPolicies: () => request<SlaPolicy[]>("/sla-policies"),
  updateSlaPolicies: (policies: Omit<SlaPolicy, "id" | "entity_label" | "is_default">[]) =>
    request<SlaPolicy[]>("/sla-policies", { method: "PUT", body: JSON.stringify({ policies }) }),
  slaBreaches: () => request<TatSummary>("/sla-breaches"),

  // Risk-scenario library and asset-driven generation.
  riskScenarios: (qs = "limit=500") => request<Page<RiskScenario>>(`/risk-scenarios?${qs}`),
  assetKinds: () => request<AssetKind[]>("/risk-scenarios/asset-kinds"),
  createRiskScenario: (payload: Record<string, unknown>) =>
    request<RiskScenario>("/risk-scenarios", { method: "POST", body: JSON.stringify(payload) }),
  deleteRiskScenario: (id: string) =>
    request<void>(`/risk-scenarios/${id}`, { method: "DELETE" }),
  updateRiskScenario: (id: string, payload: Partial<RiskScenario>) =>
    request<RiskScenario>(`/risk-scenarios/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  installScenarioLibrary: () =>
    request<ScenarioInstallResult>("/risk-scenarios/install-library", { method: "POST" }),
  generateRisks: (payload: GenerateRisksRequest) =>
    request<GenerateRisksResponse>("/risk-scenarios/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  commitGeneratedRisks: (items: GeneratedRiskCommitItem[]) =>
    request<GenerateRisksCommitResult>("/risk-scenarios/commit", {
      method: "POST",
      body: JSON.stringify({ items }),
    }),

  // --- report builder ---
  reportSubjects: () => request<ReportSubject[]>("/report-builder/subjects"),
  runReport: (body: ReportDefinition & { limit: number; offset: number }) =>
    request<ReportRun>("/report-builder/run", { method: "POST", body: JSON.stringify(body) }),
  exportReport: (body: ReportDefinition, format: ReportFormat) =>
    downloadBlobPost(`/report-builder/export?format=${format}`, body, `report.${format}`),
  savedReports: () => request<Page<SavedReport>>("/report-builder/saved?limit=200"),
  createSavedReport: (body: { name: string; description?: string; subject: string; definition: Record<string, unknown>; shared: boolean }) =>
    request<SavedReport>("/report-builder/saved", { method: "POST", body: JSON.stringify(body) }),
  updateSavedReport: (id: string, body: Partial<{ name: string; description: string; definition: Record<string, unknown>; shared: boolean }>) =>
    request<SavedReport>(`/report-builder/saved/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSavedReport: (id: string) => request<void>(`/report-builder/saved/${id}`, { method: "DELETE" }),
  exportSavedReport: (id: string, format: ReportFormat, name: string) =>
    downloadBlob(`/report-builder/saved/${id}/export?format=${format}`, `${slugForFile(name)}.${format}`),

  requestAcceptance: (riskId: string, body: { rationale: string; expires_at?: string | null }) =>
    request<RiskAcceptance>(`/risks/${riskId}/acceptances`, { method: "POST", body: JSON.stringify(body) }),
  decideAcceptance: (riskId: string, acceptanceId: string, body: { approve: boolean; note?: string }) =>
    request<RiskAcceptance>(`/risks/${riskId}/acceptances/${acceptanceId}/decision`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  suggestedResidual: (riskId: string) =>
    request<SuggestedResidual>(`/risks/${riskId}/suggested-residual`),
  acceptResidual: (riskId: string, payload: { likelihood?: number; impact?: number; override_reason?: string }) =>
    request<Risk>(`/risks/${riskId}/accept-residual`, { method: "POST", body: JSON.stringify(payload) }),
  search: (q: string) => request<SearchResults>(`/search?q=${encodeURIComponent(q)}`),

  // AML/CFT
  amlScreening: () => request<Page<ScreeningCase>>("/aml/screening?limit=200"),
  createScreening: (p: Record<string, unknown>) =>
    request<ScreeningCase>("/aml/screening", { method: "POST", body: JSON.stringify(p) }),
  updateScreening: (id: string, p: Record<string, unknown>) =>
    request<ScreeningCase>(`/aml/screening/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteScreening: (id: string) => request<void>(`/aml/screening/${id}`, { method: "DELETE" }),
  screeningSummary: () => request<ScreeningSummary>("/aml/screening-summary"),
  amlSars: () => request<Page<Sar>>("/aml/sars?limit=200"),
  createSar: (p: Record<string, unknown>) =>
    request<Sar>("/aml/sars", { method: "POST", body: JSON.stringify(p) }),
  updateSar: (id: string, p: Record<string, unknown>) =>
    request<Sar>(`/aml/sars/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteSar: (id: string) => request<void>(`/aml/sars/${id}`, { method: "DELETE" }),
  amlRisks: () => request<Page<AmlRisk>>("/aml/risk-assessments?limit=200"),
  createAmlRisk: (p: Record<string, unknown>) =>
    request<AmlRisk>("/aml/risk-assessments", { method: "POST", body: JSON.stringify(p) }),
  updateAmlRisk: (id: string, p: Record<string, unknown>) =>
    request<AmlRisk>(`/aml/risk-assessments/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteAmlRisk: (id: string) => request<void>(`/aml/risk-assessments/${id}`, { method: "DELETE" }),

  // Operational risk — RCSA, KRIs, loss database
  rcsaList: () => request<Page<RcsaAssessment>>("/rcsa?limit=200"),
  rcsaGet: (id: string) => request<RcsaAssessment>(`/rcsa/${id}`),
  createRcsa: (p: Record<string, unknown>) =>
    request<RcsaAssessment>("/rcsa", { method: "POST", body: JSON.stringify(p) }),
  updateRcsa: (id: string, p: Record<string, unknown>) =>
    request<RcsaAssessment>(`/rcsa/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteRcsa: (id: string) => request<void>(`/rcsa/${id}`, { method: "DELETE" }),
  addRcsaRisk: (id: string, p: Record<string, unknown>) =>
    request<RcsaAssessment>(`/rcsa/${id}/risks`, { method: "POST", body: JSON.stringify(p) }),
  updateRcsaRisk: (lineId: string, p: Record<string, unknown>) =>
    request<RcsaRisk>(`/rcsa-risks/${lineId}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteRcsaRisk: (lineId: string) => request<void>(`/rcsa-risks/${lineId}`, { method: "DELETE" }),
  kris: () => request<Page<KeyRiskIndicator>>("/kris?limit=200"),
  kriEscalationRoles: () => request<{ id: string; name: string }[]>("/kri-escalation-roles"),
  createKriEscalation: (id: string, p: Record<string, unknown>) =>
    request<KriEscalation>(`/kris/${id}/escalations`, { method: "POST", body: JSON.stringify(p) }),
  updateKriEscalation: (id: string, escalationId: string, p: Record<string, unknown>) =>
    request<KriEscalation>(`/kris/${id}/escalations/${escalationId}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteKriEscalation: (id: string, escalationId: string) =>
    request<void>(`/kris/${id}/escalations/${escalationId}`, { method: "DELETE" }),
  issueKriFeedToken: (id: string) => request<KriFeedToken>(`/kris/${id}/feed-token`, { method: "POST" }),
  revokeKriFeedToken: (id: string) => request<void>(`/kris/${id}/feed-token`, { method: "DELETE" }),
  createKri: (p: Record<string, unknown>) =>
    request<KeyRiskIndicator>("/kris", { method: "POST", body: JSON.stringify(p) }),
  updateKri: (id: string, p: Record<string, unknown>) =>
    request<KeyRiskIndicator>(`/kris/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteKri: (id: string) => request<void>(`/kris/${id}`, { method: "DELETE" }),
  addKriMeasurement: (id: string, p: Record<string, unknown>) =>
    request<KeyRiskIndicator>(`/kris/${id}/measurements`, { method: "POST", body: JSON.stringify(p) }),
  lossEvents: () => request<Page<LossEvent>>("/loss-events?limit=200"),
  createLossEvent: (p: Record<string, unknown>) =>
    request<LossEvent>("/loss-events", { method: "POST", body: JSON.stringify(p) }),
  updateLossEvent: (id: string, p: Record<string, unknown>) =>
    request<LossEvent>(`/loss-events/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteLossEvent: (id: string) => request<void>(`/loss-events/${id}`, { method: "DELETE" }),
  lossSummary: () => request<LossSummary>("/loss-events-summary"),

  // PDF reports (board / audit-committee / Shariah-board packs)
  /** Exports exactly the scope the register is showing, so the PDF and the screen can
   *  never disagree. Undefined entries are dropped. `name` distinguishes the file on
   *  disk — pulling a report for ten assets should not produce ten "risk-register.pdf". */
  pdfRiskRegister: (scope?: RiskExportScope, name?: string) =>
    downloadBlob(
      `/reports/pdf/risk-register${queryString(scope)}`,
      name ? `risk-report-${slugForFile(name)}.pdf` : "risk-report.pdf",
    ),
  pdfExecutiveSummary: () => downloadBlob("/reports/pdf/executive-summary", "executive-summary.pdf"),
  pdfAuditEngagement: (id: string, ref: string) =>
    downloadBlob(`/reports/pdf/audit-engagement/${id}`, `audit-${ref}.pdf`),
  pdfShariahReview: (id: string, ref: string) =>
    downloadBlob(`/reports/pdf/shariah-review/${id}`, `shariah-${ref}.pdf`),

  // Internal Audit
  auditUnits: () => request<Page<AuditableUnit>>("/audit-universe?limit=200"),
  createAuditUnit: (payload: Record<string, unknown>) =>
    request<AuditableUnit>("/audit-universe", { method: "POST", body: JSON.stringify(payload) }),
  updateAuditUnit: (id: string, payload: Record<string, unknown>) =>
    request<AuditableUnit>(`/audit-universe/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAuditUnit: (id: string) => request<void>(`/audit-universe/${id}`, { method: "DELETE" }),

  auditEngagements: () => request<Page<AuditEngagement>>("/audit-engagements?limit=200"),
  assuranceSummary: () => request<AssuranceSummary>("/assurance-summary"),
  auditEngagement: (id: string) => request<AuditEngagement>(`/audit-engagements/${id}`),
  createAuditEngagement: (payload: Record<string, unknown>) =>
    request<AuditEngagement>("/audit-engagements", { method: "POST", body: JSON.stringify(payload) }),
  updateAuditEngagement: (id: string, payload: Record<string, unknown>) =>
    request<AuditEngagement>(`/audit-engagements/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAuditEngagement: (id: string) => request<void>(`/audit-engagements/${id}`, { method: "DELETE" }),
  addAuditProcedure: (eid: string, payload: Record<string, unknown>) =>
    request<AuditEngagement>(`/audit-engagements/${eid}/procedures`, { method: "POST", body: JSON.stringify(payload) }),
  updateAuditProcedure: (pid: string, payload: Record<string, unknown>) =>
    request<AuditProcedure>(`/audit-procedures/${pid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAuditProcedure: (pid: string) => request<void>(`/audit-procedures/${pid}`, { method: "DELETE" }),
  addAuditFinding: (eid: string, payload: Record<string, unknown>) =>
    request<AuditEngagement>(`/audit-engagements/${eid}/findings`, { method: "POST", body: JSON.stringify(payload) }),
  updateAuditFinding: (fid: string, payload: Record<string, unknown>) =>
    request<AuditFinding>(`/audit-findings/${fid}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteAuditFinding: (fid: string) => request<void>(`/audit-findings/${fid}`, { method: "DELETE" }),
  auditFindings: (params = "") => request<AuditFinding[]>(`/audit-findings${params}`),

  // Shariah governance
  shariahRulings: () => request<Page<ShariahRuling>>("/shariah-rulings?limit=200"),
  createShariahRuling: (p: Record<string, unknown>) =>
    request<ShariahRuling>("/shariah-rulings", { method: "POST", body: JSON.stringify(p) }),
  updateShariahRuling: (id: string, p: Record<string, unknown>) =>
    request<ShariahRuling>(`/shariah-rulings/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteShariahRuling: (id: string) => request<void>(`/shariah-rulings/${id}`, { method: "DELETE" }),
  islamicProducts: () => request<Page<IslamicProduct>>("/islamic-products?limit=200"),
  createIslamicProduct: (p: Record<string, unknown>) =>
    request<IslamicProduct>("/islamic-products", { method: "POST", body: JSON.stringify(p) }),
  updateIslamicProduct: (id: string, p: Record<string, unknown>) =>
    request<IslamicProduct>(`/islamic-products/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteIslamicProduct: (id: string) => request<void>(`/islamic-products/${id}`, { method: "DELETE" }),
  shariahReviews: () => request<Page<ShariahReview>>("/shariah-reviews?limit=200"),
  shariahReview: (id: string) => request<ShariahReview>(`/shariah-reviews/${id}`),
  createShariahReview: (p: Record<string, unknown>) =>
    request<ShariahReview>("/shariah-reviews", { method: "POST", body: JSON.stringify(p) }),
  updateShariahReview: (id: string, p: Record<string, unknown>) =>
    request<ShariahReview>(`/shariah-reviews/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteShariahReview: (id: string) => request<void>(`/shariah-reviews/${id}`, { method: "DELETE" }),
  addShariahFinding: (rid: string, p: Record<string, unknown>) =>
    request<ShariahReview>(`/shariah-reviews/${rid}/findings`, { method: "POST", body: JSON.stringify(p) }),
  updateShariahFinding: (fid: string, p: Record<string, unknown>) =>
    request<ShariahFinding>(`/shariah-findings/${fid}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteShariahFinding: (fid: string) => request<void>(`/shariah-findings/${fid}`, { method: "DELETE" }),
  charityLedger: () => request<Page<CharityDisbursement>>("/charity-ledger?limit=200"),
  createCharity: (p: Record<string, unknown>) =>
    request<CharityDisbursement>("/charity-ledger", { method: "POST", body: JSON.stringify(p) }),
  updateCharity: (id: string, p: Record<string, unknown>) =>
    request<CharityDisbursement>(`/charity-ledger/${id}`, { method: "PATCH", body: JSON.stringify(p) }),
  deleteCharity: (id: string) => request<void>(`/charity-ledger/${id}`, { method: "DELETE" }),

  evidence: () => request<Page<Evidence>>("/evidence"),
  createEvidence: (payload: Record<string, unknown>) =>
    request<Evidence>("/evidence", { method: "POST", body: JSON.stringify(payload) }),
  deleteEvidence: (id: string) =>
    request<void>(`/evidence/${id}`, { method: "DELETE" }),
  requirementEvidence: (id: string) =>
    request<Evidence[]>(`/requirements/${id}/evidence`),
  requirementCrosswalks: (id: string) =>
    request<CrosswalkItem[]>(`/requirements/${id}/crosswalks`),
  setCrosswalks: (id: string, related_requirement_ids: string[]) =>
    request<CrosswalkItem[]>(`/requirements/${id}/crosswalks`, {
      method: "PUT",
      body: JSON.stringify({ related_requirement_ids }),
    }),

  businessUnits: () => request<Page<BusinessUnit>>("/business-units"),
  createBusinessUnit: (payload: Record<string, unknown>) =>
    request<BusinessUnit>("/business-units", { method: "POST", body: JSON.stringify(payload) }),
  processes: () => request<Page<ProcessRow>>("/processes"),
  createProcess: (payload: Record<string, unknown>) =>
    request<ProcessRow>("/processes", { method: "POST", body: JSON.stringify(payload) }),
  legals: () => request<Page<Legal>>("/legals"),
  createLegal: (payload: Record<string, unknown>) =>
    request<Legal>("/legals", { method: "POST", body: JSON.stringify(payload) }),

  continuityPlans: () => request<Page<ContinuityPlan>>("/continuity-plans"),
  createContinuityPlan: (payload: Record<string, unknown>) =>
    request<ContinuityPlan>("/continuity-plans", { method: "POST", body: JSON.stringify(payload) }),
  addContinuityTask: (id: string, payload: Record<string, unknown>) =>
    request<ContinuityPlan>(`/continuity-plans/${id}/tasks`, { method: "POST", body: JSON.stringify(payload) }),
  recordContinuityTest: (id: string, payload: Record<string, unknown>) =>
    request<ContinuityPlan>(`/continuity-plans/${id}/tests`, { method: "POST", body: JSON.stringify(payload) }),

  ropa: () => request<Page<Ropa>>("/processing-activities"),
  createRopa: (payload: Record<string, unknown>) =>
    request<Ropa>("/processing-activities", { method: "POST", body: JSON.stringify(payload) }),
  updateRopa: (id: string, payload: Record<string, unknown>) =>
    request<Ropa>(`/processing-activities/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),

  accessReviews: () => request<Page<AccessReview>>("/access-reviews"),
  createAccessReview: (payload: Record<string, unknown>) =>
    request<AccessReview>("/access-reviews", { method: "POST", body: JSON.stringify(payload) }),
  addReviewItem: (id: string, payload: Record<string, unknown>) =>
    request<AccessReview>(`/access-reviews/${id}/items`, { method: "POST", body: JSON.stringify(payload) }),
  decideReviewItem: (id: string, itemId: string, payload: Record<string, unknown>) =>
    request<AccessReview>(`/access-reviews/${id}/items/${itemId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  completeAccessReview: (id: string) =>
    request<AccessReview>(`/access-reviews/${id}/complete`, { method: "POST" }),

  exceptions: () => request<Page<ExceptionRecord>>("/exceptions?limit=200"),
  createException: (payload: Record<string, unknown>) =>
    request<ExceptionRecord>("/exceptions", { method: "POST", body: JSON.stringify(payload) }),
  decideException: (id: string, approve: boolean, note = "") =>
    request<ExceptionRecord>(`/exceptions/${id}/decision`, {
      method: "POST",
      body: JSON.stringify({ approve, note }),
    }),
  closeException: (id: string) =>
    request<ExceptionRecord>(`/exceptions/${id}/close`, { method: "POST" }),

  projects: () => request<Page<Project>>("/projects?limit=200"),
  createProject: (payload: Record<string, unknown>) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  addTask: (id: string, payload: Record<string, unknown>) =>
    request<Project>(`/projects/${id}/tasks`, { method: "POST", body: JSON.stringify(payload) }),
  updateTask: (id: string, taskId: string, payload: Record<string, unknown>) =>
    request<Project>(`/projects/${id}/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  addExpense: (id: string, payload: Record<string, unknown>) =>
    request<Project>(`/projects/${id}/expenses`, { method: "POST", body: JSON.stringify(payload) }),

  goals: () => request<Page<Goal>>("/goals"),
  createGoal: (payload: Record<string, unknown>) =>
    request<Goal>("/goals", { method: "POST", body: JSON.stringify(payload) }),
  recordGoalAudit: (id: string, payload: Record<string, unknown>) =>
    request<Goal>(`/goals/${id}/audits`, { method: "POST", body: JSON.stringify(payload) }),

  threatCatalog: () => request<Page<CatalogItem>>("/threats?limit=500"),
  createThreat: (payload: Record<string, unknown>) =>
    request<CatalogItem>("/threats", { method: "POST", body: JSON.stringify(payload) }),
  vulnerabilityCatalog: () => request<Page<CatalogItem>>("/vulnerabilities?limit=500"),
  createVulnerability: (payload: Record<string, unknown>) =>
    request<CatalogItem>("/vulnerabilities", { method: "POST", body: JSON.stringify(payload) }),

  questionnaires: () => request<QuestionnaireSummary[]>("/questionnaires"),
  questionnaire: (id: string) => request<Questionnaire>(`/questionnaires/${id}`),
  createQuestionnaire: (payload: Record<string, unknown>) =>
    request<Questionnaire>("/questionnaires", { method: "POST", body: JSON.stringify(payload) }),
  assessments: () => request<AssessmentSummary[]>("/assessments"),
  assessment: (id: string) => request<Assessment>(`/assessments/${id}`),
  createAssessment: (payload: Record<string, unknown>) =>
    request<Assessment>("/assessments", { method: "POST", body: JSON.stringify(payload) }),
  submitAnswers: (id: string, answers: unknown[], submit = false) =>
    request<Assessment>(`/assessments/${id}/answers`, {
      method: "POST",
      body: JSON.stringify({ answers, submit }),
    }),
  addFinding: (id: string, payload: Record<string, unknown>) =>
    request<Assessment>(`/assessments/${id}/findings`, { method: "POST", body: JSON.stringify(payload) }),
  closeFinding: (id: string, fid: string) =>
    request<Assessment>(`/assessments/${id}/findings/${fid}/close`, { method: "POST" }),

  awarenessPrograms: () => request<AwarenessProgram[]>("/awareness-programs"),
  awarenessProgram: (id: string) => request<AwarenessProgram>(`/awareness-programs/${id}`),
  createAwarenessProgram: (payload: Record<string, unknown>) =>
    request<AwarenessProgram>("/awareness-programs", { method: "POST", body: JSON.stringify(payload) }),
  addParticipant: (id: string, payload: Record<string, unknown>) =>
    request<AwarenessProgram>(`/awareness-programs/${id}/participants`, { method: "POST", body: JSON.stringify(payload) }),
  submitQuiz: (id: string, pid: string, answers: Record<string, string>) =>
    request<AwarenessProgram>(`/awareness-programs/${id}/participants/${pid}/quiz`, { method: "POST", body: JSON.stringify({ answers }) }),
};
