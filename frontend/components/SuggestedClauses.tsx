"use client";

import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { toast } from "@/lib/feedback";
import { trapTab, useDialogFocus, useEscapeLayer } from "@/lib/escapeLayer";
import {
  acceptSuggestedRequirements,
  bulkAcceptSuggestions,
  bulkSuggestRequirements,
  getPendingSuggestions,
  getSuggestedRequirements,
  reviewSuggestionsPage,
  STRONG_SUGGESTION,
  type ControlSuggestions,
  type PendingSuggestions,
  type RequirementSuggestion,
  type SuggestionReviewPage,
  type SuggestionScope,
} from "@/lib/compliance";
import { Badge } from "@/components/badges";

/** Strong / likely / possible — the score as a word, so nobody reads 0.62 as 62 %. */
function Strength({ score }: { score: number }) {
  if (score >= STRONG_SUGGESTION) return <Badge tone="low">Strong</Badge>;
  if (score >= 0.5) return <Badge tone="info">Likely</Badge>;
  return <Badge tone="neutral" plain>Possible</Badge>;
}

function Reasons({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return null;
  return (
    <div className="muted" style={{ fontSize: 11.5, marginTop: 2, lineHeight: 1.45 }}>
      {reasons.slice(0, 3).join(" · ")}
      {reasons.length > 3 ? ` · +${reasons.length - 3} more` : ""}
    </div>
  );
}

/* ================================================================ drawer panel */
type Props = {
  controlId: string;
  /** Called after links are written, so the page can reload the control. */
  onAccepted?: () => void;
};

/** "Suggested clauses" for one control: ranked clauses from the installed compliance
 *  frameworks, with the reasons each was suggested. Nothing is linked until the user
 *  ticks and accepts. */
export default function SuggestedClauses({ controlId, onAccepted }: Props) {
  const [items, setItems] = useState<RequirementSuggestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setError(null);
    getSuggestedRequirements(controlId)
      .then((rows) => {
        setItems(rows);
        // Pre-tick the strong ones; the rest are there to consider.
        setPicked(new Set(rows.filter((r) => r.score >= STRONG_SUGGESTION).map((r) => r.requirement_id)));
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load suggestions"));
  }, [controlId]);

  useEffect(() => {
    setItems(null);
    load();
  }, [load]);

  function flip(id: string) {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function accept() {
    if (!picked.size) return;
    setSaving(true);
    try {
      const res = await acceptSuggestedRequirements(controlId, [...picked]);
      toast(res.linked ? `Linked ${res.linked} requirement${res.linked === 1 ? "" : "s"} to this control.` : "Those requirements were already linked.");
      onAccepted?.();
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not link the requirements", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-head">
        <h3>Suggested clauses</h3>
        <span className="sub">From your installed compliance frameworks</span>
      </div>
      <div className="card-pad">
        {error ? (
          <div className="error">{error}</div>
        ) : items === null ? (
          <span className="muted">Finding clauses…</span>
        ) : items.length === 0 ? (
          <span className="muted" style={{ fontSize: 12.5 }}>
            No further clauses match this control&apos;s name and description. Install a framework from the
            Framework Library, or link requirements by hand under Edit → Links &amp; Relations.
          </span>
        ) : (
          <>
            <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
              {items.map((s) => (
                <label key={s.requirement_id} style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={picked.has(s.requirement_id)}
                    onChange={() => flip(s.requirement_id)}
                    style={{ marginTop: 3 }}
                    aria-label={`Link ${s.reference} ${s.title}`}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
                      <span className="ref">{s.reference}</span>
                      <span>{s.title}</span>
                      <Strength score={s.score} />
                    </div>
                    <div className="muted" style={{ fontSize: 11.5 }}>{s.framework}</div>
                    <Reasons reasons={s.reasons} />
                  </div>
                </label>
              ))}
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <button className="btn sm" type="button" disabled={!picked.size || saving} onClick={accept}>
                {saving ? "Linking…" : `Accept selected (${picked.size})`}
              </button>
              <button
                className="btn secondary sm"
                type="button"
                disabled={saving}
                onClick={() => setPicked(picked.size === items.length ? new Set() : new Set(items.map((s) => s.requirement_id)))}
              >
                {picked.size === items.length ? "Clear" : "Select all"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ============================================================ bulk review modal */
type BulkProps = {
  /** Review these controls (the register's selected rows)… */
  controlIds?: string[];
  /** …or every control in scope, a page at a time ("Review all suggestions"). */
  scope?: SuggestionScope;
  /** With `scope`: only this framework's clauses, and "unmapped" means none of its clauses. */
  frameworkId?: string | null;
  frameworkName?: string;
  onClose: () => void;
  /** Called after links are written. */
  onDone?: () => void;
};

/** How many controls one bulk request scores, and how many links one accept writes. */
const SUGGEST_CHUNK = 500;
const ACCEPT_CHUNK = 500;
/** Controls rendered before "Show more" — a register of thousands stays responsive. */
const GROUPS_SHOWN = 100;

const pairKey = (controlId: string, requirementId: string) => `${controlId}:${requirementId}`;
const nf = (n: number) => n.toLocaleString("en-US");

/** Review suggested clause mappings for many controls: the register's selected rows
 *  ("Suggest mappings") or the whole register ("Review all suggestions"), loaded in
 *  pages. Strong matches are pre-ticked; nothing is linked until Accept, which writes in
 *  chunks with progress. */
export function BulkSuggestMappings({ controlIds, scope: initialScope, frameworkId = null, frameworkName, onClose, onDone }: BulkProps) {
  const registerWide = !controlIds;
  const [scope, setScope] = useState<SuggestionScope>(initialScope ?? "unmapped");
  const [minScore, setMinScore] = useState(0.5);
  const [groups, setGroups] = useState<ControlSuggestions[]>([]);
  const [loading, setLoading] = useState(true);
  /** Controls scored so far / in scope. */
  const [progress, setProgress] = useState<{ done: number; total: number }>({ done: 0, total: controlIds?.length ?? 0 });
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [fwFilter, setFwFilter] = useState<string>("");
  const [shown, setShown] = useState(GROUPS_SHOWN);
  const [saving, setSaving] = useState<{ done: number; total: number } | null>(null);
  const runRef = useRef(0);

  const idsKey = controlIds?.join(",") ?? "";

  useEffect(() => {
    const run = ++runRef.current;
    const live = () => run === runRef.current;
    setGroups([]);
    setPicked(new Set());
    setError(null);
    setShown(GROUPS_SHOWN);
    setLoading(true);
    const addPage = (page: ControlSuggestions[]) => {
      const withAny = page.filter((g) => g.suggestions.length > 0);
      setGroups((cur) => [...cur, ...withAny]);
      setPicked((cur) => {
        const next = new Set(cur);
        withAny.forEach((g) => g.suggestions.forEach((x) => x.score >= STRONG_SUGGESTION && next.add(pairKey(g.control_id, x.requirement_id))));
        return next;
      });
    };
    (async () => {
      try {
        if (controlIds) {
          setProgress({ done: 0, total: controlIds.length });
          for (let i = 0; i < controlIds.length; i += SUGGEST_CHUNK) {
            const chunk = controlIds.slice(i, i + SUGGEST_CHUNK);
            const res = await bulkSuggestRequirements(chunk, minScore, 5);
            if (!live()) return;
            addPage(res);
            setProgress({ done: Math.min(controlIds.length, i + chunk.length), total: controlIds.length });
          }
        } else {
          let offset: number | null = 0;
          while (offset !== null) {
            const page: SuggestionReviewPage = await reviewSuggestionsPage({ scope, frameworkId, offset, pageSize: 100, minScore, limit: 5 });
            if (!live()) return;
            addPage(page.groups);
            setProgress({ done: page.offset + page.scanned, total: page.total_controls });
            offset = page.next_offset;
          }
        }
      } catch (e) {
        if (live()) setError(e instanceof Error ? e.message : "Could not load suggestions");
      } finally {
        if (live()) setLoading(false);
      }
    })();
    return () => {
      runRef.current++;
    };
    // controlIds is compared by value (idsKey).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, scope, frameworkId, minScore]);

  // Esc: a layer of the shared escape stack; ignored while saving.
  useEscapeLayer(true, () => {
    if (!saving) onClose();
  });
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(true, dialogRef);

  /** Frameworks among the loaded suggestions, for the filter. */
  const frameworks = useMemo(() => {
    const m = new Map<string, { id: string; name: string; count: number; strong: number }>();
    groups.forEach((g) => g.suggestions.forEach((x) => {
      const id = x.framework_id ?? x.framework;
      const row = m.get(id) ?? { id, name: x.framework, count: 0, strong: 0 };
      row.count += 1;
      if (x.score >= STRONG_SUGGESTION) row.strong += 1;
      m.set(id, row);
    }));
    return [...m.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [groups]);

  /** The groups as filtered by framework (controls left with nothing are hidden). */
  const visible = useMemo(() => {
    if (!fwFilter) return groups;
    return groups
      .map((g) => ({ ...g, suggestions: g.suggestions.filter((x) => (x.framework_id ?? x.framework) === fwFilter) }))
      .filter((g) => g.suggestions.length > 0);
  }, [groups, fwFilter]);

  const visibleKeys = useMemo(() => visible.flatMap((g) => g.suggestions.map((x) => pairKey(g.control_id, x.requirement_id))), [visible]);
  const strongKeys = useMemo(
    () => visible.flatMap((g) => g.suggestions.filter((x) => x.score >= STRONG_SUGGESTION).map((x) => pairKey(g.control_id, x.requirement_id))),
    [visible],
  );
  const hiddenPicked = useMemo(() => {
    const vis = new Set(visibleKeys);
    return [...picked].filter((k) => !vis.has(k)).length;
  }, [picked, visibleKeys]);

  function flip(k: string) {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }
  function setMany(keys: string[], on: boolean) {
    setPicked((cur) => {
      const next = new Set(cur);
      keys.forEach((k) => (on ? next.add(k) : next.delete(k)));
      return next;
    });
  }

  async function accept() {
    // Only what is ticked and shown: a filter hides rows, it never links them unseen.
    const vis = new Set(visibleKeys);
    const pairs = [...picked].filter((k) => vis.has(k)).map((k) => {
      const [control_id, requirement_id] = k.split(":");
      return { control_id, requirement_id };
    });
    if (!pairs.length) return;
    setError(null);
    setSaving({ done: 0, total: pairs.length });
    let linked = 0;
    const controls = new Set<string>();
    try {
      for (let i = 0; i < pairs.length; i += ACCEPT_CHUNK) {
        const chunk = pairs.slice(i, i + ACCEPT_CHUNK);
        const res = await bulkAcceptSuggestions(chunk);
        linked += res.linked;
        chunk.forEach((p) => controls.add(p.control_id));
        setSaving({ done: Math.min(pairs.length, i + chunk.length), total: pairs.length });
      }
      toast(`Linked ${nf(linked)} requirement${linked === 1 ? "" : "s"} across ${nf(controls.size)} control${controls.size === 1 ? "" : "s"}.`);
      onDone?.();
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Could not link the requirements";
      setError(linked ? `${msg} ${nf(linked)} link${linked === 1 ? " was" : "s were"} written before the error; accept again to finish.` : msg);
      if (linked) onDone?.();
    } finally {
      setSaving(null);
    }
  }

  const acceptCount = picked.size - hiddenPicked;
  const suggestionTotal = visibleKeys.length;
  const title = registerWide
    ? `Review all suggestions${frameworkName ? ` for ${frameworkName}` : ""}`
    : `Suggest mappings for ${nf(controlIds!.length)} control${controlIds!.length === 1 ? "" : "s"}`;

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && !saving && onClose()}>
      <div ref={dialogRef} tabIndex={-1} className="modal wide" role="dialog" aria-modal="true" aria-label={title} onKeyDown={(e) => trapTab(e, dialogRef.current)}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="x" onClick={onClose} aria-label="Close" disabled={!!saving}>✕</button>
        </div>
        <div className="modal-body">
          <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
            Clauses from your installed compliance frameworks that each control probably meets, matched on its
            name, description and reference. <b>Nothing is linked until you accept.</b> Strong matches are
            pre-ticked. Mapping shows which controls cover a clause; it does not mark the clause compliant or
            tested.
          </p>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 10 }}>
            {registerWide && (
              <div>
                <span className="label" id="suggest-scope-label">Controls</span>
                <div className="seg" role="group" aria-labelledby="suggest-scope-label">
                  <button type="button" className={scope === "unmapped" ? "on" : ""} onClick={() => setScope("unmapped")} disabled={!!saving}>
                    {frameworkName ? `Not mapped to ${frameworkName}` : "With no clause mapped"}
                  </button>
                  <button type="button" className={scope === "all" ? "on" : ""} onClick={() => setScope("all")} disabled={!!saving}>
                    All controls
                  </button>
                </div>
              </div>
            )}
            <div style={{ width: 200 }}>
              <label className="label" htmlFor="suggest-min">Show matches that are at least</label>
              <select id="suggest-min" className="select" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} disabled={!!saving}>
                <option value={0.75}>Strong</option>
                <option value={0.5}>Likely</option>
                <option value={0.3}>Possible</option>
              </select>
            </div>
            {!frameworkId && frameworks.length > 1 && (
              <div style={{ width: 240 }}>
                <label className="label" htmlFor="suggest-fw">Framework</label>
                <select id="suggest-fw" className="select" value={fwFilter} onChange={(e) => { setFwFilter(e.target.value); setShown(GROUPS_SHOWN); }} disabled={!!saving}>
                  <option value="">All frameworks</option>
                  {frameworks.map((f) => (
                    <option key={f.id} value={f.id}>{f.name} ({nf(f.count)})</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
            <button type="button" className="btn secondary sm" disabled={!strongKeys.length || !!saving} onClick={() => setMany(strongKeys, true)}>
              Select all strong ({nf(strongKeys.length)})
            </button>
            <button type="button" className="btn secondary sm" disabled={!visibleKeys.length || !!saving} onClick={() => setMany(visibleKeys, true)}>
              Select all shown ({nf(visibleKeys.length)})
            </button>
            <button type="button" className="btn secondary sm" disabled={!picked.size || !!saving} onClick={() => setPicked(new Set())}>
              Clear
            </button>
            <span className="muted" style={{ fontSize: 12.5 }} aria-live="polite">
              {nf(suggestionTotal)} suggestion{suggestionTotal === 1 ? "" : "s"} for {nf(visible.length)} control{visible.length === 1 ? "" : "s"}
              {" · "}<b>{nf(acceptCount)} selected</b>
              {hiddenPicked > 0 ? ` (${nf(hiddenPicked)} more hidden by the framework filter, not accepted)` : ""}
            </span>
          </div>

          {(loading || progress.total > 0) && (
            <div style={{ marginBottom: 12 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                {loading
                  ? `Scanning controls… ${nf(progress.done)} of ${nf(progress.total)}`
                  : `Scanned ${nf(progress.total)} control${progress.total === 1 ? "" : "s"}.`}
              </div>
              {loading && progress.total > 0 && (
                <div className="progress"><span style={{ width: `${Math.round((100 * progress.done) / progress.total)}%` }} /></div>
              )}
            </div>
          )}

          {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}
          {!loading && visible.length === 0 && !error ? (
            <div className="empty" style={{ padding: 20 }}>
              <p>
                {registerWide && scope === "unmapped" && progress.total === 0
                  ? "Every control already has a clause mapped. Choose “All controls” to look for further clauses."
                  : "No clauses match at this strength. Try “Possible”, or install a framework from the Framework Library."}
              </p>
            </div>
          ) : visible.length > 0 ? (
            <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 34 }} />
                    <th>Suggested clause</th>
                    <th style={{ width: 90 }}>Match</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.slice(0, shown).map((g) => {
                    const keys = g.suggestions.map((x) => pairKey(g.control_id, x.requirement_id));
                    const on = keys.filter((k) => picked.has(k)).length;
                    return (
                      <GroupRows
                        key={g.control_id}
                        group={g}
                        on={on}
                        picked={picked}
                        disabled={!!saving}
                        onGroup={(value) => setMany(keys, value)}
                        onFlip={flip}
                      />
                    );
                  })}
                </tbody>
              </table>
              {visible.length > shown && (
                <div style={{ padding: 10, textAlign: "center" }}>
                  <button type="button" className="btn secondary sm" onClick={() => setShown((n) => n + GROUPS_SHOWN)}>
                    Show {nf(Math.min(GROUPS_SHOWN, visible.length - shown))} more controls ({nf(visible.length - shown)} not shown)
                  </button>
                </div>
              )}
            </div>
          ) : null}
        </div>
        <div className="modal-foot">
          <button className="btn secondary" type="button" onClick={onClose} disabled={!!saving}>Close</button>
          <button className="btn" type="button" onClick={accept} disabled={!acceptCount || !!saving}>
            {saving ? `Linking… ${nf(saving.done)} of ${nf(saving.total)}` : `Accept selected (${nf(acceptCount)})`}
          </button>
        </div>
      </div>
    </div>
  );
}

/** One control's header row (tick all of its clauses) and its suggestion rows. */
function GroupRows({ group: g, on, picked, disabled, onGroup, onFlip }: {
  group: ControlSuggestions;
  on: number;
  picked: Set<string>;
  disabled: boolean;
  onGroup: (on: boolean) => void;
  onFlip: (k: string) => void;
}) {
  const boxRef = useRef<HTMLInputElement>(null);
  const all = on === g.suggestions.length;
  useEffect(() => {
    if (boxRef.current) boxRef.current.indeterminate = on > 0 && !all;
  }, [on, all]);
  const label = `${g.reference ? `${g.reference} ` : ""}${g.name}`;
  return (
    <>
      <tr style={{ background: "var(--surface-2)" }}>
        <td>
          <input ref={boxRef} type="checkbox" checked={all} disabled={disabled} onChange={() => onGroup(!all)} aria-label={`Select every suggestion for ${label}`} />
        </td>
        <td colSpan={2}>
          <span className="cell-title">{g.name}</span>
          {g.reference && <span className="ref" style={{ marginLeft: 6 }}>{g.reference}</span>}
          <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
            {on} of {g.suggestions.length} selected
          </span>
        </td>
      </tr>
      {g.suggestions.map((x) => {
        const k = pairKey(g.control_id, x.requirement_id);
        return (
          <tr key={k}>
            <td>
              <input type="checkbox" checked={picked.has(k)} disabled={disabled} onChange={() => onFlip(k)} aria-label={`Link ${x.reference} to ${g.name}`} />
            </td>
            <td>
              <div style={{ fontSize: 13 }}><span className="ref">{x.reference}</span> {x.title}</div>
              <div className="muted" style={{ fontSize: 11.5 }}>{x.framework}</div>
              <Reasons reasons={x.reasons} />
            </td>
            <td><Strength score={x.score} /></td>
          </tr>
        );
      })}
    </>
  );
}

/* ============================================================ pending hint */
/** "12 controls with no clause mapped have strong clause suggestions waiting" — on the
 *  controls register and the compliance page, so a freshly installed catalogue does not
 *  sit unmapped with compliance at 0%. Renders nothing when nothing is waiting or the
 *  viewer can't read suggestions. */
export function PendingSuggestionsHint({ frameworkId, frameworkName, refreshKey, onReview }: {
  frameworkId?: string | null;
  frameworkName?: string;
  refreshKey?: number;
  onReview: () => void;
}) {
  const [pending, setPending] = useState<PendingSuggestions | null>(null);
  useEffect(() => {
    let live = true;
    setPending(null);
    getPendingSuggestions(frameworkId)
      .then((p) => live && setPending(p))
      .catch(() => live && setPending(null));
    return () => {
      live = false;
    };
  }, [frameworkId, refreshKey]);
  if (!pending || pending.controls_with_strong === 0) return null;
  const n = pending.controls_with_strong;
  const scopeText = frameworkName ? `mapped to no ${frameworkName} clause` : "with no clause mapped";
  return (
    <div
      role="status"
      style={{
        display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between", flexWrap: "wrap",
        background: "var(--primary-weak-2)", border: "1px solid var(--primary-weak)", borderRadius: "var(--radius-sm)",
        padding: "10px 14px", marginBottom: 14, fontSize: 13,
      }}
    >
      <span>
        <b>{nf(n)} control{n === 1 ? "" : "s"}</b> {scopeText} {n === 1 ? "has" : "have"} strong clause suggestions
        ({nf(pending.strong_suggestions)} in total){pending.capped ? `, from the first ${nf(pending.scanned)} of ${nf(pending.unmapped_controls)} unmapped controls` : ""}.
        <span className="muted"> Accepting them maps the controls; the clauses still need testing and assessment.</span>
      </span>
      <button type="button" className="btn sm" onClick={onReview}>Review suggestions</button>
    </div>
  );
}
