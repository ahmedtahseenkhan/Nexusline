"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "@/lib/api";

export default function SsoCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const slug = window.localStorage.getItem("sso_slug") || "";
    const redirect_uri = window.localStorage.getItem("sso_redirect_uri") || `${window.location.origin}/sso/callback`;
    if (!code || !state || !slug) {
      setError("Missing SSO parameters. Please start sign-in again.");
      return;
    }
    api
      .ssoCallback(slug, { code, state, redirect_uri })
      .then((res) => {
        setToken(res.access_token);
        router.push("/dashboard");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "SSO sign-in failed"));
  }, [router]);

  return (
    <div className="login-wrap">
      <div className="login-card" style={{ textAlign: "center" }}>
        <h1>{error ? "Sign-in failed" : "Completing sign-in…"}</h1>
        {error ? (
          <>
            <div className="error">{error}</div>
            <button className="btn" style={{ width: "100%", justifyContent: "center", marginTop: 16 }} onClick={() => router.push("/")}>
              Back to sign in
            </button>
          </>
        ) : (
          <p className="sub">Verifying your identity with the provider.</p>
        )}
      </div>
    </div>
  );
}
