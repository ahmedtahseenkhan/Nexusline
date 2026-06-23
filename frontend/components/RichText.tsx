"use client";

import { useEffect, useRef } from "react";

/** Lightweight rich-text editor (contentEditable + execCommand). Emits HTML. No deps. */
export default function RichText({
  value,
  onChange,
  placeholder = "Write the document content…",
}: {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // Sync external value in only when it diverges from what's rendered (avoids caret jumps).
  useEffect(() => {
    if (ref.current && ref.current.innerHTML !== value) {
      ref.current.innerHTML = value || "";
    }
  }, [value]);

  function exec(cmd: string, arg?: string) {
    ref.current?.focus();
    document.execCommand(cmd, false, arg);
    if (ref.current) onChange(ref.current.innerHTML);
  }

  function link() {
    const url = window.prompt("Link URL");
    if (url) exec("createLink", url);
  }

  const B = ({ cmd, arg, title, children }: { cmd: string; arg?: string; title: string; children: React.ReactNode }) => (
    <button type="button" className="rt-btn" title={title} onMouseDown={(e) => { e.preventDefault(); exec(cmd, arg); }}>
      {children}
    </button>
  );

  return (
    <div className="rt">
      <div className="rt-toolbar">
        <B cmd="bold" title="Bold"><b>B</b></B>
        <B cmd="italic" title="Italic"><i>I</i></B>
        <B cmd="underline" title="Underline"><u>U</u></B>
        <span className="rt-sep" />
        <B cmd="formatBlock" arg="<h2>" title="Heading">H2</B>
        <B cmd="formatBlock" arg="<h3>" title="Subheading">H3</B>
        <B cmd="formatBlock" arg="<p>" title="Paragraph">¶</B>
        <span className="rt-sep" />
        <B cmd="insertUnorderedList" title="Bulleted list">•</B>
        <B cmd="insertOrderedList" title="Numbered list">1.</B>
        <span className="rt-sep" />
        <button type="button" className="rt-btn" title="Insert link" onMouseDown={(e) => { e.preventDefault(); link(); }}>🔗</button>
        <B cmd="removeFormat" title="Clear formatting">⌫</B>
      </div>
      <div
        ref={ref}
        className="rt-editor"
        contentEditable
        suppressContentEditableWarning
        data-placeholder={placeholder}
        onInput={(e) => onChange((e.target as HTMLDivElement).innerHTML)}
      />
    </div>
  );
}
