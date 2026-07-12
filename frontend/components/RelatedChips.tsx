"use client";

import Link from "next/link";

export type GraphRef = { id: string; reference?: string; title?: string; name?: string };

const labelOf = (x: GraphRef) => x.reference || x.title || x.name || x.id;

/** A labelled row of related records rendered as chips that deep-link to each record's
 *  own view (`href?id=<id>`). This is the connective tissue: from any record you can
 *  jump straight to anything linked to it, in any module. */
export default function RelatedChips({
  label,
  items,
  href,
}: {
  label: string;
  items: GraphRef[] | undefined;
  href: string;
}) {
  const list = items ?? [];
  return (
    <div style={{ minWidth: 140 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
      <div style={{ marginTop: 3 }}>
        {list.length ? (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {list.map((x) => (
              <Link key={x.id} href={`${href}?id=${x.id}`} className="chip chip-link" title={labelOf(x)}>
                {labelOf(x)}
              </Link>
            ))}
          </div>
        ) : (
          <span className="muted">—</span>
        )}
      </div>
    </div>
  );
}
