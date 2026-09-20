"use client";

/* Assurance (GET /assurance/home) — internal audit's workspace: engagements in progress,
   audit findings to follow up by age and owner, and the three-lines assurance map. For
   each risk category the map shows what the first line (attestations, risk reviews,
   RCSAs), the second line (independently reviewed control tests, assessed compliance
   clauses) and the third line (audit engagements) have covered, when last, and where the
   gaps are — so the audit plan can go where assurance is thinnest. */

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { useFormat } from "@/lib/format";

type Engagement = { id: string; reference: string; title: string; status: string; audit_type: string; lead_auditor: string; unit: string; planned_start: string | null; planned_end: string | null; overdue: boolean; procedures: number; procedures_pending: number; findings_open: number };
type Bucket = { key: string; label: string; count: number; overdue: number };
type Owner = { owner: string; open: number; overdue: number; oldest_days: number };
type Finding = { id: string; reference: string; title: string; rating: string; status: string; owner: string; engagement_id: string; engagement: string; due_date: string | null; age_days: number; days_overdue: number };
type Line = { state: "covered" | "partial" | "none" | "not_applicable"; covered: number; total: number; pct: number | null; last: string | null; detail: string };
type MapRow = { key: string; label: string; risks: number; controls: number; first_line: Line; second_line: Line; third_line: Line; gaps: string[] };

type AssuranceHome = {
  as_of: string;
  internal_audit_enabled: boolean;
  engagements: Engagement[];
  engagements_overdue: number;
  findings_open: number;
  findings_overdue: number;
  age_buckets: Bucket[];
  by_owner: Owner[];
  overdue_findings: Finding[];
  document_requests_supported: boolean;
  map: MapRow[];
};

const STATE: Record<Line["state"], { text: string; tone: "low" | "medium" | "critical" | "neutral" }> = {
  covered: { text: "Covered", tone: "low" },
  partial: { text: "Partial", tone: "medium" },
  none: { text: "No coverage", tone: "critical" },
  not_applicable: { text: "Not applicable", tone: "neutral" },
};

