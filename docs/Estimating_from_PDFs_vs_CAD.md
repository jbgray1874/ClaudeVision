# Automated Estimating: Why Model the Process, Not the PDF

### A write-up from the M&S Food Equipment tender exercise (SDI Intelligence / ClaudeVision)

---

## 1. Purpose

This note explains, using the M&S tender work as the worked example:

- **what the estimating engine now does well,**
- **what went wrong and why,**
- **why not everything is priced,** and
- **why the single biggest lever on accuracy is the input data, not the algorithm** — i.e. why we should be estimating from part CAD (DXF / IGES / STEP) and the assembly model, not from PDF drawing packs.

The short version: **a PDF drawing pack is a *presentation* document, not a *manufacturing* dataset.** Estimating from it is like trying to machine a part from the general-assembly drawing. It can be done approximately, but the moment precision matters the PDF simply does not carry the information — and no amount of software cleverness can invent what was never in the file.

---

## 2. What went right

The pipeline is genuinely working. On the Cocktails Hero Bay (a mixed metal + plywood + tile product, 60+ parts) the engine, with no human intervention, correctly:

- **Extracted the full bill of materials** — 47 BOM lines including tube cut-lists, fixings, nutserts, LED strip — via both a deterministic reader and a whole-document LLM pass, cross-checked against each other.
- **Classified material families correctly** for the great majority of parts: mild-steel plate/brackets/mesh, plywood panels, mosaic tiles, acrylic diffusers.
- **Built manufacturing routes that follow the material** — laser / fold / weld / dress / powder-coat for steel; joinery for genuine board; handling-only for bought-in tiles and fixings.
- **Priced bought-in items from the live catalogue** (UDEF): fixings, inserts, LED strip, all matched by part code.
- **Recognised and excluded assembly parents** so their children are not double-counted.
- **Populated the estimators' own template** — same layout, same formulas — rather than a bespoke sheet.

Every number it produces is **traceable**: each line carries the source it came from (drawing fact, catalogue match, geometry, or flagged assumption).

---

## 3. What went wrong — and the honest root cause

Almost every error we chased on this job traced back to **one thing: the PDF.** Not the maths, not the pricing tables — the source document.

**Example A — material contamination from boilerplate.**
Every M&S drawing carries a standard specification legend that reads, in part:

> *"… SPCC UP TO 3mm THICK FOR CHROME … **TIMBER PRODUCTS:** • Q235 OVER 3mm THICK FOR POWDER COATED STEEL …"*

A PDF has no structure — it is just text and lines on a page. So when the engine scanned a **steel** part's page for its material, it found the word **TIMBER** (from the *"TIMBER PRODUCTS"* section header of that generic legend) and tagged a steel bracket as timber. That one mis-read then cascaded: the part got a joinery route (saw / glue / CNC) instead of a metal route. We fixed it — the engine now reads the labelled `MATERIAL:` field first and ignores the legend — **but the only reason the ambiguity existed at all is that a PDF does not label its own data.** A CAD file states the material as a *property*, unambiguously. There is nothing to misread.

**Example B — a polish specification that isn't a polish operation.**
The same legend contains *"POLISHING SPECIFICATION IS 400 GRIT FINAL POLISH."* The engine read *"POLISH"* and added a diamond-polish operation to every powder-coated steel part — over £130 of phantom labour on one bay. Again: fixable (and fixed), but the root cause is that a PDF cannot distinguish *"this part is polished"* from *"here is the general polishing note for the whole product family."* A process defined against a CAD model carries no such ambiguity.

**Example C — tubes described as a paragraph, not a feature.**
The cross-rail, front post and leg are steel tubes. On the PDF their size and length appear as free text in a cut-list table (*"30 x 60 x 2mm TUBE 2043.75"*). The engine read them as tubes for pricing — correctly — but the *geometry* it had for them was the whole general-assembly page's vector outline (thousands of stray lines), from which any "cut length" is meaningless. A STEP/IGES model **is** the tube — its length, section and wall thickness are geometric fact, not a sentence to parse.

**The pattern:** every failure was the software doing its best to reconstruct, from an unstructured presentation document, information that a CAD file would simply *contain*.

