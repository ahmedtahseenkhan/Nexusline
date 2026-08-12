"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";

/* ----------------------------------------------------------------- Types ---
   Mirrors the /io backend contract exactly. All defined inline per spec. */

type ColumnKind = "text" | "int" | "float" | "bool" | "date" | "enum" | "link";

interface SchemaColumn {
  header: string;
  field: string;
  required: boolean;
  kind: ColumnKind;
  enum_values: string[] | null;
  /** bool-ish / object / null — only its truthiness matters to the UI. */
  link: unknown;
  help?: string | null;
}

interface ResourceSchema {
  resource: string;
  label: string;
  importable: boolean;
  /** "" when this register has no custom fields. */
  custom_field_model: string;
  columns: SchemaColumn[];
}

interface CsvPayload {
  filename: string;
  csv: string;
}

interface ImportError {
  row: number;
  message: string;
}

interface ImportResult {
  total: number;
  created: number;
  skipped: number;
  errors: ImportError[];
}

interface MappingSuggestion {
  source: string;
  target: string;
  field: string;
  confidence: number;
  reason: string;
  band: "high" | "medium" | "low";
}

interface InspectResponse {
  csv: string;
  headers: string[];
  row_count: number;
  header_row_index: number;
  sheet_names: string[];
  sheet: string;
  sample_rows: string[][];
  suggestions: MappingSuggestion[];
  unmapped_source_headers: string[];
  unfilled_target_headers: string[];
  missing_required: string[];
}

interface PreviewRow {
  row: number;
  values: Record<string, string>;
  error: string;
}

interface PreviewResponse {
  total: number;
  previewed: number;
  valid: number;
  rows: PreviewRow[];
  columns: string[];
}

interface ImportProfile {
  id: string;
  resource: string;
  name: string;
  description: string;
  mapping: Record<string, string>;
  custom_field_mapping: Record<string, string>;
  created_by_email: string;
  created_at: string;
}

interface CustomFieldRead {
  id: string;
  model: string;
  label: string;
  field_type: string;
  enabled: boolean;
}

interface Page<T> {
  items: T[];
  total: number;
}

type Props = {
  resource: string;
  label: string;
  /** Optional: pages pass this to refresh their data after a successful import. */
  onDone?: () => void;
};

/** Where a client column goes: one of our fields, a custom field, or nowhere. */
type Destination =
  | { kind: "ignore" }
  | { kind: "field"; target: string }
  | { kind: "custom"; customFieldId: string };

type Step = 1 | 2 | 3 | 4;

/* --------------------------------------------------------------- Helpers --- */

/** Trigger a browser download of CSV text via a transient object URL. */
function downloadCsv(filename: string, csv: string) {
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "export.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const KIND_LABEL: Record<ColumnKind, string> = {
  text: "Text",
  int: "Whole number",
  float: "Number",
  bool: "true / false",
  date: "Date (YYYY-MM-DD)",
  enum: "Choice",
  link: "Reference",
};

function acceptedFor(col: SchemaColumn): string {
  if (col.kind === "enum" && col.enum_values && col.enum_values.length)
    return col.enum_values.join(", ");
  if (col.kind === "link" || col.link) return "comma-separated references";
  if (col.kind === "bool") return "true, false, yes, no, 1, 0";
  if (col.kind === "date") return "YYYY-MM-DD";
  if (col.kind === "int") return "whole number, e.g. 42";
  if (col.kind === "float") return "number, e.g. 3.5";
  return "free text";
}

/** Read a file as base64 (xlsx) — strips the data: URL prefix the reader adds. */
function readAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function errorText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

const BAND_TONE: Record<MappingSuggestion["band"], "low" | "medium" | "critical"> = {
  high: "low",
  medium: "medium",
  low: "critical",
};

const BAND_LABEL: Record<MappingSuggestion["band"], string> = {
  high: "Confident",
  medium: "Check",
  low: "Unsure",
};

/* ---------------------------------------------------------------- Export --- */

