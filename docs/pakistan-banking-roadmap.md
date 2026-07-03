# NexusLine — Pakistan Banking Roadmap (On-Premise + SaaS)

_Strategic scope for the primary target market: **banks in Pakistan**, deployed **on-premise**
(client-managed, we support) with a **SaaS** option on our own servers for clients who accept it._

> ⚠️ **Regulatory accuracy:** every SBP/regulatory reference in this document and in the
> shipped `sbp-*` framework packs is structured for operational use and **must be verified
> against the current SBP circular by a compliance SME** before audit reliance. Regulations
> change; do not treat these as legal citations.

---

## 1. Reframing the gap list for banking

The earlier `gap-analysis.md` list was written against eramba + the SaaS GRC market. For
on-premise Pakistani banks, that list is **over-scoped in some places and under-scoped in
others**. Banks care about three things, in order:

1. **Regulatory fit** — SBP frameworks, maker-checker, immutable audit trail, internal audit.
2. **Enterprise security controls** — AD/LDAP + SAML, MFA, RBAC/SoD, hardening.
3. **On-prem operations** — packaging, offline updates, backup/DR, offline licensing, low-touch support.

Several "modern SaaS" gap items are **not wanted** by air-gapped banks (see §5).

---

## 2. Already shipped (foundation these clients need)

- **SBP framework content packs** — `sbp-etgrm` (71), `sbp-cybersecurity` (71),
  `sbp-outsourcing` (50), `sbp-bcp` (44) = 236 controls, loadable into any tenant like the
  ISO/SOC packs. (Plus ISO 27001:2022, SOC 2, NIST CSF 2.0, PCI DSS 4.0, GDPR, HIPAA, CIS v8,
  NIST 800-53, ISO 42001 — 13 packs, ~1,235 requirements total.)
- **Maker-checker (4-eyes / N-eyes)** — approval requests now enforce **Segregation of Duties**
  (the maker can never approve their own request), support **N independent checkers**
  (`required_approvals`), require a **documented reason to reject**, and record an audit-grade
  **checker action log**. Controlled by `ENFORCE_SEGREGATION_OF_DUTIES` (default on).
