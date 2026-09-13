/* Allowlist HTML sanitiser for stored rich text: policy bodies, incident root cause and
   lessons learned, risk treatment descriptions, exception rationales, control
   descriptions, and anything else the RichText editor wrote. No dependencies.

     import { sanitizeHtml } from "@/lib/sanitize";
     <div dangerouslySetInnerHTML={{ __html: sanitizeHtml(stored) }} />
     // better: <RichTextView html={stored} /> from "@/components/RichText"

   Why it exists: rich text is stored exactly as the browser's contentEditable produced
   it (or as an attacker POSTed it), and nothing on the server cleans it. Before this
   module, a policy body carrying `<img src=x onerror=…>` ran script the moment Edit
   opened. Every place that turns stored HTML back into DOM (the editor loading a value,
   a paste, a read-only view) must pass it through `sanitizeHtml` first.

   Policy (an allowlist: anything not named here is removed)
   - Kept, with no attributes: p, br, strong, b, em, i, u, s, ul, ol, li, h1–h4,
     blockquote, code, pre, table, thead, tbody, tfoot, tr, th, td, caption, and also
     div, hr, sub and sup. `div` is kept because Chrome's contentEditable writes one div
     per line.
   - Renamed: strike/del → s, ins → u, h5/h6 → h4, tt/kbd/samp → code, listing → pre,
     menu → ul, and block containers pasted from other tools (section, article, header,
     footer, main, aside, nav, figure, figcaption, address, center, details, summary, dl,
     dt, dd, hgroup, search) → div, so their line breaks survive.
   - `a` keeps only an http:, https: or mailto: `href` (see `safeLinkUrl`: checked after
     the parser has decoded entities and after removing the whitespace and control
     characters browsers ignore inside a URL, so `java&#9;script:`, `javascript&colon;`
     and `jav&#x0A;ascript:` are caught), and always gets target="_blank" and
     rel="noopener noreferrer". A link with any other URL (javascript:, vbscript:, data:,
     relative, protocol-relative) keeps only its text.
   - `th` / `td` keep `colspan` / `rowspan` when they are whole numbers 1–100.
   - Removed together with their content: script, style, template, svg, math, iframe,
     frame(set), object, embed, applet, noscript, noembed, noframes, img, picture,
     video, audio, canvas, map, form controls (input, button, textarea, select, option,
     datalist, output, meter, progress, keygen), head, title, meta, link, base, dialog,
     portal, fencedframe, xmp and plaintext (DROP below). Anything outside the HTML
     namespace (SVG, MathML and everything inside them) is removed the same way.
   - Every other element (span, font, form, label, marquee, custom elements …) is
     unwrapped: its text and allowed children stay, the element goes.
   - Every attribute not named above is dropped: all on* handlers, style, class, id,
     name, src, srcset, formaction, xlink:href, …
   - Comments, doctypes, CDATA and processing instructions are dropped.

   Images: `img` is removed, not allowed with an http(s) src. The editor has no image
   button, a remote image in a bank's policy text is a web beacon that reports every
   reader's IP address and reading time to whoever hosts it, and `data:` images are a
   known carrier for oversized payloads. Put images in attachments.

   How: the output is BUILT from the allowlist (tag names from the tables below,
   attribute values and text re-escaped); it is never re-serialised from the input, so
   what the browser finally parses is exactly what was checked. There is no
   parser-differential or mutation-XSS path (noscript, template, svg/math namespace
   confusion) because none of those elements are ever emitted and no input markup is
   copied through. The walk reads tree pointers and node facts through the DOM
   prototypes (never `node.nextSibling`, which a `<form>`'s named controls can shadow and
   so loop the walk forever) and gives up past MAX_NODES, falling back to the text form.

   Two environments, one guarantee:
   - Browser: DOMParser (an inert document: nothing loads, no handler runs, scripting
     is off) gives the browser's own parse; the tree is walked and rebuilt.
   - No DOM (server rendering, Node): strip everything. The output is the input's
     visible text, escaped, with `<br>` between blocks, and no other markup. RichTextView
     renders that on the server and during hydration, then swaps in the formatted
     version once mounted.

   Check: `npm run check:sanitize` (scripts/sanitize-check) runs every case through this
   file in Node AND in real Chromium (Playwright), then puts the browser output into a
   live document to prove that nothing fires. Keep this file erasable TypeScript (no
   enum, namespace or parameter properties): the check runs it with type stripping. */

