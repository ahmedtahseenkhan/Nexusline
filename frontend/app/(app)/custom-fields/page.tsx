"use client";

import { useCallback, useEffect, useState } from "react";
import { api, apiCall, type CustomField } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

const TYPES = ["text", "textarea", "number", "date", "select", "checkbox"];

export default function CustomFieldsPage() {
  const [models, setModels] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [filterModel, setFilterModel] = useState("");

  const [model, setModel] = useState("project");
  const [label, setLabel] = useState("");
  const [fieldType, setFieldType] = useState("text");
  const [options, setOptions] = useState("");
  const [required, setRequired] = useState(false);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchFields = useCallback((qs: string) => apiCall<PagedList<CustomField>>("GET", `/custom-fields?${qs}`), []);

  useEffect(() => {
    api.customFieldModels().then(setModels).catch(() => {});
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createCustomField({ model, label, field_type: fieldType, options, required });
      setLabel("");
      setOptions("");
      setRequired(false);
      reload();
      toast("Custom field added");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }

  async function remove(f: CustomField) {
    if (!(await confirmDialog({ title: `Delete field "${f.label}"?`, message: "Existing values for this field will be removed.", danger: true }))) return;
    setError(null);
    try {
      await api.deleteCustomField(f.id);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const columns: Column<CustomField>[] = [
    { key: "model", header: "Module", sortable: true, render: (f) => <span className="muted" style={{ textTransform: "capitalize" }}>{f.model.replace(/_/g, " ")}</span> },
    { key: "label", header: "Label", sortable: true, render: (f) => <span className="cell-title">{f.label}</span> },
    { key: "field_type", header: "Type", sortable: true, render: (f) => <Badge tone="info">{f.field_type}</Badge> },
    { key: "required", header: "Required", render: (f) => (f.required ? <Badge tone="medium">required</Badge> : <span className="muted">optional</span>) },
    { key: "options", header: "Options", render: (f) => <span className="muted">{f.options ? f.options.split("\n").filter(Boolean).join(", ") : "—"}</span> },
    { key: "actions", header: "", render: (f) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(f)}>Delete</button></div> },
  ];

  return (
    <>
      <div className="page-head">
        <h1>Custom Fields</h1>
        <p>Extend any module with your own fields. They appear on each record automatically.</p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ flex: "0 0 180px" }}>
            <label className="label">Module</label>
            <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div style={{ flex: "1 1 220px" }}>
            <label className="label">Field label</label>
            <input className="input" required value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Cost Center" />
          </div>
          <div style={{ flex: "0 0 150px" }}>
            <label className="label">Type</label>
            <select className="input" value={fieldType} onChange={(e) => setFieldType(e.target.value)}>
              {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, paddingBottom: 9 }}>
            <input type="checkbox" checked={required} onChange={(e) => setRequired(e.target.checked)} /> Required
          </label>
          <button className="btn"><IconPlus width={16} height={16} /> Add field</button>
        </div>
        {fieldType === "select" && (
          <div style={{ marginTop: 12 }}>
            <label className="label">Options (one per line)</label>
            <textarea className="input" rows={3} value={options} onChange={(e) => setOptions(e.target.value)} placeholder={"Option A\nOption B"} />
          </div>
        )}
      </form>

      <DataTable<CustomField>
        columns={columns}
        fetcher={fetchFields}
        rowKey={(f) => f.id}
        searchPlaceholder="Search fields by label…"
        filters={{ model: filterModel || undefined }}
        toolbarRight={
          <select className="input" style={{ maxWidth: 200 }} value={filterModel} onChange={(e) => setFilterModel(e.target.value)}>
            <option value="">All modules</option>
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        }
        emptyMessage="No custom fields yet. Add one above to extend a module."
        refreshKey={refreshKey}
      />
    </>
  );
}
