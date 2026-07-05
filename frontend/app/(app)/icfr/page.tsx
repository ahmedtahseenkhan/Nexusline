"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconCompliance } from "@/components/icons";

/* ------------------------------------------------------------------ types */
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type IcfrTest = {
  id: string;
  control_id: string;
  reference: string;
  test_type: string;
  period: string;
  tester: string;
  sample_size: number;
  exceptions_found: number;
  test_date: string | null;
  result: string;
  conclusion: string;
  status: string;
  created_at: string;
};

type IcfrControl = {
  id: string;
  process_id: string;
  reference: string;
  title: string;
  control_objective: string;
  risk_description: string;
  assertion: string;
  control_type: string;
  nature: string;
  frequency: string;
  is_key: boolean;
  owner: string;
  design_effectiveness: string;
  operating_effectiveness: string;
  test_count: number;
  latest_result: string | null;
  created_at: string;
  tests: IcfrTest[];
};

type IcfrProcess = {
  id: string;
  reference: string;
  name: string;
  cycle: string;
  business_unit: string;
  owner: string;
  description: string;
  key_process: boolean;
  status: string;
  workflow_status: string;
  control_count: number;
  key_control_count: number;
  created_at: string;
  controls: IcfrControl[];
};

type IcfrDeficiency = {
  id: string;
  reference: string;
  title: string;
  description: string;
  control_id: string | null;
  process_id: string | null;
  severity: string;
  status: string;
  owner: string;
  identified_date: string | null;
  remediation_plan: string | null;
  target_date: string | null;
  remediated_date: string | null;
  created_at: string;
};

type IcfrSummary = {
  processes: number;
  key_processes: number;
  controls: number;
  key_controls: number;
  controls_by_operating_effectiveness: Record<string, number>;
  tests_by_result: Record<string, number>;
  deficiencies_by_severity: Record<string, number>;
  open_deficiencies: number;
  material_weaknesses: number;
};

/* ------------------------------------------------------------------ helpers */
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

