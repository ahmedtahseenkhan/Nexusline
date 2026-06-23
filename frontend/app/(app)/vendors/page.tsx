"use client";

import { useEffect, useState } from "react";
import { api, type Vendor } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import { Badge, Severity } from "@/components/badges";
import { IconPlus, IconVendor } from "@/components/icons";

const CRIT = ["low", "medium", "high", "critical"];
const ASSESS_TONE: Record<string, "low" | "medium" | "neutral"> = {
  completed: "low",
  in_progress: "medium",
  not_started: "neutral",
};

export default function VendorsPage() {
  const [items, setItems] = useState<Vendor[]>([]);
  const [open, setOpen] = useState<Vendor | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [criticality, setCriticality] = useState("medium");

  async function load() {
    try {
      setItems((await api.vendors()).items);
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
      await api.createVendor({ name, category, contact_email: contactEmail, criticality });
      setShowForm(false);
      setName("");
      setCategory("");
      setContactEmail("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create vendor");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Third-Party Risk</h1>
          <p>Vendor registry with criticality, risk rating and assessment status.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "Add vendor"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 240px" }}>
              <label className="label">Name</label>
              <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Stripe" />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Category</label>
              <input className="input" value={category} onChange={(e) => setCategory(e.target.value)} placeholder="Payments" />
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Criticality</label>
              <select className="select" value={criticality} onChange={(e) => setCriticality(e.target.value)}>
                {CRIT.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Contact email</label>
              <input className="input" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Add vendor</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Vendors</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Category</th>
                <th>Criticality</th>
                <th>Risk rating</th>
                <th>Status</th>
                <th>Assessment</th>
                <th>Last assessed</th>
              </tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === v.id ? null : v)}>
                  <td className="cell-title">{v.name}</td>
                  <td className="muted">{v.category || "—"}</td>
                  <td><Severity value={v.criticality} /></td>
                  <td><Severity value={v.risk_rating} /></td>
                  <td><Badge tone="neutral">{v.status}</Badge></td>
                  <td><Badge tone={ASSESS_TONE[v.assessment_status] || "neutral"}>{v.assessment_status.replace(/_/g, " ")}</Badge></td>
                  <td className="muted">{v.last_assessed_at || "—"}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconVendor width={24} height={24} /></span>
                      <h3>No vendors</h3>
                      <p>Add the third parties your organization relies on.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {open && <RecordPanels model="vendor" entityId={open.id} />}
    </>
  );
}