/* ------------------------------------------------------------------ policy ----- */

/** Elements kept as themselves. */
const KEEP = new Set([
  "p", "br", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li", "h1", "h2", "h3", "h4",
  "blockquote", "code", "pre", "a", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
  "div", "hr", "sub", "sup",
]);

/** Elements kept under another (allowed) name. */
const RENAME: Record<string, string> = {
  strike: "s", del: "s", ins: "u", h5: "h4", h6: "h4", tt: "code", kbd: "code", samp: "code",
  listing: "pre", menu: "ul",
  section: "div", article: "div", header: "div", footer: "div", main: "div", aside: "div", nav: "div",
  figure: "div", figcaption: "div", address: "div", center: "div", details: "div", summary: "div",
  dl: "div", dt: "div", dd: "div", hgroup: "div", search: "div",
};

/** Elements removed together with everything inside them. */
const DROP = new Set([
  "script", "style", "template", "svg", "math",
  "iframe", "frame", "frameset", "noframes", "object", "embed", "applet", "param", "noscript", "noembed",
  "img", "image", "picture", "source", "track", "video", "audio", "canvas", "map", "area",
  "input", "button", "textarea", "select", "option", "optgroup", "datalist", "output", "meter", "progress", "keygen",
  "head", "title", "meta", "link", "base", "basefont", "bgsound",
  "xmp", "plaintext", "dialog", "portal", "fencedframe",
]);

/** Output elements that have no end tag. */
const VOID_OUT = new Set(["br", "hr"]);

/** Deeper than this, elements are unwrapped (their text stays): no pathological nesting
 *  in the output, and no recursion blow-up. */
const MAX_DEPTH = 64;

/** Every element name `sanitizeHtml` can emit. */
export const ALLOWED_TAGS: ReadonlySet<string> = new Set([...KEEP, ...Object.values(RENAME)]);

/** Every attribute `sanitizeHtml` can emit, per element. */
export const ALLOWED_ATTRIBUTES: Readonly<Record<string, readonly string[]>> = {
  a: ["href", "target", "rel"],
  td: ["colspan", "rowspan"],
  th: ["colspan", "rowspan"],
};

type Decision = { kind: "keep"; name: string } | { kind: "drop" } | { kind: "unwrap" };

function decide(tag: string): Decision {
  const t = tag.toLowerCase();
  if (DROP.has(t)) return { kind: "drop" };
  if (KEEP.has(t)) return { kind: "keep", name: t };
  const renamed = Object.prototype.hasOwnProperty.call(RENAME, t) ? RENAME[t] : undefined;
  if (renamed) return { kind: "keep", name: renamed };
  return { kind: "unwrap" };
}

/* ----------------------------------------------------------------- escaping ----- */

