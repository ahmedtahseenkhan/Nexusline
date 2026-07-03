"use client";

import { useEffect, useState } from "react";
import { api, type CollabBundle } from "@/lib/api";

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

/** Polymorphic comments + tags + attachments for any record. */
export default function CollabPanel({ entityType, entityId }: { entityType: string; entityId: string }) {
  const [bundle, setBundle] = useState<CollabBundle | null>(null);
  const [comment, setComment] = useState("");
  const [newTag, setNewTag] = useState("");
  const [attTitle, setAttTitle] = useState("");
  const [attUrl, setAttUrl] = useState("");
  const [showAtt, setShowAtt] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  async function load() {
    setBundle(await api.collab(entityType, entityId).catch(() => null));
  }
  useEffect(() => {
    load();
  }, [entityType, entityId]);

  if (!bundle) return null;

  async function postComment(e: React.FormEvent) {
    e.preventDefault();
    if (!comment.trim()) return;
    await api.addComment(entityType, entityId, comment);
    setComment("");
    await load();
  }
  async function addTag(e: React.FormEvent) {
    e.preventDefault();
    if (!newTag.trim()) return;
    await api.assignTag(entityType, entityId, { name: newTag.trim() });
    setNewTag("");
    await load();
  }
  async function addAttachment(e: React.FormEvent) {
    e.preventDefault();
    if (!attTitle.trim()) return;
    await api.addAttachment(entityType, entityId, { title: attTitle, url: attUrl, kind: "link" });
    setAttTitle("");
    setAttUrl("");
    setShowAtt(false);
    await load();
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

  const assignedIds = new Set(bundle.tags.map((t) => t.id));
  const suggestable = bundle.available_tags.filter((t) => !assignedIds.has(t.id));

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3>Collaboration</h3>
        <span className="sub">{bundle.comments.length} comment{bundle.comments.length !== 1 ? "s" : ""}</span>
      </div>
      <div className="card-pad">
        {/* Tags */}
        <div style={{ marginBottom: 16 }}>
          <label className="label">Tags</label>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
            {bundle.tags.map((t) => (
              <span key={t.id} style={{ display: "inline-flex", alignItems: "center", gap: 5, background: `${t.color}1a`, color: t.color, border: `1px solid ${t.color}55`, borderRadius: 99, padding: "2px 9px", fontSize: 12, fontWeight: 600 }}>
                {t.name}
                <button onClick={async () => { await api.unassignTag(entityType, entityId, t.id); await load(); }} style={{ border: "none", background: "none", cursor: "pointer", color: "inherit", fontSize: 13, lineHeight: 1 }} title="Remove">×</button>
              </span>
            ))}
            {bundle.tags.length === 0 && <span className="muted" style={{ fontSize: 12 }}>No tags</span>}
          </div>
          <form onSubmit={addTag} style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <input className="input" style={{ maxWidth: 200 }} list="tag-suggestions" value={newTag} onChange={(e) => setNewTag(e.target.value)} placeholder="Add a tag…" />
            <datalist id="tag-suggestions">
              {suggestable.map((t) => <option key={t.id} value={t.name} />)}
            </datalist>
            <button className="btn secondary sm">Add</button>
          </form>
        </div>

        {/* Attachments */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <label className="label" style={{ margin: 0 }}>Attachments</label>
            <button className="btn secondary sm" onClick={() => setShowAtt((v) => !v)}>{showAtt ? "Cancel" : "+ Link"}</button>
          </div>
          {showAtt && (
            <form onSubmit={addAttachment} style={{ display: "flex", gap: 6, marginTop: 8 }}>
              <input className="input" value={attTitle} onChange={(e) => setAttTitle(e.target.value)} placeholder="Title" />
              <input className="input" value={attUrl} onChange={(e) => setAttUrl(e.target.value)} placeholder="https://…" />
              <button className="btn sm">Save</button>
            </form>
          )}
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            {bundle.attachments.map((a) => (
              <div key={a.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                <span aria-hidden>📎</span>
                {a.url ? <a href={a.url} target="_blank" rel="noreferrer">{a.title}</a> : <span>{a.title}</span>}
                <span className="muted" style={{ fontSize: 11 }}>· {a.added_by_email}</span>
                <button className="btn secondary sm" style={{ marginLeft: "auto" }} onClick={async () => { await api.deleteAttachment(a.id).catch(() => {}); await load(); }}>Remove</button>
              </div>
            ))}
            {bundle.attachments.length === 0 && <span className="muted" style={{ fontSize: 12 }}>No attachments</span>}
          </div>
        </div>

        {/* Uploaded files (binary) */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <label className="label" style={{ margin: 0 }}>Files</label>
            <label className="btn secondary sm" style={{ cursor: uploading ? "wait" : "pointer", margin: 0 }}>
              {uploading ? "Uploading…" : "⤒ Upload"}
              <input type="file" onChange={onUpload} disabled={uploading} style={{ display: "none" }} />
            </label>
          </div>
          {uploadError && <div className="error" style={{ marginTop: 8, fontSize: 12 }}>{uploadError}</div>}
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 6 }}>
            {bundle.files.map((f) => (
              <div key={f.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
                <span aria-hidden>🗎</span>
                <button
                  className="linklike"
                  onClick={() => api.downloadFile(f.id, f.filename).catch(() => {})}
                  style={{ border: "none", background: "none", padding: 0, color: "var(--primary-text, #1d4fd7)", cursor: "pointer", textAlign: "left" }}
                  title="Download"
                >
                  {f.title || f.filename}
                </button>
                <span className="muted" style={{ fontSize: 11 }}>· {fmtBytes(f.size_bytes)} · {f.uploaded_by_email}</span>
                {f.can_delete && (
                  <button className="btn secondary sm" style={{ marginLeft: "auto" }} onClick={async () => { await api.deleteFile(f.id).catch(() => {}); await load(); }}>Remove</button>
                )}
              </div>
            ))}
            {bundle.files.length === 0 && <span className="muted" style={{ fontSize: 12 }}>No files uploaded</span>}
          </div>
        </div>

        {/* Comments */}
        <div>
          <label className="label">Comments</label>
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 10 }}>
            {bundle.comments.map((c) => (
              <div key={c.id} style={{ display: "flex", gap: 10 }}>
                <span className="avatar" style={{ flexShrink: 0 }}>{initials(c.author_email)}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12 }}><b>{c.author_email}</b> <span className="muted">· {ago(c.created_at)}</span>
                    {c.can_delete && <button onClick={async () => { await api.deleteComment(c.id).catch(() => {}); await load(); }} style={{ border: "none", background: "none", cursor: "pointer", color: "var(--muted)", marginLeft: 6, fontSize: 11 }}>delete</button>}
                  </div>
                  <div style={{ fontSize: 13.5 }}>{c.body}</div>
                </div>
              </div>
            ))}
            {bundle.comments.length === 0 && <span className="muted" style={{ fontSize: 12 }}>No comments yet</span>}
          </div>
          <form onSubmit={postComment} style={{ display: "flex", gap: 8 }}>
            <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Write a comment…" />
            <button className="btn sm">Post</button>
          </form>
        </div>
      </div>
    </div>
  );
}
