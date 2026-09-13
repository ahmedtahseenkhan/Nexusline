"use client";

import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { api, type TreatmentAction } from "@/lib/api";
import { toast, confirmDialog } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import UserPicker, { UserName } from "@/components/UserPicker";
import { Badge } from "@/components/badges";
import Disclosure from "@/components/record/Disclosure";
import LabelledSearch, { rowAction } from "@/components/record/a11y";

/* A risk's treatment plan as actions with an owner, a due date and progress.

   The plan's summary stays in the risk's "Treatment plan" text; this is the part that can
   be chased. The risk's treatment deadline follows the actions (the latest open action's
   due date), and each open action past its due date raises its own overdue alert. Marking
   an action done stamps when it was completed; cancel an action to take it off the plan
   while keeping it on the record.

   The add form opens on demand (a Disclosure: Esc and Cancel return focus to "Add
   action"); a parent opens it through the `add()` handle — the risk record's More menu
   and its "Add action" open points do. Every button is secondary: the record page keeps
   its one filled button in the header. Each row's buttons and fields name the action they
   act on ("Edit Enforce MFA", "Remove Enforce MFA"), and every picker has a real label
   (record-page-spec v1.1 D3). Without `canWrite` the plan is read-only. */

const STATUS_LABEL: Record<TreatmentAction["status"], string> = {
  open: "Open",
  in_progress: "In progress",
  done: "Done",
  cancelled: "Cancelled",
};
const STATUS_TONE: Record<TreatmentAction["status"], "low" | "medium" | "neutral" | "info"> = {
  open: "info",
  in_progress: "medium",
  done: "low",
  cancelled: "neutral",
};

type Draft = { title: string; owner_id: string | null; due_date: string; description: string };
const EMPTY: Draft = { title: "", owner_id: null, due_date: "", description: "" };

type Props = {
  riskId: string;
  actions: TreatmentAction[];
  progress?: { done: number; total: number; overdue: number; percent: number } | null;
  /** Reload the risk after any change (its treatment deadline may have moved). */
  onChange: () => void;
  /** The viewer holds risk:write. Default true (the server still decides). */
  canWrite?: boolean;
};

export type RiskTreatmentActionsHandle = {
  /** Open the "Add action" form (focus moves to its first field). */
  add(): void;
};

