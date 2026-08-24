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

## How a job actually runs

Every source writes into **one shared list of part records** (`manufacturing_writeup.parts`).
Nothing costs anything until that list is complete. The order below is the order in
`file_scan._finalize_scan_summary`, and it *is* the waterfall — each stage can only fill
what the stages above it left empty.

| # | Stage | Module | What it contributes |
|---|-------|--------|---------------------|
| 1 | Render + read every PDF page | `pdfplumber`, `PyMuPDF` | page text, vector geometry |
| 2 | Classify pages, pool the BOM | `file_scan`, `document_builder` | one part record per BOM line |
| 3 | Deterministic title-block read | `extractor_patterns`, `drawing_facts` | material, finish, thickness, weights |
| 4 | Normalise | `json_normaliser` | material → costable family |
| 5 | **DXF augmentation** | `dxf_reader`, `drawing_job_merge` | measured flat blank, bends, cut length, holes |
| 6 | **SolidWorks native** | `source_connectors/solidworks` | cut-list flat, gauge, bends, BOM qty, finish, mass |
| 7 | Whole-document LLM extract | `llm_full_extract`, `source_connectors/llm_full_job` | fills gaps only; never overrides 5 or 6 |
| 8 | Knowledge base / corrections | `learning_engine` | prior corrections for known parts |
| 9 | Provisional geometry | `geometry_inference` | dimensions for parts with none — every value flagged |
| 10 | **Costing** | `estimator.estimate_document` | material + labour + routes |
| 11 | Credibility gate | `estimator` | withholds the headline if too little rests on measured data |
| 12 | Workbook, then read back | `wb_populate`, `wep_readback_from_xlsx` | Excel computes; its totals are stamped back as authoritative |

### Where SolidWorks fits, and where it does not

**The estimating pipeline never opens SolidWorks.** COM lives only in
`tools/solidworks/sw_native_analyse.py`, which is run by hand on a licensed Windows seat
and writes `_sw_native_extract.json`. Stage 6 above only ever *reads that JSON*, so the
estimate runs on any machine — and a **PDF-only job never touches the SolidWorks API at
all**. No extract file, no effect; the job runs on PDF + DXF exactly as before.

*(The `win32com` you will find inside `src/` is **Excel** COM — used to read the workbook's
own computed totals at stage 12. Unrelated to SolidWorks.)*

**What the analyser interrogates**

| Read | Used for |
|------|----------|
| `.SLDASM` | full-depth component BOM — part numbers, quantities, assembly structure |
| `.SLDPRT` | material, feature tree (bends, holes, weldment, imported bodies), bounding box, sheet-metal cut list |
| `.SLDDRW` | opened, but its BOM tables currently return **0 rows** — see below |

**What it does not**

- **Drawing BOM tables.** The table API varies by SolidWorks version and our read returns
  nothing. This matters: the PDF's BOM — which carries the `BI-` stock codes — is rendered
  *from* that table, so it is the one place those codes exist in CAD. Open.
- **STEP / IGES / Parasolid.** Geometry only, no BOM, no material. Never a source.
- **DXF.** Handled by the separate DXF path (stage 5), not through SolidWorks.
- **Bought-in identity.** Model titles are `USB`, `M4 Male Grip Knob`; the BOM says
  `BI-SCREENCABLE`, `BI-KNURLEDKNOB`. Five of six carry no custom properties at all, so
  **no honest string rule bridges them** — it needs a mapping table or the drawing BOM.

### How the sources are reconciled

Per datum, not per file — one part can take its blank from a DXF, its finish from the
model and its weight from the drawing.

| Datum | Wins | Loser's value |
|-------|------|---------------|
| Flat blank | DXF, else SolidWorks cut list | native flat compared; >10% area difference **flagged** |
| Thickness | cut list, else DXF filename, else title block | board values under `MIN_BOARD_THICKNESS_MM` rejected outright |
| Material | stated on the drawing | native override only across a family boundary (metal ↔ non-metal); same-family disagreement **flagged**, drawing kept |
| Quantity | native assembly BOM | LLM roll-up used only where native has no row |
| Bends | cut-list `Bends`, else feature tree | a formed part whose bends cannot be counted is **flagged**, never assumed zero |
| Finish | printed on the drawing | model `Surface Treatment` added alongside, both kept |

Nothing is silently overwritten. Every value a lower layer contributes carries a
`review_flags` entry naming its source, and every disagreement between layers is recorded
on the part rather than resolved out of sight.

### What ends up in the JSON

The canonical job JSON keeps each source **separately** as well as the merged result, so
any number can be traced back:

- `manufacturing_writeup.parts` — the merged part records the estimate was built from
- `dxf_augmentation` — what matched, what did not
- `solidworks_native` — extract path, BOM, counts, and what was applied
- `llm_full_extract` — the transcribed source data, auditable against the drawing
- `estimate_summary.data_sufficiency` — whether the headline is reportable
- `workbook_equivalent_pricing` — Excel's own totals, stamped back at stage 12

