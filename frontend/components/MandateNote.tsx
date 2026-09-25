"use client";

import { useEffect, useRef, useState } from "react";
import { api, type RecordMandate } from "@/lib/api";
import { useFormat } from "@/lib/format";

/* The delegation-of-authority check on a pending decision, shown where the approver
   decides (GET /authority-matrix/mandate/{entity_type}/{id} — the same answer the server
   gives when they click Approve). Nothing is shown when the organisation has no matrix
   lines for the decision's category: the matrix does not restrict it. Inside the mandate
   it is one muted line; outside it, the refusal and the lines that say who may approve,
   so the approver knows where to send it. Rejecting never needs a mandate. */

type Props = {
  entityType: "risk_acceptance" | "exception" | "loss_event" | "outsourcing_arrangement";
  recordId: string;
  /** Change to fetch again (after the record's amount is edited). */
  refreshKey?: unknown;
  /** Told the answer (null when there is none), so the caller can withhold Approve
   *  when the decision is above the user's mandate. */
  onMandate?: (m: RecordMandate | null) => void;
};

export default function MandateNote({ entityType, recordId, refreshKey, onMandate }: Props) {
  const [mandate, setMandate] = useState<RecordMandate | null>(null);
  const { formatMoney } = useFormat();
  const report = useRef(onMandate);
  useEffect(() => { report.current = onMandate; });

  useEffect(() => {
    let live = true;
    api.recordMandate(entityType, recordId)
      .then((m) => { if (live) { setMandate(m); report.current?.(m); } })
      // No read permission or no such record: the decision control speaks for itself.
      .catch(() => { if (live) { setMandate(null); report.current?.(null); } });
    return () => { live = false; };
  }, [entityType, recordId, refreshKey]);

  if (!mandate || !mandate.governed) return null;
  const amount = mandate.amount != null ? formatMoney(mandate.amount, mandate.currency || undefined) : "no amount";
  const basis = mandate.basis ? ` (${mandate.basis})` : "";
  if (mandate.allowed) {
    return (
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        Within your delegation-of-authority mandate: {amount}{basis}.
      </p>
    );
  }
  return (
    <div role="note" style={{ fontSize: 12.5, lineHeight: "18px", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6 }}>
      <div>{mandate.reason}</div>
      {mandate.amount != null && <div className="muted">Amount checked: {amount}{basis}.</div>}
      {mandate.lines.length > 0 && (
        <ul className="muted" style={{ margin: "4px 0 0", paddingLeft: 18 }}>
          {mandate.lines.map((l) => (
            <li key={`${l.reference}-${l.role_title}`}>
              {l.role_title || "Unnamed role"}: {formatMoney(l.amount_from, l.currency || undefined)}
              {" – "}{l.amount_to != null ? formatMoney(l.amount_to, l.currency || undefined) : "no upper limit"}
              {l.reference ? ` (${l.reference})` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
