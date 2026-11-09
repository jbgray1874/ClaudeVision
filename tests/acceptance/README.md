# Acceptance packs: the deterministic reader against the original drawings (SCRUM-194)

One folder per pack under `packs/<pack>/`:

- `expected_facts.json`, committed: what the drawing prints, drafted from its pages with the page
  named per fact, then checked by the reviewer (`reviewed_by`). Never copied from a previous
  estimate. `strict: {fact: false}` marks a fact that is reported but not yet asserted.
- the original drawing, **never committed** (`*.pdf`). Put it beside the facts file on the
  laptop, or point `SDI_ACCEPTANCE_PACKS` at a folder holding `<pack>/<drawing>.pdf`.

Run one pack, or all:

    python tools/acceptance/deterministic_pack_check.py 0358141
    python tools/acceptance/deterministic_pack_check.py --all --mode pdf-only

`--mode deterministic` turns every model reader off and leaves the deterministic BOM reader,
DXF flat patterns and SolidWorks extract on. `--mode pdf-only` turns those off too. The report
names which readers ran. Reports land in `output/acceptance/`.

What a pass means: every strict fact was **extracted and linked** to its part at the scan stage.
It does not mean charged. Requirement 2, the retention trace, takes the costed `_record.json`
and the workbook and gives each finding its disposition: used, covered elsewhere, superseded or
excluded with a reason, or unresolved, with the row named.

With a costed run the same rows are also held to their charge, on the reviewer's format
(Finding | Expected | Reader result | Costing/workbook result | Verdict), with the drawing's
sha256, the test mode and the build on the header:

    python tools/acceptance/deterministic_pack_check.py 0358141 --record <job>_record.json --xlsx <book.xlsx>

Every costing-critical fact is strict: a missing blank FAILS the reading, it is never advisory.
A fixture-backed run (the PDF present) is the evidence; the suite's run with
`SDI_REPLAY_ALLOW_MISSING=1` skips a missing drawing as NOT TESTED and is not that evidence.

The reader's findings are captured page by page at scan, before the build can merge, filter or
drop them (`reader_findings`, on the record), and the trace follows each one: finding -> built
record -> costed record -> workbook cell, with a finding no part was given listed as UNASSIGNED.
A record without captured findings says NOT APPLICABLE; nothing is reconstructed.

Requirement 3: the gaps the deterministic read left are asked one at a time (`gap_fill`, on the
record): one question per gap on the part's own pages, the answer checked against the sheet's
own readings, written as `llm_assisted`. A deterministic-only run asks nothing and names each
gap; an LLM recovery never turns the deterministic reading test into a pass.

Requirement 2 runs on a saved run, never on the scan:

    python tools/acceptance/retention_trace.py --record <job>_record.json [--xlsx <book.xlsx>]

It takes the record's `drawing_ledger` (captured once the deterministic build is done, before
costing) and holds every stated fact to the calculated workbook: charged, covered, excluded,
unresolved; a quantity, material, size or section carried or corrected by a named source. An
engine allowance beside the drawing's facts is priced and named, not a hold; a purchase or a
commercial line is listed; a made part with a sheet the read gave no fact holds. A record with
no calculated read-back is **NOT TESTED**. The same audit runs in `main` after Excel
(`drawing_charge_result`) and the release invariant `drawing_*` holds on an unresolved item.

A pack whose drawing is missing is **NOT TESTED** (exit 2). `tests/acceptance/` fails on that
unless `SDI_REPLAY_ALLOW_MISSING=1`, which only GitHub CI sets.
