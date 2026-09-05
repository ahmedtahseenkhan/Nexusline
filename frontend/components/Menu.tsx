"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/* A dropdown of actions. Exists so a page head can hold three buttons instead of eight:
   the primary action stays a button, everything occasional — imports, templates,
   maintenance, methodology — goes behind a labelled menu. Nothing is removed, it is
   ranked. */

export type MenuItem =
  | "divider"
  | {
      label: ReactNode;
      onClick: () => void;
      /** Small grey line under the label — what the action does, or when to use it. */
      hint?: string;
      danger?: boolean;
      disabled?: boolean;
    };

type Props = {
  label: ReactNode;
  items: MenuItem[];
  /** Which edge of the button the menu aligns to. */
  align?: "left" | "right";
  className?: string;
};

export default function Menu({ label, items, align = "right", className = "btn secondary" }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <button type="button" className={className} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {label} <span aria-hidden style={{ opacity: 0.6, marginLeft: 2 }}>▾</span>
      </button>
      {open && (
        <div className="menu" role="menu" style={{ [align]: 0 }}>
          {items.map((item, i) =>
            item === "divider" ? (
              <div key={i} className="menu-divider" />
            ) : (
              <button
                key={i}
                type="button"
                role="menuitem"
                className={`menu-item${item.danger ? " danger" : ""}`}
                disabled={item.disabled}
                onClick={() => { setOpen(false); item.onClick(); }}
              >
                <span>{item.label}</span>
                {item.hint && <span className="menu-hint">{item.hint}</span>}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}
