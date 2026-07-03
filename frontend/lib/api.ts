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
export async function downloadBlob(path: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
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
  issued: string;
  expires: string;
  deployment: string;
  message: string;
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
  access_hash: string;
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
}
export interface NotificationList {
  items: Notification[];
  unseen_count: number;
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
export interface AuditEngagement {
  id: string;
  reference: string;
  title: string;
  scope: string;
  objectives: string;
  auditable_unit_id: string | null;
  lead_auditor: string;
  audit_team: string;
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
  attested_by_email: string;
  attested_at: string;
  comment: string;
  frequency: string;
  next_due: string | null;
  created_at: string;
}
export interface AttestationStatus {
  status: string;
  last_attested_at: string | null;
  last_by: string | null;
  next_due: string | null;
  frequency: string | null;
  history: Attestation[];
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
  total_requirements: number;
  compliant: number;
  compliant_pct: number;
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
  detected_at: string | null;
  resolved_at: string | null;
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
  systemHealth: () => request<SystemHealth>("/system/health"),
  listBackups: () => request<BackupItem[]>("/system/backups"),
  createBackup: () => request<BackupItem>("/system/backups", { method: "POST" }),
  downloadSupportBundle: () => downloadBlob("/system/support-bundle", "nexusline-support-bundle.zip"),
  risks: () => request<Page<Risk>>("/risks?limit=200"),
  dashboard: () => request<Dashboard>("/dashboard"),
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
  notifications: () => request<NotificationList>("/notifications"),
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
    request<CustomField[]>(`/custom-fields${model ? `?model=${model}` : ""}`),
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
  webhooks: () => request<Webhook[]>("/webhooks"),
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
    request<StatusRule[]>(`/status-rules${model ? `?model=${model}` : ""}`),
  createStatusRule: (payload: Record<string, unknown>) =>
    request<StatusRule>("/status-rules", { method: "POST", body: JSON.stringify(payload) }),
  deleteStatusRule: (id: string) => request<void>(`/status-rules/${id}`, { method: "DELETE" }),
  evaluateStatus: (model: string, ids: string[]) =>
    request<Record<string, StatusLabel[]>>(`/status-rules/evaluate/${model}`, { method: "POST", body: JSON.stringify({ ids }) }),
  attestation: (entityType: string, entityId: string) =>
    request<AttestationStatus>(`/attestations/${entityType}/${entityId}`),
  attest: (entityType: string, entityId: string, payload: Record<string, unknown>) =>
    request<AttestationStatus>(`/attestations/${entityType}/${entityId}`, { method: "POST", body: JSON.stringify(payload) }),
  filterFields: (model: string) => request<FieldInfo[]>(`/filters/fields/${model}`),
  filters: (model?: string) => request<SavedFilter[]>(`/filters${model ? `?model=${model}` : ""}`),
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
  riskAlerts: () => request<Risk[]>("/risk-alerts"),
  riskAggregate: () => request<RiskAggregate>("/risk-aggregate"),
  riskMatrix: () => request<RiskMatrix>("/risk-matrix"),
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
  pdfRiskRegister: () => downloadBlob("/reports/pdf/risk-register", "risk-register.pdf"),
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
