# Live Orders on Sage X3: from today's board to an SDI portal service with an AI layer

Written 19 Nov 2026. It covers how Live Orders moves from the Access extract to Sage X3 data, what we can do through the X3 UI before Acuity give development access, how it sits in the SDI portal, and where AI comes in.

**Rule:** each stage works on its own. Nothing waits for the next one.

## 1. What exists now

| Piece | File | What it does |
|---|---|---|
| Engine | `build_live_orders.py` | Works orders, material status (RAG), hours per work centre, weekly load, WO suggestions, exploded BOMs |
| **Data contract** | `SDI_Live_Orders_<date>.json` (written by the engine, schema `sdi.live_orders/1`) | One file with everything above. The dashboard, a portal endpoint and an AI agent all read this, whatever the source |
| Board | `SDI_Live_Orders_<date>.xlsx / .html` | Production's working sheet: Comments / Prog / Tube req carried week to week |
| **Dashboard** | `live_orders_dashboard.html` | The visual view: KPIs, works orders by due week and status, hours by week and shop, hours by work centre, bought-in material demand against supply, filterable works orders with exploded BOMs. Self-contained, works offline, read-only |
| Reconciliation | `reconcile_dave.py` | Production's sheet against Access, column by column, mapped to X3 |
| Web page | `live_orders_app.py` | Refresh from Access (read-only) or upload an extract, keeping every run |

The data contract is the key piece: **only the source changes**, from the Access extract to X3 exports to the X3 API. The engine output, dashboard, portal and agent stay the same.

## 2. Getting data in and out of X3 through the UI (no development access needed)

James is Super administrator on the training site (sdi-displays-trn, folder SDIMIG). Menu paths are from X3 v12 and **need checking on our site**: SaaS sites can hide or restrict functions.

