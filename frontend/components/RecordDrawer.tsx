"use client";

import { useEffect, type ReactNode } from "react";

type Props = {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  subtitle?: ReactNode;
  /** actions shown in the drawer header (Edit, Delete, …) */
  actions?: ReactNode;
  children: ReactNode;
  width?: number;
};

/**
 * Right-side slide-over for record detail. Replaces the "detail rendered below the
 * whole table" pattern: the detail overlays in place, no scrolling past 1,000 rows,
 * and (paired with useRecordParam) it's driven by the URL so it's deep-linkable and
 * Back-button correct.
 */
export default function RecordDrawer({ open, onClose, title, subtitle, actions, children, width = 620 }: Props) {
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

  return (
    <div className="drawer-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" style={{ width }} role="dialog" aria-modal="true">
        <div className="drawer-head">
          <div style={{ minWidth: 0 }}>
            <h2 style={{ margin: 0, fontSize: 18, overflow: "hidden", textOverflow: "ellipsis" }}>{title}</h2>
            {subtitle && <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>{subtitle}</div>}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            {actions}
            <button className="x" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}
