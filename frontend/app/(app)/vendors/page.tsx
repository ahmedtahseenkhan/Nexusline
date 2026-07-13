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
import RelatedChips from "@/components/RelatedChips";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, Toggle, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconPlus } from "@/components/icons";

/* ---------------------------------------------------------------- inline types */
type RefItem = { id: string; reference?: string; title?: string; name?: string };
type VendorType = { id: string; name: string; description: string };
type ServiceContract = { id: string; name: string; description: string; value: number | null; start_date: string | null; end_date: string | null; is_expired: boolean; created_at: string };
type Vendor = {
  id: string; name: string; description: string; category: string; type_id: string | null;
  contact_name: string; contact_email: string; contact_phone: string; website: string; location: string;
  criticality: string; status: string; workflow_status: string; risk_rating: string | null; shares_data: boolean;
  assessment_status: string; last_assessed_at: string | null; onboarded_at: string | null; offboarded_at: string | null;
  review_frequency: string; next_review_date: string | null; type: VendorType | null; contracts: ServiceContract[];
  risks: RefItem[]; assets: RefItem[]; requirements: RefItem[]; controls: RefItem[]; contract_count: number; active_contract_value: number; created_at: string;
  // reverse graph links (read-only, from GET /vendors/{id})
  incidents?: RefItem[]; assessments?: RefItem[]; outsourcing_arrangements?: RefItem[];
};

