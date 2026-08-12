# Client Feedback — Implementation Plan

**Source:** client review meeting (risk register + internal audit walkthrough).
**Date:** 2026-08-12.
**Scope:** 11 raised items. All are in-scope for a GRC platform; roughly two-thirds are
already built and were not surfaced in the demo. This plan covers only the genuine gaps,
plus the two zero-code actions that close the rest.

---

## 0. Conventions every phase must follow

These are the repo's existing rules. Deviating from them is what breaks on-prem upgrades.

| Change type | What you must touch |
|---|---|
| **New table** | Model in `backend/app/models/` + a new `backend/alembic/versions/00NN_*.py`. The dev `create_all` boot path picks new tables up automatically. |
| **New column on an existing table** | Model **and** `backend/app/db/schema_patches.py` (idempotent DDL) **and** the Alembic version. `create_all` cannot `ALTER`; the patch file is the single source of truth applied by both paths. |
| **New enum type** | Add to the enum dict in `schema_patches.py` as well, or on-prem upgrades fail. |
| **New record type that accepts files/comments/tags** | Register in `backend/app/services/entity_types.py` (otherwise attachments are rejected). |
| **New record type that should accept custom fields** | Add its key to `CUSTOM_FIELD_MODELS` in `backend/app/models/custom_field.py`. |
| **New importable/exportable resource** | Declare in `backend/app/services/import_registry.py`. Nothing else changes. |
| **New permission** | `backend/app/core/permissions.py` → `PERMISSION_CATALOG` (roles derive from it). |
| **New licensable module** | `backend/app/core/modules.py` → `MODULES`, and gate the router with `require_module`. |
| **New page** | `frontend/app/(app)/<route>/page.tsx` + entry in `frontend/lib/nav.tsx` and `frontend/lib/modules.tsx`. |
| **Every phase** | Backend tests under `backend/tests/`, and a section in `docs/user-guide.md`. |

**Reference generation** uses `backend/app/services/refs.py`. **Audit logging** uses
`backend/app/services/audit.py` — every new write endpoint records an event.

---

## Phase 0 — Zero-code, do this week

### 0.1 Re-demo the features they didn't see (0.5 day, no code)
Five of the eleven questions are answered by shipped functionality. Run a focused
walkthrough covering, in this order:

1. **Heat map** — dashboard 5×5 grid, Inherent/Residual toggle, click a cell to see the
   actual risk references in it, appetite/tolerance bands (`/dashboard`).
2. **Quantitative scoring** — ALF × SLE = ALE on the risk record, plus
   `/risk-quantification` and `/scenario-analysis` (answers "qualitative ya quantitative?").
3. **Risk ↔ control graph** — risk detail Controls tab, live control-health rollup that
   flips to `issues` when a linked control's audit fails.
4. **Framework linkage** — `/content-library`, install ISO 27001:2022 + the four SBP packs,
   show requirement ↔ risk ↔ control traceability.
5. **Alerting** — notification centre, the scheduler sweep, the email digest, and
   `/status-rules` (e.g. "score ≥ 15 → Above Tolerance").
6. **Approvals** — `/approvals` inbox, maker-checker, `required_approvals` for 4-eyes/6-eyes,
   and the enforced segregation of duties.

**Deliverable:** a scripted demo runbook so this never depends on who is presenting.

### 0.2 Explain the residual-risk methodology (0.25 day, written note)
They believed the system auto-computes residual. It does not, and it should not by default.
Write a one-page note stating: inherent = assessor-entered L×I; residual = separately
assessed L×I after considering control effectiveness; ISO 27005 / 31000 both treat residual
as an assessed judgement, not an arithmetic output; a black-box residual is an audit finding
waiting to happen. Then present Phase 2.3 (**suggested** residual with mandatory override
trail) as the answer to their underlying want.

### 0.3 Move Policy Management under Governance ✅ **DONE 2026-08-12**
The formal minutes name it precisely — *"Policy management should fall under governance"* —
so only Policy Management moved; awareness and declarations were left where they are.

The group holding Board & Committees, Delegation of Authority and the Legal Register was
titled **Organization**, so moving policy there would not have *visibly* satisfied the
request. It is now titled **Governance**, which matches what it actually contains. That
rename is a judgement call and reverts in one line of `frontend/lib/nav.tsx` if they would
rather keep the old label.

### 0.1 / 0.2 ✅ **DONE 2026-08-12**
* `docs/demo-runbook.md` — a fixed-order walkthrough with the specific click that proves
  each of the five already-shipped capabilities, plus what not to do.
* `docs/residual-risk-methodology.md` — the written answer for Usman on inherent vs
  residual, why the standards make it an assessed judgement, and what we still need from
  them to finish configuring it.

---

## Phase 1 — Smart Import Mapper ✅ **DELIVERED 2026-08-12** *(their #1)*

