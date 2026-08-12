"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type MatrixBand, type RiskMatrix } from "@/lib/api";

/* The grid, its axis wording and its severity bands all come from the server, because
   the matrix is per-organisation configurable (3x3 to 6x6, ISO 27005 / 31000 / in-house
   scales). Nothing about the scale is hard-coded here — duplicating the thresholds in
   the client is how a heat map ends up disagreeing with the register it summarises. */

const BAND_COLOR: Record<string, string> = {
  critical: "#b42323",
  high: "#bd4408",
  medium: "#a96414",
  low: "#157f4a",
};

const BAND_ORDER = ["critical", "high", "medium", "low"] as const;

function bandFor(score: number, bands: MatrixBand[]): string {
  const hit = bands.find((b) => score >= b.min_score && score <= b.max_score);
  return hit ? hit.severity : "low";
}

export default function RiskHeatmap() {
  const [matrix, setMatrix] = useState<RiskMatrix | null>(null);
  const [mode, setMode] = useState<"inherent" | "residual">("residual");

  useEffect(() => {
    api.riskMatrix().then(setMatrix).catch(() => {});
  }, []);

  const size = matrix?.size ?? 5;
  const bands = useMemo(() => matrix?.bands ?? [], [matrix]);

  // Distribution by severity band for the active mode.
  const dist = useMemo(() => {
    const out: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const c of matrix?.cells ?? []) {
      const n = mode === "inherent" ? c.inherent_count : c.residual_count;
      if (n) out[bandFor(c.score, bands)] += n;
    }
    return out;
  }, [matrix, mode, bands]);

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
  const levelName = (axis: "likelihood" | "impact", level: number) => {
    const levels = axis === "likelihood" ? matrix.likelihood_levels : matrix.impact_levels;
    const found = levels.find((x) => x.level === level);
    return found?.label ? `${level} — ${found.label}` : String(level);
  };

  const impacts = Array.from({ length: size }, (_, n) => size - n); // high impact at the top
  const likelihoods = Array.from({ length: size }, (_, n) => n + 1);

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
              <div
                className="hm-grid"
                /* Overrides the stylesheet's fixed 5-column default for other scales. */
                style={{ gridTemplateColumns: `repeat(${size}, minmax(56px, 100px))` }}
              >
                {impacts.map((i) =>
                  likelihoods.map((l) => {
                    const n = count(l, i);
                    const c = cell(l, i);
                    const score = c?.score ?? l * i;
                    return (
                      <div
                        key={`${l}-${i}`}
                        className={`hm-cell${n ? " filled" : ""}`}
                        style={n ? { background: BAND_COLOR[bandFor(score, bands)] } : undefined}
                        title={
                          `Likelihood ${levelName("likelihood", l)}\n` +
                          `Impact ${levelName("impact", i)}\n` +
                          `Score ${score} (${bandFor(score, bands)})\n${refs(l, i)}`
                        }
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
            {BAND_ORDER.map((key) => {
              const band = bands.find((b) => b.severity === key);
              return (
                <div className="hm-band" key={key}>
                  <span className="sw" style={{ background: BAND_COLOR[key] }} />
                  <span className="nm">
                    {key[0].toUpperCase() + key.slice(1)}
                    {band ? ` (${band.min_score}–${band.max_score})` : ""}
                  </span>
                  <span className="ct">{dist[key]}</span>
                </div>
              );
            })}
            <div className="hm-note">
              <span>{matrix.total} risk{matrix.total !== 1 ? "s" : ""} plotted on a {size}×{size} matrix</span>
              <span>appetite {matrix.appetite_score} · tolerance {matrix.tolerance_score}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
