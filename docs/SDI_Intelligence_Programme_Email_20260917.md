# SDI Intelligence — what has changed this week, and where to see it

Thursday 17 September 2026 · every section links to the page it was made on

Plain-text twin of `SDI_Intelligence_Programme_Email_20260917.html`. The HTML is the one to send; this file is the record.

---

James, Jack,

A fuller note than usual, because a good deal has moved and most of it is now visible on the portal rather than described in an e-mail. **Each heading below is a link to the page the change was made on**, so this reads as a tour rather than a claim.

Five things: the estimating engine is now **measured against the estimators' own spreadsheets** rather than assessed by eye; the **Access Supply Chain to Sage X3 migration** has a dated plan with owners and a gate; **Drawing Search has a link the design team can use** for full user testing ahead of an imminent go-live; **Client Briefing is in full design and analysis** with a working template; and **drawing packs are about to be assembled automatically** for the manual estimators as well as for the engine.

## 1 · SDI Estimating Intelligence — parity, measured
http://10.0.0.5:8071/#aisvc-estimating

Until this week the only reading we had on accuracy was what the estimators said in words. We now have **four jobs where the engine's workbook and the estimator's own manual estimate sit side by side**, compared block by block at a matched quantity. This is the number the go-live decision rests on, and it refreshes every week as more pairs come in.

| Figure | What it is |
|---|---|
| 4 of 11 | jobs compared — a manual sheet exists and pairs with a run |
| 17.9% | mean absolute variance on material plus labour |
| 0.4% | closest material agreement — essentially exact |
| 3 of 4 | read under the manual — the safe direction |

| Job | At | Material | Labour | Combined | Why |
|---|---|---|---|---|---|
| 7332-01 · Howard · Harrods stand | 6 off | −17.3% | −27.1% | −24.8% | Plating and the freight to the plater carry no price — both awaiting current quotes rather than a figure off a sheet |
| 12349-02 · Tim · Fanatics feeders | 7 off | −21.1% | −23.5% | −22.9% | Same cause — packaging, delivery and two fixings unpriced on this book |
| 10975-02 · Howard · M&S holder | 10 off | +0.4% | +19.5% | +12.9% | **Material essentially exact.** One labour line is still with Howard to rule on |
| 11908-21 · Tony · sunglasses tray | 50 off | −66.4% | +35.3% | −10.8% | Labour over because Tony's review added the joinery route that was missing entirely; the material side is the open one |

**Two points on method, because they decide whether the number means anything.** Both books are read by the same block reader and each is reconciled to its own totals before anything is compared. And every pair is compared **at a matched quantity** — two of these were priced at different quantities, and a variance across two quantities is arithmetic about nothing, because set-up spreads over a different number on each side. No figure from a manual estimate is retained in our reports; parity is published as our own number and a variance.

11350-02 and 11350-01 have engine runs and no manual sheet, so no accuracy is claimed for them either way. If those books exist they complete the week.

## 2 · Access Supply Chain → Sage X3 — the dates
http://10.0.0.5:8071/#aisvc-x3 · also now a workstream on http://10.0.0.5:8071/#roadmap

The migration has a dated plan, an owner for every data area and a gate. **Eleven Sage X3 templates** are covered by built extract views over eighteen core source tables — products, bills of material, customers and open sales orders, suppliers and open purchase orders, the AR, AP and general-ledger openings, and stock. The remaining ~300 tables in SDI Live, and the Crystal Reports layer above them, each get a stated disposition rather than surviving by accident.

| When | What |
|---|---|
| Mon 12 – Fri 16 Oct | **Mobilise.** Owner named per data area, classification locked per table, the UDEF column analysis run, the Crystal Reports inventory opened, parity and QA over the eleven views. |
| **Fri 16 Oct** | **The gate.** Three third-party items must clear: the sign convention, non-production environment access and the product-category confirmation. If they do not, the date rebaselines to mid-November. |
| Mon 19 – Fri 23 Oct | **Cleanse, in parallel by owner.** 20,724 items carry a blank description — half the catalogue, and the single biggest piece. Behind it: the zero base prices, 66 duplicate part records, 51 BOM orphans, 74 blank postcodes, and one decision that settles 23,082 sales-order lines. |
| Mon 26 – Thu 29 Oct | Trial load master data Monday, transactions Tuesday, a full timed dress rehearsal against a frozen snapshot Wednesday, then **cutover Thursday evening** — access read-only, snapshot taken, all waves loaded. |
| **Fri 30 Oct** | **All data in Sage X3.** Go / no-go in the morning, with the FD signing the trial balance, the stock value, AR and AP and the sales and purchase order totals. |
| End Oct | The Crystal Reports register complete — every report identified, its source tables traced, and rebuilt in X3 reporting or retired with an owner. |
| Mon 4 Jan 2027 | **ERP go-live.** Not ours to move, and deliberately after the data lands. From this point the estimating engine reads its material and supplier prices from X3 rather than SDI Live, with dual-running validation across the changeover. |

