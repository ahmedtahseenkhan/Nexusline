"use client";

/* Settings → Organisation → Security: which roles must use two-factor authentication.
   The server decides (services/mfa_policy.py); this card shows why each role is or isn't
   required, lets an administrator add or remove roles (never Admin), and lists the people
   who must enrol and haven't. */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { Badge } from "@/components/badges";

type Requirement = "everyone" | "protected" | "listed" | "approves" | "not_required";

type RoleRow = {
  name: string;
  is_system: boolean;
  requirement: Requirement;
  listed: boolean;
  locked: boolean;
  approve_permissions: string[];
  active_users: number;
  not_enrolled: number;
};

type PendingUser = {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  status: "required" | "overdue";
  due: string | null;
};

export type SecurityPolicy = {
  mfa_required_for_everyone: boolean;
  grace_days: number;
  deployment_roles: string[];
  organisation_roles: string[] | null;
  effective_roles: string[];
  protected_roles: string[];
  sso_enabled: boolean;
  email_actions_enabled: boolean;
  roles: RoleRow[];
  pending_users: PendingUser[];
  enrolled_users: number;
  required_users: number;
};

const key = (s: string) => s.trim().toLowerCase();

function reasonText(row: RoleRow, toggledOn: boolean): string {
  if (row.requirement === "everyone") return "Required for everyone on this installation";
  if (row.requirement === "protected") return "Always required: administrators can change any setting";
  if (toggledOn) return "Required by your organisation";
  if (row.approve_permissions.length) {
    return `Required anyway: this role can approve (${row.approve_permissions.join(", ")})`;
  }
  return "Not required";
}

