"use client";

/* Settings → Start page: the workspace a person lands on after signing in. The default
   follows their line of defence (first line My Work, second line the dashboard, internal
   audit Assurance, board members the Board home); choosing one here overrides it, and
   "Default" goes back. */

import { useEffect, useState } from "react";
import { getWorkspace, setWorkspacePreference, type Workspace } from "@/lib/landing";
import { toast } from "@/lib/feedback";

const LINE: Record<Workspace["line"], string> = {
  first_line: "first line",
  second_line: "second line",
  audit: "internal audit",
  board: "board",
};

export default function StartPageSetting() {
  const [ws, setWs] = useState<Workspace | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getWorkspace().then(setWs).catch(() => setWs(null));
  }, []);

  if (!ws) return null;
  const defaultLabel = ws.available.find((w) => w.key === ws.default)?.label || "My work";

  async function choose(value: string) {
    setBusy(true);
    try {
      setWs(await setWorkspacePreference(value || null));
      toast("Start page saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save your start page", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ marginTop: 16 }}>
      <div className="card-head"><h3>Start page</h3></div>
      <div className="card-pad">
        <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
          Where you land after signing in. Your roles place you in the {ws.is_admin ? "administrators'" : LINE[ws.line]} group,
          whose default is {defaultLabel}.
        </p>
        <label className="label" htmlFor="start-page">Start on</label>
        <select id="start-page" className="select" style={{ maxWidth: 320 }} value={ws.preference || ""} disabled={busy}
          onChange={(e) => choose(e.target.value)}>
          <option value="">Default ({defaultLabel})</option>
          {ws.available.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
        </select>
      </div>
    </div>
  );
}
