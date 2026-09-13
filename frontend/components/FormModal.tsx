"use client";

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { confirmDialog } from "@/lib/feedback";
import { trapTab, useEscapeLayer } from "@/lib/escapeLayer";

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
  /** Tab to open on (default the first) — record pages open Edit on the tab a fix names. */
  initialTab?: string;
};

/** eramba-style tabbed record dialog: header, tab strip, scrollable body, Close/Save footer.
 *
 *  Client-side validation is automatic and global: on save it finds any empty
 *  `required` inputs, switches to the tab that contains the first one, highlights the
 *  fields, focuses the first, and shows a plain-language message — all without the
 *  page needing to wire anything. The server's (now readable) validation is the
 *  backstop for anything not caught here.
 *
 *  Keyboard: the dialog is labelled by its title and takes focus on open (unless a
 *  field autofocused); Tab stays inside it; focus returns to the opener on close. Esc
 *  goes through the escape stack (lib/escapeLayer): a picker, menu or confirm opened
 *  inside or on top of the form closes first, and Esc while saving does nothing. */
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
  initialTab,
}: Props) {
  const [active, setActive] = useState(
    initialTab && tabs.some((t) => t.id === initialTab) ? initialTab : tabs[0]?.id,
  );
  const [clientError, setClientError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const dirtyRef = useRef(false);
  const titleId = `fm-title-${useId()}`;

  // Focus: move into the dialog on open (unless a field already took it with autoFocus)
  // and give it back to whatever opened it on close — "Attest…", Edit, a row, …
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const raf = requestAnimationFrame(() => {
      const root = modalRef.current;
      if (root && !root.contains(document.activeElement)) root.focus({ preventScroll: true });
    });
    return () => {
      cancelAnimationFrame(raf);
      if (opener && opener !== document.body && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);

  /** Close, but guard unsaved edits: any change in the form marks it dirty, and closing
   *  a dirty form prompts before discarding — so a stray Escape/overlay-click can't wipe
   *  a half-completed multi-tab record. */
  const requestClose = useCallback(async () => {
    if (!dirtyRef.current) return onClose();
    if (await confirmDialog({ title: "Discard changes?", message: "Your edits to this form haven't been saved.", confirmLabel: "Discard", danger: true })) {
      onClose();
    }
  }, [onClose]);

  // Esc: the top layer of the escape stack while the form is open (pickers, menus and the
  // discard-changes confirm opened from it sit above it). Ignored while saving, like Close.
  useEscapeLayer(true, () => {
    if (!saving) void requestClose();
  });

  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, []);

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
      <div
        ref={modalRef}
        tabIndex={-1}
        className={`modal${wide ? " wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(e) => trapTab(e, modalRef.current)}
      >
        <div className="modal-head">
          <h2 id={titleId}>{title}</h2>
          <button className="x" onClick={requestClose} aria-label={`Close ${title}`} type="button">✕</button>
        </div>

        {tabs.length > 1 && (
          <div className="modal-tabs">
            {tabs.map((t) => (
              <button
                key={t.id}
                className={`modal-tab${active === t.id ? " active" : ""}`}
                onClick={() => setActive(t.id)}
                type="button"
                aria-current={active === t.id ? "true" : undefined}
              >
                {t.label}
                {t.required && <span className="req-dot" aria-hidden="true">•</span>}
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
