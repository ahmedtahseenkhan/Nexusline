"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiCall, type RiskCandidate, type RiskCandidatePage } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { useFilterParams, type FilterSpec, type FilterValues } from "@/lib/useFilterParams";
import DataTable, { type Column } from "@/components/DataTable";
import BusinessUnitSelect from "@/components/BusinessUnitSelect";
import LookupSelect from "@/components/LookupSelect";
import UserPicker, { UserName } from "@/components/UserPicker";
import AsyncSelect from "@/components/AsyncSelect";
import FormModal from "@/components/FormModal";
import GenerateRisks, { type GenerateRisksHandle } from "@/components/GenerateRisks";
import { Field, Select, TextArea, type Option } from "@/components/fields";
import { Badge, Severity } from "@/components/badges";

/* The risk candidate queue (product review F-04). Generate risks from assets used to write
   one register risk per asset × scenario pair — a reviewed register reached 1,700 of them.
   Generated risks now wait here as candidates, one per scenario, process and business
   unit, each carrying every asset it covers. A person accepts (the candidate becomes a
   draft risk through the register's normal create path), merges (two candidates are one
   risk) or rejects (with a reason, remembered by the next generation run). */

type Row = RiskCandidate & {
  /** First row of its scenario on this page, and how many rows the scenario has here. */
  _first?: boolean;
  _groupCount?: number;
};

const STATUSES = [
  { value: "pending", label: "Pending" },
  { value: "accepted", label: "Accepted" },
  { value: "rejected", label: "Rejected" },
  { value: "merged", label: "Merged" },
] as const;

const STATUS_TONE: Record<string, "low" | "medium" | "info" | "neutral"> = {
  pending: "medium",
  accepted: "low",
  rejected: "neutral",
  merged: "info",
};

/** Mark the first row of each scenario so the table reads as grouped (rows arrive
 *  ordered by scenario, then exposure). */
function markGroups(items: RiskCandidate[]): Row[] {
  const counts = new Map<string, number>();
  for (const r of items) counts.set(r.scenario_reference, (counts.get(r.scenario_reference) ?? 0) + 1);
  let previous = "";
  return items.map((r) => {
    const first = r.scenario_reference !== previous;
    previous = r.scenario_reference;
    return { ...r, _first: first, _groupCount: counts.get(r.scenario_reference) ?? 1 };
  });
}

const assetHref = (cls: string) => (cls === "it_asset" ? "/it-assets" : "/information-assets");

type Dialog = { kind: "accept" | "merge" | "reject"; rows: Row[]; clear: () => void };

/* The queue's filters live in the URL: the generator links to one run's candidates
   (?run_id=…), and a filtered queue is a shareable link. No status means pending. */
const CANDIDATE_FILTERS = {
  status: ["pending", "accepted", "rejected", "merged", "all"],
  run_id: "string",
  scenario: "string",
  business_unit_id: "string",
} as const satisfies FilterSpec;

