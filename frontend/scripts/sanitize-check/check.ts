/* The sanitiser check (lib/sanitize.ts).

     npm run check:sanitize

   Runs the SAME file twice:
   1. In Node (no DOM): the strip-everything path. Every output may contain only <br>
      as markup; htmlToText, safeLinkUrl, linkFromUserInput and sanitizePaste give the
      expected values.
   2. In real Chromium (Playwright's bundled browser, resolved from frontend/node_modules):
      lib/sanitize.ts is loaded into a page with its types stripped (node:module
      stripTypeScriptTypes), so the DOMParser path that runs in the app is the one tested
      — not a reimplementation. Each case must give its exact expected output, sanitising
      twice must change nothing, and sanitising must be inert (no handler runs, no
      request leaves). Then every output (browser and Node) is put into a LIVE document
      with innerHTML, the way RichText and RichTextView use it, and must contain only
      allowlisted elements and attributes, only http(s)/mailto links by the browser's own
      URL parser, and must neither run a handler nor issue a request.

   Exit code 1 on any failure. When Playwright or its Chromium is missing the browser
   half fails too (install it with `npx playwright install chromium`), unless
   SANITIZE_CHECK_NODE_ONLY=1 is set, which runs the Node half alone and says so.

   Runs under Node 22 with --experimental-strip-types (no dependencies). */

import { readFileSync } from "node:fs";
import * as nodeModule from "node:module";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { CASES, PASTE_CASES, URL_CASES, USER_LINK_CASES } from "./cases";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
/** SANITIZE_CHECK_FILE points the check at another copy (used to prove the check fails
 *  on a broken sanitiser); the default is the real lib/sanitize.ts. */
const SANITIZE_TS = process.env.SANITIZE_CHECK_FILE ? path.resolve(process.env.SANITIZE_CHECK_FILE) : path.join(ROOT, "lib/sanitize.ts");
const ORIGIN = "http://sanitize-check.test";

const { ALLOWED_ATTRIBUTES, ALLOWED_TAGS, htmlToText, linkFromUserInput, safeLinkUrl, sanitizeHtml, sanitizePaste } =
  (await import(pathToFileURL(SANITIZE_TS).href)) as typeof import("../../lib/sanitize");

let failures = 0;
let checks = 0;
function expectEq(what: string, got: unknown, want: unknown) {
  checks++;
  if (got !== want) {
    failures++;
    console.error(`  FAIL ${what}\n       got:  ${JSON.stringify(got)}\n       want: ${JSON.stringify(want)}`);
  }
}
function expectTrue(what: string, ok: boolean, detail = "") {
  checks++;
  if (!ok) {
    failures++;
    console.error(`  FAIL ${what}${detail ? `\n       ${detail}` : ""}`);
  }
}

/* ------------------------------------------------------------------ Node half ----- */

console.log(`sanitize-check: ${path.relative(ROOT, SANITIZE_TS)} in Node (no DOM, strip-everything path)`);
expectTrue("Node has no DOMParser (the fallback path is what runs here)", typeof (globalThis as { DOMParser?: unknown }).DOMParser === "undefined");

const nodeOutputs: { name: string; out: string }[] = [];
for (const c of CASES) {
  const out = sanitizeHtml(c.input);
  nodeOutputs.push({ name: `node: ${c.name}`, out });
  expectTrue(`node sanitizeHtml(${c.name}) has no markup but <br>`, !/[<>]/.test(out.replace(/<br>/g, "")), out);
  if (c.text !== undefined) expectEq(`htmlToText(${c.name})`, htmlToText(c.input), c.text);
}
for (const [input, want] of URL_CASES) expectEq(`safeLinkUrl(${JSON.stringify(input)})`, safeLinkUrl(input), want);
for (const [input, want] of USER_LINK_CASES) expectEq(`linkFromUserInput(${JSON.stringify(input)})`, linkFromUserInput(input), want);
for (const p of PASTE_CASES) expectEq(`node sanitizePaste(${p.name})`, sanitizePaste(p.input), p.node);
expectEq("sanitizeHtml(null)", sanitizeHtml(null), "");
expectEq("sanitizeHtml(undefined)", sanitizeHtml(undefined), "");
const nodeFailures = failures;
console.log(`  ${checks} checks, ${nodeFailures} failed`);

