"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type MatrixLevel, type ResidualPolicy, type RiskMatrixConfig } from "@/lib/api";
import { Badge } from "@/components/badges";

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

const EFFECTIVENESS_ROWS: { key: keyof ResidualPolicy; label: string; hint: string }[] = [
  { key: "weight_effective", label: "Effective", hint: "Tested and working as intended" },
  { key: "weight_partially_effective", label: "Partially effective", hint: "Working with gaps" },
  { key: "weight_ineffective", label: "Ineffective", hint: "Normally earns nothing" },
  { key: "weight_not_assessed", label: "Not assessed", hint: "No evidence yet — normally earns nothing" },
];

export default function RiskMethodology({ onSaved }: { onSaved?: () => void }) {
  const [config, setConfig] = useState<RiskMatrixConfig | null>(null);
  const [policy, setPolicy] = useState<ResidualPolicy | null>(null);
  const [size, setSize] = useState(5);
  const [likelihood, setLikelihood] = useState<MatrixLevel[]>([]);
  const [impact, setImpact] = useState<MatrixLevel[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .riskMatrixConfig()
      .then((c) => {
        setConfig(c);
        setSize(c.size);
        setLikelihood(c.likelihood_levels);
        setImpact(c.impact_levels);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the matrix"));
    api.residualPolicy().then(setPolicy).catch(() => {});
  }, []);

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
      const saved = await api.updateRiskMatrixConfig({
        size,
        likelihood_levels: likelihood,
        impact_levels: impact,
      });
      setConfig(saved);
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

  if (!config) {
    return <div className="muted" style={{ fontSize: 12.5 }}>{error ?? "Loading methodology…"}</div>;
  }

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
                : "e.g. PKR 50–200m loss, or regulatory censure"
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
          <div className="muted" style={{ fontSize: 12.5, paddingBottom: 8 }}>
            Scores run 1–{size * size}. Severity bands scale with the matrix:{" "}
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
