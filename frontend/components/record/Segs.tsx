/* Renders sentence segments from lib/record/<type>.ts (record-page-spec §3.3.2):
   strings as text, `{ b }` as <b> (key figures). No other markup, ever.

     <p className="rec-headline"><Segs segs={riskHeadline(input, ctx)} /></p> */

import { Fragment } from "react";
import type { Seg } from "@/lib/record/types";

export default function Segs({ segs }: { segs: readonly Seg[] }) {
  return (
    <>
      {segs.map((s, i) => (typeof s === "string" ? <Fragment key={i}>{s}</Fragment> : <b key={i}>{s.b}</b>))}
    </>
  );
}

export { Segs };
