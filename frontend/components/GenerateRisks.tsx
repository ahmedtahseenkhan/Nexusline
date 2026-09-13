"use client";

import Link from "next/link";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState, useRef } from "react";
import {
  api,
  type GenerateRisksCommitResult,
  type GenerateRisksResponse,
  type GeneratedRiskCommitItem,
  type RiskProposal,
} from "@/lib/api";
import { Badge } from "@/components/badges";
import { useFormat } from "@/lib/format";
import { trapTab, useDialogFocus, useEscapeLayer } from "@/lib/escapeLayer";

/* Turns the asset register into risk candidates the ISO 27005 way — a threat exploiting
   a vulnerability against an asset. The scenario library supplies the pairs; the asset's
   own criticality supplies the opening impact.

   Three rules shape this screen:
   · Nothing is written until Send is pressed. Everything before that is a proposal.
   · Nothing goes straight into the register: proposals become candidates in the risk
     candidate queue (Risk Management → Risk candidates), where a person accepts, merges
     or rejects them. A generated register nobody reviewed is worse than none.
   · Pairs are grouped the way the queue groups them — one candidate per scenario,
     process and business unit — so forty servers running Payments are one risk with
     forty assets, not forty risks. */

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

/** One candidate-to-be: every pair sharing a de-duplication key. */
type Group = {
  key: string;
  pairs: RiskProposal[];
  include: boolean;
  /** Editable unless the pairs join a candidate already in the queue. */
  title: string;
  likelihood: number;
  impact: number;
  controls: string[];
  unmapped: string[];
};

/** The most exposed pair: highest score, then impact — how the queue scores a candidate. */
function worst(pairs: RiskProposal[]): [number, number] {
  let best = pairs[0];
  for (const p of pairs) {
    const a = [p.inherent_score, p.inherent_impact, p.inherent_likelihood];
    const b = [best.inherent_score, best.inherent_impact, best.inherent_likelihood];
    if (a[0] > b[0] || (a[0] === b[0] && (a[1] > b[1] || (a[1] === b[1] && a[2] > b[2])))) best = p;
  }
  return [best.inherent_likelihood, best.inherent_impact];
}

const unique = (items: string[]) => Array.from(new Set(items.filter(Boolean)));

function toGroups(proposals: RiskProposal[]): Group[] {
  const byKey = new Map<string, RiskProposal[]>();
  for (const p of proposals) {
    const key = p.dedupe_key || `${p.scenario_reference}|${p.asset_id}`;
    byKey.set(key, [...(byKey.get(key) ?? []), p]);
  }
  const groups: Group[] = [];
  byKey.forEach((pairs, key) => {
    const first = pairs[0];
    const [likelihood, impact] = worst(pairs);
    groups.push({
      key,
      pairs,
      // A key rejected before stays unticked; the reason is shown on the row.
      include: !first.rejected_note,
      title: first.queued_title || (pairs.length === 1 ? first.title : first.group_title || first.title),
      likelihood,
      impact,
      controls: unique(pairs.flatMap((p) => p.control_labels)),
      unmapped: unique(pairs.flatMap((p) => p.unmapped_references)),
    });
  });
  return groups.sort((a, b) => b.likelihood * b.impact - a.likelihood * a.impact || a.title.localeCompare(b.title));
}

