"use client";

/* Pick one business unit from the organisation's tree.

     <Field label="Business unit">
       <BusinessUnitSelect
         value={form.business_unit_id}
         onChange={(id) => set("business_unit_id", id)}
         legacyText={record.business_unit}   // old free text, hinted until a unit is picked
       />
     </Field>

   The tree (`GET /pickers/business-units`) is loaded once per page and searched in the
   browser. With no search text, units are listed depth-first and indented by depth;
   children show their parent path ("Retail › Branch Ops") as a sub-line. Searching
   matches the whole path, so typing a parent also lists what sits under it.
   `exclude` hides one unit and everything under it — use it for a unit's own "parent"
   field so nobody can make a unit its own ancestor. */

import { useCallback, useEffect, useState } from "react";
import AsyncSelect, { type Option } from "@/components/AsyncSelect";
import { LegacyHint } from "@/components/LookupSelect";
import { cachedBusinessUnits, type UnitPick, type UnitRef } from "@/lib/masterData";

export type BusinessUnitSelectProps = {
  /** Selected business-unit id, or null. */
  value: string | null;
  /** Called with the new id (null when cleared) and the picked unit (with depth/path). */
  onChange: (id: string | null, ref?: UnitPick | null) => void;
  placeholder?: string;
  /** The record's old free-text unit; hinted while `value` is null. */
  legacyText?: string | null;
  disabled?: boolean;
  /** Hide this unit and its descendants (for a unit's own parent field). */
  exclude?: string | null;
};

/** Non-breaking, so the indent survives HTML whitespace collapsing. */
const INDENT = "\u00A0\u00A0\u00A0\u00A0";

/** Units under (and including) `rootId` in a depth-first flattened tree. */
export function descendantsOf(units: UnitPick[], rootId: string): Set<string> {
  const out = new Set<string>([rootId]);
  for (const u of units) if (u.parent_id && out.has(u.parent_id)) out.add(u.id);
  return out;
}

function parentPath(u: UnitPick): string | undefined {
  const cut = u.path.lastIndexOf(" › ");
  return cut > 0 ? u.path.slice(0, cut) : undefined;
}

/** Business-unit picker. See the file header for behaviour. */
export default function BusinessUnitSelect({
  value,
  onChange,
  placeholder = "Choose a business unit…",
  legacyText,
  disabled,
  exclude,
}: BusinessUnitSelectProps) {
  const [units, setUnits] = useState<UnitPick[] | null>(null);

  useEffect(() => {
    let live = true;
    cachedBusinessUnits()
      .then((u) => live && setUnits(u))
      .catch(() => live && setUnits([]));
    return () => {
      live = false;
    };
  }, []);

  const search = useCallback(
    async (q: string): Promise<Option[]> => {
      const all = await cachedBusinessUnits();
      const hidden = exclude ? descendantsOf(all, exclude) : new Set<string>();
      const needle = q.trim().toLowerCase();
      return all
        .filter((u) => !hidden.has(u.id) && (!needle || u.path.toLowerCase().includes(needle)))
        .slice(0, 200)
        .map((u) => ({
          value: u.id,
          label: needle ? u.name : `${INDENT.repeat(u.depth)}${u.name}`,
          sub: parentPath(u),
        }));
    },
    [exclude],
  );

  const current = value && units ? units.find((u) => u.id === value) : undefined;
  const selectedLabel = !value ? undefined : current ? current.path : units ? "Unknown or archived unit" : "Loading…";

  return (
    <div>
      <AsyncSelect
        search={search}
        value={value}
        selectedLabel={selectedLabel}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(id) => onChange(id, id ? units?.find((u) => u.id === id) ?? null : null)}
      />
      <LegacyHint value={value} legacyText={legacyText} />
    </div>
  );
}

/** A unit's name for tables: the name, else `fallback` (legacy text) or "—". */
export function UnitName({ unit, fallback }: { unit?: UnitRef | null; fallback?: string | null }) {
  if (!unit) return <span className={fallback ? undefined : "muted"}>{fallback || "—"}</span>;
  return <span>{unit.name || "—"}</span>;
}
