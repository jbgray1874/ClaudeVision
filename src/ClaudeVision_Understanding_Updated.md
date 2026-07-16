# ClaudeVision — Understanding & Current State (updated)

I have a solid picture from the handoff, the repo layout, and the files read — but the summary below has been **updated to reflect the current architecture**, which changed materially in the most recent sessions. The earlier understanding described the *pre-pivot* design (engine computes an estimate, then parity compares it to the manual sheet). That is no longer how the system works. The corrected picture follows.

## What ClaudeVision does

An AI-assisted manufacturing estimating system for SDI sheet-metal / fabrication work (display fixtures — e.g. the Milwaukee wall bays). The flow:

- **Input** — GA PDFs and flat DXFs (engineering drawings) go in.
- **Scan & extract** — Vision + text parsing pulls part numbers, materials, thickness, geometry, holes, folds, finishes, and BOM lines. BOM lines come from the **drawing** (note-scan + UDEF catalogue), not from any manual sheet.
- **Estimate — inputs, not final costs.** `estimator.py` derives the *inputs*: part dimensions, materials, operation lists, bought-in items, and per-operation `batch_hours`. It no longer computes the final priced estimate itself (see the pivot).
- **Populate the estimators' sheet** — `wb_populate.py` writes those inputs into the estimators' **real Blank Estimating Workbook template**, and the workbook's own formulas produce the priced estimate (material + labour → unit cost → sell price).
- **Output** — the populated workbook in the estimators' own format, plus the structured run JSON that the populate reads from.
- **Future goal** — BOM + labour route good enough to write back to ERP (SDILive).

### The pivot — the key correction

The earlier design had the engine build a workbook from scratch and then a parity report compare the engine's self-computed estimate against the manual "Route & Bom" sheet. **This was abandoned.** The from-scratch build diverged from the estimators' own logic (a material total came out as £166 one way and £99.99 another — an internal contradiction).

The current design **populates the estimators' own template and lets it calculate.** There is only ever one material total — the workbook's own SUM — because we no longer run a parallel costing engine alongside it. The engine supplies high-quality *inputs*; the workbook does the maths, in the format the estimators already use.

**Consequence:** compute-then-parity is not the core loop any more. Parity against the manual sheet is now a *validation* check (does our populated output land near the manual number on a known job), not the mechanism the system is built around.

## Current state

The full estimate computes end-to-end through the estimators' workbook format. On the reference job **1282 (Milwaukee 500mm Wall Bay, order qty 180)** material and labour both populate and calculate, and unit cost / sell price flow through. The output lands close to the manual benchmark, with the residual gap attributable to assembly/finishing labour that isn't derivable from the drawings. It's in live testing with JR across a cross-section of drawing types.

Section status of the populated workbook: BOM ✅ working (tubes as catalogue sections, fixings, vinyl, electricals — all drawing-sourced); Sheet Steel ✅ working (parts cost from L×W×gauge); Wire ✅ correctly empty (tubes are catalogue-priced sections, not wire/rod); Other Sheet ⚠️ acrylic lens placed correctly but £0 material (no acrylic rate yet); Labour 🔧 populating & computing, coverage partial; Sell Price ✅ computes once labour is present.

## The labour block (the part most changed from the old picture)

The estimators' labour block runs rows 63–134 (widened from the original 40). Per row, the engine writes **three inputs**: operation name, qty, and **throughput / pieces-per-hour**. The **workbook** does the rest — it looks up the £/hour rate, department, and set-up minutes from its own rate table off the operation name, and computes hours and cost with its own formulas.

Throughput = `order_qty × qty_per_unit ÷ batch_hours[operation]`, which makes the workbook's formulas reproduce the engine's run-time cost (the workbook then adds its set-up allowance). Rate/dept/setup are **not** written by us — the workbook looks them up; we supply only operation + qty + throughput. Acrylic parts are mapped to the acrylic operation variants (Laser (Acrylic), etc.), and physically-impossible operations are filtered (no "fold" on tubes or acrylic).

## Recent focus (calibration, not mapping)

Strong areas: geometry, BOM structure, bought-ins, routing, totals. The remaining work is **calibration** — closing the gap between the engine's inputs and the estimators' reality:

- **Assembly / process labour** — make boxes, kit, palletise, fit electrics, shrink-wrap. Not on the drawings (process knowledge), so the engine doesn't produce them and the labour total runs low by roughly this amount. Main source of the manual gap.
- **Throughput artifacts** — where the engine's `batch_hours` is unrealistically small (e.g. fold), the back-calculated throughput comes out physically absurd (e.g. 10,810/hr) even though the cost lands roughly right. Fix identified (use realistic per-operation throughputs) — deferred.
- **Acrylic sheet rate** — the lens needs a real £/sheet rate from a verified source (SQL/catalogue, not LLM).
- **Tube-cutting labour** — tubes get powder/handling but no cut operation; missing.
- **Laser hole/internal-cut data** — empty for 1282, so laser time is profile-only (understates perforated parts); should improve on jobs with fuller DXF geometry.

## Provenance — worth being explicit

The estimate is now **drawing-sourced**, not read from the manual sheet. `wb_populate.py` reads only the run JSON's `part_estimates` (drawing-sourced). `main.py`'s old injection of a bought-in total from `job_bought_in_materials.json` (learned from Tim's manual sheet) is **inert** — the JSONs are renamed (`+OLD`/`_OLD`) so main.py skips them, and the DB tables the ingest wrote are never read back. A separate assembly-labour JSON is similarly parked.

## Key files in C:\ClaudeVision\src

| Area | Files |
|---|---|
| CLI entry | `main.py` |
| **Workbook populate — the current output path** | **`wb_populate.py`** |
| Estimating engine (produces inputs) | `estimator.py` |
| Old from-scratch builder (superseded, not the current path) | `xlsx_output.py` |
| Full parity (validation, not core loop) | `estimate_full_parity_report.py` |
| Sheet discovery | `estimate_sheet_discovery.py` |
| Pretty HTML report | `estimate_parity_pretty_report.py` |
| Config / policies | `config.py` |

## Not yet done (for the record)

`wb_populate.py` is still **standalone** — not yet wired into `main.py` to replace the old builder, so an engine run via `main.py` still produces the old output; the populate is run separately. Reconciling parity to the populated WB output is a later task.

## Open items that would genuinely sharpen things

Most of the earlier questions are already answered — the manual sheet layout (including exact cell formulas), the job types (sheet-metal display fixtures), and the reference job are all known. The genuinely useful open items are:

- **ERP write-back target** — what fields SDILive needs (part, route ops, costs, qty).
- **Acceptable variance** — the threshold at which AI is trusted over manual (tells us when to stop calibrating).
- **Throughput direction** — confirming realistic per-operation throughputs as the fix for the col-I artifacts.
