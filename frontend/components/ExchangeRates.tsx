"use client";

/* Settings → Organisation → Exchange rates.

   Every amount keeps the currency it was recorded in; totals are shown in the
   organisation's reporting currency. The bank enters the rates itself — an on-premises
   installation has no internet feed, and a bank reports at the rates its treasury uses
   (typically the SBP weighted-average customer rates).

   Anyone signed in can read the rates; adding, correcting or removing one needs
   "Change organisation settings" (Admin). */

import { useCallback, useEffect, useMemo, useState } from "react";
import ImportExport from "@/components/ImportExport";
import { Field, NumberInput, Select, TextInput } from "@/components/fields";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { CURRENCIES, currencyOptions, formatDate } from "@/lib/format";

type Rate = {
  id: string;
  currency: string;
  reporting_currency: string;
  rate_to_reporting: string;
  effective_date: string;
  source: string;
  created_by_name: string;
  created_at: string | null;
};

type CurrencySummary = {
  currency: string;
  name: string;
  latest_rate: string;
  latest_date: string;
  rate_count: number;
  age_days: number;
};

type RateList = {
  reporting_currency: string;
  currencies: CurrencySummary[];
  items: Rate[];
  /** Currencies used on records that have no rate into the reporting currency. */
  missing: string[];
};

const BLANK = { currency: "", rate: "" as number | "", effective_date: "", source: "" };

/** A rate is kept to 8 decimals; show what was entered, without trailing zeros. */
function rateText(value: string): string {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : value;
}

