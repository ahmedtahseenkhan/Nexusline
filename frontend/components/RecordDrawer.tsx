"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { flushSync } from "react-dom";
import type { MenuItem } from "@/components/Menu";
import RecordHeader from "@/components/record/RecordHeader";
import { RecordGovernanceContext, type RecordGovernance } from "@/components/record/RecordGovernance";
import { RecordSectionsProvider } from "@/components/record/RecordSection";
import { RecordSurfaceContext } from "@/components/record/RecordSurface";
import { RelatedClusterProvider } from "@/components/record/RelatedCluster";
import type { RecordIdentity } from "@/components/record/types";
import { trapTab, useEscapeLayer } from "@/lib/escapeLayer";
import { useFormat } from "@/lib/format";

export { RecordSurfaceContext };

type Props = {
  open: boolean;
  onClose: () => void;
  /** Classic header title. Dossier pages pass `identity` instead (its name is the H1). */
  title?: ReactNode;
  subtitle?: ReactNode;
  /** actions shown in the header (Edit, Delete, …). Dossier: extra secondary buttons, after Edit. */
  actions?: ReactNode;
  /** The record itself — fields, related records, the page's own panels. */
  children: ReactNode;
  /** Activity and collaboration for the record: status rules, attestation, comments,
   *  attachments, the audit trail. Rendered as a second column that scrolls on its
   *  own, so the record and its history are read side by side, not one after the other. */
  aside?: ReactNode;
  /** "full" (default) takes the viewport with two columns; "panel" is the older
   *  right-hand slide-over, kept for small records that do not need the room. */
  layout?: "full" | "panel";
  /** Panel width, honoured only when ``layout="panel"``. */
  width?: number;

  /** "classic" (default): today's header and columns. "dossier": the record page of
   *  record-page-spec §2 — identity header, main sections, "Sign-off & trail" rail. */
  variant?: "classic" | "dossier";
  /** Required for dossier (missing → console.error and a classic render). */
  identity?: RecordIdentity;
  /** Dossier: <PrimaryAction …/> — the one filled button. */
  primaryAction?: ReactNode;
  /** Dossier: renders [Edit]; at ≤640px it becomes the first More item. */
  onEdit?: () => void;
  /** Dossier: the "More ▾" menu (see withBaseMoreItems). */
  moreItems?: MenuItem[];
  /** Provided as RecordGovernanceContext to the whole drawer (header, main, aside). */
  governance?: RecordGovernance | null;
  /** Default "Activity & collaboration" (classic) / "Sign-off & trail" (dossier). */
  asideTitle?: string;
};

/**
 * Record detail. Overlays the list in place — no scrolling past a thousand rows —
 * and, paired with useRecordParam, is driven by the URL so it is deep-linkable and
 * Back-button correct.
 *
 * The full layout exists because a GRC record is not a form: a risk carries its
 * scores, controls, assets, acceptance history, attestations, comments and an audit
 * trail, and stacking all of that in a 620px column made a single record several
 * screens tall. Two columns, each scrolling independently, is how eramba lays it out
 * and it is the right shape — the item on the left, what has happened to it on the
 * right, both visible at once.
 *
 * Both variants: the dialog is labelled by its title, which takes focus on open; focus
 * returns to whatever was focused before on close (for a deep-linked record: its list
 * row, else the page heading); Tab stays inside it; Esc goes through
 * the shared escape stack (lib/escapeLayer), so a menu, picker, disclosure or dialog on
 * top closes first (no DOM inspection of other overlays); related
 * chips cluster (RelatedClusterProvider); and children know which column they are in
 * (RecordSurfaceContext — RecordApproval goes compact in the rail).
 *
 * Dossier (record-page-spec §3.5):
 *
 *   <RecordDrawer variant="dossier" open={!!detail} onClose={close} governance={gov}
 *     identity={{ kind: "Risk", backLabel: "Risk Register", reference: r.reference, name: r.title, lead, meta, statusRules }}
 *     primaryAction={<PrimaryAction candidates={…} onChanged={refresh} />}
 *     onEdit={() => openEdit(r)} moreItems={withBaseMoreItems(typeItems, { onDelete: () => remove(r) })}
 *     aside={<RecordPanels model="risk" entityId={r.id} layout="dossier" signOff={{ onChanged: refresh }} trail={{ reference: r.reference }} />}>
 *     <SummaryBand … /> <OpenPoints … /> <SectionNav /> <RecordSection id="assessment" …>…</RecordSection> …
 *   </RecordDrawer>
 *
 * It also sets up section registration (SectionNav, deep links `?id=…#section`) and the
 * working-copy print: `html.rec-printing` while printing, printing only the record, with
 * the footer "Working copy printed from NexusLine by {email} on {time}. Not a certified export."
 */
