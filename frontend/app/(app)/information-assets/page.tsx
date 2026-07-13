"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { type Page } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncSelect from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";
import RelatedChips, { type GraphRef } from "@/components/RelatedChips";

/* ------------------------------------------------------------------ types */
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";
type LinkRef = { id: string; label: string };
// Relation refs from GET /assets/{id} arrive as {id, label}; adapt to the
// {id, name} shape RelatedChips renders.
const asRefs = (items?: LinkRef[]): GraphRef[] | undefined =>
  items?.map((x) => ({ id: x.id, name: x.label }));
type DependencyRow = {
  id: string;
  relationship_type: string;
  notes: string;
  information_asset: LinkRef | null;
  it_asset: LinkRef | null;
};
type Asset = {
  id: string;
  name: string;
  description: string;
  asset_class: string;
  media_type: LinkRef | null;
  label: LinkRef | null;
  owner: LinkRef | null;
  guardian: LinkRef | null;
  user: LinkRef | null;
  confidentiality: string;
  integrity: string;
  availability: string;
  business_value: string;
  information_owner: string;
  data_categories: string;
  records_volume: string;
  self_assessed: boolean;
  assessed_by: string;
  assessed_date: string | null;
  effective_criticality: string;
  review_frequency: string;
  next_review_date: string | null;
  workflow_status: string;
  dependencies: DependencyRow[];
  created_at: string;
  // cross-module relations from GET /assets/{id} ({id,label} LinkRef shape)
  processes?: LinkRef[];
  legals?: LinkRef[];
  requirements?: LinkRef[];
  incidents?: LinkRef[];
  exceptions?: LinkRef[];
  risks?: LinkRef[];
  related_assets?: LinkRef[];
  // reverse graph links (read-only) — GraphRef {id,reference?,title?,name?}
  vendors?: GraphRef[];
  access_reviews?: GraphRef[];
  controls?: GraphRef[];
  threats?: GraphRef[];
  vulnerabilities?: GraphRef[];
};
type MediaType = { id: string; name: string; description: string; editable: boolean };
type LabelRow = { id: string; name: string; description: string; color: string };
type BusinessUnit = { id: string; name: string };
type Summary = { total: number; high_or_critical_value: number; self_assessed_pct: number; with_pii: number };

