"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";

type Issue = { id: string; reference: string; title: string; severity?: string; status?: string };
type Page = { items: Issue[] };

/** The "Issues raised against this record" surface — the connective tissue that lets any
 *  finding/gap be tracked against the record it concerns. Fetches issues by source_id and
 *  lets the user raise a new one inline (stamped with source_type + source_id). */
export default function RecordIssues({
  entityId,
  entityRef,
  sourceType = "self_identified",
}: {
  entityId: string;
  entityRef?: string;
  sourceType?: string;
}) {
  const [issues, setIssues] = useState<Issue[]>([]);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("medium");
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    apiCall<Page>("GET", `/issues?source_id=${entityId}&limit=50`)
      .then((r) => setIssues(r.items))
      .catch(() => setIssues([]));
  }, [entityId]);

  useEffect(() => { load(); }, [load]);

  async function raise() {
    if (!title.trim()) return;
    setSaving(true);
    try {
      await apiCall("POST", "/issues", {
        title: title.trim(),
        severity,
        source_type: sourceType,
        source_id: entityId,
        source_reference: entityRef || "",
      });
      setTitle("");
      setAdding(false);
      load();
      toast("Issue raised");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Failed to raise issue", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
        <strong style={{ fontSize: 13 }}>Issues</strong>
        <button className="btn secondary sm" onClick={() => setAdding((v) => !v)}>
          {adding ? "Cancel" : "Raise issue"}
        </button>
      </div>

      {adding && (
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          <input
            className="input sm"
            style={{ flex: "1 1 200px" }}
            placeholder="Issue title…"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && raise()}
          />
          <select className="select sm" style={{ width: 120 }} value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {["low", "medium", "high", "critical"].map((s) => (
              <option key={s} value={s}>{s[0].toUpperCase() + s.slice(1)}</option>
            ))}
          </select>
          <button className="btn sm" onClick={raise} disabled={saving || !title.trim()}>Add</button>
        </div>
      )}

      {issues.length ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {issues.map((i) => (
            <Link
              key={i.id}
              href={`/issues?id=${i.id}`}
              style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none", color: "inherit", padding: "5px 8px", borderRadius: 6, border: "1px solid var(--border)" }}
            >
              <span className="ref" style={{ fontSize: 12 }}>{i.reference}</span>
              <span style={{ fontSize: 13, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{i.title}</span>
              {i.severity && <span className="chip" style={{ fontSize: 10.5 }}>{i.severity}</span>}
              {i.status && <span className="muted" style={{ fontSize: 11.5 }}>{i.status.replace(/_/g, " ")}</span>}
            </Link>
          ))}
        </div>
      ) : (
        !adding && <span className="muted" style={{ fontSize: 13 }}>No issues raised against this record.</span>
      )}
    </div>
  );
}
