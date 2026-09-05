"use client";

import { useEffect, type ReactNode } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** actions shown in the header (Edit, Delete, …) */
  actions?: ReactNode;
  /** The record itself — fields, related records, the page's own panels. */
  children: ReactNode;
  /** Activity and collaboration for the record: status rules, attestation, comments,
   *  attachments, the audit trail. Rendered as a second column that scrolls on its
   *  own, so the record and its history are read side by side, not one after the other. */
  aside?: ReactNode;
  /** "full" (default) takes the viewport with two columns; "panel" is the older
   *  right-hand slide-over, kept for small records that do not need the room. */
  layout?: "full" | "panel";
  /** Panel width, honoured only when ``layout="panel"``. */
  width?: number;
};

/**
 * Record detail. Overlays the list in place — no scrolling past a thousand rows —
 * and, paired with useRecordParam, is driven by the URL so it is deep-linkable and
 * Back-button correct.
 *
 * The full layout exists because a GRC record is not a form: a risk carries its
 * scores, controls, assets, acceptance history, attestations, comments and an audit
 * trail, and stacking all of that in a 620px column made a single record several
 * screens tall. Two columns, each scrolling independently, is how eramba lays it out
 * and it is the right shape — the item on the left, what has happened to it on the
 * right, both visible at once.
 */
export default function RecordDrawer({
  open, onClose, title, subtitle, actions, children, aside, layout = "full", width = 620,
}: Props) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  const full = layout === "full";

  return (
    <div className={`drawer-overlay${full ? " full" : ""}`} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className={`drawer${full ? " full" : ""}`} style={full ? undefined : { width }} role="dialog" aria-modal="true">
        <div className="drawer-head">
          {full && (
            <button className="btn secondary sm drawer-back" onClick={onClose} aria-label="Back to list">
              ← Back
            </button>
          )}
          <div style={{ minWidth: 0, flex: 1 }}>
            <h2 style={{ margin: 0, fontSize: full ? 20 : 18, overflow: "hidden", textOverflow: "ellipsis" }}>{title}</h2>
            {subtitle && <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>{subtitle}</div>}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            {actions}
            <button className="x" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </div>

        {full ? (
          <div className={`drawer-columns${aside ? " has-aside" : ""}`}>
            <div className="drawer-main">
              <div className="drawer-main-inner">{children}</div>
            </div>
            {aside && (
              <div className="drawer-aside">
                <div className="drawer-aside-title">Activity &amp; collaboration</div>
                {aside}
              </div>
            )}
          </div>
        ) : (
          <div className="drawer-body">{children}</div>
        )}
      </aside>
    </div>
  );
}
