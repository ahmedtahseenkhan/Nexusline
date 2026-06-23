"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall, type Page as PageT } from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconRisk, IconShield, IconAlert } from "@/components/icons";

// ---- inline types (backend ThreatRead / VulnerabilityRead) ----------------
// Both catalogs share the same shape: name + description + category, plus a
// read-only reverse count of how many risks reference the item.
type CatalogRow = {
  id: string;
  name: string;
  description: string;
  category: string;
  used_by_risks_count: number;
};

type FormState = { name: string; description: string; category: string };
const BLANK: FormState = { name: "", description: "", category: "" };

const fromRow = (r: CatalogRow): FormState => ({
  name: r.name,
  description: r.description || "",
  category: r.category || "",
});

// "kind" drives copy, endpoints and accent colour for each of the two sections.
type Kind = "threat" | "vulnerability";
type KindMeta = {
  base: string; // API path segment
  label: string; // singular
  plural: string;
  icon: typeof IconShield;
  examples: string[]; // category type-ahead suggestions
  placeholderName: string;
  placeholderCategory: string;
  help: string;
};

const META: Record<Kind, KindMeta> = {
  threat: {
    base: "threats",
    label: "Threat",
    plural: "Threats",
    icon: IconAlert,
    examples: ["Adversarial", "Accidental", "Environmental", "Structural", "Malware", "Insider", "Natural"],
    placeholderName: "Phishing attack",
    placeholderCategory: "Adversarial",
    help: "A potential cause of an unwanted incident — what could exploit a weakness (e.g. Phishing, DDoS, Theft).",
  },
  vulnerability: {
    base: "vulnerabilities",
    label: "Vulnerability",
    plural: "Vulnerabilities",
    icon: IconShield,
    examples: ["Technical", "Organizational", "Physical", "Human", "Configuration", "Software", "Network"],
    placeholderName: "Unpatched software",
    placeholderCategory: "Technical",
    help: "A weakness that a threat can exploit (e.g. Unpatched software, Weak passwords, Missing MFA).",
  },
};

