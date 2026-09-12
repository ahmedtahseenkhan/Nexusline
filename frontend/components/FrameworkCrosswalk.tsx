"use client";

/* Crosswalk between two frameworks (Compliance → Crosswalk tab).

   Shows the crosswalks already recorded between the selected framework and another one,
   and suggested ones with the reason and strength of each. Suggestions come from the
   topic table (a topic's primary clause in at least one of the two frameworks) and from
   controls two clauses share. Nothing is recorded until someone ticks and accepts. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { Badge } from "@/components/badges";

type FrameworkLite = { id: string; name: string; kind?: string };

type FrameworkRef = { id: string; name: string; template_key: string | null };

type Suggestion = {
  requirement_id: string;
  reference: string;
  title: string;
  related_requirement_id: string;
  related_reference: string;
  related_title: string;
  confidence: number;
  strength: string;
  reasons: string[];
  sources: string[];
};

type SuggestionsResponse = {
  from_framework: FrameworkRef;
  to_framework: FrameworkRef;
  topic_matching: boolean;
  existing: number;
  total: number;
  suggestions: Suggestion[];
};

type Pair = {
  requirement_id: string;
  reference: string;
  title: string;
  related_requirement_id: string;
  related_reference: string;
  related_title: string;
};

type PairsResponse = { from_framework: FrameworkRef; to_framework: FrameworkRef; pairs: Pair[] };

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
const key = (a: string, b: string) => `${a}:${b}`;

function Strength({ value }: { value: string }) {
  return value === "high" ? <Badge tone="low">Strong</Badge> : <Badge tone="info">Likely</Badge>;
}

export default function FrameworkCrosswalk({ framework, frameworks }: { framework: FrameworkLite; frameworks: FrameworkLite[] }) {
  const others = useMemo(() => frameworks.filter((f) => f.id !== framework.id), [frameworks, framework.id]);
  const [target, setTarget] = useState<string>("");
  const [pairs, setPairs] = useState<Pair[] | null>(null);
  const [data, setData] = useState<SuggestionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [strongOnly, setStrongOnly] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setTarget((cur) => (cur && others.some((f) => f.id === cur) ? cur : others[0]?.id || ""));
  }, [others]);

  const load = useCallback(() => {
    if (!target) return;
    setError(null);
    setPairs(null);
    setData(null);
    const qs = `from_framework=${framework.id}&to_framework=${target}`;
    Promise.all([
      apiCall<PairsResponse>("GET", `/compliance/crosswalks?${qs}`),
      apiCall<SuggestionsResponse>("GET", `/compliance/crosswalks/suggest?${qs}`),
    ])
      .then(([p, s]) => {
        setPairs(p.pairs);
        setData(s);
        setPicked(new Set(s.suggestions.filter((x) => x.strength === "high").map((x) => key(x.requirement_id, x.related_requirement_id))));
      })
      .catch((e) => setError(errMsg(e, "Could not load the crosswalk")));
  }, [framework.id, target]);

  useEffect(() => {
    load();
  }, [load]);

  const shown = useMemo(
    () => (data?.suggestions || []).filter((s) => !strongOnly || s.strength === "high"),
    [data, strongOnly],
  );

  function flip(k: string) {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  async function accept() {
    const chosen = shown.filter((s) => picked.has(key(s.requirement_id, s.related_requirement_id)));
    if (!chosen.length) return;
    setSaving(true);
    try {
      const res = await apiCall<{ changed: number; skipped: number }>("POST", "/compliance/crosswalks/accept", {
        pairs: chosen.map((s) => ({ requirement_id: s.requirement_id, related_requirement_id: s.related_requirement_id })),
      });
      toast(res.changed ? `Crosswalked ${res.changed} pair${res.changed === 1 ? "" : "s"} of clauses.` : "Those clauses were already crosswalked.");
      load();
    } catch (e) {
      toast(errMsg(e, "Could not record the crosswalks"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove(p: Pair) {
    const ok = await confirmDialog({
      title: `Remove the crosswalk ${p.reference} ≡ ${p.related_reference}?`,
      message: "The two clauses are no longer treated as equivalent. The change is kept in the activity trail.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      await apiCall("POST", "/compliance/crosswalks/remove", {
        pairs: [{ requirement_id: p.requirement_id, related_requirement_id: p.related_requirement_id }],
      });
      toast("Crosswalk removed");
      load();
    } catch (e) {
      toast(errMsg(e, "Could not remove the crosswalk"), "error");
    }
  }

  const targetName = others.find((f) => f.id === target)?.name || "";
  const pickedShown = shown.filter((s) => picked.has(key(s.requirement_id, s.related_requirement_id))).length;

  if (!others.length) {
    return (
      <div className="card">
        <div className="card-pad muted">Install a second framework to crosswalk {framework.name} with it.</div>
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="card">
        <div className="card-pad" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: 13 }}>
            Crosswalk <strong>{framework.name}</strong> with
          </span>
          <select className="select" style={{ width: 300 }} value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Framework to crosswalk with">
            {others.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Recorded crosswalks</h3>
          <span className="sub">{pairs ? `${pairs.length} pair${pairs.length === 1 ? "" : "s"}` : ""}</span>
        </div>
        {pairs === null ? (
          <div className="card-pad muted">Loading…</div>
        ) : pairs.length === 0 ? (
          <div className="card-pad muted" style={{ fontSize: 13 }}>No clauses of these two frameworks are crosswalked yet.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{framework.name}</th>
                  <th>{targetName}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((p) => (
                  <tr key={key(p.requirement_id, p.related_requirement_id)}>
                    <td><span className="ref">{p.reference}</span> {p.title}</td>
                    <td><span className="ref">{p.related_reference}</span> {p.related_title}</td>
                    <td><button type="button" className="btn secondary sm" onClick={() => remove(p)}>Remove</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Suggested crosswalks</h3>
          <span className="sub">
            {data ? `${data.total} suggestion${data.total === 1 ? "" : "s"}` : ""}
          </span>
        </div>
        <div className="card-pad">
          <p className="muted" style={{ marginTop: 0, fontSize: 12.5, lineHeight: 1.5 }}>
            Two clauses are suggested when the topic table lists them for the same topic and at least one is its framework&apos;s
            main clause for that topic (<em>strong</em> when both are), or when the same control implements both. Nothing is
            recorded until you accept it.
            {data && !data.topic_matching && (
              <> One of these frameworks is not from the Framework Library, so only clauses implemented by the same control can be suggested.</>
            )}
          </p>
          {data === null && !error ? (
            <span className="muted">Finding candidates…</span>
          ) : data && data.suggestions.length === 0 ? (
            <span className="muted" style={{ fontSize: 13 }}>No further crosswalks to suggest between these two frameworks.</span>
          ) : data ? (
            <>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
                <label className="switch" style={{ whiteSpace: "nowrap" }}>
                  <input type="checkbox" checked={strongOnly} onChange={(e) => setStrongOnly(e.target.checked)} />
                  <span className="track" />
                  <span className="txt">Strong only</span>
                </label>
                <button type="button" className="btn sm" disabled={!pickedShown || saving} onClick={accept}>
                  {saving ? "Recording…" : `Accept selected (${pickedShown})`}
                </button>
                <button
                  type="button"
                  className="btn secondary sm"
                  disabled={saving}
                  onClick={() =>
                    setPicked(pickedShown === shown.length ? new Set() : new Set(shown.map((s) => key(s.requirement_id, s.related_requirement_id))))
                  }
                >
                  {pickedShown === shown.length ? "Clear" : "Select all"}
                </button>
                {data.total > data.suggestions.length && (
                  <span className="muted" style={{ fontSize: 12 }}>Showing the strongest {data.suggestions.length} of {data.total}.</span>
                )}
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                {shown.map((s) => {
                  const k = key(s.requirement_id, s.related_requirement_id);
                  return (
                    <label key={k} style={{ display: "flex", gap: 8, alignItems: "flex-start", cursor: "pointer", borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                      <input
                        type="checkbox"
                        checked={picked.has(k)}
                        onChange={() => flip(k)}
                        style={{ marginTop: 3 }}
                        aria-label={`Crosswalk ${s.reference} with ${s.related_reference}`}
                      />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
                          <span className="ref">{s.reference}</span>
                          <span>{s.title}</span>
                          <span className="muted">≡</span>
                          <span className="ref">{s.related_reference}</span>
                          <span>{s.related_title}</span>
                          <Strength value={s.strength} />
                        </div>
                        <div className="muted" style={{ fontSize: 11.5, marginTop: 2, lineHeight: 1.45 }}>{s.reasons.join(" · ")}</div>
                      </div>
                    </label>
                  );
                })}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
