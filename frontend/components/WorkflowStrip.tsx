"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { toast } from "@/lib/feedback";

/* Where a record has got to in its approval route, on the record itself.

   Renders nothing at all when the record type has no enabled route — which is the
   platform's default — so adding this to a page cannot change how that page looks for
   an organisation that has not configured a workflow. */

type Step = {
  id: string;
  order_index: number;
  name: string;
  approver_label: string;
  status: string;
  due_date: string | null;
  decided_at: string | null;
  decision_comment: string;
};

type Instance = {
  id: string;
  entity_type: string;
  entity_id: string;
  entity_label: string;
  status: string;
  started_by_email: string;
  total_stages: number;
  completed_stages: number;
  steps: Step[];
};

const STEP_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  in_progress: "info",
  pending: "neutral",
  rejected: "critical",
  skipped: "neutral",
};

const STATUS_TONE: Record<string, "low" | "medium" | "critical" | "info" | "neutral"> = {
  in_progress: "info",
  approved: "low",
  rejected: "critical",
  cancelled: "neutral",
};

type Props = {
  entityType: string;
  entityId: string;
  entityLabel?: string;
  link?: string;
  ownerEmail?: string;
  /** Called after the route starts or is cancelled, so the parent can reload. */
  onChange?: () => void;
};

export default function WorkflowStrip({
  entityType,
  entityId,
  entityLabel = "",
  link = "",
  ownerEmail = "",
  onChange,
}: Props) {
  const [instance, setInstance] = useState<Instance | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [routable, setRoutable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiCall<Instance | null>(
      "GET",
      `/workflows/instance?entity_type=${encodeURIComponent(entityType)}&entity_id=${entityId}`,
    )
      .then((data) => {
        setInstance(data);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
    // Whether a route exists at all decides if the "Start" button is worth showing.
    apiCall<{ items: { enabled: boolean }[] }>(
      "GET",
      `/workflows/definitions?entity_type=${encodeURIComponent(entityType)}`,
    )
      .then((page) => setRoutable(page.items.some((d) => d.enabled)))
      .catch(() => setRoutable(false));
  }, [entityType, entityId]);

  useEffect(load, [load]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const result = await apiCall<{ started: boolean; reason: string }>("POST", "/workflows/start", {
        entity_type: entityType,
        entity_id: entityId,
        entity_label: entityLabel,
        link,
        record_owner_email: ownerEmail,
      });
      if (!result.started) {
        setError(result.reason || "No approval route is enabled for this record type");
      } else {
        toast("Sent for approval — stage 1 is in the approvals inbox");
        load();
        onChange?.();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the route");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!instance) return;
    setBusy(true);
    setError(null);
    try {
      await apiCall("POST", `/workflows/instances/${instance.id}/cancel`, {});
      toast("Approval route cancelled");
      load();
      onChange?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel the route");
    } finally {
      setBusy(false);
    }
  }

  // Nothing configured and nothing running: stay completely out of the way.
  if (!loaded || (!instance && !routable)) return null;

  if (!instance) {
    return (
      <div style={{ padding: "10px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>Approval route</strong>
        <span className="muted" style={{ fontSize: 12.5 }}>
          This record type has a multi-stage route configured.
        </span>
        <button className="btn sm" type="button" onClick={start} disabled={busy} style={{ marginLeft: "auto" }}>
          {busy ? "Starting…" : "Send for approval"}
        </button>
        {error && <div className="error" style={{ width: "100%", margin: 0, fontSize: 12.5 }}>{error}</div>}
      </div>
    );
  }

  const current = instance.steps.find((s) => s.status === "in_progress");

  return (
    <div style={{ padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: 13 }}>Approval route</strong>
        <Badge tone={STATUS_TONE[instance.status] ?? "neutral"}>
          {instance.status.replace("_", " ")}
        </Badge>
        <span className="muted" style={{ fontSize: 12.5 }}>
          stage {Math.min(instance.completed_stages + 1, instance.total_stages)} of {instance.total_stages}
          {current?.due_date && ` · due ${current.due_date}`}
        </span>
        {instance.status === "in_progress" && (
          <button className="btn secondary sm" type="button" onClick={cancel} disabled={busy} style={{ marginLeft: "auto" }}>
            Cancel route
          </button>
        )}
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 12, flexWrap: "wrap" }}>
        {instance.steps.map((step) => (
          <div
            key={step.id}
            title={
              `${step.name}\n${step.approver_label || "approver not resolved"}` +
              (step.decided_at ? `\nDecided ${step.decided_at.slice(0, 10)}` : "") +
              (step.decision_comment ? `\n"${step.decision_comment}"` : "")
            }
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "5px 10px", borderRadius: "var(--radius-sm)", fontSize: 12.5,
              border: "1px solid var(--border)",
              background: step.status === "in_progress" ? "var(--primary-weak-2)" : "transparent",
              opacity: step.status === "skipped" ? 0.5 : 1,
            }}
          >
            <span aria-hidden>
              {step.status === "approved" ? "✓" : step.status === "rejected" ? "✕" : step.order_index}
            </span>
            <span style={{ fontWeight: step.status === "in_progress" ? 600 : 500 }}>{step.name}</span>
            <Badge tone={STEP_TONE[step.status] ?? "neutral"}>{step.status.replace("_", " ")}</Badge>
          </div>
        ))}
      </div>

      {current && (
        <div className="muted" style={{ fontSize: 12, marginTop: 10 }}>
          Waiting on <b>{current.approver_label || "an approver"}</b> — the decision is made from
          the Approvals inbox, where segregation of duties applies.
        </div>
      )}

      {error && <div className="error" style={{ marginTop: 10, fontSize: 12.5 }}>{error}</div>}
    </div>
  );
}
