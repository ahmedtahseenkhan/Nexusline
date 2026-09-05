"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Me, type Organization, type PlatformSummary } from "@/lib/api";
import { confirmDialog, toast } from "@/lib/feedback";
import FormModal from "@/components/FormModal";
import { Field, TextInput } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconShield } from "@/components/icons";

/* The operator's console: which organisations exist on this deployment, and the button
   that creates the next one.

   Everything else in the app answers "what is true inside my organisation?". This page
   answers a different question for a different audience — whoever runs the install, not
   whoever uses it — which is why it is gated on `is_platform_admin` rather than on a
   permission code. Permissions are tenant-scoped rows, so an org admin could otherwise
   grant themselves one.

   What it deliberately does NOT do is show anybody's data. The counts below are the only
   thing crossing an organisation boundary, and each is read inside that organisation's
   own scope on the server. There is also no delete: suspending locks people out and
   leaves every record where it is, which is the only reversible answer to "this client's
   contract ended". */

const BLANK = { name: "", slug: "", admin_email: "", admin_password: "", admin_full_name: "" };

/** Slug suggestion from the organisation name — lowercase, hyphenated, no leading or
 *  trailing punctuation, because that is what the API's pattern accepts. */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63);
}

export default function OrganizationsPage() {
  const [me, setMe] = useState<Me | null>(null);
  const [rows, setRows] = useState<Organization[] | null>(null);
  const [summary, setSummary] = useState<PlatformSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [f, setF] = useState({ ...BLANK });
  // True once the operator edits the identifier by hand, after which the name stops
  // overwriting it — retyping a slug only to have it clobbered is maddening.
  const [slugTouched, setSlugTouched] = useState(false);

  const set = <K extends keyof typeof BLANK>(k: K, v: string) => setF((p) => ({ ...p, [k]: v }));

  const load = useCallback(() => {
    api.organizations().then(setRows).catch((e) => setError(e instanceof Error ? e.message : "Could not load organisations"));
    api.platformSummary().then(setSummary).catch(() => {});
  }, []);

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  useEffect(() => {
    if (me?.is_platform_admin) load();
  }, [me, load]);

  const openNew = () => {
    setF({ ...BLANK });
    setSlugTouched(false);
    setFormError(null);
    setShowForm(true);
  };

  async function save() {
    setSaving(true);
    setFormError(null);
    try {
      const created = await api.createOrganization({
        name: f.name.trim(),
        slug: (slugTouched ? f.slug : slugify(f.name)).trim(),
        admin_email: f.admin_email.trim(),
        admin_password: f.admin_password,
        admin_full_name: f.admin_full_name.trim(),
      });
      setShowForm(false);
      toast(`${created.name} created. Its admin signs in with the identifier "${created.slug}".`);
      load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not create the organisation");
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(org: Organization) {
    const suspending = org.is_active;
    const ok = await confirmDialog({
      title: suspending ? `Suspend ${org.name}?` : `Restore ${org.name}?`,
      message: suspending
        ? "Everyone in this organisation will be locked out at the login screen. Nothing is deleted — every record stays exactly where it is, and you can restore access at any time."
        : "People in this organisation will be able to sign in again.",
      confirmLabel: suspending ? "Suspend" : "Restore",
      danger: suspending,
    });
    if (!ok) return;
    try {
      await api.updateOrganization(org.id, { is_active: !org.is_active });
      toast(suspending ? `${org.name} suspended.` : `${org.name} restored.`);
      load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not update the organisation");
    }
  }

  const licence = useMemo(() => {
    const info = summary?.license as { status?: string; licensed_to?: string; expires?: string } | undefined;
    if (!info) return null;
    return info;
  }, [summary]);

  // ------------------------------------------------------------------ gating
  if (me && !me.is_platform_admin) {
    return (
      <>
        <div className="page-head">
          <h1>Organisations</h1>
          <p>Provisioning and running the organisations on this deployment.</p>
        </div>
        <div className="card card-pad">
          <p style={{ margin: 0 }}>
            This console is for whoever operates the deployment, not for organisation
            administrators, so it is gated separately from your role here.
          </p>
          <p className="muted" style={{ fontSize: 13 }}>
            Ask a platform administrator to grant you access if you need to create or
            suspend organisations. Your access inside{" "}
            <b>your own organisation</b> is unaffected.
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Organisations</h1>
          <p>
            Every organisation on this deployment. Each one is fully isolated: its users
            sign in with their own identifier and can reach nothing outside it.
          </p>
        </div>
        <button className="btn" onClick={openNew}>
          <IconPlus width={16} height={16} />
          Add organisation
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {summary && (
        <div className="card card-pad" style={{ marginBottom: 16, display: "flex", gap: 26, flexWrap: "wrap", alignItems: "center" }}>
          <div>
            <div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Organisations</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>
              {summary.active_organizations}
              <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}> active of {summary.organizations}</span>
            </div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Users</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{summary.users}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>Deployment</div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>{summary.deployment}</div>
          </div>
          {licence && (
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <div className="muted" style={{ fontSize: 12, fontWeight: 700 }}>
                <IconShield width={13} height={13} /> Licence
              </div>
              <div style={{ fontSize: 13 }}>
                <Badge tone={licence.status === "valid" ? "low" : "medium"}>{licence.status ?? "unknown"}</Badge>{" "}
                {licence.licensed_to && <span className="muted">{licence.licensed_to}</span>}
                {licence.expires && <span className="muted"> · expires {licence.expires}</span>}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Organisation</th>
                <th>Sign-in identifier</th>
                <th style={{ textAlign: "center" }}>Users</th>
                <th style={{ textAlign: "center" }}>Risks</th>
                <th style={{ textAlign: "center" }}>Controls</th>
                <th>Created</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows === null && (
                <tr><td colSpan={8} className="muted" style={{ padding: 18 }}>Loading organisations…</td></tr>
              )}
              {rows?.length === 0 && (
                <tr><td colSpan={8} className="muted" style={{ padding: 18 }}>No organisations yet.</td></tr>
              )}
              {rows?.map((org) => (
                <tr key={org.id}>
                  <td className="cell-title">{org.name}</td>
                  <td><span className="ref">{org.slug}</span></td>
                  <td style={{ textAlign: "center" }}>
                    {org.active_users}
                    {org.users !== org.active_users && (
                      <span className="muted"> / {org.users}</span>
                    )}
                  </td>
                  <td style={{ textAlign: "center" }} className="muted">{org.risks}</td>
                  <td style={{ textAlign: "center" }} className="muted">{org.controls}</td>
                  <td className="muted">{org.created_at?.slice(0, 10)}</td>
                  <td>
                    <Badge tone={org.is_active ? "low" : "neutral"}>
                      {org.is_active ? "Active" : "Suspended"}
                    </Badge>
                  </td>
                  <td>
                    <button className="btn secondary sm" onClick={() => toggleActive(org)}>
                      {org.is_active ? "Suspend" : "Restore"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="muted" style={{ fontSize: 12.5, marginTop: 12 }}>
        Counts are read inside each organisation&apos;s own scope — this console can see how
        much is there, never what is there. Suspending is reversible and deletes nothing.
      </p>

      {showForm && (
        <FormModal
          title="Add organisation"
          saving={saving}
          error={formError}
          saveLabel="Create organisation"
          onClose={() => setShowForm(false)}
          onSave={save}
          tabs={[{
            id: "org",
            label: "Organisation",
            required: true,
            content: (
              <>
                <Field label="Organisation name" required help="As it should appear on reports and PDF packs.">
                  <TextInput
                    value={f.name}
                    onChange={(v) => { set("name", v); if (!slugTouched) set("slug", slugify(v)); }}
                    placeholder="Meezan Bank"
                    required
                  />
                </Field>
                <Field
                  label="Sign-in identifier"
                  required
                  help="What this organisation's people type at the login screen, alongside their email. Lowercase letters, digits and hyphens."
                >
                  <TextInput
                    value={slugTouched ? f.slug : slugify(f.name)}
                    onChange={(v) => { setSlugTouched(true); set("slug", v); }}
                    placeholder="meezan"
                    required
                  />
                </Field>
                <Field label="First administrator — email" required help="This person receives the Admin role and can invite everyone else.">
                  <TextInput value={f.admin_email} onChange={(v) => set("admin_email", v)} type="email" placeholder="grc.admin@meezanbank.com" required />
                </Field>
                <Field label="First administrator — name">
                  <TextInput value={f.admin_full_name} onChange={(v) => set("admin_full_name", v)} placeholder="Ayesha Raza" />
                </Field>
                <Field
                  label="Temporary password"
                  required
                  help="Hand this over out of band. It must satisfy the deployment's password policy, and the administrator should change it at first sign-in."
                >
                  <TextInput value={f.admin_password} onChange={(v) => set("admin_password", v)} type="password" required />
                </Field>
              </>
            ),
          }]}
        />
      )}
    </>
  );
}
