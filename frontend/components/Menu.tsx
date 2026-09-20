"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useEscapeLayer } from "@/lib/escapeLayer";

/* A dropdown of actions. Exists so a page head can hold three buttons instead of eight:
   the primary action stays a button, everything occasional — imports, templates,
   maintenance, methodology — goes behind a labelled menu. Nothing is removed, it is
   ranked.

   Keyboard contract (WAI-ARIA menu button):
   - Trigger: a button with aria-haspopup="menu", aria-expanded and (while open)
     aria-controls. Click, Enter or Space opens the menu with focus on the first item;
     ArrowDown opens on the first item, ArrowUp on the last.
   - Menu: role="menu", labelled by the trigger. Items are role="menuitem" buttons
     (tabIndex -1, roving focus). ArrowDown / ArrowUp move and wrap, Home / End jump to
     the ends, disabled items are skipped, typing a letter jumps to the next item that
     starts with it. Enter or Space activates.
   - Closing: Esc (through the escape stack, so only the menu closes and a dialog or
     record underneath stays open) and choosing an item return focus to the trigger —
     before the item's action runs, so a dialog it opens gives focus back to the
     trigger when it closes. Tab closes the menu and moves on from the trigger. A click
     outside, or focus moving elsewhere, closes it without moving focus. */

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
  /** Accessible name of the trigger when the visible label is too short on its own,
   *  e.g. "More actions for R-002". Default: the visible label. */
  ariaLabel?: string;
};

const TYPEAHEAD_MS = 600;

export default function Menu({ label, items, align = "right", className = "btn secondary", ariaLabel }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const focusOnOpen = useRef<"first" | "last">("first");
  const typed = useRef({ text: "", at: 0 });
  const uid = useId();
  const triggerId = `menu-btn-${uid}`;
  const menuId = `menu-${uid}`;

  /** Indexes of the items focus can land on (not dividers, not disabled). */
  const focusable = () =>
    items.flatMap((it, i) => (it !== "divider" && !it.disabled && itemRefs.current[i] ? [i] : []));

  function focusItem(i: number | undefined) {
    if (i === undefined) return;
    itemRefs.current[i]?.focus();
  }

  function openMenu(where: "first" | "last") {
    focusOnOpen.current = where;
    setOpen(true);
  }

  function closeMenu(returnFocus: boolean) {
    setOpen(false);
    typed.current = { text: "", at: 0 };
    if (returnFocus) triggerRef.current?.focus({ preventScroll: true });
  }

  // Focus the first (or last) item when the menu opens.
  useEffect(() => {
    if (!open) return;
    const idx = focusable();
    focusItem(focusOnOpen.current === "last" ? idx[idx.length - 1] : idx[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // A click outside closes the menu (focus stays where the click put it).
  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) closeMenu(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Esc closes the menu and nothing under it.
  useEscapeLayer(open, () => closeMenu(true));

  function onMenuKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const idx = focusable();
    if (idx.length === 0) return;
    const current = itemRefs.current.findIndex((el) => el === document.activeElement);
    const pos = idx.indexOf(current);
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        focusItem(idx[pos < 0 ? 0 : (pos + 1) % idx.length]);
        return;
      case "ArrowUp":
        e.preventDefault();
        focusItem(idx[pos < 0 ? idx.length - 1 : (pos - 1 + idx.length) % idx.length]);
        return;
      case "Home":
        e.preventDefault();
        focusItem(idx[0]);
        return;
      case "End":
        e.preventDefault();
        focusItem(idx[idx.length - 1]);
        return;
      case "Tab":
        // Not prevented: the browser moves on from the trigger (or back before it).
        closeMenu(true);
        return;
    }
    // Typeahead: a printable character jumps to the next item starting with what was typed.
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== " ") {
      const now = Date.now();
      const t = typed.current;
      t.text = now - t.at > TYPEAHEAD_MS ? e.key.toLowerCase() : t.text + e.key.toLowerCase();
      t.at = now;
      const textOf = (i: number) => (itemRefs.current[i]?.querySelector(".menu-label")?.textContent ?? "").trim().toLowerCase();
      const find = (prefix: string) => {
        const start = pos < 0 ? 0 : prefix.length === 1 ? pos + 1 : pos;
        for (let k = 0; k < idx.length; k++) {
          const i = idx[(start + k) % idx.length];
          if (textOf(i).startsWith(prefix)) return i;
        }
        return undefined;
      };
      // "c" then "o" narrows to "co…"; when that matches nothing, the newest letter alone is used.
      let hit = find(t.text);
      if (hit === undefined && t.text.length > 1) {
        t.text = e.key.toLowerCase();
        hit = find(t.text);
      }
      if (hit !== undefined) {
        e.preventDefault();
        focusItem(hit);
      }
    }
  }

  itemRefs.current.length = items.length;

  return (
    <div
      ref={ref}
      style={{ position: "relative", display: "inline-block" }}
      onBlur={(e) => {
        // Focus moved to something outside the menu (not a click on nothing): close.
        const to = e.relatedTarget as Node | null;
        if (open && to && ref.current && !ref.current.contains(to)) closeMenu(false);
      }}
    >
      <button
        ref={triggerRef}
        id={triggerId}
        type="button"
        className={className}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={ariaLabel}
        onClick={() => (open ? closeMenu(true) : openMenu("first"))}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            openMenu(e.key === "ArrowUp" ? "last" : "first");
          }
        }}
      >
        {label} <span aria-hidden style={{ opacity: 0.6, marginLeft: 2 }}>▾</span>
      </button>
      {open && (
        <div className="menu" role="menu" id={menuId} aria-labelledby={triggerId} style={{ [align]: 0 }} onKeyDown={onMenuKeyDown}>
          {items.map((item, i) =>
            item === "divider" ? (
              <div key={i} className="menu-divider" role="separator" />
            ) : (
              <button
                key={i}
                ref={(el) => {
                  itemRefs.current[i] = el;
                }}
                type="button"
                role="menuitem"
                tabIndex={-1}
                className={`menu-item${item.danger ? " danger" : ""}`}
                disabled={item.disabled}
                aria-disabled={item.disabled || undefined}
                aria-labelledby={`${menuId}-label-${i}`}
                aria-describedby={item.hint ? `${menuId}-hint-${i}` : undefined}
                onClick={() => {
                  closeMenu(true); // focus is back on the trigger before the action runs
                  item.onClick();
                }}
              >
                <span className="menu-label" id={`${menuId}-label-${i}`}>{item.label}</span>
                {item.hint && (
                  <span className="menu-hint" id={`${menuId}-hint-${i}`}>
                    {item.hint}
                  </span>
                )}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}
