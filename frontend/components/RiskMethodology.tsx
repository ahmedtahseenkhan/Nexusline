"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type MatrixLevel,
  type ResidualPolicy,
  type RiskAppetite,
  type RiskMatrixConfig,
  type SeverityBands,
} from "@/lib/api";
import { Badge } from "@/components/badges";
import { useFormat } from "@/lib/format";
import { confirmDialog, toast } from "@/lib/feedback";
import { lookupValues, type LookupValue } from "@/lib/masterData";

/* Two things a bank baselines its register on:

   1. **The scale.** ISO 27005 and ISO 31000 do not mandate 5x5, and an organisation's
      existing methodology usually already defines its own likelihood and impact rungs.
      Writing those definitions down is what makes scoring repeatable between assessors —
      "3 = Possible: once in 1-3 years" rather than a bare number.
   2. **How much credit a control earns** toward the suggested residual. The engine only
      ever proposes; these weights decide what it proposes. */

/* 3 is the floor at which four severity bands still separate; 10 is the ceiling because
   a bank arriving with a board-approved 1-10 ERM matrix must be able to say so rather
   than re-score its whole register onto ours. Mirrors MAX_MATRIX_SIZE on the server. */
const SIZES = [3, 4, 5, 6, 7, 8, 9, 10];

/* Heat-map colours, the same as RiskHeatmap's, so the editor previews the real thing. */
const BAND_COLOR: Record<string, string> = {
  critical: "#b42323",
  high: "#bd4408",
  medium: "#a96414",
  low: "#157f4a",
};
/* A click on a cell walks: its score's band (no override) → low → medium → high →
   critical → back to no override. */
const CYCLE = ["low", "medium", "high", "critical"] as const;

const EFFECTIVENESS_ROWS: { key: keyof ResidualPolicy; label: string; hint: string }[] = [
  { key: "weight_effective", label: "Effective", hint: "Tested and working as intended" },
  { key: "weight_partially_effective", label: "Partially effective", hint: "Working with gaps" },
  { key: "weight_ineffective", label: "Ineffective", hint: "Normally earns nothing" },
  { key: "weight_not_assessed", label: "Not assessed", hint: "No evidence yet — normally earns nothing" },
];

