"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useDebounced, useLatest } from "@/lib/list";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { useFieldLabel, type Option } from "@/components/AsyncSelect";

type Props = {
  /** query the server for matching options (server-limited) */
  search: (q: string) => Promise<Option[]>;
  /** selected items, carrying their labels so chips render without a re-fetch */
  value: Option[];
  onChange: (value: Option[]) => void;
  placeholder?: string;
  /** Accessible name of the search input (default: the surrounding Field label, else the placeholder). */
  ariaLabel?: string;
  /** id of the search input, for an external `<label htmlFor>`. */
  id?: string;
};

/**
 * Server-backed multi-select. Selected values are held as {value,label} so chips
 * render immediately; typing queries the server, so any record in a 100k-row register
 * is linkable — unlike the old MultiSelect which filtered a preloaded, capped array.
 *
 * Keyboard: the search input is a combobox (ArrowUp / ArrowDown move, Enter adds,
 * Backspace on an empty input removes the last chip). Each chip has its own
 * "Remove {label}" button. Esc closes only the list (escape stack, lib/escapeLayer);
 * tabbing away closes it too.
 */
export default function AsyncMultiSelect({ search, value, onChange, placeholder = "Search to add…", ariaLabel, id }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [opts, setOpts] = useState<Option[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDebounced(text, 250);
  const latest = useLatest();
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const selectedIds = new Set(value.map((v) => v.value));
  const uid = useId();
  const listId = `ams-list-${uid}`;
  const optId = (i: number) => `ams-opt-${uid}-${i}`;
  const name = useFieldLabel(boxRef, ariaLabel) ?? placeholder;

  useEffect(() => {
    if (!open) return;
    const n = latest.next();
    setLoading(true);
    search(q)
      .then((r) => latest.isCurrent(n) && (setOpts(r.filter((o) => !selectedIds.has(o.value))), setActive(0)))
      .catch(() => latest.isCurrent(n) && setOpts([]))
      .finally(() => latest.isCurrent(n) && setLoading(false));
  }, [q, open, value.length]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Esc closes the list and nothing under it, wherever focus is.
  useEscapeLayer(open, () => setOpen(false));

  function add(o: Option) {
    onChange([...value, o]);
    setText("");
  }
  function remove(id: string) {
    onChange(value.filter((v) => v.value !== id));
    inputRef.current?.focus({ preventScroll: true });
  }

  const shown = loading ? [] : opts;

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <div className="input" style={{ display: "flex", flexWrap: "wrap", gap: 6, minHeight: 38, alignItems: "center", cursor: "text", padding: 6 }} onClick={() => setOpen(true)}>
        {value.map((v) => (
          <span key={v.value} className="chip">
            {v.label}
            <button
              type="button"
              className="chip-x"
              aria-label={`Remove ${v.label}`}
              title="Remove"
              onClick={(e) => { e.stopPropagation(); remove(v.value); }}
            >
              ✕
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-controls={open ? listId : undefined}
          aria-autocomplete="list"
          aria-activedescendant={open && shown[active] ? optId(active) : undefined}
          aria-label={name}
          style={{ border: "none", outline: "none", flex: "1 1 80px", minWidth: 80, background: "transparent", fontSize: 13.5 }}
          placeholder={value.length ? "" : placeholder}
          value={text}
          onFocus={() => setOpen(true)}
          onChange={(e) => { setText(e.target.value); setOpen(true); }}
          onBlur={(e) => {
            // Tabbing to another control closes the list (a click inside it keeps focus here).
            const to = e.relatedTarget as Node | null;
            if (to && boxRef.current && !boxRef.current.contains(to)) setOpen(false);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((a) => Math.min(shown.length - 1, a + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            else if (e.key === "Enter" && open && shown[active]) { e.preventDefault(); add(shown[active]); }
            else if (e.key === "Backspace" && !text && value.length) remove(value[value.length - 1].value);
            // An open list consumes Esc (preventDefault: the escape stack leaves every other layer open).
            else if (e.key === "Escape" && open) { e.preventDefault(); setOpen(false); }
          }}
        />
      </div>

      {open && (
        <div className="async-menu" role="listbox" id={listId} aria-label={name} aria-multiselectable="true" tabIndex={-1}>
          {loading && <div className="async-opt muted" role="presentation">Searching…</div>}
          {!loading && opts.length === 0 && <div className="async-opt muted" role="presentation">{text ? "No matches" : "Type to search"}</div>}
          {shown.map((o, i) => (
            <div
              key={o.value}
              id={optId(i)}
              role="option"
              aria-selected={false}
              className={`async-opt${i === active ? " active" : ""}`}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => { e.preventDefault(); add(o); }}
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
