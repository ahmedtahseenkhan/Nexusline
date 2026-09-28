"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall, type Page } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import RecordApproval from "@/components/RecordApproval";
import FormModal from "@/components/FormModal";
import { useCustomFieldForm } from "@/components/useCustomFieldForm";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import ConnectorFeed from "@/components/ConnectorFeed";
import AsyncSelect from "@/components/AsyncSelect";
import ParamFields from "@/components/ccm/ParamFields";
import RunHistory from "@/components/ccm/RunHistory";
import { initialParams, KRI_METRIC_LABEL, paramsPayload, type CheckType, type ConnectorKind, type ParamValues } from "@/lib/ccm";
import { titleCase } from "@/lib/text";
import { safeLinkUrl } from "@/lib/sanitize";
import { useFormat } from "@/lib/format";

// ------------------------------------------------------------------ local types
interface Connector {
  id: string;
  reference: string;
  name: string;
  connector_type: string;
  description: string;
  endpoint_url: string;
  auth_method: string;
  sync_frequency: string;
  owner: string;
  config_note: string;
  status: string;
  last_sync: string | null;
  workflow_status: string;
  is_stale: boolean;
  created_at: string;
  /** A monitoring-feed token is live (the token itself is never returned). */
  has_ingest_token?: boolean;
  /** Phase 4: non-secret settings for the connector type. */
  config?: Record<string, unknown>;
  timeout_seconds?: number;
  /** Names of the secrets on file — never their values. */
  secrets_set?: string[];
  kind?: string;
  last_test_at?: string | null;
  last_test_ok?: boolean | null;
  last_test_message?: string;
}
interface ControlTestRun {
  id: string;
  test_id: string;
  run_date: string | null;
  result: string;
  findings: string;
  evidence_ref: string;
  pass_rate: number;
  created_at: string;
  /** manual | scheduled | run_now | upload | push */
  source?: string;
}
interface AutomatedControlTest {
  id: string;
  reference: string;
  name: string;
  control_ref: string;
  connector_id: string | null;
  description: string;
  test_logic: string;
  frequency: string;
  owner: string;
  last_run: string | null;
  last_result: string;
  pass_rate: number;
  status: string;
  workflow_status: string;
  run_count: number;
  created_at: string;
  runs: ControlTestRun[];
  // Phase 4: the executable definition.
  control_id?: string | null;
  check_type?: string;
  parameters?: Record<string, unknown>;
  threshold_max_failures?: number | null;
  threshold_max_percent?: number | null;
  population_description?: string;
  pass_criterion?: string;
  kri_id?: string | null;
  kri_metric?: string;
  last_run_at?: string | null;
  failing_since?: string | null;
  last_error?: string;
  issue_id?: string | null;
  is_executable?: boolean;
  is_overdue?: boolean;
}
interface IntegrationsSummary {
  total_connectors: number;
  active_connectors: number;
  error_connectors: number;
  stale_connectors: number;
  total_tests: number;
  tests_by_result: Record<string, number>;
  avg_pass_rate: number;
  failing_tests: number;
  executable_tests?: number;
  overdue_tests?: number;
  error_tests?: number;
  controls_failing_monitoring?: number;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

// ------------------------------------------------------------------ enum lists
const CONNECTOR_TYPE = opts([
  "active_directory",
  "azure_ad",
  "o365",
  "siem",
  "edr_crowdstrike",
  "cmdb",
  "core_banking",
  "cloud_aws",
  "cloud_azure",
  "webhook",
  "csv_feed",
  "api",
  "vuln_scanner",
]);
const CONNECTOR_STATUS = opts(["configured", "active", "error", "disabled"]);
const CCM_RESULT = opts(["passed", "failed", "error", "not_run"]);
const KRI_METRICS: Option[] = Object.entries(KRI_METRIC_LABEL).map(([value, label]) => ({ value, label }));
const CCM_STATUS = opts(["active", "paused"]);
const FREQ = opts(["none", "daily", "weekly", "fortnightly", "monthly", "quarterly", "semiannual", "annual"]);

// ------------------------------------------------------------------ tones
const CONNECTOR_STATUS_TONE: Record<string, Tone> = {
  configured: "neutral",
  active: "low",
  error: "critical",
  disabled: "neutral",
};
const RESULT_TONE: Record<string, Tone> = {
  passed: "low",
  failed: "critical",
  error: "high",
  not_run: "neutral",
};
const CCM_STATUS_TONE: Record<string, Tone> = {
  active: "low",
  paused: "neutral",
};

function ResultBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={RESULT_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

function PassRateBar({ value }: { value: number | null | undefined }) {
  const pct = Math.max(0, Math.min(100, Number(value || 0)));
  const tone = pct >= 90 ? "var(--ok, #1f9d55)" : pct >= 70 ? "var(--warn, #c98a00)" : "var(--danger, #c0392b)";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 120 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 4, background: "var(--border, #e2e5ea)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: tone }} />
      </div>
      <span className="muted" style={{ fontSize: 12, minWidth: 34, textAlign: "right" }}>{pct.toFixed(0)}%</span>
    </div>
  );
}

// ------------------------------------------------------------------ connector form state
type ConnectorForm = {
  name: string;
  connector_type: string;
  description: string;
  endpoint_url: string;
  auth_method: string;
  sync_frequency: string;
  owner: string;
  config_note: string;
  status: string;
  last_sync: string;
  config: ParamValues;
  timeout_seconds: string;
  /** Write-only: a typed value replaces the stored secret; blank keeps it. */
  secrets: Record<string, string>;
  clear_secrets: string[];
};
const BLANK_CONNECTOR: ConnectorForm = {
  name: "",
  connector_type: "active_directory",
  description: "",
  endpoint_url: "",
  auth_method: "",
  sync_frequency: "monthly",
  owner: "",
  config_note: "",
  status: "configured",
  last_sync: "",
  config: {},
  timeout_seconds: "30",
  secrets: {},
  clear_secrets: [],
};
function fromConnector(c: Connector): ConnectorForm {
  return {
    name: c.name,
    connector_type: c.connector_type || "active_directory",
    description: c.description || "",
    endpoint_url: c.endpoint_url || "",
    auth_method: c.auth_method || "",
    sync_frequency: c.sync_frequency || "monthly",
    owner: c.owner || "",
    config_note: c.config_note || "",
    status: c.status || "configured",
    last_sync: c.last_sync || "",
    config: { ...(c.config || {}) },
    timeout_seconds: String(c.timeout_seconds ?? 30),
    secrets: {},
    clear_secrets: [],
  };
}
function connectorPayload(f: ConnectorForm, kind: ConnectorKind | undefined): Record<string, unknown> {
  const { params: config, errors } = paramsPayload(kind?.config_fields ?? [], f.config);
  if (errors.length) throw new Error(errors.join(" "));
  const secrets = Object.fromEntries(Object.entries(f.secrets).filter(([, v]) => v.trim() !== ""));
  return {
    config,
    timeout_seconds: Number(f.timeout_seconds) || 30,
    ...(Object.keys(secrets).length ? { secrets } : {}),
    ...(f.clear_secrets.length ? { clear_secrets: f.clear_secrets } : {}),
    name: f.name,
    connector_type: f.connector_type,
    description: f.description,
    endpoint_url: f.endpoint_url,
    auth_method: f.auth_method,
    sync_frequency: f.sync_frequency,
    owner: f.owner,
    config_note: f.config_note,
    status: f.status,
    last_sync: f.last_sync || null,
  };
}

// ------------------------------------------------------------------ ccm test form state
type CctForm = {
  name: string;
  control_ref: string;
  connector_id: string;
  description: string;
  test_logic: string;
  frequency: string;
  owner: string;
  status: string;
  control_id: string;
  control_label: string;
  check_type: string;
  parameters: ParamValues;
  threshold_max_failures: string;
  threshold_max_percent: string;
  pass_criterion: string;
  population_description: string;
  kri_id: string;
  kri_label: string;
  kri_metric: string;
};
const BLANK_CCT: CctForm = {
  name: "",
  control_ref: "",
  connector_id: "",
  description: "",
  test_logic: "",
  frequency: "monthly",
  owner: "",
  status: "active",
  control_id: "",
  control_label: "",
  check_type: "manual",
  parameters: {},
  threshold_max_failures: "",
  threshold_max_percent: "",
  pass_criterion: "",
  population_description: "",
  kri_id: "",
  kri_label: "",
  kri_metric: "exceptions",
};
function fromCct(t: AutomatedControlTest): CctForm {
  return {
    name: t.name,
    control_ref: t.control_ref || "",
    connector_id: t.connector_id || "",
    description: t.description || "",
    test_logic: t.test_logic || "",
    frequency: t.frequency || "monthly",
    owner: t.owner || "",
    status: t.status || "active",
    control_id: t.control_id || "",
    control_label: t.control_ref || "",
    check_type: t.check_type || "manual",
    parameters: { ...(t.parameters || {}) },
    threshold_max_failures: t.threshold_max_failures == null ? "" : String(t.threshold_max_failures),
    threshold_max_percent: t.threshold_max_percent == null ? "" : String(t.threshold_max_percent),
    pass_criterion: t.pass_criterion || "",
    population_description: t.population_description || "",
    kri_id: t.kri_id || "",
    kri_label: t.kri_id ? "Linked KRI" : "",
    kri_metric: t.kri_metric || "exceptions",
  };
}
function cctPayload(f: CctForm, check: CheckType | undefined): Record<string, unknown> {
  const { params, errors } = paramsPayload(check?.params ?? [], f.parameters);
  const metricOnly = Boolean(f.parameters.metric_only);
  if (errors.length) throw new Error(errors.join(" "));
  return {
    control_id: f.control_id || null,
    check_type: f.check_type || "manual",
    parameters: metricOnly ? { ...params, metric_only: true } : params,
    threshold_max_failures: f.threshold_max_failures === "" ? null : Number(f.threshold_max_failures),
    threshold_max_percent: f.threshold_max_percent === "" ? null : Number(f.threshold_max_percent),
    pass_criterion: f.pass_criterion,
    population_description: f.population_description,
    kri_id: f.kri_id || null,
    kri_metric: f.kri_metric || "exceptions",
    name: f.name,
    control_ref: f.control_ref,
    connector_id: f.connector_id || null,
    description: f.description,
    test_logic: f.test_logic,
    frequency: f.frequency,
    owner: f.owner,
    status: f.status,
  };
}

// ------------------------------------------------------------------ run draft
type RunDraft = {
  run_date: string;
  result: string;
  pass_rate: string;
  findings: string;
  evidence_ref: string;
};
const BLANK_RUN: RunDraft = {
  run_date: "",
  result: "passed",
  pass_rate: "100",
  findings: "",
  evidence_ref: "",
};

type SectionId = "connectors" | "ccm";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "connectors", label: "Connectors" },
  { id: "ccm", label: "Continuous Controls Monitoring" },
];

