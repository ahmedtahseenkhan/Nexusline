"use client";

/* The committee's member users (Governance → committee drawer). Members receive released
   board packs — in the app and by e-mail — and see the committee's decisions on the board
   home. The free-text membership roll on the committee form stays as the charter states
   it (it may name people outside the system). */

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";
import UserPicker from "@/components/UserPicker";

export type CommitteeMember = { user_id: string; role: string; full_name: string; email: string; is_active: boolean };

const ROLES = [
  { value: "chair", label: "Chair" },
  { value: "secretary", label: "Secretary" },
  { value: "member", label: "Member" },
  { value: "attendee", label: "In attendance" },
];

export default function CommitteeMembers({ committeeId, members, canWrite, onSaved }: {
  committeeId: string;
  members: CommitteeMember[];
  canWrite: boolean;
  onSaved: () => void;
}) {
  const [rows, setRows] = useState<CommitteeMember[]>(members);
  const [adding, setAdding] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(rows.map((r) => [r.user_id, r.role])) !== JSON.stringify(members.map((r) => [r.user_id, r.role]));

  useEffect(() => setRows(members), [members]);

  async function save() {
    setBusy(true);
    try {
      await apiCall("PUT", `/governance/${committeeId}/members`, { members: rows.map((r) => ({ user_id: r.user_id, role: r.role })) });
      toast("Members saved");
      onSaved();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save the members", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-pad">
        <strong>Member users</strong>
        <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
          People in the system who sit on this committee. They receive released board packs and see the committee&apos;s decisions on their board home.
        </p>
        {rows.length === 0 && <p className="muted" style={{ fontSize: 13 }}>No member users yet.</p>}
        {rows.map((r) => (
          <div key={r.user_id} className="activity-item" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 180 }}>
              <div style={{ fontWeight: 600, fontSize: 13.5 }}>{r.full_name || r.email}{!r.is_active && <span className="muted"> (deactivated)</span>}</div>
              {r.full_name && <div className="when">{r.email}</div>}
            </div>
            <select className="select" style={{ width: 150 }} value={r.role} disabled={!canWrite} aria-label={`Role of ${r.full_name || r.email}`}
              onChange={(e) => setRows((cur) => cur.map((x) => (x.user_id === r.user_id ? { ...x, role: e.target.value } : x)))}>
              {ROLES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {canWrite && (
              <button type="button" className="btn secondary sm" onClick={() => setRows((cur) => cur.filter((x) => x.user_id !== r.user_id))}>Remove</button>
            )}
          </div>
        ))}
        {canWrite && (
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 260px", maxWidth: 360 }}>
              <UserPicker
                value={adding}
                placeholder="Add a member…"
                onChange={(id, ref) => {
                  setAdding(null);
                  if (!id || rows.some((x) => x.user_id === id)) return;
                  setRows((cur) => [...cur, { user_id: id, role: "member", full_name: ref?.full_name || "", email: ref?.email || "", is_active: true }]);
                }}
              />
            </div>
            <button type="button" className="btn sm" onClick={save} disabled={busy || !dirty}>{busy ? "Saving…" : "Save members"}</button>
          </div>
        )}
      </div>
    </div>
  );
}
