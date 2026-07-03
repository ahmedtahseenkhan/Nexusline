"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall, type Page, type Control, type Vendor, type Risk, type Asset } from "@/lib/api";
import { Badge, Severity } from "@/components/badges";
import { Field, TextInput, TextArea, Select, MultiSelect, NumberInput, type Option } from "@/components/fields";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import RecordPanels from "@/components/RecordPanels";
import { IconCheck, IconPlus, IconShield } from "@/components/icons";

// ----------------------------------------------------------------- types (inline)
type Ref = { id: string; reference?: string; title?: string; name?: string };

type IncidentStageFull = {
  id: string;
  incident_id: string;
  name: string;
  order_index: number;
  status: string;
  notes: string;
  completed_at: string | null;
};

type RegReport = {
  id: string;
  incident_id: string;
  regulator: string;
  report_type: string;
  deadline: string | null;
  status: string;
  submitted_at: string | null;
  reference: string;
  summary: string;
  submitted_by: string;
  is_overdue: boolean;
  created_at: string;
};

type IncidentFull = {
  id: string;
  reference: string;
  title: string;
  description: string;
  category: string;
  classification: string;
  severity: string;
  status: string;
  workflow_status: string;
  assignee: string;
  reported_by: string;
  impact: string;
  root_cause: string;
  lessons_learned: string;
  cost: number | null;
  detected_at: string | null;
  occurred_at: string | null;
  resolved_at: string | null;
  stage_count: number;
  completed_stages: number;
  lifecycle_complete: boolean;
  current_stage: string | null;
  stages: IncidentStageFull[];
  is_reportable: boolean;
  regulator: string;
  regulatory_reports: RegReport[];
  controls: Ref[];
  vendors: Ref[];
  assets: Ref[];
  risks: Ref[];
  created_at: string;
};

