"use client";

/* Periodic review sign-off for any record.

     <AttestationPanel entityType="risk" entityId={r.id} />                 // card (classic rail)
     <AttestationPanel entityType="risk" entityId={r.id} variant="row" />   // row in the Sign-off card

   An attestation certifies a stated sentence, signed by someone independent of the
   record; a second person may confirm it. Records that carry their own review cycle
   (risk, policy, third party) take the cadence from that cycle, so there is one review
   date.

   Record-page-spec §3.5 behaviour, in both variants:
   - A summary: status badge (Current / Overdue / hollow "Never attested"), who last
     attested and when, and the due line (native cycle, attestation cycle, or "No
     attestation cycle yet — chosen when attesting").
   - "Attest…" opens the form in a dialog (never an always-open form). It also opens
     when the governance context's `attestOpen` becomes true (header primary, open
     point). After attesting it reloads the governance (or itself on classic pages).
   - Enablement comes ONLY from the server (B1): `can_attest === false` disables the
     button and prints `blocked_reason` beside it; when the field is absent the button
     is enabled and a refusal shows inline under it as well as in a toast. The client
     never infers draft or owner rules.
   - History folds into "History (n)"; rows this viewer may confirm stay visible:
     "{date} by {email} · awaiting confirmation · [Confirm]". */

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Badge } from "@/components/badges";
import FormModal from "@/components/FormModal";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { cadenceNoun, sentenceCase } from "@/lib/record/text";
import { useRecordGovernance, type AttestationStatusB1 } from "@/components/record/RecordGovernance";

const FREQS = ["fortnightly", "monthly", "quarterly", "semiannual", "annual", "none"];

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

type Props = {
  entityType: string;
  entityId: string;
  /** "card" (default) or "row" (the same content without the card frame, for SignOffCard). */
  variant?: "card" | "row";
  /** Called after an attestation or confirmation is recorded. */
  onChanged?: () => void;
};

