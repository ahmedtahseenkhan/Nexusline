"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Notification } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconBell } from "@/components/icons";

const TONE: Record<string, "critical" | "high" | "info"> = {
  critical: "critical",
  warning: "high",
  info: "info",
};

function ago(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function NotificationsPage() {
  const [items, setItems] = useState<Notification[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .notifications()
      .then((r) => {
        setItems(r.items);
        // mark everything read now that the user is viewing the feed
        api.markNotificationsSeen().catch(() => {});
      })
      .catch((e) => setError(e.message));
  }, []);

  const counts = {
    critical: items.filter((i) => i.category === "critical").length,
    warning: items.filter((i) => i.category === "warning").length,
    info: items.filter((i) => i.category === "info").length,
  };

  return (
    <>
      <div className="page-head">
        <h1>Notifications</h1>
        <p>Cross-module alerts — overdue reviews/tests, tolerance breaches, expiring exceptions and gaps.</p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat danger"><div className="stat-top"><span className="n">{counts.critical}</span></div><span className="l">Critical</span></div>
        <div className="card stat warn"><div className="stat-top"><span className="n">{counts.warning}</span></div><span className="l">Warning</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{counts.info}</span></div><span className="l">Info</span></div>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>Alert feed</h3>
          <span className="sub">{items.length} active</span>
        </div>
        <div className="card-pad" style={{ paddingTop: 6, paddingBottom: 6 }}>
          {items.map((n) => (
            <div className="activity-item" key={n.id} style={{ alignItems: "center" }}>
              <Badge tone={TONE[n.category] || "info"}>{n.category}</Badge>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13.5, fontWeight: 550 }}>{n.title}</div>
                <div className="when">{n.body} · {ago(n.created_at)}</div>
              </div>
              {n.link && (
                <Link href={n.link} className="btn secondary sm">View</Link>
              )}
            </div>
          ))}
          {items.length === 0 && (
            <div className="empty">
              <span className="ico"><IconBell width={24} height={24} /></span>
              <h3>All clear</h3>
              <p>No active alerts — nothing overdue, breaching, or gapped right now.</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