export default function RecordDrawer({
  open, onClose, title, subtitle, actions, children, aside, layout = "full", width = 620,
  variant = "classic", identity, primaryAction, onEdit, moreItems, governance, asideTitle,
}: Props) {
  const wantsDossier = variant === "dossier";
  const dossier = wantsDossier && !!identity;
  const titleId = useId();
  const labelId = dossier ? "rec-title" : `drawer-title-${titleId}`;
  const titleRef = useRef<HTMLHeadingElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const [printedAt, setPrintedAt] = useState<Date | null>(null);
  const { formatDateTime } = useFormat();

  if (process.env.NODE_ENV !== "production" && wantsDossier && !identity && open) {
    console.error("RecordDrawer: variant=\"dossier\" needs `identity`; rendering the classic layout.");
  }

  // Esc closes the record only when nothing is open on top of it: every menu, picker,
  // disclosure and dialog registers on the same escape stack and, having opened later,
  // sits above this layer and takes the Esc first.
  useEscapeLayer(open, onClose);

  useEffect(() => {
    if (!open) return;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  // Give focus back to where it was when the drawer closes. A record opened from a deep
  // link (or from a control that is gone by now) has nothing to go back to, so focus
  // goes to its row in the list (DataTable marks rows with data-row-key), else to the
  // page heading — never to <body>, where the next Tab starts from the top of the page.
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const recordId = new URLSearchParams(window.location.search).get("id");
    return () => {
      if (previous && previous.isConnected && previous !== document.body) {
        previous.focus({ preventScroll: true });
        return;
      }
      const now = document.activeElement;
      if (now && now !== document.body && now.isConnected) return; // something else took it
      const row = recordId ? document.querySelector<HTMLElement>(`tr[data-row-key="${CSS.escape(recordId)}"]`) : null;
      if (row && row.tabIndex >= 0) {
        row.focus();
        return;
      }
      const heading = document.querySelector<HTMLElement>("main h1");
      if (heading) {
        if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
        heading.focus({ preventScroll: true });
      }
    };
  }, [open]);

  // Focus the title on open — and again if the layout switches (classic placeholder →
  // dossier once `identity` arrives) while focus is not already inside the drawer.
  useEffect(() => {
    if (!open) return;
    const raf = requestAnimationFrame(() => {
      const active = document.activeElement;
      if (active && active !== document.body && overlayRef.current?.contains(active)) return;
      const el = (dossier ? document.getElementById("rec-title") : titleRef.current) as HTMLElement | null;
      el?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(raf);
  }, [open, dossier]);

  // Working-copy print (dossier): mark the document while printing.
  useEffect(() => {
    if (!open || !dossier) return;
    const before = () => {
      flushSync(() => setPrintedAt(new Date())); // the footer's time must be in this print
      document.documentElement.classList.add("rec-printing");
    };
    const after = () => document.documentElement.classList.remove("rec-printing");
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
      document.documentElement.classList.remove("rec-printing");
    };
  }, [open, dossier]);

  if (!open) return null;
  const full = layout === "full" || dossier;
  // aria-modal: Tab and Shift+Tab stay inside the record instead of reaching the page behind it.
  const keepTabInside = (e: KeyboardEvent<HTMLElement>) => trapTab(e, e.currentTarget);

  let content: ReactNode;
  if (dossier && identity) {
    content = (
      <aside className="drawer full rec" role="dialog" aria-modal="true" aria-labelledby={labelId} onKeyDown={keepTabInside}>
        <RecordHeader
          identity={identity}
          primaryAction={primaryAction}
          onEdit={onEdit}
          actions={actions}
          moreItems={moreItems}
          onClose={onClose}
        />
        <RecordSectionsProvider hasRail={!!aside}>
          <div className={`drawer-columns${aside ? " has-aside" : ""}`}>
            <div className="drawer-main">
              <RecordSurfaceContext.Provider value="main">
                <div className="drawer-main-inner">{children}</div>
              </RecordSurfaceContext.Provider>
            </div>
            {aside && (
              <div className="drawer-aside" id="rec-rail" aria-labelledby="rec-rail-h">
                <h2 className="drawer-aside-title" id="rec-rail-h" tabIndex={-1}>
                  {asideTitle ?? "Sign-off & trail"}
                </h2>
                <RecordSurfaceContext.Provider value="aside">{aside}</RecordSurfaceContext.Provider>
              </div>
            )}
          </div>
        </RecordSectionsProvider>
        <p className="rec-print-footer">
          Working copy printed from NexusLine{governance?.me?.email ? ` by ${governance.me.email}` : ""} on{" "}
          {formatDateTime(printedAt ?? new Date())}. Not a certified export.
        </p>
      </aside>
    );
  } else {
    content = (
      <aside
        className={`drawer${full ? " full" : ""}`}
        style={full ? undefined : { width }}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        onKeyDown={keepTabInside}
      >
        <div className="drawer-head">
          {full && (
            <button className="btn secondary sm drawer-back" onClick={onClose} aria-label="Back to list">
              ← Back
            </button>
          )}
          <div style={{ minWidth: 0, flex: 1 }}>
            <h2
              id={labelId}
              ref={titleRef}
              tabIndex={-1}
              className="drawer-title"
              style={{ margin: 0, fontSize: full ? 20 : 18, overflow: "hidden", textOverflow: "ellipsis" }}
            >
              {title ?? identity?.name}
            </h2>
            {subtitle && <div className="muted" style={{ fontSize: 13, marginTop: 2 }}>{subtitle}</div>}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexShrink: 0 }}>
            {actions}
            <button className="x" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </div>

        {full ? (
          <div className={`drawer-columns${aside ? " has-aside" : ""}`}>
            <div className="drawer-main">
              <RecordSurfaceContext.Provider value="main">
                <div className="drawer-main-inner">{children}</div>
              </RecordSurfaceContext.Provider>
            </div>
            {aside && (
              <div className="drawer-aside">
                <div className="drawer-aside-title">{asideTitle ?? "Activity & collaboration"}</div>
                <RecordSurfaceContext.Provider value="aside">{aside}</RecordSurfaceContext.Provider>
              </div>
            )}
          </div>
        ) : (
          <RecordSurfaceContext.Provider value="main">
            <div className="drawer-body">{children}</div>
          </RecordSurfaceContext.Provider>
        )}
      </aside>
    );
  }

  return (
    <div
      ref={overlayRef}
      className={`drawer-overlay${full ? " full" : ""}${dossier ? " rec-print-root" : ""}`}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <RecordGovernanceContext.Provider value={governance ?? null}>
        <RelatedClusterProvider>{content}</RelatedClusterProvider>
      </RecordGovernanceContext.Provider>
    </div>
  );
}
