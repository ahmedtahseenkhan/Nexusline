"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { confirmDialog, toast } from "@/lib/feedback";
import { IconPlus } from "@/components/icons";

/* Define your own approval route: "Risk acceptance goes Owner → Department Head → CRO →
   Risk Committee, two of three".

   Every stage raises a real approval request, so the inbox, N-eyes counting, segregation
   of duties and the audit trail are the ones that already exist — a stage cannot approve
   itself around them. A record type with no enabled route keeps the fixed lifecycle the
   platform has always had, so switching this on for one type disturbs nothing else. */

type Stage = {
  id: string;
  name: string;
  order_index: number;
  approver_mode: string;
  approver_ref: string;
  required_approvals: number;
  sla_days: number;
  on_timeout: string;
};

type Definition = {
  id: string;
  entity_type: string;
  name: string;
  description: string;
  enabled: boolean;
  stage_count: number;
  stages: Stage[];
};

type EntityType = { key: string; label: string };

const APPROVER_MODE: { value: string; label: string; hint: string }[] = [
  { value: "role", label: "Anyone with a role", hint: "e.g. Risk Manager" },
  { value: "named_user", label: "A named person", hint: "their email address" },
  { value: "record_owner", label: "The record's owner", hint: "resolved per record" },
  { value: "line_manager", label: "The owner's line manager", hint: "resolved per record" },
];

const TIMEOUT: { value: string; label: string }[] = [
  { value: "escalate", label: "Escalate and keep waiting" },
  { value: "auto_approve", label: "Approve automatically" },
  { value: "block", label: "Block until someone acts" },
];

const BLANK_STAGE = {
  name: "",
  approver_mode: "role",
  approver_ref: "",
  required_approvals: 1,
  sla_days: 0,
  on_timeout: "escalate",
};

