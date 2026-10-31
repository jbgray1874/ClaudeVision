# Rebuild kit: every Sage X3 load file, from Access, at any time

The goal: one set of read-only extract queries and one set of scripts that rebuild **every** mapped
spreadsheet from current Access data, cleanly and completely. Each run comes with a write-up of
what changed since the last one. It replaces the chain of one-off V6 → V7 → V8 scripts in
`../scripts`, which depend on files uploaded during the project.

The rules it follows are in the runbook (`../SDI_X3_Migration_Runbook.md`), especially:
- **1a, no exclusions by assumption:** every live record goes across, with the best value Access
  has; anything left out is on an agreed rule and listed.
- **1b, complete files only:** every file is the whole file, built from scratch; no top-ups.
- **0, SDILive is production:** the extract only reads Access. Our own `migration` objects are
  the only things a script may change, and the kit aims to need none.

## How a run will work

1. Run `sql/extract_*.sql` on SDILive. Each is read-only, with temporary tables at most. Save each
   one with Results To File, tab-delimited, into a new folder for the run, e.g. `runs/2026-12-31/extract/`.
2. `python run.py runs/2026-12-31 --previous runs/2026-11-20`, which:
   - builds every mapped spreadsheet into `runs/2026-12-31/out/`;
   - runs the section 9 checks and stops on a silent drop;
   - writes `WHAT_CHANGED.md` and `What_changed.xlsx` against the previous run (`changes.py`).
3. Load the files in the order of runbook section 2.

Settings that change per run (dates, company) are passed in, not edited in code:
`--stock-date 20261231 --accounting-date 20261231 --company S01A`.

## Status (31 Oct)

| Part | State |
|---|---|
| `common.py`: code rule, character rule, readers and writers, one copy each | done |
| `changes.py`: the what-changed write-up | done, tested on the 30 Oct cost change (9,597 → 15,562) |
| `sql/00_discover.sql`: full view definitions and the Access product-table columns | written; waiting on its output |
| `sql/extract_products.sql` + `products.py`: ZSDIITM, with live products in, the PHANT usage test and costs for every product | next, once the discovery output is back |
| BOMs, routes, costs, product-suppliers | after products |
| Customers, suppliers, banks, delivery addresses | after that |
| Stock, orders, open items, works orders | last; already close to repeatable via `views_v2.sql` |
| `run.py` | as the builders arrive |
