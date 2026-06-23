"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api,
  apiCall,
  type Questionnaire,
  type QuestionnaireSummary,
} from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, NumberInput } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconPolicy, IconCheck } from "@/components/icons";

// ---- builder draft types (mirror the backend create/update schema) --------------
type OptionDraft = { label: string; score: number | ""; order_index: number };
type QuestionDraft = {
  text: string;
  guidance: string;
  order_index: number;
  options: OptionDraft[];
};

const STD_OPTIONS = (): OptionDraft[] => [
  { label: "Yes", score: 10, order_index: 0 },
  { label: "Partial", score: 5, order_index: 1 },
  { label: "No", score: 0, order_index: 2 },
];

const blankQuestion = (order: number): QuestionDraft => ({
  text: "",
  guidance: "",
  order_index: order,
  options: STD_OPTIONS(),
});

function fromQuestionnaire(q: Questionnaire): { name: string; description: string; questions: QuestionDraft[] } {
  return {
    name: q.name,
    description: q.description || "",
    questions: [...q.questions]
      .sort((a, b) => a.order_index - b.order_index)
      .map((qq, i) => ({
        text: qq.text,
        guidance: qq.guidance || "",
        order_index: qq.order_index ?? i,
        options: [...qq.options]
          .sort((a, b) => a.order_index - b.order_index)
          .map((o, j) => ({ label: o.label, score: o.score, order_index: o.order_index ?? j })),
      })),
  };
}

// max score for a draft question = the highest option score
const draftQMax = (q: QuestionDraft) =>
  q.options.reduce((m, o) => Math.max(m, typeof o.score === "number" ? o.score : 0), 0);
const draftMax = (qs: QuestionDraft[]) => qs.reduce((s, q) => s + draftQMax(q), 0);

