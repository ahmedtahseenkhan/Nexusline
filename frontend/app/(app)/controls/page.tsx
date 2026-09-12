"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFormat } from "@/lib/format";
import { confirmDeleteWithImpact, WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";
import { deleteEach, deleteErrorText, toastDeleteSummary } from "@/lib/bulkDelete";
import type { LookupRef, UserRef } from "@/lib/masterData";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import WorkflowFields from "@/components/WorkflowFields";
import ArchivedRecords from "@/components/ArchivedRecords";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import RecordIssues from "@/components/RecordIssues";
import RelatedChips from "@/components/RelatedChips";
import SuggestedClauses, { BulkSuggestMappings } from "@/components/SuggestedClauses";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import { Badge, EffectivenessBadge, StatusBadge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import { titleCase } from "@/lib/text";

/* ---------------------------------------------------------------- inline types */
type LinkRef = { id: string; reference?: string; title?: string; name?: string };
type Control = {
  id: string; name: string; reference: string; description: string; objective: string;
  /** Legacy free text ("CISO"); shown only while no owner is picked. */
  owner: string; owner_id: string | null; owner_ref: UserRef | null;
  operator_id: string | null; operator_ref: UserRef | null;
  control_type: string;
  /** Legacy free text, kept in step with the picked classification. */
  classification: string; classification_id: string | null; classification_ref: (LookupRef & { path?: string }) | null;
  documentation_url: string; status: string; effectiveness: string;
  /** Read-only: moved only through WorkflowFields. */
  workflow_status: string; opex: number | null; capex: number | null; resource_utilization: number | null;
  audit_frequency: string; audit_metric: string; audit_success_criteria: string; maintenance_frequency: string;
  next_audit_date: string | null; last_audit_date: string | null; next_maintenance_date: string | null;
  last_maintenance_date: string | null; audit_count: number; last_audit_result: string | null; is_audit_overdue: boolean;
  maintenance_count: number; last_maintenance_result: string | null; is_maintenance_overdue: boolean;
  policies: LinkRef[]; requirements: LinkRef[]; risks: LinkRef[];
  // reverse graph links (read-only, from GET /controls/{id})
  assets?: LinkRef[]; vendors?: LinkRef[];
  incidents?: LinkRef[]; exceptions?: LinkRef[]; projects?: LinkRef[]; audit_findings?: LinkRef[];
};
type ControlAudit = {
  id: string; result: string; conducted_date: string | null; result_description: string;
  /** The tester's name as text (legacy, kept equal to the picked tester's name). */
  auditor: string; tested_by_id?: string | null; tested_by_ref?: UserRef | null;
};
type ControlMaintenance = { id: string; result: string; task: string; conducted_date: string | null };

/* ----------------------------------------------------------------- enum options */
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const CONTROL_TYPE = opts(["design", "production"]);
const STATUS = opts(["planned", "implemented", "operational", "retired"]);
const EFFECTIVENESS = opts(["not_assessed", "ineffective", "partially_effective", "effective"]);
const workflowLabel = (s: string) => WORKFLOW_STATE_LABEL[s as WorkflowStateKey] ?? cap(s);
/** The picked classification ("Parent › Child"), else the legacy text. */
const classificationText = (c: Pick<Control, "classification" | "classification_ref">) =>
  c.classification_ref ? c.classification_ref.path || c.classification_ref.label : c.classification || "";
const personText = (u: UserRef | null | undefined, fallback?: string) => (u ? u.full_name || u.email : fallback || "");
const FREQ = opts(["none", "fortnightly", "monthly", "quarterly", "semiannual", "annual"]);
/** How often a cycle runs, in words. "none" has no cadence, so the line is hidden. */
const FREQ_ADVERB: Record<string, string> = {
  fortnightly: "Every two weeks", monthly: "Monthly", quarterly: "Quarterly",
  semiannual: "Twice a year", annual: "Annually",
};
const cadence = (freq: string) => FREQ_ADVERB[freq] ?? "";
/** Planned and retired controls carry no test clock (the server never schedules one). */
const UNTESTABLE = new Set(["planned", "retired"]);
const NO_CLOCK_NOTE: Record<string, string> = {
  planned: "No test scheduled until the control is implemented",
  retired: "Retired — no further tests scheduled",
};
/** Local calendar date as YYYY-MM-DD (toISOString would give the UTC date). */
const today = () => new Date().toLocaleDateString("en-CA");
const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  operational: "low", implemented: "info", planned: "neutral", retired: "neutral",
};
const RESULT_TONE: Record<string, "low" | "critical" | "neutral"> = { passed: "low", failed: "critical", not_assessed: "neutral" };
function ResultBadge({ value }: { value: string | null }) {
  if (!value || value === "not_assessed") return <span className="muted">—</span>;
  return <Badge tone={RESULT_TONE[value] || "neutral"}>{value}</Badge>;
}
const refToOpt = (x: LinkRef): AsyncOption => ({ value: x.id, label: x.reference || x.title || x.name || x.id });

/* ------------------------------------------------------------------- form state */
type FormState = {
  name: string; reference: string; objective: string; description: string;
  owner_id: string | null; operator_id: string | null; control_type: string;
  classification_id: string | null; documentation_url: string; status: string; effectiveness: string;
  opex: number | ""; capex: number | ""; resource_utilization: number | ""; audit_frequency: string;
  audit_metric: string; audit_success_criteria: string; next_audit_date: string; maintenance_frequency: string;
  next_maintenance_date: string; policy_ids: AsyncOption[]; requirement_ids: AsyncOption[]; risk_ids: AsyncOption[]; asset_ids: AsyncOption[];
};
const BLANK: FormState = {
  name: "", reference: "", objective: "", description: "", owner_id: null, operator_id: null, control_type: "production",
  classification_id: null, documentation_url: "", status: "planned", effectiveness: "not_assessed", opex: "", capex: "",
  resource_utilization: "", audit_frequency: "annual", audit_metric: "", audit_success_criteria: "", next_audit_date: "",
  maintenance_frequency: "quarterly", next_maintenance_date: "", policy_ids: [], requirement_ids: [], risk_ids: [], asset_ids: [],
};
function fromControl(c: Control): FormState {
  return {
    name: c.name, reference: c.reference || "", objective: c.objective || "", description: c.description || "",
    owner_id: c.owner_id ?? null, operator_id: c.operator_id ?? null, control_type: c.control_type,
    classification_id: c.classification_id ?? null,
    documentation_url: c.documentation_url || "", status: c.status, effectiveness: c.effectiveness,
    opex: c.opex ?? "", capex: c.capex ?? "", resource_utilization: c.resource_utilization ?? "",
    audit_frequency: c.audit_frequency, audit_metric: c.audit_metric || "", audit_success_criteria: c.audit_success_criteria || "",
    next_audit_date: c.next_audit_date || "", maintenance_frequency: c.maintenance_frequency, next_maintenance_date: c.next_maintenance_date || "",
    policy_ids: c.policies.map(refToOpt), requirement_ids: c.requirements.map(refToOpt), risk_ids: c.risks.map(refToOpt),
    asset_ids: (c.assets ?? []).map(refToOpt),
  };
}
function toPayload(f: FormState) {
  return {
    name: f.name, reference: f.reference, objective: f.objective, description: f.description,
    owner_id: f.owner_id, operator_id: f.operator_id,
    control_type: f.control_type, classification_id: f.classification_id, documentation_url: f.documentation_url,
    status: f.status, effectiveness: f.effectiveness,
    opex: f.opex === "" ? null : f.opex, capex: f.capex === "" ? null : f.capex,
    resource_utilization: f.resource_utilization === "" ? null : f.resource_utilization,
    audit_frequency: f.audit_frequency, audit_metric: f.audit_metric, audit_success_criteria: f.audit_success_criteria,
    next_audit_date: f.next_audit_date || null, maintenance_frequency: f.maintenance_frequency,
    next_maintenance_date: f.next_maintenance_date || null,
    policy_ids: f.policy_ids.map((o) => o.value), requirement_ids: f.requirement_ids.map((o) => o.value), risk_ids: f.risk_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
  };
}
const linkCount = (c: Control) => c.policies.length + c.requirements.length + c.risks.length;

/* ================================================================ page ===== */
function ControlsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Control | null>(null);
  const [audits, setAudits] = useState<ControlAudit[]>([]);
  const [maints, setMaints] = useState<ControlMaintenance[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const { currency, formatDate, formatMoney } = useFormat();

  const [editing, setEditing] = useState<Control | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // No preselected result: "passed" by default recorded untested controls as passed.
  const [auditResult, setAuditResult] = useState("");
  const [auditDate, setAuditDate] = useState("");
  const [auditNote, setAuditNote] = useState("");
  /** The tester, picked from the user list (tested_by_id); their name is also sent as `auditor`. */
  const [tester, setTester] = useState<UserRef | null>(null);
  const auditReady = !!auditResult && !!auditDate && auditNote.trim().length > 0;
  const [maintResult, setMaintResult] = useState("passed");
  const [maintTask, setMaintTask] = useState("");

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  // Register bulk action "Suggest mappings": the selected control ids under review.
  const [suggestFor, setSuggestFor] = useState<string[] | null>(null);
  const fetchControls = useCallback((qs: string) => apiCall<PagedList<Control>>("GET", `/controls?${qs}`), []);

  const loadDetail = useCallback((id: string) => {
    apiCall<Control>("GET", `/controls/${id}`).then(setDetail).catch(() => setDetail(null));
    Promise.all([
      apiCall<ControlAudit[]>("GET", `/controls/${id}/audits`),
      apiCall<ControlMaintenance[]>("GET", `/controls/${id}/maintenances`),
    ]).then(([a, m]) => { setAudits(a); setMaints(m); }).catch(() => {});
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else { setDetail(null); setAudits([]); setMaints([]); }
  }, [openId, loadDetail]);

  // server typeahead pickers
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((p) => ({ value: p.id, label: p.title, sub: p.reference })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((a) => ({ value: a.id, label: a.name })));

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(c: Control) { setEditing(c); setF(fromControl(c)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Control>("PATCH", `/controls/${editing.id}`, payload);
      else await apiCall<Control>("POST", "/controls", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Control created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save control"); }
    finally { setSaving(false); }
  }
  async function remove(c: Control) {
    if (!(await confirmDeleteWithImpact("control", c.id, c.reference ? `${c.reference} — ${c.name}` : c.name))) return;
    try {
      await apiCall<unknown>("DELETE", `/controls/${c.id}`);
      if (openId === c.id) setOpenId(null);
      reload(); toast(`Archived ${c.reference || c.name}`);
    } catch (e) { toast(deleteErrorText(e, "Failed to delete the control"), "error"); }
  }
  async function recordAudit() {
    if (!detail || !auditReady) return; setError(null);
    try {
      await apiCall<Control>("POST", `/controls/${detail.id}/audits`, {
        result: auditResult, conducted_date: auditDate, result_description: auditNote.trim(),
        tested_by_id: tester?.id ?? null,
        // The legacy text column, kept for display compatibility with older readers.
        auditor: tester ? tester.full_name || tester.email : "",
      });
      setAuditResult(""); setAuditDate(""); setAuditNote(""); setTester(null);
      loadDetail(detail.id); reload(); toast("Test recorded");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to record the test"); }
  }
  async function recordMaintenance() {
    if (!detail) return; setError(null);
    try {
      await apiCall<Control>("POST", `/controls/${detail.id}/maintenances`, { result: maintResult, task: maintTask });
      setMaintTask(""); loadDetail(detail.id); reload(); toast("Maintenance recorded");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to record maintenance"); }
  }


  /* Inline relation chips linking to each record's own page. */
  const labelOf = (x: { id: string; label?: string; name?: string; title?: string; reference?: string }) =>
    x.label || x.name || x.title || x.reference || x.id;
  const linkChips = (items: { id: string; label?: string; name?: string; title?: string; reference?: string }[] | undefined, href: string) =>
    items && items.length ? (
      <div className="chips" onClick={(e) => e.stopPropagation()}>
        {items.map((x) => <Link key={x.id} className="chip" href={`${href}?id=${x.id}`}>{labelOf(x)}</Link>)}
      </div>
    ) : <span className="muted">—</span>;
  const names = (items: { id: string; label?: string; name?: string; title?: string; reference?: string }[] | undefined) =>
    (items ?? []).map(labelOf).join(", ");

  const columns: Column<Control>[] = [
    { key: "reference", header: "Ref", sortable: true, locked: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, locked: true, render: (c) => <span className="cell-title">{c.name}</span> },
    { key: "control_type", header: "Type", render: (c) => <Badge tone="neutral" plain>{cap(c.control_type)}</Badge>, text: (c) => cap(c.control_type) },
    { key: "status", header: "Status", sortable: true, render: (c) => <StatusBadge value={c.status} tone={STATUS_TONE[c.status] === "low" ? "info" : "neutral"} />, text: (c) => cap(c.status) },
    { key: "effectiveness", header: "Effectiveness", sortable: true, render: (c) => <EffectivenessBadge value={c.effectiveness} />, text: (c) => cap(c.effectiveness) },
    { key: "owner", header: "Owner", render: (c) => <span className="muted"><UserName user={c.owner_ref} fallback={c.owner} /></span>, text: (c) => personText(c.owner_ref, c.owner) },
    { key: "operator", header: "Operator", hidden: true, render: (c) => <span className="muted"><UserName user={c.operator_ref} /></span>, text: (c) => personText(c.operator_ref) },
    { key: "classification", header: "Classification", hidden: true, render: (c) => <span className="muted">{classificationText(c) || "—"}</span>, text: (c) => classificationText(c) },
    { key: "risks", header: "Risks mitigated", render: (c) => linkChips(c.risks, "/risks"), text: (c) => names(c.risks) },
    { key: "policies", header: "Policies", hidden: true, render: (c) => linkChips(c.policies, "/policies"), text: (c) => names(c.policies) },
    { key: "requirements", header: "Requirements", hidden: true, render: (c) => linkChips(c.requirements, "/compliance"), text: (c) => names(c.requirements) },
    { key: "assets", header: "Protected assets", hidden: true, render: (c) => linkChips(c.assets, "/information-assets"), text: (c) => names(c.assets) },
    { key: "audit_frequency", header: "Test cycle", hidden: true, render: (c) => <span className="muted">{cap(c.audit_frequency)}</span>, text: (c) => cap(c.audit_frequency) },
    { key: "last_audit_date", header: "Last tested", hidden: true, sortable: true, render: (c) => <span className="muted">{formatDate(c.last_audit_date)}</span>, text: (c) => (c.last_audit_date ? formatDate(c.last_audit_date) : "") },
    { key: "last_audit_result", header: "Last result", hidden: true, render: (c) => <span className="muted">{c.last_audit_result ? cap(c.last_audit_result) : "—"}</span>, text: (c) => c.last_audit_result ? cap(c.last_audit_result) : "" },
    { key: "next_audit_date", header: "Next test", sortable: true, render: (c) => (c.is_audit_overdue ? <Badge tone="high">Overdue</Badge> : UNTESTABLE.has(c.status) ? <span className="muted" title={NO_CLOCK_NOTE[c.status]}>Not scheduled</span> : <span className="muted">{formatDate(c.next_audit_date)}</span>), text: (c) => (UNTESTABLE.has(c.status) ? "Not scheduled" : c.next_audit_date ? formatDate(c.next_audit_date) : "") },
    { key: "audit_count", header: "Tests run", hidden: true, align: "center", render: (c) => <span className="muted">{c.audit_count || "—"}</span> },
    { key: "next_maintenance_date", header: "Next maintenance", hidden: true, render: (c) => (c.is_maintenance_overdue ? <Badge tone="high">Overdue</Badge> : UNTESTABLE.has(c.status) ? <span className="muted">Not scheduled</span> : <span className="muted">{formatDate(c.next_maintenance_date)}</span>), text: (c) => (UNTESTABLE.has(c.status) ? "Not scheduled" : c.next_maintenance_date ? formatDate(c.next_maintenance_date) : "") },
    { key: "opex", header: "Opex / yr", hidden: true, align: "right", render: (c) => <span className="muted">{formatMoney(c.opex)}</span>, text: (c) => c.opex != null ? formatMoney(c.opex) : "" },
    { key: "capex", header: "Capex", hidden: true, align: "right", render: (c) => <span className="muted">{formatMoney(c.capex)}</span>, text: (c) => c.capex != null ? formatMoney(c.capex) : "" },
    { key: "workflow_status", header: "Approval", hidden: true, render: (c) => <span className="muted">{workflowLabel(c.workflow_status)}</span>, text: (c) => workflowLabel(c.workflow_status) },
    { key: "actions", header: "", render: (c) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(c)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(c)}>Delete</button></div> },
  ];

  /** Delete every selected control after one confirmation, then drop the selection. */
  async function removeMany(rowsToDelete: { id: string }[], clear: () => void) {
    const ok = await confirmDialog({
      title: `Delete ${rowsToDelete.length} control${rowsToDelete.length === 1 ? "" : "s"}?`,
      message: "They are archived, not erased: links from other records are kept, they can be restored from Archived, and the activity trail records who removed them.",
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    const res = await deleteEach(rowsToDelete, (r) => apiCall("DELETE", `/controls/${r.id}`));
    clear();
    reload();
    toastDeleteSummary(res, "control");
  }

  /* ------------------------------ form tabs (unchanged) ------------------------------ */
  const generalTab = (
    <>
      <div className="field-row">
        <Field label="Name" required help="For example: Multi-factor authentication, Encryption at rest."><TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Multi-factor authentication" required /></Field>
        <Field label="Reference" help="Framework code, e.g. A.8.5 or AC-2."><TextInput value={f.reference} onChange={(v) => set("reference", v)} placeholder="A.8.5" /></Field>
      </div>
      <Field label="Objective" help="What the control is meant to achieve."><TextArea value={f.objective} onChange={(v) => set("objective", v)} rows={2} placeholder="Prevent unauthorised access to production systems." /></Field>
      <Field label="Description"><RichText value={f.description} onChange={(v) => set("description", v)} placeholder="Describe how the control is implemented and operated…" /></Field>
      <div className="field-row">
        <Field label="Owner / GRC Contact" help="Accountable for the control's design and effectiveness.">
          <UserPicker
            value={f.owner_id}
            onChange={(id) => set("owner_id", id)}
            selected={editing?.owner_ref}
            legacyText={editing?.owner_id ? null : editing?.owner}
            placeholder="Search people…"
          />
        </Field>
        <Field label="Operator" help="Runs the control day to day, where that is someone other than the owner.">
          <UserPicker
            value={f.operator_id}
            onChange={(id) => set("operator_id", id)}
            selected={editing?.operator_ref}
            placeholder="Search people…"
          />
        </Field>
      </div>
      <Field label="Classification" help="From the organisation's control classification list, e.g. Identity & Access.">
        <LookupSelect
          lookupKey="control_classification"
          value={f.classification_id}
          onChange={(id) => set("classification_id", id)}
          legacyText={editing?.classification_id ? null : editing?.classification}
          placeholder="Choose a classification…"
          allowCreate
        />
      </Field>
      <div className="field-row">
        <Field label="Control Type" help="Design artefact vs. in-production control."><Select value={f.control_type} onChange={(v) => set("control_type", v)} options={CONTROL_TYPE} /></Field>
        <Field label="Status"><Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} /></Field>
      </div>
      <div className="field-row">
        <Field label="Effectiveness" help="Approval is separate: submit the control for review from its detail view."><Select value={f.effectiveness} onChange={(v) => set("effectiveness", v)} options={EFFECTIVENESS} /></Field>
      </div>
      <Field label="Documentation URL" help="Link to the runbook, design doc or evidence location."><TextInput value={f.documentation_url} onChange={(v) => set("documentation_url", v)} placeholder="https://docs.example.com/controls/mfa" /></Field>
    </>
  );
  const costTab = (
    <>
      <div className="field-row">
        <Field label={`OpEx (${currency} per year)`} help="Operational cost to run this control annually."><NumberInput value={f.opex} onChange={(v) => set("opex", v)} min={0} step={100} placeholder="0" /></Field>
        <Field label={`CapEx (${currency})`} help="One-off capital cost to implement."><NumberInput value={f.capex} onChange={(v) => set("capex", v)} min={0} step={100} placeholder="0" /></Field>
      </div>
      <Field label="Resource Utilization (% FTE)" help="Share of a full-time person needed to operate the control."><NumberInput value={f.resource_utilization} onChange={(v) => set("resource_utilization", v)} min={0} max={100} step={5} placeholder="0" /></Field>
    </>
  );
  const auditTab = (
    <>
      <div className="card-pad" style={{ padding: "0 0 8px" }}><strong>Audit cycle</strong><p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>How the control&apos;s effectiveness is tested and how often.</p></div>
      <div className="field-row">
        <Field label="Audit Frequency"><Select value={f.audit_frequency} onChange={(v) => set("audit_frequency", v)} options={FREQ} /></Field>
        {UNTESTABLE.has(f.status)
          ? <Field label="Next Audit Date" help="The first test is scheduled from the frequency once the control is implemented or operational."><span className="muted" style={{ fontSize: 13 }}>{NO_CLOCK_NOTE[f.status]}</span></Field>
          : <Field label="Next Audit Date" help="Leave blank to derive from the frequency."><TextInput type="date" value={f.next_audit_date} onChange={(v) => set("next_audit_date", v)} /></Field>}
      </div>
      <Field label="Audit Metric" help="What you measure to know the control works."><TextArea value={f.audit_metric} onChange={(v) => set("audit_metric", v)} rows={2} placeholder="% of privileged accounts with MFA enforced." /></Field>
      <Field label="Audit Success Criteria" help="The threshold for a passing audit."><TextArea value={f.audit_success_criteria} onChange={(v) => set("audit_success_criteria", v)} rows={2} placeholder="100% of privileged accounts enforce MFA." /></Field>
      <div className="card-pad" style={{ padding: "16px 0 8px" }}><strong>Maintenance cycle</strong><p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>Routine upkeep that keeps the control operating.</p></div>
      <div className="field-row">
        <Field label="Maintenance Frequency"><Select value={f.maintenance_frequency} onChange={(v) => set("maintenance_frequency", v)} options={FREQ} /></Field>
        {UNTESTABLE.has(f.status)
          ? <Field label="Next Maintenance Date" help="Scheduled from the frequency once the control is implemented or operational."><span className="muted" style={{ fontSize: 13 }}>{f.status === "planned" ? "No maintenance scheduled until the control is implemented" : "Retired — no further maintenance scheduled"}</span></Field>
          : <Field label="Next Maintenance Date" help="Leave blank to derive from the frequency."><TextInput type="date" value={f.next_maintenance_date} onChange={(v) => set("next_maintenance_date", v)} /></Field>}
      </div>
    </>
  );
  const linksTab = (
    <>
      <Field label="Requirements" help="Framework requirements this control satisfies (map once, comply many)."><AsyncMultiSelect search={searchRequirements} value={f.requirement_ids} onChange={(v) => set("requirement_ids", v)} /></Field>
      <Field label="Policies" help="Policies that mandate or are enforced by this control."><AsyncMultiSelect search={searchPolicies} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} /></Field>
      <Field label="Risks" help="Risks this control mitigates."><AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} /></Field>
      <Field label="Protected assets" help="Assets this control protects."><AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} /></Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Control Catalog</h1>
          <p>Reusable controls with cost, effectiveness, framework mappings and recurring audit &amp; maintenance test cycles.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="controls" label="Controls" onDone={reload} />
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add control</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Control>
        toolbarRight={<ArchivedRecords entityType="control" noun="controls" onRestored={reload} refreshKey={refreshKey} />}
        tableKey="controls"
        statusModel="control"
        bulkActions={(rows, clear) => (
          <>
            <button className="btn secondary sm" onClick={() => { setSuggestFor(rows.map((r) => r.id)); clear(); }}>Suggest mappings</button>
            <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
          </>
        )}
        columns={columns}
        fetcher={fetchControls}
        rowKey={(c) => c.id}
        onRowClick={(c) => setOpenId(c.id)}
        activeKey={openId}
        searchPlaceholder="Search controls by name or reference…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No controls yet. Create your first control to build the catalog."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        aside={detail ? <RecordPanels model="control" entityId={detail.id} /> : null}
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? detail.reference || detail.name : "…"}
        subtitle={detail ? `${cap(detail.control_type)} · ${personText(detail.owner_ref, detail.owner) || "no owner"}` : ""}
        width={720}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              <StatusBadge value={detail.status} tone={STATUS_TONE[detail.status] === "low" ? "info" : "neutral"} />
              <EffectivenessBadge value={detail.effectiveness} />
              {linkCount(detail) > 0 && <Badge tone="neutral" plain>{linkCount(detail)} links</Badge>}
            </div>

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16, fontSize: 13.5 }}>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Owner</div><div style={{ marginTop: 3 }}><UserName user={detail.owner_ref} fallback={detail.owner} /></div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Operator</div><div style={{ marginTop: 3 }}><UserName user={detail.operator_ref} /></div></div>
              <div><div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Classification</div><div style={{ marginTop: 3 }}>{classificationText(detail) || <span className="muted">—</span>}</div></div>
              {(detail.opex != null || detail.capex != null) && (
                <div><div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Cost</div><div style={{ marginTop: 3 }}>{formatMoney(detail.opex)} / yr · {formatMoney(detail.capex)} capex</div></div>
              )}
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Approval</h3></div>
              <div className="card-pad">
                <WorkflowFields entityType="control" entityId={detail.id} onChanged={() => { loadDetail(detail.id); reload(); }} />
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Audits</h3>{cadence(detail.audit_frequency) && <span className="sub">{cadence(detail.audit_frequency)}</span>}</div>
              <div className="card-pad">
                <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>
                  {UNTESTABLE.has(detail.status)
                    ? NO_CLOCK_NOTE[detail.status]
                    : detail.is_audit_overdue
                      ? <>Next test was due <b>{formatDate(detail.next_audit_date)}</b> — overdue</>
                      : detail.next_audit_date ? <>Next test due <b>{formatDate(detail.next_audit_date)}</b></> : "No next test scheduled"}
                </div>
                <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); recordAudit(); }}>
                  <div style={{ width: 150 }}>
                    <label className="label" htmlFor="audit-result">Result</label>
                    <select id="audit-result" className="select" value={auditResult} onChange={(e) => setAuditResult(e.target.value)} required>
                      <option value="" disabled>Choose a result</option>
                      <option value="passed">Passed</option>
                      <option value="failed">Failed</option>
                    </select>
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label" htmlFor="audit-date">Test date</label>
                    <input id="audit-date" className="input" type="date" value={auditDate} max={today()} onChange={(e) => setAuditDate(e.target.value)} required />
                  </div>
                  <div style={{ flex: "1 1 180px" }}>
                    <label className="label" htmlFor="audit-conclusion">Conclusion</label>
                    <input id="audit-conclusion" className="input" value={auditNote} onChange={(e) => setAuditNote(e.target.value)} placeholder="What was tested and what you found" required />
                  </div>
                  <div style={{ width: 200 }}>
                    <label className="label">Tester</label>
                    <UserPicker
                      value={tester?.id ?? null}
                      selected={tester}
                      onChange={(_id, ref) => setTester(ref ?? null)}
                      placeholder="Who performed the test…"
                    />
                  </div>
                  <button className="btn" disabled={!auditReady} title={auditReady ? undefined : "Choose a result, the test date and the conclusion"}>Record</button>
                </form>
                {audits.length ? audits.map((a) => (
                  <div key={a.id} className="activity-item">
                    <div style={{ flex: 1 }}><div style={{ fontSize: 13 }}>{a.result_description || "Audit"}</div><div className="when">{formatDate(a.conducted_date)} · <UserName user={a.tested_by_ref} fallback={a.auditor} /></div></div>
                    <ResultBadge value={a.result} />
                  </div>
                )) : <span className="muted">No audits recorded yet.</span>}
              </div>
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Maintenance history</h3>{cadence(detail.maintenance_frequency) && <span className="sub">{cadence(detail.maintenance_frequency)}</span>}</div>
              <div className="card-pad">
                <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); recordMaintenance(); }}>
                  <div style={{ width: 120 }}><label className="label">Result</label><select className="select" value={maintResult} onChange={(e) => setMaintResult(e.target.value)}><option value="passed">passed</option><option value="failed">failed</option></select></div>
                  <div style={{ flex: "1 1 170px" }}><label className="label">Task</label><input className="input" value={maintTask} onChange={(e) => setMaintTask(e.target.value)} placeholder="e.g. Rotate keys" /></div>
                  <button className="btn">Record</button>
                </form>
                {maints.length ? maints.map((m) => (
                  <div key={m.id} className="activity-item">
                    <div style={{ flex: 1 }}><div style={{ fontSize: 13 }}>{m.task || "Maintenance"}</div><div className="when">{formatDate(m.conducted_date)}</div></div>
                    <ResultBadge value={m.result} />
                  </div>
                )) : <span className="muted">No maintenance recorded yet.</span>}
              </div>
            </div>

            <strong style={{ fontSize: 13 }}>Related records</strong>
            <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 14 }}>
              <RelatedChips label="Policies" items={detail.policies} href="/policies" />
              <RelatedChips label="Compliance requirements" items={detail.requirements} href="/compliance" />
              <RelatedChips label="Risks" items={detail.risks} href="/risks" />
              <RelatedChips label="Protected assets" items={detail.assets} href="/information-assets" />
              <RelatedChips label="Third parties" items={detail.vendors} href="/vendors" />
              <RelatedChips label="Incidents" items={detail.incidents} href="/incidents" />
              <RelatedChips label="Exceptions" items={detail.exceptions} href="/exceptions" />
              <RelatedChips label="Projects" items={detail.projects} href="/projects" />
              <RelatedChips label="Audit findings" items={detail.audit_findings} href="/internal-audit" />
            </div>

            <SuggestedClauses controlId={detail.id} onAccepted={() => { loadDetail(detail.id); reload(); }} />

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              <RecordIssues entityId={detail.id} entityRef={detail.reference} sourceType="self_identified" />
            </div>

          </>
        )}
      </RecordDrawer>

      {suggestFor && (
        <BulkSuggestMappings controlIds={suggestFor} onClose={() => setSuggestFor(null)} onDone={reload} />
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit control — ${editing.reference || editing.name}` : "Add item (Controls)"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "cost", label: "Cost & Resourcing", content: costTab },
            { id: "audit", label: "Audit & Maintenance", content: auditTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create control"}
        />
      )}
    </>
  );
}

export default function ControlsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ControlsInner />
    </Suspense>
  );
}
