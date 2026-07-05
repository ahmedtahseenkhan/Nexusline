"use client";

import { useEffect, useState } from "react";
import { apiCall, type Page } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconActivity, IconCheck, IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ local types
interface AiExtraction {
  id: string;
  reference: string;
  source_type: string;
  extraction_type: string;
  title: string;
  input_text: string;
  output_text: string;
  model_used: string;
  status: string;
  created_by: string;
  created_at: string;
}
interface AiTypeRow {
  extraction_type: string;
  count: number;
  ai_count: number;
  heuristic_count: number;
}
interface AiSummary {
  rows: AiTypeRow[];
  total: number;
  ai_count: number;
  heuristic_count: number;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const SOURCE_TYPES = ["circular", "policy", "free_text", "incident"];
const EXTRACTION_TYPES = ["obligations", "summary", "risk_suggestions", "control_mapping"];

const EXTRACTION_LABEL: Record<string, string> = {
  obligations: "Extract obligations",
  summary: "Summarise",
  risk_suggestions: "Suggest risks",
  control_mapping: "Map controls",
};
const TYPE_TONE: Record<string, Tone> = {
  obligations: "info",
  summary: "neutral",
  risk_suggestions: "high",
  control_mapping: "low",
};
const STATUS_TONE: Record<string, Tone> = { completed: "low", pending: "info", failed: "critical" };

const SAMPLE =
  "SBP circular: All authorized dealers shall ensure that customer due diligence is " +
  "completed before opening any account. Banks must report suspicious transactions to " +
  "the FMU within 7 days of detection. Institutions are required to implement " +
  "multi-factor authentication for all digital banking channels no later than 31 " +
  "December 2026. Encryption of data in transit is mandatory.";

// Render the model's plain-text output. Obligations / risk statements become an ordered
// list; control mappings a bullet list; summaries render as paragraphs + bullets.
function OutputView({ item }: { item: AiExtraction }) {
  const lines = (item.output_text || "").split("\n").map((l) => l.trim()).filter(Boolean);
  if (lines.length === 0) return <p className="muted">No output.</p>;

  const stripNum = (l: string) => l.replace(/^\d+[.)]\s*/, "").replace(/^[-*]\s*/, "");

  if (item.extraction_type === "obligations" || item.extraction_type === "risk_suggestions") {
    return (
      <ol style={{ margin: 0, paddingLeft: 22, display: "flex", flexDirection: "column", gap: 8 }}>
        {lines.map((l, i) => (
          <li key={i} style={{ lineHeight: 1.5 }}>{stripNum(l)}</li>
        ))}
      </ol>
    );
  }
  if (item.extraction_type === "control_mapping") {
    return (
      <ul style={{ margin: 0, paddingLeft: 22, display: "flex", flexDirection: "column", gap: 6 }}>
        {lines.map((l, i) => (
          <li key={i} style={{ lineHeight: 1.5 }}>{stripNum(l)}</li>
        ))}
      </ul>
    );
  }
  // summary
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {lines.map((l, i) =>
        l.startsWith("-") ? (
          <div key={i} style={{ paddingLeft: 16 }}>• {stripNum(l)}</div>
        ) : (
          <p key={i} style={{ margin: 0, lineHeight: 1.5 }}>{l}</p>
        ),
      )}
    </div>
  );
}

