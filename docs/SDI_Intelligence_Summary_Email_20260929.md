# SDI Intelligence — your four points, answered

Tuesday 29 September 2026 · in reply to Matt Evans, 17 September

Plain-text twin of `SDI_Intelligence_Summary_Email_20260929.html`. The HTML is the one to send; this file is the record.

---

Matt, Charlotte,

Thank you for the steer on 17 September. This takes your four points in turn and answers each with what has happened since. The full programme update and the status report (issue 4) go alongside it.

**In one line:** the server is being ordered. Three services go live on it at the end of October: AI estimating, the estimators' drawing-pack extraction, and Drawing Search. That go-live is confirmed by the parity evidence, not by the date.

| Figure | What it is |
|---|---|
| 20 | estimate packs issued in the September wave, to four estimators |
| 8 | detailed reviews back — Howard, Tim, Dave and Tony — every point now a general rule |
| 5 | AI-against-manual comparisons completed; mean absolute variance about 20% |
| End Oct | three go-lives on the new server: AI estimating, production drawing-pack extraction, Drawing Search |
| £13,155 | the server, inc VAT (about £10,963 ex), ordered this week |
| w/c 5 Oct | Sage X3: the estimating data loaded and user-tested first |

## 1 · A connected programme, not separate projects
http://10.0.0.5:8071/#dashboard

This is more true now than on 17 September, because the pieces have started to share dates and data:

- **One go-live date for three services.** AI estimating, Production Design Extraction (drawing packs into the production area for the estimators) and Drawing Search all go live when the server does, at the end of October.

- **Estimating feeds Sage X3.** Every estimate now comes with a BOMs and Routes pair: what parts are in the pack and what work each needs. The Sage X3 migration tests estimating first, from the week of 5 October, and how our estimating tools connect to X3 is an explicit test item.

- **Design feeds estimating.** Yogesh's extraction tool builds the correct drawing pack for both the AI engine and the manual estimators. Muhammad and I are analysing how to fast-track creative design by integrating automations with the search tool.

## 2 · Estimating — parity is the KPI, and it decides go-live
http://10.0.0.5:8071/#aisvc-estimating

Five AI-against-manual comparisons are complete. Each is shown as a variance and a direction; by our pricing rule, no figure from a manual estimate is quoted.

| Job | At | Variance | Key cause | Estimator intervention |
|---|---|---|---|---|
| 7332-01 · Howard | 6 off | −24.8% under | Plating and freight to the plater unpriced, awaiting quotes | 12-point review; shop times and rates adopted |
| 12349-02 · Tim | 7 off | −22.9% under | Packaging, delivery and two fixings unpriced on that book | 14 points; nine confirmed fixed |
| 10975-02 · Howard | 10 off | +12.9% (material +0.4%) | Material essentially exact; one labour line to rule on | Line-level review; material now to a penny |
| 11908-21 · Tony | 50 off | about +6% over | The joinery route was missing and has been added | One review |
| 1176-02 · Howard | 10 off | about +33% over | One line: a vinyl graphic the customer had already priced. Without it the AI is about 17% under | One line |

**Key causes.** On four of the five, the difference comes from a line with **no price source** (plating, freight, packaging, a price only the customer had), not from the engine's method. Where the inputs exist, as on the M&S holder's material, it agrees to within a penny. Each cause has become a general rule or a named open item: customer-supplied prices need a place in the workbook, and supplier price lists need loading.

**Estimator intervention.** On the reviewed jobs it ranged from one line (1176-02) to fourteen points (12349-02, nine fixed). On the newest books the sheet's banner now counts everything left for the estimator. On 12645 that is two shutters and the covers to price, 15 provisional steel lines and six market figures.

**Growing the number weekly.** A comparison needs the estimator's own sheet for the same job at the same quantity, and none has been filed for the twelve packs issued since 17 September. The ask of Dave's team is to attach the manual sheet wherever one exists. The testing pressure is on: 20 packs in the wave, with seven awaiting review.

## 3 · The shared workstation — being ordered
http://10.0.0.5:8071/#servers

Worked through with Jack. It is being ordered this week from Scan 3XS: an AMD Threadripper PRO 9975WX (32 cores) on an ASUS Pro WS WRX90E-SAGE SE board, with 128 GB of ECC memory, an NVIDIA RTX 4000 Ada SFF 20 GB graphics card, 2 × 2 TB NVMe drives and a 3-year warranty. **Three weeks' lead time, then about a week's build by Jack and me**, so it is in service in the week of 26 October.

**The one point that may need you.** The September request was a single workstation at about £5,000 ex VAT. The order is **about £10,963 ex VAT (£13,155.28 inc)**, because the same machine now runs three live services and the Design Vault side by side: one estimate driving SolidWorks with one or two more beside it, Drawing Search, and Yogesh's Vault and test server. It is being ordered on your existing approval. If the difference needs your sign-off, that is the only decision in front of it.

## 4 · Critical path, resource, and decisions for you
http://10.0.0.5:8071/#programme

- **Critical path: the server's delivery.** A slip in the three-week lead time or the build week moves all three end-of-October go-lives together.

- **Decision, end of October: the Design Vault.** Standard against our in-house Vault is a company direction. Yogesh's Vault is about 90% technically proven. The deciding feature is referencing parts across projects, which he builds and demonstrates next, measured against how PDM Standard behaves (confirmed with Ian today).

- **Resource: one developer carrying three things.** Yogesh is taking P2 to go-live, building the Vault's deciding feature, and now bringing the SolidWorks drawing automations forward from January/February in parallel, with December leave inside his plan. More hands are the only way to hold all three.

- **Resource: Dave's team in October.** The same estimators are asked for seven outstanding reviews, the manual sheets that grow the parity KPI, and the Sage X3 estimating tests from 5 October. That team is the programme's most contended resource. It needs protected time, or an agreed order of priority.

- **Outside the programme:** the supplier price lists (Elite, Eagle, Thermaset) and, for Sage X3, Acuity's four critical configuration answers and the route template before 5 October.

Happy to go through any of it, or to demonstrate what is running.

Kind regards,
James

James Gray · AI and Systems Controller · SDI Displays · 07585 816501 · wearesdi.com

Alongside: the **SDI Intelligence programme update** of 29 September (every section linked to its portal page) and **SDI Intelligence Programme Status**, issue 4, HTML and PDF, also on the portal's Status Reports page.
