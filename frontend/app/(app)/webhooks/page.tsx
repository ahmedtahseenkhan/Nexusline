"use client";

import { useCallback, useState } from "react";
import { api, apiCall, type Webhook, type WebhookDelivery } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

export default function WebhooksPage() {
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState("*");
  const [secret, setSecret] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([]);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchWebhooks = useCallback((qs: string) => apiCall<PagedList<Webhook>>("GET", `/webhooks?${qs}`), []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createWebhook({ name, url, events, secret });
      setName(""); setUrl(""); setEvents("*"); setSecret(""); setShowForm(false);
      reload();
      toast("Webhook created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }

  async function toggle(h: Webhook) {
    try {
      await api.updateWebhook(h.id, { enabled: !h.enabled });
      reload();
      toast(h.enabled ? "Webhook disabled" : "Webhook enabled");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  }
  async function test(h: Webhook) {
    setError(null);
    try {
      await api.testWebhook(h.id);
      reload();
      if (openId === h.id) setDeliveries(await api.webhookDeliveries(h.id));
      toast("Test event sent");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test failed");
    }
  }
  async function remove(h: Webhook) {
    if (!(await confirmDialog({ title: `Delete webhook "${h.name}"?`, danger: true }))) return;
    try {
      await api.deleteWebhook(h.id);
      if (openId === h.id) setOpenId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }
  async function openDeliveries(h: Webhook) {
    if (openId === h.id) { setOpenId(null); return; }
    setOpenId(h.id);
    setDeliveries(await api.webhookDeliveries(h.id).catch(() => []));
  }

  const columns: Column<Webhook>[] = [
    { key: "name", header: "Name", sortable: true, render: (h) => <span className="cell-title">{h.name}</span> },
    { key: "url", header: "URL", sortable: true, render: (h) => <span className="muted" style={{ display: "inline-block", maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", verticalAlign: "bottom" }}>{h.url}</span> },
    { key: "events", header: "Events", render: (h) => <code style={{ fontSize: 12 }}>{h.events}</code> },
    { key: "status", header: "Status", render: (h) => (h.enabled ? <Badge tone="low">enabled</Badge> : <Badge tone="neutral">disabled</Badge>) },
    { key: "last_status", header: "Last", sortable: true, render: (h) => (h.last_status ? <Badge tone={h.last_status < 300 ? "low" : "high"}>{h.last_status}</Badge> : <span className="muted">—</span>) },
    {
      key: "actions", header: "", render: (h) => (
        <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => test(h)}>Test</button>
          <button className="btn secondary sm" onClick={() => toggle(h)}>{h.enabled ? "Disable" : "Enable"}</button>
          <button className="btn secondary sm" onClick={() => openDeliveries(h)}>{openId === h.id ? "Hide" : "Log"}</button>
          <button className="btn secondary sm" onClick={() => remove(h)}>Delete</button>
        </div>
      ),
    },
  ];

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

      <DataTable<Webhook>
        columns={columns}
        fetcher={fetchWebhooks}
        rowKey={(h) => h.id}
        searchPlaceholder="Search webhooks by name or URL…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No webhooks yet. Add one to start streaming events."
        refreshKey={refreshKey}
      />

      {openId && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-head"><h3>Recent deliveries</h3><span className="sub">last 50 · newest first</span></div>
          <div className="card-pad">
            {deliveries.length === 0 && <span className="muted" style={{ fontSize: 12 }}>none yet</span>}
            {deliveries.map((d) => (
              <div key={d.id} style={{ display: "flex", gap: 10, fontSize: 12, marginTop: 4, alignItems: "center" }}>
                <Badge tone={d.success ? "low" : "high"}>{d.success ? "ok" : "fail"}</Badge>
                <code>{d.event}</code>
                <span className="muted">{d.status_code ?? (d.error || "no response")}</span>
                <span className="muted" style={{ marginLeft: "auto" }}>{new Date(d.created_at).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
