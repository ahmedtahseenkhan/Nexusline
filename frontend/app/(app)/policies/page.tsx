"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { api, apiCall, type Policy as PolicyBase, type PolicyAckStatus, type PolicyLink } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import { useFilterParams, type FilterSpec } from "@/lib/useFilterParams";
import { useFormat } from "@/lib/format";
import { useHasPermission } from "@/lib/tenantSettings";
import { confirmDeleteWithImpact, WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";
import { deleteEach, deleteErrorText, toastDeleteSummary } from "@/lib/bulkDelete";
import type { LookupRef, UserRef } from "@/lib/masterData";
import UserPicker, { UserName } from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
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
import RichText, { RichTextView } from "@/components/RichText";
import { useCustomFieldFacts } from "@/components/CustomFieldsPanel";
import { useCustomFieldForm } from "@/components/useCustomFieldForm";
import { useIsoLayoutEffect } from "@/components/record/useIsoLayoutEffect";
import {
  Disclosure, Fact, FactGrid, FactList, LabelledSearch, OpenPoints, PrimaryAction, RecordSection, RelatedGroups, SectionNav, SummaryBand,
  approvalHintFor, approvalMetaItem, pickPrimary, primaryLabel, relatedCount, rowAction, rowLabel, useRecordCtx, useRecordGovernanceData,
  useRecordSections, withBaseMoreItems, type FactItem, type MetaItem, type PrimaryCandidate, type RelatedGroup,
} from "@/components/record";
import { Field, TextInput, TextArea, Select, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";
import { titleCase } from "@/lib/text";
import { htmlToText, safeLinkUrl } from "@/lib/sanitize";
import { sentenceCase, textOnlyPerson, uniqueLabels } from "@/lib/record/text";
import {
  POLICY_CLEAR_TEXT, policyAckTone, policyCanPublish, policyPublishedUnapproved, policyExceptionNote, policyHeadline, policyOpenPoints, policyPublicationRow,
  policyReviewCycleText, policyTiles, type PolicyExceptionRef, type PolicyInput,
} from "@/lib/record/policy";
import Segs from "@/components/record/Segs";
import type { PointAction } from "@/lib/record/types";

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
const canPublish = (p: Policy) => policyCanPublish(p);

// GET /policies/{id} also returns reverse graph links not present on the list `Policy` type.
type PolicyDetail = Policy & {
  created_at?: string;
  /** Each carries its status and expiry with B3 (absent on an older API). */
  exceptions?: PolicyExceptionRef[];
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

/* The policy's judgement wording — tiles, open points, headline, the publication and
   review-cycle sentences — lives in lib/record/policy.ts (pinned by fixtures). */

const BODY_LINES = 12;
const BODY_LINE_PX = 22;

/** The policy text, collapsed after 12 lines with "Read full policy". Stored rich text is
 *  rendered through the shared sanitiser (RichTextView); `record-print-full` prints it
 *  whole whatever the clamp (record-page-spec v1.1 D4). */
function PolicyBody({ html }: { html: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);
  useIsoLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    setOverflows(el.scrollHeight > el.clientHeight + 1);
  }, [html, open]);
  return (
    <div style={{ marginBottom: 12 }}>
      <RichTextView
        ref={ref}
        html={html}
        className="pol-body record-print-full"
        style={{
          maxWidth: "76ch", fontSize: 14, lineHeight: `${BODY_LINE_PX}px`, overflowWrap: "anywhere",
          ...(open ? {} : { maxHeight: BODY_LINES * BODY_LINE_PX, overflow: "hidden" }),
        }}
      />
      {(overflows || open) && (
        <button type="button" className="rec-link record-print-hide" aria-expanded={open} onClick={() => setOpen((v) => !v)} style={{ marginTop: 6 }}>
          {open ? "Show less" : "Read full policy"}
        </button>
      )}
    </div>
  );
}

/** A linked record as the kit's chip: mono reference, then the name. */
function RefChip({ x, href }: { x: PolicyLink; href: string }) {
  const name = (x.title || x.name || "").trim();
  const full = [x.reference, name].filter(Boolean).join(" ") || x.id;
  return (
    <Link href={`${href}?id=${x.id}`} className="chip chip-link rec-chip" title={full}>
      {x.reference && <span className="ref">{x.reference}</span>}
      {name || (x.reference ? "" : x.id)}
    </Link>
  );
}

/** Labels of the built-in fields a custom field could duplicate (admins get a note). */
const POLICY_BUILT_IN_LABELS = ["Owner", "Category", "Document type", "Version", "Review frequency", "Approving authority", "Effective date"];

/* ================================================================ page ===== */
function PoliciesInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<PolicyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const { formatDate } = useFormat();

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

  // ---- the record page (dossier, record-page-spec §4.5) ----
  const gov = useRecordGovernanceData("policy", detail?.id ?? null, { statusRulesModel: "policy" });
  const canWrite = useHasPermission("policy:write");
  const ctx = useRecordCtx(gov, canWrite);
  const sections = useRecordSections();
  const cfForm = useCustomFieldForm("policy");
  const cf = useCustomFieldFacts("policy", detail?.id, { builtInLabels: POLICY_BUILT_IN_LABELS });
  /** FormModal tab to open on (a header gap, an open point or a "Fill in"). */
  const [editTab, setEditTab] = useState<string | undefined>(undefined);
  const [reviewFormOpen, setReviewFormOpen] = useState(false);
  const reviewTriggerRef = useRef<HTMLButtonElement>(null);
  /** The server's refusal of Publish (e.g. its author), shown in the Publication row. */
  const [publishError, setPublishError] = useState<string | null>(null);
  useEffect(() => { setReviewFormOpen(false); setPublishError(null); }, [openId]);
  /** After any change: the governance (primary, sign-off, rules), the record, the list. */
  const refresh = () => {
    void gov.reload();
    if (openId) loadDetail(openId);
    reload();
  };

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

  function openNew() { setEditing(null); setF(BLANK); cfForm.start(null); setError(null); setEditTab(undefined); setShowForm(true); }
  function openEdit(p: Policy, tab?: string) { setEditing(p); setF(fromPolicy(p)); cfForm.start(p.id); setError(null); setEditTab(tab); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      const saved = editing
        ? await apiCall<Policy>("PATCH", `/policies/${editing.id}`, payload)
        : await apiCall<Policy>("POST", "/policies", payload);
      await cfForm.save(saved.id);
      setShowForm(false); refresh(); void cf.reload(); toast(editing ? "Changes saved" : "Policy created");
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
    setPublishError(null);
    try {
      await apiCall<Policy>("POST", `/policies/${p.id}/publish`);
      refresh(); toast(`Published ${p.reference || p.title}`);
    } catch (e) {
      // 409 (not approved, effective date) or 403 (its author): the reason shows in the
      // Publication row as well as the toast.
      const msg = e instanceof Error ? e.message : "Could not publish the policy";
      setPublishError(msg); toast(msg, "error");
    }
  }
  /** True when the review was scheduled (the form then closes). */
  async function scheduleReview(p: Policy): Promise<boolean> {
    if (!reviewDate) return false;
    setReviewBusy(true);
    try {
      await apiCall("POST", `/policies/${p.id}/reviews`, {
        planned_date: reviewDate, reviewer_id: reviewer?.id ?? null, comments: reviewNote.trim(),
      });
      setReviewDate(""); setReviewer(null); setReviewNote("");
      refresh(); toast("Review scheduled");
      return true;
    } catch (e) { toast(e instanceof Error ? e.message : "Could not schedule the review", "error"); return false; }
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
      refresh(); toast("Review completed");
    } catch (e) { toast(e instanceof Error ? e.message : "Could not complete the review", "error"); }
    finally { setReviewBusy(false); }
  }
  async function acknowledge(p: Policy) {
    try {
      await apiCall<unknown>("POST", `/policies/${p.id}/acknowledge`);
      refresh(); toast(`You acknowledged ${p.reference || p.title}`);
    } catch (e) { toast(e instanceof Error ? e.message : "Failed to acknowledge", "error"); }
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
    {
      key: "actions", header: "", render: (p) => {
        const label = rowLabel(p.reference, p.title);
        return (
          <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
            <button className="btn secondary sm" {...rowAction("Edit", label)} onClick={() => openEdit(p)}>Edit</button>
            <button className="btn secondary sm" {...rowAction("Acknowledge", label)} onClick={() => acknowledge(p)}><IconCheck width={14} height={14} /> Acknowledge</button>
            <button className="btn secondary sm" {...rowAction("Delete", label)} onClick={() => remove(p)}>Delete</button>
          </div>
        );
      },
    },
  ];

  const generalTab = (
    <>
      <Field label="Name" required help="For example: Encryption Standards, Security Policy, HR Policies, etc.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="e.g. Data Retention Policy" required />
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
          <TextInput value={f.version} onChange={(v) => set("version", v)} placeholder="e.g. 1.0" />
        </Field>
      </div>
      <Field label="Document Source" help="Toggle on to reference an uploaded file or external URL instead of inline content.">
        <Toggle checked={f.use_attachments} onChange={(v) => set("use_attachments", v)} label="Use external document / attachment" />
      </Field>
      {f.use_attachments && (
        <Field label="External Document URL">
          <TextInput value={f.url} onChange={(v) => set("url", v)} placeholder="e.g. https://docs.example.com/policy.pdf" />
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

  // ---- dossier: the open policy's header, primary, rail row and sections ----
  const iAmAsked = !!detail && detail.status === "published" && !!gov.me
    && !!ackStatus?.users.some((u) => u.user_id === gov.me?.id && !u.acknowledged);
  const primaryCandidates: PrimaryCandidate[] = detail ? [
    { kind: "workflow", action: "approve" },
    { kind: "workflow", action: "submit" },
    { kind: "custom", label: "Publish", when: canWrite && canPublish(detail), onClick: () => publish(detail) },
    { kind: "custom", label: "Acknowledge", when: iAmAsked, onClick: () => acknowledge(detail) },
    { kind: "attest" },
  ] : [];
  const primary = pickPrimary(primaryCandidates, gov);
  const primaryText = primary ? primaryLabel(primary) : null;
  const policyInput: PolicyInput | null = detail ? { policy: detail, ack: ackStatus, reviews, primaryLabel: primaryText } : null;

  function openReviewForm() {
    sections.scrollTo("reviews");
    setReviewFormOpen(true);
  }
  /** Open-point fixes only move: scroll, focus, open Edit on a tab or open a form. */
  function handlePoint(a: PointAction) {
    if (!detail) return;
    if (a.kind === "section") sections.scrollTo(a.target);
    else if (a.kind === "edit") openEdit(detail, a.target);
    else if (a.kind === "focus") document.getElementById(a.target)?.focus();
    else if (a.kind === "attest") gov.openAttest();
    else if (a.kind === "open" && a.target === "schedule-review") openReviewForm();
  }

  const reviewCycleText = (p: Policy) => policyReviewCycleText(p, ctx.fmt);

  const ownerText = detail ? personText(detail.owner_ref, detail.owner) : "";
  // Header meta (record-page-spec §4.5, v1.1 D1): slot 1 the document status, slot 2
  // Record approval, then the policy's own items.
  const statusMeta: MetaItem | undefined = detail ? {
    key: "status", label: "Document status",
    // Published while Record approval is still Draft or In review: amber, not the green
    // of a settled publication (the Sign-off card says "Published, not approved").
    value: <Badge tone={policyPublishedUnapproved(detail, ctx.gov.workflowState) ? "medium" : POLICY_TONE[detail.status] || "neutral"} asIs>{sentenceCase(detail.status)}</Badge>,
    hint: "Where the document is: draft, under review, approved, published or retired. Separate from record approval.",
  } : undefined;
  const policyMeta: MetaItem[] = detail ? [
    {
      key: "owner", label: "Owner", value: ownerText || null, hint: "Accountable for the policy's content and its reviews.",
      // Free text with no person picked ("CISO") is a label nobody can be notified at.
      gap: !ownerText ? { text: "Not assigned", fix: canWrite ? { label: "Assign", onClick: () => openEdit(detail, "general") } : undefined }
        : textOnlyPerson(detail.owner_id, detail.owner) ? { text: "Text only", fix: canWrite ? { label: "Pick a person", onClick: () => openEdit(detail, "general") } : undefined }
        : undefined,
    },
    {
      key: "authority", label: "Approving authority",
      value: detail.approving_authority_ref ? detail.approving_authority_ref.name || detail.approving_authority_ref.reference || null : null,
      hint: "The board or committee that approves this policy.",
      gap: detail.approving_authority_ref ? undefined : { text: "Not set", fix: canWrite ? { label: "Name authority", onClick: () => openEdit(detail, "governance") } : undefined },
    },
    {
      key: "effective", label: "Effective",
      value: detail.effective_date ? formatDate(detail.effective_date) : detail.status === "published" ? "On publication" : null,
      hint: "When the policy takes effect. Left empty, publishing sets it to the publication date.",
    },
    {
      key: "review", label: "Next review",
      value: detail.is_review_overdue && detail.next_review_date
        ? <Badge tone="high" asIs>Overdue since {formatDate(detail.next_review_date)}</Badge>
        : detail.next_review_date ? formatDate(detail.next_review_date) : <span className="muted">Not scheduled</span>,
      sub: detail.review_frequency && detail.review_frequency !== "none" ? sentenceCase(detail.review_frequency) : undefined,
      hint: "Attesting the policy records the review and moves this date.",
    },
  ] : [];

  const pubRow = detail ? policyPublicationRow(detail, ctx.fmt, ctx.gov.workflowState) : null;
  const publicationRow = detail && pubRow ? (
    <div className="rec-so-row">
      <div className="k">
        Publication
        {pubRow.state === "published" ? <Badge tone={pubRow.warn ? "medium" : "low"} asIs>{pubRow.warn ? "Published, not approved" : "Published"}</Badge>
          : pubRow.state === "retired" ? <Badge tone="neutral" asIs>Retired</Badge>
          : <Badge hollow asIs>Not published</Badge>}
      </div>
      <div className="d"><Segs segs={pubRow.text} /></div>
      {publishError && <div className="d rec-error" role="alert">{publishError}</div>}
    </div>
  ) : null;

  const detailFacts: FactItem[] = detail ? [
    { key: "category", label: "Category", value: categoryText(detail) || null, tab: "general" },
    { key: "doctype", label: "Document type", value: sentenceCase(detail.document_type), tab: "content" },
    { key: "cycle", label: "Review cycle", value: reviewCycleText(detail), tab: "general" },
    { key: "source", label: "Document source", value: detail.use_attachments ? "External document or attachment" : "Inline text", tab: "content" },
    { key: "created", label: "Created", value: detail.created_at ? formatDate(detail.created_at) : null },
  ] : [];
  const linkGroups: RelatedGroup[] = detail ? [
    { key: "controls", label: "Controls", items: detail.controls, href: "/controls" },
    { key: "requirements", label: "Compliance requirements", items: detail.requirements, href: "/compliance" },
    { key: "risks", label: "Risks", items: detail.risks, href: "/risks" },
    { key: "related", label: "Related policies", items: detail.related, href: "/policies" },
    {
      key: "exceptions", label: "Exceptions", items: detail.exceptions, href: "/exceptions",
      // B3: "Approved · expires 30 Nov 2026"; an older API sends no status and no note shows.
      meta: (x: PolicyExceptionRef) => policyExceptionNote(x, ctx.fmt),
    },
    { key: "projects", label: "Projects", items: detail.projects, href: "/projects" },
    { key: "goals", label: "Goals", items: detail.goals, href: "/goals" },
    { key: "processing", label: "Processing activities", items: detail.processing_activities, href: "/privacy" },
  ] : [];

  return (
    <>
      <div className="page-head row-between" style={{ flexWrap: "wrap" }}>
        {/* The actions wrap under the title on a phone instead of widening the page. */}
        <div style={{ flex: "1 1 260px", minWidth: 0 }}>
          <h1>Policy Management</h1>
          <p>Repository for policies with document content, versioning, review cycles, cross-links and acknowledgments.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
        variant="dossier"
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        governance={gov}
        identity={detail ? {
          kind: "Policy",
          backLabel: "Policy Management",
          reference: detail.reference || null,
          name: detail.title,
          lead: detail.summary || null,
          badges: <Badge tone="neutral" plain asIs>v{detail.version}</Badge>,
          status: statusMeta,
          approval: approvalMetaItem(gov, ctx.fmt, approvalHintFor("Document status")),
          meta: policyMeta,
          statusRules: { model: "policy", entityId: detail.id },
        } : undefined}
        primaryAction={<PrimaryAction candidates={primaryCandidates} onChanged={refresh} />}
        onEdit={detail && canWrite ? () => openEdit(detail) : undefined}
        actions={detail && iAmAsked && primaryText !== "Acknowledge" ? (
          <button type="button" className="btn secondary sm" onClick={() => acknowledge(detail)}>Acknowledge</button>
        ) : undefined}
        moreItems={detail ? withBaseMoreItems(
          [
            { label: "Acknowledge", onClick: () => acknowledge(detail), hint: "Record that you have read this version" },
            // Publish is normally the header primary; it stays reachable when another action outranks it.
            ...(canWrite && canPublish(detail) && primaryText !== "Publish" ? [{ label: "Publish…", onClick: () => void publish(detail) }] : []),
            ...(canWrite ? [{ label: "Schedule review…", onClick: openReviewForm }] : []),
          ],
          { onDelete: canWrite ? () => remove(detail) : undefined },
        ) : []}
        aside={detail ? (
          <RecordPanels
            model="policy"
            entityId={detail.id}
            layout="dossier"
            signOff={{ onChanged: refresh, extraRows: publicationRow }}
            trail={{ reference: detail.reference }}
          />
        ) : null}
      >
        {detail && policyInput && (
          <>
            <SummaryBand tiles={policyTiles(policyInput, ctx)} headline={policyHeadline(policyInput, ctx)} />
            <OpenPoints
              points={policyOpenPoints(policyInput, ctx)}
              canAct={canWrite}
              onAction={handlePoint}
              clearText={POLICY_CLEAR_TEXT}
            />
            <SectionNav />

            <RecordSection
              id="document"
              title="Document"
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "content")}>Edit text</button> : undefined}
              empty={!htmlToText(detail.body) && !detail.url?.trim() ? "No policy text recorded." : undefined}
            >
              {/* The summary is the header lead; it is not repeated here (v1.1 D2). */}
              {htmlToText(detail.body) && <PolicyBody html={detail.body} />}
              {detail.url?.trim() && (
                <p style={{ margin: "0 0 8px", fontSize: 13.5 }}>
                  {safeLinkUrl(detail.url) ? (
                    <a href={safeLinkUrl(detail.url) ?? undefined} target="_blank" rel="noopener noreferrer">Open the published document</a>
                  ) : (
                    <><span className="muted">Document location: </span>{detail.url}</>
                  )}
                </p>
              )}
            </RecordSection>

            <RecordSection
              id="acknowledgement"
              title="Acknowledgement"
              sub={ackStatus && detail.status === "published" ? `${ackStatus.acknowledged} of ${ackStatus.total} acknowledged` : undefined}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "governance")}>Set who applies</button> : undefined}
            >
              <FactList
                items={[
                  {
                    key: "units", label: "Business units", tab: "governance",
                    value: detail.business_units?.length
                      ? <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 6 }}>{detail.business_units.map((u) => <RefChip key={u.id} x={u} href="/business-units" />)}</span>
                      : null,
                  },
                  {
                    key: "roles", label: "Roles", tab: "governance",
                    value: detail.roles?.length
                      ? <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 6 }}>{detail.roles.map((r) => <span key={r.id} className="chip">{r.name}</span>)}</span>
                      : "Everyone (no roles set)",
                  },
                ]}
                onFillIn={canWrite ? (tab) => openEdit(detail, tab) : undefined}
              />
              {ackStatus ? (
                <div style={{ marginTop: 14 }}>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", fontSize: 13, marginBottom: 6 }}>
                    <Badge tone={policyAckTone(ackStatus)} asIs>
                      {ackStatus.acknowledged} of {ackStatus.total} acknowledged
                    </Badge>
                    {ackStatus.outside_scope > 0 && <span className="muted">+{ackStatus.outside_scope} from people outside the scope</span>}
                  </div>
                  <p className="muted" style={{ fontSize: 12.5, margin: "0 0 10px" }}>{ackStatus.note}</p>
                  {ackStatus.users.length ? (
                    <div className="rec-table-wrap pol-ack-wrap record-print-full" style={{ maxHeight: 280, overflowY: "auto" }}>
                      <table className="compact">
                        <thead>
                          <tr><th>Person</th><th>Roles</th><th style={{ width: 170 }}>Acknowledged</th></tr>
                        </thead>
                        <tbody>
                          {ackStatus.users.map((u) => (
                            <tr key={u.user_id}>
                              <td><span title={u.email}>{u.full_name || u.email}</span></td>
                              <td className="muted" style={{ fontSize: 12.5 }}>{u.roles.join(", ") || <span className="muted">No role</span>}</td>
                              <td>
                                {u.acknowledged
                                  ? <span><Badge tone="low" asIs>Yes</Badge> <span className="muted" style={{ fontSize: 12 }}>{formatDate(u.acknowledged_at)}</span></span>
                                  : <Badge tone="medium" asIs>Pending</Badge>}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : <p className="rec-empty" style={{ margin: 0 }}>Nobody is in scope: the policy&apos;s roles have no active members.</p>}
                </div>
              ) : <p className="rec-empty" style={{ margin: "12px 0 0" }}>Acknowledgement status unavailable.</p>}
            </RecordSection>

            <RecordSection
              id="reviews"
              title="Reviews"
              count={reviews.length}
              sub={reviewCycleText(detail)}
              actions={canWrite ? (
                <button
                  ref={reviewTriggerRef}
                  type="button"
                  className="btn secondary sm"
                  aria-expanded={reviewFormOpen}
                  aria-controls="policy-review-form"
                  onClick={() => setReviewFormOpen((v) => !v)}
                >
                  Schedule review
                </button>
              ) : undefined}
              empty={reviews.length === 0 && !reviewFormOpen ? "No reviews scheduled yet." : undefined}
            >
              <Disclosure
                label="Schedule review"
                hideTrigger
                open={reviewFormOpen}
                onOpenChange={setReviewFormOpen}
                id="policy-review-form"
                triggerRef={reviewTriggerRef}
              >
                {(close) => (
                  <form className="row" onSubmit={async (e) => { e.preventDefault(); if (await scheduleReview(detail)) close(); }}>
                    <div style={{ width: 150 }}>
                      <label className="label" htmlFor="review-date">Planned for</label>
                      <input id="review-date" className="input" type="date" value={reviewDate} onChange={(e) => setReviewDate(e.target.value)} required />
                    </div>
                    <div style={{ flex: "1 1 190px" }}>
                      <LabelledSearch label="Reviewer">
                        <UserPicker value={reviewer?.id ?? null} selected={reviewer} onChange={(_id, ref) => setReviewer(ref ?? null)} placeholder="Who reviews it…" />
                      </LabelledSearch>
                    </div>
                    <div style={{ flex: "1 1 160px" }}>
                      <label className="label" htmlFor="review-note">Note</label>
                      <input id="review-note" className="input" value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="Scope of the review (optional)" />
                    </div>
                    <button type="submit" className="btn secondary sm" disabled={!reviewDate || reviewBusy}>Schedule</button>
                    <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
                  </form>
                )}
              </Disclosure>
              {reviews.length > 0 && (
                <div className="rec-table-wrap" style={{ marginTop: reviewFormOpen ? 12 : 0 }}>
                  <table className="compact">
                    <thead>
                      <tr><th style={{ width: 120 }}>Planned</th><th>Reviewer</th><th style={{ width: 120 }}>Done</th><th>Note</th><th style={{ width: 100 }} aria-label="Actions" /></tr>
                    </thead>
                    <tbody>
                      {reviews.map((r, ri, all) => (
                        <tr key={r.id}>
                          <td className="muted" style={{ whiteSpace: "nowrap" }}>{formatDate(r.planned_date)}</td>
                          <td>{r.reviewer_ref || r.reviewer ? <UserName user={r.reviewer_ref} fallback={r.reviewer} /> : <span className="muted">Not set</span>}</td>
                          <td className="muted">{r.actual_review_date ? formatDate(r.actual_review_date) : "Open"}</td>
                          <td style={{ fontSize: 13 }}>{r.comments || <span className="muted">No note</span>}</td>
                          <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                            {!r.actual_review_date && canWrite && (
                              <button
                                type="button"
                                className="btn secondary sm"
                                {...rowAction("Mark done", uniqueLabels(all.map((x) => {
                                  // Planned date, then the reviewer (decision D3: unique names).
                                  const who = x.reviewer_ref?.full_name || x.reviewer_ref?.email || x.reviewer || "";
                                  return `the review planned for ${formatDate(x.planned_date)}${who ? ` by ${who}` : ""}`;
                                }))[ri])}
                                onClick={() => completeReview(detail, r)}
                                disabled={reviewBusy}
                              >
                                Mark done
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </RecordSection>

            <RecordSection
              id="versions"
              title="Versions"
              sub={`Current version v${detail.version}`}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "governance")}>Set supersedes</button> : undefined}
              empty={!detail.supersedes_ref && !(detail.superseded_by?.length) ? "First version on file." : undefined}
            >
              <FactGrid>
                {detail.supersedes_ref && <Fact label="Supersedes"><RefChip x={detail.supersedes_ref} href="/policies" /></Fact>}
                {detail.superseded_by?.length ? (
                  <Fact label="Superseded by">
                    <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 6 }}>{detail.superseded_by.map((x) => <RefChip key={x.id} x={x} href="/policies" />)}</span>
                    {detail.status === "retired" && <span className="muted" style={{ display: "block", fontSize: 12.5 }}>Retired when its successor was published.</span>}
                  </Fact>
                ) : null}
              </FactGrid>
            </RecordSection>

            <RecordSection
              id="details"
              title="Details"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit details" onClick={() => openEdit(detail)}>Edit</button> : undefined}
            >
              <FactList
                items={[...detailFacts, ...cf.facts]}
                onFillIn={canWrite ? (tab) => (tab === "custom" ? cf.setEditing(true) : openEdit(detail, tab)) : undefined}
              />
              {cf.editor}
              {cf.editLink(canWrite)}
            </RecordSection>

            <RecordSection
              id="linked"
              title="Linked records"
              count={relatedCount(linkGroups)}
              actions={canWrite ? <button type="button" className="btn secondary sm" onClick={() => openEdit(detail, "links")}>Link records</button> : undefined}
            >
              {/* The head holds "Link records"; the empty line needs no second one (v1.1 D3). */}
              <RelatedGroups groups={linkGroups} />
            </RecordSection>
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
            ...cfForm.tabs,
          ]}
          initialTab={editTab}
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
