"use client";

/* Issues raised against a record (record-page-spec §3.5 "RecordIssues", §4.0 "Issues
   section"): the list of issues linked to the record plus the Raise-issue form, one
   implementation for every record page (it replaces the five page copies in controls,
   risks, information assets, IT assets and third parties).

   Dossier pages use the section, which is the whole "Issues" section of §4.0:

     const issuesRef = useRef<RecordIssuesHandle>(null);
     <RecordIssuesSection ref={issuesRef} entityId={r.id} entityKind="risk" entityRef={r.reference}
       sourceType="risk_assessment" noun="risk" onRaised={refresh} />
     // More › "Raise issue…" and an open point call issuesRef.current?.raise()

   Anywhere else, the bare body goes inside a section or card the page owns (no heading,
   no frame, no trigger — open it with the ref or `raiseOpen`):

     <RecordIssues bare ref={issuesRef} entityId={c.id} entityKind="control" entityRef={c.reference} onCount={setIssueCount} />

   Without `bare` it renders a titled card with its own "Raise issue" button (a drop-in
   for the classic components/RecordIssues).

   Behaviour, the same on every page:
   - Lists `GET /issues?{entityKind}_id={id}&limit=50` (`linked_id` without a kind):
     Ref (link) · Issue · Severity · Issue status · Owner · Due ("Overdue since {date}").
   - Permission-aware: needs `issue:read` to list (a 403 counts too) and `issue:write` to
     raise; both can be overridden with `canRead` / `canRaise`.
   - One set of messages (`recordIssuesText(noun)`): "Loading issues…", "No issues raised
     against this {noun}.", "Could not load the issues raised against this {noun}. Retry",
     "You need the Issues permission to see the issues raised against this {noun}."
   - Raise issue (a Disclosure; Esc and Cancel return focus): title (required, ≤ 255),
     severity (default Medium), owner (optional). POST /issues with `source_type`
     (default "self_identified"), `source_id` = the record, `source_reference` =
     `entityRef` (≤ 255) and the typed link `{entityKind}_ids: [id]`. Success toasts
     "Issue raised", closes, reloads the list and calls `onRaised` (the page's refresh);
     a refusal shows inline and in a toast.
   - Switching records closes the form and never shows the previous record's issues. */

import Link from "next/link";
import {
  forwardRef,
  useCallback,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
  type Ref,
} from "react";
import { Badge, type BadgeTone } from "@/components/badges";
import type { IssueLinkKind } from "@/components/RecordIssues";
import UserPicker from "@/components/UserPicker";
import LabelledSearch from "@/components/record/a11y";
import Disclosure from "@/components/record/Disclosure";
import RecordSection, { useRecordSections } from "@/components/record/RecordSection";
import { isForbidden } from "@/components/record/trailWords";
import { apiCall } from "@/lib/api";
import { toast } from "@/lib/feedback";
import { useFormat } from "@/lib/format";
import { sentenceCase } from "@/lib/record/text";
import { useTenantSettings } from "@/lib/tenantSettings";

export type { IssueLinkKind };

/** One row of `GET /issues?…_id=` as the list reads it. */
export type IssueRow = {
  id: string;
  reference: string;
  title: string;
  severity?: string | null;
  status?: string | null;
  owner?: string | null;
  owner_ref?: { full_name?: string | null; email?: string | null } | null;
  due_date?: string | null;
  is_overdue?: boolean;
};

export type RecordIssuesHandle = {
  /** Open the Raise-issue form (the section also scrolls into view). No-op without issue:write. */
  raise(): void;
  /** Refetch the list. */
  reload(): void;
};

