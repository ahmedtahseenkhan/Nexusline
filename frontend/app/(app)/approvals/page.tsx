"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { api, apiCall, type ApprovalRequest } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

const TONE: Record<string, "low" | "medium" | "critical" | "neutral"> = {
  approved: "low",
  pending: "medium",
  rejected: "critical",
  cancelled: "neutral",
};

export default function ApprovalsPage() {
  const [error, setError] = useState<string | null>(null);
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
          {a.due_date || "—"}
          {a.is_overdue && <span style={{ marginLeft: 6 }}><Badge tone="high">overdue</Badge></span>}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (a) => (
        <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
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
          <button className="btn secondary sm" onClick={() => act(api.cancelApproval(a.id), "Request cancelled")}>Cancel</button>
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
