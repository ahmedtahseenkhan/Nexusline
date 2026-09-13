"use client";

/* The dossier identity header (record-page-spec §3.3.1). Rendered ONLY by RecordDrawer
   when `variant="dossier"` — pages pass `identity`, `primaryAction`, `onEdit`,
   `moreItems` (and the existing `actions`) to RecordDrawer, not to this component.

     identity={{
       kind: "Risk", backLabel: "Risk Register", reference: r.reference, name: r.title, lead,
       badges: r.level ? <LevelBadge level={r.level} /> : null,
       status: { key: "status", label: "Risk status", value: <Badge tone={…} asIs>{sentenceCase(r.status)}</Badge>, hint: "…" },
       approval: approvalMetaItem(gov, ctx.fmt, "…"),          // optional: omitted → built from the governance
       meta: [
         { key: "owner", label: "Owner", value: r.owner_ref ? name(r.owner_ref) : null,
           gap: { text: "Not assigned", fix: { label: "Assign", onClick: () => openEdit(r, "general") } } },
         …
       ],
       statusRules: { model: "risk", entityId: r.id },
     }}

   Meta order (v1.1, enforced here): the type's status first, "Record approval" SECOND,
   then `meta` in the order given — wherever a page puts the status ("status" /
   "lifecycle" key) or approval ("approval" key) item, it renders in its slot
   (components/record/metaOrder.ts). A lifecycle type that passes no approval item gets
   the one built from the drawer's governance; `approval: null` opts out.

   The lead is published (components/record/lead.ts) so no section repeats it (v1.1:
   a description appears once).

   Crumb bar: "← {backLabel}" (closes) / KIND / [REF] (click copies the link) / badges,
   then the actions — primary, Edit, the drawer's `actions`, More ▾ — and ✕. At ≤640px
   Edit becomes the first More item. H1 is the full name (#rec-title, the dialog's
   label, focused on open). The lead is clamped to 2 lines with a More / Less toggle
   when it overflows. Meta items are never dropped: a missing value shows its amber
   `gap` (with the fix link) or muted "Not set"; "Status rules" is appended when any
   rule fires. */

import { useEffect, useRef, useState, type ReactNode } from "react";
import Menu, { type MenuItem } from "@/components/Menu";
import StatusRuleChips, { useStatusRuleVerdicts } from "@/components/record/StatusRuleChips";
import { copyRecordLink } from "@/components/record/actions";
import { approvalHintFor, approvalMetaItem, useRecordFmt } from "@/components/record/ctx";
import { publishRecordLead } from "@/components/record/lead";
import { orderMeta } from "@/components/record/metaOrder";
import { useRecordGovernance } from "@/components/record/RecordGovernance";
import { useIsoLayoutEffect } from "@/components/record/useIsoLayoutEffect";
import { useMediaQuery } from "@/components/record/useMediaQuery";
import type { MetaItem, RecordIdentity } from "@/components/record/types";
import { sentenceLabel } from "@/lib/record/text";

export type RecordHeaderProps = {
  identity: RecordIdentity;
  primaryAction?: ReactNode;
  onEdit?: () => void;
  /** The drawer's existing `actions` node (secondary buttons only). */
  actions?: ReactNode;
  moreItems?: MenuItem[];
  onClose: () => void;
};

const hasValue = (v: ReactNode) => v !== undefined && v !== null && v !== false && v !== "";

/** "Assign" + "Owner" → "Assign owner"; "Name owner" + "Business owner" → "Name owner". */
function fixName(fix: string, label: string): string {
  const last = label.trim().split(/\s+/).pop()?.toLowerCase() ?? "";
  return fix.toLowerCase().includes(last) ? fix : `${fix} ${sentenceLabel(label)}`;
}

function MetaRow({ item }: { item: MetaItem }) {
  const present = hasValue(item.value);
  return (
    <div>
      <dt title={item.hint}>{item.label}</dt>
      <dd>
        {present && item.value}
        {present && hasValue(item.sub) && <span className="sub">{item.sub}</span>}
        {item.gap && (
          <>
            <span className="rec-gap">{item.gap.text}</span>
            {item.gap.fix && (
              <button type="button" className="rec-link" aria-label={fixName(item.gap.fix.label, item.label)} onClick={item.gap.fix.onClick}>
                {item.gap.fix.label}
              </button>
            )}
          </>
        )}
        {!present && !item.gap && <span className="muted rec-notset-v">Not set</span>}
      </dd>
    </div>
  );
}

