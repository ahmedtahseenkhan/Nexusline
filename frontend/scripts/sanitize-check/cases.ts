/* Cases for scripts/sanitize-check/check.ts (lib/sanitize.ts).

   `html`: the exact browser (DOMParser) output. When omitted, only the invariants are
   checked: every element and attribute in the output is on the allowlist, every link is
   http(s)/mailto by the browser's own URL parser, sanitising twice changes nothing, and
   nothing fires or loads when the output is put into a live document.
   `text`: the exact htmlToText (DOM-free; the same in Node and in the browser).

   Handler payloads call `__xss++` or `alert()`; the check counts both. Characters that
   must not appear literally in a source file are built with String.fromCharCode. */

export type Case = { name: string; input: string; html?: string; text?: string };

const ch = (c: number) => String.fromCharCode(c);
const A = (href: string, text: string) => `<a href="${href}" target="_blank" rel="noopener noreferrer">${text}</a>`;

export const CASES: Case[] = [
  /* ---- images and handlers */
  { name: "img onerror", input: "<img src=x onerror=__xss++>", html: "", text: "" },
  { name: "img onerror inside a paragraph", input: '<p>Hi <img src=x onerror="__xss++">there</p>', html: "<p>Hi there</p>", text: "Hi there" },
  { name: "remote image (web beacon)", input: '<p>a</p><img src="http://127.0.0.1:9/beacon.png"><img srcset="http://127.0.0.1:9/b.png 1x">', html: "<p>a</p>" },
  { name: "handlers and style on allowed tags", input: '<p onclick="__xss++" style="color:red" class="x" id="y">t</p>', html: "<p>t</p>" },
  { name: "div style url", input: '<div style="background:url(javascript:alert(1))">x</div>', html: "<div>x</div>" },
  { name: "body onload", input: "<body onload=__xss++>text", html: "text", text: "text" },
  { name: "frameset onload", input: "<frameset onload=__xss++><frame src=javascript:alert(1)></frameset>", html: "" },
  { name: "marquee onstart", input: "<marquee onstart=__xss++>m</marquee>", html: "m" },
  { name: "details ontoggle", input: "<details open ontoggle=__xss++><summary>s</summary>d</details>", html: "<div><div>s</div>d</div>", text: "s d" },
  { name: "video / audio / source", input: "<video><source onerror=__xss++></video><audio src=x onerror=__xss++></audio>ok", html: "ok" },
  { name: "isindex", input: "<isindex type=image src=1 onerror=__xss++>", html: "" },

  /* ---- DOM clobbering: a form's named controls shadow the node's own properties */
  { name: "form clobbers nextSibling (input)", input: "<input form=f name=nextSibling><form id=f>x</form>", html: "x", text: "x" },
  { name: "form clobbers nextSibling (fieldset)", input: "<fieldset form=f name=nextSibling></fieldset><form id=f>x</form>", html: "x", text: "x" },
  { name: "form clobbers firstChild", input: "<form><input name=firstChild>y</form>", html: "y", text: "y" },
  { name: "form clobbers tagName / remove", input: "<p>ok</p><form><input name=tagName><input name=remove></form>", html: "<p>ok</p>", text: "ok" },
  { name: "form clobbers localName / nodeType / namespaceURI", input: "<form><input name=localName><input name=nodeType><input name=namespaceURI>z</form>", html: "z", text: "z" },
  { name: "document clobbers body", input: "<img name=body><p>t</p>", html: "<p>t</p>", text: "t" },

  /* ---- links */
  { name: "a href javascript:", input: '<a href="javascript:alert(1)">click</a>', html: "click", text: "click" },
  { name: "a href mixed-case javascript:", input: '<a href="JaVaScRiPt:alert(1)">x</a>', html: "x" },
  { name: "a href decimal-entity javascript:", input: '<a href="&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;alert(1)">x</a>', html: "x" },
  { name: "a href zero-padded entities, no semicolons", input: '<a href="&#0000106&#0000097&#0000118&#0000097&#0000115&#0000099&#0000114&#0000105&#0000112&#0000116&#0000058alert(1)">x</a>', html: "x" },
  { name: "a href hex entity + &colon;", input: '<a href="&#x6A;avascript&colon;alert(1)">x</a>', html: "x" },
  { name: "a href javascript&#x3A;", input: '<a href="javascript&#x3A;alert(1)">x</a>', html: "x" },
  { name: "a href tab entity split", input: '<a href="java&#9;script:alert(1)">x</a>', html: "x" },
  { name: "a href literal tab split", input: '<a href="java\tscript:alert(1)">x</a>', html: "x" },
  { name: "a href newline entity split", input: '<a href="jav&#x0A;ascript:alert(1)">x</a>', html: "x" },
  { name: "a href &Tab; prefix", input: '<a href="&Tab;javascript:alert(1)">x</a>', html: "x" },
  { name: "a href leading control char", input: '<a href=" &#14; javascript:alert(1)">x</a>', html: "x" },
  { name: "a href NUL inside scheme", input: '<a href="java&#0;script:alert(1)">x</a>', html: "x" },
  { name: "a href zero-width space in scheme", input: `<a href="java${ch(0x200b)}script:alert(1)">x</a>`, html: "x" },
  { name: "a href vbscript:", input: '<a href="vbscript:msgbox(1)">x</a>', html: "x" },
  { name: "a href data:", input: '<a href="data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==">x</a>', html: "x" },
  { name: "a href protocol-relative and relative", input: '<a href="//evil.example/x">x</a> <a href="/risks?id=1">y</a>', html: "x y" },
  { name: "a href http:// without host", input: '<a href="http://">x</a><a href="mailto:">y</a>', html: "xy" },
  {
    name: "a https keeps href only, forced target/rel",
    input: '<a href="https://example.com/a?b=1&amp;c=2" onclick="__xss++" style="color:red" class="x" target="_self" rel="opener">ok</a>',
    html: A("https://example.com/a?b=1&amp;c=2", "ok"),
    text: "ok",
  },
  { name: "a mailto", input: '<a href="mailto:risk@bank.com">mail</a>', html: A("mailto:risk@bank.com", "mail") },
  {
    name: "a href quote breaking",
    input: `<a href='https://x.com/"onmouseover="__xss++'>t</a>`,
    html: A("https://x.com/&quot;onmouseover=&quot;__xss++", "t"),
  },
  {
    name: "a title with encoded markup",
    input: '<a href="https://x.com/" title="&quot;&gt;&lt;img src=x onerror=__xss++&gt;">t</a>',
    html: A("https://x.com/", "t"),
  },
  {
    name: "nested anchors",
    input: '<a href="https://ok.example">outer<a href="javascript:alert(1)">inner</a></a>',
    html: `${A("https://ok.example", "outer")}inner`,
  },
  { name: "a href zero-width host", input: `<a href="https://exa${ch(0x200b)}mple.com">z</a>`, html: "z" },
  {
    name: "DOM clobbering attributes",
    input: '<p id="__proto__" name="x">t</p><a href="https://x.com" id="location" name="alert">l</a><form name="body"><input name="cookie"></form>',
    html: `<p>t</p>${A("https://x.com", "l")}`,
  },

  /* ---- script, style and embedding elements */
  { name: "script", input: "<p>Hello</p><script>__xss++</script>", html: "<p>Hello</p>", text: "Hello" },
  { name: "uppercase tags", input: '<SCRIPT>alert(1)</SCRIPT><P>Up</P><IMG SRC=x ONERROR=__xss++><A HREF="JAVASCRIPT:alert(1)">u</A>', html: "<p>Up</p>u", text: "Up u" },
  { name: "split script tag", input: "<scr<script>ipt>alert(1)</script>" },
  { name: "iframe src / srcdoc", input: '<iframe src="javascript:alert(1)"></iframe><iframe srcdoc="<script>__xss++</script>"></iframe>', html: "" },
  { name: "object / embed", input: '<object data="javascript:alert(1)"></object><embed src="javascript:alert(1)">', html: "" },
  {
    name: "style / link / meta / base",
    input: "<style>@import 'http://127.0.0.1:9/x.css';</style><link rel=stylesheet href=http://127.0.0.1:9/x.css><meta http-equiv=refresh content=\"0;url=javascript:alert(1)\"><base href=\"javascript:/\">x",
    html: "x",
    text: "x",
  },
  { name: "form controls", input: '<input autofocus onfocus=__xss++><button formaction=javascript:alert(1)>b</button><select><option>o</option></select><textarea>t</textarea>', html: "", text: "" },
  { name: "xmp", input: "<xmp><img src=x onerror=__xss++></xmp>", html: "" },
  { name: "plaintext", input: "<plaintext><img src=x onerror=__xss++>", html: "" },
  { name: "comment", input: "<!--<img src=x onerror=__xss++>-->c", html: "c", text: "c" },
  { name: "CDATA in HTML", input: "<p>a</p><![CDATA[<img src=x onerror=__xss++>]]>" },

  /* ---- svg, math, template, noscript (namespace and parser tricks) */
  { name: "svg onload", input: "<svg onload=__xss++><circle r=1></circle></svg>after", html: "after", text: "after" },
  { name: "svg script", input: "<svg><script>__xss++</script></svg>", html: "" },
  { name: "svg foreignObject img", input: "<svg><foreignObject><img src=x onerror=__xss++></foreignObject></svg>", html: "" },
  { name: "svg animate href", input: '<svg><a><animate attributeName=href values=javascript:alert(1) /><text x=20 y=20>t</text></a></svg>', html: "" },
  { name: "math xlink:href", input: '<math><mi xlink:href="javascript:alert(1)">x</mi></math>', html: "" },
  { name: "math mglyph style", input: "<math><mtext><table><mglyph><style><img src=x onerror=__xss++></style></mglyph></table></mtext></math>" },
  { name: "math form namespace confusion", input: "<form><math><mtext></form><form><mglyph><style></math><img src onerror=__xss++>" },
  { name: "svg p style mXSS", input: '<svg></p><style><a id="</style><img src=1 onerror=__xss++>">' },
  {
    name: "math h1 a h6 mXSS",
    input: `<math><mtext><h1><a><h6></a></h6><mglyph><svg><mtext><style><a title="</style><img src='#' onerror='__xss++'>"></style></h1>`,
  },
  { name: "template", input: "<template><img src=x onerror=__xss++></template>text", html: "text", text: "text" },
  { name: "select template style", input: "<select><template><style><!--</style><img src=x onerror=__xss++>--></template></select>" },
  { name: "noscript title breakout", input: '<noscript><p title="</noscript><img src=x onerror=__xss++>"></noscript>', html: "" },

  /* ---- attribute quote breaking */
  { name: "single-quoted title breakout", input: `<p title='x"><img src=x onerror=__xss++>'>t</p>`, html: "<p>t</p>" },
  { name: "double-quoted title breakout", input: `<p title="x' onmouseover='__xss++">t</p>`, html: "<p>t</p>", text: "t" },
  { name: "unquoted attribute with >", input: "<p title=a>b onmouseover=__xss++>t</p>" },

  /* ---- nesting */
  { name: "mis-nested b / i", input: "<b><i>x</b></i>", html: "<b><i>x</i></b>" },
  { name: "unclosed formatting across a paragraph", input: "<p>unclosed <b>bold <i>both</p> after", html: "<p>unclosed <b>bold <i>both</i></b></p><b><i> after</i></b>", text: "unclosed bold both after" },
  { name: "table without tbody", input: "<table><tr><td>a<td>b</table>", html: "<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>", text: "a b" },
  { name: "td colspan / rowspan", input: '<table><tr><td colspan="2" rowspan="bad" onclick=__xss++>a</td><th rowspan=" 3 " colspan=500>b</th></tr></table>', html: '<table><tbody><tr><td colspan="2">a</td><th rowspan="3">b</th></tr></tbody></table>' },
  { name: "lists without end tags", input: "<ul><li>one<li>two</ul><ol><li>1</ol>", html: "<ul><li>one</li><li>two</li></ul><ol><li>1</li></ol>", text: "one two 1" },

  /* ---- what the editor and pastes produce */
  { name: "contentEditable divs", input: "<div>line 1</div><div><b>bold</b><br></div>", html: "<div>line 1</div><div><b>bold</b><br></div>" },
  { name: "execCommand spans and fonts", input: '<span style="font-weight:bold">x</span><font color=red face="x">y</font>', html: "xy", text: "xy" },
  {
    name: "Word paste",
    input: '<html xmlns:o="urn:schemas-microsoft-com:office:office"><head><meta charset=utf-8><style>p.MsoNormal{}</style></head><body><!--[if !supportLists]--><p class=MsoNormal>Para<o:p></o:p></p></body></html>',
    html: "<p>Para</p>",
    text: "Para",
  },
  { name: "renamed elements", input: "<h5>h</h5><h6>h</h6><strike>s</strike><del>d</del><ins>i</ins><kbd>k</kbd><section>x</section>", html: "<h4>h</h4><h4>h</h4><s>s</s><s>d</s><u>i</u><code>k</code><div>x</div>" },
  {
    name: "allowed formatting kept",
    input: "<h1>T</h1><h2>S</h2><p><strong>b</strong> <em>i</em> <u>u</u> <s>s</s> <code>c</code> <sub>1</sub><sup>2</sup></p><blockquote>q</blockquote><pre>p</pre><hr>",
    html: "<h1>T</h1><h2>S</h2><p><strong>b</strong> <em>i</em> <u>u</u> <s>s</s> <code>c</code> <sub>1</sub><sup>2</sup></p><blockquote>q</blockquote><pre>p</pre><hr>",
  },
  { name: "escaped text stays escaped", input: "<p>5 &lt; 6 &amp;&amp; 7 &gt; 3</p>", html: "<p>5 &lt; 6 &amp;&amp; 7 &gt; 3</p>", text: "5 < 6 && 7 > 3" },
  { name: "bare angle brackets in text", input: "a < b > c", html: "a &lt; b &gt; c", text: "a < b > c" },
  { name: "non-Latin text", input: "<p>Urdu: اردو · done ✓</p>", html: "<p>Urdu: اردو · done ✓</p>", text: "Urdu: اردو · done ✓" },
  { name: "empty", input: "", html: "", text: "" },
];

