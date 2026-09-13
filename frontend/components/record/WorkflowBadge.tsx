import { Badge } from "@/components/badges";
import { WORKFLOW_STATE_LABEL, type WorkflowStateKey } from "@/lib/records";

const TONE: Record<string, "neutral" | "info" | "low" | "medium"> = {
  draft: "neutral",
  in_review: "info",
  approved: "low",
  retired: "medium",
};

/** Read-only approval state ("Draft", "In review", …) for a record's `workflow_status`.
 *  `asIs` keeps the label's sentence case; `hollowDraft` draws Draft as a hollow badge
 *  (dossier pages: a draft is the absence of a sign-off, not a status).
 *  Also exported from components/RecordApproval for existing imports. */
export function WorkflowBadge({
  state,
  asIs,
  hollowDraft,
}: {
  state: string | null | undefined;
  asIs?: boolean;
  hollowDraft?: boolean;
}) {
  const key = (state || "draft") as WorkflowStateKey;
  return (
    <Badge tone={TONE[key] ?? "neutral"} asIs={asIs} hollow={hollowDraft && key === "draft"}>
      {WORKFLOW_STATE_LABEL[key] ?? key}
    </Badge>
  );
}

export default WorkflowBadge;
