"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type RiskScenario } from "@/lib/api";
import { Badge } from "@/components/badges";
import { confirmDialog, toast } from "@/lib/feedback";

/* The library that drives "Generate risks" on the asset pages. It ships as a built-in
   catalogue that a bank installs into its own editable table, so retuning a base
   likelihood or silencing a scenario that does not apply is a settings change rather
   than a release — and a later platform upgrade adds new scenarios without discarding
   those edits. */

const RULE_LABEL: Record<string, string> = {
  from_criticality: "Asset criticality",
  from_business_value: "Business value of the data",
  from_cia_max: "Worst of C / I / A",
  from_property: "One security property",
  fixed: "Fixed",
};

const CLASS_LABEL: Record<string, string> = {
  information_asset: "Information assets",
  it_asset: "IT assets",
};

type NewScenario = {
  title: string;
  category: string;
  asset_classes: string;
  threat: string;
  vulnerability: string;
  likelihood: number;
  impact_rule: string;
  impact_property: string;
  fixed_impact: number;
  description: string;
  treatment_hint: string;
};

const EMPTY_SCENARIO: NewScenario = {
  title: "",
  category: "",
  asset_classes: "",
  threat: "",
  vulnerability: "",
  likelihood: 3,
  impact_rule: "from_criticality",
  impact_property: "confidentiality",
  fixed_impact: 3,
  description: "",
  treatment_hint: "",
};

function appliesTo(value: string): string {
  const parts = value.split(",").map((v) => v.trim()).filter(Boolean);
  if (!parts.length) return "All assets";
  return parts.map((p) => CLASS_LABEL[p] ?? p).join(", ");
}

