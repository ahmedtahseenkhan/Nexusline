# Demo Runbook — GRC Platform

**Why this exists.** In the review meeting, five of the eleven questions raised were about
capabilities the platform already had. They were asked because the walkthrough never
surfaced them. This runbook fixes that: a fixed order, with the specific click that proves
each point, so the demo does not depend on who is presenting.

**Setup before you start**

- Log in as an administrator on a tenant with the seed data loaded.
- Install ISO/IEC 27001:2022 and at least one SBP pack from Compliance → framework templates.
- Install the scenario library: Threat Library → Risk scenario library → **Install built-in library**.
- Have a real client spreadsheet to hand for section 2 — their own column names, not our template.

Timings assume a 45-minute session. Cut sections 8–10 first if you are short.

---

## 1. Start where their question starts (3 min)

Open **Dashboard**. Do not narrate the tiles.

Point at **Needs your attention** and say: *this is what the platform is for — it tells you
what has gone wrong without anyone running a report.* Then scroll to the heat map.

---

## 2. The heat map, and how the number is reached (5 min) — *answers Sidra, MoM 3*

On the dashboard heat map:

1. Toggle **Inherent / Residual**. Say the words: *these are two different assessments,
   not one number.*
2. **Hover a filled cell.** It shows likelihood, impact, the score, the band, and the
   actual risk references in that cell. This is the "show me how it is actually
   calculated" answer — do not skip the hover.
3. Point at the legend: the band ranges are printed (1–4, 5–9, 10–14, 15–25). Say they
   scale automatically if the matrix size changes.

Then go to **Risk Register → settings panel → matrix editor** and show:

- Matrix size 3×3 to 6×6.
- A label *and a written definition* per rung of both axes.
- That the bands re-derive when the size changes.

Finish with: *ISO 27005 and 31000 do not mandate 5×5, which is why this is yours to set.*

---

## 3. Framework baselining (3 min) — *answers Sidra, MoM 3*

Compliance → framework templates. Show **ISO/IEC 27005:2022** and **ISO 31000:2018** in the
list alongside 27001, NIST CSF, PCI DSS and the four SBP packs.

Install nothing new here — instead open an installed framework and show a requirement, then
open a risk and show the **Compliance requirements** chip linking back to it. The point is
traceability in both directions, not the catalogue size.

---

## 4. Qualitative *and* quantitative (3 min) — *answers Fahad, MoM 5*

Open any risk → **Assessment** tab.

- Top half: likelihood × impact, the qualitative score.
- Same tab, lower: **Annual Loss Frequency × Single Loss Expectancy → Annual Loss
  Expectancy**, in currency, next to treatment cost.

Say: *both, on the same record. Qualitative across the register; quantitative on the
material risks where a number in rupees changes the decision.* Mention `/risk-quantification`
(Monte Carlo) and `/scenario-analysis` exist without opening them.

---

## 5. Residual risk — the one to get right (6 min) — *answers Usman, MoM 2 and 4*

Open a risk that has controls linked. On the record:

1. Point at the **Suggested residual** panel and read the rationale lines aloud — including
   a line that says *no credit* and why.
2. Say plainly: **the system does not calculate residual for you, and it should not.** ISO
   27005 clause 8.6 has the risk *owner* approve the residual level. A number the software
   produced with nobody's name on it is a finding.
3. Click **Record a different residual**, type nothing in the reason box, and try to save.
   Show that it refuses. *That sentence is what an examiner reads.*
4. Cancel out. Click **Accept suggestion** and show the acceptance is stamped with who and when.

Then the killer demonstration, if you have two minutes:

> Open the linked control, set its next audit date into the past, return to the risk. The
> suggestion has **risen back towards inherent on its own**, with the line *"no credit — its
> audit is overdue"*. Nobody re-ran anything.

Leave the residual-risk note (`docs/residual-risk-methodology.md`) with them afterwards.

---

## 6. Import with their own spreadsheet (5 min) — *answers Asad, MoM 1*

Use **their** file, not ours.

Risk Register → **Import**:

1. **Upload** — drop in their .xlsx or .csv. Point out that a title/banner row above the
   headings is detected and skipped, and that the sheet can be chosen.
2. **Match columns** — their headers on the left, ours on the right, already filled in.
   Show the confidence labels (*Confident / Check / Unsure*) and the reason text
   ("known alternative name for 'inherent_likelihood'"). Point at a column that came back
   **Do not import** and say: *we do not guess. Unrecognised columns wait for you.*
