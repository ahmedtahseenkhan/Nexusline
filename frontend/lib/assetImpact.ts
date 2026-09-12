import { apiCall } from "@/lib/api";

/** Live records that link to an asset (GET /assets/{id}/impact). */
export type AssetImpact = { risks: number; controls: number };

/** Linked live risks across these assets, summed; null when the count could not be read. */
export async function linkedRiskCount(assetIds: string[]): Promise<number | null> {
  try {
    const rows = await Promise.all(
      assetIds.map((id) => apiCall<AssetImpact>("GET", `/assets/${id}/impact`)),
    );
    return rows.reduce((n, r) => n + r.risks, 0);
  } catch {
    return null;
  }
}

/** The delete confirmation's message: what happens to the risks written against the asset(s). */
export function assetDeleteMessage(riskCount: number | null, assetCount = 1): string {
  const subject = assetCount === 1 ? "this asset" : "these assets";
  const trail = `The activity trail records who removed ${assetCount === 1 ? "it" : "them"}.`;
  if (riskCount === null) {
    return `Any risks that link to ${subject} will be flagged for review in the risk register. ${trail}`;
  }
  if (riskCount === 0) {
    return `No risks link to ${subject}. ${trail}`;
  }
  const risks = riskCount === 1 ? "1 risk links" : `${riskCount} risks link`;
  const they = riskCount === 1 ? "It stays in the risk register and will be flagged" : "They stay in the risk register and will be flagged";
  return `${risks} to ${subject}. ${they} for review. ${trail}`;
}
