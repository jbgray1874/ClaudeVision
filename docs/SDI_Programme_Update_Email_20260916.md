# SDI Intelligence · programme status

**Eleven jobs in two weeks · the estimators' feedback is in · Drawing Search live for the designers**

Wednesday 16 September 2026 · supersedes the combined report of 7 September

Plain-text twin of `SDI_Programme_Update_Email_20260916.html`. The HTML is the one to send; this file is the record.

---

James, Jack,

Nine days on from the last report, here is where the three workstreams stand. The portal pages on the laptop and the server are updated to match.

**In one paragraph.** The estimating engine has run eleven jobs in two weeks against the estimators' own sheets and, for the first time, the feedback has come back from all three estimators — Howard on two jobs, Tony on one, Tim on three — and every point has gone into the engine as a rule that carries to every job, not as a patch to one workbook. Six more jobs run this week. Technical Design's second tool is being hardened for its 29 September go-live and the PDM environment is stood up. Drawing Search is live for the design and technical teams — out of UAT, searching 32,422 drawings by what is printed on them, and now linked from the portal. Client Briefing is back on the agenda; it was on hold from 4 September and Muhammad has resumed it.

| Workstream | Owner | Next date | State |
|---|---|---|---|
| SDI Estimating Intelligence | James Gray | Sep / Oct 26 | Parallel run · 11 jobs in 2 weeks · feedback from all three estimators |
| SDI Technical Design Intelligence | Yogesh Kumar | 29 Sep 26 (P2) | P2 hardening · P3.1 environment up |
| SDI Creative Design Intelligence | Muhammad Yazir | Now | Drawing Search live · Client Briefing back on |
| Shared workstation | James Gray | Quotes to finalise | Needed before designers and estimators get test access |

## 1 · SDI Estimating Intelligence — eleven jobs, and the loop closed

Eleven jobs have run in the past two weeks against the estimators' own sheets, among them 12349-02 (Fanatics gravity feeder modules), 11762-17 (wire display), 11762-02 (steel shelf with vinyl graphic), 11908-21 (sunglasses tray), 12552 (Infinity drawer), 7332-01 (Harrods signage stand) and 0355255 / 10975-02 (M&S table-top graphic holder). Six more run this week, 11650-06 (Coffret hospital kit) among them.

The feedback is in, from all three estimators. Tim has returned three jobs, 12349-02 line by line. Howard has returned two — the table-top graphic holder and the Harrods stand — with a full reply on each. Tony has returned the sunglasses tray. Between them that is roughly forty specific findings, and the discipline has been the same for every one: the engine learns the method, the route and the evidence; it never copies a figure off an estimator's sheet. A number from a manual estimate is not a price source, even as a reference — prices come from SDI Live, a supplier catalogue or an identified current quote, or the line says plainly that it is awaiting one and who owns it.

What the three reviews changed in the engine, in plain terms:

- **Every quantity on one workbook.** Howard asked for the breaks on one sheet with the formulas showing. The estimators' own Material Price Break tab is now filled by the engine and a Quantity Breaks tab recalculates the same estimate at every quantity asked — 10, 50, 250 and 1,000 on his job — so the base sheet is deliberately run at one unit, where each department's set-up is visible rather than hidden in a volume average.
- **Roll goods by the length used.** Howard's tape was three strips at three pack prices; it is now priced by the length cut off the roll, and the roll price is asked of SDI Live each run — on every job with tape, edging or anything else sold by the metre.
- **One laser row per component, one set-up per sheet.** Howard's own sheet has five laser rows where ours blended two parts into one rate. Each component now has its own row at its own rate, and components that the nesting proves share one sheet share one set-up — never one each.
- **What the shop knows that the drawing does not say.** Production runs 1.0 mm steel where a drawing calls for 0.9 (a confirmed substitution rule, visible on the line, overridable by an estimator); a mitred square tube leg is sawn, not bent; the welds are dressed or not by the customer's own standard (M&S yes, TTI no); a plated part is packed out and packed back as two operations; brushing before plating is a named operation. Each is a rule with the estimator's name and date on it.
- **The joinery route exists.** Tony's finding was that whole operations were missing — edge banding, saw and spindle, bench work, set-up amortised over quantity. The engine now mints saw and spindle work from the drawing's own words, gives a board assembly its bench-fitting line, holds the edging specification (rate from the supplier catalogue), and separates each department's set-up from its run time — a convention his sheet and Howard's both confirm, so it is shop-wide.
- **A change register that is the operating contract.** Every rule above is a numbered decision (D-016 to D-078) recording who ruled it, on which job, whether it is generic or a scoped pilot from one job, where it is implemented and the test that proves it — so the estimators can see what the engine believes and why, and the same question is never asked twice. Test suite: 5,940 passing, and the tests now execute the engine rather than read its source.

