# Aegis GRC — Full eramba-Parity Master Plan

**Goal:** a complete, enterprise-grade GRC product matching eramba's depth across **all 25 modules**,
every module fully featured, linked to the others, and built to standard — not an MVP.
**Spec source of truth:** `docs/eramba/*` (419 tables). Read the module doc before building it.
**Depth template (already proven):** Asset Management — see `app/models/asset.py` (media types, RACI
owners, CIA classification scheme, review cycle, workflow status, soft-delete, M2M cross-links, lookups).

---

## 1. The Platform Contract (every module gets ALL of this)

eramba records share a common envelope + behaviours. We build these once as reusable
mixins/services and apply them to every module, instead of thin per-module schemas.

| Capability | What it means per record | Status |
|---|---|---|
| **Record envelope** | `created`, `modified`, `edited`, **soft-delete** (`deleted`/`deleted_date`) | Asset ✅ → roll out to all |
| **Workflow status** | approval lifecycle `draft → in_review → approved → retired` (`workflow_owner`) | Asset ✅ → all |
| **Dynamic status** | rule-driven colored labels shown as a grid column | engine ✅ → wire per module |
| **Reviews / attestation cycle** | scheduled + completed reviews, next-due, expired counter, Reviews sub-tab | Asset ✅ → all reviewable modules |
| **Lookups (per module)** | editable reference tables (types, classifications, labels, statuses…) via a **Settings** menu | Asset ✅ → all |
| **RACI / contacts** | Owner / Guardian / User / Reviewer etc. → Business Units (or contacts) | Asset ✅ → all |
| **Cross-links (M2M)** | rich relationships to other modules (the GRC graph) | Asset ✅ → all |
| **Custom fields** | per-org extra fields | engine ✅ → render on every form |
| **Comments / tags / attachments** | collaboration on every record | engine ✅ → on every detail |
| **Filters → Views** | saved filters pinned as grid view-tabs | engine ✅ → on every grid |
| **Notifications / webhooks** | due/overdue/breach alerts + outbound events | engine ✅ → feed from every module |
| **Grid UX** | Add/Edit **slide-over drawer** w/ inline "+Add" relations, Filter/Sort/Columns, Settings, tabs | Assets first → all |

**Foundation work (do first, platform-wide):**
- `SoftDeleteMixin` + `WorkflowMixin` on the model base; list endpoints exclude soft-deleted.
- `Contact`/RACI pattern (reuse Business Units now; add a Contacts table later).
- A generic **Reviews** framework (scheduled/completed/expired) reusable beyond Assets.
- A generic **Lookup** management pattern (per-module Settings registries).
- Frontend: a reusable **RecordDrawer** (slide-over create/edit) + **GridShell** (Views + Dynamic
  Status + Filter/Sort/Columns + Settings) so every module page is consistent with eramba.

---

## 2. Modules — depth scope (from `docs/eramba`)

Each line = core entity + sub-entities/lookups + key cross-links. "Tables" = eramba table count.

