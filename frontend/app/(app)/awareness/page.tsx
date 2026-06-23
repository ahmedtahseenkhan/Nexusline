"use client";

import { useEffect, useState } from "react";
import { api, apiCall, type AwarenessProgram, type TrainingRecord, type AwQuestion } from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import RichText from "@/components/RichText";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconUsers } from "@/components/icons";

// ----------------------------------------------------------------- enum options
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "active", "closed"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);

const STATUS_TONE: Record<string, "low" | "medium" | "neutral" | "info"> = {
  active: "low",
  closed: "neutral",
  draft: "medium",
};
const REC_TONE: Record<string, "info" | "neutral"> = { completed: "info", assigned: "neutral" };

// ------------------------------------------------------------------- quiz model
type QOpt = { label: string; is_correct: boolean };
type QBuilder = { text: string; options: QOpt[]; correct: number };

const blankQuestion = (): QBuilder => ({ text: "", options: [{ label: "", is_correct: true }, { label: "", is_correct: false }], correct: 0 });

function questionsFrom(qs: AwQuestion[]): QBuilder[] {
  return qs.map((q) => {
    const correct = Math.max(0, q.options.findIndex((o) => o.is_correct));
    return { text: q.text, options: q.options.map((o) => ({ label: o.label, is_correct: o.is_correct })), correct };
  });
}

// payload shape the API expects for create/replace of the quiz
function questionsPayload(qs: QBuilder[]) {
  return qs
    .filter((q) => q.text.trim())
    .map((q, i) => ({
      text: q.text,
      order_index: i,
      options: q.options
        .filter((o) => o.label.trim())
        .map((o, j) => ({ label: o.label, is_correct: j === q.correct, order_index: j })),
    }));
}

// ------------------------------------------------------------------- form state
type FormState = {
  name: string;
  description: string;
  content: string;
  status: string;
  frequency: string;
  passing_score: number | "";
  due_date: string;
  questions: QBuilder[];
};

const BLANK: FormState = {
  name: "",
  description: "",
  content: "",
  status: "draft",
  frequency: "annual",
  passing_score: 80,
  due_date: "",
  questions: [],
};

function fromProgram(p: AwarenessProgram): FormState {
  return {
    name: p.name,
    description: p.description || "",
    content: p.content || "",
    status: p.status,
    frequency: p.frequency || "annual",
    passing_score: p.passing_score,
    due_date: p.due_date || "",
    questions: questionsFrom(p.questions || []),
  };
}

