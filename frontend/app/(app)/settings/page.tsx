"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Me, type RiskSetting } from "@/lib/api";
import SecuritySettings from "@/components/SecuritySettings";
import LdapSettings from "@/components/LdapSettings";
import SystemSettings from "@/components/SystemSettings";

type TestState =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "done"; configured: boolean; sent: boolean; recipient: string }
  | { status: "error"; message: string };

const ADMIN_LINKS: { href: string; label: string; desc: string }[] = [
  { href: "/organization", label: "Users & Roles", desc: "Accounts, role permissions, effective access" },
  { href: "/sso-settings", label: "Single Sign-On", desc: "OIDC / OAuth2 identity provider configuration" },
  { href: "/webhooks", label: "Webhooks", desc: "Outbound HMAC-signed event delivery" },
  { href: "/custom-fields", label: "Custom Fields", desc: "Tenant-defined fields per module" },
  { href: "/status-rules", label: "Status Rules", desc: "Dynamic colored status labels" },
  { href: "/filters", label: "Saved Filters", desc: "Reusable advanced query definitions" },
  { href: "/data-io", label: "Import / Export", desc: "CSV bulk data movement for every module" },
  { href: "/audit", label: "Activity Log", desc: "Append-only audit trail of changes" },
];

export default function SettingsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [risk, setRisk] = useState<RiskSetting | null>(null);
  const [test, setTest] = useState<TestState>({ status: "idle" });

  useEffect(() => {
    api.me().then(setMe).catch(() => {});
    api.riskSettings().then(setRisk).catch(() => {});
  }, []);

  async function sendTest() {
    setTest({ status: "sending" });
    try {
      const r = await api.sendTestEmail();
      setTest({ status: "done", configured: r.smtp_configured, sent: r.sent, recipient: r.recipient });
    } catch (e) {
      setTest({ status: "error", message: e instanceof Error ? e.message : "Failed" });
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="sub">Organization configuration, integrations and system health.</p>
        </div>
      </div>

      {/* Organization + system status */}
      <div className="grid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div className="card">
          <div className="card-head"><h3>Organization</h3></div>
          <div className="card-pad">
            <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px", margin: 0, fontSize: 14 }}>
              <dt className="muted">Signed in as</dt><dd>{me?.email ?? "…"}</dd>
              <dt className="muted">Name</dt><dd>{me?.full_name || "—"}</dd>
              <dt className="muted">Roles</dt><dd>{me?.roles.map((r) => r.name).join(", ") || "—"}</dd>
              <dt className="muted">Risk appetite</dt><dd>{risk ? `${risk.appetite_score}` : "…"}</dd>
              <dt className="muted">Risk tolerance</dt><dd>{risk ? `${risk.tolerance_score}` : "…"}</dd>
            </dl>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 12 }}>
              Tune appetite &amp; tolerance thresholds on the <Link href="/risks">Risk Register</Link> settings.
            </p>
          </div>
        </div>

        <div className="card">
          <div className="card-head"><h3>Email &amp; automation</h3></div>
          <div className="card-pad">
            <p style={{ fontSize: 14, marginTop: 0 }}>
              A background scheduler sweeps every tenant on an interval, refreshing overdue/breach
              alerts and emailing digests to active users. Verify outbound email below.
            </p>
            <button className="btn" onClick={sendTest} disabled={test.status === "sending"}>
              {test.status === "sending" ? "Sending…" : "Send test email"}
            </button>
            {test.status === "done" && (
              <div
                className="card card-pad"
                style={{ marginTop: 12, fontSize: 13, background: test.configured ? "var(--green-bg)" : "var(--primary-weak-2)" }}
              >
                {test.configured
                  ? `Sent to ${test.recipient}. Check the inbox.`
                  : `SMTP is not configured, so nothing was delivered — the message was logged server-side. Set SMTP_* environment variables to enable real email to ${test.recipient}.`}
              </div>
            )}
            {test.status === "error" && <div className="error" style={{ marginTop: 12 }}>{test.message}</div>}
          </div>
        </div>
      </div>

      {/* System: version, health, license, backups, support bundle */}
      <SystemSettings />

      {/* Account security: MFA + password */}
      <SecuritySettings />

      {/* Directory authentication */}
      <LdapSettings />

      {/* Admin hub */}
      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-head"><h3>Administration</h3></div>
        <div className="card-pad">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 12 }}>
            {ADMIN_LINKS.map((l) => (
              <Link
                key={l.href}
                href={l.href}
                className="card card-pad"
                style={{ textDecoration: "none", color: "inherit", display: "block" }}
              >
                <div style={{ fontWeight: 600, fontSize: 14 }}>{l.label}</div>
                <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>{l.desc}</div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