**Shipped:** `services/import_mapping.py` (five-tier matcher, GRC synonym dictionary,
banner-row detection, XLSX loader), `models/import_profile.py`, `schemas/dataio.py`,
four new endpoints on `api/v1/dataio.py`, migration `0016_import_profiles.py`, a 4-step
wizard in `components/ImportExport.tsx`, and 33 tests in `tests/test_import_mapping.py`.

**Verified end-to-end** against a running stack with a realistic bank register (banner
row + 12 non-matching headers): 10/12 columns matched automatically, unmatched columns
left for the user, preview wrote nothing, import created 3 risks with correct references
and scores, custom-field mapping landed its value, `.xlsx` upload worked including
integer/date coercion, one bad row was isolated with a clear message, saved profiles
round-tripped, and a template-header file still imported with no mapping (backwards
compatible).

The original scope is kept below for reference.



**Problem:** import requires our exact CSV headers. Every bank's sheet differs, so onboarding
means the client hand-rewrites their file.

**Current state:** `backend/app/api/v1/dataio.py` + `import_registry.py` already give a
declarative per-resource column schema, template download, export, link resolution by
reference/name, and row-isolated error reporting. The mapper builds on top — no rewrite.

### Backend
1. **`POST /io/{resource}/inspect`** — accept the uploaded file, return detected headers,
   row count, and a suggested `{source_header → field}` mapping.
   - Suggestion algorithm: exact match → case/punctuation-normalised match → token overlap
     (e.g. "Risk Desc" → `description`) → known-synonym table per field
     (`likelihood`: likely, probability, prob; `impact`: severity, consequence; etc.).
   - Return a confidence per suggestion so the UI can flag the weak ones.
2. **XLSX support** — add `openpyxl`; convert sheet 1 to CSV server-side and reuse the
   existing pipeline. Multi-sheet: return the sheet list, let the user pick.
3. **`POST /io/{resource}/preview`** — apply a mapping to the first 20 rows and return the
   resolved payloads + per-row errors, **without writing anything**. Reuses `_row_to_payload`.
4. **`POST /io/{resource}/import`** — extend `ImportRequest` with an optional
   `mapping: dict[str,str]` and `custom_field_mapping: dict[str, uuid]`. When absent,
   behaviour is byte-identical to today (backwards compatible).
5. **Unmapped columns → custom fields** — offer to create a `CustomField` on the target model
   for any leftover column, then write EAV values as part of the same row transaction.
6. **New table `import_profiles`** — saved mapping per (tenant, resource, name), so the next
   quarterly upload is one click. Columns: `resource`, `name`, `mapping` (JSON), `created_by`.

### Frontend
Rewrite `frontend/components/ImportExport.tsx` as a 4-step wizard:
**Upload → Map (two-column mapper, auto-filled, unmapped highlighted) → Preview (20 rows,
errors inline) → Commit (result summary + downloadable error CSV).**
Add "Save this mapping as…" and a profile picker on step 2.

### Migration
`0016_import_profiles.py` — new table only. No `schema_patches.py` change needed.

### Tests
`backend/tests/test_import_mapper.py` — header suggestion accuracy on 3 realistic bank sheets;
preview writes nothing; mapping round-trips through a saved profile; unmapped → custom field;
legacy no-mapping import still passes.

### Acceptance
A raw bank risk sheet with none of our headers imports end-to-end with zero manual file edits.

**Estimate: 6–8 dev-days.**

---

## Phase 2 — Risk methodology ✅ **DELIVERED 2026-08-12** *(their #2, #3, #4)*

**Shipped:** size-derived severity bands in `services/risk_scoring.py` (fractions chosen
so the 5×5 default reproduces the original bands byte-for-byte), `RiskSetting.matrix_size`
+ `risk_matrix_levels` + `residual_policies` models, `services/residual_engine.py`,
six new endpoints (`risk-matrix-config` GET/PUT, `residual-policy` GET/PUT,
`risks/{id}/suggested-residual`, `risks/{id}/accept-residual`), ISO/IEC 27005:2022 and
ISO 31000:2018 packs (34 clauses each) in `framework_library.py`, migration
`0017_risk_methodology.py` + `risk_methodology_ddl_statements()`, scale-aware
`RiskHeatmap`/dashboard/risk form, `ResidualSuggestion` and `RiskMethodology`
components, and 42 tests in `tests/test_risk_methodology.py`.

**Verified end-to-end:** default install still bands 1-4/5-9/10-14/15-25; growing to 6×6
rebands every risk (20 → high instead of critical) and the heat map returns 36 cells;
shrinking is refused while risks score above the new maximum, naming them; a 6 is
rejected on a 5×5 tenant; an effective control produces a justified −2 suggestion; an
overdue control audit withdraws that credit and the suggestion climbs back to inherent
on its own; accepting stamps the sign-off; overriding without a reason is refused;
retuning the policy weights changes the suggestion with no code change.

