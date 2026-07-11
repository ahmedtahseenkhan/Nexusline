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
import { IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ local types
interface Declaration {
  id: string;
  campaign_id: string;
  reference: string;
  declarant_name: string;
  declarant_role: string;
  business_unit: string;
  has_disclosure: boolean;
  disclosure_details: string;
  amount: number | null;
  currency: string;
  submitted_date: string | null;
  status: string;
  reviewer: string;
  review_notes: string;
  created_at: string;
}
interface DeclarationCampaign {
  id: string;
  reference: string;
  title: string;
  description: string;
  declaration_type: string;
  period: string;
  due_date: string | null;
  owner: string;
  status: string;
  workflow_status: string;
  declaration_count: number;
  disclosure_count: number;
  created_at: string;
  declarations: Declaration[];
}
interface DeclarationSummary {
  campaigns_open: number;
  declarations_submitted: number;
  declarations_pending: number;
  disclosures_flagged: number;
  by_declaration_type: { declaration_type: string; campaigns: number; declarations: number; disclosures: number }[];
}

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const pkr = (n: number | null | undefined, ccy = "PKR") =>
  n == null ? "—" : `${ccy} ${Number(n).toLocaleString()}`;

// ------------------------------------------------------------------ enum lists
const DECLARATION_TYPE = opts([
  "conflict_of_interest",
  "gifts_entertainment",
  "personal_account_dealing",
  "outside_employment",
  "related_party",
  "code_of_conduct",
]);
const CAMPAIGN_STATUS = opts(["draft", "open", "closed"]);
const DECL_STATUS = opts(["pending", "submitted", "reviewed", "escalated", "cleared"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

// ------------------------------------------------------------------ tones
const CAMPAIGN_STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  open: "info",
  closed: "low",
};
const DECL_STATUS_TONE: Record<string, Tone> = {
  pending: "high",
  submitted: "info",
  reviewed: "medium",
  escalated: "critical",
  cleared: "low",
};

function DisclosureBadge({ has }: { has: boolean }) {
  return has ? <Badge tone="high">Disclosure</Badge> : <span className="muted">None</span>;
}

// ------------------------------------------------------------------ campaign form state
type CampaignForm = {
  title: string;
  declaration_type: string;
  period: string;
  owner: string;
  status: string;
  due_date: string;
  description: string;
  workflow_status: string;
};
const BLANK_CAMPAIGN: CampaignForm = {
  title: "",
  declaration_type: "conflict_of_interest",
  period: "",
  owner: "",
  status: "draft",
  due_date: "",
  description: "",
  workflow_status: "draft",
};
function fromCampaign(c: DeclarationCampaign): CampaignForm {
  return {
    title: c.title,
    declaration_type: c.declaration_type || "conflict_of_interest",
    period: c.period || "",
    owner: c.owner || "",
    status: c.status || "draft",
    due_date: c.due_date || "",
    description: c.description || "",
    workflow_status: c.workflow_status || "draft",
  };
}
function campaignPayload(f: CampaignForm): Record<string, unknown> {
  return {
    title: f.title,
    declaration_type: f.declaration_type,
    period: f.period,
    owner: f.owner,
    status: f.status,
    due_date: f.due_date || null,
    description: f.description,
    workflow_status: f.workflow_status,
  };
}

// ------------------------------------------------------------------ inline declaration draft
type DeclDraft = {
  declarant_name: string;
  declarant_role: string;
  business_unit: string;
  has_disclosure: boolean;
  disclosure_details: string;
  amount: string;
  status: string;
};
const BLANK_DECL_DRAFT: DeclDraft = {
  declarant_name: "",
  declarant_role: "",
  business_unit: "",
  has_disclosure: false,
  disclosure_details: "",
  amount: "",
  status: "submitted",
};

// ------------------------------------------------------------------ declaration edit form state
type DeclForm = {
  declarant_name: string;
  declarant_role: string;
  business_unit: string;
  has_disclosure: boolean;
  disclosure_details: string;
  amount: string;
  currency: string;
  submitted_date: string;
  status: string;
  reviewer: string;
  review_notes: string;
};
const BLANK_DECL: DeclForm = {
  declarant_name: "",
  declarant_role: "",
  business_unit: "",
  has_disclosure: false,
  disclosure_details: "",
  amount: "",
  currency: "PKR",
  submitted_date: "",
  status: "pending",
  reviewer: "",
  review_notes: "",
};
function fromDecl(d: Declaration): DeclForm {
  return {
    declarant_name: d.declarant_name || "",
    declarant_role: d.declarant_role || "",
    business_unit: d.business_unit || "",
    has_disclosure: !!d.has_disclosure,
    disclosure_details: d.disclosure_details || "",
    amount: d.amount != null ? String(d.amount) : "",
    currency: d.currency || "PKR",
    submitted_date: d.submitted_date || "",
    status: d.status || "pending",
    reviewer: d.reviewer || "",
    review_notes: d.review_notes || "",
  };
}
function declPayload(f: DeclForm): Record<string, unknown> {
  return {
    declarant_name: f.declarant_name,
    declarant_role: f.declarant_role,
    business_unit: f.business_unit,
    has_disclosure: f.has_disclosure,
    disclosure_details: f.disclosure_details,
    amount: f.amount === "" ? null : Number(f.amount),
    currency: f.currency,
    submitted_date: f.submitted_date || null,
    status: f.status,
    reviewer: f.reviewer,
    review_notes: f.review_notes,
  };
}

// ------------------------------------------------------------------ sections
type SectionId = "campaigns" | "declarations";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "campaigns", label: "Campaigns" },
  { id: "declarations", label: "All Declarations" },
];

