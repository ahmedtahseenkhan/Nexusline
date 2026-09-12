"use client";

/* Pick a person — for every owner / assignee / reviewer / tester field.

     <Field label="Owner">
       <UserPicker
         value={form.owner_id}
         onChange={(id) => set("owner_id", id)}
         selected={record.owner}          // optional UserRef from the read schema: no lookup needed
         legacyText={record.owner_label}   // old free text, hinted until someone is picked
       />
     </Field>

   Searches `GET /pickers/users` as the user types (name or email; active users only),
   which any signed-in user may call — no `user:read` needed. Options show the name with
   the email beside it. A saved id whose user was deactivated still shows, marked
   "(deactivated)". In lists, render people with `<UserName user={row.owner} />`. */

import { useCallback, useEffect, useState } from "react";
import AsyncSelect, { type Option } from "@/components/AsyncSelect";
import { LegacyHint } from "@/components/LookupSelect";
import { pickUsers, usersById, type UserPick, type UserRef } from "@/lib/masterData";

export type UserPickerProps = {
  /** Selected user id, or null. */
  value: string | null;
  /** Called with the new id (null when cleared) and the picked person. */
  onChange: (id: string | null, ref?: UserRef | null) => void;
  placeholder?: string;
  /** The record's old free-text owner; hinted while `value` is null. */
  legacyText?: string | null;
  disabled?: boolean;
  /** The selected person as the record's read schema returned it (skips a lookup). */
  selected?: UserRef | null;
  /** Only offer holders of this role (role name, case-insensitive). */
  role?: string;
};

function nameOf(u: { full_name?: string; email?: string } | null | undefined): string {
  return (u?.full_name || "").trim() || u?.email || "";
}

/** Person picker. See the file header for behaviour. */
export default function UserPicker({
  value,
  onChange,
  placeholder = "Search people…",
  legacyText,
  disabled,
  selected,
  role,
}: UserPickerProps) {
  const [current, setCurrent] = useState<(UserRef & { is_active?: boolean }) | null>(
    selected && selected.id === value ? selected : null,
  );

  useEffect(() => {
    let live = true;
    if (!value) {
      setCurrent(null);
      return;
    }
    if (selected && selected.id === value) {
      setCurrent(selected);
      return;
    }
    if (current?.id === value) return;
    usersById([value])
      .then((m) => live && setCurrent(m[value] ?? { id: value, full_name: "Unknown user", email: "" }))
      .catch(() => live && setCurrent(null));
    return () => {
      live = false;
    };
  }, [value, selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const search = useCallback(
    async (q: string): Promise<Option[]> => {
      const page = await pickUsers({ search: q, role, limit: 20 });
      return page.items.map((u: UserPick) => ({
        value: u.id,
        label: nameOf(u),
        sub: u.full_name ? u.email : undefined,
      }));
    },
    [role],
  );

  const selectedLabel = !value
    ? undefined
    : current?.id === value
      ? `${nameOf(current)}${current.is_active === false ? " (deactivated)" : ""}`
      : "Loading…";

  return (
    <div>
      <AsyncSelect
        search={search}
        value={value}
        selectedLabel={selectedLabel}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(id, opt) => {
          if (!id) {
            setCurrent(null);
            onChange(null, null);
            return;
          }
          const ref: UserRef = { id, full_name: opt?.label ?? "", email: opt?.sub ?? (opt?.label?.includes("@") ? opt.label : "") };
          setCurrent(ref);
          onChange(id, ref);
        }}
      />
      <LegacyHint value={value} legacyText={legacyText} />
    </div>
  );
}

/** A person's name for tables and detail panes: the name (email as tooltip), the email
 *  when there is no name, else `fallback` (e.g. the legacy free text) or "—". */
export function UserName({ user, fallback }: { user?: UserRef | null; fallback?: string | null }) {
  if (!user) return <span className={fallback ? undefined : "muted"}>{fallback || "—"}</span>;
  const name = nameOf(user);
  return <span title={user.email || undefined}>{name || "—"}</span>;
}
