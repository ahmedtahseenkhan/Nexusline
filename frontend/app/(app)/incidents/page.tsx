"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
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
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

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

const refToOpt = (x: Ref): AsyncOption => ({ value: x.id, label: x.title || x.name || x.reference || x.id });

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
  control_ids: AsyncOption[];
  vendor_ids: AsyncOption[];
  asset_ids: AsyncOption[];
  risk_ids: AsyncOption[];
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
    control_ids: i.controls.map(refToOpt),
    vendor_ids: i.vendors.map(refToOpt),
    asset_ids: i.assets.map(refToOpt),
    risk_ids: i.risks.map(refToOpt),
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
    control_ids: f.control_ids.map((o) => o.value),
    vendor_ids: f.vendor_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
    risk_ids: f.risk_ids.map((o) => o.value),
  };
}

/* ================================================================ page ===== */
function IncidentsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<IncidentFull | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // filters
  const [fStatus, setFStatus] = useState("");
  const [fSeverity, setFSeverity] = useState("");

  const [editing, setEditing] = useState<IncidentFull | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchIncidents = useCallback((qs: string) => apiCall<PagedList<IncidentFull>>("GET", `/incidents?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<IncidentFull>("GET", `/incidents/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // server typeahead sources for the form link pickers
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.reference })));
  const searchVendors = (q: string) => apiCall<PagedList<{ id: string; name: string; category: string }>>("GET", `/vendors?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.category })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string; classification: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.classification })));

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(i: IncidentFull) { setEditing(i); setF(fromIncident(i)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<IncidentFull>("PATCH", `/incidents/${editing.id}`, payload);
      else await apiCall<IncidentFull>("POST", "/incidents", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Incident logged");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save incident"); }
    finally { setSaving(false); }
  }

  async function remove(i: IncidentFull) {
    if (!(await confirmDialog({ title: `Delete incident ${i.reference}?`, message: "This cannot be undone.", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/incidents/${i.id}`);
      if (openId === i.id) setOpenId(null);
      reload(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete incident"); }
  }

  async function advance(stageId: string, status: string) {
    if (!detail) return;
    setError(null);
    try {
      await apiCall<IncidentFull>("PATCH", `/incidents/${detail.id}/stages/${stageId}`, { status });
      loadDetail(detail.id); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to update stage"); }
  }

  async function regAction(fn: Promise<unknown>) {
    if (!detail) return;
    setError(null);
    try {
      await fn;
      loadDetail(detail.id); reload();
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); }
  }
  function generateRegReports() {
    if (!detail) return;
    regAction(apiCall("POST", `/incidents/${detail.id}/regulatory-reports/generate`));
  }
  function markReportSubmitted(reportId: string) {
    const ref = window.prompt("Regulator acknowledgement reference (optional):") ?? "";
    regAction(apiCall("PATCH", `/regulatory-reports/${reportId}`, { status: "submitted", reference: ref }));
  }
  function deleteRegReport(reportId: string) {
    regAction(apiCall("DELETE", `/regulatory-reports/${reportId}`));
  }

  const linkCount = (i: IncidentFull) =>
    i.controls.length + i.vendors.length + i.assets.length + i.risks.length;

  const columns: Column<IncidentFull>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (i) => <span className="ref">{i.reference}</span> },
    { key: "title", header: "Title", sortable: true, render: (i) => <span className="cell-title">{i.title}</span> },
    { key: "category", header: "Type", sortable: true, render: (i) => <span className="muted">{i.category || "—"}</span> },
    { key: "severity", header: "Severity", sortable: true, render: (i) => <Severity value={i.severity} /> },
    { key: "status", header: "Status", sortable: true, render: (i) => <Badge tone={STATUS_TONE[i.status] || "neutral"}>{cap(i.status)}</Badge> },
    { key: "detected_at", header: "Detected", sortable: true, render: (i) => <span className="muted">{i.detected_at || "—"}</span> },
    { key: "assignee", header: "Owner", render: (i) => <span className="muted">{i.assignee || "—"}</span> },
    { key: "links", header: "Links", align: "center", render: (i) => <span className="muted">{linkCount(i) || "—"}</span> },
    {
      key: "lifecycle", header: "Lifecycle", width: 150, render: (i) => (
        i.lifecycle_complete ? (
          <Badge tone="low"><IconCheck width={11} height={11} /> complete</Badge>
        ) : (
          <>
            <div className="progress"><span style={{ width: `${(i.completed_stages / (i.stage_count || 1)) * 100}%` }} /></div>
            <span className="muted" style={{ fontSize: 11 }}>{i.current_stage || "—"} ({i.completed_stages}/{i.stage_count})</span>
          </>
        )
      ),
    },
    { key: "actions", header: "", render: (i) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(i)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(i)}>Delete</button></div> },
  ];

  const filters = { status: fStatus || undefined, severity: fSeverity || undefined };

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
        <AsyncMultiSelect search={searchControls} value={f.control_ids} onChange={(v) => set("control_ids", v)} />
      </Field>
      <Field label="Related Vendors" help="Third parties involved in or affected by the incident.">
        <AsyncMultiSelect search={searchVendors} value={f.vendor_ids} onChange={(v) => set("vendor_ids", v)} />
      </Field>
      <Field label="Related Risks" help="Risks this incident realised or relates to.">
        <AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} />
      </Field>
      <Field label="Affected Assets" help="Assets impacted by the incident.">
        <AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
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
          <ImportExport resource="incidents" label="Incidents" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add incident
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<IncidentFull>
        columns={columns}
        fetcher={fetchIncidents}
        rowKey={(i) => i.id}
        onRowClick={(i) => setOpenId(i.id)}
        activeKey={openId}
        searchPlaceholder="Search incidents by title or reference…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        filters={filters}
        toolbarRight={
          <>
            <select className="select" style={{ maxWidth: 170 }} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
              <option value="">All statuses</option>
              {STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <select className="select" style={{ maxWidth: 150 }} value={fSeverity} onChange={(e) => setFSeverity(e.target.value)}>
              <option value="">All severities</option>
              {SEVERITY.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
          </>
        }
        emptyMessage="No incidents yet. Log your first security incident to begin tracking."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? `${cap(detail.status)} · ${detail.assignee || "no owner"}` : ""}
        width={760}
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
              <Severity value={detail.severity} />
              <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {linkCount(detail) > 0 && <Badge tone="neutral" plain>{linkCount(detail)} links</Badge>}
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head">
                <h3>Response lifecycle</h3>
                <span className="sub">{detail.completed_stages}/{detail.stage_count} stages done</span>
              </div>
              <div className="card-pad">
                {detail.stages.map((s) => (
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

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head">
                <h3>Regulatory reporting</h3>
                <span className="sub">
                  {detail.is_reportable ? `Reportable to ${detail.regulator || "regulator"}` : "Not flagged reportable"}
                </span>
              </div>
              <div className="card-pad">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, gap: 10 }}>
                  <p className="muted" style={{ fontSize: 12.5, margin: 0, maxWidth: 460 }}>
                    Generate the standard {detail.regulator || "SBP"} submissions (initial notification + final report)
                    with SLA deadlines computed from the detection date.
                  </p>
                  <button className="btn secondary sm" onClick={generateRegReports}>Generate {detail.regulator || "SBP"} reports</button>
                </div>
                {detail.regulatory_reports.length > 0 ? (
                  <div className="table-wrap">
                    <table>
                      <thead><tr><th>Regulator</th><th>Report</th><th>Deadline</th><th>Status</th><th>Reference</th><th></th></tr></thead>
                      <tbody>
                        {detail.regulatory_reports.map((r) => (
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

            <RecordPanels model="incident" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

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

export default function IncidentsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <IncidentsInner />
    </Suspense>
  );
}
