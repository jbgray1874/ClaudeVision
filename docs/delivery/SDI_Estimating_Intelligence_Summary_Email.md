# Summary email — SDI Estimating Intelligence, controlled launch

Paste-ready. Figures reconciled against the delivery plan and Gantt of 5 August 2026.
Keep the two attachments together; the email cites task numbers that only resolve in the plan.

---

**To:** Matt Evans; Charlotte Blackwell
**Cc:** James Ryan; Tim; Dave; Yogesh; Muhammed
**Subject:** SDI Estimating Intelligence — controlled launch 7 September, plan and status attached

---

Matt, Charlotte,

Following the Mission Critical Delivery Directive, the required outputs are attached: a dated
reverse delivery plan to launch, and a status report against the eight minimum acceptance gates.

**We are confirming Monday 7 September as the committed controlled-launch date.** Overall status
is **Amber**. The date is achievable and the plan holds it, with two dependencies that need
decisions this week rather than engineering effort.

## Key updates

**The estimating workflow now runs end to end.** On Wednesday a live Boots enquiry was estimated
entirely from a web page — drawings picked from the CAD share, quantity set, one button — and a
complete deliverable set filed automatically to the estimating share: costed workbook, client
quote, decision report, summary data and the full run log. Until this week that took a developer
at a command line. A short screen capture of the run is embedded in the attached report.

**Eight live jobs have now been run with estimators** across three customers — two Boots jobs with
Tim, four M&S jobs with James Ryan, and two Tesco jobs being priced for Nick Garrish. **Four sheets
have been reviewed and returned and two more are under way.** That is a real step up, and it has
been achieved in a very busy week for estimating: James Ryan increased testing and re-affirmed his
support, reviewing four in short order, and Tim picked up both of his live estimates despite the
workload.

**The engine has had a substantial correctness pass.** Order quantity is now honoured end to end,
assembly hierarchy from the SolidWorks models is applied so an operation charged on a parent is not
charged again on its child, and every run reports its own gaps rather than absorbing them.

**Licensing is settled.** No separate SolidWorks API licence is required — the engine uses the COM
API included with a seat. The seat and an Office licence *are* required on whichever machine runs
estimates, and both are now carried in the hardware specification.

## Key risks

**1. There is no server that can host this.** *(High)*
SDI-APP01 is a 32 GB host already carrying the SolidWorks PDM estate, the TRUMPF stack and two SQL
Server instances. The estimating engine automates SolidWorks and Excel directly, which needs a
licensed interactive session and several gigabytes of memory. Putting it there would mean a hung
Excel takes PDM down rather than failing an estimate. The service is therefore in test on one
laptop and cannot be given to the wider team as it stands.
*Mitigation:* launch on an interim host and move to permanent hardware once available.

**2. Hardware is unlikely to arrive before the launch date.** *(High)*
Lead times are not yet established, but between resourcing, cost approval and availability a
permanent server is unlikely to be ready by 7 September. Rather than let procurement move the date,
the plan launches on an interim host and cuts over afterwards.
*Decision needed:* approval of that approach, and authority to proceed to quotation.

**3. Validation throughput is limited by live estimating workload.** *(Medium, improving)*
The acceptance gates take estimator review as their evidence, so the plan has to be paced around
the validation the estimating team can accommodate alongside a large queue of live customer work.
Testing has stepped up this week, which is why this is Medium rather than High.
*Mitigation:* a standard feedback form by 7 August so each review costs minutes rather than an
afternoon, and the plan built on the rate that is genuinely achievable.

**4. The service has no user authentication.** *(Medium)*
Anyone who can reach the port could browse the CAD vault with the service's rights. Windows
Authentication and AD group control are scheduled before launch; until then use stays with named
developers and testers.

**5. Hand-drawn packs have no test data.** *(Medium)*
The agreed accuracy target for hand-drawn is 40–50% and none have been run.
*Recommendation:* explicitly exclude hand-drawn from v1 and park it, rather than let it become a
launch dependency.

## Key milestones

| Date | Milestone | What it means |
|---|---|---|
| **Fri 7 Aug** | Directive outputs complete | Launch date confirmed, v1 definition of done written with exclusions, reverse plan dated, Jira board live, testing calendar agreed. |
| **Mon 17 Aug** | No-silent-failures gate closed | Every remaining case where a blank, a zero or an unlabelled fallback could reach an estimator without being flagged is closed. |
| **Tue 25 Aug** | Release candidate frozen | v1.0-rc1. After this date no scope change enters v1 without Charlotte's approval; anything later is parked. |
| **Tue 1 Sep** | Interim host live | The service deployed off the laptop, with the service account, share rights and access control in place. |
| **Wed 2 Sep** | Estimator UAT complete | The people who will use it have used it and signed off that the output is understandable, editable and usable in the existing workflow. |
| **Thu 3 Sep** | Operationally ready | SOP published, estimators trained, support route and manual fallback documented. |
| **Fri 4 Sep** | **Go / no-go** | A documented decision by Charlotte against all eight gates. If the evidence is not there, the honest outcome is a dated slip rather than a launch. |
| **Mon 7 Sep** | **Controlled launch** | AI-first on the agreed live scope, with manual fallback available throughout. |
| **7–18 Sep** | Hypercare | Defined response times and a daily check-in for the first two weeks of live use. |
| **21–25 Sep** | Benefit review | Measured estimating time released, against the baseline established in August. |

## Decisions requested this week

1. Confirm **7 September** as the committed controlled-launch date.
2. Approve the **interim-host approach**, so launch is not coupled to hardware lead time.
3. Authorise the **hardware assessment to proceed to quotation** — dedicated estimating host,
   memory uplift for SDI-APP01, one SolidWorks seat and one Office licence.
4. Agree **hand-drawn packs are out of v1** and parked.
5. Agree the **validation rate** that is realistically achievable alongside the live estimating
   queue, so the plan is built on it rather than on an assumption.

Attached:

- *SDI Estimating Intelligence — Delivery Plan & Status* (status against all eight gates, risks,
  infrastructure assessment, embedded demonstration)
- *SDI Estimating Intelligence — Delivery Plan* (Gantt: 39 tasks across 7 phases, 586 hours, with
  owners, dependencies and dates)

Happy to walk either through ahead of the weekly review.

Thanks,
James
