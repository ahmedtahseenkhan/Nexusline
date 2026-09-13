"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Fragment, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFilterParams, type FilterSpec } from "@/lib/useFilterParams";
import { useFormat } from "@/lib/format";
import { useHasPermission } from "@/lib/tenantSettings";
import { confirmDeleteWithImpact, WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";
import { deleteEach, deleteErrorText, toastDeleteSummary } from "@/lib/bulkDelete";
import { getSuggestedRequirements } from "@/lib/compliance";
import type { LookupRef, UserRef } from "@/lib/masterData";
import { safeLinkUrl } from "@/lib/sanitize";
import { plural, rowLabel, sentenceCase, textOnlyPerson } from "@/lib/record/text";
import type { PointAction } from "@/lib/record/types";
import {
  CONTROL_CLEAR_TEXT,
  CONTROL_LIFECYCLE_HINT,
  CONTROL_OPERATOR_HINT,
  CONTROL_OWNER_HINT,
  CONTROL_STATUS_TONE as STATUS_TONE,
  EFFECTIVENESS_BASIS_NOTE as BASIS_NOTE,
  EFFECTIVENESS_TONE as EFF_TONE,
  LIVE_STATUSES as LIVE,
  NO_MAINTENANCE_CLOCK,
  NO_TEST_CLOCK as NO_CLOCK_NOTE,
  RESULT_TONE,
  TESTS_REVIEW_NOTE,
  TEST_RESULT_LABEL as RESULT_LABEL,
  TEST_REVIEW_LABEL as REVIEW_LABEL,
  UNTESTABLE_STATUSES as UNTESTABLE,
  classificationText,
  combinedFromText,
  controlHeadline,
  controlLead,
  controlNextTest,
  controlOpenPoints,
  controlSourceMeta,
  controlTestTitle,
  controlTiles,
  cycleFact,
  descriptionDiffers,
  designClassification,
  effectivenessNote,
  exceptionMeta,
  isRated,
  issueCapText,
  latestCounting,
  maintenanceEmptyText,
  maintenanceSectionSub,
  ratingWord,
  testFromText,
  testsEmptyText,
  testsSectionSub,
  type ControlExceptionRef,
  type ControlInput,
  type ControlRequirementRef,
} from "@/lib/record/control";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import ArchivedRecords from "@/components/ArchivedRecords";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import { useCustomFieldFacts } from "@/components/CustomFieldsPanel";
import type { MenuItem } from "@/components/Menu";
import { BulkSuggestMappings } from "@/components/SuggestedClauses";
import BulkEditBar from "@/components/BulkEditBar";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText, { RichTextView } from "@/components/RichText";
import { Field, TextInput, TextArea, Select, NumberInput, Toggle, type Option } from "@/components/fields";
import { Badge, EffectivenessBadge, StatusBadge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import {
  Disclosure,
  Fact,
  FactGrid,
  FactList,
  OpenPoints,
  PrimaryAction,
  RecordIssuesSection,
  RecordSection,
  RelatedGroups,
  SectionNav,
  SuggestedClausesRow,
  SummaryBand,
  approvalHintFor,
  approvalMetaItem,
  relatedCount,
  rowAction,
  useRecordCtx,
  useRecordGovernanceData,
  useRecordSections,
  withBaseMoreItems,
  type FactItem,
  type PrimaryCandidate,
  type RecordIdentity,
  type RecordIssuesHandle,
  type RecordSectionsApi,
  type RelatedGroup,
} from "@/components/record";
import { titleCase } from "@/lib/text";

/* ---------------------------------------------------------------- inline types */
type LinkRef = { id: string; reference?: string; title?: string; name?: string };
/** A linked requirement. `framework` (name) and `framework_id` arrive with B7 (spec §3.6);
 *  until the API sends them they are absent and the page never guesses them. */
type RequirementRef = LinkRef & Pick<ControlRequirementRef, "framework" | "framework_id">;
/** A linked exception. `status` and `expires_at` arrive with B3. */
type ExceptionRef = LinkRef & Pick<ControlExceptionRef, "status" | "expires_at">;
type IsoAttributes = Partial<Record<IsoKey, string[]>>;
type Control = {
  id: string; name: string; reference: string; description: string; objective: string;
  /** Legacy free text ("CISO"); shown only while no owner is picked. */
  owner: string; owner_id: string | null; owner_ref: UserRef | null;
  operator_id: string | null; operator_ref: UserRef | null;
  /** Kept, demoted: "design" = a design artefact, "production" = an operating control. */
  control_type: string;
  nature: string | null; automation: string | null; is_key: boolean; operating_frequency: string | null;
  iso27002_attributes: IsoAttributes; test_procedure: string; evidence_expected: string;
  /** Legacy free text, kept in step with the picked classification. */
  classification: string; classification_id: string | null; classification_ref: (LookupRef & { path?: string }) | null;
  documentation_url: string; status: string;
  /** The combined rating the rest of the app reads — derived, or an override with a reason. */
  effectiveness: string; design_effectiveness: string; operating_effectiveness: string;
  effectiveness_override_reason: string;
  /** tests | override | manual (rated by hand before derivation) | none */
  effectiveness_basis: string;
  open_issues: LinkRef[]; pending_review_count: number;
  business_units: LinkRef[]; processes: LinkRef[];
  /** Read-only: moved only through WorkflowFields. */
  workflow_status: string; opex: number | null; capex: number | null; resource_utilization: number | null;
  audit_frequency: string; audit_metric: string; audit_success_criteria: string; maintenance_frequency: string;
  next_audit_date: string | null; last_audit_date: string | null; next_maintenance_date: string | null;
  last_maintenance_date: string | null; audit_count: number; last_audit_result: string | null; is_audit_overdue: boolean;
  maintenance_count: number; last_maintenance_result: string | null; is_maintenance_overdue: boolean;
  policies: LinkRef[]; requirements: RequirementRef[]; risks: LinkRef[];
  // reverse graph links (read-only, from GET /controls/{id})
  assets?: LinkRef[]; vendors?: LinkRef[];
  incidents?: LinkRef[]; exceptions?: ExceptionRef[]; projects?: LinkRef[]; audit_findings?: LinkRef[];
};
/** A control test workpaper (backend: ControlAuditRead). */
type ControlTest = {
  id: string; result: string; test_type: string | null;
  planned_date: string | null; conducted_date: string | null;
  period_start: string | null; period_end: string | null;
  population_size: number | null; sample_size: number | null; sample_method: string;
  exceptions_count: number; exceptions_detail: string;
  metric_description: string; success_criteria: string; conclusion: string; result_description: string; improvement: string;
  /** The tester's name as text (legacy, kept equal to the picked tester's name). */
  auditor: string; tested_by_id?: string | null; tested_by_ref?: UserRef | null;
  /** pending | reviewed | returned | legacy (recorded before reviews existed) */
  review_status: string; reviewed_by_ref?: UserRef | null; reviewed_at: string | null; review_note: string;
  raised_issue: LinkRef | null; evidence: LinkRef[];
  can_review: boolean; review_blocked_reason: string; can_edit: boolean;
  created_at: string;
};
type ControlMaintenance = { id: string; result: string; task: string; conducted_date: string | null };

/* ----------------------------------------------------------------- enum options */
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const labelled = (m: Record<string, string>): Option[] => Object.entries(m).map(([value, label]) => ({ value, label }));
/** `control_type` is kept in the data but is no longer the primary classification. */
const CONTROL_TYPE_LABEL: Record<string, string> = { design: "Design artefact", production: "Operating control" };
const NATURE_LABEL: Record<string, string> = { preventive: "Preventive", detective: "Detective", corrective: "Corrective", directive: "Directive" };
const AUTOMATION_LABEL: Record<string, string> = { manual: "Manual", it_dependent_manual: "IT-dependent manual", automated: "Automated" };
const OP_FREQ_LABEL: Record<string, string> = {
  continuous: "Continuous", daily: "Daily", weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly",
  semiannual: "Twice a year", annual: "Annually", per_event: "Per event", ad_hoc: "Ad hoc",
};
const STATUS = opts(["planned", "implemented", "operational", "retired"]);
const EFFECTIVENESS = opts(["ineffective", "partially_effective", "effective"]);
/** ISO/IEC 27002:2022 attribute vocabulary (backend: schemas/control.py ISO27002_VOCABULARY). */
type IsoKey = "control_type" | "security_properties" | "cybersecurity_concepts" | "operational_capabilities" | "security_domains";
const ISO_ATTRS: { key: IsoKey; label: string; values: string[] }[] = [
  { key: "control_type", label: "Control type", values: ["preventive", "detective", "corrective"] },
  { key: "security_properties", label: "Information security properties", values: ["confidentiality", "integrity", "availability"] },
  { key: "cybersecurity_concepts", label: "Cybersecurity concepts", values: ["identify", "protect", "detect", "respond", "recover"] },
  {
    key: "operational_capabilities", label: "Operational capabilities", values: [
      "governance", "asset_management", "information_protection", "human_resource_security", "physical_security",
      "system_and_network_security", "application_security", "secure_configuration", "identity_and_access_management",
      "threat_and_vulnerability_management", "continuity", "supplier_relationships_security", "legal_and_compliance",
      "information_security_event_management", "information_security_assurance",
    ],
  },
  { key: "security_domains", label: "Security domains", values: ["governance_and_ecosystem", "protection", "defence", "resilience"] },
];
const isoText = (v: string) => cap(v).replace(/\bAnd\b/g, "and");
const isoCount = (a: IsoAttributes | undefined) => Object.values(a ?? {}).reduce((n, v) => n + (v?.length ?? 0), 0);
const workflowLabel = (s: string) => WORKFLOW_STATE_LABEL[s as WorkflowStateKey] ?? cap(s);
const personText = (u: UserRef | null | undefined, fallback?: string) => (u ? u.full_name || u.email : fallback || "");
const FREQ = opts(["none", "fortnightly", "monthly", "quarterly", "semiannual", "annual"]);
/** Local calendar date as YYYY-MM-DD (toISOString would give the UTC date). */
const today = () => new Date().toLocaleDateString("en-CA");
function ResultBadge({ value }: { value: string | null }) {
  if (!value || value === "not_assessed") return <Badge hollow asIs>Not assessed</Badge>;
  return <Badge tone={RESULT_TONE[value] || "neutral"} asIs>{RESULT_LABEL[value] ?? sentenceCase(value)}</Badge>;
}
const REVIEW_TONE: Record<string, "low" | "medium" | "high" | "neutral" | "info"> = { pending: "info", reviewed: "low", returned: "high", legacy: "neutral" };
const SAMPLE_METHOD = labelled({
  random: "Random", systematic: "Systematic (every nth)", judgemental: "Judgemental", haphazard: "Haphazard",
  block: "Block", full_population: "Full population",
});
const EVIDENCE_TYPES = opts(["document", "screenshot", "log", "link", "configuration", "other"]);
const refToOpt = (x: LinkRef): AsyncOption => ({ value: x.id, label: x.reference || x.title || x.name || x.id });

/* ------------------------------------------------------------- register filters */
/** Filters in the URL, so the dashboard can open this list already filtered
 *  (`/controls?assurance=not_assessed`, `?test=overdue`). Same predicates on the server
 *  as the dashboard's counts (services/drill_through.py). */
const CONTROL_FILTERS = {
  assurance: ["assured", "effective", "partially_effective", "failing", "not_assessed", "not_operating", "unmapped"],
  test: ["overdue", "due_30d", "failed"],
  key: "boolean",
} as const satisfies FilterSpec;
const ASSURANCE_LABEL: Record<(typeof CONTROL_FILTERS.assurance)[number], string> = {
  assured: "Assured (effective or partially)",
  effective: "Effective",
  partially_effective: "Partially effective",
  failing: "Failing (ineffective)",
  not_assessed: "Never tested",
  not_operating: "Planned or retired",
  unmapped: "Not mapped to any clause",
};
const TEST_LABEL: Record<(typeof CONTROL_FILTERS.test)[number], string> = {
  overdue: "Test overdue",
  due_30d: "Test due in 30 days",
  failed: "Failed its last test",
};

/* ------------------------------------------------------------------- form state */
type FormState = {
  name: string; reference: string; objective: string; description: string;
  owner_id: string | null; operator_id: string | null; control_type: string;
  nature: string; automation: string; is_key: boolean; operating_frequency: string;
  iso27002_attributes: IsoAttributes; test_procedure: string; evidence_expected: string;
  business_unit_ids: AsyncOption[]; process_ids: AsyncOption[];
  classification_id: string | null; documentation_url: string; status: string;
  opex: number | ""; capex: number | ""; resource_utilization: number | ""; audit_frequency: string;
  audit_metric: string; audit_success_criteria: string; next_audit_date: string; maintenance_frequency: string;
  next_maintenance_date: string; policy_ids: AsyncOption[]; requirement_ids: AsyncOption[]; risk_ids: AsyncOption[]; asset_ids: AsyncOption[];
};
const BLANK: FormState = {
  name: "", reference: "", objective: "", description: "", owner_id: null, operator_id: null, control_type: "production",
  nature: "", automation: "", is_key: false, operating_frequency: "", iso27002_attributes: {}, test_procedure: "",
  evidence_expected: "", business_unit_ids: [], process_ids: [],
  classification_id: null, documentation_url: "", status: "planned", opex: "", capex: "",
  resource_utilization: "", audit_frequency: "annual", audit_metric: "", audit_success_criteria: "", next_audit_date: "",
  maintenance_frequency: "quarterly", next_maintenance_date: "", policy_ids: [], requirement_ids: [], risk_ids: [], asset_ids: [],
};
function fromControl(c: Control): FormState {
  return {
    name: c.name, reference: c.reference || "", objective: c.objective || "", description: c.description || "",
    owner_id: c.owner_id ?? null, operator_id: c.operator_id ?? null, control_type: c.control_type,
    nature: c.nature ?? "", automation: c.automation ?? "", is_key: !!c.is_key, operating_frequency: c.operating_frequency ?? "",
    iso27002_attributes: c.iso27002_attributes ?? {}, test_procedure: c.test_procedure || "", evidence_expected: c.evidence_expected || "",
    business_unit_ids: (c.business_units ?? []).map(refToOpt), process_ids: (c.processes ?? []).map(refToOpt),
    classification_id: c.classification_id ?? null,
    documentation_url: c.documentation_url || "", status: c.status,
    opex: c.opex ?? "", capex: c.capex ?? "", resource_utilization: c.resource_utilization ?? "",
    audit_frequency: c.audit_frequency, audit_metric: c.audit_metric || "", audit_success_criteria: c.audit_success_criteria || "",
    next_audit_date: c.next_audit_date || "", maintenance_frequency: c.maintenance_frequency, next_maintenance_date: c.next_maintenance_date || "",
    policy_ids: c.policies.map(refToOpt), requirement_ids: c.requirements.map(refToOpt), risk_ids: c.risks.map(refToOpt),
    asset_ids: (c.assets ?? []).map(refToOpt),
  };
}
/** Effectiveness is not sent: it is derived, and set by hand only through "Override". */
function toPayload(f: FormState) {
  return {
    name: f.name, reference: f.reference, objective: f.objective, description: f.description,
    owner_id: f.owner_id, operator_id: f.operator_id,
    control_type: f.control_type, classification_id: f.classification_id, documentation_url: f.documentation_url,
    status: f.status,
    nature: f.nature || null, automation: f.automation || null, is_key: f.is_key,
    operating_frequency: f.operating_frequency || null, iso27002_attributes: f.iso27002_attributes,
    test_procedure: f.test_procedure, evidence_expected: f.evidence_expected,
    business_unit_ids: f.business_unit_ids.map((o) => o.value), process_ids: f.process_ids.map((o) => o.value),
    opex: f.opex === "" ? null : f.opex, capex: f.capex === "" ? null : f.capex,
    resource_utilization: f.resource_utilization === "" ? null : f.resource_utilization,
    audit_frequency: f.audit_frequency, audit_metric: f.audit_metric, audit_success_criteria: f.audit_success_criteria,
    next_audit_date: f.next_audit_date || null, maintenance_frequency: f.maintenance_frequency,
    next_maintenance_date: f.next_maintenance_date || null,
    policy_ids: f.policy_ids.map((o) => o.value), requirement_ids: f.requirement_ids.map((o) => o.value), risk_ids: f.risk_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
  };
}

/** ISO 27002 attribute chips: click a value to toggle it. */
function IsoAttributeChips({ value, onChange }: { value: IsoAttributes; onChange: (v: IsoAttributes) => void }) {
  const toggle = (key: IsoKey, v: string) => {
    const cur = value[key] ?? [];
    const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
    const order = ISO_ATTRS.find((a) => a.key === key)!.values;
    onChange({ ...value, [key]: order.filter((x) => next.includes(x)) });
  };
  return (
    <div style={{ display: "grid", gap: 10 }}>
      {ISO_ATTRS.map((a) => (
        <div key={a.key}>
          <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{a.label}</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {a.values.map((v) => {
              const on = (value[a.key] ?? []).includes(v);
              return (
                <button key={v} type="button" aria-pressed={on} onClick={() => toggle(a.key, v)}
                  className="chip"
                  style={on ? { border: "1px solid var(--primary)", cursor: "pointer" } : { background: "transparent", border: "1px dashed var(--border-strong)", color: "var(--muted)", cursor: "pointer" }}>
                  {on ? "✓ " : ""}{isoText(v)}
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Read-only ISO 27002 attributes for the drawer. */
function IsoAttributeList({ value }: { value: IsoAttributes | undefined }) {
  if (!isoCount(value)) return null;
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {ISO_ATTRS.filter((a) => (value?.[a.key] ?? []).length).map((a) => (
        <div key={a.key} style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
          <span className="muted" style={{ fontSize: 12, minWidth: 170 }}>{a.label}</span>
          <span style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {(value?.[a.key] ?? []).map((v) => <span key={v} className="chip">#{isoText(v).replace(/ /g, "_")}</span>)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ test workpaper form */
type NewEvidence = { title: string; evidence_type: string; reference: string };
type TestForm = {
  result: string; test_type: string; conducted_date: string; period_start: string; period_end: string;
  population_size: number | ""; sample_size: number | ""; sample_method: string;
  exceptions_count: number | ""; exceptions_detail: string;
  metric_description: string; success_criteria: string; conclusion: string; improvement: string;
  tested_by: UserRef | null; evidence_ids: AsyncOption[]; new_evidence: NewEvidence[];
};
function blankTest(c: Control): TestForm {
  const procedure = [c.test_procedure, c.audit_metric ? `Metric: ${c.audit_metric}` : ""].filter(Boolean).join("\n\n");
  return {
    result: "", test_type: c.control_type === "design" ? "design" : "operating", conducted_date: "", period_start: "", period_end: "",
    population_size: "", sample_size: "", sample_method: "", exceptions_count: "", exceptions_detail: "",
    metric_description: procedure, success_criteria: c.audit_success_criteria || "", conclusion: "", improvement: "",
    tested_by: null, evidence_ids: [], new_evidence: [],
  };
}
function testFormOf(t: ControlTest): TestForm {
  return {
    result: t.result === "not_assessed" ? "" : t.result, test_type: t.test_type || "operating",
    conducted_date: t.conducted_date || "", period_start: t.period_start || "", period_end: t.period_end || "",
    population_size: t.population_size ?? "", sample_size: t.sample_size ?? "", sample_method: t.sample_method || "",
    exceptions_count: t.exceptions_count || "", exceptions_detail: t.exceptions_detail || "",
    metric_description: t.metric_description || "", success_criteria: t.success_criteria || "",
    conclusion: t.conclusion || t.result_description || "", improvement: t.improvement || "",
    tested_by: t.tested_by_ref ?? null, evidence_ids: t.evidence.map(refToOpt), new_evidence: [],
  };
}
/** What still stops the workpaper being recorded (mirrors the server's rules). */
function testProblems(t: TestForm): string[] {
  const out: string[] = [];
  if (!t.result) out.push("choose the result");
  if (!t.test_type) out.push("say whether it was a design or an operating test");
  if (!t.conducted_date) out.push("give the date it was performed");
  if (t.test_type === "operating" && (!t.period_start || !t.period_end)) out.push("give the period the operating test covers");
  if (t.period_start && t.period_end && t.period_start > t.period_end) out.push("the period must start before it ends");
  if (t.sample_size !== "" && t.population_size !== "" && Number(t.sample_size) > Number(t.population_size)) out.push("the sample cannot be larger than the population");
  if (t.result === "passed_with_exceptions" && !(Number(t.exceptions_count) >= 1)) out.push("record how many exceptions were found");
  if (!t.conclusion.trim()) out.push("write the conclusion");
  if (t.evidence_ids.length + t.new_evidence.filter((e) => e.title.trim()).length < 1) out.push("attach or add at least one evidence item");
  return out;
}
function testPayload(t: TestForm) {
  const num = (v: number | "") => (v === "" ? null : Number(v));
  return {
    result: t.result, test_type: t.test_type, conducted_date: t.conducted_date || null,
    period_start: t.period_start || null, period_end: t.period_end || null,
    population_size: num(t.population_size), sample_size: num(t.sample_size), sample_method: t.sample_method,
    exceptions_count: t.exceptions_count === "" ? 0 : Number(t.exceptions_count), exceptions_detail: t.exceptions_detail,
    metric_description: t.metric_description, success_criteria: t.success_criteria,
    conclusion: t.conclusion.trim(), improvement: t.improvement,
    tested_by_id: t.tested_by?.id ?? null,
    // The legacy text column, kept for display compatibility with older readers.
    auditor: t.tested_by ? t.tested_by.full_name || t.tested_by.email : "",
    evidence_ids: t.evidence_ids.map((o) => o.value),
    new_evidence: t.new_evidence.filter((e) => e.title.trim()).map((e) => ({ ...e, title: e.title.trim() })),
  };
}

/* ================================================================ page ===== */
/* Every judgement the record states in words — headline, tiles, open points and the
   copy around them — comes from lib/record/control.ts (record-page-spec §4.2, §3.8). */

/** Hands the drawer's section scroller (which also moves the nav highlight) to handlers
 *  that live on the page, outside the drawer's provider. */
function SectionsBridge({ apiRef }: { apiRef: { current: RecordSectionsApi | null } }) {
  const api = useRecordSections();
  useEffect(() => {
    apiRef.current = api;
    return () => { if (apiRef.current === api) apiRef.current = null; };
  }, [api, apiRef]);
  return null;
}

function ControlsInner() {
  const router = useRouter();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Control | null>(null);
  const [tests, setTests] = useState<ControlTest[]>([]);
  const [maints, setMaints] = useState<ControlMaintenance[]>([]);
  /** Suggested clauses from the installed frameworks; null until known. */
  const [suggestionCount, setSuggestionCount] = useState<number | null>(null);
  /** The suggestion engine failed for the open control (distinct from "not loaded yet"). */
  const [suggestionFailed, setSuggestionFailed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const { currency, formatDate, formatDateTime, formatMoney } = useFormat();
  const canTest = useHasPermission("control:test");
  const canWrite = useHasPermission("control:write");
  const canRaiseIssue = useHasPermission("issue:write");

  // The record page (dossier): shared governance, the derivation context, sections, custom fields.
  const gov = useRecordGovernanceData("control", detail?.id ?? null, { statusRulesModel: "control" });
  const ctx = useRecordCtx(gov, canWrite);
  const pageSections = useRecordSections();
  const drawerSections = useRef<RecordSectionsApi | null>(null);
  /** Scroll to a record section (focuses its heading, writes `#id`, moves the nav highlight). */
  const sections = { scrollTo: (id: string) => (drawerSections.current ?? pageSections).scrollTo(id) };
  const cf = useCustomFieldFacts("control", detail?.id, { builtInLabels: ["Owner", "Operator", "Classification", "Status"] });

  const [editing, setEditing] = useState<Control | null>(null);
  const [editTab, setEditTab] = useState<string | undefined>(undefined);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // "Record test" modal: the workpaper, and the test being edited (a returned/pending one).
  const [testForm, setTestForm] = useState<TestForm | null>(null);
  const [editingTest, setEditingTest] = useState<ControlTest | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [testSaving, setTestSaving] = useState(false);
  const setT = <K extends keyof TestForm>(k: K, v: TestForm[K]) => setTestForm((p) => (p ? { ...p, [k]: v } : p));
  // Inline review of one pending test.
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  // Effectiveness override.
  const [override, setOverride] = useState<{ effectiveness: string; reason: string } | null>(null);
  const [overrideError, setOverrideError] = useState<string | null>(null);

  // Forms on demand inside the record: maintenance, suggested clauses (raise issue lives in RecordIssuesSection).
  const [maintOpen, setMaintOpen] = useState(false);
  const [maintResult, setMaintResult] = useState("passed");
  const [maintTask, setMaintTask] = useState("");
  const [maintError, setMaintError] = useState<string | null>(null);
  const [maintSaving, setMaintSaving] = useState(false);
  const maintTrigger = useRef<HTMLButtonElement>(null);
  /** The shared Issues section (decision D6): More › "Raise issue…" opens its form. */
  const issuesRef = useRef<RecordIssuesHandle>(null);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const loadSeq = useRef(0);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const filters = useFilterParams(CONTROL_FILTERS);
  // Register bulk action "Suggest mappings": the selected control ids under review.
  const [suggestFor, setSuggestFor] = useState<string[] | null>(null);
  const fetchControls = useCallback((qs: string) => apiCall<PagedList<Control>>("GET", `/controls?${qs}`), []);

  /** The control with its tests and maintenance log, set together so the summary never
   *  reads a control against another control's tests. (Its issues list is RecordIssuesSection's.) */
  const loadDetail = useCallback((id: string) => {
    const seq = ++loadSeq.current;
    Promise.all([
      apiCall<Control>("GET", `/controls/${id}`),
      apiCall<ControlTest[]>("GET", `/controls/${id}/audits`).catch(() => [] as ControlTest[]),
      apiCall<ControlMaintenance[]>("GET", `/controls/${id}/maintenances`).catch(() => [] as ControlMaintenance[]),
    ])
      .then(([c, a, m]) => {
        if (seq !== loadSeq.current) return;
        setDetail(c); setTests(a); setMaints(m);
      })
      .catch(() => { if (seq === loadSeq.current) setDetail(null); });
    loadSuggestions(id, seq);
  }, []);
  /** The suggested-clause count for the open control; a failure is kept apart from "not
   *  loaded yet" so the Linked records section can say so and offer Retry. */
  function loadSuggestions(id: string, seq = loadSeq.current) {
    setSuggestionFailed(false);
    getSuggestedRequirements(id)
      .then((rows) => { if (seq === loadSeq.current) setSuggestionCount(rows.length); })
      .catch(() => { if (seq === loadSeq.current) { setSuggestionCount(null); setSuggestionFailed(true); } });
  }
  useEffect(() => {
    if (openId) loadDetail(openId);
    else { loadSeq.current++; setDetail(null); setTests([]); setMaints([]); }
    setReviewing(null); setExpanded(null); setSuggestionCount(null); setSuggestionFailed(false);
    setMaintOpen(false); setMaintError(null); setSuggestOpen(false);
  }, [openId, loadDetail]);

  /** After any change to the open control: its sign-off state, the record and the list. */
  function refreshOpen() {
    void gov.reload();
    if (openId) loadDetail(openId);
    reload();
  }

  // server typeahead pickers
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((p) => ({ value: p.id, label: p.title, sub: p.reference })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((a) => ({ value: a.id, label: a.name })));
  const searchNamed = (path: string) => (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/${path}?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name })));
  /** This control's evidence not yet supporting another test. */
  const searchTestEvidence = (q: string) => detail
    ? apiCall<PagedList<{ id: string; title: string; evidence_type: string; control_audit_id: string | null }>>("GET", `/evidence?control_id=${detail.id}&unattached=true&search=${encodeURIComponent(q)}&limit=20`)
      .then((r) => r.items.map((e) => ({ value: e.id, label: e.title, sub: cap(e.evidence_type) })))
    : Promise.resolve([]);


  function openNew() { setEditing(null); setF(BLANK); setError(null); setEditTab(undefined); setShowForm(true); }
  /** Edit, optionally on the tab a fix names ("general", "attributes", "audit", "links"). */
  function openEdit(c: Control, tab?: string) { setEditing(c); setF(fromControl(c)); setError(null); setEditTab(tab); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Control>("PATCH", `/controls/${editing.id}`, payload);
      else await apiCall<Control>("POST", "/controls", payload);
      setShowForm(false); refreshOpen(); toast(editing ? "Changes saved" : "Control created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save control"); }
    finally { setSaving(false); }
  }
  async function remove(c: Control) {
    if (!(await confirmDeleteWithImpact("control", c.id, c.reference ? `${c.reference} — ${c.name}` : c.name))) return;
    try {
      await apiCall<unknown>("DELETE", `/controls/${c.id}`);
      if (openId === c.id) setOpenId(null);
      reload(); toast(`Archived ${c.reference || c.name}`);
    } catch (e) { toast(deleteErrorText(e, "Failed to delete the control"), "error"); }
  }

  /* ---- tests ---- */
  function openRecordTest() { if (!detail) return; setEditingTest(null); setTestForm(blankTest(detail)); setTestError(null); }
  function openEditTest(t: ControlTest) { setEditingTest(t); setTestForm(testFormOf(t)); setTestError(null); }
  async function saveTest() {
    if (!detail || !testForm) return;
    const problems = testProblems(testForm);
    if (problems.length) { setTestError(`Before recording: ${problems.join("; ")}.`); return; }
    setTestError(null); setTestSaving(true);
    try {
      const payload = testPayload(testForm);
      if (editingTest) await apiCall<Control>("PUT", `/controls/${detail.id}/audits/${editingTest.id}`, payload);
      else await apiCall<Control>("POST", `/controls/${detail.id}/audits`, payload);
      setTestForm(null); setEditingTest(null);
      refreshOpen();
      toast(editingTest ? "Test resubmitted for review" : "Test recorded — it now needs an independent review");
    } catch (e) { setTestError(e instanceof Error ? e.message : "Failed to record the test"); }
    finally { setTestSaving(false); }
  }
  async function decide(t: ControlTest, decision: "approve" | "return") {
    if (!detail) return;
    if (decision === "return" && !reviewNote.trim()) { toast("Say what the tester needs to fix", "error"); return; }
    try {
      await apiCall<Control>("POST", `/controls/${detail.id}/audits/${t.id}/review`, { decision, note: reviewNote.trim() });
      setReviewing(null); setReviewNote("");
      refreshOpen();
      toast(decision === "approve"
        ? (t.result === "failed" || t.result === "passed_with_exceptions" ? "Test approved — an issue was raised" : "Test approved")
        : "Test returned to the tester");
    } catch (e) { toast(e instanceof Error ? e.message : "Failed to record the review", "error"); }
  }
  /** Close the inline review of one test and put focus back on its Review button. */
  function closeReview(testId: string) {
    setReviewing(null);
    requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(`[data-review-btn="${testId}"]`)?.focus());
  }

  /* ---- effectiveness override ---- */
  function openOverride() {
    if (!detail) return;
    setOverride({ effectiveness: detail.effectiveness === "not_assessed" ? "" : detail.effectiveness, reason: "" });
    setOverrideError(null);
  }
  async function saveOverride() {
    if (!detail || !override) return;
    if (!override.effectiveness || !override.reason.trim()) { setOverrideError("Choose the rating and give the reason."); return; }
    try {
      await apiCall<Control>("POST", `/controls/${detail.id}/effectiveness-override`, { effectiveness: override.effectiveness, reason: override.reason.trim() });
      setOverride(null); refreshOpen(); toast("Effectiveness overridden");
    } catch (e) { setOverrideError(e instanceof Error ? e.message : "Failed to override"); }
  }
  async function dropOverride() {
    if (!detail) return;
    const ok = await confirmDialog({
      title: "Drop the override?",
      message: "The effectiveness goes back to what the reviewed tests say (not assessed if there are none).",
      confirmLabel: "Drop override",
    });
    if (!ok) return;
    try {
      await apiCall<Control>("DELETE", `/controls/${detail.id}/effectiveness-override`);
      refreshOpen(); toast("Override dropped");
    } catch (e) { toast(e instanceof Error ? e.message : "Failed to drop the override", "error"); }
  }

  /* ---- maintenance, issues and suggested clauses (forms on demand) ---- */
  function openMaintenance() { sections.scrollTo("maintenance"); setMaintError(null); setMaintOpen(true); }
  async function recordMaintenance(close: () => void) {
    if (!detail) return;
    setMaintError(null); setMaintSaving(true);
    try {
      await apiCall<Control>("POST", `/controls/${detail.id}/maintenances`, { result: maintResult, task: maintTask });
      setMaintTask(""); close(); refreshOpen(); toast("Maintenance recorded");
    } catch (e) { setMaintError(e instanceof Error ? e.message : "Failed to record maintenance"); }
    finally { setMaintSaving(false); }
  }
  /** More › "Raise issue…": the shared Issues section scrolls into view and opens its form. */
  function openRaise() { issuesRef.current?.raise(); }
  function openSuggestions() { sections.scrollTo("linked"); setSuggestOpen(true); }
  /** A form in a section that folds to one line when empty unmounts as it closes, so put
   *  focus back on its trigger (the section-head button, which stays) ourselves. */
  function closeOrOpen(setOpen: (v: boolean) => void, trigger: { current: HTMLButtonElement | null }, open: boolean) {
    setOpen(open);
    if (!open) requestAnimationFrame(() => trigger.current?.focus());
  }

  /** Openers the open points may name ("open" actions); absent = the viewer can't use it. */
  const openers: Record<string, (() => void) | undefined> = {
    "record-test": canTest ? openRecordTest : undefined,
    "record-maintenance": canWrite ? openMaintenance : undefined,
    "suggest-clauses": canWrite ? openSuggestions : undefined,
  };
  /** Whether this viewer can follow a fix; points keep their text either way. */
  function canFollow(a: PointAction): boolean {
    if (a.kind === "edit") return canWrite;
    if (a.kind === "open") return !!openers[a.target];
    if (a.kind === "attest") return gov.attestation?.can_attest !== false;
    return true;
  }
  function handlePoint(a: PointAction) {
    if (!detail) return;
    if (a.kind === "section") sections.scrollTo(a.target);
    else if (a.kind === "edit") openEdit(detail, a.target);
    else if (a.kind === "focus") document.getElementById(a.target)?.focus();
    else if (a.kind === "href") router.push(a.target);
    else if (a.kind === "attest") gov.openAttest();
    else if (a.kind === "open") openers[a.target]?.();
  }

  /* Inline relation chips linking to each record's own page. */
  const labelOf = (x: { id: string; label?: string; name?: string; title?: string; reference?: string }) =>
    x.label || x.name || x.title || x.reference || x.id;
  const linkChips = (items: { id: string; label?: string; name?: string; title?: string; reference?: string }[] | undefined, href: string) =>
    items && items.length ? (
      <div className="chips" onClick={(e) => e.stopPropagation()}>
        {items.map((x) => <Link key={x.id} className="chip" href={`${href}?id=${x.id}`}>{labelOf(x)}</Link>)}
      </div>
    ) : <span className="muted">—</span>;
  const names = (items: { id: string; label?: string; name?: string; title?: string; reference?: string }[] | undefined) =>
    (items ?? []).map(labelOf).join(", ");
  const effText = (c: Control) => cap(c.effectiveness) + (c.effectiveness_basis === "override" ? " (override)" : "");

  const columns: Column<Control>[] = [
    { key: "reference", header: "Ref", sortable: true, locked: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, locked: true, render: (c) => <span className="cell-title">{c.name}{c.is_key && <> <Badge tone="info" plain>Key</Badge></>}</span>, text: (c) => c.name },
    { key: "nature", header: "Nature", sortable: true, render: (c) => <span className="muted">{c.nature ? NATURE_LABEL[c.nature] : "—"}</span>, text: (c) => (c.nature ? NATURE_LABEL[c.nature] : "") },
    { key: "automation", header: "Automation", sortable: true, hidden: true, render: (c) => <span className="muted">{c.automation ? AUTOMATION_LABEL[c.automation] : "—"}</span>, text: (c) => (c.automation ? AUTOMATION_LABEL[c.automation] : "") },
    { key: "is_key", header: "Key control", sortable: true, hidden: true, render: (c) => (c.is_key ? <Badge tone="info">Key</Badge> : <span className="muted">—</span>), text: (c) => (c.is_key ? "Yes" : "No") },
    { key: "operating_frequency", header: "Operates", sortable: true, hidden: true, render: (c) => <span className="muted">{c.operating_frequency ? OP_FREQ_LABEL[c.operating_frequency] : "—"}</span>, text: (c) => (c.operating_frequency ? OP_FREQ_LABEL[c.operating_frequency] : "") },
    { key: "control_type", header: "Artefact / operating", hidden: true, render: (c) => <span className="muted">{CONTROL_TYPE_LABEL[c.control_type] ?? cap(c.control_type)}</span>, text: (c) => CONTROL_TYPE_LABEL[c.control_type] ?? cap(c.control_type) },
    { key: "status", header: "Status", sortable: true, render: (c) => <StatusBadge value={c.status} tone={STATUS_TONE[c.status] === "low" ? "info" : "neutral"} />, text: (c) => cap(c.status) },
    { key: "effectiveness", header: "Effectiveness", sortable: true, render: (c) => <span title={BASIS_NOTE[c.effectiveness_basis]}><EffectivenessBadge value={c.effectiveness} />{c.effectiveness_basis === "override" && <span className="muted" style={{ fontSize: 11.5 }}> override</span>}</span>, text: effText },
    { key: "design_effectiveness", header: "Design", sortable: true, hidden: true, render: (c) => <EffectivenessBadge value={c.design_effectiveness} />, text: (c) => cap(c.design_effectiveness) },
    { key: "operating_effectiveness", header: "Operating", sortable: true, hidden: true, render: (c) => <EffectivenessBadge value={c.operating_effectiveness} />, text: (c) => cap(c.operating_effectiveness) },
    { key: "pending_review_count", header: "Tests to review", hidden: true, align: "center", render: (c) => (c.pending_review_count ? <Badge tone="info">{c.pending_review_count}</Badge> : <span className="muted">—</span>), text: (c) => String(c.pending_review_count || "") },
    { key: "owner", header: "Owner", render: (c) => <span className="muted"><UserName user={c.owner_ref} fallback={c.owner} /></span>, text: (c) => personText(c.owner_ref, c.owner) },
    { key: "operator", header: "Operator", hidden: true, render: (c) => <span className="muted"><UserName user={c.operator_ref} /></span>, text: (c) => personText(c.operator_ref) },
    { key: "classification", header: "Classification", hidden: true, render: (c) => <span className="muted">{classificationText(c) || "—"}</span>, text: (c) => classificationText(c) },
    { key: "business_units", header: "Business units", hidden: true, render: (c) => linkChips(c.business_units, "/business-units"), text: (c) => names(c.business_units) },
    { key: "processes", header: "Processes", hidden: true, render: (c) => linkChips(c.processes, "/processes"), text: (c) => names(c.processes) },
    { key: "risks", header: "Risks mitigated", render: (c) => linkChips(c.risks, "/risks"), text: (c) => names(c.risks) },
    { key: "policies", header: "Policies", hidden: true, render: (c) => linkChips(c.policies, "/policies"), text: (c) => names(c.policies) },
    { key: "requirements", header: "Requirements", hidden: true, render: (c) => linkChips(c.requirements, "/compliance"), text: (c) => names(c.requirements) },
    { key: "assets", header: "Protected assets", hidden: true, render: (c) => linkChips(c.assets, "/information-assets"), text: (c) => names(c.assets) },
    { key: "audit_frequency", header: "Test cycle", hidden: true, render: (c) => <span className="muted">{cap(c.audit_frequency)}</span>, text: (c) => cap(c.audit_frequency) },
    { key: "last_audit_date", header: "Last tested", hidden: true, sortable: true, render: (c) => <span className="muted">{formatDate(c.last_audit_date)}</span>, text: (c) => (c.last_audit_date ? formatDate(c.last_audit_date) : "") },
    { key: "last_audit_result", header: "Last result", hidden: true, render: (c) => <span className="muted">{c.last_audit_result ? RESULT_LABEL[c.last_audit_result] ?? cap(c.last_audit_result) : "—"}</span>, text: (c) => c.last_audit_result ? RESULT_LABEL[c.last_audit_result] ?? cap(c.last_audit_result) : "" },
    { key: "next_audit_date", header: "Next test", sortable: true, render: (c) => (c.is_audit_overdue ? <Badge tone="high">Overdue</Badge> : UNTESTABLE.has(c.status) ? <span className="muted" title={NO_CLOCK_NOTE[c.status]}>Not scheduled</span> : <span className="muted">{formatDate(c.next_audit_date)}</span>), text: (c) => (UNTESTABLE.has(c.status) ? "Not scheduled" : c.next_audit_date ? formatDate(c.next_audit_date) : "") },
    { key: "audit_count", header: "Tests run", hidden: true, align: "center", render: (c) => <span className="muted">{c.audit_count || "—"}</span> },
    { key: "next_maintenance_date", header: "Next maintenance", hidden: true, render: (c) => (c.is_maintenance_overdue ? <Badge tone="high">Overdue</Badge> : UNTESTABLE.has(c.status) ? <span className="muted">Not scheduled</span> : <span className="muted">{formatDate(c.next_maintenance_date)}</span>), text: (c) => (UNTESTABLE.has(c.status) ? "Not scheduled" : c.next_maintenance_date ? formatDate(c.next_maintenance_date) : "") },
    { key: "opex", header: "Opex / yr", hidden: true, align: "right", render: (c) => <span className="muted">{formatMoney(c.opex)}</span>, text: (c) => c.opex != null ? formatMoney(c.opex) : "" },
    { key: "capex", header: "Capex", hidden: true, align: "right", render: (c) => <span className="muted">{formatMoney(c.capex)}</span>, text: (c) => c.capex != null ? formatMoney(c.capex) : "" },
    { key: "workflow_status", header: "Approval", hidden: true, render: (c) => <span className="muted">{workflowLabel(c.workflow_status)}</span>, text: (c) => workflowLabel(c.workflow_status) },
    {
      key: "actions", header: "", render: (c) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" {...rowAction("Edit", rowLabel(c.reference, c.name))} onClick={() => openEdit(c)}>Edit</button>{" "}
          <button className="btn secondary sm" {...rowAction("Delete", rowLabel(c.reference, c.name))} onClick={() => remove(c)}>Delete</button>
        </div>
      ),
    },
  ];

  /** Delete every selected control after one confirmation, then drop the selection. */
  async function removeMany(rowsToDelete: { id: string }[], clear: () => void) {
    const ok = await confirmDialog({
      title: `Delete ${rowsToDelete.length} control${rowsToDelete.length === 1 ? "" : "s"}?`,
      message: "They are archived, not erased: links from other records are kept, they can be restored from Archived, and the activity trail records who removed them.",
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    const res = await deleteEach(rowsToDelete, (r) => apiCall("DELETE", `/controls/${r.id}`));
    clear();
    reload();
    toastDeleteSummary(res, "control");
  }

  /* ------------------------------------------------------------------ form tabs */
  const generalTab = (
    <>
      <div className="field-row">
        <Field label="Name" required help="For example: Multi-factor authentication, Encryption at rest."><TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="e.g. Multi-factor authentication" required /></Field>
        <Field label="Reference" help="Framework code, e.g. A.8.5 or AC-2."><TextInput value={f.reference} onChange={(v) => set("reference", v)} placeholder="e.g. A.8.5" /></Field>
      </div>
      <Field label="Objective" help="What the control is meant to achieve."><TextArea value={f.objective} onChange={(v) => set("objective", v)} rows={2} placeholder="e.g. Prevent unauthorised access to production systems." /></Field>
      <Field label="Description"><RichText value={f.description} onChange={(v) => set("description", v)} placeholder="Describe how the control is implemented and operated…" /></Field>
      <div className="field-row">
        <Field label="Owner / GRC Contact" help="Accountable for the control's design and effectiveness.">
          <UserPicker
            value={f.owner_id}
            onChange={(id) => set("owner_id", id)}
            selected={editing?.owner_ref}
            legacyText={editing?.owner_id ? null : editing?.owner}
            placeholder="Search people…"
          />
        </Field>
        <Field label="Operator" help="Runs the control day to day, where that is someone other than the owner.">
          <UserPicker
            value={f.operator_id}
            onChange={(id) => set("operator_id", id)}
            selected={editing?.operator_ref}
            placeholder="Search people…"
          />
        </Field>
      </div>
      <Field label="Classification" help="From the organisation's control classification list, e.g. Identity & Access.">
        <LookupSelect
          lookupKey="control_classification"
          value={f.classification_id}
          onChange={(id) => set("classification_id", id)}
          legacyText={editing?.classification_id ? null : editing?.classification}
          placeholder="Choose a classification…"
          allowCreate
        />
      </Field>
      <div className="field-row">
        <Field label="Status" help="Effectiveness is not set here: it comes from reviewed tests (or an Override from the control's detail view)."><Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} /></Field>
      </div>
      <Field label="Documentation URL" help="Link to the runbook, design doc or evidence location."><TextInput value={f.documentation_url} onChange={(v) => set("documentation_url", v)} placeholder="e.g. https://docs.example.com/controls/mfa" /></Field>
    </>
  );
  const attributesTab = (
    <>
      <div className="field-row">
        <Field label="Nature" help="What the control does about an event: stops it, finds it, fixes it, or directs behaviour."><Select value={f.nature} onChange={(v) => set("nature", v)} options={labelled(NATURE_LABEL)} placeholder="Not set" /></Field>
        <Field label="Automation" help="IT-dependent manual: a person acts on system output, e.g. reviews an exception report."><Select value={f.automation} onChange={(v) => set("automation", v)} options={labelled(AUTOMATION_LABEL)} placeholder="Not set" /></Field>
      </div>
      <div className="field-row">
        <Field label="Operating frequency" help="How often the control operates — not how often it is tested. Drives the sample an operating test needs."><Select value={f.operating_frequency} onChange={(v) => set("operating_frequency", v)} options={labelled(OP_FREQ_LABEL)} placeholder="Not set" /></Field>
        <Field label="Key control" help="Its failure alone would let a material risk through. A failed test of a key control raises a high-severity issue."><Toggle checked={f.is_key} onChange={(v) => set("is_key", v)} label={f.is_key ? "Key control" : "Not a key control"} /></Field>
      </div>
      <Field label="Business units" help="Where the control operates."><AsyncMultiSelect search={searchNamed("business-units")} value={f.business_unit_ids} onChange={(v) => set("business_unit_ids", v)} /></Field>
      <Field label="Processes" help="The processes the control sits in."><AsyncMultiSelect search={searchNamed("processes")} value={f.process_ids} onChange={(v) => set("process_ids", v)} /></Field>
      <Field label="Test procedure" help="How to test the control, step by step. Pre-fills every test's workpaper."><TextArea value={f.test_procedure} onChange={(v) => set("test_procedure", v)} rows={3} placeholder="e.g. Select 25 privileged logins from the period; confirm each required a second factor." /></Field>
      <Field label="Evidence expected" help="What a test should produce as evidence."><TextArea value={f.evidence_expected} onChange={(v) => set("evidence_expected", v)} rows={2} placeholder="e.g. IAM export of privileged accounts; MFA policy screenshot." /></Field>
      <Field label="ISO/IEC 27002:2022 attributes" help="Click to tag. Controls installed from the ISO 27001 pack arrive tagged from the standard.">
        <IsoAttributeChips value={f.iso27002_attributes} onChange={(v) => set("iso27002_attributes", v)} />
      </Field>
      <Field label="Design artefact or operating control" help="Kept for existing data: a design artefact documents how something should work; an operating control runs."><Select value={f.control_type} onChange={(v) => set("control_type", v)} options={labelled(CONTROL_TYPE_LABEL)} /></Field>
    </>
  );
  const costTab = (
    <>
      <div className="field-row">
        <Field label={`OpEx (${currency} per year)`} help="Operational cost to run this control annually."><NumberInput value={f.opex} onChange={(v) => set("opex", v)} min={0} step={100} placeholder="Not recorded" /></Field>
        <Field label={`CapEx (${currency})`} help="One-off capital cost to implement."><NumberInput value={f.capex} onChange={(v) => set("capex", v)} min={0} step={100} placeholder="Not recorded" /></Field>
      </div>
      <Field label="Resource Utilization (% FTE)" help="Share of a full-time person needed to operate the control."><NumberInput value={f.resource_utilization} onChange={(v) => set("resource_utilization", v)} min={0} max={100} step={5} placeholder="Not recorded" /></Field>
    </>
  );
  const auditTab = (
    <>
      <div className="card-pad" style={{ padding: "0 0 8px" }}><strong>Test cycle</strong><p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>How the control&apos;s effectiveness is tested and how often.</p></div>
      <div className="field-row">
        <Field label="Test Frequency"><Select value={f.audit_frequency} onChange={(v) => set("audit_frequency", v)} options={FREQ} /></Field>
        {UNTESTABLE.has(f.status)
          ? <Field label="Next Test Date" help="The first test is scheduled from the frequency once the control is implemented or operational."><span className="muted" style={{ fontSize: 13 }}>{NO_CLOCK_NOTE[f.status]}</span></Field>
          : <Field label="Next Test Date" help="Leave blank to derive from the frequency."><TextInput type="date" value={f.next_audit_date} onChange={(v) => set("next_audit_date", v)} /></Field>}
      </div>
      <Field label="Test Metric" help="What you measure to know the control works. Pre-fills each test."><TextArea value={f.audit_metric} onChange={(v) => set("audit_metric", v)} rows={2} placeholder="e.g. % of privileged accounts with MFA enforced." /></Field>
      <Field label="Test Success Criteria" help="The threshold for a passing test. Pre-fills each test."><TextArea value={f.audit_success_criteria} onChange={(v) => set("audit_success_criteria", v)} rows={2} placeholder="e.g. 100% of privileged accounts enforce MFA." /></Field>
      <div className="card-pad" style={{ padding: "16px 0 8px" }}><strong>Maintenance cycle</strong><p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>Routine upkeep that keeps the control operating.</p></div>
      <div className="field-row">
        <Field label="Maintenance Frequency"><Select value={f.maintenance_frequency} onChange={(v) => set("maintenance_frequency", v)} options={FREQ} /></Field>
        {UNTESTABLE.has(f.status)
          ? <Field label="Next Maintenance Date" help="Scheduled from the frequency once the control is implemented or operational."><span className="muted" style={{ fontSize: 13 }}>{NO_MAINTENANCE_CLOCK[f.status]}</span></Field>
          : <Field label="Next Maintenance Date" help="Leave blank to derive from the frequency."><TextInput type="date" value={f.next_maintenance_date} onChange={(v) => set("next_maintenance_date", v)} /></Field>}
      </div>
    </>
  );
  const linksTab = (
    <>
      <Field label="Requirements" help="Framework requirements this control satisfies (map once, comply many)."><AsyncMultiSelect search={searchRequirements} value={f.requirement_ids} onChange={(v) => set("requirement_ids", v)} /></Field>
      <Field label="Policies" help="Policies that mandate or are enforced by this control."><AsyncMultiSelect search={searchPolicies} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} /></Field>
      <Field label="Risks" help="Risks this control mitigates."><AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} /></Field>
      <Field label="Protected assets" help="Assets this control protects."><AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} /></Field>
    </>
  );

  /* ------------------------------------------------------------ test workpaper tabs */
  const t = testForm;
  const testTabs = t && detail ? [
    {
      id: "test", label: "Test", required: true, content: (
        <>
          {editingTest?.review_status === "returned" && editingTest.review_note && (
            <div className="card" style={{ padding: 12, marginBottom: 14, fontSize: 13, borderColor: "var(--amber)" }}>
              <b>Returned by the reviewer:</b> {editingTest.review_note}
            </div>
          )}
          {(detail.test_procedure || detail.evidence_expected) && (
            <div className="card" style={{ padding: 12, marginBottom: 14, fontSize: 13 }}>
              {detail.test_procedure && <div style={{ marginBottom: detail.evidence_expected ? 8 : 0 }}><b>Test procedure</b><div style={{ whiteSpace: "pre-wrap", marginTop: 2 }}>{detail.test_procedure}</div></div>}
              {detail.evidence_expected && <div><b>Evidence expected</b><div style={{ whiteSpace: "pre-wrap", marginTop: 2 }}>{detail.evidence_expected}</div></div>}
            </div>
          )}
          <div className="field-row">
            <Field label="Test type" required help="Design: is the control designed to work? Operating: did it work over a period, on a sample?">
              <Select value={t.test_type} onChange={(v) => setT("test_type", v)} options={labelled({ design: "Design", operating: "Operating" })} />
            </Field>
            <Field label="Result" required help="Passed with exceptions: it worked, but the sample found exceptions — partially effective.">
              <Select value={t.result} onChange={(v) => setT("result", v)} options={labelled({ passed: "Passed", passed_with_exceptions: "Passed with exceptions", failed: "Failed" })} placeholder="Choose a result" />
            </Field>
          </div>
          <div className="field-row">
            <Field label="Date performed" required><input className="input" type="date" value={t.conducted_date} max={today()} onChange={(e) => setT("conducted_date", e.target.value)} required /></Field>
            <Field label="Tester" help="Leave blank if you performed it yourself. The tester cannot review it.">
              <UserPicker value={t.tested_by?.id ?? null} selected={t.tested_by} onChange={(_id, ref) => setT("tested_by", ref ?? null)} placeholder="Who performed the test…" />
            </Field>
          </div>
          <div className="field-row">
            <Field label="Period from" required={t.test_type === "operating"} help="The window the sample was drawn from."><TextInput type="date" value={t.period_start} onChange={(v) => setT("period_start", v)} /></Field>
            <Field label="Period to" required={t.test_type === "operating"}><TextInput type="date" value={t.period_end} onChange={(v) => setT("period_end", v)} /></Field>
          </div>
          <Field label="Procedure & metric" help="What was done and measured — pre-filled from the control's test procedure and metric."><TextArea value={t.metric_description} onChange={(v) => setT("metric_description", v)} rows={3} /></Field>
          <Field label="Success criteria" help="Pre-filled from the control."><TextArea value={t.success_criteria} onChange={(v) => setT("success_criteria", v)} rows={2} /></Field>
        </>
      ),
    },
    {
      id: "sample", label: "Sample & exceptions", content: (
        <>
          <div className="field-row">
            <Field label="Population" help="How many times the control operated in the period."><NumberInput value={t.population_size} onChange={(v) => setT("population_size", v)} min={0} /></Field>
            <Field label="Sample size" help="How many of those were tested."><NumberInput value={t.sample_size} onChange={(v) => setT("sample_size", v)} min={0} /></Field>
          </div>
          <Field label="Sample method"><Select value={t.sample_method} onChange={(v) => setT("sample_method", v)} options={SAMPLE_METHOD} placeholder="Not stated" /></Field>
          <Field label="Exceptions found" required={t.result === "passed_with_exceptions"} help="Sample items where the control did not work."><NumberInput value={t.exceptions_count} onChange={(v) => setT("exceptions_count", v)} min={0} /></Field>
          <Field label="Exception detail"><TextArea value={t.exceptions_detail} onChange={(v) => setT("exceptions_detail", v)} rows={3} placeholder="e.g. 3 of 25 logins (items 4, 11, 19) had MFA bypassed by a legacy VPN profile." /></Field>
        </>
      ),
    },
    {
      id: "conclusion", label: "Conclusion", required: true, content: (
        <>
          <Field label="Conclusion" required help="What was found, and what it means for the control."><TextArea value={t.conclusion} onChange={(v) => setT("conclusion", v)} rows={4} /></Field>
          <Field label="Improvement" help="A corrective action the test suggests. A failed test (or one with exceptions) raises an issue automatically once approved."><TextArea value={t.improvement} onChange={(v) => setT("improvement", v)} rows={2} /></Field>
        </>
      ),
    },
    {
      id: "evidence", label: `Evidence (${t.evidence_ids.length + t.new_evidence.filter((e) => e.title.trim()).length})`, content: (
        <>
          <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>A conclusive test needs at least one evidence item. Attach this control&apos;s existing evidence, or add new items here — files can be uploaded to them from the Evidence register afterwards.</p>
          <Field label="Existing evidence of this control"><AsyncMultiSelect search={searchTestEvidence} value={t.evidence_ids} onChange={(v) => setT("evidence_ids", v)} placeholder="Search this control's evidence…" /></Field>
          {t.new_evidence.map((e, i) => (
            <div key={i} className="field-row" style={{ alignItems: "flex-end" }}>
              <Field label={`New evidence ${i + 1}`}><TextInput value={e.title} onChange={(v) => setT("new_evidence", t.new_evidence.map((x, j) => (j === i ? { ...x, title: v } : x)))} placeholder="e.g. Q3 privileged-login sample" /></Field>
              <Field label="Type"><Select value={e.evidence_type} onChange={(v) => setT("new_evidence", t.new_evidence.map((x, j) => (j === i ? { ...x, evidence_type: v || "document" } : x)))} options={EVIDENCE_TYPES} /></Field>
              <Field label="Link or location"><TextInput value={e.reference} onChange={(v) => setT("new_evidence", t.new_evidence.map((x, j) => (j === i ? { ...x, reference: v } : x)))} placeholder="https://…" /></Field>
              <button type="button" className="btn secondary sm" style={{ marginBottom: 14 }} {...rowAction("Remove", `new evidence ${i + 1}${e.title.trim() ? ` ${e.title.trim()}` : ""}`)} onClick={() => setT("new_evidence", t.new_evidence.filter((_, j) => j !== i))}>Remove</button>
            </div>
          ))}
          <button type="button" className="btn secondary sm" onClick={() => setT("new_evidence", [...t.new_evidence, { title: "", evidence_type: "document", reference: "" }])}><IconPlus width={14} height={14} /> Add evidence</button>
        </>
      ),
    },
  ] : [];

  /* ------------------------------------------------------------ the record page */
  const period = (x: ControlTest) => (x.period_start && x.period_end ? `${formatDate(x.period_start)} – ${formatDate(x.period_end)}` : "");
  const effBadge = (v: string | null | undefined) =>
    isRated(v) ? <Badge tone={EFF_TONE[v ?? ""] ?? "neutral"} asIs>{sentenceCase(v)}</Badge> : <Badge hollow asIs>Not assessed</Badge>;
  const refChips = (items: LinkRef[] | undefined, href: string) =>
    items && items.length ? (
      <span className="chips">
        {items.map((x) => <Link key={x.id} className="chip chip-link" href={`${href}?id=${x.id}`}>{labelOf(x)}</Link>)}
      </span>
    ) : null;

  /** Header: crumb, H1 (the name; the reference only when there is none), the lead
   *  (objective, else the description's text) and the six meta items of spec §4.2 —
   *  Lifecycle in slot 1, Record approval in slot 2 (decision D1), then Owner, Operator,
   *  Source / Classification (B7) and Next test. */
  function identityOf(c: Control): RecordIdentity {
    const owner = personText(c.owner_ref, c.owner);
    const operator = personText(c.operator_ref);
    const assign = canWrite ? { label: "Assign", onClick: () => openEdit(c, "general") } : undefined;
    const pending = c.pending_review_count || 0;
    const src = controlSourceMeta(c);
    const next = controlNextTest(c, ctx.fmt);
    const nextValue = next.badge ? <Badge tone="high" asIs>{next.text}</Badge> : next.muted ? <span className="muted">{next.text}</span> : next.text;
    return {
      kind: "Control",
      backLabel: "Control Catalog",
      reference: c.reference || null,
      name: c.name || c.reference,
      lead: controlLead(c),
      badges: c.is_key || pending > 0 ? (
        <>
          {c.is_key && <Badge tone="info" asIs>Key control</Badge>}
          {pending > 0 && <Badge tone="info" plain asIs>{plural(pending, "test")} to review</Badge>}
        </>
      ) : null,
      status: {
        key: "lifecycle", label: "Lifecycle",
        value: <Badge tone={STATUS_TONE[c.status] ?? "neutral"} asIs>{sentenceCase(c.status)}</Badge>,
        hint: CONTROL_LIFECYCLE_HINT,
      },
      // "Imported, no approver recorded" (B10b) and "No approval step on file" come from the kit.
      approval: approvalMetaItem(gov, ctx.fmt, approvalHintFor("Lifecycle")),
      meta: [
        {
          key: "owner", label: "Owner", value: owner || null, hint: CONTROL_OWNER_HINT,
          // Free text with no person picked is a label nobody can be notified at.
          gap: !owner ? { text: "Not assigned", fix: assign }
            : textOnlyPerson(c.owner_id, c.owner) ? { text: "Text only", fix: canWrite ? { label: "Pick a person", onClick: () => openEdit(c, "general") } : undefined }
            : undefined,
        },
        {
          key: "operator", label: "Operator", value: operator || null, hint: CONTROL_OPERATOR_HINT,
          gap: !operator && LIVE.has(c.status) ? { text: "Not assigned", fix: assign } : undefined,
        },
        { key: "source", label: src.label, value: src.value, hint: src.hint },
        { key: "next-test", label: "Next test", value: nextValue, sub: next.sub },
      ],
      statusRules: { model: "control", entityId: c.id },
    };
  }

  function primaryOf(c: Control): PrimaryCandidate[] {
    return [
      { kind: "workflow", action: "approve" },
      { kind: "workflow", action: "submit" },
      { kind: "custom", label: "Record test", when: canTest && LIVE.has(c.status), onClick: openRecordTest },
      { kind: "attest" },
    ];
  }

  function moreItemsOf(c: Control): MenuItem[] {
    const items: MenuItem[] = [];
    if (canTest) items.push({ label: "Record test", onClick: openRecordTest, hint: c.status === "planned" ? "A design test while the control is planned" : undefined });
    if (canWrite) {
      items.push({ label: "Record maintenance…", onClick: openMaintenance });
      items.push({ label: "Override effectiveness…", onClick: openOverride });
      if (c.effectiveness_basis === "override") items.push({ label: "Drop override", onClick: () => void dropOverride() });
      items.push({ label: "Suggest clause mappings", onClick: openSuggestions });
    }
    if (canRaiseIssue) items.push({ label: "Raise issue…", onClick: openRaise });
    return withBaseMoreItems(items, canWrite ? { onDelete: () => void remove(c) } : {});
  }

  /* ---- Effectiveness & tests ---- */
  function effectivenessBlock(c: Control) {
    const d = c.design_effectiveness || "not_assessed";
    const o = c.operating_effectiveness || "not_assessed";
    const combined = c.effectiveness || "not_assessed";
    const from = (kind: "design" | "operating") =>
      testFromText(latestCounting(tests, kind), ctx.fmt) ?? <span className="muted">No reviewed {kind} test</span>;
    const combinedFrom = combinedFromText(c.effectiveness_basis);
    return (
      <>
        {d === o && o === combined ? (
          <p style={{ margin: "0 0 10px", display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap", fontSize: 13 }}>
            {effBadge(combined)}
            <span className="muted">{effectivenessNote(c.effectiveness_basis)}</span>
          </p>
        ) : (
          <div className="rec-table-wrap" style={{ marginBottom: 10 }}>
            <table className="compact">
              <thead><tr><th><span className="sr-only">Part</span></th><th>Rating</th><th>From</th></tr></thead>
              <tbody>
                {([["Design", effBadge(d), from("design")], ["Operating", effBadge(o), from("operating")], ["Combined", effBadge(combined), combinedFrom]] as const).map(([part, rating, source]) => (
                  <tr key={part}><th scope="row" style={{ textAlign: "left", fontWeight: 600 }}>{part}</th><td>{rating}</td><td>{source}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {c.effectiveness_basis === "override" && c.effectiveness_override_reason && (
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <blockquote className="rec-quote" style={{ flex: "1 1 260px" }}>
              <span className="muted">Override reason: </span>{c.effectiveness_override_reason}
            </blockquote>
            {canWrite && <button type="button" className="btn secondary sm" onClick={() => void dropOverride()}>Drop override</button>}
          </div>
        )}
        {c.open_issues.length > 0 && (
          <p style={{ fontSize: 12.5, margin: "8px 0 0", display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
            <span className="muted">{issueCapText(c.open_issues.length)}</span>
            {c.open_issues.map((i) => <Link key={i.id} className="chip chip-link" href={`/issues?id=${i.id}`} title={i.title}>{i.reference || i.title}</Link>)}
          </p>
        )}
      </>
    );
  }

  function testsSection(c: Control) {
    const sub = testsSectionSub(c, ctx.fmt);
    // Row names for the per-row buttons (decision D3): type, date and period; rows that
    // still collide (same day, same period, or undated legacy tests) get "test i of n".
    const testRowNames = new Map<string, string>();
    {
      const base = tests.map((x) => {
        const p = period(x);
        return [x.id, `${controlTestTitle(x, ctx.fmt)}${p ? `, period ${p}` : ""}`] as const;
      });
      const groups = new Map<string, string[]>();
      for (const [id, name] of base) groups.set(name, [...(groups.get(name) ?? []), id]);
      for (const [name, ids] of groups) ids.forEach((id, i) => testRowNames.set(id, ids.length > 1 ? `${name} (test ${i + 1} of ${ids.length})` : name));
    }
    return (
      <RecordSection
        id="tests"
        title="Effectiveness & tests"
        count={tests.length}
        sub={sub}
        actions={canTest || canWrite ? (
          <>
            {/* Named apart from the header's "Record test" (decision D3: no two controls share a name). */}
            {canTest && <button type="button" className="btn secondary sm" aria-label={`Record test of ${c.reference || c.name}`} onClick={openRecordTest}>Record test</button>}
            {canWrite && <button type="button" className="btn secondary sm" onClick={openOverride}>Override…</button>}
          </>
        ) : undefined}
      >
        {effectivenessBlock(c)}
        <p className="muted" style={{ fontSize: 12.5, margin: "14px 0 8px" }}>{TESTS_REVIEW_NOTE}</p>
        {tests.length ? (
          <div className="rec-table-wrap">
            <table className="compact">
              <thead><tr><th>Performed</th><th>Type</th><th>Result</th><th>Review</th><th>Tester</th><th>Evidence / issue</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>
                {tests.map((x) => {
                  const tester = personText(x.tested_by_ref, x.auditor);
                  /** "Operating test of 03 Jul 2026, period 01 Jan – 31 Mar 2026" — names this
                   *  row's buttons (decision D3); unique within the table. */
                  const rowName = testRowNames.get(x.id) ?? controlTestTitle(x, ctx.fmt);
                  return (
                    <Fragment key={x.id}>
                      <tr onClick={() => setExpanded(expanded === x.id ? null : x.id)} style={{ cursor: "pointer" }}>
                        <td>
                          {x.conducted_date ? formatDate(x.conducted_date) : <span className="muted">Not recorded</span>}
                          {period(x) && <div className="muted" style={{ fontSize: 11.5 }}>{period(x)}</div>}
                        </td>
                        <td>{x.test_type ? sentenceCase(x.test_type) : <span className="muted">Not set</span>}</td>
                        <td><ResultBadge value={x.result} /></td>
                        <td><Badge tone={REVIEW_TONE[x.review_status] ?? "neutral"} plain asIs>{REVIEW_LABEL[x.review_status] ?? sentenceCase(x.review_status)}</Badge></td>
                        <td>{tester ? <span title={x.tested_by_ref?.email || undefined}>{tester}</span> : <span className="muted">Not recorded</span>}</td>
                        <td onClick={(e) => e.stopPropagation()}>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                            {x.evidence.map((ev) => <Link key={ev.id} className="chip chip-link" href={`/evidence?id=${ev.id}`}>{ev.title || "Evidence"}</Link>)}
                            {x.raised_issue && <Link className="chip chip-link" href={`/issues?id=${x.raised_issue.id}`} title={x.raised_issue.title}>{x.raised_issue.reference || "Issue"}</Link>}
                            {!x.evidence.length && !x.raised_issue && <span className="muted">None</span>}
                          </div>
                        </td>
                        <td onClick={(e) => e.stopPropagation()} style={{ whiteSpace: "nowrap" }}>
                          <div style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "flex-end" }}>
                            <button type="button" className="rec-link" aria-expanded={expanded === x.id} {...rowAction(expanded === x.id ? "Hide" : "Details", rowName)} onClick={() => setExpanded(expanded === x.id ? null : x.id)}>
                              {expanded === x.id ? "Hide" : "Details"}
                            </button>
                            {x.can_review && (
                              <button type="button" className="btn secondary sm" data-review-btn={x.id} aria-expanded={reviewing === x.id}
                                {...rowAction("Review", rowName)} onClick={() => { setReviewing(reviewing === x.id ? null : x.id); setReviewNote(""); }}>
                                Review
                              </button>
                            )}
                            {x.can_edit && (
                              <button type="button" className="btn secondary sm" {...rowAction(x.review_status === "returned" ? "Fix & resubmit" : "Edit", rowName)} onClick={() => openEditTest(x)}>
                                {x.review_status === "returned" ? "Fix & resubmit" : "Edit"}
                              </button>
                            )}
                            {!x.can_review && x.review_status === "pending" && x.review_blocked_reason && (
                              <span className="muted" style={{ fontSize: 11.5 }} title={x.review_blocked_reason}>awaiting reviewer</span>
                            )}
                          </div>
                        </td>
                      </tr>
                      {reviewing === x.id && (
                        <tr><td colSpan={7}>
                          <Disclosure hideTrigger open label={`Review: ${rowName}`} panelClassName=""
                            onOpenChange={(v) => { if (!v) closeReview(x.id); }}>
                            {() => (
                              <div style={{ display: "grid", gap: 8 }}>
                                <textarea className="input" rows={2} value={reviewNote} onChange={(e) => setReviewNote(e.target.value)}
                                  placeholder="Required when returning the test to the tester" aria-label={`Review note for the ${rowName.toLowerCase()}`} />
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                  <button type="button" className="btn secondary sm" onClick={() => void decide(x, "approve")}>Approve</button>
                                  <button type="button" className="btn secondary sm" onClick={() => void decide(x, "return")}>Return to tester</button>
                                  <button type="button" className="btn secondary sm" onClick={() => closeReview(x.id)}>Cancel</button>
                                </div>
                                {(x.result === "failed" || x.result === "passed_with_exceptions") && (
                                  <div className="muted" style={{ fontSize: 12 }}>
                                    Approving raises an issue owned by the control owner{c.is_key && x.result === "failed" ? " (high severity: a key control failed)" : ""}.
                                  </div>
                                )}
                              </div>
                            )}
                          </Disclosure>
                        </td></tr>
                      )}
                      {expanded === x.id && (
                        <tr><td colSpan={7} style={{ fontSize: 13 }}>
                          <FactGrid>
                            {x.sample_size != null && (
                              <Fact label="Sample">
                                {x.sample_size}{x.population_size != null ? ` of ${x.population_size}` : ""}
                                {x.sample_method ? ` · ${SAMPLE_METHOD.find((m) => m.value === x.sample_method)?.label ?? x.sample_method}` : ""}
                              </Fact>
                            )}
                            <Fact label="Exceptions">{String(x.exceptions_count || 0)}</Fact>
                            {x.reviewed_by_ref && (
                              <Fact label={x.review_status === "returned" ? "Returned by" : "Reviewed by"}>
                                <UserName user={x.reviewed_by_ref} />{x.reviewed_at && <span className="muted"> · {formatDateTime(x.reviewed_at)}</span>}
                              </Fact>
                            )}
                            {x.metric_description && <Fact label="Procedure & metric" wide>{x.metric_description}</Fact>}
                            {x.exceptions_detail && <Fact label="Exception detail" wide>{x.exceptions_detail}</Fact>}
                            <Fact label="Conclusion" wide>{x.conclusion || x.result_description || <span className="muted">Not recorded</span>}</Fact>
                            {x.review_note && <Fact label="Review note" wide>{x.review_note}</Fact>}
                          </FactGrid>
                        </td></tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="rec-empty" style={{ margin: 0 }}>{testsEmptyText(c)}</p>
        )}
      </RecordSection>
    );
  }

  /* ---- Maintenance ---- */
  function maintenanceSection(c: Control) {
    const sub = maintenanceSectionSub(c, ctx.fmt);
    const empty = maints.length === 0 && !maintOpen ? maintenanceEmptyText(c) : undefined;
    return (
      <RecordSection
        id="maintenance"
        title="Maintenance"
        count={maints.length}
        sub={empty ? undefined : sub || undefined}
        empty={empty}
        actions={canWrite ? (
          <button ref={maintTrigger} type="button" className="btn secondary sm" aria-expanded={maintOpen} aria-controls={maintOpen ? "ctl-maint-form" : undefined}
            onClick={() => { setMaintError(null); setMaintOpen((v) => !v); }}>
            Record maintenance
          </button>
        ) : undefined}
      >
        <Disclosure label="Record maintenance" hideTrigger open={maintOpen} onOpenChange={(v) => closeOrOpen(setMaintOpen, maintTrigger, v)} id="ctl-maint-form" triggerRef={maintTrigger}>
          {(close) => (
            <form onSubmit={(e) => { e.preventDefault(); void recordMaintenance(close); }}>
              <div className="row">
                <div style={{ width: 140 }}>
                  <label className="label" htmlFor="ctl-maint-result">Result</label>
                  <select id="ctl-maint-result" className="select" value={maintResult} onChange={(e) => setMaintResult(e.target.value)}>
                    <option value="passed">Passed</option>
                    <option value="failed">Failed</option>
                  </select>
                </div>
                <div style={{ flex: "1 1 200px" }}>
                  <label className="label" htmlFor="ctl-maint-task">Task</label>
                  <input id="ctl-maint-task" className="input" value={maintTask} onChange={(e) => setMaintTask(e.target.value)} placeholder="e.g. Rotate keys" />
                </div>
                <button type="submit" className="btn secondary sm" disabled={maintSaving}>{maintSaving ? "Recording…" : "Record"}</button>
                <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
              </div>
              {maintError && <div className="error" style={{ marginTop: 8 }}>{maintError}</div>}
            </form>
          )}
        </Disclosure>
        {maints.length > 0 && (
          <div className="rec-table-wrap" style={{ marginTop: maintOpen ? 12 : 0 }}>
            <table className="compact">
              <thead><tr><th>Task</th><th>Date</th><th>Result</th></tr></thead>
              <tbody>
                {maints.map((m) => (
                  <tr key={m.id}>
                    <td>{m.task || "Maintenance"}</td>
                    <td>{m.conducted_date ? formatDate(m.conducted_date) : <span className="muted">Not recorded</span>}</td>
                    <td><ResultBadge value={m.result} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </RecordSection>
    );
  }

  /* ---- Design ---- */
  function designFacts(c: Control): FactItem[] {
    const cost = [c.opex != null ? `${formatMoney(c.opex)} a year` : "", c.capex != null ? `${formatMoney(c.capex)} capex` : ""].filter(Boolean).join(" · ");
    const cls = designClassification(c);
    const docsUrl = safeLinkUrl(c.documentation_url);
    return [
      { key: "procedure", label: "Test procedure", value: (c.test_procedure || "").trim() || null, wide: true, tab: "attributes" },
      { key: "evidence", label: "Evidence expected", value: (c.evidence_expected || "").trim() || null, wide: true, tab: "attributes" },
      // Shown once (decision D2): the objective is the lead; the description appears here,
      // formatted and sanitised, only when it says something else.
      ...(descriptionDiffers(c)
        ? [{ key: "description", label: "Description", value: <RichTextView html={c.description} />, wide: true, tab: "general" } as FactItem]
        : []),
      ...(!controlLead(c) ? [{ key: "objective", label: "Objective", value: null, tab: "general" } as FactItem] : []),
      { key: "nature", label: "Nature", value: c.nature ? NATURE_LABEL[c.nature] ?? sentenceCase(c.nature) : null, tab: "attributes" },
      { key: "automation", label: "Automation", value: c.automation ? AUTOMATION_LABEL[c.automation] ?? sentenceCase(c.automation) : null, tab: "attributes" },
      {
        key: "operates", label: "Operates", value: c.operating_frequency ? OP_FREQ_LABEL[c.operating_frequency] ?? sentenceCase(c.operating_frequency) : null,
        tab: "attributes", hint: "How often the control operates — not how often it is tested.",
      },
      { key: "key", label: "Key control", value: c.is_key ? "Yes" : "No", tab: "attributes" },
      { key: "artefact", label: "Artefact or operating", value: CONTROL_TYPE_LABEL[c.control_type] ?? sentenceCase(c.control_type), tab: "attributes" },
      { key: "test-cycle", label: "Test cycle", value: cycleFact(c.audit_frequency), tab: "audit" },
      { key: "maint-cycle", label: "Maintenance cycle", value: cycleFact(c.maintenance_frequency), tab: "audit" },
      { key: "metric", label: "Test metric", value: (c.audit_metric || "").trim() || null, wide: true, tab: "audit" },
      { key: "criteria", label: "Test success criteria", value: (c.audit_success_criteria || "").trim() || null, wide: true, tab: "audit" },
      { key: "units", label: "Business units", value: refChips(c.business_units, "/business-units"), tab: "attributes" },
      { key: "processes", label: "Processes", value: refChips(c.processes, "/processes"), tab: "attributes" },
      { key: "iso", label: "ISO/IEC 27002 attributes", value: isoCount(c.iso27002_attributes) ? <IsoAttributeList value={c.iso27002_attributes} /> : null, wide: true, tab: "attributes" },
      ...(cost ? [{ key: "cost", label: "Cost", value: cost, tab: "cost" } as FactItem] : []),
      { key: "fte", label: "Resource utilisation", value: c.resource_utilization != null ? `${c.resource_utilization}% of a full-time person` : null, tab: "cost" },
      {
        // A stored URL is a link only when it is http(s) or mailto; anything else is shown as text.
        key: "docs", label: "Documentation", tab: "general",
        value: !c.documentation_url
          ? null
          : docsUrl
            ? <a href={docsUrl} target="_blank" rel="noopener noreferrer">{c.documentation_url}</a>
            : c.documentation_url,
      },
      // A genuine classification, when the header shows the control's source instead.
      ...(cls ? [{ key: "classification", label: "Classification", value: cls, tab: "general" } as FactItem] : []),
      ...cf.facts,
    ];
  }

  function designSection(c: Control) {
    return (
      <RecordSection
        id="design"
        title="Design"
        actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit design" onClick={() => openEdit(c, "attributes")}>Edit</button> : undefined}
      >
        <FactList
          items={designFacts(c)}
          fillLabel="Complete design"
          onFillIn={canWrite ? (tab) => (tab === "custom" ? cf.setEditing(true) : openEdit(c, tab)) : undefined}
        />
        {cf.editor}
        {cf.editLink(canWrite)}
      </RecordSection>
    );
  }

  /* ---- Linked records ---- */
  function linkedSection(c: Control) {
    // The suggested-clauses line (decision D7): under Requirements, or alone when no clause is linked.
    const suggestRow = (
      <SuggestedClausesRow
        controlId={c.id}
        count={suggestionCount}
        failed={suggestionFailed}
        onRetry={() => loadSuggestions(c.id)}
        open={suggestOpen}
        onOpenChange={setSuggestOpen}
        onAccepted={refreshOpen}
      />
    );
    const hasRequirements = c.requirements.length > 0;
    const groups: RelatedGroup[] = [
      {
        key: "requirements", label: "Requirements", items: c.requirements, href: "/compliance",
        meta: (x: RequirementRef) => (x.framework ?? "").trim() || null, // B7; nothing without it
        footer: hasRequirements ? suggestRow : undefined,
      },
      { key: "risks", label: "Risks", items: c.risks, href: "/risks" },
      { key: "policies", label: "Policies", items: c.policies, href: "/policies" },
      { key: "assets", label: "Protected assets", items: c.assets, href: "/information-assets" },
      { key: "vendors", label: "Third parties", items: c.vendors, href: "/vendors" },
      { key: "incidents", label: "Incidents", items: c.incidents, href: "/incidents" },
      // B3: each exception's state and expiry; the chip alone against an older API.
      { key: "exceptions", label: "Exceptions", items: c.exceptions, href: "/exceptions", meta: (x: ExceptionRef) => exceptionMeta(x, ctx.fmt) },
      { key: "projects", label: "Projects", items: c.projects, href: "/projects" },
      { key: "findings", label: "Audit findings", items: c.audit_findings, href: "/internal-audit" },
    ];
    return (
      <RecordSection
        id="linked"
        title="Linked records"
        count={relatedCount(groups)}
        actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(c, "links")}>Link records</button> : undefined}
      >
        {/* No onLink: the head's "Link records" is the one control (decision D3). */}
        <RelatedGroups groups={groups} />
        {!hasRequirements && <div className="rec-none">{suggestRow}</div>}
      </RecordSection>
    );
  }

  function recordMain(c: Control) {
    const input: ControlInput = { control: c, tests, maints, suggestionCount };
    const points = controlOpenPoints(input, ctx).map((p) => (p.action && !canFollow(p.action) ? { ...p, action: undefined } : p));
    return (
      <>
        <SectionsBridge apiRef={drawerSections} />
        <SummaryBand tiles={controlTiles(input, ctx)} headline={controlHeadline(input, ctx)} />
        <OpenPoints points={points} canAct={canWrite || canTest} onAction={handlePoint} clearText={CONTROL_CLEAR_TEXT} />
        <SectionNav />
        {testsSection(c)}
        {maintenanceSection(c)}
        {designSection(c)}
        {linkedSection(c)}
        {/* The shared Issues section (decision D6). Open issues cap the control's operating
            rating, so a raise refreshes the control too. */}
        <RecordIssuesSection
          ref={issuesRef}
          entityId={c.id}
          entityKind="control"
          entityRef={c.reference || c.name}
          noun="control"
          canRaise={canRaiseIssue}
          onRaised={refreshOpen}
          reloadKey={refreshKey}
        />
      </>
    );
  }

  return (
    <>
      <div className="page-head row-between" style={{ flexWrap: "wrap" }}>
        {/* The actions wrap under the title on a phone instead of widening the page. */}
        <div style={{ flex: "1 1 260px", minWidth: 0 }}>
          <h1>Control Catalog</h1>
          <p>Reusable controls with attributes, derived effectiveness, framework mappings and reviewed test workpapers.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ImportExport resource="controls" label="Controls" onDone={reload} />
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add control</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Control>
        toolbarRight={<ArchivedRecords entityType="control" noun="controls" onRestored={reload} refreshKey={refreshKey} />}
        tableKey="controls"
        statusModel="control"
        bulkActions={(rows, clear) => (
          <>
            <BulkEditBar entityType="control" rows={rows} onDone={() => { clear(); reload(); }} mapRequirements />
            <button className="btn secondary sm" onClick={() => { setSuggestFor(rows.map((r) => r.id)); clear(); }}>Suggest mappings</button>
            <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
          </>
        )}
        filters={filters.values}
        onApplyFilters={filters.replace}
        toolbarLeft={
          <>
            <select className="select" style={{ maxWidth: 230 }} value={filters.values.assurance ?? ""} onChange={(e) => filters.set("assurance", (e.target.value || undefined) as typeof filters.values.assurance)} aria-label="Assurance">
              <option value="">Any assurance</option>
              {CONTROL_FILTERS.assurance.map((v) => <option key={v} value={v}>{ASSURANCE_LABEL[v]}</option>)}
            </select>
            <select className="select" style={{ maxWidth: 190 }} value={filters.values.test ?? ""} onChange={(e) => filters.set("test", (e.target.value || undefined) as typeof filters.values.test)} aria-label="Test cycle">
              <option value="">Any test status</option>
              {CONTROL_FILTERS.test.map((v) => <option key={v} value={v}>{TEST_LABEL[v]}</option>)}
            </select>
            <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={filters.values.key === true} onChange={(e) => filters.set("key", e.target.checked || undefined)} /> Key controls
            </label>
            {filters.active > 0 && <button className="linklike" onClick={filters.clear}>Clear filters</button>}
          </>
        }
        columns={columns}
        fetcher={fetchControls}
        rowKey={(c) => c.id}
        onRowClick={(c) => setOpenId(c.id)}
        activeKey={openId}
        searchPlaceholder="Search controls by name or reference…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No controls yet. Create your first control to build the catalog."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        variant="dossier"
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        governance={gov}
        identity={detail ? identityOf(detail) : undefined}
        primaryAction={detail ? <PrimaryAction candidates={primaryOf(detail)} onChanged={refreshOpen} /> : null}
        onEdit={detail && canWrite ? () => openEdit(detail) : undefined}
        moreItems={detail ? moreItemsOf(detail) : undefined}
        aside={detail ? (
          <RecordPanels model="control" entityId={detail.id} layout="dossier" signOff={{ onChanged: refreshOpen }} trail={{ reference: detail.reference }} />
        ) : null}
      >
        {detail && recordMain(detail)}
      </RecordDrawer>

      {suggestFor && (
        <BulkSuggestMappings controlIds={suggestFor} onClose={() => setSuggestFor(null)} onDone={reload} />
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit control — ${editing.reference || editing.name}` : "Add item (Controls)"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "attributes", label: "Attributes & scope", content: attributesTab },
            { id: "cost", label: "Cost & Resourcing", content: costTab },
            { id: "audit", label: "Testing & Maintenance", content: auditTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create control"}
          initialTab={editTab}
        />
      )}

      {testForm && detail && (
        <FormModal
          title={`${editingTest ? (editingTest.review_status === "returned" ? "Fix & resubmit test" : "Edit test") : "Record test"} — ${detail.reference || detail.name}`}
          wide
          tabs={testTabs}
          onClose={() => { setTestForm(null); setEditingTest(null); }}
          onSave={saveTest}
          saving={testSaving}
          error={testError}
          saveLabel={editingTest ? "Resubmit for review" : "Record test"}
          footerLeft={<span className="muted" style={{ fontSize: 12 }}>It needs an independent reviewer before it counts.</span>}
        />
      )}

      {override && detail && (
        <FormModal
          title={`Override effectiveness — ${detail.reference || detail.name}`}
          tabs={[{
            id: "override", label: "Override", required: true, content: (
              <>
                <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>The rating normally comes from reviewed tests (now: design {ratingWord(detail.design_effectiveness)}, operating {ratingWord(detail.operating_effectiveness)}). An override replaces the combined rating until it is dropped or the next test is approved, and is recorded with its reason.</p>
                <Field label="Effectiveness" required><Select value={override.effectiveness} onChange={(v) => setOverride({ ...override, effectiveness: v })} options={EFFECTIVENESS} /></Field>
                <Field label="Reason" required help="Why the tests do not tell the whole story — e.g. a compensating control, a known bypass."><TextArea value={override.reason} onChange={(v) => setOverride({ ...override, reason: v })} rows={3} /></Field>
              </>
            ),
          }]}
          onClose={() => setOverride(null)}
          onSave={saveOverride}
          error={overrideError}
          saveLabel="Override"
        />
      )}
    </>
  );
}

export default function ControlsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ControlsInner />
    </Suspense>
  );
}
