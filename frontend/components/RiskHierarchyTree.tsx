"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge, Severity } from "@/components/badges";

/* The register as a tree: enterprise (L1) → category (L2) → scenario (L3) risks. The board
   reads the top two levels; each node says how many risks sit below it and the worst
   exposure among them (residual when assessed, else inherent — as the dashboard ranks),
   counted at every level even when the tree stops at categories. The figures (worst,
   severity counts, above tolerance) take the board register only — scored, out of Draft,
   not accepted or closed — so they match the dashboard; other risks stay in the tree,
   marked "not in figures". */

export type HierarchyNodeRef = {
  id: string;
  reference: string;
  title: string;
  level: number | null;
  exposure: number | null;
  severity: string | null;
  appetite_status: string | null;
  status: string;
  /** Counted in the figures (on the board register). */
  in_figures?: boolean;
  /** False for a draft nobody has scored. */
  scored?: boolean;
};

export type HierarchyNode = HierarchyNodeRef & {
  children_count: number;
  descendants_count: number;
  worst: HierarchyNodeRef | null;
  by_severity: Record<string, number>;
  breaches: number;
  /** Risks below left out of the figures. */
  not_in_figures?: number;
  children: HierarchyNode[];
};

type Hierarchy = { max_level: number; roots: HierarchyNode[]; unplaced: number; by_level: Record<string, number> };

export const LEVEL_LABEL: Record<number, string> = { 1: "Enterprise", 2: "Category", 3: "Scenario" };

export function LevelBadge({ level }: { level: number | null | undefined }) {
  if (!level) return <span className="muted">Not placed</span>;
  return <Badge tone={level === 1 ? "info" : "neutral"} plain>L{level} · {LEVEL_LABEL[level]}</Badge>;
}

type Props = {
  onOpen: (id: string) => void;
  /** Show the risks not placed yet (the register filtered to level "none"). */
  onShowUnplaced?: () => void;
  refreshKey?: number;
};

export default function RiskHierarchyTree({ onOpen, onShowUnplaced, refreshKey = 0 }: Props) {
  const [maxLevel, setMaxLevel] = useState(3);
  const [data, setData] = useState<Hierarchy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [closed, setClosed] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setError(null);
    apiCall<Hierarchy>("GET", `/risks/hierarchy?max_level=${maxLevel}`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the hierarchy"));
  }, [maxLevel]);
  useEffect(() => { load(); }, [load, refreshKey]);

  const toggle = (id: string) =>
    setClosed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });

  const renderNode = (node: HierarchyNode, depth: number): React.ReactNode => {
    const open = !closed.has(node.id);
    const high = (node.by_severity.critical ?? 0) + (node.by_severity.high ?? 0);
    return (
      <li key={node.id} style={{ listStyle: "none" }}>
        <div
          style={{
            display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", padding: "8px 10px",
            marginLeft: depth * 22, borderBottom: "1px solid var(--border)",
          }}
        >
          <button
            type="button"
            className="linklike"
            style={{ width: 18, textDecoration: "none", visibility: node.children.length ? "visible" : "hidden" }}
            onClick={() => toggle(node.id)}
            aria-label={open ? `Collapse ${node.reference}` : `Expand ${node.reference}`}
            aria-expanded={open}
          >
            {open ? "▾" : "▸"}
          </button>
          <LevelBadge level={node.level} />
          <button type="button" className="linklike" style={{ textDecoration: "none", textAlign: "left" }} onClick={() => onOpen(node.id)}>
            <span className="ref">{node.reference}</span> <span style={{ color: "var(--text-strong)" }}>{node.title}</span>
          </button>
          {node.scored === false
            ? <span className="muted">Not scored</span>
            : <span><Severity value={node.severity} /> <span className="muted">({node.exposure ?? "—"})</span></span>}
          {node.in_figures === false && (
            <span className="muted" style={{ fontSize: 12 }} title="Draft, never scored, accepted or closed: not counted in any figure">
              not in figures
            </span>
          )}
          <span style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", fontSize: 12.5 }}>
            {node.descendants_count > 0 ? (
              <>
                <span className="muted">
                  {node.children_count} directly below · {node.descendants_count} in all
                  {(node.not_in_figures ?? 0) > 0 && <> · {node.not_in_figures} not in figures</>}
                </span>
                {high > 0 && <Badge tone="high">{high} high or critical</Badge>}
                {node.breaches > 0 && <Badge tone="critical">{node.breaches} above tolerance</Badge>}
                {node.worst && (
                  <button
                    type="button"
                    className="linklike"
                    style={{ textDecoration: "none" }}
                    title={`Worst exposure below ${node.reference}`}
                    onClick={() => onOpen(node.worst!.id)}
                  >
                    worst below: <span className="ref">{node.worst.reference}</span> <Severity value={node.worst.severity} />{" "}
                    <span className="muted">({node.worst.exposure ?? "—"})</span>
                  </button>
                )}
              </>
            ) : (
              <span className="muted">nothing below</span>
            )}
          </span>
        </div>
        {open && node.children.length > 0 && <ul style={{ margin: 0, padding: 0 }}>{node.children.map((c) => renderNode(c, depth + 1))}</ul>}
      </li>
    );
  };

  return (
    <div className="card" style={{ padding: 0 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
        <div className="seg" role="tablist" aria-label="Levels shown">
          <button className={maxLevel === 2 ? "on" : ""} onClick={() => setMaxLevel(2)} role="tab" aria-selected={maxLevel === 2}>Board view (L1–L2)</button>
          <button className={maxLevel === 3 ? "on" : ""} onClick={() => setMaxLevel(3)} role="tab" aria-selected={maxLevel === 3}>Full tree (L1–L3)</button>
        </div>
        {data && (
          <span className="muted" style={{ fontSize: 12.5 }}>
            {[1, 2, 3].map((l) => `${data.by_level[String(l)] ?? 0} ${LEVEL_LABEL[l].toLowerCase()}`).join(" · ")}
            {data.unplaced > 0 && (
              <>
                {" · "}
                {onShowUnplaced ? (
                  <button type="button" className="linklike" onClick={onShowUnplaced}>{data.unplaced} not placed</button>
                ) : `${data.unplaced} not placed`}
              </>
            )}
          </span>
        )}
      </div>
      {error && <div className="error" style={{ margin: 14 }}>{error}</div>}
      {data && data.roots.length === 0 && !error && (
        <div className="muted" style={{ padding: 18, fontSize: 13, lineHeight: 1.6 }}>
          No risk is placed in the hierarchy yet. Give a risk a level (1 enterprise, 2 category, 3 scenario) and a
          parent from its form; accepted risk candidates arrive at level 3.
        </div>
      )}
      {data && data.roots.length > 0 && <ul style={{ margin: 0, padding: 0 }}>{data.roots.map((n) => renderNode(n, 0))}</ul>}
    </div>
  );
}
