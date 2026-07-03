"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, Select, MultiSelect, NumberInput, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconPolicy } from "@/components/icons";

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
// Common obligation domains — eramba seeds similar categories; freeform via the picker too.
const CATEGORY = opts(["privacy", "security", "financial", "employment", "environmental", "industry", "contractual", "other"]);

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
  business_unit_ids: string[];
  asset_ids: string[];
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
    business_unit_ids: l.business_units.map((b) => b.id),
    asset_ids: l.assets.map((a) => a.id),
  };
}

export default function LegalPage() {
  const [items, setItems] = useState<Legal[]>([]);
  const [units, setUnits] = useState<Ref[]>([]);
  const [assets, setAssets] = useState<Ref[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Legal | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems((await apiCall<Page<Legal>>("GET", "/legals?limit=200")).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
    apiCall<Page<Ref>>("GET", "/business-units?limit=200").then((r) => setUnits(r.items)).catch(() => {});
    apiCall<Page<Ref>>("GET", "/assets?limit=200").then((r) => setAssets(r.items)).catch(() => {});
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
      business_unit_ids: f.business_unit_ids,
      asset_ids: f.asset_ids,
    };
    try {
      if (editing) await apiCall<Legal>("PATCH", `/legals/${editing.id}`, payload);
      else await apiCall<Legal>("POST", "/legals", payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save obligation");
    } finally {
      setSaving(false);
    }
  }

  async function remove(l: Legal) {
    if (!confirm(`Delete legal obligation "${l.name}"?`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/legals/${l.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const unitOpts: Option[] = useMemo(
    () => units.map((u) => ({ value: u.id, label: u.name })),
    [units],
  );
  const assetOpts: Option[] = useMemo(
    () => assets.map((a) => ({ value: a.id, label: a.name })),
    [assets],
  );

  const linkCount = (l: Legal) => l.business_units.length + l.assets.length;

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
        <MultiSelect value={f.business_unit_ids} onChange={(v) => set("business_unit_ids", v)} options={unitOpts} />
      </Field>
      <Field label="Assets" help="Assets in scope of this obligation (data, systems, processes it governs).">
        <MultiSelect value={f.asset_ids} onChange={(v) => set("asset_ids", v)} options={assetOpts} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Legal Register</h1>
          <p>Legal &amp; regulatory obligations; the risk magnifier amplifies linked risks.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="legal" label="Legal &amp; Regulatory" onDone={load} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add legal
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Obligations</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Reference</th>
                <th>Name</th>
                <th>Category</th>
                <th>Jurisdiction</th>
                <th>Risk magnifier</th>
                <th>Links</th>
                <th>Workflow</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((l) => (
                <tr key={l.id} style={{ cursor: "pointer" }} onClick={() => openEdit(l)}>
                  <td className="muted">{l.reference || "—"}</td>
                  <td className="cell-title">{l.name}</td>
                  <td>{l.category ? <Badge tone="neutral" plain>{cap(l.category)}</Badge> : <span className="muted">—</span>}</td>
                  <td className="muted">{l.jurisdiction || "—"}</td>
                  <td><Badge tone={l.risk_magnifier > 1 ? "medium" : "neutral"} plain>×{l.risk_magnifier}</Badge></td>
                  <td className="muted">{linkCount(l) || "—"}</td>
                  <td><Badge tone={WORKFLOW_TONE[l.workflow_status] || "neutral"}>{cap(l.workflow_status)}</Badge></td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => remove(l)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={8}>
                    <div className="empty">
                      <span className="ico"><IconPolicy width={24} height={24} /></span>
                      <h3>No obligations</h3>
                      <p>Register your first legal or regulatory obligation.</p>
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
          title={editing ? `Edit obligation — ${editing.name}` : "Add item (Legal Register)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create obligation"}
        />
      )}
    </>
  );
}
