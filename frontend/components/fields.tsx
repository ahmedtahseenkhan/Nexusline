"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type Option = { value: string; label: string; sub?: string };

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
  return (
    <div className="field">
      <label>
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
  const ref = useRef<HTMLDivElement>(null);

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

  function add(v: string) {
    onChange([...value, v]);
    setQ("");
  }
  function remove(v: string) {
    onChange(value.filter((x) => x !== v));
  }

  return (
    <div className="ms" ref={ref}>
      <div className={`ms-control${open ? " open" : ""}`} onClick={() => setOpen(true)}>
        {value.map((v) => {
          const o = byValue.get(v);
          return (
            <span className="chip" key={v}>
              {o?.label ?? v}
              <button type="button" onClick={(e) => { e.stopPropagation(); remove(v); }} aria-label="Remove">
                ✕
              </button>
            </span>
          );
        })}
        <input
          value={q}
          placeholder={value.length ? "" : placeholder}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
        />
      </div>
      {open && (
        <div className="ms-menu">
          {filtered.length === 0 && <div className="ms-empty">No matches</div>}
          {filtered.slice(0, 50).map((o) => (
            <div className="ms-option" key={o.value} onClick={() => add(o.value)}>
              <span>{o.label}</span>
              {o.sub && <span className="o-sub">{o.sub}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
