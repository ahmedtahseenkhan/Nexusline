"use client";

/* The header's single filled button (record-page-spec §3.3.12).

     <PrimaryAction
       candidates={[
         { kind: "workflow", action: "approve" },
         { kind: "workflow", action: "submit" },
         { kind: "custom", label: "Mark reviewed", when: r.needs_review && canWrite, onClick: markReviewed },
         { kind: "attest" },
       ]}
       onChanged={refresh}
     />

   Renders the FIRST eligible candidate as `<button id="rec-primary" class="btn sm
   rec-primary">`, or nothing — a disabled primary is never shown. Eligibility comes from
   the server via the governance context (RecordDrawer `governance` prop):
   - workflow: `gov.workflow.allowed_actions` includes the action → runs it through
     `runWorkflowAction` (same confirms and toasts as WorkflowFields), then
     `gov.reload()`, then `onChanged`;
   - attest: `gov.attestation.can_attest === true` and status ≠ current → opens the
     attestation dialog (`gov.openAttest()`);
   - custom: `when` is true → `onClick` (a returned promise shows "Working…").
   It is the only `.btn` without `.secondary` on a dossier page. */

import { useState } from "react";
import { toast } from "@/lib/feedback";
import { WORKFLOW_ACTION_LABEL } from "@/lib/records";
import { runWorkflowAction, workflowErrorMessage } from "@/lib/workflowActions";
import { useRecordGovernance, type RecordGovernance } from "@/components/record/RecordGovernance";
import type { PrimaryCandidate } from "@/components/record/types";

export type { PrimaryCandidate };

type PrimaryActionProps = { candidates: PrimaryCandidate[]; onChanged?: () => void };

/** The first candidate the server (or the page) allows now, or null. */
export function pickPrimary(candidates: PrimaryCandidate[], gov: RecordGovernance | null): PrimaryCandidate | null {
  for (const c of candidates) {
    if (c.kind === "workflow") {
      if (gov?.workflow?.allowed_actions.includes(c.action)) return c;
    } else if (c.kind === "attest") {
      if (gov?.attestation?.can_attest === true && gov.attestation.status !== "current") return c;
    } else if (c.when) {
      return c;
    }
  }
  return null;
}

/** The label the primary button would show ("Submit for review", "Attest…", …). */
export function primaryLabel(c: PrimaryCandidate): string {
  if (c.kind === "workflow") return WORKFLOW_ACTION_LABEL[c.action];
  if (c.kind === "attest") return "Attest…";
  return c.label;
}

export default function PrimaryAction({ candidates, onChanged }: PrimaryActionProps) {
  const gov = useRecordGovernance();
  const [busy, setBusy] = useState(false);
  const c = pickPrimary(candidates, gov);
  if (!c) return null;

  async function run() {
    if (!c || busy) return;
    if (c.kind === "attest") {
      gov?.openAttest();
      return;
    }
    if (c.kind === "custom") {
      const r: unknown = c.onClick();
      if (r instanceof Promise) {
        setBusy(true);
        try {
          await r;
        } finally {
          setBusy(false);
        }
      }
      return;
    }
    if (!gov?.entityId) return;
    setBusy(true);
    try {
      const res = await runWorkflowAction(gov.entityType, gov.entityId, c.action);
      if (res === null) return;
      await gov.reload();
      onChanged?.();
    } catch (e) {
      toast(workflowErrorMessage(e), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button id="rec-primary" type="button" className="btn sm rec-primary" onClick={run} disabled={busy} aria-busy={busy || undefined}>
      {busy ? "Working…" : primaryLabel(c)}
    </button>
  );
}

export { PrimaryAction };
