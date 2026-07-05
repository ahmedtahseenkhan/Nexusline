# NexusLine GRC — Gap Analysis & Maturity Plan

*Prepared 2026-07-05. Basis: module-by-module code inventory + market research (Gartner IRM landscape, Archer / MetricStream / ServiceNow IRM / AuditBoard capability sets, 2026 GRC trend reports) + Pakistani regulatory landscape (SBP ETGRM, BPRD circulars, AML/CFT, Shariah governance, PDPA).*

---

## ✅ BUILD STATUS (updated 2026-07-05) — Tiers 0–3 IMPLEMENTED

All modules below were built (backend model+schema+API, frontend page, RLS, RBAC, migration) and
verified: full app constructs (**345 API paths, 180 tables, 93 permissions**), frontend type-checks
0 errors, Alembic migration `0008_banking_productionization` ran end-to-end against real Postgres,
and a live smoke test passed (auth → new endpoints → **derived-criticality inheritance** → AI heuristic
extraction → framework-pack install → Monte Carlo simulation).

| Item | Route | Status |
|------|-------|--------|
| 0.1 Asset split → IT Asset Mgmt + Information Asset Mgmt (derived criticality, separate tags, dependency link, self-assessment, discovery-ready) | `/it-assets`, `/information-assets` | ✅ verified live |
| 1.2 Unified Issues & Actions (CAPA) | `/issues` | ✅ |
| 1.1 Regulatory Change + Obligations + Returns calendar | `/regulatory-change` | ✅ |
| 1.3 ICFR (RCM, testing, deficiencies) | `/icfr` | ✅ |
| 1.4 Business Impact Analysis | `/bia` | ✅ |
| 1.5 Fraud Risk Management (+ SBP digital-fraud checklist) | `/fraud` | ✅ |
| 1.6 Delegation of Authority + maker-checker config | `/delegation-of-authority` | ✅ (config registry; runtime enforcement = follow-up) |
| 2.1 Scenario Analysis + Basel SMA capital | `/scenario-analysis` | ✅ |
| 2.2 Whistleblowing & Case Management | `/whistleblowing` | ✅ |
| 2.3 Compliance Declarations (COI/gifts/PA-dealing) | `/declarations` | ✅ |
| 2.4 Data Protection depth (DPIA, DSAR, breach, consent) | `/data-protection` | ✅ |
| 2.5 Outsourcing & Cloud (SBP materiality/approval/exit) | `/outsourcing` | ✅ |
| 2.6 Vulnerability & Patch Oversight | `/vulnerabilities` | ✅ |
| 3.1 Integrations & Continuous Controls Monitoring | `/integrations` | ✅ |
| 3.2 AI "Circular Intelligence" (LLM + offline heuristic) | `/ai-assist` | ✅ verified live (heuristic) |
| 3.3 Risk Quantification (FAIR / Monte Carlo) | `/risk-quantification` | ✅ verified live |
| 3.4 Model Risk & AI Governance | `/model-risk` | ✅ |
| 3.5 ESG / Green Banking | `/esg` | ✅ |
| 3.6 Board & Committee Governance | `/governance` | ✅ |
| 3.7 Framework Content Library (ISO 27001:2022, NIST CSF 2.0, ETGRM, PCI DSS 4.0, Basel, Shariah) | `/content-library` | ✅ verified live |

**Deliberate follow-up (not yet built):** deep cross-cutting hardening — runtime maker-checker
*enforcement* across every module (the DoA + dual-control *configuration* is built; wiring it into each
write path is the next task), record-level immutability for loss/SAR/breach records, and scheduled
PDF/XLSX committee report packs. AI Assist uses `settings.anthropic_api_key` / `ANTHROPIC_API_KEY`
(blank ⇒ offline heuristic, so on-prem installs work with zero external calls).

**Positioning goal:** one-stop GRC for Pakistani banks (SaaS + on-prem), exceeding eramba parity and competing with BenchMatrix RiskNucleus / 360factors locally, Archer/MetricStream aspirationally.

---

## 1. Where we stand

~35 live modules: Risks, Controls, Compliance (frameworks/requirements/findings), Policies, Incidents (+ SBP regulatory reporting SLAs), Exceptions, Vendors + contracts, Continuity (plans/tasks/tests), Internal Audit (universe/engagements/procedures/findings), Operational Risk (RCSA, KRI + measurements, Basel loss events), AML (screening/SAR/risk assessment), Shariah (rulings/products/reviews/charity), Privacy (RoPA), Access Reviews, Awareness, Threat Library, Goals, Projects, Questionnaires/Assessments, Attestations, Evidence, Approvals, Reports/Widgets, Custom Fields, CSV I/O, Webhooks, SSO/LDAP, RBAC/RLS multi-tenancy, versions, audit trail.

