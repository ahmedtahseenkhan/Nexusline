"use client";

import { useCallback, useEffect, useState } from "react";
import { api, apiCall, type FieldInfo, type StatusRule } from "@/lib/api";
import { type Page as PagedList } from "@/lib/list";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import { IconPlus } from "@/components/icons";

const OP_LABEL: Record<string, string> = {
  eq: "equals", ne: "not equals", gt: ">", gte: "≥", lt: "<", lte: "≤",
  contains: "contains", overdue: "is overdue", is_true: "is true", is_false: "is false", not_empty: "is set",
};

export default function StatusRulesPage() {
  const [models, setModels] = useState<string[]>([]);
  const [operators, setOperators] = useState<string[]>([]);
  const [fields, setFields] = useState<FieldInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [filterModel, setFilterModel] = useState("");
  const [ruleCount, setRuleCount] = useState(0);

  const [model, setModel] = useState("risk");
  const [field, setField] = useState("");
  const [operator, setOperator] = useState("gte");
  const [value, setValue] = useState("");
  const [label, setLabel] = useState("");
  const [color, setColor] = useState("#dc2626");

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchRules = useCallback((qs: string) => apiCall<PagedList<StatusRule>>("GET", `/status-rules?${qs}`), []);

  useEffect(() => {
    Promise.all([api.statusRuleModels(), api.statusRuleOperators()]).then(([m, o]) => {
      setModels(m); setOperators(o);
    }).catch(() => {});
    // Count rules for the chosen module so a new rule's priority is appended.
    api.statusRules(model).then((r) => setRuleCount(r.length)).catch(() => setRuleCount(0));
  }, [model]);
  useEffect(() => {
    api.statusRuleFields(model).then((f) => { setFields(f); setField(f[0]?.key || ""); }).catch(() => setFields([]));
  }, [model]);

  const selField = fields.find((f) => f.key === field);
  const needsValue = !["overdue", "is_true", "is_false", "not_empty"].includes(operator);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createStatusRule({ model, field, operator, value, label, color, priority: ruleCount + 1 });
      setLabel(""); setValue("");
      reload();
      setRuleCount((c) => c + 1);
      toast("Rule created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }
  async function remove(r: StatusRule) {
    if (!(await confirmDialog({ title: `Delete rule "${r.label}"?`, danger: true }))) return;
    try {
      await api.deleteStatusRule(r.id);
      reload();
      toast("Deleted");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  const columns: Column<StatusRule>[] = [
    { key: "model", header: "Module", sortable: true, render: (r) => <span className="muted" style={{ textTransform: "capitalize" }}>{r.model}</span> },
    { key: "label", header: "Label", sortable: true, render: (r) => <span style={{ background: `${r.color}1a`, color: r.color, border: `1px solid ${r.color}55`, borderRadius: 99, padding: "2px 10px", fontSize: 12, fontWeight: 600 }}>{r.label}</span> },
    { key: "condition", header: "Condition", render: (r) => <code style={{ fontSize: 12 }}>{r.field} {OP_LABEL[r.operator] || r.operator} {r.value}</code> },
    { key: "priority", header: "Priority", sortable: true, align: "center", render: (r) => <span className="muted">{r.priority}</span> },
    { key: "actions", header: "", render: (r) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => remove(r)}>Delete</button></div> },
  ];

  return (
    <>
      <div className="page-head">
        <h1>Dynamic Status Rules</h1>
        <p>Auto-apply colored labels to records when a field meets a condition.</p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ flex: "0 0 140px" }}>
            <label className="label">Module</label>
            <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div style={{ flex: "0 0 180px" }}>
            <label className="label">Field</label>
            <select className="input" value={field} onChange={(e) => setField(e.target.value)}>
              {fields.map((f) => <option key={f.key} value={f.key}>{f.label} ({f.type})</option>)}
            </select>
          </div>
          <div style={{ flex: "0 0 140px" }}>
            <label className="label">Condition</label>
            <select className="input" value={operator} onChange={(e) => setOperator(e.target.value)}>
              {operators.map((o) => <option key={o} value={o}>{OP_LABEL[o] || o}</option>)}
            </select>
          </div>
          {needsValue && (
            <div style={{ flex: "0 0 130px" }}>
              <label className="label">Value</label>
              {selField?.type === "enum" && selField.options ? (
                <select className="input" value={value} onChange={(e) => setValue(e.target.value)}>
                  <option value="">—</option>
                  {selField.options.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <input className="input" value={value} onChange={(e) => setValue(e.target.value)} placeholder={selField?.type === "date" ? "YYYY-MM-DD" : ""} />
              )}
            </div>
          )}
          <div style={{ flex: "1 1 150px" }}>
            <label className="label">Label</label>
            <input className="input" required value={label} onChange={(e) => setLabel(e.target.value)} placeholder="High Exposure" />
          </div>
          <div style={{ flex: "0 0 56px" }}>
            <label className="label">Color</label>
            <input type="color" className="input" style={{ padding: 2, height: 38 }} value={color} onChange={(e) => setColor(e.target.value)} />
          </div>
          <button className="btn"><IconPlus width={16} height={16} /> Add</button>
        </div>
      </form>

      <DataTable<StatusRule>
        columns={columns}
        fetcher={fetchRules}
        rowKey={(r) => r.id}
        searchPlaceholder="Search rules by label or field…"
        filters={{ model: filterModel || undefined }}
        toolbarRight={
          <select className="input" style={{ maxWidth: 180 }} value={filterModel} onChange={(e) => setFilterModel(e.target.value)}>
            <option value="">All modules</option>
            {models.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        }
        emptyMessage="No rules yet. Create one above."
        refreshKey={refreshKey}
      />
    </>
  );
}
