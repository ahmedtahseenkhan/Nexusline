"use client";

import { useCallback, useEffect, useState } from "react";
import { api, apiCall, type FieldInfo, type FilterResults, type SavedFilter } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import { Badge } from "@/components/badges";
import { IconPlus } from "@/components/icons";

const OP_LABEL: Record<string, string> = {
  eq: "equals", ne: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤",
  contains: "contains", overdue: "is overdue", is_true: "is true", is_false: "is false", not_empty: "is set",
};
type Cond = { field: string; operator: string; value: string };

export default function FiltersPage() {
  const [models, setModels] = useState<string[]>([]);
  const [operators, setOperators] = useState<string[]>([]);
  const [fields, setFields] = useState<FieldInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [filterModel, setFilterModel] = useState("");
  const [ran, setRan] = useState<{ filter: SavedFilter; results: FilterResults } | null>(null);

  const [model, setModel] = useState("risk");
  const [name, setName] = useState("");
  const [matchMode, setMatchMode] = useState("all");
  const [shared, setShared] = useState(true);
  const [conds, setConds] = useState<Cond[]>([{ field: "", operator: "eq", value: "" }]);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchFilters = useCallback((qs: string) => apiCall<PagedList<SavedFilter>>("GET", `/filters?${qs}`), []);

  useEffect(() => {
    Promise.all([api.statusRuleModels(), api.statusRuleOperators()]).then(([m, o]) => { setModels(m); setOperators(o); }).catch(() => {});
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
      reload();
      toast("Filter saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }
  async function run(f: SavedFilter) {
    try {
      const res = await api.runFilter(f.id);
      setRan({ filter: f, results: res });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    }
  }
  async function remove(f: SavedFilter) {
    if (!(await confirmDialog({ title: `Delete filter "${f.name}"?`, danger: true }))) return;
    try {
      await api.deleteFilter(f.id);
      if (ran?.filter.id === f.id) setRan(null);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const needsValue = (op: string) => !["overdue", "is_true", "is_false", "not_empty"].includes(op);

  const columns: Column<SavedFilter>[] = [
    { key: "name", header: "Name", sortable: true, render: (f) => <span className="cell-title">{f.name}</span> },
    { key: "model", header: "Module", sortable: true, render: (f) => <Badge tone="neutral">{f.model}</Badge> },
    { key: "match_mode", header: "Match", render: (f) => <span className="muted">{f.match_mode}</span> },
    { key: "conditions", header: "Conditions", render: (f) => <span className="muted">{f.conditions.map((c) => `${c.field} ${OP_LABEL[c.operator] || c.operator} ${c.value}`).join("; ") || "—"}</span> },
    { key: "shared", header: "Visibility", render: (f) => (f.shared ? <Badge tone="info">shared</Badge> : <Badge tone="neutral">personal</Badge>) },
    {
      key: "actions", header: "", render: (f) => (
        <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
          <button className="btn sm" onClick={() => run(f)}>Run</button>
          <button className="btn secondary sm" onClick={() => remove(f)}>Delete</button>
        </div>
      ),
    },
  ];

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

      <DataTable<SavedFilter>
        columns={columns}
        fetcher={fetchFilters}
        rowKey={(f) => f.id}
        searchPlaceholder="Search filters by name…"
        filters={{ model: filterModel || undefined }}
        toolbarRight={
          <select className="input" style={{ maxWidth: 180 }} value={filterModel} onChange={(e) => setFilterModel(e.target.value)}>
            <option value="">All modules</option>
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        }
        emptyMessage="No saved filters yet. Create one above."
        refreshKey={refreshKey}
      />

      {ran && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="card-head row-between">
            <div>
              <h3>{ran.filter.name}</h3>
              <span className="sub">{ran.results.count} of {ran.results.total} match</span>
            </div>
            <button className="btn secondary sm" onClick={() => setRan(null)}>Close</button>
          </div>
          <div className="card-pad">
            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
              {ran.results.matches.map((m) => <Badge key={m.id} tone="low">{m.label}</Badge>)}
              {ran.results.count === 0 && <span className="muted" style={{ fontSize: 12 }}>No records match</span>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
