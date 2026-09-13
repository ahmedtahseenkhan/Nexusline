"use client";

/* Rich text: the editor and the read-only view. No dependencies.

     <RichText value={f.body} onChange={(v) => set("body", v)} />        // editor (forms)
     <RichTextView html={detail.body} />                                  // read-only (record pages)

   Stored rich text is untrusted HTML (nothing on the server cleans it), so every way it
   becomes DOM goes through lib/sanitize (see the policy there):
   - loading a value into the editor (the editor is a live document: an <img onerror>
     set with innerHTML runs, so it is sanitised first);
   - paste and drop (the clipboard's HTML is sanitised; images and files are refused);
   - what the editor emits (onChange receives sanitised HTML, so the next save stores
     clean markup);
   - the read-only view (RichTextView). Never render stored rich text with
     dangerouslySetInnerHTML directly.
   "Insert link" accepts web and email addresses only (www.x.com becomes https://…). */

import {
  forwardRef, useEffect, useMemo, useRef, useSyncExternalStore,
  type ClipboardEvent, type DragEvent, type HTMLAttributes, type ReactNode,
} from "react";
import { useFieldLabel } from "@/components/AsyncSelect";
import { toast } from "@/lib/feedback";
import { linkFromUserInput, plainTextHtml, sanitizeHtml, sanitizePaste } from "@/lib/sanitize";

type Props = {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  /** Accessible name of the editing area (default: the surrounding Field label, else the placeholder). */
  ariaLabel?: string;
  id?: string;
};

type CaretDoc = {
  caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  caretRangeFromPoint?: (x: number, y: number) => Range | null;
};

function ToolButton({ label, onRun, children }: { label: string; onRun: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      className="rt-btn"
      title={label}
      aria-label={label}
      // mousedown keeps the editor's selection; click covers keyboard activation.
      onMouseDown={(e) => {
        e.preventDefault();
        onRun();
      }}
      onClick={(e) => {
        if (e.detail === 0) onRun(); // Enter / Space (a mouse click already ran on mousedown)
      }}
    >
      {children}
    </button>
  );
}

