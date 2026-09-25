"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import RecordPanels from "@/components/RecordPanels";
import AsyncSelect from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import FileAttachments from "@/components/FileAttachments";
import { useCustomFieldForm } from "@/components/useCustomFieldForm";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconEvidence, IconPlus } from "@/components/icons";
import { sentenceCase, titleCase } from "@/lib/text";
import { useFormat } from "@/lib/format";
import { safeLinkUrl } from "@/lib/sanitize";
import { TEST_RESULT_LABEL as RESULT_LABEL, TEST_REVIEW_LABEL as REVIEW_LABEL, controlTestTitle } from "@/lib/record/control";

// ---- inline types (backend: app/schemas/evidence.py, app/schemas/control.py) ----
type ControlRef = { id: string; name: string; reference: string };
/** The control test an evidence item supports (backend: ControlTestRef). */
type ControlTestRef = {
  id: string; control_id: string; test_type: string | null; result: string;
  conducted_date: string | null; review_status: string;
};

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
  control_audit_id?: string | null;
  control_audit?: ControlTestRef | null;
  is_expired: boolean;
  display_status?: string;
  created_at: string;
};

type ControlListItem = { id: string; name: string; reference: string };

const cap = titleCase;
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

// What the register shows. "Valid" with no collection date is a claim about nothing, so
// uncollected evidence reads "Not collected" whatever its stored status says.
function statusBadge(ev: Evidence) {
  const shown = ev.display_status || (ev.is_expired ? "expired" : ev.status);
  if (shown === "expired") return <Badge tone="critical">Expired</Badge>;
  if (shown === "not_collected") return <Badge tone="neutral">Not collected</Badge>;
  return <Badge tone={STATUS_TONE[shown] || "neutral"}>{cap(shown)}</Badge>;
}

function statusLabel(ev: Evidence) {
  const shown = ev.display_status || (ev.is_expired ? "expired" : ev.status);
  return shown === "not_collected" ? "Not collected" : cap(shown);
}

