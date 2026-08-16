"use client";

/* Dropdown value management. Every registry here feeds a form dropdown somewhere in
   the app; this page is the one place an admin fills or prunes those vocabularies.
   Baseline values are seeded automatically for every organisation — this page is for
   tailoring them. */

import LookupManager, { type LookupRegistry } from "@/components/LookupManager";
import ClassificationSchemes from "@/components/ClassificationSchemes";

const REGISTRIES: LookupRegistry[] = [
  {
    title: "Asset media types",
    help: "The IT/information asset taxonomy — the “Media type” dropdown on both asset forms.",
    endpoint: "/asset-media-types",
    fields: ["name", "description"],
    hasBuiltins: true,
  },
  {
    title: "Information asset labels",
    help: "Handling / classification labels — the “Label” dropdown on information assets.",
    endpoint: "/asset-labels",
    fields: ["name", "description", "color"],
  },
  {
    title: "IT asset tags",
    help: "Operational tags for supporting assets (environment, location, form factor…).",
    endpoint: "/asset-tags",
    fields: ["name", "category", "description", "color"],
  },
  {
    title: "Vendor types",
    help: "Third-party taxonomy — the “Type” dropdown on the vendor form.",
    endpoint: "/vendor-types",
    fields: ["name", "description"],
  },
  {
    title: "Record tags",
    help: "Free-form tags attachable to any record from its side panel. Deleting one removes it from every record.",
    endpoint: "/collab/tags",
    fields: ["name", "color"],
  },
];

export default function LookupsPage() {
  return (
    <>
      <div className="page-head">
        <h1>Lookups</h1>
        <p>
          The value lists behind form dropdowns. Defaults are created for every organisation;
          rename, extend or prune them to match your own vocabulary.
        </p>
      </div>
      {REGISTRIES.map((r) => (
        <LookupManager key={r.endpoint} registry={r} />
      ))}
      <ClassificationSchemes />
    </>
  );
}