type CommonProps = {
  /** The record the issues are raised against. */
  entityId: string;
  /** Typed link: lists `?{kind}_id=` and links a raised issue with `{kind}_ids: [id]`.
   *  Omit to list `?linked_id=` (any link or source) with no typed link. */
  entityKind?: IssueLinkKind;
  /** Provenance on a raised issue (`source_reference`): the record's reference, or its
   *  name when it has none (assets, third parties). Cut to 255 characters. */
  entityRef?: string | null;
  /** `source_type` of a raised issue. Default "self_identified" (the risk page sends "risk_assessment"). */
  sourceType?: string;
  /** The record in running text: "risk", "control", "information asset", "third party". Default "record". */
  noun?: string;
  /** Default: the viewer holds `issue:read` (a 403 still shows the permission sentence). */
  canRead?: boolean;
  /** Default: the viewer holds `issue:write`. */
  canRaise?: boolean;
  /** Controlled Raise-issue form (optional). */
  raiseOpen?: boolean;
  onRaiseOpenChange?: (open: boolean) => void;
  /** The number of issues listed; null while loading, forbidden or failed. */
  onCount?: (n: number | null) => void;
  /** After an issue is raised (the list has already reloaded): the page's refresh(). */
  onRaised?: () => void;
  /** Change it to refetch the list (e.g. the page's refresh counter). */
  reloadKey?: unknown;
  /** Title placeholder. Default "What is wrong, in one line". */
  titlePlaceholder?: string;
};

export type RecordIssuesProps = CommonProps & {
  /** No card frame, heading or trigger: the body only, for a section the page owns. */
  bare?: boolean;
};

export type RecordIssuesSectionProps = CommonProps & {
  /** Section id (nav key, deep link). Default "issues". */
  id?: string;
  /** Default "Issues". */
  title?: string;
};

export const ISSUE_SEVERITIES = ["low", "medium", "high", "critical"] as const;

/** The one set of list messages, for every record type. */
export function recordIssuesText(noun = "record") {
  return {
    loading: "Loading issues…",
    none: `No issues raised against this ${noun}.`,
    error: `Could not load the issues raised against this ${noun}.`,
    forbidden: `You need the Issues permission to see the issues raised against this ${noun}.`,
  };
}

export type RecordIssuesStatus = "loading" | "ok" | "forbidden" | "error";

/** `GET /issues?{kind}_id={id}&limit=50` for one record. Rows belong to the record they
 *  were fetched for (a switch never shows the previous record's issues); a reload keeps
 *  the current rows on screen until the new ones arrive. `enabled: false` → "forbidden". */
export function useRecordIssues(
  entityId: string | null,
  entityKind?: IssueLinkKind,
  opts: { enabled?: boolean; reloadKey?: unknown } = {},
): { items: IssueRow[] | null; status: RecordIssuesStatus; error: string | null; reload(): void } {
  const enabled = opts.enabled ?? true;
  const key = `${entityKind ?? "linked"}:${entityId ?? ""}`;
  const [got, setGot] = useState<{ key: string; status: "ok" | "forbidden" | "error"; items: IssueRow[]; error: string | null } | null>(null);
  const seq = useRef(0);

  const reload = useCallback(() => {
    const mine = ++seq.current;
    if (!entityId || !enabled) return;
    const filter = entityKind ? `${entityKind}_id` : "linked_id";
    apiCall<{ items: IssueRow[] }>("GET", `/issues?${filter}=${encodeURIComponent(entityId)}&limit=50`)
      .then((r) => {
        if (mine === seq.current) setGot({ key, status: "ok", items: r.items ?? [], error: null });
      })
      .catch((e) => {
        if (mine !== seq.current) return;
        setGot({ key, status: isForbidden(e) ? "forbidden" : "error", items: [], error: e instanceof Error ? e.message : null });
      });
  }, [entityId, entityKind, enabled, key]);

  useEffect(() => {
    reload();
  }, [reload, opts.reloadKey]);

  if (!entityId) return { items: null, status: "loading", error: null, reload };
  if (!enabled) return { items: null, status: "forbidden", error: null, reload };
  if (!got || got.key !== key) return { items: null, status: "loading", error: null, reload };
  return { items: got.status === "ok" ? got.items : null, status: got.status, error: got.error, reload };
}

