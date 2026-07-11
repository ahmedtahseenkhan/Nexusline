"use client";

import { Suspense, useCallback, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import AsyncSelect from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import FileAttachments from "@/components/FileAttachments";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconEvidence, IconPlus } from "@/components/icons";

// ---- inline types (backend: app/schemas/evidence.py, app/schemas/control.py) ----
type ControlRef = { id: string; name: string; reference: string };

type Evidence = {
  id: string;
  control_id: string;
  title: string;
  description: string;
  evidence_type: string;
  reference: string;
  status: string;
  collected_at: string | null;
  valid_until: string | null;
  control?: ControlRef | null;
  is_expired: boolean;
  created_at: string;
};

type ControlListItem = { id: string; name: string; reference: string };

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const TYPES = opts(["document", "screenshot", "log", "link", "configuration", "other"]);
const STATUS = opts(["pending", "valid", "expired"]);

const STATUS_TONE: Record<string, "low" | "medium" | "critical" | "neutral"> = {
  valid: "low",
  pending: "medium",
  expired: "critical",
};

type FormState = {
  control_id: string;
  control_label: string;
  title: string;
  description: string;
  evidence_type: string;
  status: string;
  reference: string;
  collected_at: string;
  valid_until: string;
};

const BLANK: FormState = {
  control_id: "",
  control_label: "",
  title: "",
  description: "",
  evidence_type: "document",
  status: "valid",
  reference: "",
  collected_at: "",
  valid_until: "",
};

function fromEvidence(e: Evidence): FormState {
  return {
    control_id: e.control_id,
    control_label: e.control ? e.control.reference || e.control.name : "",
    title: e.title,
    description: e.description || "",
    evidence_type: e.evidence_type,
    status: e.status,
    reference: e.reference || "",
    collected_at: e.collected_at || "",
    valid_until: e.valid_until || "",
  };
}

/** Convert form state into the API payload, normalising empty dates to null. */
function toPayload(f: FormState) {
  return {
    control_id: f.control_id,
    title: f.title,
    description: f.description,
    evidence_type: f.evidence_type,
    status: f.status,
    reference: f.reference,
    collected_at: f.collected_at || null,
    valid_until: f.valid_until || null,
  };
}

