"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  apiCall,
  type Assessment,
  type AssessmentSummary,
  type AssessmentFinding,
  type QuestionnaireSummary,
  type Vendor,
} from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconCheck } from "@/components/icons";

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

function AssessmentsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Assessment | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [comments, setComments] = useState<Record<string, string>>({});

  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [qs, setQs] = useState<QuestionnaireSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

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

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchAssessments = useCallback((query: string) => apiCall<PagedList<Row>>("GET", `/assessments?${query}`), []);

  function hydrate(a: Assessment) {
    setDetail(a);
    const m: Record<string, string> = {};
    const c: Record<string, string> = {};
    a.answers.forEach((ans) => {
      if (ans.option_id) m[ans.question_id] = ans.option_id;
      if (ans.comment) c[ans.question_id] = ans.comment;
    });
    setAnswers(m);
    setComments(c);
  }

  const loadDetail = useCallback((id: string) => {
    api.assessment(id).then(hydrate).catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, []);

  useEffect(() => {
    if (openId) loadDetail(openId);
    else {
      setDetail(null);
      setAnswers({});
      setComments({});
    }
  }, [openId, loadDetail]);

  // reference data for the header form
  useEffect(() => {
    apiCall<PagedList<QuestionnaireSummary>>("GET", "/questionnaires?limit=200")
      .then((r) => setQs(r.items))
      .catch(() => setQs([]));
    api.vendors().then((v) => setVendors(v.items)).catch(() => setVendors([]));
  }, []);

  // ---- answers -------------------------------------------------------------------
  async function saveAnswers(submit: boolean) {
    if (!detail) return;
    setError(null);
    try {
      const touched = new Set([...Object.keys(answers), ...Object.keys(comments)]);
      const payload = [...touched].map((question_id) => ({
        question_id,
        option_id: answers[question_id] || null,
        comment: comments[question_id] || "",
      }));
      await api.submitAnswers(detail.id, payload, submit);
      loadDetail(detail.id);
      reload();
      toast(submit ? "Answers saved and assessment submitted" : "Answers saved");
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
      const payload = {
        title: hf.title.trim(),
        vendor_id: hf.vendor_id || null,
        questionnaire_id: hf.questionnaire_id,
        due_date: hf.due_date || null,
        status: hf.status,
        review_notes: hf.review_notes,
      };
      if (editingHeader) {
        const updated = await apiCall<Assessment>("PATCH", `/assessments/${editingHeader.id}`, payload);
        if (openId === editingHeader.id) hydrate(updated);
      } else {
        await api.createAssessment(payload);
      }
      setShowForm(false);
      reload();
      toast(editingHeader ? "Changes saved" : "Assessment created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save assessment");
    } finally {
      setSavingHeader(false);
    }
  }

  async function removeAssessment(a: Row | Assessment) {
    if (!(await confirmDialog({ title: `Delete assessment "${a.title}"?`, message: "This cannot be undone.", danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/assessments/${a.id}`);
      if (openId === a.id) setOpenId(null);
      reload();
      toast("Deleted");
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
    if (!detail) return;
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
        await apiCall("PATCH", `/assessments/${detail.id}/findings/${editingFinding.id}`, payload);
      } else {
        await api.addFinding(detail.id, payload);
      }
      setShowFinding(false);
      loadDetail(detail.id);
      reload();
      toast(editingFinding ? "Finding updated" : "Finding added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save finding");
    } finally {
      setSavingFinding(false);
    }
  }
  async function toggleFinding(f: AssessmentFinding) {
    if (!detail) return;
    setError(null);
    try {
      if (f.status === "open") {
        await api.closeFinding(detail.id, f.id);
      } else {
        await apiCall("PATCH", `/assessments/${detail.id}/findings/${f.id}`, { status: "open" });
      }
      loadDetail(detail.id);
      reload();
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

  const columns: Column<Row>[] = [
    { key: "title", header: "Title", sortable: true, render: (a) => <span className="cell-title">{a.title}</span> },
    { key: "vendor", header: "Vendor", render: (a) => <span className="muted">{a.vendor ? a.vendor.name : "—"}</span> },
    { key: "questionnaire", header: "Questionnaire", render: (a) => <span className="muted">{a.questionnaire ? a.questionnaire.name : "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (a) => <Badge tone={STATUS_TONE[a.status] || "neutral"}>{cap(a.status)}</Badge> },
    { key: "due_date", header: "Due", sortable: true, render: (a) => <span className="muted">{a.due_date || "—"}</span> },
    { key: "progress", header: "Progress", render: (a) => <span className="muted">{a.answered_count}/{a.question_count}</span> },
    { key: "score", header: "Score", render: (a) => <Badge tone={scoreTone(a.score_pct)} plain>{a.score_pct}%</Badge> },
    { key: "findings", header: "Findings", align: "center", render: (a) => (a.open_findings > 0 ? <Badge tone="high">{a.open_findings}</Badge> : <span className="muted">0</span>) },
    {
      key: "actions",
      header: "",
      render: (a) => (
        <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => setOpenId(a.id)}>{openId === a.id ? "Hide" : "Open"}</button>
          <button className="btn secondary sm" onClick={() => removeAssessment(a)}>Delete</button>
        </div>
      ),
    },
  ];

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
      {qs.length === 0 && (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <span className="muted">Create a questionnaire first (Questionnaires page) to run assessments.</span>
        </div>
      )}

      <DataTable<Row>
        columns={columns}
        fetcher={fetchAssessments}
        rowKey={(a) => a.id}
        onRowClick={(a) => setOpenId(a.id)}
        activeKey={openId}
        searchPlaceholder="Search assessments by title…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No assessments. Send your first scored questionnaire to a vendor."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail?.title || "…"}
        subtitle={
          detail
            ? `${detail.questionnaire?.name || ""}${detail.vendor ? " · " + detail.vendor.name : ""} · ${cap(detail.status)}${detail.due_date ? " · due " + detail.due_date : ""}${detail.submitted_at ? " · submitted " + detail.submitted_at : ""}`
            : ""
        }
        width={760}
        actions={detail && (
          <button className="btn secondary sm" onClick={() => openEditHeader(detail)}>
            <IconCheck width={14} height={14} /> Edit
          </button>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 14 }}>
              <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 22, fontWeight: 700 }}>{detail.score_pct}%</div>
                <span className="muted" style={{ fontSize: 12 }}>{detail.total_score} / {detail.max_score}</span>
              </div>
            </div>

            {detail.review_notes && (
              <div className="card card-pad" style={{ marginBottom: 12, background: "var(--surface-2, transparent)" }}>
                <div className="label" style={{ margin: 0 }}>Review notes</div>
                <div className="muted" style={{ fontSize: 13 }}>{detail.review_notes}</div>
              </div>
            )}

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Questions</h3><span className="sub">{detail.answered_count}/{detail.question_count} answered</span></div>
              <div className="card-pad">
                {[...(detail.questionnaire?.questions || [])]
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
                  <span className="sub">{detail.findings.length} total · {detail.open_findings} open</span>
                  <button className="btn secondary sm" onClick={openNewFinding}>
                    <IconPlus width={14} height={14} /> Add finding
                  </button>
                </div>
              </div>
              <div className="card-pad">
                {detail.findings.map((f) => (
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
                {detail.findings.length === 0 && <span className="muted">No findings recorded.</span>}
              </div>
            </div>
          </>
        )}
      </RecordDrawer>

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

export default function AssessmentsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <AssessmentsInner />
    </Suspense>
  );
}
