# NexusLine GRC — Complete User & Administrator Guide

*How every module works, how to use it, and how the modules connect to each other. Written from a direct code audit on 2026-07-05 — every field, status, and button named below actually exists in the app today. Sections marked ⚠ call out things that look automatic but currently require a manual step, so you don't design a process around a connection that isn't wired up yet.*

---

## Table of contents

1. [What NexusLine is](#1-what-nexusline-is)
2. [Getting started](#2-getting-started)
3. [Concepts that apply to every module](#3-concepts-that-apply-to-every-module)
4. [How the sidebar is organized](#4-how-the-sidebar-is-organized)
5. [Overview](#5-overview) — Dashboard, Reports & KPIs, Strategy & Goals, AI Assist
6. [Risk](#6-risk) — 12 modules
7. [Compliance](#7-compliance) — 12 modules
8. [Governance](#8-governance) — 7 modules
9. [Organization](#9-organization) — 4 modules
10. [Operations](#10-operations) — 10 modules
11. [System (administration)](#11-system-administration) — 8 modules
12. [End-to-end workflows](#12-end-to-end-workflows) — worked examples across modules
13. [Roles & permissions reference](#13-roles--permissions-reference)
14. [Known gaps — things that look automatic but aren't yet](#14-known-gaps--things-that-look-automatic-but-arent-yet)

---

## 1. What NexusLine is

NexusLine is a one-stop Governance, Risk & Compliance (GRC) platform, purpose-built for the depth Pakistani banks need (SBP ETGRM, AML/CFT, Basel operational risk, Shariah governance, PDPA) while covering the full breadth of a mature GRC suite — risk, compliance, policy, audit, continuity, third-party, and more. It ships either as multi-tenant SaaS or as an on-premise install for banks that require data sovereignty.

Every bank/organization that uses the platform is a fully isolated **tenant** — see [§3.3](#33-multi-tenancy--data-isolation).

---

## 2. Getting started

### 2.1 Signing in

The login screen asks for three things: **Organization** (your bank's short slug, e.g. `acme`), **Email**, and **Password**. You need to know your organization's slug — bookmark the login URL once you have it.

- If your account has **MFA** enabled, you'll be asked for a 6-digit authenticator-app code after your password.
- After **5 failed attempts** your account locks for 15 minutes (both numbers are admin-configurable).
- Sessions expire after 60 minutes of the token's lifetime by default — you'll be asked to sign in again after that.
- If your bank has **SSO** configured, a "Sign in with SSO" button redirects to your identity provider (Azure AD, Okta, etc.) instead of a local password.
- If your bank has **LDAP/Active Directory** configured, your normal directory password is checked instead of (or alongside) a local one.
- Directory- and SSO-managed accounts cannot change their password inside NexusLine — do that at the source (AD/IdP).

### 2.2 How you get an account

**There is no self-signup.** A brand-new user cannot register themselves. An account is created one of two ways:

1. An **administrator manually creates you** under Users & Roles ([§9.4](#94-users--roles-organization)), typing your email, name, an initial password, and your role(s).
2. If your bank has LDAP or SSO with **just-in-time provisioning** enabled, your account is created automatically the first time you successfully sign in through the directory/IdP.

New bank (tenant) onboarding itself is done by whoever operates the platform backend — there is currently no in-app "create your organization" page.

### 2.3 Bootstrap checklist for a brand-new bank deployment

If you're standing up NexusLine for a new organization, this is the order that avoids rework:

1. **Org + first Admin user** created by the platform operator.
2. Admin signs in, sets up **SSO/LDAP** if the bank uses one (`/sso-settings`, LDAP card on `/settings`) — otherwise skip and use local accounts.
3. Create **Users & Roles** (`/organization`) for the compliance/risk/IT team, or import them via LDAP JIT.
4. Set up **Business Units** (`/business-units`) — your branch/division hierarchy — and **Processes** (`/processes`).
5. Install the frameworks you need from the **Framework Library** (`/content-library`) — ISO 27001, NIST CSF, SBP ETGRM, PCI DSS, Basel, Shariah — so Compliance has something to assess against.
6. Build the **Control Catalog** (`/controls`) — either from scratch or by mapping to the requirements the installed frameworks created.
7. Populate **IT Assets** and **Information Assets** (`/it-assets`, `/information-assets`) and link them so criticality inherits correctly.
8. Start the **Risk Register** (`/risks`) — set your organization's risk appetite/tolerance first, then add risks and link them to assets/controls/threats.
9. Onboard **Vendors** (`/vendors`), layering **Outsourcing** records for SBP-material/cloud arrangements.
10. Turn on the modules relevant to your bank's obligations — AML, Fraud, ICFR, BIA, Shariah, Whistleblowing, Declarations, etc.

---

## 3. Concepts that apply to every module

Learn these once — they show up almost everywhere and this guide won't repeat them per module.

### 3.1 The generic workflow status

Nearly every record — on top of its own business status (e.g. a Risk's `draft → assessed → treatment_planned...`) — also carries a second, generic **Workflow** field:

```
draft → in_review → approved → retired
```

This is a lightweight "is this record itself finalized" tracker, independent of the record's operational status. A `Workflow Owner` field usually goes with it.

### 3.2 RecordPanels — the shared toolkit on every record

Open almost any record (risks, controls, vendors, incidents, policies, BIA, continuity, ICFR, issues, model risk, projects, Shariah, vulnerabilities, whistleblowing, DoA, assets, and more — roughly 30 modules) and you'll find the same three panels bundled in:

- **Custom Fields** — any extra fields your admin defined for that record type ([§11.2](#112-custom-fields)) appear automatically here.
- **Review & Attestation** — a periodic sign-off tracker: set a frequency, click "Attest now," and see the history of who confirmed the record and when it's next due. This is where most "management sign-off" and "recovery-strategy sign-off" requirements are actually satisfied, even on modules that don't have a dedicated approval button.
- **Collaboration** — comments, tags, and file attachments/links, usable on any record that has this panel. This — not the dedicated Evidence module — is the general-purpose "attach a document to this record" mechanism.

### 3.3 Multi-tenancy & data isolation

Each bank's data is walled off from every other bank on the platform at the database level (PostgreSQL row-level security, `FORCE RLS`), not just in the application code — even a buggy query cannot leak across tenants, and if the tenant tag is ever missing the system shows zero rows rather than everything. Your users, roles, SSO/LDAP config, custom fields, filters, and dashboards are all private to your organization.

⚠ **Business Units are a label, not a security boundary.** You can organize records by branch/division for reporting, but there is no built-in restriction that stops a user with `risk:read` from seeing every risk in every business unit — only whole-organization isolation is enforced.

### 3.4 Evidence vs. attachments — two different things

- **Evidence** (`/evidence`) is specifically for proving a **Control** is operating — every evidence item must point at a Control. Collect it once per control and it counts toward every Compliance Requirement that control maps to.
- **Attachments** on any other record type (a risk, a policy, an incident...) go through the Collaboration panel described above ([§3.2](#32-recordpanels--the-shared-toolkit-on-every-record)), not the Evidence module.

### 3.5 Reference numbers

Most modules auto-generate a reference number server-side when you save (e.g. `REG-001`, `VLN-014`, `DEC-003`) — you don't type these yourself.

### 3.6 Import/export, custom fields, and status rules

These are System-section services that plug into modules rather than modules in their own right — see [§11](#11-system-administration).

---

## 4. How the sidebar is organized

The left navigation groups every module into seven sections, which this guide follows exactly: **Overview, Risk, Compliance, Governance, Organization, Operations, System**.

**Not seeing a module described in this guide?** Installations are licensed per module — the sidebar only shows what your license enables (for example, conventional banks typically don't license **Shariah Governance**; Islamic banks do). Administrators can see the full module matrix — *on / hidden / unlicensed* — under **Settings → System → Modules**. Enabling an additional module is a license update from your vendor, not a reinstall: your data model already supports every module, so nothing is lost or migrated when one is switched on later. A licensed module can also be hidden by the deployment's `DISABLED_MODULES` setting; opening its URL directly shows a "module not enabled" notice, and its API rejects calls, so hiding a module genuinely turns it off rather than just removing the menu entry.

---

## 5. Overview

### Dashboard (`/dashboard`)
**Purpose:** Read-only executive snapshot of live risk/compliance/control posture — the default landing page.
**What's on it:**
- A composite **Governance Health** score (0–100, banded Healthy / Elevated / Critical), blended from the share of risks within tolerance, overall compliance %, and the residual critical/high risk mix.
- A **"Needs your attention"** queue — auto-generated and prioritized (tolerance breaches, critical inherent risks pending treatment, frameworks below 80% compliant, overdue asset reviews, pending risk acceptances), each row carrying a one-click action button (Escalate / Assign / Review / Approve) that links straight into the relevant module.
- A 5-tile metric strip: Total risks, Critical inherent, Overall compliant %, Annual exposure (ALE), Tolerance breaches.
- A **risk matrix** bubble chart with an Inherent/Residual toggle — bubble size is the risk count in that likelihood×impact cell — plus the organization's appetite/tolerance scores.
- **Compliance** donut rings — one overall ring plus one per framework.
- An **enterprise risk roll-up** table by category (risk count, max residual, breaches, exposure).
- A **recent activity** feed, filterable to 30 days / Quarter / YTD.
**Key action:** "Executive summary" PDF export button.
**Note:** content is still fixed to risk/compliance metrics — for a customizable dashboard, use Reports & KPIs instead.

### Reports & KPIs (`/reports`)
**Purpose:** Build your own KPI dashboard from a metrics catalog spanning every module.
**How to use it:** Click **Add widget** → pick a metric (grouped by category — risk, compliance, incidents, assets, vendors, policies, projects, approvals...) → pick a visualization (Number / Bar / Donut) → it's added live.
⚠ Widgets are **organization-wide**, not personal — anyone who edits this dashboard changes what everyone sees.

### Strategy & Goals (`/goals`)
**Purpose:** Track strategic goals with a recurring pass/fail audit cycle.
**How to use it:** Create a goal (name, description, owner, target audience of related Risks/Projects/Policies) → set an **Audit Frequency** and **Success Criteria** → periodically **Record audit** (pass/fail + auditor + conclusion), which auto-reschedules the next audit date.
**Status flow:** `not_started → on_track → at_risk → off_track → achieved`.
**Connects to:** many-to-many with Risks, Projects, Policies. Export/Import CSV supported.

### AI Assist (`/ai-assist`)
**Purpose:** "Circular Intelligence" text-extraction workspace — paste text, get a structured extraction.
**How to use it:** Paste text (no PDF upload — text only) → choose **Source type** (circular / policy / free text / incident) → choose **Extraction type**: Extract obligations, Summarize, Suggest risks, or Map to ISO 27001 controls → click **Run extraction**. Results are saved with a reference number in a searchable history; use **Copy** to paste the output into the module it belongs to (e.g. obligations into Regulatory Change).
**Offline vs. online:** If no Anthropic API key is configured, it runs a deterministic offline heuristic and clearly labels the result as such — no data leaves your deployment. If a key is configured, it calls the AI model (labeled in the result) and silently falls back to the offline heuristic on any failure, so a request never crashes.
⚠ There is no NL "ask a question about my data" chat — only these four fixed extraction modes. Results are **not** auto-filed into other modules; you copy them over yourself.

---

## 6. Risk

### Risk Register (`/risks`)
**Purpose:** The platform's central qualitative (5×5) + quantitative (FAIR) risk log.
**How to use it:** Create a risk → **General** tab (title, category, owner) → **Assessment** tab (inherent likelihood/impact 1–5, plus optional FAIR fields: annual loss frequency, single loss expectancy → auto-computed ALE) → **Links & Relations** tab (link Assets, Controls, Threats, Vulnerabilities, Policies, Incidents) → **Review** tab (frequency). Set your org's **Appetite/Tolerance** thresholds once from the settings panel on this page — every risk is then banded against it.
**Status flow:** `draft → assessed → treatment_planned → treatment_in_progress → accepted → closed`.
**Key actions:** Appetite/Tolerance editor, Import/Export CSV, "Register PDF" export. A formal **Risk Acceptance** sub-workflow exists in the backend (request → approve/reject, forcing status to `accepted`) but isn't exposed as a button on this page yet.
**Connects to:** the platform's hub — Assets, Controls, Threat/Vulnerability library, Policies, Incidents, Goals, Vendors, and optionally a Risk Quantification record.

### Operational Risk (`/operational-risk`)
**Purpose:** Basel-style RCSA, Key Risk Indicators, and the loss-event database.
**How to use it:** **RCSA tab** — create an assessment campaign (business unit, process, assessor, period), then add risk/control lines inside it (inherent/residual scoring, control effectiveness, remediation action + owner). **KRI tab** — define an indicator (unit, frequency, direction, warning/limit thresholds), then log measurements over time; the current RAG status (green/amber/red) is computed automatically from the latest value vs. thresholds. **Loss Database tab** — log a loss event (Basel event type, business line, gross loss, recovery, dates, root cause).
**Status flows:** RCSA `planned → in_progress → completed`; Loss event `open → under_investigation → recovered → closed`.
**Connects to:** shares the 7 Basel event-type taxonomy with Scenario Analysis's capital calculator.

### Scenario & Capital (`/scenario-analysis`)
**Purpose:** Forward-looking op-risk scenario workshops plus Basel III SMA capital calculation.
**How to use it:** **Scenario Library** — record a workshop (frequency/year, typical loss, worst-case loss, participants, assumptions); expected annual loss is computed automatically. **Capital tab** — enter a period's Business Indicator and average 10-year annual loss; the Business Indicator Component, Loss Component, Internal Loss Multiplier and final Operational Risk Capital are all computed server-side from the Basel SMA formula — you don't calculate these yourself.
**Status flows:** Scenario `draft → workshopped → approved → closed`; Capital `draft → final`.

### Model Risk (`/model-risk`)
**Purpose:** SR 11-7-style inventory and validation cycle for quantitative and AI/ML models (credit scoring, IFRS 9 ECL, AML monitoring, capital, AI/ML).
**How to use it:** Add a model (purpose, type, materiality, methodology, owner/developer/vendor, whether it's regulatory-relevant and/or AI/ML) → add **Validations** underneath it (type, validator, date, outcome, findings) as they occur.
**Status flow:** model `development → validated → in_production → under_review → retired`; validation outcome `pass / pass_with_findings / fail / not_completed`.
**Key action:** filter by overdue validation; a summary rolls up counts by status/type and flags overdue validations.

### Threat Library (`/threat-library`)
**Purpose:** Two reusable reference catalogs — Threats and Vulnerabilities — that you link onto risks ("a threat exploits a vulnerability to create a risk").
**How to use it:** Add entries (name, category, description) to either catalog. The actual linking to a specific risk happens from that risk's **Links & Relations** tab in the Risk Register, not from this page. Before deleting an entry you'll see how many risks currently use it.
**Note:** this is a static reference catalog — for a live, scanner-fed vulnerability register see Vulnerabilities ([§7](#7-compliance)) instead, which is a separate, unrelated table.

### Risk Quantification (`/risk-quantification`)
**Purpose:** FAIR-style Monte Carlo simulation of PKR loss exposure, layered on top of the simpler ALE estimate on the Risk Register.
**How to use it:** Create a quantification (title, scenario, optionally link a Risk Register entry) → enter Threat Event Frequency and Loss Magnitude as triangular distributions (min/likely/max) → click **Run simulation** (default 10,000 iterations). Results (P10/P50/P90/mean/max exposure) are cached on the record.
**Status flow:** `draft → simulated → approved` (running a simulation auto-advances the status).

### IT Asset Management (`/it-assets`)
**Purpose:** Inventory of supporting/IT assets (hardware, software, infrastructure) judged by replacement cost and availability (RTO/RPO), with criticality that can also be *inherited* from the information it hosts.
**How to use it:** Create an asset (media type, cost + currency, availability, environment, hostname/IP/serial/manufacturer for hardware) → tag it → set **Discovery source** (manual, or a connector name if it came from automated discovery) → in the dependency manager, **link** it to any Information Asset it hosts/stores/processes/transmits/backs up.
**Key concept — criticality inheritance:** each asset shows `intrinsic_criticality` (from its own cost/availability), `derived_criticality` (the highest business value of everything it hosts), and `effective_criticality` (the higher of the two). Link your assets correctly and the platform tells you which IT assets are actually critical because of the data on them — not just their replacement cost.
**Connects to:** Information Assets (dependency link), Risks, Processes, Legal, Compliance Requirements, Incidents, Exceptions.

### Information Assets (`/information-assets`)
**Purpose:** Inventory of data/information assets, whose business value is self-assessed by the business owner (not IT/Security).
**How to use it:** Create an asset (information owner, business value, Confidentiality/Integrity/Availability, handling label — Public/Internal/Confidential/Restricted/PII, data categories, volume) → toggle **Self-assessed** and record who assessed it and when → in the dependency manager, link it to the IT Asset(s) that host it.
**Design intent:** Security defines the *criteria* for rating; the business owner does the actual rating via self-assessment — this is what feeds the IT asset's `derived_criticality` described above.

### Third Parties (`/vendors`)
**Purpose:** The vendor/third-party registry — contacts, criticality, contracts, risk rating, review cycle — referenced by both Outsourcing and Assessments.
**How to use it:** Create a vendor (category, type, contact details, criticality) → **Risk & Assessment** tab (risk rating, assessment status, review frequency) → **Contracts** tab (add one or more service contracts with value and dates — active contract value is auto-summed) → **Links** tab (related Risks/Assets).
**Status flow:** `prospective → active → suspended → offboarded`.
**Connects to:** Risks (many-to-many), Assets, Outsourcing (optional link back to a vendor), Assessments (via `vendor_id`).

### Outsourcing & Cloud (`/outsourcing`)
**Purpose:** SBP-specific regulatory layer on top of the vendor register — materiality, cloud model, data-offshoring, SBP approval/NOC tracking, exit planning.
**How to use it:** Create an arrangement (optionally linked to an existing Vendor) → **Materiality & Cloud** tab (material/non-material classification + assessment note, cloud model if applicable, data-offshoring country if applicable) → **SBP & Contract** tab (whether SBP approval is required, its status/reference, contract dates) → **Exit Plan** tab (exit plan text + whether it's been tested) → periodically add a monitoring **Review** underneath it.
**Status flow:** `proposed → active → under_review → terminated`; SBP approval `not_required → pending → approved/rejected`.
**Key action:** a summary flags contracts expiring within 90 days and exit plans that have never been tested.

### Vendor Assessments (`/assessments`)
**Purpose:** Send a scored questionnaire to a vendor, capture their answers, auto-score, and track resulting findings.
**How to use it:** Create an assessment (pick a Questionnaire template, optionally a Vendor, a due date) → answer each question (pick a scored option + comment) as responses come in → **Save & submit** when complete → raise **Findings** against weak answers and track them to **Close**.
**Status flow:** `draft → sent → in_progress → submitted → reviewed`. Score % = scored answers ÷ questionnaire max score.

### Questionnaires (`/questionnaires`)
**Purpose:** Builder for the reusable, weighted-scored questionnaire templates that Assessments sends out.
**How to use it:** Create a questionnaire → add questions → for each, add answer options with a score (new questions default to Yes=10/Partial=5/No=0) → reorder as needed → Save. A live "max score" preview updates as you build.
**Note:** templates carry no status of their own — the lifecycle lives on the Assessment that uses one.

---

## 7. Compliance

### Compliance (`/compliance`)
**Purpose:** Framework and requirement registers — map controls once to satisfy many frameworks, and track compliance gaps.
**How to use it:** Pick a Framework from the dropdown (or create one, or load a smaller built-in template via the **Library** button — a separate, lighter set than the Content Library packs) → its Requirements populate below → open a requirement's tabs: **General**, **Implementation** (status, treatment strategy, efficacy %, owner), **Mappings & Crosswalks** (link Controls/Risks/Policies/a Legal obligation, and crosswalk to equivalent requirements in other installed frameworks), **Audit & Findings** (raise/close findings).
**Status flow:** compliance status `not_assessed → non_compliant/partially_compliant → compliant` (or `not_applicable`); treatment `implement / improve / accept / transfer / not_applicable`.
**Key action:** **Gap Analysis** — auto-computed per framework, listing uncovered or non-compliant requirements.
**Connects to:** Evidence surfaces here via each requirement's mapped Controls; installing a Content Library pack populates this module.

### Framework Library (`/content-library`)
**Purpose:** One-click install of 6 preloaded, banking-relevant standards, avoiding manual data entry.
**How to use it:** Click **Install** on a pack card: ISO/IEC 27001:2022 Annex A (93 controls), NIST CSF 2.0, SBP ETGRM, PCI DSS v4.0, Basel Operational Risk (7 loss types + 11 PSMOR principles), or SBP/AAOIFI Shariah Governance (12 requirements). This creates a Framework + all its Requirements in Compliance in one step — you then map Controls and set up Crosswalks back in the Compliance module.
**Note:** re-installing an already-installed pack is blocked (idempotent).

### Regulatory Change (`/regulatory-change`)
**Purpose:** Track SBP circulars/laws from identification through implementation, distill them into obligations, and manage the recurring regulatory-returns calendar.
**How to use it:** **Regulatory Changes tab** — log a circular (regulator, circular reference, issued/effective dates, summary, applicability, impact assessment, owner, priority) → expand it to add **Obligations** directly underneath (obligation, mapped policies/controls as free text, owner, due date, status). **Obligations tab** — a flat cross-change view. **Returns Calendar tab** — recurring SBP submissions (frequency, submission channel, next/last due dates); overdue ones are auto-flagged.
**Status flow:** change `identified → under_assessment → in_implementation → implemented → closed`; obligation `open, in_progress, met, not_met, not_applicable`.
⚠ Mapped policies/controls on an obligation are **free text**, not real links to the Policy/Control modules — type the name/reference, don't expect a clickable link.

### ICFR (`/icfr`)
**Purpose:** Run the SBP-mandated annual Internal Control over Financial Reporting cycle.
**How to use it:** **Process & RCM tab** — create a financial process (cycle, business unit, mark key processes) → expand it to add RCM **Controls** (financial assertion, control type/nature/frequency, design & operating effectiveness) → expand a control to add **Tests** (test type, sample size, exceptions found, result). **Deficiencies tab** — raise a deficiency against a process/control (severity, remediation plan, target date) whenever a test fails or a control is rated ineffective.
**Status flow:** deficiency severity escalates `deficiency → significant_deficiency → material_weakness`; deficiency status `open → remediating → remediated → closed`.
⚠ There's no dedicated management-attestation button — use the generic **Review & Attestation** panel ([§3.2](#32-recordpanels--the-shared-toolkit-on-every-record)) on the process/control record for sign-off.

### AML / CFT (`/aml`)
**Purpose:** Sanctions/PEP/adverse-media screening register, STR/SAR filings to the FMU, and AML/CFT risk assessments.
**How to use it:** **Screening tab** — log a screening case (subject, screening type, lists checked, match status, disposition). **STR/SAR tab** — log a suspicious-activity case (amount, detected date — the FMU filing deadline auto-calculates from your configured SLA — analyst, suspicion reason); set status to `filed` and the filed date stamps automatically. **AML Risk Assessments tab** — periodic inherent/residual risk assessment by customer/product/geography/channel/enterprise scope.
**Status flow:** screening `open, under_review, cleared, escalated`; SAR `draft → under_review → filed → closed`.
⚠ This is a **register**, not a live screening integration — there's no "run screening" button that checks an actual sanctions list; results are recorded manually.

### Fraud Risk (`/fraud`)
**Purpose:** Fraud risk register, fraud case management, and the SBP digital-fraud control checklist — deliberately separate from AML.
**How to use it:** **Fraud Risk Register tab** — log a fraud scheme (channel, business line, inherent/residual likelihood-impact, red flags, control effectiveness). **Fraud Cases tab** — log an incident (amount involved/recovered, customer impact, whether it was reported to the regulator, root cause, resolution). **SBP Control Checklist tab** — tick off each SBP digital-fraud control requirement as implemented, with an evidence note.
**Status flow:** case `reported → investigating → confirmed → recovered/closed` (or `referred_to_authorities`).
**Key metric:** the dashboard computes net loss (amount involved − recovered) by scheme, and checklist implementation %.
⚠ Fraud cases are **not** linked to Basel loss events in Operational Risk — if a fraud case is also a Basel loss, log it in both places.

### Control Catalog (`/controls`)
**Purpose:** The central, reusable control library referenced by Compliance, Risks, and (indirectly) ICFR.
**How to use it:** Create a control (objective, description, owner, control type, classification) → **Cost & Resourcing** tab → **Audit & Maintenance** tab (set an audit frequency/success criteria and a separate maintenance frequency) → **Links** tab (map to Policies, Requirements, Risks). Use **Record Audit** and **Record Maintenance** buttons periodically — each logs a pass/fail and auto-reschedules the next due date.
**Status flow:** `planned → implemented → operational → retired`; effectiveness `not_assessed, ineffective, partially_effective, effective`.
**Note:** ICFR uses its own separate control entity, not this catalog.

### Vulnerabilities (`/vulnerabilities`)
**Purpose:** Live vulnerability register for scanner findings (Nessus/Qualys-style) and the patch pipeline that remediates them.
**How to use it:** **Vulnerabilities tab** — log a finding (CVE, CVSS score, severity, asset name/IP, source, discovered date); the remediation deadline is auto-set by severity (critical=7 days, high=30, medium=90, low=180, informational=365) and flagged overdue automatically. **Patches tab** — track a patch through `pending → testing → deploying → deployed` (or `failed`/`rolled_back`).
⚠ There is currently **no CSV import** and **no real link to the Asset inventory** for this register — asset name/IP are free text, described in the code as a "conceptual link" only. If you need bulk scanner ingestion today, add findings one at a time or via the API directly.

### Evidence (`/evidence`)
**Purpose:** Attach audit-readiness artifacts to a Control — see [§3.4](#34-evidence-vs-attachments--two-different-things).
**How to use it:** Create an evidence item (must pick a Control), fill in type/description/reference → save, then use the **Files** tab (appears after the first save) to upload the actual artifact.
**Status flow:** `pending, valid, expired` (auto-flags Expired once past its validity date).

### Internal Audit (`/internal-audit`)
**Purpose:** Full assurance workflow — a risk-based audit universe, engagements, working-paper procedures, and findings follow-up.
**How to use it:** **Audit Universe tab** — build your list of auditable units (category, inherent risk, audit frequency, next-due date). **Engagements tab** — create an engagement against a unit (lead auditor, scope, objectives, planned/actual dates) → add **Procedures** as fieldwork progresses (workpaper reference, result) → raise **Findings** (rating, recommendation, management response, due date). **Findings follow-up tab** — a cross-engagement list you can filter to open/overdue only, until every finding is closed.
**Status flow:** engagement `planned → fieldwork → reporting → closed`; finding `open → in_progress → closed` (or `risk_accepted`).
**Key action:** an **Audit Engagement Report** PDF export button on an open engagement.

### Declarations (`/declarations`)
**Purpose:** Periodic/event-driven staff attestation campaigns — COI, gifts & entertainment, personal account dealing, outside employment, code of conduct.
**How to use it:** **Campaigns tab** — create a campaign (declaration type, period, due date), open it, then add each staff member's **Declaration** underneath (whether they have a disclosure, details, amount, reviewer notes). **All Declarations tab** — a flat, cross-campaign view.
**Status flow:** campaign `draft → open → closed`; declaration `pending → submitted → reviewed → escalated/cleared`.

### Shariah Governance (`/shariah`)
**Purpose:** Islamic-banking governance — fatwa/ruling register, Islamic product register, Shariah compliance reviews, and the purification/charity ledger.
**How to use it:** **Fatwa Register tab** — record a ruling (subject, approved by, ruling text, basis, review frequency). **Islamic Products tab** — register a product and link it to the ruling that approved it. **Shariah Reviews tab** — create a review scoped to a product/branch/transaction/process → raise **SNC (Shariah Non-Compliance) Findings** underneath it, each with a tainted-income amount. **Purification Ledger tab** — record a charity disbursement, optionally tracing it back to the SNC finding whose income it purifies.
**Status flow:** ruling `draft → under_review → approved` (or `superseded`); SNC finding `open → in_progress → remediated → closed`; charity `pending → approved → disbursed`.
**Key action:** a **Shariah Review Report** PDF export button on an open review. A review's total tainted-income figure auto-rolls up from all its SNC findings.

---

## 8. Governance

### Policy Management (`/policies`)
**Purpose:** Central policy repository with a full document lifecycle, review cycle, and staff acknowledgment tracking.
**How to use it:** Create a policy (category, owner, review frequency) → write or attach the document (rich-text body, or toggle "use external document" and paste a URL) → **Links** tab (related Policies/Controls/Risks) → click **Publish** when ready (stamps a publish date and moves status). Staff click **Acknowledge** to record their sign-off; each policy shows how many acknowledgments it has. Schedule and **Complete review** cycles from the record.
**Status flow:** `draft → under_review → approved → published → retired`.

### Data Privacy (RoPA) (`/privacy`)
**Purpose:** GDPR-style Record of Processing Activities register.
**How to use it:** Create a processing activity across its tabs: **General** (controller/processor/DPO/business unit), **Lawfulness & Data** (lawful basis, data subjects/categories, special-category flag), **Transfers & Retention** (retention period, cross-border transfer toggle + safeguard, DPIA required?), **Data Subject Rights** (how each of the 5 rights is handled), **Links** (related processes/policies/assets/risks).
**Status flow:** `draft → active → under_review → retired`; DPIA status `not_required → required → in_progress → completed`.
**Key indicator:** the dashboard flags "transfer gaps" (cross-border transfer with no documented safeguard) and outstanding DPIAs.

### Data Protection (`/data-protection`)
**Purpose:** The DPO's day-to-day Pakistan-PDPA toolkit — distinct from the RoPA register above.
**How to use it:** **DPIA tab** — log an impact assessment (necessity justification, risks/mitigations, residual risk). **DSAR tab** — log a subject access/erasure request (a 30-day SLA clock runs from received date and flags overdue automatically). **Breach Register tab** — log a breach (severity, whether the regulator was notified, subjects notified?) — a 72-hour notification-overdue flag triggers if it's been more than 3 days since discovery and you haven't reported it. **Consent tab** — log/withdraw consent records.
⚠ DPIA references a "processing activity" by free text, not a real link to the RoPA module above — the two registers aren't structurally connected yet.

### Awareness Training (`/awareness`)
**Purpose:** Run recurring security-awareness campaigns with a built-in quiz.
**How to use it:** Create a program (target audience, passing score %, due date) → write the **Training Material** → build a **Quiz** (add questions, each with 2+ options, mark the correct one) → add participants under **Training Records** (name/email). Participants either **Take quiz** (auto-scored on submit) or you **Mark done** manually for off-platform completions.
**Status flow:** program `draft → active → closed`; participant `assigned → completed`. Compliant = completed AND score ≥ passing score.
⚠ Participants are free-text name/email, not linked to actual user accounts in Users & Roles.

### Delegation of Authority (`/delegation-of-authority`)
**Purpose:** Registers who may approve what (by role, amount band) and the maker-checker rules that should apply per module action.
**How to use it:** **Authority Matrix tab** — add an entry (activity, category, role title, approval level, amount range, effective date). **Maker-Checker Rules tab** — add a rule (module, action, maker role, checker role, threshold amount) and toggle it **Enabled**.
⚠ **This module is a documented registry only.** Defining an approval limit or a dual-control rule here does **not** currently force approval routing anywhere else in the system — see [§14](#14-known-gaps--things-that-look-automatic-but-arent-yet). For actually-enforced four-eyes today, use the Approvals module ([§10](#10-operations)).

### Board & Committees (`/governance`)
**Purpose:** Committee register, meeting lifecycle, and enterprise-wide decision/action tracking.
**How to use it:** Create a committee (type — board/audit/risk/credit/hr/it_steering/shariah/alco/compliance — chairperson, secretary, frequency, charter) → add **Meetings** underneath it (agenda, minutes, attendees, quorum met?) → inside a meeting, log **Decisions/Actions** (owner, due date). Track everything enterprise-wide from the **Action Tracker tab** (filterable by status/overdue), regardless of which committee/meeting it came from.
**Status flow:** meeting `scheduled → held → minuted` (or cancelled); decision `open → in_progress → done → deferred` (auto-stamps completion date; flags overdue).

### ESG / Green Banking (`/esg`)
**Purpose:** SBP Green Banking Guidelines alignment tracker plus environmental risk ratings for credit/vendor exposures.
**How to use it:** **ESG Assessments tab** — track a metric against a target (pillar: environmental/social/governance; SBP reference). **Environmental Risk Ratings tab** — rate an entity's sector-specific environmental risk (high/medium/low) with findings and mitigation notes.
**Status flow:** ESG assessment `not_started → in_progress → achieved → off_track`.

---

## 9. Organization

### Business Units (`/business-units`)
**Purpose:** Your organizational hierarchy (parent/child units) — owns assets, processes, and legal obligations across the platform.
**How to use it:** Create a unit (manager, contact, location) → optionally set a **Parent Unit** to build the tree → link **Legal & Regulatory Obligations** it's subject to.
**Note:** this is descriptive/reporting structure, not a security boundary ([§3.3](#33-multi-tenancy--data-isolation)).

### Processes (`/processes`)
**Purpose:** Business process catalog with continuity objectives, used for impact analysis.
**How to use it:** Create a process (business unit, owner, criticality) → **Continuity tab** (RTO hours, RPO hours, Max Tolerable Downtime) → link **Related Assets**.

### Legal Register (`/legal`)
**Purpose:** Legal & regulatory obligations register (GDPR, PCI-DSS, SBP regulations, etc.) with a risk-amplifying factor.
**How to use it:** Create an obligation (category, jurisdiction, statute reference, applicable countries) → set a **Risk Magnifier** (a multiplier > 1.0 to amplify the risk score of anything linked to it) → link the **Business Units** and **Assets** in scope.

### Users & Roles (`/organization`)
**Purpose:** Admin screen for user accounts, roles, and the platform's permission catalog — see [§13](#13-roles--permissions-reference) for the full role list.
**How to use it:** **Users tab** — create a user (name, email, initial password, one or more roles); use **Activate/Deactivate** to suspend access (you can't deactivate your own account) and **Reset password** as needed. **Roles tab** — create a custom role by picking permissions from the catalog (grouped by module, with bulk select/clear); built-in roles can have their permissions edited but not be renamed or deleted, and can't be deleted while still assigned to a user.

---

## 10. Operations

### Security Operations (`/incidents`)
**Purpose:** Log and resolve security incidents through a response lifecycle, with SBP-style regulatory breach-notification tracking.
**How to use it:** Create an incident (category, classification, severity, assignee, impact) → work through its **Response Stages** (a fixed NIST 800-61 lifecycle: Identification, Containment, Eradication, Recovery, Lessons Learned) using **Start/Done/Reopen** buttons → if it's reportable, click **Generate regulatory reports** (auto-creates an initial-notification + final-report pair with deadlines computed from your configured SLA windows) → **Mark submitted** with an acknowledgement reference once filed.
**Status flow:** `open → triage → investigating → contained → resolved → closed`.
**Connects to:** many-to-many with Controls, Vendors, Assets, Risks.
⚠ No automatic link to Issues & Actions — if a root-cause needs long-term remediation tracking, create the Issue manually.

### Business Continuity (`/continuity`)
**Purpose:** Continuity plans with recovery objectives and a recurring test/exercise calendar.
**How to use it:** Create a plan (business unit, process, criticality, RTO/RPO/max-tolerable-downtime hours, invocation criteria) → build the **Recovery Tasks** playbook (action/actor/timing/location/method, i.e. the "5 W's") → **Record exercise** periodically (auto-updates the next-test date from your test frequency and flags overdue tests).
**Status flow:** `draft → active → under_review → retired`.
**Note:** this module has its own free-text impact narrative field but is not structurally linked to the dedicated BIA module below — treat them as complementary, not automatically synced.

### Business Impact Analysis (`/bia`)
**Purpose:** Per-process impact analysis (criticality, RTO/RPO/MTPD, financial/operational/reputational/regulatory/legal impact) feeding continuity planning.
**How to use it:** Create an assessment (process name, business unit, owner) → **Impact & Timing tab** (RTO/RPO/MTPD hours, financial impact at 24h and 1 week, operational/reputational/regulatory/legal impact narratives) → **Recovery tab** (minimum resources, recovery strategy, workaround) → add **Dependencies** underneath (applications, assets, vendors, people, facilities — flag any single point of failure).
**Status flow:** `draft → submitted → approved → retired`.
**Key indicator:** an auto-computed RTO band (<4h / <24h / <72h / >72h) and a dashboard tally of total financial exposure and SPOF-dependency count.
**Recovery-strategy sign-off** happens via the generic Review & Attestation panel, not a dedicated approval button.

### Issues & Actions (`/issues`)
**Purpose:** The unified CAPA register meant to hold every finding/gap from every other module in one place, through to closure.
**How to use it:** Create an issue and pick a **source type** — internal_audit, compliance, rcsa, shariah, assessment, incident, external_inspection, risk_assessment, self_identified, or other — plus a free-text **source reference** (e.g. "AUD-004 finding 3") pointing back at where it came from. Add **CAPA Actions** underneath (corrective/preventive, owner, due date) and log **Progress Updates** as remediation proceeds.
**Status flow:** `open → in_progress → remediated / closed / risk_accepted`.
⚠ **This is entirely manual today** — no other module has a "raise an Issue" button. When you close a compliance finding, an ICFR deficiency, an internal-audit finding, an incident, or a Shariah SNC finding, you need to separately come here and create the Issue yourself if you want it tracked in the unified register.

### Whistleblowing (`/whistleblowing`)
**Purpose:** Confidential-disclosure intake and investigation case management.
**How to use it:** Log a report (category, channel, received date, severity) — toggle **Anonymous** to suppress reporter name/contact, which auto-generates a tracking code (e.g. `WBX-1A2B3C4D`) shown in the case header → work it through triage/investigation, logging **Case Log** entries as you go, to a substantiated/unsubstantiated/closed outcome.
**Status flow:** `received → triage → investigating → substantiated / unsubstantiated / closed`.
⚠ The tracking code is currently an **internal staff reference only** — there is no public page where an anonymous reporter can enter their code to check status or add a follow-up message themselves. Don't promise reporters a working self-service portal until that's built.

### Access Reviews (`/access-reviews`)
**Purpose:** Periodic user-access certification campaigns.
**How to use it:** Create a review (system name or linked asset, reviewer, frequency, due date) → add each account under review as an **item** (username, access held) → for each, click **Keep**, **Revoke**, or **Reset** → once every item has a decision, click **Complete review** (blocked until all are decided; auto-schedules the next review from your frequency).

### Approvals (`/approvals`)
**Purpose:** A generic, genuinely-enforced maker-checker inbox for any request needing independent sign-off.
**How to use it:** Create a request (title, approver, description, and how many independent checkers are required — 1 for four-eyes, 2 for six-eyes, etc.) → checkers **Approve** or **Reject** (a reject requires a written reason) → it auto-resolves to approved once enough checkers have signed off, or rejected on a single reject.
**Enforcement that's real:** the requester can never approve their own request, and each checker can vote only once — this is checked server-side, not just a UI suggestion.
⚠ Unlike Delegation of Authority, this module's four-eyes logic is actually enforced — but only for requests you create *here*. No other module automatically routes anything through Approvals; you create the request yourself and, if relevant, note in the description which record it concerns.

### Exceptions (`/exceptions`)
**Purpose:** Formal, time-boxed acceptance of a risk/policy/compliance gap.
**How to use it:** Create an exception (type, classification, rationale, start date, expiry date, compensating controls) linked to the Risks/Policies/Controls/Requirements/Assets it covers → an approver clicks **Approve** or **Reject** → once approved and remediated, click **Close**.
**Status flow:** `pending → approved / rejected → closed`; auto-flags `is_expired` once past the expiry date.

### Projects (`/projects`)
**Purpose:** Track remediation projects/initiatives addressing risks, controls, or policies.
**How to use it:** Create a project (owner, start date, deadline, budget) linked to the Risks/Controls/Policies it addresses → add **Tasks** (assignee, due date, % completion — overall project progress is the average of task completion) → log **Expenses** against the budget (flags over-budget automatically).
**Status flow:** `planned → ongoing → on_hold → completed / cancelled`.

### Activity Log (`/audit`)
**Purpose:** The system-wide, read-only, append-only trail of who did what — distinct from the Internal Audit module.
**How to use it:** View only — every create/update/close/decide/publish/test action across nearly every module writes an entry here automatically. There's nothing to configure; use it to answer "who changed this and when."

---

## 11. System (administration)

### Integrations & CCM (`/integrations`)
**Purpose:** Register connections to your bank's systems (AD, O365, SIEM, EDR, CMDB, core banking, cloud) and define automated control tests against them for Continuous Controls Monitoring.
**How to use it:** **Connectors tab** — register a connector (type, endpoint, auth method note, sync frequency) — flagged **stale** automatically if it hasn't synced in 35+ days. **CCM tab** — define an automated control test (which control it verifies, the pass condition in plain language, optionally which connector it uses) → **Record** a run's result (passed/failed/error, pass rate %, findings, evidence reference) each time it's executed.
⚠ Execution is **manual today** — there's no live "test connection" or scheduled auto-run; you record each run's outcome yourself. A run does **not** automatically update the linked Control's effectiveness rating or create an Issue.

### Custom Fields (`/custom-fields`)
**Purpose:** Add tenant-specific fields to a record type without code changes.
**How to use it:** Pick a module (all ~32 record types are supported — risk, control, asset, vendor, policy, incident, shariah_review, rcsa_assessment, audit_engagement, and so on), name the field, pick its type (text/textarea/number/date/select/checkbox), mark required if needed.
**Where the field appears:**
- **Risk Register** — as a **Custom fields tab directly inside the Add/Edit risk form**; values save together with the risk, and required custom fields block saving like any other required field.
- **Every other record type** — in the **Custom Fields panel on the record's detail view** ([§3.2](#32-recordpanels--the-shared-toolkit-on-every-record)): create/open the record, fill the custom values in that panel, and click **Save fields** (a separate save from the main form).

Fields do not appear retroactively inside other modules' Add/Edit dialogs — the record must exist before its panel shows. If you define a field and see nothing, check you picked the model key matching the module you're testing (e.g. `shariah_review`, not `risk`).

### Status Rules (`/status-rules`)
**Purpose:** Auto-label records with a colored badge when a field meets a condition (e.g. "Above Tolerance" when a score exceeds a threshold).
**How to use it:** Pick a module (risk, control, incident, vendor, project, policy, asset, goal, or exception), pick a field and operator (equals/greater-than/contains/overdue/is-true/not-empty, etc.), a comparison value, and a label + color.
**Note:** this is a labeling engine, not a time-based escalation engine — it doesn't send alerts or reassign anything on its own.

### Saved Filters (`/filters`)
**Purpose:** Build and reuse named, multi-condition queries (e.g. "Critical open risks") over a module.
**How to use it:** Pick a module, add condition rows (field/operator/value), choose match-all or match-any, mark it Shared if others should see it, then **Run** it to see the matching records.
⚠ Saved filters are a **standalone query tool** — they don't appear as a "load filter" dropdown on each module's own table view.

### Import / Export (`/data-io`)
**Purpose:** Bulk CSV import/export for 20 supported record types (Policies, Risks, Controls, Assets, Vendors, Incidents, Exceptions, Legal, Business Units, Processes, Threats, Vulnerabilities catalog, Goals, RoPA, Continuity Plans, Projects, Compliance Requirements, Evidence, Awareness Programs, Access Reviews).
**How to use it:** For any listed resource — **Export** to CSV, **Template** to get a header row + example, or **Import** (upload a `.csv` matching the template's column headers exactly — no manual column-mapping step). Each row runs through the module's normal creation logic (so reference numbers, links to other records by name, and audit logging all happen as if you'd created it by hand); a per-row result table shows what succeeded or failed, and one bad row doesn't block the rest.

### Webhooks (`/webhooks`)
**Purpose:** Push real-time HTTP notifications to an external system (SIEM, ticketing, chat) whenever records change.
**How to use it:** Create a webhook (name, payload URL, events — a comma list like `risk,incident,approval`, or `*` for everything, optionally a signing secret for HMAC verification) → **Test** it (sends a synthetic ping) → **Enable** it. Check the **Log** to see recent deliveries (success/fail, status code).
⚠ Delivery is single-shot, best-effort — there's **no automatic retry** if the receiving end is briefly down.

### SSO (`/sso-settings`)
**Purpose:** Configure OIDC/OAuth2 sign-in with your bank's identity provider.
**How to use it:** Toggle **SSO enabled**, enter your IdP's Client ID/Secret and authorize/token/userinfo URLs, set the email/name claim names, toggle **JIT provisioning** and pick the default role new SSO users get, and optionally restrict to specific email domains.
**Note:** LDAP/Active Directory is configured separately, on the `/settings` page.

### Settings (`/settings`)
**Purpose:** General admin hub — organization info, system health, personal security, and LDAP.
**What's here:** organization/role summary, a **Send test email** button (to verify SMTP), read-only system health/version/license info, the per-installation **module entitlement matrix** (which modules are on, hidden by config, or unlicensed), personal **MFA enable/change password**, the **LDAP/Active Directory** configuration card (host, bind DN, base DN, user filter, default role for JIT users), and an Administration hub linking out to Users & Roles, SSO, Webhooks, Custom Fields, Status Rules, Saved Filters, Import/Export, and the Activity Log.

---

## 12. End-to-end workflows

Worked examples of how modules chain together in practice.

**A. Taking a risk from identification to closure**
Threat Library (catalog a threat/vulnerability, if new) → Risk Register (create the risk, link the threat/vulnerability/asset) → Assessment tab (score inherent likelihood × impact) → link a Control from the Control Catalog as your treatment (collect Evidence against that control) → optionally Risk Quantification for a Monte Carlo PKR exposure range → set a review frequency and periodically re-assess → close or formally accept once treated.

**B. Responding to a new SBP circular**
AI Assist (paste the circular text, run "Extract obligations") → Regulatory Change (create the change record, add the extracted obligations underneath, assign owners/due dates) → if it maps to a standard you track, go to Compliance and update the relevant Framework's requirements (or install a new pack from the Framework Library first) → update the affected Policy in Policy Management → if there's a compliance gap, manually raise an Issue in Issues & Actions with `source_type = regulatory_change` → add any recurring submission to the Returns Calendar.

**C. Onboarding and assessing a vendor**
Vendors (create the vendor record, status `prospective`) → Questionnaires (reuse or build a scored template) → Assessments (send it, capture answers, review findings) → if the arrangement is SBP-material or cloud-based, add an Outsourcing record (materiality, SBP approval tracking, exit plan) linked to the same vendor → link the vendor to any related Risk Register entries → move vendor status to `active` and set a recurring review frequency.

**D. Handling a security incident**
Security Operations (log the incident, work the NIST response stages to closure) → if reportable, **Generate regulatory reports** and mark submitted once filed → manually create an Issue in Issues & Actions (`source_type = incident`) if root-cause remediation needs longer-term tracking → link the incident to affected Controls/Assets/Vendors/Risks for context.

**E. Running the annual ICFR cycle**
ICFR (build/maintain the process universe) → add RCM Controls per process with financial assertions → run Tests each cycle (design + operating effectiveness) → any failed test or ineffective control → raise a Deficiency, classify its severity, and remediate → use the Review & Attestation panel on each control for management sign-off (there's no dedicated attestation button).

**F. An internal audit engagement**
Internal Audit (maintain the risk-based Audit Universe) → create an Engagement against a unit → record Procedures as fieldwork proceeds → raise Findings → track them enterprise-wide on the Findings follow-up tab until closed → optionally mirror a significant finding into Issues & Actions manually.

**G. Asset criticality inheritance**
Information Assets (business owner self-assesses business value + CIA) → link it to the IT Asset(s) that host/store/process it → the IT Asset's `derived_criticality` inherits the highest business value of everything it hosts, and `effective_criticality` (the higher of intrinsic vs. derived) is what should drive incident-response prioritization and vulnerability remediation urgency.

**H. Operational-risk loss to Basel capital**
Operational Risk (log a loss event with its Basel event type) → over time, Scenario Analysis workshops future scenarios of similar events using observed frequency/severity as a starting point → the Capital tab computes Basel III SMA operational risk capital from your Business Indicator and average annual losses.

**I. A whistleblowing case**
Whistleblowing (intake — toggle Anonymous if needed, note the generated WBX tracking code as an internal reference) → triage → investigate, logging Case Log entries → resolve to substantiated/unsubstantiated/closed. (No public follow-up portal exists yet for the reporter — see [§14](#14-known-gaps--things-that-look-automatic-but-arent-yet).)

**J. Maker-checker today**
Delegation of Authority documents *who should* approve *what* (a reference matrix — not enforced). For an approval you actually need enforced today, create the request directly in Approvals, set the required number of independent checkers, and reference the record it concerns in the description.

---

## 13. Roles & permissions reference

Every permission is a `resource:action` code (93 total across every module). Most modules follow simple read/write; a few sensitive actions get their own verb (e.g. `risk:accept`, `exception:approve`, `workflow:approve`) so "can edit" and "can approve" can be different people.

| Built-in role | Typical use |
|---|---|
| **Admin** | Full access, including user/role management. |
| **Risk Manager** | Manage risk, controls, assets, incidents, vendors, BCP, projects, operational risk, fraud, scenario analysis, vulnerabilities, model risk, outsourcing, quantitative risk, AI Assist. |
| **Risk Approver** | Read-only across risk/controls/assets, plus the *approve* actions only (risk acceptance, exceptions, approvals) — a pure "checker" role. |
| **Compliance Manager** | Frameworks, policies, privacy, awareness, Shariah, AML, issues, regulatory change, ICFR, declarations, whistleblowing, governance, ESG, DoA, data protection. |
| **Auditor** | Read-only across the entire platform, plus full read/write on Internal Audit — an independence-preserving role. |
| **Viewer** | Read-only everywhere. |

Admins can also build **custom roles** by hand-picking any combination of the 93 permissions from Users & Roles ([§9.4](#94-users--roles-organization)). Assignment is per-user (pick one or more roles) — there's no per-record or per-business-unit scoping.

When the platform is upgraded with new modules (and therefore new permission codes), every built-in role is automatically topped up with the new codes it's entitled to the next time the backend restarts — this is additive only, never removes a grant, and never touches custom roles or a user's individual assignments. In practice this means you won't hit an unexpected 403 on a newly-added module after an upgrade without having to manually re-grant anything.

---

## 14. Known gaps — things that look automatic but aren't yet

Documented here so you plan your bank's process around what's actually enforced, not what's merely configured. (These are also tracked as deliberate follow-up work — see `GAP-ANALYSIS.md`.)

- **Delegation of Authority / dual-control rules are a registry, not an enforcement engine.** Defining an approval limit or a maker-checker rule there does not gate any write anywhere else in the system yet.
- **Approvals is not auto-triggered by other modules.** You must go create the request yourself and reference the source record manually; the four-eyes logic *inside* Approvals (once a request exists) is genuinely enforced.
- **Issues & Actions is entirely manually populated.** No other module has a "raise an Issue" button — you decide what's worth tracking there and create it yourself.
- **Business Units are not a security boundary.** Only whole-organization (tenant) isolation is enforced at the database level; anyone with a module's read permission sees every business unit's records in it.
- **Whistleblowing's tracking code is internal-only.** There's no public page yet for an anonymous reporter to self-serve a status check or add a follow-up.
- **Fraud Cases and Operational Risk Loss Events are separate, unlinked registers** — log a shared event in both if it applies to both.
- **Integrations/CCM connectors and test runs are manually recorded**, not live/automatic; a recorded run doesn't update a Control's effectiveness rating or auto-create an Issue.
- **Webhook delivery has no retry** — a single failed POST is logged, not retried.
- **Saved Filters run from their own page**, not as a live filter dropdown on each module's table.
- **Reporting is on-demand, not scheduled.** Four PDF exports exist (Risk Register, Executive Summary, Audit Engagement Report, Shariah Review Report) — there's no "email me this every Monday."
- **Record-level immutability** for loss events, SAR, and breach records (a regulator expectation) is not yet built.
- **New organization/tenant self-service creation** has no frontend page — it's an operator-run backend step today.
