"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import FormModal from "@/components/FormModal";
import ImportExport from "@/components/ImportExport";
import RecordPanels from "@/components/RecordPanels";
import RichText from "@/components/RichText";
import {
  Field,
  TextInput,
  TextArea,
  Select,
  MultiSelect,
  NumberInput,
  type Option,
} from "@/components/fields";
import { Badge, ComplianceBadge } from "@/components/badges";
import { IconCompliance, IconPlus, IconCheck } from "@/components/icons";

/* ------------------------------------------------------------------ types */
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

type Framework = {
  id: string;
  name: string;
  version: string;
  authority: string;
  regulator: string;
  scope: string;
  description: string;
  workflow_status: string;
  requirement_count: number;
  compliant_count: number;
  created_at: string;
};

type Ref = { id: string; reference?: string; title?: string; name?: string };

type Finding = {
  id: string;
  title: string;
  description: string;
  recommendation: string;
  severity: string;
  status: string;
  deadline: string | null;
  created_at: string;
};

type Requirement = {
  id: string;
  framework_id: string;
  reference: string;
  title: string;
  description: string;
  domain: string;
  audit_questionnaire: string;
  status: string;
  treatment: string | null;
  owner: string;
  efficacy: number | null;
  implementation: string;
  legal_id: string | null;
  workflow_status: string;
  controls: Ref[];
  risks: Ref[];
  policies: Ref[];
  legal: Ref | null;
  findings: Finding[];
  is_covered: boolean;
  open_findings: number;
  evidence_count: number;
  crosswalk_count: number;
};

type CrosswalkItem = {
  id: string;
  reference: string;
  title: string;
  status: string;
  framework_id: string;
  framework_name: string;
};

type Evidence = {
  id: string;
  title: string;
  evidence_type: string;
  status: string;
  control?: { id: string; name: string; reference: string } | null;
};

type GapItem = {
  id: string;
  reference: string;
  title: string;
  status: string;
  is_covered: boolean;
  reason: string;
};

type GapAnalysis = {
  framework_id: string;
  framework_name: string;
  total_requirements: number;
  by_status: Record<string, number>;
  covered: number;
  uncovered: number;
  compliant_pct: number;
  gaps: GapItem[];
};

type ControlOpt = { id: string; name: string; reference: string };
type RiskOpt = { id: string; title: string; reference: string };
type PolicyOpt = { id: string; title: string; reference: string };
type LegalOpt = { id: string; name: string; reference: string };

/* ------------------------------------------------------------------ helpers */
const cap = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const opts = (vals: string[]): Option[] => vals.map((v) => ({ value: v, label: cap(v) }));

const COMPLIANCE_STATUS = opts([
  "not_assessed",
  "non_compliant",
  "partially_compliant",
  "compliant",
  "not_applicable",
]);
const TREATMENT = opts(["implement", "improve", "accept", "transfer", "not_applicable"]);
const WORKFLOW = opts(["draft", "in_review", "approved", "retired"]);
const SEVERITY = opts(["low", "medium", "high", "critical"]);

const SEVERITY_TONE: Record<string, "low" | "medium" | "high" | "critical"> = {
  low: "low",
  medium: "medium",
  high: "high",
  critical: "critical",
};

/* ------------------------------------------------------------------ framework form */
type FwState = {
  name: string;
  version: string;
  authority: string;
  regulator: string;
  scope: string;
  description: string;
  workflow_status: string;
};

const FW_BLANK: FwState = {
  name: "",
  version: "",
  authority: "",
  regulator: "",
  scope: "",
  description: "",
  workflow_status: "draft",
};

function fromFramework(f: Framework): FwState {
  return {
    name: f.name,
    version: f.version || "",
    authority: f.authority || "",
    regulator: f.regulator || "",
    scope: f.scope || "",
    description: f.description || "",
    workflow_status: f.workflow_status || "draft",
  };
}

/* ------------------------------------------------------------------ requirement form */
type ReqState = {
  reference: string;
  title: string;
  description: string;
  domain: string;
  status: string;
  workflow_status: string;
  treatment: string;
  owner: string;
  efficacy: number | "";
  implementation: string;
  audit_questionnaire: string;
  legal_id: string;
  control_ids: string[];
  risk_ids: string[];
  policy_ids: string[];
};

