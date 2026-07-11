"use client";

import { useEffect, useRef, useState } from "react";
import { useDebounced, useLatest } from "@/lib/list";

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
};

/**
 * Server-backed typeahead. Unlike the old Select/MultiSelect (which filtered a
 * preloaded, capped array and so could never reach record #201), this queries the
 * server as the user types, so any record in a 100k-row register is linkable.
 */
export default function AsyncSelect({ search, value, onChange, placeholder = "Search…", selectedLabel, disabled }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [opts, setOpts] = useState<Option[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDebounced(text, 250);
  const latest = useLatest();
  const boxRef = useRef<HTMLDivElement>(null);

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

  function pick(o: Option) {
    onChange(o.value, o);
    setOpen(false);
    setText("");
  }

  const display = value ? selectedLabel || value : "";

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      {!open ? (
        <button
          type="button"
          className="input"
          disabled={disabled}
          style={{ textAlign: "left", display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}
          onClick={() => !disabled && setOpen(true)}
        >
          <span className={display ? "" : "muted"}>{display || placeholder}</span>
          {value && (
            <span
              className="muted"
              onClick={(e) => { e.stopPropagation(); onChange(null, null); }}
              style={{ cursor: "pointer", paddingLeft: 8 }}
              aria-label="Clear"
            >
              ✕
            </span>
          )}
        </button>
      ) : (
        <input
          className="input"
          autoFocus
          placeholder={placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(opts.length - 1, a + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            else if (e.key === "Enter" && opts[active]) { e.preventDefault(); pick(opts[active]); }
            else if (e.key === "Escape") setOpen(false);
          }}
        />
      )}

      {open && (
        <div className="async-menu">
          {loading && <div className="async-opt muted">Searching…</div>}
          {!loading && opts.length === 0 && <div className="async-opt muted">No matches</div>}
          {!loading &&
            opts.map((o, i) => (
              <div
                key={o.value}
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