**One real bug caught by that testing:** FastAPI re-validates a handler's return value
against `response_model`, and the second pass carries no validation context — which was
silently resetting a 6×6 tenant's severities to the default 5×5 bands. Fixed by making
the banding validator never overwrite an already-banded value; pinned by
`test_revalidating_a_read_model_keeps_its_bands`.

**Deferred from this phase:** seeding the ISO 27005 threat/vulnerability catalogues into
the Threat Library moves to Phase 3, where the risk-scenario templates need the same data.

The original scope is kept below for reference.



### 2.1 Configurable risk matrix (currently hard-coded 5×5)
**Current:** `backend/app/services/risk_scoring.py` has fixed bands (1–4 Low, 5–9 Medium,
10–14 High, 15–25 Critical); `risk.py` has `CheckConstraint(... BETWEEN 1 AND 5)`; the
`*_score` columns are Postgres generated columns.

**Change:** extend `RiskSetting` (already per-tenant, holds appetite/tolerance) with
`matrix_size` (3–6), plus a new `risk_matrix_levels` table holding, per tenant and axis
(likelihood/impact), the level number, label and definition text; and a
`risk_matrix_bands` table for band thresholds, labels and colours.

**Careful:** the `BETWEEN 1 AND 5` check constraints must be relaxed to `BETWEEN 1 AND 6` and
validated in the schema layer against the tenant's configured size instead — a DB constraint
cannot be per-tenant. Keep the generated `*_score` columns as-is (still L×I).

`severity_for_score()` becomes tenant-aware: load bands, fall back to the current defaults
when unconfigured, so existing installs are unchanged.

**Frontend:** a matrix configurator under `/settings`; `RiskHeatmap.tsx` and the dashboard
grid render N×N from config instead of a hard-coded 5.

### 2.2 ISO 27005 + ISO 31000 packs
`backend/app/services/framework_library.py` currently ships 13 packs (ISO 27001:2022,
42001, NIST CSF 2.0, SP 800-53r5, PCI DSS 4.0, SOC 2, GDPR, HIPAA, CIS v8, and four SBP packs).
Add two more, following the identical template structure — pure data, no code change:
- **ISO/IEC 27005:2022** — risk-management process clauses, plus its threat and vulnerability
  catalogues seeded into the Threat Library (`threats` / `vulnerabilities` tables).
- **ISO 31000:2018** — principles, framework and process clauses.

Register both in `TEMPLATES` and in the `content_library` pack catalogue.

### 2.3 Suggested residual from control effectiveness — **the sensitive one**
**Design constraint (non-negotiable):** the system *suggests*, the owner *decides*. Never
silently overwrite an assessed residual.

1. **New table `residual_policies`** (per tenant): a reduction weight per
   `ControlEffectiveness` level (`ineffective` / `partially_effective` / `effective` /
   `not_assessed`), whether reduction applies to likelihood, impact or both, and a maximum
   total reduction cap.
2. **`backend/app/services/residual_engine.py`** — pure function, mirroring `risk_scoring.py`'s
   dependency-free style:
   `suggest_residual(inherent_l, inherent_i, controls, policy) → (l, i, rationale[])`.
   Only controls that are **linked, active and not currently failing** contribute — the existing
   `Risk.control_health` logic already identifies failing ones. Returns a human-readable
   rationale list ("CTL-014 Effective → −1 likelihood") so the number is never a black box.
3. **New columns on `risks`** (→ `schema_patches.py` **and** the Alembic version):
   `suggested_residual_likelihood`, `suggested_residual_impact`, `residual_override_reason`,
   `residual_accepted_by`, `residual_accepted_at`.
4. **`GET /risks/{id}/suggested-residual`** returns the suggestion + rationale;
   **`POST /risks/{id}/accept-residual`** copies it into the real residual fields with the
   acceptor recorded. Overriding with a different number requires `residual_override_reason`.
5. **Reactive:** when a linked control's audit fails, the suggestion rises again on next read.
   Raise a notification ("residual suggestion changed — reassessment due") from
   `notifications.py`.

**Frontend:** on the risk record, a "Suggested residual: 6 (from 15)" panel with the rationale
list, an **Accept** button and an **Override with reason** path.

### Migration
`0017_risk_methodology.py` — new tables (`risk_matrix_levels`, `risk_matrix_bands`,
`residual_policies`) + new `risks` columns + relaxed check constraints.
Mirror the `risks` column additions in `schema_patches.py`.

### Tests
Band lookup with a custom 4×4 config; default behaviour unchanged when unconfigured; residual
suggestion with mixed control effectiveness; failing control raises the suggestion; accept
writes the audit trail; override without a reason is rejected.

