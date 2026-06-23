"use client";

import { useEffect, useState } from "react";
import { api, type CustomField } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

const TYPES = ["text", "textarea", "number", "date", "select", "checkbox"];

export default function CustomFieldsPage() {
  const [fields, setFields] = useState<CustomField[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [model, setModel] = useState("project");
  const [label, setLabel] = useState("");
  const [fieldType, setFieldType] = useState("text");
  const [options, setOptions] = useState("");
  const [required, setRequired] = useState(false);

  async function load() {
    try {
      const [f, m] = await Promise.all([api.customFields(), api.customFieldModels()]);
      setFields(f);
      setModels(m);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createCustomField({ model, label, field_type: fieldType, options, required });
      setLabel("");
      setOptions("");
      setRequired(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await api.deleteCustomField(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const byModel = fields.reduce<Record<string, CustomField[]>>((acc, f) => {
    (acc[f.model] ||= []).push(f);
    return acc;
  }, {});

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

      {Object.keys(byModel).length === 0 && (
        <div className="card card-pad"><div className="empty"><h3>No custom fields yet</h3><p>Add one above to extend a module.</p></div></div>
      )}

      {Object.entries(byModel).map(([m, list]) => (
        <div className="card" key={m} style={{ marginBottom: 16 }}>
          <div className="card-head">
            <h3 style={{ textTransform: "capitalize" }}>{m.replace(/_/g, " ")}</h3>
            <span className="sub">{list.length} field{list.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Label</th><th>Type</th><th>Required</th><th>Options</th><th></th></tr></thead>
              <tbody>
                {list.map((f) => (
                  <tr key={f.id}>
                    <td className="cell-title">{f.label}</td>
                    <td><Badge tone="info">{f.field_type}</Badge></td>
                    <td>{f.required ? <Badge tone="medium">required</Badge> : <span className="muted">optional</span>}</td>
                    <td className="muted">{f.options ? f.options.split("\n").filter(Boolean).join(", ") : "—"}</td>
                    <td>
                      <button className="btn secondary sm" onClick={() => remove(f.id)} title="Delete">Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}
