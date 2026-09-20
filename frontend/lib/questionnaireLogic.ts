/* The questionnaire engine's rules in the browser: conditional display, scoring and bands.

   A line-for-line mirror of backend/app/services/questionnaire_logic.py — same shapes, same
   semantics — so the builder preview and the respondent portal show exactly what the server
   will score. Change both together (backend tests: tests/test_phase4_questionnaires.py).

   Conditions: {match: "all" | "any", rules: [{question, op, values?, value?}]}. Operators:
   in / not_in (selected option values; not_in is also true when unanswered), answered /
   not_answered (N/A counts as answered), eq / neq / gt / gte / lt / lte (number answers; false
   when there is no number). A hidden question counts as unanswered for every rule that refers
   to it, so hiding cascades. Rules refer only to earlier questions.

   Scoring: only choice questions score. Max = best non-N/A option (single, yes/no/N-A) or the
   sum of positive non-N/A options (multiple), times the weight. Hidden and N/A questions drop
   out; a visible blank earns 0 but keeps its maximum. pct = 100 × earned / max, one decimal,
   or null when nothing is scorable. Bands: highest min_pct not above the score. */

export type QType =
  | "single_choice" | "multiple_choice" | "yes_no_na" | "text" | "long_text" | "number" | "date" | "file_upload";

