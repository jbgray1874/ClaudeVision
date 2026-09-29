# SDI Intelligence — what has changed in the last fortnight, and where to see it

Tuesday 29 September 2026 · every section links to the page it was made on

Plain-text twin of `SDI_Intelligence_Programme_Email_20260929.html`. The HTML is the one to send; this file is the record.

---

James, Jack,

A fuller note than usual, because a lot has moved. **Each heading below links to the portal page where the change was made.** Links go to the server copy of the portal; the same pages are on the estimating laptop at localhost:8072.

Six things. The estimating wave has put **twenty packs** in front of the estimators, with **eight reviews** back. **Sage X3** now loads and tests area by area, **estimating first**. The **Design Vault** reaches its go/no-go at the end of October. **Drawing Search** is on trial with the studio. **Client Briefing version 2** runs on Jonathan's live jobs. And **the server is being ordered**.

## 1 · SDI Estimating Intelligence — twenty packs out, eight reviews back
http://10.0.0.5:8071/#aisvc-estimating · laptop: http://localhost:8072/#aisvc-estimating

The September wave has put **twenty estimate packs** in front of four estimators — Howard, Tim, Dave and Tony — and **eight detailed reviews** have come back. Every point went into the engine as a general rule, not as a correction to one workbook. Twelve jobs are now integrated; seven are awaiting review, the newest **12645, the Tesco DRS external shelter**, sent to Dave today.

Two things changed how the work is done. **Each pack is now scored against its own drawings before it is sent**: a pass table is written first, and a book that fails a row is fixed in the engine and re-run, never edited by hand. On 12645 the faults found in the early books became eleven general rules instead of a list of corrections for Dave. And **every run now writes a BOMs and Routes pair** beside the estimate, which is what Tim asked for on 16 September and is the shape a Sage X3 upload takes.

Where the reviews prove it, stated as a variance and a direction: material to within a penny on 10975-02; about 6% from the manual estimate on 11908-21; on 1176-02 the AI is about a third high at 10 off, and one line, the vinyl graphic the customer had already priced, carries more than all of it. Without that line the AI is about 17% under. Dave on the 11650-06 book: *“This looks good now.”*

## 2 · Access Supply Chain → Sage X3 — load and test together, estimating first
http://10.0.0.5:8071/#aisvc-x3 · laptop: http://localhost:8072/#aisvc-x3

The plan has changed for the better. **Loading and user testing are one cycle**, area by area: each area is loaded into test, tested by its own users on real SDI data, fixed, then kept current by incremental updates. **Estimating goes first**, in the week of 5 October: products, prices, BOMs and routes, with Dave's team uploading sample estimates and running the standard reports, including how our estimating tools connect.

All **813 source tables** are classified (21 carry the migration), and every record in 8 of the 13 load templates has a status and a reason. The headline numbers: about 16,400 of 41,645 products are current; of 10,738 current products with no main description, all but 51 have the text in another field; 918 of 936 open works orders need an end date, which one rule clears. Acuity's 16 new templates are mapped field by field (207 fields, 22 waiting on Acuity's configuration answers, four of them critical). We expect to load roughly 40% of product, BOM and route data and about 60% of customers and suppliers.

**Every area loaded and user-tested by Friday 30 October**; the dress rehearsal and cutover move to November, to be confirmed; the ERP goes live 4 January 2027. Routes are in scope.

## 3 · SDI Technical Design Intelligence — the Design Vault reaches its decision
http://10.0.0.5:8071/#aisvc-technical-design · laptop: http://localhost:8072/#aisvc-technical-design

Yogesh has the **SDI Design Vault's core loop working** (browse, lock, edit, check in to GitLab), and the designers received it well on 23 September. It is about 90% technically proven. Its advantage over PDM Standard is an API that the estimating tools, Sage, QC and AI can reach. A **go/no-go on Standard against in-house is set for the end of October**, decided on cross-project and library referencing, which he builds and demonstrates next.

The extraction endpoint is now correct end to end for the 12633 family (582 tests, verified against the W: share). P2's user testing with Ed and Ian has not started: it **waits on the test server**, so its date is to be re-planned against the server below.

