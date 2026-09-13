/* The mini-visual on the "Against appetite" tile (record-page-spec §3.3.3).

     <AppetiteScale max={25} appetite={6} tolerance={12}
       marks={[{ score: 20, kind: "inherent" }, { score: 10, kind: "suggested" }]} />

   A 6px bar from 0 to `max` in three zones (within appetite, elevated, breach), numeric
   ticks at the appetite and tolerance, and one mark per score: inherent (solid, dimmed
   once a residual exists), residual (solid), suggested (dashed) and target (hollow
   circle). Entirely aria-hidden — the tile's because-sentence says the same thing.
   Renders nothing when the appetite or tolerance is missing. */

import type { ScaleModel } from "@/lib/record/types";

type AppetiteScaleProps = ScaleModel;

const pct = (score: number, max: number) => Math.min(100, Math.max(0, (score / max) * 100));

export default function AppetiteScale({ max, appetite, tolerance, marks }: AppetiteScaleProps) {
  if (appetite == null || tolerance == null || !(max > 0)) return null;
  const a = pct(appetite, max);
  const t = Math.max(a, pct(tolerance, max));

  // Tick labels: appetite and tolerance first, then each mark's score where it fits.
  const placed: number[] = [a, t];
  const markLabels: { left: number; text: string; key: string }[] = [];
  marks.forEach((m, i) => {
    const left = pct(m.score, max);
    if (placed.some((p) => Math.abs(p - left) < 6)) return;
    placed.push(left);
    markLabels.push({ left, text: String(m.score), key: `${m.kind}-${i}` });
  });

  return (
    <div className="rec-scale" aria-hidden="true">
      <div className="rec-scale-bar">
        <span className="z-in" style={{ width: `${a}%` }} />
        <span className="z-el" style={{ width: `${t - a}%` }} />
        <span className="z-br" style={{ width: `${100 - t}%` }} />
      </div>
      <span className="rec-scale-tick" style={{ left: `${a}%` }}>{appetite}</span>
      {t !== a && <span className="rec-scale-tick" style={{ left: `${t}%` }}>{tolerance}</span>}
      {marks.map((m, i) => (
        <span
          key={`${m.kind}-${i}`}
          className={`rec-scale-mk ${m.kind}${m.dim ? " dim" : ""}`}
          style={{ left: `${pct(m.score, max)}%` }}
        />
      ))}
      {markLabels.map((l) => (
        <span key={l.key} className="rec-scale-tick is-mark" style={{ left: `${l.left}%` }}>{l.text}</span>
      ))}
    </div>
  );
}

export { AppetiteScale };
