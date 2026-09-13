"use client";

/* The "Linked records" section body (record-page-spec §3.3.8).

     const groups: RelatedGroup[] = [
       { key: "assets", label: "Assets", items: r.assets, href: "/information-assets" },
       { key: "exceptions", label: "Exceptions", items: r.exceptions, href: "/exceptions",
         meta: (x) => `${sentenceCase(x.status)} · expires ${fmt.date(x.expires_at)}` },
     ];
     <RecordSection id="linked" title="Linked records" count={relatedCount(groups)}
       actions={<button className="btn secondary sm" onClick={() => openEdit(r, "links")}>Link records</button>}>
       <RelatedGroups groups={groups} />
     </RecordSection>

   Pass `onLink` only when the section head has no "Link records" action of its own:
   the empty-state link would be a second control with the same name (decision D3).

   A `<dl class="rec-rel">` row per NON-EMPTY group: the label and count, then chips
   ("EXC-001 Accept ransomware…", truncated at 48ch with the full text in `title`), each
   item's muted `meta`, the group `action` and `footer`. Every empty group folds into one
   sentence: "Not linked to business units, processes or policies." (labels in the order
   given). When every group is empty: "No linked records yet." plus a "Link records" link. */

import { Fragment } from "react";
import Link from "next/link";
import type { GraphRef } from "@/components/RelatedChips";
import type { RelatedGroup } from "@/components/record/types";
import { joinList, sentenceLabel } from "@/lib/record/text";

export type { RelatedGroup };

type RelatedGroupsProps = {
  groups: RelatedGroup[];
  onLink?: () => void;
  /** Default "records". */
  noun?: string;
};

/** Total linked items across groups (for the section and nav count). */
export function relatedCount(groups: RelatedGroup[]): number {
  return groups.reduce((n, g) => n + (g.items?.length ?? 0), 0);
}

function hrefFor(g: RelatedGroup, x: GraphRef): string {
  return typeof g.href === "function" ? g.href(x) : `${g.href}?id=${x.id}`;
}

function Chip({ g, x }: { g: RelatedGroup; x: GraphRef }) {
  const name = (x.title || x.name || "").trim();
  const full = [x.reference, name].filter(Boolean).join(" ") || x.id;
  return (
    <Link href={hrefFor(g, x)} className="chip chip-link rec-chip" title={full}>
      {x.reference && <span className="ref">{x.reference}</span>}
      {name || (x.reference ? "" : x.id)}
    </Link>
  );
}

export default function RelatedGroups({ groups, onLink, noun = "records" }: RelatedGroupsProps) {
  const filled = groups.filter((g) => (g.items?.length ?? 0) > 0);
  const empty = groups.filter((g) => (g.items?.length ?? 0) === 0);

  if (filled.length === 0) {
    return (
      <p className="rec-none rec-none-all">
        No linked {noun} yet.
        {onLink && (
          <>
            {" "}
            <button type="button" className="rec-link" onClick={onLink}>Link {noun}</button>
          </>
        )}
      </p>
    );
  }

  return (
    <>
      <dl className="rec-rel">
        {filled.map((g) => (
          <Fragment key={g.key}>
            <dt>
              {g.label}
              <span className="n">{g.items?.length ?? 0}</span>
            </dt>
            <dd>
              {(g.items ?? []).map((x) => {
                const meta = g.meta?.(x);
                return (
                  <Fragment key={x.id}>
                    <Chip g={g} x={x} />
                    {meta !== undefined && meta !== null && meta !== "" && <span className="meta">{meta}</span>}
                  </Fragment>
                );
              })}
              {g.action && <span className="grp-act">{g.action}</span>}
              {g.footer && <div className="grp-foot">{g.footer}</div>}
            </dd>
          </Fragment>
        ))}
      </dl>
      {empty.length > 0 && (
        <p className="rec-none">Not linked to {joinList(empty.map((g) => sentenceLabel(g.label)), "or")}.</p>
      )}
    </>
  );
}

export { RelatedGroups };