function Lead({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useIsoLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => {
      if (open) return;
      setOverflows(el.scrollHeight > el.clientHeight + 1);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [text, open]);

  useEffect(() => setOpen(false), [text]);

  return (
    <div className="rec-lead-wrap">
      <p ref={ref} className={`rec-lead${open ? " is-open" : ""}`}>{text}</p>
      {(overflows || open) && (
        <button type="button" className="rec-link rec-lead-toggle" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "Less" : "More"}
        </button>
      )}
    </div>
  );
}

/** Dev warnings fire once per kind + message. */
const warned = new Set<string>();
function warnOnce(kind: string, msg: string) {
  if (process.env.NODE_ENV === "production") return;
  const k = `${kind}|${msg}`;
  if (warned.has(k)) return;
  warned.add(k);
  console.warn(msg);
}

export default function RecordHeader({ identity, primaryAction, onEdit, actions, moreItems, onClose }: RecordHeaderProps) {
  const phone = useMediaQuery("(max-width: 640px)");
  const rules = identity.statusRules ?? null;
  const verdicts = useStatusRuleVerdicts(rules?.model ?? "", rules?.entityId ?? null);
  const gov = useRecordGovernance();
  const fmt = useRecordFmt();

  // v1.1 decision 1: status first, "Record approval" second.
  const statusLabel = identity.status?.label ?? identity.meta.find((m) => m.key === "status" || m.key === "lifecycle")?.label;
  const auto = gov && gov.entityId && gov.lifecycle !== false ? approvalMetaItem(gov, fmt, approvalHintFor(statusLabel)) : null;
  const { items: meta, hasStatus } = orderMeta(identity, auto);

  if (!hasStatus) {
    warnOnce(identity.kind, `RecordHeader: no status item for "${identity.kind}". v1.1 puts the type's own status first (identity.status, or a meta item keyed "status" / "lifecycle") and "Record approval" second.`);
  }
  if (meta.length > 6) {
    warnOnce(identity.kind, `RecordHeader: ${meta.length} meta items for "${identity.kind}"; the spec allows at most 6 (status and approval included).`);
  }

  const menu: MenuItem[] = [
    ...(phone && onEdit ? [{ label: "Edit", onClick: onEdit } as MenuItem] : []),
    ...(moreItems ?? []),
  ];
  const lead = (identity.lead ?? "").trim();
  // v1.1 decision 2: sections read this to avoid repeating the description.
  useIsoLayoutEffect(() => publishRecordLead(lead || null), [lead]);

  return (
    <header className="rec-head">
      <div className="rec-crumb">
        <button type="button" className="rec-back" onClick={onClose} aria-label={`Back to ${identity.backLabel}`}>
          ← {identity.backLabel}
        </button>
        <div className="rec-idline">
          <span className="sep" aria-hidden="true">/</span>
          <span className="rec-kind">{identity.kind}</span>
          {identity.reference && (
            <button
              type="button"
              className="rec-ref"
              title="Copy link to this record"
              aria-label={`Copy link to ${identity.reference}`}
              onClick={() => void copyRecordLink()}
            >
              {identity.reference}
            </button>
          )}
          {identity.badges}
        </div>
        <div className="rec-actions">
          {primaryAction}
          {onEdit && !phone && (
            <button type="button" className="btn secondary sm" onClick={onEdit}>
              Edit
            </button>
          )}
          {actions}
          {menu.length > 0 && <Menu label="More" items={menu} className="btn secondary sm" />}
        </div>
        <button type="button" className="x rec-close" onClick={onClose} aria-label="Close record">
          ✕
        </button>
      </div>
      <h1 className="rec-title" id="rec-title" tabIndex={-1} title={identity.name}>
        {identity.name}
      </h1>
      {lead && <Lead text={lead} />}
      <dl className="rec-meta">
        {meta.map((m) => (
          <MetaRow key={m.key} item={m} />
        ))}
        {rules && verdicts.length > 0 && (
          <div>
            <dt>Status rules</dt>
            <dd>
              <StatusRuleChips model={rules.model} entityId={rules.entityId} verdicts={verdicts} />
            </dd>
          </div>
        )}
      </dl>
    </header>
  );
}

export { RecordHeader };
