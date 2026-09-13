"use client";

/* The dossier rail's "Sign-off" card (record-page-spec §3.3.10). Rendered by
   RecordPanels layout="dossier" from its `signOff` prop — pages rarely mount it directly.

     <RecordPanels model="risk" entityId={r.id} layout="dossier"
       signOff={{ route: { label: `${r.reference} — ${r.title}`, link: "/risks", ownerEmail: r.owner_ref?.email ?? "" },
                  onChanged: refresh }}
       trail={{ reference: r.reference }} />

   Rows, top to bottom:
   1. Approval — WorkflowFields variant="compact" (status line, approval owner, the
      actions the header does not own, Reject… in a Disclosure, History (n) → See in trail).
   2. Route strip — WorkflowStrip hideStart, only while an approval route is live (`route`).
   3. Attestation — AttestationPanel variant="row" (the form opens in a dialog).
   4. Review — only when `review` is given and attestation is NOT native (the asset's own
      clock until B4): "Review due {next} ({cadence}) · last {last | never}", or a red
      "Overdue since {next}" badge.
   5. `extraRows` — e.g. the policy "Publication" row (use `.rec-so-row` markup).
   The section is `#rec-signoff` (tabIndex -1) — the target of the "See sign-off" open point. */

import type { ReactNode } from "react";
import { Badge } from "@/components/badges";
import AttestationPanel from "@/components/AttestationPanel";
import WorkflowFields from "@/components/WorkflowFields";
import WorkflowStrip from "@/components/WorkflowStrip";
import { GovernanceScope, useRecordGovernance } from "@/components/record/RecordGovernance";
import { useFormat } from "@/lib/format";
import { cadenceNoun } from "@/lib/record/text";
import type { WorkflowActionKey } from "@/lib/records";

export type SignOffCardProps = {
  entityType: string;
  entityId: string;
  /** Default ["submit", "approve"]: the header primary owns them. */
  omitActions?: WorkflowActionKey[];
  /** Renders <WorkflowStrip hideStart> while a route is live (risk). */
  route?: { label: string; link: string; ownerEmail: string } | null;
  /** The record's own review clock when attestation is NOT native (asset until B4). */
  review?: { frequency: string; last: string | null; next: string | null; overdue: boolean } | null;
  /** e.g. the policy "Publication" row. */
  extraRows?: ReactNode;
  /** Page reload; the card reloads the governance first. */
  onChanged?: () => void;
};

export default function SignOffCard(props: SignOffCardProps) {
  return (
    <GovernanceScope entityType={props.entityType} entityId={props.entityId}>
      <SignOffCardInner {...props} />
    </GovernanceScope>
  );
}

function SignOffCardInner({ entityType, entityId, omitActions = ["submit", "approve"], route, review, extraRows, onChanged }: SignOffCardProps) {
  const { formatDate } = useFormat();
  const gov = useRecordGovernance(entityType, entityId);
  const native = !!gov?.attestation?.native_review;
  const showReview = !!review && !native;

  async function routeChanged() {
    await gov?.reload();
    onChanged?.();
  }

  return (
    <section id="rec-signoff" tabIndex={-1} className="rec-rail-card" aria-labelledby="rec-signoff-h">
      <header>
        <h3 id="rec-signoff-h">Sign-off</h3>
      </header>
      <div className="rec-rail-body">
        <WorkflowFields entityType={entityType} entityId={entityId} variant="compact" omitActions={omitActions} onChanged={() => onChanged?.()} />
        {route && (
          <WorkflowStrip
            entityType={entityType}
            entityId={entityId}
            entityLabel={route.label}
            link={route.link}
            ownerEmail={route.ownerEmail}
            hideStart
            onChange={routeChanged}
          />
        )}
        <AttestationPanel entityType={entityType} entityId={entityId} variant="row" onChanged={() => onChanged?.()} />
        {showReview && review && (
          <div className="rec-so-row rec-review">
            <div className="k">
              Review
              {review.overdue && review.next && <Badge tone="critical" asIs>Overdue since {formatDate(review.next)}</Badge>}
            </div>
            <div className="d">
              {review.next ? (
                <>
                  Review due <b>{formatDate(review.next)}</b> ({cadenceNoun(review.frequency)})
                </>
              ) : (
                "Review not scheduled"
              )}
              {" · "}{review.last ? <>last {formatDate(review.last)}</> : "never reviewed"}
            </div>
          </div>
        )}
        {extraRows}
      </div>
    </section>
  );
}

export { SignOffCard };
