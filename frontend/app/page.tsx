"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { landingPath, markLanded, rememberNext, safeNext, takeNext } from "@/lib/landing";
import { IconNexus } from "@/components/icons";

export default function LoginPage() {
  const router = useRouter();
  const [tenant, setTenant] = useState("acme");
  const [email, setEmail] = useState("admin@acme.com");
  const [password, setPassword] = useState("ChangeMe123!");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [challenge, setChallenge] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  // Arriving from forced MFA enrolment: say what happens next.
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("mfa") === "enabled") {
      setNotice("Two-factor authentication is on. Sign in again and enter a code from your authenticator app.");
    }
  }, []);

  /** Where to go once signed in: the link that sent you here (an e-mailed alert),
   *  else My Work for most people and the dashboard (or first-run setup) for admins. */
  async function afterSignIn() {
    const remembered = takeNext(); // always consumed, so it can't fire on a later sign-in
    const next = safeNext(new URLSearchParams(window.location.search).get("next")) ?? remembered;
    if (next) {
      markLanded();
      router.push(next);
      return;
    }
    try {
      const path = await landingPath(await api.me());
      markLanded();
      router.push(path);
    } catch {
      router.push("/dashboard");
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(tenant, email, password);
      if (res.mfa_required && res.challenge_token) {
        setChallenge(res.challenge_token);
      } else if (res.access_token && res.mfa_enrolment_required) {
        // Grace period over: this token can only enrol in MFA.
        setToken(res.access_token);
        router.push("/mfa-setup");
      } else if (res.access_token) {
        // Inside a grace period the app shell shows the "MFA required from …" banner.
        setToken(res.access_token);
        await afterSignIn();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function onVerifyMfa(e: React.FormEvent) {
    e.preventDefault();
    if (!challenge) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.mfaVerify(challenge, code);
      setToken(res.access_token);
      await afterSignIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid code");
    } finally {
      setLoading(false);
    }
  }

  async function ssoSignIn() {
    setError(null);
    try {
      const redirectUri = `${window.location.origin}/sso/callback`;
      window.localStorage.setItem("sso_slug", tenant);
      window.localStorage.setItem("sso_redirect_uri", redirectUri);
      // SSO leaves this page: keep the deep link for the app shell to open on return.
      const next = safeNext(new URLSearchParams(window.location.search).get("next"));
      if (next) rememberNext(next);
      const { redirect_url } = await api.ssoLogin(tenant, redirectUri);
      window.location.href = redirect_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "SSO is not enabled for this organization");
    }
  }

  if (challenge) {
    return (
      <div className="login-wrap">
        <form className="login-card" onSubmit={onVerifyMfa}>
          <div className="login-logo">
            <span className="logo"><IconNexus width={19} height={19} /></span>
            <span className="wordmark">Nexus<span style={{ color: "var(--primary-text)" }}>Line</span></span>
          </div>
          <h1>Two-factor authentication</h1>
          <p className="sub">Enter the 6-digit code from your authenticator app.</p>

          <label className="label">Authentication code</label>
          <input
            className="input"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoFocus
            placeholder="123456"
            style={{ letterSpacing: 4, fontSize: 18, textAlign: "center" }}
          />

          {error && <div className="error">{error}</div>}

          <button className="btn" style={{ width: "100%", justifyContent: "center", marginTop: 20 }} disabled={loading || code.length !== 6}>
            {loading ? "Verifying…" : "Verify"}
          </button>
          <button type="button" className="btn secondary" style={{ width: "100%", justifyContent: "center", marginTop: 10 }} onClick={() => { setChallenge(null); setCode(""); setError(null); }}>
            Back
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="login-logo">
          <span className="logo">
            <IconNexus width={19} height={19} />
          </span>
          <span className="wordmark">Nexus<span style={{ color: "var(--primary-text)" }}>Line</span></span>
        </div>
        <h1>Welcome back</h1>
        <p className="sub">Sign in to your governance workspace.</p>
        {notice && (
          <div role="status" style={{ background: "var(--green-bg)", color: "var(--green)", border: "1px solid #bfe3cc", borderRadius: 6, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>
            {notice}
          </div>
        )}

        <label className="label">Organization</label>
        <input className="input" value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="org-slug" />

        <label className="label">Email</label>
        <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />

        <label className="label">Password</label>
        <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />

        {error && <div className="error">{error}</div>}

        <button className="btn" style={{ width: "100%", justifyContent: "center", marginTop: 20 }} disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </button>

        <button type="button" className="btn secondary" style={{ width: "100%", justifyContent: "center", marginTop: 10 }} onClick={ssoSignIn}>
          Sign in with SSO
        </button>

        <p className="hint">
          Demo · org <strong>acme</strong> · admin@acme.com / ChangeMe123! (checker) ·
          ayesha.siddiqui@acme.com, same password (maker)
        </p>
      </form>
    </div>
  );
}
