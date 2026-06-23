"use client";

import { useEffect, useState } from "react";
import { api, type CatalogItem, type Risk, type RiskSetting, type StatusLabel } from "@/lib/api";
import { Badge, Severity, StatusBadge } from "@/components/badges";
import { IconGauge, IconPlus, IconRisk } from "@/components/icons";

function ChipPicker({
  label,
  items,
  selected,
  toggle,
}: {
  label: string;
  items: CatalogItem[];
  selected: Set<string>;
  toggle: (id: string) => void;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((i) => {
          const on = selected.has(i.id);
          return (
            <button
              type="button"
              key={i.id}
              onClick={() => toggle(i.id)}
              className={`badge ${on ? "info" : "neutral"}`}
              style={{ cursor: "pointer", border: on ? "1px solid var(--primary)" : "1px solid var(--border)" }}
            >
              {i.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function money(n: number | null) {
  if (!n) return "—";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

function appetite(risk: Risk, s: RiskSetting | null) {
  if (!s) return null;
  const score = risk.residual_score ?? risk.inherent_score;
  if (score == null) return null;
  if (score <= s.appetite_score) return { label: "within appetite", tone: "low" as const };
  if (score <= s.tolerance_score) return { label: "elevated", tone: "medium" as const };
  return { label: "breach", tone: "critical" as const };
}

export default function RisksPage() {
  const [risks, setRisks] = useState<Risk[]>([]);
  const [labels, setLabels] = useState<Record<string, StatusLabel[]>>({});
  const [settings, setSettings] = useState<RiskSetting | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("Information Security");
  const [likelihood, setLikelihood] = useState(3);
  const [impact, setImpact] = useState(3);
  const [alf, setAlf] = useState("");
  const [sle, setSle] = useState("");
  const [saving, setSaving] = useState(false);

  const [threats, setThreats] = useState<CatalogItem[]>([]);
  const [vulns, setVulns] = useState<CatalogItem[]>([]);
  const [selThreats, setSelThreats] = useState<Set<string>>(new Set());
  const [selVulns, setSelVulns] = useState<Set<string>>(new Set());

  const [appetiteScore, setAppetiteScore] = useState(6);
  const [toleranceScore, setToleranceScore] = useState(12);

  function toggle(set: Set<string>, setter: (s: Set<string>) => void, id: string) {
    const next = new Set(set);
    next.has(id) ? next.delete(id) : next.add(id);
    setter(next);
  }

  async function load() {
    try {
      const [r, s, t, v] = await Promise.all([
        api.risks(),
        api.riskSettings(),
        api.threatCatalog(),
        api.vulnerabilityCatalog(),
      ]);
      setThreats(t.items);
      setVulns(v.items);
      setRisks(r.items);
      setSettings(s);
      setAppetiteScore(s.appetite_score);
      setToleranceScore(s.tolerance_score);
      if (r.items.length) {
        api.evaluateStatus("risk", r.items.map((x) => x.id)).then(setLabels).catch(() => {});
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createRisk(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createRisk({
        title,
        category,
        inherent_likelihood: likelihood,
        inherent_impact: impact,
        annual_loss_frequency: alf ? Number(alf) : null,
        single_loss_expectancy: sle ? Number(sle) : null,
        threat_ids: [...selThreats],
        vulnerability_ids: [...selVulns],
      });
      setShowForm(false);
      setTitle("");
      setAlf("");
      setSle("");
      setSelThreats(new Set());
      setSelVulns(new Set());
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create risk");
    } finally {
      setSaving(false);
    }
  }

  async function saveSettings(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const s = await api.updateRiskSettings({
        appetite_score: appetiteScore,
        tolerance_score: toleranceScore,
      });
      setSettings(s);
      setShowSettings(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Risk Register</h1>
          <p>Identify, score and treat risks — qualitative and quantitative (FAIR).</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={() => setShowSettings((v) => !v)}>
            <IconGauge width={16} height={16} />
            Appetite
          </button>
          <button className="btn" onClick={() => setShowForm((v) => !v)}>
            <IconPlus width={16} height={16} />
            {showForm ? "Close" : "New risk"}
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {settings && (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <div className="row-between">
            <span className="muted">
              Risk appetite ≤ <b style={{ color: "var(--green)" }}>{settings.appetite_score}</b>{" "}
              · Tolerance ≤ <b style={{ color: "var(--amber)" }}>{settings.tolerance_score}</b>{" "}
              <span style={{ color: "var(--faint)" }}>(score above tolerance = breach)</span>
            </span>
          </div>
          {showSettings && (
            <form onSubmit={saveSettings} style={{ display: "flex", gap: 14, alignItems: "flex-end", marginTop: 14 }}>
              <div style={{ width: 160 }}>
                <label className="label">Appetite (1–25)</label>
                <input className="input" type="number" min={1} max={25} value={appetiteScore} onChange={(e) => setAppetiteScore(Number(e.target.value))} />
              </div>
              <div style={{ width: 160 }}>
                <label className="label">Tolerance (1–25)</label>
                <input className="input" type="number" min={1} max={25} value={toleranceScore} onChange={(e) => setToleranceScore(Number(e.target.value))} />
              </div>
              <button className="btn">Save thresholds</button>
            </form>
          )}
        </div>
      )}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={createRisk}>
          <label className="label">Title</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Phishing leads to credential theft" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Category</label>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} />
            </div>
            <div style={{ width: 130 }}>
              <label className="label">Likelihood</label>
              <input className="input" type="number" min={1} max={5} value={likelihood} onChange={(e) => setLikelihood(Number(e.target.value))} />
            </div>
            <div style={{ width: 130 }}>
              <label className="label">Impact</label>
              <input className="input" type="number" min={1} max={5} value={impact} onChange={(e) => setImpact(Number(e.target.value))} />
            </div>
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Loss events / year (FAIR, optional)</label>
              <input className="input" type="number" step="0.1" min={0} value={alf} onChange={(e) => setAlf(e.target.value)} placeholder="0.5" />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">$ per event (SLE, optional)</label>
              <input className="input" type="number" step="1000" min={0} value={sle} onChange={(e) => setSle(e.target.value)} placeholder="200000" />
            </div>
          </div>
          {threats.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <ChipPicker label="Threats" items={threats} selected={selThreats} toggle={(id) => toggle(selThreats, setSelThreats, id)} />
            </div>
          )}
          {vulns.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <ChipPicker label="Vulnerabilities" items={vulns} selected={selVulns} toggle={(id) => toggle(selVulns, setSelVulns, id)} />
            </div>
          )}
          <button className="btn" style={{ marginTop: 16 }} disabled={saving}>
            {saving ? "Saving…" : "Create risk"}
          </button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>All risks</h3>
          <span className="sub">{risks.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Status</th>
                <th>Inherent</th>
                <th>Residual</th>
                <th>Appetite</th>
                <th>Exposure (ALE)</th>
                <th>Controls</th>
                <th>Status Rules</th>
              </tr>
            </thead>
            <tbody>
              {risks.map((r) => {
                const a = appetite(r, settings);
                return (
                  <tr key={r.id}>
                    <td className="ref">{r.reference}</td>
                    <td className="cell-title">{r.title}</td>
                    <td><StatusBadge value={r.status} /></td>
                    <td>
                      <Severity value={r.inherent_severity} />{" "}
                      <span className="muted">({r.inherent_score ?? "—"})</span>
                    </td>
                    <td>
                      <Severity value={r.residual_severity} />{" "}
                      <span className="muted">({r.residual_score ?? "—"})</span>
                    </td>
                    <td>{a ? <Badge tone={a.tone}>{a.label}</Badge> : <span className="muted">—</span>}</td>
                    <td className="muted">{money(r.annual_loss_expectancy)}</td>
                    <td className="muted">{r.controls.length}</td>
                    <td>
                      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                        {(labels[r.id] || []).map((l) => (
                          <span key={l.label} style={{ background: `${l.color}1a`, color: l.color, border: `1px solid ${l.color}55`, borderRadius: 99, padding: "1px 8px", fontSize: 11, fontWeight: 600 }}>{l.label}</span>
                        ))}
                        {(!labels[r.id] || labels[r.id].length === 0) && <span className="muted">—</span>}
                      </div>
                    </td>
                  </tr>
                );
              })}
              {risks.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconRisk width={24} height={24} /></span>
                      <h3>No risks yet</h3>
                      <p>Create your first risk to start building the register.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