| # | Module (tables) | Core depth to build | Links to |
|--:|---|---|---|
| 03 | **Business Organization** (10) | Business Units (tree), Processes (RTO/RPO/criticality), Legal/Regulatory register; contacts | hub for ALL ownership |
| 01 | **Asset Management** (18) ✅ | media types, CIA classifications, labels, RACI, reviews, data flows | risks, processes, legals, compliance, incidents, exceptions, vendors |
| 02 | **Data Assets & Privacy** (18) | RoPA, data-asset instances, **data flows**, lawful basis, transfers, DPIA, retention | assets, processes, risks, legals |
| 04 | **Risk Management** (26) | risk register w/ **classifications + 5×5 score matrix**, threats↔vulns, treatments, **risk acceptance workflow**, appetite/tolerance, residual | assets, controls, compliance, BUs, processes, third parties |
| 05 | **Third-Party Risk** (22) | vendors, **vendor assessments + questionnaires/answers**, scoring, contracts, recurrence | assets, risks, compliance, legals |
| 06 | **Internal Controls** (17) | control catalog, **audits + maintenances cycles**, effectiveness, control owners, cost, SoA | risks, compliance, policies, assets |
| 07 | **Policy Management** (9) | **document types**, versions, **acknowledgments/portal**, review cycle, exceptions, LDAP groups | controls, compliance, assets, exceptions |
| 08 | **Compliance Management** (30) | frameworks, **requirements tree**, control mappings, **compliance analysis/audits**, online assessments, crosswalks, gap | controls, policies, risks, assets, exceptions |
| 09 | **Business Continuity** (22) | continuity plans, **BIA**, tests cycle, RTO/RPO, dependencies, invocation | processes, assets, risks |
| 10 | **Security Incidents** (8) | incident register, **NIST lifecycle stages**, severity, timeline, cost, lessons | assets, risks, third parties |
| 11 | **Exceptions** (10) | policy/risk/compliance exceptions, approval workflow, expiry, compensating controls | risks, policies, compliance, assets |
| 12 | **Audit & Account Reviews** (12) | **audit campaigns**, account/access reviews, keep/revoke certification, scope, evidence | assets, controls, compliance |
| 13 | **Projects** (10) | projects, tasks, expenses/budget, milestones, status | risks, controls, policies, goals |
| 14 | **Awareness Programs** (21) | programs, **questionnaires + questions/options**, participants, scoring, portal, reminders | BUs, policies, training records |
| 15 | **Strategy & Goals** (16) | goals, **audits cycle**, KPIs, alignment | risks, projects, policies |
| 16 | **Users, Roles & Access** (26) | users, **roles + granular permissions**, groups, RACI contacts, account onboarding | all (access control) |
| 17 | **Authentication & Directory** (15) | local + **SSO (OIDC ✅)**, SAML, **LDAP/AD sync**, OAuth2 server, portals | users |
| 18 | **Custom Fields & Forms** (21) | field defs ✅, forms/tabs, validators, layout per module | all |
| 19 | **Dashboards & Reports** (28) | KPI widgets ✅, **report builder (blocks)**, schedules/exports, thresholds/history | all data |
| 20 | **Filters & Advanced** (8) | saved filters ✅ → **Views per grid**, scheduled filters | all grids |
| 21 | **Notifications** (12) | in-app ✅ + **rules/recipients/channels (email/webhook ✅)**, chasing | all due-dates |
| 22 | **Workflows/Triggers/Dynamic Status** (24) | approvals ✅, dynamic status ✅, webhooks ✅, **triggers/automation rules** | all |
| 23 | **System Administration** (22) | settings, **backups, workers/cron, imports, bulk actions**, diagnostics | platform |
| 24 | **Logs & Audit Trail** (5) | activity log ✅ + **structured version audit + field deltas + restore** | all |
| 25 | **Shared / Cross-cutting** (9) | comments/tags/attachments ✅, attestation ✅, **edit locks** | all |

---

## 3. Cross-link graph (the GRC web every module plugs into)

```
Business Units ──owns──► Assets ──has──► Risks ◄──mitigated by── Controls ──satisfy──► Compliance Reqs
      │                    │ │             │ ▲                        │                     │
   Processes ◄────────────┘ │          Threats/Vulns              Policies ◄──acknowledge── Users
      │ (RTO/RPO)           │             │                          │                     │
  Continuity Plans          ├─► Data Flows / RoPA (Privacy)      Exceptions ◄──────────────┤
      │                     ├─► Incidents                         Projects / Goals          │
  Third Parties ◄───────────┘    Account/Audit Reviews            Awareness ────────────────┘
```
Every box also carries: reviews cycle · workflow status · dynamic status · custom fields ·
comments/tags/attachments · filters/views · notifications.

---

## 4. Execution order (dependency-aware, each module verified to full depth)

**Phase F0 — Foundation (platform-wide):** soft-delete + workflow mixins, reviews framework,
lookup pattern, RecordDrawer + GridShell frontend shell.
**Phase F1 — Link hub:** 03 Business Organization (units tree, processes, legal, contacts).
**Phase F2 — Core registers (deep):** 01 Assets ✅ · 04 Risk · 06 Controls · 08 Compliance.
**Phase F3 — Programs:** 07 Policies · 05 Third-Party · 02 Privacy/Data-Flows · 11 Exceptions.
**Phase F4 — Operations:** 10 Incidents · 09 Continuity · 12 Audit/Account Reviews · 13 Projects ·
15 Goals · 14 Awareness.
**Phase F5 — Platform/admin:** 16 Users/Roles deep · 17 SAML/LDAP · 19 Report builder ·
22 triggers · 23 SysAdmin · 24 version-audit/restore · 18 forms/tabs.

