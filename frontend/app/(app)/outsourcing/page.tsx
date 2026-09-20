"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { unconvertedNote, useFormat, type MoneyTotal } from "@/lib/format";
import { confirmDeleteWithImpact } from "@/lib/records";
import { useRecordParam } from "@/lib/useRecordParam";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import WorkflowFields from "@/components/WorkflowFields";
import ArchivedRecords from "@/components/ArchivedRecords";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import ImportExport from "@/components/ImportExport";
import UserPicker from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import type { LookupRef, UserRef } from "@/lib/masterData";
import { titleCase } from "@/lib/text";

// ------------------------------------------------------------------ local types
interface OutsourcingReview {
  id: string;
  arrangement_id: string;
  reference: string;
  review_date: string | null;
  reviewer: string;
  outcome: string;
  sla_met: boolean;
  issues_noted: string;
  status: string;
  created_at: string;
}
interface OutsourcingArrangement {
  id: string;
  reference: string;
  title: string;
  service_provider: string;
  service_description: string;
  vendor_id: string | null;
  category: string;
  materiality: string;
  materiality_assessment: string;
  is_cloud: boolean;
  cloud_model: string;
  data_offshored: boolean;
  /** Legacy text (the picked country's name once `country_id` is set). */
  country: string;
  country_id: string | null;
  country_ref: LookupRef | null;
  sbp_approval_required: boolean;
  sbp_approval_status: string;
  sbp_approval_ref: string;
  contract_start: string | null;
  contract_end: string | null;
  /** Decision 4: total contract value in `contract_currency` ("" = reporting currency). */
  contract_value: number | null;
  contract_currency: string;
  exit_plan: string;
  exit_plan_tested: boolean;
  concentration_note: string;
  /** easy | moderate | difficult | none; "" = not assessed. */
  substitutability: string;
  /** low | medium | high; "" = not assessed. */
  concentration_level: string;
  /** What a material arrangement still needs before it can be active. */
  missing_for_activation?: string[];
  status: string;
  /** Legacy text (the picked user's name once `owner_id` is set). */
  owner: string;
  owner_id: string | null;
  owner_ref: UserRef | null;
  /** Read-only: moved by the approval lifecycle (WorkflowFields). */
  workflow_status: string;
  review_count: number;
  is_contract_expiring: boolean;
  created_at: string;
  reviews: OutsourcingReview[];
}
interface OutsourcingSummary {
  total: number;
  by_materiality: Record<string, number>;
  material_count: number;
  cloud_count: number;
  material_cloud_count: number;
  sbp_approvals_pending: number;
  contracts_expiring_90d: number;
  exit_plans_untested: number;
  hard_to_substitute?: number;
  hard_to_substitute_untested?: number;
  substitutability_unassessed?: number;
  high_concentration?: number;
  live_missing_facts?: number;
  /** Contract value of arrangements that are not terminated, in the reporting currency. */
  contract_value?: MoneyTotal;
}
interface VendorOption {
  id: string;
  name: string;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ enum lists
const CATEGORY = opts([
  "it_infrastructure",
  "cloud",
  "application",
  "business_process",
  "call_center",
  "payment_processing",
  "data_processing",
  "other",
]);
const MATERIALITY = opts(["material", "non_material"]);
const CLOUD_MODEL = opts(["iaas", "paas", "saas", "not_applicable"]);
const SBP_STATUS = opts(["not_required", "pending", "approved", "rejected"]);
const STATUS = opts(["proposed", "active", "under_review", "terminated"]);
const REVIEW_STATUS = opts(["planned", "completed"]);
/** How hard the service is to move elsewhere (server: models/outsourcing.SUBSTITUTABILITY). */
const SUBSTITUTABILITY: Option[] = [
  { value: "easy", label: "Easy — alternatives readily available" },
  { value: "moderate", label: "Moderate — possible with planning" },
  { value: "difficult", label: "Difficult — few alternatives, long migration" },
  { value: "none", label: "None — no realistic alternative" },
];
const SUBSTITUTABILITY_SHORT: Record<string, string> = { easy: "Easy", moderate: "Moderate", difficult: "Difficult", none: "None" };
const CONCENTRATION: Option[] = [
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
];
const HARD_TO_SUBSTITUTE = new Set(["difficult", "none"]);
const LIVE_STATUSES = new Set(["active", "under_review"]);
/** The server's rule (api/v1/outsourcing.activation_error), for the form's early warning. */
function missingForActivation(f: Pick<ArrForm, "materiality" | "materiality_assessment" | "exit_plan" | "substitutability">): string[] {
  if (f.materiality !== "material") return [];
  const out: string[] = [];
  if (!f.materiality_assessment.trim()) out.push("materiality rationale");
  if (!f.exit_plan.trim()) out.push("exit plan");
  if (!f.substitutability) out.push("substitutability");
  return out;
}
const listText = (items: string[]) => (items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);

// ------------------------------------------------------------------ tones
const MATERIALITY_TONE: Record<string, Tone> = {
  material: "high",
  non_material: "neutral",
};
const SBP_TONE: Record<string, Tone> = {
  not_required: "neutral",
  pending: "medium",
  approved: "low",
  rejected: "critical",
};
const REVIEW_STATUS_TONE: Record<string, Tone> = {
  planned: "neutral",
  completed: "low",
};

const ownerName = (a: OutsourcingArrangement) => a.owner_ref?.full_name || a.owner_ref?.email || a.owner || "";
const countryName = (a: OutsourcingArrangement) => a.country_ref?.label || a.country || "";

function cloudLabel(model: string): string {
  if (model === "iaas") return "IaaS";
  if (model === "paas") return "PaaS";
  if (model === "saas") return "SaaS";
  return cap(model);
}

// ------------------------------------------------------------------ arrangement form state
type ArrForm = {
  title: string;
  service_provider: string;
  service_description: string;
  vendor_id: string;
  category: string;
  materiality: string;
  materiality_assessment: string;
  is_cloud: boolean;
  cloud_model: string;
  data_offshored: boolean;
  country_id: string | null;
  sbp_approval_required: boolean;
  sbp_approval_status: string;
  sbp_approval_ref: string;
  contract_start: string;
  contract_end: string;
  contract_value: string;
  contract_currency: string;
  exit_plan: string;
  exit_plan_tested: boolean;
  concentration_note: string;
  substitutability: string;
  concentration_level: string;
  status: string;
  owner_id: string | null;
};
const BLANK_ARR: ArrForm = {
  title: "",
  service_provider: "",
  service_description: "",
  vendor_id: "",
  category: "it_infrastructure",
  materiality: "material",
  materiality_assessment: "",
  is_cloud: false,
  cloud_model: "not_applicable",
  data_offshored: false,
  country_id: null,
  sbp_approval_required: false,
  sbp_approval_status: "not_required",
  sbp_approval_ref: "",
  contract_start: "",
  contract_end: "",
  contract_value: "",
  contract_currency: "",
  exit_plan: "",
  exit_plan_tested: false,
  concentration_note: "",
  substitutability: "",
  concentration_level: "",
  status: "proposed",
  owner_id: null,
};
function fromArr(a: OutsourcingArrangement): ArrForm {
  return {
    title: a.title,
    service_provider: a.service_provider || "",
    service_description: a.service_description || "",
    vendor_id: a.vendor_id || "",
    category: a.category || "it_infrastructure",
    materiality: a.materiality || "material",
    materiality_assessment: a.materiality_assessment || "",
    is_cloud: !!a.is_cloud,
    cloud_model: a.cloud_model || "not_applicable",
    data_offshored: !!a.data_offshored,
    country_id: a.country_id ?? null,
    sbp_approval_required: !!a.sbp_approval_required,
    sbp_approval_status: a.sbp_approval_status || "not_required",
    sbp_approval_ref: a.sbp_approval_ref || "",
    contract_start: a.contract_start || "",
    contract_end: a.contract_end || "",
    contract_value: a.contract_value != null ? String(a.contract_value) : "",
    contract_currency: a.contract_currency || "",
    exit_plan: a.exit_plan || "",
    exit_plan_tested: !!a.exit_plan_tested,
    concentration_note: a.concentration_note || "",
    substitutability: a.substitutability || "",
    concentration_level: a.concentration_level || "",
    status: a.status || "proposed",
    owner_id: a.owner_id ?? null,
  };
}
function arrPayload(f: ArrForm): Record<string, unknown> {
  return {
    title: f.title,
    service_provider: f.service_provider,
    service_description: f.service_description,
    vendor_id: f.vendor_id === "" ? null : f.vendor_id,
    category: f.category,
    materiality: f.materiality,
    materiality_assessment: f.materiality_assessment,
    is_cloud: f.is_cloud,
    cloud_model: f.cloud_model,
    data_offshored: f.data_offshored,
    country_id: f.country_id,
    sbp_approval_required: f.sbp_approval_required,
    sbp_approval_status: f.sbp_approval_status,
    sbp_approval_ref: f.sbp_approval_ref,
    contract_start: f.contract_start || null,
    contract_end: f.contract_end || null,
    contract_value: f.contract_value === "" ? null : Number(f.contract_value),
    contract_currency: f.contract_currency,
    exit_plan: f.exit_plan,
    exit_plan_tested: f.exit_plan_tested,
    concentration_note: f.concentration_note,
    substitutability: f.substitutability,
    concentration_level: f.concentration_level,
    status: f.status,
    // Picked, not typed: the server writes the person's / country's name into the
    // legacy `owner` / `country` text, which older rows keep until someone picks.
    owner_id: f.owner_id,
  };
}

// ------------------------------------------------------------------ review draft
type ReviewDraft = {
  review_date: string;
  reviewer: string;
  outcome: string;
  sla_met: boolean;
  issues_noted: string;
  status: string;
};
const BLANK_REVIEW: ReviewDraft = {
  review_date: "",
  reviewer: "",
  outcome: "",
  sla_met: true,
  issues_noted: "",
  status: "planned",
};

function OutsourcingInner() {
  const { formatDate, formatMoney, currency, currencyOptions } = useFormat();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<OutsourcingArrangement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [summary, setSummary] = useState<OutsourcingSummary | null>(null);
  const [vendors, setVendors] = useState<VendorOption[]>([]);

  // ---- filters ----
  const [fCategory, setFCategory] = useState("");
  const [fMateriality, setFMateriality] = useState("");
  const [fStatus, setFStatus] = useState("");

  // ---- arrangement dialog ----
  const [editingArr, setEditingArr] = useState<OutsourcingArrangement | null>(null);
  const [showArrForm, setShowArrForm] = useState(false);
  const [savingArr, setSavingArr] = useState(false);
  const [af, setAf] = useState<ArrForm>(BLANK_ARR);
  const setA = <K extends keyof ArrForm>(k: K, v: ArrForm[K]) => setAf((p) => ({ ...p, [k]: v }));

  // ---- inline review add-form (in drawer) ----
  const [rd, setRd] = useState<ReviewDraft>(BLANK_REVIEW);
  const setRD = <K extends keyof ReviewDraft>(k: K, v: ReviewDraft[K]) => setRd((p) => ({ ...p, [k]: v }));

  const vendorName = (id: string | null) =>
    id ? vendors.find((v) => v.id === id)?.name || "Linked vendor" : "";

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchArrangements = useCallback(
    (qs: string) => apiCall<PagedList<OutsourcingArrangement>>("GET", `/outsourcing?${qs}`),
    [],
  );

  const loadDetail = useCallback((id: string) => {
    apiCall<OutsourcingArrangement>("GET", `/outsourcing/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) {
      setRd(BLANK_REVIEW);
      loadDetail(openId);
    } else setDetail(null);
  }, [openId, loadDetail]);

  const loadSummary = useCallback(() => {
    apiCall<OutsourcingSummary>("GET", "/outsourcing-summary")
      .then(setSummary)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load outsourcing summary"));
  }, []);
  useEffect(() => {
    loadSummary();
    apiCall<PagedList<VendorOption>>("GET", "/vendors?limit=200")
      .then((r) => setVendors(r.items))
      .catch(() => setVendors([]))
      .finally(() => setVendorsLoaded(true));
  }, [loadSummary, refreshKey]);

  // ------------------------------------------------------------- arrangement CRUD
  function openNewArr(prefill?: Partial<ArrForm>) {
    setEditingArr(null);
    setAf({ ...BLANK_ARR, ...prefill });
    setError(null);
    setShowArrForm(true);
  }
  // `/outsourcing?new=1&vendor_id=…` (the third-party record's "record an arrangement"
  // open point) opens the form linked to that vendor; the params are then dropped.
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const newParam = searchParams.get("new");
  const vendorParam = searchParams.get("vendor_id");
  const [vendorsLoaded, setVendorsLoaded] = useState(false);
  useEffect(() => {
    if (newParam !== "1") return;
    if (vendorParam && !vendorsLoaded) return; // wait for the vendor list to name the provider
    const vendorId = vendorParam || "";
    const name = vendors.find((v) => v.id === vendorId)?.name ?? "";
    openNewArr({ vendor_id: vendorId, service_provider: name, title: name });
    const next = new URLSearchParams(searchParams.toString());
    next.delete("new");
    next.delete("vendor_id");
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [newParam, vendorParam, vendorsLoaded]);
  function openEditArr(a: OutsourcingArrangement) {
    setEditingArr(a);
    setAf(fromArr(a));
    setError(null);
    setShowArrForm(true);
  }
  async function saveArr() {
    setError(null);
    setSavingArr(true);
    try {
      const payload = arrPayload(af);
      if (editingArr) await apiCall<OutsourcingArrangement>("PATCH", `/outsourcing/${editingArr.id}`, payload);
      else await apiCall<OutsourcingArrangement>("POST", "/outsourcing", payload);
      setShowArrForm(false);
      reload();
      if (openId) loadDetail(openId);
      toast(editingArr ? "Changes saved" : "Arrangement created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save arrangement");
    } finally {
      setSavingArr(false);
    }
  }
  async function removeArr(a: OutsourcingArrangement) {
    if (!(await confirmDeleteWithImpact("outsourcing_arrangement", a.id, `${a.reference || ""} ${a.title}`.trim()))) return;
    try {
      await apiCall<void>("DELETE", `/outsourcing/${a.id}`);
      setShowArrForm(false);
      if (openId === a.id) setOpenId(null);
      reload();
      toast(`Deleted ${a.reference || "arrangement"}`);
    } catch (e) {
      // A 403 is segregation of duties: the server's message says who may delete it.
      toast(e instanceof Error && e.message ? e.message : "Failed to delete", "error");
    }
  }

  // ------------------------------------------------------------- reviews (inline)
  async function addReview() {
    if (!detail) return;
    setError(null);
    try {
      await apiCall<OutsourcingArrangement>("POST", `/outsourcing/${detail.id}/reviews`, {
        review_date: rd.review_date || null,
        reviewer: rd.reviewer,
        outcome: rd.outcome,
        sla_met: rd.sla_met,
        issues_noted: rd.issues_noted,
        status: rd.status,
      });
      setRd(BLANK_REVIEW);
      loadDetail(detail.id);
      reload();
      toast("Review added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add review");
    }
  }
  async function removeReview(rid: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Remove this review?", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/outsourcing-reviews/${rid}`);
      loadDetail(detail.id);
      reload();
      toast("Review removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove review");
    }
  }

  const vendorOpts: Option[] = useMemo(() => vendors.map((v) => ({ value: v.id, label: v.name })), [vendors]);

  // ------------------------------------------------------------- form tabs
  const formMissing = missingForActivation(af);
  const activationWarning = LIVE_STATUSES.has(af.status) && formMissing.length > 0 ? (
    <div className="error" role="alert" style={{ marginBottom: 12 }}>
      A material arrangement can&apos;t be {cap(af.status).toLowerCase()} until its {listText(formMissing)}{" "}
      {formMissing.length === 1 ? "is" : "are"} recorded. Fill {formMissing.length === 1 ? "it" : "them"} in on the Materiality and Exit Plan tabs, or keep it proposed.
    </div>
  ) : null;
  const arrangementTab = (
    <>
      {activationWarning}
      <Field label="Title" required help="For example: Core banking hosting — data centre.">
        <TextInput value={af.title} onChange={(v) => setA("title", v)} placeholder="Arrangement title" required />
      </Field>
      <div className="field-row">
        <Field label="Service provider" help="The outsourcing service provider / supplier.">
          <TextInput value={af.service_provider} onChange={(v) => setA("service_provider", v)} placeholder="Provider name" />
        </Field>
        <Field label="Linked vendor" help="Optional link to the vendor register.">
          <Select value={af.vendor_id} onChange={(v) => setA("vendor_id", v)} options={vendorOpts} placeholder="No linked vendor" />
        </Field>
      </div>
      <Field label="Service description" help="What service is being outsourced.">
        <TextArea value={af.service_description} onChange={(v) => setA("service_description", v)} rows={3} placeholder="Scope of the outsourced service." />
      </Field>
      <div className="field-row">
        <Field label="Category">
          <Select value={af.category} onChange={(v) => setA("category", v)} options={CATEGORY} />
        </Field>
        <Field label="Status" help="A material arrangement can't be active or under review until its materiality rationale, exit plan and substitutability are recorded.">
          <Select value={af.status} onChange={(v) => setA("status", v)} options={STATUS} />
        </Field>
      </div>
      <Field label="Owner" help="Accountable business / risk owner.">
        <UserPicker
          value={af.owner_id}
          onChange={(id) => setA("owner_id", id)}
          selected={editingArr?.owner_ref ?? null}
          legacyText={editingArr && !editingArr.owner_id ? editingArr.owner : null}
        />
      </Field>
    </>
  );
  const materialityTab = (
    <>
      <Field label="Materiality" help="SBP materiality determination — material arrangements carry heavier obligations.">
        <Select value={af.materiality} onChange={(v) => setA("materiality", v)} options={MATERIALITY} />
      </Field>
      <Field
        label="Materiality rationale"
        required={af.materiality === "material"}
        help="Why the arrangement is (or is not) material: what would happen to customers, operations and compliance if the service failed. SBP expects the reasoning on file, not just the label; a material arrangement needs it before it goes active."
      >
        <TextArea value={af.materiality_assessment} onChange={(v) => setA("materiality_assessment", v)} rows={3} placeholder="Why the arrangement is (non-)material: criticality, data sensitivity, customer impact…" />
      </Field>
      <Field
        label="Substitutability"
        required={af.materiality === "material"}
        help="How hard it would be to move this service to another provider or back in-house. SBP cares because a service the bank cannot replace quickly needs a tested exit plan and closer monitoring. Difficult or none without a tested exit plan is flagged as the most urgent gap."
      >
        <Select value={af.substitutability} onChange={(v) => setA("substitutability", v)} options={SUBSTITUTABILITY} placeholder="Not assessed" />
      </Field>
      <div className="field-row">
        <Field label="Cloud" help="Whether the service is delivered on cloud infrastructure.">
          <Toggle checked={af.is_cloud} onChange={(v) => setA("is_cloud", v)} label="Cloud-based arrangement" />
        </Field>
        <Field label="Cloud model" help="IaaS / PaaS / SaaS where cloud-based.">
          <Select value={af.cloud_model} onChange={(v) => setA("cloud_model", v)} options={CLOUD_MODEL} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Data offshored" help="Whether data leaves Pakistan under this arrangement.">
          <Toggle checked={af.data_offshored} onChange={(v) => setA("data_offshored", v)} label="Data offshored" />
        </Field>
        <Field label="Country" help="Country where data / processing is hosted.">
          <LookupSelect
            lookupKey="country"
            value={af.country_id}
            onChange={(id) => setA("country_id", id)}
            placeholder="Choose a country…"
            legacyText={editingArr && !editingArr.country_id ? editingArr.country : null}
          />
        </Field>
      </div>
    </>
  );
  const sbpTab = (
    <>
      <Field label="SBP approval required" help="Whether SBP prior approval / NOC is required.">
        <Toggle checked={af.sbp_approval_required} onChange={(v) => setA("sbp_approval_required", v)} label="SBP approval / NOC required" />
      </Field>
      <div className="field-row">
        <Field label="SBP approval status">
          <Select value={af.sbp_approval_status} onChange={(v) => setA("sbp_approval_status", v)} options={SBP_STATUS} />
        </Field>
        <Field label="SBP approval reference" help="NOC / approval letter reference.">
          <TextInput value={af.sbp_approval_ref} onChange={(v) => setA("sbp_approval_ref", v)} placeholder="NOC reference" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Contract start">
          <TextInput type="date" value={af.contract_start} onChange={(v) => setA("contract_start", v)} />
        </Field>
        <Field label="Contract end" help="Drives the expiring-within-90-days flag.">
          <TextInput type="date" value={af.contract_end} onChange={(v) => setA("contract_end", v)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Contract value" help="Total value of the arrangement over its term.">
          <TextInput type="number" value={af.contract_value} onChange={(v) => setA("contract_value", v)} placeholder="0" />
        </Field>
        <Field label="Currency" help={`The currency the value is in. Blank means ${currency}, and totals convert at the exchange rates in Settings → Organisation.`}>
          <Select
            value={af.contract_currency}
            onChange={(v) => setA("contract_currency", v)}
            options={currencyOptions}
            placeholder={`Organisation default (${currency})`}
          />
        </Field>
      </div>
    </>
  );
  const exitTab = (
    <>
      <Field label="Exit plan" required={af.materiality === "material"} help="Documented exit / termination strategy (SBP expectation for material arrangements). A material arrangement needs one before it goes active.">
        <TextArea value={af.exit_plan} onChange={(v) => setA("exit_plan", v)} rows={4} placeholder="How the bank would exit or bring the service back in-house, alternate providers, data return / destruction…" />
      </Field>
      <Field label="Exit plan tested" help="Whether the exit plan has been tested / rehearsed.">
        <Toggle checked={af.exit_plan_tested} onChange={(v) => setA("exit_plan_tested", v)} label="Exit plan tested" />
      </Field>
      {af.materiality === "material" && HARD_TO_SUBSTITUTE.has(af.substitutability) && !af.exit_plan_tested && (
        <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
          Substitutability is {SUBSTITUTABILITY_SHORT[af.substitutability].toLowerCase()}: test this exit plan, or the arrangement stays flagged.
        </p>
      )}
      <Field
        label="Concentration level"
        help="How much of the bank relies on this provider across its services. SBP asks banks to watch reliance on a single provider (and on a few large cloud providers): high concentration means one failure hits many services at once. The third-party record also derives concentration from the material arrangements and critical processes that depend on the provider."
      >
        <Select value={af.concentration_level} onChange={(v) => setA("concentration_level", v)} options={CONCENTRATION} placeholder="Not assessed" />
      </Field>
      <Field label="Concentration note" help="Concentration-risk considerations (provider / geography / technology).">
        <TextArea value={af.concentration_note} onChange={(v) => setA("concentration_note", v)} rows={3} placeholder="Reliance on a single provider, sub-outsourcing chains, sector-wide concentration…" />
      </Field>
    </>
  );

  // ------------------------------------------------------------- table columns
  const columns: Column<OutsourcingArrangement>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (a) => <span className="ref">{a.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (a) => <span className="cell-title">{a.title}</span> },
    { key: "service_provider", header: "Service provider", sortable: true, render: (a) => <span className="muted">{a.service_provider || vendorName(a.vendor_id) || "—"}</span> },
    { key: "category", header: "Category", sortable: true, render: (a) => <Badge tone="info">{cap(a.category)}</Badge> },
    { key: "materiality", header: "Materiality", sortable: true, render: (a) => <Badge tone={MATERIALITY_TONE[a.materiality] || "neutral"}>{cap(a.materiality)}</Badge> },
    {
      key: "cloud",
      header: "Cloud",
      render: (a) =>
        a.is_cloud ? (
          <Badge tone="info">{a.cloud_model && a.cloud_model !== "not_applicable" ? cloudLabel(a.cloud_model) : "Cloud"}</Badge>
        ) : (
          <span className="muted">—</span>
        ),
    },
    { key: "sbp_approval", header: "SBP approval", render: (a) => <Badge tone={SBP_TONE[a.sbp_approval_status] || "neutral"}>{cap(a.sbp_approval_status)}</Badge> },
    {
      key: "contract_end",
      header: "Contract end",
      sortable: true,
      render: (a) =>
        a.is_contract_expiring ? (
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <Badge tone="high">Expiring</Badge>
            <span className="muted">{formatDate(a.contract_end)}</span>
          </div>
        ) : (
          <span className="muted">{formatDate(a.contract_end)}</span>
        ),
      text: (a) => (a.contract_end ? formatDate(a.contract_end) : ""),
    },
    {
      key: "actions",
      header: "",
      render: (a) => (
        <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => openEditArr(a)}>Edit</button>
          <button className="btn secondary sm" onClick={() => removeArr(a)}>Delete</button>
        </div>
      ),
    },
  ];

