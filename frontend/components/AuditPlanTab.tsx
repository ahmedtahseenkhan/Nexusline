"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { confirmDialog, toast } from "@/lib/feedback";

/* The annual plan. Its whole point is that the *commitment* is recorded separately from
   what happened, so "did we do what we told the board we would do?" is a number rather
   than an argument. Sign-off goes through the existing approvals inbox, so it inherits
   maker-checker and the audit log rather than inventing a plan-specific approval. */

type PlanItem = {
  id: string;
  title: string;
  auditable_unit_id: string | null;
  auditable_unit_name: string;
  rationale: string;
  planned_quarter: number;
  budgeted_hours: number;
  lead_auditor: string;
  engagement_id: string | null;
};

type Plan = {
  id: string;
  reference: string;
  year: number;
  title: string;
  description: string;
  prepared_by: string;
  budget_hours: number;
  status: string;
  approval_request_id: string | null;
  approved_on: string | null;
  planned_count: number;
  started_count: number;
  coverage_pct: number;
  planned_hours: number;
  items: PlanItem[];
};

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  draft: "neutral",
  submitted: "medium",
  approved: "low",
  active: "info",
  closed: "neutral",
};

const QUARTERS = [1, 2, 3, 4];

export default function AuditPlanTab() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newYear, setNewYear] = useState(new Date().getFullYear());
  const [newTitle, setNewTitle] = useState("");
  const [newBudget, setNewBudget] = useState(0);

  const load = useCallback(() => {
    apiCall<{ items: Plan[] }>("GET", "/audit-plans?limit=50")
      .then((page) => {
        setPlans(page.items);
        setSelectedId((current) => current ?? page.items[0]?.id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load audit plans"));
  }, []);

  useEffect(load, [load]);

  const plan = plans.find((p) => p.id === selectedId) ?? null;

  async function createPlan(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await apiCall<Plan>("POST", "/audit-plans", {
        year: newYear,
        title: newTitle || `Annual audit plan ${newYear}`,
        budget_hours: newBudget,
      });
      setCreating(false);
      setNewTitle("");
      setSelectedId(created.id);
      load();
      toast("Audit plan created");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the plan");
    } finally {
      setBusy(false);
    }
  }

  async function generate() {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiCall<{ added: number; skipped: number; considered: number }>(
        "POST",
        `/audit-plans/${plan.id}/generate-from-universe`,
        { only_due: false, default_hours: 80 },
      );
      toast(
        `Added ${result.added} line(s) from ${result.considered} auditable unit(s)` +
          (result.skipped ? `; ${result.skipped} skipped` : ""),
      );
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate the plan");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!plan) return;
    if (!(await confirmDialog({ title: `Send ${plan.reference} for board approval?`, message: "The plan is locked to the approvals inbox for sign-off.", confirmLabel: "Submit" }))) return;
    setBusy(true);
    setError(null);
    try {
      await apiCall("POST", `/audit-plans/${plan.id}/submit`, {});
      toast("Sent to the approvals inbox for sign-off");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit the plan");
    } finally {
      setBusy(false);
    }
  }

  async function removeItem(item: PlanItem) {
    if (!(await confirmDialog({ title: "Remove this line from the plan?", message: item.title, danger: true, confirmLabel: "Remove" }))) return;
    try {
      await apiCall("DELETE", `/audit-plan-items/${item.id}`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the line");
    }
  }

  return (
    <>
      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ width: 280 }}>
          <label className="label">Plan</label>
          <select
            className="input"
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(e.target.value || null)}
          >
            {plans.length === 0 && <option value="">No plans yet</option>}
            {plans.map((p) => (
              <option key={p.id} value={p.id}>{p.year} — {p.title}</option>
            ))}
          </select>
        </div>
        <button className="btn secondary" type="button" onClick={() => setCreating((v) => !v)}>
          {creating ? "Cancel" : "New plan"}
        </button>
        {plan && (
          <>
            <button className="btn secondary" type="button" onClick={generate} disabled={busy}>
              Generate from audit universe
            </button>
            <button
              className="btn secondary"
              type="button"
              onClick={submit}
              disabled={busy || plan.status === "approved" || plan.items.length === 0}
              title={plan.items.length === 0 ? "An empty plan cannot be submitted" : undefined}
            >
              Submit for board approval
            </button>
          </>
        )}
      </div>

      {creating && (
        <form className="card card-pad" style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={createPlan}>
          <div style={{ width: 120 }}>
            <label className="label">Year</label>
            <input className="input" type="number" min={2000} max={2200} value={newYear} onChange={(e) => setNewYear(Number(e.target.value))} />
          </div>
          <div style={{ flex: "1 1 260px" }}>
            <label className="label">Title</label>
            <input className="input" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} placeholder={`Annual audit plan ${newYear}`} />
          </div>
          <div style={{ width: 160 }}>
            <label className="label">Budget (hours)</label>
            <input className="input" type="number" min={0} value={newBudget} onChange={(e) => setNewBudget(Number(e.target.value))} />
          </div>
          <button className="btn" disabled={busy}>Create</button>
        </form>
      )}

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {!plan && !creating && (
        <div className="card card-pad muted" style={{ fontSize: 13 }}>
          No audit plan yet. Create one, then <b>Generate from audit universe</b> to turn the
          risk ratings and audit frequencies you already maintain into a risk-based draft.
        </div>
      )}

      {plan && (
        <>
          <div className="grid stat-grid" style={{ marginBottom: 16 }}>
            <div className="card stat">
              <div className="stat-top"><span className="n">{plan.planned_count}</span></div>
              <span className="l">Audits planned</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{plan.started_count}</span></div>
              <span className="l">Started</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{plan.coverage_pct}%</span></div>
              <span className="l">Plan-vs-actual coverage</span>
            </div>
            <div className="card stat">
              <div className="stat-top"><span className="n">{plan.planned_hours}</span></div>
              <span className="l">
                Hours planned{plan.budget_hours ? ` of ${plan.budget_hours}` : ""}
              </span>
            </div>
          </div>

          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>{plan.reference} — {plan.title}</h3>
              <span className="sub">
                <Badge tone={STATUS_TONE[plan.status] ?? "neutral"}>{plan.status.replace("_", " ")}</Badge>
                {plan.approval_request_id && " · sign-off raised in the approvals inbox"}
              </span>
            </div>
            {plan.planned_hours > plan.budget_hours && plan.budget_hours > 0 && (
              <div className="card-pad">
                <div className="error" style={{ margin: 0, fontSize: 12.5 }}>
                  The lines add up to {plan.planned_hours} hours against a {plan.budget_hours}-hour
                  budget — either the budget or the plan needs revisiting before sign-off.
                </div>
              </div>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 70 }}>Quarter</th>
                    <th>Audit</th>
                    <th style={{ width: 170 }}>Auditable unit</th>
                    <th style={{ width: 90 }}>Hours</th>
                    <th style={{ width: 150 }}>Lead</th>
                    <th style={{ width: 110 }}>Delivery</th>
                    <th style={{ width: 80 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {QUARTERS.flatMap((quarter) => {
                    const lines = plan.items.filter((i) => i.planned_quarter === quarter);
                    return lines.map((item, index) => (
                      <tr key={item.id}>
                        <td className="ref">{index === 0 ? `Q${quarter}` : ""}</td>
                        <td>
                          <div className="cell-title">{item.title}</div>
                          {item.rationale && (
                            <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{item.rationale}</div>
                          )}
                        </td>
                        <td className="muted">{item.auditable_unit_name || "—"}</td>
                        <td className="muted">{item.budgeted_hours || "—"}</td>
                        <td className="muted">{item.lead_auditor || "—"}</td>
                        <td>
                          {item.engagement_id ? (
                            <Badge tone="low">Started</Badge>
                          ) : (
                            <Badge tone="neutral" plain>Not started</Badge>
                          )}
                        </td>
                        <td>
                          <button className="btn secondary sm" onClick={() => removeItem(item)}>Remove</button>
                        </td>
                      </tr>
                    ));
                  })}
                  {plan.items.length === 0 && (
                    <tr>
                      <td colSpan={7} className="muted" style={{ fontSize: 13 }}>
                        No lines yet — use <b>Generate from audit universe</b> to build a risk-based draft.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </>
  );
}
