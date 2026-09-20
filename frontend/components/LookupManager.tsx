"use client";

/* One CRUD panel per lookup registry (media types, vendor types, labels, tags…).
   All five registries share the same shape — a small named row with optional
   description/category/color — so one config-driven component manages them all.
   Built-in rows (editable === false) keep their name and cannot be deleted: assets
   reference them, and the API answers 409 if you try. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { Badge } from "@/components/badges";
import {
  LOOKUP_MANAGE_PERMISSION,
  createLookupValue,
  deleteLookupValue,
  lookupValues,
  reorderLookupValues,
  updateLookupValue,
  type LookupList,
  type LookupPatch,
  type LookupValue,
} from "@/lib/masterData";
import { useHasPermission } from "@/lib/tenantSettings";

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
    registry and hands the created row back so the form can select it immediately.
    `nameField` names the field the typed text is sent as ("name" for the registries,
    "label" for the governed `/lookups/{key}` lists); the created row is handed back with
    `name` set to it either way, plus everything else the endpoint returned. */
export function InlineLookupCreate({
  endpoint,
  onCreated,
  extra,
  nameField = "name",
}: {
  endpoint: string;
  onCreated: (row: { id: string; name: string; [field: string]: unknown }) => void;
  /** Extra fields the endpoint requires beyond the name (defaults for the rest). */
  extra?: Record<string, string>;
  nameField?: string;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const newBtn = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);

  // Esc cancels the inline input only (a layer of the shared escape stack, so the form it
  // sits in stays open), and focus goes back to "New".
  useEscapeLayer(open, () => cancel());
  useEffect(() => {
    if (open || !refocus.current) return;
    refocus.current = false;
    newBtn.current?.focus({ preventScroll: true });
  }, [open]);

  function cancel() {
    if (busy) return;
    refocus.current = true;
    setOpen(false);
  }

  async function create() {
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      const created = await apiCall<{ id: string; [field: string]: unknown }>("POST", endpoint, {
        [nameField]: trimmed,
        description: "",
        ...extra,
      });
      const row = { ...created, id: created.id, name: String(created[nameField] ?? trimmed) };
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
        ref={newBtn}
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
          if (e.key === "Escape") {
            e.preventDefault(); // consumed here: the escape stack leaves the form open
            cancel();
          }
        }}
      />
      <button type="button" className="btn sm" disabled={busy || !name.trim()} onClick={create}>
        Add
      </button>
      <button type="button" className="btn secondary sm" disabled={busy} onClick={cancel}>
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

/* ================================================================ governed lists ==
   The phase-1 lookup lists (`/lookups/{key}`): risk category, regulator, country …
   Values have a stable machine key (`value`) and a label people read; renaming the label
   never breaks a record. Deactivate a value to retire it — records keep pointing at it,
   pickers stop offering it. Delete is only for values nothing uses (the API answers
   409 otherwise). Two-level lists (risk category L1 → L2) show a Parent column. */

/** Lists that are two levels deep by design, so the Parent field is always offered. */
const TWO_LEVEL_LISTS = new Set(["risk_category"]);

type GovernedDraft = { label: string; description: string; parent_id: string };
const EMPTY_GOVERNED: GovernedDraft = { label: "", description: "", parent_id: "" };

/**
 * One governed lookup list as a collapsible admin card: add, rename, describe,
 * re-parent, reorder (↑ ↓ within siblings), deactivate / reactivate and delete.
 * Writes need `org:write`; without it the card is read-only.
 *
 * @param list  the list from `GET /lookups`
 * @param help  where the list's values show up, so an admin knows what they edit
 * @param defaultOpen  expand on first render
 */
