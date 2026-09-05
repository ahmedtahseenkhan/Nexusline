"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  api,
  type ActionItem,
  type AuditEntry,
  type DashboardOverview,
  type FrameworkPosture,
  type MatrixBand,
  type RiskMatrix,
  type TopRisk,
} from "@/lib/api";

/* The dashboard, rebuilt around the questions a risk function is judged on, in the
   order a board asks them:

     1. Are we inside the boundary we set?      — posture against appetite, top risks
     2. Are the controls actually working?      — assurance, tests overdue and failed
     3. Are we compliant, and can we prove it?  — per framework, assured vs mapped
     4. What is overdue or needs a decision?    — one queue, every line a link
     5. What happened?                          — incidents, KRIs, movement, activity

   Every number links to the register that produced it, and the headline score shows
   its own components, because a gauge with no reasons is decoration. Mapped-but-
   untested controls count for nothing anywhere on this page — same rule as the gap
   analysis and the residual engine, so the three can never disagree. */

const FONT_SANS = "'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const FONT_MONO = "'Space Grotesk', 'Plus Jakarta Sans', system-ui, sans-serif";
const SEV = { critical: "#b42318", high: "#c2622d", medium: "#b8892a", low: "#15803d" } as const;
const EMERALD = "#10b981";
const AMBER = "#d97706";
const RED = "#dc2626";
const SLATE = "#94a3b8";

const CARD: React.CSSProperties = {
  background: "#fff", border: "1px solid #e6e9ef", borderRadius: 16, boxShadow: "0 1px 2px rgba(15,23,42,.04)",
};
const H2: React.CSSProperties = { fontSize: 16, fontWeight: 700, margin: 0 };
const SUB: React.CSSProperties = { fontSize: 12.5, color: "#64748b" };

type Range = "30d" | "quarter" | "ytd";

function bandFromScore(score: number | null, bands?: MatrixBand[]): keyof typeof SEV {
  if (!score) return "low";
  if (bands?.length) {
    const hit = bands.find((b) => score >= b.min_score && score <= b.max_score);
    if (hit) return hit.severity as keyof typeof SEV;
  }
  if (score >= 15) return "critical";
  if (score >= 10) return "high";
  if (score >= 5) return "medium";
  return "low";
}

function timeAgo(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

/* ------------------------------------------------------------------ atoms */
function Gauge({ score, band }: { score: number; band: string }) {
  const R = 78, C = 2 * Math.PI * R, TRACK = C * 0.75;
  // Nothing in the registers: there is no score to give. An empty organisation is
  // neither healthy nor critical, and printing a number for one is how a wiped
  // system used to report 70/100.
  const empty = band === "no_data";
  const prog = empty ? 0 : Math.max(0, Math.min(1, score / 100)) * TRACK;
  const color = band === "healthy" ? "#34d399" : band === "elevated" ? "#fbbf24" : "#f87171";
  return (
    <svg viewBox="0 0 200 170" width={190} height={162} aria-label={empty ? "Governance health: no data yet" : `Governance health ${score} of 100`}>
      <circle cx="100" cy="100" r={R} fill="none" stroke="rgba(255,255,255,.08)" strokeWidth="14" strokeDasharray={`${TRACK} ${C}`} strokeLinecap="round" transform="rotate(135 100 100)" />
      {!empty && <circle cx="100" cy="100" r={R} fill="none" stroke={color} strokeWidth="14" strokeDasharray={`${prog} ${C}`} strokeLinecap="round" transform="rotate(135 100 100)" />}
      <text x="100" y="96" textAnchor="middle" fill={empty ? "#64748b" : "#f8fafc"} fontFamily={FONT_MONO} fontSize={empty ? "44" : "52"} fontWeight="700">{empty ? "—" : score}</text>
      <text x="100" y="118" textAnchor="middle" fill="#94a3b8" fontFamily={FONT_SANS} fontSize="12">{empty ? "no data yet" : "/ 100"}</text>
    </svg>
  );
}

function Stat({ label, value, sub, tone, href }: { label: string; value: React.ReactNode; sub?: string; tone?: "danger" | "warn" | "ok"; href?: string }) {
  const color = tone === "danger" ? RED : tone === "warn" ? AMBER : tone === "ok" ? "#15803d" : "#0f172a";
  const body = (
    <div style={{ ...CARD, padding: "16px 18px", height: "100%" }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".07em", textTransform: "uppercase", color: "#64748b" }}>{label}</div>
      <div style={{ fontFamily: FONT_MONO, fontSize: 30, fontWeight: 700, color, marginTop: 6, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ ...SUB, marginTop: 6 }}>{sub}</div>}
    </div>
  );
  return href ? <Link href={href} style={{ textDecoration: "none", color: "inherit" }}>{body}</Link> : body;
}

