# SDI Intelligence — your four priorities answered, and what moved this week

Tuesday 6 October 2026 · every section links to the page it was made on

Plain-text twin of `SDI_Intelligence_Programme_Email_20261006.html`. The HTML is the one to send; this file is the record.

---

Matt, Charlotte, James,

Matt, thank you for the note of 30 September. This answers each of your four priorities with an owner and a date, then covers the week. **Each heading links to the portal page where the change was made.** Links go to the server copy of the portal; the same pages are on the estimating laptop at localhost:8072.

The headline: **the server is ordered**, with a build plan and a date. It is on site on 19 October, Jack and I build it over the two weeks after, and **AI estimating, drawing-pack extraction and Drawing Search go live on it on Monday 2 November** with a week in hand — a few days later than the "end of October" I gave you last time, and now a date with a plan behind it rather than an estimate. Go-live stays driven by testing and the estimators' and studio's sign-off.

## Your four priorities, point by point

| Priority | Where it stands | Owner · date |
|---|---|---|
| **1 · Server** — cost, order, dates, security | **Full installed cost, agreed with Jack:** hardware £10,963 ex VAT (£13,155.28 inc); Windows Server 2025 about £2,000 plus client licences, *only* if Scan supplies a board that supports it, nothing if we build on Proxmox; Windows 11 Pro for the virtual machine about £200; Office under our existing agreement; a possible SOLIDWORKS licence change for unattended use, unknown until our own agreement has been read this fortnight. **Indicative total about £13,200 ex VAT plus client licences.** **The increase over the September approval is about £5,963 ex VAT** on the hardware, because the machine now carries three services and the Design Vault side by side. **Order:** placed this week with Scan 3XS on a fourteen-day lead time. **Delivery** Monday 19 October. **Installation** 19 to 30 October: Jack builds the host and two virtual machines in the first week, I install the services in the second, known jobs are re-run against the laptop on 29 and 30 October. **Live Monday 2 November.** **Security and configuration:** remote access, firewall rules, backups with a tested restore, update windows, service accounts and a UPS are all decided in the build plan. Open: Scan's answer on the board (decides Windows Server or Proxmox), the SOLIDWORKS licence position, and Microsoft sign-in with MFA for starting jobs from outside the office. | James Gray · Jack Calow — **cost confirmed now · live 2 Nov** |
| **2 · Testing** — review dates with Dave | James Ryan agrees dates with Dave for the **eight packs awaiting review** (12552, 12312-01, 12633-10, 12633-00, 12527-22, 12173-02, 12696-01 and 9439-01-04) and for the **manual comparison sheets** that grow the parity KPI, protecting that time alongside the Sage estimating testing in the same weeks. Tim's and Dave's reviews of 30 September are in hand and in the engine. **Proposed:** dates agreed by Friday 9 October; reviews and sheets back by Friday 23 October, so that 2 November rests on them. | James Ryan · Dave Wright — **dates 9 Oct · returns 23 Oct** (proposed) |
| **3 · Pricing gaps** — supplier lists, customer prices | **Supplier price lists:** estimating has given me a spreadsheet of supplier contacts, and estimating and I are reaching out to them this week for a comprehensive digital catalogue or price list of generic items; Purchasing is coordinated through James Ryan. The loader is built and tested, and each list is loaded as it arrives. **Customer-specific quoted prices:** two reviews in a row (1176-02, 12567-01) were decided by a price somebody already had. The answer is a quoted-price entry on the run page, filed with the pack and carried to the estimate, the quote and the price history, so a figure the account manager holds is entered once. **Proposed:** requests to suppliers out by 9 October, first lists loaded by 23 October; the quoted-price entry in the engine by 16 October. | James Gray · James Ryan · Purchasing — **requests 9 Oct · loads 23 Oct · entry 16 Oct** (proposed) |
| **4 · Delivery focus** — studio feedback, into use | **Studio feedback:** Drawing Search feedback is expected next week, and Dave's new requirement (search by UPC or drawing number on the K: drive as well as W:) is the first change; the full Client Briefing tool is shown to the studio team next week for their reviews. **Into use:** AI estimating, drawing-pack extraction and Drawing Search go live together on the server on 2 November, each with its runbook and the portal's guides, driven by testing and sign-off. | James Gray · Muhammad Yazir · Yogesh Kumar — **feedback w/c 12 Oct · live 2 Nov** |

