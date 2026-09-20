"use client";

/* Questionnaires: the builder, versions and the template library (phase 4E).

   A questionnaire has versions. A draft can be edited; publishing makes it immutable and the
   version new assessments use. Editing a published questionnaire opens the next draft version.
   The builder edits sections (ordered with up/down), typed questions (mandatory, weight,
   display conditions), scored answer options (N/A, risk flag with a suggested finding) and the
   scoring bands. The Preview tab answers the draft live with the same rules the server uses. */

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFormat } from "@/lib/format";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import FormModal from "@/components/FormModal";
import QuestionnaireForm from "@/components/QuestionnaireForm";
import { Field, TextInput, TextArea, Select, NumberInput, Toggle } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import {
  CHOICE_TYPES, NUMBER_OPS, OPERATORS, OPTION_OPS, PURPOSES, QUESTION_TYPES, RATINGS,
  bandFor, score, slug, staticMax, uniqueKey, type Band, type Condition, type Rule,
} from "@/lib/questionnaireLogic";
import {
  PURPOSE_LABEL, STATUS_LABEL, answerValues, asSpec, formSections,
  type Draft, type FormSection, type LibraryTemplateApi, type QuestionnaireApi, type QuestionnaireSummaryApi, type VersionRowApi,
} from "@/lib/questionnaire";

// ------------------------------------------------------------------ draft model ---
type OptionDraft = { value: string; label: string; score: number | ""; is_na: boolean; risk_flag: boolean; finding_title: string; finding_severity: string };
type QuestionDraft = {
  uid: string; key: string; text: string; guidance: string; type: string; mandatory: boolean; weight: number | "";
  conditions: { match: "all" | "any"; rules: Rule[] }; options: OptionDraft[]; config: Record<string, unknown>;
};
type SectionDraft = { uid: string; key: string; title: string; description: string; conditions: { match: "all" | "any"; rules: Rule[] }; questions: QuestionDraft[] };
type Tree = { name: string; description: string; purpose: string; bands: { label: string; min_pct: number | ""; rating: string }[]; change_note: string; sections: SectionDraft[] };

let uidSeq = 0;
const uid = () => `u${Date.now().toString(36)}${(uidSeq++).toString(36)}`;
const cond = (c: Condition) => ({ match: (c?.match === "any" ? "any" : "all") as "all" | "any", rules: [...(c?.rules || [])] });

const opt = (value: string, label: string, score: number, extra: Partial<OptionDraft> = {}): OptionDraft => ({
  value, label, score, is_na: false, risk_flag: false, finding_title: "", finding_severity: "medium", ...extra,
});
function defaultOptions(type: string): OptionDraft[] {
  if (type === "yes_no_na") return [opt("yes", "Yes", 1), opt("no", "No", 0), opt("na", "Not applicable", 0, { is_na: true })];
  if (CHOICE_TYPES.has(type)) return [opt("option_1", "", 1), opt("option_2", "", 0)];
  return [];
}

function allKeys(t: Tree): Set<string> {
  return new Set(t.sections.flatMap((s) => s.questions.map((q) => q.key)));
}

function blankQuestion(t: Tree): QuestionDraft {
  return { uid: uid(), key: uniqueKey("q", allKeys(t)), text: "", guidance: "", type: "yes_no_na", mandatory: true, weight: 1,
    conditions: { match: "all", rules: [] }, options: defaultOptions("yes_no_na"), config: {} };
}
function blankSection(t: Tree, n: number): SectionDraft {
  const keys = new Set(t.sections.map((s) => s.key));
  return { uid: uid(), key: uniqueKey(`section_${n}`, keys), title: "", description: "", conditions: { match: "all", rules: [] }, questions: [] };
}

function fromApi(q: QuestionnaireApi): Tree {
  return {
    name: q.name, description: q.description || "", purpose: q.purpose, change_note: q.change_note || "",
    bands: (q.bands || []).map((b) => ({ ...b })),
    sections: formSections(q).map((s) => ({
      uid: uid(), key: s.key, title: s.title, description: s.description, conditions: cond(s.conditions),
      questions: s.questions.map((x) => {
        const full = q.questions.find((y) => y.id === x.id)!;
        return {
          uid: uid(), key: x.key, text: x.text, guidance: x.guidance || "", type: x.type, mandatory: x.mandatory,
          weight: full.weight ?? 1, conditions: cond(x.conditions), config: full.config || {},
          options: full.options.map((o) => ({ value: o.value, label: o.label, score: o.score ?? 0, is_na: !!o.is_na, risk_flag: !!o.risk_flag, finding_title: o.finding_title || "", finding_severity: o.finding_severity || "medium" })),
        };
      }),
    })),
  };
}

