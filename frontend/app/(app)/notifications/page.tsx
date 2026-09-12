"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type Notification } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconBell } from "@/components/icons";
import { useFormat } from "@/lib/format";

const TONE: Record<string, "critical" | "high" | "info"> = {
  critical: "critical",
  warning: "high",
  info: "info",
};

const PAGE = 100;

type Scope = "all" | "mine";

function ago(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

/** Who an alert reached the reader as: themselves, a role they hold, or everyone. */
function Audience({ n }: { n: Notification }) {
  if (n.audience === "me") return <Badge tone="info" plain>For you</Badge>;
  if (n.audience === "role") return <Badge tone="neutral" plain>{`Role: ${n.role_name || "yours"}`}</Badge>;
  return <Badge tone="neutral" plain>Everyone</Badge>;
}

export default function NotificationsPage() {
  const { formatDateTime } = useFormat();
  const [scope, setScope] = useState<Scope>("all");
  const [items, setItems] = useState<Notification[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const query = scope === "mine" ? "&mine=true" : "";

  const load = useCallback(
    (markSeen: boolean) => {
      setLoading(true);
      setError(null);
      api
        .notifications(PAGE, 0, query)
        .then((r) => {
          setItems(r.items);
          setTotal(r.total);
          setCounts(r.counts || {});
          // Mark everything read now that the user is viewing the feed.
          if (markSeen) api.markNotificationsSeen().catch(() => {});
        })
        .catch((e) => setError(e instanceof Error ? e.message : "Could not load alerts"))
        .finally(() => setLoading(false));
    },
    [query],
  );

  useEffect(() => {
    load(scope === "all");
  }, [load, scope]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const r = await api.notifications(PAGE, items.length, query);
      setItems((prev) => [...prev, ...r.items]);
      setTotal(r.total);
      setCounts(r.counts || {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load more alerts");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>Notifications</h1>
        <p>
          Alerts for you: those addressed to you as a record&apos;s owner, operator or approver, those addressed
          to a role you hold, and those for everyone because the record names nobody. Each opens its record.
          Routine items of one kind are grouped once you have more than five; breaches, turnaround times,
          approvals and attestations are always listed one by one. <Link href="/my-work">My Work</Link> lists
          everything waiting for you, due soon as well as overdue.
        </p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat danger"><div className="stat-top"><span className="n">{counts.critical ?? 0}</span></div><span className="l">Critical</span></div>
        <div className="card stat warn"><div className="stat-top"><span className="n">{counts.warning ?? 0}</span></div><span className="l">Warning</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{counts.info ?? 0}</span></div><span className="l">Info</span></div>
      </div>

      <div className="card">
        <div className="card-head" style={{ flexWrap: "wrap", gap: 10 }}>
          <h3>Alert feed</h3>
          <span className="sub">
            {total} active{items.length < total ? ` · showing ${items.length}` : ""}
          </span>
          <div className="seg" role="tablist" aria-label="Which alerts" style={{ marginLeft: "auto" }}>
            <button type="button" role="tab" aria-selected={scope === "all"} className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>
              Everything for me
            </button>
            <button type="button" role="tab" aria-selected={scope === "mine"} className={scope === "mine" ? "on" : ""} onClick={() => setScope("mine")}>
              Addressed to me
            </button>
          </div>
        </div>
        <div className="card-pad" style={{ paddingTop: 6, paddingBottom: 6 }}>
          {items.map((n) => (
            <div className="activity-item" key={n.id} style={{ alignItems: "center" }}>
              <Badge tone={TONE[n.category] || "info"}>{n.category}</Badge>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13.5, fontWeight: n.seen ? 500 : 650 }}>{n.title}</div>
                <div className="when">
                  {n.body} · <span title={formatDateTime(n.created_at)}>{ago(n.created_at)}</span>
                </div>
              </div>
              <Audience n={n} />
              {n.link && (
                <Link href={n.link} className="btn secondary sm" aria-label={`Open ${n.title}`}>
                  Open
                </Link>
              )}
            </div>
          ))}
          {!loading && items.length === 0 && !error && (
            <div className="empty">
              <span className="ico"><IconBell width={24} height={24} /></span>
              <h3>All clear</h3>
              <p>
                {scope === "mine"
                  ? "Nothing is addressed to you or your roles right now."
                  : "No active alerts — nothing overdue, breaching, or gapped right now."}
              </p>
            </div>
          )}
          {items.length < total && (
            <div style={{ display: "flex", justifyContent: "center", padding: "10px 0" }}>
              <button className="btn secondary sm" onClick={loadMore} disabled={loadingMore}>
                {loadingMore ? "Loading…" : `Show more (${total - items.length} left)`}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
