# SolidWorks tooling

The scripts that matter here:

| script | purpose |
|--------|---------|
| `sw_native_analyse.py` | **production extractor.** Reads a job's models and writes `_sw_native_extract.json` — the input the estimating pipeline consumes. |
| `sw_docmgr_analyse.py` | **backup reader** (SCRUM-184). Reads the same files through the SOLIDWORKS Document Manager when the extractor above cannot run, and writes `_sw_docmgr_extract.json` in the same schema. Saved values only — see *The Document Manager backup reader* below. |
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
| `SDI_SW_FLATTEN=0` | do not flatten-and-measure a formed part with no cut-list blank (default **on**) |
| `SDI_SW_DOCMGR=1` | when an extract is needed and the COM analyser cannot run (switched off, no SolidWorks on the machine, or its run failed), read the models with the Document Manager backup reader instead; and read the files SolidWorks failed on partway through a run (D-706). Default **off** |
| `SDI_SW_DOCMGR_KEY` | the SOLIDWORKS Document Manager licence key the backup reader needs. Set it in the machine's environment; it is never printed, logged, written to an extract or put on a command line |
| `SDI_SW_TURN_WAIT_MINUTES` | how long a run waits for the desktop's one SolidWorks while another run on the machine reads its models (D-731). Default **30**. At the limit the run reads its models with the Document Manager (`SDI_SW_TURN_TIMEOUT=docmgr`, the default, with the key set) or goes on without them (`none`); it is never stopped |
| `SDI_SERVICE_RUN_ID`, `SDI_SUBMITTED_SCOPE`, `SDI_CLAIMED_BY_RUNNER` | **set by the runner for the engine, never by hand**: the portal's run id, the scope as submitted and the runner's id. The run holding SolidWorks writes them beside the lock, so every waiting run, and the wall monitor, can say which job has the licence (D-738) |

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

## The Document Manager backup reader

`sw_docmgr_analyse.py` reads `.SLDPRT`, `.SLDASM` and `.SLDDRW` through the SOLIDWORKS
Document Manager API (`SwDocumentMgr.SwDMClassFactory`): Windows and the Document Manager
library, no running SolidWorks and no seat, only a licence key in `SDI_SW_DOCMGR_KEY`.

**When it runs.** Only with `SDI_SW_DOCMGR=1`, only when the job's model folder holds models
and has no fresh extract, and only when the COM analyser cannot run — `SDI_SW_RUN_ANALYSER=0`,
no SolidWorks registered on the machine, or the analyser run failed. With the switch off
nothing about the SolidWorks layer changes. Its extract is written as `_sw_docmgr_extract.json`
beside `_sw_native_extract.json`, never over it, so the next run still tries the worker first.

**Partway through a run (D-706).** SolidWorks can read some files and not others: a seat that
drops out mid-batch, a model open in a designer's session, a file it will not open. The worker
still exits zero with what it reached. With `SDI_SW_DOCMGR=1`, the files it opened and got
nothing from (an error and no title) are read by the backup in the same run, with
`--only-from <list>`, into `_sw_docmgr_topup.json`. Their records replace the failures; every
file SolidWorks read keeps its values; the worker's extract is left as it wrote it, so a healthy
seat reads those files next time. A file SolidWorks read in part keeps the worker's values. The
summary names the files as `docmgr_topped_up`, and anything neither reader could open as
`docmgr_still_unread`.

**Opened is not read; unknown is not no (D-714).** An assembly whose components the library
cannot hand back is a FAILED read, with the reason as its error, never an assembly with no
parts; a sub-assembly that cannot be read fails its parent the same way. A part whose cut list
cannot be read keeps sheet metal and bends UNKNOWN (null, not false and 0) and is flagged
`needs_solidworks_worker`. A thickness that is only a linked property's saved value is said and
not taken unless a sheet-metal cut list stands behind it. `--trace` prints, per file, what each
call into the library answered.

