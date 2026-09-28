"use client";

/* Board packs for one committee (Governance → committee drawer).

   Generate builds the pack now — the committee's view of risk, assurance and compliance
   for a period (the fiscal quarter to date unless a period is given), from the same
   figures as the dashboard — and files it as a PDF and a spreadsheet. A pack for a
   period that has ended takes its position figures from the period snapshot nearest the
   period end, and says so.

   Sign-off: a new pack is a draft. Whoever prepares it writes the commentary for each
   section (it is printed at the top of the section); someone else marks it reviewed and
   releases it — the committee's member users are then notified and e-mailed a link.
   Changing commentary on a reviewed pack sends it back to draft. A released pack is final.

   The committee keeps its own section choice and order; scheduled packs use it. Branding
   (logo, colour, cover title, classification) is set once for the organisation. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall, downloadBlob, uploadMultipart } from "@/lib/api";
import { type Page } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { useTenantSettings } from "@/lib/tenantSettings";
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
  review_state: "draft" | "reviewed" | "released";
  reviewed_by: string;
  reviewed_at: string | null;
  released_by: string;
  released_at: string | null;
  commentary: Record<string, string>;
  basis: { position?: string; snapshot_as_of?: string; reason?: string };
  distribution: { user_id: string; name: string; email: string; emailed: boolean }[];
  can_review: boolean;
  can_release: boolean;
  blocked_reason: string;
  editable: boolean;
};

type Section = { key: string; title: string };

type MeetingLite = { id: string; reference: string; title: string; meeting_date: string | null; status: string };

type Branding = { cover_title: string; primary_colour: string; classification: string; logo_file_id: string | null; logo_filename: string };

type Props = {
  committeeId: string;
  meetings: MeetingLite[];
  /** The committee's automatic generation lead time, or null when packs are made by hand. */
  autoDays: number | null;
  /** The committee's saved section choice and order, or null for every section. */
  savedSections?: string[] | null;
  /** Called after the committee's section choice is saved. */
  onSectionsSaved?: () => void;
};

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