- **Binary evidence storage**, **email + scheduler** (points at the bank's internal SMTP relay),
  **Alembic migrations** (the on-prem upgrade path), risk heatmap, global search, Settings page,
  CSV import/export on every module.
- **Authentication hardening** _(P0 auth tail — done)_:
  - **LDAP / Active Directory** login with two-step bind + JIT provisioning (per-tenant config
    UI; `ldap3`, lazily imported so the app runs without it).
  - **MFA (TOTP)** — RFC 6238, pure-stdlib (no dependency, works air-gapped), verified against the
    RFC test vectors; enrolment + login challenge step + self-service disable.
  - **Brute-force lockout** (configurable threshold/duration; counters persist across the failed
    login), **password policy** (length + complexity + optional expiry) enforced at
    register/change/admin-create/reset, and admin-reset clears lockout.
  - Config flags: `LDAP_ENABLED`, `MFA_REQUIRED`, `MAX_FAILED_LOGINS`, `LOCKOUT_MINUTES`,
    `PASSWORD_*`. _Still open in this tier: SAML (needs native xmlsec — separate track), API keys,
    user groups, record-level permissions._

---

## 3. Must-build for banks (pull forward from the gap list)

Procurement blockers — a bank's IT-security / internal-audit team will stop the deal without these:

| Priority | Item | Why banks require it |
|---|---|---|
| P0 | **AD/LDAP + SAML SSO** | Banks integrate with Active Directory; they will not create separate logins. Usually the first RFP question. |
| P0 | **MFA / 2FA** | SBP cyber guidance mandates MFA for privileged/admin access. |
| P0 | **Maker-checker applied system-wide** | Engine shipped; next step is routing material create/edit on each module through it (config-driven per module). |
| P0 | **RBAC + record-level permissions + SoD reporting** | Auditors test least-privilege and SoD conflicts explicitly. |
| P0 | **Immutable audit trail + SIEM export** (syslog/CEF) | Internal audit and SBP inspections require tamper-evident, exportable change history. |
| P0 | **Password policy, session timeout, lockout, brute-force bans** | Baseline security tests. |
| ✅ | **PDF report export** _(shipped)_ | ReportLab (pure-Python, air-gap safe — no headless browser). Four board/committee packs: audit-committee (engagement report), Shariah-board (review report), risk register, and executive GRC summary. Download buttons on the audit, Shariah, risks and dashboard pages. _(A drag-and-drop report *builder* is still open; these are fixed, styled report types.)_ |
| P1 | **Backup/restore + DR runbook** | Operational must-have on-prem. |

---

## 4. Pakistan/banking-specific requirements (not in eramba)

Where you win or lose bank deals — none of this is in the eramba spec:

- **Internal Audit module** _(shipped)_ — audit universe (risk-rated auditable units with
  frequency-driven planning), engagements with a full lifecycle (planned → fieldwork → reporting
  → closed), working papers / test procedures, and findings with rating, recommendation,
  management response and an action plan tracked through **follow-up to closure**. Overdue
  findings/engagements raise notifications; the `Auditor` role owns it via `internal_audit:*`
  permissions; RecordPanels gives auditors file-based working-paper evidence.
- **Operational Risk Management (Basel-style)** _(shipped)_ — **RCSA** campaigns with assessed
  risk/control lines (inherent vs residual scoring, control effectiveness), **KRIs** with
  warning/limit thresholds, a computed **RAG status** (green/amber/red) + breach alerts and a
  measurement time-series, and the **operational loss database** (7 Basel event types, gross/
  recovery/net, roll-up by event type). Owned by `oprisk:*`; live-verified 16/16 incl. the RAG
  transitions and net-loss math.
- **AML/CFT compliance tracking** _(shipped)_ — three registers: **sanctions/PEP screening**
  (match disposition, risk rating, escalation), **STR/SAR filings** with the FMU (auto-computed
  filing deadline from detection date, overdue tracking, FMU acknowledgement reference), and
  **AML risk assessments** (customer/product/geography/enterprise, inherent → controls →
  residual). Screening summary, overdue-SAR + escalated-case notifications; owned by `aml:*`.
  Live-verified 13/13. _(SLA windows verify vs current FMU/SBP rules.)_
- **Regulatory incident reporting** _(shipped)_ — incidents can be flagged reportable and
  **auto-generate the standard SBP submissions** (initial notification + final report) with SLA
  **deadlines computed from the detection date** (configurable windows — verify vs the current
  SBP circular). Submission tracking (status, acknowledgement reference), a cross-incident
  **obligations tracker** endpoint, and overdue-report notifications. Live-verified 8/8 incl.
  deadline math, overdue detection, and submission stamping.
- **SWIFT CSP attestation** — annual Customer Security Programme self-attestation for SWIFT banks
  (a framework pack + attestation cycle).
- **Regulatory change management** — track new SBP circulars → impact assessment → tasks.
- **Islamic / Shariah governance** _(shipped)_ — under the SBP Shariah Governance Framework: a
  **fatwa register** (Shariah Board rulings/resolutions with review cycles), an **Islamic product
  register** (by mode of finance — Murabaha, Ijarah, Musharakah, etc. — each linked to its
  approving ruling), **Shariah compliance reviews / Shariah audits** with **Shariah
  Non-Compliance (SNC) findings** that carry tainted income, and a **purification (charity)
  ledger** routing SNC income to charity. Overdue SNC findings raise notifications; owned by the
  `shariah:*` permissions. A differentiator few GRC competitors offer.

---

## 5. Deprioritize / drop for on-prem banks

Do not build these for air-gapped bank clients — some they cannot use:

- **External AI assistance** — usually prohibited (records cannot leave the bank). Only viable as a
  self-hosted model on their premises — a separate, later track.
- **CCM cloud connectors, Trust Center, outbound internet webhooks** — assume internet egress and
  SaaS estates; air-gapped core-banking can't reach them. **Keep these in the SaaS tier only.**
- **SCIM provisioning** — LDAP/AD sync covers the on-prem identity story instead.

---

## 6. Dual-deployment architecture (SaaS + on-prem)

**Principle: one codebase, config-driven deployment modes — never fork.** The existing RLS
multi-tenancy serves SaaS and degrades cleanly to a single-tenant on-prem install.

- **Packaging** — Docker Compose bundle (Postgres + backend + frontend + TLS reverse proxy) for
  most banks; Kubernetes/Helm for large ones. **Offline image bundle** (pinned image tarball) +
  installer script + sized `.env` template for air-gapped installs (no public-registry pulls).
- **Feature flags per deployment** — `AI_ENABLED`, `CCM_CONNECTORS`, `OUTBOUND_WEBHOOKS`,
  `ENFORCE_SEGREGATION_OF_DUTIES`, SMTP → internal relay. Cloud-only features off on-prem.
- **Licensing (on-prem control point)** — signed, **offline-verifiable license key** (expiry, seat
  count, enabled features); no phone-home (critical for air-gapped). Build on the existing
  license-check stub.
- **Updates & migrations** — Alembic is the upgrade path; ship **versioned release bundles + upgrade
  runbook**; banks apply signed update packages manually. No auto-update.
- **Data residency** — on-prem keeps all data in the bank's DC (satisfies SBP localization — the
  reason they want on-prem). For SaaS to banks, host **in-country**; otherwise keep SaaS for
  non-bank/less-sensitive clients.
- **Security integration** — AD/LDAP + SAML, TLS with the bank's certs, DB encryption at rest
  (disk-level TDE or `pgcrypto`), and audit-log export to their SIEM.

---

## 7. On-prem support model

Banks restrict remote access, so design for **low-touch support**:

- **Self-diagnostics built in** — a health dashboard and a **support-bundle generator** that
  collects logs/config/version **with secrets redacted**, so the bank sends you that instead of
  granting access. This single feature is what makes air-gapped support workable.
- **Tiered access** — on-site (or bank-approved jump-host/VPN) for installs and major upgrades;
  the diagnostic-bundle workflow for day-to-day issues.
- **Contractual** — SLA tiers, a patch/security-advisory cadence, and a signed-release process
  (banks ask for all three).

---

## 8. Recommended sequencing

1. **On-prem hardening & security** — SSO/LDAP + SAML + MFA + password/session/lockout +
   maker-checker rollout across modules + SIEM audit export. _(Unblocks every bank deal.)_
2. **SBP content packs** _(done)_ **+ Internal Audit module + PDF report export.**
3. **Operational risk (RCSA/KRI/loss events) + regulatory incident reporting + AML register.**
4. **Packaging / licensing / support tooling** — offline installer, offline license validation,
   support-bundle generator. _(In parallel; needed before first on-prem go-live.)_
5. **Islamic/Shariah module** and **SaaS-only differentiators** (AI/CCM/trust center) as later,
   tier-dependent add-ons.