function toPayload(t: Tree) {
  return {
    name: t.name.trim(), description: t.description.trim(), purpose: t.purpose, change_note: t.change_note,
    bands: t.bands.filter((b) => b.label.trim()).map((b) => ({ label: b.label.trim(), min_pct: Number(b.min_pct || 0), rating: b.rating })),
    sections: t.sections.map((s) => ({
      key: s.key, title: s.title.trim() || "Untitled section", description: s.description, conditions: s.conditions.rules.length ? s.conditions : {},
      questions: s.questions.map((q) => ({
        key: q.key, text: q.text.trim(), guidance: q.guidance, type: q.type, mandatory: q.mandatory, weight: Number(q.weight === "" ? 0 : q.weight),
        conditions: q.conditions.rules.length ? q.conditions : {}, config: q.config,
        options: CHOICE_TYPES.has(q.type) ? q.options.map((o) => ({ ...o, label: o.label.trim(), score: Number(o.score || 0) })) : [],
      })),
    })),
  };
}

/** The draft tree as the preview form and the evaluator see it. */
function previewSections(t: Tree): FormSection[] {
  return t.sections.map((s) => ({
    id: s.uid, key: s.key, title: s.title || "Untitled section", description: s.description, conditions: s.conditions,
    questions: s.questions.map((q) => ({
      id: q.uid, key: q.key, text: q.text || "(no text yet)", guidance: q.guidance, type: q.type, mandatory: q.mandatory,
      conditions: q.conditions, weight: Number(q.weight || 0),
      options: q.options.map((o, i) => ({ id: `${q.uid}-${i}`, value: o.value, label: o.label || `Option ${i + 1}`, score: Number(o.score || 0), is_na: o.is_na, risk_flag: o.risk_flag })),
    })),
  }));
}

const TONE: Record<string, "low" | "medium" | "info" | "neutral"> = { published: "low", draft: "medium", superseded: "neutral" };
const errText = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

