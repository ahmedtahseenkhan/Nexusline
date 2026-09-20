"use client";

/* Key Risk Indicator detail panels (phase 2, F-14) for the KRI drawer on
   /operational-risk:

     <KriBand kri={kri} />                          where the value sits on a within-range band
     <KriEscalations kri={kri} onChanged={reload} /> who is told at amber / red, and what they do
     <KriFeed kri={kri} onChanged={reload} />        the integration token (shown once)

   Rules live on the server (api/v1/operational_risk.py); these only display and call it. */

import { useEffect, useState } from "react";
import { api, type KeyRiskIndicator, type KriEscalation, type KriFeedToken } from "@/lib/api";
import UserPicker, { UserName } from "@/components/UserPicker";
import { Badge } from "@/components/badges";
import { confirmDialog, toast } from "@/lib/feedback";

const API_ORIGIN = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Kri = KeyRiskIndicator & { id: string };

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

/** A number as a KRI shows it (thousands separators, no trailing zeros). */
export const kriNum = (n: number | string | null | undefined) =>
  n == null || n === "" ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 4 });

const withUnit = (n: number | string | null | undefined, unit?: string) => `${kriNum(n)}${unit ? " " + unit : ""}`;

/** The thresholds in words, e.g. "Range 110–150 %, red at ≤ 100 or ≥ 160" or "Amber ≥ 2 · Red ≥ 5 %". */
export function kriThresholdText(k: Pick<Kri, "direction" | "warning_threshold" | "limit_threshold" | "lower_bound" | "upper_bound" | "unit">): string {
  const unit = k.unit ? ` ${k.unit}` : "";
  if (k.direction === "within_range") {
    if (k.lower_bound == null || k.upper_bound == null) return "Range not set";
    const band = `Range ${kriNum(k.lower_bound)}–${kriNum(k.upper_bound)}${unit}`;
    if (k.limit_threshold == null) return `${band}; red as soon as it leaves the range`;
    const lo = Number(k.lower_bound) - Number(k.limit_threshold);
    const hi = Number(k.upper_bound) + Number(k.limit_threshold);
    return `${band}; amber outside it, red at ≤ ${kriNum(lo)} or ≥ ${kriNum(hi)}`;
  }
  const op = k.direction === "lower_is_worse" ? "≤" : "≥";
  const parts: string[] = [];
  if (k.warning_threshold != null) parts.push(`Amber ${op} ${kriNum(k.warning_threshold)}`);
  if (k.limit_threshold != null) parts.push(`Red ${op} ${kriNum(k.limit_threshold)}`);
  return parts.length ? parts.join(" · ") + unit : "No thresholds";
}

/* ================================================================ band ===== */
/** A within-range KRI's band: red | amber | green | amber | red, with the current value
 *  marked. Renders nothing for the one-sided directions. */