export default function AttestationPanel({ entityType, entityId, variant = "card", onChanged }: Props) {
  const { formatDate, formatDateTime } = useFormat();
  const gov = useRecordGovernance(entityType, entityId);
  const shared = !!gov;

  const [own, setOwn] = useState<AttestationStatusB1 | null>(null);
  const [ownMeId, setOwnMeId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [frequency, setFrequency] = useState("annual");
  const [statement, setStatement] = useState("");
  const [scope, setScope] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  // "History (n)" is a disclosure: while open, Esc folds it (focus back on its toggle)
  // and leaves the record open.
  const historyBtn = useRef<HTMLButtonElement>(null);
  useEscapeLayer(historyOpen, () => {
    setHistoryOpen(false);
    historyBtn.current?.focus({ preventScroll: true });
  });

  const data: AttestationStatusB1 | null = shared ? gov?.attestation ?? null : own;
  const meId = shared ? gov?.me?.id ?? null : ownMeId;

  const loadOwn = useCallback(async () => {
    if (shared) return;
    const d = (await api.attestation(entityType, entityId).catch(() => null)) as AttestationStatusB1 | null;
    setOwn(d);
  }, [shared, entityType, entityId]);

  // A different record: start from a clean form and closed history.
  useEffect(() => {
    setOpen(false);
    setStatement("");
    setScope("");
    setComment("");
    setRefusal(null);
    setFormError(null);
    setHistoryOpen(false);
  }, [entityType, entityId]);

  useEffect(() => {
    setOwn(null);
    loadOwn();
  }, [loadOwn]);

  useEffect(() => {
    if (shared) return;
    api.me().then((m) => setOwnMeId(m.id)).catch(() => setOwnMeId(null));
  }, [shared]);

  // The form is prefilled from the record's cycle when the dialog OPENS, never when the
  // record refreshes: a refresh while the dialog is open (a governance reload, a trail
  // or page refresh) must not overwrite the frequency or statement being edited.
  const dataRef = useRef(data);
  dataRef.current = data;
  const openForm = useCallback(() => {
    const cur = dataRef.current;
    if (!cur) return;
    setFrequency(cur.frequency && FREQS.includes(cur.frequency) ? cur.frequency : "annual");
    setStatement((s) => s || cur.default_statement || "");
    setFormError(null);
    setOpen(true);
  }, []);

  // Header primary / open-point "Attest…" opens the dialog through the governance context.
  const attestOpen = gov?.attestOpen ?? false;
  const closeAttest = gov?.closeAttest;
  const hasData = !!data;
  const refused = data?.can_attest === false;
  const openRef = useRef(open);
  openRef.current = open;
  useEffect(() => {
    if (!attestOpen || !hasData) return;
    if (refused) {
      closeAttest?.(); // the server refuses: the button shows why
      return;
    }
    if (!openRef.current) openForm();
  }, [attestOpen, hasData, refused, closeAttest, openForm]);

  if (!data) return null;
  const d = data;

  function close() {
    setOpen(false);
    setFormError(null);
    gov?.closeAttest();
  }

  async function reloadAfter() {
    if (shared && gov) await gov.reload();
    else await loadOwn();
    onChanged?.();
  }

  async function attest() {
    setBusy(true);
    setFormError(null);
    try {
      const payload: Record<string, unknown> = { comment, statement: statement.trim(), scope: scope.trim() };
      if (!d.native_review) payload.frequency = frequency;
      const next = (await api.attest(entityType, entityId, payload)) as AttestationStatusB1;
      if (!shared) setOwn(next);
      setComment("");
      setScope("");
      setRefusal(null);
      toast("Attestation recorded");
      setOpen(false);
      gov?.closeAttest();
      await reloadAfter();
    } catch (e) {
      const msg = errMsg(e, "Could not record the attestation");
      setFormError(msg);
      setRefusal(msg);
      toast(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  async function confirm(id: string) {
    setConfirming(id);
    try {
      const next = (await api.confirmAttestation(id)) as AttestationStatusB1;
      if (!shared) setOwn(next);
      toast("Attestation confirmed");
      await reloadAfter();
    } catch (e) {
      toast(errMsg(e, "Could not confirm the attestation"), "error");
    } finally {
      setConfirming(null);
    }
  }

  const status = d.status === "current" || d.status === "overdue" ? d.status : "never";
  const badge =
    status === "current" ? (
      <Badge tone="low" asIs>Current</Badge>
    ) : status === "overdue" ? (
      <Badge tone="high" asIs>Overdue</Badge>
    ) : (
      <Badge hollow asIs>Never attested</Badge>
    );

  const freqWord = cadenceNoun(d.frequency);
  const dueLine = d.native_review ? (
    d.next_due ? (
      <>Due <b>{formatDate(d.next_due)}</b> from the {freqWord} review cycle</>
    ) : (
      <>No review date scheduled on this record&apos;s review cycle</>
    )
  ) : d.next_due ? (
    <>Next due <b>{formatDate(d.next_due)}</b> ({freqWord})</>
  ) : (
    <>No attestation cycle yet — chosen when attesting</>
  );

  const blocked = d.can_attest === false;
  const pending = d.history.filter((h) => !h.confirmed_by_id && meId !== null && h.attested_by_id !== meId);
  const title = `Attest — ${gov?.workflow?.label || sentenceCase(entityType)}`;
  const attestNoun = (() => {
    const t = (gov?.workflow?.label || sentenceCase(entityType)).trim();
    return /^[A-Z]{2}/.test(t) ? t : t.charAt(0).toLowerCase() + t.slice(1);
  })();

  const content = (
    <>
      {status !== "never" && (
        <div className="d">
          Last attested <b>{d.last_attested_at ? formatDate(d.last_attested_at) : "—"}</b>
          {d.last_by ? <> by <b>{d.last_by}</b></> : null}
        </div>
      )}
      <div className="d">{dueLine}</div>
      <div className="acts">
        <button
          type="button"
          className="btn secondary sm"
          onClick={openForm}
          disabled={blocked}
          // Named apart from the header's "Attest…" primary (decision D3); the name still
          // starts with the visible word.
          aria-label={`Attest this ${attestNoun}`}
          aria-describedby={blocked && d.blocked_reason ? `att-blocked-${entityId}` : undefined}
        >
          Attest…
        </button>
        {blocked && d.blocked_reason && (
          <span className="rec-att-blocked" id={`att-blocked-${entityId}`}>{d.blocked_reason}</span>
        )}
      </div>
      {refusal && !blocked && <div className="d rec-error" role="alert">{refusal}</div>}
      {pending.length > 0 && (
        <ul className="rec-att-pending">
          {pending.map((h) => (
            <li key={h.id}>
              {formatDate(h.attested_at)} by <b>{h.attested_by_email || "another user"}</b> · awaiting confirmation{" "}
              <button type="button" className="btn secondary sm" aria-label={`Confirm the attestation of ${formatDate(h.attested_at)} by ${h.attested_by_email || "another user"}`} onClick={() => confirm(h.id)} disabled={confirming === h.id}>
                {confirming === h.id ? "Confirming…" : "Confirm"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {d.history.length > 0 && (
        <div className="d">
          <button
            ref={historyBtn}
            type="button"
            className="rec-link"
            aria-expanded={historyOpen}
            aria-controls={`att-history-${entityId}`}
            onClick={() => setHistoryOpen((v) => !v)}
          >
            History ({d.history.length})
          </button>
        </div>
      )}
      {historyOpen && (
        <div className="d rec-att-history" id={`att-history-${entityId}`}>
          {d.history.map((h) => (
            <div key={h.id} className="rec-att-item">
              <div>
                <span className="muted">{formatDateTime(h.attested_at)}</span> · signed by <b>{h.attested_by_email || "—"}</b>{" "}
                <span className="muted">({cadenceNoun(h.frequency)} · next {formatDate(h.next_due)})</span>
              </div>
              <div className="muted">
                {h.confirmed_by_id ? (
                  <>Confirmed by <b>{h.confirmed_by_email || "another user"}</b>{h.confirmed_at ? ` on ${formatDateTime(h.confirmed_at)}` : ""}</>
                ) : (
                  "Not yet confirmed"
                )}
              </div>
              {h.statement && <div style={{ color: "var(--text)" }}>&ldquo;{h.statement}&rdquo;</div>}
              {h.scope && <div className="muted">Scope: {h.scope}</div>}
              {h.comment && <div className="muted">{h.comment}</div>}
            </div>
          ))}
        </div>
      )}
    </>
  );

  const dialog = open ? (
    <FormModal
      title={title}
      saveLabel="Attest"
      saving={busy}
      error={formError}
      onClose={close}
      onSave={attest}
      tabs={[
        {
          id: "attest",
          label: "Attestation",
          content: (
            <div>
              <div className="field">
                <label htmlFor={`att-statement-${entityId}`}>Statement you are signing</label>
                <textarea
                  id={`att-statement-${entityId}`}
                  className="input"
                  rows={3}
                  required
                  value={statement}
                  onChange={(e) => setStatement(e.target.value)}
                  placeholder={d.default_statement}
                />
              </div>
              <div className="field">
                <label htmlFor={`att-scope-${entityId}`}>Scope (optional)</label>
                <input
                  id={`att-scope-${entityId}`}
                  className="input"
                  value={scope}
                  onChange={(e) => setScope(e.target.value)}
                  placeholder="What you looked at, e.g. Q3 loss data, latest control tests"
                />
              </div>
              {d.native_review ? (
                <p className="muted" style={{ fontSize: 12.5, margin: "0 0 18px" }}>
                  Next review: <b>{d.next_due ? formatDate(d.next_due) : "not scheduled"}</b>, from this record&apos;s review cycle
                  {d.frequency ? ` (${cadenceNoun(d.frequency)})` : ""}. Attesting records the review and moves that date.
                </p>
              ) : (
                <div className="field">
                  <label htmlFor={`att-freq-${entityId}`}>Frequency</label>
                  <select id={`att-freq-${entityId}`} className="input" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
                    {FREQS.map((f) => <option key={f} value={f}>{sentenceCase(f)}</option>)}
                  </select>
                </div>
              )}
              <div className="field">
                <label htmlFor={`att-comment-${entityId}`}>Comment</label>
                <input
                  id={`att-comment-${entityId}`}
                  className="input"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Reviewed — no changes"
                />
              </div>
            </div>
          ),
        },
      ]}
    />
  ) : null;

  if (variant === "row") {
    return (
      <div className="rec-so-row rec-att">
        <div className="k">Attestation {badge}</div>
        {content}
        {dialog}
      </div>
    );
  }

  return (
    <div className="card rec-att-card" style={{ marginTop: 16 }}>
      <div className="card-head">
        <h3>Review &amp; attestation</h3>
        {badge}
      </div>
      <div className="card-pad">
        <div className="rec-so-row rec-att">{content}</div>
      </div>
      {dialog}
    </div>
  );
}