## 4 · SDI Drawing Search Intelligence — on trial with the studio
http://10.0.0.5:8071/#aisvc-drawing-search · laptop: http://localhost:8072/#aisvc-drawing-search

The design and technical teams are on a **two-week trial**, with their feedback due at the end of the month and changes to follow. It still runs from Muhammad's own machine; its always-on home is the server below.

## 5 · SDI Client Briefing Intelligence — version 2, on Jonathan’s live jobs
http://10.0.0.5:8071/#aisvc-client-briefing · laptop: http://localhost:8072/#aisvc-client-briefing

A big week. The design team saw version 1, liked it, and asked for 25 changes. **Version 2 is built from them, with 19 done and 3 partly done**, and runs alongside version 1. It shows each job's size, how much information is in and whether it is booked. Each person has their own view. Jonathan's three everyday e-mails are drafted for him to check and send, and his calendar is in the tool, read-only. It **runs on his live jobs**, 24 of them today, picked up automatically.

Voice notes are written up on our own machine, so there is no AI cost and the client is not recorded. WhatsApp is built and **needs IT to set up a secure connection** for the Meta test number. Every AI call is logged: $2.92 so far.

## 6 · The SDI Intelligence server — ordered
http://10.0.0.5:8071/#servers · laptop: http://localhost:8072/#servers

The server all three workstreams have been waiting on is **being ordered this week** from Scan 3XS. It has a **three-week lead time**, then about **a week's build** between the two of us, so it is in service in the **week of 26 October**. The specification is an AMD Threadripper PRO 9975WX (32 cores) on an ASUS Pro WS WRX90E-SAGE SE, with 128 GB of DDR5 ECC memory, an NVIDIA RTX 4000 Ada SFF 20 GB graphics card, 2 × 2 TB NVMe drives and a 3-year warranty. The price is **£13,155.28 inc VAT**.

It is sized to run an estimate driving SolidWorks with one or two more beside it, Drawing Search and the Design Vault together. The operating system and licensing, RAID and backup, a UPS and its place on the network are for us to settle before it arrives, so that the build week is spent building.

## Everything above, on the portal

| Page | Server | Estimating laptop |
|---|---|---|
| **Dashboard** — all workstreams, the Sage X3 plan and the server at a glance | http://10.0.0.5:8071/#dashboard | http://localhost:8072/#dashboard |
| **AI Roadmap** — the phases, Sage X3 and the server | http://10.0.0.5:8071/#roadmap | http://localhost:8072/#roadmap |
| **AI Programme** — the timeline | http://10.0.0.5:8071/#programme | http://localhost:8072/#programme |
| **SDI Estimating Intelligence** | http://10.0.0.5:8071/#aisvc-estimating | http://localhost:8072/#aisvc-estimating |
| **SDI Technical Design Intelligence** | http://10.0.0.5:8071/#aisvc-technical-design | http://localhost:8072/#aisvc-technical-design |
| **SDI Drawing Search Intelligence** | http://10.0.0.5:8071/#aisvc-drawing-search | http://localhost:8072/#aisvc-drawing-search |
| **SDI Client Briefing Intelligence** | http://10.0.0.5:8071/#aisvc-client-briefing | http://localhost:8072/#aisvc-client-briefing |
| **SDI Sage X3 Data Migration** — the plan of record | http://10.0.0.5:8071/#aisvc-x3 | http://localhost:8072/#aisvc-x3 |
| **Server Infrastructure** — the new server in the inventory | http://10.0.0.5:8071/#servers | http://localhost:8072/#servers |
| **Status Reports** — issue 4 of the programme report, HTML and PDF | http://10.0.0.5:8071/#reports | http://localhost:8072/#reports |

**Still the thing we need from outside the programme:** the **supplier price lists** from Elite, Eagle and Thermaset. Every market figure on this month's books traces back to them. The machinery to load them is built, tested and waiting on the files.

Happy to walk either of you through any of it.

Kind regards,
James

James Gray · AI and Systems Controller · SDI Displays · 07585 816501 · wearesdi.com

Attached: **SDI Intelligence Programme Status**, issue 4 (29 September 2026), the full report, HTML and PDF, also on the portal's Status Reports page · **SDI Intelligence Testing Status** and the **Estimating Test Log**, with 12645 added.
