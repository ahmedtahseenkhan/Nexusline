"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  api,
  type AuditEntry,
  type ComplianceSummary,
  type Dashboard,
  type RiskAggregate,
  type RiskMatrix,
} from "@/lib/api";

// Font stacks. The webfonts are loaded via a plain <link> (build-safe, no build-time
// fetch); if unreachable (air-gapped on-prem) the browser falls back to system-ui.
const FONT_SANS = "'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const FONT_MONO = "'Space Grotesk', 'Plus Jakarta Sans', system-ui, sans-serif";

// ---------------------------------------------------------------- palette (from the v2 design)
const SEV = { critical: "#b42318", high: "#c2622d", medium: "#b8892a", low: "#15803d" } as const;
const EMERALD = "#10b981";

function money(n: number) {
  if (!n) return "$0";
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${Math.round(n / 1_000)}K`;
  return `$${Math.round(n)}`;
}
function bandFromScore(score: number | null): keyof typeof SEV {
  if (!score) return "low";
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

const CARD: React.CSSProperties = {
  background: "#fff",
  border: "1px solid #e5e9ee",
  borderRadius: 18,
  boxShadow: "0 1px 2px rgba(16,24,40,.04)",
};

// ================================================================ Governance gauge
function Gauge({ score }: { score: number }) {
  const CIRC = 502.65; // 2πr, r=80
  const TRACK = 376.99; // 270° arc
  const prog = Math.max(0, Math.min(1, score / 100)) * TRACK;
  const band = score >= 80 ? "Healthy" : score >= 60 ? "Elevated" : "Critical";
  const bandColor = score >= 80 ? "#34d399" : score >= 60 ? "#fbbf24" : "#f87171";
  const bandBg = score >= 80 ? "rgba(52,211,153,.12)" : score >= 60 ? "rgba(251,191,36,.12)" : "rgba(248,113,113,.12)";
  return (
    <>
      <div style={{ position: "relative", width: "100%", display: "flex", justifyContent: "center", marginTop: 4 }}>
        <svg viewBox="0 0 200 168" style={{ width: 200 }}>
          <defs>
            <linearGradient id="gaugegrad" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0" stopColor="#ef4444" />
              <stop offset="0.45" stopColor="#f59e0b" />
              <stop offset="0.75" stopColor="#eab308" />
              <stop offset="1" stopColor="#10b981" />
            </linearGradient>
          </defs>
          <circle cx="100" cy="100" r="80" fill="none" stroke="rgba(255,255,255,.08)" strokeWidth="16" strokeLinecap="round" strokeDasharray={`${TRACK} ${CIRC}`} transform="rotate(135 100 100)" />
          <circle cx="100" cy="100" r="80" fill="none" stroke="url(#gaugegrad)" strokeWidth="16" strokeLinecap="round" strokeDasharray={`${prog} ${CIRC}`} transform="rotate(135 100 100)" />
          <text x="100" y="96" textAnchor="middle" fill="#f8fafc" fontFamily={FONT_MONO} fontSize="52" fontWeight="700">{score}</text>
          <text x="100" y="120" textAnchor="middle" fill="#7d959d" fontSize="13" fontWeight="600">/ 100</text>
        </svg>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", marginTop: 2 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: bandColor, background: bandBg, padding: "4px 12px", borderRadius: 20 }}>{band}</span>
      </div>
    </>
  );
}

// ================================================================ compliance donut
function Donut({ pct, size = 150, inset = 14, big }: { pct: number; size?: number; inset?: number; big?: boolean }) {
  const deg = Math.round((pct / 100) * 360);
  const color = pct >= 80 ? EMERALD : pct >= 40 ? "#0ea5a3" : "#c2622d";
  return (
    <div style={{ position: "relative", width: size, height: size, borderRadius: "50%", background: `conic-gradient(${color} 0deg ${deg}deg, #eef1f4 ${deg}deg 360deg)`, flex: "none" }}>
      <div style={{ position: "absolute", inset, borderRadius: "50%", background: "#fff", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        <div style={{ fontFamily: big ? FONT_MONO : undefined, fontSize: big ? 34 : size <= 46 ? 11 : 13, fontWeight: 700, lineHeight: 1, color: pct >= 80 ? "#15803d" : "#0f172a" }}>{pct}%</div>
        {big && <div style={{ fontSize: 11.5, color: "#94a3b8", marginTop: 3 }}>overall</div>}
      </div>
    </div>
  );
}

// ================================================================ page
type Range = "30d" | "quarter" | "ytd";

export default function DashboardPage() {
  const [d, setD] = useState<Dashboard | null>(null);
  const [c, setC] = useState<ComplianceSummary | null>(null);
  const [agg, setAgg] = useState<RiskAggregate | null>(null);
  const [matrix, setMatrix] = useState<RiskMatrix | null>(null);
  const [activity, setActivity] = useState<AuditEntry[]>([]);
  const [heatMode, setHeatMode] = useState<"inherent" | "residual">("residual");
  const [range, setRange] = useState<Range>("30d");
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    api.dashboard().then(setD).catch(() => {});
    api.complianceSummary().then(setC).catch(() => {});
    api.riskAggregate().then(setAgg).catch(() => {});
    api.riskMatrix().then(setMatrix).catch(() => {});
    api.audit(50).then((r) => setActivity(r.items)).catch(() => {});
  }, []);

  const today = useMemo(() => new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }), []);
  const clock = useMemo(() => new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }), []);

  const critical = d?.risks_by_inherent_severity?.critical || 0;
  const criticalResidual = d?.risks_by_residual_severity?.critical || 0;
  const highResidual = d?.risks_by_residual_severity?.high || 0;
  const withinTolerance = d ? d.total_risks - d.risks_in_breach : 0;
  const onTrack = c ? c.frameworks.filter((f) => f.compliant_pct >= 80).length : 0;

  // ---- composite governance-health score (0-100), computed from live posture ----
  const score = useMemo(() => {
    if (!d) return 0;
    const tol = d.total_risks ? withinTolerance / d.total_risks : 1;
    const comp = c ? c.overall_compliant_pct / 100 : 0.5;
    const resid = d.total_risks ? 1 - (criticalResidual + highResidual) / d.total_risks : 1;
    return Math.round(100 * (0.5 * tol + 0.3 * comp + 0.2 * resid));
  }, [d, c, withinTolerance, criticalResidual, highResidual]);

  // ---- "needs your attention" queue, derived from real data ----
  const attention = useMemo(() => {
    if (!d) return [];
    const items: { tag: string; chip: [string, string]; title: string; meta: string; action: string; href: string; danger?: boolean }[] = [];
    if (d.risks_in_breach > 0)
      items.push({ tag: "BREACH", chip: ["rgba(239,68,68,.16)", "#fca5a5"], title: `${d.risks_in_breach} risk${d.risks_in_breach > 1 ? "s" : ""} exceed tolerance (residual ≥ ${d.tolerance_score})`, meta: "Escalation to risk owner required", action: "Escalate", href: "/risks", danger: true });
    if (critical > 0)
      items.push({ tag: "CRITICAL", chip: ["rgba(251,191,36,.16)", "#fcd34d"], title: `${critical} critical inherent risk${critical > 1 ? "s" : ""} pending treatment`, meta: "No residual assessment recorded", action: "Assign", href: "/risks" });
    if (c)
      c.frameworks.filter((f) => f.compliant_pct < 80).slice(0, 1).forEach((f) =>
        items.push({ tag: "REVIEW", chip: ["rgba(251,191,36,.16)", "#fcd34d"], title: `${f.name} at ${f.compliant_pct}% — ${f.total_requirements - f.compliant} controls awaiting evidence`, meta: "Framework below target compliance", action: "Review", href: "/compliance" }));
    if (d.overdue_reviews > 0)
      items.push({ tag: "REVIEW", chip: ["rgba(251,191,36,.16)", "#fcd34d"], title: `${d.overdue_reviews} asset review${d.overdue_reviews > 1 ? "s" : ""} overdue`, meta: "Review cycle lapsed", action: "Review", href: "/it-assets" });
    if (d.pending_acceptances > 0)
      items.push({ tag: "APPROVE", chip: ["rgba(52,211,153,.16)", "#6ee7b7"], title: `${d.pending_acceptances} risk acceptance${d.pending_acceptances > 1 ? "s" : ""} awaiting sign-off`, meta: "Pending approver decision", action: "Approve", href: "/approvals" });
    return items.slice(0, 3);
  }, [d, c, critical]);

  // ---- risk matrix cells + bubbles ----
  const pos: Record<number, number> = { 1: 10, 2: 30, 3: 50, 4: 70, 5: 90 };
  const bubbles = useMemo(() => {
    if (!matrix) return [];
    return matrix.cells
      .map((cell) => {
        const count = heatMode === "residual" ? cell.residual_count : cell.inherent_count;
        if (!count) return null;
        const band = bandFromScore(cell.score);
        const size = 24 + Math.min(count, 5) * 5;
        return {
          key: `${cell.likelihood}-${cell.impact}`,
          count,
          left: `${pos[cell.likelihood] ?? cell.likelihood * 20 - 10}%`,
          top: `${100 - (pos[cell.impact] ?? cell.impact * 20 - 10)}%`,
          size,
          color: SEV[band],
          title: `Likelihood ${cell.likelihood} × Impact ${cell.impact} · ${count} risk${count > 1 ? "s" : ""} · ${band}`,
        };
      })
      .filter(Boolean) as { key: string; count: number; left: string; top: string; size: number; color: string; title: string }[];
  }, [matrix, heatMode]);

  // ---- activity filtered by the selected range ----
  const rangeStart = useMemo(() => {
    const now = new Date();
    if (range === "30d") return new Date(now.getTime() - 30 * 864e5);
    if (range === "quarter") return new Date(now.getTime() - 90 * 864e5);
    return new Date(now.getFullYear(), 0, 1);
  }, [range]);
  const shownActivity = useMemo(
    () => activity.filter((a) => new Date(a.created_at) >= rangeStart).slice(0, 7),
    [activity, rangeStart]
  );

  async function execSummary() {
    setDownloading(true);
    try { await api.pdfExecutiveSummary(); } catch { /* ignore */ } finally { setDownloading(false); }
  }

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: "7px 13px", borderRadius: 8, cursor: "pointer", fontWeight: 600,
    background: active ? "#0f172a" : "transparent", color: active ? "#fff" : "#64748b",
  });
  const heatBtn = (active: boolean): React.CSSProperties => ({
    border: "none", cursor: "pointer", fontFamily: "inherit", fontSize: 12.5, fontWeight: 600,
    padding: "6px 14px", borderRadius: 7, background: active ? "#0f172a" : "transparent", color: active ? "#fff" : "#64748b",
  });

  return (
    <div style={{ fontFamily: FONT_SANS, display: "flex", flexDirection: "column", gap: 18, color: "#0f172a" }}>
      {/* Build-safe webfont load — degrades to system-ui if unreachable (air-gapped). */}
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet" />

      {/* ---------- page header ---------- */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 24, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: "0 0 6px", fontSize: 27, fontWeight: 800, letterSpacing: "-.02em" }}>Governance &amp; risk overview</h1>
          <p style={{ margin: 0, fontSize: 14, color: "#64748b" }}>
            Enterprise posture across risk, compliance and controls — as of {today}.
            <span style={{ marginLeft: 10, display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600, color: "#0f766e" }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: EMERALD, display: "inline-block" }} />Live · {clock}
            </span>
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ display: "flex", background: "#fff", border: "1px solid #e5e9ee", borderRadius: 11, padding: 3, fontSize: 12.5, fontWeight: 600 }}>
            <span style={tabStyle(range === "30d")} onClick={() => setRange("30d")}>30 days</span>
            <span style={tabStyle(range === "quarter")} onClick={() => setRange("quarter")}>Quarter</span>
            <span style={tabStyle(range === "ytd")} onClick={() => setRange("ytd")}>YTD</span>
          </div>
          <button onClick={execSummary} disabled={downloading}
            style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 15px", border: "none", borderRadius: 11, background: EMERALD, cursor: "pointer", fontFamily: "inherit", fontSize: 13.5, fontWeight: 700, color: "#04231b", boxShadow: "0 2px 8px rgba(16,185,129,.3)", opacity: downloading ? 0.7 : 1 }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ width: 16, height: 16 }}><path d="M6 3h8l4 4v14H6zM14 3v4h4M9 13h6M9 17h6" /></svg>
            {downloading ? "Preparing…" : "Executive summary"}
          </button>
        </div>
      </div>

      {/* ---------- HERO BAND ---------- */}
      <div style={{ background: "radial-gradient(120% 140% at 0% 0%, #12242c 0%, #0b1519 60%)", border: "1px solid #0a1418", borderRadius: 22, padding: "26px 30px", display: "grid", gridTemplateColumns: "300px 1fr", gap: 34, boxShadow: "0 16px 40px -18px rgba(6,20,24,.5)" }}>
        <div style={{ borderRight: "1px solid rgba(255,255,255,.08)", paddingRight: 30 }}>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".11em", color: "#5f7a83", marginBottom: 6 }}>GOVERNANCE HEALTH</div>
          <Gauge score={score} />
          <div style={{ display: "flex", flexDirection: "column", gap: 9, marginTop: 20 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }}><span style={{ color: "#9fb2ba" }}>Risks within tolerance</span><span style={{ color: "#e2e8f0", fontWeight: 700 }}>{withinTolerance} / {d?.total_risks ?? 0}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }}><span style={{ color: "#9fb2ba" }}>Residual within appetite</span><span style={{ color: "#e2e8f0", fontWeight: 700 }}>{d?.risks_within_appetite ?? 0} / {d?.total_risks ?? 0}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }}><span style={{ color: "#9fb2ba" }}>Frameworks on track</span><span style={{ color: "#e2e8f0", fontWeight: 700 }}>{onTrack} / {c?.total_frameworks ?? 0}</span></div>
          </div>
        </div>

        <div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span style={{ fontSize: 15, fontWeight: 700, color: "#f8fafc" }}>Needs your attention</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#052e26", background: "#34d399", borderRadius: 20, padding: "2px 9px" }}>{attention.length}</span>
            </div>
            <Link href="/issues" style={{ fontSize: 12.5, color: "#7d959d", fontWeight: 600, textDecoration: "none" }}>View all →</Link>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {attention.map((a, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 14, padding: "13px 16px", background: "rgba(255,255,255,.045)", border: "1px solid rgba(255,255,255,.07)", borderRadius: 13 }}>
                <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".05em", color: a.chip[1], background: a.chip[0], borderRadius: 7, padding: "5px 9px", flex: "none" }}>{a.tag}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: "#f1f5f9", lineHeight: 1.35 }}>{a.title}</div>
                  <div style={{ fontSize: 11.5, color: "#7d959d", marginTop: 2 }}>{a.meta}</div>
                </div>
                <Link href={a.href} style={{ textDecoration: "none", fontSize: 12, fontWeight: 700, padding: "8px 14px", borderRadius: 9, flex: "none", background: a.danger ? "#e11d48" : "rgba(255,255,255,.1)", color: a.danger ? "#fff" : "#e2e8f0" }}>{a.action}</Link>
              </div>
            ))}
            {d && attention.length === 0 && (
              <div style={{ padding: "22px 16px", textAlign: "center", background: "rgba(255,255,255,.04)", border: "1px solid rgba(255,255,255,.07)", borderRadius: 13, color: "#9fb2ba", fontSize: 13 }}>
                ✓ Nothing needs escalation — all risks within tolerance and reviews current.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ---------- METRIC STRIP ---------- */}
      <div style={{ ...CARD, display: "grid", gridTemplateColumns: "repeat(5,1fr)", overflow: "hidden" }}>
        {[
          { k: "TOTAL RISKS", v: d?.total_risks ?? "—", sub: `${withinTolerance} within tolerance`, color: "#0f172a" },
          { k: "CRITICAL INHERENT", v: critical, sub: `of ${d?.total_risks ?? 0} total`, color: SEV.critical },
          { k: "OVERALL COMPLIANT", v: c ? `${c.overall_compliant_pct}%` : "—", sub: `${c?.total_frameworks ?? 0} frameworks`, color: "#0f172a" },
          { k: "ANNUAL EXPOSURE", v: d ? money(d.total_exposure) : "—", sub: "expected annual loss", color: "#0f172a" },
          { k: "TOLERANCE BREACHES", v: d?.risks_in_breach ?? "—", sub: d && d.risks_in_breach > 0 ? "escalation due" : "within tolerance", color: d && d.risks_in_breach > 0 ? SEV.critical : "#0f172a" },
        ].map((t, i) => (
          <div key={t.k} style={{ padding: "18px 20px", borderRight: i < 4 ? "1px solid #eef1f4" : "none" }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".05em", color: "#94a3b8" }}>{t.k}</div>
            <div style={{ fontFamily: FONT_MONO, fontSize: 30, fontWeight: 700, lineHeight: 1, marginTop: 8, color: t.color }}>{t.v}</div>
            <div style={{ fontSize: 11.5, color: "#94a3b8", fontWeight: 500, marginTop: 6 }}>{t.sub}</div>
          </div>
        ))}
      </div>

      {/* ---------- MATRIX + COMPLIANCE ---------- */}
      <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18 }}>
        {/* risk matrix */}
        <div style={{ ...CARD, padding: "22px 24px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>Risk matrix</div>
              <div style={{ fontSize: 12.5, color: "#94a3b8", marginTop: 2 }}>Bubble = risks in cell · {matrix?.total ?? 0} plotted</div>
            </div>
            <div style={{ display: "flex", background: "#f4f6f8", border: "1px solid #e5e9ee", borderRadius: 9, padding: 3 }}>
              <button onClick={() => setHeatMode("inherent")} style={heatBtn(heatMode === "inherent")}>Inherent</button>
              <button onClick={() => setHeatMode("residual")} style={heatBtn(heatMode === "residual")}>Residual</button>
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "20px 1fr", gap: 12, marginTop: 14 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
              <span style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", fontSize: 10, fontWeight: 700, letterSpacing: ".12em", color: "#94a3b8" }}>IMPACT →</span>
            </div>
            <div>
              <div style={{ position: "relative", width: "100%", aspectRatio: "1.35 / 1" }}>
                <div style={{ position: "absolute", inset: 0, display: "grid", gridTemplateColumns: "repeat(5,1fr)", gridTemplateRows: "repeat(5,1fr)", gap: 5 }}>
                  {Array.from({ length: 25 }).map((_, idx) => {
                    const row = Math.floor(idx / 5), col = idx % 5;
                    const impact = 5 - row, likelihood = col + 1;
                    const band = bandFromScore(impact * likelihood);
                    return <div key={idx} style={{ borderRadius: 9, background: SEV[band] + "22", border: `1px solid ${SEV[band]}2e` }} />;
                  })}
                </div>
                {bubbles.map((b) => (
                  <div key={b.key} title={b.title}
                    style={{ fontFamily: FONT_MONO, position: "absolute", left: b.left, top: b.top, transform: "translate(-50%,-50%)", width: b.size, height: b.size, borderRadius: "50%", background: b.color + "e0", border: "2px solid #fff", boxShadow: `0 2px 8px ${b.color}66`, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 11, fontWeight: 700, zIndex: 2, cursor: "default" }}>
                    {b.count}
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".12em", color: "#94a3b8", marginTop: 10, textAlign: "right" }}>LIKELIHOOD →</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginTop: 14, paddingTop: 14, borderTop: "1px solid #f1f4f7" }}>
            {(["critical", "high", "medium", "low"] as const).map((k) => (
              <div key={k} style={{ display: "flex", alignItems: "center", gap: 7 }}>
                <span style={{ width: 10, height: 10, borderRadius: "50%", background: SEV[k] }} />
                <span style={{ fontSize: 12.5, color: "#475569", textTransform: "capitalize" }}>{k}</span>
              </div>
            ))}
            <div style={{ marginLeft: "auto", fontSize: 12, color: "#94a3b8" }}>appetite <b style={{ color: "#334155" }}>{matrix?.appetite_score ?? d?.appetite_score ?? "—"}</b> · tolerance <b style={{ color: "#334155" }}>{matrix?.tolerance_score ?? d?.tolerance_score ?? "—"}</b></div>
          </div>
        </div>

        {/* compliance rings */}
        <div style={{ ...CARD, padding: "22px 24px", display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Compliance</div>
            <div style={{ fontSize: 12.5, color: "#94a3b8" }}>{c?.total_frameworks ?? 0} frameworks</div>
          </div>
          <div style={{ display: "flex", justifyContent: "center", padding: "12px 0 18px" }}>
            <Donut pct={c?.overall_compliant_pct ?? 0} big />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: "auto" }}>
            {(c?.frameworks ?? []).slice(0, 4).map((f) => (
              <div key={f.framework_id} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <Donut pct={f.compliant_pct} size={46} inset={6} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 1 }}>{f.compliant} of {f.total_requirements} controls met</div>
                </div>
              </div>
            ))}
            {c && c.frameworks.length === 0 && <span style={{ fontSize: 13, color: "#94a3b8" }}>No frameworks yet — install one from the Framework Library.</span>}
          </div>
        </div>
      </div>

      {/* ---------- ROLL-UP + ACTIVITY ---------- */}
      <div style={{ display: "grid", gridTemplateColumns: "1.55fr 1fr", gap: 18 }}>
        {/* enterprise roll-up */}
        <div style={{ ...CARD, padding: "22px 24px 10px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Enterprise risk roll-up</div>
            <div style={{ fontSize: 12.5, color: "#94a3b8" }}>by category</div>
          </div>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", color: "#94a3b8", fontSize: 10.5, fontWeight: 700, letterSpacing: ".06em" }}>
                <th style={{ padding: "8px 12px 8px 0" }}>CATEGORY</th>
                <th style={{ padding: "8px 12px", textAlign: "center" }}>RISKS</th>
                <th style={{ padding: "8px 12px" }}>RESIDUAL</th>
                <th style={{ padding: "8px 12px", textAlign: "center" }}>BREACH</th>
                <th style={{ padding: "8px 0 8px 12px", textAlign: "right" }}>EXPOSURE</th>
              </tr>
            </thead>
            <tbody>
              {(agg?.rows ?? []).map((r) => {
                const band = bandFromScore(r.max_residual_score);
                return (
                  <tr key={r.category} style={{ borderTop: "1px solid #f1f4f7", fontSize: 13.5 }}>
                    <td style={{ padding: "14px 12px 14px 0", fontWeight: 600 }}>{r.category}</td>
                    <td style={{ padding: "14px 12px", color: "#475569", textAlign: "center" }}>{r.count}</td>
                    <td style={{ padding: "14px 12px" }}>
                      <div title={`max residual: ${band}`} style={{ display: "flex", height: 8, borderRadius: 5, overflow: "hidden", background: "#eef1f4", minWidth: 110 }}>
                        <div style={{ width: `${Math.min(100, ((r.max_residual_score ?? 0) / 25) * 100)}%`, background: SEV[band] }} />
                      </div>
                    </td>
                    <td style={{ padding: "14px 12px", textAlign: "center" }}>
                      {r.breaches > 0 ? (
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "3px 9px", background: "rgba(225,29,72,.09)", color: SEV.critical, fontWeight: 700, borderRadius: 20, fontSize: 12 }}>
                          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#e11d48" }} />{r.breaches}
                        </span>
                      ) : <span style={{ color: "#cbd5e1" }}>—</span>}
                    </td>
                    <td style={{ padding: "14px 0 14px 12px", textAlign: "right", fontWeight: 700 }}>{r.exposure ? money(r.exposure) : "—"}</td>
                  </tr>
                );
              })}
              {agg && agg.rows.length > 0 && (
                <tr style={{ borderTop: "2px solid #e5e9ee", fontSize: 13.5 }}>
                  <td style={{ padding: "14px 12px 14px 0", fontWeight: 700 }}>Total</td>
                  <td style={{ padding: "14px 12px", textAlign: "center", fontWeight: 700 }}>{agg.rows.reduce((s, r) => s + r.count, 0)}</td>
                  <td style={{ padding: "14px 12px" }} />
                  <td style={{ padding: "14px 12px", textAlign: "center", fontWeight: 700, color: SEV.critical }}>{agg.rows.reduce((s, r) => s + r.breaches, 0)}</td>
                  <td style={{ fontFamily: FONT_MONO, padding: "14px 0 14px 12px", textAlign: "right", fontWeight: 800 }}>{money(agg.total_exposure)}</td>
                </tr>
              )}
              {agg && agg.rows.length === 0 && (
                <tr><td colSpan={5} style={{ padding: "20px 0", color: "#94a3b8", fontSize: 13 }}>No risks recorded yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* activity timeline */}
        <div style={{ ...CARD, padding: "22px 24px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <div style={{ fontSize: 16, fontWeight: 700 }}>Recent activity</div>
            <div style={{ fontSize: 12, color: "#94a3b8" }}>{range === "30d" ? "30 days" : range === "quarter" ? "Quarter" : "YTD"}</div>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {shownActivity.map((ev, i) => (
              <div key={ev.id} style={{ display: "flex", gap: 14 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: "none" }}>
                  <span style={{ width: 9, height: 9, borderRadius: "50%", background: EMERALD, marginTop: 5, boxShadow: "0 0 0 3px rgba(16,185,129,.14)" }} />
                  {i < shownActivity.length - 1 && <span style={{ width: 2, flex: 1, background: "#eef1f4" }} />}
                </div>
                <div style={{ paddingBottom: 16, minWidth: 0 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600, color: "#1e293b", lineHeight: 1.35 }}>{ev.summary}</div>
                  <div style={{ fontSize: 11.5, color: "#94a3b8", marginTop: 2 }}>{ev.actor_email} · {timeAgo(ev.created_at)}</div>
                </div>
              </div>
            ))}
            {shownActivity.length === 0 && <span style={{ fontSize: 13, color: "#94a3b8" }}>No activity in this period.</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