// ----------------------------------------------------------------- option helpers
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const SEVERITY = opts(["low", "medium", "high", "critical"]);
const STATUS = opts(["open", "triage", "investigating", "contained", "resolved", "closed"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  open: "high",
  triage: "medium",
  investigating: "medium",
  contained: "info",
  resolved: "low",
  closed: "neutral",
};
const STAGE_TONE: Record<string, "low" | "medium" | "neutral"> = {
  done: "low",
  in_progress: "medium",
  pending: "neutral",
};

// ----------------------------------------------------------------- form state
type FormState = {
  title: string;
  description: string;
  category: string;
  classification: string;
  severity: string;
  status: string;
  workflow_status: string;
  assignee: string;
  reported_by: string;
  detected_at: string;
  occurred_at: string;
  resolved_at: string;
  impact: string;
  root_cause: string;
  lessons_learned: string;
  cost: number | "";
  control_ids: string[];
  vendor_ids: string[];
  asset_ids: string[];
  risk_ids: string[];
};

const BLANK: FormState = {
  title: "", description: "", category: "", classification: "",
  severity: "medium", status: "open", workflow_status: "draft",
  assignee: "", reported_by: "",
  detected_at: "", occurred_at: "", resolved_at: "",
  impact: "", root_cause: "", lessons_learned: "", cost: "",
  control_ids: [], vendor_ids: [], asset_ids: [], risk_ids: [],
};

function fromIncident(i: IncidentFull): FormState {
  return {
    title: i.title,
    description: i.description || "",
    category: i.category || "",
    classification: i.classification || "",
    severity: i.severity,
    status: i.status,
    workflow_status: i.workflow_status,
    assignee: i.assignee || "",
    reported_by: i.reported_by || "",
    detected_at: i.detected_at || "",
    occurred_at: i.occurred_at || "",
    resolved_at: i.resolved_at || "",
    impact: i.impact || "",
    root_cause: i.root_cause || "",
    lessons_learned: i.lessons_learned || "",
    cost: i.cost ?? "",
    control_ids: i.controls.map((r) => r.id),
    vendor_ids: i.vendors.map((r) => r.id),
    asset_ids: i.assets.map((r) => r.id),
    risk_ids: i.risks.map((r) => r.id),
  };
}

/** Strip empty-string dates/cost to null so the backend's optional fields stay null. */
function toPayload(f: FormState) {
  return {
    title: f.title,
    description: f.description,
    category: f.category,
    classification: f.classification,
    severity: f.severity,
    status: f.status,
    workflow_status: f.workflow_status,
    assignee: f.assignee,
    reported_by: f.reported_by,
    detected_at: f.detected_at || null,
    occurred_at: f.occurred_at || null,
    resolved_at: f.resolved_at || null,
    impact: f.impact,
    root_cause: f.root_cause,
    lessons_learned: f.lessons_learned,
    cost: f.cost === "" ? null : f.cost,
    control_ids: f.control_ids,
    vendor_ids: f.vendor_ids,
    asset_ids: f.asset_ids,
    risk_ids: f.risk_ids,
  };
}

export default function IncidentsPage() {
  const [items, setItems] = useState<IncidentFull[]>([]);
  const [controls, setControls] = useState<Control[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [open, setOpen] = useState<IncidentFull | null>(null); // lifecycle/detail row
  const [editing, setEditing] = useState<IncidentFull | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load(keepOpen?: string) {
    try {
      const list = (await apiCall<Page<IncidentFull>>("GET", "/incidents?limit=200")).items;
      setItems(list);
      if (keepOpen) setOpen(list.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
    apiCall<Page<Control>>("GET", "/controls?limit=200").then((r) => setControls(r.items)).catch(() => {});
    apiCall<Page<Vendor>>("GET", "/vendors?limit=200").then((r) => setVendors(r.items)).catch(() => {});
    apiCall<Page<Risk>>("GET", "/risks?limit=200").then((r) => setRisks(r.items)).catch(() => {});
    apiCall<Page<Asset>>("GET", "/assets?limit=200").then((r) => setAssets(r.items)).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  function openEdit(i: IncidentFull) {
    setEditing(i);
    setF(fromIncident(i));
    setError(null);
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<IncidentFull>("PATCH", `/incidents/${editing.id}`, payload);
      else await apiCall<IncidentFull>("POST", "/incidents", payload);
      setShowForm(false);
      await load(open?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save incident");
    } finally {
      setSaving(false);
    }
  }

  async function remove(i: IncidentFull) {
    if (!window.confirm(`Delete incident ${i.reference}? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/incidents/${i.id}`);
      if (open?.id === i.id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete incident");
    }
  }

  async function advance(stageId: string, status: string) {
    if (!open) return;
    setError(null);
    try {
      await apiCall<IncidentFull>("PATCH", `/incidents/${open.id}/stages/${stageId}`, { status });
      await load(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update stage");
    }
  }

  async function regAction(fn: Promise<unknown>) {
    if (!open) return;
    setError(null);
    try {
      await fn;
      await load(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }
  function generateRegReports() {
    if (!open) return;
    regAction(apiCall("POST", `/incidents/${open.id}/regulatory-reports/generate`));
  }
  function markReportSubmitted(reportId: string) {
    const ref = window.prompt("Regulator acknowledgement reference (optional):") ?? "";
    regAction(apiCall("PATCH", `/regulatory-reports/${reportId}`, { status: "submitted", reference: ref }));
  }
  function deleteRegReport(reportId: string) {
    regAction(apiCall("DELETE", `/regulatory-reports/${reportId}`));
  }

  const controlOpts: Option[] = useMemo(
    () => controls.map((c) => ({ value: c.id, label: c.name, sub: c.reference })),
    [controls],
  );
  const vendorOpts: Option[] = useMemo(
    () => vendors.map((v) => ({ value: v.id, label: v.name, sub: v.category })),
    [vendors],
  );
  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: r.title, sub: r.reference })),
    [risks],
  );
  const assetOpts: Option[] = useMemo(
    () => assets.map((a) => ({ value: a.id, label: a.name, sub: a.classification })),
    [assets],
  );

  const linkCount = (i: IncidentFull) =>
    i.controls.length + i.vendors.length + i.assets.length + i.risks.length;

  // ------------------------------------------------------------- tabs
  const generalTab = (
    <>
      <Field label="Title" required help="A short, descriptive name for the incident.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Suspicious login from unknown IP" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What happened, who detected it, and the initial scope." />
      </Field>
      <div className="field-row">
        <Field label="Type / Category">
          <TextInput value={f.category} onChange={(v) => set("category", v)} placeholder="Phishing" />
        </Field>
        <Field label="Classification" help="Sensitivity of the affected information (e.g. Confidential).">
          <TextInput value={f.classification} onChange={(v) => set("classification", v)} placeholder="Confidential" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Severity">
          <Select value={f.severity} onChange={(v) => set("severity", v)} options={SEVERITY} />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Owner / Handler" help="Person or team responsible for response.">
          <TextInput value={f.assignee} onChange={(v) => set("assignee", v)} placeholder="SOC Team" />
        </Field>
        <Field label="Reported By">
          <TextInput value={f.reported_by} onChange={(v) => set("reported_by", v)} placeholder="Jane Doe" />
        </Field>
      </div>
    </>
  );

  const timelineTab = (
    <>
      <div className="field-row">
        <Field label="Occurred At" help="When the incident actually took place.">
          <TextInput type="date" value={f.occurred_at} onChange={(v) => set("occurred_at", v)} />
        </Field>
        <Field label="Detected At" help="When the incident was first discovered.">
          <TextInput type="date" value={f.detected_at} onChange={(v) => set("detected_at", v)} />
        </Field>
        <Field label="Resolved At" help="When response work was completed.">
          <TextInput type="date" value={f.resolved_at} onChange={(v) => set("resolved_at", v)} />
        </Field>
      </div>
    </>
  );

  const analysisTab = (
    <>
      <Field label="Impact" help="Business / operational impact of the incident.">
        <TextArea value={f.impact} onChange={(v) => set("impact", v)} rows={3} placeholder="Systems affected, data exposed, downtime, etc." />
      </Field>
      <Field label="Estimated Cost" help="Financial impact in your reporting currency.">
        <NumberInput value={f.cost} onChange={(v) => set("cost", v)} min={0} step={100} placeholder="0" />
      </Field>
      <Field label="Root Cause">
        <RichText value={f.root_cause} onChange={(v) => set("root_cause", v)} placeholder="Describe the underlying cause…" />
      </Field>
      <Field label="Lessons Learned">
        <RichText value={f.lessons_learned} onChange={(v) => set("lessons_learned", v)} placeholder="What will change to prevent recurrence…" />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Related Controls" help="Controls that failed, were tested, or mitigate this incident.">
        <MultiSelect value={f.control_ids} onChange={(v) => set("control_ids", v)} options={controlOpts} />
      </Field>
      <Field label="Related Vendors" help="Third parties involved in or affected by the incident.">
        <MultiSelect value={f.vendor_ids} onChange={(v) => set("vendor_ids", v)} options={vendorOpts} />
      </Field>
      <Field label="Related Risks" help="Risks this incident realised or relates to.">
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
      <Field label="Affected Assets" help="Assets impacted by the incident.">
        <MultiSelect value={f.asset_ids} onChange={(v) => set("asset_ids", v)} options={assetOpts} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Security Operations</h1>
          <p>Log, triage and resolve security incidents through their response lifecycle.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="incidents" label="Incidents" onDone={() => load()} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add incident
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Incidents</h3>
          <span className="sub">{items.length} total · click a row to edit</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Type</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Detected</th>
                <th>Owner</th>
                <th>Links</th>
                <th>Lifecycle</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.id} style={{ cursor: "pointer" }} onClick={() => openEdit(i)}>
                  <td className="ref">{i.reference}</td>
                  <td className="cell-title">{i.title}</td>
                  <td className="muted">{i.category || "—"}</td>
                  <td><Severity value={i.severity} /></td>
                  <td><Badge tone={STATUS_TONE[i.status] || "neutral"}>{cap(i.status)}</Badge></td>
                  <td className="muted">{i.detected_at || "—"}</td>
                  <td className="muted">{i.assignee || "—"}</td>
                  <td className="muted">{linkCount(i) || "—"}</td>
                  <td style={{ minWidth: 150 }}>
                    {i.lifecycle_complete ? (
                      <Badge tone="low"><IconCheck width={11} height={11} /> complete</Badge>
                    ) : (
                      <>
                        <div className="progress"><span style={{ width: `${(i.completed_stages / (i.stage_count || 1)) * 100}%` }} /></div>
                        <span className="muted" style={{ fontSize: 11 }}>{i.current_stage || "—"} ({i.completed_stages}/{i.stage_count})</span>
                      </>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => setOpen(open?.id === i.id ? null : i)}>
                        Lifecycle
                      </button>
                      <button className="btn secondary sm" onClick={() => remove(i)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconShield width={24} height={24} /></span>
                      <h3>No incidents</h3>
                      <p>Log your first security incident to begin tracking.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (<>
        <div className="card">
          <div className="card-head">
            <h3>Response lifecycle · {open.reference}</h3>
            <span className="sub">{open.completed_stages}/{open.stage_count} stages done</span>
          </div>
          <div className="card-pad">
            {open.stages.map((s) => (
              <div key={s.id} className="activity-item" style={{ alignItems: "center" }}>
                <span style={{ width: 24, textAlign: "center", color: "var(--faint)" }}>{s.order_index + 1}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13 }}>{s.name}</div>
                  {s.completed_at && <div className="when">completed {s.completed_at}</div>}
                </div>
                <Badge tone={STAGE_TONE[s.status] || "neutral"}>{s.status.replace(/_/g, " ")}</Badge>
                <div style={{ display: "flex", gap: 6 }}>
                  {s.status === "pending" && <button className="btn secondary sm" onClick={() => advance(s.id, "in_progress")}>Start</button>}
                  {s.status !== "done" && <button className="btn sm" onClick={() => advance(s.id, "done")}>Done</button>}
                  {s.status === "done" && <button className="btn secondary sm" onClick={() => advance(s.id, "in_progress")}>Reopen</button>}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h3>Regulatory reporting</h3>
            <span className="sub">
              {open.is_reportable ? `Reportable to ${open.regulator || "regulator"}` : "Not flagged reportable"}
            </span>
          </div>
          <div className="card-pad">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <p className="muted" style={{ fontSize: 12.5, margin: 0, maxWidth: 460 }}>
                Generate the standard {open.regulator || "SBP"} submissions (initial notification + final report)
                with SLA deadlines computed from the detection date.
              </p>
              <button className="btn secondary sm" onClick={generateRegReports}>Generate {open.regulator || "SBP"} reports</button>
            </div>
            {open.regulatory_reports.length > 0 ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Regulator</th><th>Report</th><th>Deadline</th><th>Status</th><th>Reference</th><th></th></tr></thead>
                  <tbody>
                    {open.regulatory_reports.map((r) => (
                      <tr key={r.id}>
                        <td className="muted">{r.regulator}</td>
                        <td className="cell-title">{cap(r.report_type)}</td>
                        <td className="muted">
                          {r.deadline || "—"}
                          {r.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="critical">overdue</Badge></span>}
                        </td>
                        <td><Badge tone={r.status === "pending" ? "medium" : "low"}>{cap(r.status)}</Badge></td>
                        <td className="muted">{r.reference || "—"}</td>
                        <td>
                          <div style={{ display: "flex", gap: 6 }}>
                            {r.status === "pending" && <button className="btn sm" onClick={() => markReportSubmitted(r.id)}>Mark submitted</button>}
                            <button className="btn secondary sm" onClick={() => deleteRegReport(r.id)}>Remove</button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <span className="muted" style={{ fontSize: 12.5 }}>No regulatory reports yet.</span>
            )}
          </div>
        </div>

        <RecordPanels model="incident" entityId={open.id} />
        </>
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit incident — ${editing.reference}` : "Add item (Incidents)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "timeline", label: "Timeline", content: timelineTab },
            { id: "analysis", label: "Analysis", content: analysisTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create incident"}
        />
      )}
    </>
  );
}
