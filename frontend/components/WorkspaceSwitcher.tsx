"use client";

/* Workspace switcher in the header — shown only to someone with more than one
   workspace (My Work, Risk dashboard, Assurance, Board). The label is the workspace the
   current page belongs to; each item opens that workspace, and the one they start on
   after sign-in is marked. The start page itself is chosen in Settings → Start page. */

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Menu from "@/components/Menu";
import { getWorkspace, type Workspace } from "@/lib/landing";

export default function WorkspaceSwitcher() {
  const pathname = usePathname();
  const router = useRouter();
  const [ws, setWs] = useState<Workspace | null>(null);

  useEffect(() => {
    getWorkspace().then(setWs).catch(() => setWs(null));
  }, []);

  if (!ws || ws.available.length < 2) return null;
  const current = ws.available.find((w) => pathname === w.href || pathname.startsWith(`${w.href}/`));
  return (
    <Menu
      align="right"
      className="btn secondary sm"
      ariaLabel={`Workspace: ${current ? current.label : "choose a workspace"}`}
      label={<span>{current ? current.label : "Workspaces"} ▾</span>}
      items={ws.available.map((w) => ({
        label: w.key === ws.landing ? `${w.label} (your start page)` : w.label,
        hint: w.description,
        onClick: () => router.push(w.href),
      }))}
    />
  );
}
