"use client";

import { useEffect, useMemo, useState } from "react";
import {
  api,
  apiCall,
  type Assessment,
  type AssessmentSummary,
  type AssessmentFinding,
  type QuestionnaireSummary,
  type Vendor,
} from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconVendor, IconCheck } from "@/components/icons";

// the list endpoint now also returns the questionnaire ref + score totals
type Row = AssessmentSummary & {
  questionnaire?: { id: string; name: string } | null;
  questionnaire_id?: string;
  submitted_at?: string | null;
  max_score?: number;
  total_score?: number;
};

const STATUS = ["draft", "sent", "in_progress", "submitted", "reviewed"];
const SEVERITIES = ["low", "medium", "high", "critical"];
const FINDING_STATUS = ["open", "closed"];

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "info" | "neutral"> = {
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

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ---- assessment-header form state ------------------------------------------------
type HeaderForm = {
  title: string;
  vendor_id: string;
  questionnaire_id: string;
  due_date: string;
  status: string;
  review_notes: string;
};
const BLANK_HEADER: HeaderForm = {
  title: "",
  vendor_id: "",
  questionnaire_id: "",
  due_date: "",
  status: "draft",
  review_notes: "",
};

// ---- finding form state ----------------------------------------------------------
type FindingForm = {
  title: string;
  description: string;
  severity: string;
  status: string;
  deadline: string;
};
const BLANK_FINDING: FindingForm = {
  title: "",
  description: "",
  severity: "medium",
  status: "open",
  deadline: "",
};

export default function AssessmentsPage() {
  const [items, setItems] = useState<Row[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [qs, setQs] = useState<QuestionnaireSummary[]>([]);
  const [open, setOpen] = useState<Assessment | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [comments, setComments] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  // header modal
  const [showForm, setShowForm] = useState(false);
  const [editingHeader, setEditingHeader] = useState<Assessment | null>(null);
  const [savingHeader, setSavingHeader] = useState(false);
  const [hf, setHf] = useState<HeaderForm>(BLANK_HEADER);
  const setH = <K extends keyof HeaderForm>(k: K, v: HeaderForm[K]) => setHf((p) => ({ ...p, [k]: v }));

  // finding modal
  const [showFinding, setShowFinding] = useState(false);
  const [editingFinding, setEditingFinding] = useState<AssessmentFinding | null>(null);
  const [savingFinding, setSavingFinding] = useState(false);
  const [ff, setFf] = useState<FindingForm>(BLANK_FINDING);
  const setFF = <K extends keyof FindingForm>(k: K, v: FindingForm[K]) => setFf((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      const [a, v, q] = await Promise.all([api.assessments(), api.vendors(), api.questionnaires()]);
      setItems(a as Row[]);
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
      hydrate(a);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  function hydrate(a: Assessment) {
    setOpen(a);
    const m: Record<string, string> = {};
    const c: Record<string, string> = {};
    a.answers.forEach((ans) => {
      if (ans.option_id) m[ans.question_id] = ans.option_id;
      if (ans.comment) c[ans.question_id] = ans.comment;
    });
    setAnswers(m);
    setComments(c);
  }

  async function refreshOpen(id: string) {
    const a = await api.assessment(id);
    hydrate(a);
    await load();
  }

  // ---- answers -------------------------------------------------------------------
  async function saveAnswers(submit: boolean) {
    if (!open) return;
    setError(null);
    try {
      const touched = new Set([...Object.keys(answers), ...Object.keys(comments)]);
      const payload = [...touched].map((question_id) => ({
        question_id,
        option_id: answers[question_id] || null,
        comment: comments[question_id] || "",
      }));
      await api.submitAnswers(open.id, payload, submit);
      await refreshOpen(open.id);
      setNote(submit ? "Answers saved and assessment submitted." : "Answers saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    }
  }

  // ---- header create / edit ------------------------------------------------------
  function openNew() {
    setEditingHeader(null);
    setHf({ ...BLANK_HEADER, questionnaire_id: qs[0]?.id || "" });
    setError(null);
    setShowForm(true);
  }
  function openEditHeader(a: Assessment) {
    setEditingHeader(a);
    setHf({
      title: a.title,
      vendor_id: a.vendor_id || "",
      questionnaire_id: a.questionnaire_id,
      due_date: a.due_date || "",
      status: a.status,
      review_notes: a.review_notes || "",
    });
    setError(null);
    setShowForm(true);
  }

  async function saveHeader() {
    setError(null);
    if (!hf.title.trim()) {
      setError("Title is required");
      return;
    }
    if (!hf.questionnaire_id) {
      setError("Choose a questionnaire");
      return;
    }
    setSavingHeader(true);
    try {
      if (editingHeader) {
        const updated = await apiCall<Assessment>("PATCH", `/assessments/${editingHeader.id}`, {
          title: hf.title.trim(),
          vendor_id: hf.vendor_id || null,
          questionnaire_id: hf.questionnaire_id,
          due_date: hf.due_date || null,
          status: hf.status,
          review_notes: hf.review_notes,
        });
        if (open?.id === editingHeader.id) hydrate(updated);
      } else {
        await api.createAssessment({
          title: hf.title.trim(),
          vendor_id: hf.vendor_id || null,
          questionnaire_id: hf.questionnaire_id,
          due_date: hf.due_date || null,
          status: hf.status,
          review_notes: hf.review_notes,
        });
      }
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save assessment");
    } finally {
      setSavingHeader(false);
    }
  }

  async function removeAssessment(id: string, title: string) {
    if (!window.confirm(`Delete assessment "${title}"? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiCall("DELETE", `/assessments/${id}`);
      if (open?.id === id) setOpen(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ---- findings ------------------------------------------------------------------
  function openNewFinding() {
    setEditingFinding(null);
    setFf(BLANK_FINDING);
    setError(null);
    setShowFinding(true);
  }
  function openEditFinding(f: AssessmentFinding) {
    setEditingFinding(f);
    setFf({
      title: f.title,
      description: f.description || "",
      severity: f.severity,
      status: f.status,
      deadline: f.deadline || "",
    });
    setError(null);
    setShowFinding(true);
  }
  async function saveFinding() {
    if (!open) return;
    setError(null);
    if (!ff.title.trim()) {
      setError("Finding title is required");
      return;
    }
    setSavingFinding(true);
    try {
      const payload = {
        title: ff.title.trim(),
        description: ff.description,
        severity: ff.severity,
        status: ff.status,
        deadline: ff.deadline || null,
      };
      if (editingFinding) {
        await apiCall("PATCH", `/assessments/${open.id}/findings/${editingFinding.id}`, payload);
      } else {
        await api.addFinding(open.id, payload);
      }
      setShowFinding(false);
      await refreshOpen(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save finding");
    } finally {
      setSavingFinding(false);
    }
  }
  async function toggleFinding(f: AssessmentFinding) {
    if (!open) return;
    setError(null);
    try {
      if (f.status === "open") {
        await api.closeFinding(open.id, f.id);
      } else {
        await apiCall("PATCH", `/assessments/${open.id}/findings/${f.id}`, { status: "open" });
      }
      await refreshOpen(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update finding");
    }
  }

  const vendorOpts: Option[] = useMemo(
    () => vendors.map((v) => ({ value: v.id, label: v.name, sub: v.category })),
    [vendors],
  );
  const questionnaireOpts: Option[] = useMemo(
    () => qs.map((q) => ({ value: q.id, label: q.name, sub: `${q.question_count} q · max ${q.max_score}` })),
    [qs],
  );

  const scoreTone = (pct: number) => (pct >= 80 ? "low" : pct >= 50 ? "medium" : "critical");

  // ---- header form (tabbed) ------------------------------------------------------
  const detailsTab = (
    <>
      <Field label="Title" required help="For example: Stripe annual security review.">
        <TextInput value={hf.title} onChange={(v) => setH("title", v)} placeholder="Stripe annual security review" required />
      </Field>
      <div className="field-row">
        <Field label="Vendor" help="The third party being assessed (optional).">
          <Select value={hf.vendor_id} onChange={(v) => setH("vendor_id", v)} options={vendorOpts} placeholder="— none —" />
        </Field>
        <Field label="Questionnaire" required help="Template whose questions & scoring apply.">
          <Select value={hf.questionnaire_id} onChange={(v) => setH("questionnaire_id", v)} options={questionnaireOpts} placeholder="— select —" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Due date">
          <TextInput type="date" value={hf.due_date} onChange={(v) => setH("due_date", v)} />
        </Field>
        <Field label="Status">
          <Select value={hf.status} onChange={(v) => setH("status", v)} options={opts(STATUS)} />
        </Field>
      </div>
      <Field label="Review notes" help="Internal notes from the reviewer about this assessment.">
        <TextArea value={hf.review_notes} onChange={(v) => setH("review_notes", v)} rows={3} placeholder="Observations, scope caveats, follow-ups…" />
      </Field>
    </>
  );

  // ---- finding form --------------------------------------------------------------
  const findingTab = (
    <>
      <Field label="Title" required help="Short summary of the gap.">
        <TextInput value={ff.title} onChange={(v) => setFF("title", v)} placeholder="No penetration testing performed" required />
      </Field>
      <Field label="Description" help="Detail the gap, impact and recommended remediation.">
        <TextArea value={ff.description} onChange={(v) => setFF("description", v)} rows={4} placeholder="Vendor confirmed they have never run an external pentest…" />
      </Field>
      <div className="field-row">
        <Field label="Severity">
          <Select value={ff.severity} onChange={(v) => setFF("severity", v)} options={opts(SEVERITIES)} />
        </Field>
        <Field label="Status">
          <Select value={ff.status} onChange={(v) => setFF("status", v)} options={opts(FINDING_STATUS)} />
        </Field>
        <Field label="Remediation deadline">
          <TextInput type="date" value={ff.deadline} onChange={(v) => setFF("deadline", v)} />
        </Field>
      </div>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Vendor Assessments</h1>
          <p>Send scored questionnaires to third parties, capture answers, and track findings to closure.</p>
        </div>
        <button className="btn" onClick={openNew} disabled={qs.length === 0}>
          <IconPlus width={16} height={16} /> New assessment
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
      {note && (
        <div className="card card-pad" style={{ marginBottom: 16, borderColor: "var(--primary)" }}>{note}</div>
      )}
      {qs.length === 0 && (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <span className="muted">Create a questionnaire first (Questionnaires page) to run assessments.</span>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Assessments</h3>
          <span className="sub">{items.length} total · click a row to answer</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Vendor</th>
                <th>Questionnaire</th>
                <th>Status</th>
                <th>Due</th>
                <th>Progress</th>
                <th>Score</th>
                <th>Findings</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} style={{ cursor: "pointer" }} onClick={() => openAssessment(a.id)}>
                  <td className="cell-title">{a.title}</td>
                  <td className="muted">{a.vendor ? a.vendor.name : "—"}</td>
                  <td className="muted">{a.questionnaire ? a.questionnaire.name : "—"}</td>
                  <td><Badge tone={STATUS_TONE[a.status] || "neutral"}>{cap(a.status)}</Badge></td>
                  <td className="muted">{a.due_date || "—"}</td>
                  <td className="muted">{a.answered_count}/{a.question_count}</td>
                  <td><Badge tone={scoreTone(a.score_pct)} plain>{a.score_pct}%</Badge></td>
                  <td>{a.open_findings > 0 ? <Badge tone="high">{a.open_findings}</Badge> : <span className="muted">0</span>}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => openAssessment(a.id)}>
                        {open?.id === a.id ? "Hide" : "Open"}
                      </button>
                      <button className="btn secondary sm" onClick={() => removeAssessment(a.id, a.title)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconVendor width={24} height={24} /></span>
                      <h3>No assessments</h3>
                      <p>Send your first scored questionnaire to a vendor.</p>
                    </div>
                  </td>
                </tr>
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
                <span className="sub">
                  {open.questionnaire?.name}
                  {open.vendor ? ` · ${open.vendor.name}` : ""}
                  {" · "}
                  <Badge tone={STATUS_TONE[open.status] || "neutral"}>{cap(open.status)}</Badge>
                  {open.due_date ? ` · due ${open.due_date}` : ""}
                  {open.submitted_at ? ` · submitted ${open.submitted_at}` : ""}
                </span>
              </div>
              <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: 22, fontWeight: 700 }}>{open.score_pct}%</div>
                  <span className="muted" style={{ fontSize: 12 }}>{open.total_score} / {open.max_score}</span>
                </div>
                <button className="btn secondary sm" onClick={() => openEditHeader(open)}>
                  <IconCheck width={14} height={14} /> Edit
                </button>
              </div>
            </div>
            <div className="card-pad">
              {open.review_notes && (
                <div className="card card-pad" style={{ marginBottom: 12, background: "var(--surface-2, transparent)" }}>
                  <div className="label" style={{ margin: 0 }}>Review notes</div>
                  <div className="muted" style={{ fontSize: 13 }}>{open.review_notes}</div>
                </div>
              )}
              {[...(open.questionnaire?.questions || [])]
                .sort((a, b) => a.order_index - b.order_index)
                .map((q, i) => (
                  <div key={q.id} style={{ padding: "12px 0", borderBottom: "1px solid var(--border)" }}>
                    <div style={{ fontSize: 13.5, marginBottom: 2 }}>{i + 1}. {q.text}</div>
                    {q.guidance && <div className="when" style={{ marginBottom: 6 }}>{q.guidance}</div>}
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
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
                    <input
                      className="input"
                      style={{ marginTop: 8 }}
                      value={comments[q.id] || ""}
                      placeholder="Comment (optional)…"
                      onChange={(e) => setComments({ ...comments, [q.id]: e.target.value })}
                    />
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
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span className="sub">{open.findings.length} total · {open.open_findings} open</span>
                <button className="btn secondary sm" onClick={openNewFinding}>
                  <IconPlus width={14} height={14} /> Add finding
                </button>
              </div>
            </div>
            <div className="card-pad">
              {open.findings.map((f) => (
                <div key={f.id} className="activity-item">
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13 }}>{f.title}</div>
                    {f.description && <div className="when">{f.description}</div>}
                    {f.deadline && <div className="when">Deadline: {f.deadline}</div>}
                  </div>
                  <Badge tone={SEV_TONE[f.severity] || "neutral"}>{f.severity}</Badge>
                  <Badge tone={f.status === "open" ? "high" : "neutral"}>{f.status}</Badge>
                  <button className="btn secondary sm" onClick={() => openEditFinding(f)}>Edit</button>
                  <button className="btn secondary sm" onClick={() => toggleFinding(f)}>
                    {f.status === "open" ? "Close" : "Reopen"}
                  </button>
                </div>
              ))}
              {open.findings.length === 0 && <span className="muted">No findings recorded.</span>}
            </div>
          </div>
        </>
      )}

      {showForm && (
        <FormModal
          title={editingHeader ? `Edit assessment — ${editingHeader.title}` : "New vendor assessment"}
          tabs={[{ id: "details", label: "Details", content: detailsTab, required: true }]}
          onClose={() => setShowForm(false)}
          onSave={saveHeader}
          saving={savingHeader}
          error={error}
          saveLabel={editingHeader ? "Save changes" : "Create assessment"}
        />
      )}

      {showFinding && (
        <FormModal
          title={editingFinding ? "Edit finding" : "Add finding"}
          tabs={[{ id: "finding", label: "Finding", content: findingTab, required: true }]}
          onClose={() => setShowFinding(false)}
          onSave={saveFinding}
          saving={savingFinding}
          error={error}
          saveLabel={editingFinding ? "Save changes" : "Add finding"}
        />
      )}
    </>
  );
}
