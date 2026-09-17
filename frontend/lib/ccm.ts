/* Continuous control monitoring (phase 4D): the shapes the Integrations & CCM page reads,
   and the pure helpers its forms share. Specs come from the server
   (GET /ccm/check-types, GET /ccm/connector-types), so a new check needs no UI change. */

export type ParamSpec = {
  name: string;
  label: string;
  /** text | number | list | bool | select | textarea | json */
  kind: string;
  required: boolean;
  default: unknown;
  help: string;
  options: string[];
};

export type CheckType = {
  key: string;
  label: string;
  group: string;
  description: string;
  connector_types: string[];
  /** connector | file | connector_or_file | none */
  input: string;
  params: ParamSpec[];
  pass_criterion: string;
  population: string;
};

export type ConnectorKind = {
  connector_type: string;
  /** ldap | http | file | push */
  kind: string;
  config_fields: ParamSpec[];
  secret_fields: ParamSpec[];
  note: string;
};

export type RunRow = {
  id: string;
  test_id: string;
  run_date: string | null;
  result: string;
  findings: string;
  evidence_ref: string;
  pass_rate: number;
  created_at: string;
  source?: string;
  started_at?: string | null;
  duration_ms?: number | null;
  population_size?: number | null;
  exceptions_count?: number | null;
  metric_value?: number | null;
  error_message?: string;
  evidence_id?: string | null;
  issue_id?: string | null;
  kri_measurement_id?: string | null;
};

export type RunDetail = RunRow & {
  exceptions_sample: Record<string, unknown>[];
  details: Record<string, unknown>;
  test_reference: string;
  evidence_title: string | null;
  issue_reference: string | null;
};

export type RunNowResult = { result: string; message: string; run: RunDetail | null; issue_reference: string; kri_note: string };

export type ParamValues = Record<string, unknown>;

/** The value a form starts with: what is stored, else the spec's default. */
export function initialParams(specs: ParamSpec[], stored: ParamValues | null | undefined): ParamValues {
  const out: ParamValues = {};
  for (const p of specs) {
    const v = stored?.[p.name];
    out[p.name] = v !== undefined && v !== null ? v : p.default ?? (p.kind === "bool" ? false : "");
  }
  return out;
}

/** What is sent: lists split into lines, numbers as numbers, blanks dropped, JSON parsed.
 *  Returns the problems (a JSON field that doesn't parse) instead of guessing. */
export function paramsPayload(specs: ParamSpec[], values: ParamValues): { params: ParamValues; errors: string[] } {
  const params: ParamValues = {};
  const errors: string[] = [];
  for (const p of specs) {
    const v = values[p.name];
    if (v === undefined || v === null || v === "") continue;
    if (p.kind === "list") {
      const items = Array.isArray(v) ? v.map(String) : String(v).split(/\r?\n|,/);
      const clean = items.map((x) => x.trim()).filter(Boolean);
      if (clean.length) params[p.name] = clean;
    } else if (p.kind === "number") {
      const n = Number(v);
      if (Number.isNaN(n)) errors.push(`${p.label}: must be a number.`);
      else params[p.name] = n;
    } else if (p.kind === "json") {
      if (typeof v === "object") params[p.name] = v;
      else {
        try {
          params[p.name] = JSON.parse(String(v));
        } catch {
          errors.push(`${p.label}: not valid JSON.`);
        }
      }
    } else if (p.kind === "bool") {
      params[p.name] = Boolean(v);
    } else {
      params[p.name] = v;
    }
  }
  return { params, errors };
}

/** "1.2 s", "350 ms". */
export function durationText(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export const RUN_SOURCE_LABEL: Readonly<Record<string, string>> = {
  manual: "Recorded by hand",
  scheduled: "Scheduled",
  run_now: "Run now",
  upload: "Uploaded file",
  push: "Monitoring feed",
};

export const KRI_METRIC_LABEL: Readonly<Record<string, string>> = {
  exceptions: "Number of exceptions",
  exception_percent: "Exceptions as % of population",
  population: "Population size",
  pass_rate: "Pass rate %",
  value: "Checked value",
};