export default function RiskMethodology({ onSaved }: { onSaved?: () => void }) {
  const { currency } = useFormat();
  const [config, setConfig] = useState<RiskMatrixConfig | null>(null);
  const [policy, setPolicy] = useState<ResidualPolicy | null>(null);
  const [size, setSize] = useState(5);
  const [likelihood, setLikelihood] = useState<MatrixLevel[]>([]);
  const [impact, setImpact] = useState<MatrixLevel[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Phase 2: configured band thresholds, cell-by-cell bands and how impact dimensions combine.
  const [customBands, setCustomBands] = useState(false);
  const [bands, setBands] = useState<SeverityBands>({ low_max: 4, medium_max: 9, high_max: 14 });
  const [cells, setCells] = useState<Record<string, string>>({});
  const [impactMode, setImpactMode] = useState<"max" | "average">("max");
  // Appetite per top-level risk category.
  const [appetites, setAppetites] = useState<RiskAppetite[]>([]);
  const [topCategories, setTopCategories] = useState<LookupValue[]>([]);
  const [draftAppetite, setDraftAppetite] = useState({ category_id: "", appetite_score: 4, tolerance_score: 8, statement: "" });

  const adopt = useCallback((c: RiskMatrixConfig) => {
    setConfig(c);
    setSize(c.size);
    setLikelihood(c.likelihood_levels);
    setImpact(c.impact_levels);
    setCustomBands(Boolean(c.severity_bands));
    const derived = (sev: string) => c.bands.find((b) => b.severity === sev)?.max_score ?? 1;
    setBands(c.severity_bands ?? { low_max: derived("low"), medium_max: derived("medium"), high_max: derived("high") });
    setCells(c.matrix_cells ?? {});
    setImpactMode(c.impact_mode ?? "max");
  }, []);

  const loadAppetites = useCallback(() => {
    api.riskAppetites().then(setAppetites).catch(() => {});
    lookupValues("risk_category").then((rows) => setTopCategories(rows.filter((r) => !r.parent_id))).catch(() => {});
  }, []);

  const load = useCallback(() => {
    api
      .riskMatrixConfig()
      .then(adopt)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the matrix"));
    api.residualPolicy().then(setPolicy).catch(() => {});
    loadAppetites();
  }, [adopt, loadAppetites]);

  useEffect(load, [load]);

  /** Grow/shrink the edited rungs to match a newly chosen size, keeping what was typed. */
  function resize(next: number) {
    setSize(next);
    const fit = (rows: MatrixLevel[]) =>
      Array.from({ length: next }, (_, i) =>
        rows[i] ?? { level: i + 1, label: "", definition: "" },
      ).map((row, i) => ({ ...row, level: i + 1 }));
    setLikelihood(fit);
    setImpact(fit);
  }

  function editLevel(
    axis: "likelihood" | "impact",
    level: number,
    patch: Partial<MatrixLevel>,
  ) {
    const apply = (rows: MatrixLevel[]) =>
      rows.map((r) => (r.level === level ? { ...r, ...patch } : r));
    if (axis === "likelihood") setLikelihood(apply); else setImpact(apply);
  }

  async function saveMatrix(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const resized = config != null && size !== config.size;
      const saved = await api.updateRiskMatrixConfig({
        size,
        likelihood_levels: likelihood,
        impact_levels: impact,
        severity_bands: customBands ? bands : null,
        // Cell overrides were drawn on the old grid; on a resize the server keeps the
        // ones that still fit.
        ...(resized ? {} : { matrix_cells: cells }),
        impact_mode: impactMode,
      });
      adopt(saved);
      setNote(`Matrix saved — scores now run 1 to ${saved.max_score}.`);
      onSaved?.();
    } catch (err) {
      // A shrink that would orphan already-scored risks comes back as a 409 naming them.
      setError(err instanceof Error ? err.message : "Could not save the matrix");
    } finally {
      setBusy(false);
    }
  }

  async function savePolicy(e: React.FormEvent) {
    e.preventDefault();
    if (!policy) return;
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      setPolicy(await api.updateResidualPolicy(policy));
      setNote("Residual policy saved. Suggestions use it from the next time you open a risk.");
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the policy");
    } finally {
      setBusy(false);
    }
  }

  /** A cell's band as it would be saved: its override, else its score's band. */
  const scoreBand = useMemo(() => {
    const ranges = customBands
      ? [
          { severity: "low", min: 1, max: bands.low_max },
          { severity: "medium", min: bands.low_max + 1, max: bands.medium_max },
          { severity: "high", min: bands.medium_max + 1, max: bands.high_max },
          { severity: "critical", min: bands.high_max + 1, max: Number.MAX_SAFE_INTEGER },
        ]
      : (config?.bands ?? []).map((b) => ({ severity: b.severity, min: b.min_score, max: b.max_score }));
    return (score: number) => ranges.find((r) => score >= r.min && score <= r.max)?.severity ?? "critical";
  }, [customBands, bands, config]);

  function cycleCell(l: number, i: number) {
    const key = `${l},${i}`;
    setCells((prev) => {
      const next = { ...prev };
      const current = prev[key];
      const at = current ? CYCLE.indexOf(current as (typeof CYCLE)[number]) : -1;
      if (at === CYCLE.length - 1) delete next[key];
      else next[key] = CYCLE[at + 1];
      return next;
    });
  }

  async function addAppetite() {
    if (!draftAppetite.category_id) {
      setError("Choose a top-level risk category for the appetite.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.createRiskAppetite(draftAppetite);
      setDraftAppetite({ category_id: "", appetite_score: draftAppetite.appetite_score, tolerance_score: draftAppetite.tolerance_score, statement: "" });
      toast("Category appetite saved");
      loadAppetites();
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the appetite");
    } finally {
      setBusy(false);
    }
  }

  async function saveAppetite(row: RiskAppetite) {
    setBusy(true);
    setError(null);
    try {
      await api.updateRiskAppetite(row.id, {
        appetite_score: row.appetite_score, tolerance_score: row.tolerance_score, statement: row.statement,
      });
      toast(`Appetite for ${row.category_ref?.label ?? "the category"} saved`);
      loadAppetites();
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the appetite");
    } finally {
      setBusy(false);
    }
  }

  async function removeAppetite(row: RiskAppetite) {
    const label = row.category_ref?.label ?? "this category";
    const ok = await confirmDialog({
      title: `Remove the appetite for ${label}?`,
      message: "Its risks will be measured against the organisation's appetite and tolerance again.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteRiskAppetite(row.id);
      loadAppetites();
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the appetite");
    }
  }

  const editAppetite = (id: string, patch: Partial<RiskAppetite>) =>
    setAppetites((rows) => rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  if (!config) {
    return <div className="muted" style={{ fontSize: 12.5 }}>{error ?? "Loading methodology…"}</div>;
  }

  const unusedCategories = topCategories.filter((c) => !appetites.some((a) => a.category_id === c.id));
  const maxScore = size * size;
  const gridSize = config.size;

  const levelRows = (axis: "likelihood" | "impact") => {
    const rows = axis === "likelihood" ? likelihood : impact;
    return rows.map((row) => (
      <tr key={`${axis}-${row.level}`}>
        <td className="ref" style={{ width: 40 }}>{row.level}</td>
        <td>
          <input
            className="input" style={{ padding: "4px 8px", fontSize: 13 }}
            value={row.label}
            placeholder={axis === "likelihood" ? "e.g. Possible" : "e.g. Major"}
            onChange={(e) => editLevel(axis, row.level, { label: e.target.value })}
          />
        </td>
        <td>
          <input
            className="input" style={{ padding: "4px 8px", fontSize: 13 }}
            value={row.definition}
            placeholder={
              axis === "likelihood"
                ? "e.g. Could occur once in 1–3 years"
                : `e.g. ${currency} 50–200m loss, or regulatory censure`
            }
            onChange={(e) => editLevel(axis, row.level, { definition: e.target.value })}
          />
        </td>
      </tr>
    ));
  };

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {error && <div className="error" style={{ fontSize: 13 }}>{error}</div>}
      {note && <div className="muted" style={{ fontSize: 12.5 }}>{note}</div>}

      {/* ---------------------------------------------------------- the scale */}
      <form onSubmit={saveMatrix}>
        <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ width: 180 }}>
            <label className="label">Matrix size</label>
            <select className="input" value={size} onChange={(e) => resize(Number(e.target.value))}>
              {SIZES.map((n) => <option key={n} value={n}>{n} × {n}</option>)}
            </select>
          </div>
          <div style={{ width: 210 }}>
            <label className="label">Impact from dimensions</label>
            <select className="input" value={impactMode} onChange={(e) => setImpactMode(e.target.value as "max" | "average")}>
              <option value="max">Highest dimension</option>
              <option value="average">Average (rounded up)</option>
            </select>
          </div>
          <div className="muted" style={{ fontSize: 12.5, paddingBottom: 8 }}>
            Scores run 1–{maxScore}. Bands now:{" "}
            {config.bands.map((b) => `${b.severity} ${b.min_score}–${b.max_score}`).join(" · ")}
          </div>
          <button className="btn" disabled={busy} style={{ marginLeft: "auto" }}>
            {busy ? "Saving…" : "Save scale"}
          </button>
        </div>

        {size < config.size && (
          <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
            Shrinking the matrix is refused while any risk still scores above {size} — those
            assessments have to be re-scored deliberately rather than silently clamped.
          </div>
        )}

        {/* ------------------------------------------------ band thresholds */}
        <div style={{ marginTop: 14, padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8 }}>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, fontWeight: 600 }}>
            <input type="checkbox" checked={customBands} onChange={(e) => setCustomBands(e.target.checked)} />
            Set our own band thresholds
          </label>
          <p className="muted" style={{ fontSize: 12, margin: "6px 0 8px" }}>
            Off: the bands scale with the matrix size. On: your methodology&apos;s numbers — each is the
            highest score in that band; anything above &quot;high up to&quot; is critical.
          </p>
          {customBands && (
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {([["low_max", "Low up to"], ["medium_max", "Medium up to"], ["high_max", "High up to"]] as const).map(([key, label]) => (
                <div key={key} style={{ width: 130 }}>
                  <label className="label">{label}</label>
                  <input
                    className="input" type="number" min={1} max={maxScore - 1} value={bands[key]}
                    onChange={(e) => setBands({ ...bands, [key]: Number(e.target.value) })}
                  />
                </div>
              ))}
              <div className="muted" style={{ fontSize: 12.5, alignSelf: "flex-end", paddingBottom: 8 }}>
                Critical: {bands.high_max + 1}–{maxScore}
              </div>
            </div>
          )}
        </div>

        {/* ------------------------------------------------ cell-by-cell bands */}
        <div style={{ marginTop: 14 }}>
          <div className="bt" style={{ marginBottom: 4 }}>Matrix cells</div>
          <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
            Click a cell to set its band — for a matrix that is not symmetric, e.g. rare but
            catastrophic rated high. Cells marked • override their score&apos;s band; a click past
            critical returns the cell to its score&apos;s band. The heat map and severity labels use these.
          </p>
          {size !== gridSize ? (
            <div className="muted" style={{ fontSize: 12.5 }}>Save the new size first, then edit its cells.</div>
          ) : (
            <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
              <div className="muted" style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", fontSize: 11.5, textAlign: "center" }}>Impact →</div>
              <div>
                <div style={{ display: "grid", gridTemplateColumns: `repeat(${gridSize}, 44px)`, gap: 4 }}>
                  {Array.from({ length: gridSize }, (_, n) => gridSize - n).map((i) =>
                    Array.from({ length: gridSize }, (_, n) => n + 1).map((l) => {
                      const key = `${l},${i}`;
                      const band = cells[key] ?? scoreBand(l * i);
                      return (
                        <button
                          key={key}
                          type="button"
                          onClick={() => cycleCell(l, i)}
                          title={`Likelihood ${l} × impact ${i} = ${l * i} · ${band}${cells[key] ? " (set by hand)" : ""}`}
                          aria-label={`Likelihood ${l}, impact ${i}: ${band}${cells[key] ? ", set by hand" : ""}`}
                          style={{
                            height: 36, borderRadius: 6, border: cells[key] ? "2px solid var(--text)" : "1px solid transparent",
                            background: BAND_COLOR[band], color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer",
                          }}
                        >
                          {l * i}{cells[key] ? " •" : ""}
                        </button>
                      );
                    }),
                  )}
                </div>
                <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>Likelihood →</div>
              </div>
              {Object.keys(cells).length > 0 && (
                <button type="button" className="btn secondary sm" style={{ alignSelf: "flex-start" }} onClick={() => setCells({})}>
                  Clear overrides
                </button>
              )}
            </div>
          )}
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 14 }}>
          {(["likelihood", "impact"] as const).map((axis) => (
            <div key={axis}>
              <div className="bt" style={{ marginBottom: 6, textTransform: "capitalize" }}>{axis} scale</div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 40 }}>#</th>
                      <th style={{ width: "32%" }}>Label</th>
                      <th>Definition</th>
                    </tr>
                  </thead>
                  <tbody>{levelRows(axis)}</tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </form>

      {/* ------------------------------------------ appetite per category */}
      <div style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
        <strong style={{ fontSize: 13 }}>Appetite per risk category</strong>
        <p className="muted" style={{ fontSize: 12, lineHeight: 1.6, margin: "6px 0 10px" }}>
          A top-level risk category can carry its own appetite and tolerance — usually lower for
          compliance and conduct than for strategic risk. Its sub-categories use it too; every
          other category uses the organisation&apos;s appetite ({config.appetite_score}) and
          tolerance ({config.tolerance_score}). The register flags, dashboard and alerts compare
          each risk against its own category&apos;s numbers.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: "24%" }}>Category</th>
                <th style={{ width: 90 }}>Appetite</th>
                <th style={{ width: 90 }}>Tolerance</th>
                <th>Statement</th>
                <th style={{ width: 90 }}>Risks</th>
                <th style={{ width: 130 }} />
              </tr>
            </thead>
            <tbody>
              {appetites.map((row) => (
                <tr key={row.id}>
                  <td className="cell-title">{row.category_ref?.label ?? "—"}</td>
                  <td>
                    <input className="input" type="number" min={1} max={config.max_score} style={{ width: 70, padding: "4px 8px", fontSize: 13 }}
                      value={row.appetite_score} onChange={(e) => editAppetite(row.id, { appetite_score: Number(e.target.value) })} />
                  </td>
                  <td>
                    <input className="input" type="number" min={1} max={config.max_score} style={{ width: 70, padding: "4px 8px", fontSize: 13 }}
                      value={row.tolerance_score} onChange={(e) => editAppetite(row.id, { tolerance_score: Number(e.target.value) })} />
                  </td>
                  <td>
                    <input className="input" style={{ padding: "4px 8px", fontSize: 13 }} value={row.statement}
                      placeholder="e.g. No appetite for regulatory breaches"
                      onChange={(e) => editAppetite(row.id, { statement: e.target.value })} />
                  </td>
                  <td className="muted">
                    {row.risks}
                    {row.breaches ? <> · <span style={{ color: "var(--red)", fontWeight: 600 }}>{row.breaches} over</span></> : null}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <button type="button" className="btn secondary sm" disabled={busy} onClick={() => saveAppetite(row)}>Save</button>{" "}
                    <button type="button" className="btn secondary sm" disabled={busy} onClick={() => removeAppetite(row)}>Remove</button>
                  </td>
                </tr>
              ))}
              <tr>
                <td>
                  <select className="input" style={{ padding: "4px 8px", fontSize: 13 }} value={draftAppetite.category_id}
                    onChange={(e) => setDraftAppetite({ ...draftAppetite, category_id: e.target.value })}>
                    <option value="">{unusedCategories.length ? "Add a category…" : "Every category has one"}</option>
                    {unusedCategories.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                  </select>
                </td>
                <td>
                  <input className="input" type="number" min={1} max={config.max_score} style={{ width: 70, padding: "4px 8px", fontSize: 13 }}
                    value={draftAppetite.appetite_score} onChange={(e) => setDraftAppetite({ ...draftAppetite, appetite_score: Number(e.target.value) })} />
                </td>
                <td>
                  <input className="input" type="number" min={1} max={config.max_score} style={{ width: 70, padding: "4px 8px", fontSize: 13 }}
                    value={draftAppetite.tolerance_score} onChange={(e) => setDraftAppetite({ ...draftAppetite, tolerance_score: Number(e.target.value) })} />
                </td>
                <td>
                  <input className="input" style={{ padding: "4px 8px", fontSize: 13 }} value={draftAppetite.statement}
                    placeholder="Appetite statement (optional)"
                    onChange={(e) => setDraftAppetite({ ...draftAppetite, statement: e.target.value })} />
                </td>
                <td />
                <td>
                  <button type="button" className="btn sm" disabled={busy || !draftAppetite.category_id} onClick={addAppetite}>Add</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* ------------------------------------------------- the residual policy */}
      {policy && (
        <form onSubmit={savePolicy} style={{ borderTop: "1px solid var(--border)", paddingTop: 14 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: 13 }}>Residual suggestion</strong>
            <Badge tone={policy.enabled ? "low" : "neutral"}>{policy.enabled ? "On" : "Off"}</Badge>
            <span className="muted" style={{ fontSize: 12.5 }}>
              How many points a control earns toward a lower residual score.
            </span>
          </div>

          <p className="muted" style={{ fontSize: 12, lineHeight: 1.6, margin: "8px 0 12px" }}>
            The system never writes a residual on its own — it proposes one and the risk owner
            accepts it or records a different judgement with a reason. Controls whose audit has
            failed, is overdue, or has an open finding earn nothing regardless of their rating.
          </p>

          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-end" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
              <input
                type="checkbox" checked={policy.enabled}
                onChange={(e) => setPolicy({ ...policy, enabled: e.target.checked })}
              />
              Suggest a residual
            </label>
            <div style={{ width: 190 }}>
              <label className="label">Credit reduces</label>
              <select
                className="input" value={policy.applies_to}
                onChange={(e) => setPolicy({ ...policy, applies_to: e.target.value as ResidualPolicy["applies_to"] })}
              >
                <option value="likelihood">Likelihood only</option>
                <option value="impact">Impact only</option>
                <option value="both">Both (split)</option>
              </select>
            </div>
            <div style={{ width: 170 }}>
              <label className="label">Maximum reduction</label>
              <input
                className="input" type="number" min={0} max={5} value={policy.max_reduction}
                onChange={(e) => setPolicy({ ...policy, max_reduction: Number(e.target.value) })}
              />
            </div>
            <button className="btn" disabled={busy} style={{ marginLeft: "auto" }}>
              {busy ? "Saving…" : "Save policy"}
            </button>
          </div>

          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: "26%" }}>Control effectiveness</th>
                  <th style={{ width: 120 }}>Points earned</th>
                  <th>Meaning</th>
                </tr>
              </thead>
              <tbody>
                {EFFECTIVENESS_ROWS.map((row) => (
                  <tr key={row.key}>
                    <td className="cell-title">{row.label}</td>
                    <td>
                      <input
                        className="input" type="number" min={0} max={5}
                        style={{ width: 70, padding: "4px 8px", fontSize: 13 }}
                        value={policy[row.key] as number}
                        onChange={(e) => setPolicy({ ...policy, [row.key]: Number(e.target.value) })}
                      />
                    </td>
                    <td className="muted">{row.hint}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            Default: an effective control earns 2 points and a partially effective one earns 1,
            reducing likelihood only, capped at 3 — controls change how often something happens
            more than how badly it hurts. Adjust to match your own methodology.
          </p>
        </form>
      )}
    </div>
  );
}
