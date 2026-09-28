"use client";

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { confirmDialog, toast } from "@/lib/feedback";
import CustomFieldsPanel from "@/components/CustomFieldsPanel";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea } from "@/components/fields";

/* Reusable checklists. The high-value path is generating one from an installed
   framework: the clause list is already loaded, so an ISO 27001 audit programme is a
   click rather than a fortnight of authoring — and every step keeps a link back to the
   clause it tests, which is what makes the finished working papers defensible.

   Programmes are also written by hand (a branch audit, a cash-in-transit review have no
   framework behind them), and a generated one is tailored step by step before use. */

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

type ProgramForm = { name: string; category: string; description: string };
type StepForm = { title: string; procedure: string; expected_evidence: string; order_index: string };
const BLANK_PROGRAM: ProgramForm = { name: "", category: "", description: "" };
const BLANK_STEP: StepForm = { title: "", procedure: "", expected_evidence: "", order_index: "" };

export default function AuditProgramTab({
  engagements,
  onChanged,
}: {
  engagements: { id: string; reference: string; title: string }[];
  onChanged?: () => void;
}) {
  const [programs, setPrograms] = useState<Program[]>([]);
  const [frameworks, setFrameworks] = useState<FrameworkRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [frameworkId, setFrameworkId] = useState("");
  const [applyTo, setApplyTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // programme dialog (new / edit details)
  const [programOpen, setProgramOpen] = useState(false);
  const [editingProgram, setEditingProgram] = useState(false);
  const [pgf, setPgf] = useState<ProgramForm>(BLANK_PROGRAM);
  const [programError, setProgramError] = useState<string | null>(null);
  const setPG = <K extends keyof ProgramForm>(k: K, v: ProgramForm[K]) => setPgf((p) => ({ ...p, [k]: v }));

  // step dialog (add / edit)
  const [stepOpen, setStepOpen] = useState(false);
  const [editingStep, setEditingStep] = useState<Step | null>(null);
  const [sf, setSf] = useState<StepForm>(BLANK_STEP);
  const [stepError, setStepError] = useState<string | null>(null);
  const setS = <K extends keyof StepForm>(k: K, v: StepForm[K]) => setSf((p) => ({ ...p, [k]: v }));

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
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not apply the programme");
    } finally {
      setBusy(false);
    }
  }

  function openNewProgram() {
    setEditingProgram(false);
    setPgf(BLANK_PROGRAM);
    setProgramError(null);
    setProgramOpen(true);
  }

  function openEditProgram() {
    if (!program) return;
    setEditingProgram(true);
    setPgf({ name: program.name, category: program.category || "", description: program.description || "" });
    setProgramError(null);
    setProgramOpen(true);
  }

  async function saveProgram() {
    setBusy(true);
    setProgramError(null);
    try {
      if (editingProgram && program) {
        await apiCall("PATCH", `/audit-programs/${program.id}`, pgf);
        toast("Programme saved");
      } else {
        const created = await apiCall<Program>("POST", "/audit-programs", pgf);
        setSelectedId(created.id);
        toast("Programme created — add its test steps");
      }
      setProgramOpen(false);
      load();
    } catch (err) {
      setProgramError(err instanceof Error ? err.message : "Could not save the programme");
    } finally {
      setBusy(false);
    }
  }

  function openNewStep() {
    setEditingStep(null);
    setSf(BLANK_STEP);
    setStepError(null);
    setStepOpen(true);
  }

  function openEditStep(step: Step) {
    setEditingStep(step);
    setSf({
      title: step.title,
      procedure: step.procedure || "",
      expected_evidence: step.expected_evidence || "",
      order_index: String(step.order_index),
    });
    setStepError(null);
    setStepOpen(true);
  }

  async function saveStep() {
    if (!program) return;
    setBusy(true);
    setStepError(null);
    const body: Record<string, unknown> = {
      title: sf.title,
      procedure: sf.procedure,
      expected_evidence: sf.expected_evidence,
    };
    // Blank order on a new step appends it; the server numbers it after the last one.
    if (sf.order_index !== "") body.order_index = Number(sf.order_index) || 0;
    try {
      if (editingStep) await apiCall("PATCH", `/audit-program-steps/${editingStep.id}`, body);
      else await apiCall("POST", `/audit-programs/${program.id}/steps`, body);
      setStepOpen(false);
      toast(editingStep ? "Step saved" : "Step added");
      load();
    } catch (err) {
      setStepError(err instanceof Error ? err.message : "Could not save the step");
    } finally {
      setBusy(false);
    }
  }

  async function removeStep(step: Step) {
    if (!(await confirmDialog({ title: `Remove step ${step.order_index}?`, message: step.title, danger: true, confirmLabel: "Remove" }))) return;
    try {
      await apiCall("DELETE", `/audit-program-steps/${step.id}`);
      toast("Step removed");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the step");
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
          <span className="muted" style={{ fontSize: 12.5, alignSelf: "center" }}>or</span>
          <button className="btn secondary" type="button" onClick={openNewProgram} disabled={busy}>
            Write a programme
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
            <button className="btn secondary" type="button" onClick={openEditProgram} disabled={busy}>
              Edit details
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
              {" "}
              <button className="btn sm" type="button" onClick={openNewStep} disabled={busy} style={{ marginLeft: 8 }}>
                Add step
              </button>
            </span>
          </div>
          {program.description && (
            <div className="card-pad muted" style={{ fontSize: 12.5, paddingTop: 0 }}>{program.description}</div>
          )}
          <div className="table-wrap" style={{ maxHeight: 520, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 50 }}>#</th>
                  <th style={{ width: "34%" }}>Step</th>
                  <th>How to test it</th>
                  <th style={{ width: "20%" }}>Evidence to collect</th>
                  <th style={{ width: 70 }}>Clause</th>
                  <th style={{ width: 130 }}></th>
                </tr>
              </thead>
              <tbody>
                {program.steps.map((step) => (
                  <tr key={step.id}>
                    <td className="ref">{step.order_index}</td>
                    <td className="cell-title">{step.title}</td>
                    <td className="muted" style={{ fontSize: 12.5 }}>{step.procedure || "—"}</td>
                    <td className="muted" style={{ fontSize: 12.5 }}>{step.expected_evidence || "—"}</td>
                    <td>
                      {step.requirement_id ? (
                        <Badge tone="low">linked</Badge>
                      ) : (
                        <span className="muted" style={{ fontSize: 12 }}>—</span>
                      )}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <button className="btn secondary sm" type="button" onClick={() => openEditStep(step)} disabled={busy}>Edit</button>
                        <button className="btn secondary sm" type="button" onClick={() => removeStep(step)} disabled={busy}>Remove</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {program.steps.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted" style={{ fontSize: 13 }}>
                      This programme has no steps yet — use <b>Add step</b> to write them.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {program && <CustomFieldsPanel model="audit_program" entityId={program.id} />}

      {programOpen && (
        <FormModal
          title={editingProgram && program ? `Edit programme — ${program.reference}` : "New audit programme"}
          tabs={[{
            id: "programme",
            label: "Programme",
            required: true,
            content: (
              <>
                <Field label="Name" required help="The kind of audit it is for, e.g. Branch operations audit.">
                  <TextInput value={pgf.name} onChange={(v) => setPG("name", v)} placeholder="Branch operations audit" required />
                </Field>
                <Field label="Category" help="Grouping, e.g. Operations, IT, Treasury, Compliance.">
                  <TextInput value={pgf.category} onChange={(v) => setPG("category", v)} placeholder="Operations" />
                </Field>
                <Field label="Description" help="Objective and scope the steps are written for.">
                  <TextArea value={pgf.description} onChange={(v) => setPG("description", v)} rows={3} />
                </Field>
              </>
            ),
          }]}
          onClose={() => setProgramOpen(false)}
          onSave={saveProgram}
          saving={busy}
          error={programError}
          saveLabel={editingProgram ? "Save programme" : "Create programme"}
        />
      )}

      {stepOpen && program && (
        <FormModal
          title={editingStep ? `Edit step ${editingStep.order_index}` : `Add a step to ${program.reference}`}
          tabs={[{
            id: "step",
            label: "Test step",
            required: true,
            content: (
              <>
                <Field label="Step" required help="What is tested, e.g. Cash counts reconcile to the ledger.">
                  <TextInput value={sf.title} onChange={(v) => setS("title", v)} placeholder="Cash counts reconcile to the ledger" required />
                </Field>
                <Field label="How to test it" help="The procedure the auditor follows, including sample size.">
                  <TextArea value={sf.procedure} onChange={(v) => setS("procedure", v)} rows={4} />
                </Field>
                <Field label="Evidence to collect">
                  <TextArea value={sf.expected_evidence} onChange={(v) => setS("expected_evidence", v)} rows={2} />
                </Field>
                <Field label="Order" help="Position in the checklist. Leave blank to add at the end.">
                  <TextInput type="number" value={sf.order_index} onChange={(v) => setS("order_index", v)} />
                </Field>
              </>
            ),
          }]}
          onClose={() => setStepOpen(false)}
          onSave={saveStep}
          saving={busy}
          error={stepError}
          saveLabel={editingStep ? "Save step" : "Add step"}
        />
      )}
    </>
  );
}
