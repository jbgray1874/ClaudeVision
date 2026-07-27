# ClaudeVision — SDI Intelligence Estimating Engine

Automated pipeline for extracting data from PDF + DXF technical drawings and
producing structured, priced estimates for SDI's sheet-metal / fabrication work
(display fixtures). The engine derives estimate **inputs** from the drawings and
populates the estimators' own workbook template, which then calculates the
priced estimate.

## What it does

- Extracts text and geometry from engineering drawings (PDFs + flat DXFs)
- Identifies parts, materials, thickness, dimensions, holes, folds, finishes and BOM lines
- Assigns manufacturing routes that **follow the material family** (metal / board / tube / bought-in)
- Prices material, labour and bought-in items from the catalogue / historical DB
- **Derives genuinely or flags honestly** — never fabricates a price (see *Principles*)
- Produces structured JSON and populates the estimators' Blank Estimate Workbook
- Emits deliverables: client quote HTML, job report HTML, LLM extract JSON (audit trail)
- Prepares data for pricing and RAG (historical lookup)

## Source waterfall

Data is taken from the most reliable source available, **per datum** — not per file — in
this order:

0. **SolidWorks native** *(reliability 1.0)* — the model itself: flat blank and sheet gauge
   from the sheet-metal cut list, bend count and radius, applied material, full-depth
   assembly BOM quantities. See `tools/solidworks/README.md`.
1. **DXF geometry** — exact blank size, bends, cut length, holes
2. **Deterministic PDF reads** — labelled title-block fields, BOM tables, drawing facts
3. **Whole-document LLM extract** — cross-checked against (2); drives geometry only for
   PDF-only parts with no DXF

Each layer fills only what the layer above left empty. Where two layers both have a value
and they disagree, the disagreement is **flagged on the part** — a native/DXF blank
mismatch over 10% by area, or a material the model and the title block do not agree on.

Where no measured geometry (DXF *or* native flat pattern) covers the fabricated parts, the
**credibility gate** computes a provisional total but marks it *not reportable* rather than
presenting it as a quote. A part the model names a material for but yields no blank, mass
or section is flagged as *cost not derivable* — never left as a £0 line that reads as free.

## Project layout

| Path | Purpose |
|------|---------|
| `src/` | **Active source** — the live `.py` pipeline (entry point `src/main.py`) |
| `corpus/` | Historical corpus (JSONL) for RAG |
| `config/` | Configuration and example env templates |
| `sql/` | SQL assets |
| `docs/` | Documentation (see *Further reading*) |
| `Notes/` | Working notes / architecture drafts |

> The canonical, actively-maintained Python lives in **`src/`**. Other trees are
> historical mirrors kept only for reference.

## Setup

```bash
python -m venv venv
# Windows:  venv\Scripts\activate
# Unix:     source venv/bin/activate
pip install -r requirements.txt
```

Copy the example env template and fill in real values (never commit the populated file):

```bash
cp config/live_enquiry_collector.example.env config/.env   # example
```

## Run

```bash
python src/main.py --search-root input/drawings --drawing-pattern "*.pdf"
```

Folder-as-job (all PDFs + DXFs in a folder treated as one job):

```bash
python src/main.py --search-root "path/to/1282 - Milwaukee Wall Bay" --folder-as-job
```

Single job with deliverables (the pattern used for the M&S tender):

```powershell
$env:SDI_APPLY_DRAWING_FACTS = "1"
$env:SDI_LLM_FULL_EXTRACT    = "1"
python src\main.py --pdf "<pack>.pdf" --generate-ai-spreadsheet --deliverables `
  --order-qty 1 --customer "M&S"
