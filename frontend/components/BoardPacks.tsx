"use client";

/* Board packs for one committee (Governance → committee drawer).

   Generate builds the pack now — the committee's view of risk, assurance and compliance
   for a period (the fiscal quarter to date unless a period is given), from the same
   figures as the dashboard — and files it as a PDF and a spreadsheet. The list keeps
   every pack generated, by hand or by the scheduler, with its downloads, so the version
   a committee saw is the version on file. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall, downloadBlob } from "@/lib/api";
import { type Page } from "@/lib/list";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { Badge } from "@/components/badges";

type PackFile = { id: string; filename: string; content_type: string; size_bytes: number };

export type BoardPack = {
  id: string;
  committee_id: string | null;
  committee_name: string;
  meeting_id: string | null;
  meeting_title: string;
  meeting_date: string | null;
  title: string;
  period_start: string | null;
  period_end: string | null;
  sections: string[];
  status: string;
  error: string;
  pdf: PackFile | null;
  xlsx: PackFile | null;
  generated_by: string;
  generated_at: string | null;
  created_at: string;
};

type Section = { key: string; title: string };

type MeetingLite = { id: string; reference: string; title: string; meeting_date: string | null; status: string };

type Props = {
  committeeId: string;
  meetings: MeetingLite[];
  /** The committee's automatic generation lead time, or null when packs are made by hand. */
  autoDays: number | null;
};

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

