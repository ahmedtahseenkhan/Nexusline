"use client";

import { useEffect, useState } from "react";
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

type Props = {
  resource: string;
  label: string;
  /** Optional: pages pass this to refresh their data after a successful import. */
  onDone?: () => void;
};

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
      setBarError(e instanceof Error ? e.message : `Failed to download ${kind}`);
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
            title={`Import ${label} from CSV`}
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
        <ImportModal
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

/* --------------------------------------------------------- Import modal --- */

function ImportModal({
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
  const [schema, setSchema] = useState<ResourceSchema | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  const [fileName, setFileName] = useState<string>("");
  const [content, setContent] = useState<string>("");
  const [fileError, setFileError] = useState<string | null>(null);

  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  // Load the guidance schema; lock body scroll + Escape-to-close like FormModal.
  useEffect(() => {
    let alive = true;
    apiCall<ResourceSchema>("GET", `/io/${resource}/schema`)
      .then((s) => alive && setSchema(s))
      .catch((e) => alive && setSchemaError(e instanceof Error ? e.message : "Failed to load schema"));

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

  async function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    setFileError(null);
    setResult(null);
    setImportError(null);
    const file = e.target.files?.[0];
    if (!file) {
      setFileName("");
      setContent("");
      return;
    }
    setFileName(file.name);
    try {
      const text = await file.text();
      setContent(text);
    } catch {
      try {
        const text = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result || ""));
          reader.onerror = () => reject(reader.error);
          reader.readAsText(file);
        });
        setContent(text);
      } catch {
        setFileError("Could not read that file. Please choose a valid .csv file.");
        setContent("");
      }
    }
  }

  async function runImport() {
    setImporting(true);
    setImportError(null);
    setResult(null);
    try {
      const res = await apiCall<ImportResult>("POST", `/io/${resource}/import`, { content });
      setResult(res);
      // Refresh the parent whenever anything was created.
      if (res.created > 0) onDone?.();
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Import failed");
    } finally {
      setImporting(false);
    }
  }

  function done() {
    onDone?.();
    onClose();
  }

  const succeeded = result !== null && result.errors.length === 0;

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="modal wide" role="dialog" aria-modal="true" aria-label={`Import ${label}`}>
        <div className="modal-head">
          <h2>Import {label}</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="modal-body">
          {/* (a) How-to callout */}
          <div
            className="card card-pad"
            style={{ background: "var(--primary-weak-2)", borderColor: "var(--primary-weak)", marginBottom: 18 }}
          >
            <b style={{ fontSize: 13.5, color: "var(--primary-text)" }}>How to import</b>
            <ol style={{ margin: "8px 0 0", paddingLeft: 20, color: "var(--text)", fontSize: 13, lineHeight: 1.7 }}>
              <li>
                Click{" "}
                <button
                  type="button"
                  className="btn secondary sm"
                  style={{ padding: "1px 8px", fontSize: 12 }}
                  onClick={onDownloadTemplate}
                >
                  Template
                </button>{" "}
                to download a demo CSV (it includes the headers and one example row).
              </li>
              <li>Keep the header row; add one row per record.</li>
              <li>Save as <code>.csv</code>.</li>
              <li>Choose your file below and import.</li>
              <li className="muted">
                Blank cells are skipped; links accept comma-separated references.
              </li>
            </ol>
          </div>

          {/* (b) Guidance table from the schema */}
          <div className="card" style={{ marginBottom: 18 }}>
            <div className="card-head">
              <h3>Columns</h3>
              <span className="sub">
                {schema ? `${schema.columns.length} field${schema.columns.length !== 1 ? "s" : ""}` : "Loading…"}
              </span>
            </div>
            {schemaError && <div className="error" style={{ margin: 16 }}>{schemaError}</div>}
            {!schema && !schemaError && (
              <div className="card-pad muted" style={{ fontSize: 13 }}>Loading column guidance…</div>
            )}
            {schema && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Column</th>
                      <th>Required</th>
                      <th>Type</th>
                      <th>Accepted values / format</th>
                      <th>Notes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {schema.columns.map((col) => (
                      <tr key={col.header}>
                        <td className="cell-title"><code>{col.header}</code></td>
                        <td>
                          {col.required ? (
                            <Badge tone="medium">Yes</Badge>
                          ) : (
                            <Badge tone="neutral" plain>No</Badge>
                          )}
                        </td>
                        <td className="muted">{KIND_LABEL[col.kind] ?? col.kind}</td>
                        <td className="muted">{acceptedFor(col)}</td>
                        <td className="muted">{col.help || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* (c) File input */}
          <div className="field" style={{ marginBottom: 0 }}>
            <label>CSV file</label>
            <input
              type="file"
              accept=".csv"
              onChange={onPickFile}
              className="input"
              style={{ padding: 8 }}
            />
            {fileName && (
              <div className="muted" style={{ fontSize: 12.5, marginTop: 6 }}>
                Selected: <b>{fileName}</b>
                {content ? ` · ${content.split(/\r\n|\r|\n/).filter((l) => l.trim()).length} non-empty line(s)` : ""}
              </div>
            )}
            {fileError && <div className="error" style={{ marginTop: 10 }}>{fileError}</div>}
          </div>

          {/* (e) Result panel */}
          {importError && <div className="error" style={{ marginTop: 18 }}>{importError}</div>}

          {result && (
            <div className="card card-pad" style={{ marginTop: 18 }}>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
                <Badge tone="low">Created {result.created}</Badge>
                <Badge tone="neutral">Skipped {result.skipped}</Badge>
                <Badge tone="info">Total {result.total}</Badge>
                {result.errors.length > 0 && (
                  <Badge tone="critical">{result.errors.length} error{result.errors.length !== 1 ? "s" : ""}</Badge>
                )}
              </div>

              {succeeded ? (
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
                  <div className="error" style={{ marginBottom: 10 }}>
                    Some rows could not be imported. Fix the lines below and re-import.
                  </div>
                  <div className="table-wrap" style={{ maxHeight: 240, overflowY: "auto", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
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

        {/* (d) Footer actions */}
        <div className="modal-foot">
          <button className="btn secondary" onClick={onClose} type="button" disabled={importing}>
            Cancel
          </button>
          {result ? (
            <button className="btn" onClick={done} type="button">
              Done
            </button>
          ) : (
            <button
              className="btn"
              onClick={runImport}
              type="button"
              disabled={importing || !content}
              title={!content ? "Choose a .csv file first" : undefined}
            >
              {importing ? "Importing…" : "Import"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
