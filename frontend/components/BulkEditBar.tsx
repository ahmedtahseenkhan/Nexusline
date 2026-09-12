"use client";

/* Bulk edit for a register's selection — the DataTable `bulkActions` slot.

     <DataTable
       bulkActions={(rows, clear) => (
         <>
           <BulkEditBar entityType="control" rows={rows} onDone={() => { clear(); reload(); }} mapRequirements />
           <button className="btn secondary sm" onClick={() => removeMany(rows, clear)}>Delete selected</button>
         </>
       )}
     />

   One "Edit N ▾" menu offers what the register can set on many records at once — owner,
   next review (a control's next test), category, status, review frequency — as the
   server's allow-list says (`GET /records/{type}/bulk-fields`), with the register's own
   picker: UserPicker for a person, BusinessUnitSelect for an asset's owning unit,
   LookupSelect for the register's governed list, the statuses its form offers. Choosing
   a value shows a confirmation naming the change, how many records it touches and the
   register rule that may skip some; the result comes back as one toast ("Updated 38;
   2 skipped: archived"). Users without the register's write permission see nothing.
   `mapRequirements` adds "Map to requirements…" (controls only). */

import { useEffect, useState, type ReactNode } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import Menu, { type MenuItem } from "@/components/Menu";
import FormModal from "@/components/FormModal";
import UserPicker from "@/components/UserPicker";
import LookupSelect from "@/components/LookupSelect";
import BusinessUnitSelect from "@/components/BusinessUnitSelect";
import AsyncMultiSelect from "@/components/AsyncMultiSelect";
import { type Option as AsyncOption } from "@/components/AsyncSelect";
import { Field, Select } from "@/components/fields";

/* ------------------------------------------------------------------ types --- */
export type BulkOption = { value: string; label: string };
export type BulkField = {
  key: "owner_id" | "next_review_date" | "review_frequency" | "category_id" | "status";
  label: string;
  kind: "user" | "unit" | "lookup" | "date" | "frequency" | "status";
  lookup_key: string | null;
  options: BulkOption[];
  note: string;
};
export type BulkFields = { entity_type: string; noun: string; can_edit: boolean; fields: BulkField[] };
export type BulkResultItem = {
  id: string;
  reference: string;
  label: string;
  outcome: "updated" | "skipped";
  reason: string;
  changed: string[];
};
export type BulkResult = {
  entity_type: string;
  batch_id: string;
  updated: number;
  skipped: number;
  summary: string;
  results: BulkResultItem[];
};

/* -------------------------------------------------------------------- API --- */
const seg = (s: string) => encodeURIComponent(s);
const fieldsCache = new Map<string, Promise<BulkFields | null>>();

export const bulk = {
  /** What the register can set in bulk (cached per page load). */
  fields(entityType: string): Promise<BulkFields | null> {
    if (!fieldsCache.has(entityType)) {
      fieldsCache.set(
        entityType,
        apiCall<BulkFields>("GET", `/records/${seg(entityType)}/bulk-fields`).catch(() => {
          fieldsCache.delete(entityType);
          return null;
        }),
      );
    }
    return fieldsCache.get(entityType)!;
  },
  /** Set values on many records; each id comes back updated or skipped with a reason. */
  update(entityType: string, ids: string[], patch: Partial<Record<BulkField["key"], string>>) {
    return apiCall<BulkResult>("PATCH", `/records/${seg(entityType)}/bulk`, { ids, patch });
  },
  /** Link every control to every requirement (links are only added). */
  mapRequirements(controlIds: string[], requirementIds: string[]) {
    return apiCall<BulkResult>("POST", "/controls/bulk/map-requirements", {
      control_ids: controlIds,
      requirement_ids: requirementIds,
    });
  },
};

/** Toast a bulk result: success when everything changed, info when some were skipped,
 *  error when nothing was. */
export function toastBulkResult(res: BulkResult) {
  toast(res.summary, !res.skipped ? "success" : res.updated ? "info" : "error");
}

/* -------------------------------------------------------------- component --- */
type Row = { id: string; reference?: string | null; name?: string | null; title?: string | null };

type Props = {
  /** Shared entity registry key: "control", "issue", "incident", "policy", "vendor", "asset", "risk". */
  entityType: string;
  /** The selected rows (DataTable `bulkActions` gives them). */
  rows: Row[];
  /** Called after a run that changed something — clear the selection and reload. */
  onDone: (result: BulkResult) => void;
  /** Only offer these fields (default: everything the register allows). */
  only?: BulkField["key"][];
  /** Offer "Map to requirements…" (controls). */
  mapRequirements?: boolean;
};

const rowName = (r: Row) => [r.reference, r.name || r.title].filter(Boolean).join(" ") || r.id.slice(0, 8);

function selectionDetails(rows: Row[], note: string): ReactNode {
  const shown = rows.slice(0, 5).map(rowName);
  return (
    <>
      <div>
        {shown.join(", ")}
        {rows.length > shown.length ? `, and ${rows.length - shown.length} more` : ""}.
      </div>
      {note && <div className="muted" style={{ marginTop: 6 }}>{note}</div>}
      <div className="muted" style={{ marginTop: 6 }}>
        Archived records, and records that already have this value, are skipped. Each change is recorded on the
        record&apos;s activity trail.
      </div>
    </>
  );
}

