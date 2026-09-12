"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import type { UserRef } from "@/lib/masterData";
import { titleCase } from "@/lib/text";
import UserPicker from "@/components/UserPicker";

type Issue = {
  id: string;
  reference: string;
  title: string;
  severity?: string;
  status?: string;
  owner?: string;
  owner_ref?: UserRef | null;
  due_date?: string | null;
  is_overdue?: boolean;
};
type Page = { items: Issue[] };

/** The "Issues raised against this record" surface — the connective tissue that lets any
 *  finding/gap be tracked against the record it concerns. Fetches issues by source_id and
 *  lets the user raise a new one inline (stamped with source_type + source_id), with an
 *  optional owner picked from the user directory. */
export default function RecordIssues({
  entityId,
  entityRef,
  sourceType = "self_identified",
}: {
  entityId: string;
  entityRef?: string;
  sourceType?: string;
}) {
  const { formatDate } = useFormat();
  const [issues, setIssues] = useState<Issue[]>([]);
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("medium");
  const [ownerId, setOwnerId] = useState<string | null>(null);
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
        owner_id: ownerId,
      });
      setTitle("");
      setOwnerId(null);
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
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap", alignItems: "flex-start" }}>
          <input
            className="input sm"
            style={{ flex: "1 1 200px" }}
            placeholder="Issue title…"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && raise()}
            aria-label="Issue title"
          />
          <select className="select sm" style={{ width: 120 }} value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Severity">
            {["low", "medium", "high", "critical"].map((s) => (
              <option key={s} value={s}>{titleCase(s)}</option>
            ))}
          </select>
          <div style={{ flex: "0 1 200px", minWidth: 160 }}>
            <UserPicker value={ownerId} onChange={(id) => setOwnerId(id)} placeholder="Owner (optional)…" />
          </div>
          <button className="btn sm" onClick={raise} disabled={saving || !title.trim()}>Add</button>
        </div>
      )}

      {issues.length ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {issues.map((i) => {
            const owner = i.owner_ref?.full_name || i.owner_ref?.email || i.owner || "";
            return (
              <Link
                key={i.id}
                href={`/issues?id=${i.id}`}
                style={{ display: "flex", alignItems: "center", gap: 8, textDecoration: "none", color: "inherit", padding: "5px 8px", borderRadius: 6, border: "1px solid var(--border)" }}
              >
                <span className="ref" style={{ fontSize: 12 }}>{i.reference}</span>
                <span style={{ fontSize: 13, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{i.title}</span>
                {owner && <span className="muted" style={{ fontSize: 11.5 }}>{owner}</span>}
                {i.due_date && (
                  <span className="muted" style={{ fontSize: 11.5, color: i.is_overdue ? "var(--danger, #c0392b)" : undefined }}>
                    {i.is_overdue ? "Overdue · " : "Due "}{formatDate(i.due_date)}
                  </span>
                )}
                {i.severity && <span className="chip" style={{ fontSize: 10.5 }}>{titleCase(i.severity)}</span>}
                {i.status && <span className="muted" style={{ fontSize: 11.5 }}>{titleCase(i.status)}</span>}
              </Link>
            );
          })}
        </div>
      ) : (
        !adding && <span className="muted" style={{ fontSize: 13 }}>No issues raised against this record.</span>
      )}
    </div>
  );
}
