"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import { useRecordParam } from "@/lib/useRecordParam";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

// ----------------------------------------------------------------- inline types
type AccessReviewItem = {
  id: string;
  review_id: string;
  username: string;
  display_name: string;
  access: string;
  decision: string;
  comment: string;
  decided_by: string;
  decided_at: string | null;
};

type AccessReview = {
  id: string;
  reference: string;
  name: string;
  description: string;
  status: string;
  reviewer: string;
  system_name: string;
  asset_id: string | null;
  due_date: string | null;
  frequency: string;
  next_review_date: string | null;
  completed_at: string | null;
  total_items: number;
  reviewed_count: number;
  keep_count: number;
  revoke_count: number;
  completion_pct: number;
  is_overdue: boolean;
  asset: { id: string; name: string } | null;
  items: AccessReviewItem[];
  created_at?: string;
};

type AssetRef = { id: string; name: string };

// ----------------------------------------------------------------- helpers
const STATUS_TONE: Record<string, "low" | "medium" | "neutral"> = {
  completed: "low",
  in_progress: "medium",
  draft: "neutral",
};
const DECISION_TONE: Record<string, "low" | "critical" | "neutral"> = {
  keep: "low",
  revoke: "critical",
  pending: "neutral",
};

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const STATUS = opts(["draft", "in_progress", "completed"]);
const FREQUENCY = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);

// ----------------------------------------------------------------- form state
type FormState = {
  name: string;
  description: string;
  system_name: string;
  asset_id: string;
  reviewer: string;
  status: string;
  frequency: string;
  due_date: string;
};

const BLANK: FormState = {
  name: "", description: "", system_name: "", asset_id: "", reviewer: "", status: "draft", frequency: "quarterly", due_date: "",
};

function fromReview(r: AccessReview): FormState {
  return {
    name: r.name,
    description: r.description || "",
    system_name: r.system_name || "",
    asset_id: r.asset_id || "",
    reviewer: r.reviewer || "",
    status: r.status,
    frequency: r.frequency,
    due_date: r.due_date || "",
  };
}

function toPayload(f: FormState): Record<string, unknown> {
  return {
    name: f.name,
    description: f.description,
    system_name: f.system_name,
    asset_id: f.asset_id || null,
    reviewer: f.reviewer,
    status: f.status,
    frequency: f.frequency,
    due_date: f.due_date || null,
  };
}

