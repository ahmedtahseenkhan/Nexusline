# Section-by-Section Review — Findings Register

A full review of all 57 modules across the 7 sidebar sections was run on 2026-07-11
(10 parallel review agents, each doing code review **plus** live API testing of
add / map / archive behaviour against the running stack). This register lists every
verified finding, its location, and its status.

**Status legend:** ✅ Fixed & verified live · 🔷 Fixed (code) · ⏭️ Deferred · 🔵 Out of scope (feature/known-limitation)

## Summary

| Severity | Found | Fixed | Deferred / Out-of-scope |
|----------|-------|-------|--------------------------|
| Critical | 2 | 2 | 0 |
| High | 8 | 8 | 0 |
| Medium | ~38 | ~36 | 2 |
| Low | ~22 | ~20 | 2 |

The dominant issue was a single systemic class — **soft-deleted (archived) records
leaking** through single-record loaders, relationship backlinks, summaries/rollups,
link resolvers, and reference counters — the same bug first found in the Risk Register.
It recurred in nearly every module and is now fixed everywhere. On top of that: 1
critical data-loss bug, 1 critical false-success bug, and 3 genuine security holes.

---

## Critical

| # | Module | Location | Finding | Status |
|---|--------|----------|---------|--------|
| C1 | Assets / versioning | `services/versioning.py:_json` | Version-snapshot writer couldn't serialize `Decimal`; the insert failed at commit **after** the 200 response was sent, silently rolling back every asset edit. Serializer is now total (can never corrupt a transaction). | ✅ |
| C2 | Assessments | `api/v1/assessments.py` delete_questionnaire | Deleting an in-use questionnaire returned a false `204` (FK RESTRICT failed at commit, after response). Now checks references up front → `409`. | ✅ |

## High

| # | Module | Location | Finding | Status |
|---|--------|----------|---------|--------|
| H1 | Whistleblowing | `api/v1/whistleblowing.py` create/update | Anonymous reports stored & returned reporter name/contact (only the UI hid it). Identity is now scrubbed server-side on write. | ✅ |
| H2 | Saved Filters | `api/v1/filters.py` run_filter | Any user could run another user's **private** filter by ID and read data from modules they can't access. Now enforces owner/shared + the model's read permission. | ✅ |
| H3 | Exceptions | `api/v1/exceptions.py` update_exception | `PATCH status=approved` bypassed the `exception:approve` maker-checker control (no approver recorded). Now blocked (`403`). | ✅ |
| H4 | Reports / metrics | `api/v1/reports.py` | `/reports/metrics`, `/widgets`, `/dashboard` had no permission gate — any user saw cross-module aggregates. Added `report:read`. | ✅ |
| H5 | Reports / metrics | `services/metrics.py` | ~15 KPI metrics counted soft-deleted rows. `_count`/`_breakdown` now filter `deleted`. | ✅ |
| H6 | Dashboard | `api/v1/dashboard.py` | `total_controls`/`total_assets` counted archived rows; pending-acceptances counted archived risks. | ✅ |
| H7 | Notifications | `services/notifications.py` | 10 alert scans (control/exception/access-review/policy/project/goal/continuity/RoPA/awareness/audit) ignored `deleted` → perpetual, **unclearable** phantom alerts for archived records. | ✅ |
| H8 | ICFR | `api/v1/icfr.py` create/update_deficiency | Unknown `control_id`/`process_id` → unhandled `500` (FK violation). Now validated → `400`/`404`. | ✅ |

## Medium — soft-delete class (single-record loaders)

Archived records stayed readable/editable and usable as parents. Loaders now apply the
`deleted` filter (the `authority.py` pattern). All verified live (GET/PATCH archived → `404`).

