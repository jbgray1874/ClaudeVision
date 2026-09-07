# Programme status e-mail — 7 September 2026

Paste-ready. Figures reconciled against the combined status report of 7 September
(`reports/SDI-Programme-Status-2026-09-07.html`), Yogesh's status of 4 September and his
project plan tracker (week 04 Sep), and the shared workstation capital request of 3 September.
Keep the attachments together; the e-mail refers to them.

---

**To:** James Ryan; Jack Calow
**Cc:** Yogesh Kumar; Muhammad Yazir
**Subject:** SDI Intelligence — programme status 7 Sep: five jobs a week in parallel run, Drawing Search into UAT, workstation to order this week

---

James, Jack,

Eleven days on from the first combined report, here is where the three workstreams stand, and the
two decisions I need from you this week. The full report is attached; the portal pages are
updated to match.

## In one paragraph

The estimating engine has moved from producing workbooks to a **five-jobs-a-week parallel run**
with James Ryan and Dave's estimating team, and one job has come back; over the weekend its four
documents were made to read one costed record. Technical Design's second
tool was **demoed and approved** on 2 September and the PDM phases have been re-planned against
real deployment days. **Drawing Search goes into UAT on Monday 7 September**; Client Briefing is
**on hold** and Muhammad moves to the manufacturing workstream. All three now have a home: **one
shared workstation, to be ordered this week**.

## 1 · SDI Estimating Intelligence — parallel run, five a week

**Five jobs ran last week** against the estimators' own sheets: 12349-02 (Fanatics gravity feeder
modules), 11762-17 (wire display), 11762-02 (steel shelf with vinyl graphic), 11908-21 (sunglasses
tray, priced at 1, 50, 100, 250 and 500) and 12552 (Infinity drawer). **Five more run this week**,
starting with 7332-01 for Harrods.

**Tim has returned one — 12349-02 — line by line.** It found three real defects (the engine costed
three modules where the enquiry was for one; a bonded acrylic box came through as one flat where
the pack holds seven; powder at £2.14 against his £0.72). All three were fixed the same day and
every line now matches his sheet. **The other four are with Dave's team.** The September / October
go-live target is decided on reviews returned, so the ask of estimating is the same as the run
rate: five out, five back.

What landed in the engine since 27 August, in plain terms:

- **Automated e-mails.** When a run completes, the workbook, report and covering note go to the
  people who asked for it. The customer quote is withheld while an estimate is provisional.
- **A much better explanation of the P&L.** An AI Explanation tab in the workbook, the same text
  in the report and the e-mail: every pound reconciled to the sheet's own totals, labour split
  into set-up and run with what it does at 1 to 250 off, and the lines that still need a person
  listed worst-first with the money at stake.
- **Parity reporting through the portal.** The engine's sheet against the estimator's, block by
  block, on every run where a manual sheet is attached, with the inputs behind each difference.
- **One estimate at every quantity asked for**, one workbook per quantity — the norm now.
- **One record behind every document, and a report an estimator works from** (7 Sep). The
  Harrods run showed the workbook, the e-mail, the report and the quote describing one estimate
  in four sets of words. They now all read one costed record, and the job report opens with the
  decisions still open — issue, part, assumption, action, the money riding on it — before any
  diagnostics. Sample attached (`SDI-Estimator-Page-Sample-20260907.png`).
- **The workbook is five tabs, not nine** (7 Sep). The estimators' own three untouched, then an
  AI Explanation tab that leads with the decisions and an AI Provenance tab that says, for every
  line, the value used, its source, how firm the evidence is and what the estimator has to do —
  and where a part's name did not track through the pack.

**After the parallel run — the automated pipeline, and on demand.** The parallel run is what we
are on now. Once through it, the engine becomes a button an estimator presses: **one button
imports the full and latest drawing pack** from Document Manager, **one click generates the
estimate with its explains and e-mails it with the client quote**, and **parity against the
manual sheet runs with the estimate** where a manual sheet exists, or is added afterwards where
the AI run comes first. Two pieces are in already: an estimator can **amend the estimate and
regenerate the quote** from their own figure, and **print the PDFs and DXFs of a pack** from the
portal. Beyond that, no timetable yet: **China quotations** (buttons in, analytics to follow) and
**multi-PDF packs** (working, needs testing; runs against our model or purely against an LLM).

