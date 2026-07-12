# GRC Connectivity Plan — Making NexusLine One Connected System

**Date:** 2026-07-13 · **Source of truth:** eramba data dictionary (419 tables, `docs/eramba/` in the eramba-docker repo) vs. a full audit of our models/schemas/APIs.

---

## 1. Executive summary

A GRC platform is not a set of registers — it is **one graph**. The value proposition of
eramba (and every enterprise GRC) is that a control links to the risks it mitigates, the
policies that mandate it, the compliance requirements it evidences, and the audits that
test it — so that when a control audit **fails**, the risk goes above appetite, the
compliance status flips, and a remediation project is born. Everything closes a loop.

Our audit found:

1. **The core seven are already meshed in the database** — risk, control, policy,
   requirement, asset, exception, incident have every eramba-style link table between
   them. This is a strong foundation.
2. **…but the UI hides half of it.** The Risk detail — the hub of the whole graph —
   exposes the *fewest* reverse links of any record: it never shows the requirements,
   exceptions, vendors, projects, goals, RoPAs, or quantifications that point at it.
   The system *feels* disconnected because each record shows only its outbound links.
3. **The banking modules are islands.** Internal-audit findings, RCSA lines, KRIs,
   loss events, BIA, ICFR, data-protection records, and regulatory change have
   essentially **zero foreign keys into the core graph** — free-text strings
   (`process_name`, `asset_name`, `control_description`) where FKs belong.
4. **The Issue module — designed as the connective tissue — is severed at both ends**:
   `source_id` is a bare unvalidated UUID, nothing auto-creates issues from findings,
   and no record shows "issues raised against me."
5. **None of the closed loops exist**: audit failure doesn't touch risk health;
   compliance status doesn't roll up from linked control/policy health; exceptions
   expire without consequence surfacing anywhere.

The plan: **five phases**, ordered so each ships visible value. Phase 1 requires no
schema change and transforms how connected the product feels; Phases 2–3 add the
missing edges; Phase 4 implements the eramba closed loops; Phase 5 finishes
cross-cutting parity.

---

## 2. The reference model — how eramba connects G, R, and C

### 2.1 The three closed loops

**RISK loop** (operational reality → risk posture):
```
Asset/Process registered (owner, CIA classification)
  → Risk identified on the asset (assets_risks), caused by threat/vuln (risks_threats)
  → scored inherent/residual vs appetite (risk_appetite breach flag)
  → treated: mitigated by CONTROLS (risks_security_services)
             + mandated by POLICIES (risks_security_policies)
             or accepted via EXCEPTION (risk_exceptions_risks, expiring)
  → controls are AUDITED on a calendar (security_service_audits)
  → audit FAILURE → improvement/issue → remediation PROJECT
  → failure/incident propagates BACK to the risk (controls_issues,
    risk_above_appetite flags recompute; risks_security_incidents)
  → periodic risk REVIEW closes the loop (reviews, expired_reviews counter)
```

**COMPLIANCE loop** (framework → evidence → status):
```
Framework loaded (packages → requirements)
  → each requirement gets ONE analysis row (compliance_managements):
    treatment = Compliant / Not Applicable / Not Compliant, an owner, efficacy
  → the analysis maps the requirement to its EVIDENCE GRAPH:
    controls, policies, risks, assets-in-scope, exceptions, projects
  → GAPS become dated findings (compliance_analysis_findings, due_date/expired)
    and remediation projects
  → external audits test item-by-item → audit findings → waived by compliance
    exception or converted into vendor risk
  → requirement STATUS ROLLS UP from the health of everything linked:
    control audit results, policy review currency, exception expiry, open findings
```

**GOVERNANCE loop** (ownership → cadence → approval):
```
Every governed record has an OWNER (workflow_owner_id)
  → and a REVIEW CYCLE (polymorphic reviews: planned vs actual, expired counter)
  → and WORKFLOW APPROVAL (draft → review → approved, approver/validator chains)
  → EXCEPTIONS are time-boxed acceptances that force re-approval on expiry
  → dynamic statuses + triggers automate the cadence; everything trails to audit log
```

