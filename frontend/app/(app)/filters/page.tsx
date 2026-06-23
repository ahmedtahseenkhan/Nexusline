"use client";

import { useEffect, useState } from "react";
import { api, type FieldInfo, type FilterResults, type SavedFilter } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

const OP_LABEL: Record<string, string> = {
  eq: "equals", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤",
  contains: "contains", overdue: "is overdue", is_true: "is true", is_false: "is false", not_empty: "is set",
};
type Cond = { field: string; operator: string; value: string };

export default function FiltersPage() {
  const [filters, setFilters] = useState<SavedFilter[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [operators, setOperators] = useState<string[]>([]);
  const [fields, setFields] = useState<FieldInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, FilterResults>>({});

  const [model, setModel] = useState("risk");
  const [name, setName] = useState("");
  const [matchMode, setMatchMode] = useState("all");
  const [shared, setShared] = useState(true);
  const [conds, setConds] = useState<Cond[]>([{ field: "", operator: "eq", value: "" }]);

  async function loadFilters() {
    setFilters(await api.filters().catch(() => []));
  }
  useEffect(() => {
    Promise.all([api.statusRuleModels(), api.statusRuleOperators()]).then(([m, o]) => { setModels(m); setOperators(o); });
    loadFilters();
  }, []);
  useEffect(() => {
    api.filterFields(model).then((f) => {
      setFields(f);
      setConds((c) => c.map((x) => ({ ...x, field: x.field || f[0]?.key || "" })));
    }).catch(() => setFields([]));
  }, [model]);

  function setCond(i: number, patch: Partial<Cond>) {
    setConds((c) => c.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createFilter({ name, model, match_mode: matchMode, shared, conditions: conds.filter((c) => c.field) });
      setName("");
      setConds([{ field: fields[0]?.key || "", operator: "eq", value: "" }]);
      await loadFilters();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }
  async function run(id: string) {
    const res = await api.runFilter(id);
    setResults((r) => ({ ...r, [id]: res }));
  }
  async function remove(id: string) {
    await api.deleteFilter(id).catch((e) => setError(e instanceof Error ? e.message : "Delete failed"));
    await loadFilters();
  }

  const needsValue = (op: string) => !["overdue", "is_true", "is_false", "not_empty"].includes(op);

  return (
    <>
      <div className="page-head">
        <h1>Saved Filters</h1>
        <p>Build reusable, named queries over any module and run them on demand.</p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 12 }}>
          <div style={{ flex: "1 1 200px" }}>
            <label className="label">Filter name</label>
            <input className="input" required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Critical open risks" />
          </div>
          <div style={{ flex: "0 0 140px" }}>
            <label className="label">Module</label>
            <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div style={{ flex: "0 0 120px" }}>
            <label className="label">Match</label>
            <select className="input" value={matchMode} onChange={(e) => setMatchMode(e.target.value)}>
              <option value="all">all (AND)</option>
              <option value="any">any (OR)</option>
            </select>
          </div>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 13, paddingBottom: 9 }}>
            <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} /> Shared
          </label>
        </div>

        {conds.map((c, i) => {
          const sf = fields.find((f) => f.key === c.field);
          return (
            <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "flex-end" }}>
              <div style={{ flex: "0 0 190px" }}>
                {i === 0 && <label className="label">Field</label>}
                <select className="input" value={c.field} onChange={(e) => setCond(i, { field: e.target.value })}>
                  {fields.map((f) => <option key={f.key} value={f.key}>{f.label} ({f.type})</option>)}
                </select>
              </div>
              <div style={{ flex: "0 0 130px" }}>
                {i === 0 && <label className="label">Condition</label>}
                <select className="input" value={c.operator} onChange={(e) => setCond(i, { operator: e.target.value })}>
                  {operators.map((o) => <option key={o} value={o}>{OP_LABEL[o] || o}</option>)}
                </select>
              </div>
              <div style={{ flex: "1 1 130px" }}>
                {i === 0 && <label className="label">Value</label>}
                {needsValue(c.operator) ? (
                  sf?.type === "enum" && sf.options ? (
                    <select className="input" value={c.value} onChange={(e) => setCond(i, { value: e.target.value })}>
                      <option value="">—</option>
                      {sf.options.map((o) => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : (
                    <input className="input" value={c.value} onChange={(e) => setCond(i, { value: e.target.value })} placeholder={sf?.type === "date" ? "YYYY-MM-DD" : ""} />
                  )
                ) : <input className="input" disabled value="—" />}
              </div>
              <button type="button" className="btn secondary sm" onClick={() => setConds((cs) => cs.filter((_, j) => j !== i))} disabled={conds.length === 1}>×</button>
            </div>
          );
        })}
        <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
          <button type="button" className="btn secondary sm" onClick={() => setConds((c) => [...c, { field: fields[0]?.key || "", operator: "eq", value: "" }])}>+ Condition</button>
          <button className="btn"><IconPlus width={16} height={16} /> Save filter</button>
        </div>
      </form>

      {filters.length === 0 && <div className="card card-pad"><div className="empty"><h3>No saved filters</h3><p>Create one above.</p></div></div>}

      <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
        {filters.map((f) => (
          <div className="card" key={f.id}>
            <div className="card-head">
              <h3>{f.name}</h3>
              {f.shared ? <Badge tone="info">shared</Badge> : <Badge tone="neutral">personal</Badge>}
            </div>
            <div className="card-pad">
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                <Badge tone="neutral">{f.model}</Badge> · match {f.match_mode}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
                {f.conditions.map((c, i) => (
                  <code key={i} style={{ fontSize: 12 }}>{c.field} {OP_LABEL[c.operator] || c.operator} {c.value}</code>
                ))}
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn sm" onClick={() => run(f.id)}>Run</button>
                <button className="btn secondary sm" onClick={() => remove(f.id)}>Delete</button>
              </div>
              {results[f.id] && (
                <div style={{ marginTop: 12 }}>
                  <b style={{ fontSize: 13 }}>{results[f.id].count} of {results[f.id].total} match</b>
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap", marginTop: 6 }}>
                    {results[f.id].matches.map((m) => <Badge key={m.id} tone="low">{m.label}</Badge>)}
                    {results[f.id].count === 0 && <span className="muted" style={{ fontSize: 12 }}>No records match</span>}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