/** Lightweight rich-text editor (contentEditable + execCommand). Emits sanitised HTML. */
export default function RichText({ value, onChange, placeholder = "Write the document content…", ariaLabel, id }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  /** The last HTML this editor reported; when it comes back as `value` it is not reloaded
   *  (that would move the caret). */
  const emitted = useRef<string | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const draggingInside = useRef(false);
  const label = useFieldLabel(wrapRef, ariaLabel) ?? placeholder;

  // Load a value that came from outside (a record opened, a form reset), sanitised.
  useEffect(() => {
    const el = ref.current;
    if (!el || value === emitted.current) return;
    const clean = sanitizeHtml(value || "");
    if (el.innerHTML !== clean) el.innerHTML = clean;
    emitted.current = null;
  }, [value]);

  function emit() {
    const el = ref.current;
    if (!el) return;
    const clean = sanitizeHtml(el.innerHTML);
    emitted.current = clean;
    onChangeRef.current(clean);
  }

  function exec(cmd: string, arg?: string) {
    ref.current?.focus();
    document.execCommand(cmd, false, arg);
    emit();
  }

  function insertLink() {
    const raw = window.prompt("Link address (https://… or an email address)");
    if (raw === null || !raw.trim()) return;
    const url = linkFromUserInput(raw);
    if (!url) {
      toast("Links can only be web addresses (https://…) or email addresses.", "error");
      return;
    }
    exec("createLink", url);
  }

  function insertClean(html: string) {
    ref.current?.focus();
    if (html) document.execCommand("insertHTML", false, html);
    emit();
  }

  function onPaste(e: ClipboardEvent<HTMLDivElement>) {
    e.preventDefault(); // never let the browser insert the clipboard's own markup (or an image)
    insertClean(sanitizePaste({ html: e.clipboardData.getData("text/html"), text: e.clipboardData.getData("text/plain") }));
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    if (draggingInside.current) return; // moving text within the editor: it is already clean
    e.preventDefault();
    const html = sanitizePaste({ html: e.dataTransfer.getData("text/html"), text: e.dataTransfer.getData("text/plain") });
    placeCaret(e.clientX, e.clientY);
    insertClean(html);
  }

  function placeCaret(x: number, y: number) {
    const el = ref.current;
    if (!el) return;
    const d = document as unknown as CaretDoc;
    let range: Range | null = null;
    if (typeof d.caretPositionFromPoint === "function") {
      const pos = d.caretPositionFromPoint(x, y);
      if (pos) {
        range = document.createRange();
        range.setStart(pos.offsetNode, pos.offset);
        range.collapse(true);
      }
    } else if (typeof d.caretRangeFromPoint === "function") {
      range = d.caretRangeFromPoint(x, y);
    }
    el.focus();
    if (range && el.contains(range.startContainer)) {
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
  }

  return (
    <div className="rt" ref={wrapRef}>
      <div className="rt-toolbar" role="toolbar" aria-label="Formatting">
        <ToolButton label="Bold" onRun={() => exec("bold")}><b>B</b></ToolButton>
        <ToolButton label="Italic" onRun={() => exec("italic")}><i>I</i></ToolButton>
        <ToolButton label="Underline" onRun={() => exec("underline")}><u>U</u></ToolButton>
        <span className="rt-sep" aria-hidden="true" />
        <ToolButton label="Heading" onRun={() => exec("formatBlock", "<h2>")}>H2</ToolButton>
        <ToolButton label="Subheading" onRun={() => exec("formatBlock", "<h3>")}>H3</ToolButton>
        <ToolButton label="Paragraph" onRun={() => exec("formatBlock", "<p>")}>¶</ToolButton>
        <span className="rt-sep" aria-hidden="true" />
        <ToolButton label="Bulleted list" onRun={() => exec("insertUnorderedList")}>•</ToolButton>
        <ToolButton label="Numbered list" onRun={() => exec("insertOrderedList")}>1.</ToolButton>
        <span className="rt-sep" aria-hidden="true" />
        <ToolButton label="Insert link" onRun={insertLink}>Link</ToolButton>
        <ToolButton label="Clear formatting" onRun={() => exec("removeFormat")}>Clear</ToolButton>
      </div>
      <div
        ref={ref}
        id={id}
        className="rt-editor"
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline="true"
        aria-label={label}
        data-placeholder={placeholder}
        onInput={emit}
        onPaste={onPaste}
        onDrop={onDrop}
        onDragStart={() => {
          draggingInside.current = true;
        }}
        onDragEnd={() => {
          draggingInside.current = false;
        }}
      />
    </div>
  );
}

const noSubscribe = () => () => {};

type ViewProps = Omit<HTMLAttributes<HTMLDivElement>, "children" | "dangerouslySetInnerHTML"> & {
  /** Stored rich text (untrusted HTML). */
  html: string | null | undefined;
};

/**
 * Stored rich text, read-only and sanitised (lib/sanitize). Server rendering and
 * hydration show the plain-text form (the server has no DOM parser); the formatted
 * form replaces it once mounted, so the two never disagree during hydration.
 */
export const RichTextView = forwardRef<HTMLDivElement, ViewProps>(function RichTextView({ html, className, ...rest }, ref) {
  // false on the server and while hydrating, true in the browser afterwards.
  const inBrowser = useSyncExternalStore(noSubscribe, () => true, () => false);
  const safe = useMemo(() => (inBrowser ? sanitizeHtml(html) : plainTextHtml(html)), [html, inBrowser]);
  return <div ref={ref} {...rest} className={className ? `rt-view ${className}` : "rt-view"} dangerouslySetInnerHTML={{ __html: safe }} />;
});
