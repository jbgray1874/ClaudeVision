# SolidWorks tooling

Two scripts live here:

| script | purpose |
|--------|---------|
| `sw_native_analyse.py` | **production extractor.** Reads a job's models and writes `_sw_native_extract.json` — the input the estimating pipeline consumes. |
| `sw_discovery_probe.py` | one-off coverage probe (below) — answers *which* CAD data is actually populated, before committing to build against it. |

## Running the extractor, then the estimate

The extractor needs Windows + a licensed SolidWorks seat. The pipeline does **not** —
it only reads the JSON, so the estimate can run anywhere.

```powershell
# 1. On the SolidWorks machine — read the models (read-only, nothing is saved back)
C:\ClaudeVision\.venv\Scripts\python.exe tools\solidworks\sw_native_analyse.py `
    "K:\Estimating\...\12120 Digital Ticketing Bracket" `
    --out "C:\ClaudeVision\jobs\0359131\_sw_native_extract.json"

# 2. Run the estimate as normal — the extract is picked up automatically
C:\ClaudeVision\.venv\Scripts\python.exe -m src.main --job "C:\ClaudeVision\jobs\0359131"
```

**How the pipeline finds it.** `src/source_connectors/solidworks.py` is applied before
costing (Layer 0 of the source waterfall) and is *self-gating*: it fires when
`_sw_native_extract.json` is present in the job folder. No file, no effect — the job runs
on PDF + DXF exactly as before.

| variable | effect |
|----------|--------|
| `SDI_APPLY_SOLIDWORKS=0` | force off |
| `SDI_APPLY_SOLIDWORKS=1` | force on; says so loudly if the extract is missing |
| `SDI_SW_EXTRACT_JSON=<path>` | read the extract from an explicit path (models on a CAD share, job folder elsewhere) |
| `SDI_SW_RUN_ANALYSER=0` | never invoke COM; consume an existing extract only |

**You do not normally run this tool by hand.** When a job folder holds `.SLDPRT` / `.SLDASM`
and there is no extract — or the extract is older than the models — the estimate invokes the
analyser itself. It closes only the documents it opened; anything a designer already had open
is read in place, left open, and recorded in the manifest as `read_from_open_documents`.

That was not always so. The in-pipeline call was turned off in July to protect open documents
from a `close_all()` that closed everything it touched. The ownership fix removed that hazard
and the default was not restored, so jobs with models beside them were costed from PDF + DXF
for weeks. Run it by hand to diagnose, or on a machine where the estimate cannot reach
SolidWorks — not as a routine step.

**What it sets, and the rule for each** — all keyed on document type, stock form or
drawing convention, so every rule inherits to the next job:

- **Flat blank + sheet gauge + bend radius** from the sheet-metal cut list. Written only
  where the part is not already DXF-backed; where it is, the two blanks are compared and a
  disagreement over 10% by area is **flagged** (the DXF is kept).
- **Material** from the model's applied material. Fills a gap always. Overrides only where
  the family is wrong (metal ↔ non-metal). A same-family grade disagreement is flagged and
  the drawing value kept — the title block is what the shop buys to.
- **Bends** from the feature tree; where a Base Flange bakes its bends into the sketch the
  part is flagged as *formed, bend count unreadable* rather than silently counted as flat.
- **Quantities** from the full-depth assembly BOM.
- **Assemblies** are marked as parents so their material is never costed twice alongside
  their children (the GA double-count rule).
- **Imported supplier bodies** with no modelled fabrication are marked bought-in and take
  no fabrication route.
- **Flag, never zero.** If the model names a material but yields no blank, mass or section,
  the part is flagged as *cost not derivable* — a £0 line must never read as "free".

Every value written carries a `review_flags` entry naming SolidWorks as the source.

---

# SolidWorks discovery probe

Read-only tooling that answers one factual question before we build the
production connector (`src/source_connectors/solidworks.py`, see
[`docs/solidworks_integration_design.md`](../../docs/solidworks_integration_design.md)):

> For SDI's own drawings, **which** of the CAD capabilities the design note
> promises (material, gauge, bend count, flat pattern, holes, surface area,
> weldment cut list, assembly BOM) are actually populated in the files?

The answer decides Phase 1/2 scope on evidence, not assumption.

## What it does

`sw_discovery_probe.py` opens a batch of `.SLDPRT` / `.SLDASM` files **read-only**
over the full SolidWorks COM API (win32com), reads what it can from each, and
writes a JSON report plus a batch **coverage matrix** — for how many models was
each datum present.

- **Read-only, no writes.** Every document is opened with the Silent + ReadOnly
  flags and closed without saving. Mass-property/flat-pattern reads may rebuild
  in memory; that is discarded on close. Nothing is written back to any file.
- **Honest.** A field it cannot read is reported `null`, never guessed
  (NO MOCKING). Hole data is reported as a *signal* (feature counts), not a
  per-diameter enumeration — that needs the full-API geometry pass (Phase 2).

## Requirements

- Windows, with a licensed SolidWorks seat (the trial is fine — licence clock: **Aug 5**).
- `pip install pywin32` in the ClaudeVision venv.
- SolidWorks must have been run at least once so the `SldWorks.Application`
  COM ProgID resolves.

## Run it

```powershell
C:\ClaudeVision\.venv\Scripts\python.exe tools\solidworks\sw_discovery_probe.py `
    --path "C:\path\to\drawings" `
    --out  "C:\ClaudeVision\sw_probe_report.json"
```

Options:

| flag | meaning |
|------|---------|
| `--path` | folder (recursed) or a single model file; repeat for several roots |
| `--out` | report JSON path (default `sw_probe_report.json`) |
| `--limit N` | stop after N models — quick first look |
| `--visible` | run SolidWorks visibly (can be more robust on some installs) |
| `--no-mass` | skip mass properties (surface area/mass) for a fast metadata-only pass |

## Reading the output

The console prints the coverage matrix at the end; the full per-model detail is
in the JSON. High material / cut-list / surface-area coverage means Phase 1
(metadata + weldment cut lists) and area-based powder/acrylic pricing are worth
building now. Low saved flat-pattern / hole coverage means those need the
full-API compute path (Phase 2). Bring the report back here and we'll scope from it.
