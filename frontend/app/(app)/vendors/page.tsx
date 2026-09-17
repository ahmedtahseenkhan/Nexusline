"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { confirmDeleteWithImpact } from "@/lib/records";
import { lookupValues, pickProcesses, type LookupRef, type UserRef } from "@/lib/masterData";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFilterParams, type FilterSpec } from "@/lib/useFilterParams";
import DataTable, { type Column } from "@/components/DataTable";
import BulkEditBar from "@/components/BulkEditBar";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, Toggle, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import { InlineLookupCreate } from "@/components/LookupManager";
import LookupSelect from "@/components/LookupSelect";
import UserPicker from "@/components/UserPicker";
import ArchivedRecords from "@/components/ArchivedRecords";
import { useCustomFieldFacts } from "@/components/CustomFieldsPanel";
import {
  FactList, OpenPoints, PrimaryAction, RecordIssuesSection, RecordSection, RelatedGroups, SectionNav, SummaryBand,
  approvalHintFor, approvalMetaItem, relatedCount, rowAction, useRecordCtx, useRecordGovernanceData, useRecordSections,
  withBaseMoreItems, type MetaItem, type RecordIssuesHandle, type RelatedGroup,
} from "@/components/record";
import { useHasPermission } from "@/lib/tenantSettings";
import { titleCase } from "@/lib/text";
import { sentenceCase, uniqueLabels } from "@/lib/record/text";
import { safeLinkUrl } from "@/lib/sanitize";
import {
  VENDOR_CLEAR_TEXT, vendorContractsSub, vendorDataTone, vendorHeadline, vendorOpenPoints, vendorOverrideNote, vendorOverrideText,
  vendorOutsourcingDiligence, vendorReviewOverdue, vendorSevTone, vendorTiles, VENDOR_SUBSTITUTABILITY,
  type VendorConcentrationFacts, type VendorInput,
  type VendorDueDiligenceFacts,
} from "@/lib/record/vendor";
import type { PointAction } from "@/lib/record/types";

/* ---------------------------------------------------------------- inline types */
type RefItem = { id: string; reference?: string; title?: string; name?: string };
type VendorType = { id: string; name: string; description: string };
type ServiceContract = {
  id: string; name: string; description: string; value: number | null;
  /** ISO code; blank on contracts recorded before contracts carried a currency (= the organisation's). */
  currency: string;
  start_date: string | null; end_date: string | null; is_expired: boolean; created_at: string;
};
type Certification = {
  id: string; vendor_id: string; cert_type: string; cert_type_label: string; issuer: string;
  certificate_number: string; scope: string; issued_on: string | null; expires_on: string | null;
  /** valid | expiring (within 60 days) | expired | no_expiry */
  expiry_state: string; days_to_expiry: number | null;
};
type Tiering = {
  tier: string | null; proposed_criticality: string | null; overridden: boolean; override_reason: string;
  assessment: RefItem | null; submitted_at: string | null; total_score: number | null; max_score: number | null;
  score_pct: number | null; band_tier: string | null; worst_case_answers: number | null; floor_applied: boolean;
  explanation: string; stale: boolean; problem: string; questionnaire_id: string | null;
};
type OutsourcingFact = {
  id: string; reference: string; title: string; status: string; materiality: string; is_cloud: boolean;
  data_offshored: boolean; country: string; sbp_approval_status: string; contract_end: string | null;
  exit_plan: string; exit_plan_tested: boolean;
  materiality_assessment?: string; substitutability?: string; concentration_level?: string; concentration_note?: string;
};
type Vendor = {
  id: string; name: string; description: string; type_id: string | null;
  /** Legacy text (the picked value's label once `category_id` is set). */
  category: string; category_id: string | null; category_ref: LookupRef | null;
  /** From the country list; `location` stays free text (city / address). */
  country_id: string | null; country_ref: LookupRef | null;
  contact_name: string; contact_email: string; contact_phone: string; website: string; location: string;
  criticality: string; status: string; risk_rating: string | null; shares_data: boolean;
  /** Read-only: moved by the approval lifecycle (WorkflowFields). */
  workflow_status: string;
  assessment_status: string; last_assessed_at: string | null; onboarded_at: string | null; offboarded_at: string | null;
  review_frequency: string; next_review_date: string | null; type: VendorType | null; contracts: ServiceContract[];
  risks: RefItem[]; assets: RefItem[]; requirements: RefItem[]; controls: RefItem[]; contract_count: number; active_contract_value: number; created_at: string;
  /** Live contract value per currency. */
  active_contract_totals?: Record<string, number>;
  // reverse graph links (read-only, from GET /vendors/{id})
  incidents?: RefItem[]; assessments?: RefItem[]; outsourcing_arrangements?: RefItem[];
  // Phase 2 due diligence
  legal_name?: string; registration_number?: string;
  relationship_owner_id?: string | null; relationship_owner_ref?: UserRef | null;
  data_classification_id?: string | null; data_classification_ref?: LookupRef | null;
  annual_spend?: number | null; spend_currency?: string;
  data_residency_countries?: LookupRef[]; processes?: RefItem[]; subcontractors?: RefItem[]; subcontractor_of?: RefItem[];
  certifications?: Certification[];
  /** Derived from the "Inherent risk tiering" questionnaire; never typed. */
  inherent_tier?: string | null; tier_override_reason?: string; tiering?: Tiering | null;
  /** Phase 4E: the latest reviewed due-diligence questionnaire and the rating it proposes. */
  due_diligence?: VendorDueDiligenceFacts | null; risk_rating_override_reason?: string;
  outsourcing?: OutsourcingFact[];
  concentration?: VendorConcentrationFacts | null;
};

/* ------------------------------------------------------------------ enum options */
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const CRITICALITY = opts(["low", "medium", "high", "critical"]);
const STATUS = opts(["prospective", "active", "suspended", "offboarded"]);
/** Register filters, kept in the URL: the dashboard's third-party line opens
 *  `/vendors?criticality=critical` and `/vendors?review=overdue`. */