const RiskTreatmentActions = forwardRef<RiskTreatmentActionsHandle, Props>(function RiskTreatmentActions(
  { riskId, actions, progress, onChange, canWrite = true },
  ref,
) {
  const { formatDate } = useFormat();
  const [adding, setAdding] = useState(false);
  const addBtn = useRef<HTMLButtonElement>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [edit, setEdit] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setAddOpen(open: boolean) {
    setAdding(open);
    setError(null);
    if (!open) setDraft(EMPTY);
  }

  useImperativeHandle(ref, () => ({ add: () => { if (canWrite) setAddOpen(true); } }), [canWrite]);

  async function run(fn: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (done) toast(done);
      onChange();
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the action");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(close: () => void) {
    if (!draft.title.trim()) {
      setError("Give the action a title.");
      return;
    }
    const ok = await run(
      () => api.createTreatmentAction(riskId, {
        title: draft.title.trim(), owner_id: draft.owner_id, due_date: draft.due_date || null,
        description: draft.description,
      }),
      "Treatment action added",
    );
    if (ok) {
      setDraft(EMPTY);
      close();
    }
  }

  async function saveEdit(a: TreatmentAction) {
    if (!edit.title.trim()) {
      setError("Give the action a title.");
      return;
    }
    const ok = await run(() => api.updateTreatmentAction(riskId, a.id, {
      title: edit.title.trim(), owner_id: edit.owner_id, due_date: edit.due_date || null, description: edit.description,
    }), "Action updated");
    if (ok) setEditingId(null);
  }

  async function remove(a: TreatmentAction) {
    const ok = await confirmDialog({
      title: `Remove "${a.title}"?`,
      message: "The action is deleted from the plan (the activity trail keeps a record). To keep it on the plan but stop tracking it, set it to Cancelled instead.",
      confirmLabel: "Remove",
      danger: true,
    });
    if (ok) await run(() => api.deleteTreatmentAction(riskId, a.id), "Action removed");
  }

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, fontSize: 13, lineHeight: "18px", fontWeight: 650, color: "var(--text-strong)" }}>Actions</h3>
        {progress && progress.total > 0 && (
          <>
            <div
              role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent}
              aria-label="Treatment progress"
              style={{ flex: "0 0 120px", height: 6, borderRadius: 3, background: "var(--surface-2)", overflow: "hidden" }}
            >
              <div style={{ width: `${progress.percent}%`, height: "100%", background: "var(--green)" }} />
            </div>
            <span className="muted" style={{ fontSize: 12 }}>
              {progress.done} of {progress.total} done
              {progress.overdue ? <> · <span style={{ color: "var(--red)", fontWeight: 600 }}>{progress.overdue} overdue</span></> : null}
            </span>
          </>
        )}
        {canWrite && (
          <button
            ref={addBtn}
            type="button"
            className="btn secondary sm"
            style={{ marginLeft: "auto" }}
            aria-expanded={adding}
            aria-controls="risk-treatment-add"
            onClick={() => setAddOpen(!adding)}
          >
            Add action
          </button>
        )}
      </div>
      {error && !adding && <div className="error" style={{ fontSize: 12.5, marginBottom: 8 }}>{error}</div>}

      {actions.length > 0 ? (
        <div className="table-wrap">
          <table style={{ fontSize: 13 }}>
            <thead>
              <tr>
                <th>Action</th>
                <th style={{ width: 130 }}>Owner</th>
                <th style={{ width: 110 }}>Due</th>
                <th style={{ width: 150 }}>Status</th>
                <th style={{ width: 70 }}>%</th>
                <th style={{ width: 110 }}><span className="sr-only">Row actions</span></th>
              </tr>
            </thead>
            <tbody>
              {actions.map((a) =>
                editingId === a.id ? (
                  <tr key={a.id}>
                    <td><input className="input" aria-label={`Title of ${a.title}`} style={{ padding: "4px 8px", fontSize: 13 }} value={edit.title} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></td>
                    <td>
                      <LabelledSearch label={`Owner of ${a.title}`} hideLabel>
                        <UserPicker value={edit.owner_id} onChange={(id) => setEdit({ ...edit, owner_id: id })} selected={a.owner_ref} placeholder="Owner…" />
                      </LabelledSearch>
                    </td>
                    <td><input className="input" type="date" aria-label={`Due date of ${a.title}`} style={{ padding: "4px 6px", fontSize: 12.5 }} value={edit.due_date} onChange={(e) => setEdit({ ...edit, due_date: e.target.value })} /></td>
                    <td colSpan={2} className="muted" style={{ fontSize: 12 }}>Status and % are set in the row.</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button type="button" className="btn secondary sm" disabled={busy} {...rowAction("Save", a.title)} onClick={() => saveEdit(a)}>Save</button>{" "}
                      <button type="button" className="btn secondary sm" {...rowAction("Cancel editing", a.title)} onClick={() => setEditingId(null)}>Cancel</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={a.id} style={a.status === "cancelled" ? { opacity: 0.6 } : undefined}>
                    <td>
                      <div className="cell-title" style={a.status === "cancelled" ? { textDecoration: "line-through" } : undefined}>{a.title}</div>
                      {a.completed_at && <div className="muted" style={{ fontSize: 11.5 }}>Completed {formatDate(a.completed_at)}</div>}
                    </td>
                    <td className="muted"><UserName user={a.owner_ref} /></td>
                    <td>{a.overdue ? <Badge tone="high" asIs>Overdue · {formatDate(a.due_date)}</Badge> : a.due_date ? <span className="muted">{formatDate(a.due_date)}</span> : <span className="muted">No due date</span>}</td>
                    <td>
                      <select
                        className="select" aria-label={`Status of ${a.title}`} value={a.status} disabled={busy || !canWrite}
                        onChange={(e) => run(() => api.updateTreatmentAction(riskId, a.id, { status: e.target.value as TreatmentAction["status"] }))}
                      >
                        {(Object.keys(STATUS_LABEL) as TreatmentAction["status"][]).map((k) => <option key={k} value={k}>{STATUS_LABEL[k]}</option>)}
                      </select>
                    </td>
                    <td>
                      {a.status === "done" || a.status === "cancelled" ? (
                        <Badge tone={STATUS_TONE[a.status]} plain>{a.percent_complete}</Badge>
                      ) : (
                        <input
                          key={`${a.id}-${a.percent_complete}`}
                          className="input" type="number" min={0} max={100} aria-label={`Percent complete of ${a.title}`}
                          style={{ width: 60, padding: "4px 6px", fontSize: 12.5 }} defaultValue={a.percent_complete} disabled={busy || !canWrite}
                          onBlur={(e) => {
                            const v = Math.max(0, Math.min(100, Number(e.target.value) || 0));
                            if (v !== a.percent_complete) run(() => api.updateTreatmentAction(riskId, a.id, { percent_complete: v }));
                          }}
                        />
                      )}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {canWrite && (
                        <>
                          <button type="button" className="btn secondary sm" {...rowAction("Edit", a.title)} onClick={() => {
                            setEditingId(a.id);
                            setEdit({ title: a.title, owner_id: a.owner_id, due_date: a.due_date ?? "", description: a.description });
                          }}>Edit</button>{" "}
                          <button type="button" className="btn secondary sm" disabled={busy} {...rowAction("Remove", a.title)} onClick={() => remove(a)}>Remove</button>
                        </>
                      )}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      ) : (
        !adding && <div className="muted" style={{ fontSize: 12.5 }}>No actions yet — break the plan into owned, dated actions so it can be chased.</div>
      )}

      <Disclosure label="Add action" hideTrigger open={canWrite && adding} onOpenChange={setAddOpen} triggerRef={addBtn} id="risk-treatment-add">
        {(close) => (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void add(close);
            }}
          >
            <div>
              <label className="label" htmlFor="risk-action-title">Action</label>
              <input id="risk-action-title" className="input" value={draft.title} placeholder="e.g. Enforce MFA on internet banking" onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 8, alignItems: "end", marginTop: 8 }}>
              <LabelledSearch label="Owner">
                <UserPicker value={draft.owner_id} onChange={(id) => setDraft({ ...draft, owner_id: id })} placeholder="Search people…" />
              </LabelledSearch>
              <div>
                <label className="label" htmlFor="risk-action-due">Due</label>
                <input id="risk-action-due" className="input" type="date" value={draft.due_date} onChange={(e) => setDraft({ ...draft, due_date: e.target.value })} />
              </div>
            </div>
            {error && <div className="error" style={{ fontSize: 12.5, marginTop: 8 }}>{error}</div>}
            <div className="row" style={{ marginTop: 10 }}>
              <button type="submit" className="btn secondary sm" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
              <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
            </div>
          </form>
        )}
      </Disclosure>
    </div>
  );
});

export default RiskTreatmentActions;
