"use client";

import { Fragment, Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncSelect from "@/components/AsyncSelect";
import RelatedChips from "@/components/RelatedChips";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

/* ------------------------------------------------------------------ types */
type Ref = { id: string; reference?: string; title?: string; name?: string };
const refLabel = (x: Ref) => x.reference || x.title || x.name || x.id;

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
  // additive FK to the enterprise controls register (nullable)
  control?: Ref | null;
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
  process_label: string | null;
  control_label: string | null;
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
  control_id: string;
  control_label: string;
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
  control_id: "",
  control_label: "",
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
  process_label: string;
  control_id: string;
  control_label: string;
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
  process_label: "",
  control_id: "",
  control_label: "",
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
    process_label: d.process_label || "",
    control_id: d.control_id || "",
    control_label: d.control_label || "",
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

function IcfrInner() {
  const [section, setSection] = useState<SectionId>("processes");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  const [summary, setSummary] = useState<IcfrSummary | null>(null);

  // ---- process form dialog ----
  const [editingProcess, setEditingProcess] = useState<IcfrProcess | null>(null);
  const [showProcessForm, setShowProcessForm] = useState(false);
  const [savingProcess, setSavingProcess] = useState(false);
  const [pf, setPf] = useState<ProcessForm>(BLANK_PROCESS);
  const setP = <K extends keyof ProcessForm>(k: K, v: ProcessForm[K]) => setPf((p) => ({ ...p, [k]: v }));

  // ---- process drawer (RCM) ----
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<IcfrProcess | null>(null);
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
  const loadSummary = useCallback(async () => {
    try {
      setSummary(await apiCall<IcfrSummary>("GET", "/icfr-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ICFR summary");
    }
  }, []);
  useEffect(() => {
    loadSummary();
  }, [loadSummary, refreshKey]);

  const fetchProcesses = useCallback((qs: string) => apiCall<PagedList<IcfrProcess>>("GET", `/icfr?${qs}`), []);
  const fetchDeficiencies = useCallback(
    (qs: string) => apiCall<PagedList<IcfrDeficiency>>("GET", `/icfr-deficiencies?${qs}`),
    [],
  );

  const loadDetail = useCallback((id: string) => {
    return apiCall<IcfrProcess>("GET", `/icfr/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) {
      loadDetail(openId);
    } else {
      setDetail(null);
      setOpenControlId(null);
      setCd(BLANK_CONTROL);
    }
  }, [openId, loadDetail]);

  async function refreshProcess(id: string) {
    const p = await apiCall<IcfrProcess>("GET", `/icfr/${id}`);
    setDetail(p);
    reload();
  }

  // ------------------------------------------------------------- process CRUD
  function openNewProcess() {
    setEditingProcess(null);
    setPf(BLANK_PROCESS);
    setError(null);
    setShowProcessForm(true);
  }
  function openEditProcess(p: IcfrProcess) {
    setEditingProcess(p);
    setPf(fromProcess(p));
    setError(null);
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
      reload();
      if (openId) loadDetail(openId);
      await loadSummary();
      toast(editingProcess ? "Changes saved" : "Process created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save process");
    } finally {
      setSavingProcess(false);
    }
  }
  async function removeProcess(p: IcfrProcess) {
    if (!(await confirmDialog({ title: `Delete process ${p.reference || p.name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/icfr/${p.id}`);
      setShowProcessForm(false);
      if (openId === p.id) setOpenId(null);
      reload();
      await loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- RCM controls (drawer)
  async function addControl() {
    if (!detail) return;
    setError(null);
    try {
      await apiCall("POST", `/icfr/${detail.id}/controls`, {
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
        control_id: cd.control_id || null,
      });
      setCd(BLANK_CONTROL);
      await refreshProcess(detail.id);
      await loadSummary();
      toast("Control added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add control");
    }
  }
  async function removeControl(controlId: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Remove this control from the RCM?", danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/icfr-controls/${controlId}`);
      if (openControlId === controlId) setOpenControlId(null);
      await refreshProcess(detail.id);
      await loadSummary();
      toast("Control removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove control");
    }
  }
  function toggleControl(controlId: string) {
    setTd(BLANK_TEST);
    setOpenControlId(openControlId === controlId ? null : controlId);
  }

  // ------------------------------------------------------------- control tests (drawer)
  async function addTest(controlId: string) {
    if (!detail) return;
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
      await refreshProcess(detail.id);
      await loadSummary();
      toast("Test recorded");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add test");
    }
  }

  // ------------------------------------------------------------- deficiency CRUD
  function openNewDef() {
    setEditingDef(null);
    setDf(BLANK_DEF);
    setError(null);
    setShowDefForm(true);
  }
  function openEditDef(d: IcfrDeficiency) {
    setEditingDef(d);
    setDf(fromDef(d));
    setError(null);
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
      reload();
      await loadSummary();
      toast(editingDef ? "Changes saved" : "Deficiency created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save deficiency");
    } finally {
      setSavingDef(false);
    }
  }
  async function removeDef(d: IcfrDeficiency) {
    if (!(await confirmDialog({ title: `Delete deficiency ${d.reference || d.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/icfr-deficiencies/${d.id}`);
      setShowDefForm(false);
      reload();
      await loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- deficiency link pickers (server typeahead)
  const searchProcesses = (q: string) =>
    apiCall<PagedList<IcfrProcess>>("GET", `/icfr?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((p) => ({ value: p.id, label: `${p.reference || "PRC"} — ${p.name}` })),
    );
  const searchControls = (q: string) =>
    apiCall<PagedList<IcfrControl>>("GET", `/icfr-controls?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((c) => ({ value: c.id, label: `${c.reference || "CTL"} — ${c.title}` })),
    );
  // enterprise controls register — the RCM line's control FK
  const searchEnterpriseControls = (q: string) =>
    apiCall<PagedList<Ref>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((c) => ({ value: c.id, label: refLabel(c), sub: c.reference })),
    );

  // ------------------------------------------------------------- table columns
  const processColumns: Column<IcfrProcess>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (p) => <span className="ref">{p.reference || "—"}</span> },
    { key: "name", header: "Process", sortable: true, render: (p) => <span className="cell-title">{p.name}</span> },
    { key: "cycle", header: "Cycle", sortable: true, render: (p) => <span className="muted">{p.cycle || "—"}</span> },
    { key: "owner", header: "Owner", sortable: true, render: (p) => <span className="muted">{p.owner || "—"}</span> },
    { key: "key", header: "Key", render: (p) => (p.key_process ? <Badge tone="info">Key</Badge> : <span className="muted">—</span>) },
    { key: "controls", header: "Controls", render: (p) => <span className="muted">{p.control_count} ({p.key_control_count} key)</span> },
    { key: "status", header: "Status", sortable: true, render: (p) => <Badge tone={PROCESS_STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge> },
    {
      key: "actions",
      header: "",
      render: (p) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => openEditProcess(p)}>Edit</button>{" "}
          <button className="btn secondary sm" onClick={() => removeProcess(p)}>Delete</button>
        </div>
      ),
    },
  ];

  const defColumns: Column<IcfrDeficiency>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (d) => <span className="ref">{d.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (d) => <span className="cell-title">{d.title}</span> },
    {
      key: "severity",
      header: "Severity",
      sortable: true,
      render: (d) => (
        <>
          <Badge tone={SEVERITY_TONE[d.severity] || "neutral"}>{cap(d.severity)}</Badge>
          {d.severity === "material_weakness" && <> <Badge tone="critical">Material</Badge></>}
        </>
      ),
    },
    { key: "status", header: "Status", sortable: true, render: (d) => <Badge tone={DEF_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge> },
    { key: "owner", header: "Owner", sortable: true, render: (d) => <span className="muted">{d.owner || "—"}</span> },
    { key: "identified_date", header: "Identified", sortable: true, render: (d) => <span className="muted">{d.identified_date || "—"}</span> },
    { key: "target_date", header: "Target", sortable: true, render: (d) => <span className="muted">{d.target_date || "—"}</span> },
    {
      key: "actions",
      header: "",
      render: (d) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => removeDef(d)}>Delete</button>
        </div>
      ),
    },
  ];

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
          <AsyncSelect
            search={searchProcesses}
            value={df.process_id || null}
            selectedLabel={df.process_label || undefined}
            onChange={(v, opt) => setDf((p) => ({ ...p, process_id: v ?? "", process_label: opt?.label ?? "" }))}
            placeholder="Unlinked"
          />
        </Field>
        <Field label="Control" help="The RCM control this deficiency relates to.">
          <AsyncSelect
            search={searchControls}
            value={df.control_id || null}
            selectedLabel={df.control_label || undefined}
            onChange={(v, opt) => setDf((p) => ({ ...p, control_id: v ?? "", control_label: opt?.label ?? "" }))}
            placeholder="Unlinked"
          />
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
            onClick={() => {
              if (s.id !== "processes") setOpenId(null);
              setSection(s.id);
            }}
            type="button"
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= PROCESS & RCM */}
      {section === "processes" && (
        <DataTable<IcfrProcess>
          columns={processColumns}
          fetcher={fetchProcesses}
          rowKey={(p) => p.id}
          onRowClick={(p) => setOpenId(p.id)}
          activeKey={openId}
          searchPlaceholder="Search processes by name or reference…"
          emptyMessage="No ICFR processes yet. Map the financial-reporting process universe, then build a Risk-Control Matrix for each."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= DEFICIENCIES */}
      {section === "deficiencies" && (
        <DataTable<IcfrDeficiency>
          columns={defColumns}
          fetcher={fetchDeficiencies}
          rowKey={(d) => d.id}
          onRowClick={(d) => openEditDef(d)}
          searchPlaceholder="Search deficiencies by title or reference…"
          emptyMessage="No deficiencies logged. Record control deficiencies from testing and evaluate each severity."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= PROCESS / RCM DRAWER */}
      <RecordDrawer
        open={section === "processes" && !!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference || "PRC"} — ${detail.name}` : "…"}
        subtitle={
          detail
            ? `${cap(detail.status)} · ${detail.cycle || "no cycle"}${detail.owner ? " · owner " + detail.owner : ""}${detail.key_process ? " · key process" : ""}`
            : ""
        }
        width={900}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditProcess(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeProcess(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              <Badge tone={PROCESS_STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {detail.key_process && <Badge tone="info">Key process</Badge>}
              <Badge tone="neutral" plain>{detail.control_count} controls · {detail.key_control_count} key</Badge>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Risk-Control Matrix</h3></div>
              <div className="card-pad">
                <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
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
                  <div style={{ width: 200 }}>
                    <label className="label">Enterprise control</label>
                    <AsyncSelect
                      search={searchEnterpriseControls}
                      value={cd.control_id || null}
                      selectedLabel={cd.control_label || undefined}
                      onChange={(v, opt) => setCd((p) => ({ ...p, control_id: v ?? "", control_label: opt?.label ?? "" }))}
                      placeholder="Link control"
                    />
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
                      {detail.controls.map((c) => (
                        <Fragment key={c.id}>
                          <tr style={{ cursor: "pointer" }} onClick={() => toggleControl(c.id)}>
                            <td className="ref">{c.reference || "—"}</td>
                            <td className="cell-title">
                              {c.title}
                              {c.control && (
                                <div style={{ marginTop: 4 }} onClick={(ev) => ev.stopPropagation()}>
                                  <RelatedChips label="Enterprise control" items={[c.control]} href="/controls" />
                                </div>
                              )}
                            </td>
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
                      {detail.controls.length === 0 && (
                        <tr><td colSpan={9}><span className="muted">No controls in the RCM yet.</span></td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <RecordPanels model="icfr_process" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

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

export default function IcfrPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <IcfrInner />
    </Suspense>
  );
}