/** safeLinkUrl(input) → expected (both environments). */
export const URL_CASES: [string | null, string | null][] = [
  ["javascript:alert(1)", null],
  ["JAVASCRIPT:alert(1)", null],
  [" javascript:alert(1)", null],
  ["java\tscript:alert(1)", null],
  ["java\nscript:alert(1)", null],
  ["java\rscript:alert(1)", null],
  ["\x01javascript:alert(1)", null],
  ["javascript\x00:alert(1)", null],
  [`jav${ch(0x200b)}ascript:alert(1)`, null],
  [`${ch(0xfeff)}javascript:alert(1)`, null],
  ["javascript&colon;alert(1)", null],
  ["vbscript:msgbox(1)", null],
  ["data:text/html,<script>alert(1)</script>", null],
  ["DATA:text/html,x", null],
  ["https://example.com", "https://example.com"],
  ["  https://example.com/a b  ", "https://example.com/a b"],
  ["HTTPS://EXAMPLE.COM", "HTTPS://EXAMPLE.COM"],
  ["http://x", "http://x"],
  ["https://ex\tample.com", "https://example.com"],
  ["mailto:risk@bank.com", "mailto:risk@bank.com"],
  ["mailto:", null],
  ["//evil.example", null],
  ["/relative/path", null],
  ["https:evil.example", null],
  ["https:/evil.example", null],
  ["http:\\\\evil.example", null],
  ["https://", null],
  ["ftp://files.example", null],
  [`https://exa${ch(0x200b)}mple.com`, null],
  [`https://example.com/${ch(0xa0)}`, null],
  ["", null],
  [null, null],
];

