"use client";

/* Management for the asset classification scheme: axes (Confidentiality, Integrity…)
   and the graded values inside each. The default CIA scheme is seeded per organisation;
   a bank with its own methodology reshapes it here. Values attach to information assets
   on the asset form ("Scheme classification"). */

import { useCallback, useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";

export type ClassificationValue = {
  id: string;
  name: string;
  criteria: string;
  value: number;
  type_id: string;
};

export type ClassificationType = {
  id: string;
  name: string;
  description: string;
  classifications: ClassificationValue[];
};

const ENDPOINT = "/asset-classification-types";

export default function ClassificationSchemes() {
  const [types, setTypes] = useState<ClassificationType[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newAxis, setNewAxis] = useState("");
  // Per-axis add-value drafts, keyed by type id.
  const [drafts, setDrafts] = useState<Record<string, { name: string; value: string; criteria: string }>>({});

  const load = useCallback(async () => {
    try {
      setTypes(await apiCall<ClassificationType[]>("GET", ENDPOINT));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(fn: () => Promise<void>, done?: string) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      if (done) toast(done);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  function addAxis(e: React.FormEvent) {
    e.preventDefault();
    const name = newAxis.trim();
    if (!name) return;
    run(async () => {
      await apiCall<ClassificationType>("POST", ENDPOINT, { name, description: "" });
      setNewAxis("");
    }, "Axis added");
  }

  async function removeAxis(t: ClassificationType) {
    const ok = await confirmDialog({
      title: `Delete axis "${t.name}"?`,
      message: `Its ${t.classifications.length} value(s) are removed and detached from every asset.`,
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    run(() => apiCall<void>("DELETE", `${ENDPOINT}/${t.id}`), "Axis deleted");
  }

  function addValue(t: ClassificationType, e: React.FormEvent) {
    e.preventDefault();
    const d = drafts[t.id];
    if (!d?.name.trim()) return;
    run(async () => {
      await apiCall<ClassificationValue>("POST", `${ENDPOINT}/${t.id}/classifications`, {
        name: d.name.trim(),
        value: Number(d.value) || 1,
        criteria: d.criteria.trim(),
      });
      setDrafts((p) => ({ ...p, [t.id]: { name: "", value: "", criteria: "" } }));
    }, "Value added");
  }

  async function removeValue(v: ClassificationValue) {
    const ok = await confirmDialog({
      title: `Delete value "${v.name}"?`,
      message: "Assets classified with it simply lose this classification.",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    run(() => apiCall<void>("DELETE", `${ENDPOINT}/classifications/${v.id}`), "Value deleted");
  }

  function draftOf(id: string) {
    return drafts[id] ?? { name: "", value: "", criteria: "" };
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 18 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>Classification schemes</h2>
        <span className="muted" style={{ fontSize: 12.5 }}>
          Axes and graded values — the “Scheme classification” picker on information assets.
        </span>
      </div>

      {error && <div className="error" style={{ margin: "10px 0" }}>{error}</div>}

      <form onSubmit={addAxis} style={{ display: "flex", gap: 8, alignItems: "flex-end", margin: "12px 0" }}>
        <div style={{ flex: "0 1 260px" }}>
          <label className="label">New axis</label>
          <input
            className="input"
            value={newAxis}
            onChange={(e) => setNewAxis(e.target.value)}
            placeholder="e.g. Regulatory sensitivity"
          />
        </div>
        <button className="btn" disabled={busy || !newAxis.trim()}>Add axis</button>
      </form>

      {types.length === 0 && (
        <div className="muted" style={{ fontSize: 13 }}>No axes yet — add one above.</div>
      )}

      {types.map((t) => (
        <div key={t.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "10px 12px", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <strong>{t.name}</strong>
            <span className="muted" style={{ fontSize: 12 }}>{t.description}</span>
            <button
              className="btn secondary sm"
              type="button"
              style={{ marginLeft: "auto" }}
              disabled={busy}
              onClick={() => removeAxis(t)}
            >
              Delete axis
            </button>
          </div>

          {t.classifications.length > 0 && (
            <div className="table-wrap" style={{ marginBottom: 8 }}>
              <table>
                <thead>
                  <tr>
                    <th style={{ width: 180 }}>Value</th>
                    <th style={{ width: 80 }}>Grade</th>
                    <th>Criteria</th>
                    <th style={{ width: 90 }} />
                  </tr>
                </thead>
                <tbody>
                  {t.classifications.map((v) => (
                    <tr key={v.id}>
                      <td>{v.name}</td>
                      <td className="ref">{v.value}</td>
                      <td className="muted" style={{ fontSize: 12.5 }}>{v.criteria || "—"}</td>
                      <td style={{ textAlign: "right" }}>
                        <button className="btn secondary sm" type="button" disabled={busy} onClick={() => removeValue(v)}>
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <form onSubmit={(e) => addValue(t, e)} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ flex: "0 1 180px" }}>
              <label className="label">Value name</label>
              <input
                className="input"
                value={draftOf(t.id).name}
                onChange={(e) => setDrafts((p) => ({ ...p, [t.id]: { ...draftOf(t.id), name: e.target.value } }))}
                placeholder="Restricted"
              />
            </div>
            <div style={{ flex: "0 0 90px" }}>
              <label className="label">Grade</label>
              <input
                className="input"
                type="number"
                step="0.5"
                value={draftOf(t.id).value}
                onChange={(e) => setDrafts((p) => ({ ...p, [t.id]: { ...draftOf(t.id), value: e.target.value } }))}
                placeholder="4"
              />
            </div>
            <div style={{ flex: "2 1 240px" }}>
              <label className="label">Criteria</label>
              <input
                className="input"
                value={draftOf(t.id).criteria}
                onChange={(e) => setDrafts((p) => ({ ...p, [t.id]: { ...draftOf(t.id), criteria: e.target.value } }))}
                placeholder="When does data belong in this band?"
              />
            </div>
            <button className="btn sm" disabled={busy || !draftOf(t.id).name.trim()}>Add value</button>
          </form>
        </div>
      ))}
    </div>
  );
}
