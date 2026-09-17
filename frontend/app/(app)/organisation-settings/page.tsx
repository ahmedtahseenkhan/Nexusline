"use client";

/* Settings → Organisation: the locale every page formats with (currency, timezone, date
   format, fiscal year, phone country), how long archived records are kept, and — for
   administrators — Security: MFA by role and segregation-of-duties readiness.
   Anyone signed in can read these; changing them needs `settings:manage` (Admin). */

import { useCallback, useEffect, useMemo, useState } from "react";
import AsyncSelect, { type Option as AsyncOption } from "@/components/AsyncSelect";
import MfaPolicySettings from "@/components/MfaPolicySettings";
import SegregationOfDutiesSettings from "@/components/SegregationOfDutiesSettings";
import { Field, NumberInput, Select } from "@/components/fields";
import { toast } from "@/lib/feedback";
import {
  DATE_FORMATS,
  DEFAULT_TENANT_SETTINGS,
  MONTHS,
  currencyOptions,
  formatDate,
  formatDateTime,
  formatMoney,
  timezoneOffset,
  type DateFormat,
  type TenantSettings,
} from "@/lib/format";
import {
  SETTINGS_MANAGE_PERMISSION,
  cachedLookupList,
  organisationSettingsOptions,
  updateOrganisationSettings,
} from "@/lib/masterData";
import { useHasPermission, useTenantSettings } from "@/lib/tenantSettings";

const FIELDS = [
  "currency",
  "timezone",
  "date_format",
  "fiscal_year_start_month",
  "phone_country",
  "retention_days",
] as const;

const MONTH_OPTIONS = MONTHS.map((m, i) => ({ value: String(i + 1), label: m }));