// ---------------------------------------------------------------------------
function CatalogSection({
  kind,
  rows,
  onEdit,
  onAdd,
}: {
  kind: Kind;
  rows: CatalogRow[];
  onEdit: (r: CatalogRow) => void;
  onAdd: () => void;
}) {
  const m = META[kind];
  const Icon = m.icon;
  const linked = rows.reduce((n, r) => n + (r.used_by_risks_count > 0 ? 1 : 0), 0);

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>{m.plural}</h3>
          <span className="sub">
            {rows.length} in catalog{rows.length ? ` · ${linked} linked to risks` : ""}
          </span>
        </div>
        <button className="btn sm" onClick={onAdd}>
          <IconPlus width={14} height={14} /> Add {m.label.toLowerCase()}
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Category</th>
              <th>Description</th>
              <th>Used by risks</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => onEdit(r)}>
                <td className="cell-title">{r.name}</td>
                <td>
                  {r.category ? (
                    <Badge tone="info" plain>
                      {r.category}
                    </Badge>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="muted" style={{ maxWidth: 320 }}>
                  {r.description ? (
                    <span
                      style={{
                        display: "block",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={r.description}
                    >
                      {r.description}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  {r.used_by_risks_count > 0 ? (
                    <Badge tone="medium" plain>
                      {r.used_by_risks_count}
                    </Badge>
                  ) : (
                    <span className="muted">0</span>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={4}>
                  <div className="empty">
                    <span className="ico">
                      <Icon width={22} height={22} />
                    </span>
                    <h3>No {m.plural.toLowerCase()}</h3>
                    <p>Add your first {m.label.toLowerCase()} to seed the risk register.</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function ThreatLibraryPage() {
  const [threats, setThreats] = useState<CatalogRow[]>([]);
  const [vulns, setVulns] = useState<CatalogRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  // single shared dialog, parameterised by kind + editing target
  const [kind, setKind] = useState<Kind>("threat");
  const [editing, setEditing] = useState<CatalogRow | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      const [t, v] = await Promise.all([
        apiCall<PageT<CatalogRow>>("GET", "/threats?limit=500"),
        apiCall<PageT<CatalogRow>>("GET", "/vulnerabilities?limit=500"),
      ]);
      setThreats(t.items);
      setVulns(v.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  function openNew(k: Kind) {
    setKind(k);
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  function openEdit(k: Kind, r: CatalogRow) {
    setKind(k);
    setEditing(r);
    setF(fromRow(r));
    setError(null);
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    const m = META[kind];
    try {
      const payload = { name: f.name.trim(), description: f.description, category: f.category.trim() };
      if (editing) await apiCall("PATCH", `/${m.base}/${editing.id}`, payload);
      else await apiCall("POST", `/${m.base}`, payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to save ${m.label.toLowerCase()}`);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!editing) return;
    const m = META[kind];
    setError(null);
    setDeleting(true);
    try {
      await apiCall("DELETE", `/${m.base}/${editing.id}`);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to delete ${m.label.toLowerCase()}`);
    } finally {
      setDeleting(false);
    }
  }

  const m = META[kind];
  const datalistId = `cat-suggest-${kind}`;

  const formBody = (
    <>
      <Field label="Name" required help={m.help}>
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder={m.placeholderName} required />
      </Field>
      <Field
        label="Category"
        help={`Group ${m.plural.toLowerCase()} for filtering and reporting. Suggestions: ${m.examples
          .slice(0, 5)
          .join(", ")}.`}
      >
        <input
          className="input"
          value={f.category}
          list={datalistId}
          placeholder={m.placeholderCategory}
          onChange={(e) => set("category", e.target.value)}
        />
        <datalist id={datalistId}>
          {m.examples.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </Field>
      <Field label="Description" help={`What this ${m.label.toLowerCase()} is and how it is relevant to risk.`}>
        <TextArea
          value={f.description}
          onChange={(v) => set("description", v)}
          rows={5}
          placeholder={`Describe the ${m.label.toLowerCase()} so risk owners understand when to link it.`}
        />
      </Field>
      {editing && (
        <Field
          label="Usage"
          help="Read-only. Risks reference this item via the Risk Register; deleting it removes those links."
        >
          <div>
            {editing.used_by_risks_count > 0 ? (
              <Badge tone="medium" plain>
                Linked to {editing.used_by_risks_count} risk{editing.used_by_risks_count === 1 ? "" : "s"}
              </Badge>
            ) : (
              <span className="muted">Not yet linked to any risk.</span>
            )}
          </div>
        </Field>
      )}
    </>
  );

  const deleteBtn = editing ? (
    <button
      className="btn secondary sm"
      type="button"
      onClick={remove}
      disabled={deleting || saving}
      style={{ color: "var(--danger, #c0392b)" }}
    >
      {deleting ? "Deleting…" : "Delete"}
    </button>
  ) : undefined;

  const total = threats.length + vulns.length;
  const linkedTotal = useMemo(
    () =>
      threats.filter((r) => r.used_by_risks_count > 0).length +
      vulns.filter((r) => r.used_by_risks_count > 0).length,
    [threats, vulns],
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Threat &amp; Vulnerability Library</h1>
          <p>Reusable catalogs you can link to risks — a threat exploits a vulnerability to create a risk.</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" onClick={() => openNew("threat")}>
            <IconPlus width={16} height={16} /> Add threat
          </button>
          <button className="btn" onClick={() => openNew("vulnerability")}>
            <IconPlus width={16} height={16} /> Add vulnerability
          </button>
        </div>
      </div>

      {error && !showForm && (
        <div className="error" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <CatalogSection kind="threat" rows={threats} onEdit={(r) => openEdit("threat", r)} onAdd={() => openNew("threat")} />
        <CatalogSection
          kind="vulnerability"
          rows={vulns}
          onEdit={(r) => openEdit("vulnerability", r)}
          onAdd={() => openNew("vulnerability")}
        />
      </div>

      <div className="card card-pad" style={{ marginTop: 16 }}>
        <div className="empty" style={{ padding: "8px 0" }}>
          <span className="ico">
            <IconRisk width={22} height={22} />
          </span>
          <p>
            {total} catalog item{total === 1 ? "" : "s"}
            {linkedTotal ? `, ${linkedTotal} linked to risks. ` : ". "}
            Link threats &amp; vulnerabilities to risks when creating a risk in the Risk Register.
          </p>
        </div>
      </div>

      {showForm && (
        <FormModal
          title={editing ? `Edit ${m.label.toLowerCase()} — ${editing.name}` : `Add ${m.label.toLowerCase()}`}
          tabs={[{ id: "general", label: "General", content: formBody, required: true }]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving || deleting}
          error={error}
          saveLabel={editing ? "Save changes" : `Create ${m.label.toLowerCase()}`}
          footerLeft={deleteBtn}
        />
      )}
    </>
  );
}
