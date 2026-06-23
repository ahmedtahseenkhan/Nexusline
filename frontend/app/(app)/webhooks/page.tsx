"use client";

import { Fragment, useEffect, useState } from "react";
import { api, type Webhook, type WebhookDelivery } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

export default function WebhooksPage() {
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState("*");
  const [secret, setSecret] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([]);

  async function load() {
    try {
      setHooks(await api.webhooks());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createWebhook({ name, url, events, secret });
      setName(""); setUrl(""); setEvents("*"); setSecret(""); setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }

  async function toggle(h: Webhook) {
    await api.updateWebhook(h.id, { enabled: !h.enabled }).catch(() => {});
    await load();
  }
  async function test(h: Webhook) {
    setError(null);
    try {
      await api.testWebhook(h.id);
      await load();
      if (openId === h.id) setDeliveries(await api.webhookDeliveries(h.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test failed");
    }
  }
  async function remove(id: string) {
    await api.deleteWebhook(id).catch(() => {});
    if (openId === id) setOpenId(null);
    await load();
  }
  async function openDeliveries(h: Webhook) {
    if (openId === h.id) { setOpenId(null); return; }
    setOpenId(h.id);
    setDeliveries(await api.webhookDeliveries(h.id).catch(() => []));
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Webhooks</h1>
          <p>Fire outbound HTTP events to SIEMs, ticketing or chat when records change.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} /> {showForm ? "Close" : "New webhook"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Name</label>
              <input className="input" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Security SIEM" />
            </div>
            <div style={{ flex: "2 1 320px" }}>
              <label className="label">Payload URL</label>
              <input className="input" required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://hooks.example.com/nexusline" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12 }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Events (csv of types, or *)</label>
              <input className="input" value={events} onChange={(e) => setEvents(e.target.value)} placeholder="risk,incident,approval" />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Signing secret (optional)</label>
              <input className="input" value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="HMAC SHA-256 secret" />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create webhook</button>
        </form>
      )}

      <div className="card">
        <div className="card-head"><h3>Endpoints</h3><span className="sub">{hooks.length} configured</span></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Name</th><th>URL</th><th>Events</th><th>Status</th><th>Last</th><th></th></tr></thead>
            <tbody>
              {hooks.map((h) => (
                <Fragment key={h.id}>
                  <tr>
                    <td className="cell-title">{h.name}</td>
                    <td className="muted" style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.url}</td>
                    <td><code style={{ fontSize: 12 }}>{h.events}</code></td>
                    <td>{h.enabled ? <Badge tone="low">enabled</Badge> : <Badge tone="neutral">disabled</Badge>}</td>
                    <td className="muted">{h.last_status ? <Badge tone={h.last_status < 300 ? "low" : "high"}>{h.last_status}</Badge> : "—"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn secondary sm" onClick={() => test(h)}>Test</button>
                        <button className="btn secondary sm" onClick={() => toggle(h)}>{h.enabled ? "Disable" : "Enable"}</button>
                        <button className="btn secondary sm" onClick={() => openDeliveries(h)}>{openId === h.id ? "Hide" : "Log"}</button>
                        <button className="btn secondary sm" onClick={() => remove(h.id)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                  {openId === h.id && (
                    <tr>
                      <td colSpan={6} style={{ background: "var(--surface-2, #f8fafc)" }}>
                        <div style={{ padding: "4px 2px" }}>
                          <b style={{ fontSize: 12 }}>Recent deliveries</b>
                          {deliveries.length === 0 && <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>none yet</span>}
                          {deliveries.map((d) => (
                            <div key={d.id} style={{ display: "flex", gap: 10, fontSize: 12, marginTop: 4, alignItems: "center" }}>
                              <Badge tone={d.success ? "low" : "high"}>{d.success ? "ok" : "fail"}</Badge>
                              <code>{d.event}</code>
                              <span className="muted">{d.status_code ?? (d.error || "no response")}</span>
                              <span className="muted" style={{ marginLeft: "auto" }}>{new Date(d.created_at).toLocaleString()}</span>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {hooks.length === 0 && <tr><td colSpan={6}><div className="empty"><h3>No webhooks</h3><p>Add one to start streaming events.</p></div></td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
