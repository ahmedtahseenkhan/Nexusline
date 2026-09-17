"use client";

/* Settings → Organisation → Security: is maker-checker actually workable here? Shows the
   approval routes every organisation starts with, whether anyone holds the roles their
   stages are assigned to, the dual-control rules in force, and the one-user problem.
   Read from GET /settings/organisation/governance (services/default_governance.py). */

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";

export type GovernanceStatus = {
  sod_enforced: boolean;
  active_users: number;
  needs_second_user: boolean;
  second_user_message: string | null;
  routes: {
    id: string;
    entity_type: string;
    name: string;
    enabled: boolean;
    stages: { name: string; role: string | null; holders: number | null }[];
  }[];
  rules_total: number;
  rules_enabled: number;
  role_gaps: { role: string; routes: string[]; message: string }[];
};

export function loadGovernanceStatus(): Promise<GovernanceStatus> {
  return apiCall<GovernanceStatus>("GET", "/settings/organisation/governance");
}

export default function SegregationOfDutiesSettings() {
  const [status, setStatus] = useState<GovernanceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadGovernanceStatus()
      .then(setStatus)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load segregation of duties"));
  }, []);

  return (
    <div className="card" id="segregation-of-duties">
      <div className="card-head">
        <h3>Segregation of duties</h3>
        {status && (
          <span className="sub">
            {status.sod_enforced ? "Enforced" : "Not enforced on this installation"} · {status.active_users} active user
            {status.active_users === 1 ? "" : "s"}
          </span>
        )}
      </div>
      <div className="card-pad">
        {error && <div className="error">{error}</div>}
        {!status ? (
          !error && <p className="muted">Loading…</p>
        ) : (
          <>
            <p style={{ marginTop: 0, fontSize: 13.5 }}>
              The person who enters or submits something can never be the one who approves it. Records submitted for
              review follow the approval routes below; every other two-person step is set by a dual-control rule.
            </p>

            {status.needs_second_user && (
              <div className="card card-pad" style={{ marginBottom: 12, fontSize: 13, background: "var(--amber-bg)", color: "var(--amber)" }}>
                {status.second_user_message}{" "}
                <Link href="/organization" style={{ fontWeight: 600 }}>Invite a user</Link>
              </div>
            )}
            {!status.sod_enforced && (
              <div className="card card-pad" style={{ marginBottom: 12, fontSize: 13, background: "var(--primary-weak-2)" }}>
                This installation has segregation of duties switched off (ENFORCE_SEGREGATION_OF_DUTIES=false), so
                rules are kept but not applied unless enabled one by one.
              </div>
            )}
            {status.role_gaps.map((gap) => (
              <div key={gap.role} className="card card-pad" style={{ marginBottom: 12, fontSize: 13, background: "var(--amber-bg)", color: "var(--amber)" }}>
                {gap.message} Used by: {gap.routes.join(", ")}.{" "}
                <Link href="/organization" style={{ fontWeight: 600 }}>Open Users</Link>
              </div>
            ))}

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Approval route</th>
                    <th>Record</th>
                    <th>Decided by</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {status.routes.length === 0 && (
                    <tr>
                      <td colSpan={4} className="muted">No approval routes. Records are approved directly on the record.</td>
                    </tr>
                  )}
                  {status.routes.map((r) => (
                    <tr key={r.id}>
                      <td className="cell-title">{r.name}</td>
                      <td className="muted">{r.entity_type.replace(/_/g, " ")}</td>
                      <td style={{ fontSize: 12.5 }}>
                        {r.stages.map((s, i) => (
                          <div key={`${s.name}-${i}`}>
                            {s.name}
                            {s.role && (
                              <span className="muted">
                                {" "}— {s.role}:{" "}
                                {s.holders ? `${s.holders} ${s.holders === 1 ? "person" : "people"}` : <Badge tone="medium" asIs>No one holds it</Badge>}
                              </span>
                            )}
                          </div>
                        ))}
                      </td>
                      <td>{r.enabled ? <Badge tone="low">On</Badge> : <Badge tone="neutral">Off</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ fontSize: 12.5, margin: "12px 0 0" }}>
              {status.rules_enabled} of {status.rules_total} dual-control rules are on.{" "}
              <Link href="/workflows">Edit approval routes</Link> · <Link href="/delegation-of-authority">Edit dual-control rules</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