### 2.2 The standard record surface (every eramba detail page)

1. Identity envelope (ref, title, owner, workflow status, soft-delete)
2. **One section per linked object type** — a risk shows its Assets, Controls,
   Policies, Exceptions, Requirements, Projects, Incidents, Threats, Vulnerabilities
3. Reviews (next date + overdue counter) · 4. Issues · 5. Comments & attachments
6. Tags · 7. Dynamic status chips · 8. **Denormalized health rollups**
   (`controls_issues`, `risk_above_appetite`, `security_incident_open_count`,
   `audits_last_passed`) — downstream health visible without clicking through

### 2.3 The 15 most important edges (ranked)

| # | Edge | Ours today? |
|---|------|-------------|
| 1 | risk ↔ control | ✅ have, exposed both ways |
| 2 | requirement ↔ control | ✅ have, exposed both ways |
| 3 | asset ↔ risk | ✅ have, exposed both ways |
| 4 | risk ↔ policy | ✅ have, exposed both ways |
| 5 | requirement ↔ policy | ✅ have, exposed both ways |
| 6 | requirement ↔ risk | ✅ in DB — **risk side hidden** |
| 7 | exception ↔ risk (expiring acceptance) | ✅ in DB — **risk side hidden** |
| 8 | policy ↔ control | ✅ have, exposed both ways |
| 9 | audit failure → remediation project | ❌ **missing** (findings are dead-ends) |
| 10 | requirement gap → dated finding | ⚠️ partial (RequirementAssessment exists; no dated finding register) |
| 11 | incident ↔ risk | ✅ have |
| 12 | control ↔ vendor risk | ❌ **missing** (vendor↔control absent) |
| 13 | vendor ↔ vendor-risk anchor | ✅ have (`vendor_risks`) |
| 14 | compliance exception ↔ requirement | ✅ in DB — **requirement side hidden** |
| 15 | requirement ↔ assets in scope | ✅ in DB — **requirement side hidden** |

**Conclusion:** we already have 11 of the 15 most important edges in the database.
The perceived disconnection is primarily an **exposure problem** (Phase 1), then an
**island problem** (Phases 2–3), then a **loop problem** (Phase 4).

---

## 3. Where we stand — the gap matrix

### 3.1 Hidden reverse links (edge exists in DB, one side blind)

| Detail page | Already shows | Must ALSO show (edge already in DB) |
|---|---|---|
| **Risk** | assets, controls, threats, vulns, policies, incidents, acceptances | **requirements, exceptions, vendors, projects, goals, RoPAs, quantifications** |
| **Control** | policies, requirements, risks | **incidents, exceptions, projects, evidence** |
| **Policy** | related, controls, requirements, risks, reviews | **exceptions, projects, goals, RoPAs** |
| **Requirement** | controls, risks, policies, legal, crosswalks | **assets-in-scope, exceptions** |
| **Vendor** | risks, assets, contracts | **incidents, assessments, outsourcing arrangements** |
| **Asset** | (full outbound set) | **vendors, access reviews** |
| **Threat/Vuln** | count of risks only | **the actual list of risks** |

### 3.2 Island modules (zero FK edges into the core graph)

| Island | Free-text where an FK belongs | Should connect to |
|---|---|---|
| Internal Audit findings | — | control, risk, requirement |
| RCSA lines | `control_description` text | enterprise risk, control |
| KRIs | `business_area` string | risk |
| Loss events | — | risk, incident |
| BIA | `process_name`, `business_unit` strings; dependencies free-text | process FK; dependency→asset/vendor FKs |
| Continuity plan | `bia` is a Text blob | BIA FK, assets, risks |
| Issues | `source_id` bare UUID, unvalidated | typed links + reverse listing |
| VulnFindings | `asset_name`/`asset_ip` strings | asset FK |
| Data breaches / DPIA / DSAR | — | incident, RoPA, assets |
| ICFR controls | parallel control universe | main `controls` register |
| Regulatory change obligations | — | requirements, policies |
| Auditable units | own free catalog | business unit / process |