/* ------------------------------------------------------------------ enum lists */
const PROCESS_STATUS = opts(["active", "retired"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const ASSERTIONS = [
  "existence_occurrence",
  "completeness",
  "accuracy",
  "valuation_allocation",
  "rights_obligations",
  "presentation_disclosure",
  "cutoff",
];
const CONTROL_TYPE = ["preventive", "detective"];
const NATURE = ["manual", "automated", "it_dependent_manual"];
const FREQUENCY = ["none", "monthly", "quarterly", "semiannual", "annual"];
const CONTROL_EFF = ["not_assessed", "ineffective", "partially_effective", "effective"];
const TEST_TYPE = ["design", "operating"];
const TEST_RESULT = ["not_tested", "passed", "failed", "passed_with_exceptions"];
const TEST_STATUS = ["planned", "in_progress", "completed"];
const SEVERITY = opts(["deficiency", "significant_deficiency", "material_weakness"]);
const DEF_STATUS = opts(["open", "remediating", "remediated", "closed"]);

/* ------------------------------------------------------------------ tones */
const PROCESS_STATUS_TONE: Record<string, Tone> = { active: "info", retired: "neutral" };
const EFF_TONE: Record<string, Tone> = {
  effective: "low",
  partially_effective: "medium",
  ineffective: "critical",
  not_assessed: "neutral",
};
const TEST_RESULT_TONE: Record<string, Tone> = {
  passed: "low",
  passed_with_exceptions: "medium",
  failed: "critical",
  not_tested: "neutral",
};
const TEST_STATUS_TONE: Record<string, Tone> = {
  planned: "neutral",
  in_progress: "info",
  completed: "low",
};
const SEVERITY_TONE: Record<string, Tone> = {
  deficiency: "medium",
  significant_deficiency: "high",
  material_weakness: "critical",
};
const DEF_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  remediating: "info",
  remediated: "low",
  closed: "neutral",
};

function EffBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={EFF_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

/* ------------------------------------------------------------------ process form */
type ProcessForm = {
  name: string;
  cycle: string;
  business_unit: string;
  owner: string;
  description: string;
  key_process: boolean;
  status: string;
  workflow_status: string;
};
const BLANK_PROCESS: ProcessForm = {
  name: "",
  cycle: "",
  business_unit: "",
  owner: "",
  description: "",
  key_process: false,
  status: "active",
  workflow_status: "draft",
};
function fromProcess(p: IcfrProcess): ProcessForm {
  return {
    name: p.name,
    cycle: p.cycle || "",
    business_unit: p.business_unit || "",
    owner: p.owner || "",
    description: p.description || "",
    key_process: !!p.key_process,
    status: p.status || "active",
    workflow_status: p.workflow_status || "draft",
  };
}
function processPayload(f: ProcessForm): Record<string, unknown> {
  return {
    name: f.name,
    cycle: f.cycle,
    business_unit: f.business_unit,
    owner: f.owner,
    description: f.description,
    key_process: f.key_process,
    status: f.status,
    workflow_status: f.workflow_status,
  };
}

/* ------------------------------------------------------------------ control draft */
type ControlDraft = {
  title: string;
  control_objective: string;
  risk_description: string;
  assertion: string;
  control_type: string;
  nature: string;
  frequency: string;
  is_key: boolean;
  owner: string;
  design_effectiveness: string;
  operating_effectiveness: string;
};
const BLANK_CONTROL: ControlDraft = {
  title: "",
  control_objective: "",
  risk_description: "",
  assertion: "accuracy",
  control_type: "preventive",
  nature: "manual",
  frequency: "monthly",
  is_key: false,
  owner: "",
  design_effectiveness: "not_assessed",
  operating_effectiveness: "not_assessed",
};

/* ------------------------------------------------------------------ test draft */
type TestDraft = {
  test_type: string;
  period: string;
  tester: string;
  sample_size: string;
  exceptions_found: string;
  test_date: string;
  result: string;
  status: string;
  conclusion: string;
};
const BLANK_TEST: TestDraft = {
  test_type: "operating",
  period: "",
  tester: "",
  sample_size: "0",
  exceptions_found: "0",
  test_date: "",
  result: "not_tested",
  status: "planned",
  conclusion: "",
};

/* ------------------------------------------------------------------ deficiency form */
type DefForm = {
  title: string;
  description: string;
  process_id: string;
  control_id: string;
  severity: string;
  status: string;
  owner: string;
  identified_date: string;
  remediation_plan: string;
  target_date: string;
  remediated_date: string;
};
const BLANK_DEF: DefForm = {
  title: "",
  description: "",
  process_id: "",
  control_id: "",
  severity: "deficiency",
  status: "open",
  owner: "",
  identified_date: "",
  remediation_plan: "",
  target_date: "",
  remediated_date: "",
};
function fromDef(d: IcfrDeficiency): DefForm {
  return {
    title: d.title,
    description: d.description || "",
    process_id: d.process_id || "",
    control_id: d.control_id || "",
    severity: d.severity || "deficiency",
    status: d.status || "open",
    owner: d.owner || "",
    identified_date: d.identified_date || "",
    remediation_plan: d.remediation_plan || "",
    target_date: d.target_date || "",
    remediated_date: d.remediated_date || "",
  };
}
function defPayload(f: DefForm): Record<string, unknown> {
  return {
    title: f.title,
    description: f.description,
    process_id: f.process_id || null,
    control_id: f.control_id || null,
    severity: f.severity,
    status: f.status,
    owner: f.owner,
    identified_date: f.identified_date || null,
    remediation_plan: f.remediation_plan,
    target_date: f.target_date || null,
    remediated_date: f.remediated_date || null,
  };
}

type SectionId = "processes" | "deficiencies";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "processes", label: "Process & RCM" },
  { id: "deficiencies", label: "Deficiencies" },
];