### Acceptance
A bank configures a 4×4 matrix with its own level definitions, installs 27005, links three
controls to a risk, and sees a justified suggested residual it can accept or override.

**Estimate: 10–12 dev-days** (2.1 ≈ 5, 2.2 ≈ 2, 2.3 ≈ 4).

---

## Phase 3 — Generate applicable risks from assets ✅ **DELIVERED 2026-08-12** *(their #8)*

**Shipped:** `services/risk_scenarios.py` — a 42-scenario banking catalogue (access
control, data protection, cyber, continuity, operations, third party, physical,
compliance, financial crime) plus the pure derivation rules;
`models/risk_scenario.py` (tenant-editable library the catalogue installs into);
`api/v1/risk_scenarios.py` with library CRUD, `install-library`, `generate` (writes
nothing) and `commit`; migration `0018_risk_scenario_templates.py`; an import-registry
entry so a bank can bulk-load its own scenarios; `GenerateRisks` and `ScenarioLibrary`
components wired into both asset registers and the Threat Library; 52 tests in
`tests/test_risk_scenarios.py`.

**Also closed the Phase 2 deferral:** installing the library seeds the Threat and
Vulnerability catalogues with everything the scenarios reference (64 of each in the test
tenant), so generated risks carry real graph links rather than free text.

**Verified end-to-end:** generating before install returns a clear instruction rather
than an error; install created 42 scenarios and is idempotent on re-run (0 installed, 42
skipped, local edits preserved); 6 IT assets × 42 scenarios produced 222 proposals; one
critical information asset produced 30, correctly scored — a confidentiality scenario
opened at impact 5 (C=critical) while an availability scenario on the same asset opened
at 4 (A=high); committing produced R-053/054/055 as ordinary risks with asset, threat,
vulnerability links and treatment text; re-running then skipped exactly those three;
criticality and category filters and per-scenario disable all narrow the run as expected.

**One real bug caught by that testing:** the dev tenant held two pairs of distinct assets
sharing a name, which produced indistinguishable proposed titles — and since the title is
the de-duplication key, that would have created unusable duplicate risks *and* poisoned
the next run's dedup. Fixed with `_disambiguate()`, which suffixes colliding titles with
the asset's hostname/serial/short-id; pinned by
`test_colliding_titles_are_disambiguated_by_the_asset`.

**Deliberate scope call:** tenant-authored scenarios are supported through the library
table, CRUD API and CSV import, but there is no bespoke scenario-authoring form yet —
editing an installed scenario's likelihood and on/off state is inline in the library
table, which covers the common case.

The original scope is kept below for reference.



**Current:** `asset_threats` and `asset_vulnerabilities` link tables already exist, as do
`risk_assets`, `risk_threats`, `risk_vulnerabilities`. Assets carry `asset_class`,
`confidentiality`/`integrity`/`availability`, `criticality` and derived criticality. Everything
needed is modelled — nothing generates.

### Backend
1. **New table `risk_scenario_templates`** — a reusable library row: title, description,
   category, applicable asset classes, optional threat and vulnerability references, and
   **default likelihood** + an **impact-derivation rule** (`from_criticality` /
   `from_cia_max` / `fixed`). Seed ~40 banking-relevant scenarios (and let the ISO 27005
   pack from Phase 2.2 contribute more).
2. **`POST /risks/generate-from-assets`** — body: `asset_ids[]` (or a filter), optional
   template filter. For each asset × matching template, produce a **proposed** risk:
   - title interpolated (`"{threat} affecting {asset.name}"`),
   - inherent likelihood from the template default,
   - inherent impact derived from the asset's criticality/CIA per the rule,
   - pre-linked asset, threat, vulnerability, and any controls already mapped to that asset.
   Returns proposals **without persisting** — deduplicated against existing risks on
   (asset, threat, vulnerability) so re-running never creates duplicates.
3. **`POST /risks/generate-from-assets/commit`** — accepts the edited subset the user ticked,
   creates real risks through the normal `create_risk` path so refs, audit log and links all
   behave identically to manual creation.

### Frontend
On `/it-assets` and `/information-assets`: a **"Generate risks"** action (single asset or
bulk selection) → a review table of proposals with editable scores and tick boxes → Commit.
Mirror the entry point on `/risks`.

### Migration
`0018_risk_scenario_templates.py` — new table + seed data.

### Tests
Impact derivation per rule; dedup on re-run; commit path produces refs and links; proposals
are not persisted before commit.

### Acceptance
Import 200 IT assets, click Generate, and get a de-duplicated, pre-scored, pre-linked
candidate risk register the risk owner edits rather than types from scratch.

**Estimate: 6–8 dev-days.**

---

## Phase 4 — TAT / SLA engine ✅ **DELIVERED 2026-08-12** *(their #6)*