const REQ_BLANK: ReqState = {
  reference: "",
  title: "",
  description: "",
  domain: "",
  status: "not_assessed",
  workflow_status: "draft",
  treatment: "",
  owner: "",
  efficacy: "",
  implementation: "",
  audit_questionnaire: "",
  legal_id: "",
  control_ids: [],
  risk_ids: [],
  policy_ids: [],
};

function fromRequirement(r: Requirement): ReqState {
  return {
    reference: r.reference || "",
    title: r.title,
    description: r.description || "",
    domain: r.domain || "",
    status: r.status,
    workflow_status: r.workflow_status || "draft",
    treatment: r.treatment || "",
    owner: r.owner || "",
    efficacy: r.efficacy ?? "",
    implementation: r.implementation || "",
    audit_questionnaire: r.audit_questionnaire || "",
    legal_id: r.legal_id || "",
    control_ids: r.controls.map((c) => c.id),
    risk_ids: r.risks.map((c) => c.id),
    policy_ids: r.policies.map((c) => c.id),
  };
}

function reqPayload(s: ReqState) {
  return {
    reference: s.reference,
    title: s.title,
    description: s.description,
    domain: s.domain,
    status: s.status,
    workflow_status: s.workflow_status,
    treatment: s.treatment || null,
    owner: s.owner,
    efficacy: s.efficacy === "" ? null : s.efficacy,
    implementation: s.implementation,
    audit_questionnaire: s.audit_questionnaire,
    legal_id: s.legal_id || null,
    control_ids: s.control_ids,
    risk_ids: s.risk_ids,
    policy_ids: s.policy_ids,
  };
}

/* ------------------------------------------------------------------ finding form */
type FindingState = {
  title: string;
  description: string;
  recommendation: string;
  severity: string;
  deadline: string;
};
const FINDING_BLANK: FindingState = {
  title: "",
  description: "",
  recommendation: "",
  severity: "medium",
  deadline: "",
};

