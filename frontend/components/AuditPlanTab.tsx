"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { confirmDialog, toast } from "@/lib/feedback";
import CustomFieldsPanel from "@/components/CustomFieldsPanel";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";

/* The annual plan. Its whole point is that the *commitment* is recorded separately from
   what happened, so "did we do what we told the board we would do?" is a number rather
   than an argument. Sign-off goes through the existing approvals inbox, so it inherits
   maker-checker and the audit log rather than inventing a plan-specific approval.

   Delivery is recorded by linking each line to the engagement that carries it out —
   either an existing audit, or one opened from the line with "Start audit". That link is
   what plan-vs-actual coverage counts. */

type PlanItem = {
  id: string;
  title: string;
  auditable_unit_id: string | null;
  auditable_unit_name: string;
  rationale: string;
  planned_quarter: number;
  planned_month: number | null;
  budgeted_hours: number;
  lead_auditor: string;
  engagement_id: string | null;
  engagement_reference: string;
  engagement_title: string;
  engagement_status: string;
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

type EngagementOption = { id: string; reference: string; title: string };

const STATUS_TONE: Record<string, "low" | "medium" | "high" | "critical" | "neutral" | "info"> = {
  draft: "neutral",
  submitted: "medium",
  approved: "low",
  active: "info",
  closed: "neutral",
};
const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  submitted: "Awaiting approval",
  approved: "Approved",
  active: "In delivery",
  closed: "Closed",
};

const QUARTERS = [1, 2, 3, 4];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const QUARTER_OPTS: Option[] = QUARTERS.map((q) => ({ value: String(q), label: `Q${q}` }));
const quarterOf = (month: number) => Math.floor((month - 1) / 3) + 1;

type LineForm = {
  title: string;
  auditable_unit_id: string;
  rationale: string;
  planned_quarter: string;
  planned_month: string;
  budgeted_hours: string;
  lead_auditor: string;
  engagement_id: string;
};
const BLANK_LINE: LineForm = {
  title: "",
  auditable_unit_id: "",
  rationale: "",
  planned_quarter: "1",
  planned_month: "",
  budgeted_hours: "0",
  lead_auditor: "",
  engagement_id: "",
};
function fromLine(i: PlanItem): LineForm {
  return {
    title: i.title,
    auditable_unit_id: i.auditable_unit_id || "",
    rationale: i.rationale || "",
    planned_quarter: String(i.planned_quarter),
    planned_month: i.planned_month ? String(i.planned_month) : "",
    budgeted_hours: String(i.budgeted_hours || 0),
    lead_auditor: i.lead_auditor || "",
    engagement_id: i.engagement_id || "",
  };
}

type PlanForm = { year: string; title: string; budget_hours: string; prepared_by: string; description: string };