function RiskCandidatesPage() {
  const { formatDate } = useFormat();
  const url = useFilterParams(CANDIDATE_FILTERS);
  const status = url.values.status ?? "pending";
  const runId = url.values.run_id ?? "";
  const scenario = url.values.scenario ?? "";
  const unit = url.values.business_unit_id ?? null;
  const setFilter = (key: keyof typeof CANDIDATE_FILTERS & string, value: string | null) =>
    url.update({ [key]: value || undefined } as FilterValues<typeof CANDIDATE_FILTERS>);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [refreshKey, setRefreshKey] = useState(0);
  const [scenarios, setScenarios] = useState<Option[]>([]);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const gen = useRef<GenerateRisksHandle>(null);
  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    apiCall<PagedList<{ reference: string; title: string }>>("GET", "/risk-scenarios?limit=500")
      .then((r) => setScenarios(r.items.map((s) => ({ value: s.reference, label: `${s.reference} — ${s.title.replace("{asset}", "…")}` }))))
      .catch(() => {});
  }, []);

  const fetcher = useCallback(async (qs: string) => {
    const res = await apiCall<RiskCandidatePage>("GET", `/risk-proposals?${qs}`);
    setCounts(res.counts ?? {});
    return { ...res, items: markGroups(res.items) };
  }, []);

  const filters = useMemo(
    () => ({
      status: status === "all" ? undefined : status,
      run_id: runId || undefined,
      scenario: scenario || undefined,
      business_unit_id: unit || undefined,
    }),
    [status, runId, scenario, unit],
  );
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  const columns: Column<Row>[] = [
    {
      key: "scenario", header: "Scenario", locked: true, width: 210,
      render: (r) => r._first ? (
        <div>
          <span className="ref">{r.scenario_reference}</span>
          <div className="muted" style={{ fontSize: 12, marginTop: 2, lineHeight: 1.4 }}>
            {r.scenario_title || "Scenario no longer in the library"}
            {r._groupCount && r._groupCount > 1 ? ` · ${r._groupCount} here` : ""}
          </div>
        </div>
      ) : <span className="muted" aria-label={`Same scenario ${r.scenario_reference}`}>″</span>,
      text: (r) => r.scenario_reference,
    },
    {
      key: "title", header: "Candidate", locked: true,
      render: (r) => (
        <div>
          <span className="cell-title">{r.title}</span>
          <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
            {[r.process_ref?.name, r.business_unit_ref?.name].filter(Boolean).join(" · ") || "No process or unit"}
            {r.category_ref ? ` · ${r.category_ref.label}` : r.scenario_category ? ` · ${r.scenario_category}` : ""}
          </div>
        </div>
      ),
      text: (r) => r.title,
    },
    {
      key: "assets", header: "Assets",
      render: (r) => (
        <div className="chips" onClick={(e) => e.stopPropagation()}>
          {r.assets.slice(0, 5).map((a) => (
            <Link key={a.id} className="chip" href={`${assetHref(a.asset_class)}?id=${a.id}`}>{a.name}</Link>
          ))}
          {r.assets.length > 5 && <span className="chip" title={r.assets.slice(5).map((a) => a.name).join(", ")}>+{r.assets.length - 5}</span>}
          {r.archived_assets > 0 && <span className="muted" style={{ fontSize: 11.5 }}>{r.archived_assets} deleted</span>}
          {r.assets.length === 0 && !r.archived_assets && <span className="muted">—</span>}
        </div>
      ),
      text: (r) => r.assets.map((a) => a.name).join(", "),
    },
    {
      key: "score", header: "Inherent",
      render: (r) => r.inherent_score
        ? <><Severity value={r.inherent_severity} /> <span className="muted">({r.inherent_likelihood}×{r.inherent_impact} = {r.inherent_score})</span></>
        : <span className="muted">—</span>,
      text: (r) => (r.inherent_score ? `${r.inherent_score} ${r.inherent_severity ?? ""}`.trim() : ""),
    },
    {
      key: "controls", header: "Controls",
      render: (r) => (
        <div className="chips" onClick={(e) => e.stopPropagation()}>
          {r.controls.slice(0, 4).map((c) => (
            <Link key={c.id} className="chip" href={`/controls?id=${c.id}`} title={c.name}>{c.reference || c.name}</Link>
          ))}
          {r.controls.length > 4 && <span className="chip">+{r.controls.length - 4}</span>}
          {r.unmapped_references.length > 0 && (
            <span className="muted" style={{ fontSize: 11.5 }} title={`Not in your catalogue: ${r.unmapped_references.join(", ")}`}>
              {r.unmapped_references.length} not in catalogue
            </span>
          )}
          {r.control_references.length === 0 && <span className="muted">—</span>}
        </div>
      ),
      text: (r) => r.control_references.join(", "),
    },
    {
      key: "status", header: "Status",
      render: (r) => (
        <div onClick={(e) => e.stopPropagation()}>
          <Badge tone={STATUS_TONE[r.status] ?? "neutral"}>{r.status[0].toUpperCase() + r.status.slice(1)}</Badge>
          {r.status === "accepted" && r.promoted_risk && (
            <div style={{ fontSize: 12, marginTop: 3 }}>
              <Link href={`/risks?id=${r.promoted_risk.id}`}>{r.promoted_risk.reference}</Link>
              {r.promoted_risk_archived && <span className="muted"> (archived)</span>}
            </div>
          )}
          {r.status === "merged" && r.merged_into && (
            <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>into “{r.merged_into.title}”</div>
          )}
        </div>
      ),
      text: (r) => r.status,
    },
    {
      key: "decision", header: "Decision",
      render: (r) => r.status === "pending" ? <span className="muted">—</span> : (
        <div style={{ fontSize: 12.5 }} title={r.decision_note || undefined}>
          <UserName user={r.decided_by_ref} /> <span className="muted">· {formatDate(r.decided_at)}</span>
          {r.decision_note && <div className="muted" style={{ marginTop: 2, maxWidth: 260, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.decision_note}</div>}
        </div>
      ),
      text: (r) => (r.status === "pending" ? "" : `${r.decided_by_ref?.full_name ?? ""} ${r.decision_note}`.trim()),
    },
    {
      key: "created", header: "Proposed", hidden: true,
      render: (r) => <span className="muted"><UserName user={r.created_by_ref} /> · {formatDate(r.created_at)}</span>,
      text: (r) => formatDate(r.created_at),
    },
    {
      key: "description", header: "Description", hidden: true,
      render: (r) => <span className="muted" style={{ fontSize: 12.5 }}>{r.description || "—"}</span>,
      text: (r) => r.description,
    },
  ];

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Risk candidates</h1>
          <p>
            Risks proposed from the asset register wait here until someone decides. Each candidate is one
            scenario for one process and business unit, carrying every asset it covers; accepted candidates
            become draft risks in the register.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Link className="btn secondary" href="/risks">Risk Register</Link>
          <button className="btn" onClick={() => gen.current?.open()}>Generate from assets…</button>
        </div>
      </div>
      <GenerateRisks ref={gen} label="the asset inventory" onDone={reload} hideButton />

      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
        <div className="seg" role="tablist" aria-label="Candidate status">
          {STATUSES.map((s) => (
            <button key={s.value} className={status === s.value ? "on" : ""} onClick={() => setFilter("status", s.value === "pending" ? null : s.value)} role="tab" aria-selected={status === s.value}>
              {s.label} <span className="muted">{counts[s.value] ?? 0}</span>
            </button>
          ))}
          <button className={status === "all" ? "on" : ""} onClick={() => setFilter("status", "all")} role="tab" aria-selected={status === "all"}>
            All <span className="muted">{total}</span>
          </button>
        </div>
        {runId && (
          <span className="chip">
            One generation run
            <button className="chip-x" onClick={() => setFilter("run_id", null)} aria-label="Show every run">✕</button>
          </span>
        )}
      </div>

      <DataTable<Row>
        toolbarLeft={
          <div className="toolbar-filters">
            <div style={{ width: 260 }}>
              <Select value={scenario} onChange={(v) => setFilter("scenario", v)} options={scenarios} placeholder="All scenarios" />
            </div>
            <div style={{ width: 210 }}>
              <BusinessUnitSelect value={unit} onChange={(id) => setFilter("business_unit_id", id)} placeholder="All business units" />
            </div>
            {(scenario || unit) && (
              <button className="btn secondary sm" onClick={() => url.update({ scenario: undefined, business_unit_id: undefined })}>Clear</button>
            )}
          </div>
        }
        tableKey="risk-proposals"
        columns={columns}
        fetcher={fetcher}
        filters={filters}
        pageSize={100}
        rowKey={(r) => r.id}
        searchPlaceholder="Search candidates by title or scenario…"
        emptyMessage={status === "pending"
          ? "No candidates waiting. Generate risks from the asset register to propose some."
          : "No candidates here."}
        refreshKey={refreshKey}
        bulkActions={(rows, clear) => {
          const pending = rows.every((r) => r.status === "pending");
          if (!pending) {
            return <span className="muted" style={{ fontSize: 12.5 }}>Only pending candidates can be accepted, merged or rejected.</span>;
          }
          return (
            <>
              <button className="btn sm" onClick={() => setDialog({ kind: "accept", rows, clear })}>Accept {rows.length}…</button>
              <button
                className="btn secondary sm"
                disabled={rows.length < 2}
                title={rows.length < 2 ? "Select two or more candidates to merge" : undefined}
                onClick={() => setDialog({ kind: "merge", rows, clear })}
              >
                Merge…
              </button>
              <button className="btn secondary sm" onClick={() => setDialog({ kind: "reject", rows, clear })}>Reject…</button>
            </>
          );
        }}
      />

      {dialog?.kind === "accept" && (
        <AcceptDialog rows={dialog.rows} onClose={() => setDialog(null)} onDone={() => { dialog.clear(); setDialog(null); reload(); }} />
      )}
      {dialog?.kind === "merge" && (
        <MergeDialog rows={dialog.rows} onClose={() => setDialog(null)} onDone={() => { dialog.clear(); setDialog(null); reload(); }} />
      )}
      {dialog?.kind === "reject" && (
        <RejectDialog rows={dialog.rows} onClose={() => setDialog(null)} onDone={() => { dialog.clear(); setDialog(null); reload(); }} />
      )}
    </>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Risks that can be a candidate's parent: enterprise (1) or category (2) level. */
const searchParents = (q: string) =>
  apiCall<PagedList<{ id: string; reference: string; title: string; level: number | null }>>(
    "GET", `/risks?max_level=2&limit=20&search=${encodeURIComponent(q)}`,
  ).then((r) => r.items.map((x) => ({ value: x.id, label: `${x.reference} — ${x.title}`, sub: `Level ${x.level}` })));

function AcceptDialog({ rows, onClose, onDone }: { rows: Row[]; onClose: () => void; onDone: () => void }) {
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [parentId, setParentId] = useState<string | null>(null);
  const [parentLabel, setParentLabel] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const res = await apiCall<{ accepted: number; risks: { id: string; reference: string }[]; errors: { title: string; message: string }[] }>(
        "POST", "/risk-proposals/accept",
        { ids: rows.map((r) => r.id), category_id: categoryId, owner_id: ownerId, parent_id: parentId, note },
      );
      if (res.accepted) {
        const refs = res.risks.slice(0, 6).map((r) => r.reference).join(", ");
        toast(`Accepted ${plural(res.accepted, "candidate")} as draft risks: ${refs}${res.risks.length > 6 ? " …" : ""}`);
      }
      if (res.errors.length) {
        setError(`${plural(res.errors.length, "candidate")} could not be accepted: ` +
          res.errors.slice(0, 4).map((e) => `${e.title || "Candidate"} — ${e.message}`).join("; "));
        if (res.accepted) onDone();
        return;
      }
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not accept the candidates");
    } finally {
      setSaving(false);
    }
  }

  const assets = rows.reduce((n, r) => n + r.assets.length, 0);
  return (
    <FormModal
      title={`Accept ${plural(rows.length, "candidate")}`}
      saveLabel={`Accept ${rows.length}`}
      saving={saving}
      error={error}
      onClose={onClose}
      onSave={save}
      tabs={[{
        id: "accept", label: "Accept", content: (
          <>
            <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
              Each candidate becomes a <b>draft</b> risk in the register — source <i>Generated</i>, scenario level —
              linked to its {plural(assets, "asset")}, its unit and process, the controls its scenario names that
              your catalogue has, and the scenario&apos;s threat and vulnerability. The scores are provisional until
              someone assesses the risk. The choices below apply to every one; leave them blank to set them later.
            </p>
            <Field label="Category" help="Otherwise the scenario's category is matched onto your risk category list.">
              <LookupSelect lookupKey="risk_category" value={categoryId} onChange={(id) => setCategoryId(id)} placeholder="Keep the scenario's category" />
            </Field>
            <Field label="Risk owner">
              <UserPicker value={ownerId} onChange={(id) => setOwnerId(id)} placeholder="Unassigned — search people…" />
            </Field>
            <Field label="Parent risk" help="An enterprise (level 1) or category (level 2) risk these scenarios sit under.">
              <AsyncSelect
                search={searchParents}
                value={parentId}
                selectedLabel={parentLabel}
                onChange={(id, opt) => { setParentId(id); setParentLabel(opt?.label ?? ""); }}
                placeholder="No parent — search risks…"
              />
            </Field>
            <Field label="Note" help="Optional; kept on each candidate and in its activity trail.">
              <TextArea value={note} onChange={setNote} rows={2} placeholder="For example: agreed at the Payments RCSA workshop, 12 Sep" />
            </Field>
          </>
        ),
      }]}
    />
  );
}

