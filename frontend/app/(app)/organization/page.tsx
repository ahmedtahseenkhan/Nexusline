"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { useRecordParam } from "@/lib/useRecordParam";
import { confirmDialog, toast } from "@/lib/feedback";
import DataTable, { type Column } from "@/components/DataTable";
import RecordDrawer from "@/components/RecordDrawer";
import FormModal from "@/components/FormModal";
import { Field, TextInput, TextArea, Toggle, MultiSelect, type Option } from "@/components/fields";
import { Badge } from "@/components/badges";
import { IconPlus, IconShield, IconUsers } from "@/components/icons";

// ----------------------------------------------------------------- inline API types
type RoleSummary = { id: string; name: string; description: string };
type UserRecord = {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
  permission_codes: string[];
  roles: RoleSummary[];
};
type RoleRecord = {
  id: string;
  name: string;
  description: string;
  is_system: boolean;
  permission_codes: string[];
};
type Permission = { code: string; description: string };
type Page<T> = { items: T[]; total: number; limit: number; offset: number };

// --------------------------------------------------------------------------- helpers
const cap = (s: string) => s.replace(/[:_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
const fmtDate = (s: string | null) => (s ? new Date(s).toLocaleDateString() : "—");
const resourceOf = (code: string) => code.split(":")[0] || "other";

// ----------------------------------------------------------------------- user dialog
type UserForm = {
  full_name: string;
  email: string;
  is_active: boolean;
  role_names: string[];
  password: string;
};
const BLANK_USER: UserForm = { full_name: "", email: "", is_active: true, role_names: ["Viewer"], password: "" };

// ----------------------------------------------------------------------- role dialog
type RoleForm = { name: string; description: string; permission_codes: string[] };
const BLANK_ROLE: RoleForm = { name: "", description: "", permission_codes: [] };

function OrganizationInner() {
  const [view, setView] = useState<"users" | "roles">("users");

  const [roles, setRoles] = useState<RoleRecord[]>([]);
  const [perms, setPerms] = useState<Permission[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [userTotal, setUserTotal] = useState<number | null>(null);

  // user dialog state
  const [editingUser, setEditingUser] = useState<UserRecord | null>(null);
  const [showUser, setShowUser] = useState(false);
  const [uf, setUf] = useState<UserForm>(BLANK_USER);
  const [savingUser, setSavingUser] = useState(false);

  // read-only view drawer for the Users register (?id=)
  const [recordId, setRecordId] = useRecordParam("id");
  const [detail, setDetail] = useState<UserRecord | null>(null);
  const loadDetail = useCallback((id: string) => {
    apiCall<UserRecord>("GET", `/users/${id}`).then(setDetail).catch(() => setDetail(null));
  }, []);
  useEffect(() => {
    if (recordId) loadDetail(recordId);
    else setDetail(null);
  }, [recordId, loadDetail]);

  // role dialog state
  const [editingRole, setEditingRole] = useState<RoleRecord | null>(null);
  const [showRole, setShowRole] = useState(false);
  const [rf, setRf] = useState<RoleForm>(BLANK_ROLE);
  const [savingRole, setSavingRole] = useState(false);

  const setU = <K extends keyof UserForm>(k: K, v: UserForm[K]) => setUf((p) => ({ ...p, [k]: v }));
  const setR = <K extends keyof RoleForm>(k: K, v: RoleForm[K]) => setRf((p) => ({ ...p, [k]: v }));

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);
  const fetchUsers = useCallback(
    (qs: string) => apiCall<Page<UserRecord>>("GET", `/users?${qs}`),
    [],
  );

  async function loadRoles() {
    try {
      setRoles(await apiCall<RoleRecord[]>("GET", "/users/roles"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load roles");
    }
  }
  useEffect(() => {
    loadRoles();
    apiCall<Permission[]>("GET", "/users/permissions").then(setPerms).catch(() => {});
  }, []);
  // Keep the Users tab badge count in sync with the server-driven table.
  useEffect(() => {
    apiCall<Page<UserRecord>>("GET", "/users?limit=1")
      .then((r) => setUserTotal(r.total))
      .catch(() => {});
  }, [refreshKey]);

  // -------------------------------------------------------------------- option lists
  const roleOpts: Option[] = useMemo(
    () => roles.map((r) => ({ value: r.name, label: r.name, sub: r.description || undefined })),
    [roles],
  );
  const permOpts: Option[] = useMemo(
    () =>
      [...perms]
        .sort((a, b) => a.code.localeCompare(b.code))
        .map((p) => ({ value: p.code, label: p.description || cap(p.code), sub: p.code })),
    [perms],
  );
  const permLabel = useMemo(() => new Map(perms.map((p) => [p.code, p.description || cap(p.code)])), [perms]);
  const roleByName = useMemo(() => new Map(roles.map((r) => [r.name, r])), [roles]);

  // Effective permissions implied by the roles selected in the user dialog.
  const effectivePerms = useMemo(() => {
    const set = new Set<string>();
    for (const name of uf.role_names) {
      const r = roleByName.get(name);
      if (r) r.permission_codes.forEach((c) => set.add(c));
    }
    return [...set].sort();
  }, [uf.role_names, roleByName]);

  // ----------------------------------------------------------------------- user CRUD
  function openNewUser() {
    setEditingUser(null);
    setUf(BLANK_USER);
    setError(null);
    setShowUser(true);
  }
  function openEditUser(u: UserRecord) {
    setEditingUser(u);
    setUf({
      full_name: u.full_name,
      email: u.email,
      is_active: u.is_active,
      role_names: u.roles.map((r) => r.name),
      password: "",
    });
    setError(null);
    setShowUser(true);
  }
  async function saveUser() {
    setError(null);
    setSavingUser(true);
    try {
      if (editingUser) {
        await apiCall<UserRecord>("PATCH", `/users/${editingUser.id}`, {
          full_name: uf.full_name,
          is_active: uf.is_active,
          role_names: uf.role_names,
        });
        if (uf.password.trim()) {
          await apiCall<UserRecord>("POST", `/users/${editingUser.id}/password`, { password: uf.password });
        }
      } else {
        await apiCall<UserRecord>("POST", "/users", {
          email: uf.email,
          full_name: uf.full_name,
          password: uf.password,
          is_active: uf.is_active,
          role_names: uf.role_names,
        });
      }
      const wasEditing = !!editingUser;
      setShowUser(false);
      reload();
      if (recordId) loadDetail(recordId); // refresh the open view drawer
      toast(wasEditing ? "Changes saved" : "User created");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save user");
    } finally {
      setSavingUser(false);
    }
  }
  async function toggleActive(u: UserRecord) {
    setError(null);
    try {
      await apiCall<UserRecord>("POST", `/users/${u.id}/${u.is_active ? "deactivate" : "activate"}`);
      toast(`${u.is_active ? "Deactivated" : "Activated"} ${u.email}`);
      reload();
      if (recordId) loadDetail(recordId); // refresh the open view drawer
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update status");
    }
  }

  // ----------------------------------------------------------------------- role CRUD
  function openNewRole() {
    setEditingRole(null);
    setRf(BLANK_ROLE);
    setError(null);
    setShowRole(true);
  }
  function openEditRole(r: RoleRecord) {
    setEditingRole(r);
    setRf({ name: r.name, description: r.description, permission_codes: [...r.permission_codes] });
    setError(null);
    setShowRole(true);
  }
  async function saveRole() {
    setError(null);
    setSavingRole(true);
    try {
      if (editingRole) {
        const payload: Record<string, unknown> = {
          description: rf.description,
          permission_codes: rf.permission_codes,
        };
        if (!editingRole.is_system) payload.name = rf.name;
        await apiCall<RoleRecord>("PATCH", `/users/roles/${editingRole.id}`, payload);
      } else {
        await apiCall<RoleRecord>("POST", "/users/roles", {
          name: rf.name,
          description: rf.description,
          permission_codes: rf.permission_codes,
        });
      }
      setShowRole(false);
      await loadRoles();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save role");
    } finally {
      setSavingRole(false);
    }
  }
  async function deleteRole(r: RoleRecord) {
    if (!window.confirm(`Delete role "${r.name}"? This cannot be undone.`)) return;
    setError(null);
    try {
      await apiCall<void>("DELETE", `/users/roles/${r.id}`);
      toast(`Deleted role ${r.name}`);
      await loadRoles();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete role");
    }
  }

  // bulk-select helpers for the role permission picker
  const selectAllPerms = () => setR("permission_codes", perms.map((p) => p.code));
  const clearPerms = () => setR("permission_codes", []);
  const selectResource = (resource: string) => {
    const codes = perms.filter((p) => resourceOf(p.code) === resource).map((p) => p.code);
    setR("permission_codes", [...new Set([...rf.permission_codes, ...codes])]);
  };
  const resources = useMemo(
    () => [...new Set(perms.map((p) => resourceOf(p.code)))].sort(),
    [perms],
  );

  // ------------------------------------------------------------------- dialog tabs
  const userGeneralTab = (
    <>
      <Field label="Full name" help="The person's display name shown across the app.">
        <TextInput value={uf.full_name} onChange={(v) => setU("full_name", v)} placeholder="Jane Doe" />
      </Field>
      <Field label="Email" required help={editingUser ? "Email is the account identity and can't be changed here." : "Used to sign in. Must be unique within the organization."}>
        {editingUser ? (
          <input className="input" value={uf.email} disabled />
        ) : (
          <TextInput value={uf.email} onChange={(v) => setU("email", v)} type="email" placeholder="jane@acme.com" required />
        )}
      </Field>
      <Field label="Account status" help="Inactive users keep their data and roles but cannot sign in.">
        <Toggle checked={uf.is_active} onChange={(v) => setU("is_active", v)} label={uf.is_active ? "Active" : "Inactive"} />
      </Field>
    </>
  );

  const userAccessTab = (
    <>
      <Field label="Roles" help="Roles grant permissions. A user's effective permissions are the union of all assigned roles.">
        <MultiSelect value={uf.role_names} onChange={(v) => setU("role_names", v)} options={roleOpts} />
      </Field>
      <Field
        label={editingUser ? "Reset password" : "Initial password"}
        required={!editingUser}
        help={editingUser ? "Leave blank to keep the current password. Minimum 8 characters." : "Set the user's first password. Minimum 8 characters."}
      >
        <TextInput
          value={uf.password}
          onChange={(v) => setU("password", v)}
          type="password"
          placeholder={editingUser ? "••••••••" : "At least 8 characters"}
          required={!editingUser}
        />
      </Field>
      <Field label="Effective permissions" help="Derived from the selected roles — read-only preview.">
        {effectivePerms.length === 0 ? (
          <span className="muted">No permissions (no roles selected).</span>
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {effectivePerms.map((c) => (
              <Badge key={c} tone="info" plain>{permLabel.get(c) || cap(c)}</Badge>
            ))}
          </div>
        )}
      </Field>
    </>
  );

  const roleGeneralTab = (
    <>
      <Field label="Name" required help={editingRole?.is_system ? "System roles are built-in and cannot be renamed." : "For example: Auditor, Privacy Officer, Risk Approver."}>
        {editingRole?.is_system ? (
          <input className="input" value={rf.name} disabled />
        ) : (
          <TextInput value={rf.name} onChange={(v) => setR("name", v)} placeholder="Privacy Officer" required />
        )}
      </Field>
      <Field label="Description">
        <TextArea value={rf.description} onChange={(v) => setR("description", v)} rows={2} placeholder="What this role is allowed to do." />
      </Field>
    </>
  );

  const rolePermsTab = (
    <>
      <Field label="Permissions" help="Grant the capabilities this role should have. Permissions follow a resource:action convention.">
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 10 }}>
          <button type="button" className="btn secondary sm" onClick={selectAllPerms}>Select all</button>
          <button type="button" className="btn secondary sm" onClick={clearPerms}>Clear</button>
          {resources.map((res) => (
            <button key={res} type="button" className="btn secondary sm" onClick={() => selectResource(res)}>
              + {cap(res)}
            </button>
          ))}
        </div>
        <MultiSelect value={rf.permission_codes} onChange={(v) => setR("permission_codes", v)} options={permOpts} />
      </Field>
      <Field label="Selected" help={`${rf.permission_codes.length} permission(s) selected.`}>
        {rf.permission_codes.length === 0 ? (
          <span className="muted">No permissions selected.</span>
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {[...rf.permission_codes].sort().map((c) => (
              <Badge key={c} tone="neutral" plain>{c}</Badge>
            ))}
          </div>
        )}
      </Field>
    </>
  );

  const userColumns: Column<UserRecord>[] = [
    { key: "full_name", header: "User", sortable: true, render: (u) => <span className="cell-title">{u.full_name || u.email.split("@")[0]}</span> },
    { key: "email", header: "Email", sortable: true, render: (u) => <span className="muted">{u.email}</span> },
    { key: "roles", header: "Roles", render: (u) => <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{u.roles.length === 0 && <span className="muted">—</span>}{u.roles.map((r) => <Badge key={r.id} tone="info" plain>{r.name}</Badge>)}</div> },
    { key: "permissions", header: "Permissions", align: "center", render: (u) => <span className="muted">{u.permission_codes.length}</span> },
    { key: "is_active", header: "Status", sortable: true, render: (u) => <Badge tone={u.is_active ? "low" : "neutral"}>{u.is_active ? "active" : "inactive"}</Badge> },
    { key: "created_at", header: "Created", sortable: true, render: (u) => <span className="muted">{fmtDate(u.created_at)}</span> },
    { key: "actions", header: "", render: (u) => <div onClick={(e) => e.stopPropagation()}><button className="btn secondary sm" onClick={() => openEditUser(u)}>Edit</button> <button className="btn secondary sm" onClick={() => toggleActive(u)}>{u.is_active ? "Deactivate" : "Activate"}</button></div> },
  ];

  // ------------------------------------------------------------------------- render
  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Organization</h1>
          <p>Administer users, roles and the permissions that govern access across your organization.</p>
        </div>
        <button className="btn" onClick={view === "users" ? openNewUser : openNewRole}>
          <IconPlus width={16} height={16} /> {view === "users" ? "Add user" : "Add role"}
        </button>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        <button className={`btn ${view === "users" ? "" : "secondary"}`} onClick={() => setView("users")}>
          <IconUsers width={15} height={15} /> Users <Badge tone="neutral" plain>{userTotal ?? 0}</Badge>
        </button>
        <button className={`btn ${view === "roles" ? "" : "secondary"}`} onClick={() => setView("roles")}>
          <IconShield width={15} height={15} /> Roles <Badge tone="neutral" plain>{roles.length}</Badge>
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {view === "users" && (
        <DataTable<UserRecord>
          columns={userColumns}
          fetcher={fetchUsers}
          rowKey={(u) => u.id}
          onRowClick={(u) => setRecordId(u.id)}
          activeKey={recordId ?? undefined}
          searchPlaceholder="Search users by name or email…"
          defaultSort={{ by: "email", dir: "asc" }}
          emptyMessage="No users yet. Invite your first teammate to get started."
          refreshKey={refreshKey}
        />
      )}

      {view === "roles" && (
        <div className="card">
          <div className="card-head">
            <h3>Roles & permissions</h3>
            <span className="sub">{roles.length} roles</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Description</th>
                  <th>Type</th>
                  <th>Permissions</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {roles.map((r) => (
                  <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openEditRole(r)}>
                    <td className="cell-title">{r.name}</td>
                    <td className="muted">{r.description || "—"}</td>
                    <td>
                      {r.is_system ? <Badge tone="info">system</Badge> : <Badge tone="neutral" plain>custom</Badge>}
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                        <Badge tone="neutral" plain>{r.permission_codes.length}</Badge>
                        {r.permission_codes.slice(0, 4).map((c) => (
                          <Badge key={c} tone="info" plain>{c}</Badge>
                        ))}
                        {r.permission_codes.length > 4 && (
                          <span className="muted">+{r.permission_codes.length - 4} more</span>
                        )}
                      </div>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }} onClick={(e) => e.stopPropagation()}>
                        <button className="btn secondary sm" onClick={() => openEditRole(r)}>Edit</button>
                        {!r.is_system && (
                          <button className="btn secondary sm danger" onClick={() => deleteRole(r)}>Delete</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {roles.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <div className="empty">
                        <span className="ico"><IconShield width={24} height={24} /></span>
                        <h3>No roles</h3>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ===================== USER — read-only detail view (?id=) */}
      <RecordDrawer
        open={!!recordId && !!detail}
        onClose={() => setRecordId(null)}
        title={detail ? detail.full_name || detail.email.split("@")[0] : "…"}
        subtitle={detail ? detail.email : ""}
        width={620}
        actions={detail && (
          <>
            <button className="btn secondary sm" onClick={() => openEditUser(detail)}>Edit</button>
            <button className="btn secondary sm" onClick={() => toggleActive(detail)}>
              {detail.is_active ? "Deactivate" : "Activate"}
            </button>
          </>
        )}
      >
        {detail && (
          <>
            <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginBottom: 18 }}>
              <div style={{ minWidth: 140 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Email</div>
                <div style={{ marginTop: 3 }}>{detail.email}</div>
              </div>
              <div style={{ minWidth: 140 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Full name</div>
                <div style={{ marginTop: 3 }}>{detail.full_name || <span className="muted">—</span>}</div>
              </div>
              <div style={{ minWidth: 140 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Status</div>
                <div style={{ marginTop: 3 }}>
                  <Badge tone={detail.is_active ? "low" : "neutral"}>{detail.is_active ? "active" : "inactive"}</Badge>
                </div>
              </div>
              <div style={{ minWidth: 140 }}>
                <div className="muted" style={{ fontSize: 12, fontWeight: 600 }}>Created</div>
                <div style={{ marginTop: 3 }}>{fmtDate(detail.created_at)}</div>
              </div>
            </div>

            <div style={{ marginBottom: 18 }}>
              <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>Roles</div>
              {detail.roles.length === 0 ? (
                <span className="muted">No roles assigned.</span>
              ) : (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {detail.roles.map((r) => <Badge key={r.id} tone="info" plain>{r.name}</Badge>)}
                </div>
              )}
            </div>

            <div>
              <div className="muted" style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                Effective permissions ({detail.permission_codes.length})
              </div>
              {detail.permission_codes.length === 0 ? (
                <span className="muted">No permissions.</span>
              ) : (
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {[...detail.permission_codes].sort().map((c) => (
                    <Badge key={c} tone="neutral" plain>{permLabel.get(c) || cap(c)}</Badge>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </RecordDrawer>

      {showUser && (
        <FormModal
          title={editingUser ? `Edit user — ${editingUser.email}` : "Add user"}
          tabs={[
            { id: "general", label: "General", content: userGeneralTab, required: true },
            { id: "access", label: "Roles & Access", content: userAccessTab },
          ]}
          onClose={() => setShowUser(false)}
          onSave={saveUser}
          saving={savingUser}
          error={error}
          saveLabel={editingUser ? "Save changes" : "Create user"}
          footerLeft={
            editingUser ? (
              <button
                type="button"
                className="btn secondary sm"
                onClick={() => { setShowUser(false); toggleActive(editingUser); }}
              >
                {editingUser.is_active ? "Deactivate user" : "Activate user"}
              </button>
            ) : undefined
          }
        />
      )}

      {showRole && (
        <FormModal
          title={editingRole ? `Edit role — ${editingRole.name}` : "Add role"}
          tabs={[
            { id: "general", label: "General", content: roleGeneralTab, required: true },
            { id: "perms", label: "Permissions", content: rolePermsTab },
          ]}
          onClose={() => setShowRole(false)}
          onSave={saveRole}
          saving={savingRole}
          error={error}
          saveLabel={editingRole ? "Save changes" : "Create role"}
          footerLeft={
            editingRole && !editingRole.is_system ? (
              <button
                type="button"
                className="btn secondary sm danger"
                onClick={() => { setShowRole(false); deleteRole(editingRole); }}
              >
                Delete role
              </button>
            ) : undefined
          }
        />
      )}
    </>
  );
}

export default function OrganizationPage() {
  return (
    <Suspense fallback={null}>
      <OrganizationInner />
    </Suspense>
  );
}
