"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiCall } from "@/lib/api";
import { assetDeleteMessage, linkedRiskCount } from "@/lib/assetImpact";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
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
import { Field, TextInput, TextArea, Select, Toggle, MultiSelect, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";
import RecordPanels from "@/components/RecordPanels";
import type { GraphRef } from "@/components/RelatedChips";
import type { MenuItem } from "@/components/Menu";
import ImportExport from "@/components/ImportExport";
import GenerateRisks, { type GenerateRisksHandle } from "@/components/GenerateRisks";
import { InlineLookupCreate } from "@/components/LookupManager";
import { useCustomFieldFacts } from "@/components/CustomFieldsPanel";
import { useCustomFieldForm } from "@/components/useCustomFieldForm";
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
  INFO_ASSET_COPY as COPY,
  agreementText,
  ciaChecks,
  exceptionGroupMeta,
  hasPii,
  infoAssetHeadline,
  infoAssetOpenPoints,
  infoAssetTiles,
  linkRowLabel,
  otherClassifications,
  alsoClassified,
  recoveryText,
  reviewCycleText,
  assetReviewStatusView,
  reviewStatusHint,
  riskGroupMeta,
  riskRowLabel,
  schemeCellText,
  selfAssessmentText,
  type AssetDependency,
  type AssetExceptionRef,
  type AssetRiskRef,
  type ClassificationTypeRow,
  type InfoAssetInput,
  userUnitSub,
} from "@/lib/record/infoAsset";
import { sentenceCase, uniqueLabels } from "@/lib/record/text";
import type { PointAction } from "@/lib/record/types";
import { titleCase } from "@/lib/text";

/* ------------------------------------------------------------------ types */
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";
type LinkRef = { id: string; label: string; reference?: string; name?: string };
// Relation refs from GET /assets/{id} arrive as {id, label, reference, name}; adapt to
// the {id, reference, name} shape the linked-record chips render ("SBP-05 Outsourcing").
const asRefs = (items?: LinkRef[]): GraphRef[] | undefined =>
  items?.map((x) => ({ id: x.id, reference: x.reference || undefined, name: x.name || x.label }));
/** Risk refs carry their reference separately and the risk's name as the label (an older API sent the reference as the label). */
const riskRefs = (items?: AssetRiskRef[]): (GraphRef & AssetRiskRef)[] | undefined =>
  items?.map((x) => ({ ...x, reference: x.reference || x.label, name: x.reference && x.label !== x.reference ? x.label : "" }));
/** Exception refs keep their B3 status and expiry for the group meta. */
const exceptionRefs = (items?: AssetExceptionRef[]): (GraphRef & AssetExceptionRef)[] | undefined =>
  items?.map((x) => ({ ...x, name: x.label }));
type Asset = {
  id: string;
  name: string;
  description: string;
  asset_class: string;
  media_type: LinkRef | null;
  label: LinkRef | null;
  owner: LinkRef | null;
  guardian: LinkRef | null;
  user: LinkRef | null;
  confidentiality: string;
  integrity: string;
  availability: string;
  business_value: string;
  information_owner: string;
  data_categories: string;
  records_volume: string;
  potential_liabilities: string;
  self_assessed: boolean;
  assessed_by: string;
  assessed_date: string | null;
  classifications?: ClassificationRef[];
  effective_criticality: string;
  /** Service tier (1 = most critical) and PCI DSS scope; null until decided. */
  tier: number | null;
  pci_scope: string | null;
  rto_hours: number | null;
  rpo_hours: number | null;
  review_frequency: string;
  next_review_date: string | null;
  last_review_date: string | null;
  /** "none" | "current" | "overdue" (server-computed from next_review_date). */
  review_status: string;
  expired_reviews: number;
  /** Read-only: moved only through the approval lifecycle (Sign-off card). */
  workflow_status: string;
  dependencies: AssetDependency[];
  created_at: string;
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
  // linked from the other side: continuity plans, RoPA entries, BIAs, scanner findings
  continuity_plans?: GraphRef[];
  processing_activities?: GraphRef[];
  bia_assessments?: GraphRef[];
  vuln_findings?: GraphRef[];
};
type MediaType = { id: string; name: string; description: string; editable: boolean };
type LabelRow = { id: string; name: string; description: string; color: string };
type ClassificationRef = { id: string; name: string; value: number; type_name: string };
type ClassificationType = ClassificationTypeRow & { description: string };
type Summary = { total: number; high_or_critical_value: number; self_assessed_pct: number; with_pii: number };

/* ----------------------------------------------------------------- helpers */
const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const CRIT = opts(["low", "medium", "high", "critical"]);
// Register filter: approval state, beside criticality (see the IT register).
const WORKFLOW_FILTER: Option[] = [
  { value: "draft", label: "Draft" }, { value: "in_review", label: "In review" },
  { value: "approved", label: "Approved" }, { value: "retired", label: "Retired" },
];
const REVIEW_FILTER: Option[] = [{ value: "overdue", label: "Review overdue" }];
// Service tier: 1 is the most critical. PCI DSS scope follows the PCI SSC scoping categories.
const TIER: Option[] = [1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: `Tier ${n}` }));
const PCI_SCOPE: Option[] = [
  { value: "in_scope", label: "In scope (cardholder data)" }, { value: "connected", label: "Connected to CDE" },
  { value: "out_of_scope", label: "Out of scope" },
];
const pciLabel = (v: string | null | undefined) => PCI_SCOPE.find((o) => o.value === v)?.label ?? null;
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const RELATIONSHIP = opts(["hosts", "stores", "processes", "transmits", "backs_up"]);
const workflowLabel = (s: string) => WORKFLOW_STATE_LABEL[s as WorkflowStateKey] ?? cap(s);

