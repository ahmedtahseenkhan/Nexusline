"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall, type Page } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

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
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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
]);
const CONNECTOR_STATUS = opts(["configured", "active", "error", "disabled"]);
const CCM_RESULT = opts(["passed", "failed", "error", "not_run"]);
const CCM_STATUS = opts(["active", "paused"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

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
  workflow_status: string;
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
  workflow_status: "draft",
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
    workflow_status: c.workflow_status || "draft",
  };
}
function connectorPayload(f: ConnectorForm): Record<string, unknown> {
  return {
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
    workflow_status: f.workflow_status,
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
  workflow_status: string;
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
  workflow_status: "draft",
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
    workflow_status: t.workflow_status || "draft",
  };
}
function cctPayload(f: CctForm): Record<string, unknown> {
  return {
    name: f.name,
    control_ref: f.control_ref,
    connector_id: f.connector_id || null,
    description: f.description,
    test_logic: f.test_logic,
    frequency: f.frequency,
    owner: f.owner,
    status: f.status,
    workflow_status: f.workflow_status,
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

export default function IntegrationsPage() {
  const [section, setSection] = useState<SectionId>("connectors");
  const [error, setError] = useState<string | null>(null);
  const [connectorsKey, setConnectorsKey] = useState(0);
  const [testsKey, setTestsKey] = useState(0);
  const [connectorStatus, setConnectorStatus] = useState("");
  const [testStatus, setTestStatus] = useState("");

  // Connectors are also kept as a flat list to power the CCM connector dropdown and
  // the connector-name lookup in the tests table (independent of the paged table view).
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [summary, setSummary] = useState<IntegrationsSummary | null>(null);

  const reloadConnectors = useCallback(() => setConnectorsKey((k) => k + 1), []);
  const reloadTests = useCallback(() => setTestsKey((k) => k + 1), []);
  const fetchConnectors = useCallback((qs: string) => apiCall<PagedList<Connector>>("GET", `/connectors?${qs}`), []);
  const fetchTests = useCallback((qs: string) => apiCall<PagedList<AutomatedControlTest>>("GET", `/automated-control-tests?${qs}`), []);

  // ---- connector dialog ----
  const [editingConnector, setEditingConnector] = useState<Connector | null>(null);
  const [showConnectorForm, setShowConnectorForm] = useState(false);
  const [savingConnector, setSavingConnector] = useState(false);
  const [cf, setCf] = useState<ConnectorForm>(BLANK_CONNECTOR);
  const setC = <K extends keyof ConnectorForm>(k: K, v: ConnectorForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ---- ccm test dialog ----
  const [editingCct, setEditingCct] = useState<AutomatedControlTest | null>(null);
  const [showCctForm, setShowCctForm] = useState(false);
  const [savingCct, setSavingCct] = useState(false);
  const [tf, setTf] = useState<CctForm>(BLANK_CCT);
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

  useEffect(() => {
    loadConnectors();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- connector CRUD
  function openNewConnector() {
    setEditingConnector(null);
    setCf(BLANK_CONNECTOR);
    setShowConnectorForm(true);
  }
  function openEditConnector(c: Connector) {
    setEditingConnector(c);
    setCf(fromConnector(c));
    setShowConnectorForm(true);
  }
  async function saveConnector() {
    setError(null);
    setSavingConnector(true);
    try {
      const payload = connectorPayload(cf);
      if (editingConnector) await apiCall<Connector>("PATCH", `/connectors/${editingConnector.id}`, payload);
      else await apiCall<Connector>("POST", "/connectors", payload);
      setShowConnectorForm(false);
      await loadConnectors();
      reloadConnectors();
      await loadSummary();
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
    setShowCctForm(true);
  }
  function openEditCct(t: AutomatedControlTest) {
    setEditingCct(t);
    setTf(fromCct(t));
    setShowCctForm(true);
  }
  async function saveCct() {
    setError(null);
    setSavingCct(true);
    try {
      const payload = cctPayload(tf);
      if (editingCct) await apiCall<AutomatedControlTest>("PATCH", `/automated-control-tests/${editingCct.id}`, payload);
      else await apiCall<AutomatedControlTest>("POST", "/automated-control-tests", payload);
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
    if (openTest?.id === t.id) { setOpenTest(null); return; }
    await refreshTest(t.id);
  }

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
  const connectorConnection = (
    <>
      <Field label="Endpoint URL" help="Base URL / host of the source (informational for now).">
        <TextInput value={cf.endpoint_url} onChange={(v) => setC("endpoint_url", v)} placeholder="https://…" />
      </Field>
      <Field label="Auth method" help='For example: "OAuth2 client credentials", "API key", "service account".'>
        <TextInput value={cf.auth_method} onChange={(v) => setC("auth_method", v)} placeholder="OAuth2 / API key / service account" />
      </Field>
      <Field label="Last sync" help="Date of the most recent sync — drives the stale flag (older than 35 days).">
        <TextInput type="date" value={cf.last_sync} onChange={(v) => setC("last_sync", v)} />
      </Field>
      <Field label="Config note" help="Secrets are never stored here — connection notes only.">
        <TextArea value={cf.config_note} onChange={(v) => setC("config_note", v)} rows={3} placeholder="Connection notes, scopes, tenant IDs…" />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this connector record.">
        <Select value={cf.workflow_status} onChange={(v) => setC("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- ccm form tabs
  const cctGeneral = (
    <>
      <Field label="Name" required help="For example: Privileged accounts have MFA enabled.">
        <TextInput value={tf.name} onChange={(v) => setT("name", v)} placeholder="Control test name" required />
      </Field>
      <div className="field-row">
        <Field label="Control reference" help="Free-text link to a control (e.g. AC-2, CIS 5.3).">
          <TextInput value={tf.control_ref} onChange={(v) => setT("control_ref", v)} placeholder="Control ref" />
        </Field>
        <Field label="Connector" help="The source this test runs against (optional).">
          <Select value={tf.connector_id} onChange={(v) => setT("connector_id", v)} options={CONNECTOR_OPTS} placeholder="No connector" />
        </Field>
      </div>
      <Field label="Test logic" help='Plain-language rule, e.g. "all privileged accounts have MFA enabled".'>
        <TextArea value={tf.test_logic} onChange={(v) => setT("test_logic", v)} rows={3} placeholder="What a passing state looks like." />
      </Field>
      <Field label="Description">
        <TextArea value={tf.description} onChange={(v) => setT("description", v)} rows={3} placeholder="Context for this continuous control test." />
      </Field>
    </>
  );
  const cctConfig = (
    <>
      <div className="field-row">
        <Field label="Frequency" help="How often this test is expected to run.">
          <Select value={tf.frequency} onChange={(v) => setT("frequency", v)} options={FREQ} />
        </Field>
        <Field label="Status" help="Whether the test is actively monitored.">
          <Select value={tf.status} onChange={(v) => setT("status", v)} options={CCM_STATUS} />
        </Field>
      </div>
      <Field label="Owner">
        <TextInput value={tf.owner} onChange={(v) => setT("owner", v)} placeholder="Owner" />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this control-test record.">
        <Select value={tf.workflow_status} onChange={(v) => setT("workflow_status", v)} options={WORKFLOW} />
      </Field>
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
      </div>
    ) },
    { key: "last_sync", header: "Last sync", sortable: true, render: (c) => <span className="muted">{c.last_sync || "never"}</span> },
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
    { key: "connector", header: "Connector", render: (t) => <span className="muted">{connectorName(t.connector_id)}</span> },
    { key: "last_result", header: "Last result", sortable: true, render: (t) => <ResultBadge value={t.last_result} /> },
    { key: "pass_rate", header: "Pass rate", sortable: true, render: (t) => <PassRateBar value={t.pass_rate} /> },
    { key: "last_run", header: "Last run", sortable: true, render: (t) => <span className="muted">{t.last_run || "—"}</span> },
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
          <span className="l">Failing controls</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? `${summary.avg_pass_rate.toFixed(0)}%` : "—"}</span></div>
          <span className="l">Avg pass rate</span>
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
          onRowClick={openEditConnector}
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

      {/* ============================================= CCM */}
      {section === "ccm" && (
        <>
          <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
            Runtime execution is manual for now — click a row to record a run; its outcome rolls up onto the test&apos;s last result and pass-rate.
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
                  {openTest.test_logic && (
                    <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
                      <strong>Test logic:</strong> {openTest.test_logic}
                    </p>
                  )}
                  <strong>Run history</strong>
                  <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                    Recorded executions. The most recent run drives the test&apos;s last result and pass-rate.
                  </p>
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

                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Run date</th>
                          <th>Result</th>
                          <th>Pass rate</th>
                          <th>Findings</th>
                          <th>Evidence</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...openTest.runs]
                          .sort((a, b) => (b.run_date || b.created_at || "").localeCompare(a.run_date || a.created_at || ""))
                          .map((r) => (
                            <tr key={r.id}>
                              <td className="muted">{r.run_date || "—"}</td>
                              <td><ResultBadge value={r.result} /></td>
                              <td><PassRateBar value={r.pass_rate} /></td>
                              <td className="muted">{r.findings || "—"}</td>
                              <td className="muted">{r.evidence_ref || "—"}</td>
                              <td>
                                <button className="btn secondary sm" onClick={() => removeRun(r.id)}>Remove</button>
                              </td>
                            </tr>
                          ))}
                        {openTest.runs.length === 0 && (
                          <tr><td colSpan={6}><span className="muted">No runs recorded yet.</span></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

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
            { id: "config", label: "Config", content: cctConfig },
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
