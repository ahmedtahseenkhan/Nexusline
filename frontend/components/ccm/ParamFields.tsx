"use client";

/* A parameter form built from server specs (check parameters, connector settings). */

import { Field, TextArea, TextInput, Toggle } from "@/components/fields";
import type { ParamSpec, ParamValues } from "@/lib/ccm";

function asText(v: unknown, kind: string): string {
  if (v === undefined || v === null) return "";
  if (kind === "list" && Array.isArray(v)) return v.join("\n");
  if (kind === "json" && typeof v === "object") return JSON.stringify(v, null, 2);
  return String(v);
}

export default function ParamFields({
  specs,
  values,
  onChange,
}: {
  specs: ParamSpec[];
  values: ParamValues;
  onChange: (name: string, value: unknown) => void;
}) {
  if (!specs.length) return null;
  return (
    <>
      {specs.map((p) => {
        const v = values[p.name];
        let control;
        if (p.kind === "bool") {
          control = <Toggle checked={Boolean(v)} onChange={(x) => onChange(p.name, x)} label={p.label} />;
        } else if (p.kind === "select") {
          control = (
            <select className="select" value={asText(v, p.kind)} onChange={(e) => onChange(p.name, e.target.value)}>
              {!p.required && <option value="">Not set</option>}
              {p.options.map((o) => (
                <option key={o} value={o}>{o.replace(/_/g, " ")}</option>
              ))}
            </select>
          );
        } else if (p.kind === "list" || p.kind === "textarea" || p.kind === "json") {
          control = (
            <TextArea
              value={asText(v, p.kind)}
              onChange={(x) => onChange(p.name, x)}
              rows={p.kind === "json" ? 4 : 3}
              placeholder={p.kind === "list" ? "One per line" : p.kind === "json" ? "{ }" : undefined}
            />
          );
        } else {
          control = (
            <TextInput value={asText(v, p.kind)} onChange={(x) => onChange(p.name, x)} type={p.kind === "number" ? "number" : "text"} />
          );
        }
        return (
          <Field key={p.name} label={p.kind === "bool" ? "" : p.label} required={p.required} help={p.help || undefined}>
            {control}
          </Field>
        );
      })}
    </>
  );
}