const words = (s: string) => (s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ") : "—");

function LineCell({ line, when }: { line: Line; when: (d: string | null) => string }) {
  const s = STATE[line.state];
  return (
    <td title={line.detail}>
      <Badge tone={s.tone} asIs>{s.text}</Badge>
      <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
        {line.pct !== null && `${line.covered} of ${line.total} · `}
        {line.last ? `last ${when(line.last)}` : "never"}
      </div>
    </td>
  );
}

export default function AssurancePage() {
  const { formatDate } = useFormat();
  const [data, setData] = useState<AssuranceHome | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiCall<AssuranceHome>("GET", "/assurance/home")
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the assurance workspace"));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!data) return <div className="muted">Loading assurance…</div>;
  const gaps = data.map.reduce((n, r) => n + r.gaps.length, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Assurance</h1>
          <p>
            Engagements in progress, audit findings to follow up, and where the three lines of defence have — and
            have not — given assurance over each risk category, as at {formatDate(data.as_of)}.
          </p>
        </div>
      </div>

      <div className="grid stat-grid">
        <div className="card stat"><div className="stat-top"><span className="n">{data.engagements.length}</span></div><span className="l">Engagements in progress</span></div>
        <div className={`card stat${data.engagements_overdue ? " warn" : ""}`}><div className="stat-top"><span className="n">{data.engagements_overdue}</span></div><span className="l">Past planned end</span></div>
        <div className="card stat"><div className="stat-top"><span className="n">{data.findings_open}</span></div><span className="l">Open findings</span></div>
        <div className={`card stat${data.findings_overdue ? " danger" : ""}`}><div className="stat-top"><span className="n">{data.findings_overdue}</span></div><span className="l">Past agreed date</span></div>
      </div>

      {!data.internal_audit_enabled && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-pad muted" style={{ fontSize: 13 }}>
            The Internal Audit module is switched off for this organisation, so engagements and findings are not shown.
            The assurance map below still covers the first and second lines.
          </div>
        </div>
      )}

      {data.internal_audit_enabled && (
        <>
          <section className="card" style={{ marginBottom: 16 }} aria-labelledby="h-eng">
            <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
              <h3 id="h-eng">Engagements in progress</h3>
              <span className="sub" style={{ flexBasis: "100%" }}>In fieldwork or reporting, and planned engagements starting in the next 30 days.</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Engagement</th><th>Status</th><th>Lead auditor</th><th>Procedures to perform</th><th>Open findings</th><th>Planned end</th></tr></thead>
                <tbody>
                  {data.engagements.length === 0 && <tr><td colSpan={6} className="muted">No engagement is in progress.</td></tr>}
                  {data.engagements.map((e) => (
                    <tr key={e.id}>
                      <td>
                        <Link href={`/internal-audit?id=${e.id}`} className="cell-title">{e.title}</Link>
                        <div className="muted" style={{ fontSize: 12 }}>{[e.reference, e.unit, e.audit_type && e.audit_type !== "internal" ? words(e.audit_type) : ""].filter(Boolean).join(" · ")}</div>
                      </td>
                      <td>{words(e.status)}</td>
                      <td className="muted">{e.lead_auditor || "—"}</td>
                      <td>{e.procedures ? `${e.procedures_pending} of ${e.procedures}` : "None yet"}</td>
                      <td>{e.findings_open}</td>
                      <td style={{ color: e.overdue ? "var(--red)" : undefined, whiteSpace: "nowrap" }}>{formatDate(e.planned_end)}{e.overdue ? " (past)" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16, marginBottom: 16 }}>
            <section className="card" aria-labelledby="h-age">
              <div className="card-head"><h3 id="h-age">Open findings by age</h3></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Raised</th><th>Open</th><th>Past agreed date</th></tr></thead>
                  <tbody>
                    {data.age_buckets.map((b) => (
                      <tr key={b.key}><td>{b.label}</td><td>{b.count}</td><td style={{ color: b.overdue ? "var(--red)" : undefined }}>{b.overdue}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
            <section className="card" aria-labelledby="h-owner">
              <div className="card-head"><h3 id="h-owner">Open findings by owner</h3></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Action owner</th><th>Open</th><th>Past agreed date</th><th>Oldest</th></tr></thead>
                  <tbody>
                    {data.by_owner.length === 0 && <tr><td colSpan={4} className="muted">No open findings.</td></tr>}
                    {data.by_owner.slice(0, 12).map((o) => (
                      <tr key={o.owner}><td>{o.owner}</td><td>{o.open}</td><td style={{ color: o.overdue ? "var(--red)" : undefined }}>{o.overdue}</td><td className="muted">{o.oldest_days} days</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <section className="card" style={{ marginBottom: 16 }} aria-labelledby="h-follow">
            <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
              <h3 id="h-follow">Findings due for validation</h3>
              <span className="sub" style={{ flexBasis: "100%" }}>
                Past their agreed date and still open: confirm the fix and close them, or escalate. Longest overdue first.
              </span>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Finding</th><th>Rating</th><th>Owner</th><th>Engagement</th><th>Agreed date</th></tr></thead>
                <tbody>
                  {data.overdue_findings.length === 0 && <tr><td colSpan={5} className="muted">No finding is past its agreed date.</td></tr>}
                  {data.overdue_findings.map((f) => (
                    <tr key={f.id}>
                      <td><Link href={`/internal-audit?id=${f.engagement_id}`} className="cell-title">{f.title}</Link><div className="muted" style={{ fontSize: 12 }}>{f.reference} · raised {f.age_days} days ago</div></td>
                      <td><Badge tone={(["low", "medium", "high", "critical"].includes(f.rating) ? f.rating : "neutral") as "low"}>{f.rating}</Badge></td>
                      <td className="muted">{f.owner || "Unassigned"}</td>
                      <td className="muted">{f.engagement}</td>
                      <td style={{ color: "var(--red)", whiteSpace: "nowrap" }}>{formatDate(f.due_date)} ({f.days_overdue} days late)</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      <section className="card" style={{ marginBottom: 16 }} aria-labelledby="h-map">
        <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
          <h3 id="h-map">Three-lines assurance map</h3>
          {gaps > 0 && <Badge tone="medium">{`${gaps} gap${gaps === 1 ? "" : "s"}`}</Badge>}
          <span className="sub" style={{ flexBasis: "100%" }}>
            For each risk category: first line — controls attested, risks reviewed or an RCSA completed in the last 12
            months; second line — controls tested and independently reviewed in the last 12 months; third line — an
            audit engagement touching the category in the last 3 years. A line is covered at 80% of the category&apos;s controls.
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Risk category</th><th>Risks / controls</th><th>First line</th><th>Second line</th><th>Third line</th><th>Gaps</th></tr></thead>
            <tbody>
              {data.map.length === 0 && <tr><td colSpan={6} className="muted">No open risks to map.</td></tr>}
              {data.map.map((r) => (
                <tr key={r.key}>
                  <td className="cell-title">{r.label}</td>
                  <td className="muted">{r.risks} / {r.controls}</td>
                  <LineCell line={r.first_line} when={formatDate} />
                  <LineCell line={r.second_line} when={formatDate} />
                  <LineCell line={r.third_line} when={formatDate} />
                  <td style={{ fontSize: 12.5 }}>
                    {r.gaps.length === 0 ? <span className="muted">None</span> : <ul style={{ margin: 0, paddingLeft: 16 }}>{r.gaps.map((g) => <li key={g}>{g}</li>)}</ul>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {!data.document_requests_supported && (
        <p className="muted" style={{ fontSize: 12.5 }}>Document requests (prepared-by-client lists) are not tracked in the platform yet.</p>
      )}
    </>
  );
}
