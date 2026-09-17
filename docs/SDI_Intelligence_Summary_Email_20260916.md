# SDI Intelligence — four services, and what the numbers say

Wednesday 16 September 2026 · a summary of where the programme has got to, alongside the fuller status report

Plain-text twin of `SDI_Intelligence_Summary_Email_20260916.html`. The HTML is the one to send; this file is the record.

---

James, Jack,

A short one, and a positive one. The detailed status report has the caveats and the open items; this is what the programme has actually delivered, in the round.

**Four services are now real rather than planned.** The estimating engine has run eleven jobs in a fortnight against the estimators' own work and has feedback from all three of them. Drawing Search is live for the design and technical teams. Technical Design's second tool goes live on 29 September. Client Briefing is back on and further along than its status suggested. **Muhammad and I are preparing the KTP presentation**, which will carry the plans and live demonstrations of all of it.

## The fortnight, counted

| Figure | What it is |
|---|---|
| 11 | jobs run in two weeks, against a minimum of five a week |
| 3 of 3 | estimators have reviewed the engine's work — six job-reviews between them |
| ~40 | points they raised, every one now a rule that carries to every job |
| 32,422 | drawings live and searchable by the design and technical teams |
| 69 | numbered decisions on the engine's change register, each with its source and its proof |
| 5,957 | tests passing on the estimating engine — they run the engine, not a description of it |
| 363 | tests on Technical Design's second tool, up from about 240 in a week |
| 4 | jobs measured against the estimator's own sheet — mean variance 17.9%, one within half a percent on material |

## SDI Estimating Intelligence — the loop is closed

The thing that was missing in August was feedback. It is no longer missing. All three estimators have now reviewed the engine's work on their own jobs and replied in detail — Tim on three, Howard on two, Tony on one — and **every point has gone in as a rule that carries to every job**, recorded with the estimator's name, the job it came from and the test that proves it. Tim's fourteen points on the Fanatics feeders became fourteen changes; his four on the Boots comms bar became four more, answered the same day.

**One workbook now covers every quantity.** An enquiry asked at 10, 50, 250 and 1,000 comes back as a single spreadsheet with the estimators' own price-break tab filled in and a Quantity Breaks tab that recalculates the whole estimate at each one, with order-level freight divided by that quantity rather than landed on every unit. That replaces a file per quantity, which is what the estimators were being sent before.

**The engine has started learning the shop rather than the drawing.** Production runs 1.0 mm steel where a drawing says 0.9. A mitred tube leg is sawn, not bent. Welds are dressed to the customer's own standard. A plated part is packed out and packed back as two operations. None of that is written on any drawing; all of it is now in the engine with the estimator's name against it.

**And it is now measured against their own sheets.** Four of the eleven jobs have both books side by side — the engine's workbook and the estimator's manual estimate for the same job, compared at the same quantity. The mean variance on material plus labour is **17.9%**, the engine reads under the manual on three of the four, and on the M&S graphic holder the material agrees to within **half a percent**. Where the engine reads low it is because it refuses to price a line nobody has quoted — plating and freight on the Harrods stand, packaging and two fixings on the feeders. That is the number the go-live decision rests on, and it now refreshes every week.

**Next from this workstream:** Tim has asked for the Boots Coffret hospital kit at two quantities with the route and the bill of materials alongside the cost — the first time the route has been wanted as a deliverable in its own right, and a good sign of what the estimators now expect from it.

## SDI Technical Design Intelligence — and a win that helps both sets of estimators

Yogesh's second tool, Production Design Extraction, is being hardened for its **29 September** go-live, with the feature branch merging next week. Its test count went from about 240 to 363 in a week. Six short demo videos with write-ups now cover the SolidWorks tools, the extraction endpoint and the Document Manager work, so it can be reviewed without booking meetings. The in-house PDM's first phase has started — its environment is built.

**The part worth drawing out:** the drawing packs are going to be prepared automatically **for manual estimating as well as for the AI engine**. The same tool that collects the correct, current pack for a job will serve both, so Dave's team stop assembling packs by hand whether or not a job goes through the engine. That is a saving that lands immediately and does not wait on go-live.

## SDI Drawing Search Intelligence — live, and ahead of its date

