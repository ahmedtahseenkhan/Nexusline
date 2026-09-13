"use client";

/* Phase 0 related-chip clustering (record-page-spec §3.3.15). RecordDrawer mounts the
   provider around its content; RelatedChips calls the hook. Nothing else uses it.

   Every RelatedChips inside a drawer registers { node, parent, label, empty } before
   paint. Entries are grouped by their parent element. A group of 3 or more is a
   cluster: its empty entries render `hidden`, and the last entry in DOM order also
   renders one sibling sentence — "Not linked to business units, processes or
   policies." (or "No linked records." when the whole cluster is empty). Groups of 1–2
   are left alone (their empty text reads "None"). Outside a provider RelatedChips
   behaves exactly as before. */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useIsoLayoutEffect } from "@/components/record/useIsoLayoutEffect";
import { joinList, sentenceLabel } from "@/lib/record/text";

type Entry = { id: number; node: HTMLElement; label: string; empty: boolean };
type Result = { hidden: boolean; sentence: string | null };

type ClusterApi = {
  set(id: number, entry: Entry | null): void;
  results: Map<number, Result>;
};

const ClusterContext = createContext<ClusterApi | null>(null);

const NONE: Result = { hidden: false, sentence: null };

function order(a: Entry, b: Entry): number {
  if (a.node === b.node) return 0;
  return a.node.compareDocumentPosition(b.node) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

function compute(entries: Map<number, Entry>): Map<number, Result> {
  const groups = new Map<HTMLElement | null, Entry[]>();
  entries.forEach((e) => {
    if (!e.node.isConnected) return;
    const parent = e.node.parentElement;
    const list = groups.get(parent) ?? [];
    list.push(e);
    groups.set(parent, list);
  });
  const out = new Map<number, Result>();
  groups.forEach((list) => {
    if (list.length < 3) return;
    list.sort(order);
    const empties = list.filter((e) => e.empty);
    if (empties.length === 0) return;
    const sentence =
      empties.length === list.length
        ? "No linked records."
        : `Not linked to ${joinList(empties.map((e) => sentenceLabel(e.label)), "or")}.`;
    list.forEach((e, i) => {
      out.set(e.id, { hidden: e.empty, sentence: i === list.length - 1 ? sentence : null });
    });
  });
  return out;
}

function sameResults(a: Map<number, Result>, b: Map<number, Result>): boolean {
  if (a.size !== b.size) return false;
  for (const [k, v] of a) {
    const w = b.get(k);
    if (!w || w.hidden !== v.hidden || w.sentence !== v.sentence) return false;
  }
  return true;
}

export function RelatedClusterProvider({ children }: { children: ReactNode }) {
  const entries = useRef(new Map<number, Entry>());
  const [tick, setTick] = useState(0);
  const [results, setResults] = useState<Map<number, Result>>(() => new Map());

  const set = useCallback((id: number, entry: Entry | null) => {
    if (entry) entries.current.set(id, entry);
    else entries.current.delete(id);
    setTick((t) => t + 1);
  }, []);

  useIsoLayoutEffect(() => {
    const next = compute(entries.current);
    setResults((prev) => (sameResults(prev, next) ? prev : next));
  }, [tick]);

  const api = useMemo<ClusterApi>(() => ({ set, results }), [set, results]);
  return <ClusterContext.Provider value={api}>{children}</ClusterContext.Provider>;
}

let seq = 0;

/** Whether this RelatedChips is inside a drawer's cluster provider. */
export function useInRelatedCluster(): boolean {
  return useContext(ClusterContext) !== null;
}

/** Register a RelatedChips (its root node via `ref`) and read whether to hide it and
 *  whether it carries the cluster's sentence. `enabled` false opts out (collapse="never"). */
export function useRelatedCluster(
  label: string,
  empty: boolean,
  ref: RefObject<HTMLElement>,
  enabled = true,
): { hidden: boolean; sentence: string | null } {
  const ctx = useContext(ClusterContext);
  const idRef = useRef(0);
  if (idRef.current === 0) idRef.current = ++seq;
  const id = idRef.current;
  const set = ctx?.set;

  useIsoLayoutEffect(() => {
    if (!set || !enabled || !ref.current) return;
    set(id, { id, node: ref.current, label, empty });
  }, [set, enabled, id, label, empty, ref]);

  useEffect(() => {
    if (!set) return;
    return () => set(id, null);
  }, [set, id]);

  useIsoLayoutEffect(() => {
    if (set && !enabled) set(id, null);
  }, [set, enabled, id]);

  if (!ctx || !enabled) return NONE;
  return ctx.results.get(id) ?? NONE;
}
