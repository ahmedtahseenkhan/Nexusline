"use client";

/* First-run setup for a new organisation (§3.3): locale, the frameworks in scope, the
   modules to start with, the team — then the dashboard. Every step saves on its own and
   can be revisited from Settings, so leaving half-way loses nothing. Administrators are
   sent here after sign-in until they finish; everyone else never sees it. */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Field, Select } from "@/components/fields";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { DATE_FORMATS, MONTHS, currencyOptions, useFormat, type DateFormat } from "@/lib/format";
import { SETTINGS_MANAGE_PERMISSION, updateOrganisationSettings } from "@/lib/masterData";
import { useHasPermission, useTenantSettings } from "@/lib/tenantSettings";

type Step = "locale" | "frameworks" | "modules" | "team" | "finish";
const STEPS: { key: Step; title: string; hint: string }[] = [
  { key: "locale", title: "Locale", hint: "Currency, timezone and date format" },
  { key: "frameworks", title: "Frameworks", hint: "The standards you're assessed against" },
  { key: "modules", title: "Modules", hint: "What your teams will use first" },
  { key: "team", title: "Team", hint: "Invite a second user — an approver" },
  { key: "finish", title: "Finish", hint: "Go to the dashboard" },
];

type ContentPack = {
  id: string;
  name: string;
  description: string;
  requirement_count: number;
  installed: boolean;
  is_control_framework: boolean;
  kind: string;
  upgrade_available: boolean;
};

type ModuleState = {
  key: string;
  title: string;
  category: string;
  description: string;
  available: boolean;
  enabled_by_organisation: boolean;
  starter: boolean;
  enabled: boolean;
};

type OnboardingStatus = {
  completed_at: string | null;
  frameworks_installed: number;
  users: number;
  modules_chosen: boolean;
  locale_set: boolean;
  /** Segregation of duties (F-06): on, but only one active user — nothing can be approved. */
  sod_enforced?: boolean;
  needs_second_user?: boolean;
  approval_routes_enabled?: number;
  role_gaps?: string[];
};

/** What a Pakistani bank is examined against first; ISO 27001 is the certification most
 *  ask for. Shown pre-highlighted, never installed without a click. */
const RECOMMENDED_FRAMEWORKS = ["sbp-etgrm", "sbp-cybersecurity", "sbp-bcp", "sbp-outsourcing", "iso-27001-2022"];

const MONTH_OPTIONS = MONTHS.map((m, i) => ({ value: String(i + 1), label: m }));
const TIMEZONES = [
  "Asia/Karachi", "Asia/Dubai", "Asia/Riyadh", "Asia/Muscat", "Asia/Qatar", "Asia/Kuwait",
  "Asia/Bahrain", "Europe/London", "UTC",
].map((z) => ({ value: z, label: z }));

