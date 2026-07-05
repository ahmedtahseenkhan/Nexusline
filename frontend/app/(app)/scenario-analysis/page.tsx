"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconGauge } from "@/components/icons";

// ------------------------------------------------------------------ types
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type ScenarioAnalysis = {
  id: string;
  reference: string;
  title: string;
  basel_event_type: string;
  business_line: string;
  description: string;
  frequency_per_year: number;
  typical_loss: number;
  worst_case_loss: number;
  currency: string;
  confidence_level: string;
  participants: string;
  assumptions: string;
  owner: string;
  status: string;
  review_date: string | null;
  workflow_status: string;
  expected_annual_loss: number;
  created_at: string;
};

type CapitalCalculation = {
  id: string;
  reference: string;
  period: string;
  business_indicator: number;
  avg_annual_loss: number;
  currency: string;
  notes: string;
  status: string;
  workflow_status: string;
  bic: number;
  loss_component: number;
  ilm: number;
  orc: number;
  created_at: string;
};

type ScenarioSummary = {
  rows: { basel_event_type: string; count: number; expected_annual_loss: number }[];
  total_expected_annual_loss: number;
  total_count: number;
  approved_count: number;
  latest_capital: {
    reference: string;
    period: string;
    bic: number;
    loss_component: number;
    ilm: number;
    orc: number;
    currency: string;
  } | null;
};

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

// ------------------------------------------------------------------ enum lists
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const SCENARIO_STATUS = opts(["draft", "workshopped", "approved", "closed"]);
const CAPITAL_STATUS = opts(["draft", "final"]);
const BASEL_TYPES = opts([
  "internal_fraud",
  "external_fraud",
  "employment_practices",
  "clients_products_business_practices",
  "damage_to_physical_assets",
  "business_disruption_system_failure",
  "execution_delivery_process_management",
]);

// ------------------------------------------------------------------ tones
const SCENARIO_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  workshopped: "info",
  approved: "low",
  closed: "neutral",
};
const CAPITAL_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  final: "low",
};

// ------------------------------------------------------------------ scenario form state
type ScenarioForm = {
  title: string;
  basel_event_type: string;
  business_line: string;
  description: string;
  frequency_per_year: string;
  typical_loss: string;
  worst_case_loss: string;
  currency: string;
  confidence_level: string;
  participants: string;
  assumptions: string;
  owner: string;
  status: string;
  review_date: string;
  workflow_status: string;
};
const BLANK_SCENARIO: ScenarioForm = {
  title: "",
  basel_event_type: "internal_fraud",
  business_line: "",
  description: "",
  frequency_per_year: "",
  typical_loss: "",
  worst_case_loss: "",
  currency: "PKR",
  confidence_level: "",
  participants: "",
  assumptions: "",
  owner: "",
  status: "draft",
  review_date: "",
  workflow_status: "draft",
};
function fromScenario(s: ScenarioAnalysis): ScenarioForm {
  return {
    title: s.title,
    basel_event_type: s.basel_event_type || "internal_fraud",
    business_line: s.business_line || "",
    description: s.description || "",
    frequency_per_year: s.frequency_per_year != null ? String(s.frequency_per_year) : "",
    typical_loss: s.typical_loss != null ? String(s.typical_loss) : "",
    worst_case_loss: s.worst_case_loss != null ? String(s.worst_case_loss) : "",
    currency: s.currency || "PKR",
    confidence_level: s.confidence_level || "",
    participants: s.participants || "",
    assumptions: s.assumptions || "",
    owner: s.owner || "",
    status: s.status || "draft",
    review_date: s.review_date || "",
    workflow_status: s.workflow_status || "draft",
  };
}
function scenarioPayload(f: ScenarioForm): Record<string, unknown> {
  return {
    title: f.title,
    basel_event_type: f.basel_event_type,
    business_line: f.business_line,
    description: f.description,
    frequency_per_year: f.frequency_per_year === "" ? 0 : Number(f.frequency_per_year),
    typical_loss: f.typical_loss === "" ? 0 : Number(f.typical_loss),
    worst_case_loss: f.worst_case_loss === "" ? 0 : Number(f.worst_case_loss),
    currency: f.currency,
    confidence_level: f.confidence_level,
    participants: f.participants,
    assumptions: f.assumptions,
    owner: f.owner,
    status: f.status,
    review_date: f.review_date || null,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ capital form state
type CapitalForm = {
  period: string;
  business_indicator: string;
  avg_annual_loss: string;
  currency: string;
  notes: string;
  status: string;
  workflow_status: string;
};
const BLANK_CAPITAL: CapitalForm = {
  period: "",
  business_indicator: "",
  avg_annual_loss: "",
  currency: "PKR",
  notes: "",
  status: "draft",
  workflow_status: "draft",
};
function fromCapital(c: CapitalCalculation): CapitalForm {
  return {
    period: c.period || "",
    business_indicator: c.business_indicator != null ? String(c.business_indicator) : "",
    avg_annual_loss: c.avg_annual_loss != null ? String(c.avg_annual_loss) : "",
    currency: c.currency || "PKR",
    notes: c.notes || "",
    status: c.status || "draft",
    workflow_status: c.workflow_status || "draft",
  };
}
function capitalPayload(f: CapitalForm): Record<string, unknown> {
  return {
    period: f.period,
    business_indicator: f.business_indicator === "" ? 0 : Number(f.business_indicator),
    avg_annual_loss: f.avg_annual_loss === "" ? 0 : Number(f.avg_annual_loss),
    currency: f.currency,
    notes: f.notes,
    status: f.status,
    workflow_status: f.workflow_status,
  };
}

type SectionId = "scenarios" | "capital";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "scenarios", label: "Scenario Library" },
  { id: "capital", label: "Capital (SMA)" },
];