export function GovernedLookupManager({
  list,
  help,
  defaultOpen = false,
}: {
  list: LookupList;
  help?: string;
  defaultOpen?: boolean;
}) {
  const canManage = useHasPermission(LOOKUP_MANAGE_PERMISSION);
  const [open, setOpen] = useState(defaultOpen);
  const [rows, setRows] = useState<LookupValue[] | null>(null);
  const [draft, setDraft] = useState<GovernedDraft>(EMPTY_GOVERNED);
  const [edits, setEdits] = useState<Record<string, LookupPatch>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [counts, setCounts] = useState({ total: list.total, active: list.active });

  const load = useCallback(async () => {
    try {
      const data = await lookupValues(list.key, { active: "all", usage: true });
      setRows(data);
      setCounts({ total: data.length, active: data.filter((r) => r.active).length });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [list.key]);

  useEffect(() => {
    if (open && rows === null) load();
  }, [open, rows, load]);

  const twoLevel = TWO_LEVEL_LISTS.has(list.key) || (rows ?? []).some((r) => r.parent_id);
  const parents = useMemo(() => (rows ?? []).filter((r) => r.depth === 0), [rows]);

  async function run(action: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
      if (done) toast(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  function create(e: React.FormEvent) {
    e.preventDefault();
    const label = draft.label.trim();
    if (!label) return;
    run(async () => {
      await createLookupValue(list.key, {
        label,
        description: draft.description.trim(),
        parent_id: draft.parent_id || null,
      });
      setDraft(EMPTY_GOVERNED);
    }, `"${label}" added`);
  }

  function edit(row: LookupValue, patch: LookupPatch) {
    setEdits((p) => ({ ...p, [row.id]: { ...p[row.id], ...patch } }));
  }

  function save(row: LookupValue) {
    const patch = edits[row.id];
    if (!patch) return;
    run(async () => {
      await updateLookupValue(list.key, row.id, patch);
      setEdits((p) => {
        const next = { ...p };
        delete next[row.id];
        return next;
      });
    }, "Saved");
  }

  function toggleActive(row: LookupValue) {
    run(
      () => updateLookupValue(list.key, row.id, { active: !row.active }),
      row.active ? `"${row.label}" deactivated` : `"${row.label}" reactivated`,
    );
  }

  async function remove(row: LookupValue) {
    const ok = await confirmDialog({
      title: `Delete "${row.label}"?`,
      message: row.builtin
        ? "This is a built-in default: it will be re-created the next time the server starts. Deactivate it instead to retire it for good."
        : "Only values no record uses can be deleted. This cannot be undone.",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    run(() => deleteLookupValue(list.key, row.id), "Deleted");
  }

  function move(row: LookupValue, dir: -1 | 1) {
    const siblings = (rows ?? []).filter((r) => r.parent_id === row.parent_id);
    const i = siblings.findIndex((r) => r.id === row.id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= siblings.length) return;
    const ids = siblings.map((r) => r.id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    run(() => reorderLookupValues(list.key, ids));
  }

  function field<K extends keyof LookupPatch>(row: LookupValue, k: K): LookupPatch[K] {
    const pending = edits[row.id];
    return (pending && k in pending ? pending[k] : row[k as keyof LookupValue]) as LookupPatch[K];
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 12 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{ all: "unset", cursor: "pointer", display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", width: "100%" }}
      >
        <span aria-hidden style={{ width: 12, display: "inline-block" }}>{open ? "▾" : "▸"}</span>
        <h2 style={{ margin: 0, fontSize: 16 }}>{list.name}</h2>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {counts.active} active{counts.total > counts.active ? ` · ${counts.total - counts.active} inactive` : ""}
        </span>
        {help && <span className="muted" style={{ fontSize: 12.5, flexBasis: "100%", paddingLeft: 22 }}>{help}</span>}
      </button>

      {open && (
        <div style={{ marginTop: 12 }}>
          {error && <div className="error" style={{ margin: "10px 0" }}>{error}</div>}

          {canManage && (
            <form onSubmit={create} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", margin: "0 0 12px" }}>
              <div style={{ flex: "1 1 200px" }}>
                <label className="label">Label</label>
                <input
                  className="input"
                  value={draft.label}
                  required
                  placeholder="New value…"
                  onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
                />
              </div>
              {twoLevel && (
                <div style={{ flex: "0 1 200px" }}>
                  <label className="label">Parent</label>
                  <select
                    className="select"
                    value={draft.parent_id}
                    onChange={(e) => setDraft((d) => ({ ...d, parent_id: e.target.value }))}
                  >
                    <option value="">— Top level —</option>
                    {parents.map((p) => (
                      <option key={p.id} value={p.id}>{p.label}</option>
                    ))}
                  </select>
                </div>
              )}
              <div style={{ flex: "2 1 240px" }}>
                <label className="label">Description</label>
                <input
                  className="input"
                  value={draft.description}
                  onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                />
              </div>
              <button className="btn" disabled={busy || !draft.label.trim()}>Add</button>
            </form>
          )}

          {rows === null ? (
            <div className="muted" style={{ fontSize: 13 }}>Loading…</div>
          ) : rows.length === 0 ? (
            <div className="muted" style={{ fontSize: 13 }}>No values yet{canManage ? " — add the first one above." : "."}</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 64 }} aria-label="Order" />
                    <th>Label</th>
                    {twoLevel && <th style={{ width: 170 }}>Parent</th>}
                    <th>Description</th>
                    <th style={{ width: 80 }}>Used by</th>
                    <th style={{ width: 250 }} />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const siblings = rows.filter((r) => r.parent_id === row.parent_id);
                    const pos = siblings.findIndex((r) => r.id === row.id);
                    const dirty = !!edits[row.id];
                    const used = row.usage ?? 0;
                    return (
                      <tr key={row.id} style={row.active ? undefined : { opacity: 0.6 }}>
                        <td>
                          {canManage && (
                            <div style={{ display: "flex", gap: 2 }}>
                              <button type="button" className="btn secondary sm" aria-label={`Move ${row.label} up`} disabled={busy || pos <= 0} onClick={() => move(row, -1)}>↑</button>
                              <button type="button" className="btn secondary sm" aria-label={`Move ${row.label} down`} disabled={busy || pos >= siblings.length - 1} onClick={() => move(row, 1)}>↓</button>
                            </div>
                          )}
                        </td>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, paddingLeft: row.depth * 18 }}>
                            {row.depth > 0 && <span className="muted" aria-hidden>↳</span>}
                            <input
                              className="input"
                              style={{ padding: "4px 8px", fontSize: 13 }}
                              value={String(field(row, "label") ?? "")}
                              disabled={!canManage}
                              aria-label="Label"
                              onChange={(e) => edit(row, { label: e.target.value })}
                            />
                          </div>
                          <div className="muted" style={{ fontSize: 11, paddingLeft: row.depth * 18 + (row.depth ? 18 : 0), marginTop: 2 }}>
                            {row.value}
                          </div>
                        </td>
                        {twoLevel && (
                          <td>
                            <select
                              className="select"
                              style={{ padding: "4px 8px", fontSize: 13 }}
                              value={String(field(row, "parent_id") ?? "")}
                              disabled={!canManage || rows.some((r) => r.parent_id === row.id)}
                              title={rows.some((r) => r.parent_id === row.id) ? "Has child values of its own" : undefined}
                              aria-label="Parent"
                              onChange={(e) => edit(row, { parent_id: e.target.value || null })}
                            >
                              <option value="">— Top level —</option>
                              {parents.filter((p) => p.id !== row.id).map((p) => (
                                <option key={p.id} value={p.id}>{p.label}</option>
                              ))}
                            </select>
                          </td>
                        )}
                        <td>
                          <input
                            className="input"
                            style={{ padding: "4px 8px", fontSize: 13 }}
                            value={String(field(row, "description") ?? "")}
                            disabled={!canManage}
                            aria-label="Description"
                            onChange={(e) => edit(row, { description: e.target.value })}
                          />
                        </td>
                        <td className="muted" style={{ fontSize: 13 }}>{used ? `${used} record${used === 1 ? "" : "s"}` : "—"}</td>
                        <td>
                          <div style={{ display: "flex", gap: 6, alignItems: "center", justifyContent: "flex-end", flexWrap: "wrap" }}>
                            {row.builtin && <Badge tone="neutral" plain>default</Badge>}
                            {!row.active && <Badge tone="medium" plain>inactive</Badge>}
                            {canManage && dirty && (
                              <button className="btn sm" type="button" disabled={busy} onClick={() => save(row)}>Save</button>
                            )}
                            {canManage && (
                              <button className="btn secondary sm" type="button" disabled={busy} onClick={() => toggleActive(row)}>
                                {row.active ? "Deactivate" : "Reactivate"}
                              </button>
                            )}
                            {canManage && (
                              <button
                                className="btn secondary sm"
                                type="button"
                                disabled={busy || used > 0}
                                title={used > 0 ? `In use by ${used} record${used === 1 ? "" : "s"}; deactivate it instead.` : undefined}
                                onClick={() => remove(row)}
                              >
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
      )}
    </div>
  );
}
