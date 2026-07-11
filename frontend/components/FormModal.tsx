"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { confirmDialog } from "@/lib/feedback";

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

/** eramba-style tabbed record dialog: header, tab strip, scrollable body, Close/Save footer.
 *
 *  Client-side validation is automatic and global: on save it finds any empty
 *  `required` inputs, switches to the tab that contains the first one, highlights the
 *  fields, focuses the first, and shows a plain-language message — all without the
 *  page needing to wire anything. The server's (now readable) validation is the
 *  backstop for anything not caught here. */
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
  const [clientError, setClientError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const dirtyRef = useRef(false);

  /** Close, but guard unsaved edits: any change in the form marks it dirty, and closing
   *  a dirty form prompts before discarding — so a stray Escape/overlay-click can't wipe
   *  a half-completed multi-tab record. */
  const requestClose = useCallback(async () => {
    if (!dirtyRef.current) return onClose();
    if (await confirmDialog({ title: "Discard changes?", message: "Your edits to this form haven't been saved.", confirmLabel: "Discard", danger: true })) {
      onClose();
    }
  }, [onClose]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") requestClose();
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [requestClose]);

  function labelFor(el: Element): string {
    const lbl = el.closest(".field")?.querySelector("label")?.textContent || "";
    return lbl.replace(/\*/g, "").trim() || "This field";
  }

  function handleSave() {
    const root = bodyRef.current;
    if (root) {
      const reqEls = Array.from(
        root.querySelectorAll<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(
          "input[required], textarea[required], select[required]",
        ),
      );
      reqEls.forEach((el) => el.classList.remove("field-invalid"));
      const empty = reqEls.filter((el) => !String(el.value).trim());
      if (empty.length) {
        // Switch to the tab holding the first missing field, then focus it.
        const firstTab = empty[0].closest("[data-tab-id]")?.getAttribute("data-tab-id");
        if (firstTab) setActive(firstTab);
        empty.forEach((el) => el.classList.add("field-invalid"));
        const names = [...new Set(empty.map(labelFor))];
        setClientError(
          `Please fill in the required field${names.length > 1 ? "s" : ""}: ${names.join(", ")}.`,
        );
        setTimeout(() => empty[0].focus(), 0);
        return;
      }
    }
    setClientError(null);
    onSave();
  }

  // Clear a field's error highlight as soon as the user starts fixing it, and mark the
  // form dirty so closing it will prompt before discarding.
  function onBodyInput(e: React.FormEvent) {
    dirtyRef.current = true;
    (e.target as HTMLElement)?.classList?.remove("field-invalid");
  }

  const shownError = clientError || error;

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && requestClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="x" onClick={requestClose} aria-label="Close">✕</button>
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

        <div className="modal-body" ref={bodyRef} onInput={onBodyInput}>
          {shownError && (
            <div className="alert alert-error" role="alert" style={{ marginBottom: 16 }}>
              <span className="alert-ico" aria-hidden>⚠</span>
              <span>{shownError}</span>
            </div>
          )}
          {tabs.map((t) => (
            <div key={t.id} data-tab-id={t.id} style={{ display: active === t.id ? "block" : "none" }}>
              {t.content}
            </div>
          ))}
        </div>

        <div className="modal-foot">
          {footerLeft && <div className="spacer">{footerLeft}</div>}
          <button className="btn secondary" onClick={requestClose} type="button" disabled={saving}>
            Close
          </button>
          <button className="btn" onClick={handleSave} type="button" disabled={saving}>
            {saving ? "Saving…" : saveLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
