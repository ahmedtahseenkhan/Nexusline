"use client";

import { useEffect, useState } from "react";
import { api, type CustomFieldValueItem } from "@/lib/api";

/** Renders an org's custom fields for a given record and saves their values. */
export default function CustomFieldsPanel({ model, entityId }: { model: string; entityId: string }) {
  const [items, setItems] = useState<CustomFieldValueItem[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    setStatus("idle");
    api
      .customFieldValues(model, entityId)
      .then((rows) => {
        setItems(rows);
        setValues(Object.fromEntries(rows.map((r) => [r.field.id, r.value])));
      })
      .catch(() => setItems([]));
  }, [model, entityId]);

  if (items.length === 0) return null;

  function set(id: string, v: string) {
    setValues((prev) => ({ ...prev, [id]: v }));
    setStatus("idle");
  }

  async function save() {
    setStatus("saving");
    try {
      await api.setCustomFieldValues(model, entityId, values);
      setStatus("saved");
    } catch (e) {
      setStatus("error");
      setMsg(e instanceof Error ? e.message : "Save failed");
    }
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3>Custom fields</h3>
        <span className="sub">org-defined</span>
      </div>
      <div className="card-pad">
        {items.map(({ field }) => {
          const v = values[field.id] ?? "";
          return (
            <div key={field.id} style={{ marginBottom: 12 }}>
              <label className="label">
                {field.label}
                {field.required && <span style={{ color: "var(--red)" }}> *</span>}
              </label>
              {field.field_type === "textarea" ? (
                <textarea className="input" rows={2} value={v} onChange={(e) => set(field.id, e.target.value)} />
              ) : field.field_type === "select" ? (
                <select className="input" value={v} onChange={(e) => set(field.id, e.target.value)}>
                  <option value="">—</option>
                  {field.options.split("\n").filter(Boolean).map((o) => (
                    <option key={o} value={o.trim()}>{o.trim()}</option>
                  ))}
                </select>
              ) : field.field_type === "checkbox" ? (
                <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                  <input type="checkbox" checked={v === "true"} onChange={(e) => set(field.id, e.target.checked ? "true" : "false")} />
                  Yes
                </label>
              ) : (
                <input
                  className="input"
                  type={field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text"}
                  value={v}
                  onChange={(e) => set(field.id, e.target.value)}
                />
              )}
              {field.help_text && <div className="when" style={{ marginTop: 4 }}>{field.help_text}</div>}
            </div>
          );
        })}
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 4 }}>
          <button className="btn sm" onClick={save} disabled={status === "saving"}>
            {status === "saving" ? "Saving…" : "Save fields"}
          </button>
          {status === "saved" && <span className="when" style={{ color: "var(--green)" }}>Saved</span>}
          {status === "error" && <span className="when" style={{ color: "var(--red)" }}>{msg}</span>}
        </div>
      </div>
    </div>
  );
}
