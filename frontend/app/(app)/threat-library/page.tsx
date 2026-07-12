"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconShield, IconAlert } from "@/components/icons";

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
  refreshKey,
  onView,
  onEdit,
  onAdd,
  onDelete,
  onImported,
  activeKey,
}: {
  kind: Kind;
  refreshKey: number;
  onView: (r: CatalogRow) => void;
  onEdit: (r: CatalogRow) => void;
  onAdd: () => void;
  onDelete: (r: CatalogRow) => void;
  onImported: () => void;
  activeKey?: string;
}) {
  const m = META[kind];

  const fetcher = useCallback(
    (qs: string) => apiCall<PagedList<CatalogRow>>("GET", `/${m.base}?${qs}`),
    [m.base],
  );

  const columns: Column<CatalogRow>[] = [
    { key: "name", header: "Name", sortable: true, render: (r) => <span className="cell-title">{r.name}</span> },
    {
      key: "category",
      header: "Category",
      sortable: true,
      render: (r) => (r.category ? <Badge tone="info" plain>{r.category}</Badge> : <span className="muted">—</span>),
    },
    {
      key: "description",
      header: "Description",
      render: (r) =>
        r.description ? (
          <span
            className="muted"
            style={{ display: "block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            title={r.description}
          >
            {r.description}
          </span>
        ) : (
          <span className="muted">—</span>
        ),
    },
    {
      key: "used_by_risks_count",
      header: "Used by risks",
      align: "center",
      render: (r) =>
        r.used_by_risks_count > 0 ? <Badge tone="medium" plain>{r.used_by_risks_count}</Badge> : <span className="muted">0</span>,
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => onEdit(r)}>Edit</button>{" "}
          <button className="btn secondary sm" onClick={() => onDelete(r)}>Delete</button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div className="card-head" style={{ marginBottom: 8 }}>
        <div>
          <h3>{m.plural}</h3>
          <span className="sub">Reusable catalog linked to risks.</span>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource={m.base} label={m.plural} onDone={onImported} />
          <button className="btn sm" onClick={onAdd}>
            <IconPlus width={14} height={14} /> Add {m.label.toLowerCase()}
          </button>
        </div>
      </div>
      <DataTable<CatalogRow>
        columns={columns}
        fetcher={fetcher}
        rowKey={(r) => r.id}
        onRowClick={onView}
        activeKey={activeKey}
        searchPlaceholder={`Search ${m.plural.toLowerCase()} by name…`}
        defaultSort={{ by: "name", dir: "asc" }}
        emptyMessage={`No ${m.plural.toLowerCase()} yet. Add your first ${m.label.toLowerCase()} to seed the risk register.`}
        refreshKey={refreshKey}
      />
    </div>
  );
}

function ThreatLibraryInner() {
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  // Read-only detail loaded for the view drawer (?id=). The ?id can point to a
  // threat or a vulnerability — viewKind records which catalog it resolved to.
  const [recordId, setRecordId] = useRecordParam("id");
  const [detail, setDetail] = useState<CatalogRow | null>(null);
  const [viewKind, setViewKind] = useState<Kind>("threat");

  // single shared dialog, parameterised by kind + editing target
  const [kind, setKind] = useState<Kind>("threat");
  const [editing, setEditing] = useState<CatalogRow | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

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

  // Deep-link view: ?id= (row click, global search, ⌘K) loads the record's full
  // detail into the read-only drawer. The id may belong to either catalog, so try
  // the threat endpoint first and fall back to the vulnerability endpoint.
  const loadDetail = useCallback((id: string) => {
    apiCall<CatalogRow>("GET", `/threats/${id}`)
      .then((r) => { setViewKind("threat"); setDetail(r); })
      .catch(() =>
        apiCall<CatalogRow>("GET", `/vulnerabilities/${id}`)
          .then((r) => { setViewKind("vulnerability"); setDetail(r); })
          .catch(() => setDetail(null)),
      );
  }, []);
  useEffect(() => {
    if (recordId) loadDetail(recordId);
    else setDetail(null);
  }, [recordId, loadDetail]);

  async function save() {
    setError(null);
    setSaving(true);
    const m = META[kind];
    try {
      const payload = { name: f.name.trim(), description: f.description, category: f.category.trim() };
      if (editing) await apiCall("PATCH", `/${m.base}/${editing.id}`, payload);
      else await apiCall("POST", `/${m.base}`, payload);
      setShowForm(false);
      reload();
      if (recordId) loadDetail(recordId); // refresh the open view drawer
      toast(editing ? "Changes saved" : `${m.label} created`);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Failed to save ${m.label.toLowerCase()}`);
    } finally {
      setSaving(false);
    }
  }

  async function remove(k: Kind, r: CatalogRow) {
    const m = META[k];
    const warn =
      r.used_by_risks_count > 0
        ? `This ${m.label.toLowerCase()} is linked to ${r.used_by_risks_count} risk${r.used_by_risks_count === 1 ? "" : "s"}; deleting it removes those links.`
        : "This cannot be undone.";
    if (!(await confirmDialog({ title: `Delete ${m.label.toLowerCase()} "${r.name}"?`, message: warn, danger: true }))) return;
    setError(null);
    setDeleting(true);
    try {
      await apiCall("DELETE", `/${m.base}/${r.id}`);
      if (editing?.id === r.id) setShowForm(false);
      if (recordId === r.id) setRecordId(null);
      reload();
      toast("Deleted");
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
      onClick={() => remove(kind, editing)}
      disabled={deleting || saving}
      style={{ color: "var(--danger, #c0392b)" }}
    >
      {deleting ? "Deleting…" : "Delete"}
    </button>
  ) : undefined;

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

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", alignItems: "start" }}>
        <CatalogSection
          kind="threat"
          refreshKey={refreshKey}
          onView={(r) => setRecordId(r.id)}
          activeKey={recordId ?? undefined}
          onEdit={(r) => openEdit("threat", r)}
          onAdd={() => openNew("threat")}
          onDelete={(r) => remove("threat", r)}
          onImported={reload}
        />
        <CatalogSection
          kind="vulnerability"
          refreshKey={refreshKey}
          onView={(r) => setRecordId(r.id)}
          activeKey={recordId ?? undefined}
          onEdit={(r) => openEdit("vulnerability", r)}
          onAdd={() => openNew("vulnerability")}
          onDelete={(r) => remove("vulnerability", r)}
          onImported={reload}
        />
      </div>

      {/* Read-only detail view (?id=) — click a row to see everything; Edit is separate. */}
      <RecordDrawer
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? detail.name : "…"}
        subtitle={detail ? META[viewKind].label + (detail.category ? ` · ${detail.category}` : "") : ""}
        width={560}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(viewKind, detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(viewKind, detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              <div style={{ minWidth: 140 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Type</div>
                <div style={{ marginTop: 3 }}><Badge tone="info" plain>{META[viewKind].label}</Badge></div>
              </div>
              <div style={{ minWidth: 140 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Category</div>
                <div style={{ marginTop: 3 }}>
                  {detail.category ? <Badge tone="info" plain>{detail.category}</Badge> : <span className="muted">—</span>}
                </div>
              </div>
              <div style={{ minWidth: 140 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Used by risks</div>
                <div style={{ marginTop: 3 }}>
                  {detail.used_by_risks_count > 0 ? (
                    <Badge tone="medium" plain>{detail.used_by_risks_count} risk{detail.used_by_risks_count === 1 ? "" : "s"}</Badge>
                  ) : (
                    <span className="muted">Not yet linked</span>
                  )}
                </div>
              </div>
            </div>

            {detail.description ? (
              <div>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description</div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }}>{detail.description}</div>
              </div>
            ) : (
              <p className="muted" style={{ fontSize: 13 }}>No description.</p>
            )}
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit ${m.label.toLowerCase()} — ${editing.name}` : `Add ${m.label.toLowerCase()}`}
          tabs={[{ id: "general", label: "General", content: formBody, required: true }]}
          onClose={() => { setShowForm(false); setRecordId(null); }}
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

export default function ThreatLibraryPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <ThreatLibraryInner />
    </Suspense>
  );
}
