# Automated Estimating: Why We Must Model the Process, Not the PDF

### Findings from the M&S Food Equipment tender — for estimators and production engineering
**SDI Intelligence / ClaudeVision · Banked jobs 0348837 · 0357299 · 0357831 · 0359131 · July 2026**

---

## 1. Executive summary

We have built and proven an automated estimating pipeline that reads drawing packs, extracts the bill of materials, assigns manufacturing routes, prices parts against the live catalogue and history, and populates the estimators' own workbook — with every figure traceable to its source.

It works. Four M&S products have been costed end-to-end with no manual intervention. On the hardest job (Cocktails Hero Bay, 60+ parts), costing bugs that once produced a distorted **£5,270** unit were fixed at source; the reconciled provisional figure is **£669.80**.

> **The central finding.** The pipeline is running on the wrong fuel. We are feeding a manufacturing calculation with a *presentation document*. A PDF drawing pack cannot drive a CNC machine — that is not controversial; it is how manufacturing works. The same limitation applies, for the same reasons, to automated *and* manual estimating.

The highest-value change available is not more software. It is **giving estimating the same data the shop floor already requires: DXF flat patterns, IGES/STEP solids, and native SolidWorks part and assembly files.** With those, the pipeline produces defensible, quotable numbers. Without them, it produces an honest provisional figure with a warning banner — correct behaviour, and a limit of the input, not something we can code around.

**We must not invent what the drawing does not contain.**

---

## 2. Banked jobs — workbook figures