/* ================================================================== page */
export default function CompliancePage() {
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [gap, setGap] = useState<GapAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [openReq, setOpenReq] = useState<Requirement | null>(null);
  const [crosswalks, setCrosswalks] = useState<CrosswalkItem[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);

  // option sources
  const [controls, setControls] = useState<ControlOpt[]>([]);
  const [risks, setRisks] = useState<RiskOpt[]>([]);
  const [policies, setPolicies] = useState<PolicyOpt[]>([]);
  const [legals, setLegals] = useState<LegalOpt[]>([]);

  // framework modal
  const [showFw, setShowFw] = useState(false);
  const [editingFw, setEditingFw] = useState<Framework | null>(null);
  const [fw, setFw] = useState<FwState>(FW_BLANK);
  const [savingFw, setSavingFw] = useState(false);

  // framework library
  type FwTemplate = { key: string; name: string; version: string; authority: string; description: string; requirement_count: number };
  const [showLib, setShowLib] = useState(false);
  const [templates, setTemplates] = useState<FwTemplate[]>([]);
  const [loadingTpl, setLoadingTpl] = useState<string | null>(null);
  async function openLibrary() {
    setError(null);
    setShowLib(true);
    try {
      setTemplates(await apiCall<FwTemplate[]>("GET", "/framework-templates"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load library");
    }
  }
  async function loadTemplate(key: string) {
    setError(null);
    setLoadingTpl(key);
    try {
      const created = await apiCall<Framework>("POST", `/framework-templates/${key}/load`);
      setShowLib(false);
      await loadFrameworks(created.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load framework");
    } finally {
      setLoadingTpl(null);
    }
  }

  // requirement modal
  const [showReq, setShowReq] = useState(false);
  const [editingReq, setEditingReq] = useState<Requirement | null>(null);
  const [rq, setRq] = useState<ReqState>(REQ_BLANK);
  const [savingReq, setSavingReq] = useState(false);
  const [crosswalkIds, setCrosswalkIds] = useState<string[]>([]);
  const [allRequirements, setAllRequirements] = useState<CrosswalkItem[]>([]);

  // finding modal
  const [showFinding, setShowFinding] = useState(false);
  const [findingReq, setFindingReq] = useState<Requirement | null>(null);
  const [fd, setFd] = useState<FindingState>(FINDING_BLANK);
  const [savingFinding, setSavingFinding] = useState(false);

  const setF = <K extends keyof FwState>(k: K, v: FwState[K]) => setFw((p) => ({ ...p, [k]: v }));
  const setR = <K extends keyof ReqState>(k: K, v: ReqState[K]) => setRq((p) => ({ ...p, [k]: v }));
  const setFi = <K extends keyof FindingState>(k: K, v: FindingState[K]) =>
    setFd((p) => ({ ...p, [k]: v }));

  /* ---------------------------------------------------------------- loaders */
  async function loadFrameworks(selectId?: string) {
    const fwPage = await apiCall<Page<Framework>>("GET", "/frameworks");
    setFrameworks(fwPage.items);
    if (selectId) setSelected(selectId);
    else if (!selected && fwPage.items.length) setSelected(fwPage.items[0].id);
    return fwPage.items;
  }

  async function loadRequirements(frameworkId: string) {
    const [reqs, g] = await Promise.all([
      apiCall<Requirement[]>("GET", `/frameworks/${frameworkId}/requirements`),
      apiCall<GapAnalysis>("GET", `/frameworks/${frameworkId}/gap-analysis`),
    ]);
    setRequirements(reqs);
    setGap(g);
  }

  useEffect(() => {
    loadFrameworks().catch((e) => setError(e.message));
    apiCall<Page<ControlOpt>>("GET", "/controls?limit=200")
      .then((r) => setControls(r.items))
      .catch(() => {});
    apiCall<Page<RiskOpt>>("GET", "/risks?limit=200")
      .then((r) => setRisks(r.items))
      .catch(() => {});
    apiCall<Page<PolicyOpt>>("GET", "/policies?limit=200")
      .then((r) => setPolicies(r.items))
      .catch(() => {});
    apiCall<Page<LegalOpt>>("GET", "/legals?limit=200")
      .then((r) => setLegals(r.items))
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) return;
    setOpenReq(null);
    loadRequirements(selected).catch((e) => setError(e.message));
  }, [selected]);

  async function openRequirementDetail(r: Requirement) {
    if (openReq?.id === r.id) {
      setOpenReq(null);
      return;
    }
    setOpenReq(r);
    setCrosswalks([]);
    setEvidence([]);
    try {
      const [cw, ev] = await Promise.all([
        apiCall<CrosswalkItem[]>("GET", `/requirements/${r.id}/crosswalks`),
        apiCall<Evidence[]>("GET", `/requirements/${r.id}/evidence`),
      ]);
      setCrosswalks(cw);
      setEvidence(ev);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load detail");
    }
  }

  /* ---------------------------------------------------------------- framework ops */
  function openNewFw() {
    setEditingFw(null);
    setFw(FW_BLANK);
    setShowFw(true);
  }
  function openEditFw(f: Framework) {
    setEditingFw(f);
    setFw(fromFramework(f));
    setShowFw(true);
  }
  async function saveFw() {
    setError(null);
    setSavingFw(true);
    try {
      if (editingFw) {
        const updated = await apiCall<Framework>("PATCH", `/frameworks/${editingFw.id}`, fw);
        await loadFrameworks(updated.id);
      } else {
        const created = await apiCall<Framework>("POST", "/frameworks", fw);
        await loadFrameworks(created.id);
      }
      setShowFw(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save framework");
    } finally {
      setSavingFw(false);
    }
  }
  async function deleteFw() {
    if (!editingFw) return;
    if (!window.confirm(`Delete framework "${editingFw.name}" and all its requirements?`)) return;
    setError(null);
    setSavingFw(true);
    try {
      await apiCall("DELETE", `/frameworks/${editingFw.id}`);
      setShowFw(false);
      setSelected(null);
      const remaining = await loadFrameworks();
      setSelected(remaining[0]?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete framework");
    } finally {
      setSavingFw(false);
    }
  }

  /* ---------------------------------------------------------------- requirement ops */
  async function ensureAllRequirements() {
    // Pull every requirement across frameworks to offer as crosswalk targets.
    try {
      const all: CrosswalkItem[] = [];
      for (const f of frameworks) {
        const reqs = await apiCall<Requirement[]>("GET", `/frameworks/${f.id}/requirements`);
        for (const r of reqs)
          all.push({
            id: r.id,
            reference: r.reference,
            title: r.title,
            status: r.status,
            framework_id: f.id,
            framework_name: f.name,
          });
      }
      setAllRequirements(all);
    } catch {
      /* ignore */
    }
  }

  async function openNewReq() {
    setEditingReq(null);
    setRq(REQ_BLANK);
    setCrosswalkIds([]);
    setShowReq(true);
    ensureAllRequirements();
  }
  async function openEditReq(r: Requirement) {
    setEditingReq(r);
    setRq(fromRequirement(r));
    setShowReq(true);
    ensureAllRequirements();
    try {
      const cw = await apiCall<CrosswalkItem[]>("GET", `/requirements/${r.id}/crosswalks`);
      setCrosswalkIds(cw.map((c) => c.id));
    } catch {
      setCrosswalkIds([]);
    }
  }
  async function saveReq() {
    if (!selected) return;
    setError(null);
    setSavingReq(true);
    try {
      let reqId: string;
      if (editingReq) {
        const updated = await apiCall<Requirement>(
          "PATCH",
          `/requirements/${editingReq.id}`,
          reqPayload(rq),
        );
        reqId = updated.id;
      } else {
        const created = await apiCall<Requirement>(
          "POST",
          `/frameworks/${selected}/requirements`,
          reqPayload(rq),
        );
        reqId = created.id;
      }
      // Crosswalks are managed via their own endpoint (PUT replaces the set).
      await apiCall<CrosswalkItem[]>("PUT", `/requirements/${reqId}/crosswalks`, {
        related_requirement_ids: crosswalkIds,
      });
      setShowReq(false);
      await loadRequirements(selected);
      await loadFrameworks(selected);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save requirement");
    } finally {
      setSavingReq(false);
    }
  }
  async function deleteReq() {
    if (!editingReq || !selected) return;
    if (!window.confirm(`Delete requirement "${editingReq.reference || editingReq.title}"?`)) return;
    setError(null);
    setSavingReq(true);
    try {
      await apiCall("DELETE", `/requirements/${editingReq.id}`);
      setShowReq(false);
      await loadRequirements(selected);
      await loadFrameworks(selected);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete requirement");
    } finally {
      setSavingReq(false);
    }
  }

  /* ---------------------------------------------------------------- finding ops */
  function openFinding(r: Requirement) {
    setFindingReq(r);
    setFd(FINDING_BLANK);
    setShowFinding(true);
  }
  async function saveFinding() {
    if (!findingReq || !selected) return;
    setError(null);
    setSavingFinding(true);
    try {
      await apiCall("POST", `/requirements/${findingReq.id}/findings`, {
        title: fd.title,
        description: fd.description,
        recommendation: fd.recommendation,
        severity: fd.severity,
        deadline: fd.deadline || null,
      });
      setShowFinding(false);
      await loadRequirements(selected);
      if (openReq?.id === findingReq.id) {
        const fresh = await apiCall<Requirement>("GET", `/requirements/${findingReq.id}`);
        setOpenReq(fresh);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add finding");
    } finally {
      setSavingFinding(false);
    }
  }
  async function closeFinding(findingId: string) {
    setError(null);
    try {
      await apiCall("POST", `/findings/${findingId}/close`);
      if (selected) await loadRequirements(selected);
      if (openReq) {
        const fresh = await apiCall<Requirement>("GET", `/requirements/${openReq.id}`);
        setOpenReq(fresh);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to close finding");
    }
  }

  /* ---------------------------------------------------------------- options */
  const controlOpts: Option[] = useMemo(
    () => controls.map((c) => ({ value: c.id, label: c.name, sub: c.reference })),
    [controls],
  );
  const riskOpts: Option[] = useMemo(
    () => risks.map((r) => ({ value: r.id, label: r.title, sub: r.reference })),
    [risks],
  );
  const policyOpts: Option[] = useMemo(
    () => policies.map((p) => ({ value: p.id, label: p.title, sub: p.reference })),
    [policies],
  );
  const legalOpts: Option[] = useMemo(
    () => legals.map((l) => ({ value: l.id, label: l.name, sub: l.reference })),
    [legals],
  );
  const crosswalkOpts: Option[] = useMemo(
    () =>
      allRequirements
        .filter((r) => r.id !== editingReq?.id)
        .map((r) => ({
          value: r.id,
          label: `${r.reference ? r.reference + " — " : ""}${r.title}`,
          sub: r.framework_name,
        })),
    [allRequirements, editingReq],
  );

  /* ---------------------------------------------------------------- tabs: framework */
  const fwGeneralTab = (
    <>
      <Field label="Name" required help="For example: ISO 27001:2022, SOC 2, GDPR, PCI DSS.">
        <TextInput value={fw.name} onChange={(v) => setF("name", v)} placeholder="ISO 27001:2022" required />
      </Field>
      <div className="field-row">
        <Field label="Version" help="Release/edition of the framework.">
          <TextInput value={fw.version} onChange={(v) => setF("version", v)} placeholder="2022" />
        </Field>
        <Field label="Workflow">
          <Select value={fw.workflow_status} onChange={(v) => setF("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Authority" help="Body that publishes the standard (ISO, AICPA, NIST…).">
          <TextInput value={fw.authority} onChange={(v) => setF("authority", v)} placeholder="ISO" />
        </Field>
        <Field label="Regulator" help="Body that enforces compliance, if different.">
          <TextInput value={fw.regulator} onChange={(v) => setF("regulator", v)} placeholder="National DPA" />
        </Field>
      </div>
    </>
  );

  const fwDetailTab = (
    <>
      <Field label="Scope / Applicability" help="What parts of the organization this framework applies to.">
        <TextArea value={fw.scope} onChange={(v) => setF("scope", v)} rows={4} placeholder="All cloud-hosted production systems and the teams operating them." />
      </Field>
      <Field label="Description">
        <TextArea value={fw.description} onChange={(v) => setF("description", v)} rows={5} placeholder="Purpose and background of this framework." />
      </Field>
    </>
  );

  /* ---------------------------------------------------------------- tabs: requirement */
  const reqGeneralTab = (
    <>
      <div className="field-row">
        <Field label="Reference" help='The clause/control number, e.g. "A.5.1".'>
          <TextInput value={rq.reference} onChange={(v) => setR("reference", v)} placeholder="A.5.1" />
        </Field>
        <Field label="Domain" help="Grouping/category within the framework.">
          <TextInput value={rq.domain} onChange={(v) => setR("domain", v)} placeholder="Organizational controls" />
        </Field>
      </div>
      <Field label="Title" required>
        <TextInput value={rq.title} onChange={(v) => setR("title", v)} placeholder="Policies for information security" required />
      </Field>
      <Field label="Description" help="The requirement text / what must be achieved.">
        <RichText value={rq.description} onChange={(v) => setR("description", v)} placeholder="Describe the requirement…" />
      </Field>
      <div className="field-row">
        <Field label="Compliance Status">
          <Select value={rq.status} onChange={(v) => setR("status", v)} options={COMPLIANCE_STATUS} />
        </Field>
        <Field label="Workflow">
          <Select value={rq.workflow_status} onChange={(v) => setR("workflow_status", v)} options={WORKFLOW} />
        </Field>
      </div>
    </>
  );

  const reqImplementationTab = (
    <>
      <div className="field-row">
        <Field label="Treatment Strategy" help="How a gap against this requirement is treated.">
          <Select value={rq.treatment} onChange={(v) => setR("treatment", v)} options={TREATMENT} placeholder="Not set" />
        </Field>
        <Field label="Owner / GRC Contact">
          <TextInput value={rq.owner} onChange={(v) => setR("owner", v)} placeholder="CISO" />
        </Field>
      </div>
      <Field label="Efficacy (%)" help="How effective the current implementation is (0–100).">
        <NumberInput value={rq.efficacy} onChange={(v) => setR("efficacy", v)} min={0} max={100} step={5} placeholder="0–100" />
      </Field>
      <Field label="How We Comply (Implementation)" help="Narrative of the controls/processes that satisfy this requirement.">
        <RichText value={rq.implementation} onChange={(v) => setR("implementation", v)} placeholder="Describe how the organization complies…" />
      </Field>
    </>
  );

  const reqMappingsTab = (
    <>
      <Field label="Mapped Controls" help="Controls that satisfy this requirement (map once, comply many).">
        <MultiSelect value={rq.control_ids} onChange={(v) => setR("control_ids", v)} options={controlOpts} />
      </Field>
      <Field label="Related Risks" help="Risks this requirement helps mitigate.">
        <MultiSelect value={rq.risk_ids} onChange={(v) => setR("risk_ids", v)} options={riskOpts} />
      </Field>
      <Field label="Related Policies" help="Policies that document this requirement.">
        <MultiSelect value={rq.policy_ids} onChange={(v) => setR("policy_ids", v)} options={policyOpts} />
      </Field>
      <Field label="Legal Obligation" help="The law/regulation this requirement discharges.">
        <Select value={rq.legal_id} onChange={(v) => setR("legal_id", v)} options={legalOpts} placeholder="None" />
      </Field>
      <Field label="Crosswalks" help="Equivalent requirements in other frameworks (e.g. ISO A.5.15 ≡ SOC2 CC6.1).">
        <MultiSelect value={crosswalkIds} onChange={setCrosswalkIds} options={crosswalkOpts} />
      </Field>
    </>
  );

  const reqAuditTab = (
    <>
      <Field label="Audit Questionnaire" help="How to test compliance with this requirement during an audit.">
        <TextArea value={rq.audit_questionnaire} onChange={(v) => setR("audit_questionnaire", v)} rows={6} placeholder="List the questions / tests an auditor should perform." />
      </Field>
      {editingReq && editingReq.findings.length > 0 && (
        <Field label="Existing Findings">
          <div className="card-pad" style={{ padding: 0 }}>
            {editingReq.findings.map((fnd) => (
              <div key={fnd.id} className="activity-item">
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13 }}>{fnd.title}</div>
                  <div className="when">
                    <Badge tone={SEVERITY_TONE[fnd.severity] || "neutral"}>{fnd.severity}</Badge>{" "}
                    <Badge tone={fnd.status === "open" ? "high" : "low"} plain>
                      {fnd.status}
                    </Badge>
                    {fnd.deadline ? ` · due ${fnd.deadline}` : ""}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Field>
      )}
    </>
  );

  const linkCount = (r: Requirement) =>
    r.controls.length + r.risks.length + r.policies.length;

  /* ================================================================ render */
  const selectedFw = frameworks.find((f) => f.id === selected) || null;

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Compliance Management</h1>
          <p>Map controls to requirements, crosswalk frameworks, and collect evidence.</p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select
            className="select"
            style={{ width: 240 }}
            value={selected || ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            {frameworks.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name} ({f.requirement_count})
              </option>
            ))}
          </select>
          {selectedFw && (
            <button className="btn secondary" onClick={() => openEditFw(selectedFw)}>
              Edit
            </button>
          )}
          <button className="btn secondary" onClick={openLibrary}>
            <IconCompliance width={16} height={16} /> Library
          </button>
          <button className="btn secondary" onClick={openNewFw}>
            <IconPlus width={16} height={16} /> Framework
          </button>
          {selected && (
            <>
              <ImportExport
                resource="requirements"
                label="Requirements"
                onDone={() => { if (selected) loadRequirements(selected); }}
              />
              <button className="btn" onClick={openNewReq}>
                <IconPlus width={16} height={16} /> Requirement
              </button>
            </>
          )}
        </div>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {gap && (
        <div className="grid stat-grid">
          <div className="card stat">
            <div className="stat-top"><span className="n">{gap.total_requirements}</span></div>
            <span className="l">Requirements</span>
          </div>
          <div className="card stat ok">
            <div className="stat-top"><span className="n" style={{ color: "var(--green)" }}>{gap.compliant_pct}%</span></div>
            <span className="l">Compliant</span>
            <div className="progress" style={{ marginTop: 4 }}>
              <span style={{ width: `${gap.compliant_pct}%` }} />
            </div>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{gap.covered}/{gap.total_requirements}</span></div>
            <span className="l">Controls mapped</span>
          </div>
          <div className="card stat warn">
            <div className="stat-top"><span className="n" style={{ color: "var(--orange)" }}>{gap.gaps.length}</span></div>
            <span className="l">Open gaps</span>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Requirements</h3>
          <span className="sub">{gap?.framework_name} · click a row for crosswalks &amp; evidence</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Requirement</th>
                <th>Domain</th>
                <th>Status</th>
                <th>Covered</th>
                <th>Controls</th>
                <th>Policies</th>
                <th>Evidence</th>
                <th>Findings</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openRequirementDetail(r)}>
                  <td className="ref">{r.reference}</td>
                  <td className="cell-title">{r.title}</td>
                  <td className="muted">{r.domain || "—"}</td>
                  <td><ComplianceBadge value={r.status} /></td>
                  <td>
                    {r.is_covered ? (
                      <Badge tone="low" plain>Yes</Badge>
                    ) : (
                      <Badge tone="high" plain>No</Badge>
                    )}
                  </td>
                  <td className="muted">{r.controls.length}</td>
                  <td className="muted">{r.policies.length}</td>
                  <td>
                    {r.evidence_count > 0 ? (
                      <Badge tone="low" plain>{r.evidence_count}</Badge>
                    ) : (
                      <span className="muted">0</span>
                    )}
                  </td>
                  <td>
                    {r.open_findings > 0 ? (
                      <Badge tone="high" plain>{r.open_findings}</Badge>
                    ) : (
                      <span className="muted">0</span>
                    )}
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                      <button className="btn secondary sm" onClick={() => openEditReq(r)}>
                        Edit
                      </button>
                      <button className="btn secondary sm" onClick={() => openFinding(r)}>
                        Finding
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {requirements.length === 0 && (
                <tr>
                  <td colSpan={10}>
                    <div className="empty">
                      <span className="ico"><IconCompliance width={24} height={24} /></span>
                      <h3>No requirements</h3>
                      <p>Add the first requirement to this framework.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {openReq && (
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 16 }}>
          <div className="card">
            <div className="card-head">
              <h3>Crosswalks · {openReq.reference}</h3>
              <span className="sub">Equivalent requirements</span>
            </div>
            <div className="card-pad">
              {crosswalks.length ? (
                crosswalks.map((c) => (
                  <div key={c.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>
                        <span className="ref">{c.reference}</span> — {c.title}
                      </div>
                      <div className="when">
                        <Badge tone="info" plain>{c.framework_name}</Badge>{" "}
                        <ComplianceBadge value={c.status} />
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <span className="muted">No crosswalks mapped for this requirement.</span>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Evidence · {openReq.reference}</h3>
              <span className="sub">Via mapped controls</span>
            </div>
            <div className="card-pad">
              {evidence.length ? (
                evidence.map((ev) => (
                  <div key={ev.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{ev.title}</div>
                      <div className="when">
                        <Badge tone="info" plain>{ev.evidence_type}</Badge>{" "}
                        {ev.control ? ev.control.reference || ev.control.name : ""}
                      </div>
                    </div>
                    <Badge tone={ev.status === "valid" ? "low" : "neutral"}>{ev.status}</Badge>
                  </div>
                ))
              ) : (
                <span className="muted">No evidence collected yet.</span>
              )}
            </div>
          </div>
        </div>
      )}

      {openReq && openReq.findings.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="card-head">
            <h3>Findings · {openReq.reference}</h3>
            <span className="sub">{openReq.open_findings} open</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Finding</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Deadline</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {openReq.findings.map((fnd) => (
                  <tr key={fnd.id}>
                    <td className="cell-title">{fnd.title}</td>
                    <td><Badge tone={SEVERITY_TONE[fnd.severity] || "neutral"}>{fnd.severity}</Badge></td>
                    <td><Badge tone={fnd.status === "open" ? "high" : "low"}>{fnd.status}</Badge></td>
                    <td className="muted">{fnd.deadline || "—"}</td>
                    <td>
                      {fnd.status === "open" && (
                        <button className="btn secondary sm" onClick={() => closeFinding(fnd.id)}>
                          <IconCheck width={14} height={14} /> Close
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {gap && gap.gaps.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>Gap analysis</h3>
            <span className="sub">{gap.gaps.length} open</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Requirement</th>
                  <th>Status</th>
                  <th>Why it&apos;s a gap</th>
                </tr>
              </thead>
              <tbody>
                {gap.gaps.map((g) => (
                  <tr key={g.id}>
                    <td className="ref">{g.reference}</td>
                    <td className="cell-title">{g.title}</td>
                    <td><ComplianceBadge value={g.status} /></td>
                    <td className="muted">{g.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selectedFw && <RecordPanels model="framework" entityId={selectedFw.id} />}

      {showLib && (
        <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && setShowLib(false)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="Framework library">
            <div className="modal-head">
              <h2>Framework Library</h2>
              <button className="x" onClick={() => setShowLib(false)} aria-label="Close">✕</button>
            </div>
            <div className="modal-body">
              <p className="muted" style={{ marginTop: 0, marginBottom: 16 }}>
                Load a recognised standard with all of its clauses and controls as requirements. You can then map controls,
                collect evidence and track coverage against it.
              </p>
              {templates.length === 0 && <div className="empty"><p>Loading…</p></div>}
              {templates.map((t) => (
                <div key={t.key} className="card card-pad" style={{ marginBottom: 12, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
                  <div>
                    <div className="cell-title" style={{ marginBottom: 2 }}>{t.name}</div>
                    <div className="muted" style={{ fontSize: 12.5 }}>{t.description}</div>
                    <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                      <Badge tone="info">{t.authority}</Badge>
                      <Badge tone="neutral" plain>{t.requirement_count} requirements</Badge>
                    </div>
                  </div>
                  <button className="btn" disabled={loadingTpl === t.key} onClick={() => loadTemplate(t.key)}>
                    {loadingTpl === t.key ? "Loading…" : "Load"}
                  </button>
                </div>
              ))}
            </div>
            <div className="modal-foot">
              <button className="btn secondary" onClick={() => setShowLib(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {showFw && (
        <FormModal
          title={editingFw ? `Edit framework — ${editingFw.name}` : "Add framework"}
          tabs={[
            { id: "general", label: "General", content: fwGeneralTab, required: true },
            { id: "detail", label: "Scope & Description", content: fwDetailTab },
          ]}
          onClose={() => setShowFw(false)}
          onSave={saveFw}
          saving={savingFw}
          error={error}
          saveLabel={editingFw ? "Save changes" : "Create framework"}
          footerLeft={
            editingFw ? (
              <button className="btn secondary" style={{ color: "var(--red)" }} onClick={deleteFw} disabled={savingFw} type="button">
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showReq && (
        <FormModal
          title={editingReq ? `Edit requirement — ${editingReq.reference || editingReq.title}` : "Add requirement"}
          wide
          tabs={[
            { id: "general", label: "General", content: reqGeneralTab, required: true },
            { id: "implementation", label: "Implementation", content: reqImplementationTab },
            { id: "mappings", label: "Mappings & Crosswalks", content: reqMappingsTab },
            { id: "audit", label: "Audit & Findings", content: reqAuditTab },
          ]}
          onClose={() => setShowReq(false)}
          onSave={saveReq}
          saving={savingReq}
          error={error}
          saveLabel={editingReq ? "Save changes" : "Create requirement"}
          footerLeft={
            editingReq ? (
              <button className="btn secondary" style={{ color: "var(--red)" }} onClick={deleteReq} disabled={savingReq} type="button">
                Delete
              </button>
            ) : undefined
          }
        />
      )}

      {showFinding && findingReq && (
        <FormModal
          title={`Add finding — ${findingReq.reference || findingReq.title}`}
          tabs={[
            {
              id: "finding",
              label: "Finding",
              content: (
                <>
                  <Field label="Title" required>
                    <TextInput value={fd.title} onChange={(v) => setFi("title", v)} placeholder="Missing MFA on admin accounts" required />
                  </Field>
                  <Field label="Description">
                    <TextArea value={fd.description} onChange={(v) => setFi("description", v)} rows={3} placeholder="What gap was observed." />
                  </Field>
                  <Field label="Recommendation">
                    <TextArea value={fd.recommendation} onChange={(v) => setFi("recommendation", v)} rows={3} placeholder="How to remediate." />
                  </Field>
                  <div className="field-row">
                    <Field label="Severity">
                      <Select value={fd.severity} onChange={(v) => setFi("severity", v)} options={SEVERITY} />
                    </Field>
                    <Field label="Deadline">
                      <TextInput value={fd.deadline} onChange={(v) => setFi("deadline", v)} type="date" />
                    </Field>
                  </div>
                </>
              ),
              required: true,
            },
          ]}
          onClose={() => setShowFinding(false)}
          onSave={saveFinding}
          saving={savingFinding}
          error={error}
          saveLabel="Raise finding"
        />
      )}
    </>
  );
}