### 3.3 Cross-cutting registry gaps

| Capability | Missing coverage |
|---|---|
| Custom fields | requirement, assessment, threat/vuln catalog, loss_event, audit finding, business_unit/process/legal |
| Versioning | all ~19 banking modules (issue, audit, RCSA, KRI, BIA, continuity, reg-change, outsourcing, ICFR, shariah…) |
| Dynamic status rules | requirement, continuity, RoPA, all banking modules |
| CSV import/export | issues, internal audit, RCSA/KRI/loss, BIA, outsourcing, reg-change, ICFR, shariah |
| Maker-checker enforcement | only 2 actions wired (risk accept, exception approve) |

---

## 4. The implementation plan

### Phase 1 — Expose what we already have (no schema change) 🎯 *biggest visible win*

Every detail drawer shows **every** DB edge, both directions, eramba-style.

1. **Backend:** add viewonly reverse relationships + Read-schema lists:
   - `RiskRead` += `requirements`, `exceptions`, `vendors`, `projects`, `goals`,
     `processing_activities`, `quantifications`
   - `ControlRead` += `incidents`, `exceptions`, `projects`, `evidence_count`
   - `PolicyRead` += `exceptions`, `projects`, `goals`, `processing_activities`
   - `RequirementRead` += `assets`, `exceptions`
   - `VendorRead` += `incidents`, `assessments`, `outsourcing_arrangements`
   - `AssetRead` += `vendors`, `access_reviews`
   - Threat/Vuln detail: return the risk list, not just a count
2. **Frontend:** the view drawers (already built) render a **"Related records"
   section per linked type** with chips that deep-link (`/module?id=`). Add missing
   sections per the matrix above.
3. **Performance guard:** all new lists use `selectinload` and cap at 50 with a count.

*Acceptance:* opening any Risk shows all ~13 relation groups; clicking a chip lands on
that record's drawer. No “Links: 6” counts without the actual records.

### Phase 2 — Reconnect the islands (highest-value new edges)

Schema additions (Alembic migration `0010_grc_graph`), models + schemas + API sync +
pickers in the record forms:

1. `audit_finding_controls` / `audit_finding_risks` / `audit_finding_requirements`
   — audit findings pin to what failed. Reverse: Control/Risk/Requirement drawers show
   open audit findings.
2. `rcsa_risks.risk_id` + `rcsa_risk_controls` — RCSA lines reference the enterprise
   register and real controls; RCSA effectiveness surfaces on the Control.
3. `kri_risks` — a KRI monitors risks; a red KRI badges every linked risk.
4. `loss_event_risks` + `loss_events.incident_id` — loss data calibrates risks.
5. `bia_assessments.process_id` FK (+ keep name fallback);
   `bia_dependencies.asset_id` / `.vendor_id` FKs.
6. `continuity_plans.bia_id` FK + `continuity_plan_assets` + `continuity_plan_risks`.
7. **Issue linkage:** `issue_links(issue_id, entity_type, entity_id)` generic table;
   `GET /issues?entity=` reverse endpoint; every core drawer gains an "Issues" panel;
   "Raise issue" action on AuditFinding / AssessmentFinding / ShariahFinding /
   Incident stamps the link.

*Acceptance:* an internal-audit finding created against control C shows on C's drawer;
an RCSA line's linked risk shows the RCSA rating; BIA can only pick real processes.

### Phase 3 — Complete the graph