**Checking it against SolidWorks (D-710, SCRUM-184 acceptance).** Run by hand, the reader
takes its key from the engine's `.env` (a key already set in the shell wins), so nothing else
needs setting:

```powershell
.\.venv\Scripts\python.exe tools\solidworks\sw_docmgr_analyse.py "<model folder>" --out "$env:TEMP\docmgr_check.json"
.\.venv\Scripts\python.exe tools\solidworks\compare_extracts.py "<model folder>\_sw_native_extract.json" "$env:TEMP\docmgr_check.json"
```

Use a folder that holds the `.SLDPRT` / `.SLDASM` files themselves, and read the SAME folder
with both readers, so the two extracts describe the same files. A staged pack of PDFs and DXFs
has nothing for either reader. With SolidWorks on the machine, the worker's read of that folder
is:

```powershell
.\.venv\Scripts\python.exe tools\solidworks\sw_native_analyse.py "<model folder>" --out "$env:TEMP\sw_check.json"
```

`compare_extracts.py` lists parts only one reader found, every file either reader failed on with
its error, and any material, thickness, flat blank, bends, cut length, mass or assembly
quantity that disagrees. A value the file never saved is counted as *not saved*, not as a
difference. It refuses (exit 2) when either read has no file read successfully: two empty
extracts agree on everything and prove nothing (D-710a). It writes nothing.

**Is this machine ready?** `tools\start\check-runner-host.ps1` prints whether SolidWorks and the
Document Manager are registered, whether Excel is installed, and the names (never the values) of
the settings above. Read-only.

**What it reads.** Custom properties (file and active configuration), the configurations,
the assembly's components with their quantities (sub-assemblies walked, suppressed components
skipped), external references, BOM tables saved in a drawing, and the sheet-metal and weldment
cut lists *as last saved* — flat blank, thickness, bends, cut length, cut-outs, a weldment
member's section.

**What it cannot read, and what happens instead.** It never rebuilds a model, so it measures
nothing: no bounding box, volume or surface area, and a mass or flat pattern only where the
file saved one. Each is left empty and named on the part as *not saved in the file; needs the
SolidWorks worker* — never inferred. A formed sheet-metal part whose file saved no flat
pattern is flagged `needs_solidworks_worker` with a manufacturing question; no blank is taken
from the model for it, and with no DXF the job carries a BLOCKING `native_extract_from_docmgr`
violation until the worker or a DXF measures it.

**Where its values rank.** They enter as `solidworks_docmgr` (rank 76), below `solidworks_api`
(90) and below a DXF (80, and 95 for gauge), so they fill gaps and never displace either. A
saved flat that disagrees with a part's DXF does not replace it: the DXF is kept and the part
is marked unreconciled. A material linked to the library's SW-Material enters as
`solidworks_docmgr_applied_material` (67), below the drawing's own callout.

**What it records.** Every record carries `"reader": "solidworks_docmgr"`; the job meta
carries `extract_reader`, `docmgr_backup_reason`, `docmgr_not_saved` and
`docmgr_needs_worker`, and the estimate summary repeats them.

**By hand, to diagnose** (the key must already be in the environment):

```powershell
.\.venv\Scripts\python.exe tools\solidworks\sw_docmgr_analyse.py "$pack" --out "C:\ClaudeVision\work\docmgr_extract.json"
"exit=$LASTEXITCODE"
```

The exit codes mean what they mean for the production extractor (table below). Several
Document Manager calls could not be exercised when the reader was written; each is isolated
in one function in its *COM SEAM* section, marked UNVERIFIED, for a first check on a Windows
machine.

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

## What the SolidWorks path can and cannot do

Measured from the code, not from the API documentation — these are this engine's limits, and
several of them are ours rather than SolidWorks'.