**One thing still open before the plan is final:** whether routings and works orders are in scope for October. They are not among the eleven templates, and if they are now wanted it changes both the table dispositions and the load waves.

## 3 · SDI Drawing Search Intelligence — a link for Design, and full UAT
http://10.0.0.5:8071/#aisvc-drawing-search

**The design team now has a link.** It sits on the SDI Intelligence portal menu, directly below its user guide, and opens the search in its own tab. That is what puts the tool in front of every designer rather than on one machine, and it is what makes **full user acceptance testing across Design** possible ahead of an **imminent go-live**.

It searches **32,422 indexed drawings** by what is actually printed on the sheet — the client, the material, the finish, the RAL, the job number, a line from a note — and from the result a designer opens the SolidWorks or 3ds Max file straight into the software rather than hunting through folders. Ian has tested it. This week's fixes came from watching real use: opening the right drawing, and drawings filed in unusual places not showing at all.

**The next step after go-live is integration.** The search runs as its own web application; the portal links to it rather than containing it. Joining the two is what turns a drawing found in the library into a part code the price chain already understands.

## 4 · SDI Client Briefing Intelligence — in full design and analysis
http://10.0.0.5:8071/#aisvc-client-briefing

It came off hold on 4 September and is now **in full design and analysis** with Muhammad. It is worth correcting the impression that it restarted from a blank page:

- **A generic template, already developed** — built and in use. The work now is enhancing it, not designing it.
- **Partly written automatically** — **e-mail AI agents write into that template** from the client's own communications, so a brief that arrives as an e-mail, a recorded call or a voice note starts as a structured brief rather than as a blank form.
- **The account comes with it** — design and account manager details are collated against the brief, so the right people and the account's own history travel with it.
- **And why it matters** — communication and collaboration across the four teams: one consistent brief, the gaps named, and nothing booked without Jonathan's approval.

Honestly early — two briefs through it so far, both Muhammad's own. What it needs is Jonathan's time on real briefs, and that is the only thing holding it.

## 5 · Drawing packs, assembled automatically — for both sets of estimating
http://10.0.0.5:8071/#aisvc-technical-design

This is the piece of the programme that pays back fastest, and it is worth setting out on its own because it helps people who are not otherwise touched by any of it.

Today a drawing pack is assembled by hand: somebody finds the general arrangement, the detail sheets, the DXFs and the models, decides which revision is current, and copies them into a folder. It is done once for the AI engine and again, separately, for whoever is estimating manually. **The same tool is going to do both.** Yogesh's Document Manager work walks the project's SolidWorks references and collects the correct, current pack — the latest revision chosen from the data inside the file rather than from the filename — and it will deliver:

- **Into SDI Estimating Intelligence** — straight into the engine, so an estimate is built from what design has now rather than from whatever was last copied into a folder. One button, and the pack that arrives is the current one.
- **Onto the W production drive** — **for manual estimating.** The same pack, in the place the estimators already work from, assembled without anybody collecting it. Dave's team stop doing that job whether or not a given enquiry goes through the engine.

**Why it is worth naming separately:** every other benefit on this programme is gated on a go-live. This one is not. It lands when the tool does, it removes a job somebody does today, and it does so for the manual route as well as the automated one — which also means both routes are estimating from the same pack, so a difference between them is a real difference rather than two people looking at different revisions.

## Everything above, on the portal

| Page | Link |
|---|---|
| **Dashboard** — all five workstreams at a glance | http://10.0.0.5:8071/#dashboard |
| **AI Roadmap** — Sage X3 now sits here as a workstream | http://10.0.0.5:8071/#roadmap |
| **AI Programme** — the timeline, six dated milestones | http://10.0.0.5:8071/#programme |
| SDI Estimating Intelligence | http://10.0.0.5:8071/#aisvc-estimating |
| SDI Technical Design Intelligence | http://10.0.0.5:8071/#aisvc-technical-design |
| SDI Drawing Search Intelligence — the application is on the portal menu | http://10.0.0.5:8071/#aisvc-drawing-search |
| SDI Client Briefing Intelligence | http://10.0.0.5:8071/#aisvc-client-briefing |
| SDI Sage X3 Data Migration — the consolidated table view and the plan | http://10.0.0.5:8071/#aisvc-x3 |

**Unchanged, and still the two things we need.** The **shared workstation** was needed by 10 September and is not ordered; Jack has the specification and quotes to work through. Until it exists the designers and estimators cannot get test access to the Technical Design tools and the engine keeps running on a laptop. And the **supplier price lists** — Elite, Eagle and Thermaset — are what every unpriced line on an estimate traces back to; the machinery to load them is built and tested and waiting on the files.

Happy to walk either of you through any of it, or to demonstrate any of the five.

Kind regards,
James

James Gray · AI and Systems Controller · SDI Displays · 075858 16501 · wearesdi.com

Attached: **SDI Intelligence Programme Status**, issue 3 — the full report, including the Sage X3 section at the same depth as the portal · **SDI Intelligence Estimating Engine Status** — the parity detail, the rules now live, and the questions owned by people.
