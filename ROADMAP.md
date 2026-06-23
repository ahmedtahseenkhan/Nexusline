# Aegis GRC — Clone Roadmap & Gap Analysis

Target: a modern clone of **eramba** (25 modules, ~419 tables — see [docs/eramba](docs/eramba)).
We re-implement eramba's *features and data model* on a **modern stack** (Python/FastAPI,
async SQLAlchemy 2.0, PostgreSQL + RLS multi-tenancy, Next.js) — **not** its PHP/CakePHP /
MySQL / integer-enum / CakePHP-ACL internals.

## Modeling decisions (eramba → Aegis)

| eramba pattern | Aegis equivalent |
|---|---|
| int `type`/`status` + lookup tables | Python `str` enums (typed, readable) |
| `deleted`/`deleted_date` soft-delete | hard delete now; add soft-delete mixin when needed |
| `workflow_owner_id` + `workflow_status` envelope | dedicated approval-workflow engine (later phase) |
| CakePHP ACL (ARO/ACO) + `authorization_*` matrix | RBAC: roles → `resource:action` permissions (done) |
| polymorphic `model` + `foreign_key` | per-relation M2M tables now; generic polymorphic helper for cross-cutting (attachments/comments/tags) later |
| denormalized rollup counters | computed on read in services |
| single-install (one org) | **multi-tenant** via Postgres Row-Level Security |

## Module status

| # | eramba module | Aegis status | Gap to close |
|--:|---|---|---|
| 01 | Asset Management | **Strong** | CIA classification (+ derived overall), owner/guardian + owning business unit, handling labels ✅; remaining: per-axis classification weights, review scheduling |
| 02 | Data Assets & Privacy (RoPA/GDPR) | **Done** | RoPA (Article 30): purpose, lawful basis, subjects, retention, controller/processor/DPO, cross-border transfers + DPIA with auto gap-flags, asset/risk links ✅ |
| 03 | Business Organization (Units/Processes/Legal) | **Building now** | business units (hierarchy), processes (RTO/RPO), legal register (risk magnifier) |
| 04 | Risk Management | **Strong** | threats/vulns catalogs + linking ✅; remaining: classification types/axes, appetite color bands, over-time graphs |
| 05 | Third-Party Risk & Vendor Assessments | **Strong** | vendor registry + questionnaire builder + weighted-scored assessments + findings ✅; remaining: public vendor portal (hash link), recurrence |
| 06 | Internal Controls | **Strong** | audit + maintenance scheduling engine ✅ (recurring pass/fail tests, reschedule, due tracking); remaining: improvements → projects, service contracts |
| 07 | Policy Management | **Strong** | document types lookup, custom roles, LDAP groups, version log, portal |
| 08 | Compliance Management | **Strong** | regulator→package→items import, efficacy, online audits w/ questionnaires & feedback |
| 09 | Business Continuity | **Done** | continuity plans + 5W playbook tasks + recurring pass/fail test calendar, MTD/criticality, BU/process links ✅ (separate BIA-scoring + improvements deferred) |
| 10 | Security Incidents | **Done** | incident register + response-stage lifecycle (NIST phases, advance/complete) ✅ |
| 11 | Exceptions | **Done** | unified exception (risk/policy/compliance) w/ approval workflow + expiry |
| 12 | Audit & Account Reviews | **Done** | access certification campaigns + keep/revoke per account + completion gate + reschedule ✅ (LDAP/AWS/file auto-pull feeds deferred — accounts added manually) |
| 13 | Project Management | **Done** | projects + tasks (% complete) + expenses, computed progress/spend/over-budget, links to risks/controls/policies |
| 14 | Awareness Programs | **Done** | recurring programs + quiz builder + auto-scored completion + per-participant compliance ✅ (public portal/video + reminders deferred) |
| 15 | Strategy & Goals | **Done** | goals + recurring pass/fail audit cycle, links to risks/projects/policies (program issues/scopes deferred) |
| 16 | Users, Roles & Access | **Strong** | groups/portals, per-user overrides, custom (ownership) roles |
| 17 | Authentication & Directory | **Done** (core) | per-org JWT login ✅ + OIDC/OAuth2 SSO ✅ (per-tenant IdP config, authorize→code→token→userinfo, JIT provisioning w/ default role + domain allow-list, CSRF state, secret-masked); remaining: SAML XML binding, LDAP/AD directory sync |
| 18 | Custom Fields & Customization | **Done** (core) | per-model field defs (text/textarea/number/date/select/checkbox) + EAV value store ✅, admin manager + auto-rendered panel on records; remaining: per-field validators, tabs/sections, layout ordering |
| 19 | Dashboards & Reports | **Done** (core) | 19-metric registry across 8 modules + configurable widget builder (number/bar/donut) + per-tenant computed dashboard ✅; remaining: KPI thresholds/history/trends, scheduled/exported reports |
| 20 | Filters | **Done** (core) | named saved filters (personal/shared) over any model, multi-condition AND/OR via the field/operator engine, run-on-demand results ✅; remaining: schedulable filters + grid-embedded quick filters |
| 21 | Notifications | **Done** (in-app) | cross-module alert scanner (overdue/breach/expiry/gap) → in-app feed + bell badge + per-user unread + auto-resolve ✅; remaining: email/webhook channels, configurable rules, chasing |
| 22 | Workflows/Triggers/Dynamic Status | **Done** | approval workflows ✅ + webhooks/triggers ✅ (audit-pipeline fan-out, HMAC-signed, delivery log) + dynamic-status rule engine ✅ (field-introspected conditions number/date/enum → colored labels, single+bulk evaluate, shown on risk register) |
| 23 | System Administration | **Partial** (Docker) | backups, cron+queue/workers, imports, bulk actions, diagnostics |
| 24 | Logs & Audit Trail | **Partial** (activity log) | structured version audit + field deltas + restore, request correlation |
| 25 | Shared / Cross-cutting | **Done** | polymorphic comments + tags + attachments ✅ + review/attestation engine ✅ (periodic sign-off on any record, history, status never/current/overdue, feeds + auto-resolves notifications); remaining: edit locks (minor) |

