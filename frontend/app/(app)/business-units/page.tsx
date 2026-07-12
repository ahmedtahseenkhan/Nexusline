"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
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
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

// ----------------------------------------------------------------- inline types
type Ref = { id: string; name: string };

type BusinessUnit = {
  id: string;
  name: string;
  description: string;
  manager: string;
  email: string;
  location: string;
  parent_id: string | null;
  parent_name: string | null;
  workflow_status: string;
  workflow_owner: string;
  legals: Ref[];
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
const refToOpt = (l: Ref): AsyncOption => ({ value: l.id, label: l.name });

type FormState = {
  name: string;
  description: string;
  manager: string;
  email: string;
  location: string;
  parent_id: string;
  workflow_status: string;
  workflow_owner: string;
  legal_ids: AsyncOption[];
};

const BLANK: FormState = {
  name: "", description: "", manager: "", email: "", location: "",
  parent_id: "", workflow_status: "draft", workflow_owner: "", legal_ids: [],
};

function fromUnit(u: BusinessUnit): FormState {
  return {
    name: u.name,
    description: u.description || "",
    manager: u.manager || "",
    email: u.email || "",
    location: u.location || "",
    parent_id: u.parent_id || "",
    workflow_status: u.workflow_status,
    workflow_owner: u.workflow_owner || "",
    legal_ids: u.legals.map(refToOpt),
  };
}

function BusinessUnitsInner() {
  // A full flat index of units backs the hierarchy (parent picker + sub-unit counts),
  // independent of the paginated table below.
  const [allUnits, setAllUnits] = useState<BusinessUnit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [recordId, setRecordId] = useRecordParam("id");
  // Read-only detail loaded for the view drawer (?id=). Edit is a separate action.
  const [detail, setDetail] = useState<BusinessUnit | null>(null);

  const [editing, setEditing] = useState<BusinessUnit | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchUnits = useCallback((qs: string) => apiCall<PagedList<BusinessUnit>>("GET", `/business-units?${qs}`), []);

  const loadIndex = useCallback(() => {
    apiCall<PagedList<BusinessUnit>>("GET", "/business-units?limit=200")
      .then((r) => setAllUnits(r.items))
      .catch(() => {});
  }, []);
  useEffect(() => { loadIndex(); }, [loadIndex]);

  // Read-only view: ?id= (row click, global search, ⌘K) loads the record's full
  // detail into the drawer. Editing is a separate action from there.
  const loadDetail = useCallback((id: string) => {
    apiCall<BusinessUnit>("GET", `/business-units/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);

  const searchLegals = (q: string) =>
    apiCall<PagedList<Ref>>("GET", `/legals?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map(refToOpt));

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  function openEdit(u: BusinessUnit) {
    setEditing(u);
    setF(fromUnit(u));
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
      manager: f.manager,
      email: f.email,
      location: f.location,
      parent_id: f.parent_id || null,
      workflow_status: f.workflow_status,
      workflow_owner: f.workflow_owner,
      legal_ids: f.legal_ids.map((o) => o.value),
    };
    try {
      if (editing) await apiCall<BusinessUnit>("PATCH", `/business-units/${editing.id}`, payload);
      else await apiCall<BusinessUnit>("POST", "/business-units", payload);
      setShowForm(false);
      reload();
      loadIndex();
      if (recordId) loadDetail(recordId);  // refresh the open view drawer
      toast(editing ? "Changes saved" : "Business unit created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save business unit");
    } finally {
      setSaving(false);
    }
  }

  async function remove(u: BusinessUnit) {
    if (!(await confirmDialog({ title: `Delete business unit "${u.name}"?`, message: "Child units will be detached.", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/business-units/${u.id}`);
      if (recordId === u.id) setRecordId(null);
      reload();
      loadIndex();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // Parent options exclude self (prevent a unit being its own parent).
  const parentOpts: Option[] = useMemo(
    () =>
      allUnits
        .filter((u) => u.id !== editing?.id)
        .map((u) => ({ value: u.id, label: u.name, sub: u.manager || undefined })),
    [allUnits, editing],
  );

  // children count is derived from the full index: units whose parent is this one.
  const childCount = useMemo(() => {
    const m = new Map<string, number>();
    for (const u of allUnits) {
      if (u.parent_id) m.set(u.parent_id, (m.get(u.parent_id) || 0) + 1);
    }
    return m;
  }, [allUnits]);

  const columns: Column<BusinessUnit>[] = [
    { key: "name", header: "Name", sortable: true, render: (u) => <span className="cell-title">{u.name}</span> },
    { key: "manager", header: "Manager", sortable: true, render: (u) => <span className="muted">{u.manager || "—"}</span> },
    { key: "parent", header: "Parent", render: (u) => <span className="muted">{u.parent_name || "—"}</span> },
    { key: "obligations", header: "Obligations", align: "center", render: (u) => <span className="muted">{u.legals.length || "—"}</span> },
    { key: "subunits", header: "Sub-units", align: "center", render: (u) => <span className="muted">{childCount.get(u.id) || "—"}</span> },
    { key: "workflow_status", header: "Workflow", sortable: true, render: (u) => <Badge tone={WORKFLOW_TONE[u.workflow_status] || "neutral"}>{cap(u.workflow_status)}</Badge> },
    { key: "actions", header: "", render: (u) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(u)}>Delete</button></div> },
  ];

  const generalTab = (
    <>
      <Field label="Name" required help="For example: Engineering, Finance, Human Resources, EMEA Operations.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Engineering" required />
      </Field>
      <Field label="Description">
        <TextArea
          value={f.description}
          onChange={(v) => set("description", v)}
          rows={3}
          placeholder="Mandate, scope and responsibilities of this organizational unit."
        />
      </Field>
      <Field label="Parent Unit" help="Place this unit under another to build the organizational hierarchy. A unit cannot be its own parent.">
        <Select value={f.parent_id} onChange={(v) => set("parent_id", v)} options={parentOpts} placeholder="— Top level —" />
      </Field>
      <div className="field-row">
        <Field label="Manager / Head" help="The accountable contact for this unit (RACI head).">
          <TextInput value={f.manager} onChange={(v) => set("manager", v)} placeholder="Jane Doe" />
        </Field>
        <Field label="Contact Email">
          <TextInput value={f.email} onChange={(v) => set("email", v)} type="email" placeholder="head.engineering@example.com" />
        </Field>
      </div>
      <Field label="Location">
        <TextInput value={f.location} onChange={(v) => set("location", v)} placeholder="London, UK" />
      </Field>
      <div className="field-row">
        <Field label="Workflow Status">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Workflow Owner" help="The person responsible for moving this record through the approval lifecycle.">
          <TextInput value={f.workflow_owner} onChange={(v) => set("workflow_owner", v)} placeholder="GRC Lead" />
        </Field>
      </div>
    </>
  );

  const linksTab = (
    <Field label="Legal & Regulatory Obligations" help="Legal obligations that apply to this business unit.">
      <AsyncMultiSelect search={searchLegals} value={f.legal_ids} onChange={(v) => set("legal_ids", v)} />
    </Field>
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
          <h1>Business Units</h1>
          <p>Organizational hierarchy that owns assets, runs processes and holds legal obligations.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="business-units" label="Business Units" onDone={() => { reload(); loadIndex(); }} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add business unit
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<BusinessUnit>
        columns={columns}
        fetcher={fetchUnits}
        rowKey={(u) => u.id}
        onRowClick={(u) => setRecordId(u.id)}
        activeKey={recordId ?? undefined}
        searchPlaceholder="Search units by name, manager or location…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No business units. Create your first unit to build the organizational hierarchy."
        refreshKey={refreshKey}
      />

      {/* Read-only detail view (?id=) — click a row to see everything; Edit is separate. */}
      <RecordDrawer
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? detail.name : "…"}
        subtitle={detail ? cap(detail.workflow_status) + (detail.parent_name ? ` · under ${detail.parent_name}` : "") : ""}
        width={620}
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
              {field("Manager / Head", detail.manager || "—")}
              {field("Contact email", detail.email || "—")}
              {field("Location", detail.location || "—")}
            </div>

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              {field("Parent unit", detail.parent_name || "— Top level —")}
              {field("Sub-units", String(childCount.get(detail.id) || 0))}
              {field("Workflow", <Badge tone={WORKFLOW_TONE[detail.workflow_status] || "neutral"}>{cap(detail.workflow_status)}</Badge>)}
              {field("Workflow owner", detail.workflow_owner || "—")}
            </div>

            {detail.description && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description</div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }}>{detail.description}</div>
              </div>
            )}

            <strong style={{ fontSize: 13 }}>Related records</strong>
            <div style={{ display: "grid", gap: 12, marginTop: 8, marginBottom: 8 }}>
              {field("Legal & regulatory obligations", chips(detail.legals))}
            </div>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
              <RecordPanels model="business_unit" entityId={detail.id} />
            </div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit business unit — ${editing.name}` : "Add item (Business Units)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => { setShowForm(false); setRecordId(null); }}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create business unit"}
        />
      )}
    </>
  );
}

export default function BusinessUnitsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <BusinessUnitsInner />
    </Suspense>
  );
}
