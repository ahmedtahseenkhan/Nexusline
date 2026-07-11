"use client";

import { useEffect, useState, type ReactNode } from "react";

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
type ConfirmOpts = { title: string; message?: string; confirmLabel?: string; danger?: boolean };
type PendingConfirm = ConfirmOpts & { resolve: (ok: boolean) => void };

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
    confirmSub({ ...opts, resolve });
  });
}

/* ============================================================ The host ====== */
/** Mount once (in the app layout). Renders toasts + the confirm dialog. */
export function FeedbackHost() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);

  useEffect(() => {
    const sub = (t: ToastItem[]) => setItems([...t]);
    toastSubs.add(sub);
    confirmSub = setConfirm;
    return () => {
      toastSubs.delete(sub);
      confirmSub = null;
    };
  }, []);

  useEffect(() => {
    if (!confirm) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [confirm]);

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
          <div className="modal confirm-modal" role="alertdialog" aria-modal="true" aria-label={confirm.title}>
            <div className="modal-body" style={{ padding: "22px 24px" }}>
              <h2 style={{ margin: "0 0 8px", fontSize: 17 }}>{confirm.title}</h2>
              {confirm.message && <p className="muted" style={{ margin: 0, fontSize: 14, lineHeight: 1.55 }}>{confirm.message}</p>}
            </div>
            <div className="modal-foot">
              <button className="btn secondary" onClick={() => close(false)} autoFocus>Cancel</button>
              <button className={`btn${confirm.danger ? " danger" : ""}`} onClick={() => close(true)}>
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
