"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";

/* The record's own trail: who did what to it, and when. A detail view without this is
   a snapshot; with it, it is evidence. Pulled from the same activity log the audit
   module shows tenant-wide, filtered to this one record. */

type Entry = {
  id: string;
  actor_email: string;
  action: string;
  summary: string;
  created_at: string;
  changes?: Record<string, unknown>;
};

type Page = { items: Entry[]; total: number };

const ACTION_WORDS: Record<string, string> = {
  create: "created", update: "updated", delete: "deleted", review: "reviewed",
  attest: "attested", decide: "decided", publish: "published", export: "exported",
  request_acceptance: "requested acceptance", approve_acceptance: "approved acceptance",
  reject_acceptance: "rejected acceptance", expire_acceptance: "acceptance lapsed",
  accept_residual: "accepted residual",
};

export default function ActivityPanel({
  entityType, entityId, defaultOpen = false,
}: { entityType: string; entityId: string; defaultOpen?: boolean }) {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setEntries(null);
    apiCall<Page>("GET", `/audit?entity_type=${encodeURIComponent(entityType)}&entity_id=${entityId}&limit=25`)
      .then((p) => { setEntries(p.items); setTotal(p.total); })
      .catch(() => setEntries([]));
  }, [entityType, entityId]);

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head" style={{ cursor: "pointer" }} onClick={() => setOpen((v) => !v)}>
        <h3 style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ display: "inline-block", transform: open ? "rotate(90deg)" : "none", transition: "transform .12s" }}>▸</span>
          Activity
        </h3>
        <span className="sub">
          {entries === null ? "…" : total === 0 ? "nothing recorded" : `${total} entr${total === 1 ? "y" : "ies"}`}
        </span>
      </div>

      {open && entries && (
        <div className="card-pad" style={{ paddingTop: 6 }}>
          {entries.length === 0 && <div className="muted" style={{ fontSize: 12.5 }}>No activity recorded for this record yet.</div>}
          <div className="activity-list">
            {entries.map((e) => (
              <div key={e.id} className="activity-item">
                <span className="activity-dot" aria-hidden />
                <div style={{ fontSize: 12.5, minWidth: 0 }}>
                  <div className="activity-when" title={e.created_at}>{e.created_at.slice(0, 16).replace("T", " ")}</div>
                  <div>
                    <b>{e.actor_email || "system"}</b>{" "}
                    <span className="muted">{ACTION_WORDS[e.action] ?? e.action.replace(/_/g, " ")}</span>
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
