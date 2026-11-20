# Estimate → Sage X3 converter (EST-10, Jira SCRUM-210)

This is how the converter works and how to embed it in the estimating portal.

## 1. What it does

`est_to_x3.py` reads **one estimate workbook** exactly as the estimator saved it. There's no macro and no copy and paste. It writes the **Sage X3 import files** in the same templates and format as the data-migration files (`;`-separated, cp850, CRLF):

| File | X3 template | When |
|---|---|---|
| `<part>_ZSDIITM.txt` / `.xlsx` | ZSDIITM: the product | **Always** (20 Nov, James). If the part is already in X3, X3 rejects that line on import (expected) |
| `<part>_YA00408BOM.txt` / `.xlsx` | YA00408BOM: the bill of materials | Always |
| `<part>_ZSDIROU2.txt` / `.xlsx` | ZSDIROU2: the route | Always |
| `<part>_CHECKS.xlsx` | – | Always: Notes (result), Checks, BOM read, Route read |

- The `.txt` files are what X3 loads (Usage → Imports, TEST first: ZSDIITM, then BOM, then route).
- The `.xlsx` files are the same data, for people to read.
- **Nothing is written into Sage X3.** Stage 2 sends the files through the X3 API once Acuity provide API access.

**Proved (13 and 16 Nov):** on Tim's Gift Card Header estimate (rev B), the route is identical to Access's route for the same part, and the BOM has the same 8 components. Re-running on the original `.xls` gives byte-identical files.

## 1a. In the SDI Intelligence portal: Estimate → X3 (20 Nov 2026)

