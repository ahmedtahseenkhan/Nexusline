"use client";

/* The suggested residual for one risk, and the two ways to record a residual from it
   (record-page-spec §3.5 "ResidualSuggestion": `useResidualSuggestion(riskId)`).

     const s = useResidualSuggestion(detail?.id ?? null);
     s.data            // SuggestedResidual (+ B12 appetite_status) for THIS risk, or null
     s.loading / s.error
     await s.accept(note?)                    // record the suggestion as the residual
     await s.override(likelihood, impact, reason)   // record a different judgement
     s.reload()

   GET /risks/{id}/suggested-residual is recomputed on every read and never stored: the
   number is a proposal, and nothing is recorded until the owner accepts it (POST
   /risks/{id}/accept-residual with no scores, plus the owner's `note`) or records a
   different residual with a written reason (`likelihood`, `impact`, `override_reason`).

   B6: when a credited control is rated by hand or by override, or has no reviewed test,
   the server refuses an acceptance without a note (422, `UNTESTED_CREDIT_NOTE_NEEDED`);
   `isNoteRequired(e)` recognises that refusal so the form can ask for one.

   `accept` and `override` resolve with the updated risk and refetch the suggestion; they
   throw with the server's message (the caller shows it inline). Data from another risk
   is never returned: switching risks reads `loading` until the new one arrives. The
   caller still runs the page refresh (`gov.reload()`, `loadDetail`) afterwards. */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiCall, type Risk, type SuggestedResidual } from "@/lib/api";

/** `SuggestedResidual` plus B12: the appetite band the suggested score would fall in
 *  ("within_appetite" | "elevated" | "breach"); absent on an older backend. */
export type SuggestedResidualB12 = SuggestedResidual & { appetite_status?: string | null };

/** The B6 refusal text (backend `schemas.risk.UNTESTED_CREDIT_NOTE_NEEDED`). */
export const UNTESTED_CREDIT_NOTE_NEEDED = "Accepting credit from an untested control rating needs a note";

/** True when `e` is the server asking for a note before accepting untested credit (B6). */
export function isNoteRequired(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : typeof e === "string" ? e : "";
  return msg.toLowerCase().includes(UNTESTED_CREDIT_NOTE_NEEDED.toLowerCase());
}

export type ResidualSuggestionApi = {
  data: SuggestedResidualB12 | null;
  error: string | null;
  loading: boolean;
  /** An accept or override is in flight. */
  busy: boolean;
  /** Record the suggestion as the residual; `note` is the owner's word (required by B6 for untested credit). */
  accept(note?: string): Promise<Risk>;
  /** Record a different residual; `reason` is required whenever it differs from the suggestion (the server enforces it). */
  override(likelihood: number, impact: number, reason: string): Promise<Risk>;
  reload(): void;
};

/** The suggested residual for `riskId` (null: nothing is fetched) plus `accept` /
 *  `override`, which record a residual and refetch. See the file header. */
export function useResidualSuggestion(riskId: string | null | undefined): ResidualSuggestionApi {
  const id = riskId ?? null;
  const [state, setState] = useState<{ id: string | null; data: SuggestedResidualB12 | null; error: string | null }>({
    id: null,
    data: null,
    error: null,
  });
  const [busy, setBusy] = useState(false);
  const seq = useRef(0);

  const reload = useCallback(() => {
    const mine = ++seq.current;
    if (!id) return;
    api
      .suggestedResidual(id)
      .then((data) => {
        if (mine === seq.current) setState({ id, data: data as SuggestedResidualB12, error: null });
      })
      .catch((e) => {
        if (mine === seq.current) {
          setState({ id, data: null, error: e instanceof Error && e.message ? e.message : "Could not load the suggested residual" });
        }
      });
  }, [id]);

  useEffect(() => {
    reload();
  }, [reload]);

  const post = useCallback(
    async (body: Record<string, unknown>): Promise<Risk> => {
      if (!id) throw new Error("No risk is open");
      setBusy(true);
      try {
        const risk = await apiCall<Risk>("POST", `/risks/${id}/accept-residual`, body);
        reload();
        return risk;
      } finally {
        setBusy(false);
      }
    },
    [id, reload],
  );

  const accept = useCallback(
    (note?: string) => {
      const n = (note ?? "").trim();
      return post(n ? { note: n } : {});
    },
    [post],
  );

  const override = useCallback(
    (likelihood: number, impact: number, reason: string) =>
      post({ likelihood, impact, override_reason: reason.trim() }),
    [post],
  );

  const current = state.id === id && id !== null;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: !!id && !current,
    busy,
    accept,
    override,
    reload,
  };
}

export default useResidualSuggestion;
