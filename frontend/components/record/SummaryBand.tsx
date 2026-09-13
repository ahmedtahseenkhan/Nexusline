"use client";

/* The headline and summary band (record-page-spec §3.3.2).

     const sections = useRecordSections();
     <SummaryBand tiles={riskTiles(input, ctx)} headline={riskHeadline(input, ctx)} onJump={sections.scrollTo} />

   Exactly 3 or 6 tiles (any other count logs a dev console.error and still renders),
   drawn as one bordered block with 1px dividers, 3 per row (2 / 1 in narrow containers).
   Each tile is ONE link to the section that backs it: its accessible name is
   "label, value" and its description is the because-sentence plus the basis. A tile
   never contains another control — actions live in the section. A missing judgement is
   a hollow value ("Not recorded"), never an absent tile.

   `onJump` defaults to the drawer's section scroller, so it can be omitted inside a
   dossier RecordDrawer. The "Key" toggle explains the four basis markers; while it is
   open it is a layer of the escape stack, so Esc folds the key (focus back on the
   toggle) and leaves the record open. */

import { useId, useRef, useState } from "react";
import { Badge } from "@/components/badges";
import AppetiteScale from "@/components/record/AppetiteScale";
import Segs from "@/components/record/Segs";
import { useRecordSections } from "@/components/record/RecordSection";
import { useEscapeLayer } from "@/lib/escapeLayer";
import { segsText } from "@/lib/record/text";
import type { BasisKind, Seg, TileModel, TileValue } from "@/lib/record/types";

type SummaryBandProps = {
  /** Exactly 3 or 6. */
  tiles: TileModel[];
  headline?: Seg[];
  /** The page passes (id) => sections.scrollTo(id); defaults to the drawer's scroller. */
  onJump?: (sectionId: string) => void;
};

/** Words for the visually hidden basis prefix and the Key line. */
export const BASIS_WORD: Record<BasisKind, string> = {
  evidenced: "evidenced",
  declared: "set by hand",
  derived: "calculated",
  missing: "not on file",
};

const WORD_TONES = new Set(["critical", "high", "medium", "low"]);

function valueText(v: TileValue): string {
  return [v.text, v.num, v.unit].filter(Boolean).join(" ");
}

function TileValueView({ value }: { value: TileValue }) {
  const hollow = value.tone === "hollow";
  let main;
  if (hollow) {
    main = <Badge hollow asIs>{value.text}</Badge>;
  } else if (value.badge) {
    const tone = value.tone && value.tone !== "hollow" ? value.tone : "neutral";
    main = <Badge tone={tone} asIs>{value.text}</Badge>;
  } else {
    const cls = value.tone && WORD_TONES.has(value.tone) ? `rec-tone-${value.tone}` : undefined;
    main = <span className={cls}>{value.text}</span>;
  }
  return (
    <span className={`rec-tile-value${hollow ? " is-hollow" : ""}`}>
      {main}
      {value.num && <b>{value.num}</b>}
      {value.unit && <span className="unit">{value.unit}</span>}
    </span>
  );
}

export default function SummaryBand({ tiles, headline, onJump }: SummaryBandProps) {
  const sections = useRecordSections();
  const jump = onJump ?? sections.scrollTo;
  const uid = useId();
  const [keyOpen, setKeyOpen] = useState(false);
  const keyId = `${uid}-key`;
  const keyToggle = useRef<HTMLButtonElement>(null);
  useEscapeLayer(keyOpen, () => {
    setKeyOpen(false);
    keyToggle.current?.focus({ preventScroll: true });
  });

  if (process.env.NODE_ENV !== "production" && tiles.length !== 3 && tiles.length !== 6) {
    console.error(`SummaryBand: expected 3 or 6 tiles, got ${tiles.length}`, tiles.map((t) => t.key));
  }

  return (
    <section className="rec-summary" aria-labelledby="rec-sum-h">
      <h2 id="rec-sum-h" className="sr-only">Summary</h2>
      <div className="rec-headline-row">
        {headline && headline.length > 0 ? (
          <p className="rec-headline"><Segs segs={headline} /></p>
        ) : (
          <span />
        )}
        <button
          ref={keyToggle}
          type="button"
          className="rec-link rec-key-toggle"
          aria-expanded={keyOpen}
          aria-controls={keyId}
          onClick={() => setKeyOpen((v) => !v)}
        >
          Key
        </button>
      </div>
      {keyOpen && (
        <p className="rec-key" id={keyId}>
          <span className="rec-basis evidenced">Evidenced: backed by a record on file</span>
          {" · "}
          <span className="rec-basis declared">Set by hand: no evidence</span>
          {" · "}
          <span className="rec-basis derived">Calculated from other fields</span>
          {" · "}
          <span className="rec-basis missing">Not on file</span>
        </p>
      )}
      <ul className="rec-band" data-count={tiles.length}>
        {tiles.map((t) => {
          const becauseId = `${uid}-${t.key}-because`;
          const basisId = `${uid}-${t.key}-basis`;
          return (
            <li key={t.key}>
              <a
                className="rec-tile"
                href={`#${t.section}`}
                aria-label={`${t.label}, ${valueText(t.value)}`}
                aria-describedby={`${becauseId} ${basisId}`}
                onClick={(e) => {
                  e.preventDefault();
                  jump(t.section);
                }}
              >
                <span className="rec-tile-label">{t.label}</span>
                <TileValueView value={t.value} />
                {t.scale && <AppetiteScale {...t.scale} />}
                <span className="rec-tile-because" id={becauseId} title={segsText(t.because)}>
                  <Segs segs={t.because} />
                </span>
                <span className={`rec-basis ${t.basis.kind}`} id={basisId}>
                  <span className="sr-only">Basis: {BASIS_WORD[t.basis.kind]}. </span>
                  {t.basis.text}
                </span>
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export { SummaryBand };