| Need | X3 UI function | Automatable without development? |
|---|---|---|
| Read works orders, operations, materials, allocations, stock, PO / SO lines | **Enquiries** (Manufacturing / Stock / Purchasing / Sales → Enquiries) with **Excel / CSV export** on the right-hand panel | Manual: one click per enquiry |
| Ad-hoc queries over several tables | **Requester** (Usage → Requests → Requester) | A request can be saved and re-run; results export to Excel |
| Bulk export of a whole table set | **Exports** (Usage → Imports/exports → Exports) with an **export template** (Templates; standard ones exist for products, BOMs, routes, orders) | **Yes:** an export can run as a **recurring batch task** (Usage → Batch server → Recurring tasks), writing a file to a server volume every day / hour |
| Bulk load (estimating products / BOMs / routes; master data) | **Imports** (Usage → Imports/exports → Imports) with the import templates we already build for | **Yes:** an import can also run as a batch task from a file dropped in the import volume |
| Read the data model (real table / field names) | Development → Data and parameters → Tables (view only) | Look up once: MFGHEAD (WO header), MFGITM (WO products), MFGMAT (materials), MFGOPE (operations), STOCK, STOALL, PORDERQ, SORDERQ, ITMMASTER, BOMD, ROUOPE, WORKSTATIO |
| Visualise inside X3 | **Landing pages** with gadgets / vignettes (per-user home pages), standard **printouts** (Crystal), Sage's separate analytics product (licence) | Configurable per user. Not a substitute for Live Orders, but good for simple KPIs |
| Programmatic access | **Web services**: SOAP (classic), **REST / GraphQL** (current X3 API), all through a **connected application** (OAuth2) and an API user | Needs administration set-up: on our access list for Acuity. Check whether *Administration → … → Connected applications* is visible to James on the training site (look, don't create) |

**Safe now (read-only):** enquiries + export, Requester, viewing templates and the data dictionary.

**Training site only, agreed first:** creating an export template / recurring export; loading the estimating IMPORT test part (after Ethan's load, not during it, as he loads into the same SDIMIG folder).

**Never without sign-off:** anything in production; creating connected applications or users.

## 3. Stages

| Stage | Source | How it refreshes | Needs |
|---|---|---|---|
| **1. Now** | Access extract (`live_orders.sql`, read-only) | Run on demand; dashboard opens the `.json` | Nothing new |
| **2. After go-live, manual** | X3 enquiry / Requester exports (CSV) | Someone exports; the engine reads the CSVs (a new **X3 source adapter** maps them to the same grids) | Agree the export layouts on the training site |
| **3. Automated, still no API** | X3 **recurring export batch task** → file on a share | The portal backend picks up the newest file, builds the `.json`, and the dashboard refreshes | Batch-server rights and a shared export folder (Acuity / IT) |
| **4. Near real-time** | X3 **REST / GraphQL**, read-only | The portal backend queries X3 directly on demand | Connected app + API user + IP / rate limits (our access list, items 1–5) |
| **5. AI layer** | The data contract + the read-only API | See section 5 | Stage 3 or 4 |

## 4. In the SDI portal

The portal (`sdi-intelligence-backend/app.py` + `sdi-intelligence-portal.html`) is a FastAPI backend serving a single-page front end, with an API key and allowed file roots.

- **Backend:** one read-only endpoint, `GET /api/live-orders`. It returns the newest `SDI_Live_Orders_*.json` from the runs folder under the same `X-SDI-Key` check. Later (stage 3 / 4), it builds that file itself.
- **Front end:** one **Live Orders tile** that opens `live_orders_dashboard.html?data=/api/live-orders`, in a frame or as its own page.
- **Kept separate on purpose:** the portal files are James's working code (14 Nov: a branch checkout broke estimating). The dashboard and endpoint are built and tested beside the portal, and joined with a two-line change James makes when he's ready.

## 5. The AI layer (where the enterprise value is)

All of these read from the data contract; none needs write access to X3:

- **Daily exceptions briefing** (scheduled): red works orders due in the next two weeks and why; components short with nothing on order; weeks where a work centre is overloaded; sales orders with no works order (suggestions); overdue orders. Sent to Production / Purchasing each morning.
- **Ask Live Orders:** questions in plain English, such as "why is WO 12345 red?", "what do we need to buy to make next week's Metal work?", "which TTI orders are at risk?". Answered from the data, quoting the works orders and lines.
- **Draft actions, approved by a person:**
  - proposed PO lines for shortages (supplier from the product-supplier links, quantity from the shortfall);
  - re-schedule suggestions when a week is overloaded;
  - works-order suggestions for uncovered sales orders.

  They go into X3 **only** through the approved import files after sign-off: the same route as estimating.
- **Estimating → order → production:** the same pattern joins estimating (`est_to_x3.py`) to Live Orders. A won estimate becomes its product / BOM / route import, the works order follows, and it appears on Live Orders with its material status.

**Why it has to be in-house:** the agent's value is SDI's know-how (what Production look at on a Monday, how an estimate becomes a job), applied to SDI's data. That needs direct, governed data access, which is the access we've asked Acuity for.

## 5a. Built 20 Nov (without waiting for Acuity)

| Piece | File |
|---|---|
| Read-only API client: connected application, finds the URL / token form on the site, pulls data sets | `sagex3/integration/x3_api/x3_api.py` (README there) |
| X3 data → the engine's extract | `x3_source.py` + `x3_columns.json` (column map provisional until the first real pull) |
| One command, schedulable | `run_x3.py` → `SDI_X3_runs\latest.json` + `status.json` |
| Portal | `sdi-intelligence-backend/live_orders_routes.py` (`/api/live-orders/latest`, `/status`, `/dashboard`) |

Tested against a mock X3. Next: the connected application on the training site, then `probe`.

## 6. Next steps

1. **On James's PC, today:** re-run the board on the latest extract. It now also writes the `.json`. Open it in `live_orders_dashboard.html` and check it against Production's view.
2. **Training site (read-only):** export the works-order, materials, operations, stock and PO / SO enquiries once, so the stage 2 X3 source adapter can be written against real X3 layouts.
3. **Portal:** add `/api/live-orders` and the tile, when James is ready.
4. **Acuity:** batch-server rights for a recurring export (stage 3); a connected app and API user (stage 4). Both are already on the 17 Nov access list (SCRUM-329).
5. **AI:** the daily exceptions briefing first, as it needs nothing beyond the data contract.