/* ------------------------------------------------------------------ enum options */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const CRITICALITY = opts(["low", "medium", "high", "critical"]);
const STATUS = opts(["prospective", "active", "suspended", "offboarded"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const RISK_RATING = opts(["low", "medium", "high", "critical"]);
const ASSESS = opts(["not_started", "in_progress", "completed"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = { active: "low", prospective: "info", suspended: "medium", offboarded: "neutral" };
const ASSESS_TONE: Record<string, "low" | "medium" | "neutral"> = { completed: "low", in_progress: "medium", not_started: "neutral" };
const money = (n: number) => n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const refToOpt = (x: RefItem): AsyncOption => ({ value: x.id, label: x.title || x.name || x.reference || x.id });

/* -------------------------------------------------------------------- form state */
type FormState = {
  name: string; description: string; category: string; type_id: string; contact_name: string; contact_email: string;
  contact_phone: string; website: string; location: string; criticality: string; status: string; workflow_status: string;
  shares_data: boolean; risk_rating: string; assessment_status: string; last_assessed_at: string; onboarded_at: string;
  offboarded_at: string; review_frequency: string; next_review_date: string; risk_ids: AsyncOption[]; asset_ids: AsyncOption[];
  requirement_ids: AsyncOption[]; control_ids: AsyncOption[];
};
const BLANK: FormState = {
  name: "", description: "", category: "", type_id: "", contact_name: "", contact_email: "", contact_phone: "", website: "",
  location: "", criticality: "medium", status: "active", workflow_status: "draft", shares_data: false, risk_rating: "",
  assessment_status: "not_started", last_assessed_at: "", onboarded_at: "", offboarded_at: "", review_frequency: "annual",
  next_review_date: "", risk_ids: [], asset_ids: [], requirement_ids: [], control_ids: [],
};
function fromVendor(v: Vendor): FormState {
  return {
    name: v.name, description: v.description || "", category: v.category || "", type_id: v.type_id || "",
    contact_name: v.contact_name || "", contact_email: v.contact_email || "", contact_phone: v.contact_phone || "",
    website: v.website || "", location: v.location || "", criticality: v.criticality, status: v.status,
    workflow_status: v.workflow_status, shares_data: v.shares_data, risk_rating: v.risk_rating || "",
    assessment_status: v.assessment_status, last_assessed_at: v.last_assessed_at || "", onboarded_at: v.onboarded_at || "",
    offboarded_at: v.offboarded_at || "", review_frequency: v.review_frequency, next_review_date: v.next_review_date || "",
    risk_ids: v.risks.map(refToOpt), asset_ids: v.assets.map(refToOpt),
    requirement_ids: (v.requirements ?? []).map(refToOpt), control_ids: (v.controls ?? []).map(refToOpt),
  };
}
function toPayload(f: FormState): Record<string, unknown> {
  return {
    name: f.name, description: f.description, category: f.category, type_id: f.type_id || null, contact_name: f.contact_name,
    contact_email: f.contact_email, contact_phone: f.contact_phone, website: f.website, location: f.location,
    criticality: f.criticality, status: f.status, workflow_status: f.workflow_status, shares_data: f.shares_data,
    risk_rating: f.risk_rating || null, assessment_status: f.assessment_status, last_assessed_at: f.last_assessed_at || null,
    onboarded_at: f.onboarded_at || null, offboarded_at: f.offboarded_at || null, review_frequency: f.review_frequency,
    next_review_date: f.next_review_date || null, risk_ids: f.risk_ids.map((o) => o.value), asset_ids: f.asset_ids.map((o) => o.value),
    requirement_ids: f.requirement_ids.map((o) => o.value), control_ids: f.control_ids.map((o) => o.value),
  };
}
type ContractForm = { name: string; description: string; value: number | ""; start_date: string; end_date: string };
const BLANK_CONTRACT: ContractForm = { name: "", description: "", value: "", start_date: "", end_date: "" };

/* ================================================================ page ===== */
function VendorsInner() {
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
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));
  const setC = <K extends keyof ContractForm>(k: K, v: ContractForm[K]) => setContract((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchVendors = useCallback((qs: string) => apiCall<PagedList<Vendor>>("GET", `/vendors?${qs}`), []);
  const loadDetail = useCallback((id: string) => { apiCall<Vendor>("GET", `/vendors/${id}`).then(setDetail).catch(() => setDetail(null)); }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);
  useEffect(() => { apiCall<VendorType[]>("GET", "/vendor-types").then(setTypes).catch(() => {}); }, []);

  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((c) => ({ value: c.id, label: c.name, sub: c.reference })));

  function openNew() { setEditing(null); setF(BLANK); setContract(BLANK_CONTRACT); setError(null); setShowForm(true); }
  function openEdit(v: Vendor) { setEditing(v); setF(fromVendor(v)); setContract(BLANK_CONTRACT); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Vendor>("PATCH", `/vendors/${editing.id}`, payload);
      else await apiCall<Vendor>("POST", "/vendors", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Vendor created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save vendor"); }
    finally { setSaving(false); }
  }
  async function remove(v: Vendor) {
    if (!(await confirmDialog({ title: `Delete vendor "${v.name}"?`, message: "This cannot be undone.", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/vendors/${v.id}`);
      if (openId === v.id) setOpenId(null);
      reload(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete vendor"); }
  }
  async function addContract() {
    if (!editing || !contract.name.trim()) return; setContractBusy(true); setError(null);
    try {
      const updated = await apiCall<Vendor>("POST", `/vendors/${editing.id}/contracts`, { name: contract.name, description: contract.description, value: contract.value === "" ? null : contract.value, start_date: contract.start_date || null, end_date: contract.end_date || null });
      setEditing(updated); setContract(BLANK_CONTRACT); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to add contract"); }
    finally { setContractBusy(false); }
  }
  async function removeContract(contractId: string) {
    if (!editing) return; setContractBusy(true); setError(null);
    try {
      await apiCall<void>("DELETE", `/vendors/contracts/${contractId}`);
      setEditing(await apiCall<Vendor>("GET", `/vendors/${editing.id}`)); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete contract"); }
    finally { setContractBusy(false); }
  }

  const typeOpts: Option[] = useMemo(() => types.map((t) => ({ value: t.id, label: t.name })), [types]);
  const linkCount = (v: Vendor) => v.risks.length + v.assets.length;

  const columns: Column<Vendor>[] = [
    { key: "name", header: "Name", sortable: true, render: (v) => <span className="cell-title">{v.name}{v.shares_data && <> <Badge tone="info" plain>data</Badge></>}</span> },
    { key: "category", header: "Type / Category", sortable: true, render: (v) => <span className="muted">{v.type?.name || v.category || "—"}</span> },
    { key: "criticality", header: "Criticality", sortable: true, render: (v) => <Severity value={v.criticality} /> },
    { key: "status", header: "Status", sortable: true, render: (v) => <Badge tone={STATUS_TONE[v.status] || "neutral"}>{cap(v.status)}</Badge> },
    { key: "risk_rating", header: "Risk rating", sortable: true, render: (v) => <Severity value={v.risk_rating} /> },
    { key: "assessment_status", header: "Assessment", sortable: true, render: (v) => <Badge tone={ASSESS_TONE[v.assessment_status] || "neutral"}>{cap(v.assessment_status)}</Badge> },
    { key: "contracts", header: "Contracts", render: (v) => <span className="muted">{v.contract_count > 0 ? `${v.contract_count} · ${money(v.active_contract_value)}` : "—"}</span> },
    { key: "links", header: "Links", align: "center", render: (v) => <span className="muted">{linkCount(v) || "—"}</span> },
    { key: "actions", header: "", render: (v) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(v)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(v)}>Delete</button></div> },
  ];

  /* -------------------------------- form tabs (unchanged) -------------------------------- */
  const generalTab = (
    <>
      <Field label="Name" required help="The third party / supplier name, e.g. Stripe, AWS, Acme Consulting."><TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Stripe" required /></Field>
      <Field label="Description"><TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this vendor provides and how it is used." /></Field>
      <div className="field-row">
        <Field label="Category"><TextInput value={f.category} onChange={(v) => set("category", v)} placeholder="Payments" /></Field>
        <Field label="Type" help="Third-party taxonomy (managed under vendor types)."><Select value={f.type_id} onChange={(v) => set("type_id", v)} options={typeOpts} placeholder="Choose a type…" /></Field>
      </div>
      <div className="field-row">
        <Field label="Contact Name"><TextInput value={f.contact_name} onChange={(v) => set("contact_name", v)} placeholder="Account manager" /></Field>
        <Field label="Contact Email"><TextInput value={f.contact_email} onChange={(v) => set("contact_email", v)} type="email" placeholder="support@vendor.com" /></Field>
      </div>
      <div className="field-row">
        <Field label="Contact Phone"><TextInput value={f.contact_phone} onChange={(v) => set("contact_phone", v)} placeholder="+1 555 0100" /></Field>
        <Field label="Website"><TextInput value={f.website} onChange={(v) => set("website", v)} placeholder="https://vendor.com" /></Field>
        <Field label="Location"><TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="Dublin, IE" /></Field>
      </div>
      <div className="field-row">
        <Field label="Criticality" help="How critical this vendor is to your operations."><Select value={f.criticality} onChange={(v) => set("criticality", v)} options={CRITICALITY} /></Field>
        <Field label="Status"><Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} /></Field>
      </div>
      <Field label="Shares / processes data" help="Toggle on if this vendor stores, processes or has access to your data."><Toggle checked={f.shares_data} onChange={(v) => set("shares_data", v)} label="Vendor handles our data" /></Field>
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
        <Field label="Workflow"><Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} /></Field>
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
                    <td className="muted">{c.value != null ? money(c.value) : "—"}</td>
                    <td className="muted">{c.start_date || "—"}</td>
                    <td className="muted">{c.end_date || "—"}</td>
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
              <Field label="Value (USD)"><NumberInput value={contract.value} onChange={(v) => setC("value", v)} min={0} placeholder="50000" /></Field>
              <Field label="Start Date"><TextInput value={contract.start_date} onChange={(v) => setC("start_date", v)} type="date" /></Field>
              <Field label="End Date"><TextInput value={contract.end_date} onChange={(v) => setC("end_date", v)} type="date" /></Field>
            </div>
            <button className="btn" type="button" disabled={contractBusy || !contract.name.trim()} onClick={addContract}><IconPlus width={16} height={16} /> Add contract</button>
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

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Third-Party Risk</h1>
          <p>Vendor registry with criticality, risk rating, assessment status, contracts and linked risks/assets.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="vendors" label="Vendors" onDone={reload} />
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add vendor</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Vendor>
        columns={columns}
        fetcher={fetchVendors}
        rowKey={(v) => v.id}
        onRowClick={(v) => setOpenId(v.id)}
        activeKey={openId}
        searchPlaceholder="Search vendors by name or category…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No vendors yet. Add the third parties your organization relies on."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail?.name || "…"}
        subtitle={detail ? `${detail.type?.name || detail.category || "Vendor"}${detail.location ? " · " + detail.location : ""}` : ""}
        actions={detail && (<><button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button><button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button></>)}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Criticality</div><div style={{ marginTop: 4 }}><Severity value={detail.criticality} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Status</div><div style={{ marginTop: 4 }}><Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Risk rating</div><div style={{ marginTop: 4 }}><Severity value={detail.risk_rating} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Assessment</div><div style={{ marginTop: 4 }}><Badge tone={ASSESS_TONE[detail.assessment_status] || "neutral"}>{cap(detail.assessment_status)}</Badge></div></div>
              {detail.contract_count > 0 && <div style={{ marginLeft: "auto", textAlign: "right" }}><div className="muted" style={{ fontSize: 12 }}>Contracts</div><div style={{ marginTop: 4 }}><strong>{detail.contract_count}</strong> · {money(detail.active_contract_value)}</div></div>}
            </div>
            {detail.shares_data && <div style={{ marginBottom: 14 }}><Badge tone="info">Handles our data</Badge></div>}

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

            <RecordPanels model="vendor" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

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

export default function VendorsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <VendorsInner />
    </Suspense>
  );
}