const VENDOR_FILTERS = {
  criticality: ["low", "medium", "high", "critical"],
  review: ["overdue"],
} as const satisfies FilterSpec;
const RISK_RATING = opts(["low", "medium", "high", "critical"]);
const ASSESS = opts(["not_started", "in_progress", "completed"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
/** Fixed list, as the server accepts it (schemas/vendor.py CERT_TYPES). */
const CERT_TYPES: Option[] = [
  { value: "iso_27001", label: "ISO 27001" }, { value: "iso_22301", label: "ISO 22301" },
  { value: "soc1", label: "SOC 1" }, { value: "soc2_type1", label: "SOC 2 Type I" },
  { value: "soc2_type2", label: "SOC 2 Type II" }, { value: "pci_dss", label: "PCI DSS" },
  { value: "csa_star", label: "CSA STAR" }, { value: "other", label: "Other" },
];
const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = { active: "low", prospective: "info", suspended: "medium", offboarded: "neutral" };
const ASSESS_TONE: Record<string, "low" | "medium" | "neutral"> = { completed: "low", in_progress: "medium", not_started: "neutral" };
const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
const categoryName = (v: Vendor) => v.category_ref?.label || v.category || "";
const refToOpt = (x: RefItem): AsyncOption => ({ value: x.id, label: x.title || x.name || x.reference || x.id });
const personName = (u: UserRef | null | undefined) => (u ? u.full_name || u.email : "");

function ExpiryBadge({ c, formatDate }: { c: Certification; formatDate: (d: string | null) => string }) {
  if (c.expiry_state === "expired") return <Badge tone="critical" asIs>Expired {formatDate(c.expires_on)}</Badge>;
  if (c.expiry_state === "expiring") return <Badge tone="medium" asIs>Expires in {c.days_to_expiry} day{c.days_to_expiry === 1 ? "" : "s"}</Badge>;
  if (c.expiry_state === "valid") return <Badge tone="low" asIs>Valid to {formatDate(c.expires_on)}</Badge>;
  return <Badge tone="neutral" asIs>No expiry recorded</Badge>;
}

/* ---------------------------------------------------------------- record copy */
/* The third party's judgement wording (tiles, open points, headline, the review and
   override rules the header shares) lives in lib/record/vendor.ts, pinned by
   lib/record/__fixtures__/vendor-*.json. */
const sevTone = vendorSevTone;

/** Labels of the built-in fields a custom field could duplicate (admins get a note). */
const VENDOR_BUILT_IN_LABELS = ["Relationship owner", "Owner", "Criticality", "Status", "Category", "Type", "Country", "Risk rating", "Data classification"];

/* -------------------------------------------------------------------- form state */
type FormState = {
  name: string; description: string; category_id: string | null; type_id: string; contact_name: string; contact_email: string;
  contact_phone: string; website: string; location: string; country_id: string | null; criticality: string; status: string;
  shares_data: boolean; risk_rating: string; assessment_status: string; last_assessed_at: string; onboarded_at: string;
  offboarded_at: string; review_frequency: string; next_review_date: string; risk_ids: AsyncOption[]; asset_ids: AsyncOption[];
  requirement_ids: AsyncOption[]; control_ids: AsyncOption[];
  // due diligence
  legal_name: string; registration_number: string; relationship_owner_id: string | null; data_classification_id: string | null;
  annual_spend: number | ""; spend_currency: string; residency: AsyncOption[]; process_ids: AsyncOption[];
  subcontractor_ids: AsyncOption[]; tier_override_reason: string; risk_rating_override_reason: string;
};
const BLANK: FormState = {
  name: "", description: "", category_id: null, type_id: "", contact_name: "", contact_email: "", contact_phone: "", website: "",
  location: "", country_id: null, criticality: "medium", status: "active", shares_data: false, risk_rating: "",
  assessment_status: "not_started", last_assessed_at: "", onboarded_at: "", offboarded_at: "", review_frequency: "annual",
  next_review_date: "", risk_ids: [], asset_ids: [], requirement_ids: [], control_ids: [],
  legal_name: "", registration_number: "", relationship_owner_id: null, data_classification_id: null,
  annual_spend: "", spend_currency: "", residency: [], process_ids: [], subcontractor_ids: [], tier_override_reason: "", risk_rating_override_reason: "",
};
function fromVendor(v: Vendor): FormState {
  return {
    name: v.name, description: v.description || "", category_id: v.category_id, type_id: v.type_id || "",
    contact_name: v.contact_name || "", contact_email: v.contact_email || "", contact_phone: v.contact_phone || "",
    website: v.website || "", location: v.location || "", country_id: v.country_id, criticality: v.criticality, status: v.status,
    shares_data: v.shares_data, risk_rating: v.risk_rating || "",
    assessment_status: v.assessment_status, last_assessed_at: v.last_assessed_at || "", onboarded_at: v.onboarded_at || "",
    offboarded_at: v.offboarded_at || "", review_frequency: v.review_frequency, next_review_date: v.next_review_date || "",
    risk_ids: v.risks.map(refToOpt), asset_ids: v.assets.map(refToOpt),
    requirement_ids: (v.requirements ?? []).map(refToOpt), control_ids: (v.controls ?? []).map(refToOpt),
    legal_name: v.legal_name || "", registration_number: v.registration_number || "",
    relationship_owner_id: v.relationship_owner_id ?? null, data_classification_id: v.data_classification_id ?? null,
    annual_spend: v.annual_spend ?? "", spend_currency: v.spend_currency || "",
    residency: (v.data_residency_countries ?? []).map((c) => ({ value: c.id, label: c.label })),
    process_ids: (v.processes ?? []).map(refToOpt), subcontractor_ids: (v.subcontractors ?? []).map(refToOpt),
    tier_override_reason: v.tier_override_reason || "",
    risk_rating_override_reason: v.risk_rating_override_reason || "",
  };
}
function toPayload(f: FormState, editing: boolean): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    name: f.name, description: f.description, category_id: f.category_id, type_id: f.type_id || null, contact_name: f.contact_name,
    contact_email: f.contact_email, contact_phone: f.contact_phone, website: f.website, location: f.location,
    country_id: f.country_id, criticality: f.criticality, status: f.status, shares_data: f.shares_data,
    risk_rating: f.risk_rating || null, assessment_status: f.assessment_status, last_assessed_at: f.last_assessed_at || null,
    onboarded_at: f.onboarded_at || null, offboarded_at: f.offboarded_at || null, review_frequency: f.review_frequency,
    next_review_date: f.next_review_date || null, risk_ids: f.risk_ids.map((o) => o.value), asset_ids: f.asset_ids.map((o) => o.value),
    requirement_ids: f.requirement_ids.map((o) => o.value), control_ids: f.control_ids.map((o) => o.value),
    legal_name: f.legal_name, registration_number: f.registration_number,
    relationship_owner_id: f.relationship_owner_id, data_classification_id: f.data_classification_id,
    annual_spend: f.annual_spend === "" ? null : f.annual_spend, spend_currency: f.spend_currency,
    data_residency_country_ids: f.residency.map((o) => o.value), process_ids: f.process_ids.map((o) => o.value),
    subcontractor_ids: f.subcontractor_ids.map((o) => o.value),
  };
  // The override reason only exists once a tier does; the server clears it when the
  // criticality matches the tier's proposal.
  if (editing) payload.tier_override_reason = f.tier_override_reason;
  // Phase 4E: the same rule for a risk rating that differs from due diligence's proposal.
  if (editing) payload.risk_rating_override_reason = f.risk_rating_override_reason;
  return payload;
}
type ContractForm = { name: string; description: string; value: number | ""; currency: string; start_date: string; end_date: string };
const BLANK_CONTRACT: ContractForm = { name: "", description: "", value: "", currency: "", start_date: "", end_date: "" };
type CertForm = { id: string | null; cert_type: string; issuer: string; certificate_number: string; scope: string; issued_on: string; expires_on: string };
const BLANK_CERT: CertForm = { id: null, cert_type: "iso_27001", issuer: "", certificate_number: "", scope: "", issued_on: "", expires_on: "" };

