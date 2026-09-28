/* API types for questionnaires, assessments and the respondent portal (phase 4E), and the
   helpers that turn API answers into the evaluator's shape (lib/questionnaireLogic.ts). */

import type { AnswerValue, Band, Condition, SectionSpec } from "./questionnaireLogic";

export type QOptionApi = {
  id: string; value: string; label: string; score?: number; order_index?: number; is_na?: boolean;
  risk_flag?: boolean; finding_title?: string; finding_severity?: string;
};
export type QQuestionApi = {
  id: string; key: string; text: string; guidance: string; type: string; mandatory: boolean; weight?: number;
  conditions: Condition; config?: Record<string, unknown>; section_id?: string | null; order_index?: number;
  max_score?: number; options: QOptionApi[];
};
export type QSectionApi = { id: string | null; key: string; title: string; description: string; order_index?: number; conditions: Condition };

export type QuestionnaireSummaryApi = {
  id: string; name: string; description: string; question_count: number; section_count: number; max_score: number;
  family_id: string | null; version: number; status: string; purpose: string; origin: string; library_key: string;
  library_version: number | null; published_at: string | null; updated_at: string | null;
  published_version_id: string | null; published_version: number | null; draft_version_id: string | null;
};
export type QuestionnaireApi = QuestionnaireSummaryApi & {
  bands: Band[]; change_note: string; sections: QSectionApi[]; questions: QQuestionApi[]; in_use: number;
};
export type VersionRowApi = {
  id: string; version: number; status: string; name: string; change_note: string; published_at: string | null;
  created_at: string; question_count: number; in_use: number;
};
export type LibraryTemplateApi = {
  key: string; version: number; name: string; purpose: string; description: string; section_count: number;
  question_count: number; scored_question_count: number; risk_flag_count: number; installed_versions: number[];
};

export type FileRefApi = { id: string; filename: string; content_type?: string; size_bytes: number; uploaded_by_email?: string; created_at?: string | null };
export type AnswerApi = {
  id?: string; question_id: string; option_id?: string | null; option_ids: string[]; value_text: string;
  value_number: number | null; value_date: string | null; not_applicable: boolean; comment: string;
  review_state: string; review_comment: string; reviewed_at?: string | null; answered_by?: string;
  answered_at?: string | null; files: FileRefApi[];
};
export type FindingApi = {
  id: string; title: string; description: string; severity: string; status: string; deadline: string | null;
  created_at: string; answer_id: string | null; question_key: string; auto_raised: boolean; issue_id: string | null;
  issue_ref: { id: string; reference: string; title: string; status: string } | null; effective_status: string;
};
export type AssessmentApi = {
  id: string; title: string; vendor_id: string | null; vendor: { id: string; name: string } | null;
  questionnaire_id: string; questionnaire: QuestionnaireApi | null; status: string; due_date: string | null;
  submitted_at: string | null; review_notes: string; question_count: number; answered_count: number;
  max_score: number; total_score: number; score_pct: number; open_findings: number; answers: AnswerApi[];
  findings: FindingApi[]; created_at: string; purpose: string; progress_pct: number; missing_mandatory: number;
  band: string; band_rating: string | null; returned_count: number; is_overdue: boolean; contact_name: string;
  contact_email: string; sent_at: string | null; sent_by_id: string | null; reviewer_id: string | null;
  reviewed_at: string | null; reviewed_by_id: string | null; submitted_by: string; result_score: number | null;
  result_max: number | null; result_pct: number | null; result_band: string; result_rating: string | null;
  scored_at: string | null; recurrence_months: number | null; next_issue_on: string | null;
  parent_assessment_id: string | null; rcsa_assessment_id: string | null; active_links: number;
  review_blocked_reason: string | null;
  /** In a returned round, the questions that may still change; null when nothing is locked. */
  reopened_question_ids?: string[] | null;
};
export type AssessmentRowApi = {
  id: string; title: string; vendor: { id: string; name: string } | null; questionnaire: { id: string; name: string; version: number; purpose: string } | null;
  questionnaire_id: string; status: string; due_date: string | null; submitted_at: string | null; question_count: number;
  answered_count: number; score_pct: number; open_findings: number; created_at: string; purpose: string;
  progress_pct: number; band: string; result_band: string; result_rating: string | null; returned_count: number;
  is_overdue: boolean; contact_email: string;
};
export type LinkApi = {
  id: string; contact_name: string; contact_email: string; reason: string; expires_at: string; revoked_at: string | null;
  emailed_at: string | null; last_used_at: string | null; use_count: number; created_at: string; state: string;
};
export type LinkIssuedApi = { link: LinkApi; token: string; url: string; emailed: boolean; assessment?: AssessmentApi | null };
export type AccessLogApi = { id: string; link_id: string | null; action: string; outcome: string; detail: string; ip_address: string; user_agent: string; created_at: string };

