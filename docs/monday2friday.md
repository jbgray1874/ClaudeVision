# SDI Monday2Friday

Account and delivery workspace inside SDI Intelligence: the account director's
tracker becomes shared records that the director, AM, PM and Finance screens
all read. Design brief: the 12-screen workspace mock-up and the migration
review (held outside the repo: they contain client data).

## What is built so far

The pilot app runs at `/m2f` on the SDI Intelligence service, with its user
guide at `/m2f/guide` and architecture at `/m2f/architecture` (buttons on the
app's header and on the portal dashboard). During the pilot the tracker stays
the source of truth: the app re-reads it whenever it is saved, and keeps
freezes, movement notes, variations, answers and owners in a small SQLite
pilot store.

| Piece | File | What it does |
| --- | --- | --- |
| Web app | `sdi-intelligence-backend/m2f/web/index.html` | Director dashboard, weekly review, variations, accounts, AM workspace, PM overview, projects, questions for Kayleigh, settings |
| Guide and architecture | `sdi-intelligence-backend/m2f/web/guide.html`, `architecture.html` | User guide and architecture pages |
| API | `sdi-intelligence-backend/m2f_routes.py` | `/api/m2f/*` behind the `X-SDI-Key` gate; mounted in `app.py` |
| Workspace | `sdi-intelligence-backend/m2f/service.py` | Builds every view from the tracker; pilot store for freezes, notes, variations, answers, owners |
| Tracker importer | `sdi-intelligence-backend/m2f/tracker_import.py` | Reads the tracker workbook into projects, dated forecast lines, accounts, brands and people, with an issue for anything it cannot read with certainty |
| Database schema | `sdi-intelligence-backend/m2f/schema_m2f.sql` | `m2f` schema on SDILive: people, accounts, projects, forecast lines, freezes, budgets, variations, activities, plus import staging |
| Staging loader | `sdi-intelligence-backend/m2f/db_load.py` | Writes an import batch, its rows and its issues to the staging tables |
| Tests | `sdi-intelligence-backend/tests/test_m2f_*.py` | Synthetic workbook fixture; set `M2F_TRACKER` to also check a real tracker |

## Deploying the pilot

1. Pull this branch into the backend folder (laptop or server).
2. Add `M2F_TRACKER_PATH` (UNC path to the tracker) and `M2F_DATA_DIR` to `.env`
   (see `config.example.env`).
3. Restart the service: `Restart-Service SDIIntelligence` (admin PowerShell),
   or `python app.py` on a laptop.
4. Open `http://sdi-intelligence.sdi.local:8071/m2f` (server) or
   `http://localhost:8071/m2f` (laptop) and check Settings and data.

## Running the pieces directly

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

1. Kayleigh answers the open questions in the app (Questions for Kayleigh).
2. Promotion from staging into the SDILive `m2f` schema, carrying the pilot
   store across; people then update Monday2Friday instead of the tracker.
3. Budget against forecast, project CPA templates, holiday cover.
4. Phase 2: Sage X3 reads (PO, sales order, invoice status), Debbie's Finance
   queue, team capacity with BrightHR leave.
5. Phase 3: Sage X3 writes with confirmation, WhatsApp brief, meeting notes.
