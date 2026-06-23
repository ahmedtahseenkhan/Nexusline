"use client";

import { useEffect, useState } from "react";
import { api, type BusinessUnit } from "@/lib/api";
import { IconPlus, IconUsers } from "@/components/icons";

export default function BusinessUnitsPage() {
  const [items, setItems] = useState<BusinessUnit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [manager, setManager] = useState("");
  const [parentId, setParentId] = useState("");

  async function load() {
    try {
      setItems((await api.businessUnits()).items);
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
      await api.createBusinessUnit({ name, manager, parent_id: parentId || null });
      setShowForm(false);
      setName("");
      setManager("");
      setParentId("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Units</h1>
          <p>Organizational structure that owns assets, processes and risks.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New unit"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 240px" }}>
              <label className="label">Name</label>
              <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Engineering" />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Manager</label>
              <input className="input" value={manager} onChange={(e) => setManager(e.target.value)} />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Parent unit</label>
              <select className="select" value={parentId} onChange={(e) => setParentId(e.target.value)}>
                <option value="">— none —</option>
                {items.map((u) => (
                  <option key={u.id} value={u.id}>{u.name}</option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create unit</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Units</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Manager</th>
                <th>Parent</th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => (
                <tr key={u.id}>
                  <td className="cell-title">{u.name}</td>
                  <td className="muted">{u.manager || "—"}</td>
                  <td className="muted">{u.parent_name || "—"}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={3}>
                    <div className="empty">
                      <span className="ico"><IconUsers width={24} height={24} /></span>
                      <h3>No business units</h3>
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
