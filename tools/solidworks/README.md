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
