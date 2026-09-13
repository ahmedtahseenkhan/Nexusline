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
   the state cannot be moved from the page.

   Layout (record-page-spec §3.5):
   - `compact` — the one-row WorkflowFields with every action available. When omitted it
     is decided by where the card sits: inside a RecordDrawer aside it is compact, in a
     form tab or the main column it is the full layout, as before.
   - `bare` — no card frame (the caller supplies one).
   Dossier pages do not mount this: their Sign-off card (RecordPanels layout="dossier")
   carries approval, so it is never shown twice. */

import WorkflowFields from "@/components/WorkflowFields";
import { useRecordSurface } from "@/components/record/RecordSurface";
import type { WorkflowStateKey } from "@/lib/records";

type Props = {
  /** Entity registry key (backend/app/services/entity_types.py). */
  entityType: string;
  entityId: string | null;
  onChanged?: (state: WorkflowStateKey) => void;
  /** One-row layout; default: compact inside a drawer aside, full elsewhere. */
  compact?: boolean;
  /** Drop the card wrapper. */
  bare?: boolean;
};

export default function RecordApproval({ entityType, entityId, onChanged, compact, bare }: Props) {
  const surface = useRecordSurface();
  const isCompact = compact ?? surface === "aside";
  const body = isCompact ? (
    <WorkflowFields entityType={entityType} entityId={entityId} onChanged={onChanged} variant="compact" omitActions={[]} keyLabel={null} />
  ) : (
    <WorkflowFields entityType={entityType} entityId={entityId} onChanged={onChanged} />
  );
  if (bare) return body;
  if (isCompact) {
    return (
      <div className="card rec-approval-card">
        <div className="card-head">
          <h3>Approval</h3>
        </div>
        <div className="card-pad">{body}</div>
      </div>
    );
  }
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-head">
        <h3>Approval</h3>
      </div>
      <div className="card-pad">{body}</div>
    </div>
  );
}

export { WorkflowBadge } from "@/components/record/WorkflowBadge";
