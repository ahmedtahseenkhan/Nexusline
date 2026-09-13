"use client";

import { forwardRef, useImperativeHandle, useMemo, useRef, useState } from "react";
import { api, type RiskAcceptance } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { acceptanceView, daysFrom, exceptionsLine, type RiskExceptionRef } from "@/lib/record/risk";
import { Badge } from "@/components/badges";
import { Field, TextInput, TextArea } from "@/components/fields";
import Disclosure from "@/components/record/Disclosure";
import { useRecordFmt } from "@/components/record/ctx";

/* Accepting a risk is the one place in the register where doing nothing is a *decision*.
   Three things make it that rather than an omission, and all three are visible here:

   1. **A written rationale.** The sentence an auditor reads when they ask why this
      exposure was tolerated.
   2. **Four eyes.** Whoever requested the acceptance can never approve it; the server
      refuses, and says so. The panel does not try to guess who is allowed — it offers
      the buttons and lets the refusal be the answer, because the rule depends on
      dual-control thresholds the client cannot see.
   3. **An expiry.** An open-ended acceptance is how a risk disappears for three years.
      Once the date passes, the scheduled sweep marks the acceptance expired and puts the
      risk back in the register awaiting a fresh decision — which is why the expiry field
      warns rather than being quietly optional.

   The request form opens on demand (a Disclosure: Esc and Cancel return focus to its
   trigger), and a parent can open it through the `openRequest()` handle — the risk
   record's More menu and its open points do. `relatedExceptions` names any linked
   exception to policy, so it is never mistaken for a risk acceptance (record-page-spec
   §5, row 15). `bare` drops the bordered box for the dossier's Assessment section. */

const TONE: Record<RiskAcceptance["status"], "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  pending: "medium",
  rejected: "neutral",
  expired: "high",
};

const WORDS: Record<RiskAcceptance["status"], string> = {
  approved: "In force",
  pending: "Awaiting approval",
  rejected: "Rejected",
  expired: "Lapsed",
};

/** An exception to policy linked to the risk; `status` / `expires_at` arrive with B3. */
export type RelatedExceptionRef = RiskExceptionRef;

export type RiskAcceptancePanelHandle = {
  /** Open the request (or renewal) form; does nothing while a request awaits a decision. */
  openRequest(): void;
};

type Props = {
  riskId: string;
  riskReference: string;
  acceptances: RiskAcceptance[];
  /** Reload the record after anything is recorded. */
  onChange: () => void;
  /** Linked exceptions to policy: "EXC-001 (approved, expires …) is an exception to policy, not a risk acceptance." */
  relatedExceptions?: RelatedExceptionRef[];
  /** No bordered box (the record page's section rule frames it). */
  bare?: boolean;
  /** May request (or renew) an acceptance: the page passes risk:write. Default true. */
  canRequest?: boolean;
  /** May approve or reject a pending request: the page passes risk:accept. Default true.
   *  Without it the pending rationale stays visible, the decision controls do not. */
  canDecide?: boolean;
};