const CRIT_TONE: Record<string, Tone> = { low: "low", medium: "medium", high: "high", critical: "critical" };
const RANK: Record<string, number> = { low: 0, medium: 1, high: 2, critical: 3 };
const maxCia = (a: Asset) =>
  [a.confidentiality, a.integrity, a.availability].reduce((hi, v) => ((RANK[v] ?? -1) > (RANK[hi] ?? -1) ? v : hi), "low");

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

/* The record's wording — tiles, headline, open points, the Agreement column, fact texts
   and the fixed copy — lives in lib/record/infoAsset.ts (record-page-spec §4.3), checked
   by the Corporate Network fixtures (npm run check:record-copy). */

const PRIMARY: PrimaryCandidate[] = [
  { kind: "workflow", action: "approve" },
  { kind: "workflow", action: "submit" },
  { kind: "attest" },
];

/* ------------------------------------------------------------------ form */
type FormState = {
  name: string; description: string; media_type_id: string; information_owner: string;
  business_value: string; confidentiality: string; integrity: string; availability: string;
  label_id: string; data_categories: string; records_volume: string; potential_liabilities: string;
  self_assessed: boolean; assessed_by: string; assessed_date: string;
  /** Business units (RACI owner / guardian / user). */
  owner_id: string | null; guardian_id: string | null; user_id: string | null;
  review_frequency: string; classification_ids: string[];
  tier: string; pci_scope: string;
};
const BLANK: FormState = {
  name: "", description: "", media_type_id: "", information_owner: "", business_value: "medium",
  confidentiality: "medium", integrity: "medium", availability: "medium", label_id: "",
  data_categories: "", records_volume: "", potential_liabilities: "", self_assessed: false, assessed_by: "",
  assessed_date: "", owner_id: null, guardian_id: null, user_id: null, review_frequency: "annual",
  classification_ids: [], tier: "", pci_scope: "",
};
function fromAsset(a: Asset): FormState {
  return {
    name: a.name, description: a.description || "", media_type_id: a.media_type?.id || "",
    information_owner: a.information_owner || "", business_value: a.business_value || "medium",
    confidentiality: a.confidentiality || "medium", integrity: a.integrity || "medium",
    availability: a.availability || "medium", label_id: a.label?.id || "",
    data_categories: a.data_categories || "", records_volume: a.records_volume || "",
    potential_liabilities: a.potential_liabilities || "",
    self_assessed: !!a.self_assessed, assessed_by: a.assessed_by || "", assessed_date: a.assessed_date || "",
    owner_id: a.owner?.id ?? null, guardian_id: a.guardian?.id ?? null, user_id: a.user?.id ?? null,
    review_frequency: a.review_frequency || "annual",
    classification_ids: (a.classifications || []).map((c) => c.id),
    tier: a.tier != null ? String(a.tier) : "", pci_scope: a.pci_scope || "",
  };
}
function toPayload(f: FormState): Record<string, unknown> {
  return {
    asset_class: "information_asset", name: f.name, description: f.description,
    media_type_id: f.media_type_id || null, information_owner: f.information_owner,
    business_value: f.business_value, confidentiality: f.confidentiality, integrity: f.integrity,
    availability: f.availability, label_id: f.label_id || null, data_categories: f.data_categories,
    records_volume: f.records_volume, potential_liabilities: f.potential_liabilities,
    self_assessed: f.self_assessed, assessed_by: f.assessed_by,
    assessed_date: f.assessed_date || null, owner_id: f.owner_id, guardian_id: f.guardian_id,
    user_id: f.user_id, review_frequency: f.review_frequency,
    classification_ids: f.classification_ids,
    tier: f.tier === "" ? null : Number(f.tier), pci_scope: f.pci_scope || null,
  };
}

