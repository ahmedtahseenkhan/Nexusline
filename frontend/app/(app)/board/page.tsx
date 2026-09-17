"use client";

/* Board home (GET /board/home) — the board's questions, in the board's words:
   are we inside appetite and how has that moved over the last four quarters; which risks
   matter most and did they get better or worse; do the controls work; can we show
   compliance; which indicators are in breach; what is overdue; and what has the board
   itself decided that is due. Read-only. Trends come from period snapshots: a quarter
   with no snapshot is drawn as a gap, never as zero. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall, downloadBlob } from "@/lib/api";
import { Badge } from "@/components/badges";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";

type AppetitePoint = { date: string; as_of: string | null; risks: number | null; within: number | null; elevated: number | null; breach: number | null };
type TrendPoint = { date: string; as_of: string | null; value: number | null };
type Category = { key: string; label: string; appetite: number; tolerance: number; risks: number; within: number; elevated: number; breach: number; trend: AppetitePoint[] };
type TopRisk = { id: string; reference: string; title: string; score: number | null; severity: string | null; appetite_status: string | null; owner: string; movement: string; movement_text: string };
type Headline = { value: number | null; detail: string; trend: TrendPoint[] };
type Kri = { id: string; reference: string; name: string; status: string; value: number | null; unit: string; threshold_text: string; owner: string; readings: { as_of: string | null; value: number }[] };
type Issue = { id: string; reference: string; title: string; severity: string; owner: string; due_date: string | null; days_overdue: number; regulator_related: boolean };
type Decision = { id: string; reference: string; description: string; decision_type: string; status: string; owner: string; due_date: string | null; overdue: boolean; mine: boolean; committee: string; meeting: string };
type Meeting = { id: string; reference: string; title: string; committee: string; meeting_date: string | null; days_away: number | null; pack_state: string; mine: boolean };
type Pack = { id: string; title: string; committee: string; meeting: string; period_start: string | null; period_end: string | null; released_at: string | null; has_pdf: boolean; has_xlsx: boolean };

type BoardHome = {
  as_of: string;
  organisation: string;
  quarter_ends: string[];
  has_snapshots: boolean;
  health_score: number | null;
  health_band: string;
  appetite: { risks: number; within: number; elevated: number; breach: number; appetite: number; tolerance: number; categories: Category[]; trend: AppetitePoint[] };
  top_risks: TopRisk[];
  assurance: Headline;
  compliance: Headline;
  frameworks: { name: string; assured_pct: number | null; gaps: number }[];
  kris_red: number;
  kris_amber: number;
  kris_in_breach: Kri[];
  issues_past_due: number;
  issues: Issue[];
  governance_enabled: boolean;
  my_committees: string[];
  decisions_overdue: number;
  decisions_due: number;
  decisions: Decision[];
  meetings: Meeting[];
  packs: Pack[];
};

const GREEN = "#16a34a";
const AMBER = "#d97706";
const RED = "#dc2626";
const GAP = "#e5e7eb";

const pct = (v: number | null) => (v === null || v === undefined ? "—" : `${Math.round(v)}%`);

/** Stacked bars (within / elevated / above tolerance) per point; a point with no snapshot is an empty outline. */
function AppetiteBars({ points, label, height = 44 }: { points: AppetitePoint[]; label: string; height?: number }) {
  const max = Math.max(1, ...points.map((p) => (p.within ?? 0) + (p.elevated ?? 0) + (p.breach ?? 0)));
  const w = 16;
  const gap = 8;
  return (
    <svg width={points.length * (w + gap)} height={height} role="img" aria-label={label}>
      {points.map((p, i) => {
        const x = i * (w + gap);
        if (p.within === null && p.elevated === null && p.breach === null) {
          return <rect key={i} x={x + 0.5} y={0.5} width={w - 1} height={height - 1} fill="none" stroke={GAP} strokeDasharray="2 2"><title>{`${p.date}: no snapshot`}</title></rect>;
        }
        let y = height;
        return (
          <g key={i}>
            <title>{`${p.date}: ${p.breach ?? 0} above tolerance, ${p.elevated ?? 0} elevated, ${p.within ?? 0} within`}</title>
            {([["within", GREEN], ["elevated", AMBER], ["breach", RED]] as const).map(([k, c]) => {
              const h = ((p[k] ?? 0) / max) * height;
              y -= h;
              return h > 0 ? <rect key={k} x={x} y={y} width={w} height={h} fill={c} /> : null;
            })}
          </g>
        );
      })}
    </svg>
  );
}

