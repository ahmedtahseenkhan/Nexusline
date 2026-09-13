"use client";

/* Accessible names on record pages (record-page-spec v1.1 decision 3).

   1. Per-row actions say which row they act on. The visible text stays the verb; the
      accessible name is "{Verb} {row label}", so a screen reader's button list reads
      "Edit SRV-01 Core banking host, Unlink SRV-01 Core banking host" instead of
      "Edit, Unlink, Edit, Unlink":

        <button className="rec-link" {...rowAction("Unlink", rowLabel(d.reference, d.name))} onClick={…}>Unlink</button>

      Verbs in use: Edit, Unlink, Remove, Delete, Open, Confirm, Download, Review.

   2. Search inputs in link forms are labelled. Wrap the picker:

        <LabelledSearch label="IT asset">
          <AsyncSelect search={searchItAssets} … placeholder="Search IT assets…" />
        </LabelledSearch>

      It renders a real label (visible by default, `hideLabel` for screen readers only)
      the way a form Field does, so every picker names itself from it: the child gets
      `ariaLabel={label}` (AsyncSelect / AsyncMultiSelect / UserPicker take it, and they
      also read a surrounding `.field > label`), and any input, select, textarea or
      combobox trigger inside that still has no name — including ones the picker mounts
      later — is pointed at the label with `aria-labelledby`. A placeholder is never the
      name. */

import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from "react";
import { rowActionName } from "@/lib/record/text";

export { rowActionName, rowLabel } from "@/lib/record/text";

/** Props for a per-row action button: `{ "aria-label": "Unlink SRV-01 Core banking host" }`. */
export function rowAction(verb: string, label: string | null | undefined): { "aria-label": string } {
  return { "aria-label": rowActionName(verb, label) };
}

const CONTROLS = 'input:not([type="hidden"]), select, textarea, button.input, button[aria-haspopup], [role="combobox"]';

/** Point every unnamed input / select / textarea inside `ref` at `labelId`, and every
 *  unnamed picker trigger (`button.input`, `[aria-haspopup]`) at the label plus its own
 *  text — now and whenever the subtree changes. Controls that already have a name of
 *  their own (aria-label, aria-labelledby, a <label for>) and ordinary buttons ("Clear",
 *  "Remove") are left alone. */
export function useLabelledControls(ref: RefObject<HTMLElement | null>, labelId: string): void {
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    let n = 0;
    const apply = () => {
      root.querySelectorAll<HTMLElement>(CONTROLS).forEach((el) => {
        if (el.dataset.recLabelled === labelId) return;
        if (el.hasAttribute("aria-label")) return;
        if (el.hasAttribute("aria-labelledby") && el.dataset.recLabelled === undefined) return;
        if ((el as HTMLInputElement).labels?.length) return;
        if (el.tagName === "BUTTON") {
          if (!el.id) el.id = `${labelId}-c${++n}`;
          el.setAttribute("aria-labelledby", `${labelId} ${el.id}`);
        } else {
          el.setAttribute("aria-labelledby", labelId);
        }
        el.dataset.recLabelled = labelId;
      });
    };
    apply();
    if (typeof MutationObserver === "undefined") return;
    const mo = new MutationObserver(apply);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [ref, labelId]);
}

type LabelledSearchProps = {
  /** The field's name: "IT asset", "Information asset", "Owner (optional)". */
  label: string;
  /** Keep the label for screen readers only (a compact inline form). */
  hideLabel?: boolean;
  /** Default "label" (the form label style). */
  labelClassName?: string;
  className?: string;
  children: ReactNode;
};

/** A picker with a real label. See the file header. */
export default function LabelledSearch({ label, hideLabel, labelClassName = "label", className, children }: LabelledSearchProps) {
  const labelId = `lbl-${useId().replace(/:/g, "")}`;
  const box = useRef<HTMLDivElement>(null);
  useLabelledControls(box, labelId);
  // Name a picker component explicitly; DOM children are labelled by the effect instead.
  const child =
    isValidElement(children) && typeof children.type !== "string" && (children.props as { ariaLabel?: string }).ariaLabel === undefined
      ? cloneElement(children as ReactElement<{ ariaLabel?: string }>, { ariaLabel: label })
      : children;
  return (
    <div className={`field rec-labelled${className ? ` ${className}` : ""}`}>
      <label id={labelId} className={hideLabel ? "sr-only" : labelClassName}>
        {label}
      </label>
      <div ref={box}>{child}</div>
    </div>
  );
}

export { LabelledSearch };
