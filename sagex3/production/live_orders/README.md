# Live Orders: the Python process (LO-00..05, Jira SCRUM-241)

How to re-create the two Live Orders workbooks sent to Acuity on 16 Nov, and how the process works.

| Workbook | Script | What it is |
|---|---|---|
| `SDI_Live_Orders_<date>.xlsx` (+ `.html`) | `build_live_orders.py` | **The board:** Production's Live Orders report, built from the data with nothing typed. This is the "example of the target" (attachment 3). |
| `SDI_Live_Orders_<date>.json` (19 Nov) | `build_live_orders.py` | **The data contract** (schema `sdi.live_orders/1`): the board's data as one file, for `live_orders_dashboard.html`, a portal endpoint and an AI agent. See `INTEGRATION_PLAN.md` |
| `LiveOrders_reconciliation_and_SageX3_mapping.xlsx` | `reconcile_dave.py` | **The reconciliation:** Production's own sheet compared with Access, column by column, and every column mapped to its Sage X3 template / field (attachment 1). |

Both are **read-only**: they read files and write workbooks. Nothing is written to Access or Sage X3.

**Proved (16 Nov):** re-running both commands in section 4 on the original inputs gives the same workbooks as were sent: every tab, every row. The only differences are Findings wording that is now generated rather than typed (no fixed dates in the text).

## 1. Files

```
sagex3/
  production/live_orders/
    live_orders.sql          read-only extract from Access (the day's transactions)
    build_live_orders.py     the board (library function build() + command line)
    reconcile_dave.py        the reconciliation against Production's sheet (command line)
    live_orders_app.py       a small web page: Refresh from Access / upload, keeps every run (optional)
    README.md                this file
  migration/rebuild/
    common.py                X3 code rule (product_code)
    work_centres.csv         Access department -> X3 work centre (LASM -> MMAC002, FOLD -> MMAC001, ...)
```

Keep this layout: the scripts find `common.py` and `work_centres.csv` by relative path. `runs/` is gitignored (it holds customer names).

## 2. Requirements

- **Python 3.10+** and **openpyxl** (`pip install openpyxl`).
- **pyodbc** only for the web page's "Refresh from Access".
- **SQL Server Management Studio**, or the web page, to run `live_orders.sql`.

## 3. Inputs

| Input | Where it comes from | Used by |
|---|---|---|
| **Extract** (the transactions) | Run `live_orders.sql` in SSMS against SDILive. Set *Results to file*, tab-delimited, no headers, and save the `.rpt`. The migration's `extract_transactions.txt` has the same grids and works too. Grids: CHECK (as-at time), WOR (open works orders, `ASC_WOR_TBL`, status blank), SOH (open SO lines, `migration.vw_SOH_V2`), POH (open PO lines, `vw_POH_V2`), SMR (stock, `vw_SMR_V2`). | both |
| **Products** | Migration `ZSDIITM_products_MAPPED.xlsx`, sheet "Data with Headings" | both |
| **BOMs** | Migration `YA00408BOM_boms_MAPPED.txt` | both |
| **Routes** | Migration `ZSDIROU2_routes_MAPPED.txt` | both |
| Costs (optional) | Migration `YITC_product_costs_MAPPED.txt`: material cost on the exploded BOMs | board |
| Production's sheet | Dave's `Live_Orders.xlsx` (the Crystal export, edited by hand) | reconciliation; and the board's `--dave` / `--carry` |
| Last week's sheet (optional) | Production's last sheet, or last week's board after Production have typed on it | board `--carry` |

Because the master data is the migration's X3 files, codes and work centres are already X3's. After go-live, only the extract changes (an X3 export or the API).

**Use the extract nearest the date of Production's sheet** for the reconciliation, otherwise orders made or rescheduled in between show as differences.

## 4. Re-creating the two workbooks sent on 16 Nov

**Safest way to run it: no git at all.** Unzip `SDI_Live_Orders_python.zip` into its own new folder (e.g. `C:\SDI_LiveOrders`), and the master files into `C:\X3_inputs`. That folder shares nothing with `C:\ClaudeVision` or the estimating code. Never check this branch out in `C:\ClaudeVision`.