function Sparkline({ values, label, colour = RED }: { values: (number | null)[]; label: string; colour?: string }) {
  const pts = values.map((v, i) => [i, v] as const).filter((p): p is readonly [number, number] => p[1] !== null);
  if (pts.length < 2) return <span className="muted" style={{ fontSize: 12 }}>Not enough readings</span>;
  const W = 120;
  const H = 32;
  const vals = pts.map((p) => p[1]);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const n = values.length - 1 || 1;
  const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${((i / n) * (W - 4) + 2).toFixed(1)},${(H - 3 - ((v - lo) / span) * (H - 6)).toFixed(1)}`).join(" ");
  return (
    <svg width={W} height={H} role="img" aria-label={label}>
      <path d={d} fill="none" stroke={colour} strokeWidth={1.8} />
    </svg>
  );
}

function Movement({ risk }: { risk: TopRisk }) {
  const arrow = risk.movement === "up" ? "▲" : risk.movement === "down" ? "▼" : risk.movement === "new" ? "●" : risk.movement === "same" ? "=" : "";
  const colour = risk.movement === "up" ? RED : risk.movement === "down" ? GREEN : "var(--muted)";
  return (
    <span style={{ color: colour, fontSize: 12.5, whiteSpace: "nowrap" }}>
      {arrow && <span aria-hidden style={{ marginRight: 4 }}>{arrow}</span>}
      {risk.movement_text || "—"}
    </span>
  );
}

const PACK_STATE: Record<string, { text: string; tone: "neutral" | "info" | "low" | "medium" }> = {
  none: { text: "No pack yet", tone: "neutral" },
  draft: { text: "Pack in draft", tone: "medium" },
  reviewed: { text: "Pack reviewed", tone: "info" },
  released: { text: "Pack released", tone: "low" },
};

export default function BoardHomePage() {
  const { formatDate } = useFormat();
  const [data, setData] = useState<BoardHome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    apiCall<BoardHome>("GET", "/board/home")
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the board home"));
  }, []);

  useEffect(() => {
    load();
    setHighlight(new URLSearchParams(window.location.search).get("pack"));
  }, [load]);

  useEffect(() => {
    if (!data || !highlight) return;
    document.getElementById(`pack-${highlight}`)?.scrollIntoView({ block: "center" });
  }, [data, highlight]);

  const qLabels = useMemo(() => (data ? [...data.quarter_ends.map((d) => formatDate(d)), "Today"] : []), [data, formatDate]);

  async function download(p: Pack, kind: "pdf" | "xlsx") {
    try {
      await downloadBlob(`/board-packs/${p.id}/${kind}`, `${p.title}.${kind}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Download failed", "error");
    }
  }

  if (error) return <div className="error">{error}</div>;
  if (!data) return <div className="muted">Loading the board home…</div>;

  const a = data.appetite;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Board</h1>
          <p>
            {data.organisation}&apos;s position as at {formatDate(data.as_of)}: appetite, the risks that matter most,
            whether controls work, compliance, indicators in breach and the board&apos;s own decisions.
            {data.my_committees.length > 0 && <> You sit on {data.my_committees.join(", ")}.</>}
          </p>
        </div>
      </div>

      <div className="grid stat-grid">
        <div className={`card stat${a.breach ? " danger" : ""}`}><div className="stat-top"><span className="n">{a.breach}</span></div><span className="l">Risks above tolerance, of {a.risks}</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{pct(data.assurance.value)}</span></div><span className="l">Controls working</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{pct(data.compliance.value)}</span></div><span className="l">Clauses assured</span></div>
        <div className={`card stat${data.kris_red ? " danger" : ""}`}><div className="stat-top"><span className="n">{data.kris_red}</span></div><span className="l">Indicators in breach</span></div>
      </div>

      {!data.has_snapshots && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-pad muted" style={{ fontSize: 13 }}>
            No period snapshots are recorded yet, so the trends show today only. A snapshot is taken at each month end.
          </div>
        </div>
      )}

      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="h-appetite">
        <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
          <h3 id="h-appetite">Risk appetite</h3>
          <span className="sub" style={{ flexBasis: "100%" }}>
            Each category against its own appetite and tolerance. Bars show the last four quarter ends and today:{" "}
            <span style={{ color: GREEN }}>within</span>, <span style={{ color: AMBER }}>elevated</span>,{" "}
            <span style={{ color: RED }}>above tolerance</span>; a dashed outline means no snapshot for that date.
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Category</th><th>Appetite / tolerance</th><th>Risks</th><th>Above tolerance</th><th>Elevated</th><th>Trend ({qLabels[0]} to today)</th></tr>
            </thead>
            <tbody>
              {(a.categories.length ? a.categories : [{ key: "all", label: "All risks (organisation appetite)", appetite: a.appetite, tolerance: a.tolerance, risks: a.risks, within: a.within, elevated: a.elevated, breach: a.breach, trend: a.trend }]).map((c) => (
                <tr key={c.key}>
                  <td className="cell-title">{c.label}</td>
                  <td className="muted">{c.appetite} / {c.tolerance}</td>
                  <td>{c.risks}</td>
                  <td style={{ color: c.breach ? RED : undefined, fontWeight: c.breach ? 650 : undefined }}>{c.breach}</td>
                  <td>{c.elevated}</td>
                  <td><AppetiteBars points={c.trend} label={`${c.label}: appetite position over the last four quarters`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="h-top">
        <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
          <h3 id="h-top">Top risks</h3>
          <span className="sub" style={{ flexBasis: "100%" }}>Highest current exposure, and how each moved since the quarter began.</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Risk</th><th>Score</th><th>Appetite</th><th>Owner</th><th>Since the quarter began</th></tr></thead>
            <tbody>
              {data.top_risks.length === 0 && <tr><td colSpan={5} className="muted">No risks on the board register.</td></tr>}
              {data.top_risks.map((r) => (
                <tr key={r.id}>
                  <td><div className="cell-title">{r.title}</div><div className="muted" style={{ fontSize: 12 }}>{r.reference}</div></td>
                  <td>{r.score ?? "—"} {r.severity && <Badge tone={(r.severity as "low") || "neutral"}>{r.severity}</Badge>}</td>
                  <td>{r.appetite_status === "breach" ? <Badge tone="critical">Above tolerance</Badge> : r.appetite_status === "elevated" ? <Badge tone="medium">Elevated</Badge> : r.appetite_status ? <Badge tone="low">Within</Badge> : "—"}</td>
                  <td className="muted">{r.owner || "Unassigned"}</td>
                  <td><Movement risk={r} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 16, marginBottom: 16 }}>
        {([["Control assurance", data.assurance], ["Compliance", data.compliance]] as const).map(([title, h]) => (
          <section key={title} className="card" aria-label={title}>
            <div className="card-head"><h3>{title}</h3></div>
            <div className="card-pad">
              <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
                <span style={{ fontSize: 28, fontWeight: 750 }}>{pct(h.value)}</span>
                <Sparkline values={h.trend.map((t) => t.value)} label={`${title} over the last four quarters`} colour="var(--primary)" />
              </div>
              <p className="muted" style={{ fontSize: 13, margin: "6px 0 0" }}>{h.detail}</p>
              {title === "Compliance" && data.frameworks.length > 0 && (
                <ul style={{ margin: "10px 0 0", paddingLeft: 18, fontSize: 13 }}>
                  {data.frameworks.map((f) => <li key={f.name}>{f.name}: {pct(f.assured_pct)} assured, {f.gaps} gap{f.gaps === 1 ? "" : "s"}</li>)}
                </ul>
              )}
            </div>
          </section>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16, marginBottom: 16 }}>
        <section className="card" aria-labelledby="h-kri">
          <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
            <h3 id="h-kri">Indicators in breach</h3>
            <Badge tone={data.kris_red ? "critical" : "neutral"}>{`${data.kris_red} red`}</Badge>
            {data.kris_amber > 0 && <Badge tone="medium">{`${data.kris_amber} amber`}</Badge>}
          </div>
          <div className="card-pad" style={{ paddingTop: 4 }}>
            {data.kris_in_breach.length === 0 && <p className="muted" style={{ fontSize: 13 }}>No key risk indicator is in breach.</p>}
            {data.kris_in_breach.map((k) => (
              <div key={k.id} className="activity-item" style={{ alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>{k.name}</div>
                  <div className="when">{[k.reference, `now ${k.value ?? "—"}${k.unit ? ` ${k.unit}` : ""}`, k.threshold_text].filter(Boolean).join(" · ")}</div>
                </div>
                <Sparkline values={k.readings.map((r) => r.value)} label={`${k.name}: recent readings`} />
              </div>
            ))}
          </div>
        </section>

        <section className="card" aria-labelledby="h-issues">
          <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
            <h3 id="h-issues">High issues past due</h3>
            <Badge tone={data.issues_past_due ? "critical" : "neutral"}>{String(data.issues_past_due)}</Badge>
            <span className="sub" style={{ flexBasis: "100%" }}>Open critical and high issues whose agreed date has passed.</span>
          </div>
          <div className="card-pad" style={{ paddingTop: 4 }}>
            {data.issues.length === 0 && <p className="muted" style={{ fontSize: 13 }}>None.</p>}
            {data.issues.map((i) => (
              <div key={i.id} className="activity-item" style={{ alignItems: "center" }}>
                <Badge tone={i.severity === "critical" ? "critical" : "high"}>{i.severity}</Badge>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }}>{i.title}</div>
                  <div className="when">{[i.reference, i.owner || "Unassigned", i.regulator_related ? "regulator-related" : ""].filter(Boolean).join(" · ")}</div>
                </div>
                <span style={{ color: RED, fontSize: 12.5, whiteSpace: "nowrap" }}>{i.days_overdue} day{i.days_overdue === 1 ? "" : "s"} late</span>
              </div>
            ))}
            {data.issues_past_due > data.issues.length && <div className="muted" style={{ fontSize: 12.5 }}>Showing {data.issues.length} of {data.issues_past_due}, longest overdue first.</div>}
          </div>
        </section>
      </div>

      {data.governance_enabled && (
        <>
          <section className="card" style={{ marginBottom: 16 }} aria-labelledby="h-decisions">
            <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
              <h3 id="h-decisions">Committee decisions and actions</h3>
              {data.decisions_overdue > 0 && <Badge tone="critical">{`${data.decisions_overdue} overdue`}</Badge>}
              <Badge tone="neutral">{`${data.decisions_due} due in 30 days`}</Badge>
              <span className="sub" style={{ flexBasis: "100%" }}>Open items overdue or due in the next 30 days. Yours come first.</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Decision or action</th><th>Committee</th><th>Owner</th><th>Due</th></tr></thead>
                <tbody>
                  {data.decisions.length === 0 && <tr><td colSpan={4} className="muted">Nothing is due.</td></tr>}
                  {data.decisions.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <div className="cell-title">{d.description}</div>
                        <div className="muted" style={{ fontSize: 12 }}>{d.reference} · {d.decision_type}{d.mine && <> · <strong>assigned to you</strong></>}</div>
                      </td>
                      <td className="muted">{d.committee}{d.meeting ? ` · ${d.meeting}` : ""}</td>
                      <td className="muted">{d.owner || (d.mine ? "You" : "—")}</td>
                      <td style={{ color: d.overdue ? RED : undefined, whiteSpace: "nowrap" }}>{formatDate(d.due_date)}{d.overdue ? " (overdue)" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(360px, 1fr))", gap: 16 }}>
            <section className="card" aria-labelledby="h-meetings">
              <div className="card-head"><h3 id="h-meetings">Upcoming meetings</h3></div>
              <div className="card-pad" style={{ paddingTop: 4 }}>
                {data.meetings.length === 0 && <p className="muted" style={{ fontSize: 13 }}>No meetings are scheduled.</p>}
                {data.meetings.map((m) => (
                  <div key={m.id} className="activity-item" style={{ alignItems: "center", flexWrap: "wrap" }}>
                    <div style={{ flex: 1, minWidth: 180 }}>
                      <div style={{ fontWeight: 600, fontSize: 13.5 }}>{m.title}{m.mine && <span className="muted" style={{ fontWeight: 500 }}> · your committee</span>}</div>
                      <div className="when">{m.committee} · {formatDate(m.meeting_date)}{m.days_away !== null ? ` · in ${m.days_away} day${m.days_away === 1 ? "" : "s"}` : ""}</div>
                    </div>
                    <Badge tone={PACK_STATE[m.pack_state]?.tone || "neutral"} asIs>{PACK_STATE[m.pack_state]?.text || m.pack_state}</Badge>
                  </div>
                ))}
              </div>
            </section>

            <section className="card" aria-labelledby="h-packs">
              <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
                <h3 id="h-packs">Board packs</h3>
                <span className="sub" style={{ flexBasis: "100%" }}>Released packs, as the committee received them.</span>
              </div>
              <div className="card-pad" style={{ paddingTop: 4 }}>
                {data.packs.length === 0 && <p className="muted" style={{ fontSize: 13 }}>No pack has been released yet.</p>}
                {data.packs.map((p) => (
                  <div key={p.id} id={`pack-${p.id}`} className="activity-item" style={{ alignItems: "center", flexWrap: "wrap", background: highlight === p.id ? "var(--primary-weak-2)" : undefined }}>
                    <div style={{ flex: 1, minWidth: 180 }}>
                      <div style={{ fontWeight: 600, fontSize: 13.5 }}>{p.title}</div>
                      <div className="when">
                        {[p.committee, p.period_start && p.period_end ? `${formatDate(p.period_start)} – ${formatDate(p.period_end)}` : "", p.released_at ? `released ${formatDate(p.released_at)}` : ""].filter(Boolean).join(" · ")}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      {p.has_pdf && <button type="button" className="btn secondary sm" onClick={() => download(p, "pdf")}>PDF</button>}
                      {p.has_xlsx && <button type="button" className="btn secondary sm" onClick={() => download(p, "xlsx")}>XLSX</button>}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </>
      )}
    </>
  );
}
