# SDI Monday2Friday

Account and delivery workspace inside SDI Intelligence: the account director's
tracker becomes shared records that the director, AM, PM and Finance screens
all read. Design brief: the 12-screen workspace mock-up and the migration
review (held outside the repo: they contain client data).

## What is built so far

| Piece | File | What it does |
| --- | --- | --- |
| Tracker importer | `sdi-intelligence-backend/m2f/tracker_import.py` | Reads the tracker workbook into projects, dated forecast lines, accounts, brands and people, with an issue for anything it cannot read with certainty |
| Database schema | `sdi-intelligence-backend/m2f/schema_m2f.sql` | `m2f` schema on SDILive: people, accounts, projects, forecast lines, freezes, budgets, variations, activities, plus import staging |
| Staging loader | `sdi-intelligence-backend/m2f/db_load.py` | Writes an import batch, its rows and its issues to the staging tables |
| Tests | `sdi-intelligence-backend/tests/test_m2f_*.py` | Synthetic workbook fixture; set `M2F_TRACKER` to also check a real tracker |

## Running it

```
cd sdi-intelligence-backend
python -m m2f.tracker_import "<tracker.xlsx>" --out ..\output\m2f   (read only, writes JSON)
python -m m2f.db_load --schema                                       (create the m2f tables)
python -m m2f.db_load "<tracker.xlsx>"                               (import into staging)
python -m pytest tests -q
```

Output goes under `output/`, which git ignores. Credit limits are left out of
every export unless `--include-sensitive` is passed.

## How the importer reads the tracker

No value is invented. Anything ambiguous keeps its raw text and raises an issue
with a severity: `decision` (needs Kayleigh), `check` (needs a look) or `info`.

- **Months get their year from the tab's own `FYnn` headers**, walking the month
  sequence either side. `Jan FY27` is January 2027; the "Forcasting Total"
  sheet confirms this, and the reconciliation checks every label.
- **Status comes from each tab's colour legend.** Cell and legend colours are
  compared as the colour Excel shows, with theme colours resolved through the
  workbook theme. A colour that is not on the legend stays unclassified.
- **Sub-accounts come from the row ranges the totals sheet sums** for BUK,
  Sigma, BOPS and Hearingcare, never from fixed row numbers.
- **Every column is kept.** Mapped columns go to `fields`; the rest go to
  `extra` under their header, so nothing in the tracker is lost.
- **Reconciliation** re-adds each monthly total on the totals sheet from the
  imported lines, and checks each tab's total row for values it leaves out.
  Against the current tracker, every formula total matches to the penny or
  differs by exactly an amount typed as text.

## Source keys are not permanent IDs

Projects carry the review's key (tab code + row, e.g. `BUK-004`) so decisions
in the migration review can be traced. Those keys shift whenever a row is
inserted: one inserted row already moved every later Boots row by one since
the review was built. Decisions must be matched by tab and project name, and
permanent IDs are issued by the database on promotion from staging.

## Decisions pending (owner: Kayleigh)

1. Status mapping: do Confirmed and TBC mean PO received and Awaiting PO?
2. Which hidden rows are archive and which are live.
3. AM owner per account and project; who `KT` is; whether the Chloe in the PM
   column is the Beauty AM.
4. Which FY27 budget figure is correct (the monthly plan and the split by
   account disagree).
5. Projects named only by an order number need a recognisable name.
6. Rows the importer flags as sitting outside a total or a sub-account range.

## Next

1. Promotion from staging to live tables once the decisions are recorded.
2. API router (`m2f_routes.py`) behind the existing `X-SDI-Key` gate, with
   write methods enabled deliberately (the backend currently allows GET only).
3. Director dashboard, AM workspace and PM overview in the portal.
4. Forecast freeze and the weekly review; variations register.
5. Phase 2: Sage X3 reads (PO, sales order, invoice status) and Debbie's
   Finance queue.