**Shipped:** `models/sla.py` (target days, early-warning threshold and escalation role
per record type × severity), `services/sla.py` (entity registry, shipped defaults, pure
clock arithmetic, `reconcile`/`summary`), `api/v1/sla.py` (`GET/PUT /sla-policies`,
`GET /sla-breaches`), TAT columns on risks/issues/audit_findings/incidents via
`tat_ddl_statements()`, migration `0019_sla_engine.py`, two new categories in the
existing `scan_alerts()` sweep, escalation email in the scheduler, a new `sla:manage`
permission, the `/sla-policies` page, a `TatReminder` sign-in modal in the app shell, a
TAT entry at the top of the dashboard attention queue, and 24 tests in `tests/test_sla.py`.

**Verified end-to-end:** the grid ships complete on defaults (16 scopes, all flagged
`is_default`); the seeded register surfaced 3 genuine breaches across incident, risk and
issue; lengthening the critical-risk target to 365d cleared its breach *immediately* and
tightening it to 5d re-raised more; disabling a scope removed risks from chasing
entirely rather than falling back to the default; TAT columns are stamped on open records
and cleared on closed ones so nothing re-alerts forever; three TAT alerts reached the
notification centre as `critical`; escalation resolved `Admin` → `admin@acme.com` for a
configured scope and `[]` for an unconfigured one. Back-dating one record through a 10-day
window walked the full sequence: **on track at 7 days → at risk at 8 (80%) → breached at
11 → 15 days over at 25**.

**One real bug caught by that testing:** `GET /sla-breaches` returned 500 because the
service deliberately returns plain dataclasses (so the clock arithmetic stays testable
without Pydantic) and the response schema could not read them. Fixed with
`from_attributes` on `TatRecordRead`.

**Design decisions worth recording:**

- **No `tat_start_date` column.** The clock starts when the record was raised, which
  `created_at` already records; a third column would be a copy that can drift.
- **TAT is separate from a record's own `due_date`** — policy allowance vs. what was
  agreed with the owner. Both are tracked; the gap between them is itself informative.
- **Disabling a scope means no clock**, not a fall-back to the default, so a bank that
  deliberately excludes low-severity findings is not chased about them anyway.
- **Escalation is by email**, because notifications are tenant-wide rather than addressed
  to individuals — and telling the line above the owner in writing is what a bank means
  by escalation.
- **`sla:manage` is its own permission**, not folded into module write rights: who may
  lengthen a remediation deadline is a governance control in its own right.

The original scope is kept below for reference.



**Current:** the alert engine is real — `backend/app/services/scheduler.py` sweeps every
tenant on a timer, `notifications.py` computes ~20 categories of due/overdue/breach alerts
with dedup and auto-resolve, results land in the notification centre and an email digest.
Records already carry `due_date`, `next_review_date`, `treatment_deadline`, etc.
**Missing:** a named, configurable TAT clock per record type and severity, and any pop-up.

### Backend
1. **New table `sla_policies`** — `(tenant, entity_type, severity) → target_days`, plus
   optional `warn_at_percent` (e.g. alert at 80% of TAT elapsed) and an
   `escalate_to_role`. Entity types drawn from the existing `entity_types.py` registry.
2. **New columns** on the SLA-bearing records — start with `risks`, `issues`,
   `audit_findings`, `incidents`: `tat_start_date`, `tat_due_date`, `tat_breached_at`.
   Computed on create/status-change from the applicable policy.
   (→ `schema_patches.py` + Alembic.)
3. **`backend/app/services/sla.py`** — `compute_due(entity, severity, policy)` and
   `breach_state(entity) → on_track | at_risk | breached`.
4. **Extend `notifications.scan_alerts()`** with two new categories: TAT approaching
   (warning, at `warn_at_percent`) and **TAT breached** (critical). Reuse the existing dedup
   key pattern (`tat-breach:{entity_type}:{id}`) so nothing duplicates.
5. **Escalation:** on breach, additionally notify the owner's manager / the configured role.

### Frontend
- A **TAT breach widget** on `/dashboard` — count by module, click through to the records.
- A **login-time modal** listing TAT breaches assigned to the current user, dismissible,
  suppressed for 24h once dismissed (store in `NotificationView`-style per-user state).
- TAT columns and RAG chips on the risk / issue / finding tables.
- An **SLA policy editor** under `/settings`.

### Migration
`0019_sla_engine.py` — new table + columns on four existing tables (mirror in
`schema_patches.py`).

### Tests
Due-date computation per severity; at-risk threshold fires once; breach fires once and
auto-resolves on closure; escalation targets the right role; no duplicate notifications
across sweeps.

### Acceptance
Set "Critical risk must be treated in 15 days". Create one, wind the clock, and see: an
at-risk warning at day 12, a critical breach alert at day 16, a dashboard widget, a login
pop-up, and an escalation email.

