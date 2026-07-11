"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall, type Policy, type PolicyLink } from "@/lib/api";
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
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

const POLICY_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  published: "low",
  approved: "info",
  under_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "under_review", "approved", "published", "retired"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const DOCTYPE = opts(["policy", "standard", "procedure", "guideline"]);

const refToOpt = (x: PolicyLink): AsyncOption => ({ value: x.id, label: x.reference || x.title || x.name || x.id });

type FormState = {
  title: string;
  summary: string;
  owner: string;
  category: string;
  status: string;
  workflow_status: string;
  review_frequency: string;
  document_type: string;
  version: string;
  use_attachments: boolean;
  url: string;
  body: string;
  related_ids: AsyncOption[];
  controls_ids: AsyncOption[];
  requirements_ids: AsyncOption[];
  risks_ids: AsyncOption[];
};

const BLANK: FormState = {
  title: "", summary: "", owner: "", category: "",
  status: "draft", workflow_status: "draft", review_frequency: "annual",
  document_type: "policy", version: "1.0", use_attachments: false, url: "", body: "",
  related_ids: [], controls_ids: [], requirements_ids: [], risks_ids: [],
};

function fromPolicy(p: Policy): FormState {
  return {
    title: p.title, summary: p.summary || "", owner: p.owner || "", category: p.category || "",
    status: p.status, workflow_status: p.workflow_status, review_frequency: p.review_frequency,
    document_type: p.document_type, version: p.version, use_attachments: p.use_attachments,
    url: p.url || "", body: p.body || "",
    related_ids: p.related.map(refToOpt),
    controls_ids: p.controls.map(refToOpt),
    requirements_ids: p.requirements.map(refToOpt),
    risks_ids: p.risks.map(refToOpt),
  };
}

function toPayload(f: FormState): Record<string, unknown> {
  return {
    title: f.title, summary: f.summary, owner: f.owner, category: f.category,
    status: f.status, workflow_status: f.workflow_status, review_frequency: f.review_frequency,
    document_type: f.document_type, version: f.version, use_attachments: f.use_attachments,
    url: f.url, body: f.body,
    related_ids: f.related_ids.map((o) => o.value),
    controls_ids: f.controls_ids.map((o) => o.value),
    requirements_ids: f.requirements_ids.map((o) => o.value),
    risks_ids: f.risks_ids.map((o) => o.value),
  };
}

const linkCount = (p: Policy) => p.related.length + p.controls.length + p.requirements.length + p.risks.length;