function size(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function BoardPacks({ committeeId, meetings, autoDays }: Props) {
  const { formatDate, formatDateTime } = useFormat();
  const [packs, setPacks] = useState<BoardPack[] | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meetingId, setMeetingId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    apiCall<Page<BoardPack>>("GET", `/board-packs?committee_id=${committeeId}&limit=50`)
      .then((res) => setPacks(res.items))
      .catch((e) => {
        setPacks([]);
        setError(errMsg(e, "Could not load the board packs"));
      });
  }, [committeeId]);

  useEffect(() => {
    setPacks(null);
    setOpen(false);
    load();
  }, [load]);

  useEffect(() => {
    apiCall<Section[]>("GET", "/board-packs/sections")
      .then((rows) => {
        setSections(rows);
        setPicked(new Set(rows.map((s) => s.key)));
      })
      .catch(() => setSections([]));
  }, []);

  // Scheduled meetings soonest first, then the rest newest first.
  const meetingOptions = useMemo(() => {
    const upcoming = meetings.filter((m) => m.status === "scheduled").sort((a, b) => (a.meeting_date || "").localeCompare(b.meeting_date || ""));
    const rest = meetings.filter((m) => m.status !== "scheduled");
    return [...upcoming, ...rest];
  }, [meetings]);

  function flip(key: string) {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  async function generate() {
    if (!picked.size) {
      setError("Choose at least one section.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const pack = await apiCall<BoardPack>("POST", "/board-packs", {
        committee_id: committeeId,
        meeting_id: meetingId || null,
        period_start: from || null,
        period_end: to || null,
        sections: sections.filter((s) => picked.has(s.key)).map((s) => s.key),
      });
      if (pack.status === "ready") toast("Board pack generated");
      else toast(`The pack could not be generated: ${pack.error || "unknown error"}`, "error");
      setOpen(false);
      load();
    } catch (e) {
      setError(errMsg(e, "Could not generate the pack"));
    } finally {
      setBusy(false);
    }
  }

  async function download(pack: BoardPack, kind: "pdf" | "xlsx") {
    const file = kind === "pdf" ? pack.pdf : pack.xlsx;
    try {
      await downloadBlob(`/board-packs/${pack.id}/${kind}`, file?.filename || `board-pack.${kind}`);
    } catch (e) {
      toast(errMsg(e, "Download failed"), "error");
    }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-pad">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong>Board packs</strong>
          {!open && (
            <button type="button" className="btn sm" onClick={() => { setError(null); setOpen(true); }}>
              Generate pack
            </button>
          )}
        </div>
        <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
          Appetite, top risks and their trend, risk movement, control assurance, compliance, issues, incidents, KRIs and
          third parties for a period, from the same figures as the dashboard — kept as a PDF and a spreadsheet.{" "}
          {autoDays
            ? `Generated automatically ${autoDays} day${autoDays === 1 ? "" : "s"} before each scheduled meeting.`
            : "Set automatic generation before each meeting on the committee form (Edit)."}
        </p>

        {open && (
          <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginBottom: 14, display: "grid", gap: 10 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div style={{ flex: "1 1 240px" }}>
                <label className="label" htmlFor="bp-meeting">For meeting</label>
                <select id="bp-meeting" className="select" value={meetingId} onChange={(e) => setMeetingId(e.target.value)}>
                  <option value="">No particular meeting</option>
                  {meetingOptions.map((m) => (
                    <option key={m.id} value={m.id}>
                      {`${m.reference ? m.reference + " — " : ""}${m.title}${m.meeting_date ? ` (${formatDate(m.meeting_date)})` : ""}`}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ width: 160 }}>
                <label className="label" htmlFor="bp-from">Period from</label>
                <input id="bp-from" className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              </div>
              <div style={{ width: 160 }}>
                <label className="label" htmlFor="bp-to">Period to</label>
                <input id="bp-to" className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
              </div>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              Leave the period blank for the financial quarter to date. The pack is filed with the meeting you pick.
            </div>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="label" style={{ marginBottom: 4 }}>Sections</legend>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
                {sections.map((s) => (
                  <label key={s.key} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
                    <input type="checkbox" checked={picked.has(s.key)} onChange={() => flip(s.key)} />
                    {s.title}
                  </label>
                ))}
              </div>
            </fieldset>
            {error && <div className="error">{error}</div>}
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="btn sm" onClick={generate} disabled={busy}>
                {busy ? "Generating…" : "Generate"}
              </button>
              <button type="button" className="btn secondary sm" onClick={() => setOpen(false)} disabled={busy}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {!open && error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Pack</th>
                <th>Period</th>
                <th>Generated</th>
                <th>Files</th>
              </tr>
            </thead>
            <tbody>
              {packs === null && (
                <tr><td colSpan={4}><span className="muted">Loading…</span></td></tr>
              )}
              {packs?.length === 0 && (
                <tr><td colSpan={4}><span className="muted">No board packs yet.</span></td></tr>
              )}
              {packs?.map((p) => (
                <tr key={p.id}>
                  <td>
                    <div className="cell-title">{p.title}</div>
                    {p.meeting_title && (
                      <div className="muted" style={{ fontSize: 12 }}>
                        {p.meeting_title}{p.meeting_date ? ` · ${formatDate(p.meeting_date)}` : ""}
                      </div>
                    )}
                  </td>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>{formatDate(p.period_start)} – {formatDate(p.period_end)}</td>
                  <td className="muted">
                    <div>{formatDateTime(p.generated_at || p.created_at)}</div>
                    <div style={{ fontSize: 12 }}>{p.generated_by || "—"}</div>
                  </td>
                  <td>
                    {p.status === "ready" ? (
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {p.pdf && (
                          <button type="button" className="btn secondary sm" onClick={() => download(p, "pdf")} title={`${p.pdf.filename}, ${size(p.pdf.size_bytes)}`}>
                            PDF
                          </button>
                        )}
                        {p.xlsx && (
                          <button type="button" className="btn secondary sm" onClick={() => download(p, "xlsx")} title={`${p.xlsx.filename}, ${size(p.xlsx.size_bytes)}`}>
                            XLSX
                          </button>
                        )}
                        {!p.pdf && !p.xlsx && <span className="muted">Files removed</span>}
                      </div>
                    ) : (
                      <div>
                        <Badge tone="critical">Failed</Badge>
                        <div className="muted" style={{ fontSize: 12, marginTop: 4, maxWidth: 260 }}>{p.error || "The pack could not be generated."}</div>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