function MergeDialog({ rows, onClose, onDone }: { rows: Row[]; onClose: () => void; onDone: () => void }) {
  // Keep the candidate covering the most assets by default.
  const [into, setInto] = useState<string>(() => [...rows].sort((a, b) => b.assets.length - a.assets.length)[0]?.id ?? "");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const res = await apiCall<{ merged: number; survivor: RiskCandidate }>(
        "POST", "/risk-proposals/merge", { ids: rows.map((r) => r.id), into_id: into, note },
      );
      toast(`Merged ${plural(res.merged, "candidate")} into “${res.survivor.title}” — ${plural(res.survivor.assets.length, "asset")}`);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not merge the candidates");
    } finally {
      setSaving(false);
    }
  }

  return (
    <FormModal
      title={`Merge ${plural(rows.length, "candidate")}`}
      saveLabel="Merge"
      saving={saving}
      error={error}
      onClose={onClose}
      onSave={save}
      tabs={[{
        id: "merge", label: "Merge", content: (
          <>
            <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
              Pick the candidate to keep. The others&apos; assets and control references move to it, it takes the
              worst of their scores, and they are marked merged. Later generation runs for their scope add to the
              one you keep.
            </p>
            <div role="radiogroup" aria-label="Candidate to keep" style={{ display: "grid", gap: 8, marginBottom: 14 }}>
              {rows.map((r) => (
                <label key={r.id} style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 8, cursor: "pointer" }}>
                  <input type="radio" name="survivor" checked={into === r.id} onChange={() => setInto(r.id)} style={{ marginTop: 3 }} />
                  <span>
                    <span style={{ fontWeight: 600, fontSize: 13.5 }}>{r.title}</span>
                    <span className="muted" style={{ display: "block", fontSize: 12 }}>
                      {r.scenario_reference} · {plural(r.assets.length, "asset")} · {r.inherent_score ?? "—"}
                      {[r.process_ref?.name, r.business_unit_ref?.name].filter(Boolean).length ? ` · ${[r.process_ref?.name, r.business_unit_ref?.name].filter(Boolean).join(" · ")}` : ""}
                    </span>
                  </span>
                </label>
              ))}
            </div>
            <Field label="Note" help="Optional; recorded on the merged candidates.">
              <TextArea value={note} onChange={setNote} rows={2} placeholder="For example: one ransomware risk for the whole Payments estate" />
            </Field>
          </>
        ),
      }]}
    />
  );
}

