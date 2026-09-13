"use client";

/* Comments, files, links and tags for any record.

     <CollabPanel entityType="risk" entityId={r.id} />                                    // classic card
     <CollabPanel entityType="risk" entityId={r.id} title="Discussion & files" frame="rail" />  // dossier rail card

   Quiet by default (record-page-spec §3.5): with nothing on file it is one line — "No
   comments, files, links or tags yet." — and four buttons (Comment, Upload file, Add
   link, Tag). Each opens its input on demand (Upload file opens the file picker
   directly). Groups that have content show their count in the head ("Comments 3",
   "Files 1") with an add link; the comment composer sits under the thread once there
   is at least one comment. Removing items and downloading files work as before. */

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { api, type CollabBundle } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { safeLinkUrl } from "@/lib/sanitize";
import Disclosure from "@/components/record/Disclosure";

function initials(email: string) {
  return (email[0] || "?").toUpperCase();
}
function ago(iso: string) {
  const d = (Date.now() - new Date(iso).getTime()) / 1000;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}
function fmtBytes(n: number) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

type Adding = "comment" | "link" | "tag" | null;

type Props = {
  entityType: string;
  entityId: string;
  /** Card title; default "Collaboration". */
  title?: string;
  /** "card" (default, classic rail) or "rail" (the dossier `.rec-rail-card`). */
  frame?: "card" | "rail";
};

