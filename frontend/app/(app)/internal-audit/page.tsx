"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import {
  api,
  apiCall,
  type Page as PagedList,
  type AuditableUnit,
  type AuditEngagement,
  type AuditFinding,
} from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconAlert } from "@/components/icons";

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ enum lists
const INHERENT_RISK = opts(["low", "medium", "high", "critical"]);
const AUDIT_FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const UNIT_WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const ENG_STATUS = opts(["planned", "fieldwork", "reporting", "closed", "cancelled"]);
const RATING = opts(["low", "medium", "high", "critical"]);
const PROC_RESULT = ["pending", "passed", "failed", "not_applicable"];
const FINDING_STATUS = ["open", "in_progress", "closed", "risk_accepted"];

// ------------------------------------------------------------------ tones
const RISK_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "high", critical: "critical" };
const ENG_STATUS_TONE: Record<string, Tone> = {
  planned: "neutral",
  fieldwork: "info",
  reporting: "medium",
  closed: "low",
  cancelled: "neutral",
};
const FINDING_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  in_progress: "info",
  closed: "low",
  risk_accepted: "medium",
};
const PROC_RESULT_TONE: Record<string, Tone> = {
  pending: "neutral",
  passed: "low",
  failed: "critical",
  not_applicable: "neutral",
};

function RatingBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={RISK_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

// ------------------------------------------------------------------ form state
type UnitForm = {
  name: string;
  category: string;
  owner: string;
  description: string;
  inherent_risk: string;
  audit_frequency: string;
  last_audited_date: string;
  next_audit_due: string;
  workflow_status: string;
};
const BLANK_UNIT: UnitForm = {
  name: "",
  category: "",
  owner: "",
  description: "",
  inherent_risk: "medium",
  audit_frequency: "annual",
  last_audited_date: "",
  next_audit_due: "",
  workflow_status: "draft",
};
function fromUnit(u: AuditableUnit): UnitForm {
  return {
    name: u.name,
    category: u.category || "",
    owner: u.owner || "",
    description: u.description || "",
    inherent_risk: u.inherent_risk || "medium",
    audit_frequency: u.audit_frequency || "annual",
    last_audited_date: u.last_audited_date || "",
    next_audit_due: u.next_audit_due || "",
    workflow_status: u.workflow_status || "draft",
  };
}
function unitPayload(f: UnitForm): Record<string, unknown> {
  return {
    name: f.name,
    category: f.category,
    owner: f.owner,
    description: f.description,
    inherent_risk: f.inherent_risk,
    audit_frequency: f.audit_frequency,
    last_audited_date: f.last_audited_date || null,
    next_audit_due: f.next_audit_due || null,
    workflow_status: f.workflow_status,
  };
}

type EngForm = {
  title: string;
  auditable_unit_id: string;
  lead_auditor: string;
  audit_team: string;
  status: string;
  scope: string;
  objectives: string;
  period_start: string;
  period_end: string;
  planned_start: string;
  planned_end: string;
  actual_start: string;
  actual_end: string;
  rating: string;
  conclusion: string;
};
const BLANK_ENG: EngForm = {
  title: "",
  auditable_unit_id: "",
  lead_auditor: "",
  audit_team: "",
  status: "planned",
  scope: "",
  objectives: "",
  period_start: "",
  period_end: "",
  planned_start: "",
  planned_end: "",
  actual_start: "",
  actual_end: "",
  rating: "",
  conclusion: "",
};
function fromEng(e: AuditEngagement): EngForm {
  return {
    title: e.title,
    auditable_unit_id: e.auditable_unit_id || "",
    lead_auditor: e.lead_auditor || "",
    audit_team: e.audit_team || "",
    status: e.status,
    scope: e.scope || "",
    objectives: e.objectives || "",
    period_start: e.period_start || "",
    period_end: e.period_end || "",
    planned_start: e.planned_start || "",
    planned_end: e.planned_end || "",
    actual_start: e.actual_start || "",
    actual_end: e.actual_end || "",
    rating: e.rating || "",
    conclusion: e.conclusion || "",
  };
}
function engPayload(f: EngForm): Record<string, unknown> {
  return {
    title: f.title,
    auditable_unit_id: f.auditable_unit_id || null,
    lead_auditor: f.lead_auditor,
    audit_team: f.audit_team,
    status: f.status,
    scope: f.scope,
    objectives: f.objectives,
    period_start: f.period_start || null,
    period_end: f.period_end || null,
    planned_start: f.planned_start || null,
    planned_end: f.planned_end || null,
    actual_start: f.actual_start || null,
    actual_end: f.actual_end || null,
    rating: f.rating || null,
    conclusion: f.conclusion,
  };
}

type ProcDraft = {
  title: string;
  description: string;
  result: string;
  workpaper_ref: string;
  performed_by: string;
  performed_date: string;
};
const BLANK_PROC: ProcDraft = {
  title: "",
  description: "",
  result: "pending",
  workpaper_ref: "",
  performed_by: "",
  performed_date: "",
};

type FindingDraft = {
  title: string;
  description: string;
  rating: string;
  risk_implication: string;
  recommendation: string;
  management_response: string;
  action_owner: string;
  due_date: string;
  status: string;
};
const BLANK_FINDING: FindingDraft = {
  title: "",
  description: "",
  rating: "medium",
  risk_implication: "",
  recommendation: "",
  management_response: "",
  action_owner: "",
  due_date: "",
  status: "open",
};

type TabId = "universe" | "engagements" | "findings";
const TABS: { id: TabId; label: string }[] = [
  { id: "universe", label: "Audit Universe" },
  { id: "engagements", label: "Engagements" },
  { id: "findings", label: "Findings follow-up" },
];
type FindingFilter = "all" | "open" | "overdue";
type FindingSummary = { total: number; open: number; overdue: number };

// ================================================================ page =====
function InternalAuditInner() {
  const [tab, setTab] = useState<TabId>("universe");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  // unit options for the engagement form dropdown (loaded once; refreshed on change)
  const [unitList, setUnitList] = useState<AuditableUnit[]>([]);
  const loadUnitOptions = useCallback(() => {
    apiCall<PagedList<AuditableUnit>>("GET", "/audit-universe?limit=200")
      .then((r) => setUnitList(r.items))
      .catch(() => {});
  }, []);
  useEffect(() => { loadUnitOptions(); }, [loadUnitOptions, refreshKey]);

  // ---- auditable-unit dialog ----
  const [editingUnit, setEditingUnit] = useState<AuditableUnit | null>(null);
  const [showUnitForm, setShowUnitForm] = useState(false);
  const [savingUnit, setSavingUnit] = useState(false);
  const [uf, setUf] = useState<UnitForm>(BLANK_UNIT);
  const setU = <K extends keyof UnitForm>(k: K, v: UnitForm[K]) => setUf((p) => ({ ...p, [k]: v }));

  // ---- engagement dialog ----
  const [editingEng, setEditingEng] = useState<AuditEngagement | null>(null);
  const [showEngForm, setShowEngForm] = useState(false);
  const [savingEng, setSavingEng] = useState(false);
  const [ef, setEf] = useState<EngForm>(BLANK_ENG);
  const setE = <K extends keyof EngForm>(k: K, v: EngForm[K]) => setEf((p) => ({ ...p, [k]: v }));

  // ---- engagement detail drawer (URL-driven) ----
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<AuditEngagement | null>(null);
  const loadDetail = useCallback((id: string) => {
    apiCall<AuditEngagement>("GET", `/audit-engagements/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  const [pd, setPd] = useState<ProcDraft>(BLANK_PROC);
  const setP = <K extends keyof ProcDraft>(k: K, v: ProcDraft[K]) => setPd((p) => ({ ...p, [k]: v }));
  const [fd, setFd] = useState<FindingDraft>(BLANK_FINDING);
  const setFD = <K extends keyof FindingDraft>(k: K, v: FindingDraft[K]) => setFd((p) => ({ ...p, [k]: v }));

  // ---- findings follow-up ----
  const [findingFilter, setFindingFilter] = useState<FindingFilter>("all");
  const [summary, setSummary] = useState<FindingSummary>({ total: 0, open: 0, overdue: 0 });
  const loadSummary = useCallback(() => {
    apiCall<FindingSummary>("GET", "/audit-findings/summary").then(setSummary).catch(() => {});
  }, []);
  useEffect(() => { loadSummary(); }, [loadSummary, refreshKey]);

  // ------------------------------------------------------------- fetchers
  const fetchUnits = useCallback((qs: string) => apiCall<PagedList<AuditableUnit>>("GET", `/audit-universe?${qs}`), []);
  const fetchEngagements = useCallback((qs: string) => apiCall<PagedList<AuditEngagement>>("GET", `/audit-engagements?${qs}`), []);
  const fetchFindings = useCallback((qs: string) => apiCall<PagedList<AuditFinding>>("GET", `/audit-findings?${qs}`), []);

  // ------------------------------------------------------------- unit CRUD
  function openNewUnit() { setEditingUnit(null); setUf(BLANK_UNIT); setError(null); setShowUnitForm(true); }
  function openEditUnit(u: AuditableUnit) { setEditingUnit(u); setUf(fromUnit(u)); setError(null); setShowUnitForm(true); }
  async function saveUnit() {
    setError(null); setSavingUnit(true);
    try {
      const payload = unitPayload(uf);
      if (editingUnit) await api.updateAuditUnit(editingUnit.id, payload);
      else await api.createAuditUnit(payload);
      setShowUnitForm(false); reload(); toast(editingUnit ? "Changes saved" : "Auditable unit created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save auditable unit");
    } finally {
      setSavingUnit(false);
    }
  }
  async function removeUnit(u: AuditableUnit) {
    if (!(await confirmDialog({ title: `Delete auditable unit ${u.reference || u.name}?`, danger: true }))) return;
    setError(null);
    try {
      await api.deleteAuditUnit(u.id);
      setShowUnitForm(false); reload(); toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- engagement CRUD
  function openNewEng() { setEditingEng(null); setEf(BLANK_ENG); setError(null); setShowEngForm(true); }
  function openEditEng(e: AuditEngagement) { setEditingEng(e); setEf(fromEng(e)); setError(null); setShowEngForm(true); }
  async function saveEng() {
    setError(null); setSavingEng(true);
    try {
      const payload = engPayload(ef);
      if (editingEng) await api.updateAuditEngagement(editingEng.id, payload);
      else await api.createAuditEngagement(payload);
      setShowEngForm(false); reload();
      if (openId) loadDetail(openId);
      toast(editingEng ? "Changes saved" : "Engagement created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save engagement");
    } finally {
      setSavingEng(false);
    }
  }
  async function removeEng(e: AuditEngagement) {
    if (!(await confirmDialog({ title: `Delete engagement ${e.reference || e.title}?`, danger: true }))) return;
    setError(null);
    try {
      await api.deleteAuditEngagement(e.id);
      setShowEngForm(false);
      if (openId === e.id) setOpenId(null);
      reload(); toast("Deleted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    }
  }
  function openDrawer(e: AuditEngagement) {
    setPd(BLANK_PROC);
    setFd(BLANK_FINDING);
    setOpenId(e.id);
  }

  // ------------------------------------------------------------- procedure CRUD
  async function addProc() {
    if (!detail) return;
    setError(null);
    try {
      await api.addAuditProcedure(detail.id, {
        title: pd.title,
        description: pd.description,
        result: pd.result,
        workpaper_ref: pd.workpaper_ref,
        performed_by: pd.performed_by,
        performed_date: pd.performed_date || null,
      });
      setPd(BLANK_PROC); loadDetail(detail.id); reload(); toast("Working paper added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add working paper");
    }
  }
  async function changeProc(pid: string, result: string) {
    if (!detail) return;
    setError(null);
    try {
      await api.updateAuditProcedure(pid, { result });
      loadDetail(detail.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update working paper");
    }
  }
  async function removeProc(pid: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Remove this working paper?", danger: true }))) return;
    setError(null);
    try {
      await api.deleteAuditProcedure(pid);
      loadDetail(detail.id); toast("Removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove working paper");
    }
  }

  // ------------------------------------------------------------- finding CRUD
  async function addFinding() {
    if (!detail) return;
    setError(null);
    try {
      await api.addAuditFinding(detail.id, {
        title: fd.title,
        description: fd.description,
        rating: fd.rating,
        risk_implication: fd.risk_implication,
        recommendation: fd.recommendation,
        management_response: fd.management_response,
        action_owner: fd.action_owner,
        due_date: fd.due_date || null,
        status: fd.status,
      });
      setFd(BLANK_FINDING); loadDetail(detail.id); reload(); toast("Finding raised");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add finding");
    }
  }
  // Used by both the drawer and the follow-up tracker; reloads whichever is affected.
  async function changeFindingStatus(fid: string, status: string) {
    setError(null);
    try {
      await api.updateAuditFinding(fid, { status });
      if (openId) loadDetail(openId);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update finding");
    }
  }
  async function removeFinding(fid: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Remove this finding?", danger: true }))) return;
    setError(null);
    try {
      await api.deleteAuditFinding(fid);
      loadDetail(detail.id); reload(); toast("Removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove finding");
    }
  }

  const unitOpts: Option[] = unitList.map((u) => ({ value: u.id, label: u.name, sub: u.reference }));

  // ------------------------------------------------------------- columns
  const unitColumns: Column<AuditableUnit>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (u) => <span className="ref">{u.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, render: (u) => <span className="cell-title">{u.name}</span> },
    { key: "category", header: "Category", sortable: true, render: (u) => <span className="muted">{u.category || "—"}</span> },
    { key: "owner", header: "Owner", sortable: true, render: (u) => <span className="muted">{u.owner || "—"}</span> },
    { key: "inherent_risk", header: "Inherent risk", sortable: true, render: (u) => <RatingBadge value={u.inherent_risk} /> },
    { key: "audit_frequency", header: "Frequency", render: (u) => <span className="muted">{cap(u.audit_frequency || "none")}</span> },
    { key: "next_audit_due", header: "Next audit due", sortable: true, render: (u) => (u.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{u.next_audit_due || "—"}</span>) },
    { key: "actions", header: "", render: (u) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditUnit(u)}>Edit</button> <button className="btn secondary sm" onClick={() => removeUnit(u)}>Delete</button></div> },
  ];

  const engColumns: Column<AuditEngagement>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (e) => <span className="ref">{e.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (e) => <span className="cell-title">{e.title}</span> },
    { key: "status", header: "Status", sortable: true, render: (e) => <Badge tone={ENG_STATUS_TONE[e.status] || "neutral"}>{cap(e.status)}</Badge> },
    { key: "lead_auditor", header: "Lead auditor", sortable: true, render: (e) => <span className="muted">{e.lead_auditor || "—"}</span> },
    { key: "planned_end", header: "Planned end", sortable: true, render: (e) => (e.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{e.planned_end || "—"}</span>) },
    { key: "findings", header: "Findings", render: (e) => <span className="muted">{e.open_finding_count}/{e.finding_count} open</span> },
    { key: "actions", header: "", render: (e) => <div onClick={(ev) => ev.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditEng(e)}>Edit</button> <button className="btn secondary sm" onClick={() => removeEng(e)}>Delete</button></div> },
  ];

  const findingColumns: Column<AuditFinding>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (f) => <span className="ref">{f.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (f) => <span className="cell-title">{f.title}</span> },
    { key: "rating", header: "Rating", sortable: true, render: (f) => <RatingBadge value={f.rating} /> },
    { key: "action_owner", header: "Action owner", sortable: true, render: (f) => <span className="muted">{f.action_owner || "—"}</span> },
    { key: "due_date", header: "Due", sortable: true, render: (f) => (f.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{f.due_date || "—"}</span>) },
    {
      key: "status", header: "Status", sortable: true, render: (f) => (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }} onClick={(e) => e.stopPropagation()}>
          <Badge tone={FINDING_STATUS_TONE[f.status] || "neutral"}>{cap(f.status)}</Badge>
          <select className="select" style={{ width: 140 }} value={f.status} onChange={(ev) => changeFindingStatus(f.id, ev.target.value)}>
            {FINDING_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
          </select>
        </div>
      ),
    },
  ];

  const findingFilters: Record<string, boolean | undefined> =
    findingFilter === "open" ? { open: true } : findingFilter === "overdue" ? { overdue: true } : {};

  // ------------------------------------------------------------- unit form
  const unitTab = (
    <>
      <Field label="Name" required help="For example: Payroll process, Production data centre, Vendor onboarding.">
        <TextInput value={uf.name} onChange={(v) => setU("name", v)} placeholder="Payroll process" required />
      </Field>
      <div className="field-row">
        <Field label="Category" help="Grouping in the universe, e.g. Finance, IT, Operations.">
          <TextInput value={uf.category} onChange={(v) => setU("category", v)} placeholder="Finance" />
        </Field>
        <Field label="Owner">
          <TextInput value={uf.owner} onChange={(v) => setU("owner", v)} placeholder="Process owner" />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={uf.description} onChange={(v) => setU("description", v)} rows={3} placeholder="What this auditable unit covers." />
      </Field>
      <div className="field-row">
        <Field label="Inherent Risk" help="Risk of the unit before audit assurance.">
          <Select value={uf.inherent_risk} onChange={(v) => setU("inherent_risk", v)} options={INHERENT_RISK} />
        </Field>
        <Field label="Audit Frequency" help="How often the unit should be audited.">
          <Select value={uf.audit_frequency} onChange={(v) => setU("audit_frequency", v)} options={AUDIT_FREQ} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Last Audited">
          <TextInput type="date" value={uf.last_audited_date} onChange={(v) => setU("last_audited_date", v)} />
        </Field>
        <Field label="Next Audit Due" help="Leave blank to derive from the frequency.">
          <TextInput type="date" value={uf.next_audit_due} onChange={(v) => setU("next_audit_due", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this universe record.">
        <Select value={uf.workflow_status} onChange={(v) => setU("workflow_status", v)} options={UNIT_WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- engagement form
  const engGeneral = (
    <>
      <Field label="Title" required help="For example: FY26 Payroll controls review.">
        <TextInput value={ef.title} onChange={(v) => setE("title", v)} placeholder="FY26 Payroll controls review" required />
      </Field>
      <div className="field-row">
        <Field label="Auditable Unit" help="The universe entry this engagement covers.">
          <Select value={ef.auditable_unit_id} onChange={(v) => setE("auditable_unit_id", v)} options={unitOpts} placeholder="—" />
        </Field>
        <Field label="Status">
          <Select value={ef.status} onChange={(v) => setE("status", v)} options={ENG_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Lead Auditor">
          <TextInput value={ef.lead_auditor} onChange={(v) => setE("lead_auditor", v)} placeholder="Name" />
        </Field>
        <Field label="Audit Team" help="Comma-separated team members.">
          <TextInput value={ef.audit_team} onChange={(v) => setE("audit_team", v)} placeholder="Jane, Omar" />
        </Field>
      </div>
      <Field label="Scope">
        <TextArea value={ef.scope} onChange={(v) => setE("scope", v)} rows={3} placeholder="What is in and out of scope." />
      </Field>
      <Field label="Objectives">
        <TextArea value={ef.objectives} onChange={(v) => setE("objectives", v)} rows={3} placeholder="What this engagement seeks to assure." />
      </Field>
    </>
  );

  const engPlanning = (
    <>
      <div className="field-row">
        <Field label="Period Start" help="Start of the period under review.">
          <TextInput type="date" value={ef.period_start} onChange={(v) => setE("period_start", v)} />
        </Field>
        <Field label="Period End">
          <TextInput type="date" value={ef.period_end} onChange={(v) => setE("period_end", v)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Planned Start">
          <TextInput type="date" value={ef.planned_start} onChange={(v) => setE("planned_start", v)} />
        </Field>
        <Field label="Planned End" help="Target completion — drives the overdue flag.">
          <TextInput type="date" value={ef.planned_end} onChange={(v) => setE("planned_end", v)} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Actual Start">
          <TextInput type="date" value={ef.actual_start} onChange={(v) => setE("actual_start", v)} />
        </Field>
        <Field label="Actual End">
          <TextInput type="date" value={ef.actual_end} onChange={(v) => setE("actual_end", v)} />
        </Field>
      </div>
    </>
  );

  const engConclusion = (
    <>
      <Field label="Overall Opinion" help="Overall assurance rating for the engagement.">
        <Select value={ef.rating} onChange={(v) => setE("rating", v)} options={RATING} placeholder="— No opinion —" />
      </Field>
      <Field label="Conclusion">
        <RichText value={ef.conclusion} onChange={(v) => setE("conclusion", v)} placeholder="Summarise the engagement conclusion…" />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Internal Audit</h1>
          <p>Risk-based audit universe, engagements with working papers, and remediation tracking across findings.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {tab === "universe" && (
            <button className="btn" onClick={openNewUnit}><IconPlus width={16} height={16} /> New auditable unit</button>
          )}
          {tab === "engagements" && (
            <button className="btn" onClick={openNewEng}><IconPlus width={16} height={16} /> New engagement</button>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button key={t.id} className={`btn${tab === t.id ? "" : " secondary"}`} onClick={() => setTab(t.id)} type="button">
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= AUDIT UNIVERSE */}
      {tab === "universe" && (
        <DataTable<AuditableUnit>
          columns={unitColumns}
          fetcher={fetchUnits}
          rowKey={(u) => u.id}
          onRowClick={(u) => openEditUnit(u)}
          searchPlaceholder="Search auditable units by name, ref, category or owner…"
          defaultSort={{ by: "name", dir: "asc" }}
          emptyMessage="No auditable units. Build your risk-based audit universe to plan engagements."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= ENGAGEMENTS */}
      {tab === "engagements" && (
        <DataTable<AuditEngagement>
          columns={engColumns}
          fetcher={fetchEngagements}
          rowKey={(e) => e.id}
          onRowClick={(e) => openDrawer(e)}
          activeKey={openId}
          searchPlaceholder="Search engagements by title, ref or lead auditor…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No engagements. Plan your first audit engagement to record working papers and findings."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= FINDINGS FOLLOW-UP */}
      {tab === "findings" && (
        <>
          <div className="grid stat-grid">
            <div className="card stat warn">
              <div className="stat-top">
                <span className="n">{summary.open}</span>
                <span className="ico"><IconAlert /></span>
              </div>
              <span className="l">Open findings</span>
            </div>
            <div className="card stat danger">
              <div className="stat-top">
                <span className="n">{summary.overdue}</span>
                <span className="ico"><IconAlert /></span>
              </div>
              <span className="l">Overdue findings</span>
            </div>
          </div>

          <DataTable<AuditFinding>
            columns={findingColumns}
            fetcher={fetchFindings}
            rowKey={(f) => f.id}
            filters={findingFilters}
            searchPlaceholder="Search findings by title, ref or action owner…"
            defaultSort={{ by: "due_date", dir: "asc" }}
            emptyMessage="No findings. Findings raised on engagements show up here for remediation tracking."
            refreshKey={refreshKey}
            toolbarRight={
              <div style={{ display: "flex", gap: 6 }}>
                {(["all", "open", "overdue"] as FindingFilter[]).map((k) => (
                  <button key={k} className={`btn sm${findingFilter === k ? "" : " secondary"}`} onClick={() => setFindingFilter(k)} type="button">
                    {cap(k)}
                  </button>
                ))}
              </div>
            }
          />
        </>
      )}

      {/* ============================================= ENGAGEMENT DRAWER */}
      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? `${cap(detail.status)} · lead ${detail.lead_auditor || "unassigned"}${detail.rating ? " · opinion " + cap(detail.rating) : ""}` : ""}
        width={920}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => api.pdfAuditEngagement(detail.id, detail.reference).catch(() => {})}>Report PDF</button>
            <button className="btn secondary sm" onClick={() => openEditEng(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeEng(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            {/* --- Working papers (procedures) --- */}
            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Working papers</h3><span className="sub">Audit procedures performed and their result.</span></div>
              <div className="card-pad">
                <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(ev) => { ev.preventDefault(); addProc(); }}>
                  <div style={{ flex: "1 1 180px" }}><label className="label">Title</label><input className="input" value={pd.title} onChange={(ev) => setP("title", ev.target.value)} placeholder="Procedure title" required /></div>
                  <div style={{ flex: "1 1 200px" }}><label className="label">Description</label><input className="input" value={pd.description} onChange={(ev) => setP("description", ev.target.value)} placeholder="What was tested" /></div>
                  <div style={{ width: 140 }}><label className="label">Result</label><select className="select" value={pd.result} onChange={(ev) => setP("result", ev.target.value)}>{PROC_RESULT.map((r) => (<option key={r} value={r}>{cap(r)}</option>))}</select></div>
                  <div style={{ width: 130 }}><label className="label">Workpaper ref</label><input className="input" value={pd.workpaper_ref} onChange={(ev) => setP("workpaper_ref", ev.target.value)} placeholder="WP-01" /></div>
                  <div style={{ width: 130 }}><label className="label">Performed by</label><input className="input" value={pd.performed_by} onChange={(ev) => setP("performed_by", ev.target.value)} placeholder="Name" /></div>
                  <div style={{ width: 150 }}><label className="label">Performed</label><input className="input" type="date" value={pd.performed_date} onChange={(ev) => setP("performed_date", ev.target.value)} /></div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Title</th><th>Result</th><th>Workpaper</th><th>Performed by</th><th></th></tr></thead>
                    <tbody>
                      {detail.procedures.map((p) => (
                        <tr key={p.id}>
                          <td className="cell-title">{p.title}</td>
                          <td>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <Badge tone={PROC_RESULT_TONE[p.result] || "neutral"}>{cap(p.result)}</Badge>
                              <select className="select" style={{ width: 130 }} value={p.result} onChange={(ev) => changeProc(p.id, ev.target.value)}>
                                {PROC_RESULT.map((r) => (<option key={r} value={r}>{cap(r)}</option>))}
                              </select>
                            </div>
                          </td>
                          <td className="muted">{p.workpaper_ref || "—"}</td>
                          <td className="muted">{p.performed_by || "—"}</td>
                          <td><button className="btn secondary sm" onClick={() => removeProc(p.id)}>Remove</button></td>
                        </tr>
                      ))}
                      {detail.procedures.length === 0 && (<tr><td colSpan={5}><span className="muted">No working papers recorded yet.</span></td></tr>)}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            {/* --- Findings --- */}
            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Findings</h3><span className="sub">Issues raised by this engagement and their remediation status.</span></div>
              <div className="card-pad">
                <form style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(ev) => { ev.preventDefault(); addFinding(); }}>
                  <div style={{ flex: "1 1 180px" }}><label className="label">Title</label><input className="input" value={fd.title} onChange={(ev) => setFD("title", ev.target.value)} placeholder="Finding title" required /></div>
                  <div style={{ width: 130 }}><label className="label">Rating</label><select className="select" value={fd.rating} onChange={(ev) => setFD("rating", ev.target.value)}>{RATING.map((r) => (<option key={r.value} value={r.value}>{r.label}</option>))}</select></div>
                  <div style={{ flex: "1 1 200px" }}><label className="label">Description</label><input className="input" value={fd.description} onChange={(ev) => setFD("description", ev.target.value)} placeholder="What went wrong" /></div>
                  <div style={{ flex: "1 1 180px" }}><label className="label">Risk implication</label><input className="input" value={fd.risk_implication} onChange={(ev) => setFD("risk_implication", ev.target.value)} placeholder="Exposure if unresolved" /></div>
                  <div style={{ flex: "1 1 180px" }}><label className="label">Recommendation</label><input className="input" value={fd.recommendation} onChange={(ev) => setFD("recommendation", ev.target.value)} placeholder="Proposed remediation" /></div>
                  <div style={{ flex: "1 1 180px" }}><label className="label">Management response</label><input className="input" value={fd.management_response} onChange={(ev) => setFD("management_response", ev.target.value)} placeholder="Agreed action" /></div>
                  <div style={{ width: 140 }}><label className="label">Action owner</label><input className="input" value={fd.action_owner} onChange={(ev) => setFD("action_owner", ev.target.value)} placeholder="Owner" /></div>
                  <div style={{ width: 150 }}><label className="label">Due date</label><input className="input" type="date" value={fd.due_date} onChange={(ev) => setFD("due_date", ev.target.value)} /></div>
                  <div style={{ width: 140 }}><label className="label">Status</label><select className="select" value={fd.status} onChange={(ev) => setFD("status", ev.target.value)}>{FINDING_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}</select></div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead><tr><th>Ref</th><th>Title</th><th>Rating</th><th>Action owner</th><th>Due</th><th>Status</th><th></th></tr></thead>
                    <tbody>
                      {detail.findings.map((fi) => (
                        <tr key={fi.id}>
                          <td className="ref">{fi.reference || "—"}</td>
                          <td className="cell-title">{fi.title}</td>
                          <td><RatingBadge value={fi.rating} /></td>
                          <td className="muted">{fi.action_owner || "—"}</td>
                          <td>{fi.is_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{fi.due_date || "—"}</span>}</td>
                          <td>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <Badge tone={FINDING_STATUS_TONE[fi.status] || "neutral"}>{cap(fi.status)}</Badge>
                              <select className="select" style={{ width: 140 }} value={fi.status} onChange={(ev) => changeFindingStatus(fi.id, ev.target.value)}>
                                {FINDING_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                              </select>
                            </div>
                          </td>
                          <td><button className="btn secondary sm" onClick={() => removeFinding(fi.id)}>Remove</button></td>
                        </tr>
                      ))}
                      {detail.findings.length === 0 && (<tr><td colSpan={7}><span className="muted">No findings raised yet.</span></td></tr>)}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <RecordPanels model="audit_engagement" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {/* ============================================= MODALS */}
      {showUnitForm && (
        <FormModal
          title={editingUnit ? `Edit auditable unit — ${editingUnit.reference || editingUnit.name}` : "New auditable unit"}
          tabs={[{ id: "general", label: "General", content: unitTab, required: true }]}
          onClose={() => setShowUnitForm(false)}
          onSave={saveUnit}
          saving={savingUnit}
          error={error}
          saveLabel={editingUnit ? "Save changes" : "Create unit"}
          footerLeft={
            editingUnit ? (
              <button className="btn secondary sm" type="button" onClick={() => removeUnit(editingUnit)} disabled={savingUnit} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showEngForm && (
        <FormModal
          title={editingEng ? `Edit engagement — ${editingEng.reference || editingEng.title}` : "New engagement"}
          wide
          tabs={[
            { id: "general", label: "General", content: engGeneral, required: true },
            { id: "planning", label: "Planning", content: engPlanning },
            { id: "conclusion", label: "Conclusion", content: engConclusion },
          ]}
          onClose={() => setShowEngForm(false)}
          onSave={saveEng}
          saving={savingEng}
          error={error}
          saveLabel={editingEng ? "Save changes" : "Create engagement"}
          footerLeft={
            editingEng ? (
              <button className="btn secondary sm" type="button" onClick={() => removeEng(editingEng)} disabled={savingEng} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

export default function InternalAuditPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <InternalAuditInner />
    </Suspense>
  );
}