export default function WorkflowsPage() {
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [entityTypes, setEntityTypes] = useState<EntityType[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [newType, setNewType] = useState("risk");
  const [newName, setNewName] = useState("");

  const [stage, setStage] = useState({ ...BLANK_STAGE });

  const load = useCallback(() => {
    apiCall<{ items: Definition[] }>("GET", "/workflows/definitions?limit=100")
      .then((page) => {
        setDefinitions(page.items);
        setSelectedId((current) => current ?? page.items[0]?.id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load workflows"));
    apiCall<EntityType[]>("GET", "/workflows/entity-types")
      .then(setEntityTypes)
      .catch(() => {/* the picker falls back to free text */});
  }, []);

  useEffect(load, [load]);

  const definition = definitions.find((d) => d.id === selectedId) ?? null;
  const typeLabel = useMemo(
    () => Object.fromEntries(entityTypes.map((t) => [t.key, t.label])),
    [entityTypes],
  );

  async function createDefinition(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await apiCall<Definition>("POST", "/workflows/definitions", {
        entity_type: newType,
        name: newName || `${typeLabel[newType] ?? newType} approval route`,
        stages: [],
      });
      setSelectedId(created.id);
      setCreating(false);
      setNewName("");
      load();
      toast("Route created — add its stages, then switch it on");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the route");
    } finally {
      setBusy(false);
    }
  }

  async function addStage(e: React.FormEvent) {
    e.preventDefault();
    if (!definition || !stage.name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await apiCall("POST", `/workflows/definitions/${definition.id}/stages`, stage);
      setStage({ ...BLANK_STAGE });
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the stage");
    } finally {
      setBusy(false);
    }
  }

  async function removeStage(target: Stage) {
    if (!(await confirmDialog({ title: "Remove this stage?", message: target.name, danger: true, confirmLabel: "Remove" }))) return;
    try {
      await apiCall("DELETE", `/workflows/stages/${target.id}`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the stage");
    }
  }

  async function toggle() {
    if (!definition) return;
    setBusy(true);
    setError(null);
    try {
      await apiCall("PATCH", `/workflows/definitions/${definition.id}`, {
        enabled: !definition.enabled,
      });
      toast(
        definition.enabled
          ? "Route switched off — this record type reverts to the standard lifecycle"
          : "Route is live for new submissions of this record type",
      );
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the route");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!definition) return;
    if (!(await confirmDialog({ title: `Delete "${definition.name}"?`, message: "Records still routing through it will block the delete.", danger: true, confirmLabel: "Delete" }))) return;
    try {
      await apiCall("DELETE", `/workflows/definitions/${definition.id}`);
      setSelectedId(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the route");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Approval Workflows</h1>
          <p>
            Define your own multi-stage approval route per record type. Each stage raises a real
            approval request, so maker-checker and segregation of duties apply exactly as they do
            today.
          </p>
        </div>
        <button className="btn" onClick={() => setCreating((v) => !v)}>
          <IconPlus width={16} height={16} /> {creating ? "Cancel" : "New route"}
        </button>
      </div>

      {creating && (
        <form className="card card-pad" style={{ marginBottom: 16, display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={createDefinition}>
          <div style={{ width: 260 }}>
            <label className="label">Record type</label>
            <select className="input" value={newType} onChange={(e) => setNewType(e.target.value)}>
              {entityTypes.map((t) => (
                <option key={t.key} value={t.key}>{t.label}</option>
              ))}
            </select>
          </div>
          <div style={{ flex: "1 1 280px" }}>
            <label className="label">Route name</label>
            <input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Risk acceptance sign-off" />
          </div>
          <button className="btn" disabled={busy}>Create</button>
        </form>
      )}

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap", marginBottom: 16 }}>
        <div style={{ width: 380 }}>
          <label className="label">Route</label>
          <select className="input" value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value || null)}>
            {definitions.length === 0 && <option value="">No routes defined</option>}
            {definitions.map((d) => (
              <option key={d.id} value={d.id}>
                {typeLabel[d.entity_type] ?? d.entity_type} — {d.name}{d.enabled ? " (live)" : ""}
              </option>
            ))}
          </select>
        </div>
        {definition && (
          <>
            <button className="btn secondary" type="button" onClick={toggle} disabled={busy}>
              {definition.enabled ? "Switch off" : "Switch on"}
            </button>
            <button className="btn secondary" type="button" onClick={remove} disabled={busy}>
              Delete
            </button>
          </>
        )}
      </div>

      {!definition && (
        <div className="card card-pad muted" style={{ fontSize: 13 }}>
          No approval route defined yet. Until one exists — or while every route is switched off —
          every record type keeps the standard lifecycle it has today, so nothing changes until
          you deliberately switch a route on.
        </div>
      )}

      {definition && (
        <>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="card-head">
              <h3>{definition.name}</h3>
              <span className="sub">
                <Badge tone={definition.enabled ? "low" : "neutral"}>
                  {definition.enabled ? "Live" : "Off"}
                </Badge>
                {" "}· {typeLabel[definition.entity_type] ?? definition.entity_type}
                {" "}· {definition.stage_count} stage(s)
              </span>
            </div>
            {definition.stages.length === 0 && (
              <div className="card-pad muted" style={{ fontSize: 13 }}>
                A route with no stages cannot be switched on. Add the first stage below.
              </div>
            )}
            {definition.stages.length > 0 && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 50 }}>#</th>
                      <th>Stage</th>
                      <th style={{ width: 210 }}>Decided by</th>
                      <th style={{ width: 110 }}>Approvals</th>
                      <th style={{ width: 110 }}>Deadline</th>
                      <th style={{ width: 190 }}>If it lapses</th>
                      <th style={{ width: 90 }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {definition.stages.map((s) => (
                      <tr key={s.id}>
                        <td className="ref">{s.order_index}</td>
                        <td className="cell-title">{s.name}</td>
                        <td className="muted">
                          {APPROVER_MODE.find((m) => m.value === s.approver_mode)?.label ?? s.approver_mode}
                          {s.approver_ref && <> — <b>{s.approver_ref}</b></>}
                        </td>
                        <td className="muted">{s.required_approvals} of the group</td>
                        <td className="muted">{s.sla_days ? `${s.sla_days} days` : "—"}</td>
                        <td className="muted">
                          {TIMEOUT.find((t) => t.value === s.on_timeout)?.label ?? s.on_timeout}
                        </td>
                        <td>
                          <button className="btn secondary sm" onClick={() => removeStage(s)}>Remove</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <form className="card card-pad" onSubmit={addStage}>
            <strong style={{ fontSize: 13 }}>Add a stage</strong>
            <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap", marginTop: 12 }}>
              <div style={{ flex: "1 1 200px" }}>
                <label className="label">Stage name</label>
                <input className="input" value={stage.name} onChange={(e) => setStage({ ...stage, name: e.target.value })} placeholder="e.g. CRO sign-off" required />
              </div>
              <div style={{ width: 220 }}>
                <label className="label">Decided by</label>
                <select className="input" value={stage.approver_mode} onChange={(e) => setStage({ ...stage, approver_mode: e.target.value })}>
                  {APPROVER_MODE.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </div>
              <div style={{ width: 220 }}>
                <label className="label">
                  {APPROVER_MODE.find((m) => m.value === stage.approver_mode)?.hint ?? "Reference"}
                </label>
                <input
                  className="input"
                  value={stage.approver_ref}
                  onChange={(e) => setStage({ ...stage, approver_ref: e.target.value })}
                  disabled={stage.approver_mode === "record_owner" || stage.approver_mode === "line_manager"}
                  placeholder={stage.approver_mode === "role" ? "Role name" : "name@bank.com"}
                />
              </div>
              <div style={{ width: 120 }}>
                <label className="label">Approvals</label>
                <input className="input" type="number" min={1} max={10} value={stage.required_approvals} onChange={(e) => setStage({ ...stage, required_approvals: Number(e.target.value) })} />
              </div>
              <div style={{ width: 130 }}>
                <label className="label">Deadline (days)</label>
                <input className="input" type="number" min={0} max={365} value={stage.sla_days} onChange={(e) => setStage({ ...stage, sla_days: Number(e.target.value) })} />
              </div>
              <div style={{ width: 210 }}>
                <label className="label">If it lapses</label>
                <select className="input" value={stage.on_timeout} onChange={(e) => setStage({ ...stage, on_timeout: e.target.value })}>
                  {TIMEOUT.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
              <button className="btn" disabled={busy || !stage.name.trim()}>Add stage</button>
            </div>
            <p className="muted" style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 0, marginTop: 12 }}>
              &quot;Approvals&quot; is how many distinct people must approve this stage — 2 gives you
              six-eyes on that step alone. The submitter can never be one of them; that rule lives
              in the approvals module and applies to every stage automatically.
            </p>
          </form>
        </>
      )}
    </>
  );
}
