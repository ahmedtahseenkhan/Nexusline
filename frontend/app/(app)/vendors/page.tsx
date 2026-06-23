"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall, type Page, type Risk, type Asset } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import RichText from "@/components/RichText";
import {
  Field,
  TextInput,
  TextArea,
  Select,
  MultiSelect,
  Toggle,
  NumberInput,
  type Option,
} from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconPlus, IconVendor } from "@/components/icons";

// ---------------------------------------------------------------- inline types
// The shared lib/api.ts Vendor type is intentionally minimal; the vendor module
// exposes the full record, so we model it locally here.
type RefItem = { id: string; reference?: string; title?: string; name?: string };

type VendorType = { id: string; name: string; description: string };

type ServiceContract = {
  id: string;
  name: string;
  description: string;
  value: number | null;
  start_date: string | null;
  end_date: string | null;
  is_expired: boolean;
  created_at: string;
};

type Vendor = {
  id: string;
  name: string;
  description: string;
  category: string;
  type_id: string | null;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  website: string;
  location: string;
  criticality: string;
  status: string;
  workflow_status: string;
  risk_rating: string | null;
  shares_data: boolean;
  assessment_status: string;
  last_assessed_at: string | null;
  onboarded_at: string | null;
  offboarded_at: string | null;
  review_frequency: string;
  next_review_date: string | null;
  type: VendorType | null;
  contracts: ServiceContract[];
  risks: RefItem[];
  assets: RefItem[];
  contract_count: number;
  active_contract_value: number;
  created_at: string;
};