The portal has an **Estimate → X3** page (menu, under Live Orders):
1. Drop an estimate (.xls or .xlsx) and press **Generate the X3 files**.
2. The page shows **READY TO LOAD / NOT READY**, the counts, and the same views as the workbook: Estimate → X3 (every cell, where it lands, how it's worked out), BOM file, Route file, Product file, Checks.
3. Download the **write-up workbook** (`<part>_estimate_to_SageX3.xlsx`, modelled on the 16 Nov write-up of Tim's Gift Card Header) and, once READY, the three load files (or a zip), with the load order.
4. Every run is kept (EST_RUNS): click an earlier run to see it again.

How it hangs together:
- `est_x3_page.html` (the page) → `sdi-intelligence-backend/estimating_routes.py` (`/api/estimate-x3`, portal key) → `est_run.py` (a subprocess, with the portal's `EST_PYTHON`) → `est_to_x3.build()` + `est_workbook.write()`.
- **Product list = Sage X3's own:** the newest `products.json` from the X3 pull (`X3_EXPORT_DIR`, refreshed daily by Live Orders), or `EST_PRODUCTS`. The migration ZSDIITM file still works.
- **Old .xls:** read with **xlrd** (`python -s -m pip install xlrd`), no LibreOffice needed; LibreOffice is the fallback. Tested byte-identical on Tim's estimate.
- Installed by `add_live_orders_to_portal.py` (with Live Orders) and, on the server, `deploy_live_orders_server.ps1`.
- Nothing is written to Sage X3. Loading is still by hand in Usage → Imports (TEST first); the automatic load needs a write-capable X3 connection (next stage).

## 2. Files and folder layout

Keep this layout. The converter finds `common.py` and `work_centres.csv` by relative path.

```
sagex3/
  estimating/
    est_to_x3.py        the converter (library function + command line)
    est_app.py          a small web page around it (optional)
    README.md           this file
  migration/rebuild/
    common.py           shared rules: X3 code rule (product_code), X3 file writer (write_load), workbook helpers
    work_centres.csv    Access department -> X3 work centre (LASM -> MMAC002, FOLD -> MMAC001, ...)
```

## 3. Requirements

- **Python 3.10+** and **openpyxl** (`pip install openpyxl`).
- **LibreOffice** (`soffice` on the PATH), only for old `.xls` estimates. The converter turns a `.xls` into `.xlsx` in a temp folder (values kept). A `.xlsx` estimate doesn't need it. On Windows, add `C:\Program Files\LibreOffice\program` to the PATH.
- **The current X3 product list.** Use the latest ZSDIITM product file from the migration (`ZSDIITM_products_MAPPED.xlsx`, sheet "Data with Headings"), or an X3 product export in the same layout. It's used:
  - to check every component exists;
  - to see if the part already exists;
  - to find the sheet-steel product by gauge and size, from Description 2 / 3, e.g. "2500 x 1250 x 1.5mm CR4".

  Refresh it from X3 regularly (Acuity question B13: a scheduled product export).

## 4. Three ways to run it

### a) Library call (best for embedding in the portal)

```python
import sys
sys.path.insert(0, r"C:\ClaudeVision_X3\sagex3\estimating")
import est_to_x3

res = est_to_x3.build(
    est_path=r"C:\uploads\<estimate>.xls",
    out_dir=r"C:\portal\runs\20261116-0905_<part>",
    products_path=r"C:\portal\master\ZSDIITM_products_MAPPED.xlsx",
    parent=None,             # override the part code (e.g. "IMPORT"); None = take it from the estimate
    category="FGML",         # X3 category for a NEW part
    rev_in_code=False,       # IMPORT layout only: put the revision in the part code
    sheet_material="CR4",    # material assumed for sheet steel (template has no material column)
)
```

`build()` returns a dict:

```python
{
  "code":  "XX-0000001",        # X3 part code
  "new":   False,               # True = ZSDIITM written (part not in X3)
  "bom":   8,                   # BOM lines written
  "ops":   9,                   # route operations written
  "stop":  0,                   # STOP checks: if > 0 the result is NOT READY - do not load
  "warn":  0,                   # WARN checks: load allowed, but someone should look
  "files": ["XX-0000001_YA00408BOM.xlsx", "XX-0000001_ZSDIROU2.xlsx"],
  "checks": [["INFO", "H38", "Sheet 2500 x 1250 x 1.5mm CR4 -> SHEETMETAL11", "..."], ...]
}
```

- The `.txt` load files sit next to the `.xlsx` files in `out_dir`, with the same stem.
- **Raises `SystemExit("…")`** when there's no part code at all (no A63 / E5 and no `parent`). Catch it and show the message.
- **Files are still written when `stop > 0`,** so the user can see what was read. The portal must show **NOT READY** and must not offer them for loading.

### b) Command line

```
cd C:\ClaudeVision_X3\sagex3\estimating
python est_to_x3.py "<estimate.xls>" <out_dir> --products "<ZSDIITM_products_MAPPED.xlsx>" [--parent CODE] [--category FGML] [--rev-in-code] [--sheet-material CR4]
```

It prints, for example, `XX-0000001 (existing): BOM 8 lines, route 9 ops, 0 stop, 0 warn -> ...`, followed by any WARN / STOP lines.

### c) Web page (`est_app.py`)

```
set EST_PRODUCTS=C:\portal\master\ZSDIITM_products_MAPPED.xlsx
set EST_RUNS=C:\portal\est_runs          (optional; default estimating\runs)
python est_app.py                       -> http://localhost:8766
python est_app.py --host 0.0.0.0        -> on the SDI network (no login - keep it inside SDI)
```

| Route | What |
|---|---|
| `GET /` | Upload form, plus the list of past runs |
| `POST /run` | multipart/form-data. Fields: `estimate` (file, required), `products` (file, optional: a newer product list for this run), `parent`, `category`, `sheet_material`, `rev_in_code`. Redirects (303) to `/run/<id>`. |
| `GET /run/<id>` | READY / NOT READY, every check by cell, the BOM and route read, load order, download links |
| `GET /run/<id>/file/<name>` | One output file |
| `GET /run/<id>/zip` | All output files as a zip |

Every run is kept in `EST_RUNS/<timestamp>_<name>/` (the estimate, `out/`, `run.json`).

## 5. Embedding in the estimating portal (recommended)

1. **On "Send to Sage X3 (TEST)"** in the portal, save the uploaded estimate to a run folder and call `est_to_x3.build(...)` as in 4a. Run it in a worker or background task: a `.xls` conversion takes a few seconds.
2. **Show the result:**
   - `READY` if `stop == 0` (with a count of any WARN), else `NOT READY`;
   - the `checks` list as a table (level, estimate cell, check, detail);
   - the BOM and route read, from `<part>_CHECKS.xlsx` "BOM read" / "Route read", or from the `.xlsx` load files.
3. **Offer the `.txt` files** (and a zip) only when `stop == 0`. Show the load order: ZSDIITM, then YA00408BOM, then ZSDIROU2. When `new` is False, say *"part already in X3 – its ZSDIITM line will be rejected on import (expected); BOM and route load onto it"*.
4. **Keep every run:** the estimate, outputs, `run.json` with `res`, who ran it and when. That gives the audit trail.
5. **Stage 2 (later):** replace the download with a call to the X3 API (or submit to the X3 import folder). That needs Acuity's connected-app client ID / secret and an integration user (questions A1–A2, B14).
6. **Keep the product list current:** point `products_path` at the newest ZSDIITM file or the scheduled X3 product export.

## 6. What it reads from the estimate

The layout is detected automatically. The **estimators' template** has `H10 = "Part code"`, sheet **"Estimate"**:

| Estimate | Becomes |
|---|---|
| **A63** part code (first labour line) | X3 product code. Code rule: upper case; spaces, `&`, `( )`, CHAR(160) removed; `. / _` → `-`. So `A&B-0000001` → `AB-0000001`. |
| D4 description, D5 drawing, G5 rev | Product description / Description 2. These are only written if the part is new. |
| D6 quantity, G6 unit cost, M59 material, M103 labour | Shown on Notes only; **not loaded** (costs: Acuity question B10) |
| **Rows 11–25** standard materials: H code, K qty per unit, L scrap | BOM line: component H, link qty K. Scrap is **not loaded**, because the X3 template has no scrap column. |
| **Rows 28–35** wire: H code (gauge table), K qty | BOM line |
| **Rows 38–48** sheet steel: E parts, H gauge, I × J sheet, K parts per sheet | The X3 sheet is found by (I, J, H) + material (CR4 default). Link qty = E ÷ K. Rows on the same sheet are **added**. |
| **Rows 51–58** other sheet: C description, D qty, J per sheet | Code is taken from the description's first word (**WARN**: the template has no code column) |
| **Rows 63–102** labour: C operation, D description, G Access dept, H qty/unit, I rate/hour, L set-up | Route operation 5, 10, 15…: work centre = `work_centres.csv[G]`, set-up = L, **run minutes/unit = 60 ÷ I × H**, routing 10, site S01A, time unit 2 (minutes) |

**Dave's IMPORT layout** (IMPORT.xls, with the X3 columns: component B/I, link qty C, X3 work centre R, run minutes Q) is recognised and read too. Its part code is the drawing number in E5, and the revision is in H5.

## 7. Checks (`checks` list / CHECKS.xlsx)

| Level | Examples | Effect |
|---|---|---|
| STOP | component not in X3; no X3 sheet for that size / gauge / material; Access department with no X3 work centre (e.g. OVEN); quantity 0; no part code | `stop > 0` → **NOT READY**, don't load |
| WARN | component marked "DONT USE" in X3; other-sheet code taken from a description | Load allowed; someone should look |
| INFO | code rule applied; sheet picked (with the other materials available); scrap not carried; repeated component quantities added; part new or existing | For information |

## 8. Open points (affect the rules, not the code)

- **Sheet material:** the template has no material column, so CR4 is assumed. Asked of Tim / Dave.
- **Codes:** other-sheet codes, wire gauges with no code, and FIXING49 ("DONT USE") are with Dave / James Ryan.
- **Acuity:**
  - what re-importing a BOM / route for an existing part does (B6);
  - whether a product-site record is needed for a new part (B7);
  - whether costs should load (B10);
  - API access (A1–A2, B14).
- **Dave's import macros:** not yet seen (IMPORT.xls has none). Asked for, as a cross-check that no step is missed.
