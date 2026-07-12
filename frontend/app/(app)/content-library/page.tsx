"use client";

import { useEffect, useMemo, useState } from "react";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { Badge } from "@/components/badges";
import { IconCompliance } from "@/components/icons";

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
  const [query, setQuery] = useState("");

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
    setInstallingId(pack.id);
    try {
      const res = await apiCall<InstallResult>("POST", `/content-library/${pack.id}/install`);
      toast(`Installed ${res.name} — ${res.requirement_count} requirements added. It now appears in Compliance.`);
      await loadPacks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to install framework pack");
    } finally {
      setInstallingId(null);
    }
  }

  const installedCount = packs.filter((p) => p.installed).length;
  const visiblePacks = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return packs;
    return packs.filter((p) =>
      [p.name, p.standard, p.description, p.domain].some((v) => (v || "").toLowerCase().includes(q)),
    );
  }, [packs, query]);

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

      {!loading && packs.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <input
            className="input"
            style={{ maxWidth: 320 }}
            placeholder="Search framework packs…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
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
      ) : visiblePacks.length === 0 ? (
        <div className="empty">
          <span className="ico"><IconCompliance width={24} height={24} /></span>
          <h3>No matching packs</h3>
          <p>No framework packs match &ldquo;{query}&rdquo;.</p>
        </div>
      ) : (
        <div
          className="grid"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
        >
          {visiblePacks.map((p) => (
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
