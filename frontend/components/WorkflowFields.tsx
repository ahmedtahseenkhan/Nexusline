"use client";

/* A record's approval lifecycle, on the record: state badge, approval owner, the steps
   this user may take now, and who moved it when and why.

     <WorkflowFields entityType="risk" entityId={record?.id ?? null} onChanged={reload} />

   Replaces the per-page `workflow_status` dropdowns: the state moves only through
   Submit for review → Approve / Reject (with a reason) → Revise / Retire, via
   POST /records/{entityType}/{id}/workflow/{action}. The server decides which buttons
   appear (permission, four-eyes, a live approval route) and enforces the same rules
   again when one is pressed. For a record not saved yet (`entityId` null) it shows
   "Draft — save first" and nothing else. */

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/badges";
import UserPicker from "@/components/UserPicker";
import { confirmDialog, toast } from "@/lib/feedback";
import { formatDateTime } from "@/lib/format";
import {
  records,
  WORKFLOW_ACTION_DONE,
  WORKFLOW_ACTION_LABEL,
  WORKFLOW_STATE_LABEL,
  type RecordWorkflow,
  type WorkflowActionKey,
  type WorkflowStateKey,
} from "@/lib/records";

type Props = {
  /** Entity registry key ("risk", "control", "policy", "business_unit"…). */
  entityType: string;
  /** The saved record's id; null while the record is being created. */
  entityId: string | null;
  /** Called with the new state after a transition (or owner change), so the page can reload. */
  onChanged?: (state: WorkflowStateKey) => void;
};

const STATE_TONE: Record<WorkflowStateKey, "neutral" | "info" | "low" | "medium"> = {
  draft: "neutral",
  in_review: "info",
  approved: "low",
  retired: "medium",
};

const HISTORY_PREVIEW = 4;

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