export type PortalQuestionApi = { id: string; key: string; text: string; guidance: string; type: string; mandatory: boolean; conditions: Condition; options: { id: string; value: string; label: string; is_na: boolean }[] };
export type PortalSectionApi = { id: string | null; key: string; title: string; description: string; conditions: Condition; questions: PortalQuestionApi[] };
export type PortalViewApi = {
  organisation: string; assessment_title: string; vendor_name: string; questionnaire_name: string; questionnaire_version: number;
  contact_name: string; due_date: string | null; status: string; editable: boolean; reopened_question_ids: string[] | null;
  submitted_at: string | null; expires_at: string; sections: PortalSectionApi[]; answers: AnswerApi[];
  max_upload_mb: number; allowed_file_types: string[]; message: string;
};

/** A section tree the form renders: sections with their questions, in order. */
export type FormQuestion = {
  id: string; key: string; text: string; guidance: string; type: string; mandatory: boolean; conditions: Condition;
  weight?: number;
  options: { id: string; value: string; label: string; is_na?: boolean; score?: number; risk_flag?: boolean; finding_severity?: string }[];
};
export type FormSection = { id: string | null; key: string; title: string; description: string; conditions: Condition; questions: FormQuestion[] };

/** The version's sections with their questions (questions without a section go last). */
export function formSections(q: Pick<QuestionnaireApi, "sections" | "questions">): FormSection[] {
  const sections = [...(q.sections || [])].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0));
  const questions = [...(q.questions || [])].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0));
  const out: FormSection[] = sections.map((s) => ({
    id: s.id, key: s.key, title: s.title, description: s.description, conditions: s.conditions,
    questions: questions.filter((x) => x.section_id === s.id).map(toFormQuestion),
  }));
  const loose = questions.filter((x) => !x.section_id || !sections.some((s) => s.id === x.section_id));
  if (loose.length) out.push({ id: null, key: "_unsectioned", title: "Questions", description: "", conditions: {}, questions: loose.map(toFormQuestion) });
  return out;
}

function toFormQuestion(x: QQuestionApi): FormQuestion {
  return {
    id: x.id, key: x.key, text: x.text, guidance: x.guidance, type: x.type, mandatory: x.mandatory, conditions: x.conditions,
    weight: x.weight,
    options: [...x.options].sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0)),
  };
}

/** The editable state of one answer in a form. */
export type Draft = {
  option_ids: string[]; value_text: string; value_number: number | ""; value_date: string; comment: string;
};
export const blankDraft = (): Draft => ({ option_ids: [], value_text: "", value_number: "", value_date: "", comment: "" });

export function draftFromAnswer(a: AnswerApi): Draft {
  const ids = a.option_id ? [a.option_id] : (a.option_ids || []);
  return {
    option_ids: ids.map(String), value_text: a.value_text || "", value_number: a.value_number ?? "",
    value_date: a.value_date || "", comment: a.comment || "",
  };
}

/** Drafts (by question id) as evaluator answers (by question key). */
export function answerValues(sections: FormSection[], drafts: Record<string, Draft>, files: Record<string, number> = {}): Record<string, AnswerValue> {
  const out: Record<string, AnswerValue> = {};
  for (const s of sections) {
    for (const q of s.questions) {
      const d = drafts[q.id];
      const fileCount = files[q.id] || 0;
      if (!d && !fileCount) continue;
      const chosen = (d?.option_ids || []).map((id) => q.options.find((o) => o.id === id)).filter(Boolean) as FormQuestion["options"];
      out[q.key] = {
        option_values: chosen.map((o) => o.value),
        number: d && d.value_number !== "" ? Number(d.value_number) : null,
        text: d?.value_text || "",
        date: d?.value_date || null,
        na: chosen.length > 0 && chosen.every((o) => o.is_na),
        files: fileCount,
      };
    }
  }
  return out;
}

export const asSpec = (sections: FormSection[]): SectionSpec[] =>
  sections.map((s) => ({ key: s.key, conditions: s.conditions, questions: s.questions.map((q) => ({
    key: q.key, text: q.text, type: q.type, mandatory: q.mandatory, conditions: q.conditions,
    weight: q.weight, options: q.options.map((o) => ({ value: o.value, score: o.score, is_na: o.is_na })),
  })) }));

/** The payload the API takes for one draft. */
export function submitPayload(questionId: string, type: string, d: Draft) {
  const base = { question_id: questionId, comment: d.comment || "" };
  if (type === "multiple_choice") return { ...base, option_ids: d.option_ids };
  if (type === "single_choice" || type === "yes_no_na") return { ...base, option_id: d.option_ids[0] || null };
  if (type === "text" || type === "long_text") return { ...base, value_text: d.value_text };
  if (type === "number") return { ...base, value_number: d.value_number === "" ? null : Number(d.value_number) };
  if (type === "date") return { ...base, value_date: d.value_date || null };
  return base;
}

export const PURPOSE_LABEL: Record<string, string> = {
  general: "General",
  vendor_tiering: "Vendor tiering",
  vendor_due_diligence: "Vendor due diligence",
  rcsa_control_self_assessment: "Control self-assessment",
};
export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", sent: "Sent", in_progress: "In progress", submitted: "Submitted", reviewed: "Reviewed",
  published: "Published", superseded: "Superseded",
};

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
