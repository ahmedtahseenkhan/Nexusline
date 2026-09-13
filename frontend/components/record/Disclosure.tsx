"use client";

/* The only "form on demand" primitive (record-page-spec §3.3.9): maintenance, link IT
   asset, reject reason, approval owner, custom fields, raise issue, schedule review, CAPA,
   progress log and the add inputs in Discussion & files.

     <Disclosure label="Record maintenance">
       {(close) => (
         <form onSubmit={async (e) => { e.preventDefault(); await save(); close(); }}>
           …inputs…
           <div className="row">
             <button className="btn secondary sm">Record</button>
             <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
           </div>
         </form>
       )}
     </Disclosure>

   The trigger is a button with aria-expanded / aria-controls; the panel is a labelled
   `role="group"`. Opening moves focus to the first focusable element in the panel;
   closing (Cancel, Esc via the escape stack, or `close()` after a successful submit)
   returns focus to the trigger.

   Controlled use (a section head or More item opens it): pass `open` + `onOpenChange`,
   and `hideTrigger` when the trigger lives elsewhere — then pass `triggerRef` (or focus
   returns to whatever was focused when it opened). */

import { useCallback, useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { useEscapeLayer } from "@/lib/escapeLayer";

type DisclosureProps = {
  /** Trigger text: "Record maintenance". */
  label: ReactNode;
  /** Default "btn secondary sm". */
  buttonClassName?: string;
  /** Optional control (More-menu items can open it). */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Default "rec-disclosure". */
  panelClassName?: string;
  /** The trigger lives elsewhere (e.g. the section head). */
  hideTrigger?: boolean;
  children: (close: () => void) => ReactNode;
  /** Accessible name of the panel when `label` is not plain text. */
  ariaLabel?: string;
  /** Panel id (default generated) — for an external trigger's aria-controls. */
  id?: string;
  /** Where focus returns on close when `hideTrigger` is set. */
  triggerRef?: RefObject<HTMLElement | null>;
  disabled?: boolean;
};

const FOCUSABLE =
  'input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

function textOf(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  return "";
}

export default function Disclosure({
  label,
  buttonClassName = "btn secondary sm",
  open: openProp,
  onOpenChange,
  panelClassName = "rec-disclosure",
  hideTrigger = false,
  children,
  ariaLabel,
  id,
  triggerRef,
  disabled,
}: DisclosureProps) {
  const genId = useId();
  const panelId = id ?? `disc-${genId}`;
  const [inner, setInner] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? !!openProp : inner;
  const ownTrigger = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  const setOpen = useCallback(
    (v: boolean) => {
      if (!controlled) setInner(v);
      onOpenChange?.(v);
    },
    [controlled, onOpenChange],
  );

  const close = useCallback(() => setOpen(false), [setOpen]);
  // Esc closes the panel. A dialog, menu or picker opened on top of it (the Edit form,
  // the Attest dialog, More, an AsyncSelect inside the panel) is a later layer of the
  // same stack, so it takes that Esc first.
  useEscapeLayer(open, close);

  // Focus in on open; back to the trigger on close. When the trigger is gone by then (a
  // row that only renders while it has something to show, a section that collapses to
  // its empty line and unmounts this panel), focus goes to what was focused when the
  // panel opened — the More button, for a panel opened from the More menu — never to
  // <body>.
  const wasOpen = useRef(false);
  const opener = useRef<HTMLElement | null>(null);
  const restoreFocus = useCallback((onlyIfLost: boolean) => {
    const candidates = [returnTo.current, opener.current];
    if (!onlyIfLost) {
      returnTo.current = null;
      opener.current = null;
    }
    if (typeof document === "undefined") return;
    const now = document.activeElement as HTMLElement | null;
    const lost = !now || now === document.body || !now.isConnected;
    if (onlyIfLost && !lost) return;
    for (const el of candidates) {
      if (el && el.isConnected && !(el as HTMLButtonElement).disabled && el.getClientRects().length > 0) {
        el.focus({ preventScroll: true });
        return;
      }
    }
  }, []);
  useEffect(() => {
    if (open && !wasOpen.current) {
      wasOpen.current = true;
      const active = typeof document !== "undefined" ? (document.activeElement as HTMLElement | null) : null;
      opener.current = active && active !== document.body ? active : null;
      returnTo.current = hideTrigger ? triggerRef?.current ?? active : ownTrigger.current;
      requestAnimationFrame(() => {
        const first = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE);
        (first ?? panelRef.current)?.focus({ preventScroll: false });
      });
    } else if (!open && wasOpen.current) {
      wasOpen.current = false;
      restoreFocus(false);
    }
  }, [open, hideTrigger, triggerRef, restoreFocus]);
  // Unmounted while open (the parent stopped rendering it on close): focus was inside the
  // panel and went with it, so put it back. Only when focus is actually lost, and without
  // clearing the refs, so StrictMode's mount → unmount → mount check changes nothing.
  useEffect(
    () => () => {
      if (wasOpen.current) restoreFocus(true);
    },
    [restoreFocus],
  );

  const name = ariaLabel ?? (textOf(label) || undefined);

  return (
    <>
      {!hideTrigger && (
        <button
          ref={ownTrigger}
          type="button"
          className={buttonClassName}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          disabled={disabled}
          onClick={() => setOpen(!open)}
        >
          {label}
        </button>
      )}
      {open && (
        <div role="group" id={panelId} aria-label={name} className={panelClassName} ref={panelRef} tabIndex={-1}>
          {children(close)}
        </div>
      )}
    </>
  );
}

export { Disclosure };
