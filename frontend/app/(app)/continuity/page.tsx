"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconShield, IconCheck } from "@/components/icons";

// ----------------------------------------------------------------- inline types
type Ref = { id: string; name: string };

type ContinuityTask = {
  id: string;
  plan_id: string;
  step: number;
  action: string;
  actor: string;
  timing: string;
  location: string;
  method: string;
};

type ContinuityTest = {
  id: string;
  plan_id: string;
  result: string;
  planned_date: string | null;
  conducted_date: string | null;
  result_description: string;
  tester: string;
  created_at?: string;
};

type ContinuityPlan = {
  id: string;
  reference: string;
  name: string;
  description: string;
  bia: string;
  invocation: string;
  status: string;
  workflow_status: string;
  owner: string;
  business_unit_id: string | null;
  process_id: string | null;
  max_tolerable_downtime_hours: number | null;
  rto_hours: number | null;
  rpo_hours: number | null;
  criticality: string;
  test_frequency: string;
  next_test_date: string | null;
  last_test_date: string | null;
  task_count: number;
  test_count: number;
  last_test_result: string | null;
  is_test_overdue: boolean;
  business_unit: Ref | null;
  process: Ref | null;
  tasks: ContinuityTask[];
  tests: ContinuityTest[];
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

// ----------------------------------------------------------------- option sets
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "active", "under_review", "retired"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const CRIT = opts(["low", "medium", "high", "critical"]);
const RESULT = opts(["not_assessed", "passed", "failed"]);

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  active: "low",
  under_review: "medium",
  draft: "neutral",
  retired: "neutral",
};
const RESULT_TONE: Record<string, "low" | "critical" | "neutral"> = {
  passed: "low",
  failed: "critical",
  not_assessed: "neutral",
};

// ----------------------------------------------------------------- plan form
type FormState = {
  name: string;
  description: string;
  owner: string;
  status: string;
  workflow_status: string;
  business_unit_id: string;
  process_id: string;
  bia: string;
  invocation: string;
  criticality: string;
  max_tolerable_downtime_hours: number | "";
  rto_hours: number | "";
  rpo_hours: number | "";
  test_frequency: string;
};

const BLANK: FormState = {
  name: "", description: "", owner: "", status: "active", workflow_status: "draft",
  business_unit_id: "", process_id: "",
  bia: "", invocation: "", criticality: "high",
  max_tolerable_downtime_hours: "", rto_hours: "", rpo_hours: "", test_frequency: "annual",
};

function fromPlan(p: ContinuityPlan): FormState {
  return {
    name: p.name,
    description: p.description || "",
    owner: p.owner || "",
    status: p.status,
    workflow_status: p.workflow_status,
    business_unit_id: p.business_unit_id || "",
    process_id: p.process_id || "",
    bia: p.bia || "",
    invocation: p.invocation || "",
    criticality: p.criticality,
    max_tolerable_downtime_hours: p.max_tolerable_downtime_hours ?? "",
    rto_hours: p.rto_hours ?? "",
    rpo_hours: p.rpo_hours ?? "",
    test_frequency: p.test_frequency,
  };
}

function toPayload(f: FormState) {
  const num = (v: number | "") => (v === "" ? null : Number(v));
  return {
    name: f.name,
    description: f.description,
    owner: f.owner,
    status: f.status,
    workflow_status: f.workflow_status,
    business_unit_id: f.business_unit_id || null,
    process_id: f.process_id || null,
    bia: f.bia,
    invocation: f.invocation,
    criticality: f.criticality,
    max_tolerable_downtime_hours: num(f.max_tolerable_downtime_hours),
    rto_hours: num(f.rto_hours),
    rpo_hours: num(f.rpo_hours),
    test_frequency: f.test_frequency,
  };
}

// blank child-record rows
const BLANK_TASK = { step: 0, action: "", actor: "", timing: "", location: "", method: "" };
const BLANK_TEST = { result: "passed", planned_date: "", conducted_date: "", result_description: "", tester: "" };

