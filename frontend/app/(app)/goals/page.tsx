"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, MultiSelect, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconGauge, IconPlus } from "@/components/icons";

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

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

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
const refLabel = (r: Ref) => r.title || r.name || r.reference || r.id;

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
  risk_ids: string[];
  project_ids: string[];
  policy_ids: string[];
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
    risk_ids: g.risks.map((r) => r.id),
    project_ids: g.projects.map((r) => r.id),
    policy_ids: g.policies.map((r) => r.id),
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
    risk_ids: f.risk_ids,
    project_ids: f.project_ids,
    policy_ids: f.policy_ids,
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

export default function GoalsPage() {
  const [items, setItems] = useState<Goal[]>([]);
  const [riskOpts, setRiskOpts] = useState<Option[]>([]);
  const [projectOpts, setProjectOpts] = useState<Option[]>([]);
  const [policyOpts, setPolicyOpts] = useState<Option[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Goal | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setF((p) => ({ ...p, [k]: v }));

  // detail / audit management
  const [open, setOpen] = useState<Goal | null>(null);
  const [ad, setAd] = useState<AuditDraft>(BLANK_AUDIT);
  const setA = <K extends keyof AuditDraft>(k: K, v: AuditDraft[K]) =>
    setAd((p) => ({ ...p, [k]: v }));

  async function load(keepOpen?: string) {
    try {
      const g = await apiCall<Page<Goal>>("GET", "/goals?limit=200");
      setItems(g.items);
      if (keepOpen) setOpen(g.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  async function loadOptions() {
    try {
      const [rk, pr, po] = await Promise.all([
        apiCall<Page<{ id: string; title: string; reference: string }>>("GET", "/risks?limit=200"),
        apiCall<Page<{ id: string; title: string; reference: string }>>("GET", "/projects?limit=200"),
        apiCall<Page<{ id: string; title: string; reference: string }>>("GET", "/policies?limit=200"),
      ]);
      setRiskOpts(rk.items.map((r) => ({ value: r.id, label: r.title, sub: r.reference })));
      setProjectOpts(pr.items.map((p) => ({ value: p.id, label: p.title, sub: p.reference })));
      setPolicyOpts(po.items.map((p) => ({ value: p.id, label: p.title, sub: p.reference })));
    } catch {
      /* options are best-effort; the form still works without them */
    }
  }

  useEffect(() => {
    load();
    loadOptions();
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setShowForm(true);
  }
  function openEdit(g: Goal) {
    setEditing(g);
    setF(fromGoal(g));
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
      await load(open?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save goal");
    } finally {
      setSaving(false);
    }
  }

  async function remove(g: Goal) {
    if (!window.confirm(`Delete goal ${g.reference || g.name}?`)) return;
    setError(null);
    try {
      await apiCall<unknown>("DELETE", `/goals/${g.id}`);
      if (open?.id === g.id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  function toggleRow(g: Goal) {
    setOpen(open?.id === g.id ? null : g);
    setAd(BLANK_AUDIT);
  }

  async function recordAudit() {
    if (!open) return;
    setError(null);
    try {
      await apiCall<Goal>("POST", `/goals/${open.id}/audits`, {
        result: ad.result,
        conducted_date: ad.conducted_date || null,
        auditor: ad.auditor,
        result_description: ad.result_description,
        metric_description: ad.metric_description,
        success_criteria: ad.success_criteria,
      });
      setAd(BLANK_AUDIT);
      await load(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record audit");
    }
  }

  async function removeAudit(auditId: string) {
    if (!open) return;
    if (!window.confirm("Delete this audit?")) return;
    setError(null);
    try {
      await apiCall<Goal>("DELETE", `/goals/${open.id}/audits/${auditId}`);
      await load(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete audit");
    }
  }

  const linkCount = (g: Goal) => g.risks.length + g.projects.length + g.policies.length;

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
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
      <Field label="Related Projects" help="Projects that deliver toward this goal.">
        <MultiSelect value={f.project_ids} onChange={(v) => set("project_ids", v)} options={projectOpts} />
      </Field>
      <Field label="Related Policies" help="Policies that support or are driven by this goal.">
        <MultiSelect value={f.policy_ids} onChange={(v) => set("policy_ids", v)} options={policyOpts} />
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
          <ImportExport resource="goals" label="Goals" onDone={() => load()} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add goal
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Goals</h3>
          <span className="sub">{items.length} total · click a row to manage audits</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Goal</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Workflow</th>
                <th>Last result</th>
                <th>Audits</th>
                <th>Links</th>
                <th>Next audit</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((g) => (
                <tr key={g.id} style={{ cursor: "pointer" }} onClick={() => openEdit(g)}>
                  <td className="ref">{g.reference}</td>
                  <td className="cell-title">{g.name}</td>
                  <td className="muted">{g.owner || "—"}</td>
                  <td><Badge tone={STATUS_TONE[g.status] || "neutral"}>{cap(g.status)}</Badge></td>
                  <td><Badge tone={WORKFLOW_TONE[g.workflow_status] || "neutral"} plain>{cap(g.workflow_status || "draft")}</Badge></td>
                  <td>{g.last_result ? <Badge tone={RESULT_TONE[g.last_result] || "neutral"}>{cap(g.last_result)}</Badge> : <span className="muted">—</span>}</td>
                  <td className="muted">{g.audit_count}</td>
                  <td className="muted">{linkCount(g) || "—"}</td>
                  <td className="muted">
                    {g.is_audit_overdue ? <Badge tone="high">Overdue</Badge> : (g.next_audit_date || "—")}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => toggleRow(g)}>
                        {open?.id === g.id ? "Hide" : "Audits"}
                      </button>
                      <button className="btn secondary sm" onClick={() => remove(g)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconGauge width={24} height={24} /></span>
                      <h3>No goals</h3>
                      <p>Create your first strategic goal to start the audit cycle.</p>
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
          <div className="card">
            <div className="card-head">
              <h3>Audits · {open.reference} — {open.name}</h3>
              <span className="sub">{open.audit_metric || "no metric defined"}</span>
            </div>
            <div className="card-pad">
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(e) => { e.preventDefault(); recordAudit(); }}
              >
                <div style={{ width: 140 }}>
                  <label className="label">Result</label>
                  <select className="select" value={ad.result} onChange={(e) => setA("result", e.target.value)}>
                    {RESULT.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                  </select>
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Conducted</label>
                  <input className="input" type="date" value={ad.conducted_date} onChange={(e) => setA("conducted_date", e.target.value)} />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Auditor</label>
                  <input className="input" value={ad.auditor} onChange={(e) => setA("auditor", e.target.value)} placeholder="Name" />
                </div>
                <div style={{ flex: "1 1 220px" }}>
                  <label className="label">Conclusion</label>
                  <input className="input" value={ad.result_description} onChange={(e) => setA("result_description", e.target.value)} placeholder="Audit conclusion / findings" />
                </div>
                <button className="btn">Record audit</button>
              </form>

              {open.audits.length ? (
                open.audits.map((a) => (
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
          <RecordPanels model="goal" entityId={open.id} />
        </>
      )}

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