export default function AwarenessPage() {
  const [items, setItems] = useState<AwarenessProgram[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<AwarenessProgram | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  // training-records (children of the program being edited) management state
  const [pname, setPname] = useState("");
  const [pemail, setPemail] = useState("");
  const [pscore, setPscore] = useState<number | "">("");
  const [pdone, setPdone] = useState(false);
  const [quizFor, setQuizFor] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems(await api.awarenessPrograms());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setQuizFor(null);
    setShowForm(true);
  }
  async function openEdit(id: string) {
    setError(null);
    try {
      const full = await api.awarenessProgram(id);
      setEditing(full);
      setF(fromProgram(full));
      setQuizFor(null);
      setShowForm(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to open program");
    }
  }

  /** Re-fetch the program being edited and refresh its form-bound child state. */
  async function refreshEditing(id: string) {
    const full = await api.awarenessProgram(id);
    setEditing(full);
    await load();
    return full;
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = {
        name: f.name,
        description: f.description,
        content: f.content,
        status: f.status,
        frequency: f.frequency,
        passing_score: f.passing_score === "" ? 0 : f.passing_score,
        due_date: f.due_date || null,
        questions: questionsPayload(f.questions),
      };
      if (editing) {
        await apiCall<AwarenessProgram>("PATCH", `/awareness-programs/${editing.id}`, payload);
      } else {
        await api.createAwarenessProgram(payload);
      }
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save program");
    } finally {
      setSaving(false);
    }
  }

  async function removeProgram(id: string, ref: string) {
    if (!window.confirm(`Delete program ${ref}? This removes its quiz and training records.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/awareness-programs/${id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // --------------------------------------------------------------- child: records
  async function childAct(fn: Promise<unknown>) {
    if (!editing) return;
    setError(null);
    try {
      await fn;
      await refreshEditing(editing.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function addRecord() {
    if (!editing || !pname.trim()) return;
    const done = pdone || pscore !== "";
    await childAct(
      api.addParticipant(editing.id, {
        participant_name: pname,
        participant_email: pemail,
        status: done ? "completed" : "assigned",
        score: pscore === "" ? null : pscore,
        completed_at: done ? new Date().toISOString().slice(0, 10) : null,
      }),
    );
    setPname("");
    setPemail("");
    setPscore("");
    setPdone(false);
  }

  function compliant(p: TrainingRecord, prog: AwarenessProgram) {
    return p.status === "completed" && p.score != null && p.score >= prog.passing_score;
  }

  // -------------------------------------------------------------------- quiz tab
  const quizCorrectCount = f.questions.filter((q) => q.text.trim() && q.options.some((o, j) => j === q.correct && o.label.trim())).length;

  const generalTab = (
    <>
      <Field label="Name" required help="For example: Phishing Awareness 2026, Annual Security Training, etc.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Phishing Awareness 2026" required />
      </Field>
      <Field label="Description / Target audience" help="Who must take this and why — e.g. 'All staff', 'New joiners', engineering team.">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="All employees. Covers recognising and reporting phishing." />
      </Field>
      <div className="field-row">
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Frequency" help="How often participants must re-take the program.">
          <Select value={f.frequency} onChange={(v) => set("frequency", v)} options={FREQ} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Passing score %" help="Minimum quiz score for a participant to be marked compliant.">
          <NumberInput value={f.passing_score} onChange={(v) => set("passing_score", v)} min={0} max={100} />
        </Field>
        <Field label="Due date" help="Optional deadline for completing this cycle.">
          <TextInput type="date" value={f.due_date} onChange={(v) => set("due_date", v)} />
        </Field>
      </div>
    </>
  );

  const contentTab = (
    <Field label="Training material" help="Inline training content, instructions, or a link to the course / video participants should review before the quiz.">
      <RichText value={f.content} onChange={(v) => set("content", v)} placeholder="Write the training material…" />
    </Field>
  );

  const quizTab = (
    <>
      <div className="row-between" style={{ marginBottom: 12 }}>
        <div className="help" style={{ marginTop: 0 }}>
          Build the quiz: add questions, fill the answer options, and select the one correct option per question.
        </div>
        <Badge tone="neutral" plain>{quizCorrectCount} ready</Badge>
      </div>

      {f.questions.map((q, qi) => (
        <div key={qi} className="card card-pad" style={{ marginBottom: 10, background: "var(--surface-2)" }}>
          <div className="row-between" style={{ marginBottom: 8 }}>
            <strong style={{ fontSize: 13 }}>Question {qi + 1}</strong>
            <button
              type="button"
              className="btn secondary sm"
              onClick={() => set("questions", f.questions.filter((_, i) => i !== qi))}
            >
              Remove
            </button>
          </div>
          <TextInput
            value={q.text}
            onChange={(v) => set("questions", f.questions.map((x, i) => (i === qi ? { ...x, text: v } : x)))}
            placeholder={`What does a phishing email often try to do?`}
          />
          <div className="help" style={{ marginTop: 8 }}>Options — select the correct answer:</div>
          {q.options.map((o, oi) => (
            <div key={oi} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
              <input
                type="radio"
                name={`correct-${qi}`}
                checked={q.correct === oi}
                onChange={() => set("questions", f.questions.map((x, i) => (i === qi ? { ...x, correct: oi } : x)))}
                title="Mark as correct answer"
              />
              <div style={{ flex: 1 }}>
                <TextInput
                  value={o.label}
                  onChange={(v) =>
                    set("questions", f.questions.map((x, i) => (i === qi ? { ...x, options: x.options.map((y, j) => (j === oi ? { ...y, label: v } : y)) } : x)))
                  }
                  placeholder={`Option ${oi + 1}`}
                />
              </div>
              {q.options.length > 2 && (
                <button
                  type="button"
                  className="btn secondary sm"
                  onClick={() =>
                    set("questions", f.questions.map((x, i) => {
                      if (i !== qi) return x;
                      const options = x.options.filter((_, j) => j !== oi);
                      const correct = x.correct === oi ? 0 : x.correct > oi ? x.correct - 1 : x.correct;
                      return { ...x, options, correct };
                    }))
                  }
                  aria-label="Remove option"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="btn secondary sm"
            style={{ marginTop: 8 }}
            onClick={() =>
              set("questions", f.questions.map((x, i) => (i === qi ? { ...x, options: [...x.options, { label: "", is_correct: false }] } : x)))
            }
          >
            <IconPlus width={14} height={14} /> Add option
          </button>
        </div>
      ))}

      <button type="button" className="btn secondary sm" onClick={() => set("questions", [...f.questions, blankQuestion()])}>
        <IconPlus width={14} height={14} /> Add question
      </button>
      {f.questions.length === 0 && (
        <div className="muted" style={{ marginTop: 10, fontSize: 13 }}>No questions yet. A program can be saved without a quiz.</div>
      )}
    </>
  );

  const recordsTab = editing ? (
    <>
      <div className="help" style={{ marginTop: 0, marginBottom: 10 }}>
        Per-participant completion. Compliance requires status <em>completed</em> and a score ≥ {editing.passing_score}%.
      </div>
      <div className="table-wrap" style={{ marginBottom: 14 }}>
        <table>
          <thead>
            <tr><th>Participant</th><th>Status</th><th>Score</th><th>Completed</th><th>Compliant</th><th></th></tr>
          </thead>
          <tbody>
            {editing.participants.map((p) => (
              <tr key={p.id}>
                <td className="cell-title">
                  {p.participant_name}
                  {p.participant_email && <div className="when">{p.participant_email}</div>}
                </td>
                <td><Badge tone={REC_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                <td className="muted">{p.score != null ? `${p.score}%` : "—"}</td>
                <td className="muted">{p.completed_at || "—"}</td>
                <td>
                  {p.status === "completed"
                    ? <Badge tone={compliant(p, editing) ? "low" : "critical"}>{compliant(p, editing) ? "yes" : "no"}</Badge>
                    : <span className="muted">—</span>}
                </td>
                <td>
                  <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                    {p.status !== "completed" && (editing.question_count > 0) && (
                      <button className="btn secondary sm" type="button" onClick={() => { setQuizFor(quizFor === p.id ? null : p.id); setAnswers({}); }}>
                        {quizFor === p.id ? "Close quiz" : "Take quiz"}
                      </button>
                    )}
                    {p.status !== "completed" && (
                      <button
                        className="btn secondary sm"
                        type="button"
                        onClick={() => childAct(apiCall("PATCH", `/awareness-programs/${editing.id}/participants/${p.id}`, { status: "completed", completed_at: new Date().toISOString().slice(0, 10) }))}
                      >
                        <IconCheck width={14} height={14} /> Mark done
                      </button>
                    )}
                    <button
                      className="btn secondary sm"
                      type="button"
                      onClick={() => window.confirm(`Remove ${p.participant_name}?`) && childAct(apiCall("DELETE", `/awareness-programs/${editing.id}/participants/${p.id}`))}
                    >
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {editing.participants.length === 0 && (
              <tr><td colSpan={6} className="muted" style={{ padding: 14 }}>No training records yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {quizFor && (
        <div className="card card-pad" style={{ marginBottom: 14, background: "var(--surface-2)" }}>
          <strong style={{ fontSize: 13 }}>Take quiz — auto-scores on submit</strong>
          {editing.questions.map((q, i) => (
            <div key={q.id} style={{ padding: "8px 0" }}>
              <div style={{ fontSize: 13 }}>{i + 1}. {q.text}</div>
              <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
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
                      {o.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn sm" type="button" onClick={() => childAct(api.submitQuiz(editing.id, quizFor, answers)).then(() => setQuizFor(null))}>
              Submit quiz
            </button>
            <button className="btn secondary sm" type="button" onClick={() => setQuizFor(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="card card-pad" style={{ background: "var(--surface-2)" }}>
        <strong style={{ fontSize: 13 }}>Add training record</strong>
        <div className="field-row" style={{ marginTop: 8 }}>
          <Field label="Participant name">
            <TextInput value={pname} onChange={setPname} placeholder="Jane Doe" />
          </Field>
          <Field label="Email">
            <TextInput value={pemail} onChange={setPemail} placeholder="jane@example.com" />
          </Field>
        </div>
        <div className="field-row">
          <Field label="Score % (optional)" help="Provide a score to record an off-platform completion.">
            <NumberInput value={pscore} onChange={setPscore} min={0} max={100} placeholder="—" />
          </Field>
          <Field label="Mark completed">
            <label className="switch">
              <input type="checkbox" checked={pdone} onChange={(e) => setPdone(e.target.checked)} />
              <span className="track" />
              <span className="txt">Completed now</span>
            </label>
          </Field>
        </div>
        <button className="btn sm" type="button" onClick={addRecord}>
          <IconPlus width={14} height={14} /> Add record
        </button>
      </div>
    </>
  ) : (
    <div className="muted" style={{ fontSize: 13 }}>Save the program first, then re-open it to assign participants and track completion.</div>
  );

  const tabs = [
    { id: "general", label: "General", content: generalTab, required: true },
    { id: "content", label: "Training Material", content: contentTab },
    { id: "quiz", label: `Quiz${f.questions.length ? ` (${f.questions.length})` : ""}`, content: quizTab },
    { id: "records", label: editing ? `Training Records (${editing.participants.length})` : "Training Records", content: recordsTab },
  ];

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Awareness Training</h1>
          <p>Recurring security-awareness programs with a quiz and per-participant completion / compliance tracking.</p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} /> Add program
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Programs</h3>
          <span className="sub">{items.length} total · click a row to manage</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Name</th>
                <th>Status</th>
                <th>Frequency</th>
                <th>Questions</th>
                <th>Participants</th>
                <th>Completion</th>
                <th>Compliance</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => openEdit(p.id)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">
                    {p.name}
                    {p.description && <div className="when">{p.description}</div>}
                  </td>
                  <td><Badge tone={STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                  <td className="muted">{cap(p.frequency || "—")}</td>
                  <td className="muted">{p.question_count}</td>
                  <td className="muted">{p.participant_count}</td>
                  <td className="muted">{p.completed_count}/{p.participant_count}</td>
                  <td>
                    <Badge tone={p.compliance_pct >= 80 ? "low" : p.compliance_pct >= 50 ? "medium" : "critical"} plain>
                      {p.compliance_pct}%
                    </Badge>
                  </td>
                  <td>
                    <div onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => removeProgram(p.id, p.reference)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconUsers width={24} height={24} /></span>
                      <h3>No programs</h3>
                      <p>Create your first awareness program to build a quiz and track completion.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showForm && (
        <FormModal
          title={editing ? `Edit program — ${editing.reference}` : "Add item (Awareness Training)"}
          tabs={tabs}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create program"}
          wide
        />
      )}
    </>
  );
}
