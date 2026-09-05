"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import {
  api,
  type GenerateRisksResponse,
  type GeneratedRiskCommitItem,
  type RiskProposal,
} from "@/lib/api";
import { Badge } from "@/components/badges";

/* Turns the asset register into a starting risk register the ISO 27005 way — a threat
   exploiting a vulnerability against an asset. The scenario library supplies the pairs;
   the asset's own criticality supplies the opening impact.

   Two rules shape this screen:
   · Nothing is written until Create is pressed. Everything before that is a proposal.
   · Proposals arrive unticked-friendly but fully editable, because a generated register
     nobody reviewed is worse than no register at all. */

type Props = {
  /** Restrict generation to one asset class; omit to run across the whole inventory. */
  assetClass?: "information_asset" | "it_asset";
  /** Pre-selected assets (e.g. the rows ticked on the asset table). */
  assetIds?: string[];
  label: string;
  onDone?: () => void;
};

const CRITICALITY = ["low", "medium", "high", "critical"] as const;

export type GenerateRisksHandle = { open: () => void };

const GenerateRisks = forwardRef<GenerateRisksHandle, Props & { hideButton?: boolean }>(function GenerateRisks(
  { assetClass, assetIds, label, onDone, hideButton }, ref,
) {
  const [open, setOpen] = useState(false);
  useImperativeHandle(ref, () => ({ open: () => setOpen(true) }));

  return (
    <>
      {!hideButton && (
      <button
        className="btn secondary"
        onClick={() => setOpen(true)}
        title={`Propose risks for ${label} from the scenario library`}
      >
        Generate risks
      </button>
      )}
      {open && (
        <GenerateModal
          assetClass={assetClass}
          assetIds={assetIds}
          label={label}
          onClose={() => setOpen(false)}
          onDone={onDone}
        />
      )}
    </>
  );
});

export default GenerateRisks;

