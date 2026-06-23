"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus, IconUsers } from "@/components/icons";

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

type Page<T> = { items: T[]; total: number; limit: number; offset: number };
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
  name: "",
  description: "",
  system_name: "",
  asset_id: "",
  reviewer: "",
  status: "draft",
  frequency: "quarterly",
  due_date: "",
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

export default function AccessReviewsPage() {
  const [items, setItems] = useState<AccessReview[]>([]);
  const [assets, setAssets] = useState<AssetRef[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<AccessReview | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [f, setF] = useState<FormState>(BLANK);

  // Line-item ("account") management inputs (active only while editing a review).
  const [newUser, setNewUser] = useState("");
  const [newDisplay, setNewDisplay] = useState("");
  const [newAccess, setNewAccess] = useState("");
  const [busyItem, setBusyItem] = useState<string | null>(null);

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((p) => ({ ...p, [k]: v }));

  async function load() {
    try {
      const r = await apiCall<Page<AccessReview>>("GET", "/access-reviews");
      setItems(r.items);
      // Keep the editing record in sync with the latest server state (counts, items, status).
      if (editing) {
        const fresh = r.items.find((x) => x.id === editing.id);
        if (fresh) setEditing(fresh);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }

  useEffect(() => {
    load();
    apiCall<Page<AssetRef>>("GET", "/assets?limit=200")
      .then((r) => setAssets(r.items.map((a) => ({ id: a.id, name: a.name }))))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function openNew() {
    setEditing(null);
    setF(BLANK);
    setError(null);
    resetItemInputs();
    setShowForm(true);
  }

  function openEdit(r: AccessReview) {
    setEditing(r);
    setF(fromReview(r));
    setError(null);
    resetItemInputs();
    setShowForm(true);
  }

  function resetItemInputs() {
    setNewUser("");
    setNewDisplay("");
    setNewAccess("");
    setBusyItem(null);
  }

  async function save() {
    setError(null);
    setSaving(true);
    try {
      if (editing) await apiCall<AccessReview>("PATCH", `/access-reviews/${editing.id}`, toPayload(f));
      else await apiCall<AccessReview>("POST", "/access-reviews", toPayload(f));
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save review");
    } finally {
      setSaving(false);
    }
  }

  async function remove(r: AccessReview) {
    if (!confirm(`Delete access review ${r.reference}? This removes all its line items.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/access-reviews/${r.id}`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete review");
    }
  }

  // -------------------------------------------------------------- item actions
  // Each mutation returns the fresh ReviewRead; we re-sync both the editing record
  // and the list so counts / status / progress stay accurate without a full reload.
  function applyFresh(fresh: AccessReview) {
    setEditing(fresh);
    setItems((prev) => prev.map((x) => (x.id === fresh.id ? fresh : x)));
    // Adding an item / completing flips status server-side (draft → in_progress →
    // completed); mirror it so a subsequent save doesn't revert it.
    setF((p) => ({ ...p, status: fresh.status }));
  }

  async function addItem(e: React.FormEvent) {
    e.preventDefault();
    if (!editing || !newUser.trim()) return;
    setError(null);
    try {
      const fresh = await apiCall<AccessReview>("POST", `/access-reviews/${editing.id}/items`, {
        username: newUser.trim(),
        display_name: newDisplay.trim(),
        access: newAccess.trim(),
      });
      applyFresh(fresh);
      setNewUser("");
      setNewDisplay("");
      setNewAccess("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add account");
    }
  }

  async function decideItem(itemId: string, decision: string) {
    if (!editing) return;
    setError(null);
    setBusyItem(itemId);
    try {
      const fresh = await apiCall<AccessReview>(
        "PATCH",
        `/access-reviews/${editing.id}/items/${itemId}`,
        { decision },
      );
      applyFresh(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set decision");
    } finally {
      setBusyItem(null);
    }
  }

  async function removeItem(itemId: string) {
    if (!editing) return;
    setError(null);
    setBusyItem(itemId);
    try {
      await apiCall<void>("DELETE", `/access-reviews/${editing.id}/items/${itemId}`);
      const fresh = await apiCall<AccessReview>("GET", `/access-reviews/${editing.id}`);
      applyFresh(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove account");
    } finally {
      setBusyItem(null);
    }
  }

  async function complete() {
    if (!editing) return;
    setError(null);
    try {
      const fresh = await apiCall<AccessReview>("POST", `/access-reviews/${editing.id}/complete`);
      applyFresh(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to complete review");
    }
  }

  const assetOpts: Option[] = useMemo(
    () => assets.map((a) => ({ value: a.id, label: a.name })),
    [assets],
  );

  // ----------------------------------------------------------------- form tabs
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
          <Field label="Reference">
            <div className="muted">{editing.reference}</div>
          </Field>
          <Field label="Next Review">
            <div className="muted">{editing.next_review_date || "—"}</div>
          </Field>
          <Field label="Completed">
            <div className="muted">{editing.completed_at || "—"}</div>
          </Field>
        </div>
      )}
    </>
  );

  const itemsTab = editing ? (
    <>
      <div className="row-between" style={{ marginBottom: 12, alignItems: "flex-end" }}>
        <div>
          <strong>Accounts under review</strong>
          <div className="help" style={{ marginTop: 2 }}>
            {editing.reviewed_count}/{editing.total_items} certified ·{" "}
            <span style={{ color: "var(--green)" }}>{editing.keep_count} keep</span> /{" "}
            <span style={{ color: "var(--red)" }}>{editing.revoke_count} revoke</span>
          </div>
        </div>
        {editing.status !== "completed" && editing.total_items > 0 && (
          <button className="btn secondary sm" type="button" onClick={complete} disabled={editing.reviewed_count < editing.total_items}>
            <IconCheck width={14} height={14} /> Complete review
          </button>
        )}
      </div>

      <div className="progress" style={{ marginBottom: 14 }}>
        <span style={{ width: `${editing.completion_pct}%` }} />
      </div>

      <form
        className="field-row"
        style={{ alignItems: "flex-end", marginBottom: 14 }}
        onSubmit={addItem}
      >
        <Field label="Username">
          <TextInput value={newUser} onChange={setNewUser} placeholder="jdoe" />
        </Field>
        <Field label="Display name">
          <TextInput value={newDisplay} onChange={setNewDisplay} placeholder="Jane Doe" />
        </Field>
        <Field label="Access / roles held">
          <TextInput value={newAccess} onChange={setNewAccess} placeholder="AdministratorAccess" />
        </Field>
        <button className="btn sm" type="submit" disabled={!newUser.trim()} style={{ marginBottom: 2 }}>
          <IconPlus width={14} height={14} /> Add
        </button>
      </form>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Account</th>
              <th>Access</th>
              <th>Decision</th>
              <th>Decided by</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {editing.items.map((it) => (
              <tr key={it.id}>
                <td className="cell-title">
                  {it.username}
                  {it.display_name && <div className="when">{it.display_name}</div>}
                </td>
                <td className="muted">{it.access || "—"}</td>
                <td><Badge tone={DECISION_TONE[it.decision] || "neutral"}>{cap(it.decision)}</Badge></td>
                <td className="muted">
                  {it.decided_by || "—"}
                  {it.decided_at && <div className="when">{it.decided_at}</div>}
                </td>
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
            {editing.items.length === 0 && (
              <tr><td colSpan={5} className="muted" style={{ padding: 16 }}>No accounts added yet. Add the accounts to be certified above.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  ) : (
    <div className="muted" style={{ padding: "8px 0" }}>
      Save the campaign first, then re-open it to add and certify accounts.
    </div>
  );

  // ----------------------------------------------------------------- list
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Access Reviews</h1>
          <p>Periodic access certification campaigns — certify (keep or revoke) each account&apos;s access per system.</p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} /> Add review
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Certification campaigns</h3>
          <span className="sub">{items.length} total · click a row to edit &amp; certify</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Name</th>
                <th>System / Asset</th>
                <th>Reviewer</th>
                <th>Status</th>
                <th>Accounts</th>
                <th>Decided</th>
                <th>Keep / Revoke</th>
                <th>Due</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openEdit(r)}>
                  <td className="ref">{r.reference}</td>
                  <td className="cell-title">{r.name}</td>
                  <td className="muted">{r.system_name || (r.asset ? r.asset.name : "—")}</td>
                  <td className="muted">{r.reviewer || "—"}</td>
                  <td><Badge tone={STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge></td>
                  <td className="muted">{r.total_items}</td>
                  <td style={{ minWidth: 120 }}>
                    <div className="progress"><span style={{ width: `${r.completion_pct}%` }} /></div>
                    <span className="muted" style={{ fontSize: 11 }}>{r.reviewed_count}/{r.total_items} · {r.completion_pct}%</span>
                  </td>
                  <td className="muted">
                    <span style={{ color: "var(--green)" }}>{r.keep_count}</span> / <span style={{ color: "var(--red)" }}>{r.revoke_count}</span>
                  </td>
                  <td className="muted">
                    {r.due_date || "—"}
                    {r.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => remove(r)}>Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconUsers width={24} height={24} /></span>
                      <h3>No access reviews</h3>
                      <p>Create your first certification campaign to start reviewing account access.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {showForm && (
        <FormModal
          title={editing ? `Edit review — ${editing.reference}` : "Add item (Access Reviews)"}
          wide
          tabs={[
            { id: "general", label: "General", content: generalTab, required: true },
            {
              id: "items",
              label: editing ? `Accounts (${editing.total_items})` : "Accounts",
              content: itemsTab,
            },
          ]}
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
