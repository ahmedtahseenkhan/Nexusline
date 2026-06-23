"use client";

import { useEffect, useState } from "react";
import { api, type UserRow } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconPlus, IconUsers } from "@/components/icons";

const ROLES = ["Admin", "Risk Manager", "Risk Approver", "Compliance Manager", "Auditor", "Viewer"];

export default function OrganizationPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("Viewer");

  async function load() {
    try {
      setUsers((await api.users()).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.createUser({ email, full_name: fullName, password, role_names: [role] });
      setShowForm(false);
      setEmail("");
      setFullName("");
      setPassword("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create user");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Organization</h1>
          <p>Users, roles and access across your organization.</p>
        </div>
        <button className="btn" onClick={() => setShowForm((v) => !v)}>
          <IconPlus width={16} height={16} />
          {showForm ? "Close" : "Invite user"}
        </button>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {showForm && (
        <form className="card card-pad" style={{ marginBottom: 18 }} onSubmit={create}>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 240px" }}>
              <label className="label">Email</label>
              <input className="input" type="email" value={email} required onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div style={{ flex: "1 1 200px" }}>
              <label className="label">Full name</label>
              <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </div>
            <div style={{ width: 180 }}>
              <label className="label">Password</label>
              <input className="input" type="password" value={password} required minLength={8} onChange={(e) => setPassword(e.target.value)} />
            </div>
            <div style={{ width: 200 }}>
              <label className="label">Role</label>
              <select className="select" value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn" style={{ marginTop: 16 }}>Create user</button>
        </form>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Members</h3>
          <span className="sub">{users.length} users</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Roles</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="cell-title">{u.full_name || u.email.split("@")[0]}</td>
                  <td className="muted">{u.email}</td>
                  <td>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      {u.roles.map((r) => (
                        <Badge key={r.name} tone="info" plain>{r.name}</Badge>
                      ))}
                    </div>
                  </td>
                  <td>
                    <Badge tone={u.is_active ? "low" : "neutral"}>{u.is_active ? "active" : "inactive"}</Badge>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={4}>
                    <div className="empty">
                      <span className="ico"><IconUsers width={24} height={24} /></span>
                      <h3>No users</h3>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
