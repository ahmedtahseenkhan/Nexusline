"use client";

import { useEffect, useState } from "react";
import { api, type SystemInfo, type SystemHealth, type BackupItem, type ModuleState } from "@/lib/api";
import { Badge } from "@/components/badges";

function fmtBytes(n: number) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

/** On-prem System admin: version, health, license status, backups, support bundle. */
export default function SystemSettings() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    setInfo(await api.systemInfo().catch(() => null));
    setHealth(await api.systemHealth().catch(() => null));
    setBackups(await api.listBackups().catch(() => []));
    setModules(await api.systemModules().catch(() => []));
  }
  useEffect(() => {
    load();
  }, []);

  async function backupNow() {
    setBusy("backup");
    setErr(null);
    setMsg(null);
    try {
      const b = await api.createBackup();
      setMsg(`Backup created: ${b.filename} (${fmtBytes(b.size_bytes)}).`);
      setBackups(await api.listBackups().catch(() => backups));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Backup failed");
    } finally {
      setBusy(null);
    }
  }
  async function supportBundle() {
    setBusy("bundle");
    setErr(null);
    try {
      await api.downloadSupportBundle();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Download failed");
    } finally {
      setBusy(null);
    }
  }

  const lic = info?.license;
  const licTone = lic?.valid ? "low" : lic?.status === "expired" ? "critical" : "neutral";

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3>System</h3>
        {info && <span className="sub">v{info.app_version} · {info.deployment_mode} · {info.environment}</span>}
      </div>
      <div className="card-pad">
        {msg && <div style={{ background: "var(--green-bg)", color: "var(--green)", border: "1px solid #bfe3cc", borderRadius: 6, padding: "8px 12px", fontSize: 13, marginBottom: 12 }}>{msg}</div>}
        {err && <div className="error" style={{ marginBottom: 12 }}>{err}</div>}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {/* Health */}
          <div>
            <b style={{ fontSize: 14 }}>Health</b>
            <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
              {health ? (
                Object.entries(health.checks).map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
                    <span className="muted">{k.replace(/_/g, " ")}</span>
                    <Badge tone={v.ok ? "low" : "critical"}>{v.ok ? "ok" : "fail"}</Badge>
                  </div>
                ))
              ) : (
                <span className="muted" style={{ fontSize: 13 }}>Loading…</span>
              )}
            </div>
          </div>

          {/* License */}
          <div>
            <b style={{ fontSize: 14 }}>License</b>
            <div style={{ marginTop: 8, fontSize: 13, display: "flex", flexDirection: "column", gap: 4 }}>
              <div><Badge tone={licTone}>{lic?.status ?? "…"}</Badge></div>
              {lic?.licensed_to && <div className="muted">Licensed to <b>{lic.licensed_to}</b></div>}
              {lic?.plan && <div className="muted">Plan: {lic.plan} · {lic.seats} seats</div>}
              {lic?.expires && <div className="muted">Expires: {lic.expires}</div>}
              {lic?.features?.length ? <div className="muted">Features: {lic.features.join(", ")}</div> : null}
              {lic && !lic.valid && <div className="muted">{lic.message}</div>}
            </div>
          </div>
        </div>

        {/* Module entitlements: what the license includes and what config hides */}
        {modules.length > 0 && (
          <div style={{ marginTop: 18 }}>
            <b style={{ fontSize: 14 }}>Modules</b>
            <p className="muted" style={{ fontSize: 12, margin: "4px 0 8px" }}>
              Enabled by the installation license; hidden modules can be unlocked with a license
              update — no reinstall needed. <code>DISABLED_MODULES</code> in the deploy config hides
              licensed modules.
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 6 }}>
              {modules.map((m) => (
                <div key={m.key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, fontSize: 13, border: "1px solid var(--border, #e5e7eb)", borderRadius: 6, padding: "6px 10px" }}>
                  <span title={m.description}>
                    {m.title}
                    <span className="muted" style={{ display: "block", fontSize: 11 }}>{m.category}</span>
                  </span>
                  <Badge tone={m.enabled ? "low" : "neutral"}>
                    {m.enabled ? "on" : m.licensed ? "hidden" : "unlicensed"}
                  </Badge>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, marginTop: 18, flexWrap: "wrap" }}>
          <button className="btn sm" onClick={backupNow} disabled={busy !== null}>
            {busy === "backup" ? "Backing up…" : "Back up database now"}
          </button>
          <button className="btn secondary sm" onClick={supportBundle} disabled={busy !== null}>
            {busy === "bundle" ? "Preparing…" : "Download support bundle"}
          </button>
        </div>

        {/* Backups list */}
        {backups.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 14 }}>
            <table>
              <thead><tr><th>Backup</th><th>Size</th><th>Created</th></tr></thead>
              <tbody>
                {backups.slice(0, 8).map((b) => (
                  <tr key={b.filename}>
                    <td className="ref">{b.filename}</td>
                    <td className="muted">{fmtBytes(b.size_bytes)}</td>
                    <td className="muted">{new Date(b.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 12 }}>
          The support bundle redacts all secrets — send it to support without granting remote access.
          Restore a backup with <code>pg_restore</code> (see the deployment runbook).
        </p>
      </div>
    </div>
  );
}