```

### Useful environment flags

| Flag | Effect |
|------|--------|
| `SDI_APPLY_DRAWING_FACTS=1` | Apply deterministic drawing-fact overlay |
| `SDI_LLM_FULL_EXTRACT=1` | Whole-document LLM extract (default-on when `XAI_API_KEY` present) |
| `SKIP_VISION_EXTRACTION=1` | Skip page-image vision pass (faster) |
| `SCAN_DEBUG=1` | Per-part timing and source diagnostics |
| `VISION_RENDER_DPI` | Page render DPI for vision/OCR (default **300**, was 144) |
| `VISION_MAX_SIDE` | Max rendered image edge in px (default 4000) |
| `SDI_ENABLE_PART_DESC_SCAN=1` | Re-enable the description `LIKE` catalogue scan (default **off** — see *Performance*) |
| `ESTIMATE_DEFAULT_JOB_QUANTITY` | Default order quantity when not supplied |

## Quick health check

Verify the whole `src/` tree still parses (no DB required):

```bash
python scripts/check_compile.py
```

## Principles

The single most important rule, enforced throughout the codebase:

> **NO MOCKING.** Every output must be derived genuinely from drawing data or the
> database, or honestly flagged as a gap. A confidently-wrong number is worse than
> an honestly-absent one — it corrupts parity signals and erodes trust.

- Exact-code catalogue lookups only — never a loose `LIKE`.
- Deterministic-primary, LLM-backstop. The LLM *identifies* items in prose; it does
  not *price* known SDI part codes.
- **Every fix must be general and inheritable.** Rules are keyed on family, stock form
  or drawing convention — never on a single part number or job.
- Hold the reference-job regression (1282 — Milwaukee Wall Bay) at every step.

## Costing safeguards

Rules that prevent classes of error, all general:

| Safeguard | What it prevents |
|---|---|
| Labelled `MATERIAL:` read first; spec-legend boilerplate rejected | Generic legend text (e.g. a *"TIMBER PRODUCTS"* header) tagging a steel part as timber |
| Cross-reference notes rejected as material | *"SEE INDIVIDUAL DRAWINGS"* becoming a material family |
| Diamond-polish requires a genuine polish cue | Boilerplate *"POLISHING SPECIFICATION"* inventing a DPOL op on powder-coated steel |
| Tube / section / wire never takes a joinery route | A steel tube being saw / rout / glue / spray costed |
| Top-level `-00-` line treated as an assembly parent | The whole product costed as a leaf part on top of its children |
| Special finishing items (`-X` suffix, tiles / mosaic / graphic / vinyl) routed bought-in | Fabrication labour on items we buy in |
| Throughput floor + ceiling per operation | Garbage derived rates (e.g. 0.17 parts/hr) printing thousands in phantom labour |
| Tube catalogue price gated on length | A 12 m and 13 m tube returning the same price |
| BOM overflow spills in-code | A large job silently dropping BOM lines, or falling back to the legacy sheet |

## Performance

- Part price lookups use a **sargable exact-code seek**. The legacy description
  `LIKE '%…%'` scan (full table scan of ~91k rows *per part*) is **off by default** —
  re-enable with `SDI_ENABLE_PART_DESC_SCAN=1` only for description cross-matching.
- All DB calls are bounded (connect + query timeouts); the web/AI price fallback is
  bounded by per-call timeout and a per-job budget, so a run can never hang.
- Vision pages render at **300 DPI** (from 144) for materially better small-text and
  callout legibility, capped by `VISION_MAX_SIDE`.
- A ~60-drawing tender pack still takes **30+ minutes** — dominated by page vector
  volume, the LLM cross-check pass and catalogue lookups. See the write-up in
  *Further reading* for why, and why CAD input removes most of it.

## Status

Proven end-to-end on four M&S tender products: **0348837** (Horti Rustic Crate, timber),
**0357299** (2 Module Wide Arch, metal/tube), **0357831** (Madrid Bulk Stack, mixed
metal + MDF), **0359131** (Cocktails Hero Bay 4ft, mixed metal + ply + tile + acrylic).

These are PDF-only packs, so totals are **provisional** — the credibility gate reports
0% DXF coverage on fabricated parts and withholds a reportable headline. Obtaining CAD is
the highest-value change available.

**SolidWorks API integration is live.** `tools/solidworks/sw_native_analyse.py` reads a
job's models read-only over the SolidWorks API and writes `_sw_native_extract.json`;
`src/source_connectors/solidworks.py` folds that into the part records *before* costing.
On a modelled job this replaces the whole class of PDF guesswork: measured flat blanks and
sheet gauges instead of inferred ones, quantities from the assembly BOM instead of a vision
read, imported supplier bodies identified as bought-in, and assemblies marked so their
material is not counted twice. Outstanding: mass properties (`mass_kg`) do not yet populate,
and revision selection where a pack carries two drawing revisions is still manual.

## Further reading

- **`docs/Estimating_from_PDFs_vs_CAD.md`** *(and `.html`)* — why PDFs cannot support a
  fully trustworthy estimate, worked examples of what they cannot provide, and the CAD ask
- `docs/solidworks_integration_design.md` — SolidWorks integration design
- `docs/solidworks_portal_architecture.md` — portal architecture
- `src/ClaudeVision_Understanding_Updated.md` — current architecture overview
- `SDI_Intelligence_HANDOFF_STATE_2.md` — accumulated engineering state
- `src/sdi_golive_roadmap.md` — go-live roadmap and open items
