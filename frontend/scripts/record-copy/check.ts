/* The record-copy fixture check (record-page-spec §3.8).

     npm run check:record-copy

   For each lib/record/__fixtures__/*.json:
     {
       "type": "risk",                          // → lib/record/risk.ts: riskTiles / riskOpenPoints / riskHeadline
       "input": { …the endpoint payloads… },    // the type's <Type>Input, captured verbatim
       "ctx": { "now": "2026-09-12T09:00:00Z", "gov": { …GovModel without canWrite… }, "canWrite": true },
       "expect": {                              // each part optional; when present it must match exactly
         "tiles": [{ "key": "inherent", "value": "Critical", "because": "Likelihood 4 × …", "basis": { "kind": "declared", "text": "…" } }],
                                                // a tile may also pin "tone" ("medium", or null for none)
         "points": [{ "id": "risk.owner", "level": "gap", "action": { "kind": "edit", "target": "general" } }],
         "headline": "Breach on inherent 20 — …"
       }
     }
   A point's `text` is optional: when given, the point's sentence must match it.
   A point's `action` is optional: when given, the point's fix must have that kind and
   target (`null` = the point must have no fix), so a routing rule such as B1's "See
   sign-off" versus "Attest…" is pinned, not just the point's presence.
   Invariants for every fixture: exactly 6 tiles; every because non-empty and ≤ 160
   characters; the headline ≤ 160 characters; no tile value "—".

   The check runs in UTC (TZ is pinned below), so day counts such as "Overdue 13 days"
   come out the same on every machine and CI runner.

   Before the fixtures it runs the kit checks: the shared wording in lib/record/text.ts
   and the header meta order (components/record/metaOrder.ts) that every page relies on
   (record-page-spec "v1.1 decisions" D1, D3, D5).

   Runs under Node 22 with --experimental-strip-types (no dependencies): keep this file
   and lib/record/* to erasable TypeScript (no enum, namespace or parameter properties). */

import assert from "node:assert/strict";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { Ctx, Fmt, GovModel, OpenPoint, Seg, TileModel } from "../../lib/record/types";
import { approvalLine, approvalWithoutStepText, exceptionStateText, importedApprovalText, rowActionName, rowLabel, uniqueLabels } from "../../lib/record/text";
import { orderMeta } from "../../components/record/metaOrder";
import { creditedControlLines, type RiskInput } from "../../lib/record/risk";
import { incidentDurationNote } from "../../lib/record/incident";

