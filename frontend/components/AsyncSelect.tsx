"use client";

import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { useDebounced, useLatest } from "@/lib/list";
import { useEscapeLayer } from "@/lib/escapeLayer";

export type Option = { value: string; label: string; sub?: string };

type Props = {
  /** query the server for matching options (already limited server-side) */
  search: (q: string) => Promise<Option[]>;
  value: string | null;
  onChange: (value: string | null, option: Option | null) => void;
  placeholder?: string;
  /** label to show for the current value when the option isn't in the last result set */
  selectedLabel?: string;
  disabled?: boolean;
  /** Accessible name (default: the surrounding Field label, else the placeholder). */
  ariaLabel?: string;
  /** id of the trigger / search input, for an external `<label htmlFor>`. */
  id?: string;
};

/** The text of the `.field` label around `el`. fields.tsx's Field renders a <label> that
 *  is not tied to its control, so pickers and the rich-text editor read it for their
 *  accessible name. */
export function fieldLabelOf(el: Element | null): string {
  const field = el?.closest(".field");
  const lbl = field ? Array.from(field.children).find((c) => c.tagName === "LABEL") : null;
  return (lbl?.textContent ?? "").replace(/\*/g, "").trim();
}

/** `explicit` when given, else the surrounding Field label once mounted. */
export function useFieldLabel(ref: RefObject<Element | null>, explicit?: string): string | undefined {
  const [found, setFound] = useState("");
  useEffect(() => {
    if (!explicit) setFound(fieldLabelOf(ref.current));
  }, [explicit, ref]);
  return explicit || found || undefined;
}

/**
 * Server-backed typeahead. Unlike the old Select/MultiSelect (which filtered a
 * preloaded, capped array and so could never reach record #201), this queries the
 * server as the user types, so any record in a 100k-row register is linkable.
 *
 * Keyboard: the closed control is a button (Enter / Space / ArrowDown open it); the open
 * control is a combobox input with a listbox (ArrowUp / ArrowDown move, Enter picks).
 * Esc closes only the list — it is the top layer of the escape stack (lib/escapeLayer),
 * so an enclosing form, disclosure or record stays open. Tabbing away closes it too.
 */
export default function AsyncSelect({ search, value, onChange, placeholder = "Search…", selectedLabel, disabled, ariaLabel, id }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [opts, setOpts] = useState<Option[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDebounced(text, 250);
  const latest = useLatest();
  const boxRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const refocusTrigger = useRef(false);
  const uid = useId();
  const listId = `as-list-${uid}`;
  const optId = (i: number) => `as-opt-${uid}-${i}`;
  const name = useFieldLabel(boxRef, ariaLabel) ?? placeholder;

  useEffect(() => {
    if (!open) return;
    const n = latest.next();
    setLoading(true);
    search(q)
      .then((r) => {
        if (latest.isCurrent(n)) {
          setOpts(r);
          setActive(0);
        }
      })
      .catch(() => latest.isCurrent(n) && setOpts([]))
      .finally(() => latest.isCurrent(n) && setLoading(false));
  }, [q, open]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Back on the trigger after Esc or a pick (the input it replaced is gone).
  useEffect(() => {
    if (open || !refocusTrigger.current) return;
    refocusTrigger.current = false;
    triggerRef.current?.focus({ preventScroll: true });
  }, [open]);

  function close(refocus: boolean) {
    refocusTrigger.current = refocus;
    setOpen(false);
    setText("");
  }

  // Esc closes the list and nothing under it, wherever focus is.
  useEscapeLayer(open, () => close(true));

  function pick(o: Option) {
    onChange(o.value, o);
    close(true);
  }

  const display = value ? selectedLabel || value : "";
  const shown = loading ? [] : opts;

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      {!open ? (
        <>
          <button
            ref={triggerRef}
            id={id}
            type="button"
            className="input"
            disabled={disabled}
            aria-haspopup="listbox"
            aria-expanded={false}
            aria-label={display ? `${name}: ${display}` : name}
            style={{ textAlign: "left", display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", paddingRight: value ? 34 : undefined }}
            onClick={() => !disabled && setOpen(true)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" && !disabled) {
                e.preventDefault();
                setOpen(true);
              }
            }}
          >
            <span className={display ? "" : "muted"}>{display || placeholder}</span>
          </button>
          {value && !disabled && (
            <button
              type="button"
              className="async-clear"
              aria-label={`Clear ${name}`}
              title="Clear"
              onClick={() => {
                onChange(null, null);
                triggerRef.current?.focus({ preventScroll: true });
              }}
            >
              ✕
            </button>
          )}
        </>
      ) : (
        <input
          id={id}
          className="input"
          autoFocus
          role="combobox"
          aria-expanded={true}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={shown[active] ? optId(active) : undefined}
          aria-label={name}
          placeholder={placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={(e) => {
            // Tabbing to another control closes the list (a click inside it keeps focus here).
            const to = e.relatedTarget as Node | null;
            if (to && boxRef.current && !boxRef.current.contains(to)) close(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(shown.length - 1, a + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            else if (e.key === "Enter" && shown[active]) { e.preventDefault(); pick(shown[active]); }
            // Consumed here (preventDefault): the escape stack then leaves every other layer open.
            else if (e.key === "Escape") { e.preventDefault(); close(true); }
          }}
        />
      )}

      {open && (
        <div className="async-menu" role="listbox" id={listId} aria-label={name} tabIndex={-1}>
          {loading && <div className="async-opt muted" role="presentation">Searching…</div>}
          {!loading && opts.length === 0 && <div className="async-opt muted" role="presentation">No matches</div>}
          {shown.map((o, i) => (
            <div
              key={o.value}
              id={optId(i)}
              role="option"
              aria-selected={i === active}
              className={`async-opt${i === active ? " active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); pick(o); }}
            >
              <span>{o.label}</span>
              {o.sub && <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>{o.sub}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
