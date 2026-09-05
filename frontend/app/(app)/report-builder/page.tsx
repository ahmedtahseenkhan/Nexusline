"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  apiCall,
  type ReportDefinition,
  type ReportFilterSpec,
  type ReportFormat,
  type ReportRun,
  type ReportSubject,
  type SavedReport,
} from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import AsyncSelect from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import { Field, MultiSelect, Select, TextInput, TextArea } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

/* The report builder. A report is a question — which records, shown how, summed up
   how — and the whole screen is generated from the subject registry the server
   publishes: filters, columns, sort. Nothing about risks, controls or incidents is
   hard-coded here, so a fourth subject appears when the server declares it.

   Three verbs, deliberately separate: **Run** shows the answer on screen with a summary
   over everything that matched (not just the page); **Export** produces the same rows
   as PDF, Excel or CSV with the parameters printed on them; **Save** keeps the question
   so the monthly pack is re-run live rather than re-built by hand. */

const PAGE_SIZE = 50;

type Filters = Record<string, string | string[]>;
type Named = { id: string; name?: string; title?: string; reference?: string; email?: string; full_name?: string };

/** Typeahead sources by name. Users and risks label themselves differently. */
function searchFor(source: string) {
  return (q: string) =>
    apiCall<PagedList<Named>>("GET", `/${source}?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((x) => ({
        value: x.id,
        label: x.full_name || x.name || (x.reference && x.title ? `${x.reference} — ${x.title}` : x.title) || x.email || x.id,
        sub: x.reference,
      })),
    );
}

const BLANK_SAVE = { name: "", description: "", shared: true };

/** Display name for one record a typeahead filter points at, from its own endpoint. */
async function nameOf(source: string, id: string): Promise<string> {
  const x = await apiCall<Named>("GET", `/${source}/${id}`);
  return x.full_name || x.name || (x.reference && x.title ? `${x.reference} — ${x.title}` : x.title) || x.email || id;
}

export default function ReportBuilderPage() {
  const [subjects, setSubjects] = useState<ReportSubject[]>([]);
  const [subjectKey, setSubjectKey] = useState("");
  const [title, setTitle] = useState("");
  const [filters, setFilters] = useState<Filters>({});
  // Display names for typeahead choices, so a loaded saved report shows "Internet
  // Banking" rather than a UUID until the user re-opens the picker.
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [columns, setColumns] = useState<string[]>([]);
  const [sortBy, setSortBy] = useState("");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [includeDetails, setIncludeDetails] = useState(false);

  const [run, setRun] = useState<ReportRun | null>(null);
  const [offset, setOffset] = useState(0);
  const [running, setRunning] = useState(false);
  const [exporting, setExporting] = useState<ReportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [saved, setSaved] = useState<SavedReport[]>([]);
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [showSave, setShowSave] = useState(false);
  const [saveForm, setSaveForm] = useState({ ...BLANK_SAVE });
  const [saving, setSaving] = useState(false);

  const subject = useMemo(() => subjects.find((s) => s.key === subjectKey) ?? null, [subjects, subjectKey]);

  // ------------------------------------------------------------- bootstrap
  const loadSaved = useCallback(() => {
    api.savedReports().then((p) => setSaved(p.items)).catch(() => {});
  }, []);

  useEffect(() => {
    api.reportSubjects()
      .then((list) => {
        setSubjects(list);
        if (list.length && !subjectKey) applySubject(list[0]);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load report subjects"));
    loadSaved();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Reset the definition to a subject's defaults. */
  function applySubject(s: ReportSubject) {
    setSubjectKey(s.key);
    setFilters({});
    setLabels({});
    setColumns(s.columns.filter((c) => c.default).map((c) => c.key));
    setSortBy(s.default_sort);
    setSortDir(s.default_sort_dir);
    setIncludeDetails(false);
    setRun(null);
    setOffset(0);
    setLoadedId(null);
    setTitle("");
  }

  function newReport() {
    if (subject) applySubject(subject);
  }

  const setFilter = (key: string, value: string | string[]) =>
    setFilters((f) => {
      const next = { ...f };
      if (value === "" || (Array.isArray(value) && value.length === 0)) delete next[key];
      else next[key] = value;
      return next;
    });

  const definition = (): ReportDefinition => ({
    subject: subjectKey,
    filters,
    columns,
    sort_by: sortBy || null,
    sort_dir: sortDir,
    include_details: includeDetails,
    title,
  });

  // ------------------------------------------------------------------ run
  async function runReport(nextOffset = 0) {
    if (!subject) return;
    setRunning(true);
    setError(null);
    try {
      const result = await api.runReport({ ...definition(), limit: PAGE_SIZE, offset: nextOffset });
      setRun(result);
      setOffset(nextOffset);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The report could not be run");
    } finally {
      setRunning(false);
    }
  }

  async function exportAs(format: ReportFormat) {
    if (!subject) return;
    setExporting(format);
    setError(null);
    try {
      await api.exportReport(definition(), format);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  // ----------------------------------------------------------------- save
  function openSave() {
    const current = saved.find((s) => s.id === loadedId);
    setSaveForm(current
      ? { name: current.name, description: current.description, shared: current.shared }
      : { ...BLANK_SAVE, name: title });
    setShowSave(true);
  }

  async function save(asNew: boolean) {
    if (!saveForm.name.trim()) {
      setError("Give the report a name.");
      return;
    }
    setSaving(true);
    try {
      const body = { ...definition(), title: saveForm.name.trim() };
      const current = saved.find((s) => s.id === loadedId);
      let result: SavedReport;
      if (current && !asNew) {
        result = await api.updateSavedReport(current.id, {
          name: saveForm.name.trim(), description: saveForm.description, definition: body, shared: saveForm.shared,
        });
        toast(`Saved changes to "${result.name}".`);
      } else {
        result = await api.createSavedReport({
          name: saveForm.name.trim(), description: saveForm.description, subject: subjectKey,
          definition: body, shared: saveForm.shared,
        });
        toast(`Saved "${result.name}"${saveForm.shared ? " for everyone" : ""}.`);
      }
      setLoadedId(result.id);
      setTitle(result.name);
      setShowSave(false);
      loadSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the report");
    } finally {
      setSaving(false);
    }
  }

  /** A saved definition holds ids. Resolve the ones behind typeahead filters so the
   *  form reads "Digital Banking", not a UUID, before the picker is ever opened. */
  function resolveLabels(s: ReportSubject, f: Filters) {
    for (const spec of s.filters) {
      const id = f[spec.key];
      if (spec.kind === "typeahead" && typeof id === "string" && id) {
        nameOf(spec.source, id)
          .then((label) => setLabels((l) => ({ ...l, [id]: label })))
          .catch(() => {});
      }
    }
  }

  function loadSavedReport(r: SavedReport) {
    const s = subjects.find((x) => x.key === r.subject);
    if (!s) return;
    const d = r.definition as Partial<ReportDefinition>;
    const f = (d.filters as Filters) ?? {};
    setSubjectKey(s.key);
    setFilters(f);
    setLabels({});
    resolveLabels(s, f);
    setColumns(d.columns?.length ? d.columns : s.columns.filter((c) => c.default).map((c) => c.key));
    setSortBy(d.sort_by || s.default_sort);
    setSortDir((d.sort_dir as "asc" | "desc") || s.default_sort_dir);
    setIncludeDetails(!!d.include_details);
    setTitle(r.name);
    setLoadedId(r.id);
    setRun(null);
    setOffset(0);
  }

  async function removeSaved(r: SavedReport) {
    const ok = await confirmDialog({
      title: `Delete "${r.name}"?`,
      message: "Only the saved question is removed. No records are affected.",
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteSavedReport(r.id);
      if (loadedId === r.id) setLoadedId(null);
      loadSaved();
      toast(`Deleted "${r.name}".`);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not delete");
    }
  }

  // --------------------------------------------------------------- render
  const sortable = subject?.columns.filter((c) => c.sortable) ?? [];
  const toggleColumn = (key: string) =>
    setColumns((c) => (c.includes(key) ? c.filter((k) => k !== key) : [...c, key]));

  const filterInput = (f: ReportFilterSpec) => {
    const v = filters[f.key];
    switch (f.kind) {
      case "multiselect":
        return <MultiSelect value={Array.isArray(v) ? v : v ? [v] : []} onChange={(x) => setFilter(f.key, x)} options={f.options} placeholder="Any" />;
      case "select":
      case "bool":
        return <Select value={typeof v === "string" ? v : ""} onChange={(x) => setFilter(f.key, x)} options={f.options} placeholder="Any" />;
      case "typeahead":
        return (
          <AsyncSelect
            search={searchFor(f.source)}
            value={typeof v === "string" ? v : null}
            selectedLabel={typeof v === "string" ? labels[v] : undefined}
            onChange={(id, opt) => {
              setFilter(f.key, id ?? "");
              if (id && opt) setLabels((l) => ({ ...l, [id]: opt.label }));
            }}
            placeholder="Any"
          />
        );
      case "date":
        return <TextInput value={typeof v === "string" ? v : ""} onChange={(x) => setFilter(f.key, x)} type="date" />;
      default:
        return <TextInput value={typeof v === "string" ? v : ""} onChange={(x) => setFilter(f.key, x)} placeholder={f.help || ""} />;
    }
  };

  const activeCount = Object.keys(filters).length;
  const pages = run ? Math.max(1, Math.ceil(run.total / PAGE_SIZE)) : 0;
  const pageNo = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Report Builder</h1>
          <p>Choose a subject, set the filters, pick the columns — then run it on screen, export it, or save the question for next month.</p>
        </div>
        <button className="btn secondary" onClick={newReport}>
          <IconPlus width={16} height={16} />
          New report
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 16, alignItems: "start" }}>
        {/* ------------------------------------------------------- saved list */}
        <div className="card card-pad">
          <div className="bt" style={{ marginBottom: 8 }}>Saved reports</div>
          {saved.length === 0 && <div className="muted" style={{ fontSize: 12.5 }}>Nothing saved yet. Build a report and press Save.</div>}
          <div style={{ display: "grid", gap: 6 }}>
            {saved.map((r) => (
              <div
                key={r.id}
                style={{
                  padding: "8px 10px", borderRadius: 8, cursor: "pointer",
                  border: `1px solid ${loadedId === r.id ? "var(--accent, #1d4fd7)" : "var(--border)"}`,
                }}
                onClick={() => loadSavedReport(r)}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontWeight: 600, fontSize: 13, flex: 1 }}>{r.name}</span>
                  <Badge tone="neutral" plain>{subjects.find((s) => s.key === r.subject)?.label ?? r.subject}</Badge>
                </div>
                {r.description && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{r.description}</div>}
                <div style={{ display: "flex", gap: 6, marginTop: 6 }} onClick={(e) => e.stopPropagation()}>
                  {(["pdf", "xlsx", "csv"] as ReportFormat[]).map((fmt) => (
                    <button key={fmt} className="btn secondary sm" onClick={() => api.exportSavedReport(r.id, fmt, r.name).catch((e) => toast(e.message))}>
                      {fmt.toUpperCase()}
                    </button>
                  ))}
                  <button className="btn secondary sm" style={{ marginLeft: "auto" }} onClick={() => removeSaved(r)}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ------------------------------------------------------ definition */}
        <div style={{ display: "grid", gap: 16 }}>
          <div className="card card-pad">
            <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 14 }}>
              <div style={{ width: 200 }}>
                <label className="label">Subject</label>
                <select
                  className="select"
                  value={subjectKey}
                  onChange={(e) => { const s = subjects.find((x) => x.key === e.target.value); if (s) applySubject(s); }}
                >
                  {subjects.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
              </div>
              <div style={{ flex: 1, minWidth: 240 }}>
                <label className="label">Report title</label>
                <TextInput value={title} onChange={setTitle} placeholder={subject ? `${subject.label} report` : ""} />
              </div>
              {loadedId && <Badge tone="info">Loaded from saved</Badge>}
            </div>

            {subject && (
              <>
                <div className="bt" style={{ marginBottom: 6 }}>
                  Filters {activeCount > 0 && <span className="muted" style={{ fontWeight: 400 }}>· {activeCount} set</span>}
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
                  {subject.filters.map((f) => (
                    <div key={f.key}>
                      <label className="label" title={f.help}>{f.label}</label>
                      {filterInput(f)}
                    </div>
                  ))}
                </div>

                <div className="bt" style={{ margin: "16px 0 6px" }}>
                  Columns <span className="muted" style={{ fontWeight: 400 }}>· {columns.length} chosen, in this order</span>
                  <button type="button" className="btn secondary sm" style={{ marginLeft: 10 }}
                    onClick={() => setColumns(subject.columns.filter((c) => c.default).map((c) => c.key))}>
                    Reset to default
                  </button>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {subject.columns.map((c) => {
                    const on = columns.includes(c.key);
                    return (
                      <button
                        key={c.key} type="button"
                        className={`chip${on ? " chip-link" : ""}`}
                        style={{ cursor: "pointer", opacity: on ? 1 : 0.55 }}
                        onClick={() => toggleColumn(c.key)}
                        title={on ? "Remove column" : "Add column"}
                      >
                        {on ? "✓ " : ""}{c.label}
                      </button>
                    );
                  })}
                </div>

                <div style={{ display: "flex", gap: 14, alignItems: "flex-end", flexWrap: "wrap", marginTop: 16 }}>
                  <div style={{ width: 200 }}>
                    <label className="label">Sort by</label>
                    <select className="select" value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                      {sortable.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                    </select>
                  </div>
                  <div style={{ width: 130 }}>
                    <label className="label">Direction</label>
                    <select className="select" value={sortDir} onChange={(e) => setSortDir(e.target.value as "asc" | "desc")}>
                      <option value="desc">Descending</option>
                      <option value="asc">Ascending</option>
                    </select>
                  </div>
                  {subject.has_detail && (
                    <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, paddingBottom: 8 }}>
                      <input type="checkbox" checked={includeDetails} onChange={(e) => setIncludeDetails(e.target.checked)} />
                      Detail page per record in the PDF
                    </label>
                  )}
                </div>

                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 18, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
                  <button className="btn" disabled={running} onClick={() => runReport(0)}>
                    {running ? "Running…" : "Run report"}
                  </button>
                  {(["pdf", "xlsx", "csv"] as ReportFormat[]).map((fmt) => (
                    <button key={fmt} className="btn secondary" disabled={exporting !== null} onClick={() => exportAs(fmt)}>
                      {exporting === fmt ? "Exporting…" : `Export ${fmt === "xlsx" ? "Excel" : fmt.toUpperCase()}`}
                    </button>
                  ))}
                  <button className="btn secondary" style={{ marginLeft: "auto" }} onClick={openSave}>
                    {loadedId ? "Save" : "Save report…"}
                  </button>
                </div>
              </>
            )}
          </div>

          {/* --------------------------------------------------------- results */}
          {run && (
            <div className="card card-pad">
              <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
                <strong style={{ fontSize: 14 }}>{run.total} record{run.total === 1 ? "" : "s"}</strong>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {run.params.length ? run.params.map(([k, v]) => `${k}: ${v}`).join(" · ") : "Whole register"}
                </span>
                {run.summary_over < run.total && (
                  <Badge tone="medium">Summary over the first {run.summary_over}</Badge>
                )}
              </div>

              {Object.keys(run.summary).length > 0 && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12, margin: "12px 0 16px" }}>
                  {Object.entries(run.summary).map(([section, counts]) => (
                    <div key={section} style={{ padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8 }}>
                      <div className="muted" style={{ fontSize: 12, fontWeight: 700, marginBottom: 6 }}>{section}</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
                          <Badge key={k} tone="neutral" plain>{k}: <b>{n}</b></Badge>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>{run.columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
                  </thead>
                  <tbody>
                    {run.items.length === 0 && (
                      <tr><td colSpan={run.columns.length} className="muted" style={{ padding: 18 }}>No records match these parameters.</td></tr>
                    )}
                    {run.items.map((row) => (
                      <tr key={row.id}>
                        {run.columns.map((c) => {
                          const v = row.cells[c.key];
                          return <td key={c.key} style={{ fontSize: 13 }}>{v === null || v === undefined || v === "" ? <span className="muted">—</span> : String(v)}</td>;
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {pages > 1 && (
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 12 }}>
                  <span className="muted" style={{ fontSize: 12.5 }}>Page {pageNo} of {pages}</span>
                  <button className="btn secondary sm" disabled={offset === 0 || running} onClick={() => runReport(Math.max(0, offset - PAGE_SIZE))}>‹ Prev</button>
                  <button className="btn secondary sm" disabled={offset + PAGE_SIZE >= run.total || running} onClick={() => runReport(offset + PAGE_SIZE)}>Next ›</button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {showSave && (
        <FormModal
          title={loadedId ? "Save report" : "Save report"}
          saving={saving}
          saveLabel={loadedId ? "Save changes" : "Save"}
          onClose={() => setShowSave(false)}
          onSave={() => save(false)}
          footerLeft={loadedId ? (
            <button type="button" className="btn secondary" disabled={saving} onClick={() => save(true)}>Save as new</button>
          ) : undefined}
          tabs={[{
            id: "save", label: "Report", required: true,
            content: (
              <>
                <Field label="Name" required help="How it will appear in the saved list and on the PDF cover.">
                  <TextInput value={saveForm.name} onChange={(v) => setSaveForm((f) => ({ ...f, name: v }))} placeholder="Critical risks — Digital Banking" required />
                </Field>
                <Field label="Description">
                  <TextArea value={saveForm.description} onChange={(v) => setSaveForm((f) => ({ ...f, description: v }))} placeholder="Monthly pack for the risk committee." rows={2} />
                </Field>
                <Field label="Visibility" help="Shared reports appear for everyone with access to the subject. Only the question is shared; each person sees the records they are allowed to.">
                  <Select value={saveForm.shared ? "shared" : "mine"} onChange={(v) => setSaveForm((f) => ({ ...f, shared: v === "shared" }))}
                    options={[{ value: "shared", label: "Shared with the organisation" }, { value: "mine", label: "Only me" }]} placeholder="Choose" />
                </Field>
              </>
            ),
          }]}
        />
      )}
    </>
  );
}
