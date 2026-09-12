"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { api, apiCall, type Policy as PolicyBase, type PolicyAckStatus, type PolicyLink } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFilterParams, type FilterSpec } from "@/lib/useFilterParams";
import { useFormat } from "@/lib/format";
import { confirmDeleteWithImpact, WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";
import { deleteEach, deleteErrorText, toastDeleteSummary } from "@/lib/bulkDelete";
import type { LookupRef, UserRef } from "@/lib/masterData";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import WorkflowFields from "@/components/WorkflowFields";
import ArchivedRecords from "@/components/ArchivedRecords";
import DataTable, { type Column } from "@/components/DataTable";
import BulkEditBar from "@/components/BulkEditBar";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import AsyncSelect, { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import RelatedChips from "@/components/RelatedChips";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";
import { titleCase } from "@/lib/text";

const POLICY_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  published: "low",
  approved: "info",
  under_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

/** The only statuses an edit may set. Under review, approved and published come from the
 *  approval lifecycle (Submit for review → Approve) and the Publish button. */
const EDITABLE_STATUS = opts(["draft", "retired"]);
const isEditableStatus = (s: string) => s === "draft" || s === "retired";
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const DOCTYPE = opts(["policy", "standard", "procedure", "guideline"]);

const refToOpt = (x: PolicyLink): AsyncOption => ({ value: x.id, label: x.reference || x.title || x.name || x.id });

/** The shared `Policy` read type plus the picked owner / category (phase 1). The text
 *  columns `owner` / `category` stay as the legacy values. */
type Policy = PolicyBase & {
  owner_id: string | null;
  owner_ref: UserRef | null;
  category_id: string | null;
  category_ref: (LookupRef & { path?: string }) | null;
};

type PolicyReview = {
  id: string;
  planned_date: string;
  actual_review_date: string | null;
  /** Legacy text: the reviewer's name. */
  reviewer: string;
  reviewer_id: string | null;
  reviewer_ref: UserRef | null;
  comments: string;
  created_at: string;
};

/** Register filters, kept in the URL: the dashboard's "policy reviews overdue" opens
 *  `/policies?review=overdue` (approved or published, next review passed). */
const POLICY_FILTERS = { review: ["overdue"] } as const satisfies FilterSpec;

const categoryText = (p: Pick<Policy, "category" | "category_ref">) =>
  p.category_ref ? p.category_ref.path || p.category_ref.label : p.category || "";
const personText = (u: UserRef | null | undefined, fallback?: string) => (u ? u.full_name || u.email : fallback || "");
const workflowLabel = (s: string) => WORKFLOW_STATE_LABEL[s as WorkflowStateKey] ?? cap(s);
/** Publishing needs an approved policy (the server answers 409 otherwise). */
const canPublish = (p: Policy) => p.status !== "published" && (p.workflow_status === "approved" || p.status === "approved");

// GET /policies/{id} also returns reverse graph links not present on the list `Policy` type.
type PolicyDetail = Policy & {
  exceptions?: PolicyLink[];
  projects?: PolicyLink[];
  goals?: PolicyLink[];
  processing_activities?: PolicyLink[];
};

type FormState = {
  title: string;
  summary: string;
  owner_id: string | null;
  category_id: string | null;
  /** Phase 2: the approving committee, effective date, the policy this replaces, and
   *  who it applies to. */
  approving_authority_id: string;
  effective_date: string;
  supersedes: AsyncOption | null;
  business_unit_ids: AsyncOption[];
  role_ids: AsyncOption[];
  /** "draft" / "retired", or "" to keep a lifecycle status (under review, approved, published). */
  status: string;
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
  title: "", summary: "", owner_id: null, category_id: null,
  approving_authority_id: "", effective_date: "", supersedes: null, business_unit_ids: [], role_ids: [],
  status: "draft", review_frequency: "annual",
  document_type: "policy", version: "1.0", use_attachments: false, url: "", body: "",
  related_ids: [], controls_ids: [], requirements_ids: [], risks_ids: [],
};

function fromPolicy(p: Policy): FormState {
  return {
    title: p.title, summary: p.summary || "", owner_id: p.owner_id ?? null, category_id: p.category_id ?? null,
    approving_authority_id: p.approving_authority_id || "",
    effective_date: p.effective_date || "",
    supersedes: p.supersedes_ref ? refToOpt(p.supersedes_ref) : null,
    business_unit_ids: (p.business_units ?? []).map(refToOpt),
    role_ids: (p.roles ?? []).map(refToOpt),
    status: isEditableStatus(p.status) ? p.status : "", review_frequency: p.review_frequency,
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
    title: f.title, summary: f.summary, owner_id: f.owner_id, category_id: f.category_id,
    approving_authority_id: f.approving_authority_id || null,
    effective_date: f.effective_date || null,
    supersedes_id: f.supersedes?.value ?? null,
    business_unit_ids: f.business_unit_ids.map((o) => o.value),
    role_ids: f.role_ids.map((o) => o.value),
    // Only draft / retired are ever sent; a lifecycle status is left as it is.
    ...(f.status ? { status: f.status } : {}),
    review_frequency: f.review_frequency,
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
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const { formatDate } = useFormat();
  const [publishing, setPublishing] = useState(false);

  // Review cycle of the open policy: GET/POST /policies/{id}/reviews.
  const [reviews, setReviews] = useState<PolicyReview[]>([]);
  const [reviewDate, setReviewDate] = useState("");
  const [reviewer, setReviewer] = useState<UserRef | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);

  // Acknowledgement targeting of the open policy, and the committee / role choices.
  const [ackStatus, setAckStatus] = useState<PolicyAckStatus | null>(null);
  const [options, setOptions] = useState<{ committees: PolicyLink[]; roles: PolicyLink[] }>({ committees: [], roles: [] });
  useEffect(() => {
    api.policyOptions().then(setOptions).catch(() => {});
  }, []);

  const [editing, setEditing] = useState<Policy | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const filters = useFilterParams(POLICY_FILTERS);
  const fetchPolicies = useCallback((qs: string) => apiCall<PagedList<Policy>>("GET", `/policies?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<PolicyDetail>("GET", `/policies/${id}`).then(setDetail).catch(() => setDetail(null));
    apiCall<PolicyReview[]>("GET", `/policies/${id}/reviews`).then(setReviews).catch(() => setReviews([]));
    api.policyAckStatus(id).then(setAckStatus).catch(() => setAckStatus(null));
  }, []);
  useEffect(() => {
    setReviewDate(""); setReviewer(null); setReviewNote("");
    if (openId) loadDetail(openId); else { setDetail(null); setReviews([]); setAckStatus(null); }
  }, [openId, loadDetail]);

  // server typeahead pickers
  const searchPolicies = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/policies?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.filter((p) => p.id !== editing?.id).map((p) => ({ value: p.id, label: p.title, sub: p.reference })));
  const searchControls = (q: string) => apiCall<PagedList<{ id: string; name: string; reference: string }>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((c) => ({ value: c.id, label: c.name, sub: c.reference })));
  const searchRequirements = (q: string) => apiCall<{ id: string; reference: string; title: string; framework: string }[]>("GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`).then((rows) => rows.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));
  const searchRisks = (q: string) => apiCall<PagedList<{ id: string; title: string; reference: string }>>("GET", `/risks?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map((x) => ({ value: x.id, label: x.title, sub: x.reference })));
  // The unit picker feed needs only a sign-in (GET /business-units needs org:read).
  const searchUnits = (q: string) => apiCall<{ id: string; name: string; path?: string }[]>("GET", `/pickers/business-units?search=${encodeURIComponent(q)}`).then((rows) => rows.slice(0, 30).map((x) => ({ value: x.id, label: x.name, sub: x.path && x.path !== x.name ? x.path : undefined })));
  const searchRoles = (q: string) => Promise.resolve(
    options.roles.filter((r) => (r.name || "").toLowerCase().includes(q.trim().toLowerCase())).map((r) => ({ value: r.id, label: r.name || r.id })),
  );
  const committeeOptions: Option[] = options.committees.map((c) => ({ value: c.id, label: c.reference ? `${c.name} (${c.reference})` : c.name || c.id }));
  if (editing?.approving_authority_ref && !committeeOptions.some((o) => o.value === editing.approving_authority_ref?.id)) {
    const c = editing.approving_authority_ref;
    committeeOptions.push({ value: c.id, label: c.name || c.reference || c.id });
  }

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
    if (!(await confirmDeleteWithImpact("policy", p.id, p.reference ? `${p.reference} — ${p.title}` : p.title))) return;
    try {
      await apiCall<unknown>("DELETE", `/policies/${p.id}`);
      if (openId === p.id) setOpenId(null);
      reload(); toast(`Archived ${p.reference || p.title}`);
    } catch (e) { toast(deleteErrorText(e, "Failed to delete the policy"), "error"); }
  }
  async function removeMany(rowsToDelete: Policy[], clear: () => void) {
    const ok = await confirmDialog({
      title: `Delete ${rowsToDelete.length} polic${rowsToDelete.length === 1 ? "y" : "ies"}?`,
      message: "They are archived, not erased: links from other records are kept, they can be restored from Archived, and the activity trail records who removed them.",
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    const res = await deleteEach(rowsToDelete, (p) => apiCall("DELETE", `/policies/${p.id}`));
    clear();
    reload();
    toastDeleteSummary(res, "policy");
  }
  async function publish(p: Policy) {
    const ok = await confirmDialog({
      title: `Publish ${p.reference || p.title}?`,
      message: "Publishing makes the approved version binding on staff and opens it for acknowledgment. The person who wrote the policy cannot publish it.",
      confirmLabel: "Publish",
    });
    if (!ok) return;
    setPublishing(true);
    try {
      await apiCall<Policy>("POST", `/policies/${p.id}/publish`);
      loadDetail(p.id); reload(); toast(`Published ${p.reference || p.title}`);
    } catch (e) { toast(e instanceof Error ? e.message : "Could not publish the policy", "error"); }
    finally { setPublishing(false); }
  }
  async function scheduleReview(p: Policy) {
    if (!reviewDate) return;
    setReviewBusy(true);
    try {
      await apiCall("POST", `/policies/${p.id}/reviews`, {
        planned_date: reviewDate, reviewer_id: reviewer?.id ?? null, comments: reviewNote.trim(),
      });
      setReviewDate(""); setReviewer(null); setReviewNote("");
      loadDetail(p.id); reload(); toast("Review scheduled");
    } catch (e) { toast(e instanceof Error ? e.message : "Could not schedule the review", "error"); }
    finally { setReviewBusy(false); }
  }
  async function completeReview(p: Policy, r: PolicyReview) {
    const ok = await confirmDialog({
      title: "Mark this review done?",
      message: "Records today as the review date and schedules the next review from the policy's review frequency.",
      confirmLabel: "Mark done",
    });
    if (!ok) return;
    setReviewBusy(true);
    try {
      await apiCall("POST", `/policies/${p.id}/reviews/${r.id}/complete`, { comments: r.comments });
      loadDetail(p.id); reload(); toast("Review completed");
    } catch (e) { toast(e instanceof Error ? e.message : "Could not complete the review", "error"); }
    finally { setReviewBusy(false); }
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
    { key: "status", header: "Status", sortable: true, render: (p) => <Badge tone={POLICY_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge>, text: (p) => cap(p.status) },
    { key: "workflow_status", header: "Approval", render: (p) => <span className="muted">{workflowLabel(p.workflow_status)}</span>, text: (p) => workflowLabel(p.workflow_status) },
    { key: "owner", header: "Owner", sortable: true, render: (p) => <span className="muted"><UserName user={p.owner_ref} fallback={p.owner} /></span>, text: (p) => personText(p.owner_ref, p.owner) },
    { key: "category", header: "Category", sortable: true, render: (p) => <span className="muted">{categoryText(p) || "—"}</span>, text: (p) => categoryText(p) },
    { key: "links", header: "Links", align: "center", render: (p) => <span className="muted">{linkCount(p) || "—"}</span> },
    { key: "next_review_date", header: "Reviews", sortable: true, render: (p) => (p.is_review_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{formatDate(p.next_review_date)}</span>), text: (p) => (p.next_review_date ? formatDate(p.next_review_date) : "") },
    { key: "effective_date", header: "Effective", hidden: true, render: (p) => <span className="muted">{formatDate(p.effective_date)}</span>, text: (p) => (p.effective_date ? formatDate(p.effective_date) : "") },
    { key: "approving_authority", header: "Approved by", hidden: true, render: (p) => <span className="muted">{p.approving_authority_ref?.name || "—"}</span>, text: (p) => p.approving_authority_ref?.name || "" },
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
        <Field label="Owner / GRC Contact" help="Accountable for the policy's content and its reviews.">
          <UserPicker
            value={f.owner_id}
            onChange={(id) => set("owner_id", id)}
            selected={editing?.owner_ref}
            legacyText={editing?.owner_id ? null : editing?.owner}
            placeholder="Search people…"
          />
        </Field>
        <Field label="Category" help="From the organisation's policy category list.">
          <LookupSelect
            lookupKey="policy_category"
            value={f.category_id}
            onChange={(id) => set("category_id", id)}
            legacyText={editing?.category_id ? null : editing?.category}
            placeholder="Choose a category…"
            allowCreate
          />
        </Field>
      </div>
      <div className="field-row">
        <Field
          label="Status"
          help={
            editing && !isEditableStatus(editing.status)
              ? `${cap(editing.status)} comes from approval and Publish, not from editing. You can still return it to draft or retire it.`
              : editing
                ? "Under review, approved and published come from approval (Submit for review → Approve) and the Publish button in the policy's detail view."
                : "A new policy starts as a draft. Once saved, submit it for review from its detail view."
          }
        >
          {editing ? (
            <Select
              value={f.status}
              onChange={(v) => set("status", v)}
              options={EDITABLE_STATUS}
              placeholder={`Keep as ${cap(editing.status)}`}
            />
          ) : (
            <div style={{ paddingTop: 6 }}><Badge tone="neutral">Draft</Badge></div>
          )}
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

  const governanceTab = (
    <>
      <div className="field-row">
        <Field label="Approving authority" help="The board or committee that approves this policy (Governance → committees).">
          <Select
            value={f.approving_authority_id}
            onChange={(v) => set("approving_authority_id", v)}
            options={committeeOptions}
            placeholder={committeeOptions.length ? "Choose a committee…" : "No committees yet"}
          />
        </Field>
        <Field label="Effective date" help="When it takes effect. Leave empty to use the publication date; it can't be earlier than the approval.">
          <input className="input" type="date" value={f.effective_date} onChange={(e) => set("effective_date", e.target.value)} />
        </Field>
      </div>
      <Field label="Supersedes" help="The policy this one replaces. When this one is published, that one is retired automatically.">
        <AsyncSelect
          search={searchPolicies}
          value={f.supersedes?.value ?? null}
          selectedLabel={f.supersedes?.label}
          onChange={(v, o) => set("supersedes", v ? { value: v, label: o?.label || f.supersedes?.label || v } : null)}
          placeholder="Search policies…"
        />
      </Field>
      {editing?.superseded_by?.length ? (
        <div style={{ marginBottom: 12 }}>
          <RelatedChips label="Superseded by" items={editing.superseded_by} href="/policies" />
        </div>
      ) : null}
      <Field label="Applies to — business units" help="Recorded for reporting. People aren't linked to business units, so this doesn't change who is asked to acknowledge.">
        <AsyncMultiSelect search={searchUnits} value={f.business_unit_ids} onChange={(v) => set("business_unit_ids", v)} />
      </Field>
      <Field label="Applies to — roles" help="Members of these roles are asked to acknowledge the policy. None: everyone is.">
        <AsyncMultiSelect search={searchRoles} value={f.role_ids} onChange={(v) => set("role_ids", v)} placeholder="Search roles…" />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Related Policies" help="Cross-link policies that reference or depend on this one. A replacement goes under Governance → Supersedes.">
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
        toolbarRight={<ArchivedRecords entityType="policy" noun="policies" onRestored={reload} refreshKey={refreshKey} />}
        bulkActions={(rows, clear) => (
          <>
            <BulkEditBar entityType="policy" rows={rows} onDone={() => { clear(); reload(); }} />
            <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
          </>
        )}
        filters={filters.values}
        onApplyFilters={filters.replace}
        toolbarLeft={
          <label className="label" style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }} title="Approved or published, and the next review date has passed">
            <input type="checkbox" checked={filters.values.review === "overdue"} onChange={(e) => filters.set("review", e.target.checked ? "overdue" : undefined)} /> Review overdue
          </label>
        }
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
        aside={detail ? <RecordPanels model="policy" entityId={detail.id} /> : null}
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? detail.reference || detail.title : "…"}
        subtitle={detail ? `${cap(detail.document_type)} v${detail.version}${personText(detail.owner_ref, detail.owner) ? " · " + personText(detail.owner_ref, detail.owner) : ""}` : ""}
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
              <div><div className="muted" style={{ fontSize: 12 }}>Owner</div><div style={{ marginTop: 4 }}><UserName user={detail.owner_ref} fallback={detail.owner} /></div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Category</div><div style={{ marginTop: 4 }}>{categoryText(detail) || "—"}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Next review</div><div style={{ marginTop: 4 }}>{formatDate(detail.next_review_date)}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Last review</div><div style={{ marginTop: 4 }}>{formatDate(detail.last_review_date)}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Published</div><div style={{ marginTop: 4 }}>{formatDate(detail.published_at)}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Effective</div><div style={{ marginTop: 4 }}>{formatDate(detail.effective_date)}</div></div>
              <div><div className="muted" style={{ fontSize: 12 }}>Approving authority</div><div style={{ marginTop: 4 }}>{detail.approving_authority_ref ? detail.approving_authority_ref.name || detail.approving_authority_ref.reference : "—"}</div></div>
            </div>

            {(detail.supersedes_ref || (detail.superseded_by?.length ?? 0) > 0) && (
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-start", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
                {detail.supersedes_ref && (
                  <RelatedChips label="Supersedes" items={[detail.supersedes_ref]} href="/policies" />
                )}
                {(detail.superseded_by?.length ?? 0) > 0 && (
                  <div>
                    <RelatedChips label="Superseded by" items={detail.superseded_by} href="/policies" />
                    {detail.status === "retired" && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Retired when its successor was published.</div>}
                  </div>
                )}
              </div>
            )}

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <strong style={{ fontSize: 13, display: "block", marginBottom: 10 }}>Approval &amp; publication</strong>
              <WorkflowFields entityType="policy" entityId={detail.id} onChanged={() => { loadDetail(detail.id); reload(); }} />
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                {detail.status === "published" ? (
                  <span style={{ fontSize: 13 }}>
                    <Badge tone="low">Published</Badge>{" "}
                    <span className="muted">on {formatDate(detail.published_at)} — staff can acknowledge it.</span>
                  </span>
                ) : (
                  <>
                    <button
                      type="button"
                      className="btn sm"
                      onClick={() => publish(detail)}
                      disabled={!canPublish(detail) || publishing}
                      title={canPublish(detail) ? undefined : "Approve the policy first"}
                    >
                      {publishing ? "Publishing…" : "Publish"}
                    </button>
                    <span className="muted" style={{ fontSize: 12.5 }}>
                      {canPublish(detail)
                        ? "Approved — publishing makes it binding on staff. Its author cannot publish it."
                        : "Publish opens once the policy is approved: submit it for review above, and an independent approver approves it."}
                    </span>
                  </>
                )}
              </div>
            </div>

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <strong style={{ fontSize: 13 }}>Reviews</strong>
              <form
                style={{ display: "flex", gap: 8, margin: "10px 0 12px", alignItems: "flex-end", flexWrap: "wrap" }}
                onSubmit={(e) => { e.preventDefault(); scheduleReview(detail); }}
              >
                <div style={{ width: 150 }}>
                  <label className="label" htmlFor="review-date">Planned for</label>
                  <input id="review-date" className="input" type="date" value={reviewDate} onChange={(e) => setReviewDate(e.target.value)} required />
                </div>
                <div style={{ flex: "1 1 190px" }}>
                  <label className="label">Reviewer</label>
                  <UserPicker value={reviewer?.id ?? null} selected={reviewer} onChange={(_id, ref) => setReviewer(ref ?? null)} placeholder="Who reviews it…" />
                </div>
                <div style={{ flex: "1 1 160px" }}>
                  <label className="label" htmlFor="review-note">Note</label>
                  <input id="review-note" className="input" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="Scope of the review (optional)" />
                </div>
                <button className="btn sm" disabled={!reviewDate || reviewBusy}>Schedule</button>
              </form>
              {reviews.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th style={{ width: 110 }}>Planned</th><th>Reviewer</th><th style={{ width: 110 }}>Done</th><th>Note</th><th style={{ width: 90 }} aria-label="Actions" /></tr>
                    </thead>
                    <tbody>
                      {reviews.map((r) => (
                        <tr key={r.id}>
                          <td className="muted">{formatDate(r.planned_date)}</td>
                          <td><UserName user={r.reviewer_ref} fallback={r.reviewer} /></td>
                          <td className="muted">{r.actual_review_date ? formatDate(r.actual_review_date) : "Open"}</td>
                          <td style={{ fontSize: 13 }}>{r.comments || <span className="muted">—</span>}</td>
                          <td style={{ textAlign: "right" }}>
                            {!r.actual_review_date && (
                              <button type="button" className="btn secondary sm" onClick={() => completeReview(detail, r)} disabled={reviewBusy}>Mark done</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <span className="muted" style={{ fontSize: 12.5 }}>No reviews scheduled yet.</span>}
            </div>

            <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
              <strong style={{ fontSize: 13 }}>Applicability &amp; acknowledgement</strong>
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap", margin: "10px 0" }}>
                <RelatedChips label="Business units" items={detail.business_units} href="/business-units" />
                <div style={{ minWidth: 140 }}>
                  <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Roles</div>
                  <div style={{ marginTop: 3, display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {detail.roles?.length ? detail.roles.map((r) => <span key={r.id} className="chip">{r.name}</span>) : <span className="muted">— everyone</span>}
                  </div>
                </div>
              </div>
              {ackStatus ? (
                <>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", fontSize: 13, marginBottom: 6 }}>
                    <Badge tone={ackStatus.pending === 0 && ackStatus.total > 0 ? "low" : "info"}>
                      {ackStatus.acknowledged} of {ackStatus.total} acknowledged
                    </Badge>
                    {ackStatus.outside_scope > 0 && (
                      <span className="muted">+{ackStatus.outside_scope} from people outside the scope</span>
                    )}
                  </div>
                  <p className="muted" style={{ fontSize: 12.5, margin: "0 0 10px" }}>{ackStatus.note}</p>
                  {ackStatus.users.length ? (
                    <div className="table-wrap" style={{ maxHeight: 280, overflowY: "auto" }}>
                      <table>
                        <thead>
                          <tr><th>Person</th><th>Roles</th><th style={{ width: 150 }}>Acknowledged</th></tr>
                        </thead>
                        <tbody>
                          {ackStatus.users.map((u) => (
                            <tr key={u.user_id}>
                              <td><span title={u.email}>{u.full_name || u.email}</span></td>
                              <td className="muted" style={{ fontSize: 12.5 }}>{u.roles.join(", ") || "—"}</td>
                              <td>{u.acknowledged ? <span><Badge tone="low">Yes</Badge> <span className="muted" style={{ fontSize: 12 }}>{formatDate(u.acknowledged_at)}</span></span> : <Badge tone="medium">Pending</Badge>}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : <span className="muted" style={{ fontSize: 12.5 }}>Nobody is in scope: the policy's roles have no active members.</span>}
                </>
              ) : <span className="muted" style={{ fontSize: 12.5 }}>Acknowledgement status unavailable.</span>}
            </div>

            <strong style={{ fontSize: 13 }}>Related records</strong>
            <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 14 }}>
              <RelatedChips label="Controls" items={detail.controls} href="/controls" />
              <RelatedChips label="Compliance requirements" items={detail.requirements} href="/compliance" />
              <RelatedChips label="Risks" items={detail.risks} href="/risks" />
              <RelatedChips label="Related policies" items={detail.related} href="/policies" />
              <RelatedChips label="Exceptions" items={detail.exceptions} href="/exceptions" />
              <RelatedChips label="Projects" items={detail.projects} href="/projects" />
              <RelatedChips label="Goals" items={detail.goals} href="/goals" />
              <RelatedChips label="Processing activities" items={detail.processing_activities} href="/privacy" />
            </div>

          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit policy — ${editing.reference || editing.title}` : "Add item (Policies)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "content", label: "Policy Content", content: contentTab },
            { id: "governance", label: "Governance & Applicability", content: governanceTab },
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
