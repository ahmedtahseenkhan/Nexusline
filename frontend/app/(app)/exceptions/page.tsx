"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RichText from "@/components/RichText";
import { Field, TextInput, TextArea, Select, MultiSelect, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconAlert } from "@/components/icons";

// ----- inline types (api.ts is shared / read-only) -----------------------------
type LinkRef = { id: string; reference?: string; title?: string; name?: string };

type Exception = {
  id: string;
  reference: string;
  title: string;
  description: string;
  exception_type: string;
  classification: string;
  rationale: string;
  compensating_controls: string;
  business_owner: string;
  workflow_status: string;
  status: string;
  start_date: string | null;
  expires_at: string | null;
  closure_date: string | null;
  requested_by: string | null;
  approver_id: string | null;
  decided_at: string | null;
  is_expired: boolean;
  risks: LinkRef[];
  policies: LinkRef[];
  requirements: LinkRef[];
  controls: LinkRef[];
  assets: LinkRef[];
  created_at: string;
};

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
type Ctrl = { id: string; name: string; reference: string };
type Rk = { id: string; reference: string; title: string };
type Pol = { id: string; reference: string; title: string };
type Req = { id: string; reference: string; title: string };
type Ast = { id: string; name: string };
type Framework = { id: string; name: string };

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  approved: "low",
  pending: "medium",
  rejected: "critical",
  expired: "high",
  closed: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const TYPE = opts(["risk", "policy", "compliance", "other"]);