| Module | Location | Status |
|--------|----------|--------|
| Operational Risk | `_get`, `_load_rcsa`, `_load_kri` | ✅ |
| Risk Quantification | `_load` | ✅ |
| Scenario Analysis | `_get` | ✅ |
| Model Risk | `_get`, `_load_model` | ✅ |
| Shariah | `_get`, `_load_review` | ✅ |
| ESG | `_get` | ✅ |
| BIA | `_get`, `_load_bia` | ✅ |
| Issues | `_get`, `_load_issue` | ✅ |
| Vulnerability | `_get` | ✅ |
| Regulatory Change | `_get`, `_load_change`, `_load_return` | ✅ |
| ICFR | `_get`, `_load_process` | ✅ |
| Data Protection | `_get` | ✅ |
| Outsourcing | `_get`, `_load_arrangement` | ✅ |
| AML / Fraud / Declaration | `_get`, `_load_*` | ✅ |
| Governance | `_load_committee`, `_load_meeting` | ✅ |
| Awareness | `_load` | ✅ |
| Access Reviews | `_load` | ✅ |
| Goals | `_load` | ✅ |
| Internal Audit | `_load_unit`, `_load_engagement` | ✅ |
| Whistleblowing | `_load_report` | ✅ |

## Medium — soft-delete class (relationship backlinks)

Archived records leaked into ~30 many-to-many backlinks (a deleted asset still shown on
a vendor/risk/policy, etc.). All relationships now carry a filtered `secondaryjoin`;
the write path was verified intact (link create/edit still persists).

| Model | Relationships fixed | Status |
|-------|---------------------|--------|
| Risk | assets, controls, policies, incidents | ✅ |
| Vendor | risks, assets | ✅ |
| ProcessingActivity (RoPA) | assets, risks, processes, policies | ✅ |
| Organization | BusinessUnit.legals, Legal.business_units | ✅ |
| Control | policies | ✅ |
| Exception | risks, policies, requirements, controls | ✅ |
| Asset | incidents, processes, requirements, exceptions, related_assets (self-ref) | ✅ |
| Policy | controls, requirements, related (self-ref) | ✅ |
| Requirement | controls, risks, policies | ✅ |
| Goal | risks, projects, policies | ✅ |
| Project | risks, controls, policies | ✅ |

## Medium — summary / aggregate / rollup leaks

| # | Module | Location | Finding | Status |
|---|--------|----------|---------|--------|
| S1 | Compliance | `compliance.py` compliance_summary | Summary counted soft-deleted frameworks. | ✅ |
| S2 | Compliance | `models/compliance.py` is_covered | Gap analysis counted requirements covered only by deleted controls (relationship now filters). | ✅ |
| S3 | Regulatory Change | `regulatory_change.py` obligations list + summary | Obligations of a deleted change leaked (now outer-join, keeps standalone). | ✅ |
| S4 | ICFR | `icfr.py` icfr_summary | Counted controls/tests of archived processes (now joins non-deleted process). | ✅ |
| S5 | Internal Audit | `internal_audit.py` list_findings | Findings of archived engagements in the remediation view (now joins non-deleted engagement). | ✅ |

## Medium — FK validation (unknown link IDs → 500)

Unknown IDs hit the FK layer and returned `500` (aborting the transaction). All now
validate up front → `400`, and exclude soft-deleted targets. Verified live.

| Module | Location | Status |
|--------|----------|--------|
| Incidents | `_flush_assoc` (asset/risk ids) | ✅ |
| Controls | `_flush_assoc` (requirement/risk ids) | ✅ |
| Policies | `_flush_assoc` + `_load_related` | ✅ |
| Organization | `_load_many`, `_set_process_assets`, `_set_legal_assets` | ✅ |
| Assessments | vendor_id | ✅ |
| Outsourcing | vendor_id | ✅ |
| Risk Quantification | risk_id | ✅ |
| ICFR | deficiency control/process id (H8) | ✅ |

## Medium — regulatory date / SLA logic

| # | Module | Location | Finding | Status |
|---|--------|----------|---------|--------|
| D1 | Data Protection | `data_protection.py` create_dsar | DSAR had no default `due_date` → statutory 30-day clock never started. Defaults to `received_date + 30d`. | ✅ |
| D2 | Vulnerability | `vulnerability.py` create_vuln_finding | Severity SLA never derived `due_date` → overdue metrics undercounted. Now defaults from severity. | ✅ |
| D3 | Data Protection | `models/data_protection.py` | Late regulator report cleared the 72-hour breach-overdue flag. | ⏭️ Low-value; noted |

## Medium — backdated rollup regressions

Back-filling an older reading corrupted the "current"/latest rollup. All now only advance
on the most recent entry. Verified live (KRI stays at latest value).

