/* Dates and money in the organisation's own locale.

   Every date and amount on screen should go through here so that one setting — Settings →
   Organisation — decides how they read: DD/MM/YYYY or YYYY-MM-DD, Asia/Karachi or
   Asia/Dubai, PKR or USD.

   Two ways to call:

     // In a component: bound to the current organisation's settings.
     const { formatDate, formatDateTime, formatMoney } = useFormat();
     formatMoney(row.exposure)                 // "PKR 1,250,000"
     formatMoney(row.exposure, row.currency, { compact: true })   // "USD 1.3M"

     // Anywhere else (table column helpers, CSV labels, tests): the plain functions.
     // Without a settings argument they use the settings the provider last loaded;
     // pass one to make them pure.
     formatDate("2026-09-12")                  // "12/09/2026"
     formatDate(value, { ...DEFAULT_TENANT_SETTINGS, date_format: "YYYY-MM-DD" })

   Every formatter returns "—" for null / undefined / "" and the input unchanged when it
   cannot be parsed, so a bad value is visible rather than silently blank. */

import { createContext, useContext, useMemo } from "react";

export type DateFormat = "DD/MM/YYYY" | "MM/DD/YYYY" | "YYYY-MM-DD" | "DD MMM YYYY";

/** The organisation's settings (`GET /settings/organisation`). */
export type TenantSettings = {
  /** ISO 4217 code money is shown in unless a record carries its own currency. */
  currency: string;
  /** IANA timezone timestamps are shown in. */
  timezone: string;
  date_format: DateFormat;
  /** 1 = January … 12 = December. */
  fiscal_year_start_month: number;
  /** ISO 3166-1 alpha-2 country for phone-number defaults. */
  phone_country: string;
  /** Days an archived record is kept before it is purged. */
  retention_days: number;
  updated_at?: string | null;
  id?: string | null;
};

export const DATE_FORMATS: DateFormat[] = ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD", "DD MMM YYYY"];

/** What pages use until the organisation's settings have loaded (and if they cannot). */
export const DEFAULT_TENANT_SETTINGS: TenantSettings = {
  currency: "PKR",
  timezone: "Asia/Karachi",
  date_format: "DD/MM/YYYY",
  fiscal_year_start_month: 1,
  phone_country: "PK",
  retention_days: 90,
};

/** ISO 4217 codes offered by every currency select — the same list the API accepts
 *  (`backend/app/schemas/tenant_settings.py` `CURRENCIES`); keep the two in step. */
export const CURRENCIES: Record<string, string> = {
  PKR: "Pakistani Rupee",
  USD: "US Dollar",
  EUR: "Euro",
  GBP: "Pound Sterling",
  AED: "UAE Dirham",
  SAR: "Saudi Riyal",
  OMR: "Omani Rial",
  QAR: "Qatari Riyal",
  KWD: "Kuwaiti Dinar",
  BHD: "Bahraini Dinar",
  CNY: "Chinese Yuan",
  JPY: "Japanese Yen",
  INR: "Indian Rupee",
  BDT: "Bangladeshi Taka",
  LKR: "Sri Lankan Rupee",
  AFN: "Afghan Afghani",
  IRR: "Iranian Rial",
  TRY: "Turkish Lira",
  EGP: "Egyptian Pound",
  JOD: "Jordanian Dinar",
  MYR: "Malaysian Ringgit",
  IDR: "Indonesian Rupiah",
  SGD: "Singapore Dollar",
  HKD: "Hong Kong Dollar",
  CHF: "Swiss Franc",
  CAD: "Canadian Dollar",
  AUD: "Australian Dollar",
  NZD: "New Zealand Dollar",
  SEK: "Swedish Krona",
  NOK: "Norwegian Krone",
  DKK: "Danish Krone",
  ZAR: "South African Rand",
  KES: "Kenyan Shilling",
  NGN: "Nigerian Naira",
  RUB: "Russian Rouble",
  KRW: "South Korean Won",
  THB: "Thai Baht",
  BRL: "Brazilian Real",
  MXN: "Mexican Peso",
};

/** `{value, label}` options for a currency `<Select>` ("PKR — Pakistani Rupee"). Shape
 *  matches `Option` in `components/fields.tsx`. */
export const currencyOptions: { value: string; label: string }[] = Object.entries(CURRENCIES).map(
  ([code, name]) => ({ value: code, label: `${code} — ${name}` }),
);

export const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const MONTHS_SHORT = MONTHS.map((m) => m.slice(0, 3));

/* ------------------------------------------------------------ current settings -- */

let current: TenantSettings = DEFAULT_TENANT_SETTINGS;

/** Called by `TenantSettingsProvider` once the organisation's settings load, so the plain
 *  (non-hook) formatters follow them too. */
export function setFormatSettings(settings: TenantSettings): void {
  current = { ...DEFAULT_TENANT_SETTINGS, ...settings };
}

/** The settings the plain formatters use right now. */
export function getFormatSettings(): TenantSettings {
  return current;
}

/* ---------------------------------------------------------------------- dates -- */

export type DateValue = string | number | Date | null | undefined;

type Parts = { year: string; month: string; day: string; hour: string; minute: string };

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const partFormatters = new Map<string, Intl.DateTimeFormat>();

function partsFormatter(timeZone: string): Intl.DateTimeFormat {
  let f = partFormatters.get(timeZone);
  if (!f) {
    const opts: Intl.DateTimeFormatOptions = {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    };
    try {
      f = new Intl.DateTimeFormat("en-GB", { ...opts, timeZone });
    } catch {
      f = new Intl.DateTimeFormat("en-GB", opts); // unknown zone: browser's own
    }
    partFormatters.set(timeZone, f);
  }
  return f;
}