  const filters = useMemo(
    () => ({ category: fCategory || undefined, materiality: fMateriality || undefined, status: fStatus || undefined }),
    [fCategory, fMateriality, fStatus],
  );

  const toolbarRight = (
    <>
      <select className="select" style={{ width: 170 }} value={fCategory} onChange={(e) => setFCategory(e.target.value)}>
        <option value="">All categories</option>
        {CATEGORY.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
      </select>
      <select className="select" style={{ width: 140 }} value={fMateriality} onChange={(e) => setFMateriality(e.target.value)}>
        <option value="">All materiality</option>
        {MATERIALITY.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
      </select>
      <select className="select" style={{ width: 150 }} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
        <option value="">All statuses</option>
        {STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
      </select>
      <ArchivedRecords entityType="outsourcing_arrangement" noun="arrangements" refreshKey={refreshKey} onRestored={() => { reload(); loadSummary(); }} />
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Outsourcing &amp; Cloud Risk</h1>
          <p>The SBP outsourcing / cloud regulatory register — materiality, cloud model and data offshoring, SBP approval (NOC) tracking, contract windows, tested exit plans and concentration risk.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="outsourcing-arrangements" label="Arrangements" onDone={() => setRefreshKey((k) => k + 1)} />
          <button className="btn" onClick={() => openNewArr()}>
            <IconPlus width={16} height={16} /> New arrangement
          </button>
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.material_count.toLocaleString() : "—"}</span></div>
          <span className="l">Material arrangements</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.cloud_count.toLocaleString() : "—"}</span></div>
          <span className="l">Cloud arrangements</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.sbp_approvals_pending.toLocaleString() : "—"}</span></div>
          <span className="l">SBP approvals pending</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.contracts_expiring_90d.toLocaleString() : "—"}</span></div>
          <span className="l">Contracts expiring ≤90d</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">
              {summary?.contract_value
                ? formatMoney(summary.contract_value.total, summary.contract_value.reporting_currency || currency, { compact: "auto" })
                : "—"}
            </span>
          </div>
          <span className="l">Contract value</span>
        </div>
      </div>