const STATUS = opts(["pending", "approved", "rejected", "expired", "closed"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);

type FormState = {
  title: string;
  description: string;
  exception_type: string;
  classification: string;
  rationale: string;
  status: string;
  workflow_status: string;
  business_owner: string;
  start_date: string;
  expires_at: string;
  closure_date: string;
  compensating_controls: string;
  control_ids: string[];
  risk_ids: string[];
  policy_ids: string[];
  requirement_ids: string[];
  asset_ids: string[];
};

const BLANK: FormState = {
  title: "", description: "", exception_type: "risk", classification: "",
  rationale: "", status: "pending", workflow_status: "draft", business_owner: "",
  start_date: "", expires_at: "", closure_date: "", compensating_controls: "",
  control_ids: [], risk_ids: [], policy_ids: [], requirement_ids: [], asset_ids: [],
};

function fromException(x: Exception): FormState {
  return {
    title: x.title,
    description: x.description || "",
    exception_type: x.exception_type,
    classification: x.classification || "",
    rationale: x.rationale || "",
    status: x.status,
    workflow_status: x.workflow_status || "draft",
    business_owner: x.business_owner || "",
    start_date: x.start_date || "",
    expires_at: x.expires_at || "",
    closure_date: x.closure_date || "",
    compensating_controls: x.compensating_controls || "",
    control_ids: x.controls.map((r) => r.id),
    risk_ids: x.risks.map((r) => r.id),
    policy_ids: x.policies.map((r) => r.id),
    requirement_ids: x.requirements.map((r) => r.id),
    asset_ids: x.assets.map((r) => r.id),
  };
}

// only send the fields the API understands; empty dates -> null.
// `status` is accepted on PATCH (manual override) but not on create — the model
// always starts a new exception as `pending` and the workflow drives it thereafter.
function toPayload(f: FormState, editing: boolean): Record<string, unknown> {
  return {
    title: f.title,
    description: f.description,
    exception_type: f.exception_type,
    classification: f.classification,
    rationale: f.rationale,
    workflow_status: f.workflow_status,
    business_owner: f.business_owner,
    compensating_controls: f.compensating_controls,
    start_date: f.start_date || null,
    expires_at: f.expires_at || null,
    closure_date: f.closure_date || null,
    control_ids: f.control_ids,
    risk_ids: f.risk_ids,
    policy_ids: f.policy_ids,
    requirement_ids: f.requirement_ids,
    asset_ids: f.asset_ids,
    ...(editing ? { status: f.status } : {}),
  };
}

export default function ExceptionsPage() {
  const [items, setItems] = useState<Exception[]>([]);
  const [controls, setControls] = useState<Ctrl[]>([]);
  const [risks, setRisks] = useState<Rk[]>([]);
  const [policies, setPolicies] = useState<Pol[]>([]);
  const [requirements, setRequirements] = useState<Req[]>([]);
  const [assets, setAssets] = useState<Ast[]>([]);

  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Exception | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const [detailId, setDetailId] = useState<string | null>(null);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      setItems((await apiCall<Page<Exception>>("GET", "/exceptions?limit=200")).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  async function loadRequirements() {
    try {
      const fws = await apiCall<Page<Framework>>("GET", "/frameworks?limit=200");
      const lists = await Promise.all(
        fws.items.map((fw) =>
          apiCall<Req[]>("GET", `/frameworks/${fw.id}/requirements`).catch(() => [] as Req[]),
        ),
      );
      setRequirements(lists.flat());
    } catch {
      /* requirements are optional links */
    }
  }

  useEffect(() => {
    load();
    apiCall<Page<Ctrl>>("GET", "/controls?limit=200").then((r) => setControls(r.items)).catch(() => {});
    apiCall<Page<Rk>>("GET", "/risks?limit=200").then((r) => setRisks(r.items)).catch(() => {});
    apiCall<Page<Pol>>("GET", "/policies?limit=200").then((r) => setPolicies(r.items)).catch(() => {});
    apiCall<Page<Ast>>("GET", "/assets?limit=200").then((r) => setAssets(r.items)).catch(() => {});
    loadRequirements();
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setShowForm(true);
  }
  function openEdit(x: Exception) {
    setEditing(x);
    setF(fromException(x));
    setShowForm(true);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const payload = toPayload(f, !!editing);
      if (editing) await apiCall("PATCH", `/exceptions/${editing.id}`, payload);
      else await apiCall("POST", "/exceptions", payload);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save exception");
    } finally {
      setSaving(false);
    }
  }

  async function act(fn: Promise<unknown>) {
    setError(null);
    try {
      await fn;
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
  }

  const decide = (id: string, approve: boolean) =>
    act(apiCall("POST", `/exceptions/${id}/decision`, { approve, note: "" }));
  const close = (id: string) => act(apiCall("POST", `/exceptions/${id}/close`));
  const remove = (id: string) => act(apiCall("DELETE", `/exceptions/${id}`));

  const controlOpts: Option[] = useMemo(
    () => controls.map((c) => ({ value: c.id, label: c.name, sub: c.reference })),
    [controls],
  );
  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: r.title, sub: r.reference })),
    [risks],
  );
  const policyOpts: Option[] = useMemo(
    () => policies.map((p) => ({ value: p.id, label: p.title, sub: p.reference })),
    [policies],
  );
  const requirementOpts: Option[] = useMemo(
    () => requirements.map((r) => ({ value: r.id, label: r.title, sub: r.reference })),
    [requirements],
  );
  const assetOpts: Option[] = useMemo(
    () => assets.map((a) => ({ value: a.id, label: a.name })),
    [assets],
  );

  const linkCount = (x: Exception) =>
    x.risks.length + x.policies.length + x.requirements.length + x.controls.length + x.assets.length;

  const isPast = (d: string | null) => !!d && new Date(d) < new Date(new Date().toDateString());

  const generalTab = (
    <>
      <Field label="Title" required help="For example: Accept legacy TLS until Q4 migration.">
        <TextInput value={f.title} onChange={(v) => set("title", v)} placeholder="Accept legacy TLS until Q4 migration" required />
      </Field>
      <Field label="Description">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="What gap is being accepted and why it cannot be remediated now." />
      </Field>
      <div className="field-row">
        <Field label="Exception Type" help="What kind of gap this exception covers.">
          <Select value={f.exception_type} onChange={(v) => set("exception_type", v)} options={TYPE} />
        </Field>
        <Field label="Classification" help="Optional grouping label, e.g. Temporary, Permanent, Regulatory.">
          <TextInput value={f.classification} onChange={(v) => set("classification", v)} placeholder="Temporary" />
        </Field>
      </div>
      <div className="field-row">
        {editing ? (
          <Field label="Status" help="Manual override. The row actions (Approve / Reject / Close) are the primary path.">
            <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
          </Field>
        ) : (
          <Field label="Status" help="New exceptions start as Pending and await an approval decision.">
            <TextInput value="Pending (on submit)" onChange={() => {}} />
          </Field>
        )}
        <Field label="Workflow">
          <Select value={f.workflow_status} onChange={(v) => set("workflow_status", v)} options={WORKFLOW} />
        </Field>
        <Field label="Business Owner">
          <TextInput value={f.business_owner} onChange={(v) => set("business_owner", v)} placeholder="Head of Engineering" />
        </Field>
      </div>
      <Field label="Rationale / Justification" help="Business justification for accepting this gap.">
        <RichText value={f.rationale} onChange={(v) => set("rationale", v)} />
      </Field>
    </>
  );

  const validityTab = (
    <>
      <p className="help" style={{ marginBottom: 14 }}>
        Exceptions are time-boxed. An approved exception past its expiry date is flagged as Expired in the register.
      </p>
      <div className="field-row">
        <Field label="Start Date" help="When the exception takes effect.">
          <TextInput type="date" value={f.start_date} onChange={(v) => set("start_date", v)} />
        </Field>
        <Field label="Expires At" help="Hard expiry — the exception must be re-reviewed or closed by this date.">
          <TextInput type="date" value={f.expires_at} onChange={(v) => set("expires_at", v)} />
        </Field>
        <Field label="Closure Date" help="Set when the exception is formally closed.">
          <TextInput type="date" value={f.closure_date} onChange={(v) => set("closure_date", v)} />
        </Field>
      </div>
    </>
  );

  const linksTab = (
    <>
      <Field label="Compensating Controls" help="Interim mitigation in place while the gap is accepted (free text).">
        <TextArea value={f.compensating_controls} onChange={(v) => set("compensating_controls", v)} rows={3} placeholder="e.g. WAF rule + quarterly review of access logs" />
      </Field>
      <Field label="Linked Controls" help="Controls that mitigate or relate to this exception.">
        <MultiSelect value={f.control_ids} onChange={(v) => set("control_ids", v)} options={controlOpts} />
      </Field>
      <Field label="Linked Risks" help="Risks being formally accepted by this exception.">
        <MultiSelect value={f.risk_ids} onChange={(v) => set("risk_ids", v)} options={riskOpts} />
      </Field>
      <Field label="Linked Policies" help="Policies whose requirements are being excepted.">
        <MultiSelect value={f.policy_ids} onChange={(v) => set("policy_ids", v)} options={policyOpts} />
      </Field>
      <Field label="Linked Requirements" help="Compliance requirements covered by this exception.">
        <MultiSelect value={f.requirement_ids} onChange={(v) => set("requirement_ids", v)} options={requirementOpts} />
      </Field>
      <Field label="Linked Assets" help="Assets affected by this exception.">
        <MultiSelect value={f.asset_ids} onChange={(v) => set("asset_ids", v)} options={assetOpts} />
      </Field>
    </>
  );

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Exceptions</h1>
          <p>Formal, time-boxed acceptance of risk, policy or compliance gaps with an approval workflow.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="exceptions" label="Exceptions" onDone={load} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add exception
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Exception register</h3>
          <span className="sub">{items.length} total</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Type</th>
                <th>Status</th>
                <th>Start</th>
                <th>Expires</th>
                <th>Controls</th>
                <th>Risks</th>
                <th>Links</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((x) => (
                <tr key={x.id} style={{ cursor: "pointer" }} onClick={() => openEdit(x)}>
                  <td className="ref">{x.reference}</td>
                  <td className="cell-title">{x.title}</td>
                  <td><Badge tone="info" plain>{cap(x.exception_type)}</Badge></td>
                  <td>
                    <Badge tone={STATUS_TONE[x.status] || "neutral"}>{cap(x.status)}</Badge>
                    {x.is_expired && <span style={{ marginLeft: 6 }}><Badge tone="high">Expired</Badge></span>}
                  </td>
                  <td className="muted">{x.start_date || "—"}</td>
                  <td>
                    {x.expires_at
                      ? (
                        <span className={isPast(x.expires_at) ? "" : "muted"}>
                          {isPast(x.expires_at) ? <Badge tone="high">{x.expires_at}</Badge> : x.expires_at}
                        </span>
                      )
                      : <span className="muted">—</span>}
                  </td>
                  <td className="muted">{x.controls.length || "—"}</td>
                  <td className="muted">{x.risks.length || "—"}</td>
                  <td className="muted">{linkCount(x) || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      {x.status === "pending" && (
                        <>
                          <button className="btn sm" onClick={() => decide(x.id, true)}>
                            <IconCheck width={13} height={13} /> Approve
                          </button>
                          <button className="btn secondary sm" onClick={() => decide(x.id, false)}>Reject</button>
                        </>
                      )}
                      {x.status === "approved" && (
                        <button className="btn secondary sm" onClick={() => close(x.id)}>Close</button>
                      )}
                      <button className="btn secondary sm" onClick={() => setDetailId(detailId === x.id ? null : x.id)}>
                        Details
                      </button>
                      <button className="btn secondary sm" onClick={() => remove(x.id)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconAlert width={24} height={24} /></span>
                      <h3>No exceptions</h3>
                      <p>Request an exception to formally accept a gap with an expiry date.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {detailId && <RecordPanels model="exception" entityId={detailId} />}

      {showForm && (
        <FormModal
          title={editing ? `Edit exception — ${editing.reference}` : "Add item (Exceptions)"}
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            { id: "validity", label: "Validity", content: validityTab },
            { id: "links", label: "Compensating & Links", content: linksTab },
          ]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create exception"}
        />
      )}
    </>
  );
}
