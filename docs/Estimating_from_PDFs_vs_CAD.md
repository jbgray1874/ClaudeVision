# Automated Estimating: Why We Must Model the Process, Not the PDF

### Findings from the M&S Food Equipment tender automation exercise
**SDI Intelligence / ClaudeVision — prepared for the estimating team**

---

## 1. Executive summary

We have built and proven an automated estimating pipeline that reads drawing packs, extracts the bill of materials, assigns manufacturing routes, prices parts against our live catalogue and history, and populates the estimators' own workbook — with every figure traceable to its source.

It works. Four M&S products have been costed end-to-end with no manual intervention.

**But it is running on the wrong fuel.** We are feeding a manufacturing calculation with a *presentation document*. A PDF drawing pack cannot drive a CNC machine — that is not a controversial statement, it is simply how manufacturing works. The same limitation applies, for exactly the same reasons, to automated *and* manual estimating.

The single highest-value change available to us is not more software. It is **giving the estimating process the same data the shop floor already requires: DXF flat patterns, IGES/STEP solids, and the native SolidWorks part and assembly files.**

With those, the pipeline produces defensible, quotable numbers. Without them, it produces an honest provisional figure with a warning banner — which is the correct behaviour, and a limitation of the input, not something we can code our way around.

---

## 2. What we have proven works

Four products costed end-to-end, automatically:

| Product | Code | Type | Outcome |
|---|---|---|---|
| Horti Rustic Crate | 0348837 | Timber | Costed — timber route, material by weight |
| 2 Module Wide Arch | 0357299 | Metal / tube | Costed — tube catalogue pricing, metal route |
| Madrid Bulk Stack | 0357831 | Mixed metal + MDF | Costed — mixed families handled correctly |
| Cocktails Hero Bay 4ft | 0359131 | Mixed metal + ply + tile + acrylic | Costed — 60+ parts, provisional (no DXFs) |

On the most complex of these (Cocktails — a 4ft bay with over 60 parts spanning steel, plywood, mosaic tile and acrylic), the system with no human input:

- **Read the full bill of materials** — 46 lines including tube cut-lists, fixings, inserts, LED strip — using two independent methods (a deterministic table reader and a whole-document AI pass) which are cross-checked against each other.
- **Identified material families correctly** across steel, plywood, tiles and acrylic.
- **Built manufacturing routes that follow the material** — laser / fold / weld / dress / powder-coat on steel; saw / rout / glue / spray on genuine board; handling only on bought-in tiles and fixings.
- **Priced bought-in items from the live SDI catalogue** by exact part code — fixings, threaded inserts, LED strip, tube sections against supplier records.
- **Recognised and excluded assembly parents**, so sub-assembly costs are not double-counted on top of their children.
- **Populated the estimators' own template**, using its native formulas and layout — not a bespoke sheet.
- **Flagged every assumption** — over 40 explicit notes on that job, each naming what was assumed and what an estimator should confirm.

Every number carries its provenance: catalogue match, drawing fact, computed geometry, or flagged assumption. Nothing appears without a source.

**The refinement journey on Cocktails is itself instructive.** Its costed unit moved from £5,270 to £670 as we removed defects — every one of which traced back to the ambiguity of reading a PDF rather than a model (detailed in §4). That is the cost of the wrong input format, measured.

---

## 3. The core point: a PDF is not a manufacturing file

**You cannot machine from a PDF.** No CNC control, no nesting package, no press-brake controller will accept one. This is not a preference or a limitation of any particular software — a PDF describes *marks on a page*: lines, text, and their positions. It does not describe *a part*. There is no material property, no thickness attribute, no bend table, no feature tree, no assembly relationship. Those things are not hidden in the file; they were never in it.

Given that, the question answers itself:

> If a PDF does not contain enough information to *make* the part, it cannot contain enough information to accurately *cost making* the part.

Estimating is a manufacturing calculation. It needs the same class of data the manufacturing process needs.

### This is not only an AI problem

It is worth being blunt: **the PDF is a poor input for manual estimating too.**

- **It is slow.** An estimator must read, interpret and re-key values that already exist as data in the CAD model — dimensions, quantities, thicknesses, cut lengths. That is transcription, not estimating.
- **It is error-prone.** Every re-keyed number is an opportunity for a transposition, a misread, or a missed revision. A 60-page pack has hundreds of such opportunities.
- **It is inconsistent.** Two estimators reading the same ambiguous pack will produce different numbers, because the pack does not define the answer.
- **It hides changes.** A revised part in a re-issued pack looks identical to an unchanged one unless someone spots the revision cloud.

