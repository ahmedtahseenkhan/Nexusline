"use client";

/* The cross-cutting record rail, mounted in RecordDrawer's `aside` by every register
   that has a record view.

     <RecordPanels model="exception" entityId={detail.id} />            // classic (default)

     <RecordPanels model="risk" entityId={r.id} layout="dossier"        // dossier pages
       signOff={{ onChanged: refresh }} trail={{ reference: r.reference }} />

   Classic (today's order, quiet defaults — record-page-spec §3.5, Phase 0): status-rule
   chips, custom fields (read card, Edit to change), review & attestation (form in a
   dialog), the activity trail and collaboration (inputs on demand). It never renders
   approval — pages that need it mount RecordApproval above it.

   Dossier: the "Sign-off & trail" rail — SignOffCard (approval, route, attestation,
   review, extra rows), RecordTrail (the audit log, filterable) and "Discussion & files".
   Status rules move to the header and custom fields to the page's Details section.
   Pages that adopt it must delete their own RecordApproval / WorkflowFields block, so
   approval is never shown twice. */

import CustomFieldsPanel from "@/components/CustomFieldsPanel";
import AttestationPanel from "@/components/AttestationPanel";
import CollabPanel from "@/components/CollabPanel";
import ActivityPanel from "@/components/ActivityPanel";
import SignOffCard, { type SignOffCardProps } from "@/components/record/SignOffCard";
import RecordTrail from "@/components/record/RecordTrail";
import StatusRuleChips, { useStatusRuleVerdicts } from "@/components/record/StatusRuleChips";
import { GovernanceScope } from "@/components/record/RecordGovernance";

type Props = {
  model: string;
  entityId: string;
  /** "classic" (default) or "dossier". */
  layout?: "classic" | "dossier";
  /** Dossier: the Sign-off card's options. */
  signOff?: Omit<SignOffCardProps, "entityType" | "entityId">;
  /** Dossier: the Trail card's options. */
  trail?: { reference?: string | null; related?: { entityType: string; entityId: string; label: string }[] };
  /** Classic: hide the status-rule chips (the page shows them itself). */
  hideStatusRules?: boolean;
};

export default function RecordPanels({ model, entityId, layout = "classic", signOff, trail, hideStatusRules = false }: Props) {
  if (layout === "dossier") {
    return (
      <GovernanceScope entityType={model} entityId={entityId}>
        <SignOffCard entityType={model} entityId={entityId} {...signOff} />
        <RecordTrail entityType={model} entityId={entityId} reference={trail?.reference} related={trail?.related} />
        <CollabPanel entityType={model} entityId={entityId} title="Discussion & files" frame="rail" />
      </GovernanceScope>
    );
  }
  return (
    <>
      {!hideStatusRules && <StatusRulesRow model={model} entityId={entityId} />}
      <CustomFieldsPanel model={model} entityId={entityId} />
      <AttestationPanel entityType={model} entityId={entityId} />
      <ActivityPanel entityType={model} entityId={entityId} defaultOpen />
      <CollabPanel entityType={model} entityId={entityId} />
    </>
  );
}

/** The status-rules verdicts for one record — the same chips the list shows, so a
 *  record opened from a row flagged "Control audit failed" says so on its own page. */
function StatusRulesRow({ model, entityId }: { model: string; entityId: string }) {
  const verdicts = useStatusRuleVerdicts(model, entityId);
  if (verdicts.length === 0) return null;
  return (
    <div className="rec-rules-row">
      <span className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Status rules</span>
      <StatusRuleChips model={model} entityId={entityId} verdicts={verdicts} />
    </div>
  );
}
