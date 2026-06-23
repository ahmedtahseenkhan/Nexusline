"use client";

import { useEffect, useState } from "react";
import {
  api,
  type Assessment,
  type AssessmentSummary,
  type QuestionnaireSummary,
  type Vendor,
} from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus, IconVendor } from "@/components/icons";

const STATUS_TONE: Record<string, "low" | "medium" | "info" | "neutral"> = {
  reviewed: "low",
  submitted: "info",
  in_progress: "medium",
  sent: "medium",
  draft: "neutral",
};
const SEV_TONE: Record<string, "low" | "medium" | "high" | "critical"> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

export default function AssessmentsPage() {
  const [items, setItems] = useState<AssessmentSummary[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [qs, setQs] = useState<QuestionnaireSummary[]>([]);
  const [open, setOpen] = useState<Assessment | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [title, setTitle] = useState("");
  const [vendorId, setVendorId] = useState("");
  const [qId, setQId] = useState("");

  const [fTitle, setFTitle] = useState("");
  const [fSev, setFSev] = useState("medium");

  async function load() {
    try {
      const [a, v, q] = await Promise.all([api.assessments(), api.vendors(), api.questionnaires()]);
      setItems(a);
      setVendors(v.items);
      setQs(q);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function openAssessment(id: string) {
    if (open?.id === id) {
      setOpen(null);
      return;
    }
    try {
      const a = await api.assessment(id);
      setOpen(a);
      const m: Record<string, string> = {};
      a.answers.forEach((ans) => {
        if (ans.option_id) m[ans.question_id] = ans.option_id;
      });
      setAnswers(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  async function refreshOpen(id: string) {
    const a = await api.assessment(id);
    setOpen(a);
    await load();
  }

  async function saveAnswers(submit: boolean) {
    if (!open) return;
    setError(null);
    try {
      const payload = Object.entries(answers).map(([question_id, option_id]) => ({
        question_id,
        option_id,
        comment: "",
      }));
      await api.submitAnswers(open.id, payload, submit);
      await refreshOpen(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createAssessment({ title, vendor_id: vendorId || null, questionnaire_id: qId, due_date: null });
      setShowForm(false);
      setTitle("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Vendor Assessments</h1>
          <p>Send scored questionnaires to third parties and track findings.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)} disabled={qs.length === 0}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New assessment"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
      {qs.length === 0 && (
        <div className="card card-pad" style={{ marginBottom: 16 }} >
          <span className="muted">Create a questionnaire first (Questionnaires page) to run assessments.</span>
        </div>
      )}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Title</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Stripe annual security review" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Vendor</label>
              <select className="select" value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
                <option value="">— none —</option>
                {vendors.map((v) => (<option key={v.id} value={v.id}>{v.name}</option>))}
              </select>
            </div>
            <div style={{ flex: "1 1 220px" }}>
              <label className="label">Questionnaire</label>
              <select className="select" value={qId} required onChange={(e) => setQId(e.target.value)}>
                <option value="">— select —</option>
                {qs.map((q) => (<option key={q.id} value={q.id}>{q.name}</option>))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create assessment</button>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Assessments</h3>
          <span className="sub">{items.length} total · click to answer</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Title</th><th>Vendor</th><th>Status</th><th>Progress</th><th>Score</th><th>Findings</th></tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => openAssessment(a.id)}>
                  <td className="cell-title">{a.title}</td>
                  <td className="muted">{a.vendor ? a.vendor.name : "—"}</td>
                  <td><Badge tone={STATUS_TONE[a.status] || "neutral"}>{a.status.replace(/_/g, " ")}</Badge></td>
                  <td className="muted">{a.answered_count}/{a.question_count}</td>
                  <td><Badge tone={a.score_pct >= 80 ? "low" : a.score_pct >= 50 ? "medium" : "critical"} plain>{a.score_pct}%</Badge></td>
                  <td>{a.open_findings > 0 ? <Badge tone="high">{a.open_findings}</Badge> : <span className="muted">0</span>}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={6}><div className="empty"><span className="ico"><IconVendor width={24} height={24} /></span><h3>No assessments</h3></div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <div>
                <h3>{open.title}</h3>
                <span className="sub">{open.questionnaire?.name}</span>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{open.score_pct}%</div>
                <span className="muted" style={{ fontSize: 12 }}>{open.total_score} / {open.max_score}</span>
              </div>
            </div>
            <div className="card-pad">
              {open.questionnaire?.questions.map((q, i) => (
                <div key={q.id} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                  <div style={{ fontSize: 13.5, marginBottom: 6 }}>{i + 1}. {q.text}</div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {q.options.map((o) => {
                      const on = answers[q.id] === o.id;
                      return (
                        <button
                          key={o.id}
                          type="button"
                          className={`badge ${on ? "info" : "neutral"}`}
                          style={{ cursor: "pointer", border: on ? "1px solid var(--primary)" : "1px solid var(--border)" }}
                          onClick={() => setAnswers({ ...answers, [q.id]: o.id })}
                        >
                          {o.label} ({o.score})
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
                <button className="btn secondary" onClick={() => saveAnswers(false)}>Save answers</button>
                <button className="btn" onClick={() => saveAnswers(true)}>Save &amp; submit</button>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Findings</h3>
              <span className="sub">{open.findings.length} total</span>
            </div>
            <div className="card-pad">
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end" }}
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!fTitle) return;
                  await api.addFinding(open.id, { title: fTitle, severity: fSev });
                  setFTitle("");
                  await refreshOpen(open.id);
                }}
              >
                <div style={{ flex: 1 }}>
                  <label className="label">Finding</label>
                  <input className="input" value={fTitle} onChange={(e) => setFTitle(e.target.value)} placeholder="e.g. No pen testing" />
                </div>
                <div style={{ width: 130 }}>
                  <label className="label">Severity</label>
                  <select className="select" value={fSev} onChange={(e) => setFSev(e.target.value)}>
                    {["low", "medium", "high", "critical"].map((s) => (<option key={s} value={s}>{s}</option>))}
                  </select>
                </div>
                <button className="btn">Add</button>
              </form>
              {open.findings.map((f) => (
                <div key={f.id} className="activity-item">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{f.title}</div>
                    <div className="when">{f.description}</div>
                  </div>
                  <Badge tone={SEV_TONE[f.severity] || "neutral"}>{f.severity}</Badge>
                  {f.status === "open" ? (
                    <button className="btn secondary sm" onClick={async () => { await api.closeFinding(open.id, f.id); await refreshOpen(open.id); }}>Close</button>
                  ) : (
                    <Badge tone="neutral">closed</Badge>
                  )}
                </div>
              ))}
              {open.findings.length === 0 && <span className="muted">No findings.</span>}
            </div>
          </div>
        </>
      )}
    </>
  );
}
