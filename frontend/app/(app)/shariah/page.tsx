"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import {
  api,
  apiCall,
  type ShariahRuling,
  type IslamicProduct,
  type ShariahReview,
  type ShariahFinding,
  type CharityDisbursement,
} from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import AsyncSelect, { type Option as AsyncOption } from "@/components/AsyncSelect";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const money = (n: number | null | undefined) =>
  n == null ? "—" : Number(n).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });

// ------------------------------------------------------------------ enum lists
const RULING_STATUS = opts(["draft", "under_review", "approved", "superseded"]);
const REVIEW_FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const SHARIAH_MODE = opts([
  "murabaha",
  "ijarah",
  "musharakah",
  "diminishing_musharakah",
  "mudarabah",
  "salam",
  "istisna",
  "wakala",
  "tawarruq",
  "qard",
  "other",
]);
const PRODUCT_STATUS = opts(["in_development", "approved", "active", "suspended", "withdrawn"]);
const REVIEW_TYPE = opts(["product", "branch", "transaction", "process"]);
const REVIEW_STATUS = opts(["planned", "in_progress", "completed"]);
const RATING = opts(["low", "medium", "high", "critical"]);
const CHARITY_STATUS = opts(["pending", "approved", "disbursed"]);
const FINDING_STATUS = ["open", "in_progress", "remediated", "closed"];

// ------------------------------------------------------------------ tones
const SEVERITY_TONE: Record<string, Tone> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};
const RULING_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  under_review: "info",
  approved: "low",
  superseded: "neutral",
};
const PRODUCT_STATUS_TONE: Record<string, Tone> = {
  in_development: "neutral",
  approved: "low",
  active: "info",
  suspended: "medium",
  withdrawn: "neutral",
};
const REVIEW_STATUS_TONE: Record<string, Tone> = {
  planned: "neutral",
  in_progress: "info",
  completed: "low",
};
const FINDING_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  in_progress: "info",
  remediated: "medium",
  closed: "low",
};
const CHARITY_STATUS_TONE: Record<string, Tone> = {
  pending: "neutral",
  approved: "info",
  disbursed: "low",
};

function SeverityBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={SEVERITY_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

const rulingLabel = (r: ShariahRuling) => `${r.reference || "—"} · ${r.title}`;

// ------------------------------------------------------------------ form state
type RulingForm = {
  title: string;
  subject: string;
  status: string;
  approved_by: string;
  issued_date: string;
  ruling_text: string;
  basis: string;
  review_frequency: string;
  next_review_date: string;
  workflow_status: string;
};
const BLANK_RULING: RulingForm = {
  title: "",
  subject: "",
  status: "draft",
  approved_by: "",
  issued_date: "",
  ruling_text: "",
  basis: "",
  review_frequency: "annual",
  next_review_date: "",
  workflow_status: "draft",
};
function fromRuling(r: ShariahRuling): RulingForm {
  return {
    title: r.title,
    subject: r.subject || "",
    status: r.status || "draft",
    approved_by: r.approved_by || "",
    issued_date: r.issued_date || "",
    ruling_text: r.ruling_text || "",
    basis: r.basis || "",
    review_frequency: r.review_frequency || "annual",
    next_review_date: r.next_review_date || "",
    workflow_status: r.workflow_status || "draft",
  };
}
function rulingPayload(f: RulingForm): Record<string, unknown> {
  return {
    title: f.title,
    subject: f.subject,
    status: f.status,
    approved_by: f.approved_by,
    issued_date: f.issued_date || null,
    ruling_text: f.ruling_text,
    basis: f.basis,
    review_frequency: f.review_frequency,
    next_review_date: f.next_review_date || null,
    workflow_status: f.workflow_status,
  };
}

type ProductForm = {
  name: string;
  shariah_mode: string;
  status: string;
  owner: string;
  launch_date: string;
  approving_ruling_id: string;
  description: string;
  structure: string;
  workflow_status: string;
};
const BLANK_PRODUCT: ProductForm = {
  name: "",
  shariah_mode: "murabaha",
  status: "in_development",
  owner: "",
  launch_date: "",
  approving_ruling_id: "",
  description: "",
  structure: "",
  workflow_status: "draft",
};
function fromProduct(p: IslamicProduct): ProductForm {
  return {
    name: p.name,
    shariah_mode: p.shariah_mode || "murabaha",
    status: p.status || "in_development",
    owner: p.owner || "",
    launch_date: p.launch_date || "",
    approving_ruling_id: p.approving_ruling_id || "",
    description: p.description || "",
    structure: p.structure || "",
    workflow_status: p.workflow_status || "draft",
  };
}
function productPayload(f: ProductForm): Record<string, unknown> {
  return {
    name: f.name,
    shariah_mode: f.shariah_mode,
    status: f.status,
    owner: f.owner,
    launch_date: f.launch_date || null,
    approving_ruling_id: f.approving_ruling_id || null,
    description: f.description,
    structure: f.structure,
    workflow_status: f.workflow_status,
  };
}

type ReviewForm = {
  title: string;
  product_id: string;
  review_type: string;
  reviewer: string;
  status: string;
  scope: string;
  period_start: string;
  period_end: string;
  planned_date: string;
  rating: string;
  conclusion: string;
  workflow_status: string;
};
const BLANK_REVIEW: ReviewForm = {
  title: "",
  product_id: "",
  review_type: "product",
  reviewer: "",
  status: "planned",
  scope: "",
  period_start: "",
  period_end: "",
  planned_date: "",
  rating: "",
  conclusion: "",
  workflow_status: "draft",
};
function fromReview(r: ShariahReview): ReviewForm {
  return {
    title: r.title,
    product_id: r.product_id || "",
    review_type: r.review_type || "product",
    reviewer: r.reviewer || "",
    status: r.status || "planned",
    scope: r.scope || "",
    period_start: r.period_start || "",
    period_end: r.period_end || "",
    planned_date: r.planned_date || "",
    rating: r.rating || "",
    conclusion: r.conclusion || "",
    workflow_status: r.workflow_status || "draft",
  };
}
function reviewPayload(f: ReviewForm): Record<string, unknown> {
  return {
    title: f.title,
    product_id: f.product_id || null,
    review_type: f.review_type,
    reviewer: f.reviewer,
    status: f.status,
    scope: f.scope,
    period_start: f.period_start || null,
    period_end: f.period_end || null,
    planned_date: f.planned_date || null,
    rating: f.rating || null,
    conclusion: f.conclusion,
    workflow_status: f.workflow_status,
  };
}

type CharityForm = {
  description: string;
  amount: string;
  currency: string;
  beneficiary: string;
  status: string;
  disbursement_date: string;
  notes: string;
  workflow_status: string;
};
const BLANK_CHARITY: CharityForm = {
  description: "",
  amount: "",
  currency: "PKR",
  beneficiary: "",
  status: "pending",
  disbursement_date: "",
  notes: "",
  workflow_status: "draft",
};
function fromCharity(c: CharityDisbursement): CharityForm {
  return {
    description: c.description,
    amount: c.amount != null ? String(c.amount) : "",
    currency: c.currency || "PKR",
    beneficiary: c.beneficiary || "",
    status: c.status || "pending",
    disbursement_date: c.disbursement_date || "",
    notes: c.notes || "",
    workflow_status: c.workflow_status || "draft",
  };
}
function charityPayload(f: CharityForm): Record<string, unknown> {
  return {
    description: f.description,
    amount: f.amount === "" ? 0 : Number(f.amount),
    currency: f.currency,
    beneficiary: f.beneficiary,
    status: f.status,
    disbursement_date: f.disbursement_date || null,
    notes: f.notes,
    workflow_status: f.workflow_status,
  };
}

type FindingDraft = {
  title: string;
  description: string;
  severity: string;
  snc_income_amount: string;
  recommendation: string;
  management_response: string;
  action_owner: string;
  due_date: string;
  status: string;
};
const BLANK_FINDING: FindingDraft = {
  title: "",
  description: "",
  severity: "medium",
  snc_income_amount: "",
  recommendation: "",
  management_response: "",
  action_owner: "",
  due_date: "",
  status: "open",
};

type SectionId = "fatwa" | "products" | "reviews" | "ledger";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "fatwa", label: "Fatwa Register" },
  { id: "products", label: "Islamic Products" },
  { id: "reviews", label: "Shariah Reviews" },
  { id: "ledger", label: "Purification Ledger" },
];

