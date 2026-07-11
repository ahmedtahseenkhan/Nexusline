"use client";

import { useEffect, useRef, useState } from "react";
import { useDebounced, useLatest } from "@/lib/list";
import { type Option } from "@/components/AsyncSelect";

type Props = {
  /** query the server for matching options (server-limited) */
  search: (q: string) => Promise<Option[]>;
  /** selected items, carrying their labels so chips render without a re-fetch */
  value: Option[];
  onChange: (value: Option[]) => void;
  placeholder?: string;
};

/**
 * Server-backed multi-select. Selected values are held as {value,label} so chips
 * render immediately; typing queries the server, so any record in a 100k-row register
 * is linkable — unlike the old MultiSelect which filtered a preloaded, capped array.
 */
export default function AsyncMultiSelect({ search, value, onChange, placeholder = "Search to add…" }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [opts, setOpts] = useState<Option[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDebounced(text, 250);
  const latest = useLatest();
  const boxRef = useRef<HTMLDivElement>(null);
  const selectedIds = new Set(value.map((v) => v.value));

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

  function add(o: Option) {
    onChange([...value, o]);
    setText("");
  }
  function remove(id: string) {
    onChange(value.filter((v) => v.value !== id));
  }

  return (
    <div ref={boxRef} style={{ position: "relative" }}>
      <div className="input" style={{ display: "flex", flexWrap: "wrap", gap: 6, minHeight: 38, alignItems: "center", cursor: "text", padding: 6 }} onClick={() => setOpen(true)}>
        {value.map((v) => (
          <span key={v.value} className="chip">
            {v.label}
            <span className="chip-x" onClick={(e) => { e.stopPropagation(); remove(v.value); }} aria-label="Remove">✕</span>
          </span>
        ))}
        <input
          style={{ border: "none", outline: "none", flex: "1 1 80px", minWidth: 80, background: "transparent", fontSize: 13.5 }}
          placeholder={value.length ? "" : placeholder}
          value={text}
          onFocus={() => setOpen(true)}
          onChange={(e) => { setText(e.target.value); setOpen(true); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(opts.length - 1, a + 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
            else if (e.key === "Enter" && opts[active]) { e.preventDefault(); add(opts[active]); }
            else if (e.key === "Backspace" && !text && value.length) remove(value[value.length - 1].value);
            else if (e.key === "Escape") setOpen(false);
          }}
        />
      </div>

      {open && (
        <div className="async-menu">
          {loading && <div className="async-opt muted">Searching…</div>}
          {!loading && opts.length === 0 && <div className="async-opt muted">{text ? "No matches" : "Type to search"}</div>}
          {!loading &&
            opts.map((o, i) => (
              <div key={o.value} className={`async-opt${i === active ? " active" : ""}`} onMouseEnter={() => setActive(i)} onMouseDown={(e) => { e.preventDefault(); add(o); }}>
                <span>{o.label}</span>
                {o.sub && <span className="muted" style={{ marginLeft: 8, fontSize: 12 }}>{o.sub}</span>}
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
