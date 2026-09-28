# NexusLine GRC — User Guide

*How every module works, how to use it, and how the modules connect to each other. Written from a direct code audit on 2026-07-05 and updated since — every field, status, and button named below actually exists in the app today. Sections marked ⚠ call out things that look automatic but currently require a manual step, so you don't design a process around a connection that isn't wired up yet.*

> **Setting NexusLine up for a bank?** The [Administrator & Configuration Manual](admin-guide.md) covers installation, the licence and modules, users and roles, sign-in (MFA, SSO, LDAP), e-mail, lists, frameworks, the risk methodology, maker-checker rules, approval routes, turnaround times, integrations, data migration and a go-live checklist, step by step.

---

## Table of contents

1. [What NexusLine is](#1-what-nexusline-is)
2. [Getting started](#2-getting-started)
3. [Concepts that apply to every module](#3-concepts-that-apply-to-every-module)
    - 3b. [How every register works](#3b-how-every-register-works)
    - 3c. [The dashboard](#3c-the-dashboard)
    - 3d. [Rules that keep the numbers honest](#3d-rules-that-keep-the-numbers-honest)
    - 3e. [Picked, not typed: owners, lists and the approval lifecycle](#3e-picked-not-typed-owners-lists-and-the-approval-lifecycle)
    - 3f. [Record depth](#3f-record-depth) — issues, controls, risks, third parties, incidents, KRIs, policies
    - 3g. [Working day to day](#3g-working-day-to-day) — setup, navigation, risk candidates, board packs, crosswalks, monitoring feeds, My Work and alerts
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

1. An **administrator manually creates you** under Users & Roles ([§9.4](#users--roles-organization)), typing your email, name, an initial password, and your role(s).
2. If your bank has LDAP or SSO with **just-in-time provisioning** enabled, your account is created automatically the first time you successfully sign in through the directory/IdP.

A new bank (organisation) is created by a platform administrator in the **Organisations** console (`/organizations`), or at first start of an on-premise install; its first administrator is then taken through **Organisation setup** (`/onboarding`).

### 2.3 Setting up a brand-new bank

The step-by-step order — setup wizard, organisation settings, sign-in, roles and users, e-mail, lists, structure, frameworks, risk methodology, governance controls, integrations and data import — is in the [Administrator & Configuration Manual, §7](admin-guide.md#7-the-setup-order-at-a-glance), with a go-live checklist in [§24](admin-guide.md#24-go-live-checklist).

---

## 3. Concepts that apply to every module

Learn these once — they show up almost everywhere and this guide won't repeat them per module.

### 3.1 The generic workflow status

Nearly every record — on top of its own business status (e.g. a Risk's `draft → assessed → treatment_planned...`) — also carries a second, generic **Workflow** field:

```
draft → in_review → approved → retired
```

It says whether the record itself has been approved, independently of its operational status. Since September 2026 it is not an editable field: it moves only through the **Submit for review / Approve / Reject / Revise / Retire** buttons on the record, and the person who submitted a record can't approve it. The **approval owner** is picked from the user list. See [3e](#3e-picked-not-typed-owners-lists-and-the-approval-lifecycle).

### 3.2 RecordPanels — the shared toolkit on every record

Open almost any record (risks, controls, vendors, incidents, policies, BIA, continuity, ICFR, issues, model risk, projects, Shariah, vulnerabilities, whistleblowing, DoA, assets, and more — roughly 30 modules) and you'll find the same three panels bundled in:

- **Custom Fields** — any extra fields your admin defined for that record type ([Custom Fields](#custom-fields-custom-fields)) appear automatically here.
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

## 3b. How every register works

Every list page — risks, controls, assets, incidents, policies, and the rest — is the same workbench, so what you learn on one applies to all of them.

- **Columns.** Each register declares far more columns than it shows by default. **Columns · N** on the toolbar opens the chooser: hide what you do not need, add anything from the catalogue (relation chips such as *Assets* and *Controls*, classification chips such as *L 3 — Possible · I 4 — Major*, dates, treatment, workflow), and drag to reorder. Locked columns (the reference and title) always stay. The layout is remembered per person, per register.
- **Views.** Once the columns, sort, search and filters are the way you want them, **+ Save view** keeps that arrangement as a tab — *Top risks*, *Review due this month*, *Mine*. Click a tab to restore it; *All items* is always the plain register. Views are yours and live in your browser; for a shared, exportable question use the **Report Builder**.
- **Dynamic status.** The first column shows what the organisation's **Status Rules** say about each row — *High Exposure*, *Review Overdue*, *Control Audit Failed* — evaluated live for the page. The same chips appear at the top of the record when you open it.
- **Selection.** Tick rows (or the header box for the page) and a bar appears with the register's bulk actions — *Delete selected* — plus **Export CSV** of exactly the visible columns for the selected rows.
- **Density.** The ≡ button switches between comfortable and compact rows.
- **Relation chips.** Columns such as *Assets*, *Controls*, *Policies* show the linked records inline, and each chip opens that record — the list is where the graph is walked, not just the drawer.

**Opening a record** takes the full page, in two columns that scroll independently — the same shape eramba uses, because a GRC record is not a form. On the **left** is the item: its fields, scores, related records and the page's own panels (for a risk: the suggested residual, the acceptance workflow, treatment). On the **right** is everything that has happened to it: status-rule chips, custom fields, review/attestation, an **Activity** timeline with the record's own audit trail (who changed what, and when), then comments, tags and attachments. **← Back**, the ✕, or Escape returns to the list exactly where you were. On a narrow screen the two columns stack.

## 3c. The dashboard

The dashboard is built around the five questions a risk function is judged on, in the order a board asks them. Every number on it links to the register that produced it, and the same rules apply as everywhere else — in particular, a control that has been mapped but never tested counts for nothing here, exactly as in the gap analysis and the residual engine.

1. **Are we inside the boundary we set?** — the **Governance health** score and, beside it, **Needs a decision or is overdue**: one queue, each line a link. The score is a weighted mean of four named components, all shown with the counts behind them: *within tolerance* (35%), *control assurance* (30%), *compliance assured* (20%), *nothing overdue* (15%). A gauge with no reasons is decoration; this one says "49 — because 7 of 227 controls have been tested".
2. **Are we inside appetite, and where?** — the KPI strip (above tolerance, control assurance, compliance assured, open incidents, KRIs breaching, tests overdue), the **risk matrix** on your own matrix size, and **Top risks**: the highest current exposures with owner, segment, appetite position, control count and review date — an unassigned owner or a risk with no controls is shown in red.
3. **Are the controls actually working?** — **Control assurance**: effective / partially / ineffective / never tested as a stacked bar, with tests overdue, failed last test, and tests recorded in the period.
4. **Are we compliant, and can we prove it?** — **Compliance**, one stacked bar per framework: *assured* (a working control behind the clause), *mapped but not tested*, *failing*, *no control*, plus the gap count and the percentage somebody has marked compliant — the two are shown side by side so an assertion without evidence is visible.
5. **What happened?** — open incidents by severity with the regulator-reportable count and the change against the prior period; KRIs as red / amber / green / no data with the breaching ones listed; risks **by segment** with breaches; third parties; and **Movement** — what was added, closed, tested and lapsed in the period — with recent activity.

The **30 days / Quarter / YTD** toggle sets the period for the movement and incident comparisons. **Executive summary** exports the board pack.

**When there is no data.** A measure with nothing to count is left out of the score, not scored as 100%, and the other measures' weights are scaled back up. Under the gauge the dashboard says how much of the score is real — *Scored on 2 of 4 measures (55% of weight)* — and a measure with no data reads "— no data". An organisation with nothing assessed shows no score at all. **How this is calculated**, under the list of measures, gives each weight and formula in words. Only frameworks that are obligations count towards *compliance assured*; maturity self-assessments such as ISO 31000 are listed separately. Planned and retired controls are not counted as tested, untested or overdue: a control that is not operating yet has nothing to test.

## 3d. Rules that keep the numbers honest

These rules were added in September 2026 after a product review found places where the product contradicted itself once real data was in it. Each one refuses a save or flags a record; none of them changes a number silently.

- **Residual can't be higher than inherent.** Controls only reduce a risk. Saving a residual score above the inherent score is refused unless you write an **override reason**, and only a user who can accept risk may record one. On the risk form, residual options above inherent are marked *(above inherent)*. Risks saved like this before the rule are flagged **Needs review** and stay flagged until the residual is lowered or a reason is recorded.
- **Needs review.** A risk is flagged when something it depended on changed underneath it: its residual contradicts its inherent score, or an asset it was written against was deleted (*Asset removed – review: Core Banking*). Flagged risks show a banner on the record, a **Review flag** column and filter on the register, and a marker in the dashboard's top risks. **Mark reviewed** clears the flag once the cause is dealt with.
- **Deleting an asset never removes risks.** The delete confirmation says how many risks link to the asset; those risks are flagged for review and stay in the register.
- **Review risks with no live links** (Risk Register → More) lists risks whose every asset was deleted *and* that link to nothing else — no controls, units, processes, policies, incidents, issues, KRIs, requirements or findings. Nothing is ticked for you; you choose each risk and write the reason. Archiving is a four-eyes action (*risk / bulk_archive*): while segregation of duties is on and no rule is configured it is refused, so add a rule for module *risk*, action *bulk_archive* under **Delegation of Authority → Maker-Checker Rules** to allow it. Archived risks are hidden from the register and kept in the database; each one gets its own audit entry.
- **Planned controls have no test clock.** A control's next test and maintenance dates are set when it becomes *implemented* or *operational*, one cycle from that day. A planned control shows *No test scheduled until the control is implemented* and never raises an overdue alert.
- **Recording a control test.** There is no preselected result. A passed or failed test needs the date it was performed and the tester's conclusion.
- **Evidence starts pending.** Evidence can be marked *valid* only once it has a collected date. Evidence with no collected date reads *Not collected*, and collected evidence with no expiry reads *No expiry set*.
- **One framework per name.** Two live frameworks can't share a name (ignoring case). Installing a library framework over an older, shallower copy of the same standard **upgrades** it: missing clauses are added and the existing clauses, statuses and links are kept. Duplicate copies left from older releases are merged on the next restart. The install message reports the requirement links it wrote (*93 requirement links*).
- **Maturity frameworks.** ISO 31000, ISO 27005 and the Basel operational-risk principles are guidance a bank measures itself against, not obligations. They carry a *Maturity self-assessment* badge, show clauses self-assessed instead of a compliance percentage, and stay out of the dashboard's compliance figures.
- **Alerts stay current and readable.** An alert's text is rewritten when the record changes, so it never quotes an old score. When one routine family produces more than five alerts — tests overdue, reviews due — they are shown as one line (*36 controls have tests overdue*) linking to the list. Tolerance breaches, missed turnaround times, approvals, attestations, regulatory deadlines and suspicious-activity reports are never grouped.
- **One review clock per record.** Attesting a risk, policy or third party uses that record's own review cycle and moves its next review date; it no longer starts a second, separate schedule.
- **Attestation is the owner's certification.** The record's **owner** attests it — that is the point of an attestation, and it is how ServiceNow, Archer and a SOX 302/404 certification work. You still can't attest a record that is still in Draft, or one whose approval is not complete (*Approve this control before attesting it*). Anyone else with write access to the module may sign instead, and the record then reads *attested by … on behalf of …*.
- **The second signature.** Every attestation can be **Confirm**ed by a second person, never by whoever signed it. On a **key control**, a **critical or high residual risk**, a **material outsourcing** relationship and **every policy** that confirmation is *required*: until it arrives the record reads *Attested by … — awaiting independent confirmation*, the attestation does not count, and the review cycle has not restarted. Whoever can confirm sees it in My Work under *Attestations to confirm*. The new review date is counted from the day the attestation was **signed**, not the day it was confirmed.
- **Approvals.** A request you raised shows *You submitted this — an independent checker must decide* instead of Approve and Reject; the server refuses it too, matching you by account or by email.
- **Two-factor authentication.** Your organisation runs at one of three levels, set by an administrator under **Organisation Settings → Security**: *Off* (nobody is made to enrol; anyone may still set it up), *Privileged roles* (the Admin role, anyone with a permission to approve, and the roles the administrator lists) or *Everyone* (every password sign-in). Where it is required, the first sign-in starts a 7-day grace period with a reminder banner; after it, the session can only open the setup screen. Single sign-on users are exempt, because their identity provider handles it.
- **Evaluation builds** show a banner saying the build is unlicensed and not for production use.

## 3e. Picked, not typed: owners, lists and the approval lifecycle

These changes, added in September 2026, replace free text with governed choices and give every record one approval lifecycle.

**Organisation settings** (Settings → Organisation). Choose the currency money is shown in, the timezone dates belong to, the date format, the month your financial year starts, the phone country, and how many days an archived record is kept before it is purged for good. The defaults are PKR, Asia/Karachi, DD/MM/YYYY, January, Pakistan and 90 days. Only an administrator can change them.

**Governed lists** (Settings → Lookups → Governed lists). Risk category (two levels, such as *Operational › Fraud*), incident type, incident classification, regulator, country, control classification, and the issue, KRI, policy, legal and third-party categories are managed lists, not free text. Add, rename, reorder, re-parent or deactivate values; a value in use can't be deleted, so deactivate it instead. When your organisation upgraded, every category already typed into a record became a value in its list, so nothing you entered was lost.

**Pickers.** Owners, managers, testers, reviewers, assignees and reporters are picked from the user list; business units and processes from the organisation tree; categories from their list. Anyone who can edit a record can pick an owner, without needing user-administration rights. Where an old record still holds text that matched nobody (*Was: CISO — pick a value*), the form shows it beside the picker until someone picks a real person.

**One approval lifecycle.** Every record moves Draft → In review → Approved → Retired through buttons on the record, not a dropdown: **Submit for review**, **Approve**, **Reject** (with a reason, back to draft), **Revise** (an approved record back to draft for rework) and **Retire**. The person who entered or submitted a record can't approve or reject it; the record says so and names why. If an approval route is switched on for that record type (Settings → Workflows), Submit starts the route and the record waits for it. Every move is kept in the record's history with who, when and why.

**Policies.** A policy becomes *under review* and *approved* through that lifecycle, and **Publish** is available only once it is approved. A published policy stays published while a revision is drafted, until it is retired.

**Deleting and restoring.** Before you delete a record, the confirmation lists what it is linked to (*12 controls, 3 policies and 1 KRI*). Deleting a risk, control, policy, business unit, process, issue, incident or third party is a four-eyes action: you can't delete a record you entered yourself while segregation of duties is on. Deleted records go to **Archived (N)** on their register, where anyone who can edit that register can restore them. Restoring an asset clears the *Asset removed* flag it put on its risks. After the retention period set under Organisation settings, archived records are purged for good.

**Statement of Applicability.** Each compliance framework has a **Statement of Applicability** tab: every clause, whether it applies, why, which controls implement it and how they last tested. Excluding a clause needs a justification. Export it as XLSX or PDF for your certification body.

**SBP frameworks bring their controls.** Installing SBP ETGRM, SBP Outsourcing or SBP BCP now creates their controls in the catalogue, and generated risks map to them as well as to ISO and CIS controls. For a framework you installed earlier, **Create controls** on the Framework Library adds them.

**Reusing your own controls.** Before a framework's controls are created, a preview shows which clauses will reuse a control you already have (by reference, or by the same name) and which will create a new one; you can switch any row. For a control you wrote yourself, **Suggested clauses** on the control lists the clauses it most likely implements across your installed frameworks, with the reason for each (*MFA → ISO A.8.5*). Tick and accept them, or use **Suggest mappings** on several selected controls at once.

**Importing.** Owner, unit and category columns in a spreadsheet can hold an email, a name or a list value; they are matched to the right person, unit or value. A value that matches nothing is kept on the record as text and reported as a warning for that row. A spreadsheet can bring records in already approved (a migration from another tool), but only when the person importing could approve those records in the app; otherwise the row is refused and the rest import.

**KRI breach alerts** now fire. Before this release a KRI past its limit never raised an alert.

## 3f. Record depth

These changes, added in September 2026, give the core records the depth a bank's reviewers expect.

### Issues

Issues now say what they concern, and closing one takes proof and a second person.

- **Links.** On the issue form, the **Links** tab picks the risks, controls, compliance requirements, assets and third parties the issue concerns; the drawer shows each as a chip that opens the record. **Raise issue** on a risk or control writes the link for you, and each record lists its issues by that link. *Source type*, *Source reference* and *Raised against* stay as where the issue came from. Issues raised from a record before this release were linked to it when your organisation upgraded. The register filters by linked risk, control or requirement.
- **Root cause.** Pick a **Root cause category** (People, Process, Technology, External — edit the list under Settings → Lookups) and describe the detail in *Root cause*.
- **Closing is not an edit.** The form's status offers only *Open* and *In progress*. In the drawer's **Validation & closure** card:
  - **Validate** records whether the fix works. The validator can't be the issue's owner or the person who raised it. *Effective* needs closure evidence under Attachments or Files on the issue; *Not effective* sends the issue back to *In progress*. The card shows who validated it, when, and their note.
  - **Close** (as closed, remediated or risk accepted) is refused, with the reason, while any action is still open or until the fix has been validated effective. Closing as *risk accepted* needs no validation; it needs an approved, unexpired acceptance on a linked risk, or a note from someone with approval rights (*workflow:approve*). The person who raised the issue can't close it.
  - The **Closed** date is set on Close and can't be typed. Choosing an open status on a closed issue reopens it and clears its validation.
  - An open issue linked to a control holds that control at *partially effective* until the issue closes.
- **Due dates.** Changing an agreed due date asks for a reason and is recorded in **Due date history** (*Date moved 3 times*); setting the first date isn't counted. A later date on a regulator-related, high or critical issue waits for approval, and the issue keeps its old date until someone with approval rights, other than the person who asked, clicks **Approve** in the history. Only one change can wait at a time. The register has an **Extension pending** filter, a *Date moved N+ times* filter, a sortable *Date moved* column and a count of extensions awaiting approval.
- **Maker-checker rules.** Validation, closing and extension approvals are four-eyes actions (*issue / validate*, *issue / close*, *issue / extend_due_date*). With segregation of duties on and no rule configured they refuse the same person; configure a rule under **Delegation of Authority → Maker-Checker Rules** to change that.
- **Importing.** An issue spreadsheet can link risks, controls, requirements, assets and third parties by name. Rows can come in closed, with their closed date, only when the person importing has approval rights; otherwise import them open.

### Controls and control tests

A control now says what kind of control it is, and its effectiveness comes from tests another person has reviewed, not from a dropdown.

- **Attributes.** The control form's **Attributes & scope** tab records the control's **nature** (preventive, detective, corrective, directive), **automation** (manual, IT-dependent manual, automated), whether it is a **key control**, how often it **operates** (continuous to ad hoc — separate from how often it is tested), the **business units** and **processes** it covers, its **test procedure**, the **evidence expected**, and its **ISO/IEC 27002:2022 attributes** (control type, security properties, cybersecurity concepts, operational capabilities, security domains), tagged by clicking. Controls created by installing ISO 27001 arrive tagged from the standard; a control you already had keeps any tags you gave it. The old *Control type* is still there, relabelled **Design artefact** or **Operating control**, at the bottom of the tab. The register has columns and filters for these.
- **Effectiveness is derived.** The drawer's **Effectiveness** card shows three ratings. **Design** comes from the latest approved design test, **Operating** from the latest approved operating test, and **Combined** — the one dashboards, residual suggestions and compliance coverage read — is the worse of the two that have been assessed. An open issue linked to the control holds the operating rating at *partially effective* until it closes. Tests recorded before this release count as operating tests. A control rated by hand before this release, with no test behind it, keeps that rating until its first approved test.
- **Override.** **Override** on the Effectiveness card sets the combined rating by hand; it needs a reason, which is shown on the card and kept in the activity trail. **Drop override** returns to what the tests say. The next approved test replaces an override. Importing a spreadsheet with an *effectiveness* value needs an *effectiveness_override_reason* on the row; leave effectiveness blank to let tests decide.
- **Recording a test.** **Record test** on the **Tests** card (permission *control:test*, which every role that can edit controls now has) opens a workpaper pre-filled from the control's test procedure, metric and success criteria. Say whether it was a **design** or **operating** test, when it was performed, and — for an operating test — the period it covers; then the population, sample size and method, any **exceptions**, the result and the conclusion. **Passed with exceptions** needs at least one exception and rates the control partially effective. A passed, passed-with-exceptions or failed test needs at least one evidence item: attach the control's existing evidence, or add new items in the workpaper and upload their files from the Evidence register. Leave **Tester** blank if you did the test yourself.
- **Review (four-eyes).** A new test is *Pending review* and changes nothing until someone else approves it. **Review** on the test row offers **Approve** or **Return to tester** (with a note). The tester, the person who recorded the test and anyone who edited it can't review it (*control / review_test* under Maker-Checker Rules). A returned test shows the reviewer's note; the tester opens **Fix & resubmit**, and it goes back to pending. An approved test is signed off: it can't be edited, and its evidence can't be deleted or moved — record a new test instead.
- **A failed test raises an issue.** Approving a *failed* or *passed with exceptions* test opens an issue at once — *Control test failed: A.8.5 Secure authentication* — owned by the control owner, linked to the control, and shown on the test row. A failed key control is *high* severity; any other failure, or exceptions in a key control, *medium*; exceptions in another control, *low*.
- **Evidence shows its test.** The Evidence register's **Supports test** column and the evidence drawer name the test an item supports (date, type, result, review state) and open the control.

### Risks

A risk now carries a structured statement, a scored and explained assessment, a target, a treatment plan you can chase, and the appetite of its own category.

- **Risk statement.** The form opens with **Cause**, **Event** and **Consequence**. Leave **Title** blank and it is written for you as *"Event, caused by cause, resulting in consequence"* (the form shows the title it will use). The event is required when there is no title. **Risk type** (strategic, operational, financial, compliance, technology, emerging), **Velocity** (how fast the impact is felt once the event happens: immediate — within days, weeks, months, years), **Source** (RCSA, audit, incident, regulatory, self-identified, generated, other), **Identified on** and **Identified by** (you, if left blank) sit under the category. Risks created by **Generate risks from assets** are marked *Generated*.
- **No pre-filled scores.** A new risk starts with blank likelihood and impact. A **draft** can be saved unscored, or with provisional scores and no rationale; any other status needs both inherent scores and an **Assessment rationale**. The server refuses it otherwise.
- **Every score change has a reason.** Changing an inherent or residual score on a risk that is not a draft needs a new **Assessment rationale** — the form clears the old one when you change a score and asks why the scores moved. Each change records **Last assessed** (who and when), shown under the rationale in the drawer. Accepting the suggested residual writes its reasoning as the rationale; an override writes your reason. **Assess** and **Accept suggestion** move a draft to *Assessed* only when its inherent scores were recorded earlier and there is a rationale; otherwise the risk stays a draft with a provisional residual.
- **Impact by dimension.** The Assessment tab has a grid: one row per impact dimension (Financial, Regulatory, Reputational, Customer, Operational — edit the list under Settings → Lookups → *Impact dimension*), one column each for inherent and residual. Score the dimensions that apply and the overall impact for that column is set from them — the **highest** by default, or the **average rounded up** (Risk methodology → *Impact from dimensions*). While a column has dimension scores, its impact can only change through them. Leave a column blank to set its impact directly.
- **Target.** **Target risk** (likelihood × impact) is where treatment should take the risk. It can't be higher than the residual, or the inherent when there is no residual. The drawer shows target beside inherent and residual; the register has an optional **Target** column.
- **Treatment actions.** In the drawer's **Treatment** card, **Add action** records a step with an owner and a due date. Change its status (open, in progress, done, cancelled) and percent complete in the row; **Done** records when it was completed. The card shows *n of m done* (cancelled actions are not counted) and flags overdue actions. *Treatment plan* stays as the summary. Once a risk has actions, its **Treatment deadline** is the latest due date among its open actions (or of all actions, once every one is done) and can't be typed. The dashboard's *treatment actions past due* count, the health score's deadlines and the notification feed follow the actions: each open action past its due date raises an alert, and many are grouped into one (*12 risk treatment actions past due*). A risk without actions is still judged on its deadline on the dashboard. **Remove** deletes an action (the activity trail keeps it); cancel it instead to keep it on the plan.
- **Linked issues.** Issues linked to the risk from the issue side appear under **Related records → Issues**.
- **Appetite per category.** In **Risk methodology** (register → More → *Risk methodology…*), **Appetite per risk category** sets an appetite, a tolerance and a statement for a top-level risk category; its sub-categories use it too. Risks in other categories use the organisation's appetite and tolerance. Each risk is compared with its own category's numbers everywhere: the register's *Appetite* column (hover for the numbers applied), the drawer, the dashboard's *above tolerance* count, top risks, segments and health score, the *Tolerance by category* table under the dashboard's risk matrix, **Risk alerts**, the category roll-up and the tolerance-breach notification. Changing appetite needs the same permission as the organisation's thresholds (*risk:write*), and every change is in the activity trail. Removing a category's appetite returns its risks to the organisation's.
- **Band thresholds and cell-by-cell bands.** Risk methodology can now **Set our own band thresholds** (the highest score that is low, medium and high; everything above is critical) instead of bands that scale with the matrix size. **Matrix cells** shows the grid: click a cell to cycle its band (low, medium, high, critical, back to its score's band) — for example to rate rare-but-catastrophic as high. Cells set by hand are marked •. **Save scale** saves the size, wording, thresholds, cells and the impact rule together. The register's severity labels, the drawer and the dashboard (risk matrix, severity counts and top risks) use them. Shrinking the matrix keeps the cells that still fit and drops thresholds that no longer fit, and is still refused while any score — including a target or a dimension score — is above the new size.
- **Importing.** A risk spreadsheet can carry *cause*, *event*, *risk_type*, *velocity*, *source*, *identified_date*, *target_likelihood*, *target_impact* and *assessment_rationale*. Rows with a status beyond draft need both inherent scores and an *assessment_rationale*; import them as drafts otherwise. There is no *consequence* column, because in most bank registers "Consequence" is the impact score; add it in the form after importing.
- **Reports.** The report builder's risk report has optional *Target*, *Type*, *Velocity*, *Source*, *Identified*, *Cause*, *Event*, *Consequence*, *Assessment rationale* and *Last assessed* columns; the register PDF's detail pages show the statement, the target, the type, velocity and source, and the rationale.
- **Everywhere the same numbers.** The PDF register export, the report builder, the KPI metrics and the turnaround-time clock all use the configured bands, cell overrides and category appetites, so a report's "breach" matches the dashboard's. Overdue treatment actions appear in their owner's My Work.

### Third parties

A third party's record now holds its due diligence, its certifications, the SBP outsourcing facts about it, and an inherent risk tier worked out from a questionnaire rather than a guess.

- **Due diligence.** The vendor form's **Due diligence** tab records the **legal name** and **registration number** (SECP), the bank's **relationship owner** (picked from users), the highest **data classification** the third party can see (Public, Internal, Confidential, Restricted — edit under Settings → Lookups → *Data classification*), the **data residency** countries (where it stores or processes the bank's data, DR sites included), the **processes** it supports, its **sub-contractors** (fourth parties, picked from the vendor register) and its **annual spend** with a currency. A vendor can't be its own sub-contractor. The drawer's **Due diligence** card shows all of it, including **Is a sub-contractor of**: the vendors that list this one as theirs. A spend or contract with no currency picked is in your organisation's currency (Settings → Organisation).
- **Contracts in their own currency.** A contract now has a **Currency** (your organisation's by default). The register and the drawer show live contract value per currency (*PKR 5,000,000 + USD 12,000*) rather than adding rupees to dollars. Contracts recorded earlier are in the organisation's currency.
- **Certifications.** The **Certifications** tab (after the vendor is saved) records ISO 27001, ISO 22301, SOC 1, SOC 2 Type I, SOC 2 Type II, PCI DSS, CSA STAR or Other, with issuer, certificate number, scope, issue date and expiry date. **Edit** and **Remove** are on each row; every change is in the activity log. Each row shows its state: *Valid to …*, *Expires in N days* from 60 days before expiry, *Expired*. The notification feed raises **Certification expiring** 60 days before a certificate's expiry and **Certification expired** once it has passed (critical for a high or critical third party), one per certificate; more than five of either are grouped into one alert. Offboarded third parties raise none.
- **Inherent risk tier.** Every organisation now has an **Inherent risk tiering** questionnaire under Questionnaires: eight scored questions on the data the third party handles, the customer impact of a failure, SBP outsourcing materiality, how quickly it could be replaced, concentration, its access to your systems, its reliance on sub-contractors, and where your data is held. Each answer scores 0 (least risk) to 3 (worst case). In the vendor drawer, **Start tiering questionnaire** creates an assessment of it for that vendor and opens it; answer every question and submit. On submission the vendor's **inherent tier** is written:
  - the total as a percentage of the maximum sets the band — **70% and above critical, 45% high, 20% medium, below that low**;
  - one worst-case answer makes the tier at least **medium**, three or more at least **high**, so a few severe answers aren't averaged away;
  - a tiering assessment with an unanswered question can't be submitted.
  The **Inherent risk tier** card shows the tier, the score (*9 of 24 (37.5%) is medium; raised to high by 3 worst-case answers*), the assessment it came from, and the criticality it proposes. If the assessment's answers change later, the card says so; **Recompute tier** takes the tier from the latest completed tiering assessment. The register has a sortable **Inherent tier** column. Questionnaires you edit keep working as long as the name stays *Inherent risk tiering*; the bands use percentages, so re-weighting the options is fine. A renamed or deleted tiering questionnaire is re-created the next time the server starts.
- **Criticality follows the tier unless you give a reason.** Once a vendor has a tier, its criticality is set to the tier's proposal (low, medium, high or critical, one for one). To keep a different criticality, pick it on the form and give a **Reason for overriding the tier**; the form asks for one, and the server refuses the change without it. The override and its reason show in the drawer and are in the activity log. A later tiering keeps a reasoned override and replaces an unreasoned criticality. Picking the proposed criticality again clears the reason.
- **Outsourcing facts on the vendor.** When an outsourcing arrangement is linked to the vendor, the drawer's **Outsourcing (SBP)** card shows its materiality, cloud, data offshoring and country, SBP approval, contract end and exit plan (tested or not). Change them under Outsourcing.
- **Outsourcing owner and country are picked.** On an outsourcing arrangement, **Owner** is now a person picked from users and **Country** a value from the country list. An arrangement saved before this release shows its old text as *Was: … — pick a value* until someone picks. Spreadsheet imports can still give an owner's email or name and a country's name; they are matched when they name exactly one. Every change to an arrangement and its monitoring reviews is now in the activity log.
- **Importing.** A vendor spreadsheet can carry *legal_name*, *registration_number*, *annual_spend* and *spend_currency*. The relationship owner, data classification, residency, processes, sub-contractors and certifications are set in the form.
- **Known gaps.** A general (non-tiering) assessment's score still doesn't write the vendor's *Risk rating*. A certificate has no file of its own; attach the certificate to the vendor under Attachments. Reports, the PDF export and the dashboard don't show the new fields yet.

### Incidents

An incident now keeps its timeline to the minute, runs the regulator's notification clock, and hands off to the breach register and the loss database.

- **Times, not dates.** On the form's **Timeline** tab, *Occurred*, *Detected*, *Contained* and *Resolved* take a date **and a time**, entered in your organisation's timezone (Settings → Organisation; the tab names it, e.g. *Asia/Karachi · UTC+05:00*), whatever the browser's timezone. They must run in order: occurred, then detected, then contained, then resolved; the server refuses a timeline out of order. Moving the status to **Contained** fills in *Contained* with the current time if it is blank, and **Resolved** or **Closed** does the same for *Resolved*; correct either on the form. Dates recorded before this release became 00:00 on that day, organisation time.
- **Response times.** The drawer's **Response times** card shows **MTTD** (occurred to detected), **MTTC** (detected to contained) and **MTTR** (detected to resolved) for the incident, and the Timeline tab shows them as you type. The cards above the register show the means across incidents that recorded both ends, with how many that is.
- **The regulator's clock.** The **Regulatory** tab holds **Reportable** and the **Regulator** (from the *Regulator* list; SBP when left blank). Saving a reportable incident creates its **initial notification** and **final report**. The initial notification is due the configured number of hours after detection (24 by default), to the minute; the final report is due the configured number of days after (30 by default). With no detection time, the clock starts when the incident was logged. Changing the detection time moves both deadlines while they are still pending; a submitted report keeps its deadline. *Generate* in the drawer's **Regulatory reporting** card recreates a report that was removed. Record the notification on the Regulatory tab (**Notified at**, **Regulator reference**) or with **Mark submitted** on the initial notification's row; both write to that report. The drawer shows the deadline, a **live countdown** (*Due in 5 h 12 m*, *Overdue by 2 h*), when it was notified, the reference and an **on time / late** badge; the register's *Regulator notification* column shows the same badge. An overdue report raises a critical alert naming the deadline in organisation time.
- **Impact.** The **Impact & analysis** tab records *Customers affected* and *Records affected* beside the impact text and cost.
- **Near miss.** Tick **Near miss** when nothing was lost. A near miss can't carry a cost, is left out of the register's cost total, and can't have a loss event.
- **Personal data breach.** Ticking **Personal data breach** opens a breach in **Data Protection → Breach Register** the first time the incident is saved with it: same title and severity, occurred and discovered dates, records affected, *notification required* ticked. The incident links to it (*Data breach record*) and the breach names its **Source incident**, shown in the register and the breach drawer. If a role named *DPO* or *Data Protection Officer* (or containing *data protection*) exists, a critical notification tells it; otherwise the hand-off is only in the activity trail. Picking the incident as the *Source incident* on a breach flags the incident too. The breach is created only while Data Protection is enabled.
- **Loss events.** **Create loss event** in the drawer's **Loss events** card adds a loss to **Operational Risk → Loss Database**, pre-filled from the incident: its cost as the gross loss, in your organisation's currency; occurrence and discovery dates; the handler as action owner; the root cause; its linked risks; and the business unit, when the incident's assets and risks point to exactly one. It needs *oprisk:write* and the Operational Risk module. The card lists the incident's loss events with gross and net loss.
- **Importing.** An incident spreadsheet's *occurred_at*, *detected_at*, *contained_at* and *resolved_at* take `2026-09-01` (00:00 organisation time) or a date and time (`2026-09-01T14:30`, or with an offset, `2026-09-01T14:30:00+05:00`). New columns: *customers_affected*, *records_affected*, *near_miss*, *personal_data_breach*, *is_reportable* and *regulator*. Exports write times with their offset, so a file round-trips.
- **Reports.** The report builder's incident report shows times in organisation time and has optional *Contained*, *Near miss*, *Personal data breach*, *Customers affected* and *Records affected* columns. An *Occurred to* or *Detected to* filter includes the whole of that day.
- **Known gaps.** The dashboard's incidents card doesn't show MTTD/MTTR yet, and the turnaround-time clock still starts when the incident was logged. The loss-event link opens the Operational Risk page, not the loss itself. The *from* filters in the report builder start at 00:00 UTC, not organisation time.

### KRIs

A key risk indicator now says exactly what it measures, where its number comes from, how it is judged, and who is told when it turns amber or red.

- **Definition.** The KRI form's **Definition** tab records the **definition**, the formula's **numerator** and **denominator** (leave the denominator empty for a count), the **data source**, the **data provider** (picked from users) and whether it is a **leading** or **lagging** indicator. **Frequency** now offers daily, weekly and fortnightly as well.
- **Thresholds.** The **Thresholds** tab sets the direction and its thresholds. None of them is pre-filled with 0.
  - *Higher is worse*: amber at or above the warning, red at or above the limit, so the warning must be below the limit.
  - *Lower is worse*: amber at or below the warning, red at or below the limit, so the warning must be above the limit.
  - *Within range*: green between the **lower** and **upper bound**, which are both required, with the lower below the upper. The bounds themselves count as inside. Outside the range the KRI is amber. It turns red once it is the **tolerance** or more beyond the nearer bound, or as soon as it leaves the range when no tolerance is set. There is no warning threshold. For example, an LCR kept between 110 and 150 with a tolerance of 10 is amber at 105 and red at 100 or 160.

  A save that breaks these rules is refused with the reason. Thresholds can stay empty only until the first value is recorded. After that, a KRI needs a warning or a limit, or a range if it is within-range. Switching a within-range KRI to another direction clears its bounds.
- **Appetite.** **Risk appetite** links the KRI to a risk category's appetite (set under Risk register → More → *Risk methodology…*). The drawer shows it with its appetite and tolerance scores.
- **Readings.** A reading can't be dated in the future. Only the latest-dated reading moves the current value and the status; an older reading goes into the history. A KRI without usable thresholds refuses readings until they are set. A within-range KRI shows its band under the value, with the reading marked on it.
- **Escalation.** The drawer's **Escalation** card holds one line for amber and one for red. Each names a person and/or a role, and the action they must take. When a reading moves the KRI up into amber or red (green to amber, or anything to red), a notification names the target and the action, e.g. *Escalate to Jane Doe and the CRO role: freeze outbound wires above PKR 10m*. If no escalation is set for that level, the notification names the owner instead. A reading that improves from red to amber raises nothing. The notice goes to the escalation's person and role (see *My Work and alerts*). Escalations, and every escalation raised, are recorded in the activity trail, and the live *KRI breach* alert names the red escalation.
- **Integration feed.** **Generate token** on the **Integration feed** card creates a token that a monitoring system or CCM connector uses to post readings without a user login. The token is shown once, so copy it then. Only a fingerprint of it (SHA-256) is kept, so it can't be shown again. **Replace token** issues a new token and stops the old one, and **Revoke** stops it. The integration sends:

  ```
  POST <API address>/api/v1/kris/<KRI id>/measurements/feed
  Authorization: Bearer <token>
  Content-Type: application/json

  {"value": 12.5, "as_of_date": "2026-09-12", "notes": "CCM run 42"}
  ```

  `as_of_date` is optional: it defaults to today and can't be in the future. A missing, wrong or revoked token gets `401`. The reply gives the new status (`green`, `amber` or `red`), the current value and any escalation level, and no names or history. The reading follows the same rules as one typed in and is recorded in the activity trail as **KRI feed**. A token belongs to one KRI, so each KRI needs its own.
- **Importing.** A KRI spreadsheet can carry *definition*, *numerator*, *denominator*, *data_source*, *data_provider* (a user's email), *indicator_type*, *lower_bound* and *upper_bound*. Escalations, the appetite link and feed tokens are set in the app.
- **Known gaps.** Escalation notifications aren't sent to the named person alone yet. Restoring an older version of a KRI from its version history also restores that version's feed token, so after revoking a token, generate a new one rather than restoring an old version. Feed tokens have no rate limit of their own.

### Policies

A policy now records who approves it, when it takes effect, what it replaces and who it applies to, and it shows who still has to acknowledge it.

- **Governance.** The policy form's **Governance & Applicability** tab records the **approving authority** (a board or committee from Governance), the **effective date** and the policy it **supersedes**.
- **Effective date.** It can't be earlier than the date the policy was last approved. A save that sets an earlier date is refused, and so is publishing a policy that has one. Left empty, the effective date is set to the publication date when the policy is published.
- **Supersedes.** Pick the policy this one replaces. A policy can't supersede itself, or a policy that already replaces it directly or further down the chain. When this policy is published, the one it supersedes is **retired** automatically, and that policy's activity trail reads *Retired: policy POL-001 — superseded by POL-009 (published)*. If an already published policy is pointed at another one, that one is retired at once. The drawer shows **Supersedes** and **Superseded by** chips.
- **Applies to.** Pick the **business units** and **roles** the policy applies to.
- **Acknowledgement status.** The drawer's **Applicability & acknowledgement** card lists the people asked to acknowledge the policy, with *Yes* and the date or *Pending*, and a count (*7 of 12 acknowledged*). These are the members of the policy's roles, or every active user when the policy names no role. Business units don't narrow the list, because people aren't linked to business units in NexusLine; units are recorded for reporting only. Acknowledgements from people outside that list are counted separately.
- **Requirements.** Requirements picked on the **Links & Relations** tab are saved as links between the requirement and the policy, so they show on the requirement too.
- **Importing.** A policy spreadsheet can carry *approving_authority* (a committee's name or reference), *effective_date*, *supersedes* (a policy's reference or title), and *business_units* and *roles* (comma-separated names). Importing a policy that supersedes another doesn't retire it; publishing the new policy does.
- **Known gaps.** Nobody is reminded to acknowledge a policy yet: the status list shows who is outstanding, but no campaign or reminder is sent.

## 3g. Working day to day

Added in September 2026: tools that help a bank use the platform day to day, not only record things in it.

### Organisation setup and modules

A new organisation starts at **Organisation setup** (`/onboarding`), which an administrator sees after signing in until it is finished. Five steps, each saved as you go:

1. **Locale** — currency, timezone, date format and the month the financial year starts.
2. **Frameworks** — install the standards you are examined or certified against. SBP ETGRM, SBP Cyber Security, SBP BCP, SBP Outsourcing and ISO 27001 are marked as recommended; control frameworks also create their controls.
3. **Modules** — choose the specialist modules your teams use first. Eight are pre-selected for a Pakistani bank (operational risk, internal audit, business continuity, business impact analysis, outsourcing, regulatory change, board & committees, AML). Tick *We are an Islamic bank* to add Shariah Governance. The risk register, controls, compliance, policies, issues and incidents are always on.
4. **Team** — invite the people who own records; segregation of duties means someone other than you must approve what you submit.
5. **Finish** — opens the dashboard.

A module that is switched off disappears from the sidebar and its pages and API refuse requests with *switched off for your organisation*. An administrator changes the choice at any time from **Settings → Organisation settings → Organisation setup & modules**. The choice works within the licence: a module the licence doesn't cover can't be switched on. Organisations that existed before September 2026 keep every licensed module until an administrator chooses otherwise.

### Finding your way: navigation, drill-through and bulk edit

**A sidebar for your job.** The sidebar, your favourites and recents, and the ⌘K / Ctrl-K palette show only pages you can open. Each link needs the permission its page reads with: the Risk Register needs *risk:read*, Users & Roles *user:read* or *role:read*, Organisation Settings *settings:manage*, and so on. A group with nothing you can open disappears. General Settings (where you set up two-factor authentication), Saved Filters and Import / Export stay for everyone. Hiding a link is not what protects the data: the server still refuses anything your roles don't allow.

**Groups open for your role.** Which groups start open depends on the work your roles do:

| You are | Recognised by | Opens |
|---|---|---|
| First line | a role named *first line*, *champion*, *owner*, *business*, *branch* or *operations*; or you can edit registers but hold none of *risk:write*, *risk:accept*, *compliance:write*, *control:write* | the groups holding the registers you can edit, and My Work |
| Second line | a role named *admin*, *risk*, *compliance*, *GRC*, *CISO*, *CRO*, *CCO* or *second line*; or you hold one of those four permissions | Risk Management, Controls & Assurance, Compliance |
| Internal audit | a role named *audit*; or you can edit internal audit and nothing second-line | Controls & Assurance, where Internal Audit is |
| Board and viewers | a role named *board*, *viewer*, *director*, *executive* or *read only*; or you can only read | Program, where Reports & KPIs is. The Dashboard is always at the top |

Role names are checked first, in that order (audit, first line, second line, board), then permissions. A group you open or close yourself stays that way. Your choices, favourites and recents are now kept per person on this browser. **Reset**, beside *Modules*, hands the choice back to your role. The group holding the page you are on always opens.

**Every number opens its list.** On the dashboard, a count opens its register filtered to exactly those rows. The count and the list use the same rule, so the numbers match. For example:

- *98 controls never tested* opens the Control Catalog filtered to *Never tested* (`/controls?assurance=not_assessed`). Tests overdue, due in 30 days and failed last test each open their own filter, and so does each part of the control-assurance bar.
- *Risks above tolerance*, *risk reviews overdue* and *risks with treatment past due* open the risk register filtered (`/risks?appetite=breach`, `?review=overdue`, `?treatment_overdue=true`).
- *Open incidents* opens every incident not yet resolved or closed, including those in triage, under investigation or contained. The severity counts and *regulator-reportable* narrow it further.
- *Issues past due*, *policy reviews overdue*, *critical* third parties and third-party *reviews overdue* open their registers filtered.
- A framework's name opens its compliance view. KRIs open the Operational Risk page; choose the KRIs tab there.

The filters live in the address bar. When you change one, the link changes with it, so copying the link sends exactly what you are looking at, and saved views remember filters too. The same filters sit on the registers:

- **Control Catalog:** *Assurance*, *Test status* and *Key controls*
- **Incidents:** *Open — not resolved or closed*, and *Reportable*
- **Policies:** *Review overdue*
- **Third Parties:** *Review overdue* and *Criticality*

Three dashboard figures changed so that each one matches its list:

- An issue marked *remediated* no longer counts as open. The register never counted it as open.
- The treatment line now counts risks, not treatment actions, because it opens the risk list.
- The third-party figure is now labelled *reviews overdue*. It counts third parties whose next review date has passed.

**Bulk edit.** Tick rows on the Control Catalog, Issues, Incidents, Policy Management, Third Parties, IT Assets or Information Assets, then choose **Edit N ▾**:

- **Set owner.** On incidents this is the assignee, on third parties the relationship owner, and on assets the owning business unit.
- **Set next review date.** On controls, the next test date.
- **Set review frequency.** On controls, the test frequency.
- **Set category.** Picked from the register's own list: on controls the classification, on incidents the incident type.
- **Set status.** Controls, issues, incidents and third parties.

Before anything changes you see a summary. Afterwards one message says what happened, such as *Updated 38; 2 skipped: archived*. A record is skipped whole, never half-changed, when it is archived, already has the value, or a rule says no:

- A planned or retired control has no test clock, so it gets no next test date. A new test frequency re-derives the next test from the last one. Making a control implemented or operational starts its clocks, and retiring it stops them, just as when you edit one control.
- An issue moves only between *Open* and *In progress*. Closing still takes **Validate** and **Close** on each issue, and a closed issue can only be reopened from the issue itself.
- Moving incidents to *Contained* or *Resolved* records the current time where that time is blank. An incident whose timeline would then be out of order is skipped, with the reason.
- A policy's status follows its approval lifecycle, so policies have no bulk status. A new review frequency sets a policy's next review from today; for risks, from the last review.
- Approval state is never bulk-edited.

You need permission to edit the register. Every record changed gets its own entry in the activity log, and all the entries from one run share a batch id.

**Map to requirements.** On the Control Catalog, **Edit N ▾ → Map to requirements…** links every selected control to the framework clauses you pick. Links are only added, never removed, and a control already linked to all of them is skipped. Mapping is not assurance: a clause counts as assured only once a mapped control passes a reviewed test.

### Risk candidates and hierarchy

**Generating risks fills a queue, not the register.** *Generate risks from assets* (Risk Register → More, or the IT Assets and Information Assets pages) still pairs each asset with the scenarios that apply to it, but the preview now groups the pairs into **candidates**: one per scenario, process and business unit, carrying every asset it covers and scored at its most exposed asset. Forty servers that run Payments in Retail Banking make one candidate, *Ransomware encrypts Payments assets in Retail Banking*, not forty risks. Untick what does not apply, adjust a title or a score, and press **Send N proposals to the queue**. Nothing reaches the register until someone accepts it. The result says how many candidates were created, how many pairs were merged into a candidate (including ones already waiting from an earlier run), and how many were skipped because the register already covers them, with a link to the queue.

**How pairs are grouped.** Two pairs are the same candidate when they share a scenario, a process and a business unit:

- **Process**: the asset's linked process. When it has several, the first alphabetically.
- **Business unit**: the asset's owning unit (*Owner* on the asset form). When it has none, the unit that runs its process.
- An asset with neither is grouped by asset class, so unplaced IT assets make one candidate per scenario and unplaced information assets another. Give assets an owner and a process and the candidates follow your organisation.

A pair is **skipped as already in the register** when a candidate with the same scenario, process and unit was accepted and its risk is still live; when a risk written by the old generator (one risk per asset, titled after the scenario and the asset) covers the same scenario, process and unit; or when a live risk has the same title. A pair **joins** a candidate still waiting with the same grouping: the candidate gains the asset and keeps the worse score. If the last candidate for that grouping was **rejected**, the preview shows the reason and leaves it unticked; tick it to send it again.

**Risk candidates** (Risk Management → *Risk candidates*, `/risk-proposals`) lists candidates grouped by scenario, with their assets, inherent score, and the controls the scenario names that your catalogue has (and how many it does not). Tabs show how many are pending, accepted, rejected and merged; filter by scenario, business unit, text, or one generation run. Tick pending candidates, then:

- **Accept** turns each one into a **draft** risk through the register's normal create path: source *Generated*, level 3 (scenario), linked to its live assets, its business unit and process, the assets' own controls plus the scenario's controls found in your catalogue, the scenario's threat and vulnerability, and the framework clauses those controls satisfy. Optionally pick a category, an owner and a **parent** (a level 1 or 2 risk) for all of them. The scores are provisional: as for any draft, an assessment rationale is needed before the risk leaves draft. A candidate whose assets were all deleted since cannot be accepted; reject it. When one candidate fails, the others are still accepted and the failure is listed with its reason.
- **Merge** keeps the candidate you pick. The others' assets and control references move to it, it takes the worst of their scores, and they are marked merged. Later generation runs for their scope add to the one you kept, or are skipped once it is in the register.
- **Reject** needs a reason. It is kept on the candidate and shown the next time the same scenario comes up for the same process and unit.

Accepted candidates link to the risk they became; every candidate shows who decided, when, and the note. Each decision has its own entry in the activity log. Viewing needs *risk:read*; sending, accepting, merging and rejecting need *risk:write*.

**The hierarchy.** A risk can sit at **level 1 (enterprise)**, what the board reads, **level 2 (category)**, or **level 3 (scenario)**, what practitioners assess and where accepted candidates land. The risk form's *General* tab has **Hierarchy level** and **Parent risk**; the parent search offers only risks at a higher level. The server refuses, with the reason:

- a parent that is archived, is the risk itself, or sits below the risk (a loop);
- a parent that is not above its child (level 1 is above 2, which is above 3), a parent that has no level yet, or a parent at level 3, since scenarios are the bottom of the hierarchy;
- a parent for a level 1 risk;
- a new level for a risk that would leave one of its children at or above it. Move or re-level the children first.

With a parent and no level, a risk sits one level below its parent. If a risk's parent is archived later, the risk keeps the link and can still be edited; it shows *Its parent was archived* until you pick another parent or clear it.

In the register, the **Level** column and filter (including *Not placed*) sit beside the others; *Parent* and *Below* columns are in the column chooser, and a *Below* count lists the risks directly under that risk. The record's **Hierarchy** card shows its level and parent, the risks directly below as chips, how many sit below it in all, the worst exposure below it (residual when assessed, otherwise inherent, as the dashboard ranks) and the worst residual, counts by severity, how many are above tolerance, and **List the risks directly below**. **List | Hierarchy** at the top of the register switches to a tree: **Board view (L1–L2)** shows enterprise and category risks, each with the number of risks below it and its worst exposure counted at every level, including scenarios the view does not show; **Full tree (L1–L3)** adds the scenarios. The count of risks not yet placed opens them in the list.

**More register filters.** The toolbar also filters by **review date** (*overdue*, *due in 30 days*), **appetite** (*within appetite*, *elevated*, *above tolerance*, with each risk compared with its own top-level category's appetite, as on the dashboard), **controls** (*has controls* or *no controls*, counting live controls only) and **treatment overdue** (a risk that is not accepted or closed and has an open treatment action past its due date, or has no actions and a treatment deadline in the past). These are the filters the dashboard's counts open, and like the level and parent filters they live in the address bar.

**Known gaps.** The register PDF does not apply the level, review, appetite, controls and treatment filters yet, so the export is the list without them. The delete confirmation does not list the risks below the one being deleted; they keep pointing at their archived parent. *Review risks with no live links* does not count a parent or child as a link. Risk spreadsheets cannot carry a level or parent yet, and the dashboard heat map does not switch between levels. Risks written by the old generator are recognised by their titles, so a renamed one is not recognised; reject or merge the candidate it causes. A candidate cannot be edited in the queue: adjust the title and scores in the preview before sending, or on the risk after accepting it.

### Board packs

A board pack is a committee's view of risk, assurance and compliance for a period, kept as the PDF and the spreadsheet the committee actually saw.

- **Generate.** Open a committee under **Board & Committees** and, in its **Board packs** card, click **Generate pack**. You can pick the meeting it is for, a period (leave it blank for the financial quarter to date; quarters run from the month your financial year starts, under Settings → Organisation) and the sections. **Generate** builds it at once. You need *governance:write*.
- **What it contains.** A cover (organisation, committee, meeting, period, when and by whom it was generated), then:
  - *Executive summary*: the governance-health score and how much of it is scored, what the score is made of, and what needs a decision or is overdue.
  - *Appetite by category*: within appetite, elevated and above tolerance for each risk category.
  - *Top risks*: the highest current exposures, with their trend since the period began.
  - *Risk movement*: risks added, closed and re-assessed in the period, and how many re-assessed risks moved up or down.
  - *Control assurance*: effective, partially effective, ineffective and not tested; the reviewed tests that failed in the period, with the issue each raised; and how many failed tests still await review.
  - *Compliance by framework*: compliance frameworks only.
  - *Open issues* by severity, with how many are overdue and how many had their due date moved.
  - *Incidents* detected in the period: the regulator-reportable ones, the share notified to the regulator on time, and mean time to detect and to resolve.
  - *Key risk indicators* at red and amber.
  - *Third parties* rated critical or high, and certifications expired or expiring within 60 days.
- **The same numbers as the dashboard.** The health score, appetite, top risks, control assurance and compliance come from the dashboard itself. Those figures, and issues, KRIs and third parties, are as at the day the pack is generated. Risk movement, failed tests and incidents cover the period. The cover says so.
- **Trend.** A top risk not re-scored since the period began reads *Unchanged*. One re-scored during the period is compared with its score when the period began, taken from the risk's history (*Up from 12*, *Down from 20*). A risk added in the period reads *New in period*, and one with no score recorded before the period reads *No earlier score*.
- **Files.** Both files are stored with the meeting you picked, or with the committee when you picked no meeting (they then also appear under the committee's Files). **PDF** and **XLSX** on each pack download them. The PDF lists up to 50 rows per table; the spreadsheet has one sheet per section and lists every row.
- **Automatically before each meeting.** On the committee form (**Edit**), *Generate the board pack automatically* takes a number of days, from 1 to 90. The scheduler then generates the pack for each **scheduled** meeting of an active committee once the meeting is that many days away, once per meeting. A pack generated before that window opened doesn't count, so a draft made weeks earlier is replaced by a fresh one. Automatic packs cover the financial quarter to date and name *Scheduler* as their author. Leave the field blank to generate packs by hand.
- **When it fails.** A pack that can't be built stays in the list as *Failed*, with the reason, and leaves no files behind. Generate it again once the cause is fixed.
- **Trail.** Every pack, by hand or automatic, is recorded in the committee's activity trail (automatic ones by the system), and so is a change to the automatic setting.
- **Also fixed.** Editing a meeting, or adding a decision or action to one, failed with an error before this release.
- **Known gaps.** A pack for a past period still shows the position figures as at the day it is generated; only movement, failed tests and incidents follow the period. A pack can't be deleted, because it is the record of what was presented. The pack doesn't include the committee's own decisions and actions.

### Crosswalks

A crosswalk records that two clauses of different frameworks ask for the same thing, for example ISO 27001 A.8.5 and PCI DSS 8.4. A control linked to one then suggests the other: **Suggested clauses** on a control follows crosswalks to the equivalent clauses.

- **Crosswalk view.** On **Compliance**, pick a framework and open the **Crosswalk** tab, then choose the framework to crosswalk it with. **Recorded crosswalks** lists the pairs already linked. **Remove** unlinks a pair.
- **Suggestions.** **Suggested crosswalks** lists candidate pairs, each with its reasons and a strength:
  - **Same topic.** The topic table behind *Suggested clauses* lists, for each topic, the clauses each library framework has for it, main clause first. Two clauses listed for the same topic are suggested when at least one of them is its framework's main clause for that topic. The pair is *Strong* when both are (*Multi-factor authentication: A.8.5 ≡ PCI 8.4*) and *Likely* when one is. Two clauses that only touch a topic are never suggested.
  - **Same control.** Two clauses implemented by the same control are suggested when that control is specific: linked to no more than two clauses in each framework. A control mapped to many clauses, such as an information-security policy, suggests nothing on its own. A topic match that a shared control confirms is *Strong*.
  - Only clauses that exist in your installed copy of each framework are suggested. A framework you built yourself gets suggestions from shared controls only.
- **Accept.** Strong suggestions start ticked. Tick or untick them, narrow the list with *Strong only*, then **Accept selected**. Nothing is linked until you accept. Each accepted crosswalk is recorded in the clause's activity trail, naming the clause it was linked to, and so is each removal. Accepting or removing needs *compliance:write*; seeing suggestions needs *compliance:read*.
- Crosswalks can still be edited one requirement at a time, on its **Mappings & Crosswalks** tab.

### Continuous monitoring feeds

A monitoring tool, such as a SIEM, an identity platform or a script, can send the result of a control check to NexusLine through a connector, without a user login.

- **Token.** On **Integrations & CCM**, open a connector. In its **Monitoring feed** card, **Generate token** creates the token and shows it once, with an example request, so copy it then. Only a fingerprint of it (SHA-256) is kept. **Replace token** issues a new token and stops the old one, and **Revoke** stops it. Setting the connector's status to *disabled* also stops the feed, and archiving the connector revokes its token. Issuing or revoking a token needs *ccm:write* or *integration:manage*.
- **Sending a result.**

  ```
  POST <API address>/api/v1/connectors/ingest
  Authorization: Bearer <token>
  Content-Type: application/json

  {"control_reference": "A.8.5", "result": "failed",
   "observed_at": "2026-09-12T10:00:00+05:00",
   "summary": "3 privileged accounts without MFA",
   "details": {"accounts": ["svc-backup", "admin2", "ops-root"]},
   "evidence": {"title": "MFA coverage report", "url": "https://siem.example/r/42", "valid_until": "2026-12-31"}}
  ```

  - `control_reference` (or `control_id`) names the control, and `result` is `passed`, `failed` or `passed_with_exceptions`.
  - `observed_at` is when the check ran. A time with no offset is taken in your organisation's timezone. It can't be in the future; a clock two minutes fast is tolerated.
  - `pass_rate` (0 to 100) is required with `passed_with_exceptions`. `test_reference` names the test to record the run on when several match. `details` (up to 50,000 characters of JSON) and `evidence` are optional.
  - A missing, wrong or revoked token gets `401`, whatever the reason. An unknown control, a time in the future or a bad field gets `422` with the reason.
- **What a result becomes.**
  - **Evidence on the control.** It is collected on the day the check ran and marked valid, titled from the evidence you send or from the summary, with the details in its description. It shows in the control's evidence and the Evidence register, and a person can attach it to a test they record.
  - **A run of the connector's test.** When this connector has exactly one active continuous control test whose *Control reference* matches the control (or the one `test_reference` names), the result is recorded as a run of it. The latest run rolls up onto the test's last result and pass rate. *Passed with exceptions* is recorded as a pass with its pass rate, and the findings say *Passed with exceptions*. With no such test, only the evidence is kept and the reply says why.
  - **An alert when it failed.** *Continuous monitoring failed: A.8.5 Secure authentication* is critical for a key control and a warning otherwise, and names the control owner. A check that keeps failing raises one alert per control and connector per day.
  - **Never a rating.** A result never changes the control's effectiveness. That still moves only when a person records a test and another person reviews it.
- **Trail.** Every result is recorded in the activity trail as **Connector** followed by the connector's name: on the connector, the evidence, the control and the test. The **Monitoring feed** card shows when the last result arrived, how many arrived in the last 30 days, and the latest results with their control, result and test run. The connector's *Last sync* moves to the day of its latest result.
- **Known gaps.** There is no rate limit beyond the token. The alert goes to the control's owner, or to the whole organisation when the control has none.

### My Work and alerts

Alerts now go to the person who has to act, every alert opens the record it is about, and **My Work** (`/my-work`) lists everything waiting for you in one place.

**My Work.** It is the first link in the sidebar. Each kind of work has its own section with a count, overdue items first:

- **Decisions waiting for you.**
  - *Approval requests* you can decide. You hold *workflow:approve*, you didn't raise the request, you haven't decided it already, and it names you, one of your roles, or nobody in particular.
  - *Records submitted for review* that you may approve. Records you entered or submitted aren't listed, and neither are records going through an approval route: their stages appear as approval requests.
  - *Control tests to review* (*control:test*). Tests you performed, recorded or edited aren't listed.
  - *Issue fixes to validate* (*issue:write*). Every action on the issue is done, and you neither own nor raised it.
  - *Due-date extensions to approve* on serious issues. Extensions you asked for aren't listed.
- **Things you own that are overdue or due in the next 14 days.**
  - Risk treatment actions, issue actions and issues you own.
  - Incidents assigned to you, dated by their turnaround-time deadline.
  - Tests of controls you own or operate, and tests a reviewer returned to you.
  - Reviews of risks, policies and third parties you own, and attestations due on other records you own.
  - Attestations waiting for your independent confirmation, under *Attestations to confirm* — a high-stakes record someone has certified, which only counts once a second person signs it (owed within a week of the certification).
  - KRI readings you supply. You supply a KRI's readings when you are its data provider, or its owner when it names no provider. A reading is due one frequency after the last one and is listed from three days before.
  - Actions on open RCSAs where you are the action owner.
- **Policies to acknowledge.** Published policies that name one of your roles, or no role at all, and that you haven't acknowledged.

Every row opens its record. Two things can be done from the row itself:

- **Acknowledge** a policy. You confirm that you have read it.
- **Mark done** a treatment action you own. Its completion date is today and the risk's treatment deadline is recalculated. The change appears in the risk's activity log. Someone who can edit risks can do this for any action.

A section shows up to 50 rows and its count is the full number. KRIs and RCSA actions are listed only while Operational Risk is switched on.

**Where you land.** After signing in, people who don't administer the organisation (no *settings:manage* and no *user:write*) land on My Work. Administrators land on the dashboard, or on Organisation setup until it is finished. A link you open while signed out, such as one in an alert e-mail, opens after you sign in, whether by password, two-factor authentication or single sign-on.

**Who an alert goes to.**

- **The record's accountable person, where one is on file:**
  - a risk's owner, for reviews, tolerance breaches and acceptances running out;
  - a treatment action's owner, else the risk's treatment owner, else the risk's owner;
  - a control's owner and operator for an overdue test, and its owner for maintenance;
  - an issue action's owner, else the issue's owner;
  - an incident's assignee, for its regulatory reports;
  - a KRI's owner, plus the person and role its red escalation names;
  - a policy's owner, and a third party's relationship owner (reviews and certificates);
  - an RCSA's assessor, and the owner of a record whose attestation is overdue.
- **Registers that still hold the owner as text** (continuity plans, projects, access reviews, audit findings, AML cases). The alert goes to the user whose e-mail or full name matches that text, when exactly one does. Otherwise it goes to the record's approval owner.
- **Approval requests.** The alert goes to the approver the request names, a person (by e-mail or full name) or a role. A request that names nobody in particular, or names the person who raised it, goes to every role that can approve requests. So does a request whose named person or role can't approve requests, as well as to them, so it never waits unseen.
- **Turnaround time.** A turnaround-time breach goes to the record's owner and to the escalation role set for it under Turnaround Time.
- **Data protection.** Gaps in a processing activity go to its approval owner, else the DPO role.
- **KRI escalations.** An escalation notice goes to the escalation's person and role, or to the KRI's owner when no escalation is set.
- **Two new alerts.** *Issue action overdue* goes to the action's owner. *Due-date extension awaiting approval* goes to the roles that may approve issues.
- **Nobody on file.** An alert whose record names nobody who can be matched goes to everyone, as before, so nothing is lost.

**The bell and the notifications page.** You see alerts addressed to you, to a role you hold, and to everyone. **Addressed to me** narrows the list to the first two. Each alert says how it reached you: *For you*, *Role: CRO* or *Everyone*. An alert that reaches you twice, for example as a risk's owner and through the escalation role, is shown once. The bell counts what you haven't seen, and turns red when some of it is addressed to you. Grouping (*12 controls have tests overdue*) now counts your own alerts, not the organisation's. **Open** on an alert opens the record itself, not just its register. When your organisation upgraded, alerts that everyone had already been shown were given to their owners without counting as new.

**E-mail digests.** Each person is e-mailed only the alerts addressed to them, to their roles and to everyone, raised since their previous digest. Each alert links to its record. If there is nothing new, no e-mail is sent. The first digest after the upgrade covers only the last two scheduler runs, so alerts already e-mailed aren't sent again. Each digest is recorded in the activity log (*Emailed … a digest of 4 alert(s)*). A turnaround-time breach reaches the escalation role through its members' digests, and the subject says so. The separate turnaround-time escalation e-mail has been replaced by this.

**Approve or reject from the e-mail.** When a request is waiting for your decision, the e-mail has **Approve** and **Reject** buttons. That is the digest, and, when outbound e-mail is set up, a *Decision needed* e-mail sent as soon as the request is raised. A button opens a page that shows the request. Nothing is decided until you press the button on that page, because mail scanners open links. A rejection needs a reason. The decision follows the same rules as on the Approvals page:

- the person who raised the request can't decide it;
- you can decide a request only once;
- an approval route moves on to its next stage.

The activity log records it as *Decided by email*. Each link is for you alone, works once and expires after 72 hours. A link that has been used or has expired, or whose request is already decided, says so on the page. Only a fingerprint (SHA-256) of each link's token is kept.

**Known gaps.**

- The personal-data-breach hand-off goes to the DPO role, a finished approval route to the person who started it, an expired risk acceptance to the risk owner, and a continuous-monitoring failure to the control owner. Each falls back to the whole organisation when nobody is named.
- **Deciding from e-mail** skips two-factor authentication. Where policy requires 2FA for every approval, the administrator sets `EMAIL_ACTIONS_ENABLED=false`: no links are sent, and links already sent stop working.
- KRI alerts open the Operational Risk page on its RCSA tab, so choose KRIs there. Approval alerts open the Approvals list rather than the single request.
- Deciding from an e-mail relies on the mailbox and doesn't ask for two-factor authentication.

## 4. How the sidebar is organized

**My work** and the **Dashboard** sit at the top. Below them the sidebar groups the modules the way eramba does:

| Group | Pages |
|---|---|
| **Program** | Reports & KPIs, Report Builder, Strategy & Goals, Projects, Approvals, AI Assist |
| **Governance** | Business Units, Processes, Legal Register, Board & Committees, Policy Management, Delegation of Authority, Users & Roles |
| **Asset Management** | Information Assets, IT Assets, Data Privacy (RoPA), Data Protection |
| **Risk Management** | Risk Register, Risk candidates, Operational Risk, Scenario & Capital, Model Risk, Risk Quantification, Threat Library, Risk Exceptions |
| **Third-Party Risk** | Third Parties, Outsourcing & Cloud, Vendor Assessments, Questionnaires |
| **Controls & Assurance** | Control Catalog, Evidence, Awareness Training, Internal Audit |
| **Compliance** | Compliance Management, Framework Library, Regulatory Change, ICFR, Declarations, ESG / Green Banking |
| **Financial Crime** | AML / CFT, Fraud Risk, Whistleblowing |
| **Shariah Governance** | a single page |
| **Security Operations** | Incidents, Vulnerabilities, Business Continuity, Business Impact Analysis, Access Reviews, Issues & Actions |
| **Settings** | General Settings, Organisation Settings, Integrations & CCM, Custom Fields, Lookups & Dropdowns, Status Rules, Turnaround Time (TAT), Approval Workflows, Saved Filters, Import / Export, Webhooks, Single Sign-On, Activity Log, and Organisations for platform administrators |

The chapters of this guide below still follow the older seven-section grouping (Overview, Risk, Compliance, Governance, Organization, Operations, System); use the table above, or ⌘K / Ctrl-K, to find a page. You see only the pages your permissions allow ([Administrator Manual, Appendix C](admin-guide.md#appendix-c--sidebar-map-every-page-and-the-permission-it-needs)).

**Not seeing a module described in this guide?** Installations are licensed per module — the sidebar only shows what your license enables (for example, conventional banks typically don't license **Shariah Governance**; Islamic banks do). Your organisation's administrator can also switch licensed modules off for your organisation. Administrators can see the full module matrix — *on / hidden / unlicensed* — under **Settings → General Settings → System → Modules**. Enabling an additional module is a license update from your vendor, not a reinstall: your data model already supports every module, so nothing is lost or migrated when one is switched on later. A licensed module can also be hidden by the deployment's `DISABLED_MODULES` setting; opening its URL directly shows a "module not enabled" notice, and its API rejects calls, so hiding a module genuinely turns it off rather than just removing the menu entry.

---

## 5. Overview

### Dashboard (`/dashboard`)
**Purpose:** Read-only executive snapshot of live risk, control and compliance posture — where administrators land after signing in (most other people land on My Work).
**What's on it:** the Governance health score with its four weighted components and the *Needs a decision or is overdue* queue; a six-tile KPI strip (above tolerance, control assurance, compliance assured, open incidents, KRIs breaching, tests overdue); the risk matrix (residual by default, inherent on the toggle) with Top risks; control assurance and compliance as stacked bars; incidents and KRIs; risks by segment; and Movement for the period. Every number opens the register filtered to exactly those rows. See [3c. The dashboard](#3c-the-dashboard) for how each figure is worked out.
**Key action:** the 30 days / Quarter / YTD toggle, and the **Executive summary** PDF export.
**Note:** the dashboard's content is fixed — for a customizable dashboard, use Reports & KPIs instead.

### Report Builder (`/report-builder`)

**Purpose:** the report system. Every module used to offer one fixed export; this is where you ask the organisation's own questions — *critical risks in Digital Banking with no controls*, *controls not tested this year*, *regulator-reportable incidents this quarter* — and get the answer on screen, as a PDF for the committee pack, or as Excel for the analyst.

**How to use it:**
1. **Subject** — Risks, Controls or Incidents. Everything below is generated from what the subject declares, so a subject you cannot read is simply not offered.
2. **Filters** — every one compiles to a database query, so a report over the whole register costs one query, not a scan. Risks filter by business unit, process, asset, owner, category, status, inherent and residual severity (bands follow *your* matrix — "critical" means 15–25 on a 5×5 and 57–100 on a 10×10), position against appetite, treatment strategy, whether controls are linked, review overdue, next-review and created date ranges, and free text. Controls filter by status, effectiveness, type, owner, the risk they mitigate, the asset they protect, and test dates. Incidents by status, severity, category, assignee, regulator-reportable, resolved, affected asset, failed control, and occurred/detected dates.
3. **Columns** — toggle chips; the order you choose is the order in the file. Reset returns the subject's default set.
4. **Sort**, and for risks whether the PDF should carry a **detail page per record** (controls with effectiveness, assets with classification, both ratings, treatment, acceptance history).
5. **Run report** shows the rows with a summary — by severity, by status, against appetite — computed over *everything that matched*, not just the page you are looking at.
6. **Export** PDF, Excel or CSV. The PDF states its parameters on the cover and goes landscape when the columns need it. The Excel has a **Parameters** sheet — subject, every filter, who ran it and when, the summary counts — because a spreadsheet that circulates without its parameters becomes "the risk register" in someone's inbox; with them it is provably *critical risks in Digital Banking as at 5 September*.
7. **Save** the question with a name. Saved reports sit in the left rail; one click re-runs them live or exports them in any format. Shared reports are visible to everyone with access to the subject — only the question is shared, and each reader sees the records they are permitted to.

**What it will not do:** hand you more than 10,000 rows in one file (it asks you to narrow the filters instead), or let a report reach a module you lack read permission for — running a risk report needs `risk:read`, exactly as the register does. Every export is written to the activity log: who, which report, which format, how many rows.

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
**Purpose:** The platform's central qualitative + quantitative (FAIR) risk log.
**How to use it:** Create a risk → **General** tab (title, category, owner) → **Assessment** tab (inherent likelihood/impact, plus optional FAIR fields: annual loss frequency, single loss expectancy → auto-computed ALE) → **Links & Relations** tab (the **business units and processes** this risk sits in, then Assets, Controls, Threats, Vulnerabilities, Policies, Incidents) → **Review** tab (frequency). Set your org's **Appetite/Tolerance** thresholds once from the settings panel on this page — every risk is then banded against it.
**Status flow:** `draft → assessed → treatment_planned → treatment_in_progress → accepted → closed`.
**Key actions:** the page head holds three controls — **Export** (Register PDF for whatever the register is scoped to, or CSV of everything), **More** (import from your existing register, download the import template, generate risks from assets, clean up orphans, and the risk methodology), and **Add risk**. The segment scope — business unit, process, asset, status — sits in the table's own toolbar beside the search box, and the current scope plus the appetite and tolerance thresholds read as one line on the view-tabs row, with **Methodology** opening the appetite/tolerance and matrix editor in a side panel.
**Connects to:** the platform's hub — Assets, Controls, Threat/Vulnerability library, Policies, Incidents, Goals, Vendors, and optionally a Risk Quantification record.

#### Assessing by segment, not just by asset

Banks do not convene a risk workshop around an asset; they convene one around a **segment** — Digital Banking, Trade Finance, Branch Operations — and the assets are what that segment happens to run on. So a risk links to **business units** and **processes** as well as to assets, and the bar above the register narrows everything to one of them.

Choosing a segment scopes the whole page, not just the table: the counts, and — this is the part that matters — the **Register PDF**. Exporting while scoped gives you that segment's risks and nothing else, with the scope printed on the cover so a filtered pack circulating on its own can never be mistaken for the bank's total exposure.

Both links are many-to-many on purpose. "MFA is not enforced" genuinely belongs to Retail and Corporate at once; forcing a single owner would either duplicate the risk or hide it from one of them.

> **Importing an existing register?** Your spreadsheet almost certainly already has a *Department*, *Division*, *Segment* or *Business Process* column. The importer recognises all of those and links the segment as it loads, so a segment-scoped assessment works on day one rather than after someone re-tags several hundred rows by hand. Deliberately ambiguous headings — "Branch Manager Signature", "Unit Price" — are reported unmapped rather than guessed, because a wrong silent mapping is worse than none.

#### From framework to controls to risks — the loop

Install a **control framework** — ISO 27001 (Annex A), CIS Controls v8, NIST 800-53, PCI DSS, SBP Cybersecurity — from the Framework Library and, by default, its clauses arrive in the **Control Catalogue** as controls, each linked to the clause it came from: *A.8.5 Secure authentication* is a control, not just a line in a checklist. Every one starts *Not assessed* / *Planned*, because a freshly installed catalogue must not grant residual credit until somebody has actually tested something. If a control with that reference already exists it is linked, not duplicated, so an organisation that built its own catalogue keeps it. Untick *Also create its controls* on the card to install the clauses alone. Management-system frameworks (ISO 31000, GDPR, Basel) have clauses but no controls and never create any.

Every scenario in the risk library knows which controls address it — *credential compromise* → `A.8.5, A.5.17, A.5.16` in ISO terms, `CIS 6.3, 6.4` in CIS terms, `CS-3.3, CS-3.2` in SBP terms. When **Generate risks** proposes a risk, it resolves those references against *your* catalogue and pre-links whatever it finds, together with any control already recorded as protecting that asset. What it cannot find is shown in amber on the proposal — *not in your catalogue: CIS 6.3* — rather than dropped, so the gap is visible: install that framework and the next run links them. Nothing is written until you press Create.

The result is the loop the client asked for: install a framework → controls appear → generate risks → each arrives with its mitigating controls **and is linked to the clauses those controls satisfy** → test a control → its effectiveness changes → every linked risk's **suggested residual** moves → the compliance **gap analysis** shows which clauses still have no working control behind them. The system maps; a person judges.

Three rules make that loop honest:

- **Recording a control test sets its effectiveness.** *Passed* → effective, *failed* → ineffective, and the tester can say *partially effective* explicitly when a pass came with findings. The change is written to the activity log. A test scheduled but not yet performed changes nothing. Until a control is tested, the residual proposal says *no credit — rated not assessed* and residual equals inherent, which is exactly what an auditor would insist on.
- **A clause is assured by a working control, not by a mapped one.** Coverage has four states — *No controls*, *Mapped, not tested*, *Controls failing*, *Assured* — and only *Assured* (a mapped control that is effective or partially effective) counts. So a freshly installed framework with 93 untested controls is not "covered"; it is 93 clauses waiting for tests, and the gap analysis says so. A clause marked *not applicable* is never a gap.
- **Generated risks link to their clauses.** Because scenario → controls → clauses is known, a generated risk is linked to every clause its controls satisfy. Open a clause in Compliance and its risks are there; the register's *Compliance requirements* column shows a risk's clauses. Risks you create by hand keep the clause links you choose.

> Installed the scenario library before this existed? Run **Install library** again under Threat Library → Scenarios. It adds the control mapping to scenarios that have none and leaves any you edited alone.

#### One risk per asset, not one rating stretched across four

A common request is for a single risk tagged to several assets to carry a *different* severity per asset — "MFA missing" is worse on Internet Banking than on an internal reporting server. The register does not work that way, and deliberately: a risk carries one inherent and one residual rating, and the assets on it are references.

The answer ISO 27005 gives, and the one the platform implements, is to produce **one risk per asset**. Press **Generate risks** on the register toolbar (or on either asset register, to scope it to those assets) and the scenario library pairs each selected asset with each applicable threat/vulnerability scenario; the opening impact is derived from *that asset's own* criticality and CIA ratings. So "MFA not enforced" against Internet Banking and against the core banking host arrive as two risks with two ratings and two owners — which is also what lets each be treated, accepted or closed on its own schedule. Nothing is written until you press Create: everything before that is an editable proposal, because a generated register nobody reviewed is worse than no register at all. The scenario catalogue itself is editable under **Scenario Analysis** (`/scenario-analysis`).

#### Configuring your risk matrix

The likelihood × impact matrix is **yours to define**, because ISO 27005 and ISO 31000 don't mandate a 5×5 and most banks already have a scale in their own methodology. Open the settings panel on the Risk Register and set:

- **Matrix size** — anything from 3×3 up to **10×10**, with 5×5 the default. Scores run 1 to size², and the four severity bands scale with it automatically — on 5×5 they are the familiar 1–4 Low, 5–9 Medium, 10–14 High, 15–25 Critical; on 6×6 they become 1–5 / 6–12 / 13–20 / 21–36; on 10×10, 1–16 / 17–36 / 37–56 / 57–100. There is no separate threshold to maintain, and the heat map, the register's severity chips, the exports and the dashboard all read the same bands, so they can never disagree. A bank arriving with a board-approved 1–10 ERM matrix sets it here rather than re-scoring its register to fit ours.
- **Scale definitions** — a label and a written definition for every rung of both axes ("3 = Possible — could occur once in 1–3 years", "5 = Severe — PKR 200m–1bn or regulatory censure"). This is what makes scoring repeatable between assessors, and it appears in the heat-map tooltips.
- **Appetite and tolerance** — bounded by the matrix maximum, and appetite can't exceed tolerance.

⚠ **Shrinking the matrix is refused while any risk still scores above the new maximum**, and the error names the risks. Silently clamping them would rewrite an assessor's judgement, so those risks have to be re-scored deliberately first.

**Baselining on a standard:** install **ISO/IEC 27005:2022** or **ISO 31000:2018** from Compliance → framework templates, then configure the matrix to match the criteria that standard has you define. The register's risks link to the standard's clauses like any other framework, so you can show an auditor which clause each part of your methodology satisfies.

#### Suggested residual risk

Residual risk is **assessed, not calculated** — both ISO 27005 and ISO 31000 treat it as a judgement made after considering control effectiveness. The system will not silently compute it for you; a residual score with no owner and no reasoning behind it is a finding waiting to happen. What it does instead is *propose* one.

Open any risk and the **Suggested residual** panel shows what the linked controls imply, with a line of reasoning per control:

```
Suggested residual  2 × 5 = 10      from inherent 20
  · CTL-014 Privileged access review: −2 (effective).
  · CTL-031 Quarterly recertification: no credit — its audit is overdue.
  · Applied −2 to likelihood: 4x5 → 2x5.
```

You then either **Accept suggestion** — which records it and stamps who accepted it and when — or **Record a different residual**, which requires a written reason. That sentence is what an auditor reads when they ask why your residual is lower than the control evidence supports.

Two behaviours worth knowing:

- **A control that isn't working earns nothing.** A failed audit, an overdue test or an open audit finding drops the control out of the calculation, and the rationale says which. So if assurance lapses, the suggestion **rises back towards inherent on its own** the next time anyone opens the risk — no re-run needed.
- **The weighting is your policy, not our formula.** In the same settings panel you set how many points each effectiveness rating earns, whether that credit reduces likelihood, impact or both, and the maximum any one risk may claim. The shipped default — effective = 2, partially effective = 1, likelihood only, capped at 3 — is deliberately conservative: controls change how often something happens more than how badly it hurts. Set the weights to zero, or switch the suggestion off entirely, and the panel simply reports that residual equals inherent.

#### Accepting a risk, and why it expires

Accepting a risk is the one place in the register where doing nothing is a *decision*. Open a risk and use the **Risk acceptance** panel:

1. **Request acceptance** with a written rationale — the compensating measures, who agreed, and what would change the decision. That sentence is what an auditor reads.
2. **A second person approves it.** Whoever requested it can never approve it; the platform refuses and says so, and a dual-control rule can require an even more senior approver above a chosen exposure. Approving sets the risk to `accepted` with treatment strategy `accept`.
3. **Set an expiry.** An open-ended acceptance is how a risk quietly disappears for three years.

With an expiry set, the platform manages the rest. Thirty days out it starts chasing you to renew. Once the date passes, the nightly sweep marks the acceptance **lapsed**, clears the `accept` strategy and returns the risk to `assessed` — back in the register, awaiting a fresh decision — and raises a notification saying so. Nothing is deleted: the acceptance record stays as evidence that the risk *was* accepted, until when and by whom, and the lapse is written to the activity log against the platform rather than against a person, because nobody clicked anything.

A risk somebody has since moved on to treatment, or closed, is left where it is; the acceptance lapses without dragging the risk backwards.

#### The risk report (PDF)

**Register PDF** on the toolbar produces the pack a board or a regulator asks for, covering **whatever the page is currently showing** — scope the segment bar first and the export follows.

- **Cover** — the scope it was taken under, the counts against appetite and tolerance, the methodology (your scale, your bands, your thresholds) and a heat map at your matrix size.
- **Register** — one line per risk, worst exposure first: reference, title, segment, inherent and residual severity, appetite status, owner, control count.
- **Detail page per risk** — the linked controls with their effectiveness, status, owner and next test date; the assets **with their classification and criticality**; both ratings written out (`L4 × I5 = 20 (Critical)`); the treatment plan; and the acceptance history.

A risk with no controls linked says so explicitly — "None linked — the residual rating rests on nothing recorded here" — rather than showing a blank section that reads as *not filled in yet*.

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
**Purpose:** Two reusable reference catalogs — Threats and Vulnerabilities — that you link onto risks ("a threat exploits a vulnerability to create a risk"), plus the **risk scenario library** that turns your asset register into a starting risk register.
**How to use it:** Add entries (name, category, description) to either catalog. The actual linking to a specific risk happens from that risk's **Links & Relations** tab in the Risk Register, not from this page. Before deleting an entry you'll see how many risks currently use it.
**Note:** this is a static reference catalog — for a live, scanner-fed vulnerability register see Vulnerabilities ([§7](#7-compliance)) instead, which is a separate, unrelated table.

#### Risk scenario library

At the bottom of this page sits the library that powers **Generate risks** on the asset registers. Each scenario is one reusable statement — *this threat exploits this vulnerability against this kind of asset* — plus a rule for deriving an opening impact from the asset's own rating.

**Install it once:** click **Install built-in library** to load 42 banking-relevant scenarios covering access control, data protection, cyber security, continuity, operations, third parties, physical security, compliance and financial crime. Installing also seeds the threat and vulnerability catalogs above with everything those scenarios reference, so the generated risks carry real graph links rather than free text.

**Then make it yours.** Switch off any scenario that doesn't apply to your bank, and tune the base likelihood (1–5) of the ones that do. Re-running the install after a platform upgrade adds newly shipped scenarios and **leaves your edits untouched** — it never overwrites a scenario you have already retuned. You can also bulk-load your own scenarios through Import/Export (`risk-scenarios`).

⚠ The register you generate is only as good as this library. Spend twenty minutes pruning and retuning it before generating a few thousand risks.

#### Generating risks from your asset register

On **IT Assets** and **Information Assets** there's a **Generate risks** button. It pairs every selected asset with the scenarios that apply to it and proposes a pre-filled risk for each pair.

How the opening score is worked out:

- **Impact comes from the asset.** Each scenario says which rating it should follow — the data's business value, the asset's overall criticality, the worst of its C/I/A ratings, or one specific property. A confidentiality scenario against a database rated *critical* for confidentiality opens at maximum impact; an availability scenario against the same database follows its availability rating instead. Ratings are mapped onto whatever matrix size you have configured.
- **Likelihood comes from the scenario, not the asset.** How often a threat materialises is a property of the threat and the environment, not of how much the asset is worth. Deriving it from asset value would double-count criticality and push every important asset into the top-right corner of the heat map.

**Nothing is written until you send the proposals, and nothing reaches the register until someone accepts them.** The review table groups the pairs into candidates — one per scenario, process and business unit — with an editable title and scores; untick what doesn't apply and adjust anything that looks wrong. **Send N proposals to the queue** puts them in **Risk candidates**, where each is accepted (it becomes an ordinary draft risk — reference number, asset/threat/vulnerability links, treatment suggestion, the assets' controls, audit-log entry), merged or rejected. See [Risk candidates and hierarchy](#risk-candidates-and-hierarchy).

Two behaviours worth knowing:

- **Re-running is safe.** A pair already covered by the register — an accepted candidate for the same scenario, process and unit, a risk from an earlier run, or a risk with the same title — is skipped, and a pair whose candidate is still waiting joins it, so after adding fifty assets you get only what is new. The count of skipped duplicates is shown.
- **Identically-named assets stay distinguishable.** If two different assets share a name — a pair of servers, one app in two environments — the colliding titles gain that asset's hostname (or serial, or a short id) so the resulting risks can be told apart and the next run de-duplicates correctly.

Filters let you scope a run: only assets at or above a chosen criticality, and/or only one scenario category. A very large run is capped; narrow the filter and run again for the rest.

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
**Purpose:** One-click install of 17 standards, avoiding manual data entry.
**How to use it:** Click **Install** on a card: ISO/IEC 27001:2022, the four SBP frameworks (ETGRM, Cyber Security, Outsourcing, BCP), PCI DSS v4.0.1, CIS Controls v8, NIST SP 800-53 Rev. 5, NIST CSF 2.0, SOC 2, ISO/IEC 42001, GDPR, HIPAA, SBP/AAOIFI Shariah Governance, and the maturity frameworks ISO 31000, ISO/IEC 27005 and Basel Operational Risk. This creates a Framework and all its Requirements in Compliance in one step; control frameworks can also create their controls in the Control Catalog, reusing any you already have. The full list, with requirement and control counts, is in the [Administrator Manual, §15](admin-guide.md#15-frameworks-and-the-control-catalogue).
**Note:** installing a framework that is already complete is refused; installing over an older, shallower copy **upgrades** it and keeps every existing status and link.

### Regulatory Change (`/regulatory-change`)
**Purpose:** Track SBP circulars/laws from identification through implementation, distill them into obligations, and manage the recurring regulatory-returns calendar.
**How to use it:** **Regulatory Changes tab** — log a circular (regulator, circular reference, issued/effective dates, summary, applicability, impact assessment, owner, priority) → expand it to add **Obligations** directly underneath (obligation, mapped policies/controls as free text, owner, due date, status). **Obligations tab** — a flat cross-change view. **Returns Calendar tab** — recurring SBP submissions (frequency, submission channel, next/last due dates); overdue ones are auto-flagged.
**Status flow:** change `identified → under_assessment → in_implementation → implemented → closed`; obligation `open, in_progress, met, not_met, not_applicable`.
An obligation's requirements, policies and controls are picked from those registers and saved as real links, so they show on the linked record too. Obligations created before the links existed may still carry the old free-text mapping alongside.

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
A finding can be linked to the affected IT asset, picked from the asset register, and shows on that asset.
⚠ There is currently **no CSV import** for this register (the *Vulnerabilities* import on Import / Export is the Threat Library's catalogue, not scanner findings). If you need bulk scanner ingestion today, add findings one at a time or via the API directly.

### Evidence (`/evidence`)
**Purpose:** Attach audit-readiness artifacts to a Control — see [§3.4](#34-evidence-vs-attachments--two-different-things).
**How to use it:** Create an evidence item (must pick a Control), fill in type/description/reference → save, then use the **Files** tab (appears after the first save) to upload the actual artifact.
**Status flow:** `pending, valid, expired` (auto-flags Expired once past its validity date).

### Internal Audit (`/internal-audit`)
**Purpose:** Full assurance workflow — a risk-based audit universe, engagements, working-paper procedures, and findings follow-up.
**How to use it:** **Audit Universe tab** — build your list of auditable units (category, inherent risk, audit frequency, next-due date). **Engagements tab** — create an engagement against a unit (lead auditor, scope, objectives, planned/actual dates) → add **Procedures** as fieldwork progresses (workpaper reference, result) → raise **Findings** (rating, recommendation, management response, due date). **Findings follow-up tab** — a cross-engagement list you can filter to open/overdue only, until every finding is closed.
**Status flow:** engagement `planned → fieldwork → reporting → closed`; finding `open → in_progress → closed` (or `risk_accepted`).
**Key action:** an **Audit Engagement Report** PDF export button on an open engagement.

#### Every audit in one register — internal, external, SBP

An engagement records **who performed it**: Internal audit, External (statutory), Regulatory inspection, or Certification body — along with the audit firm or regulator, the report reference and the report date. All four share one findings pipeline, which is what makes *"how many SBP inspection findings are still open?"* answerable without keeping a separate spreadsheet per auditor.

The **Assurance coverage** table on the Findings follow-up tab breaks audits, findings, open and overdue down by provenance. The engagement list can be filtered to one audit type.

**Loading an external auditor's findings:** attach their report to the engagement using the file panel at the bottom of the engagement view, then bulk-load the finding list itself through Import/Export (`audit-findings`) — name the engagement in the first column and the findings land in the same remediation tracking your internal ones use, with references, owners and due dates.

⚠ The system does **not** read findings out of an uploaded PDF. Auditors have to confirm each finding anyway, so they are entered or imported rather than extracted.

#### Annual Plan tab

What the assurance function committed to cover this year, recorded separately from what actually happened — so *"did we do what we told the board we would do?"* is a number rather than an argument.

Create a plan (year, title, budgeted hours), then **Generate from audit universe**: every auditable unit becomes a plan line, with its quarter derived from when it falls due and its rationale taken from its risk rating and audit frequency. Re-running skips units already in the plan, so it is safe after the universe grows. Lines can be removed, and each shows whether it has become a real engagement yet — that ratio is the plan-vs-actual **coverage** figure.

**Submit for board approval** raises a normal approval request in the Approvals inbox, so board or audit-committee sign-off inherits maker-checker, chasing and the audit log. An empty plan cannot be submitted, and an approved plan cannot be re-submitted.

#### Programmes tab (checklists)

A programme is the test steps for one kind of audit, written once. The fast path is **Generate from framework**: pick a framework you have installed and you get one step per clause — for ISO 27001:2022 that is the whole Annex A list — with each step linked back to the requirement it tests, which is what makes the finished working papers defensible to a certification auditor.

**Apply as working papers** instantiates the steps onto an engagement as ordinary Procedures you record results against. Applying twice tops up rather than duplicating: steps already on the engagement are skipped.

#### Calendar tab

Everything the assurance function has to turn up for, in one window: planned fieldwork (with its end date), finding due dates, when each auditable unit next falls due, and plan lines that have not started yet. Filter by kind, set any date range; anything already past is flagged. No new dates are entered here — it reads what the plan, engagements, findings and universe already hold.

**Auditing something twice a month.** Two ways, depending on whether it recurs:

- **A recurring fortnightly cycle** — set the auditable unit's audit frequency to **Fortnightly**. Its next-due date then advances 14 days at a time rather than a month, and it appears on the calendar on that cadence. The same frequency is available anywhere a review cycle is set: risk reviews, control tests, policy reviews.
- **Two specific audits in one month** — give each plan line a **month** as well as a quarter. A line with a month lands on that month in the calendar; one without sits mid-quarter.

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
**What is enforced:** four-eyes is checked on about seventeen decisions — accepting a risk, approving an exception, testing and reviewing control tests, publishing a policy, filing an STR/SAR, Shariah disbursements, amending an authority-matrix line, validating and closing issues and approving their extensions, deleting core records, approving any record submitted for review, and bulk-archiving risks. With segregation of duties on, all of them are four-eyes without any rule; a rule relaxes one decision or makes it depend on an amount. **Attesting is the exception**: it is the owner's own certification, so it is four-eyes only where an administrator has added a rule for it — independence comes from the record's approval and from the second signature. The exact module/action keys and how rules are resolved are in the [Administrator Manual, §19.1](admin-guide.md#191-maker-checker-four-eyes).
⚠ A rule's **Maker role** and **Checker role** only document it — who may check is decided by permissions. The **Authority Matrix**'s amount bands are a registry: they don't block anything in other modules.

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
**How to use it:** **Users tab** — create a user (name, email, initial password, one or more roles); use **Activate/Deactivate** to suspend access (you can't deactivate your own account) and **Reset password** as needed (a reset also unlocks a locked account). **Roles tab** — create a custom role by picking permissions from the catalog (grouped by module, with bulk select/clear); built-in roles can have their permissions edited but not be renamed or deleted, and a custom role can't be deleted while still assigned to a user. How to design roles for a bank, and which permissions are privileged: [Administrator Manual, §10](admin-guide.md#10-users-and-roles).

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
**Status flow:** `open → in_progress → remediated / closed / risk_accepted`. The last three are reached only through **Validate** and **Close** in the drawer — see *3f. Record depth → Issues*.
**Where issues come from automatically:** risks, controls, third parties, IT assets and information assets have a **Raise issue…** action that links the issue to them, and approving a failed (or passed-with-exceptions) control test opens an issue on its own.
⚠ Other modules don't. When you close a compliance finding, an ICFR deficiency, an internal-audit finding, an incident, or a Shariah SNC finding, you need to separately come here and create the Issue yourself if you want it tracked in the unified register.

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
**What lands here automatically:** the stages of an approval route when a record whose type has a live route is submitted for review ([Approval Workflows](#approval-workflows-workflows)), and an internal audit annual plan submitted for board approval. You can also create a request by hand and note in the description which record it concerns.

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
**How to use it:** **Connectors tab** — register a connector (type, endpoint, auth method note, sync frequency) — flagged **stale** automatically if it hasn't synced in 35+ days. **CCM tab** — define an automated control test (which control it verifies, the pass condition in plain language, optionally which connector it uses) → **Record** a run's result (passed/failed/error, pass rate %, findings, evidence reference) by hand, or let the monitoring tool send results through the connector's **Monitoring feed** token (see [Continuous monitoring feeds](#continuous-monitoring-feeds)). A fed result becomes evidence on the control, a run of the matching test and, when it failed, an alert to the control owner.
⚠ NexusLine doesn't reach out to the other system: there's no "test connection" and no scheduled pull — results arrive only when the other system posts them or someone records them. A result never changes the control's effectiveness rating and never opens an Issue; that still takes a person-recorded, second-person-approved test.

### Custom Fields (`/custom-fields`)
**Purpose:** Add tenant-specific fields to a record type without code changes.
**How to use it:** Pick a module (48 record types are supported — risk, control, IT asset, information asset, vendor, policy, incident, issue, requirement, KRI, loss event, shariah_review, rcsa_assessment, audit_engagement, and so on), name the field, pick its type (text/textarea/number/date/select/checkbox), mark required if needed. Needs `customfield:manage`.
**Where the field appears:**
- **In the module's Add / Edit form** — as a **Custom fields** tab (the last tab). Values save together with the record, and required custom fields block saving like any other required field.
- **On the record** — in its Details section or **Custom fields** card, with **Edit** to change values without opening the full form.

**IT assets and information assets are separate modules.** A field added to *IT asset* appears only on IT assets, and one added to *Information asset* only on information assets. Fields created before this split was introduced were copied to both, each keeping its values; delete the copy you don't need.

If you define a field and see nothing, check you picked the module you're testing (e.g. `shariah_review`, not `risk`) and that the field is enabled.

### Status Rules (`/status-rules`)
**Purpose:** Auto-label records with a colored badge when a field meets a condition (e.g. "Above Tolerance" when a score exceeds a threshold).
**How to use it:** Pick a module (risk, control, incident, vendor, project, policy, asset, goal, exception, requirement, continuity plan, processing activity, KRI, RCSA or evidence), pick a field and operator (equals/greater-than/contains/overdue/is-true/not-empty, etc.), a comparison value, and a label + color. Needs `automation:manage`.
**Note:** this is a labeling engine, not a time-based escalation engine — for time-based chasing see Turnaround Time below.

### Turnaround Time — TAT (`/sla-policies`)
**Purpose:** Turn your remediation standard ("critical findings within 15 days, high within 30") into something the platform measures, warns about *before* it lapses, and escalates when it does. Until this clock exists, the standard lives in a policy document and nobody knows it was missed until an auditor counts.

**What it covers:** Risks, Issues, Audit Findings and Incidents — a target in calendar days for each severity of each.

**How to use it:** The screen shows the complete grid, already filled with sensible defaults, so the clock is running from day one rather than waiting to be switched on. Anything nobody has configured is marked *default*. For each row set:

- **Target (days)** — how long a record of that severity may stay open. The clock starts when the record is raised.
- **Warn at %** — raise an early warning once this much of the window has elapsed. At the default 80%, the owner is told with a fifth of the time still left; an alert that only arrives on the day of breach is a report, not a control.
- **Escalate to role** — who is emailed, in addition to the normal digest, when the window is breached. Leave blank for no escalation.
- **Clock on/off** — switching a row off means *no clock for that scope*, not a fall-back to the default. Use it where your bank deliberately doesn't chase, e.g. low-severity findings.

**Where breaches show up:** the notification centre (critical for a breach, warning for one approaching), the **Needs your attention** queue on the dashboard, a **once-a-day sign-in reminder** listing what is past its window, the "Currently outside TAT" table on this page, and an escalation email to the configured role. The reminder is dismissible for the day — but if something *new* breaches later it returns rather than staying silent.

⚠ **TAT is not the same as a record's due date.** The due date is what was agreed with the action owner; TAT is what the policy allows. Both are tracked, neither overwrites the other, and the gap between them is itself worth looking at.

Editing a target recalculates every open record's window immediately, so a policy change is reflected the moment you save it rather than at the next background sweep. Defaults in force today: risks and issues 15/30/60/90 days by criticality, audit findings 30/60/90/120 (they usually need a project), incidents 1/3/7/14 (there the clock is response, not remediation). Changing them needs the **Set turnaround-time (TAT) targets and escalation** permission, which is held separately from module edit rights — who may lengthen a remediation deadline is itself a governance control.

### Approval Workflows (`/workflows`)
**Purpose:** Define your own multi-stage approval route per record type — *"risk acceptance goes Owner → Department Head → CRO → Risk Committee, two of three"*.

**How to use it:** Create a route for a record type, add its stages in order, then switch it on. Each stage sets:

- **Decided by** — anyone holding a role, a named person, the record's own owner, or the owner's line manager. It names who the stage is for on the approval request and in its alerts.
- **Approvals** — how many distinct people must approve *that stage*; 2 gives six-eyes on that step alone.
- **Deadline** and what happens if it lapses (escalate and keep waiting, approve automatically, or block).

⚠ Today **Decided by** is a label, not an access check: anyone with `workflow:approve` who isn't the submitter can decide any stage. *The owner's line manager* isn't looked up (users have no manager field), and the lapse choice is recorded but not acted on — an overdue stage simply keeps alerting. See the [Administrator Manual, §19.2](admin-guide.md#192-approval-workflows).

On a record with a live route, a progress strip shows which stage it is on, who it is waiting for, and what each decided stage concluded. **Send for approval** starts the route; **Cancel route** abandons it.

**What this does *not* change.** A stage never approves anything itself — it raises an ordinary approval request and waits. That means maker-checker, segregation of duties (the submitter can never approve their own stage), N-eyes counting, overdue chasing and the audit trail all apply to workflow stages exactly as they do to any other approval, because they are the same code. A rejection at any stage ends the route and marks the remaining stages *skipped*, never approved. When the last stage lands, the submitter gets a notification.

⚠ **Nothing changes until you switch a route on.** A record type with no enabled route keeps the standard `draft → in review → approved → retired` lifecycle it has always had. Only one route per record type can be live at a time — two would leave "which approval applied?" unanswerable. A route that records are still travelling cannot be deleted; disable it instead so those approvals can finish.

### Saved Filters (`/filters`)
**Purpose:** Build and reuse named, multi-condition queries (e.g. "Critical open risks") over a module.
**How to use it:** Pick a module, add condition rows (field/operator/value), choose match-all or match-any, mark it Shared if others should see it, then **Run** it to see the matching records.
⚠ Saved filters are a **standalone query tool** — they don't appear as a "load filter" dropdown on each module's own table view.

### Import / Export (`/data-io`)
**Purpose:** Bulk import/export for every supported register (Policies, Risks, Controls, IT & Information Assets, Vendors, Incidents, Exceptions, Legal, Business Units, Processes, Threats, Vulnerabilities catalog, Goals, RoPA, Continuity Plans, Projects, Compliance Requirements, Evidence, Awareness Programs, Access Reviews, Issues, RCSA, KRIs, Loss Events, Obligations, Regulatory Changes, Audit Engagements, ICFR Processes, Models, Outsourcing Arrangements, BIAs).

**Export / Template:** **Export Excel** (or **CSV**) downloads every record with every column — **your organisation's custom fields included**, after the built-in columns. **Template** downloads an Excel workbook to fill in: the same columns (custom fields included), a dropdown on every choice column (status, yes/no, a custom field's select options), required headings shaded, and a **Guide** sheet listing each column's type, allowed values and an example. A custom field whose name repeats a built-in column is headed "Name (custom)". Uploading a filled template or an edited export maps the custom-field columns back to their fields automatically, and checks their values (a select must be one of its options, a date must be YYYY-MM-DD, a yes/no must be yes or no) — a bad value fails just that row, with the column named.

**Import — you do not have to rewrite your spreadsheet.** Upload the file your organisation already keeps, with its own column names, and the wizard matches them to our fields. It runs in four steps:

1. **Upload** — choose a `.csv` or Excel `.xlsx` file. A title/banner row above the real headings is detected and skipped, and a multi-sheet workbook lets you pick the sheet. If you have imported this layout before, pick the **saved mapping** and the columns are filled in for you.
2. **Match columns** — each of your columns is shown with a real example value from your file and the field it will import into. Matches are pre-selected and labelled **Confident**, **Check** or **Unsure** with the reason ("known alternative name for 'inherent_likelihood'"), so you know which ones deserve a second look. Anything we could not recognise starts as **Do not import** — it is never guessed at. You can point any column at a different field, at a **custom field** (for data we have no native field for), or leave it out.
3. **Preview** — the first 20 rows are processed exactly as the real import would, **without saving anything**, so you see the values that will land and any problems first — including a reference that points at a record which doesn't exist yet. This is also where you can **save the mapping** under a name for next quarter's upload.
4. **Import** — each row runs through the module's normal creation logic, so reference numbers, links to other records by name, custom-field values and audit logging all happen as if you'd created the record by hand. One bad row never blocks the rest: a result table lists every skipped row with its reason, and **Download errors** gives you a CSV of just those rows to fix and re-import.

**Notes.** Blank cells are skipped. Link columns accept comma-separated references or names. Two of your columns can never feed the same field — the wizard blocks it, because silently letting one win would make repeat imports inconsistent. A file whose headings already match our template still imports exactly as before, with no mapping step.

### Webhooks (`/webhooks`)
**Purpose:** Push real-time HTTP notifications to an external system (SIEM, ticketing, chat) whenever records change.
**How to use it:** Create a webhook (name, payload URL, events — a comma list like `risk,incident,approval`, or `*` for everything, optionally a signing secret for HMAC verification) → **Test** it (sends a synthetic ping) → **Enable** it. Check the **Log** to see recent deliveries (success/fail, status code).
⚠ Delivery is single-shot, best-effort — there's **no automatic retry** if the receiving end is briefly down.

### SSO (`/sso-settings`)
**Purpose:** Configure OIDC/OAuth2 sign-in with your bank's identity provider.
**How to use it:** Toggle **SSO enabled**, enter your IdP's Client ID/Secret and authorize/token/userinfo URLs, set the email/name claim names, toggle **JIT provisioning** and pick the default role new SSO users get, and optionally restrict to specific email domains. Register `https://<your address>/sso/callback` as the redirect URL at the identity provider. Step by step: [Administrator Manual, §11.4](admin-guide.md#114-single-sign-on-sso).
**Note:** LDAP/Active Directory is configured separately, on the `/settings` page ([§11.5](admin-guide.md#115-ldap--active-directory)).

### Settings (`/settings`)
**Purpose:** General admin hub — organization info, system health, personal security, and LDAP. It appears in the sidebar as **General Settings**, for everyone.
**What's here:** an organisation and role summary; **Email & automation** with **Send test email** (to verify SMTP); **System** — version, health, licence, the **module matrix** (on, hidden, or unlicensed), **Back up database now** and **Download support bundle**; **Account security** — your own two-factor authentication and password; the **LDAP / Active Directory** card; and an **Administration** hub linking to Organisation Settings, Users & Roles, Single Sign-On, Webhooks, Custom Fields, Lookups & Dropdowns, Status Rules, Saved Filters, Import / Export and the Activity Log. What each administrator setting does: [Administrator Manual](admin-guide.md).

### Organisation Settings (`/organisation-settings`)
**Purpose:** currency, timezone, date format, phone country, fiscal year and how long archived records are kept, plus the **Organisation setup & modules** button that reopens the setup wizard to change which modules are on. Changing them needs `settings:manage`. See [3e](#3e-picked-not-typed-owners-lists-and-the-approval-lifecycle) and the [Administrator Manual, §9](admin-guide.md#9-organisation-settings).

### Lookups & Dropdowns (`/lookups`)
**Purpose:** the organisation's governed lists — risk category, incident type, regulator, country, impact dimension and ten more — plus asset, vendor and tag lists and the C/I/A classification schemes. Values can be added, renamed, reordered, re-parented and deactivated; a value in use can't be deleted. See the [Administrator Manual, §13](admin-guide.md#13-lookups-the-organisations-governed-lists).

### Organisations (`/organizations`) — platform administrators only

**Purpose:** running the *deployment*, as opposed to running an organisation inside it. One installation hosts many client organisations; this is where they are created, listed and suspended.

**Who sees it:** only accounts flagged `is_platform_admin`. This is deliberately **not** a role or permission: permissions are rows in each organisation's own `roles` table, so an organisation's admin could otherwise grant themselves the run of the platform. The bootstrap admin created by the seed holds the flag; everyone else is promoted by another platform administrator.

**How to use it:**
- **Add organisation** — name, a sign-in identifier (the short slug its people type at the login screen alongside their email), and the first administrator's email and temporary password. That administrator gets the Admin role and invites everyone else. The organisation arrives complete: default roles, permission catalogue, and the baseline lookup vocabulary, so its forms are usable immediately.
- **Suspend / Restore** — suspension blocks every login for that organisation and **deletes nothing**; every record stays exactly where it is and access can be restored at any time. There is no delete button: an organisation's data outlives its contract. You cannot suspend the organisation you are currently signed in to.
- The summary strip shows totals and the deployment's licence.

**What it cannot do:** read anybody's data. The per-organisation counts are the only figures crossing a boundary, and each is read inside that organisation's own scope. A grouped query across organisations is not expressible at all — row-level security prevents it — which is the guarantee, not a limitation to work around.

#### How the isolation actually works

Every tenant-scoped table (150 of them) carries a PostgreSQL row-level-security policy matching `tenant_id` against a transaction-local setting the connection makes per request. `FORCE ROW LEVEL SECURITY` means it applies even to the table owner, and the application connects as a non-superuser so the policy genuinely binds. If the tenant is never set, `NULLIF(…, '')::uuid` is NULL, `tenant_id = NULL` matches nothing, and the connection sees **zero rows** — it fails closed rather than open.

The evidence to hand an auditor is `backend/tests/test_tenant_isolation.py`. Its structural half runs on every build and fails if a new table ships with a `tenant_id` and no policy — the one way this guarantee realistically breaks. Its live half, run with `TEST_DATABASE_URL` pointing at a real database, uses two organisations to prove that the second cannot list, count, fetch by primary key, or write into the first, and that a connection with no tenant set sees nothing.

A fresh install seeds **two** organisations for exactly this reason: sign in to the second one and the register is empty. Same URL, same build, none of the first organisation's data.

**Cloud and on-premise are the same build.** Multi-tenancy is always on; an on-premise bank simply runs an installation with one organisation in it, and the licence covers the deployment rather than each organisation. Nothing has to be forked or configured differently to serve either.

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
Four-eyes is enforced on the record itself for the decisions listed under [Delegation of Authority](#delegation-of-authority-delegation-of-authority): submit a record for review and someone else approves it; request a risk acceptance and someone else approves it; record a control test and someone else reviews it. For multi-stage sign-off, an administrator switches on an approval route for that record type, and each stage arrives in Approvals. For a decision that has no record of its own, create the request directly in Approvals, set the required number of independent checkers, and reference what it concerns in the description.

---

## 13. Roles & permissions reference

Every permission is a `resource:action` code (96 total across every module). Most modules follow simple read/write; a few sensitive actions get their own verb (e.g. `risk:accept`, `control:test`, `exception:approve`, `workflow:approve`) so "can edit" and "can approve" can be different people, and six `:manage` codes cover administration (settings, SSO, custom fields, automation, TAT, integrations).

| Built-in role | Permissions | Typical use |
|---|---|---|
| **Admin** | 96 | Full access, including user/role management. |
| **Risk Manager** | 53 | Manage risk, controls (including recording tests), assets, incidents, vendors, BCP, projects, operational risk, issues, fraud, scenario analysis, vulnerabilities, model risk, outsourcing, quantitative risk, CCM, AI Assist. Can't accept risks or approve. |
| **Risk Approver** | 9 | Read-only across risk/controls/assets, plus the *approve* actions only (risk acceptance, exceptions, approvals) — a pure "checker" role. |
| **Compliance Manager** | 45 | Frameworks, controls (including tests), policies, privacy, awareness, Shariah, AML, issues, regulatory change, ICFR, declarations, whistleblowing, governance, ESG, DoA, data protection. |
| **Auditor** | 44 | Read-only across the entire platform, plus full read/write on Internal Audit — an independence-preserving role. |
| **Viewer** | 43 | Read-only everywhere, including the user list, roles and activity log. |

Admins can also build **custom roles** by hand-picking any combination of the 96 permissions from [Users & Roles](#users--roles-organization). Assignment is per-user (pick one or more roles) — there's no per-record or per-business-unit scoping. The full catalogue and a suggested role set for a bank are in the [Administrator Manual, §10 and Appendix B](admin-guide.md#105-designing-roles-for-a-bank).

When the platform is upgraded with new modules (and therefore new permission codes), every built-in role is automatically topped up with the new codes it's entitled to the next time the backend restarts. This never touches a user's assignments, but note two consequences: a default permission you *removed* from a built-in role comes back at the next restart (use a custom role to give less), and **custom roles are not topped up** — add new module permissions to them yourself after an upgrade.

---

## 14. Known gaps — things that look automatic but aren't yet

Documented here so you plan your bank's process around what's actually enforced, not what's merely configured. (These are also tracked as deliberate follow-up work — see `GAP-ANALYSIS.md`.)

Checked against the code again on 13 September 2026. Gaps that only an administrator meets (sign-in, backups, approval routes, imports) are listed in the [Administrator Manual, §27](admin-guide.md#27-known-limitations-for-administrators).

- **The Authority Matrix doesn't gate other modules.** Four-eyes itself *is* enforced on about seventeen decisions (see [Delegation of Authority](#delegation-of-authority-delegation-of-authority)); the matrix's approval *limits* by amount are still a registry — they document the rule, they don't block anything elsewhere. A maker-checker rule's maker and checker roles are documentation too.
- **Approval routes don't restrict who decides a stage.** Anyone with `workflow:approve` who isn't the submitter can decide any stage, whatever the stage's *Decided by* says.
- **Issues are raised automatically only from risks, controls, third parties, assets and failed control tests.** Incidents, compliance findings, ICFR deficiencies, internal-audit findings and Shariah SNC findings still need an Issue created by hand if you want them in the unified register.
- **Business Units are not a security boundary.** Only whole-organization (tenant) isolation is enforced at the database level; anyone with a module's read permission sees every business unit's records in it.
- **Whistleblowing's tracking code is internal-only.** There's no public page yet for an anonymous reporter to self-serve a status check or add a follow-up.
- **Fraud Cases and Operational Risk Loss Events are separate, unlinked registers** — log a shared event in both if it applies to both.
- **Continuous monitoring is push-only.** Monitoring tools can post results through a connector's feed token, but NexusLine doesn't poll other systems, and a result never changes a control's effectiveness rating or opens an Issue.
- **Webhook delivery has no retry** — a single failed POST is logged, not retried.
- **Saved Filters run from their own page.** Each register has its own saved views, but those live in your browser and aren't shared.
- **Reports aren't e-mailed on a schedule.** The Report Builder saves and shares report definitions, board packs are generated automatically before committee meetings, and the Statement of Applicability exports on demand — but there's no "email me this every Monday."
- **Record-level immutability** for loss events, SAR, and breach records (a regulator expectation) is not yet built; version history is kept but records stay editable.
- **Several modules are not yet wired into the cross-module graph.** AML/CFT, Fraud Risk, Model Risk, Scenario & Capital, ESG, Declarations, Whistleblowing, Awareness and DPIA/DSAR/Consent have no links to the risk, control or RoPA registers; Shariah Governance and Board & Committees link only within themselves. Awareness participants are typed names, not user accounts. They work standalone; they just don't appear on a linked record's "related" panel. (Regulatory-change obligations, vulnerability findings and data breaches now do link.)

### What changed on 11 Aug 2026

- **Every sign-in is now in the Activity Log.** Successful logins, failed attempts and the reason, lockouts, MFA changes, password changes and SSO/LDAP configuration edits all appear under the `auth` entity type. Webhook, custom-field, status-rule, business-unit, process, legal-register and bulk-import changes are logged too.
- **Read-only users can no longer write through the side panels.** Adding a comment, tag, attachment or file, signing off a review, or filling a custom field now needs that module's *write* permission — previously any signed-in user could do it on any record they could see.
- **Bulk import covers 32 registers, up from 20** — including Issues, RCSA, KRIs, Loss Events, Obligations, Regulatory Changes, Audit Engagements, ICFR Processes, Models, Outsourcing Arrangements and BIAs. IT Assets and Information Assets now import separately, each with its own columns.
- **Global search reaches every module**, not just the core registers.
- **Four-eyes now applies to eight decisions** (see the Delegation of Authority note above). On a single-user evaluation install, set `ENFORCE_SEGREGATION_OF_DUTIES=false` or add a second user — otherwise you cannot approve your own records.
