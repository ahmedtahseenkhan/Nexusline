"use client";

/* The dossier rail's "Trail" card (record-page-spec §3.3.11): the record's audit log —
   the single trail. Workflow history and attestations are already audit rows, so there
   is NO merge and NO de-duplication: rows are shown verbatim, newest first.

     <RecordTrail entityType="risk" entityId={r.id} reference={r.reference}
       related={r.acceptances.map((a) => ({ entityType: "risk_acceptance", entityId: a.id, label: "Acceptance" }))} />

   GET /audit?entity_type=…&entity_id=…&limit=… plus one call per `related` record
   (their rows are labelled with that source). Filter chips (All · Approval ·
   Attestation · Decisions · Changes, with counts, aria-pressed) keep their state in the
   governance context, so Sign-off's "See in trail" can switch to Approval.

   Integrity flag (narrow): an action "submit" row whose summary starts with "Started
   approval route for " and does not contain this record's `reference` gets the note
   "Label names another record…". The row text itself is never altered.

   403 (no audit:read) says so — never "nothing recorded". Other errors offer Retry.

   An import backfill (`workflow_import`, written for a record imported as approved with
   no approval step on file) reads "Imported as approved, no approver recorded" and names
   no actor. Platform rows show "System" instead of the platform's mailbox.

   Loading: once per record (switching records never shows the previous record's rows
   and never fetches twice), then again after each action that reloads the governance
   (`gov.entityVersion` > 1). Responses that arrive after a newer request are dropped. */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import { useFormat } from "@/lib/format";
import { useRecordGovernance } from "@/components/record/RecordGovernance";
import type { TrailFilter } from "@/components/record/types";
import { isForbidden, TRAIL_FORBIDDEN, TRAIL_LABEL, trailCategory, trailRowWords } from "@/components/record/trailWords";

export type { TrailFilter };

type RecordTrailProps = {
  entityType: string;
  entityId: string;
  /** Enables the narrow integrity flag. */
  reference?: string | null;
  /** Risk: one per acceptance, label "Acceptance". */
  related?: { entityType: string; entityId: string; label: string }[];
  /** Default 25 per source. */
  limit?: number;
};

type AuditRow = {
  id: string;
  actor_email: string;
  action: string;
  summary: string;
  created_at: string;
  changes?: Record<string, unknown> | null;
};
type AuditPage = { items: AuditRow[]; total: number };
type Row = AuditRow & { source: string | null };

const FILTERS: TrailFilter[] = ["all", "approval", "attestation", "decision", "change"];
const ROUTE_PREFIX = "Started approval route for ";

function auditPath(entityType: string, entityId: string, limit: number) {
  return `/audit?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}&limit=${limit}`;
}

