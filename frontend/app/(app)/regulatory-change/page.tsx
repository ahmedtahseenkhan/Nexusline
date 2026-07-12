"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncSelect, { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// ------------------------------------------------------------------ enum lists
const APPLICABILITY = ["pending", "applicable", "not_applicable", "under_review"];
const REG_STATUS = ["identified", "under_assessment", "in_implementation", "implemented", "closed"];
const OBL_TYPE = ["mandatory", "recommended", "conditional"];
const OBL_STATUS = ["open", "in_progress", "met", "not_met", "not_applicable"];
const RETURN_STATUS = ["upcoming", "submitted", "overdue"];
const FREQUENCY = ["none", "monthly", "quarterly", "semiannual", "annual"];
const PRIORITY = ["low", "medium", "high", "critical"];
const WORKFLOW = ["draft", "in_review", "approved", "retired"];

const APPLICABILITY_OPTS = opts(APPLICABILITY);
const REG_STATUS_OPTS = opts(REG_STATUS);
const OBL_TYPE_OPTS = opts(OBL_TYPE);
const OBL_STATUS_OPTS = opts(OBL_STATUS);
const RETURN_STATUS_OPTS = opts(RETURN_STATUS);
const FREQUENCY_OPTS = opts(FREQUENCY);
const PRIORITY_OPTS = opts(PRIORITY);
const WORKFLOW_OPTS = opts(WORKFLOW);