**Estimate: 6–8 dev-days.**

---

## Phase 5 — Audit provenance ✅ **DELIVERED 2026-08-12** *(their #9)*

**Shipped:** an `AuditType` enum (internal / external statutory / regulatory / certification)
plus `auditor_firm`, `report_reference` and `report_date` on engagements via
`audit_type_ddl_statements()`; migration `0020_audit_provenance.py`; an `audit_type`
filter on the engagement list; a new `GET /assurance-summary` roll-up; `AuditFinding`
added to the import registry with a standalone `create_finding`; audit-type column,
form fields and an assurance-coverage table on the internal-audit page.

**Report attachment already worked** — `RecordPanels` on the engagement detail already
renders `CollabPanel`, which uploads and downloads files against any registered entity.
No new plumbing was needed; the plan over-scoped this.

**Verified end-to-end:** an SBP inspection was recorded with its report reference and
date, the `audit_type=regulatory` filter returned it, a three-line regulator finding list
imported by CSV into the same remediation pipeline, and the roll-up then answered *"how
many SBP inspection findings are open?"* — 3 open, 1 already overdue — beside internal
audit's own numbers.

The original scope is kept below for reference.


**Current:** `backend/app/models/internal_audit.py` already has the audit universe
(`AuditableUnit` with inherent risk, frequency, next-due, overdue flag), engagements with
lifecycle and opinion rating, procedures/working papers, and findings with rating,
recommendation, management response, owner, due date, closure status and links to
controls/risks/requirements. `finding_count`, `open_finding_count` and overdue flags already
answer "kitne open, kitne resolved". The generic file API
(`POST /collab/{entity_type}/{entity_id}/files`) already exists.

### Gaps to close — all small
1. **New columns on `audit_engagements`**: `audit_type` (new enum:
   `internal` / `external_statutory` / `regulatory_sbp` / `third_party_certification`),
   `auditor_firm`, `report_date`, `report_reference`.
   (→ enum **and** columns in `schema_patches.py` + Alembic.)
2. **Register `audit_engagement` in `entity_types.py`** if not already present, so the
   report PDF and evidence files attach to the engagement.
3. **Frontend:** add the `FileAttachments` panel to the engagement detail in
   `frontend/app/(app)/internal-audit/page.tsx` (the component exists — it's currently only
   wired into `/evidence`). Add an audit-type filter and column to the engagement list.
4. **Roll-up:** extend the internal-audit summary endpoint with counts by audit type and
   open-vs-closed findings per type, so "external audit ka status" is one screen.
5. **Findings import:** `AuditFinding` should be added to `import_registry.py` so a firm's
   finding list arrives by CSV (engagements are already registered).

**Explicitly out of scope:** AI extraction of findings from an uploaded PDF. Error-prone,
and auditors must confirm each finding anyway. Revisit later if they insist.

### Migration
`0020_audit_type.py`.

### Acceptance
An SBP inspection and a Big-4 external audit are both tracked as engagements with their
report PDFs attached, and the dashboard shows open vs closed findings split by audit type.

**Estimate: 3–4 dev-days.**

---

## Phase 6 — Audit plan, programmes, calendar ✅ **DELIVERED 2026-08-12** *(their #11, part 1)*

**Shipped:** `models/audit_plan.py` (plans, plan lines, programmes, programme steps),
`api/v1/audit_plan.py` with 21 endpoints, migration `0021_audit_plan_programs.py`, and
three new tabs on the internal-audit page — Annual Plan, Programmes and Calendar.

**Verified end-to-end:** submitting an empty plan was refused; generating from the audit
universe produced risk-based lines with quarters derived from each unit's due date, and
re-running skipped units already planned; submitting raised a real `ApprovalRequest` in
the shared inbox (APR-003) and re-submitting an approved plan was refused; coverage
reported plan-vs-actual by quarter. A checklist generated from the installed ISO 27001
framework produced one step per clause, **each linked back to the requirement it tests**;
applying it to an engagement created working papers `APG-001-001…005`, and re-applying
added 0 and skipped 5 rather than duplicating. The calendar returned all four event kinds
(fieldwork with an end date, finding due, unit due, unstarted plan line) and refused an
inverted date range.

**Deviation from the plan:** no separate `audit_plan:read/write` permissions — plans and
programmes are internal audit, so they reuse `internal_audit:read/write`. A new permission
would have needed role updates at every client for no separation that matters.

The original scope is kept below for reference.


This is the largest functional addition. Treat it as its own milestone.

### 6.1 Annual Audit Plan
**New tables:**
- `audit_plans` — year, title, status (`draft` / `submitted` / `board_approved` / `active` /
  `closed`), total budgeted hours, approval linkage into the existing `ApprovalRequest`
  flow (so board/BAC approval reuses maker-checker rather than inventing a new mechanism).