function size(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

const STATE_BADGE: Record<BoardPack["review_state"], { text: string; tone: "medium" | "info" | "low" }> = {
  draft: { text: "Draft", tone: "medium" },
  reviewed: { text: "Reviewed", tone: "info" },
  released: { text: "Released", tone: "low" },
};

/* ------------------------------------------------------------ commentary editor */
function CommentaryEditor({ pack, titles, onSaved, onCancel }: { pack: BoardPack; titles: Record<string, string>; onSaved: (p: BoardPack) => void; onCancel: () => void }) {
  const [text, setText] = useState<Record<string, string>>({ ...pack.commentary });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (pack.review_state === "reviewed" && !(await confirmDialog({
      title: "Send the pack back to draft?",
      message: "This pack has been reviewed. Changing its commentary returns it to draft, and it must be reviewed again before release.",
      confirmLabel: "Save and return to draft",
    }))) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await apiCall<BoardPack>("PUT", `/board-packs/${pack.id}/commentary`, { commentary: text });
      toast("Commentary saved; the PDF and spreadsheet now carry it");
      onSaved(saved);
    } catch (e) {
      setError(errMsg(e, "Could not save the commentary"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12, margin: "8px 0", display: "grid", gap: 8 }}>
      <div className="muted" style={{ fontSize: 12.5 }}>
        Write what the committee should take from each section. It is printed at the top of the section; leave a section blank to print none.
      </div>
      {pack.sections.map((key) => (
        <div key={key}>
          <label className="label" htmlFor={`c-${pack.id}-${key}`} style={{ marginTop: 4 }}>{titles[key] || key}</label>
          <textarea id={`c-${pack.id}-${key}`} className="input" rows={3} maxLength={6000} value={text[key] || ""}
            onChange={(e) => setText((t) => ({ ...t, [key]: e.target.value }))} style={{ height: "auto", minHeight: 64 }} />
        </div>
      ))}
      {error && <div className="error">{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="button" className="btn sm" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save commentary"}</button>
        <button type="button" className="btn secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- section order */
function SectionOrder({ committeeId, all, saved, onSaved, onClose }: { committeeId: string; all: Section[]; saved: string[] | null; onSaved?: () => void; onClose: () => void }) {
  const [order, setOrder] = useState<string[]>(() => {
    const chosen = saved && saved.length ? saved : all.map((s) => s.key);
    return [...chosen, ...all.map((s) => s.key).filter((k) => !chosen.includes(k))];
  });
  const [on, setOn] = useState<Set<string>>(new Set(saved && saved.length ? saved : all.map((s) => s.key)));
  const [busy, setBusy] = useState(false);
  const title = (k: string) => all.find((s) => s.key === k)?.title || k;

  function move(i: number, d: -1 | 1) {
    setOrder((o) => {
      const j = i + d;
      if (j < 0 || j >= o.length) return o;
      const next = [...o];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  }

  async function save(reset = false) {
    const chosen = order.filter((k) => on.has(k));
    if (!reset && !chosen.length) {
      toast("Choose at least one section", "error");
      return;
    }
    setBusy(true);
    try {
      await apiCall("PATCH", `/governance/${committeeId}`, { board_pack_sections: reset ? null : chosen });
      toast(reset ? "This committee's packs carry every section again" : "Section choice saved for this committee");
      onSaved?.();
      onClose();
    } catch (e) {
      toast(errMsg(e, "Could not save the sections"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginBottom: 14 }}>
      <div className="muted" style={{ fontSize: 12.5, marginBottom: 8 }}>
        The sections this committee&apos;s packs carry, in the order it reads them. Packs generated for it — by hand or by the scheduler — use this.
      </div>
      <ol style={{ margin: 0, paddingLeft: 20, display: "grid", gap: 4 }}>
        {order.map((k, i) => (
          <li key={k} style={{ fontSize: 13 }}>
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
              <label style={{ display: "flex", gap: 6, alignItems: "center", minWidth: 220, cursor: "pointer" }}>
                <input type="checkbox" checked={on.has(k)} onChange={() => setOn((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; })} />
                {title(k)}
              </label>
              <button type="button" className="btn secondary sm" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${title(k)} up`}>↑</button>
              <button type="button" className="btn secondary sm" onClick={() => move(i, 1)} disabled={i === order.length - 1} aria-label={`Move ${title(k)} down`}>↓</button>
            </span>
          </li>
        ))}
      </ol>
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
        <button type="button" className="btn sm" onClick={() => save(false)} disabled={busy}>Save for this committee</button>
        <button type="button" className="btn secondary sm" onClick={() => save(true)} disabled={busy}>Use every section</button>
        <button type="button" className="btn secondary sm" onClick={onClose} disabled={busy}>Cancel</button>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------- branding */
export function BoardPackBrandingForm({ onClose }: { onClose: () => void }) {
  const [b, setB] = useState<Branding | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiCall<Branding>("GET", "/board-pack-branding").then(setB).catch(() => setB(null));
  }, []);

  if (!b) return <div className="muted" style={{ fontSize: 13, marginBottom: 12 }}>Loading branding…</div>;

  async function save(extra: Record<string, unknown> = {}) {
    if (!b) return;
    setBusy(true);
    try {
      setB(await apiCall<Branding>("PUT", "/board-pack-branding", {
        cover_title: b.cover_title, primary_colour: b.primary_colour, classification: b.classification, ...extra,
      }));
      toast("Branding saved; it applies to packs generated from now on");
    } catch (e) {
      toast(errMsg(e, "Could not save the branding"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      setB(await uploadMultipart<Branding>("/board-pack-branding/logo", file));
      toast("Logo uploaded");
    } catch (e) {
      toast(errMsg(e, "Could not upload the logo"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 12, marginBottom: 14 }}>
      <div className="muted" style={{ fontSize: 12.5 }}>How every board pack of the organisation looks. Packs already released keep the look they were released with.</div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
        <div style={{ flex: "1 1 220px" }}>
          <label className="label" htmlFor="br-title">Cover title</label>
          <input id="br-title" className="input" maxLength={120} value={b.cover_title} placeholder="e.g. Board Risk Management Committee" onChange={(e) => setB({ ...b, cover_title: e.target.value })} />
        </div>
        <div style={{ width: 150 }}>
          <label className="label" htmlFor="br-colour">Primary colour</label>
          <input id="br-colour" className="input" type="color" value={b.primary_colour || "#1d4fd7"} onChange={(e) => setB({ ...b, primary_colour: e.target.value })} />
        </div>
        <div style={{ flex: "1 1 180px" }}>
          <label className="label" htmlFor="br-class">Classification on every page</label>
          <input id="br-class" className="input" maxLength={60} value={b.classification} onChange={(e) => setB({ ...b, classification: e.target.value })} />
        </div>
      </div>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
        <span style={{ fontSize: 13 }}>Logo: {b.logo_filename || <span className="muted">none</span>}</span>
        <label className="btn secondary sm" style={{ cursor: "pointer" }}>
          Upload PNG or JPEG
          <input type="file" accept="image/png,image/jpeg" hidden onChange={(e) => upload(e.target.files?.[0])} />
        </label>
        {b.logo_file_id && <button type="button" className="btn secondary sm" onClick={() => save({ remove_logo: true })} disabled={busy}>Remove logo</button>}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button type="button" className="btn sm" onClick={() => save()} disabled={busy}>Save branding</button>
        <button type="button" className="btn secondary sm" onClick={onClose} disabled={busy}>Close</button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------ list */
export default function BoardPacks({ committeeId, meetings, autoDays, savedSections = null, onSectionsSaved }: Props) {
  const { formatDate, formatDateTime } = useFormat();
  const { permissions } = useTenantSettings();
  const canWrite = permissions.includes("governance:write");
  const canBrand = permissions.includes("settings:manage");
  const [packs, setPacks] = useState<BoardPack[] | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [open, setOpen] = useState(false);
  const [panel, setPanel] = useState<"none" | "sections" | "branding">("none");
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [meetingId, setMeetingId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const titles = useMemo(() => Object.fromEntries(sections.map((s) => [s.key, s.title])), [sections]);
  /** Sections in the committee's saved order, then the rest. */
  const ordered = useMemo(() => {
    if (!savedSections?.length) return sections;
    const first = savedSections.map((k) => sections.find((s) => s.key === k)).filter((s): s is Section => !!s);
    return [...first, ...sections.filter((s) => !savedSections.includes(s.key))];
  }, [sections, savedSections]);

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
    setPanel("none");
    load();
  }, [load]);

  useEffect(() => {
    apiCall<Section[]>("GET", "/board-packs/sections").then(setSections).catch(() => setSections([]));
  }, []);

  useEffect(() => {
    setPicked(new Set(savedSections?.length ? savedSections : sections.map((s) => s.key)));
  }, [sections, savedSections]);

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

  function replace(p: BoardPack) {
    setPacks((cur) => (cur ? cur.map((x) => (x.id === p.id ? p : x)) : cur));
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
        sections: ordered.filter((s) => picked.has(s.key)).map((s) => s.key),
      });
      if (pack.status === "ready") toast("Draft board pack generated. Add commentary, then have it reviewed and released.");
      else toast(`The pack could not be generated: ${pack.error || "unknown error"}`, "error");
      setOpen(false);
      load();
    } catch (e) {
      setError(errMsg(e, "Could not generate the pack"));
    } finally {
      setBusy(false);
    }
  }

  async function act(pack: BoardPack, action: "review" | "return" | "release") {
    const members = "the committee's member users";
    const ok = await confirmDialog(
      action === "review"
        ? { title: "Mark this pack reviewed?", message: "You confirm the figures and commentary are ready for the committee. Someone may then release it.", confirmLabel: "Mark reviewed" }
        : action === "return"
          ? { title: "Return this pack to draft?", message: "It will need to be reviewed again before release.", confirmLabel: "Return to draft" }
          : { title: "Release this pack?", message: `The final PDF and spreadsheet are filed and ${members} are notified and e-mailed a link. A released pack cannot be changed.`, confirmLabel: "Release" },
    );
    if (!ok) return;
    setActing(pack.id);
    try {
      const updated = await apiCall<BoardPack>("POST", `/board-packs/${pack.id}/${action}`, action === "release" ? undefined : { note: "" });
      replace(updated);
      toast(action === "release" ? `Released to ${updated.distribution.length} member${updated.distribution.length === 1 ? "" : "s"}` : action === "review" ? "Marked reviewed" : "Returned to draft");
    } catch (e) {
      toast(errMsg(e, "That didn't work"), "error");
    } finally {
      setActing(null);
    }
  }

  /** A failed pack is built again with the same meeting, period and sections; the new
      pack replaces the failed one. */
  async function regenerate(pack: BoardPack) {
    setActing(pack.id);
    try {
      const fresh = await apiCall<BoardPack>("POST", `/board-packs/${pack.id}/regenerate`);
      if (fresh.status === "ready") toast("Draft board pack generated.");
      else toast(`The pack still could not be generated: ${fresh.error || "unknown error"}`, "error");
      load();
    } catch (e) {
      toast(errMsg(e, "Could not generate the pack"), "error");
    } finally {
      setActing(null);
    }
  }

  async function remove(pack: BoardPack) {
    const failed = pack.status !== "ready";
    const ok = await confirmDialog({
      title: failed ? "Delete this failed pack?" : "Delete this draft pack?",
      message: failed
        ? "It has no files; only the entry is removed. The failure stays in the activity trail."
        : "The draft's PDF, spreadsheet and commentary are deleted. The activity trail keeps a record that it existed.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    setActing(pack.id);
    try {
      await apiCall<void>("DELETE", `/board-packs/${pack.id}`);
      setPacks((cur) => (cur ? cur.filter((x) => x.id !== pack.id) : cur));
      toast("Board pack deleted");
    } catch (e) {
      toast(errMsg(e, "Could not delete the pack"), "error");
    } finally {
      setActing(null);
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

  function basisText(p: BoardPack): string {
    if (p.basis?.position === "snapshot" && p.basis.snapshot_as_of) return `Position figures from the snapshot of ${formatDate(p.basis.snapshot_as_of)}`;
    if (p.basis?.reason === "no_snapshot") return "No snapshot near the period end: position figures as at generation";
    return "";
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="card-pad">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong>Board packs</strong>
          {canWrite && !open && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <button type="button" className="btn secondary sm" onClick={() => setPanel(panel === "sections" ? "none" : "sections")}>Sections and order</button>
              {canBrand && <button type="button" className="btn secondary sm" onClick={() => setPanel(panel === "branding" ? "none" : "branding")}>Branding</button>}
              <button type="button" className="btn sm" onClick={() => { setError(null); setPanel("none"); setOpen(true); }}>Generate pack</button>
            </div>
          )}
        </div>
        <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
          Appetite with its heat map and quarterly trend, top risks, movement, control assurance, compliance, issues,
          incidents, KRIs with their readings and third parties, from the same figures as the dashboard. A pack starts as a
          draft; someone other than its preparers reviews and releases it to the committee&apos;s members.{" "}
          {savedSections?.length ? `This committee's packs carry ${savedSections.length} section${savedSections.length === 1 ? "" : "s"} in its own order. ` : ""}
          {autoDays
            ? `A draft is generated automatically ${autoDays} day${autoDays === 1 ? "" : "s"} before each scheduled meeting.`
            : "Set automatic generation before each meeting on the committee form (Edit)."}
        </p>

        {panel === "sections" && sections.length > 0 && (
          <SectionOrder committeeId={committeeId} all={sections} saved={savedSections} onSaved={onSectionsSaved} onClose={() => setPanel("none")} />
        )}
        {panel === "branding" && <BoardPackBrandingForm onClose={() => setPanel("none")} />}

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
              Leave the period blank for the financial quarter to date. For a period that has ended, position figures come from the
              period snapshot nearest its end. The pack is filed with the meeting you pick.
            </div>
            <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
              <legend className="label" style={{ marginBottom: 4 }}>Sections{savedSections?.length ? " (in this committee's order)" : ""}</legend>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 16px" }}>
                {ordered.map((s) => (
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
                {busy ? "Generating…" : "Generate draft"}
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
                <th>Sign-off</th>
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
                  <td style={{ minWidth: 240 }}>
                    <div className="cell-title">{p.title}</div>
                    {p.meeting_title && (
                      <div className="muted" style={{ fontSize: 12 }}>
                        {p.meeting_title}{p.meeting_date ? ` · ${formatDate(p.meeting_date)}` : ""}
                      </div>
                    )}
                    <div className="muted" style={{ fontSize: 12 }}>
                      Generated {formatDateTime(p.generated_at || p.created_at)} by {p.generated_by || "—"}
                    </div>
                    {basisText(p) && <div className="muted" style={{ fontSize: 12 }}>{basisText(p)}</div>}
                    {Object.keys(p.commentary || {}).length > 0 && (
                      <div className="muted" style={{ fontSize: 12 }}>Commentary on {Object.keys(p.commentary).map((k) => titles[k] || k).join(", ")}</div>
                    )}
                    {editing === p.id && (
                      <CommentaryEditor pack={p} titles={titles} onCancel={() => setEditing(null)} onSaved={(saved) => { replace(saved); setEditing(null); }} />
                    )}
                  </td>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>{formatDate(p.period_start)} – {formatDate(p.period_end)}</td>
                  <td style={{ minWidth: 200 }}>
                    {p.status === "ready" ? (
                      <>
                        <Badge tone={STATE_BADGE[p.review_state]?.tone || "neutral"}>{STATE_BADGE[p.review_state]?.text || p.review_state}</Badge>
                        {p.reviewed_by && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Reviewed by {p.reviewed_by}{p.reviewed_at ? `, ${formatDate(p.reviewed_at)}` : ""}</div>}
                        {p.released_by && <div className="muted" style={{ fontSize: 12 }}>Released by {p.released_by}{p.released_at ? `, ${formatDate(p.released_at)}` : ""}</div>}
                        {p.review_state === "released" && p.distribution.length > 0 && (
                          <div className="muted" style={{ fontSize: 12 }} title={p.distribution.map((d) => `${d.name}${d.emailed ? " (e-mailed)" : ""}`).join(", ")}>
                            Sent to {p.distribution.length} member{p.distribution.length === 1 ? "" : "s"}
                          </div>
                        )}
                        {p.review_state === "released" && p.distribution.length === 0 && p.released_at && (
                          <div className="muted" style={{ fontSize: 12 }}>No member users to notify</div>
                        )}
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                          {canWrite && p.editable && editing !== p.id && (
                            <button type="button" className="btn secondary sm" onClick={() => setEditing(p.id)}>Commentary</button>
                          )}
                          {p.can_review && <button type="button" className="btn sm" disabled={acting === p.id} onClick={() => act(p, "review")}>Mark reviewed</button>}
                          {p.review_state === "reviewed" && p.can_release && <button type="button" className="btn sm" disabled={acting === p.id} onClick={() => act(p, "release")}>Release</button>}
                          {p.review_state === "reviewed" && permissions.includes("boardpack:release") && (
                            <button type="button" className="btn secondary sm" disabled={acting === p.id} onClick={() => act(p, "return")}>Return to draft</button>
                          )}
                          {canWrite && p.review_state === "draft" && (
                            <button type="button" className="btn secondary sm" disabled={acting === p.id} onClick={() => remove(p)}>Delete draft</button>
                          )}
                        </div>
                        {p.review_state !== "released" && p.blocked_reason && !p.can_review && !p.can_release && (
                          <div className="muted" style={{ fontSize: 12, marginTop: 4, maxWidth: 260 }}>{p.blocked_reason}</div>
                        )}
                      </>
                    ) : (
                      <div>
                        <Badge tone="critical">Failed</Badge>
                        <div className="muted" style={{ fontSize: 12, marginTop: 4, maxWidth: 260 }}>{p.error || "The pack could not be generated."}</div>
                        {canWrite && (
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 }}>
                            <button type="button" className="btn sm" disabled={acting === p.id} onClick={() => regenerate(p)}>
                              {acting === p.id ? "Generating…" : "Try again"}
                            </button>
                            <button type="button" className="btn secondary sm" disabled={acting === p.id} onClick={() => remove(p)}>Delete</button>
                          </div>
                        )}
                      </div>
                    )}
                  </td>
                  <td>
                    {p.status === "ready" && (
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
