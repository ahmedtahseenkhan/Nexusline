"use client";

/* Picker for a governed lookup list (risk category, regulator, country …).

   Usage in a form whose record has `category_id` (+ legacy text `category`):

     <Field label="Category">
       <LookupSelect
         lookupKey="risk_category"
         value={form.category_id}
         onChange={(id) => set("category_id", id)}
         legacyText={form.category}      // the old free text, shown until a value is picked
         allowCreate
       />
     </Field>

   - Options come from the server as the user types (`GET /lookups/{key}?search=`), active
     values only; a child value reads "Parent › Child".
   - The current value's label is resolved from a per-page cache of the list (inactive
     values included, marked "(inactive)"), so a saved id always shows its name.
   - `allowCreate` adds "＋ New" for users who can manage lookups (`org:write`): it creates
     a top-level value and selects it.
   - `legacyText` with no value shows "Was: <text> — pick a value" under the picker. */

import { useCallback, useEffect, useRef, useState } from "react";
import AsyncSelect, { type Option } from "@/components/AsyncSelect";
import { InlineLookupCreate } from "@/components/LookupManager";
import {
  LOOKUP_MANAGE_PERMISSION,
  cachedLookupList,
  invalidateLookupCache,
  lookupValues,
  type LookupValue,
} from "@/lib/masterData";
import { useHasPermission } from "@/lib/tenantSettings";

export type LookupSelectProps = {
  /** Governed list key, e.g. "risk_category", "regulator", "country". */
  lookupKey: string;
  /** Selected lookup id, or null. */
  value: string | null;
  /** Called with the new id (null when cleared) and the picked value's details. */
  onChange: (id: string | null, ref?: LookupValue | null) => void;
  /** Offer "＋ New" (only shown to users holding org:write). */
  allowCreate?: boolean;
  placeholder?: string;
  /** The record's old free-text value; hinted while `value` is null. */
  legacyText?: string | null;
  disabled?: boolean;
};

/** "Was: <text> — pick a value" hint shown under a picker whose record still carries
 *  only the pre-upgrade free text. Renders nothing when there is a value or no text. */
export function LegacyHint({ value, legacyText }: { value: string | null; legacyText?: string | null }) {
  if (value || !legacyText || !legacyText.trim()) return null;
  return (
    <div className="help" style={{ fontSize: 12, color: "var(--amber, #b45309)", marginTop: 4 }}>
      Was: <strong>{legacyText}</strong> — pick a value
    </div>
  );
}

function toOption(v: LookupValue): Option {
  return { value: v.id, label: v.path || v.label };
}

/** Governed-list picker. See the file header for behaviour. */
export default function LookupSelect({
  lookupKey,
  value,
  onChange,
  allowCreate,
  placeholder = "Choose…",
  legacyText,
  disabled,
}: LookupSelectProps) {
  const canCreate = useHasPermission(LOOKUP_MANAGE_PERMISSION) && !!allowCreate && !disabled;
  const [selected, setSelected] = useState<LookupValue | null>(null);
  /** The id the last label lookup was for — tells "still loading" from "not found". */
  const [resolvedFor, setResolvedFor] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    if (!value) {
      setSelected(null);
      return;
    }
    if (selected?.id === value) return;
    cachedLookupList(lookupKey)
      .then((rows) => live && setSelected(rows.find((r) => r.id === value) ?? null))
      .catch(() => live && setSelected(null))
      .finally(() => live && setResolvedFor(value));
    return () => {
      live = false;
    };
  }, [lookupKey, value]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Values from the latest search, so a pick needs no second lookup. */
  const lastResults = useRef(new Map<string, LookupValue>());

  const search = useCallback(
    async (q: string) => {
      const rows = await lookupValues(lookupKey, { search: q, active: "true" });
      lastResults.current = new Map(rows.map((r) => [r.id, r]));
      return rows.map(toOption);
    },
    [lookupKey],
  );

  function pick(id: string | null) {
    const row = id ? lastResults.current.get(id) ?? null : null;
    setSelected(row);
    onChange(id, row);
  }

  const selectedLabel = !value
    ? undefined
    : selected?.id === value
      ? `${selected.path || selected.label}${selected.active ? "" : " (inactive)"}`
      : resolvedFor === value
        ? "Unknown value"
        : "Loading…";

  return (
    <div>
      <AsyncSelect
        search={search}
        value={value}
        selectedLabel={selectedLabel}
        onChange={(id) => pick(id)}
        placeholder={placeholder}
        disabled={disabled}
      />
      <LegacyHint value={value} legacyText={legacyText} />
      {canCreate && (
        <InlineLookupCreate
          endpoint={`/lookups/${encodeURIComponent(lookupKey)}`}
          nameField="label"
          onCreated={(row) => {
            invalidateLookupCache(lookupKey);
            const created = row as unknown as LookupValue;
            setSelected(created);
            onChange(created.id, created);
          }}
        />
      )}
    </div>
  );
}
