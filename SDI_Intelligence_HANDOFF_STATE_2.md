# SDI Intelligence — Engineering Handoff / Accumulated State

**Purpose of this document:** This is a detailed working-state note for the SDI Intelligence AI
estimating engine, written so that a fresh chat (or a new collaborator) can pick up with the full
context that has been accumulated across many sessions, WITHOUT re-deriving decisions or repeating
mistakes. It is deliberately long. Read it fully before changing code. When in doubt, trust the
RUN OUTPUT and read-only diagnostics over any snapshot (including this document, which ages the
moment it is written).

Last updated: session of 2026-06-30 (Session 12+), after building the general FIXING/VINYL
bought-in recogniser and the cross-layer reconciliation pass.

---

## 1. WHAT THE PROJECT IS

SDI Intelligence is a Python engine at `C:\ClaudeVision\src\` that reads PDF + DXF engineering
drawings and produces a priced estimate workbook. Flow:

  drawings (PDF + DXF) → extraction (text, BOM rows, geometry) → part records →
  material + labour + bought-in estimation → priced estimate workbook (xlsx)

The goal is production go-live: the engine should produce estimates close enough to the manual
estimators' sheets that reviewers trust it, and structurally familiar enough that they can test it.

### People
- **James Gray (JG)** — lead developer / AI & Systems Controller. Treats Claude as a peer
  engineering collaborator. Actively challenges approaches that drift from first principles.
  Can run SQL directly against the database.
- **Tim Wilkes** — manual estimator; his rate card + manual sheets are the parity benchmark.
- **Tony Ford** — senior estimator; benchmark owner, non-technical. Owns verified tube rates.
- **James Ryan (JR) & Simon** — reviewers. Goal is to send them ~3 easy drawings to validate.
- A new starter is joining.

### The single most important principle (enforced repeatedly)
**NO MOCKING, EVER.** The engine must derive every output genuinely from drawing data / the
database, or honestly flag the gap. Hard-coded or approximated values that fake completeness are
WORSE than honest gaps — they corrupt parity signals and erode trust. A confidently-wrong number
(e.g. a £132 foam tape) is worse than an honestly-absent one. This has been enforced many times;
treat any temptation to "fill in a plausible value" as a signal to STOP and flag instead.

---

## 2. ENVIRONMENT FACTS (critical — these have caused wasted effort when forgotten)

- **Claude CANNOT edit JG's machine.** Claude produces complete drop-in files + read-only probe
  scripts to `/mnt/user-data/outputs/`. JG deploys them into `C:\ClaudeVision\src\` and runs.
- **The `/mnt/project/` snapshot is STALE.** It does NOT reflect what JG has deployed. Trust RUN
  OUTPUT over the snapshot. This caused wrong reasoning more than once — always verify the
  deployed code with `findstr` or a probe before assuming behaviour.
- **Run via the venv ONLY:** `C:\ClaudeVision\.venv\Scripts\python.exe`
- **Entry point is ALWAYS `main.py`.**
- **DXF reader SHIM:** `dxf_reader.py` imports from `dxf_reader.py.py` (double extension —
  DELIBERATE, do not "fix" or delete it).
- **Database:** SQL Server, **SDILive @ 10.0.0.200**, accessed via **pyodbc, ODBC Driver 18,
  autocommit**, user AIBot, via `config.get_connection(timeout=N)`. `sqlcmd` is NOT installed.
- **SQL comments must be plain `--`.** Decorative `====` separators trigger Msg 102 syntax errors
  in pyodbc DDL.
- **K: drive** maps to `\\10.0.0.4\shareddata$\Shared\Estimating`.
- **LLM = xAI/Grok**, called via `web_ai_price_lookup._call_xai_llm`; degrades gracefully if down.
- Verbatim descriptions only (never reword a catalogue/historical description).

### RUN COMMAND (regression anchor job 1282)
```
C:\ClaudeVision\.venv\Scripts\python.exe main.py --search-root "K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay" --folder-as-job
```

### PARITY COMMAND (vs Tim's manual .xls — needs --read-via-excel COM flag; openpyxl can't read .xls)
```
C:\ClaudeVision\.venv\Scripts\python.exe estimate_full_parity_report.py --summary-json "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json" --workbook "K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls" --read-via-excel
```

### THE AUTHORITATIVE PRICING TEMPLATE (the SPEC)
`Blank_Estimate_Sheet__WB_2026.xlsx` (also at `C:\ClaudeVision\input\spreadsheets\`). JG declared
this the canonical SDI method — the engine MUST implement THIS template's formulas exactly, not
approximate them. Estimate sheet ~527 formulas, Labour ~264, Material Price Break ~26.

---

## 3. THE REGRESSION ANCHOR: JOB 1282

**1282 — Milwaukee 500mm Standard Wall Bay.** Folder-as-job: 7 PDFs + 14 DXFs, order qty 180 bays.
It is the HARDEST job in the corpus and is used as a stress test, NOT a first-correctness proof,
because it exercises many edge cases at once:
- Tubes via TWO detection paths (canonical "30x60x1.5 TUBE" and WALL-notation)
- A plastic/HIPS lens (1455-C-005)
- A weldment (1455-C-101)
- Loose electrical consumables described in assembly-note PROSE (page 10)
- Vinyl referenced by description (page 9)
- Packaging / delivery (commercial, order-specific)
- Per-bay vs per-order quantity complexity

Because so many edge cases overlap, 1282 is poor for proving the core path in isolation. The plan
is to ALSO use easy single-combination drawings (to prove each layer cleanly) and 12479 (Replen
Trolley) as a training/coding case (NOT a full run for now). Together they triangulate.

### Tim's GENUINE 1282 bought-in list (the target to converge on)
```
ELECTRICS - 50cm LOOM            £23.00  x1  -> £24.15   (bundled electrical assembly)
FIXING125  M8 x 25mm GUIDES      £0.22   x4  -> £0.92
FIXING2    CABLE TIES            £0.04   x3  -> £0.12    (real UDEF code is FIXING236)
FIXING5    4.0x10 POP RIVET      £0.01   x2  -> £0.02
FIXING1101 ADHESIVE CABLE CLIP   £0.12   x3  -> £0.37
FIXING49   M6 THREADED INSERT    £0.04   x4  -> £0.15
FIXING51   M8 LARGE THREADED INS £0.05   x4  -> £0.21
SLOTTEDTUBE01                    £3.65   x2  -> £7.59    (PREFERRED Tubes)
SLOTTEDTUBE02                    £3.65   x2  -> £7.59
SUBPLAS72  HEADER LENS (OPAL)    £1.02   x1  -> £1.07    (EAGLE)
VINYL03    KICK PLATE            £0.85   x1  -> £0.88
VINYL76    BASE PLATE            £0.85   x1  -> £0.88
POWDER5                          £4.00  x0.8 -> £3.33
BOX82 packaging                  £10.48  x1  -> £10.48   (Harleys)
Euro Pallet & misc               £2.50   x1  -> £2.50    (A.Dale)
Delivery Swadlincote             £280/artic x0.01 -> £2.86 (Hardings)
```
Tim total bought-in ≈ £63.62.

**Note on loom bundling:** Tim BUNDLES the electrical assembly into one "ELECTRICS 50cm LOOM" line
(£24.15). The engine SPLITS it into itemised parts (loom + junction box + LED light + downlights +
mains cable + earth strap + foam tape). JG has said **splitting/bundling is FINE — do not worry
about reconciling that difference.** They are not directly comparable and that's acceptable.

---

## 4. ARCHITECTURE — THE MULTI-LAYERED SOLUTION SET

JG's framing (important): the solution is a **multi-layered set, trained across a FINITE set of
drawing-pattern combinations.** "There are only so many combinations." Each layer handles a
different slice; the next layer backstops what the previous missed; the BOTTOM layer is always
"honest flag, don't guess" — that property is what makes the finite-combination approach robust
against combinations not yet seen.

### The layers (identification → pricing → flagging)
1. **DXF geometry** — flat-pattern parts: cut length, holes, bends from DXF (reliability 1.0 when
   a flat DXF is matched).
2. **Section detection** (tubes/RHS/SHS) — `document_builder._detect_section_stock`, two paths:
   - **canonical_profile**: "30 x 60 x 1.50mm TUBE 1125" (keyword + AxBxC). e.g. 3886-01.
   - **wall_notation**: detail drawings like 1448-01 page 4 ("60.0 EXT / 30.0 EXT / 1.5 WALL /
     1072.0 EXT"). Rule: "n.n WALL" = unambiguous tube signal; section sides = unqualified EXT
     dims >2×wall and ≤300mm; EXCLUDES qualified dims (FROM TOP/FROM BOTTOM/PITCH); large EXT
     >300 = length. Carries `review_section_profile=True` (flagged less-certain).
   - Section detection ALSO runs on the folder-as-job path in `drawing_job_merge.py` (the
     `[section]` print). This was a real deployment-gap bug: the section-detection pair
     (`drawing_job_merge.py` + `document_builder.py`) was not deployed while estimator.py was,
     so tubes priced as flat sheet with no `[section]` line. Lesson: confirm ALL related files
     deploy, not just the obvious one.
3. **Catalogue / UDEF pricing** — genuine prices from `dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING`.
4. **Deterministic prose recogniser** — `bought_in_recogniser.py`: mines vocab from SDI history,
   matches head-word-anchored phrases in assembly-note prose, prices from historical_quote lines.
5. **LLM note-scan (backstop)** — `note_scan.py` via grok-4.3: finds items in unstructured prose
   the deterministic layer can't (interleaved descriptions).
6. **Honest flagging** — anything not grounded becomes "estimator to price", never a guess.

### Identification vs Pricing are DISTINCT roles
The LLM is excellent at *finding* items in prose (a genuine capability). It must NOT be relied on
to *price* known SDI part codes — for those, look up the real price (UDEF/history) or flag.
LLM-estimated prices are round-number guesses (junction box £12, LED £7.50) and must be LABELLED
as xAI/LLM estimates so estimators know to verify (see Pending #3 below).

---

## 5. KEY FILES

- `main.py` — entry point.
- `estimator.py` — the core: material/labour/bought-in estimation, section pricing, recognisers,
  reconciliation. (Most of this session's work is here.)
- `drawing_job_merge.py` — folder-as-job merge; runs section detection on the merged parts list
  BEFORE estimate_document. Imports `_detect_section_stock`, `_get_page_text`, `_page_lookup_key`
  from document_builder.
- `document_builder.py` — `_detect_section_stock` (two-path tube detection), page helpers.
- `bought_in_recogniser.py` — deterministic prose recogniser (layer 4).
- `note_scan.py` — LLM note-scan backstop (layer 5). (NOT in Claude's working copy this session —
  only on JG's machine; needs paste/upload to edit.)
- `web_ai_price_lookup.py` — xAI/Grok caller. Uploaded version reads `xai_model` from config with
  a grok-4.3 fallback (line ~265). If deployed src still 400s on grok-2 after config fix, the
  deployed copy is older than the upload — refresh it.
- `xlsx_output.py` — writes the estimate workbook + Decision Report + AI Provenance sheets.
- `config.py` — rate card (reverse-engineered from Tim's sheet), policies, model name, DB conn.
- `pricing_service.py` — pricing waterfall / PricingService.
- Template: `Blank_Estimate_Sheet__WB_2026.xlsx`.
- Catalogue tables: `dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING`, `dbo.historical_quote_*`,
  `estimating_tube_rate` (dbo).

---

## 6. WHAT WAS BUILT / FIXED THIS SESSION (all staged in /mnt/user-data/outputs/, JG deploys)

### config.py
- **xai_model: "grok-2-latest" → "grok-4.3"** (line ~779). grok-2 was 400ing ALL session, so the
  LLM note-scan backstop was silently dead. With grok-4.3 it came alive and found 6 electrical
  items on 1282 (junction box, mains cable, earth strap, LED link light, GU10 downlight, loom).
  Current xAI flagship is grok-4.3 (verified via web search; older slugs redirect to it, but
  grok-2 is too old even for redirect).

### estimator.py (the big one — many changes; verified present via grep at end of session)
- **`_lookup_catalogue_tube_price`** (line ~540): matches a detected tube profile+length against
  UDEF priced rows by cross-section dims (order-independent) + wall±0.3 + length proximity,
  prefers "Preferred Tubes Ltd". Wired into the section path in `estimate_material` (~line 1399)
  BEFORE the mass-calc fallback. Verified: 3886-01 (L=1125) → SLOTTEDTUBE01 £3.57; 1448-01
  (L=1072) → SLOTTEDTUBE02 £3.57. NOTE: tube UNIT shows £4.54 = £3.57 catalogue material + in-house
  bend/finish/handling labour. This is CORRECT (SDI buys the tube as a length and bends/coats it).
- **Commercial placeholder skip** (top of `estimate_part`, ~line 2145): PACKAGING and DELIVERY
  stubs short-circuit estimation and stay £0 (`cost_method="commercial_placeholder_unpriced"`).
  Was a bug where they got re-priced to £16.97/£13.04.
- **Recogniser-price preservation guard** (top of `estimate_part`, ~line 2159): a bought-in stub
  carrying a price from the deterministic recogniser / LLM note-scan / UDEF-code recogniser KEEPS
  that price (returns immediately) instead of being re-costed via material+labour. This fixed the
  £132 foam tape (recogniser correctly set £0.28, but estimate_part was recomputing it as if it had
  geometry). Sources respected: `prose_recogniser_layer2`, `llm_note_scan`, `sdi_bom_code_udef_priced`.
  `sdi_bom_code_unpriced` passes through unpriced (None/flagged), NOT re-costed.
- **Tube ops display-strip** (in `estimate_process_times`, ~line 1748): for a bought-as-length
  tube (`_section_no_dxf`), strips `laser_cutting`/`saw` from the DISPLAYED `textual_operations`
  too (previously only the local `ops` used for labour was stripped, leaving the workbook showing
  a misleading "laser_cutting" on a tube that's never lasered). Cosmetic — does not change cost.
- **General SDI-coded bought-in recogniser** (`_recognise_sdi_coded_bought_in` ~line 2853,
  `_lookup_udef_exact_code` ~line 2687, regex `_SDI_BOUGHT_IN_CODE_RE` ~line 2733): finds ANY
  `FIXING\d+ / VINYL\d+ / PRINT\d+ / SUBPLAS\d+ / POWDER\d+` code in the BOM text and prices it
  from UDEF by **EXACT code** (`[Part code] = ?`, NEVER `LIKE` — a loose LIKE '%FIXING2%' matches
  FIXING236, FIXING2538, FIXING2658 (a £15 hinge), which would attach a wildly wrong price).
  Replaces reliance on the brittle hard-coded `patterns` list. Generalises to all drawings, no
  enumeration. If a code isn't priced in UDEF → flagged "estimator to price" (source
  `sdi_bom_code_unpriced`), never guessed. Verified in DB: FIXING125=£0.22 (M8 Swivel Glide),
  FIXING236=£0.02 (cable tie), FIXING1101=£0.12 (Adhesive Cable Clip), FIXING51x=rivet,
  VINYL76=£0.85 (Milwaukee Base Shelf 425x190), VINYL03=£0.85.
- **Vinyl-by-description matcher** (`_recognise_vinyl_callouts` ~line 2793,
  `_lookup_udef_vinyl_by_dimensions` ~line 2746, regex `_VINYL_CALLOUT_RE` ~line 2740): the
  page-9 vinyl is referenced by DESCRIPTION not code ("MILWAUKEE LOGO WHITE 425 W X 190 H"). The
  matcher extracts W×H and looks up UDEF vinyls by dimension. Prices ONLY when dimensions resolve
  to exactly ONE priced SKU (425x190 → unique VINYL76 £0.85, verified). 0 or many matches → flagged
  "estimator to price", never guessed. Verified: regex extracts 425/190 from real page-9 text.
- **Cross-layer reconciliation pass** (`_reconcile_bought_in` ~line 3105, `_bought_in_token_set`
  ~line 3055, `_bought_in_same_item` ~line 3074, `_BOUGHT_IN_SOURCE_RANK` ~line 3038; called at
  ~line 3384 before `estimable_parts` is built). Collapses the HARD duplicate case: the SAME
  physical item found by two DIFFERENT layers under different identifiers (BOM-table loom vs
  note-scan loom; FIXING5 vs BI-DOMERIVET). Matches on distinctive-token OVERLAP (containment),
  not exact key equality. Keeps the MOST-GROUNDED source (exact UDEF code 5 > BOM row 4 >
  deterministic 3 > unpriced-flag 2 > LLM 1 > placeholder 0), drops the duplicate, FLAGS the merge
  for audit (never silent). Guards verified: does NOT merge 50cm loom vs 100cm loom (number
  conflict), M8 glide vs M6 insert, or two different LED items. Fabricated parts and commercial
  placeholders are never dedup-dropped.

### xlsx_output.py (earlier this session)
- **Backed out Tim's JSON** (`job_bought_in_materials.json`): `_load_bought_in_for` is dead code,
  no longer called. Bought-in section is now sourced from the engine's part_estimates (drawing /
  catalogue derived), not from Tim's manually-produced sheets. JG: "back out tim's json read
  s/sheet. that's nasty." Honest trade-off accepted: output is genuine-but-incomplete vs Tim's
  complete-but-fake. Also fixed a dangling `_bi_total` reference that crashed xlsx generation.

### bought_in_recogniser.py (earlier this session)
- `best_priced_match` scoring changed from `shared/smaller` (let a 2-token phrase score 1.0 vs any
  longer line) to **Jaccard (shared/union)** + a plausibility guard rejecting implausibly-high
  prices on loose consumables. This is what found the CORRECT "Foam Tape 890x10x1.5mm" @ £0.28.

---

## 7. CURRENT 1282 STATE (as of last confirmed run, before the FIXING/VINYL/reconcile deploy)

- Document total ≈ £163.66 (was £128.31 before the LLM came alive and added 6 electrical items).
- Tubes: catalogue-priced £3.57/Preferred Tubes (unit £4.54 with in-house ops). CORRECT.
- Consumables (deterministic): Foam Tape £0.28, Dome Rivet £0.01, Adhesive Cable £1.16.
- Electricals (LLM note-scan): Junction box £12, mains cable £3.75, earth strap £0.85, LED link
  light £7.50, GU10 downlight £4.50 x2, 50cm lighting loom £2.25 — ALL round-number LLM guesses,
  flagged "AI-identified... verify", but NOT YET labelled clearly as xAI-sourced in the provenance
  sheet (Pending #3).
- Packaging £0 / Delivery £0, flagged. xlsx generates with Decision Report + AI Provenance sheets.

### AI Provenance sheet — how to read the rate/source column
- **"SDI Displays Ltd <date>"** = price came from the DATABASE (UDEF/historical). Most trustworthy.
- **"config rate card"** = from config.py rates, reverse-engineered from Tim's sheet. Grounded in
  SDI method.
- **blank / "—"** = NO grounded source = currently the LLM-estimated prices. Honest (no source) but
  not yet clearly labelled as "xAI LLM estimate" — that's Pending #3.

---

## 8. PENDING / NEXT STEPS (priority order)

### IMMEDIATE (in flight at handoff)
1. Confirm the run with the FIXING/VINYL recognisers + reconciliation pass:
   - Look for `[DEBUG] SDI-coded bought-in recognised: ... ['FIXING125','FIXING236',...]`
   - Look for `[DEBUG] Vinyl/logo callouts recognised: ... ['VINYL76']`
   - Look for `[reconcile] N duplicate bought-in line(s) merged` (tells us real cross-layer dupes)
   - Confirm the loom appears ONCE, fixings (GLIDE/NUTSERT/cable tie) and base-plate VINYL76
     appear with genuine UDEF prices.

2. **#3 — xAI/LLM price label.** Make note-scan-priced items carry `cost_source: "xai_llm_estimate"`
   (and a clear flag "Price is an xAI LLM estimate — verify") so the AI Provenance sheet shows the
   LLM as the price source instead of a blank. NEEDS `note_scan.py` (only on JG's machine). The
   relevant lines are around: stub price set at ~line 379-382 (`_price["source"]` flows into
   `cost_source`), flag built ~line 387. Get it via:
   `findstr /N "_price source cost_source def " note_scan.py`  or upload the file.

### THEN (JG's sequence)
3. **DXF quality examination** — NOT done yet. DXF MATCHING works (11/14 matched on 1282), but the
   extraction QUALITY/numbers are unexamined. Suspect numbers to verify:
   - 1449-01C reports **386 holes** (pegboard — plausible but check for path-doubling).
   - Tube cut-lengths 1448-01 = 10873mm / 3886-01 = 9379mm (GA-page rollup noise; harmless for
     catalogue-priced material but check it doesn't drive labour).
   - Several `reliability:1.0 dxf_flat_pattern` parts need cut-length / hole-count verification vs
     the drawings.
   PLAN: inspect 12479 DXFs directly here (uploaded) as a ground-truth training case + build a
   read-only 1282 DXF-quality probe. Tune against both combination sets at once. JG's intuition:
   tightening DXFs may also bring routes/assemblies closer.

4. Run main + parity with tubes/consumables/fixings/vinyl genuine; see where material & labour land.

5. **Find easy drawings; send 3 to JR.** A simple flat-steel job proves the core path cleanly,
   away from 1282's edge cases.

6. **AI-vs-manual STRUCTURAL comparison** (for adoption). JG wants the AI sheet to LOOK structurally
   familiar to the manual so reviewers trust it. Claude OFFERED to open both and produce an honest
   structural diff (section order, headers, layout divergence, what xlsx_output.py needs to change).
   NEEDS the AI-generated workbook uploaded (Claude has the template + Tim's manual data, not the
   generated output). Familiarity of layout is part of the product, not cosmetic.

### OTHER GENUINE GAPS STILL OPEN
- **Kick-plate vinyl (VINYL03)** — NOT captured and honestly NOT determinable from 1282's drawings:
  page 9 only states dimensions for the base-plate logo (425x190), not the kick plate; and the UDEF
  VINYL03 ("NOTHING BUT HEAVY DUTY 900x61") doesn't correspond to a Milwaukee kick plate. "Kick
  plate vinyl" matches 11 SKUs in UDEF. Leaving it flagged-absent is CORRECT — pricing it would be
  guessing. Needs a dimension on the drawing or a human to pick the SKU.
- **SerpAPI / web lookup TIMED OUT** — it's the BOTTOM of the pricing waterfall (fallback for
  genuinely-unknown parts only). It did NOT break the run (prices came from catalogue/history). JG
  asked whether to fix/replace. Advice: DON'T prioritise — not on critical path; for adoption you
  WANT unknowns flagged "estimator to price", not web-scraped. If replaced later, the cleaner
  answer is LLM-with-web-search via grok-4.3, not a separate SerpAPI dependency.
- Reconciliation is a HEURISTIC on description tokens. It catches the known dupes (loom, rivet) and
  holds the tested false-positive guards, but a future drawing could have two genuinely-different
  items with very similar descriptions. Safety net = every merge is FLAGGED, not silent. Tune token
  rules only if a wrong merge actually surfaces.
- Hard-coded `patterns` list in `extract_bought_in_from_pages` still exists (for non-coded items
  like SHFP28, MAGNET23). The general code-recogniser runs AFTER it and dedups against it. Fine.
- `main.py:~487` still references `job_bought_in_materials.json` (cosmetic, confirm not in the
  active path).
- `estimating_tube_rate` (dbo, 3 rows, Preferred Tubes, status pending_supplier_invoice) is the
  correct long-term home for Tony's verified tube rates — currently UNPRICED (unit_price_gbp=None),
  so UDEF is the genuine source for now. Needs Tony's prices later.
- BoughtInCatalogue duplicate-price hygiene (same SKU at two prices; a view filters out
  rag_fallback so the less-reliable web_indicative price can win). Lower priority.
- Three "Rose Hero Bay" M&S ingestion rejects (column truncation) logged for later.
- Vector DB / RAG corpus (pgvector or ChromaDB/Qdrant) — BACKLOG. Prerequisite: Tim's time rules
  integrated + 10+ parity runs done.

---

## 9. DISCIPLINE / WORKING PRINCIPLES (reinforced repeatedly — follow these)

- **NO MOCKING.** Derive genuinely or flag. Confidently-wrong > honestly-absent is FALSE — the
  reverse is true. (£132 foam tape, £15 hinge from loose LIKE — both are the trap.)
- **EXACT-code matching for catalogue lookups**, never loose LIKE, or you attach the wrong price.
- **VERIFY against real extracted data before building.** Test regexes/logic against the ACTUAL
  page text and DB, not idealised strings. Two failed tests on real data is the signal to find the
  right rule, not to tune until it passes.
- **Lean on read-only DIAGNOSTIC PROBES to find runtime reality BEFORE staging fixes.** Claude
  reasoned WRONGLY more than once about pipeline internals (assumed deployment gap, then logic bug;
  real causes were stale snapshot + downstream override + parts having empty `pages` at the
  section-loop stage). The probes showed truth; assumptions didn't. When a fix "should fire" but
  doesn't, BUILD A PROBE rather than reason in circles.
- **Trust RUN OUTPUT over the stale /mnt/project/ snapshot (and over this document).**
- **ONE change at a time, parity-check, hold the 1282 regression at every step.**
- **Deterministic-primary, LLM-backstop.** The deterministic layer is the primary; the LLM only
  backstops what it misses (and only PRICES via flag/verify, never grounds a price).
- **Distinguish IDENTIFICATION from PRICING** — finding an item and pricing it are different jobs.
- **Bottom layer always "honest flag, don't guess"** — this is what makes the finite-combination
  approach robust against unseen combinations.
- **Confirm ALL related files deploy**, not just the obvious one (the section-detection pair gap).
- **Solutions must EXTEND across all drawings**, not special-case 1282 (general recognisers, not
  enumerated lists).

---

## 10. READ-ONLY DIAGNOSTIC PROBES BUILT (in /mnt/user-data/outputs/ — pattern to reuse)

- `_section_diag.py` — replays section detection against the live JSON.
- `_part_fields_diag.py` — dumps all fields/keys on specific parts.
- `_section_value_diag.py` — inspects section_stock + costing values on the costed record.
- `_notescan_price_diag.py` — note-scan price provenance + loom double-count check.
- `_fixing_lookup_diag.py` — discovers DB columns, then checks FIXING/VINYL codes in UDEF /
  historical_quote_material. (KEY LEARNING: historical_quote_material columns are
  material_code / supplier_name / unit_price_gbp / material_cost_gbp / effective_date /
  source_sheet — NOT part_code/description. UDEF is the genuine bought-in source.)
- `_vinyl_match_diag.py` — confirmed 425x190 is UNIQUE in UDEF (→ VINYL76), kick-plate vinyl is
  ambiguous (11 SKUs).

Probe pattern: import config; `cn = config.get_connection(timeout=N)`; discover schema via
INFORMATION_SCHEMA.COLUMNS before guessing column names; print results; close. Read-only always.

---

## 11. DB FACTS WORTH KEEPING

- **UDEF** (`dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING`): columns `[Part code]`, `[Description]`,
  `[System cost per]`, `[Supplier name]`, `[UOM]`. The genuine bought-in price source. Match by
  EXACT `[Part code]`.
- **historical_quote_material** (dbo): columns material_code, supplier_code, supplier_name, unit,
  unit_price_gbp, quantity_per_unit, scrap_pct, material_cost_gbp, effective_date, source_sheet,
  source_cell_ref, raw_material_json, created_at. (Engine reads dbo.historical_quote_*; the
  AIEstimating.historical_quote_* tables are EMPTY — ingestion must land in dbo.)
- SLOTTEDTUBE01 = "ERW RECT. 60 x 30 x 1.5mm @ 1125mm SLOTTED TUBE Drawing 3886 Lower Leg" £3.57.
  SLOTTEDTUBE02 = same @ 1072mm Drawing 1448 Upper Leg £3.57. Length is the discriminator.
- Preferred Tubes Ltd — verified real supplier (Birdhall Industrial Park, Stockport SK3 0SZ).

---

## 12. HOW TO RESUME IN A NEW CHAT

1. Read this whole document first.
2. Do NOT trust the /mnt/project/ snapshot — verify deployed code with `findstr` / a probe.
3. The deployed `src` + the latest RUN OUTPUT are the source of truth.
4. Before changing anything, confirm what's actually deployed (line-number / grep check) so edits
   match the real file, not this doc's possibly-aged description.
5. Keep the discipline in §9. When a fix "should work" but doesn't, build a read-only probe.
6. Produce drop-in files to outputs/ for JG to deploy; never assume Claude can edit the machine.