Four products were driven end-to-end (PDF → extract → material/route → catalogue pricing → estimators' template → quote + review HTML). They stress different material families. **Unit costs below are the authoritative workbook totals** — the figures Excel itself computed, read back from each saved estimate.

| Job | Product | Unit (workbook) | Material | Labour | Parts | DXF | Credible |
|---|---|---|---|---|---|---|---|
| `0348837` | Horti Crate — timber (FSC pine / MR-MDF) | **£46.53** | £8.72 | £34.56 | 11 | 0% | 0% |
| `0357299` | 2 Wide Arch — steel tube frame | **£363.43** | £31.61 | £306.38 | 28 | 0% | 0% |
| `0357831` | Madrid Bulk Stack — steel + MDF | **£556.03** | £150.64 | £366.46 | 30 | 0% | 0% |
| `0359131` | Cocktails Hero Bay 4ft — steel + ply + tile + acrylic | **£669.80** | £291.26 | £331.65 | 69 | 0% | 9% |

*Source: Excel-computed totals stamped into each job's JSON (`wep-readback`), read via `scripts/banked_job_figures.py`. **DXF** = share of fabricated parts with a matched flat pattern. **Credible** = proportion of cost from reliable geometry. All four are `insufficient_data` — 0% DXF — so every unit is provisional and not reportable for quoting.*

### Reading the table

- **Material + labour does not equal the unit — deliberately.** The workbook adds its own rebate gross-up and overhead absorption on top of the manufacturing sub-total, exactly as on a manually prepared estimate. So adding the material and labour columns always falls short of the unit figure — e.g. Crate £8.72 + £34.56 = £43.28 against a £46.53 unit. That uplift is **7.51%–7.53% on all four jobs**: the same commercial treatment applied consistently on every sheet, not an error.
- **Every job is 0% DXF and provisional.** These are PDF-only packs, so no fabricated part carries a flat pattern. The credibility gate computes a total but marks it *not reportable*. These are working estimates for review, not quotable prices.
- **Arch is the outlier — flag it before anyone leans on it.** £306 labour against £32 material is a **9.7 : 1** ratio, where Cocktails is 1.1 : 1 and Madrid 2.4 : 1. On a tube frame with almost no sheet content that is directionally plausible (nearly all cutting, welding and dressing), but it is the figure in this set most in need of an estimator's judgement.

> **Status of these four totals.** Only **0359131 (Cocktails)** was costed on the build carrying the material de-pollution, tube-routing, assembly-parent and labour-throughput fixes in §3 and §5. The Crate, Arch and Madrid figures are exactly what their workbooks say, but predate those fixes and are **indicative pending a confirmation re-run** (`scripts/rerun_banked_jobs.ps1`). The direction of travel from the fixes is downward — they remove phantom cost — so treat these three as upper bounds rather than settled totals.

**What the pipeline proved (evidenced on these packs):**

- **BOM extraction** — multi-line BOMs including tubes, fixings, nutserts, LED. On Cocktails, 46 BOM lines against a 40-row template block: **39 shown individually, the remaining 7 consolidated onto the 40th row and itemised in full on a dedicated "BOM Overflow" tab — nothing dropped** (39 + 7 = 46).
- **Material streams separated** — sheet steel / acrylic / bought-in / other; no double-counting.
- **Routes follow material (after fixes)** — laser / fold / weld / powder for steel; joinery for real board; handling-only for tiles and catalogue bought-ins.
- **Catalogue bought-ins** — UDEF codes matched rather than fabricated.
- **Assembly parents excluded** — children carry cost; the top-level product line is not leaf-costed.
- **Estimators' own template** — same layout and formulas; the unit cost is Excel-computed, not a parallel black box.
- **Transparent review lists** — Verify items (weld cues, missing material, low confidence) instead of silent uncertainty.

**How to read the parity quote / report HTML:**

- **Unit numbers match the workbook** — use the table above as the estimate figure.
- **Take process detail from the review report and workbook routes**, not the quote's "What's included" bullets. Those bullets are a customer-facing summary; a defect that let drawing-note boilerplate reach them has been corrected, but packs generated before that fix may list generic processes (e.g. powder coat / diamond polish against a lacquered timber product). The workbook routes are authoritative in all cases.
- **Material lines on quotes may echo residual labels** (e.g. "Timber" next to mild steel). The labour block and stream split are the better check.
- **Any "geometry reliability" percentage is PDF vector extraction confidence** — how cleanly the page was read — *not* flat-pattern coverage. All four packs are **0% DXF** → provisional.
- **Qty basis differs by deliverable** — review reports often use qty 1; commercial quotes may scale. Confirm order qty before using order-value lines.
- **Long Verify lists are correct behaviour** — the system saying "check me," not "I failed silently."

**As good as the PDF allows.** On these four jobs the engine extracted essentially everything a structured read of a GA pack can support: BOM lines, labelled materials where present, finish pointers, catalogue codes, and provisional routes. Where accuracy stops is where the PDF stops — no flat-pattern blanks, no true bend features, no weld lengths, no part-level material properties. Pushing further would mean inventing geometry. The Verify lists and 0% DXF flags are evidence that we stopped at the honest boundary.

---

## 3. What each job proved — and what it fixed

Each job exposed a distinct defect class. Fixes were written as **general rules** (family, stock form, drawing convention) — not part-number patches — so later jobs inherit them.

### 0348837 — Horti Crate *(timber)*
FSC pine and MR-MDF; stated weights on the drawing; no fab DXF.

- **Proved:** timber/board path — material by mass (weight × £/kg) where no blank exists; joinery route (saw / CNC-rout / glue / lacquer) at real shop rates.
- **Defect:** material defaulted to mild steel; `FSC PINE` / `MRMDF` never applied → £0 material and £0 labour timed on geometry timber does not have.
- **Fix:** non-metal title-block override; timber/board normalisers; flat per-part joinery allowance for no-DXF board parts (flagged for estimator refinement).
- **Banked unit:** £46.53 (material £8.72 · labour £34.56).

### 0357299 — 2 Wide Arch *(metal / tube)*
Steel tube-frame arch; SDI GA with tube cut-lists.

- **Proved:** metal and tube path — geometry scan, bought-in recognition, BOM tree, tubes priced as sections not sheet.
- **Defect class (earlier runs):** catalogue tube matching could ignore length; tubes could land in the Sheet Steel block instead of BOM.
- **Fix:** length-aware catalogue matching; stock-form so tubes always route to BOM, never sheet.
- **Banked unit:** £363.43 (material £31.61 · labour £306.38) — labour-heavy relative to material; weld/dress content is an estimator check item.

### 0357831 — Madrid Bulk Stack *(mixed steel + MDF)*
Steel frame, MDF panels, ticket strip — first genuinely mixed job in the set.

- **Proved:** two material families in one job — steel laser/fold/weld/powder; board joinery; each on its own basis.
- **Defect class (earlier):** an unmapped finishing operation could fuzzy-match to the wrong department with no throughput floor — the same garbage-throughput failure mode later dominant on Cocktails.
- **Fix:** map finishing ops to the correct department; throughput floors so implausible rates are clamped and flagged.
- **Banked unit:** £556.03 (material £150.64 · labour £366.46).

### 0359131 — Cocktails Hero Bay 4ft *(steel + ply + tile + acrylic)*
Hardest job: 60+ parts, four material families, ~46 BOM lines.

- **Proved:** multi-family handling, dual-path BOM (deterministic + AI cross-check), live catalogue bought-ins, parent exclusion, estimators' template, credibility gate refusing "quotable" at 0% DXF.
- **Defects:** the full set in §5 — boilerplate TIMBER/POLISH, tubes on joinery, product parent as leaf, unbounded throughputs.
- **Outcome:** unit **£669.80** (material £291.26, labour £331.65), reconciled from a distorted ~£5,270; still provisional.

---

## 4. A PDF is not a manufacturing file

**You cannot machine from a PDF.** No CNC, nesting package, or press-brake accepts one. A PDF describes marks on a page — lines, text, positions. It does not describe a part: no material property, thickness attribute, bend table, feature tree, or assembly relationship. Those were never in the file.

> If a PDF does not contain enough information to **make** the part, it cannot contain enough information to accurately **cost making** the part.

Estimating is a manufacturing calculation. It needs the same class of data the manufacturing process needs.

### Not only an AI problem
The PDF is a poor input for **manual** estimating too:

- **Slow** — re-keying dimensions, quantities and thicknesses that already exist in CAD.
- **Error-prone** — every re-key is a transposition or missed-revision risk; a 60-page pack has hundreds of such opportunities.
- **Inconsistent** — two estimators on the same ambiguous pack produce different numbers because the pack does not define the answer.
- **Hides change** — a revised part looks identical unless someone spots the revision cloud.

Automating a PDF-based process makes it faster; it does not make the underlying data better. **We are automating around a problem that should be removed at source.**

> **M&S packs specifically.** These packs do not contain enough information for a trustworthy automated estimate on their own. They are GA presentation documents. Flat patterns, reliable per-part material properties, bend and weld definitions, and structured hierarchy are absent or ambiguous. What we extract is useful (BOM, counts, bought-ins, tube lists, finishes, provisional route). The credibility gate correctly reports **0% DXF on fabricated parts** and marks totals provisional. Only CAD — or, as a fallback, historical manufactured-cost matching — lifts that.

---

## 5. What a PDF cannot provide — real examples from this exercise

Each case is software reconstructing from an unstructured page what a CAD file simply contains.

| Manufacturing need | What the PDF gives | What DXF / IGES / STEP / assembly gives | Consequence when wrong |
|---|---|---|---|
| Material per part | Title-block text or shared legend on every page (`TIMBER PRODUCTS:`, grade tables) | Material as a model property | Steel tagged TIMBER → saw/glue/CNC instead of laser/weld/powder |
| Flat-pattern blank | Often absent; GA dims ≠ unfolded blank | The DXF *is* the flat pattern | No credible sheet cost or laser time → "dimensions required" |
| Bend count / lines | Occasional note; easy to miss | Bend features / DXF bend layer | Missed folds understate labour; invented folds overstate it |
| Cut length & cut-outs | Noisy page vectors — overshoots common | Exact perimeter + holes from DXF | Derived 6–8 m internal cuts on small brackets inflate laser hours |
| Tube size & length | Free text in a cut-list | Solid geometry — exact | Priced OK, but geometry weak; route can be mis-assigned |
| Weld length / joint | Weld symbol at best | Assembly mates / weld beads | Guessed weld time or blanket dress-weld |
| Hierarchy & qty | BOM tables of varying layout; parents mixed with leaves | Assembly tree — exact | Product parent costed as a leaf (~£389 phantom material) |
| Process note vs part op | Shared "POLISHING SPECIFICATION / 400 GRIT" on every page | Op only where finish requires it | Diamond polish on powder-coated mild steel — phantom labour |

**Example — boilerplate material.** The standard M&S legend includes *"TIMBER PRODUCTS: …"* on steel detail pages. The scanner found the word TIMBER and tagged steel as timber until labelled `MATERIAL:` was made primary and legend text rejected. In CAD, material is a body property — nothing to mis-parse.

**Example — polish note → polish op.** *"POLISHING SPECIFICATION IS 400 GRIT FINAL POLISH"* became a diamond-polish operation on powder-coated steel parts until gated to genuine polish/acrylic cues.

**Example — tubes as paragraphs.** Cut-list text prices correctly; page vectors do not give real tube geometry. STEP/IGES *is* the tube.

### Defects found → general rule applied

| Defect | Symptom | General rule |
|---|---|---|
| Boilerplate `TIMBER PRODUCTS` / `POLISH` | Steel → joinery; DPOL on powder-coated MS | Labelled `MATERIAL:` first; reject legend; genuine polish cue required |
| *SEE INDIVIDUAL DRAWINGS* as material | Placeholder treated as a family | Reject reference phrases; default and flag |
| Tubes tagged timber | Leg/post/rail took saw/glue/CNC | `stock_form = tube/section/wire` → never joinery route |
| Product GA line as a part | ~£389 phantom material on top-level line | Top-level `-00-` unit line = assembly parent |
| Bought-in specials fabricated | Tiles given saw/glue/CNC/powder | `-X` / tile / mosaic / graphic / vinyl → bought-in, no fab labour |
| Unbounded throughputs | CNC/glue/spray/dress in £100s–£1000s | Throughput floor/ceiling per op; substitution flagged |
| BOM larger than template | Fallback sheet or silent drop | Spill to BOM Overflow tab; consolidate; nothing dropped |

**Cumulative effect on Cocktails: £5,270 → £670.** None of these were arithmetic errors. Every one was mis-reading an unstructured document — and every one is absent by construction when reading CAD.

---

## 6. Why we deliberately refuse to guess

Unpriced or flagged lines are **intentional** — the most important design decision in the system.

- **Quantity not on the drawing** — powder kg, packaging, delivery (order-level commercial).
- **Not in catalogue and no geometry** — special tiles, graphics.
- **No flat pattern** — blank size and cut/fold time cannot be computed; flag rather than assume.

> **Hallucination risk.** An AI system asked for a number will produce a number. If the information is missing, it produces a *plausible* one — and a fabricated figure looks as authoritative on the sheet as a measured one. No asterisk. That is more dangerous than a blank. A blank says *"I need this."* A guess says nothing, and gets quoted and manufactured at a loss.

**The system transcribes and computes; it does not speculate.** Where it must assume so a job can be reviewed at all, the assumption is written on the face of the estimate. Cocktails produced 40+ explicit flags. When DXF coverage on fabricated parts is 0%, the credibility gate computes a provisional total but **refuses to present it as reportable**. That is the system telling the truth about its inputs — and it should be respected, not worked around.

---

## 7. Performance, image quality, and price data

A full tender pack is not small. Analysing on the order of **60 PDF drawings can take more than half an hour**. Drivers:

1. **Data volume** — every page rendered, vectors extracted, text parsed. Dense GA/mesh pages can contain thousands of paths (one Cocktails page held 9,771), most irrelevant to costing but still processed to determine that.
2. **AI cross-check** — a whole-document pass in addition to deterministic extraction, so disagreements are flagged (a deliberate accuracy/time trade).
3. **Catalogue lookups against a messy dataset** — duplicate codes, free-text descriptions, inconsistent formatting. (An earlier pattern scanned tens of thousands of rows per part until corrected.)

**None of that reconstruction work is necessary against CAD** — geometry is read directly; the AI guard against ambiguous text becomes far less critical.

### Image quality
Vision analysis does not rely on native display resolution. Pages are re-rendered at substantially higher pixel density — **~300 DPI, up from an initial 144 DPI** — with a size cap, improving legibility of small callouts, dimensions and table text for OCR and AI reading.

> **Being precise.** Upscaling improves how well we read what is on the page. It cannot add information that was never drawn. A sharper image of a folded view still does not contain a flat pattern.

### Supplier price API
Bought-ins are priced from catalogue and quote history first. The historical set is large and inconsistent; gaps fall to flagged web/AI indicative prices or zero. **A direct supplier price API** would cut matching error, remove indicative AI pricing on bought-ins, and speed runs. CAD does not solve bought-in pricing; a price feed does.

**Packaging and delivery** are order-level commercial costs — never from CAD or the drawing. They need a small rules module (envelope, units per box/pallet, haulage rates), separate from drawing analysis.

---

## 8. What we need — and how to produce it

To move from *provisional* to *quotable*, per product:

| File | Unlocks |
|---|---|
| **Part DXF** (flat pattern, one per fab sheet part) | Blank size, nesting, profile cut, holes, bends — **highest single value** |
| **IGES / STEP** | Tube/section geometry, volumes/weights, weld lengths |
| **SolidWorks part** (`.SLDPRT`) | Material, thickness, sheet-metal parameters, features |
| **SolidWorks assembly** (`.SLDASM`) | Real part tree, quantities, joints — removes BOM-table guesswork |
| **Drawings** (`.SLDDRW` / `.DWG`) | Structured dimensioned detail, not a flattened page |

- **DXF flat patterns** — sheet-metal flat-pattern feature → Export to DXF, or Save As DXF/DWG (flat-pattern option). Batchable via Task Scheduler or a macro.
- **STEP / IGES** — File → Save As at part or assembly level.
- **Native files** — **Pack and Go** gathers assembly, parts and drawings with references intact. *Easiest single request to a design source: one Pack-and-Go per product.*

If drawings originate outside SDI (as with M&S), this is a data request to the customer or their consultancy — reasonable, because the parts cannot have been designed or manufactured without those files.

**Strategic end-state:** direct SolidWorks / PDM API — geometry, materials, sheet-metal parameters and the assembly tree from the model, with no export step. That removes the entire class of defects in §5 at source.

**Fallback where CAD cannot be obtained:** deeper historical quote / actual-cost matching — measured reality in place of missing geometry. Already partially in the pipeline; worth further development.

---

## 9. Guidance for estimators

1. **Treat PDF-only output as a provisional first pass** — structure, BOM completeness, catalogue hits, risk flags. Not a final sell price while fabricated parts have no DXF (the sheet says so).
2. **Read the flags** — they are the most valuable part. An assumption written in words is an instruction, not noise.
3. **Prefer the review report and workbook routes** over quote "What's included" bullets for process truth.
4. **Ask for part DXFs (and STEP/assembly where relevant)** — the same standard required to manufacture.
5. **Fill commercial gaps deliberately** — packaging, delivery, and specials not in the catalogue come back as zero on purpose.
6. **Prefer catalogue and historical matches for bought-ins** — indicative web/AI prices are marked; verify before they reach a quote.
7. **Do not pressure the system — or a person — to "complete" numbers the drawing cannot support.** That is how an inaccurate quote is born. A gap is a question, not a blank to invent.

---

## 10. Conclusion and recommendation

- The automation **works**, proven across timber, metal and mixed builds; Cocktails shows both the capability and the cost of PDF ambiguity (£5,270 → £670).
- The accuracy ceiling is set by the **input format**, not the software. Every significant defect traced to reconstructing, from an unstructured presentation document, information a CAD file contains.
- **A PDF cannot drive a CNC machine, and for the same reasons it cannot support a fully trustworthy estimate** — automated or manual. Manual estimating also pays in re-key time, transcription error and inconsistency.
- The system is built **not to guess**. Unpriced lines and the provisional banner are features. A flagged gap filled in seconds is worth more than a confident, invisible fabrication.
- **Highest-value action: obtain CAD** — DXF flat patterns, STEP/IGES, native part/assembly (Pack-and-Go), toward SolidWorks API integration.
- **Secondary:** supplier price API; a packaging/delivery rules module; stronger historical matching where CAD cannot be obtained.

**Bottom line.** A strong provisional estimate from PDFs is available *today*, and is useful for early commercial decisions. **The CAD inputs are what convert it into a defensible quoted price.**

---

*Prepared from the M&S Food Equipment tender automation exercise (ClaudeVision / SDI Intelligence). Reference jobs: 0348837 Horti Crate · 0357299 2 Wide Arch · 0357831 Madrid Bulk Stack · 0359131 Cocktails Hero Bay 4ft. July 2026 · PDF path provisional-by-design pending part CAD.*
