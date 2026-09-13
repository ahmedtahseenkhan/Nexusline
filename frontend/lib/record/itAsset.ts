/* Record wording for the IT asset (record-page-spec §4.4).

   Every judgement sentence on the IT asset page lives here: the six tiles, the headline,
   the open points, the Criticality derivation table, the fact texts and the page's fixed
   copy. The page renders what these functions return and adds no wording of its own.
   Wording changes update lib/record/__fixtures__/it-asset-*.json
   (`npm run check:record-copy`) and need a Compliance reviewer.

   Pure: imports only ./text, ./types and ./infoAsset (the asset pieces both types share:
   the Risk exposure tile, the review and approval points). It explains the server's
   judgements (cost_band, intrinsic / derived / effective criticality) and never
   recomputes them.

   Degrade paths: B8 `dependencies[].information_asset.business_value` absent → the
   Inherited tile names the hosted assets without their values; B8 risk scores absent →
   the shared Risk exposure tile lists labels only (see ./infoAsset). */

import {
  approvedWithoutStepPoint,
  distinctLinked,
  graphName,
  neverAttestedPoint,
  reviewOverduePoint,
  riskExposureTile,
  sevValue,
  someNames,
  type AssetDependency,
  type AssetGraphRef,
  type AssetReviewFields,
  type AssetRiskRef,
} from "./infoAsset";
import { critRank, plural, sentenceCase, truncate } from "./text";
import type { Ctx, Fmt, OpenPoint, Seg, TileModel } from "./types";

/* ------------------------------------------------------------------ input types */

/** What the IT asset rules read from GET /assets/{id}. */
export type ItAssetRecord = AssetReviewFields & {
  id: string;
  name: string;
  description: string;
  owner: { id: string; label: string } | null;
  guardian: { id: string; label: string } | null;
  availability: string;
  replacement_cost: number;
  currency: string;
  rto_hours: number | null;
  rpo_hours: number | null;
  hostname: string;
  ip_address: string;
  os_version: string;
  discovery_source: string;
  external_id: string;
  auto_discovered: boolean;
  last_seen: string | null;
  cost_band: string;
  intrinsic_criticality: string;
  derived_criticality: string;
  effective_criticality: string;
  dependencies: AssetDependency[];
  risks?: AssetRiskRef[];
  vulnerabilities?: AssetGraphRef[];
};

export type ItAssetInput = { asset: ItAssetRecord };

/* ------------------------------------------------------------------ fact texts */

const DISCOVERY_LABEL: Record<string, string> = {
  manual: "Manual entry",
  active_directory: "Active Directory",
  intune_mdm: "Intune MDM",
  cmdb: "CMDB",
  network_scan: "Network scan",
  cloud_connector: "Cloud connector",
  edr: "EDR",
  import_csv: "CSV import",
};

/** "Active Directory", "CMDB", "Intune MDM" (acronyms kept). */
export function discoverySourceLabel(source: string | null | undefined): string {
  const k = (source ?? "").toLowerCase() || "manual";
  return DISCOVERY_LABEL[k] ?? sentenceCase(k);
}

/** The lead: "db-khi-core-01 · 10.20.0.11 · RHEL 9.3" (non-empty parts only), or "". */
export function hostLine(a: { hostname?: string | null; ip_address?: string | null; os_version?: string | null }): string {
  return [a.hostname, a.ip_address, a.os_version].map((s) => (s ?? "").trim()).filter(Boolean).join(" · ");
}

