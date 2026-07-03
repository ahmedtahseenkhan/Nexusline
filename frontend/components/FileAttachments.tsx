"use client";

import { useEffect, useState } from "react";
import { api, type CollabFile } from "@/lib/api";

function fmtBytes(n: number) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

/** Focused binary file uploader/list for any record, keyed by (entityType, entityId).
 *  Backed by the object-storage endpoints under /collab. Reusable across modules. */
export default function FileAttachments({ entityType, entityId }: { entityType: string; entityId: string }) {
  const [files, setFiles] = useState<CollabFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function load() {
    const bundle = await api.collab(entityType, entityId).catch(() => null);
    setFiles(bundle?.files ?? []);
  }
  useEffect(() => {
    load();
  }, [entityType, entityId]);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    setErr(null);
    setUploading(true);
    try {
      await api.uploadFile(entityType, entityId, file);
      await load();
    } catch (er) {
      setErr(er instanceof Error ? er.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <label className="label" style={{ margin: 0 }}>Uploaded files</label>
        <label className="btn secondary sm" style={{ cursor: uploading ? "wait" : "pointer", margin: 0 }}>
          {uploading ? "Uploading…" : "⤒ Upload file"}
          <input type="file" onChange={onUpload} disabled={uploading} style={{ display: "none" }} />
        </label>
      </div>
      {err && <div className="error" style={{ marginTop: 8, fontSize: 12 }}>{err}</div>}
      <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
        {files.map((f) => (
          <div key={f.id} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <span aria-hidden>🗎</span>
            <button
              onClick={() => api.downloadFile(f.id, f.filename).catch(() => {})}
              style={{ border: "none", background: "none", padding: 0, color: "var(--primary-text, #1d4fd7)", cursor: "pointer", textAlign: "left" }}
              title="Download"
            >
              {f.title || f.filename}
            </button>
            <span className="muted" style={{ fontSize: 11 }}>· {fmtBytes(f.size_bytes)} · {f.uploaded_by_email}</span>
            {f.can_delete && (
              <button
                className="btn secondary sm"
                style={{ marginLeft: "auto" }}
                onClick={async () => { await api.deleteFile(f.id).catch(() => {}); await load(); }}
              >
                Remove
              </button>
            )}
          </div>
        ))}
        {files.length === 0 && (
          <span className="muted" style={{ fontSize: 12.5 }}>No files uploaded yet. Upload the actual artifact (PDF, screenshot, export…).</span>
        )}
      </div>
    </div>
  );
}
