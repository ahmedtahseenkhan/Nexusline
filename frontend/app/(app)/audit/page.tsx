"use client";

import { Suspense, useCallback, useState } from "react";
import { apiCall, type AuditEntry } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import DataTable, { type Column } from "@/components/DataTable";
import { Badge } from "@/components/badges";

/* ------------------------------------------------------------- option sets */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// Actions and entity types recorded by the audit service across the platform.
const ACTIONS = [
  "approve", "assess", "attest", "audit", "close", "complete", "create", "crosswalk",
  "decide", "delete", "finding", "ignore", "map_controls", "publish", "request_acceptance",
  "restore", "review", "submit", "test", "update",
];
const ENTITY_TYPES = [
  "access_review", "ai_extraction", "approval", "assessment", "asset", "audit_engagement",
  "audit_finding", "auditable_unit", "authority_matrix", "automated_control_test",
  "awareness_program", "bia_assessment", "capital_calculation", "charity_disbursement",
  "committee", "committee_meeting", "connector", "continuity_plan", "control", "data_breach",
  "declaration_campaign", "dsar", "dual_control_rule", "esg_assessment", "evidence",
  "exception", "framework", "fraud_case", "goal", "icfr_deficiency", "icfr_process",
  "incident", "islamic_product", "issue", "loss_event", "model_inventory",
  "outsourcing_arrangement", "policy", "processing_activity", "project", "questionnaire",
  "rcsa_assessment", "regulatory_change", "regulatory_return", "requirement", "risk",
  "risk_acceptance", "risk_quantification", "role", "sar", "scenario_analysis",
  "screening_case", "shariah_finding", "shariah_review", "shariah_ruling", "user",
  "vendor", "vuln_finding", "whistleblowing_report",
];

/* ================================================================ page ===== */
function AuditInner() {
  const [entityType, setEntityType] = useState("");
  const [action, setAction] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const fetchAudit = useCallback(
    (qs: string) => apiCall<PagedList<AuditEntry>>("GET", `/audit?${qs}`),
    [],
  );

  const filters = {
    entity_type: entityType || undefined,
    action: action || undefined,
    from: from || undefined,
    to: to || undefined,
  };

  const columns: Column<AuditEntry>[] = [
    {
      key: "created_at",
      header: "When",
      sortable: true,
      render: (a) => (
        <span className="muted" style={{ whiteSpace: "nowrap" }}>
          {new Date(a.created_at).toLocaleString()}
        </span>
      ),
    },
    { key: "actor_email", header: "Actor", sortable: true, render: (a) => <span className="muted">{a.actor_email || "—"}</span> },
    { key: "action", header: "Action", sortable: true, render: (a) => <Badge tone="info" plain>{a.action.replace(/_/g, " ")}</Badge> },
    { key: "entity_type", header: "Entity", sortable: true, render: (a) => <span className="muted">{a.entity_type}</span> },
    { key: "summary", header: "Summary", render: (a) => <span>{a.summary}</span> },
  ];

  return (
    <>
      <div className="page-head">
        <h1>Activity Log</h1>
        <p>Immutable audit trail of changes across the platform. Filter by entity, action, actor or date range.</p>
      </div>

      <DataTable<AuditEntry>
        columns={columns}
        fetcher={fetchAudit}
        rowKey={(a) => a.id}
        searchPlaceholder="Search by summary or actor…"
        defaultSort={{ by: "created_at", dir: "desc" }}
        filters={filters}
        toolbarRight={
          <>
            <select className="select" style={{ maxWidth: 180 }} value={entityType} onChange={(e) => setEntityType(e.target.value)} title="Filter by entity type">
              <option value="">All entities</option>
              {ENTITY_TYPES.map((v) => (<option key={v} value={v}>{cap(v)}</option>))}
            </select>
            <select className="select" style={{ maxWidth: 150 }} value={action} onChange={(e) => setAction(e.target.value)} title="Filter by action">
              <option value="">All actions</option>
              {ACTIONS.map((v) => (<option key={v} value={v}>{cap(v)}</option>))}
            </select>
            <input className="input" type="date" style={{ maxWidth: 150 }} value={from} onChange={(e) => setFrom(e.target.value)} title="From date" />
            <input className="input" type="date" style={{ maxWidth: 150 }} value={to} onChange={(e) => setTo(e.target.value)} title="To date" />
          </>
        }
        emptyMessage="No activity matches your filters."
      />
    </>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<div className="muted" style={{ padding: 24 }}>Loading…</div>}>
      <AuditInner />
    </Suspense>
  );
}