function EvidenceInner() {
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [editing, setEditing] = useState<Evidence | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setF((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchEvidence = useCallback(
    (qs: string) => apiCall<PagedList<Evidence>>("GET", `/evidence?${qs}`),
    [],
  );

  // server typeahead over the control catalog — any control is reachable, not just the first page
  const searchControls = (q: string) =>
    apiCall<PagedList<ControlListItem>>("GET", `/controls?search=${encodeURIComponent(q)}&limit=20`).then(
      (r) => r.items.map((c) => ({ value: c.id, label: c.name, sub: c.reference })),
    );

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    setShowForm(true);
  }
  function openEdit(e: Evidence) {
    setEditing(e);
    setF(fromEvidence(e));
    setError(null);
    setShowForm(true);
  }

  async function save() {
    setError(null);
    if (!f.control_id) {
      setError("A control is required — evidence is collected against a control.");
      return;
    }
    setSaving(true);
    try {
      const payload = toPayload(f);
      if (editing) {
        await apiCall<Evidence>("PATCH", `/evidence/${editing.id}`, payload);
        setShowForm(false);
        toast("Changes saved");
      } else {
        // Convert to edit mode after creating so the Files tab becomes usable and
        // the user can immediately upload the actual artifact.
        const created = await apiCall<Evidence>("POST", "/evidence", payload);
        setEditing(created);
        toast("Evidence collected");
      }
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save evidence");
    } finally {
      setSaving(false);
    }
  }

  async function remove(ev: Evidence) {
    if (!(await confirmDialog({ title: `Delete evidence "${ev.title}"?`, message: "This cannot be undone.", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/evidence/${ev.id}`);
      if (editing?.id === ev.id) setShowForm(false);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const controlLabel = (e: Evidence) => (e.control ? e.control.reference || e.control.name : "—");

  const columns: Column<Evidence>[] = [
    {
      key: "reference",
      header: "Ref",
      sortable: true,
      render: (ev) => (
        <span style={{ display: "inline-block", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", verticalAlign: "bottom" }}>
          {ev.reference ? (
            <a href={ev.reference} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
              {ev.reference}
            </a>
          ) : (
            <span className="muted">—</span>
          )}
        </span>
      ),
    },
    { key: "title", header: "Title", sortable: true, render: (ev) => <span className="cell-title">{ev.title}</span> },
    { key: "evidence_type", header: "Type", sortable: true, render: (ev) => <Badge tone="info" plain>{cap(ev.evidence_type)}</Badge> },
    {
      key: "status",
      header: "Status",
      sortable: true,
      render: (ev) => (
        <Badge tone={ev.is_expired ? "critical" : STATUS_TONE[ev.status] || "neutral"}>
          {ev.is_expired && ev.status !== "expired" ? "Expired" : cap(ev.status)}
        </Badge>
      ),
    },
    { key: "control", header: "Control", render: (ev) => <span className="muted">{controlLabel(ev)}</span> },
    { key: "collected_at", header: "Collected", sortable: true, render: (ev) => <span className="muted">{ev.collected_at || "—"}</span> },
    {
      key: "valid_until",
      header: "Valid until",
      sortable: true,
      render: (ev) => (ev.valid_until ? (ev.is_expired ? <Badge tone="high">{ev.valid_until}</Badge> : <span className="muted">{ev.valid_until}</span>) : <span className="muted">—</span>),
    },
    {
      key: "actions",
      header: "",
      render: (ev) => (
        <div onClick={(e) => e.stopPropagation()}>
          <button className="btn secondary sm" onClick={() => openEdit(ev)}>Edit</button>{" "}
          <button className="btn secondary sm" onClick={() => remove(ev)}>Delete</button>
        </div>
      ),
    },
  ];

  const generalTab = (
    <>
      <Field label="Control" required help="Evidence is collected against a control — collect once, satisfy every requirement that control maps to.">
        <AsyncSelect
          search={searchControls}
          value={f.control_id || null}
          selectedLabel={f.control_label}
          onChange={(v, o) => setF((p) => ({ ...p, control_id: v || "", control_label: o?.label || "" }))}
          placeholder="Search controls…"
        />
      </Field>
      <Field label="Title" required help="For example: Q2 access review export, Firewall ruleset screenshot.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Q2 access review export" required />
      </Field>
      <Field label="Description" help="What this artifact demonstrates and how it was obtained.">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={4} placeholder="Exported from the IAM console on the first business day of the quarter…" />
      </Field>
      <div className="field-row">
        <Field label="Type" help="A label for the artifact. Upload the file in the Files tab, or paste a link under Source & Validity.">
          <Select value={f.evidence_type} onChange={(v) => set("evidence_type", v)} options={TYPES} />
        </Field>
        <Field label="Status" help="Expired evidence (or one past its valid-until date) is flagged in the list.">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
      </div>
    </>
  );

  const filesTab = editing ? (
    <FileAttachments entityType="evidence" entityId={editing.id} />
  ) : (
    <div className="muted" style={{ fontSize: 13, padding: "8px 0" }}>
      Save this evidence first (click <b>Collect evidence</b>) — the form stays open and you can
      upload the actual artifact file(s) here.
    </div>
  );

  const sourceTab = (
    <>
      <Field label="Reference (URL or location)" help="Link to the artifact, ticket, or file store location.">
        <TextInput value={f.reference} onChange={(v) => set("reference", v)} placeholder="https://drive.example.com/evidence/q2-access-review.pdf" />
      </Field>
      <div className="field-row">
        <Field label="Collected at" help="When this evidence was gathered.">
          <TextInput type="date" value={f.collected_at} onChange={(v) => set("collected_at", v)} />
        </Field>
        <Field label="Valid until" help="When this evidence goes stale and must be re-collected. Leave blank if it does not expire.">
          <TextInput type="date" value={f.valid_until} onChange={(v) => set("valid_until", v)} />
        </Field>
      </div>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Evidence</h1>
          <p>Audit-ready artifacts attached to controls — collect once, satisfy many.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="evidence" label="Evidence" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add evidence
          </button>
        </div>
      </div>

      {error && !showForm && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<Evidence>
        columns={columns}
        fetcher={fetchEvidence}
        rowKey={(e) => e.id}
        onRowClick={(e) => openEdit(e)}
        searchPlaceholder="Search evidence by title or reference…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No evidence yet. Attach evidence to a control to demonstrate compliance."
        refreshKey={refreshKey}
        toolbarRight={<span className="muted" style={{ fontSize: 13, display: "inline-flex", gap: 6, alignItems: "center" }}><IconEvidence width={16} height={16} /> collect once, satisfy many</span>}
      />

      {showForm && (
        <FormModal
          title={editing ? `Edit evidence — ${editing.title}` : "Add item (Evidence)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "source", label: "Source & Validity", content: sourceTab },
            { id: "files", label: "Files", content: filesTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Collect evidence"}
        />
      )}
    </>
  );
}

export default function EvidencePage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <EvidenceInner />
    </Suspense>
  );
}