/** Technical › Discovery: "Active Directory · AD-00123 · last seen 20 Jul 2026 · auto-discovered". */
export function discoveryText(a: ItAssetRecord, fmt: Fmt): string {
  return [
    discoverySourceLabel(a.discovery_source),
    (a.external_id ?? "").trim(),
    a.last_seen ? `last seen ${fmt.date(a.last_seen)}` : "",
    a.auto_discovered ? "auto-discovered" : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The crumb badge: "Auto-discovered · last seen 20 Jul 2026". */
export function autoDiscoveredText(a: ItAssetRecord, fmt: Fmt): string {
  return `Auto-discovered${a.last_seen ? ` · last seen ${fmt.date(a.last_seen)}` : ""}`;
}

/** The hosted information asset with the highest business value (B8), or null without values. */
export function topHostedValue(deps: readonly AssetDependency[]): { name: string; value: string } | null {
  let best: { name: string; value: string } | null = null;
  for (const d of deps) {
    const v = d.information_asset?.business_value;
    if (!v) continue;
    if (!best || critRank(v) > critRank(best.value)) best = { name: d.information_asset?.label ?? "", value: v };
  }
  return best;
}

export type CriticalityRow = { key: string; input: string; value: string; source: string; strong?: boolean };

/** The Criticality section's derivation table: each input, its value and where it came from. */
export function itAssetCriticalityRows(a: ItAssetRecord, fmt: Fmt): CriticalityRow[] {
  const cost = Number(a.replacement_cost || 0);
  const deps = a.dependencies ?? [];
  const n = distinctLinked(deps, "information_asset").length;
  const top = topHostedValue(deps);
  return [
    {
      key: "cost",
      input: "Cost band",
      value: a.cost_band,
      source:
        cost > 0
          ? `from replacement cost ${fmt.money(cost, a.currency)} (bands at 250k / 2M / 10M)`
          : "replacement cost not recorded, so Low (bands at 250k / 2M / 10M)",
    },
    { key: "availability", input: "Availability requirement", value: a.availability, source: "set on this asset" },
    { key: "intrinsic", input: "Intrinsic", value: a.intrinsic_criticality, source: "higher of cost band and availability", strong: true },
    {
      key: "inherited",
      input: "Inherited from data",
      value: a.derived_criticality,
      source: !n
        ? "highest business value hosted; none hosted, so Low"
        : top
          ? `highest business value hosted: ${truncate(top.name, 40)} (${sentenceCase(top.value)})${n > 1 ? `, of ${n} hosted` : ""}`
          : `highest business value hosted (${plural(n, "information asset")})`,
    },
    { key: "effective", input: "Effective", value: a.effective_criticality, source: "higher of intrinsic and inherited", strong: true },
  ];
}

/** Technical › RTO / RPO as a fact value: "4 h", or null (not set). */
export const hoursText = (h: number | null | undefined): string | null => (h !== null && h !== undefined ? `${h} h` : null);

/** The page's fixed copy (hints, empty states, the clear text). */
export const IT_ASSET_COPY = {
  clearText: "No open points: ownership, recovery objectives and approval are on file.",
  owningUnitHint: "The business unit accountable for this asset.",
  owningUnitGap: "Not assigned",
  custodianHint: "The business unit that safeguards and maintains it.",
  hostedEmpty: "No information assets hosted on this asset yet.",
  hostedSub: "it inherits their highest business value",
  noNotes: "No notes",
  noValue: "Not recorded",
  archivedLink: "Not available",
  generateHint: "Propose risks for this asset from the scenario library",
  costTabNote:
    "IT assets are judged on cost and availability only. Business-criticality is inherited from the information assets they host — a backup server is critical because of the data on it, not on its own.",
} as const;

/* ------------------------------------------------------------------ tiles */

const has = (v: number | null | undefined): v is number => v !== null && v !== undefined;

export function itAssetTiles({ asset: a }: ItAssetInput, ctx: Ctx): TileModel[] {
  const cost = Number(a.replacement_cost || 0);
  const deps = a.dependencies ?? [];
  const hosted = distinctLinked(deps, "information_asset");
  const top = topHostedValue(deps);
  const vulns = a.vulnerabilities ?? [];
  const rto = a.rto_hours;
  const rpo = a.rpo_hours;

  let recoveryBecause: Seg[];
  if (has(rto) && has(rpo)) recoveryBecause = ["Must be back within ", { b: `${rto} h` }, ", losing at most ", { b: `${rpo} h` }, " of data."];
  else if (has(rto)) recoveryBecause = ["Must be back within ", { b: `${rto} h` }, "; no RPO recorded, so tolerable data loss can't be checked."];
  else if (has(rpo)) recoveryBecause = ["May lose at most ", { b: `${rpo} h` }, " of data; no RTO recorded, so recovery time can't be checked."];
  else recoveryBecause = ["No RTO or RPO recorded, so continuity plans can't be checked against it."];

  let inheritedBecause: Seg[];
  if (!deps.length) inheritedBecause = ["Hosts no information assets, so it inherits nothing (Low)."];
  else if (top) {
    inheritedBecause = [
      `Highest business value among ${plural(hosted.length, "hosted information asset")}: ${truncate(top.name, 40)} (`,
      { b: sentenceCase(top.value) },
      ").",
    ];
  } else {
    inheritedBecause = [`Highest business value among ${plural(hosted.length, "hosted information asset")} (${someNames(hosted, 2, 30)}).`];
  }

  return [
    {
      key: "effective",
      label: "Effective criticality",
      section: "criticality",
      value: sevValue(a.effective_criticality),
      because: ["Higher of intrinsic ", { b: sentenceCase(a.intrinsic_criticality) }, " and inherited ", { b: sentenceCase(a.derived_criticality) }, "."],
      basis: { kind: "derived", text: "Calculated" },
    },
    {
      key: "intrinsic",
      label: "Intrinsic criticality",
      section: "criticality",
      value: sevValue(a.intrinsic_criticality),
      because:
        cost > 0
          ? ["Higher of cost band ", { b: sentenceCase(a.cost_band) }, ` (${ctx.fmt.money(cost, a.currency)}) and availability `, { b: sentenceCase(a.availability) }, "."]
          : ["Replacement cost not recorded, so the cost band is Low; availability ", { b: sentenceCase(a.availability) }, " decides."],
      basis: cost > 0 ? { kind: "derived", text: "Calculated from cost and availability" } : { kind: "declared", text: "Cost not recorded" },
    },
    {
      key: "inherited",
      label: "Inherited from data",
      section: "hosted",
      value: sevValue(a.derived_criticality),
      because: inheritedBecause,
      basis: { kind: "derived", text: "From dependency links" },
    },
    {
      key: "recovery",
      label: "Recovery objectives",
      section: "technical",
      value:
        has(rto) || has(rpo)
          ? { text: `RTO ${has(rto) ? `${rto} h` : "not set"} · RPO ${has(rpo) ? `${rpo} h` : "not set"}` }
          : { text: "Not set", tone: "hollow" },
      because: recoveryBecause,
      basis: has(rto) || has(rpo) ? { kind: "declared", text: "Recorded by hand" } : { kind: "missing", text: "Not on file" },
    },
    {
      key: "vulns",
      label: "Vulnerabilities",
      section: "linked",
      value: vulns.length ? { text: plural(vulns.length, "vulnerability", "vulnerabilities") } : { text: "None linked" },
      because: vulns.length ? [`${someNames(vulns.map(graphName), 2, 40)}.`] : ["No vulnerability is linked to this asset."],
      basis: { kind: "derived", text: "From links" },
    },
    riskExposureTile(a.risks),
  ];
}

/* ------------------------------------------------------------------ headline */

export function itAssetHeadline({ asset: a }: ItAssetInput, _ctx?: Ctx): Seg[] {
  const i = critRank(a.intrinsic_criticality);
  const d = critRank(a.derived_criticality);
  const why = i > d ? "criticality from its own cost and availability" : d > i ? "criticality inherited from the data it hosts" : "own and inherited criticality agree";
  const n = distinctLinked(a.dependencies ?? [], "information_asset").length;
  const v = (a.vulnerabilities ?? []).length;
  const hosts = n ? `hosts ${plural(n, "information asset")}` : "hosts no recorded data";
  const vulns = v ? `${plural(v, "vulnerability", "vulnerabilities")} linked` : "no vulnerabilities linked";
  const crit = a.effective_criticality ? sentenceCase(a.effective_criticality) : "Unrated";
  // "Critical IT asset", never "Critical criticality" (as the third party's "Critical third party").
  return [{ b: crit }, ` IT asset: ${why}; ${hosts}; ${vulns}.`];
}

/* ------------------------------------------------------------------ open points */

const DAY_MS = 86_400_000;

export function itAssetOpenPoints({ asset: a }: ItAssetInput, ctx: Ctx): OpenPoint[] {
  const gov = ctx.gov;
  const gaps: OpenPoint[] = [];
  const notes: OpenPoint[] = [];
  const push = (list: OpenPoint[], p: OpenPoint | null) => {
    if (p) list.push(p);
  };

  if (!a.owner) {
    gaps.push({
      id: "itasset.owning_unit",
      level: "gap",
      text: ["No owning unit: nobody is accountable for this asset."],
      action: { kind: "edit", target: "identity", label: "Assign unit" },
    });
  }
  if (!a.guardian) {
    gaps.push({
      id: "itasset.custodian",
      level: "gap",
      text: ["No custodian named."],
      action: { kind: "edit", target: "identity", label: "Name custodian" },
    });
  }
  if (a.auto_discovered && a.last_seen) {
    const seen = Date.parse(a.last_seen);
    const days = Number.isFinite(seen) ? Math.floor((ctx.now.getTime() - seen) / DAY_MS) : 0;
    if (days > 30) {
      gaps.push({
        id: "itasset.stale_discovery",
        level: "gap",
        text: [`Not seen by ${discoverySourceLabel(a.discovery_source)} for ${days} days.`],
        action: { kind: "section", target: "technical", label: "See discovery" },
      });
    }
  }
  const noRto = !has(a.rto_hours);
  const noRpo = !has(a.rpo_hours);
  if (critRank(a.effective_criticality) >= 3 && (noRto || noRpo)) {
    const missing = noRto && noRpo ? "no RTO or RPO" : noRto ? "no RTO" : "no RPO";
    gaps.push({
      id: "itasset.no_recovery",
      level: "gap",
      text: [`Rated ${(a.effective_criticality || "").toLowerCase()} but ${missing} recorded.`],
      action: { kind: "edit", target: "cost", label: "Set RTO / RPO" },
    });
  }
  push(gaps, approvedWithoutStepPoint("itasset", gov));
  push(gaps, reviewOverduePoint("itasset", a, ctx, "identity"));

  if ((a.dependencies ?? []).length === 0) {
    notes.push({
      id: "itasset.hosts_no_data",
      level: "note",
      text: ["Hosts no information assets"],
      action: { kind: "open", target: "link-info-asset", label: "Link information asset" },
    });
  }
  if (!(Number(a.replacement_cost || 0) > 0)) {
    notes.push({
      id: "itasset.no_cost",
      level: "note",
      text: ["Replacement cost not recorded"],
      action: { kind: "edit", target: "cost", label: "Add cost" },
    });
  }
  push(notes, neverAttestedPoint("itasset", gov));
  return [...gaps, ...notes];
}