**Breadth already exceeds eramba.** The gaps are (a) banking-regulatory depth SBP examiners ask for, (b) the "connective tissue" mature platforms have (unified issues, workflow enforcement), and (c) the 2026 market direction (automation, CCM, AI).

---

## 2. Gap tiers

### Tier 0 — In flight (from stakeholder module review)

| # | Item | Notes |
|---|------|-------|
| 0.1 | **Split Asset Management → IT Asset Mgmt + Information Asset Mgmt** | ISO 27005 primary/supporting asset model. IT criticality = intrinsic (cost + availability/RTO-RPO) **+ derived** (inherited from information assets hosted). Info criticality = business value, attested by business owner via self-assessment form; Security designs criteria only. Separate tag/label vocabularies. One dependency join (info asset ↔ hosting IT asset) so criticality inherits — split, don't silo. Schema carries `discovery_source` / `last_seen` fields now for future automated discovery (CAASM direction). |

### Tier 1 — Regulatory table stakes for Pakistani banks (sell-tomorrow items)

| # | Module | What it is | Why it wins deals |
|---|--------|-----------|-------------------|
| 1.1 | **Regulatory Change Management** | Intake of SBP circulars/laws → applicability screening → **obligation register** (obligation → owner → mapped policies/controls) → impact assessment → implementation action plan → closure attestation. Plus a **regulatory returns calendar** (recurring SBP submissions with deadlines, owners, evidence). | Compliance departments' #1 pain. SBP issues circulars continuously; every bank tracks them in Excel. Nothing in our current `regulatory.py` does this (that file is incident breach-notification only). |
| 1.2 | **Unified Issues & Actions (CAPA)** | One issue universe aggregating findings from internal audit, compliance, RCSA actions, Shariah findings, assessment findings, incident RCAs, external/SBP inspection findings → action plans, owners, due dates, aging, escalation, closure evidence, repeat-finding flagging. | The single biggest architecture marker separating mature platforms (Archer/MetricStream/AuditBoard) from point tools. We have findings scattered in 6+ tables with no unified lifecycle. SBP inspection follow-up tracking alone justifies it. |
| 1.3 | **ICFR module** | Process universe → Risk-Control Matrix (RCM) → control testing cycles (design + operating effectiveness) → deficiency evaluation (deficiency / significant deficiency / material weakness) → management attestation → external-auditor view. | SBP mandates ICFR roadmap compliance; every bank runs an annual ICFR cycle with external auditor LFAR. Local competitors sell this as a headline module. |
| 1.4 | **Business Impact Analysis (BIA)** | Per business process: criticality, RTO/RPO/MTPD, peak periods, dependencies on information + IT assets (links to the Tier-0 split), recovery strategy sign-off. Feeds continuity plans. | ETGRM explicitly requires BIA-driven BCP; our continuity module has plans/tests but no BIA — an examiner would flag this immediately. |
| 1.5 | **Fraud Risk Management** | Fraud risk register (taxonomy aligned to RCSA), digital-fraud controls checklist per SBP 2023–25 fraud circulars (behavioral-profile rules, cash-out restrictions), fraud case management distinct from AML, complaint linkage, loss linkage to Basel loss events. | SBP's most active enforcement area right now; consumer digital fraud circulars have hard requirements. AML module doesn't cover internal/digital fraud. |
| 1.6 | **Maker-checker enforcement + Delegation of Authority** | Platform-wide four-eyes configuration: per module, which actions require independent approval; DoA matrix (who may approve what, by amount/severity); enforced, not advisory. | Banking table stakes; we have an approvals module but it is request-based, not enforced per-transaction. First question in any bank's IT audit of a new system. |

### Tier 2 — Complete the Basel/compliance suite (fast-follow)

| # | Module | What it is |
|---|--------|-----------|
| 2.1 | **Scenario Analysis + Op-Risk Capital** | The missing 4th leg of Basel ORM (we have RCSA, KRI, loss events). Structured scenario workshops (frequency/severity estimates, basis, participants) + a Basel III SMA capital calculator fed by the loss-event database → ICAAP support. Strong differentiator vs local competition. |
| 2.2 | **Whistleblowing & Case Management** | Anonymous intake portal (tokenized two-way channel), triage, investigation case files, outcome tracking. SBP governance + conduct expectations. |
| 2.3 | **Compliance Declarations engine** | Conflict-of-interest, gifts & entertainment, personal account dealing, outside employment — periodic + event-driven declarations. Reuse the questionnaire engine; add registers + approval flows. |
| 2.4 | **Privacy depth (Pakistan PDPA readiness)** | We have RoPA only. Add: DPIA workflow, DSAR intake + SLA clock, breach register with 72-hour notification tracking, consent registry. Positions us for the Personal Data Protection Act enforcement wave. |
| 2.5 | **Outsourcing / cloud depth on Vendors** | SBP outsourcing + cloud circular alignment: materiality assessment, SBP approval/NOC tracking, exit plans, concentration-risk dashboard, cloud-specific risk checklist. Vendor module has contracts; this is the regulatory layer on top. |
| 2.6 | **Vulnerability & Patch Oversight** | Live vulnerability register (CSV/API import from Nessus/Qualys/OpenVAS), auto-linked to IT assets (Tier-0), remediation SLA by severity, patch-compliance attestation. ETGRM requires VM program oversight; our threat library is a static catalog, not a live register. |