const TYPES = opts(["document", "screenshot", "log", "link", "configuration", "other"]);
/* Test results and reviews use the control record's words (RESULT_LABEL / REVIEW_LABEL
   come from lib/record/control.ts, the one home of that wording). */
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
  status: "pending",
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
  const [recordId, setRecordId] = useRecordParam("id");
  const { formatDate, formatDateTime } = useFormat();
  // Read-only detail loaded for the view drawer (?id=). Edit is a separate action.
  const [detail, setDetail] = useState<Evidence | null>(null);

  const [editing, setEditing] = useState<Evidence | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const cfForm = useCustomFieldForm("evidence");

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
    cfForm.start(null);
    setError(null);
    setShowForm(true);
  }
  function openEdit(e: Evidence) {
    setEditing(e);
    setF(fromEvidence(e));
    cfForm.start(e.id);
    setError(null);
    setShowForm(true);
  }

  // Deep-link view: ?id= (row click, global search, ⌘K) loads the record's full
  // detail into the read-only drawer. Editing is a separate action from there.
  const loadDetail = useCallback((id: string) => {
    apiCall<Evidence>("GET", `/evidence/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (recordId) loadDetail(recordId);
    else setDetail(null);
  }, [recordId, loadDetail]);

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
        await cfForm.save(editing.id);
        setShowForm(false);
        toast("Changes saved");
      } else {
        // Convert to edit mode after creating so the Files tab becomes usable and
        // the user can immediately upload the actual artifact.
        const created = await apiCall<Evidence>("POST", "/evidence", payload);
        await cfForm.save(created.id);
        setEditing(created);
        toast("Evidence collected");
      }
      reload();
      if (recordId) loadDetail(recordId); // refresh the open view drawer
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
      if (recordId === ev.id) setRecordId(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  const controlLabel = (e: Evidence) => (e.control ? e.control.reference || e.control.name : "—");
  /** The control this evidence is collected against, as the control record names it:
   *  reference chip, then the name, linking to the control. */
  const controlLink = (e: Evidence) =>
    e.control ? (
      <Link
        href={`/controls?id=${e.control.id}`}
        className="chip chip-link"
        title={[e.control.reference, e.control.name].filter(Boolean).join(" ")}
        onClick={(ev) => ev.stopPropagation()}
      >
        {e.control.reference && <span className="ref" style={{ marginRight: 5 }}>{e.control.reference}</span>}
        {e.control.name}
      </Link>
    ) : (
      <span className="muted">Not set</span>
    );
  /** "Operating test of 12 Sep 2026 · Failed · Reviewed" — the test this evidence
   *  supports, in the words of the control's "Effectiveness & tests" section. */
  const testLabel = (t: ControlTestRef) =>
    [
      controlTestTitle(t, { date: formatDate }),
      RESULT_LABEL[t.result] ?? sentenceCase(t.result),
      REVIEW_LABEL[t.review_status] ?? sentenceCase(t.review_status),
    ].join(" · ");
  /** Opens the control on its "Effectiveness & tests" section (`#tests`), where the test is listed. */
  const testLink = (e: Evidence) =>
    e.control_audit ? (
      <Link href={`/controls?id=${e.control_audit.control_id}#tests`} className="chip chip-link" onClick={(ev) => ev.stopPropagation()}>
        {testLabel(e.control_audit)}
      </Link>
    ) : (
      <span className="muted">Not attached to a test</span>
    );

  // read-only helper for the view drawer
  const field = (label: string, value: React.ReactNode) => (
    <div style={{ minWidth: 140 }}>
      <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>{label}</div>
      <div style={{ marginTop: 3 }}>{value ?? <span className="muted">—</span>}</div>
    </div>
  );

  const columns: Column<Evidence>[] = [
    {
      key: "reference",
      header: "Ref",
      sortable: true,
      render: (ev) => (
        <span style={{ display: "inline-block", maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", verticalAlign: "bottom" }}>
          {ev.reference && safeLinkUrl(ev.reference) ? (
            <a href={safeLinkUrl(ev.reference) ?? undefined} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
              {ev.reference}
            </a>
          ) : ev.reference ? (
            // Not a web or mail address (a file path, a folder name, or an unsafe scheme): text only.
            <span title={ev.reference}>{ev.reference}</span>
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
      render: (ev) => statusBadge(ev),
    },
    { key: "control", header: "Control", render: (ev) => <span className="muted">{controlLabel(ev)}</span> },
    { key: "control_audit", header: "Supports test", render: (ev) => testLink(ev), text: (ev) => (ev.control_audit ? testLabel(ev.control_audit) : "") },
    { key: "collected_at", header: "Collected", sortable: true, render: (ev) => <span className="muted">{ev.collected_at ? formatDate(ev.collected_at) : "Not collected"}</span> },
    {
      key: "valid_until",
      header: "Valid until",
      sortable: true,
      render: (ev) => (ev.valid_until ? (ev.is_expired ? <Badge tone="high">{formatDate(ev.valid_until)}</Badge> : <span className="muted">{formatDate(ev.valid_until)}</span>) : <span className="muted">{ev.collected_at ? "No expiry set" : "—"}</span>),
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
        <Field label="Status" help="Mark it valid once it has been collected (set the collected date under Source & Validity). Expired evidence, or evidence past its valid-until date, is flagged in the list.">
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
        onRowClick={(e) => setRecordId(e.id)}
        activeKey={recordId ?? undefined}
        searchPlaceholder="Search evidence by title or reference…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No evidence yet. Attach evidence to a control to demonstrate compliance."
        refreshKey={refreshKey}
        toolbarRight={<span className="muted" style={{ fontSize: 13, display: "inline-flex", gap: 6, alignItems: "center" }}><IconEvidence width={16} height={16} /> collect once, satisfy many</span>}
      />

      {/* Read-only detail view (?id=) — click a row to see everything; Edit is separate. */}
      <RecordDrawer
        aside={detail ? <RecordPanels model="evidence" entityId={detail.id} /> : null}
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? detail.title : "…"}
        subtitle={detail ? cap(detail.evidence_type) + " · " + statusLabel(detail) : ""}
        width={640}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 16 }}>
              {field("Control", controlLink(detail))}
              {field("Supports test", testLink(detail))}
              {field("Type", <Badge tone="info" plain>{cap(detail.evidence_type)}</Badge>)}
              {field("Status", statusBadge(detail))}
            </div>

            {detail.description && (
              <div style={{ marginBottom: 16 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>Description</div>
                <div style={{ fontSize: 14, lineHeight: 1.5 }}>{detail.description}</div>
              </div>
            )}

            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 18 }}>
              {field("Reference", detail.reference ? (
                safeLinkUrl(detail.reference)
                  ? <a href={safeLinkUrl(detail.reference) ?? undefined} target="_blank" rel="noopener noreferrer">{detail.reference}</a>
                  : detail.reference
              ) : "—")}
              {field("Collected at", detail.collected_at ? formatDate(detail.collected_at) : "Not collected")}
              {field("Valid until", detail.valid_until ? (
                detail.is_expired ? <Badge tone="high">{formatDate(detail.valid_until)}</Badge> : formatDate(detail.valid_until)
              ) : (detail.collected_at ? "No expiry set" : "—"))}
              {field("Created", formatDateTime(detail.created_at))}
            </div>

            <div style={{ marginBottom: 8 }}>
              <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Files</div>
              <FileAttachments entityType="evidence" entityId={detail.id} />
            </div>

            <div style={{ marginTop: 18, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
            </div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit evidence — ${editing.title}` : "Add item (Evidence)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "source", label: "Source & Validity", content: sourceTab },
            { id: "files", label: "Files", content: filesTab },
            ...cfForm.tabs,
          ]}
          onClose={() => { setShowForm(false); setRecordId(null); }}
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