export default function OnboardingPage() {
  const router = useRouter();
  const canManage = useHasPermission(SETTINGS_MANAGE_PERMISSION);
  const { settings, reload } = useTenantSettings();
  const { formatDate } = useFormat();
  const [step, setStep] = useState<Step>("locale");
  const [status, setStatus] = useState<OnboardingStatus | null>(null);
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      setStatus(await apiCall<OnboardingStatus>("GET", "/settings/organisation/onboarding"));
    } catch {
      setStatus(null);
    }
  }, []);
  useEffect(() => { void loadStatus(); }, [loadStatus]);

  const index = STEPS.findIndex((s) => s.key === step);
  const next = () => setStep(STEPS[Math.min(index + 1, STEPS.length - 1)].key);
  const back = () => setStep(STEPS[Math.max(index - 1, 0)].key);

  async function finish() {
    setBusy(true);
    try {
      await apiCall("POST", "/settings/organisation/onboarding/complete");
      await reload();
      toast("Setup complete");
      router.push("/dashboard");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not finish setup", "error");
    } finally {
      setBusy(false);
    }
  }

  if (!canManage) {
    return (
      <div className="page">
        <div className="card card-pad" style={{ maxWidth: 640 }}>
          <h2 style={{ marginTop: 0 }}>Organisation setup</h2>
          <p className="muted">An administrator sets up the organisation. You can start from <Link href="/my-work">My work</Link>.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Set up your organisation</h1>
          <p className="muted">
            Five short steps. Each one saves as you go and can be changed later under Settings, so you can stop at any point.
          </p>
        </div>
        {status?.completed_at && <span className="badge">Completed {formatDate(status.completed_at)}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(180px, 240px) minmax(0, 1fr)", gap: 20, alignItems: "start" }}>
        <ol className="card card-pad" style={{ listStyle: "none", margin: 0, display: "grid", gap: 4 }} aria-label="Setup steps">
          {STEPS.map((s, i) => {
            const done = stepDone(s.key, status);
            return (
              <li key={s.key}>
                <button
                  className={s.key === step ? "btn sm" : "btn secondary sm"}
                  style={{ width: "100%", justifyContent: "flex-start", textAlign: "left" }}
                  onClick={() => setStep(s.key)}
                  aria-current={s.key === step ? "step" : undefined}
                >
                  <span style={{ width: 20 }}>{done ? "✓" : `${i + 1}.`}</span>
                  <span>
                    <b>{s.title}</b>
                    <span className="muted" style={{ display: "block", fontSize: 12 }}>{s.hint}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <div className="card">
          {step === "locale" && <LocaleStep settings={settings} onSaved={async () => { await reload(); await loadStatus(); next(); }} />}
          {step === "frameworks" && <FrameworksStep onChanged={loadStatus} />}
          {step === "modules" && <ModulesStep onSaved={async () => { await loadStatus(); next(); }} />}
          {step === "team" && <TeamStep status={status} onInvited={loadStatus} />}
          {step === "finish" && (
            <div className="card-pad">
              <h3 style={{ marginTop: 0 }}>You're ready</h3>
              <ul style={{ lineHeight: 1.8 }}>
                <li>Locale: {status?.locale_set ? "set" : "defaults (PKR, Asia/Karachi, DD/MM/YYYY)"}</li>
                <li>Frameworks installed: {status?.frameworks_installed ?? 0}</li>
                <li>Modules: {status?.modules_chosen ? "chosen" : "all licensed modules"}</li>
                <li>Active users: {status?.users ?? 0}</li>
                <li>Approval routes on: {status?.approval_routes_enabled ?? 0} (risks, policies and exceptions go to an approver)</li>
              </ul>
              {status?.needs_second_user && (
                <div className="card card-pad" role="note" style={{ marginBottom: 12, fontSize: 13, background: "var(--amber-bg)", color: "var(--amber)" }}>
                  Segregation of duties needs at least two users. Until you{" "}
                  <button type="button" className="btn secondary sm" onClick={() => setStep("team")}>invite a second user</button>{" "}
                  nothing you submit can be approved, and a reminder stays at the top of every page.
                </div>
              )}
              {(status?.role_gaps ?? []).map((gap) => (
                <div key={gap} className="card card-pad" role="note" style={{ marginBottom: 12, fontSize: 13, background: "var(--primary-weak-2)" }}>
                  {gap}
                </div>
              ))}
              <button className="btn" onClick={finish} disabled={busy}>{busy ? "Finishing…" : "Finish and open the dashboard"}</button>
            </div>
          )}
          {step !== "finish" && (
            <div className="card-pad" style={{ display: "flex", justifyContent: "space-between", borderTop: "1px solid var(--border)" }}>
              <button className="btn secondary" onClick={back} disabled={index === 0}>Back</button>
              <button className="btn secondary" onClick={next}>Skip this step</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function stepDone(step: Step, status: OnboardingStatus | null): boolean {
  if (!status) return false;
  if (step === "locale") return status.locale_set;
  if (step === "frameworks") return status.frameworks_installed > 0;
  if (step === "modules") return status.modules_chosen;
  if (step === "team") return status.users > 1;
  return Boolean(status.completed_at);
}

function LocaleStep({ settings, onSaved }: { settings: { currency: string; timezone: string; date_format: string; fiscal_year_start_month: number }; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState({
    currency: settings.currency,
    timezone: settings.timezone,
    date_format: settings.date_format,
    fiscal_year_start_month: String(settings.fiscal_year_start_month),
  });
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setForm({
      currency: settings.currency,
      timezone: settings.timezone,
      date_format: settings.date_format,
      fiscal_year_start_month: String(settings.fiscal_year_start_month),
    });
  }, [settings.currency, settings.timezone, settings.date_format, settings.fiscal_year_start_month]);

  async function save() {
    setSaving(true);
    try {
      await updateOrganisationSettings({
        currency: form.currency,
        timezone: form.timezone,
        date_format: form.date_format as DateFormat,
        fiscal_year_start_month: Number(form.fiscal_year_start_month),
      });
      toast("Locale saved");
      await onSaved();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card-pad">
      <h3 style={{ marginTop: 0 }}>Locale</h3>
      <p className="muted">Every amount and date in the app is shown this way. Pakistani banks usually keep the defaults.</p>
      <div className="field-row">
        <Field label="Currency" help="Money is shown in this currency unless a record says otherwise.">
          <Select value={form.currency} onChange={(v) => setForm({ ...form, currency: v })} options={currencyOptions} />
        </Field>
        <Field label="Timezone" help="Incident times and deadlines are read in this timezone.">
          <Select value={form.timezone} onChange={(v) => setForm({ ...form, timezone: v })} options={TIMEZONES.some((t) => t.value === form.timezone) ? TIMEZONES : [{ value: form.timezone, label: form.timezone }, ...TIMEZONES]} />
        </Field>
      </div>
      <div className="field-row">
        <Field label="Date format">
          <Select value={form.date_format} onChange={(v) => setForm({ ...form, date_format: v })} options={DATE_FORMATS.map((d) => ({ value: d, label: d }))} />
        </Field>
        <Field label="Financial year starts" help="Banks in Pakistan report on the calendar year.">
          <Select value={form.fiscal_year_start_month} onChange={(v) => setForm({ ...form, fiscal_year_start_month: v })} options={MONTH_OPTIONS} />
        </Field>
      </div>
      <button className="btn" onClick={save} disabled={saving}>{saving ? "Saving…" : "Save and continue"}</button>
    </div>
  );
}

function FrameworksStep({ onChanged }: { onChanged: () => Promise<void> }) {
  const [packs, setPacks] = useState<ContentPack[] | null>(null);
  const [installing, setInstalling] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setPacks(await apiCall<ContentPack[]>("GET", "/content-library"));
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load the framework library", "error");
      setPacks([]);
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const ordered = useMemo(() => {
    const list = packs ?? [];
    const rank = (p: ContentPack) => {
      const i = RECOMMENDED_FRAMEWORKS.indexOf(p.id);
      return i === -1 ? 100 : i;
    };
    return [...list].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  }, [packs]);

  async function install(pack: ContentPack) {
    setInstalling(pack.id);
    try {
      const flag = pack.is_control_framework ? "?create_controls=true" : "";
      await apiCall("POST", `/content-library/${pack.id}/install${flag}`);
      toast(`Installed ${pack.name}`);
      await load();
      await onChanged();
    } catch (e) {
      toast(e instanceof Error ? e.message : `Could not install ${pack.name}`, "error");
    } finally {
      setInstalling(null);
    }
  }

  return (
    <div className="card-pad">
      <h3 style={{ marginTop: 0 }}>Frameworks in scope</h3>
      <p className="muted">
        Install the standards you're examined or certified against. Control frameworks also create their controls in the catalogue.
        Recommended for Pakistani banks are marked; you can add more any time from the Framework Library.
      </p>
      {packs === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {ordered.map((p) => (
            <div key={p.id} style={{ display: "flex", gap: 12, alignItems: "center", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
              <div style={{ minWidth: 0 }}>
                <b>{p.name}</b>
                {RECOMMENDED_FRAMEWORKS.includes(p.id) && <span className="badge" style={{ marginLeft: 8 }}>Recommended</span>}
                {p.kind !== "compliance" && <span className="badge" style={{ marginLeft: 8 }}>Maturity self-assessment</span>}
                <div className="muted" style={{ fontSize: 12.5 }}>{p.requirement_count} requirements{p.is_control_framework ? " · brings its controls" : ""}</div>
              </div>
              {p.installed && !p.upgrade_available ? (
                <span className="muted">Installed</span>
              ) : (
                <button className="btn secondary sm" onClick={() => install(p)} disabled={installing !== null}>
                  {installing === p.id ? "Installing…" : p.upgrade_available ? "Upgrade" : "Install"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ModulesStep({ onSaved }: { onSaved: () => Promise<void> }) {
  const [modules, setModules] = useState<ModuleState[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [islamic, setIslamic] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const rows = await apiCall<ModuleState[]>("GET", "/settings/organisation/modules");
        setModules(rows);
        const organisationChose = rows.some((m) => !m.enabled_by_organisation);
        // First visit: start from the recommended set; afterwards, what was chosen.
        const initial = organisationChose
          ? rows.filter((m) => m.enabled).map((m) => m.key)
          : rows.filter((m) => m.available && m.starter).map((m) => m.key);
        setChosen(new Set(initial));
        setIslamic(initial.includes("shariah"));
      } catch (e) {
        toast(e instanceof Error ? e.message : "Could not load modules", "error");
        setModules([]);
      }
    })();
  }, []);

  function toggle(key: string) {
    setChosen((prev) => {
      const nextSet = new Set(prev);
      if (nextSet.has(key)) nextSet.delete(key); else nextSet.add(key);
      return nextSet;
    });
  }

  function setIslamicBank(value: boolean) {
    setIslamic(value);
    setChosen((prev) => {
      const nextSet = new Set(prev);
      if (value) nextSet.add("shariah"); else nextSet.delete("shariah");
      return nextSet;
    });
  }

  async function save(all: boolean) {
    setSaving(true);
    try {
      await apiCall("PUT", "/settings/organisation/modules", { enabled: all ? null : Array.from(chosen) });
      toast(all ? "All licensed modules are on" : `${chosen.size} modules on`);
      await onSaved();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save modules", "error");
    } finally {
      setSaving(false);
    }
  }

  const groups = useMemo(() => {
    const byCategory = new Map<string, ModuleState[]>();
    for (const m of modules ?? []) {
      byCategory.set(m.category, [...(byCategory.get(m.category) ?? []), m]);
    }
    return Array.from(byCategory.entries());
  }, [modules]);

  return (
    <div className="card-pad">
      <h3 style={{ marginTop: 0 }}>Modules to start with</h3>
      <p className="muted">
        The risk register, controls, compliance, policies, issues and incidents are always on. Choose the specialist modules your teams
        will use first; the rest stay hidden until you switch them on under Settings → Organisation.
      </p>
      <label style={{ display: "flex", gap: 8, alignItems: "center", margin: "8px 0 16px" }}>
        <input id="onboarding-islamic" type="checkbox" checked={islamic} onChange={(e) => setIslamicBank(e.target.checked)} />
        We are an Islamic bank or have an Islamic banking window (adds Shariah Governance)
      </label>
      {modules === null ? (
        <p className="muted">Loading…</p>
      ) : (
        <div style={{ display: "grid", gap: 14 }}>
          {groups.map(([category, rows]) => (
            <fieldset key={category} style={{ border: "none", padding: 0, margin: 0 }}>
              <legend className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: ".04em" }}>{category}</legend>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 8 }}>
                {rows.map((m) => (
                  <label key={m.key} style={{ display: "flex", gap: 8, alignItems: "flex-start", opacity: m.available ? 1 : 0.5 }} title={m.available ? m.description : "Not on this installation's licence"}>
                    <input
                      id={`onboarding-module-${m.key}`}
                      type="checkbox"
                      checked={chosen.has(m.key)}
                      disabled={!m.available}
                      onChange={() => toggle(m.key)}
                    />
                    <span>
                      {m.title}
                      {m.starter && <span className="badge" style={{ marginLeft: 6 }}>Recommended</span>}
                      <span className="muted" style={{ display: "block", fontSize: 12 }}>{m.available ? m.description : "Not licensed"}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button className="btn" onClick={() => save(false)} disabled={saving || modules === null}>{saving ? "Saving…" : `Use these ${chosen.size} modules`}</button>
        <button className="btn secondary" onClick={() => save(true)} disabled={saving}>Turn on everything licensed</button>
      </div>
    </div>
  );
}

type RoleOption = { id: string; name: string; description: string };

/** Maker-checker needs a second person: invite one here (or several under Users). The
 *  default role is Risk Approver, which decides the default risk and exception routes. */
function TeamStep({ status, onInvited }: { status: OnboardingStatus | null; onInvited: () => Promise<void> }) {
  const users = status?.users ?? 0;
  const [roles, setRoles] = useState<RoleOption[]>([]);
  const [form, setForm] = useState({ full_name: "", email: "", role: "Risk Approver", password: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiCall<RoleOption[]>("GET", "/users/roles").then(setRoles).catch(() => setRoles([]));
  }, []);

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await apiCall("POST", "/users", {
        email: form.email.trim(),
        full_name: form.full_name.trim(),
        password: form.password,
        is_active: true,
        role_names: [form.role],
      });
      toast(`Added ${form.email.trim()} as ${form.role}`);
      setForm({ full_name: "", email: "", role: form.role, password: "" });
      await onInvited();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the user");
    } finally {
      setSaving(false);
    }
  }

  const roleOptions = (roles.length ? roles.map((r) => r.name) : ["Risk Approver", "Compliance Manager", "Risk Manager"])
    .map((name) => ({ value: name, label: name }));

  return (
    <div className="card-pad">
      <h3 style={{ marginTop: 0 }}>Invite a second user</h3>
      <p className="muted">
        Records are owned by people, so owners, testers and approvers need accounts. {users} active {users === 1 ? "user" : "users"} so far.
      </p>
      {status?.needs_second_user ? (
        <div className="card card-pad" role="note" style={{ marginBottom: 14, fontSize: 13, background: "var(--amber-bg)", color: "var(--amber)" }}>
          Segregation of duties needs at least two users. The person who submits a risk, policy or exception can never
          approve it, so with only you nothing can be approved. Add at least one approver now.
        </div>
      ) : (
        <p className="muted" style={{ fontSize: 13 }}>
          You have enough people for maker-checker. Risk and exception approvals go to the Risk Approver role; policy
          approvals go to the Compliance Manager role.
        </p>
      )}
      <form onSubmit={invite}>
        <div className="field-row">
          <Field label="Full name">
            <input className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} placeholder="Sana Qureshi" />
          </Field>
          <Field label="Work e-mail" required>
            <input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="sana.qureshi@bank.com.pk" />
          </Field>
        </div>
        <div className="field-row">
          <Field label="Role" help="Risk Approver decides risk and exception approvals; Compliance Manager decides policy approvals.">
            <Select value={form.role} onChange={(v) => v && setForm({ ...form, role: v })} options={roleOptions} />
          </Field>
          <Field label="Initial password" required help="At least 12 characters with upper and lower case, a digit and a symbol. Share it securely; they must set up two-factor authentication.">
            <input className="input" type="password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />
          </Field>
        </div>
        {error && <div className="error" style={{ marginBottom: 10 }}>{error}</div>}
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn" disabled={saving || !form.email.trim() || !form.password}>{saving ? "Adding…" : "Add user"}</button>
          <Link className="btn secondary" href="/organization">Manage all users and roles</Link>
        </div>
      </form>
      <p className="muted" style={{ fontSize: 12.5, marginTop: 12 }}>
        If your bank signs in with Active Directory or single sign-on, set that up under Settings → SSO / LDAP instead.
      </p>
    </div>
  );
}
