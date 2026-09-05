"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
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
  framework_id: string | null;
  /** A catalogue of controls (ISO 27001 Annex A, CIS, SBP Cybersecurity, …) rather
   *  than management clauses — installing it also populates the Control Catalogue. */
  is_control_framework: boolean;
  control_count: number;
  controls_present: number;
  controls_total: number;
};

type InstallResult = {
  framework_id: string;
  name: string;
  requirement_count: number;
  controls_created: number;
  controls_linked: number;
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

  // Per pack: whether installing also creates its controls. On by default for control
  // frameworks — a clause like "A.8.5 Secure authentication" is a control, and a
  // framework installed without its controls is a checklist with nothing behind it.
  // Duplicate protection makes the default safe: an existing control with that
  // reference is linked, not recreated.
  const [withControls, setWithControls] = useState<Record<string, boolean>>({});
  const createControls = (pack: ContentPack) => withControls[pack.id] ?? true;

  /** The upgrade path: a framework installed before the controls pack existed. */
  async function installControls(pack: ContentPack) {
    setError(null);
    setInstallingId(pack.id);
    try {
      const res = await apiCall<InstallResult>("POST", `/content-library/${pack.id}/install-controls`);
      toast(`${res.name}: ${res.controls_created} controls created${res.controls_linked ? `, ${res.controls_linked} linked to existing` : ""}. They are in the Control Catalogue, linked to their clauses.`);
      await loadPacks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create the controls");
    } finally {
      setInstallingId(null);
    }
  }

  async function install(pack: ContentPack) {
    setError(null);
    setInstallingId(pack.id);
    try {
      const flag = pack.is_control_framework ? `?create_controls=${createControls(pack)}` : "";
      const res = await apiCall<InstallResult>("POST", `/content-library/${pack.id}/install${flag}`);
      const controls = res.controls_created || res.controls_linked
        ? ` ${res.controls_created} controls created${res.controls_linked ? `, ${res.controls_linked} linked to existing` : ""}.`
        : "";
      toast(`Installed ${res.name} — ${res.requirement_count} requirements added.${controls} It now appears in Compliance.`);
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
                {p.is_control_framework && <Badge tone="low" plain>{p.control_count} controls</Badge>}
              </div>

              {p.is_control_framework && !p.installed && (
                <label style={{ display: "flex", alignItems: "flex-start", gap: 8, fontSize: 12.5, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={createControls(p)}
                    onChange={(e) => setWithControls((m) => ({ ...m, [p.id]: e.target.checked }))}
                    style={{ marginTop: 3 }}
                  />
                  <span>
                    Also create its {p.control_count} controls in the Control Catalogue, linked to their clauses.
                    <span className="muted"> Generated risks link to them automatically. An existing control with the same reference is linked, not duplicated.</span>
                  </span>
                </label>
              )}

              {p.installed && p.is_control_framework && p.controls_present < p.controls_total && (
                <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, padding: "8px 10px", borderRadius: 8, background: "var(--amber-bg)", color: "var(--amber)" }}>
                  <span style={{ flex: 1 }}>
                    Installed without its controls — {p.controls_present} of {p.controls_total} clauses have a control behind them.
                  </span>
                  <button className="btn secondary sm" disabled={installingId === p.id} onClick={() => installControls(p)}>
                    {installingId === p.id ? "Creating…" : `Create ${p.controls_total - p.controls_present} controls`}
                  </button>
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                {p.installed ? (
                  p.framework_id ? (
                    <Link
                      className="btn secondary"
                      href={`/compliance?framework=${p.framework_id}`}
                      title="Open this framework's requirements in the Compliance module"
                    >
                      Open in Compliance
                    </Link>
                  ) : (
                    <button className="btn secondary" disabled>Installed</button>
                  )
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
