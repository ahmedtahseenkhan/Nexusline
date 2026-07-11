"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";

// ------------------------------------------------------------------ types
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

type AuthorityMatrix = {
  id: string;
  reference: string;
  activity: string;
  description: string;
  category: string;
  role_title: string;
  approval_level: number;
  amount_from: number;
  amount_to: number | null;
  currency: string;
  conditions: string;
  effective_date: string | null;
  status: string;
  workflow_status: string;
  amount_range_label: string;
  created_at: string;
};

type DualControlRule = {
  id: string;
  reference: string;
  module: string;
  action: string;
  requires_dual_control: boolean;
  maker_role: string;
  checker_role: string;
  threshold_amount: number | null;
  currency: string;
  description: string;
  enabled: boolean;
  status: string;
  workflow_status: string;
  created_at: string;
};

type AuthoritySummary = {
  matrix_total: number;
  matrix_by_category: Record<string, number>;
  matrix_by_level: Record<string, number>;
  categories_covered: number;
  dual_control_total: number;
  dual_control_enabled: number;
  modules_covered: number;
};

// ------------------------------------------------------------------ helpers
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

// ------------------------------------------------------------------ enum lists
const CATEGORIES = opts(["credit", "expenditure", "procurement", "hr", "it_change", "risk_acceptance", "treasury", "general"]);
const AUTHORITY_STATUS = opts(["active", "retired"]);
const DUAL_STATUS = opts(["active", "disabled"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

// ------------------------------------------------------------------ tones
const CATEGORY_TONE: Record<string, Tone> = {
  credit: "info", expenditure: "info", procurement: "neutral", hr: "neutral",
  it_change: "medium", risk_acceptance: "high", treasury: "info", general: "neutral",
};
const AUTHORITY_STATUS_TONE: Record<string, Tone> = { active: "low", retired: "neutral" };
const DUAL_STATUS_TONE: Record<string, Tone> = { active: "low", disabled: "neutral" };

// ------------------------------------------------------------------ matrix form state
type MatrixForm = {
  activity: string; description: string; category: string; role_title: string; approval_level: string;
  amount_from: string; amount_to: string; currency: string; conditions: string; effective_date: string;
  status: string; workflow_status: string;
};
const BLANK_MATRIX: MatrixForm = {
  activity: "", description: "", category: "credit", role_title: "", approval_level: "1",
  amount_from: "0", amount_to: "", currency: "PKR", conditions: "", effective_date: "",
  status: "active", workflow_status: "draft",
};
function fromMatrix(m: AuthorityMatrix): MatrixForm {
  return {
    activity: m.activity, description: m.description || "", category: m.category || "credit",
    role_title: m.role_title || "", approval_level: m.approval_level != null ? String(m.approval_level) : "1",
    amount_from: m.amount_from != null ? String(m.amount_from) : "0",
    amount_to: m.amount_to != null ? String(m.amount_to) : "", currency: m.currency || "PKR",
    conditions: m.conditions || "", effective_date: m.effective_date || "",
    status: m.status || "active", workflow_status: m.workflow_status || "draft",
  };
}
function matrixPayload(f: MatrixForm): Record<string, unknown> {
  return {
    activity: f.activity, description: f.description, category: f.category, role_title: f.role_title,
    approval_level: f.approval_level === "" ? 1 : Number(f.approval_level),
    amount_from: f.amount_from === "" ? 0 : Number(f.amount_from),
    amount_to: f.amount_to === "" ? null : Number(f.amount_to),
    currency: f.currency, conditions: f.conditions, effective_date: f.effective_date || null,
    status: f.status, workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ rule form state
type RuleForm = {
  module: string; action: string; requires_dual_control: boolean; maker_role: string; checker_role: string;
  threshold_amount: string; currency: string; description: string; enabled: boolean; status: string; workflow_status: string;
};
const BLANK_RULE: RuleForm = {
  module: "", action: "", requires_dual_control: true, maker_role: "", checker_role: "",
  threshold_amount: "", currency: "PKR", description: "", enabled: true, status: "active", workflow_status: "draft",
};
function fromRule(r: DualControlRule): RuleForm {
  return {
    module: r.module, action: r.action, requires_dual_control: r.requires_dual_control,
    maker_role: r.maker_role || "", checker_role: r.checker_role || "",
    threshold_amount: r.threshold_amount != null ? String(r.threshold_amount) : "", currency: r.currency || "PKR",
    description: r.description || "", enabled: r.enabled, status: r.status || "active", workflow_status: r.workflow_status || "draft",
  };
}
function rulePayload(f: RuleForm): Record<string, unknown> {
  return {
    module: f.module, action: f.action, requires_dual_control: f.requires_dual_control,
    maker_role: f.maker_role, checker_role: f.checker_role,
    threshold_amount: f.threshold_amount === "" ? null : Number(f.threshold_amount),
    currency: f.currency, description: f.description, enabled: f.enabled, status: f.status, workflow_status: f.workflow_status,
  };
}

type SectionId = "matrix" | "rules";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "matrix", label: "Authority Matrix" },
  { id: "rules", label: "Maker-Checker Rules" },
];

/* ================================================================ page ===== */
function DelegationOfAuthorityInner() {
  const [section, setSection] = useState<SectionId>("matrix");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<AuthoritySummary | null>(null);

  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<AuthorityMatrix | null>(null);

  // ---- matrix dialog ----
  const [editingMatrix, setEditingMatrix] = useState<AuthorityMatrix | null>(null);
  const [showMatrixForm, setShowMatrixForm] = useState(false);
  const [savingMatrix, setSavingMatrix] = useState(false);
  const [mf, setMf] = useState<MatrixForm>(BLANK_MATRIX);
  const setM = <K extends keyof MatrixForm>(k: K, v: MatrixForm[K]) => setMf((p) => ({ ...p, [k]: v }));

  // ---- rule dialog ----
  const [editingRule, setEditingRule] = useState<DualControlRule | null>(null);
  const [showRuleForm, setShowRuleForm] = useState(false);
  const [savingRule, setSavingRule] = useState(false);
  const [rf, setRf] = useState<RuleForm>(BLANK_RULE);
  const setR = <K extends keyof RuleForm>(k: K, v: RuleForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchMatrix = useCallback((qs: string) => apiCall<PagedList<AuthorityMatrix>>("GET", `/authority-matrix?${qs}`), []);
  const fetchRules = useCallback((qs: string) => apiCall<PagedList<DualControlRule>>("GET", `/dual-control-rules?${qs}`), []);

  const loadSummary = useCallback(() => { apiCall<AuthoritySummary>("GET", "/authority-summary").then(setSummary).catch(() => {}); }, []);
  const loadDetail = useCallback((id: string) => { apiCall<AuthorityMatrix>("GET", `/authority-matrix/${id}`).then(setDetail).catch(() => setDetail(null)); }, []);

  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // ------------------------------------------------------------- matrix CRUD
  function openNewMatrix() { setEditingMatrix(null); setMf(BLANK_MATRIX); setError(null); setShowMatrixForm(true); }
  function openEditMatrix(m: AuthorityMatrix) { setEditingMatrix(m); setMf(fromMatrix(m)); setError(null); setShowMatrixForm(true); }
  async function saveMatrix() {
    setError(null); setSavingMatrix(true);
    try {
      const payload = matrixPayload(mf);
      if (editingMatrix) await apiCall<AuthorityMatrix>("PATCH", `/authority-matrix/${editingMatrix.id}`, payload);
      else await apiCall<AuthorityMatrix>("POST", "/authority-matrix", payload);
      setShowMatrixForm(false); reload(); loadSummary(); if (openId) loadDetail(openId);
      toast(editingMatrix ? "Changes saved" : "Authority line created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save authority line"); }
    finally { setSavingMatrix(false); }
  }
  async function removeMatrix(m: AuthorityMatrix) {
    if (!(await confirmDialog({ title: `Delete authority line ${m.reference || m.activity}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/authority-matrix/${m.id}`);
      setShowMatrixForm(false); if (openId === m.id) setOpenId(null); reload(); loadSummary(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }

  // ------------------------------------------------------------- rule CRUD
  function openNewRule() { setEditingRule(null); setRf(BLANK_RULE); setError(null); setShowRuleForm(true); }
  function openEditRule(r: DualControlRule) { setEditingRule(r); setRf(fromRule(r)); setError(null); setShowRuleForm(true); }
  async function saveRule() {
    setError(null); setSavingRule(true);
    try {
      const payload = rulePayload(rf);
      if (editingRule) await apiCall<DualControlRule>("PATCH", `/dual-control-rules/${editingRule.id}`, payload);
      else await apiCall<DualControlRule>("POST", "/dual-control-rules", payload);
      setShowRuleForm(false); reload(); loadSummary();
      toast(editingRule ? "Changes saved" : "Rule created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save rule"); }
    finally { setSavingRule(false); }
  }
  async function removeRule(r: DualControlRule) {
    if (!(await confirmDialog({ title: `Delete maker-checker rule ${r.reference || r.module}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/dual-control-rules/${r.id}`);
      setShowRuleForm(false); reload(); loadSummary(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }
  async function toggleEnabled(r: DualControlRule) {
    setError(null);
    try {
      await apiCall<DualControlRule>("PATCH", `/dual-control-rules/${r.id}`, {
        enabled: !r.enabled,
        status: !r.enabled ? "active" : "disabled",
      });
      reload(); loadSummary();
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to update rule"); }
  }

  // ------------------------------------------------------------- columns
  const matrixColumns: Column<AuthorityMatrix>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (m) => <span className="ref">{m.reference || "—"}</span> },
    { key: "activity", header: "Activity", sortable: true, render: (m) => <span className="cell-title">{m.activity}</span> },
    { key: "category", header: "Category", sortable: true, render: (m) => <Badge tone={CATEGORY_TONE[m.category] || "neutral"}>{cap(m.category)}</Badge> },
    { key: "role_title", header: "Role", sortable: true, render: (m) => <span className="muted">{m.role_title || "—"}</span> },
    { key: "approval_level", header: "Level", sortable: true, render: (m) => <span className="muted">L{m.approval_level}</span> },
    { key: "amount_from", header: "Amount range", sortable: true, render: (m) => <span className="muted">{m.amount_range_label}</span> },
    { key: "status", header: "Status", sortable: true, render: (m) => <Badge tone={AUTHORITY_STATUS_TONE[m.status] || "neutral"}>{cap(m.status)}</Badge> },
    { key: "actions", header: "", render: (m) => <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditMatrix(m)}>Edit</button><button className="btn secondary sm" onClick={() => removeMatrix(m)}>Delete</button></div> },
  ];

  const ruleColumns: Column<DualControlRule>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference || "—"}</span> },
    { key: "module", header: "Module", sortable: true, render: (r) => <span className="cell-title">{r.module}</span> },
    { key: "action", header: "Action", sortable: true, render: (r) => <span className="muted">{cap(r.action)}</span> },
    { key: "makerchecker", header: "Maker → Checker", render: (r) => <span className="muted">{(r.maker_role || "—")} → {(r.checker_role || "—")}{!r.requires_dual_control && <span className="muted"> (single)</span>}</span> },
    { key: "threshold_amount", header: "Threshold", sortable: true, render: (r) => <span className="muted">{r.threshold_amount != null ? `${num(r.threshold_amount)} ${r.currency}` : "Always"}</span> },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={DUAL_STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge> },
    { key: "enabled", header: "Enabled", render: (r) => <span onClick={(e) => e.stopPropagation()}><Toggle checked={r.enabled} onChange={() => toggleEnabled(r)} label={r.enabled ? "On" : "Off"} /></span> },
    { key: "actions", header: "", render: (r) => <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditRule(r)}>Edit</button><button className="btn secondary sm" onClick={() => removeRule(r)}>Delete</button></div> },
  ];

  // ------------------------------------------------------------- matrix form tabs
  const matrixGeneral = (
    <>
      <Field label="Activity" required help='For example: "Approve credit facility" or "Waive service charges".'>
        <TextInput value={mf.activity} onChange={(v) => setM("activity", v)} placeholder="Approve credit facility" required />
      </Field>
      <div className="field-row">
        <Field label="Category" help="The kind of activity this mandate governs.">
          <Select value={mf.category} onChange={(v) => setM("category", v)} options={CATEGORIES} />
        </Field>
        <Field label="Status">
          <Select value={mf.status} onChange={(v) => setM("status", v)} options={AUTHORITY_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Role title" help='The approving role, e.g. "Branch Manager", "CRO", "Board".'>
          <TextInput value={mf.role_title} onChange={(v) => setM("role_title", v)} placeholder="Branch Manager" />
        </Field>
        <Field label="Approval level" help="Escalation tier — level 1 is the lowest mandate.">
          <TextInput type="number" value={mf.approval_level} onChange={(v) => setM("approval_level", v)} placeholder="1" />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={mf.description} onChange={(v) => setM("description", v)} rows={3} placeholder="What this mandate covers." />
      </Field>
    </>
  );
  const matrixAmounts = (
    <>
      <div className="field-row">
        <Field label="Amount from" help="Lower bound of the approval band.">
          <TextInput type="number" value={mf.amount_from} onChange={(v) => setM("amount_from", v)} placeholder="0" />
        </Field>
        <Field label="Amount to" help="Upper bound — leave blank for unlimited.">
          <TextInput type="number" value={mf.amount_to} onChange={(v) => setM("amount_to", v)} placeholder="Unlimited" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Currency">
          <TextInput value={mf.currency} onChange={(v) => setM("currency", v)} placeholder="PKR" />
        </Field>
        <Field label="Effective date" help="When this mandate takes effect.">
          <TextInput type="date" value={mf.effective_date} onChange={(v) => setM("effective_date", v)} />
        </Field>
      </div>
      <Field label="Conditions" help="Any conditions or caveats attached to this mandate.">
        <TextArea value={mf.conditions} onChange={(v) => setM("conditions", v)} rows={3} placeholder="e.g. subject to committee endorsement above PKR 50M." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this authority record.">
        <Select value={mf.workflow_status} onChange={(v) => setM("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- rule form tabs
  const ruleGeneral = (
    <>
      <div className="field-row">
        <Field label="Module" required help='The module the control applies to, e.g. "payments", "vendor", "policy_publish".'>
          <TextInput value={rf.module} onChange={(v) => setR("module", v)} placeholder="payments" required />
        </Field>
        <Field label="Action" required help='The action being controlled, e.g. "create", "approve", "disburse".'>
          <TextInput value={rf.action} onChange={(v) => setR("action", v)} placeholder="disburse" required />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Maker role" help="The role that initiates / prepares the transaction.">
          <TextInput value={rf.maker_role} onChange={(v) => setR("maker_role", v)} placeholder="Payments Officer" />
        </Field>
        <Field label="Checker role" help="The role that independently verifies / releases.">
          <TextInput value={rf.checker_role} onChange={(v) => setR("checker_role", v)} placeholder="Branch Manager" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Requires dual control" help="Whether four-eyes is mandatory for this action.">
          <Toggle checked={rf.requires_dual_control} onChange={(v) => setR("requires_dual_control", v)} label={rf.requires_dual_control ? "Required" : "Not required"} />
        </Field>
        <Field label="Enabled" help="Whether this rule is live in the registry.">
          <Toggle checked={rf.enabled} onChange={(v) => setR("enabled", v)} label={rf.enabled ? "Enabled" : "Disabled"} />
        </Field>
      </div>
    </>
  );
  const ruleDetails = (
    <>
      <div className="field-row">
        <Field label="Threshold amount" help="Dual control kicks in above this amount — leave blank to always apply.">
          <TextInput type="number" value={rf.threshold_amount} onChange={(v) => setR("threshold_amount", v)} placeholder="Always" />
        </Field>
        <Field label="Currency">
          <TextInput value={rf.currency} onChange={(v) => setR("currency", v)} placeholder="PKR" />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={rf.description} onChange={(v) => setR("description", v)} rows={3} placeholder="What this maker-checker rule enforces." />
      </Field>
      <div className="field-row">
        <Field label="Status">
          <Select value={rf.status} onChange={(v) => setR("status", v)} options={DUAL_STATUS} />
        </Field>
        <Field label="Workflow" help="Approval lifecycle for this rule record.">
          <Select value={rf.workflow_status} onChange={(v) => setR("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Delegation of Authority</h1>
          <p>The delegation-of-authority matrix (who may approve what, by amount and level) and the maker-checker (four-eyes) configuration registry per module action.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "matrix" && <button className="btn" onClick={openNewMatrix}>New authority line</button>}
          {section === "rules" && <button className="btn" onClick={openNewRule}>New maker-checker rule</button>}
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.matrix_total.toLocaleString() : "—"}</span></div>
          <span className="l">Authority matrix entries</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.categories_covered.toLocaleString() : "—"}</span></div>
          <span className="l">Categories covered</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.dual_control_enabled.toLocaleString() : "—"}</span></div>
          <span className="l">Dual-control rules enabled</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.modules_covered.toLocaleString() : "—"}</span></div>
          <span className="l">Modules covered</span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, margin: "16px 0", flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button key={s.id} className={`btn${section === s.id ? "" : " secondary"}`} onClick={() => setSection(s.id)} type="button">
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {section === "matrix" && (
        <DataTable<AuthorityMatrix>
          columns={matrixColumns}
          fetcher={fetchMatrix}
          rowKey={(m) => m.id}
          onRowClick={(m) => setOpenId(m.id)}
          activeKey={openId}
          searchPlaceholder="Search by activity, reference, role or description…"
          defaultSort={{ by: "approval_level", dir: "asc" }}
          emptyMessage="No authority lines. Define who may approve what, by amount band and approval level."
          refreshKey={refreshKey}
        />
      )}

      {section === "rules" && (
        <DataTable<DualControlRule>
          columns={ruleColumns}
          fetcher={fetchRules}
          rowKey={(r) => r.id}
          onRowClick={(r) => openEditRule(r)}
          searchPlaceholder="Search by module, action, roles or reference…"
          defaultSort={{ by: "module", dir: "asc" }}
          emptyMessage="No maker-checker rules. Register four-eyes / dual-control requirements per module action."
          refreshKey={refreshKey}
        />
      )}

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference || ""} ${detail.activity}`.trim() : "…"}
        subtitle={detail ? `${cap(detail.category)} · ${detail.role_title || "no role"} · level ${detail.approval_level}` : ""}
        width={720}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditMatrix(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeMatrix(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Amount range</div><div style={{ marginTop: 4 }}><strong>{detail.amount_range_label}</strong></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Effective date</div><div style={{ marginTop: 4 }}><strong>{detail.effective_date || "—"}</strong></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Status</div><div style={{ marginTop: 4 }}><Badge tone={AUTHORITY_STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge></div></div>
            </div>
            {detail.description && <p style={{ margin: "0 0 10px" }}>{detail.description}</p>}
            {detail.conditions && <p className="muted" style={{ margin: "0 0 14px", fontSize: 13 }}><strong>Conditions:</strong> {detail.conditions}</p>}
            <RecordPanels model="authority_matrix" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {showMatrixForm && (
        <FormModal
          title={editingMatrix ? `Edit authority line — ${editingMatrix.reference || editingMatrix.activity}` : "New authority line"}
          wide
          tabs={[
            { id: "general", label: "General", content: matrixGeneral, required: true },
            { id: "amounts", label: "Authority & amounts", content: matrixAmounts },
          ]}
          onClose={() => setShowMatrixForm(false)}
          onSave={saveMatrix}
          saving={savingMatrix}
          error={error}
          saveLabel={editingMatrix ? "Save changes" : "Create authority line"}
          footerLeft={editingMatrix ? (
            <button className="btn secondary sm" type="button" onClick={() => removeMatrix(editingMatrix)} disabled={savingMatrix} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
          ) : undefined}
        />
      )}

      {showRuleForm && (
        <FormModal
          title={editingRule ? `Edit rule — ${editingRule.reference || editingRule.module}` : "New maker-checker rule"}
          wide
          tabs={[
            { id: "general", label: "General", content: ruleGeneral, required: true },
            { id: "details", label: "Details", content: ruleDetails },
          ]}
          onClose={() => setShowRuleForm(false)}
          onSave={saveRule}
          saving={savingRule}
          error={error}
          saveLabel={editingRule ? "Save changes" : "Create rule"}
          footerLeft={editingRule ? (
            <button className="btn secondary sm" type="button" onClick={() => removeRule(editingRule)} disabled={savingRule} style={{ color: "var(--danger, #c0392b)" }}>Delete</button>
          ) : undefined}
        />
      )}
    </>
  );
}

export default function DelegationOfAuthorityPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <DelegationOfAuthorityInner />
    </Suspense>
  );
}