function GenerateModal({
  assetClass,
  assetIds,
  label,
  onClose,
  onDone,
}: Props & { onClose: () => void }) {
  const [minCriticality, setMinCriticality] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [result, setResult] = useState<GenerateRisksResponse | null>(null);
  const [rows, setRows] = useState<(RiskProposal & { include: boolean })[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [committed, setCommitted] = useState<{ created: number; refs: string[] } | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const generate = useCallback(async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await api.generateRisks({
        asset_ids: assetIds && assetIds.length ? assetIds : undefined,
        asset_class: assetClass,
        min_criticality: minCriticality || undefined,
        category: category || undefined,
      });
      setResult(res);
      setRows(res.proposals.map((p) => ({ ...p, include: true })));
    } catch (e) {
      const message = e instanceof Error ? e.message : "Could not generate proposals";
      setError(message);
      setResult(null);
      setRows([]);
    } finally {
      setBusy(false);
    }
  }, [assetIds, assetClass, minCriticality, category]);

  useEffect(() => {
    generate();
    // Re-runs only when the filters change; the user drives it with the Refresh button.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function installLibrary() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.installScenarioLibrary();
      setNote(
        `Installed ${res.installed} scenario${res.installed !== 1 ? "s" : ""}` +
          (res.skipped ? ` (${res.skipped} already present, left as they were)` : "") +
          ". Threats and vulnerabilities were added to the library too.",
      );
      await generate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not install the library");
    } finally {
      setBusy(false);
    }
  }

  function edit(index: number, patch: Partial<RiskProposal & { include: boolean }>) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  const selected = useMemo(() => rows.filter((r) => r.include), [rows]);

  async function commit() {
    setBusy(true);
    setError(null);
    try {
      const items: GeneratedRiskCommitItem[] = selected.map((r) => ({
        asset_id: r.asset_id,
        title: r.title,
        description: r.description,
        category: r.category,
        inherent_likelihood: r.inherent_likelihood,
        inherent_impact: r.inherent_impact,
        threat: r.threat,
        vulnerability: r.vulnerability,
        treatment_description: r.treatment_description,
        control_ids: r.control_ids,
      }));
      const res = await api.commitGeneratedRisks(items);
      setCommitted({ created: res.created, refs: res.references });
      if (res.errors.length) {
        setError(
          `${res.errors.length} could not be created: ` +
            res.errors.slice(0, 3).map((x) => `${x.title} — ${x.message}`).join("; "),
        );
      }
      if (res.created > 0) onDone?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the risks");
    } finally {
      setBusy(false);
    }
  }

  const needsLibrary = !!error && error.toLowerCase().includes("no scenarios in the library");

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-label={`Generate risks for ${label}`}>
        <div className="modal-head">
          <h2>Generate risks from {label}</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          {committed ? (
            <div className="card card-pad">
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <Badge tone="low">Created {committed.created}</Badge>
                <span className="muted" style={{ fontSize: 13 }}>
                  {committed.refs.slice(0, 12).join(", ")}
                  {committed.refs.length > 12 ? ` … +${committed.refs.length - 12} more` : ""}
                </span>
              </div>
              <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6, marginBottom: 0 }}>
                These are ordinary risks — they carry references, asset/threat/vulnerability links
                and an audit-log entry exactly as hand-made ones do. Each already has its asset&apos;s
                existing controls attached, so the suggested residual has something to work with.
                Open the register to review and assign owners.
              </p>
              {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}
            </div>
          ) : (
            <>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, marginTop: 0 }}>
                Every asset is paired with the scenarios that apply to it, and the opening impact is
                derived from that asset&apos;s own criticality and CIA rating. <b>Nothing is saved
                until you press Create</b> — untick what does not apply and adjust any score first.
              </p>

              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 14 }}>
                <div style={{ width: 200 }}>
                  <label className="label">Only assets rated at least</label>
                  <select className="input" value={minCriticality} onChange={(e) => setMinCriticality(e.target.value)}>
                    <option value="">Any criticality</option>
                    {CRITICALITY.map((c) => (
                      <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>
                    ))}
                  </select>
                </div>
                <div style={{ width: 220 }}>
                  <label className="label">Scenario category</label>
                  <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
                    <option value="">All categories</option>
                    {[...new Set(rows.map((r) => r.category))].sort().map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
                <button className="btn secondary" type="button" onClick={generate} disabled={busy}>
                  {busy ? "Working…" : "Refresh proposals"}
                </button>
              </div>

              {note && <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>{note}</div>}
              {error && (
                <div className="error" style={{ marginBottom: 12 }}>
                  {error}
                  {needsLibrary && (
                    <div style={{ marginTop: 8 }}>
                      <button className="btn sm" type="button" onClick={installLibrary} disabled={busy}>
                        Install the built-in library
                      </button>
                    </div>
                  )}
                </div>
              )}

              {result && (
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 10 }}>
                  <Badge tone="info">{result.assets_considered} assets</Badge>
                  <Badge tone="info">{result.scenarios_considered} scenarios</Badge>
                  <Badge tone={selected.length ? "low" : "neutral"}>{selected.length} selected</Badge>
                  {result.duplicates_skipped > 0 && (
                    <span className="muted" style={{ fontSize: 12.5 }}>
                      {result.duplicates_skipped} already in the register — skipped
                    </span>
                  )}
                  {result.truncated && (
                    <Badge tone="medium">Capped — narrow the filter and run again for the rest</Badge>
                  )}
                </div>
              )}

              {rows.length > 0 && (
                <div className="table-wrap" style={{ maxHeight: 430, overflowY: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th style={{ width: 34 }}>
                          <input
                            type="checkbox"
                            checked={rows.every((r) => r.include)}
                            onChange={(e) => setRows((prev) => prev.map((r) => ({ ...r, include: e.target.checked })))}
                            aria-label="Select all"
                          />
                        </th>
                        <th>Proposed risk</th>
                        <th style={{ width: 130 }}>Asset</th>
                        <th style={{ width: 66 }}>L</th>
                        <th style={{ width: 66 }}>I</th>
                        <th style={{ width: 60 }}>Score</th>
                        <th style={{ width: 150 }}>Threat</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((row, index) => (
                        <tr key={`${row.scenario_id}-${row.asset_id}`}>
                          <td>
                            <input
                              type="checkbox"
                              checked={row.include}
                              onChange={(e) => edit(index, { include: e.target.checked })}
                              aria-label={`Include ${row.title}`}
                            />
                          </td>
                          <td>
                            <input
                              className="input"
                              style={{ padding: "4px 8px", fontSize: 13 }}
                              value={row.title}
                              onChange={(e) => edit(index, { title: e.target.value })}
                            />
                            <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
                              {row.scenario_reference} · {row.category}
                              {row.control_labels.length > 0 && ` · controls: ${row.control_labels.slice(0, 3).join(", ")}`}
                            </div>
                          </td>
                          <td className="muted" style={{ fontSize: 12.5 }}>{row.asset_name}</td>
                          <td>
                            <input
                              className="input" type="number" min={1} max={6}
                              style={{ width: 54, padding: "4px 6px", fontSize: 13 }}
                              value={row.inherent_likelihood}
                              onChange={(e) => edit(index, { inherent_likelihood: Number(e.target.value) })}
                            />
                          </td>
                          <td>
                            <input
                              className="input" type="number" min={1} max={6}
                              style={{ width: 54, padding: "4px 6px", fontSize: 13 }}
                              value={row.inherent_impact}
                              onChange={(e) => edit(index, { inherent_impact: Number(e.target.value) })}
                            />
                          </td>
                          <td className="ref">{row.inherent_likelihood * row.inherent_impact}</td>
                          <td className="muted" style={{ fontSize: 12 }}>{row.threat}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {result && rows.length === 0 && !error && (
                <div className="muted" style={{ fontSize: 13 }}>
                  Nothing new to propose — every applicable scenario is already in the register for
                  these assets.
                </div>
              )}
            </>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn secondary" type="button" onClick={onClose} disabled={busy}>
            {committed ? "Close" : "Cancel"}
          </button>
          {!committed && (
            <button
              className="btn"
              type="button"
              onClick={commit}
              disabled={busy || selected.length === 0}
              title={selected.length === 0 ? "Select at least one proposal" : undefined}
            >
              {busy ? "Creating…" : `Create ${selected.length} risk${selected.length !== 1 ? "s" : ""}`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
