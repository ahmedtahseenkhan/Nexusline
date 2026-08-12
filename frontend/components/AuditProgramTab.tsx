"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { confirmDialog, toast } from "@/lib/feedback";

/* Reusable checklists. The high-value path is generating one from an installed
   framework: the clause list is already loaded, so an ISO 27001 audit programme is a
   click rather than a fortnight of authoring — and every step keeps a link back to the
   clause it tests, which is what makes the finished working papers defensible. */

type Step = {
  id: string;
  title: string;
  procedure: string;
  expected_evidence: string;
  order_index: number;
  requirement_id: string | null;
};

type Program = {
  id: string;
  reference: string;
  name: string;
  description: string;
  category: string;
  framework_id: string | null;
  framework_name: string;
  step_count: number;
  steps: Step[];
};

type FrameworkRow = { id: string; name: string; requirement_count?: number };

export default function AuditProgramTab({ engagements }: { engagements: { id: string; reference: string; title: string }[] }) {
  const [programs, setPrograms] = useState<Program[]>([]);
  const [frameworks, setFrameworks] = useState<FrameworkRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [frameworkId, setFrameworkId] = useState("");
  const [applyTo, setApplyTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    apiCall<{ items: Program[] }>("GET", "/audit-programs?limit=100")
      .then((page) => {
        setPrograms(page.items);
        setSelectedId((current) => current ?? page.items[0]?.id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load programmes"));
    apiCall<{ items: FrameworkRow[] }>("GET", "/frameworks?limit=100")
      .then((page) => setFrameworks(page.items))
      .catch(() => {/* the picker simply stays empty */});
  }, []);

  useEffect(load, [load]);

  const program = programs.find((p) => p.id === selectedId) ?? null;

  async function generate() {
    if (!frameworkId) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiCall<Program>("POST", `/audit-programs/from-framework/${frameworkId}`, {});
      setSelectedId(created.id);
      toast(`Generated ${created.step_count} step(s) from ${created.framework_name || "the framework"}`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not generate the programme");
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!program || !applyTo) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiCall<{ added: number; skipped: number; engagement_reference: string }>(
        "POST",
        `/audit-engagements/${applyTo}/apply-program/${program.id}`,
        {},
      );
      toast(
        `${result.added} working paper(s) added to ${result.engagement_reference}` +
          (result.skipped ? `; ${result.skipped} already there` : ""),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply the programme");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!program) return;
    if (!(await confirmDialog({ title: `Archive programme ${program.reference}?`, message: program.name, danger: true, confirmLabel: "Archive" }))) return;
    try {
      await apiCall("DELETE", `/audit-programs/${program.id}`);
      setSelectedId(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not archive the programme");
    }
  }

  return (
    <>
      <div className="card card-pad" style={{ marginBottom: 16 }}>
        <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, marginTop: 0 }}>
          A programme is the test steps for one kind of audit, written once. Generate one from
          a framework you have installed — the clauses are already loaded — then apply it to an
          engagement, where the steps become ordinary working papers you record results against.
        </p>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ width: 320 }}>
            <label className="label">Generate from framework</label>
            <select className="input" value={frameworkId} onChange={(e) => setFrameworkId(e.target.value)}>
              <option value="">Choose an installed framework…</option>
              {frameworks.map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
          </div>
          <button className="btn" type="button" onClick={generate} disabled={busy || !frameworkId}>
            {busy ? "Working…" : "Generate checklist"}
          </button>
        </div>
        {frameworks.length === 0 && (
          <div className="muted" style={{ fontSize: 12.5, marginTop: 10 }}>
            No frameworks installed yet — add one from Compliance → framework templates first.
          </div>
        )}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ width: 340 }}>
          <label className="label">Programme</label>
          <select className="input" value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value || null)}>
            {programs.length === 0 && <option value="">No programmes yet</option>}
            {programs.map((p) => (
              <option key={p.id} value={p.id}>{p.reference} — {p.name} ({p.step_count})</option>
            ))}
          </select>
        </div>
        {program && (
          <>
            <div style={{ width: 300 }}>
              <label className="label">Apply to engagement</label>
              <select className="input" value={applyTo} onChange={(e) => setApplyTo(e.target.value)}>
                <option value="">Choose an audit…</option>
                {engagements.map((e) => (
                  <option key={e.id} value={e.id}>{e.reference} — {e.title}</option>
                ))}
              </select>
            </div>
            <button className="btn" type="button" onClick={apply} disabled={busy || !applyTo}>
              Apply as working papers
            </button>
            <button className="btn secondary" type="button" onClick={remove} disabled={busy}>
              Archive
            </button>
          </>
        )}
      </div>

      {program && (
        <div className="card">
          <div className="card-head">
            <h3>{program.name}</h3>
            <span className="sub">
              {program.step_count} step(s)
              {program.framework_name && (
                <> · <Badge tone="info">{program.framework_name}</Badge></>
              )}
            </span>
          </div>
          <div className="table-wrap" style={{ maxHeight: 520, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 50 }}>#</th>
                  <th style={{ width: "34%" }}>Step</th>
                  <th>How to test it</th>
                  <th style={{ width: 90 }}>Clause</th>
                </tr>
              </thead>
              <tbody>
                {program.steps.map((step) => (
                  <tr key={step.id}>
                    <td className="ref">{step.order_index}</td>
                    <td className="cell-title">{step.title}</td>
                    <td className="muted" style={{ fontSize: 12.5 }}>{step.procedure || "—"}</td>
                    <td>
                      {step.requirement_id ? (
                        <Badge tone="low">linked</Badge>
                      ) : (
                        <span className="muted" style={{ fontSize: 12 }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
                {program.steps.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted" style={{ fontSize: 13 }}>
                      This programme has no steps yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
