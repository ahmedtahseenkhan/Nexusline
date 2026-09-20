"use client";

/* Facts and the not-set sentence (record-page-spec §3.3.7).

     <FactList
       items={[
         { label: "Category", value: categoryText(r), tab: "general" },
         { label: "Key control", value: c.is_key ? "Yes" : "No" },       // booleans as text: "No" is SET
         { label: "Test procedure", value: c.test_procedure, wide: true, tab: "attributes" },
         ...cf.facts,                                                    // useCustomFieldFacts
       ]}
       onFillIn={(tab) => (tab === "custom" ? cf.setEditing(true) : openEdit(detail, tab))}
     />

   Renders `<dl class="rec-facts">` with the SET items only; every unset item (null,
   undefined, "", whitespace or []) folds into one line: "3 not set: Type, Velocity and
   Source · Fill in" (up to 7 names, then "and k more"; custom fields get
   "(custom field)"). "Fill in" calls `onFillIn` with the first unset item's `tab`.
   When nothing is set: "{allUnsetText}: … · Fill in".

   `Fact` is the drop-in replacement for page-local Fact / kv() / field() helpers:
     <FactGrid><Fact label="Root cause" wide>{text}</Fact>…</FactGrid>
   A Fact outside FactGrid / FactList renders its own one-item list, so the HTML stays valid.

   v1.1 (a description appears once): in the dossier main column, a fact whose text is
   the lead under the title is not shown again — FactList drops it (it is not "not set"
   either: the lead shows it) and a `Fact` with that text renders nothing. A dev warning
   names the dropped label. */

import { createContext, useContext, type ReactNode } from "react";
import { repeatsLead, useRecordLead } from "@/components/record/lead";
import { useRecordSurface } from "@/components/record/RecordSurface";
import type { FactItem } from "@/components/record/types";

export type { FactItem };

type FactListProps = {
  items: FactItem[];
  /** Called with the first unset item's tab. */
  onFillIn?: (tab?: string) => void;
  /** Default "Fill in". */
  fillLabel?: string;
  /** Default "Nothing recorded yet". */
  allUnsetText?: string;
};

const MAX_NAMES = 7;

/** null, undefined, "" (or whitespace-only) and [] count as not set. */
export function isUnsetValue(v: unknown): boolean {
  if (v === null || v === undefined || v === false) return true;
  if (typeof v === "string") return v.trim() === "";
  if (Array.isArray(v)) return v.length === 0;
  return false;
}

const InFactList = createContext(false);

const warnedLead = new Set<string>();
function warnRepeat(label: string) {
  if (process.env.NODE_ENV === "production" || warnedLead.has(label)) return;
  warnedLead.add(label);
  console.warn(`FactList: "${label.trim()}" repeats the lead under the title, so it is not shown again (v1.1: a description appears once).`);
}

/** The lead to compare against: only in a dossier's main column. */
function useLeadInMain(): string | null {
  const lead = useRecordLead();
  return useRecordSurface() === "main" ? lead : null;
}

export function Fact({ label, children, wide, hint }: { label: string; children: ReactNode; wide?: boolean; hint?: string }) {
  const inList = useContext(InFactList);
  const lead = useLeadInMain();
  if (repeatsLead(children, lead)) {
    warnRepeat(label);
    return null;
  }
  const item = (
    <div className={wide ? "wide" : undefined}>
      <dt title={hint}>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
  if (inList) return item;
  return <dl className="rec-facts rec-fact-solo">{item}</dl>;
}

/** A `dl.rec-facts` grid for hand-written `<Fact>` children. */
export function FactGrid({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <InFactList.Provider value={true}>
      <dl className={`rec-facts${className ? ` ${className}` : ""}`}>{children}</dl>
    </InFactList.Provider>
  );
}

function NameList({ items }: { items: FactItem[] }) {
  const shown = items.slice(0, MAX_NAMES);
  const more = items.length - shown.length;
  const parts = shown.map((f, i) => (
    <span key={f.key ?? `${f.label}-${i}`}>
      <b>{f.label.trim()}</b>
      {f.origin === "custom" ? " (custom field)" : ""}
    </span>
  ));
  const out: ReactNode[] = [];
  parts.forEach((p, i) => {
    if (i > 0) {
      const last = i === parts.length - 1 && more === 0;
      out.push(last ? " and " : ", ");
    }
    out.push(p);
  });
  if (more > 0) out.push(` and ${more} more`);
  return <>{out}</>;
}

export default function FactList({ items: all, onFillIn, fillLabel = "Fill in", allUnsetText = "Nothing recorded yet" }: FactListProps) {
  const lead = useLeadInMain();
  const items = all.filter((f) => {
    if (!repeatsLead(f.value, lead)) return true;
    warnRepeat(f.label);
    return false;
  });
  const set = items.filter((f) => !isUnsetValue(f.value));
  const unset = items.filter((f) => isUnsetValue(f.value));
  const names = unset.map((f) => f.label.trim());

  return (
    <>
      {set.length > 0 && (
        <InFactList.Provider value={true}>
          <dl className="rec-facts">
            {set.map((f, i) => (
              <div key={f.key ?? `${f.label}-${i}`} className={f.wide ? "wide" : undefined}>
                <dt title={f.hint}>{f.label.trim()}</dt>
                <dd>{f.value as ReactNode}</dd>
              </div>
            ))}
          </dl>
        </InFactList.Provider>
      )}
      {unset.length > 0 && (
        <p className={`rec-notset${set.length === 0 ? " is-all" : ""}`}>
          {set.length === 0 ? `${allUnsetText}: ` : `${unset.length} not set: `}
          <NameList items={unset} />
          {onFillIn && (
            <>
              {" · "}
              <button
                type="button"
                className="rec-link"
                aria-label={`${fillLabel}: ${names.join(", ")}`}
                onClick={() => onFillIn(unset.find((f) => f.tab)?.tab ?? unset[0]?.tab)}
              >
                {fillLabel}
              </button>
            </>
          )}
        </p>
      )}
    </>
  );
}

export { FactList };
