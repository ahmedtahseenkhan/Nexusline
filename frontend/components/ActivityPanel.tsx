"use client";

import { useEffect, useId, useState } from "react";
import { apiCall } from "@/lib/api";
import { useFormat } from "@/lib/format";
import { actionWord, isForbidden, TRAIL_FORBIDDEN } from "@/components/record/trailWords";

/* The record's own trail: who did what to it, and when. A detail view without this is
   a snapshot; with it, it is evidence. Pulled from the same activity log the audit
   module shows tenant-wide, filtered to this one record.

     <ActivityPanel entityType="risk" entityId={r.id} defaultOpen />

   A viewer without the Activity log permission (HTTP 403) is told so — never shown
   "nothing recorded", which would read as an empty trail. Dossier pages use
   RecordTrail (components/record) instead.

   It loads once per record. A response for a record the panel no longer shows (the
   user switched records while it was in flight) is dropped, so the trail can never
   show another record's rows. */

type Entry = {
  id: string;
  actor_email: string;
  action: string;
  summary: string;
  created_at: string;
  changes?: Record<string, unknown>;
};

type Page = { items: Entry[]; total: number };

export default function ActivityPanel({
  entityType, entityId, defaultOpen = false,
}: { entityType: string; entityId: string; defaultOpen?: boolean }) {
  const { formatDateTime } = useFormat();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [forbidden, setForbidden] = useState(false);
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = `activity-${useId()}`;

  useEffect(() => {
    let live = true;
    setEntries(null);
    setForbidden(false);
    apiCall<Page>("GET", `/audit?entity_type=${encodeURIComponent(entityType)}&entity_id=${encodeURIComponent(entityId)}&limit=25`)
      .then((p) => {
        if (!live) return;
        setEntries(p.items);
        setTotal(p.total);
      })
      .catch((e) => {
        if (!live) return;
        setForbidden(isForbidden(e));
        setEntries([]);
        setTotal(0);
      });
    return () => {
      live = false;
    };
  }, [entityType, entityId]);

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head" style={{ cursor: "pointer" }} onClick={() => setOpen((v) => !v)}>
        <h3 style={{ margin: 0 }}>
          {/* The whole head toggles (click bubbles to it); the button makes it reachable by keyboard. */}
          <button
            type="button"
            className="activity-toggle"
            aria-expanded={open}
            aria-controls={open ? bodyId : undefined}
            style={{ display: "flex", alignItems: "center", gap: 8, padding: 0, border: 0, background: "none", font: "inherit", color: "inherit", cursor: "pointer" }}
          >
            <span aria-hidden="true" style={{ display: "inline-block", transform: open ? "rotate(90deg)" : "none", transition: "transform .12s" }}>▸</span>
            Activity
          </button>
        </h3>
        <span className="sub">
          {entries === null
            ? "…"
            : forbidden
              ? "no access"
              : total === 0
                ? "nothing recorded"
                : `${total} entr${total === 1 ? "y" : "ies"}`}
        </span>
      </div>

      {open && entries && (
        <div className="card-pad" style={{ paddingTop: 6 }} id={bodyId}>
          {forbidden && <div className="muted" style={{ fontSize: 12.5 }}>{TRAIL_FORBIDDEN}</div>}
          {!forbidden && entries.length === 0 && <div className="muted" style={{ fontSize: 12.5 }}>No activity recorded for this record yet.</div>}
          <div className="activity-list">
            {entries.map((e) => (
              <div key={e.id} className="activity-item">
                <span className="activity-dot" aria-hidden />
                <div style={{ fontSize: 12.5, minWidth: 0 }}>
                  <div className="activity-when" title={e.created_at}>{formatDateTime(e.created_at)}</div>
                  <div>
                    <b>{e.actor_email || "system"}</b>{" "}
                    <span className="muted">{actionWord(e.action)}</span>
                  </div>
                  {e.summary && <div style={{ marginTop: 2, overflowWrap: "anywhere" }}>{e.summary}</div>}
                </div>
              </div>
            ))}
          </div>
          {total > entries.length && (
            <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
              Latest {entries.length} of {total}. The full trail is under Settings → Activity Log.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