8. `vendor_requirements` + `vendor_controls` (SBP outsourcing compliance).
9. `asset_threats` + `asset_vulnerabilities` (asset-based risk identification).
10. `vuln_findings.asset_id` FK — scanner findings land on real IT assets.
11. `data_breaches.incident_id` + `breach_ropas` + `breach_assets`.
12. Assessments generalized: target control/requirement, not only vendor;
    `assessment_findings.control_id` / `.risk_id`.
13. `obligation_requirements` + `obligation_policies` (reg-change mapping).
14. `control_assets` (which controls protect this asset — direct edge).
15. `icfr_controls.control_id` bridge to the main register.
16. `auditable_units.business_unit_id` / `.process_id`.

*Acceptance:* every register's form has pickers for its full edge set; every drawer
shows the reverse.

### Phase 4 — Close the loops (eramba's real magic)

1. **Risk health rollup:** denormalized flags on Risk — `controls_with_issues`
   (any linked control failing its latest audit / open finding), `exception_expired`,
   `above_appetite` — recomputed on control-audit save, finding save, exception expiry
   (extend the notification scheduler). Risk register gets a "Control health" column.
2. **Compliance status rollup:** requirement status derives from linked evidence:
   any linked control failing → flag; linked policy review overdue → flag; linked
   exception expired → flag. Gap register: dated findings with due dates on
   requirements (extend RequirementAssessment or new `compliance_findings`).
3. **Audit-failure → remediation:** failing a ControlAudit or AuditFinding offers
   one-click "Create project" / "Raise issue" pre-linked to the control + risk.
4. **Exception expiry consequence:** expired exception → notification (exists) +
   badge on every linked risk/policy/requirement/control drawer.
5. **Review cadence everywhere:** the attestation panel's `next_due` becomes a
   first-class "next review / overdue" indicator on all core registers (list column +
   drawer), matching eramba's `expired_reviews` counters.

*Acceptance:* fail a control audit → the mitigated risk's row shows a red "control
issues" chip and the evidenced requirement flips to "at risk" — with zero manual steps.

### Phase 5 — Cross-cutting parity

1. Custom fields: add requirement, assessment, threat, vulnerability, loss_event,
   audit finding, business_unit, process, legal to `CUSTOM_FIELD_MODELS`.
2. Versioning: register the banking modules in `MODEL_MAP`.
3. Dynamic status rules: extend to requirement, continuity, RoPA, banking modules.
4. CSV import/export: register the banking modules in `ResourceIO`.
5. Maker-checker: wire `enforce_maker_checker` into control-audit sign-off, SAR
   filing, charity disbursement, policy approval, authority-matrix changes.
6. Entity-type validation for collab/attestation/approvals (kill silent typos).

---

## 5. Sequencing & sizing

| Phase | Size | Depends on | Ship gate |
|---|---|---|---|
| 1 — Expose existing edges | M (backend schemas + drawer sections) | none | every core drawer shows all DB edges |
| 2 — Reconnect islands | L (migration 0010 + 7 modules) | none | findings/RCSA/KRI/BIA linked to core |
| 3 — Complete graph | L (9 edge sets) | 2 (migration pattern) | full picker + reverse coverage |
| 4 — Close loops | M/L (rollups + scheduler + one-clicks) | 1–3 | audit failure visibly propagates |
| 5 — Parity | M (registry extensions) | none (parallel-safe) | registries cover banking modules |

Recommended order: **1 → 2 → 4(1,4) → 3 → 4(rest) → 5.** Phase 1 first because it is
pure exposure of existing data — it changes the perceived product overnight. Phase 2
next because islands are where bank auditors will look (internal audit, RCSA, BIA).
The risk-health rollup (4.1) lands early because it's the single most "eramba" moment
in a demo: fail an audit, watch the risk register react.

## 6. Out of scope (tracked separately)

- Record-level immutability for loss events / SAR / breach records
- Scheduled PDF/XLSX committee report packs
- eramba-style polymorphic `reviews` table refactor (our attestation panel already
  covers the cadence; a refactor is not worth the migration risk now)
