"use client";

import { useEffect, useState } from "react";
import { api, type LdapConfig } from "@/lib/api";

const BLANK: LdapConfig = {
  enabled: false, host: "", port: 389, use_ssl: false, start_tls: true,
  bind_dn: "", base_dn: "", user_filter: "(userPrincipalName={username})",
  email_attribute: "mail", name_attribute: "displayName", default_role: "Viewer",
  bind_password_set: false,
};

/** Admin: LDAP / Active Directory connection for directory login + JIT provisioning. */
export default function LdapSettings() {
  const [cfg, setCfg] = useState<LdapConfig>(BLANK);
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    api.ldapConfig().then((c) => { setCfg(c); setLoaded(true); }).catch(() => setLoaded(true));
  }, []);

  function set<K extends keyof LdapConfig>(k: K, v: LdapConfig[K]) {
    setCfg((c) => ({ ...c, [k]: v }));
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    try {
      const payload: Record<string, unknown> = { ...cfg };
      delete payload.bind_password_set;
      if (password) payload.bind_password = password; // only send when changed
      const saved = await api.saveLdapConfig(payload);
      setCfg(saved);
      setPassword("");
      setMsg("LDAP configuration saved.");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Failed to save");
    }
  }

  if (!loaded) return null;

  const F = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div style={{ flex: "1 1 220px" }}>
      <label className="label">{label}</label>
      {children}
    </div>
  );

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3>LDAP / Active Directory</h3>
        <span className="sub">{cfg.enabled ? "Enabled" : "Disabled"}</span>
      </div>
      <form className="card-pad" onSubmit={save}>
        {msg && <div style={{ background: "var(--green-bg)", color: "var(--green)", border: "1px solid #bfe3cc", borderRadius: 6, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>{msg}</div>}
        {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 14, marginBottom: 14 }}>
          <input type="checkbox" checked={cfg.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          Enable directory authentication for this organization
        </label>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <F label="Host"><input className="input" value={cfg.host} onChange={(e) => set("host", e.target.value)} placeholder="ldap.bank.local" /></F>
          <F label="Port"><input className="input" type="number" value={cfg.port} onChange={(e) => set("port", Number(e.target.value))} /></F>
          <F label="Default role (JIT users)"><input className="input" value={cfg.default_role} onChange={(e) => set("default_role", e.target.value)} /></F>
        </div>

        <div style={{ display: "flex", gap: 16, margin: "10px 0" }}>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={cfg.use_ssl} onChange={(e) => set("use_ssl", e.target.checked)} /> LDAPS (SSL)
          </label>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
            <input type="checkbox" checked={cfg.start_tls} onChange={(e) => set("start_tls", e.target.checked)} /> StartTLS
          </label>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <F label="Bind DN (service account)"><input className="input" value={cfg.bind_dn} onChange={(e) => set("bind_dn", e.target.value)} placeholder="CN=svc,OU=Service,DC=bank,DC=local" /></F>
          <F label={`Bind password ${cfg.bind_password_set ? "(set — leave blank to keep)" : ""}`}>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={cfg.bind_password_set ? "••••••••" : ""} />
          </F>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
          <F label="Base DN (user search)"><input className="input" value={cfg.base_dn} onChange={(e) => set("base_dn", e.target.value)} placeholder="DC=bank,DC=local" /></F>
          <F label="User filter"><input className="input" value={cfg.user_filter} onChange={(e) => set("user_filter", e.target.value)} /></F>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
          <F label="Email attribute"><input className="input" value={cfg.email_attribute} onChange={(e) => set("email_attribute", e.target.value)} /></F>
          <F label="Name attribute"><input className="input" value={cfg.name_attribute} onChange={(e) => set("name_attribute", e.target.value)} /></F>
        </div>

        <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          <code>{"{username}"}</code> in the filter is replaced with the login value. Users who pass
          directory bind are provisioned automatically with the default role.
        </p>
        <button className="btn" style={{ marginTop: 8 }}>Save LDAP configuration</button>
      </form>
    </div>
  );
}
