"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type Policy, type Control, type Risk } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, MultiSelect, Toggle, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconPolicy } from "@/components/icons";

const POLICY_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  published: "low",
  approved: "info",
  under_review: "medium",
  draft: "neutral",
  retired: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "under_review", "approved", "published", "retired"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const DOCTYPE = opts(["policy", "standard", "procedure", "guideline"]);

type FormState = {
  title: string;
  summary: string;
  owner: string;
  category: string;
  status: string;
  workflow_status: string;
  review_frequency: string;
  document_type: string;
  version: string;
  use_attachments: boolean;
  url: string;
  body: string;
  related_ids: string[];
  controls_ids: string[];
  risks_ids: string[];
};

const BLANK: FormState = {
  title: "", summary: "", owner: "", category: "",
  status: "draft", workflow_status: "draft", review_frequency: "annual",
  document_type: "policy", version: "1.0", use_attachments: false, url: "", body: "",
  related_ids: [], controls_ids: [], risks_ids: [],
};

function fromPolicy(p: Policy): FormState {
  return {
    title: p.title, summary: p.summary || "", owner: p.owner || "", category: p.category || "",
    status: p.status, workflow_status: p.workflow_status, review_frequency: p.review_frequency,
    document_type: p.document_type, version: p.version, use_attachments: p.use_attachments,
    url: p.url || "", body: p.body || "",
    related_ids: p.related.map((r) => r.id),
    controls_ids: p.controls.map((r) => r.id),
    risks_ids: p.risks.map((r) => r.id),
  };
}

export default function PoliciesPage() {
  const [items, setItems] = useState<Policy[]>([]);
  const [controls, setControls] = useState<Control[]>([]);
  const [risks, setRisks] = useState<Risk[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const [editing, setEditing] = useState<Policy | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const [detailId, setDetailId] = useState<string | null>(null);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems((await api.policies()).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
    api.controls().then((r) => setControls(r.items)).catch(() => {});
    api.risks().then((r) => setRisks(r.items)).catch(() => {});
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setShowForm(true);
  }
  function openEdit(p: Policy) {
    setEditing(p);
    setF(fromPolicy(p));
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      if (editing) await api.updatePolicy(editing.id, f);
      else await api.createPolicy(f);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save policy");
    } finally {
      setSaving(false);
    }
  }

  async function acknowledge(id: string, ref: string) {
    setError(null);
    try {
      await api.acknowledgePolicy(id);
      setNote(`You acknowledged ${ref}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to acknowledge");
    }
  }

  const policyOpts: Option[] = useMemo(
    () => items.filter((p) => p.id !== editing?.id).map((p) => ({ value: p.id, label: p.title, sub: p.reference })),
    [items, editing],
  );
  const controlOpts: Option[] = useMemo(
    () => controls.map((c) => ({ value: c.id, label: c.name, sub: c.reference })),
    [controls],
  );
  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: r.title, sub: r.reference })),
    [risks],
  );

  const linkCount = (p: Policy) => p.related.length + p.controls.length + p.requirements.length + p.risks.length;

  const generalTab = (
    <>
      <Field label="Name" required help="For example: Encryption Standards, Security Policy, HR Policies, etc.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Data Retention Policy" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.summary} onChange={(v) => set("summary", v)} rows={3} placeholder="Short summary of the policy's purpose and scope." />
      </Field>
      <div className="field-row">
        <Field label="Owner / GRC Contact">
          <TextInput value={f.owner} onChange={(v) => set("owner", v)} placeholder="CISO" />
        </Field>
        <Field label="Category">
          <TextInput value={f.category} onChange={(v) => set("category", v)} placeholder="Security" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Review Frequency">
          <Select value={f.review_frequency} onChange={(v) => set("review_frequency", v)} options={FREQ} />
        </Field>
      </div>
    </>
  );

  const contentTab = (
    <>
      <div className="field-row">
        <Field label="Document Type">
          <Select value={f.document_type} onChange={(v) => set("document_type", v)} options={DOCTYPE} />
        </Field>
        <Field label="Version">
          <TextInput value={f.version} onChange={(v) => set("version", v)} placeholder="1.0" />
        </Field>
      </div>
      <Field label="Document Source" help="Toggle on to reference an uploaded file or external URL instead of inline content.">
        <Toggle checked={f.use_attachments} onChange={(v) => set("use_attachments", v)} label="Use external document / attachment" />
      </Field>
      {f.use_attachments && (
        <Field label="External Document URL">
          <TextInput value={f.url} onChange={(v) => set("url", v)} placeholder="https://docs.example.com/policy.pdf" />
        </Field>
      )}
      <Field label="Document Content">
        <RichText value={f.body} onChange={(v) => set("body", v)} />
      </Field>
    </>
  );

  const linksTab = (
    <>
      <Field label="Related Policies" help="Cross-link policies that supersede, reference or depend on this one.">
        <MultiSelect value={f.related_ids} onChange={(v) => set("related_ids", v)} options={policyOpts} />
      </Field>
      <Field label="Related Controls" help="Controls that implement or enforce this policy.">
        <MultiSelect value={f.controls_ids} onChange={(v) => set("controls_ids", v)} options={controlOpts} />
      </Field>
      <Field label="Related Risks" help="Risks this policy mitigates or addresses.">
        <MultiSelect value={f.risks_ids} onChange={(v) => set("risks_ids", v)} options={riskOpts} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Policy Management</h1>
          <p>Repository for policies with document content, versioning, review cycles, cross-links and acknowledgments.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="policies" label="Policies" onDone={load} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add policy
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
      {note && (
        <div className="card card-pad" style={{ marginBottom: 16, borderColor: "var(--primary)" }}>{note}</div>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Policies</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Name</th>
                <th>Type</th>
                <th>Version</th>
                <th>Status</th>
                <th>Owner</th>
                <th>Links</th>
                <th>Reviews</th>
                <th>Acks</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => openEdit(p)}>
                  <td className="ref">{p.reference}</td>
                  <td className="cell-title">{p.title}</td>
                  <td><Badge tone="neutral" plain>{cap(p.document_type)}</Badge></td>
                  <td className="muted">v{p.version}</td>
                  <td><Badge tone={POLICY_TONE[p.status] || "neutral"}>{cap(p.status)}</Badge></td>
                  <td className="muted">{p.owner || "—"}</td>
                  <td className="muted">{linkCount(p) || "—"}</td>
                  <td>
                    {p.is_review_overdue
                      ? <Badge tone="high">Overdue</Badge>
                      : <span className="muted">{p.next_review_date || "—"}</span>}
                  </td>
                  <td><Badge tone="info" plain>{p.acknowledgment_count}</Badge></td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => setDetailId(detailId === p.id ? null : p.id)}>
                        Details
                      </button>
                      <button className="btn secondary sm" onClick={() => acknowledge(p.id, p.reference)}>
                        <IconCheck width={14} height={14} /> Ack
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconPolicy width={24} height={24} /></span>
                      <h3>No policies</h3>
                      <p>Create your first policy to build the repository.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detailId && <RecordPanels model="policy" entityId={detailId} />}

      {showForm && (
        <FormModal
          title={editing ? `Edit policy — ${editing.reference}` : "Add item (Policies)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "content", label: "Policy Content", content: contentTab },
            { id: "links", label: "Links & Relations", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create policy"}
        />
      )}
    </>
  );
}