      {unconvertedNote(summary?.contract_value) && (
        <div className="card card-pad" style={{ marginBottom: 16, fontSize: 13.5, background: "var(--primary-weak-2)" }}>
          {unconvertedNote(summary?.contract_value)} — <Link href="/organisation-settings#exchange-rates">add a rate</Link>.
        </div>
      )}

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
      {summary && (summary.exit_plans_untested > 0 || !!summary.hard_to_substitute_untested || !!summary.live_missing_facts
        || !!summary.high_concentration || !!summary.substitutability_unassessed) && (
        <div className="card card-pad" style={{ marginBottom: 16, display: "grid", gap: 4, fontSize: 13 }}>
          {!!summary.hard_to_substitute_untested && (
            <span style={{ color: "var(--red)" }}>
              <b>{summary.hard_to_substitute_untested}</b> material arrangement{summary.hard_to_substitute_untested === 1 ? "" : "s"} that can&apos;t easily be replaced {summary.hard_to_substitute_untested === 1 ? "has" : "have"} no tested exit plan.
            </span>
          )}
          {!!summary.live_missing_facts && (
            <span style={{ color: "var(--orange)" }}>
              <b>{summary.live_missing_facts}</b> live material arrangement{summary.live_missing_facts === 1 ? " is" : "s are"} missing the materiality rationale, exit plan or substitutability.
            </span>
          )}
          {summary.exit_plans_untested > 0 && (
            <span className="muted">{summary.exit_plans_untested} material exit plan{summary.exit_plans_untested === 1 ? "" : "s"} untested.</span>
          )}
          {!!summary.substitutability_unassessed && (
            <span className="muted">{summary.substitutability_unassessed} material arrangement{summary.substitutability_unassessed === 1 ? " has" : "s have"} no substitutability assessed.</span>
          )}
          {!!summary.high_concentration && (
            <span className="muted">{summary.high_concentration} arrangement{summary.high_concentration === 1 ? " records" : "s record"} high concentration on its provider.</span>
          )}
        </div>
      )}