export default function QuestionnairesPage() {
  const [items, setItems] = useState<QuestionnaireSummary[]>([]);
  const [open, setOpen] = useState<Questionnaire | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Questionnaire | null>(null);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [questions, setQuestions] = useState<QuestionDraft[]>([blankQuestion(0)]);

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

  function openNew() {
    setEditing(null);
    setName("");
    setDescription("");
    setQuestions([blankQuestion(0)]);
    setError(null);
    setShowForm(true);
  }

  async function openEdit(id: string) {
    setError(null);
    try {
      const full = await api.questionnaire(id);
      const d = fromQuestionnaire(full);
      setEditing(full);
      setName(d.name);
      setDescription(d.description);
      setQuestions(d.questions.length ? d.questions : [blankQuestion(0)]);
      setShowForm(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load questionnaire");
    }
  }

  // ---- question/option mutators --------------------------------------------------
  const setQ = (i: number, patch: Partial<QuestionDraft>) =>
    setQuestions((qs) => qs.map((q, j) => (j === i ? { ...q, ...patch } : q)));
  const addQuestion = () => setQuestions((qs) => [...qs, blankQuestion(qs.length)]);
  const removeQuestion = (i: number) =>
    setQuestions((qs) => qs.filter((_, j) => j !== i).map((q, k) => ({ ...q, order_index: k })));
  const moveQuestion = (i: number, dir: -1 | 1) =>
    setQuestions((qs) => {
      const t = i + dir;
      if (t < 0 || t >= qs.length) return qs;
      const next = [...qs];
      [next[i], next[t]] = [next[t], next[i]];
      return next.map((q, k) => ({ ...q, order_index: k }));
    });

  const setOpt = (qi: number, oi: number, patch: Partial<OptionDraft>) =>
    setQuestions((qs) =>
      qs.map((q, j) =>
        j === qi ? { ...q, options: q.options.map((o, k) => (k === oi ? { ...o, ...patch } : o)) } : q,
      ),
    );
  const addOpt = (qi: number) =>
    setQuestions((qs) =>
      qs.map((q, j) =>
        j === qi
          ? { ...q, options: [...q.options, { label: "", score: 0, order_index: q.options.length }] }
          : q,
      ),
    );
  const removeOpt = (qi: number, oi: number) =>
    setQuestions((qs) =>
      qs.map((q, j) =>
        j === qi
          ? { ...q, options: q.options.filter((_, k) => k !== oi).map((o, k) => ({ ...o, order_index: k })) }
          : q,
      ),
    );

  async function save() {
    setError(null);
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    const clean = questions
      .map((q, i) => ({
        text: q.text.trim(),
        guidance: q.guidance.trim(),
        order_index: i,
        options: q.options
          .map((o, j) => ({
            label: o.label.trim(),
            score: typeof o.score === "number" ? o.score : 0,
            order_index: j,
          }))
          .filter((o) => o.label),
      }))
      .filter((q) => q.text);
    if (!clean.length) {
      setError("Add at least one question with text");
      return;
    }
    if (clean.some((q) => q.options.length === 0)) {
      setError("Every question needs at least one scored option");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await apiCall("PATCH", `/questionnaires/${editing.id}`, {
          name: name.trim(),
          description: description.trim(),
          questions: clean,
        });
        if (open?.id === editing.id) setOpen(await api.questionnaire(editing.id));
      } else {
        await api.createQuestionnaire({ name: name.trim(), description: description.trim(), questions: clean });
      }
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string, label: string) {
    if (!window.confirm(`Delete questionnaire "${label}"? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/questionnaires/${id}`);
      if (open?.id === id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const liveMax = useMemo(() => draftMax(questions), [questions]);

  const builder = (
    <>
      <div className="field-row">
        <Field label="Name" required help="For example: Security Baseline Assessment, SIG Lite, GDPR Processor Review.">
          <TextInput value={name} onChange={setName} placeholder="Security Baseline Assessment" required />
        </Field>
      </div>
      <Field label="Description" help="What this template measures and when to send it.">
        <TextArea value={description} onChange={setDescription} rows={2} placeholder="Short summary of scope and intent." />
      </Field>

      <div className="row-between" style={{ margin: "10px 0 6px" }}>
        <label className="label" style={{ margin: 0 }}>Questions</label>
        <span className="sub">{questions.length} question{questions.length === 1 ? "" : "s"} · max score {liveMax}</span>
      </div>

      {questions.map((q, qi) => (
        <div key={qi} className="card card-pad" style={{ marginBottom: 12, background: "var(--surface-2, transparent)" }}>
          <div className="row-between" style={{ marginBottom: 8 }}>
            <strong style={{ fontSize: 13 }}>
              Question {qi + 1}
              <Badge tone="info" plain>max {draftQMax(q)}</Badge>
            </strong>
            <div style={{ display: "flex", gap: 6 }}>
              <button type="button" className="btn secondary sm" disabled={qi === 0} onClick={() => moveQuestion(qi, -1)} aria-label="Move up">↑</button>
              <button type="button" className="btn secondary sm" disabled={qi === questions.length - 1} onClick={() => moveQuestion(qi, 1)} aria-label="Move down">↓</button>
              <button type="button" className="btn secondary sm" disabled={questions.length === 1} onClick={() => removeQuestion(qi)} aria-label="Remove question">✕</button>
            </div>
          </div>

          <Field label="Question text" required>
            <TextArea value={q.text} onChange={(v) => setQ(qi, { text: v })} rows={2} placeholder={`e.g. Do you perform annual penetration testing?`} />
          </Field>
          <Field label="Guidance" help="Optional helper text shown to the vendor answering this question.">
            <TextInput value={q.guidance} onChange={(v) => setQ(qi, { guidance: v })} placeholder="Attach the latest report if available." />
          </Field>

          <label className="label">Answer options (label + score)</label>
          {q.options.map((o, oi) => (
            <div key={oi} style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "center" }}>
              <div style={{ flex: 1 }}>
                <TextInput value={o.label} onChange={(v) => setOpt(qi, oi, { label: v })} placeholder={`Option ${oi + 1}`} />
              </div>
              <div style={{ width: 110 }}>
                <NumberInput value={o.score} onChange={(v) => setOpt(qi, oi, { score: v })} min={0} step={1} placeholder="score" />
              </div>
              <button
                type="button"
                className="btn secondary sm"
                disabled={q.options.length === 1}
                onClick={() => removeOpt(qi, oi)}
                aria-label="Remove option"
              >
                ✕
              </button>
            </div>
          ))}
          <button type="button" className="btn secondary sm" onClick={() => addOpt(qi)}>
            <IconPlus width={13} height={13} /> Add option
          </button>
        </div>
      ))}

      <button type="button" className="btn secondary" onClick={addQuestion}>
        <IconPlus width={15} height={15} /> Add question
      </button>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Questionnaires</h1>
          <p>Reusable assessment templates — questions with scored answer options sent to vendors.</p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} /> New questionnaire
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Templates</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Questions</th>
                <th>Max score</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((q) => (
                <tr key={q.id} style={{ cursor: "pointer" }} onClick={() => openEdit(q.id)}>
                  <td className="cell-title">{q.name}</td>
                  <td className="muted">{q.description || "—"}</td>
                  <td className="muted">{q.question_count}</td>
                  <td><Badge tone="info" plain>{q.max_score}</Badge></td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => view(q.id)}>
                        {open?.id === q.id ? "Hide" : "Preview"}
                      </button>
                      <button className="btn secondary sm" onClick={() => remove(q.id, q.name)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={5}>
                    <div className="empty">
                      <span className="ico"><IconPolicy width={24} height={24} /></span>
                      <h3>No questionnaires</h3>
                      <p>Create your first reusable template to start assessing vendors.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {open && (
        <div className="card">
          <div className="card-head">
            <div>
              <h3>{open.name}</h3>
              {open.description && <span className="sub">{open.description}</span>}
            </div>
            <span className="sub">{open.question_count} questions · max score {open.max_score}</span>
          </div>
          <div className="card-pad">
            {[...open.questions]
              .sort((a, b) => a.order_index - b.order_index)
              .map((q, i) => (
                <div key={q.id} style={{ padding: "10px 0", borderBottom: "1px solid var(--border)" }}>
                  <div style={{ fontSize: 13.5 }}>{i + 1}. {q.text}</div>
                  {q.guidance && <div className="when" style={{ marginTop: 2 }}>{q.guidance}</div>}
                  <div style={{ marginTop: 6, display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {q.options.map((o) => (
                      <Badge key={o.id} tone="neutral" plain>{o.label} = {o.score}</Badge>
                    ))}
                  </div>
                </div>
              ))}
            <div style={{ marginTop: 12 }}>
              <button className="btn secondary sm" onClick={() => openEdit(open.id)}>
                <IconCheck width={14} height={14} /> Edit template
              </button>
            </div>
          </div>
        </div>
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit questionnaire — ${editing.name}` : "New questionnaire"}
          wide
          tabs={[{ id: "builder", label: "Template & Questions", content: builder, required: true }]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create questionnaire"}
          footerLeft={<span className="sub">{questions.length} questions · max score {liveMax}</span>}
        />
      )}
    </>
  );
}
