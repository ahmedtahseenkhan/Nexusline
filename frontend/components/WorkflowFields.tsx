"use client";

/* A record's approval lifecycle, on the record: state badge, approval owner, the steps
   this user may take now, and who moved it when and why.

     <WorkflowFields entityType="risk" entityId={record?.id ?? null} onChanged={reload} />

   Replaces the per-page `workflow_status` dropdowns: the state moves only through
   Submit for review → Approve / Reject (with a reason) → Revise / Retire, via
   POST /records/{entityType}/{id}/workflow/{action}. The server decides which buttons
   appear (permission, four-eyes, a live approval route) and enforces the same rules
   again when one is pressed. For a record not saved yet (`entityId` null) it shows
   "Draft — save first" and nothing else.

   Options (record-page-spec §3.5, §3.3.10):
   - `variant="compact"`: the one-row layout of the dossier Sign-off card (and of
     RecordApproval in a drawer aside): "Approval [badge]", the status line, the
     approval-owner line (Set / Change in a Disclosure), the remaining actions as
     secondary buttons (Reject… opens its reason form in a Disclosure), the blocked
     reason and a collapsed "History (n)" with "See in trail".
   - `omitActions`: actions not to render here (SignOffCard omits submit and approve,
     which the header's primary button owns).
   Inside a RecordDrawer with a matching `governance` it reads that shared state and
   reloads it after a change; anywhere else it fetches its own, as before. Transitions go
   through `runWorkflowAction`, so confirms and toasts match the header button. */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Badge } from "@/components/badges";
import UserPicker from "@/components/UserPicker";
import MandateNote from "@/components/MandateNote";
import Disclosure from "@/components/record/Disclosure";
import { WorkflowBadge } from "@/components/record/WorkflowBadge";
import { useRecordGovernance, govModelFromParts } from "@/components/record/RecordGovernance";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { toast } from "@/lib/feedback";
import { formatDate, formatDateTime } from "@/lib/format";
import { approvalLine } from "@/lib/record/text";
import { runWorkflowAction, workflowErrorMessage } from "@/lib/workflowActions";
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
  /** "full" (default) or the one-row "compact" layout. */
  variant?: "full" | "compact";
  /** Actions not to render here (the header's primary owns them). */
  omitActions?: WorkflowActionKey[];
  /** Compact only: the row's key label (default "Approval"); null shows the badge alone. */
  keyLabel?: string | null;
};

const STATE_TONE: Record<WorkflowStateKey, "neutral" | "info" | "low" | "medium"> = {
  draft: "neutral",
  in_review: "info",
  approved: "low",
  retired: "medium",
};

const HISTORY_PREVIEW = 4;

/** Accessible names that say which row the button belongs to. */
const ACTION_ARIA: Record<WorkflowActionKey, string> = {
  submit: "Submit the record for review",
  approve: "Approve the record",
  reject: "Reject approval…",
  revise: "Revise: reopen the record for revision",
  retire: "Retire the record",
};

/** Record types whose approval is checked against the delegation-of-authority matrix
 *  (backend services/authority_limits.py): the approver sees their mandate before approving.
 *  Exceptions show it in their own drawer, beside the Approve / Reject decision. */
const MANDATE_TYPES = new Set(["loss_event", "outsourcing_arrangement"]);
type MandateType = "loss_event" | "outsourcing_arrangement";

const dateFmt = { date: (v: string | null | undefined) => formatDate(v), dateTime: (v: string | null | undefined) => formatDateTime(v), money: () => "" };

