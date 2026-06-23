"use client";

import { useEffect, useState } from "react";
import { api, type AwarenessProgram, type TrainingRecord } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus, IconUsers } from "@/components/icons";

type Builder = { text: string; options: string[]; correct: number };
const STATUS_TONE: Record<string, "low" | "medium" | "neutral"> = { active: "low", closed: "neutral", draft: "medium" };

export default function AwarenessPage() {
  const [items, setItems] = useState<AwarenessProgram[]>([]);
  const [open, setOpen] = useState<AwarenessProgram | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const [name, setName] = useState("");
  const [pass, setPass] = useState(80);
  const [questions, setQuestions] = useState<Builder[]>([{ text: "", options: ["", "", ""], correct: 0 }]);

  const [pname, setPname] = useState("");
  const [quizFor, setQuizFor] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  async function load(keep?: string) {
    try {
      const list = await api.awarenessPrograms();
      setItems(list);
      if (keep) {
        const full = await api.awarenessProgram(keep);
        setOpen(full);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function view(id: string) {
    if (open?.id === id) {
      setOpen(null);
      return;
    }
    setQuizFor(null);
    setOpen(await api.awarenessProgram(id));
  }

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
    const qs = questions
      .filter((q) => q.text.trim())
      .map((q, i) => ({
        text: q.text,
        order_index: i,
        options: q.options.map((label, j) => ({ label, is_correct: j === q.correct, order_index: j })),
      }));
    await act(api.createAwarenessProgram({ name, passing_score: pass, status: "active", questions: qs }));
    setShowForm(false);
    setName("");
    setQuestions([{ text: "", options: ["", "", ""], correct: 0 }]);
  }

  function compliant(p: TrainingRecord, prog: AwarenessProgram) {
    return p.status === "completed" && p.score != null && p.score >= prog.passing_score;
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Awareness Training</h1>
          <p>Recurring security-awareness programs with a quiz and compliance tracking.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New program"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 280px" }}>
              <label className="label">Program name</label>
              <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Phishing Awareness 2026" />
            </div>
            <div style={{ width: 150 }}>
              <label className="label">Passing score %</label>
              <input className="input" type="number" min={0} max={100} value={pass} onChange={(e) => setPass(Number(e.target.value))} />
            </div>
          </div>
          <label className="label">Quiz questions (pick the correct option)</label>
          {questions.map((q, qi) => (
            <div key={qi} className="card card-pad" style={{ marginBottom: 8, background: "var(--surface-2)" }}>
              <input className="input" value={q.text} onChange={(e) => setQuestions(questions.map((x, i) => i === qi ? { ...x, text: e.target.value } : x))} placeholder={`Question ${qi + 1}`} />
              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                {q.options.map((o, oi) => (
                  <label key={oi} style={{ display: "flex", gap: 4, alignItems: "center", flex: "1 1 160px" }}>
                    <input type="radio" checked={q.correct === oi} onChange={() => setQuestions(questions.map((x, i) => i === qi ? { ...x, correct: oi } : x))} />
                    <input className="input" value={o} onChange={(e) => setQuestions(questions.map((x, i) => i === qi ? { ...x, options: x.options.map((y, j) => j === oi ? e.target.value : y) } : x))} placeholder={`Option ${oi + 1}`} />
                  </label>
                ))}
              </div>
            </div>
          ))}
          <button type="button" className="btn secondary sm" onClick={() => setQuestions([...questions, { text: "", options: ["", "", ""], correct: 0 }])}>+ Add question</button>
          <div><button className="btn" style={{ marginTop: 16 }}>Create program</button></div>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Programs</h3>
          <span className="sub">{items.length} total · click to manage</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Ref</th><th>Name</th><th>Status</th><th>Participants</th><th>Completed</th><th>Compliance</th></tr></thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => view(p.id)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">{p.name}</td>
                  <td><Badge tone={STATUS_TONE[p.status] || "neutral"}>{p.status}</Badge></td>
                  <td className="muted">{p.participant_count}</td>
                  <td className="muted">{p.completed_count}/{p.participant_count}</td>
                  <td><Badge tone={p.compliance_pct >= 80 ? "low" : p.compliance_pct >= 50 ? "medium" : "critical"} plain>{p.compliance_pct}%</Badge></td>
                </tr>
              ))}
              {items.length === 0 && (<tr><td colSpan={6}><div className="empty"><span className="ico"><IconUsers width={24} height={24} /></span><h3>No programs</h3></div></td></tr>)}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <div className="card">
          <div className="card-head">
            <h3>{open.reference} · {open.name}</h3>
            <span className="sub">pass ≥ {open.passing_score}% · {open.question_count} questions</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Participant</th><th>Status</th><th>Score</th><th>Compliant</th><th></th></tr></thead>
              <tbody>
                {open.participants.map((p) => (
                  <tr key={p.id}>
                    <td className="cell-title">{p.participant_name}<div className="when">{p.participant_email}</div></td>
                    <td><Badge tone={p.status === "completed" ? "info" : "neutral"}>{p.status}</Badge></td>
                    <td className="muted">{p.score != null ? `${p.score}%` : "—"}</td>
                    <td>{p.status === "completed" ? <Badge tone={compliant(p, open) ? "low" : "critical"}>{compliant(p, open) ? "yes" : "no"}</Badge> : <span className="muted">—</span>}</td>
                    <td>{p.status !== "completed" && open.question_count > 0 && (
                      <button className="btn secondary sm" onClick={() => { setQuizFor(p.id); setAnswers({}); }}>Take quiz</button>
                    )}</td>
                  </tr>
                ))}
                {open.participants.length === 0 && (<tr><td colSpan={5} className="muted" style={{ padding: 16 }}>No participants yet.</td></tr>)}
              </tbody>
            </table>
          </div>
          <form className="card-pad" style={{ display: "flex", gap: 8, borderTop: "1px solid var(--border)" }}
            onSubmit={(e) => { e.preventDefault(); if (!pname) return; act(api.addParticipant(open.id, { participant_name: pname }), open.id); setPname(""); }}>
            <input className="input" value={pname} onChange={(e) => setPname(e.target.value)} placeholder="Add participant name" />
            <button className="btn sm">Assign</button>
          </form>

          {quizFor && (
            <div className="card-pad" style={{ borderTop: "1px solid var(--border)", background: "var(--surface-2)" }}>
              <strong style={{ fontSize: 13 }}>Quiz</strong>
              {open.questions.map((q, i) => (
                <div key={q.id} style={{ padding: "8px 0" }}>
                  <div style={{ fontSize: 13 }}>{i + 1}. {q.text}</div>
                  <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                    {q.options.map((o) => {
                      const on = answers[q.id] === o.id;
                      return <button key={o.id} type="button" className={`badge ${on ? "info" : "neutral"}`} style={{ cursor: "pointer", border: on ? "1px solid var(--primary)" : "1px solid var(--border)" }} onClick={() => setAnswers({ ...answers, [q.id]: o.id })}>{o.label}</button>;
                    })}
                  </div>
                </div>
              ))}
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <button className="btn" onClick={() => { act(api.submitQuiz(open.id, quizFor!, answers), open.id); setQuizFor(null); }}>Submit quiz</button>
                <button className="btn secondary" onClick={() => setQuizFor(null)}>Cancel</button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}
