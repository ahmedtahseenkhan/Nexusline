"use client";

/* The respondent portal: a vendor contact answers a questionnaire from a personal link.

   No sign-in: the link is the credential (only its hash is stored on the server; it expires
   and can be withdrawn). The page shows the bank's name, the sections with live conditional
   display, saves drafts, takes evidence uploads and submits. It never shows scores or which
   answers raise findings. After the reviewer returns answers, only those can change. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { IconNexus } from "@/components/icons";
import QuestionnaireForm from "@/components/QuestionnaireForm";
import {
  answerValues, asSpec, blankDraft, draftFromAnswer, fileSize, submitPayload,
  type Draft, type FormQuestion, type FormSection, type PortalViewApi,
} from "@/lib/questionnaire";
import { score, visibility } from "@/lib/questionnaireLogic";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/v1${path}`, { ...init, referrerPolicy: "no-referrer" });
  if (!res.ok) {
    let message = res.statusText || "Something went wrong";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail?.message) message = [body.detail.message, ...(body.detail.problems || [])].join(" ");
    } catch {
      /* not JSON */
    }
    throw Object.assign(new Error(message), { status: res.status });
  }
  return res.json();
}

const fmtDate = (v: string | null | undefined) => {
  if (!v) return "";
  const d = new Date(v.length === 10 ? `${v}T00:00:00` : v);
  return Number.isNaN(d.getTime()) ? v : d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
};