function DeclarationsInner() {
  const [section, setSection] = useState<SectionId>("campaigns");
  const [error, setError] = useState<string | null>(null);

  const [summary, setSummary] = useState<DeclarationSummary | null>(null);
  const [disclosuresOnly, setDisclosuresOnly] = useState(false);

  // campaign reference lookup for the flat declarations table (labels only)
  const [campaignRef, setCampaignRef] = useState<Map<string, string>>(new Map());

  const [campaignKey, setCampaignKey] = useState(0);
  const [declKey, setDeclKey] = useState(0);
  const reloadCampaigns = useCallback(() => setCampaignKey((k) => k + 1), []);
  const reloadDecls = useCallback(() => setDeclKey((k) => k + 1), []);

  const fetchCampaigns = useCallback((qs: string) => apiCall<PagedList<DeclarationCampaign>>("GET", `/declaration-campaigns?${qs}`), []);
  const fetchDeclarations = useCallback((qs: string) => apiCall<PagedList<Declaration>>("GET", `/declarations?${qs}`), []);

  const loadSummary = useCallback(() => {
    apiCall<DeclarationSummary>("GET", "/declarations-summary").then(setSummary).catch((e) => setError(e instanceof Error ? e.message : "Failed to load declaration summary"));
  }, []);
  const loadCampaignRefs = useCallback(() => {
    apiCall<PagedList<DeclarationCampaign>>("GET", "/declaration-campaigns?limit=200")
      .then((r) => setCampaignRef(new Map(r.items.map((c) => [c.id, c.reference || c.title]))))
      .catch(() => {});
  }, []);
  useEffect(() => { loadSummary(); loadCampaignRefs(); }, [loadSummary, loadCampaignRefs]);

  // ---- campaign drawer (URL-driven) ----
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<DeclarationCampaign | null>(null);
  const [dd, setDd] = useState<DeclDraft>(BLANK_DECL_DRAFT);
  const setDD = <K extends keyof DeclDraft>(k: K, v: DeclDraft[K]) => setDd((p) => ({ ...p, [k]: v }));

  const loadDetail = useCallback((id: string) => {
    apiCall<DeclarationCampaign>("GET", `/declaration-campaigns/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) loadDetail(openId);
    else setDetail(null);
    setDd(BLANK_DECL_DRAFT);
  }, [openId, loadDetail]);

  // ---- campaign edit dialog ----
  const [editingCampaign, setEditingCampaign] = useState<DeclarationCampaign | null>(null);
  const [showCampaignForm, setShowCampaignForm] = useState(false);
  const [savingCampaign, setSavingCampaign] = useState(false);
  const [cf, setCf] = useState<CampaignForm>(BLANK_CAMPAIGN);
  const setC = <K extends keyof CampaignForm>(k: K, v: CampaignForm[K]) => setCf((p) => ({ ...p, [k]: v }));

  // ---- declaration edit dialog ----
  const [editingDecl, setEditingDecl] = useState<Declaration | null>(null);
  const [showDeclForm, setShowDeclForm] = useState(false);
  const [savingDecl, setSavingDecl] = useState(false);
  const [df, setDf] = useState<DeclForm>(BLANK_DECL);
  const setD = <K extends keyof DeclForm>(k: K, v: DeclForm[K]) => setDf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- campaign CRUD
  function openNewCampaign() {
    setEditingCampaign(null);
    setCf(BLANK_CAMPAIGN);
    setError(null);
    setShowCampaignForm(true);
  }
  function openEditCampaign(c: DeclarationCampaign) {
    setEditingCampaign(c);
    setCf(fromCampaign(c));
    setError(null);
    setShowCampaignForm(true);
  }
  async function saveCampaign() {
    setError(null);
    setSavingCampaign(true);
    try {
      const payload = campaignPayload(cf);
      if (editingCampaign) await apiCall<DeclarationCampaign>("PATCH", `/declaration-campaigns/${editingCampaign.id}`, payload);
      else await apiCall<DeclarationCampaign>("POST", "/declaration-campaigns", payload);
      setShowCampaignForm(false);
      reloadCampaigns();
      loadSummary();
      loadCampaignRefs();
      if (openId) loadDetail(openId);
      toast(editingCampaign ? "Changes saved" : "Campaign created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save campaign");
    } finally {
      setSavingCampaign(false);
    }
  }
  async function removeCampaign(c: DeclarationCampaign) {
    if (!(await confirmDialog({ title: `Delete declaration campaign ${c.reference || c.title}?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/declaration-campaigns/${c.id}`);
      setShowCampaignForm(false);
      if (openId === c.id) setOpenId(null);
      reloadCampaigns();
      reloadDecls();
      loadSummary();
      loadCampaignRefs();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- inline declaration add
  async function addDeclaration() {
    if (!detail) return;
    setError(null);
    try {
      await apiCall<DeclarationCampaign>("POST", `/declaration-campaigns/${detail.id}/declarations`, {
        declarant_name: dd.declarant_name,
        declarant_role: dd.declarant_role,
        business_unit: dd.business_unit,
        has_disclosure: dd.has_disclosure,
        disclosure_details: dd.disclosure_details,
        amount: dd.amount === "" ? null : Number(dd.amount),
        status: dd.status,
      });
      setDd(BLANK_DECL_DRAFT);
      loadDetail(detail.id);
      reloadCampaigns();
      reloadDecls();
      loadSummary();
      toast("Declaration added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add declaration");
    }
  }
  async function removeDeclaration(declId: string) {
    if (!(await confirmDialog({ title: "Remove this declaration?", danger: true, confirmLabel: "Remove" }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/declarations/${declId}`);
      if (detail) loadDetail(detail.id);
      reloadCampaigns();
      reloadDecls();
      loadSummary();
      toast("Removed");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove declaration");
    }
  }

  // ------------------------------------------------------------- declaration edit CRUD
  function openEditDecl(d: Declaration) {
    setEditingDecl(d);
    setDf(fromDecl(d));
    setError(null);
    setShowDeclForm(true);
  }
  async function saveDecl() {
    if (!editingDecl) return;
    setError(null);
    setSavingDecl(true);
    try {
      await apiCall<Declaration>("PATCH", `/declarations/${editingDecl.id}`, declPayload(df));
      setShowDeclForm(false);
      if (detail) loadDetail(detail.id);
      reloadCampaigns();
      reloadDecls();
      loadSummary();
      toast("Changes saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save declaration");
    } finally {
      setSavingDecl(false);
    }
  }

  // ------------------------------------------------------------- columns
  const campaignColumns: Column<DeclarationCampaign>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (c) => <span className="ref">{c.reference || "—"}</span> },
    { key: "title", header: "Title", sortable: true, render: (c) => <span className="cell-title">{c.title}</span> },
    { key: "declaration_type", header: "Type", sortable: true, render: (c) => <Badge tone="info">{cap(c.declaration_type)}</Badge> },
    { key: "period", header: "Period", sortable: true, render: (c) => <span className="muted">{c.period || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (c) => <Badge tone={CAMPAIGN_STATUS_TONE[c.status] || "neutral"}>{cap(c.status)}</Badge> },
    { key: "declaration_count", header: "Declarations", align: "center", render: (c) => <span className="muted">{c.declaration_count}</span> },
    { key: "disclosure_count", header: "Disclosures", align: "center", render: (c) => (c.disclosure_count > 0 ? <Badge tone="high">{c.disclosure_count}</Badge> : <span className="muted">0</span>) },
    { key: "due_date", header: "Due", sortable: true, render: (c) => <span className="muted">{c.due_date || "—"}</span> },
    { key: "actions", header: "", render: (c) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => setOpenId(c.id)}>Manage</button> <button className="btn secondary sm" onClick={() => removeCampaign(c)}>Delete</button></div> },
  ];

  const declColumns: Column<Declaration>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (d) => <span className="ref">{d.reference || "—"}</span> },
    { key: "campaign", header: "Campaign", render: (d) => <span className="muted">{campaignRef.get(d.campaign_id) || "—"}</span> },
    { key: "declarant_name", header: "Declarant", sortable: true, render: (d) => <span className="cell-title">{d.declarant_name || "—"}{d.declarant_role ? <span className="muted"> · {d.declarant_role}</span> : null}</span> },
    { key: "business_unit", header: "Business unit", sortable: true, render: (d) => <span className="muted">{d.business_unit || "—"}</span> },
    { key: "disclosure", header: "Disclosure", render: (d) => <DisclosureBadge has={d.has_disclosure} /> },
    { key: "amount", header: "Amount", render: (d) => <span className="muted">{d.amount != null ? pkr(d.amount, d.currency) : "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (d) => <Badge tone={DECL_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge> },
    { key: "submitted_date", header: "Submitted", sortable: true, render: (d) => <span className="muted">{d.submitted_date || "—"}</span> },
    { key: "actions", header: "", render: (d) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => removeDeclaration(d.id)}>Remove</button></div> },
  ];

  // ------------------------------------------------------------- campaign form tabs
  const campaignGeneral = (
    <>
      <Field label="Title" required help="For example: FY26 annual conflict-of-interest attestation.">
        <TextInput value={cf.title} onChange={(v) => setC("title", v)} placeholder="Campaign title" required />
      </Field>
      <div className="field-row">
        <Field label="Declaration type" help="The kind of attestation this campaign collects.">
          <Select value={cf.declaration_type} onChange={(v) => setC("declaration_type", v)} options={DECLARATION_TYPE} />
        </Field>
        <Field label="Status">
          <Select value={cf.status} onChange={(v) => setC("status", v)} options={CAMPAIGN_STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Period" help="Attestation period, e.g. FY26 or Q1 2026.">
          <TextInput value={cf.period} onChange={(v) => setC("period", v)} placeholder="FY26" />
        </Field>
        <Field label="Owner" help="Compliance owner accountable for the campaign.">
          <TextInput value={cf.owner} onChange={(v) => setC("owner", v)} placeholder="Head of Compliance" />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={cf.description} onChange={(v) => setC("description", v)} rows={3} placeholder="Scope, staff population and instructions." />
      </Field>
    </>
  );
  const campaignTiming = (
    <>
      <Field label="Due date" help="Target date by which all staff must submit.">
        <TextInput type="date" value={cf.due_date} onChange={(v) => setC("due_date", v)} />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this campaign record.">
        <Select value={cf.workflow_status} onChange={(v) => setC("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- declaration form tabs
  const declGeneral = (
    <>
      <div className="field-row">
        <Field label="Declarant name">
          <TextInput value={df.declarant_name} onChange={(v) => setD("declarant_name", v)} placeholder="Staff member" />
        </Field>
        <Field label="Role">
          <TextInput value={df.declarant_role} onChange={(v) => setD("declarant_role", v)} placeholder="Relationship Manager" />
        </Field>
      </div>
      <Field label="Business unit">
        <TextInput value={df.business_unit} onChange={(v) => setD("business_unit", v)} placeholder="Corporate Banking" />
      </Field>
      <Field label="Disclosure made">
        <Toggle checked={df.has_disclosure} onChange={(v) => setD("has_disclosure", v)} label="This submission discloses a conflict / gift / interest" />
      </Field>
      <Field label="Disclosure details" help="What is being disclosed (gift, directorship, trade, relationship…).">
        <TextArea value={df.disclosure_details} onChange={(v) => setD("disclosure_details", v)} rows={3} placeholder="Details of the disclosure." />
      </Field>
      <div className="field-row">
        <Field label="Amount" help="Value of a declared gift / interest (PKR).">
          <TextInput type="number" value={df.amount} onChange={(v) => setD("amount", v)} placeholder="0" />
        </Field>
        <Field label="Currency">
          <TextInput value={df.currency} onChange={(v) => setD("currency", v)} placeholder="PKR" />
        </Field>
      </div>
    </>
  );
  const declReview = (
    <>
      <div className="field-row">
        <Field label="Status" help="Review lifecycle of this submission.">
          <Select value={df.status} onChange={(v) => setD("status", v)} options={DECL_STATUS} />
        </Field>
        <Field label="Submitted date">
          <TextInput type="date" value={df.submitted_date} onChange={(v) => setD("submitted_date", v)} />
        </Field>
      </div>
      <Field label="Reviewer" help="Compliance officer who reviewed this submission.">
        <TextInput value={df.reviewer} onChange={(v) => setD("reviewer", v)} placeholder="Reviewer" />
      </Field>
      <Field label="Review notes" help="Disposition, conditions imposed, or escalation rationale.">
        <TextArea value={df.review_notes} onChange={(v) => setD("review_notes", v)} rows={3} placeholder="Review outcome and notes." />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Compliance Declarations</h1>
          <p>Periodic and event-driven staff declarations — conflict of interest, gifts &amp; entertainment, personal account dealing, outside employment and code of conduct — with disclosure review and escalation.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "campaigns" && (
            <button className="btn" onClick={openNewCampaign}>
              <IconPlus width={16} height={16} /> New campaign
            </button>
          )}
        </div>
      </div>

      <div className="grid stat-grid" style={{ marginBottom: 16 }}>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.campaigns_open.toLocaleString() : "—"}</span></div>
          <span className="l">Open campaigns</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.declarations_submitted.toLocaleString() : "—"}</span></div>
          <span className="l">Declarations submitted</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.declarations_pending.toLocaleString() : "—"}</span></div>
          <span className="l">Pending</span>
        </div>
        <div className="card stat">
          <div className="stat-top"><span className="n">{summary ? summary.disclosures_flagged.toLocaleString() : "—"}</span></div>
          <span className="l">Disclosures flagged</span>
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

      {/* ============================================= CAMPAIGNS */}
      {section === "campaigns" && (
        <DataTable<DeclarationCampaign>
          columns={campaignColumns}
          fetcher={fetchCampaigns}
          rowKey={(c) => c.id}
          onRowClick={(c) => setOpenId(c.id)}
          activeKey={openId}
          searchPlaceholder="Search campaigns by title or reference…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No declaration campaigns. Launch one to collect staff attestations and disclosures."
          refreshKey={campaignKey}
        />
      )}

      {/* ============================================= ALL DECLARATIONS */}
      {section === "declarations" && (
        <DataTable<Declaration>
          columns={declColumns}
          fetcher={fetchDeclarations}
          rowKey={(d) => d.id}
          onRowClick={(d) => openEditDecl(d)}
          filters={{ has_disclosure: disclosuresOnly ? true : undefined }}
          searchPlaceholder="Search declarations by declarant or reference…"
          defaultSort={{ by: "created_at", dir: "desc" }}
          emptyMessage="No declarations. Staff submissions across all campaigns appear here."
          refreshKey={declKey}
          toolbarRight={<Toggle checked={disclosuresOnly} onChange={setDisclosuresOnly} label="Only disclosures" />}
        />
      )}

      {/* ============================================= CAMPAIGN DRAWER */}
      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? `${detail.reference || ""} ${detail.title}`.trim() : "…"}
        subtitle={detail ? `${cap(detail.declaration_type)} · ${cap(detail.status)}${detail.owner ? " · owner " + detail.owner : ""}${detail.period ? " · " + detail.period : ""}` : ""}
        width={860}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditCampaign(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => removeCampaign(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
              <Badge tone={CAMPAIGN_STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              <Badge tone="neutral" plain>{detail.declaration_count} declarations</Badge>
              {detail.disclosure_count > 0 && <Badge tone="high">{detail.disclosure_count} disclosures</Badge>}
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head"><h3>Declarations</h3></div>
              <div className="card-pad">
                <p className="muted" style={{ margin: "0 0 12px", fontSize: 13 }}>
                  One submission per staff member. Flag a disclosure where a conflict, gift or interest is being declared.
                </p>
                <form
                  style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                  onSubmit={(ev) => { ev.preventDefault(); addDeclaration(); }}
                >
                  <div style={{ flex: "1 1 180px" }}>
                    <label className="label">Declarant</label>
                    <input className="input" value={dd.declarant_name} onChange={(ev) => setDD("declarant_name", ev.target.value)} placeholder="Staff member" required />
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label">Role</label>
                    <input className="input" value={dd.declarant_role} onChange={(ev) => setDD("declarant_role", ev.target.value)} placeholder="Role" />
                  </div>
                  <div style={{ width: 150 }}>
                    <label className="label">Business unit</label>
                    <input className="input" value={dd.business_unit} onChange={(ev) => setDD("business_unit", ev.target.value)} placeholder="Unit" />
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, height: 38 }}>
                    <input id="dd-disc" type="checkbox" checked={dd.has_disclosure} onChange={(ev) => setDD("has_disclosure", ev.target.checked)} />
                    <label htmlFor="dd-disc" className="label" style={{ margin: 0 }}>Disclosure</label>
                  </div>
                  <div style={{ flex: "1 1 200px" }}>
                    <label className="label">Disclosure details</label>
                    <input className="input" value={dd.disclosure_details} onChange={(ev) => setDD("disclosure_details", ev.target.value)} placeholder="What is disclosed" />
                  </div>
                  <div style={{ width: 130 }}>
                    <label className="label">Amount (PKR)</label>
                    <input className="input" type="number" value={dd.amount} onChange={(ev) => setDD("amount", ev.target.value)} placeholder="0" />
                  </div>
                  <div style={{ width: 140 }}>
                    <label className="label">Status</label>
                    <select className="select" value={dd.status} onChange={(ev) => setDD("status", ev.target.value)}>
                      {DECL_STATUS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
                    </select>
                  </div>
                  <button className="btn">Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Ref</th>
                        <th>Declarant</th>
                        <th>Business unit</th>
                        <th>Disclosure</th>
                        <th>Amount</th>
                        <th>Status</th>
                        <th>Reviewer</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.declarations.map((d) => (
                        <tr key={d.id} style={{ cursor: "pointer" }} onClick={() => openEditDecl(d)}>
                          <td className="ref">{d.reference || "—"}</td>
                          <td className="cell-title">{d.declarant_name || "—"}{d.declarant_role ? <span className="muted"> · {d.declarant_role}</span> : null}</td>
                          <td className="muted">{d.business_unit || "—"}</td>
                          <td><DisclosureBadge has={d.has_disclosure} /></td>
                          <td className="muted">{d.amount != null ? pkr(d.amount, d.currency) : "—"}</td>
                          <td><Badge tone={DECL_STATUS_TONE[d.status] || "neutral"}>{cap(d.status)}</Badge></td>
                          <td className="muted">{d.reviewer || "—"}</td>
                          <td>
                            <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                              <button className="btn secondary sm" onClick={() => openEditDecl(d)}>Review</button>
                              <button className="btn secondary sm" onClick={() => removeDeclaration(d.id)}>Remove</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {detail.declarations.length === 0 && (
                        <tr><td colSpan={8}><span className="muted">No declarations recorded yet.</span></td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <RecordPanels model="declaration_campaign" entityId={detail.id} />
          </>
        )}
      </RecordDrawer>

      {/* ============================================= MODALS */}
      {showCampaignForm && (
        <FormModal
          title={editingCampaign ? `Edit campaign — ${editingCampaign.reference || editingCampaign.title}` : "New declaration campaign"}
          wide
          tabs={[
            { id: "general", label: "General", content: campaignGeneral, required: true },
            { id: "timing", label: "Timing", content: campaignTiming },
          ]}
          onClose={() => setShowCampaignForm(false)}
          onSave={saveCampaign}
          saving={savingCampaign}
          error={error}
          saveLabel={editingCampaign ? "Save changes" : "Create campaign"}
          footerLeft={
            editingCampaign ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeCampaign(editingCampaign)}
                disabled={savingCampaign}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showDeclForm && editingDecl && (
        <FormModal
          title={`Review declaration — ${editingDecl.reference || editingDecl.declarant_name || "submission"}`}
          wide
          tabs={[
            { id: "general", label: "Declaration", content: declGeneral },
            { id: "review", label: "Review", content: declReview },
          ]}
          onClose={() => setShowDeclForm(false)}
          onSave={saveDecl}
          saving={savingDecl}
          error={error}
          saveLabel="Save changes"
          footerLeft={
            <button
              className="btn secondary sm"
              type="button"
              onClick={() => { setShowDeclForm(false); removeDeclaration(editingDecl.id); }}
              disabled={savingDecl}
              style={{ color: "var(--danger, #c0392b)" }}
            >
              Delete
            </button>
          }
        />
      )}
    </>
  );
}

export default function DeclarationsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <DeclarationsInner />
    </Suspense>
  );
}
