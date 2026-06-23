"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import { api, getToken, type Me } from "@/lib/api";

export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/");
      return;
    }
    api
      .me()
      .then((u) => {
        setUser(u);
        setReady(true);
      })
      .catch(() => {
        router.replace("/");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!ready) {
    return (
      <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
        <span className="muted">Loading…</span>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="main">
        <Topbar user={user} />
        <main className="content">{children}</main>
      </div>
    </div>
  );
}