/* ================================================================ page ===== */
function PoliciesInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Policy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [editing, setEditing] = useState<Policy | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchPolicies = useCallback((qs: string) => apiCall<PagedList<Policy>>("GET", `/policies?${qs}`), []);
  const loadDetail = useCallback((id: string) => { apiCall<Policy>("GET", `/policies/${id}`).then(setDetail).catch(() => setDetail(null)); }, []);
  useEffect(() => { if (openId) loadDetail(openId); else setDetail(null); }, [openId, loadDetail]);

  // server typeahead pickers
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.filter((p) => p.id !== editing?.id).map((p) => ({ value: p.id, label: p.title, sub: p.reference })));
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((c) => ({ value: c.id, label: c.name, sub: c.reference })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(p: Policy) { setEditing(p); setF(fromPolicy(p)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Policy>("PATCH", `/policies/${editing.id}`, payload);
      else await apiCall<Policy>("POST", "/policies", payload);
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Policy created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save policy"); }
    finally { setSaving(false); }
  }
  async function remove(p: Policy) {
    if (!(await confirmDialog({ title: `Delete policy ${p.reference || p.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<unknown>("DELETE", `/policies/${p.id}`);
      if (openId === p.id) setOpenId(null);
      reload(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete"); }
  }
  async function acknowledge(p: Policy) {
    setError(null);
    try {
      await apiCall<unknown>("POST", `/policies/${p.id}/acknowledge`);
      if (openId) loadDetail(openId); reload(); toast(`You acknowledged ${p.reference || p.title}`);
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to acknowledge"); }
  }

  const columns: Column<Policy>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (p) => <span className="ref">{p.reference || "—"}</span> },
    { key: "title", header: "Name", sortable: true, render: (p) => <span className="cell-title">{p.title}</span> },
    { key: "document_type", header: "Type", sortable: true, render: (p) => <Badge tone="neutral" plain>{cap(p.document_type)}</Badge> },
    { key: "version", header: "Version", sortable: true, render: (p) => <span className="muted">v{p.version}</span> },
    { key: "status", header: "Status", sortable: true, render: (p) => <Badge tone={POLICY_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge> },
    { key: "owner", header: "Owner", sortable: true, render: (p) => <span className="muted">{p.owner || "—"}</span> },
    { key: "links", header: "Links", align: "center", render: (p) => <span className="muted">{linkCount(p) || "—"}</span> },
    { key: "next_review_date", header: "Reviews", sortable: true, render: (p) => (p.is_review_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{p.next_review_date || "—"}</span>) },
    { key: "acks", header: "Acks", align: "center", render: (p) => <Badge tone="info" plain>{p.acknowledgment_count}</Badge> },
    { key: "actions", header: "", render: (p) => <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(p)}>Edit</button><button className="btn secondary sm" onClick={() => acknowledge(p)}><IconCheck width={14} height={14} /> Ack</button><button className="btn secondary sm" onClick={() => remove(p)}>Delete</button></div> },
  ];

  const generalTab = (
    <>
      <Field label="Name" required help="For example: Encryption Standards, Security Policy, HR Policies, etc.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Data Retention Policy" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.summary} onChange={(v) => set("summary", v)} rows={3} placeholder="Short summary of the policy's purpose and scope." />
      </Field>
      <div className="field-row">
        <Field label="Owner / GRC Contact">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="CISO" />
        </Field>
        <Field label="Category">
          <TextInput value={f.category} onChange={(v) => set("category", v)} placeholder="Security" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Review Frequency">
          <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
        </Field>
      </div>
    </>
  );

  const contentTab = (
    <>
      <div className="field-row">
        <Field label="Document Type">
          <Select value={f.document_type} onChange={(v) => set("document_type", v)} options={DOCTYPE} />
        </Field>
        <Field label="Version">
          <TextInput value={f.version} onChange={(v) => set("version", v)} placeholder="1.0" />
        </Field>
      </div>
      <Field label="Document Source" help="Toggle on to reference an uploaded file or external URL instead of inline content.">
        <Toggle checked={f.use_attachments} onChange={(v) => set("use_attachments", v)} label="Use external document / attachment" />
      </Field>
      {f.use_attachments && (
        <Field label="External Document URL">
          <TextInput value={f.url} onChange={(v) => set("url", v)} placeholder="https://docs.example.com/policy.pdf" />
        </Field>
      )}
      <Field label="Document Content">
        <RichText value={f.body} onChange={(v) => set("body", v)} />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Related Policies" help="Cross-link policies that supersede, reference or depend on this one.">
        <AsyncMultiSelect search={searchPolicies} value={f.related_ids} onChange={(v) => set("related_ids", v)} />
      </Field>
      <Field label="Related Controls" help="Controls that implement or enforce this policy.">
        <AsyncMultiSelect search={searchControls} value={f.controls_ids} onChange={(v) => set("controls_ids", v)} />
      </Field>
      <Field label="Requirements" help="Framework requirements this policy addresses.">
        <AsyncMultiSelect search={searchRequirements} value={f.requirements_ids} onChange={(v) => set("requirements_ids", v)} />
      </Field>
      <Field label="Related Risks" help="Risks this policy mitigates or addresses.">
        <AsyncMultiSelect search={searchRisks} value={f.risks_ids} onChange={(v) => set("risks_ids", v)} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Policy Management</h1>
          <p>Repository for policies with document content, versioning, review cycles, cross-links and acknowledgments.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="policies" label="Policies" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add policy
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Policy>
        columns={columns}
        fetcher={fetchPolicies}
        rowKey={(p) => p.id}
        onRowClick={(p) => setOpenId(p.id)}
        activeKey={openId}
        searchPlaceholder="Search policies by name or reference…"
        defaultSort={{ by: "reference", dir: "asc" }}
        emptyMessage="No policies yet. Create your first policy to build the repository."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? detail.reference || detail.title : "…"}
        subtitle={detail ? `${cap(detail.document_type)} v${detail.version}${detail.owner ? " · " + detail.owner : ""}` : ""}
        width={720}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => acknowledge(detail)}><IconCheck width={14} height={14} /> Ack</button>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              <Badge tone={POLICY_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              <Badge tone="info" plain>{detail.acknowledgment_count} acks</Badge>
              {linkCount(detail) > 0 && <Badge tone="neutral" plain>{linkCount(detail)} links</Badge>}
              {detail.is_review_overdue && <Badge tone="high">Review overdue</Badge>}
            </div>
            {detail.summary && <p style={{ marginBottom: 14 }}>{detail.summary}</p>}
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <div><div className="muted" style={{ fontSize: 12 }}>Category</div><div style={{ marginTop: 4 }}>{detail.category || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Next review</div><div style={{ marginTop: 4 }}>{detail.next_review_date || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Last review</div><div style={{ marginTop: 4 }}>{detail.last_review_date || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Published</div><div style={{ marginTop: 4 }}>{detail.published_at || "—"}</div></div>
            </div>
            <RecordPanels model="policy" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit policy — ${editing.reference || editing.title}` : "Add item (Policies)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "content", label: "Policy Content", content: contentTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create policy"}
        />
      )}
    </>
  );
}

export default function PoliciesPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <PoliciesInner />
    </Suspense>
  );
}