PowerShell:

```
cd C:\SDI_LiveOrders\production\live_orders
$IN = "C:\X3_inputs"
$M = @("--products", "$IN\ZSDIITM_products_MAPPED.xlsx", "--boms", "$IN\YA00408BOM_boms_MAPPED.txt", "--routes", "$IN\ZSDIROU2_routes_MAPPED.txt")
```

The master files used on 16 Nov were the 4 Nov pm mapped set, with Ethan's 5 Nov fixes for products and routes.

**a) The reconciliation** (Production's sheet of 26 Oct against the 4 Nov extract):

```
python reconcile_dave.py "$IN\Live_Orders.xlsx" "$IN\extract_transactions.txt" LiveOrders_reconciliation_and_SageX3_mapping.xlsx @M
```

It prints the score per column:

```
sheet 220 rows, compared 102, not open 118
  Part code: 102/102   Due date: 76/102   SO Num: 98/102   REV: 20/102   QTY: 102/102
  Booked in: 98/102    Balance: 98/102    Metal / Joinery / Acrylics: 63/102   Dept hours: 14/102
```

(Dept hours 14/102 is per works order, all work centres within tolerance. Per work-centre line it's 297 of 334, as reported in Findings.)

**b) The board** (13 Nov extract, with costs, Production's notes carried forward, and the check against Dave's sheet):

```
python build_live_orders.py "$IN\live_orders_2026-11-13.rpt" out @M --costs "$IN\YITC_product_costs_MAPPED.txt" --dave "$IN\Live_Orders.xlsx" --carry "$IN\Live_Orders.xlsx"
```

This writes `out\SDI_Live_Orders_2026-11-13.xlsx` and `.html`, and prints a summary (703 works orders still to make; 169 green, 261 amber, 273 red; 8,125 hours; 118 WO suggestions; 45 rows with Production's notes carried).

The options:

| Option | Effect |
|---|---|
| `--costs <YITC .txt>` | Material cost per line and per works order on Exploded BOMs |
| `--dave <sheet .xlsx>` | Adds the "Check against Dave" tab |
| `--carry <last week .xlsx>` | Copies Comments, Prog, Tube req and Production's material note onto the same works order, so there's no Monday copy-over |
| `--suggest-lead-days 14` | Suggested start = SO date − this many days |

From Python (to embed in a portal): `build_live_orders.build(extract, out_dir, products, boms, routes, dave=None, lead_days=14, costs_path=None, carry=None)` returns `meta` (the counts above), `files`, `wos` (every works order with its lines, hours, status) and `wcnames`.

## 5. How the board works it out (`build_live_orders.py`)

- **Works orders:** every open Access works order with something left to make. Balance = (amended, or else ordered) − made (good quantity). Sub-assemblies (`/` in the WO number) are their own rows.
- **Part code:** the X3 code rule from `common.product_code` (upper case; spaces, `&`, `( )` removed; `. / _` → `-`). Drawing = the code without its customer prefix.
- **Customer date:** from the works order's sales order. The SO line for the same part is used, else any line on that order. One date shows the date; no open line gives "SO not open"; several dates give "Check SO dates".
- **Material status** (rule to agree with Production, LO-01):
  1. Each works order needs BOM link qty × balance of every component.
  2. Stock is shared out to works orders in **due-date order**, earliest first.
  3. A shortage is covered by open **PO lines** (earliest first), then by **works orders** for made components.
  4. **GREEN** means everything is in stock. **AMBER** means covered by a PO / WO due on or before the works order's due date, or a call-off material still to call off. **RED** means short with nothing due in time, or no BOM in X3.
  5. The call-off list is provisional: SHEETMETAL, POWDER, PACK, PALLET, WIRE, CARRIAGE.

  Access holds no allocations we can read, so the sharing-out is the board's own. In X3, the works order's allocations replace it.
- **Metal / Joinery / Acrylics:** from the route's work centres (first letter M / J / A).
- **Hours still to do per work centre:** route run minutes × balance ÷ 60, plus set-up if nothing has been made yet. Columns are labelled with Production's department names via `work_centres.csv`.
- **Work-centre load:** those hours by week of the due date. Overdue orders count in this week.
- **WO Suggestions:** open SO lines for made parts (has a BOM or route, or category FGML) not covered by stock or works orders. Suggested start = SO date − lead days. Red where the part has no BOM or route. SO lines due more than 60 days ago go on Checks, not Suggestions.
- **Exploded BOMs:** every works order's BOM at all levels (up to 8) × balance, against stock, on PO, first PO due date, on WO, has BOM / route, department, and material cost. **The part code on Live Orders links to its works order's first BOM row** (Dave's "game changer").
- **Checks:** works orders with no route or with a part missing from the X3 product file; old open SO lines.

**Tabs:** Read me, Live Orders, Work-centre load, WO Suggestions, Exploded BOMs, Check against Dave (with `--dave`), Checks. The `.html` file is the same board for a browser.

## 6. How the reconciliation works (`reconcile_dave.py`)

1. It runs `build_live_orders.build()` on the extract, so Access is read exactly as the board reads it.
2. It reads Production's sheet: the first tab, headings in row 1, department columns S to AO.
3. For each works order on the sheet (by **WO Num**):
   - **If it isn't open in Access**, the row goes to **Not open** (made or closed since the sheet was saved).
   - **Otherwise each column is compared:**

     | Column | Same when |
     |---|---|
     | Part code | the sheet's code, after the X3 code rule, equals Access's |
     | Due date | equals the WO scheduled date |
     | SO Num | equal, ignoring leading zeros; "Stock" or blank = no sales order |
     | REV | equal, ignoring case |
     | QTY, Booked in, Balance | equal numbers |
     | Metal / Joinery / Acrylics | the set of Y's equals the route's shops |
     | Dept hours | the sheet's departments, summed onto X3 work centres via `work_centres.csv`, are each within max(0.05 h, 2%) of the route hours |
4. It writes the workbook:
   - **Read me:** the sheet (creator, last saved by / when, rows), the extract's as-at time, and the counts.
   - **Findings:** generated from the comparison: what agrees, what differs and why, and the gaps to Sage X3 as loaded.
   - **Column map:** every column of the sheet: meaning, Access source, how it's worked out, X3 template / field, whether it reaches X3 (green loaded / yellow partly / red gap), and its reconciliation score. The mapping text is the `COLUMNS` list at the top of the script.
   - **By works order:** the sheet's value, the Access value and ✓ / ✗ for each column, plus the typed material status against the board's.
   - **Dept hours:** sheet hours against route hours per works order and work centre.
   - **Not open.**

## 7. Web page (`live_orders_app.py`, optional)

```
set SDI_SQL_CONN=DRIVER={ODBC Driver 17 for SQL Server};SERVER=<server>;DATABASE=SDILive;Trusted_Connection=yes;ApplicationIntent=ReadOnly
set LO_PRODUCTS=...ZSDIITM_products_MAPPED.xlsx   set LO_BOMS=...YA00408BOM_boms_MAPPED.txt   set LO_ROUTES=...ZSDIROU2_routes_MAPPED.txt
set LO_COSTS=...YITC_product_costs_MAPPED.txt     (optional)
set LO_CARRY=<last week's sheet .xlsx>            (optional)
set LO_DAVE=<Production's sheet .xlsx>            (optional)
python live_orders_app.py                          -> http://localhost:8767
```

- **Refresh** runs `live_orders.sql` read-only through pyodbc. Without a connection, upload a saved `.rpt` / `.txt` instead.
- Every run is kept in `runs/`.
- There's no login, so keep it inside SDI.

## 8. Open points

- **The material-status rule and call-off list** are to agree with Production (LO-01).
- **For Acuity** (16 Nov email, questions 1–12):
  - whether Sage X3 provides this report as standard;
  - the migration-load gaps: operations already done, the WO → SO link, the Access WO number, and made-to-date in YA004MFG.
- **Dave's REV check:** which drawing folder to compare the revision against.
