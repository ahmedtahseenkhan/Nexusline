"use client";

import { useEffect, useState, type ReactNode } from "react";

export type FormTab = { id: string; label: string; content: ReactNode; required?: boolean };

type Props = {
  title: string;
  tabs: FormTab[];
  onClose: () => void;
  onSave: () => void;
  saving?: boolean;
  error?: string | null;
  saveLabel?: string;
  wide?: boolean;
  footerLeft?: ReactNode;
};

/** eramba-style tabbed record dialog: header, tab strip, scrollable body, Close/Save footer. */
export default function FormModal({
  title,
  tabs,
  onClose,
  onSave,
  saving,
  error,
  saveLabel = "Save",
  wide,
  footerLeft,
}: Props) {
  const [active, setActive] = useState(tabs[0]?.id);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {tabs.length > 1 && (
          <div className="modal-tabs">
            {tabs.map((t) => (
              <button
                key={t.id}
                className={`modal-tab${active === t.id ? " active" : ""}`}
                onClick={() => setActive(t.id)}
                type="button"
              >
                {t.label}
                {t.required && <span className="req-dot">•</span>}
              </button>
            ))}
          </div>
        )}

        <div className="modal-body">
          {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
          {tabs.map((t) => (
            <div key={t.id} style={{ display: active === t.id ? "block" : "none" }}>
              {t.content}
            </div>
          ))}
        </div>

        <div className="modal-foot">
          {footerLeft && <div className="spacer">{footerLeft}</div>}
          <button className="btn secondary" onClick={onClose} type="button" disabled={saving}>
            Close
          </button>
          <button className="btn" onClick={onSave} type="button" disabled={saving}>
            {saving ? "Saving…" : saveLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
