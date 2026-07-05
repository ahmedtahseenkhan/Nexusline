"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconLayers, IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

/* ------------------------------------------------------------------ types */
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";
type LinkRef = { id: string; label: string };
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
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
type MediaType = { id: string; name: string; description: string; editable: boolean };
type LabelRow = { id: string; name: string; description: string; color: string };
type BusinessUnit = { id: string; name: string };

/* ----------------------------------------------------------------- helpers */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

/* ------------------------------------------------------------------ enum lists */
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
  name: string;
  description: string;
  media_type_id: string;
  information_owner: string;
  business_value: string;
  confidentiality: string;
  integrity: string;
  availability: string;
  label_id: string;
  data_categories: string;
  records_volume: string;
  self_assessed: boolean;
  assessed_by: string;
  assessed_date: string;
  owner_id: string;
  guardian_id: string;
  user_id: string;
  review_frequency: string;
  workflow_status: string;
};

const BLANK: FormState = {
  name: "",
  description: "",
  media_type_id: "",
  information_owner: "",
  business_value: "medium",
  confidentiality: "medium",
  integrity: "medium",
  availability: "medium",
  label_id: "",
  data_categories: "",
  records_volume: "",
  self_assessed: false,
  assessed_by: "",
  assessed_date: "",
  owner_id: "",
  guardian_id: "",
  user_id: "",
  review_frequency: "annual",
  workflow_status: "draft",
};

function fromAsset(a: Asset): FormState {
  return {
    name: a.name,
    description: a.description || "",
    media_type_id: a.media_type?.id || "",
    information_owner: a.information_owner || "",
    business_value: a.business_value || "medium",
    confidentiality: a.confidentiality || "medium",
    integrity: a.integrity || "medium",
    availability: a.availability || "medium",
    label_id: a.label?.id || "",
    data_categories: a.data_categories || "",
    records_volume: a.records_volume || "",
    self_assessed: !!a.self_assessed,
    assessed_by: a.assessed_by || "",
    assessed_date: a.assessed_date || "",
    owner_id: a.owner?.id || "",
    guardian_id: a.guardian?.id || "",
    user_id: a.user?.id || "",
    review_frequency: a.review_frequency || "annual",
    workflow_status: a.workflow_status || "draft",
  };
}

/** Send only the information-asset (primary) fields plus asset_class. */
function toPayload(f: FormState): Record<string, unknown> {
  return {
    asset_class: "information_asset",
    name: f.name,
    description: f.description,
    media_type_id: f.media_type_id || null,
    information_owner: f.information_owner,
    business_value: f.business_value,
    confidentiality: f.confidentiality,
    integrity: f.integrity,
    availability: f.availability,
    label_id: f.label_id || null,
    data_categories: f.data_categories,
    records_volume: f.records_volume,
    self_assessed: f.self_assessed,
    assessed_by: f.assessed_by,
    assessed_date: f.assessed_date || null,
    owner_id: f.owner_id || null,
    guardian_id: f.guardian_id || null,
    user_id: f.user_id || null,
    review_frequency: f.review_frequency,
    workflow_status: f.workflow_status,
  };
}

