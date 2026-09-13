"use client";

/* Shared governance state for one open record (record-page-spec §3.3.14): its approval
   lifecycle, attestation, status-rule verdicts and the signed-in user, fetched once and
   read by the header (PrimaryAction, StatusRuleChips) and the rail (SignOffCard,
   WorkflowFields, AttestationPanel, RecordTrail) so they never disagree.

     const gov = useRecordGovernanceData("risk", detail?.id ?? null, { statusRulesModel: "risk" });
     const canWrite = useHasPermission("risk:write");
     const ctx = { fmt, now: new Date(), gov: toGovModel(gov, canWrite) };   // for lib/record/<type>.ts
     <RecordDrawer variant="dossier" governance={gov} …>                     // provides the context

   Reload rule: every action that can change approval, attestation or rule verdicts
   calls `gov.reload()` (then the page's own loadDetail). Components inside the drawer
   that find a matching context (`useRecordGovernance(type, id)`) read it and reload it;
   anywhere else they self-fetch as they always did, so classic pages are unchanged. */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, apiCall, type AttestationStatus, type Me } from "@/lib/api";
import { records, type RecordWorkflow } from "@/lib/records";
import type { GovModel } from "@/lib/record/types";
import type { StatusRuleVerdict, TrailFilter } from "@/components/record/types";

/** `AttestationStatus` plus the B1 fields (`can_attest`, `blocked_reason`); both are
 *  undefined on an older backend. */
export type AttestationStatusB1 = AttestationStatus & { can_attest?: boolean; blocked_reason?: string | null };

export type RecordGovernance = {
  entityType: string;
  entityId: string | null;
  workflow: RecordWorkflow | null;
  attestation: AttestationStatusB1 | null;
  statusRules: StatusRuleVerdict[];
  me: { id: string; email: string } | null;
  loading: boolean;
  errors: { workflow?: string; attestation?: string; statusRules?: string };
  /** Refetch workflow, attestation and status rules in parallel. */
  reload(): Promise<void>;
  trailFilter: TrailFilter;
  setTrailFilter(f: TrailFilter): void;
  attestOpen: boolean;
  openAttest(): void;
  closeAttest(): void;
  /** The model the status rules were evaluated for (null: not fetched here — StatusRuleChips self-fetches). */
  statusRulesModel: string | null;
  /** False when the page opted out of the approval lifecycle (the type is not in the registry). */
  lifecycle: boolean;
  /** Increments after every completed reload. */
  version: number;
  /** Completed loads for the CURRENT record: 0 while its first load is in flight, 1 after
   *  it, then +1 per `reload()`. Anything > 1 means an action changed the record since it
   *  opened — the trail refetches on that, and never twice when the user switches records. */
  entityVersion: number;
};

export const RecordGovernanceContext = createContext<RecordGovernance | null>(null);

/* `GET /auth/me` once per session. */
let mePromise: Promise<Me> | null = null;
function loadMe(): Promise<Me> {
  if (!mePromise) {
    mePromise = api.me().catch((e) => {
      mePromise = null;
      throw e;
    });
  }
  return mePromise;
}

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback);

/** Fetch and hold the governance for one record. Pass `entityId = null` for a no-op
 *  object (nothing is fetched). */
