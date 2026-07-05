"use client";

import { useEffect, useState } from "react";
import { apiCall, type Page } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconShield } from "@/components/icons";

// ------------------------------------------------------------------ local types
interface WhistleUpdate {
  id: string;
  report_id: string;
  note: string;
  author: string;
  update_date: string | null;
  status_change: string;
  created_at: string;
}
interface WhistleReport {
  id: string;
  reference: string;
  title: string;
  description: string;
  category: string;
  anonymous: boolean;
  reporter_name: string;
  reporter_contact: string;
  channel: string;
  received_date: string | null;
  severity: string;
  status: string;
  assigned_to: string;
  tracking_code: string;
  confidentiality_note: string;
  outcome: string;
  workflow_status: string;
  update_count: number;
  is_open: boolean;
  created_at: string;
  updates: WhistleUpdate[];
}
interface WhistleSummary {
  total: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  open_investigations: number;
  substantiated: number;
  substantiated_rate: number;
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ enum lists
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const CATEGORY = opts([
  "fraud",
  "corruption",
  "harassment",
  "discrimination",
  "safety",
  "financial_misconduct",
  "policy_violation",
  "data_privacy",
  "other",
]);
const CHANNEL = opts(["web_portal", "hotline", "email", "in_person", "letter"]);
const SEVERITY = opts(["low", "medium", "high", "critical"]);
const STATUS = opts(["received", "triage", "investigating", "substantiated", "unsubstantiated", "closed"]);

// ------------------------------------------------------------------ tones
const STATUS_TONE: Record<string, Tone> = {
  received: "high",
  triage: "info",
  investigating: "info",
  substantiated: "critical",
  unsubstantiated: "low",
  closed: "neutral",
};
const SEVERITY_TONE: Record<string, Tone> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

// ------------------------------------------------------------------ form state
type ReportForm = {
  title: string;
  description: string;
  category: string;
  channel: string;
  received_date: string;
  severity: string;
  status: string;
  anonymous: boolean;
  reporter_name: string;
  reporter_contact: string;
  assigned_to: string;
  tracking_code: string;
  confidentiality_note: string;
  outcome: string;
  workflow_status: string;
};
const BLANK_REPORT: ReportForm = {
  title: "",
  description: "",
  category: "other",
  channel: "web_portal",
  received_date: "",
  severity: "medium",
  status: "received",
  anonymous: true,
  reporter_name: "",
  reporter_contact: "",
  assigned_to: "",
  tracking_code: "",
  confidentiality_note: "",
  outcome: "",
  workflow_status: "draft",
};
function fromReport(r: WhistleReport): ReportForm {
  return {
    title: r.title,
    description: r.description || "",
    category: r.category || "other",
    channel: r.channel || "web_portal",
    received_date: r.received_date || "",
    severity: r.severity || "medium",
    status: r.status || "received",
    anonymous: !!r.anonymous,
    reporter_name: r.reporter_name || "",
    reporter_contact: r.reporter_contact || "",
    assigned_to: r.assigned_to || "",
    tracking_code: r.tracking_code || "",
    confidentiality_note: r.confidentiality_note || "",
    outcome: r.outcome || "",
    workflow_status: r.workflow_status || "draft",
  };
}
function reportPayload(f: ReportForm): Record<string, unknown> {
  return {
    title: f.title,
    description: f.description,
    category: f.category,
    channel: f.channel,
    received_date: f.received_date || null,
    severity: f.severity,
    status: f.status,
    anonymous: f.anonymous,
    // When anonymous, never persist reporter identity.
    reporter_name: f.anonymous ? "" : f.reporter_name,
    reporter_contact: f.anonymous ? "" : f.reporter_contact,
    assigned_to: f.assigned_to,
    tracking_code: f.tracking_code,
    confidentiality_note: f.confidentiality_note,
    outcome: f.outcome,
    workflow_status: f.workflow_status,
  };
}

type UpdateDraft = {
  note: string;
  author: string;
  update_date: string;
  status_change: string;
};
const BLANK_UPDATE: UpdateDraft = { note: "", author: "", update_date: "", status_change: "" };

export default function WhistleblowingPage() {
  const [error, setError] = useState<string | null>(null);

  const [reports, setReports] = useState<WhistleReport[]>([]);
  const [summary, setSummary] = useState<WhistleSummary | null>(null);

  // ---- report dialog ----
  const [editingReport, setEditingReport] = useState<WhistleReport | null>(null);
  const [showReportForm, setShowReportForm] = useState(false);
  const [savingReport, setSavingReport] = useState(false);
  const [rf, setRf] = useState<ReportForm>(BLANK_REPORT);
  const setR = <K extends keyof ReportForm>(k: K, v: ReportForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  // ---- expanded case detail + inline case-log ----
  const [openReport, setOpenReport] = useState<WhistleReport | null>(null);
  const [ud, setUd] = useState<UpdateDraft>(BLANK_UPDATE);
  const setU = <K extends keyof UpdateDraft>(k: K, v: UpdateDraft[K]) => setUd((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadReports(keepOpen?: string) {
    try {
      const res = await apiCall<Page<WhistleReport>>("GET", "/whistleblowing?limit=200");
      setReports(res.items);
      if (keepOpen) setOpenReport(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load reports");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await apiCall<WhistleSummary>("GET", "/whistleblowing-summary"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary");
    }
  }
  async function refreshReport(id: string) {
    const r = await apiCall<WhistleReport>("GET", `/whistleblowing/${id}`);
    setOpenReport(r);
    setReports((prev) => prev.map((x) => (x.id === id ? r : x)));
  }

  useEffect(() => {
    loadReports();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- report CRUD
  function openNewReport() {
    setEditingReport(null);
    setRf(BLANK_REPORT);
    setShowReportForm(true);
  }
  function openEditReport(r: WhistleReport) {
    setEditingReport(r);
    setRf(fromReport(r));
    setShowReportForm(true);
  }
  async function saveReport() {
    setError(null);
    setSavingReport(true);
    try {
      const payload = reportPayload(rf);
      if (editingReport) await apiCall<WhistleReport>("PATCH", `/whistleblowing/${editingReport.id}`, payload);
      else await apiCall<WhistleReport>("POST", "/whistleblowing", payload);
      setShowReportForm(false);
      await loadReports(openReport?.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save report");
    } finally {
      setSavingReport(false);
    }
  }
  async function removeReport(r: WhistleReport) {
    if (!window.confirm(`Delete whistleblowing report ${r.reference || r.title}?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/whistleblowing/${r.id}`);
      setShowReportForm(false);
      if (openReport?.id === r.id) setOpenReport(null);
      await loadReports();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleReport(r: WhistleReport) {
    setUd(BLANK_UPDATE);
    setOpenReport(openReport?.id === r.id ? null : r);
  }

  // ------------------------------------------------------------- case-log (inline)
  async function addUpdate() {
    if (!openReport) return;
    setError(null);
    try {
      await apiCall<WhistleReport>("POST", `/whistleblowing/${openReport.id}/updates`, {
        note: ud.note,
        author: ud.author,
        update_date: ud.update_date || null,
        status_change: ud.status_change,
      });
      setUd(BLANK_UPDATE);
      await refreshReport(openReport.id);
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add case-log entry");
    }
  }

  // ------------------------------------------------------------- derived stats
  const anonymousPct =
    reports.length > 0
      ? Math.round((reports.filter((r) => r.anonymous).length / reports.length) * 100)
      : null;
  const investigating = summary ? summary.by_status["investigating"] || 0 : null;

  // ------------------------------------------------------------- form tabs
  const reportTab = (
    <>
      <Field label="Title" required help="For example: Kickbacks alleged in vendor onboarding.">
        <TextInput value={rf.title} onChange={(v) => setR("title", v)} placeholder="Report title" required />
      </Field>
      <Field label="Description" help="What is being disclosed.">
        <TextArea value={rf.description} onChange={(v) => setR("description", v)} rows={4} placeholder="Details of the concern." />
      </Field>
      <div className="field-row">
        <Field label="Category" help="Nature of the disclosure.">
          <Select value={rf.category} onChange={(v) => setR("category", v)} options={CATEGORY} />
        </Field>
        <Field label="Channel" help="How the disclosure reached the bank.">
          <Select value={rf.channel} onChange={(v) => setR("channel", v)} options={CHANNEL} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Severity">
          <Select value={rf.severity} onChange={(v) => setR("severity", v)} options={SEVERITY} />
        </Field>
        <Field label="Received date" help="When the disclosure was received.">
          <TextInput type="date" value={rf.received_date} onChange={(v) => setR("received_date", v)} />
        </Field>
      </div>
    </>
  );
  const reporterTab = (
    <>
      <Field label="Anonymous" help="Anonymous reporters stay masked everywhere; identity is never stored.">
        <Toggle checked={rf.anonymous} onChange={(v) => setR("anonymous", v)} label="Reporter wishes to remain anonymous" />
      </Field>
      {!rf.anonymous && (
        <>
          <Field label="Reporter name">
            <TextInput value={rf.reporter_name} onChange={(v) => setR("reporter_name", v)} placeholder="Full name" />
          </Field>
          <Field label="Reporter contact" help="Email or phone for follow-up.">
            <TextInput value={rf.reporter_contact} onChange={(v) => setR("reporter_contact", v)} placeholder="email@example.com / +92…" />
          </Field>
        </>
      )}
      <Field label="Tracking code" help="Tokenized code for the anonymous two-way channel. Auto-generated on intake if left blank.">
        <TextInput value={rf.tracking_code} onChange={(v) => setR("tracking_code", v)} placeholder="WBX-…" />
      </Field>
      <Field label="Confidentiality note" help="Handling restrictions / who may see this case.">
        <TextArea value={rf.confidentiality_note} onChange={(v) => setR("confidentiality_note", v)} rows={3} placeholder="Restricted to the ethics committee." />
      </Field>
    </>
  );
  const handlingTab = (
    <>
      <div className="field-row">
        <Field label="Status" help="Case lifecycle from intake to closure.">
          <Select value={rf.status} onChange={(v) => setR("status", v)} options={STATUS} />
        </Field>
        <Field label="Assigned to" help="Case handler / investigator.">
          <TextInput value={rf.assigned_to} onChange={(v) => setR("assigned_to", v)} placeholder="Investigator" />
        </Field>
      </div>
      <Field label="Outcome" help="Investigation conclusion and remediation.">
        <TextArea value={rf.outcome} onChange={(v) => setR("outcome", v)} rows={3} placeholder="Findings, disciplinary action, remediation." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this case record.">
        <Select value={rf.workflow_status} onChange={(v) => setR("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Whistleblowing &amp; Case Management</h1>
          <p>Confidential-disclosure intake, triage and investigation case handling. Anonymous reporters stay masked and are reached only through a tokenized tracking code.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button className="btn" onClick={openNewReport}>
            <IconPlus width={16} height={16} /> New report
          </button>
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.open_investigations.toLocaleString() : "—"}</span></div>
          <span className="l">Open cases</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{investigating != null ? investigating.toLocaleString() : "—"}</span></div>
          <span className="l">Investigating</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.substantiated.toLocaleString() : "—"}</span></div>
          <span className="l">Substantiated{summary && summary.substantiated_rate ? ` · ${summary.substantiated_rate}%` : ""}</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{anonymousPct != null ? `${anonymousPct}%` : "—"}</span></div>
          <span className="l">Anonymous reports</span>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Disclosure Register</h3>
          <span className="sub">{reports.length} total · click a row to open the case</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Category</th>
                <th>Channel</th>
                <th>Reporter</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Log</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => toggleReport(r)}>
                  <td className="ref">{r.reference || "—"}</td>
                  <td className="cell-title">{r.title}</td>
                  <td><Badge tone="info">{cap(r.category)}</Badge></td>
                  <td className="muted">{cap(r.channel)}</td>
                  <td>
                    {r.anonymous ? (
                      <span>
                        <Badge tone="neutral">Anonymous</Badge>
                        {r.tracking_code ? <span className="muted" style={{ marginLeft: 6 }}>{r.tracking_code}</span> : null}
                      </span>
                    ) : (
                      <span className="muted">{r.reporter_name || "—"}</span>
                    )}
                  </td>
                  <td><Badge tone={SEVERITY_TONE[r.severity] || "neutral"}>{cap(r.severity)}</Badge></td>
                  <td><Badge tone={STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge></td>
                  <td className="muted">{r.update_count}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => toggleReport(r)}>
                        {openReport?.id === r.id ? "Hide" : "Open"}
                      </button>
                      <button className="btn secondary sm" onClick={() => removeReport(r)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {reports.length === 0 && (
                <tr>
                  <td colSpan={9}>
                    <div className="empty">
                      <span className="ico"><IconShield width={24} height={24} /></span>
                      <h3>No reports</h3>
                      <p>Log a confidential disclosure to open a whistleblowing case. Anonymous reporters are masked and reachable via a tracking code.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {openReport && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head row-between">
              <div>
                <h3>{openReport.reference} — {openReport.title}</h3>
                <span className="sub">
                  {cap(openReport.status)} · {cap(openReport.category)}
                  {openReport.anonymous
                    ? ` · Anonymous${openReport.tracking_code ? " · " + openReport.tracking_code : ""}`
                    : openReport.reporter_name
                      ? " · " + openReport.reporter_name
                      : ""}
                  {openReport.assigned_to ? " · handler " + openReport.assigned_to : ""}
                </span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn secondary sm" onClick={() => openEditReport(openReport)}>Edit</button>
                <button className="btn secondary sm" onClick={() => removeReport(openReport)}>Delete</button>
              </div>
            </div>

            <div className="card-pad">
              {openReport.description && (
                <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>{openReport.description}</p>
              )}
              {openReport.confidentiality_note && (
                <p style={{ margin: "0 0 12px", fontSize: 13 }}>
                  <Badge tone="high">Confidential</Badge>{" "}
                  <span className="muted">{openReport.confidentiality_note}</span>
                </p>
              )}

              <strong>Case log</strong>
              <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                Investigation notes and status changes for this disclosure.
              </p>
              <form
                style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(e) => { e.preventDefault(); addUpdate(); }}
              >
                <div style={{ flex: "1 1 260px" }}>
                  <label className="label">Note</label>
                  <input className="input" value={ud.note} onChange={(e) => setU("note", e.target.value)} placeholder="Case-log entry" required />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Author</label>
                  <input className="input" value={ud.author} onChange={(e) => setU("author", e.target.value)} placeholder="Handler" />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Status change</label>
                  <input className="input" value={ud.status_change} onChange={(e) => setU("status_change", e.target.value)} placeholder="e.g. investigating" />
                </div>
                <div style={{ width: 150 }}>
                  <label className="label">Date</label>
                  <input className="input" type="date" value={ud.update_date} onChange={(e) => setU("update_date", e.target.value)} />
                </div>
                <button className="btn">Add</button>
              </form>

              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Note</th>
                      <th>Status change</th>
                      <th>Author</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...openReport.updates]
                      .sort((a, b) => (b.update_date || b.created_at).localeCompare(a.update_date || a.created_at))
                      .map((u) => (
                        <tr key={u.id}>
                          <td className="muted">{u.update_date || "—"}</td>
                          <td className="cell-title">{u.note || "—"}</td>
                          <td>{u.status_change ? <Badge tone="info">{cap(u.status_change)}</Badge> : <span className="muted">—</span>}</td>
                          <td className="muted">{u.author || "—"}</td>
                        </tr>
                      ))}
                    {openReport.updates.length === 0 && (
                      <tr><td colSpan={4}><span className="muted">No case-log entries yet.</span></td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <RecordPanels model="whistleblowing_report" entityId={openReport.id} />
        </>
      )}

      {/* ============================================= MODAL */}
      {showReportForm && (
        <FormModal
          title={editingReport ? `Edit report — ${editingReport.reference || editingReport.title}` : "New whistleblowing report"}
          wide
          tabs={[
            { id: "report", label: "Report", content: reportTab, required: true },
            { id: "reporter", label: "Reporter", content: reporterTab },
            { id: "handling", label: "Handling", content: handlingTab },
          ]}
          onClose={() => setShowReportForm(false)}
          onSave={saveReport}
          saving={savingReport}
          error={error}
          saveLabel={editingReport ? "Save changes" : "Create report"}
          footerLeft={
            editingReport ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeReport(editingReport)}
                disabled={savingReport}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}