// Calendar-day wording ("Overdue 13 days") reads the local calendar: pin it, so the
// result does not depend on the machine's timezone. Dates are computed at call time,
// after this line.
process.env.TZ = "UTC";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const FIXTURES = path.join(ROOT, "lib/record/__fixtures__");

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Deterministic formatting: "03 Jul 2027", "03 Jul 2027 18:42" (UTC), "PKR 100,000". */
const fmt: Fmt = {
  date(v) {
    if (v === null || v === undefined || v === "") return "—";
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
    if (!m) return String(v);
    return `${m[3]} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
  },
  dateTime(v) {
    if (v === null || v === undefined || v === "") return "—";
    const d = new Date(v);
    if (Number.isNaN(d.getTime())) return String(v);
    const iso = d.toISOString();
    return `${fmt.date(iso.slice(0, 10))} ${iso.slice(11, 16)}`;
  },
  money(n, currency) {
    if (n === null || n === undefined) return "—";
    return `${(currency || "PKR").toUpperCase()} ${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(n)}`;
  },
};

const flat = (segs: readonly Seg[]) => segs.map((s) => (typeof s === "string" ? s : s.b)).join("");

type Fixture = {
  type: string;
  input: unknown;
  ctx: { now: string; gov: Omit<GovModel, "canWrite">; canWrite?: boolean };
  expect?: {
    tiles?: { key: string; value?: string; tone?: string | null; because?: string; basis?: { kind: string; text: string } }[];
    points?: { id: string; level: string; text?: string; action?: { kind: string; target: string } | null }[];
    headline?: string;
  };
};

type Rules = {
  tiles: (input: unknown, ctx: Ctx) => TileModel[];
  points: (input: unknown, ctx: Ctx) => OpenPoint[];
  headline: (input: unknown, ctx: Ctx) => Seg[];
};

async function rulesFor(type: string): Promise<Rules> {
  const file = path.join(ROOT, "lib/record", `${type}.ts`);
  if (!existsSync(file)) throw new Error(`lib/record/${type}.ts not found`);
  const mod = (await import(pathToFileURL(file).href)) as Record<string, unknown>;
  const pick = <T>(name: string): T => {
    const fn = mod[name];
    if (typeof fn !== "function") throw new Error(`lib/record/${type}.ts must export ${name}()`);
    return fn as T;
  };
  return {
    tiles: pick(`${type}Tiles`),
    points: pick(`${type}OpenPoints`),
    headline: pick(`${type}Headline`),
  };
}

/** Shared wording and order every record type depends on. Returns the failures. */
function kitChecks(): string[] {
  const out: string[] = [];
  const check = (name: string, fn: () => void) => {
    try {
      fn();
    } catch (e) {
      out.push(`${name}: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  const gov: GovModel = { workflowState: "approved", approvalSteps: 0, lastStep: null, lastSubmitAt: null, attestation: null, canWrite: true };
  check("D5 import backfill names nobody", () => {
    const line = approvalLine({ ...gov, lastStep: { action: "import", at: "2026-09-13T01:00:00Z", actor: "system@nexusline", reason: "" } }, fmt);
    assert.equal(line.text, "Imported as approved, no approver recorded");
    assert.equal(line.warn, true);
    assert.equal(importedApprovalText("retired"), "Imported as retired, no approver recorded");
  });
  check("no approval step on file", () => assert.equal(approvalLine(gov, fmt).text, "No approval step on file"));
  check("D3 row action names", () => {
    assert.equal(rowActionName("Unlink", rowLabel("SRV-01", "Core banking host")), "Unlink SRV-01 Core banking host");
    assert.equal(rowActionName("Edit", null), "Edit");
  });
  check("B3 exception state reads in the right tense", () => {
    assert.equal(exceptionStateText("expired", "2026-06-30", fmt), "Expired 30 Jun 2026");
    assert.equal(exceptionStateText("approved", "2027-01-03", fmt), "Approved · expires 03 Jan 2027");
    assert.equal(exceptionStateText("approved", null, fmt), "Approved · no expiry set");
    assert.equal(exceptionStateText("rejected", "2027-01-03", fmt), "Rejected");
    assert.equal(exceptionStateText("approved", "2027-01-03", fmt, { sep: ", ", lower: true }), "approved, expires 03 Jan 2027");
    assert.equal(exceptionStateText(null, "2027-01-03", fmt), null);
  });
  check("D5 the approved-without-step point", () => {
    const imp = { workflowState: "approved" as const, lastStep: { action: "import", at: "2026-09-13T01:00:00Z", actor: "system@nexusline", reason: "" } };
    assert.equal(approvalWithoutStepText(imp, "Approved"), "Imported as approved, no approver recorded.");
    assert.equal(approvalWithoutStepText({ workflowState: "approved", lastStep: null }, "Approved"), "Record approval shows Approved but no approval step is on file.");
  });
  check("D3 unique row labels", () => {
    assert.deepStrictEqual(uniqueLabels(["SRV-01 (hosts)", "SRV-01 (hosts)", "DB-02 (stores)"]), ["SRV-01 (hosts) (1 of 2)", "SRV-01 (hosts) (2 of 2)", "DB-02 (stores)"]);
  });
  check("older API: the credited controls come from the engine's rationale", () => {
    const file = path.join(FIXTURES, "risk-R-002.older-api.json");
    if (!existsSync(file)) return;
    const fx = JSON.parse(readFileSync(file, "utf8")) as { input: RiskInput };
    assert.deepStrictEqual(creditedControlLines(fx.input).map((l) => [l.text, l.untested]), [["A.8.13 Backup & Recovery: rated effective", null]]);
  });
  check("incident durations: a stage not reached yet is a fact, a missing time is named", () => {
    const base = { occurred_at: null, detected_at: "2026-09-12T01:00:00Z", contained_at: null, resolved_at: null, mttd_hours: null, mttc_hours: null, mttr_hours: null };
    assert.equal(incidentDurationNote({ ...base, status: "investigating" }, "mttr", fmt), "Not resolved yet");
    assert.equal(incidentDurationNote({ ...base, status: "investigating" }, "mttc", fmt), "Not contained yet");
    assert.equal(incidentDurationNote({ ...base, status: "contained" }, "mttc", fmt), "Needs Contained");
    assert.equal(incidentDurationNote({ ...base, status: "investigating" }, "mttd", fmt), "Needs Occurred");
  });
  check("D1 status first, approval second", () => {
    const m = (key: string, label: string) => ({ key, label });
    const issue = orderMeta({ meta: [m("severity", "Severity"), m("status", "Issue status"), m("owner", "Owner"), m("approval", "Record approval")] });
    assert.deepStrictEqual(issue.items.map((x) => x.key), ["status", "approval", "severity", "owner"]);
    const slots = orderMeta({ status: m("status", "Review status"), meta: [m("owner", "Business owner")] }, m("approval", "Record approval"));
    assert.deepStrictEqual(slots.items.map((x) => x.key), ["status", "approval", "owner"]);
    assert.deepStrictEqual(orderMeta({ approval: null, meta: [m("status", "Risk status"), m("approval", "Record approval")] }).items.map((x) => x.key), ["status"]);
  });
  return out;
}

async function main() {
  const kit = kitChecks();
  if (kit.length) {
    console.error(`FAIL kit checks\n${kit.join("\n")}`);
    process.exitCode = 1;
  } else {
    console.log("ok   kit checks (shared wording and meta order)");
  }
  const files = existsSync(FIXTURES) ? readdirSync(FIXTURES).filter((f) => f.endsWith(".json")).sort() : [];
  if (files.length === 0) {
    console.log("record-copy: no fixtures in lib/record/__fixtures__ yet");
    return;
  }
  let failed = 0;
  for (const f of files) {
    const fx = JSON.parse(readFileSync(path.join(FIXTURES, f), "utf8")) as Fixture;
    try {
      const rules = await rulesFor(fx.type);
      const ctx: Ctx = { fmt, now: new Date(fx.ctx.now), gov: { ...fx.ctx.gov, canWrite: fx.ctx.canWrite ?? true } };
      const tiles = rules.tiles(fx.input, ctx);
      const points = rules.points(fx.input, ctx);
      const headline = flat(rules.headline(fx.input, ctx));

      assert.equal(tiles.length, 6, "exactly 6 tiles");
      for (const t of tiles) {
        const because = flat(t.because);
        assert.ok(because.trim().length > 0, `${t.key}: because is empty`);
        assert.ok(because.length <= 160, `${t.key}: because is ${because.length} characters (max 160)`);
        assert.notEqual(t.value.text.trim(), "—", `${t.key}: value is "—"`);
      }
      assert.ok(headline.length <= 160, `headline is ${headline.length} characters (max 160)`);

      const exp = fx.expect ?? {};
      if (exp.tiles) {
        const got = tiles.map((t, i) => {
          const want = exp.tiles?.[i];
          const out: Record<string, unknown> = { key: t.key };
          if (!want || want.value !== undefined) out.value = t.value.text;
          // Optional: the value's tone (null = none), so a colour rule such as "green only
          // when everyone has acknowledged" is pinned, not just the words.
          if (want && want.tone !== undefined) out.tone = t.value.tone ?? null;
          if (!want || want.because !== undefined) out.because = flat(t.because);
          if (!want || want.basis !== undefined) out.basis = { kind: t.basis.kind, text: t.basis.text };
          return out;
        });
        assert.deepStrictEqual(got, exp.tiles);
      }
      if (exp.points) {
        const got = points.map((p, i) => {
          const out: Record<string, unknown> = { id: p.id, level: p.level };
          const want = exp.points?.[i];
          if (want && want.text !== undefined) out.text = flat(p.text);
          if (want && want.action !== undefined) out.action = p.action ? { kind: p.action.kind, target: p.action.target } : null;
          return out;
        });
        assert.deepStrictEqual(got, exp.points);
      }
      if (exp.headline !== undefined) assert.equal(headline, exp.headline);
      console.log(`ok   ${f}`);
    } catch (e) {
      failed++;
      console.error(`FAIL ${f}\n${e instanceof Error ? e.message : String(e)}`);
    }
  }
  if (failed) {
    console.error(`record-copy: ${failed} of ${files.length} fixtures failed`);
    process.exitCode = 1;
  } else {
    console.log(`record-copy: ${files.length} fixtures passed`);
  }
}

main();