**Matt, for your decision now:** (1) confirm the server's increase of about £5,963 ex VAT over the September approval; (2) approve in principle the Windows Server licence of about £2,000 plus client licences, spent only if Scan supplies a board that supports it and it installs cleanly; (3) agree in principle that if the SOLIDWORKS licence position on unattended automation carries a cost, it comes back to you with the figure before we commit; (4) the Design Vault's direction — how far to take the in-house Vault against PDM Standard, given that a two to three month build delivers the core workflow but not every PDM feature. Everything else above is ours to deliver.

## 1 · SDI Estimating Intelligence — twenty-five packs, twelve reviews, four new books checked against a brief first
http://10.0.0.5:8071/#aisvc-estimating · laptop: http://localhost:8072/#aisvc-estimating

The wave stands at **twenty-five packs** (twenty-four issued, one held back), **forty-three since May**, and **twelve reviews back** from Howard, Tim, Dave and Tony. Four packs went out this week: the M&S card spinner and footwear riser to Tim, the M&S bag pricing hook to Tim and Dave, and the Harrods table-standing POS holder to Tony and Dave. For each, the drawings were read and **the right book written down as facts before the engine ran**, and a checker scores every book against them. The faults were found in the engine and fixed there, never on the sheet. Seventy numbered rules landed in the week; the suite stands at 7,731 tests.

**Tim's review of the lit header kit** is the sixth AI-against-manual comparison: about £240 a unit above his figure at 163 off, two-thirds of it one line, a printed side graphic priced from the market at £95 against the supplier's £13.19. His spot-welding point is already in: weld symbols are now read off each sheet, and a part whose sheet shows only spot welds is spot welded. **Dave** called the render-priced M&S recycling unit a good estimate for a non-SDI pack and briefed the 350-off re-run in plywood and steel, which now runs from a brief box on the portal.

Open for the estimators: packaging and delivery as market figures, the P.Coat set-up rate on small jobs, and the two items in your priority 3.

## 2 · Access Supply Chain → Sage X3 — the estimating tables load this week
http://10.0.0.5:8071/#aisvc-x3 · laptop: http://localhost:8072/#aisvc-x3

This week we are loading the **estimating tables — BOMs, routes and products — and customers and suppliers** into test. Once the estimating data is in on this first pass, user testing opens to **estimating, customer services, finance, and warehouse and manufacturing**, each on its own loaded area, with incremental updates keeping test current. Dave's team uploads sample estimates and runs the standard reports, including how the engine's BOMs and Routes output connects. **Every area loaded and user-tested by Friday 30 October** holds; dress rehearsal and cutover in November, to be confirmed; the ERP live on 4 January. Still from Acuity: the four critical configuration answers and the route template.

## 3 · SDI Technical Design Intelligence — the Vault handles the hard cases
http://10.0.0.5:8071/#aisvc-technical-design · laptop: http://localhost:8072/#aisvc-technical-design

Yogesh's **Design Vault now handles the scenarios Ian asked to see proven**: an administrator cancelling another user's checkout for holiday cover, cross-project and library referencing, WIP-to-Released workflow states with automatic revisioning, and a browser-only check-out and check-in so laptops need no desktop install. The **PDM handover meeting** on 30 September confirmed that PDM Standard keeps its metadata in SQL we are allowed to read, which de-risks a later migration whichever way the decision goes. The extraction endpoint is hardened on five live projects, 610 tests passing. The go/no-go stays at the end of October, run in parallel with PDM; the designers' hands-on testing follows on the server from 2 November. Yogesh has also started the SolidWorks assembly and part automation in parallel, because Brief Lite below will need it.

