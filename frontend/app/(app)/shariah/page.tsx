"use client";

import { useEffect, useState } from "react";
import {
  api,
  type ShariahRuling,
  type IslamicProduct,
  type ShariahReview,
  type ShariahFinding,
  type CharityDisbursement,
} from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

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

export default function ShariahPage() {
  const [section, setSection] = useState<SectionId>("fatwa");
  const [error, setError] = useState<string | null>(null);

  const [rulings, setRulings] = useState<ShariahRuling[]>([]);
  const [products, setProducts] = useState<IslamicProduct[]>([]);
  const [reviews, setReviews] = useState<ShariahReview[]>([]);
  const [charities, setCharities] = useState<CharityDisbursement[]>([]);

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
  const setP = <K extends keyof ProductForm>(k: K, v: ProductForm[K]) => setPf((p) => ({ ...p, [k]: v }));

  // ---- review dialog + expanded detail ----
  const [editingReview, setEditingReview] = useState<ShariahReview | null>(null);
  const [showReviewForm, setShowReviewForm] = useState(false);
  const [savingReview, setSavingReview] = useState(false);
  const [vf, setVf] = useState<ReviewForm>(BLANK_REVIEW);
  const setV = <K extends keyof ReviewForm>(k: K, v: ReviewForm[K]) => setVf((p) => ({ ...p, [k]: v }));

  const [open, setOpen] = useState<ShariahReview | null>(null);
  const [fd, setFd] = useState<FindingDraft>(BLANK_FINDING);
  const setFD = <K extends keyof FindingDraft>(k: K, v: FindingDraft[K]) =>
    setFd((p) => ({ ...p, [k]: v }));

  // ---- charity dialog ----
  const [editingCharity, setEditingCharity] = useState<CharityDisbursement | null>(null);
  const [showCharityForm, setShowCharityForm] = useState(false);
  const [savingCharity, setSavingCharity] = useState(false);
  const [cf, setCf] = useState<CharityForm>(BLANK_CHARITY);
  const setC = <K extends keyof CharityForm>(k: K, v: CharityForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadRulings() {
    try {
      const res = await api.shariahRulings();
      setRulings(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load rulings");
    }
  }
  async function loadProducts() {
    try {
      const res = await api.islamicProducts();
      setProducts(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load products");
    }
  }
  async function loadReviews(keepOpen?: string) {
    try {
      const res = await api.shariahReviews();
      setReviews(res.items);
      if (keepOpen) setOpen(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load reviews");
    }
  }
  async function loadCharities() {
    try {
      const res = await api.charityLedger();
      setCharities(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load purification ledger");
    }
  }
  async function refreshOpen(id: string) {
    const r = await api.shariahReview(id);
    setOpen(r);
    setReviews((prev) => prev.map((x) => (x.id === id ? r : x)));
  }

  useEffect(() => {
    loadRulings();
    loadProducts();
    loadReviews();
    loadCharities();
  }, []);

  // ------------------------------------------------------------- ruling CRUD
  function openNewRuling() {
    setEditingRuling(null);
    setRf(BLANK_RULING);
    setShowRulingForm(true);
  }
  function openEditRuling(r: ShariahRuling) {
    setEditingRuling(r);
    setRf(fromRuling(r));
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
      await loadRulings();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save ruling");
    } finally {
      setSavingRuling(false);
    }
  }
  async function removeRuling(r: ShariahRuling) {
    if (!window.confirm(`Delete ruling ${r.reference || r.title}?`)) return;
    setError(null);
    try {
      await api.deleteShariahRuling(r.id);
      setShowRulingForm(false);
      await loadRulings();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- product CRUD
  function openNewProduct() {
    setEditingProduct(null);
    setPf(BLANK_PRODUCT);
    setShowProductForm(true);
  }
  function openEditProduct(p: IslamicProduct) {
    setEditingProduct(p);
    setPf(fromProduct(p));
    setShowProductForm(true);
  }
  async function saveProduct() {
    setError(null);
    setSavingProduct(true);
    try {
      const payload = productPayload(pf);
      if (editingProduct) await api.updateIslamicProduct(editingProduct.id, payload);
      else await api.createIslamicProduct(payload);
      setShowProductForm(false);
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save product");
    } finally {
      setSavingProduct(false);
    }
  }
  async function removeProduct(p: IslamicProduct) {
    if (!window.confirm(`Delete product ${p.reference || p.name}?`)) return;
    setError(null);
    try {
      await api.deleteIslamicProduct(p.id);
      setShowProductForm(false);
      await loadProducts();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- review CRUD
  function openNewReview() {
    setEditingReview(null);
    setVf(BLANK_REVIEW);
    setShowReviewForm(true);
  }
  function openEditReview(r: ShariahReview) {
    setEditingReview(r);
    setVf(fromReview(r));
    setShowReviewForm(true);
  }
  async function saveReview() {
    setError(null);
    setSavingReview(true);
    try {
      const payload = reviewPayload(vf);
      if (editingReview) await api.updateShariahReview(editingReview.id, payload);
      else await api.createShariahReview(payload);
      setShowReviewForm(false);
      await loadReviews(open?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save review");
    } finally {
      setSavingReview(false);
    }
  }
  async function removeReview(r: ShariahReview) {
    if (!window.confirm(`Delete review ${r.reference || r.title}?`)) return;
    setError(null);
    try {
      await api.deleteShariahReview(r.id);
      setShowReviewForm(false);
      if (open?.id === r.id) setOpen(null);
      await loadReviews();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleRow(r: ShariahReview) {
    setFd(BLANK_FINDING);
    setOpen(open?.id === r.id ? null : r);
  }

  // ------------------------------------------------------------- finding CRUD (inline)
  async function addFinding() {
    if (!open) return;
    setError(null);
    try {
      await api.addShariahFinding(open.id, {
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
      await refreshOpen(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add finding");
    }
  }
  async function changeFindingStatus(fid: string, status: string) {
    if (!open) return;
    setError(null);
    try {
      await api.updateShariahFinding(fid, { status });
      await refreshOpen(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update finding");
    }
  }
  async function removeFinding(fid: string) {
    if (!open) return;
    if (!window.confirm("Remove this finding?")) return;
    setError(null);
    try {
      await api.deleteShariahFinding(fid);
      await refreshOpen(open.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove finding");
    }
  }

  // ------------------------------------------------------------- charity CRUD
  function openNewCharity() {
    setEditingCharity(null);
    setCf(BLANK_CHARITY);
    setShowCharityForm(true);
  }
  function openEditCharity(c: CharityDisbursement) {
    setEditingCharity(c);
    setCf(fromCharity(c));
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
      await loadCharities();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save disbursement");
    } finally {
      setSavingCharity(false);
    }
  }
  async function removeCharity(c: CharityDisbursement) {
    if (!window.confirm(`Delete disbursement ${c.reference || c.description}?`)) return;
    setError(null);
    try {
      await api.deleteCharity(c.id);
      setShowCharityForm(false);
      await loadCharities();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const rulingOpts: Option[] = rulings.map((r) => ({
    value: r.id,
    label: `${r.reference || "—"} · ${r.title}`,
  }));
  const productOpts: Option[] = products.map((p) => ({ value: p.id, label: p.name, sub: p.reference }));

  const disbursedTotal = charities
    .filter((c) => c.status === "disbursed")
    .reduce((s, c) => s + (c.amount || 0), 0);

  // ------------------------------------------------------------- ruling form tabs
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

  // ------------------------------------------------------------- product form tabs
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
        <Select
          value={pf.approving_ruling_id}
          onChange={(v) => setP("approving_ruling_id", v)}
          options={rulingOpts}
          placeholder="—"
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
          <Select value={vf.product_id} onChange={(v) => setV("product_id", v)} options={productOpts} placeholder="—" />
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

  // ------------------------------------------------------------- charity form tabs
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
        <div className="card">
          <div className="card-head">
            <h3>Fatwa Register</h3>
            <span className="sub">{rulings.length} total · click a row to edit</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Title</th>
                  <th>Subject</th>
                  <th>Status</th>
                  <th>Approved by</th>
                  <th>Next review</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rulings.map((r) => (
                  <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openEditRuling(r)}>
                    <td className="ref">{r.reference || "—"}</td>
                    <td className="cell-title">{r.title}</td>
                    <td className="muted">{r.subject || "—"}</td>
                    <td><Badge tone={RULING_STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge></td>
                    <td className="muted">{r.approved_by || "—"}</td>
                    <td>
                      {r.is_review_overdue ? (
                        <Badge tone="high">Overdue</Badge>
                      ) : (
                        <span className="muted">{r.next_review_date || "—"}</span>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeRuling(r)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {rulings.length === 0 && (
                  <tr>
                    <td colSpan={7}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No rulings</h3>
                        <p>Record Shariah Board rulings and fatwas to govern your products.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= ISLAMIC PRODUCTS */}
      {section === "products" && (
        <div className="card">
          <div className="card-head">
            <h3>Islamic Products</h3>
            <span className="sub">{products.length} total · click a row to edit</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Name</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th>Owner</th>
                  <th>Launch date</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {products.map((p) => (
                  <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => openEditProduct(p)}>
                    <td className="ref">{p.reference || "—"}</td>
                    <td className="cell-title">{p.name}</td>
                    <td><Badge tone="info">{cap(p.shariah_mode)}</Badge></td>
                    <td><Badge tone={PRODUCT_STATUS_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                    <td className="muted">{p.owner || "—"}</td>
                    <td className="muted">{p.launch_date || "—"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => removeProduct(p)}>Delete</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {products.length === 0 && (
                  <tr>
                    <td colSpan={7}>
                      <div className="empty">
                        <span className="ico"><IconCheck width={24} height={24} /></span>
                        <h3>No products</h3>
                        <p>Register Islamic finance products and link them to approving rulings.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ============================================= SHARIAH REVIEWS */}
      {section === "reviews" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>Shariah Reviews</h3>
              <span className="sub">{reviews.length} total · click a row to manage SNC findings</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Title</th>
                    <th>Status</th>
                    <th>Reviewer</th>
                    <th>Findings</th>
                    <th>SNC income</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {reviews.map((r) => (
                    <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => toggleRow(r)}>
                      <td className="ref">{r.reference || "—"}</td>
                      <td className="cell-title">{r.title}</td>
                      <td><Badge tone={REVIEW_STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge></td>
                      <td className="muted">{r.reviewer || "—"}</td>
                      <td className="muted">{r.open_finding_count}/{r.finding_count} open</td>
                      <td className="muted">{money(r.snc_income_total)}</td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleRow(r)}>
                            {open?.id === r.id ? "Hide" : "Manage"}
                          </button>
                          <button className="btn secondary sm" onClick={() => removeReview(r)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {reviews.length === 0 && (
                    <tr>
                      <td colSpan={7}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No reviews</h3>
                          <p>Plan a Shariah review to record non-compliance findings and income to purify.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {open && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{open.reference} — {open.title}</h3>
                    <span className="sub">
                      {cap(open.status)} · reviewer {open.reviewer || "unassigned"}
                      {open.rating ? " · rating " + cap(open.rating) : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                    <div style={{ textAlign: "right" }}>
                      <div className="muted" style={{ fontSize: 12 }}>SNC income to purify</div>
                      <strong style={{ fontSize: 18 }}>{money(open.snc_income_total)}</strong>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn secondary sm" onClick={() => api.pdfShariahReview(open.id, open.reference).catch(() => {})}>Report PDF</button>
                      <button className="btn secondary sm" onClick={() => openEditReview(open)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => removeReview(open)}>Delete</button>
                    </div>
                  </div>
                </div>

                {/* --- SNC findings --- */}
                <div className="card-pad">
                  <strong>SNC findings</strong>
                  <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
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
                        {open.findings.map((fi: ShariahFinding) => (
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
                        {open.findings.length === 0 && (
                          <tr><td colSpan={8}><span className="muted">No findings raised yet.</span></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <RecordPanels model="shariah_review" entityId={open.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= PURIFICATION LEDGER */}
      {section === "ledger" && (
        <>
          <div className="grid stat-grid">
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{money(disbursedTotal)}</span>
              </div>
              <span className="l">Total disbursed</span>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Purification Ledger</h3>
              <span className="sub">{charities.length} total · click a row to edit</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Description</th>
                    <th>Amount</th>
                    <th>Beneficiary</th>
                    <th>Status</th>
                    <th>Disbursed</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {charities.map((c) => (
                    <tr key={c.id} style={{ cursor: "pointer" }} onClick={() => openEditCharity(c)}>
                      <td className="ref">{c.reference || "—"}</td>
                      <td className="cell-title">{c.description}</td>
                      <td className="muted">{money(c.amount)} {c.currency}</td>
                      <td className="muted">{c.beneficiary || "—"}</td>
                      <td><Badge tone={CHARITY_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge></td>
                      <td className="muted">{c.disbursement_date || "—"}</td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => removeCharity(c)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {charities.length === 0 && (
                    <tr>
                      <td colSpan={7}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No disbursements</h3>
                          <p>Record purification of Shariah non-compliant income disbursed to charity.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

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