export default function ScenarioLibrary() {
  const [rows, setRows] = useState<RiskScenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [category, setCategory] = useState("");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<NewScenario>(EMPTY_SCENARIO);

  const load = useCallback(() => {
    setLoading(true);
    api
      .riskScenarios()
      .then((page) => setRows(page.items))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the library"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  async function install() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const res = await api.installScenarioLibrary();
      setNote(
        res.installed === 0
          ? "Already up to date — nothing new to install."
          : `Installed ${res.installed} scenario${res.installed !== 1 ? "s" : ""}` +
              (res.skipped ? `; ${res.skipped} already present and left untouched` : "") +
              ". Their threats and vulnerabilities were added to the catalogs above.",
      );
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not install the library");
    } finally {
      setBusy(false);
    }
  }

  async function createScenario(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.createRiskScenario({
        ...draft,
        title: draft.title.trim(),
        // Only the rule's own parameter travels; the backend defaults the rest.
        impact_property: draft.impact_rule === "from_property" ? draft.impact_property : "",
        fixed_impact: draft.impact_rule === "fixed" ? draft.fixed_impact : 0,
      });
      setDraft(EMPTY_SCENARIO);
      setAdding(false);
      toast("Scenario added");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the scenario");
    } finally {
      setBusy(false);
    }
  }

  async function removeScenario(row: RiskScenario) {
    const ok = await confirmDialog({
      title: `Delete scenario ${row.reference}?`,
      message:
        "Risks already generated from it are untouched. If it simply does not apply to your bank, switching it off keeps your tuning history.",
      danger: true,
      confirmLabel: "Delete",
    });
    if (!ok) return;
    setError(null);
    try {
      await api.deleteRiskScenario(row.id);
      toast("Scenario deleted");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the scenario");
    }
  }

  async function toggle(row: RiskScenario) {
    setError(null);
    const next = !row.enabled;
    setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, enabled: next } : r)));
    try {
      await api.updateRiskScenario(row.id, { enabled: next });
    } catch (e) {
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, enabled: !next } : r)));
      setError(e instanceof Error ? e.message : "Could not update the scenario");
    }
  }

  async function setLikelihood(row: RiskScenario, likelihood: number) {
    if (!Number.isFinite(likelihood) || likelihood < 1 || likelihood > 5) return;
    setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, likelihood } : r)));
    try {
      await api.updateRiskScenario(row.id, { likelihood });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update the scenario");
      load();
    }
  }

  const categories = useMemo(
    () => [...new Set(rows.map((r) => r.category))].filter(Boolean).sort(),
    [rows],
  );
  const shown = category ? rows.filter((r) => r.category === category) : rows;
  const enabledCount = rows.filter((r) => r.enabled).length;

  return (
    <div className="card">
      <div className="card-head">
        <h3>Risk scenario library</h3>
        <span className="sub">
          {loading ? "Loading…" : `${enabledCount} of ${rows.length} active`}
        </span>
      </div>
      <div className="card-pad">
        <p className="muted" style={{ fontSize: 13, lineHeight: 1.7, marginTop: 0 }}>
          Each scenario is a threat/vulnerability pair that applies to a kind of asset, plus how to
          derive an opening impact from that asset&apos;s own rating. They power the{" "}
          <b>Generate risks</b> button on the asset registers. Switch off what does not apply to
          your bank and tune the base likelihood — the register you generate is only as good as
          this library.
        </p>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 12 }}>
          <div style={{ width: 220 }}>
            <label className="label">Category</label>
            <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">All categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <button className="btn secondary" type="button" onClick={install} disabled={busy}>
            {busy ? "Working…" : rows.length ? "Update from built-in library" : "Install built-in library"}
          </button>
          <button className="btn secondary" type="button" onClick={() => setAdding((v) => !v)} disabled={busy}>
            {adding ? "Cancel" : "New scenario"}
          </button>
        </div>

        {adding && (
          <form onSubmit={createScenario} className="card card-pad" style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <div style={{ flex: "2 1 260px" }}>
                <label className="label">Title (use {"{asset}"} where the asset name goes)</label>
                <input className="input" required value={draft.title}
                  onChange={(e) => setDraft((p) => ({ ...p, title: e.target.value }))}
                  placeholder="Unauthorised change to {asset}" />
              </div>
              <div style={{ flex: "1 1 160px" }}>
                <label className="label">Category</label>
                <input className="input" value={draft.category}
                  onChange={(e) => setDraft((p) => ({ ...p, category: e.target.value }))}
                  placeholder="Cyber Security" />
              </div>
              <div style={{ flex: "0 1 180px" }}>
                <label className="label">Applies to</label>
                <select className="input" value={draft.asset_classes}
                  onChange={(e) => setDraft((p) => ({ ...p, asset_classes: e.target.value }))}>
                  <option value="">All assets</option>
                  <option value="information_asset">Information assets</option>
                  <option value="it_asset">IT assets</option>
                </select>
              </div>
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
              <div style={{ flex: "1 1 200px" }}>
                <label className="label">Threat</label>
                <input className="input" required value={draft.threat}
                  onChange={(e) => setDraft((p) => ({ ...p, threat: e.target.value }))}
                  placeholder="Unauthorised change" />
              </div>
              <div style={{ flex: "1 1 200px" }}>
                <label className="label">Vulnerability</label>
                <input className="input" required value={draft.vulnerability}
                  onChange={(e) => setDraft((p) => ({ ...p, vulnerability: e.target.value }))}
                  placeholder="No change control on production" />
              </div>
              <div style={{ flex: "0 0 110px" }}>
                <label className="label">Likelihood (1–5)</label>
                <input className="input" type="number" min={1} max={5} value={draft.likelihood}
                  onChange={(e) => setDraft((p) => ({ ...p, likelihood: Number(e.target.value) || 3 }))} />
              </div>
              <div style={{ flex: "0 1 190px" }}>
                <label className="label">Impact from</label>
                <select className="input" value={draft.impact_rule}
                  onChange={(e) => setDraft((p) => ({ ...p, impact_rule: e.target.value }))}>
                  {Object.entries(RULE_LABEL).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </div>
              {draft.impact_rule === "from_property" && (
                <div style={{ flex: "0 1 160px" }}>
                  <label className="label">Property</label>
                  <select className="input" value={draft.impact_property}
                    onChange={(e) => setDraft((p) => ({ ...p, impact_property: e.target.value }))}>
                    <option value="confidentiality">Confidentiality</option>
                    <option value="integrity">Integrity</option>
                    <option value="availability">Availability</option>
                  </select>
                </div>
              )}
              {draft.impact_rule === "fixed" && (
                <div style={{ flex: "0 0 110px" }}>
                  <label className="label">Impact (1–5)</label>
                  <input className="input" type="number" min={1} max={5} value={draft.fixed_impact}
                    onChange={(e) => setDraft((p) => ({ ...p, fixed_impact: Number(e.target.value) || 3 }))} />
                </div>
              )}
            </div>
            <div style={{ marginTop: 10 }}>
              <label className="label">Suggested treatment (optional)</label>
              <input className="input" value={draft.treatment_hint}
                onChange={(e) => setDraft((p) => ({ ...p, treatment_hint: e.target.value }))}
                placeholder="What a generated risk should propose as its treatment" />
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
              <button className="btn" disabled={busy || !draft.title.trim()}>Create scenario</button>
            </div>
          </form>
        )}

        {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}
        {note && <div className="muted" style={{ fontSize: 12.5, marginBottom: 10 }}>{note}</div>}

        {!loading && rows.length === 0 && (
          <div className="muted" style={{ fontSize: 13 }}>
            No scenarios yet. Install the built-in catalogue to get started — it also seeds the
            threat and vulnerability catalogs above.
          </div>
        )}

        {shown.length > 0 && (
          <div className="table-wrap" style={{ maxHeight: 460, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Ref</th>
                  <th>Scenario</th>
                  <th style={{ width: 140 }}>Applies to</th>
                  <th style={{ width: 150 }}>Impact from</th>
                  <th style={{ width: 90 }}>Likelihood</th>
                  <th style={{ width: 80 }}>Active</th>
                  <th style={{ width: 40 }} />
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr key={row.id} style={{ opacity: row.enabled ? 1 : 0.55 }}>
                    <td className="ref">{row.reference}</td>
                    <td>
                      <div className="cell-title">{row.title}</div>
                      <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                        {row.threat} → {row.vulnerability}
                      </div>
                    </td>
                    <td className="muted" style={{ fontSize: 12.5 }}>{appliesTo(row.asset_classes)}</td>
                    <td className="muted" style={{ fontSize: 12.5 }}>
                      {RULE_LABEL[row.impact_rule] ?? row.impact_rule}
                      {row.impact_rule === "from_property" && row.impact_property
                        ? ` (${row.impact_property})`
                        : ""}
                    </td>
                    <td>
                      <input
                        className="input" type="number" min={1} max={5}
                        style={{ width: 58, padding: "4px 6px", fontSize: 13 }}
                        value={row.likelihood}
                        onChange={(e) => setLikelihood(row, Number(e.target.value))}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn secondary sm"
                        style={{ padding: "2px 8px", fontSize: 12 }}
                        onClick={() => toggle(row)}
                      >
                        {row.enabled ? <Badge tone="low">On</Badge> : <Badge tone="neutral" plain>Off</Badge>}
                      </button>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn secondary sm"
                        style={{ padding: "2px 8px", fontSize: 12 }}
                        title="Delete scenario"
                        onClick={() => removeScenario(row)}
                      >
                        ✕
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