function GenerateModal({
  assetClass,
  assetIds,
  label,
  onClose,
  onDone,
}: Props & { onClose: () => void }) {
  const { formatDate } = useFormat();
  const [minCriticality, setMinCriticality] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [result, setResult] = useState<GenerateRisksResponse | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [sent, setSent] = useState<GenerateRisksCommitResult | null>(null);

  // Esc: a layer of the shared escape stack (the asset record it was opened from stays open).
  useEscapeLayer(true, onClose);
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(true, dialogRef);

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
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
      setGroups(toGroups(res.proposals));
    } catch (e) {
      const message = e instanceof Error ? e.message : "Could not generate proposals";
      setError(message);
      setResult(null);
      setGroups([]);
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

  function edit(index: number, patch: Partial<Group>) {
    setGroups((prev) => prev.map((g, i) => (i === index ? { ...g, ...patch } : g)));
  }

  const selected = useMemo(() => groups.filter((g) => g.include), [groups]);
  const selectedPairs = selected.reduce((n, g) => n + g.pairs.length, 0);
  const categories = useMemo(
    () => unique(groups.flatMap((g) => g.pairs.map((p) => p.category))).sort(),
    [groups],
  );

  async function send() {
    setBusy(true);
    setError(null);
    try {
      // One item per asset × scenario pair; the group's title and scores go with each,
      // so the queue keeps what was reviewed here.
      const items: GeneratedRiskCommitItem[] = selected.flatMap((g) =>
        g.pairs.map((p) => ({
          asset_id: p.asset_id,
          scenario_id: p.scenario_id,
          scenario_reference: p.scenario_reference,
          title: g.title.trim() || p.title,
          description: p.description,
          category: p.category,
          inherent_likelihood: g.likelihood,
          inherent_impact: g.impact,
          threat: p.threat,
          vulnerability: p.vulnerability,
          treatment_description: p.treatment_description,
          control_ids: p.control_ids,
        })),
      );
      const res = await api.commitGeneratedRisks(items);
      setSent(res);
      if (res.errors.length) {
        setError(
          `${res.errors.length} could not be queued: ` +
            res.errors.slice(0, 3).map((x) => `${x.title} — ${x.message}`).join("; "),
        );
      }
      if (res.created > 0 || res.merged > 0) onDone?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the proposals to the queue");
    } finally {
      setBusy(false);
    }
  }

  const needsLibrary = !!error && error.toLowerCase().includes("no scenarios in the library");
  const allTicked = groups.length > 0 && groups.every((g) => g.include);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialogRef} tabIndex={-1} className="modal wide" role="dialog" aria-modal="true" aria-label={`Generate risks for ${label}`} onKeyDown={(e) => trapTab(e, dialogRef.current)}>
        <div className="modal-head">
          <h2>Generate risks from {label}</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          {sent ? (
            <div className="card card-pad">
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <Badge tone="low">{sent.created} new candidate{sent.created !== 1 ? "s" : ""}</Badge>
                {sent.merged > 0 && (
                  <Badge tone="info">
                    {sent.merged} merged into a candidate
                    {sent.merged_into_existing ? ` (${sent.merged_into_existing} into ones already waiting)` : ""}
                  </Badge>
                )}
                {sent.skipped > 0 && <Badge tone="neutral">{sent.skipped} already in the register</Badge>}
              </div>
              <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                Nothing was added to the register. The candidates wait in the queue until someone
                accepts, merges or rejects them; accepted ones become draft risks with their assets,
                controls, threat and vulnerability linked.
              </p>
              {sent.skipped_items.length > 0 && (
                <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                  Already covered:{" "}
                  {sent.skipped_items.slice(0, 5).map((s) => `${s.title}${s.risk_reference ? ` (${s.risk_reference})` : ""}`).join("; ")}
                  {sent.skipped_items.length > 5 ? ` … +${sent.skipped_items.length - 5} more` : ""}
                </div>
              )}
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {sent.created > 0 && (
                  <Link className="btn sm" href={`/risk-proposals?run_id=${sent.run_id}`} onClick={onClose}>
                    Review this run&apos;s candidates
                  </Link>
                )}
                <Link className="btn secondary sm" href="/risk-proposals" onClick={onClose}>
                  Open the risk candidates queue
                </Link>
              </div>
              {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}
            </div>
          ) : (
            <>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, marginTop: 0 }}>
                Every asset is paired with the scenarios that apply to it, and the opening impact is
                derived from that asset&apos;s own criticality and CIA rating. Pairs are grouped into one
                candidate per scenario, process and business unit, scored at the most exposed asset.
                <b> Nothing is saved until you send them to the queue</b>, and nothing reaches the
                register until someone accepts it there.
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
                    {categories.map((c) => (
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
                  <Badge tone="info">{result.proposals.length} asset × scenario pairs</Badge>
                  <Badge tone={selected.length ? "low" : "neutral"}>
                    {selected.length} of {groups.length} candidates selected
                  </Badge>
                  {result.queued > 0 && (
                    <span className="muted" style={{ fontSize: 12.5 }}>
                      {result.queued} pair{result.queued !== 1 ? "s" : ""} join candidates already in the queue
                    </span>
                  )}
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

              {groups.length > 0 && (
                <div className="table-wrap" style={{ maxHeight: 430, overflowY: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th style={{ width: 34 }}>
                          <input
                            type="checkbox"
                            checked={allTicked}
                            onChange={(e) => setGroups((prev) => prev.map((g) => ({ ...g, include: e.target.checked })))}
                            aria-label="Select all candidates"
                          />
                        </th>
                        <th>Candidate</th>
                        <th style={{ width: 200 }}>Assets</th>
                        <th style={{ width: 66 }}>L</th>
                        <th style={{ width: 66 }}>I</th>
                        <th style={{ width: 60 }}>Score</th>
                      </tr>
                    </thead>
                    <tbody>
                      {groups.map((group, index) => {
                        const first = group.pairs[0];
                        const joins = !!first.queued_proposal_id;
                        return (
                          <tr key={group.key}>
                            <td style={{ verticalAlign: "top" }}>
                              <input
                                type="checkbox"
                                checked={group.include}
                                onChange={(e) => edit(index, { include: e.target.checked })}
                                aria-label={`Include ${group.title}`}
                              />
                            </td>
                            <td>
                              {joins ? (
                                <div style={{ fontSize: 13, fontWeight: 600 }} title="The candidate already in the queue keeps its title">
                                  {group.title}
                                </div>
                              ) : (
                                <input
                                  className="input"
                                  style={{ padding: "4px 8px", fontSize: 13 }}
                                  value={group.title}
                                  onChange={(e) => edit(index, { title: e.target.value })}
                                  aria-label="Candidate title"
                                />
                              )}
                              <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
                                {first.scenario_reference} · {first.category} · {first.scope_label || "No process or unit"} · {first.threat}
                                {group.controls.length > 0 && (
                                  <> · controls: {group.controls.slice(0, 4).join(", ")}{group.controls.length > 4 ? ` +${group.controls.length - 4}` : ""}</>
                                )}
                              </div>
                              {joins && (
                                <div style={{ fontSize: 11.5, marginTop: 2 }}>
                                  <Badge tone="info">Joins a candidate already in the queue</Badge>
                                </div>
                              )}
                              {first.rejected_note && (
                                <div style={{ fontSize: 11.5, marginTop: 2, color: "var(--amber)" }}>
                                  Rejected{first.rejected_at ? ` on ${formatDate(first.rejected_at)}` : ""}: {first.rejected_note} — tick it to send it again
                                </div>
                              )}
                              {group.unmapped.length > 0 && (
                                /* The scenario names controls this catalogue lacks — the
                                   framework is not installed, or the reference differs.
                                   Said out loud rather than dropped, so the gap is visible. */
                                <div style={{ fontSize: 11.5, marginTop: 2, color: "var(--amber)" }} title="Install the framework from the Framework Library to link these">
                                  not in your catalogue: {group.unmapped.slice(0, 5).join(", ")}{group.unmapped.length > 5 ? ` +${group.unmapped.length - 5}` : ""}
                                </div>
                              )}
                            </td>
                            <td>
                              <div className="chips">
                                {group.pairs.slice(0, 6).map((p) => (
                                  <span key={p.asset_id} className="chip" title={p.title}>{p.asset_name}</span>
                                ))}
                                {group.pairs.length > 6 && <span className="chip">+{group.pairs.length - 6}</span>}
                              </div>
                            </td>
                            <td>
                              <input
                                className="input" type="number" min={1} max={10}
                                style={{ width: 54, padding: "4px 6px", fontSize: 13 }}
                                value={group.likelihood}
                                onChange={(e) => edit(index, { likelihood: Number(e.target.value) })}
                                aria-label="Likelihood"
                              />
                            </td>
                            <td>
                              <input
                                className="input" type="number" min={1} max={10}
                                style={{ width: 54, padding: "4px 6px", fontSize: 13 }}
                                value={group.impact}
                                onChange={(e) => edit(index, { impact: Number(e.target.value) })}
                                aria-label="Impact"
                              />
                            </td>
                            <td className="ref">{group.likelihood * group.impact}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {result && groups.length === 0 && !error && (
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
            {sent ? "Close" : "Cancel"}
          </button>
          {!sent && (
            <button
              className="btn"
              type="button"
              onClick={send}
              disabled={busy || selected.length === 0}
              title={selected.length === 0 ? "Select at least one candidate" : `${selectedPairs} asset × scenario pairs`}
            >
              {busy ? "Sending…" : `Send ${selected.length} proposal${selected.length !== 1 ? "s" : ""} to the queue`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
