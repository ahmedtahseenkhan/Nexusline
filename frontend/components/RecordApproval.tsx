"use client";

/* The "Approval" card a record drawer shows in its aside, above RecordPanels:

     aside={detail ? (
       <>
         <RecordApproval entityType="exception" entityId={detail.id} onChanged={refresh} />
         <RecordPanels model="exception" entityId={detail.id} />
       </>
     ) : null}

   A thin frame around WorkflowFields so every register lays the lifecycle out the same
   way. `WorkflowBadge` is the read-only state for record types the lifecycle endpoints
   do not cover (not in the backend entity registry): it shows where the record is, but
   the state cannot be moved from the page. */

import { Badge } from "@/components/badges";
import WorkflowFields from "@/components/WorkflowFields";
import { WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";

type Props = {
  /** Entity registry key (backend/app/services/entity_types.py). */
  entityType: string;
  entityId: string | null;
  onChanged?: (state: WorkflowStateKey) => void;
};

export default function RecordApproval({ entityType, entityId, onChanged }: Props) {
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-head">
        <h3>Approval</h3>
      </div>
      <div className="card-pad">
        <WorkflowFields entityType={entityType} entityId={entityId} onChanged={onChanged} />
      </div>
    </div>
  );
}

const TONE: Record<string, "neutral" | "info" | "low" | "medium"> = {
  draft: "neutral",
  in_review: "info",
  approved: "low",
  retired: "medium",
};

/** Read-only approval state ("Draft", "In review", …) for a record's `workflow_status`. */
export function WorkflowBadge({ state }: { state: string | null | undefined }) {
  const key = (state || "draft") as WorkflowStateKey;
  return <Badge tone={TONE[key] ?? "neutral"}>{WORKFLOW_STATE_LABEL[key] ?? key}</Badge>;
}
