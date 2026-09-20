"use client";

import { useRef } from "react";
import Link from "next/link";
import { useInRelatedCluster, useRelatedCluster } from "@/components/record/RelatedCluster";

export type GraphRef = { id: string; reference?: string; title?: string; name?: string };

const labelOf = (x: GraphRef) => x.reference || x.title || x.name || x.id;

/** A labelled row of related records rendered as chips that deep-link to each record's
 *  own view (`href?id=<id>`). This is the connective tissue: from any record you can
 *  jump straight to anything linked to it, in any module.
 *
 *    <RelatedChips label="Risks" items={detail.risks} href="/risks" />
 *
 *  Options (all optional, defaults keep today's behaviour):
 *  - `format="ref-name"` shows the reference in mono followed by the title/name
 *    (default "label": the reference, else the title/name).
 *  - `hideEmpty` renders nothing when there are no items.
 *  - `collapse="never"` opts out of clustering. By default ("auto"), inside a
 *    RecordDrawer a stack of 3+ RelatedChips under one parent folds its empty rows into
 *    one "Not linked to …" sentence (record-page-spec §3.3.15); inside a drawer the
 *    empty text reads "None" instead of "—". Outside a drawer nothing changes. */
export default function RelatedChips({
  label,
  items,
  href,
  format = "label",
  hideEmpty = false,
  collapse = "auto",
}: {
  label: string;
  items: GraphRef[] | undefined;
  href: string;
  format?: "label" | "ref-name";
  hideEmpty?: boolean;
  collapse?: "auto" | "never";
}) {
  const list = items ?? [];
  const empty = list.length === 0;
  const ref = useRef<HTMLDivElement>(null);
  const inDrawer = useInRelatedCluster();
  const { hidden, sentence } = useRelatedCluster(label, empty, ref, collapse === "auto" && !(hideEmpty && empty));

  if (hideEmpty && empty) return null;

  return (
    <>
      <div ref={ref} style={{ minWidth: 140 }} hidden={hidden}>
        <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
        <div style={{ marginTop: 3 }}>
          {list.length ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {list.map((x) => {
                const name = x.title || x.name || "";
                const full = format === "ref-name" ? [x.reference, name].filter(Boolean).join(" ") || x.id : labelOf(x);
                return (
                  <Link key={x.id} href={`${href}?id=${x.id}`} className={`chip chip-link${format === "ref-name" ? " rec-chip" : ""}`} title={full}>
                    {format === "ref-name" ? (
                      <>
                        {x.reference && <span className="ref">{x.reference}</span>}
                        {name || (x.reference ? "" : x.id)}
                      </>
                    ) : (
                      labelOf(x)
                    )}
                  </Link>
                );
              })}
            </div>
          ) : (
            <span className="muted">{inDrawer ? "None" : "—"}</span>
          )}
        </div>
      </div>
      {sentence && (
        <p className="rec-none rc-none" style={{ gridColumn: "1 / -1", flexBasis: "100%" }}>{sentence}</p>
      )}
    </>
  );
}
