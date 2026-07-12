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
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ---- inline types (mirror backend GoalRead / GoalAuditRead) ----------------
type Ref = { id: string; reference?: string; title?: string; name?: string };

type GoalAudit = {
  id: string;
  goal_id: string;
  result: string;
  planned_date: string | null;
  conducted_date: string | null;
  metric_description: string;
  success_criteria: string;
  result_description: string;
  auditor: string;
  created_at?: string;
};

type Goal = {
  id: string;
  reference: string;
  name: string;
  description: string;
  owner: string;
  status: string;
  audit_metric: string;
  success_criteria: string;
  audit_frequency: string;
  workflow_status: string;
  workflow_owner: string;
  next_audit_date: string | null;
  last_audit_date: string | null;
  audit_count: number;
  last_result: string | null;
  is_audit_overdue: boolean;
  audits: GoalAudit[];
  risks: Ref[];
  projects: Ref[];
  policies: Ref[];
};

// ---- enum tones / option lists ---------------------------------------------
const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  achieved: "low",
  on_track: "info",
  at_risk: "medium",
  off_track: "critical",
  not_started: "neutral",
};
const RESULT_TONE: Record<string, "low" | "critical" | "neutral"> = {
  passed: "low",
  failed: "critical",
  not_assessed: "neutral",
};
const WORKFLOW_TONE: Record<string, "low" | "medium" | "neutral" | "info"> = {
  approved: "low",
  in_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const refToOpt = (r: Ref): AsyncOption => ({ value: r.id, label: r.title || r.name || r.reference || r.id, sub: r.reference });

const STATUS = opts(["not_started", "on_track", "at_risk", "off_track", "achieved"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const RESULT = opts(["not_assessed", "passed", "failed"]);

// ---- form state -------------------------------------------------------------
type FormState = {
  name: string;
  description: string;
  owner: string;
  status: string;
  workflow_status: string;
  workflow_owner: string;
  audit_frequency: string;
  next_audit_date: string;
  audit_metric: string;
  success_criteria: string;
  risk_ids: AsyncOption[];
  project_ids: AsyncOption[];
  policy_ids: AsyncOption[];
};

const BLANK: FormState = {
  name: "",
  description: "",
  owner: "",
  status: "not_started",
  workflow_status: "draft",
  workflow_owner: "",
  audit_frequency: "annual",
  next_audit_date: "",
  audit_metric: "",
  success_criteria: "",
  risk_ids: [],
  project_ids: [],
  policy_ids: [],
};

function fromGoal(g: Goal): FormState {
  return {
    name: g.name,
    description: g.description || "",
    owner: g.owner || "",
    status: g.status,
    workflow_status: g.workflow_status || "draft",
    workflow_owner: g.workflow_owner || "",
    audit_frequency: g.audit_frequency,
    next_audit_date: g.next_audit_date || "",
    audit_metric: g.audit_metric || "",
    success_criteria: g.success_criteria || "",
    risk_ids: g.risks.map(refToOpt),
    project_ids: g.projects.map(refToOpt),
    policy_ids: g.policies.map(refToOpt),
  };
}

function toPayload(f: FormState): Record<string, unknown> {
  return {
    name: f.name,
    description: f.description,
    owner: f.owner,
    status: f.status,
    workflow_status: f.workflow_status,
    workflow_owner: f.workflow_owner,
    audit_frequency: f.audit_frequency,
    next_audit_date: f.next_audit_date || null,
    audit_metric: f.audit_metric,
    success_criteria: f.success_criteria,
    risk_ids: f.risk_ids.map((o) => o.value),
    project_ids: f.project_ids.map((o) => o.value),
    policy_ids: f.policy_ids.map((o) => o.value),
  };
}

type AuditDraft = {
  result: string;
  conducted_date: string;
  auditor: string;
  result_description: string;
  metric_description: string;
  success_criteria: string;
};
const BLANK_AUDIT: AuditDraft = {
  result: "passed",
  conducted_date: "",
  auditor: "",
  result_description: "",
  metric_description: "",
  success_criteria: "",
};

const linkCount = (g: Goal) => g.risks.length + g.projects.length + g.policies.length;

/* ================================================================ page ===== */
function GoalsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Goal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [editing, setEditing] = useState<Goal | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const [ad, setAd] = useState<AuditDraft>(BLANK_AUDIT);
  const setA = <K extends keyof AuditDraft>(k: K, v: AuditDraft[K]) => setAd((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchGoals = useCallback((qs: string) => apiCall<PagedList<Goal>>("GET", `/goals?${qs}`), []);

  const loadDetail = useCallback((id: string) => {
    apiCall<Goal>("GET", `/goals/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  // server typeahead pickers
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchProjects = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/projects?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  function openEdit(g: Goal) {
    setEditing(g);
    setF(fromGoal(g));
    setError(null);
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Goal>("PATCH", `/goals/${editing.id}`, payload);
      else await apiCall<Goal>("POST", "/goals", payload);
      setShowForm(false);
      reload();
      if (openId) loadDetail(openId);
      toast(editing ? "Changes saved" : "Goal created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save goal");
    } finally {
      setSaving(false);
    }
  }

  async function remove(g: Goal) {
    if (!(await confirmDialog({ title: `Delete goal ${g.reference || g.name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<unknown>("DELETE", `/goals/${g.id}`);
      if (openId === g.id) setOpenId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  async function recordAudit() {
    if (!detail) return;
    setError(null);
    try {
      await apiCall<Goal>("POST", `/goals/${detail.id}/audits`, {
        result: ad.result,
        conducted_date: ad.conducted_date || null,
        auditor: ad.auditor,
        result_description: ad.result_description,
        metric_description: ad.metric_description,
        success_criteria: ad.success_criteria,
      });
      setAd(BLANK_AUDIT);
      loadDetail(detail.id);
      reload();
      toast("Audit recorded");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record audit");
    }
  }

  async function removeAudit(auditId: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Delete this audit?", danger: true }))) return;
    setError(null);
    try {
      await apiCall<Goal>("DELETE", `/goals/${detail.id}/audits/${auditId}`);
      loadDetail(detail.id);
      reload();
      toast("Audit deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete audit");
    }
  }

  const columns: Column<Goal>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (g) => <span className="ref">{g.reference || "—"}</span> },
    { key: "name", header: "Goal", sortable: true, render: (g) => <span className="cell-title">{g.name}</span> },
    { key: "owner", header: "Owner", sortable: true, render: (g) => <span className="muted">{g.owner || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (g) => <Badge tone={STATUS_TONE[g.status] || "neutral"}>{cap(g.status)}</Badge> },
    { key: "workflow_status", header: "Workflow", render: (g) => <Badge tone={WORKFLOW_TONE[g.workflow_status] || "neutral"} plain>{cap(g.workflow_status || "draft")}</Badge> },
    { key: "last_result", header: "Last result", render: (g) => (g.last_result ? <Badge tone={RESULT_TONE[g.last_result] || "neutral"}>{cap(g.last_result)}</Badge> : <span className="muted">—</span>) },
    { key: "audit_count", header: "Audits", align: "center", render: (g) => <span className="muted">{g.audit_count}</span> },
    { key: "links", header: "Links", align: "center", render: (g) => <span className="muted">{linkCount(g) || "—"}</span> },
    { key: "next_audit_date", header: "Next audit", sortable: true, render: (g) => (g.is_audit_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{g.next_audit_date || "—"}</span>) },
    { key: "actions", header: "", render: (g) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(g)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(g)}>Delete</button></div> },
  ];

  // ---- form tabs ------------------------------------------------------------
  const generalTab = (
    <>
      <Field label="Goal" required help="For example: Achieve SOC 2 Type II, Reduce critical findings to zero.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Achieve SOC 2 Type II" required />
      </Field>
      <Field label="Description">
        <RichText value={f.description} onChange={(v) => set("description", v)} />
      </Field>
      <div className="field-row">
        <Field label="Owner / GRC Contact">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="CISO" />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Workflow" help="Approval lifecycle for this goal record.">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Workflow Owner">
          <TextInput value={f.workflow_owner} onChange={(v) => set("workflow_owner", v)} placeholder="Approver" />
        </Field>
      </div>
    </>
  );

  const auditTab = (
    <>
      <div className="field-row">
        <Field label="Audit Frequency" help="How often the goal is assessed pass/fail.">
          <Select value={f.audit_frequency} onChange={(v) => set("audit_frequency", v)} options={FREQ} />
        </Field>
        <Field label="Next Audit Date" help="Leave blank to derive from the frequency.">
          <TextInput type="date" value={f.next_audit_date} onChange={(v) => set("next_audit_date", v)} />
        </Field>
      </div>
      <Field label="Audit Metric" help="What you measure to know the goal is being met.">
        <TextArea value={f.audit_metric} onChange={(v) => set("audit_metric", v)} rows={2} placeholder="e.g. Number of open SOC 2 exceptions." />
      </Field>
      <Field label="Success Criteria" help="The threshold for a passing audit.">
        <TextArea value={f.success_criteria} onChange={(v) => set("success_criteria", v)} rows={2} placeholder="e.g. Zero open exceptions for two consecutive quarters." />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Related Risks" help="Risks this goal helps reduce or mitigate.">
        <AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} />
      </Field>
      <Field label="Related Projects" help="Projects that deliver toward this goal.">
        <AsyncMultiSelect search={searchProjects} value={f.project_ids} onChange={(v) => set("project_ids", v)} />
      </Field>
      <Field label="Related Policies" help="Policies that support or are driven by this goal.">
        <AsyncMultiSelect search={searchPolicies} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Strategy &amp; Goals</h1>
          <p>Strategic goals with a recurring pass/fail audit cycle, linked to the risks, projects and policies that support them.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="goals" label="Goals" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add goal
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Goal>
        columns={columns}
        fetcher={fetchGoals}
        rowKey={(g) => g.id}
        onRowClick={(g) => setOpenId(g.id)}
        activeKey={openId}
        searchPlaceholder="Search goals by name, reference or owner…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No goals yet. Create your first strategic goal to start the audit cycle."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference || ""} ${detail.name}`.trim() : "…"}
        subtitle={detail ? `${cap(detail.status)} · ${detail.owner || "no owner"}` : ""}
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
              <Badge tone={WORKFLOW_TONE[detail.workflow_status] || "neutral"} plain>{cap(detail.workflow_status || "draft")}</Badge>
              {detail.last_result && <Badge tone={RESULT_TONE[detail.last_result] || "neutral"}>{cap(detail.last_result)}</Badge>}
              {linkCount(detail) > 0 && <Badge tone="neutral" plain>{linkCount(detail)} links</Badge>}
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head">
                <h3>Audits</h3>
                <span className="sub">{detail.audit_metric || "no metric defined"}</span>
              </div>
              <div className="card-pad">
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(e) => { e.preventDefault(); recordAudit(); }}
                >
                  <div style={{ width: 130 }}>
                    <label className="label">Result</label>
                    <select className="select" value={ad.result} onChange={(e) => setA("result", e.target.value)}>
                      {RESULT.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label">Conducted</label>
                    <input className="input" type="date" value={ad.conducted_date} onChange={(e) => setA("conducted_date", e.target.value)} />
                  </div>
                  <div style={{ width: 130 }}>
                    <label className="label">Auditor</label>
                    <input className="input" value={ad.auditor} onChange={(e) => setA("auditor", e.target.value)} placeholder="Name" />
                  </div>
                  <div style={{ flex: "1 1 180px" }}>
                    <label className="label">Conclusion</label>
                    <input className="input" value={ad.result_description} onChange={(e) => setA("result_description", e.target.value)} placeholder="Audit conclusion / findings" />
                  </div>
                  <button className="btn">Record</button>
                </form>

                {detail.audits.length ? (
                  detail.audits.map((a) => (
                    <div key={a.id} className="activity-item">
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13 }}>{a.result_description || "Audit"}</div>
                        <div className="when">
                          {a.conducted_date || a.planned_date || "—"} · {a.auditor || "unassigned"}
                        </div>
                      </div>
                      <Badge tone={RESULT_TONE[a.result] || "neutral"}>{cap(a.result)}</Badge>
                      <button className="btn secondary sm" style={{ marginLeft: 8 }} onClick={() => removeAudit(a.id)}>
                        Remove
                      </button>
                    </div>
                  ))
                ) : (
                  <span className="muted">No audits recorded yet.</span>
                )}
              </div>
            </div>

            <RecordPanels model="goal" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit goal — ${editing.reference}` : "Add item (Goals)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "audit", label: "Audit Cycle", content: auditTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create goal"}
        />
      )}
    </>
  );
}

export default function GoalsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <GoalsInner />
    </Suspense>
  );
}
