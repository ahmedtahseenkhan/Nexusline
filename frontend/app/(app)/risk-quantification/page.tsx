"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconGauge } from "@/components/icons";

// ------------------------------------------------------------------ types
type RiskQuant = {
  id: string;
  reference: string;
  title: string;
  scenario: string;
  risk_id: string | null;
  asset_at_risk: string;
  tef_min: number;
  tef_likely: number;
  tef_max: number;
  lm_min: number;
  lm_likely: number;
  lm_max: number;
  currency: string;
  iterations: number;
  owner: string;
  notes: string;
  status: string;
  workflow_status: string;
  ale_point: number;
  last_mean_ale: number;
  last_p90: number;
  last_simulated: string | null;
  created_at: string;
};

type SimResult = {
  p10: number;
  p50: number;
  p90: number;
  mean: number;
  max: number;
  iterations: number;
};

type QuantSummary = {
  total_mean_ale: number;
  count_quantified: number;
  count_simulated: number;
  highest_p90: number;
  top: { id: string; title: string; last_mean_ale: number; last_p90: number }[];
};

type Paged<T> = { items: T[]; total: number; limit: number; offset: number };
type RiskRef = { id: string; reference: string; title: string };

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());
const pkr = (n: number | null | undefined, ccy = "PKR") =>
  n == null ? "—" : `${ccy} ${Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

const QUANT_STATUS = opts(["draft", "simulated", "approved"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  simulated: "info",
  approved: "low",
};

// ------------------------------------------------------------------ form state
type QuantForm = {
  title: string;
  scenario: string;
  risk_id: string;
  asset_at_risk: string;
  tef_min: string;
  tef_likely: string;
  tef_max: string;
  lm_min: string;
  lm_likely: string;
  lm_max: string;
  currency: string;
  iterations: string;
  owner: string;
  notes: string;
  status: string;
  workflow_status: string;
};
const BLANK: QuantForm = {
  title: "",
  scenario: "",
  risk_id: "",
  asset_at_risk: "",
  tef_min: "0.1",
  tef_likely: "1",
  tef_max: "4",
  lm_min: "0",
  lm_likely: "0",
  lm_max: "0",
  currency: "PKR",
  iterations: "10000",
  owner: "",
  notes: "",
  status: "draft",
  workflow_status: "draft",
};
function fromQuant(q: RiskQuant): QuantForm {
  return {
    title: q.title,
    scenario: q.scenario || "",
    risk_id: q.risk_id || "",
    asset_at_risk: q.asset_at_risk || "",
    tef_min: String(q.tef_min ?? 0),
    tef_likely: String(q.tef_likely ?? 0),
    tef_max: String(q.tef_max ?? 0),
    lm_min: String(q.lm_min ?? 0),
    lm_likely: String(q.lm_likely ?? 0),
    lm_max: String(q.lm_max ?? 0),
    currency: q.currency || "PKR",
    iterations: String(q.iterations ?? 10000),
    owner: q.owner || "",
    notes: q.notes || "",
    status: q.status || "draft",
    workflow_status: q.workflow_status || "draft",
  };
}
function payload(f: QuantForm): Record<string, unknown> {
  const n = (v: string, d = 0) => (v === "" ? d : Number(v));
  return {
    title: f.title,
    scenario: f.scenario,
    risk_id: f.risk_id || null,
    asset_at_risk: f.asset_at_risk,
    tef_min: n(f.tef_min),
    tef_likely: n(f.tef_likely),
    tef_max: n(f.tef_max),
    lm_min: n(f.lm_min),
    lm_likely: n(f.lm_likely),
    lm_max: n(f.lm_max),
    currency: f.currency || "PKR",
    iterations: n(f.iterations, 10000),
    owner: f.owner,
    notes: f.notes,
    status: f.status,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ loss-curve bars
function SimBars({ p50, p90, max, currency }: { p50: number; p90: number; max: number; currency: string }) {
  const scale = max > 0 ? max : 1;
  const rows: { label: string; value: number; color: string }[] = [
    { label: "P50 (median)", value: p50, color: "#2f855a" },
    { label: "P90", value: p90, color: "#b7791f" },
    { label: "Max", value: max, color: "#c0392b" },
  ];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
      {rows.map((r) => (
        <div key={r.label} style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span className="muted" style={{ width: 110, fontSize: 12, flex: "0 0 auto" }}>{r.label}</span>
          <div style={{ flex: 1, background: "var(--surface-2, #f1f3f5)", borderRadius: 4, height: 16, overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.max(2, (r.value / scale) * 100)}%`,
                background: r.color,
                height: "100%",
                borderRadius: 4,
                transition: "width .3s ease",
              }}
            />
          </div>
          <span className="ref" style={{ width: 150, textAlign: "right", flex: "0 0 auto" }}>
            {pkr(r.value, currency)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ page
export default function RiskQuantificationPage() {
  const [error, setError] = useState<string | null>(null);
  const [rows, setRows] = useState<RiskQuant[]>([]);
  const [summary, setSummary] = useState<QuantSummary | null>(null);
  const [risks, setRisks] = useState<RiskRef[]>([]);

  const [openId, setOpenId] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, SimResult>>({});
  const [simulating, setSimulating] = useState<string | null>(null);

  const [editing, setEditing] = useState<RiskQuant | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<QuantForm>(BLANK);
  const set = <K extends keyof QuantForm>(k: K, v: QuantForm[K]) => setF((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadRows() {
    try {
      const res = await apiCall<Paged<RiskQuant>>("GET", "/risk-quantification");
      setRows(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load quantifications");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<QuantSummary>("GET", "/risk-quantification-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }
  async function loadRisks() {
    // Best-effort: populate the optional risk-register link. Silently ignore if the
    // user lacks risk:read — the record simply stays unlinked.
    try {
      const res = await apiCall<Paged<RiskRef>>("GET", "/risks?limit=200");
      setRisks(res.items);
    } catch {
      /* no risk-register access — leave the link picker empty */
    }
  }

  useEffect(() => {
    loadRows();
    loadSummary();
    loadRisks();
  }, []);

  const riskOptions: Option[] = risks.map((r) => ({
    value: r.id,
    label: `${r.reference || "—"} — ${r.title}`,
  }));

  // ------------------------------------------------------------- CRUD
  function openNew() {
    setEditing(null);
    setF(BLANK);
    setShowForm(true);
  }
  function openEdit(q: RiskQuant) {
    setEditing(q);
    setF(fromQuant(q));
    setShowForm(true);
  }
  async function save() {
    setError(null);
    setSaving(true);
    try {
      const body = payload(f);
      if (editing) await apiCall("PATCH", `/risk-quantification/${editing.id}`, body);
      else await apiCall("POST", "/risk-quantification", body);
      setShowForm(false);
      await loadRows();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save quantification");
    } finally {
      setSaving(false);
    }
  }
  async function remove(q: RiskQuant) {
    if (!window.confirm(`Delete quantification ${q.reference || q.title}?`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/risk-quantification/${q.id}`);
      setShowForm(false);
      if (openId === q.id) setOpenId(null);
      await loadRows();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggle(id: string) {
    setOpenId(openId === id ? null : id);
  }
  async function runSimulate(id: string) {
    setError(null);
    setSimulating(id);
    try {
      const res = await apiCall<SimResult>("POST", `/risk-quantification/${id}/simulate`);
      setResults((prev) => ({ ...prev, [id]: res }));
      setOpenId(id);
      await loadRows();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run simulation");
    } finally {
      setSimulating(null);
    }
  }

  // ------------------------------------------------------------- form tabs
  const scenarioTab = (
    <>
      <Field label="Title" required help="For example: Ransomware halts core banking for 3 days.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Loss scenario title" required />
      </Field>
      <Field label="Scenario" help="Narrative of the threat, asset, and how the loss materialises.">
        <TextArea value={f.scenario} onChange={(v) => set("scenario", v)} rows={4} placeholder="Describe the loss scenario." />
      </Field>
      <div className="field-row">
        <Field label="Asset at risk" help="The system, process, or portfolio exposed.">
          <TextInput value={f.asset_at_risk} onChange={(v) => set("asset_at_risk", v)} placeholder="Core banking system" />
        </Field>
        <Field label="Owner">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="Risk owner" />
        </Field>
      </div>
      <Field label="Notes">
        <TextArea value={f.notes} onChange={(v) => set("notes", v)} rows={3} placeholder="Assumptions and data sources." />
      </Field>
    </>
  );

  const frequencyTab = (
    <>
      <p className="muted" style={{ fontSize: 13, margin: "0 0 12px" }}>
        Threat Event Frequency — how many loss events per year, as a triangular estimate
        (minimum, most-likely, maximum).
      </p>
      <div className="field-row">
        <Field label="TEF minimum" help="Fewest events per year.">
          <TextInput type="number" value={f.tef_min} onChange={(v) => set("tef_min", v)} placeholder="0" />
        </Field>
        <Field label="TEF most-likely" help="Central estimate, events/year.">
          <TextInput type="number" value={f.tef_likely} onChange={(v) => set("tef_likely", v)} placeholder="1" />
        </Field>
        <Field label="TEF maximum" help="Most events per year.">
          <TextInput type="number" value={f.tef_max} onChange={(v) => set("tef_max", v)} placeholder="4" />
        </Field>
      </div>
    </>
  );

  const magnitudeTab = (
    <>
      <p className="muted" style={{ fontSize: 13, margin: "0 0 12px" }}>
        Loss Magnitude per event in {f.currency || "PKR"}, as a triangular estimate
        (minimum, most-likely, maximum).
      </p>
      <div className="field-row">
        <Field label="LM minimum" help="Smallest single-event loss.">
          <TextInput type="number" value={f.lm_min} onChange={(v) => set("lm_min", v)} placeholder="0" />
        </Field>
        <Field label="LM most-likely" help="Central single-event loss.">
          <TextInput type="number" value={f.lm_likely} onChange={(v) => set("lm_likely", v)} placeholder="0" />
        </Field>
        <Field label="LM maximum" help="Worst-case single-event loss.">
          <TextInput type="number" value={f.lm_max} onChange={(v) => set("lm_max", v)} placeholder="0" />
        </Field>
      </div>
      <Field label="Currency">
        <TextInput value={f.currency} onChange={(v) => set("currency", v)} placeholder="PKR" />
      </Field>
    </>
  );

  const settingsTab = (
    <>
      <div className="field-row">
        <Field label="Iterations" help="Monte Carlo sample count (100 – 1,000,000).">
          <TextInput type="number" value={f.iterations} onChange={(v) => set("iterations", v)} placeholder="10000" />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={QUANT_STATUS} />
        </Field>
      </div>
      <Field label="Linked risk (optional)" help="Attach this quantification to a risk-register entry.">
        <Select
          value={f.risk_id}
          onChange={(v) => set("risk_id", v)}
          options={riskOptions}
          placeholder={risks.length ? "No linked risk" : "No risk register access"}
        />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this quantification record.">
        <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Risk Quantification</h1>
          <p>FAIR-style loss exposure — Monte Carlo simulation of annualised loss (ALE) in PKR on top of the qualitative risk register.</p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} /> New quantification
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.count_quantified.toLocaleString() : "—"}</span></div>
          <span className="l">Quantified risks</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? pkr(summary.total_mean_ale) : "—"}</span></div>
          <span className="l">Total mean ALE</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? pkr(summary.highest_p90) : "—"}</span></div>
          <span className="l">Highest single P90</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.count_simulated.toLocaleString() : "—"}</span></div>
          <span className="l">Simulated</span>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Quantified loss scenarios</h3>
          <span className="sub">{rows.length} total · click a row to view the loss curve · Simulate runs a fresh Monte Carlo</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Asset at risk</th>
                <th>ALE point</th>
                <th>Mean ALE</th>
                <th>P90</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((q) => (
                <tr key={q.id} style={{ cursor: "pointer" }} onClick={() => toggle(q.id)}>
                  <td className="ref">{q.reference || "—"}</td>
                  <td className="cell-title">{q.title}</td>
                  <td className="muted">{q.asset_at_risk || "—"}</td>
                  <td className="muted">{pkr(q.ale_point, q.currency)}</td>
                  <td className="muted">{q.last_simulated ? pkr(q.last_mean_ale, q.currency) : "—"}</td>
                  <td className="muted">{q.last_simulated ? pkr(q.last_p90, q.currency) : "—"}</td>
                  <td><Badge tone={STATUS_TONE[q.status] || "neutral"}>{cap(q.status)}</Badge></td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => runSimulate(q.id)} disabled={simulating === q.id}>
                        {simulating === q.id ? "Simulating…" : "Simulate"}
                      </button>
                      <button className="btn secondary sm" onClick={() => toggle(q.id)}>
                        {openId === q.id ? "Hide" : "View"}
                      </button>
                      <button className="btn secondary sm" onClick={() => openEdit(q)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => remove(q)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="empty">
                      <span className="ico"><IconGauge width={24} height={24} /></span>
                      <h3>No quantified risks</h3>
                      <p>Frame a loss scenario with frequency and magnitude estimates, then run a Monte Carlo to size the exposure in PKR.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {openId && (() => {
        const q = rows.find((x) => x.id === openId);
        if (!q) return null;
        const fresh = results[q.id];
        const hasCurve = fresh || q.last_simulated;
        return (
          <>
            <div className="card" style={{ margin: "16px 0" }}>
              <div className="card-head row-between">
                <div>
                  <h3>{q.reference} — {q.title}</h3>
                  <span className="sub">
                    {cap(q.status)} · {q.asset_at_risk || "no asset"}
                    {q.last_simulated ? " · last simulated " + q.last_simulated : " · not yet simulated"}
                  </span>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button className="btn" onClick={() => runSimulate(q.id)} disabled={simulating === q.id}>
                    {simulating === q.id ? "Simulating…" : "Run simulation"}
                  </button>
                  <button className="btn secondary sm" onClick={() => openEdit(q)}>Edit</button>
                  <button className="btn secondary sm" onClick={() => remove(q)}>Delete</button>
                </div>
              </div>

              <div className="card-pad">
                <div className="field-row" style={{ marginBottom: 12 }}>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Threat Event Frequency (events/yr)</div>
                    <strong>{num(q.tef_min)} · {num(q.tef_likely)} · {num(q.tef_max)}</strong>
                  </div>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Loss Magnitude / event</div>
                    <strong>{pkr(q.lm_min, q.currency)} · {pkr(q.lm_likely, q.currency)} · {pkr(q.lm_max, q.currency)}</strong>
                  </div>
                  <div>
                    <div className="muted" style={{ fontSize: 12 }}>Point ALE · iterations</div>
                    <strong>{pkr(q.ale_point, q.currency)} · {num(q.iterations)}</strong>
                  </div>
                </div>

                <strong>Monte Carlo loss curve</strong>
                {!hasCurve && (
                  <p className="muted" style={{ margin: "6px 0 0", fontSize: 13 }}>
                    No simulation yet. Run a simulation to estimate the annualised loss distribution.
                  </p>
                )}

                {fresh && (
                  <>
                    <div className="grid stat-grid" style={{ marginTop: 12 }}>
                      <div className="card stat"><div className="stat-top"><span className="n">{pkr(fresh.p10, q.currency)}</span></div><span className="l">P10</span></div>
                      <div className="card stat"><div className="stat-top"><span className="n">{pkr(fresh.p50, q.currency)}</span></div><span className="l">P50 (median)</span></div>
                      <div className="card stat"><div className="stat-top"><span className="n">{pkr(fresh.p90, q.currency)}</span></div><span className="l">P90</span></div>
                      <div className="card stat"><div className="stat-top"><span className="n">{pkr(fresh.mean, q.currency)}</span></div><span className="l">Mean ALE</span></div>
                      <div className="card stat"><div className="stat-top"><span className="n">{pkr(fresh.max, q.currency)}</span></div><span className="l">Max</span></div>
                    </div>
                    <SimBars p50={fresh.p50} p90={fresh.p90} max={fresh.max} currency={q.currency} />
                    <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                      Based on {num(fresh.iterations)} Monte Carlo iterations.
                    </p>
                  </>
                )}

                {!fresh && q.last_simulated && (
                  <>
                    <div className="grid stat-grid" style={{ marginTop: 12 }}>
                      <div className="card stat"><div className="stat-top"><span className="n">{pkr(q.last_mean_ale, q.currency)}</span></div><span className="l">Mean ALE (cached)</span></div>
                      <div className="card stat"><div className="stat-top"><span className="n">{pkr(q.last_p90, q.currency)}</span></div><span className="l">P90 (cached)</span></div>
                    </div>
                    <SimBars p50={q.last_mean_ale} p90={q.last_p90} max={q.last_p90} currency={q.currency} />
                    <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                      Cached from the run on {q.last_simulated}. Run again for the full P10 / P50 / max breakdown.
                    </p>
                  </>
                )}
              </div>
            </div>

            <RecordPanels model="risk_quantification" entityId={q.id} />
          </>
        );
      })()}

      {showForm && (
        <FormModal
          title={editing ? `Edit quantification — ${editing.reference || editing.title}` : "New quantification"}
          wide
          tabs={[
            { id: "scenario", label: "Scenario", content: scenarioTab, required: true },
            { id: "frequency", label: "Frequency", content: frequencyTab },
            { id: "magnitude", label: "Magnitude", content: magnitudeTab },
            { id: "settings", label: "Settings", content: settingsTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create quantification"}
          footerLeft={
            editing ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => remove(editing)}
                disabled={saving}
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
