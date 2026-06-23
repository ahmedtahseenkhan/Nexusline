"use client";

import { useEffect, useState } from "react";
import { api, type SsoConfig } from "@/lib/api";
import { Badge } from "@/components/badges";

const ROLES = ["Viewer", "Auditor", "Risk Manager", "Compliance Manager", "Admin"];

export default function SsoSettingsPage() {
  const [cfg, setCfg] = useState<SsoConfig | null>(null);
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.ssoConfig().then(setCfg).catch((e) => setError(e instanceof Error ? e.message : "Load failed"));
  }, []);

  if (!cfg) return <div className="card card-pad">{error ? <div className="error">{error}</div> : "Loading…"}</div>;

  function set<K extends keyof SsoConfig>(k: K, v: SsoConfig[K]) {
    setCfg((c) => (c ? { ...c, [k]: v } : c));
    setSaved(false);
  }

  async function save() {
    setError(null);
    try {
      const payload: Record<string, unknown> = { ...cfg };
      delete payload.client_secret_set;
      if (secret) payload.client_secret = secret;
      else delete payload.client_secret;
      const updated = await api.updateSsoConfig(payload);
      setCfg(updated);
      setSecret("");
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    }
  }

  const field = (label: string, key: keyof SsoConfig, placeholder = "") => (
    <div style={{ marginBottom: 12 }}>
      <label className="label">{label}</label>
      <input className="input" value={String(cfg[key] ?? "")} placeholder={placeholder} onChange={(e) => set(key, e.target.value as never)} />
    </div>
  );

  return (
    <>
      <div className="page-head">
        <h1>Single Sign-On (SSO)</h1>
        <p>Connect an OIDC / OAuth2 identity provider for this organization.</p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card card-pad" style={{ maxWidth: 720 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <label style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 600 }}>
            <input type="checkbox" checked={cfg.enabled} onChange={(e) => set("enabled", e.target.checked)} />
            SSO enabled
          </label>
          {cfg.enabled ? <Badge tone="low">active</Badge> : <Badge tone="neutral">disabled</Badge>}
        </div>

        {field("Client ID", "client_id")}
        <div style={{ marginBottom: 12 }}>
          <label className="label">Client secret {cfg.client_secret_set && <span className="muted">(set — leave blank to keep)</span>}</label>
          <input className="input" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder={cfg.client_secret_set ? "••••••••" : ""} />
        </div>
        {field("Authorize URL", "authorize_url", "https://idp.example.com/authorize")}
        {field("Token URL", "token_url", "https://idp.example.com/token")}
        {field("Userinfo URL", "userinfo_url", "https://idp.example.com/userinfo")}
        {field("Scopes", "scopes")}

        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 150px" }}>{field("Email claim", "email_claim")}</div>
          <div style={{ flex: "1 1 150px" }}>{field("Name claim", "name_claim")}</div>
        </div>

        <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "8px 0 16px" }} />

        <label style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12 }}>
          <input type="checkbox" checked={cfg.jit_provisioning} onChange={(e) => set("jit_provisioning", e.target.checked)} />
          Just-in-time provisioning (auto-create users on first SSO login)
        </label>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 150px", marginBottom: 12 }}>
            <label className="label">Default role for new users</label>
            <select className="input" value={cfg.default_role} onChange={(e) => set("default_role", e.target.value)}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div style={{ flex: "1 1 220px" }}>{field("Allowed email domains (csv)", "allowed_domains", "acme.com")}</div>
        </div>

        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 8 }}>
          <button className="btn" onClick={save}>Save SSO settings</button>
          {saved && <span className="when" style={{ color: "var(--green)" }}>Saved</span>}
        </div>
      </div>
    </>
  );
}
