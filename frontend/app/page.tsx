"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";
import { IconNexus } from "@/components/icons";

export default function LoginPage() {
  const router = useRouter();
  const [tenant, setTenant] = useState("acme");
  const [email, setEmail] = useState("admin@acme.com");
  const [password, setPassword] = useState("ChangeMe123!");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(tenant, email, password);
      setToken(res.access_token);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
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
      const { redirect_url } = await api.ssoLogin(tenant, redirectUri);
      window.location.href = redirect_url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "SSO is not enabled for this organization");
    }
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
          Demo · org <strong>acme</strong> · admin@acme.com / ChangeMe123!
        </p>
      </form>
    </div>
  );
}
