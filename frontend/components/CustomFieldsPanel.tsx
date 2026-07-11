"use client";

import { useEffect, useState } from "react";
import { api, type CustomFieldValueItem } from "@/lib/api";
import CustomFieldsEditor from "@/components/CustomFieldsEditor";

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
        <CustomFieldsEditor fields={items.map((i) => i.field)} values={values} onChange={set} />
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
