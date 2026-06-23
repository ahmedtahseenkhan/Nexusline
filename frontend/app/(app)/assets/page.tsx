"use client";

import { useEffect, useState } from "react";
import { api, type Asset, type AssetLabel, type BusinessUnit, type SavedFilter, type StatusLabel } from "@/lib/api";
import { Badge, Severity } from "@/components/badges";
import { IconAsset, IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

const TYPES = ["information", "software", "hardware", "service", "people", "facility", "process"];
const CRIT = ["low", "medium", "high", "critical"];

function CiaSelect({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div style={{ width: 110 }}>
      <label className="label">{label}</label>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {CRIT.map((c) => (<option key={c} value={c}>{c}</option>))}
      </select>
    </div>
  );
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [open, setOpen] = useState<Asset | null>(null);
  const [units, setUnits] = useState<BusinessUnit[]>([]);
  const [labels, setLabels] = useState<AssetLabel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Record<string, StatusLabel[]>>({});
  const [views, setViews] = useState<SavedFilter[]>([]);
  const [activeView, setActiveView] = useState<string>("all");
  const [viewIds, setViewIds] = useState<Set<string> | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [showLabels, setShowLabels] = useState(false);

  const [name, setName] = useState("");
  const [assetType, setAssetType] = useState("information");
  const [owner, setOwner] = useState("");
  const [guardian, setGuardian] = useState("");
  const [crit, setCrit] = useState("medium");
  const [conf, setConf] = useState("medium");
  const [integ, setInteg] = useState("medium");
  const [avail, setAvail] = useState("medium");
  const [unitId, setUnitId] = useState("");
  const [labelId, setLabelId] = useState("");
  const [newLabel, setNewLabel] = useState("");

  async function load() {
    try {
      const [a, u, l, v] = await Promise.all([api.assets(), api.businessUnits(), api.assetLabels(), api.filters("asset")]);
      setAssets(a.items);
      setUnits(u.items);
      setLabels(l);
      setViews(v);
      if (a.items.length) api.evaluateStatus("asset", a.items.map((x) => x.id)).then(setStatus).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function selectView(id: string) {
    setActiveView(id);
    if (id === "all") { setViewIds(null); return; }
    try {
      const res = await api.runFilter(id);
      setViewIds(new Set(res.matches.map((m) => m.id)));
    } catch { setViewIds(new Set()); }
  }

  const shown = viewIds ? assets.filter((a) => viewIds.has(a.id)) : assets;

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createAsset({
        name,
        asset_type: assetType,
        owner,
        guardian,
        criticality: crit,
        confidentiality: conf,
        integrity: integ,
        availability: avail,
        business_unit_id: unitId || null,
        label_id: labelId || null,
      });
      setShowForm(false);
      setName("");
      setOwner("");
      setGuardian("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create asset");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Asset Management</h1>
          <p>Inventory with CIA classification, ownership and handling labels.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={() => setShowLabels((v) => !v)}>Labels</button>
          <button className="btn" onClick={() => setShowForm((v) => !v)}>
            <IconPlus width={16} height={16} />
            {showForm ? "Close" : "New asset"}
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showLabels && (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <div className="row-between" style={{ marginBottom: 10 }}>
            <strong>Handling labels</strong>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
            {labels.map((l) => (
              <span key={l.id} className="badge" style={{ background: "var(--surface-3)", color: l.color || "var(--muted)", border: `1px solid ${l.color || "var(--border)"}` }}>
                {l.name}
              </span>
            ))}
            {labels.length === 0 && <span className="muted">No labels yet.</span>}
          </div>
          <form
            style={{ display: "flex", gap: 8 }}
            onSubmit={async (e) => {
              e.preventDefault();
              if (!newLabel) return;
              await api.createAssetLabel({ name: newLabel });
              setNewLabel("");
              await load();
            }}
          >
            <input className="input" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="New label (e.g. Confidential)" />
            <button className="btn sm">Add label</button>
          </form>
        </div>
      )}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 240px" }}>
              <label className="label">Name</label>
              <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Customer Database" />
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Type</label>
              <select className="select" value={assetType} onChange={(e) => setAssetType(e.target.value)}>
                {TYPES.map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Criticality</label>
              <select className="select" value={crit} onChange={(e) => setCrit(e.target.value)}>
                {CRIT.map((t) => (<option key={t} value={t}>{t}</option>))}
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 4 }}>
            <CiaSelect label="Confidentiality" value={conf} onChange={setConf} />
            <CiaSelect label="Integrity" value={integ} onChange={setInteg} />
            <CiaSelect label="Availability" value={avail} onChange={setAvail} />
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Owner</label>
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Guardian</label>
              <input className="input" value={guardian} onChange={(e) => setGuardian(e.target.value)} />
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Business unit</label>
              <select className="select" value={unitId} onChange={(e) => setUnitId(e.target.value)}>
                <option value="">— none —</option>
                {units.map((u) => (<option key={u.id} value={u.id}>{u.name}</option>))}
              </select>
            </div>
            <div style={{ width: 160 }}>
              <label className="label">Label</label>
              <select className="select" value={labelId} onChange={(e) => setLabelId(e.target.value)}>
                <option value="">— none —</option>
                {labels.map((l) => (<option key={l.id} value={l.id}>{l.name}</option>))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create asset</button>
        </form>
      )}

      {/* eramba-style view tabs (saved filters as quick views) */}
      <div style={{ display: "flex", gap: 4, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
        <button className={`viewtab${activeView === "all" ? " active" : ""}`} onClick={() => selectView("all")}>
          All items <span className="muted">{assets.length}</span>
        </button>
        {views.map((v) => (
          <button key={v.id} className={`viewtab${activeView === v.id ? " active" : ""}`} onClick={() => selectView(v.id)} title={v.description}>
            {v.name}
          </button>
        ))}
        <a href="/filters" className="viewtab" style={{ color: "var(--primary-text)" }}>+ New view</a>
      </div>

      <div className="card">
        <div className="card-head">
          <h3>{activeView === "all" ? "All assets" : views.find((v) => v.id === activeView)?.name}</h3>
          <span className="sub">{shown.length} {viewIds ? `of ${assets.length}` : "total"}</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Dynamic Status</th>
                <th>Name</th>
                <th>Media type</th>
                <th>Owner</th>
                <th>Guardian</th>
                <th>C / I / A</th>
                <th>Classification</th>
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((a) => (
                <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === a.id ? null : a)}>
                  <td>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {(status[a.id] || []).map((l) => (
                        <span key={l.label} style={{ background: `${l.color}1a`, color: l.color, border: `1px solid ${l.color}55`, borderRadius: 99, padding: "1px 8px", fontSize: 11, fontWeight: 600 }}>{l.label}</span>
                      ))}
                      {(!status[a.id] || status[a.id].length === 0) && <span className="muted">—</span>}
                    </div>
                  </td>
                  <td className="cell-title">{a.name}</td>
                  <td>{a.media_type ? <Badge tone="info" plain>{a.media_type.label}</Badge> : "—"}</td>
                  <td className="muted">{a.owner ? a.owner.label : "—"}</td>
                  <td className="muted">{a.guardian ? a.guardian.label : "—"}</td>
                  <td>
                    <span style={{ display: "flex", gap: 4 }}>
                      <Severity value={a.confidentiality} />
                      <Severity value={a.integrity} />
                      <Severity value={a.availability} />
                    </span>
                  </td>
                  <td><Severity value={a.classification} /></td>
                  <td className="muted">{a.label ? a.label.label : "—"}</td>
                </tr>
              ))}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="empty">
                      <span className="ico"><IconAsset width={24} height={24} /></span>
                      <h3>No assets yet</h3>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {open && <RecordPanels model="asset" entityId={open.id} />}
    </>
  );
}
