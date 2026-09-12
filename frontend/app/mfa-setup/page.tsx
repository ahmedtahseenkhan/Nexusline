"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearToken, getToken, type Me } from "@/lib/api";
import SecuritySettings from "@/components/SecuritySettings";
import { IconNexus } from "@/components/icons";
// Plain formatter: this page renders outside the app shell's organisation-settings
// provider (the enrol-only token can't read them), so it uses the default settings.
import { formatDate } from "@/lib/format";

/** Forced MFA enrolment. Reached after sign-in once the grace period for a user who must
 *  use two-factor authentication has passed: the session token is enrol-only, so the
 *  normal app shell (which calls many endpoints) is not used here. Once MFA is on, the
 *  user signs in again — this time with a code — to get a full session. */
export default function MfaSetupPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    api
      .me()
      .then((u) => {
        if (!u.mfa_enrolment_required) {
          router.replace("/dashboard");
          return;
        }
        setMe(u);
      })
      .catch(() => router.replace("/"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function signOut(query = "") {
    clearToken();
    router.replace(`/${query}`);
  }

  if (!me) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <span className="muted">Loading…</span>
      </div>
    );
  }

  return (
    <div className="login-wrap">
      <div style={{ width: "100%", maxWidth: 620, padding: "0 16px" }}>
        <div className="login-logo" style={{ marginBottom: 12 }}>
          <span className="logo"><IconNexus width={19} height={19} /></span>
          <span className="wordmark">Nexus<span style={{ color: "var(--primary-text)" }}>Line</span></span>
        </div>
        <h1 style={{ marginBottom: 6 }}>Set up two-factor authentication</h1>
        <p className="muted" style={{ fontSize: 14, lineHeight: 1.6 }}>
          Your role can approve or administer records, so your organisation requires a second
          factor for {me.email}. The grace period
          {me.mfa_enrolment_due ? ` ended on ${formatDate(me.mfa_enrolment_due)}` : " has ended"}
          ; until you enrol, this session can do nothing else. Add NexusLine to an
          authenticator app, confirm a code, then sign in again with it.
        </p>
        <SecuritySettings enrolOnly onEnabled={() => signOut("?mfa=enabled")} />
        <button type="button" className="btn secondary" style={{ marginTop: 14 }} onClick={() => signOut()}>
          Sign out
        </button>
      </div>
    </div>
  );
}