## 4 · SDI Drawing Search Intelligence — trial running, the K: drive next
http://10.0.0.5:8071/#aisvc-drawing-search · laptop: http://localhost:8072/#aisvc-drawing-search

The design and technical teams' trial runs on, with feedback expected next week. Dave has raised a new requirement: the team often search by UPC or drawing number on the **K: drive**, and the tool searches W: only. Extending it to K: is the next change. It goes live on the server on 2 November.

## 5 · SDI Client Briefing Intelligence — demonstrated to Matt, tested with Jonathan, on WhatsApp; and Brief Lite
http://10.0.0.5:8071/#aisvc-client-briefing · laptop: http://localhost:8072/#aisvc-client-briefing · Brief Lite: http://10.0.0.5:8071/#aisvc-client-brief-lite

A lot of work went into this one. Matt saw it and gave new directions. Jonathan ran it on real briefs: most were assigned to the right team, the right details were pulled from his e-mails and calendar, and he was happy with the structure. **WhatsApp is connected** on a test number, so anyone set up can ask about any brief by voice note or text and follow up. It is working and in testing; the full web tool goes in front of the studio team next week.

**Brief Lite**, from the meeting with Matt, is a lighter tool for account and project managers: describe the client's brief after a meeting and get back the full pack, including new concept visuals based on the SDI jobs, renders and estimates already indexed rather than generic AI images, a concept GA at the exact size asked for, a one-page client sheet and a full internal brief PDF. The blocker is OpenAI API credits for the 3D visuals, which Muhammad arranges next week. Muhammad has also completed the KTP Impact Log, Benefits Log and Risk Register for the LMC presentation, his main focus next week.

## 6 · The SDI Intelligence server — ordered, live 2 November
http://10.0.0.5:8071/#servers · laptop: http://localhost:8072/#servers

The machine runs Windows Server 2025 with Hyper-V. Everything people use runs in one Windows 11 virtual machine that owns the graphics card: the estimating engine and runner, the portal, Client Briefing, Drawing Search, Excel and SOLIDWORKS. A Linux virtual machine beside it carries the Design Vault and Technical Design's services. Jack and I log in from our desks without interrupting an estimate. The one point open with Scan is whether they can supply the build on a board that supports Windows Server at the same lead time; if not, we build on Proxmox and the £2,000 licence line is not spent. The hardware order and the dates do not depend on that answer. The week-by-week plan, the cost table and the risks are in section 05 of the attached report.

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
| **Brief Lite** — the new direction from Matt | http://10.0.0.5:8071/#aisvc-client-brief-lite | http://localhost:8072/#aisvc-client-brief-lite |
| **SDI Sage X3 Data Migration** — the plan of record | http://10.0.0.5:8071/#aisvc-x3 | http://localhost:8072/#aisvc-x3 |
| **Server Infrastructure** — the new server in the inventory | http://10.0.0.5:8071/#servers | http://localhost:8072/#servers |
| **Status Reports** — issue 5 of the programme report, HTML and PDF | http://10.0.0.5:8071/#reports | http://localhost:8072/#reports |

The proposed dates above are confirmed with James Ryan, Dave and Jack by Friday 9 October. Happy to walk any of you through the report.

Kind regards,
James

James Gray · AI and Systems Controller · SDI Displays · 07585 816501 · wearesdi.com

Attached: **SDI Intelligence Programme Status**, issue 5 (6 October 2026), the full report, HTML and PDF, also on the portal's Status Reports page · **SDI Intelligence server**, summary for the Managing Director and Finance Director (5 October) · **SDI Intelligence Testing Status** and the **Estimating Test Log**, with 12696-01 and 9439-01-04 added.