## Phased build plan

**Phase A — foundational registers (small, high-leverage, referenced everywhere)**
1. ~~Business Organization (units, processes, legal)~~ ✅ done
2. ~~Exceptions (risk/policy/compliance, expiry + approval)~~ ✅ done
3. ~~Project Management (projects, tasks, budget)~~ ✅ done
4. ~~Strategy & Goals (goals + recurring goal audits)~~ ✅ done — **✅ Phase A complete**

**Phase B — deepen existing modules to eramba parity**
5. Risk: ~~threats/vulns catalogs~~ ✅ done · remaining: classification axes + appetite color bands
6. ~~Internal Controls: audit + maintenance scheduling engine~~ ✅ done
7. ~~Third-Party Risk: questionnaire assessments + weighted scoring + findings~~ ✅ done (public portal + recurrence deferred)
8. ~~Asset Management: CIA classification + ownership + handling labels~~ ✅ done — **✅ Phase B complete**

**Phase C — remaining domain modules** ✅ **COMPLETE**
9. ~~Business Continuity (BCP + 5W playbook + test calendar)~~ ✅ done
10. ~~Data Privacy / RoPA (GDPR analysis)~~ ✅ done
11. ~~Security Incidents: lifecycle stages~~ ✅ done
12. ~~Audit & Account Reviews (access certification)~~ ✅ done
13. ~~Awareness Programs (quiz + compliance)~~ ✅ done

**Phase D — cross-cutting platform engines**
14. ~~Polymorphic attachments/comments/tags~~ ✅ · ~~review/attestation engine~~ ✅ — **module 25 COMPLETE** (edit locks minor)
15. ~~Notifications engine (in-app cross-module alert feed)~~ ✅ done (email/webhook channels deferred) ← *started Phase D*
16. ~~Approval workflows~~ ✅ · ~~webhooks/triggers~~ ✅ · ~~dynamic-status rule engine~~ ✅ — **module 22 COMPLETE**
17. ~~Saved/advanced filters~~ ✅ done · remaining: schedulable + grid quick-filters (module 20)
18. ~~Custom fields / forms~~ ✅ done · remaining: tabs/sections, validators (module 18)
19. ~~KPI + report builder~~ ✅ done · remaining: thresholds/history, scheduled exports (module 19)
20. ~~Auth: OIDC/OAuth2 SSO + JIT provisioning~~ ✅ done · remaining: SAML XML, LDAP sync (module 17)
21. SysAdmin: background workers (Celery), backups, bulk actions, imports (module 23)
22. Structured version-audit + restore (module 24)

> This is a multi-phase program. Each module ships fully working (backend + UI + verified
> tenant isolation + RBAC) before moving on, following the established module template.