3. Repoint one mapping by hand to show it is editable, and show a column being sent to a
   **custom field** instead of being discarded.
4. **Preview** — 20 rows, errors inline, *nothing saved yet*.
5. **Save this mapping** under a name. Say: *next quarter's upload is one click.*
6. **Import** — show the result summary and, if any row failed, the **Download errors** CSV.

---

## 7. Generating risks from the asset register (4 min) — *answers Usman, MoM 8*

IT Assets or Information Assets → **Generate risks**.

- Show the proposals: pre-scored, pre-linked, with the scenario reference.
- Point at two rows for the same asset with different impacts and explain: *impact comes
  from that asset's own rating — a confidentiality scenario follows its confidentiality
  rating, an availability scenario follows availability.*
- Untick a few, edit one score, then **Create**.
- Open the register and show the new risks carry references, asset/threat/vulnerability
  links and a suggested treatment.
- Re-open Generate risks and show the **duplicates skipped** count. *Safe to re-run after
  you add assets.*

---

## 8. TAT and being chased (4 min) — *answers Sidra, MoM 6*

System → **Turnaround Time (TAT)**.

- Show the grid: every record type × severity, already populated with working defaults.
  Say: *the clock is already running; it did not wait to be switched on.*
- Explain **Warn at 80%** — *an alert that only arrives on the day of breach is a report,
  not a control.*
- Point at **Escalate to role**.
- Scroll to **Currently outside TAT** and show real records.

Then go back to the Dashboard and show the TAT line at the top of **Needs your attention**.
Mention the once-a-day sign-in reminder rather than forcing it to appear.

---

## 9. Audits — internal, external and SBP in one register (5 min) — *answers Asad, MoM 9*

Internal Audit:

1. **Engagements tab** — create or open one and show **Audit type** (Internal / External
   statutory / Regulatory inspection / Certification body), the firm or regulator, report
   reference and report date.
2. Scroll to the bottom of the engagement and **upload a PDF** as the audit report.
3. **Findings follow-up tab** → the **Assurance coverage** table. Say the sentence that
   lands: *this is how you answer "how many SBP inspection findings are still open?"
   without a separate spreadsheet per auditor.*
4. Mention that an external firm's finding list bulk-loads via Import/Export
   (`audit-findings`) into the same remediation pipeline.

---

## 10. Audit planning, checklists, calendar (5 min) — *answers MoM 10*

Still in Internal Audit:

- **Annual Plan tab** → **Generate from audit universe**. Show lines appearing with
  quarters derived from due dates and a rationale from the risk rating. Show the
  **coverage %** and say: *plan versus actual — did we do what we told the board we would do.*
  Click **Submit for board approval** and show the request landing in the Approvals inbox.
- **Programmes tab** → **Generate from framework**, pick ISO 27001. Show one step per
  clause, each linked back to the requirement. Then **Apply as working papers** to an
  engagement and open the engagement to see them as procedures.
- **Calendar tab** — show fieldwork, finding due dates, unit due dates and unstarted plan
  lines in one window. Mention the **fortnightly** frequency for units audited twice a month.

---

## 11. Workflow approvals (4 min) — *answers MoM 10*

System → **Approval Workflows**.

- Show a route: Owner → Department Head → CRO, with per-stage approver mode, number of
  approvals and deadline.
- Open a risk and show the **progress strip** — which stage, who it is waiting on, what
  each decided stage concluded.
- Say the sentence that matters: **a stage does not approve anything itself.** It raises an
  ordinary approval request, so maker-checker and segregation of duties apply automatically.
  If you can, demonstrate the submitter being refused with the SoD error.
- Note that a record type with **no route switched on keeps its existing lifecycle** —
  nothing changes until they choose it.

---

## 12. Close (2 min)

Two sentences, not a summary of everything:

> Most of what you asked for on the risk side is configuration, not development — your
> matrix, your residual weighting, your TAT targets. Send us those three and we will have
> the platform speaking your methodology rather than ours.

Then ask for the three things by name:

1. Their **likelihood and impact scale definitions**.
2. Their **residual weighting** — points per control effectiveness rating, and the cap.
3. Their **TAT targets** — days per severity, per record type, and who escalation goes to.

---

## Things not to do

- **Do not open Settings first.** Configuration screens make a product look like work.
- **Do not narrate the module list.** They have seen it; that is why the questions were
  about depth, not breadth.
- **Do not claim residual is auto-calculated.** It is not, deliberately, and the reason is
  a selling point — say it that way.
- **Do not demo import with our own template.** The entire point is that their file works.
