"use client";

import { useEffect, useState } from "react";
import { api, type Legal } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPolicy, IconPlus } from "@/components/icons";

export default function LegalPage() {
  const [items, setItems] = useState<Legal[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [jurisdiction, setJurisdiction] = useState("");
  const [reference, setReference] = useState("");
  const [magnifier, setMagnifier] = useState("1.0");

  async function load() {
    try {
      setItems((await api.legals()).items);
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
      await api.createLegal({
        name,
        category,
        jurisdiction,
        reference,
        risk_magnifier: Number(magnifier) || 1.0,
      });
      setShowForm(false);
      setName("");
      setCategory("");
      setJurisdiction("");
      setReference("");
      setMagnifier("1.0");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Legal Register</h1>
          <p>Legal &amp; regulatory obligations; the risk magnifier amplifies linked risks.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New obligation"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Name</label>
              <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. HIPAA" />
            </div>
            <div style={{ flex: "1 1 160px" }}>
              <label className="label">Category</label>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Privacy" />
            </div>
            <div style={{ flex: "1 1 160px" }}>
              <label className="label">Jurisdiction</label>
              <input className="input" value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)} placeholder="US" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Reference</label>
              <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. 45 CFR Part 160" />
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Risk magnifier</label>
              <input className="input" type="number" step="0.1" min={0} value={magnifier} onChange={(e) => setMagnifier(e.target.value)} />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create obligation</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Obligations</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Category</th>
                <th>Jurisdiction</th>
                <th>Reference</th>
                <th>Risk magnifier</th>
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id}>
                  <td className="cell-title">{l.name}</td>
                  <td className="muted">{l.category || "—"}</td>
                  <td className="muted">{l.jurisdiction || "—"}</td>
                  <td className="muted">{l.reference || "—"}</td>
                  <td><Badge tone={l.risk_magnifier > 1 ? "medium" : "neutral"} plain>×{l.risk_magnifier}</Badge></td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <div className="empty">
                      <span className="ico"><IconPolicy width={24} height={24} /></span>
                      <h3>No obligations</h3>
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