/* ================================================================ page ===== */
function VendorsInner() {
  const { formatDate, formatMoney, currency, currencyOptions } = useFormat();
  const router = useRouter();
  /** Money in its own currency; a blank currency is the organisation's. */
  const money = (n: number, ccy?: string | null) => formatMoney(n, ccy || currency);
  const totals = (v: Vendor) => {
    const t = v.active_contract_totals;
    if (t && Object.keys(t).length) return Object.entries(t).map(([c, n]) => money(n, c)).join(" + ");
    return money(v.active_contract_value);
  };
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Vendor | null>(null);
  const [types, setTypes] = useState<VendorType[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [editing, setEditing] = useState<Vendor | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const [contract, setContract] = useState<ContractForm>(BLANK_CONTRACT);
  const [contractBusy, setContractBusy] = useState(false);
  const [cert, setCert] = useState<CertForm>(BLANK_CERT);
  const [certBusy, setCertBusy] = useState(false);
  const [tierBusy, setTierBusy] = useState(false);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  const setC = <K extends keyof ContractForm>(k: K, v: ContractForm[K]) => setContract((p) => ({ ...p, [k]: v }));
  const setCt = <K extends keyof CertForm>(k: K, v: CertForm[K]) => setCert((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const filters = useFilterParams(VENDOR_FILTERS);
  const fetchVendors = useCallback((qs: string) => apiCall<PagedList<Vendor>>("GET", `/vendors?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<Vendor>("GET", `/vendors/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // ---- the record page (dossier, record-page-spec §4.8) ----
  const gov = useRecordGovernanceData("vendor", detail?.id ?? null, { statusRulesModel: "vendor" });
  const canWrite = useHasPermission("vendor:write");
  const canRaiseIssue = useHasPermission("issue:write");
  const ctx = useRecordCtx(gov, canWrite);
  const sections = useRecordSections();
  const cf = useCustomFieldFacts("vendor", detail?.id, { builtInLabels: VENDOR_BUILT_IN_LABELS });
  /** FormModal tab to open on (a header gap, an open point or a "Fill in"). */
  const [editTab, setEditTab] = useState<string | undefined>(undefined);
  /** The Issues section (the shared kit: list + Raise issue form); More › "Raise issue…"
   *  opens its form. */
  const issuesRef = useRef<RecordIssuesHandle>(null);
  /** After any change: the governance (primary, sign-off, rules), the record, the list. */
  const refresh = () => {
    void gov.reload();
    if (openId) loadDetail(openId);
    reload();
  };
  useEffect(() => { apiCall<VendorType[]>("GET", "/vendor-types").then(setTypes).catch(() => {}); }, []);

  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((c) => ({ value: c.id, label: c.name, sub: c.reference })));
  const searchCountries = (q: string) => lookupValues("country", { search: q }).then((rows) => rows.slice(0, 30).map((c) => ({ value: c.id, label: c.label })));
  const searchProcesses = (q: string) => pickProcesses({ search: q }).then((rows) => rows.slice(0, 30).map((p) => ({ value: p.id, label: p.name, sub: p.business_unit_name })));
  // A vendor can't be its own sub-contractor, so it is left out of the choices.
  const searchSubcontractors = (q: string) => apiCall<PagedList<{ id: string; name: string; legal_name?: string }>>("GET", `/vendors?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.filter((x) => x.id !== editing?.id).map((x) => ({ value: x.id, label: x.name, sub: x.legal_name && x.legal_name !== x.name ? x.legal_name : undefined })));

  function openNew() { setEditing(null); setF(BLANK); setContract(BLANK_CONTRACT); setCert(BLANK_CERT); setError(null); setEditTab(undefined); setShowForm(true); }
  function openEdit(v: Vendor, tab?: string) { setEditing(v); setF(fromVendor(v)); setContract(BLANK_CONTRACT); setCert(BLANK_CERT); setError(null); setEditTab(tab); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f, !!editing);
      if (editing) await apiCall<Vendor>("PATCH", `/vendors/${editing.id}`, payload);
      else await apiCall<Vendor>("POST", "/vendors", payload);
      setShowForm(false); refresh(); toast(editing ? "Changes saved" : "Vendor created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save vendor"); }
    finally { setSaving(false); }
  }
  async function remove(v: Vendor) {
    if (!(await confirmDeleteWithImpact("vendor", v.id, v.name, { typeLabel: "third party" }))) return;
    try {
      await apiCall<void>("DELETE", `/vendors/${v.id}`);
      setShowForm(false);
      if (openId === v.id) setOpenId(null);
      reload(); toast(`Deleted ${v.name}`);
    } catch (e) {
      // A 403 is segregation of duties: the server's message says who may delete it.
      toast(errMsg(e, "Failed to delete vendor"), "error");
    }
  }
  async function addContract() {
    if (!editing || !contract.name.trim()) return; setContractBusy(true); setError(null);
    try {
      const updated = await apiCall<Vendor>("POST", `/vendors/${editing.id}/contracts`, { name: contract.name, description: contract.description, value: contract.value === "" ? null : contract.value, currency: contract.currency, start_date: contract.start_date || null, end_date: contract.end_date || null });
      setEditing(updated); setContract(BLANK_CONTRACT); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to add contract"); }
    finally { setContractBusy(false); }
  }
  async function removeContract(contractId: string) {
    if (!editing) return;
    if (!(await confirmDialog({ title: "Remove this contract?", message: "The contract is deleted for good; this can't be undone.", confirmLabel: "Remove", danger: true }))) return;
    setContractBusy(true); setError(null);
    try {
      await apiCall<void>("DELETE", `/vendors/contracts/${contractId}`);
      setEditing(await apiCall<Vendor>("GET", `/vendors/${editing.id}`)); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete contract"); }
    finally { setContractBusy(false); }
  }

  /* ----------------------------------------------------------- certifications */
  async function saveCert() {
    if (!editing) return; setCertBusy(true); setError(null);
    const body = { cert_type: cert.cert_type, issuer: cert.issuer, certificate_number: cert.certificate_number, scope: cert.scope, issued_on: cert.issued_on || null, expires_on: cert.expires_on || null };
    try {
      if (cert.id) await apiCall<Certification>("PATCH", `/vendors/${editing.id}/certifications/${cert.id}`, body);
      else await apiCall<Certification>("POST", `/vendors/${editing.id}/certifications`, body);
      setEditing(await apiCall<Vendor>("GET", `/vendors/${editing.id}`)); setCert(BLANK_CERT); reload();
      if (openId === editing.id) loadDetail(editing.id);
    } catch (e) { setError(errMsg(e, "Failed to save certification")); }
    finally { setCertBusy(false); }
  }
  function editCert(c: Certification) {
    setCert({ id: c.id, cert_type: c.cert_type, issuer: c.issuer, certificate_number: c.certificate_number, scope: c.scope, issued_on: c.issued_on || "", expires_on: c.expires_on || "" });
  }
  async function removeCert(c: Certification) {
    if (!editing) return;
    if (!(await confirmDialog({ title: `Remove the ${c.cert_type_label} certification?`, message: "Its expiry alerts stop. The removal is recorded in the activity log.", confirmLabel: "Remove", danger: true }))) return;
    setCertBusy(true); setError(null);
    try {
      await apiCall<void>("DELETE", `/vendors/${editing.id}/certifications/${c.id}`);
      setEditing(await apiCall<Vendor>("GET", `/vendors/${editing.id}`)); if (cert.id === c.id) setCert(BLANK_CERT); reload();
    } catch (e) { setError(errMsg(e, "Failed to remove certification")); }
    finally { setCertBusy(false); }
  }

  /* ------------------------------------------------------------------ tiering */
  async function recomputeTier(v: Vendor) {
    setTierBusy(true);
    try {
      const updated = await apiCall<Vendor>("POST", `/vendors/${v.id}/tiering`);
      setDetail(updated); refresh(); toast(`Inherent tier: ${updated.inherent_tier ? sentenceCase(updated.inherent_tier) : "not set"}`);
    } catch (e) { toast(errMsg(e, "Could not compute the tier"), "error"); }
    finally { setTierBusy(false); }
  }
  async function startTiering(v: Vendor) {
    const qid = v.tiering?.questionnaire_id;
    if (!qid) { toast("The 'Inherent risk tiering' questionnaire is missing; it is re-created on the next server start, or build it under Questionnaires.", "error"); return; }
    setTierBusy(true);
    try {
      const created = await apiCall<{ id: string }>("POST", "/assessments", { title: `Inherent risk tiering — ${v.name}`, vendor_id: v.id, questionnaire_id: qid });
      router.push(`/assessments?id=${created.id}`);
    } catch (e) { toast(errMsg(e, "Could not start the tiering assessment"), "error"); }
    finally { setTierBusy(false); }
  }

  const typeOpts: Option[] = useMemo(() => types.map((t) => ({ value: t.id, label: t.name })), [types]);
  const linkCount = (v: Vendor) => v.risks.length + v.assets.length;
  const proposed = editing?.tiering?.proposed_criticality || null;
  const overriding = !!(editing?.inherent_tier && proposed && f.criticality !== proposed);

  const columns: Column<Vendor>[] = [
    { key: "name", header: "Name", sortable: true, render: (v) => <span className="cell-title">{v.name}{v.shares_data && <> <Badge tone="info" plain>data</Badge></>}</span> },
    { key: "category", header: "Type / Category", sortable: true, render: (v) => <span className="muted">{[v.type?.name, categoryName(v)].filter(Boolean).join(" · ") || "—"}</span>, text: (v) => [v.type?.name, categoryName(v)].filter(Boolean).join(" · ") },
    { key: "country", header: "Country", render: (v) => <span className="muted">{v.country_ref?.label || "—"}</span>, text: (v) => v.country_ref?.label || "" },
    { key: "inherent_tier", header: "Inherent tier", sortable: true, render: (v) => <Severity value={v.inherent_tier || null} />, text: (v) => v.inherent_tier || "" },
    { key: "criticality", header: "Criticality", sortable: true, render: (v) => <span><Severity value={v.criticality} />{v.tiering?.overridden && <span className="muted" title={v.tier_override_reason} style={{ fontSize: 11, marginLeft: 4 }}>override</span>}</span> },
    { key: "status", header: "Status", sortable: true, render: (v) => <Badge tone={STATUS_TONE[v.status] || "neutral"}>{cap(v.status)}</Badge> },
    { key: "risk_rating", header: "Risk rating", sortable: true, render: (v) => <Severity value={v.risk_rating} /> },
    { key: "assessment_status", header: "Assessment", sortable: true, render: (v) => <Badge tone={ASSESS_TONE[v.assessment_status] || "neutral"}>{cap(v.assessment_status)}</Badge> },
    { key: "contracts", header: "Contracts", render: (v) => <span className="muted">{v.contract_count > 0 ? `${v.contract_count} · ${totals(v)}` : "—"}</span> },
    { key: "links", header: "Links", align: "center", render: (v) => <span className="muted">{linkCount(v) || "—"}</span> },
    { key: "actions", header: "", render: (v) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" {...rowAction("Edit", v.name)} onClick={() => openEdit(v)}>Edit</button> <button className="btn secondary sm" {...rowAction("Delete", v.name)} onClick={() => remove(v)}>Delete</button></div> },
  ];

  /* -------------------------------- form tabs -------------------------------- */
  const generalTab = (
    <>
      <Field label="Name" required help="The name the bank knows the third party by, e.g. 1LINK, Systems Ltd, Microsoft Azure."><TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="e.g. 1LINK" required /></Field>
      <Field label="Description"><TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this third party provides and how the bank uses it." /></Field>
      <div className="field-row">
        <Field label="Category">
          <LookupSelect
            lookupKey="vendor_category"
            value={f.category_id}
            onChange={(id) => set("category_id", id)}
            legacyText={editing && !editing.category_id ? editing.category : null}
            allowCreate
          />
        </Field>
        <Field label="Type" help="Third-party taxonomy (managed in Settings → Lookups).">
          <Select value={f.type_id} onChange={(v) => set("type_id", v)} options={typeOpts} placeholder="Choose a type…" />
          <InlineLookupCreate
            endpoint="/vendor-types"
            onCreated={(r) => { setTypes((p) => [...p, r as VendorType]); set("type_id", r.id); }}
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Contact Name"><TextInput value={f.contact_name} onChange={(v) => set("contact_name", v)} placeholder="Relationship manager" /></Field>
        <Field label="Contact Email"><TextInput value={f.contact_email} onChange={(v) => set("contact_email", v)} type="email" placeholder="e.g. accounts@vendor.com.pk" /></Field>
      </div>
      <div className="field-row">
        <Field label="Contact Phone"><TextInput value={f.contact_phone} onChange={(v) => set("contact_phone", v)} placeholder="e.g. +92 21 3456 7890" /></Field>
        <Field label="Website"><TextInput value={f.website} onChange={(v) => set("website", v)} placeholder="e.g. https://www.vendor.com.pk" /></Field>
      </div>
      <div className="field-row">
        <Field label="Country" help="Where the third party is based — drives offshoring and concentration reporting.">
          <LookupSelect lookupKey="country" value={f.country_id} onChange={(id) => set("country_id", id)} placeholder="Choose a country…" />
        </Field>
        <Field label="Location" help="City or address."><TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="e.g. Karachi, PK" /></Field>
      </div>
      <div className="field-row">
        <Field
          label="Criticality"
          help={editing?.inherent_tier && proposed
            ? `The ${editing.inherent_tier} inherent tier proposes ${proposed}. Choosing anything else needs a reason.`
            : "How critical this third party is to your operations. Set by the inherent risk tier once a tiering assessment is completed."}
        >
          <Select value={f.criticality} onChange={(v) => set("criticality", v)} options={CRITICALITY} />
        </Field>
        <Field label="Status"><Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} /></Field>
      </div>
      {overriding && (
        <Field label="Reason for overriding the tier" required help={`Recorded in the activity log. Pick ${proposed} instead to follow the tier.`}>
          <TextArea value={f.tier_override_reason} onChange={(v) => set("tier_override_reason", v)} rows={2} placeholder="e.g. Sole provider of RAAST connectivity; the board treats it as critical regardless of score." />
        </Field>
      )}
      <Field label="Shares / processes data" help="Toggle on if this vendor stores, processes or has access to your data."><Toggle checked={f.shares_data} onChange={(v) => set("shares_data", v)} label="Vendor handles our data" /></Field>
    </>
  );
  const diligenceTab = (
    <>
      <div className="field-row">
        <Field label="Legal name" help="Registered name, if it differs from the trading name."><TextInput value={f.legal_name} onChange={(v) => set("legal_name", v)} placeholder="e.g. 1LINK (Private) Limited" /></Field>
        <Field label="Registration number" help="SECP incorporation / company registration number."><TextInput value={f.registration_number} onChange={(v) => set("registration_number", v)} placeholder="e.g. 0045678" /></Field>
      </div>
      <div className="field-row">
        <Field label="Relationship owner" help="The bank's accountable owner of this relationship.">
          <UserPicker value={f.relationship_owner_id} onChange={(id) => set("relationship_owner_id", id)} selected={editing?.relationship_owner_ref ?? null} />
        </Field>
        <Field label="Data classification" help="Highest classification of bank data this third party can access.">
          <LookupSelect lookupKey="data_classification" value={f.data_classification_id} onChange={(id) => set("data_classification_id", id)} placeholder="Choose a classification…" />
        </Field>
      </div>
      <Field label="Data residency" help="Countries where the third party stores or processes the bank's data, including DR sites.">
        <AsyncMultiSelect search={searchCountries} value={f.residency} onChange={(v) => set("residency", v)} placeholder="Search countries…" />
      </Field>
      <Field label="Processes supported" help="Business processes that depend on this third party.">
        <AsyncMultiSelect search={searchProcesses} value={f.process_ids} onChange={(v) => set("process_ids", v)} placeholder="Search processes…" />
      </Field>
      <Field label="Sub-contractors (fourth parties)" help="Other registered third parties this one relies on to deliver the service.">
        <AsyncMultiSelect search={searchSubcontractors} value={f.subcontractor_ids} onChange={(v) => set("subcontractor_ids", v)} placeholder="Search the vendor register…" />
      </Field>
      <div className="field-row">
        <Field label="Annual spend"><NumberInput value={f.annual_spend} onChange={(v) => set("annual_spend", v)} min={0} placeholder="e.g. 12500000" /></Field>
        <Field label="Spend currency">
          <Select value={f.spend_currency} onChange={(v) => set("spend_currency", v)} options={currencyOptions} placeholder={`Organisation default (${currency})`} />
        </Field>
      </div>
    </>
  );
  const riskTab = (
    <>
      {editing?.due_diligence?.proposed_rating && f.risk_rating !== editing.due_diligence.proposed_rating && (
        <Field label="Reason for overriding due diligence" required help={`Recorded in the activity log. Pick ${editing.due_diligence.proposed_rating} instead to follow due diligence.`}>
          <TextArea value={f.risk_rating_override_reason} onChange={(v) => set("risk_rating_override_reason", v)} rows={2} placeholder="e.g. Compensating controls tested by internal audit in August." />
        </Field>
      )}
      <div className="field-row">
        <Field label="Risk Rating" help={editing?.due_diligence?.proposed_rating
          ? `Due diligence (${editing.due_diligence.band || "no band"}) proposes ${editing.due_diligence.proposed_rating}. Choosing anything else needs a reason.`
          : "Overall residual risk this vendor poses. Set by a reviewed due-diligence questionnaire."}><Select value={f.risk_rating} onChange={(v) => set("risk_rating", v)} options={RISK_RATING} placeholder="Not rated" /></Field>
        <Field label="Assessment Status"><Select value={f.assessment_status} onChange={(v) => set("assessment_status", v)} options={ASSESS} /></Field>
        <Field label="Last Assessed"><TextInput value={f.last_assessed_at} onChange={(v) => set("last_assessed_at", v)} type="date" /></Field>
      </div>
      <div className="field-row">
        <Field label="Review Frequency" help="How often this vendor relationship should be reviewed."><Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} /></Field>
        <Field label="Next Review Date"><TextInput value={f.next_review_date} onChange={(v) => set("next_review_date", v)} type="date" /></Field>
      </div>
      <div className="field-row">
        <Field label="Onboarded"><TextInput value={f.onboarded_at} onChange={(v) => set("onboarded_at", v)} type="date" /></Field>
        <Field label="Offboarded"><TextInput value={f.offboarded_at} onChange={(v) => set("offboarded_at", v)} type="date" /></Field>
      </div>
    </>
  );
  const contractsTab = (
    <>
      {!editing && <div className="card card-pad" style={{ marginBottom: 14 }}>Save the vendor first, then add service contracts here.</div>}
      {editing && (
        <>
          <div className="table-wrap" style={{ marginBottom: 16 }}>
            <table>
              <thead><tr><th>Contract</th><th>Value</th><th>Start</th><th>End</th><th>State</th><th></th></tr></thead>
              <tbody>
                {editing.contracts.map((c) => (
                  <tr key={c.id}>
                    <td className="cell-title">{c.name}</td>
                    <td className="muted">{c.value != null ? money(c.value, c.currency) : "—"}</td>
                    <td className="muted">{formatDate(c.start_date)}</td>
                    <td className="muted">{formatDate(c.end_date)}</td>
                    <td>{c.is_expired ? <Badge tone="high">Expired</Badge> : <Badge tone="low">Active</Badge>}</td>
                    <td><button className="btn secondary sm" type="button" disabled={contractBusy} {...rowAction("Remove", c.name)} onClick={() => removeContract(c.id)}>Remove</button></td>
                  </tr>
                ))}
                {editing.contracts.length === 0 && <tr><td colSpan={6}><span className="muted">No contracts yet.</span></td></tr>}
              </tbody>
            </table>
          </div>
          <div className="card card-pad">
            <Field label="Add Contract" help="Record a contract, SLA or order with this vendor."><TextInput value={contract.name} onChange={(v) => setC("name", v)} placeholder="e.g. Master Services Agreement" /></Field>
            <Field label="Description"><TextArea value={contract.description} onChange={(v) => setC("description", v)} rows={2} /></Field>
            <div className="field-row">
              <Field label="Value"><NumberInput value={contract.value} onChange={(v) => setC("value", v)} min={0} placeholder="e.g. 5000000" /></Field>
              <Field label="Currency"><Select value={contract.currency} onChange={(v) => setC("currency", v)} options={currencyOptions} placeholder={`Organisation default (${currency})`} /></Field>
            </div>
            <div className="field-row">
              <Field label="Start Date"><TextInput value={contract.start_date} onChange={(v) => setC("start_date", v)} type="date" /></Field>
              <Field label="End Date"><TextInput value={contract.end_date} onChange={(v) => setC("end_date", v)} type="date" /></Field>
            </div>
            <button className="btn" type="button" disabled={contractBusy || !contract.name.trim()} onClick={addContract}><IconPlus width={16} height={16} /> Add contract</button>
          </div>
        </>
      )}
    </>
  );
  const certsTab = (
    <>
      {!editing && <div className="card card-pad" style={{ marginBottom: 14 }}>Save the vendor first, then record its certifications here.</div>}
      {editing && (
        <>
          <div className="table-wrap" style={{ marginBottom: 16 }}>
            <table>
              <thead><tr><th>Certification</th><th>Issuer</th><th>Number</th><th>Issued</th><th>Expiry</th><th></th></tr></thead>
              <tbody>
                {(editing.certifications ?? []).map((c, ci, all) => {
                  // The row's name (decision D3): type, then scope or number; still unique.
                  const cl = uniqueLabels(all.map((x) => {
                    const extra = (x.scope || "").trim() || (x.certificate_number || "").trim();
                    return extra ? `${x.cert_type_label} (${extra})` : x.cert_type_label;
                  }))[ci];
                  return (
                  <tr key={c.id}>
                    <td className="cell-title">{c.cert_type_label}{c.scope && <div className="muted" style={{ fontSize: 12 }}>{c.scope}</div>}</td>
                    <td className="muted">{c.issuer || "—"}</td>
                    <td className="muted">{c.certificate_number || "—"}</td>
                    <td className="muted">{formatDate(c.issued_on)}</td>
                    <td><ExpiryBadge c={c} formatDate={formatDate} /></td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="btn secondary sm" type="button" disabled={certBusy} {...rowAction("Edit", cl)} onClick={() => editCert(c)}>Edit</button>{" "}
                      <button className="btn secondary sm" type="button" disabled={certBusy} {...rowAction("Remove", cl)} onClick={() => removeCert(c)}>Remove</button>
                    </td>
                  </tr>
                  );
                })}
                {(editing.certifications ?? []).length === 0 && <tr><td colSpan={6}><span className="muted">No certifications recorded.</span></td></tr>}
              </tbody>
            </table>
          </div>
          <div className="card card-pad">
            <strong style={{ fontSize: 13 }}>{cert.id ? "Edit certification" : "Add certification"}</strong>
            <div className="field-row" style={{ marginTop: 8 }}>
              <Field label="Type" required><Select value={cert.cert_type} onChange={(v) => setCt("cert_type", v)} options={CERT_TYPES} /></Field>
              <Field label="Issuer" help="Certification body or audit firm."><TextInput value={cert.issuer} onChange={(v) => setCt("issuer", v)} placeholder="e.g. BSI, A. F. Ferguson & Co." /></Field>
              <Field label="Certificate number"><TextInput value={cert.certificate_number} onChange={(v) => setCt("certificate_number", v)} placeholder="e.g. IS 123456" /></Field>
            </div>
            <Field label="Scope" help="What the certificate or report covers."><TextArea value={cert.scope} onChange={(v) => setCt("scope", v)} rows={2} placeholder="e.g. Switching and ATM network operations, Karachi and Lahore data centres." /></Field>
            <div className="field-row">
              <Field label="Issued on"><TextInput value={cert.issued_on} onChange={(v) => setCt("issued_on", v)} type="date" /></Field>
              <Field label="Expires on" help="An alert is raised 60 days before this date, and again once it has passed."><TextInput value={cert.expires_on} onChange={(v) => setCt("expires_on", v)} type="date" /></Field>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" type="button" disabled={certBusy || !cert.cert_type} onClick={saveCert}>{cert.id ? "Save certification" : <><IconPlus width={16} height={16} /> Add certification</>}</button>
              {cert.id && <button className="btn secondary" type="button" disabled={certBusy} onClick={() => setCert(BLANK_CERT)}>Cancel</button>}
            </div>
          </div>
        </>
      )}
    </>
  );
  const linksTab = (
    <>
      <Field label="Related Risks" help="Risks this vendor introduces or is associated with."><AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} /></Field>
      <Field label="Related Assets" help="Assets or data this vendor touches, hosts or has access to."><AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} /></Field>
      <Field label="Compliance requirements" help="Framework requirements this vendor is subject to."><AsyncMultiSelect search={searchRequirements} value={f.requirement_ids} onChange={(v) => set("requirement_ids", v)} /></Field>
      <Field label="Mitigating controls" help="Controls that mitigate the risk this vendor introduces."><AsyncMultiSelect search={searchControls} value={f.control_ids} onChange={(v) => set("control_ids", v)} /></Field>
    </>
  );

  const tiering = detail?.tiering;

  // ---- dossier: the open third party's header, open points and sections ----
  const vendorInput: VendorInput | null = detail ? { vendor: detail } : null;
  function openIssueForm() {
    issuesRef.current?.raise();
  }
  /** Open-point fixes only move: scroll, focus, open Edit on a tab or open a form. */
  function handlePoint(a: PointAction) {
    if (!detail) return;
    if (a.kind === "section") sections.scrollTo(a.target);
    else if (a.kind === "edit") openEdit(detail, a.target);
    else if (a.kind === "focus") document.getElementById(a.target)?.focus();
    else if (a.kind === "attest") gov.openAttest();
    else if (a.kind === "href") router.push(a.target);
    else if (a.kind === "open" && a.target === "raise-issue") openIssueForm();
  }
  const reviewOverdue = !!detail && vendorReviewOverdue(detail, ctx.now);
  const ownerText = detail ? personName(detail.relationship_owner_ref) : "";
  const overrideNote = detail ? vendorOverrideNote(detail) : null;
  // Header meta (record-page-spec §4.8, v1.1 D1): Third-party status, Record approval,
  // then Relationship owner, Criticality, Assessment, Next review.
  const statusMeta: MetaItem | undefined = detail ? {
    key: "status", label: "Third-party status",
    value: <Badge tone={STATUS_TONE[detail.status] || "neutral"} asIs>{sentenceCase(detail.status)}</Badge>,
    hint: "Where the relationship is: prospective, active, suspended or offboarded. Separate from record approval.",
  } : undefined;
  const vendorMeta: MetaItem[] = detail ? [
    {
      key: "owner", label: "Relationship owner", value: ownerText || null, hint: "The bank's accountable owner of this relationship.",
      gap: ownerText ? undefined : { text: "Not assigned", fix: canWrite ? { label: "Assign", onClick: () => openEdit(detail, "diligence") } : undefined },
    },
    {
      key: "criticality", label: "Criticality",
      value: <Badge tone={sevTone(detail.criticality)} asIs>{sentenceCase(detail.criticality)}</Badge>,
      sub: overrideNote ? <span style={{ color: "var(--amber)" }}>{overrideNote}</span> : undefined,
      hint: "How critical the third party is to operations. The inherent tier proposes it.",
    },
    {
      key: "assessment", label: "Assessment", value: sentenceCase(detail.assessment_status),
      sub: detail.last_assessed_at ? `last ${formatDate(detail.last_assessed_at)}` : undefined,
    },
    {
      key: "review", label: "Next review",
      value: reviewOverdue && detail.next_review_date
        ? <Badge tone="high" asIs>Overdue since {formatDate(detail.next_review_date)}</Badge>
        : detail.next_review_date ? formatDate(detail.next_review_date) : <span className="muted">Not scheduled</span>,
      sub: detail.review_frequency && detail.review_frequency !== "none" ? sentenceCase(detail.review_frequency) : undefined,
      hint: "Attesting the third party records the review and moves this date.",
    },
  ] : [];
  /** SBP outsourcing facts in Due diligence (F-11): materiality and its rationale,
   *  substitutability and concentration — edited under Outsourcing, so a missing one
   *  links there rather than to this form. */
  function outsourcingFacts(v: Vendor) {
    const d = vendorOutsourcingDiligence(v);
    const live = (v.outsourcing ?? []).filter((o) => o.status !== "terminated");
    const conc = v.concentration ?? null;
    const edit = (label: string) => live.length === 1
      ? <Link href={`/outsourcing?id=${live[0].id}`}>{label}</Link>
      : <Link href="/outsourcing">{label}</Link>;
    const items = [];
    if (!live.length) {
      if (conc?.arrangement_expected) {
        items.push({
          key: "outsourcing", label: "Outsourcing",
          value: <span>None recorded. <Link href={`/outsourcing?new=1&vendor_id=${encodeURIComponent(v.id)}`}>Decide whether this is material outsourcing</Link></span>,
          hint: "A critical third party, or one supporting a critical process, usually needs an SBP outsourcing arrangement on file.",
        });
      }
    } else {
      items.push({ key: "outsourcing", label: "Outsourcing", value: d.materiality });
      items.push({ key: "materiality_rationale", label: "Materiality rationale", wide: true, value: d.rationale ?? edit("Not recorded — add it under Outsourcing") });
      const hard = live.some((o) => o.materiality === "material" && (o.substitutability === "difficult" || o.substitutability === "none"));
      items.push({
        key: "substitutability", label: "Substitutability",
        hint: "How hard it would be to move the service to another provider. SBP expects a tested exit plan where it is difficult or impossible.",
        value: d.substitutability
          ? (hard ? <span style={{ color: "var(--orange)" }}>{d.substitutability}</span> : d.substitutability)
          : edit("Not assessed — assess it under Outsourcing"),
      });
    }
    if (conc && (live.length || conc.critical_processes)) {
      items.push({
        key: "concentration", label: "Concentration", wide: true,
        hint: "Derived: high when an arrangement records high concentration, two or more material arrangements rely on this provider, or three or more high or critical processes do.",
        value: (
          <span>
            <Badge tone={conc.level === "high" ? "high" : conc.level === "medium" ? "medium" : "neutral"} asIs>{sentenceCase(conc.level)}</Badge>{" "}
            <span className="muted">{d.concentration}</span>
            {conc.reasons.length > 0 && <span style={{ display: "block", fontSize: 12, color: "var(--orange)" }}>{conc.reasons.join(" ")}</span>}
          </span>
        ),
      });
    }
    return items;
  }
  const linkGroups: RelatedGroup[] = detail ? [
    { key: "risks", label: "Risks", items: detail.risks, href: "/risks" },
    { key: "assets", label: "Assets", items: detail.assets, href: "/information-assets" },
    { key: "requirements", label: "Compliance requirements", items: detail.requirements, href: "/compliance" },
    { key: "controls", label: "Mitigating controls", items: detail.controls, href: "/controls" },
    { key: "incidents", label: "Incidents", items: detail.incidents, href: "/incidents" },
    { key: "assessments", label: "Assessments", items: detail.assessments, href: "/assessments" },
    { key: "outsourcing", label: "Outsourcing arrangements", items: detail.outsourcing_arrangements, href: "/outsourcing" },
  ] : [];
  return (
    <>
      <div className="page-head row-between" style={{ flexWrap: "wrap" }}>
        {/* The actions wrap under the title on a phone instead of widening the page. */}
        <div style={{ flex: "1 1 260px", minWidth: 0 }}>
          <h1>Third-Party Risk</h1>
          <p>Vendor registry with due diligence, inherent risk tier, certifications, contracts and linked risks/assets.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ImportExport resource="vendors" label="Vendors" onDone={reload} />
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add vendor</button>
        </div>
      </div>

      {error && !showForm && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Vendor>
        columns={columns}
        fetcher={fetchVendors}
        rowKey={(v) => v.id}
        onRowClick={(v) => setOpenId(v.id)}
        activeKey={openId}
        searchPlaceholder="Search vendors by name, legal name, registration no. or category…"
        defaultSort={{ by: "name", dir: "asc" }}
        filters={filters.values}
        onApplyFilters={filters.replace}
        toolbarLeft={
          <>
            <select className="select" style={{ maxWidth: 170 }} value={filters.values.criticality ?? ""} onChange={(e) => filters.set("criticality", (e.target.value || undefined) as typeof filters.values.criticality)} aria-label="Criticality">
              <option value="">Any criticality</option>
              {CRITICALITY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }} title="The next review date has passed">
              <input type="checkbox" checked={filters.values.review === "overdue"} onChange={(e) => filters.set("review", e.target.checked ? "overdue" : undefined)} /> Review overdue
            </label>
          </>
        }
        bulkActions={(rows, clear) => (
          <BulkEditBar entityType="vendor" rows={rows} onDone={() => { clear(); reload(); }} />
        )}
        toolbarRight={<ArchivedRecords entityType="vendor" noun="third parties" refreshKey={refreshKey} onRestored={reload} />}
        emptyMessage="No vendors yet. Add the third parties your organization relies on."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        variant="dossier"
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        governance={gov}
        identity={detail ? {
          kind: "Third party",
          backLabel: "Third Parties",
          reference: null,
          name: detail.name,
          lead: detail.description?.trim() || [detail.legal_name, detail.country_ref?.label].filter(Boolean).join(" · ") || null,
          badges: (detail.type?.name || categoryName(detail) || detail.shares_data) ? (
            <>
              {(detail.type?.name || categoryName(detail)) && (
                <>
                  <span className="sep" aria-hidden="true">/</span>
                  <span>{detail.type?.name || categoryName(detail)}</span>
                </>
              )}
              {/* A risk-bearing fact: amber while its classification or residency is missing, never the success green. */}
              {detail.shares_data && <Badge tone={vendorDataTone(detail)} asIs>Handles our data</Badge>}
            </>
          ) : null,
          status: statusMeta,
          approval: approvalMetaItem(gov, ctx.fmt, approvalHintFor("Third-party status")),
          meta: vendorMeta,
          statusRules: { model: "vendor", entityId: detail.id },
        } : undefined}
        primaryAction={(
          <PrimaryAction
            candidates={[{ kind: "workflow", action: "approve" }, { kind: "workflow", action: "submit" }, { kind: "attest" }]}
            onChanged={refresh}
          />
        )}
        onEdit={detail && canWrite ? () => openEdit(detail) : undefined}
        moreItems={detail ? withBaseMoreItems(
          [
            { label: "Start tiering questionnaire", onClick: () => startTiering(detail), disabled: tierBusy, hint: "Opens a new tiering assessment" },
            ...(canWrite && detail.tiering?.assessment ? [{ label: "Recompute tier", onClick: () => recomputeTier(detail), disabled: tierBusy }] : []),
            ...(canRaiseIssue ? [{ label: "Raise issue…", onClick: openIssueForm }] : []),
          ],
          { onDelete: canWrite ? () => remove(detail) : undefined },
        ) : []}
        aside={detail ? (
          <RecordPanels model="vendor" entityId={detail.id} layout="dossier" signOff={{ onChanged: refresh }} trail={{ reference: detail.name }} />
        ) : null}
      >
        {detail && vendorInput && (
          <>
            <SummaryBand tiles={vendorTiles(vendorInput, ctx)} headline={vendorHeadline(vendorInput, ctx)} />
            <OpenPoints
              points={vendorOpenPoints(vendorInput, ctx)}
              canAct={canWrite}
              onAction={handlePoint}
              clearText={VENDOR_CLEAR_TEXT}
            />
            <SectionNav />

            <RecordSection
              id="tiering"
              title="Tiering & assessment"
              actions={(
                <>
                  <button type="button" className="btn secondary sm" disabled={tierBusy} onClick={() => startTiering(detail)}>Start tiering questionnaire</button>
                  {canWrite && tiering?.assessment && (
                    <button type="button" className="btn secondary sm" disabled={tierBusy} onClick={() => recomputeTier(detail)}>Recompute tier</button>
                  )}
                </>
              )}
            >
              {!detail.inherent_tier && !tiering?.assessment ? (
                <p className="rec-empty" style={{ margin: 0, maxWidth: "86ch" }}>
                  Not tiered yet. Start the eight-question “Inherent risk tiering” questionnaire, answer every question and submit it — the tier is written here and proposes the criticality.
                </p>
              ) : (
                <div style={{ display: "grid", gap: 8, fontSize: 13 }}>
                  <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
                    <span>Tier {detail.inherent_tier ? <Badge tone={sevTone(detail.inherent_tier)} asIs>{sentenceCase(detail.inherent_tier)}</Badge> : <Badge hollow asIs>Not tiered</Badge>}</span>
                    {tiering?.proposed_criticality && <span>Proposes criticality <Badge tone={sevTone(tiering.proposed_criticality)} asIs>{sentenceCase(tiering.proposed_criticality)}</Badge></span>}
                    {tiering?.assessment && (
                      <span className="muted">
                        From <Link href={`/assessments?id=${tiering.assessment.id}`}>{tiering.assessment.title || "assessment"}</Link>
                        {tiering.submitted_at ? `, submitted ${formatDate(tiering.submitted_at)}` : ""}
                      </span>
                    )}
                  </div>
                  {tiering?.explanation && (
                    <div className="muted">
                      Score {tiering.explanation}. Bands: 70% and above critical, 45% high, 20% medium, below that low; one worst-case answer makes it at least medium, three at least high.
                    </div>
                  )}
                  {tiering?.stale && (
                    <div style={{ color: "var(--amber)" }}>
                      {tiering.problem || "The latest completed tiering assessment gives a different tier from the one stored."} {!tiering.problem && "Recompute to update it."}
                    </div>
                  )}
                  {tiering?.overridden && (
                    <div>
                      <Badge tone="medium" asIs>Criticality overridden</Badge>{" "}
                      <span className="muted">{vendorOverrideText(detail)}</span>
                    </div>
                  )}
                </div>
              )}
            </RecordSection>

            <RecordSection
              id="diligence"
              title="Due diligence"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit due diligence" onClick={() => openEdit(detail, "diligence")}>Edit</button> : undefined}
            >
              <FactList
                items={[
                  { key: "legal", label: "Legal name", value: detail.legal_name?.trim() || null, tab: "diligence" },
                  { key: "reg", label: "Registration number", value: detail.registration_number?.trim() || null, tab: "diligence" },
                  { key: "rating", label: "Risk rating", value: detail.risk_rating ? <Badge tone={sevTone(detail.risk_rating)} asIs>{sentenceCase(detail.risk_rating)}</Badge> : null, tab: "risk" },
                  {
                    key: "assessment", label: "Assessment", tab: "risk",
                    value: `${sentenceCase(detail.assessment_status)}${detail.last_assessed_at ? ` · last ${formatDate(detail.last_assessed_at)}` : ""}`,
                  },
                  { key: "classification", label: "Data classification", value: detail.data_classification_ref?.label || null, tab: "diligence" },
                  { key: "residency", label: "Data residency", value: (detail.data_residency_countries ?? []).map((c) => c.label).join(", ") || null, tab: "diligence" },
                  { key: "spend", label: "Annual spend", value: detail.annual_spend != null ? money(detail.annual_spend, detail.spend_currency) : null, tab: "diligence" },
                  ...outsourcingFacts(detail),
                  {
                    key: "contact", label: "Contact", tab: "general",
                    // Name, email and phone each stay whole (a phone number never breaks mid-number).
                    value: detail.contact_name?.trim() || detail.contact_email?.trim() || detail.contact_phone?.trim() ? (
                      <span className="rec-contact">
                        {[
                          detail.contact_name?.trim() ? <span key="n" style={{ whiteSpace: "nowrap" }}>{detail.contact_name.trim()}</span> : null,
                          detail.contact_email?.trim() ? <a key="e" href={`mailto:${detail.contact_email.trim()}`} style={{ whiteSpace: "nowrap" }}>{detail.contact_email.trim()}</a> : null,
                          detail.contact_phone?.trim() ? <a key="p" href={`tel:${detail.contact_phone.trim().replace(/[^\d+]/g, "")}`} style={{ whiteSpace: "nowrap" }}>{detail.contact_phone.trim()}</a> : null,
                        ].filter(Boolean).flatMap((el, i) => (i ? [<span key={`s${i}`} className="muted" aria-hidden="true"> · </span>, el] : [el]))}
                      </span>
                    ) : null,
                  },
                  {
                    key: "website", label: "Website", tab: "general",
                    // Stored URLs render as links only when they are web addresses (never javascript:).
                    value: detail.website?.trim()
                      ? (safeLinkUrl(detail.website)
                          ? <a href={safeLinkUrl(detail.website) ?? undefined} target="_blank" rel="noopener noreferrer">{detail.website.trim()}</a>
                          : detail.website.trim())
                      : null,
                  },
                ]}
                onFillIn={canWrite ? (tab) => openEdit(detail, tab) : undefined}
              />
              <div style={{ marginTop: 14 }}>
                <RelatedGroups
                  groups={[
                    { key: "processes", label: "Processes supported", items: detail.processes, href: "/processes" },
                    { key: "subcontractors", label: "Sub-contractors (fourth parties)", items: detail.subcontractors, href: "/vendors" },
                    { key: "main", label: "Main contractors", items: detail.subcontractor_of, href: "/vendors" },
                  ]}
                  noun="processes or sub-contractors"
                  onLink={canWrite ? () => openEdit(detail, "diligence") : undefined}
                />
              </div>
            </RecordSection>

            <RecordSection
              id="contracts"
              title="Contracts"
              count={detail.contracts.length}
              sub={vendorContractsSub(detail, ctx.fmt) ?? undefined}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "contracts")}>Add contract</button> : undefined}
              empty={detail.contracts.length === 0 ? "No service contract on file." : undefined}
            >
              <div className="rec-table-wrap">
                <table className="compact">
                  <thead><tr><th>Contract</th><th className="num">Value</th><th>Start</th><th>End</th><th>State</th></tr></thead>
                  <tbody>
                    {detail.contracts.map((c) => (
                      <tr key={c.id}>
                        <td className="cell-title">{c.name}</td>
                        <td className="muted num">{c.value != null ? money(c.value, c.currency) : "Not set"}</td>
                        <td className="muted">{c.start_date ? formatDate(c.start_date) : "Not set"}</td>
                        <td className="muted">{c.end_date ? formatDate(c.end_date) : "Open-ended"}</td>
                        <td>{c.is_expired ? <Badge tone="high" asIs>Expired</Badge> : <Badge tone="low" asIs>Active</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </RecordSection>

            <RecordSection
              id="certifications"
              title="Certifications"
              count={(detail.certifications ?? []).length}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "certifications")}>Add certification</button> : undefined}
              empty={(detail.certifications ?? []).length === 0 ? "No certification on file." : undefined}
            >
              <div className="rec-table-wrap">
                <table className="compact">
                  <thead><tr><th>Certification</th><th>Issuer</th><th>Number</th><th>Expiry</th></tr></thead>
                  <tbody>
                    {(detail.certifications ?? []).map((c) => (
                      <tr key={c.id}>
                        <td className="cell-title">{c.cert_type_label}{c.scope && <div className="muted" style={{ fontSize: 12 }}>{c.scope}</div>}</td>
                        <td className="muted">{c.issuer || "Not set"}</td>
                        <td className="muted">{c.certificate_number || "Not set"}</td>
                        <td><ExpiryBadge c={c} formatDate={formatDate} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </RecordSection>

            {(detail.outsourcing ?? []).length > 0 && (
              <RecordSection id="outsourcing" title="Outsourcing (SBP)" count={(detail.outsourcing ?? []).length} sub="Edited under Outsourcing">
                <div style={{ display: "grid", gap: 12 }}>
                  {(detail.outsourcing ?? []).map((o) => (
                    <div key={o.id} style={{ display: "grid", gap: 6 }}>
                      <div>
                        <Link href={`/outsourcing?id=${o.id}`} className="cell-title">{o.reference ? `${o.reference} — ` : ""}{o.title}</Link>{" "}
                        <span className="muted" style={{ fontSize: 12 }}>{sentenceCase(o.status)}{o.contract_end ? ` · contract to ${formatDate(o.contract_end)}` : ""}</span>
                      </div>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <Badge tone={o.materiality === "material" ? "high" : "neutral"} asIs>{sentenceCase(o.materiality)}</Badge>
                        {o.is_cloud && <Badge tone="info" asIs>Cloud</Badge>}
                        {o.data_offshored
                          ? <Badge tone="high" asIs>Data offshored{o.country ? ` · ${o.country}` : ""}</Badge>
                          : o.country ? <Badge tone="neutral" asIs>{o.country}</Badge> : null}
                        <Badge
                          tone={o.sbp_approval_status === "approved" ? "low" : o.sbp_approval_status === "pending" ? "medium" : o.sbp_approval_status === "rejected" ? "critical" : "neutral"}
                          asIs
                        >
                          SBP: {sentenceCase(o.sbp_approval_status).toLowerCase()}
                        </Badge>
                        <Badge tone={o.exit_plan_tested ? "low" : "medium"} asIs>Exit plan {o.exit_plan ? (o.exit_plan_tested ? "tested" : "untested") : "missing"}</Badge>
                        {o.substitutability
                          ? <Badge tone={o.substitutability === "difficult" || o.substitutability === "none" ? "high" : "neutral"} asIs>{VENDOR_SUBSTITUTABILITY[o.substitutability] ?? o.substitutability}</Badge>
                          : o.materiality === "material" ? <Badge tone="medium" asIs>Substitutability not assessed</Badge> : null}
                        {o.concentration_level && (
                          <Badge tone={o.concentration_level === "high" ? "high" : o.concentration_level === "medium" ? "medium" : "neutral"} asIs>
                            {sentenceCase(o.concentration_level)} concentration
                          </Badge>
                        )}
                      </div>
                      {o.exit_plan && <p className="muted" style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>{o.exit_plan}</p>}
                    </div>
                  ))}
                </div>
              </RecordSection>
            )}

            <RecordSection
              id="details"
              title="Details"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit details" onClick={() => openEdit(detail)}>Edit</button> : undefined}
            >
              <FactList
                items={[
                  { key: "category", label: "Category", value: categoryName(detail) || null, tab: "general" },
                  { key: "type", label: "Type", value: detail.type?.name || null, tab: "general" },
                  { key: "country", label: "Country", value: detail.country_ref?.label || null, tab: "general" },
                  { key: "location", label: "Location", value: detail.location?.trim() || null, tab: "general" },
                  { key: "onboarded", label: "Onboarded", value: detail.onboarded_at ? formatDate(detail.onboarded_at) : null, tab: "risk" },
                  ...(detail.offboarded_at || detail.status === "offboarded"
                    ? [{ key: "offboarded", label: "Offboarded", value: detail.offboarded_at ? formatDate(detail.offboarded_at) : null, tab: "risk" }]
                    : []),
                  { key: "created", label: "Created", value: detail.created_at ? formatDate(detail.created_at) : null },
                  ...cf.facts,
                ]}
                onFillIn={canWrite ? (tab) => (tab === "custom" ? cf.setEditing(true) : openEdit(detail, tab)) : undefined}
              />
              {cf.editor}
              {cf.editLink(canWrite)}
            </RecordSection>

            <RecordSection
              id="linked"
              title="Linked records"
              count={relatedCount(linkGroups)}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "links")}>Link records</button> : undefined}
            >
              {/* The head holds "Link records"; the empty line needs no second one (v1.1 D3). */}
              <RelatedGroups groups={linkGroups} />
            </RecordSection>

            <RecordIssuesSection
              ref={issuesRef}
              entityId={detail.id}
              entityKind="vendor"
              entityRef={detail.name}
              noun="third party"
              onRaised={refresh}
            />
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit third party — ${editing.name}` : "Add third party"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "diligence", label: "Due diligence", content: diligenceTab },
            { id: "risk", label: "Risk & Assessment", content: riskTab },
            { id: "contracts", label: "Contracts", content: contractsTab },
            { id: "certifications", label: "Certifications", content: certsTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          initialTab={editTab}
          onClose={() => {
            setShowForm(false);
            // Contracts and certificates are saved from the form as they are added; the
            // open record picks them up even when the form closes without Save.
            if (editing && openId === editing.id) loadDetail(editing.id);
          }}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create vendor"}
          footerLeft={
            editing ? (
              <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

export default function VendorsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <VendorsInner />
    </Suspense>
  );
}
