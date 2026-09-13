"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { trapTab, useEscapeLayer } from "@/lib/escapeLayer";

/* ============================================================== Toasts ===== */
type ToastKind = "success" | "error" | "info";
type ToastItem = { id: number; kind: ToastKind; message: string };

let toastSeq = 0;
const toastSubs = new Set<(t: ToastItem[]) => void>();
let toasts: ToastItem[] = [];

function emitToasts() {
  toastSubs.forEach((fn) => fn(toasts));
}

/** Fire a transient toast from anywhere (no context/provider needed). */
export function toast(message: string, kind: ToastKind = "success") {
  const item: ToastItem = { id: ++toastSeq, kind, message };
  toasts = [...toasts, item];
  emitToasts();
  setTimeout(() => {
    toasts = toasts.filter((t) => t.id !== item.id);
    emitToasts();
  }, kind === "error" ? 6000 : 3500);
}

/* ========================================================= Confirm dialog === */
type ConfirmOpts = {
  title: string;
  message?: string;
  /** Extra content under the message — e.g. the list of records a delete would touch. */
  details?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
};
/** `opener`: what had focus when the confirm was asked for (focus goes back there). */
type PendingConfirm = ConfirmOpts & { resolve: (ok: boolean) => void; opener: HTMLElement | null };

let confirmSub: ((c: PendingConfirm | null) => void) | null = null;

/**
 * Promise-based confirm — a styled, accessible replacement for window.confirm.
 *   if (!(await confirmDialog({ title: "Archive risk?", danger: true }))) return;
 */
export function confirmDialog(opts: ConfirmOpts): Promise<boolean> {
  return new Promise((resolve) => {
    if (!confirmSub) {
      // Host not mounted — fall back to native confirm so callers never hang.
      resolve(window.confirm(opts.message || opts.title));
      return;
    }
    const active = typeof document !== "undefined" ? (document.activeElement as HTMLElement | null) : null;
    confirmSub({ ...opts, resolve, opener: active && active !== document.body ? active : null });
  });
}

/* ============================================================ The host ====== */
/** Mount once (in the app layout). Renders toasts + the confirm dialog.
 *
 *  The confirm dialog is an alertdialog labelled by its title and described by its
 *  message. Cancel has focus on open; Tab stays inside; Esc cancels through the escape
 *  stack (lib/escapeLayer), so a confirm opened from a menu, a form or a record closes
 *  alone and whatever opened it stays open; focus returns to where it was before. */
export function FeedbackHost() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const uid = useId();
  const titleId = `cf-title-${uid}`;
  const msgId = `cf-msg-${uid}`;

  useEffect(() => {
    const sub = (t: ToastItem[]) => setItems([...t]);
    toastSubs.add(sub);
    confirmSub = setConfirm;
    return () => {
      toastSubs.delete(sub);
      confirmSub = null;
    };
  }, []);

  // Give focus back to what had it when the confirm was asked for (the menu trigger, a
  // row button, a field in the form) once it closes.
  useEffect(() => {
    if (!confirm) return;
    const back = confirm.opener;
    return () => {
      if (back && back.isConnected) back.focus({ preventScroll: true });
    };
  }, [confirm]);

  useEscapeLayer(!!confirm, () => close(false));

  function close(ok: boolean) {
    confirm?.resolve(ok);
    setConfirm(null);
  }

  return (
    <>
      <div className="toast-stack" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.kind}`} role="status">
            <span className="toast-ico" aria-hidden>{t.kind === "success" ? "✓" : t.kind === "error" ? "⚠" : "ℹ"}</span>
            <span>{t.message}</span>
          </div>
        ))}
      </div>

      {confirm && (
        <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && close(false)}>
          <div
            ref={dialogRef}
            className="modal confirm-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={confirm.message ? msgId : undefined}
            onKeyDown={(e) => trapTab(e, dialogRef.current)}
          >
            <div className="modal-body" style={{ padding: "22px 24px" }}>
              <h2 id={titleId} style={{ margin: "0 0 8px", fontSize: 17 }}>{confirm.title}</h2>
              {confirm.message && <p id={msgId} className="muted" style={{ margin: 0, fontSize: 14, lineHeight: 1.55 }}>{confirm.message}</p>}
              {confirm.details && <div style={{ marginTop: 12, fontSize: 13.5, lineHeight: 1.55 }}>{confirm.details}</div>}
            </div>
            <div className="modal-foot">
              <button type="button" className="btn secondary" onClick={() => close(false)} autoFocus>Cancel</button>
              <button type="button" className={`btn${confirm.danger ? " danger" : ""}`} onClick={() => close(true)}>
                {confirm.confirmLabel || (confirm.danger ? "Delete" : "Confirm")}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export type { ReactNode };