// ======================================================================= page ===
function QuestionnairesInner() {
  const { formatDate } = useFormat();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<QuestionnaireApi | null>(null);
  const [history, setHistory] = useState<VersionRowApi[]>([]);
  const [problems, setProblems] = useState<string[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [tab, setTab] = useState<"mine" | "library">("mine");
  const [library, setLibrary] = useState<LibraryTemplateApi[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<QuestionnaireApi | null>(null);
  const [tree, setTree] = useState<Tree | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetcher = useCallback((query: string) => apiCall<PagedList<QuestionnaireSummaryApi>>("GET", `/questionnaires?${query}`), []);

  const loadDetail = useCallback(async (id: string) => {
    try {
      const q = await apiCall<QuestionnaireApi>("GET", `/questionnaires/${id}`);
      setDetail(q);
      setHistory(await apiCall<VersionRowApi[]>("GET", `/questionnaires/${id}/versions`));
      setProblems(q.status === "draft" ? (await apiCall<{ problems: string[] }>("POST", `/questionnaires/${id}/validate`)).problems : []);
    } catch (e) {
      setError(errText(e, "Failed to load the questionnaire"));
    }
  }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);
  useEffect(() => {
    if (tab === "library") apiCall<LibraryTemplateApi[]>("GET", "/questionnaire-library").then(setLibrary).catch((e) => setError(errText(e, "Failed to load the library")));
  }, [tab, refreshKey]);

  function openNew() {
    setEditing(null);
    const t: Tree = { name: "", description: "", purpose: "vendor_due_diligence", change_note: "", sections: [], bands: [
      { label: "Strong", min_pct: 80, rating: "low" }, { label: "Adequate", min_pct: 60, rating: "medium" },
      { label: "Weak", min_pct: 40, rating: "high" }, { label: "Inadequate", min_pct: 0, rating: "critical" },
    ] };
    const s = blankSection(t, 1);
    t.sections = [s];
    s.questions = [blankQuestion(t)];
    setTree(t);
    setFormError(null);
  }

  async function openEdit(q: QuestionnaireApi) {
    setFormError(null);
    try {
      let target = q;
      if (q.status !== "draft") {
        target = await apiCall<QuestionnaireApi>("POST", `/questionnaires/${q.id}/new-version`);
        toast(`Editing draft version ${target.version}. Version ${q.version} stays as published until you publish the draft.`);
        setOpenId(target.id);
        reload();
      }
      setEditing(target);
      setTree(fromApi(target));
    } catch (e) {
      setError(errText(e, "Could not open the questionnaire for editing"));
    }
  }

  async function save() {
    if (!tree) return;
    if (!tree.name.trim()) { setFormError("Give the questionnaire a name."); return; }
    setSaving(true);
    setFormError(null);
    try {
      const body = toPayload(tree);
      const saved = editing
        ? await apiCall<QuestionnaireApi>("PATCH", `/questionnaires/${editing.id}`, body)
        : await apiCall<QuestionnaireApi>("POST", "/questionnaires", body);
      setTree(null);
      setEditing(null);
      reload();
      setOpenId(saved.id);
      loadDetail(saved.id);
      toast(editing ? "Draft saved" : "Questionnaire created as a draft");
    } catch (e) {
      setFormError(errText(e, "Failed to save"));
    } finally {
      setSaving(false);
    }
  }

  async function publish(q: QuestionnaireApi) {
    const note = window.prompt(`Publish version ${q.version} of "${q.name}"? New assessments will use it. Optional note about what changed:`, q.change_note || "");
    if (note === null) return;
    try {
      await apiCall("POST", `/questionnaires/${q.id}/publish`, { change_note: note });
      toast(`Version ${q.version} published`);
      reload();
      loadDetail(q.id);
    } catch (e) {
      setError(errText(e, "Could not publish"));
    }
  }

  async function remove(q: QuestionnaireApi) {
    if (!(await confirmDialog({ title: `Delete version ${q.version} of "${q.name}"?`, message: q.in_use ? "It is used by assessments and can't be deleted." : "This cannot be undone.", danger: true }))) return;
    try {
      await apiCall("DELETE", `/questionnaires/${q.id}`);
      setOpenId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(errText(e, "Failed to delete"));
    }
  }

  async function install(t: LibraryTemplateApi) {
    try {
      const q = await apiCall<QuestionnaireApi>("POST", `/questionnaire-library/${t.key}/install`, {});
      toast(`Installed "${q.name}" as a draft. Review it, then publish.`);
      setTab("mine");
      reload();
      setOpenId(q.id);
    } catch (e) {
      setError(errText(e, "Could not install the template"));
    }
  }

  const columns: Column<QuestionnaireSummaryApi>[] = [
    { key: "name", header: "Name", sortable: true, render: (q) => <span className="cell-title">{q.name}</span> },
    { key: "purpose", header: "Purpose", render: (q) => <span className="muted">{PURPOSE_LABEL[q.purpose] || q.purpose}</span> },
    { key: "version", header: "Version", render: (q) => (
      <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
        {q.published_version ? <Badge tone="low" plain>v{q.published_version} published</Badge> : <span className="muted">Not published</span>}
        {q.draft_version_id && <Badge tone="medium" plain>draft v{q.version}</Badge>}
      </span>
    ) },
    { key: "question_count", header: "Questions", align: "center", render: (q) => <span className="muted">{q.question_count}</span> },
    { key: "origin", header: "Source", render: (q) => <span className="muted">{q.origin === "library" ? "Template library" : "Built here"}</span> },
    { key: "updated_at", header: "Updated", sortable: true, render: (q) => <span className="muted">{formatDate(q.updated_at)}</span> },
  ];

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Questionnaires</h1>
          <p>Versioned questionnaires for vendor tiering, due diligence and control self-assessment. Publish a version to use it.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <div className="seg" role="tablist" aria-label="View">
            <button role="tab" aria-selected={tab === "mine"} className={tab === "mine" ? "on" : ""} onClick={() => setTab("mine")}>Our questionnaires</button>
            <button role="tab" aria-selected={tab === "library"} className={tab === "library" ? "on" : ""} onClick={() => setTab("library")}>Template library</button>
          </div>
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> New questionnaire</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }} role="alert">{error}</div>}

      {tab === "mine" ? (
        <DataTable<QuestionnaireSummaryApi>
          columns={columns} fetcher={fetcher} rowKey={(q) => q.id} onRowClick={(q) => setOpenId(q.id)} activeKey={openId}
          searchPlaceholder="Search questionnaires by name…" defaultSort={{ by: "name", dir: "asc" }}
          emptyMessage="No questionnaires yet. Install one from the template library or build your own." refreshKey={refreshKey}
        />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {library.map((t) => (
            <div key={t.key} className="card card-pad">
              <div className="row-between">
                <strong>{t.name}</strong>
                <Badge tone="info" plain>v{t.version}</Badge>
              </div>
              <div className="muted" style={{ fontSize: 12.5, margin: "2px 0 8px" }}>{PURPOSE_LABEL[t.purpose]}</div>
              <p style={{ fontSize: 13, margin: "0 0 10px" }}>{t.description}</p>
              <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
                {t.section_count} sections · {t.question_count} questions · {t.scored_question_count} scored · {t.risk_flag_count} answers raise findings
              </div>
              {t.installed_versions.length > 0 && <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>Installed: version {t.installed_versions.join(", ")}</div>}
              <button className="btn secondary sm" onClick={() => install(t)}>Install as draft</button>
            </div>
          ))}
        </div>
      )}

      <RecordDrawer
        open={!!openId && !!detail} onClose={() => setOpenId(null)} title={detail?.name || "…"} width={760}
        subtitle={detail ? `${PURPOSE_LABEL[detail.purpose] || detail.purpose} · version ${detail.version} · ${STATUS_LABEL[detail.status] || detail.status}` : ""}
        actions={detail && (
          <div style={{ display: "flex", gap: 6 }}>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>{detail.status === "draft" ? "Edit draft" : "Edit (new version)"}</button>
            {detail.status === "draft" && <button className="btn sm" disabled={problems.length > 0} onClick={() => publish(detail)}>Publish</button>}
            {!detail.in_use && <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>}
          </div>
        )}
      >
        {detail && <Detail q={detail} history={history} problems={problems} onOpen={setOpenId} />}
      </RecordDrawer>

      {tree && (
        <FormModal
          title={editing ? `Edit draft version ${editing.version} — ${editing.name}` : "New questionnaire"}
          wide
          tabs={[
            { id: "setup", label: "Setup & bands", required: true, content: <SetupTab tree={tree} setTree={setTree} /> },
            { id: "questions", label: "Sections & questions", content: <BuilderTab tree={tree} setTree={setTree} /> },
            { id: "preview", label: "Preview", content: <PreviewTab tree={tree} /> },
          ]}
          onClose={() => { setTree(null); setEditing(null); }}
          onSave={save} saving={saving} error={formError}
          saveLabel={editing ? "Save draft" : "Create draft"}
          footerLeft={<span className="sub">{tree.sections.reduce((n, s) => n + s.questions.length, 0)} questions · max score {staticMax(asSpec(previewSections(tree)))}</span>}
        />
      )}
    </>
  );
}

