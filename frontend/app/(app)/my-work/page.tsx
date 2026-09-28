"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconCheck } from "@/components/icons";
import { confirmDialog, toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";

/* My Work — everything waiting for the signed-in user (GET /my/work), most urgent
   first. Decisions come first (approvals, records in review, tests to review, issue
   validations, due-date extensions), then what they own that is overdue or due soon,
   then policies to acknowledge. Every row opens its record; two rows can be finished
   here: acknowledging a policy and marking a treatment action done. */

type QuickAction = "acknowledge" | "mark_done";

type MyWorkItem = {
  kind: string;
  id: string;
  title: string;
  reference: string;
  subtitle: string;
  due_date: string | null;
  previous_date: string | null;
  overdue: boolean;
  due_soon: boolean;
  link: string;
  entity_type: string;
  entity_id: string | null;
  actions: QuickAction[];
  /** Set when the reader can return the item but not approve it, and why. */
  note?: string;
};

type MyWorkSection = {
  kind: string;
  label: string;
  hint: string;
  count: number;
  /** count is only what one capped read returned — shown as "500+". */
  count_is_floor?: boolean;
  overdue: number;
  items: MyWorkItem[];
  truncated: boolean;
};

type MyWork = {
  as_of: string;
  horizon_days: number;
  total: number;
  overdue: number;
  counts: Record<string, number>;
  sections: MyWorkSection[];
};

/** Kinds that are somebody else's work waiting on the reader's decision. */
const DECISIONS = new Set([
  "approval", "record_review", "test_review", "issue_validation", "due_date_change", "risk_acceptance",
  "vuln_acceptance",
  // Phase 4B: submitted vendor assessments and audit findings whose agreed date has come.
  "assessment_review", "finding_follow_up",
  // Decision 9: the second signature that completes someone else's attestation.
  "attestation_confirm",
]);

function StatusBadge({ item }: { item: MyWorkItem }) {
  if (item.overdue) return <Badge tone="critical">Overdue</Badge>;
  if (item.due_soon) return <Badge tone="medium">Due soon</Badge>;
  if (DECISIONS.has(item.kind)) return <Badge tone="info">Your decision</Badge>;
  return <Badge tone="neutral">Open</Badge>;
}

export default function MyWorkPage() {
  const { formatDate } = useFormat();
  const [data, setData] = useState<MyWork | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    apiCall<MyWork>("GET", "/my/work")
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load your work"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const sections = useMemo(() => (data?.sections || []).filter((s) => s.count > 0), [data]);
  const decisions = useMemo(
    () => sections.filter((s) => DECISIONS.has(s.kind)).reduce((n, s) => n + s.count, 0),
    [sections],
  );
  const dueSoon = useMemo(
    () => sections.reduce((n, s) => n + s.items.filter((i) => i.due_soon).length, 0),
    [sections],
  );

  async function quick(item: MyWorkItem, action: QuickAction) {
    const label = [item.reference, item.title].filter(Boolean).join(" ");
    const ok =
      action === "acknowledge"
        ? await confirmDialog({
            title: `Acknowledge ${item.reference || "this policy"}?`,
            message: `You confirm that you have read and understood "${item.title}". Your acknowledgement is recorded with the date.`,
            confirmLabel: "Acknowledge",
          })
        : await confirmDialog({
            title: "Mark this action done?",
            message: `"${item.title}" will be marked done (100%) today, and its risk's treatment deadline recalculated. Reopen it on the risk if that was a mistake.`,
            confirmLabel: "Mark done",
          });
    if (!ok) return;
    setBusy(item.id);
    try {
      if (action === "acknowledge") {
        await apiCall("POST", `/policies/${item.id}/acknowledge`);
        toast(`Acknowledged ${label}`);
      } else {
        await apiCall("POST", `/my/work/treatment-actions/${item.id}/done`);
        toast(`Marked done: ${item.title}`);
      }
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "That didn't work", "error");
    } finally {
      setBusy(null);
    }
  }

  function dueText(item: MyWorkItem): string {
    if (item.previous_date && item.due_date) return `${formatDate(item.previous_date)} → ${formatDate(item.due_date)}`;
    if (item.previous_date && !item.due_date) return `${formatDate(item.previous_date)} → no date`;
    return item.due_date ? formatDate(item.due_date) : "";
  }

  return (
    <>
      <div className="page-head" style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <h1>My work</h1>
          <p>
            Everything waiting for you, most urgent first: decisions other people are waiting on, then what you
            own that is overdue or due in the next {data?.horizon_days ?? 14} days — including audit engagements and
            findings, access reviews, regulatory changes and returns, regulator notification deadlines, expiring
            exceptions and declarations — then policies to acknowledge.
            Each row opens its record.
          </p>
        </div>
        <button type="button" className="btn secondary sm" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {data && (
        <div className="grid stat-grid">
          <div className="card stat"><div className="stat-top"><span className="n">{data.total}</span></div><span className="l">Waiting for you</span></div>
          <div className={`card stat${data.overdue ? " danger" : ""}`}><div className="stat-top"><span className="n">{data.overdue}</span></div><span className="l">Overdue</span></div>
          <div className="card stat"><div className="stat-top"><span className="n">{decisions}</span></div><span className="l">Your decisions</span></div>
          <div className={`card stat${dueSoon ? " warn" : ""}`}><div className="stat-top"><span className="n">{dueSoon}</span></div><span className="l">Due soon</span></div>
        </div>
      )}

      {sections.length > 1 && (
        <nav aria-label="Jump to a section" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
          {sections.map((s) => (
            <a key={s.kind} href={`#${s.kind}`} className="chip" style={{ textDecoration: "none" }}>
              {s.label} · {s.count}{s.count_is_floor ? "+" : ""}
              {s.overdue > 0 && <span style={{ color: "var(--red)", fontWeight: 650 }}>&nbsp;({s.overdue} overdue)</span>}
            </a>
          ))}
        </nav>
      )}

      {!loading && data && sections.length === 0 && (
        <div className="card">
          <div className="empty">
            <span className="ico"><IconCheck width={24} height={24} /></span>
            <h3>Nothing is waiting for you</h3>
            <p>
              No decisions, nothing you own is overdue or due in the next {data.horizon_days} days, and every policy
              that applies to you is acknowledged. <Link href="/notifications">Notifications</Link> shows the
              organisation&apos;s alerts.
            </p>
          </div>
        </div>
      )}

      {sections.map((s) => (
        <section key={s.kind} id={s.kind} className="card" style={{ marginBottom: 16, scrollMarginTop: 80 }} aria-labelledby={`h-${s.kind}`}>
          <div className="card-head" style={{ flexWrap: "wrap", gap: 8 }}>
            <h3 id={`h-${s.kind}`}>{s.label}</h3>
            <Badge tone="neutral">{`${s.count}${s.count_is_floor ? "+" : ""}`}</Badge>
            {s.overdue > 0 && <Badge tone="critical">{`${s.overdue} overdue`}</Badge>}
            <span className="sub" style={{ flexBasis: "100%" }}>{s.hint}</span>
          </div>
          <div className="card-pad" style={{ paddingTop: 4, paddingBottom: 4 }}>
            {s.items.map((item) => (
              <div className="activity-item" key={`${item.kind}-${item.id}`} style={{ alignItems: "center", flexWrap: "wrap" }}>
                <StatusBadge item={item} />
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontSize: 13.5, fontWeight: 600 }}>
                    {item.link ? <Link href={item.link}>{item.title}</Link> : item.title}
                    {item.reference && <span className="muted" style={{ fontWeight: 500, marginLeft: 6 }}>{item.reference}</span>}
                  </div>
                  {item.subtitle && <div className="when">{item.subtitle}</div>}
                  {item.note && (
                    <div role="note" style={{ fontSize: 12.5, color: "var(--amber)", marginTop: 2 }}>{item.note}</div>
                  )}
                </div>
                {dueText(item) && (
                  <div style={{ fontSize: 12.5, whiteSpace: "nowrap", color: item.overdue ? "var(--red)" : "var(--muted)" }}>
                    {item.previous_date ? "Due date " : "Due "}
                    {dueText(item)}
                  </div>
                )}
                <div style={{ display: "flex", gap: 6 }}>
                  {item.actions.includes("acknowledge") && (
                    <button type="button" className="btn sm" disabled={busy === item.id} onClick={() => quick(item, "acknowledge")}>
                      Acknowledge
                    </button>
                  )}
                  {item.actions.includes("mark_done") && (
                    <button type="button" className="btn sm" disabled={busy === item.id} onClick={() => quick(item, "mark_done")}>
                      Mark done
                    </button>
                  )}
                  {item.link && (
                    <Link href={item.link} className="btn secondary sm" aria-label={`Open ${item.title}`}>
                      Open
                    </Link>
                  )}
                </div>
              </div>
            ))}
            {s.truncated && (
              <div className="muted" style={{ fontSize: 12.5, padding: "8px 0" }}>
                Showing the first {s.items.length} of {s.count}{s.count_is_floor ? "+" : ""}, most urgent first.
              </div>
            )}
          </div>
        </section>
      ))}

      {loading && !data && <div className="muted">Loading your work…</div>}
    </>
  );
}
