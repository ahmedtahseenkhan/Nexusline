# NexusLine vs eramba — Feature Parity & Modern GRC Gap Analysis

_Audit date: July 2026. Method: full read of `docs/eramba/` spec (25 modules, ~500 discrete capabilities) cross-referenced against the FastAPI backend (35 router modules, ~70 tables) and Next.js frontend (36 routes)._

---

## 0. Implementation log — closed in this iteration (July 2026)

The following P0/P1 items from the gap list below have now been **built and verified**
(backend imports + OpenAPI build clean; frontend `tsc --noEmit` clean). Not yet
integration-tested against a live Postgres — that's the next verification step.

| Gap closed | What shipped |
|---|---|
| **CSV import/export on every module** | Registry grew 16→20 resources (added requirements w/ framework adapter, evidence, awareness-programs, access-reviews); Import/Export control added to all 20 module pages. |
| **Binary file storage** | New `stored_files` table + local object-storage service (`services/storage.py`, sha256, size cap, path-traversal guard); upload/download/delete endpoints under `/collab`; file-upload UI in `CollabPanel`; RLS-scoped per tenant. |
| **Email (SMTP) + scheduler** | `services/email.py` (stdlib SMTP, dev-safe log fallback, HTML digests); `services/scheduler.py` (in-process asyncio sweep per tenant, wired into app lifespan); `refresh()` now returns new alerts for digesting; `POST /notifications/test-email`. |
| **Alembic baseline** | `alembic/versions/0001_baseline.py` materializes the full schema + applies RLS; RLS DDL refactored into reusable `rls_ddl_statements()`. |
| **Settings UI** | Replaced the app's only placeholder page with a real Settings page (org profile, appetite/tolerance, SMTP verify button, admin hub). |
| **Risk 5×5 heatmap** | `GET /risk-matrix` (inherent + residual grid counts) + `RiskHeatmap` component on the dashboard. |
| **Global search** | `GET /search` across 15 registers (permission- and RLS-scoped) + debounced Topbar search box with results dropdown. |
| **Framework content library** | Expanded 1→**9 templates / 999 requirements**: ISO 42001, ISO 27001:2022 (clauses + all 93 Annex A), SOC 2 TSC, NIST CSF 2.0, PCI DSS 4.0, GDPR, HIPAA, CIS v8, NIST 800-53 R5 (all 20 families). Loadable into any tenant via the compliance API. |

**Still open** (tracked below, not yet built): vendor public portal, online compliance-audit
workflow, account-review feeds+diffing, awareness email delivery, multi-step approver/validator
workflows, corrective-action chains; SAML/LDAP/2FA/API-keys/user-groups/record-level-permissions;
report builder + PDF export, time-series trend graphs, embedded grid filters; and the modern-GRC
differentiators (CCM/connectors, automated evidence, trust center, AI assist, auditor workspace).

**Verdict: ~85% functional parity with eramba at module level. All 25 eramba modules exist end-to-end (models + API + full-depth UI). The remaining 15% is concentrated in the platform/operational layer — email+scheduler, file storage, external portals, directory services — plus content (framework library) and a handful of per-module sub-features.**

---

## 1. Module-by-module parity scorecard

