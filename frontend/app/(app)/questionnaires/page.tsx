"use client";

import { useEffect, useState } from "react";
import { api, type Questionnaire, type QuestionnaireSummary } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus, IconPolicy } from "@/components/icons";

const STD_OPTIONS = [
  { label: "Yes", score: 10, order_index: 0 },
  { label: "Partial", score: 5, order_index: 1 },
  { label: "No", score: 0, order_index: 2 },
];

export default function QuestionnairesPage() {
  const [items, setItems] = useState<QuestionnaireSummary[]>([]);
  const [open, setOpen] = useState<Questionnaire | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [questions, setQuestions] = useState<string[]>([""]);

  async function load() {
    try {
      setItems(await api.questionnaires());
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
    try {
      setOpen(await api.questionnaire(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const qs = questions
      .map((t) => t.trim())
      .filter(Boolean)
      .map((text, i) => ({ text, order_index: i, options: STD_OPTIONS }));
    if (!qs.length) {
      setError("Add at least one question");
      return;
    }
    try {
      await api.createQuestionnaire({ name, description, questions: qs });
      setShowForm(false);
      setName("");
      setDescription("");
      setQuestions([""]);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Questionnaires</h1>
          <p>Reusable templates with scored options (Yes 10 / Partial 5 / No 0).</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New questionnaire"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <label className="label">Name</label>
          <input className="input" value={name} required onChange={(e) => setName(e.target.value)} placeholder="e.g. Security Baseline Assessment" />
          <label className="label">Description</label>
          <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
          <label className="label">Questions</label>
          {questions.map((q, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <input
                className="input"
                value={q}
                onChange={(e) => setQuestions(questions.map((x, j) => (j === i ? e.target.value : x)))}
                placeholder={`Question ${i + 1}`}
              />
              {questions.length > 1 && (
                <button type="button" className="btn secondary sm" onClick={() => setQuestions(questions.filter((_, j) => j !== i))}>×</button>
              )}
            </div>
          ))}
          <button type="button" className="btn secondary sm" onClick={() => setQuestions([...questions, ""])}>
            + Add question
          </button>
          <div><button className="btn" style={{ marginTop: 16 }}>Create questionnaire</button></div>
        </form>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Templates</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Name</th><th>Questions</th><th>Max score</th></tr>
            </thead>
            <tbody>
              {items.map((q) => (
                <tr key={q.id} style={{ cursor: "pointer" }} onClick={() => view(q.id)}>
                  <td className="cell-title">{q.name}</td>
                  <td className="muted">{q.question_count}</td>
                  <td><Badge tone="info" plain>{q.max_score}</Badge></td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr><td colSpan={3}><div className="empty"><span className="ico"><IconPolicy width={24} height={24} /></span><h3>No questionnaires</h3></div></td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <div className="card">
          <div className="card-head">
            <h3>{open.name}</h3>
            <span className="sub">max score {open.max_score}</span>
          </div>
          <div className="card-pad">
            {open.questions.map((q, i) => (
              <div key={q.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                <div style={{ fontSize: 13.5 }}>{i + 1}. {q.text}</div>
                <div style={{ marginTop: 4, display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {q.options.map((o) => (
                    <Badge key={o.id} tone="neutral" plain>{o.label} = {o.score}</Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