const SEV_TONE: Record<string, BadgeTone> = { low: "low", medium: "medium", high: "high", critical: "critical" };

function ownerText(i: IssueRow): string {
  return (i.owner_ref?.full_name || i.owner_ref?.email || i.owner || "").trim();
}

/** The issues table (Ref · Issue · Severity · Issue status · Owner · Due). */
function IssuesTable({ items, noun }: { items: IssueRow[]; noun: string }) {
  const { formatDate } = useFormat();
  return (
    <div className="rec-table-wrap">
      <table className="compact">
        <caption className="sr-only">Issues raised against this {noun}</caption>
        <thead>
          <tr>
            <th scope="col">Ref</th>
            <th scope="col">Issue</th>
            <th scope="col">Severity</th>
            <th scope="col">Issue status</th>
            <th scope="col">Owner</th>
            <th scope="col">Due</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => {
            const owner = ownerText(i);
            const sev = (i.severity ?? "").toLowerCase();
            return (
              <tr key={i.id}>
                <td>
                  <Link className="ref" href={`/issues?id=${i.id}`} aria-label={[i.reference || "Issue", i.title].filter(Boolean).join(" ")}>
                    {i.reference || "Issue"}
                  </Link>
                </td>
                <td className="cell-title">{i.title}</td>
                <td>{sev ? <Badge tone={SEV_TONE[sev] ?? "neutral"} asIs>{sentenceCase(sev)}</Badge> : <span className="muted">Not set</span>}</td>
                <td>{i.status ? sentenceCase(i.status) : <span className="muted">Not set</span>}</td>
                <td>{owner || <span className="muted">Not assigned</span>}</td>
                <td>
                  {i.is_overdue ? (
                    <Badge tone="high" asIs>{i.due_date ? `Overdue since ${formatDate(i.due_date)}` : "Overdue"}</Badge>
                  ) : i.due_date ? (
                    formatDate(i.due_date)
                  ) : (
                    <span className="muted">Not set</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type RaiseTarget = Pick<CommonProps, "entityId" | "entityKind" | "entityRef" | "sourceType" | "titlePlaceholder">;

/** The Raise-issue form. Mounted only while the Disclosure is open, so each opening starts blank. */
function RaiseIssueForm({ target, close, onDone }: { target: RaiseTarget; close: () => void; onDone: () => void }) {
  const uid = useId().replace(/:/g, "");
  const titleRef = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState<string>("medium");
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (saving) return;
    if (!title.trim()) {
      setError("Give the issue a title.");
      titleRef.current?.focus();
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiCall("POST", "/issues", {
        title: title.trim(),
        severity,
        source_type: target.sourceType || "self_identified",
        source_id: target.entityId,
        source_reference: (target.entityRef ?? "").slice(0, 255),
        owner_id: ownerId,
        ...(target.entityKind ? { [`${target.entityKind}_ids`]: [target.entityId] } : {}),
      });
      toast("Issue raised");
      close();
      onDone();
    } catch (err) {
      const msg = err instanceof Error && err.message ? err.message : "Could not raise the issue";
      setError(msg);
      toast(msg, "error");
      setSaving(false);
    }
  }

  return (
    <form className="rec-issue-form" onSubmit={submit} noValidate>
      <div className="row">
        <div className="rec-issue-title">
          <label className="label" htmlFor={`${uid}-title`}>Issue title</label>
          <input
            ref={titleRef}
            id={`${uid}-title`}
            className="input"
            maxLength={255}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={target.titlePlaceholder || "What is wrong, in one line"}
            aria-invalid={error === "Give the issue a title." || undefined}
            aria-describedby={error ? `${uid}-err` : undefined}
          />
        </div>
        <div className="rec-issue-sev">
          <label className="label" htmlFor={`${uid}-sev`}>Severity</label>
          <select id={`${uid}-sev`} className="select" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {ISSUE_SEVERITIES.map((s) => (
              <option key={s} value={s}>{sentenceCase(s)}</option>
            ))}
          </select>
        </div>
        <LabelledSearch label="Owner (optional)" className="rec-issue-owner">
          <UserPicker value={ownerId} onChange={(id) => setOwnerId(id)} placeholder="Search people…" disabled={saving} />
        </LabelledSearch>
      </div>
      {error && (
        <p className="rec-error rec-issue-err" role="alert" id={`${uid}-err`}>{error}</p>
      )}
      <div className="row rec-issue-acts">
        <button type="submit" className="btn secondary sm" disabled={saving}>{saving ? "Raising…" : "Raise issue"}</button>
        <button type="button" className="btn secondary sm" onClick={close} disabled={saving}>Cancel</button>
      </div>
    </form>
  );
}

/** State shared by the section, the card and the bare body. */
function useIssuesController(p: CommonProps, sectionId: string | null, ref: Ref<RecordIssuesHandle>) {
  const { permissions } = useTenantSettings();
  const known = permissions.length > 0; // before the permissions arrive, let the server decide
  const canRead = p.canRead ?? (!known || permissions.includes("issue:read"));
  const canRaise = p.canRaise ?? (known && permissions.includes("issue:write"));
  const list = useRecordIssues(p.entityId, p.entityKind, { enabled: canRead, reloadKey: p.reloadKey });
  const sections = useRecordSections();
  const noun = (p.noun ?? "").trim() || "record";
  const text = recordIssuesText(noun);

  const [innerOpen, setInnerOpen] = useState(false);
  const controlled = p.raiseOpen !== undefined;
  const open = canRaise && (controlled ? !!p.raiseOpen : innerOpen);
  const onOpenChange = useRef(p.onRaiseOpenChange);
  onOpenChange.current = p.onRaiseOpenChange;
  const setOpen = useCallback(
    (v: boolean) => {
      if (!controlled) setInnerOpen(v);
      onOpenChange.current?.(v);
    },
    [controlled],
  );

  // Another record: close the form (its fields reset because it unmounts).
  const lastId = useRef(p.entityId);
  useEffect(() => {
    if (lastId.current === p.entityId) return;
    lastId.current = p.entityId;
    setInnerOpen(false);
    if (controlled && p.raiseOpen) onOpenChange.current?.(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.entityId]);

  // Report the count (null while not listed).
  const onCount = useRef(p.onCount);
  onCount.current = p.onCount;
  const count = list.status === "ok" && list.items ? list.items.length : null;
  useEffect(() => {
    onCount.current?.(count);
  }, [count]);

  const onRaised = useRef(p.onRaised);
  onRaised.current = p.onRaised;
  const afterRaise = useCallback(() => {
    list.reload();
    onRaised.current?.();
  }, [list]);

  useImperativeHandle(
    ref,
    () => ({
      raise() {
        if (!canRaise) return;
        if (sectionId) sections.scrollTo(sectionId);
        setOpen(true);
      },
      reload: list.reload,
    }),
    [canRaise, sectionId, sections, setOpen, list.reload],
  );

  return { list, canRead, canRaise, open, setOpen, count, noun, text, afterRaise };
}

type Controller = ReturnType<typeof useIssuesController>;

/** The message line for a list that has no rows to show (or null). */
function statusLine(c: Controller): ReactNode {
  const { list, text } = c;
  if (list.status === "loading") return text.loading;
  if (list.status === "forbidden") return text.forbidden;
  if (list.status === "error") {
    return (
      <>
        {text.error}{" "}
        <button type="button" className="rec-link" onClick={list.reload}>Retry</button>
      </>
    );
  }
  if (!list.items || list.items.length === 0) return text.none;
  return null;
}

/** Form (when open) + table or message. */
function IssuesBody({
  c,
  p,
  panelId,
  triggerRef,
}: {
  c: Controller;
  p: CommonProps;
  panelId: string;
  triggerRef?: React.RefObject<HTMLButtonElement | null>;
}) {
  const items = c.list.items ?? [];
  const line = statusLine(c);
  const target: RaiseTarget = {
    entityId: p.entityId,
    entityKind: p.entityKind,
    entityRef: p.entityRef,
    sourceType: p.sourceType,
    titlePlaceholder: p.titlePlaceholder,
  };
  return (
    <>
      {c.canRaise && (
        <Disclosure label="Raise issue" hideTrigger open={c.open} onOpenChange={c.setOpen} id={panelId} triggerRef={triggerRef}>
          {(close) => <RaiseIssueForm target={target} close={close} onDone={c.afterRaise} />}
        </Disclosure>
      )}
      {items.length > 0 ? (
        <div className={c.open ? "rec-issues-list is-after-form" : "rec-issues-list"}>
          <IssuesTable items={items} noun={c.noun} />
        </div>
      ) : (
        line && !(c.open && c.list.status === "ok") && <p className="rec-empty rec-issues-msg">{line}</p>
      )}
    </>
  );
}

/** The list and Raise-issue form for one record: bare (inside a page's section) or a titled card. */
export const RecordIssues = forwardRef<RecordIssuesHandle, RecordIssuesProps>(function RecordIssues({ bare, ...p }, ref) {
  const c = useIssuesController(p, null, ref);
  const uid = useId().replace(/:/g, "");
  const panelId = `rec-raise-${uid}`;
  const trigger = useRef<HTMLButtonElement>(null);

  if (bare) {
    return (
      <div className="rec-issues">
        <IssuesBody c={c} p={p} panelId={panelId} />
      </div>
    );
  }
  return (
    <section className="card rec-issues rec-issues-card" aria-labelledby={`${panelId}-h`}>
      <div className="card-head">
        <h3 id={`${panelId}-h`}>
          Issues{c.count !== null && <span className="n"> {c.count}</span>}
        </h3>
        {c.canRaise && (
          <button
            ref={trigger}
            type="button"
            className="btn secondary sm"
            aria-expanded={c.open}
            aria-controls={panelId}
            onClick={() => c.setOpen(!c.open)}
          >
            Raise issue
          </button>
        )}
      </div>
      <div className="card-pad">
        <IssuesBody c={c} p={p} panelId={panelId} triggerRef={trigger} />
      </div>
    </section>
  );
});

/** The dossier "Issues" section (§4.0): the head's "Raise issue" button, the count in the
 *  head and nav, and the one-line empty state when there is nothing to list. */
export const RecordIssuesSection = forwardRef<RecordIssuesHandle, RecordIssuesSectionProps>(function RecordIssuesSection(
  { id = "issues", title = "Issues", ...p },
  ref,
) {
  const c = useIssuesController(p, id, ref);
  const panelId = `${id}-raise`;
  const trigger = useRef<HTMLButtonElement>(null);
  const items = c.list.items ?? [];
  const collapsed = !c.open && items.length === 0;

  // A section with nothing to list folds to one line as the form closes, unmounting the
  // Disclosure before it can return focus — so put focus back on the head button here.
  const setOpen = (v: boolean) => {
    c.setOpen(v);
    if (!v) requestAnimationFrame(() => trigger.current?.focus({ preventScroll: true }));
  };

  return (
    <RecordSection
      id={id}
      title={title}
      count={c.count}
      actions={
        c.canRaise ? (
          <button
            ref={trigger}
            type="button"
            className="btn secondary sm"
            aria-expanded={c.open}
            aria-controls={panelId}
            onClick={() => setOpen(!c.open)}
          >
            Raise issue
          </button>
        ) : undefined
      }
      empty={collapsed ? statusLine(c) : undefined}
    >
      <IssuesBody c={{ ...c, setOpen }} p={p} panelId={panelId} triggerRef={trigger} />
    </RecordSection>
  );
});

export default RecordIssues;
