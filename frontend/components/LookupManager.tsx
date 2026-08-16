"use client";

/* One CRUD panel per lookup registry (media types, vendor types, labels, tags…).
   All five registries share the same shape — a small named row with optional
   description/category/color — so one config-driven component manages them all.
   Built-in rows (editable === false) keep their name and cannot be deleted: assets
   reference them, and the API answers 409 if you try. */

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { Badge } from "@/components/badges";

export type LookupFieldKey = "name" | "category" | "description" | "color";

export type LookupRegistry = {
  title: string;
  /** Where the values show up, so an admin knows what they are editing. */
  help: string;
  endpoint: string; // e.g. "/asset-media-types"
  fields: LookupFieldKey[]; // "name" is always first and required
  /** Registry rows carry an `editable` flag (media types): false = built-in. */
  hasBuiltins?: boolean;
};

type Row = {
  id: string;
  name: string;
  category?: string;
  description?: string;
  color?: string;
  editable?: boolean;
};

const FIELD_LABEL: Record<LookupFieldKey, string> = {
  name: "Name",
  category: "Category",
  description: "Description",
  color: "Color",
};

const FIELD_FLEX: Record<LookupFieldKey, string> = {
  name: "1 1 180px",
  category: "0 1 140px",
  description: "2 1 240px",
  color: "0 0 52px",
};

function emptyDraft(fields: LookupFieldKey[]): Record<string, string> {
  return Object.fromEntries(fields.map((f) => [f, ""]));
}

/** A "＋ New" affordance for a form dropdown whose values live in a lookup registry.
    Renders a link-sized button; clicking it swaps in a name input that POSTs to the
    registry and hands the created row back so the form can select it immediately. */
export function InlineLookupCreate({
  endpoint,
  onCreated,
  extra,
}: {
  endpoint: string;
  onCreated: (row: { id: string; name: string }) => void;
  /** Extra fields the endpoint requires beyond the name (defaults for the rest). */
  extra?: Record<string, string>;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function create() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const row = await apiCall<{ id: string; name: string }>("POST", endpoint, {
        name: trimmed,
        description: "",
        ...extra,
      });
      onCreated(row);
      setName("");
      setOpen(false);
      toast(`"${row.name}" added`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Create failed", "error");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        className="btn secondary sm"
        style={{ marginTop: 6 }}
        onClick={() => setOpen(true)}
      >
        ＋ New
      </button>
    );
  }
  return (
    <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
      <input
        className="input"
        style={{ padding: "4px 8px", fontSize: 13 }}
        autoFocus
        value={name}
        placeholder="Name…"
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            create();
          }
          if (e.key === "Escape") setOpen(false);
        }}
      />
      <button type="button" className="btn sm" disabled={busy || !name.trim()} onClick={create}>
        Add
      </button>
      <button type="button" className="btn secondary sm" disabled={busy} onClick={() => setOpen(false)}>
        Cancel
      </button>
    </div>
  );
}

export default function LookupManager({ registry }: { registry: LookupRegistry }) {
  const [rows, setRows] = useState<Row[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>(() => emptyDraft(registry.fields));
  const [edits, setEdits] = useState<Record<string, Record<string, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await apiCall<Row[]>("GET", registry.endpoint));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [registry.endpoint]);

  useEffect(() => {
    load();
  }, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.name?.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const payload = Object.fromEntries(registry.fields.map((f) => [f, (draft[f] || "").trim()]));
      await apiCall<Row>("POST", registry.endpoint, payload);
      setDraft(emptyDraft(registry.fields));
      await load();
      toast(`${registry.title.replace(/s$/, "")} added`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  async function save(row: Row) {
    const patch = edits[row.id];
    if (!patch) return;
    setBusy(true);
    setError(null);
    try {
      await apiCall<Row>("PATCH", `${registry.endpoint}/${row.id}`, patch);
      setEdits((p) => {
        const next = { ...p };
        delete next[row.id];
        return next;
      });
      await load();
      toast("Saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: Row) {
    const ok = await confirmDialog({
      title: `Delete "${row.name}"?`,
      message: "Records using this value keep working — the reference is simply cleared.",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await apiCall<void>("DELETE", `${registry.endpoint}/${row.id}`);
      await load();
      toast("Deleted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  function edit(row: Row, field: string, value: string) {
    setEdits((p) => ({ ...p, [row.id]: { ...p[row.id], [field]: value } }));
  }

  function valueOf(row: Row, field: LookupFieldKey): string {
    const pending = edits[row.id]?.[field];
    if (pending !== undefined) return pending;
    return (row[field] as string | undefined) || "";
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>{registry.title}</h2>
        <span className="muted" style={{ fontSize: 12.5 }}>{registry.help}</span>
      </div>

      {error && <div className="error" style={{ margin: "10px 0" }}>{error}</div>}

      <form onSubmit={create} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", margin: "12px 0" }}>
        {registry.fields.map((f) => (
          <div key={f} style={{ flex: FIELD_FLEX[f] }}>
            <label className="label">{FIELD_LABEL[f]}</label>
            {f === "color" ? (
              <input
                className="input"
                type="color"
                style={{ padding: 2, height: 34 }}
                value={draft.color || "#2563eb"}
                onChange={(e) => setDraft((p) => ({ ...p, color: e.target.value }))}
              />
            ) : (
              <input
                className="input"
                value={draft[f] || ""}
                required={f === "name"}
                onChange={(e) => setDraft((p) => ({ ...p, [f]: e.target.value }))}
                placeholder={f === "name" ? "New value…" : ""}
              />
            )}
          </div>
        ))}
        <button className="btn" disabled={busy || !draft.name?.trim()}>Add</button>
      </form>

      {rows.length === 0 ? (
        <div className="muted" style={{ fontSize: 13 }}>Nothing here yet — add the first value above.</div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {registry.fields.map((f) => (
                  <th key={f} style={f === "color" ? { width: 64 } : undefined}>{FIELD_LABEL[f]}</th>
                ))}
                <th style={{ width: 150 }} />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const builtin = registry.hasBuiltins && row.editable === false;
                const dirty = !!edits[row.id];
                return (
                  <tr key={row.id}>
                    {registry.fields.map((f) => (
                      <td key={f}>
                        {f === "color" ? (
                          <input
                            type="color"
                            className="input"
                            style={{ padding: 2, height: 30, width: 46 }}
                            value={valueOf(row, "color") || "#2563eb"}
                            onChange={(e) => edit(row, "color", e.target.value)}
                          />
                        ) : (
                          <input
                            className="input"
                            style={{ padding: "4px 8px", fontSize: 13 }}
                            value={valueOf(row, f)}
                            disabled={f === "name" && builtin}
                            title={f === "name" && builtin ? "Built-in — assets reference this name" : undefined}
                            onChange={(e) => edit(row, f, e.target.value)}
                          />
                        )}
                      </td>
                    ))}
                    <td>
                      <div style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "flex-end" }}>
                        {builtin && <Badge tone="neutral" plain>built-in</Badge>}
                        {dirty && (
                          <button className="btn sm" type="button" disabled={busy} onClick={() => save(row)}>
                            Save
                          </button>
                        )}
                        {!builtin && (
                          <button className="btn secondary sm" type="button" disabled={busy} onClick={() => remove(row)}>
                            Delete
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
