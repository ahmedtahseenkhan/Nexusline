"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, MultiSelect, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconUsers } from "@/components/icons";

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

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

const WORKFLOW_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  in_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

type FormState = {
  name: string;
  description: string;
  manager: string;
  email: string;
  location: string;
  parent_id: string;
  workflow_status: string;
  workflow_owner: string;
  legal_ids: string[];
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
    legal_ids: u.legals.map((l) => l.id),
  };
}

export default function BusinessUnitsPage() {
  const [items, setItems] = useState<BusinessUnit[]>([]);
  const [legals, setLegals] = useState<Ref[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<BusinessUnit | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems((await apiCall<Page<BusinessUnit>>("GET", "/business-units")).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
    apiCall<Page<Ref>>("GET", "/legals")
      .then((r) => setLegals(r.items))
      .catch(() => {});
  }, []);

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
      legal_ids: f.legal_ids,
    };
    try {
      if (editing) await apiCall<BusinessUnit>("PATCH", `/business-units/${editing.id}`, payload);
      else await apiCall<BusinessUnit>("POST", "/business-units", payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save business unit");
    } finally {
      setSaving(false);
    }
  }

  async function remove(u: BusinessUnit) {
    if (!confirm(`Delete business unit "${u.name}"? Child units will be detached.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/business-units/${u.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // Parent options exclude self (prevent a unit being its own parent).
  const parentOpts: Option[] = useMemo(
    () =>
      items
        .filter((u) => u.id !== editing?.id)
        .map((u) => ({ value: u.id, label: u.name, sub: u.manager || undefined })),
    [items, editing],
  );
  const legalOpts: Option[] = useMemo(
    () => legals.map((l) => ({ value: l.id, label: l.name })),
    [legals],
  );

  // children count is derived client-side: units whose parent is this one.
  const childCount = useMemo(() => {
    const m = new Map<string, number>();
    for (const u of items) {
      if (u.parent_id) m.set(u.parent_id, (m.get(u.parent_id) || 0) + 1);
    }
    return m;
  }, [items]);

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
      <MultiSelect value={f.legal_ids} onChange={(v) => set("legal_ids", v)} options={legalOpts} />
    </Field>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Units</h1>
          <p>Organizational hierarchy that owns assets, runs processes and holds legal obligations.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="business-units" label="Business Units" onDone={load} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add business unit
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Units</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Manager</th>
                <th>Parent</th>
                <th>Obligations</th>
                <th>Sub-units</th>
                <th>Workflow</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((u) => (
                <tr key={u.id} style={{ cursor: "pointer" }} onClick={() => openEdit(u)}>
                  <td className="cell-title">{u.name}</td>
                  <td className="muted">{u.manager || "—"}</td>
                  <td className="muted">{u.parent_name || "—"}</td>
                  <td className="muted">{u.legals.length || "—"}</td>
                  <td className="muted">{childCount.get(u.id) || "—"}</td>
                  <td><Badge tone={WORKFLOW_TONE[u.workflow_status] || "neutral"}>{cap(u.workflow_status)}</Badge></td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => remove(u)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">
                      <span className="ico"><IconUsers width={24} height={24} /></span>
                      <h3>No business units</h3>
                      <p>Create your first unit to build the organizational hierarchy.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showForm && (
        <FormModal
          title={editing ? `Edit business unit — ${editing.name}` : "Add item (Business Units)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create business unit"}
        />
      )}
    </>
  );
}