export default function BulkEditBar({ entityType, rows, onDone, only, mapRequirements }: Props) {
  const [meta, setMeta] = useState<BulkFields | null>(null);
  const [editing, setEditing] = useState<BulkField | null>(null);
  const [value, setValue] = useState<string>("");
  const [valueText, setValueText] = useState<string>("");
  const [mapping, setMapping] = useState<AsyncOption[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    bulk.fields(entityType).then((m) => live && setMeta(m));
    return () => {
      live = false;
    };
  }, [entityType]);

  if (!meta || !meta.can_edit || rows.length === 0) return null;
  const fields = meta.fields.filter((f) => !only || only.includes(f.key));
  const n = rows.length;
  const nounFor = (count: number) => (count === 1 ? meta.noun.replace(/ies$/, "y").replace(/s$/, "") : meta.noun);

  function start(f: BulkField) {
    setEditing(f);
    setValue("");
    setValueText("");
    setError(null);
  }

  async function apply() {
    if (!editing) return;
    if (!value) {
      setError(`Choose the ${editing.label.toLowerCase()} to set.`);
      return;
    }
    const shown = valueText || editing.options.find((o) => o.value === value)?.label || value;
    const ok = await confirmDialog({
      title: `Set ${editing.label.toLowerCase()} on ${n} ${nounFor(n)}?`,
      message: `${editing.label} → ${shown}.`,
      details: selectionDetails(rows, editing.note),
      confirmLabel: `Apply to ${n}`,
    });
    if (!ok) return;
    setSaving(true);
    setError(null);
    try {
      const res = await bulk.update(entityType, rows.map((r) => r.id), { [editing.key]: value });
      toastBulkResult(res);
      setEditing(null);
      if (res.updated) onDone(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not apply the change");
    } finally {
      setSaving(false);
    }
  }

  async function applyMapping() {
    if (!mapping?.length) {
      setError("Choose at least one requirement.");
      return;
    }
    const ok = await confirmDialog({
      title: `Map ${n} ${nounFor(n)} to ${mapping.length} requirement${mapping.length === 1 ? "" : "s"}?`,
      message: `Adds ${mapping.map((m) => m.label).slice(0, 4).join(", ")}${mapping.length > 4 ? ` and ${mapping.length - 4} more` : ""} to every selected control. Existing mappings are kept.`,
      details: selectionDetails(rows, "Mapping alone is not assurance: a clause counts as assured only once a mapped control has passed a reviewed test."),
      confirmLabel: "Map",
    });
    if (!ok) return;
    setSaving(true);
    setError(null);
    try {
      const res = await bulk.mapRequirements(rows.map((r) => r.id), mapping.map((m) => m.value));
      toastBulkResult(res);
      setMapping(null);
      if (res.updated) onDone(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not map the controls");
    } finally {
      setSaving(false);
    }
  }

  const searchRequirements = (q: string) =>
    apiCall<{ id: string; reference: string; title: string; framework: string }[]>(
      "GET", `/requirements?search=${encodeURIComponent(q)}&limit=20`,
    ).then((list) => list.map((r) => ({ value: r.id, label: `${r.reference ? r.reference + " · " : ""}${r.title}`, sub: r.framework })));

  const items: MenuItem[] = fields.map((f) => ({
    label: `Set ${f.label.toLowerCase()}…`,
    hint: f.note || undefined,
    onClick: () => start(f),
  }));
  if (mapRequirements) {
    if (items.length) items.push("divider");
    items.push({
      label: "Map to requirements…",
      hint: "Link every selected control to the same framework clauses.",
      onClick: () => {
        setMapping([]);
        setError(null);
      },
    });
  }
  if (!items.length) return null;

  function picker(f: BulkField): ReactNode {
    switch (f.kind) {
      case "user":
        return <UserPicker value={value || null} onChange={(id, ref) => { setValue(id ?? ""); setValueText(ref ? ref.full_name || ref.email : ""); }} placeholder="Search people…" />;
      case "unit":
        return <BusinessUnitSelect value={value || null} onChange={(id, ref) => { setValue(id ?? ""); setValueText(ref?.path || ref?.name || ""); }} />;
      case "lookup":
        return <LookupSelect lookupKey={f.lookup_key || ""} value={value || null} onChange={(id, ref) => { setValue(id ?? ""); setValueText(ref ? ref.path || ref.label : ""); }} placeholder="Choose a value…" />;
      case "date":
        return <input className="input" type="date" value={value} onChange={(e) => { setValue(e.target.value); setValueText(e.target.value); }} required />;
      default:
        return <Select value={value} onChange={(v) => { setValue(v); setValueText(f.options.find((o) => o.value === v)?.label ?? v); }} options={f.options} placeholder="Choose one…" />;
    }
  }

  return (
    <>
      <Menu label={<>Edit {n} ▾</>} items={items} align="left" className="btn secondary sm" />
      {editing && (
        <FormModal
          title={`Set ${editing.label.toLowerCase()} on ${n} ${nounFor(n)}`}
          tabs={[{
            id: "value",
            label: editing.label,
            content: (
              <>
                <Field label={editing.label} required help={editing.note || undefined}>{picker(editing)}</Field>
                <p className="muted" style={{ fontSize: 13, margin: 0 }}>
                  Applies to the {n} selected {nounFor(n)}. You&apos;ll see a summary before anything changes.
                </p>
              </>
            ),
          }]}
          onClose={() => setEditing(null)}
          onSave={apply}
          saving={saving}
          error={error}
          saveLabel={`Review ${n} change${n === 1 ? "" : "s"}`}
        />
      )}
      {mapping !== null && (
        <FormModal
          title={`Map ${n} ${nounFor(n)} to requirements`}
          tabs={[{
            id: "requirements",
            label: "Requirements",
            content: (
              <Field label="Requirements" help="Framework clauses every selected control implements. Links are added; none are removed.">
                <AsyncMultiSelect search={searchRequirements} value={mapping} onChange={setMapping} placeholder="Search clauses by reference or title…" />
              </Field>
            ),
          }]}
          onClose={() => setMapping(null)}
          onSave={applyMapping}
          saving={saving}
          error={error}
          saveLabel="Review mapping"
        />
      )}
    </>
  );
}