export default function IcfrPage() {
  const [section, setSection] = useState<SectionId>("processes");
  const [error, setError] = useState<string | null>(null);

  const [processes, setProcesses] = useState<IcfrProcess[]>([]);
  const [deficiencies, setDeficiencies] = useState<IcfrDeficiency[]>([]);
  const [summary, setSummary] = useState<IcfrSummary | null>(null);

  // ---- process dialog + expanded detail ----
  const [editingProcess, setEditingProcess] = useState<IcfrProcess | null>(null);
  const [showProcessForm, setShowProcessForm] = useState(false);
  const [savingProcess, setSavingProcess] = useState(false);
  const [pf, setPf] = useState<ProcessForm>(BLANK_PROCESS);
  const setP = <K extends keyof ProcessForm>(k: K, v: ProcessForm[K]) => setPf((p) => ({ ...p, [k]: v }));

  const [openProcess, setOpenProcess] = useState<IcfrProcess | null>(null);
  const [cd, setCd] = useState<ControlDraft>(BLANK_CONTROL);
  const setCD = <K extends keyof ControlDraft>(k: K, v: ControlDraft[K]) => setCd((p) => ({ ...p, [k]: v }));

  // ---- control expand (per control row) + test draft ----
  const [openControlId, setOpenControlId] = useState<string | null>(null);
  const [td, setTd] = useState<TestDraft>(BLANK_TEST);
  const setTD = <K extends keyof TestDraft>(k: K, v: TestDraft[K]) => setTd((p) => ({ ...p, [k]: v }));

  // ---- deficiency dialog ----
  const [editingDef, setEditingDef] = useState<IcfrDeficiency | null>(null);
  const [showDefForm, setShowDefForm] = useState(false);
  const [savingDef, setSavingDef] = useState(false);
  const [df, setDf] = useState<DefForm>(BLANK_DEF);
  const setD = <K extends keyof DefForm>(k: K, v: DefForm[K]) => setDf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadProcesses(keepOpen?: string) {
    try {
      const res = await apiCall<Page<IcfrProcess>>("GET", "/icfr");
      setProcesses(res.items);
      if (keepOpen) setOpenProcess(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ICFR processes");
    }
  }
  async function loadDeficiencies() {
    try {
      const res = await apiCall<Page<IcfrDeficiency>>("GET", "/icfr-deficiencies");
      setDeficiencies(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load deficiencies");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<IcfrSummary>("GET", "/icfr-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ICFR summary");
    }
  }
  async function refreshProcess(id: string) {
    const p = await apiCall<IcfrProcess>("GET", `/icfr/${id}`);
    setOpenProcess(p);
    setProcesses((prev) => prev.map((x) => (x.id === id ? p : x)));
  }

  useEffect(() => {
    loadProcesses();
    loadDeficiencies();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- process CRUD
  function openNewProcess() {
    setEditingProcess(null);
    setPf(BLANK_PROCESS);
    setShowProcessForm(true);
  }
  function openEditProcess(p: IcfrProcess) {
    setEditingProcess(p);
    setPf(fromProcess(p));
    setShowProcessForm(true);
  }
  async function saveProcess() {
    setError(null);
    setSavingProcess(true);
    try {
      const payload = processPayload(pf);
      if (editingProcess) await apiCall("PATCH", `/icfr/${editingProcess.id}`, payload);
      else await apiCall("POST", "/icfr", payload);
      setShowProcessForm(false);
      await loadProcesses(openProcess?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save process");
    } finally {
      setSavingProcess(false);
    }
  }
  async function removeProcess(p: IcfrProcess) {
    if (!window.confirm(`Delete process ${p.reference || p.name}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/icfr/${p.id}`);
      setShowProcessForm(false);
      if (openProcess?.id === p.id) setOpenProcess(null);
      await loadProcesses();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleProcess(p: IcfrProcess) {
    setCd(BLANK_CONTROL);
    setOpenControlId(null);
    setOpenProcess(openProcess?.id === p.id ? null : p);
  }

  // ------------------------------------------------------------- RCM controls (inline)
  async function addControl() {
    if (!openProcess) return;
    setError(null);
    try {
      await apiCall("POST", `/icfr/${openProcess.id}/controls`, {
        title: cd.title,
        control_objective: cd.control_objective,
        risk_description: cd.risk_description,
        assertion: cd.assertion,
        control_type: cd.control_type,
        nature: cd.nature,
        frequency: cd.frequency,
        is_key: cd.is_key,
        owner: cd.owner,
        design_effectiveness: cd.design_effectiveness,
        operating_effectiveness: cd.operating_effectiveness,
      });
      setCd(BLANK_CONTROL);
      await refreshProcess(openProcess.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add control");
    }
  }
  async function removeControl(controlId: string) {
    if (!openProcess) return;
    if (!window.confirm("Remove this control from the RCM?")) return;
    setError(null);
    try {
      await apiCall("DELETE", `/icfr-controls/${controlId}`);
      if (openControlId === controlId) setOpenControlId(null);
      await refreshProcess(openProcess.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove control");
    }
  }
  function toggleControl(controlId: string) {
    setTd(BLANK_TEST);
    setOpenControlId(openControlId === controlId ? null : controlId);
  }

  // ------------------------------------------------------------- control tests (inline)
  async function addTest(controlId: string) {
    if (!openProcess) return;
    setError(null);
    try {
      await apiCall("POST", `/icfr-controls/${controlId}/tests`, {
        test_type: td.test_type,
        period: td.period,
        tester: td.tester,
        sample_size: td.sample_size === "" ? 0 : Number(td.sample_size),
        exceptions_found: td.exceptions_found === "" ? 0 : Number(td.exceptions_found),
        test_date: td.test_date || null,
        result: td.result,
        status: td.status,
        conclusion: td.conclusion,
      });
      setTd(BLANK_TEST);
      await refreshProcess(openProcess.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add test");
    }
  }

  // ------------------------------------------------------------- deficiency CRUD
  function openNewDef() {
    setEditingDef(null);
    setDf(BLANK_DEF);
    setShowDefForm(true);
  }
  function openEditDef(d: IcfrDeficiency) {
    setEditingDef(d);
    setDf(fromDef(d));
    setShowDefForm(true);
  }
  async function saveDef() {
    setError(null);
    setSavingDef(true);
    try {
      const payload = defPayload(df);
      if (editingDef) await apiCall("PATCH", `/icfr-deficiencies/${editingDef.id}`, payload);
      else await apiCall("POST", "/icfr-deficiencies", payload);
      setShowDefForm(false);
      await loadDeficiencies();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save deficiency");
    } finally {
      setSavingDef(false);
    }
  }
  async function removeDef(d: IcfrDeficiency) {
    if (!window.confirm(`Delete deficiency ${d.reference || d.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/icfr-deficiencies/${d.id}`);
      setShowDefForm(false);
      await loadDeficiencies();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- deficiency link options
  const processOptions = useMemo<Option[]>(
    () => processes.map((p) => ({ value: p.id, label: `${p.reference || "PRC"} — ${p.name}` })),
    [processes],
  );
  const controlOptions = useMemo<Option[]>(
    () =>
      processes.flatMap((p) =>
        p.controls.map((c) => ({ value: c.id, label: `${c.reference || "CTL"} — ${c.title}`, sub: p.name })),
      ),
    [processes],
  );

  // ------------------------------------------------------------- process form tabs
  const processGeneral = (
    <>
      <Field label="Process name" required help="For example: Revenue recognition or Financial close.">
        <TextInput value={pf.name} onChange={(v) => setP("name", v)} placeholder="Process name" required />
      </Field>
      <div className="field-row">
        <Field label="Cycle" help="Financial reporting cycle, e.g. Revenue, Procure-to-Pay, Financial Close.">
          <TextInput value={pf.cycle} onChange={(v) => setP("cycle", v)} placeholder="Procure-to-Pay" />
        </Field>
        <Field label="Business unit">
          <TextInput value={pf.business_unit} onChange={(v) => setP("business_unit", v)} placeholder="Finance" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Process owner">
          <TextInput value={pf.owner} onChange={(v) => setP("owner", v)} placeholder="Owner" />
        </Field>
        <Field label="Status">
          <Select value={pf.status} onChange={(v) => setP("status", v)} options={PROCESS_STATUS} />
        </Field>
      </div>
      <Field label="Key process" help="Flag processes that are significant to financial reporting.">
        <Toggle checked={pf.key_process} onChange={(v) => setP("key_process", v)} label="This is a key process" />
      </Field>
    </>
  );
  const processDetails = (
    <>
      <Field label="Description">
        <TextArea value={pf.description} onChange={(v) => setP("description", v)} rows={4} placeholder="Scope of the process and its financial-reporting relevance." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this process record.">
        <Select value={pf.workflow_status} onChange={(v) => setP("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- deficiency form tabs
  const defGeneral = (
    <>
      <Field label="Title" required help="For example: Manual journal entries lack independent review.">
        <TextInput value={df.title} onChange={(v) => setD("title", v)} placeholder="Deficiency title" required />
      </Field>
      <div className="field-row">
        <Field label="Severity" help="Deficiency, significant deficiency, or material weakness.">
          <Select value={df.severity} onChange={(v) => setD("severity", v)} options={SEVERITY} />
        </Field>
        <Field label="Status">
          <Select value={df.status} onChange={(v) => setD("status", v)} options={DEF_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Process" help="The process this deficiency relates to.">
          <Select value={df.process_id} onChange={(v) => setD("process_id", v)} options={processOptions} placeholder="Unlinked" />
        </Field>
        <Field label="Control" help="The RCM control this deficiency relates to.">
          <Select value={df.control_id} onChange={(v) => setD("control_id", v)} options={controlOptions} placeholder="Unlinked" />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={df.description} onChange={(v) => setD("description", v)} rows={3} placeholder="Nature of the control deficiency." />
      </Field>
    </>
  );
  const defRemediation = (
    <>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={df.owner} onChange={(v) => setD("owner", v)} placeholder="Remediation owner" />
        </Field>
        <Field label="Identified date">
          <TextInput type="date" value={df.identified_date} onChange={(v) => setD("identified_date", v)} />
        </Field>
      </div>
      <Field label="Remediation plan">
        <TextArea value={df.remediation_plan} onChange={(v) => setD("remediation_plan", v)} rows={3} placeholder="Planned corrective action." />
      </Field>
      <div className="field-row">
        <Field label="Target date" help="Target remediation completion.">
          <TextInput type="date" value={df.target_date} onChange={(v) => setD("target_date", v)} />
        </Field>
        <Field label="Remediated date">
          <TextInput type="date" value={df.remediated_date} onChange={(v) => setD("remediated_date", v)} />
        </Field>
      </div>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>ICFR</h1>
          <p>Internal Control over Financial Reporting — the SBP annual cycle: process universe, Risk-Control Matrix, control testing, and deficiency evaluation.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "processes" && (
            <button className="btn" onClick={openNewProcess}>
              <IconPlus width={16} height={16} /> New process
            </button>
          )}
          {section === "deficiencies" && (
            <button className="btn" onClick={openNewDef}>
              <IconPlus width={16} height={16} /> New deficiency
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.processes.toLocaleString() : "—"}</span></div>
          <span className="l">Processes</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.key_controls.toLocaleString() : "—"}</span></div>
          <span className="l">Key controls</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.open_deficiencies.toLocaleString() : "—"}</span></div>
          <span className="l">Open deficiencies</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.material_weaknesses.toLocaleString() : "—"}</span></div>
          <span className="l">Material weaknesses</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, margin: "16px 0", flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            className={`btn${section === s.id ? "" : " secondary"}`}
            onClick={() => setSection(s.id)}
            type="button"
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= PROCESS & RCM */}
      {section === "processes" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>Process universe</h3>
              <span className="sub">{processes.length} total · click a row to manage its Risk-Control Matrix</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Process</th>
                    <th>Cycle</th>
                    <th>Owner</th>
                    <th>Key</th>
                    <th>Controls</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {processes.map((p) => (
                    <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => toggleProcess(p)}>
                      <td className="ref">{p.reference || "—"}</td>
                      <td className="cell-title">{p.name}</td>
                      <td className="muted">{p.cycle || "—"}</td>
                      <td className="muted">{p.owner || "—"}</td>
                      <td>{p.key_process ? <Badge tone="info">Key</Badge> : <span className="muted">—</span>}</td>
                      <td className="muted">{p.control_count} ({p.key_control_count} key)</td>
                      <td><Badge tone={PROCESS_STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleProcess(p)}>
                            {openProcess?.id === p.id ? "Hide" : "Manage RCM"}
                          </button>
                          <button className="btn secondary sm" onClick={() => removeProcess(p)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {processes.length === 0 && (
                    <tr>
                      <td colSpan={8}>
                        <div className="empty">
                          <span className="ico"><IconCompliance width={24} height={24} /></span>
                          <h3>No ICFR processes</h3>
                          <p>Map the financial-reporting process universe, then build a Risk-Control Matrix for each.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openProcess && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openProcess.reference} — {openProcess.name}</h3>
                    <span className="sub">
                      {cap(openProcess.status)} · {openProcess.cycle || "no cycle"}
                      {openProcess.owner ? " · owner " + openProcess.owner : ""}
                      {openProcess.key_process ? " · key process" : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button className="btn secondary sm" onClick={() => openEditProcess(openProcess)}>Edit</button>
                    <button className="btn secondary sm" onClick={() => removeProcess(openProcess)}>Delete</button>
                  </div>
                </div>

                <div className="card-pad">
                  <strong>Risk-Control Matrix</strong>
                  <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                    Each control maps a risk to a financial-statement assertion, with design and operating effectiveness. Click a control to record tests.
                  </p>
                  <form
                    style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                    onSubmit={(ev) => { ev.preventDefault(); addControl(); }}
                  >
                    <div style={{ flex: "1 1 200px" }}>
                      <label className="label">Control title</label>
                      <input className="input" value={cd.title} onChange={(ev) => setCD("title", ev.target.value)} placeholder="Control title" required />
                    </div>
                    <div style={{ width: 190 }}>
                      <label className="label">Assertion</label>
                      <select className="select" value={cd.assertion} onChange={(ev) => setCD("assertion", ev.target.value)}>
                        {ASSERTIONS.map((a) => (<option key={a} value={a}>{cap(a)}</option>))}
                      </select>
                    </div>
                    <div style={{ width: 130 }}>
                      <label className="label">Type</label>
                      <select className="select" value={cd.control_type} onChange={(ev) => setCD("control_type", ev.target.value)}>
                        {CONTROL_TYPE.map((t) => (<option key={t} value={t}>{cap(t)}</option>))}
                      </select>
                    </div>
                    <div style={{ width: 160 }}>
                      <label className="label">Nature</label>
                      <select className="select" value={cd.nature} onChange={(ev) => setCD("nature", ev.target.value)}>
                        {NATURE.map((n) => (<option key={n} value={n}>{cap(n)}</option>))}
                      </select>
                    </div>
                    <div style={{ width: 130 }}>
                      <label className="label">Frequency</label>
                      <select className="select" value={cd.frequency} onChange={(ev) => setCD("frequency", ev.target.value)}>
                        {FREQUENCY.map((fr) => (<option key={fr} value={fr}>{cap(fr)}</option>))}
                      </select>
                    </div>
                    <div style={{ width: 140 }}>
                      <label className="label">Owner</label>
                      <input className="input" value={cd.owner} onChange={(ev) => setCD("owner", ev.target.value)} placeholder="Owner" />
                    </div>
                    <div style={{ width: 170 }}>
                      <label className="label">Design eff.</label>
                      <select className="select" value={cd.design_effectiveness} onChange={(ev) => setCD("design_effectiveness", ev.target.value)}>
                        {CONTROL_EFF.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                      </select>
                    </div>
                    <div style={{ width: 170 }}>
                      <label className="label">Operating eff.</label>
                      <select className="select" value={cd.operating_effectiveness} onChange={(ev) => setCD("operating_effectiveness", ev.target.value)}>
                        {CONTROL_EFF.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                      </select>
                    </div>
                    <div style={{ flex: "1 1 200px" }}>
                      <label className="label">Control objective</label>
                      <input className="input" value={cd.control_objective} onChange={(ev) => setCD("control_objective", ev.target.value)} placeholder="What the control achieves" />
                    </div>
                    <div style={{ flex: "1 1 200px" }}>
                      <label className="label">Risk description</label>
                      <input className="input" value={cd.risk_description} onChange={(ev) => setCD("risk_description", ev.target.value)} placeholder="Risk being mitigated" />
                    </div>
                    <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, paddingBottom: 8 }}>
                      <input type="checkbox" checked={cd.is_key} onChange={(ev) => setCD("is_key", ev.target.checked)} /> Key
                    </label>
                    <button className="btn">Add control</button>
                  </form>

                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Ref</th>
                          <th>Control</th>
                          <th>Assertion</th>
                          <th>Type</th>
                          <th>Key</th>
                          <th>Design eff.</th>
                          <th>Operating eff.</th>
                          <th>Tests</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {openProcess.controls.map((c) => (
                          <Fragment key={c.id}>
                            <tr style={{ cursor: "pointer" }} onClick={() => toggleControl(c.id)}>
                              <td className="ref">{c.reference || "—"}</td>
                              <td className="cell-title">{c.title}</td>
                              <td><Badge tone="info">{cap(c.assertion)}</Badge></td>
                              <td className="muted">{cap(c.control_type)}</td>
                              <td>{c.is_key ? <Badge tone="info">Key</Badge> : <span className="muted">—</span>}</td>
                              <td><EffBadge value={c.design_effectiveness} /></td>
                              <td><EffBadge value={c.operating_effectiveness} /></td>
                              <td className="muted">
                                {c.test_count}
                                {c.latest_result ? (
                                  <> · <Badge tone={TEST_RESULT_TONE[c.latest_result] || "neutral"}>{cap(c.latest_result)}</Badge></>
                                ) : null}
                              </td>
                              <td>
                                <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                                  <button className="btn secondary sm" onClick={() => toggleControl(c.id)}>
                                    {openControlId === c.id ? "Hide" : "Tests"}
                                  </button>
                                  <button className="btn secondary sm" onClick={() => removeControl(c.id)}>Remove</button>
                                </div>
                              </td>
                            </tr>
                            {openControlId === c.id && (
                              <tr>
                                <td colSpan={9} style={{ background: "var(--panel-2, rgba(0,0,0,0.02))" }}>
                                  <div style={{ padding: "4px 0 8px" }}>
                                    <strong style={{ fontSize: 13 }}>Control testing — {c.reference}</strong>
                                    <p className="muted" style={{ margin: "4px 0 10px", fontSize: 12 }}>
                                      Record design and operating-effectiveness tests, sample sizes and exceptions.
                                    </p>
                                    <form
                                      style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "flex-end", flexWrap: "wrap" }}
                                      onSubmit={(ev) => { ev.preventDefault(); addTest(c.id); }}
                                    >
                                      <div style={{ width: 130 }}>
                                        <label className="label">Test type</label>
                                        <select className="select" value={td.test_type} onChange={(ev) => setTD("test_type", ev.target.value)}>
                                          {TEST_TYPE.map((t) => (<option key={t} value={t}>{cap(t)}</option>))}
                                        </select>
                                      </div>
                                      <div style={{ width: 120 }}>
                                        <label className="label">Period</label>
                                        <input className="input" value={td.period} onChange={(ev) => setTD("period", ev.target.value)} placeholder="FY26 Q1" />
                                      </div>
                                      <div style={{ width: 140 }}>
                                        <label className="label">Tester</label>
                                        <input className="input" value={td.tester} onChange={(ev) => setTD("tester", ev.target.value)} placeholder="Tester" />
                                      </div>
                                      <div style={{ width: 90 }}>
                                        <label className="label">Sample</label>
                                        <input className="input" type="number" min={0} value={td.sample_size} onChange={(ev) => setTD("sample_size", ev.target.value)} />
                                      </div>
                                      <div style={{ width: 100 }}>
                                        <label className="label">Exceptions</label>
                                        <input className="input" type="number" min={0} value={td.exceptions_found} onChange={(ev) => setTD("exceptions_found", ev.target.value)} />
                                      </div>
                                      <div style={{ width: 150 }}>
                                        <label className="label">Test date</label>
                                        <input className="input" type="date" value={td.test_date} onChange={(ev) => setTD("test_date", ev.target.value)} />
                                      </div>
                                      <div style={{ width: 190 }}>
                                        <label className="label">Result</label>
                                        <select className="select" value={td.result} onChange={(ev) => setTD("result", ev.target.value)}>
                                          {TEST_RESULT.map((r) => (<option key={r} value={r}>{cap(r)}</option>))}
                                        </select>
                                      </div>
                                      <div style={{ width: 140 }}>
                                        <label className="label">Status</label>
                                        <select className="select" value={td.status} onChange={(ev) => setTD("status", ev.target.value)}>
                                          {TEST_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                                        </select>
                                      </div>
                                      <div style={{ flex: "1 1 200px" }}>
                                        <label className="label">Conclusion</label>
                                        <input className="input" value={td.conclusion} onChange={(ev) => setTD("conclusion", ev.target.value)} placeholder="Test conclusion" />
                                      </div>
                                      <button className="btn">Add test</button>
                                    </form>

                                    <div className="table-wrap">
                                      <table>
                                        <thead>
                                          <tr>
                                            <th>Ref</th>
                                            <th>Type</th>
                                            <th>Period</th>
                                            <th>Tester</th>
                                            <th>Sample</th>
                                            <th>Exceptions</th>
                                            <th>Result</th>
                                            <th>Status</th>
                                            <th>Date</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {c.tests.map((t) => (
                                            <tr key={t.id}>
                                              <td className="ref">{t.reference || "—"}</td>
                                              <td className="muted">{cap(t.test_type)}</td>
                                              <td className="muted">{t.period || "—"}</td>
                                              <td className="muted">{t.tester || "—"}</td>
                                              <td className="muted">{t.sample_size}</td>
                                              <td className="muted">{t.exceptions_found}</td>
                                              <td><Badge tone={TEST_RESULT_TONE[t.result] || "neutral"}>{cap(t.result)}</Badge></td>
                                              <td><Badge tone={TEST_STATUS_TONE[t.status] || "neutral"}>{cap(t.status)}</Badge></td>
                                              <td className="muted">{t.test_date || "—"}</td>
                                            </tr>
                                          ))}
                                          {c.tests.length === 0 && (
                                            <tr><td colSpan={9}><span className="muted">No tests recorded yet.</span></td></tr>
                                          )}
                                        </tbody>
                                      </table>
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </Fragment>
                        ))}
                        {openProcess.controls.length === 0 && (
                          <tr><td colSpan={9}><span className="muted">No controls in the RCM yet.</span></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <RecordPanels model="icfr_process" entityId={openProcess.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= DEFICIENCIES */}
      {section === "deficiencies" && (
        <div className="card">
          <div className="card-head">
            <h3>Deficiency register</h3>
            <span className="sub">{deficiencies.length} total · material weaknesses highlighted · click a row to edit</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Title</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Owner</th>
                  <th>Identified</th>
                  <th>Target</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {deficiencies.map((d) => {
                  const mw = d.severity === "material_weakness";
                  return (
                    <tr
                      key={d.id}
                      style={{ cursor: "pointer", background: mw ? "rgba(192,57,43,0.06)" : undefined }}
                      onClick={() => openEditDef(d)}
                    >
                      <td className="ref">{d.reference || "—"}</td>
                      <td className="cell-title">{d.title}</td>
                      <td>
                        <Badge tone={SEVERITY_TONE[d.severity] || "neutral"}>{cap(d.severity)}</Badge>
                        {mw && <Badge tone="critical">Material</Badge>}
                      </td>
                      <td><Badge tone={DEF_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge></td>
                      <td className="muted">{d.owner || "—"}</td>
                      <td className="muted">{d.identified_date || "—"}</td>
                      <td className="muted">{d.target_date || "—"}</td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => removeDef(d)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {deficiencies.length === 0 && (
                  <tr>
                    <td colSpan={8}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No deficiencies logged</h3>
                        <p>Record control deficiencies from testing and evaluate each as a deficiency, significant deficiency, or material weakness.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= MODALS */}
      {showProcessForm && (
        <FormModal
          title={editingProcess ? `Edit process — ${editingProcess.reference || editingProcess.name}` : "New ICFR process"}
          wide
          tabs={[
            { id: "general", label: "General", content: processGeneral, required: true },
            { id: "details", label: "Details", content: processDetails },
          ]}
          onClose={() => setShowProcessForm(false)}
          onSave={saveProcess}
          saving={savingProcess}
          error={error}
          saveLabel={editingProcess ? "Save changes" : "Create process"}
          footerLeft={
            editingProcess ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeProcess(editingProcess)}
                disabled={savingProcess}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showDefForm && (
        <FormModal
          title={editingDef ? `Edit deficiency — ${editingDef.reference || editingDef.title}` : "New deficiency"}
          wide
          tabs={[
            { id: "general", label: "General", content: defGeneral, required: true },
            { id: "remediation", label: "Remediation", content: defRemediation },
          ]}
          onClose={() => setShowDefForm(false)}
          onSave={saveDef}
          saving={savingDef}
          error={error}
          saveLabel={editingDef ? "Save changes" : "Create deficiency"}
          footerLeft={
            editingDef ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeDef(editingDef)}
                disabled={savingDef}
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
