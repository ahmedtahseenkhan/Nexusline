"use client";

/* Dropdown value management. Every registry here feeds a form dropdown somewhere in
   the app; this page is the one place an admin fills or prunes those vocabularies.
   Baseline values are seeded automatically for every organisation — this page is for
   tailoring them. */

import { useEffect, useState } from "react";
import LookupManager, { GovernedLookupManager, type LookupRegistry } from "@/components/LookupManager";
import ClassificationSchemes from "@/components/ClassificationSchemes";
import { listLookupLists, type LookupList } from "@/lib/masterData";

/** Where each governed list's values are picked, so an admin knows what they edit. */
const GOVERNED_HELP: Record<string, string> = {
  risk_category: "Category on risks and RCSA risks. Two levels: a top-level category and its sub-categories.",
  control_classification: "Classification on controls (preventive, detective …).",
  issue_category: "Category on issues and remediation actions.",
  root_cause_category: "Root-cause category on issues and incidents.",
  incident_type: "Incident type — the Basel event types plus cyber categories.",
  incident_classification: "Information classification of the data an incident touched.",
  regulator: "Regulator an incident or return is reported to.",
  kri_category: "Category on key risk indicators.",
  policy_category: "Category on policies.",
  legal_category: "Category on the legal and regulatory register.",
  vendor_category: "Category on third parties.",
  country: "Country of a third party (ISO 3166 names; the code is the value).",
};

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

function GovernedLists() {
  const [lists, setLists] = useState<LookupList[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listLookupLists()
      .then(setLists)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load the governed lists"));
  }, []);

  return (
    <section style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 17, margin: "0 0 4px" }}>Governed lists</h2>
      <p className="muted" style={{ fontSize: 13, margin: "0 0 12px", maxWidth: 820 }}>
        The categories, regulators and countries records are classified by. Renaming a value
        updates every record that uses it. To retire a value, deactivate it: records keep it,
        pickers stop offering it. Only values no record uses can be deleted.
      </p>
      {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}
      {lists === null && !error && <div className="muted" style={{ fontSize: 13 }}>Loading…</div>}
      {lists?.map((l) => (
        <GovernedLookupManager key={l.key} list={l} help={GOVERNED_HELP[l.key]} />
      ))}
    </section>
  );
}

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
      <GovernedLists />
      <h2 style={{ fontSize: 17, margin: "0 0 12px" }}>Asset, vendor and tag lists</h2>
      {REGISTRIES.map((r) => (
        <LookupManager key={r.endpoint} registry={r} />
      ))}
      <ClassificationSchemes />
    </>
  );
}