function RejectDialog({ rows, onClose, onDone }: { rows: Row[]; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    if (!note.trim()) {
      setError("Say why these candidates are rejected — the reason is shown the next time they are generated.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const res = await apiCall<{ rejected: number; skipped: { message: string }[] }>(
        "POST", "/risk-proposals/reject", { ids: rows.map((r) => r.id), note: note.trim() },
      );
      toast(`Rejected ${plural(res.rejected, "candidate")}` + (res.skipped.length ? ` (${res.skipped.length} already decided)` : ""));
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reject the candidates");
    } finally {
      setSaving(false);
    }
  }

  return (
    <FormModal
      title={`Reject ${plural(rows.length, "candidate")}`}
      saveLabel="Reject"
      saving={saving}
      error={error}
      onClose={onClose}
      onSave={save}
      tabs={[{
        id: "reject", label: "Reject", content: (
          <>
            <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
              Rejected candidates stay in the queue&apos;s history with your reason. When the same scenario comes
              up again for the same process and unit, the generator shows the reason and leaves it unticked.
            </p>
            <Field label="Reason" required>
              <TextArea value={note} onChange={setNote} rows={3} placeholder="For example: covered by R-0012 Enterprise cyber risk; not applicable to test environments" />
            </Field>
          </>
        ),
      }]}
    />
  );
}

export default function RiskCandidatesPageWrapper() {
  return (
    <Suspense fallback={null}>
      <RiskCandidatesPage />
    </Suspense>
  );
}
