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

A pack whose drawing is missing is **NOT TESTED** (exit 2). `tests/acceptance/` fails on that
unless `SDI_REPLAY_ALLOW_MISSING=1`, which only GitHub CI sets.