Automating a PDF-based process makes it faster, but it does not make the underlying data any better. **We are automating around a problem that should be removed at source.**

---

## 4. What a PDF genuinely cannot provide — with real examples

These are all real defects encountered and fixed during this exercise. Each one is a case of software trying to reconstruct, from an unstructured page, information that a CAD file simply *contains*.

### Example A — Material cannot be read reliably, because it is just text on a page

Every M&S drawing carries a standard specification legend for the whole product range:

> *"… SPCC UP TO 3mm THICK FOR CHROME, ZINC PLATE OR HIGH QUALITY PAINT FINISH … **TIMBER PRODUCTS:** • Q235 OVER 3mm THICK FOR POWDER COATED STEEL …"*

A PDF has no structure — it cannot distinguish a *part property* from *generic boilerplate*. So when the system scanned a **steel** part's page for its material, it found the word **TIMBER** (the section header of that generic legend) and tagged a steel bracket as timber. That single mis-read then cascaded: the part was given a joinery route — saw, CNC-rout, glue, spray — instead of a metal route.

We fixed it (the system now reads the labelled `MATERIAL:` field first, and rejects legend boilerplate). **But in a CAD file, material is a stored property of the body. There is no sentence to parse, and no ambiguity to resolve.**

### Example B — A note about polishing became a polishing operation

The same legend states *"POLISHING SPECIFICATION IS 400 GRIT FINAL POLISH."* The system read *"POLISH"* and added a diamond-polish operation to every powder-coated steel part in the job — over £130 of labour that does not exist.

A PDF cannot distinguish *"this part is polished"* from *"here is the general polishing note for the product family."* **A route defined against a model carries no such ambiguity.**

### Example C — Tubes described as a paragraph, not as geometry

The cross-rail, front post and leg are steel tubes. On the PDF, their sizes and lengths appear as free text in a cut-list table:

> *"LENGTH QTY 1 30 x 60 x 2mm TUBE 658 1 2 30 x 60 x 2mm TUBE 2043.75 …"*

We parse that successfully for pricing. But the *geometry* available for those parts is the whole general-assembly page's vector outline — thousands of unrelated lines — from which any computed "cut length" is meaningless. **In a STEP or IGES model, the tube simply *is* its geometry: section, wall thickness and length are exact facts, not a sentence to interpret.**

### Example D — The product line was costed as if it were a part

The pack's top-level line (the whole 4ft bay) carried a stated overall weight. With no structural hierarchy in the file, the system costed it as a fabricated part — a £389 material line — *in addition to* all of its children. A double-count of over half the material value.

**An assembly file states the hierarchy explicitly.** There is no inference required, and therefore no inference to get wrong.

### Example E — No flat pattern means no blank, no nest, no bend cost

This is the big one. For a sheet-metal part, the flat pattern determines material consumption (blank size), nesting efficiency (parts per sheet), cut length (laser time) and bend count (press-brake time). **A PDF drawing of a folded part does not contain its flat pattern.** It shows the folded views and some dimensions.

Consequently, for every fabricated part without a DXF, the system must either flag the values as missing or derive provisional ones — and it correctly refuses to present a headline price when it has done so.

### Summary table

| Needed for a credible estimate | Available on the PDF | Available in CAD (DXF / IGES / STEP / SLDPRT / SLDASM) |
|---|---|---|
| Material of each part | A text note, often shared boilerplate — ambiguous | A stored property — exact |
| Thickness / gauge | A callout, easily missed or mis-associated | A model attribute — exact |
| Flat-pattern blank size (L × W) | **Not present** | The DXF *is* the flat pattern — exact |
| Nesting / parts per sheet | Cannot be computed without the blank | Directly computable |
| Bend count, bend lines, bend allowance | Sometimes a note, often nothing | Geometric fact from the sheet-metal feature |
| Profile cut length & internal cut-outs | Derived from noisy page vectors — overshoots | Exact perimeter and hole geometry |
| Tube / section size and cut length | Free text in a cut-list table | The solid's geometry — exact |
| Weld length and joint type | A weld symbol at best | Defined in the assembly mates / weld beads |
| Hole count and sizes | Callouts, easily missed or double-counted | Every hole is a feature |
| True part count and hierarchy | Inferred from BOM tables of varying format | The assembly tree — exact |
| Revision state per part | A cloud and a letter, if noticed | Managed metadata |

The right-hand column is not "nicer to have." It is the difference between a **quotable** number and a **provisional** one.

---

## 5. Why we deliberately refuse to guess