export default function ContinuityPage() {
  const [items, setItems] = useState<ContinuityPlan[]>([]);
  const [units, setUnits] = useState<Ref[]>([]);
  const [processes, setProcesses] = useState<Ref[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  const [editing, setEditing] = useState<ContinuityPlan | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // child-record draft inputs (only used while editing an existing plan)
  const [task, setTask] = useState({ ...BLANK_TASK });
  const [test, setTest] = useState({ ...BLANK_TEST });

  async function load(keepEditing?: string) {
    try {
      const p = await apiCall<Page<ContinuityPlan>>("GET", "/continuity-plans?limit=200");
      setItems(p.items);
      if (keepEditing) {
        const fresh = p.items.find((x) => x.id === keepEditing) || null;
        setEditing(fresh);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  useEffect(() => {
    load();
    apiCall<Page<Ref>>("GET", "/business-units?limit=200").then((r) => setUnits(r.items)).catch(() => {});
    apiCall<Page<Ref>>("GET", "/processes?limit=200").then((r) => setProcesses(r.items)).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setTask({ ...BLANK_TASK });
    setTest({ ...BLANK_TEST });
    setError(null);
    setShowForm(true);
  }
  function openEdit(p: ContinuityPlan) {
    setEditing(p);
    setF(fromPlan(p));
    setTask({ ...BLANK_TASK });
    setTest({ ...BLANK_TEST });
    setError(null);
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<ContinuityPlan>("PATCH", `/continuity-plans/${editing.id}`, payload);
      else await apiCall<ContinuityPlan>("POST", "/continuity-plans", payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save plan");
    } finally {
      setSaving(false);
    }
  }

  async function deletePlan(p: ContinuityPlan) {
    if (!confirm(`Delete continuity plan ${p.reference}? This removes its tasks and tests.`)) return;
    setError(null);
    try {
      await apiCall<unknown>("DELETE", `/continuity-plans/${p.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // -------- child-record actions (operate on the plan being edited) --------
  async function child(fn: Promise<unknown>) {
    if (!editing) return;
    setError(null);
    try {
      await fn;
      await load(editing.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  function addTask() {
    if (!editing || !task.action.trim()) return;
    const step = task.step || editing.tasks.length + 1;
    child(apiCall("POST", `/continuity-plans/${editing.id}/tasks`, { ...task, step }));
    setTask({ ...BLANK_TASK });
  }
  function removeTask(id: string) {
    if (!editing) return;
    child(apiCall("DELETE", `/continuity-plans/${editing.id}/tasks/${id}`));
  }
  function addTest() {
    if (!editing) return;
    child(
      apiCall("POST", `/continuity-plans/${editing.id}/tests`, {
        result: test.result,
        planned_date: test.planned_date || null,
        conducted_date: test.conducted_date || null,
        result_description: test.result_description,
        tester: test.tester,
      }),
    );
    setTest({ ...BLANK_TEST });
  }
  function removeTest(id: string) {
    if (!editing) return;
    child(apiCall("DELETE", `/continuity-plans/${editing.id}/tests/${id}`));
  }

  const unitOpts: Option[] = useMemo(() => units.map((u) => ({ value: u.id, label: u.name })), [units]);
  const procOpts: Option[] = useMemo(() => processes.map((p) => ({ value: p.id, label: p.name })), [processes]);

  // ------------------------------------------------------------------ tabs
  const generalTab = (
    <>
      <Field label="Name" required help="For example: Data Centre Failover Plan, Pandemic Response Plan.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Data Centre Failover Plan" required />
      </Field>
      <Field label="Description / Scope" help="Objective and scope of this continuity plan.">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this plan covers and its objective." />
      </Field>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="BCM Coordinator" />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );

  const biaTab = (
    <>
      <Field label="Criticality" help="Business criticality driving recovery priority.">
        <Select value={f.criticality} onChange={(v) => set("criticality", v)} options={CRIT} />
      </Field>
      <div className="field-row">
        <Field label="MTD (hours)" help="Maximum tolerable downtime before unacceptable impact.">
          <NumberInput value={f.max_tolerable_downtime_hours} onChange={(v) => set("max_tolerable_downtime_hours", v)} min={0} placeholder="48" />
        </Field>
        <Field label="RTO (hours)" help="Recovery time objective — target restore time.">
          <NumberInput value={f.rto_hours} onChange={(v) => set("rto_hours", v)} min={0} placeholder="8" />
        </Field>
        <Field label="RPO (hours)" help="Recovery point objective — tolerable data loss window.">
          <NumberInput value={f.rpo_hours} onChange={(v) => set("rpo_hours", v)} min={0} placeholder="1" />
        </Field>
      </div>
      <Field label="Business Impact Analysis" help="Impacts of disruption — financial, operational, reputational, regulatory.">
        <RichText value={f.bia} onChange={(v) => set("bia", v)} placeholder="Describe the business impact of disruption…" />
      </Field>
      <Field label="Invocation Criteria" help="Conditions and procedure that trigger this plan.">
        <RichText value={f.invocation} onChange={(v) => set("invocation", v)} placeholder="When and how this plan is invoked…" />
      </Field>
      <Field label="Test Frequency" help="How often the plan is exercised; the next test date is scheduled from this.">
        <Select value={f.test_frequency} onChange={(v) => set("test_frequency", v)} options={FREQ} />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Business Unit" help="Owning business unit this plan protects.">
        <Select value={f.business_unit_id} onChange={(v) => set("business_unit_id", v)} options={unitOpts} placeholder="— none —" />
      </Field>
      <Field label="Business Process" help="Critical process this plan recovers.">
        <Select value={f.process_id} onChange={(v) => set("process_id", v)} options={procOpts} placeholder="— none —" />
      </Field>
    </>
  );

  const tasksTab = !editing ? (
    <div className="muted" style={{ padding: 8 }}>Save the plan first, then reopen it to build the recovery playbook.</div>
  ) : (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>Action (what)</th><th>Actor (who)</th><th>Timing (when)</th><th>Location (where)</th><th>Method (how)</th><th></th></tr>
          </thead>
          <tbody>
            {editing.tasks.map((t) => (
              <tr key={t.id}>
                <td className="ref">{t.step}</td>
                <td className="cell-title">{t.action}</td>
                <td className="muted">{t.actor || "—"}</td>
                <td className="muted">{t.timing || "—"}</td>
                <td className="muted">{t.location || "—"}</td>
                <td className="muted">{t.method || "—"}</td>
                <td>
                  <button className="btn secondary sm" type="button" onClick={() => removeTask(t.id)}>Remove</button>
                </td>
              </tr>
            ))}
            {editing.tasks.length === 0 && (
              <tr><td colSpan={7} className="muted" style={{ padding: 16 }}>No recovery steps yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="field-row" style={{ marginTop: 14 }}>
        <Field label="Step #"><NumberInput value={task.step || ""} onChange={(v) => setTask((p) => ({ ...p, step: v === "" ? 0 : Number(v) }))} min={0} placeholder="auto" /></Field>
        <Field label="Action (what)"><TextInput value={task.action} onChange={(v) => setTask((p) => ({ ...p, action: v }))} placeholder="Fail over to DR site" /></Field>
        <Field label="Actor (who)"><TextInput value={task.actor} onChange={(v) => setTask((p) => ({ ...p, actor: v }))} placeholder="Infra team" /></Field>
      </div>
      <div className="field-row">
        <Field label="Timing (when)"><TextInput value={task.timing} onChange={(v) => setTask((p) => ({ ...p, timing: v }))} placeholder="Within 1h" /></Field>
        <Field label="Location (where)"><TextInput value={task.location} onChange={(v) => setTask((p) => ({ ...p, location: v }))} placeholder="DR datacentre" /></Field>
        <Field label="Method (how)"><TextInput value={task.method} onChange={(v) => setTask((p) => ({ ...p, method: v }))} placeholder="Runbook DR-01" /></Field>
      </div>
      <button className="btn sm" type="button" onClick={addTask} disabled={!task.action.trim()} style={{ marginTop: 4 }}>
        <IconPlus width={14} height={14} /> Add step
      </button>
    </>
  );

  const testsTab = !editing ? (
    <div className="muted" style={{ padding: 8 }}>Save the plan first, then reopen it to record exercises.</div>
  ) : (
    <>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>Result</th><th>Planned</th><th>Conducted</th><th>Tester</th><th>Notes</th><th></th></tr>
          </thead>
          <tbody>
            {editing.tests.map((t) => (
              <tr key={t.id}>
                <td><Badge tone={RESULT_TONE[t.result] || "neutral"}>{cap(t.result)}</Badge></td>
                <td className="muted">{t.planned_date || "—"}</td>
                <td className="muted">{t.conducted_date || "—"}</td>
                <td className="muted">{t.tester || "—"}</td>
                <td className="muted">{t.result_description || "—"}</td>
                <td>
                  <button className="btn secondary sm" type="button" onClick={() => removeTest(t.id)}>Remove</button>
                </td>
              </tr>
            ))}
            {editing.tests.length === 0 && (
              <tr><td colSpan={6} className="muted" style={{ padding: 16 }}>No exercises recorded yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="field-row" style={{ marginTop: 14 }}>
        <Field label="Result"><Select value={test.result} onChange={(v) => setTest((p) => ({ ...p, result: v }))} options={RESULT} /></Field>
        <Field label="Planned date"><TextInput type="date" value={test.planned_date} onChange={(v) => setTest((p) => ({ ...p, planned_date: v }))} /></Field>
        <Field label="Conducted date"><TextInput type="date" value={test.conducted_date} onChange={(v) => setTest((p) => ({ ...p, conducted_date: v }))} /></Field>
      </div>
      <Field label="Tester"><TextInput value={test.tester} onChange={(v) => setTest((p) => ({ ...p, tester: v }))} placeholder="Exercise lead" /></Field>
      <Field label="Outcome notes"><TextArea value={test.result_description} onChange={(v) => setTest((p) => ({ ...p, result_description: v }))} rows={2} placeholder="What happened, findings, gaps." /></Field>
      <div className="help" style={{ marginBottom: 8 }}>Recording an exercise updates the plan&apos;s last/next test dates.</div>
      <button className="btn sm" type="button" onClick={addTest} style={{ marginTop: 4 }}>
        <IconCheck width={14} height={14} /> Record exercise
      </button>
    </>
  );

  const tabs = [
    { id: "general", label: "General", content: generalTab, required: true },
    { id: "bia", label: "BIA & Recovery", content: biaTab },
    { id: "links", label: "Links", content: linksTab },
    { id: "tasks", label: `Recovery Tasks${editing ? ` (${editing.task_count})` : ""}`, content: tasksTab },
    { id: "tests", label: `Tests${editing ? ` (${editing.test_count})` : ""}`, content: testsTab },
  ];

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Continuity</h1>
          <p>Continuity plans with BIA, recovery objectives, a 5W recovery playbook and an exercise calendar.</p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} /> Add plan
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Continuity plans</h3>
          <span className="sub">{items.length} total · click a row to edit</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Plan</th>
                <th>Scope</th>
                <th>Criticality</th>
                <th>RTO</th>
                <th>RPO</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Tasks</th>
                <th>Tests</th>
                <th>Next test</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => openEdit(p)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">{p.name}</td>
                  <td className="muted">{p.process?.name || p.business_unit?.name || "—"}</td>
                  <td><Badge tone={STATUS_TONE[p.criticality] || "neutral"}>{cap(p.criticality)}</Badge></td>
                  <td className="muted">{p.rto_hours != null ? `${p.rto_hours}h` : "—"}</td>
                  <td className="muted">{p.rpo_hours != null ? `${p.rpo_hours}h` : "—"}</td>
                  <td className="muted">{p.owner || "—"}</td>
                  <td><Badge tone={STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                  <td><Badge tone="info" plain>{p.task_count}</Badge></td>
                  <td>
                    {p.last_test_result
                      ? <Badge tone={RESULT_TONE[p.last_test_result] || "neutral"}>{p.test_count}</Badge>
                      : <Badge tone="neutral" plain>{p.test_count}</Badge>}
                  </td>
                  <td className="muted">
                    {p.is_test_overdue ? <Badge tone="high">Overdue</Badge> : (p.next_test_date || "—")}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => setDetailId(detailId === p.id ? null : p.id)}>Details</button>
                      <button className="btn secondary sm" onClick={() => deletePlan(p)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={12}>
                    <div className="empty">
                      <span className="ico"><IconShield width={24} height={24} /></span>
                      <h3>No continuity plans</h3>
                      <p>Create your first plan to build the recovery playbook.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detailId && <RecordPanels model="continuity_plan" entityId={detailId} />}

      {showForm && (
        <FormModal
          title={editing ? `Edit plan — ${editing.reference}` : "Add item (Business Continuity)"}
          tabs={tabs}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create plan"}
          wide
        />
      )}
    </>
  );
}