- `audit_plan_items` — one planned engagement: auditable unit, planned quarter/month,
  budgeted hours, assigned lead, and a nullable FK to the `AuditEngagement` created when
  the audit actually starts.

**Endpoints:** CRUD, plus `POST /audit-plans/{id}/generate-from-universe` — build a
risk-based draft plan from `AuditableUnit.inherent_risk` + `audit_frequency` +
`next_audit_due` (the data is already there), and `GET /audit-plans/{id}/coverage` for
plan-vs-actual %.

### 6.2 Checklist / audit programme templates
**New tables:** `audit_programs` (name, framework link, description) and
`audit_program_steps` (title, test procedure text, expected evidence, requirement link).

**The high-value endpoint:** `POST /audit-programs/from-framework/{framework_id}` — generate
a step per `Requirement` of an installed framework. Since ISO 27001:2022 with its full 93
Annex A controls is already in the content library, this produces a clause-by-clause 27001
checklist with no manual authoring.

Then `POST /audit-engagements/{id}/apply-program/{program_id}` instantiates the steps as
`AuditProcedure` rows — the existing per-engagement checklist. No new checklist concept is
introduced; templates simply populate what already exists.

### 6.3 Audit calendar
No new data — `planned_start`, `planned_end`, `next_audit_due`, finding `due_date` and
control `next_audit_date` all exist. Build a month/quarter calendar view at
`/internal-audit` (new tab) backed by one `GET /audit-calendar?from=&to=` endpoint that
returns typed events. Follow the pattern already used by the regulatory-returns calendar in
`frontend/app/(app)/regulatory-change/page.tsx`.

### Also required
- `audit_plan` and `audit_program` into `entity_types.py` and `CUSTOM_FIELD_MODELS`.
- New permissions `audit_plan:read` / `audit_plan:write` in `PERMISSION_CATALOG`.
- `import_registry.py` entries for plans and program steps.

### Migration
`0021_audit_plan_programs.py`.

### Acceptance
Generate a FY plan from the audit universe, get it board-approved through the approvals
inbox, instantiate a 27001 checklist onto an engagement in one click, and see the year on a
calendar with plan-vs-actual coverage.

**Estimate: 12–15 dev-days.**

---

## Phase 7 — Workflow designer ✅ **DELIVERED 2026-08-12** *(their #11, part 2)*

**Shipped:** `models/workflow.py` (definitions, stages, instances, instance stages),
`services/workflow_engine.py`, `api/v1/workflows.py`, a hook in the approvals decision
endpoint, migration `0022_workflow_designer.py`, the `/workflows` designer page and a
`WorkflowStrip` progress component on the risk record.

**Verified end-to-end:** with no route defined, `start` returned `started=false` and
nothing changed — the safety property. A three-stage route (record owner → role → named
user, with per-stage deadlines) was defined, enabled, and walked: stage 1 raised a real
approval request due in 3 days; **the submitter was refused with the existing segregation-
of-duties error**; an independent checker then approved each stage and the instance moved
1/3 → 2/3 → approved. A rejection on a second record ended the route and marked the
remaining stages *skipped*, not approved. Enabling a route with no stages was refused.

**Two real bugs caught by that testing:**

1. **Every stage was created as stage 1.** `StageCreate.order_index` defaulted to 1, which
   is indistinguishable from a caller explicitly asking for first place, so the "or next
   position" fallback never fired. The default is now 0, meaning *append*.
2. **The completion notification was deleted before anyone could see it.** The alert
   scanner reconciles the notifications table by removing anything it did not just
   produce — correct for *conditions* that resolve, wrong for *events* that happened.
   Event notifications now carry an `event:` dedup prefix that `refresh()` preserves.
   Both are pinned by regression tests.

**Design decisions worth recording:**

- **A stage never approves anything itself** — it raises a real `ApprovalRequest` and
  waits. That is what makes segregation of duties, N-eyes counting, the inbox and the
  audit trail apply to workflow stages automatically, and a test asserts the engine
  contains no approval-writing code.
- **Enabling one route disables any other for that record type**, so "which approval
  applied?" always has one answer.
- **Deleting a route with records still travelling it is refused**; disable it instead so
  those approvals can finish.

The original scope is kept below for reference.


**Current:** workflow is real but fixed-shape — `WorkflowMixin` gives every major record
`draft → in_review → approved → retired`; `ApprovalRequest` supports N-approver
maker-checker with due dates and an audit-grade action log; `DualControlRule` already makes
four-eyes configurable per module + action with monetary thresholds; segregation of duties is
enforced at runtime in `dual_control.py`. What's missing is **user-defined multi-stage
routing**.