const RiskAcceptancePanel = forwardRef<RiskAcceptancePanelHandle, Props>(function RiskAcceptancePanel(
  { riskId, riskReference, acceptances, onChange, relatedExceptions, bare = false, canRequest = true, canDecide = true },
  ref,
) {
  const [requesting, setRequesting] = useState(false);
  const [rationale, setRationale] = useState("");
  const [expires, setExpires] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestBtn = useRef<HTMLButtonElement>(null);
  const { formatDate } = useFormat();
  const fmt = useRecordFmt();

  const history = useMemo(
    () => [...acceptances].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    [acceptances],
  );
  // The same reading as the record's Risk acceptance tile: an approved acceptance past
  // its expiry is lapsed, not in force, even before the nightly sweep marks it expired.
  const view = acceptanceView({ acceptances }, new Date());
  const pending = view.pending ?? undefined;
  const inForce = view.inForce ?? undefined;
  const lapsedApproval = (a: RiskAcceptance) => a.status === "approved" && !!a.expires_at && daysFrom(a.expires_at, new Date()) < 0;

  useImperativeHandle(
    ref,
    () => ({
      openRequest: () => {
        if (pending || !canRequest) return;
        setError(null);
        setRequesting(true);
      },
    }),
    [pending, canRequest],
  );

  function setRequestOpen(open: boolean) {
    setRequesting(open);
    if (!open) setError(null);
  }

  async function submitRequest(close: () => void) {
    if (!rationale.trim()) {
      setError("Write down why this risk is being accepted — that sentence is the record.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.requestAcceptance(riskId, { rationale: rationale.trim(), expires_at: expires || null });
      setRationale("");
      setExpires("");
      close();
      toast(`Acceptance requested for ${riskReference}. A second person has to approve it.`);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not request acceptance");
    } finally {
      setBusy(false);
    }
  }

  async function decide(acceptance: RiskAcceptance, approve: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.decideAcceptance(riskId, acceptance.id, { approve, note: note.trim() });
      setNote("");
      toast(approve ? `${riskReference} accepted.` : `Acceptance rejected for ${riskReference}.`);
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record the decision");
    } finally {
      setBusy(false);
    }
  }

  // "EXC-001 (approved, expires 03 Jan 2027) is an exception to policy, not a risk acceptance."
  // The wording lives in lib/record/risk.ts with the rest of the risk page's.
  const exceptionLine = exceptionsLine(relatedExceptions, fmt);

  const requestLabel = inForce ? "Request renewal" : "Request acceptance";
  const headStyle = bare
    ? { margin: 0, fontSize: 13, lineHeight: "18px", fontWeight: 650, color: "var(--text-strong)" }
    : { fontSize: 13 };

  return (
    <div style={bare ? { marginTop: 18 } : { padding: "12px 14px", border: "1px solid var(--border)", borderRadius: 8, marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        {bare ? <h3 style={headStyle}>Risk acceptance</h3> : <strong style={headStyle}>Risk acceptance</strong>}
        {inForce && <Badge tone="low" asIs>In force</Badge>}
        {pending && <Badge tone="medium" asIs>Awaiting a second approver</Badge>}
        {!inForce && !pending && !history.length && (
          <span className="muted" style={{ fontSize: 12.5 }}>None on file.</span>
        )}
        {!pending && canRequest && (
          <button
            ref={requestBtn}
            type="button"
            className="btn secondary sm"
            style={{ marginLeft: "auto" }}
            aria-expanded={requesting}
            aria-controls="risk-acceptance-request"
            onClick={() => setRequestOpen(!requesting)}
          >
            {requestLabel}
          </button>
        )}
      </div>

      {exceptionLine && (
        <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5, lineHeight: "18px" }}>{exceptionLine}</p>
      )}

      {error && !requesting && <div className="error" style={{ fontSize: 12.5, marginTop: 10 }}>{error}</div>}

      {inForce?.expires_at && (() => {
        const left = daysFrom(inForce.expires_at, new Date());
        if (left < 0) return null;
        return (
          <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
            {left <= 30 ? (
              <b>
                Expires in {left} day{left === 1 ? "" : "s"} ({formatDate(inForce.expires_at)}) — renew it, or the risk
                returns to the register on its own.
              </b>
            ) : (
              <>In force until {formatDate(inForce.expires_at)}.</>
            )}
          </div>
        );
      })()}

      {/* ------------------------------------------------------- request form */}
      {!pending && canRequest && (
        <Disclosure
          label={requestLabel}
          hideTrigger
          open={requesting}
          onOpenChange={setRequestOpen}
          triggerRef={requestBtn}
          id="risk-acceptance-request"
        >
          {(close) => (
            <form
              style={{ display: "grid", gap: 10 }}
              onSubmit={(e) => {
                e.preventDefault();
                void submitRequest(close);
              }}
            >
              <Field
                label="Why is this risk being accepted?"
                required
                help="Stated in full: the compensating measures, who agreed, and what would change the decision. This is what an auditor reads."
              >
                <TextArea
                  value={rationale}
                  onChange={setRationale}
                  placeholder="Exposure is tolerated until the MFA rollout completes; privileged sessions are monitored daily in the interim and reviewed by the CISO monthly."
                />
              </Field>
              <Field
                label="Acceptance expires on"
                help="Leave blank only for a deliberately open-ended acceptance. With a date, the platform lapses the acceptance itself once it passes and puts the risk back in the register — nobody has to remember."
              >
                <TextInput value={expires} onChange={setExpires} type="date" />
              </Field>
              {error && <div className="error" style={{ fontSize: 12.5 }}>{error}</div>}
              <div className="row">
                <button type="submit" className="btn secondary sm" disabled={busy}>
                  {busy ? "Submitting…" : "Submit for approval"}
                </button>
                <button type="button" className="btn secondary sm" disabled={busy} onClick={close}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </Disclosure>
      )}

      {/* -------------------------------------------------- pending decision */}
      {pending && (
        <div style={{ marginTop: 12, display: "grid", gap: 10 }}>
          <div style={{ fontSize: 13.5, lineHeight: 1.5 }}>{pending.rationale}</div>
          {!canDecide ? (
            <span className="muted" style={{ fontSize: 12 }}>
              Awaiting a decision by someone who may accept risk.
            </span>
          ) : (<>
          <Field label="Decision note" help="Optional, and recorded on the trail either way.">
            <TextInput value={note} onChange={setNote} placeholder="Approved at the September risk committee." />
          </Field>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button type="button" className="btn secondary sm" disabled={busy} onClick={() => decide(pending, true)}>
              {busy ? "Recording…" : "Approve acceptance"}
            </button>
            <button type="button" className="btn secondary sm" disabled={busy} onClick={() => decide(pending, false)}>
              Reject
            </button>
            <span className="muted" style={{ fontSize: 12 }}>
              Whoever requested this cannot approve it.
            </span>
          </div>
          </>)}
        </div>
      )}

      {/* -------------------------------------------------------- the history */}
      {history.length > 0 && (
        <div className={bare ? "rec-table-wrap" : "table-wrap"} style={{ marginTop: 12 }}>
          <table className={bare ? "compact" : undefined}>
            <thead>
              <tr>
                <th style={{ width: 150 }}>Decision</th>
                <th style={{ width: 110 }}>Expires</th>
                <th style={{ width: 110 }}>Decided</th>
                <th>Rationale</th>
              </tr>
            </thead>
            <tbody>
              {history.map((a) => (
                <tr key={a.id}>
                  <td>
                    {lapsedApproval(a)
                      ? <Badge tone={TONE.expired} asIs>{WORDS.expired}</Badge>
                      : <Badge tone={TONE[a.status]} asIs>{WORDS[a.status]}</Badge>}
                  </td>
                  <td className="muted">{a.expires_at ? formatDate(a.expires_at) : "Open-ended"}</td>
                  <td className="muted">{a.decided_at ? formatDate(a.decided_at) : "Not decided"}</td>
                  <td style={{ fontSize: 13 }}>{a.rationale || <span className="muted">No rationale</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
});

export default RiskAcceptancePanel;