// ------------------------------------------------------------------ tones
const REG_STATUS_TONE: Record<string, Tone> = {
  identified: "neutral",
  under_assessment: "info",
  in_implementation: "medium",
  implemented: "low",
  closed: "neutral",
};
const APPLICABILITY_TONE: Record<string, Tone> = {
  pending: "neutral",
  applicable: "high",
  not_applicable: "neutral",
  under_review: "info",
};
const OBL_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  in_progress: "info",
  met: "low",
  not_met: "critical",
  not_applicable: "neutral",
};
const OBL_TYPE_TONE: Record<string, Tone> = {
  mandatory: "high",
  recommended: "info",
  conditional: "medium",
};
const RETURN_STATUS_TONE: Record<string, Tone> = {
  upcoming: "info",
  submitted: "low",
  overdue: "critical",
};
const PRIORITY_TONE: Record<string, Tone> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};
const WORKFLOW_TONE: Record<string, Tone> = {
  approved: "low",
  in_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

// ------------------------------------------------------------------ types
type Obligation = {
  id: string;
  regulatory_change_id: string | null;
  reference: string;
  title: string;
  description: string;
  obligation_type: string;
  owner: string;
  business_unit: string;
  mapped_policies: string;
  mapped_controls: string;
  status: string;
  due_date: string | null;
  created_at: string;
};

type RegChange = {
  id: string;
  reference: string;
  title: string;
  regulator: string;
  circular_ref: string;
  source_url: string;
  issued_date: string | null;
  effective_date: string | null;
  summary: string;
  applicability: string;
  impact_assessment: string;
  status: string;
  owner: string;
  priority: string;
  department: string;
  workflow_status: string;
  obligation_count: number;
  days_to_effective: number | null;
  is_overdue: boolean;
  created_at: string;
  obligations: Obligation[];
};

type RegReturn = {
  id: string;
  reference: string;
  name: string;
  regulator: string;
  description: string;
  frequency: string;
  owner: string;
  department: string;
  submission_channel: string;
  next_due_date: string | null;
  last_submitted_date: string | null;
  status: string;
  workflow_status: string;
  is_overdue: boolean;
  days_to_due: number | null;
  created_at: string;
};

type Summary = {
  changes_by_status: Record<string, number>;
  total_changes: number;
  changes_open: number;
  changes_in_implementation: number;
  changes_overdue: number;
  obligations_total: number;
  obligations_open: number;
  obligations_met: number;
  returns_total: number;
  returns_due_30: number;
  returns_due_60: number;
  returns_due_90: number;
  returns_overdue: number;
};

// ------------------------------------------------------------------ form state
type ChangeForm = {
  title: string;
  regulator: string;
  circular_ref: string;
  source_url: string;
  issued_date: string;
  effective_date: string;
  summary: string;
  applicability: string;
  impact_assessment: string;
  status: string;
  owner: string;
  priority: string;
  department: string;
  workflow_status: string;
};
const BLANK_CHANGE: ChangeForm = {
  title: "",
  regulator: "SBP",
  circular_ref: "",
  source_url: "",
  issued_date: "",
  effective_date: "",
  summary: "",
  applicability: "pending",
  impact_assessment: "",
  status: "identified",
  owner: "",
  priority: "medium",
  department: "",
  workflow_status: "draft",
};
function fromChange(c: RegChange): ChangeForm {
  return {
    title: c.title,
    regulator: c.regulator || "SBP",
    circular_ref: c.circular_ref || "",
    source_url: c.source_url || "",
    issued_date: c.issued_date || "",
    effective_date: c.effective_date || "",
    summary: c.summary || "",
    applicability: c.applicability || "pending",
    impact_assessment: c.impact_assessment || "",
    status: c.status || "identified",
    owner: c.owner || "",
    priority: c.priority || "medium",
    department: c.department || "",
    workflow_status: c.workflow_status || "draft",
  };
}
function changePayload(f: ChangeForm): Record<string, unknown> {
  return {
    title: f.title,
    regulator: f.regulator,
    circular_ref: f.circular_ref,
    source_url: f.source_url,
    issued_date: f.issued_date || null,
    effective_date: f.effective_date || null,
    summary: f.summary,
    applicability: f.applicability,
    impact_assessment: f.impact_assessment,
    status: f.status,
    owner: f.owner,
    priority: f.priority,
    department: f.department,
    workflow_status: f.workflow_status,
  };
}

type OblForm = {
  title: string;
  regulatory_change_id: string;
  description: string;
  obligation_type: string;
  owner: string;
  business_unit: string;
  mapped_policies: string;
  mapped_controls: string;
  status: string;
  due_date: string;
};
const BLANK_OBL: OblForm = {
  title: "",
  regulatory_change_id: "",
  description: "",
  obligation_type: "mandatory",
  owner: "",
  business_unit: "",
  mapped_policies: "",
  mapped_controls: "",
  status: "open",
  due_date: "",
};
function fromObl(o: Obligation): OblForm {
  return {
    title: o.title,
    regulatory_change_id: o.regulatory_change_id || "",
    description: o.description || "",
    obligation_type: o.obligation_type || "mandatory",
    owner: o.owner || "",
    business_unit: o.business_unit || "",
    mapped_policies: o.mapped_policies || "",
    mapped_controls: o.mapped_controls || "",
    status: o.status || "open",
    due_date: o.due_date || "",
  };
}
function oblPayload(f: OblForm): Record<string, unknown> {
  return {
    title: f.title,
    regulatory_change_id: f.regulatory_change_id || null,
    description: f.description,
    obligation_type: f.obligation_type,
    owner: f.owner,
    business_unit: f.business_unit,
    mapped_policies: f.mapped_policies,
    mapped_controls: f.mapped_controls,
    status: f.status,
    due_date: f.due_date || null,
  };
}

// inline nested obligation draft (change drawer)
type OblDraft = { title: string; obligation_type: string; owner: string; status: string; due_date: string };
const BLANK_OBL_DRAFT: OblDraft = { title: "", obligation_type: "mandatory", owner: "", status: "open", due_date: "" };

type ReturnForm = {
  name: string;
  regulator: string;
  description: string;
  frequency: string;
  owner: string;
  department: string;
  submission_channel: string;
  next_due_date: string;
  last_submitted_date: string;
  status: string;
  workflow_status: string;
};
const BLANK_RETURN: ReturnForm = {
  name: "",
  regulator: "SBP",
  description: "",
  frequency: "quarterly",
  owner: "",
  department: "",
  submission_channel: "",
  next_due_date: "",
  last_submitted_date: "",
  status: "upcoming",
  workflow_status: "draft",
};
function fromReturn(r: RegReturn): ReturnForm {
  return {
    name: r.name,
    regulator: r.regulator || "SBP",
    description: r.description || "",
    frequency: r.frequency || "quarterly",
    owner: r.owner || "",
    department: r.department || "",
    submission_channel: r.submission_channel || "",
    next_due_date: r.next_due_date || "",
    last_submitted_date: r.last_submitted_date || "",
    status: r.status || "upcoming",
    workflow_status: r.workflow_status || "draft",
  };
}
function returnPayload(f: ReturnForm): Record<string, unknown> {
  return {
    name: f.name,
    regulator: f.regulator,
    description: f.description,
    frequency: f.frequency,
    owner: f.owner,
    department: f.department,
    submission_channel: f.submission_channel,
    next_due_date: f.next_due_date || null,
    last_submitted_date: f.last_submitted_date || null,
    status: f.status,
    workflow_status: f.workflow_status,
  };
}

type SectionId = "changes" | "obligations" | "returns";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "changes", label: "Regulatory Changes" },
  { id: "obligations", label: "Obligations" },
  { id: "returns", label: "Returns Calendar" },
];

function StatusBadge({ value, tone }: { value: string | null; tone: Record<string, Tone> }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={tone[value] || "neutral"}>{cap(value)}</Badge>;
}