Still open on this workstream: packaging and delivery are held at £0 by decision until the
estimators provide their own calculation; the supplier price lists (Elite, Eagle, Thermaset) are
still not loaded; three rates on the Harrods job are labelled indicative and wait on Tim.

## 2 · SDI Technical Design Intelligence — P2 approved, PDM re-planned

Yogesh demoed the second Document Manager tool to Ian B and Ed Cooper on 2 September. **Approved**,
and named **Production Design Extraction**. It is at 90% with a UI for user testing on 8 September;
this week it gained the DWG/PDF revision-mismatch rule (surveyed across 297 Boots projects), a fix
for the OneDrive "file missing" problem, an audit log and a shop-floor e-mail option. The Design
Vault feasibility is complete and with me.

**Dates.** P1 stays at 15 September. P2 moves from 24 to **29 September**. The four PDM phases move
by one to three weeks — P3.1 to 6 Nov, P3.2 to 30 Nov, P3.3 to 19 Jan, P3.4 to **1 Feb 2027** —
because the tracker now carves each tool's deployment days out of the next tool's build. That is
the honest version of a one-developer plan, not a slip. **The Design Vault proof of concept needs a
Linux machine by 10 September**, which is the workstation below; if it is late he switches to the
design-generation work rather than waits.

## 3 · SDI Creative Design Intelligence — UAT this week, one project on hold

**SDI Drawing Search Intelligence goes into UAT on Monday 7 September** with the studio designers,
ahead of studio-wide go-live on ~25 September — still the earliest go-live in the programme, and
still with no buffer between the end of UAT and rollout. The tool and Muhammad's user guide are on
the portal (links below).

**SDI Client Briefing Intelligence is on hold** from 4 September. Yogesh and I will pick it up as
a set of AI real-time agents rather than a single application; a plan follows. **Muhammad moves to
business analysis for the Manufacturing / CNC SDI Intelligence automations** — the workstream
that closes the loop to the shop floor and has had no written record until now. Specifically: map
the live production spreadsheet for BOMs and routes for the warehouse, so that process can be
automated and is understood on the way into Sage X3; map the design DXF process onto CNC
machining; and document both as a BRD and user stories, planned and executed with me. Client
Briefing is written up to an extent before it is parked. He keeps Drawing Search through UAT and
go-live, and his user guide is attached.

## 4 · The shared workstation — this week

One machine hosting all three: the estimating engine (on my laptop today), Drawing Search (needs
to be always-on beside the file server) and the Design Vault (Linux VMs, from 10 September).
**£4,800–5,050 ex-VAT built and warranted**, Scan 3XS as the target build with Lenovo and Dell/HP
quoted alongside. Full spec attached; every figure in it is measured from what we already run.

**Two decisions before I place the order:**

1. **Can it sit on the same LAN as sdi-dc01?** (IT.) Free, and the single most important line in
   the request — over VPN, indexing takes days; on the same network, hours. It cannot be fixed
   later by buying more machine.
2. **Is AD integration for Drawing Search firm, or nice-to-have?** (Muhammad.) SolidWorks cannot
   run on Windows Server, so the search would run under Windows 11 Pro without AD group control.
   If AD is a hard requirement, the host OS choice reopens.

## Asks this week

1. **Approve the workstation** at £4,800–5,050 ex-VAT and confirm the two decisions above, so it
   is ordered this week and racked by 10 September.
2. **Five reviews back for five out** from Dave's team, starting with the four already issued.
3. **Packaging and delivery** — a calculation from estimating, so the two lines stop reading £0.
4. **Supplier price lists** — Elite, Eagle and Thermaset, so indicative figures become
   reproducible ones.

## Where to look

- Portal dashboard — http://localhost:8072/#dashboard
- SDI Estimating Intelligence — http://localhost:8072/#aisvc-estimating · guide: http://localhost:8072/guide
- SDI Technical Design Intelligence — http://localhost:8072/#aisvc-technical-design
- SDI Drawing Search Intelligence — http://localhost:8072/#aisvc-drawing-search · guide: http://localhost:8072/#fixture-guide
- SDI Client Briefing Intelligence (on hold) — http://localhost:8072/#aisvc-client-briefing

Attached: *SDI Programme Status — 7 September 2026* (combined report); *SDI Shared Workstation*
(capital request, 3 September); *SDI Project Plan Tracker — week 04 Sep* (Yogesh); *SDI Estimator
Page — sample* (PNG); *SDI Drawing Search Intelligence — user guide* (Muhammad).

Happy to walk either of you through any of it.

Thanks,
James
