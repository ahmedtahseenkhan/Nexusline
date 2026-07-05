"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import { IconCompliance, IconCheck } from "@/components/icons";

// ------------------------------------------------------------------ types
type ContentPack = {
  id: string;
  name: string;
  standard: string;
  description: string;
  domain: string;
  requirement_count: number;
  installed: boolean;
};

type InstallResult = {
  framework_id: string;
  name: string;
  requirement_count: number;
};

export default function ContentLibraryPage() {
  const [packs, setPacks] = useState<ContentPack[]>([]);
  const [loading, setLoading] = useState(true);
  const [installingId, setInstallingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function loadPacks() {
    try {
      setPacks(await apiCall<ContentPack[]>("GET", "/content-library"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load the content library");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadPacks();
  }, []);

  async function install(pack: ContentPack) {
    setError(null);
    setNotice(null);
    setInstallingId(pack.id);
    try {
      const res = await apiCall<InstallResult>("POST", `/content-library/${pack.id}/install`);
      setNotice(`Installed ${res.name} — ${res.requirement_count} requirements added. It now appears in Compliance.`);
      await loadPacks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to install framework pack");
    } finally {
      setInstallingId(null);
    }
  }

  const installedCount = packs.filter((p) => p.installed).length;

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Framework Library</h1>
          <p>
            Install preloaded, banking-relevant framework packs. Each pack creates a framework and
            all of its requirements — ready to map controls, collect evidence and track coverage in the
            Compliance module.
          </p>
        </div>
        <Badge tone="info" plain>
          {installedCount} of {packs.length} installed
        </Badge>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}
      {notice && (
        <div
          className="card card-pad"
          style={{
            marginBottom: 16,
            display: "flex",
            alignItems: "center",
            gap: 10,
            color: "var(--green)",
            background: "var(--green-bg)",
          }}
        >
          <IconCheck width={18} height={18} />
          <span>{notice}</span>
        </div>
      )}

      {loading ? (
        <div className="empty"><p>Loading…</p></div>
      ) : packs.length === 0 ? (
        <div className="empty">
          <span className="ico"><IconCompliance width={24} height={24} /></span>
          <h3>No framework packs</h3>
          <p>There are no framework packs available to install.</p>
        </div>
      ) : (
        <div
          className="grid"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
        >
          {packs.map((p) => (
            <div
              key={p.id}
              className="card card-pad"
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12 }}>
                <div>
                  <div className="cell-title" style={{ fontSize: 15, marginBottom: 3 }}>{p.name}</div>
                  <div className="ref">{p.standard}</div>
                </div>
                {p.installed && <Badge tone="low">Installed</Badge>}
              </div>

              <p className="muted" style={{ fontSize: 13, margin: 0, flex: 1 }}>{p.description}</p>

              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <Badge tone="info">{p.domain}</Badge>
                <Badge tone="neutral" plain>{p.requirement_count} requirements</Badge>
              </div>

              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                {p.installed ? (
                  <button className="btn secondary" disabled>Installed</button>
                ) : (
                  <button
                    className="btn"
                    disabled={installingId === p.id}
                    onClick={() => install(p)}
                  >
                    {installingId === p.id ? "Installing…" : "Install"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
