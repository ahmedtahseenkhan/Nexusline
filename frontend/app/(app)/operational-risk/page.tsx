"use client";

import { useEffect, useState } from "react";
import {
  api,
  type RcsaAssessment,
  type RcsaRisk,
  type KeyRiskIndicator,
  type LossEvent,
  type LossSummary,
} from "@/lib/api";
import RecordPanels from "@/components/RecordPanels";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Select, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconCheck, IconPlus } from "@/components/icons";

// ------------------------------------------------------------------ helpers
type Tone = "low" | "medium" | "high" | "critical" | "neutral" | "info";

const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));
const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString());

// ------------------------------------------------------------------ enum lists
const RCSA_STATUS = opts(["planned", "in_progress", "completed"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const KRI_FREQ = opts(["none", "monthly", "quarterly", "semiannual", "annual"]);
const KRI_DIRECTION = opts(["higher_is_worse", "lower_is_worse"]);
const CONTROL_EFF = ["not_assessed", "ineffective", "partially_effective", "effective"];
const LOSS_STATUS = opts(["open", "under_investigation", "recovered", "closed"]);
const BASEL_TYPES = opts([
  "internal_fraud",
  "external_fraud",
  "employment_practices",
  "clients_products_business_practices",
  "damage_to_physical_assets",
  "business_disruption_system_failure",
  "execution_delivery_process_management",
]);

// ------------------------------------------------------------------ tones
const RCSA_STATUS_TONE: Record<string, Tone> = {
  planned: "neutral",
  in_progress: "info",
  completed: "low",
};
const RAG_TONE: Record<string, Tone> = {
  green: "low",
  amber: "medium",
  red: "critical",
  no_data: "neutral",
};
const RAG_LABEL: Record<string, string> = {
  green: "Green",
  amber: "Amber",
  red: "Red",
  no_data: "No data",
};
const EFF_TONE: Record<string, Tone> = {
  effective: "low",
  partially_effective: "medium",
  ineffective: "critical",
  not_assessed: "neutral",
};
const LOSS_STATUS_TONE: Record<string, Tone> = {
  open: "high",
  under_investigation: "info",
  recovered: "low",
  closed: "neutral",
};

function EffBadge({ value }: { value: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <Badge tone={EFF_TONE[value] || "neutral"}>{cap(value)}</Badge>;
}

// ------------------------------------------------------------------ form state
type RcsaForm = {
  title: string;
  business_unit: string;
  process: string;
  assessor: string;
  status: string;
  period: string;
  due_date: string;
  completed_date: string;
  workflow_status: string;
};
const BLANK_RCSA: RcsaForm = {
  title: "",
  business_unit: "",
  process: "",
  assessor: "",
  status: "planned",
  period: "",
  due_date: "",
  completed_date: "",
  workflow_status: "draft",
};
function fromRcsa(r: RcsaAssessment): RcsaForm {
  return {
    title: r.title,
    business_unit: r.business_unit || "",
    process: r.process || "",
    assessor: r.assessor || "",
    status: r.status || "planned",
    period: r.period || "",
    due_date: r.due_date || "",
    completed_date: r.completed_date || "",
    workflow_status: r.workflow_status || "draft",
  };
}
function rcsaPayload(f: RcsaForm): Record<string, unknown> {
  return {
    title: f.title,
    business_unit: f.business_unit,
    process: f.process,
    assessor: f.assessor,
    status: f.status,
    period: f.period,
    due_date: f.due_date || null,
    completed_date: f.completed_date || null,
    workflow_status: f.workflow_status,
  };
}

type RiskDraft = {
  title: string;
  category: string;
  inherent_likelihood: string;
  inherent_impact: string;
  control_description: string;
  control_effectiveness: string;
  residual_likelihood: string;
  residual_impact: string;
  action: string;
  action_owner: string;
  due_date: string;
};
const BLANK_RISK: RiskDraft = {
  title: "",
  category: "",
  inherent_likelihood: "3",
  inherent_impact: "3",
  control_description: "",
  control_effectiveness: "not_assessed",
  residual_likelihood: "2",
  residual_impact: "2",
  action: "",
  action_owner: "",
  due_date: "",
};

type KriForm = {
  name: string;
  category: string;
  business_area: string;
  owner: string;
  unit: string;
  frequency: string;
  direction: string;
  warning_threshold: string;
  limit_threshold: string;
  description: string;
  workflow_status: string;
};
const BLANK_KRI: KriForm = {
  name: "",
  category: "",
  business_area: "",
  owner: "",
  unit: "",
  frequency: "monthly",
  direction: "higher_is_worse",
  warning_threshold: "",
  limit_threshold: "",
  description: "",
  workflow_status: "draft",
};
function fromKri(k: KeyRiskIndicator): KriForm {
  return {
    name: k.name,
    category: k.category || "",
    business_area: k.business_area || "",
    owner: k.owner || "",
    unit: k.unit || "",
    frequency: k.frequency || "monthly",
    direction: k.direction || "higher_is_worse",
    warning_threshold: k.warning_threshold != null ? String(k.warning_threshold) : "",
    limit_threshold: k.limit_threshold != null ? String(k.limit_threshold) : "",
    description: k.description || "",
    workflow_status: k.workflow_status || "draft",
  };
}
function kriPayload(f: KriForm): Record<string, unknown> {
  return {
    name: f.name,
    category: f.category,
    business_area: f.business_area,
    owner: f.owner,
    unit: f.unit,
    frequency: f.frequency,
    direction: f.direction,
    warning_threshold: f.warning_threshold === "" ? null : Number(f.warning_threshold),
    limit_threshold: f.limit_threshold === "" ? null : Number(f.limit_threshold),
    description: f.description,
    workflow_status: f.workflow_status,
  };
}

type MeasureDraft = {
  value: string;
  as_of_date: string;
  notes: string;
};
const BLANK_MEASURE: MeasureDraft = { value: "", as_of_date: "", notes: "" };

type LossForm = {
  title: string;
  basel_event_type: string;
  business_line: string;
  gross_loss: string;
  recovery: string;
  currency: string;
  status: string;
  occurrence_date: string;
  discovery_date: string;
  accounting_date: string;
  root_cause: string;
  action_owner: string;
  workflow_status: string;
};
const BLANK_LOSS: LossForm = {
  title: "",
  basel_event_type: "internal_fraud",
  business_line: "",
  gross_loss: "",
  recovery: "",
  currency: "PKR",
  status: "open",
  occurrence_date: "",
  discovery_date: "",
  accounting_date: "",
  root_cause: "",
  action_owner: "",
  workflow_status: "draft",
};
function fromLoss(l: LossEvent): LossForm {
  return {
    title: l.title,
    basel_event_type: l.basel_event_type || "internal_fraud",
    business_line: l.business_line || "",
    gross_loss: l.gross_loss != null ? String(l.gross_loss) : "",
    recovery: l.recovery != null ? String(l.recovery) : "",
    currency: l.currency || "PKR",
    status: l.status || "open",
    occurrence_date: l.occurrence_date || "",
    discovery_date: l.discovery_date || "",
    accounting_date: l.accounting_date || "",
    root_cause: l.root_cause || "",
    action_owner: l.action_owner || "",
    workflow_status: l.workflow_status || "draft",
  };
}
function lossPayload(f: LossForm): Record<string, unknown> {
  return {
    title: f.title,
    basel_event_type: f.basel_event_type,
    business_line: f.business_line,
    gross_loss: f.gross_loss === "" ? 0 : Number(f.gross_loss),
    recovery: f.recovery === "" ? 0 : Number(f.recovery),
    currency: f.currency,
    status: f.status,
    occurrence_date: f.occurrence_date || null,
    discovery_date: f.discovery_date || null,
    accounting_date: f.accounting_date || null,
    root_cause: f.root_cause,
    action_owner: f.action_owner,
    workflow_status: f.workflow_status,
  };
}

type SectionId = "rcsa" | "kris" | "losses";
const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "rcsa", label: "RCSA" },
  { id: "kris", label: "Key Risk Indicators" },
  { id: "losses", label: "Loss Database" },
];

export default function OperationalRiskPage() {
  const [section, setSection] = useState<SectionId>("rcsa");
  const [error, setError] = useState<string | null>(null);

  const [rcsas, setRcsas] = useState<RcsaAssessment[]>([]);
  const [kris, setKris] = useState<KeyRiskIndicator[]>([]);
  const [losses, setLosses] = useState<LossEvent[]>([]);
  const [summary, setSummary] = useState<LossSummary | null>(null);

  // ---- RCSA dialog + expanded detail ----
  const [editingRcsa, setEditingRcsa] = useState<RcsaAssessment | null>(null);
  const [showRcsaForm, setShowRcsaForm] = useState(false);
  const [savingRcsa, setSavingRcsa] = useState(false);
  const [af, setAf] = useState<RcsaForm>(BLANK_RCSA);
  const setA = <K extends keyof RcsaForm>(k: K, v: RcsaForm[K]) => setAf((p) => ({ ...p, [k]: v }));

  const [openRcsa, setOpenRcsa] = useState<RcsaAssessment | null>(null);
  const [rd, setRd] = useState<RiskDraft>(BLANK_RISK);
  const setRD = <K extends keyof RiskDraft>(k: K, v: RiskDraft[K]) => setRd((p) => ({ ...p, [k]: v }));

  // ---- KRI dialog + expanded detail ----
  const [editingKri, setEditingKri] = useState<KeyRiskIndicator | null>(null);
  const [showKriForm, setShowKriForm] = useState(false);
  const [savingKri, setSavingKri] = useState(false);
  const [kf, setKf] = useState<KriForm>(BLANK_KRI);
  const setK = <K extends keyof KriForm>(k: K, v: KriForm[K]) => setKf((p) => ({ ...p, [k]: v }));

  const [openKri, setOpenKri] = useState<KeyRiskIndicator | null>(null);
  const [md, setMd] = useState<MeasureDraft>(BLANK_MEASURE);
  const setMD = <K extends keyof MeasureDraft>(k: K, v: MeasureDraft[K]) => setMd((p) => ({ ...p, [k]: v }));

  // ---- Loss dialog ----
  const [editingLoss, setEditingLoss] = useState<LossEvent | null>(null);
  const [showLossForm, setShowLossForm] = useState(false);
  const [savingLoss, setSavingLoss] = useState(false);
  const [lf, setLf] = useState<LossForm>(BLANK_LOSS);
  const setL = <K extends keyof LossForm>(k: K, v: LossForm[K]) => setLf((p) => ({ ...p, [k]: v }));

  // ------------------------------------------------------------- loaders
  async function loadRcsas(keepOpen?: string) {
    try {
      const res = await api.rcsaList();
      setRcsas(res.items);
      if (keepOpen) setOpenRcsa(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load RCSA campaigns");
    }
  }
  async function loadKris(keepOpen?: string) {
    try {
      const res = await api.kris();
      setKris(res.items);
      if (keepOpen) setOpenKri(res.items.find((x) => x.id === keepOpen) || null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load KRIs");
    }
  }
  async function loadLosses() {
    try {
      const res = await api.lossEvents();
      setLosses(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load loss events");
    }
  }
  async function loadSummary() {
    try {
      setSummary(await api.lossSummary());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load loss summary");
    }
  }
  async function refreshRcsa(id: string) {
    const r = await api.rcsaGet(id);
    setOpenRcsa(r);
    setRcsas((prev) => prev.map((x) => (x.id === id ? r : x)));
  }

  useEffect(() => {
    loadRcsas();
    loadKris();
    loadLosses();
    loadSummary();
  }, []);

  // ------------------------------------------------------------- RCSA CRUD
  function openNewRcsa() {
    setEditingRcsa(null);
    setAf(BLANK_RCSA);
    setShowRcsaForm(true);
  }
  function openEditRcsa(r: RcsaAssessment) {
    setEditingRcsa(r);
    setAf(fromRcsa(r));
    setShowRcsaForm(true);
  }
  async function saveRcsa() {
    setError(null);
    setSavingRcsa(true);
    try {
      const payload = rcsaPayload(af);
      if (editingRcsa) await api.updateRcsa(editingRcsa.id, payload);
      else await api.createRcsa(payload);
      setShowRcsaForm(false);
      await loadRcsas(openRcsa?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save RCSA");
    } finally {
      setSavingRcsa(false);
    }
  }
  async function removeRcsa(r: RcsaAssessment) {
    if (!window.confirm(`Delete RCSA ${r.reference || r.title}?`)) return;
    setError(null);
    try {
      await api.deleteRcsa(r.id);
      setShowRcsaForm(false);
      if (openRcsa?.id === r.id) setOpenRcsa(null);
      await loadRcsas();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleRcsa(r: RcsaAssessment) {
    setRd(BLANK_RISK);
    setOpenRcsa(openRcsa?.id === r.id ? null : r);
  }

  // ------------------------------------------------------------- RCSA risk lines (inline)
  async function addRisk() {
    if (!openRcsa) return;
    setError(null);
    try {
      await api.addRcsaRisk(openRcsa.id, {
        title: rd.title,
        category: rd.category,
        inherent_likelihood: rd.inherent_likelihood === "" ? 0 : Number(rd.inherent_likelihood),
        inherent_impact: rd.inherent_impact === "" ? 0 : Number(rd.inherent_impact),
        control_description: rd.control_description,
        control_effectiveness: rd.control_effectiveness,
        residual_likelihood: rd.residual_likelihood === "" ? 0 : Number(rd.residual_likelihood),
        residual_impact: rd.residual_impact === "" ? 0 : Number(rd.residual_impact),
        action: rd.action,
        action_owner: rd.action_owner,
        due_date: rd.due_date || null,
      });
      setRd(BLANK_RISK);
      await refreshRcsa(openRcsa.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add risk line");
    }
  }
  async function removeRisk(lineId: string) {
    if (!openRcsa) return;
    if (!window.confirm("Remove this risk line?")) return;
    setError(null);
    try {
      await api.deleteRcsaRisk(lineId);
      await refreshRcsa(openRcsa.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove risk line");
    }
  }

  // ------------------------------------------------------------- KRI CRUD
  function openNewKri() {
    setEditingKri(null);
    setKf(BLANK_KRI);
    setShowKriForm(true);
  }
  function openEditKri(k: KeyRiskIndicator) {
    setEditingKri(k);
    setKf(fromKri(k));
    setShowKriForm(true);
  }
  async function saveKri() {
    setError(null);
    setSavingKri(true);
    try {
      const payload = kriPayload(kf);
      if (editingKri) await api.updateKri(editingKri.id, payload);
      else await api.createKri(payload);
      setShowKriForm(false);
      await loadKris(openKri?.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save KRI");
    } finally {
      setSavingKri(false);
    }
  }
  async function removeKri(k: KeyRiskIndicator) {
    if (!window.confirm(`Delete KRI ${k.reference || k.name}?`)) return;
    setError(null);
    try {
      await api.deleteKri(k.id);
      setShowKriForm(false);
      if (openKri?.id === k.id) setOpenKri(null);
      await loadKris();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }
  function toggleKri(k: KeyRiskIndicator) {
    setMd(BLANK_MEASURE);
    setOpenKri(openKri?.id === k.id ? null : k);
  }
  async function addMeasurement() {
    if (!openKri) return;
    setError(null);
    try {
      await api.addKriMeasurement(openKri.id, {
        value: md.value === "" ? 0 : Number(md.value),
        as_of_date: md.as_of_date || null,
        notes: md.notes,
      });
      setMd(BLANK_MEASURE);
      await loadKris(openKri.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to record measurement");
    }
  }

  // ------------------------------------------------------------- Loss CRUD
  function openNewLoss() {
    setEditingLoss(null);
    setLf(BLANK_LOSS);
    setShowLossForm(true);
  }
  function openEditLoss(l: LossEvent) {
    setEditingLoss(l);
    setLf(fromLoss(l));
    setShowLossForm(true);
  }
  async function saveLoss() {
    setError(null);
    setSavingLoss(true);
    try {
      const payload = lossPayload(lf);
      if (editingLoss) await api.updateLossEvent(editingLoss.id, payload);
      else await api.createLossEvent(payload);
      setShowLossForm(false);
      await loadLosses();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save loss event");
    } finally {
      setSavingLoss(false);
    }
  }
  async function removeLoss(l: LossEvent) {
    if (!window.confirm(`Delete loss event ${l.reference || l.title}?`)) return;
    setError(null);
    try {
      await api.deleteLossEvent(l.id);
      setShowLossForm(false);
      await loadLosses();
      await loadSummary();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
  }

  // ------------------------------------------------------------- RCSA form tabs
  const rcsaGeneral = (
    <>
      <Field label="Title" required help="For example: FY26 Payments operations RCSA.">
        <TextInput value={af.title} onChange={(v) => setA("title", v)} placeholder="RCSA title" required />
      </Field>
      <div className="field-row">
        <Field label="Business unit" help="The unit or department being assessed.">
          <TextInput value={af.business_unit} onChange={(v) => setA("business_unit", v)} placeholder="Payments" />
        </Field>
        <Field label="Process" help="The process under assessment.">
          <TextInput value={af.process} onChange={(v) => setA("process", v)} placeholder="Wire transfers" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Assessor">
          <TextInput value={af.assessor} onChange={(v) => setA("assessor", v)} placeholder="Name" />
        </Field>
        <Field label="Status">
          <Select value={af.status} onChange={(v) => setA("status", v)} options={RCSA_STATUS} />
        </Field>
      </div>
      <Field label="Period" help="Assessment period, e.g. FY26 or Q1 2026.">
        <TextInput value={af.period} onChange={(v) => setA("period", v)} placeholder="FY26" />
      </Field>
    </>
  );
  const rcsaTiming = (
    <>
      <div className="field-row">
        <Field label="Due date" help="Target completion — drives the overdue flag.">
          <TextInput type="date" value={af.due_date} onChange={(v) => setA("due_date", v)} />
        </Field>
        <Field label="Completed date">
          <TextInput type="date" value={af.completed_date} onChange={(v) => setA("completed_date", v)} />
        </Field>
      </div>
      <Field label="Workflow" help="Approval lifecycle for this campaign record.">
        <Select value={af.workflow_status} onChange={(v) => setA("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- KRI form tabs
  const kriGeneral = (
    <>
      <Field label="Name" required help="For example: Failed wire transfers rate.">
        <TextInput value={kf.name} onChange={(v) => setK("name", v)} placeholder="KRI name" required />
      </Field>
      <div className="field-row">
        <Field label="Category">
          <TextInput value={kf.category} onChange={(v) => setK("category", v)} placeholder="Operational" />
        </Field>
        <Field label="Business area">
          <TextInput value={kf.business_area} onChange={(v) => setK("business_area", v)} placeholder="Payments" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Owner">
          <TextInput value={kf.owner} onChange={(v) => setK("owner", v)} placeholder="Risk owner" />
        </Field>
        <Field label="Unit" help='Unit of measure, e.g. "%", "count", "PKR".'>
          <TextInput value={kf.unit} onChange={(v) => setK("unit", v)} placeholder="%" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Frequency" help="How often the indicator is measured.">
          <Select value={kf.frequency} onChange={(v) => setK("frequency", v)} options={KRI_FREQ} />
        </Field>
        <Field label="Direction" help="Which way of the threshold is a breach.">
          <Select value={kf.direction} onChange={(v) => setK("direction", v)} options={KRI_DIRECTION} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Warning threshold" help="Amber level.">
          <TextInput type="number" value={kf.warning_threshold} onChange={(v) => setK("warning_threshold", v)} placeholder="0" />
        </Field>
        <Field label="Limit threshold" help="Red / breach level.">
          <TextInput type="number" value={kf.limit_threshold} onChange={(v) => setK("limit_threshold", v)} placeholder="0" />
        </Field>
      </div>
      <Field label="Description">
        <TextArea value={kf.description} onChange={(v) => setK("description", v)} rows={3} placeholder="What this indicator measures." />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this KRI record.">
        <Select value={kf.workflow_status} onChange={(v) => setK("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- Loss form tabs
  const lossGeneral = (
    <>
      <Field label="Title" required help="For example: Duplicate vendor payment released.">
        <TextInput value={lf.title} onChange={(v) => setL("title", v)} placeholder="Loss event title" required />
      </Field>
      <div className="field-row">
        <Field label="Basel event type" help="Basel II level-1 loss category.">
          <Select value={lf.basel_event_type} onChange={(v) => setL("basel_event_type", v)} options={BASEL_TYPES} />
        </Field>
        <Field label="Business line">
          <TextInput value={lf.business_line} onChange={(v) => setL("business_line", v)} placeholder="Retail banking" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Gross loss" help="Total loss before recoveries.">
          <TextInput type="number" value={lf.gross_loss} onChange={(v) => setL("gross_loss", v)} placeholder="0" />
        </Field>
        <Field label="Recovery" help="Amount recovered.">
          <TextInput type="number" value={lf.recovery} onChange={(v) => setL("recovery", v)} placeholder="0" />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Currency">
          <TextInput value={lf.currency} onChange={(v) => setL("currency", v)} placeholder="PKR" />
        </Field>
        <Field label="Status">
          <Select value={lf.status} onChange={(v) => setL("status", v)} options={LOSS_STATUS} />
        </Field>
      </div>
    </>
  );
  const lossDetails = (
    <>
      <div className="field-row">
        <Field label="Occurrence date" help="When the loss occurred.">
          <TextInput type="date" value={lf.occurrence_date} onChange={(v) => setL("occurrence_date", v)} />
        </Field>
        <Field label="Discovery date">
          <TextInput type="date" value={lf.discovery_date} onChange={(v) => setL("discovery_date", v)} />
        </Field>
      </div>
      <Field label="Accounting date" help="When the loss hit the books.">
        <TextInput type="date" value={lf.accounting_date} onChange={(v) => setL("accounting_date", v)} />
      </Field>
      <Field label="Root cause">
        <TextArea value={lf.root_cause} onChange={(v) => setL("root_cause", v)} rows={3} placeholder="Underlying cause of the loss." />
      </Field>
      <Field label="Action owner">
        <TextInput value={lf.action_owner} onChange={(v) => setL("action_owner", v)} placeholder="Owner" />
      </Field>
      <Field label="Workflow" help="Approval lifecycle for this loss record.">
        <Select value={lf.workflow_status} onChange={(v) => setL("workflow_status", v)} options={WORKFLOW} />
      </Field>
    </>
  );

  // ------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Operational Risk</h1>
          <p>Risk &amp; control self-assessments, key risk indicators with RAG monitoring, and a Basel operational loss database.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {section === "rcsa" && (
            <button className="btn" onClick={openNewRcsa}>
              <IconPlus width={16} height={16} /> New RCSA
            </button>
          )}
          {section === "kris" && (
            <button className="btn" onClick={openNewKri}>
              <IconPlus width={16} height={16} /> New KRI
            </button>
          )}
          {section === "losses" && (
            <button className="btn" onClick={openNewLoss}>
              <IconPlus width={16} height={16} /> New loss event
            </button>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {SECTIONS.map((s) => (
          <button
            key={s.id}
            className={`btn${section === s.id ? "" : " secondary"}`}
            onClick={() => setSection(s.id)}
            type="button"
          >
            {s.label}
          </button>
        ))}
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {/* ============================================= RCSA */}
      {section === "rcsa" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>Risk &amp; Control Self-Assessments</h3>
              <span className="sub">{rcsas.length} total · click a row to manage risk &amp; control lines</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Title</th>
                    <th>Business unit</th>
                    <th>Status</th>
                    <th>Risks</th>
                    <th>Due</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {rcsas.map((r) => (
                    <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => toggleRcsa(r)}>
                      <td className="ref">{r.reference || "—"}</td>
                      <td className="cell-title">{r.title}</td>
                      <td className="muted">{r.business_unit || "—"}</td>
                      <td><Badge tone={RCSA_STATUS_TONE[r.status] || "neutral"}>{cap(r.status)}</Badge></td>
                      <td className="muted">{r.risk_count}</td>
                      <td>
                        {r.is_overdue ? (
                          <Badge tone="high">Overdue</Badge>
                        ) : (
                          <span className="muted">{r.due_date || "—"}</span>
                        )}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleRcsa(r)}>
                            {openRcsa?.id === r.id ? "Hide" : "Manage"}
                          </button>
                          <button className="btn secondary sm" onClick={() => removeRcsa(r)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {rcsas.length === 0 && (
                    <tr>
                      <td colSpan={7}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No RCSA campaigns</h3>
                          <p>Launch a risk &amp; control self-assessment to score inherent and residual risk.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openRcsa && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openRcsa.reference} — {openRcsa.title}</h3>
                    <span className="sub">
                      {cap(openRcsa.status)} · {openRcsa.business_unit || "no unit"}
                      {openRcsa.assessor ? " · assessor " + openRcsa.assessor : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button className="btn secondary sm" onClick={() => openEditRcsa(openRcsa)}>Edit</button>
                    <button className="btn secondary sm" onClick={() => removeRcsa(openRcsa)}>Delete</button>
                  </div>
                </div>

                <div className="card-pad">
                  <strong>Risk &amp; control lines</strong>
                  <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                    Inherent risk, control effectiveness, and residual risk for each assessed item.
                  </p>
                  <form
                    style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                    onSubmit={(ev) => { ev.preventDefault(); addRisk(); }}
                  >
                    <div style={{ flex: "1 1 180px" }}>
                      <label className="label">Title</label>
                      <input className="input" value={rd.title} onChange={(ev) => setRD("title", ev.target.value)} placeholder="Risk title" required />
                    </div>
                    <div style={{ width: 130 }}>
                      <label className="label">Category</label>
                      <input className="input" value={rd.category} onChange={(ev) => setRD("category", ev.target.value)} placeholder="Category" />
                    </div>
                    <div style={{ width: 90 }}>
                      <label className="label">Inh. L</label>
                      <input className="input" type="number" min={1} max={5} value={rd.inherent_likelihood} onChange={(ev) => setRD("inherent_likelihood", ev.target.value)} />
                    </div>
                    <div style={{ width: 90 }}>
                      <label className="label">Inh. I</label>
                      <input className="input" type="number" min={1} max={5} value={rd.inherent_impact} onChange={(ev) => setRD("inherent_impact", ev.target.value)} />
                    </div>
                    <div style={{ flex: "1 1 180px" }}>
                      <label className="label">Control description</label>
                      <input className="input" value={rd.control_description} onChange={(ev) => setRD("control_description", ev.target.value)} placeholder="Mitigating control" />
                    </div>
                    <div style={{ width: 170 }}>
                      <label className="label">Control effectiveness</label>
                      <select className="select" value={rd.control_effectiveness} onChange={(ev) => setRD("control_effectiveness", ev.target.value)}>
                        {CONTROL_EFF.map((c) => (<option key={c} value={c}>{cap(c)}</option>))}
                      </select>
                    </div>
                    <div style={{ width: 90 }}>
                      <label className="label">Res. L</label>
                      <input className="input" type="number" min={1} max={5} value={rd.residual_likelihood} onChange={(ev) => setRD("residual_likelihood", ev.target.value)} />
                    </div>
                    <div style={{ width: 90 }}>
                      <label className="label">Res. I</label>
                      <input className="input" type="number" min={1} max={5} value={rd.residual_impact} onChange={(ev) => setRD("residual_impact", ev.target.value)} />
                    </div>
                    <div style={{ flex: "1 1 180px" }}>
                      <label className="label">Action</label>
                      <input className="input" value={rd.action} onChange={(ev) => setRD("action", ev.target.value)} placeholder="Remediation action" />
                    </div>
                    <div style={{ width: 140 }}>
                      <label className="label">Action owner</label>
                      <input className="input" value={rd.action_owner} onChange={(ev) => setRD("action_owner", ev.target.value)} placeholder="Owner" />
                    </div>
                    <div style={{ width: 150 }}>
                      <label className="label">Due date</label>
                      <input className="input" type="date" value={rd.due_date} onChange={(ev) => setRD("due_date", ev.target.value)} />
                    </div>
                    <button className="btn">Add</button>
                  </form>

                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Title</th>
                          <th>Category</th>
                          <th>Inherent LxI</th>
                          <th>Control</th>
                          <th>Residual LxI</th>
                          <th>Action owner</th>
                          <th>Due</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {openRcsa.risks.map((ri: RcsaRisk) => (
                          <tr key={ri.id}>
                            <td className="cell-title">{ri.title}</td>
                            <td className="muted">{ri.category || "—"}</td>
                            <td className="muted">{ri.inherent_likelihood}×{ri.inherent_impact} ({ri.inherent_score})</td>
                            <td><EffBadge value={ri.control_effectiveness} /></td>
                            <td className="muted">{ri.residual_likelihood}×{ri.residual_impact} ({ri.residual_score})</td>
                            <td className="muted">{ri.action_owner || "—"}</td>
                            <td className="muted">{ri.due_date || "—"}</td>
                            <td>
                              <button className="btn secondary sm" onClick={() => removeRisk(ri.id)}>Remove</button>
                            </td>
                          </tr>
                        ))}
                        {openRcsa.risks.length === 0 && (
                          <tr><td colSpan={8}><span className="muted">No risk lines recorded yet.</span></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <RecordPanels model="rcsa_assessment" entityId={openRcsa.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= KRIs */}
      {section === "kris" && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>Key Risk Indicators</h3>
              <span className="sub">{kris.length} total · click a row to record measurements</span>
            </div>
            <p className="muted" style={{ padding: "0 16px 12px", fontSize: 13 }}>
              RAG status is computed from the current value versus the warning / limit thresholds and the KRI direction.
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Name</th>
                    <th>Category</th>
                    <th>Owner</th>
                    <th>Current</th>
                    <th>Warn / Limit</th>
                    <th>RAG status</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {kris.map((k) => (
                    <tr key={k.id} style={{ cursor: "pointer" }} onClick={() => toggleKri(k)}>
                      <td className="ref">{k.reference || "—"}</td>
                      <td className="cell-title">{k.name}</td>
                      <td className="muted">{k.category || "—"}</td>
                      <td className="muted">{k.owner || "—"}</td>
                      <td className="muted">
                        {k.current_value != null ? `${num(k.current_value)}${k.unit ? " " + k.unit : ""}` : "—"}
                      </td>
                      <td className="muted">{num(k.warning_threshold)} / {num(k.limit_threshold)}</td>
                      <td>
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <Badge tone={RAG_TONE[k.status] || "neutral"}>{RAG_LABEL[k.status] || cap(k.status)}</Badge>
                          {k.is_breached && <Badge tone="critical">Breached</Badge>}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => toggleKri(k)}>
                            {openKri?.id === k.id ? "Hide" : "Measure"}
                          </button>
                          <button className="btn secondary sm" onClick={() => openEditKri(k)}>Edit</button>
                          <button className="btn secondary sm" onClick={() => removeKri(k)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {kris.length === 0 && (
                    <tr>
                      <td colSpan={8}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No KRIs</h3>
                          <p>Define key risk indicators and record measurements to monitor RAG status.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {openKri && (
            <>
              <div className="card" style={{ marginBottom: 16 }}>
                <div className="card-head row-between">
                  <div>
                    <h3>{openKri.reference} — {openKri.name}</h3>
                    <span className="sub">
                      {RAG_LABEL[openKri.status] || cap(openKri.status)} · {cap(openKri.direction)}
                      {openKri.last_measured_date ? " · last measured " + openKri.last_measured_date : ""}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
                    <div style={{ textAlign: "right" }}>
                      <div className="muted" style={{ fontSize: 12 }}>Current value</div>
                      <strong style={{ fontSize: 18 }}>
                        {openKri.current_value != null ? `${num(openKri.current_value)}${openKri.unit ? " " + openKri.unit : ""}` : "—"}
                      </strong>
                    </div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn secondary sm" onClick={() => openEditKri(openKri)}>Edit</button>
                      <button className="btn secondary sm" onClick={() => removeKri(openKri)}>Delete</button>
                    </div>
                  </div>
                </div>

                <div className="card-pad">
                  <strong>Measurement history</strong>
                  <p className="muted" style={{ margin: "4px 0 12px", fontSize: 13 }}>
                    Recorded values over time. RAG status recomputes from the latest value.
                  </p>
                  <form
                    style={{ display: "flex", gap: 8, marginBottom: 14, alignItems: "flex-end", flexWrap: "wrap" }}
                    onSubmit={(ev) => { ev.preventDefault(); addMeasurement(); }}
                  >
                    <div style={{ width: 160 }}>
                      <label className="label">Value{openKri.unit ? ` (${openKri.unit})` : ""}</label>
                      <input className="input" type="number" value={md.value} onChange={(ev) => setMD("value", ev.target.value)} placeholder="0" required />
                    </div>
                    <div style={{ width: 160 }}>
                      <label className="label">As of date</label>
                      <input className="input" type="date" value={md.as_of_date} onChange={(ev) => setMD("as_of_date", ev.target.value)} />
                    </div>
                    <div style={{ flex: "1 1 220px" }}>
                      <label className="label">Notes</label>
                      <input className="input" value={md.notes} onChange={(ev) => setMD("notes", ev.target.value)} placeholder="Context for this reading" />
                    </div>
                    <button className="btn">Record</button>
                  </form>

                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>As of date</th>
                          <th>Value</th>
                          <th>Notes</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...openKri.measurements]
                          .sort((a, b) => (b.as_of_date || "").localeCompare(a.as_of_date || ""))
                          .map((m) => (
                            <tr key={m.id}>
                              <td className="muted">{m.as_of_date || "—"}</td>
                              <td className="cell-title">{num(m.value)}{openKri.unit ? " " + openKri.unit : ""}</td>
                              <td className="muted">{m.notes || "—"}</td>
                            </tr>
                          ))}
                        {openKri.measurements.length === 0 && (
                          <tr><td colSpan={3}><span className="muted">No measurements recorded yet.</span></td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <RecordPanels model="key_risk_indicator" entityId={openKri.id} />
            </>
          )}
        </>
      )}

      {/* ============================================= LOSS DATABASE */}
      {section === "losses" && (
        <>
          <div className="grid stat-grid">
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{summary ? summary.total_count.toLocaleString() : "—"}</span>
              </div>
              <span className="l">Loss events</span>
            </div>
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{summary ? summary.total_gross.toLocaleString() : "—"}</span>
              </div>
              <span className="l">Total gross loss</span>
            </div>
            <div className="card stat">
              <div className="stat-top">
                <span className="n">{summary ? summary.total_net.toLocaleString() : "—"}</span>
              </div>
              <span className="l">Total net loss</span>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Loss Database</h3>
              <span className="sub">{losses.length} total · click a row to edit</span>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Ref</th>
                    <th>Title</th>
                    <th>Basel event type</th>
                    <th>Business line</th>
                    <th>Gross</th>
                    <th>Recovery</th>
                    <th>Net</th>
                    <th>Status</th>
                    <th>Occurred</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {losses.map((l) => (
                    <tr key={l.id} style={{ cursor: "pointer" }} onClick={() => openEditLoss(l)}>
                      <td className="ref">{l.reference || "—"}</td>
                      <td className="cell-title">{l.title}</td>
                      <td><Badge tone="info">{cap(l.basel_event_type)}</Badge></td>
                      <td className="muted">{l.business_line || "—"}</td>
                      <td className="muted">{num(l.gross_loss)} {l.currency}</td>
                      <td className="muted">{num(l.recovery)}</td>
                      <td className="muted">{num(l.net_loss)}</td>
                      <td><Badge tone={LOSS_STATUS_TONE[l.status] || "neutral"}>{cap(l.status)}</Badge></td>
                      <td className="muted">{l.occurrence_date || "—"}</td>
                      <td>
                        <div style={{ display: "flex", gap: 6 }} onClick={(ev) => ev.stopPropagation()}>
                          <button className="btn secondary sm" onClick={() => removeLoss(l)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {losses.length === 0 && (
                    <tr>
                      <td colSpan={10}>
                        <div className="empty">
                          <span className="ico"><IconCheck width={24} height={24} /></span>
                          <h3>No loss events</h3>
                          <p>Log operational losses against Basel event types to build the loss database.</p>
                        </div>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ============================================= MODALS */}
      {showRcsaForm && (
        <FormModal
          title={editingRcsa ? `Edit RCSA — ${editingRcsa.reference || editingRcsa.title}` : "New RCSA"}
          wide
          tabs={[
            { id: "general", label: "General", content: rcsaGeneral, required: true },
            { id: "timing", label: "Timing", content: rcsaTiming },
          ]}
          onClose={() => setShowRcsaForm(false)}
          onSave={saveRcsa}
          saving={savingRcsa}
          error={error}
          saveLabel={editingRcsa ? "Save changes" : "Create RCSA"}
          footerLeft={
            editingRcsa ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeRcsa(editingRcsa)}
                disabled={savingRcsa}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showKriForm && (
        <FormModal
          title={editingKri ? `Edit KRI — ${editingKri.reference || editingKri.name}` : "New KRI"}
          wide
          tabs={[{ id: "general", label: "General", content: kriGeneral, required: true }]}
          onClose={() => setShowKriForm(false)}
          onSave={saveKri}
          saving={savingKri}
          error={error}
          saveLabel={editingKri ? "Save changes" : "Create KRI"}
          footerLeft={
            editingKri ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeKri(editingKri)}
                disabled={savingKri}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showLossForm && (
        <FormModal
          title={editingLoss ? `Edit loss event — ${editingLoss.reference || editingLoss.title}` : "New loss event"}
          wide
          tabs={[
            { id: "general", label: "General", content: lossGeneral, required: true },
            { id: "details", label: "Details", content: lossDetails },
          ]}
          onClose={() => setShowLossForm(false)}
          onSave={saveLoss}
          saving={savingLoss}
          error={error}
          saveLabel={editingLoss ? "Save changes" : "Create loss event"}
          footerLeft={
            editingLoss ? (
              <button
                className="btn secondary sm"
                type="button"
                onClick={() => removeLoss(editingLoss)}
                disabled={savingLoss}
                style={{ color: "var(--danger, #c0392b)" }}
              >
                Delete
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}
