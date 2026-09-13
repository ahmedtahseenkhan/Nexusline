"use client";

/* An organisation's custom fields for one record.

     <CustomFieldsPanel model="risk" entityId={r.id} />               // read card; "Edit" opens the editor
     <CustomFieldsPanel model="risk" entityId={r.id} mode="edit" />   // the always-editable form (as before)

   Read mode (the default, record-page-spec §3.5): set values as label/value rows, unset
   ones folded into "2 not set: A and B · Fill in", and Edit to reveal the editor with
   Save and Cancel (Esc cancels). Labels are trimmed. For admins, a field whose name
   repeats a built-in field (`builtInLabels`, e.g. "Owner", or "Control Owner" on a
   control) carries the note "Same name as the built-in “Owner” field — rename or retire
   it in Settings → Custom fields."

   Dossier pages fold custom fields into their Details section instead of a card:

     const cf = useCustomFieldFacts("control", c.id, { builtInLabels: ["Owner", "Operator"] });
     <FactList items={[...facts, ...cf.facts]}
       onFillIn={(tab) => (tab === "custom" ? cf.setEditing(true) : openEdit(c, tab))} />
     {cf.editor}                                  // the editor + Save / Cancel while editing */

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type CustomFieldValueItem } from "@/lib/api";
import CustomFieldsEditor from "@/components/CustomFieldsEditor";
import FactList from "@/components/record/FactList";
import type { FactItem } from "@/components/record/types";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { formatDate } from "@/lib/format";
import { useHasPermission } from "@/lib/tenantSettings";

type Props = {
  model: string;
  entityId: string;
  /** "read" (default): a read card with Edit. "edit": the always-editable form. */
  mode?: "read" | "edit";
  /** Built-in field names on this record type, for the admin duplicate-name note. */
  builtInLabels?: string[];
};

export default function CustomFieldsPanel({ model, entityId, mode = "read", builtInLabels }: Props) {
  if (mode === "edit") return <CustomFieldsEditPanel model={model} entityId={entityId} />;
  return <CustomFieldsReadPanel model={model} entityId={entityId} builtInLabels={builtInLabels} />;
}