Some lines come back unpriced or flagged. **This is intentional and it is the most important design decision in the system.**

The pipeline will not invent a number it cannot defend. Lines are left unpriced when:

- **The quantity is genuinely not on the drawing** — powder-coat kilograms, packaging, delivery. These are order-level commercial figures the drawing does not contain.
- **The item is not in the catalogue and has no geometry to cost from** — a special mosaic-tile panel, a bought-in graphic.
- **The part has no flat pattern** — without it, blank size and cut/fold time cannot be computed, so the system flags rather than assumes.

### The hallucination risk, stated plainly

An AI system asked to produce a number will produce a number. If the information is not present, it will produce a *plausible* one — and **a fabricated figure looks exactly as authoritative on the sheet as a measured one.** There is no visual cue. No asterisk. It reads like fact.

That is far more dangerous than a blank. A blank says *"I need this."* A guess says nothing, and gets quoted, won, and manufactured at a loss.

So the rule is absolute: **the system transcribes and computes; it does not speculate.** Where it must assume (e.g. a provisional dimension so a job can be reviewed at all), the assumption is written on the face of the estimate, in words, naming what was assumed and what to confirm. On the Cocktails job that produced over 40 explicit flags.

This is also why the **credibility gate** exists. When DXF coverage on fabricated parts is 0%, the system computes a provisional total but **refuses to present it as reportable**, stating the coverage figure. That is the system telling the truth about its own inputs — and it should be trusted and respected, not worked around.

---

## 6. Performance: why volume is a real constraint

A full tender pack is not a small job. Analysing a set of around **60 PDF drawings takes in excess of half an hour**, and the reasons are structural, not a tuning problem:

1. **Sheer data volume.** Every page must be rendered, its vectors extracted and its text parsed. One Cocktails page alone contained **9,771 vector paths** — the mesh detail — nearly all of it irrelevant to costing, but all of it requiring processing to determine that.
2. **The AI cross-check pass.** A whole-document AI read is run *in addition to* the deterministic extraction, so the two can be compared and disagreements flagged. That is a deliberate accuracy/time trade — it is what stops a single bad table read going through unchallenged.
3. **Database price lookups, against a difficult dataset.** Every part is looked up against the live catalogue. The price data is large and inconsistent — duplicated codes, varying descriptions, differing casing and formatting. (One lookup pattern was scanning ~91,000 rows *per part* until we corrected it; that alone accounted for several minutes per job.)

**None of that work would be necessary against CAD.** Geometry would be read directly instead of reconstructed from page vectors, and the AI cross-check would no longer be needed to guard against mis-reads of ambiguous text.

### Image quality and the upscaler

Because drawing detail matters, the vision analysis does **not** read the PDF at its native display resolution. Pages are re-rendered at a substantially higher pixel density — **300 DPI (up from an initial 144 DPI)**, with a scaling cap to keep image sizes manageable. This materially improves the legibility of small callouts, dimension text and table entries for both OCR and AI reading.

It is worth being clear about what this does and does not achieve: **upscaling improves how well we can read what is on the page. It cannot add information that was never drawn.** A sharper image of a folded-view drawing still does not contain a flat pattern.

---

## 7. Price data: the case for supplier API integration

Bought-in parts are priced from our own catalogue and quote history first — correctly, since those are our real, negotiated prices. But:

- The historical price dataset is **large, messy and inconsistent** — duplicate codes, free-text descriptions, differing formats, stale entries.
- Where an item is not in the catalogue, the remaining options are a web/AI indicative price (explicitly flagged, low-confidence, verify-before-quoting) or nothing.

**The right answer is a direct API integration to supplier price lists** — live, structured, authoritative pricing for bought-in components, rather than fuzzy-matching a legacy dataset or asking an AI for a market estimate. This would:

- remove a whole category of matching error,
- eliminate the need for indicative AI pricing on bought-ins altogether,
- and speed up the run, since a keyed API lookup is fast and deterministic.

**Packaging and delivery** deserve separate mention: these are **order-level commercial costs** and will never come from CAD or a drawing. They are a function of product envelope, units per box/pallet, pallet count and haulage rate. They need a small, rule-based module fed with our real packaging and carriage rates — a genuine gap to close, but a different problem from drawing analysis.

---

## 8. A specific and uncomfortable observation on the M&S packs

Stated plainly, because it matters commercially:

**The M&S PDF drawing packs do not contain enough information to produce a trustworthy automated estimate on their own.** They are general-assembly presentation documents. Key manufacturing data — flat patterns, reliable per-part material properties, bend and weld definitions, structured hierarchy — is absent or ambiguous.