---

## 4. Why not everything is priced

Some lines come back unpriced or flagged. This is **deliberate and correct** — it is the "no cheating" principle. The engine will not invent a number it cannot defend. Lines are left unpriced when:

- **The quantity isn't on the drawing** (e.g. powder-coat kilograms, packaging, delivery) — these are order-level commercial figures the drawing genuinely does not contain.
- **The item isn't in the catalogue and has no geometry to cost from** (a special mosaic-tile panel, a bought-in graphic).
- **The part has no flat pattern** — without a DXF, a sheet-metal part has no blank size, so its material and cut/fold labour cannot be computed; the engine flags it rather than guessing an area.

An honest gap that an estimator fills in five seconds is worth far more than a confident wrong number that ships to the customer. **Guessing is the one thing we must never do** — a hallucinated blank size or an invented weld length looks exactly as authoritative as a real one on the sheet, and there is no visual cue that it was fabricated. A flagged blank says *"I need this"*; a guess says nothing and is worse than silence.

---

## 5. What a PDF cannot give us (and CAD can)

| Needed for a credible estimate | On the PDF | In the CAD (DXF / IGES / STEP + assembly) |
|---|---|---|
| Material of each part | A text note, often shared boilerplate — ambiguous | A stored property — exact |
| Flat-pattern blank size (L × W) | Not present unless drawn to scale and dimensioned | The DXF *is* the flat pattern — exact |
| Bend count, bend lines, bend allowance | Sometimes a note; often nothing | Geometric fact from the model |
| Cut length / internal cutouts | Derived from noisy page vectors — overshoots | Exact perimeter + hole geometry |
| Tube/section size & cut length | Free text in a cut-list | The solid's geometry — exact |
| Weld length / joint type | A weld symbol at best | Defined in the assembly mates/joints |
| True part count & hierarchy | Inferred from BOM tables that vary in format | The assembly tree — exact |
| Hole count & sizes | Callouts, easily missed or double-read | Every hole is a feature |

The right column is not "nicer to have" — it is the difference between a **quotable** number and a **provisional** one. On this tender the credibility gate correctly refused to report a headline price precisely because it had **0% DXF coverage on the fabricated parts**. The engine is not being pessimistic; it is being honest about what the input can support.

---

## 6. Why estimators should analyse 2D/3D directly

A PDF drawing pack is a **general-assembly / presentation document** — it exists to communicate intent to a human, not to drive manufacture. Machining does not run from a PDF; it runs from the CAD. Estimating is no different: it is a manufacturing calculation, and it should run from manufacturing data.

Feeding CAD to the estimating step would:

- **Remove the entire class of errors above at source** — no boilerplate to misread, no page-vector noise, no cut-lists to parse.
- **Speed the estimators up**, not slow them down — the engine would pre-fill the blanks, bends, weld lengths and part counts from geometry, leaving the estimator to sanity-check and price commercial lines, rather than key everything from a drawing.
- **Make every number reportable**, because the credibility gate would see real geometry, not inferred provisional dimensions.

---

## 7. Recommendation / the ask

To move from *provisional* to *quotable*, we need, per product:

1. **Part DXFs** (flat patterns) for every fabricated sheet-metal part — the single highest-value input; unlocks blank size, bends, cut length, nesting.
2. **STEP or IGES** for the 3D solids — unlocks tube/section geometry, weld lengths, true hierarchy.
3. **The assembly file** — unlocks the real part tree, quantities and joints, removing BOM-table guesswork.

With those, the pipeline already demonstrated on this tender produces traceable, per-line, catalogue-priced estimates automatically. **Without them, the PDF path is a strong first pass and a provisional figure — never a final quote — and that is a property of the input, not a limitation we can code our way around.**

If a strong provisional (PDF-only) estimate is useful to progress commercially, it is available now; the CAD inputs are what convert it into a defensible quoted price.

---

*Prepared from the M&S Food Equipment tender automation exercise. The Cocktails Hero Bay is used throughout as the worked example; the same behaviour and the same conclusions apply across the tender set.*