function toParts(value: DateValue, timeZone: string): Parts | null {
  if (value instanceof Date || typeof value === "number") {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return null;
    const out: Record<string, string> = {};
    for (const p of partsFormatter(timeZone).formatToParts(d)) out[p.type] = p.value;
    return { year: out.year, month: out.month, day: out.day, hour: out.hour, minute: out.minute };
  }
  const text = String(value).trim();
  // A calendar date has no time and no zone: never shift it across midnight.
  const m = DATE_ONLY.exec(text);
  if (m) return { year: m[1], month: m[2], day: m[3], hour: "00", minute: "00" };
  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? null : toParts(d, timeZone);
}

function datePart(p: Parts, fmt: DateFormat): string {
  switch (fmt) {
    case "MM/DD/YYYY":
      return `${p.month}/${p.day}/${p.year}`;
    case "YYYY-MM-DD":
      return `${p.year}-${p.month}-${p.day}`;
    case "DD MMM YYYY":
      return `${p.day} ${MONTHS_SHORT[Number(p.month) - 1] ?? p.month} ${p.year}`;
    case "DD/MM/YYYY":
    default:
      return `${p.day}/${p.month}/${p.year}`;
  }
}

function isBlank(value: DateValue): boolean {
  return value === null || value === undefined || (typeof value === "string" && value.trim() === "");
}

/** A date in the organisation's date format. Timestamps are first converted to the
 *  organisation's timezone; a bare `YYYY-MM-DD` is shown as that calendar day. */
export function formatDate(value: DateValue, settings: TenantSettings = current): string {
  if (isBlank(value)) return "—";
  const p = toParts(value, settings.timezone);
  return p ? datePart(p, settings.date_format) : String(value);
}

/** Date and 24-hour time ("12/09/2026 14:05") in the organisation's timezone. A bare
 *  `YYYY-MM-DD` has no time, so it is shown as a date. */
export function formatDateTime(value: DateValue, settings: TenantSettings = current): string {
  if (isBlank(value)) return "—";
  if (typeof value === "string" && DATE_ONLY.test(value.trim())) return formatDate(value, settings);
  const p = toParts(value, settings.timezone);
  return p ? `${datePart(p, settings.date_format)} ${p.hour}:${p.minute}` : String(value);
}

/** "UTC+05:00"-style offset of a timezone right now (for pickers); "" if unknown. */
export function timezoneOffset(timeZone: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "longOffset" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName");
    return part ? part.value.replace("GMT", "UTC") || "UTC" : "";
  } catch {
    return "";
  }
}

/* ---------------------------------------------------------------------- money -- */

export type MoneyOptions = {
  /** `true`: always "PKR 1.2M"; `"auto"`: compact only from one million up. */
  compact?: boolean | "auto";
  /** Fixed number of decimals (default: up to 2, none for whole amounts). */
  decimals?: number;
  /** Settings to format with (makes the call pure); default: the loaded settings. */
  settings?: TenantSettings;
};

/** An amount with its ISO currency code in front: "PKR 1,250,000", "USD 12,500.50",
 *  "PKR 1.3M" (compact). `currency` defaults to the organisation's currency — pass the
 *  record's own currency when it has one. */
export function formatMoney(
  amount: number | string | null | undefined,
  currency?: string | null,
  options: MoneyOptions = {},
): string {
  if (amount === null || amount === undefined || (typeof amount === "string" && amount.trim() === "")) return "—";
  const n = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(n)) return String(amount);
  const settings = options.settings ?? current;
  const code = (currency || settings.currency || "PKR").toUpperCase();
  const compact = options.compact === true || (options.compact === "auto" && Math.abs(n) >= 1_000_000);
  const number = compact
    ? new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: options.decimals ?? 1 }).format(n)
    : new Intl.NumberFormat("en-US", {
        minimumFractionDigits: options.decimals ?? 0,
        maximumFractionDigits: options.decimals ?? 2,
      }).format(n);
  return `${code} ${number}`;
}

/* ---------------------------------------------------------------------- React -- */

/** What `TenantSettingsProvider` (lib/tenantSettings.tsx) puts in context. */
export type TenantSettingsState = {
  settings: TenantSettings;
  /** True until the first load finishes (settings hold the defaults meanwhile). */
  loading: boolean;
  /** Load error, if any (settings stay on the defaults). */
  error: string | null;
  /** Re-read the settings from the server (after saving them, say). */
  reload: () => Promise<void>;
  /** The signed-in user's permission codes, as `/auth/me` returned them. */
  permissions: string[];
};

export const TenantSettingsContext = createContext<TenantSettingsState>({
  settings: DEFAULT_TENANT_SETTINGS,
  loading: false,
  error: null,
  reload: async () => {},
  permissions: [],
});

/** The formatters bound to the current organisation's settings, plus the settings and
 *  the currency options. Re-renders when the settings change. */
export function useFormat() {
  const { settings } = useContext(TenantSettingsContext);
  return useMemo(
    () => ({
      settings,
      currency: settings.currency,
      currencyOptions,
      formatDate: (value: DateValue) => formatDate(value, settings),
      formatDateTime: (value: DateValue) => formatDateTime(value, settings),
      formatMoney: (amount: number | string | null | undefined, currency?: string | null, options: Omit<MoneyOptions, "settings"> = {}) =>
        formatMoney(amount, currency, { ...options, settings }),
    }),
    [settings],
  );
}