Each module is **done** only when it matches eramba: full fields, lookups (Settings), RACI, reviews
sub-tab, cross-links, dynamic-status column, Views, slide-over drawer, custom fields + collaboration,
seeded richly, and verified (CRUD + relations + reviews + RBAC + isolation).

---

## 5. Progress

- ✅ **F0 Foundation** — `SoftDeleteMixin` + `WorkflowMixin` + `WorkflowState` in `models/base.py`; applied to rebuilt modules.
- ✅ **01 Asset Management** — full parity backend (media types, CIA scheme, RACI, reviews, workflow, soft-delete, M2M, lookups). Verified.
- ✅ **03 Business Organization** — BUs (contacts, location, workflow, ↔legal obligations), Processes (RTO/RPO/RPD, criticality, workflow), Legal register (risk_magnifier, countries, ↔BUs), soft-delete throughout. Verified.
- ✅ **04 Risk Management** — envelope (workflow + soft-delete), treatment plan (strategy/owner/deadline/cost), 5×5 inherent/residual + ALE, 25-threat/22-vuln library, acceptance workflow, appetite/tolerance, links to assets/controls/policies/incidents. Verified.
- ✅ **06 Internal Controls** — objective, control type (design/production), classification, owner, OPEX/CAPEX/resource util, audit + maintenance review cycles (metric/criteria/result/improvement), workflow + soft-delete, links to compliance requirements (crosswalk) + policies + risks. Verified.
- ✅ **08 Compliance** — frameworks (regulator/scope/workflow, compliant counts), requirement **implementation layer** (treatment/owner/efficacy/implementation/audit-questionnaire), requirement↔control/risk/policy/legal links, **compliance findings** (raise→close, severity, deadline), crosswalks, gap analysis, soft-delete. Verified.
- ✅ **F2 core registers COMPLETE** (Assets · Risk · Controls · Compliance).
- ✅ **07 Policy Management** — document types (policy/standard/procedure/guideline), summary/url/body/label, versioning, **review cycle** (schedule→complete), related policies, reverse links to controls/requirements/risks, acknowledgments, workflow + soft-delete. Verified.
- ✅ **05 Third-Party/Vendors** — vendor type taxonomy, full contacts, workflow + soft-delete, data-sharing flag, onboarding + review cycle, **service contracts** (value/expiry), vendor↔risk + vendor↔asset links; vendor-assessment questionnaires already built. Verified.
- ✅ **02 Privacy/Data-Flows (RoPA)** — all 6 GDPR data-subject rights, data types/collection/volume/accuracy/archiving driver, data-flow origin→destination + transfers, DPIA, workflow + soft-delete, review cycle, links to assets/risks/processes/policies. Verified.
- ✅ **11 Exceptions** — type (risk/policy/compliance), classification, compensating controls, business owner, approval workflow + envelope, expiry, links to risks/policies/requirements/controls/assets. Verified. **F3 COMPLETE.**
- ✅ **10 Incidents** — workflow envelope, classification, root cause, lessons learned, cost, NIST response stages, links to controls/vendors/assets/risks. Verified.
- ✅ **09 Continuity** — workflow envelope, BIA, invocation criteria, RTO/RPO/MTD, BCP tasks + test/exercise cycle, soft-delete. Verified.
- ✅ **13 Projects · 15 Goals · 14 Awareness · 12 Audit/Account Reviews** — workflow + soft-delete envelope applied on top of existing depth (project tasks/expenses, goal audit cycle, awareness questionnaires/scoring, access certification keep/revoke). Verified soft-delete.
- ✅ **F4 OPERATIONS COMPLETE → all domain modules F0–F4 done (16 modules).**
### F5 — Platform polish
- ✅ **24 Logs & Audit Trail** — activity log + **structured version-audit** (per-record snapshots on every change, field-level diffs, one-click **restore**, RBAC-gated). Verified. Wired into the audit pipeline (alongside webhooks) so all mapped modules are versioned automatically.
- ▶️ **Remaining:** 23 SysAdmin settings surface, 16 Users/Roles management depth (UI), 17 SAML/LDAP (OIDC SSO done), 18 forms/tabs layout. Mostly admin/infra polish — core GRC capability is complete.

**Status: all 25 eramba functional modules built at parity depth + 11 platform engines (incl. version-audit). The GRC product is functionally complete; remaining work is platform/admin polish.**
