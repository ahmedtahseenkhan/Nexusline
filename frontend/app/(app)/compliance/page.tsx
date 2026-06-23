"use client";

import { useEffect, useState } from "react";
import {
  api,
  type CrosswalkItem,
  type Evidence,
  type Framework,
  type GapAnalysis,
  type Requirement,
} from "@/lib/api";
import { Badge, ComplianceBadge } from "@/components/badges";
import { IconCompliance } from "@/components/icons";

export default function CompliancePage() {
  const [frameworks, setFrameworks] = useState<Framework[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [gap, setGap] = useState<GapAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [openReq, setOpenReq] = useState<Requirement | null>(null);
  const [crosswalks, setCrosswalks] = useState<CrosswalkItem[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);

  useEffect(() => {
    api
      .frameworks()
      .then((fw) => {
        setFrameworks(fw.items);
        if (fw.items.length) setSelected(fw.items[0].id);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setOpenReq(null);
    Promise.all([api.requirements(selected), api.gapAnalysis(selected)])
      .then(([reqs, g]) => {
        setRequirements(reqs);
        setGap(g);
      })
      .catch((e) => setError(e.message));
  }, [selected]);

  async function openRequirement(r: Requirement) {
    if (openReq?.id === r.id) {
      setOpenReq(null);
      return;
    }
    setOpenReq(r);
    setCrosswalks([]);
    setEvidence([]);
    try {
      const [cw, ev] = await Promise.all([
        api.requirementCrosswalks(r.id),
        api.requirementEvidence(r.id),
      ]);
      setCrosswalks(cw);
      setEvidence(ev);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load detail");
    }
  }

  return (
    <>
      <div className="page-head row-between">
        <div>
          <h1>Compliance Management</h1>
          <p>Map controls to requirements, crosswalk frameworks, and collect evidence.</p>
        </div>
        <select
          className="select"
          style={{ width: 280 }}
          value={selected || ""}
          onChange={(e) => setSelected(e.target.value)}
        >
          {frameworks.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name} ({f.requirement_count})
            </option>
          ))}
        </select>
      </div>

      {error && <div className="error" style={{ marginBottom: 16 }}>{error}</div>}

      {gap && (
        <div className="grid stat-grid">
          <div className="card stat">
            <div className="stat-top"><span className="n">{gap.total_requirements}</span></div>
            <span className="l">Requirements</span>
          </div>
          <div className="card stat ok">
            <div className="stat-top"><span className="n" style={{ color: "var(--green)" }}>{gap.compliant_pct}%</span></div>
            <span className="l">Compliant</span>
            <div className="progress" style={{ marginTop: 4 }}>
              <span style={{ width: `${gap.compliant_pct}%` }} />
            </div>
          </div>
          <div className="card stat">
            <div className="stat-top"><span className="n">{gap.covered}/{gap.total_requirements}</span></div>
            <span className="l">Controls mapped</span>
          </div>
          <div className="card stat warn">
            <div className="stat-top"><span className="n" style={{ color: "var(--orange)" }}>{gap.gaps.length}</span></div>
            <span className="l">Open gaps</span>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="card-head">
          <h3>Requirements</h3>
          <span className="sub">{gap?.framework_name} · click a row for crosswalks &amp; evidence</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Ref</th>
                <th>Requirement</th>
                <th>Status</th>
                <th>Controls</th>
                <th>Evidence</th>
                <th>Crosswalks</th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((r) => (
                <tr key={r.id} style={{ cursor: "pointer" }} onClick={() => openRequirement(r)}>
                  <td className="ref">{r.reference}</td>
                  <td className="cell-title">{r.title}</td>
                  <td><ComplianceBadge value={r.status} /></td>
                  <td className="muted">{r.controls.length}</td>
                  <td>
                    {r.evidence_count > 0 ? (
                      <Badge tone="low" plain>{r.evidence_count}</Badge>
                    ) : (
                      <span className="muted">0</span>
                    )}
                  </td>
                  <td>
                    {r.crosswalk_count > 0 ? (
                      <Badge tone="info" plain>{r.crosswalk_count}</Badge>
                    ) : (
                      <span className="muted">0</span>
                    )}
                  </td>
                </tr>
              ))}
              {requirements.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <div className="empty">
                      <span className="ico"><IconCompliance width={24} height={24} /></span>
                      <h3>No requirements</h3>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {openReq && (
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 16 }}>
          <div className="card">
            <div className="card-head">
              <h3>Crosswalks · {openReq.reference}</h3>
              <span className="sub">Equivalent requirements</span>
            </div>
            <div className="card-pad">
              {crosswalks.length ? (
                crosswalks.map((c) => (
                  <div key={c.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>
                        <span className="ref">{c.reference}</span> — {c.title}
                      </div>
                      <div className="when">
                        <Badge tone="info" plain>{c.framework_name}</Badge>{" "}
                        <ComplianceBadge value={c.status} />
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <span className="muted">No crosswalks mapped for this requirement.</span>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h3>Evidence · {openReq.reference}</h3>
              <span className="sub">Via mapped controls</span>
            </div>
            <div className="card-pad">
              {evidence.length ? (
                evidence.map((ev) => (
                  <div key={ev.id} className="activity-item">
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{ev.title}</div>
                      <div className="when">
                        <Badge tone="info" plain>{ev.evidence_type}</Badge>{" "}
                        {ev.control ? ev.control.reference || ev.control.name : ""}
                      </div>
                    </div>
                    <Badge tone={ev.status === "valid" ? "low" : "neutral"}>{ev.status}</Badge>
                  </div>
                ))
              ) : (
                <span className="muted">No evidence collected yet.</span>
              )}
            </div>
          </div>
        </div>
      )}

      {gap && gap.gaps.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>Gap analysis</h3>
            <span className="sub">{gap.gaps.length} open</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Ref</th>
                  <th>Requirement</th>
                  <th>Status</th>
                  <th>Why it&apos;s a gap</th>
                </tr>
              </thead>
              <tbody>
                {gap.gaps.map((g) => (
                  <tr key={g.id}>
                    <td className="ref">{g.reference}</td>
                    <td className="cell-title">{g.title}</td>
                    <td><ComplianceBadge value={g.status} /></td>
                    <td className="muted">{g.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
