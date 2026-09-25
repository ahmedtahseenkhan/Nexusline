"use client";

/* Assessments: run a questionnaire version for a vendor, an RCSA, or on its own (phase 4E).

   Draft → Send (a personal link for the contact, e-mailed, shown once here) → the respondent
   answers in the portal (or someone answers here) → Submit → the reviewer accepts or returns
   each answer → Return sends returned answers back → Final review by someone other than the
   sender scores it and applies the results: tiering sets the vendor tier, due diligence the
   vendor's risk rating, RCSA runs the control self-ratings. Flagged answers raise findings;
   a finding can be raised to an Issue. */

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, apiCall, uploadMultipart, type RcsaAssessment, type Vendor } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFormat } from "@/lib/format";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import FormModal from "@/components/FormModal";
import CustomFieldsPanel from "@/components/CustomFieldsPanel";
import { useCustomFieldForm } from "@/components/useCustomFieldForm";
import QuestionnaireForm from "@/components/QuestionnaireForm";
import UserPicker from "@/components/UserPicker";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import { bandFor, score } from "@/lib/questionnaireLogic";
import {
  PURPOSE_LABEL, STATUS_LABEL, answerValues, asSpec, blankDraft, draftFromAnswer, fileSize, formSections, submitPayload,
  type AccessLogApi, type AnswerApi, type AssessmentApi, type AssessmentRowApi, type Draft, type FindingApi, type FormQuestion,
  type LinkApi, type LinkIssuedApi, type QuestionnaireSummaryApi,
} from "@/lib/questionnaire";

const STATUSES = ["draft", "sent", "in_progress", "submitted", "reviewed"];
const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "info" | "neutral"> = {
  reviewed: "low", submitted: "info", in_progress: "medium", sent: "medium", draft: "neutral",
};
const SEVERITIES = ["low", "medium", "high", "critical"];
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1).replace(/_/g, " ") : s);
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

type HeaderForm = {
  title: string; vendor_id: string; questionnaire_id: string; due_date: string; contact_name: string; contact_email: string;
  reviewer_id: string | null; recurrence_months: number | ""; review_notes: string;
};
const BLANK: HeaderForm = { title: "", vendor_id: "", questionnaire_id: "", due_date: "", contact_name: "", contact_email: "", reviewer_id: null, recurrence_months: "", review_notes: "" };