export function KriBand({ kri }: { kri: Kri }) {
  if (kri.direction !== "within_range" || kri.lower_bound == null || kri.upper_bound == null) return null;
  const lo = Number(kri.lower_bound);
  const hi = Number(kri.upper_bound);
  const tol = kri.limit_threshold == null ? 0 : Number(kri.limit_threshold);
  const pad = Math.max(tol * 1.5, (hi - lo) * 0.25, 1);
  const cur = kri.current_value == null ? null : Number(kri.current_value);
  let min = lo - pad;
  let max = hi + pad;
  if (cur != null) {
    min = Math.min(min, cur - pad * 0.2);
    max = Math.max(max, cur + pad * 0.2);
  }
  const pos = (v: number) => `${(((v - min) / (max - min)) * 100).toFixed(2)}%`;
  const seg = (from: number, to: number, bg: string) => (
    <div style={{ position: "absolute", top: 0, bottom: 0, left: pos(from), width: `calc(${pos(to)} - ${pos(from)})`, background: bg }} />
  );
  const where =
    cur == null
      ? "no value yet"
      : cur < lo
        ? `${kriNum(lo - cur)} below the range`
        : cur > hi
          ? `${kriNum(cur - hi)} above the range`
          : "inside the range";
  const label = `Range ${kriNum(lo)} to ${kriNum(hi)}${tol ? `, tolerance ${kriNum(tol)}` : ""}; current value ${cur == null ? "none" : kriNum(cur)}, ${where}.`;
  return (
    <div style={{ margin: "4px 0 16px" }}>
      <div role="img" aria-label={label} style={{ position: "relative", height: 12, borderRadius: 6, overflow: "hidden", background: "var(--red-bg)" }}>
        {tol > 0 && seg(lo - tol, lo, "var(--amber-bg)")}
        {seg(lo, hi, "var(--green-bg)")}
        {tol > 0 && seg(hi, hi + tol, "var(--amber-bg)")}
        {cur != null && (
          <div style={{ position: "absolute", top: -2, bottom: -2, width: 3, marginLeft: -1.5, left: pos(Math.min(Math.max(cur, min), max)), background: "var(--text-strong)", borderRadius: 2 }} />
        )}
      </div>
      <div style={{ position: "relative", height: 16, fontSize: 11.5 }} className="muted">
        <span style={{ position: "absolute", left: pos(lo), transform: "translateX(-50%)" }}>{kriNum(lo)}</span>
        <span style={{ position: "absolute", left: pos(hi), transform: "translateX(-50%)" }}>{kriNum(hi)}</span>
      </div>
      <div className="muted" style={{ fontSize: 12.5 }}>
        {cur == null ? "No value recorded yet." : <>Current {withUnit(cur, kri.unit)} — {where}.</>}
      </div>
    </div>
  );
}

/* ========================================================= escalations ===== */
type EscDraft = { id: string | null; level: "amber" | "red"; escalate_to_id: string | null; escalate_to_role: string; action: string };
const BLANK_ESC: EscDraft = { id: null, level: "amber", escalate_to_id: null, escalate_to_role: "", action: "" };
const LEVEL_TONE = { amber: "medium", red: "critical" } as const;

