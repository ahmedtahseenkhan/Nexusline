"use client";

import { useEffect, useState } from "react";
import { api, type RiskSetting } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { Select } from "@/components/fields";

/* The rating-driven review cadence (F-22): for each severity, the longest review cycle
   a risk of that rating may have. A risk's owner may choose a shorter cycle; a longer
   one is overridden, and the risk says why ("Monthly — required for Critical risks").
   Tightening a severity brings in the next review of every risk it now covers. */

const SEVERITIES = [
  { key: "critical", label: "Critical" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
] as const;
type SeverityKey = (typeof SEVERITIES)[number]["key"];

const CYCLES = [
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "semiannual", label: "Twice a year" },
  { value: "annual", label: "Annual" },
];
const ORDER = CYCLES.map((c) => c.value);
const DEFAULTS: Record<SeverityKey, string> = { critical: "monthly", high: "quarterly", medium: "semiannual", low: "annual" };

export default function RiskReviewCadence({ settings, onSaved }: { settings: RiskSetting | null; onSaved?: (s: RiskSetting) => void }) {
  const [cadence, setCadence] = useState<Record<SeverityKey, string>>(DEFAULTS);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const defaults = (settings?.review_cadence_defaults ?? DEFAULTS) as Record<SeverityKey, string>;

  useEffect(() => {
    if (settings?.review_cadence) setCadence({ ...DEFAULTS, ...settings.review_cadence });
  }, [settings]);

  // A worse rating may not be allowed a longer interval than a milder one; the server
  // refuses it too, this only says so before the round trip.
  const outOfOrder = SEVERITIES.slice(0, -1).find((s, i) => ORDER.indexOf(cadence[s.key]) > ORDER.indexOf(cadence[SEVERITIES[i + 1].key]));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const s = await api.patchRiskSettings({ review_cadence: cadence });
      toast("Review cadence saved");
      onSaved?.(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the review cadence");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save}>
      <div style={{ fontWeight: 600, marginBottom: 2 }}>Review cadence by rating</div>
      <p className="muted" style={{ fontSize: 13, margin: "0 0 10px" }}>
        The longest a risk may go between reviews, set by its current rating (residual where assessed, otherwise
        inherent). An owner can choose a shorter cycle. When a re-score makes a risk worse, its next review is brought in.
      </p>
      {error && <div className="error" style={{ marginBottom: 8 }}>{error}</div>}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        {SEVERITIES.map((s) => (
          <div key={s.key} style={{ width: 150 }}>
            <label className="label">{s.label} risks</label>
            <Select value={cadence[s.key]} onChange={(v) => setCadence((c) => ({ ...c, [s.key]: v || defaults[s.key] }))} options={CYCLES} />
            {cadence[s.key] !== defaults[s.key] && (
              <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                Default: {CYCLES.find((c) => c.value === defaults[s.key])?.label}
              </div>
            )}
          </div>
        ))}
        <button className="btn" disabled={saving || !!outOfOrder}>{saving ? "Saving…" : "Save cadence"}</button>
      </div>
      {outOfOrder && (
        <p style={{ fontSize: 12.5, color: "var(--red)", margin: "8px 0 0" }}>
          {outOfOrder.label} risks can&apos;t be reviewed less often than the rating below them.
        </p>
      )}
    </form>
  );
}
