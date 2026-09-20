"use client";

import { useEffect, useId, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { useFieldLabel } from "@/components/AsyncSelect";

export type Option = { value: string; label: string; sub?: string };

/* Field's <label> is not tied to its control by `htmlFor` (the control is whatever the
   page passes as children), so without help every input, select and textarea in a form
   was named by its placeholder ("Multi-factor authentication" for Name) or not at all.
   useFieldControlNames gives each control of THIS field (not of a Field nested inside
   it) that has no name of its own — aria-label, aria-labelledby, a <label> — the field
   label: `aria-labelledby` when it is the field's only such control, and
   "{label}: {placeholder}" when the field holds several (Opex / Capex), so they do not
   share one name. Picker triggers (`button.input`, `button[aria-haspopup]`) without a
   name get the label plus their own text. Controls mounted later are named too. */
const FIELD_CONTROLS = 'input:not([type="hidden"]), select, textarea, button.input, button[aria-haspopup], [role="combobox"]';

function useFieldControlNames(ref: RefObject<HTMLElement | null>, labelId: string): void {
  useEffect(() => {
    const root = ref.current;
    if (!root) return;
    let n = 0;
    const apply = () => {
      const label = document.getElementById(labelId);
      const text = (label?.textContent ?? "").replace(/\*/g, "").trim();
      const mine = Array.from(root.querySelectorAll<HTMLElement>(FIELD_CONTROLS)).filter((el) => {
        if (el.closest(".field") !== root) return false;
        if (el.dataset.fieldNamed === labelId) return true; // ours: recompute
        if (el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby")) return false;
        if ((el as HTMLInputElement).labels?.length) return false;
        return true;
      });
      const several = mine.filter((el) => el.tagName !== "BUTTON").length > 1;
      for (const el of mine) {
        el.dataset.fieldNamed = labelId;
        if (el.tagName === "BUTTON") {
          if (!el.id) el.id = `${labelId}-c${++n}`;
          el.setAttribute("aria-labelledby", `${labelId} ${el.id}`);
          continue;
        }
        const ph = el.getAttribute("placeholder")?.trim();
        if (several && ph && text) {
          el.removeAttribute("aria-labelledby");
          el.setAttribute("aria-label", `${text}: ${ph}`);
        } else {
          el.removeAttribute("aria-label");
          el.setAttribute("aria-labelledby", labelId);
        }
      }
    };
    apply();
    if (typeof MutationObserver === "undefined") return;
    const mo = new MutationObserver(apply);
    mo.observe(root, { childList: true, subtree: true });
    return () => mo.disconnect();
  }, [ref, labelId]);
}

export function Field({
  label,
  help,
  required,
  children,
}: {
  label: string;
  help?: string;
  required?: boolean;
  children: ReactNode;
}) {
  const labelId = `fld-${useId().replace(/:/g, "")}`;
  const box = useRef<HTMLDivElement>(null);
  useFieldControlNames(box, labelId);
  return (
    <div className="field" ref={box}>
      <label id={labelId}>
        {label}
        {required && <span className="req">*</span>}
      </label>
      {children}
      {help && <div className="help">{help}</div>}
    </div>
  );
}

export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  required,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  required?: boolean;
}) {
  return (
    <input
      className="input"
      value={value}
      type={type}
      required={required}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function TextArea({
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <textarea
      className="input"
      value={value}
      rows={rows}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export function Select({
  value,
  onChange,
  options,
  placeholder = "Choose one…",
}: {
  value: string;
  onChange: (v: string) => void;
  options: Option[];
  placeholder?: string;
}) {
  return (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function NumberInput({
  value,
  onChange,
  placeholder,
  min,
  max,
  step,
}: {
  value: number | "";
  onChange: (v: number | "") => void;
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <input
      className="input"
      type="number"
      value={value}
      min={min}
      max={max}
      step={step}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
    />
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      {label && <span className="txt">{label}</span>}
    </label>
  );
}

/** Chip-based multi-select with type-ahead search. value/onChange are arrays of option values. */
export function MultiSelect({
  value,
  onChange,
  options,
  placeholder = "Choose one or more…",
}: {
  value: string[];
  onChange: (v: string[]) => void;
  options: Option[];
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const uid = useId();
  const listId = `ms-list-${uid}`;
  const optId = (i: number) => `ms-opt-${uid}-${i}`;
  const name = useFieldLabel(ref) ?? placeholder;
  // Esc closes the open list and nothing under it (the form it sits in stays open).
  useEscapeLayer(open, () => setOpen(false));

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const byValue = useMemo(() => new Map(options.map((o) => [o.value, o])), [options]);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return options.filter(
      (o) =>
        !value.includes(o.value) &&
        (!needle || o.label.toLowerCase().includes(needle) || (o.sub || "").toLowerCase().includes(needle)),
    );
  }, [options, value, q]);

  const shown = filtered.slice(0, 50);
  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, shown.length - 1)));
  }, [shown.length]);
  useEffect(() => {
    if (open) setActive(0);
  }, [open]);

  function add(v: string) {
    onChange([...value, v]);
    setQ("");
  }
  function remove(v: string) {
    onChange(value.filter((x) => x !== v));
    inputRef.current?.focus({ preventScroll: true });
  }

  /* Keyboard: the search input is a combobox (ArrowUp / ArrowDown move, Enter adds,
     Backspace on an empty input removes the last chip, Esc closes only the list). Tabbing
     away closes the list — before, it stayed open behind the focus and took the next Esc,
     so the form around it needed two. */
  return (
    <div
      className="ms"
      ref={ref}
      onBlur={(e) => {
        const to = e.relatedTarget as Node | null;
        if (to && ref.current && !ref.current.contains(to)) setOpen(false);
      }}
    >
      <div className={`ms-control${open ? " open" : ""}`} onClick={() => setOpen(true)}>
        {value.map((v) => {
          const o = byValue.get(v);
          return (
            <span className="chip" key={v}>
              {o?.label ?? v}
              <button type="button" onClick={(e) => { e.stopPropagation(); remove(v); }} aria-label={`Remove ${o?.label ?? v}`}>
                ✕
              </button>
            </span>
          );
        })}
        <input
          ref={inputRef}
          role="combobox"
          aria-label={name}
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={open && shown[active] ? optId(active) : undefined}
          value={q}
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(shown.length - 1, a + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            else if (e.key === "Enter" && open && shown[active]) { e.preventDefault(); add(shown[active].value); }
            else if (e.key === "Backspace" && !q && value.length) remove(value[value.length - 1]);
            // An open list consumes Esc (preventDefault: the escape stack leaves every other layer open).
            else if (e.key === "Escape" && open) { e.preventDefault(); setOpen(false); }
          }}
        />
      </div>
      {open && (
        <div className="ms-menu" role="listbox" id={listId} aria-label={name} aria-multiselectable="true" tabIndex={-1}>
          {shown.length === 0 && <div className="ms-empty" role="presentation">No matches</div>}
          {shown.map((o, i) => (
            <div
              className={`ms-option${i === active ? " cursor" : ""}`}
              key={o.value}
              id={optId(i)}
              role="option"
              aria-selected={false}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => add(o.value)}
            >
              <span>{o.label}</span>
              {o.sub && <span className="o-sub">{o.sub}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