export default function AiAssistPage() {
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  // workspace form
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState("circular");
  const [extractionType, setExtractionType] = useState("obligations");
  const [inputText, setInputText] = useState("");

  const [result, setResult] = useState<AiExtraction | null>(null);
  const [history, setHistory] = useState<AiExtraction[]>([]);
  const [summary, setSummary] = useState<AiSummary | null>(null);
  const [copied, setCopied] = useState(false);

  // ------------------------------------------------------------- loaders
  async function loadHistory() {
    try {
      setHistory((await apiCall<Page<AiExtraction>>("GET", "/ai-assist?limit=200")).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<AiSummary>("GET", "/ai-assist-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }
  useEffect(() => {
    loadHistory();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- actions
  async function run() {
    if (!title.trim() || !inputText.trim()) {
      setError("Provide a title and paste some source text to run an extraction.");
      return;
    }
    setError(null);
    setRunning(true);
    setCopied(false);
    try {
      const res = await apiCall<AiExtraction>("POST", "/ai-assist/extract", {
        title,
        source_type: sourceType,
        extraction_type: extractionType,
        input_text: inputText,
      });
      setResult(res);
      await loadHistory();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to run extraction");
    } finally {
      setRunning(false);
    }
  }

  function newExtraction() {
    setResult(null);
    setTitle("");
    setInputText("");
    setSourceType("circular");
    setExtractionType("obligations");
    setCopied(false);
    setError(null);
  }

  function viewItem(item: AiExtraction) {
    setResult(item);
    setTitle(item.title);
    setSourceType(item.source_type);
    setExtractionType(item.extraction_type);
    setInputText(item.input_text);
    setCopied(false);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function remove(item: AiExtraction) {
    if (!window.confirm(`Delete extraction ${item.reference || item.title}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/ai-assist/${item.id}`);
      if (result?.id === item.id) setResult(null);
      await loadHistory();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  function copyOutput() {
    if (!result || typeof navigator === "undefined" || !navigator.clipboard) return;
    navigator.clipboard.writeText(result.output_text || "").then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const isHeuristic = result ? result.model_used === "heuristic" : false;

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>AI Assist — Circular Intelligence</h1>
          <p>
            Paste an SBP circular, policy or incident note and extract obligations,
            summaries, risk suggestions or ISO 27001 control mappings. Works online with an
            AI model or fully offline with the built-in heuristic.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn secondary" onClick={newExtraction} type="button">
            <IconPlus width={16} height={16} /> New extraction
          </button>
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.total.toLocaleString() : "—"}</span></div>
          <span className="l">Extractions run</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.ai_count.toLocaleString() : "—"}</span></div>
          <span className="l">Via AI model</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.heuristic_count.toLocaleString() : "—"}</span></div>
          <span className="l">Via offline heuristic</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.rows.length.toLocaleString() : "—"}</span></div>
          <span className="l">Extraction types used</span>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= WORKSPACE */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Workspace</h3>
          <span className="sub">Paste source text, choose what to extract, then Run</span>
        </div>
        <div className="card-pad">
          <div className="field-row">
            <div style={{ flex: "1 1 260px" }}>
              <label className="label">Title</label>
              <input
                className="input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. SBP PSD Circular 03 of 2026 — digital fraud controls"
              />
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Source type</label>
              <select className="select" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
                {SOURCE_TYPES.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
              </select>
            </div>
            <div style={{ width: 200 }}>
              <label className="label">Extraction</label>
              <select className="select" value={extractionType} onChange={(e) => setExtractionType(e.target.value)}>
                {EXTRACTION_TYPES.map((s) => (<option key={s} value={s}>{EXTRACTION_LABEL[s] || cap(s)}</option>))}
              </select>
            </div>
          </div>
          <div style={{ marginTop: 12 }}>
            <label className="label">Source text</label>
            <textarea
              className="input"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              rows={10}
              placeholder="Paste the full text of the circular / policy / incident note here…"
              style={{ fontFamily: "inherit", lineHeight: 1.5 }}
            />
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn" onClick={run} disabled={running} type="button">
              <IconActivity width={16} height={16} /> {running ? "Running…" : "Run extraction"}
            </button>
            <button
              className="btn secondary sm"
              type="button"
              onClick={() => { setInputText(SAMPLE); if (!title) setTitle("Sample SBP circular"); }}
            >
              Load sample text
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              Extractions never leave your deployment unless an AI model key is configured.
            </span>
          </div>
        </div>
      </div>

      {/* ============================================= RESULT */}
      {result && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-head row-between">
            <div>
              <h3>{result.reference} — {result.title}</h3>
              <span className="sub">
                {cap(result.extraction_type)} · source {cap(result.source_type)}
                {result.created_by ? " · by " + result.created_by : ""}
              </span>
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <Badge tone={TYPE_TONE[result.extraction_type] || "neutral"}>{cap(result.extraction_type)}</Badge>
              <Badge tone={STATUS_TONE[result.status] || "neutral"}>{cap(result.status)}</Badge>
              <button className="btn secondary sm" type="button" onClick={copyOutput}>
                {copied ? "Copied!" : "Copy output"}
              </button>
            </div>
          </div>

          <div className="card-pad">
            {/* provenance banner */}
            <div
              className={`alert ${isHeuristic ? "alert-warn" : "alert-success"}`}
              role="status"
              style={{
                marginBottom: 14,
                padding: "10px 12px",
                borderRadius: 8,
                display: "flex",
                gap: 8,
                alignItems: "center",
                background: isHeuristic ? "rgba(234,179,8,0.12)" : "rgba(34,197,94,0.12)",
                border: `1px solid ${isHeuristic ? "rgba(234,179,8,0.4)" : "rgba(34,197,94,0.4)"}`,
                fontSize: 13,
              }}
            >
              <span aria-hidden>{isHeuristic ? "⚙" : "✓"}</span>
              <span>
                {isHeuristic ? (
                  <>Generated <strong>offline</strong> by the built-in deterministic heuristic — no AI model key is configured.</>
                ) : (
                  <>Generated by the AI model <strong>{result.model_used}</strong>.</>
                )}
              </span>
            </div>

            <OutputView item={result} />

            {(result.extraction_type === "obligations" || result.extraction_type === "risk_suggestions") && (
              <p className="muted" style={{ marginTop: 14, fontSize: 13 }}>
                Tip: copy these extracted obligations into the{" "}
                <a href="/regulatory-change">Regulatory Change</a> module to track implementation
                against the source circular.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ============================================= HISTORY */}
      <div className="card">
        <div className="card-head">
          <h3>History</h3>
          <span className="sub">{history.length} total · click a row to view</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Source</th>
                <th>Extraction</th>
                <th>Model</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} style={{ cursor: "pointer" }} onClick={() => viewItem(h)}>
                  <td className="ref">{h.reference || "—"}</td>
                  <td className="cell-title">{h.title}</td>
                  <td className="muted">{cap(h.source_type)}</td>
                  <td><Badge tone={TYPE_TONE[h.extraction_type] || "neutral"}>{cap(h.extraction_type)}</Badge></td>
                  <td>
                    {h.model_used === "heuristic" ? (
                      <span className="muted">Heuristic</span>
                    ) : (
                      <Badge tone="low">AI · {h.model_used}</Badge>
                    )}
                  </td>
                  <td><Badge tone={STATUS_TONE[h.status] || "neutral"}>{cap(h.status)}</Badge></td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => viewItem(h)}>View</button>
                      <button className="btn secondary sm" onClick={() => remove(h)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconCheck width={24} height={24} /></span>
                      <h3>No extractions yet</h3>
                      <p>Paste an SBP circular or policy above and run your first extraction.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