export const QUESTION_TYPES: { value: QType; label: string }[] = [
  { value: "single_choice", label: "Single choice" },
  { value: "multiple_choice", label: "Multiple choice" },
  { value: "yes_no_na", label: "Yes / No / Not applicable" },
  { value: "text", label: "Short text" },
  { value: "long_text", label: "Long text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "file_upload", label: "File upload (evidence)" },
];
export const CHOICE_TYPES = new Set<string>(["single_choice", "multiple_choice", "yes_no_na"]);
export const OPERATORS: { value: string; label: string }[] = [
  { value: "in", label: "is one of" },
  { value: "not_in", label: "is none of" },
  { value: "answered", label: "is answered" },
  { value: "not_answered", label: "is not answered" },
  { value: "eq", label: "=" },
  { value: "neq", label: "≠" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
];
export const NUMBER_OPS = new Set(["eq", "neq", "gt", "gte", "lt", "lte"]);
export const OPTION_OPS = new Set(["in", "not_in"]);
export const PURPOSES: { value: string; label: string; help: string }[] = [
  { value: "general", label: "General", help: "Scores and findings only; no record is updated." },
  { value: "vendor_tiering", label: "Vendor tiering", help: "A completed assessment sets the vendor's inherent tier." },
  { value: "vendor_due_diligence", label: "Vendor due diligence", help: "The reviewed band sets the vendor's risk rating and next due-diligence date." },
  { value: "rcsa_control_self_assessment", label: "Control self-assessment (RCSA)", help: "Design and operation ratings set each RCSA line's control self-rating." },
];
export const RATINGS = ["low", "medium", "high", "critical"] as const;

export type Rule = { question: string; op: string; values?: string[]; value?: number | null };
export type Condition = { match?: "all" | "any"; rules?: Rule[] } | null | undefined;
export type OptionSpec = {
  value: string; label?: string; score?: number; is_na?: boolean; risk_flag?: boolean;
  finding_title?: string; finding_severity?: string;
};
export type QuestionSpec = {
  key: string; text?: string; type: string; mandatory?: boolean; weight?: number | null;
  conditions?: Condition; options?: OptionSpec[];
};
export type SectionSpec = { key: string; title?: string; conditions?: Condition; questions: QuestionSpec[] };
export type Band = { label: string; min_pct: number; rating: string };

export type AnswerValue = {
  option_values?: string[];
  number?: number | null;
  text?: string;
  date?: string | null;
  na?: boolean;
  files?: number;
};

export function isAnswered(a: AnswerValue | undefined | null): boolean {
  if (!a) return false;
  return !!(a.na || (a.option_values && a.option_values.length) || (a.number !== null && a.number !== undefined)
    || (a.text || "").trim() || a.date || (a.files || 0) > 0);
}

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "" || typeof v === "boolean") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

export function ruleHolds(rule: Rule, answer: AnswerValue | undefined): boolean {
  const op = rule.op;
  if (op === "answered") return isAnswered(answer);
  if (op === "not_answered") return !isAnswered(answer);
  if (OPTION_OPS.has(op)) {
    const wanted = new Set((rule.values || []).map(String));
    const hit = (answer?.option_values || []).some((v) => wanted.has(v));
    return op === "in" ? hit : !hit;
  }
  if (NUMBER_OPS.has(op)) {
    const target = num(rule.value);
    const have = answer ? num(answer.number) : null;
    if (target === null || have === null) return false;
    switch (op) {
      case "eq": return have === target;
      case "neq": return have !== target;
      case "gt": return have > target;
      case "gte": return have >= target;
      case "lt": return have < target;
      default: return have <= target;
    }
  }
  return false;
}

export function conditionHolds(condition: Condition, answers: Record<string, AnswerValue>): boolean {
  const rules = (condition?.rules || []).filter((r) => r && typeof r === "object");
  if (!rules.length) return true;
  const results = rules.map((r) => ruleHolds(r, answers[String(r.question)]));
  return condition?.match === "any" ? results.some(Boolean) : results.every(Boolean);
}

export function visibility(sections: SectionSpec[], answers: Record<string, AnswerValue>): { sections: Set<string>; questions: Set<string> } {
  const seen: Record<string, AnswerValue> = {};
  const out = { sections: new Set<string>(), questions: new Set<string>() };
  for (const s of sections) {
    const shows = conditionHolds(s.conditions, seen);
    if (shows) out.sections.add(s.key);
    for (const q of s.questions || []) {
      if (shows && conditionHolds(q.conditions, seen)) {
        out.questions.add(q.key);
        if (answers[q.key]) seen[q.key] = answers[q.key];
      }
    }
  }
  return out;
}

export function questionMax(q: QuestionSpec): number {
  if (!CHOICE_TYPES.has(q.type || "single_choice")) return 0;
  const scores = (q.options || []).filter((o) => !o.is_na).map((o) => Number(o.score || 0));
  if (!scores.length) return 0;
  if (q.type === "multiple_choice") return scores.filter((s) => s > 0).reduce((a, b) => a + b, 0);
  return Math.max(Math.max(...scores), 0);
}

const weightOf = (q: QuestionSpec) => {
  const w = num(q.weight);
  return w === null ? 1 : Math.max(w, 0);
};

/** null = drops out (N/A). */
export function questionEarned(q: QuestionSpec, answer: AnswerValue | undefined): number | null {
  if (!CHOICE_TYPES.has(q.type || "single_choice")) return 0;
  if (!answer) return 0;
  const byValue = new Map((q.options || []).map((o) => [String(o.value), o]));
  let chosen = (answer.option_values || []).map((v) => byValue.get(v)).filter((o): o is OptionSpec => !!o);
  if (answer.na || (chosen.length && chosen.every((o) => o.is_na))) return null;
  chosen = chosen.filter((o) => !o.is_na);
  if (!chosen.length) return 0;
  if (q.type === "multiple_choice") return Math.min(chosen.reduce((s, o) => s + Number(o.score || 0), 0), questionMax(q));
  return Number(chosen[0].score || 0);
}

const round = (n: number, d: number) => Math.round(n * 10 ** d) / 10 ** d;

export type ScoreResult = {
  earned: number; maximum: number; pct: number | null; visible: number; answered: number;
  notApplicable: number; missingMandatory: string[]; progressPct: number;
};

export function score(sections: SectionSpec[], answers: Record<string, AnswerValue>): ScoreResult {
  const vis = visibility(sections, answers);
  let earned = 0, maximum = 0, visible = 0, answered = 0, na = 0;
  const missing: string[] = [];
  for (const s of sections) {
    for (const q of s.questions || []) {
      if (!vis.questions.has(q.key)) continue;
      visible += 1;
      const a = answers[q.key];
      if (isAnswered(a)) answered += 1;
      else if (q.mandatory) missing.push(q.key);
      const got = questionEarned(q, a);
      if (got === null) { na += 1; continue; }
      const w = weightOf(q);
      earned += w * got;
      maximum += w * questionMax(q);
    }
  }
  earned = round(earned, 2);
  maximum = round(maximum, 2);
  const pct = maximum > 0 ? round((100 * earned) / maximum, 1) : null;
  return { earned, maximum, pct, visible, answered, notApplicable: na, missingMandatory: missing,
    progressPct: visible ? Math.round((100 * answered) / visible) : 0 };
}

export function staticMax(sections: SectionSpec[]): number {
  return round(sections.reduce((t, s) => t + (s.questions || []).reduce((u, q) => u + weightOf(q) * questionMax(q), 0), 0), 2);
}

export function bandFor(bands: Band[] | null | undefined, pct: number | null): Band | null {
  if (pct === null || pct === undefined) return null;
  const sorted = [...(bands || [])].sort((a, b) => Number(b.min_pct) - Number(a.min_pct));
  return sorted.find((b) => pct >= Number(b.min_pct || 0)) || null;
}

/** "Do you use MFA?" → "do_you_use_mfa" (the server's slug). */
export function slug(text: string, fallback = "q"): string {
  const s = (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);
  return s || fallback;
}

export function uniqueKey(base: string, taken: Set<string>): string {
  let candidate = base.slice(0, 60) || "x";
  let n = 2;
  while (taken.has(candidate)) candidate = `${base.slice(0, 56)}_${n++}`;
  return candidate;
}
