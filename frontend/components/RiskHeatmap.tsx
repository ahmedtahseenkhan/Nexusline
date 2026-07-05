"use client";

import { useEffect, useState } from "react";
import { api, type RiskMatrix } from "@/lib/api";

const BANDS = [
  { key: "critical", label: "Critical (15–25)", color: "#b42323" },
  { key: "high", label: "High (10–14)", color: "#bd4408" },
  { key: "medium", label: "Medium (5–9)", color: "#a96414" },
  { key: "low", label: "Low (1–4)", color: "#157f4a" },
] as const;

function bandColor(score: number): string {
  if (score >= 15) return "#b42323";
  if (score >= 10) return "#bd4408";
  if (score >= 5) return "#a96414";
  return "#157f4a";
}

/** 5×5 risk matrix with an inherent/residual toggle and a distribution legend. */
export default function RiskHeatmap() {
  const [matrix, setMatrix] = useState<RiskMatrix | null>(null);
  const [mode, setMode] = useState<"inherent" | "residual">("residual");

  useEffect(() => {
    api.riskMatrix().then(setMatrix).catch(() => {});
  }, []);

  if (!matrix) return null;

  const cell = (l: number, i: number) => matrix.cells.find((c) => c.likelihood === l && c.impact === i);
  const count = (l: number, i: number) => {
    const c = cell(l, i);
    return c ? (mode === "inherent" ? c.inherent_count : c.residual_count) : 0;
  };
  const refs = (l: number, i: number) => {
    const c = cell(l, i);
    const list = c ? (mode === "inherent" ? c.inherent_refs : c.residual_refs) : [];
    return list.length ? list.join(", ") : "No risks";
  };

  const impacts = [5, 4, 3, 2, 1];
  const likelihoods = [1, 2, 3, 4, 5];

  // Distribution by severity band for the active mode.
  const dist: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const c of matrix.cells) {
    const n = mode === "inherent" ? c.inherent_count : c.residual_count;
    if (!n) continue;
    if (c.score >= 15) dist.critical += n;
    else if (c.score >= 10) dist.high += n;
    else if (c.score >= 5) dist.medium += n;
    else dist.low += n;
  }

  return (
    <div className="card">
      <div className="card-head">
        <h3>Risk heatmap</h3>
        <div className="seg">
          <button className={mode === "inherent" ? "on" : ""} onClick={() => setMode("inherent")}>Inherent</button>
          <button className={mode === "residual" ? "on" : ""} onClick={() => setMode("residual")}>Residual</button>
        </div>
      </div>
      <div className="card-pad">
        <div className="hm">
          <div className="hm-matrix">
            <div className="hm-yaxis">Impact →</div>
            <div>
              <div className="hm-grid">
                {impacts.map((i) =>
                  likelihoods.map((l) => {
                    const n = count(l, i);
                    const c = cell(l, i);
                    return (
                      <div
                        key={`${l}-${i}`}
                        className={`hm-cell${n ? " filled" : ""}`}
                        style={n ? { background: bandColor(c?.score ?? l * i) } : undefined}
                        title={`Likelihood ${l} × Impact ${i} (score ${c?.score ?? l * i})\n${refs(l, i)}`}
                      >
                        {n || ""}
                      </div>
                    );
                  }),
                )}
              </div>
              <div className="hm-xaxis"><span>Likelihood →</span></div>
            </div>
          </div>
          <div className="hm-side">
            <div className="bt">{mode} distribution</div>
            {BANDS.map((b) => (
              <div className="hm-band" key={b.key}>
                <span className="sw" style={{ background: b.color }} />
                <span className="nm">{b.label}</span>
                <span className="ct">{dist[b.key]}</span>
              </div>
            ))}
            <div className="hm-note">
              <span>{matrix.total} risk{matrix.total !== 1 ? "s" : ""} plotted</span>
              <span>appetite {matrix.appetite_score} · tolerance {matrix.tolerance_score}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
