"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, NumberInput, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";
import { IconPlus } from "@/components/icons";

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
const refToOpt = (a: Ref): AsyncOption => ({ value: a.id, label: a.name });

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
  asset_ids: AsyncOption[];
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
    asset_ids: p.assets.map(refToOpt),
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
    asset_ids: f.asset_ids.map((o) => o.value),
  };
}

function ProcessesInner() {
  const [units, setUnits] = useState<Ref[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [recordId, setRecordId] = useRecordParam("id");

  const [editing, setEditing] = useState<Process | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchProcesses = useCallback((qs: string) => apiCall<PagedList<Process>>("GET", `/processes?${qs}`), []);

  useEffect(() => {
    apiCall<PagedList<Ref>>("GET", "/business-units?limit=200").then((r) => setUnits(r.items)).catch(() => {});
  }, []);

  const searchAssets = (q: string) =>
    apiCall<PagedList<Ref>>("GET", `/assets?search=${encodeURIComponent(q)}&limit=20`).then((r) => r.items.map(refToOpt));

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

  // Deep-link: open the record named by ?id= (e.g. from global search / ⌘K).
  useEffect(() => {
    if (!recordId || editing?.id === recordId) return;
    apiCall<Process>("GET", `/processes/${recordId}`).then(openEdit).catch(() => setRecordId(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) await apiCall<Process>("PATCH", `/processes/${editing.id}`, payload);
      else await apiCall<Process>("POST", "/processes", payload);
      setShowForm(false);
      reload();
      toast(editing ? "Changes saved" : "Process created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save process");
    } finally {
      setSaving(false);
    }
  }

  async function remove(p: Process) {
    if (!(await confirmDialog({ title: `Delete process "${p.name}"?`, message: "This cannot be undone.", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/processes/${p.id}`);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const unitOpts: Option[] = useMemo(
    () => units.map((u) => ({ value: u.id, label: u.name })),
    [units],
  );

  const columns: Column<Process>[] = [
    { key: "name", header: "Name", sortable: true, render: (p) => <span className="cell-title">{p.name}</span> },
    { key: "business_unit", header: "Business unit", render: (p) => <span className="muted">{p.business_unit ? p.business_unit.name : "—"}</span> },
    { key: "owner", header: "Owner", sortable: true, render: (p) => <span className="muted">{p.owner || "—"}</span> },
    { key: "criticality", header: "Criticality", sortable: true, render: (p) => <Severity value={p.criticality} /> },
    { key: "rto", header: "RTO", render: (p) => <span className="muted">{hrs(p.rto_hours)}</span> },
    { key: "rpo", header: "RPO", render: (p) => <span className="muted">{hrs(p.rpo_hours)}</span> },
    { key: "mtd", header: "MTD", render: (p) => <span className="muted">{hrs(p.rpd_hours)}</span> },
    { key: "assets", header: "Assets", align: "center", render: (p) => <span className="muted">{p.assets.length || "—"}</span> },
    { key: "workflow_status", header: "Workflow", sortable: true, render: (p) => <Badge tone={WORKFLOW_TONE[p.workflow_status] || "neutral"}>{cap(p.workflow_status)}</Badge> },
    { key: "actions", header: "", render: (p) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(p)}>Delete</button></div> },
  ];

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
      <AsyncMultiSelect search={searchAssets} value={f.asset_ids} onChange={(v) => set("asset_ids", v)} />
    </Field>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Business Processes</h1>
          <p>Processes with continuity objectives (RTO / RPO / MTD), criticality and asset dependencies for impact analysis.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="processes" label="Processes" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add process
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Process>
        columns={columns}
        fetcher={fetchProcesses}
        rowKey={(p) => p.id}
        onRowClick={(p) => { setRecordId(p.id); openEdit(p); }}
        activeKey={recordId ?? undefined}
        searchPlaceholder="Search processes by name or owner…"
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage="No processes. Add your first business process to start impact analysis."
        refreshKey={refreshKey}
      />

      {showForm && (
        <FormModal
          title={editing ? `Edit process — ${editing.name}` : "Add item (Business Processes)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "continuity", label: "Continuity (RTO / RPO / MTD)", content: continuityTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => { setShowForm(false); setRecordId(null); }}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create process"}
        />
      )}
    </>
  );
}

export default function ProcessesPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ProcessesInner />
    </Suspense>
  );
}
