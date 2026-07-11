"use client";

import type { CustomField } from "@/lib/api";

/** Controlled renderer for org-defined custom fields. Owns no state and does no
 * fetching/saving — the host (a FormModal tab, the record detail panel) supplies
 * definitions + values and persists them. Inputs carry `required`, so FormModal's
 * global client-side validation covers custom fields for free. */
export default function CustomFieldsEditor({
  fields,
  values,
  onChange,
}: {
  fields: CustomField[];
  values: Record<string, string>;
  onChange: (id: string, value: string) => void;
}) {
  return (
    <>
      {fields.map((field) => {
        const v = values[field.id] ?? "";
        return (
          <div key={field.id} className="field" style={{ marginBottom: 12 }}>
            <label className="label">
              {field.label}
              {field.required && <span style={{ color: "var(--red)" }}> *</span>}
            </label>
            {field.field_type === "textarea" ? (
              <textarea
                className="input"
                rows={2}
                value={v}
                required={field.required}
                onChange={(e) => onChange(field.id, e.target.value)}
              />
            ) : field.field_type === "select" ? (
              <select
                className="input"
                value={v}
                required={field.required}
                onChange={(e) => onChange(field.id, e.target.value)}
              >
                <option value="">—</option>
                {field.options.split("\n").filter(Boolean).map((o) => (
                  <option key={o} value={o.trim()}>{o.trim()}</option>
                ))}
              </select>
            ) : field.field_type === "checkbox" ? (
              <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={v === "true"}
                  onChange={(e) => onChange(field.id, e.target.checked ? "true" : "false")}
                />
                Yes
              </label>
            ) : (
              <input
                className="input"
                type={field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text"}
                value={v}
                required={field.required}
                onChange={(e) => onChange(field.id, e.target.value)}
              />
            )}
            {field.help_text && <div className="when" style={{ marginTop: 4 }}>{field.help_text}</div>}
          </div>
        );
      })}
    </>
  );
}