| # | eramba module | Status | Notes |
|---|---------------|--------|-------|
| 01 | Asset Management | ✅ Full | Assets, media types, labels, classification types/values (CIA), 3-role ownership (owner/guardian/user → BU), review cycles, 7 link types. Gap: seeded media-type→threat/vulnerability mapping catalogs. |
| 02 | Data Assets / Privacy | ✅ Full (different model) | We use RoPA-record model (GDPR Art. 30: lawful basis, DSR narratives, transfers, DPIA) — more modern than eramba's data-flow-status model. Gap: data-lifecycle flow statuses (Created/Stored/Transit/…) per asset. |
| 03 | Business Organization | ✅ Full | BU hierarchy, processes with RTO/RPO/RPD, legal register with risk_magnifier, countries. |
| 04 | Risk Management | ✅ Full+ | 5×5 qualitative + FAIR quantitative (ALE) — **exceeds eramba**. Appetite/tolerance with breach alerts, acceptance workflow, treatment, reviews, threat/vuln catalogs, enterprise aggregation. Gaps: configurable calculation methods per register; time-series "overtime" trend snapshots; risk matrix heatmap UI. |
| 05 | Third-Party Risk | 🟡 Mostly full | Vendors, types, contracts, criticality/risk rating, questionnaire builder with weighted scoring, assessment campaigns, findings. **Gaps: no public (unauthenticated) vendor portal endpoint — `access_hash` exists but external vendors cannot submit; no conditional question triggers (show/hide); no chaptered questionnaires; no recurrence/auto-close scheduling.** Third-party risks handled via unified risk register (design choice, acceptable). |
| 06 | Internal Controls | ✅ Full | Design/production types, effectiveness, opex/capex/FTE, recurring audit + maintenance cycles with pass/fail. Gaps: corrective-action chain (failed audit → improvement → project/incident); polymorphic "issues" on controls. |
| 07 | Policy Management | ✅ Full | Doc types, versioning, review cycles, RichText or URL content, **acknowledgments (exceeds base eramba)**. Gap: standalone policy portal with directory-group targeted publication. |
| 08 | Compliance Management | 🟡 Mostly full | Frameworks, requirements, treatment strategy, efficacy %, control mapping (map-once-comply-many), **crosswalks (exceeds eramba)**, findings, gap analysis, roll-up summary, template loader. **Gaps: framework content library has only ISO/IEC 42001 (eramba ships dozens: ISO 27001, PCI DSS, NIST CSF, SOC 2, GDPR, CIS…); no online compliance-audit (auditee questionnaire + email invitation) workflow.** |
| 09 | Business Continuity | ✅ Full | BIA, invocation criteria, MTD/RTO/RPO, 5W recovery playbook tasks, test/exercise cycles. Gap: eramba scores BIAs as a third risk register with appetite — ours doesn't risk-score continuity plans. |
| 10 | Security Incidents | ✅ Full | Severity/status, NIST IR stage lifecycle with progress, root cause, lessons learned, cost, links. |
| 11 | Exceptions | ✅ Full | Unified register (risk/policy/compliance types) vs eramba's 3 tables. Approval workflow, expiry flagging, compensating controls. |
| 12 | Audits / Account Reviews | 🟡 Mostly full | Campaigns, frequency, line-item keep/revoke certification, completion %, complete-campaign. **Gaps: automated feeds (CSV/LDAP/AWS imports), pull-to-pull diff comparison (added/removed/role-change detection), findings from reviews.** Ours is manual entry. |
| 13 | Projects | ✅ Full | Status, budget, tasks with % completion, expenses, over-budget calc, links to risks/controls/policies. |
| 14 | Awareness Programs | 🟡 Mostly full | Programs, quiz builder, per-participant records, auto-scored take-quiz flow, completion/compliance %. **Gaps: email invitations/reminders (chasing), video training content, directory-driven audiences, recurrence windows, public training portal.** |
| 15 | Strategy & Goals | ✅ Full | Goals, recurring audit cycles pass/fail, links. Gap: program scopes & program issues (maturity gap items). |
| 16 | Users / Roles / Access | 🟡 Partial | RBAC with 56 `resource:action` permissions, 6 seeded roles, system-role protection, effective-permissions preview. **Gaps: user groups; record-level permissions / custom roles (eramba's per-item authorization engine); team roles & governance scopes (CISO/board); brute-force login bans.** |
| 17 | Authentication / Directory | 🟡 Partial | Local (bcrypt+JWT, per-tenant) + OIDC SSO with JIT provisioning and domain allowlist. **Gaps: SAML, LDAP connectors + scheduled sync, 2FA/TOTP, API keys / OAuth2 token server.** |
| 18 | Customization | 🟡 Mostly full | Custom fields (6 types, 12 models; eramba covers 46), saved-filter query builder, dynamic status rules. **Gaps: custom forms/layout builder, custom labels (field relabeling), custom validators, translations/i18n.** |
| 19 | Dashboards / Reports | 🟡 Partial | Metric catalog (~22 metrics), composable widget dashboard (tiles/bar/donut), posture dashboard, gap tables. **Gaps: report template builder (block-based), PDF/Word export, KPI thresholds + history logs, calendar view, per-user dashboard sharing.** |
| 20 | Filters | 🟡 Mostly full | Field/operator/value builder, AND/OR, shared/personal, run-to-results. **Gaps: filters embedded in module list views (currently standalone page), pinned/default per user, scheduled filter runs driving notifications.** |
| 21 | Notifications | 🟠 Partial | In-app engine with cross-module scan (overdue/breach/gap), dedupe, auto-resolve, unseen badge. **Gaps: NO email delivery (no SMTP anywhere), no scheduled sending (scan runs on request, not cron), no chasing/reminder sequences, no recipient configuration, no report attachments.** |
| 22 | Workflows / Triggers | 🟡 Partial | Approval inbox (submit/approve/reject/cancel, deep links), `workflow_status` lifecycle on all records, dynamic status rules, HMAC webhooks with delivery logs + test. **Gaps: multi-step approver+validator workflows with scopes/logs/acknowledgements; user-defined code triggers; status triggers.** |
| 23 | System Administration | 🟠 Partial | CSV import/export (17 resources, validated, per-row errors), settings via env vars. **Gaps: NO cron/scheduler, no job queue, backups UI, bulk actions, health checks, mail queue, settings UI (frontend page is the only placeholder). 0 Alembic migrations — schema is `create_all` at boot (operational risk for upgrades).** |
| 24 | Logs / Audit Trail | ✅ Full | Append-only activity log (JSONB diffs), record versioning with point-in-time restore (15 models), audit→version→webhook fan-out pipeline. |
| 25 | Shared / Cross-cutting | 🟡 Mostly full | Polymorphic comments, tags (colored, suggestions), attestations (periodic review sign-off), custom fields — all mounted on 10 detail surfaces. **Gaps: attachments are URL-only (no binary file upload/blob storage); polymorphic "issues"; concurrent-edit locks.** |

**Where NexusLine exceeds eramba:** true multi-tenancy (Postgres RLS, forced, fail-closed), FAIR quantitative risk, framework crosswalks, policy acknowledgments, unified exception register, record versioning + restore, HMAC-signed webhooks with delivery logs, OIDC/JIT SSO, modern REST/OpenAPI surface.

---

## 2. Critical gaps, prioritized

### P0 — blocks real-world operation
1. **Email (SMTP) + scheduler (cron/queue).** Eramba's operating model is email-driven: review reminders, expirations, chasing, workflow notices, report delivery. We have neither an email backend nor any scheduled execution — notifications only compute when someone opens the app. Needs: SMTP/provider integration, background scheduler (APScheduler/Celery/arq), notification recipient config, chase sequences.
2. **Binary file storage.** Attachments and evidence are URL references only. Auditors expect uploaded evidence files (screenshots, PDFs, exports) with versioning. Needs: object storage (S3/local), upload endpoints, virus-scan hook, size limits.
3. **Framework content library.** Only ISO/IEC 42001 template ships. Minimum viable catalog: ISO 27001:2022, SOC 2 TSC, NIST CSF 2.0, PCI DSS 4.0, GDPR, HIPAA, CIS Controls v8, NIST 800-53.
4. **Alembic migrations.** `create_all` at boot cannot evolve a production schema. Generate the baseline migration now, migrate from there.

### P1 — completes eramba parity
5. Public vendor-assessment portal (unauthenticated submit via `access_hash`), conditional question triggers, assessment recurrence.
6. Online compliance-audit workflow (auditee invitations, per-requirement feedback, email templates).
7. Account-review feeds: CSV/LDAP/cloud imports + snapshot diffing (added/removed/role-change).
8. Awareness delivery: email invitations + reminder chasing, video content, public training portal.
9. Multi-step approval workflows (approvers + validators, per-model config, logs).
10. Corrective-action chain: failed audit/test → improvement → project/incident links.
11. SAML + LDAP (connectors, scheduled sync, group-based provisioning), 2FA/TOTP, API keys.
12. Report builder with PDF export (board/audit packs).
13. Risk matrix (5×5 heatmap) visualisation; time-series trend snapshots (risk/compliance/audit overtime graphs).
14. Filters embedded in module grids (pinned/default per user); scheduled filter → notification pipeline.
15. Settings UI (org profile, mail config, risk matrix labels, API keys) — currently the app's only placeholder page.
16. Record-level permissions / custom roles; user groups.
17. Global search.

### P2 — polish
18. Custom forms/layout builder, field relabeling, custom validators, i18n.
19. Concurrent-edit locks, polymorphic issues, media-type threat/vuln catalogs, program scopes/issues, governance team roles.
20. Backups UI, health checks, bulk actions.

---

## 3. Modern GRC benchmark (Vanta / Drata / OneTrust / AuditBoard class)

Capabilities the modern market expects that **neither eramba nor NexusLine** has today:

| Capability | Status | Notes |
|---|---|---|
| **Continuous control monitoring (CCM)** — automated tests against cloud/SaaS APIs (AWS, Azure, GCP, GitHub, Okta, Google Workspace, MDM…) with pass/fail drift alerts | ❌ | The single biggest differentiator of Vanta/Drata-class tools. Our evidence model ("collect once, satisfy many") is the right substrate; needs an integration/connector framework + test runner. |
| **Automated evidence collection** via integrations, on schedule, mapped to controls | ❌ | Follows from CCM framework. |
| **Trust center** — public security posture page with NDA-gated document sharing | ❌ | Standard in 2025+ deals. |
| **AI assistance** — security-questionnaire auto-answering from answer library, policy drafting, control-mapping suggestions, risk insights | ❌ | Table stakes in current market; natural fit as an API layer over existing data. |
| **External auditor workspace** — scoped auditor access, evidence requests (PBC lists), sampling | ❌ | We have Auditor role but no external scoping/portal. |
| **SCIM provisioning** + HR-system sync (personnel compliance: onboarding/offboarding, training, background checks) | ❌ | We have OIDC JIT; SCIM + HRIS feeds missing. |
| **Ticketing/chat integrations** — Jira/Slack/Teams for remediation and alerts | ❌ | HMAC webhooks are a primitive to build on. |
| **Vulnerability/finding ingestion** (scanner → risk/finding pipeline) | ❌ | Optional depending on target market. |
| Multi-framework mapping with shared evidence | ✅ Have | Crosswalks + evidence-satisfies-many already built. |
| Risk quantification (FAIR) | ✅ Have | Exceeds most competitors at this tier. |
| Multi-tenant / MSP-ready architecture | ✅ Have | Postgres RLS, fail-closed. |
| Modern API-first surface (REST + OpenAPI + webhooks) | ✅ Have | API keys/OAuth2 client credentials still needed for machine access. |

---

## 4. Suggested build order

1. **P0 platform**: SMTP + scheduler + notification delivery → file upload/storage → Alembic baseline → framework library expansion (content work, high value/low risk).
2. **External surfaces**: vendor portal → compliance audit workflow → awareness portal + email chasing (all share "public portal + email" infrastructure built in step 1).
3. **Parity tail**: account-review feeds/diffing, approval workflows, corrective-action chains, SAML/LDAP/2FA/API keys, report builder + PDF, risk heatmap + trends, embedded filters, settings UI.
4. **Modern differentiators**: integration/connector framework → CCM tests → trust center → AI questionnaire/policy assist → auditor workspace.
