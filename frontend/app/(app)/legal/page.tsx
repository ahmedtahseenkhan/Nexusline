"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, Select, NumberInput, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ----------------------------------------------------------------- inline types
type Ref = { id: string; name: string };

type Legal = {
  id: string;
  name: string;
  description: string;
  category: string;
  jurisdiction: string;
  reference: string;
  countries: string;
  risk_magnifier: number;
  workflow_status: string;
  workflow_owner: string;
  business_units: Ref[];
  assets: Ref[];
};

const WORKFLOW_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  in_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
// Common obligation domains — eramba seeds similar categories; freeform via the picker too.
const CATEGORY = opts(["privacy", "security", "financial", "employment", "environmental", "industry", "contractual", "other"]);
const refToOpt = (r: Ref): AsyncOption => ({ value: r.id, label: r.name });

type FormState = {
  name: string;
  description: string;
  category: string;
  jurisdiction: string;
  reference: string;
  countries: string;
  risk_magnifier: number | "";
  workflow_status: string;
  workflow_owner: string;
  business_unit_ids: AsyncOption[];
  asset_ids: AsyncOption[];
};

const BLANK: FormState = {
  name: "", description: "", category: "", jurisdiction: "", reference: "",
  countries: "", risk_magnifier: 1, workflow_status: "draft", workflow_owner: "",
  business_unit_ids: [], asset_ids: [],
};

function fromLegal(l: Legal): FormState {
  return {
    name: l.name,
    description: l.description || "",
    category: l.category || "",
    jurisdiction: l.jurisdiction || "",
    reference: l.reference || "",
    countries: l.countries || "",
    risk_magnifier: l.risk_magnifier,
    workflow_status: l.workflow_status,
    workflow_owner: l.workflow_owner || "",
    business_unit_ids: l.business_units.map(refToOpt),
    asset_ids: l.assets.map(refToOpt),
  };
}