export default function InformationAssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [open, setOpen] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);

  // lookups / relation sources
  const [mediaTypes, setMediaTypes] = useState<MediaType[]>([]);
  const [labels, setLabels] = useState<LabelRow[]>([]);
  const [units, setUnits] = useState<BusinessUnit[]>([]);
  const [itAssets, setItAssets] = useState<Asset[]>([]);

  // form
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // hosted-on (dependency) add-form
  const [depAssetId, setDepAssetId] = useState("");
  const [depRel, setDepRel] = useState("hosts");
  const [depNotes, setDepNotes] = useState("");

  async function load(keepOpen?: string) {
    try {
      const a = await apiCall<Page<Asset>>("GET", "/assets?asset_class=information_asset&limit=200");
      setAssets(a.items);
      if (keepOpen) setOpen(a.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load information assets");
    }
  }

  function loadLookups() {
    const ignore = () => {};
    apiCall<MediaType[]>("GET", "/asset-media-types").then(setMediaTypes).catch(ignore);
    apiCall<LabelRow[]>("GET", "/asset-labels").then(setLabels).catch(ignore);
    apiCall<Page<BusinessUnit>>("GET", "/business-units").then((r) => setUnits(r.items)).catch(ignore);
    apiCall<Page<Asset>>("GET", "/assets?asset_class=it_asset&limit=200")
      .then((r) => setItAssets(r.items))
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
      setError(e instanceof Error ? e.message : "Failed to save information asset");
    } finally {
      setSaving(false);
    }
  }

  async function remove(a: Asset) {
    if (!window.confirm(`Archive information asset "${a.name}"? It will be removed from the inventory.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/assets/${a.id}`);
      setShowForm(false);
      if (open?.id === a.id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete information asset");
    }
  }

  async function addDependency() {
    if (!open || !depAssetId) return;
    setError(null);
    try {
      await apiCall("POST", "/assets/dependencies", {
        information_asset_id: open.id,
        it_asset_id: depAssetId,
        relationship_type: depRel,
        notes: depNotes,
      });
      setDepAssetId("");
      setDepNotes("");
      await refresh(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to link IT asset");
    }
  }

  async function removeDependency(depId: string) {
    if (!open) return;
    if (!window.confirm("Unlink this IT asset?")) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/assets/dependencies/${depId}`);
      await refresh(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to unlink IT asset");
    }
  }

  /* ------------------------------------------------------------- options */
  const mediaTypeOpts: Option[] = useMemo(() => mediaTypes.map((m) => ({ value: m.id, label: m.name })), [mediaTypes]);
  const labelOpts: Option[] = useMemo(() => labels.map((l) => ({ value: l.id, label: l.name })), [labels]);
  const unitOpts: Option[] = useMemo(() => units.map((u) => ({ value: u.id, label: u.name })), [units]);
  const itAssetOpts: Option[] = useMemo(
    () => itAssets.map((a) => ({ value: a.id, label: a.name, sub: cap(a.effective_criticality || "") })),
    [itAssets],
  );

  /* -------------------------------------------------------------- summary */
  const highValueCount = assets.filter((a) => a.business_value === "high" || a.business_value === "critical").length;
  const selfAssessedCount = assets.filter((a) => a.self_assessed).length;
  const selfAssessedPct = assets.length ? Math.round((selfAssessedCount / assets.length) * 100) : 0;
  const piiCount = assets.filter(hasPii).length;

  /* --------------------------------------------------------------- tabs */
  const identityTab = (
    <>
      <Field label="Name" required help="For example: Customer master data, SWIFT payment messages, Loan origination records.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Customer master data" required />
      </Field>
      <Field label="Description">
        <TextArea
          value={f.description}
          onChange={(v) => set("description", v)}
          rows={3}
          placeholder="What this data / application is and why it matters to the business."
        />
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
        <Field label="Confidentiality">
          <Select value={f.confidentiality} onChange={(v) => set("confidentiality", v)} options={CRIT} />
        </Field>
        <Field label="Integrity">
          <Select value={f.integrity} onChange={(v) => set("integrity", v)} options={CRIT} />
        </Field>
        <Field label="Availability">
          <Select value={f.availability} onChange={(v) => set("availability", v)} options={CRIT} />
        </Field>
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
        <TextArea
          value={f.data_categories}
          onChange={(v) => set("data_categories", v)}
          rows={2}
          placeholder="PII, account numbers, transaction history, CNIC"
        />
      </Field>
    </>
  );

  const selfAssessTab = (
    <>
      <Field label="Self-assessed" help="The business owner has completed the self-assessment for this asset.">
        <Toggle checked={f.self_assessed} onChange={(v) => set("self_assessed", v)} label="Self-assessment completed" />
      </Field>
      <div className="field-row">
        <Field label="Assessed by" help="Who signed off the self-assessment.">
          <TextInput value={f.assessed_by} onChange={(v) => set("assessed_by", v)} placeholder="Business owner name" />
        </Field>
        <Field label="Assessed date">
          <TextInput type="date" value={f.assessed_date} onChange={(v) => set("assessed_date", v)} />
        </Field>
      </div>
      <div className="help">
        Upload the signed self-assessment form via the attachments panel on the record detail — it is kept in the
        central repository.
      </div>
    </>
  );

  const governanceTab = (
    <>
      <div className="field-row">
        <Field label="Owner" help="Business unit accountable for this asset (RACI owner).">
          <Select value={f.owner_id} onChange={(v) => set("owner_id", v)} options={unitOpts} placeholder="— none —" />
        </Field>
        <Field label="Guardian" help="Business unit that safeguards / maintains the asset.">
          <Select value={f.guardian_id} onChange={(v) => set("guardian_id", v)} options={unitOpts} placeholder="— none —" />
        </Field>
        <Field label="User" help="Business unit that uses the asset day to day.">
          <Select value={f.user_id} onChange={(v) => set("user_id", v)} options={unitOpts} placeholder="— none —" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Review frequency" help="How often this asset's value / classification is re-attested.">
          <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
        </Field>
        <Field label="Workflow status" help="Approval lifecycle for this asset record.">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Information Asset Management</h1>
          <p>
            Primary assets — data and applications. Criticality is business value, set by the business owner, with CIA
            classification, handling labels and owner self-assessment.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add information asset
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{assets.length.toLocaleString()}</span>
          </div>
          <span className="l">Information assets</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{highValueCount.toLocaleString()}</span>
          </div>
          <span className="l">High / critical value</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{selfAssessedPct}%</span>
          </div>
          <span className="l">Self-assessed</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{piiCount.toLocaleString()}</span>
          </div>
          <span className="l">Assets with PII</span>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Information Assets</h3>
          <span className="sub">{assets.length} total · click a row for classification &amp; hosting</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Information owner</th>
                <th>Business value</th>
                <th>Classification</th>
                <th>Self-assessed</th>
                <th>Hosted on</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => toggle(a)}>
                  <td className="cell-title">{a.name}</td>
                  <td className="muted">{a.information_owner || "—"}</td>
                  <td><CritBadge value={a.effective_criticality} /></td>
                  <td><CritBadge value={maxCia(a)} /></td>
                  <td>
                    {a.self_assessed ? (
                      <Badge tone="low">Self-assessed</Badge>
                    ) : (
                      <Badge tone="neutral">Pending</Badge>
                    )}
                  </td>
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
                      <span className="ico"><IconLayers width={24} height={24} /></span>
                      <h3>No information assets yet</h3>
                      <p>Register the data and applications that carry business value to build the primary-asset register.</p>
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
                  {open.information_owner ? "Owner " + open.information_owner : "No business owner"}
                  {open.records_volume ? " · " + open.records_volume : ""}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn secondary sm" onClick={() => openEdit(open)}>Edit</button>
                <button className="btn secondary sm" onClick={() => remove(open)}>Delete</button>
              </div>
            </div>

            <div className="card-pad">
              {/* Business value + CIA classification */}
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
                  <div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Business value</div>
                  <div style={{ marginTop: 4 }}><CritBadge value={open.business_value} /></div>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Confidentiality</div>
                  <div style={{ marginTop: 4 }}><CritBadge value={open.confidentiality} /></div>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Integrity</div>
                  <div style={{ marginTop: 4 }}><CritBadge value={open.integrity} /></div>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: 12 }}>Availability</div>
                  <div style={{ marginTop: 4 }}><CritBadge value={open.availability} /></div>
                </div>
                <div style={{ marginLeft: "auto", textAlign: "right" }}>
                  <div className="muted" style={{ fontSize: 12 }}>Effective criticality</div>
                  <div style={{ marginTop: 4 }}><CritBadge value={open.effective_criticality} /></div>
                </div>
              </div>

              <div style={{ marginBottom: 16 }}>
                <span className="muted" style={{ fontSize: 13 }}>Data categories: </span>
                <span>{open.data_categories || "—"}</span>
                {hasPii(open) && <span style={{ marginLeft: 8 }}><Badge tone="high">Contains PII</Badge></span>}
              </div>

              {/* Self-assessment block */}
              <div
                style={{
                  padding: "12px 16px",
                  border: "1px solid var(--border, #e5e7eb)",
                  borderRadius: 8,
                  marginBottom: 16,
                }}
              >
                <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                  <strong>Self-assessment</strong>
                  {open.self_assessed ? (
                    <Badge tone="low">Completed</Badge>
                  ) : (
                    <Badge tone="neutral">Pending</Badge>
                  )}
                  {open.assessed_by && <span className="muted" style={{ fontSize: 13 }}>by {open.assessed_by}</span>}
                  {open.assessed_date && <span className="muted" style={{ fontSize: 13 }}>on {open.assessed_date}</span>}
                </div>
                <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
                  The signed self-assessment form is uploaded via the attachments panel below and held in the central
                  repository.
                </p>
              </div>

              {/* Hosted on (IT assets) */}
              <strong>Hosted on (IT assets)</strong>
              <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                The supporting IT assets that carry this data. Linking here lets those assets inherit this data's
                business value.
              </p>
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(ev) => { ev.preventDefault(); addDependency(); }}
              >
                <div style={{ flex: "1 1 240px" }}>
                  <label className="label">IT asset</label>
                  <select className="select" value={depAssetId} onChange={(e) => setDepAssetId(e.target.value)} required>
                    <option value="">Choose an IT asset…</option>
                    {itAssetOpts.map((o) => (
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
                      <th>IT asset</th>
                      <th>Relationship</th>
                      <th>Notes</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {open.dependencies.map((d) => (
                      <tr key={d.id}>
                        <td className="cell-title">{d.it_asset?.label || "—"}</td>
                        <td><Badge tone="info" plain>{cap(d.relationship_type)}</Badge></td>
                        <td className="muted">{d.notes || "—"}</td>
                        <td>
                          <button className="btn secondary sm" onClick={() => removeDependency(d.id)}>Unlink</button>
                        </td>
                      </tr>
                    ))}
                    {open.dependencies.length === 0 && (
                      <tr><td colSpan={4}><span className="muted">Not linked to any IT asset yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <RecordPanels model="asset" entityId={open.id} />
        </>
      )}

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