// ------------------------------------------------------------------ server typeahead
const searchRulings = (q: string) =>
  apiCall<PagedList<ShariahRuling>>("GET", `/shariah-rulings?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
    r.items.map((x) => ({ value: x.id, label: rulingLabel(x) })),
  );
const searchProducts = (q: string) =>
  apiCall<PagedList<IslamicProduct>>("GET", `/islamic-products?search=${encodeURIComponent(q)}&limit=20`).then((r) =>
    r.items.map((x) => ({ value: x.id, label: x.name, sub: x.reference })),
  );

// ================================================================= page =====
function ShariahInner() {
  const [section, setSection] = useState<SectionId>("fatwa");
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  // ---- ruling dialog ----
  const [editingRuling, setEditingRuling] = useState<ShariahRuling | null>(null);
  const [showRulingForm, setShowRulingForm] = useState(false);
  const [savingRuling, setSavingRuling] = useState(false);
  const [rf, setRf] = useState<RulingForm>(BLANK_RULING);
  const setR = <K extends keyof RulingForm>(k: K, v: RulingForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  // ---- product dialog ----
  const [editingProduct, setEditingProduct] = useState<IslamicProduct | null>(null);
  const [showProductForm, setShowProductForm] = useState(false);
  const [savingProduct, setSavingProduct] = useState(false);
  const [pf, setPf] = useState<ProductForm>(BLANK_PRODUCT);
  const [rulingSelLabel, setRulingSelLabel] = useState(""); // display label for the approving ruling
  const setP = <K extends keyof ProductForm>(k: K, v: ProductForm[K]) => setPf((p) => ({ ...p, [k]: v }));

  // ---- review dialog + drawer detail ----
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<ShariahReview | null>(null);
  const [editingReview, setEditingReview] = useState<ShariahReview | null>(null);
  const [showReviewForm, setShowReviewForm] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  const [vf, setVf] = useState<ReviewForm>(BLANK_REVIEW);
  const [productSelLabel, setProductSelLabel] = useState(""); // display label for the review's product
  const setV = <K extends keyof ReviewForm>(k: K, v: ReviewForm[K]) => setVf((p) => ({ ...p, [k]: v }));

  const [fd, setFd] = useState<FindingDraft>(BLANK_FINDING);
  const setFD = <K extends keyof FindingDraft>(k: K, v: FindingDraft[K]) => setFd((p) => ({ ...p, [k]: v }));

  // ---- charity dialog ----
  const [editingCharity, setEditingCharity] = useState<CharityDisbursement | null>(null);
  const [showCharityForm, setShowCharityForm] = useState(false);
  const [savingCharity, setSavingCharity] = useState(false);
  const [cf, setCf] = useState<CharityForm>(BLANK_CHARITY);
  const setC = <K extends keyof CharityForm>(k: K, v: CharityForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ---- server summary (authoritative total, not a client reduce over a capped page) ----
  const [disbursedTotal, setDisbursedTotal] = useState<number | null>(null);
  const loadSummary = useCallback(() => {
    apiCall<{ disbursed_total: number }>("GET", "/charity-ledger-summary")
      .then((s) => setDisbursedTotal(s.disbursed_total ?? 0))
      .catch(() => {});
  }, []);
  useEffect(() => {
    loadSummary();
  }, [loadSummary]);

  // ------------------------------------------------------------- table fetchers
  const fetchRulings = useCallback((qs: string) => apiCall<PagedList<ShariahRuling>>("GET", `/shariah-rulings?${qs}`), []);
  const fetchProducts = useCallback((qs: string) => apiCall<PagedList<IslamicProduct>>("GET", `/islamic-products?${qs}`), []);
  const fetchReviews = useCallback((qs: string) => apiCall<PagedList<ShariahReview>>("GET", `/shariah-reviews?${qs}`), []);
  const fetchCharities = useCallback((qs: string) => apiCall<PagedList<CharityDisbursement>>("GET", `/charity-ledger?${qs}`), []);

  // ------------------------------------------------------------- review drawer detail
  const loadDetail = useCallback((id: string) => {
    apiCall<ShariahReview>("GET", `/shariah-reviews/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
  }, [openId, loadDetail]);

  // ------------------------------------------------------------- ruling CRUD
  function openNewRuling() {
    setEditingRuling(null);
    setRf(BLANK_RULING);
    setError(null);
    setShowRulingForm(true);
  }
  function openEditRuling(r: ShariahRuling) {
    setEditingRuling(r);
    setRf(fromRuling(r));
    setError(null);
    setShowRulingForm(true);
  }
  async function saveRuling() {
    setError(null);
    setSavingRuling(true);
    try {
      const payload = rulingPayload(rf);
      if (editingRuling) await api.updateShariahRuling(editingRuling.id, payload);
      else await api.createShariahRuling(payload);
      setShowRulingForm(false);
      reload();
      toast(editingRuling ? "Changes saved" : "Ruling created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save ruling");
    } finally {
      setSavingRuling(false);
    }
  }
  async function removeRuling(r: ShariahRuling) {
    if (!(await confirmDialog({ title: `Delete ruling ${r.reference || r.title}?`, danger: true }))) return;
    setError(null);
    try {
      await api.deleteShariahRuling(r.id);
      setShowRulingForm(false);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- product CRUD
  function openNewProduct() {
    setEditingProduct(null);
    setPf(BLANK_PRODUCT);
    setRulingSelLabel("");
    setError(null);
    setShowProductForm(true);
  }
  function openEditProduct(p: IslamicProduct) {
    setEditingProduct(p);
    setPf(fromProduct(p));
    setRulingSelLabel("");
    setError(null);
    setShowProductForm(true);
    if (p.approving_ruling_id) {
      apiCall<ShariahRuling>("GET", `/shariah-rulings/${p.approving_ruling_id}`)
        .then((r) => setRulingSelLabel(rulingLabel(r)))
        .catch(() => {});
    }
  }
  async function saveProduct() {
    setError(null);
    setSavingProduct(true);
    try {
      const payload = productPayload(pf);
      if (editingProduct) await api.updateIslamicProduct(editingProduct.id, payload);
      else await api.createIslamicProduct(payload);
      setShowProductForm(false);
      reload();
      toast(editingProduct ? "Changes saved" : "Product created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save product");
    } finally {
      setSavingProduct(false);
    }
  }
  async function removeProduct(p: IslamicProduct) {
    if (!(await confirmDialog({ title: `Delete product ${p.reference || p.name}?`, danger: true }))) return;
    setError(null);
    try {
      await api.deleteIslamicProduct(p.id);
      setShowProductForm(false);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- review CRUD
  function openNewReview() {
    setEditingReview(null);
    setVf(BLANK_REVIEW);
    setProductSelLabel("");
    setError(null);
    setShowReviewForm(true);
  }
  function openEditReview(r: ShariahReview) {
    setEditingReview(r);
    setVf(fromReview(r));
    setProductSelLabel("");
    setError(null);
    setShowReviewForm(true);
    if (r.product_id) {
      apiCall<IslamicProduct>("GET", `/islamic-products/${r.product_id}`)
        .then((p) => setProductSelLabel(p.name))
        .catch(() => {});
    }
  }
  async function saveReview() {
    setError(null);
    setSavingReview(true);
    try {
      const payload = reviewPayload(vf);
      if (editingReview) await api.updateShariahReview(editingReview.id, payload);
      else await api.createShariahReview(payload);
      setShowReviewForm(false);
      reload();
      if (openId) loadDetail(openId);
      toast(editingReview ? "Changes saved" : "Review created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save review");
    } finally {
      setSavingReview(false);
    }
  }
  async function removeReview(r: ShariahReview) {
    if (!(await confirmDialog({ title: `Delete review ${r.reference || r.title}?`, danger: true }))) return;
    setError(null);
    try {
      await api.deleteShariahReview(r.id);
      setShowReviewForm(false);
      if (openId === r.id) setOpenId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- finding CRUD (in drawer)
  async function addFinding() {
    if (!detail) return;
    setError(null);
    try {
      await api.addShariahFinding(detail.id, {
        title: fd.title,
        description: fd.description,
        severity: fd.severity,
        snc_income_amount: fd.snc_income_amount === "" ? null : Number(fd.snc_income_amount),
        recommendation: fd.recommendation,
        management_response: fd.management_response,
        action_owner: fd.action_owner,
        due_date: fd.due_date || null,
        status: fd.status,
      });
      setFd(BLANK_FINDING);
      loadDetail(detail.id);
      reload();
      toast("Finding raised");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add finding");
    }
  }
  async function changeFindingStatus(fid: string, status: string) {
    if (!detail) return;
    setError(null);
    try {
      await api.updateShariahFinding(fid, { status });
      loadDetail(detail.id);
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
      await api.deleteShariahFinding(fid);
      loadDetail(detail.id);
      reload();
      toast("Finding removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove finding");
    }
  }

  // ------------------------------------------------------------- charity CRUD
  function openNewCharity() {
    setEditingCharity(null);
    setCf(BLANK_CHARITY);
    setError(null);
    setShowCharityForm(true);
  }
  function openEditCharity(c: CharityDisbursement) {
    setEditingCharity(c);
    setCf(fromCharity(c));
    setError(null);
    setShowCharityForm(true);
  }
  async function saveCharity() {
    setError(null);
    setSavingCharity(true);
    try {
      const payload = charityPayload(cf);
      if (editingCharity) await api.updateCharity(editingCharity.id, payload);
      else await api.createCharity(payload);
      setShowCharityForm(false);
      reload();
      loadSummary();
      toast(editingCharity ? "Changes saved" : "Disbursement recorded");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save disbursement");
    } finally {
      setSavingCharity(false);
    }
  }
  async function removeCharity(c: CharityDisbursement) {
    if (!(await confirmDialog({ title: `Delete disbursement ${c.reference || c.description}?`, danger: true }))) return;
    setError(null);
    try {
      await api.deleteCharity(c.id);
      setShowCharityForm(false);
      reload();
      loadSummary();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- columns
  const rulingCols: Column<ShariahRuling>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (r) => <span className="cell-title">{r.title}</span> },
    { key: "subject", header: "Subject", sortable: true, render: (r) => <span className="muted">{r.subject || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={RULING_STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge> },
    { key: "approved_by", header: "Approved by", sortable: true, render: (r) => <span className="muted">{r.approved_by || "—"}</span> },
    { key: "next_review_date", header: "Next review", sortable: true, render: (r) => (r.is_review_overdue ? <Badge tone="high">Overdue</Badge> : <span className="muted">{r.next_review_date || "—"}</span>) },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditRuling(r)}>Edit</button> <button className="btn secondary sm" onClick={() => removeRuling(r)}>Delete</button></div> },
  ];
  const productCols: Column<IslamicProduct>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (p) => <span className="ref">{p.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, render: (p) => <span className="cell-title">{p.name}</span> },
    { key: "shariah_mode", header: "Mode", sortable: true, render: (p) => <Badge tone="info">{cap(p.shariah_mode)}</Badge> },
    { key: "status", header: "Status", sortable: true, render: (p) => <Badge tone={PRODUCT_STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge> },
    { key: "owner", header: "Owner", sortable: true, render: (p) => <span className="muted">{p.owner || "—"}</span> },
    { key: "launch_date", header: "Launch date", sortable: true, render: (p) => <span className="muted">{p.launch_date || "—"}</span> },
    { key: "actions", header: "", render: (p) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditProduct(p)}>Edit</button> <button className="btn secondary sm" onClick={() => removeProduct(p)}>Delete</button></div> },
  ];
  const reviewCols: Column<ShariahReview>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (r) => <span className="cell-title">{r.title}</span> },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={REVIEW_STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge> },
    { key: "reviewer", header: "Reviewer", sortable: true, render: (r) => <span className="muted">{r.reviewer || "—"}</span> },
    { key: "findings", header: "Findings", render: (r) => <span className="muted">{r.open_finding_count}/{r.finding_count} open</span> },
    { key: "snc_income_total", header: "SNC income", render: (r) => <span className="muted">{money(r.snc_income_total)}</span> },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => setOpenId(r.id)}>Manage</button> <button className="btn secondary sm" onClick={() => removeReview(r)}>Delete</button></div> },
  ];
  const charityCols: Column<CharityDisbursement>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "description", header: "Description", sortable: true, render: (c) => <span className="cell-title">{c.description}</span> },
    { key: "amount", header: "Amount", sortable: true, render: (c) => <span className="muted">{money(c.amount)} {c.currency}</span> },
    { key: "beneficiary", header: "Beneficiary", sortable: true, render: (c) => <span className="muted">{c.beneficiary || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (c) => <Badge tone={CHARITY_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge> },
    { key: "disbursement_date", header: "Disbursed", sortable: true, render: (c) => <span className="muted">{c.disbursement_date || "—"}</span> },
    { key: "actions", header: "", render: (c) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditCharity(c)}>Edit</button> <button className="btn secondary sm" onClick={() => removeCharity(c)}>Delete</button></div> },
  ];

  // ------------------------------------------------------------- ruling form tab
  const rulingGeneral = (
    <>
      <Field label="Title" required help="For example: Permissibility of commodity murabaha for liquidity.">
        <TextInput value={rf.title} onChange={(v) => setR("title", v)} placeholder="Ruling title" required />
      </Field>
      <div className="field-row">
        <Field label="Subject" help="What the ruling concerns.">
          <TextInput value={rf.subject} onChange={(v) => setR("subject", v)} placeholder="Commodity murabaha" />
        </Field>
        <Field label="Status">
          <Select value={rf.status} onChange={(v) => setR("status", v)} options={RULING_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Approved by" help="Shariah Board / scholar who issued the ruling.">
          <TextInput value={rf.approved_by} onChange={(v) => setR("approved_by", v)} placeholder="Shariah Board" />
        </Field>
        <Field label="Issued date">
          <TextInput type="date" value={rf.issued_date} onChange={(v) => setR("issued_date", v)} />
        </Field>
      </div>
      <Field label="Ruling text" help="The text of the fatwa / resolution.">
        <RichText value={rf.ruling_text} onChange={(v) => setR("ruling_text", v)} placeholder="Record the ruling…" />
      </Field>
      <Field label="Basis" help="Scriptural / juristic basis and references.">
        <TextArea value={rf.basis} onChange={(v) => setR("basis", v)} rows={3} placeholder="Quran, Sunnah, AAOIFI standard…" />
      </Field>
      <div className="field-row">
        <Field label="Review frequency" help="How often the ruling should be revisited.">
          <Select value={rf.review_frequency} onChange={(v) => setR("review_frequency", v)} options={REVIEW_FREQ} />
        </Field>
        <Field label="Next review date" help="Leave blank to derive from the frequency.">
          <TextInput type="date" value={rf.next_review_date} onChange={(v) => setR("next_review_date", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this ruling record.">
        <Select value={rf.workflow_status} onChange={(v) => setR("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- product form tab
  const productGeneral = (
    <>
      <Field label="Name" required help="For example: Home Musharakah Finance.">
        <TextInput value={pf.name} onChange={(v) => setP("name", v)} placeholder="Product name" required />
      </Field>
      <div className="field-row">
        <Field label="Shariah mode" help="Islamic mode of finance / contract type.">
          <Select value={pf.shariah_mode} onChange={(v) => setP("shariah_mode", v)} options={SHARIAH_MODE} />
        </Field>
        <Field label="Status">
          <Select value={pf.status} onChange={(v) => setP("status", v)} options={PRODUCT_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={pf.owner} onChange={(v) => setP("owner", v)} placeholder="Product owner" />
        </Field>
        <Field label="Launch date">
          <TextInput type="date" value={pf.launch_date} onChange={(v) => setP("launch_date", v)} />
        </Field>
      </div>
      <Field label="Approving ruling" help="The Shariah ruling that approves this product structure.">
        <AsyncSelect
          search={searchRulings}
          value={pf.approving_ruling_id || null}
          selectedLabel={rulingSelLabel}
          onChange={(v, o) => {
            setP("approving_ruling_id", v || "");
            setRulingSelLabel(o?.label || "");
          }}
          placeholder="Search rulings…"
        />
      </Field>
      <Field label="Description">
        <TextArea value={pf.description} onChange={(v) => setP("description", v)} rows={3} placeholder="What the product offers." />
      </Field>
      <Field label="Structure" help="How the contract is structured and executed.">
        <TextArea value={pf.structure} onChange={(v) => setP("structure", v)} rows={3} placeholder="Contract flow and steps." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this product record.">
        <Select value={pf.workflow_status} onChange={(v) => setP("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- review form tabs
  const reviewGeneral = (
    <>
      <Field label="Title" required help="For example: Q3 branch Shariah compliance review.">
        <TextInput value={vf.title} onChange={(v) => setV("title", v)} placeholder="Review title" required />
      </Field>
      <div className="field-row">
        <Field label="Product" help="The Islamic product under review, if applicable.">
          <AsyncSelect
            search={searchProducts}
            value={vf.product_id || null}
            selectedLabel={productSelLabel}
            onChange={(v, o) => {
              setV("product_id", v || "");
              setProductSelLabel(o?.label || "");
            }}
            placeholder="Search products…"
          />
        </Field>
        <Field label="Review type">
          <Select value={vf.review_type} onChange={(v) => setV("review_type", v)} options={REVIEW_TYPE} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Reviewer" help="Shariah auditor / reviewer.">
          <TextInput value={vf.reviewer} onChange={(v) => setV("reviewer", v)} placeholder="Name" />
        </Field>
        <Field label="Status">
          <Select value={vf.status} onChange={(v) => setV("status", v)} options={REVIEW_STATUS} />
        </Field>
      </div>
      <Field label="Scope">
        <TextArea value={vf.scope} onChange={(v) => setV("scope", v)} rows={3} placeholder="What is in and out of scope." />
      </Field>
    </>
  );

  const reviewTiming = (
    <>
      <div className="field-row">
        <Field label="Period start" help="Start of the period under review.">
          <TextInput type="date" value={vf.period_start} onChange={(v) => setV("period_start", v)} />
        </Field>
        <Field label="Period end">
          <TextInput type="date" value={vf.period_end} onChange={(v) => setV("period_end", v)} />
        </Field>
      </div>
      <Field label="Planned date" help="Target date for the review.">
        <TextInput type="date" value={vf.planned_date} onChange={(v) => setV("planned_date", v)} />
      </Field>
    </>
  );

  const reviewConclusion = (
    <>
      <Field label="Rating" help="Overall Shariah compliance rating.">
        <Select value={vf.rating} onChange={(v) => setV("rating", v)} options={RATING} placeholder="— No rating —" />
      </Field>
      <Field label="Conclusion">
        <RichText value={vf.conclusion} onChange={(v) => setV("conclusion", v)} placeholder="Summarise the review conclusion…" />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this review record.">
        <Select value={vf.workflow_status} onChange={(v) => setV("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- charity form tab
  const charityGeneral = (
    <>
      <Field label="Description" required help="What the disbursement is for.">
        <TextInput value={cf.description} onChange={(v) => setC("description", v)} placeholder="Disbursement description" required />
      </Field>
      <div className="field-row">
        <Field label="Amount" help="Tainted income being purified.">
          <TextInput type="number" value={cf.amount} onChange={(v) => setC("amount", v)} placeholder="0.00" />
        </Field>
        <Field label="Currency">
          <TextInput value={cf.currency} onChange={(v) => setC("currency", v)} placeholder="PKR" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Beneficiary" help="Charity / recipient of the disbursement.">
          <TextInput value={cf.beneficiary} onChange={(v) => setC("beneficiary", v)} placeholder="Approved charity" />
        </Field>
        <Field label="Status">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={CHARITY_STATUS} />
        </Field>
      </div>
      <Field label="Disbursement date">
        <TextInput type="date" value={cf.disbursement_date} onChange={(v) => setC("disbursement_date", v)} />
      </Field>
      <Field label="Notes">
        <TextArea value={cf.notes} onChange={(v) => setC("notes", v)} rows={3} placeholder="Additional notes." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this disbursement record.">
        <Select value={cf.workflow_status} onChange={(v) => setC("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Islamic / Shariah Governance</h1>
          <p>Fatwa register, Islamic product oversight, Shariah reviews with SNC findings, and purification of non-compliant income.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "fatwa" && (
            <button className="btn" onClick={openNewRuling}>
              <IconPlus width={16} height={16} /> New ruling
            </button>
          )}
          {section === "products" && (
            <button className="btn" onClick={openNewProduct}>
              <IconPlus width={16} height={16} /> New product
            </button>
          )}
          {section === "reviews" && (
            <button className="btn" onClick={openNewReview}>
              <IconPlus width={16} height={16} /> New review
            </button>
          )}
          {section === "ledger" && (
            <button className="btn" onClick={openNewCharity}>
              <IconPlus width={16} height={16} /> New disbursement
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

      {/* ============================================= FATWA REGISTER */}
      {section === "fatwa" && (
        <DataTable<ShariahRuling>
          columns={rulingCols}
          fetcher={fetchRulings}
          rowKey={(r) => r.id}
          onRowClick={(r) => openEditRuling(r)}
          searchPlaceholder="Search rulings by title, subject or reference…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No rulings yet. Record Shariah Board rulings and fatwas to govern your products."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= ISLAMIC PRODUCTS */}
      {section === "products" && (
        <DataTable<IslamicProduct>
          columns={productCols}
          fetcher={fetchProducts}
          rowKey={(p) => p.id}
          onRowClick={(p) => openEditProduct(p)}
          searchPlaceholder="Search products by name, reference or owner…"
          defaultSort={{ by: "name", dir: "asc" }}
          emptyMessage="No products yet. Register Islamic finance products and link them to approving rulings."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= SHARIAH REVIEWS */}
      {section === "reviews" && (
        <DataTable<ShariahReview>
          columns={reviewCols}
          fetcher={fetchReviews}
          rowKey={(r) => r.id}
          onRowClick={(r) => setOpenId(r.id)}
          activeKey={openId}
          searchPlaceholder="Search reviews by title, reviewer or reference…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No reviews yet. Plan a Shariah review to record non-compliance findings and income to purify."
          refreshKey={refreshKey}
        />
      )}

      {/* ============================================= PURIFICATION LEDGER */}
      {section === "ledger" && (
        <>
          <div className="grid stat-grid">
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{disbursedTotal == null ? "…" : money(disbursedTotal)}</span>
              </div>
              <span className="l">Total disbursed</span>
            </div>
          </div>

          <DataTable<CharityDisbursement>
            columns={charityCols}
            fetcher={fetchCharities}
            rowKey={(c) => c.id}
            onRowClick={(c) => openEditCharity(c)}
            searchPlaceholder="Search ledger by description, beneficiary or reference…"
            defaultSort={{ by: "created_at", dir: "desc" }}
            emptyMessage="No disbursements yet. Record purification of Shariah non-compliant income disbursed to charity."
            refreshKey={refreshKey}
          />
        </>
      )}

      {/* ============================================= REVIEW DRAWER (SNC findings) */}
      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference} — ${detail.title}` : "…"}
        subtitle={
          detail
            ? `${cap(detail.status)} · reviewer ${detail.reviewer || "unassigned"}${detail.rating ? " · rating " + cap(detail.rating) : ""}`
            : ""
        }
        width={900}
        actions={
          detail && (
            <>
              <button className="btn secondary sm" onClick={() => api.pdfShariahReview(detail.id, detail.reference).catch(() => {})}>Report PDF</button>
              <button className="btn secondary sm" onClick={() => openEditReview(detail)}>Edit</button>
              <button className="btn secondary sm" onClick={() => removeReview(detail)}>Delete</button>
            </>
          )
        }
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 16, alignItems: "center", justifyContent: "space-between", padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16, flexWrap: "wrap" }}>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Badge tone={REVIEW_STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
                {detail.rating && <SeverityBadge value={detail.rating} />}
                <Badge tone="neutral" plain>{detail.open_finding_count}/{detail.finding_count} open</Badge>
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="muted" style={{ fontSize: 12 }}>SNC income to purify</div>
                <strong style={{ fontSize: 18 }}>{money(detail.snc_income_total)}</strong>
              </div>
            </div>

            {/* --- SNC findings --- */}
            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>SNC findings</h3></div>
              <div className="card-pad">
                <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
                  Shariah non-compliance issues raised by this review and their remediation status.
                </p>
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(ev) => { ev.preventDefault(); addFinding(); }}
                >
                  <div style={{ flex: "1 1 180px" }}>
                    <label className="label">Title</label>
                    <input className="input" value={fd.title} onChange={(ev) => setFD("title", ev.target.value)} placeholder="Finding title" required />
                  </div>
                  <div style={{ width: 130 }}>
                    <label className="label">Severity</label>
                    <select className="select" value={fd.severity} onChange={(ev) => setFD("severity", ev.target.value)}>
                      {RATING.map((r) => (<option key={r.value} value={r.value}>{r.label}</option>))}
                    </select>
                  </div>
                  <div style={{ width: 160 }}>
                    <label className="label">SNC income to purify</label>
                    <input className="input" type="number" value={fd.snc_income_amount} onChange={(ev) => setFD("snc_income_amount", ev.target.value)} placeholder="0.00" />
                  </div>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Description</label>
                    <input className="input" value={fd.description} onChange={(ev) => setFD("description", ev.target.value)} placeholder="What is non-compliant" />
                  </div>
                  <div style={{ flex: "1 1 180px" }}>
                    <label className="label">Recommendation</label>
                    <input className="input" value={fd.recommendation} onChange={(ev) => setFD("recommendation", ev.target.value)} placeholder="Proposed remediation" />
                  </div>
                  <div style={{ flex: "1 1 180px" }}>
                    <label className="label">Management response</label>
                    <input className="input" value={fd.management_response} onChange={(ev) => setFD("management_response", ev.target.value)} placeholder="Agreed action" />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Action owner</label>
                    <input className="input" value={fd.action_owner} onChange={(ev) => setFD("action_owner", ev.target.value)} placeholder="Owner" />
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label">Due date</label>
                    <input className="input" type="date" value={fd.due_date} onChange={(ev) => setFD("due_date", ev.target.value)} />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Status</label>
                    <select className="select" value={fd.status} onChange={(ev) => setFD("status", ev.target.value)}>
                      {FINDING_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                    </select>
                  </div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ref</th>
                        <th>Title</th>
                        <th>Severity</th>
                        <th>SNC income</th>
                        <th>Action owner</th>
                        <th>Due</th>
                        <th>Status</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.findings.map((fi: ShariahFinding) => (
                        <tr key={fi.id}>
                          <td className="ref">{fi.reference || "—"}</td>
                          <td className="cell-title">{fi.title}</td>
                          <td><SeverityBadge value={fi.severity} /></td>
                          <td className="muted">{money(fi.snc_income_amount)}</td>
                          <td className="muted">{fi.action_owner || "—"}</td>
                          <td>
                            {fi.is_overdue ? (
                              <Badge tone="high">Overdue</Badge>
                            ) : (
                              <span className="muted">{fi.due_date || "—"}</span>
                            )}
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                              <Badge tone={FINDING_STATUS_TONE[fi.status] || "neutral"}>{cap(fi.status)}</Badge>
                              <select
                                className="select"
                                style={{ width: 140 }}
                                value={fi.status}
                                onChange={(ev) => changeFindingStatus(fi.id, ev.target.value)}
                              >
                                {FINDING_STATUS.map((s) => (<option key={s} value={s}>{cap(s)}</option>))}
                              </select>
                            </div>
                          </td>
                          <td>
                            <button className="btn secondary sm" onClick={() => removeFinding(fi.id)}>Remove</button>
                          </td>
                        </tr>
                      ))}
                      {detail.findings.length === 0 && (
                        <tr><td colSpan={8}><span className="muted">No findings raised yet.</span></td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <RecordPanels model="shariah_review" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {/* ============================================= MODALS */}
      {showRulingForm && (
        <FormModal
          title={editingRuling ? `Edit ruling — ${editingRuling.reference || editingRuling.title}` : "New ruling"}
          wide
          tabs={[{ id: "general", label: "General", content: rulingGeneral, required: true }]}
          onClose={() => setShowRulingForm(false)}
          onSave={saveRuling}
          saving={savingRuling}
          error={error}
          saveLabel={editingRuling ? "Save changes" : "Create ruling"}
          footerLeft={
            editingRuling ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeRuling(editingRuling)}
                disabled={savingRuling}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showProductForm && (
        <FormModal
          title={editingProduct ? `Edit product — ${editingProduct.reference || editingProduct.name}` : "New product"}
          wide
          tabs={[{ id: "general", label: "General", content: productGeneral, required: true }]}
          onClose={() => setShowProductForm(false)}
          onSave={saveProduct}
          saving={savingProduct}
          error={error}
          saveLabel={editingProduct ? "Save changes" : "Create product"}
          footerLeft={
            editingProduct ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeProduct(editingProduct)}
                disabled={savingProduct}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showReviewForm && (
        <FormModal
          title={editingReview ? `Edit review — ${editingReview.reference || editingReview.title}` : "New review"}
          wide
          tabs={[
            { id: "general", label: "General", content: reviewGeneral, required: true },
            { id: "timing", label: "Timing", content: reviewTiming },
            { id: "conclusion", label: "Conclusion", content: reviewConclusion },
          ]}
          onClose={() => setShowReviewForm(false)}
          onSave={saveReview}
          saving={savingReview}
          error={error}
          saveLabel={editingReview ? "Save changes" : "Create review"}
          footerLeft={
            editingReview ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeReview(editingReview)}
                disabled={savingReview}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showCharityForm && (
        <FormModal
          title={editingCharity ? `Edit disbursement — ${editingCharity.reference || editingCharity.description}` : "New disbursement"}
          tabs={[{ id: "general", label: "General", content: charityGeneral, required: true }]}
          onClose={() => setShowCharityForm(false)}
          onSave={saveCharity}
          saving={savingCharity}
          error={error}
          saveLabel={editingCharity ? "Save changes" : "Create disbursement"}
          footerLeft={
            editingCharity ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeCharity(editingCharity)}
                disabled={savingCharity}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

export default function ShariahPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ShariahInner />
    </Suspense>
  );
}