### Backend
1. **New tables:**
   - `workflow_definitions` — tenant, entity type, name, enabled, version.
   - `workflow_stages` — order, name, approver mode (`role` / `named user` / `record owner` /
     `line manager`), approver reference, `required_approvals`, parallel-or-sequential flag,
     SLA days (reuse Phase 4), and an on-timeout action (escalate / auto-approve / block).
   - `workflow_instances` + `workflow_instance_stages` — the runtime state of one record
     moving through one definition.
2. **`backend/app/services/workflow_engine.py`** — `start(entity)`, `advance(instance,
   decision)`, `current_stage(instance)`. Each stage materialises a real `ApprovalRequest`
   so the existing inbox, notifications, dual-control enforcement and audit log all keep
   working unchanged. **Do not build a parallel approval mechanism.**
3. **Fallback:** entity types with no definition keep today's fixed lifecycle exactly.
   This must stay true — it's what keeps existing installs safe.
4. **Completion:** on final approval, set `workflow_status = approved` and raise a
   notification (their "pop-up aaye ke sab se approve ho gaya hai"), surfaced through the
   Phase 4 pop-up mechanism.

### Frontend
- `/settings/workflows` — a stage-list designer (add/reorder/remove stages, pick approver
  mode, set SLA and timeout action), with a per-entity-type enable switch.
- A **stage progress strip** on any record under an active workflow ("Stage 2 of 4 — Risk
  Committee — 3 days left"), showing who approved what and when.

### Migration
`0022_workflow_designer.py`.

### Tests
Sequential and parallel stages; rejection at any stage terminates; SoD still blocks a maker
from approving their own stage; timeout escalation; records without a definition behave
exactly as before (regression guard).

### Acceptance
An admin defines "Risk acceptance: Owner → Dept Head → CRO → Risk Committee (2 of 3)",
a risk routes through it, each stage appears in the approvals inbox with SoD enforced, and
the submitter gets a completion pop-up.

**Estimate: 12–15 dev-days.**

---

## Sequencing and totals

| Phase | Deliverable | Est. (dev-days) | Client-visible value |
|---|---|---|---|
| ~~0~~ | ~~Re-demo runbook, residual note, nav move~~ ✅ **done** | ~~1~~ | Closes 5 of 11 questions immediately |
| ~~1~~ | ~~Smart Import Mapper~~ ✅ **done** | ~~6–8~~ | Unblocks onboarding — highest impact |
| ~~2~~ | ~~Configurable matrix · 27005/31000 · suggested residual~~ ✅ **done** | ~~10–12~~ | Answers the methodology objections |
| ~~3~~ | ~~Generate risks from assets~~ ✅ **done** | ~~6–8~~ | The "automatically aa jayein" ask |
| ~~4~~ | ~~TAT / SLA engine + breach pop-up~~ ✅ **done** | ~~6–8~~ | The "remind karwaye" ask |
| ~~5~~ | ~~Audit type + report attachment~~ ✅ **done** | **3–4** | Internal vs external tracking |
| ~~6~~ | ~~Audit plan · checklist templates · calendar~~ ✅ **done** | **12–15** | Their strongest suggestion |
| ~~7~~ | ~~Workflow designer~~ ✅ **done** | **12–15** | "Workflow customization bhi chahiye" |
| | **Total** | **56–71 dev-days** | ≈ 11–14 weeks for one developer |

**Recommended commercial framing:** Phases 0–5 (**32–41 days, ~7–8 weeks**) as the committed
response to this meeting. Phases 6–7 (**24–30 days**) as a second milestone with its own
timeline — they are a distinct product capability, not a punch-list fix, and Phase 6 in
particular overlaps with dedicated audit-management products.

**Parallelisation:** Phases 1, 3 and 5 are independent and can run concurrently. Phase 4 must
precede Phase 7 (the workflow designer reuses the SLA engine). Phase 2.1 should precede 2.3.

---

## Decisions needed from the client before starting

1. **Residual formula (blocks 2.3):** does the bank want pure control-effectiveness reduction,
   or its own weighting scheme? Get their existing methodology document if one exists.
2. **Matrix size and level definitions (blocks 2.1):** 5×5 or something else, and their own
   wording per level.
3. **TAT targets (blocks 4):** days per severity, per record type, and who escalation goes to.
4. **Nav grouping (blocks 0.3):** policy only under Governance, or policy + awareness +
   declarations?
5. **Audit types (blocks 5):** confirm the four proposed types cover their reality
   (internal, external statutory, SBP regulatory, certification body).

Items 1–3 are the ones that will cause rework if guessed. Ask for them in writing.

---

## Explicitly out of scope

- **AI extraction of findings from uploaded audit report PDFs** — document-AI, not GRC;
  error-prone; auditors verify every finding regardless. CSV import covers the need.
- **Auto-computed residual with no human acceptance** — refused on methodology grounds; it
  would be a black box that fails an SBP or certification audit. The suggestion + override
  trail in 2.3 is the correct form of this request.