export function useRecordGovernanceData(
  entityType: string,
  entityId: string | null,
  opts?: { statusRulesModel?: string | null; lifecycle?: boolean },
): RecordGovernance {
  const statusRulesModel = opts?.statusRulesModel ?? null;
  const lifecycle = opts?.lifecycle ?? true;

  const [workflow, setWorkflow] = useState<RecordWorkflow | null>(null);
  const [attestation, setAttestation] = useState<AttestationStatusB1 | null>(null);
  const [statusRules, setStatusRules] = useState<StatusRuleVerdict[]>([]);
  const [me, setMe] = useState<{ id: string; email: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState<RecordGovernance["errors"]>({});
  const [trailFilter, setTrailFilter] = useState<TrailFilter>("all");
  const [attestOpen, setAttestOpen] = useState(false);
  const [version, setVersion] = useState(0);
  const [entityVersion, setEntityVersion] = useState(0);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    if (!entityId) return;
    const mine = ++seq.current;
    setLoading(true);
    const [wf, att, rules] = await Promise.allSettled([
      lifecycle ? records.workflow(entityType, entityId) : Promise.resolve(null),
      api.attestation(entityType, entityId) as Promise<AttestationStatusB1>,
      statusRulesModel
        ? apiCall<StatusRuleVerdict[]>("GET", `/status-rules/evaluate/${statusRulesModel}/${entityId}`)
        : Promise.resolve([] as StatusRuleVerdict[]),
    ]);
    if (mine !== seq.current) return; // a newer reload (or another record) superseded this one
    const next: RecordGovernance["errors"] = {};
    if (wf.status === "fulfilled") setWorkflow(wf.value);
    else next.workflow = errMsg(wf.reason, "Could not load the approval status");
    if (att.status === "fulfilled") setAttestation(att.value);
    else next.attestation = errMsg(att.reason, "Could not load the attestation");
    if (rules.status === "fulfilled") setStatusRules(Array.isArray(rules.value) ? rules.value : []);
    else next.statusRules = errMsg(rules.reason, "Could not evaluate the status rules");
    setErrors(next);
    setLoading(false);
    setVersion((v) => v + 1);
    setEntityVersion((v) => v + 1);
  }, [entityType, entityId, lifecycle, statusRulesModel]);

  useEffect(() => {
    seq.current++;
    setWorkflow(null);
    setAttestation(null);
    setStatusRules([]);
    setErrors({});
    setTrailFilter("all");
    setAttestOpen(false);
    setEntityVersion(0);
    setLoading(!!entityId);
    if (entityId) reload();
  }, [entityId, reload]);

  useEffect(() => {
    if (!entityId || me) return;
    let live = true;
    loadMe()
      .then((m) => live && setMe({ id: m.id, email: m.email }))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [entityId, me]);

  const openAttest = useCallback(() => setAttestOpen(true), []);
  const closeAttest = useCallback(() => setAttestOpen(false), []);

  return useMemo<RecordGovernance>(
    () => ({
      entityType,
      entityId,
      workflow,
      attestation,
      statusRules,
      me,
      loading,
      errors,
      reload,
      trailFilter,
      setTrailFilter,
      attestOpen,
      openAttest,
      closeAttest,
      statusRulesModel,
      lifecycle,
      version,
      entityVersion,
    }),
    [entityType, entityId, workflow, attestation, statusRules, me, loading, errors, reload, trailFilter, attestOpen, openAttest, closeAttest, statusRulesModel, lifecycle, version, entityVersion],
  );
}

/** The governance in context — only when it belongs to the given record (either
 *  argument omitted matches anything). null → the caller self-fetches. */
export function useRecordGovernance(entityType?: string, entityId?: string | null): RecordGovernance | null {
  const g = useContext(RecordGovernanceContext);
  if (!g) return null;
  if (entityType !== undefined && g.entityType !== entityType) return null;
  if (entityId !== undefined && g.entityId !== entityId) return null;
  return g;
}

/** Provides a governance context for `entityType/entityId` unless a matching one is
 *  already above (used by RecordPanels layout="dossier" and SignOffCard so they work
 *  even when the page forgot to pass `governance` to RecordDrawer). */
export function GovernanceScope({
  entityType,
  entityId,
  statusRulesModel,
  children,
}: {
  entityType: string;
  entityId: string;
  statusRulesModel?: string | null;
  children: ReactNode;
}) {
  const existing = useRecordGovernance(entityType, entityId);
  const own = useRecordGovernanceData(entityType, existing ? null : entityId, { statusRulesModel });
  if (existing) return <>{children}</>;
  return <RecordGovernanceContext.Provider value={own}>{children}</RecordGovernanceContext.Provider>;
}

const ATTEST_STATUS = new Set(["current", "overdue", "never"]);

/** The slice of governance `lib/record/<type>.ts` reads.
 *
 *  `approvalSteps` counts history items other than `import` backfills and approval-owner
 *  changes (an owner change is not a sign-off step); `lastStep` is the newest such item. */
export function toGovModel(g: RecordGovernance | null, canWrite: boolean): GovModel {
  return govModelFromParts(g?.lifecycle === false ? null : (g?.workflow ?? null), g?.attestation ?? null, canWrite, g?.lifecycle !== false);
}

/** toGovModel from raw parts (a component that fetched its own workflow / attestation). */
export function govModelFromParts(
  workflow: RecordWorkflow | null,
  att: AttestationStatusB1 | null,
  canWrite: boolean,
  lifecycle = true,
): GovModel {
  const history = workflow?.history ?? [];
  const steps = history.filter((h) => h.action !== "owner");
  const signOffSteps = steps.filter((h) => h.action !== "import");
  const newest = steps[0] ?? null; // history is newest first
  const lastSubmit = history.find((h) => h.action === "submit") ?? null;
  return {
    workflowState: lifecycle ? (workflow?.state ?? null) : null,
    approvalSteps: signOffSteps.length,
    lastStep: newest
      ? { action: newest.action, at: newest.at, actor: newest.actor_email || "system", reason: newest.reason || "" }
      : null,
    lastSubmitAt: lastSubmit ? lastSubmit.at : null,
    attestation: att
      ? {
          status: (ATTEST_STATUS.has(att.status) ? att.status : "never") as "current" | "overdue" | "never",
          nativeReview: !!att.native_review,
          nextDue: att.next_due ?? null,
          canAttest: typeof att.can_attest === "boolean" ? att.can_attest : null,
          blockedReason: att.blocked_reason ?? null,
        }
      : null,
    canWrite,
  };
}