| Limit | Value | Consequence |
|---|---|---|
| Analyser timeout, in-pipeline | **30 minutes** | A folder large enough to exceed it is killed and reported as a failed run. 41 models is comfortable; several hundred is not. |
| COM attach | same integrity level only | An elevated console cannot take a SolidWorks a designer already has open. With SolidWorks **closed**, an elevated run starts its own instance and works. |
| Instances | one | The analyser never `Quit()`s SolidWorks and never closes a document it did not open. |
| Flat-blank window | **1 – 2500 mm** | Outside it the model's blank is refused and the part falls back to DXF or drawing. Now flagged; it used to be silent. |
| Thickness window | **0.3 – 50 mm** | Same treatment. |
| Flatten | **off unless `--flatten`** | A formed part with no cut-list blank is *not* flattened in memory by an automatic run. Hand runs can ask for it. |
| `.DWG` | not read | Convert with the ODA File Converter first; the geometry is the same, the container is not. |
| `.IGES` / `.STEP` | geometry only | Never a BOM source: no part numbers, no quantities, no material. |
| Bent tube | envelope only | The bounding box is the envelope, not the developed length. |

**Precedence, strongest first.** `.SLDASM` for part numbers, quantities, material and
configuration; `.SLDPRT` for material, thickness, mass and sheet-metal features; `.SLDDRW`
for released BOM tables and callouts; then DXF flat patterns, then PDF notes.

## Commands

Everything below runs at `C:\ClaudeVision`. **Elevated or not does not matter** provided
SolidWorks is closed and the job share is visible from whichever console you use — check with
`Test-Path`. Do not switch consoles to fix something: a drive mapped in one token is invisible
from the other, so moving from a working prompt is how a path that plainly exists stops being
readable.

**Normal path — nothing to type.** With models in the job folder and no fresh extract, the
estimate runs the analyser itself:

```powershell
$pack = "K:\Estimating\Completed\AI Estimating\Live Enquiry\11650-00-GAFragranceCoffret"
Test-Path $pack
.\run-packs.ps1 "${pack}:45" -Deliverables
```

**By hand, to diagnose.** Quote the paths — the folders contain spaces:

```powershell
$pack    = "K:\Estimating\Completed\AI Estimating\Live Enquiry\11650-00-GAFragranceCoffret"
$extract = "C:\ClaudeVision\work\11650_sw_native_extract.json"
New-Item -ItemType Directory -Force -Path (Split-Path $extract) | Out-Null

.\.venv\Scripts\python.exe tools\solidworks\sw_native_analyse.py "$pack" --out "$extract"
"exit=$LASTEXITCODE"
Get-Item $extract | Select-Object FullName, Length, LastWriteTime
```

**Feed a hand-made extract to an estimate:**

```powershell
$env:SDI_SW_EXTRACT_JSON = $extract
.\run-packs.ps1 "${pack}:45" -Deliverables
Remove-Item Env:\SDI_SW_EXTRACT_JSON     # or it follows you onto the next job
```

**Flatten formed parts that have no cut-list blank** (slower; opens and restores each model
in memory, saving nothing):

```powershell
.\.venv\Scripts\python.exe tools\solidworks\sw_native_analyse.py "$pack" --out "$extract" --flatten
```

**Turn native acquisition off** on a shared designer workstation:

```powershell
$env:SDI_SW_RUN_ANALYSER = "0"
```

### Reading the exit code

| `$LASTEXITCODE` | Meaning |
|---|---|
| `0` | At least one model was read. Check `COVERAGE:` for how many failed. |
| `1` | Every file failed, **or** the models changed on disk mid-run. The written extract is not usable — read the console. |
| `2` | Bad command line — usually an unset `$pack` or `$extract`, or a missing `--out` value. SolidWorks was never reached. |

### When it reads nothing

The message names which kind of nothing it found. `No SolidWorks files ANALYSED under:`
followed by an exclusion list means the models are in a folder whose name contains `archive`,
`old`, `wip`, `temp`, `prev`, `bak` or similar — move them, or point the analyser at the
subfolder that holds them.