/** Escape text for use between tags. */
export function escapeText(s: string): string {
  return s.replace(/[&<>]/g, (c) => (c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"));
}

/** Escape text for use inside a double- or single-quoted attribute value. */
export function escapeAttr(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    c === "&" ? "&amp;" : c === "<" ? "&lt;" : c === ">" ? "&gt;" : c === '"' ? "&quot;" : "&#39;",
  );
}

/* --------------------------------------------------------------------- URLs ----- */

/** A regex matching any code point in the given inclusive ranges. Built from numbers so
 *  that no invisible character ever has to appear in this source file. */
function charClass(ranges: [number, number][], flags = ""): RegExp {
  const esc = (c: number) => (c < 0x100 ? "\\x" + c.toString(16).padStart(2, "0") : "\\u" + c.toString(16).padStart(4, "0"));
  return new RegExp(`[${ranges.map(([a, b]) => (a === b ? esc(a) : `${esc(a)}-${esc(b)}`)).join("")}]`, flags);
}

/** Leading / trailing C0 controls and spaces: the URL parser strips these. */
const URL_EDGE = /^[\x00-\x20]+|[\x00-\x20]+$/g;
/** Tab, LF and CR: the URL parser removes these anywhere in the URL. */
const URL_TAB_NEWLINE = /[\t\n\r]/g;
/** Characters no legitimate link contains, and that can hide a scheme from a naive
 *  check: C0 and C1 controls, DEL, no-break and soft hyphen, zero-width and bidi marks,
 *  line / paragraph separators, invisible fillers, variation selectors, BOM. A URL that
 *  still contains one after the browser's own stripping is refused outright. */
const URL_FORBIDDEN = charClass([
  [0x00, 0x1f], [0x7f, 0xa0], [0xad, 0xad], [0x61c, 0x61c], [0x115f, 0x1160], [0x17b4, 0x17b5], [0x180b, 0x180f],
  [0x200b, 0x200f], [0x2028, 0x202e], [0x2060, 0x206f], [0x3164, 0x3164], [0xfe00, 0xfe0f], [0xfeff, 0xfeff], [0xffa0, 0xffa0],
]);

/**
 * The URL a link may carry: `http://host…`, `https://host…` or `mailto:…`, else null.
 * The value is first reduced the way the browser's URL parser reduces it (edge
 * whitespace and controls trimmed, tabs and newlines removed), so `java\tscript:` and
 * ` javascript:` are judged as the javascript: URLs they are; anything that still
 * carries a control or invisible character is refused. The scheme test is on that
 * reduced value with spaces removed, lower-cased, and must be one of the three.
 *
 * Use it for any stored URL rendered as a link — `<a href={safeLinkUrl(v.website) ??
 * undefined}>` — because React renders a `javascript:` href as written and it runs on
 * click. Inside stored rich text the parser has already decoded entities, so
 * `javascript&colon;` and `&#106;avascript:` arrive here decoded.
 */
export function safeLinkUrl(raw: string | null | undefined): string | null {
  if (raw === null || raw === undefined) return null;
  const value = String(raw).replace(URL_EDGE, "").replace(URL_TAB_NEWLINE, "");
  if (!value || value.length > 4096 || URL_FORBIDDEN.test(value)) return null;
  const probe = value.replace(/ /g, "").toLowerCase();
  if (/^https?:\/\/[^/\\]/.test(probe)) return value;
  if (/^mailto:[^\s/\\]/.test(probe)) return value;
  return null;
}

/**
 * What the editor's "Insert link" accepts from a person typing a URL: a safe URL as
 * is, `www.example.com` or `example.com/x` as https://…, and `name@bank.com` as
 * mailto:…. Anything else (javascript:, data:, a relative path) → null.
 */
export function linkFromUserInput(raw: string | null | undefined): string | null {
  const v = (raw ?? "").trim();
  if (!v) return null;
  const direct = safeLinkUrl(v);
  if (direct) return direct;
  if (/^[a-z][a-z0-9+.-]*:/i.test(v)) return null; // some other scheme
  if (/^[^\s@/:]+@[^\s@/:]+\.[^\s@/:]+$/.test(v)) return safeLinkUrl(`mailto:${v}`);
  if (/^(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?::\d+)?(?:[/?#]\S*)?$/i.test(v)) return safeLinkUrl(`https://${v}`);
  return null;
}

function cleanSpan(v: string | null): string | null {
  if (v === null) return null;
  const t = v.trim();
  if (!/^\d{1,3}$/.test(t)) return null;
  const n = Number(t);
  return n >= 1 && n <= 100 ? String(n) : null;
}

/** The opening tag for an allowed element, built from its (already decoded) attributes;
 *  null when the element must be unwrapped instead (a link whose URL is not allowed). */
function openTag(name: string, attr: (n: string) => string | null): string | null {
  if (name === "a") {
    const href = safeLinkUrl(attr("href"));
    if (!href) return null;
    return `<a href="${escapeAttr(href)}" target="_blank" rel="noopener noreferrer">`;
  }
  if (name === "td" || name === "th") {
    const colspan = cleanSpan(attr("colspan"));
    const rowspan = cleanSpan(attr("rowspan"));
    return `<${name}${colspan ? ` colspan="${colspan}"` : ""}${rowspan ? ` rowspan="${rowspan}"` : ""}>`;
  }
  return `<${name}>`;
}

/* ------------------------------------------------------------ browser path ----- */

const HTML_NS = "http://www.w3.org/1999/xhtml";

/** More nodes than this in one value and the walk gives up (the caller falls back to
 *  the text form): a guard against any traversal that fails to terminate. */
const MAX_NODES = 200000;

type DomReaders = {
  firstChild: (n: Node) => Node | null;
  nextSibling: (n: Node) => Node | null;
  nodeType: (n: Node) => number;
  nodeValue: (n: Node) => string | null;
  nodeName: (n: Node) => string;
  namespaceURI: (el: Element) => string | null;
  localName: (el: Element) => string;
  getAttribute: (el: Element, name: string) => string | null;
};

/** Tree pointers and node facts read through the DOM prototypes, never through the node.
 *  A `<form>` exposes its named controls as properties that shadow the built-ins
 *  (`<input form=f name=nextSibling>` makes `form.nextSibling` that input, which loops a
 *  naive walk forever; `name=localName`, `name=getAttribute`, … break it otherwise), so
 *  the walk must not ask the element. Built lazily: only the browser path needs a DOM. */
function domReaders(): DomReaders {
  const getter = (proto: object, key: string): ((this: unknown) => unknown) => {
    const d = Object.getOwnPropertyDescriptor(proto, key);
    if (!d || typeof d.get !== "function") throw new Error(`no ${key} getter`);
    return d.get as (this: unknown) => unknown;
  };
  const NodeP = Node.prototype;
  const ElP = Element.prototype;
  const first = getter(NodeP, "firstChild");
  const next = getter(NodeP, "nextSibling");
  const type = getter(NodeP, "nodeType");
  const value = getter(NodeP, "nodeValue");
  const nname = getter(NodeP, "nodeName");
  const ns = getter(ElP, "namespaceURI");
  const local = getter(ElP, "localName");
  const getAttr = ElP.getAttribute;
  return {
    firstChild: (n) => first.call(n) as Node | null,
    nextSibling: (n) => next.call(n) as Node | null,
    nodeType: (n) => type.call(n) as number,
    nodeValue: (n) => value.call(n) as string | null,
    nodeName: (n) => nname.call(n) as string,
    namespaceURI: (el) => ns.call(el) as string | null,
    localName: (el) => local.call(el) as string,
    getAttribute: (el, name) => getAttr.call(el, name),
  };
}

/** Rebuild the children of `root` from the allowlist. Throws (the caller then falls
 *  back to the text form) when the tree is larger than MAX_NODES. */
function rebuild(root: Node): string {
  const dom = domReaders();
  const out: string[] = [];
  let visited = 0;
  const walk = (node: Node, depth: number) => {
    for (let child = dom.firstChild(node); child; child = dom.nextSibling(child)) {
      if (++visited > MAX_NODES) throw new Error("sanitizeHtml: too many nodes");
      const type = dom.nodeType(child);
      if (type === 3) {
        out.push(escapeText(dom.nodeValue(child) ?? ""));
        continue;
      }
      if (type !== 1) continue; // comments, processing instructions, CDATA
      const el = child as Element;
      // SVG / MathML (and everything inside them) never survive, whatever the tag is called.
      if (dom.namespaceURI(el) !== HTML_NS) continue;
      const d = decide(String(dom.localName(el) || dom.nodeName(el)));
      if (d.kind === "drop") continue;
      const name = d.kind === "keep" && depth < MAX_DEPTH ? d.name : null;
      const open = name === null ? null : openTag(name, (n) => dom.getAttribute(el, n));
      if (name === null || open === null) {
        walk(el, depth + 1); // unwrap: keep the text and allowed children
        continue;
      }
      out.push(open);
      if (VOID_OUT.has(name)) continue;
      walk(el, depth + 1);
      out.push(`</${name}>`);
    }
  };
  walk(root, 0);
  return out.join("");
}

/** An inert parse of `html` (nothing loads, nothing runs), or null without a DOM. */
function parseInert(html: string): Document | null {
  if (typeof DOMParser === "undefined") return null;
  try {
    // Standards mode, and straight into <body> so leading <style>/<meta>/<title> are
    // parsed where the walk sees (and drops) them.
    return new DOMParser().parseFromString(`<!DOCTYPE html><html><head></head><body>${html}`, "text/html");
  } catch {
    return null;
  }
}

/* ------------------------------------------------------ no-DOM path (text) ----- */

/** Elements whose end tag is the only way out (their content is never markup). */
const RAW_TEXT = new Set(["script", "style", "xmp", "iframe", "noembed", "noframes", "noscript", "textarea", "title"]);

/** Void elements: a start tag with nothing to skip. */
const VOID_IN = new Set([
  "area", "base", "basefont", "bgsound", "br", "col", "embed", "frame", "hr", "image", "img", "input",
  "keygen", "link", "meta", "param", "source", "track", "wbr",
]);

/** Elements whose start or end marks a line break in the text. */
const BLOCK = new Set([
  "br", "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table", "tr",
  "caption", "hr", "section", "article", "header", "footer", "main", "aside", "nav", "figure", "figcaption",
  "address", "center", "details", "summary", "dl", "dt", "dd", "hgroup", "search", "listing", "menu", "form", "fieldset",
]);

const cp = (c: number) => String.fromCharCode(c);
const NAMED: Record<string, string> = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", colon: ":", Tab: "\t", NewLine: "\n",
  sol: "/", lpar: "(", rpar: ")", period: ".", comma: ",", excl: "!", num: "#", percnt: "%", equals: "=",
  plus: "+", hyphen: "-", dash: "-", semi: ";", quest: "?", commat: "@", lowbar: "_",
  nbsp: cp(0xa0), shy: cp(0xad), ensp: cp(0x2002), emsp: cp(0x2003), thinsp: cp(0x2009),
  zwnj: cp(0x200c), zwj: cp(0x200d), lrm: cp(0x200e), rlm: cp(0x200f),
  ndash: cp(0x2013), mdash: cp(0x2014), hellip: cp(0x2026), lsquo: cp(0x2018), rsquo: cp(0x2019),
  ldquo: cp(0x201c), rdquo: cp(0x201d), sbquo: cp(0x201a), bdquo: cp(0x201e), bull: cp(0x2022), middot: cp(0xb7),
  copy: cp(0xa9), reg: cp(0xae), trade: cp(0x2122), deg: cp(0xb0), times: cp(0xd7), divide: cp(0xf7),
  euro: cp(0x20ac), pound: cp(0xa3), yen: cp(0xa5), cent: cp(0xa2), sect: cp(0xa7), para: cp(0xb6),
  laquo: cp(0xab), raquo: cp(0xbb), larr: cp(0x2190), rarr: cp(0x2192), uarr: cp(0x2191), darr: cp(0x2193),
  le: cp(0x2264), ge: cp(0x2265), ne: cp(0x2260), plusmn: cp(0xb1), frac12: cp(0xbd), frac14: cp(0xbc),
  frac34: cp(0xbe), sup2: cp(0xb2), sup3: cp(0xb3), micro: cp(0xb5), iexcl: cp(0xa1), iquest: cp(0xbf), check: cp(0x2713),
};

/** Decode character references for text output: numeric ones (with or without the `;`)
 *  and the common named ones above (`;` required). Unknown names stay as written. The
 *  result is TEXT, always escaped or rendered as text afterwards. */
export function decodeEntities(s: string): string {
  return s.replace(/&(#[xX][0-9a-fA-F]{1,8}|#[0-9]{1,10}|[a-zA-Z][a-zA-Z0-9]{0,31});?/g, (m, body: string) => {
    if (body[0] === "#") {
      const hex = body[1] === "x" || body[1] === "X";
      const code = parseInt(body.slice(hex ? 2 : 1), hex ? 16 : 10);
      if (!Number.isFinite(code) || code <= 0 || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return cp(0xfffd);
      return String.fromCodePoint(code);
    }
    if (!m.endsWith(";")) return m;
    const ch = Object.prototype.hasOwnProperty.call(NAMED, body) ? NAMED[body] : undefined;
    return ch ?? m;
  });
}

/** A tag at `i` (which is "<"): its end index (after ">"), lower-case name and whether it
 *  closes. null when "<" does not start a tag (it is then text). Quotes are honoured,
 *  so `<p title="a>b">` is one tag. */
function readTag(s: string, i: number): { end: number; name: string; closing: boolean; selfClosing: boolean } | null {
  const n = s.length;
  let j = i + 1;
  const closing = s[j] === "/";
  if (closing) j++;
  if (!/[a-zA-Z]/.test(s[j] ?? "")) return null;
  const nameStart = j;
  while (j < n && !/[\s/>]/.test(s[j])) j++;
  const name = s.slice(nameStart, j).toLowerCase();
  let quote: string | null = null;
  let last = "";
  for (; j < n; j++) {
    const c = s[j];
    if (quote) {
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'") {
      // A quote opens a value only right after "=" (allowing spaces): `<a b"c>` is not quoted.
      if (last === "=") quote = c;
    } else if (c === ">") {
      return { end: j + 1, name, closing, selfClosing: s[j - 1] === "/" };
    }
    if (!/\s/.test(c)) last = c;
  }
  return { end: n, name, closing, selfClosing: false }; // unterminated: the rest is the tag
}

/** Index just after the end tag `</name…>` that closes a skipped element, counting
 *  nested same-name elements unless its content is raw text. n when there is none. */
function skipElement(s: string, from: number, name: string): number {
  const n = s.length;
  if (name === "plaintext") return n;
  const raw = RAW_TEXT.has(name);
  let depth = 1;
  let i = from;
  const re = new RegExp(raw ? `</${name}(?=[\\s/>]|$)` : `<(/?)${name}(?=[\\s/>]|$)`, "ig");
  while (i < n) {
    re.lastIndex = i;
    const m = re.exec(s);
    if (!m) return n;
    const t = readTag(s, m.index);
    const end = t ? t.end : m.index + m[0].length;
    if (raw || m[1] === "/") {
      depth--;
      if (depth === 0) return end;
    } else if (!(t && t.selfClosing)) {
      depth++;
    }
    i = end;
  }
  return n;
}

/** The visible text of `html` without a DOM: tags removed, DROP elements removed with
 *  their content, comments removed, entities decoded. `lines`: block boundaries become
 *  "\n" and each line is trimmed; otherwise all whitespace collapses to one space. */
function extractText(html: string, lines: boolean): string {
  const s = html;
  const n = s.length;
  const out: string[] = [];
  let i = 0;
  while (i < n) {
    const lt = s.indexOf("<", i);
    if (lt < 0) {
      out.push(decodeEntities(s.slice(i)));
      break;
    }
    if (lt > i) out.push(decodeEntities(s.slice(i, lt)));
    i = lt;
    if (s.startsWith("<!--", i)) {
      const e = s.indexOf("-->", i + 4);
      i = e < 0 ? n : e + 3;
      continue;
    }
    const next = s[i + 1];
    if (next === "!" || next === "?" || (next === "/" && !/[a-zA-Z]/.test(s[i + 2] ?? ""))) {
      // doctype, CDATA, processing instruction, "</ junk>": bogus comments up to ">"
      const gt = s.indexOf(">", i + 2);
      i = gt < 0 ? n : gt + 1;
      continue;
    }
    const tag = readTag(s, i);
    if (!tag) {
      out.push("<");
      i++;
      continue;
    }
    i = tag.end;
    if (BLOCK.has(tag.name)) out.push("\n");
    else if (tag.name === "td" || tag.name === "th") out.push(" ");
    if (!tag.closing && !tag.selfClosing && !VOID_IN.has(tag.name) && (DROP.has(tag.name) || RAW_TEXT.has(tag.name))) {
      i = skipElement(s, i, tag.name);
    }
  }
  const text = out.join("");
  if (!lines) return text.replace(/\s+/g, " ").trim();
  return text
    .split("\n")
    .map((l) => l.replace(/\s+/g, " ").trim())
    .filter((l) => l !== "")
    .join("\n");
}

/* --------------------------------------------------------------------- API ----- */

/**
 * The DOM-free form of stored rich text, safe for `innerHTML`: every input tag
 * stripped, the text escaped, `<br>` between blocks, nothing else. `sanitizeHtml` uses
 * it when there is no DOM (server rendering); RichTextView renders it until mounted.
 */
export function plainTextHtml(html: string | null | undefined): string {
  if (html === null || html === undefined) return "";
  return extractText(String(html), true)
    .split("\n")
    .map(escapeText)
    .join("<br>");
}

/**
 * Reduce stored rich text to the allowlist above. The result is safe to put in
 * `innerHTML` / `dangerouslySetInnerHTML`. Uses DOMParser in the browser; without a
 * DOM it strips everything (`plainTextHtml`). null / undefined / "" → "".
 */
export function sanitizeHtml(html: string | null | undefined): string {
  if (html === null || html === undefined) return "";
  const src = String(html);
  if (!src) return "";
  const doc = parseInert(src);
  if (doc) {
    try {
      // `doc.body` read through the prototype: `<img name=body>` shadows it on the document.
      const bodyGet = Object.getOwnPropertyDescriptor(Document.prototype, "body")?.get;
      const body = (bodyGet ? bodyGet.call(doc) : doc.body) as Node | null;
      if (body) return rebuild(body);
    } catch {
      /* fall through to the text form */
    }
  }
  return plainTextHtml(src);
}

/**
 * What a paste or drop puts into the editor: the clipboard's HTML through
 * `sanitizeHtml`, or its plain text escaped with line breaks kept. Never raw.
 */
export function sanitizePaste(data: { html?: string | null; text?: string | null }): string {
  const html = (data.html ?? "").trim();
  if (html) return sanitizeHtml(html);
  const text = (data.text ?? "").replace(/\r\n?/g, "\n");
  return text.split("\n").map(escapeText).join("<br>");
}

/** The visible text of stored rich text: tags removed, entities decoded, whitespace
 *  collapsed. DOM-free (the same on server and client), for "is anything written?"
 *  checks, list cells and one-line previews. Render the result as text. */
export function htmlToText(html: string | null | undefined): string {
  if (html === null || html === undefined) return "";
  return extractText(String(html), false).replace(/\xa0/g, " ").replace(/\s+/g, " ").trim();
}

/** `htmlToText` with line breaks kept (one line per block), for multi-line text views. */
export function htmlToLines(html: string | null | undefined): string {
  if (html === null || html === undefined) return "";
  return extractText(String(html), true).replace(/\xa0/g, " ");
}

/** True when stored rich text has no visible text (an editor that was cleared leaves
 *  "<p><br></p>" or "<div><br></div>" behind). */
export function isRichTextEmpty(html: string | null | undefined): boolean {
  return htmlToText(html) === "";
}