export default function WorkflowFields({ entityType, entityId, onChanged }: Props) {
  const [data, setData] = useState<RecordWorkflow | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<WorkflowActionKey | "owner" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [showAll, setShowAll] = useState(false);

  const load = useCallback(async () => {
    if (!entityId) return;
    try {
      setData(await records.workflow(entityType, entityId));
      setLoadError(null);
    } catch (e) {
      setLoadError(errMsg(e, "Could not load the approval status"));
    }
  }, [entityType, entityId]);

  useEffect(() => {
    setData(null);
    setRejecting(false);
    setReason("");
    setError(null);
    setShowAll(false);
    load();
  }, [load]);

  if (!entityId) {
    return (
      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
        <Badge tone="neutral">Draft</Badge>
        <span className="muted">Draft — save first, then submit it for review.</span>
      </div>
    );
  }
  if (loadError) return <div className="muted" style={{ fontSize: 12.5 }}>{loadError}</div>;
  if (!data) return <div className="muted" style={{ fontSize: 12.5 }}>Loading approval status…</div>;

  const id = entityId;

  async function run(action: WorkflowActionKey, why?: string) {
    if (action === "retire") {
      const ok = await confirmDialog({
        title: "Retire this record?",
        message: "A retired record stays on file but is no longer in force. Retiring is final — a replacement is a new record.",
        confirmLabel: "Retire",
        danger: true,
      });
      if (!ok) return;
    }
    if (action === "revise") {
      const ok = await confirmDialog({
        title: "Reopen for revision?",
        message: "The record returns to draft. Once edited it must be submitted and approved again.",
        confirmLabel: "Revise",
      });
      if (!ok) return;
    }
    setBusy(action);
    setError(null);
    try {
      const res = await records.transition(entityType, id, action, why);
      toast(
        res.routed
          ? "Submitted — the approval route's first stage is in the Approvals inbox"
          : WORKFLOW_ACTION_DONE[action] || "Done",
      );
      setRejecting(false);
      setReason("");
      await load();
      onChanged?.(res.state);
    } catch (e) {
      const msg = errMsg(e, "Could not change the approval status");
      setError(msg);
      toast(msg, "error");
    } finally {
      setBusy(null);
    }
  }

  async function changeOwner(ownerId: string | null) {
    setBusy("owner");
    setError(null);
    try {
      setData(await records.setOwner(entityType, id, ownerId));
      toast(ownerId ? "Approval owner set" : "Approval owner cleared");
      if (data) onChanged?.(data.state);
    } catch (e) {
      const msg = errMsg(e, "Could not change the approval owner");
      setError(msg);
      toast(msg, "error");
    } finally {
      setBusy(null);
    }
  }

  const history = showAll ? data.history : data.history.slice(0, HISTORY_PREVIEW);
  const ownerName = data.owner ? data.owner.full_name || data.owner.email : data.owner_text;

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone={STATE_TONE[data.state] ?? "neutral"}>{WORKFLOW_STATE_LABEL[data.state] ?? data.state}</Badge>
        {data.routing && (
          <span className="muted" style={{ fontSize: 12.5 }}>
            Going through its approval route — each stage is decided in the Approvals inbox.
          </span>
        )}
      </div>

      <div>
        <label className="label">Approval owner</label>
        {data.can_set_owner ? (
          <UserPicker
            value={data.owner?.id ?? null}
            selected={data.owner}
            legacyText={data.owner_text || null}
            onChange={(ownerId) => changeOwner(ownerId)}
            disabled={busy !== null}
            placeholder="Who takes this through approval…"
          />
        ) : (
          <div style={{ fontSize: 13 }}>{ownerName || <span className="muted">Not set</span>}</div>
        )}
      </div>

      {(data.allowed_actions.length > 0 || data.blocked_reason) && (
        <div style={{ display: "grid", gap: 8 }}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {data.allowed_actions.map((action) =>
              action === "reject" ? (
                <button
                  key={action}
                  type="button"
                  className="btn secondary sm"
                  onClick={() => setRejecting((v) => !v)}
                  disabled={busy !== null}
                  aria-expanded={rejecting}
                >
                  Reject…
                </button>
              ) : (
                <button
                  key={action}
                  type="button"
                  className={`btn sm${action === "retire" || action === "revise" ? " secondary" : ""}`}
                  onClick={() => run(action)}
                  disabled={busy !== null}
                >
                  {busy === action ? "Working…" : WORKFLOW_ACTION_LABEL[action]}
                </button>
              ),
            )}
          </div>
          {data.blocked_reason && (
            <div className="muted" style={{ fontSize: 12.5 }}>{data.blocked_reason}</div>
          )}
          {rejecting && (
            <div style={{ display: "grid", gap: 6 }}>
              <label className="label" htmlFor={`wf-reject-${id}`}>Why is it going back to draft?</label>
              <textarea
                id={`wf-reject-${id}`}
                className="input"
                rows={2}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="The reason is recorded in the history and the activity log"
              />
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn danger sm"
                  onClick={() => run("reject", reason)}
                  disabled={busy !== null || !reason.trim()}
                >
                  {busy === "reject" ? "Rejecting…" : "Reject"}
                </button>
                <button type="button" className="btn secondary sm" onClick={() => setRejecting(false)} disabled={busy !== null}>
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {error && <div className="error" style={{ margin: 0, fontSize: 12.5 }}>{error}</div>}

      <div>
        <div className="label" style={{ marginBottom: 4 }}>History</div>
        {data.history.length === 0 ? (
          <div className="muted" style={{ fontSize: 12.5 }}>No approval steps yet.</div>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
            {history.map((h, i) => (
              <li key={`${h.at}-${i}`} style={{ fontSize: 12.5, lineHeight: 1.5 }}>
                <b>{WORKFLOW_ACTION_DONE[h.action] || h.action}</b>
                <span className="muted">
                  {" · "}{h.actor_email || "system"}{" · "}{formatDateTime(h.at)}
                  {h.via ? ` · via ${h.via}` : ""}
                </span>
                {h.reason && <div style={{ marginTop: 2 }}>&ldquo;{h.reason}&rdquo;</div>}
              </li>
            ))}
          </ul>
        )}
        {data.history.length > HISTORY_PREVIEW && (
          <button type="button" className="btn secondary sm" style={{ marginTop: 6 }} onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show less" : `Show all ${data.history.length}`}
          </button>
        )}
      </div>
    </div>
  );
}
