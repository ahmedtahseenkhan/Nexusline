"use client";

/* Pick one business process, optionally within a business unit.

     <BusinessUnitSelect value={form.business_unit_id} onChange={(id) => set("business_unit_id", id)} />
     <ProcessSelect
       value={form.process_id}
       businessUnitId={form.business_unit_id}   // narrow to the chosen unit (optional)
       onChange={(id) => set("process_id", id)}
       legacyText={record.process}
     />

   Searches `GET /pickers/processes` as the user types; each option shows its business
   unit as a sub-line. Changing `businessUnitId` does not clear the value — the form
   decides whether a process outside the new unit is still acceptable. */

import { useCallback, useEffect, useState } from "react";
import AsyncSelect, { type Option } from "@/components/AsyncSelect";
import { LegacyHint } from "@/components/LookupSelect";
import { pickProcesses, type ProcessPick } from "@/lib/masterData";

export type ProcessSelectProps = {
  /** Selected process id, or null. */
  value: string | null;
  /** Called with the new id (null when cleared) and the picked process. */
  onChange: (id: string | null, ref?: ProcessPick | null) => void;
  /** Only offer processes of this business unit. */
  businessUnitId?: string | null;
  placeholder?: string;
  /** The record's old free-text process; hinted while `value` is null. */
  legacyText?: string | null;
  disabled?: boolean;
};

const labelCache = new Map<string, Promise<ProcessPick | null>>();

function processById(id: string): Promise<ProcessPick | null> {
  let p = labelCache.get(id);
  if (!p) {
    p = pickProcesses({ ids: [id] })
      .then((rows) => rows[0] ?? null)
      .catch(() => {
        labelCache.delete(id);
        return null;
      });
    labelCache.set(id, p);
  }
  return p;
}

/** Process picker. See the file header for behaviour. */
export default function ProcessSelect({
  value,
  onChange,
  businessUnitId,
  placeholder = "Choose a process…",
  legacyText,
  disabled,
}: ProcessSelectProps) {
  const [current, setCurrent] = useState<ProcessPick | null>(null);
  const [known, setKnown] = useState<Record<string, ProcessPick>>({});

  useEffect(() => {
    let live = true;
    if (!value) {
      setCurrent(null);
      return;
    }
    if (current?.id === value) return;
    if (known[value]) {
      setCurrent(known[value]);
      return;
    }
    processById(value).then((p) => live && setCurrent(p ?? { id: value, name: "Unknown or archived process", business_unit_id: null, business_unit_name: "" }));
    return () => {
      live = false;
    };
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  const search = useCallback(
    async (q: string): Promise<Option[]> => {
      const rows = await pickProcesses({ businessUnitId, search: q });
      setKnown((k) => ({ ...k, ...Object.fromEntries(rows.map((r) => [r.id, r])) }));
      return rows.map((r) => ({ value: r.id, label: r.name, sub: r.business_unit_name || undefined }));
    },
    [businessUnitId],
  );

  return (
    <div>
      <AsyncSelect
        search={search}
        value={value}
        selectedLabel={!value ? undefined : current?.id === value ? current.name : "Loading…"}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(id) => {
          const ref = id ? known[id] ?? null : null;
          setCurrent(ref);
          onChange(id, ref);
        }}
      />
      <LegacyHint value={value} legacyText={legacyText} />
    </div>
  );
}