function LegalInner() {
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [recordId, setRecordId] = useRecordParam("id");
  // Read-only detail loaded for the view drawer (?id=). Edit is a separate action.
  const [detail, setDetail] = useState<Legal | null>(null);

  const [editing, setEditing] = useState<Legal | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchLegals = useCallback((qs: string) => apiCall<PagedList<Legal>>("GET", `/legals?${qs}`), []);

  const searchUnits = (q: string) =>
    apiCall<PagedList<Ref>>("GET", `/business-units?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map(refToOpt));
  const searchAssets = (q: string) =>
    apiCall<PagedList<Ref>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map(refToOpt));

  // Read-only view: ?id= (row click, global search, ⌘K) loads the record's full
  // detail into the drawer. Editing is a separate action from there.
  const loadDetail = useCallback((id: string) => {
    apiCall<Legal>("GET", `/legals/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  function openEdit(l: Legal) {
    setEditing(l);
    setF(fromLegal(l));
    setError(null);
    setShowForm(true);
  }

  useEffect(() => {
    if (recordId) loadDetail(recordId);
    else setDetail(null);
  }, [recordId, loadDetail]);

  async function save() {
    if (!f.name.trim()) {
      setError("Name is required.");
      return;
    }
    setError(null);
    setSaving(true);
    const payload = {
      name: f.name,
      description: f.description,
      category: f.category,
      jurisdiction: f.jurisdiction,
      reference: f.reference,
      countries: f.countries,
      risk_magnifier: f.risk_magnifier === "" ? 1.0 : f.risk_magnifier,
      workflow_status: f.workflow_status,
      workflow_owner: f.workflow_owner,
      business_unit_ids: f.business_unit_ids.map((o) => o.value),
      asset_ids: f.asset_ids.map((o) => o.value),
    };
    try {
      if (editing) await apiCall<Legal>("PATCH", `/legals/${editing.id}`, payload);
      else await apiCall<Legal>("POST", "/legals", payload);
      setShowForm(false);
      reload();
      if (recordId) loadDetail(recordId);  // refresh the open view drawer
      toast(editing ? "Changes saved" : "Obligation created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save obligation");
    } finally {
      setSaving(false);
    }
  }

  async function remove(l: Legal) {
    if (!(await confirmDialog({ title: `Delete legal obligation "${l.name}"?`, danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/legals/${l.id}`);
      if (recordId === l.id) setRecordId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const linkCount = (l: Legal) => l.business_units.length + l.assets.length;

  const columns: Column<Legal>[] = [
    { key: "reference", header: "Reference", sortable: true, render: (l) => <span className="ref">{l.reference || "—"}</span> },
    { key: "name", header: "Name", sortable: true, render: (l) => <span className="cell-title">{l.name}</span> },
    { key: "category", header: "Category", sortable: true, render: (l) => (l.category ? <Badge tone="neutral" plain>{cap(l.category)}</Badge> : <span className="muted">—</span>) },
    { key: "jurisdiction", header: "Jurisdiction", sortable: true, render: (l) => <span className="muted">{l.jurisdiction || "—"}</span> },
    { key: "risk_magnifier", header: "Risk magnifier", sortable: true, render: (l) => <Badge tone={l.risk_magnifier > 1 ? "medium" : "neutral"} plain>×{l.risk_magnifier}</Badge> },
    { key: "links", header: "Links", align: "center", render: (l) => <span className="muted">{linkCount(l) || "—"}</span> },
    { key: "workflow_status", header: "Workflow", sortable: true, render: (l) => <Badge tone={WORKFLOW_TONE[l.workflow_status] || "neutral"}>{cap(l.workflow_status)}</Badge> },
    { key: "actions", header: "", render: (l) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(l)}>Delete</button></div> },
  ];

  const generalTab = (
    <>
      <Field label="Name" required help="For example: GDPR, HIPAA, PCI-DSS, SOX — the legal or regulatory obligation.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="HIPAA" required />
      </Field>
      <Field label="Description" help="Scope and intent of this obligation, and how it applies to the organization.">
        <RichText value={f.description} onChange={(v) => set("description", v)} placeholder="What this obligation requires and how it applies…" />
      </Field>
      <div className="field-row">
        <Field label="Category" help="Obligation domain. Pick one or type your own value.">
          <Select value={f.category} onChange={(v) => set("category", v)} options={CATEGORY} placeholder="— Select —" />
        </Field>
        <Field label="Jurisdiction" help="The governing body or legal jurisdiction (e.g. EU, US Federal, California).">
          <TextInput value={f.jurisdiction} onChange={(v) => set("jurisdiction", v)} placeholder="US Federal" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Reference" help="Statute, article or clause reference (e.g. 45 CFR Part 160).">
          <TextInput value={f.reference} onChange={(v) => set("reference", v)} placeholder="45 CFR Part 160" />
        </Field>
        <Field label="Applicable Countries" help="Comma-separated list of countries where this obligation applies.">
          <TextInput value={f.countries} onChange={(v) => set("countries", v)} placeholder="United States, Canada" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Risk Magnifier" help="Multiplier (≥ 0) that amplifies the score of risks linked to this obligation. 1.0 = no change.">
          <NumberInput value={f.risk_magnifier} onChange={(v) => set("risk_magnifier", v)} min={0} step={0.1} placeholder="1.0" />
        </Field>
        <Field label="Workflow Status">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Workflow Owner" help="Person accountable for moving this record through approval.">
          <TextInput value={f.workflow_owner} onChange={(v) => set("workflow_owner", v)} placeholder="Compliance Lead" />
        </Field>
      </div>
    </>
  );

  const linksTab = (
    <>
      <Field label="Business Units" help="Organizational units that must comply with this obligation.">
        <AsyncMultiSelect search={searchUnits} value={f.business_unit_ids} onChange={(v) => set("business_unit_ids", v)} />
      </Field>
      <Field label="Assets" help="Assets in scope of this obligation (data, systems, processes it governs).">
        <AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
      </Field>
    </>
  );

  // read-only helpers for the view drawer
  const chips = (items: Ref[]) =>
    items.length ? (
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {items.map((x) => (
          <span key={x.id} className="chip">{x.name}</span>
        ))}
      </div>
    ) : (
      <span className="muted">—</span>
    );
  const field = (label: string, value: React.ReactNode) => (
    <div style={{ minWidth: 140 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
      <div style={{ marginTop: 3 }}>{value ?? <span className="muted">—</span>}</div>
    </div>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Legal Register</h1>
          <p>Legal &amp; regulatory obligations; the risk magnifier amplifies linked risks.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="legal" label="Legal &amp; Regulatory" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add legal
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Legal>
        columns={columns}
        fetcher={fetchLegals}
        rowKey={(l) => l.id}
        onRowClick={(l) => setRecordId(l.id)}
        activeKey={recordId ?? undefined}
        searchPlaceholder="Search obligations by name, reference or jurisdiction…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No obligations. Register your first legal or regulatory obligation."
        refreshKey={refreshKey}
      />

      {/* Read-only detail view (?id=) — click a row to see everything; Edit is separate. */}
      <RecordDrawer
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? detail.name : "…"}
        subtitle={detail ? (detail.reference ? `${detail.reference} · ` : "") + cap(detail.workflow_status) : ""}
        width={640}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              {field("Reference", detail.reference || "—")}
              {field("Category", detail.category ? <Badge tone="neutral" plain>{cap(detail.category)}</Badge> : "—")}
              {field("Jurisdiction", detail.jurisdiction || "—")}
              {field("Applicable countries", detail.countries || "—")}
            </div>

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              {field("Risk magnifier", <Badge tone={detail.risk_magnifier > 1 ? "medium" : "neutral"} plain>×{detail.risk_magnifier}</Badge>)}
              {field("Workflow", <Badge tone={WORKFLOW_TONE[detail.workflow_status] || "neutral"}>{cap(detail.workflow_status)}</Badge>)}
              {field("Workflow owner", detail.workflow_owner || "—")}
            </div>

            {detail.description && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description</div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }} dangerouslySetInnerHTML={{ __html: detail.description }} />
              </div>
            )}

            <strong style={{ fontSize: 13 }}>Related records</strong>
            <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 8 }}>
              {field("Business units", chips(detail.business_units))}
              {field("Assets", chips(detail.assets))}
            </div>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
              <RecordPanels model="legal" entityId={detail.id} />
            </div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit obligation — ${editing.name}` : "Add item (Legal Register)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => { setShowForm(false); setRecordId(null); }}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create obligation"}
        />
      )}
    </>
  );
}

export default function LegalPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <LegalInner />
    </Suspense>
  );
}