/* ================================================================ page ===== */
function AccessReviewsInner() {
  const [openId, setOpenId] = useRecordParam("id");
  const [detail, setDetail] = useState<AccessReview | null>(null);
  const [assets, setAssets] = useState<AssetRef[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [editing, setEditing] = useState<AccessReview | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  // Line-item ("account") management inputs (drawer).
  const [newUser, setNewUser] = useState("");
  const [newDisplay, setNewDisplay] = useState("");
  const [newAccess, setNewAccess] = useState("");
  const [busyItem, setBusyItem] = useState<string | null>(null);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchReviews = useCallback((qs: string) => apiCall<PagedList<AccessReview>>("GET", `/access-reviews?${qs}`), []);
  const loadDetail = useCallback((id: string) => {
    apiCall<AccessReview>("GET", `/access-reviews/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (openId) { setNewUser(""); setNewDisplay(""); setNewAccess(""); setBusyItem(null); loadDetail(openId); }
    else setDetail(null);
  }, [openId, loadDetail]);

  useEffect(() => {
    apiCall<PagedList<AssetRef>>("GET", "/assets?limit=200")
      .then((r) => setAssets(r.items.map((a) => ({ id: a.id, name: a.name }))))
      .catch(() => {});
  }, []);

  function openNew() { setEditing(null); setF(BLANK); setError(null); setShowForm(true); }
  function openEdit(r: AccessReview) { setEditing(r); setF(fromReview(r)); setError(null); setShowForm(true); }

  async function save() {
    setError(null); setSaving(true);
    try {
      if (editing) await apiCall<AccessReview>("PATCH", `/access-reviews/${editing.id}`, toPayload(f));
      else await apiCall<AccessReview>("POST", "/access-reviews", toPayload(f));
      setShowForm(false); reload(); if (openId) loadDetail(openId); toast(editing ? "Changes saved" : "Review created");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to save review"); }
    finally { setSaving(false); }
  }

  async function remove(r: AccessReview) {
    if (!(await confirmDialog({ title: `Delete access review ${r.reference}?`, message: "This removes all its line items.", danger: true }))) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/access-reviews/${r.id}`);
      if (openId === r.id) setOpenId(null);
      reload(); toast("Deleted");
    } catch (e) { setError(e instanceof Error ? e.message : "Failed to delete review"); }
  }

  // -------------------------------------------------------------- item actions
  // Each mutation returns the fresh ReviewRead; re-sync the drawer and refetch the table
  // so counts / status / progress stay accurate.
  function applyFresh(fresh: AccessReview) { setDetail(fresh); reload(); }

  async function addItem(e: React.FormEvent) {
    e.preventDefault();
    if (!detail || !newUser.trim()) return;
    setError(null);
    try {
      const fresh = await apiCall<AccessReview>("POST", `/access-reviews/${detail.id}/items`, {
        username: newUser.trim(), display_name: newDisplay.trim(), access: newAccess.trim(),
      });
      applyFresh(fresh); setNewUser(""); setNewDisplay(""); setNewAccess("");
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to add account"); }
  }

  async function decideItem(itemId: string, decision: string) {
    if (!detail) return;
    setError(null); setBusyItem(itemId);
    try {
      const fresh = await apiCall<AccessReview>("PATCH", `/access-reviews/${detail.id}/items/${itemId}`, { decision });
      applyFresh(fresh);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to set decision"); }
    finally { setBusyItem(null); }
  }

  async function removeItem(itemId: string) {
    if (!detail) return;
    setError(null); setBusyItem(itemId);
    try {
      await apiCall<void>("DELETE", `/access-reviews/${detail.id}/items/${itemId}`);
      const fresh = await apiCall<AccessReview>("GET", `/access-reviews/${detail.id}`);
      applyFresh(fresh);
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to remove account"); }
    finally { setBusyItem(null); }
  }

  async function complete() {
    if (!detail) return;
    setError(null);
    try {
      const fresh = await apiCall<AccessReview>("POST", `/access-reviews/${detail.id}/complete`);
      applyFresh(fresh); toast("Review completed");
    } catch (err) { setError(err instanceof Error ? err.message : "Failed to complete review"); }
  }

  const assetOpts: Option[] = useMemo(() => assets.map((a) => ({ value: a.id, label: a.name })), [assets]);

  const columns: Column<AccessReview>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (r) => <span className="ref">{r.reference}</span> },
    { key: "name", header: "Name", sortable: true, render: (r) => <span className="cell-title">{r.name}</span> },
    { key: "system_name", header: "System / Asset", sortable: true, render: (r) => <span className="muted">{r.system_name || (r.asset ? r.asset.name : "—")}</span> },
    { key: "reviewer", header: "Reviewer", render: (r) => <span className="muted">{r.reviewer || "—"}</span> },
    { key: "status", header: "Status", sortable: true, render: (r) => <Badge tone={STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge> },
    { key: "accounts", header: "Accounts", render: (r) => <span className="muted">{r.total_items}</span> },
    { key: "decided", header: "Decided", render: (r) => <div style={{ minWidth: 120 }}><div className="progress"><span style={{ width: `${r.completion_pct}%` }} /></div><span className="muted" style={{ fontSize: 11 }}>{r.reviewed_count}/{r.total_items} · {r.completion_pct}%</span></div> },
    { key: "keeprevoke", header: "Keep / Revoke", render: (r) => <span className="muted"><span style={{ color: "var(--green)" }}>{r.keep_count}</span> / <span style={{ color: "var(--red)" }}>{r.revoke_count}</span></span> },
    { key: "due_date", header: "Due", sortable: true, render: (r) => <span className="muted">{r.due_date || "—"}{r.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}</span> },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEdit(r)}>Edit</button> <button className="btn secondary sm" onClick={() => remove(r)}>Delete</button></div> },
  ];

  // ----------------------------------------------------------------- form tab
  const generalTab = (
    <>
      <Field label="Name" required help="For example: Q4 Admin Access Review, Production AWS Certification.">
        <TextInput value={f.name} onChange={(v) => set("name", v)} placeholder="Q4 Admin Access Review" required />
      </Field>
      <Field label="Description / Scope" help="What systems, account types or entitlements this campaign certifies.">
        <TextArea value={f.description} onChange={(v) => set("description", v)} rows={3} placeholder="Certify all privileged accounts on production systems hold least-privilege access." />
      </Field>
      <div className="field-row">
        <Field label="System" help="Free-text system name being reviewed.">
          <TextInput value={f.system_name} onChange={(v) => set("system_name", v)} placeholder="Production AWS" />
        </Field>
        <Field label="Asset" help="Optionally link the inventory asset under review.">
          <Select value={f.asset_id} onChange={(v) => set("asset_id", v)} options={assetOpts} placeholder="No linked asset" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Reviewer / Certifier">
          <TextInput value={f.reviewer} onChange={(v) => set("reviewer", v)} placeholder="Jane Doe (System Owner)" />
        </Field>
        <Field label="Status">
          <Select value={f.status} onChange={(v) => set("status", v)} options={STATUS} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Review Frequency" help="Drives the next scheduled certification date.">
          <Select value={f.frequency} onChange={(v) => set("frequency", v)} options={FREQUENCY} />
        </Field>
        <Field label="Due Date" help="Target completion date for this campaign.">
          <TextInput type="date" value={f.due_date} onChange={(v) => set("due_date", v)} />
        </Field>
      </div>
      {editing && (
        <div className="field-row">
          <Field label="Reference"><div className="muted">{editing.reference}</div></Field>
          <Field label="Next Review"><div className="muted">{editing.next_review_date || "—"}</div></Field>
          <Field label="Completed"><div className="muted">{editing.completed_at || "—"}</div></Field>
        </div>
      )}
    </>
  );

  // ----------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Access Reviews</h1>
          <p>Periodic access certification campaigns — certify (keep or revoke) each account&apos;s access per system.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <ImportExport resource="access-reviews" label="Access Reviews" onDone={reload} />
          <button className="btn" onClick={openNew}>
            <IconPlus width={16} height={16} /> Add review
          </button>
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <DataTable<AccessReview>
        columns={columns}
        fetcher={fetchReviews}
        rowKey={(r) => r.id}
        onRowClick={(r) => setOpenId(r.id)}
        activeKey={openId}
        searchPlaceholder="Search reviews by name, reference or system…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        emptyMessage="No access reviews yet. Create your first certification campaign to start reviewing account access."
        refreshKey={refreshKey}
      />

      <RecordDrawer
        open={!!openId && !!detail}
        onClose={() => setOpenId(null)}
        title={detail ? detail.reference : "…"}
        subtitle={detail ? `${detail.name}${detail.system_name ? " · " + detail.system_name : ""}` : ""}
        width={820}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEdit(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => remove(detail)}>Delete</button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16, alignItems: "center" }}>
              <Badge tone={STATUS_TONE[detail.status] || "neutral"}>{cap(detail.status)}</Badge>
              {detail.reviewer && <span className="muted" style={{ fontSize: 13 }}>Reviewer: {detail.reviewer}</span>}
              {detail.is_overdue && <Badge tone="high">Overdue</Badge>}
            </div>

            <div className="card" style={{ marginBottom: 14 }}>
              <div className="card-head">
                <h3>Accounts under review</h3>
                <span className="sub">
                  {detail.reviewed_count}/{detail.total_items} certified ·{" "}
                  <span style={{ color: "var(--green)" }}>{detail.keep_count} keep</span> /{" "}
                  <span style={{ color: "var(--red)" }}>{detail.revoke_count} revoke</span>
                </span>
              </div>
              <div className="card-pad">
                <div className="row-between" style={{ marginBottom: 12, alignItems: "center" }}>
                  <div className="progress" style={{ flex: 1, marginRight: 12 }}>
                    <span style={{ width: `${detail.completion_pct}%` }} />
                  </div>
                  {detail.status !== "completed" && detail.total_items > 0 && (
                    <button className="btn secondary sm" type="button" onClick={complete} disabled={detail.reviewed_count < detail.total_items}>
                      <IconCheck width={14} height={14} /> Complete review
                    </button>
                  )}
                </div>

                <form className="field-row" style={{ alignItems: "flex-end", marginBottom: 14 }} onSubmit={addItem}>
                  <Field label="Username"><TextInput value={newUser} onChange={setNewUser} placeholder="jdoe" /></Field>
                  <Field label="Display name"><TextInput value={newDisplay} onChange={setNewDisplay} placeholder="Jane Doe" /></Field>
                  <Field label="Access / roles held"><TextInput value={newAccess} onChange={setNewAccess} placeholder="AdministratorAccess" /></Field>
                  <button className="btn sm" type="submit" disabled={!newUser.trim()} style={{ marginBottom: 2 }}><IconPlus width={14} height={14} /> Add</button>
                </form>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>Account</th><th>Access</th><th>Decision</th><th>Decided by</th><th></th></tr>
                    </thead>
                    <tbody>
                      {detail.items.map((it) => (
                        <tr key={it.id}>
                          <td className="cell-title">{it.username}{it.display_name && <div className="when">{it.display_name}</div>}</td>
                          <td className="muted">{it.access || "—"}</td>
                          <td><Badge tone={DECISION_TONE[it.decision] || "neutral"}>{cap(it.decision)}</Badge></td>
                          <td className="muted">{it.decided_by || "—"}{it.decided_at && <div className="when">{it.decided_at}</div>}</td>
                          <td>
                            <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                              <button className="btn secondary sm" type="button" disabled={busyItem === it.id} onClick={() => decideItem(it.id, "keep")}>Keep</button>
                              <button className="btn secondary sm" type="button" disabled={busyItem === it.id} onClick={() => decideItem(it.id, "revoke")}>Revoke</button>
                              {it.decision !== "pending" && (
                                <button className="btn secondary sm" type="button" disabled={busyItem === it.id} onClick={() => decideItem(it.id, "pending")}>Reset</button>
                              )}
                              <button className="btn secondary sm" type="button" disabled={busyItem === it.id} onClick={() => removeItem(it.id)}>Remove</button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {detail.items.length === 0 && (
                        <tr><td colSpan={5} className="muted" style={{ padding: 16 }}>No accounts added yet. Add the accounts to be certified above.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </>
        )}
      </RecordDrawer>

      {showForm && (
        <FormModal
          title={editing ? `Edit review — ${editing.reference}` : "Add item (Access Reviews)"}
          wide
          tabs={[{ id: "general", label: "General", content: generalTab, required: true }]}
          onClose={() => setShowForm(false)}
          onSave={save}
          saving={saving}
          error={error}
          saveLabel={editing ? "Save changes" : "Create review"}
        />
      )}
    </>
  );
}

export default function AccessReviewsPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <AccessReviewsInner />
    </Suspense>
  );
}
