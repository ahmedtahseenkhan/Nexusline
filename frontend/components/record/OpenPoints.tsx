"use client";

/* "Open points" (record-page-spec §3.3.4): the derived gaps and notes for one record.

     <OpenPoints points={riskOpenPoints(input, ctx)} canAct={canWrite} onAction={handlePoint}
       clearText="No open points: owner, assessment, approval and attestation are on file." />

   Gaps are rows (amber dot, a visually hidden "Gap:" prefix, the text and a fix link on
   the right); notes fold into one "Also noted: … · …" line. There is no Hide: gaps are
   always listed, and read-only viewers (`canAct` false) see the same list with no
   buttons. Fix actions NEVER change state — the page maps them to scroll / focus /
   Edit-on-a-tab / open a form / navigate:

     const handlePoint = (a: PointAction) => {
       if (a.kind === "section") sections.scrollTo(a.target);
       else if (a.kind === "edit") openEdit(detail, a.target);
       else if (a.kind === "focus") document.getElementById(a.target)?.focus();
       else if (a.kind === "href") router.push(a.target);
       else if (a.kind === "attest") gov.openAttest();
       else if (a.kind === "open") openers[a.target]?.();
     };

   With no points it shows one green line, `clearText`. */

import { Fragment } from "react";
import Segs from "@/components/record/Segs";
import { segsText } from "@/lib/record/text";
import type { OpenPoint, PointAction } from "@/lib/record/types";

type OpenPointsProps = {
  points: OpenPoint[];
  onAction: (a: PointAction) => void;
  /** false: no buttons ("Open points" for audit / read-only viewers). */
  canAct: boolean;
  /** "No open points: owner, assessment, approval and attestation are on file." */
  clearText: string;
};

/** "No risk owner: accountability can't be shown." → "No risk owner" (for accessible names). */
function shortText(p: OpenPoint): string {
  const t = segsText(p.text).trim();
  const head = t.split(":")[0] ?? t;
  return head.replace(/[.\s]+$/, "");
}

export default function OpenPoints({ points, onAction, canAct, clearText }: OpenPointsProps) {
  const gaps = points.filter((p) => p.level === "gap");
  const notes = points.filter((p) => p.level === "note");

  if (points.length === 0) {
    return (
      <section className="rec-op is-clear" aria-labelledby="rec-op-h">
        <h2 id="rec-op-h" className="sr-only">Open points</h2>
        <p className="rec-op-clear">{clearText}</p>
      </section>
    );
  }

  const count = gaps.length > 0 ? `${gaps.length} to resolve` : `${notes.length} noted`;
  const actionable = (p: OpenPoint) => canAct && !!p.action && !!p.action.label;

  return (
    <section className="rec-op" aria-labelledby="rec-op-h">
      <div className="rec-op-head">
        <h2 id="rec-op-h">Open points</h2>
        <span className="rec-op-count" aria-live="polite">{count}</span>
      </div>
      {gaps.length > 0 && (
        <ul>
          {gaps.map((p) => (
            <li key={p.id} data-point={p.id}>
              <span className="mk" aria-hidden="true" />
              <span>
                <span className="sr-only">Gap: </span>
                <Segs segs={p.text} />
              </span>
              {actionable(p) && p.action && (
                <button
                  type="button"
                  className="rec-link"
                  aria-label={`${p.action.label}, for: ${shortText(p)}`}
                  onClick={() => p.action && onAction(p.action)}
                >
                  {p.action.label}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {notes.length > 0 && (
        <p className="rec-op-notes">
          Also noted:{" "}
          {notes.map((p, i) => (
            <Fragment key={p.id}>
              {i > 0 && " · "}
              <span data-point={p.id}>
                <Segs segs={p.text} />
                {actionable(p) && p.action && (
                  <>
                    {" "}
                    <button
                      type="button"
                      className="rec-link"
                      aria-label={`${p.action.label}, for: ${shortText(p)}`}
                      onClick={() => p.action && onAction(p.action)}
                    >
                      {p.action.label}
                    </button>
                  </>
                )}
              </span>
            </Fragment>
          ))}
        </p>
      )}
    </section>
  );
}

export { OpenPoints };
