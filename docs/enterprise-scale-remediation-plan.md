# Enterprise-Scale Remediation Plan

An audit of the entire frontend (57 module pages + shared infrastructure) and the
backend list/summary API, triggered by a correct observation: on the Information Asset
page, clicking a row shows the detail **below the whole table**, so at 1,000 assets you
scroll forever. That symptom is one of a *systemic* set of MVP-scale patterns that
repeat across nearly every module. This document is the findings + the plan to fix them.

---

## The core problem, in one line

The app was built to one template — **stat cards → full table → detail rendered below
the table** — and every list **fetches at most 200 rows with no pagination and throws
the total away**. Both assumptions hold at demo scale (3 records) and break at bank
scale. The frontend has **no shared table, no record routes, no async pickers, no
data/cache layer**, and the backend has **no sort support on any of ~75 list endpoints**
and **no index on `status`, `created_at`, or the audit log**.

## Severity summary

| Class | Blocker / Major | Where |
|-------|-----------------|-------|
| **Record #201 is invisible** — `limit=200` (or 100/50) cap, `total` discarded, zero pagination UI | Blocker | Every list page; ~45 API endpoints capped, ~15 fetch-all |
| **Detail rendered below the full table** (scroll-forever, no scroll-into-view) | Blocker | ~18 pages incl. it-assets, controls, compliance, icfr, internal-audit, declarations, shariah |
| **No deep-linkable record URLs** — zero `[id]` routes, zero `useSearchParams`; back exits module; nothing shareable | Blocker | Whole app (0 dynamic routes) |
| **Link pickers preload capped lists** — cannot link record #201+ (e.g. evidence → only first 50 controls) | Blocker | Most forms; evidence picker capped at 50 |
| **Stat cards / regulatory figures computed client-side over the capped fetch** → silently wrong | Blocker | it-assets (total value), information-assets (% self-assessed), shariah (total disbursed money), internal-audit (open/overdue) |
| **Sub-lists rendered in full** — all UAR line-items / all campaign declarants / all requirements in one unvirtualized table or modal | Blocker | access-reviews, declarations, awareness, compliance requirements, internal-audit findings |
| **Audit log shows only the latest 100 events**, no filter/search/paging/export | Blocker | audit page (a likely SBP finding) |
| **No sort on any list endpoint** (0 of ~75) | Major | Backend-wide |
| **FormModal discards unsaved edits** on Escape/overlay/X with no dirty check | Major | All forms (`components/FormModal.tsx:41,93`) |
| **`window.confirm` (81×) / no-confirm deletes** — threat-library and evidence delete instantly | Major | 40+ pages; threat-library, evidence destroy data on one click |
| **No search on core registers** — controls, vendors, policies, users, AML, fraud, shariah, assets | Major | Backend + frontend |
| **Full-table Python aggregation per request** — notifications scans ~15 whole tables per poll per user; dashboard + ~21 summaries load all rows | Major | Backend performance |
| **No data layer** — no cache/cancellation/401 handling; refetch storms; silent empty tables on error | Major | `lib/api.ts` |
| **No toast/feedback, no bulk select, no export on several registers** | Minor→Major | App-wide |

Full per-page evidence is in the audit notes; representative file:line anchors are cited
inline in the phases below.

---

## What already exists to build on (not starting from zero)

- Consistent `Page{items,total,limit,offset}` envelope (`schemas/common.py`) and a
  uniform count-subquery pattern on ~45 endpoints — a `sort_by`/`sort_dir` param and an
  `offset` slot in cleanly.
- Good reference implementations to copy: **issues page** (server search + filters +
  summary + keep-open resync), **vulnerabilities** (server search), **model-risk**
  (Apply-style filters), **declarations** (server summary + server toggle), and the
  `*-summary` endpoints that already exist for scenario/model-risk/outsourcing/bia/icfr.
- `FormModal` (tabbed + required-field validation), `RecordPanels` (custom fields +
  attestation + collaboration), and a decent 422 error normalizer (`formatDetail`).

