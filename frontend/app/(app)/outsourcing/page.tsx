"use client";

import { useEffect, useState } from "react";
import { apiCall, type Page } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

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
  country: string;
  sbp_approval_required: boolean;
  sbp_approval_status: string;
  sbp_approval_ref: string;
  contract_start: string | null;
  contract_end: string | null;
  exit_plan: string;
  exit_plan_tested: boolean;
  concentration_note: string;
  status: string;
  owner: string;
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
}
interface VendorOption {
  id: string;
  name: string;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const REVIEW_STATUS = opts(["planned", "completed"]);

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
const STATUS_TONE: Record<string, Tone> = {
  proposed: "neutral",
  active: "low",
  under_review: "medium",
  terminated: "neutral",
};
const REVIEW_STATUS_TONE: Record<string, Tone> = {
  planned: "neutral",
  completed: "low",
};

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
  country: string;
  sbp_approval_required: boolean;
  sbp_approval_status: string;
  sbp_approval_ref: string;
  contract_start: string;
  contract_end: string;
  exit_plan: string;
  exit_plan_tested: boolean;
  concentration_note: string;
  status: string;
  owner: string;
  workflow_status: string;
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
  country: "",
  sbp_approval_required: false,
  sbp_approval_status: "not_required",
  sbp_approval_ref: "",
  contract_start: "",
  contract_end: "",
  exit_plan: "",
  exit_plan_tested: false,
  concentration_note: "",
  status: "proposed",
  owner: "",
  workflow_status: "draft",
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
    country: a.country || "",
    sbp_approval_required: !!a.sbp_approval_required,
    sbp_approval_status: a.sbp_approval_status || "not_required",
    sbp_approval_ref: a.sbp_approval_ref || "",
    contract_start: a.contract_start || "",
    contract_end: a.contract_end || "",
    exit_plan: a.exit_plan || "",
    exit_plan_tested: !!a.exit_plan_tested,
    concentration_note: a.concentration_note || "",
    status: a.status || "proposed",
    owner: a.owner || "",
    workflow_status: a.workflow_status || "draft",
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
    country: f.country,
    sbp_approval_required: f.sbp_approval_required,
    sbp_approval_status: f.sbp_approval_status,
    sbp_approval_ref: f.sbp_approval_ref,
    contract_start: f.contract_start || null,
    contract_end: f.contract_end || null,
    exit_plan: f.exit_plan,
    exit_plan_tested: f.exit_plan_tested,
    concentration_note: f.concentration_note,
    status: f.status,
    owner: f.owner,
    workflow_status: f.workflow_status,
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

export default function OutsourcingPage() {
  const [error, setError] = useState<string | null>(null);

  const [arrangements, setArrangements] = useState<OutsourcingArrangement[]>([]);
  const [summary, setSummary] = useState<OutsourcingSummary | null>(null);
  const [vendors, setVendors] = useState<VendorOption[]>([]);

  // ---- filters ----
  const [search, setSearch] = useState("");
  const [fCategory, setFCategory] = useState("");
  const [fMateriality, setFMateriality] = useState("");
  const [fStatus, setFStatus] = useState("");

  // ---- arrangement dialog ----
  const [editingArr, setEditingArr] = useState<OutsourcingArrangement | null>(null);
  const [showArrForm, setShowArrForm] = useState(false);
  const [savingArr, setSavingArr] = useState(false);
  const [af, setAf] = useState<ArrForm>(BLANK_ARR);
  const setA = <K extends keyof ArrForm>(k: K, v: ArrForm[K]) => setAf((p) => ({ ...p, [k]: v }));

  // ---- expanded detail + inline review add-form ----
  const [openArr, setOpenArr] = useState<OutsourcingArrangement | null>(null);
  const [rd, setRd] = useState<ReviewDraft>(BLANK_REVIEW);
  const setRD = <K extends keyof ReviewDraft>(k: K, v: ReviewDraft[K]) => setRd((p) => ({ ...p, [k]: v }));

  const vendorName = (id: string | null) =>
    id ? vendors.find((v) => v.id === id)?.name || "Linked vendor" : "";

  // ------------------------------------------------------------- loaders
  async function loadArrangements(keepOpen?: string) {
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (search.trim()) params.set("search", search.trim());
      if (fCategory) params.set("category", fCategory);
      if (fMateriality) params.set("materiality", fMateriality);
      if (fStatus) params.set("status", fStatus);
      const res = await apiCall<Page<OutsourcingArrangement>>("GET", `/outsourcing?${params.toString()}`);
      setArrangements(res.items);
      if (keepOpen) setOpenArr(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load outsourcing arrangements");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<OutsourcingSummary>("GET", "/outsourcing-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load outsourcing summary");
    }
  }
  async function loadVendors() {
    try {
      const res = await apiCall<Page<VendorOption>>("GET", "/vendors?limit=200");
      setVendors(res.items);
    } catch {
      // Vendor linking is optional — a missing vendor list must not block the page.
      setVendors([]);
    }
  }
  async function refreshArr(id: string) {
    const a = await apiCall<OutsourcingArrangement>("GET", `/outsourcing/${id}`);
    setOpenArr(a);
    setArrangements((prev) => prev.map((x) => (x.id === id ? a : x)));
  }

  useEffect(() => {
    loadArrangements();
    loadSummary();
    loadVendors();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------------------- arrangement CRUD
  function openNewArr() {
    setEditingArr(null);
    setAf(BLANK_ARR);
    setShowArrForm(true);
  }
  function openEditArr(a: OutsourcingArrangement) {
    setEditingArr(a);
    setAf(fromArr(a));
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
      await loadArrangements(openArr?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save arrangement");
    } finally {
      setSavingArr(false);
    }
  }
  async function removeArr(a: OutsourcingArrangement) {
    if (!window.confirm(`Delete outsourcing arrangement ${a.reference || a.title}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/outsourcing/${a.id}`);
      setShowArrForm(false);
      if (openArr?.id === a.id) setOpenArr(null);
      await loadArrangements();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleArr(a: OutsourcingArrangement) {
    setRd(BLANK_REVIEW);
    setOpenArr(openArr?.id === a.id ? null : a);
  }

  // ------------------------------------------------------------- reviews (inline)
  async function addReview() {
    if (!openArr) return;
    setError(null);
    try {
      await apiCall<OutsourcingArrangement>("POST", `/outsourcing/${openArr.id}/reviews`, {
        review_date: rd.review_date || null,
        reviewer: rd.reviewer,
        outcome: rd.outcome,
        sla_met: rd.sla_met,
        issues_noted: rd.issues_noted,
        status: rd.status,
      });
      setRd(BLANK_REVIEW);
      await refreshArr(openArr.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add review");
    }
  }
  async function removeReview(rid: string) {
    if (!openArr) return;
    if (!window.confirm("Remove this review?")) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/outsourcing-reviews/${rid}`);
      await refreshArr(openArr.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove review");
    }
  }

  // ------------------------------------------------------------- form tabs
  const arrangementTab = (
    <>
      <Field label="Title" required help="For example: Core banking hosting — data centre.">
        <TextInput value={af.title} onChange={(v) => setA("title", v)} placeholder="Arrangement title" required />
      </Field>
      <div className="field-row">
        <Field label="Service provider" help="The outsourcing service provider / supplier.">
          <TextInput value={af.service_provider} onChange={(v) => setA("service_provider", v)} placeholder="Provider name" />
        </Field>
        <Field label="Linked vendor" help="Optional link to the vendor register.">
          <Select
            value={af.vendor_id}
            onChange={(v) => setA("vendor_id", v)}
            options={vendors.map((v) => ({ value: v.id, label: v.name }))}
            placeholder="No linked vendor"
          />
        </Field>
      </div>
      <Field label="Service description" help="What service is being outsourced.">
        <TextArea value={af.service_description} onChange={(v) => setA("service_description", v)} rows={3} placeholder="Scope of the outsourced service." />
      </Field>
      <div className="field-row">
        <Field label="Category">
          <Select value={af.category} onChange={(v) => setA("category", v)} options={CATEGORY} />
        </Field>
        <Field label="Status">
          <Select value={af.status} onChange={(v) => setA("status", v)} options={STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Owner" help="Accountable business / risk owner.">
          <TextInput value={af.owner} onChange={(v) => setA("owner", v)} placeholder="Owner" />
        </Field>
        <Field label="Workflow" help="Approval lifecycle for this arrangement record.">
          <Select value={af.workflow_status} onChange={(v) => setA("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );
  const materialityTab = (
    <>
      <Field label="Materiality" help="SBP materiality determination — material arrangements carry heavier obligations.">
        <Select value={af.materiality} onChange={(v) => setA("materiality", v)} options={MATERIALITY} />
      </Field>
      <Field label="Materiality assessment" help="Rationale for the materiality determination.">
        <TextArea value={af.materiality_assessment} onChange={(v) => setA("materiality_assessment", v)} rows={3} placeholder="Why the arrangement is (non-)material: criticality, data sensitivity, substitutability…" />
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
          <TextInput value={af.country} onChange={(v) => setA("country", v)} placeholder="Pakistan" />
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
    </>
  );
  const exitTab = (
    <>
      <Field label="Exit plan" help="Documented exit / termination strategy (SBP expectation for material arrangements).">
        <TextArea value={af.exit_plan} onChange={(v) => setA("exit_plan", v)} rows={4} placeholder="How the bank would exit or bring the service back in-house, alternate providers, data return / destruction…" />
      </Field>
      <Field label="Exit plan tested" help="Whether the exit plan has been tested / rehearsed.">
        <Toggle checked={af.exit_plan_tested} onChange={(v) => setA("exit_plan_tested", v)} label="Exit plan tested" />
      </Field>
      <Field label="Concentration note" help="Concentration-risk considerations (provider / geography / technology).">
        <TextArea value={af.concentration_note} onChange={(v) => setA("concentration_note", v)} rows={3} placeholder="Reliance on a single provider, sub-outsourcing chains, sector-wide concentration…" />
      </Field>
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
          <button className="btn" onClick={openNewArr}>
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
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head row-between">
          <div>
            <h3>Outsourcing Arrangements</h3>
            <span className="sub">
              {arrangements.length} shown · click a row to manage reviews
              {summary && summary.exit_plans_untested > 0 ? ` · ${summary.exit_plans_untested} material exit plan(s) untested` : ""}
            </span>
          </div>
        </div>

        <form
          className="card-pad"
          style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap", paddingBottom: 0 }}
          onSubmit={(ev) => { ev.preventDefault(); loadArrangements(openArr?.id); }}
        >
          <div style={{ flex: "1 1 220px" }}>
            <label className="label">Search</label>
            <input className="input" value={search} onChange={(ev) => setSearch(ev.target.value)} placeholder="Title, reference, provider, owner" />
          </div>
          <div style={{ width: 190 }}>
            <label className="label">Category</label>
            <select className="select" value={fCategory} onChange={(ev) => setFCategory(ev.target.value)}>
              <option value="">All categories</option>
              {CATEGORY.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
          </div>
          <div style={{ width: 160 }}>
            <label className="label">Materiality</label>
            <select className="select" value={fMateriality} onChange={(ev) => setFMateriality(ev.target.value)}>
              <option value="">All</option>
              {MATERIALITY.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
          </div>
          <div style={{ width: 160 }}>
            <label className="label">Status</label>
            <select className="select" value={fStatus} onChange={(ev) => setFStatus(ev.target.value)}>
              <option value="">All statuses</option>
              {STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
          </div>
          <button className="btn secondary sm" type="submit">Apply</button>
        </form>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Service provider</th>
                <th>Category</th>
                <th>Materiality</th>
                <th>Cloud</th>
                <th>SBP approval</th>
                <th>Contract end</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {arrangements.map((a) => (
                <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => toggleArr(a)}>
                  <td className="ref">{a.reference || "—"}</td>
                  <td className="cell-title">{a.title}</td>
                  <td className="muted">{a.service_provider || vendorName(a.vendor_id) || "—"}</td>
                  <td><Badge tone="info">{cap(a.category)}</Badge></td>
                  <td><Badge tone={MATERIALITY_TONE[a.materiality] || "neutral"}>{cap(a.materiality)}</Badge></td>
                  <td>
                    {a.is_cloud ? (
                      <Badge tone="info">{a.cloud_model && a.cloud_model !== "not_applicable" ? cloudLabel(a.cloud_model) : "Cloud"}</Badge>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    <Badge tone={SBP_TONE[a.sbp_approval_status] || "neutral"}>{cap(a.sbp_approval_status)}</Badge>
                  </td>
                  <td>
                    {a.is_contract_expiring ? (
                      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                        <Badge tone="high">Expiring</Badge>
                        <span className="muted">{a.contract_end}</span>
                      </div>
                    ) : (
                      <span className="muted">{a.contract_end || "—"}</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => toggleArr(a)}>
                        {openArr?.id === a.id ? "Hide" : "Manage"}
                      </button>
                      <button className="btn secondary sm" onClick={() => openEditArr(a)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => removeArr(a)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {arrangements.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconCheck width={24} height={24} /></span>
                      <h3>No outsourcing arrangements</h3>
                      <p>Register the bank&apos;s outsourcing and cloud arrangements to track SBP materiality, approvals, exit plans and concentration risk.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {openArr && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head row-between">
              <div>
                <h3>{openArr.reference} — {openArr.title}</h3>
                <span className="sub">
                  {cap(openArr.category)} · {cap(openArr.materiality)} · {cap(openArr.status)}
                  {openArr.service_provider ? " · " + openArr.service_provider : ""}
                  {openArr.is_cloud ? " · cloud (" + cloudLabel(openArr.cloud_model) + ")" : ""}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn secondary sm" onClick={() => openEditArr(openArr)}>Edit</button>
                <button className="btn secondary sm" onClick={() => removeArr(openArr)}>Delete</button>
              </div>
            </div>

            <div className="card-pad">
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
                <Badge tone={MATERIALITY_TONE[openArr.materiality] || "neutral"}>{cap(openArr.materiality)}</Badge>
                <Badge tone={SBP_TONE[openArr.sbp_approval_status] || "neutral"}>SBP: {cap(openArr.sbp_approval_status)}</Badge>
                {openArr.sbp_approval_required && <Badge tone="medium">Approval required</Badge>}
                {openArr.is_cloud && <Badge tone="info">Cloud · {cloudLabel(openArr.cloud_model)}</Badge>}
                {openArr.data_offshored && <Badge tone="high">Data offshored{openArr.country ? " · " + openArr.country : ""}</Badge>}
                <Badge tone={openArr.exit_plan_tested ? "low" : "medium"}>Exit plan {openArr.exit_plan_tested ? "tested" : "untested"}</Badge>
                {openArr.is_contract_expiring && <Badge tone="high">Contract expiring ≤90d</Badge>}
              </div>

              <div className="field-row" style={{ marginBottom: 12 }}>
                <div style={{ flex: 1 }}>
                  <div className="label">Materiality assessment</div>
                  <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                    {openArr.materiality_assessment || "—"}
                  </p>
                </div>
                <div style={{ flex: 1 }}>
                  <div className="label">Exit plan</div>
                  <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                    {openArr.exit_plan || "—"}
                  </p>
                </div>
              </div>
              <div style={{ marginBottom: 16 }}>
                <div className="label">Concentration note</div>
                <p className="muted" style={{ margin: "4px 0", fontSize: 13, whiteSpace: "pre-wrap" }}>
                  {openArr.concentration_note || "—"}
                </p>
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  {openArr.sbp_approval_ref ? `NOC ref ${openArr.sbp_approval_ref} · ` : ""}
                  Contract {openArr.contract_start || "—"} → {openArr.contract_end || "—"}
                  {openArr.vendor_id ? ` · linked vendor ${vendorName(openArr.vendor_id)}` : ""}
                </div>
              </div>

              <strong>Monitoring reviews</strong>
              <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
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
                    {[...openArr.reviews]
                      .sort((a, b) => (b.review_date || "").localeCompare(a.review_date || ""))
                      .map((rv) => (
                        <tr key={rv.id}>
                          <td className="ref">{rv.reference || "—"}</td>
                          <td className="muted">{rv.review_date || "—"}</td>
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
                    {openArr.reviews.length === 0 && (
                      <tr><td colSpan={8}><span className="muted">No reviews recorded yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <RecordPanels model="outsourcing_arrangement" entityId={openArr.id} />
        </>
      )}

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
