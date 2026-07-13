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
import { Field, TextInput, TextArea, Select, MultiSelect, type Option } from "@/components/fields";
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
type TagRow = { id: string; name: string; category: string; description?: string; color?: string };
type DependencyRow = { id: string; relationship_type: string; notes: string; information_asset: LinkRef | null; it_asset: LinkRef | null };
type Asset = {
  id: string; name: string; description: string; asset_class: string; media_type: LinkRef | null;
  availability: string; replacement_cost: number; currency: string; rto_hours: number | null; rpo_hours: number | null;
  environment: string; location: string; hostname: string; ip_address: string; serial_number: string;
  manufacturer: string; model_number: string; os_version: string; discovery_source: string; external_id: string;
  cost_band: string; intrinsic_criticality: string; derived_criticality: string; effective_criticality: string;
  workflow_status: string; tags: TagRow[]; dependencies: DependencyRow[]; created_at: string;
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
type Summary = { total: number; production: number; total_replacement_value: number; effective_critical: number };

/* ----------------------------------------------------------------- helpers */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const money = (n: number | null | undefined, cur = "PKR") => `${cur} ${Number(n || 0).toLocaleString()}`;

const CRIT = opts(["low", "medium", "high", "critical"]);
const ENVIRONMENT = opts(["production", "dr", "uat", "staging", "development", "not_applicable"]);
const DISCOVERY = opts(["manual", "active_directory", "intune_mdm", "cmdb", "network_scan", "cloud_connector", "edr", "import_csv"]);
const RELATIONSHIP = opts(["hosts", "stores", "processes", "transmits", "backs_up"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const CRIT_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "high", critical: "critical" };

function CritBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={CRIT_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

/* ------------------------------------------------------------------ form */
type FormState = {
  name: string; description: string; media_type_id: string; replacement_cost: string; currency: string;
  availability: string; rto_hours: string; rpo_hours: string; environment: string; location: string;
  hostname: string; ip_address: string; serial_number: string; manufacturer: string; model_number: string;
  os_version: string; tag_ids: string[]; discovery_source: string; external_id: string; workflow_status: string;
};
const BLANK: FormState = {
  name: "", description: "", media_type_id: "", replacement_cost: "", currency: "PKR", availability: "medium",
  rto_hours: "", rpo_hours: "", environment: "production", location: "", hostname: "", ip_address: "",
  serial_number: "", manufacturer: "", model_number: "", os_version: "", tag_ids: [], discovery_source: "manual",
  external_id: "", workflow_status: "draft",
};
function fromAsset(a: Asset): FormState {
  return {
    name: a.name, description: a.description || "", media_type_id: a.media_type?.id || "",
    replacement_cost: a.replacement_cost != null ? String(a.replacement_cost) : "", currency: a.currency || "PKR",
    availability: a.availability || "medium", rto_hours: a.rto_hours != null ? String(a.rto_hours) : "",
    rpo_hours: a.rpo_hours != null ? String(a.rpo_hours) : "", environment: a.environment || "production",
    location: a.location || "", hostname: a.hostname || "", ip_address: a.ip_address || "",
    serial_number: a.serial_number || "", manufacturer: a.manufacturer || "", model_number: a.model_number || "",
    os_version: a.os_version || "", tag_ids: a.tags.map((t) => t.id), discovery_source: a.discovery_source || "manual",
    external_id: a.external_id || "", workflow_status: a.workflow_status || "draft",
  };
}
function toPayload(f: FormState): Record<string, unknown> {
  return {
    asset_class: "it_asset", name: f.name, description: f.description, media_type_id: f.media_type_id || null,
    replacement_cost: f.replacement_cost === "" ? 0 : Number(f.replacement_cost), currency: f.currency || "PKR",
    availability: f.availability, rto_hours: f.rto_hours === "" ? null : Number(f.rto_hours),
    rpo_hours: f.rpo_hours === "" ? null : Number(f.rpo_hours), environment: f.environment, location: f.location,
    hostname: f.hostname, ip_address: f.ip_address, serial_number: f.serial_number, manufacturer: f.manufacturer,
    model_number: f.model_number, os_version: f.os_version, tag_ids: f.tag_ids, discovery_source: f.discovery_source,
    external_id: f.external_id, workflow_status: f.workflow_status,
  };
}

function ITAssetsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);

  const [mediaTypes, setMediaTypes] = useState<MediaType[]>([]);
  const [tags, setTags] = useState<TagRow[]>([]);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const [newTag, setNewTag] = useState("");
  const [creatingTag, setCreatingTag] = useState(false);

  const [depAssetId, setDepAssetId] = useState<string | null>(null);
  const [depAssetLabel, setDepAssetLabel] = useState("");
  const [depRel, setDepRel] = useState("hosts");
  const [depNotes, setDepNotes] = useState("");

  const loadSummary = useCallback(() => {
    apiCall<Summary>("GET", "/assets/summary?asset_class=it_asset").then(setSummary).catch(() => {});
  }, []);
  useEffect(() => {
    const ignore = () => {};
    apiCall<MediaType[]>("GET", "/asset-media-types").then(setMediaTypes).catch(ignore);
    apiCall<TagRow[]>("GET", "/asset-tags").then(setTags).catch(ignore);
    loadSummary();
  }, [loadSummary]);

  const loadDetail = useCallback((id: string) => {
    apiCall<Asset>("GET", `/assets/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  const fetchAssets = useCallback((qs: string) => apiCall<Page<Asset>>("GET", `/assets?asset_class=it_asset&${qs}`), []);
  const searchInfoAssets = useCallback(
    (q: string) =>
      apiCall<Page<Asset>>("GET", `/assets?asset_class=information_asset&search=${encodeURIComponent(q)}&limit=20`).then((r) =>
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
      setShowForm(false); setRefreshKey((k) => k + 1); loadSummary();
      if (openId) loadDetail(openId);
      toast(editing ? "Changes saved" : "Created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save IT asset");
    } finally { setSaving(false); }
  }
  async function remove(a: Asset) {
    if (!(await confirmDialog({ title: `Archive IT asset "${a.name}"?`, message: "It will be removed from the inventory.", confirmLabel: "Archive", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/assets/${a.id}`);
      setShowForm(false); if (openId === a.id) setOpenId(null); setRefreshKey((k) => k + 1); loadSummary(); toast("Archived");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete IT asset"); }
  }
  async function createTag() {
    const name = newTag.trim(); if (!name) return; setCreatingTag(true);
    try {
      const t = await apiCall<TagRow>("POST", "/asset-tags", { name, category: "", description: "", color: "" });
      setTags((p) => [...p, t]); set("tag_ids", [...f.tag_ids, t.id]); setNewTag("");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to create tag"); }
    finally { setCreatingTag(false); }
  }
  async function addDependency() {
    if (!detail || !depAssetId) return; setError(null);
    try {
      await apiCall("POST", "/assets/dependencies", { information_asset_id: depAssetId, it_asset_id: detail.id, relationship_type: depRel, notes: depNotes });
      setDepAssetId(null); setDepAssetLabel(""); setDepNotes(""); loadDetail(detail.id);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to link information asset"); }
  }
  async function removeDependency(depId: string) {
    if (!detail) return; if (!(await confirmDialog({ title: "Unlink this hosted information asset?", danger: true, confirmLabel: "Unlink" }))) return;
    try { await apiCall<void>("DELETE", `/assets/dependencies/${depId}`); loadDetail(detail.id); }
    catch (e) { setError(e instanceof Error ? e.message : "Failed to unlink information asset"); }
  }

  const mediaTypeOpts: Option[] = useMemo(() => mediaTypes.map((m) => ({ value: m.id, label: m.name })), [mediaTypes]);
  const tagOpts: Option[] = useMemo(() => tags.map((t) => ({ value: t.id, label: t.name, sub: t.category || undefined })), [tags]);

  const columns: Column<Asset>[] = [
    { key: "name", header: "Name", sortable: true, render: (a) => <span className="cell-title">{a.name}</span> },
    { key: "environment", header: "Environment", sortable: true, render: (a) => <Badge tone="neutral" plain>{cap(a.environment)}</Badge> },
    { key: "availability", header: "Availability", render: (a) => <CritBadge value={a.availability} /> },
    { key: "replacement_cost", header: "Cost band", sortable: true, render: (a) => <CritBadge value={a.cost_band} /> },
    { key: "effective_criticality", header: "Effective criticality", render: (a) => <CritBadge value={a.effective_criticality} /> },
    { key: "hosted", header: "Hosted data", align: "center", render: (a) => <span className="muted">{a.dependencies?.length || "—"}</span> },
  ];

  /* --------------------------------------------------------------- form tabs (unchanged) */
  const identityTab = (
    <>
      <Field label="Name" required help="For example: DC-Karachi Core Banking DB Server, SWIFT Gateway Appliance.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="DB-KHI-CORE-01" required />
      </Field>
      <Field label="Description"><TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this supporting asset is and where it runs." /></Field>
      <Field label="Media type" help="The IT asset taxonomy (Hardware, Software, Network device…).">
        <Select value={f.media_type_id} onChange={(v) => set("media_type_id", v)} options={mediaTypeOpts} placeholder="— none —" />
      </Field>
    </>
  );
  const costTab = (
    <>
      <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>IT assets are judged on cost and availability only. Business-criticality is inherited from the information assets they host — a backup server is critical because of the data on it, not on its own.</p>
      <div className="field-row">
        <Field label="Replacement cost" help="Cost to replace this asset — drives its cost band."><TextInput type="number" value={f.replacement_cost} onChange={(v) => set("replacement_cost", v)} placeholder="0" /></Field>
        <Field label="Currency"><TextInput value={f.currency} onChange={(v) => set("currency", v)} placeholder="PKR" /></Field>
        <Field label="Availability" help="How available this asset must be (SLA tier)."><Select value={f.availability} onChange={(v) => set("availability", v)} options={CRIT} /></Field>
      </div>
      <div className="field-row">
        <Field label="RTO (hours)" help="Recovery time objective for this asset."><TextInput type="number" value={f.rto_hours} onChange={(v) => set("rto_hours", v)} placeholder="4" /></Field>
        <Field label="RPO (hours)" help="Recovery point objective — tolerable data loss window."><TextInput type="number" value={f.rpo_hours} onChange={(v) => set("rpo_hours", v)} placeholder="1" /></Field>
      </div>
    </>
  );
  const inventoryTab = (
    <>
      <div className="field-row">
        <Field label="Environment"><Select value={f.environment} onChange={(v) => set("environment", v)} options={ENVIRONMENT} /></Field>
        <Field label="Location" help="Data centre / site."><TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="DC-Karachi" /></Field>
      </div>
      <div className="field-row">
        <Field label="Hostname"><TextInput value={f.hostname} onChange={(v) => set("hostname", v)} placeholder="db-khi-core-01" /></Field>
        <Field label="IP address"><TextInput value={f.ip_address} onChange={(v) => set("ip_address", v)} placeholder="10.20.0.11" /></Field>
      </div>
      <div className="field-row">
        <Field label="Serial number"><TextInput value={f.serial_number} onChange={(v) => set("serial_number", v)} placeholder="SN-XXXX" /></Field>
        <Field label="Manufacturer"><TextInput value={f.manufacturer} onChange={(v) => set("manufacturer", v)} placeholder="Dell" /></Field>
      </div>
      <div className="field-row">
        <Field label="Model number"><TextInput value={f.model_number} onChange={(v) => set("model_number", v)} placeholder="PowerEdge R760" /></Field>
        <Field label="OS version"><TextInput value={f.os_version} onChange={(v) => set("os_version", v)} placeholder="RHEL 9.3" /></Field>
      </div>
    </>
  );
  const tagsTab = (
    <>
      <Field label="Tags" help="Free-form operational tags for IT assets (not sensitivity labels)."><MultiSelect value={f.tag_ids} onChange={(v) => set("tag_ids", v)} options={tagOpts} /></Field>
      <Field label="Create a tag" help="Quickly add a new tag and attach it to this asset.">
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder="e.g. PCI-scope, DC-Karachi, EOL-2026"
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); createTag(); } }} />
          <button className="btn secondary" type="button" onClick={createTag} disabled={creatingTag || !newTag.trim()}>{creatingTag ? "Adding…" : "Add tag"}</button>
        </div>
      </Field>
      <div className="field-row">
        <Field label="Discovery source" help="How this asset was brought into the inventory."><Select value={f.discovery_source} onChange={(v) => set("discovery_source", v)} options={DISCOVERY} /></Field>
        <Field label="External ID" help="Identifier in the source system (CMDB, AD, Intune…)."><TextInput value={f.external_id} onChange={(v) => set("external_id", v)} placeholder="CMDB-00123" /></Field>
      </div>
      <Field label="Workflow status" help="Approval lifecycle for this asset record."><Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} /></Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>IT Asset Management</h1>
          <p>Supporting assets — hardware, software and network. Judged on cost and availability, with criticality inheriting from the information assets they host.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add IT asset</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.total ?? 0).toLocaleString()}</span></div><span className="l">IT assets</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.effective_critical ?? 0).toLocaleString()}</span></div><span className="l">Effective-critical</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.production ?? 0).toLocaleString()}</span></div><span className="l">Production assets</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{money(summary?.total_replacement_value)}</span></div><span className="l">Total replacement value</span></div>
      </div>

      <DataTable<Asset>
        columns={columns}
        fetcher={fetchAssets}
        rowKey={(a) => a.id}
        onRowClick={(a) => setOpenId(a.id)}
        activeKey={openId}
        searchPlaceholder="Search IT assets by name, hostname or owner…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No IT assets yet. Add hardware, software and network assets to build the supporting-asset inventory."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail?.name || "…"}
        subtitle={detail ? `${cap(detail.environment)}${detail.hostname ? " · " + detail.hostname : ""}${detail.ip_address ? " · " + detail.ip_address : ""}` : ""}
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
              <div><div className="muted" style={{ fontSize: 12 }}>Intrinsic (cost + availability)</div><div style={{ marginTop: 4 }}><CritBadge value={detail.intrinsic_criticality} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Derived (from hosted data)</div><div style={{ marginTop: 4 }}><CritBadge value={detail.derived_criticality} /></div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Effective</div><div style={{ marginTop: 4 }}><CritBadge value={detail.effective_criticality} /></div></div>
              <div style={{ marginLeft: "auto", textAlign: "right" }}><div className="muted" style={{ fontSize: 12 }}>Replacement cost · band</div><div style={{ marginTop: 4 }}><strong>{money(detail.replacement_cost, detail.currency)}</strong> <CritBadge value={detail.cost_band} /></div></div>
            </div>

            <strong>Hosted information assets</strong>
            <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>The data this asset carries. Its effective criticality inherits the highest business value of the information assets it hosts.</p>
            <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(ev) => { ev.preventDefault(); addDependency(); }}>
              <div style={{ flex: "1 1 220px" }}>
                <label className="label">Information asset</label>
                <AsyncSelect search={searchInfoAssets} value={depAssetId} selectedLabel={depAssetLabel} placeholder="Search information assets…" onChange={(v, o) => { setDepAssetId(v); setDepAssetLabel(o?.label || ""); }} />
              </div>
              <div style={{ width: 150 }}>
                <label className="label">Relationship</label>
                <select className="select" value={depRel} onChange={(e) => setDepRel(e.target.value)}>{RELATIONSHIP.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}</select>
              </div>
              <div style={{ flex: "1 1 160px" }}>
                <label className="label">Notes</label>
                <input className="input" value={depNotes} onChange={(e) => setDepNotes(e.target.value)} placeholder="Optional context" />
              </div>
              <button className="btn" disabled={!depAssetId}>Link</button>
            </form>

            <div className="table-wrap">
              <table>
                <thead><tr><th>Information asset</th><th>Relationship</th><th>Notes</th><th></th></tr></thead>
                <tbody>
                  {detail.dependencies.map((d) => (
                    <tr key={d.id}>
                      <td className="cell-title">{d.information_asset?.label || "—"}</td>
                      <td><Badge tone="info" plain>{cap(d.relationship_type)}</Badge></td>
                      <td className="muted">{d.notes || "—"}</td>
                      <td><button className="btn secondary sm" onClick={() => removeDependency(d.id)}>Unlink</button></td>
                    </tr>
                  ))}
                  {detail.dependencies.length === 0 && (<tr><td colSpan={4}><span className="muted">No information assets hosted on this asset yet.</span></td></tr>)}
                </tbody>
              </table>
            </div>

            {detail.tags.length > 0 && (
              <div style={{ marginTop: 14, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                <span className="muted" style={{ fontSize: 13 }}>Tags:</span>
                {detail.tags.map((t) => (<Badge key={t.id} tone="neutral" plain>{t.name}</Badge>))}
              </div>
            )}

            <div style={{ marginTop: 20 }}>
              <strong style={{ fontSize: 13 }}>Related records</strong>
              <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 8 }}>
                <RelatedChips label="Risks" items={asRefs(detail.risks)} href="/risks" />
                <RelatedChips label="Processes" items={asRefs(detail.processes)} href="/processes" />
                <RelatedChips label="Legal registers" items={asRefs(detail.legals)} href="/legal" />
                <RelatedChips label="Compliance requirements" items={asRefs(detail.requirements)} href="/compliance" />
                <RelatedChips label="Incidents" items={asRefs(detail.incidents)} href="/incidents" />
                <RelatedChips label="Exceptions" items={asRefs(detail.exceptions)} href="/exceptions" />
                <RelatedChips label="Related assets" items={asRefs(detail.related_assets)} href="/it-assets" />
                <RelatedChips label="Controls" items={detail.controls} href="/controls" />
                <RelatedChips label="Threats" items={detail.threats} href="/threat-library" />
                <RelatedChips label="Vulnerabilities" items={detail.vulnerabilities} href="/threat-library" />
                <RelatedChips label="Third parties" items={detail.vendors} href="/vendors" />
                <RelatedChips label="Access reviews" items={detail.access_reviews} href="/access-reviews" />
              </div>
            </div>

            <div style={{ marginTop: 20 }}><RecordPanels model="asset" entityId={detail.id} /></div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit IT asset — ${editing.name}` : "Add IT asset"}
          wide
          tabs={[
            { id: "identity", label: "Identity", content: identityTab, required: true },
            { id: "cost", label: "Cost & Availability", content: costTab },
            { id: "inventory", label: "Inventory", content: inventoryTab },
            { id: "tags", label: "Tags & Discovery", content: tagsTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create IT asset"}
          footerLeft={editing ? (
            <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--red)" }}>Delete</button>
          ) : undefined}
        />
      )}
    </>
  );
}

export default function ITAssetsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ITAssetsInner />
    </Suspense>
  );
}