export function KriEscalations({ kri, onChanged, canEdit = true }: { kri: Kri; onChanged: () => void; canEdit?: boolean }) {
  const rows: KriEscalation[] = [...(kri.escalations ?? [])].sort((a, b) => a.level.localeCompare(b.level));
  const [draft, setDraft] = useState<EscDraft | null>(null);
  const [roles, setRoles] = useState<{ id: string; name: string }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const free = (["amber", "red"] as const).filter((l) => !rows.some((r) => r.level === l));
  const editorOpen = draft !== null;

  useEffect(() => {
    // The role list is fetched once, the first time the editor opens.
    if (editorOpen && roles === null) api.kriEscalationRoles().then(setRoles).catch(() => setRoles([]));
  }, [editorOpen, roles]);
  useEffect(() => {
    setDraft(null);
    setError(null);
  }, [kri.id]);

  function startNew() {
    setError(null);
    setDraft({ ...BLANK_ESC, level: free[0] ?? "amber" });
  }
  function startEdit(e: KriEscalation) {
    setError(null);
    setDraft({ id: e.id, level: e.level, escalate_to_id: e.escalate_to_id, escalate_to_role: e.escalate_to_role, action: e.action });
  }
  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    const payload = { level: draft.level, escalate_to_id: draft.escalate_to_id, escalate_to_role: draft.escalate_to_role, action: draft.action.trim() };
    try {
      if (draft.id) await api.updateKriEscalation(kri.id, draft.id, payload);
      else await api.createKriEscalation(kri.id, payload);
      setDraft(null);
      onChanged();
      toast("Escalation saved");
    } catch (e) {
      setError(errMsg(e, "Could not save the escalation"));
    } finally {
      setBusy(false);
    }
  }
  async function remove(e: KriEscalation) {
    const ok = await confirmDialog({ title: `Remove the ${e.level} escalation?`, message: "Readings that reach this level will then only name the KRI's owner.", confirmLabel: "Remove", danger: true });
    if (!ok) return;
    try {
      await api.deleteKriEscalation(kri.id, e.id);
      onChanged();
      toast("Escalation removed");
    } catch (err) {
      toast(errMsg(err, "Could not remove the escalation"), "error");
    }
  }

  const editing = draft?.id ? rows.find((r) => r.id === draft.id) : undefined;
  const levelChoices = draft?.id ? (["amber", "red"] as const).filter((l) => l === draft.level || free.includes(l)) : free;

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-pad">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
          <strong>Escalation</strong>
          {canEdit && !draft && free.length > 0 && (
            <button type="button" className="btn secondary sm" onClick={startNew}>Add escalation</button>
          )}
        </div>
        <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
          When a reading moves this KRI up into amber or red, a notification names who is told and what they must do.
        </p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th style={{ width: 90 }}>Level</th><th>Escalate to</th><th>Action</th>{canEdit && <th style={{ width: 130 }} aria-label="Actions" />}</tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td><Badge tone={LEVEL_TONE[e.level]}>{e.level === "red" ? "Red" : "Amber"}</Badge></td>
                  <td style={{ fontSize: 13 }}>
                    {e.escalate_to_id ? <UserName user={e.escalate_to_ref} /> : null}
                    {e.escalate_to_id && e.escalate_to_role ? " and " : null}
                    {e.escalate_to_role ? <span>the {e.escalate_to_role} role</span> : null}
                  </td>
                  <td style={{ fontSize: 13 }}>{e.action}</td>
                  {canEdit && (
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button type="button" className="btn secondary sm" onClick={() => startEdit(e)}>Edit</button>{" "}
                      <button type="button" className="btn secondary sm" onClick={() => remove(e)}>Remove</button>
                    </td>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={canEdit ? 4 : 3}><span className="muted">No escalation set: an amber or red reading names the owner only.</span></td></tr>
              )}
            </tbody>
          </table>
        </div>

        {draft && (
          <form
            style={{ display: "grid", gap: 10, marginTop: 12, padding: 12, border: "1px solid var(--border)", borderRadius: 8 }}
            onSubmit={(ev) => { ev.preventDefault(); save(); }}
          >
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
              <div style={{ width: 120 }}>
                <label className="label" htmlFor="esc-level">Level</label>
                <select id="esc-level" className="select" value={draft.level} onChange={(ev) => setDraft({ ...draft, level: ev.target.value as "amber" | "red" })}>
                  {levelChoices.map((l) => <option key={l} value={l}>{l === "red" ? "Red" : "Amber"}</option>)}
                </select>
              </div>
              <div style={{ flex: "1 1 200px" }}>
                <label className="label">Person</label>
                <UserPicker
                  value={draft.escalate_to_id}
                  selected={editing?.escalate_to_ref ?? null}
                  onChange={(id) => setDraft({ ...draft, escalate_to_id: id })}
                  placeholder="Who is told…"
                />
              </div>
              <div style={{ flex: "1 1 160px" }}>
                <label className="label" htmlFor="esc-role">Role</label>
                <select id="esc-role" className="select" value={draft.escalate_to_role} onChange={(ev) => setDraft({ ...draft, escalate_to_role: ev.target.value })}>
                  <option value="">No role</option>
                  {draft.escalate_to_role && !(roles ?? []).some((r) => r.name === draft.escalate_to_role) && (
                    <option value={draft.escalate_to_role}>{draft.escalate_to_role}</option>
                  )}
                  {(roles ?? []).map((r) => <option key={r.id} value={r.name}>{r.name}</option>)}
                </select>
              </div>
            </div>
            <div>
              <label className="label" htmlFor="esc-action">Action</label>
              <textarea id="esc-action" className="input" rows={2} value={draft.action} onChange={(ev) => setDraft({ ...draft, action: ev.target.value })} placeholder="What must be done, and by when" required />
            </div>
            {error && <div className="error">{error}</div>}
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button type="button" className="btn secondary sm" onClick={() => setDraft(null)} disabled={busy}>Cancel</button>
              <button className="btn sm" disabled={busy || !draft.action.trim() || (!draft.escalate_to_id && !draft.escalate_to_role)}>
                {busy ? "Saving…" : "Save escalation"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

/* ================================================================ feed ===== */
export function KriFeed({ kri, onChanged, canEdit = true }: { kri: Kri; onChanged: () => void; canEdit?: boolean }) {
  const [issued, setIssued] = useState<KriFeedToken | null>(null);
  const [busy, setBusy] = useState(false);
  const live = !!kri.has_feed_token;

  useEffect(() => setIssued(null), [kri.id]);

  async function generate() {
    if (live) {
      const ok = await confirmDialog({
        title: "Replace the feed token?",
        message: "The current token stops working at once; the integration must be given the new one.",
        confirmLabel: "Replace token",
        danger: true,
      });
      if (!ok) return;
    }
    setBusy(true);
    try {
      setIssued(await api.issueKriFeedToken(kri.id));
      onChanged();
    } catch (e) {
      toast(errMsg(e, "Could not generate a token"), "error");
    } finally {
      setBusy(false);
    }
  }
  async function revoke() {
    const ok = await confirmDialog({ title: "Revoke the feed token?", message: "The integration's next reading is refused (401).", confirmLabel: "Revoke", danger: true });
    if (!ok) return;
    setBusy(true);
    try {
      await api.revokeKriFeedToken(kri.id);
      setIssued(null);
      onChanged();
      toast("Feed token revoked");
    } catch (e) {
      toast(errMsg(e, "Could not revoke the token"), "error");
    } finally {
      setBusy(false);
    }
  }
  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${what} copied`);
    } catch {
      toast("Copy failed — select the text and copy it", "error");
    }
  }

  const url = issued ? `${API_ORIGIN}${issued.endpoint}` : "";
  const curl = issued
    ? `curl -X POST '${url}' \\\n  -H 'Authorization: Bearer ${issued.token}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"value": 1.5, "as_of_date": "YYYY-MM-DD", "notes": "source run id"}'`
    : "";

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="card-pad">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <strong>Integration feed</strong>
          <span>{live ? <Badge tone="low">Token active</Badge> : <Badge tone="neutral">No token</Badge>}</span>
        </div>
        <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
          A monitoring system or CCM connector can post readings with a token instead of a user login. Readings follow the same
          rules as ones entered here (no future dates; amber or red escalates) and are recorded as “KRI feed” in the activity trail.
        </p>
        {canEdit && (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button type="button" className="btn secondary sm" onClick={generate} disabled={busy}>{live ? "Replace token" : "Generate token"}</button>
            {live && <button type="button" className="btn secondary sm" onClick={revoke} disabled={busy}>Revoke</button>}
          </div>
        )}
        {issued && (
          <div style={{ marginTop: 12, padding: 12, border: "1px solid var(--amber)", background: "var(--amber-bg)", borderRadius: 8, display: "grid", gap: 8 }}>
            <strong style={{ fontSize: 13 }}>Copy this token now — it is not shown again.</strong>
            <div style={{ display: "flex", gap: 8 }}>
              <input className="input" readOnly value={issued.token} aria-label="Feed token" style={{ fontFamily: "var(--mono)", fontSize: 12.5 }} onFocus={(e) => e.currentTarget.select()} />
              <button type="button" className="btn sm" onClick={() => copy(issued.token, "Token")}>Copy</button>
            </div>
            <div className="muted" style={{ fontSize: 12.5 }}>Only a fingerprint of it is stored. If it is lost, generate a new one.</div>
            <pre style={{ margin: 0, padding: 10, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12, overflowX: "auto", whiteSpace: "pre" }}>{curl}</pre>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="btn secondary sm" onClick={() => copy(curl, "Example request")}>Copy example</button>
              <button type="button" className="btn secondary sm" onClick={() => setIssued(null)}>I have copied it</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
