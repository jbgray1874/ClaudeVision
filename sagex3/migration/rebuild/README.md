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
| `common.py`: code rule, character rule, readers and writers, sheet tabs, one copy each | done |
| `changes.py`: the what-changed write-up | done; tested on the 30 Oct cost change (9,597 → 15,562) |
| `sql/00_discover.sql`: full view definitions and the Access product-table columns | written; a cross-check only now, since the product extract uses columns already proven |
| `sql/extract_products.sql` + `products.py`: ZSDIITM with live products in, already-loaded products kept, the PHANT usage test, live shared codes flagged, and Check, Not migrated, Held back and Why tabs | **done; first live run 4 Nov:** 19,868 products (+3,369, 0 removed) |
| `run.py` | done for products; each builder joins it as it's written |
| `costs.py`: YITC, a cost line for every product (loaded costs kept; new products costed from Access) | **done 4 Nov**, tested |
| `product_suppliers.py`: ZSDIITMSUP, every supplier pair with a PIO priority (input: `product_suppliers_v4.sql`) | **done 4 Nov**, tested: 7,603 main + 3,147 alternatives |
| BOMs, routes | next (the extract carries the BOM lines and line ids) |
| Customers, suppliers, banks, delivery addresses | after that |
| Stock, orders, open items, works orders | last; already close to repeatable via `views_v2.sql` |

## Product rule (rule 1a)

A product goes in if any of these holds:
- it holds stock;
- it's on an open sales, purchase or works order;
- it was sold, bought or made in the last two years (`--recent-years`);
- it's graded GOOD or INCOMPLETE, the rule the loaded file was built on;
- it's a component, at any depth, of a BOM that goes in.

Every other Access product is on "Not migrated", with its grade and last activity. If a stocked
or ordered product, or a needed BOM component, would be left out, the run stops.

The X3 code is decided once, over every code Access holds. A product coming into the file later
can't change the code of one already loaded.