/* --------------------------------------------------------------- browser half ----- */

type Browserish = {
  newPage(): Promise<Pageish>;
  close(): Promise<void>;
};
type Routeish = { request(): { url(): string }; fulfill(r: { status: number; contentType: string; body: string }): Promise<void>; abort(): Promise<void> };
type Pageish = {
  route(url: string, handler: (route: Routeish) => unknown): Promise<void>;
  goto(url: string): Promise<unknown>;
  addScriptTag(o: { content: string; type?: string }): Promise<unknown>;
  waitForFunction(fn: string, arg?: unknown, opts?: { timeout?: number }): Promise<unknown>;
  evaluate<R, A>(fn: (arg: A) => R | Promise<R>, arg: A): Promise<R>;
  on(event: "pageerror", fn: (e: Error) => void): void;
};

async function loadChromium(): Promise<{ launch(): Promise<Browserish> } | string> {
  try {
    const req = createRequire(import.meta.url);
    const pw = req("playwright") as { chromium: { launch(): Promise<Browserish> } };
    return pw.chromium;
  } catch (e) {
    return `playwright is not installed in frontend/node_modules (${e instanceof Error ? e.message.split("\n")[0] : e})`;
  }
}

function strippedSanitizer(): string {
  const strip = (nodeModule as unknown as { stripTypeScriptTypes?: (src: string, o?: { mode?: string }) => string }).stripTypeScriptTypes;
  if (typeof strip !== "function") throw new Error("node:module stripTypeScriptTypes is unavailable (Node 22.13+ needed)");
  return strip(readFileSync(SANITIZE_TS, "utf8"), { mode: "strip" });
}

type BrowserResult = { name: string; out: string; again: string; text: string };

/** How long one browser case may take before the check calls it hung. */
const CASE_TIMEOUT_MS = 5000;
const TIMED_OUT = Symbol("timed out");
function withTimeout<T>(p: Promise<T>, ms: number): Promise<T | typeof TIMED_OUT> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const t = new Promise<typeof TIMED_OUT>((resolve) => {
    timer = setTimeout(() => resolve(TIMED_OUT), ms);
  });
  return Promise.race([p, t]).finally(() => clearTimeout(timer));
}
type SinkReport = { problems: string[]; xss: number; tagCount: number };

