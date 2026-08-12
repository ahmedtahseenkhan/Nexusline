# How Residual Risk Works

**For:** Usman — raised at the GRC tool review (MoM items 2 and 4).
**Short answer:** the system does **not** calculate residual risk on its own, and that is
deliberate. It proposes a residual score, shows you exactly how it arrived at it, and
records who accepted it. This note explains why that is the correct design and how to
use it.

---

## 1. What you saw in the demo

Risks appeared with both an inherent and a residual score already filled in, which
reasonably looked like the tool had calculated the residual itself. It had not — that was
demonstration data with both values pre-entered.

Here is what actually happens:

| | Where it comes from |
|---|---|
| **Inherent risk** | Likelihood × Impact, both entered by the assessor. This is the exposure *before* any control is considered. |
| **Residual risk** | A **separate** Likelihood × Impact, entered after considering how well the controls actually work. Blank until someone assesses it. |
| **Effective score** (what reporting uses) | Residual if it has been assessed; inherent if it has not. |

So inherent and residual are two independent assessments on the same record. You were
right to say they are different things — the system treats them that way.

---

## 2. Why the tool should not simply compute it for you

This is the part worth pausing on, because "make the system calculate it" sounds like an
improvement and in an audit it is a liability.

**ISO/IEC 27005:2022 and ISO 31000:2018 both treat residual risk as an assessed
judgement**, made after considering control effectiveness — not as an arithmetic output.
27005 clause 8.6 is explicit that the risk owner **approves** the residual level as part
of the treatment plan. It is a decision with a name attached to it.

Now picture the inspection. An examiner asks: *"This risk was inherent 20. Why is the
residual 6?"*

- If the answer is **"the software subtracted it"**, you are defending a black box. You
  cannot show which controls earned the reduction, whether they were working on the day,
  or who agreed the number. That is a finding.
- If the answer is **"three controls were considered, two are tested and effective, the
  third has an overdue audit so it earned no credit; the risk owner accepted 6 on 12
  August"**, the conversation is over.

The second answer is what this design produces.

---

## 3. What the system does instead

Open any risk and you will see a **Suggested residual** panel:

```
Suggested residual  2 × 5 = 10        from inherent 20
  · CTL-014 Privileged access review: −2 (effective).
  · CTL-031 Quarterly recertification: no credit — its audit is overdue.
  · Applied −2 to likelihood: 4×5 → 2×5.
```

Three things to note:

1. **Every control is accounted for**, including the ones that earned nothing and why.
2. **A control that is not currently working earns nothing** — a failed audit, an overdue
   test, or an open audit finding against it. So the suggestion is based on assurance that
   actually holds today, not on a control that exists on paper.
3. **Nothing is written yet.** The record's residual does not change until you act.

You then either:

- **Accept suggestion** — the residual is recorded, stamped with who accepted it and when; or
- **Record a different residual** — which **requires a written reason**. That sentence is
  what an examiner reads when your number is lower than the control evidence supports.

### It corrects itself when assurance lapses

This is the behaviour worth demonstrating. If a mitigating control's audit fails or falls
overdue, that control stops earning credit and **the suggestion rises back towards
inherent on its own**, the next time anyone opens the risk. Nobody has to remember to
re-run anything. We verified this end to end: a risk sitting at a suggested 2×5 went back
to 4×5 with the line *"no credit — its audit is overdue"* the moment its control lapsed.

---

## 4. This is your methodology, not ours

The weighting is configuration. On the Risk Register settings panel you set:

| Setting | Default | Meaning |
|---|---|---|
| Points per effectiveness rating | Effective = 2, Partially effective = 1, Ineffective = 0, Not assessed = 0 | How much credit a control earns |
| Credit reduces | Likelihood only | Whether credit comes off likelihood, impact, or is split |
| Maximum reduction | 3 | The most any single risk may claim |
| Suggestion on/off | On | Switch it off entirely and the panel simply reports residual = inherent |

**Why the defaults are what they are:** controls generally change how *often* something
happens, not how *badly* it hurts when it does — a backup does not make a data breach less
severe, it makes an outage less likely. So credit reduces likelihood by default. If your
methodology says otherwise, change the setting; no code change and no release is involved.

**We need two numbers from you** to finish configuring this: your own weighting per
effectiveness rating, and your maximum reduction. If you have an existing risk methodology
document, sending it is the fastest route.

---

## 5. Where the controls themselves are visible (MoM item 4)

Your related point was that the controls behind a residual score were not visible. They now
are, in three places:

- **On the risk** — the Controls tab lists every linked control from the Control Catalog,
  and a live **control health** indicator turns to *issues* the moment a linked control's
  audit fails, has an open finding, or goes overdue.
- **In the suggestion panel** — the line-by-line reasoning above.
- **From the asset** — assets link to controls and to threats and vulnerabilities, so
  "which systems protect this asset" is answerable from the asset register.

---

## 6. Is it qualitative or quantitative? (MoM item 5 — Fahad)

**Both, on the same record**, which is what a bank needs:

- **Qualitative** — likelihood × impact on a configurable matrix (3×3 up to 6×6, default
  5×5), banded Low / Medium / High / Critical, plotted on the heat map.
- **Quantitative** — Annual Loss Frequency × Single Loss Expectancy = **Annual Loss
  Expectancy**, on the same risk, alongside treatment cost. There are also separate Risk
  Quantification (Monte Carlo) and Scenario & Capital modules for material exposures.

In practice: qualitative across the whole register, quantitative on the top risks where a
number in rupees changes the decision.

---

## 7. Framework baselining (MoM item 3 — Sidra)

**ISO/IEC 27005:2022** and **ISO 31000:2018** are both installable from Compliance →
framework templates (34 clauses each). Installing 27005 and then configuring the matrix to
match its risk criteria is the intended pairing — 27005 clause 6.4.3 is precisely the
"define your likelihood and consequence scales" step, and the matrix editor is where you
record them.

The matrix is yours to define: size 3×3 to 6×6, and a label plus a written definition for
every rung of both axes ("3 = Possible — could occur once in 1–3 years"). Severity bands
scale with the matrix automatically; at 5×5 they remain the familiar 1–4 / 5–9 / 10–14 /
15–25.

**The heat map shows the calculation, not just the colour.** Each cell displays the
likelihood, the impact, the resulting score, its band, and the actual risk references
sitting in it — so "how was this calculated?" is answered by hovering, and the band
thresholds come from the server so the map can never disagree with the register.

---

## Summary

| Your concern | Where it stands |
|---|---|
| How is residual calculated? | It is assessed, not calculated. The system proposes and explains; the owner decides. |
| Inherent and residual are different | Two independent assessments on the same record, stored separately. |
| Existing controls not visible | Line-by-line on the suggestion, plus the Controls tab and live control health. |
| Auto-calculate during threat assessment | Suggested automatically from linked controls, and it self-corrects when a control's assurance lapses. |
| Qualitative or quantitative? | Both, on the same record. |
| Baseline to 27005 / 31000 | Both installable; matrix and scale definitions configurable to match. |

**What we need from you:** your residual weighting (points per effectiveness rating and the
maximum reduction), and your likelihood/impact scale definitions if you already have them
written down.
