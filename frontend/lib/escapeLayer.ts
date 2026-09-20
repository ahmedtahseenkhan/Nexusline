/* One Escape stack for every overlay (record-page-spec §2.5, §3.4).

     useEscapeLayer(open, close);

   Esc closes only the most recently opened layer: a picker or menu inside the Edit form
   closes before the form, a confirm dialog before whatever opened it, a disclosure before
   the record, and the record last. Every component that closes on Esc registers here —
   RecordDrawer, FormModal, the confirm dialog (lib/feedback), Menu, AsyncSelect,
   AsyncMultiSelect, Disclosure, the custom-fields editor, CommandPalette, ArchivedRecords,
   DataTable's column chooser, GenerateRisks, ImportExport, OrphanCleanup, SuggestedClauses'
   bulk dialog and InlineLookupCreate — and none of them keeps its own window listener.

   Rules
   - Call it unconditionally (it is a hook) with `active` = "this layer is open now". A
     component that only exists while open passes `true`.
   - Order is the order layers OPENED, taken from render order: a layer that becomes
     active in a later render sits above one that became active earlier, and when a
     parent and its child become active in the same render the child sits above (React
     renders parents first). So a dialog opened from a menu item, or a menu inside a
     dialog, is always above what it came from, whatever order the effects run in.
   - The stack keeps ONE `keydown` listener on `window` (bubble phase). On Escape it does
     nothing when the event is already `defaultPrevented` or is part of an IME
     composition; otherwise it prevents default and calls the top layer's handler only.
   - A control that consumes Esc itself (a typeahead clearing its list, an inline editor
     cancelling) calls `e.preventDefault()` in its onKeyDown; every layer then stays open.
     As a guard for components that close on Esc without preventDefault, the stack also
     stands aside when the focused element was removed by an earlier handler of the same
     key press.
   - The handler may change between renders; the newest one is called. It should close
     (or refuse to close, e.g. while saving) and must not rethrow.
   - Layers never stack by DOM inspection: do not look for `.modal-overlay` or
     `[role=menu]` to decide whether to close. */

import { useEffect, useRef } from "react";

type Layer = { seq: number; run: () => void };

const stack: Layer[] = []; // sorted by seq, top = last
let seqCounter = 0;
let listening = false;

function onKeyDown(e: KeyboardEvent) {
  if (e.key !== "Escape" && e.key !== "Esc") return;
  if (e.defaultPrevented || e.isComposing) return;
  // A component that closed itself on this Esc (without preventDefault) and unmounted the
  // focused element: that was the top layer, leave the rest.
  if (e.target instanceof Node && e.target !== window.document && !e.target.isConnected) return;
  const top = stack[stack.length - 1];
  if (!top) return;
  e.preventDefault();
  top.run();
}

function ensureListener() {
  if (listening || typeof window === "undefined") return;
  window.addEventListener("keydown", onKeyDown);
  listening = true;
}

function dropListenerIfIdle() {
  if (!listening || stack.length > 0 || typeof window === "undefined") return;
  window.removeEventListener("keydown", onKeyDown);
  listening = false;
}

function insert(layer: Layer) {
  let i = stack.length;
  while (i > 0 && stack[i - 1].seq > layer.seq) i--;
  stack.splice(i, 0, layer);
}

/** Register `onEscape` as an Escape layer while `active` is true. */
export function useEscapeLayer(active: boolean, onEscape: () => void): void {
  const handler = useRef(onEscape);
  handler.current = onEscape;

  // The activation order, stamped in render (parents render before children). Only
  // ordering depends on it, so a discarded render just leaves a gap in the numbers.
  const seq = useRef(0);
  if (!active) seq.current = 0;
  else if (seq.current === 0) seq.current = ++seqCounter;

  useEffect(() => {
    if (!active) return;
    const layer: Layer = { seq: seq.current || ++seqCounter, run: () => handler.current() };
    insert(layer);
    ensureListener();
    return () => {
      const i = stack.indexOf(layer);
      if (i >= 0) stack.splice(i, 1);
      dropListenerIfIdle();
    };
  }, [active]);
}

/** Number of open Escape layers (tests and debugging). */
export function escapeLayerDepth(): number {
  return stack.length;
}

/* ------------------------------------------------------------- Tab trap ----- */

const FOCUSABLE = [
  "a[href]", "button:not([disabled])", 'input:not([disabled]):not([type="hidden"])', "select:not([disabled])",
  "textarea:not([disabled])", '[tabindex]:not([tabindex="-1"])', '[contenteditable]:not([contenteditable="false"])',
].join(", ");

/** Keep Tab / Shift+Tab inside `root`, an aria-modal dialog: from the last control back
 *  to the first and the other way round. Hidden controls (other tabs) and controls with
 *  a negative tabindex (not in the Tab order) are skipped.
 *  Call it from the dialog's onKeyDown: `onKeyDown={(e) => trapTab(e, ref.current)}`. */
export function trapTab(
  e: { key: string; shiftKey: boolean; defaultPrevented: boolean; preventDefault(): void },
  root: HTMLElement | null,
): void {
  // defaultPrevented: a dialog nested inside this one already kept focus in itself.
  if (e.key !== "Tab" || e.defaultPrevented || !root) return;
  // Tab order only: a control taken out of it with tabindex="-1" (menu items, options
  // reached with the arrow keys) is not where Tab goes, so it is not the first or last stop.
  const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.getClientRects().length > 0 && !el.closest("[inert]") && !(Number(el.getAttribute("tabindex")) < 0),
  );
  if (items.length === 0) {
    e.preventDefault();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (e.shiftKey && (active === first || active === root || !root.contains(active))) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && (active === last || !root.contains(active))) {
    e.preventDefault();
    first.focus();
  }
}

/* --------------------------------------------------------- Dialog focus ----- */

/** Focus handling for an aria-modal dialog, as FormModal does it: while `active`, focus
 *  moves into `ref` (the dialog; give it `tabIndex={-1}`) on the next frame unless
 *  something inside already took it (autoFocus), and on close it returns to whatever
 *  was focused when the dialog opened, when that element is still in the document.
 *  Pair it with `onKeyDown={(e) => trapTab(e, ref.current)}` on the dialog. */
export function useDialogFocus(active: boolean, ref: { readonly current: HTMLElement | null }): void {
  useEffect(() => {
    if (!active || typeof document === "undefined") return;
    const opener = document.activeElement as HTMLElement | null;
    const raf = requestAnimationFrame(() => {
      const root = ref.current;
      if (root && !root.contains(document.activeElement)) root.focus({ preventScroll: true });
    });
    return () => {
      cancelAnimationFrame(raf);
      if (opener && opener !== document.body && opener.isConnected && typeof opener.focus === "function") {
        opener.focus({ preventScroll: true });
      }
    };
  }, [active, ref]);
}