/* ----------------------------------------------------------------- helpers */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const CRIT = opts(["low", "medium", "high", "critical"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const RELATIONSHIP = opts(["hosts", "stores", "processes", "transmits", "backs_up"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

const CRIT_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "high", critical: "critical" };
const RANK: Record<string, number> = { low: 0, medium: 1, high: 2, critical: 3 };
const maxCia = (a: Asset) =>
  [a.confidentiality, a.integrity, a.availability].reduce((hi, v) => ((RANK[v] ?? -1) > (RANK[hi] ?? -1) ? v : hi), "low");
const hasPii = (a: Asset) => (a.data_categories || "").toLowerCase().includes("pii");

function CritBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={CRIT_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

/* ------------------------------------------------------------------ form */
type FormState = {
  name: string; description: string; media_type_id: string; information_owner: string;
  business_value: string; confidentiality: string; integrity: string; availability: string;
  label_id: string; data_categories: string; records_volume: string; self_assessed: boolean;
  assessed_by: string; assessed_date: string; owner_id: string; guardian_id: string; user_id: string;
  review_frequency: string; workflow_status: string;
};
const BLANK: FormState = {
  name: "", description: "", media_type_id: "", information_owner: "", business_value: "medium",
  confidentiality: "medium", integrity: "medium", availability: "medium", label_id: "",
  data_categories: "", records_volume: "", self_assessed: false, assessed_by: "", assessed_date: "",
  owner_id: "", guardian_id: "", user_id: "", review_frequency: "annual", workflow_status: "draft",
};
function fromAsset(a: Asset): FormState {
  return {
    name: a.name, description: a.description || "", media_type_id: a.media_type?.id || "",
    information_owner: a.information_owner || "", business_value: a.business_value || "medium",
    confidentiality: a.confidentiality || "medium", integrity: a.integrity || "medium",
    availability: a.availability || "medium", label_id: a.label?.id || "",
    data_categories: a.data_categories || "", records_volume: a.records_volume || "",
    self_assessed: !!a.self_assessed, assessed_by: a.assessed_by || "", assessed_date: a.assessed_date || "",
    owner_id: a.owner?.id || "", guardian_id: a.guardian?.id || "", user_id: a.user?.id || "",
    review_frequency: a.review_frequency || "annual", workflow_status: a.workflow_status || "draft",
  };
}
function toPayload(f: FormState): Record<string, unknown> {
  return {
    asset_class: "information_asset", name: f.name, description: f.description,
    media_type_id: f.media_type_id || null, information_owner: f.information_owner,
    business_value: f.business_value, confidentiality: f.confidentiality, integrity: f.integrity,
    availability: f.availability, label_id: f.label_id || null, data_categories: f.data_categories,
    records_volume: f.records_volume, self_assessed: f.self_assessed, assessed_by: f.assessed_by,
    assessed_date: f.assessed_date || null, owner_id: f.owner_id || null, guardian_id: f.guardian_id || null,
    user_id: f.user_id || null, review_frequency: f.review_frequency, workflow_status: f.workflow_status,
  };
}

function InformationAssetsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);

  // small lookup tables (bounded) for the form Selects
  const [mediaTypes, setMediaTypes] = useState<MediaType[]>([]);
  const [labels, setLabels] = useState<LabelRow[]>([]);
  const [units, setUnits] = useState<BusinessUnit[]>([]);

  // form
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // hosted-on dependency add-form
  const [depAssetId, setDepAssetId] = useState<string | null>(null);
  const [depAssetLabel, setDepAssetLabel] = useState("");
  const [depRel, setDepRel] = useState("hosts");
  const [depNotes, setDepNotes] = useState("");

  const loadSummary = useCallback(() => {
    apiCall<Summary>("GET", "/assets/summary?asset_class=information_asset").then(setSummary).catch(() => {});
  }, []);

  useEffect(() => {
    const ignore = () => {};
    apiCall<MediaType[]>("GET", "/asset-media-types").then(setMediaTypes).catch(ignore);
    apiCall<LabelRow[]>("GET", "/asset-labels").then(setLabels).catch(ignore);
    apiCall<Page<BusinessUnit>>("GET", "/business-units").then((r) => setUnits(r.items)).catch(ignore);
    loadSummary();
  }, [loadSummary]);

  // load the open record's full detail whenever the URL id changes
  const loadDetail = useCallback((id: string) => {
    apiCall<Asset>("GET", `/assets/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  const fetchAssets = useCallback(
    (qs: string) => apiCall<Page<Asset>>("GET", `/assets?asset_class=information_asset&${qs}`),
    [],
  );
  const searchItAssets = useCallback(
    (q: string) =>
      apiCall<Page<Asset>>("GET", `/assets?asset_class=it_asset&search=${encodeURIComponent(q)}&limit=20`).then((r) =>
        r.items.map((a) => ({ value: a.id, label: a.name, sub: cap(a.effective_criticality || "") })),
      ),
    [],
  );

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(a: Asset) { setEditing(a); setF(fromAsset(a)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Asset>("PATCH", `/assets/${editing.id}`, payload);
      else await apiCall<Asset>("POST", "/assets", payload);
      setShowForm(false);
      setRefreshKey((k) => k + 1);
      loadSummary();
      if (openId) loadDetail(openId);
      toast(editing ? "Changes saved" : "Created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save information asset");
    } finally {
      setSaving(false);
    }
  }

  async function remove(a: Asset) {
    if (!(await confirmDialog({ title: `Archive information asset "${a.name}"?`, message: "It will be removed from the inventory.", confirmLabel: "Archive", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/assets/${a.id}`);
      setShowForm(false);
      if (openId === a.id) setOpenId(null);
      setRefreshKey((k) => k + 1);
      loadSummary();
      toast("Archived");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete information asset");
    }
  }

  async function addDependency() {
    if (!detail || !depAssetId) return;
    setError(null);
    try {
      await apiCall("POST", "/assets/dependencies", {
        information_asset_id: detail.id, it_asset_id: depAssetId, relationship_type: depRel, notes: depNotes,
      });
      setDepAssetId(null); setDepAssetLabel(""); setDepNotes("");
      loadDetail(detail.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to link IT asset");
    }
  }
  async function removeDependency(depId: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Unlink this IT asset?", danger: true, confirmLabel: "Unlink" }))) return;
    try {
      await apiCall<void>("DELETE", `/assets/dependencies/${depId}`);
      loadDetail(detail.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to unlink IT asset");
    }
  }

  const mediaTypeOpts: Option[] = useMemo(() => mediaTypes.map((m) => ({ value: m.id, label: m.name })), [mediaTypes]);
  const labelOpts: Option[] = useMemo(() => labels.map((l) => ({ value: l.id, label: l.name })), [labels]);
  const unitOpts: Option[] = useMemo(() => units.map((u) => ({ value: u.id, label: u.name })), [units]);

  const columns: Column<Asset>[] = [
    { key: "name", header: "Name", sortable: true, render: (a) => <span className="cell-title">{a.name}</span> },
    { key: "information_owner", header: "Information owner", render: (a) => <span className="muted">{a.information_owner || "—"}</span> },
    { key: "business_value", header: "Business value", sortable: true, render: (a) => <CritBadge value={a.effective_criticality} /> },
    { key: "classification", header: "Classification", render: (a) => <CritBadge value={maxCia(a)} /> },
    { key: "self_assessed", header: "Self-assessed", sortable: true, render: (a) => (a.self_assessed ? <Badge tone="low">Self-assessed</Badge> : <Badge tone="neutral">Pending</Badge>) },
    { key: "hosted", header: "Hosted on", align: "center", render: (a) => <span className="muted">{a.dependencies?.length || "—"}</span> },
  ];

  /* --------------------------------------------------------------- form tabs (unchanged) */
  const identityTab = (
    <>
      <Field label="Name" required help="For example: Customer master data, SWIFT payment messages, Loan origination records.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Customer master data" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this data / application is and why it matters to the business." />
      </Field>
      <div className="field-row">
        <Field label="Media type" help="The information asset taxonomy (Data asset, Application…).">
          <Select value={f.media_type_id} onChange={(v) => set("media_type_id", v)} options={mediaTypeOpts} placeholder="— none —" />
        </Field>
        <Field label="Business owner (identifies value)" help="The business owner accountable for this data and its value.">
          <TextInput value={f.information_owner} onChange={(v) => set("information_owner", v)} placeholder="Head of Retail Banking" />
        </Field>
      </div>
    </>
  );
  const valueTab = (
    <>
      <Field label="Business value" help="Set by the business owner — the data's value to the business.">
        <Select value={f.business_value} onChange={(v) => set("business_value", v)} options={CRIT} />
      </Field>
      <div className="field-row">
        <Field label="Confidentiality"><Select value={f.confidentiality} onChange={(v) => set("confidentiality", v)} options={CRIT} /></Field>
        <Field label="Integrity"><Select value={f.integrity} onChange={(v) => set("integrity", v)} options={CRIT} /></Field>
        <Field label="Availability"><Select value={f.availability} onChange={(v) => set("availability", v)} options={CRIT} /></Field>
      </div>
      <div className="field-row">
        <Field label="Handling label" help="Reusable handling / sensitivity label (Public, Confidential, PII…).">
          <Select value={f.label_id} onChange={(v) => set("label_id", v)} options={labelOpts} placeholder="— none —" />
        </Field>
        <Field label="Records volume" help="Approximate number of records held.">
          <TextInput value={f.records_volume} onChange={(v) => set("records_volume", v)} placeholder="~4.2M customers" />
        </Field>
      </div>
      <Field label="Data categories" help='Comma-separated. Include "PII" where personal data is held.'>
        <TextArea value={f.data_categories} onChange={(v) => set("data_categories", v)} rows={2} placeholder="PII, account numbers, transaction history, CNIC" />
      </Field>
    </>
  );
  const selfAssessTab = (
    <>
      <Field label="Self-assessed" help="The business owner has completed the self-assessment for this asset.">
        <Toggle checked={f.self_assessed} onChange={(v) => set("self_assessed", v)} label="Self-assessment completed" />
      </Field>
      <div className="field-row">
        <Field label="Assessed by" help="Who signed off the self-assessment."><TextInput value={f.assessed_by} onChange={(v) => set("assessed_by", v)} placeholder="Business owner name" /></Field>
        <Field label="Assessed date"><TextInput type="date" value={f.assessed_date} onChange={(v) => set("assessed_date", v)} /></Field>
      </div>
      <div className="help">Upload the signed self-assessment form via the attachments panel on the record detail — it is kept in the central repository.</div>
    </>
  );
  const governanceTab = (
    <>
      <div className="field-row">
        <Field label="Owner" help="Business unit accountable for this asset (RACI owner)."><Select value={f.owner_id} onChange={(v) => set("owner_id", v)} options={unitOpts} placeholder="— none —" /></Field>
        <Field label="Guardian" help="Business unit that safeguards / maintains the asset."><Select value={f.guardian_id} onChange={(v) => set("guardian_id", v)} options={unitOpts} placeholder="— none —" /></Field>
        <Field label="User" help="Business unit that uses the asset day to day."><Select value={f.user_id} onChange={(v) => set("user_id", v)} options={unitOpts} placeholder="— none —" /></Field>
      </div>
      <div className="field-row">
        <Field label="Review frequency" help="How often this asset's value / classification is re-attested."><Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} /></Field>
        <Field label="Workflow status" help="Approval lifecycle for this asset record."><Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} /></Field>
      </div>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Information Asset Management</h1>
          <p>Primary assets — data and applications. Criticality is business value, set by the business owner, with CIA classification, handling labels and owner self-assessment.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add information asset</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.total ?? 0).toLocaleString()}</span></div><span className="l">Information assets</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.high_or_critical_value ?? 0).toLocaleString()}</span></div><span className="l">High / critical value</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{summary?.self_assessed_pct ?? 0}%</span></div><span className="l">Self-assessed</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.with_pii ?? 0).toLocaleString()}</span></div><span className="l">Assets with PII</span></div>
      </div>

      <DataTable<Asset>
        columns={columns}
        fetcher={fetchAssets}
        rowKey={(a) => a.id}
        onRowClick={(a) => setOpenId(a.id)}
        activeKey={openId}
        searchPlaceholder="Search assets by name or owner…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No information assets yet. Register the data and applications that carry business value."
        refreshKey={refreshKey}
      />

      {/* Deep-linkable detail drawer (?id=) */}
      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail?.name || "…"}
        subtitle={detail ? (detail.information_owner ? `Owner ${detail.information_owner}` : "No business owner") + (detail.records_volume ? ` · ${detail.records_volume}` : "") : ""}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-end", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Business value</div><div style={{ marginTop: 4 }}><CritBadge value={detail.business_value} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Confidentiality</div><div style={{ marginTop: 4 }}><CritBadge value={detail.confidentiality} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Integrity</div><div style={{ marginTop: 4 }}><CritBadge value={detail.integrity} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Availability</div><div style={{ marginTop: 4 }}><CritBadge value={detail.availability} /></div></div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}><div className="muted" style={{ fontSize: 12 }}>Effective criticality</div><div style={{ marginTop: 4 }}><CritBadge value={detail.effective_criticality} /></div></div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <span className="muted" style={{ fontSize: 13 }}>Data categories: </span>
              <span>{detail.data_categories || "—"}</span>
              {hasPii(detail) && <span style={{ marginLeft: 8 }}><Badge tone="high">Contains PII</Badge></span>}
            </div>

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                <strong>Self-assessment</strong>
                {detail.self_assessed ? <Badge tone="low">Completed</Badge> : <Badge tone="neutral">Pending</Badge>}
                {detail.assessed_by && <span className="muted" style={{ fontSize: 13 }}>by {detail.assessed_by}</span>}
                {detail.assessed_date && <span className="muted" style={{ fontSize: 13 }}>on {detail.assessed_date}</span>}
              </div>
            </div>

            <strong>Hosted on (IT assets)</strong>
            <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>The supporting IT assets that carry this data. Linking here lets those assets inherit this data&apos;s business value.</p>
            <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(ev) => { ev.preventDefault(); addDependency(); }}>
              <div style={{ flex: "1 1 220px" }}>
                <label className="label">IT asset</label>
                <AsyncSelect search={searchItAssets} value={depAssetId} selectedLabel={depAssetLabel} placeholder="Search IT assets…" onChange={(v, o) => { setDepAssetId(v); setDepAssetLabel(o?.label || ""); }} />
              </div>
              <div style={{ width: 150 }}>
                <label className="label">Relationship</label>
                <select className="select" value={depRel} onChange={(e) => setDepRel(e.target.value)}>
                  {RELATIONSHIP.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                </select>
              </div>
              <div style={{ flex: "1 1 160px" }}>
                <label className="label">Notes</label>
                <input className="input" value={depNotes} onChange={(e) => setDepNotes(e.target.value)} placeholder="Optional context" />
              </div>
              <button className="btn" disabled={!depAssetId}>Link</button>
            </form>

            <div className="table-wrap">
              <table>
                <thead><tr><th>IT asset</th><th>Relationship</th><th>Notes</th><th></th></tr></thead>
                <tbody>
                  {detail.dependencies.map((d) => (
                    <tr key={d.id}>
                      <td className="cell-title">{d.it_asset?.label || "—"}</td>
                      <td><Badge tone="info" plain>{cap(d.relationship_type)}</Badge></td>
                      <td className="muted">{d.notes || "—"}</td>
                      <td><button className="btn secondary sm" onClick={() => removeDependency(d.id)}>Unlink</button></td>
                    </tr>
                  ))}
                  {detail.dependencies.length === 0 && (
                    <tr><td colSpan={4}><span className="muted">Not linked to any IT asset yet.</span></td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div style={{ marginTop: 20 }}>
              <strong style={{ fontSize: 13 }}>Related records</strong>
              <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 8 }}>
                <RelatedChips label="Risks" items={asRefs(detail.risks)} href="/risks" />
                <RelatedChips label="Processes" items={asRefs(detail.processes)} href="/processes" />
                <RelatedChips label="Legal registers" items={asRefs(detail.legals)} href="/legal" />
                <RelatedChips label="Compliance requirements" items={asRefs(detail.requirements)} href="/compliance" />
                <RelatedChips label="Incidents" items={asRefs(detail.incidents)} href="/incidents" />
                <RelatedChips label="Exceptions" items={asRefs(detail.exceptions)} href="/exceptions" />
                <RelatedChips label="Related assets" items={asRefs(detail.related_assets)} href="/information-assets" />
                <RelatedChips label="Controls" items={detail.controls} href="/controls" />
                <RelatedChips label="Threats" items={detail.threats} href="/threat-library" />
                <RelatedChips label="Vulnerabilities" items={detail.vulnerabilities} href="/threat-library" />
                <RelatedChips label="Third parties" items={detail.vendors} href="/vendors" />
                <RelatedChips label="Access reviews" items={detail.access_reviews} href="/access-reviews" />
              </div>
            </div>

            <div style={{ marginTop: 20 }}>
              <RecordPanels model="asset" entityId={detail.id} />
            </div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit information asset — ${editing.name}` : "Add information asset"}
          wide
          tabs={[
            { id: "identity", label: "Identity", content: identityTab, required: true },
            { id: "value", label: "Business Value & Classification", content: valueTab },
            { id: "self", label: "Self-assessment", content: selfAssessTab },
            { id: "governance", label: "Governance", content: governanceTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create information asset"}
          footerLeft={editing ? (
            <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--red)" }}>Delete</button>
          ) : undefined}
        />
      )}
    </>
  );
}

export default function InformationAssetsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <InformationAssetsInner />
    </Suspense>
  );
}