export default function MfaPolicySettings({ canEdit }: { canEdit: boolean }) {
  const { formatDate } = useFormat();
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apply = useCallback((p: SecurityPolicy) => {
    setPolicy(p);
    setChosen(new Set(p.effective_roles.map(key)));
  }, []);

  useEffect(() => {
    apiCall<SecurityPolicy>("GET", "/settings/organisation/security")
      .then(apply)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the MFA policy"));
  }, [apply]);

  const saved = useMemo(() => new Set((policy?.effective_roles ?? []).map(key)), [policy]);
  const dirty = useMemo(
    () => chosen.size !== saved.size || Array.from(chosen).some((r) => !saved.has(r)),
    [chosen, saved],
  );

  function toggle(row: RoleRow) {
    if (row.locked) return;
    setChosen((prev) => {
      const next = new Set(prev);
      if (next.has(key(row.name))) next.delete(key(row.name));
      else next.add(key(row.name));
      return next;
    });
  }

  async function save(roles: string[] | null) {
    setBusy(true);
    setError(null);
    try {
      apply(await apiCall<SecurityPolicy>("PUT", "/settings/organisation/security/mfa-roles", { required_roles: roles }));
      toast(roles === null ? "MFA roles reset to the installation default" : "MFA roles saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the MFA roles");
    } finally {
      setBusy(false);
    }
  }

  const chosenNames = () => (policy?.roles ?? []).filter((r) => chosen.has(key(r.name))).map((r) => r.name);

  return (
    <div className="card" id="mfa">
      <div className="card-head">
        <h3>Multi-factor authentication</h3>
        {policy && (
          <span className="sub">
            {policy.enrolled_users} enrolled · {policy.pending_users.length} still to enrol
          </span>
        )}
      </div>
      <div className="card-pad">
        {error && <div className="error" style={{ marginBottom: 12 }}>{error}</div>}
        {!policy ? (
          !error && <p className="muted">Loading…</p>
        ) : (
          <>
            <p style={{ marginTop: 0, fontSize: 13.5 }}>
              People in the roles switched on below must set up an authenticator app. Anyone who can approve
              something must use it too, whatever their role, because approving is the step segregation of duties
              protects. The Admin role can&apos;t be switched off.
            </p>
            <ul className="muted" style={{ fontSize: 12.5, margin: "0 0 14px", paddingLeft: 18, lineHeight: 1.7 }}>
              <li>
                Grace period: {policy.grace_days} day{policy.grace_days === 1 ? "" : "s"} from the first sign-in after MFA
                becomes required. After that the person can only set up MFA until they do.
              </li>
              {policy.sso_enabled && (
                <li>
                  Single sign-on: people who sign in through your identity provider aren&apos;t asked again here —
                  handled by your identity provider. The rules below apply to password and Active Directory sign-ins.
                </li>
              )}
              <li>
                Approve / Reject links in e-mail:{" "}
                {policy.email_actions_enabled
                  ? "on. They let a checker decide without signing in, so without MFA — your installation has chosen to allow this."
                  : "off, so checkers sign in (with MFA) to decide."}
              </li>
              {policy.organisation_roles === null && (
                <li>Using this installation&apos;s default list ({policy.deployment_roles.join(", ") || "none"}).</li>
              )}
            </ul>

            {policy.mfa_required_for_everyone && (
              <div className="card card-pad" style={{ marginBottom: 12, fontSize: 13, background: "var(--primary-weak-2)" }}>
                This installation requires MFA for everyone who signs in with a password, so every role is required.
              </div>
            )}

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Role</th>
                    <th>Require MFA</th>
                    <th>Why</th>
                    <th style={{ textAlign: "right" }}>Active users</th>
                    <th style={{ textAlign: "right" }}>Not enrolled</th>
                  </tr>
                </thead>
                <tbody>
                  {policy.roles.map((row) => {
                    const on = row.locked || chosen.has(key(row.name));
                    const effective = on || row.requirement === "approves";
                    return (
                      <tr key={row.name}>
                        <td className="cell-title">
                          {row.name}
                          {!row.is_system && <span className="muted" style={{ fontSize: 12, marginLeft: 6 }}>custom</span>}
                        </td>
                        <td>
                          <label
                            className="switch"
                            title={row.locked ? "Can't be switched off" : undefined}
                            style={!canEdit || row.locked ? { opacity: 0.6, cursor: "not-allowed" } : undefined}
                          >
                            <input
                              type="checkbox"
                              checked={on}
                              disabled={!canEdit || row.locked || busy}
                              onChange={() => toggle(row)}
                              aria-label={`Require MFA for ${row.name}`}
                            />
                            <span className="track" />
                          </label>
                        </td>
                        <td className="muted" style={{ fontSize: 12.5 }}>
                          {effective && !on && <Badge tone="info" plain>Implicit</Badge>} {reasonText(row, on)}
                        </td>
                        <td style={{ textAlign: "right" }}>{row.active_users}</td>
                        <td style={{ textAlign: "right" }}>
                          {row.not_enrolled > 0 ? <Badge tone="medium">{row.not_enrolled}</Badge> : <span className="muted">0</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {canEdit && (
              <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
                <button className="btn" disabled={busy || !dirty} onClick={() => save(chosenNames())}>
                  {busy ? "Saving…" : "Save MFA roles"}
                </button>
                {dirty && (
                  <button className="btn secondary" disabled={busy} onClick={() => setChosen(new Set(saved))}>
                    Discard changes
                  </button>
                )}
                {policy.organisation_roles !== null && (
                  <button className="btn secondary" disabled={busy} onClick={() => save(null)}>
                    Use installation default
                  </button>
                )}
                <span className="muted" style={{ fontSize: 12.5 }}>Every change is written to the activity log.</span>
              </div>
            )}

            <h4 style={{ margin: "20px 0 8px" }}>Required but not enrolled</h4>
            {policy.pending_users.length === 0 ? (
              <p className="muted" style={{ margin: 0, fontSize: 13 }}>Everyone who must use MFA has set it up.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Roles</th>
                      <th>Must enrol by</th>
                    </tr>
                  </thead>
                  <tbody>
                    {policy.pending_users.map((u) => (
                      <tr key={u.id}>
                        <td>
                          <Link href={`/organization?id=${u.id}`} className="cell-title">{u.full_name || u.email}</Link>
                          {u.full_name && <div className="muted" style={{ fontSize: 12 }}>{u.email}</div>}
                        </td>
                        <td className="muted" style={{ fontSize: 12.5 }}>{u.roles.join(", ") || "—"}</td>
                        <td>
                          {u.status === "overdue" ? (
                            <Badge tone="high" asIs>Overdue since {formatDate(u.due)}</Badge>
                          ) : u.due ? (
                            formatDate(u.due)
                          ) : (
                            <span className="muted" style={{ fontSize: 12.5 }}>
                              {policy.grace_days} days after their next sign-in
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