export default function WorkflowFields({ entityType, entityId, onChanged, variant = "full", omitActions, keyLabel = "Approval" }: Props) {
  const gov = useRecordGovernance(entityType, entityId);
  const shared = !!gov && gov.lifecycle && !!entityId;

  const [own, setOwn] = useState<RecordWorkflow | null>(null);
  const [ownError, setOwnError] = useState<string | null>(null);
  const [busy, setBusy] = useState<WorkflowActionKey | "owner" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  // "History (n)" is a disclosure: while open, Esc folds it (focus back on its toggle)
  // and leaves the record open.
  const historyBtn = useRef<HTMLButtonElement>(null);
  useEscapeLayer(historyOpen, () => {
    setHistoryOpen(false);
    historyBtn.current?.focus({ preventScroll: true });
  });
  const [ownerOpen, setOwnerOpen] = useState(false);
  const uid = useId();
  const rejectBtn = useRef<HTMLButtonElement>(null);
  const ownerBtn = useRef<HTMLButtonElement>(null);

  const load = useCallback(async () => {
    if (!entityId || shared) return;
    try {
      setOwn(await records.workflow(entityType, entityId));
      setOwnError(null);
    } catch (e) {
      setOwnError(workflowErrorMessage(e, "Could not load the approval status"));
    }
  }, [entityType, entityId, shared]);

  useEffect(() => {
    setOwn(null);
    setRejecting(false);
    setReason("");
    setError(null);
    setShowAll(false);
    setHistoryOpen(false);
    setOwnerOpen(false);
    load();
  }, [load]);

  const data = shared ? gov?.workflow ?? null : own;
  const loadError = shared ? gov?.errors.workflow ?? null : ownError;
  const compact = variant === "compact";

  if (!entityId) {
    const msg = (
      <>
        <Badge tone="neutral">Draft</Badge>
        <span className="muted">Draft — save first, then submit it for review.</span>
      </>
    );
    return compact ? (
      <div className="rec-so-row rec-wf"><div className="k">{msg}</div></div>
    ) : (
      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>{msg}</div>
    );
  }
  if (!data && loadError) {
    return compact ? (
      <div className="rec-so-row rec-wf"><div className="k">{keyLabel}</div><div className="d">{loadError}</div></div>
    ) : (
      <div className="muted" style={{ fontSize: 12.5 }}>{loadError}</div>
    );
  }
  if (!data) {
    return compact ? (
      <div className="rec-so-row rec-wf"><div className="k">{keyLabel}</div><div className="d">Loading approval status…</div></div>
    ) : (
      <div className="muted" style={{ fontSize: 12.5 }}>Loading approval status…</div>
    );
  }

  const id = entityId;
  const wf = data;

  async function afterChange(state: WorkflowStateKey) {
    if (shared && gov) await gov.reload();
    else await load();
    onChanged?.(state);
  }

  async function run(action: WorkflowActionKey, why?: string) {
    setBusy(action);
    setError(null);
    try {
      const res = await runWorkflowAction(entityType, id, action, why);
      if (!res) return;
      setRejecting(false);
      setReason("");
      await afterChange(res.state);
    } catch (e) {
      const msg = workflowErrorMessage(e);
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
      const next = await records.setOwner(entityType, id, ownerId);
      toast(ownerId ? "Approval owner set" : "Approval owner cleared");
      setOwnerOpen(false);
      if (shared && gov) await gov.reload();
      else setOwn(next);
      onChanged?.(next.state);
    } catch (e) {
      const msg = workflowErrorMessage(e, "Could not change the approval owner");
      setError(msg);
      toast(msg, "error");
    } finally {
      setBusy(null);
    }
  }

  const omit = new Set(omitActions ?? []);
  const actions = wf.allowed_actions.filter((a) => !omit.has(a));
  const history = showAll ? wf.history : wf.history.slice(0, HISTORY_PREVIEW);
  const mandate = wf.allowed_actions.includes("approve") && MANDATE_TYPES.has(entityType)
    ? <MandateNote entityType={entityType as MandateType} recordId={entityId} refreshKey={wf} />
    : null;
  const ownerName = wf.owner ? wf.owner.full_name || wf.owner.email : wf.owner_text;

  const historyList = (
    <>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "grid", gap: 6 }}>
        {history.map((h, i) => (
          <li key={`${h.at}-${i}`} style={{ fontSize: 12.5, lineHeight: 1.5 }}>
            <b>{WORKFLOW_ACTION_DONE[h.action] || (h.action === "import" ? "Imported" : h.action)}</b>
            <span className="muted">
              {" · "}{h.actor_email || "system"}{" · "}{formatDateTime(h.at)}
              {h.via ? ` · via ${h.via}` : ""}
            </span>
            {h.reason && <div style={{ marginTop: 2 }}>&ldquo;{h.reason}&rdquo;</div>}
          </li>
        ))}
      </ul>
      {wf.history.length > HISTORY_PREVIEW && (
        <button
          type="button"
          className={compact ? "rec-link" : "btn secondary sm"}
          style={{ marginTop: 6 }}
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "Show less" : `Show all ${wf.history.length}`}
        </button>
      )}
    </>
  );

  if (compact) {
    const line = approvalLine(govModelFromParts(wf, null, false), dateFmt, { routing: wf.routing });
    const rejectPanel = `${uid}-reject`;
    const ownerPanel = `${uid}-owner`;
    const seeInTrail = () => {
      gov?.setTrailFilter("approval");
      requestAnimationFrame(() => document.getElementById("rec-trail-card")?.focus());
    };
    return (
      <div className="rec-so-row rec-wf">
        <div className="k">
          {keyLabel}
          <WorkflowBadge state={wf.state} asIs hollowDraft />
        </div>
        <div className="d">
          <span className={line.warn ? "rec-gap" : undefined}>{line.text}</span>
          {line.note && <span> {line.note}</span>}
        </div>
        <div className="d">
          {ownerName ? (
            <>
              Approval owner: <b>{ownerName}</b>
            </>
          ) : (
            "Approval owner not set"
          )}
          {wf.can_set_owner && (
            <>
              {" "}
              <button
                ref={ownerBtn}
                type="button"
                className="rec-link"
                aria-expanded={ownerOpen}
                aria-controls={ownerPanel}
                aria-label={ownerName ? "Change the approval owner" : "Set the approval owner"}
                onClick={() => setOwnerOpen((v) => !v)}
                disabled={busy !== null}
              >
                {ownerName ? "Change" : "Set"}
              </button>
            </>
          )}
        </div>
        {wf.can_set_owner && (
          <div className="d">
            <Disclosure
              label="Approval owner"
              hideTrigger
              open={ownerOpen}
              onOpenChange={setOwnerOpen}
              id={ownerPanel}
              triggerRef={ownerBtn}
            >
              {(close) => (
                <div style={{ display: "grid", gap: 8 }}>
                  <UserPicker
                    value={wf.owner?.id ?? null}
                    selected={wf.owner}
                    legacyText={wf.owner_text || null}
                    onChange={(ownerId) => changeOwner(ownerId)}
                    disabled={busy !== null}
                    placeholder="Who takes this through approval…"
                  />
                  <div className="row">
                    {(wf.owner || wf.owner_text) && (
                      <button type="button" className="btn secondary sm" onClick={() => changeOwner(null)} disabled={busy !== null}>
                        Clear
                      </button>
                    )}
                    <button type="button" className="btn secondary sm" onClick={close} disabled={busy !== null}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </Disclosure>
          </div>
        )}
        {actions.length > 0 && (
          <div className="acts">
            {actions.map((action) =>
              action === "reject" ? (
                <button
                  key={action}
                  ref={rejectBtn}
                  type="button"
                  className="btn secondary sm"
                  aria-label={ACTION_ARIA.reject}
                  aria-expanded={rejecting}
                  aria-controls={rejectPanel}
                  onClick={() => setRejecting((v) => !v)}
                  disabled={busy !== null}
                >
                  Reject…
                </button>
              ) : (
                <button
                  key={action}
                  type="button"
                  className="btn secondary sm"
                  aria-label={ACTION_ARIA[action]}
                  onClick={() => run(action)}
                  disabled={busy !== null}
                >
                  {busy === action ? "Working…" : WORKFLOW_ACTION_LABEL[action]}
                </button>
              ),
            )}
          </div>
        )}
        {mandate && <div className="d">{mandate}</div>}
        {actions.includes("reject") && (
          <div className="d">
            <Disclosure label="Reject approval" hideTrigger open={rejecting} onOpenChange={setRejecting} id={rejectPanel} triggerRef={rejectBtn}>
              {(close) => (
                <div style={{ display: "grid", gap: 6 }}>
                  <label className="label" htmlFor={`wf-reject-${id}`} style={{ margin: 0 }}>Why is it going back to draft?</label>
                  <textarea
                    id={`wf-reject-${id}`}
                    className="input"
                    rows={2}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="The reason is recorded in the history and the activity log"
                  />
                  <div className="row">
                    <button type="button" className="btn secondary sm" onClick={() => run("reject", reason)} disabled={busy !== null || !reason.trim()}>
                      {busy === "reject" ? "Rejecting…" : "Reject"}
                    </button>
                    <button type="button" className="btn secondary sm" onClick={close} disabled={busy !== null}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </Disclosure>
          </div>
        )}
        {wf.blocked_reason && <div className="d">{wf.blocked_reason}</div>}
        {error && <div className="d rec-error" role="alert">{error}</div>}
        {wf.history.length > 0 && (
          <div className="d">
            <button
              ref={historyBtn}
              type="button"
              className="rec-link"
              aria-expanded={historyOpen}
              aria-controls={`${uid}-history`}
              onClick={() => setHistoryOpen((v) => !v)}
            >
              History ({wf.history.length})
            </button>
          </div>
        )}
        {historyOpen && (
          <div className="d rec-wf-history" id={`${uid}-history`}>
            {historyList}
            {shared && (
              <div style={{ marginTop: 6 }}>
                <button type="button" className="rec-link" onClick={seeInTrail}>See in trail</button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <Badge tone={STATE_TONE[wf.state] ?? "neutral"}>{WORKFLOW_STATE_LABEL[wf.state] ?? wf.state}</Badge>
        {wf.routing && (
          <span className="muted" style={{ fontSize: 12.5 }}>
            Going through its approval route — each stage is decided in the Approvals inbox.
          </span>
        )}
      </div>

      <div>
        <label className="label">Approval owner</label>
        {wf.can_set_owner ? (
          <UserPicker
            value={wf.owner?.id ?? null}
            selected={wf.owner}
            legacyText={wf.owner_text || null}
            onChange={(ownerId) => changeOwner(ownerId)}
            disabled={busy !== null}
            placeholder="Who takes this through approval…"
          />
        ) : (
          <div style={{ fontSize: 13 }}>{ownerName || <span className="muted">Not set</span>}</div>
        )}
      </div>

      {(actions.length > 0 || wf.blocked_reason) && (
        <div style={{ display: "grid", gap: 8 }}>
          {mandate}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {actions.map((action) =>
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
          {wf.blocked_reason && (
            <div className="muted" style={{ fontSize: 12.5 }}>{wf.blocked_reason}</div>
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
        {wf.history.length === 0 ? (
          <div className="muted" style={{ fontSize: 12.5 }}>No approval steps yet.</div>
        ) : (
          historyList
        )}
      </div>
    </div>
  );
}
