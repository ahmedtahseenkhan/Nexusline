"use client";

import { useEffect, useState } from "react";
import { api, type BusinessUnit, type ContinuityPlan } from "@/lib/api";
import { Badge, Severity } from "@/components/badges";
import { IconPlus, IconShield } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";

const STATUS_TONE: Record<string, "low" | "medium" | "neutral" | "info"> = {
  active: "low",
  under_review: "medium",
  draft: "neutral",
  retired: "neutral",
};
const RESULT_TONE: Record<string, "low" | "critical" | "neutral"> = {
  passed: "low",
  failed: "critical",
  not_assessed: "neutral",
};
const FREQ = ["annual", "semiannual", "quarterly", "monthly", "none"];
const CRIT = ["low", "medium", "high", "critical"];

export default function ContinuityPage() {
  const [items, setItems] = useState<ContinuityPlan[]>([]);
  const [units, setUnits] = useState<BusinessUnit[]>([]);
  const [open, setOpen] = useState<ContinuityPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [name, setName] = useState("");
  const [owner, setOwner] = useState("");
  const [unitId, setUnitId] = useState("");
  const [mtd, setMtd] = useState("");
  const [crit, setCrit] = useState("high");
  const [freq, setFreq] = useState("annual");

  const [taskAction, setTaskAction] = useState("");
  const [taskActor, setTaskActor] = useState("");
  const [testResult, setTestResult] = useState("passed");
  const [testNote, setTestNote] = useState("");

  async function load(keep?: string) {
    try {
      const [p, u] = await Promise.all([api.continuityPlans(), api.businessUnits()]);
      setItems(p.items);
      setUnits(u.items);
      if (keep) setOpen(p.items.find((x) => x.id === keep) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function act(fn: Promise<unknown>, keep?: string) {
    setError(null);
    try {
      await fn;
      await load(keep);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    await act(
      api.createContinuityPlan({
        name,
        owner,
        business_unit_id: unitId || null,
        max_tolerable_downtime_hours: mtd ? Number(mtd) : null,
        criticality: crit,
        test_frequency: freq,
        status: "active",
      })
    );
    setShowForm(false);
    setName("");
    setOwner("");
    setMtd("");
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Continuity</h1>
          <p>Continuity plans with a 5W recovery playbook and a test/exercise calendar.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New plan"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Plan name</label>
          <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Data center failover plan" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 180px" }}>
              <label className="label">Owner</label>
              <input className="input" value={owner} onChange={(e) => setOwner(e.target.value)} />
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Business unit</label>
              <select className="select" value={unitId} onChange={(e) => setUnitId(e.target.value)}>
                <option value="">— none —</option>
                {units.map((u) => (<option key={u.id} value={u.id}>{u.name}</option>))}
              </select>
            </div>
            <div style={{ width: 130 }}>
              <label className="label">MTD (hours)</label>
              <input className="input" type="number" min={0} value={mtd} onChange={(e) => setMtd(e.target.value)} />
            </div>
            <div style={{ width: 130 }}>
              <label className="label">Criticality</label>
              <select className="select" value={crit} onChange={(e) => setCrit(e.target.value)}>
                {CRIT.map((c) => (<option key={c} value={c}>{c}</option>))}
              </select>
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Test every</label>
              <select className="select" value={freq} onChange={(e) => setFreq(e.target.value)}>
                {FREQ.map((f) => (<option key={f} value={f}>{f}</option>))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create plan</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Continuity plans</h3>
          <span className="sub">{items.length} total · click to open</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Ref</th><th>Plan</th><th>Business unit</th><th>Criticality</th><th>MTD</th><th>Last test</th><th>Next test</th></tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => setOpen(open?.id === p.id ? null : p)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">{p.name}</td>
                  <td className="muted">{p.business_unit ? p.business_unit.name : "—"}</td>
                  <td><Severity value={p.criticality} /></td>
                  <td className="muted">{p.max_tolerable_downtime_hours != null ? `${p.max_tolerable_downtime_hours}h` : "—"}</td>
                  <td>{p.last_test_result ? <Badge tone={RESULT_TONE[p.last_test_result] || "neutral"}>{p.last_test_result}</Badge> : <span className="muted">—</span>}</td>
                  <td className="muted">{p.next_test_date || "—"}{p.is_test_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">due</Badge></span>}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={7}><div className="empty"><span className="ico"><IconShield width={24} height={24} /></span><h3>No continuity plans</h3></div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (<>
        <div className="grid" style={{ gridTemplateColumns: "1.4fr 1fr" }}>
          <div className="card">
            <div className="card-head">
              <h3>Recovery playbook · {open.reference}</h3>
              <span className="sub">{open.status.replace(/_/g, " ")}</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Action</th><th>Who</th><th>When</th><th>How</th></tr></thead>
                <tbody>
                  {open.tasks.map((t) => (
                    <tr key={t.id}>
                      <td className="ref">{t.step}</td>
                      <td className="cell-title">{t.action}</td>
                      <td className="muted">{t.actor || "—"}</td>
                      <td className="muted">{t.timing || "—"}</td>
                      <td className="muted">{t.method || "—"}</td>
                    </tr>
                  ))}
                  {open.tasks.length === 0 && (<tr><td colSpan={5} className="muted" style={{ padding: 16 }}>No steps yet.</td></tr>)}
                </tbody>
              </table>
            </div>
            <form
              className="card-pad"
              style={{ display: "flex", gap: 8, borderTop: "1px solid var(--border)" }}
              onSubmit={(e) => {
                e.preventDefault();
                if (!taskAction) return;
                act(api.addContinuityTask(open.id, { step: open.tasks.length + 1, action: taskAction, actor: taskActor }), open.id);
                setTaskAction("");
                setTaskActor("");
              }}
            >
              <input className="input" value={taskAction} onChange={(e) => setTaskAction(e.target.value)} placeholder="Recovery step…" />
              <input className="input" style={{ width: 140 }} value={taskActor} onChange={(e) => setTaskActor(e.target.value)} placeholder="Who" />
              <button className="btn sm">Add</button>
            </form>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Tests · {open.reference}</h3>
              <span className="sub">every {open.test_frequency}</span>
            </div>
            <div className="card-pad">
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end" }}
                onSubmit={(e) => {
                  e.preventDefault();
                  act(api.recordContinuityTest(open.id, { result: testResult, result_description: testNote }), open.id);
                  setTestNote("");
                }}
              >
                <div style={{ width: 120 }}>
                  <label className="label">Result</label>
                  <select className="select" value={testResult} onChange={(e) => setTestResult(e.target.value)}>
                    <option value="passed">passed</option>
                    <option value="failed">failed</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label className="label">Notes</label>
                  <input className="input" value={testNote} onChange={(e) => setTestNote(e.target.value)} placeholder="Exercise outcome" />
                </div>
                <button className="btn">Record</button>
              </form>
              {open.tests.length ? open.tests.map((t) => (
                <div key={t.id} className="activity-item">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{t.result_description || "Test"}</div>
                    <div className="when">{t.conducted_date || "—"} · {t.tester || "—"}</div>
                  </div>
                  <Badge tone={RESULT_TONE[t.result] || "neutral"}>{t.result}</Badge>
                </div>
              )) : <span className="muted">No tests recorded yet.</span>}
            </div>
          </div>
        </div>
        <RecordPanels model="continuity_plan" entityId={open.id} />
        </>
      )}
    </>
  );
}
