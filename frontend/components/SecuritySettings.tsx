"use client";

import { useEffect, useState } from "react";
import { api, type Me, type MfaSetup } from "@/lib/api";
// Plain formatter, not useFormat(): this also renders on /mfa-setup, outside the
// organisation-settings provider, where it falls back to the default settings.
import { formatDate } from "@/lib/format";


/** Self-service account security: TOTP MFA enrolment and password change.
 *
 *  `enrolOnly` is the forced-enrolment screen (/mfa-setup): the session can do nothing
 *  but enrol, so the password form and the Disable button are hidden, and `onEnabled`
 *  runs once MFA is active (the caller signs the user out to sign in with the code). */
export default function SecuritySettings({
  enrolOnly = false,
  onEnabled,
}: {
  enrolOnly?: boolean;
  onEnabled?: () => void;
} = {}) {
  const [me, setMe] = useState<Me | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // MFA enrolment
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [code, setCode] = useState("");

  // Password change
  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");

  async function refresh() {
    setMe(await api.me().catch(() => null));
  }
  useEffect(() => {
    refresh();
  }, []);

  const local = (me?.auth_source ?? "local") === "local";
  // The policy requires MFA for this user (privileged role or a checker): no Disable.
  const required = !!me?.mfa_required_for_user;

  async function beginSetup() {
    setErr(null);
    setMsg(null);
    try {
      setSetup(await api.mfaSetup());
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    }
  }
  async function activate() {
    setErr(null);
    try {
      await api.mfaActivate(code);
      setSetup(null);
      setCode("");
      setMsg("Two-factor authentication is now enabled.");
      if (onEnabled) {
        onEnabled();
        return;
      }
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Invalid code");
    }
  }
  async function disable() {
    const c = window.prompt("Enter a current authenticator code to disable MFA:");
    if (!c) return;
    setErr(null);
    try {
      await api.mfaDisable(c);
      setMsg("Two-factor authentication disabled.");
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    }
  }
  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    try {
      await api.changePassword(curPw, newPw);
      setCurPw("");
      setNewPw("");
      setMsg("Password changed.");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    }
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head"><h3>Account security</h3></div>
      <div className="card-pad">
        {msg && <div style={{ background: "var(--green-bg)", color: "var(--green)", border: "1px solid #bfe3cc", borderRadius: 6, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>{msg}</div>}
        {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

        {/* MFA */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <b style={{ fontSize: 14 }}>Two-factor authentication (TOTP)</b>
              <div className="muted" style={{ fontSize: 12.5 }}>
                Status: {me?.mfa_enabled ? <span style={{ color: "var(--green)", fontWeight: 600 }}>Enabled</span> : "Not enabled"}
                {me?.mfa_via_identity_provider && !me?.mfa_enabled && " · Handled by your identity provider when you sign in with single sign-on"}
                {me?.mfa_enforcement === "off" && !me?.mfa_via_identity_provider && " · Optional in your organisation"}
                {required && (
                  <>
                    {" · "}
                    <span style={{ fontWeight: 600 }}>
                      {me?.mfa_required_for_everyone ? "Required for everyone who signs in with a password" : "Required for your role"}
                      {!me?.mfa_enabled && me?.mfa_enrolment_due ? ` from ${formatDate(me.mfa_enrolment_due)}` : ""}
                    </span>
                  </>
                )}
              </div>
            </div>
            {me?.mfa_enabled ? (
              required || enrolOnly ? null : <button className="btn secondary sm" onClick={disable}>Disable</button>
            ) : !setup ? (
              <button className="btn sm" onClick={beginSetup}>Enable MFA</button>
            ) : null}
          </div>

          {setup && !me?.mfa_enabled && (
            <div className="card card-pad" style={{ marginTop: 12, background: "var(--surface-2, #f8fafc)" }}>
              <ol style={{ margin: 0, paddingLeft: 18, fontSize: 13, lineHeight: 1.8 }}>
                <li>In Google/Microsoft Authenticator, add an account and scan or paste this key:</li>
              </ol>
              <div style={{ margin: "10px 0", fontFamily: "monospace", fontSize: 14, wordBreak: "break-all", background: "#fff", border: "1px solid var(--border)", borderRadius: 6, padding: "8px 10px" }}>
                {setup.secret}
              </div>
              <div className="muted" style={{ fontSize: 11.5, marginBottom: 10, wordBreak: "break-all" }}>
                otpauth URI: {setup.otpauth_uri}
              </div>
              <label className="label">Enter the 6-digit code to confirm</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input className="input" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="123456" style={{ maxWidth: 160, letterSpacing: 3 }} />
                <button className="btn sm" onClick={activate} disabled={code.length !== 6}>Confirm & enable</button>
                <button className="btn secondary sm" onClick={() => { setSetup(null); setCode(""); }}>Cancel</button>
              </div>
            </div>
          )}
        </div>

        {/* Password change (local accounts only) — not reachable from an enrol-only session */}
        {!enrolOnly && (
        <div>
          <b style={{ fontSize: 14 }}>Password</b>
          {local ? (
            <form onSubmit={changePassword} style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8, alignItems: "flex-end" }}>
              <div>
                <label className="label">Current</label>
                <input className="input" type="password" value={curPw} onChange={(e) => setCurPw(e.target.value)} style={{ maxWidth: 200 }} />
              </div>
              <div>
                <label className="label">New password</label>
                <input className="input" type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} style={{ maxWidth: 200 }} />
              </div>
              <button className="btn sm" disabled={!curPw || !newPw}>Change password</button>
            </form>
          ) : (
            <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
              This account is managed by your directory (LDAP/AD); change your password there.
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
}