The workbook is the authority on the final figure. `wb_populate` writes formulas; Excel
computes them on load; `wep-readback` reads the real totals back into the JSON so the
spreadsheet, the quote and the report cannot drift apart.

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
| `SDI_APPLY_SOLIDWORKS=0` / `=1` | Force the native extract off / on. Default: **on**. Models present and unread is a **WARNING** — a seat is not always available and the engine falls back to the drawings by design. A job folder that cannot be OPENED is still BLOCKING: "I could not look" must never read as "there is nothing there" |
| `SDI_SW_EXTRACT_JSON` | Read the native extract from an explicit path (models on a CAD share, job folder elsewhere) |
| `SDI_SW_RUN_ANALYSER=0` | Never invoke SolidWorks COM; consume an existing extract only. Default: **the analyser runs** when models are present and no fresh extract exists. Set this on a shared designer workstation |
| `SDI_CANONICAL_ROUTE_WORKBOOK=0` | Fall back to the legacy per-part labour loop instead of the compiled route (default **on**) |
| `SDI_DUALPATH_BOM=0` | Read the BOM with the deterministic reader only, without the vision cross-check (default **on**) |
| `SDI_ORDER_QTY` | Order quantity for the run, when it is not given on the command line |
| `SDI_OUTPUT_ROOT` | Where reports and estimates are written (default `C:\ClaudeVision\output`) |
| `SDI_AISHEETS_DIR` | Where the estimator-override loop writes the regenerated client quote (default the AISheets share). Point at a local folder on a test box with no share mounted |
| `SDI_OVERRIDE_XLSX_DIR` | Where the estimator-override loop saves the amended workbook as the `_MANUAL_OVERRIDE` record (default: same as `SDI_AISHEETS_DIR`; set to the job's Live Enquiry folder to keep the override beside its pack) |
| `SDI_WELD_DEBUG=1` | Per-weld diagnostics from the document builder |
| `SDI_DWG_CONVERTER` | Full path to `ODAFileConverter.exe`. **This is the DWG backend that does not need SOLIDWORKS**, and it is tried first for exactly that reason — a licensed interactive seat can be closed, lapsed, or in another logon session, and all three end with DWG files present and unread. Leave unset to auto-detect (PATH, then `C:\Program Files\ODA\*`); set it when the converter lives elsewhere |
| `SDI_STAGING_ROOT` | *(portal backend)* Where the drawings for a run are gathered — one folder per client and job, **replaced on a re-run** so a second estimate cannot inherit a drawing taken off the list. Default is the **UNC** form `\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets\SDIIntelligenceAISheet` — a drive letter such as `K:` is a per-logon-session mapping and does not exist for a service, which is how this first failed (`WinError 3: cannot find the path 'K:\'`). Must also appear in `SDI_FILE_ROOTS`, and the service account needs **Modify** on it |
| `SDI_STAGING_MAX_FILES` / `SDI_STAGING_MAX_MB` | *(portal backend)* Guards against a folder picked a level too high (defaults **400** files / **750** MB). Past either, the run is refused before anything is copied |
| `SDI_DM_OUTPUT_ROOT` | *(portal backend)* Folder the Document Manager extract tool writes its packs to. The portal imports from here; it does not run the extraction. Must ALSO appear in `SDI_FILE_ROOTS` — there is no looser path rule for this feature |
| `SDI_DM_API_BASE` | *(portal backend)* Base URL of the DM API tool, for asking it to RUN an extract rather than importing one that has already run. **Unset** until its API contract is known; the portal reports 'not configured' rather than guessing |
| `SDI_DM_API_KEY` | *(portal backend)* Key for `SDI_DM_API_BASE`, if it needs one |
| `SDI_MAX_PARITY_UPLOAD_MB` | *(portal backend)* Cap on each side of an uploaded parity comparison (default **20**). Either side may instead be a path on the share, which is not capped |
| `SDI_BRAND_ASSETS_DIR` | *(portal backend)* Folder holding the brand logos the portal header serves — the **same folder** `src/client_quote_html.py` reads for the quotation header, so the two cannot show different marks (default `C:\ClaudeVision\assets\customer_logos`) |
| `SDI_BRAND_LOGO_KEY` | *(portal backend)* Filename stem of SDI's own logo within that folder, matched case- and space-insensitively (default `wearesdi`) |

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
| Timber / board / plastic never takes weld or dress-weld | Border *"WELD SPECIFICATION"* text booking Weld (CO2) **and** its chained Dress Welds against a wooden crate |
| `-J` is not a steel signal; `-M` yields to timber evidence | Joinery part numbers force-routed to mild steel, laser and powder ahead of any material read |
| Species map to their family (`FSC PINE` → `TIMBER`) | A stated material resolving to *nothing*, leaving part-number hints to win by default on a wooden part |
| Board thickness below a physical floor rejected | Tolerance-table text costed as stock — `0.5mm TIMBER`. Separate floors for sheet board (3 mm) and solid timber (6 mm) |
| Acrylic-department substitution on timber is named | A joinery part silently priced at the acrylic hand rate because the template has no joinery equivalent |
| Blank allowance never added to a measured flat pattern | A DXF or cut-list blank — already the developed size — inflated by a bend allowance it does not need |

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