function AssessmentsInner() {
  const { formatDate, formatDateTime } = useFormat();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<AssessmentApi | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [dirty, setDirty] = useState(false);
  const [links, setLinks] = useState<LinkApi[]>([]);
  const [log, setLog] = useState<AccessLogApi[]>([]);
  const [view, setView] = useState<"answers" | "findings" | "links" | "log">("answers");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const cfForm = useCustomFieldForm("assessment");
  const [filters, setFilters] = useState<{ status: string; purpose: string; overdue: string }>({ status: "", purpose: "", overdue: "" });

  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [qs, setQs] = useState<QuestionnaireSummaryApi[]>([]);
  const [rcsas, setRcsas] = useState<RcsaAssessment[]>([]);

  const [header, setHeader] = useState<{ editing: AssessmentApi | null; form: HeaderForm } | null>(null);
  const [send, setSend] = useState<{ name: string; email: string; days: number | ""; message: string; mode: "send" | "link" | "resend"; linkId?: string } | null>(null);
  const [issued, setIssued] = useState<LinkIssuedApi | null>(null);
  const [raise, setRaise] = useState<{ finding: FindingApi; owner_id: string | null; due_date: string; severity: string } | null>(null);
  const [finding, setFinding] = useState<{ editing: FindingApi | null; title: string; description: string; severity: string; deadline: string } | null>(null);
  const [rcsaRun, setRcsaRun] = useState<{ rcsa_id: string; due_date: string; reviewer_id: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [modalError, setModalError] = useState<string | null>(null);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetcher = useCallback((query: string) => apiCall<PagedList<AssessmentRowApi>>("GET", `/assessments?${query}`), []);

  const hydrate = useCallback((a: AssessmentApi) => {
    setDetail(a);
    const d: Record<string, Draft> = {};
    a.answers.forEach((x) => { d[x.question_id] = draftFromAnswer(x); });
    setDrafts(d);
    setDirty(false);
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    try {
      hydrate(await apiCall<AssessmentApi>("GET", `/assessments/${id}`));
      setLinks(await apiCall<LinkApi[]>("GET", `/assessments/${id}/links`));
      setLog(await apiCall<AccessLogApi[]>("GET", `/assessments/${id}/access-log?limit=100`));
    } catch (e) {
      setError(errText(e, "Failed to load the assessment"));
    }
  }, [hydrate]);

  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);
  useEffect(() => {
    apiCall<PagedList<QuestionnaireSummaryApi>>("GET", "/questionnaires?published_only=true&limit=200").then((r) => setQs(r.items)).catch(() => setQs([]));
    api.vendors().then((v) => setVendors(v.items)).catch(() => setVendors([]));
    api.rcsaList().then((r) => setRcsas(r.items)).catch(() => setRcsas([]));
  }, []);

  const sections = useMemo(() => (detail?.questionnaire ? formSections(detail.questionnaire) : []), [detail]);
  const answersById = useMemo(() => new Map((detail?.answers || []).map((a) => [a.question_id, a])), [detail]);
  const fileCounts = useMemo(() => {
    const m: Record<string, number> = {};
    detail?.answers.forEach((a) => { m[a.question_id] = a.files.length; });
    return m;
  }, [detail]);
  const live = useMemo(() => score(asSpec(sections), answerValues(sections, drafts, fileCounts)), [sections, drafts, fileCounts]);
  const state = detail?.status || "";
  const answering = ["draft", "sent", "in_progress"].includes(state);
  const reviewing = state === "submitted";
  // The server says what may change in a returned round: the returned answers, those
  // revised since, and the follow-up questions they show.
  const reopened = useMemo(
    () => (detail?.reopened_question_ids ? new Set(detail.reopened_question_ids) : null),
    [detail],
  );

  async function act<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
    setError(null);
    try {
      const r = await fn();
      if (ok) toast(ok);
      return r;
    } catch (e) {
      setError(errText(e, "That did not work"));
      return undefined;
    }
  }

  async function saveAnswers(submit: boolean) {
    if (!detail) return;
    const payload = sections.flatMap((s) => s.questions)
      .filter((q) => drafts[q.id] && (!reopened || reopened.has(q.id)))
      .map((q) => submitPayload(q.id, q.type, drafts[q.id]));
    const a = await act(() => apiCall<AssessmentApi>("POST", `/assessments/${detail.id}/answers`, { answers: payload, submit }), submit ? "Submitted" : "Answers saved");
    if (a) { hydrate(a); reload(); }
  }

  async function reviewAnswer(answer: AnswerApi, decision: "accept" | "return") {
    if (!detail || !answer.id) return;
    let comment = "";
    if (decision === "return") {
      const c = window.prompt("What should the respondent change? (required)", answer.review_comment || "");
      if (c === null) return;
      comment = c;
    }
    const a = await act(() => apiCall<AssessmentApi>("POST", `/assessments/${detail.id}/answers/${answer.id}/review`, { decision, comment }));
    if (a) hydrate(a);
  }

  async function returnToRespondent() {
    if (!detail) return;
    const message = window.prompt(`Send ${detail.returned_count} returned answer${detail.returned_count === 1 ? "" : "s"} back to ${detail.contact_email || "the respondent"}? Optional message:`, "");
    if (message === null) return;
    const a = await act(() => apiCall<AssessmentApi>("POST", `/assessments/${detail.id}/return`, { message }), "Returned to the respondent");
    if (a) { hydrate(a); reload(); loadDetail(a.id); }
  }

  async function finalReview() {
    if (!detail) return;
    const notes = window.prompt("Final review. Pending answers are accepted, the score and band are recorded and the results are applied. Review notes (optional):", detail.review_notes || "");
    if (notes === null) return;
    const a = await act(() => apiCall<AssessmentApi>("POST", `/assessments/${detail.id}/review`, { notes }), "Assessment reviewed");
    if (a) { hydrate(a); reload(); }
  }

  async function uploadEvidence(q: FormQuestion, file: File) {
    if (!detail) return;
    const a = await act(() => uploadMultipart<AssessmentApi>(`/assessments/${detail.id}/questions/${q.id}/files`, file), `${file.name} attached`);
    if (a) hydrate(a);
  }

  // ------------------------------------------------------------- header form
  function openNew() {
    setModalError(null);
    cfForm.start(null);
    setHeader({ editing: null, form: { ...BLANK, questionnaire_id: qs[0]?.published_version_id || qs[0]?.id || "" } });
  }
  function openEdit(a: AssessmentApi) {
    setModalError(null);
    cfForm.start(a.id);
    setHeader({ editing: a, form: {
      title: a.title, vendor_id: a.vendor_id || "", questionnaire_id: a.questionnaire_id, due_date: a.due_date || "",
      contact_name: a.contact_name, contact_email: a.contact_email, reviewer_id: a.reviewer_id,
      recurrence_months: a.recurrence_months ?? "", review_notes: a.review_notes || "",
    } });
  }
  async function saveHeader() {
    if (!header) return;
    const f = header.form;
    if (!f.title.trim() || !f.questionnaire_id) { setModalError("Give a title and choose a questionnaire."); return; }
    setBusy(true);
    setModalError(null);
    const body = {
      title: f.title.trim(), vendor_id: f.vendor_id || null, due_date: f.due_date || null, contact_name: f.contact_name,
      contact_email: f.contact_email, reviewer_id: f.reviewer_id, recurrence_months: f.recurrence_months === "" ? null : f.recurrence_months,
      review_notes: f.review_notes, ...(header.editing && header.editing.answers.length ? {} : { questionnaire_id: f.questionnaire_id }),
    };
    try {
      const a = header.editing
        ? await apiCall<AssessmentApi>("PATCH", `/assessments/${header.editing.id}`, body)
        : await apiCall<AssessmentApi>("POST", "/assessments", body);
      await cfForm.save(a.id);
      setHeader(null);
      reload();
      setOpenId(a.id);
      hydrate(a);
      toast(header.editing ? "Changes saved" : "Assessment created as a draft");
    } catch (e) {
      setModalError(errText(e, "Failed to save"));
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------- send / links
  async function doSend() {
    if (!detail || !send) return;
    setBusy(true);
    setModalError(null);
    const body = { contact_name: send.name, contact_email: send.email, expires_in_days: send.days === "" ? 30 : send.days, message: send.message, send_email: true };
    try {
      const path = send.mode === "send" ? `/assessments/${detail.id}/send`
        : send.mode === "resend" ? `/assessments/${detail.id}/links/${send.linkId}/resend` : `/assessments/${detail.id}/links`;
      const r = await apiCall<LinkIssuedApi>("POST", path, body);
      setSend(null);
      setIssued(r);
      reload();
      loadDetail(detail.id);
    } catch (e) {
      setModalError(errText(e, "The link was not created"));
    } finally {
      setBusy(false);
    }
  }
  async function revoke(l: LinkApi) {
    if (!detail) return;
    if (!(await confirmDialog({ title: `Withdraw the link for ${l.contact_email}?`, message: "It stops working immediately. Answers already saved are kept.", danger: true }))) return;
    await act(() => apiCall("POST", `/assessments/${detail.id}/links/${l.id}/revoke`), "Link withdrawn");
    loadDetail(detail.id);
  }

  // ------------------------------------------------------------------ findings
  async function saveFinding() {
    if (!detail || !finding) return;
    if (!finding.title.trim()) { setModalError("Give the finding a title."); return; }
    setBusy(true);
    const body = { title: finding.title.trim(), description: finding.description, severity: finding.severity, deadline: finding.deadline || null };
    try {
      const a = finding.editing
        ? await apiCall<AssessmentApi>("PATCH", `/assessments/${detail.id}/findings/${finding.editing.id}`, body)
        : await apiCall<AssessmentApi>("POST", `/assessments/${detail.id}/findings`, body);
      hydrate(a);
      setFinding(null);
      reload();
    } catch (e) {
      setModalError(errText(e, "Failed to save the finding"));
    } finally {
      setBusy(false);
    }
  }
  async function toggleFinding(f: FindingApi) {
    if (!detail) return;
    const a = await act(() => f.status === "open"
      ? apiCall<AssessmentApi>("POST", `/assessments/${detail.id}/findings/${f.id}/close`)
      : apiCall<AssessmentApi>("PATCH", `/assessments/${detail.id}/findings/${f.id}`, { status: "open" }));
    if (a) { hydrate(a); reload(); }
  }
  async function doRaise() {
    if (!detail || !raise) return;
    setBusy(true);
    setModalError(null);
    try {
      const a = await apiCall<AssessmentApi>("POST", `/assessments/${detail.id}/findings/${raise.finding.id}/issue`, {
        owner_id: raise.owner_id, due_date: raise.due_date || null, severity: raise.severity,
      });
      hydrate(a);
      setRaise(null);
      toast("Issue raised");
    } catch (e) {
      setModalError(errText(e, "The issue was not raised"));
    } finally {
      setBusy(false);
    }
  }

  async function doRcsaRun() {
    if (!rcsaRun?.rcsa_id) { setModalError("Choose an RCSA."); return; }
    setBusy(true);
    setModalError(null);
    try {
      const a = await apiCall<AssessmentApi>("POST", `/rcsa/${rcsaRun.rcsa_id}/self-assessment`, { due_date: rcsaRun.due_date || null, reviewer_id: rcsaRun.reviewer_id });
      setRcsaRun(null);
      reload();
      setOpenId(a.id);
      hydrate(a);
      toast("Control self-assessment created");
    } catch (e) {
      setModalError(errText(e, "Could not start the self-assessment"));
    } finally {
      setBusy(false);
    }
  }

  const vendorOpts: Option[] = vendors.map((v) => ({ value: v.id, label: v.name }));
  const qOpts: Option[] = qs.map((q) => ({ value: q.published_version_id || q.id, label: `${q.name} (v${q.published_version ?? q.version}, ${PURPOSE_LABEL[q.purpose] || q.purpose})` }));

  const columns: Column<AssessmentRowApi>[] = [
    { key: "title", header: "Title", sortable: true, render: (a) => <span className="cell-title">{a.title}</span> },
    { key: "vendor", header: "Third party", render: (a) => <span className="muted">{a.vendor?.name || "—"}</span> },
    { key: "questionnaire", header: "Questionnaire", render: (a) => <span className="muted">{a.questionnaire ? `${a.questionnaire.name} v${a.questionnaire.version}` : "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (a) => (
      <span style={{ display: "inline-flex", gap: 4 }}>
        <Badge tone={STATUS_TONE[a.status] || "neutral"}>{STATUS_LABEL[a.status] || a.status}</Badge>
        {a.returned_count > 0 && <Badge tone="medium" plain>{a.returned_count} returned</Badge>}
        {a.is_overdue && <Badge tone="high" plain>Overdue</Badge>}
      </span>
    ) },
    { key: "due_date", header: "Due", sortable: true, render: (a) => <span className="muted">{formatDate(a.due_date)}</span> },
    { key: "progress", header: "Progress", render: (a) => <span className="muted">{a.answered_count}/{a.question_count}</span> },
    { key: "band", header: "Result", render: (a) => a.result_band ? <Badge tone={(a.result_rating as "low") || "neutral"} plain>{a.result_band}</Badge> : <span className="muted">—</span> },
    { key: "findings", header: "Open findings", align: "center", render: (a) => (a.open_findings > 0 ? <Badge tone="high">{a.open_findings}</Badge> : <span className="muted">0</span>) },
  ];

  const extra = (q: FormQuestion) => {
    const a = answersById.get(q.id);
    const canUpload = answering && (!reopened || reopened.has(q.id));
    return (
      <>
        {(a?.files.length || 0) > 0 && (
          <div style={{ marginTop: 6, fontSize: 12.5 }}>
            {a!.files.map((f) => (
              <div key={f.id}>
                <a href="#" onClick={(e) => { e.preventDefault(); import("@/lib/api").then((m) => m.downloadBlob(`/collab/files/${f.id}/download`, f.filename)); }}>{f.filename}</a>
                <span className="muted"> · {fileSize(f.size_bytes)}{f.uploaded_by_email ? ` · ${f.uploaded_by_email}` : ""}</span>
              </div>
            ))}
          </div>
        )}
        {canUpload && (q.type === "file_upload") && (
          <label className="btn secondary sm" style={{ marginTop: 6 }}>
            Attach file
            <input type="file" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) uploadEvidence(q, f); }} />
          </label>
        )}
        {a && (a.answered_by || a.review_state !== "pending" || reviewing) && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6, flexWrap: "wrap", fontSize: 12.5 }}>
            {a.answered_by && <span className="muted">Answered by {a.answered_by}{a.answered_at ? `, ${formatDateTime(a.answered_at)}` : ""}</span>}
            {a.review_state === "accepted" && <Badge tone="low" plain>Accepted</Badge>}
            {a.review_state === "returned" && <Badge tone="medium" plain>Returned: {a.review_comment}</Badge>}
            {reviewing && a.id && (
              <>
                <button type="button" className="btn secondary sm" disabled={a.review_state === "accepted"} onClick={() => reviewAnswer(a, "accept")}>Accept</button>
                <button type="button" className="btn secondary sm" onClick={() => reviewAnswer(a, "return")}>Return…</button>
              </>
            )}
          </div>
        )}
      </>
    );
  };

  const liveBand = detail?.questionnaire ? bandFor(detail.questionnaire.bands, live.pct) : null;

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Assessments</h1>
          <p>Send questionnaires to third parties through a personal link, review each answer, and turn gaps into findings and issues.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={() => { setModalError(null); setRcsaRun({ rcsa_id: "", due_date: "", reviewer_id: null }); }}>RCSA self-assessment</button>
          <button className="btn" onClick={openNew} disabled={qs.length === 0}><IconPlus width={16} height={16} /> New assessment</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }} role="alert">{error}</div>}
      {qs.length === 0 && (
        <div className="card card-pad" style={{ marginBottom: 16 }}>
          <span className="muted">No published questionnaire yet. Install one from the template library under <Link href="/questionnaires">Questionnaires</Link> and publish it.</span>
        </div>
      )}

      <DataTable<AssessmentRowApi>
        columns={columns} fetcher={fetcher} rowKey={(a) => a.id} onRowClick={(a) => setOpenId(a.id)} activeKey={openId}
        searchPlaceholder="Search assessments by title…" defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No assessments yet." refreshKey={refreshKey}
        filters={{ status: filters.status || undefined, purpose: filters.purpose || undefined, overdue: filters.overdue ? true : undefined }}
        toolbarLeft={(
          <div style={{ display: "flex", gap: 6 }}>
            <select className="select" aria-label="Status" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
              <option value="">Any status</option>
              {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
            <select className="select" aria-label="Purpose" value={filters.purpose} onChange={(e) => setFilters({ ...filters, purpose: e.target.value })}>
              <option value="">Any purpose</option>
              {Object.entries(PURPOSE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <label style={{ fontSize: 13, display: "flex", gap: 4, alignItems: "center" }}>
              <input type="checkbox" checked={!!filters.overdue} onChange={(e) => setFilters({ ...filters, overdue: e.target.checked ? "1" : "" })} /> Overdue
            </label>
          </div>
        )}
      />

      <RecordDrawer
        open={!!openId && !!detail} onClose={() => setOpenId(null)} title={detail?.title || "…"} width={820}
        subtitle={detail ? [
          detail.questionnaire ? `${detail.questionnaire.name} v${detail.questionnaire.version}` : "",
          detail.vendor?.name || "", STATUS_LABEL[detail.status] || detail.status,
          detail.due_date ? `due ${formatDate(detail.due_date)}` : "",
        ].filter(Boolean).join(" · ") : ""}
        actions={detail && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            {answering && (
              <button className="btn sm" onClick={() => { setModalError(null); setSend({ name: detail.contact_name, email: detail.contact_email, days: 30, message: "", mode: "send" }); }}>
                {detail.status === "draft" ? "Send…" : "Send new link…"}
              </button>
            )}
            {reviewing && detail.returned_count > 0 && <button className="btn secondary sm" onClick={returnToRespondent}>Return to respondent…</button>}
            {reviewing && (
              <button className="btn sm" disabled={!!detail.review_blocked_reason || detail.returned_count > 0}
                title={detail.review_blocked_reason || (detail.returned_count ? "Answers are returned to the respondent" : "")} onClick={finalReview}>
                Final review…
              </button>
            )}
            <button className="btn secondary sm" onClick={async () => {
              if (!(await confirmDialog({ title: `Delete "${detail.title}"?`, message: "Answers, findings and links are deleted too.", danger: true }))) return;
              if (await act(() => apiCall("DELETE", `/assessments/${detail.id}`), "Deleted") !== undefined) { setOpenId(null); reload(); }
            }}>Delete</button>
          </div>
        )}
      >
        {detail && (
          <>
            <div className="card card-pad" style={{ marginBottom: 12, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, fontSize: 13 }}>
              <div><div className="muted">Progress</div><strong>{live.answered} of {live.visible} answered</strong>{live.missingMandatory.length > 0 && <div className="muted">{live.missingMandatory.length} required open</div>}</div>
              <div>
                <div className="muted">{detail.result_pct !== null && !answering ? "Recorded score" : "Score so far"}</div>
                <strong>{(detail.result_pct !== null && !answering ? detail.result_pct : live.pct) ?? "—"}{(detail.result_pct ?? live.pct) !== null ? "%" : ""}</strong>
                {(detail.result_band && !answering ? detail.result_band : liveBand?.label) && (
                  <div><Badge tone={((!answering ? detail.result_rating : liveBand?.rating) as "low") || "neutral"} plain>{!answering ? detail.result_band : liveBand?.label}</Badge></div>
                )}
              </div>
              <div><div className="muted">Respondent</div><strong>{detail.contact_name || detail.contact_email || "Not set"}</strong>{detail.contact_email && detail.contact_name && <div className="muted">{detail.contact_email}</div>}</div>
              <div><div className="muted">Links</div><strong>{detail.active_links} active</strong>{detail.sent_at && <div className="muted">Sent {formatDate(detail.sent_at)}</div>}</div>
              <div><div className="muted">Purpose</div><strong>{PURPOSE_LABEL[detail.purpose] || detail.purpose}</strong>{detail.recurrence_months && <div className="muted">Every {detail.recurrence_months} months{detail.next_issue_on ? `, next ${formatDate(detail.next_issue_on)}` : ""}</div>}</div>
            </div>
            {detail.review_blocked_reason && reviewing && <p className="muted" style={{ fontSize: 12.5 }}>{detail.review_blocked_reason}</p>}
            {detail.status === "reviewed" && (
              <p style={{ fontSize: 13 }}>
                Reviewed {formatDate(detail.reviewed_at)}.{" "}
                {detail.purpose === "vendor_due_diligence" && detail.vendor ? <>The {detail.result_rating} rating was applied to <Link href={`/vendors?id=${detail.vendor.id}`}>{detail.vendor.name}</Link> unless a reasoned override is on record.</> : null}
                {detail.purpose === "vendor_tiering" && detail.vendor ? <>The tier was written to <Link href={`/vendors?id=${detail.vendor.id}`}>{detail.vendor.name}</Link>.</> : null}
                {detail.purpose === "rcsa_control_self_assessment" && detail.rcsa_assessment_id ? <>The control self-ratings were written to the <Link href={`/operational-risk?rcsa=${detail.rcsa_assessment_id}`}>RCSA lines</Link>.</> : null}
              </p>
            )}

            <div className="seg" role="tablist" style={{ marginBottom: 12 }}>
              {([["answers", "Answers"], ["findings", `Findings (${detail.open_findings} open)`], ["links", `Links (${links.length})`], ["log", "Access log"]] as const).map(([k, label]) => (
                <button key={k} role="tab" aria-selected={view === k} className={view === k ? "on" : ""} onClick={() => setView(k)}>{label}</button>
              ))}
            </div>

            {view === "answers" && (
              <>
                {reopened && answering && <p className="muted" style={{ fontSize: 13 }}>Only the returned answers and the follow-up questions they show can change until the respondent resubmits.</p>}
                <QuestionnaireForm
                  sections={sections} drafts={drafts} readOnly={!answering} editableIds={reopened} fileCounts={fileCounts}
                  onChange={(id, d) => { setDrafts((x) => ({ ...x, [id]: d })); setDirty(true); }} extra={extra} showScores
                />
                {answering && (
                  <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                    <button className="btn secondary" disabled={!dirty} onClick={() => saveAnswers(false)}>Save answers</button>
                    <button className="btn" onClick={() => saveAnswers(true)}>Save and submit</button>
                  </div>
                )}
              </>
            )}

            {view === "findings" && (
              <div>
                <div className="row-between" style={{ marginBottom: 8 }}>
                  <span className="sub">Flagged answers raise findings when the assessment is submitted.</span>
                  <button className="btn secondary sm" onClick={() => { setModalError(null); setFinding({ editing: null, title: "", description: "", severity: "medium", deadline: "" }); }}>
                    <IconPlus width={14} height={14} /> Add finding
                  </button>
                </div>
                {detail.findings.map((f) => (
                  <div key={f.id} className="activity-item" style={{ alignItems: "flex-start" }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{f.title}</div>
                      {f.description && <div className="when" style={{ whiteSpace: "pre-wrap" }}>{f.description}</div>}
                      <div className="when">
                        {f.auto_raised ? "Raised by a flagged answer" : "Added by hand"}
                        {f.deadline ? ` · deadline ${formatDate(f.deadline)}` : ""}
                        {f.issue_ref && <> · <Link href={`/issues?id=${f.issue_ref.id}`}>{f.issue_ref.reference}</Link> {cap(f.issue_ref.status)}</>}
                      </div>
                    </div>
                    <Badge tone={(f.severity as "low") || "neutral"}>{cap(f.severity)}</Badge>
                    <Badge tone={f.effective_status === "open" ? "high" : "neutral"}>{f.effective_status === "closed" && f.status === "open" ? "Closed by issue" : cap(f.effective_status)}</Badge>
                    {!f.issue_ref && f.status === "open" && (
                      <button className="btn secondary sm" onClick={() => { setModalError(null); setRaise({ finding: f, owner_id: null, due_date: f.deadline || "", severity: f.severity }); }}>Raise issue…</button>
                    )}
                    <button className="btn secondary sm" onClick={() => { setModalError(null); setFinding({ editing: f, title: f.title, description: f.description, severity: f.severity, deadline: f.deadline || "" }); }}>Edit</button>
                    {!f.issue_ref && <button className="btn secondary sm" onClick={() => toggleFinding(f)}>{f.status === "open" ? "Close" : "Reopen"}</button>}
                  </div>
                ))}
                {detail.findings.length === 0 && <span className="muted">No findings.</span>}
              </div>
            )}

            {view === "links" && (
              <div>
                <p className="sub" style={{ marginTop: 0 }}>Each link is personal, shown once when created and e-mailed when mail is set up. Only a fingerprint of it is stored.</p>
                {links.map((l) => (
                  <div key={l.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{l.contact_name ? `${l.contact_name} · ` : ""}{l.contact_email}</div>
                      <div className="when">
                        {cap(l.reason)} · created {formatDate(l.created_at)} · {l.state === "revoked" ? `withdrawn ${formatDate(l.revoked_at)}` : `valid until ${formatDate(l.expires_at)}`}
                        {l.emailed_at ? " · e-mailed" : " · not e-mailed"} · used {l.use_count} time{l.use_count === 1 ? "" : "s"}{l.last_used_at ? `, last ${formatDateTime(l.last_used_at)}` : ""}
                      </div>
                    </div>
                    <Badge tone={l.state === "active" ? "low" : "neutral"}>{cap(l.state)}</Badge>
                    {["sent", "in_progress", "submitted"].includes(state) && (
                      <button className="btn secondary sm" onClick={() => { setModalError(null); setSend({ name: l.contact_name, email: l.contact_email, days: 30, message: "", mode: "resend", linkId: l.id }); }}>Resend…</button>
                    )}
                    {l.state === "active" && <button className="btn secondary sm" onClick={() => revoke(l)}>Withdraw</button>}
                  </div>
                ))}
                {links.length === 0 && <span className="muted">Not sent yet.</span>}
                {["sent", "in_progress", "submitted"].includes(state) && (
                  <button className="btn secondary sm" style={{ marginTop: 8 }} onClick={() => { setModalError(null); setSend({ name: detail.contact_name, email: detail.contact_email, days: 30, message: "", mode: "link" }); }}>
                    <IconPlus width={13} height={13} /> New link…
                  </button>
                )}
              </div>
            )}

            {view === "log" && (
              <div>
                {log.map((r) => (
                  <div key={r.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{cap(r.action)}{r.outcome !== "ok" ? ` (${r.outcome})` : ""}{r.detail ? `: ${r.detail}` : ""}</div>
                      <div className="when">{formatDateTime(r.created_at)} · {r.ip_address || "unknown address"} · {r.user_agent.slice(0, 90) || "unknown browser"}</div>
                    </div>
                  </div>
                ))}
                {log.length === 0 && <span className="muted">No access through a link yet.</span>}
              </div>
            )}

            {/* Re-mounts after a save so edited custom-field values show at once. */}
            <div style={{ marginTop: 16 }}>
              <CustomFieldsPanel key={`${detail.id}-${refreshKey}`} model="assessment" entityId={detail.id} />
            </div>
          </>
        )}
      </RecordDrawer>

      {header && (
        <FormModal
          title={header.editing ? `Edit ${header.editing.title}` : "New assessment"}
          tabs={[{ id: "details", label: "Details", required: true, content: (
            <HeaderFields form={header.form} set={(p) => setHeader({ ...header, form: { ...header.form, ...p } })}
              vendors={vendors} vendorOpts={vendorOpts} qOpts={qOpts} lockQuestionnaire={!!header.editing?.answers.length} />
          ) }, ...cfForm.tabs]}
          onClose={() => setHeader(null)} onSave={saveHeader} saving={busy} error={modalError}
          saveLabel={header.editing ? "Save changes" : "Create draft"}
        />
      )}

      {send && (
        <FormModal
          title={send.mode === "send" ? "Send the assessment" : send.mode === "resend" ? "Resend the link" : "New respondent link"}
          tabs={[{ id: "send", label: "Respondent", required: true, content: (
            <>
              {send.mode === "resend" && <p className="sub" style={{ marginTop: 0 }}>The current link stops working and a new one is issued.</p>}
              <div className="field-row">
                <Field label="Contact name"><TextInput value={send.name} onChange={(v) => setSend({ ...send, name: v })} /></Field>
                <Field label="Contact e-mail" required><TextInput type="email" value={send.email} onChange={(v) => setSend({ ...send, email: v })} required /></Field>
              </div>
              <Field label="Link valid for (days)" help="1 to 90 days."><NumberInput value={send.days} min={1} max={90} onChange={(v) => setSend({ ...send, days: v })} /></Field>
              <Field label="Message" help="Added to the e-mail."><TextArea value={send.message} rows={3} onChange={(v) => setSend({ ...send, message: v })} /></Field>
            </>
          ) }]}
          onClose={() => setSend(null)} onSave={doSend} saving={busy} error={modalError}
          saveLabel={send.mode === "send" ? "Send" : "Create link"}
        />
      )}

      {issued && (
        <FormModal
          title="Link created"
          tabs={[{ id: "link", label: "Link", content: (
            <>
              <p style={{ marginTop: 0, fontSize: 13.5 }}>
                {issued.emailed ? `E-mailed to ${issued.link.contact_email}.` : `Not e-mailed (mail is not set up). Send this link to ${issued.link.contact_email} yourself.`}{" "}
                This is the only time the link is shown. It works until {formatDate(issued.link.expires_at)}.
              </p>
              <input className="input" readOnly value={issued.url} onFocus={(e) => e.currentTarget.select()} aria-label="Respondent link" />
            </>
          ) }]}
          onClose={() => setIssued(null)}
          onSave={() => { navigator.clipboard?.writeText(issued.url).then(() => toast("Link copied")).catch(() => undefined); setIssued(null); }}
          saveLabel="Copy and close"
        />
      )}

      {finding && (
        <FormModal
          title={finding.editing ? "Edit finding" : "Add finding"}
          tabs={[{ id: "f", label: "Finding", required: true, content: (
            <>
              <Field label="Title" required><TextInput value={finding.title} onChange={(v) => setFinding({ ...finding, title: v })} required /></Field>
              <Field label="Description"><TextArea value={finding.description} rows={4} onChange={(v) => setFinding({ ...finding, description: v })} /></Field>
              <div className="field-row">
                <Field label="Severity"><Select value={finding.severity} onChange={(v) => setFinding({ ...finding, severity: v || "medium" })} options={SEVERITIES.map((s) => ({ value: s, label: cap(s) }))} /></Field>
                <Field label="Remediation deadline"><TextInput type="date" value={finding.deadline} onChange={(v) => setFinding({ ...finding, deadline: v })} /></Field>
              </div>
            </>
          ) }]}
          onClose={() => setFinding(null)} onSave={saveFinding} saving={busy} error={modalError}
          saveLabel={finding.editing ? "Save changes" : "Add finding"}
        />
      )}

      {raise && (
        <FormModal
          title="Raise the finding as an issue"
          tabs={[{ id: "issue", label: "Issue", required: true, content: (
            <>
              <p className="sub" style={{ marginTop: 0 }}>&ldquo;{raise.finding.title}&rdquo; becomes an issue from this assessment{detail?.vendor ? `, linked to ${detail.vendor.name}` : ""}. Closing the issue closes the finding.</p>
              <Field label="Owner"><UserPicker value={raise.owner_id} onChange={(id) => setRaise({ ...raise, owner_id: id })} /></Field>
              <div className="field-row">
                <Field label="Due date"><TextInput type="date" value={raise.due_date} onChange={(v) => setRaise({ ...raise, due_date: v })} /></Field>
                <Field label="Severity"><Select value={raise.severity} onChange={(v) => setRaise({ ...raise, severity: v || "medium" })} options={SEVERITIES.map((s) => ({ value: s, label: cap(s) }))} /></Field>
              </div>
            </>
          ) }]}
          onClose={() => setRaise(null)} onSave={doRaise} saving={busy} error={modalError} saveLabel="Raise issue"
        />
      )}

      {rcsaRun && (
        <FormModal
          title="Run an RCSA as a control self-assessment"
          tabs={[{ id: "rcsa", label: "RCSA", required: true, content: (
            <>
              <p className="sub" style={{ marginTop: 0 }}>Each line of the RCSA becomes a section asking for the control&apos;s design and operation rating. The reviewed answers set each line&apos;s control self-rating.</p>
              <Field label="RCSA" required>
                <Select value={rcsaRun.rcsa_id} onChange={(v) => setRcsaRun({ ...rcsaRun, rcsa_id: v })} options={rcsas.map((r) => ({ value: r.id, label: `${r.reference} ${r.title} (${r.risk_count} lines)` }))} />
              </Field>
              <div className="field-row">
                <Field label="Due date"><TextInput type="date" value={rcsaRun.due_date} onChange={(v) => setRcsaRun({ ...rcsaRun, due_date: v })} /></Field>
                <Field label="Reviewer"><UserPicker value={rcsaRun.reviewer_id} onChange={(id) => setRcsaRun({ ...rcsaRun, reviewer_id: id })} /></Field>
              </div>
            </>
          ) }]}
          onClose={() => setRcsaRun(null)} onSave={doRcsaRun} saving={busy} error={modalError} saveLabel="Create"
        />
      )}
    </>
  );
}

function HeaderFields({ form, set, vendors, vendorOpts, qOpts, lockQuestionnaire }: {
  form: HeaderForm; set: (p: Partial<HeaderForm>) => void; vendors: Vendor[]; vendorOpts: Option[]; qOpts: Option[]; lockQuestionnaire: boolean;
}) {
  return (
    <>
      <Field label="Title" required><TextInput value={form.title} onChange={(v) => set({ title: v })} placeholder="1LINK outsourcing due diligence 2026" required /></Field>
      <div className="field-row">
        <Field label="Questionnaire" required help={lockQuestionnaire ? "Answers have been given; the questionnaire can't change." : "The published version is pinned to this assessment."}>
          {lockQuestionnaire ? <TextInput value={qOpts.find((o) => o.value === form.questionnaire_id)?.label || "Pinned version"} onChange={() => undefined} />
            : <Select value={form.questionnaire_id} onChange={(v) => set({ questionnaire_id: v })} options={qOpts} />}
        </Field>
        <Field label="Third party">
          <Select value={form.vendor_id} placeholder="None" options={vendorOpts} onChange={(v) => {
            const vendor = vendors.find((x) => x.id === v) as (Vendor & { contact_name?: string; contact_email?: string }) | undefined;
            set({ vendor_id: v, contact_name: form.contact_name || vendor?.contact_name || "", contact_email: form.contact_email || vendor?.contact_email || "" });
          }} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Respondent name"><TextInput value={form.contact_name} onChange={(v) => set({ contact_name: v })} /></Field>
        <Field label="Respondent e-mail"><TextInput type="email" value={form.contact_email} onChange={(v) => set({ contact_email: v })} /></Field>
      </div>
      <div className="field-row">
        <Field label="Due date"><TextInput type="date" value={form.due_date} onChange={(v) => set({ due_date: v })} /></Field>
        <Field label="Repeat every (months)" help="Re-issued as a draft after the final review."><NumberInput value={form.recurrence_months} min={1} max={60} onChange={(v) => set({ recurrence_months: v })} /></Field>
      </div>
      <Field label="Reviewer" help="Reviews each answer. The person who sends the assessment can't give its final review.">
        <UserPicker value={form.reviewer_id} onChange={(id) => set({ reviewer_id: id })} />
      </Field>
      <Field label="Internal notes"><TextArea value={form.review_notes} rows={2} onChange={(v) => set({ review_notes: v })} /></Field>
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
