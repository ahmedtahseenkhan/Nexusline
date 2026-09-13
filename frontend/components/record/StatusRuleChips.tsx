"use client";

/* Status-rule verdicts for one record (record-page-spec §3.3.13) — the same chips the
   list shows, so a record flagged "Control audit failed" says so on its own page.

     <StatusRuleChips model="risk" entityId={r.id} />

   Uses `verdicts` when given, else the governance context's `statusRules` (when it was
   evaluated for this model and record), else fetches GET /status-rules/evaluate/{model}/{id}.
   Each verdict is a `.dyn-status` chip in the rule's own colour; with B9 the condition
   follows in muted text ("inherent score ≥ 15"). Renders null when nothing fires — the
   header then omits its "Status rules" meta item (it reads `useStatusRuleVerdicts`). */

import { Fragment, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { opLabel } from "@/lib/record/text";
import { useRecordGovernance } from "@/components/record/RecordGovernance";
import type { StatusRuleVerdict } from "@/components/record/types";

export type { StatusRuleVerdict };

type StatusRuleChipsProps = { model: string; entityId: string; verdicts?: StatusRuleVerdict[] };

/** The verdicts for one record: `verdicts` → governance context → fetch. */
export function useStatusRuleVerdicts(model: string, entityId: string | null, verdicts?: StatusRuleVerdict[]): StatusRuleVerdict[] {
  const gov = useRecordGovernance(undefined, entityId);
  const fromGov = gov && gov.statusRulesModel === model ? gov.statusRules : null;
  const needFetch = !verdicts && !fromGov && !!entityId;
  const [fetched, setFetched] = useState<StatusRuleVerdict[]>([]);

  useEffect(() => {
    if (!needFetch || !entityId) return;
    let live = true;
    setFetched([]);
    apiCall<StatusRuleVerdict[]>("GET", `/status-rules/evaluate/${model}/${entityId}`)
      .then((v) => live && setFetched(Array.isArray(v) ? v : []))
      .catch(() => live && setFetched([]));
    return () => {
      live = false;
    };
  }, [needFetch, model, entityId]);

  return verdicts ?? fromGov ?? fetched;
}

/** "inherent score ≥ 15" (B9 fields), or "" when the backend sent none. */
export function ruleCondition(v: StatusRuleVerdict): string {
  if (!v.field || !v.operator) return "";
  const value = v.value ?? "";
  return `${v.field.replace(/_/g, " ")} ${opLabel(v.operator)}${value !== "" ? ` ${value}` : ""}`;
}

export default function StatusRuleChips({ model, entityId, verdicts }: StatusRuleChipsProps) {
  const list = useStatusRuleVerdicts(model, entityId, verdicts);
  if (list.length === 0) return null;
  return (
    <span className="rec-rules">
      {list.map((v, i) => {
        const cond = ruleCondition(v);
        return (
          <Fragment key={`${v.label}-${i}`}>
            <span className="dyn-status" style={{ color: v.color || "var(--muted)" }}>{v.label}</span>
            {cond && <span className="rec-rule-cond">{cond}</span>}
          </Fragment>
        );
      })}
    </span>
  );
}

export { StatusRuleChips };