export default function RespondPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token ? decodeURIComponent(String(params.token)) : "";
  const [view, setView] = useState<PortalViewApi | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [missing, setMissing] = useState<Set<string>>(new Set());

  const hydrate = useCallback((v: PortalViewApi) => {
    setView(v);
    const next: Record<string, Draft> = {};
    v.answers.forEach((a) => { next[a.question_id] = draftFromAnswer(a); });
    setDrafts(next);
    setDirty(false);
  }, []);

  useEffect(() => {
    if (!token) return;
    call<PortalViewApi>(`/respond/${encodeURIComponent(token)}`).then(hydrate).catch((e: Error) => setFatal(e.message));
  }, [token, hydrate]);

  useEffect(() => {
    if (view) document.title = `${view.assessment_title} · ${view.organisation}`;
  }, [view]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const sections: FormSection[] = useMemo(() => (view?.sections || []).map((s) => ({
    ...s, questions: s.questions.map((q) => ({ ...q, options: q.options })),
  })), [view]);
  const files = useMemo(() => {
    const m: Record<string, number> = {};
    view?.answers.forEach((a) => { m[a.question_id] = a.files.length; });
    return m;
  }, [view]);
  const answersById = useMemo(() => new Map((view?.answers || []).map((a) => [a.question_id, a])), [view]);
  const editableIds = view?.reopened_question_ids ? new Set(view.reopened_question_ids) : null;
  const progress = useMemo(() => score(asSpec(sections), answerValues(sections, drafts, files)), [sections, drafts, files]);
  const canEdit = !!view?.editable;

  function change(id: string, next: Draft) {
    setDrafts((d) => ({ ...d, [id]: next }));
    setDirty(true);
    setNotice(null);
  }

  function payload() {
    const vis = visibility(asSpec(sections), answerValues(sections, drafts, files));
    const out = [];
    for (const s of sections) for (const q of s.questions) {
      if (editableIds && !editableIds.has(q.id)) continue;
      const d = drafts[q.id];
      if (!d && !answersById.has(q.id)) continue;
      if (!vis.questions.has(q.key) && !answersById.has(q.id)) continue;
      out.push(submitPayload(q.id, q.type, d || blankDraft()));
    }
    return out;
  }

  async function save(quiet = false): Promise<boolean> {
    setBusy("save");
    setError(null);
    try {
      const v = await call<PortalViewApi>(`/respond/${encodeURIComponent(token)}/answers`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ answers: payload() }),
      });
      hydrate(v);
      if (!quiet) setNotice(`Saved at ${new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}. You can close this page and come back with the same link.`);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Your answers were not saved.");
      return false;
    } finally {
      setBusy(null);
    }
  }

  async function submit() {
    const idsByKey = new Map(sections.flatMap((s) => s.questions.map((q) => [q.key, q.id] as const)));
    if (progress.missingMandatory.length) {
      const ids = new Set(progress.missingMandatory.map((k) => idsByKey.get(k) || ""));
      setMissing(ids);
      setError(`${progress.missingMandatory.length} required question${progress.missingMandatory.length === 1 ? " is" : "s are"} unanswered.`);
      const first = progress.missingMandatory[0];
      document.getElementById(`q-${idsByKey.get(first)}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (!window.confirm("Submit your answers? You won't be able to change them unless the reviewer returns them.")) return;
    if (dirty && !(await save(true))) return;
    setBusy("submit");
    setError(null);
    try {
      const v = await call<PortalViewApi>(`/respond/${encodeURIComponent(token)}/submit`, { method: "POST" });
      hydrate(v);
      setMissing(new Set());
      setNotice(null);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Your answers were not submitted.");
    } finally {
      setBusy(null);
    }
  }

  async function upload(q: FormQuestion, file: File) {
    if (!view) return;
    const ext = file.name.includes(".") ? file.name.split(".").pop()!.toLowerCase() : "";
    if (!view.allowed_file_types.includes(ext)) {
      setError(`Files of type .${ext || "?"} can't be uploaded. Accepted: ${view.allowed_file_types.join(", ").toUpperCase()}.`);
      return;
    }
    if (file.size > view.max_upload_mb * 1024 * 1024) {
      setError(`${file.name} is larger than ${view.max_upload_mb} MB.`);
      return;
    }
    if (dirty && !(await save(true))) return;
    setBusy(`upload-${q.id}`);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const v = await call<PortalViewApi>(`/respond/${encodeURIComponent(token)}/questions/${q.id}/files`, { method: "POST", body: form });
      hydrate(v);
      setNotice(`${file.name} uploaded.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The file was not uploaded.");
    } finally {
      setBusy(null);
    }
  }

  async function removeFile(fileId: string, name: string) {
    if (!window.confirm(`Remove ${name}?`)) return;
    setBusy(`file-${fileId}`);
    try {
      hydrate(await call<PortalViewApi>(`/respond/${encodeURIComponent(token)}/files/${fileId}`, { method: "DELETE" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The file was not removed.");
    } finally {
      setBusy(null);
    }
  }

  const extra = (q: FormQuestion) => {
    const a = answersById.get(q.id);
    const locked = !canEdit || (editableIds ? !editableIds.has(q.id) : false);
    return (
      <>
        {a?.review_state === "returned" && a.review_comment && (
          <div role="note" style={{ marginTop: 8, padding: "8px 10px", background: "var(--amber-bg)", color: "var(--amber)", borderRadius: 6, fontSize: 13 }}>
            Reviewer&apos;s comment: {a.review_comment}
          </div>
        )}
        {(q.type === "file_upload" || (a?.files.length ?? 0) > 0 || !locked) && (
          <div style={{ marginTop: 8 }}>
            {(a?.files || []).map((f) => (
              <div key={f.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, padding: "2px 0" }}>
                <span>{f.filename}</span>
                <span className="muted">{fileSize(f.size_bytes)}</span>
                {!locked && (
                  <button type="button" className="btn secondary sm" disabled={!!busy} onClick={() => removeFile(f.id, f.filename)}>Remove</button>
                )}
              </div>
            ))}
            {!locked && (
              <label className="btn secondary sm" style={{ marginTop: 4, cursor: busy ? "default" : "pointer" }}>
                {busy === `upload-${q.id}` ? "Uploading…" : q.type === "file_upload" ? "Upload a file" : "Attach supporting evidence"}
                <input type="file" hidden disabled={!!busy}
                  accept={view?.allowed_file_types.map((t) => `.${t}`).join(",")}
                  onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) upload(q, f); }} />
              </label>
            )}
          </div>
        )}
      </>
    );
  };

  if (fatal || !token) {
    return (
      <div className="login-wrap">
        <div className="login-card" style={{ width: 520 }}>
          <Logo />
          <h1>This link can&apos;t be used</h1>
          <p className="sub">{fatal || "The link is incomplete."}</p>
        </div>
      </div>
    );
  }
  if (!view) {
    return <div className="login-wrap"><div className="login-card" style={{ width: 520 }}><Logo /><p className="sub">Opening the questionnaire…</p></div></div>;
  }

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg, #f6f7f9)", padding: "24px 16px 64px" }}>
      <main style={{ maxWidth: 820, margin: "0 auto" }}>
        <header className="card card-pad" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div>
              <div className="muted" style={{ fontSize: 12.5 }}>{view.organisation}</div>
              <h1 style={{ fontSize: 20, margin: "2px 0 4px" }}>{view.assessment_title}</h1>
              <div className="muted" style={{ fontSize: 13 }}>
                {view.questionnaire_name} (version {view.questionnaire_version})
                {view.vendor_name ? ` · for ${view.vendor_name}` : ""}
              </div>
            </div>
            <div style={{ textAlign: "right", fontSize: 13 }}>
              {view.due_date && <div>Due <strong>{fmtDate(view.due_date)}</strong></div>}
              <div className="muted">Link valid until {fmtDate(view.expires_at)}</div>
            </div>
          </div>
          {view.message && <p role="status" style={{ margin: "12px 0 0", fontSize: 13.5 }}>{view.message}</p>}
          {canEdit && (
            <div style={{ marginTop: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5 }} className="muted">
                <span>{progress.answered} of {progress.visible} questions answered</span>
                <span>{progress.progressPct}%</span>
              </div>
              <div style={{ height: 6, background: "var(--border)", borderRadius: 3, marginTop: 4 }} role="progressbar"
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.progressPct} aria-label="Progress">
                <div style={{ width: `${progress.progressPct}%`, height: "100%", background: "var(--primary)", borderRadius: 3 }} />
              </div>
            </div>
          )}
        </header>

        <div className="card card-pad">
          <QuestionnaireForm
            sections={sections} drafts={drafts} onChange={change} readOnly={!canEdit} editableIds={editableIds}
            fileCounts={files} extra={extra} missing={missing}
          />
        </div>

        {canEdit && (
          <div className="card card-pad" style={{ position: "sticky", bottom: 12, marginTop: 16, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn secondary" disabled={!!busy || !dirty} onClick={() => save()}>{busy === "save" ? "Saving…" : "Save draft"}</button>
            <button className="btn" disabled={!!busy} onClick={submit}>{busy === "submit" ? "Submitting…" : "Submit answers"}</button>
            <span className="muted" style={{ fontSize: 12.5 }} role="status">{dirty ? "Unsaved changes" : notice || ""}</span>
            {error && <div className="error" role="alert" style={{ flexBasis: "100%" }}>{error}</div>}
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 16, textAlign: "center" }}>
          This link is personal to you. Every visit is recorded with your network address. Do not forward it.
          Files up to {view.max_upload_mb} MB: {view.allowed_file_types.join(", ").toUpperCase()}.
        </p>
      </main>
    </div>
  );
}

function Logo() {
  return (
    <div className="login-logo">
      <span className="logo"><IconNexus width={19} height={19} /></span>
      <span className="wordmark">Nexus<span style={{ color: "var(--primary-text)" }}>Line</span></span>
    </div>
  );
}
