"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiCall } from "@/lib/api";
import { assetDeleteMessage, linkedRiskCount } from "@/lib/assetImpact";
import { confirmDialog, toast } from "@/lib/feedback";
import { unconvertedNote, useFormat, type MoneyTotal } from "@/lib/format";
import { confirmDeleteWithImpact, WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";
import { deleteEach, deleteErrorText, toastDeleteSummary } from "@/lib/bulkDelete";
import { useHasPermission } from "@/lib/tenantSettings";
import BusinessUnitSelect from "@/components/BusinessUnitSelect";
import ArchivedRecords from "@/components/ArchivedRecords";
import { type Page } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import BulkEditBar from "@/components/BulkEditBar";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncSelect from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, MultiSelect, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";
import type { GraphRef } from "@/components/RelatedChips";
import type { MenuItem } from "@/components/Menu";
import ImportExport from "@/components/ImportExport";
import GenerateRisks, { type GenerateRisksHandle } from "@/components/GenerateRisks";
import { InlineLookupCreate } from "@/components/LookupManager";
import { useCustomFieldFacts } from "@/components/CustomFieldsPanel";
import {
  AssetRiskReportButton,
  Disclosure,
  FactList,
  LabelledSearch,
  OpenPoints,
  PrimaryAction,
  RecordIssuesSection,
  RecordSection,
  RelatedGroups,
  SectionNav,
  SummaryBand,
  approvalMetaItem,
  assetRiskReportItems,
  relatedCount,
  reviewStatusMetaItem,
  rowAction,
  scrollToSection,
  useAssetRiskReport,
  useRecordCtx,
  useRecordGovernanceData,
  withBaseMoreItems,
  type FactItem,
  type MetaItem,
  type PrimaryCandidate,
  type RecordIssuesHandle,
  type RelatedGroup,
} from "@/components/record";
import {
  ASSET_APPROVAL_HINT,
  exceptionGroupMeta,
  linkRowLabel,
  reviewCycleText,
  assetReviewStatusView,
  reviewStatusHint,
  riskGroupMeta,
  type AssetDependency,
  type AssetExceptionRef,
  type AssetRiskRef,
} from "@/lib/record/infoAsset";
import {
  IT_ASSET_COPY as COPY,
  autoDiscoveredText,
  discoveryText,
  hostLine,
  hoursText,
  itAssetCriticalityRows,
  itAssetHeadline,
  itAssetOpenPoints,
  itAssetTiles,
  type ItAssetInput,
} from "@/lib/record/itAsset";
import { sentenceCase, uniqueLabels } from "@/lib/record/text";
import type { PointAction } from "@/lib/record/types";
import { titleCase } from "@/lib/text";

/* ------------------------------------------------------------------ types */
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";
type LinkRef = { id: string; label: string };
// Relation refs from GET /assets/{id} arrive as {id, label}; adapt to the
// {id, name} shape the linked-record chips render.
const asRefs = (items?: LinkRef[]): GraphRef[] | undefined =>
  items?.map((x) => ({ id: x.id, name: x.label }));
/** Risk refs carry their reference separately and the risk's name as the label (an older API sent the reference as the label). */
const riskRefs = (items?: AssetRiskRef[]): (GraphRef & AssetRiskRef)[] | undefined =>
  items?.map((x) => ({ ...x, reference: x.reference || x.label, name: x.reference && x.label !== x.reference ? x.label : "" }));
/** Exception refs keep their B3 status and expiry for the group meta. */
const exceptionRefs = (items?: AssetExceptionRef[]): (GraphRef & AssetExceptionRef)[] | undefined =>
  items?.map((x) => ({ ...x, name: x.label }));
type TagRow = { id: string; name: string; category: string; description?: string; color?: string };
type Asset = {
  id: string; name: string; description: string; asset_class: string; media_type: LinkRef | null;
  /** Business units (RACI owner / guardian / user). */
  owner: LinkRef | null; guardian: LinkRef | null; user: LinkRef | null;
  availability: string; replacement_cost: number; currency: string; rto_hours: number | null; rpo_hours: number | null;
  environment: string; location: string; hostname: string; ip_address: string; serial_number: string;
  manufacturer: string; model_number: string; os_version: string; discovery_source: string; external_id: string;
  auto_discovered: boolean; last_seen: string | null;
  cost_band: string; intrinsic_criticality: string; derived_criticality: string; effective_criticality: string;
  review_frequency: string; next_review_date: string | null; last_review_date: string | null;
  /** "none" | "current" | "overdue" (server-computed from next_review_date). */
  review_status: string; expired_reviews: number;
  /** B8: each hosted information asset carries its business value (absent on an older API). */
  workflow_status: string; tags: TagRow[]; dependencies: AssetDependency[]; created_at: string;
  // cross-module relations from GET /assets/{id} ({id,label} LinkRef shape)
  processes?: LinkRef[];
  legals?: LinkRef[];
  requirements?: LinkRef[];
  incidents?: LinkRef[];
  /** B3: status and expiry (absent on an older API). */
  exceptions?: AssetExceptionRef[];
  /** B8: reference, scores, bands and appetite status (absent on an older API, null without risk:read). */
  risks?: AssetRiskRef[];
  related_assets?: LinkRef[];
  // reverse graph links (read-only) — GraphRef {id,reference?,title?,name?}
  vendors?: GraphRef[];
  access_reviews?: GraphRef[];
  controls?: GraphRef[];
  threats?: GraphRef[];
  vulnerabilities?: GraphRef[];
};
type MediaType = { id: string; name: string; description: string; editable: boolean };
type Summary = {
  total: number; production: number; total_replacement_value: number; effective_critical: number;
  /** Decision 4: the same figure with its currency and anything left out for want of a rate. */
  replacement_value?: MoneyTotal;
};

/* ----------------------------------------------------------------- helpers */
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const workflowLabel = (s: string) => WORKFLOW_STATE_LABEL[s as WorkflowStateKey] ?? cap(s);

const CRIT = opts(["low", "medium", "high", "critical"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const ENVIRONMENT = opts(["production", "dr", "uat", "staging", "development", "not_applicable"]);
const DISCOVERY = opts(["manual", "active_directory", "intune_mdm", "cmdb", "network_scan", "cloud_connector", "edr", "import_csv"]);
const RELATIONSHIP = opts(["hosts", "stores", "processes", "transmits", "backs_up"]);
const CRIT_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "high", critical: "critical" };

/** Register list badge (unchanged). */
function CritBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={CRIT_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

const SEV_TONES = new Set(["low", "medium", "high", "critical"]);
const toneOf = (v: string | null | undefined): "low" | "medium" | "high" | "critical" | "neutral" => {
  const k = (v ?? "").toLowerCase();
  return SEV_TONES.has(k) ? (k as "low" | "medium" | "high" | "critical") : "neutral";
};

/** Record-page badge: sentence case, as stored (`sev(x)` in record-page-spec §4). */
function SevBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <Badge hollow asIs>Not assessed</Badge>;
  return <Badge tone={toneOf(value)} asIs>{sentenceCase(value)}</Badge>;
}

/* The record's wording — tiles, headline, open points, the Criticality derivation, fact
   texts and the fixed copy — lives in lib/record/itAsset.ts (record-page-spec §4.4),
   checked by lib/record/__fixtures__/it-asset-*.json (npm run check:record-copy). */

const PRIMARY: PrimaryCandidate[] = [
  { kind: "workflow", action: "approve" },
  { kind: "workflow", action: "submit" },
  { kind: "attest" },
];

/* ------------------------------------------------------------------ form */
type FormState = {
  name: string; description: string; media_type_id: string; replacement_cost: string; currency: string;
  availability: string; rto_hours: string; rpo_hours: string; environment: string; location: string;
  hostname: string; ip_address: string; serial_number: string; manufacturer: string; model_number: string;
  os_version: string; tag_ids: string[]; discovery_source: string; external_id: string;
  /** Business units (RACI owner / guardian / user) and the review cycle. */
  owner_id: string | null; guardian_id: string | null; user_id: string | null; review_frequency: string;
};
/** `currency` is filled with the organisation's currency when the form opens. */
const BLANK: FormState = {
  name: "", description: "", media_type_id: "", replacement_cost: "", currency: "", availability: "medium",
  rto_hours: "", rpo_hours: "", environment: "production", location: "", hostname: "", ip_address: "",
  serial_number: "", manufacturer: "", model_number: "", os_version: "", tag_ids: [], discovery_source: "manual",
  external_id: "", owner_id: null, guardian_id: null, user_id: null, review_frequency: "annual",
};
function fromAsset(a: Asset): FormState {
  return {
    name: a.name, description: a.description || "", media_type_id: a.media_type?.id || "",
    replacement_cost: a.replacement_cost != null ? String(a.replacement_cost) : "", currency: a.currency || "",
    availability: a.availability || "medium", rto_hours: a.rto_hours != null ? String(a.rto_hours) : "",
    rpo_hours: a.rpo_hours != null ? String(a.rpo_hours) : "", environment: a.environment || "production",
    location: a.location || "", hostname: a.hostname || "", ip_address: a.ip_address || "",
    serial_number: a.serial_number || "", manufacturer: a.manufacturer || "", model_number: a.model_number || "",
    os_version: a.os_version || "", tag_ids: a.tags.map((t) => t.id), discovery_source: a.discovery_source || "manual",
    external_id: a.external_id || "",
    owner_id: a.owner?.id ?? null, guardian_id: a.guardian?.id ?? null, user_id: a.user?.id ?? null,
    review_frequency: a.review_frequency || "annual",
  };
}
function toPayload(f: FormState, tenantCurrency: string): Record<string, unknown> {
  return {
    asset_class: "it_asset", name: f.name, description: f.description, media_type_id: f.media_type_id || null,
    replacement_cost: f.replacement_cost === "" ? 0 : Number(f.replacement_cost), currency: f.currency || tenantCurrency,
    availability: f.availability, rto_hours: f.rto_hours === "" ? null : Number(f.rto_hours),
    rpo_hours: f.rpo_hours === "" ? null : Number(f.rpo_hours), environment: f.environment, location: f.location,
    hostname: f.hostname, ip_address: f.ip_address, serial_number: f.serial_number, manufacturer: f.manufacturer,
    model_number: f.model_number, os_version: f.os_version, tag_ids: f.tag_ids, discovery_source: f.discovery_source,
    external_id: f.external_id, owner_id: f.owner_id, guardian_id: f.guardian_id, user_id: f.user_id,
    review_frequency: f.review_frequency,
  };
}

function ITAssetsInner() {
  const router = useRouter();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [summary, setSummary] = useState<Summary | null>(null);
  const { currency, currencyOptions, formatDate, formatMoney } = useFormat();

  const [mediaTypes, setMediaTypes] = useState<MediaType[]>([]);
  const [tags, setTags] = useState<TagRow[]>([]);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [editTab, setEditTab] = useState<string | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const [newTag, setNewTag] = useState("");
  const [creatingTag, setCreatingTag] = useState(false);

  // hosted information assets link form (behind "Link information asset")
  const [linkOpen, setLinkOpen] = useState(false);
  const linkTriggerRef = useRef<HTMLButtonElement>(null);
  const [depAssetId, setDepAssetId] = useState<string | null>(null);
  const [depAssetLabel, setDepAssetLabel] = useState("");
  const [depRel, setDepRel] = useState("hosts");
  const [depNotes, setDepNotes] = useState("");
  const [depError, setDepError] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);

  const generateRef = useRef<GenerateRisksHandle>(null);
  const issuesRef = useRef<RecordIssuesHandle>(null);

  // record page (dossier) state — record-page-spec §4.0 / §4.4
  const gov = useRecordGovernanceData("asset", detail?.id ?? null, { statusRulesModel: "asset" });
  const canWrite = useHasPermission("asset:write");
  const canRaiseIssue = useHasPermission("issue:write");
  const report = useAssetRiskReport(detail ? { id: detail.id, name: detail.name } : null);
  const canGenerate = useHasPermission("risk:write");
  const ctx = useRecordCtx(gov, canWrite);
  const fmt = ctx.fmt;
  const cf = useCustomFieldFacts("asset", detail?.id, { builtInLabels: ["Owner", "Owning unit", "Guardian", "Custodian"] });

  const loadSummary = useCallback(() => {
    apiCall<Summary>("GET", "/assets/summary?asset_class=it_asset").then(setSummary).catch(() => {});
  }, []);
  useEffect(() => {
    const ignore = () => {};
    apiCall<MediaType[]>("GET", "/asset-media-types").then(setMediaTypes).catch(ignore);
    apiCall<TagRow[]>("GET", "/asset-tags").then(setTags).catch(ignore);
    loadSummary();
  }, [loadSummary]);

  const loadDetail = useCallback((id: string) => {
    apiCall<Asset>("GET", `/assets/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  // forms on demand close when another record opens
  const detailId = detail?.id ?? null;
  useEffect(() => {
    setLinkOpen(false);
    setDepError(null);
  }, [detailId]);

  /** After any change to the open record: governance, the record, the list and the stats. */
  function refresh() {
    void gov.reload();
    if (detail) loadDetail(detail.id);
    setRefreshKey((k) => k + 1);
    loadSummary();
  }

  const fetchAssets = useCallback((qs: string) => apiCall<Page<Asset>>("GET", `/assets?asset_class=it_asset&${qs}`), []);
  const searchInfoAssets = useCallback(
    (q: string) =>
      apiCall<Page<Asset>>("GET", `/assets?asset_class=information_asset&search=${encodeURIComponent(q)}&limit=20`).then((r) =>
        r.items.map((a) => ({ value: a.id, label: a.name, sub: cap(a.effective_criticality || "") })),
      ),
    [],
  );

  function openNew() { setEditing(null); setEditTab(undefined); setF({ ...BLANK, currency }); setError(null); setShowForm(true); }
  function openEdit(a: Asset, tab?: string) { setEditing(a); setEditTab(tab); setF({ ...fromAsset(a), currency: a.currency || currency }); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f, currency);
      if (editing) await apiCall<Asset>("PATCH", `/assets/${editing.id}`, payload);
      else await apiCall<Asset>("POST", "/assets", payload);
      setShowForm(false); setRefreshKey((k) => k + 1); loadSummary();
      if (openId) {
        loadDetail(openId);
        void gov.reload();
      }
      toast(editing ? "Changes saved" : "Created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save IT asset");
    } finally { setSaving(false); }
  }
  async function remove(a: Asset) {
    const ok = await confirmDeleteWithImpact("asset", a.id, a.name, {
      typeLabel: "IT asset", confirmLabel: "Archive", note: "Linked risks stay in the risk register and are flagged for review.",
    });
    if (!ok) return;
    try {
      await apiCall<void>("DELETE", `/assets/${a.id}`);
      setShowForm(false); if (openId === a.id) setOpenId(null); setRefreshKey((k) => k + 1); loadSummary(); toast(`Archived ${a.name}`);
    } catch (e) { toast(deleteErrorText(e, "Failed to delete the IT asset"), "error"); }
  }
  async function createTag() {
    const name = newTag.trim(); if (!name) return; setCreatingTag(true);
    try {
      const t = await apiCall<TagRow>("POST", "/asset-tags", { name, category: "", description: "", color: "" });
      setTags((p) => [...p, t]); set("tag_ids", [...f.tag_ids, t.id]); setNewTag("");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to create tag"); }
    finally { setCreatingTag(false); }
  }
  /** Link the chosen information asset. Resolves true when the link was made (the form closes). */
  async function addDependency(): Promise<boolean> {
    if (!detail || !depAssetId) return false;
    setDepError(null);
    setLinking(true);
    try {
      await apiCall("POST", "/assets/dependencies", { information_asset_id: depAssetId, it_asset_id: detail.id, relationship_type: depRel, notes: depNotes });
      setDepAssetId(null); setDepAssetLabel(""); setDepNotes(""); setDepRel("hosts");
      toast("Information asset linked");
      refresh();
      return true;
    } catch (e) {
      setDepError(e instanceof Error ? e.message : "Failed to link information asset");
      return false;
    } finally {
      setLinking(false);
    }
  }
  async function removeDependency(depId: string) {
    if (!detail) return; if (!(await confirmDialog({ title: "Unlink this hosted information asset?", danger: true, confirmLabel: "Unlink" }))) return;
    try { await apiCall<void>("DELETE", `/assets/dependencies/${depId}`); refresh(); }
    catch (e) { toast(e instanceof Error ? e.message : "Failed to unlink information asset", "error"); }
  }

  /** The section falls back to its one-line empty state when the form closes, which
   *  unmounts the Disclosure before it can return focus — so return it here. */
  function onLinkOpenChange(open: boolean) {
    setLinkOpen(open);
    if (!open) {
      setDepError(null);
      requestAnimationFrame(() => linkTriggerRef.current?.focus({ preventScroll: true }));
    }
  }
  function openLinkForm() {
    setLinkOpen(true);
    scrollToSection("hosted");
  }
  /** More › "Raise issue…": the shared Issues section scrolls into view and opens its form. */
  function openRaiseIssue() {
    issuesRef.current?.raise();
  }

  /** Open-point fixes only scroll, focus, open Edit on a tab, open a form or navigate. */
  function handlePoint(p: PointAction) {
    if (!detail) return;
    if (p.kind === "section") scrollToSection(p.target);
    else if (p.kind === "edit") openEdit(detail, p.target);
    else if (p.kind === "focus") document.getElementById(p.target)?.focus();
    else if (p.kind === "href") router.push(p.target);
    else if (p.kind === "attest") gov.openAttest();
    else if (p.kind === "open" && p.target === "link-info-asset") openLinkForm();
  }

  const mediaTypeOpts: Option[] = useMemo(() => mediaTypes.map((m) => ({ value: m.id, label: m.name })), [mediaTypes]);
  const tagOpts: Option[] = useMemo(() => tags.map((t) => ({ value: t.id, label: t.name, sub: t.category || undefined })), [tags]);

  const columns: Column<Asset>[] = [
    { key: "name", header: "Name", sortable: true, locked: true, render: (a) => <span className="cell-title">{a.name}</span> },
    { key: "environment", header: "Environment", sortable: true, render: (a) => <Badge tone="neutral" plain>{cap(a.environment)}</Badge>, text: (a) => cap(a.environment) },
    { key: "availability", header: "Availability", render: (a) => <CritBadge value={a.availability} />, text: (a) => cap(a.availability) },
    { key: "replacement_cost", header: "Cost band", sortable: true, render: (a) => <CritBadge value={a.cost_band} />, text: (a) => cap(a.cost_band) },
    { key: "effective_criticality", header: "Effective criticality", render: (a) => <CritBadge value={a.effective_criticality} />, text: (a) => cap(a.effective_criticality) },
    { key: "hosted", header: "Hosted data", align: "center", render: (a) => <span className="muted">{a.dependencies?.length || "—"}</span>, text: (a) => String(a.dependencies?.length ?? 0) },
    { key: "hostname", header: "Hostname", hidden: true, render: (a) => <span className="ref">{a.hostname || "—"}</span> },
    { key: "ip_address", header: "IP address", hidden: true, render: (a) => <span className="ref">{a.ip_address || "—"}</span> },
    { key: "location", header: "Location", hidden: true, render: (a) => <span className="muted">{a.location || "—"}</span> },
    { key: "manufacturer", header: "Make / model", hidden: true, render: (a) => <span className="muted">{[a.manufacturer, a.model_number].filter(Boolean).join(" ") || "—"}</span>, text: (a) => [a.manufacturer, a.model_number].filter(Boolean).join(" ") },
    { key: "os_version", header: "OS", hidden: true, render: (a) => <span className="muted">{a.os_version || "—"}</span> },
    { key: "serial_number", header: "Serial", hidden: true, render: (a) => <span className="ref">{a.serial_number || "—"}</span> },
    { key: "rto", header: "RTO / RPO (h)", hidden: true, render: (a) => <span className="muted">{a.rto_hours ?? "—"} / {a.rpo_hours ?? "—"}</span>, text: (a) => `${a.rto_hours ?? ""}/${a.rpo_hours ?? ""}` },
    { key: "replacement_cost_value", header: "Replacement cost", hidden: true, align: "right", render: (a) => <span className="muted">{a.replacement_cost ? formatMoney(a.replacement_cost, a.currency) : "—"}</span>, text: (a) => (a.replacement_cost ? formatMoney(a.replacement_cost, a.currency) : "") },
    { key: "discovery_source", header: "Discovered via", hidden: true, render: (a) => <span className="muted">{cap(a.discovery_source)}</span>, text: (a) => cap(a.discovery_source) },
    { key: "tags", header: "Tags", hidden: true, render: (a) => a.tags?.length ? <div className="chips">{a.tags.map((t) => <span key={t.id} className="chip">{t.name}</span>)}</div> : <span className="muted">—</span>, text: (a) => (a.tags ?? []).map((t) => t.name).join(", ") },
    { key: "workflow_status", header: "Approval", hidden: true, render: (a) => <span className="muted">{workflowLabel(a.workflow_status)}</span>, text: (a) => workflowLabel(a.workflow_status) },
    { key: "created_at", header: "Created", hidden: true, render: (a) => <span className="muted">{formatDate(a.created_at)}</span>, text: (a) => (a.created_at ? formatDate(a.created_at) : "") },
  ];

  /** Delete every selected asset after one confirmation, then drop the selection. */
  async function removeMany(rowsToDelete: { id: string }[], clear: () => void) {
    const linked = await linkedRiskCount(rowsToDelete.map((r) => r.id));
    const ok = await confirmDialog({
      title: `Delete ${rowsToDelete.length} asset${rowsToDelete.length === 1 ? "" : "s"}?`,
      message: assetDeleteMessage(linked, rowsToDelete.length),
      confirmLabel: "Delete", danger: true,
    });
    if (!ok) return;
    const res = await deleteEach(rowsToDelete, (r) => apiCall("DELETE", `/assets/${r.id}`));
    clear();
    setRefreshKey((k) => k + 1);
    loadSummary();
    toastDeleteSummary(res, "IT asset");
  }

  /* --------------------------------------------------------------- form tabs */
  const identityTab = (
    <>
      <Field label="Name" required help="For example: DC-Karachi Core Banking DB Server, SWIFT Gateway Appliance.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="e.g. DB-KHI-CORE-01" required />
      </Field>
      <Field label="Description"><TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this supporting asset is and where it runs." /></Field>
      <Field label="Media type" help="The IT asset taxonomy (Hardware, Software, Network device…).">
        <Select value={f.media_type_id} onChange={(v) => set("media_type_id", v)} options={mediaTypeOpts} placeholder="— none —" />
        <InlineLookupCreate
          endpoint="/asset-media-types"
          onCreated={(r) => { setMediaTypes((p) => [...p, r as MediaType]); set("media_type_id", r.id); }}
        />
      </Field>
      <div className="field-row">
        <Field label="Owning unit" help="Business unit accountable for this asset (RACI owner)."><BusinessUnitSelect value={f.owner_id} onChange={(id) => set("owner_id", id)} placeholder="— none —" /></Field>
        <Field label="Custodian" help="Business unit that safeguards and maintains the asset (guardian)."><BusinessUnitSelect value={f.guardian_id} onChange={(id) => set("guardian_id", id)} placeholder="— none —" /></Field>
        <Field label="User" help="Business unit that uses the asset day to day."><BusinessUnitSelect value={f.user_id} onChange={(id) => set("user_id", id)} placeholder="— none —" /></Field>
      </div>
      <div className="field-row">
        <Field label="Review frequency" help="How often this asset is re-reviewed. Approval is separate: submit the asset for review from its record."><Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} /></Field>
      </div>
    </>
  );
  const costTab = (
    <>
      <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>{COPY.costTabNote}</p>
      <div className="field-row">
        <Field label="Replacement cost" help="Cost to replace this asset — drives its cost band."><TextInput type="number" value={f.replacement_cost} onChange={(v) => set("replacement_cost", v)} placeholder="Not recorded" /></Field>
        <Field label="Currency" help="Defaults to the organisation's currency.">
          <Select value={f.currency} onChange={(v) => set("currency", v)} options={currencyOptions} placeholder={`Organisation default (${currency})`} />
        </Field>
        <Field label="Availability" help="How available this asset must be (SLA tier)."><Select value={f.availability} onChange={(v) => set("availability", v)} options={CRIT} /></Field>
      </div>
      <div className="field-row">
        <Field label="RTO (hours)" help="Recovery time objective for this asset."><TextInput type="number" value={f.rto_hours} onChange={(v) => set("rto_hours", v)} placeholder="e.g. 4" /></Field>
        <Field label="RPO (hours)" help="Recovery point objective — tolerable data loss window."><TextInput type="number" value={f.rpo_hours} onChange={(v) => set("rpo_hours", v)} placeholder="e.g. 1" /></Field>
      </div>
    </>
  );
  const inventoryTab = (
    <>
      <div className="field-row">
        <Field label="Environment"><Select value={f.environment} onChange={(v) => set("environment", v)} options={ENVIRONMENT} /></Field>
        <Field label="Location" help="Data centre / site."><TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="e.g. DC-Karachi" /></Field>
      </div>
      <div className="field-row">
        <Field label="Hostname"><TextInput value={f.hostname} onChange={(v) => set("hostname", v)} placeholder="e.g. db-khi-core-01" /></Field>
        <Field label="IP address"><TextInput value={f.ip_address} onChange={(v) => set("ip_address", v)} placeholder="e.g. 10.20.0.11" /></Field>
      </div>
      <div className="field-row">
        <Field label="Serial number"><TextInput value={f.serial_number} onChange={(v) => set("serial_number", v)} placeholder="SN-XXXX" /></Field>
        <Field label="Manufacturer"><TextInput value={f.manufacturer} onChange={(v) => set("manufacturer", v)} placeholder="e.g. Dell" /></Field>
      </div>
      <div className="field-row">
        <Field label="Model number"><TextInput value={f.model_number} onChange={(v) => set("model_number", v)} placeholder="e.g. PowerEdge R760" /></Field>
        <Field label="OS version"><TextInput value={f.os_version} onChange={(v) => set("os_version", v)} placeholder="e.g. RHEL 9.3" /></Field>
      </div>
    </>
  );
  const tagsTab = (
    <>
      <Field label="Tags" help="Free-form operational tags for IT assets (not sensitivity labels)."><MultiSelect value={f.tag_ids} onChange={(v) => set("tag_ids", v)} options={tagOpts} /></Field>
      <Field label="Create a tag" help="Quickly add a new tag and attach it to this asset.">
        <div style={{ display: "flex", gap: 8 }}>
          <input className="input" value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder="e.g. PCI-scope, DC-Karachi, EOL-2026"
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); createTag(); } }} />
          <button className="btn secondary" type="button" onClick={createTag} disabled={creatingTag || !newTag.trim()}>{creatingTag ? "Adding…" : "Add tag"}</button>
        </div>
      </Field>
      <div className="field-row">
        <Field label="Discovery source" help="How this asset was brought into the inventory."><Select value={f.discovery_source} onChange={(v) => set("discovery_source", v)} options={DISCOVERY} /></Field>
        <Field label="External ID" help="Identifier in the source system (CMDB, AD, Intune…)."><TextInput value={f.external_id} onChange={(v) => set("external_id", v)} placeholder="e.g. CMDB-00123" /></Field>
      </div>
    </>
  );

  /* --------------------------------------------------------------- the record (dossier) */
  const a = detail;
  const input: ItAssetInput | null = a ? { asset: a } : null;
  const deps = a?.dependencies ?? [];
  /** The Unlink buttons' row labels (decision D3): the linked asset and the relationship,
   *  since one pair can be linked under several relationship types; still unique. */
  const unlinkLabels = uniqueLabels(deps.map((d) => `${linkRowLabel(d.information_asset)} (${sentenceCase(d.relationship_type).toLowerCase()})`));
  const riskCount = (a?.risks ?? []).length;
  const host = a ? hostLine(a) : "";
  // B8: the hosted information assets carry the business value this asset inherits.
  const hostedValues = deps.some((d) => !!d.information_asset?.business_value);

  const typeItems: MenuItem[] = [];
  if (a) {
    if (canWrite) typeItems.push({ label: "Link information asset…", onClick: openLinkForm });
    typeItems.push(...assetRiskReportItems(report, riskCount));
    if (canGenerate) {
      typeItems.push({ label: "Generate risks…", onClick: () => generateRef.current?.open(), hint: COPY.generateHint });
    }
    if (canRaiseIssue) typeItems.push({ label: "Raise issue…", onClick: openRaiseIssue });
  }

  // v1.1 D1: slot 1 is the review status (assets have no business status), slot 2 the
  // Record approval; B4 (native review) decides whether attesting moves the review date.
  const nativeReview = !!gov.attestation?.native_review;
  // The kit item, with the value and sub from assetReviewStatusView: a never-reviewed
  // asset reads "Not yet reviewed", not a green "Current".
  const reviewView = a ? assetReviewStatusView(a, fmt) : null;
  const statusItem: MetaItem | undefined = a && reviewView ? {
    ...reviewStatusMetaItem(a, fmt, reviewStatusHint(nativeReview)),
    value: reviewView.tone === "hollow" ? <Badge hollow asIs>{reviewView.text}</Badge> : <Badge tone={reviewView.tone} asIs>{reviewView.text}</Badge>,
    sub: reviewView.sub,
  } : undefined;
  const approvalItem: MetaItem | undefined = a ? approvalMetaItem(gov, fmt, ASSET_APPROVAL_HINT) : undefined;

  const meta: MetaItem[] = a
    ? [
        {
          key: "owner",
          label: "Owning unit",
          value: a.owner?.label ?? null,
          hint: COPY.owningUnitHint,
          gap: a.owner ? undefined : { text: COPY.owningUnitGap, fix: canWrite ? { label: "Assign", onClick: () => openEdit(a, "identity") } : undefined },
        },
        { key: "custodian", label: "Custodian", value: a.guardian?.label ?? null, hint: COPY.custodianHint },
        { key: "environment", label: "Environment", value: a.environment ? sentenceCase(a.environment) : null },
        { key: "location", label: "Location", value: (a.location ?? "").trim() || null },
      ]
    : [];

  const mono = (v: string | null | undefined) => ((v ?? "").trim() ? <span className="ref">{v}</span> : null);
  const technicalFacts: FactItem[] = a
    ? [
        { key: "media", label: "Media type", value: a.media_type?.label ?? null, tab: "identity" },
        { key: "hostname", label: "Hostname", value: mono(a.hostname), tab: "inventory" },
        { key: "ip", label: "IP address", value: mono(a.ip_address), tab: "inventory" },
        // A node, like the hostname and IP: when the OS alone makes the host-line lead, the
        // lead-repeat filter (decision D2) must not drop this labelled inventory fact.
        { key: "os", label: "OS", value: (a.os_version ?? "").trim() ? <span>{a.os_version}</span> : null, tab: "inventory" },
        { key: "serial", label: "Serial", value: mono(a.serial_number), tab: "inventory" },
        { key: "manufacturer", label: "Manufacturer", value: (a.manufacturer ?? "").trim() || null, tab: "inventory" },
        { key: "model", label: "Model", value: (a.model_number ?? "").trim() || null, tab: "inventory" },
        { key: "location", label: "Location", value: (a.location ?? "").trim() || null, tab: "inventory" },
        { key: "discovery", label: "Discovery", value: discoveryText(a, fmt), tab: "tags" },
        {
          key: "tags",
          label: "Asset tags",
          tab: "tags",
          value: a.tags.length ? (
            <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 4 }}>
              {a.tags.map((t) => <span key={t.id} className="chip">{t.name}</span>)}
            </span>
          ) : null,
        },
        { key: "rto", label: "RTO", value: hoursText(a.rto_hours), tab: "cost" },
        { key: "rpo", label: "RPO", value: hoursText(a.rpo_hours), tab: "cost" },
      ]
    : [];

  const detailFacts: FactItem[] = a
    ? [
        // The lead shows the host line when there is one; the description then lives here.
        ...(host ? [{ key: "description", label: "Description", value: (a.description ?? "").trim() || null, tab: "identity", wide: true }] : []),
        { key: "owner", label: "Owning unit", value: a.owner?.label ?? null, tab: "identity" },
        { key: "guardian", label: "Guardian (custodian)", value: a.guardian?.label ?? null, tab: "identity" },
        { key: "user", label: "User unit", value: a.user?.label ?? null, tab: "identity" },
        { key: "review", label: "Review cycle", value: reviewCycleText(a, fmt), tab: "identity" },
        { key: "created", label: "Created", value: fmt.date(a.created_at) },
        ...cf.facts,
      ]
    : [];

  const groups: RelatedGroup[] = a
    ? [
        {
          key: "risks",
          label: "Risks",
          items: riskRefs(a.risks),
          href: "/risks",
          meta: (x: AssetRiskRef) => riskGroupMeta(x),
          action: riskCount > 0 ? <AssetRiskReportButton assetId={a.id} assetName={a.name} riskCount={riskCount} report={report} /> : undefined,
        },
        { key: "controls", label: "Controls", items: a.controls, href: "/controls" },
        { key: "threats", label: "Threats", items: a.threats, href: "/threat-library" },
        { key: "vulnerabilities", label: "Vulnerabilities", items: a.vulnerabilities, href: "/threat-library" },
        { key: "processes", label: "Processes", items: asRefs(a.processes), href: "/processes" },
        { key: "requirements", label: "Compliance requirements", items: asRefs(a.requirements), href: "/compliance" },
        { key: "legals", label: "Legal registers", items: asRefs(a.legals), href: "/legal" },
        { key: "incidents", label: "Incidents", items: asRefs(a.incidents), href: "/incidents" },
        {
          key: "exceptions",
          label: "Exceptions",
          items: exceptionRefs(a.exceptions),
          href: "/exceptions",
          meta: (x: AssetExceptionRef) => exceptionGroupMeta(x, fmt),
        },
        { key: "related", label: "Related assets", items: asRefs(a.related_assets), href: "/it-assets" },
        { key: "vendors", label: "Third parties", items: a.vendors, href: "/vendors" },
        { key: "access", label: "Access reviews", items: a.access_reviews, href: "/access-reviews" },
      ]
    : [];

  const fillIn = (tab?: string) => {
    if (!a) return;
    if (tab === "custom") cf.setEditing(true);
    else openEdit(a, tab);
  };

  return (
    <>
      <div className="page-head row-between" style={{ flexWrap: "wrap" }}>
        {/* The actions wrap under the title on a phone instead of widening the page. */}
        <div style={{ flex: "1 1 260px", minWidth: 0 }}>
          <h1>IT Asset Management</h1>
          <p>Supporting assets — hardware, software and network. Judged on cost and availability, with criticality inheriting from the information assets they host.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ImportExport resource="it-assets" label="IT Assets"
            onDone={() => { setRefreshKey((k) => k + 1); loadSummary(); }} />
          <GenerateRisks assetClass="it_asset" label="IT assets" />
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add IT asset</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.total ?? 0).toLocaleString()}</span></div><span className="l">IT assets</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.effective_critical ?? 0).toLocaleString()}</span></div><span className="l">Effective-critical</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{(summary?.production ?? 0).toLocaleString()}</span></div><span className="l">Production assets</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{formatMoney(summary?.total_replacement_value ?? 0, summary?.replacement_value?.reporting_currency, { compact: "auto" })}</span></div><span className="l">Total replacement value</span></div>
      </div>

      {unconvertedNote(summary?.replacement_value) && (
        <div className="card card-pad" style={{ marginBottom: 16, fontSize: 13.5, background: "var(--primary-weak-2)" }}>
          {unconvertedNote(summary?.replacement_value)} — <Link href="/organisation-settings#exchange-rates">add a rate</Link>.
        </div>
      )}

      <DataTable<Asset>
        toolbarRight={<ArchivedRecords entityType="asset" noun="assets" onRestored={() => { setRefreshKey((k) => k + 1); loadSummary(); }} refreshKey={refreshKey} />}
        tableKey="it-assets"
        statusModel="asset"
        bulkActions={(rows, clear) => (
          <>
            <BulkEditBar entityType="asset" rows={rows} onDone={() => { clear(); setRefreshKey((k) => k + 1); loadSummary(); }} />
            <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
          </>
        )}
        columns={columns}
        fetcher={fetchAssets}
        rowKey={(a) => a.id}
        onRowClick={(a) => setOpenId(a.id)}
        activeKey={openId}
        searchPlaceholder="Search IT assets by name, hostname or owner…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No IT assets yet. Add hardware, software and network assets to build the supporting-asset inventory."
        refreshKey={refreshKey}
      />

      {/* Deep-linkable record (?id=, #section) — record-page-spec §4.4 */}
      <RecordDrawer
        variant="dossier"
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        governance={gov}
        identity={
          a
            ? {
                kind: "IT asset",
                backLabel: "IT Assets",
                name: a.name,
                lead: host || a.description,
                badges: (
                  <>
                    {a.environment && (
                      <>
                        <span className="sep" aria-hidden="true">/</span>
                        <span>{sentenceCase(a.environment)}</span>
                      </>
                    )}
                    {a.auto_discovered && (
                      <Badge tone="info" plain asIs>
                        {autoDiscoveredText(a, fmt)}
                      </Badge>
                    )}
                  </>
                ),
                status: statusItem,
                approval: approvalItem,
                meta,
                statusRules: { model: "asset", entityId: a.id },
              }
            : undefined
        }
        primaryAction={<PrimaryAction candidates={PRIMARY} onChanged={refresh} />}
        onEdit={a && canWrite ? () => openEdit(a) : undefined}
        moreItems={a ? withBaseMoreItems(typeItems, { onDelete: canWrite ? () => remove(a) : undefined }) : undefined}
        aside={
          a ? (
            <RecordPanels
              model="asset"
              entityId={a.id}
              layout="dossier"
              signOff={{
                review: { frequency: a.review_frequency, last: a.last_review_date, next: a.next_review_date, overdue: a.review_status === "overdue" },
                onChanged: refresh,
              }}
              trail={{ reference: null }}
            />
          ) : null
        }
      >
        {a && input && (
          <>
            <SummaryBand tiles={itAssetTiles(input, ctx)} headline={itAssetHeadline(input, ctx)} />
            <OpenPoints points={itAssetOpenPoints(input, ctx)} canAct={canWrite} onAction={handlePoint} clearText={COPY.clearText} />
            <SectionNav />

            {/* 1. Criticality — how the effective value is derived */}
            <RecordSection
              id="criticality"
              title="Criticality"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit criticality inputs" onClick={() => openEdit(a, "cost")}>Edit</button> : undefined}
            >
              <div className="rec-table-wrap">
                <table className="compact">
                  <thead>
                    <tr><th>Input</th><th>Value</th><th>Source</th></tr>
                  </thead>
                  <tbody>
                    {itAssetCriticalityRows(a, fmt).map((r) => (
                      <tr key={r.key}>
                        <td className="cell-title">{r.strong ? <b>{r.input}</b> : r.input}</td>
                        <td><SevBadge value={r.value} /></td>
                        <td className="muted">{r.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </RecordSection>

            {/* 2. Hosted information assets — the link form opens on demand */}
            <RecordSection
              id="hosted"
              title="Hosted information assets"
              count={deps.length}
              sub={deps.length > 0 ? COPY.hostedSub : undefined}
              actions={
                canWrite ? (
                  <button
                    ref={linkTriggerRef}
                    type="button"
                    className="btn secondary sm"
                    aria-expanded={linkOpen}
                    aria-controls="link-info-asset-panel"
                    onClick={() => setLinkOpen((v) => !v)}
                  >
                    Link information asset
                  </button>
                ) : undefined
              }
              empty={deps.length === 0 && !linkOpen ? COPY.hostedEmpty : undefined}
            >
              <Disclosure
                label="Link information asset"
                hideTrigger
                open={linkOpen}
                onOpenChange={onLinkOpenChange}
                id="link-info-asset-panel"
                triggerRef={linkTriggerRef}
              >
                {(close) => (
                  <form
                    className="row"
                    onSubmit={async (ev) => {
                      ev.preventDefault();
                      if (await addDependency()) close();
                    }}
                  >
                    <LabelledSearch label="Information asset" className="rec-link-pick">
                      <AsyncSelect search={searchInfoAssets} value={depAssetId} selectedLabel={depAssetLabel} placeholder="Search information assets…" onChange={(v, o) => { setDepAssetId(v); setDepAssetLabel(o?.label || ""); }} />
                    </LabelledSearch>
                    <div style={{ width: 150 }}>
                      <label className="label" style={{ marginTop: 0 }} htmlFor="link-info-asset-rel">Relationship</label>
                      <select id="link-info-asset-rel" className="select" value={depRel} onChange={(e) => setDepRel(e.target.value)}>
                        {RELATIONSHIP.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                      </select>
                    </div>
                    <div style={{ flex: "1 1 160px" }}>
                      <label className="label" style={{ marginTop: 0 }} htmlFor="link-info-asset-notes">Notes</label>
                      <input id="link-info-asset-notes" className="input" value={depNotes} onChange={(e) => setDepNotes(e.target.value)} placeholder="Optional context" />
                    </div>
                    <button className="btn secondary sm" disabled={!depAssetId || linking}>{linking ? "Linking…" : "Link"}</button>
                    <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
                    {depError && <div className="error" style={{ flexBasis: "100%", marginTop: 4 }}>{depError}</div>}
                  </form>
                )}
              </Disclosure>
              {deps.length > 0 ? (
                <div className="rec-table-wrap" style={linkOpen ? { marginTop: 12 } : undefined}>
                  <table className="compact">
                    <thead>
                      <tr>
                        <th>Information asset</th>
                        {hostedValues && <th>Business value</th>}
                        <th>Relationship</th>
                        <th>Notes</th>
                        {canWrite && <th><span className="sr-only">Actions</span></th>}
                      </tr>
                    </thead>
                    <tbody>
                      {deps.map((d, i) => (
                        <tr key={d.id}>
                          <td className="cell-title">
                            {d.information_asset ? (
                              <Link href={`/information-assets?id=${d.information_asset.id}`}>{d.information_asset.label}</Link>
                            ) : (
                              <span className="muted">{COPY.archivedLink}</span>
                            )}
                          </td>
                          {hostedValues && (
                            <td>{d.information_asset?.business_value ? <SevBadge value={d.information_asset.business_value} /> : <span className="muted">{COPY.noValue}</span>}</td>
                          )}
                          <td><Badge tone="info" plain asIs>{sentenceCase(d.relationship_type)}</Badge></td>
                          <td>{d.notes || <span className="muted">{COPY.noNotes}</span>}</td>
                          {canWrite && (
                            <td style={{ textAlign: "right" }}>
                              <button type="button" className="btn secondary sm" {...rowAction("Unlink", unlinkLabels[i])} onClick={() => removeDependency(d.id)}>Unlink</button>
                            </td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="rec-empty" style={{ margin: "12px 0 0" }}>{COPY.hostedEmpty}</p>
              )}
            </RecordSection>

            {/* 3. Technical — inventory, discovery, asset tags and recovery objectives */}
            <RecordSection
              id="technical"
              title="Technical"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit technical details" onClick={() => openEdit(a, "inventory")}>Edit</button> : undefined}
            >
              <FactList items={technicalFacts} onFillIn={canWrite ? (tab) => openEdit(a, tab) : undefined} />
            </RecordSection>

            {/* 4. Details — accountability, the review cycle and custom fields */}
            <RecordSection
              id="details"
              title="Details"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit details" onClick={() => openEdit(a, "identity")}>Edit</button> : undefined}
            >
              <FactList items={detailFacts} onFillIn={canWrite ? fillIn : undefined} />
              {cf.editor}
              {cf.editLink(canWrite)}
            </RecordSection>

            {/* 5. Linked records */}
            <RecordSection id="linked" title="Linked records" count={relatedCount(groups)}>
              <RelatedGroups groups={groups} />
            </RecordSection>

            {/* 6. Issues */}
            <RecordIssuesSection
              ref={issuesRef}
              entityId={a.id}
              entityKind="asset"
              entityRef={a.name}
              noun="IT asset"
              onRaised={refresh}
            />
          </>
        )}
      </RecordDrawer>

      {/* Per-record "Generate risks…" (More menu). Rendered outside the drawer so its
          dialog is not confined to the record's scroll container. */}
      {a && (
        <GenerateRisks
          ref={generateRef}
          hideButton
          assetClass="it_asset"
          assetIds={[a.id]}
          label={a.name}
          onDone={refresh}
        />
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit IT asset — ${editing.name}` : "Add IT asset"}
          wide
          tabs={[
            { id: "identity", label: "Identity", content: identityTab, required: true },
            { id: "cost", label: "Cost & Availability", content: costTab },
            { id: "inventory", label: "Inventory", content: inventoryTab },
            { id: "tags", label: "Tags & Discovery", content: tagsTab },
          ]}
          initialTab={editTab}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create IT asset"}
          footerLeft={editing ? (
            <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--red)" }}>Delete</button>
          ) : undefined}
        />
      )}
    </>
  );
}

export default function ITAssetsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ITAssetsInner />
    </Suspense>
  );
}