function InformationAssetsInner() {
  const router = useRouter();
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [critFilter, setCritFilter] = useState("");
  const [wfFilter, setWfFilter] = useState("");
  const [overdueFilter, setOverdueFilter] = useState("");
  const [tierFilter, setTierFilter] = useState("");
  const [pciFilter, setPciFilter] = useState("");
  // What the table shows, so Export carries exactly those rows.
  const [view, setView] = useState<{ search: string; filters: Record<string, string | number | boolean | undefined>; total: number } | null>(null);
  const exportQuery = useMemo(() => {
    const p = new URLSearchParams();
    if (view?.search) p.set("search", view.search);
    for (const [k, v] of Object.entries(view?.filters ?? {})) if (v !== undefined && v !== "" && v !== false) p.set(k, String(v));
    return p.toString();
  }, [view]);
  // Filters arrive in the link too — "1,560 IT assets have reviews overdue" opens the
  // register filtered to them (?review_overdue=true). Read once, on arrival.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("effective_criticality")) setCritFilter(p.get("effective_criticality") as string);
    if (p.get("workflow_status")) setWfFilter(p.get("workflow_status") as string);
    if (p.get("review_overdue") === "true") setOverdueFilter("overdue");
    if (p.get("tier")) setTierFilter(p.get("tier") as string);
    if (p.get("pci_scope")) setPciFilter(p.get("pci_scope") as string);
  }, []);
  const [summary, setSummary] = useState<Summary | null>(null);
  const { formatDate } = useFormat();

  // small lookup tables (bounded) for the form Selects
  const [mediaTypes, setMediaTypes] = useState<MediaType[]>([]);
  const [labels, setLabels] = useState<LabelRow[]>([]);
  const [classTypes, setClassTypes] = useState<ClassificationType[]>([]);

  // form
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Asset | null>(null);
  const [editTab, setEditTab] = useState<string | undefined>(undefined);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // hosted-on dependency link form (behind "Link IT asset")
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

  // record page (dossier) state — record-page-spec §4.0 / §4.3
  const gov = useRecordGovernanceData("asset", detail?.id ?? null, { statusRulesModel: "asset" });
  const canWrite = useHasPermission("asset:write");
  const canRaiseIssue = useHasPermission("issue:write");
  const report = useAssetRiskReport(detail ? { id: detail.id, name: detail.name } : null);
  const canGenerate = useHasPermission("risk:write");
  const ctx = useRecordCtx(gov, canWrite);
  const fmt = ctx.fmt;
  const cfForm = useCustomFieldForm("information_asset");
  const cf = useCustomFieldFacts("information_asset", detail?.id, { builtInLabels: ["Owner", "Business owner", "Guardian"] });

  const loadSummary = useCallback(() => {
    apiCall<Summary>("GET", "/assets/summary?asset_class=information_asset").then(setSummary).catch(() => {});
  }, []);

  useEffect(() => {
    const ignore = () => {};
    apiCall<MediaType[]>("GET", "/asset-media-types").then(setMediaTypes).catch(ignore);
    apiCall<LabelRow[]>("GET", "/asset-labels").then(setLabels).catch(ignore);
    apiCall<ClassificationType[]>("GET", "/asset-classification-types").then(setClassTypes).catch(ignore);

    loadSummary();
  }, [loadSummary]);

  // load the open record's full detail whenever the URL id changes
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

  const fetchAssets = useCallback(
    (qs: string) => apiCall<Page<Asset>>("GET", `/assets?asset_class=information_asset&${qs}`),
    [],
  );
  const searchItAssets = useCallback(
    (q: string) =>
      apiCall<Page<Asset>>("GET", `/assets?asset_class=it_asset&search=${encodeURIComponent(q)}&limit=20`).then((r) =>
        r.items.map((a) => ({ value: a.id, label: a.name, sub: cap(a.effective_criticality || "") })),
      ),
    [],
  );

  function openNew() { setEditing(null); setEditTab(undefined); setF(BLANK); cfForm.start(null); setError(null); setShowForm(true); }
  function openEdit(a: Asset, tab?: string) { setEditing(a); setEditTab(tab); setF(fromAsset(a)); cfForm.start(a.id); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      const payload = toPayload(f);
      const saved = editing
        ? await apiCall<Asset>("PATCH", `/assets/${editing.id}`, payload)
        : await apiCall<Asset>("POST", "/assets", payload);
      await cfForm.save(saved.id);
      setShowForm(false);
      setRefreshKey((k) => k + 1);
      loadSummary();
      if (openId) {
        loadDetail(openId);
        void gov.reload();
        void cf.reload();
      }
      toast(editing ? "Changes saved" : "Created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save information asset");
    } finally {
      setSaving(false);
    }
  }

  async function remove(a: Asset) {
    const ok = await confirmDeleteWithImpact("asset", a.id, a.name, {
      typeLabel: "information asset", confirmLabel: "Archive", note: "Linked risks stay in the risk register and are flagged for review.",
    });
    if (!ok) return;
    try {
      await apiCall<void>("DELETE", `/assets/${a.id}`);
      setShowForm(false);
      if (openId === a.id) setOpenId(null);
      setRefreshKey((k) => k + 1);
      loadSummary();
      toast(`Archived ${a.name}`);
    } catch (e) {
      toast(deleteErrorText(e, "Failed to delete the information asset"), "error");
    }
  }

  /** Link the chosen IT asset. Resolves true when the link was made (the form closes). */
  async function addDependency(): Promise<boolean> {
    if (!detail || !depAssetId) return false;
    setDepError(null);
    setLinking(true);
    try {
      await apiCall("POST", "/assets/dependencies", {
        information_asset_id: detail.id, it_asset_id: depAssetId, relationship_type: depRel, notes: depNotes,
      });
      setDepAssetId(null); setDepAssetLabel(""); setDepNotes(""); setDepRel("hosts");
      toast("IT asset linked");
      refresh();
      return true;
    } catch (e) {
      setDepError(e instanceof Error ? e.message : "Failed to link IT asset");
      return false;
    } finally {
      setLinking(false);
    }
  }
  async function removeDependency(depId: string) {
    if (!detail) return;
    if (!(await confirmDialog({ title: "Unlink this IT asset?", danger: true, confirmLabel: "Unlink" }))) return;
    try {
      await apiCall<void>("DELETE", `/assets/dependencies/${depId}`);
      refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to unlink IT asset", "error");
    }
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
    else if (p.kind === "open" && p.target === "link-it-asset") openLinkForm();
  }

  const mediaTypeOpts: Option[] = useMemo(() => mediaTypes.map((m) => ({ value: m.id, label: m.name })), [mediaTypes]);
  const labelOpts: Option[] = useMemo(() => labels.map((l) => ({ value: l.id, label: l.name })), [labels]);
  const classOpts: Option[] = useMemo(
    () =>
      classTypes.flatMap((t) =>
        t.classifications.map((c) => ({
          value: c.id,
          label: `${t.name}: ${c.name}`,
          sub: c.criteria || undefined,
        })),
      ),
    [classTypes],
  );

  /* Inline relation chips. The asset list returns {id,label} refs for its links. */
  // At most a dozen links per row; the rest is a count.
  const MAX_CHIPS = 12;
  const linkChips = (items: LinkRef[] | undefined, href: string) =>
    items && items.length ? (
      <div className="chips" onClick={(e) => e.stopPropagation()}>
        {items.slice(0, MAX_CHIPS).map((x) => <Link key={x.id} className="chip" href={`${href}?id=${x.id}`}>{x.label}</Link>)}
        {items.length > MAX_CHIPS && <span className="chip">+{(items.length - MAX_CHIPS).toLocaleString()} more</span>}
      </div>
    ) : <span className="muted">—</span>;
  const names = (items: LinkRef[] | undefined) => (items ?? []).map((x) => x.label).join(", ");
  /** A risk reads "R-002 Ransomware encrypts production systems" in the list, as on the record. */
  const riskLinks = (items: AssetRiskRef[] | undefined): LinkRef[] | undefined => items?.map((r) => ({ id: r.id, label: riskRowLabel(r) }));

  const columns: Column<Asset>[] = [
    { key: "name", header: "Name", sortable: true, locked: true, render: (a) => <span className="cell-title">{a.name}</span> },
    { key: "information_owner", header: "Information owner", render: (a) => <span className="muted">{a.information_owner || "—"}</span> },
    { key: "tier", header: "Tier", hidden: true, sortable: true, render: (a) => <span className="muted">{a.tier != null ? `Tier ${a.tier}` : "—"}</span>, text: (a) => (a.tier != null ? `Tier ${a.tier}` : "") },
    { key: "pci_scope", header: "PCI DSS scope", hidden: true, render: (a) => <span className="muted">{pciLabel(a.pci_scope) ?? "—"}</span>, text: (a) => pciLabel(a.pci_scope) ?? "" },
    { key: "owner", header: "Owning unit", hidden: true, sortable: true, render: (a) => <span className="muted">{a.owner?.label || "—"}</span>, text: (a) => a.owner?.label ?? "" },
    // Sorted server-side on the same effective criticality the badge shows.
    { key: "effective_criticality", header: "Business value", sortable: true, render: (a) => <CritBadge value={a.effective_criticality} />, text: (a) => cap(a.effective_criticality) },
    // The highest of the three quick C/I/A ratings — not the tenant's classification scheme.
    { key: "classification", header: "Highest CIA rating", render: (a) => <CritBadge value={maxCia(a)} />, text: (a) => cap(maxCia(a)) },
    { key: "cia", header: "C / I / A", hidden: true, render: (a) => <div className="chips"><span className="chip" title="Confidentiality">C {cap(a.confidentiality)}</span><span className="chip" title="Integrity">I {cap(a.integrity)}</span><span className="chip" title="Availability">A {cap(a.availability)}</span></div>, text: (a) => `${cap(a.confidentiality)} / ${cap(a.integrity)} / ${cap(a.availability)}` },
    { key: "label", header: "Handling label", hidden: true, render: (a) => a.label ? <Badge tone="neutral" plain>{a.label.label}</Badge> : <span className="muted">—</span>, text: (a) => a.label?.label ?? "" },
    { key: "data_categories", header: "Data categories", hidden: true, render: (a) => <span className="muted">{a.data_categories || "—"}</span> },
    { key: "records_volume", header: "Records", hidden: true, render: (a) => <span className="muted">{a.records_volume || "—"}</span> },
    { key: "self_assessed", header: "Self-assessed", sortable: true, render: (a) => (a.self_assessed ? <Badge tone="low">Self-assessed</Badge> : <Badge tone="neutral">Pending</Badge>), text: (a) => a.self_assessed ? "Yes" : "Pending" },
    { key: "assessed_by", header: "Assessed by", hidden: true, render: (a) => <span className="muted">{a.assessed_by ? `${a.assessed_by}${a.assessed_date ? ` · ${formatDate(a.assessed_date)}` : ""}` : "—"}</span>, text: (a) => a.assessed_by ?? "" },
    { key: "hosted", header: "Hosted on", align: "center", render: (a) => <span className="muted">{a.dependencies?.length || "—"}</span>, text: (a) => String(a.dependencies?.length ?? 0) },
    { key: "risks", header: "Risks", hidden: true, render: (a) => linkChips(riskLinks(a.risks), "/risks"), text: (a) => names(riskLinks(a.risks)) },
    { key: "processes", header: "Processes", hidden: true, render: (a) => linkChips(a.processes, "/processes"), text: (a) => names(a.processes) },
    { key: "requirements", header: "Requirements", hidden: true, render: (a) => linkChips(a.requirements, "/compliance"), text: (a) => names(a.requirements) },
    { key: "next_review_date", header: "Next review", hidden: true, render: (a) => <span className="muted">{formatDate(a.next_review_date)}</span>, text: (a) => (a.next_review_date ? formatDate(a.next_review_date) : "") },
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
    toastDeleteSummary(res, "information asset");
  }

  /* --------------------------------------------------------------- form tabs */
  const identityTab = (
    <>
      <Field label="Name" required help="For example: Customer master data, SWIFT payment messages, Loan origination records.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="e.g. Customer master data" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this data / application is and why it matters to the business." />
      </Field>
      <div className="field-row">
        <Field label="Media type" help="The information asset taxonomy (Data asset, Application…).">
          <Select value={f.media_type_id} onChange={(v) => set("media_type_id", v)} options={mediaTypeOpts} placeholder="— none —" />
          <InlineLookupCreate
            endpoint="/asset-media-types"
            onCreated={(r) => { setMediaTypes((p) => [...p, r as MediaType]); set("media_type_id", r.id); }}
          />
        </Field>
        <Field label="Business owner (identifies value)" help="The business owner accountable for this data and its value.">
          <TextInput value={f.information_owner} onChange={(v) => set("information_owner", v)} placeholder="e.g. Head of Retail Banking" />
        </Field>
      </div>
    </>
  );
  const valueTab = (
    <>
      <Field label="Business value" help="Set by the business owner — the data's value to the business.">
        <Select value={f.business_value} onChange={(v) => set("business_value", v)} options={CRIT} />
      </Field>
      <div className="field-row">
        <Field label="Confidentiality"><Select value={f.confidentiality} onChange={(v) => set("confidentiality", v)} options={CRIT} /></Field>
        <Field label="Integrity"><Select value={f.integrity} onChange={(v) => set("integrity", v)} options={CRIT} /></Field>
        <Field label="Availability"><Select value={f.availability} onChange={(v) => set("availability", v)} options={CRIT} /></Field>
      </div>
      {classOpts.length > 0 && (
        <Field
          label="Scheme classification"
          help="Formal classification against your organisation's scheme (managed in Settings → Lookups)."
        >
          <MultiSelect
            value={f.classification_ids}
            onChange={(v) => set("classification_ids", v)}
            options={classOpts}
            placeholder="Classify against each axis…"
          />
        </Field>
      )}
      <div className="field-row">
        <Field label="Handling label" help="Reusable handling / sensitivity label (Public, Confidential, PII…).">
          <Select value={f.label_id} onChange={(v) => set("label_id", v)} options={labelOpts} placeholder="— none —" />
          <InlineLookupCreate
            endpoint="/asset-labels"
            extra={{ color: "" }}
            onCreated={(r) => { setLabels((p) => [...p, r as LabelRow]); set("label_id", r.id); }}
          />
        </Field>
        <Field label="Records volume" help="Approximate number of records held.">
          <TextInput value={f.records_volume} onChange={(v) => set("records_volume", v)} placeholder="e.g. ~4.2M customers" />
        </Field>
      </div>
      <Field label="Data categories" help='Comma-separated. Include "PII" where personal data is held.'>
        <TextArea value={f.data_categories} onChange={(v) => set("data_categories", v)} rows={2} placeholder="e.g. PII, account numbers, transaction history, CNIC" />
      </Field>
      <Field label="Potential liabilities" help="The regulatory, contractual or financial exposure if this data is lost, altered or disclosed.">
        <TextArea value={f.potential_liabilities} onChange={(v) => set("potential_liabilities", v)} rows={2} placeholder="e.g. SBP penalties, customer notification, contractual damages" />
      </Field>
    </>
  );
  const selfAssessTab = (
    <>
      <Field label="Self-assessed" help="The business owner has completed the self-assessment for this asset.">
        <Toggle checked={f.self_assessed} onChange={(v) => set("self_assessed", v)} label="Self-assessment completed" />
      </Field>
      <div className="field-row">
        <Field label="Assessed by" help="Who signed off the self-assessment."><TextInput value={f.assessed_by} onChange={(v) => set("assessed_by", v)} placeholder="Business owner name" /></Field>
        <Field label="Assessed date"><TextInput type="date" value={f.assessed_date} onChange={(v) => set("assessed_date", v)} /></Field>
      </div>
      <div className="help">Upload the signed self-assessment form under Discussion &amp; files on the record — it is kept in the central repository.</div>
    </>
  );
  const governanceTab = (
    <>
      <div className="field-row">
        <Field label="Owner" help="Business unit accountable for this asset (RACI owner)."><BusinessUnitSelect value={f.owner_id} onChange={(id) => set("owner_id", id)} placeholder="— none —" /></Field>
        <Field label="Guardian" help="Business unit that safeguards / maintains the asset."><BusinessUnitSelect value={f.guardian_id} onChange={(id) => set("guardian_id", id)} placeholder="— none —" /></Field>
        <Field label="User" help="Business unit that uses the asset day to day."><BusinessUnitSelect value={f.user_id} onChange={(id) => set("user_id", id)} placeholder="— none —" /></Field>
      </div>
      <div className="field-row">
        <Field label="Tier" help="Service tier: Tier 1 is the most critical. Risks on this asset report its tier."><Select value={f.tier} onChange={(v) => set("tier", v)} options={TIER} placeholder="Not tiered" /></Field>
        <Field label="PCI DSS scope" help="In scope: this is cardholder data, or an application that stores, processes or transmits it."><Select value={f.pci_scope} onChange={(v) => set("pci_scope", v)} options={PCI_SCOPE} placeholder="Not assessed" /></Field>
      </div>
      <div className="field-row">
        <Field label="Review frequency" help="How often this asset's value / classification is re-attested. Approval is separate: submit the asset for review from its record."><Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} /></Field>
      </div>
    </>
  );

  /* --------------------------------------------------------------- the record (dossier) */
  const a = detail;
  const input: InfoAssetInput | null = a ? { asset: a, classTypes } : null;
  const checks = input ? ciaChecks(input) : [];
  const deps = a?.dependencies ?? [];
  /** The Unlink buttons' row labels (decision D3): the linked asset and the relationship,
   *  since one pair can be linked under several relationship types; still unique. */
  const unlinkLabels = uniqueLabels(deps.map((d) => `${linkRowLabel(d.it_asset)} (${sentenceCase(d.relationship_type).toLowerCase()})`));
  const riskCount = (a?.risks ?? []).length;

  const typeItems: MenuItem[] = [];
  if (a) {
    if (canWrite) typeItems.push({ label: "Link IT asset…", onClick: openLinkForm });
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
          key: "business_owner",
          label: "Business owner",
          value: (a.information_owner ?? "").trim() || null,
          hint: COPY.businessOwnerHint,
          gap: (a.information_owner ?? "").trim()
            ? undefined
            : { text: COPY.businessOwnerGap, fix: canWrite ? { label: "Name owner", onClick: () => openEdit(a, "identity") } : undefined },
        },
        {
          key: "units",
          label: "Owning unit · custodian",
          hint: COPY.unitsHint,
          value:
            a.owner || a.guardian || a.user ? (
              <span>
                {a.owner ? a.owner.label : <span className="muted rec-notset-v">{COPY.noOwningUnit}</span>}
                {" · "}
                {a.guardian ? a.guardian.label : <span className="muted rec-notset-v">{COPY.noCustodian}</span>}
              </span>
            ) : canWrite ? (
              <>
                <span className="muted rec-notset-v">{COPY.unitsNotSet}</span>
                <button type="button" className="rec-link" aria-label="Set owning unit and custodian" onClick={() => openEdit(a, "governance")}>
                  Set
                </button>
              </>
            ) : null,
          sub: userUnitSub(a.user),
        },
        { key: "label", label: "Handling label", value: a.label?.label ?? null },
      ]
    : [];

  const classFacts: FactItem[] = a
    ? [
        ...(input ? alsoClassified(input).map((f) => ({ ...f, tab: "value" })) : []),
        ...otherClassifications(a).map((c) => ({ key: `cls-${c.id}`, label: c.type_name || "Classification", value: c.name, tab: "value" })),
        { key: "label", label: "Handling label", value: a.label?.label ?? null, tab: "value" },
        { key: "media", label: "Media type", value: a.media_type?.label ?? null, tab: "identity" },
        {
          key: "categories",
          label: "Data categories",
          tab: "value",
          value: (a.data_categories ?? "").trim() ? (
            <>
              {a.data_categories}
              {hasPii(a) && <> <Badge tone="high" asIs>Contains PII</Badge></>}
            </>
          ) : null,
        },
        { key: "volume", label: "Records volume", value: (a.records_volume ?? "").trim() || null, tab: "value" },
        { key: "self", label: "Self-assessment", value: selfAssessmentText(a, fmt), tab: "self" },
        { key: "liabilities", label: "Potential liabilities", value: (a.potential_liabilities ?? "").trim() || null, tab: "value", wide: true },
      ]
    : [];

  const detailFacts: FactItem[] = a
    ? [
        { key: "owner", label: "Owning unit", value: a.owner?.label ?? null, tab: "governance" },
        { key: "guardian", label: "Guardian (custodian)", value: a.guardian?.label ?? null, tab: "governance" },
        { key: "user", label: "User unit", value: a.user?.label ?? null, tab: "governance" },
        { key: "tier", label: "Tier", value: a.tier != null ? `Tier ${a.tier}` : null, tab: "governance" },
        { key: "pci_scope", label: "PCI DSS scope", value: pciLabel(a.pci_scope), tab: "governance" },
        { key: "review", label: "Review cycle", value: reviewCycleText(a, fmt), tab: "governance" },
        ...(a.rto_hours != null || a.rpo_hours != null ? [{ key: "recovery", label: "Recovery objectives", value: recoveryText(a) }] : []),
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
        { key: "related", label: "Related assets", items: asRefs(a.related_assets), href: "/information-assets" },
        { key: "vendors", label: "Third parties", items: a.vendors, href: "/vendors" },
        { key: "access", label: "Access reviews", items: a.access_reviews, href: "/access-reviews" },
        { key: "continuity", label: "Continuity plans", items: a.continuity_plans, href: "/continuity" },
        { key: "bia", label: "Business impact analyses", items: a.bia_assessments, href: "/bia" },
        { key: "ropa", label: "Processing activities (RoPA)", items: a.processing_activities, href: "/privacy" },
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
          <h1>Information Asset Management</h1>
          <p>Primary assets — data and applications. Criticality is business value, set by the business owner, with CIA classification, handling labels and owner self-assessment.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <ImportExport resource="information-assets" label="Information Assets" exportQuery={exportQuery} exportCount={view?.total}
            onDone={() => { setRefreshKey((k) => k + 1); loadSummary(); }} />
          <GenerateRisks assetClass="information_asset" label="information assets" />
          <button className="btn" onClick={openNew}><IconPlus width={16} height={16} /> Add information asset</button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{summary ? summary.total.toLocaleString() : "…"}</span></div><span className="l">Information assets</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{summary ? summary.high_or_critical_value.toLocaleString() : "…"}</span></div><span className="l">High / critical value</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{summary ? `${summary.self_assessed_pct}%` : "…"}</span></div><span className="l">Self-assessed</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{summary ? summary.with_pii.toLocaleString() : "…"}</span></div><span className="l">Assets with PII</span></div>
      </div>

      <DataTable<Asset>
        toolbarRight={<ArchivedRecords entityType="asset" noun="assets" onRestored={() => { setRefreshKey((k) => k + 1); loadSummary(); }} refreshKey={refreshKey} />}
        tableKey="information-assets"
        filters={{ effective_criticality: critFilter || undefined, workflow_status: wfFilter || undefined, review_overdue: overdueFilter ? true : undefined, tier: tierFilter || undefined, pci_scope: pciFilter || undefined }}
        onApplyFilters={(f) => { setCritFilter(String(f.effective_criticality ?? "")); setWfFilter(String(f.workflow_status ?? "")); setOverdueFilter(f.review_overdue ? "overdue" : ""); setTierFilter(String(f.tier ?? "")); setPciFilter(String(f.pci_scope ?? "")); }}
        onViewChange={setView}
        toolbarLeft={
          <>
            <Select value={critFilter} onChange={setCritFilter} options={CRIT} placeholder="Any business value" />
            <Select value={wfFilter} onChange={setWfFilter} options={WORKFLOW_FILTER} placeholder="Any approval state" />
            <Select value={overdueFilter} onChange={setOverdueFilter} options={REVIEW_FILTER} placeholder="Any review state" />
            <Select value={tierFilter} onChange={setTierFilter} options={TIER} placeholder="Any tier" />
            <Select value={pciFilter} onChange={setPciFilter} options={PCI_SCOPE} placeholder="Any PCI DSS scope" />
          </>
        }
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
        searchPlaceholder="Search assets by name or owner…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No information assets yet. Register the data and applications that carry business value."
        refreshKey={refreshKey}
      />

      {/* Deep-linkable record (?id=, #section) — record-page-spec §4.3 */}
      <RecordDrawer
        variant="dossier"
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        governance={gov}
        identity={
          a
            ? {
                kind: "Information asset",
                backLabel: "Information Assets",
                name: a.name,
                lead: a.description,
                badges:
                  a.media_type || hasPii(a) ? (
                    <>
                      {a.media_type && (
                        <>
                          <span className="sep" aria-hidden="true">/</span>
                          <span>{a.media_type.label}</span>
                        </>
                      )}
                      {hasPii(a) && <Badge tone="high" asIs>Contains PII</Badge>}
                    </>
                  ) : null,
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
            <SummaryBand tiles={infoAssetTiles(input, ctx)} headline={infoAssetHeadline(input, ctx)} />
            <OpenPoints points={infoAssetOpenPoints(input, ctx)} canAct={canWrite} onAction={handlePoint} clearText={COPY.clearText} />
            <SectionNav />

            {/* 1. Classification — the quick ratings reconciled with the scheme */}
            <RecordSection
              id="classification"
              title="Classification"
              actions={
                canWrite ? (
                  <button type="button" className="btn secondary sm" onClick={() => openEdit(a, "value")}>Edit classification</button>
                ) : undefined
              }
            >
              <div className="rec-table-wrap">
                <table className="compact">
                  <thead>
                    <tr>
                      <th>Property</th>
                      <th>Rating (used in risk scoring)</th>
                      <th>Classification scheme</th>
                      <th>Agreement</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checks.map((c) => {
                      const ag = agreementText(c);
                      return (
                        <tr key={c.key}>
                          <td className="cell-title">{c.label}</td>
                          <td><SevBadge value={c.rating} /></td>
                          <td>
                            {c.scheme ? (
                              <>
                                <div>{schemeCellText(c)}</div>
                                {c.scheme.criteria && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{c.scheme.criteria}</div>}
                              </>
                            ) : (
                              <span className="muted">{COPY.noSchemeValue}</span>
                            )}
                          </td>
                          <td>{ag.tone === "none" ? <span className="muted">{ag.text}</span> : <span className={`rec-agree ${ag.tone}`}>{ag.text}</span>}</td>
                        </tr>
                      );
                    })}
                    <tr>
                      <td className="cell-title">Business value</td>
                      <td><SevBadge value={a.business_value} /></td>
                      <td><span className="muted">—</span></td>
                      <td><span className="muted">{COPY.businessValueAgreement}</span></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div style={{ marginTop: 16 }}>
                <FactList items={classFacts} onFillIn={canWrite ? (tab) => openEdit(a, tab) : undefined} />
              </div>
            </RecordSection>

            {/* 2. Hosted on — the link form opens on demand */}
            <RecordSection
              id="hosted"
              title="Hosted on (IT assets)"
              count={deps.length}
              sub={deps.length > 0 ? COPY.hostedSub : undefined}
              actions={
                canWrite ? (
                  <button
                    ref={linkTriggerRef}
                    type="button"
                    className="btn secondary sm"
                    aria-expanded={linkOpen}
                    aria-controls="link-it-asset-panel"
                    onClick={() => setLinkOpen((v) => !v)}
                  >
                    Link IT asset
                  </button>
                ) : undefined
              }
              empty={deps.length === 0 && !linkOpen ? COPY.hostedEmpty : undefined}
            >
              <Disclosure
                label="Link IT asset"
                hideTrigger
                open={linkOpen}
                onOpenChange={onLinkOpenChange}
                id="link-it-asset-panel"
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
                    <LabelledSearch label="IT asset" className="rec-link-pick">
                      <AsyncSelect search={searchItAssets} value={depAssetId} selectedLabel={depAssetLabel} placeholder="Search IT assets…" onChange={(v, o) => { setDepAssetId(v); setDepAssetLabel(o?.label || ""); }} />
                    </LabelledSearch>
                    <div style={{ width: 150 }}>
                      <label className="label" style={{ marginTop: 0 }} htmlFor="link-it-asset-rel">Relationship</label>
                      <select id="link-it-asset-rel" className="select" value={depRel} onChange={(e) => setDepRel(e.target.value)}>
                        {RELATIONSHIP.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                      </select>
                    </div>
                    <div style={{ flex: "1 1 160px" }}>
                      <label className="label" style={{ marginTop: 0 }} htmlFor="link-it-asset-notes">Notes</label>
                      <input id="link-it-asset-notes" className="input" value={depNotes} onChange={(e) => setDepNotes(e.target.value)} placeholder="Optional context" />
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
                        <th>IT asset</th>
                        <th>Relationship</th>
                        <th>Notes</th>
                        {canWrite && <th><span className="sr-only">Actions</span></th>}
                      </tr>
                    </thead>
                    <tbody>
                      {deps.map((d, i) => (
                        <tr key={d.id}>
                          <td className="cell-title">
                            {d.it_asset ? <Link href={`/it-assets?id=${d.it_asset.id}`}>{d.it_asset.label}</Link> : <span className="muted">{COPY.archivedLink}</span>}
                          </td>
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

            {/* 3. Details — accountability, the review cycle and custom fields */}
            <RecordSection
              id="details"
              title="Details"
              actions={canWrite ? <button type="button" className="btn secondary sm" aria-label="Edit details" onClick={() => openEdit(a, "governance")}>Edit</button> : undefined}
            >
              <FactList items={detailFacts} onFillIn={canWrite ? fillIn : undefined} />
              {cf.editor}
              {cf.editLink(canWrite)}
            </RecordSection>

            {/* 4. Linked records */}
            <RecordSection id="linked" title="Linked records" count={relatedCount(groups)}>
              <RelatedGroups groups={groups} />
            </RecordSection>

            {/* 5. Issues */}
            <RecordIssuesSection
              ref={issuesRef}
              entityId={a.id}
              entityKind="asset"
              entityRef={a.name}
              noun="information asset"
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
          assetClass="information_asset"
          assetIds={[a.id]}
          label={a.name}
          onDone={refresh}
        />
      )}

      {showForm && (
        <FormModal
          title={editing ? `Edit information asset — ${editing.name}` : "Add information asset"}
          wide
          tabs={[
            { id: "identity", label: "Identity", content: identityTab, required: true },
            { id: "value", label: "Business Value & Classification", content: valueTab },
            { id: "self", label: "Self-assessment", content: selfAssessTab },
            { id: "governance", label: "Governance", content: governanceTab },
            ...cfForm.tabs,
          ]}
          initialTab={editTab}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create information asset"}
          footerLeft={editing ? (
            <button className="btn secondary sm" type="button" onClick={() => remove(editing)} disabled={saving} style={{ color: "var(--red)" }}>Delete</button>
          ) : undefined}
        />
      )}
    </>
  );
}

export default function InformationAssetsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <InformationAssetsInner />
    </Suspense>
  );
}