export default function CollabPanel({ entityType, entityId, title = "Collaboration", frame = "card" }: Props) {
  const [bundle, setBundle] = useState<CollabBundle | null>(null);
  const [comment, setComment] = useState("");
  const [newTag, setNewTag] = useState("");
  const [attTitle, setAttTitle] = useState("");
  const [attUrl, setAttUrl] = useState("");
  const [adding, setAdding] = useState<Adding>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const uid = useId();
  const headId = `${uid}-h`;
  const panelId = `${uid}-add`;
  const tagListId = `${uid}-tags`;

  async function load() {
    setBundle(await api.collab(entityType, entityId).catch(() => null));
  }
  useEffect(() => {
    setAdding(null);
    setActionError(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType, entityId]);

  if (!bundle) return null;
  const b = bundle;

  async function guarded(fn: () => Promise<unknown>) {
    setActionError(null);
    try {
      await fn();
      await load();
      return true;
    } catch (e) {
      setActionError(e instanceof Error && e.message ? e.message : "That didn't work");
      return false;
    }
  }

  async function postComment(e: FormEvent, close?: () => void) {
    e.preventDefault();
    if (!comment.trim()) return;
    if (await guarded(() => api.addComment(entityType, entityId, comment))) {
      setComment("");
      close?.();
    }
  }
  async function addTag(e: FormEvent, close: () => void) {
    e.preventDefault();
    if (!newTag.trim()) return;
    if (await guarded(() => api.assignTag(entityType, entityId, { name: newTag.trim() }))) {
      setNewTag("");
      close();
    }
  }
  async function addAttachment(e: FormEvent, close: () => void) {
    e.preventDefault();
    if (!attTitle.trim()) return;
    if (await guarded(() => api.addAttachment(entityType, entityId, { title: attTitle, url: attUrl, kind: "link" }))) {
      setAttTitle("");
      setAttUrl("");
      close();
    }
  }
  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    setUploadError(null);
    setUploading(true);
    try {
      await api.uploadFile(entityType, entityId, file);
      await load();
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const assignedIds = new Set(b.tags.map((t) => t.id));
  const suggestable = b.available_tags.filter((t) => !assignedIds.has(t.id));
  const hasComments = b.comments.length > 0;
  const hasFiles = b.files.length > 0;
  const hasLinks = b.attachments.length > 0;
  const hasTags = b.tags.length > 0;
  const nothing = !hasComments && !hasFiles && !hasLinks && !hasTags;

  function openAdd(kind: Exclude<Adding, null>, el: HTMLElement) {
    triggerRef.current = el;
    setAdding((cur) => (cur === kind ? null : kind));
  }
  const pickFile = () => fileRef.current?.click();

  const addButton = (kind: Exclude<Adding, null>, label: string, className: string) => (
    <button
      type="button"
      className={className}
      aria-expanded={adding === kind}
      aria-controls={panelId}
      onClick={(e) => openAdd(kind, e.currentTarget)}
    >
      {label}
    </button>
  );
  const uploadButton = (className: string, label = "Upload file") => (
    <button type="button" className={className} onClick={pickFile} disabled={uploading} aria-busy={uploading || undefined}>
      {uploading ? "Uploading…" : label}
    </button>
  );

  const addPanel = (
    <Disclosure
      label={adding === "comment" ? "Add a comment" : adding === "link" ? "Add a link" : "Add a tag"}
      hideTrigger
      open={adding !== null && !(adding === "comment" && hasComments)}
      onOpenChange={(v) => !v && setAdding(null)}
      id={panelId}
      triggerRef={triggerRef}
    >
      {(close) =>
        adding === "comment" ? (
          <form onSubmit={(e) => postComment(e, close)} className="row">
            <input className="input" style={{ flex: "1 1 180px" }} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Write a comment…" aria-label="Comment" />
            <button className="btn secondary sm" disabled={!comment.trim()}>Post</button>
            <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
          </form>
        ) : adding === "link" ? (
          <form onSubmit={(e) => addAttachment(e, close)} className="row">
            <input className="input" style={{ flex: "1 1 140px" }} value={attTitle} onChange={(e) => setAttTitle(e.target.value)} placeholder="Title" aria-label="Link title" />
            <input className="input" style={{ flex: "1 1 160px" }} value={attUrl} onChange={(e) => setAttUrl(e.target.value)} placeholder="https://…" aria-label="Link address" />
            <button className="btn secondary sm" disabled={!attTitle.trim()}>Save</button>
            <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
          </form>
        ) : (
          <form onSubmit={(e) => addTag(e, close)} className="row">
            <input className="input" style={{ flex: "1 1 160px", maxWidth: 240 }} list={tagListId} value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder="Add a tag…" aria-label="Tag" />
            <datalist id={tagListId}>
              {suggestable.map((t) => <option key={t.id} value={t.name} />)}
            </datalist>
            <button className="btn secondary sm" disabled={!newTag.trim()}>Add</button>
            <button type="button" className="btn secondary sm" onClick={close}>Cancel</button>
          </form>
        )
      }
    </Disclosure>
  );

  const groupHead = (label: string, count: number, action: ReactNode) => (
    <div className="rec-collab-head">
      <span className="lbl">{label} <span className="n">{count}</span></span>
      {action}
    </div>
  );

  // Buttons for the kinds that have nothing yet (shown under the groups that do).
  const missing: ReactNode[] = [];
  if (!hasComments) missing.push(<span key="c">{addButton("comment", "Comment", "btn secondary sm")}</span>);
  if (!hasFiles) missing.push(<span key="f">{uploadButton("btn secondary sm")}</span>);
  if (!hasLinks) missing.push(<span key="l">{addButton("link", "Add link", "btn secondary sm")}</span>);
  if (!hasTags) missing.push(<span key="t">{addButton("tag", "Tag", "btn secondary sm")}</span>);

  const body = (
    <>
      <input ref={fileRef} type="file" onChange={onUpload} disabled={uploading} hidden />
      {nothing && <p className="rec-empty">No comments, files, links or tags yet.</p>}

      {hasComments && (
        <div className="rec-collab-group">
          {groupHead("Comments", b.comments.length, (
            <button type="button" className="rec-link" onClick={() => composerRef.current?.focus()}>Add comment</button>
          ))}
          <div className="rec-collab-comments">
            {b.comments.map((c) => (
              <div key={c.id} className="rec-collab-comment">
                <span className="avatar" style={{ flexShrink: 0 }} aria-hidden>{initials(c.author_email)}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12 }}>
                    <b>{c.author_email}</b> <span className="muted" title={formatDateTime(c.created_at)}>· {ago(c.created_at)}</span>
                    {c.can_delete && (
                      <button
                        type="button"
                        className="rec-link rec-collab-del"
                        onClick={() => guarded(() => api.deleteComment(c.id))}
                        aria-label={`Delete comment by ${c.author_email}`}
                      >
                        Delete
                      </button>
                    )}
                  </div>
                  <div style={{ fontSize: 13.5, overflowWrap: "anywhere" }}>{c.body}</div>
                </div>
              </div>
            ))}
          </div>
          <form onSubmit={(e) => postComment(e)} className="row" style={{ marginTop: 8 }}>
            <input ref={composerRef} className="input" style={{ flex: "1 1 180px" }} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Write a comment…" aria-label="Write a comment" />
            <button className="btn secondary sm" disabled={!comment.trim()}>Post</button>
          </form>
        </div>
      )}

      {hasFiles && (
        <div className="rec-collab-group">
          {groupHead("Files", b.files.length, uploadButton("rec-link"))}
          <ul className="rec-collab-list">
            {b.files.map((f) => (
              <li key={f.id}>
                <button
                  type="button"
                  className="rec-link"
                  onClick={() => api.downloadFile(f.id, f.filename).catch(() => {})}
                  title={`Download ${f.filename}`}
                >
                  {f.title || f.filename}
                </button>
                <span className="muted">{fmtBytes(f.size_bytes)} · {f.uploaded_by_email}</span>
                {f.can_delete && (
                  <button type="button" className="btn secondary sm" onClick={() => guarded(() => api.deleteFile(f.id))} aria-label={`Remove file ${f.title || f.filename}`}>
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasLinks && (
        <div className="rec-collab-group">
          {groupHead("Links", b.attachments.length, addButton("link", "Add link", "rec-link"))}
          <ul className="rec-collab-list">
            {b.attachments.map((a) => (
              <li key={a.id}>
                {(() => {
                  // A stored javascript: / data: URL would run on click: only http(s) and mailto are links.
                  const href = safeLinkUrl(a.url);
                  if (href) return <a href={href} target="_blank" rel="noopener noreferrer">{a.title}</a>;
                  return (
                    <span>
                      {a.title}
                      {a.url ? <span className="muted"> (not a web address, so not linked)</span> : null}
                    </span>
                  );
                })()}
                <span className="muted">{a.added_by_email}</span>
                <button type="button" className="btn secondary sm" onClick={() => guarded(() => api.deleteAttachment(a.id))} aria-label={`Remove link ${a.title}`}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {hasTags && (
        <div className="rec-collab-group">
          {groupHead("Tags", b.tags.length, addButton("tag", "Add tag", "rec-link"))}
          <div className="rec-collab-tags">
            {b.tags.map((t) => (
              <span
                key={t.id}
                className="rec-collab-tag"
                style={{ background: `${t.color}1a`, color: t.color, borderColor: `${t.color}55` }}
              >
                {t.name}
                <button type="button" onClick={() => guarded(() => api.unassignTag(entityType, entityId, t.id))} aria-label={`Remove tag ${t.name}`}>
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>
      )}

      {missing.length > 0 && <div className="rec-collab-add">{missing}</div>}
      {addPanel}
      {uploadError && <div className="error" style={{ marginTop: 8, fontSize: 12 }}>{uploadError}</div>}
      {actionError && <div className="error" style={{ marginTop: 8, fontSize: 12 }}>{actionError}</div>}
    </>
  );

  const summary = [
    hasComments ? `${b.comments.length} comment${b.comments.length !== 1 ? "s" : ""}` : "",
    hasFiles ? `${b.files.length} file${b.files.length !== 1 ? "s" : ""}` : "",
  ].filter(Boolean).join(" · ");

  if (frame === "rail") {
    return (
      <section className="rec-rail-card rec-collab" aria-labelledby={headId}>
        <header>
          <h3 id={headId}>{title}</h3>
        </header>
        <div className="rec-rail-body">{body}</div>
      </section>
    );
  }

  return (
    <div className="card rec-collab" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3 id={headId}>{title}</h3>
        {summary && <span className="sub">{summary}</span>}
      </div>
      <div className="card-pad">{body}</div>
    </div>
  );
}
