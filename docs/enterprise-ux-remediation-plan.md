# Enterprise UX & Scalability — Audit Findings and Remediation Plan

Audit date: 2026-07-11. Scope: all ~45 module pages, shared frontend infrastructure,
and the backend list-API surface — audited by five parallel reviewers with file:line
evidence. Trigger: the Information Assets page renders a clicked record's detail at the
bottom of the page, below the full table — unusable at 1,000 records. The audit
confirmed that flaw and found it is one of **seven systemic patterns**, all traceable to
one root cause: *every page was built on a "small data" template (fetch ≤200 rows,
render everything, keep all state in memory).*

---

## Part 1 — The seven systemic flaws

### F1 · Record #201 is invisible — BLOCKER, app-wide
Every list fetch hardcodes `?limit=200` (100+ occurrences in `lib/api.ts`), some pages
fall to backend defaults (50 for controls-picker, 100 for icfr/vulnerabilities/evidence),
and **no page renders pagination controls** — the server's `total` is returned and thrown
away. Records beyond the cap are unreachable by any means: not in tables, not in
searches (mostly client-side over the capped fetch), not in link pickers. Header counts
("X total") lie at scale. The inverse problem also exists: several endpoints are
**unbounded** (assessments, questionnaires, requirements, internal-audit findings,
awareness) — 10,000 findings would arrive as one JSON payload into one DOM table.

### F2 · Inline-below-table record detail — BLOCKER, ~24 pages
The flagged pattern. Clicking a row renders the detail card + panels *after* the full
table with no scroll-into-view — at scale the click appears to do nothing. Worst
instances: declarations (an org-wide campaign renders **all** staff declarations in the
inline card), icfr (detail nested three levels), assessments (the questionnaire
answer-entry form itself is below the table).

### F3 · Zero deep-linking — BLOCKER, app-wide
No dynamic routes (`[id]/page.tsx`: none), no `useSearchParams` anywhere. No record has
a URL. Consequences: nothing shareable/bookmarkable; browser Back exits the module;
refresh loses your place; global search can only land on a module page, not the record
it found; notifications and approval requests cannot link to the record they concern.
For a GRC product — where auditors and approvers reference records constantly — this is
structural.

### F4 · Link pickers can't reach most records — MAJOR (correctness bug)
All pickers preload capped lists (`?limit=200`) and filter client-side; `MultiSelect`
renders max 50 options. With 1,000 controls, **control #201+ can never be linked to
anything**. The risks page fires 7 parallel full-table fetches on mount just to fill
pickers; compliance and controls each add an N+1 fan-out (one request per framework for
all requirements). Evidence's control picker is capped at **50**.

### F5 · Stat cards computed from truncated data — MAJOR (wrong numbers)
Several modules compute headline numbers client-side over the capped fetch: IT-assets
(total replacement value, critical count), information-assets (% self-assessed — a
compliance metric), privacy (transfer-gap count), internal-audit (open/overdue
findings), approvals (pending count), and worst: **Shariah charity "Total disbursed" — a
regulatory money figure** — silently understated past 200 ledger rows. Roughly half the
modules already do this right via server `*-summary` endpoints; the rest must follow.

### F6 · Data-loss interaction patterns — MAJOR
- `FormModal` closes on Escape / overlay-click / X with **no dirty check** — a
  half-completed 6-tab form (or an entire authored questionnaire) is silently discarded.
- Assessments: answers live in local state; clicking the row again or another row
  **silently discards a half-completed vendor assessment**.
- Evidence and threat-library: **delete with no confirmation at all** (one misclick
  destroys audit evidence / drops risk links).
- 81 `window.confirm()` calls elsewhere; `window.prompt` for approval rejections;
  no toast/undo anywhere.