/** linkFromUserInput(input) → expected. */
export const USER_LINK_CASES: [string, string | null][] = [
  ["www.example.com", "https://www.example.com"],
  ["example.com/policy?x=1", "https://example.com/policy?x=1"],
  ["risk@bank.com", "mailto:risk@bank.com"],
  ["https://ok.example", "https://ok.example"],
  ["  https://ok.example/a  ", "https://ok.example/a"],
  ["javascript:alert(1)", null],
  ["JavaScript:alert(1)", null],
  ["data:text/html,x", null],
  ["/relative", null],
  ["ftp://x.example", null],
  ["not a url", null],
  ["   ", null],
];

/** sanitizePaste(input): `html` in the browser, `node` without a DOM. */
export const PASTE_CASES: { name: string; input: { html?: string; text?: string }; html: string; node: string }[] = [
  { name: "clipboard HTML with an image", input: { html: "<meta charset='utf-8'><p>a</p><img src=x onerror=__xss++>", text: "a" }, html: "<p>a</p>", node: "a" },
  { name: "plain text only", input: { html: "", text: "line 1\r\nline 2 <b>&amp;" }, html: "line 1<br>line 2 &lt;b&gt;&amp;amp;", node: "line 1<br>line 2 &lt;b&gt;&amp;amp;" },
  { name: "nothing usable (a file)", input: { html: "", text: "" }, html: "", node: "" },
];
