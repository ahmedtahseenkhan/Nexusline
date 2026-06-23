"use client";

import { useEffect, useState } from "react";
import { api, type BusinessUnit, type ProcessRow } from "@/lib/api";
import { Severity } from "@/components/badges";
import { IconLayers, IconPlus } from "@/components/icons";

const CRIT = ["low", "medium", "high", "critical"];

export default function ProcessesPage() {
  const [items, setItems] = useState<ProcessRow[]>([]);
  const [units, setUnits] = useState<BusinessUnit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [businessUnitId, setBusinessUnitId] = useState("");
  const [owner, setOwner] = useState("");
  const [criticality, setCriticality] = useState("medium");
  const [rto, setRto] = useState("");
  const [rpo, setRpo] = useState("");

  async function load() {
    try {
      const [p, u] = await Promise.all([api.processes(), api.businessUnits()]);
      setItems(p.items);
      setUnits(u.items);
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
      await api.createProcess({
        name,
        business_unit_id: businessUnitId || null,
        owner,
        criticality,
        rto_hours: rto ? Number(rto) : null,
        rpo_hours: rpo ? Number(rpo) : null,
      });
      setShowForm(false);
      setName("");
      setOwner("");
      setRto("");
      setRpo("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Processes</h1>
          <p>Processes with continuity objectives (RTO / RPO) for impact analysis.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New process"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Name</label>
              <input className="input" value={name} required onChange={(e) => setName(e.target.value)} />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Business unit</label>
              <select className="select" value={businessUnitId} onChange={(e) => setBusinessUnitId(e.target.value)}>
                <option value="">— none —</option>
                {units.map((u) => (
                  <option key={u.id} value={u.id}>{u.name}</option>
                ))}
              </select>
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Criticality</label>
              <select className="select" value={criticality} onChange={(e) => setCriticality(e.target.value)}>
                {CRIT.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Owner</label>
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} />
            </div>
            <div style={{ width: 150 }}>
              <label className="label">RTO (hours)</label>
              <input className="input" type="number" min={0} value={rto} onChange={(e) => setRto(e.target.value)} />
            </div>
            <div style={{ width: 150 }}>
              <label className="label">RPO (hours)</label>
              <input className="input" type="number" min={0} value={rpo} onChange={(e) => setRpo(e.target.value)} />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create process</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Processes</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Business unit</th>
                <th>Owner</th>
                <th>Criticality</th>
                <th>RTO</th>
                <th>RPO</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id}>
                  <td className="cell-title">{p.name}</td>
                  <td className="muted">{p.business_unit ? p.business_unit.name : "—"}</td>
                  <td className="muted">{p.owner || "—"}</td>
                  <td><Severity value={p.criticality} /></td>
                  <td className="muted">{p.rto_hours != null ? `${p.rto_hours}h` : "—"}</td>
                  <td className="muted">{p.rpo_hours != null ? `${p.rpo_hours}h` : "—"}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <div className="empty">
                      <span className="ico"><IconLayers width={24} height={24} /></span>
                      <h3>No processes</h3>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
