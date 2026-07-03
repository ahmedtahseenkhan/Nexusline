"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import {
  Field,
  TextInput,
  TextArea,
  Select,
  MultiSelect,
  NumberInput,
  type Option,
} from "@/components/fields";
import { Badge, EffectivenessBadge, StatusBadge } from "@/components/badges";
import { IconControl, IconPlus } from "@/components/icons";

// ---------------------------------------------------------------- inline types
type LinkRef = { id: string; reference?: string; title?: string; name?: string };

type Control = {
  id: string;
  name: string;
  reference: string;
  description: string;
  objective: string;
  owner: string;
  control_type: string;
  classification: string;
  documentation_url: string;
  status: string;
  effectiveness: string;
  workflow_status: string;
  opex: number | null;
  capex: number | null;
  resource_utilization: number | null;
  audit_frequency: string;
  audit_metric: string;
  audit_success_criteria: string;
  maintenance_frequency: string;
  next_audit_date: string | null;
  last_audit_date: string | null;
  next_maintenance_date: string | null;
  last_maintenance_date: string | null;
  audit_count: number;
  last_audit_result: string | null;
  is_audit_overdue: boolean;
  maintenance_count: number;
  last_maintenance_result: string | null;
  is_maintenance_overdue: boolean;
  policies: LinkRef[];
  requirements: LinkRef[];
  risks: LinkRef[];
};

type ControlAudit = {
  id: string;
  control_id: string;
  result: string;
  planned_date: string | null;
  conducted_date: string | null;
  metric_description: string;
  success_criteria: string;
  result_description: string;
  improvement: string;
  auditor: string;
  created_at: string;
};

