"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type MetricInfo, type WidgetData } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { IconPlus } from "@/components/icons";

const PALETTE = ["#2563eb", "#0891b2", "#7c3aed", "#db2777", "#ea580c", "#16a34a", "#ca8a04", "#64748b"];

function BarChart({ series }: { series: { label: string; value: number }[] }) {
  const max = Math.max(1, ...series.map((s) => s.value));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 6 }}>
      {series.map((s, i) => (
        <div key={s.label}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 3 }}>
            <span style={{ textTransform: "capitalize" }}>{s.label}</span>
            <b>{s.value}</b>
          </div>
          <div style={{ height: 8, background: "var(--surface-2, #eef2f7)", borderRadius: 99 }}>
            <div style={{ width: `${(s.value / max) * 100}%`, height: "100%", background: PALETTE[i % PALETTE.length], borderRadius: 99 }} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Donut({ series }: { series: { label: string; value: number }[] }) {
  const total = series.reduce((a, s) => a + s.value, 0) || 1;
  let acc = 0;
  const stops = series.map((s, i) => {
    const start = (acc / total) * 360;
    acc += s.value;
    const end = (acc / total) * 360;
    return `${PALETTE[i % PALETTE.length]} ${start}deg ${end}deg`;
  });
  return (
    <div style={{ display: "flex", gap: 18, alignItems: "center", marginTop: 6 }}>
      <div style={{ width: 110, height: 110, borderRadius: "50%", background: `conic-gradient(${stops.join(",")})`, position: "relative", flexShrink: 0 }}>
        <div style={{ position: "absolute", inset: 18, background: "var(--card, #fff)", borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 700 }}>{total}</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        {series.map((s, i) => (
          <div key={s.label} style={{ display: "flex", gap: 7, alignItems: "center", fontSize: 12 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: PALETTE[i % PALETTE.length] }} />
            <span style={{ textTransform: "capitalize" }}>{s.label}</span>
            <b style={{ marginLeft: "auto" }}>{s.value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ReportsPage() {
  const [data, setData] = useState<WidgetData[]>([]);
  const [metrics, setMetrics] = useState<MetricInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [metricKey, setMetricKey] = useState("");
  const [viz, setViz] = useState("number");

  async function load() {
    try {
      const [d, m] = await Promise.all([api.reportDashboard(), api.reportMetrics()]);
      setData(d);
      setMetrics(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  const selected = metrics.find((m) => m.key === metricKey);
  useEffect(() => {
    if (selected) setViz(selected.kind === "scalar" ? "number" : "bar");
  }, [metricKey]); // eslint-disable-line

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    setError(null);
    try {
      await api.createWidget({ title: selected.label, metric_key: selected.key, viz, order_index: data.length + 1 });
      setShowForm(false);
      setMetricKey("");
      await load();
      toast("Widget added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Add failed");
    }
  }

  async function remove(id: string) {
    if (!(await confirmDialog({ title: "Remove this widget?", danger: true, confirmLabel: "Remove" }))) return;
    try {
      await api.deleteWidget(id);
      await load();
      toast("Widget removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove widget");
    }
  }

  const scalars = data.filter((d) => d.kind === "scalar");
  const charts = data.filter((d) => d.kind === "breakdown");
  const grouped = useMemo(() => {
    const g: Record<string, MetricInfo[]> = {};
    metrics.forEach((m) => (g[m.category] ||= []).push(m));
    return g;
  }, [metrics]);

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Reports &amp; KPIs</h1>
          <p>Build a live dashboard from metrics across every module.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} /> {showForm ? "Close" : "Add widget"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={add}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: "1 1 280px" }}>
              <label className="label">Metric</label>
              <select className="input" value={metricKey} required onChange={(e) => setMetricKey(e.target.value)}>
                <option value="">Choose a metric…</option>
                {Object.entries(grouped).map(([cat, list]) => (
                  <optgroup key={cat} label={cat}>
                    {list.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
                  </optgroup>
                ))}
              </select>
            </div>
            <div style={{ flex: "0 0 160px" }}>
              <label className="label">Visualization</label>
              <select className="input" value={viz} onChange={(e) => setViz(e.target.value)}>
                {selected?.kind === "scalar"
                  ? <option value="number">Number</option>
                  : <><option value="bar">Bar</option><option value="donut">Donut</option></>}
              </select>
            </div>
            <button className="btn" disabled={!selected}>Add to dashboard</button>
          </div>
          {selected && <p className="muted" style={{ marginTop: 10, fontSize: 12 }}>{selected.description}</p>}
        </form>
      )}

      {scalars.length > 0 && (
        <div className="grid stat-grid" style={{ marginBottom: 16 }}>
          {scalars.map((d) => (
            <div className="card stat" key={d.widget.id} style={{ position: "relative" }}>
              <button className="widget-x" onClick={() => remove(d.widget.id)} title="Remove" style={{ position: "absolute", top: 8, right: 10, border: "none", background: "none", cursor: "pointer", color: "var(--muted)", fontSize: 15 }}>×</button>
              <div className="stat-top"><span className="n">{d.error ? "—" : d.value}</span></div>
              <span className="l">{d.widget.title}</span>
            </div>
          ))}
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 16 }}>
        {charts.map((d) => (
          <div className="card" key={d.widget.id}>
            <div className="card-head">
              <h3>{d.widget.title}</h3>
              <button className="widget-x" onClick={() => remove(d.widget.id)} title="Remove" style={{ border: "none", background: "none", cursor: "pointer", color: "var(--muted)", fontSize: 16 }}>×</button>
            </div>
            <div className="card-pad">
              {d.error ? <p className="muted">{d.error}</p>
                : !d.series || d.series.length === 0 ? <p className="muted">No data</p>
                : d.widget.viz === "donut" ? <Donut series={d.series} />
                : <BarChart series={d.series} />}
            </div>
          </div>
        ))}
      </div>

      {data.length === 0 && (
        <div className="card card-pad"><div className="empty"><h3>Empty dashboard</h3><p>Add a widget to start building your KPI dashboard.</p></div></div>
      )}
    </>
  );
}