function CustomFieldsReadPanel({ model, entityId, builtInLabels }: { model: string; entityId: string; builtInLabels?: string[] }) {
  const cf = useCustomFieldFacts(model, entityId, { builtInLabels });
  const editBtn = useRef<HTMLButtonElement>(null);
  const wasEditing = useRef(false);
  // The Edit button is hidden while editing; give it focus back when the editor closes.
  useEffect(() => {
    if (wasEditing.current && !cf.editing) editBtn.current?.focus({ preventScroll: true });
    wasEditing.current = cf.editing;
  }, [cf.editing]);
  if (cf.count === 0) return null;
  return (
    <div className="card rec-cf-card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3>Custom fields</h3>
        {!cf.editing && (
          <button ref={editBtn} type="button" className="btn secondary sm" onClick={() => cf.setEditing(true)} aria-label="Edit custom fields">
            Edit
          </button>
        )}
      </div>
      <div className="card-pad">
        {cf.editing ? cf.editor : <FactList items={cf.facts} onFillIn={() => cf.setEditing(true)} />}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- hook --- */

const norm = (s: string) => s.trim().toLowerCase().replace(/\s+/g, " ");

/** "Control Owner" on a control → "owner": the label without the record type's own name. */
function withoutModel(label: string, model: string): string {
  const n = norm(label);
  const m = norm(model.replace(/_/g, " "));
  return n.startsWith(`${m} `) ? n.slice(m.length + 1) : n;
}

function displayValue(item: CustomFieldValueItem): string {
  const v = (item.value ?? "").trim();
  if (!v) return "";
  switch (item.field.field_type) {
    case "checkbox":
      return v === "true" ? "Yes" : v === "false" ? "No" : v;
    case "date":
      return formatDate(v);
    default:
      return v;
  }
}

export type CustomFieldFacts = {
  /** One fact per field: origin "custom", tab "custom". */
  facts: FactItem[];
  count: number;
  loading: boolean;
  editing: boolean;
  setEditing(v: boolean): void;
  /** The editor + Save / Cancel, rendered by the page under Details while editing. */
  editor: ReactNode | null;
  /** The "Edit custom fields" link for a viewer who may edit, while the editor is closed
   *  and the record has custom fields: render it under `editor`. Without it a record whose
   *  fields are all set (or whose first unset fact is a built-in one, which "Fill in"
   *  reaches first) offers no way into the editor. */
  editLink(canEdit: boolean): ReactNode | null;
  reload(): Promise<void>;
};

/** The record's custom fields as FactList items, plus an on-demand editor. */
export function useCustomFieldFacts(
  model: string,
  entityId: string | null | undefined,
  opts?: { builtInLabels?: string[] },
): CustomFieldFacts {
  const [items, setItems] = useState<CustomFieldValueItem[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditingState] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isAdmin = useHasPermission("settings:manage");
  const builtIns = opts?.builtInLabels ?? [];
  const builtInKey = builtIns.join("|");

  const load = useCallback(async () => {
    if (!entityId) {
      setItems([]);
      setValues({});
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const rows = await api.customFieldValues(model, entityId);
      setItems(rows);
      setValues(Object.fromEntries(rows.map((r) => [r.field.id, r.value])));
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [model, entityId]);

  useEffect(() => {
    setEditingState(false);
    setError(null);
    load();
  }, [load]);

  const setEditing = useCallback(
    (v: boolean) => {
      if (!v) {
        // Cancel: back to the saved values.
        setValues(Object.fromEntries(items.map((r) => [r.field.id, r.value])));
        setError(null);
      }
      setEditingState(v);
    },
    [items],
  );

  const dupNote = useCallback(
    (label: string): string | null => {
      if (!isAdmin || builtIns.length === 0) return null;
      const key = withoutModel(label, model);
      const hit = builtIns.find((b) => norm(b) === key || norm(b) === norm(label));
      return hit ? `Same name as the built-in “${hit}” field — rename or retire it in Settings → Custom fields.` : null;
    },
    // builtInKey stands in for the array
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isAdmin, builtInKey, model],
  );

  const facts: FactItem[] = items.map((it) => {
    const shown = displayValue(it);
    const note = dupNote(it.field.label);
    return {
      key: `cf-${it.field.id}`,
      label: it.field.label.trim(),
      value: shown ? (note ? <>{shown}<span className="rec-cf-note">{note}</span></> : shown) : null,
      wide: it.field.field_type === "textarea",
      hint: it.field.help_text || undefined,
      tab: "custom",
      origin: "custom",
    };
  });

  async function save() {
    if (!entityId) return;
    setSaving(true);
    setError(null);
    try {
      await api.setCustomFieldValues(model, entityId, values);
      await load();
      setEditingState(false);
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const notes = items.map((it) => ({ id: it.field.id, label: it.field.label.trim(), note: dupNote(it.field.label) })).filter((n) => n.note);

  const editor =
    editing && items.length > 0 ? (
      <CustomFieldsEditorPanel
        onCancel={() => setEditing(false)}
        onSave={save}
        saving={saving}
        error={error}
      >
        {notes.map((n) => (
          <p key={n.id} className="rec-cf-note">
            <b>{n.label}</b>: {n.note}
          </p>
        ))}
        <CustomFieldsEditor
          fields={items.map((i) => i.field)}
          values={values}
          onChange={(id, v) => setValues((prev) => ({ ...prev, [id]: v }))}
        />
      </CustomFieldsEditorPanel>
    ) : null;

  const editLink = (canEdit: boolean): ReactNode | null =>
    canEdit && items.length > 0 && !editing ? (
      <p className="rec-none">
        <button type="button" className="rec-link" onClick={() => setEditing(true)}>Edit custom fields</button>
      </p>
    ) : null;

  return { facts, count: items.length, loading, editing, setEditing, editor, editLink, reload: load };
}

/** The on-demand editor frame: focus moves in on open and back on close; Esc cancels. */
function CustomFieldsEditorPanel({
  children,
  onCancel,
  onSave,
  saving,
  error,
}: {
  children: ReactNode;
  onCancel: () => void;
  onSave: () => void;
  saving: boolean;
  error: string | null;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // Esc cancels, unless saving. Anything opened on top (a picker, a dialog) is a later
  // layer of the escape stack and closes first.
  useEscapeLayer(true, () => {
    if (!saving) onCancel();
  });
  useEffect(() => {
    const back = document.activeElement as HTMLElement | null;
    requestAnimationFrame(() => ref.current?.querySelector<HTMLElement>("input, select, textarea, button")?.focus());
    return () => {
      if (back && back.isConnected) back.focus({ preventScroll: true });
    };
  }, []);
  return (
    <div className="rec-disclosure rec-cf-editor" role="group" aria-label="Edit custom fields" ref={ref}>
      {children}
      <div className="row">
        <button type="button" className="btn secondary sm" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" className="btn secondary sm" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        {error && <span className="rec-error" role="alert">{error}</span>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------ mode="edit" (as before) --- */

function CustomFieldsEditPanel({ model, entityId }: { model: string; entityId: string }) {
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
