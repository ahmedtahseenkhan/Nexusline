"use client";

/* An organisation's custom fields as a tab of a record's Add / Edit form.

     const cfForm = useCustomFieldForm("vendor");
     function openNew()         { …; cfForm.start(null); setShowForm(true); }
     function openEdit(v)       { …; cfForm.start(v.id); setShowForm(true); }
     async function save() {
       const saved = editing ? await api.updateVendor(…) : await api.createVendor(…);
       await cfForm.save(saved.id);                          // after the record exists
       …
     }
     <FormModal tabs={[…, ...cfForm.tabs]} … />

   The tab appears only when the module has enabled fields. Required custom fields are
   plain `required` inputs, so FormModal's validation covers them. */

import { useCallback, useEffect, useState } from "react";
import { api, type CustomField } from "@/lib/api";
import CustomFieldsEditor from "@/components/CustomFieldsEditor";
import type { FormTab } from "@/components/FormModal";

const SAVED_EVENT = "custom-fields-saved";

/** Tell any open view of this record's custom fields (a drawer's card, a dossier's
 *  Details) to re-read them — the form saves outside those views. */
export function announceCustomFieldsSaved(model: string, entityId: string) {
  window.dispatchEvent(new CustomEvent(SAVED_EVENT, { detail: { model, entityId } }));
}

/** Run `reload` whenever this record's custom fields are saved elsewhere. */
export function useCustomFieldsSaved(model: string, entityId: string | null | undefined, reload: () => void) {
  useEffect(() => {
    if (!entityId) return;
    const onSaved = (e: Event) => {
      const d = (e as CustomEvent<{ model: string; entityId: string }>).detail;
      if (d.model === model && d.entityId === entityId) reload();
    };
    window.addEventListener(SAVED_EVENT, onSaved);
    return () => window.removeEventListener(SAVED_EVENT, onSaved);
  }, [model, entityId, reload]);
}

export type CustomFieldForm = {
  /** The "Custom fields" tab, or none when the module has no enabled fields. */
  tabs: FormTab[];
  /** Reset for a new record (null) or load an existing record's values. */
  start(entityId: string | null | undefined): void;
  /** Persist the values onto the saved record. No-op when there are no fields. */
  save(entityId: string): Promise<void>;
};

export function useCustomFieldForm(model: string): CustomFieldForm {
  const [defs, setDefs] = useState<CustomField[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    api.customFields(model).then((d) => setDefs(d.filter((x) => x.enabled))).catch(() => setDefs([]));
  }, [model]);

  const start = useCallback(
    (entityId: string | null | undefined) => {
      setValues({});
      if (!entityId) return;
      api
        .customFieldValues(model, entityId)
        .then((rows) => setValues(Object.fromEntries(rows.map((r) => [r.field.id, r.value]))))
        .catch(() => {});
    },
    [model],
  );

  const save = useCallback(
    async (entityId: string) => {
      if (defs.length === 0) return;
      await api.setCustomFieldValues(model, entityId, values);
      announceCustomFieldsSaved(model, entityId);
    },
    [model, defs.length, values],
  );

  const tabs: FormTab[] = defs.length
    ? [{
        id: "custom",
        label: "Custom fields",
        required: defs.some((d) => d.required),
        content: (
          <CustomFieldsEditor
            fields={defs}
            values={values}
            onChange={(id, v) => setValues((p) => ({ ...p, [id]: v }))}
          />
        ),
      }]
    : [];

  return { tabs, start, save };
}