export default function ExchangeRates({ canEdit }: { canEdit: boolean }) {
  const [data, setData] = useState<RateList | null>(null);
  const [form, setForm] = useState(BLANK);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const reload = useCallback(async () => {
    try {
      setData(await apiCall<RateList>("GET", "/settings/exchange-rates"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the exchange rates");
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const reporting = data?.reporting_currency || "PKR";
  const options = useMemo(
    () => currencyOptions.filter((o) => o.value !== reporting),
    [reporting],
  );
  const rows = data?.items ?? [];
  const shown = showAll ? rows : rows.slice(0, 12);

  const set = <K extends keyof typeof BLANK>(k: K, v: (typeof BLANK)[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!form.currency || form.rate === "" || !form.effective_date) return;
    setBusy(true);
    setError(null);
    try {
      await apiCall("POST", "/settings/exchange-rates", {
        currency: form.currency,
        rate_to_reporting: form.rate,
        effective_date: form.effective_date,
        source: form.source,
      });
      setForm({ ...BLANK });
      await reload();
      toast("Exchange rate added");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the rate");
    } finally {
      setBusy(false);
    }
  }

  async function remove(rate: Rate) {
    if (!window.confirm(`Delete the ${rate.currency} rate of ${formatDate(rate.effective_date)}?`)) return;
    try {
      await apiCall("DELETE", `/settings/exchange-rates/${rate.id}`);
      await reload();
      toast("Exchange rate deleted");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the rate");
    }
  }

  return (
    <div className="card">
      <div className="card-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
        <h3>Exchange rates</h3>
        {/* Import and export both need `settings:manage`, so they are hidden for a reader. */}
        {canEdit && <ImportExport resource="fx-rates" label="Exchange Rates" onDone={reload} />}
      </div>
      <div className="card-pad">
        <p className="muted" style={{ fontSize: 13.5, marginTop: 0 }}>
          Every amount keeps the currency it was recorded in. Totals — losses, replacement
          cost, vendor spend, contract value — are shown in <strong>{reporting}</strong>,
          converted at the rate in force on the amount&apos;s date. Rates are entered by your
          bank (for example the SBP weighted-average customer rates, or your treasury&apos;s
          month-end rates): an on-premises installation has no internet feed. An amount in a
          currency with no rate is never added into a total; it is listed separately.
        </p>

        {data && data.missing.length > 0 && (
          <div className="card card-pad" style={{ marginBottom: 12, fontSize: 13.5, background: "var(--primary-weak-2)" }}>
            No rate yet for {data.missing.join(", ")} — amounts in{" "}
            {data.missing.length === 1 ? "that currency are" : "those currencies are"} left out of
            every total until a rate is added.
          </div>
        )}

        {data && data.currencies.length > 0 && (
          <div className="table-wrap" style={{ marginBottom: 16 }}>
            <table>
            <thead>
              <tr>
                <th>Currency</th>
                <th style={{ textAlign: "right" }}>Latest rate</th>
                <th>Effective</th>
                <th style={{ textAlign: "right" }}>Rates on file</th>
              </tr>
            </thead>
            <tbody>
              {data.currencies.map((c) => (
                <tr key={c.currency}>
                  <td>
                    <strong>{c.currency}</strong> <span className="muted">{c.name || CURRENCIES[c.currency] || ""}</span>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    1 {c.currency} = {rateText(c.latest_rate)} {reporting}
                  </td>
                  <td>
                    {formatDate(c.latest_date)}
                    {c.age_days > 90 && <span className="muted"> · {c.age_days} days old</span>}
                  </td>
                  <td style={{ textAlign: "right" }}>{c.rate_count}</td>
                </tr>
              ))}
              </tbody>
            </table>
          </div>
        )}

        {canEdit && (
          <form onSubmit={add} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: 12, alignItems: "end" }}>
            <Field label="Currency">
              <Select
                value={form.currency}
                onChange={(v) => set("currency", v)}
                options={options}
                placeholder="Choose a currency…"
              />
            </Field>
            <Field label={`Rate to ${reporting}`} help={`Units of ${reporting} for 1 unit of the currency.`}>
              <NumberInput value={form.rate} onChange={(v) => set("rate", v)} min={0} step={0.0001} placeholder="278.45" />
            </Field>
            <Field label="Effective from" help="Applies to amounts dated on or after this day.">
              <TextInput type="date" value={form.effective_date} onChange={(v) => set("effective_date", v)} />
            </Field>
            <Field label="Source" help="e.g. SBP weighted average, 30 Jun 2026.">
              <TextInput value={form.source} onChange={(v) => set("source", v)} placeholder="SBP weighted average" />
            </Field>
            <div style={{ marginBottom: 14 }}>
              <button className="btn" disabled={busy || !form.currency || form.rate === "" || !form.effective_date}>
                {busy ? "Adding…" : "Add rate"}
              </button>
            </div>
          </form>
        )}

        {error && <div className="error" style={{ marginTop: 8 }}>{error}</div>}

        {rows.length > 0 ? (
          <>
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
              <thead>
                <tr>
                  <th>Effective</th>
                  <th>Currency</th>
                  <th style={{ textAlign: "right" }}>Rate</th>
                  <th>Source</th>
                  <th>Added by</th>
                  {canEdit && <th />}
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.id}>
                    <td>{formatDate(r.effective_date)}</td>
                    <td>{r.currency}</td>
                    <td style={{ textAlign: "right" }}>{rateText(r.rate_to_reporting)}</td>
                    <td className="muted">{r.source || "—"}</td>
                    <td className="muted">{r.created_by_name || "—"}</td>
                    {canEdit && (
                      <td style={{ textAlign: "right" }}>
                        <button type="button" className="btn secondary sm" onClick={() => remove(r)}>
                          Delete
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
                </tbody>
              </table>
            </div>
            {rows.length > shown.length && (
              <button type="button" className="btn secondary sm" style={{ marginTop: 8 }} onClick={() => setShowAll(true)}>
                Show all {rows.length} rates
              </button>
            )}
          </>
        ) : (
          <p className="muted" style={{ fontSize: 13.5 }}>
            No rates yet. Amounts already in {reporting} need none; add a rate for every other
            currency your records use.
          </p>
        )}
      </div>
    </div>
  );
}