Where the engine and the estimators still differ, it says so. On the Harrods stand, plating and freight to the plater are shown as awaiting current quotes rather than carrying a figure from anyone's sheet; on the graphic holder the remaining gap is one labour line Howard has been asked to rule on. Packaging and delivery are still held at £0 with a named owner until estimating provides the calculation, and the supplier price lists (Elite, Eagle, Thermaset) are still not loaded — both carried from the last report.

## 2 · SDI Technical Design Intelligence — P2 hardened, PDM environment up

Yogesh's week was Production Design Extraction (P2) hardening after the 2 September approval: the two checkouts untangled (UAT on 8000, feature branch on 8001), the licence key and password-less e-mail fixed, the fifteen missing BOM previews diagnosed (twelve were library hardware pointing at a folder that did not exist — repointed and verified; three are sheet-metal parts that must be re-saved in SolidWorks), and the project-10975 crash traced to stale SolidWorks lock files being opened as assemblies. It gained extraction history, diagnostics and a metrics endpoint, live mismatch alerts in Step 4 with recorded acknowledgement, and richer e-mail notifications; the test count went from about 240 to 363.

Six short demo videos with write-ups now cover the SolidWorks COM API, the file-extraction endpoint, the Document Manager API proof of concept and P2 itself, for review without meetings. The weekly design meeting with Ian B and Ed Cooper produced a clear action list: ISO release traceability (who released a drawing and when), overwrite behaviour on re-run, an isometric preview image for the estimating quote page, a "promote drawing files" button so estimating reuses the back end, and staging for self-service testing.

**Dates.** P2 keeps 29 September, with the feature branch merging to main next week. P3.1 has started: Ubuntu and Docker are installed for the PDM MVP. Two watch-points from Yogesh: one to two days absorbed by demo preparation and the design team's new e-mail and history requirements, and the server and hardware quotes still to be finalised before designers and estimators get test access — the workstation from the last report.

## 3 · SDI Creative Design Intelligence — Drawing Search live, Client Briefing back on

**SDI Drawing Search Intelligence is live for the design and technical teams — out of UAT.** It searches 32,422 drawings by what is actually printed on the sheet — the client, the material, the finish, the RAL, the job number, a line from a note — and from the same screen a designer opens the SolidWorks or 3ds Max file straight into the software rather than hunting through folders. Ian tested it and liked it, which is why it went in. Muhammad's fixes this week all came from watching real use: opening the right drawing, and not hiding drawings filed in unusual places — this year's Boots Dynamix drawings were not showing at all and now are. It has been added to the portal as SDI Drawing Search Intelligence, directly below its user guide. Next: more designers on it on real jobs.

**SDI Client Briefing Intelligence is back on the agenda.** The last report had it on hold from 4 September; Muhammad has resumed it. It takes a brief however it arrives — e-mail, a recorded call, a WhatsApp voice note — and turns it into one consistent brief: which of the four teams it belongs to, what can be filled in from what we already know about the account, and what is still missing, separating what blocks work from what can follow. It never books anything itself; every brief goes to Jonathan to approve. Honestly early: two briefs through it, both Muhammad's own, none yet on live work. What it needs is time with Jonathan and real briefs.

## Asks this week

1. Reviews back for the jobs still with Dave's team, at the run rate — six out this week, six back. The go-live target is decided on this number.
2. The server and hardware quotes finalised, so the workstation is ordered and the designers and estimators get test access.
3. Packaging and delivery — a calculation from estimating; and the supplier price lists (Elite, Eagle, Thermaset), so lines that are awaiting a price stop waiting.
4. Jonathan's time with Muhammad on a few real briefs, which is what Client Briefing is waiting on.

## Where to look

| Page | Link |
|---|---|
| Portal dashboard | http://10.0.0.5:8071/#dashboard |
| SDI Estimating Intelligence | http://10.0.0.5:8071/#aisvc-estimating |
| SDI Technical Design Intelligence | http://10.0.0.5:8071/#aisvc-technical-design |
| SDI Drawing Search Intelligence | http://10.0.0.5:8071/#aisvc-drawing-search · the application itself is on the portal menu |
| SDI Client Briefing Intelligence | http://10.0.0.5:8071/#aisvc-client-briefing |
| AI Programme · AI Roadmap | http://10.0.0.5:8071/#programme · http://10.0.0.5:8071/#roadmap |

Attached: SDI Programme Status, issue 3 (PDF) · SDI Estimating Intelligence — change register (decisions D-016 to D-078) · the estimators' reviews and replies for 0355255 / 10975-02, 7332-01 and 11908-21 · Yogesh Kumar status 11 Sep · Muhammad Yazir weekly update and project plan.

Happy to walk either of you through any of it.

Thanks,
James

James Gray · AI and Systems Controller · SDI Displays. Sources: SDI Intelligence commit history 7 – 16 Sep and change register D-016 to D-078; estimator reviews from Howard Thurley (10 and 15 Sep), Tony Ford (8 Sep) and Tim; Yogesh Kumar status 11 Sep; Muhammad Yazir weekly update.