/** Reusable Export / Template / Import control. */
export default function ImportExport({ resource, label, onDone }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"export" | "template" | null>(null);
  const [barError, setBarError] = useState<string | null>(null);

  async function doDownload(kind: "export" | "template") {
    setBarError(null);
    setBusy(kind);
    try {
      const data = await apiCall<CsvPayload>("GET", `/io/${resource}/${kind}`);
      downloadCsv(data.filename, data.csv);
    } catch (e) {
      setBarError(errorText(e, `Failed to download ${kind}`));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
        <div style={{ display: "inline-flex", gap: 6 }}>
          <button
            className="btn secondary sm"
            onClick={() => doDownload("export")}
            disabled={busy !== null}
            title={`Download all ${label} as CSV`}
          >
            {busy === "export" ? "Exporting…" : "Export CSV"}
          </button>
          <button
            className="btn secondary sm"
            onClick={() => doDownload("template")}
            disabled={busy !== null}
            title="Download a demo CSV with headers and an example row"
          >
            {busy === "template" ? "…" : "Template"}
          </button>
          <button
            className="btn secondary sm"
            onClick={() => setOpen(true)}
            title={`Import ${label} from your own spreadsheet`}
          >
            Import
          </button>
        </div>
        {barError && (
          <div className="error" style={{ margin: 0, fontSize: 12 }}>
            {barError}
          </div>
        )}
      </div>

      {open && (
        <ImportWizard
          resource={resource}
          label={label}
          onClose={() => setOpen(false)}
          onDownloadTemplate={() => doDownload("template")}
          onDone={onDone}
        />
      )}
    </>
  );
}

/* -------------------------------------------------------- Import wizard --- */
/* Upload → Map → Preview → Import. The client's own spreadsheet is accepted as-is:
   step 1 detects its columns, step 2 matches them to ours (auto-filled, editable),
   step 3 dry-runs the mapping without writing, step 4 commits. A confirmed mapping
   can be saved so the next upload skips straight to preview. */

function ImportWizard({
  resource,
  label,
  onClose,
  onDownloadTemplate,
  onDone,
}: {
  resource: string;
  label: string;
  onClose: () => void;
  onDownloadTemplate: () => void;
  onDone?: () => void;
}) {
  const [step, setStep] = useState<Step>(1);
  const [schema, setSchema] = useState<ResourceSchema | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  // Step 1 — the uploaded file
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<InspectResponse | null>(null);
  const [inspecting, setInspecting] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  // Step 2 — the mapping being edited
  const [destinations, setDestinations] = useState<Record<string, Destination>>({});
  const [customFields, setCustomFields] = useState<CustomFieldRead[]>([]);
  const [profiles, setProfiles] = useState<ImportProfile[]>([]);
  const [profileName, setProfileName] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileNote, setProfileNote] = useState<string | null>(null);

  // Step 3 — dry run
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Step 4 — commit
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  // Load the schema and any saved profiles; lock body scroll + Escape-to-close.
  useEffect(() => {
    let alive = true;
    apiCall<ResourceSchema>("GET", `/io/${resource}/schema`)
      .then((s) => alive && setSchema(s))
      .catch((e) => alive && setSchemaError(errorText(e, "Failed to load schema")));
    apiCall<ImportProfile[]>("GET", `/io/${resource}/profiles`)
      .then((p) => alive && setProfiles(p))
      .catch(() => {/* profiles are optional — never block the wizard on them */});

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      alive = false;
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [resource, onClose]);

  // Custom fields are only offered for registers that support them.
  useEffect(() => {
    const model = schema?.custom_field_model;
    if (!model) return;
    let alive = true;
    apiCall<Page<CustomFieldRead>>("GET", `/custom-fields?model=${encodeURIComponent(model)}&limit=200`)
      .then((page) => alive && setCustomFields(page.items.filter((f) => f.enabled)))
      .catch(() => {/* optional */});
    return () => {
      alive = false;
    };
  }, [schema?.custom_field_model]);

  const columnByHeader = useMemo(() => {
    const map = new Map<string, SchemaColumn>();
    for (const col of schema?.columns ?? []) map.set(col.header, col);
    return map;
  }, [schema]);

  const suggestionBySource = useMemo(() => {
    const map = new Map<string, MappingSuggestion>();
    for (const s of inspection?.suggestions ?? []) map.set(s.source, s);
    return map;
  }, [inspection]);

  /** Split the edited destinations into the two payloads the API expects. */
  const { mapping, customMapping } = useMemo(() => {
    const fieldMap: Record<string, string> = {};
    const customMap: Record<string, string> = {};
    for (const [source, dest] of Object.entries(destinations)) {
      if (dest.kind === "field") fieldMap[source] = dest.target;
      else if (dest.kind === "custom") customMap[source] = dest.customFieldId;
    }
    return { mapping: fieldMap, customMapping: customMap };
  }, [destinations]);

  const takenTargets = useMemo(() => new Set(Object.values(mapping)), [mapping]);

  const missingRequired = useMemo(() => {
    const required = (schema?.columns ?? []).filter((c) => c.required).map((c) => c.header);
    return required.filter((header) => !takenTargets.has(header));
  }, [schema, takenTargets]);

  const mappedCount = Object.keys(mapping).length;
  const customCount = Object.keys(customMapping).length;
  const ignoredCount = (inspection?.headers.length ?? 0) - mappedCount - customCount;

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    setFileError(null);
    setInspection(null);
    setDestinations({});
    setPreview(null);
    setResult(null);
    setFile(picked);
    if (picked) await inspect(picked, undefined);
  }

  /** Ask the backend what is in the file and how it proposes to read it. */
  const inspect = useCallback(
    async (picked: File, sheet: string | undefined) => {
      setInspecting(true);
      setFileError(null);
      try {
        const isExcel = /\.xlsx?$/i.test(picked.name);
        const body = isExcel
          ? { file_b64: await readAsBase64(picked), filename: picked.name, sheet }
          : { content: await picked.text(), filename: picked.name };
        const found = await apiCall<InspectResponse>("POST", `/io/${resource}/inspect`, body);
        setInspection(found);
        // Preselect the suggested mapping; everything else starts ignored, so an
        // unrecognised column is never silently imported.
        const next: Record<string, Destination> = {};
        for (const header of found.headers) next[header] = { kind: "ignore" };
        for (const s of found.suggestions) next[s.source] = { kind: "field", target: s.target };
        setDestinations(next);
      } catch (err) {
        setFileError(errorText(err, "Could not read that file"));
        setInspection(null);
      } finally {
        setInspecting(false);
      }
    },
    [resource],
  );

  function applyProfile(profile: ImportProfile | null) {
    if (!inspection) return;
    const next: Record<string, Destination> = {};
    for (const header of inspection.headers) next[header] = { kind: "ignore" };
    if (profile) {
      for (const [source, target] of Object.entries(profile.mapping)) {
        if (hasHeader(inspection,source)) next[source] = { kind: "field", target };
      }
      for (const [source, id] of Object.entries(profile.custom_field_mapping)) {
        if (hasHeader(inspection,source)) next[source] = { kind: "custom", customFieldId: id };
      }
      setProfileName(profile.name);
    } else {
      for (const s of inspection.suggestions) next[s.source] = { kind: "field", target: s.target };
      setProfileName("");
    }
    setDestinations(next);
    setProfileNote(null);
  }

  function setDestination(source: string, raw: string) {
    setDestinations((prev) => {
      const next = { ...prev };
      if (raw === "") next[source] = { kind: "ignore" };
      else if (raw.startsWith("cf:")) next[source] = { kind: "custom", customFieldId: raw.slice(3) };
      else {
        // One field can only be filled by one column; release whoever held it.
        for (const [other, dest] of Object.entries(next)) {
          if (other !== source && dest.kind === "field" && dest.target === raw) {
            next[other] = { kind: "ignore" };
          }
        }
        next[source] = { kind: "field", target: raw };
      }
      return next;
    });
  }

  async function runPreview() {
    if (!inspection) return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      const res = await apiCall<PreviewResponse>("POST", `/io/${resource}/preview`, {
        content: inspection.csv,
        mapping,
        custom_field_mapping: customMapping,
        limit: 20,
      });
      setPreview(res);
      setStep(3);
    } catch (e) {
      setPreviewError(errorText(e, "Preview failed"));
    } finally {
      setPreviewing(false);
    }
  }

  async function runImport() {
    if (!inspection) return;
    setImporting(true);
    setImportError(null);
    setResult(null);
    try {
      const res = await apiCall<ImportResult>("POST", `/io/${resource}/import`, {
        content: inspection.csv,
        mapping,
        custom_field_mapping: customMapping,
      });
      setResult(res);
      setStep(4);
      if (res.created > 0) onDone?.();
    } catch (e) {
      setImportError(errorText(e, "Import failed"));
    } finally {
      setImporting(false);
    }
  }

  async function saveProfile() {
    if (!profileName.trim()) return;
    setSavingProfile(true);
    setProfileNote(null);
    try {
      const saved = await apiCall<ImportProfile>("POST", `/io/${resource}/profiles`, {
        name: profileName.trim(),
        description: "",
        mapping,
        custom_field_mapping: customMapping,
      });
      setProfiles((prev) => [...prev.filter((p) => p.id !== saved.id), saved].sort((a, b) => a.name.localeCompare(b.name)));
      setProfileNote(`Saved as “${saved.name}” — it will be offered next time.`);
    } catch (e) {
      setProfileNote(errorText(e, "Could not save the mapping"));
    } finally {
      setSavingProfile(false);
    }
  }

  function downloadErrors() {
    if (!result) return;
    const rows = [["row", "message"], ...result.errors.map((e) => [String(e.row), e.message])];
    const csv = rows
      .map((r) => r.map((cell) => (/[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell)).join(","))
      .join("\n");
    downloadCsv(`${resource}_import_errors.csv`, csv);
  }

  function done() {
    onDone?.();
    onClose();
  }

  const canMap = inspection !== null && inspection.headers.length > 0;
  const canPreview = canMap && mappedCount > 0 && missingRequired.length === 0;

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide" role="dialog" aria-modal="true" aria-label={`Import ${label}`}>
        <div className="modal-head">
          <h2>Import {label}</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          <StepBar step={step} />

          {schemaError && <div className="error">{schemaError}</div>}

          {/* ------------------------------------------------ Step 1: upload */}
          {step === 1 && (
            <>
              <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, marginTop: 0 }}>
                Upload the spreadsheet you already keep — <b>your own column names are fine</b>.
                We read its headings and match them to our fields on the next step, where you
                can correct anything before a single record is created. CSV and Excel (.xlsx)
                are both accepted. Prefer to start from our layout?{" "}
                <button
                  type="button"
                  className="btn secondary sm"
                  style={{ padding: "1px 8px", fontSize: 12 }}
                  onClick={onDownloadTemplate}
                >
                  Download template
                </button>
              </p>

              <div className="field">
                <label>Spreadsheet</label>
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={onPickFile}
                  className="input"
                  style={{ padding: 8 }}
                />
                {fileError && <div className="error" style={{ marginTop: 10 }}>{fileError}</div>}
                {inspecting && (
                  <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
                    Reading {file?.name}…
                  </div>
                )}
              </div>

              {inspection && (
                <div className="card card-pad" style={{ marginTop: 4 }}>
                  <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                    <Badge tone="info">{inspection.headers.length} columns</Badge>
                    <Badge tone="info">{inspection.row_count} rows</Badge>
                    <Badge tone="low">{inspection.suggestions.length} matched automatically</Badge>
                    {inspection.unmapped_source_headers.length > 0 && (
                      <Badge tone="medium">
                        {inspection.unmapped_source_headers.length} need a decision
                      </Badge>
                    )}
                  </div>

                  {inspection.header_row_index > 0 && (
                    <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
                      Skipped {inspection.header_row_index} row(s) above the headings — headings
                      were found on row {inspection.header_row_index + 1}.
                    </div>
                  )}

                  {inspection.sheet_names.length > 1 && (
                    <div className="field" style={{ marginTop: 12, marginBottom: 0 }}>
                      <label>Sheet</label>
                      <select
                        className="input"
                        value={inspection.sheet}
                        onChange={(e) => file && inspect(file, e.target.value)}
                      >
                        {inspection.sheet_names.map((name) => (
                          <option key={name} value={name}>{name}</option>
                        ))}
                      </select>
                    </div>
                  )}

                  {profiles.length > 0 && (
                    <div className="field" style={{ marginTop: 12, marginBottom: 0 }}>
                      <label>Saved mapping</label>
                      <select
                        className="input"
                        defaultValue=""
                        onChange={(e) =>
                          applyProfile(profiles.find((p) => p.id === e.target.value) ?? null)
                        }
                      >
                        <option value="">Suggested mapping (auto-detected)</option>
                        {profiles.map((p) => (
                          <option key={p.id} value={p.id}>{p.name}</option>
                        ))}
                      </select>
                      <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                        Reuse the mapping confirmed on a previous upload of this file layout.
                      </div>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {/* --------------------------------------------------- Step 2: map */}
          {step === 2 && inspection && schema && (
            <>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
                <Badge tone="low">{mappedCount} mapped</Badge>
                {customCount > 0 && <Badge tone="info">{customCount} to custom fields</Badge>}
                {ignoredCount > 0 && <Badge tone="neutral">{ignoredCount} ignored</Badge>}
              </div>

              {missingRequired.length > 0 && (
                <div className="error" style={{ marginBottom: 12 }}>
                  Required field{missingRequired.length !== 1 ? "s" : ""} not yet mapped:{" "}
                  <b>{missingRequired.join(", ")}</b>. Choose which of your columns fills{" "}
                  {missingRequired.length !== 1 ? "them" : "it"}.
                </div>
              )}

              <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: "26%" }}>Your column</th>
                      <th style={{ width: "24%" }}>Example from your file</th>
                      <th style={{ width: "30%" }}>Imports into</th>
                      <th style={{ width: "20%" }}>Match</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inspection.headers.map((header, index) => {
                      const dest = destinations[header] ?? { kind: "ignore" as const };
                      const suggestion = suggestionBySource.get(header);
                      const sample = inspection.sample_rows
                        .map((row) => row[index])
                        .find((value) => value && value.trim());
                      const value =
                        dest.kind === "field" ? dest.target
                        : dest.kind === "custom" ? `cf:${dest.customFieldId}`
                        : "";
                      return (
                        <tr key={header}>
                          <td className="cell-title">{header}</td>
                          <td className="muted" style={{ fontSize: 12.5 }}>
                            {sample ? truncate(sample, 60) : "—"}
                          </td>
                          <td>
                            <select
                              className="input"
                              style={{ padding: "5px 8px", fontSize: 13 }}
                              value={value}
                              onChange={(e) => setDestination(header, e.target.value)}
                            >
                              <option value="">— Do not import —</option>
                              <optgroup label={`${schema.label} fields`}>
                                {schema.columns.map((col) => (
                                  <option
                                    key={col.header}
                                    value={col.header}
                                    disabled={takenTargets.has(col.header) && !(dest.kind === "field" && dest.target === col.header)}
                                  >
                                    {col.header}
                                    {col.required ? " (required)" : ""}
                                  </option>
                                ))}
                              </optgroup>
                              {customFields.length > 0 && (
                                <optgroup label="Custom fields">
                                  {customFields.map((cf) => (
                                    <option key={cf.id} value={`cf:${cf.id}`}>{cf.label}</option>
                                  ))}
                                </optgroup>
                              )}
                            </select>
                          </td>
                          <td>
                            {dest.kind === "ignore" ? (
                              <span className="muted" style={{ fontSize: 12 }}>Ignored</span>
                            ) : dest.kind === "custom" ? (
                              <Badge tone="info">Custom field</Badge>
                            ) : suggestion && suggestion.target === dest.target ? (
                              <span title={suggestion.reason}>
                                <Badge tone={BAND_TONE[suggestion.band]}>{BAND_LABEL[suggestion.band]}</Badge>{" "}
                                <span className="muted" style={{ fontSize: 11.5 }}>
                                  {suggestion.reason}
                                </span>
                              </span>
                            ) : (
                              <Badge tone="neutral" plain>Set by you</Badge>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {schema.custom_field_model && customFields.length === 0 && ignoredCount > 0 && (
                <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
                  Want to keep a column we have no field for? Create it under Settings → Custom
                  Fields for “{schema.custom_field_model}”, then reopen this wizard.
                </div>
              )}

              <details style={{ marginTop: 14 }}>
                <summary className="muted" style={{ fontSize: 12.5, cursor: "pointer" }}>
                  What each of our fields accepts
                </summary>
                <div className="table-wrap" style={{ marginTop: 10, maxHeight: 260, overflowY: "auto" }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Required</th>
                        <th>Type</th>
                        <th>Accepted values / format</th>
                      </tr>
                    </thead>
                    <tbody>
                      {schema.columns.map((col) => (
                        <tr key={col.header}>
                          <td className="cell-title"><code>{col.header}</code></td>
                          <td>
                            {col.required ? <Badge tone="medium">Yes</Badge> : <Badge tone="neutral" plain>No</Badge>}
                          </td>
                          <td className="muted">{KIND_LABEL[col.kind] ?? col.kind}</td>
                          <td className="muted">{acceptedFor(col)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>

              {previewError && <div className="error" style={{ marginTop: 12 }}>{previewError}</div>}
            </>
          )}

          {/* ----------------------------------------------- Step 3: preview */}
          {step === 3 && preview && (
            <>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center", marginBottom: 6 }}>
                <Badge tone={preview.valid === preview.previewed ? "low" : "medium"}>
                  {preview.valid} of {preview.previewed} shown rows are valid
                </Badge>
                <Badge tone="info">{preview.total} rows in the file</Badge>
              </div>
              <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
                Nothing has been saved yet. This is exactly how the first {preview.previewed} row
                {preview.previewed !== 1 ? "s" : ""} will be read — including references that
                point at records which do not exist yet.
              </p>

              <div className="table-wrap" style={{ maxHeight: 400, overflowY: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 60 }}>Row</th>
                      {preview.columns.map((col) => <th key={col}>{col}</th>)}
                      <th style={{ width: "22%" }}>Problem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row) => (
                      <tr key={row.row}>
                        <td className="ref">{row.row}</td>
                        {preview.columns.map((col) => (
                          <td key={col} className="muted" style={{ fontSize: 12.5 }}>
                            {truncate(row.values[col] ?? "", 40)}
                          </td>
                        ))}
                        <td style={{ color: row.error ? "var(--red)" : undefined, fontSize: 12.5 }}>
                          {row.error || "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="card card-pad" style={{ marginTop: 14 }}>
                <label style={{ fontSize: 12.5, fontWeight: 560 }}>Save this mapping for next time</label>
                <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  <input
                    className="input"
                    style={{ flex: "1 1 220px", padding: "6px 9px", fontSize: 13 }}
                    placeholder="e.g. Quarterly risk register (Head Office)"
                    value={profileName}
                    onChange={(e) => setProfileName(e.target.value)}
                  />
                  <button
                    className="btn secondary sm"
                    type="button"
                    onClick={saveProfile}
                    disabled={savingProfile || !profileName.trim()}
                  >
                    {savingProfile ? "Saving…" : "Save mapping"}
                  </button>
                </div>
                {profileNote && (
                  <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>{profileNote}</div>
                )}
              </div>

              {importError && <div className="error" style={{ marginTop: 12 }}>{importError}</div>}
            </>
          )}

          {/* ------------------------------------------------ Step 4: result */}
          {step === 4 && result && (
            <div className="card card-pad">
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                <Badge tone="low">Created {result.created}</Badge>
                <Badge tone="neutral">Skipped {result.skipped}</Badge>
                <Badge tone="info">Total {result.total}</Badge>
                {result.errors.length > 0 && (
                  <Badge tone="critical">
                    {result.errors.length} error{result.errors.length !== 1 ? "s" : ""}
                  </Badge>
                )}
              </div>

              {result.errors.length === 0 ? (
                <div
                  style={{
                    marginTop: 12,
                    background: "var(--green-bg)",
                    color: "var(--green)",
                    border: "1px solid #bfe3cc",
                    borderRadius: "var(--radius-sm)",
                    padding: "9px 12px",
                    fontSize: 13,
                    fontWeight: 560,
                  }}
                >
                  Import complete — {result.created} record{result.created !== 1 ? "s" : ""} created
                  {result.skipped ? `, ${result.skipped} skipped` : ""}.
                </div>
              ) : (
                <div style={{ marginTop: 14 }}>
                  <div className="error" style={{ marginBottom: 10, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                    <span>
                      {result.created} row{result.created !== 1 ? "s" : ""} imported; the rows below
                      were skipped. Every other row was saved — fix these and re-import just them.
                    </span>
                    <button className="btn secondary sm" type="button" onClick={downloadErrors}>
                      Download errors
                    </button>
                  </div>
                  <div
                    className="table-wrap"
                    style={{ maxHeight: 240, overflowY: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}
                  >
                    <table>
                      <thead>
                        <tr>
                          <th style={{ width: 80 }}>Row</th>
                          <th>Message</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.errors.map((err, i) => (
                          <tr key={`${err.row}-${i}`}>
                            <td className="ref" style={{ color: "var(--red)" }}>{err.row}</td>
                            <td style={{ color: "var(--red)" }}>{err.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ------------------------------------------------------ Footer --- */}
        <div className="modal-foot">
          <button
            className="btn secondary"
            type="button"
            onClick={step === 1 || step === 4 ? onClose : () => setStep((step - 1) as Step)}
            disabled={importing}
          >
            {step === 1 || step === 4 ? "Cancel" : "Back"}
          </button>

          {step === 1 && (
            <button
              className="btn"
              type="button"
              onClick={() => setStep(2)}
              disabled={!canMap || inspecting}
              title={!canMap ? "Choose a spreadsheet first" : undefined}
            >
              Next: match columns
            </button>
          )}
          {step === 2 && (
            <button
              className="btn"
              type="button"
              onClick={runPreview}
              disabled={!canPreview || previewing}
              title={
                missingRequired.length > 0
                  ? `Map the required field(s): ${missingRequired.join(", ")}`
                  : mappedCount === 0
                    ? "Map at least one column"
                    : undefined
              }
            >
              {previewing ? "Checking…" : "Next: preview"}
            </button>
          )}
          {step === 3 && (
            <button className="btn" type="button" onClick={runImport} disabled={importing}>
              {importing ? "Importing…" : `Import ${preview?.total ?? 0} row${(preview?.total ?? 0) !== 1 ? "s" : ""}`}
            </button>
          )}
          {step === 4 && (
            <button className="btn" type="button" onClick={done}>Done</button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Step bar --- */

const STEP_LABELS: Record<Step, string> = {
  1: "Upload",
  2: "Match columns",
  3: "Preview",
  4: "Result",
};

function StepBar({ step }: { step: Step }) {
  return (
    <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
      {([1, 2, 3, 4] as Step[]).map((n) => {
        const state = n === step ? "current" : n < step ? "done" : "todo";
        return (
          <div
            key={n}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: "var(--radius-sm)",
              fontSize: 12.5,
              fontWeight: state === "current" ? 600 : 500,
              background: state === "current" ? "var(--primary-weak-2)" : "transparent",
              color: state === "todo" ? "var(--muted)" : state === "current" ? "var(--primary-text)" : "var(--text)",
              border: `1px solid ${state === "current" ? "var(--primary-weak)" : "transparent"}`,
            }}
          >
            <span aria-hidden>{state === "done" ? "✓" : n}</span>
            {STEP_LABELS[n]}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------ Utilities --- */

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

/** A saved profile may name columns this particular file does not have. */
function hasHeader(inspection: InspectResponse, header: string): boolean {
  return inspection.headers.includes(header);
}
