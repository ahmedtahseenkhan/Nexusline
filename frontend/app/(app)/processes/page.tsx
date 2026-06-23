"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, MultiSelect, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconLayers, IconPlus } from "@/components/icons";

// ----------------------------------------------------------------- inline types
type Ref = { id: string; name: string };

type Process = {
  id: string;
  name: string;
  description: string;
  business_unit_id: string | null;
  owner: string;
  criticality: string;
  rto_hours: number | null;
  rpo_hours: number | null;
  rpd_hours: number | null;
  workflow_status: string;
  workflow_owner: string;
  business_unit: Ref | null;
  assets: Ref[];
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };

// ----------------------------------------------------------------- option sets
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const CRIT = opts(["low", "medium", "high", "critical"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

const WORKFLOW_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  in_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

const hrs = (v: number | null) => (v != null ? `${v}h` : "—");

// ----------------------------------------------------------------- form state
type FormState = {
  name: string;
  description: string;
  business_unit_id: string;
  owner: string;
  criticality: string;
  workflow_status: string;
  workflow_owner: string;
  rto_hours: number | "";
  rpo_hours: number | "";
  rpd_hours: number | "";
  asset_ids: string[];
};

const BLANK: FormState = {
  name: "", description: "", business_unit_id: "", owner: "",
  criticality: "medium", workflow_status: "draft", workflow_owner: "",
  rto_hours: "", rpo_hours: "", rpd_hours: "", asset_ids: [],
};

function fromProcess(p: Process): FormState {
  return {
    name: p.name,
    description: p.description || "",
    business_unit_id: p.business_unit_id || "",
    owner: p.owner || "",
    criticality: p.criticality,
    workflow_status: p.workflow_status,
    workflow_owner: p.workflow_owner || "",
    rto_hours: p.rto_hours ?? "",
    rpo_hours: p.rpo_hours ?? "",
    rpd_hours: p.rpd_hours ?? "",
    asset_ids: p.assets.map((a) => a.id),
  };
}

function toPayload(f: FormState) {
  return {
    name: f.name,
    description: f.description,
    business_unit_id: f.business_unit_id || null,
    owner: f.owner,
    criticality: f.criticality,
    workflow_status: f.workflow_status,
    workflow_owner: f.workflow_owner,
    rto_hours: f.rto_hours === "" ? null : f.rto_hours,
    rpo_hours: f.rpo_hours === "" ? null : f.rpo_hours,
    rpd_hours: f.rpd_hours === "" ? null : f.rpd_hours,
    asset_ids: f.asset_ids,
  };
}

export default function ProcessesPage() {
  const [items, setItems] = useState<Process[]>([]);
  const [units, setUnits] = useState<Ref[]>([]);
  const [assets, setAssets] = useState<Ref[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<Process | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems((await apiCall<Page<Process>>("GET", "/processes?limit=200")).items);
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
  function openEdit(p: Process) {
    setEditing(p);
    setF(fromProcess(p));
    setError(null);
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Process>("PATCH", `/processes/${editing.id}`, payload);
      else await apiCall<Process>("POST", "/processes", payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save process");
    } finally {
      setSaving(false);
    }
  }

  async function remove(p: Process) {
    if (!confirm(`Delete process "${p.name}"? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/processes/${p.id}`);
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

  const generalTab = (
    <>
      <Field label="Name" required help="The business process — e.g. Payroll, Order Fulfilment, Customer Onboarding.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Order Fulfilment" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What this process does and why it matters to the business." />
      </Field>
      <div className="field-row">
        <Field label="Business Unit" help="The unit that runs this process.">
          <Select value={f.business_unit_id} onChange={(v) => set("business_unit_id", v)} options={unitOpts} placeholder="— none —" />
        </Field>
        <Field label="Process Owner" help="Person accountable for the process.">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="Head of Operations" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Criticality" help="Business impact if this process is disrupted.">
          <Select value={f.criticality} onChange={(v) => set("criticality", v)} options={CRIT} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Workflow Owner" help="Accountable for approving this record.">
          <TextInput value={f.workflow_owner} onChange={(v) => set("workflow_owner", v)} placeholder="GRC Manager" />
        </Field>
      </div>
    </>
  );

  const continuityTab = (
    <>
      <p className="help" style={{ marginBottom: 14 }}>
        Business-continuity objectives used in impact analysis. All values are in hours.
      </p>
      <div className="field-row">
        <Field label="RTO — Recovery Time Objective" help="Max acceptable time to restore the process after disruption.">
          <NumberInput value={f.rto_hours} onChange={(v) => set("rto_hours", v)} min={0} placeholder="4" />
        </Field>
        <Field label="RPO — Recovery Point Objective" help="Max acceptable data loss, measured in time.">
          <NumberInput value={f.rpo_hours} onChange={(v) => set("rpo_hours", v)} min={0} placeholder="1" />
        </Field>
        <Field label="MTD — Max Tolerable Downtime" help="Longest the process can be down before unacceptable harm.">
          <NumberInput value={f.rpd_hours} onChange={(v) => set("rpd_hours", v)} min={0} placeholder="24" />
        </Field>
      </div>
    </>
  );

  const linksTab = (
    <Field label="Related Assets" help="Assets (systems, data, services) this process depends on.">
      <MultiSelect value={f.asset_ids} onChange={(v) => set("asset_ids", v)} options={assetOpts} />
    </Field>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Processes</h1>
          <p>Processes with continuity objectives (RTO / RPO / MTD), criticality and asset dependencies for impact analysis.</p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} /> Add process
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Processes</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Business unit</th>
                <th>Owner</th>
                <th>Criticality</th>
                <th>RTO</th>
                <th>RPO</th>
                <th>MTD</th>
                <th>Assets</th>
                <th>Workflow</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => openEdit(p)}>
                  <td className="cell-title">{p.name}</td>
                  <td className="muted">{p.business_unit ? p.business_unit.name : "—"}</td>
                  <td className="muted">{p.owner || "—"}</td>
                  <td><Severity value={p.criticality} /></td>
                  <td className="muted">{hrs(p.rto_hours)}</td>
                  <td className="muted">{hrs(p.rpo_hours)}</td>
                  <td className="muted">{hrs(p.rpd_hours)}</td>
                  <td className="muted">{p.assets.length || "—"}</td>
                  <td><Badge tone={WORKFLOW_TONE[p.workflow_status] || "neutral"}>{cap(p.workflow_status)}</Badge></td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => remove(p)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconLayers width={24} height={24} /></span>
                      <h3>No processes</h3>
                      <p>Add your first business process to start impact analysis.</p>
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
          title={editing ? `Edit process — ${editing.name}` : "Add item (Business Processes)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "continuity", label: "Continuity (RTO / RPO / MTD)", content: continuityTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create process"}
        />
      )}
    </>
  );
}