      <DataTable<OutsourcingArrangement>
        columns={columns}
        fetcher={fetchArrangements}
        rowKey={(a) => a.id}
        onRowClick={(a) => setOpenId(a.id)}
        activeKey={openId}
        filters={filters}
        toolbarRight={toolbarRight}
        searchPlaceholder="Search title, reference, provider, owner…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No outsourcing arrangements. Register the bank's outsourcing and cloud arrangements to track SBP materiality, approvals, exit plans and concentration risk."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        aside={detail ? <RecordPanels model="outsourcing_arrangement" entityId={detail.id} /> : null}
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? `${cap(detail.category)} · ${cap(detail.materiality)} · ${cap(detail.status)}${detail.service_provider ? " · " + detail.service_provider : ""}` : ""}
        width={760}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditArr(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeArr(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
              <Badge tone={MATERIALITY_TONE[detail.materiality] || "neutral"}>{cap(detail.materiality)}</Badge>
              <Badge tone={SBP_TONE[detail.sbp_approval_status] || "neutral"}>SBP: {cap(detail.sbp_approval_status)}</Badge>
              {detail.sbp_approval_required && <Badge tone="medium">Approval required</Badge>}
              {detail.is_cloud && <Badge tone="info">Cloud · {cloudLabel(detail.cloud_model)}</Badge>}
              {detail.data_offshored && <Badge tone="high">Data offshored{countryName(detail) ? " · " + countryName(detail) : ""}</Badge>}
              {!detail.data_offshored && countryName(detail) && <Badge tone="neutral">{countryName(detail)}</Badge>}
              <Badge tone={detail.exit_plan_tested ? "low" : "medium"}>Exit plan {detail.exit_plan_tested ? "tested" : "untested"}</Badge>
              {detail.substitutability
                ? <Badge tone={HARD_TO_SUBSTITUTE.has(detail.substitutability) ? "high" : "neutral"}>Substitutability: {SUBSTITUTABILITY_SHORT[detail.substitutability]?.toLowerCase() ?? detail.substitutability}</Badge>
                : detail.materiality === "material" ? <Badge tone="medium">Substitutability not assessed</Badge> : null}
              {detail.concentration_level && (
                <Badge tone={detail.concentration_level === "high" ? "high" : detail.concentration_level === "medium" ? "medium" : "neutral"}>
                  Concentration: {detail.concentration_level}
                </Badge>
              )}
              {detail.is_contract_expiring && <Badge tone="high">Contract expiring ≤90d</Badge>}
            </div>

            {detail.materiality === "material" && HARD_TO_SUBSTITUTE.has(detail.substitutability) && (!detail.exit_plan.trim() || !detail.exit_plan_tested) && (
              <div className="error" role="status" style={{ marginBottom: 12 }}>
                Material and {detail.substitutability === "none" ? "with no realistic alternative provider" : "difficult to substitute"}, but the exit plan is {detail.exit_plan.trim() ? "untested" : "missing"}. Test the exit plan so the bank can leave this provider if it fails.
              </div>
            )}
            {(detail.missing_for_activation ?? []).length > 0 && (
              <div className="card card-pad" style={{ marginBottom: 12, fontSize: 13, borderColor: "var(--amber)" }}>
                {LIVE_STATUSES.has(detail.status)
                  ? <>Recorded as {cap(detail.status).toLowerCase()} without its {listText(detail.missing_for_activation ?? [])}. SBP expects these on file for every material arrangement.</>
                  : <>Before this material arrangement can be active, record its {listText(detail.missing_for_activation ?? [])}.</>}{" "}
                <button type="button" className="linklike" onClick={() => openEditArr(detail)}>Fill in</button>
              </div>
            )}

            <div className="field-row" style={{ marginBottom: 12 }}>
              <div style={{ flex: 1 }}>
                <div className="label">Materiality assessment</div>
                <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                  {detail.materiality_assessment || "—"}
                </p>
              </div>
              <div style={{ flex: 1 }}>
                <div className="label">Exit plan</div>
                <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                  {detail.exit_plan || "—"}
                </p>
              </div>
            </div>
            <div style={{ marginBottom: 16 }}>
              <div className="label">Substitutability and concentration</div>
              <p className="muted" style={{ margin: "4px 0", fontSize: 13 }}>
                {detail.substitutability
                  ? SUBSTITUTABILITY.find((o) => o.value === detail.substitutability)?.label ?? detail.substitutability
                  : "Substitutability not assessed"}
                {" · "}
                {detail.concentration_level ? `${cap(detail.concentration_level)} concentration` : "Concentration not assessed"}
              </p>
              <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                {detail.concentration_note || "No concentration note."}
              </p>
              <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                {detail.sbp_approval_ref ? `NOC ref ${detail.sbp_approval_ref} · ` : ""}
                Contract {formatDate(detail.contract_start)} → {formatDate(detail.contract_end)}
                {detail.contract_value != null
                  ? ` · value ${formatMoney(detail.contract_value, detail.contract_currency || currency)}`
                  : ""}
                {detail.vendor_id ? ` · linked vendor ${vendorName(detail.vendor_id)}` : ""}
                {ownerName(detail) ? ` · owner ${ownerName(detail)}` : ""}
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Approval</h3></div>
              <div className="card-pad">
                <WorkflowFields entityType="outsourcing_arrangement" entityId={detail.id} onChanged={() => { loadDetail(detail.id); reload(); }} />
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Monitoring reviews</h3><span className="sub">{detail.review_count} recorded</span></div>
              <div className="card-pad">
                <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
                  Periodic reviews of the arrangement — SLA performance, outcome and any issues noted.
                </p>
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(ev) => { ev.preventDefault(); addReview(); }}
                >
                  <div style={{ width: 150 }}>
                    <label className="label">Review date</label>
                    <input className="input" type="date" value={rd.review_date} onChange={(ev) => setRD("review_date", ev.target.value)} />
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label">Reviewer</label>
                    <input className="input" value={rd.reviewer} onChange={(ev) => setRD("reviewer", ev.target.value)} placeholder="Reviewer" />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Status</label>
                    <select className="select" value={rd.status} onChange={(ev) => setRD("status", ev.target.value)}>
                      {REVIEW_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                  </div>
                  <label className="label" style={{ display: "flex", gap: 6, alignItems: "center", paddingBottom: 8 }}>
                    <input type="checkbox" checked={rd.sla_met} onChange={(ev) => setRD("sla_met", ev.target.checked)} /> SLA met
                  </label>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Outcome</label>
                    <input className="input" value={rd.outcome} onChange={(ev) => setRD("outcome", ev.target.value)} placeholder="Review outcome" />
                  </div>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Issues noted</label>
                    <input className="input" value={rd.issues_noted} onChange={(ev) => setRD("issues_noted", ev.target.value)} placeholder="Issues / follow-ups" />
                  </div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ref</th>
                        <th>Date</th>
                        <th>Reviewer</th>
                        <th>Status</th>
                        <th>SLA</th>
                        <th>Outcome</th>
                        <th>Issues</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...detail.reviews]
                        .sort((a, b) => (b.review_date || "").localeCompare(a.review_date || ""))
                        .map((rv) => (
                          <tr key={rv.id}>
                            <td className="ref">{rv.reference || "—"}</td>
                            <td className="muted">{formatDate(rv.review_date)}</td>
                            <td className="muted">{rv.reviewer || "—"}</td>
                            <td><Badge tone={REVIEW_STATUS_TONE[rv.status] || "neutral"}>{cap(rv.status)}</Badge></td>
                            <td>{rv.sla_met ? <Badge tone="low">Met</Badge> : <Badge tone="critical">Breached</Badge>}</td>
                            <td className="muted">{rv.outcome || "—"}</td>
                            <td className="muted">{rv.issues_noted || "—"}</td>
                            <td>
                              <button className="btn secondary sm" onClick={() => removeReview(rv.id)}>Remove</button>
                            </td>
                          </tr>
                        ))}
                      {detail.reviews.length === 0 && (
                        <tr><td colSpan={8}><span className="muted">No reviews recorded yet.</span></td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

          </>
        )}
      </RecordDrawer>

      {/* ============================================= MODAL */}
      {showArrForm && (
        <FormModal
          title={editingArr ? `Edit arrangement — ${editingArr.reference || editingArr.title}` : "New outsourcing arrangement"}
          wide
          tabs={[
            { id: "arrangement", label: "Arrangement", content: arrangementTab, required: true },
            { id: "materiality", label: "Materiality & Cloud", content: materialityTab },
            { id: "sbp", label: "SBP & Contract", content: sbpTab },
            { id: "exit", label: "Exit Plan", content: exitTab },
          ]}
          onClose={() => setShowArrForm(false)}
          onSave={saveArr}
          saving={savingArr}
          error={error}
          saveLabel={editingArr ? "Save changes" : "Create arrangement"}
          footerLeft={
            editingArr ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeArr(editingArr)}
                disabled={savingArr}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

export default function OutsourcingPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <OutsourcingInner />
    </Suspense>
  );
}
