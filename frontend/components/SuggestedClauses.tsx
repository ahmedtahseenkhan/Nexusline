"use client";

import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import { toast } from "@/lib/feedback";
import { trapTab, useDialogFocus, useEscapeLayer } from "@/lib/escapeLayer";
import {
  acceptSuggestedRequirements,
  bulkAcceptSuggestions,
  bulkSuggestRequirements,
  getSuggestedRequirements,
  type ControlSuggestions,
  type RequirementSuggestion,
} from "@/lib/compliance";
import { Badge } from "@/components/badges";

/** Strong / likely / possible — the score as a word, so nobody reads 0.62 as 62 %. */
function Strength({ score }: { score: number }) {
  if (score >= 0.75) return <Badge tone="low">Strong</Badge>;
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
        setPicked(new Set(rows.filter((r) => r.score >= 0.75).map((r) => r.requirement_id)));
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
  controlIds: string[];
  onClose: () => void;
  /** Called after links are written. */
  onDone?: () => void;
};

/** Register bulk action "Suggest mappings": suggestions for every selected control in
 *  one review, strong ones pre-ticked, one Accept for the lot. */
export function BulkSuggestMappings({ controlIds, onClose, onDone }: BulkProps) {
  const [minScore, setMinScore] = useState(0.5);
  const [groups, setGroups] = useState<ControlSuggestions[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  const key = (controlId: string, requirementId: string) => `${controlId}:${requirementId}`;

  useEffect(() => {
    setGroups(null);
    setError(null);
    bulkSuggestRequirements(controlIds, minScore, 5)
      .then((res) => {
        setGroups(res);
        const strong = new Set<string>();
        res.forEach((g) => g.suggestions.forEach((s) => s.score >= 0.75 && strong.add(key(g.control_id, s.requirement_id))));
        setPicked(strong);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load suggestions"));
  }, [controlIds, minScore]);

  // Esc: a layer of the shared escape stack; ignored while saving.
  useEscapeLayer(true, () => {
    if (!saving) onClose();
  });
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(true, dialogRef);

  const total = useMemo(() => (groups ?? []).reduce((n, g) => n + g.suggestions.length, 0), [groups]);
  const withSuggestions = (groups ?? []).filter((g) => g.suggestions.length > 0);

  function flip(k: string) {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  async function accept() {
    const pairs = [...picked].map((k) => {
      const [control_id, requirement_id] = k.split(":");
      return { control_id, requirement_id };
    });
    if (!pairs.length) return;
    setSaving(true);
    try {
      const res = await bulkAcceptSuggestions(pairs);
      toast(`Linked ${res.linked} requirement${res.linked === 1 ? "" : "s"} across ${res.controls} control${res.controls === 1 ? "" : "s"}.`);
      onDone?.();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not link the requirements");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && !saving && onClose()}>
      <div ref={dialogRef} tabIndex={-1} className="modal wide" role="dialog" aria-modal="true" aria-label="Suggest mappings" onKeyDown={(e) => trapTab(e, dialogRef.current)}>
        <div className="modal-head">
          <h2>Suggest mappings for {controlIds.length} control{controlIds.length === 1 ? "" : "s"}</h2>
          <button className="x" onClick={onClose} aria-label="Close" disabled={saving}>✕</button>
        </div>
        <div className="modal-body">
          <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
            Clauses from your installed compliance frameworks that each control probably meets, matched on its
            name, description and reference. <b>Nothing is linked until you accept.</b> Strong matches are
            pre-ticked.
          </p>
          <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 12 }}>
            <div style={{ width: 220 }}>
              <label className="label" htmlFor="suggest-min">Show matches that are at least</label>
              <select id="suggest-min" className="select" value={minScore} onChange={(e) => setMinScore(Number(e.target.value))}>
                <option value={0.75}>Strong</option>
                <option value={0.5}>Likely</option>
                <option value={0.3}>Possible</option>
              </select>
            </div>
            {groups && (
              <span className="muted" style={{ fontSize: 12.5 }}>
                {total} suggestion{total === 1 ? "" : "s"} for {withSuggestions.length} of {groups.length} controls · {picked.size} selected
              </span>
            )}
          </div>
          {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}
          {groups === null && !error ? (
            <div className="muted">Finding clauses…</div>
          ) : groups && withSuggestions.length === 0 ? (
            <div className="empty" style={{ padding: 20 }}>
              <p>No clauses match at this strength. Try &ldquo;Possible&rdquo;, or install a framework from the Framework Library.</p>
            </div>
          ) : (
            <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 34 }} />
                    <th style={{ width: "30%" }}>Control</th>
                    <th>Suggested clause</th>
                    <th style={{ width: 90 }}>Match</th>
                  </tr>
                </thead>
                <tbody>
                  {withSuggestions.map((g) =>
                    g.suggestions.map((s, i) => {
                      const k = key(g.control_id, s.requirement_id);
                      return (
                        <tr key={k}>
                          <td>
                            <input type="checkbox" checked={picked.has(k)} onChange={() => flip(k)} aria-label={`Link ${s.reference} to ${g.name}`} />
                          </td>
                          <td>
                            {i === 0 && (
                              <>
                                <div className="cell-title">{g.name}</div>
                                {g.reference && <div className="ref">{g.reference}</div>}
                              </>
                            )}
                          </td>
                          <td>
                            <div style={{ fontSize: 13 }}><span className="ref">{s.reference}</span> {s.title}</div>
                            <div className="muted" style={{ fontSize: 11.5 }}>{s.framework}</div>
                            <Reasons reasons={s.reasons} />
                          </td>
                          <td><Strength score={s.score} /></td>
                        </tr>
                      );
                    }),
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn secondary" type="button" onClick={onClose} disabled={saving}>Close</button>
          <button className="btn" type="button" onClick={accept} disabled={!picked.size || saving}>
            {saving ? "Linking…" : `Accept selected (${picked.size})`}
          </button>
        </div>
      </div>
    </div>
  );
}
