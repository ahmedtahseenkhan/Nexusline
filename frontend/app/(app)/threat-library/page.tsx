"use client";

import { useEffect, useState } from "react";
import { api, type CatalogItem } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus, IconRisk } from "@/components/icons";

function Catalog({
  title,
  subtitle,
  items,
  onCreate,
}: {
  title: string;
  subtitle: string;
  items: CatalogItem[];
  onCreate: (name: string, category: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [showForm, setShowForm] = useState(false);

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>{title}</h3>
          <span className="sub">{subtitle}</span>
        </div>
        <button className="btn sm" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={14} height={14} /> Add
        </button>
      </div>
      {showForm && (
        <form
          className="card-pad"
          style={{ display: "flex", gap: 8, alignItems: "flex-end", borderBottom: "1px solid var(--border)" }}
          onSubmit={async (e) => {
            e.preventDefault();
            if (!name) return;
            await onCreate(name, category);
            setName("");
            setCategory("");
            setShowForm(false);
          }}
        >
          <div style={{ flex: 1 }}>
            <label className="label">Name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div style={{ width: 160 }}>
            <label className="label">Category</label>
            <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} />
          </div>
          <button className="btn">Add</button>
        </form>
      )}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Category</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td className="cell-title">{i.name}</td>
                <td>{i.category ? <Badge tone="info" plain>{i.category}</Badge> : <span className="muted">—</span>}</td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={2} className="muted" style={{ textAlign: "center", padding: 24 }}>
                  Empty catalog.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ThreatLibraryPage() {
  const [threats, setThreats] = useState<CatalogItem[]>([]);
  const [vulns, setVulns] = useState<CatalogItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [t, v] = await Promise.all([api.threatCatalog(), api.vulnerabilityCatalog()]);
      setThreats(t.items);
      setVulns(v.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  return (
    <>
      <div className="page-head">
        <h1>Threat &amp; Vulnerability Library</h1>
        <p>Reusable catalogs you can link to risks (threat exploits vulnerability).</p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <Catalog
          title="Threats"
          subtitle={`${threats.length} in catalog`}
          items={threats}
          onCreate={async (name, category) => {
            await api.createThreat({ name, category });
            await load();
          }}
        />
        <Catalog
          title="Vulnerabilities"
          subtitle={`${vulns.length} in catalog`}
          items={vulns}
          onCreate={async (name, category) => {
            await api.createVulnerability({ name, category });
            await load();
          }}
        />
      </div>

      <div className="card card-pad" style={{ marginTop: 16 }}>
        <div className="empty" style={{ padding: "8px 0" }}>
          <span className="ico"><IconRisk width={22} height={22} /></span>
          <p>Link threats &amp; vulnerabilities to risks when creating a risk in the Risk Register.</p>
        </div>
      </div>
    </>
  );
}