type ControlMaintenance = {
  id: string;
  control_id: string;
  result: string;
  task: string;
  planned_date: string | null;
  conducted_date: string | null;
  conclusion: string;
  created_at: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

// ----------------------------------------------------------------- enum options
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const CONTROL_TYPE = opts(["design", "production"]);
const STATUS = opts(["planned", "implemented", "operational", "retired"]);
const EFFECTIVENESS = opts(["not_assessed", "ineffective", "partially_effective", "effective"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const RESULT = opts(["not_assessed", "passed", "failed"]);

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  operational: "low",
  implemented: "info",
  planned: "neutral",
  retired: "neutral",
};
const RESULT_TONE: Record<string, "low" | "critical" | "neutral"> = {
  passed: "low",
  failed: "critical",
  not_assessed: "neutral",
};

function ResultBadge({ value }: { value: string | null }) {
  if (!value || value === "not_assessed") return <span className="muted">—</span>;
  return <Badge tone={RESULT_TONE[value] || "neutral"}>{value}</Badge>;
}

// ------------------------------------------------------------------- form state
type FormState = {
  name: string;
  reference: string;
  objective: string;
  description: string;
  owner: string;
  control_type: string;
  classification: string;
  documentation_url: string;
  status: string;
  effectiveness: string;
  workflow_status: string;
  opex: number | "";
  capex: number | "";
  resource_utilization: number | "";
  audit_frequency: string;
  audit_metric: string;
  audit_success_criteria: string;
  next_audit_date: string;
  maintenance_frequency: string;
  next_maintenance_date: string;
  policy_ids: string[];
  requirement_ids: string[];
  risk_ids: string[];
};

const BLANK: FormState = {
  name: "", reference: "", objective: "", description: "", owner: "",
  control_type: "production", classification: "", documentation_url: "",
  status: "planned", effectiveness: "not_assessed", workflow_status: "draft",
  opex: "", capex: "", resource_utilization: "",
  audit_frequency: "annual", audit_metric: "", audit_success_criteria: "", next_audit_date: "",
  maintenance_frequency: "quarterly", next_maintenance_date: "",
  policy_ids: [], requirement_ids: [], risk_ids: [],
};

function fromControl(c: Control): FormState {
  return {
    name: c.name,
    reference: c.reference || "",
    objective: c.objective || "",
    description: c.description || "",
    owner: c.owner || "",
    control_type: c.control_type,
    classification: c.classification || "",
    documentation_url: c.documentation_url || "",
    status: c.status,
    effectiveness: c.effectiveness,
    workflow_status: c.workflow_status,
    opex: c.opex ?? "",
    capex: c.capex ?? "",
    resource_utilization: c.resource_utilization ?? "",
    audit_frequency: c.audit_frequency,
    audit_metric: c.audit_metric || "",
    audit_success_criteria: c.audit_success_criteria || "",
    next_audit_date: c.next_audit_date || "",
    maintenance_frequency: c.maintenance_frequency,
    next_maintenance_date: c.next_maintenance_date || "",
    policy_ids: c.policies.map((r) => r.id),
    requirement_ids: c.requirements.map((r) => r.id),
    risk_ids: c.risks.map((r) => r.id),
  };
}

// Convert blank-string optionals to null/undefined for the API.
function toPayload(f: FormState) {
  return {
    name: f.name,
    reference: f.reference,
    objective: f.objective,
    description: f.description,
    owner: f.owner,
    control_type: f.control_type,
    classification: f.classification,
    documentation_url: f.documentation_url,
    status: f.status,
    effectiveness: f.effectiveness,
    workflow_status: f.workflow_status,
    opex: f.opex === "" ? null : f.opex,
    capex: f.capex === "" ? null : f.capex,
    resource_utilization: f.resource_utilization === "" ? null : f.resource_utilization,
    audit_frequency: f.audit_frequency,
    audit_metric: f.audit_metric,
    audit_success_criteria: f.audit_success_criteria,
    next_audit_date: f.next_audit_date || null,
    maintenance_frequency: f.maintenance_frequency,
    next_maintenance_date: f.next_maintenance_date || null,
    policy_ids: f.policy_ids,
    requirement_ids: f.requirement_ids,
    risk_ids: f.risk_ids,
  };
}

const linkCount = (c: Control) =>
  c.policies.length + c.requirements.length + c.risks.length;

export default function ControlsPage() {
  const [controls, setControls] = useState<Control[]>([]);
  const [policyOpts, setPolicyOpts] = useState<Option[]>([]);
  const [riskOpts, setRiskOpts] = useState<Option[]>([]);
  const [requirementOpts, setRequirementOpts] = useState<Option[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Expanded row (audit / maintenance test cycles).
  const [open, setOpen] = useState<Control | null>(null);
  const [audits, setAudits] = useState<ControlAudit[]>([]);
  const [maints, setMaints] = useState<ControlMaintenance[]>([]);

  // Edit / create dialog.
  const [editing, setEditing] = useState<Control | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  // Audit / maintenance recording inputs.
  const [auditResult, setAuditResult] = useState("passed");
  const [auditNote, setAuditNote] = useState("");
  const [auditor, setAuditor] = useState("");
  const [maintResult, setMaintResult] = useState("passed");
  const [maintTask, setMaintTask] = useState("");

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setF((p) => ({ ...p, [k]: v }));

  async function load(keepOpen?: string) {
    try {
      const c = await apiCall<Page<Control>>("GET", "/controls?limit=200");
      setControls(c.items);
      if (keepOpen) {
        const k = c.items.find((x) => x.id === keepOpen) || null;
        setOpen(k);
        if (k) await loadCycles(k.id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  async function loadCycles(id: string) {
    const [a, m] = await Promise.all([
      apiCall<ControlAudit[]>("GET", `/controls/${id}/audits`),
      apiCall<ControlMaintenance[]>("GET", `/controls/${id}/maintenances`),
    ]);
    setAudits(a);
    setMaints(m);
  }

  // Load relationship option lists (policies, risks, and requirements across frameworks).
  async function loadOptions() {
    try {
      const [pols, risks, fws] = await Promise.all([
        apiCall<Page<{ id: string; title: string; reference: string }>>("GET", "/policies?limit=200"),
        apiCall<Page<{ id: string; title: string; reference: string }>>("GET", "/risks?limit=200"),
        apiCall<Page<{ id: string; name: string }>>("GET", "/frameworks"),
      ]);
      setPolicyOpts(pols.items.map((p) => ({ value: p.id, label: p.title, sub: p.reference })));
      setRiskOpts(risks.items.map((r) => ({ value: r.id, label: r.title, sub: r.reference })));

      const perFw = await Promise.all(
        fws.items.map((fw) =>
          apiCall<{ id: string; title: string; reference: string }[]>(
            "GET",
            `/frameworks/${fw.id}/requirements`,
          )
            .then((reqs) =>
              reqs.map((r) => ({
                value: r.id,
                label: `${r.reference ? r.reference + " · " : ""}${r.title}`,
                sub: fw.name,
              })),
            )
            .catch(() => []),
        ),
      );
      setRequirementOpts(perFw.flat());
    } catch {
      /* options are best-effort; the form still works without them */
    }
  }

  useEffect(() => {
    load();
    loadOptions();
  }, []);

  async function toggleRow(c: Control) {
    if (open?.id === c.id) {
      setOpen(null);
      return;
    }
    setOpen(c);
    setError(null);
    try {
      await loadCycles(c.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load detail");
    }
  }

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setShowForm(true);
  }
  function openEdit(c: Control) {
    setEditing(c);
    setF(fromControl(c));
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Control>("PATCH", `/controls/${editing.id}`, payload);
      else await apiCall<Control>("POST", "/controls", payload);
      setShowForm(false);
      await load(open?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save control");
    } finally {
      setSaving(false);
    }
  }

  async function remove(c: Control) {
    if (!window.confirm(`Delete control ${c.reference || c.name}?`)) return;
    setError(null);
    try {
      await apiCall<unknown>("DELETE", `/controls/${c.id}`);
      if (open?.id === c.id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  async function recordAudit() {
    if (!open) return;
    setError(null);
    try {
      await apiCall<Control>("POST", `/controls/${open.id}/audits`, {
        result: auditResult,
        result_description: auditNote,
        auditor,
      });
      setAuditNote("");
      setAuditor("");
      await load(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record audit");
    }
  }

  async function recordMaintenance() {
    if (!open) return;
    setError(null);
    try {
      await apiCall<Control>("POST", `/controls/${open.id}/maintenances`, {
        result: maintResult,
        task: maintTask,
      });
      setMaintTask("");
      await load(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record maintenance");
    }
  }

  // ----------------------------------------------------------------- form tabs
  const generalTab = (
    <>
      <div className="field-row">
        <Field label="Name" required help="For example: Multi-factor authentication, Encryption at rest.">
          <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Multi-factor authentication" required />
        </Field>
        <Field label="Reference" help="Framework code, e.g. A.8.5 or AC-2.">
          <TextInput value={f.reference} onChange={(v) => set("reference", v)} placeholder="A.8.5" />
        </Field>
      </div>
      <Field label="Objective" help="What the control is meant to achieve.">
        <TextArea value={f.objective} onChange={(v) => set("objective", v)} rows={2} placeholder="Prevent unauthorised access to production systems." />
      </Field>
      <Field label="Description">
        <RichText value={f.description} onChange={(v) => set("description", v)} placeholder="Describe how the control is implemented and operated…" />
      </Field>
      <div className="field-row">
        <Field label="Owner / GRC Contact">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="CISO" />
        </Field>
        <Field label="Classification" help="Service classification, e.g. Identity & Access.">
          <TextInput value={f.classification} onChange={(v) => set("classification", v)} placeholder="Identity & Access" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Control Type" help="Design artefact vs. in-production control.">
          <Select value={f.control_type} onChange={(v) => set("control_type", v)} options={CONTROL_TYPE} />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Effectiveness">
          <Select value={f.effectiveness} onChange={(v) => set("effectiveness", v)} options={EFFECTIVENESS} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
      <Field label="Documentation URL" help="Link to the runbook, design doc or evidence location.">
        <TextInput value={f.documentation_url} onChange={(v) => set("documentation_url", v)} placeholder="https://docs.example.com/controls/mfa" />
      </Field>
    </>
  );

  const costTab = (
    <>
      <div className="field-row">
        <Field label="OpEx (per year)" help="Operational cost to run this control annually.">
          <NumberInput value={f.opex} onChange={(v) => set("opex", v)} min={0} step={100} placeholder="0" />
        </Field>
        <Field label="CapEx" help="One-off capital cost to implement.">
          <NumberInput value={f.capex} onChange={(v) => set("capex", v)} min={0} step={100} placeholder="0" />
        </Field>
      </div>
      <Field label="Resource Utilization (% FTE)" help="Share of a full-time person needed to operate the control.">
        <NumberInput value={f.resource_utilization} onChange={(v) => set("resource_utilization", v)} min={0} max={100} step={5} placeholder="0" />
      </Field>
    </>
  );

  const auditTab = (
    <>
      <div className="card-pad" style={{ padding: "0 0 8px" }}>
        <strong>Audit cycle</strong>
        <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>
          How the control&apos;s effectiveness is tested and how often.
        </p>
      </div>
      <div className="field-row">
        <Field label="Audit Frequency">
          <Select value={f.audit_frequency} onChange={(v) => set("audit_frequency", v)} options={FREQ} />
        </Field>
        <Field label="Next Audit Date" help="Leave blank to derive from the frequency.">
          <TextInput type="date" value={f.next_audit_date} onChange={(v) => set("next_audit_date", v)} />
        </Field>
      </div>
      <Field label="Audit Metric" help="What you measure to know the control works.">
        <TextArea value={f.audit_metric} onChange={(v) => set("audit_metric", v)} rows={2} placeholder="% of privileged accounts with MFA enforced." />
      </Field>
      <Field label="Audit Success Criteria" help="The threshold for a passing audit.">
        <TextArea value={f.audit_success_criteria} onChange={(v) => set("audit_success_criteria", v)} rows={2} placeholder="100% of privileged accounts enforce MFA." />
      </Field>

      <div className="card-pad" style={{ padding: "16px 0 8px" }}>
        <strong>Maintenance cycle</strong>
        <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>
          Routine upkeep that keeps the control operating.
        </p>
      </div>
      <div className="field-row">
        <Field label="Maintenance Frequency">
          <Select value={f.maintenance_frequency} onChange={(v) => set("maintenance_frequency", v)} options={FREQ} />
        </Field>
        <Field label="Next Maintenance Date" help="Leave blank to derive from the frequency.">
          <TextInput type="date" value={f.next_maintenance_date} onChange={(v) => set("next_maintenance_date", v)} />
        </Field>
      </div>
    </>
  );

  const linksTab = (
    <>
      <Field label="Requirements" help="Framework requirements this control satisfies (map once, comply many).">
        <MultiSelect value={f.requirement_ids} onChange={(v) => set("requirement_ids", v)} options={requirementOpts} />
      </Field>
      <Field label="Policies" help="Policies that mandate or are enforced by this control.">
        <MultiSelect value={f.policy_ids} onChange={(v) => set("policy_ids", v)} options={policyOpts} />
      </Field>
      <Field label="Risks" help="Risks this control mitigates.">
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Control Catalog</h1>
          <p>Reusable controls with cost, effectiveness, framework mappings and recurring audit &amp; maintenance test cycles.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="controls" label="Controls" onDone={() => load()} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add control
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>All controls</h3>
          <span className="sub">{controls.length} total · click a row to expand test cycles</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>Effectiveness</th>
                <th>Owner</th>
                <th>Next audit</th>
                <th>Links</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {controls.map((c) => (
                <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => toggleRow(c)}>
                  <td className="ref">{c.reference || "—"}</td>
                  <td className="cell-title">{c.name}</td>
                  <td><Badge tone="neutral" plain>{cap(c.control_type)}</Badge></td>
                  <td><StatusBadge value={c.status} tone={STATUS_TONE[c.status] === "low" ? "info" : "neutral"} /></td>
                  <td><EffectivenessBadge value={c.effectiveness} /></td>
                  <td className="muted">{c.owner || "—"}</td>
                  <td>
                    {c.is_audit_overdue
                      ? <Badge tone="high">Overdue</Badge>
                      : <span className="muted">{c.next_audit_date || "—"}</span>}
                  </td>
                  <td className="muted">{linkCount(c) || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => openEdit(c)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => remove(c)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {controls.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconControl width={24} height={24} /></span>
                      <h3>No controls yet</h3>
                      <p>Create your first control to build the catalog.</p>
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
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <div className="card">
              <div className="card-head">
                <h3>Audits · {open.reference || open.name}</h3>
                <span className="sub">every {open.audit_frequency}</span>
              </div>
              <div className="card-pad">
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(e) => { e.preventDefault(); recordAudit(); }}
                >
                  <div style={{ width: 130 }}>
                    <label className="label">Result</label>
                    <select className="select" value={auditResult} onChange={(e) => setAuditResult(e.target.value)}>
                      <option value="passed">passed</option>
                      <option value="failed">failed</option>
                    </select>
                  </div>
                  <div style={{ flex: "1 1 160px" }}>
                    <label className="label">Notes</label>
                    <input className="input" value={auditNote} onChange={(e) => setAuditNote(e.target.value)} placeholder="Audit conclusion" />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Auditor</label>
                    <input className="input" value={auditor} onChange={(e) => setAuditor(e.target.value)} placeholder="Name" />
                  </div>
                  <button className="btn">Record</button>
                </form>
                {audits.length ? audits.map((a) => (
                  <div key={a.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{a.result_description || "Audit"}</div>
                      <div className="when">{a.conducted_date || "—"} · {a.auditor || "—"}</div>
                    </div>
                    <ResultBadge value={a.result} />
                  </div>
                )) : <span className="muted">No audits recorded yet.</span>}
              </div>
            </div>

            <div className="card">
              <div className="card-head">
                <h3>Maintenances · {open.reference || open.name}</h3>
                <span className="sub">every {open.maintenance_frequency}</span>
              </div>
              <div className="card-pad">
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(e) => { e.preventDefault(); recordMaintenance(); }}
                >
                  <div style={{ width: 130 }}>
                    <label className="label">Result</label>
                    <select className="select" value={maintResult} onChange={(e) => setMaintResult(e.target.value)}>
                      <option value="passed">passed</option>
                      <option value="failed">failed</option>
                    </select>
                  </div>
                  <div style={{ flex: "1 1 160px" }}>
                    <label className="label">Task</label>
                    <input className="input" value={maintTask} onChange={(e) => setMaintTask(e.target.value)} placeholder="e.g. Rotate keys" />
                  </div>
                  <button className="btn">Record</button>
                </form>
                {maints.length ? maints.map((m) => (
                  <div key={m.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{m.task || "Maintenance"}</div>
                      <div className="when">{m.conducted_date || "—"}</div>
                    </div>
                    <ResultBadge value={m.result} />
                  </div>
                )) : <span className="muted">No maintenances recorded yet.</span>}
              </div>
            </div>
          </div>
          <RecordPanels model="control" entityId={open.id} />
        </>
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit control — ${editing.reference || editing.name}` : "Add item (Controls)"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "cost", label: "Cost & Resourcing", content: costTab },
            { id: "audit", label: "Audit & Maintenance", content: auditTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create control"}
        />
      )}
    </>
  );
}
