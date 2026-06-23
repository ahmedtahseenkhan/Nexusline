"use client";

import { useEffect, useState } from "react";
import { apiCall } from "@/lib/api";
import { Badge } from "@/components/badges";
import ImportExport from "@/components/ImportExport";

interface IoResource {
  resource: string;
  label: string;
  importable: boolean;
  write_perm?: boolean;
}

export default function DataIoPage() {
  const [resources, setResources] = useState<IoResource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiCall<IoResource[]>("GET", "/io/resources")
      .then((r) => setResources(r))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load resources"))
      .finally(() => setLoading(false));
  }, []);

  const sorted = [...resources].sort((a, b) => a.label.localeCompare(b.label));

  return (
    <>
      <div className="page-head">
        <h1>Import &amp; Export</h1>
        <p>
          Move data in and out of NexusLine as CSV. Download a template (it contains the column
          headers and one example row) or export every record for a module. On import, each row is
          validated and any problems are reported back per line so you can fix and retry.
        </p>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="card">
        <div className="card-head">
          <h3>Modules</h3>
          <span className="sub">
            {loading ? "Loading…" : `${sorted.length} available`}
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Module</th>
                <th>Mode</th>
                <th style={{ textAlign: "right" }}>Data transfer</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.resource}>
                  <td className="cell-title">{r.label}</td>
                  <td>
                    {r.importable ? (
                      <Badge tone="info">Importable</Badge>
                    ) : (
                      <Badge tone="neutral">Export only</Badge>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <div style={{ display: "inline-flex", justifyContent: "flex-end" }}>
                      <ImportExport resource={r.resource} label={r.label} />
                    </div>
                  </td>
                </tr>
              ))}
              {!loading && sorted.length === 0 && !error && (
                <tr>
                  <td colSpan={3}>
                    <div className="empty">
                      <h3>Nothing to transfer yet</h3>
                      <p>No importable or exportable modules are available for your account.</p>
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
