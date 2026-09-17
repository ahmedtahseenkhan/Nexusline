"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, apiCall, type ApprovalRequest, type Me } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";
import { useFormat } from "@/lib/format";

const TONE: Record<string, "low" | "medium" | "critical" | "neutral"> = {
  approved: "low",
  pending: "medium",
  rejected: "critical",
  cancelled: "neutral",
};

/** Whether `me` raised this request — matched on the maker id, or on the e-mail for
 *  requests that only carry one (the server applies the same rule). */
function raisedBy(a: ApprovalRequest, me: Me | null): boolean {
  if (!me) return false;
  if (a.requested_by && a.requested_by === me.id) return true;
  const maker = (a.requested_by_email || "").trim().toLowerCase();
  return !!maker && maker === (me.email || "").trim().toLowerCase();
}

export default function ApprovalsPage() {
  const { formatDate } = useFormat();
  const [error, setError] = useState<string | null>(null);
  // Who is looking: the maker of a request sees it but cannot decide it.
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);
  const [refreshKey, setRefreshKey] = useState(0);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  // per-row rejection reason (kept in the row, replaces window.prompt)
  const [rejectReason, setRejectReason] = useState<Record<string, string>>({});
  const setReason = (id: string, v: string) => setRejectReason((p) => ({ ...p, [id]: v }));

  // ---- new request form ----
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [approver, setApprover] = useState("");
  const [description, setDescription] = useState("");
  const [required, setRequired] = useState(1);

  const fetchApprovals = useCallback(
    (qs: string) => apiCall<PagedList<ApprovalRequest>>("GET", `/approvals?${qs}`),
    [],
  );

  async function act(fn: Promise<unknown>, okMsg: string) {
    setError(null);
    try {
      await fn;
      reload();
      toast(okMsg);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
      toast(e instanceof Error ? e.message : "Action failed", "error");
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.submitApproval({ title, approver, description, required_approvals: required });
      setShowForm(false);
      setTitle("");
      setApprover("");
      setDescription("");
      setRequired(1);
      reload();
      toast("Submitted for approval");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit");
    }
  }

  async function reject(a: ApprovalRequest) {
    const reason = (rejectReason[a.id] || "").trim();
    if (!reason) {
      toast("Enter a rejection reason first", "error");
      return;
    }
    if (!(await confirmDialog({ title: `Reject ${a.reference}?`, message: reason, danger: true, confirmLabel: "Reject" }))) return;
    await act(api.decideApproval(a.id, false, reason), "Request rejected");
    setReason(a.id, "");
  }

  async function cancel(a: ApprovalRequest) {
    const route = a.approver_role ? " This also cancels the rest of its approval route and returns the record to draft." : "";
    if (!(await confirmDialog({ title: `Cancel ${a.reference}?`, message: `The request is withdrawn without a decision.${route}`, danger: true, confirmLabel: "Cancel request" }))) return;
    await act(api.cancelApproval(a.id), "Request cancelled");
  }

  // -------------------------------------------------------- pending columns
  const pendingColumns: Column<ApprovalRequest>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (a) => <span className="ref">{a.reference}</span> },
    {
      key: "title",
      header: "Title",
      render: (a) => (
        <span className="cell-title">
          {a.title}
          {a.link && a.entity_label && <Link href={a.link} style={{ marginLeft: 8, fontSize: 12 }}>{a.entity_label}</Link>}
        </span>
      ),
    },
    { key: "maker", header: "Maker", render: (a) => <span className="muted">{a.requested_by_email}</span> },
    {
      key: "approver",
      header: "Decided by",
      render: (a) => (
        <div style={{ fontSize: 12.5 }}>
          <span className="muted">{a.approver_role || a.approver || "Any approver"}</span>
          {a.approver_role_gap && (
            <div role="note" style={{ color: "var(--amber)", marginTop: 4, maxWidth: 260 }}>
              {a.approver_role_gap} <Link href="/organization" style={{ fontWeight: 600 }}>Users</Link>
            </div>
          )}
        </div>
      ),
    },
    {
      key: "approvals",
      header: "Approvals",
      render: (a) => (
        <Badge tone={a.approvals_received >= a.required_approvals ? "low" : "medium"}>
          {a.approvals_received}/{a.required_approvals}
        </Badge>
      ),
    },
    {
      key: "due_date",
      header: "Due",
      sortable: true,
      render: (a) => (
        <span className="muted">
          {formatDate(a.due_date)}
          {a.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (a) => (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          {raisedBy(a, me) ? (
            <span className="muted" aria-disabled="true" style={{ fontSize: 12.5 }}>
              You submitted this — an independent checker must decide
            </span>
          ) : a.can_decide === false && a.decide_blocked_reason ? (
            <span className="muted" aria-disabled="true" style={{ fontSize: 12.5, maxWidth: 280 }}>
              {a.decide_blocked_reason}
            </span>
          ) : (
            <>
              <button className="btn sm" onClick={() => act(api.decideApproval(a.id, true), "Decision recorded")} title="An independent checker approves">
                <IconCheck width={13} height={13} /> Approve
              </button>
              <input
                className="input"
                style={{ width: 150 }}
                placeholder="Rejection reason"
                value={rejectReason[a.id] || ""}
                onChange={(e) => setReason(a.id, e.target.value)}
              />
              <button className="btn secondary sm" onClick={() => reject(a)}>Reject</button>
            </>
          )}
          {a.can_cancel && (
            <button
              className="btn secondary sm"
              onClick={() => cancel(a)}
              title={raisedBy(a, me) ? "Withdraw your request" : "Cancel as an administrator"}
            >
              Cancel
            </button>
          )}
        </div>
      ),
    },
  ];

  // -------------------------------------------------------- all-requests columns
  const allColumns: Column<ApprovalRequest>[] = [
    { key: "reference", header: "Ref", sortable: true, render: (a) => <span className="ref">{a.reference}</span> },
    { key: "title", header: "Title", render: (a) => <span className="cell-title">{a.title}</span> },
    { key: "status", header: "Status", sortable: true, render: (a) => <Badge tone={TONE[a.status] || "neutral"}>{a.status}</Badge> },
    { key: "decided_by", header: "Decided by", render: (a) => <span className="muted">{a.decided_by_email || "—"}</span> },
    { key: "comment", header: "Comment", render: (a) => <span className="muted">{a.decision_comment || "—"}</span> },
  ];

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Approvals</h1>
          <p>Submit records for approval and track decisions across the org.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "New request"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={submit}>
          <label className="label">What needs approval?</label>
          <input className="input" value={title} required onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Publish Data Retention Policy" />
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Approver</label>
              <input className="input" value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="e.g. CISO" />
            </div>
            <div style={{ flex: "1 1 280px" }}>
              <label className="label">Notes</label>
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div style={{ flex: "0 0 180px" }}>
              <label className="label">Approvals required</label>
              <select className="input" value={required} onChange={(e) => setRequired(Number(e.target.value))}>
                <option value={1}>1 — four-eyes</option>
                <option value={2}>2 — six-eyes</option>
                <option value={3}>3 checkers</option>
              </select>
            </div>
          </div>
          <p className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
            Maker-checker: the submitter cannot approve their own request; {required} independent
            checker{required !== 1 ? "s" : ""} must approve before it is granted.
          </p>
          <button className="btn" style={{ marginTop: 12 }}>Submit for approval</button>
        </form>
      )}

      <div style={{ marginBottom: 8 }}>
        <h3 style={{ margin: "0 0 8px" }}>Awaiting decision</h3>
      </div>
      <div style={{ marginBottom: 24 }}>
        <DataTable<ApprovalRequest>
          columns={pendingColumns}
          fetcher={fetchApprovals}
          rowKey={(a) => a.id}
          filters={{ status: "pending" }}
          defaultSort={{ by: "created_at", dir: "asc" }}
          searchPlaceholder="Search pending…"
          emptyMessage="Nothing awaiting approval."
          refreshKey={refreshKey}
        />
      </div>

      <div style={{ marginBottom: 8 }}>
        <h3 style={{ margin: "0 0 8px" }}>All requests</h3>
      </div>
      <DataTable<ApprovalRequest>
        columns={allColumns}
        fetcher={fetchApprovals}
        rowKey={(a) => a.id}
        defaultSort={{ by: "created_at", dir: "desc" }}
        searchPlaceholder="Search requests…"
        emptyMessage="No approval requests yet."
        refreshKey={refreshKey}
      />
    </>
  );
}