async function browserHalf(): Promise<void> {
  console.log("sanitize-check: Chromium (DOMParser path, then a live document)");
  const chromium = await loadChromium();
  if (typeof chromium === "string") throw new Error(chromium);
  const browser = await chromium.launch();
  const before = failures;
  const startChecks = checks;
  try {
    const page = await browser.newPage();
    const requests: string[] = [];
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(e.message));
    await page.route("**/*", (route) => {
      const url = route.request().url();
      if (url === `${ORIGIN}/`) {
        return route.fulfill({
          status: 200,
          contentType: "text/html",
          body: "<!doctype html><html><head><title>sanitize-check</title></head><body><div id=sink></div></body></html>",
        });
      }
      requests.push(url);
      return route.abort();
    });
    await page.goto(`${ORIGIN}/`);
    // Every payload calls __xss++ or alert(): both are counted.
    await page.evaluate(() => {
      const w = window as unknown as { __xss: number; alert: (m?: unknown) => void };
      w.__xss = 0;
      w.alert = () => {
        w.__xss++;
      };
    }, null);
    const exported = "sanitizeHtml, htmlToText, safeLinkUrl, linkFromUserInput, sanitizePaste, plainTextHtml, ALLOWED_TAGS, ALLOWED_ATTRIBUTES";
    await page.addScriptTag({ type: "module", content: `${strippedSanitizer()}\nwindow.__S = { ${exported} };` });
    await page.waitForFunction("!!window.__S", undefined, { timeout: 10000 });

    type S = {
      sanitizeHtml(h: string): string;
      htmlToText(h: string): string;
      safeLinkUrl(u: string | null): string | null;
      linkFromUserInput(u: string): string | null;
      sanitizePaste(d: { html?: string; text?: string }): string;
    };
    type W = { __S: S; __xss: number };

    const usesDom = await page.evaluate(() => typeof DOMParser === "function" && (window as unknown as W).__S.sanitizeHtml("<b>x</b>") === "<b>x</b>", null);
    expectTrue("browser: the DOMParser path is the one running", usesDom);

    // 1. Sanitise every case (inert: nothing may run or load while parsing). One
    //    evaluate per case with a timeout, so a case that hangs the walk fails the check
    //    by name instead of hanging it.
    const results: BrowserResult[] = [];
    for (const c of CASES) {
      const r = await withTimeout(
        page.evaluate(
          (arg: { name: string; input: string }) => {
            const s = (window as unknown as W).__S;
            const out = s.sanitizeHtml(arg.input);
            return { name: arg.name, out, again: s.sanitizeHtml(out), text: s.htmlToText(arg.input) };
          },
          { name: c.name, input: c.input },
        ),
        CASE_TIMEOUT_MS,
      );
      if (r === TIMED_OUT) {
        expectTrue(`browser sanitizeHtml(${c.name}) returns`, false, `no result after ${CASE_TIMEOUT_MS} ms: the page is hung`);
        throw new Error(`sanitizeHtml hung on "${c.name}"; the rest of the browser half cannot run`);
      }
      results.push(r as BrowserResult);
    }
    CASES.forEach((c, i) => {
      const r = results[i] as BrowserResult;
      if (c.html !== undefined) expectEq(`browser sanitizeHtml(${c.name})`, r.out, c.html);
      expectEq(`browser idempotent (${c.name})`, r.again, r.out);
      if (c.text !== undefined) expectEq(`browser htmlToText(${c.name})`, r.text, c.text);
    });
    const urlGot = await page.evaluate((inputs: (string | null)[]) => inputs.map((u) => (window as unknown as W).__S.safeLinkUrl(u)), URL_CASES.map((u) => u[0]));
    URL_CASES.forEach(([input, want], i) => expectEq(`browser safeLinkUrl(${JSON.stringify(input)})`, urlGot[i], want));
    const userGot = await page.evaluate((inputs: string[]) => inputs.map((u) => (window as unknown as W).__S.linkFromUserInput(u)), USER_LINK_CASES.map((u) => u[0]));
    USER_LINK_CASES.forEach(([input, want], i) => expectEq(`browser linkFromUserInput(${JSON.stringify(input)})`, userGot[i], want));
    const pasteGot = await page.evaluate((inputs: { html?: string; text?: string }[]) => inputs.map((d) => (window as unknown as W).__S.sanitizePaste(d)), PASTE_CASES.map((p) => p.input));
    PASTE_CASES.forEach((p, i) => expectEq(`browser sanitizePaste(${p.name})`, pasteGot[i], p.html));

    // Deep nesting and a large document: no crash, bounded output, fast enough per keystroke.
    const stress = await page.evaluate(() => {
      const s = (window as unknown as W).__S;
      const deep = "<div>".repeat(3000) + "deep" + "</div>".repeat(3000);
      const d = s.sanitizeHtml(deep);
      const para = "<p>Policy text with <b>bold</b>, <i>italic</i> and a <a href='https://example.com'>link</a>.</p>";
      const big = para.repeat(Math.ceil(200000 / para.length));
      const t0 = performance.now();
      const b = s.sanitizeHtml(big);
      const ms = performance.now() - t0;
      return { deepHasText: d.includes("deep"), deepTags: (d.match(/<div>/g) || []).length, bigLen: big.length, bigOutLen: b.length, ms };
    }, null);
    expectTrue("browser: 3000-deep nesting keeps its text", stress.deepHasText);
    expectTrue("browser: nesting is capped in the output", stress.deepTags <= 64, `${stress.deepTags} nested <div>`);
    expectTrue(`browser: a ${Math.round(stress.bigLen / 1000)} KB document sanitises in < 250 ms`, stress.ms < 250, `${stress.ms.toFixed(1)} ms`);

    await new Promise((r) => setTimeout(r, 300));
    const xssAfterParse = await page.evaluate(() => (window as unknown as W).__xss, null);
    expectEq("browser: nothing ran while sanitising (DOMParser is inert)", xssAfterParse, 0);
    expectEq("browser: nothing was requested while sanitising", requests.length, 0);

    // 2. Put every output into a live document (innerHTML, as RichText / RichTextView do).
    const outputs = [...results.map((r) => ({ name: `browser: ${r.name}`, out: r.out })), ...nodeOutputs];
    const report = (await page.evaluate(
      async (arg: { outputs: { name: string; out: string }[]; tags: string[]; attrs: Record<string, readonly string[]> }) => {
        const sink = document.getElementById("sink") as HTMLElement;
        const problems: string[] = [];
        let tagCount = 0;
        for (const o of arg.outputs) {
          const box = document.createElement("div");
          box.innerHTML = o.out; // live: a surviving handler would run, a resource would load
          sink.appendChild(box);
          for (const el of Array.from(box.querySelectorAll("*"))) {
            tagCount++;
            const tag = el.localName;
            if (el.namespaceURI !== "http://www.w3.org/1999/xhtml") problems.push(`${o.name}: foreign-namespace <${tag}>`);
            if (!arg.tags.includes(tag)) problems.push(`${o.name}: element <${tag}>`);
            for (const a of Array.from(el.attributes)) {
              if (!(arg.attrs[tag] ?? []).includes(a.name)) problems.push(`${o.name}: attribute ${tag}[${a.name}]`);
            }
            if (tag === "a") {
              const a = el as HTMLAnchorElement;
              let protocol = "";
              try {
                protocol = new URL(a.href).protocol;
              } catch {
                protocol = "(unparseable)";
              }
              if (!["http:", "https:", "mailto:"].includes(protocol)) problems.push(`${o.name}: link protocol ${protocol}`);
              if (a.target !== "_blank") problems.push(`${o.name}: link target ${a.target}`);
              if (!/\bnoopener\b/.test(a.rel) || !/\bnoreferrer\b/.test(a.rel)) problems.push(`${o.name}: link rel ${a.rel}`);
            }
          }
        }
        // Poke everything a surviving handler could hang off.
        for (const el of Array.from(sink.querySelectorAll("*"))) {
          for (const type of ["mouseover", "mouseenter", "focus", "blur", "animationstart", "toggle", "load", "error"]) {
            el.dispatchEvent(new Event(type, { bubbles: false }));
          }
        }
        await new Promise((r) => setTimeout(r, 500));
        return { problems, xss: (window as unknown as W).__xss, tagCount };
      },
      { outputs, tags: [...ALLOWED_TAGS], attrs: ALLOWED_ATTRIBUTES as Record<string, readonly string[]> },
    )) as SinkReport;
    for (const p of report.problems) expectTrue(`live document: ${p}`, false);
    checks++;
    expectEq("live document: no handler ran", report.xss, 0);
    expectEq("live document: nothing was requested", requests.length, 0);
    if (requests.length) console.error(`       requests: ${requests.slice(0, 5).join(", ")}`);
    expectEq("browser: no page errors", pageErrors.join(" | "), "");
    console.log(`  ${checks - startChecks} checks (${outputs.length} outputs, ${report.tagCount} elements in the live document), ${failures - before} failed`);
  } finally {
    await withTimeout(browser.close(), 10000);
  }
}

try {
  await browserHalf();
} catch (e) {
  const msg = e instanceof Error ? e.message.split("\n")[0] : String(e);
  if (process.env.SANITIZE_CHECK_NODE_ONLY === "1") {
    console.warn(`  SKIPPED the browser half (SANITIZE_CHECK_NODE_ONLY=1): ${msg}`);
  } else {
    failures++;
    const hint = /hung/.test(msg) ? "" : "\n       Install Chromium with `npx playwright install chromium`, or set SANITIZE_CHECK_NODE_ONLY=1 to run only the Node half.";
    console.error(`  FAIL the browser half could not run: ${msg}${hint}`);
  }
}

if (failures > 0) {
  console.error(`sanitize-check: ${failures} of ${checks} checks FAILED`);
  process.exit(1);
}
console.log(`sanitize-check: all ${checks} checks passed (${CASES.length} HTML cases, ${URL_CASES.length} URL cases, ${USER_LINK_CASES.length} link-input cases, ${PASTE_CASES.length} paste cases).`);