What we can extract is genuinely useful: the bill of materials, part counts, bought-in items, tube cut lists, finishes, and a sensible provisional route and cost. But the credibility gate correctly reports **0% DXF coverage on fabricated parts** on these jobs, and the totals are therefore marked provisional.

Two things can lift that, and only two:

1. **CAD files** (the real fix — see below), or
2. **Historical analysis** — matching parts and products against our own past quotes and actual manufactured costs, which substitutes measured reality for missing geometry. This is a viable path where CAD genuinely cannot be obtained, and the pipeline already reads historical quote data; it deserves further development as the fallback strategy.

Continuing to invest in squeezing more out of variable-quality PDFs has a low ceiling. That ceiling is set by the file format, not by our software.

---

## 9. What we are asking for, and how to produce it

To move from *provisional* to *quotable*, we need, per product:

| File | What it unlocks |
|---|---|
| **Part DXF** (flat pattern, one per fabricated sheet-metal part) | Blank size, nesting, profile cut length, hole count, bend count — the single highest-value input |
| **IGES / STEP** (3D solids) | Tube and section geometry, true volumes and weights, weld lengths |
| **SolidWorks part files** (`.SLDPRT`) | Material properties, thickness, sheet-metal parameters, features |
| **SolidWorks assembly** (`.SLDASM`) | The real part tree, quantities, and joint definitions — removes all BOM-table guesswork |
| **Drawing files** (`.SLDDRW` / `.DWG`) | Dimensioned detail with structure, rather than a flattened page |

### How these are generated

All of the above are standard SolidWorks outputs and require no new tooling or licences:

- **DXF flat patterns** — for any sheet-metal part, *right-click the flat-pattern feature → Export to DXF*, or use SolidWorks' built-in "Save As DXF/DWG" with the flat-pattern option. This can be batched across a whole assembly using a task/macro so it is a single operation per product, not per part.
- **STEP / IGES** — *File → Save As → STEP (.step) or IGES (.igs)* at either part or assembly level.
- **Native part/assembly files** — copied directly, or supplied via a Pack-and-Go (*File → Pack and Go*), which gathers the assembly, all its parts and drawings into one folder or zip with references intact. **This is the single easiest request to make of a design source: one Pack-and-Go per product.**
- **Batch export** — SolidWorks Task Scheduler (or a short macro) can export DXF and STEP for every part in an assembly automatically, so the effort is minutes per product, not hours.

If the drawings originate outside SDI (as with the M&S packs), then **this becomes a data request to the customer or their design consultancy** — and it is a reasonable one, because they already hold these files: the parts cannot have been drawn, nor can they be manufactured, without them.

### The strategic step: direct SolidWorks integration

Beyond receiving files, the intended direction is a **direct SolidWorks API integration** — reading geometry, materials, sheet-metal parameters and the assembly tree straight from the model, with no export step and no file handling at all. That removes the entire class of defects described in §4 at source, and is the natural end-state for the pipeline.

---

## 10. Conclusion and recommendation

- The estimating automation **works**, and is proven on four products across timber, metal, and mixed-material builds.
- Its accuracy ceiling is currently set by the **input format**, not the software. Every significant defect we corrected traced back to reconstructing, from an unstructured presentation document, information a CAD file simply contains.
- **A PDF cannot drive a CNC machine, and for the same reasons it cannot support a fully trustworthy estimate** — automated or manual. For manual estimating it additionally imposes re-keying time, transcription error and inconsistency between estimators.
- The system is deliberately built **not to guess**. Unpriced lines and the provisional banner are features, not failures — a flagged gap an estimator fills in seconds is worth far more than a confident, invisible fabrication.
- **The highest-value action available is to obtain CAD** — DXF flat patterns, STEP/IGES, and native part/assembly files (easiest via Pack-and-Go), working toward direct SolidWorks API integration.
- **Secondary priorities:** supplier API price integration to replace fuzzy matching against a messy historical dataset; a rules-based packaging and delivery module; and continued development of historical-quote matching as the fallback where CAD genuinely cannot be obtained.

A strong provisional estimate from PDFs is available today, and is useful for early commercial decisions. **The CAD inputs are what convert it into a defensible quoted price.**

---

*Prepared from the M&S Food Equipment tender automation exercise (products 0348837, 0357299, 0357831, 0359131). The Cocktails Hero Bay 4ft (0359131) is used as the principal worked example; the same behaviour and the same conclusions apply across the tender set and to drawing packs generally.*
