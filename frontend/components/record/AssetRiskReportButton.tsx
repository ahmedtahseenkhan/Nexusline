"use client";

/* The asset's risk report as a secondary button (record-page-spec §3.5 "AssetRiskReport"
   `variant="button"`) and as a More item. The existing card, components/AssetRiskReport,
   stays for classic pages.

     const report = useAssetRiskReport(a ? { id: a.id, name: a.name } : null);
     <AssetRiskReportButton assetId={a.id} assetName={a.name} riskCount={a.risks.length} />   // e.g. a RelatedGroup `action`
     typeItems.push(...assetRiskReportItems(report, a.risks.length));                        // More › "Risk report (PDF)"

   The same export as the register: GET /reports/pdf/risk-register?asset_id={id}, saved
   as "risk-report-{asset}.pdf" — cover naming the asset, one line per directly linked
   risk, then a page each with its controls, both ratings and the treatment. Renders
   nothing (and no More item) when no risk is linked. Failures toast the server's message. */

import { useCallback, useRef, useState } from "react";
import type { MenuItem } from "@/components/Menu";
import { api } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { plural } from "@/lib/record/text";

export type AssetRiskReport = { busy: boolean; download(): Promise<void> };

/** Download state for one asset's risk report (shared by the button and the More item). */
export function useAssetRiskReport(asset: { id: string; name: string } | null): AssetRiskReport {
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const download = useCallback(async () => {
    if (!asset || running.current) return;
    running.current = true;
    setBusy(true);
    try {
      await api.pdfRiskRegister({ asset_id: asset.id }, asset.name);
    } catch (e) {
      toast(e instanceof Error && e.message ? e.message : "Could not generate the risk report", "error");
    } finally {
      running.current = false;
      setBusy(false);
    }
  }, [asset?.id, asset?.name]); // eslint-disable-line react-hooks/exhaustive-deps
  return { busy, download };
}

/** What the report holds, for a title or a menu hint. */
export function riskReportHint(riskCount: number): string {
  return `${plural(riskCount, "linked risk")}: ratings, controls, classification and treatment`;
}

/** The More item(s): "Risk report (PDF)", or none when no risk is linked. */
export function assetRiskReportItems(report: AssetRiskReport, riskCount: number): MenuItem[] {
  if (riskCount <= 0) return [];
  return [
    {
      label: report.busy ? "Generating risk report…" : "Risk report (PDF)",
      onClick: () => void report.download(),
      disabled: report.busy,
      hint: riskReportHint(riskCount),
    },
  ];
}

type AssetRiskReportButtonProps = {
  assetId: string;
  assetName: string;
  /** Directly linked risks; 0 renders nothing. */
  riskCount: number;
  /** Share a `useAssetRiskReport` state with the More item (optional). */
  report?: AssetRiskReport;
};

/** `btn secondary sm` "Risk report (PDF)"; nothing when `riskCount` is 0. */
export default function AssetRiskReportButton({ assetId, assetName, riskCount, report }: AssetRiskReportButtonProps) {
  const own = useAssetRiskReport(report ? null : { id: assetId, name: assetName });
  const r = report ?? own;
  if (riskCount <= 0) return null;
  return (
    <button
      type="button"
      className="btn secondary sm"
      onClick={() => void r.download()}
      disabled={r.busy}
      aria-busy={r.busy || undefined}
      aria-label={r.busy ? undefined : `Risk report (PDF) for ${assetName}`}
      title={riskReportHint(riskCount)}
    >
      {r.busy ? "Generating…" : "Risk report (PDF)"}
    </button>
  );
}

export { AssetRiskReportButton };
