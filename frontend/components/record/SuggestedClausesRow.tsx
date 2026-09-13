"use client";

/* The compact "suggested clauses" row for a control's Linked records section
   (record-page-spec §3.5 "SuggestedClauses" `variant="row"`). The existing card,
   components/SuggestedClauses, stays; this row summarises it in one line and expands to
   that same list:

     3 suggested clauses from your installed frameworks · Review

     <RelatedGroup footer={<SuggestedClausesRow controlId={c.id} count={suggestionCount}
        open={suggestOpen} onOpenChange={setSuggestOpen} onAccepted={refresh} />} … />

   - `count`: the number the page already loaded with the record (the control's open
     points read it); omit it and the row fetches the suggestions itself and reports the
     number through `onCount`.
   - Renders nothing when there are no suggestions (and the list is closed); when the
     suggestions could not be loaded it says so with a Retry (`failed` / `onRetry` for a
     page-owned count), so a failure never reads as "no suggestions".
   - "Review" / "Hide" toggles the list in a Disclosure (focus moves in; Esc and Hide
     return it). Controlled with `open` + `onOpenChange`, so More › "Suggest clause
     mappings" and the open point can expand it.
   - After links are accepted the row refetches (when it owns the count) and calls
     `onAccepted` (the page's refresh). */

import { useCallback, useEffect, useId, useRef, useState } from "react";
import SuggestedClauses from "@/components/SuggestedClauses";
import Disclosure from "@/components/record/Disclosure";
import { getSuggestedRequirements } from "@/lib/compliance";
import { plural } from "@/lib/record/text";

export type SuggestedClausesRowProps = {
  controlId: string;
  /** The count the page loaded with the record; omit to let the row fetch it. */
  count?: number | null;
  /** The count the row fetched (only when `count` is not passed); null on failure. */
  onCount?: (n: number | null) => void;
  /** Controlled expansion. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** After requirements are linked: the page's refresh. */
  onAccepted?: () => void;
  /** Panel id, for an external trigger's aria-controls. Default generated. */
  id?: string;
  /** The page's own load of `count` failed: show "Could not load suggested clauses.
   *  Retry" instead of nothing (nothing would read as "no suggestions"). */
  failed?: boolean;
  /** Retry for a page-owned count (with `failed`); the row retries its own fetch itself. */
  onRetry?: () => void;
};

/** "{n} suggested clauses from your installed frameworks · Review", expanding to the
 *  existing SuggestedClauses list; nothing when there are none. See the file header. */
export default function SuggestedClausesRow({ controlId, count, onCount, open: openProp, onOpenChange, onAccepted, id, failed, onRetry }: SuggestedClausesRowProps) {
  const own = count === undefined;
  const [fetched, setFetched] = useState<{ id: string; n: number | null } | null>(null);
  const seq = useRef(0);
  const onCountRef = useRef(onCount);
  onCountRef.current = onCount;

  const load = useCallback(() => {
    if (!own) return;
    const mine = ++seq.current;
    getSuggestedRequirements(controlId)
      .then((rows) => {
        if (mine !== seq.current) return;
        setFetched({ id: controlId, n: rows.length });
        onCountRef.current?.(rows.length);
      })
      .catch(() => {
        if (mine !== seq.current) return;
        setFetched({ id: controlId, n: null });
        onCountRef.current?.(null);
      });
  }, [controlId, own]);
  useEffect(() => {
    load();
  }, [load]);

  const [inner, setInner] = useState(false);
  const controlled = openProp !== undefined;
  const open = controlled ? !!openProp : inner;
  const setOpen = (v: boolean) => {
    if (!controlled) setInner(v);
    onOpenChange?.(v);
  };
  useEffect(() => {
    if (!controlled) setInner(false);
  }, [controlId, controlled]);

  const genId = useId().replace(/:/g, "");
  const panelId = id ?? `suggest-${genId}`;
  const trigger = useRef<HTMLButtonElement>(null);
  const n = own ? (fetched && fetched.id === controlId ? fetched.n : null) : (count ?? null);

  const loadFailed = own ? !!fetched && fetched.id === controlId && fetched.n === null : !!failed && count == null;
  if (!open && !n && loadFailed) {
    return (
      <div className="rec-suggest">
        <p className="rec-suggest-line" role="status">
          Could not load suggested clauses.{" "}
          <button type="button" className="rec-link" aria-label="Retry loading suggested clauses" onClick={() => (own ? load() : onRetry?.())}>
            Retry
          </button>
        </p>
      </div>
    );
  }
  if (!open && !n) return null;
  const words = plural(n ?? 0, "suggested clause");

  return (
    <div className="rec-suggest">
      {n ? (
        <p className="rec-suggest-line">
          {words} from your installed frameworks ·{" "}
          <button
            ref={trigger}
            type="button"
            className="rec-link"
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={`${open ? "Hide" : "Review"} ${words}`}
            onClick={() => setOpen(!open)}
          >
            {open ? "Hide" : "Review"}
          </button>
        </p>
      ) : null}
      <Disclosure
        label="Suggested clauses"
        hideTrigger
        open={open}
        onOpenChange={setOpen}
        id={panelId}
        triggerRef={trigger}
        panelClassName="rec-disclosure rec-suggest-panel"
      >
        {() => (
          <SuggestedClauses
            controlId={controlId}
            onAccepted={() => {
              load();
              onAccepted?.();
            }}
          />
        )}
      </Disclosure>
    </div>
  );
}

export { SuggestedClausesRow };
