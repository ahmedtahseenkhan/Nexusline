"use client";

import CustomFieldsPanel from "@/components/CustomFieldsPanel";
import AttestationPanel from "@/components/AttestationPanel";
import CollabPanel from "@/components/CollabPanel";

/** The full cross-cutting record surface: custom fields, review/attestation, and
 * collaboration (comments/tags/attachments). Drop onto any record detail panel. */
export default function RecordPanels({ model, entityId }: { model: string; entityId: string }) {
  return (
    <>
      <CustomFieldsPanel model={model} entityId={entityId} />
      <AttestationPanel entityType={model} entityId={entityId} />
      <CollabPanel entityType={model} entityId={entityId} />
    </>
  );
}
