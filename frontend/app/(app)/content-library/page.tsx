"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiCall } from "@/lib/api";
import {
  previewControlsPack,
  RELATIONSHIP_HELP,
  RELATIONSHIP_LABEL,
  type PackDecisions,
  type PackPreview,
  type PackPreviewRow,
} from "@/lib/compliance";
import { toast } from "@/lib/feedback";
import { trapTab, useDialogFocus, useEscapeLayer } from "@/lib/escapeLayer";
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
  /** The name the installed copy carries (differs from `name` for a legacy pack). */
  installed_as: string | null;
  /** Installed as a legacy pack or missing clauses: Install upgrades it in place. */
  upgrade_available: boolean;
  requirements_missing: number;
  /** compliance | maturity | guidance */
  kind: string;
};

type InstallResult = {
  framework_id: string;
  name: string;
  requirement_count: number;
  requirements_added: number;
  controls_created: number;
  /** Template controls that already existed in the catalogue (matched by reference). */
  controls_linked: number;
  /** Requirement ↔ control links written. */
  requirements_linked: number;
  upgraded: boolean;
  previous_name: string | null;
  /** Library crosswalks recorded between this framework and the ones already installed. */
  crosswalks_added?: number;
};

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** "93 controls created, 93 requirement links, 4 matched to existing controls" — empty
 *  when the pack made no controls (a management-system framework). */
function controlsSummary(res: InstallResult): string {
  if (!res.controls_created && !res.controls_linked && !res.requirements_linked) return "";
  const parts = [
    plural(res.controls_created, "control") + " created",
    plural(res.requirements_linked, "requirement link"),
  ];
  if (res.controls_linked) parts.push(`${res.controls_linked} matched to existing controls`);
  return parts.join(", ");
}

/** A clause decided in the review: a same-named control, or a control reached through a
 *  library crosswalk to a clause of an installed framework (common control set). */