### F7 · No table ergonomics — MAJOR
**0 of ~75 backend list endpoints accept a sort parameter** (all hardcode ORDER BY);
no page has column sorting, bulk selection, or bulk actions. Server-side search exists
on only ~18 endpoints and is wired on very few pages (issues is the best-practice
reference; vulnerabilities/scenario fire a request **per keystroke** with no debounce).
CSV export is missing on ~15 operational registers (incl. AML and the SBP outsourcing
register). The **activity log is a fixed latest-100 with no filters, paging, or export**
— history beyond 100 events is unreachable, a likely external-audit finding in itself.

### Backend scale hazards (behind the UI)
- `GET /notifications` triggers a scan that loads **~15 entire tables into Python on
  every poll, per user** — the single worst hazard at 100k rows.
- Dashboard + risk-program + ~21 `*-summary` endpoints load full tables into Python
  loops instead of SQL `GROUP BY`.
- List payloads serialize heavy nested collections per row (Risk: 7 collections,
  Asset: ~15) — multi-MB responses at scale; no slim list DTOs; no gzip middleware.
- Missing indexes: `status` (indexed on **zero** models), `created_at` (the default
  sort everywhere), all due/review dates, and the audit-log table has **no indexes at
  all**. Search uses leading-wildcard `ilike` (needs pg_trgm at scale).
- N+1: controls list runs one extra query per row (200 rows → 200 queries).

---

## Part 2 — Remediation plan

Root-cause order: fix the **contract** (backend), then the **primitives** (shared
components), then migrate pages. Migrating pages first would hand-roll the same fixes
45 times.

### Phase 0 — Backend list contract (foundation)
1. **Shared list-params dependency** (`limit`, `offset`, `search`, `sort_by`,
   `sort_dir`) with a per-endpoint whitelist of sortable/searchable columns; apply to
   all ~45 paginated endpoints; **paginate the unbounded ones** (assessments,
   questionnaires, requirements, IA findings, awareness, frameworks, decisions,
   regulatory reports); give the **audit log** filters (entity, actor, action, date
   range) + paging + export.
2. **Slim list DTOs**: list views return scalar columns + counts; nested collections
   only on the single-record GET. (This also fixes the payload-weight problem.)
3. **Index migration**: `status`, `created_at`, due/review dates, `inherent_score`,
   audit-log (created_at, entity_type, actor), pg_trgm GIN for search columns.
4. **Summaries to SQL**: convert the ~21 full-table-scan `*-summary` endpoints and the
   dashboard to `GROUP BY`; make the notifications scan SQL-side and cached/scheduled
   instead of per-poll.
5. GZip middleware; fix the controls N+1.

### Phase 1 — Frontend primitives (build once, use 45 times)
1. **Data layer** in `lib/api.ts`: a `usePagedList` hook (params, debounce, abort,
   loading/error state, 401→login), plus toasts for errors/saves.
2. **`DataTable`**: server pagination (real totals), column sorting, per-table search
   box wired to the server, loading skeleton vs true empty state, sticky header, row
   selection for bulk actions, page-size selector.
3. **`RecordDrawer`**: right-hand slide-over showing record detail + RecordPanels,
   driven by a `?id=` URL param → **deep-linkable, shareable, browser-Back closes it,
   and the scrolling problem is gone**. (Chosen over full `[id]` routes for migration
   cost; the URL param gives the same shareability and can graduate to routes later.)
4. **`AsyncSelect` / `AsyncMultiSelect`**: server typeahead against the `search`
   param — kills every capped preload and both N+1 fan-outs.
5. **`ConfirmDialog`** (danger styling, consequence text) replacing `window.confirm`;
   **dirty-check guard** in FormModal (Escape/overlay prompts "Discard changes?").

### Phase 2 — Flagship migrations (prove the pattern end-to-end)
Migrate the highest-traffic registers to the new primitives:
**information-assets + it-assets** (the flagged pages), **risks**, **controls**,
**compliance requirements**, **vendors**. Each gets: DataTable + drawer + async
pickers + server-