### Tier 3 — Market differentiators (2026 trend alignment)

| # | Capability | What it is |
|---|-----------|-----------|
| 3.1 | **Continuous Controls Monitoring + Integrations framework** | Connector architecture (LDAP/AD joiners-leavers, O365, SIEM webhooks, core-banking flags) → automated control tests + auto-collected evidence → real-time control health. The defining 2026 GRC trend; also the foundation for asset auto-discovery (0.1). Build the connector/ingestion framework once, reuse everywhere. |
| 3.2 | **AI layer — "Circular Intelligence" first** | Upload an SBP circular PDF → AI extracts obligations, screens applicability, maps to existing policies/controls, drafts the impact assessment into module 1.1. Then: policy drafting/gap analysis, risk-description suggestions, NL querying. Agentic-AI-in-GRC is the top analyst trend; circular intelligence is the highest-value, most Pakistan-specific application. |
| 3.3 | **Risk quantification (FAIR / Monte Carlo)** | PKR-denominated loss-exposure ranges on top of the qualitative register. "Financial quantification of risk" is a named 2026 trend; boards understand rupees, not heat maps. |
| 3.4 | **Model Risk & AI Governance** | Model inventory (IFRS 9 ECL, AML scoring, credit scoring), validation cycles, performance monitoring; ISO 42001 / EU-AI-Act-style framework content. SBP already supervises IFRS 9 and AML models; this is an emerging examiner topic. |
| 3.5 | **ESG / Green Banking** | SBP Green Banking Guidelines checklist, environmental risk rating in credit-relevant vendor/client assessments, ESG risk register + board reporting. Lightweight first pass. |
| 3.6 | **Board & Committee Governance** | Committees, charters, meeting calendar, agendas/minutes, decision & action tracking, auto-generated board packs (PDF) pulling live data from all modules. Completes the "G"; Diligent-style; strong demo moment ("your board pack builds itself"). |
| 3.7 | **Framework content library** | Preloaded, cross-mapped: ISO 27001:2022, NIST CSF 2.0, PCI DSS 4.0, SBP ETGRM (as an assessable framework), COBIT 2019, AAOIFI/SBP Shariah, Basel op-risk taxonomy. Cross-framework control mapping = "comply once, report many." Content is a moat and reduces onboarding time dramatically. |

---

## 3. Recommended build order

```
Phase A (now):        0.1 Asset split  →  1.2 Unified Issues (do early: every later
                      module emits issues into it)  →  1.1 Regulatory Change Mgmt
Phase B:              1.3 ICFR  →  1.4 BIA  →  1.5 Fraud  →  1.6 Maker-checker/DoA
Phase C:              2.1 Scenario+Capital  →  2.4 Privacy depth  →  2.5 Outsourcing
                      →  2.2 Whistleblowing  →  2.3 Declarations  →  2.6 Vuln register
Phase D (platform):   3.1 Integrations/CCM framework  →  3.2 AI circular intelligence
                      →  3.7 Content library  →  3.6 Board packs  →  3.3/3.4/3.5
```

**Sequencing logic:**
- **1.2 before everything else in Tier 1** — ICFR deficiencies, fraud cases, regulatory-change actions, BIA gaps all want to emit into the unified issue universe. Building it late means retrofitting six modules.
- **1.1 immediately after** — most-requested by compliance buyers, unmatched by eramba, and the natural host for the AI differentiator later (3.2).
- **3.1 integrations framework before 3.2 AI** — the AI features need the ingestion plumbing.
- Tier-3 items can interleave with Tier 2 when a sales conversation demands a differentiator demo.

## 4. Cross-cutting hardening (no new module, raise existing bars)

- **Report builder / scheduled reports** — current reports = dashboard widgets; banks need scheduled PDF/XLSX packs per committee (feeds 3.6).
- **Escalation engine** — status_rules exist; add time-based escalation chains (overdue issue → line manager → CRO) usable by 1.2.
- **Record-level immutability options** for loss events and SAR records (regulator expectation).
- **Urdu-ready i18n scaffolding** — low priority, but decide before UI strings multiply further.
