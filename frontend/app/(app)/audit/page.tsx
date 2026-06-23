"use client";

import { useEffect, useState } from "react";
import { api, type AuditEntry } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconActivity } from "@/components/icons";

export default function AuditPage() {
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .audit(100)
      .then((r) => setItems(r.items))
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <div className="page-head">
        <h1>Activity Log</h1>
        <p>Immutable audit trail of changes across the platform.</p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Events</h3>
          <span className="sub">{items.length} recent</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id}>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>
                    {new Date(a.created_at).toLocaleString()}
                  </td>
                  <td className="muted">{a.actor_email}</td>
                  <td><Badge tone="info" plain>{a.action.replace(/_/g, " ")}</Badge></td>
                  <td className="muted">{a.entity_type}</td>
                  <td>{a.summary}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <div className="empty">
                      <span className="ico"><IconActivity width={24} height={24} /></span>
                      <h3>No activity yet</h3>
                      <p>Actions across the platform will appear here.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
