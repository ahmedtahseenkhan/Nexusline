"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

// ----- inline types (api.ts is shared / read-only) -----------------------------
type LinkRef = { id: string; reference?: string; title?: string; name?: string };

type Exception = {
  id: string;
  reference: string;
  title: string;
  description: string;
  exception_type: string;
  classification: string;
  rationale: string;
  compensating_controls: string;
  business_owner: string;
  workflow_status: string;
  status: string;
  start_date: string | null;
  expires_at: string | null;
  closure_date: string | null;
  requested_by: string | null;
  approver_id: string | null;
  decided_at: string | null;
  is_expired: boolean;
  risks: LinkRef[];
  policies: LinkRef[];
  requirements: LinkRef[];
  controls: LinkRef[];
  assets: LinkRef[];
  created_at: string;
};

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  pending: "medium",
  rejected: "critical",
  expired: "high",
  closed: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const TYPE = opts(["risk", "policy", "compliance", "other"]);
const STATUS = opts(["pending", "approved", "rejected", "expired", "closed"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

const refToOpt = (x: LinkRef): AsyncOption => ({ value: x.id, label: x.reference || x.title || x.name || x.id });

type FormState = {
  title: string;
  description: string;
  exception_type: string;
  classification: string;
  rationale: string;
  status: string;
  workflow_status: string;
  business_owner: string;
  start_date: string;
  expires_at: string;
  closure_date: string;
  compensating_controls: string;
  control_ids: AsyncOption[];
  risk_ids: AsyncOption[];
  policy_ids: AsyncOption[];
  requirement_ids: AsyncOption[];
  asset_ids: AsyncOption[];
};

const BLANK: FormState = {
  title: "", description: "", exception_type: "risk", classification: "",
  rationale: "", status: "pending", workflow_status: "draft", business_owner: "",
  start_date: "", expires_at: "", closure_date: "", compensating_controls: "",
  control_ids: [], risk_ids: [], policy_ids: [], requirement_ids: [], asset_ids: [],
};

function fromException(x: Exception): FormState {
  return {
    title: x.title,
    description: x.description || "",
    exception_type: x.exception_type,
    classification: x.classification || "",
    rationale: x.rationale || "",
    status: x.status,
    workflow_status: x.workflow_status || "draft",
    business_owner: x.business_owner || "",
    start_date: x.start_date || "",
    expires_at: x.expires_at || "",
    closure_date: x.closure_date || "",
    compensating_controls: x.compensating_controls || "",
    control_ids: x.controls.map(refToOpt),
    risk_ids: x.risks.map(refToOpt),
    policy_ids: x.policies.map(refToOpt),
    requirement_ids: x.requirements.map(refToOpt),
    asset_ids: x.assets.map(refToOpt),
  };
}

// only send the fields the API understands; empty dates -> null.
// `status` is accepted on PATCH (manual override) but not on create — the model
// always starts a new exception as `pending` and the workflow drives it thereafter.
function toPayload(f: FormState, editing: boolean): Record<string, unknown> {
  return {
    title: f.title,
    description: f.description,
    exception_type: f.exception_type,
    classification: f.classification,
    rationale: f.rationale,
    workflow_status: f.workflow_status,
    business_owner: f.business_owner,
    compensating_controls: f.compensating_controls,
    start_date: f.start_date || null,
    expires_at: f.expires_at || null,
    closure_date: f.closure_date || null,
    control_ids: f.control_ids.map((o) => o.value),
    risk_ids: f.risk_ids.map((o) => o.value),
    policy_ids: f.policy_ids.map((o) => o.value),
    requirement_ids: f.requirement_ids.map((o) => o.value),
    asset_ids: f.asset_ids.map((o) => o.value),
    ...(editing ? { status: f.status } : {}),
  };
}

/* ================================================================ page ===== */
function ExceptionsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Exception | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  // filters
  const [fStatus, setFStatus] = useState("");
  const [fType, setFType] = useState("");

  const [editing, setEditing] = useState<Exception | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchExceptions = useCallback((qs: string) => apiCall<PagedList<Exception>>("GET", `/exceptions?${qs}`), []);
  const loadDetail = useCallback((id: string) => { apiCall<Exception>("GET", `/exceptions/${id}`).then(setDetail).catch(() => setDetail(null)); }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // server typeahead sources for the form link pickers
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name, sub: x.reference })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  const searchAssets = (q: string) => apiCall<PagedList<{ id: string; name: string }>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.name })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(x: Exception) { setEditing(x); setF(fromException(x)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f, !!editing);
      if (editing) await apiCall("PATCH", `/exceptions/${editing.id}`, payload);
      else await apiCall("POST", "/exceptions", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Exception requested");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save exception"); }
    finally { setSaving(false); }
  }

  async function act(fn: Promise<unknown>, message: string) {
    setError(null);
    try {
      await fn;
      reload(); if (openId) loadDetail(openId); toast(message);
    } catch (e) { setError(e instanceof Error ? e.message : "Action failed"); }
  }
  const decide = (id: string, approve: boolean) =>
    act(apiCall("POST", `/exceptions/${id}/decision`, { approve, note: "" }), approve ? "Approved" : "Rejected");
  const close = (id: string) => act(apiCall("POST", `/exceptions/${id}/close`), "Closed");
  async function remove(x: Exception) {
    if (!(await confirmDialog({ title: `Delete exception ${x.reference}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall("DELETE", `/exceptions/${x.id}`);
      if (openId === x.id) setOpenId(null);
      reload(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }

  const linkCount = (x: Exception) =>
    x.risks.length + x.policies.length + x.requirements.length + x.controls.length + x.assets.length;
  const isPast = (d: string | null) => !!d && new Date(d) < new Date(new Date().toDateString());

  const columns: Column<Exception>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (x) => <span className="ref">{x.reference}</span> },
    { key: "title", header: "Title", sortable: true, render: (x) => <span className="cell-title">{x.title}</span> },
    { key: "exception_type", header: "Type", sortable: true, render: (x) => <Badge tone="info" plain>{cap(x.exception_type)}</Badge> },
    { key: "status", header: "Status", sortable: true, render: (x) => <><Badge tone={STATUS_TONE[x.status] || "neutral"}>{cap(x.status)}</Badge>{x.is_expired && <span style={{ marginLeft: 6 }}><Badge tone="high">Expired</Badge></span>}</> },
    { key: "start_date", header: "Start", sortable: true, render: (x) => <span className="muted">{x.start_date || "—"}</span> },
    { key: "expires_at", header: "Expires", sortable: true, render: (x) => (x.expires_at ? (isPast(x.expires_at) ? <Badge tone="high">{x.expires_at}</Badge> : <span className="muted">{x.expires_at}</span>) : <span className="muted">—</span>) },
    { key: "controls", header: "Controls", align: "center", render: (x) => <span className="muted">{x.controls.length || "—"}</span> },
    { key: "links", header: "Links", align: "center", render: (x) => <span className="muted">{linkCount(x) || "—"}</span> },
    { key: "actions", header: "", render: (x) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(x)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(x)}>Delete</button></div> },
  ];

  const filters = { status: fStatus || undefined, type: fType || undefined };

  const generalTab = (
    <>
      <Field label="Title" required help="For example: Accept legacy TLS until Q4 migration.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Accept legacy TLS until Q4 migration" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What gap is being accepted and why it cannot be remediated now." />
      </Field>
      <div className="field-row">
        <Field label="Exception Type" help="What kind of gap this exception covers.">
          <Select value={f.exception_type} onChange={(v) => set("exception_type", v)} options={TYPE} />
        </Field>
        <Field label="Classification" help="Optional grouping label, e.g. Temporary, Permanent, Regulatory.">
          <TextInput value={f.classification} onChange={(v) => set("classification", v)} placeholder="Temporary" />
        </Field>
      </div>
      <div className="field-row">
        {editing ? (
          <Field label="Status" help="Manual override. The row actions (Approve / Reject / Close) are the primary path.">
            <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
          </Field>
        ) : (
          <Field label="Status" help="New exceptions start as Pending and await an approval decision.">
            <TextInput value="Pending (on submit)" onChange={() => {}} />
          </Field>
        )}
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Business Owner">
          <TextInput value={f.business_owner} onChange={(v) => set("business_owner", v)} placeholder="Head of Engineering" />
        </Field>
      </div>
      <Field label="Rationale / Justification" help="Business justification for accepting this gap.">
        <RichText value={f.rationale} onChange={(v) => set("rationale", v)} />
      </Field>
    </>
  );

  const validityTab = (
    <>
      <p className="help" style={{ marginBottom: 14 }}>
        Exceptions are time-boxed. An approved exception past its expiry date is flagged as Expired in the register.
      </p>
      <div className="field-row">
        <Field label="Start Date" help="When the exception takes effect.">
          <TextInput type="date" value={f.start_date} onChange={(v) => set("start_date", v)} />
        </Field>
        <Field label="Expires At" help="Hard expiry — the exception must be re-reviewed or closed by this date.">
          <TextInput type="date" value={f.expires_at} onChange={(v) => set("expires_at", v)} />
        </Field>
        <Field label="Closure Date" help="Set when the exception is formally closed.">
          <TextInput type="date" value={f.closure_date} onChange={(v) => set("closure_date", v)} />
        </Field>
      </div>
    </>
  );

  const linksTab = (
    <>
      <Field label="Compensating Controls" help="Interim mitigation in place while the gap is accepted (free text).">
        <TextArea value={f.compensating_controls} onChange={(v) => set("compensating_controls", v)} rows={3} placeholder="e.g. WAF rule + quarterly review of access logs" />
      </Field>
      <Field label="Linked Controls" help="Controls that mitigate or relate to this exception.">
        <AsyncMultiSelect search={searchControls} value={f.control_ids} onChange={(v) => set("control_ids", v)} />
      </Field>
      <Field label="Linked Risks" help="Risks being formally accepted by this exception.">
        <AsyncMultiSelect search={searchRisks} value={f.risk_ids} onChange={(v) => set("risk_ids", v)} />
      </Field>
      <Field label="Linked Policies" help="Policies whose requirements are being excepted.">
        <AsyncMultiSelect search={searchPolicies} value={f.policy_ids} onChange={(v) => set("policy_ids", v)} />
      </Field>
      <Field label="Linked Requirements" help="Compliance requirements covered by this exception.">
        <AsyncMultiSelect search={searchRequirements} value={f.requirement_ids} onChange={(v) => set("requirement_ids", v)} />
      </Field>
      <Field label="Linked Assets" help="Assets affected by this exception.">
        <AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Exceptions</h1>
          <p>Formal, time-boxed acceptance of risk, policy or compliance gaps with an approval workflow.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="exceptions" label="Exceptions" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add exception
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Exception>
        columns={columns}
        fetcher={fetchExceptions}
        rowKey={(x) => x.id}
        onRowClick={(x) => setOpenId(x.id)}
        activeKey={openId}
        searchPlaceholder="Search exceptions by title or reference…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        filters={filters}
        toolbarRight={
          <>
            <select className="select" style={{ maxWidth: 160 }} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
              <option value="">All statuses</option>
              {STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <select className="select" style={{ maxWidth: 150 }} value={fType} onChange={(e) => setFType(e.target.value)}>
              <option value="">All types</option>
              {TYPE.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
          </>
        }
        emptyMessage="No exceptions. Request an exception to formally accept a gap with an expiry date."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={detail ? `${cap(detail.exception_type)} · ${cap(detail.status)}${detail.business_owner ? " · " + detail.business_owner : ""}` : ""}
        width={720}
        actions={detail && (
          <>
            {detail.status === "pending" && (
              <>
                <button className="btn sm" onClick={() => decide(detail.id, true)}><IconCheck width={13} height={13} /> Approve</button>
                <button className="btn secondary sm" onClick={() => decide(detail.id, false)}>Reject</button>
              </>
            )}
            {detail.status === "approved" && <button className="btn secondary sm" onClick={() => close(detail.id)}>Close</button>}
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
              <Badge tone="info" plain>{cap(detail.exception_type)}</Badge>
              <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {detail.is_expired && <Badge tone="high">Expired</Badge>}
              {linkCount(detail) > 0 && <Badge tone="neutral" plain>{linkCount(detail)} links</Badge>}
            </div>

            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Start</div><div style={{ marginTop: 4 }}>{detail.start_date || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Expires</div><div style={{ marginTop: 4 }}>{detail.expires_at || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Closure</div><div style={{ marginTop: 4 }}>{detail.closure_date || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Decided</div><div style={{ marginTop: 4 }}>{detail.decided_at || "—"}</div></div>
            </div>

            {detail.description && (
              <div style={{ marginBottom: 12 }}><span className="muted" style={{ fontSize: 12 }}>Description</span><div style={{ fontSize: 13 }}>{detail.description}</div></div>
            )}
            {detail.rationale && (
              <div style={{ marginBottom: 12 }}><span className="muted" style={{ fontSize: 12 }}>Rationale</span><div style={{ fontSize: 13 }} dangerouslySetInnerHTML={{ __html: detail.rationale }} /></div>
            )}
            {detail.compensating_controls && (
              <div style={{ marginBottom: 16 }}><span className="muted" style={{ fontSize: 12 }}>Compensating controls</span><div style={{ fontSize: 13 }}>{detail.compensating_controls}</div></div>
            )}

            <RecordPanels model="exception" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit exception — ${editing.reference}` : "Add item (Exceptions)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "validity", label: "Validity", content: validityTab },
            { id: "links", label: "Compensating & Links", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create exception"}
        />
      )}
    </>
  );
}

export default function ExceptionsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ExceptionsInner />
    </Suspense>
  );
}