export default function OrganisationSettingsPage() {
  const { settings, loading, reload } = useTenantSettings();
  const canEdit = useHasPermission(SETTINGS_MANAGE_PERMISSION);
  const [form, setForm] = useState<TenantSettings>(settings);
  const [timezones, setTimezones] = useState<string[]>([]);
  const [bounds, setBounds] = useState({ min: 30, max: 3650 });
  const [countries, setCountries] = useState<{ value: string; label: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setForm(settings), [settings]);

  useEffect(() => {
    organisationSettingsOptions()
      .then((o) => {
        setTimezones(o.timezones);
        setBounds({ min: o.retention_min_days, max: o.retention_max_days });
      })
      .catch(() => {});
    cachedLookupList("country")
      .then((rows) =>
        setCountries(
          rows
            .filter((r) => r.active && /^[a-z]{2}$/.test(r.value))
            .map((r) => ({ value: r.value.toUpperCase(), label: `${r.label} (${r.value.toUpperCase()})` }))
            .sort((a, b) => a.label.localeCompare(b.label)),
        ),
      )
      .catch(() => {});
  }, []);

  const set = <K extends keyof TenantSettings>(k: K, v: TenantSettings[K]) => setForm((f) => ({ ...f, [k]: v }));

  const changed = useMemo(
    () => FIELDS.filter((k) => form[k] !== settings[k]),
    [form, settings],
  );

  const searchTimezones = useCallback(
    async (q: string): Promise<AsyncOption[]> => {
      const needle = q.trim().toLowerCase().replace(/\s+/g, "_");
      const list = timezones.length ? timezones : [DEFAULT_TENANT_SETTINGS.timezone];
      return list
        .filter((tz) => !needle || tz.toLowerCase().includes(needle))
        .slice(0, 60)
        .map((tz) => ({ value: tz, label: tz.replace(/_/g, " "), sub: timezoneOffset(tz) }));
    },
    [timezones],
  );

  const phoneOptions = useMemo(() => {
    const opts = countries.length ? countries : [{ value: "PK", label: "Pakistan (PK)" }];
    return opts.some((o) => o.value === form.phone_country)
      ? opts
      : [...opts, { value: form.phone_country, label: form.phone_country }];
  }, [countries, form.phone_country]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!changed.length) return;
    setBusy(true);
    setError(null);
    try {
      const patch = Object.fromEntries(changed.map((k) => [k, form[k]])) as Partial<TenantSettings>;
      await updateOrganisationSettings(patch);
      await reload();
      toast("Settings saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the settings");
    } finally {
      setBusy(false);
    }
  }

  const sampleTime = useMemo(() => new Date(), []);
  const retentionOk = form.retention_days >= bounds.min && form.retention_days <= bounds.max;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>Organisation settings</h1>
          <p className="sub">
            How dates, times and money read everywhere in the platform, and how long archived
            records are kept.
          </p>
        </div>
        {canEdit && (
          <a className="btn secondary" href="/onboarding" title="Frameworks in scope, the modules your teams use, and the team">
            Organisation setup &amp; modules
          </a>
        )}
      </div>

      {!canEdit && (
        <div className="card card-pad" style={{ marginBottom: 16, fontSize: 13.5, background: "var(--primary-weak-2)" }}>
          You can view these settings. Changing them needs the <strong>Change organisation settings</strong>{" "}
          permission, which the Admin role holds.
        </div>
      )}

      <form onSubmit={save}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
          <div className="card">
            <div className="card-head"><h3>Locale</h3></div>
            <div className="card-pad">
              <fieldset disabled={!canEdit || busy} style={{ border: 0, padding: 0, margin: 0 }}>
                <Field
                  label="Currency"
                  help="Money is shown in this currency unless a record carries its own (a contract in USD, say). New records default to it."
                >
                  <Select value={form.currency} onChange={(v) => v && set("currency", v)} options={currencyOptions} />
                </Field>
                <Field
                  label="Timezone"
                  help="Timestamps — when something was created, approved or tested — are shown in this timezone for everyone, wherever they sign in from."
                >
                  <AsyncSelect
                    search={searchTimezones}
                    value={form.timezone}
                    selectedLabel={`${form.timezone.replace(/_/g, " ")}  ${timezoneOffset(form.timezone)}`}
                    onChange={(v) => v && set("timezone", v)}
                    placeholder="Search timezones…"
                    disabled={!canEdit || busy}
                  />
                </Field>
                <Field label="Date format" help="How every date is written on screen and in exports.">
                  <Select
                    value={form.date_format}
                    onChange={(v) => v && set("date_format", v as DateFormat)}
                    options={DATE_FORMATS.map((f) => ({
                      value: f,
                      label: `${f}  —  ${formatDate(sampleTime, { ...form, date_format: f })}`,
                    }))}
                  />
                </Field>
                <Field
                  label="Phone country"
                  help="Default country for phone numbers entered without an international prefix."
                >
                  <Select value={form.phone_country} onChange={(v) => v && set("phone_country", v)} options={phoneOptions} />
                </Field>
              </fieldset>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>Reporting &amp; retention</h3></div>
            <div className="card-pad">
              <fieldset disabled={!canEdit || busy} style={{ border: 0, padding: 0, margin: 0 }}>
                <Field
                  label="Fiscal year starts in"
                  help="Year-to-date figures and annual reports count from this month. Pakistani banks report on the calendar year (January); many companies use July."
                >
                  <Select
                    value={String(form.fiscal_year_start_month)}
                    onChange={(v) => v && set("fiscal_year_start_month", Number(v))}
                    options={MONTH_OPTIONS}
                  />
                </Field>
                <Field
                  label="Keep archived records for (days)"
                  help={`Archived (deleted) risks, controls, issues and other records can be restored during this window, then are purged for good. Between ${bounds.min} and ${bounds.max} days; check your record-retention policy before shortening it.`}
                >
                  <NumberInput
                    value={form.retention_days}
                    min={bounds.min}
                    max={bounds.max}
                    step={1}
                    onChange={(v) => set("retention_days", v === "" ? 0 : Math.round(v))}
                  />
                  {!retentionOk && (
                    <div className="error" style={{ fontSize: 12, marginTop: 4 }}>
                      Must be between {bounds.min} and {bounds.max} days.
                    </div>
                  )}
                </Field>
              </fieldset>
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h3>Preview</h3></div>
            <div className="card-pad">
              <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px", margin: 0, fontSize: 14 }}>
                <dt className="muted">Date</dt>
                <dd style={{ margin: 0 }}>{formatDate(sampleTime, form)}</dd>
                <dt className="muted">Date and time</dt>
                <dd style={{ margin: 0 }}>{formatDateTime(sampleTime, form)}</dd>
                <dt className="muted">Amount</dt>
                <dd style={{ margin: 0 }}>{formatMoney(1250000, null, { settings: form })}</dd>
                <dt className="muted">Compact amount</dt>
                <dd style={{ margin: 0 }}>{formatMoney(1250000, null, { settings: form, compact: true })}</dd>
                <dt className="muted">Fiscal year</dt>
                <dd style={{ margin: 0 }}>
                  {MONTHS[form.fiscal_year_start_month - 1]} – {MONTHS[(form.fiscal_year_start_month + 10) % 12]}
                </dd>
              </dl>
            </div>
          </div>
        </div>

        {error && <div className="error" style={{ marginTop: 12 }}>{error}</div>}

        {canEdit && (
          <div style={{ display: "flex", gap: 8, marginTop: 16, alignItems: "center" }}>
            <button className="btn" disabled={busy || loading || !changed.length || !retentionOk}>
              {busy ? "Saving…" : "Save settings"}
            </button>
            {changed.length > 0 && (
              <button type="button" className="btn secondary" disabled={busy} onClick={() => setForm(settings)}>
                Discard changes
              </button>
            )}
            <span className="muted" style={{ fontSize: 12.5 }}>
              {changed.length ? `${changed.length} unsaved change${changed.length === 1 ? "" : "s"}` : "No unsaved changes"}
              {" · "}Every change is written to the activity log.
            </span>
          </div>
        )}
      </form>

      {canEdit && (
        <section id="security" style={{ marginTop: 28 }}>
          <h2 style={{ fontSize: 18, margin: "0 0 4px" }}>Security</h2>
          <p className="muted" style={{ fontSize: 13.5, margin: "0 0 12px" }}>
            Who must use two-factor authentication, and whether maker-checker can work with the people you have.
          </p>
          <div style={{ display: "grid", gap: 16 }}>
            <MfaPolicySettings canEdit={canEdit} />
            <SegregationOfDutiesSettings />
          </div>
        </section>
      )}
    </div>
  );
}
