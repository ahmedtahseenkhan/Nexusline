"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, MultiSelect, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconAsset, IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

/* ------------------------------------------------------------------ types */
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";
type LinkRef = { id: string; label: string };
type TagRow = { id: string; name: string; category: string; description?: string; color?: string };
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
  availability: string;
  replacement_cost: number;
  currency: string;
  rto_hours: number | null;
  rpo_hours: number | null;
  environment: string;
  location: string;
  hostname: string;
  ip_address: string;
  serial_number: string;
  manufacturer: string;
  model_number: string;
  os_version: string;
  discovery_source: string;
  external_id: string;
  cost_band: string;
  intrinsic_criticality: string;
  derived_criticality: string;
  effective_criticality: string;
  workflow_status: string;
  tags: TagRow[];
  dependencies: DependencyRow[];
  created_at: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
type MediaType = { id: string; name: string; description: string; editable: boolean };

/* ----------------------------------------------------------------- helpers */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());
const money = (n: number | null | undefined, cur = "PKR") => `${cur} ${Number(n || 0).toLocaleString()}`;

/* ------------------------------------------------------------------ enum lists */
const CRIT = opts(["low", "medium", "high", "critical"]);
const ENVIRONMENT = opts(["production", "dr", "uat", "staging", "development", "not_applicable"]);
const DISCOVERY = opts([
  "manual",
  "active_directory",
  "intune_mdm",
  "cmdb",
  "network_scan",
  "cloud_connector",
  "edr",
  "import_csv",
]);
const RELATIONSHIP = opts(["hosts", "stores", "processes", "transmits", "backs_up"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

const CRIT_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "high", critical: "critical" };

function CritBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={CRIT_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

/* ------------------------------------------------------------------ form */
type FormState = {
  name: string;
  description: string;
  media_type_id: string;
  replacement_cost: string;
  currency: string;
  availability: string;
  rto_hours: string;
  rpo_hours: string;
  environment: string;
  location: string;
  hostname: string;
  ip_address: string;
  serial_number: string;
  manufacturer: string;
  model_number: string;
  os_version: string;
  tag_ids: string[];
  discovery_source: string;
  external_id: string;
  workflow_status: string;
};

const BLANK: FormState = {
  name: "",
  description: "",
  media_type_id: "",
  replacement_cost: "",
  currency: "PKR",
  availability: "medium",
  rto_hours: "",
  rpo_hours: "",
  environment: "production",
  location: "",
  hostname: "",
  ip_address: "",
  serial_number: "",
  manufacturer: "",
  model_number: "",
  os_version: "",
  tag_ids: [],
  discovery_source: "manual",
  external_id: "",
  workflow_status: "draft",
};

function fromAsset(a: Asset): FormState {
  return {
    name: a.name,
    description: a.description || "",
    media_type_id: a.media_type?.id || "",
    replacement_cost: a.replacement_cost != null ? String(a.replacement_cost) : "",
    currency: a.currency || "PKR",
    availability: a.availability || "medium",
    rto_hours: a.rto_hours != null ? String(a.rto_hours) : "",
    rpo_hours: a.rpo_hours != null ? String(a.rpo_hours) : "",
    environment: a.environment || "production",
    location: a.location || "",
    hostname: a.hostname || "",
    ip_address: a.ip_address || "",
    serial_number: a.serial_number || "",
    manufacturer: a.manufacturer || "",
    model_number: a.model_number || "",
    os_version: a.os_version || "",
    tag_ids: a.tags.map((t) => t.id),
    discovery_source: a.discovery_source || "manual",
    external_id: a.external_id || "",
    workflow_status: a.workflow_status || "draft",
  };
}

/** Send only the IT-relevant fields plus asset_class — no business-value / CIA framing. */
function toPayload(f: FormState): Record<string, unknown> {
  return {
    asset_class: "it_asset",
    name: f.name,
    description: f.description,
    media_type_id: f.media_type_id || null,
    replacement_cost: f.replacement_cost === "" ? 0 : Number(f.replacement_cost),
    currency: f.currency || "PKR",
    availability: f.availability,
    rto_hours: f.rto_hours === "" ? null : Number(f.rto_hours),
    rpo_hours: f.rpo_hours === "" ? null : Number(f.rpo_hours),
    environment: f.environment,
    location: f.location,
    hostname: f.hostname,
    ip_address: f.ip_address,
    serial_number: f.serial_number,
    manufacturer: f.manufacturer,
    model_number: f.model_number,
    os_version: f.os_version,
    tag_ids: f.tag_ids,
    discovery_source: f.discovery_source,
    external_id: f.external_id,
    workflow_status: f.workflow_status,
  };
}

export default function ITAssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [open, setOpen] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);

  // lookups / relation sources
  const [mediaTypes, setMediaTypes] = useState<MediaType[]>([]);
  const [tags, setTags] = useState<TagRow[]>([]);
  const [infoAssets, setInfoAssets] = useState<Asset[]>([]);

  // form
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // inline "create tag"
  const [newTag, setNewTag] = useState("");
  const [creatingTag, setCreatingTag] = useState(false);

  // hosted-data (dependency) add-form
  const [depAssetId, setDepAssetId] = useState("");
  const [depRel, setDepRel] = useState("hosts");
  const [depNotes, setDepNotes] = useState("");

  async function load(keepOpen?: string) {
    try {
      const a = await apiCall<Page<Asset>>("GET", "/assets?asset_class=it_asset&limit=200");
      setAssets(a.items);
      if (keepOpen) setOpen(a.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load IT assets");
    }
  }

  function loadLookups() {
    const ignore = () => {};
    apiCall<MediaType[]>("GET", "/asset-media-types").then(setMediaTypes).catch(ignore);
    apiCall<TagRow[]>("GET", "/asset-tags").then(setTags).catch(ignore);
    apiCall<Page<Asset>>("GET", "/assets?asset_class=information_asset&limit=200")
      .then((r) => setInfoAssets(r.items))
      .catch(ignore);
  }

  useEffect(() => {
    load();
    loadLookups();
  }, []);

  async function refresh(id: string) {
    const a = await apiCall<Asset>("GET", `/assets/${id}`);
    setOpen(a);
    setAssets((prev) => prev.map((x) => (x.id === id ? a : x)));
  }

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  function openEdit(a: Asset) {
    setEditing(a);
    setF(fromAsset(a));
    setError(null);
    setShowForm(true);
  }
  function toggle(a: Asset) {
    setDepAssetId("");
    setDepRel("hosts");
    setDepNotes("");
    setOpen(open?.id === a.id ? null : a);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Asset>("PATCH", `/assets/${editing.id}`, payload);
      else await apiCall<Asset>("POST", "/assets", payload);
      setShowForm(false);
      await load(open?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save IT asset");
    } finally {
      setSaving(false);
    }
  }

  async function remove(a: Asset) {
    if (!window.confirm(`Archive IT asset "${a.name}"? It will be removed from the inventory.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/assets/${a.id}`);
      setShowForm(false);
      if (open?.id === a.id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete IT asset");
    }
  }

  async function createTag() {
    const name = newTag.trim();
    if (!name) return;
    setCreatingTag(true);
    try {
      const t = await apiCall<TagRow>("POST", "/asset-tags", { name, category: "", description: "", color: "" });
      setTags((p) => [...p, t]);
      set("tag_ids", [...f.tag_ids, t.id]);
      setNewTag("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create tag");
    } finally {
      setCreatingTag(false);
    }
  }

  async function addDependency() {
    if (!open || !depAssetId) return;
    setError(null);
    try {
      await apiCall("POST", "/assets/dependencies", {
        information_asset_id: depAssetId,
        it_asset_id: open.id,
        relationship_type: depRel,
        notes: depNotes,
      });
      setDepAssetId("");
      setDepNotes("");
      await refresh(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to link information asset");
    }
  }

  async function removeDependency(depId: string) {
    if (!open) return;
    if (!window.confirm("Unlink this hosted information asset?")) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/assets/dependencies/${depId}`);
      await refresh(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to unlink information asset");
    }
  }

  /* ------------------------------------------------------------- options */
  const mediaTypeOpts: Option[] = useMemo(
    () => mediaTypes.map((m) => ({ value: m.id, label: m.name })),
    [mediaTypes],
  );
  const tagOpts: Option[] = useMemo(
    () => tags.map((t) => ({ value: t.id, label: t.name, sub: t.category || undefined })),
    [tags],
  );
  const infoAssetOpts: Option[] = useMemo(
    () => infoAssets.map((a) => ({ value: a.id, label: a.name, sub: cap(a.effective_criticality || "") })),
    [infoAssets],
  );

  /* -------------------------------------------------------------- summary */
  const totalValue = useMemo(() => assets.reduce((s, a) => s + Number(a.replacement_cost || 0), 0), [assets]);
  const criticalCount = assets.filter((a) => a.effective_criticality === "critical").length;
  const productionCount = assets.filter((a) => a.environment === "production").length;

  /* --------------------------------------------------------------- tabs */
  const identityTab = (
    <>
      <Field label="Name" required help="For example: DC-Karachi Core Banking DB Server, SWIFT Gateway Appliance.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="DB-KHI-CORE-01" required />
      </Field>
      <Field label="Description">
        <TextArea
          value={f.description}
          onChange={(v) => set("description", v)}
          rows={3}
          placeholder="What this supporting asset is and where it runs."
        />
      </Field>
      <Field label="Media type" help="The IT asset taxonomy (Hardware, Software, Network device…).">
        <Select value={f.media_type_id} onChange={(v) => set("media_type_id", v)} options={mediaTypeOpts} placeholder="— none —" />
      </Field>
    </>
  );

  const costTab = (
    <>
      <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
        IT assets are judged on cost and availability only. Business-criticality is inherited from the information
        assets they host — a backup server is critical because of the data on it, not on its own.
      </p>
      <div className="field-row">
        <Field label="Replacement cost" help="Cost to replace this asset — drives its cost band.">
          <TextInput type="number" value={f.replacement_cost} onChange={(v) => set("replacement_cost", v)} placeholder="0" />
        </Field>
        <Field label="Currency">
          <TextInput value={f.currency} onChange={(v) => set("currency", v)} placeholder="PKR" />
        </Field>
        <Field label="Availability" help="How available this asset must be (SLA tier).">
          <Select value={f.availability} onChange={(v) => set("availability", v)} options={CRIT} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="RTO (hours)" help="Recovery time objective for this asset.">
          <TextInput type="number" value={f.rto_hours} onChange={(v) => set("rto_hours", v)} placeholder="4" />
        </Field>
        <Field label="RPO (hours)" help="Recovery point objective — tolerable data loss window.">
          <TextInput type="number" value={f.rpo_hours} onChange={(v) => set("rpo_hours", v)} placeholder="1" />
        </Field>
      </div>
    </>
  );

  const inventoryTab = (
    <>
      <div className="field-row">
        <Field label="Environment">
          <Select value={f.environment} onChange={(v) => set("environment", v)} options={ENVIRONMENT} />
        </Field>
        <Field label="Location" help="Data centre / site.">
          <TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="DC-Karachi" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Hostname">
          <TextInput value={f.hostname} onChange={(v) => set("hostname", v)} placeholder="db-khi-core-01" />
        </Field>
        <Field label="IP address">
          <TextInput value={f.ip_address} onChange={(v) => set("ip_address", v)} placeholder="10.20.0.11" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Serial number">
          <TextInput value={f.serial_number} onChange={(v) => set("serial_number", v)} placeholder="SN-XXXX" />
        </Field>
        <Field label="Manufacturer">
          <TextInput value={f.manufacturer} onChange={(v) => set("manufacturer", v)} placeholder="Dell" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Model number">
          <TextInput value={f.model_number} onChange={(v) => set("model_number", v)} placeholder="PowerEdge R760" />
        </Field>
        <Field label="OS version">
          <TextInput value={f.os_version} onChange={(v) => set("os_version", v)} placeholder="RHEL 9.3" />
        </Field>
      </div>
    </>
  );

  const tagsTab = (
    <>
      <Field label="Tags" help="Free-form operational tags for IT assets (not sensitivity labels).">
        <MultiSelect value={f.tag_ids} onChange={(v) => set("tag_ids", v)} options={tagOpts} />
      </Field>
      <Field label="Create a tag" help="Quickly add a new tag and attach it to this asset.">
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="input"
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            placeholder="e.g. PCI-scope, DC-Karachi, EOL-2026"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                createTag();
              }
            }}
          />
          <button className="btn secondary" type="button" onClick={createTag} disabled={creatingTag || !newTag.trim()}>
            {creatingTag ? "Adding…" : "Add tag"}
          </button>
        </div>
      </Field>
      <div className="field-row">
        <Field label="Discovery source" help="How this asset was brought into the inventory.">
          <Select value={f.discovery_source} onChange={(v) => set("discovery_source", v)} options={DISCOVERY} />
        </Field>
        <Field label="External ID" help="Identifier in the source system (CMDB, AD, Intune…).">
          <TextInput value={f.external_id} onChange={(v) => set("external_id", v)} placeholder="CMDB-00123" />
        </Field>
      </div>
      <Field label="Workflow status" help="Approval lifecycle for this asset record.">
        <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>IT Asset Management</h1>
          <p>
            Supporting assets — hardware, software and network. Judged on cost and availability, with criticality
            inheriting from the information assets they host.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add IT asset
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{assets.length.toLocaleString()}</span>
          </div>
          <span className="l">IT assets</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{criticalCount.toLocaleString()}</span>
          </div>
          <span className="l">Effective-critical</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{productionCount.toLocaleString()}</span>
          </div>
          <span className="l">Production assets</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{money(totalValue)}</span>
          </div>
          <span className="l">Total replacement value</span>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>IT Assets</h3>
          <span className="sub">{assets.length} total · click a row for the criticality breakdown</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Environment</th>
                <th>Availability</th>
                <th>Cost band</th>
                <th>Effective criticality</th>
                <th>Hosted data</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => toggle(a)}>
                  <td className="cell-title">{a.name}</td>
                  <td><Badge tone="neutral" plain>{cap(a.environment)}</Badge></td>
                  <td><CritBadge value={a.availability} /></td>
                  <td><CritBadge value={a.cost_band} /></td>
                  <td><CritBadge value={a.effective_criticality} /></td>
                  <td className="muted">{a.dependencies.length || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => toggle(a)}>
                        {open?.id === a.id ? "Hide" : "Details"}
                      </button>
                      <button className="btn secondary sm" onClick={() => openEdit(a)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => remove(a)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {assets.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconAsset width={24} height={24} /></span>
                      <h3>No IT assets yet</h3>
                      <p>Add hardware, software and network assets to build the supporting-asset inventory.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <>
          <div className="card" style={{ marginTop: 16 }}>
            <div className="card-head row-between">
              <div>
                <h3>{open.name}</h3>
                <span className="sub">
                  {cap(open.environment)}
                  {open.hostname ? " · " + open.hostname : ""}
                  {open.ip_address ? " · " + open.ip_address : ""}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn secondary sm" onClick={() => openEdit(open)}>Edit</button>
                <button className="btn secondary sm" onClick={() => remove(open)}>Delete</button>
              </div>
            </div>

            <div className="card-pad">
              {/* Derived-criticality breakdown — the whole IT criticality story */}
              <div
                style={{
                  display: "flex",
                  gap: 24,
                  flexWrap: "wrap",
                  alignItems: "flex-end",
                  padding: "14px 16px",
                  border: "1px solid var(--border, #e5e7eb)",
                  borderRadius: 8,
                  marginBottom: 16,
                }}
              >
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Intrinsic (cost + availability)</div>
                  <div style={{ marginTop: 4 }}><CritBadge value={open.intrinsic_criticality} /></div>
                </div>
                <div style={{ fontSize: 20, color: "var(--muted, #94a3b8)" }}>·</div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Derived (from hosted data)</div>
                  <div style={{ marginTop: 4 }}><CritBadge value={open.derived_criticality} /></div>
                </div>
                <div style={{ fontSize: 20, color: "var(--muted, #94a3b8)" }}>·</div>
                <div>
                  <div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Effective</div>
                  <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 8 }}>
                    <CritBadge value={open.effective_criticality} />
                    <strong>{cap(open.effective_criticality)}</strong>
                  </div>
                </div>
                <div style={{ marginLeft: "auto", textAlign: "right" }}>
                  <div className="muted" style={{ fontSize: 12 }}>Replacement cost · cost band</div>
                  <div style={{ marginTop: 4 }}>
                    <strong>{money(open.replacement_cost, open.currency)}</strong>{" "}
                    <CritBadge value={open.cost_band} />
                  </div>
                </div>
              </div>

              {/* Hosted information assets */}
              <strong>Hosted information assets</strong>
              <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                The data this asset carries. Its effective criticality inherits the highest business value of the
                information assets it hosts.
              </p>
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(ev) => { ev.preventDefault(); addDependency(); }}
              >
                <div style={{ flex: "1 1 240px" }}>
                  <label className="label">Information asset</label>
                  <select className="select" value={depAssetId} onChange={(e) => setDepAssetId(e.target.value)} required>
                    <option value="">Choose an information asset…</option>
                    {infoAssetOpts.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                </div>
                <div style={{ width: 160 }}>
                  <label className="label">Relationship</label>
                  <select className="select" value={depRel} onChange={(e) => setDepRel(e.target.value)}>
                    {RELATIONSHIP.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                  </select>
                </div>
                <div style={{ flex: "1 1 200px" }}>
                  <label className="label">Notes</label>
                  <input className="input" value={depNotes} onChange={(e) => setDepNotes(e.target.value)} placeholder="Optional context" />
                </div>
                <button className="btn" disabled={!depAssetId}>Link</button>
              </form>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Information asset</th>
                      <th>Relationship</th>
                      <th>Notes</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {open.dependencies.map((d) => (
                      <tr key={d.id}>
                        <td className="cell-title">{d.information_asset?.label || "—"}</td>
                        <td><Badge tone="info" plain>{cap(d.relationship_type)}</Badge></td>
                        <td className="muted">{d.notes || "—"}</td>
                        <td>
                          <button className="btn secondary sm" onClick={() => removeDependency(d.id)}>Unlink</button>
                        </td>
                      </tr>
                    ))}
                    {open.dependencies.length === 0 && (
                      <tr><td colSpan={4}><span className="muted">No information assets hosted on this asset yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {open.tags.length > 0 && (
                <div style={{ marginTop: 14, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                  <span className="muted" style={{ fontSize: 13 }}>Tags:</span>
                  {open.tags.map((t) => (
                    <Badge key={t.id} tone="neutral" plain>{t.name}</Badge>
                  ))}
                </div>
              )}
            </div>
          </div>

          <RecordPanels model="asset" entityId={open.id} />
        </>
      )}

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
          footerLeft={
            editing ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => remove(editing)}
                disabled={saving}
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