// ------------------------------------------------------------------ enum options
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const CRITICALITY = opts(["low", "medium", "high", "critical"]);
const STATUS = opts(["prospective", "active", "suspended", "offboarded"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const RISK_RATING = opts(["low", "medium", "high", "critical"]);
const ASSESS = opts(["not_started", "in_progress", "completed"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  active: "low",
  prospective: "info",
  suspended: "medium",
  offboarded: "neutral",
};
const ASSESS_TONE: Record<string, "low" | "medium" | "neutral"> = {
  completed: "low",
  in_progress: "medium",
  not_started: "neutral",
};

const money = (n: number) =>
  n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });

// -------------------------------------------------------------------- form state
type FormState = {
  name: string;
  description: string;
  category: string;
  type_id: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  website: string;
  location: string;
  criticality: string;
  status: string;
  workflow_status: string;
  shares_data: boolean;
  risk_rating: string;
  assessment_status: string;
  last_assessed_at: string;
  onboarded_at: string;
  offboarded_at: string;
  review_frequency: string;
  next_review_date: string;
  risk_ids: string[];
  asset_ids: string[];
};

const BLANK: FormState = {
  name: "", description: "", category: "", type_id: "",
  contact_name: "", contact_email: "", contact_phone: "", website: "", location: "",
  criticality: "medium", status: "active", workflow_status: "draft", shares_data: false,
  risk_rating: "", assessment_status: "not_started", last_assessed_at: "",
  onboarded_at: "", offboarded_at: "", review_frequency: "annual", next_review_date: "",
  risk_ids: [], asset_ids: [],
};

function fromVendor(v: Vendor): FormState {
  return {
    name: v.name,
    description: v.description || "",
    category: v.category || "",
    type_id: v.type_id || "",
    contact_name: v.contact_name || "",
    contact_email: v.contact_email || "",
    contact_phone: v.contact_phone || "",
    website: v.website || "",
    location: v.location || "",
    criticality: v.criticality,
    status: v.status,
    workflow_status: v.workflow_status,
    shares_data: v.shares_data,
    risk_rating: v.risk_rating || "",
    assessment_status: v.assessment_status,
    last_assessed_at: v.last_assessed_at || "",
    onboarded_at: v.onboarded_at || "",
    offboarded_at: v.offboarded_at || "",
    review_frequency: v.review_frequency,
    next_review_date: v.next_review_date || "",
    risk_ids: v.risks.map((r) => r.id),
    asset_ids: v.assets.map((a) => a.id),
  };
}

// Convert form state -> API payload (empty strings for optional scalars/dates -> null).
function toPayload(f: FormState): Record<string, unknown> {
  return {
    name: f.name,
    description: f.description,
    category: f.category,
    type_id: f.type_id || null,
    contact_name: f.contact_name,
    contact_email: f.contact_email,
    contact_phone: f.contact_phone,
    website: f.website,
    location: f.location,
    criticality: f.criticality,
    status: f.status,
    workflow_status: f.workflow_status,
    shares_data: f.shares_data,
    risk_rating: f.risk_rating || null,
    assessment_status: f.assessment_status,
    last_assessed_at: f.last_assessed_at || null,
    onboarded_at: f.onboarded_at || null,
    offboarded_at: f.offboarded_at || null,
    review_frequency: f.review_frequency,
    next_review_date: f.next_review_date || null,
    risk_ids: f.risk_ids,
    asset_ids: f.asset_ids,
  };
}

// -------------------------------------------------- new-contract sub-form state
type ContractForm = {
  name: string;
  description: string;
  value: number | "";
  start_date: string;
  end_date: string;
};
const BLANK_CONTRACT: ContractForm = {
  name: "", description: "", value: "", start_date: "", end_date: "",
};

export default function VendorsPage() {
  const [items, setItems] = useState<Vendor[]>([]);
  const [types, setTypes] = useState<VendorType[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Vendor | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const [detailId, setDetailId] = useState<string | null>(null);

  // contract sub-form (only available while editing an existing vendor)
  const [contract, setContract] = useState<ContractForm>(BLANK_CONTRACT);
  const [contractBusy, setContractBusy] = useState(false);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  const setC = <K extends keyof ContractForm>(k: K, v: ContractForm[K]) =>
    setContract((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems((await apiCall<Page<Vendor>>("GET", "/vendors?limit=200")).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
    apiCall<VendorType[]>("GET", "/vendor-types").then(setTypes).catch(() => {});
    apiCall<Page<Risk>>("GET", "/risks?limit=200").then((r) => setRisks(r.items)).catch(() => {});
    apiCall<Page<Asset>>("GET", "/assets?limit=200").then((r) => setAssets(r.items)).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setContract(BLANK_CONTRACT);
    setShowForm(true);
  }
  function openEdit(v: Vendor) {
    setEditing(v);
    setF(fromVendor(v));
    setContract(BLANK_CONTRACT);
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Vendor>("PATCH", `/vendors/${editing.id}`, payload);
      else await apiCall<Vendor>("POST", "/vendors", payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save vendor");
    } finally {
      setSaving(false);
    }
  }

  async function remove(v: Vendor) {
    if (!window.confirm(`Delete vendor "${v.name}"? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/vendors/${v.id}`);
      if (detailId === v.id) setDetailId(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete vendor");
    }
  }

  async function addContract() {
    if (!editing || !contract.name.trim()) return;
    setContractBusy(true);
    setError(null);
    try {
      const updated = await apiCall<Vendor>("POST", `/vendors/${editing.id}/contracts`, {
        name: contract.name,
        description: contract.description,
        value: contract.value === "" ? null : contract.value,
        start_date: contract.start_date || null,
        end_date: contract.end_date || null,
      });
      setEditing(updated);
      setContract(BLANK_CONTRACT);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add contract");
    } finally {
      setContractBusy(false);
    }
  }

  async function removeContract(contractId: string) {
    if (!editing) return;
    setContractBusy(true);
    setError(null);
    try {
      await apiCall<void>("DELETE", `/vendors/contracts/${contractId}`);
      const updated = await apiCall<Vendor>("GET", `/vendors/${editing.id}`);
      setEditing(updated);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete contract");
    } finally {
      setContractBusy(false);
    }
  }

  // ---------------------------------------------------------------- option lists
  const typeOpts: Option[] = useMemo(
    () => types.map((t) => ({ value: t.id, label: t.name })),
    [types],
  );
  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: r.title, sub: r.reference })),
    [risks],
  );
  const assetOpts: Option[] = useMemo(
    () => assets.map((a) => ({ value: a.id, label: a.name })),
    [assets],
  );

  const linkCount = (v: Vendor) => v.risks.length + v.assets.length;

  // ------------------------------------------------------------------------ tabs
  const generalTab = (
    <>
      <Field label="Name" required help="The third party / supplier name, e.g. Stripe, AWS, Acme Consulting.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Stripe" required />
      </Field>
      <Field label="Description">
        <TextArea
          value={f.description}
          onChange={(v) => set("description", v)}
          rows={3}
          placeholder="What this vendor provides and how it is used."
        />
      </Field>
      <div className="field-row">
        <Field label="Category">
          <TextInput value={f.category} onChange={(v) => set("category", v)} placeholder="Payments" />
        </Field>
        <Field label="Type" help="Third-party taxonomy (managed under vendor types).">
          <Select value={f.type_id} onChange={(v) => set("type_id", v)} options={typeOpts} placeholder="Choose a type…" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Contact Name">
          <TextInput value={f.contact_name} onChange={(v) => set("contact_name", v)} placeholder="Account manager" />
        </Field>
        <Field label="Contact Email">
          <TextInput value={f.contact_email} onChange={(v) => set("contact_email", v)} type="email" placeholder="support@vendor.com" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Contact Phone">
          <TextInput value={f.contact_phone} onChange={(v) => set("contact_phone", v)} placeholder="+1 555 0100" />
        </Field>
        <Field label="Website">
          <TextInput value={f.website} onChange={(v) => set("website", v)} placeholder="https://vendor.com" />
        </Field>
        <Field label="Location">
          <TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="Dublin, IE" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Criticality" help="How critical this vendor is to your operations.">
          <Select value={f.criticality} onChange={(v) => set("criticality", v)} options={CRITICALITY} />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
      </div>
      <Field label="Shares / processes data" help="Toggle on if this vendor stores, processes or has access to your data.">
        <Toggle checked={f.shares_data} onChange={(v) => set("shares_data", v)} label="Vendor handles our data" />
      </Field>
    </>
  );

  const riskTab = (
    <>
      <div className="field-row">
        <Field label="Risk Rating" help="Overall residual risk this vendor poses.">
          <Select value={f.risk_rating} onChange={(v) => set("risk_rating", v)} options={RISK_RATING} placeholder="Not rated" />
        </Field>
        <Field label="Assessment Status">
          <Select value={f.assessment_status} onChange={(v) => set("assessment_status", v)} options={ASSESS} />
        </Field>
        <Field label="Last Assessed">
          <TextInput value={f.last_assessed_at} onChange={(v) => set("last_assessed_at", v)} type="date" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Review Frequency" help="How often this vendor relationship should be reviewed.">
          <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
        </Field>
        <Field label="Next Review Date">
          <TextInput value={f.next_review_date} onChange={(v) => set("next_review_date", v)} type="date" />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Onboarded">
          <TextInput value={f.onboarded_at} onChange={(v) => set("onboarded_at", v)} type="date" />
        </Field>
        <Field label="Offboarded">
          <TextInput value={f.offboarded_at} onChange={(v) => set("offboarded_at", v)} type="date" />
        </Field>
      </div>
    </>
  );

  const contractsTab = (
    <>
      {!editing && (
        <div className="card card-pad" style={{ marginBottom: 14 }}>
          Save the vendor first, then add service contracts here.
        </div>
      )}
      {editing && (
        <>
          <div className="table-wrap" style={{ marginBottom: 16 }}>
            <table>
              <thead>
                <tr>
                  <th>Contract</th>
                  <th>Value</th>
                  <th>Start</th>
                  <th>End</th>
                  <th>State</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {editing.contracts.map((c) => (
                  <tr key={c.id}>
                    <td className="cell-title">{c.name}</td>
                    <td className="muted">{c.value != null ? money(c.value) : "—"}</td>
                    <td className="muted">{c.start_date || "—"}</td>
                    <td className="muted">{c.end_date || "—"}</td>
                    <td>
                      {c.is_expired ? <Badge tone="high">Expired</Badge> : <Badge tone="low">Active</Badge>}
                    </td>
                    <td>
                      <button
                        className="btn secondary sm"
                        type="button"
                        disabled={contractBusy}
                        onClick={() => removeContract(c.id)}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
                {editing.contracts.length === 0 && (
                  <tr>
                    <td colSpan={6}><span className="muted">No contracts yet.</span></td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="card card-pad">
            <Field label="Add Contract" help="Record a contract, SLA or order with this vendor.">
              <TextInput value={contract.name} onChange={(v) => setC("name", v)} placeholder="Master Services Agreement" />
            </Field>
            <Field label="Description">
              <TextArea value={contract.description} onChange={(v) => setC("description", v)} rows={2} />
            </Field>
            <div className="field-row">
              <Field label="Value (USD)">
                <NumberInput value={contract.value} onChange={(v) => setC("value", v)} min={0} placeholder="50000" />
              </Field>
              <Field label="Start Date">
                <TextInput value={contract.start_date} onChange={(v) => setC("start_date", v)} type="date" />
              </Field>
              <Field label="End Date">
                <TextInput value={contract.end_date} onChange={(v) => setC("end_date", v)} type="date" />
              </Field>
            </div>
            <button
              className="btn"
              type="button"
              disabled={contractBusy || !contract.name.trim()}
              onClick={addContract}
            >
              <IconPlus width={16} height={16} /> Add contract
            </button>
          </div>
        </>
      )}
    </>
  );

  const linksTab = (
    <>
      <Field label="Related Risks" help="Risks this vendor introduces or is associated with.">
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
      <Field label="Related Assets" help="Assets or data this vendor touches, hosts or has access to.">
        <MultiSelect value={f.asset_ids} onChange={(v) => set("asset_ids", v)} options={assetOpts} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Third-Party Risk</h1>
          <p>Vendor registry with criticality, risk rating, assessment status, contracts and linked risks/assets.</p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} /> Add vendor
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Vendors</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Type / Category</th>
                <th>Criticality</th>
                <th>Status</th>
                <th>Risk rating</th>
                <th>Assessment</th>
                <th>Last assessed</th>
                <th>Contracts</th>
                <th>Links</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.id} style={{ cursor: "pointer" }} onClick={() => openEdit(v)}>
                  <td className="cell-title">
                    {v.name}
                    {v.shares_data && (
                      <Badge tone="info" plain>data</Badge>
                    )}
                  </td>
                  <td className="muted">{v.type?.name || v.category || "—"}</td>
                  <td><Severity value={v.criticality} /></td>
                  <td><Badge tone={STATUS_TONE[v.status] || "neutral"}>{cap(v.status)}</Badge></td>
                  <td><Severity value={v.risk_rating} /></td>
                  <td>
                    <Badge tone={ASSESS_TONE[v.assessment_status] || "neutral"}>
                      {cap(v.assessment_status)}
                    </Badge>
                  </td>
                  <td className="muted">{v.last_assessed_at || "—"}</td>
                  <td className="muted">
                    {v.contract_count > 0
                      ? `${v.contract_count} · ${money(v.active_contract_value)}`
                      : "—"}
                  </td>
                  <td className="muted">{linkCount(v) || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button
                        className="btn secondary sm"
                        onClick={() => setDetailId(detailId === v.id ? null : v.id)}
                      >
                        Details
                      </button>
                      <button className="btn secondary sm" onClick={() => remove(v)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconVendor width={24} height={24} /></span>
                      <h3>No vendors</h3>
                      <p>Add the third parties your organization relies on.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detailId && <RecordPanels model="vendor" entityId={detailId} />}

      {showForm && (
        <FormModal
          title={editing ? `Edit vendor — ${editing.name}` : "Add item (Vendors)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "risk", label: "Risk & Assessment", content: riskTab },
            { id: "contracts", label: "Contracts", content: contractsTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create vendor"}
        />
      )}
    </>
  );
}
