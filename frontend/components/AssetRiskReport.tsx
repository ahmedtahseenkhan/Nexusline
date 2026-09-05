"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { toast } from "@/lib/feedback";

/* "Give me the risk report for Internet Banking" is the question a bank asks about an
   asset, and the answer used to be a URL nobody could reach: the register could be
   scoped by asset on the server, but the API is bearer-token only, so pasting the link
   in a browser just returned 401.

   The button sits on the asset because that is where the question is asked. It exports
   the same report the register produces — cover naming the asset, one line per risk,
   then a detail page each carrying the controls, both ratings and the treatment.

   Direct links only: risks tagged to *this* asset. Risks that reach it through the
   dependency graph (the host it runs on, say) are deliberately not swept in — that is a
   different and much larger report, and one nobody asked for yet. */

type Props = {
  assetId: string;
  assetName: string;
  /** How many risks are linked, so the button can say what it will contain. */
  riskCount: number;
};

export default function AssetRiskReport({ assetId, assetName, riskCount }: Props) {
  const [busy, setBusy] = useState(false);

  async function download() {
    setBusy(true);
    try {
      await api.pdfRiskRegister({ asset_id: assetId }, assetName);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not generate the risk report");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
        padding: "10px 12px", border: "1px solid var(--border)", borderRadius: 8, marginTop: 20,
      }}
    >
      <div>
        <strong style={{ fontSize: 13 }}>Risk report</strong>
        <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
          {riskCount > 0
            ? `${riskCount} risk${riskCount === 1 ? "" : "s"} linked to ${assetName} — ratings, controls, classification and treatment.`
            : `No risks are linked to ${assetName} yet. Use "Generate risks" on the register to propose them from the scenario library.`}
        </div>
      </div>
      {riskCount > 0 && (
        <button className="btn secondary" style={{ marginLeft: "auto" }} disabled={busy} onClick={download}>
          {busy ? "Generating…" : "Download PDF"}
        </button>
      )}
    </div>
  );
}
