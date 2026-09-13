"use client";

/* "A description appears once" (record-page-spec v1.1 decision 2).

   The record's description is shown once: as the lead under the title. No section
   repeats it. RecordHeader publishes the lead it shows; FactList and Fact in the dossier
   main column drop any fact whose text is the lead (with a dev warning), so a page that
   also lists "Description" in a section does not print it twice.

     const lead = useRecordLead();              // the open record's lead text, or null
     repeatsLead("Malware encrypts …", lead)    // true when a value would repeat it

   One dossier is open at a time (the drawer is modal), so a single module-level value is
   enough; RecordHeader clears it when it unmounts. */

import { useSyncExternalStore } from "react";

let current: string | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

/** Set the lead the open record shows. Returns a cleanup that clears it (if unchanged). */
export function publishRecordLead(text: string | null | undefined): () => void {
  const value = text && text.trim() ? text : null;
  if (value !== current) {
    current = value;
    emit();
  }
  return () => {
    if (current === value) {
      current = null;
      emit();
    }
  };
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

/** The open dossier's lead text (null when there is none or no dossier is open). */
export function useRecordLead(): string | null {
  return useSyncExternalStore(subscribe, () => current, () => null);
}

/** Plain, comparable text: tags stripped, entities for spaces decoded, whitespace
 *  collapsed, case folded. */
export function leadKey(v: string): string {
  return v
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

/** True when `value` is plain text that says exactly what the lead says. */
export function repeatsLead(value: unknown, lead: string | null | undefined): boolean {
  if (!lead || typeof value !== "string") return false;
  const k = leadKey(value);
  return k !== "" && k === leadKey(lead);
}
