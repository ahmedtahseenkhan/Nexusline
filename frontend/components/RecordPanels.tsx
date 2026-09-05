"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import CustomFieldsPanel from "@/components/CustomFieldsPanel";
import AttestationPanel from "@/components/AttestationPanel";
import CollabPanel from "@/components/CollabPanel";
import ActivityPanel from "@/components/ActivityPanel";

/** The full cross-cutting record surface: what the status rules say about this record,
 * custom fields, review/attestation, collaboration (comments/tags/attachments), and the
 * record's own activity trail. Drop onto any record detail panel — 36 of them do. */
export default function RecordPanels({ model, entityId }: { model: string; entityId: string }) {
  return (
    <>
      <DynamicStatus model={model} entityId={entityId} />
      <CustomFieldsPanel model={model} entityId={entityId} />
      <AttestationPanel entityType={model} entityId={entityId} />
      <CollabPanel entityType={model} entityId={entityId} />
      <ActivityPanel entityType={model} entityId={entityId} />
    </>
  );
}

type StatusLabel = { label: string; color: string };

/** The status-rules verdicts for one record — the same chips the list shows, so a
 *  record opened from a row flagged "Control audit failed" says so on its own page. */
function DynamicStatus({ model, entityId }: { model: string; entityId: string }) {
  const [labels, setLabels] = useState<StatusLabel[]>([]);
  useEffect(() => {
    setLabels([]);
    apiCall<StatusLabel[]>("GET", `/status-rules/evaluate/${model}/${entityId}`)
      .then(setLabels)
      .catch(() => setLabels([]));
  }, [model, entityId]);
  if (labels.length === 0) return null;
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 14 }}>
      <span className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Status rules</span>
      {labels.map((l) => (
        <span key={l.label} className="dyn-status" style={{ color: l.color || "var(--muted)" }}>{l.label}</span>
      ))}
    </div>
  );
}