// ================================================================ page ===
function RegulatoryChangeInner() {
  const [section, setSection] = useState<SectionId>("changes");
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // ---- change filters (server-side) ----
  const [statusF, setStatusF] = useState("");
  const [applicF, setApplicF] = useState("");

  // ---- change drawer (URL-driven) ----
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<RegChange | null>(null);

  // ---- change dialog ----
  const [editingChange, setEditingChange] = useState<RegChange | null>(null);
  const [showChangeForm, setShowChangeForm] = useState(false);
  const [savingChange, setSavingChange] = useState(false);
  const [cf, setCf] = useState<ChangeForm>(BLANK_CHANGE);
  const setC = <K extends keyof ChangeForm>(k: K, v: ChangeForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ---- nested obligation draft (drawer) ----
  const [od, setOd] = useState<OblDraft>(BLANK_OBL_DRAFT);
  const setOD = <K extends keyof OblDraft>(k: K, v: OblDraft[K]) => setOd((p) => ({ ...p, [k]: v }));

  // ---- obligation dialog ----
  const [editingObl, setEditingObl] = useState<Obligation | null>(null);
  const [showOblForm, setShowOblForm] = useState(false);
  const [savingObl, setSavingObl] = useState(false);
  const [of, setOf] = useState<OblForm>(BLANK_OBL);
  const setO = <K extends keyof OblForm>(k: K, v: OblForm[K]) => setOf((p) => ({ ...p, [k]: v }));
  const [oblChange, setOblChange] = useState<AsyncOption | null>(null);

  // ---- return dialog ----
  const [editingReturn, setEditingReturn] = useState<RegReturn | null>(null);
  const [showReturnForm, setShowReturnForm] = useState(false);
  const [savingReturn, setSavingReturn] = useState(false);
  const [rf, setRf] = useState<ReturnForm>(BLANK_RETURN);
  const setR = <K extends keyof ReturnForm>(k: K, v: ReturnForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  const loadSummary = useCallback(() => {
    apiCall<Summary>("GET", "/regulatory-change-summary").then(setSummary).catch(() => {});
  }, []);
  // Bump tables + refresh the summary stat cards after any mutation.
  const reload = useCallback(() => {
    setRefreshKey((k) => k + 1);
    loadSummary();
  }, [loadSummary]);

  const loadDetail = useCallback((id: string) => {
    apiCall<RegChange>("GET", `/regulatory-change/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  // ------------------------------------------------------------- fetchers (server-driven tables)
  const fetchChanges = useCallback((qs: string) => apiCall<PagedList<RegChange>>("GET", `/regulatory-change?${qs}`), []);
  const fetchObligations = useCallback((qs: string) => apiCall<PagedList<Obligation>>("GET", `/obligations?${qs}`), []);
  const fetchReturns = useCallback((qs: string) => apiCall<PagedList<RegReturn>>("GET", `/regulatory-returns?${qs}`), []);

  // server typeahead for the "linked regulatory change" picker (any record, not a capped array)
  const searchChanges = (q: string) =>
    apiCall<PagedList<RegChange>>("GET", `/regulatory-change?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
      r.items.map((c) => ({ value: c.id, label: c.title, sub: c.reference || undefined })),
    );

  // ------------------------------------------------------------- change CRUD
  function openNewChange() {
    setEditingChange(null);
    setCf(BLANK_CHANGE);
    setError(null);
    setShowChangeForm(true);
  }
  function openEditChange(c: RegChange) {
    setEditingChange(c);
    setCf(fromChange(c));
    setError(null);
    setShowChangeForm(true);
  }
  async function saveChange() {
    setError(null);
    setSavingChange(true);
    try {
      const payload = changePayload(cf);
      if (editingChange) await apiCall<RegChange>("PATCH", `/regulatory-change/${editingChange.id}`, payload);
      else await apiCall<RegChange>("POST", "/regulatory-change", payload);
      setShowChangeForm(false);
      reload();
      if (openId) loadDetail(openId);
      toast(editingChange ? "Changes saved" : "Regulatory change created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save regulatory change");
    } finally {
      setSavingChange(false);
    }
  }
  async function removeChange(c: RegChange) {
    if (!(await confirmDialog({ title: `Delete regulatory change ${c.reference || c.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/regulatory-change/${c.id}`);
      setShowChangeForm(false);
      if (openId === c.id) setOpenId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- nested obligations (drawer)
  async function addNestedObligation() {
    if (!detail) return;
    setError(null);
    try {
      await apiCall<RegChange>("POST", `/regulatory-change/${detail.id}/obligations`, {
        title: od.title,
        obligation_type: od.obligation_type,
        owner: od.owner,
        status: od.status,
        due_date: od.due_date || null,
      });
      setOd(BLANK_OBL_DRAFT);
      loadDetail(detail.id);
      reload();
      toast("Obligation added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add obligation");
    }
  }
  async function removeNestedObligation(oid: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Remove this obligation?", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/obligations/${oid}`);
      loadDetail(detail.id);
      reload();
      toast("Removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove obligation");
    }
  }

  // ------------------------------------------------------------- obligation CRUD (flat register)
  function openNewObl() {
    setEditingObl(null);
    setOf(BLANK_OBL);
    setOblChange(null);
    setError(null);
    setShowOblForm(true);
  }
  function openEditObl(o: Obligation) {
    setEditingObl(o);
    setOf(fromObl(o));
    setError(null);
    if (o.regulatory_change_id) {
      if (detail && detail.id === o.regulatory_change_id) {
        setOblChange({ value: detail.id, label: detail.title, sub: detail.reference || undefined });
      } else {
        setOblChange(null);
        apiCall<RegChange>("GET", `/regulatory-change/${o.regulatory_change_id}`)
          .then((c) => setOblChange({ value: c.id, label: c.title, sub: c.reference || undefined }))
          .catch(() => setOblChange(null));
      }
    } else {
      setOblChange(null);
    }
    setShowOblForm(true);
  }
  async function saveObl() {
    setError(null);
    setSavingObl(true);
    try {
      const payload = oblPayload(of);
      if (editingObl) await apiCall<Obligation>("PATCH", `/obligations/${editingObl.id}`, payload);
      else await apiCall<Obligation>("POST", "/obligations", payload);
      setShowOblForm(false);
      reload();
      if (openId) loadDetail(openId);
      toast(editingObl ? "Changes saved" : "Obligation created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save obligation");
    } finally {
      setSavingObl(false);
    }
  }
  async function removeObl(o: Obligation) {
    if (!(await confirmDialog({ title: `Delete obligation ${o.reference || o.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/obligations/${o.id}`);
      setShowOblForm(false);
      reload();
      if (openId) loadDetail(openId);
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- return CRUD
  function openNewReturn() {
    setEditingReturn(null);
    setRf(BLANK_RETURN);
    setError(null);
    setShowReturnForm(true);
  }
  function openEditReturn(r: RegReturn) {
    setEditingReturn(r);
    setRf(fromReturn(r));
    setError(null);
    setShowReturnForm(true);
  }
  async function saveReturn() {
    setError(null);
    setSavingReturn(true);
    try {
      const payload = returnPayload(rf);
      if (editingReturn) await apiCall<RegReturn>("PATCH", `/regulatory-returns/${editingReturn.id}`, payload);
      else await apiCall<RegReturn>("POST", "/regulatory-returns", payload);
      setShowReturnForm(false);
      reload();
      toast(editingReturn ? "Changes saved" : "Regulatory return created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save regulatory return");
    } finally {
      setSavingReturn(false);
    }
  }
  async function removeReturn(r: RegReturn) {
    if (!(await confirmDialog({ title: `Delete regulatory return ${r.reference || r.name}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/regulatory-returns/${r.id}`);
      setShowReturnForm(false);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- columns
  const changeColumns: Column<RegChange>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (c) => <span className="cell-title">{c.title}</span> },
    { key: "circular_ref", header: "Circular", sortable: true, render: (c) => <span className="muted">{c.circular_ref || "—"}</span> },
    { key: "applicability", header: "Applicability", sortable: true, render: (c) => <StatusBadge value={c.applicability} tone={APPLICABILITY_TONE} /> },
    { key: "status", header: "Status", sortable: true, render: (c) => <StatusBadge value={c.status} tone={REG_STATUS_TONE} /> },
    { key: "priority", header: "Priority", sortable: true, render: (c) => <StatusBadge value={c.priority} tone={PRIORITY_TONE} /> },
    { key: "obligations", header: "Obligations", align: "center", render: (c) => <span className="muted">{c.obligation_count || "—"}</span> },
    {
      key: "effective_date",
      header: "Effective",
      sortable: true,
      render: (c) =>
        c.is_overdue ? (
          <Badge tone="critical">Overdue</Badge>
        ) : c.effective_date ? (
          <span className="muted">
            {c.effective_date}
            {c.days_to_effective != null && c.days_to_effective >= 0 ? ` · ${c.days_to_effective}d` : ""}
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "actions",
      header: "",
      render: (c) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => openEditChange(c)}>Edit</button>{" "}
          <button className="btn secondary sm" onClick={() => removeChange(c)}>Delete</button>
        </div>
      ),
    },
  ];

  const obligationColumns: Column<Obligation>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (o) => <span className="ref">{o.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (o) => <span className="cell-title">{o.title}</span> },
    { key: "obligation_type", header: "Type", sortable: true, render: (o) => <StatusBadge value={o.obligation_type} tone={OBL_TYPE_TONE} /> },
    { key: "owner", header: "Owner", sortable: true, render: (o) => <span className="muted">{o.owner || "—"}</span> },
    { key: "business_unit", header: "Business unit", sortable: true, render: (o) => <span className="muted">{o.business_unit || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (o) => <StatusBadge value={o.status} tone={OBL_STATUS_TONE} /> },
    { key: "due_date", header: "Due", sortable: true, render: (o) => <span className="muted">{o.due_date || "—"}</span> },
    {
      key: "actions",
      header: "",
      render: (o) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => removeObl(o)}>Delete</button>
        </div>
      ),
    },
  ];

  const returnColumns: Column<RegReturn>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, render: (r) => <span className="cell-title">{r.name}</span> },
    { key: "regulator", header: "Regulator", sortable: true, render: (r) => <span className="muted">{r.regulator || "—"}</span> },
    { key: "frequency", header: "Frequency", sortable: true, render: (r) => <span className="muted">{cap(r.frequency)}</span> },
    { key: "submission_channel", header: "Channel", render: (r) => <span className="muted">{r.submission_channel || "—"}</span> },
    { key: "owner", header: "Owner", render: (r) => <span className="muted">{r.owner || "—"}</span> },
    {
      key: "next_due_date",
      header: "Next due",
      sortable: true,
      render: (r) => {
        const dueSoon = !r.is_overdue && r.days_to_due != null && r.days_to_due >= 0 && r.days_to_due <= 30 && r.status !== "submitted";
        return r.is_overdue ? (
          <Badge tone="critical">Overdue{r.next_due_date ? ` · ${r.next_due_date}` : ""}</Badge>
        ) : r.next_due_date ? (
          <span className={dueSoon ? "" : "muted"}>
            {r.next_due_date}
            {r.days_to_due != null && r.days_to_due >= 0 ? ` · ${r.days_to_due}d` : ""}
          </span>
        ) : (
          <span className="muted">—</span>
        );
      },
    },
    { key: "status", header: "Status", sortable: true, render: (r) => <StatusBadge value={r.status} tone={RETURN_STATUS_TONE} /> },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => removeReturn(r)}>Delete</button>
        </div>
      ),
    },
  ];

  // ------------------------------------------------------------- change form tabs
  const changeGeneral = (
    <>
      <Field label="Title" required help="For example: Revised minimum capital requirements for banks.">
        <TextInput value={cf.title} onChange={(v) => setC("title", v)} placeholder="Regulatory change title" required />
      </Field>
      <div className="field-row">
        <Field label="Regulator" help="Issuing authority.">
          <TextInput value={cf.regulator} onChange={(v) => setC("regulator", v)} placeholder="SBP" />
        </Field>
        <Field label="Circular reference" help="The regulator's own reference.">
          <TextInput value={cf.circular_ref} onChange={(v) => setC("circular_ref", v)} placeholder="BPRD Circular No. 16 of 2024" />
        </Field>
      </div>
      <Field label="Source URL" help="Link to the circular / notification on the regulator's site.">
        <TextInput value={cf.source_url} onChange={(v) => setC("source_url", v)} placeholder="https://www.sbp.org.pk/..." />
      </Field>
      <div className="field-row">
        <Field label="Owner" help="Compliance officer accountable for this change.">
          <TextInput value={cf.owner} onChange={(v) => setC("owner", v)} placeholder="Compliance officer" />
        </Field>
        <Field label="Department">
          <TextInput value={cf.department} onChange={(v) => setC("department", v)} placeholder="Compliance" />
        </Field>
      </div>
      <Field label="Priority" help="Institutional priority for acting on this change.">
        <Select value={cf.priority} onChange={(v) => setC("priority", v)} options={PRIORITY_OPTS} />
      </Field>
    </>
  );
  const changeAssessment = (
    <>
      <div className="field-row">
        <Field label="Applicability" help="Does this change apply to the institution?">
          <Select value={cf.applicability} onChange={(v) => setC("applicability", v)} options={APPLICABILITY_OPTS} />
        </Field>
        <Field label="Status" help="Lifecycle from identification to closure.">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={REG_STATUS_OPTS} />
        </Field>
      </div>
      <Field label="Summary" help="What the circular changes, in plain terms.">
        <TextArea value={cf.summary} onChange={(v) => setC("summary", v)} rows={3} placeholder="Summary of the regulatory change." />
      </Field>
      <Field label="Impact assessment" help="Assessed impact on products, processes, systems and controls.">
        <TextArea value={cf.impact_assessment} onChange={(v) => setC("impact_assessment", v)} rows={4} placeholder="Impact on the institution and required actions." />
      </Field>
    </>
  );
  const changeTiming = (
    <>
      <div className="field-row">
        <Field label="Issued date" help="When the regulator issued the circular.">
          <TextInput type="date" value={cf.issued_date} onChange={(v) => setC("issued_date", v)} />
        </Field>
        <Field label="Effective date" help="Compliance deadline — drives the overdue flag.">
          <TextInput type="date" value={cf.effective_date} onChange={(v) => setC("effective_date", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this record.">
        <Select value={cf.workflow_status} onChange={(v) => setC("workflow_status", v)} options={WORKFLOW_OPTS} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- obligation form tabs
  const oblGeneral = (
    <>
      <Field label="Title" required help="For example: Submit revised KYC policy to the Board within 60 days.">
        <TextInput value={of.title} onChange={(v) => setO("title", v)} placeholder="Obligation title" required />
      </Field>
      <div className="field-row">
        <Field label="Type" help="Strength of the obligation.">
          <Select value={of.obligation_type} onChange={(v) => setO("obligation_type", v)} options={OBL_TYPE_OPTS} />
        </Field>
        <Field label="Status">
          <Select value={of.status} onChange={(v) => setO("status", v)} options={OBL_STATUS_OPTS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={of.owner} onChange={(v) => setO("owner", v)} placeholder="Accountable owner" />
        </Field>
        <Field label="Business unit">
          <TextInput value={of.business_unit} onChange={(v) => setO("business_unit", v)} placeholder="Retail banking" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Due date" help="Compliance deadline for this obligation.">
          <TextInput type="date" value={of.due_date} onChange={(v) => setO("due_date", v)} />
        </Field>
        <Field label="Linked regulatory change" help="Optional — leave blank for a standalone obligation.">
          <AsyncSelect
            search={searchChanges}
            value={of.regulatory_change_id || null}
            selectedLabel={oblChange?.label}
            onChange={(val, opt) => {
              setO("regulatory_change_id", val || "");
              setOblChange(opt);
            }}
            placeholder="— None —"
          />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={of.description} onChange={(v) => setO("description", v)} rows={3} placeholder="What must be done to meet this obligation." />
      </Field>
    </>
  );
  const oblMapping = (
    <>
      <Field label="Mapped policies" help="Policies that satisfy or govern this obligation.">
        <TextArea value={of.mapped_policies} onChange={(v) => setO("mapped_policies", v)} rows={3} placeholder="KYC/CDD Policy, AML Policy…" />
      </Field>
      <Field label="Mapped controls" help="Controls providing assurance over this obligation.">
        <TextArea value={of.mapped_controls} onChange={(v) => setO("mapped_controls", v)} rows={3} placeholder="Transaction monitoring, sanctions screening…" />
      </Field>
    </>
  );

  // ------------------------------------------------------------- return form tabs
  const returnGeneral = (
    <>
      <Field label="Name" required help="For example: Quarterly Report of Condition (QRC).">
        <TextInput value={rf.name} onChange={(v) => setR("name", v)} placeholder="Return name" required />
      </Field>
      <div className="field-row">
        <Field label="Regulator">
          <TextInput value={rf.regulator} onChange={(v) => setR("regulator", v)} placeholder="SBP" />
        </Field>
        <Field label="Submission channel" help="Where / how the return is filed.">
          <TextInput value={rf.submission_channel} onChange={(v) => setR("submission_channel", v)} placeholder="SBP Data Acquisition Portal" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={rf.owner} onChange={(v) => setR("owner", v)} placeholder="Preparer / owner" />
        </Field>
        <Field label="Department">
          <TextInput value={rf.department} onChange={(v) => setR("department", v)} placeholder="Regulatory Reporting" />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={rf.description} onChange={(v) => setR("description", v)} rows={3} placeholder="What this return covers." />
      </Field>
    </>
  );
  const returnSchedule = (
    <>
      <div className="field-row">
        <Field label="Frequency" help="How often the return is filed.">
          <Select value={rf.frequency} onChange={(v) => setR("frequency", v)} options={FREQUENCY_OPTS} />
        </Field>
        <Field label="Status">
          <Select value={rf.status} onChange={(v) => setR("status", v)} options={RETURN_STATUS_OPTS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Next due date" help="When the next submission is due.">
          <TextInput type="date" value={rf.next_due_date} onChange={(v) => setR("next_due_date", v)} />
        </Field>
        <Field label="Last submitted date">
          <TextInput type="date" value={rf.last_submitted_date} onChange={(v) => setR("last_submitted_date", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this record.">
        <Select value={rf.workflow_status} onChange={(v) => setR("workflow_status", v)} options={WORKFLOW_OPTS} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Regulatory Change</h1>
          <p>Track SBP circulars &amp; laws through applicability, obligations and implementation, plus the recurring regulatory-returns calendar.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "changes" && (
            <button className="btn" onClick={openNewChange}>
              <IconPlus width={16} height={16} /> New change
            </button>
          )}
          {section === "obligations" && (
            <button className="btn" onClick={openNewObl}>
              <IconPlus width={16} height={16} /> New obligation
            </button>
          )}
          {section === "returns" && (
            <button className="btn" onClick={openNewReturn}>
              <IconPlus width={16} height={16} /> New return
            </button>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            className={`btn${section === s.id ? "" : " secondary"}`}
            onClick={() => setSection(s.id)}
            type="button"
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= REGULATORY CHANGES */}
      {section === "changes" && (
        <>
          <div className="grid stat-grid">
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.changes_open.toLocaleString() : "—"}</span></div>
              <span className="l">Open changes</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.changes_in_implementation.toLocaleString() : "—"}</span></div>
              <span className="l">In implementation</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.changes_overdue.toLocaleString() : "—"}</span></div>
              <span className="l">Overdue</span>
            </div>
          </div>

          <DataTable<RegChange>
            columns={changeColumns}
            fetcher={fetchChanges}
            rowKey={(c) => c.id}
            onRowClick={(c) => setOpenId(c.id)}
            activeKey={openId}
            searchPlaceholder="Search title / circular ref / reference…"
            defaultSort={{ by: "created_at", dir: "desc" }}
            filters={{ status: statusF || undefined, applicability: applicF || undefined }}
            toolbarRight={
              <>
                <select className="select" style={{ width: 170 }} value={statusF} onChange={(ev) => setStatusF(ev.target.value)}>
                  <option value="">All statuses</option>
                  {REG_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                </select>
                <select className="select" style={{ width: 160 }} value={applicF} onChange={(ev) => setApplicF(ev.target.value)}>
                  <option value="">All applicability</option>
                  {APPLICABILITY.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                </select>
              </>
            }
            emptyMessage="No regulatory changes. Log an SBP circular or law to track applicability, obligations and implementation."
            refreshKey={refreshKey}
          />
        </>
      )}

      {/* ============================================= OBLIGATIONS */}
      {section === "obligations" && (
        <DataTable<Obligation>
          columns={obligationColumns}
          fetcher={fetchObligations}
          rowKey={(o) => o.id}
          onRowClick={(o) => openEditObl(o)}
          searchPlaceholder="Search obligations by title or reference…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No obligations. Register compliance obligations, standalone or linked to a regulatory change."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= RETURNS CALENDAR */}
      {section === "returns" && (
        <>
          <div className="grid stat-grid">
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.returns_due_30.toLocaleString() : "—"}</span></div>
              <span className="l">Due in 30 days</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.returns_due_60.toLocaleString() : "—"}</span></div>
              <span className="l">Due in 60 days</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.returns_due_90.toLocaleString() : "—"}</span></div>
              <span className="l">Due in 90 days</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{summary ? summary.returns_overdue.toLocaleString() : "—"}</span></div>
              <span className="l">Overdue</span>
            </div>
          </div>

          <DataTable<RegReturn>
            columns={returnColumns}
            fetcher={fetchReturns}
            rowKey={(r) => r.id}
            onRowClick={(r) => openEditReturn(r)}
            searchPlaceholder="Search returns by name, reference or regulator…"
            defaultSort={{ by: "next_due_date", dir: "asc" }}
            emptyMessage="No regulatory returns. Register recurring SBP submissions to track upcoming and overdue filings."
            refreshKey={refreshKey}
          />
        </>
      )}

      {/* ============================================= CHANGE DRAWER (obligations) */}
      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={
          detail
            ? `${detail.regulator}${detail.circular_ref ? " · " + detail.circular_ref : ""} · ${cap(detail.status)}${detail.owner ? " · owner " + detail.owner : ""}`
            : ""
        }
        width={760}
        actions={
          detail && (
            <>
              <button className="btn secondary sm" onClick={() => openEditChange(detail)}>Edit</button>
              <button className="btn secondary sm" onClick={() => removeChange(detail)}>Delete</button>
            </>
          )
        }
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              <StatusBadge value={detail.applicability} tone={APPLICABILITY_TONE} />
              <StatusBadge value={detail.status} tone={REG_STATUS_TONE} />
              <StatusBadge value={detail.priority} tone={PRIORITY_TONE} />
              {detail.is_overdue && <Badge tone="critical">Overdue</Badge>}
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Obligations</h3><span className="sub">{detail.obligation_count} tracked to closure</span></div>
              <div className="card-pad">
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(ev) => { ev.preventDefault(); addNestedObligation(); }}
                >
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Title</label>
                    <input className="input" value={od.title} onChange={(ev) => setOD("title", ev.target.value)} placeholder="Obligation title" required />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Type</label>
                    <select className="select" value={od.obligation_type} onChange={(ev) => setOD("obligation_type", ev.target.value)}>
                      {OBL_TYPE.map((t) => (<option key={t} value={t}>{cap(t)}</option>))}
                    </select>
                  </div>
                  <div style={{ width: 130 }}>
                    <label className="label">Owner</label>
                    <input className="input" value={od.owner} onChange={(ev) => setOD("owner", ev.target.value)} placeholder="Owner" />
                  </div>
                  <div style={{ width: 130 }}>
                    <label className="label">Status</label>
                    <select className="select" value={od.status} onChange={(ev) => setOD("status", ev.target.value)}>
                      {OBL_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                    </select>
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Due date</label>
                    <input className="input" type="date" value={od.due_date} onChange={(ev) => setOD("due_date", ev.target.value)} />
                  </div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ref</th>
                        <th>Title</th>
                        <th>Type</th>
                        <th>Owner</th>
                        <th>Status</th>
                        <th>Due</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.obligations.map((o) => (
                        <tr key={o.id}>
                          <td className="ref">{o.reference || "—"}</td>
                          <td className="cell-title">{o.title}</td>
                          <td><StatusBadge value={o.obligation_type} tone={OBL_TYPE_TONE} /></td>
                          <td className="muted">{o.owner || "—"}</td>
                          <td><StatusBadge value={o.status} tone={OBL_STATUS_TONE} /></td>
                          <td className="muted">{o.due_date || "—"}</td>
                          <td>
                            <div style={{ display: "flex", gap: 6 }}>
                              <button className="btn secondary sm" onClick={() => openEditObl(o)}>Edit</button>
                              <button className="btn secondary sm" onClick={() => removeNestedObligation(o.id)}>Remove</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {detail.obligations.length === 0 && (
                        <tr><td colSpan={7}><span className="muted">No obligations recorded yet.</span></td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <RecordPanels model="regulatory_change" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {/* ============================================= MODALS */}
      {showChangeForm && (
        <FormModal
          title={editingChange ? `Edit change — ${editingChange.reference || editingChange.title}` : "New regulatory change"}
          wide
          tabs={[
            { id: "general", label: "General", content: changeGeneral, required: true },
            { id: "assessment", label: "Assessment", content: changeAssessment },
            { id: "timing", label: "Timing", content: changeTiming },
          ]}
          onClose={() => setShowChangeForm(false)}
          onSave={saveChange}
          saving={savingChange}
          error={error}
          saveLabel={editingChange ? "Save changes" : "Create change"}
          footerLeft={
            editingChange ? (
              <button className="btn secondary sm" type="button" onClick={() => removeChange(editingChange)} disabled={savingChange} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showOblForm && (
        <FormModal
          title={editingObl ? `Edit obligation — ${editingObl.reference || editingObl.title}` : "New obligation"}
          wide
          tabs={[
            { id: "general", label: "General", content: oblGeneral, required: true },
            { id: "mapping", label: "Policy & Control Mapping", content: oblMapping },
          ]}
          onClose={() => setShowOblForm(false)}
          onSave={saveObl}
          saving={savingObl}
          error={error}
          saveLabel={editingObl ? "Save changes" : "Create obligation"}
          footerLeft={
            editingObl ? (
              <button className="btn secondary sm" type="button" onClick={() => removeObl(editingObl)} disabled={savingObl} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showReturnForm && (
        <FormModal
          title={editingReturn ? `Edit return — ${editingReturn.reference || editingReturn.name}` : "New regulatory return"}
          wide
          tabs={[
            { id: "general", label: "General", content: returnGeneral, required: true },
            { id: "schedule", label: "Schedule", content: returnSchedule },
          ]}
          onClose={() => setShowReturnForm(false)}
          onSave={saveReturn}
          saving={savingReturn}
          error={error}
          saveLabel={editingReturn ? "Save changes" : "Create return"}
          footerLeft={
            editingReturn ? (
              <button className="btn secondary sm" type="button" onClick={() => removeReturn(editingReturn)} disabled={savingReturn} style={{ color: "var(--danger, #c0392b)" }}>
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

export default function RegulatoryChangePage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <RegulatoryChangeInner />
    </Suspense>
  );
}
