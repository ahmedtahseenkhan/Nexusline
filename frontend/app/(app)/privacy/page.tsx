"use client";

import { useEffect, useState } from "react";
import { api, type BusinessUnit, type Ropa } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconAlert, IconPlus, IconPolicy } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

const BASES = ["consent", "contract", "legal_obligation", "vital_interests", "public_task", "legitimate_interests"];
const DPIA = ["not_required", "required", "in_progress", "completed"];

export default function PrivacyPage() {
  const [items, setItems] = useState<Ropa[]>([]);
  const [units, setUnits] = useState<BusinessUnit[]>([]);
  const [open, setOpen] = useState<Ropa | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  const [basis, setBasis] = useState("contract");
  const [subjects, setSubjects] = useState("");
  const [retention, setRetention] = useState("");
  const [dpo, setDpo] = useState("");
  const [unitId, setUnitId] = useState("");
  const [crossBorder, setCrossBorder] = useState(false);
  const [safeguard, setSafeguard] = useState("");
  const [special, setSpecial] = useState(false);
  const [dpiaReq, setDpiaReq] = useState(false);
  const [dpiaStatus, setDpiaStatus] = useState("not_required");

  async function load() {
    try {
      const [r, u] = await Promise.all([api.ropa(), api.businessUnits()]);
      setItems(r.items);
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
      await api.createRopa({
        name,
        purpose,
        status: "active",
        lawful_basis: basis,
        data_subjects: subjects,
        retention_period: retention,
        dpo,
        business_unit_id: unitId || null,
        cross_border_transfer: crossBorder,
        transfer_safeguard: safeguard,
        special_category: special,
        dpia_required: dpiaReq,
        dpia_status: dpiaStatus,
      });
      setShowForm(false);
      setName("");
      setPurpose("");
      setSubjects("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  const gaps = items.filter((i) => i.has_transfer_gap).length;
  const dpias = items.filter((i) => i.dpia_outstanding).length;

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Data Privacy (RoPA)</h1>
          <p>GDPR records of processing — lawful basis, retention, transfers, DPIA.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New record"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{items.length}</span></div><span className="l">Processing activities</span></div>
        <div className="card stat danger"><div className="stat-top"><span className="n">{gaps}</span><span className="ico"><IconAlert /></span></div><span className="l">Transfer gaps</span></div>
        <div className="card stat warn"><div className="stat-top"><span className="n">{dpias}</span></div><span className="l">DPIAs outstanding</span></div>
      </div>

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Name</label>
          <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Marketing email processing" />
          <label className="label">Purpose</label>
          <input className="input" value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="Why is this data processed?" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ width: 200 }}>
              <label className="label">Lawful basis</label>
              <select className="select" value={basis} onChange={(e) => setBasis(e.target.value)}>
                {BASES.map((b) => (<option key={b} value={b}>{b.replace(/_/g, " ")}</option>))}
              </select>
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Data subjects</label>
              <input className="input" value={subjects} onChange={(e) => setSubjects(e.target.value)} placeholder="Customers, employees…" />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Retention</label>
              <input className="input" value={retention} onChange={(e) => setRetention(e.target.value)} placeholder="e.g. 6 years" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">DPO</label>
              <input className="input" value={dpo} onChange={(e) => setDpo(e.target.value)} />
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Business unit</label>
              <select className="select" value={unitId} onChange={(e) => setUnitId(e.target.value)}>
                <option value="">— none —</option>
                {units.map((u) => (<option key={u.id} value={u.id}>{u.name}</option>))}
              </select>
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Transfer safeguard</label>
              <input className="input" value={safeguard} onChange={(e) => setSafeguard(e.target.value)} placeholder="SCCs / adequacy" />
            </div>
          </div>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", marginTop: 12, alignItems: "center" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={crossBorder} onChange={(e) => setCrossBorder(e.target.checked)} /> Cross-border transfer
            </label>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={special} onChange={(e) => setSpecial(e.target.checked)} /> Special-category data
            </label>
            <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13 }}>
              <input type="checkbox" checked={dpiaReq} onChange={(e) => setDpiaReq(e.target.checked)} /> DPIA required
            </label>
            <div style={{ width: 160 }}>
              <select className="select" value={dpiaStatus} onChange={(e) => setDpiaStatus(e.target.value)}>
                {DPIA.map((d) => (<option key={d} value={d}>{d.replace(/_/g, " ")}</option>))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create record</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Records of processing</h3>
          <span className="sub">{items.length} total · click for detail</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Ref</th><th>Name</th><th>Lawful basis</th><th>Subjects</th><th>Transfer</th><th>DPIA</th></tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === r.id ? null : r)}>
                  <td className="ref">{r.reference}</td>
                  <td className="cell-title">{r.name}{r.special_category && <span style={{ marginLeft: 6 }}><Badge tone="high">special</Badge></span>}</td>
                  <td className="muted">{r.lawful_basis.replace(/_/g, " ")}</td>
                  <td className="muted">{r.data_subjects || "—"}</td>
                  <td>{r.cross_border_transfer ? (r.has_transfer_gap ? <Badge tone="critical">gap</Badge> : <Badge tone="low">safeguarded</Badge>) : <span className="muted">none</span>}</td>
                  <td>{r.dpia_outstanding ? <Badge tone="high">{r.dpia_status.replace(/_/g, " ")}</Badge> : (r.dpia_required ? <Badge tone="low">done</Badge> : <span className="muted">n/a</span>)}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={6}><div className="empty"><span className="ico"><IconPolicy width={24} height={24} /></span><h3>No records of processing</h3></div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (<>
        <div className="card card-pad">
          <div className="card-head" style={{ padding: 0, border: "none", marginBottom: 12 }}>
            <h3>{open.reference} · {open.name}</h3>
          </div>
          <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 12, fontSize: 13 }}>
            <div><span className="muted">Purpose:</span> {open.purpose || "—"}</div>
            <div><span className="muted">Lawful basis:</span> {open.lawful_basis.replace(/_/g, " ")}</div>
            <div><span className="muted">Data subjects:</span> {open.data_subjects || "—"}</div>
            <div><span className="muted">Categories:</span> {open.data_categories || "—"}</div>
            <div><span className="muted">Retention:</span> {open.retention_period || "—"}</div>
            <div><span className="muted">DPO:</span> {open.dpo || "—"}</div>
            <div><span className="muted">Business unit:</span> {open.business_unit ? open.business_unit.name : "—"}</div>
            <div><span className="muted">Transfer:</span> {open.cross_border_transfer ? `${open.transfer_destinations || "yes"} (safeguard: ${open.transfer_safeguard || "none"})` : "none"}</div>
            <div><span className="muted">Linked assets:</span> {open.assets.map((a) => a.name).join(", ") || "—"}</div>
            <div><span className="muted">Linked risks:</span> {open.risks.map((r) => r.reference).join(", ") || "—"}</div>
          </div>
          {(open.has_transfer_gap || open.dpia_outstanding) && (
            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
              {open.has_transfer_gap && <Badge tone="critical">Cross-border transfer without safeguard</Badge>}
              {open.dpia_outstanding && <Badge tone="high">DPIA outstanding</Badge>}
            </div>
          )}
        </div>
        <RecordPanels model="processing_activity" entityId={open.id} />
        </>
      )}
    </>
  );
}