export default function RecordTrail({ entityType, entityId, reference, related, limit = 25 }: RecordTrailProps) {
  const { formatDateTime } = useFormat();
  const gov = useRecordGovernance(entityType, entityId);
  const [localFilter, setLocalFilter] = useState<TrailFilter>("all");
  const filter = gov ? gov.trailFilter : localFilter;
  const setFilter = gov ? gov.setTrailFilter : setLocalFilter;

  const recordKey = `${entityType}:${entityId}`;
  // Rows are kept with the record they belong to, so a switch never shows the old rows.
  const [loaded, setLoaded] = useState<{ key: string; rows: Row[]; total: number } | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "forbidden" | "error">("loading");
  const relatedKey = (related ?? []).map((r) => `${r.entityType}:${r.entityId}:${r.label}`).join("|");
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setState("loading");
    const sources: { entityType: string; entityId: string; label: string | null }[] = [
      { entityType, entityId, label: null },
      ...(related ?? []).map((r) => ({ ...r, label: r.label })),
    ];
    try {
      const pages = await Promise.all(sources.map((s) => apiCall<AuditPage>("GET", auditPath(s.entityType, s.entityId, limit))));
      if (mine !== seq.current) return; // a newer request (or another record) superseded this one
      const merged: Row[] = [];
      let sum = 0;
      pages.forEach((p, i) => {
        sum += p.total ?? p.items.length;
        p.items.forEach((it) => merged.push({ ...it, source: sources[i].label }));
      });
      merged.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
      setLoaded({ key: `${entityType}:${entityId}`, rows: merged, total: sum });
      setState("ok");
    } catch (e) {
      if (mine !== seq.current) return;
      setLoaded(null);
      setState(isForbidden(e) ? "forbidden" : "error");
    }
    // relatedKey stands in for `related` (a new array each render)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType, entityId, limit, relatedKey]);

  // One load per record (and when `related` or `limit` change).
  useEffect(() => {
    load();
  }, [load]);

  // Follow governance reloads: every record-changing action calls gov.reload() (the
  // reload rule), so the trail refetches after each one. The governance's first load
  // for a record (entityVersion 0 → 1) is not an action — the effect above already
  // fetched for it — so switching records fetches once, not twice.
  const govKey = gov ? `${gov.entityType}:${gov.entityId}` : "";
  const entityVersion = gov?.entityVersion ?? 0;
  const seen = useRef({ key: govKey, version: entityVersion });
  useEffect(() => {
    const prev = seen.current;
    seen.current = { key: govKey, version: entityVersion };
    if (!gov || prev.key !== govKey) return;
    if (entityVersion > prev.version && entityVersion > 1) load();
    // `load` is read, not a trigger: its own effect covers record switches.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [govKey, entityVersion]);

  const rows = loaded && loaded.key === recordKey ? loaded.rows : null;
  const total = rows ? loaded?.total ?? 0 : 0;

  const counts: Record<TrailFilter, number> = { all: 0, approval: 0, attestation: 0, decision: 0, change: 0 };
  (rows ?? []).forEach((r) => {
    counts.all++;
    counts[trailCategory(r.action)]++;
  });
  // Rows outside the filter stay in the DOM (hidden on screen) so print shows the whole trail.
  const matches = (r: Row) => filter === "all" || trailCategory(r.action) === filter;
  const shownCount = (rows ?? []).filter(matches).length;

  return (
    <section id="rec-trail-card" tabIndex={-1} className="rec-rail-card" aria-labelledby="rec-trail-h">
      <header>
        <h3 id="rec-trail-h">Trail</h3>
        {state === "ok" && <span className="rec-op-count">{total}</span>}
      </header>
      <div className="rec-rail-body">
        {state === "loading" && rows === null && <p className="rec-empty">Loading the trail…</p>}
        {state === "forbidden" && <p className="rec-empty">{TRAIL_FORBIDDEN}</p>}
        {state === "error" && (
          <p className="rec-empty">
            Could not load the trail.{" "}
            <button type="button" className="rec-link" onClick={load}>Retry</button>
          </p>
        )}
        {rows !== null && state !== "forbidden" && state !== "error" && (
          rows.length === 0 ? (
            <p className="rec-empty">Nothing recorded for this record yet.</p>
          ) : (
            <>
              <div className="rec-filters" role="group" aria-label="Filter the trail">
                {FILTERS.map((f) => (
                  <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                    {TRAIL_LABEL[f]} {counts[f]}
                  </button>
                ))}
              </div>
              {shownCount === 0 && (
                <p className="rec-empty rec-trail-none" style={{ marginTop: 8 }}>No {TRAIL_LABEL[filter].toLowerCase()} rows in the latest {rows.length}.</p>
              )}
              <ol className="rec-trail">
                {rows.map((r) => {
                  const cat = trailCategory(r.action);
                  const words = trailRowWords(r);
                  const reason = r.changes && typeof r.changes.reason === "string" ? r.changes.reason.trim() : "";
                  const flagged =
                    r.action === "submit" &&
                    !!reference &&
                    (r.summary ?? "").startsWith(ROUTE_PREFIX) &&
                    !(r.summary ?? "").includes(reference);
                  return (
                    <li key={`${r.source ?? "self"}-${r.id}`} className={matches(r) ? undefined : "is-out"}>
                      <span className="dot" aria-hidden="true" />
                      <div>
                        <time dateTime={r.created_at}>{formatDateTime(r.created_at)}</time>
                        {words.sentence ? (
                          <b className="rec-trail-import">{words.sentence}</b>
                        ) : (
                          <>
                            <b>{words.actor}</b> {words.verb}
                          </>
                        )}{" "}
                        <span className="cat">· {r.source ? `${r.source} · ` : ""}{TRAIL_LABEL[cat]}</span>
                        {r.summary && !words.sentence && <div className="sum">{r.summary}</div>}
                        {reason && <div className="quote">&ldquo;{reason}&rdquo;</div>}
                        {flagged && (
                          <span className="flag">Label names another record. The browser supplied this label when the route started.</span>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
              <p className="rec-trail-foot">
                Latest {rows.length} of {total} · <Link href="/audit">Full trail in Activity log</Link>
              </p>
            </>
          )
        )}
      </div>
    </section>
  );
}

export { RecordTrail };
