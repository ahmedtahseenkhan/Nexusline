"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, MultiSelect, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconAlert, IconPlus, IconPolicy, IconShield } from "@/components/icons";

// ---- inline types (mirror backend RopaRead — schemas/privacy.py) ----
type Ref = { id: string; name?: string; title?: string; reference?: string };

type Ropa = {
  id: string;
  reference: string;
  name: string;
  description: string;
  purpose: string;
  status: string;
  workflow_status: string;
  lawful_basis: string;
  data_subjects: string;
  data_categories: string;
  data_types: string;
  collection_methods: string;
  volume: string;
  special_category: boolean;
  retention_period: string;
  archiving_driver: string;
  recipients: string;
  security_measures: string;
  accuracy: string;
  right_to_be_informed: string;
  right_to_access: string;
  right_to_rectification: string;
  right_to_erasure: string;
  right_to_portability: string;
  right_to_object: string;
  controller: string;
  processor: string;
  dpo: string;
  business_unit_id: string | null;
  cross_border_transfer: boolean;
  origin: string;
  transfer_destinations: string;
  transfer_safeguard: string;
  dpia_required: boolean;
  dpia_status: string;
  review_frequency: string;
  review_date: string | null;
  has_transfer_gap: boolean;
  dpia_outstanding: boolean;
  business_unit: Ref | null;
  assets: Ref[];
  risks: Ref[];
  processes: Ref[];
  policies: Ref[];
  created_at: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
type BizUnit = { id: string; name: string };
type ProcessRow = { id: string; name: string; description?: string };
type PolicyRow = { id: string; title: string; reference?: string };
type AssetRow = { id: string; name: string };
type RiskRow = { id: string; reference?: string; title?: string };

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "active", "under_review", "retired"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const BASES = opts(["consent", "contract", "legal_obligation", "vital_interests", "public_task", "legitimate_interests"]);
const DPIA = opts(["not_required", "required", "in_progress", "completed"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  active: "low",
  under_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

type FormState = {
  name: string;
  description: string;
  purpose: string;
  status: string;
  workflow_status: string;
  controller: string;
  processor: string;
  dpo: string;
  business_unit_id: string;
  // lawfulness & data
  lawful_basis: string;
  data_subjects: string;
  data_categories: string;
  data_types: string;
  collection_methods: string;
  volume: string;
  special_category: boolean;
  // transfers & retention
  recipients: string;
  retention_period: string;
  archiving_driver: string;
  security_measures: string;
  accuracy: string;
  cross_border_transfer: boolean;
  origin: string;
  transfer_destinations: string;
  transfer_safeguard: string;
  dpia_required: boolean;
  dpia_status: string;
  review_frequency: string;
  review_date: string;
  // data subject rights
  right_to_be_informed: string;
  right_to_access: string;
  right_to_rectification: string;
  right_to_erasure: string;
  right_to_portability: string;
  right_to_object: string;
  // links
  process_ids: string[];
  policy_ids: string[];
  asset_ids: string[];
  risk_ids: string[];
};

const BLANK: FormState = {
  name: "", description: "", purpose: "", status: "draft", workflow_status: "draft",
  controller: "", processor: "", dpo: "", business_unit_id: "",
  lawful_basis: "consent", data_subjects: "", data_categories: "", data_types: "",
  collection_methods: "", volume: "", special_category: false,
  recipients: "", retention_period: "", archiving_driver: "", security_measures: "", accuracy: "",
  cross_border_transfer: false, origin: "", transfer_destinations: "", transfer_safeguard: "",
  dpia_required: false, dpia_status: "not_required", review_frequency: "annual", review_date: "",
  right_to_be_informed: "", right_to_access: "", right_to_rectification: "",
  right_to_erasure: "", right_to_portability: "", right_to_object: "",
  process_ids: [], policy_ids: [], asset_ids: [], risk_ids: [],
};

function fromRopa(r: Ropa): FormState {
  return {
    name: r.name, description: r.description || "", purpose: r.purpose || "",
    status: r.status, workflow_status: r.workflow_status,
    controller: r.controller || "", processor: r.processor || "", dpo: r.dpo || "",
    business_unit_id: r.business_unit_id || "",
    lawful_basis: r.lawful_basis, data_subjects: r.data_subjects || "",
    data_categories: r.data_categories || "", data_types: r.data_types || "",
    collection_methods: r.collection_methods || "", volume: r.volume || "",
    special_category: r.special_category,
    recipients: r.recipients || "", retention_period: r.retention_period || "",
    archiving_driver: r.archiving_driver || "", security_measures: r.security_measures || "",
    accuracy: r.accuracy || "",
    cross_border_transfer: r.cross_border_transfer, origin: r.origin || "",
    transfer_destinations: r.transfer_destinations || "", transfer_safeguard: r.transfer_safeguard || "",
    dpia_required: r.dpia_required, dpia_status: r.dpia_status,
    review_frequency: r.review_frequency, review_date: r.review_date || "",
    right_to_be_informed: r.right_to_be_informed || "", right_to_access: r.right_to_access || "",
    right_to_rectification: r.right_to_rectification || "", right_to_erasure: r.right_to_erasure || "",
    right_to_portability: r.right_to_portability || "", right_to_object: r.right_to_object || "",
    process_ids: r.processes.map((p) => p.id),
    policy_ids: r.policies.map((p) => p.id),
    asset_ids: r.assets.map((a) => a.id),
    risk_ids: r.risks.map((x) => x.id),
  };
}

/** Strip empty optional FKs/dates to null so the backend accepts them. */
function toPayload(f: FormState): Record<string, unknown> {
  return {
    ...f,
    business_unit_id: f.business_unit_id || null,
    review_date: f.review_date || null,
  };
}

export default function PrivacyPage() {
  const [items, setItems] = useState<Ropa[]>([]);
  const [units, setUnits] = useState<BizUnit[]>([]);
  const [processes, setProcesses] = useState<ProcessRow[]>([]);
  const [policies, setPolicies] = useState<PolicyRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [risks, setRisks] = useState<RiskRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Ropa | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const [detailId, setDetailId] = useState<string | null>(null);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems((await apiCall<Page<Ropa>>("GET", "/processing-activities?limit=200")).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
    apiCall<Page<BizUnit>>("GET", "/business-units").then((r) => setUnits(r.items)).catch(() => {});
    apiCall<Page<ProcessRow>>("GET", "/processes").then((r) => setProcesses(r.items)).catch(() => {});
    apiCall<Page<PolicyRow>>("GET", "/policies?limit=200").then((r) => setPolicies(r.items)).catch(() => {});
    apiCall<Page<AssetRow>>("GET", "/assets?limit=200").then((r) => setAssets(r.items)).catch(() => {});
    apiCall<Page<RiskRow>>("GET", "/risks?limit=200").then((r) => setRisks(r.items)).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  async function openEdit(r: Ropa) {
    setEditing(r);
    setError(null);
    // list rows already carry every field; refetch one for freshest link arrays.
    try {
      const fresh = await apiCall<Ropa>("GET", `/processing-activities/${r.id}`);
      setF(fromRopa(fresh));
    } catch {
      setF(fromRopa(r));
    }
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      if (editing) await apiCall<Ropa>("PATCH", `/processing-activities/${editing.id}`, toPayload(f));
      else await apiCall<Ropa>("POST", "/processing-activities", toPayload(f));
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save record");
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: Ropa) {
    if (!window.confirm(`Delete RoPA ${r.reference} — ${r.name}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/processing-activities/${r.id}`);
      if (detailId === r.id) setDetailId(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete record");
    }
  }

  const unitOpts: Option[] = useMemo(() => units.map((u) => ({ value: u.id, label: u.name })), [units]);
  const processOpts: Option[] = useMemo(
    () => processes.map((p) => ({ value: p.id, label: p.name, sub: p.description })),
    [processes],
  );
  const policyOpts: Option[] = useMemo(
    () => policies.map((p) => ({ value: p.id, label: p.title, sub: p.reference })),
    [policies],
  );
  const assetOpts: Option[] = useMemo(() => assets.map((a) => ({ value: a.id, label: a.name })), [assets]);
  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: r.title || r.reference || r.id, sub: r.reference })),
    [risks],
  );

  const gaps = items.filter((i) => i.has_transfer_gap).length;
  const dpias = items.filter((i) => i.dpia_outstanding).length;
  const specials = items.filter((i) => i.special_category).length;
  const linkCount = (r: Ropa) => r.processes.length + r.policies.length + r.assets.length + r.risks.length;

  // -------------------------------------------------------------- tabs
  const generalTab = (
    <>
      <Field label="Name" required help="A short, descriptive name for the processing activity. e.g. Marketing email processing.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Customer CRM processing" required />
      </Field>
      <Field label="Description" help="What does this activity entail at a high level?">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} />
      </Field>
      <Field label="Purpose of processing" help="Why is the personal data processed? (GDPR Art. 30(1)(b))">
        <TextArea value={f.purpose} onChange={(v) => set("purpose", v)} rows={3} placeholder="To deliver and support the customer relationship." />
      </Field>
      <div className="field-row">
        <Field label="Controller" help="Organisation/role that determines the purposes and means.">
          <TextInput value={f.controller} onChange={(v) => set("controller", v)} placeholder="NexusLine Ltd" />
        </Field>
        <Field label="Processor" help="Any party processing on the controller's behalf.">
          <TextInput value={f.processor} onChange={(v) => set("processor", v)} placeholder="Cloud CRM vendor" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Data Protection Officer">
          <TextInput value={f.dpo} onChange={(v) => set("dpo", v)} placeholder="dpo@example.com" />
        </Field>
        <Field label="Business unit">
          <Select value={f.business_unit_id} onChange={(v) => set("business_unit_id", v)} options={unitOpts} placeholder="— none —" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );

  const dataTab = (
    <>
      <Field label="Lawful basis" required help="The GDPR Art. 6 legal ground for processing.">
        <Select value={f.lawful_basis} onChange={(v) => set("lawful_basis", v)} options={BASES} />
      </Field>
      <Field label="Data subjects" help="Whose personal data is processed? e.g. Customers, Employees, Prospects.">
        <TextArea value={f.data_subjects} onChange={(v) => set("data_subjects", v)} rows={2} placeholder="Customers, employees…" />
      </Field>
      <Field label="Data categories" help="The categories of personal data processed (GDPR Art. 30(1)(c)).">
        <TextArea value={f.data_categories} onChange={(v) => set("data_categories", v)} rows={2} placeholder="Contact details, billing data…" />
      </Field>
      <Field label="Personal data types" help="Specific fields/attributes collected.">
        <TextArea value={f.data_types} onChange={(v) => set("data_types", v)} rows={2} placeholder="Name, email, phone, IP address…" />
      </Field>
      <div className="field-row">
        <Field label="Collection methods" help="How is the data collected?">
          <TextInput value={f.collection_methods} onChange={(v) => set("collection_methods", v)} placeholder="Web form, API, import…" />
        </Field>
        <Field label="Volume" help="Approximate number of data subjects.">
          <TextInput value={f.volume} onChange={(v) => set("volume", v)} placeholder="~50,000 records" />
        </Field>
      </div>
      <Field label="Special categories" help="Does this involve special-category data (Art. 9) — health, biometrics, etc.?">
        <Toggle checked={f.special_category} onChange={(v) => set("special_category", v)} label="Includes special-category personal data" />
      </Field>
    </>
  );

  const transfersTab = (
    <>
      <Field label="Recipients" help="Who receives the data — internal teams, processors, third parties.">
        <TextArea value={f.recipients} onChange={(v) => set("recipients", v)} rows={2} placeholder="Support team, payment processor…" />
      </Field>
      <div className="field-row">
        <Field label="Retention period" help="How long is the data kept?">
          <TextInput value={f.retention_period} onChange={(v) => set("retention_period", v)} placeholder="6 years after contract end" />
        </Field>
        <Field label="Review frequency">
          <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
        </Field>
        <Field label="Next review date">
          <TextInput type="date" value={f.review_date} onChange={(v) => set("review_date", v)} />
        </Field>
      </div>
      <Field label="Archiving / retention driver" help="Why was this retention period chosen? (legal, contractual…)">
        <TextArea value={f.archiving_driver} onChange={(v) => set("archiving_driver", v)} rows={2} />
      </Field>
      <Field label="Security measures" help="Technical & organisational measures protecting the data (GDPR Art. 30(1)(g)).">
        <TextArea value={f.security_measures} onChange={(v) => set("security_measures", v)} rows={2} placeholder="Encryption at rest, RBAC, MFA…" />
      </Field>
      <Field label="Accuracy" help="How is data accuracy maintained?">
        <TextArea value={f.accuracy} onChange={(v) => set("accuracy", v)} rows={2} />
      </Field>

      <Field label="International transfers" help="Is data transferred outside the EEA / across borders?">
        <Toggle checked={f.cross_border_transfer} onChange={(v) => set("cross_border_transfer", v)} label="Cross-border / international transfer" />
      </Field>
      {f.cross_border_transfer && (
        <>
          <div className="field-row">
            <Field label="Origin" help="Country/region where data originates.">
              <TextInput value={f.origin} onChange={(v) => set("origin", v)} placeholder="EEA" />
            </Field>
            <Field label="Transfer safeguard" help="SCCs, adequacy decision, BCRs… Required to avoid a transfer gap.">
              <TextInput value={f.transfer_safeguard} onChange={(v) => set("transfer_safeguard", v)} placeholder="Standard Contractual Clauses" />
            </Field>
          </div>
          <Field label="Transfer destinations" help="Destination countries/regions for the transfer.">
            <TextArea value={f.transfer_destinations} onChange={(v) => set("transfer_destinations", v)} rows={2} placeholder="United States, India…" />
          </Field>
        </>
      )}

      <div className="field-row">
        <Field label="DPIA required" help="Is a Data Protection Impact Assessment required (Art. 35)?">
          <Toggle checked={f.dpia_required} onChange={(v) => set("dpia_required", v)} label="DPIA required" />
        </Field>
        <Field label="DPIA status">
          <Select value={f.dpia_status} onChange={(v) => set("dpia_status", v)} options={DPIA} />
        </Field>
      </div>
    </>
  );

  const rightsTab = (
    <>
      <p className="muted" style={{ fontSize: 13, marginBottom: 4 }}>
        Document how each GDPR data-subject right is satisfied for this activity.
      </p>
      <Field label="Right to be informed" help="Art. 13/14 — how subjects are told about the processing.">
        <TextArea value={f.right_to_be_informed} onChange={(v) => set("right_to_be_informed", v)} rows={2} />
      </Field>
      <Field label="Right of access" help="Art. 15 — how subject access requests are handled.">
        <TextArea value={f.right_to_access} onChange={(v) => set("right_to_access", v)} rows={2} />
      </Field>
      <Field label="Right to rectification" help="Art. 16 — how corrections are made.">
        <TextArea value={f.right_to_rectification} onChange={(v) => set("right_to_rectification", v)} rows={2} />
      </Field>
      <Field label="Right to erasure" help="Art. 17 — how the right to be forgotten is honoured.">
        <TextArea value={f.right_to_erasure} onChange={(v) => set("right_to_erasure", v)} rows={2} />
      </Field>
      <Field label="Right to portability" help="Art. 20 — how data is exported in a portable format.">
        <TextArea value={f.right_to_portability} onChange={(v) => set("right_to_portability", v)} rows={2} />
      </Field>
      <Field label="Right to object" help="Art. 21 — how objections (incl. restriction) are handled.">
        <TextArea value={f.right_to_object} onChange={(v) => set("right_to_object", v)} rows={2} />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Related processes" help="Business processes this activity supports.">
        <MultiSelect value={f.process_ids} onChange={(v) => set("process_ids", v)} options={processOpts} />
      </Field>
      <Field label="Related policies" help="Policies governing this processing.">
        <MultiSelect value={f.policy_ids} onChange={(v) => set("policy_ids", v)} options={policyOpts} />
      </Field>
      <Field label="Related assets" help="Systems/assets that store or process this data.">
        <MultiSelect value={f.asset_ids} onChange={(v) => set("asset_ids", v)} options={assetOpts} />
      </Field>
      <Field label="Related risks" help="Privacy risks associated with this activity.">
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Data Privacy (RoPA)</h1>
          <p>GDPR Article 30 records of processing — lawful basis, data categories, retention, transfers, DPIA, and data-subject rights.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="processing-activities" label="Processing Activities" onDone={load} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add activity
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{items.length}</span></div><span className="l">Processing activities</span></div>
        <div className="card stat danger"><div className="stat-top"><span className="n">{gaps}</span><span className="ico"><IconAlert /></span></div><span className="l">Transfer gaps</span></div>
        <div className="card stat warn"><div className="stat-top"><span className="n">{dpias}</span></div><span className="l">DPIAs outstanding</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{specials}</span><span className="ico"><IconShield /></span></div><span className="l">Special-category</span></div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Records of processing</h3>
          <span className="sub">{items.length} total · click a row to edit</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Name</th>
                <th>Purpose</th>
                <th>Lawful basis</th>
                <th>Controller</th>
                <th>Transfer</th>
                <th>DPIA</th>
                <th>Links</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openEdit(r)}>
                  <td className="ref">{r.reference}</td>
                  <td className="cell-title">
                    {r.name}
                    {r.special_category && <span style={{ marginLeft: 6 }}><Badge tone="high">special</Badge></span>}
                  </td>
                  <td className="muted" style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.purpose || "—"}</td>
                  <td className="muted">{cap(r.lawful_basis)}</td>
                  <td className="muted">{r.controller || "—"}</td>
                  <td>{r.cross_border_transfer ? (r.has_transfer_gap ? <Badge tone="critical">gap</Badge> : <Badge tone="low">safeguarded</Badge>) : <span className="muted">none</span>}</td>
                  <td>{r.dpia_outstanding ? <Badge tone="high">{cap(r.dpia_status)}</Badge> : (r.dpia_required ? <Badge tone="low">done</Badge> : <span className="muted">n/a</span>)}</td>
                  <td className="muted">{linkCount(r) || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => setDetailId(detailId === r.id ? null : r.id)}>Details</button>
                      <button className="btn secondary sm" onClick={() => remove(r)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconPolicy width={24} height={24} /></span>
                      <h3>No records of processing</h3>
                      <p>Create your first RoPA to document a processing activity.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detailId && <RecordPanels model="processing_activity" entityId={detailId} />}

      {showForm && (
        <FormModal
          title={editing ? `Edit record — ${editing.reference}` : "Add item (Records of Processing)"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "data", label: "Lawfulness & Data", content: dataTab, required: true },
            { id: "transfers", label: "Transfers & Retention", content: transfersTab },
            { id: "rights", label: "Data Subject Rights", content: rightsTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create record"}
        />
      )}
    </>
  );
}
