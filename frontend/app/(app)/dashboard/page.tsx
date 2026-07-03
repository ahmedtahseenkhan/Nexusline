"use client";

import { useEffect, useState } from "react";
import {
  api,
  type AuditEntry,
  type ComplianceSummary,
  type Dashboard,
  type RiskAggregate,
} from "@/lib/api";
import {
  IconAlert,
  IconCheck,
  IconCompliance,
  IconControl,
  IconGauge,
  IconLayers,
  IconRisk,
} from "@/components/icons";
import RiskHeatmap from "@/components/RiskHeatmap";

function money(n: number) {
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

const SEV_COLORS: Record<string, string> = {
  low: "var(--green)",
  medium: "var(--amber)",
  high: "var(--orange)",
  critical: "var(--red)",
};
const SEV_ORDER = ["critical", "high", "medium", "low"];

function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function SegBar({ data }: { data: Record<string, number> }) {
  const total = Object.values(data).reduce((a, b) => a + b, 0) || 1;
  return (
    <>
      <div className="segbar">
        {SEV_ORDER.map((k) =>
          data[k] ? (
            <span
              key={k}
              style={{ width: `${(data[k] / total) * 100}%`, background: SEV_COLORS[k] }}
              title={`${k}: ${data[k]}`}
            />
          ) : null
        )}
      </div>
      <div className="legend">
        {SEV_ORDER.map((k) => (
          <span className="item" key={k}>
            <span className="dot" style={{ background: SEV_COLORS[k] }} />
            {k} <b style={{ color: "var(--text)" }}>{data[k] || 0}</b>
          </span>
        ))}
      </div>
    </>
  );
}

export default function DashboardPage() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [c, setC] = useState<ComplianceSummary | null>(null);
  const [agg, setAgg] = useState<RiskAggregate | null>(null);
  const [activity, setActivity] = useState<AuditEntry[]>([]);

  useEffect(() => {
    api.dashboard().then(setD).catch(() => {});
    api.complianceSummary().then(setC).catch(() => {});
    api.riskAggregate().then(setAgg).catch(() => {});
    api.audit(8).then((r) => setActivity(r.items)).catch(() => {});
  }, []);

  const critical = d?.risks_by_inherent_severity?.critical || 0;

  return (
    <>
      <div className="page-head row-between">
        <div>
          <div className="eyebrow"><span className="live" /> Live posture</div>
          <h1>Governance &amp; risk overview</h1>
          <p>Where the organization stands across risk, compliance and controls — right now.</p>
        </div>
        <button className="btn secondary sm" onClick={() => api.pdfExecutiveSummary().catch(() => {})}>
          Executive summary PDF
        </button>
      </div>

      <div className="kpis primary">
        <div className="kpi">
          <div className="top"><span className="k">Total risks</span><span className="ic"><IconRisk /></span></div>
          <div className="n">{d?.total_risks ?? "—"}</div>
          <div className="ctx">{d ? <><b>{d.risks_in_breach}</b> above tolerance</> : " "}</div>
        </div>
        <div className="kpi danger">
          <div className="top"><span className="k">Critical inherent</span><span className="ic"><IconAlert /></span></div>
          <div className="n">{critical}</div>
          <div className="ctx">{d ? <>of <b>{d.total_risks}</b> total risks</> : " "}</div>
        </div>
        <div className="kpi ok">
          <div className="top"><span className="k">Overall compliant</span><span className="ic"><IconCompliance /></span></div>
          <div className="n">{c ? <>{c.overall_compliant_pct}<span className="u">%</span></> : "—"}</div>
          <div className="ctx">{c ? <>across <b>{c.total_frameworks}</b> frameworks</> : " "}</div>
        </div>
        <div className="kpi warn">
          <div className="top"><span className="k">Annual exposure</span><span className="ic"><IconLayers /></span></div>
          <div className="n">{d ? money(d.total_exposure) : "—"}</div>
          <div className="ctx">expected annual loss (ALE)</div>
        </div>
      </div>

      <div className="kpis secondary">
        <div className={`kpi ${d && d.overdue_reviews > 0 ? "warn" : "ok"}`}>
          <div className="top"><span className="k">Overdue reviews</span><span className="ic"><IconGauge /></span></div>
          <div className="n">{d?.overdue_reviews ?? "—"}</div>
          <div className="ctx">{d ? (d.overdue_reviews > 0 ? "need attention" : "everything current") : " "}</div>
        </div>
        <div className="kpi">
          <div className="top"><span className="k">Controls</span><span className="ic"><IconControl /></span></div>
          <div className="n">{d?.total_controls ?? "—"}</div>
          <div className="ctx">in the catalog</div>
        </div>
        <div className="kpi danger">
          <div className="top"><span className="k">Tolerance breaches</span><span className="ic"><IconAlert /></span></div>
          <div className="n">{d?.risks_in_breach ?? "—"}</div>
          <div className="ctx">{d ? (d.risks_in_breach > 0 ? "requires escalation" : "within tolerance") : " "}</div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 16 }}>
        <div className="card">
          <div className="card-head">
            <h3>Risk by severity</h3>
            <span className="sub">Inherent</span>
          </div>
          <div className="card-pad">
            {d ? <SegBar data={d.risks_by_inherent_severity} /> : <span className="muted">Loading…</span>}
          </div>
        </div>
        <div className="card">
          <div className="card-head">
            <h3>Risk by status</h3>
            <span className="sub">Lifecycle</span>
          </div>
          <div className="card-pad">
            {d &&
              Object.entries(d.risks_by_status).map(([k, v]) => (
                <div key={k} style={{ marginBottom: 12 }}>
                  <div className="row-between" style={{ marginBottom: 5 }}>
                    <span style={{ textTransform: "capitalize", fontSize: 13 }}>
                      {k.replace(/_/g, " ")}
                    </span>
                    <span className="muted">{v}</span>
                  </div>
                  <div className="progress">
                    <span style={{ width: `${(v / (d.total_risks || 1)) * 100}%` }} />
                  </div>
                </div>
              ))}
            {d && d.total_risks === 0 && <span className="muted">No risks yet.</span>}
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: "1.3fr 1fr" }}>
        <div className="card">
          <div className="card-head">
            <h3>Compliance by framework</h3>
            <span className="sub">{c?.total_frameworks ?? 0} frameworks</span>
          </div>
          <div className="card-pad">
            {c && c.frameworks.length ? (
              c.frameworks.map((f) => (
                <div key={f.framework_id} style={{ marginBottom: 16 }}>
                  <div className="row-between" style={{ marginBottom: 6 }}>
                    <span style={{ fontWeight: 550 }}>{f.name}</span>
                    <span className="muted">
                      {f.compliant}/{f.total_requirements} · <b style={{ color: "var(--green)" }}>{f.compliant_pct}%</b>
                    </span>
                  </div>
                  <div className="progress">
                    <span style={{ width: `${f.compliant_pct}%` }} />
                  </div>
                </div>
              ))
            ) : (
              <span className="muted">No frameworks yet.</span>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h3>Recent activity</h3>
          </div>
          <div className="card-pad" style={{ paddingTop: 6, paddingBottom: 6 }}>
            {activity.length ? (
              activity.map((a) => (
                <div className="activity-item" key={a.id}>
                  <span className="dot" />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{a.summary}</div>
                    <div className="when">
                      {a.actor_email} · {timeAgo(a.created_at)}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <span className="muted">No activity recorded yet.</span>
            )}
          </div>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <RiskHeatmap />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head">
          <h3>Enterprise risk roll-up</h3>
          <span className="sub">
            {d ? `Appetite ≤ ${d.appetite_score} · Tolerance ≤ ${d.tolerance_score}` : ""}
          </span>
        </div>
        {d && (
          <div className="card-pad" style={{ paddingBottom: 8 }}>
            <div className="segbar">
              {d.risks_within_appetite > 0 && (
                <span
                  style={{
                    width: `${(d.risks_within_appetite / (d.total_risks || 1)) * 100}%`,
                    background: "var(--green)",
                  }}
                  title={`Within appetite: ${d.risks_within_appetite}`}
                />
              )}
              {d.risks_elevated > 0 && (
                <span
                  style={{
                    width: `${(d.risks_elevated / (d.total_risks || 1)) * 100}%`,
                    background: "var(--amber)",
                  }}
                  title={`Elevated: ${d.risks_elevated}`}
                />
              )}
              {d.risks_in_breach > 0 && (
                <span
                  style={{
                    width: `${(d.risks_in_breach / (d.total_risks || 1)) * 100}%`,
                    background: "var(--red)",
                  }}
                  title={`Breach: ${d.risks_in_breach}`}
                />
              )}
            </div>
            <div className="legend">
              <span className="item">
                <span className="dot" style={{ background: "var(--green)" }} />
                Within appetite <b style={{ color: "var(--text)" }}>{d.risks_within_appetite}</b>
              </span>
              <span className="item">
                <span className="dot" style={{ background: "var(--amber)" }} />
                Elevated <b style={{ color: "var(--text)" }}>{d.risks_elevated}</b>
              </span>
              <span className="item">
                <span className="dot" style={{ background: "var(--red)" }} />
                Breach <b style={{ color: "var(--text)" }}>{d.risks_in_breach}</b>
              </span>
            </div>
          </div>
        )}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Category</th>
                <th>Risks</th>
                <th>Max inherent</th>
                <th>Max residual</th>
                <th>Breaches</th>
                <th>Exposure (ALE)</th>
              </tr>
            </thead>
            <tbody>
              {agg?.rows.map((r) => (
                <tr key={r.category}>
                  <td className="cell-title">{r.category}</td>
                  <td>{r.count}</td>
                  <td className="muted">{r.max_inherent_score ?? "—"}</td>
                  <td className="muted">{r.max_residual_score ?? "—"}</td>
                  <td>
                    {r.breaches > 0 ? (
                      <span className="badge critical">{r.breaches}</span>
                    ) : (
                      <span className="muted">0</span>
                    )}
                  </td>
                  <td>{r.exposure ? money(r.exposure) : "—"}</td>
                </tr>
              ))}
              {agg && agg.rows.length > 0 && (
                <tr>
                  <td className="cell-title">Total</td>
                  <td colSpan={4}></td>
                  <td className="cell-title">{money(agg.total_exposure)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