The fix is mostly **building 6 shared primitives once, then migrating pages to them** —
not rewriting 57 pages by hand.

---

## Plan — phased

### Phase 0 — Backend enablement (unblocks everything; low UI risk)
1. **Shared list-query dependency**: `limit/offset/sort_by/sort_dir/q` params + an
   allow-listed sortable-column map per model; apply to the ~45 paginated endpoints.
2. **Paginate the fetch-all endpoints**: assessments, questionnaires, requirements,
   audit-findings, regulatory reports, governance decisions, awareness, frameworks.
3. **Indexes** (Alembic migration): `status`, `created_at` on all list models;
   `AuditLog(created_at, entity_type, actor)`; the `next_*_date`/`due_date` columns;
   `inherent_score`; `pg_trgm` GIN for `ilike` search.
4. **Audit log**: add entity_type/actor/action/date filters + real pagination + export.
5. **Slim list serializers**: drop the per-row `selectin` collections from list DTOs
   (keep them on the single-record detail), starting with Risk (7 collections/row),
   Asset (~15), Requirement/Policy/Incident (6). Add **GZip middleware**.
6. **Notifications + summaries**: move the ~15-table notification scan to a scheduled +
   cached reconcile; convert `*-summary` endpoints to `GROUP BY`. Fix the controls list
   N+1 (`_attach_risks` per row).

### Phase 1 — Shared frontend primitives (build once, reuse everywhere)
1. **`DataTable`** — server-driven: columns, sortable headers, pagination footer
   (shows `total`), loading/empty/error states, optional row selection + bulk actions,
   built-in debounced search box wired to the API `q` param.
2. **Record `RecordDrawer` + routing** — a slide-over that opens from `?id=` (via
   `useSearchParams`), so every record is **deep-linkable, back-button-correct, and
   shareable**; replaces the below-table detail. (Optionally full `/[module]/[id]`
   routes later.)
3. **`AsyncSelect` / `AsyncMultiSelect`** — server typeahead hitting the list `q`
   param; replaces every preloaded capped picker so you can link record #700 of 1,000.
4. **`ConfirmDialog`** + **`Toast`** — replace 81 `window.confirm`; add save/delete
   feedback; add the missing confirms (evidence, threat-library).
5. **Dirty-check in `FormModal`** — guard Escape/overlay/X when fields changed.
6. **Thin data layer** — a small `useQuery`-style hook (cache + cancellation + 401
   redirect + error surfacing) so pages stop hand-rolling fetch-all and swallowing errors.

### Phase 2 — Migrate flagship modules (prove the pattern end-to-end)
Convert the highest-volume, highest-pain modules first, fully, as the template:
**IT/Information Assets** (the flagged page), **Risk Register**, **Controls**,
**Compliance requirements**, **Vendors**, **Audit log**, **Access Reviews**,
**AML/Fraud**. Each: DataTable + RecordDrawer + AsyncSelect pickers + server
summary-driven stat cards.

### Phase 3 — Mechanical sweep of the rest
Roll the same primitives across the remaining ~40 modules (largely find-and-replace of
the table + detail + pickers), split the 1,000+ line monoliths (data-protection,
shariah, governance, icfr, regulatory-change) into per-section components, and fill the
export/bulk-op gaps.

### Phase 4 — Navigation & polish
Cmd+K command palette, Topbar search that lands on the **record** (needs Phase 1
routing), sidebar favorites/recents, responsive/mobile layout, keyboard nav in pickers.

---

## Effort & sequencing note

Phases 0 and 1 are the real work and must come first — they're the foundation the
57-page migration rides on. Once they exist, per-page migration is fast and low-risk.
Recommended order: **Phase 0 (backend) and Phase 1 (primitives) can proceed in
parallel**, then Phase 2 as the proof, then Phase 3 sweep, then Phase 4 polish.

This is a genuine engineering track, not a quick patch — it's the difference between the
current feature-complete-but-demo-scale build and an enterprise-deployable one.