/** A stacked bar with a legend — the shape eramba uses for "why is this package not
 *  compliant", applied to assurance: what fraction is proven, untested, failing, absent. */
function Stack({ parts, total }: { parts: { label: string; value: number; color: string }[]; total: number }) {
  return (
    <div>
      <div style={{ display: "flex", height: 12, borderRadius: 6, overflow: "hidden", background: "#eef1f5" }}>
        {parts.filter((p) => p.value > 0).map((p) => (
          <div key={p.label} title={`${p.label}: ${p.value}`} style={{ width: `${(100 * p.value) / Math.max(total, 1)}%`, background: p.color }} />
        ))}
      </div>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 6, fontSize: 11.5, color: "#64748b" }}>
        {parts.map((p) => (
          <span key={p.label} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: p.color, display: "inline-block" }} />
            {p.label} <b style={{ color: "#0f172a" }}>{p.value}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

function SevChip({ value }: { value: string | null }) {
  if (!value) return <span style={{ color: SLATE }}>—</span>;
  const c = SEV[value as keyof typeof SEV] ?? SLATE;
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 12.5, fontWeight: 600, color: c }}><span style={{ width: 7, height: 7, borderRadius: "50%", background: c }} />{cap(value)}</span>;
}

/* ------------------------------------------------------------------- page */
export default function DashboardPage() {
  const [o, setO] = useState<DashboardOverview | null>(null);
  const [matrix, setMatrix] = useState<RiskMatrix | null>(null);
  const [activity, setActivity] = useState<AuditEntry[]>([]);
  const [heatMode, setHeatMode] = useState<"inherent" | "residual">("residual");
  const [range, setRange] = useState<Range>("30d");
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const days = range === "30d" ? 30 : range === "quarter" ? 90 : Math.max(7, Math.ceil((Date.now() - new Date(new Date().getFullYear(), 0, 1).getTime()) / 864e5));

  useEffect(() => {
    api.dashboardOverview(days).then(setO).catch((e) => setError(e instanceof Error ? e.message : "Could not load the dashboard"));
  }, [days]);
  useEffect(() => {
    api.riskMatrix().then(setMatrix).catch(() => {});
    api.audit(30).then((r) => setActivity(r.items)).catch(() => {});
  }, []);

  const today = useMemo(() => new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }), []);

  const bubbles = useMemo(() => {
    if (!matrix) return [];
    return matrix.cells.map((cell) => {
      const count = heatMode === "residual" ? cell.residual_count : cell.inherent_count;
      if (!count) return null;
      const band = bandFromScore(cell.score, matrix.bands);
      return {
        key: `${cell.likelihood}-${cell.impact}`, count,
        left: `${((cell.likelihood - 0.5) / matrix.size) * 100}%`, top: `${100 - ((cell.impact - 0.5) / matrix.size) * 100}%`,
        size: 24 + Math.min(count, 5) * 5, color: SEV[band],
        title: `Likelihood ${cell.likelihood} × Impact ${cell.impact} · ${count} risk${count > 1 ? "s" : ""} · ${band}`,
      };
    }).filter(Boolean) as { key: string; count: number; left: string; top: string; size: number; color: string; title: string }[];
  }, [matrix, heatMode]);

  async function execSummary() {
    setDownloading(true);
    try { await api.pdfExecutiveSummary(); } catch { /* ignore */ } finally { setDownloading(false); }
  }

  const tab = (active: boolean): React.CSSProperties => ({
    padding: "7px 13px", borderRadius: 8, cursor: "pointer", fontWeight: 600, fontSize: 13,
    background: active ? "#0f172a" : "transparent", color: active ? "#fff" : "#64748b",
  });
  const toneColor = (t: ActionItem["tone"]) => (t === "critical" ? RED : t === "warning" ? AMBER : "#2563eb");
  const toneBg = (t: ActionItem["tone"]) => (t === "critical" ? "rgba(239,68,68,.14)" : t === "warning" ? "rgba(251,191,36,.16)" : "rgba(37,99,235,.14)");

  const a = o?.assurance;
  const assuredPct = a && a.total ? Math.round((100 * (a.effective + a.partially_effective)) / a.total) : 0;
  const incidentDelta = o ? o.incidents.opened_in_period - o.incidents.opened_prior_period : 0;

  return (
    <div style={{ fontFamily: FONT_SANS, display: "flex", flexDirection: "column", gap: 18, color: "#0f172a" }}>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet" />

      {/* ------------------------------------------------------------ header */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: "0 0 6px", fontSize: 27, fontWeight: 800, letterSpacing: "-.02em" }}>Governance &amp; risk overview</h1>
          <p style={{ margin: 0, fontSize: 14, color: "#64748b" }}>
            Are we inside appetite, are the controls working, can we prove it, and what needs a decision — as of {today}.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ display: "flex", gap: 2, background: "#fff", border: "1px solid #e6e9ef", borderRadius: 10, padding: 3 }}>
            <span style={tab(range === "30d")} onClick={() => setRange("30d")}>30 days</span>
            <span style={tab(range === "quarter")} onClick={() => setRange("quarter")}>Quarter</span>
            <span style={tab(range === "ytd")} onClick={() => setRange("ytd")}>YTD</span>
          </div>
          <button className="btn" onClick={execSummary} disabled={downloading}>{downloading ? "Preparing…" : "Executive summary"}</button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {/* --------------------------------------- hero: health + the decision queue */}
      <div style={{ background: "linear-gradient(135deg,#0b1220 0%,#111c33 100%)", borderRadius: 18, padding: 22, display: "grid", gridTemplateColumns: "300px 1fr", gap: 22, color: "#e2e8f0" }}>
        <div style={{ borderRight: "1px solid rgba(255,255,255,.08)", paddingRight: 22 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase", color: "#94a3b8" }}>Governance health</div>
          <div style={{ display: "flex", justifyContent: "center", margin: "6px 0 2px" }}>
            {o ? <Gauge score={o.health.score} band={o.health.band} /> : <div style={{ height: 162 }} />}
          </div>
          {o && (
            <div style={{ display: "grid", gap: 7, marginTop: 4 }}>
              {o.health.components.map((c) => (
                <div key={c.key} title={c.detail}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                    <span style={{ color: "#cbd5e1" }}>{c.label} <span style={{ color: "#64748b" }}>· {Math.round(c.weight * 100)}%</span></span>
                    <b style={{ fontFamily: FONT_MONO, color: c.value >= 80 ? "#6ee7b7" : c.value >= 50 ? "#fcd34d" : "#fca5a5" }}>{Math.round(c.value)}%</b>
                  </div>
                  <div style={{ height: 4, borderRadius: 2, background: "rgba(255,255,255,.08)", marginTop: 3 }}>
                    <div style={{ width: `${c.value}%`, height: "100%", borderRadius: 2, background: c.value >= 80 ? "#34d399" : c.value >= 50 ? "#fbbf24" : "#f87171" }} />
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>{c.detail}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: "#f8fafc" }}>
              Needs a decision or is overdue
              {o && <span style={{ marginLeft: 8, fontSize: 12, fontWeight: 700, background: "rgba(52,211,153,.18)", color: "#6ee7b7", borderRadius: 999, padding: "2px 8px" }}>{o.actions.length}</span>}
            </span>
            <Link href="/notifications" style={{ fontSize: 12.5, color: "#94a3b8" }}>All alerts →</Link>
          </div>
          <div style={{ display: "grid", gap: 8 }}>
            {o?.actions.slice(0, 6).map((it) => (
              <Link key={it.key} href={it.href} style={{ display: "flex", alignItems: "center", gap: 12, background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.07)", borderRadius: 12, padding: "10px 14px", textDecoration: "none", color: "inherit" }}>
                <span style={{ fontSize: 10.5, fontWeight: 800, letterSpacing: ".06em", textTransform: "uppercase", padding: "3px 8px", borderRadius: 6, background: toneBg(it.tone), color: toneColor(it.tone) }}>{it.tone}</span>
                <span style={{ flex: 1, fontSize: 13.5, fontWeight: 600, color: "#f1f5f9" }}>{it.label}</span>
                <span style={{ fontSize: 12.5, color: "#94a3b8" }}>Open →</span>
              </Link>
            ))}
            {o && o.actions.length === 0 && <div style={{ fontSize: 13.5, color: "#94a3b8" }}>Nothing overdue and nothing waiting on a decision.</div>}
            {o && o.actions.length > 6 && <div style={{ fontSize: 12, color: "#64748b" }}>+ {o.actions.length - 6} more in the list below.</div>}
          </div>
        </div>
      </div>

      {/* ---------------------------------------------------------- KPI strip */}
      {o && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 12 }}>
          <Stat label="Above tolerance" value={o.posture.breach} sub={`${o.posture.elevated} elevated · ${o.posture.within_appetite} within appetite`} tone={o.posture.breach ? "danger" : "ok"} href="/risks" />
          <Stat label="Control assurance" value={`${assuredPct}%`} sub={`${a!.effective + a!.partially_effective} of ${a!.total} controls proven working`} tone={assuredPct >= 70 ? "ok" : assuredPct >= 40 ? "warn" : "danger"} href="/controls" />
          <Stat label="Compliance assured" value={`${o.compliance.overall_assured_pct}%`} sub={`${o.compliance.frameworks.length} frameworks · ${o.compliance.frameworks.reduce((n, f) => n + f.gaps, 0)} open gaps`} tone={o.compliance.overall_assured_pct >= 70 ? "ok" : o.compliance.overall_assured_pct >= 40 ? "warn" : "danger"} href="/compliance" />
          <Stat label="Open incidents" value={o.incidents.open} sub={`${o.incidents.reportable_open} reportable · ${incidentDelta >= 0 ? "+" : ""}${incidentDelta} vs prior ${o.period_days}d`} tone={o.incidents.reportable_open ? "danger" : o.incidents.open ? "warn" : "ok"} href="/incidents" />
          <Stat label="KRIs breaching" value={o.kris.red} sub={`${o.kris.amber} amber · ${o.kris.green} green · ${o.kris.no_data} no data`} tone={o.kris.red ? "danger" : o.kris.amber ? "warn" : "ok"} href="/operational-risk" />
          <Stat label="Tests overdue" value={a!.tests_overdue} sub={`${a!.last_test_failed} failed last test · ${a!.tests_due_30d} due in 30d`} tone={a!.last_test_failed ? "danger" : a!.tests_overdue ? "warn" : "ok"} href="/controls" />
        </div>
      )}

      {/* ------------------------------------------- 1. are we inside appetite? */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(330px, 0.85fr) minmax(0, 1.7fr)", gap: 18 }}>
        <div style={{ ...CARD, padding: "20px 22px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
            <div>
              <h2 style={H2}>Risk matrix</h2>
              <div style={SUB}>Bubble = risks in cell{o ? ` · ${o.posture.total_risks} plotted` : ""}</div>
            </div>
            <div style={{ display: "flex", gap: 2, background: "#f3f4f7", borderRadius: 9, padding: 3 }}>
              <button onClick={() => setHeatMode("inherent")} style={{ ...tab(heatMode === "inherent"), border: "none", fontFamily: "inherit" }}>Inherent</button>
              <button onClick={() => setHeatMode("residual")} style={{ ...tab(heatMode === "residual"), border: "none", fontFamily: "inherit" }}>Residual</button>
            </div>
          </div>
          <div style={{ position: "relative", aspectRatio: "1 / 1", maxHeight: 360, margin: "14px 0 6px 18px" }}>
            <div style={{ position: "absolute", left: -18, top: "50%", transform: "translateY(-50%) rotate(-90deg)", fontSize: 10.5, fontWeight: 700, letterSpacing: ".07em", color: "#94a3b8" }}>IMPACT →</div>
            <div style={{ position: "absolute", inset: 0, display: "grid", gridTemplateColumns: `repeat(${matrix?.size ?? 5},1fr)`, gridTemplateRows: `repeat(${matrix?.size ?? 5},1fr)`, gap: 5 }}>
              {Array.from({ length: (matrix?.size ?? 5) ** 2 }).map((_, idx) => {
                const size = matrix?.size ?? 5;
                const row = Math.floor(idx / size), col = idx % size;
                const impact = size - row, likelihood = col + 1;
                const band = bandFromScore(likelihood * impact, matrix?.bands);
                const tint = { critical: "rgba(180,35,24,.12)", high: "rgba(194,98,45,.12)", medium: "rgba(184,137,42,.10)", low: "rgba(21,128,61,.08)" }[band];
                return <div key={idx} style={{ background: tint, borderRadius: 8, border: "1px solid rgba(15,23,42,.05)" }} />;
              })}
            </div>
            {bubbles.map((b) => (
              <div key={b.key} title={b.title} style={{ position: "absolute", left: b.left, top: b.top, width: b.size, height: b.size, transform: "translate(-50%,-50%)", borderRadius: "50%", background: b.color, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONT_MONO, fontSize: 12, fontWeight: 700, boxShadow: "0 0 0 3px #fff, 0 4px 10px rgba(15,23,42,.18)" }}>
                {b.count}
              </div>
            ))}
            <div style={{ position: "absolute", right: 0, bottom: -18, fontSize: 10.5, fontWeight: 700, letterSpacing: ".07em", color: "#94a3b8" }}>LIKELIHOOD →</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 22, ...SUB }}>
            <span style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>{(["critical", "high", "medium", "low"] as const).map((s) => <SevChip key={s} value={s} />)}</span>
            {o && <span style={{ whiteSpace: "nowrap" }}>Appetite <b>{o.posture.appetite_score}</b> · tolerance <b>{o.posture.tolerance_score}</b> on a {matrix?.size ?? 5}×{matrix?.size ?? 5} matrix</span>}
          </div>
        </div>

        <div style={{ ...CARD, padding: "20px 22px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div>
              <h2 style={H2}>Top risks</h2>
              <div style={SUB}>Highest current exposure — residual where assessed, otherwise inherent</div>
            </div>
            <Link href="/risks" style={{ fontSize: 12.5 }}>Register →</Link>
          </div>
          <div className="table-wrap">
            <div style={{ overflowX: "auto", minWidth: 0 }}>
            <table style={{ fontSize: 13, width: "100%", tableLayout: "fixed", minWidth: 560 }}>
              <colgroup><col style={{ width: 62 }} /><col /><col style={{ width: 118 }} /><col style={{ width: 80 }} /><col style={{ width: 52 }} /><col style={{ width: 96 }} /></colgroup>
              <thead><tr><th>Ref</th><th>Risk · owner · segment</th><th>Exposure</th><th>Appetite</th><th>Ctrls</th><th>Review</th></tr></thead>
              <tbody>
                {o?.posture.top_risks.map((r: TopRisk) => (
                  <tr key={r.id} onClick={() => { window.location.href = `/risks?id=${r.id}`; }} style={{ cursor: "pointer" }}>
                    <td style={{ whiteSpace: "nowrap" }}><span className="ref">{r.reference}</span></td>
                    <td style={{ overflow: "hidden" }} title={r.title}>
                      <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.title}</div>
                      <div style={{ fontSize: 11.5, color: "#64748b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>
                        <span style={{ color: r.owner ? "#64748b" : RED }}>{r.owner || "Unassigned"}</span>{r.business_units.length > 0 && <> · {r.business_units.join(", ")}</>}
                      </div>
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}><SevChip value={r.severity} /> <span style={{ color: SLATE }}>({r.score ?? "—"})</span></td>
                    <td>{r.appetite_status === "breach" ? <span style={{ color: RED, fontWeight: 700 }}>Breach</span> : r.appetite_status === "elevated" ? <span style={{ color: AMBER, fontWeight: 600 }}>Elevated</span> : <span style={{ color: "#15803d" }}>Within</span>}</td>
                    <td style={{ textAlign: "center", color: r.control_count ? "#0f172a" : RED }}>{r.control_count || "none"}</td>
                    <td style={{ color: r.review_overdue ? RED : "#64748b", whiteSpace: "nowrap" }}>{r.review_overdue ? "Overdue" : r.next_review_date ?? "—"}</td>
                  </tr>
                ))}
                {o && o.posture.top_risks.length === 0 && <tr><td colSpan={6} style={{ color: SLATE, padding: 16 }}>No risks yet.</td></tr>}
              </tbody>
            </table>
            </div>
          </div>
        </div>
      </div>

      {/* ------------------- 2. are the controls working?  3. can we prove compliance? */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.35fr", gap: 18 }}>
        <div style={{ ...CARD, padding: "20px 22px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <h2 style={H2}>Control assurance</h2>
              <div style={SUB}>Proven by a test, not by being on the list</div>
            </div>
            <Link href="/controls" style={{ fontSize: 12.5 }}>Catalogue →</Link>
          </div>
          {a && (
            <>
              <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10 }}>
                <span style={{ fontFamily: FONT_MONO, fontSize: 34, fontWeight: 700, color: assuredPct >= 70 ? "#15803d" : assuredPct >= 40 ? AMBER : RED }}>{assuredPct}%</span>
                <span style={SUB}>of {a.total} controls effective or partially effective</span>
              </div>
              <Stack total={a.total} parts={[
                { label: "Effective", value: a.effective, color: "#15803d" },
                { label: "Partially", value: a.partially_effective, color: "#65a30d" },
                { label: "Ineffective", value: a.ineffective, color: RED },
                { label: "Never tested", value: a.not_assessed, color: "#cbd5e1" },
              ]} />
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 10, marginTop: 16 }}>
                {[
                  ["Tests overdue", a.tests_overdue, a.tests_overdue ? AMBER : "#0f172a"],
                  ["Failed last test", a.last_test_failed, a.last_test_failed ? RED : "#0f172a"],
                  [`Tested last ${o!.period_days}d`, a.tests_in_period, "#0f172a"],
                ].map(([l, v, c]) => (
                  <div key={String(l)} style={{ background: "#f8fafc", borderRadius: 10, padding: "10px 12px" }}>
                    <div style={{ fontFamily: FONT_MONO, fontSize: 22, fontWeight: 700, color: String(c) }}>{v as number}</div>
                    <div style={{ fontSize: 11.5, color: "#64748b" }}>{l as string}</div>
                  </div>
                ))}
              </div>
              {a.not_assessed > 0 && a.not_assessed >= a.total / 2 && (
                <div style={{ marginTop: 12, fontSize: 12.5, color: AMBER }}>
                  Most of the catalogue has never been tested. Until it is, these controls earn no residual credit and assure no clause.
                </div>
              )}
            </>
          )}
        </div>

        <div style={{ ...CARD, padding: "20px 22px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <h2 style={H2}>Compliance</h2>
              <div style={SUB}>Per framework: clauses backed by a working control, versus mapped-but-untested, failing, or nothing</div>
            </div>
            <Link href="/compliance" style={{ fontSize: 12.5 }}>Gap analysis →</Link>
          </div>
          <div style={{ display: "grid", gap: 14 }}>
            {o?.compliance.frameworks.slice(0, 6).map((f: FrameworkPosture) => (
              <div key={f.id}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 5 }}>
                  <Link href={`/compliance?framework=${f.id}`} style={{ fontSize: 13.5, fontWeight: 600, color: "#0f172a", textDecoration: "none" }}>{f.name}</Link>
                  <span style={SUB}>
                    <b style={{ color: f.applicable && f.assured === f.applicable ? "#15803d" : "#0f172a" }}>{f.assured}</b> of {f.applicable} assured · {f.gaps} gaps · {f.compliant_pct}% marked compliant
                  </span>
                </div>
                <Stack total={f.applicable} parts={[
                  { label: "Assured", value: f.assured, color: "#15803d" },
                  { label: "Mapped, not tested", value: f.unassessed, color: "#f59e0b" },
                  { label: "Failing", value: f.failing, color: RED },
                  { label: "No control", value: f.unmapped, color: "#cbd5e1" },
                ]} />
              </div>
            ))}
            {o && o.compliance.frameworks.length === 0 && <span style={SUB}>No frameworks yet — install one from the Framework Library.</span>}
          </div>
        </div>
      </div>

      {/* ------------------------------ 5. what happened: incidents, KRIs, segments, activity */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 18 }}>
        <div style={{ ...CARD, padding: "20px 22px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <h2 style={H2}>Incidents &amp; KRIs</h2>
            <Link href="/incidents" style={{ fontSize: 12.5 }}>Incidents →</Link>
          </div>
          {o && (
            <>
              <div style={{ display: "flex", gap: 14, alignItems: "baseline" }}>
                <span style={{ fontFamily: FONT_MONO, fontSize: 30, fontWeight: 700, color: o.incidents.open ? AMBER : "#15803d" }}>{o.incidents.open}</span>
                <span style={SUB}>open · {o.incidents.reportable_open} regulator-reportable · {o.incidents.tat_breached} past TAT</span>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", margin: "8px 0 14px" }}>
                {(["critical", "high", "medium", "low"] as const).map((s) => (
                  <span key={s} style={{ fontSize: 12.5 }}><SevChip value={s} /> <b>{o.incidents.open_by_severity[s] ?? 0}</b></span>
                ))}
              </div>
              <div style={{ fontSize: 12.5, color: "#64748b", marginBottom: 12 }}>
                {o.incidents.opened_in_period} opened in the last {o.period_days} days ({incidentDelta >= 0 ? "+" : ""}{incidentDelta} vs the {o.period_days} before).
              </div>
              <div style={{ borderTop: "1px solid #eef1f5", paddingTop: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 700 }}>Key risk indicators</span>
                  <Link href="/operational-risk" style={{ fontSize: 12 }}>All KRIs →</Link>
                </div>
                <div style={{ display: "flex", gap: 12, fontSize: 12.5 }}>
                  <span><b style={{ color: RED }}>{o.kris.red}</b> red</span>
                  <span><b style={{ color: AMBER }}>{o.kris.amber}</b> amber</span>
                  <span><b style={{ color: "#15803d" }}>{o.kris.green}</b> green</span>
                  <span style={{ color: SLATE }}>{o.kris.no_data} no data</span>
                </div>
                {o.kris.red_items.map((k) => (
                  <div key={k.id} style={{ marginTop: 8, fontSize: 12.5, display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{k.reference ? `${k.reference} · ` : ""}{k.name}</span>
                    <span style={{ color: RED, fontFamily: FONT_MONO, whiteSpace: "nowrap" }}>{k.current_value ?? "—"}{k.unit ? ` ${k.unit}` : ""} / limit {k.limit_threshold ?? "—"}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div style={{ ...CARD, padding: "20px 22px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <h2 style={H2}>By segment</h2>
            <Link href="/business-units" style={{ fontSize: 12.5 }}>Business units →</Link>
          </div>
          <div className="table-wrap">
            <table style={{ fontSize: 13 }}>
              <thead><tr><th>Business unit</th><th style={{ textAlign: "right" }}>Risks</th><th style={{ textAlign: "right" }}>Breach</th><th style={{ textAlign: "right" }}>Critical</th></tr></thead>
              <tbody>
                {o?.segments.slice(0, 7).map((s) => (
                  <tr key={s.id} onClick={() => { window.location.href = `/risks?business_unit_id=${s.id}`; }} style={{ cursor: "pointer" }}>
                    <td style={{ fontWeight: 600 }}>{s.name}</td>
                    <td style={{ textAlign: "right" }}>{s.risks}</td>
                    <td style={{ textAlign: "right", color: s.breach ? RED : "#64748b", fontWeight: s.breach ? 700 : 400 }}>{s.breach || "—"}</td>
                    <td style={{ textAlign: "right", color: s.critical ? SEV.critical : "#64748b" }}>{s.critical || "—"}</td>
                  </tr>
                ))}
                {o && o.segments.length === 0 && <tr><td colSpan={4} style={{ color: SLATE, padding: 12 }}>No risks are tagged to a business unit yet.</td></tr>}
              </tbody>
            </table>
          </div>
          {o && (
            <div style={{ borderTop: "1px solid #eef1f5", marginTop: 12, paddingTop: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Third parties</div>
              <div style={{ fontSize: 12.5, color: "#64748b" }}>
                {o.third_parties.total} vendors · <b style={{ color: o.third_parties.critical ? "#0f172a" : "#64748b" }}>{o.third_parties.critical}</b> critical ·{" "}
                <b style={{ color: o.third_parties.assessments_overdue ? RED : "#64748b" }}>{o.third_parties.assessments_overdue}</b> assessments overdue
                {Object.keys(o.third_parties.by_rating).length > 0 && (
                  <> · rated {Object.entries(o.third_parties.by_rating).map(([k, v]) => `${v} ${k}`).join(", ")}</>
                )}
              </div>
            </div>
          )}
        </div>

        <div style={{ ...CARD, padding: "20px 22px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
            <h2 style={H2}>Movement</h2>
            <span style={SUB}>last {o?.period_days ?? days} days</span>
          </div>
          {o && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 14 }}>
              {[
                ["Risks added", o.movement.risks_created], ["Risks closed", o.movement.risks_closed],
                ["Control tests recorded", o.movement.tests_recorded], ["Issues closed", o.movement.issues_closed],
                ["Incidents opened", o.movement.incidents_opened], ["Acceptances lapsed", o.movement.acceptances_lapsed],
              ].map(([l, v]) => (
                <div key={String(l)} style={{ background: "#f8fafc", borderRadius: 10, padding: "8px 12px" }}>
                  <div style={{ fontFamily: FONT_MONO, fontSize: 20, fontWeight: 700 }}>{v as number}</div>
                  <div style={{ fontSize: 11.5, color: "#64748b" }}>{l as string}</div>
                </div>
              ))}
            </div>
          )}
          <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Recent activity</div>
          <div style={{ display: "grid", gap: 8 }}>
            {activity.slice(0, 6).map((e) => (
              <div key={e.id} style={{ display: "flex", gap: 10, fontSize: 12.5 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: EMERALD, marginTop: 6, flexShrink: 0 }} />
                <div style={{ minWidth: 0 }}>
                  <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.summary}</div>
                  <div style={{ fontSize: 11.5, color: SLATE }}>{e.actor_email} · {timeAgo(e.created_at)}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