Live for the design and technical teams, out of UAT and ahead of the 25 September date it was tracking. It searches **32,422 drawings** by what is actually printed on the sheet — the client, the material, the finish, the RAL, the job number, a line from a note — and opens the SolidWorks or 3ds Max file straight from the result rather than sending a designer hunting through folders. Ian tested it and liked it, which is why it went in. It is on the SDI Intelligence portal menu, below its user guide.

**The next step is integration.** The search runs as its own web application and is not yet joined up with SDI Intelligence — today the portal links to it rather than containing it. Bringing the two together is what turns a drawing found in the library into a part code the price chain already understands.

## SDI Client Briefing Intelligence — back on, and further along than it looked

It came off hold on 4 September and Muhammad has picked it back up. It is worth correcting the impression that it was starting from nothing — there is already more built than the status suggested:

- **A web template** — already developed, and now being enhanced rather than designed.
- **An e-mail AI agent** — analysing client communications, so a brief can arrive as an e-mail, a recorded call or a voice note and still come back structured.
- **Design and account manager details** — collated against the brief, so the right people and the account's own history come with it.
- **The point of it** — to promote communication and collaboration across the four teams: one consistent brief, with what is missing named, and nothing booked without Jonathan's approval.

Honestly early — two briefs have been through it, both Muhammad's own. What it needs is time with Jonathan on real briefs, and that is the only thing holding it.

## Sage X3 — the data migration, and the nearest hard date we have

Worth stating beside the four, because it lands before any of them. **All data in Sage X3 by Friday 30 October**, ahead of the ERP's own go-live in January. Eleven X3 templates are covered by built extract views over eighteen core source tables — products, bills of material, customers and open sales orders, suppliers and open purchase orders, the AR, AP and general ledger openings, and stock. The rest of the roughly three hundred tables in SDI Live, and the Crystal Reports layer above them, are being given a stated disposition rather than left to survive by accident.

**It is a target with a gate.** Three third-party items have to clear by **Friday 16 October**, and the cleansing behind it is real record-level work with named owners — 20,724 items carry a blank description, which is half the catalogue. If those three are not confirmed in the first week the date rebaselines to mid-November, which is a great deal cheaper than defending a date into a failed cutover. The full plan, every row count and the disposition of every table is on the portal.

## The KTP presentation

**Muhammad and I are preparing it now.** It will carry the plans for each workstream and live demonstrations of what is already running — the estimating engine on a real drawing pack, the drawing library on 32,422 sheets, the Document Manager tools, and the client briefing template. Everything in it is working software rather than a proposal, which is the strongest position we could be presenting from.

## Two things we need, and they are the same two as last week

**The server — the blocker.** It was needed by 10 September and is not ordered. Jack has the specification from the meeting and quotes to work through, and will place the order as soon as he can. Until it exists the designers and the estimators cannot get test access to the Technical Design tools, and the estimating engine keeps running on a laptop. It sits on all three workstreams' critical path and nothing else on this list competes with it.

**Prices and quotes — in progress.** The supplier price lists are being gathered, and the outstanding trade quotes with them. Every line the engine shows as awaiting a price traces back to one of these rather than to anything in the software — the machinery to load and use them is built and tested, and it is waiting on the files.

Happy to walk either of you through any of it, or to demonstrate any of the four.

Kind regards,
James

James Gray · AI and Systems Controller · SDI Displays · 075858 16501 · wearesdi.com

### Where to look

| Page | Link |
|---|---|
| Portal dashboard | http://10.0.0.5:8071/#dashboard |
| SDI Estimating Intelligence | http://10.0.0.5:8071/#aisvc-estimating |
| SDI Technical Design Intelligence | http://10.0.0.5:8071/#aisvc-technical-design |
| SDI Drawing Search Intelligence | http://10.0.0.5:8071/#aisvc-drawing-search |
| SDI Client Briefing Intelligence | http://10.0.0.5:8071/#aisvc-client-briefing |
| AI Programme · AI Roadmap | http://10.0.0.5:8071/#programme · http://10.0.0.5:8071/#roadmap |

Attached: SDI Programme Status issue 3 · SDI Estimating Intelligence engine status, with the numbers above and the parity position set out in full.