export default function ScenarioAnalysisPage() {
  const [section, setSection] = useState<SectionId>("scenarios");
  const [error, setError] = useState<string | null>(null);

  const [scenarios, setScenarios] = useState<ScenarioAnalysis[]>([]);
  const [capitals, setCapitals] = useState<CapitalCalculation[]>([]);
  const [summary, setSummary] = useState<ScenarioSummary | null>(null);

  // ---- scenario filters ----
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  // ---- scenario dialog + expanded detail ----
  const [editingScenario, setEditingScenario] = useState<ScenarioAnalysis | null>(null);
  const [showScenarioForm, setShowScenarioForm] = useState(false);
  const [savingScenario, setSavingScenario] = useState(false);
  const [sf, setSf] = useState<ScenarioForm>(BLANK_SCENARIO);
  const setS = <K extends keyof ScenarioForm>(k: K, v: ScenarioForm[K]) => setSf((p) => ({ ...p, [k]: v }));
  const [openScenario, setOpenScenario] = useState<ScenarioAnalysis | null>(null);

  // ---- capital dialog ----
  const [editingCapital, setEditingCapital] = useState<CapitalCalculation | null>(null);
  const [showCapitalForm, setShowCapitalForm] = useState(false);
  const [savingCapital, setSavingCapital] = useState(false);
  const [cf, setCf] = useState<CapitalForm>(BLANK_CAPITAL);
  const setC = <K extends keyof CapitalForm>(k: K, v: CapitalForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadScenarios(keepOpen?: string) {
    try {
      const qs = new URLSearchParams({ limit: "200" });
      if (search.trim()) qs.set("search", search.trim());
      if (filterType) qs.set("basel_event_type", filterType);
      if (filterStatus) qs.set("status", filterStatus);
      const res = await apiCall<Page<ScenarioAnalysis>>("GET", `/scenario-analyses?${qs.toString()}`);
      setScenarios(res.items);
      if (keepOpen) setOpenScenario(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load scenarios");
    }
  }
  async function loadCapitals() {
    try {
      const res = await apiCall<Page<CapitalCalculation>>("GET", "/capital-calculations?limit=200");
      setCapitals(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load capital calculations");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<ScenarioSummary>("GET", "/scenario-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }

  useEffect(() => {
    loadScenarios();
    loadCapitals();
    loadSummary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // re-query scenarios whenever a filter changes
  useEffect(() => {
    loadScenarios(openScenario?.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, filterType, filterStatus]);

  // ------------------------------------------------------------- scenario CRUD
  function openNewScenario() {
    setEditingScenario(null);
    setSf(BLANK_SCENARIO);
    setShowScenarioForm(true);
  }
  function openEditScenario(s: ScenarioAnalysis) {
    setEditingScenario(s);
    setSf(fromScenario(s));
    setShowScenarioForm(true);
  }
  async function saveScenario() {
    setError(null);
    setSavingScenario(true);
    try {
      const payload = scenarioPayload(sf);
      if (editingScenario) await apiCall("PATCH", `/scenario-analyses/${editingScenario.id}`, payload);
      else await apiCall("POST", "/scenario-analyses", payload);
      setShowScenarioForm(false);
      await loadScenarios(openScenario?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save scenario");
    } finally {
      setSavingScenario(false);
    }
  }
  async function removeScenario(s: ScenarioAnalysis) {
    if (!window.confirm(`Delete scenario ${s.reference || s.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/scenario-analyses/${s.id}`);
      setShowScenarioForm(false);
      if (openScenario?.id === s.id) setOpenScenario(null);
      await loadScenarios();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleScenario(s: ScenarioAnalysis) {
    setOpenScenario(openScenario?.id === s.id ? null : s);
  }

  // ------------------------------------------------------------- capital CRUD
  function openNewCapital() {
    setEditingCapital(null);
    setCf(BLANK_CAPITAL);
    setShowCapitalForm(true);
  }
  function openEditCapital(c: CapitalCalculation) {
    setEditingCapital(c);
    setCf(fromCapital(c));
    setShowCapitalForm(true);
  }
  async function saveCapital() {
    setError(null);
    setSavingCapital(true);
    try {
      const payload = capitalPayload(cf);
      if (editingCapital) await apiCall("PATCH", `/capital-calculations/${editingCapital.id}`, payload);
      else await apiCall("POST", "/capital-calculations", payload);
      setShowCapitalForm(false);
      await loadCapitals();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save calculation");
    } finally {
      setSavingCapital(false);
    }
  }
  async function removeCapital(c: CapitalCalculation) {
    if (!window.confirm(`Delete calculation ${c.reference || c.period}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/capital-calculations/${c.id}`);
      setShowCapitalForm(false);
      await loadCapitals();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- scenario form tabs
  const scenarioTab = (
    <>
      <Field label="Title" required help="For example: Large-scale wire-fraud event.">
        <TextInput value={sf.title} onChange={(v) => setS("title", v)} placeholder="Scenario title" required />
      </Field>
      <div className="field-row">
        <Field label="Basel event type" help="Basel II level-1 loss category.">
          <Select value={sf.basel_event_type} onChange={(v) => setS("basel_event_type", v)} options={BASEL_TYPES} />
        </Field>
        <Field label="Business line">
          <TextInput value={sf.business_line} onChange={(v) => setS("business_line", v)} placeholder="Retail banking" />
        </Field>
      </div>
      <Field label="Description" help="What happens in this scenario and how it unfolds.">
        <TextArea value={sf.description} onChange={(v) => setS("description", v)} rows={3} placeholder="Scenario narrative." />
      </Field>
      <div className="field-row">
        <Field label="Status">
          <Select value={sf.status} onChange={(v) => setS("status", v)} options={SCENARIO_STATUS} />
        </Field>
        <Field label="Workflow" help="Approval lifecycle for this scenario record.">
          <Select value={sf.workflow_status} onChange={(v) => setS("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );
  const estimatesTab = (
    <>
      <div className="field-row">
        <Field label="Frequency per year" help="Expected occurrences per year (e.g. 0.25 = once in 4 years).">
          <TextInput type="number" value={sf.frequency_per_year} onChange={(v) => setS("frequency_per_year", v)} placeholder="0" />
        </Field>
        <Field label="Confidence level" help="Confidence in the estimates, e.g. 95%.">
          <TextInput value={sf.confidence_level} onChange={(v) => setS("confidence_level", v)} placeholder="95%" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Typical loss (PKR)" help="Expected loss per occurrence.">
          <TextInput type="number" value={sf.typical_loss} onChange={(v) => setS("typical_loss", v)} placeholder="0" />
        </Field>
        <Field label="Worst-case loss (PKR)" help="Severe but plausible loss per occurrence.">
          <TextInput type="number" value={sf.worst_case_loss} onChange={(v) => setS("worst_case_loss", v)} placeholder="0" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Currency">
          <TextInput value={sf.currency} onChange={(v) => setS("currency", v)} placeholder="PKR" />
        </Field>
        <Field label="Review date" help="When this scenario should be re-workshopped.">
          <TextInput type="date" value={sf.review_date} onChange={(v) => setS("review_date", v)} />
        </Field>
      </div>
      <p className="muted" style={{ fontSize: 13 }}>
        Expected annual loss = frequency per year × typical loss.
      </p>
    </>
  );
  const workshopTab = (
    <>
      <Field label="Owner" help="Risk owner accountable for this scenario.">
        <TextInput value={sf.owner} onChange={(v) => setS("owner", v)} placeholder="Owner" />
      </Field>
      <Field label="Participants" help="Workshop participants / subject-matter experts.">
        <TextArea value={sf.participants} onChange={(v) => setS("participants", v)} rows={2} placeholder="Names / functions present at the workshop." />
      </Field>
      <Field label="Assumptions" help="Key assumptions behind the frequency and loss estimates.">
        <TextArea value={sf.assumptions} onChange={(v) => setS("assumptions", v)} rows={3} placeholder="Assumptions and drivers." />
      </Field>
    </>
  );

  // ------------------------------------------------------------- capital form tab
  const capitalTab = (
    <>
      <Field label="Period" required help="Reporting period, e.g. FY2026.">
        <TextInput value={cf.period} onChange={(v) => setC("period", v)} placeholder="FY2026" required />
      </Field>
      <Field label="Business Indicator — BI (PKR)" help="The Basel Business Indicator (interest, services & financial components).">
        <TextInput type="number" value={cf.business_indicator} onChange={(v) => setC("business_indicator", v)} placeholder="0" />
      </Field>
      <Field label="Average annual loss (PKR)" help="10-year average of internal operational losses (drives the Loss Component).">
        <TextInput type="number" value={cf.avg_annual_loss} onChange={(v) => setC("avg_annual_loss", v)} placeholder="0" />
      </Field>
      <div className="field-row">
        <Field label="Currency">
          <TextInput value={cf.currency} onChange={(v) => setC("currency", v)} placeholder="PKR" />
        </Field>
        <Field label="Status">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={CAPITAL_STATUS} />
        </Field>
      </div>
      <Field label="Notes">
        <TextArea value={cf.notes} onChange={(v) => setC("notes", v)} rows={3} placeholder="Basis of preparation, data sources, sign-off." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this calculation record.">
        <Select value={cf.workflow_status} onChange={(v) => setC("workflow_status", v)} options={WORKFLOW} />
      </Field>
      <p className="muted" style={{ fontSize: 13 }}>
        BIC, Loss Component, ILM and ORC are computed server-side under the Basel III Standardised Approach.
      </p>
    </>
  );

  const latestOrc = summary?.latest_capital?.orc ?? null;

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Scenario Analysis &amp; Capital</h1>
          <p>Forward-looking operational-risk scenarios and Basel III Standardised Approach (SMA) capital.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "scenarios" && (
            <button className="btn" onClick={openNewScenario}>
              <IconPlus width={16} height={16} /> New scenario
            </button>
          )}
          {section === "capital" && (
            <button className="btn" onClick={openNewCapital}>
              <IconPlus width={16} height={16} /> New calculation
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.total_count.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Scenarios</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.total_expected_annual_loss.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Total expected annual loss (PKR)</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{latestOrc != null ? latestOrc.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Latest ORC (PKR)</span>
        </div>
        <div className="card stat">
          <div className="stat-top">
            <span className="n">{summary ? summary.approved_count.toLocaleString() : "—"}</span>
          </div>
          <span className="l">Approved scenarios</span>
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

      {/* ============================================= SCENARIO LIBRARY */}
      {section === "scenarios" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head row-between">
              <div>
                <h3>Scenario Library</h3>
                <span className="sub">{scenarios.length} shown · click a row to expand</span>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  className="input"
                  style={{ width: 200 }}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search scenarios…"
                />
                <select className="select" style={{ width: 200 }} value={filterType} onChange={(e) => setFilterType(e.target.value)}>
                  <option value="">All event types</option>
                  {BASEL_TYPES.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                </select>
                <select className="select" style={{ width: 150 }} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
                  <option value="">All statuses</option>
                  {SCENARIO_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                </select>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Title</th>
                    <th>Basel event type</th>
                    <th>Business line</th>
                    <th>Freq/yr</th>
                    <th>Expected annual loss</th>
                    <th>Worst case</th>
                    <th>Status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {scenarios.map((s) => (
                    <tr key={s.id} style={{ cursor: "pointer" }} onClick={() => toggleScenario(s)}>
                      <td className="ref">{s.reference || "—"}</td>
                      <td className="cell-title">{s.title}</td>
                      <td><Badge tone="info">{cap(s.basel_event_type)}</Badge></td>
                      <td className="muted">{s.business_line || "—"}</td>
                      <td className="muted">{num(s.frequency_per_year)}</td>
                      <td className="muted">{num(s.expected_annual_loss)} {s.currency}</td>
                      <td className="muted">{num(s.worst_case_loss)}</td>
                      <td><Badge tone={SCENARIO_STATUS_TONE[s.status] || "neutral"}>{cap(s.status)}</Badge></td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleScenario(s)}>
                            {openScenario?.id === s.id ? "Hide" : "Open"}
                          </button>
                          <button className="btn secondary sm" onClick={() => openEditScenario(s)}>Edit</button>
                          <button className="btn secondary sm" onClick={() => removeScenario(s)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {scenarios.length === 0 && (
                    <tr>
                      <td colSpan={9}>
                        <div className="empty">
                          <span className="ico"><IconGauge width={24} height={24} /></span>
                          <h3>No scenarios</h3>
                          <p>Workshop forward-looking operational-risk scenarios against Basel event types.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openScenario && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openScenario.reference} — {openScenario.title}</h3>
                    <span className="sub">
                      {cap(openScenario.status)} · {cap(openScenario.basel_event_type)}
                      {openScenario.business_line ? " · " + openScenario.business_line : ""}
                      {openScenario.owner ? " · owner " + openScenario.owner : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                    <div style={{ textAlign: "right" }}>
                      <div className="muted" style={{ fontSize: 12 }}>Expected annual loss</div>
                      <strong style={{ fontSize: 18 }}>{num(openScenario.expected_annual_loss)} {openScenario.currency}</strong>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn secondary sm" onClick={() => openEditScenario(openScenario)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => removeScenario(openScenario)}>Delete</button>
                    </div>
                  </div>
                </div>
                <div className="card-pad">
                  <div className="field-row" style={{ gap: 24 }}>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Frequency / year</div>
                      <strong>{num(openScenario.frequency_per_year)}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Typical loss</div>
                      <strong>{num(openScenario.typical_loss)} {openScenario.currency}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Worst case</div>
                      <strong>{num(openScenario.worst_case_loss)} {openScenario.currency}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Confidence</div>
                      <strong>{openScenario.confidence_level || "—"}</strong>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12 }}>Review date</div>
                      <strong>{openScenario.review_date || "—"}</strong>
                    </div>
                  </div>
                  {openScenario.description && (
                    <p style={{ marginTop: 12 }}>{openScenario.description}</p>
                  )}
                  {openScenario.participants && (
                    <p className="muted" style={{ marginTop: 8, fontSize: 13 }}>
                      <strong>Participants:</strong> {openScenario.participants}
                    </p>
                  )}
                  {openScenario.assumptions && (
                    <p className="muted" style={{ marginTop: 4, fontSize: 13 }}>
                      <strong>Assumptions:</strong> {openScenario.assumptions}
                    </p>
                  )}
                </div>
              </div>

              <RecordPanels model="scenario_analysis" entityId={openScenario.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= CAPITAL (SMA) */}
      {section === "capital" && (
        <div className="card">
          <div className="card-head">
            <h3>Capital — Standardised Approach (SMA)</h3>
            <span className="sub">{capitals.length} total · click a row to edit</span>
          </div>
          <p className="muted" style={{ padding: "0 16px 12px", fontSize: 13 }}>
            ORC = BIC × ILM, where BIC uses the 12% / 15% / 18% marginal buckets and the ILM scales it by internal
            loss experience (Loss Component = 15 × average annual loss).
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Period</th>
                  <th>Business Indicator</th>
                  <th>Avg annual loss</th>
                  <th>BIC</th>
                  <th>Loss Component</th>
                  <th>ILM</th>
                  <th>ORC</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {capitals.map((c) => (
                  <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => openEditCapital(c)}>
                    <td className="ref">{c.reference || "—"}</td>
                    <td className="cell-title">{c.period || "—"}</td>
                    <td className="muted">{num(c.business_indicator)} {c.currency}</td>
                    <td className="muted">{num(c.avg_annual_loss)}</td>
                    <td className="muted">{num(c.bic)}</td>
                    <td className="muted">{num(c.loss_component)}</td>
                    <td className="muted">{num(c.ilm)}</td>
                    <td>
                      <Badge tone="critical">{num(c.orc)} {c.currency}</Badge>
                    </td>
                    <td><Badge tone={CAPITAL_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge></td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeCapital(c)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {capitals.length === 0 && (
                  <tr>
                    <td colSpan={10}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No capital calculations</h3>
                        <p>Enter the Business Indicator and average annual losses to compute SMA operational-risk capital.</p>
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
      {showScenarioForm && (
        <FormModal
          title={editingScenario ? `Edit scenario — ${editingScenario.reference || editingScenario.title}` : "New scenario"}
          wide
          tabs={[
            { id: "scenario", label: "Scenario", content: scenarioTab, required: true },
            { id: "estimates", label: "Estimates", content: estimatesTab },
            { id: "workshop", label: "Workshop", content: workshopTab },
          ]}
          onClose={() => setShowScenarioForm(false)}
          onSave={saveScenario}
          saving={savingScenario}
          error={error}
          saveLabel={editingScenario ? "Save changes" : "Create scenario"}
          footerLeft={
            editingScenario ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeScenario(editingScenario)}
                disabled={savingScenario}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showCapitalForm && (
        <FormModal
          title={editingCapital ? `Edit calculation — ${editingCapital.reference || editingCapital.period}` : "New capital calculation"}
          wide
          tabs={[{ id: "inputs", label: "Inputs", content: capitalTab, required: true }]}
          onClose={() => setShowCapitalForm(false)}
          onSave={saveCapital}
          saving={savingCapital}
          error={error}
          saveLabel={editingCapital ? "Save changes" : "Create calculation"}
          footerLeft={
            editingCapital ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeCapital(editingCapital)}
                disabled={savingCapital}
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