// ================================================================== detail ===
function Detail({ q, history, problems, onOpen }: { q: QuestionnaireApi; history: VersionRowApi[]; problems: string[]; onOpen: (id: string) => void }) {
  const { formatDate } = useFormat();
  const sections = formSections(q);
  const byKey = new Map(q.questions.map((x) => [x.key, x]));
  return (
    <>
      {q.description && <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>{q.description}</p>}
      {q.status === "published" && <p style={{ fontSize: 13 }}>Published {formatDate(q.published_at)}. It can&apos;t be changed; editing opens the next draft version. Used by {q.in_use} assessment{q.in_use === 1 ? "" : "s"}.</p>}
      {q.status === "superseded" && <p style={{ fontSize: 13 }}>A newer version has been published. Assessments already using this version keep it.</p>}
      {problems.length > 0 && (
        <div className="card card-pad" style={{ marginBottom: 12, borderColor: "var(--amber)" }}>
          <strong style={{ fontSize: 13 }}>Fix before publishing</strong>
          <ul style={{ margin: "6px 0 0 18px", fontSize: 13 }}>{problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      {q.bands.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="label">Scoring bands</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[...q.bands].sort((a, b) => b.min_pct - a.min_pct).map((b) => (
              <Badge key={b.label} tone={b.rating as "low"} plain>{b.label}: {b.min_pct}% and above → {b.rating} rating</Badge>
            ))}
          </div>
        </div>
      )}
      {sections.map((s) => (
        <div key={s.key} style={{ marginBottom: 14 }}>
          <h3 style={{ fontSize: 14, margin: "8px 0 2px" }}>{s.title}</h3>
          {s.description && <div className="when">{s.description}</div>}
          {(s.conditions?.rules || []).length > 0 && <div className="when">Shown when {describe(s.conditions, byKey)}</div>}
          {s.questions.map((x, i) => (
            <div key={x.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ fontSize: 13.5 }}>{i + 1}. {x.text}{x.mandatory && <span className="req"> *</span>}</div>
              <div className="when">{QUESTION_TYPES.find((t) => t.value === x.type)?.label}{CHOICE_TYPES.has(x.type) ? ` · weight ${x.weight ?? 1}` : ""}</div>
              {(x.conditions?.rules || []).length > 0 && <div className="when">Shown when {describe(x.conditions, byKey)}</div>}
              {x.options.length > 0 && (
                <div style={{ marginTop: 4, display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {x.options.map((o) => (
                    <Badge key={o.id} tone={o.risk_flag ? "high" : "neutral"} plain>
                      {o.label}{o.is_na ? " (N/A)" : ` = ${o.score}`}{o.risk_flag ? ` · raises ${o.finding_severity} finding` : ""}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
      <div className="label" style={{ marginTop: 16 }}>Version history</div>
      {history.map((v) => (
        <div key={v.id} className="activity-item" style={{ cursor: "pointer" }} onClick={() => onOpen(v.id)}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13 }}>Version {v.version}{v.id === q.id ? " (shown)" : ""}</div>
            <div className="when">{v.published_at ? `Published ${formatDate(v.published_at)}` : `Created ${formatDate(v.created_at)}`}{v.change_note ? ` · ${v.change_note}` : ""}</div>
          </div>
          <span className="muted" style={{ fontSize: 12 }}>{v.in_use} assessment{v.in_use === 1 ? "" : "s"}</span>
          <Badge tone={TONE[v.status] || "neutral"}>{STATUS_LABEL[v.status] || v.status}</Badge>
        </div>
      ))}
    </>
  );
}

function describe(c: Condition, byKey: Map<string, { text: string; options: { value: string; label: string }[] }>): string {
  const parts = (c?.rules || []).map((r) => {
    const q = byKey.get(r.question);
    const name = q ? `"${q.text.slice(0, 60)}"` : r.question;
    const op = OPERATORS.find((o) => o.value === r.op)?.label || r.op;
    if (OPTION_OPS.has(r.op)) return `${name} ${op} ${(r.values || []).map((v) => q?.options.find((o) => o.value === v)?.label || v).join(" / ")}`;
    if (NUMBER_OPS.has(r.op)) return `${name} ${op} ${r.value}`;
    return `${name} ${op}`;
  });
  return parts.join(c?.match === "any" ? " or " : " and ");
}

// ================================================================ setup tab ===
function SetupTab({ tree, setTree }: { tree: Tree; setTree: (t: Tree) => void }) {
  const set = (patch: Partial<Tree>) => setTree({ ...tree, ...patch });
  const purpose = PURPOSES.find((p) => p.value === tree.purpose);
  return (
    <>
      <Field label="Name" required>
        <TextInput value={tree.name} onChange={(v) => set({ name: v })} placeholder="Cloud service security" required />
      </Field>
      <Field label="Description" help="What it covers and when to send it. Shown to reviewers, not respondents.">
        <TextArea value={tree.description} onChange={(v) => set({ description: v })} rows={2} />
      </Field>
      <Field label="Purpose" help={purpose?.help}>
        <Select value={tree.purpose} onChange={(v) => set({ purpose: v || "general" })} options={PURPOSES.map((p) => ({ value: p.value, label: p.label }))} />
      </Field>
      <Field label="Change note" help="What changed in this version (kept in the version history).">
        <TextInput value={tree.change_note} onChange={(v) => set({ change_note: v })} />
      </Field>
      <div className="row-between" style={{ margin: "12px 0 6px" }}>
        <label className="label" style={{ margin: 0 }}>Scoring bands</label>
        <button type="button" className="btn secondary sm" onClick={() => set({ bands: [...tree.bands, { label: "", min_pct: "", rating: "medium" }] })}>
          <IconPlus width={13} height={13} /> Add band
        </button>
      </div>
      <p className="help" style={{ marginTop: 0 }}>A score falls in the band with the highest minimum it reaches. Include a band starting at 0%. For due diligence the band&apos;s rating becomes the vendor&apos;s risk rating.</p>
      {tree.bands.map((b, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "center" }}>
          <div style={{ flex: 1 }}><TextInput value={b.label} onChange={(v) => set({ bands: tree.bands.map((x, j) => (j === i ? { ...x, label: v } : x)) })} placeholder="Label, e.g. Strong" /></div>
          <div style={{ width: 120 }}><NumberInput value={b.min_pct} min={0} max={100} onChange={(v) => set({ bands: tree.bands.map((x, j) => (j === i ? { ...x, min_pct: v } : x)) })} placeholder="min %" /></div>
          <div style={{ width: 140 }}><Select value={b.rating} onChange={(v) => set({ bands: tree.bands.map((x, j) => (j === i ? { ...x, rating: v || "medium" } : x)) })} options={RATINGS.map((r) => ({ value: r, label: `${r[0].toUpperCase()}${r.slice(1)} rating` }))} /></div>
          <button type="button" className="btn secondary sm" aria-label="Remove band" onClick={() => set({ bands: tree.bands.filter((_, j) => j !== i) })}>✕</button>
        </div>
      ))}
    </>
  );
}

// ============================================================== builder tab ===
function BuilderTab({ tree, setTree }: { tree: Tree; setTree: (t: Tree) => void }) {
  const setSections = (sections: SectionDraft[]) => setTree({ ...tree, sections });
  const move = <T,>(list: T[], i: number, dir: -1 | 1): T[] => {
    const j = i + dir;
    if (j < 0 || j >= list.length) return list;
    const next = [...list];
    [next[i], next[j]] = [next[j], next[i]];
    return next;
  };
  const patchSection = (si: number, patch: Partial<SectionDraft>) => setSections(tree.sections.map((s, i) => (i === si ? { ...s, ...patch } : s)));
  const patchQuestion = (si: number, qi: number, patch: Partial<QuestionDraft>) =>
    patchSection(si, { questions: tree.sections[si].questions.map((q, i) => (i === qi ? { ...q, ...patch } : q)) });

  // Questions before a given position (conditions may refer only to these).
  const before = (si: number, qi: number | null) => {
    const out: QuestionDraft[] = [];
    tree.sections.forEach((s, i) => s.questions.forEach((q, j) => { if (i < si || (i === si && qi !== null && j < qi)) out.push(q); }));
    return out;
  };

  return (
    <>
      {tree.sections.map((s, si) => (
        <div key={s.uid} className="card card-pad" style={{ marginBottom: 14 }}>
          <div className="row-between" style={{ marginBottom: 8 }}>
            <strong style={{ fontSize: 13.5 }}>Section {si + 1}</strong>
            <div style={{ display: "flex", gap: 6 }}>
              <button type="button" className="btn secondary sm" disabled={si === 0} onClick={() => setSections(move(tree.sections, si, -1))} aria-label="Move section up">↑</button>
              <button type="button" className="btn secondary sm" disabled={si === tree.sections.length - 1} onClick={() => setSections(move(tree.sections, si, 1))} aria-label="Move section down">↓</button>
              <button type="button" className="btn secondary sm" onClick={() => setSections(tree.sections.filter((_, i) => i !== si))} aria-label="Remove section">✕</button>
            </div>
          </div>
          <div className="field-row">
            <Field label="Title" required><TextInput value={s.title} onChange={(v) => patchSection(si, { title: v })} placeholder="Data location and confidentiality" /></Field>
          </div>
          <Field label="Description" help="Shown to respondents above the section."><TextArea value={s.description} rows={2} onChange={(v) => patchSection(si, { description: v })} /></Field>
          <ConditionEditor label="Show this section" value={s.conditions} earlier={before(si, null)} onChange={(c) => patchSection(si, { conditions: c })} />

          {s.questions.map((q, qi) => (
            <QuestionEditor
              key={q.uid} q={q} index={qi} count={s.questions.length} earlier={before(si, qi)} tree={tree}
              onChange={(patch) => patchQuestion(si, qi, patch)}
              onMove={(dir) => patchSection(si, { questions: move(s.questions, qi, dir) })}
              onRemove={() => patchSection(si, { questions: s.questions.filter((_, i) => i !== qi) })}
            />
          ))}
          <button type="button" className="btn secondary sm" style={{ marginTop: 8 }} onClick={() => patchSection(si, { questions: [...s.questions, blankQuestion(tree)] })}>
            <IconPlus width={13} height={13} /> Add question
          </button>
        </div>
      ))}
      <button type="button" className="btn secondary" onClick={() => setSections([...tree.sections, blankSection(tree, tree.sections.length + 1)])}>
        <IconPlus width={15} height={15} /> Add section
      </button>
    </>
  );
}

function QuestionEditor({ q, index, count, earlier, tree, onChange, onMove, onRemove }: {
  q: QuestionDraft; index: number; count: number; earlier: QuestionDraft[]; tree: Tree;
  onChange: (p: Partial<QuestionDraft>) => void; onMove: (d: -1 | 1) => void; onRemove: () => void;
}) {
  const choice = CHOICE_TYPES.has(q.type);
  const setOpt = (i: number, patch: Partial<OptionDraft>) => onChange({ options: q.options.map((o, j) => (j === i ? { ...o, ...patch } : o)) });
  const rcsaRole = String(q.config?.rcsa_role || "");
  return (
    <div style={{ borderTop: "1px solid var(--border)", padding: "12px 0" }}>
      <div className="row-between" style={{ marginBottom: 6 }}>
        <strong style={{ fontSize: 13 }}>Question {index + 1}</strong>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" className="btn secondary sm" disabled={index === 0} onClick={() => onMove(-1)} aria-label="Move question up">↑</button>
          <button type="button" className="btn secondary sm" disabled={index === count - 1} onClick={() => onMove(1)} aria-label="Move question down">↓</button>
          <button type="button" className="btn secondary sm" onClick={onRemove} aria-label="Remove question">✕</button>
        </div>
      </div>
      <Field label="Question" required>
        <TextArea value={q.text} rows={2} onChange={(v) => onChange({ text: v })} />
      </Field>
      <Field label="Guidance" help="Help for the respondent, shown under the question.">
        <TextInput value={q.guidance} onChange={(v) => onChange({ guidance: v })} />
      </Field>
      <div className="field-row">
        <Field label="Type">
          <Select value={q.type} onChange={(v) => {
            const type = v || "single_choice";
            onChange({ type, options: CHOICE_TYPES.has(type) ? (CHOICE_TYPES.has(q.type) && type !== "yes_no_na" ? q.options : defaultOptions(type)) : [] });
          }} options={QUESTION_TYPES.map((t) => ({ value: t.value, label: t.label }))} />
        </Field>
        {choice && (
          <Field label="Weight" help="Multiplies this question's score.">
            <NumberInput value={q.weight} min={0} step={0.5} onChange={(v) => onChange({ weight: v })} />
          </Field>
        )}
        <Field label="Key" help="Conditions refer to it. Letters, digits and _ only.">
          <TextInput value={q.key} onChange={(v) => onChange({ key: slug(v, q.key) })} />
        </Field>
      </div>
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", margin: "4px 0 8px" }}>
        <Toggle checked={q.mandatory} onChange={(v) => onChange({ mandatory: v })} label="Required" />
        {tree.purpose === "rcsa_control_self_assessment" && choice && (
          <label style={{ fontSize: 13, display: "flex", gap: 6, alignItems: "center" }}>
            RCSA rating
            <select className="select" value={rcsaRole} onChange={(e) => onChange({ config: { ...q.config, rcsa_role: e.target.value || undefined } })}>
              <option value="">Not a rating</option>
              <option value="design">Design rating</option>
              <option value="operation">Operation rating</option>
            </select>
          </label>
        )}
      </div>

      {choice && (
        <>
          <label className="label">Answers</label>
          {tree.purpose === "rcsa_control_self_assessment" && rcsaRole && (
            <p className="help" style={{ marginTop: 0 }}>Use the values effective, partially_effective, ineffective (and an N/A answer) so the rating can be written to the RCSA line.</p>
          )}
          {q.options.map((o, i) => (
            <div key={i} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ flex: 2, minWidth: 160 }}><TextInput value={o.label} placeholder={`Answer ${i + 1}`} onChange={(v) => setOpt(i, { label: v, value: o.value.startsWith("option_") && v ? uniqueKey(slug(v, "option"), new Set(q.options.filter((_, j) => j !== i).map((x) => x.value))) : o.value })} /></div>
                <div style={{ width: 90 }}><NumberInput value={o.score} min={0} step={1} placeholder="score" onChange={(v) => setOpt(i, { score: v })} /></div>
                <label style={{ fontSize: 12.5 }}><input type="checkbox" checked={o.is_na} onChange={(e) => setOpt(i, { is_na: e.target.checked })} /> N/A</label>
                <label style={{ fontSize: 12.5 }}><input type="checkbox" checked={o.risk_flag} onChange={(e) => setOpt(i, { risk_flag: e.target.checked })} /> Raises a finding</label>
                <button type="button" className="btn secondary sm" disabled={q.options.length <= 1} onClick={() => onChange({ options: q.options.filter((_, j) => j !== i) })} aria-label="Remove answer">✕</button>
              </div>
              <div className="when" style={{ marginTop: 2 }}>Value: {o.value}</div>
              {o.risk_flag && (
                <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                  <div style={{ flex: 1 }}><TextInput value={o.finding_title} placeholder="Finding title (defaults to the question and answer)" onChange={(v) => setOpt(i, { finding_title: v })} /></div>
                  <div style={{ width: 150 }}><Select value={o.finding_severity} onChange={(v) => setOpt(i, { finding_severity: v || "medium" })} options={RATINGS.map((r) => ({ value: r, label: `${r[0].toUpperCase()}${r.slice(1)} severity` }))} /></div>
                </div>
              )}
            </div>
          ))}
          <button type="button" className="btn secondary sm" onClick={() => onChange({ options: [...q.options, opt(uniqueKey("option", new Set(q.options.map((x) => x.value))), "", 0)] })}>
            <IconPlus width={13} height={13} /> Add answer
          </button>
        </>
      )}
      <ConditionEditor label="Show this question" value={q.conditions} earlier={earlier} onChange={(c) => onChange({ conditions: c })} />
    </div>
  );
}

function ConditionEditor({ label, value, earlier, onChange }: {
  label: string; value: { match: "all" | "any"; rules: Rule[] }; earlier: QuestionDraft[];
  onChange: (c: { match: "all" | "any"; rules: Rule[] }) => void;
}) {
  const setRule = (i: number, patch: Partial<Rule>) => onChange({ ...value, rules: value.rules.map((r, j) => (j === i ? { ...r, ...patch } : r)) });
  const candidates = earlier.filter((q) => q.text.trim() || q.key);
  return (
    <div style={{ marginTop: 10, padding: "8px 10px", background: "var(--surface-2, transparent)", borderRadius: 6 }}>
      <div className="row-between">
        <span style={{ fontSize: 12.5 }}>
          {label}: {value.rules.length === 0 ? "always" : (
            <select className="select" style={{ width: "auto", display: "inline-block" }} value={value.match} onChange={(e) => onChange({ ...value, match: e.target.value as "all" | "any" })}>
              <option value="all">when all of these hold</option>
              <option value="any">when any of these holds</option>
            </select>
          )}
        </span>
        <button type="button" className="btn secondary sm" disabled={!candidates.length} title={candidates.length ? "" : "Add a question earlier in the questionnaire first"}
          onClick={() => onChange({ ...value, rules: [...value.rules, { question: candidates[candidates.length - 1].key, op: "in", values: [] }] })}>
          Add condition
        </button>
      </div>
      {value.rules.map((r, i) => {
        const target = candidates.find((q) => q.key === r.question);
        const ops = OPERATORS.filter((o) => (OPTION_OPS.has(o.value) ? !!target && CHOICE_TYPES.has(target.type) : NUMBER_OPS.has(o.value) ? target?.type === "number" : true));
        return (
          <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 6, flexWrap: "wrap" }}>
            <select className="select" style={{ flex: 2, minWidth: 180 }} value={r.question} onChange={(e) => setRule(i, { question: e.target.value, values: [] })} aria-label="Earlier question">
              {!target && <option value={r.question}>{r.question} (not an earlier question)</option>}
              {candidates.map((q) => <option key={q.uid} value={q.key}>{(q.text || q.key).slice(0, 70)}</option>)}
            </select>
            <select className="select" style={{ width: 150 }} value={r.op} onChange={(e) => setRule(i, { op: e.target.value })} aria-label="Comparison">
              {ops.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {OPTION_OPS.has(r.op) && target && (
              <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {target.options.map((o) => (
                  <label key={o.value} style={{ fontSize: 12.5 }}>
                    <input type="checkbox" checked={(r.values || []).includes(o.value)}
                      onChange={(e) => setRule(i, { values: e.target.checked ? [...(r.values || []), o.value] : (r.values || []).filter((v) => v !== o.value) })} /> {o.label || o.value}
                  </label>
                ))}
              </span>
            )}
            {NUMBER_OPS.has(r.op) && (
              <input className="input" type="number" style={{ width: 110 }} value={r.value ?? ""} aria-label="Number"
                onChange={(e) => setRule(i, { value: e.target.value === "" ? null : Number(e.target.value) })} />
            )}
            <button type="button" className="btn secondary sm" aria-label="Remove condition" onClick={() => onChange({ ...value, rules: value.rules.filter((_, j) => j !== i) })}>✕</button>
          </div>
        );
      })}
    </div>
  );
}

// ============================================================== preview tab ===
function PreviewTab({ tree }: { tree: Tree }) {
  const sections = useMemo(() => previewSections(tree), [tree]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const result = score(asSpec(sections), answerValues(sections, drafts));
  const band = bandFor(tree.bands.map((b) => ({ ...b, min_pct: Number(b.min_pct || 0) })) as Band[], result.pct);
  return (
    <>
      <div className="card card-pad" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <span style={{ fontSize: 13 }}>Answer as a respondent would: questions appear and disappear as their conditions change.</span>
        <span style={{ fontSize: 13 }}>
          <strong>{result.pct === null ? "No score" : `${result.pct}%`}</strong> ({result.earned} of {result.maximum})
          {band ? ` · ${band.label} → ${band.rating} rating` : ""} · {result.answered}/{result.visible} answered
          {result.missingMandatory.length ? ` · ${result.missingMandatory.length} required unanswered` : ""}
        </span>
      </div>
      <QuestionnaireForm sections={sections} drafts={drafts} onChange={(id, d) => setDrafts((x) => ({ ...x, [id]: d }))} showScores />
      <button type="button" className="btn secondary sm" onClick={() => setDrafts({})}>Clear answers</button>
    </>
  );
}

export default function QuestionnairesPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <QuestionnairesInner />
    </Suspense>
  );
}
