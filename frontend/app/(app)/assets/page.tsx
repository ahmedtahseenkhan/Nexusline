"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, MultiSelect, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconAsset, IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

/* ------------------------------------------------------------------ types */
type LinkRef = { id: string; label: string };
type ClassificationRef = { id: string; name: string; value: number; type_name: string };

type AssetReview = {
  id: string;
  reviewer: string;
  scheduled_date: string;
  actual_date: string | null;
  status: string;
  outcome: string;
  comments: string;
  created_at: string;
};

type Asset = {
  id: string;
  name: string;
  description: string;
  media_type: LinkRef | null;
  label: LinkRef | null;
  owner: LinkRef | null;
  guardian: LinkRef | null;
  user: LinkRef | null;
  confidentiality: string;
  integrity: string;
  availability: string;
  criticality: string;
  classification: string;
  potential_liabilities: string;
  review_frequency: string;
  next_review_date: string | null;
  last_review_date: string | null;
  expired_reviews: number;
  review_status: string;
  workflow_status: string;
  classifications: ClassificationRef[];
  processes: LinkRef[];
  legals: LinkRef[];
  requirements: LinkRef[];
  incidents: LinkRef[];
  exceptions: LinkRef[];
  related_assets: LinkRef[];
  risks: LinkRef[];
  reviews: AssetReview[];
  risk_count: number;
  review_count: number;
  created_at: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type MediaType = { id: string; name: string; description: string; editable: boolean };
type LabelRow = { id: string; name: string; description: string; color: string };
type ClassType = {
  id: string;
  name: string;
  description: string;
  classifications: { id: string; name: string; value: number; criteria: string; type_id: string }[];
};
type BusinessUnit = { id: string; name: string };
type NamedRow = { id: string; name: string };
type RefRow = { id: string; reference?: string; title?: string; name?: string };
type Framework = { id: string; name: string };

/* ----------------------------------------------------------------- helpers */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const CRIT = opts(["low", "medium", "high", "critical"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

const CRIT_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral"> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

const refLabel = (r: RefRow) => r.title || r.name || r.reference || r.id.slice(0, 8);

/* ------------------------------------------------------------------ form */
type FormState = {
  name: string;
  description: string;
  media_type_id: string;
  label_id: string;
  owner_id: string;
  guardian_id: string;
  user_id: string;
  confidentiality: string;
  integrity: string;
  availability: string;
  criticality: string;
  potential_liabilities: string;
  review_frequency: string;
  next_review_date: string;
  workflow_status: string;
  classification_ids: string[];
  process_ids: string[];
  legal_ids: string[];
  requirement_ids: string[];
  incident_ids: string[];
  exception_ids: string[];
  related_ids: string[];
  risk_ids: string[];
};

const BLANK: FormState = {
  name: "",
  description: "",
  media_type_id: "",
  label_id: "",
  owner_id: "",
  guardian_id: "",
  user_id: "",
  confidentiality: "medium",
  integrity: "medium",
  availability: "medium",
  criticality: "medium",
  potential_liabilities: "",
  review_frequency: "annual",
  next_review_date: "",
  workflow_status: "draft",
  classification_ids: [],
  process_ids: [],
  legal_ids: [],
  requirement_ids: [],
  incident_ids: [],
  exception_ids: [],
  related_ids: [],
  risk_ids: [],
};

function fromAsset(a: Asset): FormState {
  return {
    name: a.name,
    description: a.description || "",
    media_type_id: a.media_type?.id || "",
    label_id: a.label?.id || "",
    owner_id: a.owner?.id || "",
    guardian_id: a.guardian?.id || "",
    user_id: a.user?.id || "",
    confidentiality: a.confidentiality,
    integrity: a.integrity,
    availability: a.availability,
    criticality: a.criticality,
    potential_liabilities: a.potential_liabilities || "",
    review_frequency: a.review_frequency,
    next_review_date: a.next_review_date || "",
    workflow_status: a.workflow_status,
    classification_ids: a.classifications.map((c) => c.id),
    process_ids: a.processes.map((r) => r.id),
    legal_ids: a.legals.map((r) => r.id),
    requirement_ids: a.requirements.map((r) => r.id),
    incident_ids: a.incidents.map((r) => r.id),
    exception_ids: a.exceptions.map((r) => r.id),
    related_ids: a.related_assets.map((r) => r.id),
    risk_ids: a.risks.map((r) => r.id),
  };
}

/** Strip empty strings on the optional FK fields so the API receives null instead of "". */
function toPayload(f: FormState) {
  return {
    name: f.name,
    description: f.description,
    media_type_id: f.media_type_id || null,
    label_id: f.label_id || null,
    owner_id: f.owner_id || null,
    guardian_id: f.guardian_id || null,
    user_id: f.user_id || null,
    confidentiality: f.confidentiality,
    integrity: f.integrity,
    availability: f.availability,
    criticality: f.criticality,
    potential_liabilities: f.potential_liabilities,
    review_frequency: f.review_frequency,
    next_review_date: f.next_review_date || null,
    workflow_status: f.workflow_status,
    classification_ids: f.classification_ids,
    process_ids: f.process_ids,
    legal_ids: f.legal_ids,
    requirement_ids: f.requirement_ids,
    incident_ids: f.incident_ids,
    exception_ids: f.exception_ids,
    related_ids: f.related_ids,
    risk_ids: f.risk_ids,
  };
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [open, setOpen] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);

  // lookups / relation sources
  const [mediaTypes, setMediaTypes] = useState<MediaType[]>([]);
  const [labels, setLabels] = useState<LabelRow[]>([]);
  const [classTypes, setClassTypes] = useState<ClassType[]>([]);
  const [units, setUnits] = useState<BusinessUnit[]>([]);
  const [processes, setProcesses] = useState<NamedRow[]>([]);
  const [legals, setLegals] = useState<RefRow[]>([]);
  const [requirements, setRequirements] = useState<RefRow[]>([]);
  const [incidents, setIncidents] = useState<RefRow[]>([]);
  const [exceptions, setExceptions] = useState<RefRow[]>([]);
  const [risks, setRisks] = useState<RefRow[]>([]);

  // form
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      const a = await apiCall<Page<Asset>>("GET", "/assets?limit=200");
      setAssets(a.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load assets");
    }
  }

  async function loadLookups() {
    const ignore = () => {};
    apiCall<MediaType[]>("GET", "/asset-media-types").then(setMediaTypes).catch(ignore);
    apiCall<LabelRow[]>("GET", "/asset-labels").then(setLabels).catch(ignore);
    apiCall<ClassType[]>("GET", "/asset-classification-types").then(setClassTypes).catch(ignore);
    apiCall<Page<BusinessUnit>>("GET", "/business-units").then((r) => setUnits(r.items)).catch(ignore);
    apiCall<Page<NamedRow>>("GET", "/processes").then((r) => setProcesses(r.items)).catch(ignore);
    apiCall<Page<RefRow>>("GET", "/legals").then((r) => setLegals(r.items)).catch(ignore);
    apiCall<Page<RefRow>>("GET", "/incidents?limit=200").then((r) => setIncidents(r.items)).catch(ignore);
    apiCall<Page<RefRow>>("GET", "/exceptions?limit=200").then((r) => setExceptions(r.items)).catch(ignore);
    apiCall<Page<RefRow>>("GET", "/risks?limit=200").then((r) => setRisks(r.items)).catch(ignore);
    // Requirements have no flat list endpoint — gather them per framework.
    apiCall<Page<Framework>>("GET", "/frameworks")
      .then(async (fw) => {
        const lists = await Promise.all(
          fw.items.map((x) =>
            apiCall<RefRow[]>("GET", `/frameworks/${x.id}/requirements`).catch(() => [] as RefRow[]),
          ),
        );
        setRequirements(lists.flat());
      })
      .catch(ignore);
  }

  useEffect(() => {
    load();
    loadLookups();
  }, []);

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

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Asset>("PATCH", `/assets/${editing.id}`, payload);
      else await apiCall<Asset>("POST", "/assets", payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save asset");
    } finally {
      setSaving(false);
    }
  }

  async function remove(a: Asset) {
    if (!window.confirm(`Archive asset "${a.name}"? It will be removed from the inventory.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/assets/${a.id}`);
      if (open?.id === a.id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete asset");
    }
  }

  /* ------------------------------------------------------------- options */
  const mediaTypeOpts: Option[] = useMemo(
    () => mediaTypes.map((m) => ({ value: m.id, label: m.name })),
    [mediaTypes],
  );
  const labelOpts: Option[] = useMemo(() => labels.map((l) => ({ value: l.id, label: l.name })), [labels]);
  const unitOpts: Option[] = useMemo(() => units.map((u) => ({ value: u.id, label: u.name })), [units]);
  const classOpts: Option[] = useMemo(
    () =>
      classTypes.flatMap((t) =>
        t.classifications.map((c) => ({
          value: c.id,
          label: `${t.name}: ${c.name}`,
          sub: `value ${c.value}`,
        })),
      ),
    [classTypes],
  );
  const processOpts: Option[] = useMemo(() => processes.map((p) => ({ value: p.id, label: p.name })), [processes]);
  const legalOpts: Option[] = useMemo(
    () => legals.map((l) => ({ value: l.id, label: refLabel(l), sub: l.reference })),
    [legals],
  );
  const requirementOpts: Option[] = useMemo(
    () => requirements.map((r) => ({ value: r.id, label: refLabel(r), sub: r.reference })),
    [requirements],
  );
  const incidentOpts: Option[] = useMemo(
    () => incidents.map((i) => ({ value: i.id, label: refLabel(i), sub: i.reference })),
    [incidents],
  );
  const exceptionOpts: Option[] = useMemo(
    () => exceptions.map((x) => ({ value: x.id, label: refLabel(x), sub: x.reference })),
    [exceptions],
  );
  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: refLabel(r), sub: r.reference })),
    [risks],
  );
  const relatedOpts: Option[] = useMemo(
    () => assets.filter((a) => a.id !== editing?.id).map((a) => ({ value: a.id, label: a.name })),
    [assets, editing],
  );

  const linkCount = (a: Asset) =>
    a.processes.length +
    a.legals.length +
    a.requirements.length +
    a.incidents.length +
    a.exceptions.length +
    a.related_assets.length +
    a.risks.length;

  /* --------------------------------------------------------------- tabs */
  const generalTab = (
    <>
      <Field label="Name" required help="For example: Customer Database, Payroll System, Office HVAC, etc.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Customer Database" required />
      </Field>
      <Field label="Description">
        <TextArea
          value={f.description}
          onChange={(v) => set("description", v)}
          rows={3}
          placeholder="What this asset is, where it lives and why it matters."
        />
      </Field>
      <div className="field-row">
        <Field label="Media Type" help="The asset taxonomy (Data Asset, Hardware, Software, People…).">
          <Select value={f.media_type_id} onChange={(v) => set("media_type_id", v)} options={mediaTypeOpts} placeholder="— none —" />
        </Field>
        <Field label="Handling Label" help="Reusable handling/sensitivity label (Public, Confidential, PII…).">
          <Select value={f.label_id} onChange={(v) => set("label_id", v)} options={labelOpts} placeholder="— none —" />
        </Field>
        <Field label="Criticality">
          <Select value={f.criticality} onChange={(v) => set("criticality", v)} options={CRIT} />
        </Field>
      </div>
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
      <Field label="Workflow Status" help="Approval lifecycle for this asset record.">
        <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  const classificationTab = (
    <>
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
      <Field
        label="Classifications"
        help="Named values from your classification scheme (e.g. Confidentiality: Restricted). Manage the scheme under classification types."
      >
        <MultiSelect value={f.classification_ids} onChange={(v) => set("classification_ids", v)} options={classOpts} />
      </Field>
      <Field label="Potential Liabilities" help="Legal / financial exposure if this asset is compromised.">
        <TextArea
          value={f.potential_liabilities}
          onChange={(v) => set("potential_liabilities", v)}
          rows={3}
          placeholder="Regulatory fines, contractual penalties, reputational damage…"
        />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Business Processes" help="Processes that depend on or use this asset.">
        <MultiSelect value={f.process_ids} onChange={(v) => set("process_ids", v)} options={processOpts} />
      </Field>
      <Field label="Legal Obligations" help="Laws / regulations applicable to this asset.">
        <MultiSelect value={f.legal_ids} onChange={(v) => set("legal_ids", v)} options={legalOpts} />
      </Field>
      <Field label="Compliance Requirements" help="Framework requirements this asset is in scope for.">
        <MultiSelect value={f.requirement_ids} onChange={(v) => set("requirement_ids", v)} options={requirementOpts} />
      </Field>
      <Field label="Risks" help="Risks registered against this asset.">
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
      <Field label="Incidents" help="Incidents that affected this asset.">
        <MultiSelect value={f.incident_ids} onChange={(v) => set("incident_ids", v)} options={incidentOpts} />
      </Field>
      <Field label="Exceptions" help="Risk / policy exceptions raised for this asset.">
        <MultiSelect value={f.exception_ids} onChange={(v) => set("exception_ids", v)} options={exceptionOpts} />
      </Field>
      <Field label="Related Assets" help="Other assets this one depends on or is connected to.">
        <MultiSelect value={f.related_ids} onChange={(v) => set("related_ids", v)} options={relatedOpts} />
      </Field>
    </>
  );

  const reviewTab = (
    <>
      <div className="field-row">
        <Field label="Review Frequency" help="How often this asset's classification / ownership is re-attested.">
          <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
        </Field>
        <Field label="Next Review Date" help="Leave blank to auto-schedule from the frequency.">
          <TextInput type="date" value={f.next_review_date} onChange={(v) => set("next_review_date", v)} />
        </Field>
      </div>
      {editing && (
        <Field label="Review History">
          {editing.reviews.length === 0 ? (
            <div className="help">No reviews recorded yet.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Scheduled</th>
                    <th>Status</th>
                    <th>Actual</th>
                    <th>Outcome</th>
                    <th>Reviewer</th>
                  </tr>
                </thead>
                <tbody>
                  {editing.reviews.map((r) => (
                    <tr key={r.id}>
                      <td className="muted">{r.scheduled_date}</td>
                      <td><Badge tone="neutral" plain>{cap(r.status)}</Badge></td>
                      <td className="muted">{r.actual_date || "—"}</td>
                      <td className="muted">{r.outcome || "—"}</td>
                      <td className="muted">{r.reviewer || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Field>
      )}
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Asset Management</h1>
          <p>Inventory with media types, CIA classification, RACI ownership, review cycles and cross-links.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="assets" label="Assets" onDone={load} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add asset
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Assets</h3>
          <span className="sub">{assets.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Media type</th>
                <th>Criticality</th>
                <th>C / I / A</th>
                <th>Owner</th>
                <th>Guardian</th>
                <th>Label</th>
                <th>Links</th>
                <th>Review</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {assets.map((a) => (
                <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => openEdit(a)}>
                  <td className="cell-title">{a.name}</td>
                  <td>{a.media_type ? <Badge tone="info" plain>{a.media_type.label}</Badge> : <span className="muted">—</span>}</td>
                  <td><Badge tone={CRIT_TONE[a.criticality] || "neutral"}>{cap(a.criticality)}</Badge></td>
                  <td>
                    <span style={{ display: "flex", gap: 4 }}>
                      <Severity value={a.confidentiality} />
                      <Severity value={a.integrity} />
                      <Severity value={a.availability} />
                    </span>
                  </td>
                  <td className="muted">{a.owner ? a.owner.label : "—"}</td>
                  <td className="muted">{a.guardian ? a.guardian.label : "—"}</td>
                  <td className="muted">{a.label ? a.label.label : "—"}</td>
                  <td className="muted">{linkCount(a) || "—"}</td>
                  <td>
                    {a.review_status === "overdue" ? (
                      <Badge tone="high">Overdue</Badge>
                    ) : (
                      <span className="muted">{a.next_review_date || "—"}</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => setOpen(open?.id === a.id ? null : a)}>
                        Details
                      </button>
                      <button className="btn secondary sm" onClick={() => remove(a)}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {assets.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconAsset width={24} height={24} /></span>
                      <h3>No assets yet</h3>
                      <p>Create your first asset to build the inventory.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && <RecordPanels model="asset" entityId={open.id} />}

      {showForm && (
        <FormModal
          title={editing ? `Edit asset — ${editing.name}` : "Add item (Assets)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "classification", label: "Classification", content: classificationTab },
            { id: "links", label: "Links & Relations", content: linksTab },
            { id: "review", label: "Review", content: reviewTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create asset"}
        />
      )}
    </>
  );
}
