"use client";

import { useEffect, useState } from "react";
import { api, type RiskMatrix } from "@/lib/api";

/** Standard 5x5 risk heatmap. Cell color follows likelihood×impact score bands;
 *  the count shown toggles between inherent and residual exposure. */
export default function RiskHeatmap() {
  const [matrix, setMatrix] = useState<RiskMatrix | null>(null);
  const [mode, setMode] = useState<"inherent" | "residual">("residual");

  useEffect(() => {
    api.riskMatrix().then(setMatrix).catch(() => {});
  }, []);

  if (!matrix) return null;

  const cell = (l: number, i: number) =>
    matrix.cells.find((c) => c.likelihood === l && c.impact === i);
  const count = (l: number, i: number) => {
    const c = cell(l, i);
    return c ? (mode === "inherent" ? c.inherent_count : c.residual_count) : 0;
  };
  const refs = (l: number, i: number) => {
    const c = cell(l, i);
    const list = c ? (mode === "inherent" ? c.inherent_refs : c.residual_refs) : [];
    return list.length ? list.join(", ") : "No risks";
  };

  // Score-band background (score = likelihood*impact, 1..25).
  const band = (score: number) => {
    if (score >= 15) return "#ba1c1c"; // critical
    if (score >= 10) return "#c03f0c"; // high
    if (score >= 5) return "#b7791f"; // medium
    return "#166434"; // low
  };

  const impacts = [5, 4, 3, 2, 1]; // rows top→bottom (high impact at top)
  const likelihoods = [1, 2, 3, 4, 5]; // columns left→right

  return (
    <div className="card">
      <div className="card-head">
        <h3>Risk heatmap</h3>
        <div style={{ display: "inline-flex", gap: 6 }}>
          <button
            className={`btn sm ${mode === "inherent" ? "" : "secondary"}`}
            onClick={() => setMode("inherent")}
          >
            Inherent
          </button>
          <button
            className={`btn sm ${mode === "residual" ? "" : "secondary"}`}
            onClick={() => setMode("residual")}
          >
            Residual
          </button>
        </div>
      </div>
      <div className="card-pad">
        <div style={{ display: "flex", gap: 8 }}>
          {/* Y axis label */}
          <div style={{ display: "flex", alignItems: "center", writingMode: "vertical-rl", transform: "rotate(180deg)", fontSize: 11, fontWeight: 600, color: "var(--muted)" }}>
            Impact →
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: "grid", gridTemplateColumns: `repeat(5, 1fr)`, gap: 4 }}>
              {impacts.map((i) =>
                likelihoods.map((l) => {
                  const n = count(l, i);
                  const c = cell(l, i);
                  return (
                    <div
                      key={`${l}-${i}`}
                      title={`Likelihood ${l} × Impact ${i} (score ${c?.score ?? l * i})\n${refs(l, i)}`}
                      style={{
                        aspectRatio: "1.6 / 1",
                        borderRadius: 6,
                        background: n ? band(l * i) : "var(--surface-2, #f3f4f6)",
                        color: n ? "#fff" : "var(--muted)",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        justifyContent: "center",
                        fontWeight: 700,
                        fontSize: 16,
                        border: "1px solid var(--border)",
                        cursor: n ? "default" : "default",
                        opacity: n ? 1 : 0.55,
                      }}
                    >
                      {n || ""}
                    </div>
                  );
                })
              )}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 11, fontWeight: 600, color: "var(--muted)" }}>
              <span>Likelihood →</span>
              <span>
                {matrix.total} risk{matrix.total !== 1 ? "s" : ""} · appetite {matrix.appetite_score} / tolerance {matrix.tolerance_score}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
