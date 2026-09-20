"use client";

/* Answer a questionnaire: sections, typed inputs and live conditional display.

   Used by the builder preview, in-app answering on the assessment page and the public
   respondent page. Visibility comes from lib/questionnaireLogic.ts (the same rules the server
   scores with); hidden questions are not rendered, and their answers are ignored when scored.
   `extra` renders per-question additions (evidence files, review decisions). */

import type { ReactNode } from "react";
import { visibility } from "@/lib/questionnaireLogic";
import { answerValues, asSpec, blankDraft, type Draft, type FormQuestion, type FormSection } from "@/lib/questionnaire";

type Props = {
  sections: FormSection[];
  drafts: Record<string, Draft>;
  onChange?: (questionId: string, next: Draft) => void;
  readOnly?: boolean;
  /** When set, only these questions can change (answers returned by the reviewer). */
  editableIds?: Set<string> | null;
  fileCounts?: Record<string, number>;
  extra?: (q: FormQuestion) => ReactNode;
  /** Show option scores (builder preview and internal reviewers only; never the portal). */
  showScores?: boolean;
  /** Question ids to mark as missing (after a refused submit). */
  missing?: Set<string>;
};

export default function QuestionnaireForm({
  sections, drafts, onChange, readOnly, editableIds, fileCounts = {}, extra, showScores, missing,
}: Props) {
  const vis = visibility(asSpec(sections), answerValues(sections, drafts, fileCounts));
  let number = 0;
  return (
    <div className="qf">
      {sections.map((s) => {
        if (!vis.sections.has(s.key)) return null;
        const shown = s.questions.filter((q) => vis.questions.has(q.key));
        if (!shown.length) return null;
        return (
          <section key={s.key} style={{ marginBottom: 22 }} aria-labelledby={`qf-s-${s.key}`}>
            <h3 id={`qf-s-${s.key}`} style={{ fontSize: 15, margin: "0 0 2px" }}>{s.title}</h3>
            {s.description && <p className="muted" style={{ fontSize: 13, margin: "0 0 8px" }}>{s.description}</p>}
            {shown.map((q) => {
              number += 1;
              const d = drafts[q.id] || blankDraft();
              const locked = readOnly || (editableIds ? !editableIds.has(q.id) : false);
              const set = (patch: Partial<Draft>) => onChange?.(q.id, { ...d, ...patch });
              const isMissing = missing?.has(q.id);
              return (
                <div key={q.id} id={`q-${q.id}`} style={{ padding: "12px 0", borderTop: "1px solid var(--border)" }}>
                  <div style={{ fontSize: 13.5, fontWeight: 500 }}>
                    {number}. {q.text}
                    {q.mandatory && <span className="req" aria-label="required"> *</span>}
                  </div>
                  {q.guidance && <div className="when" style={{ marginTop: 2 }}>{q.guidance}</div>}
                  <div style={{ marginTop: 8 }}>
                    <Input q={q} d={d} set={set} locked={!!locked} showScores={showScores} />
                  </div>
                  {q.type !== "file_upload" && (
                    <input
                      className="input" style={{ marginTop: 8 }} value={d.comment} disabled={!!locked}
                      aria-label={`Comment on question ${number}`}
                      placeholder={locked ? "" : "Comment (optional)"}
                      onChange={(e) => set({ comment: e.target.value })}
                    />
                  )}
                  {isMissing && <div className="error" style={{ marginTop: 6, fontSize: 12.5 }}>This question needs an answer.</div>}
                  {extra?.(q)}
                </div>
              );
            })}
          </section>
        );
      })}
    </div>
  );
}

function Input({ q, d, set, locked, showScores }: { q: FormQuestion; d: Draft; set: (p: Partial<Draft>) => void; locked: boolean; showScores?: boolean }) {
  const label = (o: FormQuestion["options"][number]) => `${o.label}${showScores && !o.is_na ? ` (${o.score ?? 0})` : ""}`;
  if (q.type === "single_choice" || q.type === "yes_no_na") {
    return (
      <div role="radiogroup" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {q.options.map((o) => {
          const on = d.option_ids[0] === o.id;
          return (
            <label key={o.id} className={`badge ${on ? "info" : "neutral"}`}
              style={{ cursor: locked ? "default" : "pointer", border: on ? "1px solid var(--primary)" : "1px solid var(--border)", padding: "5px 10px" }}>
              <input type="radio" name={`q-${q.id}`} checked={on} disabled={locked} style={{ marginRight: 6 }}
                onChange={() => set({ option_ids: [o.id] })} />
              {label(o)}
            </label>
          );
        })}
        {!locked && d.option_ids.length > 0 && (
          <button type="button" className="btn secondary sm" onClick={() => set({ option_ids: [] })}>Clear</button>
        )}
      </div>
    );
  }
  if (q.type === "multiple_choice") {
    return (
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {q.options.map((o) => {
          const on = d.option_ids.includes(o.id);
          return (
            <label key={o.id} className={`badge ${on ? "info" : "neutral"}`}
              style={{ cursor: locked ? "default" : "pointer", border: on ? "1px solid var(--primary)" : "1px solid var(--border)", padding: "5px 10px" }}>
              <input type="checkbox" checked={on} disabled={locked} style={{ marginRight: 6 }}
                onChange={() => set({ option_ids: on ? d.option_ids.filter((x) => x !== o.id) : [...d.option_ids, o.id] })} />
              {label(o)}
            </label>
          );
        })}
      </div>
    );
  }
  if (q.type === "text") {
    return <input className="input" value={d.value_text} disabled={locked} maxLength={1000} aria-label={q.text} onChange={(e) => set({ value_text: e.target.value })} />;
  }
  if (q.type === "long_text") {
    return <textarea className="input" rows={4} value={d.value_text} disabled={locked} aria-label={q.text} onChange={(e) => set({ value_text: e.target.value })} />;
  }
  if (q.type === "number") {
    return (
      <input className="input" type="number" style={{ maxWidth: 220 }} value={d.value_number} disabled={locked} aria-label={q.text}
        onChange={(e) => set({ value_number: e.target.value === "" ? "" : Number(e.target.value) })} />
    );
  }
  if (q.type === "date") {
    return <input className="input" type="date" style={{ maxWidth: 220 }} value={d.value_date} disabled={locked} aria-label={q.text} onChange={(e) => set({ value_date: e.target.value })} />;
  }
  return <div className="muted" style={{ fontSize: 12.5 }}>Attach files below.</div>;
}