const isNameRow = (r: PackPreviewRow) => r.action === "match-by-name";
const isCrosswalkRow = (r: PackPreviewRow) =>
  !isNameRow(r) && !!r.crosswalk_match && (r.action === "reuse-via-crosswalk" || r.action === "create");

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

  /* Before a controls pack is written, the plan is previewed: each clause either creates
     a control or reuses one already in the catalogue (same reference, or same name once
     case, punctuation and filler words are ignored). When the plan holds a name match
     there is a decision to make, so the review opens; otherwise the default install
     stays one click. */
  const [review, setReview] = useState<{ pack: ContentPack; preview: PackPreview; mode: "install" | "controls" } | null>(null);
  const [reviewChoice, setReviewChoice] = useState<Record<string, "reuse" | "create">>({});
  // The review dialog is a layer of the shared escape stack; focus moves in and comes back.
  useEscapeLayer(!!review, () => setReview(null));
  const reviewRef = useRef<HTMLDivElement>(null);
  useDialogFocus(!!review, reviewRef);

  async function withPreview(pack: ContentPack, mode: "install" | "controls", force = false) {
    setError(null);
    setInstallingId(pack.id);
    try {
      const preview = await previewControlsPack(pack.id);
      const decidable = preview.rows.filter((r) => isNameRow(r) || isCrosswalkRow(r));
      if (!decidable.length && !force) {
        if (mode === "install") await install(pack, {});
        else await installControls(pack, {});
        return;
      }
      // Name matches and equivalent crosswalks default to reuse; a contained, containing or
      // overlapping crosswalk defaults to a new control until you choose to reuse.
      setReviewChoice(Object.fromEntries(decidable.map((r) => [
        r.requirement_ref,
        isNameRow(r) || r.action === "reuse-via-crosswalk" ? ("reuse" as const) : ("create" as const),
      ])));
      setReview({ pack, preview, mode });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not preview the controls");
    } finally {
      setInstallingId(null);
    }
  }

  function reviewDecisions(): PackDecisions {
    if (!review) return {};
    const out: PackDecisions = {};
    for (const r of review.preview.rows) {
      const choice = reviewChoice[r.requirement_ref];
      if (isNameRow(r) && r.control) {
        out[r.requirement_ref] = choice === "create" ? "create" : r.control.id;
      } else if (isCrosswalkRow(r) && r.crosswalk_match) {
        out[r.requirement_ref] = choice === "reuse" ? r.crosswalk_match.control.id : "create";
      }
    }
    return out;
  }

  async function confirmReview() {
    if (!review) return;
    const { pack, mode } = review;
    const decisions = reviewDecisions();
    setReview(null);
    if (mode === "install") await install(pack, decisions);
    else await installControls(pack, decisions);
  }

  /** The upgrade path: a framework installed before the controls pack existed. */
  async function installControls(pack: ContentPack, decisions?: PackDecisions) {
    setError(null);
    setInstallingId(pack.id);
    try {
      const res = await apiCall<InstallResult>("POST", `/content-library/${pack.id}/install-controls`, decisions ? { decisions } : undefined);
      toast(`${res.name}: ${controlsSummary(res) || "nothing to add"}. They are in the Control Catalogue, linked to their clauses.`);
      await loadPacks();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create the controls");
    } finally {
      setInstallingId(null);
    }
  }

  async function install(pack: ContentPack, decisions?: PackDecisions) {
    setError(null);
    setInstallingId(pack.id);
    try {
      const flag = pack.is_control_framework ? `?create_controls=${createControls(pack)}` : "";
      const res = await apiCall<InstallResult>("POST", `/content-library/${pack.id}/install${flag}`, decisions ? { decisions } : undefined);
      const controls = controlsSummary(res);
      if (res.upgraded) {
        const renamed = res.previous_name && res.previous_name !== res.name ? ` (was “${res.previous_name}”)` : "";
        toast(`Upgraded ${res.name}${renamed}: +${plural(res.requirements_added, "requirement")}${controls ? `, ${controls}` : ""}. Existing statuses and links were kept.`);
      } else {
        const cw = res.crosswalks_added ? ` ${plural(res.crosswalks_added, "library crosswalk")} to your other frameworks recorded for review.` : "";
        toast(`Installed ${res.name}: ${plural(res.requirement_count, "requirement")}${controls ? `, ${controls}` : ""}. It now appears in Compliance.${cw}`);
      }
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
              {p.kind !== "compliance" && (
                <div><Badge tone="info" plain>Maturity self-assessment</Badge></div>
              )}

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
                    <span className="muted"> Generated risks link to them automatically. An existing control with the same reference or the same name, or one implementing an equivalent clause of a framework you already have, is reused, not duplicated — you review these before anything is written.</span>
                  </span>
                </label>
              )}

              {p.installed && p.upgrade_available && (
                <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, padding: "8px 10px", borderRadius: 8, background: "var(--amber-bg)", color: "var(--amber)" }}>
                  <span style={{ flex: 1 }}>
                    {p.installed_as && p.installed_as !== p.name ? <>Installed as “{p.installed_as}”. </> : null}
                    {p.requirements_missing > 0
                      ? <>Missing {plural(p.requirements_missing, "requirement")} of {p.requirement_count}. </>
                      : null}
                    Upgrading keeps every existing requirement, status and link.
                  </span>
                  <button className="btn secondary sm" disabled={installingId === p.id} onClick={() => install(p)}>
                    {installingId === p.id ? "Upgrading…" : "Upgrade"}
                  </button>
                </div>
              )}

              {p.installed && p.is_control_framework && p.controls_present < p.controls_total && (
                <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12.5, padding: "8px 10px", borderRadius: 8, background: "var(--amber-bg)", color: "var(--amber)" }}>
                  <span style={{ flex: 1 }}>
                    Installed without its controls — {p.controls_present} of {p.controls_total} clauses have a control behind them.
                  </span>
                  <button className="btn secondary sm" disabled={installingId === p.id} onClick={() => withPreview(p, "controls")}>
                    {installingId === p.id ? "Creating…" : `Create ${p.controls_total - p.controls_present} controls`}
                  </button>
                  <button className="btn secondary sm" disabled={installingId === p.id} onClick={() => withPreview(p, "controls", true)} title="See which clauses create a control and which reuse one you already have">
                    Review
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
                  <div style={{ display: "flex", gap: 8 }}>
                    {p.is_control_framework && createControls(p) && (
                      <button
                        className="btn secondary"
                        disabled={installingId === p.id}
                        onClick={() => withPreview(p, "install", true)}
                        title="See which clauses create a control and which reuse one you already have"
                      >
                        Preview controls
                      </button>
                    )}
                    <button
                      className="btn"
                      disabled={installingId === p.id}
                      onClick={() => (p.is_control_framework && createControls(p) ? withPreview(p, "install") : install(p))}
                    >
                      {installingId === p.id ? "Installing…" : "Install"}
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {review && (() => {
        const nameRows = review.preview.rows.filter(isNameRow);
        const crosswalkRows = review.preview.rows.filter(isCrosswalkRow);
        const refRows = review.preview.rows.filter((r) => r.action === "match-by-reference" || r.action === "map-to-existing");
        const overridden = nameRows.filter((r) => reviewChoice[r.requirement_ref] === "create").length;
        const cwDefaultReuse = crosswalkRows.filter((r) => r.action === "reuse-via-crosswalk").length;
        const cwReuse = crosswalkRows.filter((r) => reviewChoice[r.requirement_ref] === "reuse").length;
        const willReuse = review.preview.reuse - overridden - cwDefaultReuse + cwReuse;
        const willCreate = review.preview.rows.length - willReuse;
        return (
          <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && setReview(null)}>
            <div ref={reviewRef} tabIndex={-1} className="modal wide" role="dialog" aria-modal="true" aria-label={`Controls for ${review.pack.name}`} onKeyDown={(e) => trapTab(e, reviewRef.current)}>
              <div className="modal-head">
                <h2>Controls for {review.pack.name}</h2>
                <button className="x" onClick={() => setReview(null)} aria-label="Close">✕</button>
              </div>
              <div className="modal-body">
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                  <Badge tone="info">Will create {willCreate}</Badge>
                  <Badge tone="low">Will reuse {willReuse}</Badge>
                  <span className="muted" style={{ fontSize: 12.5, alignSelf: "center" }}>
                    {review.preview.match_reference} by reference · {nameRows.length - overridden} by name · {cwReuse} through a crosswalk
                  </span>
                </div>
                {nameRows.length > 0 ? (
                  <>
                    <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 0 }}>
                      These clauses have the same name as a control you already have. Reusing it links the clause to
                      your control (map once, comply many); creating makes a separate library control.
                    </p>
                    <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto", marginBottom: 12 }}>
                      <table>
                        <thead>
                          <tr><th style={{ width: 90 }}>Clause</th><th>Title</th><th>Existing control</th><th style={{ width: 190 }}>Decision</th></tr>
                        </thead>
                        <tbody>
                          {nameRows.map((r) => (
                            <tr key={r.requirement_ref}>
                              <td><span className="ref">{r.catalogue_reference}</span></td>
                              <td>{r.title}</td>
                              <td>{r.control ? <><span className="ref">{r.control.reference || "—"}</span> {r.control.name}</> : "—"}</td>
                              <td>
                                <select
                                  className="select"
                                  value={reviewChoice[r.requirement_ref] || "reuse"}
                                  onChange={(e) => setReviewChoice((m) => ({ ...m, [r.requirement_ref]: e.target.value as "reuse" | "create" }))}
                                  aria-label={`Decision for ${r.catalogue_reference}`}
                                >
                                  <option value="reuse">Reuse existing</option>
                                  <option value="create">Create new control</option>
                                </select>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                ) : (
                  <p className="muted" style={{ fontSize: 13 }}>No clause shares a name with an existing control.</p>
                )}
                {crosswalkRows.length > 0 && (
                  <>
                    <p className="muted" style={{ fontSize: 13, lineHeight: 1.6, marginTop: 4 }}>
                      These clauses relate, through the library&apos;s crosswalk content, to a clause of a framework you already have
                      that a control implements. Reusing that control builds one common control set instead of a parallel one.
                      Equivalent clauses reuse it unless you choose otherwise; for a clause that is contained in, contains or overlaps
                      the other, decide whether the control really meets it.
                    </p>
                    <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto", marginBottom: 12 }}>
                      <table>
                        <thead>
                          <tr><th style={{ width: 90 }}>Clause</th><th>Title</th><th>Existing control</th><th style={{ width: 130 }}>Relationship</th><th style={{ width: 190 }}>Decision</th></tr>
                        </thead>
                        <tbody>
                          {crosswalkRows.map((r) => {
                            const m = r.crosswalk_match!;
                            return (
                              <tr key={r.requirement_ref}>
                                <td><span className="ref">{r.catalogue_reference}</span></td>
                                <td>{r.title}</td>
                                <td>
                                  <span className="ref">{m.control.reference || "—"}</span> {m.control.name}
                                  <div className="muted" style={{ fontSize: 11.5 }}>
                                    Mapped to {m.via_framework} {m.via_reference}
                                    {m.rationale ? ` · ${m.rationale}` : ""}
                                  </div>
                                </td>
                                <td title={RELATIONSHIP_HELP[m.relationship]}>
                                  <Badge tone={m.relationship === "equivalent" ? "low" : "info"} plain>{RELATIONSHIP_LABEL[m.relationship]}</Badge>
                                </td>
                                <td>
                                  <select
                                    className="select"
                                    value={reviewChoice[r.requirement_ref] || (m.default_reuse ? "reuse" : "create")}
                                    onChange={(e) => setReviewChoice((c) => ({ ...c, [r.requirement_ref]: e.target.value as "reuse" | "create" }))}
                                    aria-label={`Decision for ${r.catalogue_reference}`}
                                  >
                                    <option value="reuse">Reuse {m.control.reference || "existing control"}</option>
                                    <option value="create">Create new control</option>
                                  </select>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
                {refRows.length > 0 && (
                  <details style={{ fontSize: 12.5 }}>
                    <summary style={{ cursor: "pointer" }}>{refRows.length} already in the catalogue by reference (linked, not duplicated)</summary>
                    <div className="muted" style={{ marginTop: 6, lineHeight: 1.6 }}>
                      {refRows.map((r) => r.catalogue_reference).join(", ")}
                    </div>
                  </details>
                )}
              </div>
              <div className="modal-foot">
                <button className="btn secondary" type="button" onClick={() => setReview(null)}>Cancel</button>
                <button className="btn" type="button" onClick={confirmReview}>
                  {review.mode === "install" ? "Install" : "Create controls"}
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </>
  );
}