export default function AuditPlanTab({
  units = [],
  engagements = [],
  onChanged,
}: {
  units?: Option[];
  engagements?: EngagementOption[];
  onChanged?: () => void;
}) {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newYear, setNewYear] = useState(new Date().getFullYear());
  const [newTitle, setNewTitle] = useState("");
  const [newBudget, setNewBudget] = useState(0);

  // plan-line dialog
  const [lineOpen, setLineOpen] = useState(false);
  const [editingLine, setEditingLine] = useState<PlanItem | null>(null);
  const [lf, setLf] = useState<LineForm>(BLANK_LINE);
  const [lineError, setLineError] = useState<string | null>(null);
  const setL = <K extends keyof LineForm>(k: K, v: LineForm[K]) => setLf((p) => ({ ...p, [k]: v }));

  // plan-details dialog
  const [planOpen, setPlanOpen] = useState(false);
  const [pf, setPf] = useState<PlanForm>({ year: "", title: "", budget_hours: "0", prepared_by: "", description: "" });
  const [planError, setPlanError] = useState<string | null>(null);
  const setPF = <K extends keyof PlanForm>(k: K, v: PlanForm[K]) => setPf((p) => ({ ...p, [k]: v }));

  const load = useCallback(() => {
    apiCall<{ items: Plan[] }>("GET", "/audit-plans?limit=50")
      .then((page) => {
        setPlans(page.items);
        setSelectedId((current) =>
          current && page.items.some((p) => p.id === current) ? current : page.items[0]?.id ?? null,
        );
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load audit plans"));
  }, []);

  useEffect(load, [load]);

  const plan = plans.find((p) => p.id === selectedId) ?? null;
  // While the board is deciding, the plan it is deciding on cannot change; a closed
  // plan is history. (The server enforces the same rule.)
  const locked = plan ? plan.status === "submitted" || plan.status === "closed" : true;
  const lockReason =
    plan?.status === "submitted"
      ? "Awaiting approval — the plan can be changed again once the approval is decided"
      : plan?.status === "closed"
        ? "This plan is closed"
        : undefined;

  function changed() {
    load();
    onChanged?.();
  }

  async function run(action: () => Promise<unknown>, done: string, failed: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      toast(done);
      changed();
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : failed);
      return false;
    } finally {
      setBusy(false);
    }
  }

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
    if (!(await confirmDialog({ title: `Send ${plan.reference} for board approval?`, message: "The plan is locked while the approval is decided in the Approvals inbox.", confirmLabel: "Submit" }))) return;
    await run(() => apiCall("POST", `/audit-plans/${plan.id}/submit`, {}), "Sent to the approvals inbox for sign-off", "Could not submit the plan");
  }

  async function moveTo(status: "active" | "closed") {
    if (!plan) return;
    const closing = status === "closed";
    if (!(await confirmDialog({
      title: closing ? `Close ${plan.reference}?` : `Put ${plan.reference} into delivery?`,
      message: closing ? "A closed plan can no longer be changed. Its coverage stays on record." : "The approved plan becomes the one the department is delivering.",
      confirmLabel: closing ? "Close plan" : "Start delivery",
    }))) return;
    await run(() => apiCall("PATCH", `/audit-plans/${plan.id}`, { status }), closing ? "Plan closed" : "Plan in delivery", "Could not change the plan status");
  }

  function openPlanDetails() {
    if (!plan) return;
    setPf({
      year: String(plan.year),
      title: plan.title,
      budget_hours: String(plan.budget_hours || 0),
      prepared_by: plan.prepared_by || "",
      description: plan.description || "",
    });
    setPlanError(null);
    setPlanOpen(true);
  }

  async function savePlanDetails() {
    if (!plan) return;
    setBusy(true);
    setPlanError(null);
    try {
      await apiCall("PATCH", `/audit-plans/${plan.id}`, {
        year: Number(pf.year),
        title: pf.title,
        budget_hours: Number(pf.budget_hours) || 0,
        prepared_by: pf.prepared_by,
        description: pf.description,
      });
      setPlanOpen(false);
      toast("Plan saved");
      changed();
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : "Could not save the plan");
    } finally {
      setBusy(false);
    }
  }

  function openNewLine() {
    setEditingLine(null);
    setLf(BLANK_LINE);
    setLineError(null);
    setLineOpen(true);
  }

  function openEditLine(item: PlanItem) {
    setEditingLine(item);
    setLf(fromLine(item));
    setLineError(null);
    setLineOpen(true);
  }

  // The month is the finer commitment: picking one moves the line to its quarter, and
  // picking another quarter drops a month that no longer fits.
  function pickMonth(v: string) {
    setLf((p) => ({ ...p, planned_month: v, planned_quarter: v ? String(quarterOf(Number(v))) : p.planned_quarter }));
  }
  function pickQuarter(v: string) {
    setLf((p) => ({
      ...p,
      planned_quarter: v,
      planned_month: p.planned_month && quarterOf(Number(p.planned_month)) !== Number(v) ? "" : p.planned_month,
    }));
  }

  async function saveLine() {
    if (!plan) return;
    setBusy(true);
    setLineError(null);
    const body: Record<string, unknown> = {
      title: lf.title,
      auditable_unit_id: lf.auditable_unit_id || null,
      rationale: lf.rationale,
      planned_quarter: Number(lf.planned_quarter),
      planned_month: lf.planned_month ? Number(lf.planned_month) : null,
      budgeted_hours: Number(lf.budgeted_hours) || 0,
      lead_auditor: lf.lead_auditor,
    };
    try {
      if (editingLine) {
        // Content and delivery are sent separately so a line whose plan is awaiting
        // approval can still be linked to the audit that delivers it.
        const content = Object.fromEntries(
          Object.entries(body).filter(([k, v]) => (editingLine as unknown as Record<string, unknown>)[k] !== v),
        );
        if (Object.keys(content).length) await apiCall("PATCH", `/audit-plan-items/${editingLine.id}`, content);
        if ((lf.engagement_id || null) !== editingLine.engagement_id) {
          await apiCall("PATCH", `/audit-plan-items/${editingLine.id}`, { engagement_id: lf.engagement_id || null });
        }
      } else {
        const saved = await apiCall<Plan>("POST", `/audit-plans/${plan.id}/items`, body);
        if (lf.engagement_id) {
          // The new line is the one the plan did not have before.
          const known = new Set(plan.items.map((i) => i.id));
          const added = saved.items.find((i) => !known.has(i.id));
          if (added) await apiCall("PATCH", `/audit-plan-items/${added.id}`, { engagement_id: lf.engagement_id });
        }
      }
      setLineOpen(false);
      toast(editingLine ? "Plan line saved" : "Plan line added");
      changed();
    } catch (err) {
      setLineError(err instanceof Error ? err.message : "Could not save the plan line");
      load();
    } finally {
      setBusy(false);
    }
  }

  async function startAudit(item: PlanItem) {
    if (!(await confirmDialog({
      title: `Start the audit for "${item.title}"?`,
      message: "Opens an engagement from this line — title, auditable unit, lead auditor and a fieldwork window from its month or quarter — and links it, so the line counts as delivered.",
      confirmLabel: "Start audit",
    }))) return;
    await run(() => apiCall("POST", `/audit-plan-items/${item.id}/start-engagement`, {}), "Engagement opened and linked to the plan", "Could not start the audit");
  }

  async function unlink(item: PlanItem) {
    if (!(await confirmDialog({ title: "Unlink this engagement from the plan line?", message: `${item.engagement_reference} stays in the register; the line goes back to "not started".`, confirmLabel: "Unlink" }))) return;
    await run(() => apiCall("PATCH", `/audit-plan-items/${item.id}`, { engagement_id: null }), "Unlinked", "Could not unlink the engagement");
  }

  async function removeItem(item: PlanItem) {
    if (!(await confirmDialog({ title: "Remove this line from the plan?", message: item.title, danger: true, confirmLabel: "Remove" }))) return;
    await run(() => apiCall("DELETE", `/audit-plan-items/${item.id}`), "Line removed", "Could not remove the line");
  }

  // Engagements already delivering another line of this plan cannot deliver a second.
  const taken = new Set(plan?.items.filter((i) => i.id !== editingLine?.id && i.engagement_id).map((i) => i.engagement_id as string));
  const engagementOpts: Option[] = engagements
    .filter((e) => !taken.has(e.id))
    .map((e) => ({ value: e.id, label: `${e.reference} — ${e.title}` }));
  if (editingLine?.engagement_id && !engagementOpts.some((o) => o.value === editingLine.engagement_id)) {
    engagementOpts.push({ value: editingLine.engagement_id, label: `${editingLine.engagement_reference} — ${editingLine.engagement_title}` });
  }
  const unitOpts: Option[] =
    editingLine?.auditable_unit_id && !units.some((o) => o.value === editingLine.auditable_unit_id)
      ? [...units, { value: editingLine.auditable_unit_id, label: `${editingLine.auditable_unit_name || "Unit"} (archived)` }]
      : units;
  const monthOpts: Option[] = MONTHS.map((m, i) => ({ value: String(i + 1), label: `${m} (Q${quarterOf(i + 1)})` }));

  const lineContentLocked = !!editingLine && locked;
  const lineTab = (
    <>
      {lineContentLocked && lockReason && (
        <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>
          {lockReason}. Only the engagement delivering this line can be changed now.
        </div>
      )}
      <fieldset disabled={lineContentLocked} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <Field label="Audit" required help="What the department commits to audit, e.g. Payroll controls review.">
          <TextInput value={lf.title} onChange={(v) => setL("title", v)} placeholder="Payroll controls review" required />
        </Field>
        <div className="field-row">
          <Field label="Auditable unit" help="The universe entry this line covers.">
            <Select value={lf.auditable_unit_id} onChange={(v) => setL("auditable_unit_id", v)} options={unitOpts} placeholder="—" />
          </Field>
          <Field label="Lead auditor">
            <TextInput value={lf.lead_auditor} onChange={(v) => setL("lead_auditor", v)} placeholder="Name" />
          </Field>
        </div>
        <div className="field-row">
          <Field label="Quarter" required>
            <Select value={lf.planned_quarter} onChange={pickQuarter} options={QUARTER_OPTS} />
          </Field>
          <Field label="Month" help="Optional. Setting a month places the line in its quarter.">
            <Select value={lf.planned_month} onChange={pickMonth} options={monthOpts} placeholder="— Any month in the quarter —" />
          </Field>
          <Field label="Budgeted hours">
            <TextInput type="number" value={lf.budgeted_hours} onChange={(v) => setL("budgeted_hours", v)} />
          </Field>
        </div>
        <Field label="Rationale" help="Why it made the plan — risk rating, regulatory requirement, management request.">
          <TextArea value={lf.rationale} onChange={(v) => setL("rationale", v)} rows={3} />
        </Field>
      </fieldset>
      <Field label="Delivered by engagement" help="Link the audit that carries this line out. Plan-vs-actual coverage counts linked lines.">
        <Select value={lf.engagement_id} onChange={(v) => setL("engagement_id", v)} options={engagementOpts} placeholder="— Not started —" />
      </Field>
    </>
  );

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
            <button className="btn secondary" type="button" onClick={openNewLine} disabled={busy || locked} title={locked ? lockReason : undefined}>
              Add line
            </button>
            <button className="btn secondary" type="button" onClick={generate} disabled={busy || locked} title={locked ? lockReason : undefined}>
              Generate from audit universe
            </button>
            <button className="btn secondary" type="button" onClick={openPlanDetails} disabled={busy}>
              Plan details
            </button>
            {(plan.status === "draft" || plan.status === "submitted") && (
              <button
                className="btn secondary"
                type="button"
                onClick={submit}
                disabled={busy || plan.items.length === 0}
                title={
                  plan.items.length === 0
                    ? "An empty plan cannot be submitted"
                    : plan.status === "submitted"
                      ? "Only needed if the earlier approval request was withdrawn"
                      : undefined
                }
              >
                {plan.status === "submitted" ? "Re-submit for approval" : "Submit for board approval"}
              </button>
            )}
            {plan.status === "approved" && (
              <button className="btn secondary" type="button" onClick={() => moveTo("active")} disabled={busy}>
                Start delivery
              </button>
            )}
            {(plan.status === "approved" || plan.status === "active") && (
              <button className="btn secondary" type="button" onClick={() => moveTo("closed")} disabled={busy}>
                Close plan
              </button>
            )}
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
                <Badge tone={STATUS_TONE[plan.status] ?? "neutral"}>{STATUS_LABEL[plan.status] ?? plan.status}</Badge>
                {plan.approved_on && ` · approved ${plan.approved_on}`}
                {plan.status === "submitted" && (
                  <> · decided in the <Link href="/approvals">Approvals inbox</Link></>
                )}
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
                    <th style={{ width: 80 }}>When</th>
                    <th>Audit</th>
                    <th style={{ width: 170 }}>Auditable unit</th>
                    <th style={{ width: 70 }}>Hours</th>
                    <th style={{ width: 140 }}>Lead</th>
                    <th style={{ width: 170 }}>Delivery</th>
                    <th style={{ width: 210 }}></th>
                  </tr>
                </thead>
                <tbody>
                  {QUARTERS.flatMap((quarter) => {
                    const lines = plan.items.filter((i) => i.planned_quarter === quarter);
                    return lines.map((item, index) => (
                      <tr key={item.id}>
                        <td className="ref">
                          {index === 0 ? `Q${quarter}` : ""}
                          {item.planned_month ? (
                            <div className="muted" style={{ fontSize: 11.5 }}>{MONTHS[item.planned_month - 1]}</div>
                          ) : null}
                        </td>
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
                            <>
                              <Link href={`/internal-audit?id=${item.engagement_id}`}>
                                <Badge tone="low">{item.engagement_reference || "Started"}</Badge>
                              </Link>
                              {item.engagement_status && (
                                <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{item.engagement_status}</div>
                              )}
                            </>
                          ) : (
                            <Badge tone="neutral" plain>Not started</Badge>
                          )}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                            <button className="btn secondary sm" type="button" onClick={() => openEditLine(item)} disabled={busy}>Edit</button>
                            {item.engagement_id ? (
                              <button className="btn secondary sm" type="button" onClick={() => unlink(item)} disabled={busy || plan.status === "closed"}>Unlink</button>
                            ) : (
                              <button className="btn secondary sm" type="button" onClick={() => startAudit(item)} disabled={busy || plan.status === "closed"}>Start audit</button>
                            )}
                            <button className="btn secondary sm" type="button" onClick={() => removeItem(item)} disabled={busy || locked} title={locked ? lockReason : undefined}>Remove</button>
                          </div>
                        </td>
                      </tr>
                    ));
                  })}
                  {plan.items.length === 0 && (
                    <tr>
                      <td colSpan={7} className="muted" style={{ fontSize: 13 }}>
                        No lines yet — <b>Add line</b>, or <b>Generate from audit universe</b> to build a risk-based draft.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <CustomFieldsPanel model="audit_plan" entityId={plan.id} />
        </>
      )}

      {lineOpen && plan && (
        <FormModal
          title={editingLine ? `Edit plan line — ${editingLine.title}` : `Add a line to ${plan.reference}`}
          tabs={[{ id: "line", label: "Plan line", content: lineTab, required: true }]}
          onClose={() => setLineOpen(false)}
          onSave={saveLine}
          saving={busy}
          error={lineError}
          saveLabel={editingLine ? "Save line" : "Add line"}
        />
      )}

      {planOpen && plan && (
        <FormModal
          title={`Plan details — ${plan.reference}`}
          tabs={[{
            id: "plan",
            label: "Plan",
            required: true,
            content: (
              <fieldset disabled={locked} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
                {locked && lockReason && <div className="muted" style={{ fontSize: 12.5, marginBottom: 12 }}>{lockReason}.</div>}
                <div className="field-row">
                  <Field label="Year" required>
                    <TextInput type="number" value={pf.year} onChange={(v) => setPF("year", v)} required />
                  </Field>
                  <Field label="Budget (hours)">
                    <TextInput type="number" value={pf.budget_hours} onChange={(v) => setPF("budget_hours", v)} />
                  </Field>
                </div>
                <Field label="Title" required>
                  <TextInput value={pf.title} onChange={(v) => setPF("title", v)} required />
                </Field>
                <Field label="Prepared by">
                  <TextInput value={pf.prepared_by} onChange={(v) => setPF("prepared_by", v)} placeholder="Head of Internal Audit" />
                </Field>
                <Field label="Description" help="Basis of the plan — risk assessment, coverage strategy, resourcing.">
                  <TextArea value={pf.description} onChange={(v) => setPF("description", v)} rows={4} />
                </Field>
              </fieldset>
            ),
          }]}
          onClose={() => setPlanOpen(false)}
          onSave={locked ? () => setPlanOpen(false) : savePlanDetails}
          saving={busy}
          error={planError}
          saveLabel={locked ? "Close" : "Save plan"}
        />
      )}
    </>
  );
}
