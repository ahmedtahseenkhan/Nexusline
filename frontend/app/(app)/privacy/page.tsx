"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconAlert, IconPlus, IconShield } from "@/components/icons";

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

type BizUnit = { id: string; name: string };

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const refToOpt = (r: Ref): AsyncOption => ({ value: r.id, label: r.title || r.name || r.reference || r.id, sub: r.reference });

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
  process_ids: AsyncOption[];
  policy_ids: AsyncOption[];
  asset_ids: AsyncOption[];
  risk_ids: AsyncOption[];
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
    process_ids: r.processes.map(refToOpt),
    policy_ids: r.policies.map(refToOpt),
    asset_ids: r.assets.map(refToOpt),
    risk_ids: r.risks.map(refToOpt),
  };
}

/** Strip empty optional FKs/dates to null and map link options to id arrays. */
function toPayload(f: FormState): Record<string, unknown> {
  return {
    ...f,
    business_unit_id: f.business_unit_id || null,
    review_date: f.review_date || null,
    process_ids: f.process_ids.map((o) => o.value),
    policy_ids: f.policy_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
    risk_ids: f.risk_ids.map((o) => o.value),
  };
}

const linkCount = (r: Ropa) => r.processes.length + r.policies.length + r.assets.length + r.risks.length;

/* ================================================================ page ===== */
function PrivacyInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Ropa | null>(null);
  const [units, setUnits] = useState<BizUnit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [counts, setCounts] = useState({ total: 0, gaps: 0, dpias: 0, specials: 0 });

  const [editing, setEditing] = useState<Ropa | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchRopa = useCallback((qs: string) => apiCall<PagedList<Ropa>>("GET", `/processing-activities?${qs}`), []);

  const loadDetail = useCallback((id: string) => {
    apiCall<Ropa>("GET", `/processing-activities/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  // Server-side stat counts (real totals across the whole register, not just one page).
  useEffect(() => {
    const total = apiCall<PagedList<Ropa>>("GET", "/processing-activities?limit=1");
    const gaps = apiCall<PagedList<Ropa>>("GET", "/processing-activities?transfer_gap=true&limit=1");
    const dpias = apiCall<PagedList<Ropa>>("GET", "/processing-activities?dpia_outstanding=true&limit=1");
    const specials = apiCall<PagedList<Ropa>>("GET", "/processing-activities?special_category=true&limit=1");
    Promise.all([total, gaps, dpias, specials])
      .then(([t, g, d, s]) => setCounts({ total: t.total, gaps: g.total, dpias: d.total, specials: s.total }))
      .catch(() => {});
  }, [refreshKey]);

  useEffect(() => {
    apiCall<PagedList<BizUnit>>("GET", "/business-units").then((r) => setUnits(r.items)).catch(() => {});
  }, []);

  // server typeahead pickers
  const searchProcesses = (q: string) => apiCall<PagedList<{ id: string; name: string; description?: string }>>("GET", `/processes?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.description })));
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  async function openEdit(r: Ropa) {
    setEditing(r);
    setError(null);
    // Refetch one for the freshest link arrays.
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
      reload();
      if (openId) loadDetail(openId);
      toast(editing ? "Changes saved" : "Record created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save record");
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: Ropa) {
    if (!(await confirmDialog({ title: `Delete RoPA ${r.reference} — ${r.name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/processing-activities/${r.id}`);
      if (openId === r.id) setOpenId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete record");
    }
  }

  const unitOpts: Option[] = useMemo(() => units.map((u) => ({ value: u.id, label: u.name })), [units]);

  const columns: Column<Ropa>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference}</span> },
    { key: "name", header: "Name", sortable: true, render: (r) => <span className="cell-title">{r.name}{r.special_category && <span style={{ marginLeft: 6 }}><Badge tone="high">special</Badge></span>}</span> },
    { key: "purpose", header: "Purpose", render: (r) => <span className="muted" style={{ display: "inline-block", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", verticalAlign: "bottom" }}>{r.purpose || "—"}</span> },
    { key: "lawful_basis", header: "Lawful basis", sortable: true, render: (r) => <span className="muted">{cap(r.lawful_basis)}</span> },
    { key: "controller", header: "Controller", render: (r) => <span className="muted">{r.controller || "—"}</span> },
    { key: "transfer", header: "Transfer", render: (r) => (r.cross_border_transfer ? (r.has_transfer_gap ? <Badge tone="critical">gap</Badge> : <Badge tone="low">safeguarded</Badge>) : <span className="muted">none</span>) },
    { key: "dpia", header: "DPIA", render: (r) => (r.dpia_outstanding ? <Badge tone="high">{cap(r.dpia_status)}</Badge> : (r.dpia_required ? <Badge tone="low">done</Badge> : <span className="muted">n/a</span>)) },
    { key: "links", header: "Links", align: "center", render: (r) => <span className="muted">{linkCount(r) || "—"}</span> },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(r)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(r)}>Delete</button></div> },
  ];

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
        <AsyncMultiSelect search={searchProcesses} value={f.process_ids} onChange={(v) => set("process_ids", v)} />
      </Field>
      <Field label="Related policies" help="Policies governing this processing.">
        <AsyncMultiSelect search={searchPolicies} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} />
      </Field>
      <Field label="Related assets" help="Systems/assets that store or process this data.">
        <AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
      </Field>
      <Field label="Related risks" help="Privacy risks associated with this activity.">
        <AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} />
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
          <ImportExport resource="processing-activities" label="Processing Activities" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add activity
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{counts.total}</span></div><span className="l">Processing activities</span></div>
        <div className="card stat danger"><div className="stat-top"><span className="n">{counts.gaps}</span><span className="ico"><IconAlert /></span></div><span className="l">Transfer gaps</span></div>
        <div className="card stat warn"><div className="stat-top"><span className="n">{counts.dpias}</span></div><span className="l">DPIAs outstanding</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{counts.specials}</span><span className="ico"><IconShield /></span></div><span className="l">Special-category</span></div>
      </div>

      <DataTable<Ropa>
        columns={columns}
        fetcher={fetchRopa}
        rowKey={(r) => r.id}
        onRowClick={(r) => setOpenId(r.id)}
        activeKey={openId}
        searchPlaceholder="Search records by name or reference…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No records of processing yet. Create your first RoPA to document a processing activity."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.name}` : "…"}
        subtitle={detail ? `${cap(detail.lawful_basis)} · ${detail.controller || "no controller"}` : ""}
        width={720}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {detail.special_category && <Badge tone="high">special-category</Badge>}
              {detail.cross_border_transfer && (detail.has_transfer_gap ? <Badge tone="critical">transfer gap</Badge> : <Badge tone="low">transfer safeguarded</Badge>)}
              {detail.dpia_outstanding && <Badge tone="high">DPIA {cap(detail.dpia_status)}</Badge>}
              {linkCount(detail) > 0 && <Badge tone="neutral" plain>{linkCount(detail)} links</Badge>}
            </div>

            {detail.purpose && (
              <div style={{ marginBottom: 14 }}>
                <div className="muted" style={{ fontSize: 12, marginBottom: 2 }}>Purpose</div>
                <div style={{ fontSize: 13, lineHeight: 1.55 }}>{detail.purpose}</div>
              </div>
            )}

            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Retention</div><div style={{ marginTop: 4, fontSize: 13 }}>{detail.retention_period || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>DPO</div><div style={{ marginTop: 4, fontSize: 13 }}>{detail.dpo || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Next review</div><div style={{ marginTop: 4, fontSize: 13 }}>{detail.review_date || "—"}</div></div>
            </div>

            <RecordPanels model="processing_activity" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

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

export default function PrivacyPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <PrivacyInner />
    </Suspense>
  );
}
