"use client";

import { Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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
import RelatedChips from "@/components/RelatedChips";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, Toggle, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import { InlineLookupCreate } from "@/components/LookupManager";
import LookupSelect from "@/components/LookupSelect";
import UserPicker from "@/components/UserPicker";
import WorkflowFields from "@/components/WorkflowFields";
import ArchivedRecords from "@/components/ArchivedRecords";
import { titleCase } from "@/lib/text";

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
  outsourcing?: OutsourcingFact[];
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

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <div style={{ marginTop: 2, fontSize: 13 }}>{children}</div>
    </div>
  );
}

function ExpiryBadge({ c, formatDate }: { c: Certification; formatDate: (d: string | null) => string }) {
  if (c.expiry_state === "expired") return <Badge tone="critical">Expired {formatDate(c.expires_on)}</Badge>;
  if (c.expiry_state === "expiring") return <Badge tone="medium">Expires in {c.days_to_expiry} day{c.days_to_expiry === 1 ? "" : "s"}</Badge>;
  if (c.expiry_state === "valid") return <Badge tone="low">Valid to {formatDate(c.expires_on)}</Badge>;
  return <Badge tone="neutral">No expiry recorded</Badge>;
}

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
  subcontractor_ids: AsyncOption[]; tier_override_reason: string;
};
const BLANK: FormState = {
  name: "", description: "", category_id: null, type_id: "", contact_name: "", contact_email: "", contact_phone: "", website: "",
  location: "", country_id: null, criticality: "medium", status: "active", shares_data: false, risk_rating: "",
  assessment_status: "not_started", last_assessed_at: "", onboarded_at: "", offboarded_at: "", review_frequency: "annual",
  next_review_date: "", risk_ids: [], asset_ids: [], requirement_ids: [], control_ids: [],
  legal_name: "", registration_number: "", relationship_owner_id: null, data_classification_id: null,
  annual_spend: "", spend_currency: "", residency: [], process_ids: [], subcontractor_ids: [], tier_override_reason: "",
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
  const loadDetail = useCallback((id: string) => { apiCall<Vendor>("GET", `/vendors/${id}`).then(setDetail).catch(() => setDetail(null)); }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);
  useEffect(() => { apiCall<VendorType[]>("GET", "/vendor-types").then(setTypes).catch(() => {}); }, []);

  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((c) => ({ value: c.id, label: c.name, sub: c.reference })));
  const searchCountries = (q: string) => lookupValues("country", { search: q }).then((rows) => rows.slice(0, 30).map((c) => ({ value: c.id, label: c.label })));
  const searchProcesses = (q: string) => pickProcesses({ search: q }).then((rows) => rows.slice(0, 30).map((p) => ({ value: p.id, label: p.name, sub: p.business_unit_name })));
  // A vendor can't be its own sub-contractor, so it is left out of the choices.
  const searchSubcontractors = (q: string) => apiCall<PagedList<{ id: string; name: string; legal_name?: string }>>("GET", `/vendors?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.filter((x) => x.id !== editing?.id).map((x) => ({ value: x.id, label: x.name, sub: x.legal_name && x.legal_name !== x.name ? x.legal_name : undefined })));

  function openNew() { setEditing(null); setF(BLANK); setContract(BLANK_CONTRACT); setCert(BLANK_CERT); setError(null); setShowForm(true); }
  function openEdit(v: Vendor) { setEditing(v); setF(fromVendor(v)); setContract(BLANK_CONTRACT); setCert(BLANK_CERT); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f, !!editing);
      if (editing) await apiCall<Vendor>("PATCH", `/vendors/${editing.id}`, payload);
      else await apiCall<Vendor>("POST", "/vendors", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Vendor created");
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
      setDetail(updated); reload(); toast(`Inherent tier: ${cap(updated.inherent_tier || "—")}`);
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
    { key: "actions", header: "", render: (v) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(v)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(v)}>Delete</button></div> },
  ];

  /* -------------------------------- form tabs -------------------------------- */
  const generalTab = (
    <>
      <Field label="Name" required help="The name the bank knows the third party by, e.g. 1LINK, Systems Ltd, Microsoft Azure."><TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="1LINK" required /></Field>
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
        <Field label="Contact Email"><TextInput value={f.contact_email} onChange={(v) => set("contact_email", v)} type="email" placeholder="accounts@vendor.com.pk" /></Field>
      </div>
      <div className="field-row">
        <Field label="Contact Phone"><TextInput value={f.contact_phone} onChange={(v) => set("contact_phone", v)} placeholder="+92 21 3456 7890" /></Field>
        <Field label="Website"><TextInput value={f.website} onChange={(v) => set("website", v)} placeholder="https://www.vendor.com.pk" /></Field>
      </div>
      <div className="field-row">
        <Field label="Country" help="Where the third party is based — drives offshoring and concentration reporting.">
          <LookupSelect lookupKey="country" value={f.country_id} onChange={(id) => set("country_id", id)} placeholder="Choose a country…" />
        </Field>
        <Field label="Location" help="City or address."><TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="Karachi, PK" /></Field>
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
        <Field label="Legal name" help="Registered name, if it differs from the trading name."><TextInput value={f.legal_name} onChange={(v) => set("legal_name", v)} placeholder="1LINK (Private) Limited" /></Field>
        <Field label="Registration number" help="SECP incorporation / company registration number."><TextInput value={f.registration_number} onChange={(v) => set("registration_number", v)} placeholder="0045678" /></Field>
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
        <Field label="Annual spend"><NumberInput value={f.annual_spend} onChange={(v) => set("annual_spend", v)} min={0} placeholder="12500000" /></Field>
        <Field label="Spend currency">
          <Select value={f.spend_currency} onChange={(v) => set("spend_currency", v)} options={currencyOptions} placeholder={`Organisation default (${currency})`} />
        </Field>
      </div>
    </>
  );
  const riskTab = (
    <>
      <div className="field-row">
        <Field label="Risk Rating" help="Overall residual risk this vendor poses."><Select value={f.risk_rating} onChange={(v) => set("risk_rating", v)} options={RISK_RATING} placeholder="Not rated" /></Field>
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
                    <td><button className="btn secondary sm" type="button" disabled={contractBusy} onClick={() => removeContract(c.id)}>Remove</button></td>
                  </tr>
                ))}
                {editing.contracts.length === 0 && <tr><td colSpan={6}><span className="muted">No contracts yet.</span></td></tr>}
              </tbody>
            </table>
          </div>
          <div className="card card-pad">
            <Field label="Add Contract" help="Record a contract, SLA or order with this vendor."><TextInput value={contract.name} onChange={(v) => setC("name", v)} placeholder="Master Services Agreement" /></Field>
            <Field label="Description"><TextArea value={contract.description} onChange={(v) => setC("description", v)} rows={2} /></Field>
            <div className="field-row">
              <Field label="Value"><NumberInput value={contract.value} onChange={(v) => setC("value", v)} min={0} placeholder="5000000" /></Field>
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
                {(editing.certifications ?? []).map((c) => (
                  <tr key={c.id}>
                    <td className="cell-title">{c.cert_type_label}{c.scope && <div className="muted" style={{ fontSize: 12 }}>{c.scope}</div>}</td>
                    <td className="muted">{c.issuer || "—"}</td>
                    <td className="muted">{c.certificate_number || "—"}</td>
                    <td className="muted">{formatDate(c.issued_on)}</td>
                    <td><ExpiryBadge c={c} formatDate={formatDate} /></td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="btn secondary sm" type="button" disabled={certBusy} onClick={() => editCert(c)}>Edit</button>{" "}
                      <button className="btn secondary sm" type="button" disabled={certBusy} onClick={() => removeCert(c)}>Remove</button>
                    </td>
                  </tr>
                ))}
                {(editing.certifications ?? []).length === 0 && <tr><td colSpan={6}><span className="muted">No certifications recorded.</span></td></tr>}
              </tbody>
            </table>
          </div>
          <div className="card card-pad">
            <strong style={{ fontSize: 13 }}>{cert.id ? "Edit certification" : "Add certification"}</strong>
            <div className="field-row" style={{ marginTop: 8 }}>
              <Field label="Type" required><Select value={cert.cert_type} onChange={(v) => setCt("cert_type", v)} options={CERT_TYPES} /></Field>
              <Field label="Issuer" help="Certification body or audit firm."><TextInput value={cert.issuer} onChange={(v) => setCt("issuer", v)} placeholder="BSI, A. F. Ferguson & Co." /></Field>
              <Field label="Certificate number"><TextInput value={cert.certificate_number} onChange={(v) => setCt("certificate_number", v)} placeholder="IS 123456" /></Field>
            </div>
            <Field label="Scope" help="What the certificate or report covers."><TextArea value={cert.scope} onChange={(v) => setCt("scope", v)} rows={2} placeholder="Switching and ATM network operations, Karachi and Lahore data centres." /></Field>
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
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Third-Party Risk</h1>
          <p>Vendor registry with due diligence, inherent risk tier, certifications, contracts and linked risks/assets.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
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
        aside={detail ? <RecordPanels model="vendor" entityId={detail.id} /> : null}
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail?.name || "…"}
        subtitle={detail ? `${detail.type?.name || categoryName(detail) || "Vendor"}${[detail.location, detail.country_ref?.label].filter(Boolean).length ? " · " + [detail.location, detail.country_ref?.label].filter(Boolean).join(", ") : ""}` : ""}
        actions={detail && (<><button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button><button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button></>)}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Inherent tier</div><div style={{ marginTop: 4 }}><Severity value={detail.inherent_tier || null} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Criticality</div><div style={{ marginTop: 4 }}><Severity value={detail.criticality} />{tiering?.overridden && <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>override</span>}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Status</div><div style={{ marginTop: 4 }}><Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Risk rating</div><div style={{ marginTop: 4 }}><Severity value={detail.risk_rating} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Assessment</div><div style={{ marginTop: 4 }}><Badge tone={ASSESS_TONE[detail.assessment_status] || "neutral"}>{cap(detail.assessment_status)}</Badge></div></div>
              {detail.contract_count > 0 && <div style={{ marginLeft: "auto", textAlign: "right" }}><div className="muted" style={{ fontSize: 12 }}>Contracts</div><div style={{ marginTop: 4 }}><strong>{detail.contract_count}</strong> · {totals(detail)}</div></div>}
            </div>
            {detail.shares_data && <div style={{ marginBottom: 14 }}><Badge tone="info">Handles our data</Badge></div>}

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12, padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <Fact label="Category">{categoryName(detail) || <span className="muted">—</span>}</Fact>
              <Fact label="Type">{detail.type?.name || <span className="muted">—</span>}</Fact>
              <Fact label="Country">{detail.country_ref?.label || <span className="muted">—</span>}</Fact>
              <Fact label="Location">{detail.location || <span className="muted">—</span>}</Fact>
              <Fact label="Contact">{[detail.contact_name, detail.contact_email, detail.contact_phone].filter(Boolean).join(" · ") || <span className="muted">—</span>}</Fact>
              <Fact label="Last assessed">{formatDate(detail.last_assessed_at)}</Fact>
              <Fact label="Next review">{formatDate(detail.next_review_date)}</Fact>
              <Fact label="Onboarded">{formatDate(detail.onboarded_at)}</Fact>
              {detail.offboarded_at && <Fact label="Offboarded">{formatDate(detail.offboarded_at)}</Fact>}
            </div>

            <div className="card" style={{ marginBottom: 16 }}>
              <div className="card-head"><h3>Due diligence</h3></div>
              <div className="card-pad" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: 12 }}>
                <Fact label="Legal name">{detail.legal_name || <span className="muted">—</span>}</Fact>
                <Fact label="Registration no.">{detail.registration_number || <span className="muted">—</span>}</Fact>
                <Fact label="Relationship owner">{personName(detail.relationship_owner_ref) || <span className="muted">—</span>}</Fact>
                <Fact label="Data classification">{detail.data_classification_ref?.label || <span className="muted">—</span>}</Fact>
                <Fact label="Data residency">{(detail.data_residency_countries ?? []).map((c) => c.label).join(", ") || <span className="muted">—</span>}</Fact>
                <Fact label="Annual spend">{detail.annual_spend != null ? money(detail.annual_spend, detail.spend_currency) : <span className="muted">—</span>}</Fact>
              </div>
              <div className="card-pad" style={{ display: "grid", gap: 12, paddingTop: 0 }}>
                <RelatedChips label="Processes supported" items={detail.processes} href="/processes" />
                <RelatedChips label="Sub-contractors (fourth parties)" items={detail.subcontractors} href="/vendors" />
                <RelatedChips label="Is a sub-contractor of" items={detail.subcontractor_of} href="/vendors" />
              </div>
            </div>

            <div className="card" style={{ marginBottom: 16 }}>
              <div className="card-head">
                <h3>Inherent risk tier</h3>
                <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
                  <button className="btn secondary sm" disabled={tierBusy} onClick={() => startTiering(detail)}>Start tiering questionnaire</button>
                  {tiering?.assessment && <button className="btn secondary sm" disabled={tierBusy} onClick={() => recomputeTier(detail)}>Recompute tier</button>}
                </div>
              </div>
              <div className="card-pad" style={{ fontSize: 13 }}>
                {!detail.inherent_tier && !tiering?.assessment && (
                  <p className="muted" style={{ margin: 0 }}>Not tiered yet. Start the eight-question “Inherent risk tiering” questionnaire, answer every question and submit it — the tier is written here and proposes the criticality.</p>
                )}
                {(detail.inherent_tier || tiering?.assessment) && (
                  <div style={{ display: "grid", gap: 8 }}>
                    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" }}>
                      <span>Tier <Severity value={detail.inherent_tier || null} /></span>
                      {tiering?.proposed_criticality && <span>Proposes criticality <Severity value={tiering.proposed_criticality} /></span>}
                      {tiering?.assessment && <span className="muted">From <Link href={`/assessments?id=${tiering.assessment.id}`}>{tiering.assessment.title || "assessment"}</Link>{tiering.submitted_at ? `, submitted ${formatDate(tiering.submitted_at)}` : ""}</span>}
                    </div>
                    {tiering?.explanation && <div className="muted">Score {tiering.explanation}. Bands: 70% and above critical, 45% high, 20% medium, below that low; one worst-case answer makes it at least medium, three at least high.</div>}
                    {tiering?.stale && (
                      <div style={{ color: "var(--amber, #b45309)" }}>
                        {tiering.problem || "The latest completed tiering assessment gives a different tier from the one stored."} {!tiering.problem && "Recompute to update it."}
                      </div>
                    )}
                    {tiering?.overridden && (
                      <div><Badge tone="medium">Criticality overridden</Badge> <span className="muted">Set to {detail.criticality} instead of the proposed {tiering.proposed_criticality}: {detail.tier_override_reason || "—"}</span></div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {(detail.certifications ?? []).length > 0 && (
              <>
                <strong style={{ fontSize: 13 }}>Certifications</strong>
                <div className="table-wrap" style={{ marginTop: 8, marginBottom: 16 }}>
                  <table>
                    <thead><tr><th>Certification</th><th>Issuer</th><th>Number</th><th>Expiry</th></tr></thead>
                    <tbody>
                      {(detail.certifications ?? []).map((c) => (
                        <tr key={c.id}>
                          <td className="cell-title">{c.cert_type_label}{c.scope && <div className="muted" style={{ fontSize: 12 }}>{c.scope}</div>}</td>
                          <td className="muted">{c.issuer || "—"}</td>
                          <td className="muted">{c.certificate_number || "—"}</td>
                          <td><ExpiryBadge c={c} formatDate={formatDate} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {(detail.outsourcing ?? []).length > 0 && (
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head"><h3>Outsourcing (SBP)</h3><span className="sub">Edited under Outsourcing</span></div>
                <div className="card-pad" style={{ display: "grid", gap: 12 }}>
                  {(detail.outsourcing ?? []).map((o) => (
                    <div key={o.id} style={{ display: "grid", gap: 6 }}>
                      <div><Link href={`/outsourcing?id=${o.id}`} className="cell-title">{o.reference ? `${o.reference} — ` : ""}{o.title}</Link> <span className="muted" style={{ fontSize: 12 }}>{cap(o.status)}{o.contract_end ? ` · contract to ${formatDate(o.contract_end)}` : ""}</span></div>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <Badge tone={o.materiality === "material" ? "high" : "neutral"}>{cap(o.materiality)}</Badge>
                        {o.is_cloud && <Badge tone="info">Cloud</Badge>}
                        {o.data_offshored ? <Badge tone="high">Data offshored{o.country ? ` · ${o.country}` : ""}</Badge> : o.country ? <Badge tone="neutral">{o.country}</Badge> : null}
                        <Badge tone={o.sbp_approval_status === "approved" ? "low" : o.sbp_approval_status === "pending" ? "medium" : o.sbp_approval_status === "rejected" ? "critical" : "neutral"}>SBP: {cap(o.sbp_approval_status)}</Badge>
                        <Badge tone={o.exit_plan_tested ? "low" : "medium"}>Exit plan {o.exit_plan ? (o.exit_plan_tested ? "tested" : "untested") : "missing"}</Badge>
                      </div>
                      {o.exit_plan && <p className="muted" style={{ margin: 0, fontSize: 12, whiteSpace: "pre-wrap" }}>{o.exit_plan}</p>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="card" style={{ marginBottom: 16 }}>
              <div className="card-head"><h3>Approval</h3></div>
              <div className="card-pad">
                <WorkflowFields entityType="vendor" entityId={detail.id} onChanged={() => { loadDetail(detail.id); reload(); }} />
              </div>
            </div>

            {detail.contracts.length > 0 && (
              <>
                <strong style={{ fontSize: 13 }}>Service contracts</strong>
                <div className="table-wrap" style={{ marginTop: 8, marginBottom: 16 }}>
                  <table>
                    <thead><tr><th>Contract</th><th>Value</th><th>Start</th><th>End</th><th>State</th></tr></thead>
                    <tbody>
                      {detail.contracts.map((c) => (
                        <tr key={c.id}>
                          <td className="cell-title">{c.name}</td>
                          <td className="muted">{c.value != null ? money(c.value, c.currency) : "—"}</td>
                          <td className="muted">{formatDate(c.start_date)}</td>
                          <td className="muted">{formatDate(c.end_date)}</td>
                          <td>{c.is_expired ? <Badge tone="high">Expired</Badge> : <Badge tone="low">Active</Badge>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            <strong style={{ fontSize: 13 }}>Related records</strong>
            <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 16 }}>
              <RelatedChips label="Risks" items={detail.risks} href="/risks" />
              <RelatedChips label="Assets" items={detail.assets} href="/information-assets" />
              <RelatedChips label="Compliance requirements" items={detail.requirements} href="/compliance" />
              <RelatedChips label="Mitigating controls" items={detail.controls} href="/controls" />
              <RelatedChips label="Incidents" items={detail.incidents} href="/incidents" />
              <RelatedChips label="Assessments" items={detail.assessments} href="/assessments" />
              <RelatedChips label="Outsourcing arrangements" items={detail.outsourcing_arrangements} href="/outsourcing" />
            </div>

          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit vendor — ${editing.name}` : "Add item (Vendors)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "diligence", label: "Due diligence", content: diligenceTab },
            { id: "risk", label: "Risk & Assessment", content: riskTab },
            { id: "contracts", label: "Contracts", content: contractsTab },
            { id: "certifications", label: "Certifications", content: certsTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
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