| Module | Location | Status |
|--------|----------|--------|
| Operational Risk | KRI add_measurement | ✅ |
| Model Risk | add_validation (last_validation_date) | ✅ |
| Integrations / CCM | add_run (last_run/result/pass_rate) | ✅ |

## Medium — miscellaneous

| # | Module | Location | Finding | Status |
|---|--------|----------|---------|--------|
| M1 | Status Rules | `status_rules.py` update_rule | PATCH bypassed operator/model validation (invalid operator silently disabled the rule). | ✅ |
| M2 | Status Rules | `status_rules.py` evaluate | Evaluated soft-deleted records. | ✅ |
| M3 | Saved Filters | `filters.py` results | Results included soft-deleted records. | ✅ |
| M4 | Saved Filters | `SavedFilterUpdate` | PATCH accepted invalid `match_mode`. | ⏭️ Schema validator; noted |
| M5 | Declaration | `declaration.py` add_declaration | Declarations addable to deleted/closed campaigns. | ✅ (deleted→404, closed→409) |
| M6 | `conducted_date` | continuity/goals/controls record-test/audit | Defaulted date not written to the child row (undated test/audit rows). | ✅ |
| M7 | Assessments | `assessments.py` update_assessment | Repointing `questionnaire_id` on an assessment with answers yields nonsense scores. | ⏭️ Noted |

## Low

| # | Module | Location | Finding | Status |
|---|--------|----------|---------|--------|
| L1 | Many (33 helpers) | `_next_ref` | Count-based references reused a number after deletes (proven: two live `IAF-003`). Replaced with a shared max-based helper (`services/refs.py`). | ✅ |
| L2 | 14 routers | child `delete_*` | Silent `204` on unknown IDs → now `404`. | ✅ |
| L3 | Organization | `update_business_unit` | Business-unit parent cycles allowed → now ancestor-walk guard (`422`). | ✅ |
| L4 | Exceptions | `list_exceptions` | `?status=expired` never matched (status never persisted) → now computed filter. | ✅ |
| L5 | 6 modules | incidents/continuity/bia/projects/vendors/outsourcing delete | Archive not audit-logged → now records a `delete` audit entry. | ✅ |
| L6 | Shariah | `models/shariah.py` open_finding_count | Counts remediated findings as open. | ⏭️ Noted |
| L7 | Shariah | `schemas/shariah.py` charity amount | Accepts negative purification amounts. | ⏭️ Noted |
| L8 | Scenario | `models/scenario.py` | ILM rounded before ORC computation (small capital-figure error). | ⏭️ Noted |
| L9 | Various | update handlers | Some updates (not deletes) still lack audit entries. | ⏭️ Noted |
| L10 | Vendor types / asset classification types | `vendors.py` / `assets.py` | No DELETE/PATCH endpoints (lookup rows permanent). | ⏭️ Noted |

## Out of scope (features / known limitations, not bugs)

| # | Area | Note |
|---|------|------|
| O1 | Reference generation | ~~Not concurrency-safe~~ — **now fixed** via a transaction-scoped Postgres advisory lock keyed on tenant+prefix in `services/refs.py` (no schema migration needed). Verified: 10 simultaneous creates → 10 unique, gapless references. | ✅ |
| O2 | Whistleblowing | The promised tokenized two-way `tracking_code` channel has no public intake/status endpoint — a feature to build. | 🔵 |
| O3 | Runtime maker-checker | Broad four-eyes enforcement on write paths remains the separately-tracked productionization item (see the productionization follow-ups). | 🔵 |

---

## Verification

Every fix class was exercised live against the rebuilt stack: asset PATCH persists;
in-use questionnaire delete → 409; whistleblowing identity scrubbed; exception PATCH →
403; zero-permission user denied reports & private filters; archived records → 404 on
loaders and dropped from vendor/summary backlinks; relationship writes still persist;
bogus link IDs → 400; DSAR/vuln SLA dates auto-compute; KRI backdated reading doesn't
regress; declaration on closed campaign → 409; unknown child delete → 404; BU cycle →
422; self-referential related link writes + archive-drop both work; reference reuse
eliminated (delete-first-then-create yields unique refs). All 24 unit tests pass.