function IntegrationsInner() {
  const [section, setSection] = useState<SectionId>("connectors");
  const { formatDate, formatDateTime } = useFormat();
  const [error, setError] = useState<string | null>(null);
  // Read-only detail loaded for the connector view drawer (?id=).
  const [recordId, setRecordId] = useRecordParam("id");
  const [detail, setDetail] = useState<Connector | null>(null);
  const [connectorsKey, setConnectorsKey] = useState(0);
  const [testsKey, setTestsKey] = useState(0);
  const [connectorStatus, setConnectorStatus] = useState("");
  const [testStatus, setTestStatus] = useState("");

  // Connectors are also kept as a flat list to power the CCM connector dropdown and
  // the connector-name lookup in the tests table (independent of the paged table view).
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [summary, setSummary] = useState<IntegrationsSummary | null>(null);
  // Phase 4: server specs for connector settings and check types.
  const [kinds, setKinds] = useState<ConnectorKind[]>([]);
  const [checkTypes, setCheckTypes] = useState<CheckType[]>([]);
  const [testParam, setTestParam] = useRecordParam("test");
  const [runParam] = useRecordParam("run");
  const [testingConnection, setTestingConnection] = useState(false);
  const kindOf = (type: string) => kinds.find((k) => k.connector_type === type);
  const checkOf = (key: string | undefined) => checkTypes.find((c) => c.key === (key || "manual"));

  const reloadConnectors = useCallback(() => setConnectorsKey((k) => k + 1), []);
  const reloadTests = useCallback(() => setTestsKey((k) => k + 1), []);
  const fetchConnectors = useCallback((qs: string) => apiCall<PagedList<Connector>>("GET", `/connectors?${qs}`), []);
  const fetchTests = useCallback((qs: string) => apiCall<PagedList<AutomatedControlTest>>("GET", `/automated-control-tests?${qs}`), []);

  // ---- connector dialog ----
  const [editingConnector, setEditingConnector] = useState<Connector | null>(null);
  const [showConnectorForm, setShowConnectorForm] = useState(false);
  const [savingConnector, setSavingConnector] = useState(false);
  const [cf, setCf] = useState<ConnectorForm>(BLANK_CONNECTOR);
  const connectorCfForm = useCustomFieldForm("connector");
  const setC = <K extends keyof ConnectorForm>(k: K, v: ConnectorForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ---- ccm test dialog ----
  const [editingCct, setEditingCct] = useState<AutomatedControlTest | null>(null);
  const [showCctForm, setShowCctForm] = useState(false);
  const [savingCct, setSavingCct] = useState(false);
  const [tf, setTf] = useState<CctForm>(BLANK_CCT);
  const cctCfForm = useCustomFieldForm("automated_control_test");
  const setT = <K extends keyof CctForm>(k: K, v: CctForm[K]) => setTf((p) => ({ ...p, [k]: v }));

  // ---- expanded test detail + inline run add-form ----
  const [openTest, setOpenTest] = useState<AutomatedControlTest | null>(null);
  const [rd, setRd] = useState<RunDraft>(BLANK_RUN);
  const setRD = <K extends keyof RunDraft>(k: K, v: RunDraft[K]) => setRd((p) => ({ ...p, [k]: v }));

  const connectorName = (id: string | null) => {
    if (!id) return "—";
    const c = connectors.find((x) => x.id === id);
    return c ? `${c.reference} — ${c.name}` : "—";
  };
  const CONNECTOR_OPTS: Option[] = connectors.map((c) => ({ value: c.id, label: `${c.reference || "?"} — ${c.name}` }));

  // read-only helper for the view drawer
  const field = (label: string, value: React.ReactNode) => (
    <div style={{ minWidth: 140 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
      <div style={{ marginTop: 3 }}>{value ?? <span className="muted">—</span>}</div>
    </div>
  );

  // ------------------------------------------------------------- loaders
  async function loadConnectors() {
    try {
      const res = await apiCall<Page<Connector>>("GET", "/connectors?limit=200");
      setConnectors(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load connectors");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<IntegrationsSummary>("GET", "/integrations-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }
  async function refreshTest(id: string) {
    const t = await apiCall<AutomatedControlTest>("GET", `/automated-control-tests/${id}`);
    setOpenTest(t);
  }

  // Deep-link view: ?id= (row click, global search, ⌘K) loads the connector's full
  // detail into the read-only drawer. Editing is a separate action from there.
  const loadConnectorDetail = useCallback((id: string) => {
    apiCall<Connector>("GET", `/connectors/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);

  useEffect(() => {
    loadConnectors();
    loadSummary();
    apiCall<ConnectorKind[]>("GET", "/ccm/connector-types").then(setKinds).catch(() => setKinds([]));
    apiCall<CheckType[]>("GET", "/ccm/check-types").then(setCheckTypes).catch(() => setCheckTypes([]));
  }, []);

  // ?test=<id> (from a control's Monitoring section or an evidence link) opens that test.
  useEffect(() => {
    if (!testParam) return;
    setSection("ccm");
    apiCall<AutomatedControlTest>("GET", `/automated-control-tests/${testParam}`).then(setOpenTest).catch(() => setOpenTest(null));
  }, [testParam]);

  useEffect(() => {
    if (recordId) loadConnectorDetail(recordId);
    else setDetail(null);
  }, [recordId, loadConnectorDetail]);

  // ------------------------------------------------------------- connector CRUD
  function openNewConnector() {
    setEditingConnector(null);
    setCf(BLANK_CONNECTOR);
    connectorCfForm.start(null);
    setShowConnectorForm(true);
  }
  function openEditConnector(c: Connector) {
    setEditingConnector(c);
    setCf(fromConnector(c));
    connectorCfForm.start(c.id);
    setShowConnectorForm(true);
  }
  async function saveConnector() {
    setError(null);
    setSavingConnector(true);
    try {
      const payload = connectorPayload(cf, kindOf(cf.connector_type));
      const saved = editingConnector
        ? await apiCall<Connector>("PATCH", `/connectors/${editingConnector.id}`, payload)
        : await apiCall<Connector>("POST", "/connectors", payload);
      await connectorCfForm.save(saved.id);
      setShowConnectorForm(false);
      await loadConnectors();
      reloadConnectors();
      await loadSummary();
      if (recordId) loadConnectorDetail(recordId); // refresh the open view drawer
      toast(editingConnector ? "Changes saved" : "Connector created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save connector");
    } finally {
      setSavingConnector(false);
    }
  }
  async function removeConnector(c: Connector) {
    if (!(await confirmDialog({ title: `Delete connector ${c.reference || c.name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/connectors/${c.id}`);
      setShowConnectorForm(false);
      if (recordId === c.id) setRecordId(null);
      await loadConnectors();
      reloadConnectors();
      await loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- ccm test CRUD
  function openNewCct() {
    setEditingCct(null);
    setTf(BLANK_CCT);
    cctCfForm.start(null);
    setShowCctForm(true);
  }
  function openEditCct(t: AutomatedControlTest) {
    setEditingCct(t);
    setTf(fromCct(t));
    cctCfForm.start(t.id);
    setShowCctForm(true);
  }
  async function saveCct() {
    setError(null);
    setSavingCct(true);
    try {
      const payload = cctPayload(tf, checkOf(tf.check_type));
      const saved = editingCct
        ? await apiCall<AutomatedControlTest>("PATCH", `/automated-control-tests/${editingCct.id}`, payload)
        : await apiCall<AutomatedControlTest>("POST", "/automated-control-tests", payload);
      await cctCfForm.save(saved.id);
      setShowCctForm(false);
      reloadTests();
      if (openTest) await refreshTest(openTest.id);
      await loadSummary();
      toast(editingCct ? "Changes saved" : "Control test created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save control test");
    } finally {
      setSavingCct(false);
    }
  }
  async function removeCct(t: AutomatedControlTest) {
    if (!(await confirmDialog({ title: `Delete control test ${t.reference || t.name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/automated-control-tests/${t.id}`);
      setShowCctForm(false);
      if (openTest?.id === t.id) setOpenTest(null);
      reloadTests();
      await loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  async function toggleTest(t: AutomatedControlTest) {
    setRd(BLANK_RUN);
    if (openTest?.id === t.id) { setOpenTest(null); if (testParam) setTestParam(null); return; }
    await refreshTest(t.id);
  }

  async function testConnection(c: Connector) {
    setTestingConnection(true);
    setError(null);
    try {
      const res = await apiCall<{ ok: boolean; message: string }>("POST", `/connectors/${c.id}/test-connection`);
      toast(res.ok ? "Connected" : "Connection failed");
      loadConnectorDetail(c.id);
      reloadConnectors();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connection test failed");
    } finally {
      setTestingConnection(false);
    }
  }

  const searchControls = (q: string) =>
    apiCall<PagedList<{ id: string; reference: string; name: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`)
      .then((r) => r.items.map((x) => ({ value: x.id, label: `${x.reference ? x.reference + " · " : ""}${x.name}` })));
  const searchKris = (q: string) =>
    apiCall<PagedList<{ id: string; reference: string; name: string; unit?: string }>>("GET", `/kris?search=${encodeURIComponent(q)}&limit=20`)
      .then((r) => r.items.map((x) => ({ value: x.id, label: `${x.reference ? x.reference + " · " : ""}${x.name}`, sub: x.unit || undefined })));

  // ------------------------------------------------------------- runs (inline)
  async function addRun() {
    if (!openTest) return;
    setError(null);
    try {
      await apiCall<AutomatedControlTest>("POST", `/automated-control-tests/${openTest.id}/runs`, {
        run_date: rd.run_date || null,
        result: rd.result,
        pass_rate: rd.pass_rate === "" ? 0 : Number(rd.pass_rate),
        findings: rd.findings,
        evidence_ref: rd.evidence_ref,
      });
      setRd(BLANK_RUN);
      await refreshTest(openTest.id);
      reloadTests();
      await loadSummary();
      toast("Run recorded");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record run");
    }
  }
  async function removeRun(runId: string) {
    if (!openTest) return;
    if (!(await confirmDialog({ title: "Remove this run?", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/control-test-runs/${runId}`);
      await refreshTest(openTest.id);
      reloadTests();
      await loadSummary();
      toast("Run removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove run");
    }
  }

  // ------------------------------------------------------------- connector form tabs
  const connectorGeneral = (
    <>
      <Field label="Name" required help="For example: Corporate Active Directory.">
        <TextInput value={cf.name} onChange={(v) => setC("name", v)} placeholder="Connector name" required />
      </Field>
      <div className="field-row">
        <Field label="Connector type" help="The kind of source this connector integrates with.">
          <Select value={cf.connector_type} onChange={(v) => setC("connector_type", v)} options={CONNECTOR_TYPE} />
        </Field>
        <Field label="Status">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={CONNECTOR_STATUS} />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={cf.description} onChange={(v) => setC("description", v)} rows={3} placeholder="What this connector pulls in and why." />
      </Field>
      <div className="field-row">
        <Field label="Owner" help="Accountable owner for this integration.">
          <TextInput value={cf.owner} onChange={(v) => setC("owner", v)} placeholder="Owner" />
        </Field>
        <Field label="Sync frequency" help="How often the source is expected to sync.">
          <Select value={cf.sync_frequency} onChange={(v) => setC("sync_frequency", v)} options={FREQ} />
        </Field>
      </div>
    </>
  );
  const ckind = kindOf(cf.connector_type);
  const setConfig = (name: string, value: unknown) => setCf((p) => ({ ...p, config: { ...p.config, [name]: value } }));
  const connectorConnection = (
    <>
      {ckind?.note && <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>{ckind.note}</p>}
      {ckind && ckind.config_fields.length > 0 && (
        <ParamFields specs={ckind.config_fields} values={initialParams(ckind.config_fields, cf.config)} onChange={setConfig} />
      )}
      {ckind && ckind.kind !== "push" && (
        <Field label="Timeout (seconds)" help="A run or connection test that takes longer is recorded as an error.">
          <TextInput type="number" value={cf.timeout_seconds} onChange={(v) => setC("timeout_seconds", v)} />
        </Field>
      )}
      {ckind && ckind.secret_fields.length > 0 && (
        <div style={{ padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8, margin: "4px 0 14px" }}>
          <strong style={{ fontSize: 13 }}>Secrets</strong>
          <p className="muted" style={{ margin: "4px 0 10px", fontSize: 12.5 }}>
            Encrypted on the server and never shown again. Leave a field blank to keep what is stored.
          </p>
          {ckind.secret_fields.map((sf) => {
            const isSet = (editingConnector?.secrets_set ?? []).includes(sf.name) && !cf.clear_secrets.includes(sf.name);
            return (
              <Field key={sf.name} label={sf.label} help={isSet ? "Set. Type a new value to replace it." : "Not set."}>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input className="input" type="password" autoComplete="new-password" value={cf.secrets[sf.name] ?? ""}
                    placeholder={isSet ? "••••••••" : ""}
                    onChange={(e) => setCf((p) => ({ ...p, secrets: { ...p.secrets, [sf.name]: e.target.value } }))} />
                  {isSet && (
                    <button type="button" className="btn secondary sm"
                      onClick={() => setCf((p) => ({ ...p, clear_secrets: [...p.clear_secrets, sf.name], secrets: { ...p.secrets, [sf.name]: "" } }))}>
                      Clear
                    </button>
                  )}
                </div>
              </Field>
            );
          })}
        </div>
      )}
      <Field label="Last sync" help="Date of the most recent sync — drives the stale flag (older than 35 days). Runs and the feed set it.">
        <TextInput type="date" value={cf.last_sync} onChange={(v) => setC("last_sync", v)} />
      </Field>
      <Field label="Notes" help="Scopes, owners on the source side, change tickets. Never put secrets here.">
        <TextArea value={cf.config_note} onChange={(v) => setC("config_note", v)} rows={3} placeholder="Connection notes" />
      </Field>
    </>
  );

  // ------------------------------------------------------------- ccm form tabs
  const tcheck = checkOf(tf.check_type);
  const setParam = (name: string, value: unknown) => setTf((p) => ({ ...p, parameters: { ...p.parameters, [name]: value } }));
  const checkOptions: Option[] = checkTypes.map((c) => ({ value: c.key, label: `${c.group} — ${c.label}` }));
  const cctGeneral = (
    <>
      <Field label="Name" required help="For example: Privileged accounts are approved.">
        <TextInput value={tf.name} onChange={(v) => setT("name", v)} placeholder="Control test name" required />
      </Field>
      <div className="field-row">
        <Field label="Control" help="The control this test monitors. Its runs become evidence on it; failures open issues against it.">
          <AsyncSelect search={searchControls} value={tf.control_id || null} selectedLabel={tf.control_label}
            placeholder="Search controls…" onChange={(v, o) => setTf((p) => ({ ...p, control_id: v || "", control_label: o?.label || "" }))} />
        </Field>
        <Field label="Connector" help="The source this test runs against.">
          <Select value={tf.connector_id} onChange={(v) => setT("connector_id", v)} options={CONNECTOR_OPTS} placeholder="No connector" />
        </Field>
      </div>
      {!tf.control_id && (
        <Field label="Control reference" help="Used when no control is picked, and by the monitoring feed to match results.">
          <TextInput value={tf.control_ref} onChange={(v) => setT("control_ref", v)} placeholder="e.g. A.5.18" />
        </Field>
      )}
      <Field label="Description">
        <TextArea value={tf.description} onChange={(v) => setT("description", v)} rows={2} placeholder="Why this control is monitored." />
      </Field>
    </>
  );
  const cctCheck = (
    <>
      <Field label="Check" help="Recorded by hand or pushed: runs come from people or the monitoring feed. Any other check runs on its schedule.">
        <select className="select" value={tf.check_type}
          onChange={(e) => setTf((p) => ({ ...p, check_type: e.target.value, parameters: {} }))}>
          {checkOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </Field>
      {tcheck && tcheck.description && <p className="muted" style={{ margin: "-4px 0 12px", fontSize: 13 }}>{tcheck.description}</p>}
      {tcheck && tcheck.connector_types.length > 0 && (
        <p className="muted" style={{ margin: "-6px 0 12px", fontSize: 12.5 }}>
          Runs on: {tcheck.connector_types.map((t) => cap(t)).join(", ")}{tcheck.input === "file" ? " (from the import folder or an uploaded file)" : ""}.
        </p>
      )}
      {tcheck && <ParamFields specs={tcheck.params} values={initialParams(tcheck.params, tf.parameters)} onChange={setParam} />}
      {tf.check_type !== "manual" && (
        <>
          <div className="field-row">
            <Field label="Most exceptions allowed" help="Blank with no percentage = none allowed.">
              <TextInput type="number" value={tf.threshold_max_failures} onChange={(v) => setT("threshold_max_failures", v)} placeholder="0" />
            </Field>
            <Field label="Most exceptions allowed (% of population)">
              <TextInput type="number" value={tf.threshold_max_percent} onChange={(v) => setT("threshold_max_percent", v)} placeholder="Not set" />
            </Field>
          </div>
          <Field label="Pass criterion" help={tcheck?.pass_criterion ? `Blank = "${tcheck.pass_criterion}"` : "What a passing run means, in words."}>
            <TextArea value={tf.pass_criterion} onChange={(v) => setT("pass_criterion", v)} rows={2} placeholder={tcheck?.pass_criterion} />
          </Field>
          <Field label="Population" help={tcheck?.population ? `Blank = "${tcheck.population}"` : "What the check looks at."}>
            <TextInput value={tf.population_description} onChange={(v) => setT("population_description", v)} placeholder={tcheck?.population} />
          </Field>
          <Toggle checked={Boolean(tf.parameters.metric_only)} onChange={(v) => setParam("metric_only", v)}
            label="Metric only: post the numbers to the KRI, never pass or fail and never open an issue" />
        </>
      )}
      <Field label="Test logic (notes)" help="Anything a reviewer should know about how the check works.">
        <TextArea value={tf.test_logic} onChange={(v) => setT("test_logic", v)} rows={2} />
      </Field>
    </>
  );
  const cctConfig = (
    <>
      <div className="field-row">
        <Field label="Frequency" help="How often the test runs. A test that has not run for twice this long raises an overdue alert.">
          <Select value={tf.frequency} onChange={(v) => setT("frequency", v)} options={FREQ} />
        </Field>
        <Field label="Status" help="Paused tests do not run and raise no alerts.">
          <Select value={tf.status} onChange={(v) => setT("status", v)} options={CCM_STATUS} />
        </Field>
      </div>
      <Field label="Owner">
        <TextInput value={tf.owner} onChange={(v) => setT("owner", v)} placeholder="Owner" />
      </Field>
      <div className="field-row">
        <Field label="Key risk indicator" help="Each run posts a reading to this KRI through its thresholds and escalation.">
          <AsyncSelect search={searchKris} value={tf.kri_id || null} selectedLabel={tf.kri_label} placeholder="No KRI"
            onChange={(v, o) => setTf((p) => ({ ...p, kri_id: v || "", kri_label: o?.label || "" }))} />
        </Field>
        <Field label="Reading posted">
          <Select value={tf.kri_metric} onChange={(v) => setT("kri_metric", v)} options={KRI_METRICS} />
        </Field>
      </div>
    </>
  );

  // ------------------------------------------------------------- table columns
  const connectorColumns: Column<Connector>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, render: (c) => <span className="cell-title">{c.name}</span> },
    { key: "connector_type", header: "Type", sortable: true, render: (c) => <Badge tone="info">{cap(c.connector_type)}</Badge> },
    { key: "owner", header: "Owner", render: (c) => <span className="muted">{c.owner || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (c) => (
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <Badge tone={CONNECTOR_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge>
        {c.is_stale && <Badge tone="high">Stale</Badge>}
        {c.has_ingest_token && <Badge tone="info" plain>Feed</Badge>}
      </div>
    ) },
    { key: "last_sync", header: "Last sync", sortable: true, render: (c) => <span className="muted">{c.last_sync ? formatDate(c.last_sync) : "never"}</span> },
    { key: "actions", header: "", render: (c) => (
      <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
        <button className="btn secondary sm" onClick={() => openEditConnector(c)}>Edit</button>
        <button className="btn secondary sm" onClick={() => removeConnector(c)}>Delete</button>
      </div>
    ) },
  ];

  const testColumns: Column<AutomatedControlTest>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (t) => <span className="ref">{t.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, render: (t) => <span className="cell-title">{t.name}</span> },
    { key: "control_ref", header: "Control", sortable: true, render: (t) => <span className="muted">{t.control_ref || "—"}</span> },
    { key: "check_type", header: "Check", render: (t) => (
      <span className="muted">{checkOf(t.check_type)?.label ?? "Recorded by hand or pushed"}{t.is_overdue ? <> <Badge tone="medium">Overdue</Badge></> : null}</span>
    ) },
    { key: "connector", header: "Connector", render: (t) => <span className="muted">{connectorName(t.connector_id)}</span> },
    { key: "last_result", header: "Last result", sortable: true, render: (t) => <ResultBadge value={t.last_result} /> },
    { key: "pass_rate", header: "Pass rate", sortable: true, render: (t) => <PassRateBar value={t.pass_rate} /> },
    { key: "last_run", header: "Last run", sortable: true, render: (t) => <span className="muted">{formatDate(t.last_run)}</span> },
    { key: "status", header: "Status", sortable: true, render: (t) => <Badge tone={CCM_STATUS_TONE[t.status] || "neutral"}>{cap(t.status)}</Badge> },
    { key: "actions", header: "", render: (t) => (
      <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
        <button className="btn secondary sm" onClick={() => toggleTest(t)}>{openTest?.id === t.id ? "Hide" : "Runs"}</button>
        <button className="btn secondary sm" onClick={() => openEditCct(t)}>Edit</button>
        <button className="btn secondary sm" onClick={() => removeCct(t)}>Delete</button>
      </div>
    ) },
  ];

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Integrations &amp; Continuous Controls Monitoring</h1>
          <p>A connector registry into the bank&apos;s sources of truth (AD, Azure AD / O365, SIEM, EDR, CMDB, core banking, cloud) plus automated control tests that record pass / fail over time.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "connectors" && (
            <button className="btn" onClick={openNewConnector}>
              <IconPlus width={16} height={16} /> New connector
            </button>
          )}
          {section === "ccm" && (
            <button className="btn" onClick={openNewCct}>
              <IconPlus width={16} height={16} /> New control test
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.active_connectors.toLocaleString() : "—"}</span></div>
          <span className="l">Active connectors</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.error_connectors.toLocaleString() : "—"}</span></div>
          <span className="l">Connectors in error</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.failing_tests.toLocaleString() : "—"}</span></div>
          <span className="l">Failing tests</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? `${summary.avg_pass_rate.toFixed(0)}%` : "—"}</span></div>
          <span className="l">Avg pass rate</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? (summary.overdue_tests ?? 0).toLocaleString() : "—"}</span></div>
          <span className="l">Tests overdue</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
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

      {/* ============================================= CONNECTORS */}
      {section === "connectors" && (
        <DataTable<Connector>
          columns={connectorColumns}
          fetcher={fetchConnectors}
          rowKey={(c) => c.id}
          onRowClick={(c) => setRecordId(c.id)}
          activeKey={recordId ?? undefined}
          searchPlaceholder="Search connectors by name or reference…"
          defaultSort={{ by: "name", dir: "asc" }}
          filters={{ status: connectorStatus || undefined }}
          toolbarRight={
            <select className="input" style={{ maxWidth: 180 }} value={connectorStatus} onChange={(e) => setConnectorStatus(e.target.value)}>
              <option value="">All statuses</option>
              {CONNECTOR_STATUS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          }
          emptyMessage="No connectors. Register an integration into a source of truth (AD, SIEM, EDR, CMDB, core banking, cloud) to power continuous controls monitoring."
          refreshKey={connectorsKey}
        />
      )}

      {/* Read-only connector detail view (?id=) — click a row to see everything; Edit is separate. */}
      <RecordDrawer
        aside={detail ? (
          <>
            <RecordApproval entityType="connector" entityId={detail.id} onChanged={() => { reloadConnectors(); loadConnectorDetail(detail.id); }} />
            <RecordPanels model="connector" entityId={detail.id} />
          </>
        ) : null}
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? `${detail.reference || ""} ${detail.name}`.trim() : "…"}
        subtitle={detail ? cap(detail.connector_type) + " · " + cap(detail.status) : ""}
        width={640}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditConnector(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeConnector(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              {field("Type", <Badge tone="info">{cap(detail.connector_type)}</Badge>)}
              {field("Status", (
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <Badge tone={CONNECTOR_STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
                  {detail.is_stale && <Badge tone="high">Stale</Badge>}
                </div>
              ))}
              {field("Owner", detail.owner || "—")}
            </div>

            {detail.description && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description</div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }}>{detail.description}</div>
              </div>
            )}

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <strong style={{ fontSize: 13 }}>Connection</strong>
              <div style={{ display: "flex", gap: 22, flexWrap: "wrap", margin: "10px 0" }}>
                {field("Endpoint URL", detail.endpoint_url ? (
                  safeLinkUrl(detail.endpoint_url)
                    ? <a href={safeLinkUrl(detail.endpoint_url) ?? undefined} target="_blank" rel="noopener noreferrer">{detail.endpoint_url}</a>
                    : <span>{detail.endpoint_url}</span>
                ) : "—")}
                {field("Auth method", detail.auth_method || "—")}
                {field("Sync frequency", cap(detail.sync_frequency))}
                {field("Last sync", detail.last_sync ? formatDate(detail.last_sync) : "never")}
              </div>
              {detail.config_note && (
                <div style={{ fontSize: 13.5, lineHeight: 1.5 }}>
                  <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Config note</div>
                  {detail.config_note}
                </div>
              )}
            </div>

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 8 }}>
              {field("Created", formatDateTime(detail.created_at))}
            </div>

            {kindOf(detail.connector_type) && kindOf(detail.connector_type)!.kind !== "push" && (
              <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
                <div className="row-between" style={{ gap: 8, flexWrap: "wrap" }}>
                  <strong style={{ fontSize: 13 }}>Pull settings</strong>
                  <button type="button" className="btn secondary sm" disabled={testingConnection} onClick={() => testConnection(detail)}>
                    {testingConnection ? "Testing…" : "Test connection"}
                  </button>
                </div>
                <div style={{ display: "flex", gap: 22, flexWrap: "wrap", margin: "10px 0 6px" }}>
                  {kindOf(detail.connector_type)!.config_fields
                    .filter((f) => detail.config?.[f.name] !== undefined && detail.config?.[f.name] !== "")
                    .map((f) => <div key={f.name}>{field(f.label, String(detail.config?.[f.name]))}</div>)}
                  {field("Secrets", (detail.secrets_set ?? []).length ? `Set: ${(detail.secrets_set ?? []).join(", ")}` : "None set")}
                  {field("Timeout", `${detail.timeout_seconds ?? 30} s`)}
                </div>
                {detail.last_test_at ? (
                  <div className={detail.last_test_ok ? "muted" : "error"} style={{ fontSize: 13 }}>
                    {detail.last_test_ok ? "Connected" : "Failed"} on {formatDateTime(detail.last_test_at)}: {detail.last_test_message}
                  </div>
                ) : (
                  <div className="muted" style={{ fontSize: 13 }}>Not tested yet.</div>
                )}
              </div>
            )}

            <ConnectorFeed connectorId={detail.id} onChanged={() => { reloadConnectors(); loadConnectorDetail(detail.id); }} />

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            </div>
          </>
        )}
      </RecordDrawer>

      {/* ============================================= CCM */}
      {section === "ccm" && (
        <>
          <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
            Click a row to see its runs. Tests with a check run on their schedule (or with Run now) against their connector; tests recorded by hand take runs from people or from a connector&apos;s monitoring feed. The latest run rolls up onto the test&apos;s last result and pass rate.
          </p>
          <DataTable<AutomatedControlTest>
            columns={testColumns}
            fetcher={fetchTests}
            rowKey={(t) => t.id}
            onRowClick={toggleTest}
            activeKey={openTest?.id ?? null}
            searchPlaceholder="Search tests by name, reference or control…"
            defaultSort={{ by: "name", dir: "asc" }}
            filters={{ status: testStatus || undefined }}
            toolbarRight={
              <select className="input" style={{ maxWidth: 180 }} value={testStatus} onChange={(e) => setTestStatus(e.target.value)}>
                <option value="">All statuses</option>
                {CCM_STATUS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            }
            emptyMessage='No control tests. Define an automated control test (e.g. "all privileged accounts have MFA enabled") and record its runs over time.'
            refreshKey={testsKey}
          />
          <div style={{ marginBottom: 16 }} />

          {openTest && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openTest.reference} — {openTest.name}</h3>
                    <span className="sub">
                      {cap(openTest.status)} · {connectorName(openTest.connector_id)}
                      {openTest.owner ? " · owner " + openTest.owner : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                    <div style={{ textAlign: "right" }}>
                      <div className="muted" style={{ fontSize: 12 }}>Latest result</div>
                      <ResultBadge value={openTest.last_result} />
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn secondary sm" onClick={() => openEditCct(openTest)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => removeCct(openTest)}>Delete</button>
                    </div>
                  </div>
                </div>

                <div className="card-pad">
                  <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 12 }}>
                    {field("Check", checkOf(openTest.check_type)?.label ?? "Recorded by hand or pushed")}
                    {field("Runs", cap(openTest.frequency))}
                    {openTest.check_type && openTest.check_type !== "manual" && field("Threshold",
                      openTest.threshold_max_failures == null && openTest.threshold_max_percent == null
                        ? "No exceptions"
                        : [openTest.threshold_max_failures != null ? `at most ${openTest.threshold_max_failures}` : "",
                           openTest.threshold_max_percent != null ? `at most ${openTest.threshold_max_percent}%` : ""].filter(Boolean).join(" and "))}
                    {field("Last run", openTest.last_run_at ? formatDateTime(openTest.last_run_at) : formatDate(openTest.last_run))}
                    {openTest.failing_since && field("Failing since", <Badge tone="critical">{formatDate(openTest.failing_since)}</Badge>)}
                    {openTest.issue_id && field("Issue", <a href={`/issues?id=${openTest.issue_id}`}>Open the issue</a>)}
                    {openTest.is_overdue && field("Schedule", <Badge tone="medium">Overdue</Badge>)}
                  </div>
                  {(openTest.pass_criterion || checkOf(openTest.check_type)?.pass_criterion) && (
                    <p className="muted" style={{ margin: "0 0 8px", fontSize: 13 }}>
                      <strong>Pass criterion:</strong> {openTest.pass_criterion || checkOf(openTest.check_type)?.pass_criterion}
                    </p>
                  )}
                  {openTest.test_logic && (
                    <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
                      <strong>Test logic:</strong> {openTest.test_logic}
                    </p>
                  )}
                  {openTest.last_error && <div className="error" style={{ marginBottom: 12 }}>Last run could not complete: {openTest.last_error}</div>}
                  <strong>Run history</strong>
                  <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                    Each run is evidence on the control. A failed run opens an issue (or updates the open one) and stops risks relying on the control until a run passes; no run changes the control&apos;s effectiveness.
                  </p>
                  <RunHistory
                    key={openTest.id}
                    testId={openTest.id}
                    executable={Boolean(openTest.is_executable)}
                    acceptsFile={["file", "connector_or_file"].includes(checkOf(openTest.check_type)?.input ?? "")}
                    controlId={openTest.control_id ?? null}
                    canWrite
                    openRunId={runParam}
                    onRan={() => { void refreshTest(openTest.id); reloadTests(); void loadSummary(); }}
                  />
                  {!openTest.is_executable && (
                    <>
                      <p className="muted" style={{ margin: "14px 0 8px", fontSize: 13 }}>Record a run by hand:</p>
                      <form
                        style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                        onSubmit={(ev) => { ev.preventDefault(); addRun(); }}
                      >
                        <div style={{ width: 150 }}>
                          <label className="label">Run date</label>
                          <input className="input" type="date" value={rd.run_date} onChange={(ev) => setRD("run_date", ev.target.value)} />
                        </div>
                        <div style={{ width: 140 }}>
                          <label className="label">Result</label>
                          <select className="select" value={rd.result} onChange={(ev) => setRD("result", ev.target.value)}>
                            {CCM_RESULT.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                          </select>
                        </div>
                        <div style={{ width: 120 }}>
                          <label className="label">Pass rate (%)</label>
                          <input className="input" type="number" min={0} max={100} value={rd.pass_rate} onChange={(ev) => setRD("pass_rate", ev.target.value)} />
                        </div>
                        <div style={{ flex: "1 1 200px" }}>
                          <label className="label">Findings</label>
                          <input className="input" value={rd.findings} onChange={(ev) => setRD("findings", ev.target.value)} placeholder="What the run observed" />
                        </div>
                        <div style={{ width: 170 }}>
                          <label className="label">Evidence ref</label>
                          <input className="input" value={rd.evidence_ref} onChange={(ev) => setRD("evidence_ref", ev.target.value)} placeholder="Log / ticket / URL" />
                        </div>
                        <button className="btn">Record</button>
                      </form>
                      {openTest.runs.some((r) => r.source === "manual" || !r.source) && (
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {openTest.runs.filter((r) => !r.source || r.source === "manual").slice(0, 10).map((r) => (
                            <button key={r.id} type="button" className="btn secondary sm" onClick={() => removeRun(r.id)}>
                              Remove run of {formatDate(r.run_date)}
                            </button>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>

              <RecordApproval entityType="automated_control_test" entityId={openTest.id} onChanged={() => { reloadTests(); refreshTest(openTest.id); }} />
              <RecordPanels model="automated_control_test" entityId={openTest.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= MODALS */}
      {showConnectorForm && (
        <FormModal
          title={editingConnector ? `Edit connector — ${editingConnector.reference || editingConnector.name}` : "New connector"}
          wide
          tabs={[
            { id: "general", label: "General", content: connectorGeneral, required: true },
            { id: "connection", label: "Connection", content: connectorConnection },
            ...connectorCfForm.tabs,
          ]}
          onClose={() => setShowConnectorForm(false)}
          onSave={saveConnector}
          saving={savingConnector}
          error={error}
          saveLabel={editingConnector ? "Save changes" : "Create connector"}
          footerLeft={
            editingConnector ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeConnector(editingConnector)}
                disabled={savingConnector}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showCctForm && (
        <FormModal
          title={editingCct ? `Edit control test — ${editingCct.reference || editingCct.name}` : "New control test"}
          wide
          tabs={[
            { id: "general", label: "General", content: cctGeneral, required: true },
            { id: "check", label: "Check", content: cctCheck },
            { id: "config", label: "Schedule & KRI", content: cctConfig },
            ...cctCfForm.tabs,
          ]}
          onClose={() => setShowCctForm(false)}
          onSave={saveCct}
          saving={savingCct}
          error={error}
          saveLabel={editingCct ? "Save changes" : "Create control test"}
          footerLeft={
            editingCct ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeCct(editingCct)}
                disabled={savingCct}
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

export default function IntegrationsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <IntegrationsInner />
    </Suspense>
  );
}
