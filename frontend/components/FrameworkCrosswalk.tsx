"use client";

/* Crosswalk between two frameworks (Compliance → Crosswalk tab).

   Recorded crosswalks are typed: how the two clauses relate (equivalent, contained in,
   contains, overlaps, related), where the mapping comes from (library content, an
   accepted suggestion, or added by hand) and who reviewed it. Library content between
   installed frameworks is recorded automatically; reviewing it means approving the rows
   that are right, retyping or removing the rest. Removing a library row rejects it, so a
   content update never adds it back; rejected rows can be restored. Suggestions come from
   the topic table and from controls two clauses share; nothing is recorded until someone
   ticks and accepts. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { Badge } from "@/components/badges";
import {
  getCrosswalkContent,
  ORIGIN_LABEL,
  RELATIONSHIPS,
  RELATIONSHIP_HELP,
  RELATIONSHIP_LABEL,
  type CrosswalkContent,
  type CrosswalkOrigin,
  type CrosswalkRejection,
  type CrosswalkRelationship,
} from "@/lib/compliance";

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
  relationship: CrosswalkRelationship;
  rationale: string;
  source: string;
  content_version: string;
  confidence: number | null;
  origin: CrosswalkOrigin;
  approved_by: string;
  approved_at: string | null;
  shipped: boolean;
};

type PairsResponse = {
  from_framework: FrameworkRef;
  to_framework: FrameworkRef;
  total: number;
  by_relationship: Record<string, number>;
  by_origin: Record<string, number>;
  sources: string[];
  content_version: string;
  pairs: Pair[];
};

type WriteResult = { changed: number; skipped: number; rejected?: number };

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);
const key = (a: string, b: string) => `${a}:${b}`;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function Strength({ value }: { value: string }) {
  return value === "high" ? <Badge tone="low">Strong</Badge> : <Badge tone="info">Likely</Badge>;
}

function RelationshipBadge({ value }: { value: CrosswalkRelationship }) {
  const tone = value === "equivalent" ? "low" : value === "related" ? "neutral" : "info";
  return (
    <span title={RELATIONSHIP_HELP[value]}>
      <Badge tone={tone} plain>{RELATIONSHIP_LABEL[value]}</Badge>
    </span>
  );
}

export default function FrameworkCrosswalk({ framework, frameworks }: { framework: FrameworkLite; frameworks: FrameworkLite[] }) {
  const others = useMemo(() => frameworks.filter((f) => f.id !== framework.id), [frameworks, framework.id]);
  const [target, setTarget] = useState<string>("");
  const [recorded, setRecorded] = useState<PairsResponse | null>(null);
  const [data, setData] = useState<SuggestionsResponse | null>(null);
  const [rejections, setRejections] = useState<CrosswalkRejection[]>([]);
  const [content, setContent] = useState<CrosswalkContent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [acceptAs, setAcceptAs] = useState<CrosswalkRelationship>("related");
  const [strongOnly, setStrongOnly] = useState(false);
  const [saving, setSaving] = useState(false);
  // Filters over the recorded crosswalks.
  const [relFilter, setRelFilter] = useState<"" | CrosswalkRelationship>("");
  const [originFilter, setOriginFilter] = useState<"" | CrosswalkOrigin>("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [unreviewedOnly, setUnreviewedOnly] = useState(false);
  const [busyPair, setBusyPair] = useState<string | null>(null);

  useEffect(() => {
    setTarget((cur) => (cur && others.some((f) => f.id === cur) ? cur : others[0]?.id || ""));
  }, [others]);

  useEffect(() => {
    getCrosswalkContent().then(setContent).catch(() => setContent(null));
  }, []);

  const load = useCallback(() => {
    if (!target) return;
    setError(null);
    setRecorded(null);
    setData(null);
    const qs = `from_framework=${framework.id}&to_framework=${target}`;
    Promise.all([
      apiCall<PairsResponse>("GET", `/compliance/crosswalks?${qs}`),
      apiCall<SuggestionsResponse>("GET", `/compliance/crosswalks/suggest?${qs}`),
      apiCall<CrosswalkRejection[]>("GET", `/compliance/crosswalks/rejections?${qs}`),
    ])
      .then(([p, s, r]) => {
        setRecorded(p);
        setData(s);
        setRejections(r);
        setPicked(new Set(s.suggestions.filter((x) => x.strength === "high").map((x) => key(x.requirement_id, x.related_requirement_id))));
      })
      .catch((e) => setError(errMsg(e, "Could not load the crosswalk")));
  }, [framework.id, target]);

  useEffect(() => {
    load();
  }, [load]);

  const pairs = useMemo(() => {
    const q = sourceFilter.trim().toLowerCase();
    return (recorded?.pairs || []).filter(
      (p) =>
        (!relFilter || p.relationship === relFilter) &&
        (!originFilter || p.origin === originFilter) &&
        (!q || p.source.toLowerCase().includes(q)) &&
        (!unreviewedOnly || !p.approved_at),
    );
  }, [recorded, relFilter, originFilter, sourceFilter, unreviewedOnly]);

  const shown = useMemo(
    () => (data?.suggestions || []).filter((s) => !strongOnly || s.strength === "high"),
    [data, strongOnly],
  );

  const pairContent = useMemo(() => {
    if (!content || !recorded) return null;
    const a = recorded.from_framework.template_key;
    const b = recorded.to_framework.template_key;
    if (!a || !b) return null;
    return content.pairs.find((p) => (p.from_template === a && p.to_template === b) || (p.from_template === b && p.to_template === a)) || null;
  }, [content, recorded]);

  function flip(k: string) {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  }

  const body = (p: { requirement_id: string; related_requirement_id: string }, extra: object = {}) => ({
    requirement_id: p.requirement_id,
    related_requirement_id: p.related_requirement_id,
    ...extra,
  });

  async function accept() {
    const chosen = shown.filter((s) => picked.has(key(s.requirement_id, s.related_requirement_id)));
    if (!chosen.length) return;
    setSaving(true);
    try {
      const res = await apiCall<WriteResult>("POST", "/compliance/crosswalks/accept", {
        pairs: chosen.map((s) => body(s, { relationship: acceptAs })),
        origin: "accepted",
      });
      toast(res.changed ? `Crosswalked ${plural(res.changed, "pair")} of clauses as ${RELATIONSHIP_LABEL[acceptAs].toLowerCase()}.` : "Those clauses were already crosswalked.");
      load();
    } catch (e) {
      toast(errMsg(e, "Could not record the crosswalks"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function approve(list: Pair[]) {
    if (!list.length) return;
    setSaving(true);
    try {
      const res = await apiCall<WriteResult>("POST", "/compliance/crosswalks/approve", { pairs: list.map((p) => body(p)) });
      toast(`Marked ${plural(res.changed, "crosswalk")} as reviewed.`);
      load();
    } catch (e) {
      toast(errMsg(e, "Could not approve the crosswalks"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function retype(p: Pair, relationship: CrosswalkRelationship) {
    if (relationship === p.relationship) return;
    setBusyPair(key(p.requirement_id, p.related_requirement_id));
    try {
      await apiCall<WriteResult>("POST", "/compliance/crosswalks/retype", { pairs: [body(p, { relationship })] });
      toast(`${p.reference} and ${p.related_reference}: now ${RELATIONSHIP_LABEL[relationship].toLowerCase()}. Library updates will no longer change this row.`);
      load();
    } catch (e) {
      toast(errMsg(e, "Could not change the relationship"), "error");
    } finally {
      setBusyPair(null);
    }
  }

  async function remove(p: Pair) {
    const ok = await confirmDialog({
      title: `Remove the crosswalk between ${p.reference} and ${p.related_reference}?`,
      message: p.shipped
        ? "This crosswalk comes from the library. Removing it records a rejection, so library updates will not add it back. You can restore it from the rejected list. The change is kept in the activity trail."
        : "The two clauses are no longer linked. The change is kept in the activity trail.",
      confirmLabel: p.shipped ? "Reject" : "Remove",
      danger: true,
    });
    if (!ok) return;
    try {
      const res = await apiCall<WriteResult>("POST", "/compliance/crosswalks/remove", { pairs: [body(p)] });
      toast(res.rejected ? "Crosswalk rejected" : "Crosswalk removed");
      load();
    } catch (e) {
      toast(errMsg(e, "Could not remove the crosswalk"), "error");
    }
  }

  async function restore(ids: string[]) {
    try {
      const res = await apiCall<{ inserted: number }>("POST", "/compliance/crosswalks/rejections/restore", { ids });
      toast(`Restored ${plural(ids.length, "rejected crosswalk")}; ${plural(res.inserted, "crosswalk")} recorded again.`);
      load();
    } catch (e) {
      toast(errMsg(e, "Could not restore the crosswalks"), "error");
    }
  }

  const targetName = others.find((f) => f.id === target)?.name || "";
  const pickedShown = shown.filter((s) => picked.has(key(s.requirement_id, s.related_requirement_id))).length;
  const unreviewedShown = pairs.filter((p) => !p.approved_at);

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
        <div className="card-pad muted" style={{ paddingTop: 0, fontSize: 12.5, lineHeight: 1.55 }}>
          Relationships read from {framework.name} to the other framework. Only <em>equivalent</em> and <em>contained in</em>{" "}
          let a tested control on the other clause show this one as covered via crosswalk; that coverage is shown apart and never
          counts as a direct mapping.
          {content && (
            <>
              {" "}Library crosswalk content version <strong>{content.version}</strong>
              {pairContent ? (
                <>: {plural(pairContent.rows, "row")} for this pair, source “{pairContent.source}”.</>
              ) : recorded?.from_framework.template_key && recorded?.to_framework.template_key ? (
                <>: the library ships no crosswalk content for this pair.</>
              ) : (
                <>: only frameworks installed from the library receive crosswalk content.</>
              )}
            </>
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Recorded crosswalks</h3>
          <span className="sub">
            {recorded
              ? `${pairs.length} of ${plural(recorded.total, "pair")}${recorded.by_origin.shipped ? ` · ${recorded.by_origin.shipped} from library content` : ""}`
              : ""}
          </span>
        </div>
        {recorded && recorded.total > 0 && (
          <div className="card-pad" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", paddingBottom: 8 }}>
            <select className="select" style={{ width: 170 }} value={relFilter} onChange={(e) => setRelFilter(e.target.value as "" | CrosswalkRelationship)} aria-label="Filter by relationship">
              <option value="">All relationships</option>
              {RELATIONSHIPS.map((r) => (
                <option key={r} value={r}>{RELATIONSHIP_LABEL[r]} ({recorded.by_relationship[r] || 0})</option>
              ))}
            </select>
            <select className="select" style={{ width: 190 }} value={originFilter} onChange={(e) => setOriginFilter(e.target.value as "" | CrosswalkOrigin)} aria-label="Filter by origin">
              <option value="">All origins</option>
              {(Object.keys(ORIGIN_LABEL) as CrosswalkOrigin[]).map((o) => (
                <option key={o} value={o}>{ORIGIN_LABEL[o]} ({recorded.by_origin[o] || 0})</option>
              ))}
            </select>
            {recorded.sources.length > 0 && (
              <select className="select" style={{ width: 240 }} value={sourceFilter} onChange={(e) => setSourceFilter(e.target.value)} aria-label="Filter by source">
                <option value="">All sources</option>
                {recorded.sources.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            )}
            <label className="switch" style={{ whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={unreviewedOnly} onChange={(e) => setUnreviewedOnly(e.target.checked)} />
              <span className="track" />
              <span className="txt">Not reviewed</span>
            </label>
            <button type="button" className="btn secondary sm" disabled={!unreviewedShown.length || saving} onClick={() => approve(unreviewedShown)}>
              Mark {unreviewedShown.length} shown as reviewed
            </button>
          </div>
        )}
        {recorded === null ? (
          <div className="card-pad muted">Loading…</div>
        ) : recorded.total === 0 ? (
          <div className="card-pad muted" style={{ fontSize: 13 }}>No clauses of these two frameworks are crosswalked yet.</div>
        ) : pairs.length === 0 ? (
          <div className="card-pad muted" style={{ fontSize: 13 }}>No recorded crosswalks match these filters.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{framework.name}</th>
                  <th style={{ width: 150 }}>Relationship</th>
                  <th>{targetName}</th>
                  <th style={{ width: 200 }}>Source</th>
                  <th style={{ width: 150 }}></th>
                </tr>
              </thead>
              <tbody>
                {pairs.map((p) => {
                  const k = key(p.requirement_id, p.related_requirement_id);
                  return (
                    <tr key={k}>
                      <td>
                        <span className="ref">{p.reference}</span> {p.title}
                        {p.rationale && <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{p.rationale}</div>}
                      </td>
                      <td>
                        <select
                          className="select"
                          value={p.relationship}
                          disabled={busyPair === k}
                          onChange={(e) => retype(p, e.target.value as CrosswalkRelationship)}
                          aria-label={`Relationship of ${p.reference} to ${p.related_reference}`}
                          title={RELATIONSHIP_HELP[p.relationship]}
                        >
                          {RELATIONSHIPS.map((r) => (
                            <option key={r} value={r}>{RELATIONSHIP_LABEL[r]}</option>
                          ))}
                        </select>
                      </td>
                      <td><span className="ref">{p.related_reference}</span> {p.related_title}</td>
                      <td style={{ fontSize: 12 }}>
                        <div>{ORIGIN_LABEL[p.origin]}{p.confidence != null && <span className="muted"> · {Math.round(p.confidence * 100)}%</span>}</div>
                        {p.source && <div className="muted">{p.source}{p.content_version ? ` (${p.content_version})` : ""}</div>}
                        <div className="muted">{p.approved_at ? `Reviewed by ${p.approved_by || "—"}` : "Not reviewed"}</div>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          {!p.approved_at && (
                            <button type="button" className="btn secondary sm" disabled={saving} onClick={() => approve([p])}>Approve</button>
                          )}
                          <button type="button" className="btn secondary sm" onClick={() => remove(p)}>{p.shipped ? "Reject" : "Remove"}</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {rejections.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>Rejected library crosswalks</h3>
            <span className="sub">{plural(rejections.length, "row")} · not added back by library updates</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Clause</th><th style={{ width: 130 }}>Library said</th><th>Clause</th><th>Rejected</th><th style={{ width: 100 }}></th></tr>
              </thead>
              <tbody>
                {rejections.map((r) => (
                  <tr key={r.id}>
                    <td><span className="ref">{r.from_reference}</span> {r.from_title}</td>
                    <td><RelationshipBadge value={r.relationship} /></td>
                    <td><span className="ref">{r.to_reference}</span> {r.to_title}</td>
                    <td style={{ fontSize: 12 }}>
                      <div>{r.rejected_by || "—"}{r.rejected_at ? ` · ${r.rejected_at.slice(0, 10)}` : ""}</div>
                      {r.reason && <div className="muted">{r.reason}</div>}
                    </td>
                    <td><button type="button" className="btn secondary sm" onClick={() => restore([r.id])}>Restore</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

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
            main clause for that topic (<em>strong</em> when both are), or when the same control implements both. Rejected library
            crosswalks are not suggested again. Nothing is recorded until you accept it, with the relationship you choose.
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
                <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12.5 }}>
                  Record as
                  <select className="select" style={{ width: 150 }} value={acceptAs} onChange={(e) => setAcceptAs(e.target.value as CrosswalkRelationship)} aria-label="Relationship to record" title={RELATIONSHIP_HELP[acceptAs]}>
                    {RELATIONSHIPS.map((r) => (
                      <option key={r} value={r}>{RELATIONSHIP_LABEL[r]}</option>
                    ))}
                  </select>
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
                          <span className="muted">↔</span>
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
